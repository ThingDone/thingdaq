"""Protocol-v1 frame encoding, validation, and incremental parsing."""

from __future__ import annotations

import struct
import zlib
from collections.abc import Callable, Mapping
from dataclasses import dataclass
from types import MappingProxyType

from ._generated import protocol_constants as constants

BytesLike = bytes | bytearray | memoryview

_HEADER = struct.Struct(constants.HEADER_STRUCT_FORMAT)
_TRAILER = struct.Struct("<I")
_CONFIGURATION = struct.Struct("<BBBBI")
_CHECKSUM_BENCHMARK_REQUEST = struct.Struct("<BBBBHH")
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
class ParserCounters:
    """Immutable snapshot of incremental-parser health and bounded state.

    ``corruption_events`` is the sum of rejected header, checksum, and typed
    payload candidates. ``resynchronizations`` counts distinct loss-of-alignment
    episodes, including leading noise; one episode can reject several false
    magic candidates before the parser accepts another frame.
    """

    bytes_received: int
    frames_decoded: int
    corruption_events: int
    header_errors: int
    checksum_errors: int
    payload_errors: int
    resynchronizations: int
    bytes_discarded: int
    buffered_bytes: int
    high_water_mark: int


def _adler32(data: BytesLike) -> int:
    return zlib.adler32(data) & constants.UINT32_MAX


def _make_reflected_crc_table(polynomial: int) -> tuple[int, ...]:
    table: list[int] = []
    for index in range(256):
        remainder = index
        for _ in range(8):
            remainder = (remainder >> 1) ^ (polynomial if remainder & 1 else 0)
        table.append(remainder)
    return tuple(table)


_CRC32C_TABLE = _make_reflected_crc_table(0x82F63B78)


def _crc32c(data: BytesLike) -> int:
    remainder = constants.UINT32_MAX
    for value in data:
        remainder = (remainder >> 8) ^ _CRC32C_TABLE[(remainder ^ value) & 0xFF]
    return remainder ^ constants.UINT32_MAX


def _crc32_iso_hdlc(data: BytesLike) -> int:
    return zlib.crc32(data) & constants.UINT32_MAX


_CHECKSUM_DISPATCH: Mapping[constants.ChecksumAlgorithm, Callable[[BytesLike], int]] = (
    MappingProxyType(
        {
            constants.ChecksumAlgorithm.ADLER32: _adler32,
            constants.ChecksumAlgorithm.CRC32C: _crc32c,
            constants.ChecksumAlgorithm.CRC32_ISO_HDLC: _crc32_iso_hdlc,
        }
    )
)


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
    implementation = _CHECKSUM_DISPATCH.get(selected)
    if implementation is None:
        raise UnsupportedChecksumError(int(selected))
    return implementation(data)


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
    if header.checksum_algorithm not in constants.SUPPORTED_CHECKSUM_ALGORITHMS:
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
        0 if checksum is constants.ChecksumAlgorithm.ADLER32 else 1024
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


