"""Protocol-v2 envelope, temperature codec and bounded compatible parser.

Firmware 1.1.0 enables the fixed 1 MHz profile at 450 MHz. Historical profile
definitions remain decodable; only the device's INFO mask grants support.
"""

from __future__ import annotations

import struct
from dataclasses import dataclass

from ._generated import protocol_constants as v1_constants
from ._generated import protocol_v2_constants as constants
from ._incremental import BoundedIncrementalParser, BytesLike, ParserCounters
from .checksum import HOST_SUPPORTED_CHECKSUM_ALGORITHMS, compute_checksum_value
from .protocol import (
    ChecksumMismatchError as V1ChecksumMismatchError,
)
from .protocol import (
    Frame as V1Frame,
)
from .protocol import (
    FrameHeader as V1FrameHeader,
)
from .protocol import (
    FrameValidationError as V1FrameValidationError,
)
from .protocol import (
    _decode_buffered_frame as _decode_buffered_v1_frame,
)
from .protocol import (
    _decode_header as _decode_v1_header,
)
from .protocol import (
    _validate_checksum_benchmark_response,
    _validate_gpio_clock_diagnostic_response,
    adc_payload_codes_valid,
)
from .protocol import (
    decode_frame as decode_v1_frame,
)
from .protocol import (
    encode_frame as encode_v1_frame,
)

_HEADER = struct.Struct(constants.HEADER_STRUCT_FORMAT)
_TRAILER = struct.Struct("<I")
_CONFIGURE_REQUEST = struct.Struct("<BBBBIII")
_CONFIGURE_RESPONSE = struct.Struct("<BBHBBBBIII")
_RESPONSE_PREFIX = struct.Struct("<BBH")
_DATA_KINDS = frozenset({constants.FrameKind.ADC_DATA, constants.FrameKind.GPIO_DATA})
_REQUEST_KINDS = frozenset(constants.REQUEST_RESPONSE_KIND)
_TYPED_RESPONSE_KINDS = frozenset(constants.REQUEST_RESPONSE_KIND.values())
_DATA_SHAPES_BY_KIND = {
    constants.FrameKind.ADC_DATA: frozenset(
        (
            int(layout["adc_total_frame_bytes"]),
            int(layout["adc_payload_bytes"]),
            int(layout["adc_items_per_frame"]),
        )
        for layout in constants.AUX_BANK_LAYOUTS.values()
    ),
    constants.FrameKind.GPIO_DATA: frozenset(
        (
            int(layout["gpio_total_frame_bytes"]),
            int(layout["gpio_payload_bytes"]),
            int(layout["gpio_items_per_frame"]),
        )
        for layout in constants.AUX_BANK_LAYOUTS.values()
    ),
}
_DATA_PERIODS_BY_KIND = {
    constants.FrameKind.ADC_DATA: tuple(
        int(profile["adc_pair_period_ticks"])
        for profile in constants.RATE_PROFILE_TIMING.values()
    ),
    constants.FrameKind.GPIO_DATA: tuple(
        int(profile["gpio_sample_period_ticks"])
        for profile in constants.RATE_PROFILE_TIMING.values()
    ),
}
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


class V2ConfigurationEchoError(V2FrameValidationError):
    """A successful CONFIGURE/START body contradicts its correlated request."""

    def __init__(self) -> None:
        super().__init__(
            "successful applied configuration differs from the request",
            reason="contradictory_configure_echo",
            error_code=constants.ErrorCode.UNSUPPORTED_CONFIGURATION,
        )


@dataclass(frozen=True, slots=True)
class V2ConfigurationFields:
    """Validated low-level fields in one extended configuration body."""

    stream_mask: constants.StreamMask
    source: constants.Source
    data_checksum_algorithm: constants.ChecksumAlgorithm
    aux_bank_mode: constants.AuxBankMode
    data_frame_bytes: int
    adc_pair_rate_hz: int
    gpio_sample_rate_hz: int
    rate_profile: constants.RateProfile


@dataclass(frozen=True, slots=True)
class V2FrameHeader:
    """Decoded protocol-v2 header fields."""

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
class V2Frame:
    """A validated v2 frame retaining its bounded transmitted payload."""

    header: V2FrameHeader
    payload: bytes
    checksum: int

    def to_bytes(self) -> bytes:
        """Return the exact encoded wire representation."""

        return self.header.to_bytes() + self.payload + _TRAILER.pack(self.checksum)

    @property
    def payload_view(self) -> memoryview:
        """Return a zero-copy read-only view over the owned payload bytes."""

        return memoryview(self.payload)


