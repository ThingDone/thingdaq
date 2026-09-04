"""Explicit auxiliary-output protocol-v2 wire codec.

Protocol v1 remains the default acquisition protocol.  This module is used
only for output capability discovery and output control frames.
"""

from __future__ import annotations

import struct
from dataclasses import dataclass

from ._generated import protocol_v2_constants as constants
from .checksum import compute_checksum_value
from .models import CommandResponse, ResponseValue
from .output import (
    DigitalOutputCapabilities,
    DigitalOutputStatus,
    decode_append_echo,
)
from .protocol import (
    ChecksumMismatchError,
    FrameValidationError,
    UnsupportedChecksumError,
)

BytesLike = bytes | bytearray | memoryview
_HEADER = struct.Struct(constants.HEADER_STRUCT_FORMAT)
_TRAILER = struct.Struct("<I")
_RESPONSE_PREFIX = struct.Struct("<BBH")
_OUTPUT_KINDS = frozenset(
    kind for kind in constants.FrameKind if kind.name.startswith("OUTPUT_")
)
_REQUEST_KINDS = frozenset(constants.REQUEST_RESPONSE_KIND)
_RESPONSE_KINDS = frozenset(constants.REQUEST_RESPONSE_KIND.values())


@dataclass(frozen=True, slots=True)
class V2FrameHeader:
    """Decoded experimental-v2 header."""

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
class V2Frame:
    """Fully validated experimental-v2 frame."""

    header: V2FrameHeader
    payload: bytes
    checksum: int

    def to_bytes(self) -> bytes:
        return self.header.to_bytes() + self.payload + _TRAILER.pack(self.checksum)


def _checksum(data: BytesLike, algorithm: constants.ChecksumAlgorithm) -> int:
    # Protocol v2 deliberately reuses the frozen checksum IDs and algorithms.
    from ._generated import protocol_constants as v1_constants

    try:
        v1_algorithm = v1_constants.ChecksumAlgorithm(int(algorithm))
    except ValueError as error:
        raise UnsupportedChecksumError(int(algorithm)) from error
    result = compute_checksum_value(data, v1_algorithm)
    if result is None:
        raise UnsupportedChecksumError(int(algorithm))
    return result


def decode_v2_header(data: BytesLike, offset: int = 0) -> V2FrameHeader:
    """Decode and validate a complete header candidate at ``offset``."""

    if offset < 0 or len(data) - offset < constants.HEADER_SIZE:
        raise FrameValidationError("protocol-v2 frame is shorter than its header")
    (
        magic,
        version,
        raw_kind,
        raw_flags,
        header_length,
        raw_checksum,
        reserved,
        total_length,
        payload_length,
        run_id,
        sequence,
        request_id,
        first_sample_ticks,
        item_count,
    ) = _HEADER.unpack_from(data, offset)
    if magic != constants.MAGIC or version != constants.PROTOCOL_VERSION:
        raise FrameValidationError("invalid protocol-v2 magic or version")
    try:
        kind = constants.FrameKind(raw_kind)
        flags = constants.FrameFlag(raw_flags)
        checksum = constants.ChecksumAlgorithm(raw_checksum)
    except ValueError as error:
        raise FrameValidationError("unknown protocol-v2 header enum") from error
    header = V2FrameHeader(
        kind,
        flags,
        checksum,
        total_length,
        payload_length,
        run_id,
        sequence,
        request_id,
        first_sample_ticks,
        item_count,
        version,
        header_length,
    )
    _validate_header(header, reserved)
    return header


