"""Sustained correctness, loss-accounting, and performance stream tests."""

from __future__ import annotations

import gc
import json
import math
import os
import platform
import random
import time
import tracemalloc
import unittest
from dataclasses import dataclass
from functools import lru_cache
from itertools import islice
from statistics import median

from thingdone_daq import (
    ADCBlock,
    AdcConverter,
    CommandResponse,
    DeviceState,
    GPIOBlock,
    IncrementalFrameParser,
    InMemoryTransport,
    ReaderCounters,
    SimulatedDevice,
    Status,
    StreamMask,
    SyntheticStreamValidator,
    ThingDAQ,
    decode_frame,
    decode_message,
    encode_frame,
    run_synthetic_soak,
    synthetic_adc0_code,
    synthetic_adc1_code,
    synthetic_adc_payload,
    synthetic_gpio_byte,
    synthetic_gpio_payload,
)
from thingdone_daq._generated import protocol_constants as constants
from thingdone_daq.protocol import ParserCounters

TARGET_FRAMED_BYTES_PER_SECOND = (
    2
    * constants.DATA_FRAME_BYTES
    * constants.TIMESTAMP_HZ
    / constants.FRAME_COVERAGE_TICKS
)
TARGET_PAYLOAD_BYTES_PER_SECOND = (
    2
    * constants.ADC_DATA_PAYLOAD_SIZE
    * constants.TIMESTAMP_HZ
    / constants.FRAME_COVERAGE_TICKS
)
PACED_TEST_SECONDS = 2.05
CORPUS_SECONDS_PER_RUN = 1.025
STATUS_EVERY_COVERAGES = 97
REQUIRED_BENCHMARK_HEADROOM = 1.25

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
class _RunSpec:
    run_id: int
    coverage_count: int
    stats_generation: int


@dataclass(frozen=True, slots=True)
class _WireCorpus:
    wire: bytes
    runs: tuple[_RunSpec, ...]
    data_frame_count: int
    data_wire_bytes: int
    response_count: int
    logical_seconds: float


@dataclass(frozen=True, slots=True)
class _CorpusResult:
    adc_frames: int
    gpio_frames: int
    status_responses: int
    parser: ParserCounters


class _RandomChunkPacedTransport(InMemoryTransport):
    """Paced simulator transport with seeded, varying stream read boundaries."""

    def __init__(self, *, rate_multiplier: float, seed: int) -> None:
        frame_interval = constants.DATA_FRAME_BYTES / (
            TARGET_FRAMED_BYTES_PER_SECOND * rate_multiplier
        )
        super().__init__(
            stream_interval=frame_interval,
            demand_driven=False,
            max_pending_bytes=128 * 1024,
        )
        self._randomizer = random.Random(seed)
        self.nonempty_reads = 0
        self.partial_frame_reads = 0
        self.minimum_read_bytes = constants.UINT32_MAX
        self.maximum_read_bytes = 0

    def readinto(self, buffer: bytearray | memoryview) -> int:
        self._read_chunk_size = self._randomizer.randint(
            1,
            min(len(buffer), 16 * 1024),
        )
        received = super().readinto(buffer)
        if received:
            self.nonempty_reads += 1
            self.minimum_read_bytes = min(self.minimum_read_bytes, received)
            self.maximum_read_bytes = max(self.maximum_read_bytes, received)
            if received < constants.DATA_FRAME_BYTES:
                self.partial_frame_reads += 1
        return received


class _FirmwareDropDevice(SimulatedDevice):
    """Report one firmware-side ADC loss without overflowing the host queue."""

    def __init__(self) -> None:
        super().__init__()
        self._recorded_drop = False

    def next_data_frame(self) -> bytes | None:
        wire = super().next_data_frame()
        if wire is None or self._recorded_drop:
            return wire
        if decode_frame(wire).header.kind is constants.FrameKind.ADC_DATA:
            self._adc_items_dropped += constants.ADC_PAIRS_PER_FRAME
            self._recorded_drop = True
        return wire