CompatibleFrame = V1Frame | V2Frame
CompatibleFrameHeader = V1FrameHeader | V2FrameHeader


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
    if reserved != 0:
        raise V2FrameValidationError("protocol-v2 header reserved byte must be zero")

    header = V2FrameHeader(
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
        observed_shape = (
            header.total_length,
            header.payload_length,
            header.item_count,
        )
        if observed_shape not in _DATA_SHAPES_BY_KIND[header.kind]:
            raise V2FrameValidationError(
                f"{header.kind.name} has no declared auxiliary-mode layout",
                reason="invalid_length",
                error_code=constants.ErrorCode.INVALID_LENGTH,
            )
        if header.run_id == 0 or header.request_id != 0:
            raise V2FrameValidationError(
                "data frames require a nonzero run ID and zero request ID"
            )
        if not any(
            header.first_sample_ticks % period == 0
            for period in _DATA_PERIODS_BY_KIND[header.kind]
        ):
            raise V2FrameValidationError(
                "data timestamp is not aligned to any declared rate profile"
            )
        epoch_start = bool(header.flags & constants.FrameFlag.EPOCH_START)
        first_in_epoch = header.sequence == 0 and header.first_sample_ticks == 0
        if epoch_start != first_in_epoch:
            raise V2FrameValidationError(
                "EPOCH_START must identify sequence zero at timestamp zero"
            )
        return

    if (
        not constants.MIN_FRAME_BYTES
        <= header.total_length
        <= (constants.MAX_CONTROL_FRAME_BYTES)
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


def _validate_response_prefix(header: V2FrameHeader, payload: bytes) -> None:
    raw_status, reserved, raw_error = _RESPONSE_PREFIX.unpack_from(payload)
    if reserved != 0:
        raise V2FrameValidationError("response reserved byte must be zero")
    try:
        status = constants.ResponseStatus(raw_status)
        error = constants.ErrorCode(raw_error)
    except ValueError as exc:
        raise V2FrameValidationError("unknown response status or error code") from exc
    response_error = bool(header.flags & constants.FrameFlag.RESPONSE_ERROR)
    if response_error != (status is constants.ResponseStatus.ERROR):
        raise V2FrameValidationError("response flag and status disagree")
    if (status is constants.ResponseStatus.OK) != (error is constants.ErrorCode.OK):
        raise V2FrameValidationError("response status and error code disagree")


def _rate_profile_for_pair(adc_rate: int, gpio_rate: int) -> constants.RateProfile:
    if (
        adc_rate <= 0
        or gpio_rate <= 0
        or constants.TIMESTAMP_HZ % adc_rate
        or constants.TIMESTAMP_HZ % gpio_rate
    ):
        raise V2FrameValidationError(
            "ADC and GPIO rates must divide the timestamp clock exactly",
            reason="nonintegral_timestamps",
            error_code=constants.ErrorCode.UNSUPPORTED_CONFIGURATION,
        )
    if gpio_rate != 4 * adc_rate and (adc_rate, gpio_rate) != (1_000_000, 1_000_000):
        raise V2FrameValidationError(
            "rates must match a declared acquisition profile",
            reason="wrong_four_to_one_ratio",
            error_code=constants.ErrorCode.UNSUPPORTED_CONFIGURATION,
        )
    for profile, timing in constants.RATE_PROFILE_TIMING.items():
        if (
            int(timing["adc_pair_rate_hz"]) == adc_rate
            and int(timing["gpio_sample_rate_hz"]) == gpio_rate
        ):
            return profile
    raise V2FrameValidationError(
        "rate pair is not one of the declared exact profiles",
        reason="unsupported_rates",
        error_code=constants.ErrorCode.UNSUPPORTED_CONFIGURATION,
    )


def decode_v2_configuration(
    payload: BytesLike,
    *,
    response: bool = False,
) -> V2ConfigurationFields:
    """Decode and validate one request or successful applied-echo body."""

    payload_bytes = bytes(payload)
    expected_size = (
        constants.CONFIGURE_RESPONSE_PAYLOAD_SIZE
        if response
        else constants.CONFIGURE_REQUEST_PAYLOAD_SIZE
    )
    if len(payload_bytes) != expected_size:
        raise V2FrameValidationError(
            f"extended configuration body must be {expected_size} bytes",
            reason="invalid_length",
            error_code=constants.ErrorCode.INVALID_LENGTH,
        )
    if response:
        (
            raw_status,
            reserved,
            raw_error,
            raw_streams,
            raw_source,
            raw_checksum,
            raw_mode,
            frame_bytes,
            adc_rate,
            gpio_rate,
        ) = _CONFIGURE_RESPONSE.unpack(payload_bytes)
        if (
            raw_status != constants.ResponseStatus.OK
            or reserved != 0
            or raw_error != constants.ErrorCode.OK
        ):
            raise V2FrameValidationError(
                "successful applied configuration prefix is inconsistent"
            )
    else:
        (
            raw_streams,
            raw_source,
            raw_checksum,
            raw_mode,
            frame_bytes,
            adc_rate,
            gpio_rate,
        ) = _CONFIGURE_REQUEST.unpack(payload_bytes)
    valid_stream_bits = int(constants.StreamMask.ADC | constants.StreamMask.GPIO)
    if raw_streams & ~valid_stream_bits:
        raise V2FrameValidationError("configuration stream mask is invalid")
    try:
        streams = constants.StreamMask(raw_streams)
        source = constants.Source(raw_source)
        checksum = constants.ChecksumAlgorithm(raw_checksum)
        mode = constants.AuxBankMode(raw_mode)
    except ValueError as exc:
        raise V2FrameValidationError(
            "configuration contains an unknown enum value",
            reason="invalid_aux_bank_mode"
            if raw_mode not in (0, 1)
            else "invalid_enum",
        ) from exc
    if streams == constants.StreamMask.NONE and source is not constants.Source.HARDWARE:
        raise V2FrameValidationError(
            "zero-stream configuration requires the hardware source"
        )
    if checksum is constants.ChecksumAlgorithm.NONE_RESERVED:
        raise V2FrameValidationError("configuration cannot select checksum ID zero")
    _v1_checksum_algorithm(checksum)
    if frame_bytes != constants.DATA_FRAME_BYTES:
        raise V2FrameValidationError("configuration maximum frame size must be 4096")
    profile = _rate_profile_for_pair(adc_rate, gpio_rate)
    return V2ConfigurationFields(
        stream_mask=streams,
        source=source,
        data_checksum_algorithm=checksum,
        aux_bank_mode=mode,
        data_frame_bytes=frame_bytes,
        adc_pair_rate_hz=adc_rate,
        gpio_sample_rate_hz=gpio_rate,
        rate_profile=profile,
    )


def validate_v2_configuration_echo(
    request_payload: BytesLike,
    response_payload: BytesLike,
) -> V2ConfigurationFields:
    """Require a successful CONFIGURE/START echo to equal its request exactly."""

    requested = decode_v2_configuration(request_payload)
    applied = decode_v2_configuration(response_payload, response=True)
    if applied != requested:
        raise V2ConfigurationEchoError()
    return applied


def select_protocol_version(
    *,
    aux_bank_mode: constants.AuxBankMode | int = constants.DEFAULT_AUX_BANK_MODE,
    adc_pair_rate_hz: int = constants.ADC_PAIR_RATE_HZ,
    gpio_sample_rate_hz: int = constants.GPIO_SAMPLE_RATE_HZ,
) -> int:
    """Select v1 for the exact default and v2 only for an explicit extension."""

    if isinstance(aux_bank_mode, bool):
        raise TypeError("auxiliary bank mode must be DISABLED or INPUT")
    try:
        mode = constants.AuxBankMode(aux_bank_mode)
    except (TypeError, ValueError) as exc:
        raise ValueError("auxiliary bank mode must be DISABLED or INPUT") from exc
    _rate_profile_for_pair(adc_pair_rate_hz, gpio_sample_rate_hz)
    if (
        mode is constants.AuxBankMode.DISABLED
        and adc_pair_rate_hz == constants.ADC_PAIR_RATE_HZ
        and gpio_sample_rate_hz == constants.GPIO_SAMPLE_RATE_HZ
    ):
        return v1_constants.PROTOCOL_VERSION
    return constants.PROTOCOL_VERSION


def _u16(payload: bytes, offset: int) -> int:
    return int(struct.unpack_from("<H", payload, offset)[0])


def _u32(payload: bytes, offset: int) -> int:
    return int(struct.unpack_from("<I", payload, offset)[0])


def _validate_info_profile_table(payload: bytes) -> None:
    cpu_hz = _u32(payload, constants.INFO_RESPONSE_ADC_TRIGGER_DWT_CLOCK_HZ_OFFSET)
    if cpu_hz not in (450_000_000, 600_000_000):
        raise V2FrameValidationError("INFO core clock is unsupported")
    base = constants.INFO_RESPONSE_RATE_PROFILES_OFFSET
    size = constants.RATE_PROFILE_INFO_PAYLOAD_SIZE
    scalar_fields = {
        "adc_pair_rate_hz": ("I", constants.RATE_PROFILE_INFO_ADC_PAIR_RATE_HZ_OFFSET),
        "gpio_sample_rate_hz": (
            "I",
            constants.RATE_PROFILE_INFO_GPIO_SAMPLE_RATE_HZ_OFFSET,
        ),
        "adc_pair_period_ticks": (
            "H",
            constants.RATE_PROFILE_INFO_ADC_PAIR_PERIOD_TICKS_OFFSET,
        ),
        "adc1_phase_ticks": ("H", constants.RATE_PROFILE_INFO_ADC1_PHASE_TICKS_OFFSET),
        "gpio_sample_period_ticks": (
            "H",
            constants.RATE_PROFILE_INFO_GPIO_SAMPLE_PERIOD_TICKS_OFFSET,
        ),
        "gpio_master_pit_divider": (
            "H",
            constants.RATE_PROFILE_INFO_GPIO_MASTER_PIT_DIVIDER_OFFSET,
        ),
        "gpio_master_pit_load": (
            "H",
            constants.RATE_PROFILE_INFO_GPIO_MASTER_PIT_LOAD_OFFSET,
        ),
        "adc_pair_pit_divider": (
            "H",
            constants.RATE_PROFILE_INFO_ADC_PAIR_PIT_DIVIDER_OFFSET,
        ),
        "adc_pair_pit_load": (
            "H",
            constants.RATE_PROFILE_INFO_ADC_PAIR_PIT_LOAD_OFFSET,
        ),
        "adc_etc_predivider": (
            "B",
            constants.RATE_PROFILE_INFO_ADC_ETC_PREDIVIDER_OFFSET,
        ),
        "adc_etc_chain_length": (
            "B",
            constants.RATE_PROFILE_INFO_ADC_ETC_CHAIN_LENGTH_OFFSET,
        ),
        "adc0_initial_delay": (
            "H",
            constants.RATE_PROFILE_INFO_ADC0_INITIAL_DELAY_OFFSET,
        ),
        "adc1_initial_delay": (
            "H",
            constants.RATE_PROFILE_INFO_ADC1_INITIAL_DELAY_OFFSET,
        ),
        "adc0_effective_delay": (
            "H",
            constants.RATE_PROFILE_INFO_ADC0_EFFECTIVE_DELAY_OFFSET,
        ),
        "adc1_effective_delay": (
            "H",
            constants.RATE_PROFILE_INFO_ADC1_EFFECTIVE_DELAY_OFFSET,
        ),
        "adc1_phase_ipg_cycles": (
            "H",
            constants.RATE_PROFILE_INFO_ADC1_PHASE_IPG_CYCLES_OFFSET,
        ),
        "completion_expected_dwt_cycles": (
            "I",
            constants.RATE_PROFILE_INFO_COMPLETION_EXPECTED_DWT_CYCLES_OFFSET,
        ),
        "disabled_frame_coverage_ticks": (
            "I",
            constants.RATE_PROFILE_INFO_DISABLED_FRAME_COVERAGE_TICKS_OFFSET,
        ),
        "input_frame_coverage_ticks": (
            "I",
            constants.RATE_PROFILE_INFO_INPUT_FRAME_COVERAGE_TICKS_OFFSET,
        ),
    }
    for index, profile in enumerate(constants.RateProfile):
        offset = base + index * size
        if payload[offset + constants.RATE_PROFILE_INFO_RESERVED_OFFSET] != 0:
            raise V2FrameValidationError("INFO rate-profile reserved byte must be zero")
        if payload[offset + constants.RATE_PROFILE_INFO_RATE_PROFILE_OFFSET] != int(
            profile
        ):
            raise V2FrameValidationError("INFO rate-profile table order is invalid")
        expected = constants.RATE_PROFILE_TIMING[profile]
        for name, (field_format, field_offset) in scalar_fields.items():
            observed = struct.unpack_from(
                "<" + field_format, payload, offset + field_offset
            )[0]
            expected_value = int(expected[name])
            if name == "completion_expected_dwt_cycles":
                expected_value = cpu_hz // (2 * int(expected["adc_pair_rate_hz"]))
            if int(observed) != expected_value:
                raise V2FrameValidationError(
                    f"INFO rate-profile {profile.name} {name} is contradictory",
                    reason="invalid_rate_profile_metadata",
                )


def _validate_info_payload(payload: bytes) -> None:
    if payload[constants.INFO_RESPONSE_RESERVED_0_OFFSET] != 0:
        raise V2FrameValidationError("INFO reserved_0 must be zero")
    for offset in (
        constants.INFO_RESPONSE_RESERVED_2_OFFSET,
        constants.INFO_RESPONSE_RESERVED_4_OFFSET,
        constants.INFO_RESPONSE_RESERVED_9_OFFSET,
        constants.INFO_RESPONSE_RESERVED_10_OFFSET,
        constants.INFO_RESPONSE_RESERVED_11_OFFSET,
    ):
        if payload[offset] != 0:
            raise V2FrameValidationError("INFO reserved byte must be zero")
    for offset in (
        constants.INFO_RESPONSE_RESERVED_3_OFFSET,
        constants.INFO_RESPONSE_RESERVED_5_OFFSET,
        constants.INFO_RESPONSE_RESERVED_6_OFFSET,
        constants.INFO_RESPONSE_RESERVED_7_OFFSET,
        constants.INFO_RESPONSE_RESERVED_8_OFFSET,
    ):
        if _u16(payload, offset) != 0:
            raise V2FrameValidationError("INFO reserved word must be zero")
    if payload[constants.INFO_RESPONSE_PROTOCOL_VERSION_OFFSET] != (
        constants.PROTOCOL_VERSION
    ):
        raise V2FrameValidationError("INFO protocol version echo is contradictory")
    fixed_u32 = {
        constants.INFO_RESPONSE_TIMESTAMP_HZ_OFFSET: constants.TIMESTAMP_HZ,
        constants.INFO_RESPONSE_DATA_FRAME_BYTES_OFFSET: constants.DATA_FRAME_BYTES,
        constants.INFO_RESPONSE_MAX_CONTROL_FRAME_BYTES_OFFSET: (
            constants.MAX_CONTROL_FRAME_BYTES
        ),
        constants.INFO_RESPONSE_AUX_GPIO_CAPTURE_MASK_OFFSET: (
            constants.AUX_GPIO_CAPTURE_MASK
        ),
        constants.INFO_RESPONSE_PRIMARY_GPIO_CAPTURE_MASK_OFFSET: (
            constants.PRIMARY_GPIO_CAPTURE_MASK
        ),
    }
    for offset, expected in fixed_u32.items():
        if _u32(payload, offset) != int(expected):
            raise V2FrameValidationError("INFO fixed timing/resource field is invalid")
    capability_bits = _u32(payload, constants.INFO_RESPONSE_CAPABILITY_BITS_OFFSET)
    required_capabilities = int(
        constants.Capability.AUXILIARY_INPUT_BANK
        | constants.Capability.EXACT_RATE_PROFILES
    )
    if capability_bits & ~constants.KNOWN_CAPABILITY_MASK:
        raise V2FrameValidationError("INFO contains unknown capability bits")
    if capability_bits & required_capabilities != required_capabilities:
        raise V2FrameValidationError("INFO omits required auxiliary capabilities")
    rate_mask = payload[constants.INFO_RESPONSE_SUPPORTED_RATE_PROFILE_MASK_OFFSET]
    if not rate_mask or rate_mask & ~constants.SUPPORTED_RATE_PROFILE_MASK:
        raise V2FrameValidationError("INFO supported rate-profile mask is invalid")
    if payload[constants.INFO_RESPONSE_SUPPORTED_AUX_BANK_MODE_MASK_OFFSET] != (
        constants.SUPPORTED_AUX_BANK_MODE_MASK
    ):
        raise V2FrameValidationError("INFO supported auxiliary-mode mask is invalid")
    if payload[constants.INFO_RESPONSE_RATE_PROFILE_COUNT_OFFSET] != len(
        constants.RateProfile
    ):
        raise V2FrameValidationError("INFO rate-profile count is invalid")
    try:
        profile = constants.RateProfile(
            payload[constants.INFO_RESPONSE_SELECTED_RATE_PROFILE_OFFSET]
        )
        mode = constants.AuxBankMode(
            payload[constants.INFO_RESPONSE_APPLIED_AUX_BANK_MODE_OFFSET]
        )
    except ValueError as exc:
        raise V2FrameValidationError("INFO contains an unknown mode/profile") from exc
    if not rate_mask & (1 << int(profile)):
        raise V2FrameValidationError("INFO selected rate is not supported")

    primary_start = constants.INFO_RESPONSE_GPIO_PIN_MAP_OFFSET
    primary_end = primary_start + constants.INFO_RESPONSE_GPIO_PIN_MAP_COUNT
    auxiliary_start = constants.INFO_RESPONSE_AUX_GPIO_PIN_MAP_OFFSET
    auxiliary_end = auxiliary_start + constants.INFO_RESPONSE_AUX_GPIO_PIN_MAP_COUNT
    primary_pins = tuple(payload[primary_start:primary_end])
    auxiliary_pins = tuple(payload[auxiliary_start:auxiliary_end])
    if primary_pins != constants.PRIMARY_GPIO_PINS_BY_BIT:
        raise V2FrameValidationError("INFO primary GPIO pin map is invalid")
    if auxiliary_pins != constants.AUX_GPIO_PINS_BY_BIT:
        raise V2FrameValidationError(
            "INFO auxiliary GPIO pin map is invalid",
            reason="duplicate_or_invalid_pins",
        )
    if len({*primary_pins, *auxiliary_pins}) != len(primary_pins) + len(auxiliary_pins):
        raise V2FrameValidationError(
            "INFO GPIO pin maps contain duplicates",
            reason="duplicate_or_invalid_pins",
        )
    if payload[constants.INFO_RESPONSE_GPIO_PIN_COUNT_OFFSET] != len(primary_pins) or (
        payload[constants.INFO_RESPONSE_AUX_GPIO_PIN_COUNT_OFFSET]
        != len(auxiliary_pins)
    ):
        raise V2FrameValidationError("INFO GPIO pin counts are invalid")

    layout = constants.AUX_BANK_LAYOUTS[mode]
    active_u8 = {
        constants.INFO_RESPONSE_GPIO_PACKED_WIDTH_BITS_OFFSET: layout[
            "gpio_width_bits"
        ],
        constants.INFO_RESPONSE_GPIO_ITEM_BYTES_OFFSET: layout["gpio_bytes_per_item"],
    }
    for offset, expected in active_u8.items():
        if payload[offset] != int(expected):
            raise V2FrameValidationError(
                "INFO GPIO width/item-size echo is contradictory",
                reason="bad_gpio_width",
            )
    timing = constants.RATE_PROFILE_TIMING[profile]
    active_u32 = {
        constants.INFO_RESPONSE_ADC_PAIR_RATE_HZ_OFFSET: timing["adc_pair_rate_hz"],
        constants.INFO_RESPONSE_GPIO_SAMPLE_RATE_HZ_OFFSET: timing[
            "gpio_sample_rate_hz"
        ],
        constants.INFO_RESPONSE_FRAME_COVERAGE_TICKS_OFFSET: timing[
            "disabled_frame_coverage_ticks"
            if mode is constants.AuxBankMode.DISABLED
            else "input_frame_coverage_ticks"
        ],
    }
    for offset, expected in active_u32.items():
        if _u32(payload, offset) != int(expected):
            raise V2FrameValidationError(
                "INFO active rate/timing echo is contradictory"
            )
    active_u16 = {
        constants.INFO_RESPONSE_ADC_PAIR_PERIOD_TICKS_OFFSET: timing[
            "adc_pair_period_ticks"
        ],
        constants.INFO_RESPONSE_ADC1_PHASE_TICKS_OFFSET: timing["adc1_phase_ticks"],
        constants.INFO_RESPONSE_GPIO_SAMPLE_PERIOD_TICKS_OFFSET: timing[
            "gpio_sample_period_ticks"
        ],
        constants.INFO_RESPONSE_DATA_PAYLOAD_BYTES_OFFSET: layout["adc_payload_bytes"],
        constants.INFO_RESPONSE_ADC_PAIRS_PER_FRAME_OFFSET: layout[
            "adc_items_per_frame"
        ],
        constants.INFO_RESPONSE_GPIO_SAMPLES_PER_FRAME_OFFSET: layout[
            "gpio_items_per_frame"
        ],
    }
    for offset, expected in active_u16.items():
        if _u16(payload, offset) != int(expected):
            raise V2FrameValidationError("INFO active layout echo is contradictory")
    declared_counts = {
        constants.INFO_RESPONSE_DISABLED_ADC_PAIRS_PER_FRAME_OFFSET: constants.AUX_BANK_LAYOUTS[
            constants.AuxBankMode.DISABLED
        ]["adc_items_per_frame"],
        constants.INFO_RESPONSE_DISABLED_GPIO_SAMPLES_PER_FRAME_OFFSET: constants.AUX_BANK_LAYOUTS[
            constants.AuxBankMode.DISABLED
        ]["gpio_items_per_frame"],
        constants.INFO_RESPONSE_INPUT_ADC_PAIRS_PER_FRAME_OFFSET: constants.AUX_BANK_LAYOUTS[
            constants.AuxBankMode.INPUT
        ]["adc_items_per_frame"],
        constants.INFO_RESPONSE_INPUT_GPIO_SAMPLES_PER_FRAME_OFFSET: constants.AUX_BANK_LAYOUTS[
            constants.AuxBankMode.INPUT
        ]["gpio_items_per_frame"],
    }
    for offset, expected in declared_counts.items():
        if _u16(payload, offset) != int(expected):
            raise V2FrameValidationError(
                "INFO mode-specific frame count is invalid",
                reason="bad_frame_counts",
            )
    extension_u8 = {
        constants.INFO_RESPONSE_AUX_GPIO_STANDARD_PORT_OFFSET: (
            constants.AUX_GPIO_STANDARD_PORT
        ),
        constants.INFO_RESPONSE_AUX_GPIO_FAST_PORT_OFFSET: constants.AUX_GPIO_FAST_PORT,
        constants.INFO_RESPONSE_AUX_GPIO_FAST_SELECT_GPR_OFFSET: (
            constants.AUX_GPIO_FAST_SELECT_GPR
        ),
        constants.INFO_RESPONSE_GPIO_RAW_WORD_BYTES_OFFSET: (
            constants.GPIO_RAW_WORD_BYTES_PER_BANK
        ),
        constants.INFO_RESPONSE_PRIMARY_GPIO_STANDARD_PORT_OFFSET: (
            constants.PRIMARY_GPIO_STANDARD_PORT
        ),
        constants.INFO_RESPONSE_PRIMARY_GPIO_FAST_PORT_OFFSET: (
            constants.PRIMARY_GPIO_FAST_PORT
        ),
        constants.INFO_RESPONSE_PRIMARY_GPIO_FAST_SELECT_GPR_OFFSET: (
            constants.PRIMARY_GPIO_FAST_SELECT_GPR
        ),
        constants.INFO_RESPONSE_PRIMARY_GPIO_EDMA_CHANNEL_OFFSET: (
            constants.GPIO_EDMA_CHANNEL
        ),
        constants.INFO_RESPONSE_AUX_GPIO_EDMA_CHANNEL_OFFSET: (
            constants.AUX_GPIO_EDMA_CHANNEL
        ),
        constants.INFO_RESPONSE_PRIMARY_GPIO_DMAMUX_SOURCE_OFFSET: (
            constants.GPIO_DMAMUX_SOURCE
        ),
        constants.INFO_RESPONSE_AUX_GPIO_DMAMUX_SOURCE_OFFSET: (
            constants.AUX_GPIO_DMAMUX_SOURCE
        ),
        constants.INFO_RESPONSE_PRIMARY_GPIO_XBAR_OUTPUT_OFFSET: (
            constants.GPIO_XBAR_OUTPUT
        ),
        constants.INFO_RESPONSE_AUX_GPIO_XBAR_OUTPUT_OFFSET: (
            constants.AUX_GPIO_XBAR_OUTPUT
        ),
        constants.INFO_RESPONSE_PAIRED_GPIO_XBAR_INPUT_OFFSET: (
            constants.GPIO_XBAR_INPUT
        ),
        constants.INFO_RESPONSE_AUX_GPIO_RAW_RING_DEPTH_OFFSET: (
            constants.AUX_GPIO_RAW_RING_DEPTH
        ),
        constants.INFO_RESPONSE_PAIRED_GPIO_JOIN_REQUIRED_OFFSET: 1,
    }
    for offset, expected in extension_u8.items():
        if payload[offset] != int(expected):
            raise V2FrameValidationError("INFO provisional resource map is invalid")
    port_bits_start = constants.INFO_RESPONSE_AUX_GPIO_PORT_BITS_OFFSET
    port_bits_end = port_bits_start + constants.INFO_RESPONSE_AUX_GPIO_PORT_BITS_COUNT
    if tuple(payload[port_bits_start:port_bits_end]) != (
        constants.AUX_GPIO_PORT_BITS_BY_WIRE_BIT
    ):
        raise V2FrameValidationError("INFO auxiliary GPIO port-bit map is invalid")
    _validate_info_profile_table(payload)


def _validate_v1_compatible_control(header: V2FrameHeader, payload: bytes) -> None:
    try:
        encode_v1_frame(
            v1_constants.FrameKind(int(header.kind)),
            payload,
            flags=v1_constants.FrameFlag(int(header.flags)),
            checksum_algorithm=v1_constants.ChecksumAlgorithm(
                int(header.checksum_algorithm)
            ),
            run_id=header.run_id,
            sequence=header.sequence,
            request_id=header.request_id,
            first_sample_ticks=header.first_sample_ticks,
            item_count=header.item_count,
        )
    except (ValueError, V1FrameValidationError) as exc:
        raise V2FrameValidationError(str(exc)) from exc


def _validate_v2_payload(header: V2FrameHeader, payload: bytes) -> None:
    if len(payload) != header.payload_length:
        raise V2FrameValidationError(
            "payload length disagrees with header",
            reason="invalid_length",
            error_code=constants.ErrorCode.INVALID_LENGTH,
        )
    if header.kind is constants.FrameKind.ADC_DATA:
        if not adc_payload_codes_valid(payload):
            raise V2FrameValidationError("ADC payload contains out-of-range codes")
        return
    if header.kind is constants.FrameKind.GPIO_DATA:
        return
    if header.kind is constants.FrameKind.CONFIGURE_REQUEST:
        decode_v2_configuration(payload)
        return
    if header.kind in _TYPED_RESPONSE_KINDS or header.kind is (
        constants.FrameKind.ERROR_RESPONSE
    ):
        _validate_response_prefix(header, payload)
        if header.flags & constants.FrameFlag.RESPONSE_ERROR:
            return
    if header.kind is constants.FrameKind.GET_TEMPERATURE_REQUEST:
        return
    if header.kind in (
        constants.FrameKind.CHECKSUM_BENCHMARK_RESPONSE,
        constants.FrameKind.GPIO_CLOCK_DIAGNOSTIC_RESPONSE,
    ):
        benchmark = header.kind is constants.FrameKind.CHECKSUM_BENCHMARK_RESPONSE
        offset = (
            constants.CHECKSUM_BENCHMARK_RESPONSE_CYCLE_COUNTER_HZ_OFFSET
            if benchmark
            else constants.GPIO_CLOCK_DIAGNOSTIC_RESPONSE_DWT_COUNTER_HZ_OFFSET
        )
        clock_hz = _u32(payload, offset)
        if clock_hz not in (450_000_000, 600_000_000):
            raise V2FrameValidationError("unsupported diagnostic DWT clock")
        validator = (
            _validate_checksum_benchmark_response
            if benchmark
            else _validate_gpio_clock_diagnostic_response
        )
        try:
            validator(payload, clock_hz=clock_hz)
        except V1FrameValidationError as error:
            raise V2FrameValidationError(str(error)) from error
        return
    if header.kind is constants.FrameKind.GET_TEMPERATURE_RESPONSE:
        decode_temperature_payload(payload)
        return
    if header.kind is constants.FrameKind.INFO_RESPONSE:
        _validate_info_payload(payload)
        return
    if header.kind in {
        constants.FrameKind.CONFIGURE_RESPONSE,
        constants.FrameKind.START_RESPONSE,
    }:
        decode_v2_configuration(payload, response=True)
        return
    if header.kind is constants.FrameKind.GET_STATUS_RESPONSE:
        if (
            payload[constants.STATUS_RESPONSE_PROTOCOL_VERSION_OFFSET]
            != constants.PROTOCOL_VERSION
            or payload[constants.STATUS_RESPONSE_AUX_BANK_MODE_OFFSET]
            not in tuple(int(mode) for mode in constants.AuxBankMode)
            or payload[constants.STATUS_RESPONSE_RATE_PROFILE_OFFSET]
            not in tuple(int(profile) for profile in constants.RateProfile)
            or _u32(payload, constants.STATUS_RESPONSE_RESERVED_4_OFFSET) != 0
        ):
            raise V2FrameValidationError("STATUS v2 extension is contradictory")
        expected_item_bytes = (
            2
            if payload[constants.STATUS_RESPONSE_AUX_BANK_MODE_OFFSET]
            == int(constants.AuxBankMode.INPUT)
            else 1
        )
        if payload[constants.STATUS_RESPONSE_GPIO_ITEM_BYTES_OFFSET] != (
            expected_item_bytes
        ):
            raise V2FrameValidationError("STATUS GPIO width is contradictory")
        return
    if header.kind is constants.FrameKind.GPIO_CAPTURE_DIAGNOSTIC_RESPONSE:
        if (
            payload[constants.GPIO_CAPTURE_DIAGNOSTIC_RESPONSE_BANK_COUNT_OFFSET]
            not in (1, 2)
            or payload[constants.GPIO_CAPTURE_DIAGNOSTIC_RESPONSE_AUX_BANK_MODE_OFFSET]
            not in tuple(int(mode) for mode in constants.AuxBankMode)
            or payload[
                constants.GPIO_CAPTURE_DIAGNOSTIC_RESPONSE_SELECTED_RATE_PROFILE_OFFSET
            ]
            not in tuple(int(profile) for profile in constants.RateProfile)
            or payload[
                constants.GPIO_CAPTURE_DIAGNOSTIC_RESPONSE_AUX_ELECTRICALLY_UNSTIMULATED_OFFSET
            ]
            not in (0, 1)
            or payload[
                constants.GPIO_CAPTURE_DIAGNOSTIC_RESPONSE_AUX_EXTERNAL_TRANSITION_CHECKS_RUN_OFFSET
            ]
            not in (0, 1)
            or payload[constants.GPIO_CAPTURE_DIAGNOSTIC_RESPONSE_RESERVED_3_OFFSET]
            != 0
            or _u16(
                payload,
                constants.GPIO_CAPTURE_DIAGNOSTIC_RESPONSE_RESERVED_4_OFFSET,
            )
            != 0
            or payload[constants.GPIO_CAPTURE_DIAGNOSTIC_RESPONSE_RESERVED_5_OFFSET]
            != 0
        ):
            raise V2FrameValidationError(
                "GPIO capture diagnostic v2 extension is contradictory"
            )
        return
    _validate_v1_compatible_control(header, payload)


@dataclass(frozen=True)
class TemperatureReading:
    """Latest calibrated die temperature, not ambient or a forced conversion."""

    status: constants.TemperatureStatus
    millidegrees_c: int | None

    @property
    def celsius(self) -> float | None:
        return None if self.millidegrees_c is None else self.millidegrees_c / 1000


def decode_temperature_payload(payload: bytes) -> TemperatureReading:
    if len(payload) != constants.TEMPERATURE_RESPONSE_PAYLOAD_SIZE:
        raise V2FrameValidationError("invalid temperature response size")
    status, reserved, error, sensor, reserved1, reserved2, value = struct.unpack(
        "<BBHBBHi", payload
    )
    if status or reserved or error or reserved1 or reserved2:
        raise V2FrameValidationError(
            "invalid temperature response prefix/reserved fields"
        )
    try:
        sensor_status = constants.TemperatureStatus(sensor)
    except ValueError as exc:
        raise V2FrameValidationError("unknown temperature status") from exc
    if sensor_status is constants.TemperatureStatus.VALID:
        if not -40000 <= value <= 150000:
            raise V2FrameValidationError("temperature outside sensor reporting range")
        return TemperatureReading(sensor_status, value)
    if value != 0:
        raise V2FrameValidationError(
            "unavailable temperature must have zero wire value"
        )
    return TemperatureReading(sensor_status, None)


def encode_v2_frame(
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
    """Encode one strict protocol-v2 frame."""

    try:
        selected_kind = constants.FrameKind(kind)
        selected_flags = constants.FrameFlag(flags)
    except ValueError as exc:
        raise V2FrameValidationError("unknown frame kind or flags") from exc
    selected_checksum = (
        constants.DEFAULT_CHECKSUM_ALGORITHM
        if checksum_algorithm is None and selected_kind in _DATA_KINDS
        else constants.BOOTSTRAP_CHECKSUM_ALGORITHM
        if checksum_algorithm is None
        else constants.ChecksumAlgorithm(checksum_algorithm)
    )
    payload_bytes = bytes(payload)
    header = V2FrameHeader(
        kind=selected_kind,
        flags=selected_flags,
        checksum_algorithm=selected_checksum,
        total_length=constants.HEADER_SIZE
        + len(payload_bytes)
        + constants.TRAILER_SIZE,
        payload_length=len(payload_bytes),
        run_id=run_id,
        sequence=sequence,
        request_id=request_id,
        first_sample_ticks=first_sample_ticks,
        item_count=item_count,
    )
    _validate_v2_header(header)
    _validate_v2_payload(header, payload_bytes)
    body = header.to_bytes() + payload_bytes
    return body + _TRAILER.pack(compute_v2_checksum(body, selected_checksum))


def decode_v2_frame(data: BytesLike) -> V2Frame:
    """Decode exactly one checksummed protocol-v2 frame."""

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
    _validate_v2_payload(header, payload)
    return V2Frame(header=header, payload=payload, checksum=observed_checksum)


def decode_compatible_frame(data: BytesLike) -> CompatibleFrame:
    """Decode v1 by default while accepting an explicitly versioned v2 frame."""

    frame_bytes = bytes(data)
    if len(frame_bytes) < constants.HEADER_VERSION_OFFSET + 1:
        return decode_v1_frame(frame_bytes)
    version = frame_bytes[constants.HEADER_VERSION_OFFSET]
    if version == v1_constants.PROTOCOL_VERSION:
        return decode_v1_frame(frame_bytes)
    if version == constants.PROTOCOL_VERSION:
        return decode_v2_frame(frame_bytes)
    raise V2FrameValidationError(
        f"unsupported protocol version {version}",
        reason="unsupported_version",
        error_code=constants.ErrorCode.UNSUPPORTED_VERSION,
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
    _validate_v2_payload(header, payload)
    return V2Frame(header=header, payload=payload, checksum=observed_checksum)


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


def _decode_compatible_header(
    data: bytearray,
    offset: int = 0,
) -> CompatibleFrameHeader:
    """Decode a v1 or v2 header while presenting one validation type."""

    if len(data) - offset <= constants.HEADER_VERSION_OFFSET:
        raise V2FrameValidationError(
            "frame does not contain a protocol version",
            reason="invalid_length",
            error_code=constants.ErrorCode.INVALID_LENGTH,
        )
    version = data[offset + constants.HEADER_VERSION_OFFSET]
    if version == constants.PROTOCOL_VERSION:
        return _decode_v2_header(data, offset)
    if version == v1_constants.PROTOCOL_VERSION:
        try:
            return _decode_v1_header(data, offset)
        except V1FrameValidationError as exc:
            raise V2FrameValidationError(
                str(exc),
                reason="invalid_v1_frame",
                error_code=constants.ErrorCode(int(exc.error_code)),
            ) from exc
    raise V2FrameValidationError(
        f"unsupported protocol version {version}",
        reason="unsupported_version",
        error_code=constants.ErrorCode.UNSUPPORTED_VERSION,
    )


def _decode_buffered_compatible_frame(
    buffer: bytearray,
    offset: int,
    header: CompatibleFrameHeader,
) -> CompatibleFrame:
    if isinstance(header, V2FrameHeader):
        return _decode_buffered_v2_frame(buffer, offset, header)
    try:
        return _decode_buffered_v1_frame(buffer, offset, header)
    except V1ChecksumMismatchError as exc:
        raise V2ChecksumMismatchError(exc.expected, exc.observed) from exc
    except V1FrameValidationError as exc:
        raise V2FrameValidationError(
            str(exc),
            reason="invalid_v1_frame",
            error_code=constants.ErrorCode(int(exc.error_code)),
        ) from exc


class IncrementalCompatibleFrameParser(
    BoundedIncrementalParser[CompatibleFrameHeader, CompatibleFrame]
):
    """Boundedly parse interleaved v1 and explicitly negotiated v2 frames."""

    max_buffered_bytes = MAX_V2_BUFFERED_BYTES

    def __init__(self) -> None:
        super().__init__(
            magic_bytes=constants.MAGIC_BYTES,
            header_size=constants.HEADER_SIZE,
            max_frame_bytes=_MAX_FRAME_BYTES,
            decode_header=_decode_compatible_header,
            decode_frame=_decode_buffered_compatible_frame,
            validation_error=V2FrameValidationError,
            checksum_error=V2ChecksumMismatchError,
        )


__all__ = [
    "MAX_V2_BUFFERED_BYTES",
    "CompatibleFrame",
    "CompatibleFrameHeader",
    "IncrementalCompatibleFrameParser",
    "IncrementalV2FrameParser",
    "ParserCounters",
    "V2ChecksumMismatchError",
    "V2ConfigurationEchoError",
    "V2ConfigurationFields",
    "V2Frame",
    "V2FrameHeader",
    "V2FrameValidationError",
    "V2ProtocolError",
    "V2UnsupportedChecksumError",
    "compute_v2_checksum",
    "decode_compatible_frame",
    "decode_v2_configuration",
    "decode_v2_frame",
    "encode_v2_frame",
    "select_protocol_version",
    "validate_v2_configuration_echo",
]
