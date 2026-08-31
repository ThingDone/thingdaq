"""Bounded host benchmarks for exact protocol encode and validation paths."""

from __future__ import annotations

import argparse
import json
import os
import platform
import struct
from dataclasses import dataclass
from statistics import median
from time import perf_counter

from ._generated import protocol_constants as constants
from .checksum import HOST_SUPPORTED_CHECKSUM_ALGORITHMS
from .protocol import checksum_backend, decode_frame, encode_frame
from .synthetic import synthetic_adc_payload, synthetic_gpio_payload

DEFAULT_BATCH_COUNT = 5
DEFAULT_ITERATIONS_PER_BATCH = 16
DEFAULT_WARMUP_OPERATIONS = 4
MAX_BATCH_COUNT = 32
MAX_ITERATIONS_PER_BATCH = 4_096
MAX_PROCESSED_FRAME_BYTES = 512 * 1024 * 1024
_TRAILER = struct.Struct("<I")


@dataclass(frozen=True, slots=True)
class HostChecksumPathResult:
    """Repeated timings for one encode or validation path."""

    operation: str
    batch_seconds: tuple[float, ...]
    iterations_per_batch: int
    frame_bytes: int
    deterministic_digest: int

    @property
    def operations(self) -> int:
        return len(self.batch_seconds) * self.iterations_per_batch

    @property
    def processed_frame_bytes(self) -> int:
        return self.operations * self.frame_bytes

    @property
    def batch_frame_bytes(self) -> int:
        return self.iterations_per_batch * self.frame_bytes

    @property
    def bytes_per_second_samples(self) -> tuple[float, ...]:
        return tuple(self.batch_frame_bytes / seconds for seconds in self.batch_seconds)

    @property
    def minimum_bytes_per_second(self) -> float:
        return min(self.bytes_per_second_samples)

    @property
    def median_bytes_per_second(self) -> float:
        return median(self.bytes_per_second_samples)

    @property
    def maximum_bytes_per_second(self) -> float:
        return max(self.bytes_per_second_samples)

    def to_dict(self) -> dict[str, object]:
        """Return stable JSON-compatible timing data without a pass/fail verdict."""

        return {
            "operation": self.operation,
            "batch_seconds": self.batch_seconds,
            "batch_count": len(self.batch_seconds),
            "iterations_per_batch": self.iterations_per_batch,
            "operations": self.operations,
            "frame_bytes": self.frame_bytes,
            "processed_frame_bytes": self.processed_frame_bytes,
            "minimum_bytes_per_second": self.minimum_bytes_per_second,
            "median_bytes_per_second": self.median_bytes_per_second,
            "maximum_bytes_per_second": self.maximum_bytes_per_second,
            "deterministic_digest": self.deterministic_digest,
        }


@dataclass(frozen=True, slots=True)
class HostChecksumBenchmarkResult:
    """Separate encode and validation timings for one representative frame."""

    checksum_algorithm: constants.ChecksumAlgorithm
    backend_implementation: str
    backend_accelerated: bool
    frame_kind: constants.FrameKind
    frame_bytes: int
    checksum_coverage_bytes: int
    warmup_operations: int
    encode: HostChecksumPathResult
    validation: HostChecksumPathResult

    def to_dict(self) -> dict[str, object]:
        return {
            "checksum_algorithm": self.checksum_algorithm.name,
            "checksum_algorithm_id": int(self.checksum_algorithm),
            "backend_implementation": self.backend_implementation,
            "backend_accelerated": self.backend_accelerated,
            "frame_kind": self.frame_kind.name,
            "frame_bytes": self.frame_bytes,
            "checksum_coverage_bytes": self.checksum_coverage_bytes,
            "warmup_operations": self.warmup_operations,
            "encode": self.encode.to_dict(),
            "validation": self.validation.to_dict(),
        }


def _mix_digest(digest: int, value: int) -> int:
    return ((digest << 5) - digest + value) & constants.UINT32_MAX


def _representative_fields(
    kind: constants.FrameKind,
) -> tuple[bytes, int]:
    if kind is constants.FrameKind.ADC_DATA:
        return synthetic_adc_payload(0), constants.ADC_PAIRS_PER_FRAME
    if kind is constants.FrameKind.GPIO_DATA:
        return synthetic_gpio_payload(0), constants.GPIO_SAMPLES_PER_FRAME
    raise ValueError("checksum benchmark frame kind must be ADC_DATA or GPIO_DATA")


