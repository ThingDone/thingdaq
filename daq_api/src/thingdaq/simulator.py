"""Deterministic protocol device used by the in-memory transport."""

from __future__ import annotations

import struct
import zlib
from collections import deque
from collections.abc import Iterable
from dataclasses import dataclass
from enum import Enum

from ._generated import protocol_constants as constants
from ._generated import protocol_v2_constants as v2_constants
from .models import Configuration, Info, Status
from .output import DigitalOutputProgram, DigitalOutputSegment, DigitalOutputStatus
from .protocol import Frame, IncrementalFrameParser, encode_frame
from .protocol_v2 import V2Frame, encode_v2_frame
from .synthetic import synthetic_adc_payload, synthetic_gpio_payload

_RESPONSE_PREFIX = struct.Struct("<BBH")
_ERROR_RESPONSE = struct.Struct("<BBHBBH")
_SUCCESS_PREFIX = _RESPONSE_PREFIX.pack(
    constants.ResponseStatus.OK,
    0,
    constants.ErrorCode.OK,
)
_RECENT_REQUEST_ID_WINDOW = 16
_DEFAULT_OUTPUT_TRACE_EVENTS = 4096


class SimulatorError(RuntimeError):
    """Base error raised by the deterministic simulated device."""


class SimulatorInputError(SimulatorError):
    """A caller supplied more input than one bounded receive operation allows."""


class SimulatorTraceUnavailableError(SimulatorError):
    """A requested historical tick is no longer present in the bounded trace."""


class OutputTraceEvent(str, Enum):
    """Reason one deterministic output trace record was emitted."""

    ARM_IDLE = "arm_idle"
    SEGMENT = "segment"
    COMPLETE = "complete"
    STOP = "stop"
    FAULT = "fault"
    RELEASE = "release"


@dataclass(frozen=True, slots=True)
class SimulatedOutputTransition:
    """One timestamped output state/lifecycle transition in the bounded trace."""

    tick: int
    generation: int
    run_id: int
    event: OutputTraceEvent
    state_mask: int | None
    bank_mode: v2_constants.OutputBankMode
    output_state: v2_constants.OutputState
    completed_repeats: int
    segment_index: int