def _validate_header(header: V2FrameHeader, reserved: int = 0) -> None:
    if header.header_length != constants.HEADER_SIZE or reserved:
        raise FrameValidationError("invalid protocol-v2 header size or reserved byte")
    if header.checksum_algorithm != constants.BOOTSTRAP_CHECKSUM_ALGORITHM:
        raise FrameValidationError(
            "protocol-v2 output control requires bootstrap checksum"
        )
    if int(header.flags) & ~int(constants.ALLOWED_FLAGS_BY_KIND[header.kind]):
        raise FrameValidationError("invalid protocol-v2 frame flags")
    expected_total = (
        constants.HEADER_SIZE + header.payload_length + constants.TRAILER_SIZE
    )
    if header.total_length != expected_total:
        raise FrameValidationError("inconsistent protocol-v2 frame lengths")
    if (
        not constants.MIN_FRAME_BYTES
        <= header.total_length
        <= constants.MAX_CONTROL_FRAME_BYTES
    ):
        raise FrameValidationError("protocol-v2 output frame exceeds control bounds")
    if (
        not header.request_id
        or header.sequence
        or header.first_sample_ticks
        or header.item_count
    ):
        raise FrameValidationError("invalid protocol-v2 output control header fields")
    if header.kind not in _OUTPUT_KINDS and header.kind not in {
        constants.FrameKind.INFO_REQUEST,
        constants.FrameKind.INFO_RESPONSE,
        constants.FrameKind.ERROR_RESPONSE,
    }:
        raise FrameValidationError(
            "only INFO and auxiliary-output v2 frames are accepted"
        )
    if header.kind in _OUTPUT_KINDS and header.run_id == 0:
        raise FrameValidationError("output frames require a nonzero generation")
    if (
        header.kind
        in {constants.FrameKind.INFO_REQUEST, constants.FrameKind.INFO_RESPONSE}
        and header.run_id
    ):
        raise FrameValidationError("INFO frames require generation zero")
    response_error = bool(header.flags & constants.FrameFlag.RESPONSE_ERROR)
    schema = constants.PAYLOAD_SCHEMA_BY_KIND[header.kind]
    if header.kind in _RESPONSE_KINDS and response_error:
        schema = constants.ERROR_PAYLOAD_SCHEMA_BY_KIND[header.kind]
    expected_payload = constants.PAYLOAD_SIZE_BY_SCHEMA[schema]
    if header.payload_length != expected_payload:
        raise FrameValidationError(
            f"{header.kind.name} payload must be {expected_payload} bytes"
        )
    if (
        header.kind in _REQUEST_KINDS
        and header.total_length > constants.MAX_COMMAND_FRAME_BYTES
    ):
        raise FrameValidationError(
            "protocol-v2 command exceeds the eight-byte payload bound"
        )


def _validate_prefix(
    header: V2FrameHeader, payload: bytes
) -> tuple[constants.ResponseStatus, constants.ErrorCode]:
    raw_status, reserved, raw_error = _RESPONSE_PREFIX.unpack_from(payload)
    try:
        status = constants.ResponseStatus(raw_status)
        error = constants.ErrorCode(raw_error)
    except ValueError as cause:
        raise FrameValidationError("unknown response status or error") from cause
    response_error = bool(header.flags & constants.FrameFlag.RESPONSE_ERROR)
    if reserved or response_error != (status is constants.ResponseStatus.ERROR):
        raise FrameValidationError("response prefix disagrees with flags")
    if (status is constants.ResponseStatus.OK) != (error is constants.ErrorCode.OK):
        raise FrameValidationError("response status and error disagree")
    return status, error


def _validate_payload(header: V2FrameHeader, payload: bytes) -> None:
    if len(payload) != header.payload_length:
        raise FrameValidationError("payload length disagrees with protocol-v2 header")
    kind = header.kind
    if kind is constants.FrameKind.INFO_REQUEST or kind in {
        constants.FrameKind.OUTPUT_ARM_REQUEST,
        constants.FrameKind.OUTPUT_STATUS_REQUEST,
        constants.FrameKind.OUTPUT_CLEAR_REQUEST,
    }:
        return
    if kind is constants.FrameKind.OUTPUT_BEGIN_REQUEST:
        _, idle_state = struct.unpack("<II", payload)
        if idle_state & ~constants.OUTPUT_LEGAL_STATE_MASK:
            raise FrameValidationError("OUTPUT_BEGIN idle state uses reserved bits")
        return
    if kind is constants.FrameKind.OUTPUT_APPEND_REQUEST:
        duration, state = struct.unpack("<II", payload)
        if not duration or state & ~constants.OUTPUT_LEGAL_STATE_MASK:
            raise FrameValidationError("OUTPUT_APPEND segment is invalid")
        return
    if kind is constants.FrameKind.OUTPUT_COMMIT_REQUEST:
        segment_count, _ = struct.unpack("<II", payload)
        if not 1 <= segment_count <= constants.OUTPUT_SEGMENT_CAPACITY:
            raise FrameValidationError("OUTPUT_COMMIT segment count is invalid")
        return
    if kind in _RESPONSE_KINDS or kind is constants.FrameKind.ERROR_RESPONSE:
        _validate_prefix(header, payload)
        if kind is constants.FrameKind.INFO_RESPONSE:
            DigitalOutputCapabilities.from_info_payload(payload)
        elif kind is constants.FrameKind.OUTPUT_APPEND_RESPONSE and not (
            header.flags & constants.FrameFlag.RESPONSE_ERROR
        ):
            decode_append_echo(payload)
        elif kind in _OUTPUT_KINDS:
            status = DigitalOutputStatus.from_payload(payload)
            if (
                status.state is not constants.OutputState.EMPTY
                and status.generation != header.run_id
            ):
                raise FrameValidationError("output response generation echo mismatch")
            response_error = bool(header.flags & constants.FrameFlag.RESPONSE_ERROR)
            if (
                response_error
                and status.output_error is constants.OutputError.NONE
                or not response_error
                and status.state is not constants.OutputState.FAULTED
                and status.output_error is not constants.OutputError.NONE
            ):
                raise FrameValidationError(
                    "output response status and output error disagree"
                )


