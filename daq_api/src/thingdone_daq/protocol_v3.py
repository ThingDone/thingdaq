"""Bounded public-v3 framing and lossless sample codecs.

Payloads retain transmitted bytes, while ``decode_v3_block`` supplies ordinary
block views after the session negotiates v3.
"""

from __future__ import annotations

import struct
from collections.abc import Sequence
from dataclasses import dataclass
from typing import TYPE_CHECKING

from ._generated import protocol_constants as v1
from ._generated import protocol_v3_constants as c
from ._incremental import BoundedIncrementalParser, BytesLike
from .checksum import compute_checksum_value
from .protocol import adc_payload_codes_valid

if TYPE_CHECKING:
    from .models import ADCBlock, GPIOBlock
    from .models_v3 import V3Settings

_HEADER = struct.Struct(c.HEADER_STRUCT_FORMAT)
_PREFIX = struct.Struct(c.DATA_PREFIX_STRUCT_FORMAT)
_LOW_NIBBLE = bytes(i & 15 for i in range(256))
_HIGH_NIBBLE = bytes(i >> 4 for i in range(256))
_LOW_NIBBLE_SHIFT = bytes((i & 15) << 4 for i in range(256))
_DATA_KINDS = {c.FrameKind.ADC_DATA, c.FrameKind.GPIO_DATA}
_REQUEST_KINDS = {c.FrameKind(int(kind)) for kind in c.CommandKind}
_RESPONSE_SIZES = {
    c.FrameKind.INFO_RESPONSE: c.INFO_RESPONSE_PAYLOAD_SIZE,
    c.FrameKind.CONFIGURE_RESPONSE: c.SETTINGS_RESPONSE_PAYLOAD_SIZE,
    c.FrameKind.START_RESPONSE: c.SETTINGS_RESPONSE_PAYLOAD_SIZE,
    c.FrameKind.GET_STATUS_RESPONSE: c.STATUS_RESPONSE_PAYLOAD_SIZE,
    c.FrameKind.STOP_RESPONSE: c.STOP_RESPONSE_PAYLOAD_SIZE,
    c.FrameKind.GET_CAPABILITIES_RESPONSE: c.CAPABILITIES_RESPONSE_PAYLOAD_SIZE,
    c.FrameKind.GET_SETTINGS_RESPONSE: c.SETTINGS_RESPONSE_PAYLOAD_SIZE,
    c.FrameKind.ERROR_RESPONSE: c.ERROR_RESPONSE_PAYLOAD_SIZE,
}


class V3FrameValidationError(ValueError):
    """Malformed v3 bytes or contradictory typed fields."""

    def __init__(
        self, message: str, *, error_code: c.ErrorCode = c.ErrorCode.INVALID_PAYLOAD
    ) -> None:
        super().__init__(message)
        self.error_code = error_code


class V3ChecksumMismatchError(V3FrameValidationError):
    """Transmitted header/payload checksum mismatch."""

    def __init__(self, expected: int, observed: int) -> None:
        super().__init__(
            f"checksum mismatch: expected {expected:#010x}, observed {observed:#010x}",
            error_code=c.ErrorCode.CHECKSUM_MISMATCH,
        )
        self.expected = expected
        self.observed = observed


def _require(condition: bool, message: str) -> None:
    if not condition:
        raise V3FrameValidationError(message)


def _bounded_bytes(data: BytesLike, minimum: int, maximum: int) -> bytes:
    # Check byte size before copying, including typed/non-contiguous memoryviews.
    size = memoryview(data).nbytes
    _require(minimum <= size <= maximum, "payload length outside bounds")
    return bytes(data)


def compute_v3_checksum(data: BytesLike) -> int:
    result = compute_checksum_value(data, v1.ChecksumAlgorithm.ADLER32)
    assert result is not None
    return result


