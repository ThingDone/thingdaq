"""Experimental protocol-v2 envelope, RLE validation, and bounded parsing.

This module deliberately validates encoded frames without expanding their RLE
payloads. The typed logical-item codec and negotiated public API are layered on
top in the next prototype stage.
"""

from __future__ import annotations

import struct
from dataclasses import dataclass

from ._generated import protocol_constants as v1_constants
from ._generated import protocol_v2_constants as constants
from ._incremental import BoundedIncrementalParser, BytesLike, ParserCounters
from .checksum import HOST_SUPPORTED_CHECKSUM_ALGORITHMS, compute_checksum_value

_HEADER = struct.Struct(constants.HEADER_STRUCT_FORMAT)
_TRAILER = struct.Struct("<I")
_DATA_KINDS = frozenset({constants.FrameKind.ADC_DATA, constants.FrameKind.GPIO_DATA})
_REQUEST_KINDS = frozenset(constants.REQUEST_RESPONSE_KIND)
_TYPED_RESPONSE_KINDS = frozenset(constants.REQUEST_RESPONSE_KIND.values())
_MAX_FRAME_BYTES = max(
    constants.MAX_DATA_FRAME_BYTES,
    constants.MAX_CONTROL_FRAME_BYTES,
)
MAX_V2_BUFFERED_BYTES = _MAX_FRAME_BYTES + len(constants.MAGIC_BYTES) - 1


class V2ProtocolError(ValueError):
    """Base exception for malformed or unsupported protocol-v2 data."""


class V2FrameValidationError(V2ProtocolError):
    """A frame violates a protocol-v2 structural or typed-field rule."""

    def __init__(
        self,
        message: str,
        *,
        reason: str = "invalid_payload",
        error_code: constants.ErrorCode = constants.ErrorCode.INVALID_PAYLOAD,
    ) -> None:
        super().__init__(message)
        self.reason = reason
        self.error_code = error_code


class V2UnsupportedChecksumError(V2FrameValidationError):
    """The frame selects a checksum algorithm the host cannot compute."""

    def __init__(self, algorithm: int) -> None:
        super().__init__(
            f"unsupported checksum algorithm {algorithm}",
            reason="unsupported_checksum",
            error_code=constants.ErrorCode.UNSUPPORTED_CHECKSUM,
        )
        self.algorithm = algorithm


class V2ChecksumMismatchError(V2FrameValidationError):
    """The checksum trailer does not match the transmitted header and payload."""

    def __init__(self, expected: int, observed: int) -> None:
        super().__init__(
            f"checksum mismatch: expected 0x{expected:08x}, observed 0x{observed:08x}",
            reason="checksum_mismatch",
            error_code=constants.ErrorCode.CHECKSUM_MISMATCH,
        )
        self.expected = expected
        self.observed = observed


class V2RLEValidationError(V2FrameValidationError):
    """A checksummed RLE payload is incomplete, unbounded, or noncanonical."""

    def __init__(self, message: str, reason: str) -> None:
        super().__init__(message, reason=reason)


@dataclass(frozen=True, slots=True)
class V2FrameHeader:
    """Decoded protocol-v2 header fields."""

    kind: constants.FrameKind
    flags: constants.FrameFlag
    checksum_algorithm: constants.ChecksumAlgorithm
    encoding: constants.FrameEncoding
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
            int(self.encoding),
            self.total_length,
            self.payload_length,
            self.run_id,
            self.sequence,
            self.request_id,
            self.first_sample_ticks,
            self.item_count,
        )


@dataclass(frozen=True, slots=True)
class V2Frame:
    """A validated v2 frame retaining only its bounded transmitted payload."""

    header: V2FrameHeader
    payload: bytes
    checksum: int
    run_count: int | None = None

    def to_bytes(self) -> bytes:
        """Return the exact encoded wire representation."""

        return self.header.to_bytes() + self.payload + _TRAILER.pack(self.checksum)

    @property
    def payload_view(self) -> memoryview:
        """Return a zero-copy read-only view over the encoded payload bytes."""

        return memoryview(self.payload)


def _v1_checksum_algorithm(
    algorithm: constants.ChecksumAlgorithm,
) -> v1_constants.ChecksumAlgorithm:
    try:
        selected = v1_constants.ChecksumAlgorithm(int(algorithm))
    except ValueError as exc:
        raise V2UnsupportedChecksumError(int(algorithm)) from exc
    if selected not in HOST_SUPPORTED_CHECKSUM_ALGORITHMS:
        raise V2UnsupportedChecksumError(int(algorithm))
    return selected


