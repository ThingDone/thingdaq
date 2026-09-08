"""Strict synthetic-stream validation and bounded soak metrics."""

from __future__ import annotations

import math
import tracemalloc
from collections import deque
from collections.abc import Callable
from dataclasses import dataclass
from time import monotonic, sleep
from typing import TypeVar

from ._generated import protocol_constants as constants
from .client import (
    BlockTimeoutError,
    StreamItem,
    ThingDAQ,
    UnexpectedStreamValidationError,
)
from .models import ADCBlock, GPIOBlock, HostQueueLoss, Status, StreamAnomaly, StreamGap
from .protocol import ParserCounters
from .reader import ReaderCounters
from .synthetic import SyntheticPatternError, validate_synthetic_block

_Result = TypeVar("_Result")


@dataclass(frozen=True, slots=True)
class StreamRateMetrics:
    """Frame, logical-item, byte, and rate totals for one stream."""

    frame_count: int
    item_count: int
    payload_bytes: int
    framed_bytes: int
    elapsed_seconds: float

    @property
    def payload_bytes_per_second(self) -> float:
        return self.payload_bytes / self.elapsed_seconds

    @property
    def framed_bytes_per_second(self) -> float:
        return self.framed_bytes / self.elapsed_seconds


@dataclass(frozen=True, slots=True)
class CommandLatencyDistribution:
    """Bounded command-latency distribution with transparent sample retention."""

    count: int
    samples_retained: int
    samples_discarded: int
    minimum_seconds: float
    mean_seconds: float
    p50_seconds: float
    p95_seconds: float
    p99_seconds: float
    maximum_seconds: float
    command_counts: tuple[tuple[str, int], ...]


@dataclass(frozen=True, slots=True)
class QueueDepthMetrics:
    """Final and lifetime high-water depths for bounded host queues."""

    pending_requests: int
    queued_blocks: int
    queued_events: int
    pending_request_high_water: int
    block_queue_high_water: int
    event_queue_high_water: int
    parser_buffered_bytes: int
    parser_high_water_bytes: int
    reusable_read_buffer_bytes: int
    maximum_read_bytes: int


@dataclass(frozen=True, slots=True)
class MemoryHighWaterMetrics:
    """Portable Python-allocation measurements captured with ``tracemalloc``."""

    enabled: bool
    baseline_current_bytes: int
    baseline_peak_bytes: int
    final_current_bytes: int
    peak_bytes: int

    @property
    def peak_growth_bytes(self) -> int:
        return max(0, self.peak_bytes - self.baseline_peak_bytes)


@dataclass(frozen=True, slots=True)
class CounterReconciliation:
    """Firmware, wire-parser, and validated-consumer conservation snapshot."""

    adc_firmware_frames_emitted: int
    gpio_firmware_frames_emitted: int
    adc_wire_frames_received: int
    gpio_wire_frames_received: int
    adc_validated_frames: int
    gpio_validated_frames: int
    adc_host_queue_drops: int
    gpio_host_queue_drops: int
    adc_boundary_discards: int
    gpio_boundary_discards: int
    adc_stale_discards: int
    gpio_stale_discards: int
    firmware_adc_items_dropped: int
    firmware_gpio_items_dropped: int
    firmware_parser_errors: int
    firmware_transport_errors: int
    host_parser_errors: int
    host_event_queue_drops: int
    issues: tuple[str, ...]

    @property
    def ok(self) -> bool:
        return not self.issues

    def require_exact(self) -> None:
        """Raise with the first failed conservation equation."""

        if self.issues:
            raise UnexpectedStreamValidationError(
                "counter_reconciliation",
                self.issues[0],
            )


@dataclass(frozen=True, slots=True)
class SoakMetrics:
    """Reusable result for one strict synthetic capture and clean shutdown."""

    run_id: int
    elapsed_seconds: float
    adc: StreamRateMetrics
    gpio: StreamRateMetrics
    command_latency: CommandLatencyDistribution
    queues: QueueDepthMetrics
    memory: MemoryHighWaterMetrics
    final_status: Status
    reader_counters: ReaderCounters
    parser_counters: ParserCounters
    reconciliation: CounterReconciliation

    @property
    def frame_count(self) -> int:
        return self.adc.frame_count + self.gpio.frame_count

    @property
    def payload_bytes(self) -> int:
        return self.adc.payload_bytes + self.gpio.payload_bytes

    @property
    def framed_bytes(self) -> int:
        return self.adc.framed_bytes + self.gpio.framed_bytes

    @property
    def payload_bytes_per_second(self) -> float:
        return self.payload_bytes / self.elapsed_seconds

    @property
    def framed_bytes_per_second(self) -> float:
        return self.framed_bytes / self.elapsed_seconds


