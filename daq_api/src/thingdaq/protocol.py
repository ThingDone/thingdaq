"""Protocol-v1 frame encoding, validation, and incremental parsing."""

from __future__ import annotations

import struct
from dataclasses import dataclass

from ._generated import protocol_constants as constants
from ._incremental import BoundedIncrementalParser, BytesLike
from ._incremental import ParserCounters as _SharedParserCounters
from .checksum import (
    HOST_SUPPORTED_CHECKSUM_ALGORITHMS,
    ChecksumBackend,
    compute_checksum_value,
)
from .checksum import (
    checksum_backend as _checksum_backend,
)

_HEADER = struct.Struct(constants.HEADER_STRUCT_FORMAT)
_TRAILER = struct.Struct("<I")
_CONFIGURATION = struct.Struct("<BBBBI")
_CHECKSUM_BENCHMARK_REQUEST = struct.Struct("<BBBBHH")
_GPIO_CLOCK_DIAGNOSTIC_REQUEST = struct.Struct("<IHH")
_RESPONSE_PREFIX = struct.Struct("<BBH")
_DATA_KINDS = frozenset({constants.FrameKind.ADC_DATA, constants.FrameKind.GPIO_DATA})
_REQUEST_KINDS = frozenset(constants.REQUEST_RESPONSE_KIND)
_TYPED_RESPONSE_KINDS = frozenset(constants.REQUEST_RESPONSE_KIND.values())
_MAX_FRAME_BYTES = max(
    constants.MAX_DATA_FRAME_BYTES,
    constants.MAX_CONTROL_FRAME_BYTES,
)
MAX_BUFFERED_BYTES = _MAX_FRAME_BYTES + len(constants.MAGIC_BYTES) - 1


class ProtocolError(ValueError):
    """Base exception for malformed or unsupported protocol data."""


class FrameValidationError(ProtocolError):
    """A frame violates a protocol-v1 structural or typed-field rule."""

    def __init__(
        self,
        message: str,
        error_code: constants.ErrorCode = constants.ErrorCode.INVALID_PAYLOAD,
    ) -> None:
        super().__init__(message)
        self.error_code = error_code


class UnsupportedChecksumError(FrameValidationError):
    """The frame selects a checksum algorithm not enabled in protocol v1."""

    def __init__(self, algorithm: int) -> None:
        super().__init__(
            f"unsupported checksum algorithm {algorithm}",
            constants.ErrorCode.UNSUPPORTED_CHECKSUM,
        )
        self.algorithm = algorithm


class ChecksumAlgorithmMismatchError(FrameValidationError):
    """A control frame did not use the fixed bootstrap checksum."""

    def __init__(self, observed: int, expected: int) -> None:
        super().__init__(
            f"checksum algorithm {observed} is invalid for a control frame; "
            f"expected bootstrap algorithm {expected}",
            constants.ErrorCode.UNSUPPORTED_CHECKSUM,
        )
        self.observed = observed
        self.expected = expected


class ChecksumMismatchError(FrameValidationError):
    """The checksum trailer does not match the frame header and payload."""

    def __init__(self, expected: int, observed: int) -> None:
        super().__init__(
            f"checksum mismatch: expected 0x{expected:08x}, observed 0x{observed:08x}",
            constants.ErrorCode.CHECKSUM_MISMATCH,
        )
        self.expected = expected
        self.observed = observed


@dataclass(frozen=True, slots=True)
class FrameHeader:
    """Decoded protocol-v1 header fields."""

    kind: constants.FrameKind
    flags: constants.FrameFlag
    checksum_algorithm: constants.ChecksumAlgorithm
    total_length: int
    payload_length: int
    run_id: int
    sequence: int
    request_id: int
    first_sample_ticks: int
    item_count: int
    version: int = constants.PROTOCOL_VERSION
    header_length: int = constants.HEADER_SIZE

    def to_bytes(self) -> bytes:
        """Serialize the header using the fixed little-endian layout."""

        return _HEADER.pack(
            constants.MAGIC,
            self.version,
            int(self.kind),
            int(self.flags),
            self.header_length,
            int(self.checksum_algorithm),
            0,
            self.total_length,
            self.payload_length,
            self.run_id,
            self.sequence,
            self.request_id,
            self.first_sample_ticks,
            self.item_count,
        )


@dataclass(frozen=True, slots=True)
class Frame:
    """A fully validated frame with its payload retained as immutable bytes."""

    header: FrameHeader
    payload: bytes
    checksum: int

    def to_bytes(self) -> bytes:
        """Return the exact wire representation of this decoded frame."""

        return self.header.to_bytes() + self.payload + _TRAILER.pack(self.checksum)

    @property
    def payload_view(self) -> memoryview:
        """Return a zero-copy read-only view over the owned payload bytes."""

        return memoryview(self.payload)


@dataclass(frozen=True, slots=True)
class ParserCounters(_SharedParserCounters):
    """Protocol-v1 counter type backed by the shared bounded framing core."""


def compute_checksum(
    data: BytesLike,
    algorithm: constants.ChecksumAlgorithm | int = (
        constants.DEFAULT_CHECKSUM_ALGORITHM
    ),
) -> int:
    """Compute an enabled protocol checksum through the algorithm dispatch."""

    try:
        selected = constants.ChecksumAlgorithm(algorithm)
    except ValueError as exc:
        raise UnsupportedChecksumError(int(algorithm)) from exc
    result = compute_checksum_value(data, selected)
    if result is None:
        raise UnsupportedChecksumError(int(selected))
    return result


def checksum_backend(
    algorithm: constants.ChecksumAlgorithm | int,
) -> ChecksumBackend:
    """Describe the exact host implementation for a protocol algorithm."""

    try:
        selected = constants.ChecksumAlgorithm(algorithm)
    except ValueError as exc:
        raise UnsupportedChecksumError(int(algorithm)) from exc
    backend = _checksum_backend(selected)
    if backend is None:
        raise UnsupportedChecksumError(int(selected))
    return backend


def _uint(name: str, value: int, bits: int) -> int:
    maximum = (1 << bits) - 1
    if not isinstance(value, int) or not 0 <= value <= maximum:
        raise FrameValidationError(
            f"{name} must be an unsigned {bits}-bit integer",
            constants.ErrorCode.INVALID_PAYLOAD,
        )
    return value


def _decode_header(data: BytesLike, offset: int = 0) -> FrameHeader:
    available = len(data) - offset
    if offset < 0 or available < constants.HEADER_SIZE:
        raise FrameValidationError(
            f"frame has {max(available, 0)} bytes; "
            f"a header needs {constants.HEADER_SIZE}",
            constants.ErrorCode.INVALID_LENGTH,
        )
    (
        magic,
        version,
        raw_kind,
        raw_flags,
        header_length,
        raw_checksum_algorithm,
        reserved,
        total_length,
        payload_length,
        run_id,
        sequence,
        request_id,
        first_sample_ticks,
        item_count,
    ) = _HEADER.unpack_from(data, offset)

    if magic != constants.MAGIC:
        raise FrameValidationError(
            "invalid frame magic", constants.ErrorCode.INVALID_LENGTH
        )
    if version != constants.PROTOCOL_VERSION:
        raise FrameValidationError(
            f"unsupported protocol version {version}",
            constants.ErrorCode.UNSUPPORTED_VERSION,
        )
    try:
        kind = constants.FrameKind(raw_kind)
    except ValueError as exc:
        raise FrameValidationError(
            f"unknown frame kind 0x{raw_kind:02x}",
            constants.ErrorCode.UNKNOWN_FRAME_KIND,
        ) from exc
    try:
        checksum_algorithm = constants.ChecksumAlgorithm(raw_checksum_algorithm)
    except ValueError as exc:
        raise UnsupportedChecksumError(raw_checksum_algorithm) from exc

    header = FrameHeader(
        kind=kind,
        flags=constants.FrameFlag(raw_flags),
        checksum_algorithm=checksum_algorithm,
        total_length=total_length,
        payload_length=payload_length,
        run_id=run_id,
        sequence=sequence,
        request_id=request_id,
        first_sample_ticks=first_sample_ticks,
        item_count=item_count,
        version=version,
        header_length=header_length,
    )
    _validate_header(header, reserved)
    return header


