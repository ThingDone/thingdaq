"""Protocol-v1 frame encoding, validation, and incremental parsing."""

from __future__ import annotations

import struct
import zlib
from collections.abc import Callable
from dataclasses import dataclass

from ._generated import protocol_constants as constants

BytesLike = bytes | bytearray | memoryview

_HEADER = struct.Struct(constants.HEADER_STRUCT_FORMAT)
_TRAILER = struct.Struct("<I")
_CONFIGURATION = struct.Struct("<BBBBI")
_RESPONSE_PREFIX = struct.Struct("<BBH")
_DATA_KINDS = frozenset({constants.FrameKind.ADC_DATA, constants.FrameKind.GPIO_DATA})
_REQUEST_KINDS = frozenset(constants.REQUEST_RESPONSE_KIND)
_TYPED_RESPONSE_KINDS = frozenset(constants.REQUEST_RESPONSE_KIND.values())
_SUCCESS_PAYLOAD_SIZE = {
    constants.FrameKind.INFO_RESPONSE: constants.INFO_RESPONSE_PAYLOAD_SIZE,
    constants.FrameKind.CONFIGURE_RESPONSE: (constants.CONFIGURE_RESPONSE_PAYLOAD_SIZE),
    constants.FrameKind.START_RESPONSE: constants.CONFIGURE_RESPONSE_PAYLOAD_SIZE,
    constants.FrameKind.STATUS_RESPONSE: constants.STATUS_RESPONSE_PAYLOAD_SIZE,
    constants.FrameKind.STOP_RESPONSE: constants.STOP_RESPONSE_PAYLOAD_SIZE,
}
MAX_BUFFERED_BYTES = constants.DATA_FRAME_BYTES + len(constants.MAGIC_BYTES) - 1


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


def _adler32(data: BytesLike) -> int:
    return zlib.adler32(data) & constants.UINT32_MAX


CHECKSUM_DISPATCH: dict[constants.ChecksumAlgorithm, Callable[[BytesLike], int]] = {
    constants.ChecksumAlgorithm.ADLER32: _adler32,
}


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
    implementation = CHECKSUM_DISPATCH.get(selected)
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


