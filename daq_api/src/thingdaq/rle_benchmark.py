"""Deterministic host corpus benchmark for adaptive protocol-v2 RLE.

The corpus is fixed by named, stateless source formulas.  Corpus construction,
wire construction, correctness checks, and memory probes are excluded from the
timed batches.  Every measured path calls the production protocol-v2 encoder or
decoder; this module does not contain a second codec implementation.
"""

from __future__ import annotations

import argparse
import gc
import hashlib
import json
import math
import os
import platform
import struct
import tracemalloc
from collections import Counter
from collections.abc import Callable, Sequence
from dataclasses import dataclass
from fractions import Fraction
from statistics import median
from time import perf_counter
from typing import TypeAlias, cast

from ._generated import protocol_v2_constants as constants
from .models import ADCBlock, GPIOBlock
from .protocol_v2 import (
    V2DataBlock,
    V2Frame,
    decode_v2_data_block,
    decode_v2_frame,
    encode_v2_data_frame,
)
from .simulator import (
    ExperimentalSourcePattern,
    experimental_adc_payload,
    experimental_gpio_payload,
)

DEFAULT_FRAMES_PER_WORKLOAD = 8
DEFAULT_BATCH_COUNT = 5
DEFAULT_ITERATIONS_PER_BATCH = 3
DEFAULT_WARMUP_ITERATIONS = 1
MAX_FRAMES_PER_WORKLOAD = 64
MAX_BATCH_COUNT = 32
MAX_ITERATIONS_PER_BATCH = 256
MAX_WARMUP_ITERATIONS = 16
MAX_PROCESSED_LOGICAL_BYTES = 512 * 1024 * 1024
MAX_CODEC_PEAK_BYTES = 64 * 1024
REQUIRED_DECODE_HEADROOM = Fraction(5, 4)
MAX_LONG_HOLD_GPIO_WIRE_RATIO = Fraction(1, 4)

_ADC_PAIR = struct.Struct("<HH")
_TRAILER = struct.Struct("<I")
_DATA_KINDS = (constants.FrameKind.ADC_DATA, constants.FrameKind.GPIO_DATA)
_TARGET_LOGICAL_RATE = Fraction(
    constants.DATA_PAYLOAD_BYTES * constants.TIMESTAMP_HZ,
    constants.FRAME_COVERAGE_TICKS,
)
if _TARGET_LOGICAL_RATE.denominator != 1:  # pragma: no cover - contract guard
    raise RuntimeError("per-stream logical payload rate must be an integer")
TARGET_LOGICAL_BYTES_PER_SECOND = _TARGET_LOGICAL_RATE.numerator
if (  # pragma: no cover - generated-contract guard
    TARGET_LOGICAL_BYTES_PER_SECOND
    != constants.NOMINAL_PAYLOAD_BYTES_PER_SECOND_PER_STREAM
):
    raise RuntimeError("derived target rate disagrees with generated protocol v2")
REQUIRED_DECODE_BYTES_PER_SECOND = int(_TARGET_LOGICAL_RATE * REQUIRED_DECODE_HEADROOM)

DataBlock: TypeAlias = ADCBlock | GPIOBlock


class RLECorpusBenchmarkError(RuntimeError):
    """The corpus or measured production path violated a benchmark invariant."""


@dataclass(frozen=True, slots=True)
class RLECorpusWorkload:
    """One named deterministic logical workload before wire framing."""

    name: str
    stream: str
    description: str
    source_formula: str
    frame_kind: constants.FrameKind
    payloads: tuple[bytes, ...]
    requires_raw_fallback: bool = False
    requires_strong_gpio_savings: bool = False

    @property
    def item_size(self) -> int:
        return (
            constants.ADC_BYTES_PER_PAIR
            if self.frame_kind is constants.FrameKind.ADC_DATA
            else 1
        )

    @property
    def items_per_frame(self) -> int:
        return (
            constants.ADC_PAIRS_PER_FRAME
            if self.frame_kind is constants.FrameKind.ADC_DATA
            else constants.GPIO_SAMPLES_PER_FRAME
        )

    @property
    def logical_payload_bytes(self) -> int:
        return len(self.payloads) * constants.DATA_PAYLOAD_BYTES

    @property
    def logical_items(self) -> int:
        return len(self.payloads) * self.items_per_frame


@dataclass(frozen=True, slots=True)
class ExactRatio:
    """A ratio retaining the exact measured numerator and denominator."""

    numerator: int
    denominator: int

    def __post_init__(self) -> None:
        if self.numerator < 0 or self.denominator <= 0:
            raise ValueError("ratio requires a nonnegative numerator and denominator")

    @property
    def value(self) -> float:
        return self.numerator / self.denominator

    def to_dict(self) -> dict[str, int | float]:
        reduced = Fraction(self.numerator, self.denominator)
        return {
            "numerator": self.numerator,
            "denominator": self.denominator,
            "reduced_numerator": reduced.numerator,
            "reduced_denominator": reduced.denominator,
            "value": self.value,
        }


@dataclass(frozen=True, slots=True)
class RunLengthDistribution:
    """Exact frame-local run counts plus deterministic order statistics."""

    logical_items: int
    run_count: int
    minimum_items: int
    median_items: float
    p90_items: int
    p99_items: int
    maximum_items: int
    counts: tuple[tuple[int, int], ...]

    @property
    def mean_items_per_run(self) -> ExactRatio:
        return ExactRatio(self.logical_items, self.run_count)

    def to_dict(self) -> dict[str, object]:
        return {
            "logical_items": self.logical_items,
            "run_count": self.run_count,
            "mean_items_per_run": self.mean_items_per_run.to_dict(),
            "minimum_items": self.minimum_items,
            "median_items": self.median_items,
            "p90_items": self.p90_items,
            "p99_items": self.p99_items,
            "maximum_items": self.maximum_items,
            "counts": tuple(
                {"run_length_items": length, "record_count": count}
                for length, count in self.counts
            ),
        }