class SyntheticStreamValidator:
    """Validate every strict synthetic epoch invariant without NumPy."""

    def __init__(
        self,
        run_id: int,
        stream_mask: constants.StreamMask | int,
        *,
        reader_baseline: ReaderCounters,
        parser_baseline: ParserCounters,
    ) -> None:
        if not isinstance(run_id, int) or isinstance(run_id, bool) or run_id <= 0:
            raise ValueError("run_id must be a nonzero integer")
        try:
            selected_streams = constants.StreamMask(stream_mask)
        except (TypeError, ValueError) as error:
            raise ValueError("stream_mask contains an unknown stream") from error
        valid_streams = constants.StreamMask.ADC | constants.StreamMask.GPIO
        if not selected_streams or int(selected_streams) & ~int(valid_streams):
            raise ValueError("stream_mask must enable ADC, GPIO, or both")
        if not isinstance(reader_baseline, ReaderCounters):
            raise TypeError("reader_baseline must be ReaderCounters")
        if not isinstance(parser_baseline, ParserCounters):
            raise TypeError("parser_baseline must be ParserCounters")

        self.run_id = run_id
        self.stream_mask = selected_streams
        self.reader_baseline = reader_baseline
        self.parser_baseline = parser_baseline
        self._expected_sequence: dict[constants.FrameKind, int] = {}
        self._expected_ticks: dict[constants.FrameKind, int] = {}
        if selected_streams & constants.StreamMask.ADC:
            self._expected_sequence[constants.FrameKind.ADC_DATA] = 0
            self._expected_ticks[constants.FrameKind.ADC_DATA] = 0
        if selected_streams & constants.StreamMask.GPIO:
            self._expected_sequence[constants.FrameKind.GPIO_DATA] = 0
            self._expected_ticks[constants.FrameKind.GPIO_DATA] = 0
        self.adc_frames_validated = 0
        self.gpio_frames_validated = 0
        self._stats_generation: int | None = None

    def validate(self, item: StreamItem) -> ADCBlock | GPIOBlock:
        """Validate and account one block, rejecting every typed loss report."""

        if isinstance(item, StreamGap):
            self._fail(
                "stream_gap",
                f"{item.kind.name} sequence {item.observed_sequence} follows "
                f"{item.missing_frames} missing frame(s)",
            )
        if isinstance(item, HostQueueLoss):
            self._fail(
                "host_queue_loss",
                f"{item.kind.name} lost {item.dropped_blocks} decoded block(s) "
                f"under {item.policy.value}",
            )
        if isinstance(item, StreamAnomaly):
            self._fail(
                "stream_anomaly",
                f"{item.kind.name} {item.reason.value} at sequence "
                f"{item.observed_sequence}",
            )
        if not isinstance(item, (ADCBlock, GPIOBlock)):
            raise TypeError("stream validation requires a block or typed loss report")
        block = item
        kind = (
            constants.FrameKind.ADC_DATA
            if isinstance(block, ADCBlock)
            else constants.FrameKind.GPIO_DATA
        )
        if kind not in self._expected_sequence:
            self._fail("disabled_stream", f"received disabled {kind.name}")
        if block.run_id != self.run_id:
            self._fail(
                "run_id",
                f"received run {block.run_id}; expected {self.run_id}",
            )
        if block.flags & (
            constants.FrameFlag.GAP_BEFORE | constants.FrameFlag.OVERRUN_BEFORE
        ):
            self._fail(
                "firmware_gap_flag",
                f"{kind.name} sequence {block.sequence} carries "
                f"flags 0x{int(block.flags):04x}",
            )
        expected_sequence = self._expected_sequence[kind]
        if block.sequence != expected_sequence:
            self._fail(
                "sequence",
                f"{kind.name} sequence is {block.sequence}; "
                f"expected {expected_sequence}",
            )
        expected_ticks = self._expected_ticks[kind]
        if block.first_sample_ticks != expected_ticks:
            self._fail(
                "timestamp",
                f"{kind.name} timestamp is {block.first_sample_ticks}; "
                f"expected {expected_ticks}",
            )
        try:
            validate_synthetic_block(block)
        except SyntheticPatternError as error:
            self._fail("synthetic_pattern", str(error), cause=error)

        self._expected_sequence[kind] = (block.sequence + 1) & constants.UINT32_MAX
        self._expected_ticks[kind] = block.end_tick_exclusive
        if isinstance(block, ADCBlock):
            self.adc_frames_validated += 1
        else:
            self.gpio_frames_validated += 1
        return block

    def validate_host_health(
        self,
        reader: ReaderCounters,
        parser: ParserCounters,
        *,
        after_stop: bool = False,
    ) -> None:
        """Reject parser errors and loss from bounded host queues."""

        parser_errors = self._delta(
            "parser corruption counter",
            parser.corruption_events,
            self.parser_baseline.corruption_events,
        )
        if parser_errors:
            self._fail(
                "parser_errors",
                f"host parser rejected {parser_errors} frame candidate(s)",
            )
        block_drops = self._delta(
            "host block queue-drop counter",
            reader.host_block_queue_drops,
            self.reader_baseline.host_block_queue_drops,
        )
        if block_drops:
            self._fail(
                "host_queue_drops",
                f"host queue dropped {block_drops} decoded block(s)",
            )
        event_drops = self._delta(
            "host event queue-drop counter",
            reader.host_event_queue_drops,
            self.reader_baseline.host_event_queue_drops,
        )
        if event_drops:
            self._fail(
                "host_event_queue_drops",
                f"host queue dropped {event_drops} decoded event(s)",
            )
        if not after_stop:
            stale = self._delta(
                "stale block counter",
                reader.stale_blocks_discarded,
                self.reader_baseline.stale_blocks_discarded,
            )
            if stale:
                self._fail(
                    "stale_blocks",
                    f"reader rejected {stale} stale-run block(s)",
                )

    def validate_status(
        self,
        status: Status,
        *,
        response_run_id: int,
        final: bool = False,
    ) -> None:
        """Validate run identity, configuration, and firmware health counters."""

        if response_run_id != self.run_id:
            self._fail(
                "status_run_id",
                f"STATUS carries run {response_run_id}; expected {self.run_id}",
            )
        expected_state = (
            constants.DeviceState.IDLE if final else constants.DeviceState.RUNNING
        )
        if status.device_state is not expected_state:
            self._fail(
                "status_state",
                f"STATUS reports {status.device_state.name}; "
                f"expected {expected_state.name}",
            )
        if not final and (
            status.stream_mask != self.stream_mask
            or status.source is not constants.Source.SYNTHETIC
        ):
            self._fail(
                "status_configuration",
                "running STATUS disagrees with the synthetic stream configuration",
            )
        if self._stats_generation is None:
            self._stats_generation = status.stats_generation
        elif status.stats_generation != self._stats_generation:
            self._fail(
                "stats_generation",
                f"generation changed from {self._stats_generation} "
                f"to {status.stats_generation}",
            )
        if status.adc_items_dropped or status.gpio_items_dropped:
            self._fail(
                "firmware_drops",
                f"firmware reports {status.adc_items_dropped} ADC and "
                f"{status.gpio_items_dropped} GPIO dropped item(s)",
            )
        if status.parser_errors:
            self._fail(
                "firmware_parser_errors",
                f"firmware reports {status.parser_errors} parser error(s)",
            )
        if status.transport_errors:
            self._fail(
                "firmware_transport_errors",
                f"firmware reports {status.transport_errors} transport error(s)",
            )
        if status.adc_frames_emitted < self.adc_frames_validated:
            self._fail(
                "adc_counter",
                "firmware ADC emitted count trails validated host frames",
            )
        if status.gpio_frames_emitted < self.gpio_frames_validated:
            self._fail(
                "gpio_counter",
                "firmware GPIO emitted count trails validated host frames",
            )

    @staticmethod
    def _delta(name: str, current: int, baseline: int) -> int:
        if current < baseline:
            raise UnexpectedStreamValidationError(
                "counter_regression",
                f"{name} moved backwards from {baseline} to {current}",
            )
        return current - baseline

    @staticmethod
    def _fail(
        category: str,
        message: str,
        *,
        cause: BaseException | None = None,
    ) -> None:
        error = UnexpectedStreamValidationError(category, message)
        if cause is None:
            raise error
        raise error from cause


