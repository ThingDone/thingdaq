"""Bounded, allocation-light alignment of ADC and GPIO timestamp intervals."""

from __future__ import annotations

from collections.abc import Iterable, Iterator
from dataclasses import dataclass
from enum import Enum
from typing import TypeAlias

from ._generated import protocol_constants as constants
from .models import ADCBlock, GPIOBlock, RateProfile, StreamGap

_BOTH_STREAMS = constants.StreamMask.ADC | constants.StreamMask.GPIO


def _unsigned(name: str, value: int, bits: int) -> None:
    if (
        not isinstance(value, int)
        or isinstance(value, bool)
        or not 0 <= value < (1 << bits)
    ):
        raise ValueError(f"{name} must be an unsigned {bits}-bit integer")


def _block_kind(block: ADCBlock | GPIOBlock) -> constants.FrameKind:
    return (
        constants.FrameKind.ADC_DATA
        if isinstance(block, ADCBlock)
        else constants.FrameKind.GPIO_DATA
    )


def _gap_signature(gap: StreamGap) -> tuple[object, ...]:
    """Return continuity evidence, excluding optional host-drop attribution."""

    return (
        gap.kind,
        gap.run_id,
        gap.expected_sequence,
        gap.observed_sequence,
        gap.missing_frames,
        gap.missing_items,
        gap.expected_first_sample_ticks,
        gap.observed_first_sample_ticks,
        gap.firmware_reported,
        gap.firmware_overrun,
        gap.item_period_ticks,
        gap.items_per_frame,
    )


def _block_coverage_ticks(block: ADCBlock | GPIOBlock) -> int:
    return block.item_count * (
        block.pair_period_ticks
        if isinstance(block, ADCBlock)
        else block.sample_period_ticks
    )


def _block_profile_signature(block: ADCBlock | GPIOBlock) -> tuple[int, int, int]:
    return (
        block.protocol_version,
        int(block.aux_bank_mode),
        int(block.rate_profile),
    )


class TimestampAlignmentError(ValueError):
    """Input cannot be placed on one bounded, monotonic run timeline."""


class AlignmentLossReason(Enum):
    """Why an interval left the aligner without both source blocks."""

    WINDOW_EXPIRED = "window_expired"
    EXPLICIT_FLUSH = "explicit_flush"
    END_OF_INPUT = "end_of_input"
    RUN_BOUNDARY = "run_boundary"


@dataclass(frozen=True, slots=True)
class NominalEpoch:
    """The advertised START-relative schedule, not an external timing measure.

    Tick zero is the common firmware START epoch. ``external_latency_ticks`` is
    deliberately always ``None`` because protocol v1 does not measure GPIO-pad
    propagation or either ADC's analog aperture latency.
    """

    run_id: int
    timestamp_hz: int = constants.TIMESTAMP_HZ
    external_latency_ticks: None = None

    def __post_init__(self) -> None:
        _unsigned("run_id", self.run_id, 32)
        if self.run_id == 0:
            raise ValueError("nominal epochs require a nonzero run ID")
        if (
            not isinstance(self.timestamp_hz, int)
            or isinstance(self.timestamp_hz, bool)
            or self.timestamp_hz != constants.TIMESTAMP_HZ
        ):
            raise ValueError("protocol v1 requires the advertised 8 MHz timebase")
        if self.external_latency_ticks is not None:
            raise ValueError("external pad/aperture latency is not measured")

    @property
    def start_ticks(self) -> int:
        return 0

    @property
    def start_seconds(self) -> float:
        return 0.0

    @property
    def seconds_per_tick(self) -> float:
        return 1.0 / self.timestamp_hz

    def seconds_at(self, ticks: int) -> float:
        """Convert a run-relative nominal tick without adding latency claims."""

        _unsigned("ticks", ticks, 64)
        return ticks / self.timestamp_hz