@dataclass(frozen=True, slots=True)
class CodecPathResult:
    """Repeated exact-path timings for one encoding or decoding mode."""

    path: str
    batch_seconds: tuple[float, ...]
    iterations_per_batch: int
    frames_per_iteration: int
    logical_bytes_per_iteration: int
    wire_bytes_per_iteration: int
    deterministic_digest: int

    @property
    def operations(self) -> int:
        return (
            len(self.batch_seconds)
            * self.iterations_per_batch
            * self.frames_per_iteration
        )

    @property
    def processed_logical_bytes(self) -> int:
        return (
            len(self.batch_seconds)
            * self.iterations_per_batch
            * self.logical_bytes_per_iteration
        )

    @property
    def logical_bytes_per_batch(self) -> int:
        return self.iterations_per_batch * self.logical_bytes_per_iteration

    @property
    def logical_bytes_per_second_samples(self) -> tuple[float, ...]:
        return tuple(
            self.logical_bytes_per_batch / seconds for seconds in self.batch_seconds
        )

    @property
    def minimum_bytes_per_second(self) -> float:
        return min(self.logical_bytes_per_second_samples)

    @property
    def median_bytes_per_second(self) -> float:
        return median(self.logical_bytes_per_second_samples)

    @property
    def maximum_bytes_per_second(self) -> float:
        return max(self.logical_bytes_per_second_samples)

    @property
    def minimum_target_headroom(self) -> float:
        return self.minimum_bytes_per_second / TARGET_LOGICAL_BYTES_PER_SECOND

    @property
    def median_target_headroom(self) -> float:
        return self.median_bytes_per_second / TARGET_LOGICAL_BYTES_PER_SECOND

    def to_dict(self) -> dict[str, object]:
        return {
            "path": self.path,
            "batch_seconds": self.batch_seconds,
            "batch_count": len(self.batch_seconds),
            "iterations_per_batch": self.iterations_per_batch,
            "frames_per_iteration": self.frames_per_iteration,
            "operations": self.operations,
            "logical_bytes_per_iteration": self.logical_bytes_per_iteration,
            "logical_bytes_per_batch": self.logical_bytes_per_batch,
            "processed_logical_bytes": self.processed_logical_bytes,
            "wire_bytes_per_iteration": self.wire_bytes_per_iteration,
            "minimum_logical_bytes_per_second": self.minimum_bytes_per_second,
            "median_logical_bytes_per_second": self.median_bytes_per_second,
            "maximum_logical_bytes_per_second": self.maximum_bytes_per_second,
            "minimum_target_headroom": self.minimum_target_headroom,
            "median_target_headroom": self.median_target_headroom,
            "deterministic_digest": f"{self.deterministic_digest:08x}",
        }


@dataclass(frozen=True, slots=True)
class CodecMemoryResult:
    """One isolated tracemalloc peak including the returned wire or block."""

    path: str
    retained_bytes: int
    peak_bytes: int
    limit_bytes: int = MAX_CODEC_PEAK_BYTES

    @property
    def within_limit(self) -> bool:
        return self.peak_bytes <= self.limit_bytes

    def to_dict(self) -> dict[str, object]:
        return {
            "path": self.path,
            "measurement": "tracemalloc peak above an idle traced baseline",
            "includes_returned_object": True,
            "retained_bytes": self.retained_bytes,
            "peak_bytes": self.peak_bytes,
            "limit_bytes": self.limit_bytes,
            "within_limit": self.within_limit,
        }


@dataclass(frozen=True, slots=True)
class RLEWorkloadResult:
    """Compression, throughput, memory, and correctness for one workload."""

    workload: RLECorpusWorkload
    corpus_sha256: str
    raw_payload_bytes: int
    selected_payload_bytes: int
    raw_wire_bytes: int
    selected_wire_bytes: int
    rle_frames: int
    fallback_frames: int
    round_trip_equal: bool
    no_expansion: bool
    run_lengths: RunLengthDistribution
    timing: tuple[CodecPathResult, ...]
    memory: tuple[CodecMemoryResult, ...]

    @property
    def payload_ratio(self) -> ExactRatio:
        return ExactRatio(self.selected_payload_bytes, self.raw_payload_bytes)

    @property
    def complete_wire_ratio(self) -> ExactRatio:
        return ExactRatio(self.selected_wire_bytes, self.raw_wire_bytes)

    @property
    def fallback_frequency(self) -> ExactRatio:
        return ExactRatio(self.fallback_frames, len(self.workload.payloads))

    def path(self, name: str) -> CodecPathResult:
        for result in self.timing:
            if result.path == name:
                return result
        raise KeyError(name)

    def to_dict(self) -> dict[str, object]:
        return {
            "name": self.workload.name,
            "stream": self.workload.stream,
            "description": self.workload.description,
            "source_formula": self.workload.source_formula,
            "corpus_sha256": self.corpus_sha256,
            "frames": len(self.workload.payloads),
            "items_per_frame": self.workload.items_per_frame,
            "item_bytes": self.workload.item_size,
            "logical_items": self.workload.logical_items,
            "logical_payload_bytes": self.workload.logical_payload_bytes,
            "raw_payload_bytes": self.raw_payload_bytes,
            "selected_payload_bytes": self.selected_payload_bytes,
            "payload_ratio": self.payload_ratio.to_dict(),
            "raw_complete_wire_bytes": self.raw_wire_bytes,
            "selected_complete_wire_bytes": self.selected_wire_bytes,
            "complete_wire_ratio": self.complete_wire_ratio.to_dict(),
            "rle_frames": self.rle_frames,
            "fallback_frames": self.fallback_frames,
            "fallback_frequency": self.fallback_frequency.to_dict(),
            "round_trip_equal": self.round_trip_equal,
            "no_expansion": self.no_expansion,
            "requires_raw_fallback": self.workload.requires_raw_fallback,
            "requires_strong_gpio_savings": (
                self.workload.requires_strong_gpio_savings
            ),
            "run_length_distribution": self.run_lengths.to_dict(),
            "timing": tuple(item.to_dict() for item in self.timing),
            "memory": tuple(item.to_dict() for item in self.memory),
        }


@dataclass(frozen=True, slots=True)
class BenchmarkCheck:
    """One explicit benchmark acceptance or observation."""

    name: str
    required: bool
    passed: bool
    expected: object
    observed: object
    detail: str

    def to_dict(self) -> dict[str, object]:
        return {
            "name": self.name,
            "required": self.required,
            "state": "PASS" if self.passed else "FAIL",
            "expected": self.expected,
            "observed": self.observed,
            "detail": self.detail,
        }


