"""Full-rate protocol-v2 parser, typed decode, and formula throughput gate."""

from __future__ import annotations

import json
import math
import os
import platform
import random
import time
import unittest
from dataclasses import dataclass
from functools import lru_cache
from statistics import median

from thingdaq import (
    ADCBlock,
    AuxBankMode,
    DAQConfiguration,
    FrameFlag,
    FrameKind,
    GPIOBlock,
    ParserCounters,
    RateProfile,
    ReaderCounters,
    Source,
    StreamMask,
    SyntheticStreamValidator,
    decode_message,
    synthetic_adc_payload,
    synthetic_gpio_payload,
)
from thingdaq._generated import protocol_v2_constants as constants
from thingdaq.protocol_v2 import (
    IncrementalCompatibleFrameParser,
    encode_v2_frame,
)

CORPUS_SECONDS = 1.025
REQUIRED_HEADROOM_RATIO = 1.25
FULL_RATE_CONFIGURATION = DAQConfiguration(
    stream_mask=StreamMask.ADC | StreamMask.GPIO,
    source=Source.SYNTHETIC,
    aux_bank_mode=AuxBankMode.INPUT,
    rate_profile=RateProfile.ADC_1MHZ_GPIO_4MHZ,
)
FULL_RATE_LAYOUT = FULL_RATE_CONFIGURATION.gpio_layout
FULL_RATE_TIMING = FULL_RATE_CONFIGURATION.rate_timing
FULL_RATE_COVERAGE_TICKS = FULL_RATE_TIMING.frame_coverage_ticks(AuxBankMode.INPUT)
TARGET_PAYLOAD_BYTES_PER_SECOND = (
    FULL_RATE_TIMING.adc_pair_rate_hz * constants.ADC_BYTES_PER_PAIR
    + FULL_RATE_TIMING.gpio_sample_rate_hz * FULL_RATE_LAYOUT.item_bytes
)
TARGET_FRAMED_BYTES_PER_SECOND = (
    (FULL_RATE_LAYOUT.adc_total_frame_bytes + FULL_RATE_LAYOUT.total_frame_bytes)
    * constants.TIMESTAMP_HZ
    / FULL_RATE_COVERAGE_TICKS
)
EMPTY_READER_COUNTERS = ReaderCounters(
    bytes_read=0,
    read_calls=0,
    frames_received=0,
    responses_matched=0,
    late_responses=0,
    request_timeouts=0,
    queue_wait_timeouts=0,
    host_block_queue_drops=0,
    host_event_queue_drops=0,
    stale_blocks_discarded=0,
    boundary_blocks_discarded=0,
    protocol_failures=0,
    disconnects=0,
    pending_requests=0,
    queued_blocks=0,
    queued_events=0,
)
EMPTY_PARSER_COUNTERS = ParserCounters(0, 0, 0, 0, 0, 0, 0, 0, 0, 0)


@dataclass(frozen=True, slots=True)
class _Corpus:
    wire: bytes
    coverage_count: int
    logical_seconds: float


@lru_cache(maxsize=1)
def _full_rate_corpus() -> _Corpus:
    coverage_count = math.ceil(
        CORPUS_SECONDS * constants.TIMESTAMP_HZ / FULL_RATE_COVERAGE_TICKS
    )
    wire = bytearray()
    run_id = 0xA016_0001
    for sequence in range(coverage_count):
        flags = FrameFlag.SYNTHETIC
        if sequence == 0:
            flags |= FrameFlag.EPOCH_START
        first_ticks = sequence * FULL_RATE_COVERAGE_TICKS
        wire.extend(
            encode_v2_frame(
                FrameKind.ADC_DATA,
                synthetic_adc_payload(
                    sequence * FULL_RATE_LAYOUT.adc_items_per_frame,
                    FULL_RATE_LAYOUT.adc_items_per_frame,
                ),
                flags=flags,
                run_id=run_id,
                sequence=sequence,
                first_sample_ticks=first_ticks,
                item_count=FULL_RATE_LAYOUT.adc_items_per_frame,
            )
        )
        wire.extend(
            encode_v2_frame(
                FrameKind.GPIO_DATA,
                synthetic_gpio_payload(
                    sequence * FULL_RATE_LAYOUT.items_per_frame,
                    FULL_RATE_LAYOUT.items_per_frame,
                    aux_bank_mode=AuxBankMode.INPUT,
                ),
                flags=flags,
                run_id=run_id,
                sequence=sequence,
                first_sample_ticks=first_ticks,
                item_count=FULL_RATE_LAYOUT.items_per_frame,
            )
        )
    return _Corpus(
        wire=bytes(wire),
        coverage_count=coverage_count,
        logical_seconds=(
            coverage_count * FULL_RATE_COVERAGE_TICKS / constants.TIMESTAMP_HZ
        ),
    )