@dataclass(frozen=True, slots=True)
class V3FrameHeader:
    kind: c.FrameKind
    flags: c.FrameFlag
    total_length: int
    payload_length: int
    run_id: int
    sequence: int
    request_id: int
    first_sample_ticks: int
    item_count: int
    version: int = c.PROTOCOL_VERSION
    header_length: int = c.HEADER_SIZE
    checksum_algorithm: c.ChecksumAlgorithm = c.ChecksumAlgorithm.ADLER32

    def to_bytes(self) -> bytes:
        try:
            return _HEADER.pack(
                c.MAGIC,
                self.version,
                self.kind,
                self.flags,
                self.header_length,
                self.checksum_algorithm,
                0,
                self.total_length,
                self.payload_length,
                self.run_id,
                self.sequence,
                self.request_id,
                self.first_sample_ticks,
                self.item_count,
            )
        except (struct.error, OverflowError) as exc:
            raise V3FrameValidationError("header scalar outside wire range") from exc


@dataclass(frozen=True, slots=True)
class V3Frame:
    header: V3FrameHeader
    payload: bytes
    checksum: int

    def to_bytes(self) -> bytes:
        return self.header.to_bytes() + self.payload + struct.pack("<I", self.checksum)

    @property
    def payload_view(self) -> memoryview:
        return memoryview(self.payload)


def _decode_v3_header(data: BytesLike, offset: int = 0) -> V3FrameHeader:
    _require(offset >= 0 and len(data) - offset >= c.HEADER_SIZE, "truncated header")
    (
        magic,
        version,
        kind,
        flags,
        size,
        checksum,
        reserved,
        total,
        payload,
        run,
        sequence,
        request,
        ticks,
        count,
    ) = _HEADER.unpack_from(data, offset)
    _require(
        magic == c.MAGIC and version == c.PROTOCOL_VERSION, "invalid magic/version"
    )
    _require(size == c.HEADER_SIZE and reserved == 0, "invalid header size/reserved")
    _require(checksum == c.ChecksumAlgorithm.ADLER32, "unsupported checksum")
    try:
        header = V3FrameHeader(
            c.FrameKind(kind),
            c.FrameFlag(flags),
            total,
            payload,
            run,
            sequence,
            request,
            ticks,
            count,
        )
    except ValueError as exc:
        raise V3FrameValidationError("unknown frame kind") from exc
    _require(total == c.MIN_FRAME_BYTES + payload, "inconsistent frame length")
    if header.kind in _DATA_KINDS:
        _require(
            c.DATA_PREFIX_BYTES
            < payload
            <= c.DATA_PREFIX_BYTES + c.MAX_ENCODED_SAMPLE_BYTES,
            "data payload outside bounds",
        )
        _require(flags & ~15 == 0, "invalid data flags")
        _require(
            not flags & c.FrameFlag.OVERRUN_BEFORE
            or bool(flags & c.FrameFlag.GAP_BEFORE),
            "OVERRUN_BEFORE requires GAP_BEFORE",
        )
        _require(run != 0 and request == 0, "invalid data run/request ID")
        maximum = (
            c.MAX_ADC_PAIRS
            if header.kind == c.FrameKind.ADC_DATA
            else c.MAX_GPIO8_SAMPLES
        )
        _require(1 <= count <= maximum, "logical item count outside bounds")
        _require(ticks % c.ADC_PAIR_PERIOD_TICKS == 0, "unaligned timestamp")
        _require(
            ticks + count * c.ADC_PAIR_PERIOD_TICKS <= (1 << 64) - 1,
            "timestamp range would wrap within run",
        )
    else:
        _require(total <= c.MAX_CONTROL_FRAME_BYTES, "control frame outside bounds")
        _require(sequence == ticks == count == 0, "nonzero data-only control fields")
        if header.kind in _REQUEST_KINDS:
            _require(flags == 0 and run == 0 and request != 0, "invalid request fields")
            expected = (
                c.SETTINGS_PAYLOAD_SIZE
                if header.kind == c.FrameKind.CONFIGURE_REQUEST
                else 0
            )
        else:
            _require(
                flags & ~int(c.FrameFlag.RESPONSE_ERROR) == 0, "invalid response flags"
            )
            is_error = bool(flags & c.FrameFlag.RESPONSE_ERROR)
            _require(request != 0 or is_error, "zero request ID requires an error")
            if header.kind == c.FrameKind.ERROR_RESPONSE:
                _require(is_error, "generic response requires an error")
                expected = c.ERROR_RESPONSE_PAYLOAD_SIZE
            else:
                expected = (
                    c.RESPONSE_PREFIX_PAYLOAD_SIZE
                    if is_error
                    else _RESPONSE_SIZES[header.kind]
                )
            if header.kind == c.FrameKind.START_RESPONSE and not is_error:
                _require(run != 0, "START requires a nonzero run ID")
        _require(payload == expected, "incorrect control payload size")
    return header


