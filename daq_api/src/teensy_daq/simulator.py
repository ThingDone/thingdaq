"""Deterministic protocol-v1 device used by the in-memory transport."""

from __future__ import annotations

import struct

from ._generated import protocol_constants as constants
from .models import Configuration, Info, Status
from .protocol import Frame, IncrementalFrameParser, encode_frame
from .synthetic import synthetic_adc_payload, synthetic_gpio_payload

_RESPONSE_PREFIX = struct.Struct("<BBH")
_ERROR_RESPONSE = struct.Struct("<BBHBBH")
_SUCCESS_PREFIX = _RESPONSE_PREFIX.pack(
    constants.ResponseStatus.OK,
    0,
    constants.ErrorCode.OK,
)


class SimulatorError(RuntimeError):
    """Base error raised by the deterministic simulated device."""


class SimulatorInputError(SimulatorError):
    """A caller supplied more input than one bounded receive operation allows."""


class SimulatedDevice:
    """A bounded, deterministic Teensy DAQ protocol peer.

    The simulator consumes the same encoded request frames that future firmware
    will consume and produces ordinary encoded response/data frames.  It starts
    in ``BOOT`` and completes its bounded boot synchronously by default.
    """

    def __init__(
        self,
        *,
        auto_boot: bool = True,
        build_id: str = "teensy-daq-simulator-v1",
        max_receive_bytes: int = constants.MAX_CONTROL_FRAME_BYTES,
        max_requests_per_receive: int = 8,
    ) -> None:
        if max_receive_bytes < constants.MIN_FRAME_BYTES:
            raise ValueError("max_receive_bytes must hold at least one frame")
        if max_requests_per_receive <= 0:
            raise ValueError("max_requests_per_receive must be positive")
        # Validate build identity through the public model once at construction.
        Info(device_state=constants.DeviceState.IDLE, build_id=build_id)

        self._build_id = build_id
        self._max_receive_bytes = max_receive_bytes
        self._max_requests_per_receive = max_requests_per_receive
        self._request_parser = IncrementalFrameParser()
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
        self._stats_generation = 1
        self._next_stream_index = 0
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
        kind = streams[self._next_stream_index % len(streams)]
        self._next_stream_index = (self._next_stream_index + 1) % len(streams)

        if kind is constants.FrameKind.ADC_DATA:
            return self._next_adc_frame(configuration)
        return self._next_gpio_frame(configuration)

    def status(self) -> Status:
        """Return the current status model without going through the wire."""

        configuration = self._configuration
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
                else constants.Source.SYNTHETIC
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
            stats_generation=self._stats_generation,
        )

    def _handle_frame(self, request: Frame) -> bytes | None:
        if request.header.kind not in constants.REQUEST_RESPONSE_KIND:
            if request.header.request_id == 0:
                return None
            return self._generic_error(
                request,
                constants.ErrorCode.UNKNOWN_FRAME_KIND,
            )
        if self._state is constants.DeviceState.BOOT:
            return self._typed_error(request, constants.ErrorCode.INVALID_STATE)

        handlers = {
            constants.FrameKind.INFO_REQUEST: self._handle_info,
            constants.FrameKind.CONFIGURE_REQUEST: self._handle_configure,
            constants.FrameKind.START_REQUEST: self._handle_start,
            constants.FrameKind.GET_STATUS_REQUEST: self._handle_status,
            constants.FrameKind.STOP_REQUEST: self._handle_stop,
            constants.FrameKind.RESET_STATS_REQUEST: self._handle_reset_stats,
            constants.FrameKind.PING_REQUEST: self._handle_ping,
        }
        return handlers[request.header.kind](request)

    def _handle_info(self, request: Frame) -> bytes:
        info = Info(
            device_state=self._state,
            build_id=self._build_id,
            firmware_version=(0, 1, 0),
            supported_source_mask=1 << int(constants.Source.SYNTHETIC),
            capability_bits=(
                constants.Capability.ADC_STREAM
                | constants.Capability.GPIO_STREAM
                | constants.Capability.SYNTHETIC_SOURCE
                | constants.Capability.RESET_STATS
                | constants.Capability.PING
            ),
        )
        return self._success_response(request, info.to_payload())

    def _handle_configure(self, request: Frame) -> bytes:
        if self._state not in {
            constants.DeviceState.IDLE,
            constants.DeviceState.CONFIGURED,
        }:
            return self._typed_error(request, constants.ErrorCode.INVALID_STATE)

        configuration = Configuration.from_payload(request.payload)
        if configuration.source is not constants.Source.SYNTHETIC:
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

    def _handle_start(self, request: Frame) -> bytes:
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

    def _handle_status(self, request: Frame) -> bytes:
        return self._success_response(request, self.status().to_payload())

    def _handle_stop(self, request: Frame) -> bytes:
        self._state = constants.DeviceState.IDLE
        self._configuration = None
        payload = bytearray(constants.STOP_RESPONSE_PAYLOAD_SIZE)
        payload[: len(_SUCCESS_PREFIX)] = _SUCCESS_PREFIX
        payload[constants.STOP_RESPONSE_DEVICE_STATE_OFFSET] = int(
            constants.DeviceState.IDLE
        )
        return self._success_response(request, payload)

    def _handle_reset_stats(self, request: Frame) -> bytes:
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

    def _handle_ping(self, request: Frame) -> bytes:
        payload = bytearray(constants.PING_RESPONSE_PAYLOAD_SIZE)
        payload[: len(_SUCCESS_PREFIX)] = _SUCCESS_PREFIX
        payload[constants.PING_RESPONSE_NONCE_OFFSET :] = request.payload
        return self._success_response(request, payload)

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
        self._stats_generation = (self._stats_generation + 1) & constants.UINT32_MAX
        if self._stats_generation == 0:
            self._stats_generation = 1

    def _next_adc_frame(self, configuration: Configuration) -> bytes:
        flags = constants.FrameFlag.SYNTHETIC
        if self._adc_sequence == 0 and self._adc_first_ticks == 0:
            flags |= constants.FrameFlag.EPOCH_START
        wire = encode_frame(
            constants.FrameKind.ADC_DATA,
            synthetic_adc_payload(self._adc_item_index),
            flags=flags,
            checksum_algorithm=configuration.data_checksum_algorithm,
            run_id=self._last_run_id,
            sequence=self._adc_sequence,
            first_sample_ticks=self._adc_first_ticks,
            item_count=constants.ADC_PAIRS_PER_FRAME,
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
        wire = encode_frame(
            constants.FrameKind.GPIO_DATA,
            synthetic_gpio_payload(self._gpio_item_index),
            flags=flags,
            checksum_algorithm=configuration.data_checksum_algorithm,
            run_id=self._last_run_id,
            sequence=self._gpio_sequence,
            first_sample_ticks=self._gpio_first_ticks,
            item_count=constants.GPIO_SAMPLES_PER_FRAME,
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

    def _success_response(
        self,
        request: Frame,
        payload: bytes | bytearray,
        *,
        run_id: int | None = None,
    ) -> bytes:
        return encode_frame(
            constants.REQUEST_RESPONSE_KIND[request.header.kind],
            payload,
            run_id=self._last_run_id if run_id is None else run_id,
            request_id=request.header.request_id,
        )

    def _typed_error(self, request: Frame, error: constants.ErrorCode) -> bytes:
        payload = _RESPONSE_PREFIX.pack(constants.ResponseStatus.ERROR, 0, error)
        return encode_frame(
            constants.REQUEST_RESPONSE_KIND[request.header.kind],
            payload,
            flags=constants.FrameFlag.RESPONSE_ERROR,
            run_id=self._last_run_id,
            request_id=request.header.request_id,
        )

    def _generic_error(self, request: Frame, error: constants.ErrorCode) -> bytes:
        payload = _ERROR_RESPONSE.pack(
            constants.ResponseStatus.ERROR,
            0,
            error,
            int(request.header.kind),
            request.header.version,
            0,
        )
        return encode_frame(
            constants.FrameKind.ERROR_RESPONSE,
            payload,
            flags=constants.FrameFlag.RESPONSE_ERROR,
            run_id=self._last_run_id,
            request_id=request.header.request_id,
        )

    def _busy_response(self, request: Frame) -> bytes | None:
        if request.header.kind in constants.REQUEST_RESPONSE_KIND:
            return self._typed_error(request, constants.ErrorCode.BUSY)
        if request.header.request_id:
            return self._generic_error(request, constants.ErrorCode.BUSY)
        return None


__all__ = [
    "SimulatedDevice",
    "SimulatorError",
    "SimulatorInputError",
]
