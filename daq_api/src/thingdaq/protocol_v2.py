"""Experimental protocol-v2 framing, bounded RLE, and typed decoding.

Protocol v2 is deliberately isolated from the default protocol-v1 path.  Its
parser validates the transmitted checksum and the complete canonical record
stream before :func:`decode_v2_data_block` allocates the fixed-size logical
payload exposed through the existing :class:`~thingdaq.models.ADCBlock` and
:class:`~thingdaq.models.GPIOBlock` models.
"""

from __future__ import annotations

import struct
from dataclasses import dataclass, replace
from enum import Enum
from typing import TypeAlias

from ._generated import protocol_constants as v1_constants
from ._generated import protocol_v2_constants as constants
from ._incremental import BoundedIncrementalParser, BytesLike
from .checksum import HOST_SUPPORTED_CHECKSUM_ALGORITHMS, compute_checksum_value
from .models import (
    ADCBlock,
    CommandResponse,
    DAQConfiguration,
    DeviceInfo,
    GPIOBlock,
    ResponseValue,
    decode_message,
)
from .protocol import Frame as V1Frame
from .protocol import FrameHeader as V1FrameHeader
from .protocol import ParserCounters

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


class V2EncodingNotNegotiatedError(V2FrameValidationError):
    """A data-frame selector is incompatible with the active configuration."""

    def __init__(self, message: str) -> None:
        super().__init__(message, reason="encoding_not_negotiated")


class RawFallbackReason(str, Enum):
    """Why a decoded v2 frame used the raw selector."""

    NOT_REQUESTED = "not_requested"
    RLE_NOT_SMALLER = "rle_not_smaller"


@dataclass(frozen=True, slots=True)
class EncodingDiagnostics:
    """Per-frame wire/decoded byte evidence retained on a logical block."""

    negotiated_encoding: constants.ConfigurationEncoding
    frame_encoding: constants.FrameEncoding
    encoded_payload: bytes
    decoded_bytes: int
    run_count: int
    raw_fallback_reason: RawFallbackReason | None

    def __post_init__(self) -> None:
        try:
            negotiated = constants.ConfigurationEncoding(self.negotiated_encoding)
            selected = constants.FrameEncoding(self.frame_encoding)
        except (TypeError, ValueError) as exc:
            raise ValueError(
                "encoding diagnostics contain an unknown selector"
            ) from exc
        if not isinstance(self.encoded_payload, (bytes, bytearray, memoryview)):
            raise TypeError("encoded payload must be bytes-like")
        try:
            encoded_payload = bytes(self.encoded_payload)
        except (TypeError, ValueError) as exc:
            raise TypeError("encoded payload must be bytes-like") from exc
        if (
            not isinstance(self.decoded_bytes, int)
            or isinstance(self.decoded_bytes, bool)
            or self.decoded_bytes <= 0
        ):
            raise ValueError("decoded byte count must be positive")
        if (
            not isinstance(self.run_count, int)
            or isinstance(self.run_count, bool)
            or self.run_count <= 0
        ):
            raise ValueError("run count must be positive")
        fallback_reason: RawFallbackReason | None
        if self.raw_fallback_reason is None:
            fallback_reason = None
        else:
            try:
                fallback_reason = RawFallbackReason(self.raw_fallback_reason)
            except (TypeError, ValueError) as exc:
                raise ValueError("raw fallback reason is unknown") from exc
        if selected is constants.FrameEncoding.RLE:
            if negotiated is not constants.ConfigurationEncoding.RLE_AUTO:
                raise ValueError("RLE diagnostics require RLE_AUTO negotiation")
            if fallback_reason is not None:
                raise ValueError("an RLE frame cannot have a raw fallback reason")
        else:
            expected_reason = (
                RawFallbackReason.NOT_REQUESTED
                if negotiated is constants.ConfigurationEncoding.RAW
                else RawFallbackReason.RLE_NOT_SMALLER
            )
            if fallback_reason is not expected_reason:
                raise ValueError(
                    "RAW frame reason disagrees with the negotiated encoding"
                )
        object.__setattr__(self, "negotiated_encoding", negotiated)
        object.__setattr__(self, "frame_encoding", selected)
        object.__setattr__(self, "encoded_payload", encoded_payload)
        object.__setattr__(self, "raw_fallback_reason", fallback_reason)

    @property
    def encoded_bytes(self) -> int:
        """Number of transmitted payload bytes, excluding the fixed envelope."""

        return len(self.encoded_payload)

    @property
    def savings(self) -> int:
        """Payload and complete-wire bytes saved relative to the raw frame."""

        return self.decoded_bytes - self.encoded_bytes

    @property
    def encoded_frame_bytes(self) -> int:
        """Complete transmitted bytes including the fixed header and trailer."""

        return self.encoded_bytes + constants.HEADER_SIZE + constants.TRAILER_SIZE

    @property
    def raw_frame_bytes(self) -> int:
        """Complete bytes the same logical frame uses with RAW encoding."""

        return self.decoded_bytes + constants.HEADER_SIZE + constants.TRAILER_SIZE

    @property
    def encoded_payload_view(self) -> memoryview:
        """Zero-copy read-only view of the exact transmitted payload."""

        return memoryview(self.encoded_payload)


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


