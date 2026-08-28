"""Typed protocol models and lazy views over ADC and GPIO payloads."""

from __future__ import annotations

import struct
from collections.abc import Iterator, Sequence
from dataclasses import dataclass
from enum import IntEnum
from typing import Generic, TypeVar, overload

from ._generated import protocol_constants as constants
from .protocol import Frame, FrameValidationError

_CONFIGURATION = struct.Struct("<BBBBI")
_RESPONSE_PREFIX = struct.Struct("<BBH")
_STATUS_COUNTERS = struct.Struct("<QQQQII")
_ResponseValue = TypeVar("_ResponseValue")


def _unsigned(name: str, value: int, bits: int) -> None:
    if not isinstance(value, int) or not 0 <= value < (1 << bits):
        raise ValueError(f"{name} must be an unsigned {bits}-bit integer")


def _success_prefix(payload: bytes, expected_size: int) -> None:
    if len(payload) != expected_size:
        raise FrameValidationError(f"payload must be {expected_size} bytes")
    status, reserved, error = _RESPONSE_PREFIX.unpack_from(payload)
    if (
        status != constants.ResponseStatus.OK
        or reserved != 0
        or error != constants.ErrorCode.OK
    ):
        raise FrameValidationError("payload does not contain a successful response")


@dataclass(frozen=True, slots=True)
class Configuration:
    """Requested or applied ADC/GPIO stream configuration."""

    stream_mask: constants.StreamMask
    source: constants.Source
    data_checksum_algorithm: constants.ChecksumAlgorithm = (
        constants.DEFAULT_CHECKSUM_ALGORITHM
    )
    data_frame_bytes: int = constants.DATA_FRAME_BYTES

    def __post_init__(self) -> None:
        valid_streams = constants.StreamMask.ADC | constants.StreamMask.GPIO
        if self.stream_mask == constants.StreamMask.NONE or int(
            self.stream_mask
        ) & ~int(valid_streams):
            raise ValueError("configuration requires a nonempty ADC/GPIO stream mask")
        if self.source not in constants.Source:
            raise ValueError("configuration source is invalid")
        if self.data_checksum_algorithm is constants.ChecksumAlgorithm.NONE_RESERVED:
            raise ValueError("configuration cannot select checksum ID zero")
        if self.data_frame_bytes != constants.DATA_FRAME_BYTES:
            raise ValueError("protocol v1 data frames are exactly 4096 bytes")

    def to_payload(self) -> bytes:
        """Encode the eight configuration fields that follow any response prefix."""

        return _CONFIGURATION.pack(
            int(self.stream_mask),
            int(self.source),
            int(self.data_checksum_algorithm),
            0,
            self.data_frame_bytes,
        )

    @classmethod
    def from_payload(cls, payload: bytes | bytearray | memoryview) -> Configuration:
        """Decode the eight-byte CONFIGURE request/applied-configuration body."""

        payload_bytes = bytes(payload)
        if len(payload_bytes) != constants.CONFIGURE_REQUEST_PAYLOAD_SIZE:
            raise FrameValidationError("configuration body must be eight bytes")
        raw_streams, raw_source, raw_checksum, reserved, frame_bytes = (
            _CONFIGURATION.unpack(payload_bytes)
        )
        if reserved != 0:
            raise FrameValidationError("configuration reserved byte must be zero")
        try:
            return cls(
                stream_mask=constants.StreamMask(raw_streams),
                source=constants.Source(raw_source),
                data_checksum_algorithm=constants.ChecksumAlgorithm(raw_checksum),
                data_frame_bytes=frame_bytes,
            )
        except ValueError as exc:
            raise FrameValidationError(str(exc)) from exc