def _decode_header(data: BytesLike) -> FrameHeader:
    if len(data) < constants.HEADER_SIZE:
        raise FrameValidationError(
            f"frame has {len(data)} bytes; a header needs {constants.HEADER_SIZE}",
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
    ) = _HEADER.unpack_from(data)

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

    allowed_flags = int(constants.ALLOWED_FLAGS_BY_KIND[header.kind])
    if int(header.flags) & (~allowed_flags & 0xFFFF):
        raise FrameValidationError(
            f"flags 0x{int(header.flags):04x} are invalid for {header.kind.name}",
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

    response_error = bool(header.flags & constants.FrameFlag.RESPONSE_ERROR)
    if header.kind in _TYPED_RESPONSE_KINDS:
        expected_payload = (
            constants.RESPONSE_PREFIX_PAYLOAD_SIZE
            if response_error
            else _SUCCESS_PAYLOAD_SIZE[header.kind]
        )
    elif header.kind is constants.FrameKind.ERROR_RESPONSE:
        if not response_error:
            raise FrameValidationError(
                "ERROR_RESPONSE requires RESPONSE_ERROR",
                constants.ErrorCode.INVALID_FLAGS,
            )
        expected_payload = constants.ERROR_RESPONSE_PAYLOAD_SIZE
    else:
        expected_payload = {
            constants.FrameKind.INFO_REQUEST: constants.EMPTY_PAYLOAD_SIZE,
            constants.FrameKind.CONFIGURE_REQUEST: (
                constants.CONFIGURE_REQUEST_PAYLOAD_SIZE
            ),
            constants.FrameKind.START_REQUEST: constants.EMPTY_PAYLOAD_SIZE,
            constants.FrameKind.STATUS_REQUEST: constants.EMPTY_PAYLOAD_SIZE,
            constants.FrameKind.STOP_REQUEST: constants.EMPTY_PAYLOAD_SIZE,
        }[header.kind]
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
    if raw_streams == 0 or raw_streams & ~valid_stream_bits:
        raise FrameValidationError("configuration stream mask is invalid")
    try:
        constants.Source(raw_source)
        checksum = constants.ChecksumAlgorithm(raw_checksum)
    except ValueError as exc:
        raise FrameValidationError(
            "configuration contains an unknown enum value"
        ) from exc
    if checksum is constants.ChecksumAlgorithm.NONE_RESERVED:
        raise FrameValidationError("configuration cannot select checksum ID zero")
    if applied and checksum not in constants.SUPPORTED_CHECKSUM_ALGORITHMS:
        raise FrameValidationError("applied configuration checksum is not enabled")
    if reserved != 0:
        raise FrameValidationError("configuration reserved byte must be zero")
    if frame_bytes != constants.DATA_FRAME_BYTES:
        raise FrameValidationError("configuration data frame size must be 4096")


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
        constants.Source(payload[constants.STATUS_RESPONSE_SOURCE_OFFSET])
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
    if (device_state is constants.DeviceState.IDLE) != (
        streams == constants.StreamMask.NONE
    ):
        raise FrameValidationError("STATUS state and active stream mask disagree")
    if checksum not in constants.SUPPORTED_CHECKSUM_ALGORITHMS:
        raise FrameValidationError("STATUS checksum is not enabled")
    if (
        struct.unpack_from(
            "<I", payload, constants.STATUS_RESPONSE_DATA_FRAME_BYTES_OFFSET
        )[0]
        != constants.DATA_FRAME_BYTES
    ):
        raise FrameValidationError("STATUS data frame size must be 4096")


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
    elif header.kind is constants.FrameKind.STATUS_RESPONSE:
        _validate_status_payload(payload)
    elif header.kind is constants.FrameKind.STOP_RESPONSE:
        if (
            payload[constants.STOP_RESPONSE_DEVICE_STATE_OFFSET]
            != constants.DeviceState.IDLE
        ):
            raise FrameValidationError("STOP response state must be IDLE")
        if any(payload[constants.STOP_RESPONSE_RESERVED_1_OFFSET :]):
            raise FrameValidationError("STOP response reserved bytes must be zero")


def encode_frame(
    kind: constants.FrameKind | int,
    payload: BytesLike = b"",
    *,
    flags: constants.FrameFlag | int = constants.FrameFlag.NONE,
    checksum_algorithm: constants.ChecksumAlgorithm | int = (
        constants.DEFAULT_CHECKSUM_ALGORITHM
    ),
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


def _partial_magic_suffix_length(data: bytearray) -> int:
    maximum = min(len(data), len(constants.MAGIC_BYTES) - 1)
    for length in range(maximum, 0, -1):
        if data[-length:] == constants.MAGIC_BYTES[:length]:
            return length
    return 0


class IncrementalFrameParser:
    """Bounded parser for arbitrary USB CDC byte-stream chunk boundaries."""

    max_buffered_bytes = MAX_BUFFERED_BYTES

    def __init__(self) -> None:
        self._buffer = bytearray()
        self.frames_decoded = 0
        self.errors = 0
        self.bytes_discarded = 0
        self.high_water_mark = 0

    @property
    def buffered_bytes(self) -> int:
        """Number of bytes retained while awaiting a plausible complete frame."""

        return len(self._buffer)

    def reset(self) -> None:
        """Discard pending bytes and reset parser counters."""

        self._buffer.clear()
        self.frames_decoded = 0
        self.errors = 0
        self.bytes_discarded = 0
        self.high_water_mark = 0

    def feed(self, chunk: BytesLike) -> list[Frame]:
        """Consume a chunk and return every complete valid frame it contains."""

        incoming = memoryview(chunk).cast("B")
        frames: list[Frame] = []
        position = 0
        while position < len(incoming):
            frames.extend(self._drain())
            capacity = self.max_buffered_bytes - len(self._buffer)
            if capacity <= 0:
                raise RuntimeError("incremental parser could not make bounded progress")
            take = min(capacity, len(incoming) - position)
            self._buffer.extend(incoming[position : position + take])
            position += take
            self.high_water_mark = max(self.high_water_mark, len(self._buffer))
        frames.extend(self._drain())
        return frames

    def _drain(self) -> list[Frame]:
        frames: list[Frame] = []
        while True:
            magic_at = self._buffer.find(constants.MAGIC_BYTES)
            if magic_at < 0:
                retained = _partial_magic_suffix_length(self._buffer)
                discarded = len(self._buffer) - retained
                if discarded:
                    del self._buffer[:discarded]
                    self.bytes_discarded += discarded
                return frames
            if magic_at:
                del self._buffer[:magic_at]
                self.bytes_discarded += magic_at
            if len(self._buffer) < constants.HEADER_SIZE:
                return frames
            try:
                header = _decode_header(self._buffer)
            except FrameValidationError:
                del self._buffer[0]
                self.errors += 1
                self.bytes_discarded += 1
                continue
            if len(self._buffer) < header.total_length:
                return frames
            candidate = bytes(self._buffer[: header.total_length])
            try:
                frame = decode_frame(candidate)
            except FrameValidationError:
                del self._buffer[0]
                self.errors += 1
                self.bytes_discarded += 1
                continue
            del self._buffer[: header.total_length]
            self.frames_decoded += 1
            frames.append(frame)


FrameParser = IncrementalFrameParser


__all__ = [
    "CHECKSUM_DISPATCH",
    "MAX_BUFFERED_BYTES",
    "ChecksumMismatchError",
    "Frame",
    "FrameHeader",
    "FrameParser",
    "FrameValidationError",
    "IncrementalFrameParser",
    "ProtocolError",
    "UnsupportedChecksumError",
    "compute_checksum",
    "decode_frame",
    "encode_frame",
]