V2DataBlock: TypeAlias = ADCBlock | GPIOBlock
V2DecodedMessage: TypeAlias = V2DataBlock | CommandResponse[ResponseValue] | V1Frame


def _unsigned(name: str, value: int, bits: int) -> int:
    if (
        not isinstance(value, int)
        or isinstance(value, bool)
        or not 0 <= value < (1 << bits)
    ):
        raise V2FrameValidationError(f"{name} must be an unsigned {bits}-bit value")
    return value


def _byte_view(data: BytesLike, *, name: str) -> memoryview:
    if not isinstance(data, (bytes, bytearray, memoryview)):
        raise TypeError(f"{name} must be bytes-like")
    try:
        return memoryview(data).cast("B")
    except (TypeError, ValueError) as exc:
        raise ValueError(f"{name} must be a contiguous byte buffer") from exc


def _owned_bytes(data: BytesLike, *, name: str) -> bytes:
    view = _byte_view(data, name=name)
    try:
        return view.tobytes()
    finally:
        view.release()


def _validated_codec_shape(
    *,
    item_size: int,
    item_count: int,
    max_items: int,
) -> None:
    for name, value in (
        ("item_size", item_size),
        ("item_count", item_count),
        ("max_items", max_items),
    ):
        if not isinstance(value, int) or isinstance(value, bool) or value <= 0:
            raise ValueError(f"{name} must be a positive integer")
    if item_count > max_items:
        raise V2RLEValidationError(
            "decoded item count exceeds the advertised frame bound",
            "decoded_count_overflow",
        )
    if item_count > constants.RLE_RUN_LENGTH_MAX:
        raise V2RLEValidationError(
            "one frame cannot encode its item count in a u16 run",
            "decoded_count_overflow",
        )


def count_rle_runs(
    decoded_payload: BytesLike,
    *,
    item_size: int,
    max_items: int,
) -> int:
    """Count canonical runs in a bounded raw logical-item payload."""

    if not isinstance(item_size, int) or isinstance(item_size, bool) or item_size <= 0:
        raise ValueError("item_size must be a positive integer")
    if not isinstance(max_items, int) or isinstance(max_items, bool) or max_items <= 0:
        raise ValueError("max_items must be a positive integer")
    view = _byte_view(decoded_payload, name="decoded payload")
    try:
        if len(view) == 0 or len(view) % item_size:
            raise V2RLEValidationError(
                "decoded payload ends inside a logical item",
                "truncated_item",
            )
        item_count = len(view) // item_size
        _validated_codec_shape(
            item_size=item_size,
            item_count=item_count,
            max_items=max_items,
        )
        runs = 1
        previous = bytes(view[:item_size])
        for offset in range(item_size, len(view), item_size):
            item = bytes(view[offset : offset + item_size])
            if item != previous:
                runs += 1
                previous = item
        return runs
    finally:
        view.release()