def _validate_header(header: FrameHeader, reserved: int = 0) -> None:
    if header.header_length != constants.HEADER_SIZE:
        raise FrameValidationError(
            f"header length must be {constants.HEADER_SIZE}",
            constants.ErrorCode.INVALID_LENGTH,
        )
    if reserved != 0:
        raise FrameValidationError(
            "header reserved byte must be zero",
            constants.ErrorCode.INVALID_PAYLOAD,
        )
    if header.checksum_algorithm not in HOST_SUPPORTED_CHECKSUM_ALGORITHMS:
        raise UnsupportedChecksumError(int(header.checksum_algorithm))
    if (
        header.kind not in _DATA_KINDS
        and header.checksum_algorithm != constants.BOOTSTRAP_CHECKSUM_ALGORITHM
    ):
        raise ChecksumAlgorithmMismatchError(
            int(header.checksum_algorithm),
            int(constants.BOOTSTRAP_CHECKSUM_ALGORITHM),
        )

    allowed_flags = int(constants.ALLOWED_FLAGS_BY_KIND[header.kind])
    if int(header.flags) & (~allowed_flags & 0xFFFF):
        raise FrameValidationError(
            f"flags 0x{int(header.flags):04x} are invalid for {header.kind.name}",
            constants.ErrorCode.INVALID_FLAGS,
        )
    if header.flags & constants.FrameFlag.OVERRUN_BEFORE and not (
        header.flags & constants.FrameFlag.GAP_BEFORE
    ):
        raise FrameValidationError(
            "OVERRUN_BEFORE requires GAP_BEFORE",
            constants.ErrorCode.INVALID_FLAGS,
        )
    expected_total = (
        constants.HEADER_SIZE + header.payload_length + constants.TRAILER_SIZE
    )
    if header.total_length != expected_total:
        raise FrameValidationError(
            "total and payload lengths are inconsistent",
            constants.ErrorCode.INVALID_LENGTH,
        )

    if header.kind in _DATA_KINDS:
        if (
            header.total_length != constants.DATA_FRAME_BYTES
            or header.payload_length != constants.DATA_PAYLOAD_BYTES
        ):
            raise FrameValidationError(
                "data frames must be exactly 4096 bytes",
                constants.ErrorCode.INVALID_LENGTH,
            )
        expected_items = (
            constants.ADC_PAIRS_PER_FRAME
            if header.kind is constants.FrameKind.ADC_DATA
            else constants.GPIO_SAMPLES_PER_FRAME
        )
        if header.item_count != expected_items:
            raise FrameValidationError(
                f"{header.kind.name} item_count must be {expected_items}",
                constants.ErrorCode.INVALID_LENGTH,
            )
        if header.run_id == 0 or header.request_id != 0:
            raise FrameValidationError(
                "data frames require a nonzero run ID and zero request ID",
                constants.ErrorCode.INVALID_PAYLOAD,
            )
        period_ticks = (
            constants.ADC_PAIR_PERIOD_TICKS
            if header.kind is constants.FrameKind.ADC_DATA
            else constants.GPIO_SAMPLE_PERIOD_TICKS
        )
        if header.first_sample_ticks % period_ticks:
            raise FrameValidationError(
                "data timestamp is not aligned to its logical-item period",
                constants.ErrorCode.INVALID_PAYLOAD,
            )
        epoch_start = bool(header.flags & constants.FrameFlag.EPOCH_START)
        first_in_epoch = header.sequence == 0 and header.first_sample_ticks == 0
        if epoch_start != first_in_epoch:
            raise FrameValidationError(
                "EPOCH_START must identify sequence zero at timestamp zero",
                constants.ErrorCode.INVALID_PAYLOAD,
            )
        return

    if (
        not constants.MIN_FRAME_BYTES
        <= header.total_length
        <= (constants.MAX_CONTROL_FRAME_BYTES)
    ):
        raise FrameValidationError(
            "control frame exceeds protocol-v1 bounds",
            constants.ErrorCode.INVALID_LENGTH,
        )
    if header.request_id == 0:
        raise FrameValidationError(
            "control frames require a nonzero request ID",
            constants.ErrorCode.INVALID_REQUEST_ID,
        )
    if header.sequence != 0 or header.first_sample_ticks != 0 or header.item_count != 0:
        raise FrameValidationError(
            "control sequence, timestamp, and item-count fields must be zero",
            constants.ErrorCode.INVALID_PAYLOAD,
        )
    if header.kind in _REQUEST_KINDS and header.run_id != 0:
        raise FrameValidationError(
            "request run ID must be zero", constants.ErrorCode.INVALID_PAYLOAD
        )
    if (
        header.kind in _REQUEST_KINDS
        and header.total_length > constants.MAX_COMMAND_FRAME_BYTES
    ):
        raise FrameValidationError(
            "command frame exceeds the protocol-v1 command bound",
            constants.ErrorCode.INVALID_LENGTH,
        )

    response_error = bool(header.flags & constants.FrameFlag.RESPONSE_ERROR)
    if header.kind in _TYPED_RESPONSE_KINDS:
        schema = (
            constants.ERROR_PAYLOAD_SCHEMA_BY_KIND[header.kind]
            if response_error
            else constants.PAYLOAD_SCHEMA_BY_KIND[header.kind]
        )
        expected_payload = constants.PAYLOAD_SIZE_BY_SCHEMA[schema]
    elif header.kind is constants.FrameKind.ERROR_RESPONSE:
        if not response_error:
            raise FrameValidationError(
                "ERROR_RESPONSE requires RESPONSE_ERROR",
                constants.ErrorCode.INVALID_FLAGS,
            )
        expected_payload = constants.ERROR_RESPONSE_PAYLOAD_SIZE
    else:
        schema = constants.PAYLOAD_SCHEMA_BY_KIND[header.kind]
        expected_payload = constants.PAYLOAD_SIZE_BY_SCHEMA[schema]
    if header.payload_length != expected_payload:
        raise FrameValidationError(
            f"{header.kind.name} payload must be {expected_payload} bytes",
            constants.ErrorCode.INVALID_LENGTH,
        )
    if (
        header.kind is constants.FrameKind.START_RESPONSE
        and not response_error
        and header.run_id == 0
    ):
        raise FrameValidationError(
            "a successful START response requires a nonzero run ID",
            constants.ErrorCode.INVALID_PAYLOAD,
        )


def _validate_response_prefix(header: FrameHeader, payload: bytes) -> None:
    raw_status, reserved, raw_error = _RESPONSE_PREFIX.unpack_from(payload)
    if reserved != 0:
        raise FrameValidationError("response reserved byte must be zero")
    try:
        status = constants.ResponseStatus(raw_status)
        error = constants.ErrorCode(raw_error)
    except ValueError as exc:
        raise FrameValidationError("unknown response status or error code") from exc
    response_error = bool(header.flags & constants.FrameFlag.RESPONSE_ERROR)
    if response_error != (status is constants.ResponseStatus.ERROR):
        raise FrameValidationError("response flag and status disagree")
    if (status is constants.ResponseStatus.OK) != (error is constants.ErrorCode.OK):
        raise FrameValidationError("response status and error code disagree")


def _validate_configuration(payload: bytes, offset: int, *, applied: bool) -> None:
    raw_streams, raw_source, raw_checksum, reserved, frame_bytes = (
        _CONFIGURATION.unpack_from(payload, offset)
    )
    valid_stream_bits = int(constants.StreamMask.ADC | constants.StreamMask.GPIO)
    if raw_streams & ~valid_stream_bits:
        raise FrameValidationError("configuration stream mask is invalid")
    try:
        source = constants.Source(raw_source)
        checksum = constants.ChecksumAlgorithm(raw_checksum)
    except ValueError as exc:
        raise FrameValidationError(
            "configuration contains an unknown enum value"
        ) from exc
    if raw_streams == 0 and source is not constants.Source.HARDWARE:
        raise FrameValidationError(
            "zero-stream configuration requires the hardware source"
        )
    if checksum is constants.ChecksumAlgorithm.NONE_RESERVED:
        raise FrameValidationError("configuration cannot select checksum ID zero")
    if applied and checksum not in constants.SUPPORTED_CHECKSUM_ALGORITHMS:
        raise FrameValidationError("applied configuration checksum is not enabled")
    if checksum not in HOST_SUPPORTED_CHECKSUM_ALGORITHMS:
        raise UnsupportedChecksumError(int(checksum))
    if reserved != 0:
        raise FrameValidationError("configuration reserved byte must be zero")
    if frame_bytes != constants.DATA_FRAME_BYTES:
        raise FrameValidationError("configuration data frame size must be 4096")