@dataclass(frozen=True, slots=True)
class RLECorpusBenchmarkResult:
    """Complete deterministic-corpus result and explicit grading record."""

    frames_per_workload: int
    batch_count: int
    iterations_per_batch: int
    warmup_iterations: int
    corpus_sha256: str
    workloads: tuple[RLEWorkloadResult, ...]
    checks: tuple[BenchmarkCheck, ...]

    @property
    def passed(self) -> bool:
        return all(check.passed for check in self.checks if check.required)

    def to_dict(self) -> dict[str, object]:
        return {
            "schema": "thingdaq-rle-corpus-benchmark-v1",
            "result": "PASS" if self.passed else "FAIL",
            "evidence_level": "host",
            "serial_hardware": False,
            "firmware_target_timing_claim": False,
            "physical_signal_claim": False,
            "corpus_deterministic": True,
            "corpus_sha256": self.corpus_sha256,
            "protocol_version": constants.PROTOCOL_VERSION,
            "protocol_source_sha256": constants.SOURCE_SHA256,
            "raw_frame_encoding": constants.FrameEncoding.RAW.name,
            "adaptive_configuration_encoding": (
                constants.ConfigurationEncoding.RLE_AUTO.name
            ),
            "checksum_algorithm": constants.DEFAULT_CHECKSUM_ALGORITHM.name,
            "python_implementation": platform.python_implementation(),
            "python_version": platform.python_version(),
            "platform": platform.platform(),
            "machine": platform.machine(),
            "processor": platform.processor() or "unknown",
            "cpu_count": os.cpu_count(),
            "timing_clock": "time.perf_counter",
            "timing_excludes": (
                "corpus construction, correctness checks, and memory probes"
            ),
            "frames_per_workload": self.frames_per_workload,
            "workload_count": len(self.workloads),
            "batch_count": self.batch_count,
            "iterations_per_batch": self.iterations_per_batch,
            "warmup_iterations": self.warmup_iterations,
            "target_logical_bytes_per_second_per_stream": (
                TARGET_LOGICAL_BYTES_PER_SECOND
            ),
            "target_rate_exact_denominator": {
                "payload_bytes_per_frame": constants.DATA_PAYLOAD_BYTES,
                "timestamp_ticks_per_second": constants.TIMESTAMP_HZ,
                "coverage_ticks_per_frame": constants.FRAME_COVERAGE_TICKS,
            },
            "required_decode_headroom": {
                "numerator": REQUIRED_DECODE_HEADROOM.numerator,
                "denominator": REQUIRED_DECODE_HEADROOM.denominator,
                "value": float(REQUIRED_DECODE_HEADROOM),
                "required_logical_bytes_per_second": (REQUIRED_DECODE_BYTES_PER_SECOND),
            },
            "maximum_codec_peak_bytes": MAX_CODEC_PEAK_BYTES,
            "maximum_long_hold_gpio_wire_ratio": {
                "numerator": MAX_LONG_HOLD_GPIO_WIRE_RATIO.numerator,
                "denominator": MAX_LONG_HOLD_GPIO_WIRE_RATIO.denominator,
                "value": float(MAX_LONG_HOLD_GPIO_WIRE_RATIO),
            },
            "break_even": tuple(_break_even(kind) for kind in _DATA_KINDS),
            "checks": tuple(check.to_dict() for check in self.checks),
            "workloads": tuple(result.to_dict() for result in self.workloads),
        }


@dataclass(frozen=True, slots=True)
class _FrameCase:
    """One workload frame with fixed envelope fields and both exact wires."""

    workload: RLECorpusWorkload
    payload: bytes
    flags: constants.FrameFlag
    run_id: int
    sequence: int
    first_sample_ticks: int
    raw_wire: bytes
    selected_wire: bytes
    selected_frame: V2Frame
    run_lengths: tuple[int, ...]
    round_trip_equal: bool


def _quantization_noise_adc_payload(first_pair: int) -> bytes:
    """Return deterministic low-amplitude independent ADC code noise.

    The stateless high-entropy simulator formula supplies only the noise index;
    each channel is then constrained to a narrow range around a fixed DC code.
    This models quantization noise without treating it as a physical ADC claim.
    """

    entropy = experimental_adc_payload(
        ExperimentalSourcePattern.HIGH_ENTROPY,
        first_pair,
    )
    payload = bytearray(constants.DATA_PAYLOAD_BYTES)
    for offset, (noise0, noise1) in enumerate(struct.iter_unpack("<HH", entropy)):
        adc0 = 0x600 + (noise0 % 7) - 3
        adc1 = 0xA00 + (noise1 % 9) - 4
        _ADC_PAIR.pack_into(payload, offset * _ADC_PAIR.size, adc0, adc1)
    return bytes(payload)


def _workload_definitions() -> tuple[dict[str, object], ...]:
    return (
        {
            "name": "gpio-constant",
            "stream": "GPIO",
            "description": "one packed GPIO state held for the entire corpus",
            "source_formula": "experimental_gpio_payload(CONSTANT)",
            "kind": constants.FrameKind.GPIO_DATA,
            "pattern": ExperimentalSourcePattern.CONSTANT,
        },
        {
            "name": "gpio-long-digital-holds",
            "stream": "GPIO",
            "description": "packed states held for 512 samples across frame boundaries",
            "source_formula": "experimental_gpio_payload(LONG_HOLD)",
            "kind": constants.FrameKind.GPIO_DATA,
            "pattern": ExperimentalSourcePattern.LONG_HOLD,
            "strong_savings": True,
        },
        {
            "name": "gpio-sparse-single-bit-changes",
            "stream": "GPIO",
            "description": "one Gray-code bit changes every 4,001 samples",
            "source_formula": "experimental_gpio_payload(SPARSE_TRANSITION)",
            "kind": constants.FrameKind.GPIO_DATA,
            "pattern": ExperimentalSourcePattern.SPARSE_TRANSITION,
        },
        {
            "name": "gpio-alternating-bytes",
            "stream": "GPIO",
            "description": "0x55 and 0xaa alternate every sample",
            "source_formula": "experimental_gpio_payload(ALTERNATING)",
            "kind": constants.FrameKind.GPIO_DATA,
            "pattern": ExperimentalSourcePattern.ALTERNATING,
            "fallback": True,
        },
        {
            "name": "gpio-pseudo-random-bytes",
            "stream": "GPIO",
            "description": "stateless seeded 32-bit mix reduced to packed bytes",
            "source_formula": "experimental_gpio_payload(HIGH_ENTROPY)",
            "kind": constants.FrameKind.GPIO_DATA,
            "pattern": ExperimentalSourcePattern.HIGH_ENTROPY,
            "fallback": True,
        },
        {
            "name": "adc-constant-pairs",
            "stream": "ADC",
            "description": "one ADC0/ADC1 pair held for the entire corpus",
            "source_formula": "experimental_adc_payload(CONSTANT)",
            "kind": constants.FrameKind.ADC_DATA,
            "pattern": ExperimentalSourcePattern.CONSTANT,
        },
        {
            "name": "adc-independent-slow-channels",
            "stream": "ADC",
            "description": "ADC0 changes every 8 pairs and ADC1 every 11 pairs",
            "source_formula": "experimental_adc_payload(SLOWLY_CHANGING)",
            "kind": constants.FrameKind.ADC_DATA,
            "pattern": ExperimentalSourcePattern.SLOWLY_CHANGING,
        },
        {
            "name": "adc-quantization-noise",
            "stream": "ADC",
            "description": "independent deterministic +/-3 and +/-4 code noise",
            "source_formula": "bounded DC codes indexed by HIGH_ENTROPY",
            "kind": constants.FrameKind.ADC_DATA,
            "quantization_noise": True,
            "fallback": True,
        },
        {
            "name": "adc-high-entropy",
            "stream": "ADC",
            "description": "independent stateless mixed 12-bit channel codes",
            "source_formula": "experimental_adc_payload(HIGH_ENTROPY)",
            "kind": constants.FrameKind.ADC_DATA,
            "pattern": ExperimentalSourcePattern.HIGH_ENTROPY,
            "fallback": True,
        },
    )