class _LatencyRecorder:
    def __init__(self, max_samples: int) -> None:
        self._samples: deque[float] = deque(maxlen=max_samples)
        self._count = 0
        self._total = 0.0
        self._minimum = math.inf
        self._maximum = 0.0
        self._commands: dict[str, int] = {}

    def record(self, command: str, elapsed: float) -> None:
        self._samples.append(elapsed)
        self._count += 1
        self._total += elapsed
        self._minimum = min(self._minimum, elapsed)
        self._maximum = max(self._maximum, elapsed)
        self._commands[command] = self._commands.get(command, 0) + 1

    def snapshot(self) -> CommandLatencyDistribution:
        ordered = sorted(self._samples)
        retained = len(ordered)
        if not ordered:
            return CommandLatencyDistribution(
                0,
                0,
                0,
                0.0,
                0.0,
                0.0,
                0.0,
                0.0,
                0.0,
                (),
            )

        def percentile(fraction: float) -> float:
            index = max(0, math.ceil(fraction * retained) - 1)
            return ordered[index]

        return CommandLatencyDistribution(
            count=self._count,
            samples_retained=retained,
            samples_discarded=self._count - retained,
            minimum_seconds=self._minimum,
            mean_seconds=self._total / self._count,
            p50_seconds=percentile(0.50),
            p95_seconds=percentile(0.95),
            p99_seconds=percentile(0.99),
            maximum_seconds=self._maximum,
            command_counts=tuple(sorted(self._commands.items())),
        )