def encode_rle_payload(
    decoded_payload: BytesLike,
    *,
    item_size: int,
    max_items: int,
) -> bytes:
    """Encode complete logical items into canonical frame-local RLE records.

    The input view is scanned once and output growth is bounded by
    ``max_items * (item_size + 2)``.  ThingDAQ data-frame callers use the much
    tighter generated adaptive-selection limit before putting this result on
    the wire.
    """

    if not isinstance(item_size, int) or isinstance(item_size, bool) or item_size <= 0:
        raise ValueError("item_size must be a positive integer")
    if not isinstance(max_items, int) or isinstance(max_items, bool) or max_items <= 0:
        raise ValueError("max_items must be a positive integer")
    view = _byte_view(decoded_payload, name="decoded payload")
    try:
        if len(view) == 0 or len(view) % item_size:
            raise V2RLEValidationError(
                "decoded payload ends inside a logical item",
                "truncated_item",
            )
        item_count = len(view) // item_size
        _validated_codec_shape(
            item_size=item_size,
            item_count=item_count,
            max_items=max_items,
        )
        encoded = bytearray()
        previous = bytes(view[:item_size])
        run_length = 1
        for offset in range(item_size, len(view), item_size):
            item = bytes(view[offset : offset + item_size])
            if item == previous:
                run_length += 1
                continue
            encoded.extend(struct.pack("<H", run_length))
            encoded.extend(previous)
            previous = item
            run_length = 1
        encoded.extend(struct.pack("<H", run_length))
        encoded.extend(previous)
        return bytes(encoded)
    finally:
        view.release()


def decode_rle_payload(
    encoded_payload: BytesLike,
    *,
    item_size: int,
    item_count: int,
    max_items: int,
) -> bytes:
    """Validate fully, then expand into one fixed, advertised-size buffer."""

    _validated_codec_shape(
        item_size=item_size,
        item_count=item_count,
        max_items=max_items,
    )
    view = _byte_view(encoded_payload, name="encoded payload")
    try:
        record_size = item_size + 2
        if len(view) == 0 or len(view) % record_size:
            raise V2RLEValidationError(
                "RLE payload ends inside a logical item",
                "truncated_item",
            )

        decoded_count = 0
        previous: bytes | None = None
        for offset in range(0, len(view), record_size):
            run_length = struct.unpack_from("<H", view, offset)[0]
            if run_length == 0:
                raise V2RLEValidationError("RLE run length is zero", "zero_run")
            if run_length > item_count - decoded_count:
                raise V2RLEValidationError(
                    "RLE decoded count exceeds the advertised item bound",
                    "decoded_count_overflow",
                )
            item = bytes(view[offset + 2 : offset + record_size])
            if item == previous:
                raise V2RLEValidationError(
                    "adjacent RLE records contain the same logical item",
                    "adjacent_equal_runs",
                )
            decoded_count += run_length
            previous = item
        if decoded_count != item_count:
            raise V2RLEValidationError(
                "RLE run lengths do not sum to the advertised item count",
                "count_mismatch",
            )

        # Allocation is based solely on the already bounded header count.  A
        # second pass means no partially decoded payload can escape validation.
        decoded = bytearray(item_count * item_size)
        write_offset = 0
        for offset in range(0, len(view), record_size):
            run_length = struct.unpack_from("<H", view, offset)[0]
            item = bytes(view[offset + 2 : offset + record_size])
            byte_count = run_length * item_size
            decoded[write_offset : write_offset + byte_count] = item * run_length
            write_offset += byte_count
        return bytes(decoded)
    finally:
        view.release()


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


