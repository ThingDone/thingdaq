"""Deterministic protocol peers used by the in-memory transport."""

from __future__ import annotations

import struct
from collections import deque
from dataclasses import replace
from enum import Enum
from typing import TypeAlias, cast

from ._generated import protocol_constants as constants
from ._generated import protocol_v2_constants as v2_constants
from .models import ADCBlock, Configuration, GPIOBlock, Info, Status
from .protocol import Frame, IncrementalFrameParser, encode_frame
from .protocol_v2 import (
    IncrementalV2FrameParser,
    V2Frame,
    encode_v2_data_frame,
    encode_v2_frame,
)
from .synthetic import (
    SyntheticPatternError,
    synthetic_adc_payload,
    synthetic_gpio_payload,
)

_RESPONSE_PREFIX = struct.Struct("<BBH")
_ERROR_RESPONSE = struct.Struct("<BBHBBH")
_SUCCESS_PREFIX = _RESPONSE_PREFIX.pack(
    constants.ResponseStatus.OK,
    0,
    constants.ErrorCode.OK,
)
_RECENT_REQUEST_ID_WINDOW = 16
_ADC_PAIR = struct.Struct("<HH")
SimulatorRequest: TypeAlias = Frame | V2Frame


class ExperimentalSourcePattern(str, Enum):
    """Deterministic workload available only on the experimental simulator."""

    CONSTANT = "constant"
    LONG_HOLD = "long-hold"
    SPARSE_TRANSITION = "sparse-transition"
    SLOWLY_CHANGING = "slowly-changing"
    ALTERNATING = "alternating"
    HIGH_ENTROPY = "high-entropy"


def _experimental_pattern(
    pattern: ExperimentalSourcePattern | str,
) -> ExperimentalSourcePattern:
    try:
        return ExperimentalSourcePattern(pattern)
    except (TypeError, ValueError) as error:
        choices = ", ".join(item.value for item in ExperimentalSourcePattern)
        raise ValueError(
            f"experimental source pattern must be one of: {choices}"
        ) from error


def _logical_start_index(value: int) -> int:
    if not isinstance(value, int) or isinstance(value, bool) or value < 0:
        raise ValueError("logical start index must be a nonnegative integer")
    return value


def _mix_u32(value: int) -> int:
    """Return one stateless, deterministic high-entropy 32-bit value."""

    selected = (value + 0x9E3779B9) & constants.UINT32_MAX
    selected = ((selected ^ (selected >> 16)) * 0x85EBCA6B) & constants.UINT32_MAX
    selected = ((selected ^ (selected >> 13)) * 0xC2B2AE35) & constants.UINT32_MAX
    return (selected ^ (selected >> 16)) & constants.UINT32_MAX