class _MemoryTracker:
    def __init__(self, enabled: bool) -> None:
        self.enabled = enabled
        self._owned = False
        self._baseline_current = 0
        self._baseline_peak = 0

    def start(self) -> None:
        if not self.enabled:
            return
        if not tracemalloc.is_tracing():
            tracemalloc.start()
            tracemalloc.reset_peak()
            self._owned = True
        self._baseline_current, self._baseline_peak = tracemalloc.get_traced_memory()

    def finish(self) -> MemoryHighWaterMetrics:
        if not self.enabled:
            return MemoryHighWaterMetrics(False, 0, 0, 0, 0)
        final_current, peak = tracemalloc.get_traced_memory()
        result = MemoryHighWaterMetrics(
            enabled=True,
            baseline_current_bytes=self._baseline_current,
            baseline_peak_bytes=self._baseline_peak,
            final_current_bytes=final_current,
            peak_bytes=peak,
        )
        if self._owned:
            tracemalloc.stop()
        return result


def _timed(
    recorder: _LatencyRecorder,
    command: str,
    operation: Callable[[], _Result],
    *,
    clock: Callable[[], float] = monotonic,
) -> _Result:
    started = clock()
    try:
        return operation()
    finally:
        recorder.record(command, clock() - started)


def _reader_delta(name: str, final: int, baseline: int) -> int:
    if final < baseline:
        raise UnexpectedStreamValidationError(
            "counter_regression",
            f"{name} moved backwards from {baseline} to {final}",
        )
    return final - baseline


def _positive_seconds(name: str, value: float) -> float:
    if not isinstance(value, (int, float)) or isinstance(value, bool):
        raise TypeError(f"{name} must be numeric")
    try:
        selected = float(value)
    except OverflowError as error:
        raise ValueError(f"{name} must be positive and finite") from error
    if not math.isfinite(selected) or selected <= 0:
        raise ValueError(f"{name} must be positive and finite")
    return selected