def encode_v2_frame(
    kind: constants.FrameKind | v1_constants.FrameKind | int,
    payload: BytesLike = b"",
    *,
    flags: constants.FrameFlag | v1_constants.FrameFlag | int = (
        constants.FrameFlag.NONE
    ),
    checksum_algorithm: (
        constants.ChecksumAlgorithm | v1_constants.ChecksumAlgorithm | int | None
    ) = None,
    encoding: constants.FrameEncoding | int = constants.FrameEncoding.RAW,
    run_id: int = 0,
    sequence: int = 0,
    request_id: int = 0,
    first_sample_ticks: int = 0,
    item_count: int = 0,
) -> bytes:
    """Encode one validated protocol-v2 frame and its transmitted checksum."""

    try:
        selected_kind = constants.FrameKind(kind)
    except (TypeError, ValueError) as exc:
        raise V2FrameValidationError(
            f"unknown frame kind {int(kind)}",
            reason="unknown_frame_kind",
            error_code=constants.ErrorCode.UNKNOWN_FRAME_KIND,
        ) from exc
    try:
        selected_encoding = constants.FrameEncoding(encoding)
    except (TypeError, ValueError) as exc:
        raise V2FrameValidationError(
            f"illegal frame encoding selector {int(encoding)}",
            reason="illegal_selector",
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
        except (TypeError, ValueError) as exc:
            raise V2UnsupportedChecksumError(int(checksum_algorithm)) from exc
    payload_bytes = _owned_bytes(payload, name="payload")
    header = V2FrameHeader(
        kind=selected_kind,
        flags=constants.FrameFlag(_unsigned("flags", int(flags), 16)),
        checksum_algorithm=selected_checksum,
        encoding=selected_encoding,
        total_length=(
            constants.HEADER_SIZE + len(payload_bytes) + constants.TRAILER_SIZE
        ),
        payload_length=len(payload_bytes),
        run_id=_unsigned("run_id", run_id, 32),
        sequence=_unsigned("sequence", sequence, 32),
        request_id=_unsigned("request_id", request_id, 32),
        first_sample_ticks=_unsigned(
            "first_sample_ticks",
            first_sample_ticks,
            64,
        ),
        item_count=_unsigned("item_count", item_count, 32),
    )
    _validate_v2_header(header)
    run_count = _validate_v2_payload(header, payload_bytes)
    body = header.to_bytes() + payload_bytes
    checksum = compute_v2_checksum(body, selected_checksum)
    return V2Frame(
        header=header,
        payload=payload_bytes,
        checksum=checksum,
        run_count=run_count,
    ).to_bytes()


def _data_shape(
    kind: constants.FrameKind,
) -> tuple[int, int, int]:
    if kind is constants.FrameKind.ADC_DATA:
        return (
            constants.ADC_BYTES_PER_PAIR,
            constants.ADC_PAIRS_PER_FRAME,
            constants.ADC_RLE_MAX_SELECTED_PAYLOAD_BYTES,
        )
    if kind is constants.FrameKind.GPIO_DATA:
        return (
            1,
            constants.GPIO_SAMPLES_PER_FRAME,
            constants.GPIO_RLE_MAX_SELECTED_PAYLOAD_BYTES,
        )
    raise TypeError("kind must be ADC_DATA or GPIO_DATA")


def encode_v2_data_frame(
    kind: constants.FrameKind | v1_constants.FrameKind | int,
    decoded_payload: BytesLike,
    *,
    configuration_encoding: constants.ConfigurationEncoding | int = (
        constants.ConfigurationEncoding.RAW
    ),
    flags: constants.FrameFlag | v1_constants.FrameFlag | int = (
        constants.FrameFlag.NONE
    ),
    checksum_algorithm: (
        constants.ChecksumAlgorithm | v1_constants.ChecksumAlgorithm | int
    ) = constants.DEFAULT_CHECKSUM_ALGORITHM,
    run_id: int,
    sequence: int,
    first_sample_ticks: int,
) -> bytes:
    """Encode one fixed logical data frame with strict adaptive raw fallback."""

    try:
        selected_kind = constants.FrameKind(kind)
    except (TypeError, ValueError) as exc:
        raise TypeError("kind must be ADC_DATA or GPIO_DATA") from exc
    item_size, item_count, max_selected_payload = _data_shape(selected_kind)
    try:
        negotiated = constants.ConfigurationEncoding(configuration_encoding)
    except (TypeError, ValueError) as exc:
        raise ValueError("configuration encoding must be RAW or RLE_AUTO") from exc
    raw_payload = _owned_bytes(decoded_payload, name="decoded payload")
    if len(raw_payload) != constants.DATA_PAYLOAD_BYTES:
        raise V2FrameValidationError(
            f"{selected_kind.name} requires {constants.DATA_PAYLOAD_BYTES} raw bytes",
            reason="invalid_length",
            error_code=constants.ErrorCode.INVALID_LENGTH,
        )

    selected_payload = raw_payload
    selected_frame_encoding = constants.FrameEncoding.RAW
    if negotiated is constants.ConfigurationEncoding.RLE_AUTO:
        rle_payload = encode_rle_payload(
            raw_payload,
            item_size=item_size,
            max_items=item_count,
        )
        if len(rle_payload) < len(raw_payload):
            if len(rle_payload) > max_selected_payload:  # pragma: no cover - math guard
                raise V2FrameValidationError(
                    "selected RLE payload exceeds the generated frame bound",
                    reason="invalid_length",
                    error_code=constants.ErrorCode.INVALID_LENGTH,
                )
            selected_payload = rle_payload
            selected_frame_encoding = constants.FrameEncoding.RLE

    return encode_v2_frame(
        selected_kind,
        selected_payload,
        flags=flags,
        checksum_algorithm=checksum_algorithm,
        encoding=selected_frame_encoding,
        run_id=run_id,
        sequence=sequence,
        first_sample_ticks=first_sample_ticks,
        item_count=item_count,
    )


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

    frame_bytes = _owned_bytes(data, name="frame")
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


def decode_v2_data_block(
    frame: V2Frame,
    *,
    negotiated_encoding: constants.ConfigurationEncoding | int,
) -> V2DataBlock:
    """Decode one validated data envelope into the existing logical model.

    RAW payload bytes are handed directly to the block model.  RLE payloads
    undergo a second full record-validation pass before the single bounded
    expansion allocation is returned.
    """

    if frame.header.kind not in _DATA_KINDS:
        raise TypeError("frame is not ADC_DATA or GPIO_DATA")
    try:
        negotiated = constants.ConfigurationEncoding(negotiated_encoding)
    except (TypeError, ValueError) as exc:
        raise ValueError("negotiated encoding must be RAW or RLE_AUTO") from exc
    if (
        frame.header.encoding is constants.FrameEncoding.RLE
        and negotiated is not constants.ConfigurationEncoding.RLE_AUTO
    ):
        raise V2EncodingNotNegotiatedError(
            "an RLE frame arrived during a RAW-configured run"
        )

    item_size, item_count, _ = _data_shape(frame.header.kind)
    if frame.header.encoding is constants.FrameEncoding.RLE:
        decoded_payload = decode_rle_payload(
            frame.payload,
            item_size=item_size,
            item_count=item_count,
            max_items=item_count,
        )
        run_count = frame.run_count
        if run_count is None:  # pragma: no cover - V2Frame decoder invariant
            raise V2RLEValidationError(
                "validated RLE frame omitted its run count",
                "count_mismatch",
            )
        fallback_reason = None
    else:
        # ``bytes(existing_bytes)`` in each block model retains this exact
        # immutable object, preserving the v1 zero-copy raw-payload behavior.
        decoded_payload = frame.payload
        run_count = count_rle_runs(
            decoded_payload,
            item_size=item_size,
            max_items=item_count,
        )
        fallback_reason = (
            RawFallbackReason.NOT_REQUESTED
            if negotiated is constants.ConfigurationEncoding.RAW
            else RawFallbackReason.RLE_NOT_SMALLER
        )
    diagnostics = EncodingDiagnostics(
        negotiated_encoding=negotiated,
        frame_encoding=frame.header.encoding,
        encoded_payload=frame.payload,
        decoded_bytes=len(decoded_payload),
        run_count=run_count,
        raw_fallback_reason=fallback_reason,
    )
    flags = v1_constants.FrameFlag(int(frame.header.flags))
    checksum_algorithm = v1_constants.ChecksumAlgorithm(
        int(frame.header.checksum_algorithm)
    )
    if frame.header.kind is constants.FrameKind.ADC_DATA:
        return ADCBlock(
            run_id=frame.header.run_id,
            sequence=frame.header.sequence,
            first_sample_ticks=frame.header.first_sample_ticks,
            payload=decoded_payload,
            flags=flags,
            checksum_algorithm=checksum_algorithm,
            encoding_diagnostics=diagnostics,
        )
    return GPIOBlock(
        run_id=frame.header.run_id,
        sequence=frame.header.sequence,
        first_sample_ticks=frame.header.first_sample_ticks,
        payload=decoded_payload,
        flags=flags,
        checksum_algorithm=checksum_algorithm,
        encoding_diagnostics=diagnostics,
    )


def _v1_compatible_control_frame(frame: V2Frame) -> V1Frame:
    """Translate a checksummed v2 control frame for the shared model decoder."""

    if frame.header.kind in _DATA_KINDS:
        raise TypeError("data frames require the bounded v2 data decoder")
    payload = bytearray(frame.payload)
    response_ok = bool(payload) and payload[0] == int(constants.ResponseStatus.OK)
    if frame.header.kind is constants.FrameKind.INFO_RESPONSE and response_ok:
        payload[constants.INFO_RESPONSE_PROTOCOL_VERSION_OFFSET] = (
            v1_constants.PROTOCOL_VERSION
        )
        capability_bits = struct.unpack_from(
            "<I",
            payload,
            constants.INFO_RESPONSE_CAPABILITY_BITS_OFFSET,
        )[0]
        struct.pack_into(
            "<I",
            payload,
            constants.INFO_RESPONSE_CAPABILITY_BITS_OFFSET,
            capability_bits & v1_constants.KNOWN_CAPABILITY_MASK,
        )
    elif frame.header.kind is constants.FrameKind.CONFIGURE_REQUEST:
        payload[constants.CONFIGURE_REQUEST_ENCODING_OFFSET] = 0
    elif (
        frame.header.kind
        in {
            constants.FrameKind.CONFIGURE_RESPONSE,
            constants.FrameKind.START_RESPONSE,
        }
        and response_ok
    ):
        payload[constants.CONFIGURE_RESPONSE_ENCODING_OFFSET] = 0

    header = V1FrameHeader(
        kind=v1_constants.FrameKind(int(frame.header.kind)),
        flags=v1_constants.FrameFlag(int(frame.header.flags)),
        checksum_algorithm=v1_constants.ChecksumAlgorithm(
            int(frame.header.checksum_algorithm)
        ),
        total_length=frame.header.total_length,
        payload_length=frame.header.payload_length,
        run_id=frame.header.run_id,
        sequence=frame.header.sequence,
        request_id=frame.header.request_id,
        first_sample_ticks=frame.header.first_sample_ticks,
        item_count=frame.header.item_count,
    )
    return V1Frame(header=header, payload=bytes(payload), checksum=frame.checksum)


def decode_v2_message(
    frame: V2Frame,
    *,
    negotiated_encoding: constants.ConfigurationEncoding | int = (
        constants.ConfigurationEncoding.RAW
    ),
) -> V2DecodedMessage:
    """Decode a v2 frame through the shared typed v1 logical models."""

    try:
        negotiated = constants.ConfigurationEncoding(negotiated_encoding)
    except (TypeError, ValueError) as exc:
        raise ValueError("negotiated encoding must be RAW or RLE_AUTO") from exc
    if frame.header.kind in _DATA_KINDS:
        return decode_v2_data_block(frame, negotiated_encoding=negotiated)

    message = decode_message(_v1_compatible_control_frame(frame))
    if not isinstance(message, CommandResponse) or not message.ok:
        return message
    value = message.value
    if frame.header.kind is constants.FrameKind.INFO_RESPONSE:
        if not isinstance(value, DeviceInfo):  # pragma: no cover - shared invariant
            raise V2FrameValidationError("INFO response omitted typed device info")
        capability_bits = struct.unpack_from(
            "<I",
            frame.payload,
            constants.INFO_RESPONSE_CAPABILITY_BITS_OFFSET,
        )[0]
        advertised = constants.Capability(capability_bits)
        value = replace(
            value,
            protocol_version=constants.PROTOCOL_VERSION,
            capability_bits=advertised,
            configuration_encoding=(
                negotiated
                if advertised & constants.Capability.RLE_STREAMING
                else constants.ConfigurationEncoding.RAW
            ),
        )
    elif frame.header.kind in {
        constants.FrameKind.CONFIGURE_RESPONSE,
        constants.FrameKind.START_RESPONSE,
    }:
        if not isinstance(value, DAQConfiguration):  # pragma: no cover
            raise V2FrameValidationError(
                "configuration response omitted its typed configuration"
            )
        raw_encoding = frame.payload[constants.CONFIGURE_RESPONSE_ENCODING_OFFSET]
        value = replace(
            value,
            encoding=constants.ConfigurationEncoding(raw_encoding),
        )
    return replace(message, value=value)


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

    @property
    def counters(self) -> ParserCounters:
        """Return the stable public parser-counter snapshot type."""

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


__all__ = [
    "MAX_V2_BUFFERED_BYTES",
    "EncodingDiagnostics",
    "IncrementalV2FrameParser",
    "ParserCounters",
    "RawFallbackReason",
    "V2ChecksumMismatchError",
    "V2DataBlock",
    "V2DecodedMessage",
    "V2EncodingNotNegotiatedError",
    "V2Frame",
    "V2FrameHeader",
    "V2FrameValidationError",
    "V2ProtocolError",
    "V2RLEValidationError",
    "V2UnsupportedChecksumError",
    "compute_v2_checksum",
    "count_rle_runs",
    "decode_rle_payload",
    "decode_v2_data_block",
    "decode_v2_frame",
    "decode_v2_message",
    "encode_rle_payload",
    "encode_v2_data_frame",
    "encode_v2_frame",
]