@dataclass(frozen=True, slots=True)
class AlignedInterval:
    """One equal-duration ADC/GPIO interval retaining the original blocks.

    A missing source is represented by ``None`` and by ``missing_streams``.
    Payload accessors return views over each original immutable block; the
    model never builds an interleaved combined payload.
    """

    adc: ADCBlock | None = None
    gpio: GPIOBlock | None = None
    stream_gaps: tuple[StreamGap, ...] = ()

    def __post_init__(self) -> None:
        if self.adc is None and self.gpio is None:
            raise ValueError("an aligned interval requires at least one source block")
        if self.adc is not None and not isinstance(self.adc, ADCBlock):
            raise TypeError("adc must be ADCBlock or None")
        if self.gpio is not None and not isinstance(self.gpio, GPIOBlock):
            raise TypeError("gpio must be GPIOBlock or None")

        reference: ADCBlock | GPIOBlock
        if self.adc is not None:
            reference = self.adc
        else:
            assert self.gpio is not None
            reference = self.gpio
        coverage_ticks = _block_coverage_ticks(reference)
        duration = (
            reference.end_tick_exclusive - reference.first_sample_ticks
        ) & constants.UINT64_MAX
        if duration != coverage_ticks:
            raise ValueError("source block does not cover one selected interval")
        if reference.first_sample_ticks % coverage_ticks:
            raise ValueError("source block is not aligned to a frame interval")
        if reference.first_sample_ticks + coverage_ticks > constants.UINT64_MAX:
            raise ValueError("aligned intervals cannot cross timestamp wrap")

        if self.adc is not None and self.gpio is not None:
            if self.adc.run_id != self.gpio.run_id:
                raise ValueError("ADC and GPIO blocks belong to different runs")
            if self.adc.source is not self.gpio.source:
                raise ValueError("ADC and GPIO blocks report different sources")
            if self.adc.first_sample_ticks != self.gpio.first_sample_ticks:
                raise ValueError("ADC and GPIO blocks start at different timestamps")
            if self.adc.end_tick_exclusive != self.gpio.end_tick_exclusive:
                raise ValueError("ADC and GPIO blocks cover different intervals")
            if _block_profile_signature(self.adc) != _block_profile_signature(
                self.gpio
            ):
                raise ValueError("ADC and GPIO blocks use different selected profiles")

        gaps = tuple(self.stream_gaps)
        seen_kinds: set[constants.FrameKind] = set()
        for gap in gaps:
            if not isinstance(gap, StreamGap):
                raise TypeError("stream_gaps must contain StreamGap values")
            block = self.adc if gap.kind is constants.FrameKind.ADC_DATA else self.gpio
            if (
                block is None
                or gap.kind in seen_kinds
                or gap.run_id != block.run_id
                or gap.observed_sequence != block.sequence
                or gap.observed_first_sample_ticks != block.first_sample_ticks
            ):
                raise ValueError("stream gap does not describe a present source block")
            seen_kinds.add(gap.kind)
        object.__setattr__(self, "stream_gaps", gaps)

    @property
    def run_id(self) -> int:
        if self.adc is not None:
            return self.adc.run_id
        assert self.gpio is not None
        return self.gpio.run_id

    @property
    def source(self) -> constants.Source:
        if self.adc is not None:
            return self.adc.source
        assert self.gpio is not None
        return self.gpio.source

    @property
    def epoch(self) -> NominalEpoch:
        return NominalEpoch(self.run_id)

    @property
    def first_sample_ticks(self) -> int:
        if self.adc is not None:
            return self.adc.first_sample_ticks
        assert self.gpio is not None
        return self.gpio.first_sample_ticks

    @property
    def end_tick_exclusive(self) -> int:
        return (
            self.first_sample_ticks + self.frame_coverage_ticks
        ) & constants.UINT64_MAX

    @property
    def duration_ticks(self) -> int:
        return self.frame_coverage_ticks

    @property
    def frame_coverage_ticks(self) -> int:
        if self.adc is not None:
            return _block_coverage_ticks(self.adc)
        assert self.gpio is not None
        return _block_coverage_ticks(self.gpio)

    @property
    def nominal_start_seconds(self) -> float:
        return self.epoch.seconds_at(self.first_sample_ticks)

    @property
    def nominal_end_seconds(self) -> float:
        return self.epoch.seconds_at(self.end_tick_exclusive)

    @property
    def nominal_duration_seconds(self) -> float:
        return self.duration_ticks / constants.TIMESTAMP_HZ

    @property
    def present_streams(self) -> constants.StreamMask:
        streams = constants.StreamMask.NONE
        if self.adc is not None:
            streams |= constants.StreamMask.ADC
        if self.gpio is not None:
            streams |= constants.StreamMask.GPIO
        return streams

    @property
    def missing_streams(self) -> constants.StreamMask:
        return constants.StreamMask(int(_BOTH_STREAMS) ^ int(self.present_streams))

    @property
    def complete(self) -> bool:
        return self.present_streams == _BOTH_STREAMS

    @property
    def has_stream_gap(self) -> bool:
        return bool(self.stream_gaps)

    @property
    def adc_payload_view(self) -> memoryview | None:
        return None if self.adc is None else self.adc.payload_view

    @property
    def gpio_payload_view(self) -> memoryview | None:
        return None if self.gpio is None else self.gpio.payload_view

    def adc_pair_ticks(self, index: int) -> tuple[int, int] | None:
        """Return nominal ADC0/ADC1 ticks, or ``None`` when ADC is missing."""

        return None if self.adc is None else self.adc.pair_ticks(index)

    def adc_pair_seconds(self, index: int) -> tuple[float, float] | None:
        ticks = self.adc_pair_ticks(index)
        if ticks is None:
            return None
        return self.epoch.seconds_at(ticks[0]), self.epoch.seconds_at(ticks[1])

    def gpio_sample_ticks(self, index: int) -> int | None:
        """Return one nominal packed-byte tick, or ``None`` if GPIO is missing."""

        return None if self.gpio is None else self.gpio.sample_ticks(index)

    def gpio_sample_seconds(self, index: int) -> float | None:
        ticks = self.gpio_sample_ticks(index)
        return None if ticks is None else self.epoch.seconds_at(ticks)


