"""Firmware counter conservation and typed fault snapshots."""

from __future__ import annotations

from dataclasses import dataclass
from enum import Enum

from ._generated import protocol_constants as constants
from .models import Status


class EquationState(Enum):
    """Whether one counter equation is exact, inconsistent, or saturated."""

    PASS = "pass"
    FAIL = "fail"
    SATURATED = "saturated"


@dataclass(frozen=True, slots=True)
class CounterEquation:
    """One ordered conservation check with explicit units and operands."""

    counter: str
    expression: str
    actual: int
    expected: int
    unit: str
    relation: str
    state: EquationState

    @property
    def exact(self) -> bool:
        return self.state is EquationState.PASS

    @property
    def inconsistent(self) -> bool:
        return self.state is EquationState.FAIL

    @property
    def difference(self) -> int:
        return self.actual - self.expected


@dataclass(frozen=True, slots=True)
class FirmwareFault:
    """One nonzero firmware loss or fault field from a STATUS snapshot."""

    counter: str
    value: int
    unit: str
    category: str


@dataclass(frozen=True, slots=True)
class FirmwareFaultSnapshot:
    """Typed nonzero diagnostic evidence retained for one statistics epoch."""

    run_id: int
    stats_generation: int
    faults: tuple[FirmwareFault, ...]

    @property
    def clear(self) -> bool:
        return not self.faults

    @property
    def first_fault(self) -> FirmwareFault | None:
        return self.faults[0] if self.faults else None


class CounterReconciliationError(ValueError):
    """A run counter report was inconsistent or lost precision to saturation."""

    def __init__(self, equation: CounterEquation) -> None:
        self.equation = equation
        super().__init__(
            f"{equation.counter}: {equation.expression} "
            f"({equation.actual} {equation.relation} {equation.expected} "
            f"{equation.unit}) is {equation.state.value}"
        )


@dataclass(frozen=True, slots=True)
class RunCounterReconciliation:
    """Ordered conservation equations and fault evidence for one run snapshot."""

    run_id: int
    stats_generation: int
    equations: tuple[CounterEquation, ...]
    fault_snapshot: FirmwareFaultSnapshot

    @property
    def exact(self) -> bool:
        return all(equation.exact for equation in self.equations)

    @property
    def first_inconsistent_counter(self) -> str | None:
        for equation in self.equations:
            if equation.inconsistent:
                return equation.counter
        return None

    @property
    def first_indeterminate_counter(self) -> str | None:
        for equation in self.equations:
            if equation.state is EquationState.SATURATED:
                return equation.counter
        return None

    @property
    def first_nonexact_equation(self) -> CounterEquation | None:
        for equation in self.equations:
            if not equation.exact:
                return equation
        return None

    def require_exact(self) -> None:
        """Raise at the first inconsistent or saturated counter in wire order."""

        first = self.first_nonexact_equation
        if first is not None:
            raise CounterReconciliationError(first)


_U64_FIELDS = frozenset(
    {
        "adc_frames_emitted",
        "gpio_frames_emitted",
        "adc_items_dropped",
        "gpio_items_dropped",
        "adc0_dma_major_loops",
        "adc1_dma_major_loops",
        "adc0_dma_results",
        "adc1_dma_results",
        "adc_paired_major_loops",
        "adc_buffers_completed",
        "adc_buffers_acquired",
        "adc_buffers_released",
        "adc_pairs_captured",
        "adc_pairs_delivered",
        "adc_pairs_framed",
        "adc_pairs_transmitted",
        "adc_raw_pairs_lost",
        "adc_stop_pairs_discarded",
        "adc_incomplete_conversions",
        "adc_overwritten_conversions",
        "adc_raw_ring_overruns",
        "adc_incomplete_buffers",
        "gpio_samples_captured",
        "gpio_samples_packed",
        "gpio_samples_framed",
        "gpio_samples_transmitted",
        "gpio_raw_samples_lost",
        "gpio_packer_samples_dropped",
        "gpio_raw_ring_overruns",
        "gpio_dma_major_loops",
        "packet_frames_promoted",
        "packet_fairness_deferrals",
        "packet_accounted_frame_skew",
        "data_payload_bytes_transmitted",
        "data_framed_bytes_transmitted",
        "packet_pressure_evictions",
        "packet_capacity_drops_without_evictable_frame",
        "adc_frames_evicted",
        "adc_frames_evicted_after_promotion",
        "gpio_frames_evicted",
        "gpio_frames_evicted_after_promotion",
        "adc_frames_dropped_after_framing",
        "adc_frames_dropped_after_promotion",
        "gpio_frames_dropped_after_framing",
        "gpio_frames_dropped_after_promotion",
        "gpio_buffers_completed",
        "gpio_buffers_acquired",
        "gpio_buffers_released",
        "gpio_samples_delivered",
        "gpio_stop_samples_discarded",
        "gpio_frames_produced",
        "gpio_samples_produced",
        "gpio_frames_packed",
        "gpio_duplicate_samples_ignored",
        "adc_frames_consumed",
        "adc_pairs_consumed",
        "adc_raw_gap_pairs",
        "adc_raw_drop_pairs_projected",
        "gpio_raw_drop_samples_projected",
        "gpio_packer_drop_samples_projected",
    }
    | {
        f"{source}_{suffix}"
        for source in ("adc", "gpio")
        for suffix in (
            "frames_generated",
            "items_generated",
            "frames_framed_pipeline",
            "items_framed_pipeline",
            "items_emitted",
            "frames_transmitted",
            "items_transmitted_pipeline",
            "frames_dropped",
            "payload_bytes_produced",
            "payload_bytes_framed",
            "payload_bytes_emitted",
            "payload_bytes_transmitted",
            "payload_bytes_dropped",
            "framed_bytes_framed",
            "framed_bytes_emitted",
            "framed_bytes_transmitted",
        )
    }
)