def _validate_info_payload(payload: bytes) -> None:
    if payload[constants.INFO_RESPONSE_RESERVED_0_OFFSET] != 0:
        raise FrameValidationError("INFO reserved_0 must be zero")
    if payload[constants.INFO_RESPONSE_RESERVED_1_OFFSET] != 0:
        raise FrameValidationError("INFO reserved_1 must be zero")
    if payload[constants.INFO_RESPONSE_RESERVED_2_OFFSET] != 0:
        raise FrameValidationError("INFO reserved_2 must be zero")
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
    except ValueError as exc:
        raise FrameValidationError("INFO contains an unknown enum value") from exc
    if device_state is constants.DeviceState.BOOT:
        raise FrameValidationError("INFO is unavailable while the device is in BOOT")

    expected_scalars = {
        constants.INFO_RESPONSE_PROTOCOL_VERSION_OFFSET: constants.PROTOCOL_VERSION,
        constants.INFO_RESPONSE_ADC_RESOLUTION_BITS_OFFSET: (
            constants.ADC_RESOLUTION_BITS
        ),
        constants.INFO_RESPONSE_ADC_CONTAINER_BYTES_OFFSET: (
            constants.ADC_CONTAINER_BITS // 8
        ),
        constants.INFO_RESPONSE_GPIO_PIN_COUNT_OFFSET: len(constants.GPIO_PINS_BY_BIT),
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


def _partial_magic_suffix_length(data: bytearray, start: int = 0) -> int:
    maximum = min(len(data) - start, len(constants.MAGIC_BYTES) - 1)
    for length in range(maximum, 0, -1):
        if data.endswith(constants.MAGIC_BYTES[:length], start):
            return length
    return 0


def _byte_view(chunk: BytesLike) -> memoryview:
    """Return a one-dimensional byte view, copying only non-contiguous inputs."""

    try:
        return memoryview(chunk).cast("B")
    except TypeError:
        return memoryview(bytes(chunk))


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


class IncrementalFrameParser:
    """Bounded parser for arbitrary USB CDC byte-stream chunk boundaries.

    The parser owns its pending input and every returned :class:`Frame` owns an
    immutable ``bytes`` payload, so caller-owned mutable chunks can be reused as
    soon as :meth:`feed` returns. Recovery scans use a cursor and compact once
    per drain rather than deleting or copying one byte at a time.
    """

    max_buffered_bytes = MAX_BUFFERED_BYTES

    def __init__(self) -> None:
        self._buffer = bytearray()
        self._scan_start = 0
        self._resynchronizing = False
        self.bytes_received = 0
        self.frames_decoded = 0
        self.corruption_events = 0
        self.header_errors = 0
        self.checksum_errors = 0
        self.payload_errors = 0
        self.resynchronizations = 0
        self.bytes_discarded = 0
        self.high_water_mark = 0

    @property
    def buffered_bytes(self) -> int:
        """Number of bytes retained while awaiting a plausible complete frame."""

        return len(self._buffer) - self._scan_start

    @property
    def errors(self) -> int:
        """Backward-compatible total of all rejected frame candidates."""

        return self.corruption_events

    @property
    def counters(self) -> ParserCounters:
        """Return an immutable snapshot suitable for monitoring or logging."""

        return ParserCounters(
            bytes_received=self.bytes_received,
            frames_decoded=self.frames_decoded,
            corruption_events=self.corruption_events,
            header_errors=self.header_errors,
            checksum_errors=self.checksum_errors,
            payload_errors=self.payload_errors,
            resynchronizations=self.resynchronizations,
            bytes_discarded=self.bytes_discarded,
            buffered_bytes=self.buffered_bytes,
            high_water_mark=self.high_water_mark,
        )

    @property
    def is_resynchronizing(self) -> bool:
        """Whether bytes have been discarded since the last accepted frame."""

        return self._resynchronizing

    def reset(self) -> None:
        """Discard pending bytes and reset parser counters."""

        self._buffer.clear()
        self._scan_start = 0
        self._resynchronizing = False
        self.bytes_received = 0
        self.frames_decoded = 0
        self.corruption_events = 0
        self.header_errors = 0
        self.checksum_errors = 0
        self.payload_errors = 0
        self.resynchronizations = 0
        self.bytes_discarded = 0
        self.high_water_mark = 0

    def feed(self, chunk: BytesLike) -> list[Frame]:
        """Consume a chunk and return every complete valid frame it contains."""

        incoming = _byte_view(chunk)
        try:
            self.bytes_received += len(incoming)
            frames: list[Frame] = []
            position = 0
            while position < len(incoming):
                frames.extend(self._drain())
                capacity = self.max_buffered_bytes - self.buffered_bytes
                if capacity <= 0:
                    raise RuntimeError(
                        "incremental parser could not make bounded progress"
                    )
                take = min(capacity, len(incoming) - position)
                self._buffer.extend(incoming[position : position + take])
                position += take
                self.high_water_mark = max(
                    self.high_water_mark,
                    self.buffered_bytes,
                )
            frames.extend(self._drain())
            return frames
        finally:
            incoming.release()

    def _drain(self) -> list[Frame]:
        frames: list[Frame] = []
        while True:
            magic_at = self._buffer.find(constants.MAGIC_BYTES, self._scan_start)
            if magic_at < 0:
                retained = _partial_magic_suffix_length(
                    self._buffer,
                    self._scan_start,
                )
                self._discard(self.buffered_bytes - retained)
                break
            if magic_at > self._scan_start:
                self._discard(magic_at - self._scan_start)
            if self.buffered_bytes < constants.HEADER_SIZE:
                break
            try:
                header = _decode_header(self._buffer, self._scan_start)
            except FrameValidationError:
                self._record_corruption("header")
                self._discard(1)
                continue
            if self.buffered_bytes < header.total_length:
                break
            try:
                frame = _decode_buffered_frame(
                    self._buffer,
                    self._scan_start,
                    header,
                )
            except ChecksumMismatchError:
                self._record_corruption("checksum")
                self._discard(1)
                continue
            except FrameValidationError:
                self._record_corruption("payload")
                self._discard(1)
                continue
            self._scan_start += header.total_length
            self.frames_decoded += 1
            self._resynchronizing = False
            frames.append(frame)
        self._compact()
        return frames

    def _discard(self, count: int) -> None:
        if count <= 0:
            return
        if not self._resynchronizing:
            self._resynchronizing = True
            self.resynchronizations += 1
        self._scan_start += count
        self.bytes_discarded += count

    def _record_corruption(self, category: str) -> None:
        self.corruption_events += 1
        if category == "header":
            self.header_errors += 1
        elif category == "checksum":
            self.checksum_errors += 1
        else:
            self.payload_errors += 1

    def _compact(self) -> None:
        if self._scan_start:
            del self._buffer[: self._scan_start]
            self._scan_start = 0


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