def _reconcile(
    *,
    status: Status,
    baseline_reader: ReaderCounters,
    final_reader: ReaderCounters,
    baseline_parser: ParserCounters,
    final_parser: ParserCounters,
    validator: SyntheticStreamValidator,
) -> CounterReconciliation:
    adc_wire = _reader_delta(
        "ADC received counter",
        final_reader.adc_frames_received,
        baseline_reader.adc_frames_received,
    )
    gpio_wire = _reader_delta(
        "GPIO received counter",
        final_reader.gpio_frames_received,
        baseline_reader.gpio_frames_received,
    )
    adc_queue_drops = _reader_delta(
        "ADC queue-drop counter",
        final_reader.adc_block_queue_drops,
        baseline_reader.adc_block_queue_drops,
    )
    gpio_queue_drops = _reader_delta(
        "GPIO queue-drop counter",
        final_reader.gpio_block_queue_drops,
        baseline_reader.gpio_block_queue_drops,
    )
    adc_boundary = _reader_delta(
        "ADC boundary-discard counter",
        final_reader.adc_boundary_blocks_discarded,
        baseline_reader.adc_boundary_blocks_discarded,
    )
    gpio_boundary = _reader_delta(
        "GPIO boundary-discard counter",
        final_reader.gpio_boundary_blocks_discarded,
        baseline_reader.gpio_boundary_blocks_discarded,
    )
    adc_stale = _reader_delta(
        "ADC stale-discard counter",
        final_reader.adc_stale_blocks_discarded,
        baseline_reader.adc_stale_blocks_discarded,
    )
    gpio_stale = _reader_delta(
        "GPIO stale-discard counter",
        final_reader.gpio_stale_blocks_discarded,
        baseline_reader.gpio_stale_blocks_discarded,
    )
    parser_errors = _reader_delta(
        "host parser corruption counter",
        final_parser.corruption_events,
        baseline_parser.corruption_events,
    )
    event_drops = _reader_delta(
        "host event queue-drop counter",
        final_reader.host_event_queue_drops,
        baseline_reader.host_event_queue_drops,
    )

    issues: list[str] = []
    if status.adc_frames_emitted != adc_wire:
        issues.append(
            "firmware emitted "
            f"{status.adc_frames_emitted} ADC frame(s), but the host parser "
            f"received {adc_wire}"
        )
    if status.gpio_frames_emitted != gpio_wire:
        issues.append(
            "firmware emitted "
            f"{status.gpio_frames_emitted} GPIO frame(s), but the host parser "
            f"received {gpio_wire}"
        )
    adc_accounted = (
        validator.adc_frames_validated + adc_queue_drops + adc_boundary + adc_stale
    )
    gpio_accounted = (
        validator.gpio_frames_validated + gpio_queue_drops + gpio_boundary + gpio_stale
    )
    if adc_wire != adc_accounted:
        issues.append(
            f"host ADC conservation is {adc_wire} received != "
            f"{adc_accounted} validated/dropped/discarded"
        )
    if gpio_wire != gpio_accounted:
        issues.append(
            f"host GPIO conservation is {gpio_wire} received != "
            f"{gpio_accounted} validated/dropped/discarded"
        )
    if status.adc_items_dropped or status.gpio_items_dropped:
        issues.append("firmware reported dropped logical items")
    if status.parser_errors:
        issues.append("firmware reported parser errors")
    if status.transport_errors:
        issues.append("firmware reported transport errors")
    if parser_errors:
        issues.append("host parser rejected frame candidates")
    if adc_queue_drops or gpio_queue_drops:
        issues.append("host decoded-block queue dropped frames")
    if event_drops:
        issues.append("host event queue dropped frames")

    return CounterReconciliation(
        adc_firmware_frames_emitted=status.adc_frames_emitted,
        gpio_firmware_frames_emitted=status.gpio_frames_emitted,
        adc_wire_frames_received=adc_wire,
        gpio_wire_frames_received=gpio_wire,
        adc_validated_frames=validator.adc_frames_validated,
        gpio_validated_frames=validator.gpio_frames_validated,
        adc_host_queue_drops=adc_queue_drops,
        gpio_host_queue_drops=gpio_queue_drops,
        adc_boundary_discards=adc_boundary,
        gpio_boundary_discards=gpio_boundary,
        adc_stale_discards=adc_stale,
        gpio_stale_discards=gpio_stale,
        firmware_adc_items_dropped=status.adc_items_dropped,
        firmware_gpio_items_dropped=status.gpio_items_dropped,
        firmware_parser_errors=status.parser_errors,
        firmware_transport_errors=status.transport_errors,
        host_parser_errors=parser_errors,
        host_event_queue_drops=event_drops,
        issues=tuple(issues),
    )