_U32_FIELDS = frozenset(
    {
        "packet_pool_exhaustions",
        "adc_cache_dma_discards",
        "adc_cache_cpu_invalidations",
        "gpio_cache_dma_discards",
        "gpio_cache_cpu_invalidations",
    }
)


def _saturated(status: Status, fields: tuple[str, ...]) -> bool:
    for name in fields:
        value = int(getattr(status, name))
        if name in _U64_FIELDS and value == constants.UINT64_MAX:
            return True
        if name in _U32_FIELDS and value == constants.UINT32_MAX:
            return True
    return False


def _equation(
    status: Status,
    *,
    counter: str,
    expression: str,
    actual: int,
    expected: int,
    unit: str,
    relation: str = "==",
    fields: tuple[str, ...] = (),
) -> CounterEquation:
    if relation == "==":
        consistent = actual == expected
    elif relation == "<=":
        consistent = actual <= expected
    elif relation == ">=":
        consistent = actual >= expected
    else:  # pragma: no cover - private callers are static
        raise ValueError(f"unsupported counter relation {relation!r}")
    state = (
        EquationState.SATURATED
        if _saturated(status, fields)
        else EquationState.PASS
        if consistent
        else EquationState.FAIL
    )
    return CounterEquation(
        counter=counter,
        expression=expression,
        actual=actual,
        expected=expected,
        unit=unit,
        relation=relation,
        state=state,
    )