def encode_v2_frame(
    kind: constants.FrameKind | int,
    payload: BytesLike = b"",
    *,
    flags: constants.FrameFlag | int = constants.FrameFlag.NONE,
    run_id: int = 0,
    request_id: int = 0,
) -> bytes:
    """Encode one strict INFO or output-control protocol-v2 frame."""

    selected_kind = constants.FrameKind(kind)
    payload_bytes = bytes(payload)
    header = V2FrameHeader(
        selected_kind,
        constants.FrameFlag(flags),
        constants.BOOTSTRAP_CHECKSUM_ALGORITHM,
        constants.HEADER_SIZE + len(payload_bytes) + constants.TRAILER_SIZE,
        len(payload_bytes),
        run_id,
        0,
        request_id,
        0,
        0,
    )
    _validate_header(header)
    _validate_payload(header, payload_bytes)
    body = header.to_bytes() + payload_bytes
    return body + _TRAILER.pack(_checksum(body, header.checksum_algorithm))


def decode_buffered_v2_frame(
    buffer: bytearray, offset: int, header: V2FrameHeader
) -> V2Frame:
    """Decode one complete v2 frame already bounded by the shared parser."""

    payload_start = offset + constants.HEADER_SIZE
    payload_end = payload_start + header.payload_length
    observed = _TRAILER.unpack_from(buffer, payload_end)[0]
    view = memoryview(buffer)[offset:payload_end]
    try:
        expected = _checksum(view, header.checksum_algorithm)
    finally:
        view.release()
    if observed != expected:
        raise ChecksumMismatchError(expected, observed)
    payload = bytes(buffer[payload_start:payload_end])
    _validate_payload(header, payload)
    return V2Frame(header, payload, observed)


def decode_v2_response(frame: V2Frame) -> CommandResponse[ResponseValue]:
    """Decode a correlated INFO or output response for the shared reader."""

    if frame.header.kind not in _RESPONSE_KINDS | {constants.FrameKind.ERROR_RESPONSE}:
        raise TypeError("protocol-v2 frame is not a response")
    status, error = _validate_prefix(frame.header, frame.payload)
    value: ResponseValue | None = None
    output_error: constants.OutputError | None = None
    rejected_kind: int | None = None
    rejected_version: int | None = None
    if status is constants.ResponseStatus.OK:
        if frame.header.kind is constants.FrameKind.INFO_RESPONSE:
            value = DigitalOutputCapabilities.from_info_payload(frame.payload)
        elif frame.header.kind is constants.FrameKind.OUTPUT_APPEND_RESPONSE:
            value = decode_append_echo(frame.payload)
        else:
            value = DigitalOutputStatus.from_payload(frame.payload)
    elif frame.header.kind in _OUTPUT_KINDS:
        snapshot = DigitalOutputStatus.from_payload(frame.payload)
        output_error = snapshot.output_error
    elif frame.header.kind is constants.FrameKind.ERROR_RESPONSE:
        rejected_kind = frame.payload[constants.ERROR_RESPONSE_REJECTED_KIND_OFFSET]
        rejected_version = frame.payload[
            constants.ERROR_RESPONSE_REJECTED_VERSION_OFFSET
        ]
    # The frozen v1 enums have identical response/error values and are retained
    # by the shared public CommandResponse model.
    from ._generated import protocol_constants as v1_constants

    return CommandResponse(
        kind=frame.header.kind,  # type: ignore[arg-type]
        request_id=frame.header.request_id,
        run_id=frame.header.run_id,
        status=v1_constants.ResponseStatus(int(status)),
        error_code=v1_constants.ErrorCode(int(error)),
        value=value,
        rejected_kind=rejected_kind,
        rejected_version=rejected_version,
        output_error=output_error,
    )


__all__ = [
    "V2Frame",
    "V2FrameHeader",
    "decode_buffered_v2_frame",
    "decode_v2_header",
    "decode_v2_response",
    "encode_v2_frame",
]