def _wait_for_final_status(
    daq: ThingDAQ,
    recorder: _LatencyRecorder,
    baseline: ReaderCounters,
    *,
    timeout: float,
    quiet_period: float,
    clock: Callable[[], float] = monotonic,
    sleeper: Callable[[float], None] = sleep,
) -> Status:
    deadline = clock() + timeout
    stable_since: float | None = None
    previous: tuple[int, int, int, int] | None = None
    latest: Status | None = None

    while True:
        latest = _timed(recorder, "STATUS", daq.status, clock=clock)
        reader = daq.reader_counters
        adc_wire = _reader_delta(
            "ADC received counter",
            reader.adc_frames_received,
            baseline.adc_frames_received,
        )
        gpio_wire = _reader_delta(
            "GPIO received counter",
            reader.gpio_frames_received,
            baseline.gpio_frames_received,
        )
        current = (
            latest.adc_frames_emitted,
            latest.gpio_frames_emitted,
            adc_wire,
            gpio_wire,
        )
        now = clock()
        balanced = current[0] == current[2] and current[1] == current[3]
        if balanced and current == previous:
            if stable_since is None:
                stable_since = now
            if now - stable_since >= quiet_period:
                return latest
        else:
            stable_since = None
        if now >= deadline:
            return latest
        previous = current
        sleeper(min(0.005, max(0.0, deadline - now)))