@dataclass(frozen=True, slots=True)
class V3DecodedData:
    encoding: c.Encoding
    item_bytes: int
    item_count: int
    payload: bytes
    encoded_sample_bytes: int

    @property
    def decoded_bytes(self) -> int:
        return len(self.payload)


def decode_data_payload(
    kind: c.FrameKind | int,
    payload: BytesLike,
    item_count: int,
) -> V3DecodedData:
    """Validate all lengths/records before allocating an expanded sample buffer."""
    data = _bounded_bytes(
        payload, c.DATA_PREFIX_BYTES, c.DATA_PREFIX_BYTES + c.MAX_ENCODED_SAMPLE_BYTES
    )
    encoding, width, reserved, decoded, runs = _PREFIX.unpack_from(data)
    _require(kind in _DATA_KINDS, "encoding requires a data kind")
    _require(reserved == 0, "nonzero data prefix reserved field")
    _require(
        width == 4 if kind == c.FrameKind.ADC_DATA else width in (1, 2),
        "illegal item width for data kind",
    )
    _require(
        isinstance(item_count, int)
        and not isinstance(item_count, bool)
        and 1 <= item_count <= c.MAX_LOGICAL_PAYLOAD_BYTES // width,
        "logical item count outside bounds",
    )
    _require(decoded == item_count * width, "decoded byte count mismatch")
    samples = data[c.DATA_PREFIX_BYTES :]
    if encoding == c.Encoding.RAW:
        _require(runs == 0 and len(samples) == decoded, "invalid RAW length/run count")
        if kind == c.FrameKind.ADC_DATA:
            _require(adc_payload_codes_valid(samples), "ADC code outside 0..4095")
        raw = samples
    elif encoding == c.Encoding.ADC_PACK12:
        _require(
            kind == c.FrameKind.ADC_DATA and runs == 0, "illegal PACK12 kind/run count"
        )
        _require(len(samples) == 3 * item_count, "truncated or excess PACK12 samples")
        expanded = bytearray(decoded)
        # Reuse the rig decoder's bounded byte lanes. Disjoint nibbles cannot
        # carry between samples; bulk operations avoid a Python loop per pair.
        middle, high = samples[1::3], samples[2::3]
        expanded[0::4] = samples[0::3]
        expanded[1::4] = middle.translate(_LOW_NIBBLE)
        expanded[2::4] = (
            int.from_bytes(middle.translate(_HIGH_NIBBLE), "little")
            | int.from_bytes(high.translate(_LOW_NIBBLE_SHIFT), "little")
        ).to_bytes(item_count, "little")
        expanded[3::4] = high.translate(_HIGH_NIBBLE)
        raw = bytes(expanded)
    elif encoding == c.Encoding.GPIO_RLE:
        _require(kind == c.FrameKind.GPIO_DATA, "RLE requires GPIO")
        _require(
            1 <= runs <= item_count and len(samples) == runs * (2 + width),
            "invalid RLE record count/length",
        )
        _require(len(samples) < decoded, "RLE must be strictly smaller than RAW")
        fmt = (
            c.GPIO8_RLE_RECORD_STRUCT_FORMAT
            if width == 1
            else c.GPIO16_RLE_RECORD_STRUCT_FORMAT
        )
        total = 0
        previous = None
        for length, value in struct.iter_unpack(fmt, samples):
            _require(
                length > 0 and total + length <= item_count, "zero/overflow RLE run"
            )
            _require(value != previous, "adjacent RLE runs must differ")
            total += length
            previous = value
        _require(total == item_count, "RLE runs do not cover exact logical count")
        expanded = bytearray()
        for length, value in struct.iter_unpack(fmt, samples):
            expanded.extend(value.to_bytes(width, "little") * length)
        raw = bytes(expanded)
    else:
        raise V3FrameValidationError("unknown data encoding")
    return V3DecodedData(c.Encoding(encoding), width, item_count, raw, len(samples))