@dataclass(frozen=True, slots=True)
class AlignmentLoss:
    """An interval range that could not be emitted with both stream sides."""

    reason: AlignmentLossReason
    run_id: int
    source: constants.Source
    first_sample_ticks: int
    interval_count: int
    present_streams: constants.StreamMask
    missing_streams: constants.StreamMask
    frame_coverage_ticks: int = constants.FRAME_COVERAGE_TICKS

    def __post_init__(self) -> None:
        if not isinstance(self.reason, AlignmentLossReason):
            raise TypeError("reason must be AlignmentLossReason")
        _unsigned("run_id", self.run_id, 32)
        _unsigned("first_sample_ticks", self.first_sample_ticks, 64)
        if self.run_id == 0:
            raise ValueError("alignment loss requires a nonzero run ID")
        if (
            not isinstance(self.frame_coverage_ticks, int)
            or isinstance(self.frame_coverage_ticks, bool)
            or self.frame_coverage_ticks <= 0
        ):
            raise ValueError("frame_coverage_ticks must be a positive integer")
        if self.first_sample_ticks % self.frame_coverage_ticks:
            raise ValueError("alignment loss must begin on a frame interval")
        if (
            not isinstance(self.interval_count, int)
            or isinstance(self.interval_count, bool)
            or self.interval_count <= 0
        ):
            raise ValueError("interval_count must be a positive integer")
        if isinstance(self.source, bool):
            raise TypeError("source must be HARDWARE or SYNTHETIC")
        if isinstance(self.present_streams, bool) or isinstance(
            self.missing_streams, bool
        ):
            raise TypeError("present/missing stream masks cannot be booleans")
        try:
            source = constants.Source(self.source)
            present = constants.StreamMask(self.present_streams)
            missing = constants.StreamMask(self.missing_streams)
        except (TypeError, ValueError) as exc:
            raise ValueError("alignment loss contains an unknown source/mask") from exc
        if int(present) & ~int(_BOTH_STREAMS) or int(missing) & ~int(_BOTH_STREAMS):
            raise ValueError("alignment loss contains unsupported stream bits")
        if not missing or present & missing or present | missing != _BOTH_STREAMS:
            raise ValueError("present and missing streams must partition ADC/GPIO")
        duration = self.interval_count * self.frame_coverage_ticks
        if self.first_sample_ticks + duration > constants.UINT64_MAX:
            raise ValueError("alignment loss crosses unsupported timestamp wrap")
        object.__setattr__(self, "source", source)
        object.__setattr__(self, "present_streams", present)
        object.__setattr__(self, "missing_streams", missing)

    @property
    def epoch(self) -> NominalEpoch:
        return NominalEpoch(self.run_id)

    @property
    def missing_duration_ticks(self) -> int:
        return self.interval_count * self.frame_coverage_ticks

    @property
    def end_tick_exclusive(self) -> int:
        return self.first_sample_ticks + self.missing_duration_ticks

    @property
    def nominal_start_seconds(self) -> float:
        return self.epoch.seconds_at(self.first_sample_ticks)

    @property
    def nominal_end_seconds(self) -> float:
        return self.epoch.seconds_at(self.end_tick_exclusive)