def _encode_representative(
    kind: constants.FrameKind,
    algorithm: constants.ChecksumAlgorithm,
    payload: bytes,
    item_count: int,
) -> bytes:
    return encode_frame(
        kind,
        payload,
        flags=constants.FrameFlag.SYNTHETIC | constants.FrameFlag.EPOCH_START,
        checksum_algorithm=algorithm,
        run_id=1,
        sequence=0,
        first_sample_ticks=0,
        item_count=item_count,
    )


def _validate_bounds(
    batch_count: int,
    iterations_per_batch: int,
    warmup_operations: int,
) -> None:
    values = (batch_count, iterations_per_batch, warmup_operations)
    if any(not isinstance(value, int) or isinstance(value, bool) for value in values):
        raise TypeError("benchmark repetition counts must be integers")
    if not 1 <= batch_count <= MAX_BATCH_COUNT:
        raise ValueError(f"batch_count must be between 1 and {MAX_BATCH_COUNT}")
    if not 1 <= iterations_per_batch <= MAX_ITERATIONS_PER_BATCH:
        raise ValueError(
            f"iterations_per_batch must be between 1 and {MAX_ITERATIONS_PER_BATCH}"
        )
    if not 0 <= warmup_operations <= MAX_ITERATIONS_PER_BATCH:
        raise ValueError(
            f"warmup_operations must be between 0 and {MAX_ITERATIONS_PER_BATCH}"
        )


def _benchmark_one(
    algorithm: constants.ChecksumAlgorithm,
    kind: constants.FrameKind,
    *,
    batch_count: int,
    iterations_per_batch: int,
    warmup_operations: int,
) -> HostChecksumBenchmarkResult:
    backend = checksum_backend(algorithm)
    payload, item_count = _representative_fields(kind)
    wire = _encode_representative(kind, algorithm, payload, item_count)
    expected_checksum = _TRAILER.unpack_from(wire, len(wire) - constants.TRAILER_SIZE)[
        0
    ]

    for _ in range(warmup_operations):
        warmed_wire = _encode_representative(kind, algorithm, payload, item_count)
        warmed_frame = decode_frame(wire)
        if warmed_wire != wire or warmed_frame.checksum != expected_checksum:
            raise RuntimeError("checksum benchmark warm-up changed deterministic data")

    encode_seconds: list[float] = []
    encode_digest = 0
    for _ in range(batch_count):
        started = perf_counter()
        for _ in range(iterations_per_batch):
            encoded = _encode_representative(kind, algorithm, payload, item_count)
            encoded_checksum = _TRAILER.unpack_from(
                encoded, len(encoded) - constants.TRAILER_SIZE
            )[0]
            encode_digest = _mix_digest(encode_digest, encoded_checksum)
        encode_seconds.append(max(perf_counter() - started, 1e-12))

    validation_seconds: list[float] = []
    validation_digest = 0
    for _ in range(batch_count):
        started = perf_counter()
        for _ in range(iterations_per_batch):
            decoded = decode_frame(wire)
            validation_digest = _mix_digest(
                validation_digest,
                decoded.checksum ^ int(decoded.header.checksum_algorithm),
            )
        validation_seconds.append(max(perf_counter() - started, 1e-12))

    encode_result = HostChecksumPathResult(
        operation="encode",
        batch_seconds=tuple(encode_seconds),
        iterations_per_batch=iterations_per_batch,
        frame_bytes=len(wire),
        deterministic_digest=encode_digest,
    )
    validation_result = HostChecksumPathResult(
        operation="validation",
        batch_seconds=tuple(validation_seconds),
        iterations_per_batch=iterations_per_batch,
        frame_bytes=len(wire),
        deterministic_digest=validation_digest,
    )
    return HostChecksumBenchmarkResult(
        checksum_algorithm=algorithm,
        backend_implementation=backend.implementation,
        backend_accelerated=backend.accelerated,
        frame_kind=kind,
        frame_bytes=len(wire),
        checksum_coverage_bytes=len(wire) - constants.TRAILER_SIZE,
        warmup_operations=warmup_operations,
        encode=encode_result,
        validation=validation_result,
    )