def _positive_bounded(name: str, value: int, maximum: int) -> int:
    if not isinstance(value, int) or isinstance(value, bool):
        raise TypeError(f"{name} must be an integer")
    if not 1 <= value <= maximum:
        raise ValueError(f"{name} must be between 1 and {maximum}")
    return value


def _nonnegative_bounded(name: str, value: int, maximum: int) -> int:
    if not isinstance(value, int) or isinstance(value, bool):
        raise TypeError(f"{name} must be an integer")
    if not 0 <= value <= maximum:
        raise ValueError(f"{name} must be between 0 and {maximum}")
    return value


def build_rle_corpus(
    frames_per_workload: int = DEFAULT_FRAMES_PER_WORKLOAD,
) -> tuple[RLECorpusWorkload, ...]:
    """Build the nine fixed workloads without constructing or timing wire frames."""

    frame_count = _positive_bounded(
        "frames_per_workload",
        frames_per_workload,
        MAX_FRAMES_PER_WORKLOAD,
    )
    workloads: list[RLECorpusWorkload] = []
    for definition in _workload_definitions():
        kind = constants.FrameKind(cast(int, definition["kind"]))
        items_per_frame = (
            constants.ADC_PAIRS_PER_FRAME
            if kind is constants.FrameKind.ADC_DATA
            else constants.GPIO_SAMPLES_PER_FRAME
        )
        payloads: list[bytes] = []
        for frame_index in range(frame_count):
            first_item = frame_index * items_per_frame
            if definition.get("quantization_noise"):
                payload = _quantization_noise_adc_payload(first_item)
            else:
                pattern = cast(ExperimentalSourcePattern, definition["pattern"])
                payload = (
                    experimental_adc_payload(pattern, first_item)
                    if kind is constants.FrameKind.ADC_DATA
                    else experimental_gpio_payload(pattern, first_item)
                )
            if len(payload) != constants.DATA_PAYLOAD_BYTES:
                raise RLECorpusBenchmarkError(
                    f"{definition['name']} produced a non-frame payload"
                )
            payloads.append(payload)
        workloads.append(
            RLECorpusWorkload(
                name=str(definition["name"]),
                stream=str(definition["stream"]),
                description=str(definition["description"]),
                source_formula=str(definition["source_formula"]),
                frame_kind=kind,
                payloads=tuple(payloads),
                requires_raw_fallback=bool(definition.get("fallback", False)),
                requires_strong_gpio_savings=bool(
                    definition.get("strong_savings", False)
                ),
            )
        )
    return tuple(workloads)


def _payload_digest(workload: RLECorpusWorkload) -> str:
    digest = hashlib.sha256()
    digest.update(workload.name.encode("ascii"))
    digest.update(b"\0")
    digest.update(bytes((int(workload.frame_kind), workload.item_size)))
    for payload in workload.payloads:
        digest.update(len(payload).to_bytes(4, "little"))
        digest.update(payload)
    return digest.hexdigest()


def _corpus_digest(workloads: Sequence[RLECorpusWorkload]) -> str:
    digest = hashlib.sha256()
    for workload in workloads:
        digest.update(bytes.fromhex(_payload_digest(workload)))
    return digest.hexdigest()


def _frame_run_lengths(payload: bytes, item_size: int) -> tuple[int, ...]:
    if len(payload) == 0 or len(payload) % item_size:
        raise RLECorpusBenchmarkError("corpus payload ends inside a logical item")
    view = memoryview(payload)
    try:
        runs: list[int] = []
        previous = bytes(view[:item_size])
        length = 1
        for offset in range(item_size, len(view), item_size):
            item = bytes(view[offset : offset + item_size])
            if item == previous:
                length += 1
            else:
                runs.append(length)
                previous = item
                length = 1
        runs.append(length)
        return tuple(runs)
    finally:
        view.release()


def _encode_case(
    workload: RLECorpusWorkload,
    payload: bytes,
    *,
    frame_index: int,
    run_id: int,
    encoding: constants.ConfigurationEncoding,
) -> bytes:
    return encode_v2_data_frame(
        workload.frame_kind,
        payload,
        configuration_encoding=encoding,
        flags=(
            constants.FrameFlag.EPOCH_START
            if frame_index == 0
            else constants.FrameFlag.NONE
        ),
        run_id=run_id,
        sequence=frame_index,
        first_sample_ticks=frame_index * constants.FRAME_COVERAGE_TICKS,
    )


def _decode_case(
    wire: bytes,
    encoding: constants.ConfigurationEncoding,
) -> tuple[V2Frame, DataBlock]:
    frame = decode_v2_frame(wire)
    block = decode_v2_data_block(frame, negotiated_encoding=encoding)
    return frame, block