def _benchmark_vector_bytes(vector: constants.BenchmarkVector) -> int:
    return {
        constants.BenchmarkVector.EMPTY: 0,
        constants.BenchmarkVector.CANONICAL_123456789: 9,
        constants.BenchmarkVector.BUFFER_64: 64,
        constants.BenchmarkVector.BUFFER_512: 512,
        constants.BenchmarkVector.FRAME_COVERAGE: (
            constants.DATA_FRAME_BYTES - constants.TRAILER_SIZE
        ),
    }[vector]


def _validate_checksum_benchmark_request(payload: bytes, offset: int = 0) -> None:
    (
        raw_checksum,
        raw_vector,
        raw_region,
        raw_cache_state,
        batch_count,
        iterations_per_batch,
    ) = _CHECKSUM_BENCHMARK_REQUEST.unpack_from(payload, offset)
    try:
        checksum = constants.ChecksumAlgorithm(raw_checksum)
        vector = constants.BenchmarkVector(raw_vector)
        region = constants.BenchmarkMemoryRegion(raw_region)
        cache_state = constants.BenchmarkCacheState(raw_cache_state)
    except ValueError as exc:
        raise FrameValidationError(
            "checksum benchmark contains an unknown enum value"
        ) from exc
    if checksum not in constants.SUPPORTED_CHECKSUM_ALGORITHMS:
        raise FrameValidationError("checksum benchmark algorithm is not enabled")
    if (
        not 1 <= batch_count <= constants.CHECKSUM_BENCHMARK_MAX_BATCH_COUNT
        or not 1
        <= iterations_per_batch
        <= constants.CHECKSUM_BENCHMARK_MAX_ITERATIONS_PER_BATCH
    ):
        raise FrameValidationError("checksum benchmark repetition count is invalid")
    if cache_state is constants.BenchmarkCacheState.COLD_INVALIDATED and (
        region is not constants.BenchmarkMemoryRegion.OCRAM_DMA
        or vector is constants.BenchmarkVector.EMPTY
    ):
        raise FrameValidationError(
            "cold-cache benchmark requires nonempty DMA-visible OCRAM"
        )
    operations = batch_count * iterations_per_batch
    processed_bytes = operations * _benchmark_vector_bytes(vector)
    if (
        operations > constants.CHECKSUM_BENCHMARK_MAX_OPERATIONS
        or processed_bytes > constants.CHECKSUM_BENCHMARK_MAX_PROCESSED_BYTES
    ):
        raise FrameValidationError("checksum benchmark exceeds its duration bound")


def _validate_checksum_benchmark_response(payload: bytes) -> None:
    _validate_checksum_benchmark_request(
        payload, constants.CHECKSUM_BENCHMARK_RESPONSE_CHECKSUM_ALGORITHM_OFFSET
    )
    vector = constants.BenchmarkVector(
        payload[constants.CHECKSUM_BENCHMARK_RESPONSE_VECTOR_OFFSET]
    )
    checksum = constants.ChecksumAlgorithm(
        payload[constants.CHECKSUM_BENCHMARK_RESPONSE_CHECKSUM_ALGORITHM_OFFSET]
    )
    cache_state = constants.BenchmarkCacheState(
        payload[constants.CHECKSUM_BENCHMARK_RESPONSE_CACHE_STATE_OFFSET]
    )
    batch_count, iterations_per_batch = struct.unpack_from(
        "<HH", payload, constants.CHECKSUM_BENCHMARK_RESPONSE_BATCH_COUNT_OFFSET
    )
    operations = batch_count * iterations_per_batch

    def u32(offset: int) -> int:
        return struct.unpack_from("<I", payload, offset)[0]

    def u64(offset: int) -> int:
        return struct.unpack_from("<Q", payload, offset)[0]

    buffer_bytes = u32(constants.CHECKSUM_BENCHMARK_RESPONSE_BUFFER_BYTES_OFFSET)
    counter_hz = u32(constants.CHECKSUM_BENCHMARK_RESPONSE_CYCLE_COUNTER_HZ_OFFSET)
    overhead_cycles = u32(
        constants.CHECKSUM_BENCHMARK_RESPONSE_TIMER_OVERHEAD_CYCLES_OFFSET
    )
    code_bytes = u32(
        constants.CHECKSUM_BENCHMARK_RESPONSE_IMPLEMENTATION_CODE_BYTES_OFFSET
    )
    table_bytes = u32(constants.CHECKSUM_BENCHMARK_RESPONSE_TABLE_BYTES_OFFSET)
    working_ram_bytes = u32(
        constants.CHECKSUM_BENCHMARK_RESPONSE_WORKING_RAM_BYTES_OFFSET
    )
    processed_bytes = u64(constants.CHECKSUM_BENCHMARK_RESPONSE_PROCESSED_BYTES_OFFSET)
    raw_cycles = u64(constants.CHECKSUM_BENCHMARK_RESPONSE_RAW_CHECKSUM_CYCLES_OFFSET)
    net_cycles = u64(constants.CHECKSUM_BENCHMARK_RESPONSE_NET_CHECKSUM_CYCLES_OFFSET)
    cache_setup_cycles = u64(
        constants.CHECKSUM_BENCHMARK_RESPONSE_CACHE_SETUP_CYCLES_OFFSET
    )
    min_batch_cycles = u32(
        constants.CHECKSUM_BENCHMARK_RESPONSE_MIN_BATCH_CYCLES_OFFSET
    )
    max_batch_cycles = u32(
        constants.CHECKSUM_BENCHMARK_RESPONSE_MAX_BATCH_CYCLES_OFFSET
    )
    expected_table_bytes = (
        0 if checksum is constants.ChecksumAlgorithm.ADLER32 else 8192
    )
    expected_buffer_bytes = _benchmark_vector_bytes(vector)
    expected_processed_bytes = operations * expected_buffer_bytes
    calibrated_overhead = operations * overhead_cycles
    if (
        payload[constants.CHECKSUM_BENCHMARK_RESPONSE_RESERVED_OFFSET] != 0
        or counter_hz != constants.CHECKSUM_BENCHMARK_CYCLE_COUNTER_HZ
        or code_bytes == 0
        or table_bytes != expected_table_bytes
        or working_ram_bytes != 2 * constants.DATA_FRAME_BYTES
        or buffer_bytes != expected_buffer_bytes
        or processed_bytes != expected_processed_bytes
        or raw_cycles < calibrated_overhead
        or raw_cycles - calibrated_overhead != net_cycles
        or min_batch_cycles > max_batch_cycles
        or net_cycles < min_batch_cycles * batch_count
        or net_cycles > max_batch_cycles * batch_count
        or (
            cache_state is not constants.BenchmarkCacheState.COLD_INVALIDATED
            and cache_setup_cycles != 0
        )
    ):
        raise FrameValidationError("checksum benchmark measurements are inconsistent")

    target_rate = u32(
        constants.CHECKSUM_BENCHMARK_RESPONSE_TARGET_FRAMED_BYTES_PER_SECOND_OFFSET
    )
    cycles_per_byte_q16 = u32(
        constants.CHECKSUM_BENCHMARK_RESPONSE_CYCLES_PER_BYTE_Q16_OFFSET
    )
    mb_per_second_q16 = u32(
        constants.CHECKSUM_BENCHMARK_RESPONSE_MB_PER_SECOND_Q16_OFFSET
    )
    projected_cpu_q16 = u32(
        constants.CHECKSUM_BENCHMARK_RESPONSE_PROJECTED_CPU_PERCENT_Q16_OFFSET
    )
    if target_rate != constants.CHECKSUM_BENCHMARK_TARGET_FRAMED_BYTES_PER_SECOND:
        raise FrameValidationError("checksum benchmark target rate is incompatible")
    total_cycles = net_cycles + cache_setup_cycles
    if processed_bytes == 0:
        expected_metrics = (0, 0, 0)
    else:
        if total_cycles == 0:
            raise FrameValidationError("nonempty benchmark requires measured cycles")
        expected_cpb = (total_cycles * 65536) // processed_bytes
        bytes_per_second = (counter_hz * processed_bytes) // total_cycles
        expected_mb_per_second = (bytes_per_second * 65536) // 1_000_000
        expected_cpu = (expected_cpb * target_rate * 100) // counter_hz
        expected_metrics = (expected_cpb, expected_mb_per_second, expected_cpu)
    if (
        cycles_per_byte_q16,
        mb_per_second_q16,
        projected_cpu_q16,
    ) != expected_metrics:
        raise FrameValidationError("checksum benchmark derived metrics disagree")