def _status_wire(
    *,
    run_id: int,
    request_id: int,
    stats_generation: int,
    adc_frames: int,
    gpio_frames: int,
    final: bool,
) -> bytes:
    status = Status(
        device_state=DeviceState.IDLE if final else DeviceState.RUNNING,
        stream_mask=StreamMask.NONE if final else StreamMask.ADC | StreamMask.GPIO,
        source=constants.Source.SYNTHETIC,
        data_checksum_algorithm=constants.DEFAULT_CHECKSUM_ALGORITHM,
        adc_frames_emitted=adc_frames,
        gpio_frames_emitted=gpio_frames,
        stats_generation=stats_generation,
    )
    return encode_frame(
        constants.FrameKind.GET_STATUS_RESPONSE,
        status.to_payload(),
        run_id=run_id,
        request_id=request_id,
    )


@lru_cache(maxsize=1)
def _multirun_wire_corpus() -> _WireCorpus:
    coverage_count = math.ceil(
        CORPUS_SECONDS_PER_RUN * constants.TIMESTAMP_HZ / constants.FRAME_COVERAGE_TICKS
    )
    runs = (
        _RunSpec(0xDA04_0001, coverage_count, 101),
        _RunSpec(0xDA04_0002, coverage_count, 102),
    )
    wire = bytearray()
    request_id = 1
    response_count = 0

    for run in runs:
        for sequence in range(run.coverage_count):
            flags = constants.FrameFlag.SYNTHETIC
            if sequence == 0:
                flags |= constants.FrameFlag.EPOCH_START
            first_ticks = sequence * constants.FRAME_COVERAGE_TICKS
            wire.extend(
                encode_frame(
                    constants.FrameKind.ADC_DATA,
                    synthetic_adc_payload(sequence * constants.ADC_PAIRS_PER_FRAME),
                    flags=flags,
                    run_id=run.run_id,
                    sequence=sequence,
                    first_sample_ticks=first_ticks,
                    item_count=constants.ADC_PAIRS_PER_FRAME,
                )
            )
            wire.extend(
                encode_frame(
                    constants.FrameKind.GPIO_DATA,
                    synthetic_gpio_payload(sequence * constants.GPIO_SAMPLES_PER_FRAME),
                    flags=flags,
                    run_id=run.run_id,
                    sequence=sequence,
                    first_sample_ticks=first_ticks,
                    item_count=constants.GPIO_SAMPLES_PER_FRAME,
                )
            )
            emitted = sequence + 1
            if emitted % STATUS_EVERY_COVERAGES == 0:
                wire.extend(
                    _status_wire(
                        run_id=run.run_id,
                        request_id=request_id,
                        stats_generation=run.stats_generation,
                        adc_frames=emitted,
                        gpio_frames=emitted,
                        final=False,
                    )
                )
                request_id += 1
                response_count += 1

        wire.extend(
            _status_wire(
                run_id=run.run_id,
                request_id=request_id,
                stats_generation=run.stats_generation,
                adc_frames=run.coverage_count,
                gpio_frames=run.coverage_count,
                final=True,
            )
        )
        request_id += 1
        response_count += 1

    data_frame_count = 2 * sum(run.coverage_count for run in runs)
    return _WireCorpus(
        wire=bytes(wire),
        runs=runs,
        data_frame_count=data_frame_count,
        data_wire_bytes=data_frame_count * constants.DATA_FRAME_BYTES,
        response_count=response_count,
        logical_seconds=(
            sum(run.coverage_count for run in runs)
            * constants.FRAME_COVERAGE_TICKS
            / constants.TIMESTAMP_HZ
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


def _check_boundary_layout(block: ADCBlock | GPIOBlock) -> None:
    if isinstance(block, ADCBlock):
        first_index = block.first_pair_index
        last_index = first_index + block.item_count - 1
        if block.pair(0) != (
            synthetic_adc0_code(first_index),
            synthetic_adc1_code(first_index),
        ):
            raise AssertionError("ADC first pair disagrees with its global index")
        if block.pair(-1) != (
            synthetic_adc0_code(last_index),
            synthetic_adc1_code(last_index),
        ):
            raise AssertionError("ADC last pair disagrees with its global index")
        samples = tuple(islice(block.interleaved(), 4))
        expected = (
            (0, AdcConverter.ADC0, synthetic_adc0_code(first_index), 0),
            (
                0,
                AdcConverter.ADC1,
                synthetic_adc1_code(first_index),
                constants.ADC1_PHASE_TICKS,
            ),
            (
                1,
                AdcConverter.ADC0,
                synthetic_adc0_code(first_index + 1),
                constants.ADC_PAIR_PERIOD_TICKS,
            ),
            (
                1,
                AdcConverter.ADC1,
                synthetic_adc1_code(first_index + 1),
                constants.ADC_PAIR_PERIOD_TICKS + constants.ADC1_PHASE_TICKS,
            ),
        )
        observed = tuple(
            (
                sample.pair_index,
                sample.converter,
                sample.code,
                sample.timestamp_ticks - block.first_sample_ticks,
            )
            for sample in samples
        )
        if observed != expected:
            raise AssertionError("ADC interleaving or four-tick phase is incorrect")
        return

    first_index = block.first_sample_index
    last_index = first_index + block.item_count - 1
    if block.sample(0) != synthetic_gpio_byte(first_index):
        raise AssertionError("GPIO first value disagrees with its global index")
    if block.sample(-1) != synthetic_gpio_byte(last_index):
        raise AssertionError("GPIO last value disagrees with its global index")
    first_value = synthetic_gpio_byte(first_index)
    observed_pins = tuple(block.channel(pin)[0] for pin in constants.GPIO_PINS_BY_BIT)
    expected_pins = tuple(bool(first_value & (1 << bit)) for bit in range(8))
    if observed_pins != expected_pins:
        raise AssertionError("GPIO D6-through-D13 bit order is incorrect")


def _consume_corpus(
    corpus: _WireCorpus,
    *,
    seed: int,
    maximum_chunk: int,
    check_boundary_layouts: bool,
) -> _CorpusResult:
    parser = IncrementalFrameParser()
    validators = {
        run.run_id: SyntheticStreamValidator(
            run.run_id,
            StreamMask.ADC | StreamMask.GPIO,
            reader_baseline=EMPTY_READER_COUNTERS,
            parser_baseline=EMPTY_PARSER_COUNTERS,
        )
        for run in corpus.runs
    }
    specs = {run.run_id: run for run in corpus.runs}
    counts = {run.run_id: [0, 0] for run in corpus.runs}
    final_status_runs: set[int] = set()
    status_responses = 0
    previous_request_id = 0
    wire_view = memoryview(corpus.wire)
    try:
        ranges = _chunk_ranges(
            len(corpus.wire),
            seed=seed,
            maximum_chunk=maximum_chunk,
        )
        for start, end in ranges:
            chunk = wire_view[start:end]
            try:
                frames = parser.feed(chunk)
            finally:
                chunk.release()
            for frame in frames:
                message = decode_message(frame)
                if isinstance(message, (ADCBlock, GPIOBlock)):
                    spec = specs.get(message.run_id)
                    if spec is None:
                        raise AssertionError(f"unexpected data run {message.run_id}")
                    validators[message.run_id].validate(message)
                    is_adc = isinstance(message, ADCBlock)
                    counts[message.run_id][0 if is_adc else 1] += 1
                    expected_epoch_start = message.sequence == 0
                    observed_epoch_start = bool(
                        message.flags & constants.FrameFlag.EPOCH_START
                    )
                    if observed_epoch_start != expected_epoch_start:
                        raise AssertionError("EPOCH_START does not mark one run start")
                    if check_boundary_layouts and message.sequence in {
                        0,
                        spec.coverage_count - 1,
                    }:
                        _check_boundary_layout(message)
                    continue

                if not isinstance(message, CommandResponse):
                    raise TypeError(f"unexpected decoded message {message!r}")
                if message.kind is not constants.FrameKind.GET_STATUS_RESPONSE:
                    raise AssertionError(f"unexpected response {message.kind.name}")
                if message.request_id <= previous_request_id:
                    raise AssertionError("STATUS request IDs did not increase")
                previous_request_id = message.request_id
                if not message.ok or not isinstance(message.value, Status):
                    raise AssertionError("STATUS response was not a typed success")
                status = message.value
                run_counts = counts.get(message.run_id)
                if run_counts is None:
                    raise AssertionError(f"unexpected STATUS run {message.run_id}")
                if (status.adc_frames_emitted, status.gpio_frames_emitted) != tuple(
                    run_counts
                ):
                    raise AssertionError("STATUS counters do not match parsed frames")
                final = status.device_state is DeviceState.IDLE
                validators[message.run_id].validate_status(
                    status,
                    response_run_id=message.run_id,
                    final=final,
                )
                if final:
                    final_status_runs.add(message.run_id)
                status_responses += 1
    finally:
        wire_view.release()

    expected_per_source = sum(run.coverage_count for run in corpus.runs)
    adc_frames = sum(run_counts[0] for run_counts in counts.values())
    gpio_frames = sum(run_counts[1] for run_counts in counts.values())
    if (adc_frames, gpio_frames) != (expected_per_source, expected_per_source):
        raise AssertionError("not every data frame reached strict validation")
    if final_status_runs != set(specs):
        raise AssertionError("each run must end with one final IDLE STATUS")
    if status_responses != corpus.response_count:
        raise AssertionError("not every concurrent STATUS response was decoded")
    counters = parser.counters
    if counters.corruption_events or counters.buffered_bytes:
        raise AssertionError("valid corpus produced parser loss or trailing bytes")
    if counters.frames_decoded != corpus.data_frame_count + corpus.response_count:
        raise AssertionError("parser frame count does not reconcile with the corpus")
    if counters.high_water_mark > parser.max_buffered_bytes:
        raise AssertionError("incremental parser exceeded its fixed byte bound")
    return _CorpusResult(adc_frames, gpio_frames, status_responses, counters)


def _wait_for_host_drops(
    daq: ThingDAQ,
    expected: int,
    *,
    timeout: float = 5.0,
) -> ReaderCounters:
    deadline = time.monotonic() + timeout
    while True:
        counters = daq.reader_counters
        if counters.host_block_queue_drops >= expected:
            return counters
        if time.monotonic() >= deadline:
            raise AssertionError(
                f"host queue recorded {counters.host_block_queue_drops} drops; "
                f"expected at least {expected}"
            )
        time.sleep(0.0005)


class SustainedSyntheticCorrectnessTests(unittest.TestCase):
    def test_multirun_corpus_random_chunking_and_status_reconciliation(self) -> None:
        corpus = _multirun_wire_corpus()

        result = _consume_corpus(
            corpus,
            seed=0xDA04_C0DE,
            maximum_chunk=5_003,
            check_boundary_layouts=True,
        )

        self.assertGreater(corpus.logical_seconds, 2.0)
        self.assertEqual(corpus.data_frame_count // 2, result.adc_frames)
        self.assertEqual(corpus.data_frame_count // 2, result.gpio_frames)
        self.assertEqual(corpus.response_count, result.status_responses)
        self.assertEqual(0, result.parser.corruption_events)
        self.assertLessEqual(
            result.parser.high_water_mark,
            IncrementalFrameParser.max_buffered_bytes,
        )

    def test_multisecond_paced_streams_at_and_above_target_rate(self) -> None:
        profiles = (
            ("target", 1.0, 0xDA04_1000, 0.80),
            ("above-target", 1.5, 0xDA04_1500, 1.05),
        )
        first_target_run_id: int | None = None

        for name, multiplier, seed, minimum_ratio in profiles:
            with self.subTest(profile=name):
                transport = _RandomChunkPacedTransport(
                    rate_multiplier=multiplier,
                    seed=seed,
                )
                with ThingDAQ.open(
                    transport,
                    max_buffered_blocks=64,
                    idle_sleep=0.00001,
                ) as daq:
                    metrics = run_synthetic_soak(
                        daq,
                        duration=PACED_TEST_SECONDS,
                        status_interval=0.075,
                        track_memory=False,
                    )
                    if name == "target":
                        first_target_run_id = metrics.run_id
                        second_epoch = run_synthetic_soak(
                            daq,
                            frame_count=8,
                            status_interval=None,
                            track_memory=False,
                        )
                        expected_run_id = (metrics.run_id + 1) & constants.UINT32_MAX
                        if expected_run_id == 0:
                            expected_run_id = 1
                        self.assertEqual(expected_run_id, second_epoch.run_id)
                        self.assertTrue(second_epoch.reconciliation.ok)

                observed_ratio = (
                    metrics.framed_bytes_per_second / TARGET_FRAMED_BYTES_PER_SECOND
                )
                self.assertGreaterEqual(observed_ratio, minimum_ratio)
                if name == "target":
                    self.assertLessEqual(observed_ratio, 1.10)
                self.assertAlmostEqual(
                    TARGET_PAYLOAD_BYTES_PER_SECOND,
                    8_000_000.0,
                    places=6,
                )
                self.assertGreaterEqual(metrics.elapsed_seconds, PACED_TEST_SECONDS)
                self.assertLessEqual(
                    abs(metrics.adc.frame_count - metrics.gpio.frame_count),
                    1,
                )
                command_counts = dict(metrics.command_latency.command_counts)
                self.assertGreaterEqual(command_counts.get("STATUS", 0), 20)
                self.assertTrue(metrics.reconciliation.ok)
                self.assertEqual(0, metrics.reader_counters.host_block_queue_drops)
                self.assertEqual(0, metrics.parser_counters.corruption_events)
                self.assertGreater(transport.nonempty_reads, 1_000)
                self.assertGreater(transport.partial_frame_reads, 0)
                self.assertLess(
                    transport.minimum_read_bytes, constants.DATA_FRAME_BYTES
                )
                self.assertGreater(transport.maximum_read_bytes, constants.HEADER_SIZE)

        self.assertIsNotNone(first_target_run_id)


class BoundedQueueLossAccountingTests(unittest.TestCase):
    def test_slow_consumer_stays_bounded_and_attributes_only_host_drops(self) -> None:
        queue_capacity = 4
        transport = InMemoryTransport(
            demand_driven=False,
            max_pending_bytes=2 * constants.DATA_FRAME_BYTES,
        )
        tracing_was_active = tracemalloc.is_tracing()
        with ThingDAQ.open(
            transport,
            max_buffered_blocks=queue_capacity,
            idle_sleep=0.00001,
        ) as daq:
            daq.configure(adc=True, gpio=True)
            daq.start()
            _wait_for_host_drops(daq, 32)
            if not tracing_was_active:
                tracemalloc.start()
            tracemalloc.reset_peak()
            memory_baseline, _ = tracemalloc.get_traced_memory()
            try:
                _wait_for_host_drops(daq, 64)
                gc.collect()
                early_current, _ = tracemalloc.get_traced_memory()
                counters = _wait_for_host_drops(daq, 512)
                gc.collect()
                late_current, peak = tracemalloc.get_traced_memory()
            finally:
                if not tracing_was_active:
                    tracemalloc.stop()

            daq.stop()
            final_status = daq.status()
            final_reader = daq.reader_counters
            losses = daq.loss_counters(refresh=False)

        self.assertEqual(queue_capacity, counters.queued_blocks)
        self.assertEqual(queue_capacity, counters.block_queue_high_water)
        self.assertGreaterEqual(counters.adc_block_queue_drops, 1)
        self.assertGreaterEqual(counters.gpio_block_queue_drops, 1)
        self.assertEqual(
            counters.host_block_queue_drops,
            counters.adc_block_queue_drops + counters.gpio_block_queue_drops,
        )
        self.assertLessEqual(late_current, early_current + 128 * 1024)
        self.assertLessEqual(peak - memory_baseline, 512 * 1024)
        self.assertEqual(0, losses.firmware.items_dropped)
        self.assertGreaterEqual(losses.host.host_block_queue_drops, 512)
        self.assertEqual(0, losses.host.parser_corruption_events)
        self.assertEqual(0, transport.pending_bytes)
        self.assertEqual(0, final_reader.queued_blocks)
        self.assertEqual(
            final_reader.adc_frames_received + final_reader.gpio_frames_received,
            final_reader.host_block_queue_drops
            + final_reader.boundary_blocks_discarded,
        )
        self.assertEqual(
            final_status.adc_frames_emitted,
            final_reader.adc_frames_received,
        )
        self.assertEqual(
            final_status.gpio_frames_emitted,
            final_reader.gpio_frames_received,
        )

    def test_firmware_drop_counter_never_becomes_a_host_queue_drop(self) -> None:
        transport = InMemoryTransport(_FirmwareDropDevice())
        with ThingDAQ.open(transport, max_buffered_blocks=2) as daq:
            daq.configure(adc=True, gpio=True)
            daq.start()
            blocks = tuple(daq.read_block() for _ in range(4))
            losses = daq.loss_counters()
            daq.stop()

        self.assertEqual(4, len(blocks))
        self.assertEqual(
            constants.ADC_PAIRS_PER_FRAME,
            losses.firmware.adc_items_dropped,
        )
        self.assertEqual(0, losses.firmware.gpio_items_dropped)
        self.assertEqual(0, losses.host.host_block_queue_drops)
        self.assertEqual(0, losses.observed_stream_gaps)
        self.assertEqual(1, losses.protocol_telemetry_errors)
        self.assertTrue(losses.telemetry_errors)


class StreamingPerformanceGuardTests(unittest.TestCase):
    def test_parser_and_validation_keep_useful_headroom_with_variance_report(
        self,
    ) -> None:
        corpus = _multirun_wire_corpus()
        profiles = (
            ("large-random", 0xDA04_B001, 64 * 1024),
            ("usb-random", 0xDA04_B002, 16 * 1024),
            ("short-random", 0xDA04_B003, 1_024),
        )
        samples: list[dict[str, float | int | str]] = []

        for name, seed, maximum_chunk in profiles:
            wall_started = time.perf_counter()
            process_started = time.process_time()
            result = _consume_corpus(
                corpus,
                seed=seed,
                maximum_chunk=maximum_chunk,
                check_boundary_layouts=False,
            )
            process_seconds = time.process_time() - process_started
            elapsed_seconds = time.perf_counter() - wall_started
            framed_rate = corpus.data_wire_bytes / elapsed_seconds
            samples.append(
                {
                    "profile": name,
                    "seed": seed,
                    "maximum_chunk_bytes": maximum_chunk,
                    "elapsed_seconds": elapsed_seconds,
                    "process_seconds": process_seconds,
                    "framed_bytes_per_second": framed_rate,
                    "headroom_ratio": framed_rate / TARGET_FRAMED_BYTES_PER_SECOND,
                    "parser_high_water_bytes": result.parser.high_water_mark,
                }
            )

        headrooms = [float(sample["headroom_ratio"]) for sample in samples]
        report = {
            "schema": "thingdaq-python-stream-benchmark-v1",
            "python_implementation": platform.python_implementation(),
            "python_version": platform.python_version(),
            "platform": platform.platform(),
            "machine": platform.machine(),
            "processor": platform.processor() or "unknown",
            "cpu_count": os.cpu_count(),
            "target_framed_bytes_per_second": TARGET_FRAMED_BYTES_PER_SECOND,
            "required_headroom_ratio": REQUIRED_BENCHMARK_HEADROOM,
            "logical_stream_seconds": corpus.logical_seconds,
            "data_wire_bytes": corpus.data_wire_bytes,
            "status_response_count": corpus.response_count,
            "minimum_headroom_ratio": min(headrooms),
            "median_headroom_ratio": median(headrooms),
            "maximum_headroom_ratio": max(headrooms),
            "samples": samples,
        }
        serialized_report = json.dumps(report, sort_keys=True)
        print(f"PHASE04_PYTHON_BENCHMARK {serialized_report}")

        self.assertGreater(corpus.logical_seconds, 2.0)
        self.assertGreaterEqual(
            min(headrooms),
            REQUIRED_BENCHMARK_HEADROOM,
            serialized_report,
        )


if __name__ == "__main__":
    unittest.main()