def _experimental_adc_pair(
    pattern: ExperimentalSourcePattern,
    index: int,
) -> tuple[int, int]:
    if pattern is ExperimentalSourcePattern.CONSTANT:
        return 0x155, 0xAAA
    if pattern is ExperimentalSourcePattern.LONG_HOLD:
        epoch = index // 128
        return (0x155 + 17 * epoch) & 0xFFF, (0xAAA + 29 * epoch) & 0xFFF
    if pattern is ExperimentalSourcePattern.SPARSE_TRANSITION:
        epoch = index // 997
        return 0x456 ^ ((epoch & 1) << 3), 0x789
    if pattern is ExperimentalSourcePattern.SLOWLY_CHANGING:
        return (0x100 + index // 8) & 0xFFF, (0x900 + index // 11) & 0xFFF
    if pattern is ExperimentalSourcePattern.ALTERNATING:
        return (0x123, 0xABC) if index & 1 == 0 else (0xFED, 0x456)
    return _mix_u32(index) & 0xFFF, (_mix_u32(index ^ 0xA5A55A5A) >> 12) & 0xFFF


def _experimental_gpio_sample(
    pattern: ExperimentalSourcePattern,
    index: int,
) -> int:
    if pattern is ExperimentalSourcePattern.CONSTANT:
        return 0x5A
    if pattern is ExperimentalSourcePattern.LONG_HOLD:
        return (0x31 + 13 * (index // 512)) & 0xFF
    if pattern is ExperimentalSourcePattern.SPARSE_TRANSITION:
        epoch = index // 4001
        gray = epoch ^ (epoch >> 1)
        return 0x33 ^ (gray & 0xFF)
    if pattern is ExperimentalSourcePattern.SLOWLY_CHANGING:
        return (0x40 + index // 16) & 0xFF
    if pattern is ExperimentalSourcePattern.ALTERNATING:
        return 0x55 if index & 1 == 0 else 0xAA
    return _mix_u32(index ^ 0xC001D00D) & 0xFF


def experimental_adc_payload(
    pattern: ExperimentalSourcePattern | str,
    first_pair: int = 0,
) -> bytes:
    """Build one exact experimental ADC logical frame."""

    selected = _experimental_pattern(pattern)
    start = _logical_start_index(first_pair)
    payload = bytearray(constants.DATA_PAYLOAD_BYTES)
    for offset in range(constants.ADC_PAIRS_PER_FRAME):
        adc0, adc1 = _experimental_adc_pair(selected, start + offset)
        _ADC_PAIR.pack_into(payload, offset * constants.ADC_BYTES_PER_PAIR, adc0, adc1)
    return bytes(payload)


def experimental_gpio_payload(
    pattern: ExperimentalSourcePattern | str,
    first_sample: int = 0,
) -> bytes:
    """Build one exact experimental GPIO logical frame."""

    selected = _experimental_pattern(pattern)
    start = _logical_start_index(first_sample)
    return bytes(
        _experimental_gpio_sample(selected, start + offset)
        for offset in range(constants.GPIO_SAMPLES_PER_FRAME)
    )


class SimulatorError(RuntimeError):
    """Base error raised by the deterministic simulated device."""


class SimulatorInputError(SimulatorError):
    """A caller supplied more input than one bounded receive operation allows."""


class SimulatedDevice:
    """A bounded, deterministic ThingDAQ protocol peer.

    The simulator consumes the same encoded request frames that future firmware
    will consume and produces ordinary encoded response/data frames.  It starts
    in ``BOOT`` and completes its bounded boot synchronously by default.
    """

    def __init__(
        self,
        *,
        auto_boot: bool = True,
        control_only: bool = False,
        build_id: str = "thingdaq-simulator-v1",
        max_receive_bytes: int = constants.MAX_CONTROL_FRAME_BYTES,
        max_requests_per_receive: int = 8,
    ) -> None:
        if max_receive_bytes < constants.MIN_FRAME_BYTES:
            raise ValueError("max_receive_bytes must hold at least one frame")
        if max_requests_per_receive <= 0:
            raise ValueError("max_requests_per_receive must be positive")
        if not isinstance(control_only, bool):
            raise TypeError("control_only must be a boolean")
        # Validate build identity through the public model once at construction.
        Info(device_state=constants.DeviceState.IDLE, build_id=build_id)

        self._build_id = build_id
        self._control_only = control_only
        self._max_receive_bytes = max_receive_bytes
        self._max_requests_per_receive = max_requests_per_receive
        self._request_parser: IncrementalFrameParser | IncrementalV2FrameParser = (
            IncrementalFrameParser()
        )
        self._state = constants.DeviceState.BOOT
        self._configuration: Configuration | None = None
        self._last_run_id = 0
        self._adc_sequence = 0
        self._gpio_sequence = 0
        self._adc_first_ticks = 0
        self._gpio_first_ticks = 0
        self._adc_item_index = 0
        self._gpio_item_index = 0
        self._adc_frames_emitted = 0
        self._gpio_frames_emitted = 0
        self._adc_items_dropped = 0
        self._gpio_items_dropped = 0
        self._parser_error_baseline = 0
        self._transport_errors = 0
        self._bad_request_ids = 0
        self._stats_generation = 1
        self._next_stream_index = 0
        self._recent_request_ids: deque[int] = deque(maxlen=_RECENT_REQUEST_ID_WINDOW)
        if auto_boot:
            self.finish_boot()

    @property
    def state(self) -> constants.DeviceState:
        """Current control state."""

        return self._state

    @property
    def configuration(self) -> Configuration | None:
        """Applied configuration, or ``None`` after boot/STOP."""

        return self._configuration

    @property
    def run_id(self) -> int:
        """Current or most recently allocated nonzero run ID."""

        return self._last_run_id

    @property
    def max_receive_bytes(self) -> int:
        """Largest byte chunk accepted by :meth:`receive`."""

        return self._max_receive_bytes

    def finish_boot(self) -> None:
        """Complete the bounded BOOT-to-IDLE transition, idempotently."""

        if self._state is constants.DeviceState.BOOT:
            self._state = constants.DeviceState.IDLE

    def record_transport_error(self) -> None:
        """Record a simulated transport failure without overflowing the counter."""

        self._transport_errors = min(
            self._transport_errors + 1,
            constants.UINT32_MAX,
        )

    def begin_host_session(self) -> None:
        """Reset session-scoped parser and replay state without stopping a run."""

        self._request_parser.reset_session()
        self._recent_request_ids.clear()

    def receive(self, data: bytes | bytearray | memoryview) -> tuple[bytes, ...]:
        """Consume one bounded host-write chunk and return encoded responses."""

        incoming = bytes(data)
        if len(incoming) > self._max_receive_bytes:
            raise SimulatorInputError(
                f"receive accepts at most {self._max_receive_bytes} bytes"
            )

        requests = cast(list[SimulatorRequest], self._request_parser.feed(incoming))
        responses: list[bytes] = []
        for index, request in enumerate(requests):
            if index >= self._max_requests_per_receive:
                response = self._busy_response(request)
            else:
                response = self._handle_frame(request)
            if response is not None:
                responses.append(response)
        return tuple(responses)

    def next_data_frame(self) -> bytes | None:
        """Produce the next enabled stream frame, or ``None`` when not running."""

        configuration = self._configuration
        if self._state is not constants.DeviceState.RUNNING or configuration is None:
            return None

        streams: list[constants.FrameKind] = []
        if configuration.stream_mask & constants.StreamMask.ADC:
            streams.append(constants.FrameKind.ADC_DATA)
        if configuration.stream_mask & constants.StreamMask.GPIO:
            streams.append(constants.FrameKind.GPIO_DATA)
        if not streams:
            return None
        kind = streams[self._next_stream_index % len(streams)]
        self._next_stream_index = (self._next_stream_index + 1) % len(streams)

        if kind is constants.FrameKind.ADC_DATA:
            return self._next_adc_frame(configuration)
        return self._next_gpio_frame(configuration)

    def status(self) -> Status:
        """Return the current status model without going through the wire."""

        configuration = self._configuration
        adc_items = self._adc_frames_emitted * constants.ADC_PAIRS_PER_FRAME
        gpio_items = self._gpio_frames_emitted * constants.GPIO_SAMPLES_PER_FRAME
        adc_payload_bytes = self._adc_frames_emitted * constants.DATA_PAYLOAD_BYTES
        gpio_payload_bytes = self._gpio_frames_emitted * constants.DATA_PAYLOAD_BYTES
        adc_framed_bytes = self._adc_frames_emitted * constants.DATA_FRAME_BYTES
        gpio_framed_bytes = self._gpio_frames_emitted * constants.DATA_FRAME_BYTES
        adc_frames_dropped = self._adc_items_dropped // constants.ADC_PAIRS_PER_FRAME
        gpio_frames_dropped = (
            self._gpio_items_dropped // constants.GPIO_SAMPLES_PER_FRAME
        )
        return Status(
            device_state=self._state,
            stream_mask=(
                configuration.stream_mask
                if configuration is not None
                else constants.StreamMask.NONE
            ),
            source=(
                configuration.source
                if configuration is not None
                else (
                    constants.Source.HARDWARE
                    if self._control_only
                    else constants.Source.SYNTHETIC
                )
            ),
            data_checksum_algorithm=(
                configuration.data_checksum_algorithm
                if configuration is not None
                else constants.DEFAULT_CHECKSUM_ALGORITHM
            ),
            adc_frames_emitted=self._adc_frames_emitted,
            gpio_frames_emitted=self._gpio_frames_emitted,
            adc_items_dropped=self._adc_items_dropped,
            gpio_items_dropped=self._gpio_items_dropped,
            parser_errors=(self._request_parser.errors - self._parser_error_baseline)
            & constants.UINT32_MAX,
            transport_errors=self._transport_errors,
            bad_request_ids=self._bad_request_ids,
            stats_generation=self._stats_generation,
            adc_frames_generated=self._adc_frames_emitted,
            adc_items_generated=adc_items,
            adc_frames_framed_pipeline=self._adc_frames_emitted,
            adc_items_framed_pipeline=adc_items,
            adc_items_emitted=adc_items,
            adc_frames_transmitted=self._adc_frames_emitted,
            adc_items_transmitted_pipeline=adc_items,
            adc_frames_dropped=adc_frames_dropped,
            gpio_frames_generated=self._gpio_frames_emitted,
            gpio_items_generated=gpio_items,
            gpio_frames_framed_pipeline=self._gpio_frames_emitted,
            gpio_items_framed_pipeline=gpio_items,
            gpio_items_emitted=gpio_items,
            gpio_frames_transmitted=self._gpio_frames_emitted,
            gpio_items_transmitted_pipeline=gpio_items,
            gpio_frames_dropped=gpio_frames_dropped,
            adc_payload_bytes_produced=adc_payload_bytes,
            adc_payload_bytes_framed=adc_payload_bytes,
            adc_payload_bytes_emitted=adc_payload_bytes,
            adc_payload_bytes_transmitted=adc_payload_bytes,
            adc_payload_bytes_dropped=(
                self._adc_items_dropped * constants.ADC_BYTES_PER_PAIR
            ),
            adc_framed_bytes_framed=adc_framed_bytes,
            adc_framed_bytes_emitted=adc_framed_bytes,
            adc_framed_bytes_transmitted=adc_framed_bytes,
            gpio_payload_bytes_produced=gpio_payload_bytes,
            gpio_payload_bytes_framed=gpio_payload_bytes,
            gpio_payload_bytes_emitted=gpio_payload_bytes,
            gpio_payload_bytes_transmitted=gpio_payload_bytes,
            gpio_payload_bytes_dropped=self._gpio_items_dropped,
            gpio_framed_bytes_framed=gpio_framed_bytes,
            gpio_framed_bytes_emitted=gpio_framed_bytes,
            gpio_framed_bytes_transmitted=gpio_framed_bytes,
            packet_frames_promoted=(
                self._adc_frames_emitted + self._gpio_frames_emitted
            ),
            data_payload_bytes_transmitted=(adc_payload_bytes + gpio_payload_bytes),
            data_framed_bytes_transmitted=(adc_framed_bytes + gpio_framed_bytes),
        )

    def _handle_frame(self, request: SimulatorRequest) -> bytes | None:
        try:
            request_kind = constants.FrameKind(int(request.header.kind))
        except ValueError:
            request_kind = None
        if request_kind not in constants.REQUEST_RESPONSE_KIND:
            if request.header.request_id == 0:
                return None
            return self._generic_error(
                request,
                constants.ErrorCode.UNKNOWN_FRAME_KIND,
            )
        if self._state is constants.DeviceState.BOOT:
            return self._typed_error(request, constants.ErrorCode.INVALID_STATE)
        if request.header.request_id in self._recent_request_ids:
            self._bad_request_ids = min(
                self._bad_request_ids + 1,
                constants.UINT32_MAX,
            )
            return self._typed_error(request, constants.ErrorCode.INVALID_REQUEST_ID)
        self._recent_request_ids.append(request.header.request_id)

        handlers = {
            constants.FrameKind.INFO_REQUEST: self._handle_info,
            constants.FrameKind.CONFIGURE_REQUEST: self._handle_configure,
            constants.FrameKind.START_REQUEST: self._handle_start,
            constants.FrameKind.GET_STATUS_REQUEST: self._handle_status,
            constants.FrameKind.STOP_REQUEST: self._handle_stop,
            constants.FrameKind.RESET_STATS_REQUEST: self._handle_reset_stats,
            constants.FrameKind.PING_REQUEST: self._handle_ping,
            constants.FrameKind.CHECKSUM_BENCHMARK_REQUEST: (
                self._handle_checksum_benchmark
            ),
            constants.FrameKind.GPIO_CLOCK_DIAGNOSTIC_REQUEST: (
                self._handle_gpio_clock_diagnostic
            ),
            constants.FrameKind.GPIO_CAPTURE_DIAGNOSTIC_REQUEST: (
                self._handle_gpio_capture_diagnostic
            ),
        }
        return handlers[request_kind](request)

    def _build_info(self) -> Info:
        """Build the exact INFO model advertised by this simulator."""

        if self._control_only:
            supported_stream_mask = constants.StreamMask.NONE
            supported_source_mask = 1 << int(constants.Source.HARDWARE)
            capability_bits = (
                constants.Capability.HARDWARE_SOURCE
                | constants.Capability.RESET_STATS
                | constants.Capability.PING
            )
            firmware_version = (0, 3, 0)
            supported_configuration_mask = constants.ConfigurationProfile.NONE
        else:
            supported_stream_mask = constants.StreamMask.ADC | constants.StreamMask.GPIO
            supported_source_mask = 1 << int(constants.Source.SYNTHETIC)
            capability_bits = (
                constants.Capability.ADC_STREAM
                | constants.Capability.GPIO_STREAM
                | constants.Capability.SYNTHETIC_SOURCE
                | constants.Capability.RESET_STATS
                | constants.Capability.PING
            )
            firmware_version = (0, 1, 0)
            supported_configuration_mask = (
                constants.ConfigurationProfile.SYNTHETIC_ADC
                | constants.ConfigurationProfile.SYNTHETIC_GPIO
                | constants.ConfigurationProfile.SYNTHETIC_COMBINED
            )
        configuration = self._configuration
        return Info(
            device_state=self._state,
            build_id=self._build_id,
            firmware_version=firmware_version,
            supported_stream_mask=supported_stream_mask,
            supported_source_mask=supported_source_mask,
            supported_configuration_mask=supported_configuration_mask,
            applied_stream_mask=(
                configuration.stream_mask
                if configuration is not None
                else constants.StreamMask.NONE
            ),
            applied_source=(
                configuration.source
                if configuration is not None
                else (
                    constants.Source.HARDWARE
                    if self._control_only
                    else constants.Source.SYNTHETIC
                )
            ),
            data_checksum_algorithm=self.status().data_checksum_algorithm,
            capability_bits=capability_bits,
        )

    def _handle_info(self, request: SimulatorRequest) -> bytes:
        return self._success_response(request, self._build_info().to_payload())

    def _decode_configuration(self, payload: bytes) -> Configuration:
        """Decode one configuration through the active protocol contract."""

        return Configuration.from_payload(payload)

    def _configuration_supported(self, configuration: Configuration) -> bool:
        """Return whether the simulator implements one validated profile."""

        if self._control_only:
            return configuration.is_control_only
        return (
            configuration.source is constants.Source.SYNTHETIC
            and configuration.stream_mask != constants.StreamMask.NONE
        )

    def _handle_configure(self, request: SimulatorRequest) -> bytes:
        if self._state not in {
            constants.DeviceState.IDLE,
            constants.DeviceState.CONFIGURED,
        }:
            return self._typed_error(request, constants.ErrorCode.INVALID_STATE)

        configuration = self._decode_configuration(request.payload)
        if not self._configuration_supported(configuration):
            return self._typed_error(
                request,
                constants.ErrorCode.UNSUPPORTED_CONFIGURATION,
            )
        if (
            configuration.data_checksum_algorithm
            not in constants.SUPPORTED_CHECKSUM_ALGORITHMS
        ):
            return self._typed_error(
                request,
                constants.ErrorCode.UNSUPPORTED_CHECKSUM,
            )

        self._configuration = configuration
        self._state = constants.DeviceState.CONFIGURED
        return self._success_response(
            request,
            _SUCCESS_PREFIX + configuration.to_payload(),
        )

    def _handle_start(self, request: SimulatorRequest) -> bytes:
        if (
            self._state is not constants.DeviceState.CONFIGURED
            or self._configuration is None
        ):
            return self._typed_error(request, constants.ErrorCode.INVALID_STATE)

        self._last_run_id = (self._last_run_id + 1) & constants.UINT32_MAX
        if self._last_run_id == 0:
            self._last_run_id = 1
        self._reset_epoch()
        self._state = constants.DeviceState.RUNNING
        return self._success_response(
            request,
            _SUCCESS_PREFIX + self._configuration.to_payload(),
            run_id=self._last_run_id,
        )

    def _handle_status(self, request: SimulatorRequest) -> bytes:
        return self._success_response(request, self.status().to_payload())

    def _handle_stop(self, request: SimulatorRequest) -> bytes:
        self._state = constants.DeviceState.IDLE
        self._configuration = None
        payload = bytearray(constants.STOP_RESPONSE_PAYLOAD_SIZE)
        payload[: len(_SUCCESS_PREFIX)] = _SUCCESS_PREFIX
        payload[constants.STOP_RESPONSE_DEVICE_STATE_OFFSET] = int(
            constants.DeviceState.IDLE
        )
        return self._success_response(request, payload)

    def _handle_reset_stats(self, request: SimulatorRequest) -> bytes:
        if self._state not in {
            constants.DeviceState.IDLE,
            constants.DeviceState.CONFIGURED,
        }:
            return self._typed_error(request, constants.ErrorCode.INVALID_STATE)
        self._reset_counters()
        payload = bytearray(constants.RESET_STATS_RESPONSE_PAYLOAD_SIZE)
        payload[: len(_SUCCESS_PREFIX)] = _SUCCESS_PREFIX
        struct.pack_into(
            "<I",
            payload,
            constants.RESET_STATS_RESPONSE_STATS_GENERATION_OFFSET,
            self._stats_generation,
        )
        return self._success_response(request, payload)

    def _handle_ping(self, request: SimulatorRequest) -> bytes:
        payload = bytearray(constants.PING_RESPONSE_PAYLOAD_SIZE)
        payload[: len(_SUCCESS_PREFIX)] = _SUCCESS_PREFIX
        payload[constants.PING_RESPONSE_NONCE_OFFSET :] = request.payload
        return self._success_response(request, payload)

    def _handle_checksum_benchmark(self, request: SimulatorRequest) -> bytes:
        # The offline simulator has no 600 MHz DWT or Teensy memory regions and
        # therefore deliberately does not advertise or fabricate this result.
        return self._typed_error(request, constants.ErrorCode.UNSUPPORTED_CONFIGURATION)

    def _handle_gpio_clock_diagnostic(self, request: SimulatorRequest) -> bytes:
        # The simulator has no PIT/XBARA/eDMA route and does not invent target
        # register snapshots or timing evidence.
        return self._typed_error(request, constants.ErrorCode.UNSUPPORTED_CONFIGURATION)

    def _handle_gpio_capture_diagnostic(self, request: SimulatorRequest) -> bytes:
        # The simulator intentionally does not claim physical capture evidence.
        return self._typed_error(request, constants.ErrorCode.UNSUPPORTED_CONFIGURATION)

    def _reset_epoch(self) -> None:
        self._adc_sequence = 0
        self._gpio_sequence = 0
        self._adc_first_ticks = 0
        self._gpio_first_ticks = 0
        self._adc_item_index = 0
        self._gpio_item_index = 0
        self._reset_counters()
        self._next_stream_index = 0

    def _reset_counters(self) -> None:
        self._adc_frames_emitted = 0
        self._gpio_frames_emitted = 0
        self._adc_items_dropped = 0
        self._gpio_items_dropped = 0
        self._parser_error_baseline = self._request_parser.errors
        self._transport_errors = 0
        self._bad_request_ids = 0
        self._stats_generation = (self._stats_generation + 1) & constants.UINT32_MAX
        if self._stats_generation == 0:
            self._stats_generation = 1

    def _next_adc_frame(self, configuration: Configuration) -> bytes:
        flags = constants.FrameFlag.SYNTHETIC
        if self._adc_sequence == 0 and self._adc_first_ticks == 0:
            flags |= constants.FrameFlag.EPOCH_START
        wire = self._encode_data_frame(
            constants.FrameKind.ADC_DATA,
            self._adc_payload(),
            configuration,
            flags=flags,
            run_id=self._last_run_id,
            sequence=self._adc_sequence,
            first_sample_ticks=self._adc_first_ticks,
        )
        self._adc_sequence = (self._adc_sequence + 1) & constants.UINT32_MAX
        self._adc_first_ticks = (
            self._adc_first_ticks + constants.FRAME_COVERAGE_TICKS
        ) & constants.UINT64_MAX
        self._adc_item_index += constants.ADC_PAIRS_PER_FRAME
        self._adc_frames_emitted = (self._adc_frames_emitted + 1) & constants.UINT64_MAX
        return wire

    def _next_gpio_frame(self, configuration: Configuration) -> bytes:
        flags = constants.FrameFlag.SYNTHETIC
        if self._gpio_sequence == 0 and self._gpio_first_ticks == 0:
            flags |= constants.FrameFlag.EPOCH_START
        wire = self._encode_data_frame(
            constants.FrameKind.GPIO_DATA,
            self._gpio_payload(),
            configuration,
            flags=flags,
            run_id=self._last_run_id,
            sequence=self._gpio_sequence,
            first_sample_ticks=self._gpio_first_ticks,
        )
        self._gpio_sequence = (self._gpio_sequence + 1) & constants.UINT32_MAX
        self._gpio_first_ticks = (
            self._gpio_first_ticks + constants.FRAME_COVERAGE_TICKS
        ) & constants.UINT64_MAX
        self._gpio_item_index += constants.GPIO_SAMPLES_PER_FRAME
        self._gpio_frames_emitted = (
            self._gpio_frames_emitted + 1
        ) & constants.UINT64_MAX
        return wire

    def _adc_payload(self) -> bytes:
        """Return the unchanged canonical protocol-v1 ADC formula payload."""

        return synthetic_adc_payload(self._adc_item_index)

    def _gpio_payload(self) -> bytes:
        """Return the unchanged canonical protocol-v1 GPIO formula payload."""

        return synthetic_gpio_payload(self._gpio_item_index)

    def _encode_data_frame(
        self,
        kind: constants.FrameKind,
        payload: bytes,
        configuration: Configuration,
        *,
        flags: constants.FrameFlag,
        run_id: int,
        sequence: int,
        first_sample_ticks: int,
    ) -> bytes:
        item_count = (
            constants.ADC_PAIRS_PER_FRAME
            if kind is constants.FrameKind.ADC_DATA
            else constants.GPIO_SAMPLES_PER_FRAME
        )
        return encode_frame(
            kind,
            payload,
            flags=flags,
            checksum_algorithm=configuration.data_checksum_algorithm,
            run_id=run_id,
            sequence=sequence,
            first_sample_ticks=first_sample_ticks,
            item_count=item_count,
        )

    def _encode_control_frame(
        self,
        kind: constants.FrameKind,
        payload: bytes | bytearray,
        *,
        flags: constants.FrameFlag = constants.FrameFlag.NONE,
        run_id: int = 0,
        request_id: int = 0,
    ) -> bytes:
        return encode_frame(
            kind,
            payload,
            flags=flags,
            run_id=run_id,
            request_id=request_id,
        )

    def _success_response(
        self,
        request: SimulatorRequest,
        payload: bytes | bytearray,
        *,
        run_id: int | None = None,
    ) -> bytes:
        request_kind = constants.FrameKind(int(request.header.kind))
        return self._encode_control_frame(
            constants.REQUEST_RESPONSE_KIND[request_kind],
            payload,
            run_id=self._last_run_id if run_id is None else run_id,
            request_id=request.header.request_id,
        )

    def _typed_error(
        self,
        request: SimulatorRequest,
        error: constants.ErrorCode,
    ) -> bytes:
        payload = _RESPONSE_PREFIX.pack(constants.ResponseStatus.ERROR, 0, error)
        request_kind = constants.FrameKind(int(request.header.kind))
        return self._encode_control_frame(
            constants.REQUEST_RESPONSE_KIND[request_kind],
            payload,
            flags=constants.FrameFlag.RESPONSE_ERROR,
            run_id=self._last_run_id,
            request_id=request.header.request_id,
        )

    def _generic_error(
        self,
        request: SimulatorRequest,
        error: constants.ErrorCode,
    ) -> bytes:
        payload = _ERROR_RESPONSE.pack(
            constants.ResponseStatus.ERROR,
            0,
            error,
            int(request.header.kind),
            getattr(request.header, "version", v2_constants.PROTOCOL_VERSION),
            0,
        )
        return self._encode_control_frame(
            constants.FrameKind.ERROR_RESPONSE,
            payload,
            flags=constants.FrameFlag.RESPONSE_ERROR,
            run_id=self._last_run_id,
            request_id=request.header.request_id,
        )

    def _busy_response(self, request: SimulatorRequest) -> bytes | None:
        try:
            request_kind = constants.FrameKind(int(request.header.kind))
        except ValueError:
            request_kind = None
        if request_kind in constants.REQUEST_RESPONSE_KIND:
            return self._typed_error(request, constants.ErrorCode.BUSY)
        if request.header.request_id:
            return self._generic_error(request, constants.ErrorCode.BUSY)
        return None


class ExperimentalSimulatedDevice(SimulatedDevice):
    """Explicit RAW/v2-RLE simulator with deterministic workload controls.

    ``SimulatedDevice`` remains the stable protocol-v1 formula peer.  This
    separate class is the only simulator surface that can select the
    experimental source patterns or advertise protocol-v2 ``RLE_STREAMING``.
    """

    def __init__(
        self,
        *,
        encoding: v2_constants.ConfigurationEncoding | int,
        adc_pattern: ExperimentalSourcePattern | str = (
            ExperimentalSourcePattern.CONSTANT
        ),
        gpio_pattern: ExperimentalSourcePattern | str = (
            ExperimentalSourcePattern.CONSTANT
        ),
        auto_boot: bool = True,
        max_receive_bytes: int = constants.MAX_CONTROL_FRAME_BYTES,
        max_requests_per_receive: int = 8,
    ) -> None:
        if isinstance(encoding, bool):
            raise TypeError("encoding must be RAW or RLE_AUTO")
        try:
            selected_encoding = v2_constants.ConfigurationEncoding(encoding)
        except (TypeError, ValueError) as error:
            raise ValueError("encoding must be RAW or RLE_AUTO") from error
        self._experimental_encoding = selected_encoding
        self._adc_pattern = _experimental_pattern(adc_pattern)
        self._gpio_pattern = _experimental_pattern(gpio_pattern)
        build_id = (
            "thingdaq-rle-simulator-v2"
            if selected_encoding is v2_constants.ConfigurationEncoding.RLE_AUTO
            else "thingdaq-rle-simulator-raw-v1"
        )
        super().__init__(
            auto_boot=auto_boot,
            build_id=build_id,
            max_receive_bytes=max_receive_bytes,
            max_requests_per_receive=max_requests_per_receive,
        )
        self._adc_encoded_payload_bytes = 0
        self._gpio_encoded_payload_bytes = 0
        self._adc_encoded_frame_bytes = 0
        self._gpio_encoded_frame_bytes = 0
        if selected_encoding is v2_constants.ConfigurationEncoding.RLE_AUTO:
            self._request_parser = IncrementalV2FrameParser()

    @property
    def encoding(self) -> v2_constants.ConfigurationEncoding:
        """Protocol/configuration encoding accepted by this experimental peer."""

        return self._experimental_encoding

    @property
    def adc_pattern(self) -> ExperimentalSourcePattern:
        """Exact deterministic ADC workload selected for every run."""

        return self._adc_pattern

    @property
    def gpio_pattern(self) -> ExperimentalSourcePattern:
        """Exact deterministic GPIO workload selected for every run."""

        return self._gpio_pattern

    def _build_info(self) -> Info:
        info = super()._build_info()
        if self._experimental_encoding is v2_constants.ConfigurationEncoding.RAW:
            return info
        capability_bits = v2_constants.Capability(
            int(info.capability_bits) | int(v2_constants.Capability.RLE_STREAMING)
        )
        return replace(
            info,
            firmware_version=(0, 2, 0),
            protocol_version=v2_constants.PROTOCOL_VERSION,
            capability_bits=capability_bits,
            max_control_frame_bytes=v2_constants.MAX_CONTROL_FRAME_BYTES,
            configuration_encoding=(
                self._configuration.encoding
                if self._configuration is not None
                else v2_constants.ConfigurationEncoding.RAW
            ),
        )

    def _decode_configuration(self, payload: bytes) -> Configuration:
        if self._experimental_encoding is v2_constants.ConfigurationEncoding.RAW:
            return super()._decode_configuration(payload)
        return Configuration.from_payload(
            payload,
            protocol_version=v2_constants.PROTOCOL_VERSION,
        )

    def _configuration_supported(self, configuration: Configuration) -> bool:
        return (
            super()._configuration_supported(configuration)
            and configuration.encoding is self._experimental_encoding
        )

    def _adc_payload(self) -> bytes:
        return experimental_adc_payload(self._adc_pattern, self._adc_item_index)

    def _gpio_payload(self) -> bytes:
        return experimental_gpio_payload(self._gpio_pattern, self._gpio_item_index)

    def _encode_data_frame(
        self,
        kind: constants.FrameKind,
        payload: bytes,
        configuration: Configuration,
        *,
        flags: constants.FrameFlag,
        run_id: int,
        sequence: int,
        first_sample_ticks: int,
    ) -> bytes:
        if self._experimental_encoding is v2_constants.ConfigurationEncoding.RAW:
            return super()._encode_data_frame(
                kind,
                payload,
                configuration,
                flags=flags,
                run_id=run_id,
                sequence=sequence,
                first_sample_ticks=first_sample_ticks,
            )
        wire = encode_v2_data_frame(
            kind,
            payload,
            configuration_encoding=configuration.encoding,
            flags=flags,
            checksum_algorithm=configuration.data_checksum_algorithm,
            run_id=run_id,
            sequence=sequence,
            first_sample_ticks=first_sample_ticks,
        )
        encoded_payload_bytes = (
            len(wire) - v2_constants.HEADER_SIZE - v2_constants.TRAILER_SIZE
        )
        if kind is constants.FrameKind.ADC_DATA:
            self._adc_encoded_payload_bytes += encoded_payload_bytes
            self._adc_encoded_frame_bytes += len(wire)
        else:
            self._gpio_encoded_payload_bytes += encoded_payload_bytes
            self._gpio_encoded_frame_bytes += len(wire)
        return wire

    def _encode_control_frame(
        self,
        kind: constants.FrameKind,
        payload: bytes | bytearray,
        *,
        flags: constants.FrameFlag = constants.FrameFlag.NONE,
        run_id: int = 0,
        request_id: int = 0,
    ) -> bytes:
        if self._experimental_encoding is v2_constants.ConfigurationEncoding.RAW:
            return super()._encode_control_frame(
                kind,
                payload,
                flags=flags,
                run_id=run_id,
                request_id=request_id,
            )
        if (
            kind is constants.FrameKind.GET_STATUS_RESPONSE
            and not flags & constants.FrameFlag.RESPONSE_ERROR
        ):
            extended = bytearray(payload)
            extended.extend(
                bytes(v2_constants.STATUS_RESPONSE_PAYLOAD_SIZE - len(extended))
            )
            extended[v2_constants.STATUS_RESPONSE_CONFIGURATION_ENCODING_OFFSET] = int(
                self._experimental_encoding
            )
            struct.pack_into(
                "<Q",
                extended,
                v2_constants.STATUS_RESPONSE_ADC_ENCODED_PAYLOAD_BYTES_FRAMED_OFFSET,
                self._adc_encoded_payload_bytes,
            )
            struct.pack_into(
                "<Q",
                extended,
                v2_constants.STATUS_RESPONSE_ADC_ENCODED_PAYLOAD_BYTES_TRANSMITTED_OFFSET,
                self._adc_encoded_payload_bytes,
            )
            struct.pack_into(
                "<Q",
                extended,
                v2_constants.STATUS_RESPONSE_GPIO_ENCODED_PAYLOAD_BYTES_FRAMED_OFFSET,
                self._gpio_encoded_payload_bytes,
            )
            struct.pack_into(
                "<Q",
                extended,
                v2_constants.STATUS_RESPONSE_GPIO_ENCODED_PAYLOAD_BYTES_TRANSMITTED_OFFSET,
                self._gpio_encoded_payload_bytes,
            )
            payload = extended
        return encode_v2_frame(
            kind,
            payload,
            flags=flags,
            run_id=run_id,
            request_id=request_id,
        )

    def _reset_counters(self) -> None:
        super()._reset_counters()
        self._adc_encoded_payload_bytes = 0
        self._gpio_encoded_payload_bytes = 0
        self._adc_encoded_frame_bytes = 0
        self._gpio_encoded_frame_bytes = 0

    def status(self) -> Status:
        status = super().status()
        if self._experimental_encoding is v2_constants.ConfigurationEncoding.RAW:
            return status
        return replace(
            status,
            adc_payload_bytes_framed=self._adc_encoded_payload_bytes,
            adc_payload_bytes_emitted=self._adc_encoded_payload_bytes,
            adc_payload_bytes_transmitted=self._adc_encoded_payload_bytes,
            adc_framed_bytes_framed=self._adc_encoded_frame_bytes,
            adc_framed_bytes_emitted=self._adc_encoded_frame_bytes,
            adc_framed_bytes_transmitted=self._adc_encoded_frame_bytes,
            gpio_payload_bytes_framed=self._gpio_encoded_payload_bytes,
            gpio_payload_bytes_emitted=self._gpio_encoded_payload_bytes,
            gpio_payload_bytes_transmitted=self._gpio_encoded_payload_bytes,
            gpio_framed_bytes_framed=self._gpio_encoded_frame_bytes,
            gpio_framed_bytes_emitted=self._gpio_encoded_frame_bytes,
            gpio_framed_bytes_transmitted=self._gpio_encoded_frame_bytes,
            data_payload_bytes_transmitted=(
                self._adc_encoded_payload_bytes + self._gpio_encoded_payload_bytes
            ),
            data_framed_bytes_transmitted=(
                self._adc_encoded_frame_bytes + self._gpio_encoded_frame_bytes
            ),
        )

    def validate_block(self, block: ADCBlock | GPIOBlock) -> None:
        """Validate one decoded block against this device's exact workload."""

        if not block.flags & constants.FrameFlag.SYNTHETIC:
            raise SyntheticPatternError(
                "experimental simulator block is missing the SYNTHETIC flag"
            )
        if isinstance(block, ADCBlock):
            expected = experimental_adc_payload(
                self._adc_pattern,
                block.first_pair_index,
            )
            label = "ADC"
        elif isinstance(block, GPIOBlock):
            expected = experimental_gpio_payload(
                self._gpio_pattern,
                block.first_sample_index,
            )
            label = "GPIO"
        else:  # pragma: no cover - public type boundary
            raise TypeError("experimental validation requires an ADC or GPIO block")
        if block.payload != expected:
            raise SyntheticPatternError(
                f"{label} payload differs from experimental source pattern"
            )


__all__ = [
    "ExperimentalSimulatedDevice",
    "ExperimentalSourcePattern",
    "SimulatedDevice",
    "SimulatorError",
    "SimulatorInputError",
    "experimental_adc_payload",
    "experimental_gpio_payload",
]