def _frame_workload(
    workload: RLECorpusWorkload,
    *,
    run_id: int,
) -> tuple[_FrameCase, ...]:
    frames: list[_FrameCase] = []
    for frame_index, payload in enumerate(workload.payloads):
        flags = (
            constants.FrameFlag.EPOCH_START
            if frame_index == 0
            else constants.FrameFlag.NONE
        )
        raw_wire = _encode_case(
            workload,
            payload,
            frame_index=frame_index,
            run_id=run_id,
            encoding=constants.ConfigurationEncoding.RAW,
        )
        selected_wire = _encode_case(
            workload,
            payload,
            frame_index=frame_index,
            run_id=run_id,
            encoding=constants.ConfigurationEncoding.RLE_AUTO,
        )
        raw_frame, raw_block = _decode_case(
            raw_wire,
            constants.ConfigurationEncoding.RAW,
        )
        selected_frame, selected_block = _decode_case(
            selected_wire,
            constants.ConfigurationEncoding.RLE_AUTO,
        )
        expected_fields = (
            run_id,
            frame_index,
            frame_index * constants.FRAME_COVERAGE_TICKS,
            workload.items_per_frame,
        )
        raw_fields = (
            raw_frame.header.run_id,
            raw_frame.header.sequence,
            raw_frame.header.first_sample_ticks,
            raw_frame.header.item_count,
        )
        selected_fields = (
            selected_frame.header.run_id,
            selected_frame.header.sequence,
            selected_frame.header.first_sample_ticks,
            selected_frame.header.item_count,
        )
        round_trip_equal = (
            raw_fields == expected_fields
            and selected_fields == expected_fields
            and raw_block.payload == payload
            and selected_block.payload == payload
        )
        run_lengths = _frame_run_lengths(payload, workload.item_size)
        diagnostics = selected_block.encoding_diagnostics
        if diagnostics is None:
            raise RLECorpusBenchmarkError(
                f"{workload.name} selected decode omitted RLE diagnostics"
            )
        if diagnostics.run_count != len(run_lengths):
            raise RLECorpusBenchmarkError(
                f"{workload.name} run-count diagnostics disagree with the corpus"
            )
        if raw_frame.header.encoding is not constants.FrameEncoding.RAW:
            raise RLECorpusBenchmarkError("RAW benchmark frame selected RLE")
        frames.append(
            _FrameCase(
                workload=workload,
                payload=payload,
                flags=flags,
                run_id=run_id,
                sequence=frame_index,
                first_sample_ticks=(frame_index * constants.FRAME_COVERAGE_TICKS),
                raw_wire=raw_wire,
                selected_wire=selected_wire,
                selected_frame=selected_frame,
                run_lengths=run_lengths,
                round_trip_equal=round_trip_equal,
            )
        )
    return tuple(frames)


def _nearest_rank(values: Sequence[int], percentile: int) -> int:
    if not values:
        raise ValueError("percentile requires at least one value")
    if not 1 <= percentile <= 100:
        raise ValueError("percentile must be between 1 and 100")
    ordered = sorted(values)
    return ordered[math.ceil(percentile * len(ordered) / 100) - 1]


def _run_distribution(frames: Sequence[_FrameCase]) -> RunLengthDistribution:
    lengths = tuple(length for frame in frames for length in frame.run_lengths)
    if not lengths:
        raise RLECorpusBenchmarkError("workload contains no RLE runs")
    counts = Counter(lengths)
    return RunLengthDistribution(
        logical_items=sum(lengths),
        run_count=len(lengths),
        minimum_items=min(lengths),
        median_items=float(median(lengths)),
        p90_items=_nearest_rank(lengths, 90),
        p99_items=_nearest_rank(lengths, 99),
        maximum_items=max(lengths),
        counts=tuple(sorted(counts.items())),
    )


def _mix_digest(digest: int, value: int) -> int:
    return ((digest << 5) - digest + value) & constants.UINT32_MAX


def _wire_token(wire: bytes) -> int:
    checksum = _TRAILER.unpack_from(wire, len(wire) - _TRAILER.size)[0]
    return checksum ^ len(wire) ^ (wire[constants.HEADER_ENCODING_OFFSET] << 24)


def _block_token(frame: V2Frame, block: V2DataBlock) -> int:
    diagnostics = block.encoding_diagnostics
    if diagnostics is None:
        raise RLECorpusBenchmarkError("timed v2 decode omitted diagnostics")
    return (
        frame.checksum
        ^ len(block.payload)
        ^ block.payload[0]
        ^ (block.payload[-1] << 8)
        ^ (diagnostics.run_count << 16)
        ^ (int(diagnostics.frame_encoding) << 31)
    ) & constants.UINT32_MAX


def _timed_path(
    path: str,
    frames: Sequence[_FrameCase],
    operation: Callable[[_FrameCase], int],
    *,
    wire_bytes_per_iteration: int,
    batch_count: int,
    iterations_per_batch: int,
    warmup_iterations: int,
) -> CodecPathResult:
    for _ in range(warmup_iterations):
        for frame in frames:
            operation(frame)

    batch_seconds: list[float] = []
    digest = 0
    gc_was_enabled = gc.isenabled()
    if gc_was_enabled:
        gc.disable()
    try:
        for _ in range(batch_count):
            started = perf_counter()
            for _ in range(iterations_per_batch):
                for frame in frames:
                    digest = _mix_digest(digest, operation(frame))
            batch_seconds.append(max(perf_counter() - started, 1e-12))
    finally:
        if gc_was_enabled:
            gc.enable()
    return CodecPathResult(
        path=path,
        batch_seconds=tuple(batch_seconds),
        iterations_per_batch=iterations_per_batch,
        frames_per_iteration=len(frames),
        logical_bytes_per_iteration=(len(frames) * constants.DATA_PAYLOAD_BYTES),
        wire_bytes_per_iteration=wire_bytes_per_iteration,
        deterministic_digest=digest,
    )