def _chunk_ranges(
    length: int,
    *,
    seed: int,
    maximum_chunk: int,
) -> tuple[tuple[int, int], ...]:
    randomizer = random.Random(seed)
    ranges: list[tuple[int, int]] = []
    offset = 0
    while offset < length:
        chunk_size = randomizer.randint(1, min(maximum_chunk, length - offset))
        ranges.append((offset, offset + chunk_size))
        offset += chunk_size
    return tuple(ranges)


def _consume(
    corpus: _Corpus,
    ranges: tuple[tuple[int, int], ...],
) -> tuple[SyntheticStreamValidator, ParserCounters]:
    parser = IncrementalCompatibleFrameParser()
    validator = SyntheticStreamValidator(
        0xA016_0001,
        StreamMask.ADC | StreamMask.GPIO,
        reader_baseline=EMPTY_READER_COUNTERS,
        parser_baseline=EMPTY_PARSER_COUNTERS,
    )
    wire_view = memoryview(corpus.wire)
    try:
        for start, end in ranges:
            chunk = wire_view[start:end]
            try:
                frames = parser.feed(chunk)
            finally:
                chunk.release()
            for frame in frames:
                message = decode_message(
                    frame,
                    configuration=FULL_RATE_CONFIGURATION,
                )
                if not isinstance(message, (ADCBlock, GPIOBlock)):
                    raise TypeError("full-rate corpus emitted a non-data frame")
                validator.validate(message)
    finally:
        wire_view.release()
    return validator, parser.counters


class AuxiliaryInputParserThroughputTests(unittest.TestCase):
    def test_full_combined_parser_decode_and_formula_validation_headroom(
        self,
    ) -> None:
        corpus = _full_rate_corpus()
        profiles = (
            ("large-random", 0xA016_B001, 64 * 1024),
            ("usb-random", 0xA016_B002, 16 * 1024),
            ("short-random", 0xA016_B003, 1_024),
        )
        samples: list[dict[str, float | int | str]] = []

        for name, seed, maximum_chunk in profiles:
            ranges = _chunk_ranges(
                len(corpus.wire),
                seed=seed,
                maximum_chunk=maximum_chunk,
            )
            wall_started = time.perf_counter()
            process_started = time.process_time()
            validator, counters = _consume(corpus, ranges)
            process_seconds = time.process_time() - process_started
            elapsed_seconds = time.perf_counter() - wall_started
            framed_rate = len(corpus.wire) / elapsed_seconds
            self.assertEqual(corpus.coverage_count, validator.adc_frames_validated)
            self.assertEqual(corpus.coverage_count, validator.gpio_frames_validated)
            self.assertEqual(2 * corpus.coverage_count, counters.frames_decoded)
            self.assertEqual(0, counters.corruption_events)
            self.assertEqual(0, counters.buffered_bytes)
            self.assertLessEqual(
                counters.high_water_mark,
                IncrementalCompatibleFrameParser.max_buffered_bytes,
            )
            samples.append(
                {
                    "profile": name,
                    "seed": seed,
                    "maximum_chunk_bytes": maximum_chunk,
                    "elapsed_seconds": elapsed_seconds,
                    "process_seconds": process_seconds,
                    "framed_bytes_per_second": framed_rate,
                    "headroom_ratio": framed_rate / TARGET_FRAMED_BYTES_PER_SECOND,
                    "parser_high_water_bytes": counters.high_water_mark,
                }
            )

        headrooms = [float(sample["headroom_ratio"]) for sample in samples]
        report = {
            "schema": "thingdaq-aux-input-host-benchmark-v1",
            "python_implementation": platform.python_implementation(),
            "python_version": platform.python_version(),
            "platform": platform.platform(),
            "machine": platform.machine(),
            "processor": platform.processor() or "unknown",
            "cpu_count": os.cpu_count(),
            "target_payload_bytes_per_second": TARGET_PAYLOAD_BYTES_PER_SECOND,
            "target_framed_bytes_per_second": TARGET_FRAMED_BYTES_PER_SECOND,
            "required_headroom_ratio": REQUIRED_HEADROOM_RATIO,
            "logical_stream_seconds": corpus.logical_seconds,
            "data_wire_bytes": len(corpus.wire),
            "minimum_headroom_ratio": min(headrooms),
            "median_headroom_ratio": median(headrooms),
            "maximum_headroom_ratio": max(headrooms),
            "physical_usb_acceptance": False,
            "target_runtime_acceptance": False,
            "samples": samples,
        }
        serialized_report = json.dumps(report, sort_keys=True)
        print(f"AUX_INPUT_PYTHON_BENCHMARK {serialized_report}")

        self.assertEqual(12_000_000, TARGET_PAYLOAD_BYTES_PER_SECOND)
        self.assertAlmostEqual(12_189_723.320158103, TARGET_FRAMED_BYTES_PER_SECOND)
        self.assertGreater(corpus.logical_seconds, 1.0)
        self.assertGreaterEqual(
            min(headrooms),
            REQUIRED_HEADROOM_RATIO,
            serialized_report,
        )


if __name__ == "__main__":  # pragma: no cover
    unittest.main()