def encode_adc_payload(
    pairs: Sequence[tuple[int, int]],
    *,
    policy: c.AdcPolicy = c.AdcPolicy.PACK12,
) -> bytes:
    _require(1 <= len(pairs) <= c.MAX_ADC_PAIRS, "ADC pair count outside bounds")
    _require(policy in tuple(c.AdcPolicy), "unknown ADC policy")
    samples = bytearray()
    for a, b in pairs:
        _require(
            all(
                isinstance(value, int)
                and not isinstance(value, bool)
                and 0 <= value <= 4095
                for value in (a, b)
            ),
            "ADC code outside 0..4095",
        )
        if policy == c.AdcPolicy.PACK12:
            samples.extend((a & 255, (a >> 8) | ((b & 15) << 4), b >> 4))
        else:
            samples.extend(struct.pack(c.ADC_RAW_PAIR_STRUCT_FORMAT, a, b))
    encoding = c.Encoding.ADC_PACK12 if policy == c.AdcPolicy.PACK12 else c.Encoding.RAW
    return _PREFIX.pack(encoding, 4, 0, 4 * len(pairs), 0) + samples


def encode_gpio_payload(
    values: Sequence[int],
    *,
    width_bits: int = 8,
    policy: c.GpioPolicy = c.GpioPolicy.RLE_AUTO,
) -> bytes:
    _require(width_bits in (8, 16), "GPIO width must be 8 or 16")
    width = width_bits // 8
    _require(
        1 <= len(values) <= c.MAX_LOGICAL_PAYLOAD_BYTES // width,
        "GPIO count outside bounds",
    )
    _require(policy in tuple(c.GpioPolicy), "unknown GPIO policy")
    raw = bytearray()
    rle = bytearray()
    previous = None
    length = runs = 0
    for value in values:
        _require(
            isinstance(value, int)
            and not isinstance(value, bool)
            and 0 <= value < 1 << width_bits,
            "GPIO sample outside width",
        )
        raw.extend(value.to_bytes(width, "little"))
        if value == previous:
            length += 1
        else:
            if previous is not None:
                rle.extend(
                    length.to_bytes(2, "little") + previous.to_bytes(width, "little")
                )
                runs += 1
            previous, length = value, 1
    assert previous is not None
    rle.extend(length.to_bytes(2, "little") + previous.to_bytes(width, "little"))
    runs += 1
    if policy == c.GpioPolicy.RLE_AUTO and len(rle) < len(raw):
        return _PREFIX.pack(c.Encoding.GPIO_RLE, width, 0, len(raw), runs) + rle
    return _PREFIX.pack(c.Encoding.RAW, width, 0, len(raw), 0) + raw


def _validate_payload(frame: V3Frame) -> None:
    from .models_v3 import V3Settings, decode_v3_response

    if frame.header.kind in _DATA_KINDS:
        decode_data_payload(frame.header.kind, frame.payload, frame.header.item_count)
    elif frame.header.kind == c.FrameKind.CONFIGURE_REQUEST:
        V3Settings.from_bytes(frame.payload)
    elif frame.header.kind not in _REQUEST_KINDS:
        decode_v3_response(frame)


def _decode_buffered_v3_frame(
    data: BytesLike, offset: int, header: V3FrameHeader
) -> V3Frame:
    end = offset + header.total_length - c.TRAILER_SIZE
    with memoryview(data) as view:
        expected = compute_v3_checksum(view[offset:end])
        observed = struct.unpack_from("<I", data, end)[0]
        if expected != observed:
            raise V3ChecksumMismatchError(expected, observed)
        frame = V3Frame(header, bytes(view[offset + c.HEADER_SIZE : end]), observed)
    _validate_payload(frame)
    return frame


def decode_v3_frame(data: BytesLike) -> V3Frame:
    wire = _bounded_bytes(data, c.MIN_FRAME_BYTES, c.MAX_DATA_FRAME_BYTES)
    header = _decode_v3_header(wire)
    _require(len(wire) == header.total_length, "truncated or trailing frame bytes")
    return _decode_buffered_v3_frame(wire, 0, header)