def _timings(
    frames: Sequence[_FrameCase],
    *,
    batch_count: int,
    iterations_per_batch: int,
    warmup_iterations: int,
) -> tuple[CodecPathResult, ...]:
    raw_wire_bytes = sum(len(frame.raw_wire) for frame in frames)
    selected_wire_bytes = sum(len(frame.selected_wire) for frame in frames)

    def raw_encode(frame: _FrameCase) -> int:
        wire = _encode_case(
            frame.workload,
            frame.payload,
            frame_index=frame.sequence,
            run_id=frame.run_id,
            encoding=constants.ConfigurationEncoding.RAW,
        )
        return _wire_token(wire)

    def selected_encode(frame: _FrameCase) -> int:
        wire = _encode_case(
            frame.workload,
            frame.payload,
            frame_index=frame.sequence,
            run_id=frame.run_id,
            encoding=constants.ConfigurationEncoding.RLE_AUTO,
        )
        return _wire_token(wire)

    def raw_decode(frame: _FrameCase) -> int:
        envelope, block = _decode_case(
            frame.raw_wire,
            constants.ConfigurationEncoding.RAW,
        )
        return _block_token(envelope, block)

    def selected_decode(frame: _FrameCase) -> int:
        envelope, block = _decode_case(
            frame.selected_wire,
            constants.ConfigurationEncoding.RLE_AUTO,
        )
        return _block_token(envelope, block)

    return (
        _timed_path(
            "raw_encode",
            frames,
            raw_encode,
            wire_bytes_per_iteration=raw_wire_bytes,
            batch_count=batch_count,
            iterations_per_batch=iterations_per_batch,
            warmup_iterations=warmup_iterations,
        ),
        _timed_path(
            "rle_auto_encode",
            frames,
            selected_encode,
            wire_bytes_per_iteration=selected_wire_bytes,
            batch_count=batch_count,
            iterations_per_batch=iterations_per_batch,
            warmup_iterations=warmup_iterations,
        ),
        _timed_path(
            "raw_decode",
            frames,
            raw_decode,
            wire_bytes_per_iteration=raw_wire_bytes,
            batch_count=batch_count,
            iterations_per_batch=iterations_per_batch,
            warmup_iterations=warmup_iterations,
        ),
        _timed_path(
            "rle_auto_decode",
            frames,
            selected_decode,
            wire_bytes_per_iteration=selected_wire_bytes,
            batch_count=batch_count,
            iterations_per_batch=iterations_per_batch,
            warmup_iterations=warmup_iterations,
        ),
    )


def _measure_memory(
    path: str,
    operation: Callable[[], object],
) -> CodecMemoryResult:
    if tracemalloc.is_tracing():
        raise RLECorpusBenchmarkError(
            "RLE corpus memory probes require tracemalloc to be inactive"
        )
    operation()  # Warm lazy imports and one-time backend state before tracing.
    gc.collect()
    tracemalloc.start()
    baseline, _ = tracemalloc.get_traced_memory()
    try:
        result = operation()
        current, peak = tracemalloc.get_traced_memory()
        retained = max(current - baseline, 0)
        measured_peak = max(peak - baseline, 0)
        del result
    finally:
        tracemalloc.stop()
    return CodecMemoryResult(
        path=path,
        retained_bytes=retained,
        peak_bytes=measured_peak,
    )


def _memory_results(frames: Sequence[_FrameCase]) -> tuple[CodecMemoryResult, ...]:
    representative = max(
        frames,
        key=lambda frame: (len(frame.run_lengths), len(frame.selected_wire)),
    )

    def raw_encode() -> bytes:
        return _encode_case(
            representative.workload,
            representative.payload,
            frame_index=representative.sequence,
            run_id=representative.run_id,
            encoding=constants.ConfigurationEncoding.RAW,
        )

    def selected_encode() -> bytes:
        return _encode_case(
            representative.workload,
            representative.payload,
            frame_index=representative.sequence,
            run_id=representative.run_id,
            encoding=constants.ConfigurationEncoding.RLE_AUTO,
        )

    def raw_decode() -> DataBlock:
        _, block = _decode_case(
            representative.raw_wire,
            constants.ConfigurationEncoding.RAW,
        )
        return block

    def selected_decode() -> DataBlock:
        _, block = _decode_case(
            representative.selected_wire,
            constants.ConfigurationEncoding.RLE_AUTO,
        )
        return block

    return (
        _measure_memory("raw_encode", raw_encode),
        _measure_memory("rle_auto_encode", selected_encode),
        _measure_memory("raw_decode", raw_decode),
        _measure_memory("rle_auto_decode", selected_decode),
    )


def _break_even(kind: constants.FrameKind) -> dict[str, object]:
    if kind is constants.FrameKind.ADC_DATA:
        stream = "ADC"
        item_bytes = constants.ADC_BYTES_PER_PAIR
        logical_items = constants.ADC_PAIRS_PER_FRAME
        record_bytes = constants.ADC_RLE_RECORD_BYTES
        generated_maximum = constants.ADC_RLE_MAX_SELECTED_RUNS
    elif kind is constants.FrameKind.GPIO_DATA:
        stream = "GPIO"
        item_bytes = 1
        logical_items = constants.GPIO_SAMPLES_PER_FRAME
        record_bytes = constants.GPIO_RLE_RECORD_BYTES
        generated_maximum = constants.GPIO_RLE_MAX_SELECTED_RUNS
    else:  # pragma: no cover - internal caller fixes both kinds
        raise ValueError("break-even kind must be ADC_DATA or GPIO_DATA")
    if record_bytes - item_bytes != 2:
        raise RLECorpusBenchmarkError("RLE run length is not the frozen u16 field")
    maximum_selected_runs = (constants.DATA_PAYLOAD_BYTES - 1) // record_bytes
    if maximum_selected_runs != generated_maximum:
        raise RLECorpusBenchmarkError(
            f"{stream} analytic break-even disagrees with generated constants"
        )
    minimum_uniform_run = next(
        run_length
        for run_length in range(1, logical_items + 1)
        if math.ceil(logical_items / run_length) * record_bytes
        < constants.DATA_PAYLOAD_BYTES
    )
    average = Fraction(logical_items, maximum_selected_runs)
    return {
        "stream": stream,
        "logical_items_per_frame": logical_items,
        "logical_item_bytes": item_bytes,
        "rle_record_bytes": record_bytes,
        "raw_payload_bytes": constants.DATA_PAYLOAD_BYTES,
        "raw_complete_wire_bytes": constants.DATA_FRAME_BYTES,
        "strictly_smaller_selection": True,
        "maximum_selected_run_records": maximum_selected_runs,
        "payload_bytes_at_maximum_selected_runs": (
            maximum_selected_runs * record_bytes
        ),
        "complete_wire_bytes_at_maximum_selected_runs": (
            maximum_selected_runs * record_bytes
            + constants.HEADER_SIZE
            + constants.TRAILER_SIZE
        ),
        "minimum_average_run_items": {
            "logical_items_numerator": logical_items,
            "run_records_denominator": maximum_selected_runs,
            "reduced_numerator": average.numerator,
            "reduced_denominator": average.denominator,
            "value": float(average),
        },
        "minimum_uniform_integer_run_items": minimum_uniform_run,
    }