def compute_v2_checksum(
    data: BytesLike,
    algorithm: constants.ChecksumAlgorithm | int = constants.DEFAULT_CHECKSUM_ALGORITHM,
) -> int:
    """Compute one enabled v2 checksum through the shared exact backend."""

    try:
        selected = constants.ChecksumAlgorithm(algorithm)
    except ValueError as exc:
        raise V2UnsupportedChecksumError(int(algorithm)) from exc
    result = compute_checksum_value(data, _v1_checksum_algorithm(selected))
    if result is None:
        raise V2UnsupportedChecksumError(int(selected))
    return int(result)


def _decode_v2_header(data: BytesLike, offset: int = 0) -> V2FrameHeader:
    available = len(data) - offset
    if offset < 0 or available < constants.HEADER_SIZE:
        raise V2FrameValidationError(
            f"frame has {max(available, 0)} bytes; a header needs {constants.HEADER_SIZE}",
            reason="invalid_length",
            error_code=constants.ErrorCode.INVALID_LENGTH,
        )
    (
        magic,
        version,
        raw_kind,
        raw_flags,
        header_length,
        raw_checksum_algorithm,
        raw_encoding,
        total_length,
        payload_length,
        run_id,
        sequence,
        request_id,
        first_sample_ticks,
        item_count,
    ) = _HEADER.unpack_from(data, offset)

    if magic != constants.MAGIC:
        raise V2FrameValidationError(
            "invalid frame magic",
            reason="invalid_length",
            error_code=constants.ErrorCode.INVALID_LENGTH,
        )
    if version != constants.PROTOCOL_VERSION:
        raise V2FrameValidationError(
            f"unsupported protocol version {version}",
            reason="unsupported_version",
            error_code=constants.ErrorCode.UNSUPPORTED_VERSION,
        )
    try:
        kind = constants.FrameKind(raw_kind)
    except ValueError as exc:
        raise V2FrameValidationError(
            f"unknown frame kind 0x{raw_kind:02x}",
            reason="unknown_frame_kind",
            error_code=constants.ErrorCode.UNKNOWN_FRAME_KIND,
        ) from exc
    try:
        checksum_algorithm = constants.ChecksumAlgorithm(raw_checksum_algorithm)
    except ValueError as exc:
        raise V2UnsupportedChecksumError(raw_checksum_algorithm) from exc
    try:
        encoding = constants.FrameEncoding(raw_encoding)
    except ValueError as exc:
        raise V2FrameValidationError(
            f"illegal frame encoding selector {raw_encoding}",
            reason="illegal_selector",
        ) from exc

    header = V2FrameHeader(
        kind=kind,
        flags=constants.FrameFlag(raw_flags),
        checksum_algorithm=checksum_algorithm,
        encoding=encoding,
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
    _validate_v2_header(header)
    return header


def _validate_v2_header(header: V2FrameHeader) -> None:
    if header.header_length != constants.HEADER_SIZE:
        raise V2FrameValidationError(
            f"header length must be {constants.HEADER_SIZE}",
            reason="invalid_length",
            error_code=constants.ErrorCode.INVALID_LENGTH,
        )
    _v1_checksum_algorithm(header.checksum_algorithm)
    if (
        header.kind not in _DATA_KINDS
        and header.checksum_algorithm != constants.BOOTSTRAP_CHECKSUM_ALGORITHM
    ):
        raise V2UnsupportedChecksumError(int(header.checksum_algorithm))

    allowed_flags = int(constants.ALLOWED_FLAGS_BY_KIND[header.kind])
    if int(header.flags) & (~allowed_flags & 0xFFFF):
        raise V2FrameValidationError(
            f"flags 0x{int(header.flags):04x} are invalid for {header.kind.name}",
            reason="invalid_flags",
            error_code=constants.ErrorCode.INVALID_FLAGS,
        )
    if header.flags & constants.FrameFlag.OVERRUN_BEFORE and not (
        header.flags & constants.FrameFlag.GAP_BEFORE
    ):
        raise V2FrameValidationError(
            "OVERRUN_BEFORE requires GAP_BEFORE",
            reason="invalid_flags",
            error_code=constants.ErrorCode.INVALID_FLAGS,
        )
    expected_total = (
        constants.HEADER_SIZE + header.payload_length + constants.TRAILER_SIZE
    )
    if header.total_length != expected_total:
        raise V2FrameValidationError(
            "total and payload lengths are inconsistent",
            reason="invalid_length",
            error_code=constants.ErrorCode.INVALID_LENGTH,
        )

    if header.kind in _DATA_KINDS:
        _validate_v2_data_header(header)
        return

    if header.encoding is not constants.FrameEncoding.RAW:
        raise V2FrameValidationError(
            "control frames require a zero encoding selector",
            reason="illegal_selector",
        )
    if (
        not constants.MIN_FRAME_BYTES
        <= header.total_length
        <= constants.MAX_CONTROL_FRAME_BYTES
    ):
        raise V2FrameValidationError(
            "control frame exceeds protocol-v2 bounds",
            reason="invalid_length",
            error_code=constants.ErrorCode.INVALID_LENGTH,
        )
    if header.request_id == 0:
        raise V2FrameValidationError(
            "control frames require a nonzero request ID",
            reason="invalid_request_id",
            error_code=constants.ErrorCode.INVALID_REQUEST_ID,
        )
    if header.sequence != 0 or header.first_sample_ticks != 0 or header.item_count != 0:
        raise V2FrameValidationError(
            "control sequence, timestamp, and item-count fields must be zero"
        )
    if header.kind in _REQUEST_KINDS and header.run_id != 0:
        raise V2FrameValidationError("request run ID must be zero")
    if (
        header.kind in _REQUEST_KINDS
        and header.total_length > constants.MAX_COMMAND_FRAME_BYTES
    ):
        raise V2FrameValidationError(
            "command frame exceeds the protocol-v2 command bound",
            reason="invalid_length",
            error_code=constants.ErrorCode.INVALID_LENGTH,
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
            raise V2FrameValidationError(
                "ERROR_RESPONSE requires RESPONSE_ERROR",
                reason="invalid_flags",
                error_code=constants.ErrorCode.INVALID_FLAGS,
            )
        expected_payload = constants.ERROR_RESPONSE_PAYLOAD_SIZE
    else:
        schema = constants.PAYLOAD_SCHEMA_BY_KIND[header.kind]
        expected_payload = constants.PAYLOAD_SIZE_BY_SCHEMA[schema]
    if header.payload_length != expected_payload:
        raise V2FrameValidationError(
            f"{header.kind.name} payload must be {expected_payload} bytes",
            reason="invalid_length",
            error_code=constants.ErrorCode.INVALID_LENGTH,
        )
    if (
        header.kind is constants.FrameKind.START_RESPONSE
        and not response_error
        and header.run_id == 0
    ):
        raise V2FrameValidationError("successful START requires a nonzero run ID")


def _validate_v2_data_header(header: V2FrameHeader) -> None:
    if header.kind is constants.FrameKind.ADC_DATA:
        expected_items = constants.ADC_PAIRS_PER_FRAME
        period_ticks = constants.ADC_PAIR_PERIOD_TICKS
        max_rle_payload = constants.ADC_RLE_MAX_SELECTED_PAYLOAD_BYTES
        min_rle_payload = constants.ADC_RLE_RECORD_BYTES
    else:
        expected_items = constants.GPIO_SAMPLES_PER_FRAME
        period_ticks = constants.GPIO_SAMPLE_PERIOD_TICKS
        max_rle_payload = constants.GPIO_RLE_MAX_SELECTED_PAYLOAD_BYTES
        min_rle_payload = constants.GPIO_RLE_RECORD_BYTES

    if header.item_count != expected_items:
        raise V2FrameValidationError(
            f"{header.kind.name} item_count must be {expected_items}",
            reason="invalid_length",
            error_code=constants.ErrorCode.INVALID_LENGTH,
        )
    if header.encoding is constants.FrameEncoding.RAW:
        if (
            header.total_length != constants.DATA_FRAME_BYTES
            or header.payload_length != constants.DATA_PAYLOAD_BYTES
        ):
            raise V2FrameValidationError(
                "RAW data frames must be exactly 4096 bytes",
                reason="invalid_length",
                error_code=constants.ErrorCode.INVALID_LENGTH,
            )
    elif not min_rle_payload <= header.payload_length <= max_rle_payload:
        raise V2FrameValidationError(
            "RLE payload length exceeds its selected-frame bound",
            reason="invalid_length",
            error_code=constants.ErrorCode.INVALID_LENGTH,
        )
    if header.total_length > constants.MAX_DATA_FRAME_BYTES:
        raise V2FrameValidationError(
            "data frame exceeds the protocol-v2 wire bound",
            reason="invalid_length",
            error_code=constants.ErrorCode.INVALID_LENGTH,
        )
    if header.run_id == 0 or header.request_id != 0:
        raise V2FrameValidationError(
            "data frames require a nonzero run ID and zero request ID"
        )
    if header.first_sample_ticks % period_ticks:
        raise V2FrameValidationError(
            "data timestamp is not aligned to its logical-item period"
        )
    epoch_start = bool(header.flags & constants.FrameFlag.EPOCH_START)
    first_in_epoch = header.sequence == 0 and header.first_sample_ticks == 0
    if epoch_start != first_in_epoch:
        raise V2FrameValidationError(
            "EPOCH_START must identify sequence zero at timestamp zero"
        )


def _validate_rle_payload(header: V2FrameHeader, payload: bytes) -> int:
    if header.kind is constants.FrameKind.ADC_DATA:
        record_bytes = constants.ADC_RLE_RECORD_BYTES
        item_bytes = constants.ADC_BYTES_PER_PAIR
        maximum_runs = constants.ADC_RLE_MAX_SELECTED_RUNS
    else:
        record_bytes = constants.GPIO_RLE_RECORD_BYTES
        item_bytes = 1
        maximum_runs = constants.GPIO_RLE_MAX_SELECTED_RUNS
    if not payload or len(payload) % record_bytes:
        raise V2RLEValidationError(
            "RLE payload ends inside a logical item",
            "truncated_item",
        )
    run_count = len(payload) // record_bytes
    if run_count > maximum_runs:
        raise V2RLEValidationError(
            "RLE payload exceeds the selected run-count bound",
            "decoded_count_overflow",
        )

    decoded_count = 0
    previous_item: bytes | None = None
    code_mask = (1 << constants.ADC_RESOLUTION_BITS) - 1
    for offset in range(0, len(payload), record_bytes):
        run_length = struct.unpack_from("<H", payload, offset)[0]
        if run_length == 0:
            raise V2RLEValidationError("RLE run length is zero", "zero_run")
        if run_length > header.item_count - decoded_count:
            raise V2RLEValidationError(
                "RLE decoded count exceeds the advertised item bound",
                "decoded_count_overflow",
            )
        item = payload[offset + 2 : offset + 2 + item_bytes]
        if item == previous_item:
            raise V2RLEValidationError(
                "adjacent RLE records contain the same logical item",
                "adjacent_equal_runs",
            )
        if header.kind is constants.FrameKind.ADC_DATA:
            adc0, adc1 = struct.unpack("<HH", item)
            if adc0 & ~code_mask or adc1 & ~code_mask:
                raise V2RLEValidationError(
                    "ADC RLE item contains an out-of-range code",
                    "invalid_item",
                )
        decoded_count += run_length
        previous_item = item
    if decoded_count != header.item_count:
        raise V2RLEValidationError(
            "RLE run lengths do not sum to header.item_count",
            "count_mismatch",
        )
    return int(run_count)


def _validate_v2_payload(header: V2FrameHeader, payload: bytes) -> int | None:
    if len(payload) != header.payload_length:
        raise V2FrameValidationError(
            "payload length disagrees with header",
            reason="invalid_length",
            error_code=constants.ErrorCode.INVALID_LENGTH,
        )
    if header.kind in _DATA_KINDS:
        if header.encoding is constants.FrameEncoding.RLE:
            return _validate_rle_payload(header, payload)
        if header.kind is constants.FrameKind.ADC_DATA:
            code_mask = (1 << constants.ADC_RESOLUTION_BITS) - 1
            for adc0, adc1 in struct.iter_unpack("<HH", payload):
                if adc0 & ~code_mask or adc1 & ~code_mask:
                    raise V2FrameValidationError(
                        "ADC payload contains out-of-range codes"
                    )
        return None

    if header.kind is constants.FrameKind.CONFIGURE_REQUEST:
        raw_encoding = payload[constants.CONFIGURE_REQUEST_ENCODING_OFFSET]
        try:
            constants.ConfigurationEncoding(raw_encoding)
        except ValueError as exc:
            raise V2FrameValidationError(
                "CONFIGURE request contains an unknown encoding"
            ) from exc
    elif header.kind in {
        constants.FrameKind.CONFIGURE_RESPONSE,
        constants.FrameKind.START_RESPONSE,
    } and not (header.flags & constants.FrameFlag.RESPONSE_ERROR):
        raw_encoding = payload[constants.CONFIGURE_RESPONSE_ENCODING_OFFSET]
        try:
            constants.ConfigurationEncoding(raw_encoding)
        except ValueError as exc:
            raise V2FrameValidationError(
                "configuration response contains an unknown encoding"
            ) from exc
    elif header.kind is constants.FrameKind.INFO_RESPONSE and not (
        header.flags & constants.FrameFlag.RESPONSE_ERROR
    ):
        capability_bits = struct.unpack_from(
            "<I", payload, constants.INFO_RESPONSE_CAPABILITY_BITS_OFFSET
        )[0]
        if capability_bits & ~constants.KNOWN_CAPABILITY_MASK:
            raise V2FrameValidationError("INFO contains unknown capability bits")
    return None


def decode_v2_frame(data: BytesLike) -> V2Frame:
    """Decode exactly one v2 frame without allocating its decoded item count."""

    frame_bytes = bytes(data)
    header = _decode_v2_header(frame_bytes)
    if len(frame_bytes) != header.total_length:
        raise V2FrameValidationError(
            f"declared frame length is {header.total_length}, got {len(frame_bytes)}",
            reason="invalid_length",
            error_code=constants.ErrorCode.INVALID_LENGTH,
        )
    payload_end = constants.HEADER_SIZE + header.payload_length
    observed_checksum = _TRAILER.unpack_from(frame_bytes, payload_end)[0]
    expected_checksum = compute_v2_checksum(
        frame_bytes[:payload_end], header.checksum_algorithm
    )
    if observed_checksum != expected_checksum:
        raise V2ChecksumMismatchError(expected_checksum, observed_checksum)
    payload = frame_bytes[constants.HEADER_SIZE : payload_end]
    run_count = _validate_v2_payload(header, payload)
    return V2Frame(
        header=header,
        payload=payload,
        checksum=observed_checksum,
        run_count=run_count,
    )


def _decode_buffered_v2_frame(
    buffer: bytearray,
    offset: int,
    header: V2FrameHeader,
) -> V2Frame:
    payload_start = offset + constants.HEADER_SIZE
    payload_end = payload_start + header.payload_length
    observed_checksum = _TRAILER.unpack_from(buffer, payload_end)[0]
    checksum_view = memoryview(buffer)[offset:payload_end]
    try:
        expected_checksum = compute_v2_checksum(
            checksum_view,
            header.checksum_algorithm,
        )
    finally:
        checksum_view.release()
    if observed_checksum != expected_checksum:
        raise V2ChecksumMismatchError(expected_checksum, observed_checksum)

    payload_view = memoryview(buffer)[payload_start:payload_end]
    try:
        payload = payload_view.tobytes()
    finally:
        payload_view.release()
    run_count = _validate_v2_payload(header, payload)
    return V2Frame(
        header=header,
        payload=payload,
        checksum=observed_checksum,
        run_count=run_count,
    )


class IncrementalV2FrameParser(BoundedIncrementalParser[V2FrameHeader, V2Frame]):
    """Bounded v2 parser using the same recovery loop as protocol v1."""

    max_buffered_bytes = MAX_V2_BUFFERED_BYTES

    def __init__(self) -> None:
        super().__init__(
            magic_bytes=constants.MAGIC_BYTES,
            header_size=constants.HEADER_SIZE,
            max_frame_bytes=_MAX_FRAME_BYTES,
            decode_header=_decode_v2_header,
            decode_frame=_decode_buffered_v2_frame,
            validation_error=V2FrameValidationError,
            checksum_error=V2ChecksumMismatchError,
        )


__all__ = [
    "MAX_V2_BUFFERED_BYTES",
    "IncrementalV2FrameParser",
    "ParserCounters",
    "V2ChecksumMismatchError",
    "V2Frame",
    "V2FrameHeader",
    "V2FrameValidationError",
    "V2ProtocolError",
    "V2RLEValidationError",
    "V2UnsupportedChecksumError",
    "compute_v2_checksum",
    "decode_v2_frame",
]