@dataclass(frozen=True, slots=True)
class Info:
    """Identity and fixed protocol-v1 capabilities returned by INFO."""

    device_state: constants.DeviceState
    build_id: str
    hardware_serial: int = 0
    firmware_version: tuple[int, int, int] = (0, 0, 0)
    board_id: constants.BoardId = constants.BoardId.SIMULATOR
    mcu_id: constants.McuId = constants.McuId.SIMULATED
    supported_stream_mask: constants.StreamMask = (
        constants.StreamMask.ADC | constants.StreamMask.GPIO
    )
    supported_source_mask: int = 0x03
    supported_checksum_mask: int = constants.SUPPORTED_CHECKSUM_MASK
    protocol_version: int = constants.PROTOCOL_VERSION
    timestamp_hz: int = constants.TIMESTAMP_HZ
    data_frame_bytes: int = constants.DATA_FRAME_BYTES
    max_control_frame_bytes: int = constants.MAX_CONTROL_FRAME_BYTES
    adc_pair_rate_hz: int = constants.ADC_PAIR_RATE_HZ
    gpio_sample_rate_hz: int = constants.GPIO_SAMPLE_RATE_HZ
    adc_pair_period_ticks: int = constants.ADC_PAIR_PERIOD_TICKS
    adc1_phase_ticks: int = constants.ADC1_PHASE_TICKS
    gpio_sample_period_ticks: int = constants.GPIO_SAMPLE_PERIOD_TICKS
    adc_resolution_bits: int = constants.ADC_RESOLUTION_BITS
    adc_container_bytes: int = constants.ADC_CONTAINER_BITS // 8
    gpio_pin_map: tuple[int, ...] = constants.GPIO_PINS_BY_BIT

    def __post_init__(self) -> None:
        _unsigned("hardware_serial", self.hardware_serial, 32)
        if len(self.firmware_version) != 3:
            raise ValueError("firmware_version must contain major, minor, and patch")
        for part in self.firmware_version:
            _unsigned("firmware version component", part, 8)
        try:
            encoded_build = self.build_id.encode("ascii")
        except UnicodeEncodeError as exc:
            raise ValueError("build_id must contain only ASCII") from exc
        if b"\0" in encoded_build or len(encoded_build) >= (
            constants.INFO_RESPONSE_BUILD_ID_COUNT
        ):
            raise ValueError("build_id must fit 31 ASCII bytes without embedded NUL")
        valid_streams = int(constants.StreamMask.ADC | constants.StreamMask.GPIO)
        if int(self.supported_stream_mask) & ~valid_streams:
            raise ValueError("supported stream mask contains unknown bits")
        if self.supported_source_mask == 0 or self.supported_source_mask & ~0x03:
            raise ValueError("supported source mask contains unknown bits")
        fixed_values = (
            (self.protocol_version, constants.PROTOCOL_VERSION),
            (self.supported_checksum_mask, constants.SUPPORTED_CHECKSUM_MASK),
            (self.timestamp_hz, constants.TIMESTAMP_HZ),
            (self.data_frame_bytes, constants.DATA_FRAME_BYTES),
            (self.max_control_frame_bytes, constants.MAX_CONTROL_FRAME_BYTES),
            (self.adc_pair_rate_hz, constants.ADC_PAIR_RATE_HZ),
            (self.gpio_sample_rate_hz, constants.GPIO_SAMPLE_RATE_HZ),
            (self.adc_pair_period_ticks, constants.ADC_PAIR_PERIOD_TICKS),
            (self.adc1_phase_ticks, constants.ADC1_PHASE_TICKS),
            (self.gpio_sample_period_ticks, constants.GPIO_SAMPLE_PERIOD_TICKS),
            (self.adc_resolution_bits, constants.ADC_RESOLUTION_BITS),
            (self.adc_container_bytes, constants.ADC_CONTAINER_BITS // 8),
        )
        if any(actual != expected for actual, expected in fixed_values):
            raise ValueError("INFO capabilities are incompatible with protocol v1")
        if self.gpio_pin_map != constants.GPIO_PINS_BY_BIT:
            raise ValueError("GPIO bit order must remain D6 through D13")

    def supports_source(self, source: constants.Source) -> bool:
        """Return whether INFO advertises the requested source ID."""

        return bool(self.supported_source_mask & (1 << int(source)))

    def to_payload(self) -> bytes:
        """Encode a successful 94-byte INFO response payload."""

        payload = bytearray(constants.INFO_RESPONSE_PAYLOAD_SIZE)
        _RESPONSE_PREFIX.pack_into(
            payload, 0, constants.ResponseStatus.OK, 0, constants.ErrorCode.OK
        )
        payload[constants.INFO_RESPONSE_DEVICE_STATE_OFFSET] = int(self.device_state)
        payload[constants.INFO_RESPONSE_PROTOCOL_VERSION_OFFSET] = self.protocol_version
        payload[constants.INFO_RESPONSE_SUPPORTED_STREAM_MASK_OFFSET] = int(
            self.supported_stream_mask
        )
        payload[constants.INFO_RESPONSE_SUPPORTED_SOURCE_MASK_OFFSET] = (
            self.supported_source_mask
        )
        struct.pack_into(
            "<IIIII",
            payload,
            constants.INFO_RESPONSE_SUPPORTED_CHECKSUM_MASK_OFFSET,
            self.supported_checksum_mask,
            self.timestamp_hz,
            self.data_frame_bytes,
            self.max_control_frame_bytes,
            self.adc_pair_rate_hz,
        )
        struct.pack_into(
            "<IHHH",
            payload,
            constants.INFO_RESPONSE_GPIO_SAMPLE_RATE_HZ_OFFSET,
            self.gpio_sample_rate_hz,
            self.adc_pair_period_ticks,
            self.adc1_phase_ticks,
            self.gpio_sample_period_ticks,
        )
        payload[constants.INFO_RESPONSE_ADC_RESOLUTION_BITS_OFFSET] = (
            self.adc_resolution_bits
        )
        payload[constants.INFO_RESPONSE_ADC_CONTAINER_BYTES_OFFSET] = (
            self.adc_container_bytes
        )
        payload[constants.INFO_RESPONSE_GPIO_PIN_COUNT_OFFSET] = len(self.gpio_pin_map)
        pin_start = constants.INFO_RESPONSE_GPIO_PIN_MAP_OFFSET
        payload[pin_start : pin_start + len(self.gpio_pin_map)] = bytes(
            self.gpio_pin_map
        )
        struct.pack_into(
            "<I",
            payload,
            constants.INFO_RESPONSE_HARDWARE_SERIAL_OFFSET,
            self.hardware_serial,
        )
        version_start = constants.INFO_RESPONSE_FIRMWARE_VERSION_MAJOR_OFFSET
        payload[version_start : version_start + 3] = bytes(self.firmware_version)
        struct.pack_into(
            "<HH",
            payload,
            constants.INFO_RESPONSE_BOARD_ID_OFFSET,
            int(self.board_id),
            int(self.mcu_id),
        )
        build_bytes = self.build_id.encode("ascii")
        build_start = constants.INFO_RESPONSE_BUILD_ID_OFFSET
        payload[build_start : build_start + len(build_bytes)] = build_bytes
        return bytes(payload)

    @classmethod
    def from_payload(cls, payload: bytes | bytearray | memoryview) -> Info:
        """Decode a successful INFO response payload."""

        payload_bytes = bytes(payload)
        _success_prefix(payload_bytes, constants.INFO_RESPONSE_PAYLOAD_SIZE)
        build_start = constants.INFO_RESPONSE_BUILD_ID_OFFSET
        build_end = build_start + constants.INFO_RESPONSE_BUILD_ID_COUNT
        raw_build = payload_bytes[build_start:build_end]
        try:
            build_id = raw_build[: raw_build.index(0)].decode("ascii")
        except (ValueError, UnicodeDecodeError) as exc:
            raise FrameValidationError("INFO build ID is not valid ASCII") from exc
        version_start = constants.INFO_RESPONSE_FIRMWARE_VERSION_MAJOR_OFFSET
        return cls(
            device_state=constants.DeviceState(
                payload_bytes[constants.INFO_RESPONSE_DEVICE_STATE_OFFSET]
            ),
            build_id=build_id,
            hardware_serial=struct.unpack_from(
                "<I", payload_bytes, constants.INFO_RESPONSE_HARDWARE_SERIAL_OFFSET
            )[0],
            firmware_version=(
                payload_bytes[version_start],
                payload_bytes[version_start + 1],
                payload_bytes[version_start + 2],
            ),
            board_id=constants.BoardId(
                struct.unpack_from(
                    "<H", payload_bytes, constants.INFO_RESPONSE_BOARD_ID_OFFSET
                )[0]
            ),
            mcu_id=constants.McuId(
                struct.unpack_from(
                    "<H", payload_bytes, constants.INFO_RESPONSE_MCU_ID_OFFSET
                )[0]
            ),
            supported_stream_mask=constants.StreamMask(
                payload_bytes[constants.INFO_RESPONSE_SUPPORTED_STREAM_MASK_OFFSET]
            ),
            supported_source_mask=payload_bytes[
                constants.INFO_RESPONSE_SUPPORTED_SOURCE_MASK_OFFSET
            ],
            supported_checksum_mask=struct.unpack_from(
                "<I",
                payload_bytes,
                constants.INFO_RESPONSE_SUPPORTED_CHECKSUM_MASK_OFFSET,
            )[0],
            protocol_version=payload_bytes[
                constants.INFO_RESPONSE_PROTOCOL_VERSION_OFFSET
            ],
            timestamp_hz=struct.unpack_from(
                "<I", payload_bytes, constants.INFO_RESPONSE_TIMESTAMP_HZ_OFFSET
            )[0],
            data_frame_bytes=struct.unpack_from(
                "<I", payload_bytes, constants.INFO_RESPONSE_DATA_FRAME_BYTES_OFFSET
            )[0],
            max_control_frame_bytes=struct.unpack_from(
                "<I",
                payload_bytes,
                constants.INFO_RESPONSE_MAX_CONTROL_FRAME_BYTES_OFFSET,
            )[0],
            adc_pair_rate_hz=struct.unpack_from(
                "<I", payload_bytes, constants.INFO_RESPONSE_ADC_PAIR_RATE_HZ_OFFSET
            )[0],
            gpio_sample_rate_hz=struct.unpack_from(
                "<I",
                payload_bytes,
                constants.INFO_RESPONSE_GPIO_SAMPLE_RATE_HZ_OFFSET,
            )[0],
            adc_pair_period_ticks=struct.unpack_from(
                "<H",
                payload_bytes,
                constants.INFO_RESPONSE_ADC_PAIR_PERIOD_TICKS_OFFSET,
            )[0],
            adc1_phase_ticks=struct.unpack_from(
                "<H", payload_bytes, constants.INFO_RESPONSE_ADC1_PHASE_TICKS_OFFSET
            )[0],
            gpio_sample_period_ticks=struct.unpack_from(
                "<H",
                payload_bytes,
                constants.INFO_RESPONSE_GPIO_SAMPLE_PERIOD_TICKS_OFFSET,
            )[0],
            adc_resolution_bits=payload_bytes[
                constants.INFO_RESPONSE_ADC_RESOLUTION_BITS_OFFSET
            ],
            adc_container_bytes=payload_bytes[
                constants.INFO_RESPONSE_ADC_CONTAINER_BYTES_OFFSET
            ],
            gpio_pin_map=tuple(
                payload_bytes[
                    constants.INFO_RESPONSE_GPIO_PIN_MAP_OFFSET : constants.INFO_RESPONSE_GPIO_PIN_MAP_OFFSET
                    + constants.INFO_RESPONSE_GPIO_PIN_MAP_COUNT
                ]
            ),
        )


DeviceInfo = Info


@dataclass(frozen=True, slots=True)
class Status:
    """Device state, active configuration, and cumulative run counters."""

    device_state: constants.DeviceState
    stream_mask: constants.StreamMask
    source: constants.Source
    data_checksum_algorithm: constants.ChecksumAlgorithm
    data_frame_bytes: int = constants.DATA_FRAME_BYTES
    adc_frames_emitted: int = 0
    gpio_frames_emitted: int = 0
    adc_items_dropped: int = 0
    gpio_items_dropped: int = 0
    parser_errors: int = 0
    transport_errors: int = 0

    def __post_init__(self) -> None:
        valid_streams = int(constants.StreamMask.ADC | constants.StreamMask.GPIO)
        if int(self.stream_mask) & ~valid_streams:
            raise ValueError("status stream mask contains unknown bits")
        if self.data_checksum_algorithm not in constants.SUPPORTED_CHECKSUM_ALGORITHMS:
            raise ValueError("status checksum algorithm is not enabled")
        if self.data_frame_bytes != constants.DATA_FRAME_BYTES:
            raise ValueError("protocol v1 data frames are exactly 4096 bytes")
        for name in (
            "adc_frames_emitted",
            "gpio_frames_emitted",
            "adc_items_dropped",
            "gpio_items_dropped",
        ):
            _unsigned(name, getattr(self, name), 64)
        _unsigned("parser_errors", self.parser_errors, 32)
        _unsigned("transport_errors", self.transport_errors, 32)

    def to_payload(self) -> bytes:
        """Encode a successful 52-byte STATUS response payload."""

        payload = bytearray(constants.STATUS_RESPONSE_PAYLOAD_SIZE)
        _RESPONSE_PREFIX.pack_into(
            payload, 0, constants.ResponseStatus.OK, 0, constants.ErrorCode.OK
        )
        payload[constants.STATUS_RESPONSE_DEVICE_STATE_OFFSET] = int(self.device_state)
        payload[constants.STATUS_RESPONSE_STREAM_MASK_OFFSET] = int(self.stream_mask)
        payload[constants.STATUS_RESPONSE_SOURCE_OFFSET] = int(self.source)
        payload[constants.STATUS_RESPONSE_DATA_CHECKSUM_ALGORITHM_OFFSET] = int(
            self.data_checksum_algorithm
        )
        struct.pack_into(
            "<I",
            payload,
            constants.STATUS_RESPONSE_DATA_FRAME_BYTES_OFFSET,
            self.data_frame_bytes,
        )
        _STATUS_COUNTERS.pack_into(
            payload,
            constants.STATUS_RESPONSE_ADC_FRAMES_EMITTED_OFFSET,
            self.adc_frames_emitted,
            self.gpio_frames_emitted,
            self.adc_items_dropped,
            self.gpio_items_dropped,
            self.parser_errors,
            self.transport_errors,
        )
        return bytes(payload)

    @classmethod
    def from_payload(cls, payload: bytes | bytearray | memoryview) -> Status:
        """Decode a successful STATUS response payload."""

        payload_bytes = bytes(payload)
        _success_prefix(payload_bytes, constants.STATUS_RESPONSE_PAYLOAD_SIZE)
        counters = _STATUS_COUNTERS.unpack_from(
            payload_bytes, constants.STATUS_RESPONSE_ADC_FRAMES_EMITTED_OFFSET
        )
        return cls(
            device_state=constants.DeviceState(
                payload_bytes[constants.STATUS_RESPONSE_DEVICE_STATE_OFFSET]
            ),
            stream_mask=constants.StreamMask(
                payload_bytes[constants.STATUS_RESPONSE_STREAM_MASK_OFFSET]
            ),
            source=constants.Source(
                payload_bytes[constants.STATUS_RESPONSE_SOURCE_OFFSET]
            ),
            data_checksum_algorithm=constants.ChecksumAlgorithm(
                payload_bytes[constants.STATUS_RESPONSE_DATA_CHECKSUM_ALGORITHM_OFFSET]
            ),
            data_frame_bytes=struct.unpack_from(
                "<I",
                payload_bytes,
                constants.STATUS_RESPONSE_DATA_FRAME_BYTES_OFFSET,
            )[0],
            adc_frames_emitted=counters[0],
            gpio_frames_emitted=counters[1],
            adc_items_dropped=counters[2],
            gpio_items_dropped=counters[3],
            parser_errors=counters[4],
            transport_errors=counters[5],
        )


@dataclass(frozen=True, slots=True)
class CommandResponse(Generic[_ResponseValue]):
    """A request-correlated response with an optional typed success value."""

    kind: constants.FrameKind
    request_id: int
    run_id: int
    status: constants.ResponseStatus
    error_code: constants.ErrorCode
    value: _ResponseValue | None = None
    rejected_kind: int | None = None
    rejected_version: int | None = None

    def __post_init__(self) -> None:
        _unsigned("request_id", self.request_id, 32)
        _unsigned("run_id", self.run_id, 32)
        if self.request_id == 0:
            raise ValueError("command responses require a nonzero request ID")
        if self.ok != (self.error_code is constants.ErrorCode.OK):
            raise ValueError("response status and error code disagree")
        if self.ok and self.value is None:
            raise ValueError("successful responses require a typed value")
        if not self.ok and self.value is not None:
            raise ValueError("failed responses cannot contain a success value")

    @property
    def ok(self) -> bool:
        """Whether the command completed successfully."""

        return self.status is constants.ResponseStatus.OK


class AdcConverter(IntEnum):
    """Physical converter identity retained during explicit interleaving."""

    ADC0 = 0
    ADC1 = 1

    @property
    def pin(self) -> str:
        return "A0" if self is AdcConverter.ADC0 else "A1"


@dataclass(frozen=True, slots=True)
class AdcSample:
    """One lazily materialized ADC code with converter and nominal timestamp."""

    pair_index: int
    converter: AdcConverter
    code: int
    timestamp_ticks: int

    @property
    def pin(self) -> str:
        return self.converter.pin


class AdcChannelView(Sequence[int]):
    """Lazy sequence view over one converter in an interleaved wire payload."""

    __slots__ = ("_block", "converter")

    def __init__(self, block: AdcBlock, converter: AdcConverter) -> None:
        self._block = block
        self.converter = converter

    def __len__(self) -> int:
        return self._block.item_count

    @overload
    def __getitem__(self, index: int) -> int: ...

    @overload
    def __getitem__(self, index: slice) -> tuple[int, ...]: ...

    def __getitem__(self, index: int | slice) -> int | tuple[int, ...]:
        if isinstance(index, slice):
            return tuple(
                self[position] for position in range(*index.indices(len(self)))
            )
        position = index
        if position < 0:
            position += len(self)
        if not 0 <= position < len(self):
            raise IndexError("ADC sample index out of range")
        offset = position * constants.ADC_BYTES_PER_PAIR + 2 * int(self.converter)
        return struct.unpack_from("<H", self._block.payload, offset)[0]


@dataclass(frozen=True, slots=True)
class AdcBlock:
    """One fixed ADC frame; each logical item is an ADC0/ADC1 sample pair."""

    run_id: int
    sequence: int
    first_sample_ticks: int
    payload: bytes
    flags: constants.FrameFlag = constants.FrameFlag.NONE

    def __post_init__(self) -> None:
        _unsigned("run_id", self.run_id, 32)
        _unsigned("sequence", self.sequence, 32)
        _unsigned("first_sample_ticks", self.first_sample_ticks, 64)
        if self.run_id == 0:
            raise ValueError("ADC blocks require a nonzero run ID")
        payload = bytes(self.payload)
        object.__setattr__(self, "payload", payload)
        if len(payload) != constants.ADC_DATA_PAYLOAD_SIZE:
            raise ValueError("ADC blocks require exactly 1012 sample pairs")
        code_mask = (1 << constants.ADC_RESOLUTION_BITS) - 1
        if any(
            adc0 & ~code_mask or adc1 & ~code_mask
            for adc0, adc1 in struct.iter_unpack("<HH", payload)
        ):
            raise ValueError("ADC codes must fit the configured 12-bit range")

    @classmethod
    def from_frame(cls, frame: Frame) -> AdcBlock:
        if frame.header.kind is not constants.FrameKind.ADC_DATA:
            raise TypeError("frame is not ADC_DATA")
        return cls(
            run_id=frame.header.run_id,
            sequence=frame.header.sequence,
            first_sample_ticks=frame.header.first_sample_ticks,
            payload=frame.payload,
            flags=frame.header.flags,
        )

    @property
    def item_count(self) -> int:
        """Logical pair count; this is not a combined two-channel sample rate."""

        return constants.ADC_PAIRS_PER_FRAME

    @property
    def adc0(self) -> AdcChannelView:
        return AdcChannelView(self, AdcConverter.ADC0)

    @property
    def adc1(self) -> AdcChannelView:
        return AdcChannelView(self, AdcConverter.ADC1)

    @property
    def end_tick_exclusive(self) -> int:
        return (
            self.first_sample_ticks + self.item_count * constants.ADC_PAIR_PERIOD_TICKS
        ) & constants.UINT64_MAX

    @property
    def first_pair_index(self) -> int:
        """Global per-converter sample index implied by the 8 MHz timestamp."""

        return self.first_sample_ticks // constants.ADC_PAIR_PERIOD_TICKS

    def pair(self, index: int) -> tuple[int, int]:
        return self.adc0[index], self.adc1[index]

    def pair_ticks(self, index: int) -> tuple[int, int]:
        if index < 0:
            index += self.item_count
        if not 0 <= index < self.item_count:
            raise IndexError("ADC pair index out of range")
        adc0_tick = (
            self.first_sample_ticks + index * constants.ADC_PAIR_PERIOD_TICKS
        ) & constants.UINT64_MAX
        return adc0_tick, (adc0_tick + constants.ADC1_PHASE_TICKS) & (
            constants.UINT64_MAX
        )


ADCBlock = AdcBlock


def interleave_adc(block: AdcBlock) -> Iterator[AdcSample]:
    """Lazily order ADC0/A0 then ADC1/A1 samples by nominal acquisition time."""

    adc0 = block.adc0
    adc1 = block.adc1
    for pair_index in range(block.item_count):
        adc0_tick, adc1_tick = block.pair_ticks(pair_index)
        yield AdcSample(pair_index, AdcConverter.ADC0, adc0[pair_index], adc0_tick)
        yield AdcSample(pair_index, AdcConverter.ADC1, adc1[pair_index], adc1_tick)


class GpioChannelView(Sequence[bool]):
    """Lazy Boolean view over one D6-through-D13 bit in packed GPIO samples."""

    __slots__ = ("_block", "bit", "pin")

    def __init__(self, block: GpioBlock, pin: int) -> None:
        try:
            self.bit = constants.GPIO_PINS_BY_BIT.index(pin)
        except ValueError as exc:
            raise ValueError("GPIO pin must be one of D6 through D13") from exc
        self._block = block
        self.pin = pin

    def __len__(self) -> int:
        return self._block.item_count

    @overload
    def __getitem__(self, index: int) -> bool: ...

    @overload
    def __getitem__(self, index: slice) -> tuple[bool, ...]: ...

    def __getitem__(self, index: int | slice) -> bool | tuple[bool, ...]:
        if isinstance(index, slice):
            return tuple(
                self[position] for position in range(*index.indices(len(self)))
            )
        position = index
        if position < 0:
            position += len(self)
        if not 0 <= position < len(self):
            raise IndexError("GPIO sample index out of range")
        return bool(self._block.payload[position] & (1 << self.bit))


@dataclass(frozen=True, slots=True)
class GpioBlock:
    """One fixed GPIO frame containing packed simultaneous D6-D13 samples."""

    run_id: int
    sequence: int
    first_sample_ticks: int
    payload: bytes
    flags: constants.FrameFlag = constants.FrameFlag.NONE

    def __post_init__(self) -> None:
        _unsigned("run_id", self.run_id, 32)
        _unsigned("sequence", self.sequence, 32)
        _unsigned("first_sample_ticks", self.first_sample_ticks, 64)
        if self.run_id == 0:
            raise ValueError("GPIO blocks require a nonzero run ID")
        payload = bytes(self.payload)
        object.__setattr__(self, "payload", payload)
        if len(payload) != constants.GPIO_DATA_PAYLOAD_SIZE:
            raise ValueError("GPIO blocks require exactly 4048 packed samples")

    @classmethod
    def from_frame(cls, frame: Frame) -> GpioBlock:
        if frame.header.kind is not constants.FrameKind.GPIO_DATA:
            raise TypeError("frame is not GPIO_DATA")
        return cls(
            run_id=frame.header.run_id,
            sequence=frame.header.sequence,
            first_sample_ticks=frame.header.first_sample_ticks,
            payload=frame.payload,
            flags=frame.header.flags,
        )

    @property
    def item_count(self) -> int:
        """Count of simultaneous eight-pin samples in the payload."""

        return constants.GPIO_SAMPLES_PER_FRAME

    @property
    def samples(self) -> memoryview:
        """Zero-copy byte view preserving the packed D6-through-D13 bit order."""

        return memoryview(self.payload)

    @property
    def end_tick_exclusive(self) -> int:
        return (
            self.first_sample_ticks
            + self.item_count * constants.GPIO_SAMPLE_PERIOD_TICKS
        ) & constants.UINT64_MAX

    @property
    def first_sample_index(self) -> int:
        """Global simultaneous-snapshot index implied by the 8 MHz timestamp."""

        return self.first_sample_ticks // constants.GPIO_SAMPLE_PERIOD_TICKS

    def sample(self, index: int) -> int:
        return self.payload[index]

    def sample_ticks(self, index: int) -> int:
        if index < 0:
            index += self.item_count
        if not 0 <= index < self.item_count:
            raise IndexError("GPIO sample index out of range")
        return (
            self.first_sample_ticks + index * constants.GPIO_SAMPLE_PERIOD_TICKS
        ) & constants.UINT64_MAX

    def channel(self, pin: int) -> GpioChannelView:
        return GpioChannelView(self, pin)


GPIOBlock = GpioBlock


def extract_gpio_channel(block: GpioBlock, pin: int) -> GpioChannelView:
    """Return a lazy view of one pin without expanding the packed GPIO block."""

    return block.channel(pin)


@dataclass(frozen=True, slots=True)
class StreamGap:
    """A measured stream gap in logical pairs (ADC) or snapshots (GPIO)."""

    kind: constants.FrameKind
    run_id: int
    expected_sequence: int
    observed_sequence: int
    missing_frames: int
    missing_items: int
    expected_first_sample_ticks: int
    observed_first_sample_ticks: int

    def __post_init__(self) -> None:
        if self.kind not in {
            constants.FrameKind.ADC_DATA,
            constants.FrameKind.GPIO_DATA,
        }:
            raise ValueError("stream gaps apply only to ADC_DATA or GPIO_DATA")
        _unsigned("run_id", self.run_id, 32)
        _unsigned("expected_sequence", self.expected_sequence, 32)
        _unsigned("observed_sequence", self.observed_sequence, 32)
        _unsigned("expected_first_sample_ticks", self.expected_first_sample_ticks, 64)
        _unsigned("observed_first_sample_ticks", self.observed_first_sample_ticks, 64)
        if self.run_id == 0 or self.missing_frames < 0 or self.missing_items < 0:
            raise ValueError("stream gap counts and run ID must be nonnegative/nonzero")
        sequence_after_gap = (
            self.expected_sequence + self.missing_frames
        ) & constants.UINT32_MAX
        if self.observed_sequence != sequence_after_gap:
            raise ValueError("missing frame count disagrees with stream sequences")
        tick_after_gap = (
            self.expected_first_sample_ticks
            + self.missing_items * self.item_period_ticks
        ) & constants.UINT64_MAX
        if self.observed_first_sample_ticks != tick_after_gap:
            raise ValueError("missing item count disagrees with stream timestamps")

    @property
    def item_period_ticks(self) -> int:
        return (
            constants.ADC_PAIR_PERIOD_TICKS
            if self.kind is constants.FrameKind.ADC_DATA
            else constants.GPIO_SAMPLE_PERIOD_TICKS
        )

    @property
    def missing_duration_ticks(self) -> int:
        return self.missing_items * self.item_period_ticks

    @classmethod
    def between(
        cls,
        previous: AdcBlock | GpioBlock,
        current: AdcBlock | GpioBlock,
    ) -> StreamGap | None:
        """Measure a forward discontinuity between same-stream blocks."""

        if type(previous) is not type(current):
            raise ValueError("cannot compare different stream types")
        if previous.run_id != current.run_id:
            raise ValueError("a run change is an epoch boundary, not a stream gap")
        kind = (
            constants.FrameKind.ADC_DATA
            if isinstance(previous, AdcBlock)
            else constants.FrameKind.GPIO_DATA
        )
        expected_sequence = (previous.sequence + 1) & constants.UINT32_MAX
        missing_frames = (current.sequence - expected_sequence) & constants.UINT32_MAX
        if missing_frames > constants.UINT32_MAX // 2:
            raise ValueError("duplicate or reversed sequence is not a forward gap")
        expected_ticks = previous.end_tick_exclusive
        tick_delta = (
            current.first_sample_ticks - expected_ticks
        ) & constants.UINT64_MAX
        if tick_delta > constants.UINT64_MAX // 2:
            raise ValueError("reversed timestamp is not a forward gap")
        period = (
            constants.ADC_PAIR_PERIOD_TICKS
            if kind is constants.FrameKind.ADC_DATA
            else constants.GPIO_SAMPLE_PERIOD_TICKS
        )
        if tick_delta % period:
            raise ValueError("stream timestamp gap is not sample-period aligned")
        missing_items = tick_delta // period
        flagged = bool(current.flags & constants.FrameFlag.GAP_BEFORE)
        if missing_frames == 0 and missing_items == 0 and not flagged:
            return None
        return cls(
            kind=kind,
            run_id=current.run_id,
            expected_sequence=expected_sequence,
            observed_sequence=current.sequence,
            missing_frames=missing_frames,
            missing_items=missing_items,
            expected_first_sample_ticks=expected_ticks,
            observed_first_sample_ticks=current.first_sample_ticks,
        )


ResponseValue = Info | Configuration | Status | constants.DeviceState
DecodedMessage = AdcBlock | GpioBlock | CommandResponse[ResponseValue] | Frame


def decode_response(frame: Frame) -> CommandResponse[ResponseValue]:
    """Decode any typed or generic response into a request-correlated model."""

    response_kinds = set(constants.REQUEST_RESPONSE_KIND.values()) | {
        constants.FrameKind.ERROR_RESPONSE
    }
    if frame.header.kind not in response_kinds:
        raise TypeError("frame is not a command response")
    raw_status, _, raw_error = _RESPONSE_PREFIX.unpack_from(frame.payload)
    status = constants.ResponseStatus(raw_status)
    error = constants.ErrorCode(raw_error)
    value: ResponseValue | None = None
    rejected_kind: int | None = None
    rejected_version: int | None = None
    if status is constants.ResponseStatus.OK:
        if frame.header.kind is constants.FrameKind.INFO_RESPONSE:
            value = Info.from_payload(frame.payload)
        elif frame.header.kind in {
            constants.FrameKind.CONFIGURE_RESPONSE,
            constants.FrameKind.START_RESPONSE,
        }:
            value = Configuration.from_payload(frame.payload[4:])
        elif frame.header.kind is constants.FrameKind.STATUS_RESPONSE:
            value = Status.from_payload(frame.payload)
        elif frame.header.kind is constants.FrameKind.STOP_RESPONSE:
            value = constants.DeviceState(
                frame.payload[constants.STOP_RESPONSE_DEVICE_STATE_OFFSET]
            )
    elif frame.header.kind is constants.FrameKind.ERROR_RESPONSE:
        rejected_kind = frame.payload[constants.ERROR_RESPONSE_REJECTED_KIND_OFFSET]
        rejected_version = frame.payload[
            constants.ERROR_RESPONSE_REJECTED_VERSION_OFFSET
        ]
    return CommandResponse(
        kind=frame.header.kind,
        request_id=frame.header.request_id,
        run_id=frame.header.run_id,
        status=status,
        error_code=error,
        value=value,
        rejected_kind=rejected_kind,
        rejected_version=rejected_version,
    )


def decode_message(frame: Frame) -> DecodedMessage:
    """Decode data and response frames; validated request frames remain frames."""

    if frame.header.kind is constants.FrameKind.ADC_DATA:
        return AdcBlock.from_frame(frame)
    if frame.header.kind is constants.FrameKind.GPIO_DATA:
        return GpioBlock.from_frame(frame)
    if frame.header.kind in set(constants.REQUEST_RESPONSE_KIND.values()) | {
        constants.FrameKind.ERROR_RESPONSE
    }:
        return decode_response(frame)
    return frame


__all__ = [
    "ADCBlock",
    "AdcBlock",
    "AdcChannelView",
    "AdcConverter",
    "AdcSample",
    "CommandResponse",
    "Configuration",
    "DecodedMessage",
    "DeviceInfo",
    "GPIOBlock",
    "GpioBlock",
    "GpioChannelView",
    "Info",
    "ResponseValue",
    "Status",
    "StreamGap",
    "decode_message",
    "decode_response",
    "extract_gpio_channel",
    "interleave_adc",
]