def run_synthetic_soak(
    daq: ThingDAQ,
    *,
    duration: float | None = None,
    frame_count: int | None = None,
    adc: bool = True,
    gpio: bool = True,
    status_interval: float | None = 0.25,
    status_frame_interval: int | None = None,
    block_timeout: float = 1.0,
    drain_timeout: float = 1.0,
    drain_quiet_period: float = 0.02,
    max_latency_samples: int = 4096,
    track_memory: bool = True,
    adc_pair_rate_hz: int | None = None,
    gpio_sample_rate_hz: int | None = None,
    adc_resolution_bits: int | None = None,
    clock: Callable[[], float] = monotonic,
    sleeper: Callable[[float], None] = sleep,
) -> SoakMetrics:
    """Run, validate, stop, and reconcile one bounded synthetic acquisition.

    Exactly one of ``duration`` or ``frame_count`` selects the capture bound.
    ``frame_count`` counts complete ADC/GPIO blocks and is useful for fast,
    deterministic offline checks; real soak runs normally use ``duration``.
    ``status_frame_interval`` provides deterministic frame-budget STATUS
    sampling, while the rate/resolution arguments make fixed-profile
    requirements explicit at CONFIGURE. Injectable clock/sleeper callables are
    intended for deterministic host tests and do not alter device time.
    The supplied facade remains open but is left in IDLE.
    """

    if (duration is None) == (frame_count is None):
        raise ValueError("pass exactly one of duration or frame_count")
    selected_duration = (
        None if duration is None else _positive_seconds("duration", duration)
    )
    if frame_count is not None and (
        not isinstance(frame_count, int)
        or isinstance(frame_count, bool)
        or frame_count <= 0
    ):
        raise ValueError("frame_count must be a positive integer")
    if not isinstance(adc, bool) or not isinstance(gpio, bool) or not (adc or gpio):
        raise ValueError("at least one boolean stream selector must be enabled")
    selected_block_timeout = _positive_seconds("block_timeout", block_timeout)
    selected_drain_timeout = _positive_seconds("drain_timeout", drain_timeout)
    selected_drain_quiet_period = _positive_seconds(
        "drain_quiet_period",
        drain_quiet_period,
    )
    selected_status_interval = (
        None
        if status_interval is None
        else _positive_seconds("status_interval", status_interval)
    )
    if status_frame_interval is not None and (
        not isinstance(status_frame_interval, int)
        or isinstance(status_frame_interval, bool)
        or status_frame_interval <= 0
    ):
        raise ValueError("status_frame_interval must be a positive integer or None")
    if (
        not isinstance(max_latency_samples, int)
        or isinstance(max_latency_samples, bool)
        or max_latency_samples <= 0
    ):
        raise ValueError("max_latency_samples must be a positive integer")
    if not isinstance(track_memory, bool):
        raise TypeError("track_memory must be a boolean")
    if not callable(clock):
        raise TypeError("clock must be callable")
    if not callable(sleeper):
        raise TypeError("sleeper must be callable")
    if daq.state not in {constants.DeviceState.IDLE, constants.DeviceState.CONFIGURED}:
        raise ValueError("synthetic soak requires an IDLE or CONFIGURED facade")

    requested_mask = constants.StreamMask.NONE
    if adc:
        requested_mask |= constants.StreamMask.ADC
    if gpio:
        requested_mask |= constants.StreamMask.GPIO

    latency = _LatencyRecorder(max_latency_samples)
    memory = _MemoryTracker(track_memory)
    memory.start()
    configured_here = False
    started = False
    primary_error: BaseException | None = None
    cleanup_error: BaseException | None = None
    final_status: Status | None = None
    validator: SyntheticStreamValidator | None = None
    baseline_reader: ReaderCounters | None = None
    baseline_parser: ParserCounters | None = None
    run_id = 0
    adc_frames = 0
    gpio_frames = 0
    capture_started = clock()
    capture_finished = capture_started

    try:
        if daq.state is constants.DeviceState.IDLE:
            applied = _timed(
                latency,
                "CONFIGURE",
                lambda: daq.configure(
                    adc=adc,
                    gpio=gpio,
                    source=constants.Source.SYNTHETIC,
                    adc_pair_rate_hz=adc_pair_rate_hz,
                    gpio_sample_rate_hz=gpio_sample_rate_hz,
                    adc_resolution_bits=adc_resolution_bits,
                ),
                clock=clock,
            )
            configured_here = True
        else:
            existing_configuration = daq.configuration
            if existing_configuration is None:
                raise ValueError("CONFIGURED facade has no applied configuration")
            applied = existing_configuration
        if (
            applied.stream_mask != requested_mask
            or applied.source is not constants.Source.SYNTHETIC
        ):
            raise ValueError("applied configuration does not match the requested soak")

        baseline_reader = daq.reader_counters
        baseline_parser = daq.parser_counters
        run_id = _timed(latency, "START", daq.start, clock=clock)
        started = True
        validator = SyntheticStreamValidator(
            run_id,
            requested_mask,
            reader_baseline=baseline_reader,
            parser_baseline=baseline_parser,
        )
        capture_started = clock()
        deadline = (
            None if selected_duration is None else capture_started + selected_duration
        )
        next_status = (
            None
            if selected_status_interval is None
            else capture_started + selected_status_interval
        )
        total_frames = 0

        while frame_count is None or total_frames < frame_count:
            now = clock()
            if deadline is not None and now >= deadline:
                break
            if next_status is not None and now >= next_status:
                assert selected_status_interval is not None
                status = _timed(latency, "STATUS", daq.status, clock=clock)
                validator.validate_status(status, response_run_id=daq.run_id)
                validator.validate_host_health(
                    daq.reader_counters,
                    daq.parser_counters,
                )
                next_status = clock() + selected_status_interval
                continue

            wait_timeout = selected_block_timeout
            if deadline is not None:
                wait_timeout = min(wait_timeout, max(1e-9, deadline - now))
            try:
                item = daq.read_block(timeout=wait_timeout)
            except BlockTimeoutError:
                if deadline is not None and clock() >= deadline:
                    break
                raise
            block = validator.validate(item)
            if isinstance(block, ADCBlock):
                adc_frames += 1
            else:
                gpio_frames += 1
            total_frames += 1
            if (
                status_frame_interval is not None
                and total_frames % status_frame_interval == 0
            ):
                status = _timed(latency, "STATUS", daq.status, clock=clock)
                validator.validate_status(status, response_run_id=daq.run_id)
                validator.validate_host_health(
                    daq.reader_counters,
                    daq.parser_counters,
                )
            if total_frames % 32 == 0:
                validator.validate_host_health(
                    daq.reader_counters,
                    daq.parser_counters,
                )
        capture_finished = clock()
        validator.validate_host_health(daq.reader_counters, daq.parser_counters)
    except BaseException as error:  # noqa: BLE001 - cleanup must still STOP
        capture_finished = clock()
        primary_error = error
    finally:
        stop_cleanup_error: BaseException | None = None
        try:
            if started or configured_here:
                _timed(latency, "STOP", daq.stop, clock=clock)
        except BaseException as error:  # noqa: BLE001 - still attempt STATUS
            stop_cleanup_error = error

        status_cleanup_error: BaseException | None = None
        try:
            if started and baseline_reader is not None:
                final_status = _wait_for_final_status(
                    daq,
                    latency,
                    baseline_reader,
                    timeout=selected_drain_timeout,
                    quiet_period=min(
                        selected_drain_quiet_period,
                        selected_drain_timeout,
                    ),
                    clock=clock,
                    sleeper=sleeper,
                )
            elif configured_here:
                final_status = _timed(
                    latency,
                    "STATUS",
                    daq.status,
                    clock=clock,
                )
        except BaseException as error:  # noqa: BLE001 - preserve primary failure
            status_cleanup_error = error
        cleanup_error = stop_cleanup_error or status_cleanup_error

    memory_metrics = memory.finish()
    if primary_error is not None:
        if cleanup_error is not None:
            raise primary_error from cleanup_error
        raise primary_error
    if cleanup_error is not None:
        raise cleanup_error
    if (
        final_status is None
        or validator is None
        or baseline_reader is None
        or baseline_parser is None
    ):
        raise RuntimeError("synthetic soak completed without final metrics")

    final_reader = daq.reader_counters
    final_parser = daq.parser_counters
    validator.validate_status(
        final_status,
        response_run_id=daq.run_id,
        final=True,
    )
    validator.validate_host_health(final_reader, final_parser, after_stop=True)
    reconciliation = _reconcile(
        status=final_status,
        baseline_reader=baseline_reader,
        final_reader=final_reader,
        baseline_parser=baseline_parser,
        final_parser=final_parser,
        validator=validator,
    )
    reconciliation.require_exact()

    elapsed = max(capture_finished - capture_started, 1e-12)
    adc_metrics = StreamRateMetrics(
        frame_count=adc_frames,
        item_count=adc_frames * constants.ADC_PAIRS_PER_FRAME,
        payload_bytes=adc_frames * constants.ADC_DATA_PAYLOAD_SIZE,
        framed_bytes=adc_frames * constants.DATA_FRAME_BYTES,
        elapsed_seconds=elapsed,
    )
    gpio_metrics = StreamRateMetrics(
        frame_count=gpio_frames,
        item_count=gpio_frames * constants.GPIO_SAMPLES_PER_FRAME,
        payload_bytes=gpio_frames * constants.GPIO_DATA_PAYLOAD_SIZE,
        framed_bytes=gpio_frames * constants.DATA_FRAME_BYTES,
        elapsed_seconds=elapsed,
    )
    queues = QueueDepthMetrics(
        pending_requests=final_reader.pending_requests,
        queued_blocks=final_reader.queued_blocks,
        queued_events=final_reader.queued_events,
        pending_request_high_water=final_reader.pending_request_high_water,
        block_queue_high_water=final_reader.block_queue_high_water,
        event_queue_high_water=final_reader.event_queue_high_water,
        parser_buffered_bytes=final_parser.buffered_bytes,
        parser_high_water_bytes=final_parser.high_water_mark,
        reusable_read_buffer_bytes=daq.reader.read_buffer_size,
        maximum_read_bytes=final_reader.maximum_read_bytes,
    )
    return SoakMetrics(
        run_id=run_id,
        elapsed_seconds=elapsed,
        adc=adc_metrics,
        gpio=gpio_metrics,
        command_latency=latency.snapshot(),
        queues=queues,
        memory=memory_metrics,
        final_status=final_status,
        reader_counters=final_reader,
        parser_counters=final_parser,
        reconciliation=reconciliation,
    )


__all__ = [
    "CommandLatencyDistribution",
    "CounterReconciliation",
    "MemoryHighWaterMetrics",
    "QueueDepthMetrics",
    "SoakMetrics",
    "StreamRateMetrics",
    "SyntheticStreamValidator",
    "run_synthetic_soak",
]
