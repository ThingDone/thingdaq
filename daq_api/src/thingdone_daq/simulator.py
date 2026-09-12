"""Deterministic v1/v2 device used by the in-memory transport."""

from __future__ import annotations

import struct
from collections import deque

from ._generated import protocol_constants as constants
from ._generated import protocol_v2_constants as v2_constants
from .models import (
    AdcTriggerMetadata,
    AuxiliaryInputMetadata,
    Configuration,
    GPIOLayout,
    Info,
    RateProfileTiming,
    Status,
)
from .protocol import encode_frame
from .protocol_v2 import (
    CompatibleFrame,
    IncrementalCompatibleFrameParser,
    encode_v2_frame,
)
from .synthetic import (
    SyntheticGPIOPattern,
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
        gpio_pattern: SyntheticGPIOPattern | str = SyntheticGPIOPattern.COUNTER,
    ) -> None:
        if max_receive_bytes < constants.MIN_FRAME_BYTES:
            raise ValueError("max_receive_bytes must hold at least one frame")
        if max_requests_per_receive <= 0:
            raise ValueError("max_requests_per_receive must be positive")
        if not isinstance(control_only, bool):
            raise TypeError("control_only must be a boolean")
        try:
            selected_gpio_pattern = SyntheticGPIOPattern(gpio_pattern)
        except (TypeError, ValueError) as exc:
            raise ValueError("unknown synthetic GPIO pattern") from exc
        # Validate build identity through the public model once at construction.
        Info(device_state=constants.DeviceState.IDLE, build_id=build_id)

        self._build_id = build_id
        self._control_only = control_only
        self._max_receive_bytes = max_receive_bytes
        self._max_requests_per_receive = max_requests_per_receive
        self._request_parser = IncrementalCompatibleFrameParser()
        self._gpio_pattern = selected_gpio_pattern
        self._state = constants.DeviceState.BOOT
        self._configuration: Configuration | None = None
        self._counter_configuration: Configuration | None = None
        self._wire_protocol_version = constants.PROTOCOL_VERSION
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

        requests = self._request_parser.feed(incoming)
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
        counter_configuration = self._counter_configuration
        layout = GPIOLayout.from_mode(
            counter_configuration.aux_bank_mode
            if counter_configuration is not None
            else v2_constants.DEFAULT_AUX_BANK_MODE
        )
        metadata_configuration = configuration or counter_configuration
        profile = (
            metadata_configuration.rate_profile
            if metadata_configuration is not None
            else v2_constants.DEFAULT_RATE_PROFILE
        )
        adc_items = self._adc_frames_emitted * layout.adc_items_per_frame
        gpio_items = self._gpio_frames_emitted * layout.items_per_frame
        adc_payload_bytes = self._adc_frames_emitted * layout.adc_payload_bytes
        gpio_payload_bytes = self._gpio_frames_emitted * layout.payload_bytes
        adc_framed_bytes = self._adc_frames_emitted * layout.adc_total_frame_bytes
        gpio_framed_bytes = self._gpio_frames_emitted * layout.total_frame_bytes
        adc_frames_dropped = self._adc_items_dropped // layout.adc_items_per_frame
        gpio_frames_dropped = self._gpio_items_dropped // layout.items_per_frame
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
            gpio_payload_bytes_dropped=(self._gpio_items_dropped * layout.item_bytes),
            gpio_framed_bytes_framed=gpio_framed_bytes,
            gpio_framed_bytes_emitted=gpio_framed_bytes,
            gpio_framed_bytes_transmitted=gpio_framed_bytes,
            packet_frames_promoted=(
                self._adc_frames_emitted + self._gpio_frames_emitted
            ),
            data_payload_bytes_transmitted=(adc_payload_bytes + gpio_payload_bytes),
            data_framed_bytes_transmitted=(adc_framed_bytes + gpio_framed_bytes),
            adc_trigger=AdcTriggerMetadata.for_rate_profile(profile),
            configuration=configuration,
        )

    def _handle_frame(self, request: CompatibleFrame) -> bytes | None:
        diagnostic_request = (
            request.header.version == v2_constants.PROTOCOL_VERSION
            and request.header.kind
            in {
                v2_constants.FrameKind.GET_TEMPERATURE_REQUEST,
                v2_constants.FrameKind.GET_RUNTIME_HEALTH_REQUEST,
            }
        )
        try:
            request_kind = constants.FrameKind(int(request.header.kind))
        except ValueError:
            request_kind = None
        if (
            not diagnostic_request
            and request_kind not in constants.REQUEST_RESPONSE_KIND
        ):
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
        if diagnostic_request:
            # No physical sensor, target stack, watchdog, or reset register.
            response_kind = v2_constants.REQUEST_RESPONSE_KIND[
                v2_constants.FrameKind(int(request.header.kind))
            ]
            payload = (
                struct.pack("<BBHBBHi", 0, 0, 0, 1, 0, 0, 0)
                if response_kind is v2_constants.FrameKind.GET_TEMPERATURE_RESPONSE
                else bytes(v2_constants.RUNTIME_HEALTH_RESPONSE_PAYLOAD_SIZE)
            )
            return encode_v2_frame(
                response_kind,
                payload,
                request_id=request.header.request_id,
                run_id=self._last_run_id,
            )

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
        return handlers[constants.FrameKind(int(request.header.kind))](request)

    def _handle_info(self, request: CompatibleFrame) -> bytes:
        use_v2 = request.header.version == v2_constants.PROTOCOL_VERSION
        if use_v2 and self._control_only:
            return self._typed_error(
                request,
                constants.ErrorCode.UNSUPPORTED_CONFIGURATION,
            )
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
        if use_v2 and configuration is not None:
            mode = configuration.aux_bank_mode
            profile = configuration.rate_profile
        else:
            mode = v2_constants.DEFAULT_AUX_BANK_MODE
            profile = v2_constants.DEFAULT_RATE_PROFILE
        timing = RateProfileTiming.from_profile(profile)
        layout = GPIOLayout.from_mode(mode)
        auxiliary = None
        if use_v2:
            capability_bits = constants.Capability(
                int(capability_bits)
                | int(v2_constants.Capability.AUXILIARY_INPUT_BANK)
                | int(v2_constants.Capability.EXACT_RATE_PROFILES)
            )
            auxiliary = AuxiliaryInputMetadata(
                selected_rate_profile=profile,
                applied_aux_bank_mode=mode,
                gpio_item_bytes=layout.item_bytes,
            )
        info = Info(
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
            protocol_version=(
                v2_constants.PROTOCOL_VERSION if use_v2 else constants.PROTOCOL_VERSION
            ),
            max_control_frame_bytes=(
                v2_constants.MAX_CONTROL_FRAME_BYTES
                if use_v2
                else constants.MAX_CONTROL_FRAME_BYTES
            ),
            adc_pair_rate_hz=timing.adc_pair_rate_hz,
            gpio_sample_rate_hz=timing.gpio_sample_rate_hz,
            adc_pair_period_ticks=timing.adc_pair_period_ticks,
            adc1_phase_ticks=timing.adc1_phase_ticks,
            gpio_sample_period_ticks=timing.gpio_sample_period_ticks,
            adc_trigger=AdcTriggerMetadata.for_rate_profile(profile),
            gpio_packed_width_bits=layout.packed_width_bits,
            gpio_raw_samples_per_buffer=layout.items_per_frame,
            gpio_raw_ring_bytes=(
                layout.items_per_frame
                * v2_constants.GPIO_RAW_WORD_BYTES_PER_BANK
                * constants.GPIO_RAW_RING_DEPTH
            ),
            gpio_edma_priority=(1 if mode is v2_constants.AuxBankMode.INPUT else 0),
            data_payload_bytes=layout.adc_payload_bytes,
            adc_pairs_per_frame=layout.adc_items_per_frame,
            gpio_samples_per_frame=layout.items_per_frame,
            frame_coverage_ticks=timing.frame_coverage_ticks(mode),
            adc_edma_priorities=(
                (3, 2)
                if mode is v2_constants.AuxBankMode.INPUT
                else constants.ADC_EDMA_PRIORITIES
            ),
            adc_pairs_per_buffer=layout.adc_items_per_frame,
            adc_dma_ring_bytes=(
                ((layout.adc_payload_bytes + 31) // 32)
                * 32
                * constants.ADC_DMA_RING_DEPTH
            ),
            auxiliary=auxiliary,
        )
        return self._success_response(request, info.to_payload())

    def _handle_configure(self, request: CompatibleFrame) -> bytes:
        if self._state not in {
            constants.DeviceState.IDLE,
            constants.DeviceState.CONFIGURED,
        }:
            return self._typed_error(request, constants.ErrorCode.INVALID_STATE)

        configuration = Configuration.from_payload(request.payload)
        if configuration.protocol_version > request.header.version:
            return self._typed_error(
                request,
                constants.ErrorCode.UNSUPPORTED_CONFIGURATION,
            )
        if self._control_only:
            supported_configuration = configuration.is_control_only
        else:
            supported_configuration = (
                configuration.source is constants.Source.SYNTHETIC
                and configuration.stream_mask != constants.StreamMask.NONE
            )
        if not supported_configuration:
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
        self._wire_protocol_version = request.header.version
        self._state = constants.DeviceState.CONFIGURED
        return self._success_response(
            request,
            _SUCCESS_PREFIX
            + configuration.to_payload(protocol_version=request.header.version),
        )

    def _handle_start(self, request: CompatibleFrame) -> bytes:
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
            _SUCCESS_PREFIX
            + self._configuration.to_payload(
                protocol_version=self._wire_protocol_version
            ),
            run_id=self._last_run_id,
        )

    def _handle_status(self, request: CompatibleFrame) -> bytes:
        return self._success_response(
            request,
            self.status().to_payload(protocol_version=request.header.version),
        )

    def _handle_stop(self, request: CompatibleFrame) -> bytes:
        self._state = constants.DeviceState.IDLE
        self._configuration = None
        self._wire_protocol_version = constants.PROTOCOL_VERSION
        payload = bytearray(constants.STOP_RESPONSE_PAYLOAD_SIZE)
        payload[: len(_SUCCESS_PREFIX)] = _SUCCESS_PREFIX
        payload[constants.STOP_RESPONSE_DEVICE_STATE_OFFSET] = int(
            constants.DeviceState.IDLE
        )
        return self._success_response(request, payload)

    def _handle_reset_stats(self, request: CompatibleFrame) -> bytes:
        if self._state not in {
            constants.DeviceState.IDLE,
            constants.DeviceState.CONFIGURED,
        }:
            return self._typed_error(request, constants.ErrorCode.INVALID_STATE)
        self._counter_configuration = self._configuration
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

    def _handle_ping(self, request: CompatibleFrame) -> bytes:
        payload = bytearray(constants.PING_RESPONSE_PAYLOAD_SIZE)
        payload[: len(_SUCCESS_PREFIX)] = _SUCCESS_PREFIX
        payload[constants.PING_RESPONSE_NONCE_OFFSET :] = request.payload
        return self._success_response(request, payload)

    def _handle_checksum_benchmark(self, request: CompatibleFrame) -> bytes:
        # The offline simulator has no 600 MHz DWT or Teensy memory regions and
        # therefore deliberately does not advertise or fabricate this result.
        return self._typed_error(request, constants.ErrorCode.UNSUPPORTED_CONFIGURATION)

    def _handle_gpio_clock_diagnostic(self, request: CompatibleFrame) -> bytes:
        # The simulator has no PIT/XBARA/eDMA route and does not invent target
        # register snapshots or timing evidence.
        return self._typed_error(request, constants.ErrorCode.UNSUPPORTED_CONFIGURATION)

    def _handle_gpio_capture_diagnostic(self, request: CompatibleFrame) -> bytes:
        # The simulator intentionally does not claim physical capture evidence.
        return self._typed_error(request, constants.ErrorCode.UNSUPPORTED_CONFIGURATION)

    def _reset_epoch(self) -> None:
        self._adc_sequence = 0
        self._gpio_sequence = 0
        self._adc_first_ticks = 0
        self._gpio_first_ticks = 0
        self._adc_item_index = 0
        self._gpio_item_index = 0
        self._counter_configuration = self._configuration
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
        layout = configuration.gpio_layout
        timing = configuration.rate_timing
        payload = synthetic_adc_payload(
            self._adc_item_index,
            layout.adc_items_per_frame,
        )
        wire = self._encode_data_frame(
            constants.FrameKind.ADC_DATA,
            payload,
            flags,
            configuration,
            self._adc_sequence,
            self._adc_first_ticks,
            layout.adc_items_per_frame,
        )
        self._adc_sequence = (self._adc_sequence + 1) & constants.UINT32_MAX
        self._adc_first_ticks = (
            self._adc_first_ticks
            + timing.frame_coverage_ticks(configuration.aux_bank_mode)
        ) & constants.UINT64_MAX
        self._adc_item_index += layout.adc_items_per_frame
        self._adc_frames_emitted = (self._adc_frames_emitted + 1) & constants.UINT64_MAX
        return wire

    def _next_gpio_frame(self, configuration: Configuration) -> bytes:
        flags = constants.FrameFlag.SYNTHETIC
        if self._gpio_sequence == 0 and self._gpio_first_ticks == 0:
            flags |= constants.FrameFlag.EPOCH_START
        layout = configuration.gpio_layout
        timing = configuration.rate_timing
        payload = synthetic_gpio_payload(
            self._gpio_item_index,
            layout.items_per_frame,
            aux_bank_mode=configuration.aux_bank_mode,
            pattern=self._gpio_pattern,
        )
        wire = self._encode_data_frame(
            constants.FrameKind.GPIO_DATA,
            payload,
            flags,
            configuration,
            self._gpio_sequence,
            self._gpio_first_ticks,
            layout.items_per_frame,
        )
        self._gpio_sequence = (self._gpio_sequence + 1) & constants.UINT32_MAX
        self._gpio_first_ticks = (
            self._gpio_first_ticks
            + layout.items_per_frame * timing.gpio_sample_period_ticks
        ) & constants.UINT64_MAX
        self._gpio_item_index += layout.items_per_frame
        self._gpio_frames_emitted = (
            self._gpio_frames_emitted + 1
        ) & constants.UINT64_MAX
        return wire

    def _encode_data_frame(
        self,
        kind: constants.FrameKind,
        payload: bytes,
        flags: constants.FrameFlag,
        configuration: Configuration,
        sequence: int,
        first_sample_ticks: int,
        item_count: int,
    ) -> bytes:
        arguments = {
            "flags": int(flags),
            "checksum_algorithm": int(configuration.data_checksum_algorithm),
            "run_id": self._last_run_id,
            "sequence": sequence,
            "first_sample_ticks": first_sample_ticks,
            "item_count": item_count,
        }
        if self._wire_protocol_version == v2_constants.PROTOCOL_VERSION:
            return encode_v2_frame(
                v2_constants.FrameKind(int(kind)),
                payload,
                **arguments,
            )
        return encode_frame(kind, payload, **arguments)

    def _success_response(
        self,
        request: CompatibleFrame,
        payload: bytes | bytearray,
        *,
        run_id: int | None = None,
    ) -> bytes:
        request_kind = constants.FrameKind(int(request.header.kind))
        response_kind = constants.REQUEST_RESPONSE_KIND[request_kind]
        arguments = {
            "run_id": self._last_run_id if run_id is None else run_id,
            "request_id": request.header.request_id,
        }
        if request.header.version == v2_constants.PROTOCOL_VERSION:
            return encode_v2_frame(
                v2_constants.FrameKind(int(response_kind)),
                payload,
                **arguments,
            )
        return encode_frame(response_kind, payload, **arguments)

    def _typed_error(
        self,
        request: CompatibleFrame,
        error: constants.ErrorCode,
    ) -> bytes:
        payload = _RESPONSE_PREFIX.pack(constants.ResponseStatus.ERROR, 0, error)
        response_kind = (
            v2_constants.REQUEST_RESPONSE_KIND[
                v2_constants.FrameKind(int(request.header.kind))
            ]
            if request.header.version == v2_constants.PROTOCOL_VERSION
            else constants.REQUEST_RESPONSE_KIND[
                constants.FrameKind(int(request.header.kind))
            ]
        )
        if request.header.version == v2_constants.PROTOCOL_VERSION:
            return encode_v2_frame(
                v2_constants.FrameKind(int(response_kind)),
                payload,
                flags=v2_constants.FrameFlag.RESPONSE_ERROR,
                run_id=self._last_run_id,
                request_id=request.header.request_id,
            )
        return encode_frame(
            constants.FrameKind(int(response_kind)),
            payload,
            flags=constants.FrameFlag.RESPONSE_ERROR,
            run_id=self._last_run_id,
            request_id=request.header.request_id,
        )

    def _generic_error(
        self,
        request: CompatibleFrame,
        error: constants.ErrorCode,
    ) -> bytes:
        payload = _ERROR_RESPONSE.pack(
            constants.ResponseStatus.ERROR,
            0,
            error,
            int(request.header.kind),
            request.header.version,
            0,
        )
        if request.header.version == v2_constants.PROTOCOL_VERSION:
            return encode_v2_frame(
                v2_constants.FrameKind.ERROR_RESPONSE,
                payload,
                flags=v2_constants.FrameFlag.RESPONSE_ERROR,
                run_id=self._last_run_id,
                request_id=request.header.request_id,
            )
        return encode_frame(
            constants.FrameKind.ERROR_RESPONSE,
            payload,
            flags=constants.FrameFlag.RESPONSE_ERROR,
            run_id=self._last_run_id,
            request_id=request.header.request_id,
        )

    def _busy_response(self, request: CompatibleFrame) -> bytes | None:
        try:
            kind = constants.FrameKind(int(request.header.kind))
        except ValueError:
            kind = None
        if kind in constants.REQUEST_RESPONSE_KIND:
            return self._typed_error(request, constants.ErrorCode.BUSY)
        if request.header.request_id:
            return self._generic_error(request, constants.ErrorCode.BUSY)
        return None


__all__ = [
    "SimulatedDevice",
    "SimulatorError",
    "SimulatorInputError",
]