def encode_v3_frame(
    kind: c.FrameKind | int,
    payload: BytesLike = b"",
    *,
    flags: c.FrameFlag | int = 0,
    run_id: int = 0,
    sequence: int = 0,
    request_id: int = 0,
    first_sample_ticks: int = 0,
    item_count: int = 0,
) -> bytes:
    data = _bounded_bytes(payload, 0, c.DATA_PREFIX_BYTES + c.MAX_ENCODED_SAMPLE_BYTES)
    try:
        header = V3FrameHeader(
            c.FrameKind(kind),
            c.FrameFlag(flags),
            c.MIN_FRAME_BYTES + len(data),
            len(data),
            run_id,
            sequence,
            request_id,
            first_sample_ticks,
            item_count,
        )
    except ValueError as exc:
        raise V3FrameValidationError("unknown frame kind/flags") from exc
    header = _decode_v3_header(header.to_bytes())
    _validate_payload(V3Frame(header, data, 0))
    wire = header.to_bytes() + data
    return wire + struct.pack("<I", compute_v3_checksum(wire))


class V3FrameParser(BoundedIncrementalParser[V3FrameHeader, V3Frame]):
    """Opt-in v3 parser sharing the bounded scanner and corruption counters."""

    def __init__(self) -> None:
        super().__init__(
            magic_bytes=c.MAGIC.to_bytes(4, "little"),
            header_size=c.HEADER_SIZE,
            max_frame_bytes=c.MAX_DATA_FRAME_BYTES,
            decode_header=_decode_v3_header,
            decode_frame=_decode_buffered_v3_frame,
            validation_error=V3FrameValidationError,
            checksum_error=V3ChecksumMismatchError,
        )


def decode_v3_block(frame: V3Frame, settings: V3Settings) -> ADCBlock | GPIOBlock:
    """Decode with the negotiated policies, preserving existing channel views."""
    from .models import ADCBlock, AdcBlockMetadata, AuxBankMode, GPIOBlock, RateProfile

    header = frame.header
    # Also validate callers constructing V3Frame directly.
    frame = decode_v3_frame(frame.to_bytes())
    data = decode_data_payload(header.kind, frame.payload, header.item_count)
    settings.to_bytes()
    is_adc = header.kind == c.FrameKind.ADC_DATA
    stream = c.StreamMask.ADC if is_adc else c.StreamMask.GPIO
    _require(bool(settings.stream_mask & stream), "data for a disabled stream")
    _require(
        bool(header.flags & c.FrameFlag.SYNTHETIC)
        == (settings.source == c.Source.SYNTHETIC),
        "data source differs from settings",
    )
    if is_adc:
        expected = (
            c.Encoding.ADC_PACK12
            if settings.adc_policy == c.AdcPolicy.PACK12
            else c.Encoding.RAW
        )
        _require(data.encoding == expected, "ADC encoding differs from policy")
        return ADCBlock(
            run_id=header.run_id,
            sequence=header.sequence,
            first_sample_ticks=header.first_sample_ticks,
            payload=data.payload,
            flags=v1.FrameFlag(header.flags),
            checksum_algorithm=v1.ChecksumAlgorithm.ADLER32,
            metadata=AdcBlockMetadata.for_rate_profile(
                RateProfile(settings.rate_profile), v1.Source(settings.source)
            ),
            aux_bank_mode=AuxBankMode(settings.aux_bank_mode),
            rate_profile=RateProfile(settings.rate_profile),
            protocol_version=c.PROTOCOL_VERSION,
            encoded_payload=frame.payload,
        )
    _require(
        data.item_bytes * 8 == settings.gpio_width_bits,
        "GPIO width differs from settings",
    )
    _require(
        settings.gpio_policy == c.GpioPolicy.RLE_AUTO
        or data.encoding == c.Encoding.RAW,
        "GPIO encoding differs from policy",
    )
    return GPIOBlock(
        run_id=header.run_id,
        sequence=header.sequence,
        first_sample_ticks=header.first_sample_ticks,
        payload=data.payload,
        flags=v1.FrameFlag(header.flags),
        checksum_algorithm=v1.ChecksumAlgorithm.ADLER32,
        aux_bank_mode=AuxBankMode(settings.aux_bank_mode),
        rate_profile=RateProfile(settings.rate_profile),
        protocol_version=c.PROTOCOL_VERSION,
        encoded_payload=frame.payload,
    )