def benchmark_checksum_throughput(
    algorithms: tuple[constants.ChecksumAlgorithm, ...] | None = None,
    *,
    batch_count: int = DEFAULT_BATCH_COUNT,
    iterations_per_batch: int = DEFAULT_ITERATIONS_PER_BATCH,
    warmup_operations: int = DEFAULT_WARMUP_OPERATIONS,
) -> tuple[HostChecksumBenchmarkResult, ...]:
    """Benchmark full encode and validation paths without compatibility gates.

    Corpus construction and warm-up are excluded.  The two production 4,096-byte
    data layouts are measured independently because ADC typed validation performs
    additional range checks.  Results intentionally contain no qualification or
    pass/fail field: host speed cannot change a wire algorithm's compatibility.
    """

    _validate_bounds(batch_count, iterations_per_batch, warmup_operations)
    selected = (
        tuple(sorted(HOST_SUPPORTED_CHECKSUM_ALGORITHMS, key=int))
        if algorithms is None
        else algorithms
    )
    if not selected:
        raise ValueError("at least one checksum algorithm is required")
    if len(set(selected)) != len(selected):
        raise ValueError("checksum benchmark algorithms must be unique")
    for algorithm in selected:
        checksum_backend(algorithm)
    processed = (
        (batch_count * iterations_per_batch + warmup_operations)
        * constants.DATA_FRAME_BYTES
        * len(selected)
        * 2  # ADC and GPIO layouts.
        * 2  # Encode and validation paths.
    )
    if processed > MAX_PROCESSED_FRAME_BYTES:
        raise ValueError("benchmark exceeds its processed-byte bound")

    return tuple(
        _benchmark_one(
            algorithm,
            kind,
            batch_count=batch_count,
            iterations_per_batch=iterations_per_batch,
            warmup_operations=warmup_operations,
        )
        for algorithm in selected
        for kind in (constants.FrameKind.ADC_DATA, constants.FrameKind.GPIO_DATA)
    )


def benchmark_report(
    results: tuple[HostChecksumBenchmarkResult, ...],
) -> dict[str, object]:
    """Wrap measurements with reproducibility metadata."""

    return {
        "schema": "thingdaq-python-checksum-benchmark-v1",
        "python_implementation": platform.python_implementation(),
        "python_version": platform.python_version(),
        "platform": platform.platform(),
        "machine": platform.machine(),
        "processor": platform.processor() or "unknown",
        "cpu_count": os.cpu_count(),
        "target_framed_bytes_per_second": (
            constants.CHECKSUM_BENCHMARK_TARGET_FRAMED_BYTES_PER_SECOND
        ),
        "performance_is_wire_compatibility": False,
        "results": tuple(result.to_dict() for result in results),
    }


def _parse_algorithms(value: str) -> tuple[constants.ChecksumAlgorithm, ...] | None:
    if value == "all":
        return None
    selected: list[constants.ChecksumAlgorithm] = []
    by_name = {
        algorithm.name.lower(): algorithm
        for algorithm in HOST_SUPPORTED_CHECKSUM_ALGORITHMS
    }
    for name in value.split(","):
        normalized = name.strip().lower().replace("-", "_")
        try:
            selected.append(by_name[normalized])
        except KeyError as exc:
            choices = ", ".join(sorted(by_name))
            raise ValueError(
                f"unknown checksum {name!r}; expected all or {choices}"
            ) from exc
    return tuple(selected)


def main(argv: list[str] | None = None) -> int:
    parser = argparse.ArgumentParser(
        description="Measure Python protocol checksum encode/validation throughput",
    )
    parser.add_argument("--algorithms", default="all")
    parser.add_argument("--batches", type=int, default=DEFAULT_BATCH_COUNT)
    parser.add_argument("--iterations", type=int, default=DEFAULT_ITERATIONS_PER_BATCH)
    parser.add_argument("--warmups", type=int, default=DEFAULT_WARMUP_OPERATIONS)
    arguments = parser.parse_args(argv)
    try:
        algorithms = _parse_algorithms(arguments.algorithms)
        results = benchmark_checksum_throughput(
            algorithms,
            batch_count=arguments.batches,
            iterations_per_batch=arguments.iterations,
            warmup_operations=arguments.warmups,
        )
    except (TypeError, ValueError) as error:
        parser.error(str(error))
    print(json.dumps(benchmark_report(results), sort_keys=True))
    return 0


if __name__ == "__main__":
    raise SystemExit(main())


__all__ = [
    "DEFAULT_BATCH_COUNT",
    "DEFAULT_ITERATIONS_PER_BATCH",
    "DEFAULT_WARMUP_OPERATIONS",
    "HostChecksumBenchmarkResult",
    "HostChecksumPathResult",
    "benchmark_checksum_throughput",
    "benchmark_report",
]