def _valid_gpio_clock_selection(rate_hz: int, event_count: int) -> bool:
    if (
        not constants.GPIO_CLOCK_MIN_RATE_HZ
        <= rate_hz
        <= constants.GPIO_CLOCK_PRODUCTION_RATE_HZ
        or constants.GPIO_CLOCK_PIT_HZ % rate_hz != 0
        or constants.GPIO_CLOCK_DWT_HZ % rate_hz != 0
        or not constants.GPIO_CLOCK_MIN_EVENT_COUNT
        <= event_count
        <= constants.GPIO_CLOCK_MAX_EVENT_COUNT
    ):
        return False
    elapsed_cycles = event_count * (constants.GPIO_CLOCK_DWT_HZ // rate_hz)
    major_count = 2 * event_count + constants.GPIO_CLOCK_DUPLICATE_GUARD_EVENTS
    return (
        elapsed_cycles <= constants.GPIO_CLOCK_MAX_ELAPSED_CYCLES
        and major_count <= 0x7FFF
    )


def _validate_gpio_clock_diagnostic_request(payload: bytes, offset: int = 0) -> None:
    rate_hz, event_count, reserved = _GPIO_CLOCK_DIAGNOSTIC_REQUEST.unpack_from(
        payload, offset
    )
    if reserved != 0:
        raise FrameValidationError("GPIO clock diagnostic reserved field must be zero")
    if not _valid_gpio_clock_selection(rate_hz, event_count):
        raise FrameValidationError("GPIO clock diagnostic selection is invalid")


def _validate_gpio_clock_diagnostic_response(payload: bytes) -> None:
    def u32(offset: int) -> int:
        return struct.unpack_from("<I", payload, offset)[0]

    configured_rate = u32(
        constants.GPIO_CLOCK_DIAGNOSTIC_RESPONSE_CONFIGURED_RATE_HZ_OFFSET
    )
    production_rate = u32(
        constants.GPIO_CLOCK_DIAGNOSTIC_RESPONSE_PRODUCTION_RATE_HZ_OFFSET
    )
    pit_clock = u32(constants.GPIO_CLOCK_DIAGNOSTIC_RESPONSE_PIT_CLOCK_HZ_OFFSET)
    pit_load = u32(constants.GPIO_CLOCK_DIAGNOSTIC_RESPONSE_PIT_LOAD_VALUE_OFFSET)
    requested_events = u32(
        constants.GPIO_CLOCK_DIAGNOSTIC_RESPONSE_REQUESTED_EVENT_COUNT_OFFSET
    )
    scheduled_events = u32(
        constants.GPIO_CLOCK_DIAGNOSTIC_RESPONSE_SCHEDULED_EVENT_COUNT_OFFSET
    )
    samples = u32(constants.GPIO_CLOCK_DIAGNOSTIC_RESPONSE_DMA_SAMPLE_COUNT_OFFSET)
    dwt_hz = u32(constants.GPIO_CLOCK_DIAGNOSTIC_RESPONSE_DWT_COUNTER_HZ_OFFSET)
    elapsed_cycles = u32(
        constants.GPIO_CLOCK_DIAGNOSTIC_RESPONSE_DWT_ELAPSED_CYCLES_OFFSET
    )
    error_flags = u32(
        constants.GPIO_CLOCK_DIAGNOSTIC_RESPONSE_HARDWARE_ERROR_FLAGS_OFFSET
    )
    citer = struct.unpack_from(
        "<H", payload, constants.GPIO_CLOCK_DIAGNOSTIC_RESPONSE_TCD_CITER_FINAL_OFFSET
    )[0]
    biter = struct.unpack_from(
        "<H", payload, constants.GPIO_CLOCK_DIAGNOSTIC_RESPONSE_TCD_BITER_OFFSET
    )[0]
    selection_valid = _valid_gpio_clock_selection(configured_rate, requested_events)
    expected_major_count = (
        2 * requested_events + constants.GPIO_CLOCK_DUPLICATE_GUARD_EVENTS
    )
    unarmed_errors = int(
        constants.GpioClockError.DWT_UNAVAILABLE
        | constants.GpioClockError.RESOURCE_BUSY
    )
    configuration_was_armed = error_flags & unarmed_errors == 0
    expected_scheduled = (
        elapsed_cycles // (constants.GPIO_CLOCK_DWT_HZ // configured_rate)
        if selection_valid and dwt_hz == constants.GPIO_CLOCK_DWT_HZ
        else 0
    )
    if (
        not selection_valid
        or production_rate != constants.GPIO_CLOCK_PRODUCTION_RATE_HZ
        or pit_clock != constants.GPIO_CLOCK_PIT_HZ
        or pit_load != constants.GPIO_CLOCK_PIT_HZ // configured_rate - 1
        or error_flags & ~constants.KNOWN_GPIO_CLOCK_ERROR_MASK
        or (
            configuration_was_armed
            and (
                biter != expected_major_count
                or citer > biter
                or samples != biter - citer
            )
        )
        or (
            dwt_hz == constants.GPIO_CLOCK_DWT_HZ
            and scheduled_events != expected_scheduled
        )
        or (
            error_flags == 0
            and (
                dwt_hz != constants.GPIO_CLOCK_DWT_HZ
                or elapsed_cycles == 0
                or abs(scheduled_events - requested_events)
                > constants.GPIO_CLOCK_COUNT_TOLERANCE
                or abs(samples - scheduled_events)
                > constants.GPIO_CLOCK_COUNT_TOLERANCE
            )
        )
    ):
        raise FrameValidationError("GPIO clock diagnostic evidence is inconsistent")


def _validate_gpio_capture_diagnostic_response(payload: bytes) -> None:
    def u16(offset: int) -> int:
        return struct.unpack_from("<H", payload, offset)[0]

    def u32(offset: int) -> int:
        return struct.unpack_from("<I", payload, offset)[0]

    try:
        constants.GpioCaptureDiagnosticMode(
            payload[constants.GPIO_CAPTURE_DIAGNOSTIC_RESPONSE_MODE_OFFSET]
        )
    except ValueError as exc:
        raise FrameValidationError("GPIO capture diagnostic mode is unknown") from exc
    flags = u32(constants.GPIO_CAPTURE_DIAGNOSTIC_RESPONSE_DIAGNOSTIC_FLAGS_OFFSET)
    errors = u32(constants.GPIO_CAPTURE_DIAGNOSTIC_RESPONSE_HARDWARE_ERROR_FLAGS_OFFSET)
    captured = struct.unpack_from(
        "<Q",
        payload,
        constants.GPIO_CAPTURE_DIAGNOSTIC_RESPONSE_DMA_SAMPLES_CAPTURED_OFFSET,
    )[0]
    retained = u32(
        constants.GPIO_CAPTURE_DIAGNOSTIC_RESPONSE_COMPLETE_SAMPLES_RETAINED_OFFSET
    )
    analyzed = u32(constants.GPIO_CAPTURE_DIAGNOSTIC_RESPONSE_SAMPLES_ANALYZED_OFFSET)
    limit = u32(constants.GPIO_CAPTURE_DIAGNOSTIC_RESPONSE_ANALYSIS_SAMPLE_LIMIT_OFFSET)
    output_permitted = int(constants.GpioCaptureDiagnosticFlag.OUTPUT_DRIVE_PERMITTED)
    output_exercised = int(constants.GpioCaptureDiagnosticFlag.OUTPUT_DRIVE_EXERCISED)
    if (
        payload[constants.GPIO_CAPTURE_DIAGNOSTIC_RESPONSE_METADATA_KIND_OFFSET] > 2
        or payload[constants.GPIO_CAPTURE_DIAGNOSTIC_RESPONSE_DRIVE_SAFETY_OFFSET] > 2
        or payload[constants.GPIO_CAPTURE_DIAGNOSTIC_RESPONSE_STIMULUS_KIND_OFFSET] > 2
        or u16(constants.GPIO_CAPTURE_DIAGNOSTIC_RESPONSE_RESERVED_1_OFFSET) != 0
        or payload[constants.GPIO_CAPTURE_DIAGNOSTIC_RESPONSE_RESERVED_2_OFFSET] != 0
        or errors & ~constants.KNOWN_GPIO_CAPTURE_ERROR_MASK
        or flags & ~constants.KNOWN_GPIO_CAPTURE_DIAGNOSTIC_FLAG_MASK
        or not flags & int(constants.GpioCaptureDiagnosticFlag.AVAILABLE)
        or retained > captured
        or analyzed > retained
        or analyzed > limit
        or not 0 < limit <= constants.GPIO_SAMPLES_PER_FRAME
        or flags & output_exercised
        and not flags & output_permitted
    ):
        raise FrameValidationError("GPIO capture diagnostic evidence is inconsistent")


def _adc_offset(prefix: str, field: str) -> int:
    separator = "" if field[:1] in {"0", "1"} else "_"
    return int(getattr(constants, f"{prefix}_ADC{separator}{field}_OFFSET"))


def _validate_adc_metadata_payload(payload: bytes, prefix: str) -> None:
    def u16(field: str) -> int:
        return int(struct.unpack_from("<H", payload, _adc_offset(prefix, field))[0])

    def u32(field: str) -> int:
        return int(struct.unpack_from("<I", payload, _adc_offset(prefix, field))[0])

    resolution = payload[_adc_offset(prefix, "RESOLUTION_BITS")]
    if resolution not in {
        constants.ADC_PRIMARY_RESOLUTION_BITS,
        constants.ADC_FALLBACK_RESOLUTION_BITS,
    }:
        raise FrameValidationError("ADC metadata reports an unsupported resolution")
    expected_mode = 2 if resolution == constants.ADC_PRIMARY_RESOLUTION_BITS else 1
    try:
        reference = constants.AdcReference(payload[_adc_offset(prefix, "REFERENCE")])
        clock_source = constants.AdcClockSource(
            payload[_adc_offset(prefix, "CLOCK_SOURCE")]
        )
        calibration_states = (
            constants.AdcCalibrationState(
                payload[_adc_offset(prefix, "0_CALIBRATION_STATE")]
            ),
            constants.AdcCalibrationState(
                payload[_adc_offset(prefix, "1_CALIBRATION_STATE")]
            ),
        )
    except ValueError as exc:
        raise FrameValidationError("ADC metadata contains an unknown enum") from exc
    flags = constants.AdcConfigurationFlag(u16("CONFIGURATION_FLAGS"))
    errors = constants.AdcInitializationError(u32("INITIALIZATION_ERROR_FLAGS"))
    if (
        int(flags) & ~constants.KNOWN_ADC_CONFIGURATION_FLAG_MASK
        or int(errors) & ~constants.KNOWN_ADC_INITIALIZATION_ERROR_MASK
    ):
        raise FrameValidationError("ADC metadata contains reserved flags")

    expected_bytes = {
        "CONTAINER_BYTES": constants.ADC_CONTAINER_BITS // 8,
        "CLOCK_DIVIDER": constants.ADC_CLOCK_DIVIDER,
        "HARDWARE_AVERAGE_COUNT": constants.ADC_HARDWARE_AVERAGE_COUNT,
        "SAMPLE_TIME_ADCK": constants.ADC_SAMPLE_TIME_ADCK,
        "CONVERSION_MODE": expected_mode,
        "0_PIN": constants.ADC_PINS[0],
        "1_PIN": constants.ADC_PINS[1],
        "0_PERIPHERAL": constants.ADC_PERIPHERALS[0],
        "1_PERIPHERAL": constants.ADC_PERIPHERALS[1],
        "0_CHANNEL": constants.ADC_CHANNELS[0],
        "1_CHANNEL": constants.ADC_CHANNELS[1],
    }
    if any(
        payload[_adc_offset(prefix, field)] != expected
        for field, expected in expected_bytes.items()
    ):
        raise FrameValidationError("ADC metadata reports incompatible settings")
    if (
        reference is not constants.AdcReference.VREFH_VREFL_NOMINAL_3V3
        or clock_source is not constants.AdcClockSource.SYNCHRONOUS_IPG
        or u16("CODE_MIN") != constants.ADC_CODE_MIN
        or u16("CODE_MAX") != (1 << resolution) - 1
        or u16("REFERENCE_MV_NOMINAL") != constants.ADC_REFERENCE_MV_NOMINAL
        or u16("INPUT_MIN_MV_NOMINAL") != constants.ADC_INPUT_MIN_MV_NOMINAL
        or u16("INPUT_MAX_MV_NOMINAL") != constants.ADC_INPUT_MAX_MV_NOMINAL
        or u32("IPG_CLOCK_HZ") != constants.ADC_IPG_CLOCK_HZ
        or u32("CLOCK_HZ") != constants.ADC_CLOCK_HZ
        or u32("CALIBRATION_DEADLINE_US") != constants.ADC_CALIBRATION_DEADLINE_US
    ):
        raise FrameValidationError("ADC metadata reports incompatible v1 values")
    # Parse both cycle fields even when calibration did not run so truncated or
    # misaligned schema edits cannot pass this validator accidentally.
    u32("0_CALIBRATION_CYCLES")
    u32("1_CALIBRATION_CYCLES")

    required_settings = (
        constants.AdcConfigurationFlag.NO_HARDWARE_AVERAGING
        | constants.AdcConfigurationFlag.HIGH_SPEED
        | constants.AdcConfigurationFlag.SHORTEST_SAMPLE
    )
    selected_resolution = (
        constants.AdcConfigurationFlag.PRIMARY_12_BIT
        if resolution == constants.ADC_PRIMARY_RESOLUTION_BITS
        else constants.AdcConfigurationFlag.FALLBACK_10_BIT
    )
    other_resolution = (
        constants.AdcConfigurationFlag.FALLBACK_10_BIT
        if resolution == constants.ADC_PRIMARY_RESOLUTION_BITS
        else constants.AdcConfigurationFlag.PRIMARY_12_BIT
    )
    if (
        flags & required_settings != required_settings
        or not flags & selected_resolution
        or flags & other_resolution
    ):
        raise FrameValidationError("ADC flags disagree with actual configuration")
    if flags & constants.AdcConfigurationFlag.INITIALIZED:
        ready_flags = (
            constants.AdcConfigurationFlag.ROUTES_VALIDATED
            | constants.AdcConfigurationFlag.CONFIGURATION_READBACK_VALID
            | constants.AdcConfigurationFlag.CALIBRATION_COMPLETE
        )
        if (
            errors
            or flags & ready_flags != ready_flags
            or calibration_states
            != (
                constants.AdcCalibrationState.SUCCEEDED,
                constants.AdcCalibrationState.SUCCEEDED,
            )
        ):
            raise FrameValidationError("ADC initialized state is inconsistent")


def _validate_info_payload(payload: bytes) -> None:
    if payload[constants.INFO_RESPONSE_RESERVED_0_OFFSET] != 0:
        raise FrameValidationError("INFO reserved_0 must be zero")
    if payload[constants.INFO_RESPONSE_RESERVED_2_OFFSET] != 0:
        raise FrameValidationError("INFO reserved_2 must be zero")
    if (
        struct.unpack_from("<H", payload, constants.INFO_RESPONSE_RESERVED_3_OFFSET)[0]
        != 0
        or payload[constants.INFO_RESPONSE_RESERVED_4_OFFSET] != 0
        or struct.unpack_from("<H", payload, constants.INFO_RESPONSE_RESERVED_5_OFFSET)[
            0
        ]
        != 0
    ):
        raise FrameValidationError("INFO GPIO metadata reserved fields must be zero")
    try:
        device_state = constants.DeviceState(
            payload[constants.INFO_RESPONSE_DEVICE_STATE_OFFSET]
        )
        constants.BoardId(
            struct.unpack_from("<H", payload, constants.INFO_RESPONSE_BOARD_ID_OFFSET)[
                0
            ]
        )
        constants.McuId(
            struct.unpack_from("<H", payload, constants.INFO_RESPONSE_MCU_ID_OFFSET)[0]
        )
        data_checksum = constants.ChecksumAlgorithm(
            payload[constants.INFO_RESPONSE_DATA_CHECKSUM_ALGORITHM_OFFSET]
        )
        constants.GpioCaptureDiagnosticMode(
            payload[constants.INFO_RESPONSE_GPIO_CAPTURE_DIAGNOSTIC_MODE_OFFSET]
        )
    except ValueError as exc:
        raise FrameValidationError("INFO contains an unknown enum value") from exc
    if device_state is constants.DeviceState.BOOT:
        raise FrameValidationError("INFO is unavailable while the device is in BOOT")

    expected_scalars = {
        constants.INFO_RESPONSE_PROTOCOL_VERSION_OFFSET: constants.PROTOCOL_VERSION,
        constants.INFO_RESPONSE_GPIO_PIN_COUNT_OFFSET: len(constants.GPIO_PINS_BY_BIT),
        constants.INFO_RESPONSE_GPIO_PACKED_WIDTH_BITS_OFFSET: (
            constants.GPIO_PACKED_WIDTH_BITS
        ),
        constants.INFO_RESPONSE_GPIO_RAW_RING_DEPTH_OFFSET: (
            constants.GPIO_RAW_RING_DEPTH
        ),
        constants.INFO_RESPONSE_GPIO_PACKED_RING_DEPTH_OFFSET: (
            constants.GPIO_PACKED_RING_DEPTH
        ),
        constants.INFO_RESPONSE_GPIO_PIT_CHANNEL_OFFSET: constants.GPIO_PIT_CHANNEL,
        constants.INFO_RESPONSE_GPIO_XBAR_INPUT_OFFSET: constants.GPIO_XBAR_INPUT,
        constants.INFO_RESPONSE_GPIO_XBAR_OUTPUT_OFFSET: constants.GPIO_XBAR_OUTPUT,
        constants.INFO_RESPONSE_GPIO_EDMA_CHANNEL_OFFSET: constants.GPIO_EDMA_CHANNEL,
        constants.INFO_RESPONSE_GPIO_DMAMUX_SOURCE_OFFSET: (
            constants.GPIO_DMAMUX_SOURCE
        ),
        constants.INFO_RESPONSE_GPIO_EDMA_PRIORITY_OFFSET: (
            constants.GPIO_EDMA_PRIORITY
        ),
        constants.INFO_RESPONSE_GPIO_XBAR_ACTIVE_EDGE_OFFSET: (
            constants.GPIO_XBAR_ACTIVE_EDGE
        ),
    }
    for offset, expected in expected_scalars.items():
        if payload[offset] != expected:
            raise FrameValidationError("INFO reports incompatible v1 capabilities")

    valid_stream_bits = int(constants.StreamMask.ADC | constants.StreamMask.GPIO)
    stream_mask = payload[constants.INFO_RESPONSE_SUPPORTED_STREAM_MASK_OFFSET]
    source_mask = payload[constants.INFO_RESPONSE_SUPPORTED_SOURCE_MASK_OFFSET]
    if stream_mask & ~valid_stream_bits or source_mask == 0 or source_mask & ~0x03:
        raise FrameValidationError("INFO reports an invalid capability mask")
    checksum_mask = struct.unpack_from(
        "<I", payload, constants.INFO_RESPONSE_SUPPORTED_CHECKSUM_MASK_OFFSET
    )[0]
    if checksum_mask != constants.SUPPORTED_CHECKSUM_MASK:
        raise FrameValidationError("INFO checksum mask disagrees with protocol v1")
    if not checksum_mask & (1 << int(data_checksum)):
        raise FrameValidationError("INFO selected checksum is not advertised")
    if data_checksum not in HOST_SUPPORTED_CHECKSUM_ALGORITHMS:
        raise UnsupportedChecksumError(int(data_checksum))
    capability_bits = struct.unpack_from(
        "<I", payload, constants.INFO_RESPONSE_CAPABILITY_BITS_OFFSET
    )[0]
    if capability_bits & ~constants.KNOWN_CAPABILITY_MASK:
        raise FrameValidationError("INFO reports reserved capability bits")
    expected_stream_capabilities = 0
    if stream_mask & constants.StreamMask.ADC:
        expected_stream_capabilities |= constants.Capability.ADC_STREAM
    if stream_mask & constants.StreamMask.GPIO:
        expected_stream_capabilities |= constants.Capability.GPIO_STREAM
    expected_source_capabilities = 0
    if source_mask & (1 << int(constants.Source.HARDWARE)):
        expected_source_capabilities |= constants.Capability.HARDWARE_SOURCE
    if source_mask & (1 << int(constants.Source.SYNTHETIC)):
        expected_source_capabilities |= constants.Capability.SYNTHETIC_SOURCE
    identity_capabilities = int(
        constants.Capability.ADC_STREAM
        | constants.Capability.GPIO_STREAM
        | constants.Capability.HARDWARE_SOURCE
        | constants.Capability.SYNTHETIC_SOURCE
    )
    if capability_bits & identity_capabilities != int(
        expected_stream_capabilities | expected_source_capabilities
    ):
        raise FrameValidationError("INFO capability bits disagree with source masks")
    diagnostic_flags = struct.unpack_from(
        "<H",
        payload,
        constants.INFO_RESPONSE_GPIO_CAPTURE_DIAGNOSTIC_FLAGS_OFFSET,
    )[0]
    if diagnostic_flags & ~constants.KNOWN_GPIO_CAPTURE_DIAGNOSTIC_FLAG_MASK:
        raise FrameValidationError("INFO GPIO diagnostic flags contain reserved bits")
    if bool(capability_bits & constants.Capability.GPIO_CAPTURE_DIAGNOSTIC) != bool(
        diagnostic_flags & constants.GpioCaptureDiagnosticFlag.AVAILABLE
    ):
        raise FrameValidationError(
            "INFO GPIO diagnostic metadata disagrees with capability bits"
        )

    expected_u32 = {
        constants.INFO_RESPONSE_TIMESTAMP_HZ_OFFSET: constants.TIMESTAMP_HZ,
        constants.INFO_RESPONSE_DATA_FRAME_BYTES_OFFSET: constants.DATA_FRAME_BYTES,
        constants.INFO_RESPONSE_MAX_CONTROL_FRAME_BYTES_OFFSET: (
            constants.MAX_CONTROL_FRAME_BYTES
        ),
        constants.INFO_RESPONSE_ADC_PAIR_RATE_HZ_OFFSET: constants.ADC_PAIR_RATE_HZ,
        constants.INFO_RESPONSE_GPIO_SAMPLE_RATE_HZ_OFFSET: (
            constants.GPIO_SAMPLE_RATE_HZ
        ),
        constants.INFO_RESPONSE_GPIO_RAW_SAMPLES_PER_BUFFER_OFFSET: (
            constants.GPIO_RAW_SAMPLES_PER_BUFFER
        ),
        constants.INFO_RESPONSE_GPIO_RAW_RING_BYTES_OFFSET: (
            constants.GPIO_RAW_RING_BYTES
        ),
        constants.INFO_RESPONSE_GPIO_PACKED_RING_BYTES_OFFSET: (
            constants.GPIO_PACKED_RING_BYTES
        ),
    }
    for offset, expected in expected_u32.items():
        if struct.unpack_from("<I", payload, offset)[0] != expected:
            raise FrameValidationError("INFO reports incompatible v1 timing or sizes")
    expected_u16 = {
        constants.INFO_RESPONSE_ADC_PAIR_PERIOD_TICKS_OFFSET: (
            constants.ADC_PAIR_PERIOD_TICKS
        ),
        constants.INFO_RESPONSE_ADC1_PHASE_TICKS_OFFSET: constants.ADC1_PHASE_TICKS,
        constants.INFO_RESPONSE_GPIO_SAMPLE_PERIOD_TICKS_OFFSET: (
            constants.GPIO_SAMPLE_PERIOD_TICKS
        ),
        constants.INFO_RESPONSE_GPIO_PACKET_BUFFER_COUNT_OFFSET: (
            constants.GPIO_PACKET_BUFFER_COUNT
        ),
    }
    for offset, expected in expected_u16.items():
        if struct.unpack_from("<H", payload, offset)[0] != expected:
            raise FrameValidationError("INFO reports incompatible v1 timing")
    pin_start = constants.INFO_RESPONSE_GPIO_PIN_MAP_OFFSET
    pin_end = pin_start + constants.INFO_RESPONSE_GPIO_PIN_MAP_COUNT
    if tuple(payload[pin_start:pin_end]) != constants.GPIO_PINS_BY_BIT:
        raise FrameValidationError("INFO GPIO pin map must preserve D6-through-D13")

    build_start = constants.INFO_RESPONSE_BUILD_ID_OFFSET
    build_end = build_start + constants.INFO_RESPONSE_BUILD_ID_COUNT
    build_bytes = payload[build_start:build_end]
    try:
        terminator = build_bytes.index(0)
        build_bytes[:terminator].decode("ascii")
    except (ValueError, UnicodeDecodeError) as exc:
        raise FrameValidationError(
            "INFO build ID must be NUL-terminated ASCII"
        ) from exc
    if any(build_bytes[terminator + 1 :]):
        raise FrameValidationError("INFO build ID padding must be zero")
    _validate_adc_metadata_payload(payload, "INFO_RESPONSE")


def _validate_status_payload(payload: bytes) -> None:
    if payload[constants.STATUS_RESPONSE_RESERVED_OFFSET] != 0:
        raise FrameValidationError("STATUS reserved byte must be zero")
    try:
        device_state = constants.DeviceState(
            payload[constants.STATUS_RESPONSE_DEVICE_STATE_OFFSET]
        )
        source = constants.Source(payload[constants.STATUS_RESPONSE_SOURCE_OFFSET])
        checksum = constants.ChecksumAlgorithm(
            payload[constants.STATUS_RESPONSE_DATA_CHECKSUM_ALGORITHM_OFFSET]
        )
    except ValueError as exc:
        raise FrameValidationError("STATUS contains an unknown enum value") from exc
    streams = payload[constants.STATUS_RESPONSE_STREAM_MASK_OFFSET]
    valid_stream_bits = int(constants.StreamMask.ADC | constants.StreamMask.GPIO)
    if streams & ~valid_stream_bits:
        raise FrameValidationError("STATUS stream mask is invalid")
    if device_state is constants.DeviceState.BOOT:
        raise FrameValidationError("STATUS is unavailable while the device is in BOOT")
    if (
        device_state is constants.DeviceState.IDLE
        and streams != constants.StreamMask.NONE
    ):
        raise FrameValidationError("STATUS state and active stream mask disagree")
    if (
        device_state is not constants.DeviceState.IDLE
        and streams == constants.StreamMask.NONE
        and source is not constants.Source.HARDWARE
    ):
        raise FrameValidationError(
            "zero-stream CONFIGURED/RUNNING status requires hardware source"
        )
    if checksum not in constants.SUPPORTED_CHECKSUM_ALGORITHMS:
        raise FrameValidationError("STATUS checksum is not enabled")
    if checksum not in HOST_SUPPORTED_CHECKSUM_ALGORITHMS:
        raise UnsupportedChecksumError(int(checksum))
    if (
        struct.unpack_from(
            "<I", payload, constants.STATUS_RESPONSE_DATA_FRAME_BYTES_OFFSET
        )[0]
        != constants.DATA_FRAME_BYTES
    ):
        raise FrameValidationError("STATUS data frame size must be 4096")
    if (
        struct.unpack_from(
            "<I", payload, constants.STATUS_RESPONSE_STATS_GENERATION_OFFSET
        )[0]
        == 0
    ):
        raise FrameValidationError("STATUS stats generation must be nonzero")
    if (
        struct.unpack_from(
            "<H",
            payload,
            constants.STATUS_RESPONSE_GPIO_PROCESSING_CPU_BASIS_POINTS_OFFSET,
        )[0]
        > 10_000
    ):
        raise FrameValidationError("STATUS GPIO processing CPU exceeds 100%")
    depth_limits = {
        constants.STATUS_RESPONSE_GPIO_RAW_READY_DEPTH_OFFSET: (
            constants.GPIO_RAW_RING_DEPTH
        ),
        constants.STATUS_RESPONSE_GPIO_RAW_READY_HIGH_WATER_OFFSET: (
            constants.GPIO_RAW_RING_DEPTH
        ),
        constants.STATUS_RESPONSE_GPIO_PACKED_READY_DEPTH_OFFSET: (
            constants.GPIO_PACKED_RING_DEPTH
        ),
        constants.STATUS_RESPONSE_GPIO_PACKED_READY_HIGH_WATER_OFFSET: (
            constants.GPIO_PACKED_RING_DEPTH
        ),
        constants.STATUS_RESPONSE_PACKET_READY_DEPTH_OFFSET: (
            constants.GPIO_PACKET_BUFFER_COUNT
        ),
        constants.STATUS_RESPONSE_PACKET_TRANSMIT_DEPTH_OFFSET: (
            constants.GPIO_PACKET_BUFFER_COUNT
        ),
        constants.STATUS_RESPONSE_PACKET_OWNED_HIGH_WATER_OFFSET: (
            constants.GPIO_PACKET_BUFFER_COUNT
        ),
    }
    if any(
        struct.unpack_from("<H", payload, offset)[0] > maximum
        for offset, maximum in depth_limits.items()
    ):
        raise FrameValidationError("STATUS queue depth exceeds its advertised capacity")
    _validate_adc_metadata_payload(payload, "STATUS_RESPONSE")


def _validate_payload(header: FrameHeader, payload: bytes) -> None:
    if len(payload) != header.payload_length:
        raise FrameValidationError(
            "payload length disagrees with header", constants.ErrorCode.INVALID_LENGTH
        )
    if header.kind is constants.FrameKind.ADC_DATA:
        code_mask = (1 << constants.ADC_RESOLUTION_BITS) - 1
        for adc0, adc1 in struct.iter_unpack("<HH", payload):
            if adc0 & ~code_mask or adc1 & ~code_mask:
                raise FrameValidationError("ADC payload contains out-of-range codes")
        return
    if header.kind is constants.FrameKind.GPIO_DATA:
        return
    if header.kind is constants.FrameKind.CONFIGURE_REQUEST:
        _validate_configuration(payload, 0, applied=False)
        return
    if header.kind is constants.FrameKind.CHECKSUM_BENCHMARK_REQUEST:
        _validate_checksum_benchmark_request(payload)
        return
    if header.kind is constants.FrameKind.GPIO_CLOCK_DIAGNOSTIC_REQUEST:
        _validate_gpio_clock_diagnostic_request(payload)
        return
    if header.kind in _REQUEST_KINDS:
        return

    _validate_response_prefix(header, payload)
    if header.flags & constants.FrameFlag.RESPONSE_ERROR:
        if (
            header.kind is constants.FrameKind.ERROR_RESPONSE
            and struct.unpack_from(
                "<H", payload, constants.ERROR_RESPONSE_RESERVED_1_OFFSET
            )[0]
            != 0
        ):
            raise FrameValidationError("ERROR_RESPONSE reserved bytes must be zero")
        return
    if header.kind is constants.FrameKind.INFO_RESPONSE:
        _validate_info_payload(payload)
    elif header.kind in {
        constants.FrameKind.CONFIGURE_RESPONSE,
        constants.FrameKind.START_RESPONSE,
    }:
        _validate_configuration(payload, 4, applied=True)
    elif header.kind is constants.FrameKind.GET_STATUS_RESPONSE:
        _validate_status_payload(payload)
    elif header.kind is constants.FrameKind.STOP_RESPONSE:
        if (
            payload[constants.STOP_RESPONSE_DEVICE_STATE_OFFSET]
            != constants.DeviceState.IDLE
        ):
            raise FrameValidationError("STOP response state must be IDLE")
        if any(payload[constants.STOP_RESPONSE_RESERVED_1_OFFSET :]):
            raise FrameValidationError("STOP response reserved bytes must be zero")
    elif header.kind is constants.FrameKind.RESET_STATS_RESPONSE:
        if payload[constants.RESET_STATS_RESPONSE_RESERVED_OFFSET] != 0:
            raise FrameValidationError("RESET_STATS reserved byte must be zero")
        if (
            struct.unpack_from(
                "<I",
                payload,
                constants.RESET_STATS_RESPONSE_STATS_GENERATION_OFFSET,
            )[0]
            == 0
        ):
            raise FrameValidationError("RESET_STATS stats generation must be nonzero")
    elif (
        header.kind is constants.FrameKind.PING_RESPONSE
        and payload[constants.PING_RESPONSE_RESERVED_OFFSET] != 0
    ):
        raise FrameValidationError("PING response reserved byte must be zero")
    elif header.kind is constants.FrameKind.CHECKSUM_BENCHMARK_RESPONSE:
        _validate_checksum_benchmark_response(payload)
    elif header.kind is constants.FrameKind.GPIO_CLOCK_DIAGNOSTIC_RESPONSE:
        _validate_gpio_clock_diagnostic_response(payload)
    elif header.kind is constants.FrameKind.GPIO_CAPTURE_DIAGNOSTIC_RESPONSE:
        _validate_gpio_capture_diagnostic_response(payload)


def encode_frame(
    kind: constants.FrameKind | int,
    payload: BytesLike = b"",
    *,
    flags: constants.FrameFlag | int = constants.FrameFlag.NONE,
    checksum_algorithm: constants.ChecksumAlgorithm | int | None = None,
    run_id: int = 0,
    sequence: int = 0,
    request_id: int = 0,
    first_sample_ticks: int = 0,
    item_count: int = 0,
) -> bytes:
    """Encode one frame after validating all v1 envelope and payload rules."""

    try:
        selected_kind = constants.FrameKind(kind)
    except ValueError as exc:
        raise FrameValidationError(
            f"unknown frame kind {int(kind)}", constants.ErrorCode.UNKNOWN_FRAME_KIND
        ) from exc
    if checksum_algorithm is None:
        selected_checksum = (
            constants.DEFAULT_CHECKSUM_ALGORITHM
            if selected_kind in _DATA_KINDS
            else constants.BOOTSTRAP_CHECKSUM_ALGORITHM
        )
    else:
        try:
            selected_checksum = constants.ChecksumAlgorithm(checksum_algorithm)
        except ValueError as exc:
            raise UnsupportedChecksumError(int(checksum_algorithm)) from exc
    payload_bytes = bytes(payload)
    header = FrameHeader(
        kind=selected_kind,
        flags=constants.FrameFlag(_uint("flags", int(flags), 16)),
        checksum_algorithm=selected_checksum,
        total_length=constants.HEADER_SIZE
        + len(payload_bytes)
        + constants.TRAILER_SIZE,
        payload_length=len(payload_bytes),
        run_id=_uint("run_id", run_id, 32),
        sequence=_uint("sequence", sequence, 32),
        request_id=_uint("request_id", request_id, 32),
        first_sample_ticks=_uint("first_sample_ticks", first_sample_ticks, 64),
        item_count=_uint("item_count", item_count, 32),
    )
    _validate_header(header)
    _validate_payload(header, payload_bytes)
    body = header.to_bytes() + payload_bytes
    return body + _TRAILER.pack(compute_checksum(body, selected_checksum))


def decode_frame(data: BytesLike) -> Frame:
    """Decode exactly one complete frame and reject trailing or partial bytes."""

    frame_bytes = bytes(data)
    header = _decode_header(frame_bytes)
    if len(frame_bytes) != header.total_length:
        raise FrameValidationError(
            f"declared frame length is {header.total_length}, got {len(frame_bytes)}",
            constants.ErrorCode.INVALID_LENGTH,
        )
    payload_end = constants.HEADER_SIZE + header.payload_length
    payload = frame_bytes[constants.HEADER_SIZE : payload_end]
    observed_checksum = _TRAILER.unpack_from(frame_bytes, payload_end)[0]
    expected_checksum = compute_checksum(
        frame_bytes[:payload_end], header.checksum_algorithm
    )
    if observed_checksum != expected_checksum:
        raise ChecksumMismatchError(expected_checksum, observed_checksum)
    _validate_payload(header, payload)
    return Frame(header=header, payload=payload, checksum=observed_checksum)


def _decode_buffered_frame(
    buffer: bytearray,
    offset: int,
    header: FrameHeader,
) -> Frame:
    """Decode a complete plausible frame without copying its full wire image."""

    payload_start = offset + constants.HEADER_SIZE
    payload_end = payload_start + header.payload_length
    observed_checksum = _TRAILER.unpack_from(buffer, payload_end)[0]

    checksum_view = memoryview(buffer)[offset:payload_end]
    try:
        expected_checksum = compute_checksum(
            checksum_view,
            header.checksum_algorithm,
        )
    finally:
        checksum_view.release()
    if observed_checksum != expected_checksum:
        raise ChecksumMismatchError(expected_checksum, observed_checksum)

    payload_view = memoryview(buffer)[payload_start:payload_end]
    try:
        payload = payload_view.tobytes()
    finally:
        payload_view.release()
    _validate_payload(header, payload)
    return Frame(header=header, payload=payload, checksum=observed_checksum)


class IncrementalFrameParser(BoundedIncrementalParser[FrameHeader, Frame]):
    """Protocol-v1 parser using the shared bounded version-neutral scanner."""

    max_buffered_bytes = MAX_BUFFERED_BYTES

    def __init__(self) -> None:
        super().__init__(
            magic_bytes=constants.MAGIC_BYTES,
            header_size=constants.HEADER_SIZE,
            max_frame_bytes=_MAX_FRAME_BYTES,
            decode_header=_decode_header,
            decode_frame=_decode_buffered_frame,
            validation_error=FrameValidationError,
            checksum_error=ChecksumMismatchError,
        )

    @property
    def counters(self) -> ParserCounters:
        """Return the original protocol-v1 public counter type."""

        shared = super().counters
        return ParserCounters(
            bytes_received=shared.bytes_received,
            frames_decoded=shared.frames_decoded,
            corruption_events=shared.corruption_events,
            header_errors=shared.header_errors,
            checksum_errors=shared.checksum_errors,
            payload_errors=shared.payload_errors,
            resynchronizations=shared.resynchronizations,
            bytes_discarded=shared.bytes_discarded,
            buffered_bytes=shared.buffered_bytes,
            high_water_mark=shared.high_water_mark,
        )


FrameParser = IncrementalFrameParser


__all__ = [
    "MAX_BUFFERED_BYTES",
    "ChecksumAlgorithmMismatchError",
    "ChecksumMismatchError",
    "Frame",
    "FrameHeader",
    "FrameParser",
    "FrameValidationError",
    "IncrementalFrameParser",
    "ParserCounters",
    "ProtocolError",
    "UnsupportedChecksumError",
    "compute_checksum",
    "decode_frame",
    "encode_frame",
]