def _workload_result(
    workload: RLECorpusWorkload,
    frames: Sequence[_FrameCase],
    *,
    batch_count: int,
    iterations_per_batch: int,
    warmup_iterations: int,
) -> RLEWorkloadResult:
    raw_payload_bytes = sum(
        decode_v2_frame(frame.raw_wire).header.payload_length for frame in frames
    )
    selected_payload_bytes = sum(
        frame.selected_frame.header.payload_length for frame in frames
    )
    raw_wire_bytes = sum(len(frame.raw_wire) for frame in frames)
    selected_wire_bytes = sum(len(frame.selected_wire) for frame in frames)
    rle_frames = sum(
        frame.selected_frame.header.encoding is constants.FrameEncoding.RLE
        for frame in frames
    )
    fallback_frames = len(frames) - rle_frames
    no_expansion = all(
        frame.selected_frame.header.payload_length <= len(frame.payload)
        and len(frame.selected_wire) <= len(frame.raw_wire)
        for frame in frames
    )
    return RLEWorkloadResult(
        workload=workload,
        corpus_sha256=_payload_digest(workload),
        raw_payload_bytes=raw_payload_bytes,
        selected_payload_bytes=selected_payload_bytes,
        raw_wire_bytes=raw_wire_bytes,
        selected_wire_bytes=selected_wire_bytes,
        rle_frames=rle_frames,
        fallback_frames=fallback_frames,
        round_trip_equal=all(frame.round_trip_equal for frame in frames),
        no_expansion=no_expansion,
        run_lengths=_run_distribution(frames),
        timing=_timings(
            frames,
            batch_count=batch_count,
            iterations_per_batch=iterations_per_batch,
            warmup_iterations=warmup_iterations,
        ),
        memory=_memory_results(frames),
    )


def _grade(workloads: Sequence[RLEWorkloadResult]) -> tuple[BenchmarkCheck, ...]:
    round_trip_failures = [
        result.workload.name for result in workloads if not result.round_trip_equal
    ]
    expansion_failures = [
        result.workload.name for result in workloads if not result.no_expansion
    ]
    memory_failures = [
        f"{result.workload.name}:{memory.path}={memory.peak_bytes}"
        for result in workloads
        for memory in result.memory
        if not memory.within_limit
    ]
    decode_paths = {
        result.workload.name: result.path("rle_auto_decode") for result in workloads
    }
    decode_headrooms = {
        name: path.minimum_target_headroom for name, path in decode_paths.items()
    }
    minimum_decode_name = min(decode_headrooms, key=decode_headrooms.__getitem__)
    minimum_decode_headroom = decode_headrooms[minimum_decode_name]
    long_hold = next(
        result for result in workloads if result.workload.requires_strong_gpio_savings
    )
    fallback_failures = [
        result.workload.name
        for result in workloads
        if result.workload.requires_raw_fallback
        and result.fallback_frames != len(result.workload.payloads)
    ]
    adc_ratios = {
        result.workload.name: result.complete_wire_ratio.value
        for result in workloads
        if result.workload.stream == "ADC"
    }
    return (
        BenchmarkCheck(
            name="perfect_round_trip_equality",
            required=True,
            passed=not round_trip_failures,
            expected="every RAW and RLE_AUTO decode equals the logical corpus",
            observed=round_trip_failures or "all workloads equal",
            detail="checks complete payloads and logical envelope fields",
        ),
        BenchmarkCheck(
            name="rle_auto_no_expansion",
            required=True,
            passed=not expansion_failures,
            expected="selected payload and complete wire bytes <= RAW per frame",
            observed=expansion_failures or "no expanded frames",
            detail="uses exact per-frame payload and complete-wire byte counts",
        ),
        BenchmarkCheck(
            name="decode_throughput_headroom",
            required=True,
            passed=minimum_decode_headroom >= float(REQUIRED_DECODE_HEADROOM),
            expected={
                "minimum_headroom": float(REQUIRED_DECODE_HEADROOM),
                "minimum_logical_bytes_per_second": (REQUIRED_DECODE_BYTES_PER_SECOND),
            },
            observed={
                "workload": minimum_decode_name,
                "minimum_headroom": minimum_decode_headroom,
                "minimum_logical_bytes_per_second": decode_paths[
                    minimum_decode_name
                ].minimum_bytes_per_second,
            },
            detail=(
                "headroom uses the exact 4,048-byte / 8,096-tick logical "
                "denominator for one target stream"
            ),
        ),
        BenchmarkCheck(
            name="bounded_peak_working_memory",
            required=True,
            passed=not memory_failures,
            expected={"maximum_peak_bytes": MAX_CODEC_PEAK_BYTES},
            observed=memory_failures or "all measured paths within bound",
            detail="isolated tracemalloc peaks include the returned wire or block",
        ),
        BenchmarkCheck(
            name="strong_gpio_long_hold_savings",
            required=True,
            passed=(
                Fraction(
                    long_hold.selected_wire_bytes,
                    long_hold.raw_wire_bytes,
                )
                <= MAX_LONG_HOLD_GPIO_WIRE_RATIO
                and long_hold.fallback_frames == 0
            ),
            expected={
                "maximum_complete_wire_ratio": float(MAX_LONG_HOLD_GPIO_WIRE_RATIO),
                "fallback_frames": 0,
            },
            observed={
                "complete_wire_ratio": long_hold.complete_wire_ratio.value,
                "fallback_frames": long_hold.fallback_frames,
            },
            detail="the threshold is GPIO-only; ADC savings have no minimum",
        ),
        BenchmarkCheck(
            name="incompressible_frames_fall_back_to_raw",
            required=True,
            passed=not fallback_failures,
            expected="every marked incompressible frame selects RAW",
            observed=fallback_failures or "all incompressible frames used RAW",
            detail=(
                "covers alternating/pseudo-random GPIO and quantization/high-"
                "entropy ADC"
            ),
        ),
        BenchmarkCheck(
            name="adc_savings_observed_without_minimum",
            required=False,
            passed=True,
            expected="no ADC compression-ratio threshold",
            observed=adc_ratios,
            detail="ADC compression remains workload-dependent evidence only",
        ),
    )