def _stream_equations(status: Status, source: str) -> list[CounterEquation]:
    is_adc = source == "adc"
    layout = status.configuration.gpio_layout if status.configuration else None
    items_per_frame = (
        layout.adc_items_per_frame
        if is_adc and layout
        else layout.items_per_frame
        if layout
        else constants.ADC_PAIRS_PER_FRAME
        if is_adc
        else constants.GPIO_SAMPLES_PER_FRAME
    )
    bytes_per_item = (
        constants.ADC_BYTES_PER_PAIR if is_adc else layout.item_bytes if layout else 1
    )
    payload_bytes_per_frame = items_per_frame * bytes_per_item
    frame_bytes = (
        payload_bytes_per_frame + constants.HEADER_SIZE + constants.TRAILER_SIZE
    )
    frame_unit = f"{source.upper()} frames"
    item_unit = "ADC pairs" if is_adc else "GPIO sample instants"

    def value(suffix: str) -> int:
        return int(getattr(status, f"{source}_{suffix}"))

    generated_frames = value("frames_generated")
    generated_items = value("items_generated")
    framed_frames = value("frames_framed_pipeline")
    framed_items = value("items_framed_pipeline")
    emitted_frames = int(getattr(status, f"{source}_frames_emitted"))
    emitted_items = value("items_emitted")
    transmitted_frames = value("frames_transmitted")
    transmitted_items = value("items_transmitted_pipeline")
    dropped_frames = value("frames_dropped")
    evicted_frames = value("frames_evicted")
    evicted_after_promotion = value("frames_evicted_after_promotion")
    dropped_after_framing = value("frames_dropped_after_framing")
    dropped_after_promotion = value("frames_dropped_after_promotion")
    filling_depth = value("packet_filling_depth")
    ready_depth = value("packet_ready_depth")
    transmit_depth = value("packet_transmit_depth")

    equations: list[CounterEquation] = []

    def add(
        suffix: str,
        expression: str,
        actual: int,
        expected: int,
        unit: str,
        *,
        relation: str = "==",
        dependencies: tuple[str, ...] = (),
    ) -> None:
        counter = f"{source}_{suffix}"
        equations.append(
            _equation(
                status,
                counter=counter,
                expression=expression,
                actual=actual,
                expected=expected,
                unit=unit,
                relation=relation,
                fields=(counter, *dependencies),
            )
        )

    add(
        "items_generated",
        f"{source}_items_generated == {source}_frames_generated * {items_per_frame}",
        generated_items,
        generated_frames * items_per_frame,
        item_unit,
        dependencies=(f"{source}_frames_generated",),
    )
    add(
        "items_framed_pipeline",
        f"{source}_items_framed_pipeline == {source}_frames_framed_pipeline * {items_per_frame}",
        framed_items,
        framed_frames * items_per_frame,
        item_unit,
        dependencies=(f"{source}_frames_framed_pipeline",),
    )
    add(
        "items_emitted",
        f"{source}_items_emitted == {source}_frames_emitted * {items_per_frame}",
        emitted_items,
        emitted_frames * items_per_frame,
        item_unit,
        dependencies=(f"{source}_frames_emitted",),
    )
    add(
        "items_transmitted_pipeline",
        f"{source}_items_transmitted_pipeline == {source}_frames_transmitted * {items_per_frame}",
        transmitted_items,
        transmitted_frames * items_per_frame,
        item_unit,
        dependencies=(f"{source}_frames_transmitted",),
    )

    byte_stages = (
        ("payload_bytes_produced", generated_items),
        ("payload_bytes_framed", framed_items),
        ("payload_bytes_emitted", emitted_items),
        ("payload_bytes_transmitted", transmitted_items),
    )
    for suffix, items in byte_stages:
        item_suffix = {
            "payload_bytes_produced": "items_generated",
            "payload_bytes_framed": "items_framed_pipeline",
            "payload_bytes_emitted": "items_emitted",
            "payload_bytes_transmitted": "items_transmitted_pipeline",
        }[suffix]
        add(
            suffix,
            f"{source}_{suffix} == {source}_{item_suffix} * {bytes_per_item}",
            value(suffix),
            items * bytes_per_item,
            "payload bytes",
            dependencies=(f"{source}_{item_suffix}",),
        )
    add(
        "payload_bytes_dropped",
        f"{source}_payload_bytes_dropped == {source}_frames_dropped * {payload_bytes_per_frame}",
        value("payload_bytes_dropped"),
        dropped_frames * payload_bytes_per_frame,
        "payload bytes",
        dependencies=(f"{source}_frames_dropped",),
    )
    for suffix, frames in (
        ("framed_bytes_framed", framed_frames),
        ("framed_bytes_emitted", emitted_frames),
        ("framed_bytes_transmitted", transmitted_frames),
    ):
        frame_suffix = {
            "framed_bytes_framed": "frames_framed_pipeline",
            "framed_bytes_emitted": "frames_emitted",
            "framed_bytes_transmitted": "frames_transmitted",
        }[suffix]
        add(
            suffix,
            f"{source}_{suffix} == {source}_{frame_suffix} * {frame_bytes}",
            value(suffix),
            frames * frame_bytes,
            "wire bytes",
            dependencies=(f"{source}_{frame_suffix}",),
        )

    add(
        "frames_generated",
        f"{source}_frames_generated == transmitted + dropped + filling + ready + transmit",
        generated_frames,
        (
            transmitted_frames
            + dropped_frames
            + filling_depth
            + ready_depth
            + transmit_depth
        ),
        frame_unit,
        dependencies=(
            f"{source}_frames_transmitted",
            f"{source}_frames_dropped",
        ),
    )
    add(
        "frames_framed_pipeline",
        f"{source}_frames_framed_pipeline == transmitted + ready + transmit + dropped-after-framing",
        framed_frames,
        transmitted_frames + ready_depth + transmit_depth + dropped_after_framing,
        frame_unit,
        dependencies=(
            f"{source}_frames_transmitted",
            f"{source}_frames_dropped_after_framing",
        ),
    )
    add(
        "frames_emitted",
        f"{source}_frames_emitted == transmitted + transmit + dropped-after-promotion",
        emitted_frames,
        transmitted_frames + transmit_depth + dropped_after_promotion,
        frame_unit,
        dependencies=(
            f"{source}_frames_transmitted",
            f"{source}_frames_dropped_after_promotion",
        ),
    )
    add(
        "frames_dropped_after_promotion",
        f"{source}_frames_dropped_after_promotion <= {source}_frames_dropped_after_framing",
        dropped_after_promotion,
        dropped_after_framing,
        frame_unit,
        relation="<=",
        dependencies=(f"{source}_frames_dropped_after_framing",),
    )
    add(
        "frames_dropped_after_framing",
        f"{source}_frames_dropped_after_framing <= {source}_frames_dropped",
        dropped_after_framing,
        dropped_frames,
        frame_unit,
        relation="<=",
        dependencies=(f"{source}_frames_dropped",),
    )
    add(
        "frames_evicted_after_promotion",
        f"{source}_frames_evicted_after_promotion <= {source}_frames_evicted",
        evicted_after_promotion,
        evicted_frames,
        frame_unit,
        relation="<=",
        dependencies=(f"{source}_frames_evicted",),
    )
    add(
        "frames_evicted",
        f"{source}_frames_evicted <= {source}_frames_dropped_after_framing",
        evicted_frames,
        dropped_after_framing,
        frame_unit,
        relation="<=",
        dependencies=(f"{source}_frames_dropped_after_framing",),
    )
    aggregate_dropped_items = int(getattr(status, f"{source}_items_dropped"))
    add(
        "items_dropped",
        f"{source}_items_dropped >= {source}_frames_dropped * {items_per_frame}",
        aggregate_dropped_items,
        dropped_frames * items_per_frame,
        item_unit,
        relation=">=",
        dependencies=(f"{source}_frames_dropped",),
    )
    return equations