AlignmentInput: TypeAlias = ADCBlock | GPIOBlock | StreamGap
AlignmentItem: TypeAlias = AlignedInterval | AlignmentLoss | StreamGap


@dataclass(slots=True)
class _PendingInterval:
    adc: ADCBlock | None = None
    gpio: GPIOBlock | None = None

    @property
    def complete(self) -> bool:
        return self.adc is not None and self.gpio is not None

    @property
    def present_streams(self) -> constants.StreamMask:
        streams = constants.StreamMask.NONE
        if self.adc is not None:
            streams |= constants.StreamMask.ADC
        if self.gpio is not None:
            streams |= constants.StreamMask.GPIO
        return streams


@dataclass(frozen=True, slots=True)
class _ContinuityResult:
    block: ADCBlock | GPIOBlock
    gap: StreamGap | None
    emit_gap: bool
    announced_key: tuple[constants.FrameKind, int, int, int] | None


class TimestampAligner:
    """Pair equal timestamp intervals with bounded out-of-order retention.

    ``max_pending_intervals`` is an event-time lateness window. Once a newer
    timestamp advances that many frame intervals beyond the oldest unresolved
    timestamp, the old interval is emitted with an :class:`AlignmentLoss`.
    ``flush()`` provides a finite wall-clock/STOP boundary for a final delayed
    side; the helper itself never blocks or owns the serial reader.
    """

    def __init__(self, *, max_pending_intervals: int = 8) -> None:
        if (
            not isinstance(max_pending_intervals, int)
            or isinstance(max_pending_intervals, bool)
            or max_pending_intervals <= 0
        ):
            raise ValueError("max_pending_intervals must be a positive integer")
        self._max_pending_intervals = max_pending_intervals
        self._pending: dict[int, _PendingInterval] = {}
        self._announced_gaps: dict[
            tuple[constants.FrameKind, int, int, int], StreamGap
        ] = {}
        self._active_run_id: int | None = None
        self._active_source: constants.Source | None = None
        self._frame_coverage_ticks: int | None = None
        self._profile_signature: tuple[int, int, int] | None = None
        self._next_output_ticks = 0
        self._expected_sequence = {
            constants.FrameKind.ADC_DATA: 0,
            constants.FrameKind.GPIO_DATA: 0,
        }
        self._expected_ticks = {
            constants.FrameKind.ADC_DATA: 0,
            constants.FrameKind.GPIO_DATA: 0,
        }
        self._high_water_intervals = 0
        self._closed = False

    @property
    def max_pending_intervals(self) -> int:
        return self._max_pending_intervals

    @property
    def pending_intervals(self) -> int:
        return len(self._pending)

    @property
    def high_water_intervals(self) -> int:
        return self._high_water_intervals

    @property
    def active_run_id(self) -> int | None:
        return self._active_run_id

    @property
    def active_source(self) -> constants.Source | None:
        return self._active_source

    @property
    def frame_coverage_ticks(self) -> int | None:
        return self._frame_coverage_ticks

    def push(self, item: AlignmentInput) -> tuple[AlignmentItem, ...]:
        """Accept one arrival and return every now-resolved event/interval."""

        if self._closed:
            raise TimestampAlignmentError("cannot push after finish()")
        if isinstance(item, StreamGap):
            return tuple(self._push_announced_gap(item))
        if not isinstance(item, (ADCBlock, GPIOBlock)):
            raise TypeError("alignment input must be ADCBlock, GPIOBlock, or StreamGap")
        if item.rate_profile is RateProfile.ADC_1MHZ_GPIO_1MHZ:
            raise TimestampAlignmentError(
                "equal-rate acquisition has four ADC frames per GPIO frame; "
                "use read_block()/blocks() and the per-sample timestamps"
            )

        self._validate_block_interval(item)
        outputs = self._activate_epoch(
            item.run_id,
            item.source,
            frame_coverage_ticks=_block_coverage_ticks(item),
            profile_signature=_block_profile_signature(item),
        )
        if item.first_sample_ticks < self._next_output_ticks:
            raise TimestampAlignmentError(
                f"late or reordered {_block_kind(item).name} interval at "
                f"{item.first_sample_ticks}; alignment already emitted through "
                f"{self._next_output_ticks}"
            )
        existing_slot = self._pending.get(item.first_sample_ticks)
        if (
            isinstance(item, ADCBlock)
            and existing_slot is not None
            and existing_slot.adc is not None
        ):
            raise TimestampAlignmentError(
                f"duplicate ADC interval at {item.first_sample_ticks}"
            )
        if (
            isinstance(item, GPIOBlock)
            and existing_slot is not None
            and existing_slot.gpio is not None
        ):
            raise TimestampAlignmentError(
                f"duplicate GPIO interval at {item.first_sample_ticks}"
            )

        outputs.extend(self._drain(item.first_sample_ticks))
        slot = self._pending.get(item.first_sample_ticks)
        if slot is None:
            slot = _PendingInterval()
            self._pending[item.first_sample_ticks] = slot
        if isinstance(item, ADCBlock):
            assert slot.adc is None
            slot.adc = item
        else:
            assert slot.gpio is None
            slot.gpio = item

        self._high_water_intervals = max(
            self._high_water_intervals,
            len(self._pending),
        )
        outputs.extend(self._drain(max(self._pending)))
        if len(self._pending) > self._max_pending_intervals:
            raise AssertionError("timestamp aligner exceeded its configured bound")
        return tuple(outputs)

    def flush(self) -> tuple[AlignmentItem, ...]:
        """Emit every buffered interval now, explicitly marking missing sides."""

        if self._closed:
            return ()
        return tuple(self._flush_pending(AlignmentLossReason.EXPLICIT_FLUSH))

    def finish(self) -> tuple[AlignmentItem, ...]:
        """Flush an end-of-input boundary and reject any later input."""

        if self._closed:
            return ()
        outputs = self._flush_pending(AlignmentLossReason.END_OF_INPUT)
        self._announced_gaps.clear()
        self._closed = True
        return tuple(outputs)

    def _activate_epoch(
        self,
        run_id: int,
        source: constants.Source | None,
        *,
        frame_coverage_ticks: int,
        profile_signature: tuple[int, int, int] | None = None,
    ) -> list[AlignmentItem]:
        outputs: list[AlignmentItem] = []
        if self._active_run_id is None:
            self._start_epoch(
                run_id,
                source,
                frame_coverage_ticks=frame_coverage_ticks,
                profile_signature=profile_signature,
            )
            return outputs
        if run_id != self._active_run_id:
            outputs.extend(self._flush_pending(AlignmentLossReason.RUN_BOUNDARY))
            self._start_epoch(
                run_id,
                source,
                frame_coverage_ticks=frame_coverage_ticks,
                profile_signature=profile_signature,
            )
            return outputs
        if frame_coverage_ticks != self._frame_coverage_ticks:
            raise TimestampAlignmentError(
                f"frame coverage changed within run {run_id}: "
                f"{self._frame_coverage_ticks} to {frame_coverage_ticks} ticks"
            )
        if profile_signature is not None:
            if self._profile_signature is None:
                self._profile_signature = profile_signature
            elif profile_signature != self._profile_signature:
                raise TimestampAlignmentError(
                    f"mode/rate profile changed within run {run_id}"
                )
        if source is not None:
            if self._active_source is None:
                self._active_source = source
            elif source is not self._active_source:
                raise TimestampAlignmentError(
                    f"source changed within run {run_id}: "
                    f"{self._active_source.name} to {source.name}"
                )
        return outputs

    def _start_epoch(
        self,
        run_id: int,
        source: constants.Source | None,
        *,
        frame_coverage_ticks: int,
        profile_signature: tuple[int, int, int] | None,
    ) -> None:
        _unsigned("run_id", run_id, 32)
        if run_id == 0:
            raise TimestampAlignmentError("alignment input requires a nonzero run ID")
        if (
            not isinstance(frame_coverage_ticks, int)
            or isinstance(frame_coverage_ticks, bool)
            or frame_coverage_ticks <= 0
        ):
            raise TimestampAlignmentError("frame coverage must be positive")
        self._pending.clear()
        self._announced_gaps.clear()
        self._active_run_id = run_id
        self._active_source = source
        self._frame_coverage_ticks = frame_coverage_ticks
        self._profile_signature = profile_signature
        self._next_output_ticks = 0
        for kind in self._expected_sequence:
            self._expected_sequence[kind] = 0
            self._expected_ticks[kind] = 0

    def _push_announced_gap(self, gap: StreamGap) -> list[AlignmentItem]:
        coverage_ticks = gap.item_period_ticks * gap.items_per_frame
        if (
            gap.expected_first_sample_ticks % coverage_ticks
            or gap.observed_first_sample_ticks % coverage_ticks
        ):
            raise TimestampAlignmentError(
                "stream gap is not aligned to selected frame coverage"
            )
        outputs = self._activate_epoch(
            gap.run_id,
            None,
            frame_coverage_ticks=coverage_ticks,
        )
        if gap.observed_first_sample_ticks < self._next_output_ticks:
            raise TimestampAlignmentError(
                "stream gap describes an already emitted interval"
            )
        key = (
            gap.kind,
            gap.run_id,
            gap.observed_sequence,
            gap.observed_first_sample_ticks,
        )
        if key in self._announced_gaps:
            raise TimestampAlignmentError("duplicate StreamGap announcement")
        if len(self._announced_gaps) >= 2 * self._max_pending_intervals:
            raise TimestampAlignmentError("unmatched StreamGap storage is full")
        self._announced_gaps[key] = gap
        outputs.append(gap)
        return outputs

    @staticmethod
    def _validate_block_interval(block: ADCBlock | GPIOBlock) -> None:
        coverage_ticks = _block_coverage_ticks(block)
        duration = (
            block.end_tick_exclusive - block.first_sample_ticks
        ) & constants.UINT64_MAX
        if duration != coverage_ticks:
            raise TimestampAlignmentError(
                f"{_block_kind(block).name} does not cover one frame interval"
            )
        if block.first_sample_ticks % coverage_ticks:
            raise TimestampAlignmentError(
                f"{_block_kind(block).name} timestamp is not frame aligned"
            )
        if block.first_sample_ticks + coverage_ticks > constants.UINT64_MAX:
            raise TimestampAlignmentError(
                f"{_block_kind(block).name} interval crosses timestamp wrap"
            )

    def _drain(self, highest_seen_ticks: int) -> list[AlignmentItem]:
        outputs: list[AlignmentItem] = []
        coverage_ticks = self._required_frame_coverage_ticks()
        while self._pending:
            slot = self._pending.get(self._next_output_ticks)
            if slot is not None and slot.complete:
                outputs.extend(self._emit_slot(self._next_output_ticks, None))
                continue
            if highest_seen_ticks < self._next_output_ticks:
                break
            span = (highest_seen_ticks - self._next_output_ticks) // coverage_ticks
            if span < self._max_pending_intervals:
                break
            if slot is not None:
                outputs.extend(
                    self._emit_slot(
                        self._next_output_ticks,
                        AlignmentLossReason.WINDOW_EXPIRED,
                    )
                )
                continue

            eligible_count = span - self._max_pending_intervals + 1
            next_pending_ticks = min(self._pending)
            pending_distance = (
                next_pending_ticks - self._next_output_ticks
            ) // coverage_ticks
            interval_count = min(eligible_count, pending_distance)
            if interval_count <= 0:
                raise AssertionError("timestamp drain made no progress")
            outputs.append(
                self._alignment_loss(
                    AlignmentLossReason.WINDOW_EXPIRED,
                    self._next_output_ticks,
                    interval_count,
                    constants.StreamMask.NONE,
                )
            )
            self._advance(interval_count)
        return outputs

    def _flush_pending(self, reason: AlignmentLossReason) -> list[AlignmentItem]:
        outputs: list[AlignmentItem] = []
        coverage_ticks = self._required_frame_coverage_ticks()
        while self._pending:
            next_pending_ticks = min(self._pending)
            if next_pending_ticks < self._next_output_ticks:
                raise TimestampAlignmentError("pending timestamp moved behind output")
            if next_pending_ticks > self._next_output_ticks:
                delta = next_pending_ticks - self._next_output_ticks
                if delta % coverage_ticks:
                    raise TimestampAlignmentError(
                        "pending timestamp is not frame aligned"
                    )
                interval_count = delta // coverage_ticks
                outputs.append(
                    self._alignment_loss(
                        reason,
                        self._next_output_ticks,
                        interval_count,
                        constants.StreamMask.NONE,
                    )
                )
                self._advance(interval_count)
                continue
            slot = self._pending[next_pending_ticks]
            outputs.extend(
                self._emit_slot(
                    next_pending_ticks,
                    None if slot.complete else reason,
                )
            )
        return outputs

    def _emit_slot(
        self,
        ticks: int,
        loss_reason: AlignmentLossReason | None,
    ) -> list[AlignmentItem]:
        slot = self._pending[ticks]
        blocks = tuple(block for block in (slot.adc, slot.gpio) if block is not None)
        continuity = tuple(self._continuity_result(block) for block in blocks)
        gaps = tuple(result.gap for result in continuity if result.gap is not None)
        interval = AlignedInterval(slot.adc, slot.gpio, gaps)

        outputs: list[AlignmentItem] = []
        outputs.extend(
            result.gap
            for result in continuity
            if result.gap is not None and result.emit_gap
        )
        if loss_reason is not None:
            outputs.append(
                self._alignment_loss(
                    loss_reason,
                    ticks,
                    1,
                    slot.present_streams,
                )
            )
        outputs.append(interval)

        for result in continuity:
            kind = _block_kind(result.block)
            self._expected_sequence[kind] = (
                result.block.sequence + 1
            ) & constants.UINT32_MAX
            self._expected_ticks[kind] = result.block.end_tick_exclusive
            if result.announced_key is not None:
                del self._announced_gaps[result.announced_key]
        del self._pending[ticks]
        self._advance(1)
        return outputs

    def _continuity_result(
        self,
        block: ADCBlock | GPIOBlock,
    ) -> _ContinuityResult:
        kind = _block_kind(block)
        try:
            computed = StreamGap.from_expected(
                block,
                expected_sequence=self._expected_sequence[kind],
                expected_first_sample_ticks=self._expected_ticks[kind],
            )
        except ValueError as exc:
            raise TimestampAlignmentError(
                f"{kind.name} sequence/timestamp continuity is invalid: {exc}"
            ) from exc

        key = (kind, block.run_id, block.sequence, block.first_sample_ticks)
        announced = self._announced_gaps.get(key)
        embedded = block.gap if isinstance(block, ADCBlock) else None
        supplied = announced if announced is not None else embedded
        if (
            announced is not None
            and embedded is not None
            and _gap_signature(announced) != _gap_signature(embedded)
        ):
            raise TimestampAlignmentError(
                "announced and ADC-attached StreamGap evidence disagree"
            )
        selected: StreamGap | None
        if supplied is not None:
            if computed is None or _gap_signature(supplied) != _gap_signature(computed):
                raise TimestampAlignmentError(
                    f"{kind.name} StreamGap disagrees with aligned continuity"
                )
            selected = supplied
        else:
            selected = computed
        return _ContinuityResult(
            block=block,
            gap=selected,
            emit_gap=selected is not None and announced is None,
            announced_key=key if announced is not None else None,
        )

    def _alignment_loss(
        self,
        reason: AlignmentLossReason,
        first_sample_ticks: int,
        interval_count: int,
        present_streams: constants.StreamMask,
    ) -> AlignmentLoss:
        if self._active_run_id is None or self._active_source is None:
            raise AssertionError("alignment loss requires an active source epoch")
        missing = constants.StreamMask(int(_BOTH_STREAMS) ^ int(present_streams))
        return AlignmentLoss(
            reason=reason,
            run_id=self._active_run_id,
            source=self._active_source,
            first_sample_ticks=first_sample_ticks,
            interval_count=interval_count,
            present_streams=present_streams,
            missing_streams=missing,
            frame_coverage_ticks=self._required_frame_coverage_ticks(),
        )

    def _advance(self, interval_count: int) -> None:
        next_ticks = (
            self._next_output_ticks
            + interval_count * self._required_frame_coverage_ticks()
        )
        if next_ticks > constants.UINT64_MAX:
            raise TimestampAlignmentError(
                "timestamp wrap is outside the bounded alignment model"
            )
        self._next_output_ticks = next_ticks
        stale_announcements = tuple(
            key for key in self._announced_gaps if key[3] < self._next_output_ticks
        )
        for key in stale_announcements:
            del self._announced_gaps[key]

    def _required_frame_coverage_ticks(self) -> int:
        if self._frame_coverage_ticks is None:
            raise AssertionError("alignment epoch has no frame coverage")
        return self._frame_coverage_ticks


def align_by_timestamp(
    items: Iterable[AlignmentInput],
    *,
    max_pending_intervals: int = 8,
) -> Iterator[AlignmentItem]:
    """Align a finite input iterable and explicitly flush its final tail."""

    aligner = TimestampAligner(max_pending_intervals=max_pending_intervals)
    for item in items:
        yield from aligner.push(item)
    yield from aligner.finish()


__all__ = [
    "AlignedInterval",
    "AlignmentInput",
    "AlignmentItem",
    "AlignmentLoss",
    "AlignmentLossReason",
    "NominalEpoch",
    "TimestampAligner",
    "TimestampAlignmentError",
    "align_by_timestamp",
]