def benchmark_rle_corpus(
    *,
    frames_per_workload: int = DEFAULT_FRAMES_PER_WORKLOAD,
    batch_count: int = DEFAULT_BATCH_COUNT,
    iterations_per_batch: int = DEFAULT_ITERATIONS_PER_BATCH,
    warmup_iterations: int = DEFAULT_WARMUP_ITERATIONS,
) -> RLECorpusBenchmarkResult:
    """Run the bounded production-codec corpus benchmark and grade it.

    The target denominator is one logical ADC or GPIO stream:
    ``4048 bytes * 8_000_000 ticks/s / 8096 ticks/frame = 4_000_000 B/s``.
    The selected decode path must sustain at least 1.25 times that rate for
    every workload and every timed batch.
    """

    frame_count = _positive_bounded(
        "frames_per_workload",
        frames_per_workload,
        MAX_FRAMES_PER_WORKLOAD,
    )
    batches = _positive_bounded("batch_count", batch_count, MAX_BATCH_COUNT)
    iterations = _positive_bounded(
        "iterations_per_batch",
        iterations_per_batch,
        MAX_ITERATIONS_PER_BATCH,
    )
    warmups = _nonnegative_bounded(
        "warmup_iterations",
        warmup_iterations,
        MAX_WARMUP_ITERATIONS,
    )
    workload_count = len(_workload_definitions())
    processed = (
        workload_count
        * frame_count
        * constants.DATA_PAYLOAD_BYTES
        * (batches * iterations + warmups)
        * 4  # RAW/RLE_AUTO encode and decode paths.
    )
    if processed > MAX_PROCESSED_LOGICAL_BYTES:
        raise ValueError("benchmark exceeds its processed logical-byte bound")

    corpus = build_rle_corpus(frame_count)
    results: list[RLEWorkloadResult] = []
    for workload_index, workload in enumerate(corpus, start=1):
        frames = _frame_workload(workload, run_id=0x524C_4500 + workload_index)
        results.append(
            _workload_result(
                workload,
                frames,
                batch_count=batches,
                iterations_per_batch=iterations,
                warmup_iterations=warmups,
            )
        )
    workload_results = tuple(results)
    return RLECorpusBenchmarkResult(
        frames_per_workload=frame_count,
        batch_count=batches,
        iterations_per_batch=iterations,
        warmup_iterations=warmups,
        corpus_sha256=_corpus_digest(corpus),
        workloads=workload_results,
        checks=_grade(workload_results),
    )


def benchmark_report(result: RLECorpusBenchmarkResult) -> dict[str, object]:
    """Return stable-key JSON data for one measured benchmark result."""

    if not isinstance(result, RLECorpusBenchmarkResult):
        raise TypeError("result must be an RLECorpusBenchmarkResult")
    return result.to_dict()


def _positive_argument(name: str, maximum: int) -> Callable[[str], int]:
    def parse(value: str) -> int:
        try:
            selected = int(value, 10)
        except ValueError as error:
            raise argparse.ArgumentTypeError(
                f"{name} must be a decimal integer"
            ) from error
        try:
            return _positive_bounded(name, selected, maximum)
        except (TypeError, ValueError) as error:
            raise argparse.ArgumentTypeError(str(error)) from error

    return parse


def _warmup_argument(value: str) -> int:
    try:
        selected = int(value, 10)
    except ValueError as error:
        raise argparse.ArgumentTypeError(
            "warmup_iterations must be a decimal integer"
        ) from error
    try:
        return _nonnegative_bounded(
            "warmup_iterations",
            selected,
            MAX_WARMUP_ITERATIONS,
        )
    except (TypeError, ValueError) as error:
        raise argparse.ArgumentTypeError(str(error)) from error


def parse_args(argv: Sequence[str] | None = None) -> argparse.Namespace:
    parser = argparse.ArgumentParser(
        description=(
            "Benchmark exact RAW and adaptive-RLE framing over a deterministic "
            "nine-workload host corpus."
        )
    )
    parser.add_argument(
        "--frames-per-workload",
        type=_positive_argument("frames_per_workload", MAX_FRAMES_PER_WORKLOAD),
        default=DEFAULT_FRAMES_PER_WORKLOAD,
    )
    parser.add_argument(
        "--batches",
        type=_positive_argument("batch_count", MAX_BATCH_COUNT),
        default=DEFAULT_BATCH_COUNT,
    )
    parser.add_argument(
        "--iterations",
        type=_positive_argument(
            "iterations_per_batch",
            MAX_ITERATIONS_PER_BATCH,
        ),
        default=DEFAULT_ITERATIONS_PER_BATCH,
    )
    parser.add_argument(
        "--warmups",
        type=_warmup_argument,
        default=DEFAULT_WARMUP_ITERATIONS,
    )
    parser.add_argument(
        "--pretty",
        action="store_true",
        help="indent JSON output instead of emitting one compact line",
    )
    return parser.parse_args(argv)


def main(argv: Sequence[str] | None = None) -> int:
    arguments = parse_args(argv)
    try:
        result = benchmark_rle_corpus(
            frames_per_workload=arguments.frames_per_workload,
            batch_count=arguments.batches,
            iterations_per_batch=arguments.iterations,
            warmup_iterations=arguments.warmups,
        )
    except (RLECorpusBenchmarkError, TypeError, ValueError) as error:
        raise SystemExit(f"RLE corpus benchmark failed: {error}") from error
    print(
        json.dumps(
            benchmark_report(result),
            allow_nan=False,
            indent=2 if arguments.pretty else None,
            sort_keys=True,
        )
    )
    return 0 if result.passed else 1


if __name__ == "__main__":
    raise SystemExit(main())


__all__ = [
    "DEFAULT_BATCH_COUNT",
    "DEFAULT_FRAMES_PER_WORKLOAD",
    "DEFAULT_ITERATIONS_PER_BATCH",
    "DEFAULT_WARMUP_ITERATIONS",
    "MAX_CODEC_PEAK_BYTES",
    "MAX_LONG_HOLD_GPIO_WIRE_RATIO",
    "REQUIRED_DECODE_BYTES_PER_SECOND",
    "REQUIRED_DECODE_HEADROOM",
    "TARGET_LOGICAL_BYTES_PER_SECOND",
    "BenchmarkCheck",
    "CodecMemoryResult",
    "CodecPathResult",
    "ExactRatio",
    "RLECorpusBenchmarkError",
    "RLECorpusBenchmarkResult",
    "RLECorpusWorkload",
    "RLEWorkloadResult",
    "RunLengthDistribution",
    "benchmark_report",
    "benchmark_rle_corpus",
    "build_rle_corpus",
    "main",
]