_FAULT_FIELDS: tuple[tuple[str, str, str], ...] = (
    ("adc_items_dropped", "ADC pairs", "loss"),
    ("gpio_items_dropped", "GPIO sample instants", "loss"),
    ("adc_frames_dropped", "ADC frames", "loss"),
    ("gpio_frames_dropped", "GPIO frames", "loss"),
    ("adc_raw_pairs_lost", "ADC pairs", "dma"),
    ("adc_stop_pairs_discarded", "ADC pairs", "stop"),
    ("adc_incomplete_conversions", "conversion results", "adc"),
    ("adc_overwritten_conversions", "conversion results", "adc"),
    ("adc_raw_ring_overruns", "DMA major loops", "dma"),
    ("adc_incomplete_buffers", "DMA buffers", "dma"),
    ("gpio_raw_samples_lost", "GPIO sample instants", "dma"),
    ("gpio_packer_samples_dropped", "GPIO sample instants", "packer"),
    ("gpio_raw_ring_overruns", "DMA major loops", "dma"),
    ("gpio_stop_samples_discarded", "GPIO sample instants", "stop"),
    ("gpio_duplicate_samples_ignored", "GPIO sample instants", "timing"),
    ("packet_pool_exhaustions", "events", "packet"),
    ("packet_pressure_evictions", "frames", "packet"),
    (
        "packet_capacity_drops_without_evictable_frame",
        "frames",
        "packet",
    ),
    ("adc_frames_dropped_after_framing", "ADC frames", "packet"),
    ("adc_frames_dropped_after_promotion", "ADC frames", "packet"),
    ("gpio_frames_dropped_after_framing", "GPIO frames", "packet"),
    ("gpio_frames_dropped_after_promotion", "GPIO frames", "packet"),
    ("adc_initialization_error_flags", "bit flags", "adc"),
    ("adc_etc_error_events", "events", "adc"),
    ("adc_etc_error_flags", "bit flags", "adc"),
    ("adc_dma_error_events", "events", "dma"),
    ("adc_completion_mismatches", "events", "adc"),
    ("adc_destination_mismatches", "events", "dma"),
    ("adc_raw_invariant_errors", "events", "ownership"),
    ("adc_packer_source_errors", "events", "ownership"),
    ("adc_packer_pipeline_errors", "events", "packet"),
    ("adc_packer_chronology_errors", "events", "timing"),
    ("adc_schedule_exhaustions", "events", "dma"),
    ("adc_stale_completions", "events", "dma"),
    ("adc_stale_interrupts", "interrupts", "dma"),
    ("adc_resource_conflicts", "events", "resource"),
    ("adc_start_errors", "events", "lifecycle"),
    ("adc_stop_errors", "events", "lifecycle"),
    ("gpio_hardware_errors", "events", "dma"),
    ("gpio_raw_invariant_errors", "events", "ownership"),
    ("gpio_packer_source_errors", "events", "ownership"),
    ("gpio_packer_pipeline_errors", "events", "packet"),
    ("gpio_packer_chronology_errors", "events", "timing"),
    ("gpio_resource_conflicts", "events", "resource"),
    ("gpio_start_errors", "events", "lifecycle"),
    ("gpio_stop_errors", "events", "lifecycle"),
    ("gpio_stale_dma_completions", "events", "dma"),
    ("packet_invalid_operations", "events", "packet"),
    ("packet_encoding_rejections", "frames", "packet"),
    ("packet_ready_queue_rejections", "frames", "queue"),
    ("packet_transmit_queue_rejections", "frames", "queue"),
    ("parser_errors", "candidates", "parser"),
    ("bad_checksums", "candidates", "parser"),
    ("bad_lengths", "candidates", "parser"),
    ("bad_types", "candidates", "parser"),
    ("bad_versions", "candidates", "parser"),
    ("bad_flags", "candidates", "parser"),
    ("bad_payloads", "candidates", "parser"),
    ("bad_request_ids", "requests", "parser"),
    ("state_errors", "commands", "command"),
    ("response_queue_rejections", "responses", "response"),
    ("response_reservations_abandoned", "responses", "response"),
    ("timeouts", "events", "usb"),
    ("partial_usb_writes", "writes", "usb"),
    ("usb_rx_stall_events", "events", "usb"),
    ("usb_tx_stall_events", "events", "usb"),
    ("usb_io_errors", "events", "usb"),
    ("transport_errors", "events", "usb"),
)


def snapshot_firmware_faults(
    status: Status,
    *,
    run_id: int = 0,
) -> FirmwareFaultSnapshot:
    """Return every nonzero loss/fault field without collapsing its unit."""

    if not isinstance(status, Status):
        raise TypeError("status must be a Status snapshot")
    if not isinstance(run_id, int) or isinstance(run_id, bool):
        raise TypeError("run_id must be a uint32 integer")
    if not 0 <= run_id <= constants.UINT32_MAX:
        raise ValueError("run_id must fit uint32")
    faults: list[FirmwareFault] = []
    for counter, unit, category in _FAULT_FIELDS:
        value = int(getattr(status, counter))
        if value:
            faults.append(FirmwareFault(counter, value, unit, category))
    trigger_flags = int(status.adc_trigger.error_flags)
    if trigger_flags:
        faults.insert(
            3,
            FirmwareFault("adc_trigger_error_flags", trigger_flags, "bit flags", "adc"),
        )
    trigger_events = status.adc_trigger.trigger_error_count
    if trigger_events:
        faults.insert(
            4,
            FirmwareFault("adc_trigger_error_count", trigger_events, "events", "adc"),
        )
    return FirmwareFaultSnapshot(run_id, status.stats_generation, tuple(faults))