@dataclass(frozen=True, slots=True)
class SimulatedOutputSample:
    """Output state sampled at one common 8 MHz timestamp."""

    tick: int
    generation: int
    run_id: int
    state_mask: int | None
    bank_mode: v2_constants.OutputBankMode
    output_state: v2_constants.OutputState


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
        output_enabled: bool = False,
        build_id: str = "thingdaq-simulator-v1",
        max_receive_bytes: int = constants.MAX_CONTROL_FRAME_BYTES,
        max_requests_per_receive: int = 8,
        max_output_trace_events: int = _DEFAULT_OUTPUT_TRACE_EVENTS,
    ) -> None:
        if max_receive_bytes < constants.MIN_FRAME_BYTES:
            raise ValueError("max_receive_bytes must hold at least one frame")
        if max_requests_per_receive <= 0:
            raise ValueError("max_requests_per_receive must be positive")
        if not isinstance(control_only, bool):
            raise TypeError("control_only must be a boolean")
        if not isinstance(output_enabled, bool):
            raise TypeError("output_enabled must be a boolean")
        if (
            not isinstance(max_output_trace_events, int)
            or isinstance(max_output_trace_events, bool)
            or max_output_trace_events <= 0
        ):
            raise ValueError("max_output_trace_events must be a positive integer")
        # Validate build identity through the public model once at construction.
        Info(device_state=constants.DeviceState.IDLE, build_id=build_id)

        self._build_id = build_id
        self._control_only = control_only
        self._output_enabled = output_enabled
        self._max_receive_bytes = max_receive_bytes
        self._max_requests_per_receive = max_requests_per_receive
        self._request_parser = IncrementalFrameParser(accept_protocol_v2=output_enabled)
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
        self._output_state = v2_constants.OutputState.EMPTY
        self._output_bank_mode = v2_constants.OutputBankMode.DISABLED
        self._output_generation = 0
        self._output_repeat_count = 0
        self._output_idle_state = 0
        self._output_current_state = 0
        self._output_last_emitted_state = 0
        self._output_program: DigitalOutputProgram | None = None
        self._output_loading_segments: list[DigitalOutputSegment] = []
        self._output_completed_repeats = 0
        self._output_segment_index = 0
        self._output_transitions_emitted = 0
        self._output_error = v2_constants.OutputError.NONE
        self._common_ticks = 0
        self._next_output_event_ticks = 0
        self._seen_output_generations: set[int] = set()
        self._output_trace: deque[SimulatedOutputTransition] = deque(
            maxlen=max_output_trace_events
        )
        self._output_trace_dropped = 0
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

    @property
    def output_enabled(self) -> bool:
        """Whether the explicit experimental protocol-v2 surface is enabled."""

        return self._output_enabled

    @property
    def common_ticks(self) -> int:
        """Explicitly advanced timestamp ticks in the current common run."""

        return self._common_ticks

    @property
    def output_trace(self) -> tuple[SimulatedOutputTransition, ...]:
        """Return an immutable snapshot of the bounded transition trace."""

        return tuple(self._output_trace)

    @property
    def output_trace_dropped(self) -> int:
        """Number of oldest transition records evicted from the bounded trace."""

        return self._output_trace_dropped

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

    def output_status(self) -> DigitalOutputStatus:
        """Return output lifecycle/counter state without advancing simulated time."""

        self._require_output_enabled()
        program = self._output_program
        accepted = len(self._output_loading_segments)
        segment_count = 0 if program is None else len(program.segments)
        checksum = 0 if program is None else program.checksum
        return DigitalOutputStatus(
            state=self._output_state,
            bank_mode=self._output_bank_mode,
            fault_latched=self._output_state is v2_constants.OutputState.FAULTED,
            generation=self._output_generation,
            idle_state_mask=self._output_idle_state,
            current_state_mask=self._output_current_state,
            last_emitted_state_mask=self._output_last_emitted_state,
            repeat_count=self._output_repeat_count,
            completed_repeats=self._output_completed_repeats,
            segment_count=segment_count,
            accepted_segment_count=(
                accepted
                if self._output_state is v2_constants.OutputState.LOADING
                else segment_count
            ),
            program_checksum=checksum,
            current_segment_index=self._output_segment_index,
            ticks_elapsed=self._common_ticks,
            transitions_emitted=self._output_transitions_emitted,
            output_error=self._output_error,
        )

    def advance_time(self, ticks: int) -> int:
        """Advance the common 8 MHz run clock and due output events explicitly.

        Data and control reads never call this method.  This separation keeps
        offline timing assertions independent of host reader scheduling.
        """

        self._require_output_enabled()
        if not isinstance(ticks, int) or isinstance(ticks, bool) or ticks < 0:
            raise ValueError("ticks must be a nonnegative integer")
        if self._state is not constants.DeviceState.RUNNING:
            raise SimulatorError("simulated time advances only during a common run")
        target = self._common_ticks + ticks
        if target > constants.UINT64_MAX:
            raise SimulatorError("common timestamp would exceed u64")
        while (
            self._output_state is v2_constants.OutputState.RUNNING
            and self._next_output_event_ticks <= target
        ):
            self._common_ticks = self._next_output_event_ticks
            self._advance_output_boundary()
        self._common_ticks = target
        return self._common_ticks

    def sample_output(
        self,
        ticks: int | Iterable[int],
        *,
        run_id: int | None = None,
    ) -> SimulatedOutputSample | tuple[SimulatedOutputSample, ...]:
        """Sample held output states at common ticks without changing playback."""

        self._require_output_enabled()
        if isinstance(ticks, bool):
            raise TypeError("sample ticks must be integers")
        requested: tuple[int, ...]
        if isinstance(ticks, int):
            scalar = True
            requested = (ticks,)
        else:
            scalar = False
            requested = tuple(ticks)
        selected_run = self._last_run_id if run_id is None else run_id
        if not isinstance(selected_run, int) or isinstance(selected_run, bool):
            raise TypeError("run_id must be an integer")
        if not 1 <= selected_run <= constants.UINT32_MAX:
            raise ValueError("run_id must be a nonzero u32")
        run_events = tuple(
            event for event in self._output_trace if event.run_id == selected_run
        )
        samples: list[SimulatedOutputSample] = []
        for tick in requested:
            if not isinstance(tick, int) or isinstance(tick, bool) or tick < 0:
                raise ValueError("sample ticks must be nonnegative integers")
            if selected_run == self._last_run_id:
                latest_tick = (
                    self._common_ticks
                    if self._output_state is not v2_constants.OutputState.EMPTY
                    else max((event.tick for event in run_events), default=-1)
                )
                if tick > latest_tick:
                    raise ValueError("cannot sample beyond explicitly advanced time")
            matching = [event for event in run_events if event.tick <= tick]
            if not matching:
                raise SimulatorTraceUnavailableError(
                    f"output trace has no state for run {selected_run} tick {tick}"
                )
            event = matching[-1]
            samples.append(
                SimulatedOutputSample(
                    tick=tick,
                    generation=event.generation,
                    run_id=selected_run,
                    state_mask=event.state_mask,
                    bank_mode=event.bank_mode,
                    output_state=event.output_state,
                )
            )
        return samples[0] if scalar else tuple(samples)

    def inject_output_fault(
        self,
        error: v2_constants.OutputError = v2_constants.OutputError.UNDERRUN,
    ) -> DigitalOutputStatus:
        """Inject an underrun/DMA fault and stop the aligned common run."""

        self._require_output_enabled()
        try:
            selected = v2_constants.OutputError(error)
        except ValueError as cause:
            raise ValueError("unknown output fault") from cause
        if selected not in {
            v2_constants.OutputError.UNDERRUN,
            v2_constants.OutputError.DMA_FAULT,
        }:
            raise ValueError("only UNDERRUN or DMA_FAULT may be injected")
        if (
            self._state is not constants.DeviceState.RUNNING
            or self._output_state is not v2_constants.OutputState.RUNNING
        ):
            raise SimulatorError("an output fault requires active playback")
        self._output_state = v2_constants.OutputState.FAULTED
        self._output_error = selected
        self._state = constants.DeviceState.IDLE
        self._configuration = None
        self._record_output_transition(OutputTraceEvent.FAULT)
        return self.output_status()

    def _handle_frame(self, request: Frame | V2Frame) -> bytes | None:
        if isinstance(request, V2Frame):
            return self._handle_v2_frame(request)
        if request.header.kind not in constants.REQUEST_RESPONSE_KIND:
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
        return handlers[request.header.kind](request)

    def _handle_v2_frame(self, request: V2Frame) -> bytes:
        if self._state is constants.DeviceState.BOOT:
            return self._v2_error(request, constants.ErrorCode.INVALID_STATE)
        if request.header.request_id in self._recent_request_ids:
            self._bad_request_ids = min(
                self._bad_request_ids + 1,
                constants.UINT32_MAX,
            )
            return self._v2_error(request, constants.ErrorCode.INVALID_REQUEST_ID)
        self._recent_request_ids.append(request.header.request_id)
        handlers = {
            v2_constants.FrameKind.INFO_REQUEST: self._handle_v2_info,
            v2_constants.FrameKind.OUTPUT_BEGIN_REQUEST: self._handle_output_begin,
            v2_constants.FrameKind.OUTPUT_APPEND_REQUEST: self._handle_output_append,
            v2_constants.FrameKind.OUTPUT_COMMIT_REQUEST: self._handle_output_commit,
            v2_constants.FrameKind.OUTPUT_ARM_REQUEST: self._handle_output_arm,
            v2_constants.FrameKind.OUTPUT_STATUS_REQUEST: self._handle_output_status,
            v2_constants.FrameKind.OUTPUT_CLEAR_REQUEST: self._handle_output_clear,
        }
        handler = handlers.get(request.header.kind)
        if handler is None:
            return self._v2_error(request, constants.ErrorCode.UNKNOWN_FRAME_KIND)
        return handler(request)

    def _handle_v2_info(self, request: V2Frame) -> bytes:
        payload = bytearray(v2_constants.INFO_RESPONSE_PAYLOAD_SIZE)
        payload[: len(_SUCCESS_PREFIX)] = _SUCCESS_PREFIX
        payload[v2_constants.INFO_RESPONSE_PROTOCOL_VERSION_OFFSET] = (
            v2_constants.PROTOCOL_VERSION
        )
        capability_bits = (
            v2_constants.Capability.PRELOADED_AUXILIARY_OUTPUT
            | v2_constants.Capability.COMMON_EPOCH_OUTPUT
        )
        struct.pack_into(
            "<I",
            payload,
            v2_constants.INFO_RESPONSE_CAPABILITY_BITS_OFFSET,
            capability_bits,
        )
        payload[v2_constants.INFO_RESPONSE_OUTPUT_BANK_MODE_OFFSET] = int(
            v2_constants.OutputBankMode.DISABLED
        )
        payload[v2_constants.INFO_RESPONSE_OUTPUT_PIN_COUNT_OFFSET] = len(
            v2_constants.OUTPUT_PINS_BY_LOGICAL_BIT
        )
        payload[v2_constants.INFO_RESPONSE_OUTPUT_STATE_WIDTH_BITS_OFFSET] = (
            v2_constants.OUTPUT_STATE_WIDTH_BITS
        )
        payload[v2_constants.INFO_RESPONSE_OUTPUT_DURATION_QUANTUM_US_OFFSET] = (
            v2_constants.OUTPUT_DURATION_QUANTUM_US
        )
        pins_offset = v2_constants.INFO_RESPONSE_OUTPUT_PIN_MAP_OFFSET
        payload[pins_offset : pins_offset + 8] = bytes(
            v2_constants.OUTPUT_PINS_BY_LOGICAL_BIT
        )
        gpio_offset = v2_constants.INFO_RESPONSE_OUTPUT_GPIO_BITS_BY_LOGICAL_BIT_OFFSET
        payload[gpio_offset : gpio_offset + 8] = bytes(
            v2_constants.OUTPUT_GPIO_BITS_BY_LOGICAL_BIT
        )
        for offset, value in (
            (
                v2_constants.INFO_RESPONSE_OUTPUT_RATE_HZ_OFFSET,
                v2_constants.OUTPUT_RATE_HZ,
            ),
            (
                v2_constants.INFO_RESPONSE_OUTPUT_PERIOD_TICKS_OFFSET,
                v2_constants.OUTPUT_PERIOD_TICKS,
            ),
            (
                v2_constants.INFO_RESPONSE_OUTPUT_CAPACITY_SEGMENTS_OFFSET,
                v2_constants.OUTPUT_SEGMENT_CAPACITY,
            ),
            (
                v2_constants.INFO_RESPONSE_OUTPUT_LEGAL_STATE_MASK_OFFSET,
                v2_constants.OUTPUT_LEGAL_STATE_MASK,
            ),
        ):
            struct.pack_into("<I", payload, offset, value)
        return self._v2_success_response(request, payload)

    def _handle_output_begin(self, request: V2Frame) -> bytes:
        if self._state is not constants.DeviceState.IDLE or self._output_state not in {
            v2_constants.OutputState.EMPTY,
            v2_constants.OutputState.LOADING,
        }:
            return self._v2_error(
                request,
                constants.ErrorCode.INVALID_STATE,
                v2_constants.OutputError.INVALID_LIFECYCLE,
            )
        generation = request.header.run_id
        if generation in self._seen_output_generations:
            return self._v2_error(
                request,
                constants.ErrorCode.INVALID_PAYLOAD,
                v2_constants.OutputError.GENERATION_MISMATCH,
            )
        repeat_count, idle_state = struct.unpack("<II", request.payload)
        self._seen_output_generations.add(generation)
        self._output_generation = generation
        self._output_repeat_count = repeat_count
        self._output_idle_state = idle_state
        self._output_current_state = 0
        self._output_last_emitted_state = 0
        self._output_program = None
        self._output_loading_segments.clear()
        self._output_completed_repeats = 0
        self._output_segment_index = 0
        self._output_transitions_emitted = 0
        self._output_error = v2_constants.OutputError.NONE
        self._output_state = v2_constants.OutputState.LOADING
        self._output_bank_mode = v2_constants.OutputBankMode.DISABLED
        self._common_ticks = 0
        return self._v2_output_status_response(request)

    def _handle_output_append(self, request: V2Frame) -> bytes:
        invalid = self._validate_output_mutation(
            request, v2_constants.OutputState.LOADING
        )
        if invalid is not None:
            return invalid
        segment = DigitalOutputSegment(*struct.unpack("<II", request.payload))
        if len(self._output_loading_segments) >= v2_constants.OUTPUT_SEGMENT_CAPACITY:
            return self._v2_error(
                request,
                constants.ErrorCode.INVALID_PAYLOAD,
                v2_constants.OutputError.CAPACITY_EXCEEDED,
            )
        if (
            self._output_loading_segments
            and self._output_loading_segments[-1].logical_state_mask
            == segment.logical_state_mask
        ):
            return self._v2_error(
                request,
                constants.ErrorCode.INVALID_PAYLOAD,
                v2_constants.OutputError.INVALID_SEGMENT,
            )
        self._output_loading_segments.append(segment)
        payload = bytearray(v2_constants.OUTPUT_APPEND_RESPONSE_PAYLOAD_SIZE)
        payload[: len(_SUCCESS_PREFIX)] = _SUCCESS_PREFIX
        struct.pack_into("<I", payload, 4, len(self._output_loading_segments))
        payload[8:] = segment.to_bytes()
        return self._v2_success_response(request, payload)

    def _handle_output_commit(self, request: V2Frame) -> bytes:
        invalid = self._validate_output_mutation(
            request, v2_constants.OutputState.LOADING
        )
        if invalid is not None:
            return invalid
        segment_count, checksum = struct.unpack("<II", request.payload)
        if segment_count != len(self._output_loading_segments):
            return self._v2_error(
                request,
                constants.ErrorCode.INVALID_PAYLOAD,
                v2_constants.OutputError.TRUNCATED_UPLOAD,
            )
        canonical = b"".join(
            segment.to_bytes() for segment in self._output_loading_segments
        )
        if checksum != zlib.adler32(canonical) & constants.UINT32_MAX:
            return self._v2_error(
                request,
                constants.ErrorCode.CHECKSUM_MISMATCH,
                v2_constants.OutputError.CHECKSUM_MISMATCH,
            )
        self._output_program = DigitalOutputProgram(
            tuple(self._output_loading_segments),
            repeat_count=self._output_repeat_count,
            idle_state_mask=self._output_idle_state,
        )
        self._output_state = v2_constants.OutputState.COMMITTED
        return self._v2_output_status_response(request)

    def _handle_output_arm(self, request: V2Frame) -> bytes:
        invalid = self._validate_output_mutation(
            request,
            v2_constants.OutputState.COMMITTED,
            v2_constants.OutputState.HELD,
        )
        if invalid is not None:
            return invalid
        self._output_state = v2_constants.OutputState.ARMED
        self._output_bank_mode = v2_constants.OutputBankMode.OUTPUT
        self._output_current_state = self._output_idle_state
        self._output_last_emitted_state = self._output_idle_state
        self._output_completed_repeats = 0
        self._output_segment_index = 0
        self._output_transitions_emitted = 0
        self._output_error = v2_constants.OutputError.NONE
        self._common_ticks = 0
        self._record_output_transition(OutputTraceEvent.ARM_IDLE, run_id=0)
        return self._v2_output_status_response(request)

    def _handle_output_status(self, request: V2Frame) -> bytes:
        if self._state not in {
            constants.DeviceState.IDLE,
            constants.DeviceState.CONFIGURED,
            constants.DeviceState.RUNNING,
        }:
            return self._v2_error(
                request,
                constants.ErrorCode.INVALID_STATE,
                v2_constants.OutputError.INVALID_LIFECYCLE,
            )
        if self._output_generation and request.header.run_id != self._output_generation:
            return self._v2_error(
                request,
                constants.ErrorCode.INVALID_PAYLOAD,
                v2_constants.OutputError.GENERATION_MISMATCH,
            )
        return self._v2_output_status_response(request)

    def _handle_output_clear(self, request: V2Frame) -> bytes:
        if self._state is not constants.DeviceState.IDLE:
            return self._v2_error(
                request,
                constants.ErrorCode.INVALID_STATE,
                v2_constants.OutputError.INVALID_LIFECYCLE,
            )
        if self._output_generation and request.header.run_id != self._output_generation:
            return self._v2_error(
                request,
                constants.ErrorCode.INVALID_PAYLOAD,
                v2_constants.OutputError.GENERATION_MISMATCH,
            )
        if self._output_bank_mode is v2_constants.OutputBankMode.OUTPUT:
            self._output_bank_mode = v2_constants.OutputBankMode.DISABLED
            self._record_output_transition(OutputTraceEvent.RELEASE, state_mask=None)
        self._clear_output_state()
        return self._v2_output_status_response(request)

    def _handle_info(self, request: Frame) -> bytes:
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
        )
        return self._success_response(request, info.to_payload())

    def _handle_configure(self, request: Frame) -> bytes:
        if self._state not in {
            constants.DeviceState.IDLE,
            constants.DeviceState.CONFIGURED,
        }:
            return self._typed_error(request, constants.ErrorCode.INVALID_STATE)

        configuration = Configuration.from_payload(request.payload)
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
        if self._output_state is v2_constants.OutputState.ARMED:
            self._start_output_epoch()
        return self._success_response(
            request,
            _SUCCESS_PREFIX + self._configuration.to_payload(),
            run_id=self._last_run_id,
        )

    def _handle_status(self, request: Frame) -> bytes:
        return self._success_response(request, self.status().to_payload())

    def _handle_stop(self, request: Frame) -> bytes:
        if self._output_state in {
            v2_constants.OutputState.ARMED,
            v2_constants.OutputState.RUNNING,
        }:
            self._output_state = v2_constants.OutputState.HELD
        if self._output_state is v2_constants.OutputState.HELD:
            self._record_output_transition(OutputTraceEvent.STOP)
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

    def _handle_checksum_benchmark(self, request: Frame) -> bytes:
        # The offline simulator has no 600 MHz DWT or Teensy memory regions and
        # therefore deliberately does not advertise or fabricate this result.
        return self._typed_error(request, constants.ErrorCode.UNSUPPORTED_CONFIGURATION)

    def _handle_gpio_clock_diagnostic(self, request: Frame) -> bytes:
        # The simulator has no PIT/XBARA/eDMA route and does not invent target
        # register snapshots or timing evidence.
        return self._typed_error(request, constants.ErrorCode.UNSUPPORTED_CONFIGURATION)

    def _handle_gpio_capture_diagnostic(self, request: Frame) -> bytes:
        # The simulator intentionally does not claim physical capture evidence.
        return self._typed_error(request, constants.ErrorCode.UNSUPPORTED_CONFIGURATION)

    def _require_output_enabled(self) -> None:
        if not self._output_enabled:
            raise SimulatorError(
                "experimental output is disabled; construct with output_enabled=True"
            )

    def _validate_output_mutation(
        self,
        request: V2Frame,
        *allowed_states: v2_constants.OutputState,
    ) -> bytes | None:
        if self._state is not constants.DeviceState.IDLE:
            return self._v2_error(
                request,
                constants.ErrorCode.INVALID_STATE,
                v2_constants.OutputError.INVALID_LIFECYCLE,
            )
        if self._output_state not in allowed_states:
            return self._v2_error(
                request,
                constants.ErrorCode.INVALID_STATE,
                v2_constants.OutputError.INVALID_LIFECYCLE,
            )
        if request.header.run_id != self._output_generation:
            return self._v2_error(
                request,
                constants.ErrorCode.INVALID_PAYLOAD,
                v2_constants.OutputError.GENERATION_MISMATCH,
            )
        return None

    def _start_output_epoch(self) -> None:
        program = self._output_program
        if program is None:  # pragma: no cover - lifecycle guard
            raise SimulatorError("armed output has no committed program")
        self._output_state = v2_constants.OutputState.RUNNING
        self._output_completed_repeats = 0
        self._output_segment_index = 0
        self._output_transitions_emitted = 0
        self._output_error = v2_constants.OutputError.NONE
        self._emit_output_segment(0)

    def _emit_output_segment(self, index: int) -> None:
        program = self._output_program
        if program is None:  # pragma: no cover - lifecycle guard
            raise SimulatorError("running output has no committed program")
        segment = program.segments[index]
        self._output_segment_index = index
        self._output_current_state = segment.logical_state_mask
        self._output_last_emitted_state = segment.logical_state_mask
        self._output_transitions_emitted = min(
            self._output_transitions_emitted + 1,
            constants.UINT32_MAX,
        )
        self._record_output_transition(OutputTraceEvent.SEGMENT)
        self._next_output_event_ticks = self._common_ticks + (
            segment.duration_samples * v2_constants.OUTPUT_PERIOD_TICKS
        )

    def _advance_output_boundary(self) -> None:
        program = self._output_program
        if program is None:  # pragma: no cover - lifecycle guard
            raise SimulatorError("running output has no committed program")
        next_index = self._output_segment_index + 1
        if next_index < len(program.segments):
            self._emit_output_segment(next_index)
            return
        self._output_completed_repeats = min(
            self._output_completed_repeats + 1,
            constants.UINT32_MAX,
        )
        if (
            program.repeat_count != v2_constants.OUTPUT_REPEAT_FOREVER
            and self._output_completed_repeats >= program.repeat_count
        ):
            self._output_state = v2_constants.OutputState.HELD
            self._record_output_transition(OutputTraceEvent.COMPLETE)
            return
        self._emit_output_segment(0)

    def _record_output_transition(
        self,
        event: OutputTraceEvent,
        *,
        state_mask: int | None | object = ...,
        run_id: int | None = None,
    ) -> None:
        if len(self._output_trace) == self._output_trace.maxlen:
            self._output_trace_dropped = min(
                self._output_trace_dropped + 1,
                constants.UINT32_MAX,
            )
        selected_state = self._output_current_state if state_mask is ... else state_mask
        assert selected_state is None or isinstance(selected_state, int)
        self._output_trace.append(
            SimulatedOutputTransition(
                tick=self._common_ticks,
                generation=self._output_generation,
                run_id=self._last_run_id if run_id is None else run_id,
                event=event,
                state_mask=selected_state,
                bank_mode=self._output_bank_mode,
                output_state=self._output_state,
                completed_repeats=self._output_completed_repeats,
                segment_index=self._output_segment_index,
            )
        )

    def _clear_output_state(self) -> None:
        self._output_state = v2_constants.OutputState.EMPTY
        self._output_bank_mode = v2_constants.OutputBankMode.DISABLED
        self._output_generation = 0
        self._output_repeat_count = 0
        self._output_idle_state = 0
        self._output_current_state = 0
        self._output_last_emitted_state = 0
        self._output_program = None
        self._output_loading_segments.clear()
        self._output_completed_repeats = 0
        self._output_segment_index = 0
        self._output_transitions_emitted = 0
        self._output_error = v2_constants.OutputError.NONE
        self._common_ticks = 0
        self._next_output_event_ticks = 0

    def _reset_epoch(self) -> None:
        self._adc_sequence = 0
        self._gpio_sequence = 0
        self._adc_first_ticks = 0
        self._gpio_first_ticks = 0
        self._adc_item_index = 0
        self._gpio_item_index = 0
        self._reset_counters()
        self._next_stream_index = 0
        self._common_ticks = 0

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

    def _v2_success_response(
        self,
        request: V2Frame,
        payload: bytes | bytearray,
    ) -> bytes:
        return encode_v2_frame(
            v2_constants.REQUEST_RESPONSE_KIND[request.header.kind],
            payload,
            run_id=request.header.run_id,
            request_id=request.header.request_id,
        )

    def _v2_output_status_response(self, request: V2Frame) -> bytes:
        return self._v2_success_response(
            request,
            self._output_status_payload(self.output_status()),
        )

    @staticmethod
    def _output_status_payload(
        status: DigitalOutputStatus,
        *,
        response_status: constants.ResponseStatus = constants.ResponseStatus.OK,
        error_code: constants.ErrorCode = constants.ErrorCode.OK,
        output_error: v2_constants.OutputError | None = None,
        generation: int | None = None,
    ) -> bytes:
        payload = bytearray(v2_constants.OUTPUT_STATUS_RESPONSE_PAYLOAD_SIZE)
        payload[: len(_SUCCESS_PREFIX)] = _RESPONSE_PREFIX.pack(
            response_status,
            0,
            error_code,
        )
        payload[v2_constants.OUTPUT_STATUS_RESPONSE_OUTPUT_STATE_OFFSET] = int(
            status.state
        )
        payload[v2_constants.OUTPUT_STATUS_RESPONSE_OUTPUT_BANK_MODE_OFFSET] = int(
            status.bank_mode
        )
        payload[v2_constants.OUTPUT_STATUS_RESPONSE_FAULT_LATCHED_OFFSET] = int(
            status.fault_latched
        )
        u32_fields = (
            (
                v2_constants.OUTPUT_STATUS_RESPONSE_GENERATION_OFFSET,
                status.generation if generation is None else generation,
            ),
            (
                v2_constants.OUTPUT_STATUS_RESPONSE_IDLE_STATE_MASK_OFFSET,
                status.idle_state_mask,
            ),
            (
                v2_constants.OUTPUT_STATUS_RESPONSE_CURRENT_STATE_MASK_OFFSET,
                status.current_state_mask,
            ),
            (
                v2_constants.OUTPUT_STATUS_RESPONSE_LAST_EMITTED_STATE_MASK_OFFSET,
                status.last_emitted_state_mask,
            ),
            (
                v2_constants.OUTPUT_STATUS_RESPONSE_REPEAT_COUNT_OFFSET,
                status.repeat_count,
            ),
            (
                v2_constants.OUTPUT_STATUS_RESPONSE_COMPLETED_REPEATS_OFFSET,
                status.completed_repeats,
            ),
            (
                v2_constants.OUTPUT_STATUS_RESPONSE_SEGMENT_COUNT_OFFSET,
                status.segment_count,
            ),
            (
                v2_constants.OUTPUT_STATUS_RESPONSE_ACCEPTED_SEGMENT_COUNT_OFFSET,
                status.accepted_segment_count,
            ),
            (
                v2_constants.OUTPUT_STATUS_RESPONSE_PROGRAM_CHECKSUM_OFFSET,
                status.program_checksum,
            ),
            (
                v2_constants.OUTPUT_STATUS_RESPONSE_CURRENT_SEGMENT_INDEX_OFFSET,
                status.current_segment_index,
            ),
            (
                v2_constants.OUTPUT_STATUS_RESPONSE_TRANSITIONS_EMITTED_OFFSET,
                status.transitions_emitted,
            ),
        )
        for offset, value in u32_fields:
            struct.pack_into("<I", payload, offset, value)
        struct.pack_into(
            "<Q",
            payload,
            v2_constants.OUTPUT_STATUS_RESPONSE_TICKS_ELAPSED_OFFSET,
            status.ticks_elapsed,
        )
        payload[v2_constants.OUTPUT_STATUS_RESPONSE_OUTPUT_ERROR_OFFSET] = int(
            status.output_error if output_error is None else output_error
        )
        return bytes(payload)

    def _v2_error(
        self,
        request: V2Frame,
        error: constants.ErrorCode,
        output_error: v2_constants.OutputError = (
            v2_constants.OutputError.INVALID_LIFECYCLE
        ),
    ) -> bytes:
        if request.header.kind is v2_constants.FrameKind.INFO_REQUEST:
            payload = _ERROR_RESPONSE.pack(
                constants.ResponseStatus.ERROR,
                0,
                error,
                int(request.header.kind),
                request.header.version,
                0,
            )
            return encode_v2_frame(
                v2_constants.FrameKind.ERROR_RESPONSE,
                payload,
                flags=v2_constants.FrameFlag.RESPONSE_ERROR,
                request_id=request.header.request_id,
            )
        payload = self._output_status_payload(
            self.output_status(),
            response_status=constants.ResponseStatus.ERROR,
            error_code=error,
            output_error=output_error,
            generation=request.header.run_id,
        )
        return encode_v2_frame(
            v2_constants.REQUEST_RESPONSE_KIND[request.header.kind],
            payload,
            flags=v2_constants.FrameFlag.RESPONSE_ERROR,
            run_id=request.header.run_id,
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

    def _busy_response(self, request: Frame | V2Frame) -> bytes | None:
        if isinstance(request, V2Frame):
            return self._v2_error(request, constants.ErrorCode.BUSY)
        if request.header.kind in constants.REQUEST_RESPONSE_KIND:
            return self._typed_error(request, constants.ErrorCode.BUSY)
        if request.header.request_id:
            return self._generic_error(request, constants.ErrorCode.BUSY)
        return None


__all__ = [
    "OutputTraceEvent",
    "SimulatedDevice",
    "SimulatedOutputSample",
    "SimulatedOutputTransition",
    "SimulatorError",
    "SimulatorInputError",
    "SimulatorTraceUnavailableError",
]