def reconcile_run_counters(
    status: Status,
    *,
    run_id: int = 0,
) -> RunCounterReconciliation:
    """Prove ordered packet/raw conservation equations for one STATUS snapshot.

    The first failed equation is stable and names the earliest inconsistent
    counter. Saturated operands are reported as indeterminate rather than
    being mistaken for a mismatch. Live snapshots include current queue depth;
    stopped snapshots reduce naturally to produced = transmitted + dropped.
    """

    if not isinstance(status, Status):
        raise TypeError("status must be a Status snapshot")
    if not isinstance(run_id, int) or isinstance(run_id, bool):
        raise TypeError("run_id must be a uint32 integer")
    if not 0 <= run_id <= constants.UINT32_MAX:
        raise ValueError("run_id must fit uint32")

    inferred_streams = status.stream_mask
    layout = status.configuration.gpio_layout if status.configuration else None
    adc_items_per_frame = (
        layout.adc_items_per_frame if layout else constants.ADC_PAIRS_PER_FRAME
    )
    gpio_items_per_frame = (
        layout.items_per_frame if layout else constants.GPIO_SAMPLES_PER_FRAME
    )
    if inferred_streams == constants.StreamMask.NONE:
        if (
            status.adc_frames_generated
            or status.adc_items_dropped
            or status.adc_pairs_captured
            or status.adc_cache_dma_discards
        ):
            inferred_streams |= constants.StreamMask.ADC
        if (
            status.gpio_frames_generated
            or status.gpio_items_dropped
            or status.gpio_samples_captured
            or status.gpio_cache_dma_discards
        ):
            inferred_streams |= constants.StreamMask.GPIO

    equations: list[CounterEquation] = []
    if inferred_streams & constants.StreamMask.ADC:
        equations.extend(_stream_equations(status, "adc"))
    if inferred_streams & constants.StreamMask.GPIO:
        equations.extend(_stream_equations(status, "gpio"))

    equations.extend(
        (
            _equation(
                status,
                counter="packet_ready_depth",
                expression="packet_ready_depth == adc_ready + gpio_ready",
                actual=status.packet_ready_depth,
                expected=(
                    status.adc_packet_ready_depth + status.gpio_packet_ready_depth
                ),
                unit="frames",
            ),
            _equation(
                status,
                counter="packet_transmit_depth",
                expression="packet_transmit_depth == adc_transmit + gpio_transmit",
                actual=status.packet_transmit_depth,
                expected=(
                    status.adc_packet_transmit_depth + status.gpio_packet_transmit_depth
                ),
                unit="frames",
            ),
            _equation(
                status,
                counter="packet_owned_depth",
                expression="packet_owned_depth == filling + ready + transmit",
                actual=status.packet_owned_depth,
                expected=(
                    status.adc_packet_filling_depth
                    + status.gpio_packet_filling_depth
                    + status.packet_ready_depth
                    + status.packet_transmit_depth
                ),
                unit="frames",
            ),
            _equation(
                status,
                counter="packet_pressure_evictions",
                expression="packet_pressure_evictions == adc_evicted + gpio_evicted",
                actual=status.packet_pressure_evictions,
                expected=status.adc_frames_evicted + status.gpio_frames_evicted,
                unit="frames",
                fields=(
                    "packet_pressure_evictions",
                    "adc_frames_evicted",
                    "gpio_frames_evicted",
                ),
            ),
            _equation(
                status,
                counter="packet_pool_exhaustions",
                expression="packet_pool_exhaustions == evictions + no-evictable drops",
                actual=status.packet_pool_exhaustions,
                expected=(
                    status.packet_pressure_evictions
                    + status.packet_capacity_drops_without_evictable_frame
                ),
                unit="events",
                fields=(
                    "packet_pool_exhaustions",
                    "packet_pressure_evictions",
                    "packet_capacity_drops_without_evictable_frame",
                ),
            ),
            _equation(
                status,
                counter="packet_frames_promoted",
                expression="packet_frames_promoted == adc_emitted + gpio_emitted",
                actual=status.packet_frames_promoted,
                expected=status.adc_frames_emitted + status.gpio_frames_emitted,
                unit="frames",
                fields=(
                    "packet_frames_promoted",
                    "adc_frames_emitted",
                    "gpio_frames_emitted",
                ),
            ),
            _equation(
                status,
                counter="data_payload_bytes_transmitted",
                expression="data_payload_bytes_transmitted == adc + gpio payload bytes",
                actual=status.data_payload_bytes_transmitted,
                expected=(
                    status.adc_payload_bytes_transmitted
                    + status.gpio_payload_bytes_transmitted
                ),
                unit="payload bytes",
                fields=(
                    "data_payload_bytes_transmitted",
                    "adc_payload_bytes_transmitted",
                    "gpio_payload_bytes_transmitted",
                ),
            ),
            _equation(
                status,
                counter="data_framed_bytes_transmitted",
                expression="data_framed_bytes_transmitted == adc + gpio wire bytes",
                actual=status.data_framed_bytes_transmitted,
                expected=(
                    status.adc_framed_bytes_transmitted
                    + status.gpio_framed_bytes_transmitted
                ),
                unit="wire bytes",
                fields=(
                    "data_framed_bytes_transmitted",
                    "adc_framed_bytes_transmitted",
                    "gpio_framed_bytes_transmitted",
                ),
            ),
            _equation(
                status,
                counter="usb_lower_priority_queue_depth",
                expression="usb_lower_priority_queue_depth == packet_transmit_depth",
                actual=status.usb_lower_priority_queue_depth,
                expected=status.packet_transmit_depth,
                unit="frames",
            ),
            _equation(
                status,
                counter="usb_active_frame_bytes_sent",
                expression="usb_active_frame_bytes_sent <= usb_active_frame_size",
                actual=status.usb_active_frame_bytes_sent,
                expected=status.usb_active_frame_size,
                unit="wire bytes",
                relation="<=",
            ),
        )
    )

    physical_evidence = bool(
        status.adc_pairs_captured
        or status.gpio_samples_captured
        or status.adc_cache_dma_discards
        or status.gpio_cache_dma_discards
    )
    source_is_hardware = (
        status.source is constants.Source.HARDWARE
        and status.device_state is not constants.DeviceState.IDLE
    ) or physical_evidence
    if source_is_hardware and inferred_streams & constants.StreamMask.ADC:
        equations.extend(
            (
                _equation(
                    status,
                    counter="adc0_dma_results",
                    expression="adc0_dma_results == adc0_major_loops * pairs_per_frame",
                    actual=status.adc0_dma_results,
                    expected=(status.adc0_dma_major_loops * adc_items_per_frame),
                    unit="conversion results",
                    fields=("adc0_dma_results", "adc0_dma_major_loops"),
                ),
                _equation(
                    status,
                    counter="adc1_dma_results",
                    expression="adc1_dma_results == adc1_major_loops * pairs_per_frame",
                    actual=status.adc1_dma_results,
                    expected=(status.adc1_dma_major_loops * adc_items_per_frame),
                    unit="conversion results",
                    fields=("adc1_dma_results", "adc1_dma_major_loops"),
                ),
                _equation(
                    status,
                    counter="adc_paired_major_loops",
                    expression="adc_paired_major_loops == completed + overrun + incomplete buffers",
                    actual=status.adc_paired_major_loops,
                    expected=(
                        status.adc_buffers_completed
                        + status.adc_raw_ring_overruns
                        + status.adc_incomplete_buffers
                    ),
                    unit="paired DMA major loops",
                    fields=(
                        "adc_paired_major_loops",
                        "adc_buffers_completed",
                        "adc_raw_ring_overruns",
                        "adc_incomplete_buffers",
                    ),
                ),
                _equation(
                    status,
                    counter="adc_buffers_completed",
                    expression="adc_buffers_completed == acquired + raw-ready",
                    actual=status.adc_buffers_completed,
                    expected=(status.adc_buffers_acquired + status.adc_raw_ready_depth),
                    unit="paired DMA buffers",
                    fields=("adc_buffers_completed", "adc_buffers_acquired"),
                ),
                _equation(
                    status,
                    counter="adc_buffers_acquired",
                    expression="adc_buffers_acquired == adc_buffers_released",
                    actual=status.adc_buffers_acquired,
                    expected=status.adc_buffers_released,
                    unit="paired DMA buffers",
                    fields=("adc_buffers_acquired", "adc_buffers_released"),
                ),
                _equation(
                    status,
                    counter="adc_pairs_captured",
                    expression="adc_pairs_captured == paired loops * pairs-per-frame + stopped partial",
                    actual=status.adc_pairs_captured,
                    expected=(
                        status.adc_paired_major_loops * adc_items_per_frame
                        + status.adc_stop_pairs_discarded
                    ),
                    unit="ADC pairs",
                    fields=(
                        "adc_pairs_captured",
                        "adc_paired_major_loops",
                        "adc_stop_pairs_discarded",
                    ),
                ),
                _equation(
                    status,
                    counter="adc_pairs_captured",
                    expression="adc_pairs_captured == delivered + lost + raw-ready",
                    actual=status.adc_pairs_captured,
                    expected=(
                        status.adc_pairs_delivered
                        + status.adc_raw_pairs_lost
                        + status.adc_raw_ready_depth * adc_items_per_frame
                    ),
                    unit="ADC pairs",
                    fields=(
                        "adc_pairs_captured",
                        "adc_pairs_delivered",
                        "adc_raw_pairs_lost",
                    ),
                ),
                _equation(
                    status,
                    counter="adc_pairs_delivered",
                    expression="adc_pairs_delivered == buffers_acquired * pairs-per-frame",
                    actual=status.adc_pairs_delivered,
                    expected=(status.adc_buffers_acquired * adc_items_per_frame),
                    unit="ADC pairs",
                    fields=("adc_pairs_delivered", "adc_buffers_acquired"),
                ),
                _equation(
                    status,
                    counter="adc_pairs_consumed",
                    expression="adc_pairs_consumed == frames_consumed * pairs-per-frame",
                    actual=status.adc_pairs_consumed,
                    expected=(status.adc_frames_consumed * adc_items_per_frame),
                    unit="ADC pairs",
                    fields=("adc_pairs_consumed", "adc_frames_consumed"),
                ),
                _equation(
                    status,
                    counter="adc_pairs_delivered",
                    expression="adc_pairs_delivered == adc_pairs_consumed",
                    actual=status.adc_pairs_delivered,
                    expected=status.adc_pairs_consumed,
                    unit="ADC pairs",
                    fields=("adc_pairs_delivered", "adc_pairs_consumed"),
                ),
                _equation(
                    status,
                    counter="adc_pairs_framed",
                    expression="adc_pairs_framed == adc_items_framed_pipeline",
                    actual=status.adc_pairs_framed,
                    expected=status.adc_items_framed_pipeline,
                    unit="ADC pairs",
                    fields=(
                        "adc_pairs_framed",
                        "adc_items_framed_pipeline",
                    ),
                ),
                _equation(
                    status,
                    counter="adc_pairs_transmitted",
                    expression="adc_pairs_transmitted == pipeline transmitted items",
                    actual=status.adc_pairs_transmitted,
                    expected=status.adc_items_transmitted_pipeline,
                    unit="ADC pairs",
                    fields=(
                        "adc_pairs_transmitted",
                        "adc_items_transmitted_pipeline",
                    ),
                ),
                _equation(
                    status,
                    counter="adc_raw_drop_pairs_projected",
                    expression="adc_raw_drop_pairs_projected <= adc_raw_gap_pairs",
                    actual=status.adc_raw_drop_pairs_projected,
                    expected=status.adc_raw_gap_pairs,
                    unit="ADC pairs",
                    relation="<=",
                    fields=(
                        "adc_raw_drop_pairs_projected",
                        "adc_raw_gap_pairs",
                    ),
                ),
                _equation(
                    status,
                    counter="adc_items_dropped",
                    expression="adc_items_dropped == packet drops + unprojected raw loss",
                    actual=status.adc_items_dropped,
                    expected=(
                        status.adc_frames_dropped * adc_items_per_frame
                        + max(
                            0,
                            status.adc_raw_pairs_lost
                            - status.adc_raw_drop_pairs_projected,
                        )
                    ),
                    unit="ADC pairs",
                    fields=(
                        "adc_items_dropped",
                        "adc_frames_dropped",
                        "adc_raw_pairs_lost",
                        "adc_raw_drop_pairs_projected",
                    ),
                ),
                _equation(
                    status,
                    counter="adc_cache_cpu_invalidations",
                    expression="adc_cache_cpu_invalidations == adc_buffers_acquired",
                    actual=status.adc_cache_cpu_invalidations,
                    expected=status.adc_buffers_acquired,
                    unit="cache operations",
                    fields=(
                        "adc_cache_cpu_invalidations",
                        "adc_buffers_acquired",
                    ),
                ),
                _equation(
                    status,
                    counter="adc_raw_pairs_lost",
                    expression="adc_raw_pairs_lost >= raw_ring_overruns * pairs_per_frame",
                    actual=status.adc_raw_pairs_lost,
                    expected=(status.adc_raw_ring_overruns * adc_items_per_frame),
                    unit="ADC pairs",
                    relation=">=",
                    fields=("adc_raw_pairs_lost", "adc_raw_ring_overruns"),
                ),
            )
        )
    if source_is_hardware and inferred_streams & constants.StreamMask.GPIO:
        equations.extend(
            (
                _equation(
                    status,
                    counter="gpio_samples_captured",
                    expression="gpio_samples_captured == delivered + lost + raw-ready",
                    actual=status.gpio_samples_captured,
                    expected=(
                        status.gpio_samples_delivered
                        + status.gpio_raw_samples_lost
                        + status.gpio_raw_ready_depth * gpio_items_per_frame
                    ),
                    unit="GPIO sample instants",
                    fields=(
                        "gpio_samples_captured",
                        "gpio_samples_delivered",
                        "gpio_raw_samples_lost",
                    ),
                ),
                _equation(
                    status,
                    counter="gpio_buffers_completed",
                    expression="gpio_buffers_completed == acquired + raw-ready",
                    actual=status.gpio_buffers_completed,
                    expected=(
                        status.gpio_buffers_acquired + status.gpio_raw_ready_depth
                    ),
                    unit="raw DMA buffers",
                    fields=("gpio_buffers_completed", "gpio_buffers_acquired"),
                ),
                _equation(
                    status,
                    counter="gpio_buffers_acquired",
                    expression="gpio_buffers_acquired == gpio_buffers_released",
                    actual=status.gpio_buffers_acquired,
                    expected=status.gpio_buffers_released,
                    unit="raw DMA buffers",
                    fields=("gpio_buffers_acquired", "gpio_buffers_released"),
                ),
                _equation(
                    status,
                    counter="gpio_samples_delivered",
                    expression="gpio_samples_delivered == acquired * samples-per-frame",
                    actual=status.gpio_samples_delivered,
                    expected=(status.gpio_buffers_acquired * gpio_items_per_frame),
                    unit="GPIO sample instants",
                    fields=("gpio_samples_delivered", "gpio_buffers_acquired"),
                ),
                _equation(
                    status,
                    counter="gpio_samples_framed",
                    expression="gpio_samples_framed == gpio_items_framed_pipeline",
                    actual=status.gpio_samples_framed,
                    expected=status.gpio_items_framed_pipeline,
                    unit="GPIO sample instants",
                    fields=(
                        "gpio_samples_framed",
                        "gpio_items_framed_pipeline",
                    ),
                ),
                _equation(
                    status,
                    counter="gpio_samples_transmitted",
                    expression="gpio_samples_transmitted == pipeline transmitted items",
                    actual=status.gpio_samples_transmitted,
                    expected=status.gpio_items_transmitted_pipeline,
                    unit="GPIO sample instants",
                    fields=(
                        "gpio_samples_transmitted",
                        "gpio_items_transmitted_pipeline",
                    ),
                ),
                _equation(
                    status,
                    counter="gpio_cache_cpu_invalidations",
                    expression="gpio_cache_cpu_invalidations == gpio_buffers_acquired",
                    actual=status.gpio_cache_cpu_invalidations,
                    expected=status.gpio_buffers_acquired,
                    unit="cache operations",
                    fields=(
                        "gpio_cache_cpu_invalidations",
                        "gpio_buffers_acquired",
                    ),
                ),
                _equation(
                    status,
                    counter="gpio_raw_drop_samples_projected",
                    expression="gpio_raw_drop_samples_projected <= gpio_raw_samples_lost",
                    actual=status.gpio_raw_drop_samples_projected,
                    expected=status.gpio_raw_samples_lost,
                    unit="GPIO sample instants",
                    relation="<=",
                    fields=(
                        "gpio_raw_drop_samples_projected",
                        "gpio_raw_samples_lost",
                    ),
                ),
                _equation(
                    status,
                    counter="gpio_packer_drop_samples_projected",
                    expression="gpio_packer_drop_samples_projected <= gpio_packer_samples_dropped",
                    actual=status.gpio_packer_drop_samples_projected,
                    expected=status.gpio_packer_samples_dropped,
                    unit="GPIO sample instants",
                    relation="<=",
                    fields=(
                        "gpio_packer_drop_samples_projected",
                        "gpio_packer_samples_dropped",
                    ),
                ),
                _equation(
                    status,
                    counter="gpio_items_dropped",
                    expression="gpio_items_dropped == packet + unprojected raw + packer loss",
                    actual=status.gpio_items_dropped,
                    expected=(
                        status.gpio_frames_dropped * gpio_items_per_frame
                        + max(
                            0,
                            status.gpio_raw_samples_lost
                            - status.gpio_raw_drop_samples_projected,
                        )
                        + max(
                            0,
                            status.gpio_packer_samples_dropped
                            - status.gpio_packer_drop_samples_projected,
                        )
                    ),
                    unit="GPIO sample instants",
                    fields=(
                        "gpio_items_dropped",
                        "gpio_frames_dropped",
                        "gpio_raw_samples_lost",
                        "gpio_raw_drop_samples_projected",
                        "gpio_packer_samples_dropped",
                        "gpio_packer_drop_samples_projected",
                    ),
                ),
                _equation(
                    status,
                    counter="gpio_raw_samples_lost",
                    expression="gpio_raw_samples_lost >= raw_ring_overruns * samples_per_frame",
                    actual=status.gpio_raw_samples_lost,
                    expected=(status.gpio_raw_ring_overruns * gpio_items_per_frame),
                    unit="GPIO sample instants",
                    relation=">=",
                    fields=(
                        "gpio_raw_samples_lost",
                        "gpio_raw_ring_overruns",
                    ),
                ),
            )
        )

    auxiliary = status.auxiliary_gpio
    if auxiliary is not None:
        for bank_index, bank_name in enumerate(("primary", "auxiliary")):
            equations.extend(
                (
                    _equation(
                        status,
                        counter=f"{bank_name}_gpio_samples_captured",
                        expression=(
                            f"{bank_name}_samples == major_loops * samples_per_frame"
                        ),
                        actual=auxiliary.bank_samples_captured[bank_index],
                        expected=(
                            auxiliary.bank_major_loops[bank_index]
                            * gpio_items_per_frame
                        ),
                        unit="GPIO sample instants",
                    ),
                    _equation(
                        status,
                        counter=f"{bank_name}_gpio_raw_ring_overruns",
                        expression=f"{bank_name}_overruns <= paired_overruns",
                        actual=auxiliary.bank_ring_overruns[bank_index],
                        expected=auxiliary.raw_ring_overruns,
                        unit="DMA major loops",
                        relation="<=",
                    ),
                )
            )
        equations.extend(
            (
                _equation(
                    status,
                    counter="paired_gpio_samples_captured",
                    expression="paired captured == joined + paired loss",
                    actual=auxiliary.samples_captured,
                    expected=auxiliary.samples_joined + auxiliary.samples_lost,
                    unit="GPIO sample instants",
                ),
                _equation(
                    status,
                    counter="paired_gpio_buffers_completed",
                    expression="paired completed == acquired + ready",
                    actual=auxiliary.buffers_completed,
                    expected=(auxiliary.buffers_acquired + auxiliary.ready_depth[0]),
                    unit="paired DMA buffers",
                ),
                _equation(
                    status,
                    counter="paired_gpio_buffers_acquired",
                    expression="paired acquired == released",
                    actual=auxiliary.buffers_acquired,
                    expected=auxiliary.buffers_released,
                    unit="paired DMA buffers",
                ),
                _equation(
                    status,
                    counter="paired_gpio_samples_delivered",
                    expression="paired delivered == acquired * samples_per_frame",
                    actual=auxiliary.samples_delivered,
                    expected=auxiliary.buffers_acquired * gpio_items_per_frame,
                    unit="GPIO sample instants",
                ),
            )
        )

    faults = snapshot_firmware_faults(status, run_id=run_id)
    return RunCounterReconciliation(
        run_id=run_id,
        stats_generation=status.stats_generation,
        equations=tuple(equations),
        fault_snapshot=faults,
    )


__all__ = [
    "CounterEquation",
    "CounterReconciliationError",
    "EquationState",
    "FirmwareFault",
    "FirmwareFaultSnapshot",
    "RunCounterReconciliation",
    "reconcile_run_counters",
    "snapshot_firmware_faults",
]
