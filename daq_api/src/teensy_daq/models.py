"""Typed protocol models and lazy views over ADC and GPIO payloads."""

from __future__ import annotations

import struct
from collections.abc import Iterator, Sequence
from dataclasses import dataclass
from dataclasses import field as dataclass_field
from dataclasses import replace as dataclass_replace
from enum import Enum, IntEnum
from typing import Any, Generic, TypeVar, overload

from ._generated import protocol_constants as constants
from .checksum import HOST_SUPPORTED_CHECKSUM_ALGORITHMS
from .protocol import Frame, FrameValidationError

_CONFIGURATION = struct.Struct("<BBBBI")
_CHECKSUM_BENCHMARK_REQUEST = struct.Struct("<BBBBHH")
_GPIO_CLOCK_DIAGNOSTIC_REQUEST = struct.Struct("<IHH")
_RESPONSE_PREFIX = struct.Struct("<BBH")
_STATUS_COUNTERS = struct.Struct("<QQQQII")
_STATUS_PIPELINE_U64_FIELDS = (
    "adc_frames_generated",
    "adc_items_generated",
    "adc_frames_framed_pipeline",
    "adc_items_framed_pipeline",
    "adc_items_emitted",
    "adc_frames_transmitted",
    "adc_items_transmitted_pipeline",
    "adc_frames_dropped",
    "gpio_frames_generated",
    "gpio_items_generated",
    "gpio_frames_framed_pipeline",
    "gpio_items_framed_pipeline",
    "gpio_items_emitted",
    "gpio_frames_transmitted",
    "gpio_items_transmitted_pipeline",
    "gpio_frames_dropped",
    "adc_payload_bytes_produced",
    "adc_payload_bytes_framed",
    "adc_payload_bytes_emitted",
    "adc_payload_bytes_transmitted",
    "adc_payload_bytes_dropped",
    "adc_framed_bytes_framed",
    "adc_framed_bytes_emitted",
    "adc_framed_bytes_transmitted",
    "gpio_payload_bytes_produced",
    "gpio_payload_bytes_framed",
    "gpio_payload_bytes_emitted",
    "gpio_payload_bytes_transmitted",
    "gpio_payload_bytes_dropped",
    "gpio_framed_bytes_framed",
    "gpio_framed_bytes_emitted",
    "gpio_framed_bytes_transmitted",
    "packet_frames_promoted",
    "packet_fairness_deferrals",
    "packet_accounted_frame_skew",
    "data_payload_bytes_transmitted",
    "data_framed_bytes_transmitted",
)
_STATUS_DIAGNOSTIC_U32_FIELDS = (
    "packet_pool_exhaustions",
    "packet_invalid_operations",
    "packet_encoding_rejections",
    "packet_ready_queue_rejections",
    "packet_transmit_queue_rejections",
    "commands_accepted",
    "commands_rejected",
    "bad_checksums",
    "bad_lengths",
    "bad_types",
    "bad_versions",
    "timeouts",
    "partial_usb_writes",
    "state_errors",
    "usb_short_capacity_deferrals",
    "usb_rx_stall_events",
    "usb_tx_stall_events",
    "usb_io_errors",
)
_STATUS_QUEUE_U16_FIELDS = (
    "adc_packet_ready_depth",
    "gpio_packet_ready_depth",
    "adc_packet_transmit_depth",
    "gpio_packet_transmit_depth",
    "adc_packet_ready_high_water",
    "gpio_packet_ready_high_water",
    "adc_packet_transmit_high_water",
    "gpio_packet_transmit_high_water",
    "packet_ready_high_water",
    "packet_transmit_high_water",
    "usb_command_queue_depth",
    "usb_response_queue_depth",
    "usb_lower_priority_queue_depth",
    "usb_command_queue_high_water",
    "usb_response_queue_high_water",
    "usb_active_frame_bytes_sent",
)
_ResponseValue = TypeVar("_ResponseValue")
_DEFAULT_ADC_CONFIGURATION_FLAGS = (
    constants.AdcConfigurationFlag.NO_HARDWARE_AVERAGING
    | constants.AdcConfigurationFlag.HIGH_SPEED
    | constants.AdcConfigurationFlag.SHORTEST_SAMPLE
    | constants.AdcConfigurationFlag.PRIMARY_12_BIT
)
_ALL_CONFIGURATION_PROFILES = constants.ConfigurationProfile(
    constants.SUPPORTED_CONFIGURATION_MASK
)


@dataclass(frozen=True, slots=True)
class AdcTriggerMetadata:
    """Observable 1 MHz ADC_ETC schedule and completion-timing evidence.

    ``completion_delta_cycles`` measures conversion-completion interrupt
    timing. It is a bounded digital cross-check, not an analog aperture
    measurement. ``diagnostic_elapsed_cycles`` may include a small deadline
    overshoot from scheduling or the terminal counter read on a failed check.
    """

    configuration_flags: constants.AdcTriggerConfigurationFlag = (
        constants.AdcTriggerConfigurationFlag.NONE
    )
    error_flags: constants.AdcTriggerError = constants.AdcTriggerError.NONE
    pit_clock_hz: int = constants.ADC_TRIGGER_PIT_CLOCK_HZ
    dwt_clock_hz: int = constants.ADC_TRIGGER_DWT_CLOCK_HZ
    gpio_master_rate_hz: int = constants.ADC_TRIGGER_GPIO_MASTER_RATE_HZ
    pair_rate_hz: int = constants.ADC_TRIGGER_PAIR_RATE_HZ
    ipg_clock_hz: int = constants.ADC_TRIGGER_IPG_CLOCK_HZ
    gpio_master_pit_channel: int = constants.ADC_TRIGGER_GPIO_MASTER_PIT_CHANNEL
    pair_pit_channel: int = constants.ADC_TRIGGER_PAIR_PIT_CHANNEL
    gpio_master_pit_load: int = constants.ADC_TRIGGER_GPIO_MASTER_PIT_LOAD
    pair_pit_load: int = constants.ADC_TRIGGER_PAIR_PIT_LOAD
    predivider: int = constants.ADC_TRIGGER_PREDIVIDER
    chain_length: int = constants.ADC_TRIGGER_CHAIN_LENGTH
    xbar_inputs: tuple[int, int] = constants.ADC_TRIGGER_XBAR_INPUTS
    xbar_outputs: tuple[int, int] = constants.ADC_TRIGGER_XBAR_OUTPUTS
    trigger_queues: tuple[int, int] = constants.ADC_TRIGGER_QUEUES
    initial_delays: tuple[int, int] = constants.ADC_TRIGGER_INITIAL_DELAYS
    effective_delays: tuple[int, int] = constants.ADC_TRIGGER_EFFECTIVE_DELAYS
    phase_ipg_cycles: int = constants.ADC_TRIGGER_PHASE_IPG_CYCLES
    ccm_cscmr1_configured: int = 0
    ccm_ccgr1_configured: int = 0
    ccm_ccgr2_configured: int = 0
    pit_mcr_configured: int = 0
    gpio_master_tctrl_configured: int = 0
    pair_tctrl_configured: int = 0
    adc_etc_ctrl_configured: int = 0
    trigger_ctrl_configured: tuple[int, int] = (0, 0)
    trigger_counter_configured: tuple[int, int] = (0, 0)
    chain_configured: tuple[int, int] = (0, 0)
    done0_1_irq_final: int = 0
    done2_err_irq_final: int = 0
    completion_counts: tuple[int, int] = (0, 0)
    completion_delta_cycles: int = 0
    completion_expected_delta_cycles: int = constants.ADC_COMPLETION_EXPECTED_DWT_CYCLES
    completion_tolerance_cycles: int = constants.ADC_COMPLETION_TOLERANCE_DWT_CYCLES
    diagnostic_elapsed_cycles: int = 0
    trigger_error_count: int = 0
    xbar_sel_configured: tuple[int, int] = (0, 0)

    def __post_init__(self) -> None:
        if isinstance(self.configuration_flags, bool) or isinstance(
            self.error_flags, bool
        ):
            raise TypeError("ADC trigger metadata contains an unknown flag")
        try:
            flags = constants.AdcTriggerConfigurationFlag(self.configuration_flags)
            errors = constants.AdcTriggerError(self.error_flags)
        except (TypeError, ValueError) as exc:
            raise ValueError("ADC trigger metadata contains an unknown flag") from exc
        if int(flags) & ~constants.KNOWN_ADC_TRIGGER_CONFIGURATION_FLAG_MASK:
            raise ValueError("ADC trigger configuration contains reserved flags")
        if int(errors) & ~constants.KNOWN_ADC_TRIGGER_ERROR_MASK:
            raise ValueError("ADC trigger metadata contains reserved error flags")

        fixed_scalars = (
            ("pit_clock_hz", constants.ADC_TRIGGER_PIT_CLOCK_HZ),
            ("dwt_clock_hz", constants.ADC_TRIGGER_DWT_CLOCK_HZ),
            ("gpio_master_rate_hz", constants.ADC_TRIGGER_GPIO_MASTER_RATE_HZ),
            ("pair_rate_hz", constants.ADC_TRIGGER_PAIR_RATE_HZ),
            ("ipg_clock_hz", constants.ADC_TRIGGER_IPG_CLOCK_HZ),
            (
                "gpio_master_pit_channel",
                constants.ADC_TRIGGER_GPIO_MASTER_PIT_CHANNEL,
            ),
            ("pair_pit_channel", constants.ADC_TRIGGER_PAIR_PIT_CHANNEL),
            ("gpio_master_pit_load", constants.ADC_TRIGGER_GPIO_MASTER_PIT_LOAD),
            ("pair_pit_load", constants.ADC_TRIGGER_PAIR_PIT_LOAD),
            ("predivider", constants.ADC_TRIGGER_PREDIVIDER),
            ("chain_length", constants.ADC_TRIGGER_CHAIN_LENGTH),
            ("phase_ipg_cycles", constants.ADC_TRIGGER_PHASE_IPG_CYCLES),
            (
                "completion_expected_delta_cycles",
                constants.ADC_COMPLETION_EXPECTED_DWT_CYCLES,
            ),
            (
                "completion_tolerance_cycles",
                constants.ADC_COMPLETION_TOLERANCE_DWT_CYCLES,
            ),
        )
        if any(
            not isinstance(getattr(self, name), int)
            or isinstance(getattr(self, name), bool)
            or getattr(self, name) != expected
            for name, expected in fixed_scalars
        ):
            raise ValueError("ADC trigger schedule is incompatible with protocol v1")

        fixed_pairs = (
            ("xbar_inputs", constants.ADC_TRIGGER_XBAR_INPUTS),
            ("xbar_outputs", constants.ADC_TRIGGER_XBAR_OUTPUTS),
            ("trigger_queues", constants.ADC_TRIGGER_QUEUES),
            ("initial_delays", constants.ADC_TRIGGER_INITIAL_DELAYS),
            ("effective_delays", constants.ADC_TRIGGER_EFFECTIVE_DELAYS),
        )
        for name, expected in fixed_pairs:
            values = tuple(getattr(self, name))
            if values != expected:
                raise ValueError("ADC trigger routes/delays are incompatible")
            object.__setattr__(self, name, values)

        for name in (
            "trigger_ctrl_configured",
            "trigger_counter_configured",
            "chain_configured",
            "completion_counts",
            "xbar_sel_configured",
        ):
            values = tuple(getattr(self, name))
            if len(values) != 2:
                raise ValueError(f"{name} must contain two converter values")
            bits = 16 if name == "xbar_sel_configured" else 32
            for item in values:
                _unsigned(name, item, bits)
            object.__setattr__(self, name, values)

        for name in (
            "ccm_cscmr1_configured",
            "ccm_ccgr1_configured",
            "ccm_ccgr2_configured",
            "pit_mcr_configured",
            "gpio_master_tctrl_configured",
            "pair_tctrl_configured",
            "adc_etc_ctrl_configured",
            "done0_1_irq_final",
            "done2_err_irq_final",
            "completion_delta_cycles",
            "diagnostic_elapsed_cycles",
            "trigger_error_count",
        ):
            _unsigned(name, getattr(self, name), 32)

        timing_valid = constants.AdcTriggerConfigurationFlag.COMPLETION_TIMING_VALID
        required_timing_flags = (
            constants.AdcTriggerConfigurationFlag.ARM_SEQUENCE_EXERCISED
            | constants.AdcTriggerConfigurationFlag.STOPPED_AFTER_DIAGNOSTIC
        )
        if flags & timing_valid and (
            errors
            or flags & required_timing_flags != required_timing_flags
            or not all(self.completion_counts)
            or abs(self.completion_delta_cycles - self.completion_expected_delta_cycles)
            > self.completion_tolerance_cycles
        ):
            raise ValueError("ADC completion timing evidence is inconsistent")
        object.__setattr__(self, "configuration_flags", flags)
        object.__setattr__(self, "error_flags", errors)

    @property
    def ready(self) -> bool:
        """Return whether every schedule/readback/diagnostic gate passed."""

        return (
            int(self.configuration_flags)
            == constants.KNOWN_ADC_TRIGGER_CONFIGURATION_FLAG_MASK
            and not self.error_flags
        )

    @property
    def completion_timing_delta_ns(self) -> float:
        """Return completion timing in ns; this is not aperture timing."""

        return self.completion_delta_cycles * 1_000_000_000 / self.dwt_clock_hz


def _unsigned(name: str, value: int, bits: int) -> None:
    if (
        not isinstance(value, int)
        or isinstance(value, bool)
        or not 0 <= value < (1 << bits)
    ):
        raise ValueError(f"{name} must be an unsigned {bits}-bit integer")


def _nonnegative(name: str, value: int) -> None:
    if not isinstance(value, int) or isinstance(value, bool) or value < 0:
        raise ValueError(f"{name} must be a nonnegative integer")


def _validated_data_flags(value: constants.FrameFlag | int) -> constants.FrameFlag:
    if isinstance(value, bool):
        raise TypeError("data flags are invalid")
    try:
        flags = constants.FrameFlag(value)
    except (TypeError, ValueError) as exc:
        raise ValueError("data flags are invalid") from exc
    allowed = constants.ALLOWED_FLAGS_BY_KIND[constants.FrameKind.ADC_DATA]
    if int(flags) & ~int(allowed):
        raise ValueError("data flags contain reserved or response-only bits")
    if flags & constants.FrameFlag.OVERRUN_BEFORE and not (
        flags & constants.FrameFlag.GAP_BEFORE
    ):
        raise ValueError("OVERRUN_BEFORE requires GAP_BEFORE")
    return flags


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


def _normalize_adc_metadata(value: Any) -> None:
    """Validate and normalize the common INFO/STATUS ADC metadata fields."""

    resolution = value.adc_resolution_bits
    if not isinstance(value.adc_trigger, AdcTriggerMetadata):
        raise TypeError("adc_trigger must be AdcTriggerMetadata")
    if resolution not in (
        constants.ADC_PRIMARY_RESOLUTION_BITS,
        constants.ADC_FALLBACK_RESOLUTION_BITS,
    ) or isinstance(resolution, bool):
        raise ValueError("ADC resolution must be the primary 12 or gated 10 bits")
    expected_max = (1 << resolution) - 1
    expected_mode = 2 if resolution == constants.ADC_PRIMARY_RESOLUTION_BITS else 1

    try:
        reference = constants.AdcReference(value.adc_reference)
        clock_source = constants.AdcClockSource(value.adc_clock_source)
        calibration_states = tuple(
            constants.AdcCalibrationState(state)
            for state in value.adc_calibration_states
        )
        flags = constants.AdcConfigurationFlag(value.adc_configuration_flags)
        errors = constants.AdcInitializationError(value.adc_initialization_error_flags)
    except (TypeError, ValueError) as exc:
        raise ValueError("ADC metadata contains an unknown enum value") from exc
    if len(calibration_states) != 2:
        raise ValueError("ADC metadata requires two calibration states")
    if int(flags) & ~constants.KNOWN_ADC_CONFIGURATION_FLAG_MASK:
        raise ValueError("ADC configuration contains reserved flags")
    if int(errors) & ~constants.KNOWN_ADC_INITIALIZATION_ERROR_MASK:
        raise ValueError("ADC initialization contains reserved error flags")

    pins = tuple(value.adc_pins)
    peripherals = tuple(value.adc_peripherals)
    channels = tuple(value.adc_channels)
    calibration_cycles = tuple(value.adc_calibration_cycles)
    if pins != constants.ADC_PINS:
        raise ValueError("ADC pins must remain logical ADC0=A0 and ADC1=A1")
    if peripherals != constants.ADC_PERIPHERALS:
        raise ValueError("ADC peripherals must remain ADC1 then ADC2")
    if channels != constants.ADC_CHANNELS:
        raise ValueError("ADC mux channels must remain 7 then 8")
    if len(calibration_cycles) != 2:
        raise ValueError("ADC metadata requires two calibration cycle counts")
    for cycles in calibration_cycles:
        _unsigned("ADC calibration cycles", cycles, 32)

    fixed_values = (
        ("adc_container_bytes", constants.ADC_CONTAINER_BITS // 8),
        ("adc_code_min", constants.ADC_CODE_MIN),
        ("adc_code_max", expected_max),
        ("adc_clock_divider", constants.ADC_CLOCK_DIVIDER),
        ("adc_hardware_average_count", constants.ADC_HARDWARE_AVERAGE_COUNT),
        ("adc_reference_mv_nominal", constants.ADC_REFERENCE_MV_NOMINAL),
        ("adc_input_min_mv_nominal", constants.ADC_INPUT_MIN_MV_NOMINAL),
        ("adc_input_max_mv_nominal", constants.ADC_INPUT_MAX_MV_NOMINAL),
        ("adc_sample_time_adck", constants.ADC_SAMPLE_TIME_ADCK),
        ("adc_conversion_mode", expected_mode),
        ("adc_ipg_clock_hz", constants.ADC_IPG_CLOCK_HZ),
        ("adc_clock_hz", constants.ADC_CLOCK_HZ),
        ("adc_calibration_deadline_us", constants.ADC_CALIBRATION_DEADLINE_US),
    )
    if any(
        not isinstance(getattr(value, name), int)
        or isinstance(getattr(value, name), bool)
        or getattr(value, name) != expected
        for name, expected in fixed_values
    ):
        raise ValueError("ADC metadata is incompatible with protocol v1")
    if reference is not constants.AdcReference.VREFH_VREFL_NOMINAL_3V3:
        raise ValueError("ADC reference must report nominal VREFH/VREFL 3.3 V")
    if clock_source is not constants.AdcClockSource.SYNCHRONOUS_IPG:
        raise ValueError("ADC clock source must report synchronous IPG")

    required = (
        constants.AdcConfigurationFlag.NO_HARDWARE_AVERAGING
        | constants.AdcConfigurationFlag.HIGH_SPEED
        | constants.AdcConfigurationFlag.SHORTEST_SAMPLE
    )
    selected_resolution_flag = (
        constants.AdcConfigurationFlag.PRIMARY_12_BIT
        if resolution == constants.ADC_PRIMARY_RESOLUTION_BITS
        else constants.AdcConfigurationFlag.FALLBACK_10_BIT
    )
    other_resolution_flag = (
        constants.AdcConfigurationFlag.FALLBACK_10_BIT
        if resolution == constants.ADC_PRIMARY_RESOLUTION_BITS
        else constants.AdcConfigurationFlag.PRIMARY_12_BIT
    )
    if flags & required != required or not flags & selected_resolution_flag:
        raise ValueError("ADC configuration flags do not describe actual settings")
    if flags & other_resolution_flag:
        raise ValueError("ADC configuration advertises conflicting resolutions")
    if flags & constants.AdcConfigurationFlag.INITIALIZED:
        required_ready = (
            constants.AdcConfigurationFlag.ROUTES_VALIDATED
            | constants.AdcConfigurationFlag.CONFIGURATION_READBACK_VALID
            | constants.AdcConfigurationFlag.CALIBRATION_COMPLETE
        )
        if (
            errors
            or flags & required_ready != required_ready
            or calibration_states
            != (
                constants.AdcCalibrationState.SUCCEEDED,
                constants.AdcCalibrationState.SUCCEEDED,
            )
        ):
            raise ValueError("initialized ADC metadata is not internally consistent")

    object.__setattr__(value, "adc_reference", reference)
    object.__setattr__(value, "adc_clock_source", clock_source)
    object.__setattr__(value, "adc_calibration_states", calibration_states)
    object.__setattr__(value, "adc_configuration_flags", flags)
    object.__setattr__(value, "adc_initialization_error_flags", errors)
    object.__setattr__(value, "adc_pins", pins)
    object.__setattr__(value, "adc_peripherals", peripherals)
    object.__setattr__(value, "adc_channels", channels)
    object.__setattr__(value, "adc_calibration_cycles", calibration_cycles)


@dataclass(frozen=True, slots=True)
class AdcCalibrationMetadata:
    """Per-converter boot calibration evidence attached to ADC blocks.

    These values describe digital configuration and the bounded hardware
    calibration operation. They are not per-unit voltage calibration data.
    """

    states: tuple[constants.AdcCalibrationState, constants.AdcCalibrationState] = (
        constants.AdcCalibrationState.NOT_RUN,
        constants.AdcCalibrationState.NOT_RUN,
    )
    cycles: tuple[int, int] = (0, 0)
    deadline_us: int = constants.ADC_CALIBRATION_DEADLINE_US
    configuration_flags: constants.AdcConfigurationFlag = (
        _DEFAULT_ADC_CONFIGURATION_FLAGS
    )
    error_flags: constants.AdcInitializationError = (
        constants.AdcInitializationError.NONE
    )

    def __post_init__(self) -> None:
        if isinstance(self.configuration_flags, bool) or isinstance(
            self.error_flags, bool
        ):
            raise TypeError("ADC calibration metadata contains an unknown flag")
        try:
            states = tuple(constants.AdcCalibrationState(item) for item in self.states)
            flags = constants.AdcConfigurationFlag(self.configuration_flags)
            errors = constants.AdcInitializationError(self.error_flags)
        except (TypeError, ValueError) as exc:
            raise ValueError(
                "ADC calibration metadata contains an unknown enum value"
            ) from exc
        cycles = tuple(self.cycles)
        if len(states) != 2 or len(cycles) != 2:
            raise ValueError("ADC calibration metadata requires two converters")
        for value in cycles:
            _unsigned("ADC calibration cycles", value, 32)
        _unsigned("ADC calibration deadline", self.deadline_us, 32)
        if self.deadline_us != constants.ADC_CALIBRATION_DEADLINE_US:
            raise ValueError(
                "ADC calibration deadline is incompatible with protocol v1"
            )
        if int(flags) & ~constants.KNOWN_ADC_CONFIGURATION_FLAG_MASK:
            raise ValueError("ADC calibration configuration contains reserved flags")
        if int(errors) & ~constants.KNOWN_ADC_INITIALIZATION_ERROR_MASK:
            raise ValueError("ADC calibration errors contain reserved flags")
        if flags & constants.AdcConfigurationFlag.INITIALIZED and (
            errors
            or states
            != (
                constants.AdcCalibrationState.SUCCEEDED,
                constants.AdcCalibrationState.SUCCEEDED,
            )
            or flags
            & (
                constants.AdcConfigurationFlag.ROUTES_VALIDATED
                | constants.AdcConfigurationFlag.CONFIGURATION_READBACK_VALID
                | constants.AdcConfigurationFlag.CALIBRATION_COMPLETE
            )
            != (
                constants.AdcConfigurationFlag.ROUTES_VALIDATED
                | constants.AdcConfigurationFlag.CONFIGURATION_READBACK_VALID
                | constants.AdcConfigurationFlag.CALIBRATION_COMPLETE
            )
        ):
            raise ValueError("initialized ADC calibration metadata is inconsistent")
        object.__setattr__(self, "states", states)
        object.__setattr__(self, "cycles", cycles)
        object.__setattr__(self, "configuration_flags", flags)
        object.__setattr__(self, "error_flags", errors)

    @classmethod
    def from_device_metadata(cls, value: Any) -> AdcCalibrationMetadata:
        """Copy the common validated INFO/STATUS calibration fields."""

        return cls(
            states=tuple(value.adc_calibration_states),
            cycles=tuple(value.adc_calibration_cycles),
            deadline_us=value.adc_calibration_deadline_us,
            configuration_flags=value.adc_configuration_flags,
            error_flags=value.adc_initialization_error_flags,
        )

    @property
    def ready(self) -> bool:
        """Whether both converters completed the bounded calibration path."""

        return bool(
            self.configuration_flags & constants.AdcConfigurationFlag.INITIALIZED
        )

    def converter_ready(self, converter: AdcConverter | int) -> bool:
        """Return the independently reported calibration result for one ADC."""

        if isinstance(converter, bool):
            raise TypeError("converter must be ADC0 or ADC1")
        try:
            selected = AdcConverter(converter)
        except (TypeError, ValueError) as exc:
            raise ValueError("converter must be ADC0 or ADC1") from exc
        return self.states[int(selected)] is constants.AdcCalibrationState.SUCCEEDED


_ADC_ACQUISITION_U64_FIELDS = (
    ("ADC0_DMA_MAJOR_LOOPS", "adc0_dma_major_loops"),
    ("ADC1_DMA_MAJOR_LOOPS", "adc1_dma_major_loops"),
    ("ADC0_DMA_RESULTS", "adc0_dma_results"),
    ("ADC1_DMA_RESULTS", "adc1_dma_results"),
    ("ADC_PAIRED_MAJOR_LOOPS", "adc_paired_major_loops"),
    ("ADC_BUFFERS_COMPLETED", "adc_buffers_completed"),
    ("ADC_BUFFERS_ACQUIRED", "adc_buffers_acquired"),
    ("ADC_BUFFERS_RELEASED", "adc_buffers_released"),
    ("ADC_PAIRS_CAPTURED", "adc_pairs_captured"),
    ("ADC_PAIRS_DELIVERED", "adc_pairs_delivered"),
    ("ADC_PAIRS_FRAMED", "adc_pairs_framed"),
    ("ADC_PAIRS_TRANSMITTED", "adc_pairs_transmitted"),
    ("ADC_RAW_PAIRS_LOST", "adc_raw_pairs_lost"),
    ("ADC_STOP_PAIRS_DISCARDED", "adc_stop_pairs_discarded"),
    ("ADC_INCOMPLETE_CONVERSIONS", "adc_incomplete_conversions"),
    ("ADC_OVERWRITTEN_CONVERSIONS", "adc_overwritten_conversions"),
    ("ADC_RAW_RING_OVERRUNS", "adc_raw_ring_overruns"),
    ("ADC_INCOMPLETE_BUFFERS", "adc_incomplete_buffers"),
)
_ADC_ACQUISITION_U32_FIELDS = (
    ("ADC_ETC_ERROR_EVENTS", "adc_etc_error_events"),
    ("ADC_ETC_ERROR_FLAGS", "adc_etc_error_flags"),
    ("ADC_DMA_ERROR_EVENTS", "adc_dma_error_events"),
    ("ADC_COMPLETION_MISMATCHES", "adc_completion_mismatches"),
    ("ADC_DESTINATION_MISMATCHES", "adc_destination_mismatches"),
    ("ADC_SCHEDULE_EXHAUSTIONS", "adc_schedule_exhaustions"),
    ("ADC_RAW_INVARIANT_ERRORS", "adc_raw_invariant_errors"),
    ("ADC_STALE_COMPLETIONS", "adc_stale_completions"),
    ("ADC_RESOURCE_CONFLICTS", "adc_resource_conflicts"),
    ("ADC_START_ERRORS", "adc_start_errors"),
    ("ADC_STOP_ERRORS", "adc_stop_errors"),
    ("ADC_STALE_INTERRUPTS", "adc_stale_interrupts"),
    ("ADC_PACKER_SOURCE_ERRORS", "adc_packer_source_errors"),
    ("ADC_PACKER_PIPELINE_ERRORS", "adc_packer_pipeline_errors"),
    ("ADC_PACKER_CHRONOLOGY_ERRORS", "adc_packer_chronology_errors"),
)


@dataclass(frozen=True, slots=True)
class AdcAcquisitionStatus:
    """One typed STATUS snapshot of the physical ADC DMA-to-USB path."""

    adc0_dma_major_loops: int = 0
    adc1_dma_major_loops: int = 0
    adc0_dma_results: int = 0
    adc1_dma_results: int = 0
    adc_paired_major_loops: int = 0
    adc_buffers_completed: int = 0
    adc_buffers_acquired: int = 0
    adc_buffers_released: int = 0
    adc_pairs_captured: int = 0
    adc_pairs_delivered: int = 0
    adc_pairs_framed: int = 0
    adc_pairs_transmitted: int = 0
    adc_raw_pairs_lost: int = 0
    adc_stop_pairs_discarded: int = 0
    adc_incomplete_conversions: int = 0
    adc_overwritten_conversions: int = 0
    adc_raw_ring_overruns: int = 0
    adc_incomplete_buffers: int = 0
    adc_raw_ready_depth: int = 0
    adc_raw_ready_high_water: int = 0
    adc_etc_error_events: int = 0
    adc_etc_error_flags: int = 0
    adc_dma_error_events: int = 0
    adc_completion_mismatches: int = 0
    adc_destination_mismatches: int = 0
    adc_schedule_exhaustions: int = 0
    adc_raw_invariant_errors: int = 0
    adc_stale_completions: int = 0
    adc_resource_conflicts: int = 0
    adc_start_errors: int = 0
    adc_stop_errors: int = 0
    adc_stale_interrupts: int = 0
    adc_packer_source_errors: int = 0
    adc_packer_pipeline_errors: int = 0
    adc_packer_chronology_errors: int = 0

    def __post_init__(self) -> None:
        for _, name in _ADC_ACQUISITION_U64_FIELDS:
            _unsigned(name, getattr(self, name), 64)
        for _, name in _ADC_ACQUISITION_U32_FIELDS:
            _unsigned(name, getattr(self, name), 32)
        _unsigned("adc_raw_ready_depth", self.adc_raw_ready_depth, 16)
        _unsigned("adc_raw_ready_high_water", self.adc_raw_ready_high_water, 16)
        if self.adc_raw_ready_depth > self.adc_raw_ready_high_water:
            raise ValueError("ADC current ready depth exceeds its high-water depth")

    @classmethod
    def from_status_fields(cls, value: Any) -> AdcAcquisitionStatus:
        """Copy the detailed physical ADC counters from a STATUS-like model."""

        values = {
            name: getattr(value, name)
            for _, name in (
                *_ADC_ACQUISITION_U64_FIELDS,
                *_ADC_ACQUISITION_U32_FIELDS,
            )
        }
        values["adc_raw_ready_depth"] = value.adc_raw_ready_depth
        values["adc_raw_ready_high_water"] = value.adc_raw_ready_high_water
        return cls(**values)

    @property
    def has_conversion_errors(self) -> bool:
        """Whether ADC_ETC/eDMA reported missing or overwritten conversions."""

        return bool(
            self.adc_etc_error_events
            or self.adc_etc_error_flags
            or self.adc_dma_error_events
            or self.adc_incomplete_conversions
            or self.adc_overwritten_conversions
        )

    @property
    def nonzero_error_fields(self) -> tuple[tuple[str, int], ...]:
        """Return nonzero hardware, ownership, lifecycle, and packer errors."""

        error_names = (
            "adc_incomplete_conversions",
            "adc_overwritten_conversions",
            *(name for _, name in _ADC_ACQUISITION_U32_FIELDS),
        )
        return tuple(
            (name, getattr(self, name)) for name in error_names if getattr(self, name)
        )

    @property
    def has_errors(self) -> bool:
        return bool(self.nonzero_error_fields)

    @property
    def has_loss(self) -> bool:
        return bool(
            self.adc_raw_pairs_lost
            or self.adc_stop_pairs_discarded
            or self.adc_raw_ring_overruns
            or self.adc_incomplete_buffers
            or self.has_conversion_errors
        )


@dataclass(frozen=True, slots=True)
class AdcBlockMetadata:
    """Actual ADC format, timing, calibration, and latest error evidence."""

    source: constants.Source = constants.Source.HARDWARE
    timestamp_hz: int = constants.TIMESTAMP_HZ
    pair_rate_hz: int = constants.ADC_PAIR_RATE_HZ
    pair_period_ticks: int = constants.ADC_PAIR_PERIOD_TICKS
    adc1_phase_ticks: int = constants.ADC1_PHASE_TICKS
    resolution_bits: int = constants.ADC_RESOLUTION_BITS
    container_bytes: int = constants.ADC_CONTAINER_BITS // 8
    code_min: int = constants.ADC_CODE_MIN
    code_max: int = (1 << constants.ADC_PRIMARY_RESOLUTION_BITS) - 1
    calibration: AdcCalibrationMetadata = dataclass_field(
        default_factory=AdcCalibrationMetadata
    )
    trigger: AdcTriggerMetadata = dataclass_field(default_factory=AdcTriggerMetadata)
    acquisition: AdcAcquisitionStatus | None = None

    def __post_init__(self) -> None:
        if isinstance(self.source, bool):
            raise TypeError("ADC block source is invalid")
        try:
            source = constants.Source(self.source)
        except (TypeError, ValueError) as exc:
            raise ValueError("ADC block source is invalid") from exc
        object.__setattr__(self, "source", source)
        fixed_values = (
            ("timestamp_hz", self.timestamp_hz, constants.TIMESTAMP_HZ),
            ("pair_rate_hz", self.pair_rate_hz, constants.ADC_PAIR_RATE_HZ),
            (
                "pair_period_ticks",
                self.pair_period_ticks,
                constants.ADC_PAIR_PERIOD_TICKS,
            ),
            ("adc1_phase_ticks", self.adc1_phase_ticks, constants.ADC1_PHASE_TICKS),
            (
                "container_bytes",
                self.container_bytes,
                constants.ADC_CONTAINER_BITS // 8,
            ),
            ("code_min", self.code_min, constants.ADC_CODE_MIN),
        )
        if any(
            not isinstance(actual, int)
            or isinstance(actual, bool)
            or actual != expected
            for _, actual, expected in fixed_values
        ):
            raise ValueError("ADC block timing/container metadata is incompatible")
        if self.resolution_bits not in (
            constants.ADC_PRIMARY_RESOLUTION_BITS,
            constants.ADC_FALLBACK_RESOLUTION_BITS,
        ) or isinstance(self.resolution_bits, bool):
            raise ValueError("ADC block resolution must be 12 or gated 10 bits")
        if self.code_max != (1 << self.resolution_bits) - 1:
            raise ValueError("ADC block code range disagrees with its resolution")
        if not isinstance(self.calibration, AdcCalibrationMetadata):
            raise TypeError("calibration must be AdcCalibrationMetadata")
        if not isinstance(self.trigger, AdcTriggerMetadata):
            raise TypeError("trigger must be AdcTriggerMetadata")
        if self.acquisition is not None and not isinstance(
            self.acquisition, AdcAcquisitionStatus
        ):
            raise TypeError("acquisition must be AdcAcquisitionStatus or None")
        selected_resolution_flag = (
            constants.AdcConfigurationFlag.PRIMARY_12_BIT
            if self.resolution_bits == constants.ADC_PRIMARY_RESOLUTION_BITS
            else constants.AdcConfigurationFlag.FALLBACK_10_BIT
        )
        other_resolution_flag = (
            constants.AdcConfigurationFlag.FALLBACK_10_BIT
            if self.resolution_bits == constants.ADC_PRIMARY_RESOLUTION_BITS
            else constants.AdcConfigurationFlag.PRIMARY_12_BIT
        )
        flags = self.calibration.configuration_flags
        if not flags & selected_resolution_flag or flags & other_resolution_flag:
            raise ValueError("ADC block calibration flags disagree with resolution")

    @classmethod
    def from_device_metadata(
        cls,
        value: Any,
        *,
        source: constants.Source | int,
        acquisition: AdcAcquisitionStatus | None = None,
    ) -> AdcBlockMetadata:
        """Build block metadata from validated INFO plus optional STATUS data."""

        if isinstance(source, bool):
            raise TypeError("ADC block source is invalid")
        try:
            selected_source = constants.Source(source)
        except (TypeError, ValueError) as exc:
            raise ValueError("ADC block source is invalid") from exc
        return cls(
            source=selected_source,
            timestamp_hz=value.timestamp_hz,
            pair_rate_hz=value.adc_pair_rate_hz,
            pair_period_ticks=value.adc_pair_period_ticks,
            adc1_phase_ticks=value.adc1_phase_ticks,
            resolution_bits=value.adc_resolution_bits,
            container_bytes=value.adc_container_bytes,
            code_min=value.adc_code_min,
            code_max=value.adc_code_max,
            calibration=AdcCalibrationMetadata.from_device_metadata(value),
            trigger=value.adc_trigger,
            acquisition=acquisition,
        )

    @property
    def pair_period_seconds(self) -> float:
        return self.pair_period_ticks / self.timestamp_hz

    @property
    def adc1_phase_seconds(self) -> float:
        return self.adc1_phase_ticks / self.timestamp_hz


def _adc_offset(prefix: str, field: str) -> int:
    separator = "" if field[:1] in {"0", "1"} else "_"
    return int(getattr(constants, f"{prefix}_ADC{separator}{field}_OFFSET"))


def _trigger_offset(prefix: str, field: str) -> int:
    return int(getattr(constants, f"{prefix}_{field}_OFFSET"))


def _pack_adc_trigger_metadata(
    payload: bytearray, trigger: AdcTriggerMetadata, prefix: str
) -> None:
    def u16(field: str, value: int) -> None:
        struct.pack_into("<H", payload, _trigger_offset(prefix, field), value)

    def u32(field: str, value: int) -> None:
        struct.pack_into("<I", payload, _trigger_offset(prefix, field), value)

    u16("ADC_TRIGGER_CONFIGURATION_FLAGS", int(trigger.configuration_flags))
    u32("ADC_TRIGGER_ERROR_FLAGS", int(trigger.error_flags))
    for field, value in (
        ("ADC_TRIGGER_PIT_CLOCK_HZ", trigger.pit_clock_hz),
        ("ADC_TRIGGER_DWT_CLOCK_HZ", trigger.dwt_clock_hz),
        ("ADC_TRIGGER_GPIO_MASTER_RATE_HZ", trigger.gpio_master_rate_hz),
        ("ADC_TRIGGER_PAIR_RATE_HZ", trigger.pair_rate_hz),
        ("ADC_TRIGGER_IPG_CLOCK_HZ", trigger.ipg_clock_hz),
    ):
        u32(field, value)
    for field, value in (
        ("ADC_TRIGGER_GPIO_MASTER_PIT_CHANNEL", trigger.gpio_master_pit_channel),
        ("ADC_TRIGGER_PAIR_PIT_CHANNEL", trigger.pair_pit_channel),
        ("ADC_TRIGGER_GPIO_MASTER_PIT_LOAD", trigger.gpio_master_pit_load),
        ("ADC_TRIGGER_PAIR_PIT_LOAD", trigger.pair_pit_load),
        ("ADC_TRIGGER_PREDIVIDER", trigger.predivider),
        ("ADC_TRIGGER_CHAIN_LENGTH", trigger.chain_length),
        ("ADC0_TRIGGER_XBAR_INPUT", trigger.xbar_inputs[0]),
        ("ADC1_TRIGGER_XBAR_INPUT", trigger.xbar_inputs[1]),
        ("ADC0_TRIGGER_XBAR_OUTPUT", trigger.xbar_outputs[0]),
        ("ADC1_TRIGGER_XBAR_OUTPUT", trigger.xbar_outputs[1]),
        ("ADC0_ETC_TRIGGER_QUEUE", trigger.trigger_queues[0]),
        ("ADC1_ETC_TRIGGER_QUEUE", trigger.trigger_queues[1]),
    ):
        payload[_trigger_offset(prefix, field)] = value
    for field, value in (
        ("ADC0_TRIGGER_INITIAL_DELAY", trigger.initial_delays[0]),
        ("ADC1_TRIGGER_INITIAL_DELAY", trigger.initial_delays[1]),
        ("ADC0_TRIGGER_EFFECTIVE_DELAY", trigger.effective_delays[0]),
        ("ADC1_TRIGGER_EFFECTIVE_DELAY", trigger.effective_delays[1]),
        ("ADC_TRIGGER_PHASE_IPG_CYCLES", trigger.phase_ipg_cycles),
        ("ADC0_TRIGGER_XBAR_SEL_CONFIGURED", trigger.xbar_sel_configured[0]),
        ("ADC1_TRIGGER_XBAR_SEL_CONFIGURED", trigger.xbar_sel_configured[1]),
    ):
        u16(field, value)
    for field, value in (
        ("ADC_TRIGGER_CCM_CSCMR1_CONFIGURED", trigger.ccm_cscmr1_configured),
        ("ADC_TRIGGER_CCM_CCGR1_CONFIGURED", trigger.ccm_ccgr1_configured),
        ("ADC_TRIGGER_CCM_CCGR2_CONFIGURED", trigger.ccm_ccgr2_configured),
        ("ADC_TRIGGER_PIT_MCR_CONFIGURED", trigger.pit_mcr_configured),
        (
            "ADC_TRIGGER_GPIO_MASTER_TCTRL_CONFIGURED",
            trigger.gpio_master_tctrl_configured,
        ),
        ("ADC_TRIGGER_PAIR_TCTRL_CONFIGURED", trigger.pair_tctrl_configured),
        ("ADC_ETC_CTRL_CONFIGURED", trigger.adc_etc_ctrl_configured),
        ("ADC0_ETC_TRIGGER_CTRL_CONFIGURED", trigger.trigger_ctrl_configured[0]),
        ("ADC1_ETC_TRIGGER_CTRL_CONFIGURED", trigger.trigger_ctrl_configured[1]),
        (
            "ADC0_ETC_TRIGGER_COUNTER_CONFIGURED",
            trigger.trigger_counter_configured[0],
        ),
        (
            "ADC1_ETC_TRIGGER_COUNTER_CONFIGURED",
            trigger.trigger_counter_configured[1],
        ),
        ("ADC0_ETC_CHAIN_CONFIGURED", trigger.chain_configured[0]),
        ("ADC1_ETC_CHAIN_CONFIGURED", trigger.chain_configured[1]),
        ("ADC_ETC_DONE0_1_IRQ_FINAL", trigger.done0_1_irq_final),
        ("ADC_ETC_DONE2_ERR_IRQ_FINAL", trigger.done2_err_irq_final),
        ("ADC0_COMPLETION_COUNT", trigger.completion_counts[0]),
        ("ADC1_COMPLETION_COUNT", trigger.completion_counts[1]),
        ("ADC_COMPLETION_DELTA_CYCLES", trigger.completion_delta_cycles),
        (
            "ADC_COMPLETION_EXPECTED_DELTA_CYCLES",
            trigger.completion_expected_delta_cycles,
        ),
        ("ADC_COMPLETION_TOLERANCE_CYCLES", trigger.completion_tolerance_cycles),
        (
            "ADC_COMPLETION_DIAGNOSTIC_ELAPSED_CYCLES",
            trigger.diagnostic_elapsed_cycles,
        ),
        ("ADC_TRIGGER_ERROR_COUNT", trigger.trigger_error_count),
    ):
        u32(field, value)


def _unpack_adc_trigger_metadata(payload: bytes, prefix: str) -> AdcTriggerMetadata:
    def u8(field: str) -> int:
        return payload[_trigger_offset(prefix, field)]

    def u16(field: str) -> int:
        return int(struct.unpack_from("<H", payload, _trigger_offset(prefix, field))[0])

    def u32(field: str) -> int:
        return int(struct.unpack_from("<I", payload, _trigger_offset(prefix, field))[0])

    return AdcTriggerMetadata(
        configuration_flags=constants.AdcTriggerConfigurationFlag(
            u16("ADC_TRIGGER_CONFIGURATION_FLAGS")
        ),
        error_flags=constants.AdcTriggerError(u32("ADC_TRIGGER_ERROR_FLAGS")),
        pit_clock_hz=u32("ADC_TRIGGER_PIT_CLOCK_HZ"),
        dwt_clock_hz=u32("ADC_TRIGGER_DWT_CLOCK_HZ"),
        gpio_master_rate_hz=u32("ADC_TRIGGER_GPIO_MASTER_RATE_HZ"),
        pair_rate_hz=u32("ADC_TRIGGER_PAIR_RATE_HZ"),
        ipg_clock_hz=u32("ADC_TRIGGER_IPG_CLOCK_HZ"),
        gpio_master_pit_channel=u8("ADC_TRIGGER_GPIO_MASTER_PIT_CHANNEL"),
        pair_pit_channel=u8("ADC_TRIGGER_PAIR_PIT_CHANNEL"),
        gpio_master_pit_load=u8("ADC_TRIGGER_GPIO_MASTER_PIT_LOAD"),
        pair_pit_load=u8("ADC_TRIGGER_PAIR_PIT_LOAD"),
        predivider=u8("ADC_TRIGGER_PREDIVIDER"),
        chain_length=u8("ADC_TRIGGER_CHAIN_LENGTH"),
        xbar_inputs=(u8("ADC0_TRIGGER_XBAR_INPUT"), u8("ADC1_TRIGGER_XBAR_INPUT")),
        xbar_outputs=(
            u8("ADC0_TRIGGER_XBAR_OUTPUT"),
            u8("ADC1_TRIGGER_XBAR_OUTPUT"),
        ),
        trigger_queues=(
            u8("ADC0_ETC_TRIGGER_QUEUE"),
            u8("ADC1_ETC_TRIGGER_QUEUE"),
        ),
        initial_delays=(
            u16("ADC0_TRIGGER_INITIAL_DELAY"),
            u16("ADC1_TRIGGER_INITIAL_DELAY"),
        ),
        effective_delays=(
            u16("ADC0_TRIGGER_EFFECTIVE_DELAY"),
            u16("ADC1_TRIGGER_EFFECTIVE_DELAY"),
        ),
        phase_ipg_cycles=u16("ADC_TRIGGER_PHASE_IPG_CYCLES"),
        ccm_cscmr1_configured=u32("ADC_TRIGGER_CCM_CSCMR1_CONFIGURED"),
        ccm_ccgr1_configured=u32("ADC_TRIGGER_CCM_CCGR1_CONFIGURED"),
        ccm_ccgr2_configured=u32("ADC_TRIGGER_CCM_CCGR2_CONFIGURED"),
        pit_mcr_configured=u32("ADC_TRIGGER_PIT_MCR_CONFIGURED"),
        gpio_master_tctrl_configured=u32("ADC_TRIGGER_GPIO_MASTER_TCTRL_CONFIGURED"),
        pair_tctrl_configured=u32("ADC_TRIGGER_PAIR_TCTRL_CONFIGURED"),
        adc_etc_ctrl_configured=u32("ADC_ETC_CTRL_CONFIGURED"),
        trigger_ctrl_configured=(
            u32("ADC0_ETC_TRIGGER_CTRL_CONFIGURED"),
            u32("ADC1_ETC_TRIGGER_CTRL_CONFIGURED"),
        ),
        trigger_counter_configured=(
            u32("ADC0_ETC_TRIGGER_COUNTER_CONFIGURED"),
            u32("ADC1_ETC_TRIGGER_COUNTER_CONFIGURED"),
        ),
        chain_configured=(
            u32("ADC0_ETC_CHAIN_CONFIGURED"),
            u32("ADC1_ETC_CHAIN_CONFIGURED"),
        ),
        done0_1_irq_final=u32("ADC_ETC_DONE0_1_IRQ_FINAL"),
        done2_err_irq_final=u32("ADC_ETC_DONE2_ERR_IRQ_FINAL"),
        completion_counts=(
            u32("ADC0_COMPLETION_COUNT"),
            u32("ADC1_COMPLETION_COUNT"),
        ),
        completion_delta_cycles=u32("ADC_COMPLETION_DELTA_CYCLES"),
        completion_expected_delta_cycles=u32("ADC_COMPLETION_EXPECTED_DELTA_CYCLES"),
        completion_tolerance_cycles=u32("ADC_COMPLETION_TOLERANCE_CYCLES"),
        diagnostic_elapsed_cycles=u32("ADC_COMPLETION_DIAGNOSTIC_ELAPSED_CYCLES"),
        trigger_error_count=u32("ADC_TRIGGER_ERROR_COUNT"),
        xbar_sel_configured=(
            u16("ADC0_TRIGGER_XBAR_SEL_CONFIGURED"),
            u16("ADC1_TRIGGER_XBAR_SEL_CONFIGURED"),
        ),
    )


def _pack_adc_metadata(payload: bytearray, value: Any, prefix: str) -> None:
    payload[_adc_offset(prefix, "RESOLUTION_BITS")] = value.adc_resolution_bits
    payload[_adc_offset(prefix, "CONTAINER_BYTES")] = value.adc_container_bytes
    payload[_adc_offset(prefix, "REFERENCE")] = int(value.adc_reference)
    payload[_adc_offset(prefix, "CLOCK_SOURCE")] = int(value.adc_clock_source)
    payload[_adc_offset(prefix, "CLOCK_DIVIDER")] = value.adc_clock_divider
    payload[_adc_offset(prefix, "HARDWARE_AVERAGE_COUNT")] = (
        value.adc_hardware_average_count
    )
    payload[_adc_offset(prefix, "SAMPLE_TIME_ADCK")] = value.adc_sample_time_adck
    payload[_adc_offset(prefix, "CONVERSION_MODE")] = value.adc_conversion_mode
    calibration_states = value.adc_calibration_states
    payload[_adc_offset(prefix, "0_CALIBRATION_STATE")] = int(calibration_states[0])
    payload[_adc_offset(prefix, "1_CALIBRATION_STATE")] = int(calibration_states[1])
    for field, values in (
        ("PIN", value.adc_pins),
        ("PERIPHERAL", value.adc_peripherals),
        ("CHANNEL", value.adc_channels),
    ):
        payload[_adc_offset(prefix, f"0_{field}")] = values[0]
        payload[_adc_offset(prefix, f"1_{field}")] = values[1]
    for field, attribute in (
        ("CODE_MIN", "adc_code_min"),
        ("CODE_MAX", "adc_code_max"),
        ("REFERENCE_MV_NOMINAL", "adc_reference_mv_nominal"),
        ("INPUT_MIN_MV_NOMINAL", "adc_input_min_mv_nominal"),
        ("INPUT_MAX_MV_NOMINAL", "adc_input_max_mv_nominal"),
        ("CONFIGURATION_FLAGS", "adc_configuration_flags"),
    ):
        struct.pack_into(
            "<H", payload, _adc_offset(prefix, field), int(getattr(value, attribute))
        )
    for field, attribute in (
        ("IPG_CLOCK_HZ", "adc_ipg_clock_hz"),
        ("CLOCK_HZ", "adc_clock_hz"),
        ("CALIBRATION_DEADLINE_US", "adc_calibration_deadline_us"),
        ("INITIALIZATION_ERROR_FLAGS", "adc_initialization_error_flags"),
    ):
        struct.pack_into(
            "<I", payload, _adc_offset(prefix, field), int(getattr(value, attribute))
        )
    calibration_cycles = value.adc_calibration_cycles
    struct.pack_into(
        "<I",
        payload,
        _adc_offset(prefix, "0_CALIBRATION_CYCLES"),
        calibration_cycles[0],
    )
    struct.pack_into(
        "<I",
        payload,
        _adc_offset(prefix, "1_CALIBRATION_CYCLES"),
        calibration_cycles[1],
    )
    _pack_adc_trigger_metadata(payload, value.adc_trigger, prefix)


def _unpack_adc_metadata(payload: bytes, prefix: str) -> dict[str, Any]:
    def u16(field: str) -> int:
        return int(struct.unpack_from("<H", payload, _adc_offset(prefix, field))[0])

    def u32(field: str) -> int:
        return int(struct.unpack_from("<I", payload, _adc_offset(prefix, field))[0])

    return {
        "adc_resolution_bits": payload[_adc_offset(prefix, "RESOLUTION_BITS")],
        "adc_container_bytes": payload[_adc_offset(prefix, "CONTAINER_BYTES")],
        "adc_code_min": u16("CODE_MIN"),
        "adc_code_max": u16("CODE_MAX"),
        "adc_reference": constants.AdcReference(
            payload[_adc_offset(prefix, "REFERENCE")]
        ),
        "adc_clock_source": constants.AdcClockSource(
            payload[_adc_offset(prefix, "CLOCK_SOURCE")]
        ),
        "adc_clock_divider": payload[_adc_offset(prefix, "CLOCK_DIVIDER")],
        "adc_hardware_average_count": payload[
            _adc_offset(prefix, "HARDWARE_AVERAGE_COUNT")
        ],
        "adc_reference_mv_nominal": u16("REFERENCE_MV_NOMINAL"),
        "adc_input_min_mv_nominal": u16("INPUT_MIN_MV_NOMINAL"),
        "adc_input_max_mv_nominal": u16("INPUT_MAX_MV_NOMINAL"),
        "adc_sample_time_adck": payload[_adc_offset(prefix, "SAMPLE_TIME_ADCK")],
        "adc_conversion_mode": payload[_adc_offset(prefix, "CONVERSION_MODE")],
        "adc_configuration_flags": constants.AdcConfigurationFlag(
            u16("CONFIGURATION_FLAGS")
        ),
        "adc_calibration_states": (
            constants.AdcCalibrationState(
                payload[_adc_offset(prefix, "0_CALIBRATION_STATE")]
            ),
            constants.AdcCalibrationState(
                payload[_adc_offset(prefix, "1_CALIBRATION_STATE")]
            ),
        ),
        "adc_pins": (
            payload[_adc_offset(prefix, "0_PIN")],
            payload[_adc_offset(prefix, "1_PIN")],
        ),
        "adc_peripherals": (
            payload[_adc_offset(prefix, "0_PERIPHERAL")],
            payload[_adc_offset(prefix, "1_PERIPHERAL")],
        ),
        "adc_channels": (
            payload[_adc_offset(prefix, "0_CHANNEL")],
            payload[_adc_offset(prefix, "1_CHANNEL")],
        ),
        "adc_ipg_clock_hz": u32("IPG_CLOCK_HZ"),
        "adc_clock_hz": u32("CLOCK_HZ"),
        "adc_calibration_deadline_us": u32("CALIBRATION_DEADLINE_US"),
        "adc_calibration_cycles": (
            u32("0_CALIBRATION_CYCLES"),
            u32("1_CALIBRATION_CYCLES"),
        ),
        "adc_initialization_error_flags": constants.AdcInitializationError(
            u32("INITIALIZATION_ERROR_FLAGS")
        ),
        "adc_trigger": _unpack_adc_trigger_metadata(payload, prefix),
    }


def _pack_adc_acquisition_status(payload: bytearray, value: Any) -> None:
    """Pack the detailed STATUS-only ADC acquisition fields."""

    for field_name, attribute_name in _ADC_ACQUISITION_U64_FIELDS:
        struct.pack_into(
            "<Q",
            payload,
            getattr(constants, f"STATUS_RESPONSE_{field_name}_OFFSET"),
            getattr(value, attribute_name),
        )
    struct.pack_into(
        "<HH",
        payload,
        constants.STATUS_RESPONSE_ADC_RAW_READY_DEPTH_OFFSET,
        value.adc_raw_ready_depth,
        value.adc_raw_ready_high_water,
    )
    for field_name, attribute_name in _ADC_ACQUISITION_U32_FIELDS:
        struct.pack_into(
            "<I",
            payload,
            getattr(constants, f"STATUS_RESPONSE_{field_name}_OFFSET"),
            getattr(value, attribute_name),
        )


def _unpack_adc_acquisition_status(payload: bytes) -> dict[str, Any]:
    """Unpack every STATUS-only ADC acquisition counter without expansion."""

    values = {
        attribute_name: int(
            struct.unpack_from(
                "<Q",
                payload,
                getattr(constants, f"STATUS_RESPONSE_{field_name}_OFFSET"),
            )[0]
        )
        for field_name, attribute_name in _ADC_ACQUISITION_U64_FIELDS
    }
    values["adc_raw_ready_depth"] = int(
        struct.unpack_from(
            "<H", payload, constants.STATUS_RESPONSE_ADC_RAW_READY_DEPTH_OFFSET
        )[0]
    )
    values["adc_raw_ready_high_water"] = int(
        struct.unpack_from(
            "<H",
            payload,
            constants.STATUS_RESPONSE_ADC_RAW_READY_HIGH_WATER_OFFSET,
        )[0]
    )
    values.update(
        {
            attribute_name: int(
                struct.unpack_from(
                    "<I",
                    payload,
                    getattr(constants, f"STATUS_RESPONSE_{field_name}_OFFSET"),
                )[0]
            )
            for field_name, attribute_name in _ADC_ACQUISITION_U32_FIELDS
        }
    )
    return values


@dataclass(frozen=True, slots=True)
class DAQConfiguration:
    """Requested or applied ADC/GPIO stream configuration."""

    stream_mask: constants.StreamMask
    source: constants.Source
    data_checksum_algorithm: constants.ChecksumAlgorithm = (
        constants.DEFAULT_CHECKSUM_ALGORITHM
    )
    data_frame_bytes: int = constants.DATA_FRAME_BYTES

    def __post_init__(self) -> None:
        if any(
            isinstance(value, bool)
            for value in (
                self.stream_mask,
                self.source,
                self.data_checksum_algorithm,
            )
        ):
            raise ValueError("configuration contains an unknown enum value")
        try:
            stream_mask = constants.StreamMask(self.stream_mask)
            source = constants.Source(self.source)
            checksum = constants.ChecksumAlgorithm(self.data_checksum_algorithm)
        except (TypeError, ValueError) as exc:
            raise ValueError("configuration contains an unknown enum value") from exc
        object.__setattr__(self, "stream_mask", stream_mask)
        object.__setattr__(self, "source", source)
        object.__setattr__(self, "data_checksum_algorithm", checksum)
        valid_streams = constants.StreamMask.ADC | constants.StreamMask.GPIO
        if int(stream_mask) & ~int(valid_streams):
            raise ValueError("configuration stream mask contains unknown bits")
        if (
            stream_mask == constants.StreamMask.NONE
            and source is not constants.Source.HARDWARE
        ):
            raise ValueError(
                "the zero-stream control profile requires the hardware source"
            )
        if checksum is constants.ChecksumAlgorithm.NONE_RESERVED:
            raise ValueError("configuration cannot select checksum ID zero")
        if checksum not in HOST_SUPPORTED_CHECKSUM_ALGORITHMS:
            raise ValueError(
                f"host has no implementation for checksum algorithm {checksum.name}"
            )
        if (
            not isinstance(self.data_frame_bytes, int)
            or isinstance(self.data_frame_bytes, bool)
            or self.data_frame_bytes != constants.DATA_FRAME_BYTES
        ):
            raise ValueError("protocol v1 data frames are exactly 4096 bytes")

    @property
    def is_control_only(self) -> bool:
        """Whether this is the Phase 03 zero-stream hardware profile."""

        return (
            self.stream_mask == constants.StreamMask.NONE
            and self.source is constants.Source.HARDWARE
        )

    @property
    def profile(self) -> constants.ConfigurationProfile:
        """Return the exact source/stream capability bit for this profile."""

        if self.is_control_only:
            return constants.ConfigurationProfile.NONE
        profiles = {
            (constants.Source.HARDWARE, constants.StreamMask.ADC): (
                constants.ConfigurationProfile.HARDWARE_ADC
            ),
            (constants.Source.HARDWARE, constants.StreamMask.GPIO): (
                constants.ConfigurationProfile.HARDWARE_GPIO
            ),
            (
                constants.Source.HARDWARE,
                constants.StreamMask.ADC | constants.StreamMask.GPIO,
            ): constants.ConfigurationProfile.HARDWARE_COMBINED,
            (constants.Source.SYNTHETIC, constants.StreamMask.ADC): (
                constants.ConfigurationProfile.SYNTHETIC_ADC
            ),
            (constants.Source.SYNTHETIC, constants.StreamMask.GPIO): (
                constants.ConfigurationProfile.SYNTHETIC_GPIO
            ),
            (
                constants.Source.SYNTHETIC,
                constants.StreamMask.ADC | constants.StreamMask.GPIO,
            ): constants.ConfigurationProfile.SYNTHETIC_COMBINED,
        }
        try:
            return profiles[(self.source, self.stream_mask)]
        except KeyError as exc:  # pragma: no cover - constructor constrains values
            raise ValueError("configuration has no protocol-v1 profile") from exc

    @classmethod
    def control_only(cls) -> DAQConfiguration:
        """Construct the exact Phase 03 zero-stream hardware configuration."""

        return cls(
            stream_mask=constants.StreamMask.NONE,
            source=constants.Source.HARDWARE,
            data_checksum_algorithm=constants.DEFAULT_CHECKSUM_ALGORITHM,
            data_frame_bytes=constants.DATA_FRAME_BYTES,
        )

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
    def from_payload(cls, payload: bytes | bytearray | memoryview) -> DAQConfiguration:
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


# ``Configuration`` was the Phase 01 public name. Keep it as a source-compatible
# alias while making the more explicit API name canonical.
Configuration = DAQConfiguration


def _benchmark_vector_bytes(vector: constants.BenchmarkVector) -> int:
    return {
        constants.BenchmarkVector.EMPTY: 0,
        constants.BenchmarkVector.CANONICAL_123456789: 9,
        constants.BenchmarkVector.BUFFER_64: 64,
        constants.BenchmarkVector.BUFFER_512: 512,
        constants.BenchmarkVector.FRAME_COVERAGE: (
            constants.DATA_FRAME_BYTES - constants.TRAILER_SIZE
        ),
    }[vector]


def _validate_gpio_clock_selection(rate_hz: int, event_count: int) -> None:
    _unsigned("rate_hz", rate_hz, 32)
    _unsigned("event_count", event_count, 16)
    if (
        not constants.GPIO_CLOCK_MIN_RATE_HZ
        <= rate_hz
        <= constants.GPIO_CLOCK_PRODUCTION_RATE_HZ
        or constants.GPIO_CLOCK_PIT_HZ % rate_hz != 0
        or constants.GPIO_CLOCK_DWT_HZ % rate_hz != 0
        or not constants.GPIO_CLOCK_MIN_EVENT_COUNT
        <= event_count
        <= constants.GPIO_CLOCK_MAX_EVENT_COUNT
    ):
        raise ValueError("GPIO clock diagnostic selection is invalid")
    elapsed_cycles = event_count * (constants.GPIO_CLOCK_DWT_HZ // rate_hz)
    major_count = 2 * event_count + constants.GPIO_CLOCK_DUPLICATE_GUARD_EVENTS
    if elapsed_cycles > constants.GPIO_CLOCK_MAX_ELAPSED_CYCLES or major_count > 0x7FFF:
        raise ValueError("GPIO clock diagnostic exceeds its duration bound")


@dataclass(frozen=True, slots=True)
class GpioClockDiagnosticRequest:
    """One bounded exact-divisor PIT/XBARA/eDMA measurement selection."""

    rate_hz: int = constants.GPIO_CLOCK_PRODUCTION_RATE_HZ
    event_count: int = constants.GPIO_CLOCK_MAX_EVENT_COUNT

    def __post_init__(self) -> None:
        _validate_gpio_clock_selection(self.rate_hz, self.event_count)

    @property
    def pit_load_value(self) -> int:
        """Exact PIT load required for this requested event rate."""

        return constants.GPIO_CLOCK_PIT_HZ // self.rate_hz - 1

    @property
    def expected_elapsed_cycles(self) -> int:
        """DWT window length for the requested number of events."""

        return self.event_count * (constants.GPIO_CLOCK_DWT_HZ // self.rate_hz)

    @property
    def tcd_major_count(self) -> int:
        """Guarded eDMA major-loop count used to detect duplicate requests."""

        return 2 * self.event_count + constants.GPIO_CLOCK_DUPLICATE_GUARD_EVENTS

    def to_payload(self) -> bytes:
        """Encode the exact eight-byte diagnostic request payload."""

        return _GPIO_CLOCK_DIAGNOSTIC_REQUEST.pack(self.rate_hz, self.event_count, 0)

    @classmethod
    def from_payload(
        cls, payload: bytes | bytearray | memoryview
    ) -> GpioClockDiagnosticRequest:
        payload_bytes = bytes(payload)
        if len(payload_bytes) != constants.GPIO_CLOCK_DIAGNOSTIC_REQUEST_PAYLOAD_SIZE:
            raise FrameValidationError(
                "GPIO clock diagnostic request body must be eight bytes"
            )
        rate_hz, event_count, reserved = _GPIO_CLOCK_DIAGNOSTIC_REQUEST.unpack(
            payload_bytes
        )
        if reserved != 0:
            raise FrameValidationError(
                "GPIO clock diagnostic reserved field must be zero"
            )
        try:
            return cls(rate_hz=rate_hz, event_count=event_count)
        except ValueError as exc:
            raise FrameValidationError(str(exc)) from exc


@dataclass(frozen=True, slots=True)
class ChecksumBenchmarkRequest:
    """One bounded on-device checksum measurement selection."""

    checksum_algorithm: constants.ChecksumAlgorithm
    vector: constants.BenchmarkVector
    memory_region: constants.BenchmarkMemoryRegion
    cache_state: constants.BenchmarkCacheState
    batch_count: int
    iterations_per_batch: int

    def __post_init__(self) -> None:
        if any(
            isinstance(value, bool)
            for value in (
                self.checksum_algorithm,
                self.vector,
                self.memory_region,
                self.cache_state,
            )
        ):
            raise ValueError("checksum benchmark contains an unknown enum value")
        try:
            checksum = constants.ChecksumAlgorithm(self.checksum_algorithm)
            vector = constants.BenchmarkVector(self.vector)
            region = constants.BenchmarkMemoryRegion(self.memory_region)
            cache_state = constants.BenchmarkCacheState(self.cache_state)
        except (TypeError, ValueError) as exc:
            raise ValueError(
                "checksum benchmark contains an unknown enum value"
            ) from exc
        object.__setattr__(self, "checksum_algorithm", checksum)
        object.__setattr__(self, "vector", vector)
        object.__setattr__(self, "memory_region", region)
        object.__setattr__(self, "cache_state", cache_state)
        if checksum not in constants.SUPPORTED_CHECKSUM_ALGORITHMS:
            raise ValueError("checksum benchmark algorithm is not enabled")
        if checksum not in HOST_SUPPORTED_CHECKSUM_ALGORITHMS:
            raise ValueError(
                f"host has no implementation for checksum algorithm {checksum.name}"
            )
        _unsigned("batch_count", self.batch_count, 16)
        _unsigned("iterations_per_batch", self.iterations_per_batch, 16)
        if (
            not 1 <= self.batch_count <= constants.CHECKSUM_BENCHMARK_MAX_BATCH_COUNT
            or not 1
            <= self.iterations_per_batch
            <= constants.CHECKSUM_BENCHMARK_MAX_ITERATIONS_PER_BATCH
        ):
            raise ValueError("checksum benchmark repetition count is invalid")
        if cache_state is constants.BenchmarkCacheState.COLD_INVALIDATED and (
            region is not constants.BenchmarkMemoryRegion.OCRAM_DMA
            or vector is constants.BenchmarkVector.EMPTY
        ):
            raise ValueError("cold-cache benchmark requires nonempty DMA-visible OCRAM")
        if (
            self.operations > constants.CHECKSUM_BENCHMARK_MAX_OPERATIONS
            or self.processed_bytes > constants.CHECKSUM_BENCHMARK_MAX_PROCESSED_BYTES
        ):
            raise ValueError("checksum benchmark exceeds its duration bound")

    @property
    def buffer_bytes(self) -> int:
        return _benchmark_vector_bytes(self.vector)

    @property
    def operations(self) -> int:
        return self.batch_count * self.iterations_per_batch

    @property
    def processed_bytes(self) -> int:
        return self.operations * self.buffer_bytes

    def to_payload(self) -> bytes:
        """Encode the exact eight-byte benchmark request payload."""

        return _CHECKSUM_BENCHMARK_REQUEST.pack(
            int(self.checksum_algorithm),
            int(self.vector),
            int(self.memory_region),
            int(self.cache_state),
            self.batch_count,
            self.iterations_per_batch,
        )

    @classmethod
    def from_payload(
        cls, payload: bytes | bytearray | memoryview
    ) -> ChecksumBenchmarkRequest:
        payload_bytes = bytes(payload)
        if len(payload_bytes) != constants.CHECKSUM_BENCHMARK_REQUEST_PAYLOAD_SIZE:
            raise FrameValidationError(
                "checksum benchmark request body must be eight bytes"
            )
        checksum, vector, region, cache_state, batches, iterations = (
            _CHECKSUM_BENCHMARK_REQUEST.unpack(payload_bytes)
        )
        try:
            return cls(
                checksum_algorithm=constants.ChecksumAlgorithm(checksum),
                vector=constants.BenchmarkVector(vector),
                memory_region=constants.BenchmarkMemoryRegion(region),
                cache_state=constants.BenchmarkCacheState(cache_state),
                batch_count=batches,
                iterations_per_batch=iterations,
            )
        except ValueError as exc:
            raise FrameValidationError(str(exc)) from exc


@dataclass(frozen=True, slots=True)
class ChecksumBenchmarkResult:
    """Measured device cycles, resource cost, and fixed-point projections."""

    request: ChecksumBenchmarkRequest
    buffer_bytes: int
    cycle_counter_hz: int
    timer_overhead_cycles: int
    implementation_code_bytes: int
    table_bytes: int
    working_ram_bytes: int
    deterministic_digest: int
    processed_bytes: int
    raw_checksum_cycles: int
    net_checksum_cycles: int
    cache_setup_cycles: int
    min_batch_cycles: int
    max_batch_cycles: int
    cycles_per_byte_q16: int
    mb_per_second_q16: int
    projected_cpu_percent_q16: int
    target_framed_bytes_per_second: int

    def __post_init__(self) -> None:
        if not isinstance(self.request, ChecksumBenchmarkRequest):
            raise TypeError("request must be a ChecksumBenchmarkRequest")
        for name in (
            "buffer_bytes",
            "cycle_counter_hz",
            "timer_overhead_cycles",
            "implementation_code_bytes",
            "table_bytes",
            "working_ram_bytes",
            "deterministic_digest",
            "min_batch_cycles",
            "max_batch_cycles",
            "cycles_per_byte_q16",
            "mb_per_second_q16",
            "projected_cpu_percent_q16",
            "target_framed_bytes_per_second",
        ):
            _unsigned(name, getattr(self, name), 32)
        for name in (
            "processed_bytes",
            "raw_checksum_cycles",
            "net_checksum_cycles",
            "cache_setup_cycles",
        ):
            _unsigned(name, getattr(self, name), 64)
        expected_table_bytes = (
            0
            if self.request.checksum_algorithm is constants.ChecksumAlgorithm.ADLER32
            else 8192
        )
        calibrated_overhead = self.request.operations * self.timer_overhead_cycles
        if (
            self.buffer_bytes != self.request.buffer_bytes
            or self.cycle_counter_hz != constants.CHECKSUM_BENCHMARK_CYCLE_COUNTER_HZ
            or self.implementation_code_bytes == 0
            or self.table_bytes != expected_table_bytes
            or self.working_ram_bytes != 2 * constants.DATA_FRAME_BYTES
            or self.processed_bytes != self.request.processed_bytes
            or self.raw_checksum_cycles < calibrated_overhead
            or self.raw_checksum_cycles - calibrated_overhead
            != self.net_checksum_cycles
            or self.min_batch_cycles > self.max_batch_cycles
            or self.net_checksum_cycles
            < self.min_batch_cycles * self.request.batch_count
            or self.net_checksum_cycles
            > self.max_batch_cycles * self.request.batch_count
            or (
                self.request.cache_state
                is not constants.BenchmarkCacheState.COLD_INVALIDATED
                and self.cache_setup_cycles != 0
            )
            or self.target_framed_bytes_per_second
            != constants.CHECKSUM_BENCHMARK_TARGET_FRAMED_BYTES_PER_SECOND
        ):
            raise ValueError("checksum benchmark measurements are inconsistent")
        total_cycles = self.net_checksum_cycles + self.cache_setup_cycles
        if self.processed_bytes == 0:
            expected_metrics = (0, 0, 0)
        else:
            if total_cycles == 0:
                raise ValueError("nonempty benchmark requires measured cycles")
            expected_cpb = (total_cycles * 65536) // self.processed_bytes
            bytes_per_second = (
                self.cycle_counter_hz * self.processed_bytes
            ) // total_cycles
            expected_metrics = (
                expected_cpb,
                (bytes_per_second * 65536) // 1_000_000,
                (expected_cpb * self.target_framed_bytes_per_second * 100)
                // self.cycle_counter_hz,
            )
        observed_metrics = (
            self.cycles_per_byte_q16,
            self.mb_per_second_q16,
            self.projected_cpu_percent_q16,
        )
        if observed_metrics != expected_metrics:
            raise ValueError("checksum benchmark derived metrics disagree")

    @property
    def cycles_per_byte(self) -> float:
        return self.cycles_per_byte_q16 / 65536.0

    @property
    def mb_per_second(self) -> float:
        return self.mb_per_second_q16 / 65536.0

    @property
    def projected_cpu_percent(self) -> float:
        return self.projected_cpu_percent_q16 / 65536.0

    @classmethod
    def from_payload(
        cls, payload: bytes | bytearray | memoryview
    ) -> ChecksumBenchmarkResult:
        payload_bytes = bytes(payload)
        _success_prefix(
            payload_bytes, constants.CHECKSUM_BENCHMARK_RESPONSE_PAYLOAD_SIZE
        )

        def u32(offset: int) -> int:
            return struct.unpack_from("<I", payload_bytes, offset)[0]

        def u64(offset: int) -> int:
            return struct.unpack_from("<Q", payload_bytes, offset)[0]

        request_start = constants.CHECKSUM_BENCHMARK_RESPONSE_CHECKSUM_ALGORITHM_OFFSET
        request_end = request_start + constants.CHECKSUM_BENCHMARK_REQUEST_PAYLOAD_SIZE
        return cls(
            request=ChecksumBenchmarkRequest.from_payload(
                payload_bytes[request_start:request_end]
            ),
            buffer_bytes=u32(constants.CHECKSUM_BENCHMARK_RESPONSE_BUFFER_BYTES_OFFSET),
            cycle_counter_hz=u32(
                constants.CHECKSUM_BENCHMARK_RESPONSE_CYCLE_COUNTER_HZ_OFFSET
            ),
            timer_overhead_cycles=u32(
                constants.CHECKSUM_BENCHMARK_RESPONSE_TIMER_OVERHEAD_CYCLES_OFFSET
            ),
            implementation_code_bytes=u32(
                constants.CHECKSUM_BENCHMARK_RESPONSE_IMPLEMENTATION_CODE_BYTES_OFFSET
            ),
            table_bytes=u32(constants.CHECKSUM_BENCHMARK_RESPONSE_TABLE_BYTES_OFFSET),
            working_ram_bytes=u32(
                constants.CHECKSUM_BENCHMARK_RESPONSE_WORKING_RAM_BYTES_OFFSET
            ),
            deterministic_digest=u32(
                constants.CHECKSUM_BENCHMARK_RESPONSE_DETERMINISTIC_DIGEST_OFFSET
            ),
            processed_bytes=u64(
                constants.CHECKSUM_BENCHMARK_RESPONSE_PROCESSED_BYTES_OFFSET
            ),
            raw_checksum_cycles=u64(
                constants.CHECKSUM_BENCHMARK_RESPONSE_RAW_CHECKSUM_CYCLES_OFFSET
            ),
            net_checksum_cycles=u64(
                constants.CHECKSUM_BENCHMARK_RESPONSE_NET_CHECKSUM_CYCLES_OFFSET
            ),
            cache_setup_cycles=u64(
                constants.CHECKSUM_BENCHMARK_RESPONSE_CACHE_SETUP_CYCLES_OFFSET
            ),
            min_batch_cycles=u32(
                constants.CHECKSUM_BENCHMARK_RESPONSE_MIN_BATCH_CYCLES_OFFSET
            ),
            max_batch_cycles=u32(
                constants.CHECKSUM_BENCHMARK_RESPONSE_MAX_BATCH_CYCLES_OFFSET
            ),
            cycles_per_byte_q16=u32(
                constants.CHECKSUM_BENCHMARK_RESPONSE_CYCLES_PER_BYTE_Q16_OFFSET
            ),
            mb_per_second_q16=u32(
                constants.CHECKSUM_BENCHMARK_RESPONSE_MB_PER_SECOND_Q16_OFFSET
            ),
            projected_cpu_percent_q16=u32(
                constants.CHECKSUM_BENCHMARK_RESPONSE_PROJECTED_CPU_PERCENT_Q16_OFFSET
            ),
            target_framed_bytes_per_second=u32(
                constants.CHECKSUM_BENCHMARK_RESPONSE_TARGET_FRAMED_BYTES_PER_SECOND_OFFSET
            ),
        )


@dataclass(frozen=True, slots=True)
class GpioClockDiagnosticResult:
    """Read-only evidence from one bounded PIT/XBARA/eDMA measurement."""

    request: GpioClockDiagnosticRequest
    production_rate_hz: int
    pit_clock_hz: int
    pit_load_value: int
    scheduled_event_count: int
    dma_sample_count: int
    dwt_counter_hz: int
    dwt_elapsed_cycles: int
    hardware_error_flags: constants.GpioClockError
    ccm_cscmr1_configured: int
    ccm_ccgr1_configured: int
    ccm_ccgr2_configured: int
    ccm_ccgr5_configured: int
    pit_mcr_configured: int
    pit_ldval_configured: int
    pit_cval_final: int
    pit_tctrl_configured: int
    pit_tflg_final: int
    xbar_sel_configured: int
    xbar_ctrl_configured: int
    dmamux_chcfg_configured: int
    dma_cr_configured: int
    dma_es_final: int
    dma_erq_configured: int
    dma_err_final: int
    dma_hrs_final: int
    tcd_saddr: int
    tcd_daddr: int
    tcd_nbytes: int
    last_sample_word: int
    tcd_citer_final: int
    tcd_biter: int
    tcd_csr_final: int
    tcd_attr: int
    pit_channel: int
    xbar_input: int
    xbar_output: int
    edma_channel: int
    dmamux_source: int
    edma_priority: int
    tcd_soff: int

    def __post_init__(self) -> None:
        if not isinstance(self.request, GpioClockDiagnosticRequest):
            raise TypeError("request must be a GpioClockDiagnosticRequest")
        for name in (
            "production_rate_hz",
            "pit_clock_hz",
            "pit_load_value",
            "scheduled_event_count",
            "dma_sample_count",
            "dwt_counter_hz",
            "dwt_elapsed_cycles",
            "ccm_cscmr1_configured",
            "ccm_ccgr1_configured",
            "ccm_ccgr2_configured",
            "ccm_ccgr5_configured",
            "pit_mcr_configured",
            "pit_ldval_configured",
            "pit_cval_final",
            "pit_tctrl_configured",
            "pit_tflg_final",
            "dmamux_chcfg_configured",
            "dma_cr_configured",
            "dma_es_final",
            "dma_erq_configured",
            "dma_err_final",
            "dma_hrs_final",
            "tcd_saddr",
            "tcd_daddr",
            "tcd_nbytes",
            "last_sample_word",
        ):
            _unsigned(name, getattr(self, name), 32)
        for name in (
            "xbar_sel_configured",
            "xbar_ctrl_configured",
            "tcd_citer_final",
            "tcd_biter",
            "tcd_csr_final",
            "tcd_attr",
            "tcd_soff",
        ):
            _unsigned(name, getattr(self, name), 16)
        for name in (
            "pit_channel",
            "xbar_input",
            "xbar_output",
            "edma_channel",
            "dmamux_source",
            "edma_priority",
        ):
            _unsigned(name, getattr(self, name), 8)
        if isinstance(self.hardware_error_flags, bool):
            raise TypeError("hardware_error_flags contains reserved bits")
        raw_errors = int(self.hardware_error_flags)
        if raw_errors & ~constants.KNOWN_GPIO_CLOCK_ERROR_MASK:
            raise ValueError("hardware_error_flags contains reserved bits")
        errors = constants.GpioClockError(raw_errors)
        object.__setattr__(self, "hardware_error_flags", errors)

        unarmed_errors = (
            constants.GpioClockError.DWT_UNAVAILABLE
            | constants.GpioClockError.RESOURCE_BUSY
        )
        configuration_was_armed = not errors & unarmed_errors
        expected_scheduled = (
            self.dwt_elapsed_cycles
            // (constants.GPIO_CLOCK_DWT_HZ // self.request.rate_hz)
            if self.dwt_counter_hz == constants.GPIO_CLOCK_DWT_HZ
            else 0
        )
        if (
            self.production_rate_hz != constants.GPIO_CLOCK_PRODUCTION_RATE_HZ
            or self.pit_clock_hz != constants.GPIO_CLOCK_PIT_HZ
            or self.pit_load_value != self.request.pit_load_value
            or (
                configuration_was_armed
                and (
                    self.tcd_biter != self.request.tcd_major_count
                    or self.tcd_citer_final > self.tcd_biter
                    or self.dma_sample_count != self.tcd_biter - self.tcd_citer_final
                )
            )
            or (
                self.dwt_counter_hz == constants.GPIO_CLOCK_DWT_HZ
                and self.scheduled_event_count != expected_scheduled
            )
            or (
                not errors
                and (
                    self.dwt_counter_hz != constants.GPIO_CLOCK_DWT_HZ
                    or self.dwt_elapsed_cycles == 0
                    or abs(self.scheduled_event_count - self.request.event_count)
                    > constants.GPIO_CLOCK_COUNT_TOLERANCE
                    or abs(self.dma_sample_count - self.scheduled_event_count)
                    > constants.GPIO_CLOCK_COUNT_TOLERANCE
                )
            )
        ):
            raise ValueError("GPIO clock diagnostic evidence is inconsistent")

    @property
    def configured_rate_hz(self) -> int:
        return self.request.rate_hz

    @property
    def requested_event_count(self) -> int:
        return self.request.event_count

    @property
    def healthy(self) -> bool:
        """Whether all hardware configuration and count checks passed."""

        return self.hardware_error_flags == constants.GpioClockError.NONE

    @property
    def count_error(self) -> int:
        """Observed DMA samples minus DWT-derived scheduled events."""

        return self.dma_sample_count - self.scheduled_event_count

    @property
    def measured_rate_hz(self) -> float:
        """DMA sample rate measured by DWT, or zero without a valid window."""

        if self.dwt_counter_hz == 0 or self.dwt_elapsed_cycles == 0:
            return 0.0
        return (self.dma_sample_count * self.dwt_counter_hz) / self.dwt_elapsed_cycles

    @classmethod
    def from_payload(
        cls, payload: bytes | bytearray | memoryview
    ) -> GpioClockDiagnosticResult:
        payload_bytes = bytes(payload)
        _success_prefix(
            payload_bytes, constants.GPIO_CLOCK_DIAGNOSTIC_RESPONSE_PAYLOAD_SIZE
        )

        def u8(offset: int) -> int:
            return payload_bytes[offset]

        def u16(offset: int) -> int:
            return struct.unpack_from("<H", payload_bytes, offset)[0]

        def u32(offset: int) -> int:
            return struct.unpack_from("<I", payload_bytes, offset)[0]

        rate_hz = u32(
            constants.GPIO_CLOCK_DIAGNOSTIC_RESPONSE_CONFIGURED_RATE_HZ_OFFSET
        )
        requested_events = u32(
            constants.GPIO_CLOCK_DIAGNOSTIC_RESPONSE_REQUESTED_EVENT_COUNT_OFFSET
        )
        if requested_events > 0xFFFF:
            raise FrameValidationError(
                "GPIO clock diagnostic event count exceeds the request field"
            )
        try:
            return cls(
                request=GpioClockDiagnosticRequest(rate_hz, requested_events),
                production_rate_hz=u32(
                    constants.GPIO_CLOCK_DIAGNOSTIC_RESPONSE_PRODUCTION_RATE_HZ_OFFSET
                ),
                pit_clock_hz=u32(
                    constants.GPIO_CLOCK_DIAGNOSTIC_RESPONSE_PIT_CLOCK_HZ_OFFSET
                ),
                pit_load_value=u32(
                    constants.GPIO_CLOCK_DIAGNOSTIC_RESPONSE_PIT_LOAD_VALUE_OFFSET
                ),
                scheduled_event_count=u32(
                    constants.GPIO_CLOCK_DIAGNOSTIC_RESPONSE_SCHEDULED_EVENT_COUNT_OFFSET
                ),
                dma_sample_count=u32(
                    constants.GPIO_CLOCK_DIAGNOSTIC_RESPONSE_DMA_SAMPLE_COUNT_OFFSET
                ),
                dwt_counter_hz=u32(
                    constants.GPIO_CLOCK_DIAGNOSTIC_RESPONSE_DWT_COUNTER_HZ_OFFSET
                ),
                dwt_elapsed_cycles=u32(
                    constants.GPIO_CLOCK_DIAGNOSTIC_RESPONSE_DWT_ELAPSED_CYCLES_OFFSET
                ),
                hardware_error_flags=constants.GpioClockError(
                    u32(
                        constants.GPIO_CLOCK_DIAGNOSTIC_RESPONSE_HARDWARE_ERROR_FLAGS_OFFSET
                    )
                ),
                ccm_cscmr1_configured=u32(
                    constants.GPIO_CLOCK_DIAGNOSTIC_RESPONSE_CCM_CSCMR1_CONFIGURED_OFFSET
                ),
                ccm_ccgr1_configured=u32(
                    constants.GPIO_CLOCK_DIAGNOSTIC_RESPONSE_CCM_CCGR1_CONFIGURED_OFFSET
                ),
                ccm_ccgr2_configured=u32(
                    constants.GPIO_CLOCK_DIAGNOSTIC_RESPONSE_CCM_CCGR2_CONFIGURED_OFFSET
                ),
                ccm_ccgr5_configured=u32(
                    constants.GPIO_CLOCK_DIAGNOSTIC_RESPONSE_CCM_CCGR5_CONFIGURED_OFFSET
                ),
                pit_mcr_configured=u32(
                    constants.GPIO_CLOCK_DIAGNOSTIC_RESPONSE_PIT_MCR_CONFIGURED_OFFSET
                ),
                pit_ldval_configured=u32(
                    constants.GPIO_CLOCK_DIAGNOSTIC_RESPONSE_PIT_LDVAL_CONFIGURED_OFFSET
                ),
                pit_cval_final=u32(
                    constants.GPIO_CLOCK_DIAGNOSTIC_RESPONSE_PIT_CVAL_FINAL_OFFSET
                ),
                pit_tctrl_configured=u32(
                    constants.GPIO_CLOCK_DIAGNOSTIC_RESPONSE_PIT_TCTRL_CONFIGURED_OFFSET
                ),
                pit_tflg_final=u32(
                    constants.GPIO_CLOCK_DIAGNOSTIC_RESPONSE_PIT_TFLG_FINAL_OFFSET
                ),
                xbar_sel_configured=u16(
                    constants.GPIO_CLOCK_DIAGNOSTIC_RESPONSE_XBAR_SEL_CONFIGURED_OFFSET
                ),
                xbar_ctrl_configured=u16(
                    constants.GPIO_CLOCK_DIAGNOSTIC_RESPONSE_XBAR_CTRL_CONFIGURED_OFFSET
                ),
                dmamux_chcfg_configured=u32(
                    constants.GPIO_CLOCK_DIAGNOSTIC_RESPONSE_DMAMUX_CHCFG_CONFIGURED_OFFSET
                ),
                dma_cr_configured=u32(
                    constants.GPIO_CLOCK_DIAGNOSTIC_RESPONSE_DMA_CR_CONFIGURED_OFFSET
                ),
                dma_es_final=u32(
                    constants.GPIO_CLOCK_DIAGNOSTIC_RESPONSE_DMA_ES_FINAL_OFFSET
                ),
                dma_erq_configured=u32(
                    constants.GPIO_CLOCK_DIAGNOSTIC_RESPONSE_DMA_ERQ_CONFIGURED_OFFSET
                ),
                dma_err_final=u32(
                    constants.GPIO_CLOCK_DIAGNOSTIC_RESPONSE_DMA_ERR_FINAL_OFFSET
                ),
                dma_hrs_final=u32(
                    constants.GPIO_CLOCK_DIAGNOSTIC_RESPONSE_DMA_HRS_FINAL_OFFSET
                ),
                tcd_saddr=u32(
                    constants.GPIO_CLOCK_DIAGNOSTIC_RESPONSE_TCD_SADDR_OFFSET
                ),
                tcd_daddr=u32(
                    constants.GPIO_CLOCK_DIAGNOSTIC_RESPONSE_TCD_DADDR_OFFSET
                ),
                tcd_nbytes=u32(
                    constants.GPIO_CLOCK_DIAGNOSTIC_RESPONSE_TCD_NBYTES_OFFSET
                ),
                last_sample_word=u32(
                    constants.GPIO_CLOCK_DIAGNOSTIC_RESPONSE_LAST_SAMPLE_WORD_OFFSET
                ),
                tcd_citer_final=u16(
                    constants.GPIO_CLOCK_DIAGNOSTIC_RESPONSE_TCD_CITER_FINAL_OFFSET
                ),
                tcd_biter=u16(
                    constants.GPIO_CLOCK_DIAGNOSTIC_RESPONSE_TCD_BITER_OFFSET
                ),
                tcd_csr_final=u16(
                    constants.GPIO_CLOCK_DIAGNOSTIC_RESPONSE_TCD_CSR_FINAL_OFFSET
                ),
                tcd_attr=u16(constants.GPIO_CLOCK_DIAGNOSTIC_RESPONSE_TCD_ATTR_OFFSET),
                pit_channel=u8(
                    constants.GPIO_CLOCK_DIAGNOSTIC_RESPONSE_PIT_CHANNEL_OFFSET
                ),
                xbar_input=u8(
                    constants.GPIO_CLOCK_DIAGNOSTIC_RESPONSE_XBAR_INPUT_OFFSET
                ),
                xbar_output=u8(
                    constants.GPIO_CLOCK_DIAGNOSTIC_RESPONSE_XBAR_OUTPUT_OFFSET
                ),
                edma_channel=u8(
                    constants.GPIO_CLOCK_DIAGNOSTIC_RESPONSE_EDMA_CHANNEL_OFFSET
                ),
                dmamux_source=u8(
                    constants.GPIO_CLOCK_DIAGNOSTIC_RESPONSE_DMAMUX_SOURCE_OFFSET
                ),
                edma_priority=u8(
                    constants.GPIO_CLOCK_DIAGNOSTIC_RESPONSE_EDMA_PRIORITY_OFFSET
                ),
                tcd_soff=u16(constants.GPIO_CLOCK_DIAGNOSTIC_RESPONSE_TCD_SOFF_OFFSET),
            )
        except (TypeError, ValueError) as exc:
            raise FrameValidationError(str(exc)) from exc


@dataclass(frozen=True, slots=True)
class GpioCaptureDiagnosticResult:
    """Safe IDLE-only GPIO capture, packing, and cleanup evidence."""

    mode: constants.GpioCaptureDiagnosticMode
    metadata_kind: int
    drive_safety: int
    stimulus_kind: int
    fixture_identity: int
    stimulus_identity: int
    hardware_error_flags: constants.GpioCaptureError
    diagnostic_flags: constants.GpioCaptureDiagnosticFlag
    dwt_counter_hz: int
    dwt_elapsed_cycles: int
    dma_samples_captured: int
    complete_samples_retained: int
    samples_analyzed: int
    stopped_partial_samples: int
    raw_word_and: int
    raw_word_or: int
    observed_transitions: int
    mapping_values_checked: int
    mapping_failures: int
    unstable_samples: int
    packed_value_and: int
    packed_value_or: int
    first_packed_value: int
    last_packed_value: int
    gpr27_before: int
    gpr27_configured: int
    gpr27_after: int
    gpio2_gdir_before: int
    gpio2_gdir_configured: int
    gpio2_gdir_after: int
    gpio2_psr_before: int
    gpio2_psr_configured: int
    gpio2_psr_after: int
    pit_ldval_configured: int
    pit_tctrl_configured: int
    dmamux_chcfg_configured: int
    dma_erq_configured: int
    dma_err_final: int
    tcd_citer_configured: int
    tcd_biter_configured: int
    tcd_csr_configured: int
    edma_priority_configured: int
    analysis_sample_limit: int

    def __post_init__(self) -> None:
        try:
            mode = constants.GpioCaptureDiagnosticMode(self.mode)
            errors = constants.GpioCaptureError(self.hardware_error_flags)
            flags = constants.GpioCaptureDiagnosticFlag(self.diagnostic_flags)
        except (TypeError, ValueError) as exc:
            raise ValueError(
                "GPIO capture diagnostic contains an unknown enum"
            ) from exc
        if int(errors) & ~constants.KNOWN_GPIO_CAPTURE_ERROR_MASK:
            raise ValueError("GPIO capture diagnostic error mask has reserved bits")
        if int(flags) & ~constants.KNOWN_GPIO_CAPTURE_DIAGNOSTIC_FLAG_MASK:
            raise ValueError("GPIO capture diagnostic flag mask has reserved bits")
        if not flags & constants.GpioCaptureDiagnosticFlag.AVAILABLE:
            raise ValueError("GPIO capture diagnostic is not marked available")
        object.__setattr__(self, "mode", mode)
        object.__setattr__(self, "hardware_error_flags", errors)
        object.__setattr__(self, "diagnostic_flags", flags)
        for name in ("metadata_kind", "drive_safety", "stimulus_kind"):
            _unsigned(name, getattr(self, name), 8)
            if getattr(self, name) > 2:
                raise ValueError(f"{name} is unknown")
        for name in (
            "fixture_identity",
            "stimulus_identity",
            "dwt_counter_hz",
            "dwt_elapsed_cycles",
            "complete_samples_retained",
            "samples_analyzed",
            "stopped_partial_samples",
            "raw_word_and",
            "raw_word_or",
            "observed_transitions",
            "gpr27_before",
            "gpr27_configured",
            "gpr27_after",
            "gpio2_gdir_before",
            "gpio2_gdir_configured",
            "gpio2_gdir_after",
            "gpio2_psr_before",
            "gpio2_psr_configured",
            "gpio2_psr_after",
            "pit_ldval_configured",
            "pit_tctrl_configured",
            "dmamux_chcfg_configured",
            "dma_erq_configured",
            "dma_err_final",
            "analysis_sample_limit",
        ):
            _unsigned(name, getattr(self, name), 32)
        _unsigned("dma_samples_captured", self.dma_samples_captured, 64)
        for name in (
            "mapping_values_checked",
            "mapping_failures",
            "unstable_samples",
            "tcd_citer_configured",
            "tcd_biter_configured",
            "tcd_csr_configured",
        ):
            _unsigned(name, getattr(self, name), 16)
        for name in (
            "packed_value_and",
            "packed_value_or",
            "first_packed_value",
            "last_packed_value",
            "edma_priority_configured",
        ):
            _unsigned(name, getattr(self, name), 8)
        if (
            self.complete_samples_retained > self.dma_samples_captured
            or self.samples_analyzed > self.complete_samples_retained
            or self.samples_analyzed > self.analysis_sample_limit
            or not 0 < self.analysis_sample_limit <= constants.GPIO_SAMPLES_PER_FRAME
            or flags & constants.GpioCaptureDiagnosticFlag.OUTPUT_DRIVE_EXERCISED
            and not flags & constants.GpioCaptureDiagnosticFlag.OUTPUT_DRIVE_PERMITTED
        ):
            raise ValueError("GPIO capture diagnostic evidence is inconsistent")

    @property
    def healthy(self) -> bool:
        return self.hardware_error_flags == constants.GpioCaptureError.NONE

    @classmethod
    def from_payload(
        cls, payload: bytes | bytearray | memoryview
    ) -> GpioCaptureDiagnosticResult:
        data = bytes(payload)
        _success_prefix(data, constants.GPIO_CAPTURE_DIAGNOSTIC_RESPONSE_PAYLOAD_SIZE)

        def u8(name: str) -> int:
            return data[
                getattr(constants, f"GPIO_CAPTURE_DIAGNOSTIC_RESPONSE_{name}_OFFSET")
            ]

        def u16(name: str) -> int:
            return struct.unpack_from(
                "<H",
                data,
                getattr(constants, f"GPIO_CAPTURE_DIAGNOSTIC_RESPONSE_{name}_OFFSET"),
            )[0]

        def u32(name: str) -> int:
            return struct.unpack_from(
                "<I",
                data,
                getattr(constants, f"GPIO_CAPTURE_DIAGNOSTIC_RESPONSE_{name}_OFFSET"),
            )[0]

        values: dict[str, int | constants.GpioCaptureDiagnosticMode] = {
            "mode": constants.GpioCaptureDiagnosticMode(u8("MODE")),
            "metadata_kind": u8("METADATA_KIND"),
            "drive_safety": u8("DRIVE_SAFETY"),
            "stimulus_kind": u8("STIMULUS_KIND"),
            "hardware_error_flags": constants.GpioCaptureError(
                u32("HARDWARE_ERROR_FLAGS")
            ),
            "diagnostic_flags": constants.GpioCaptureDiagnosticFlag(
                u32("DIAGNOSTIC_FLAGS")
            ),
            "dma_samples_captured": struct.unpack_from(
                "<Q",
                data,
                constants.GPIO_CAPTURE_DIAGNOSTIC_RESPONSE_DMA_SAMPLES_CAPTURED_OFFSET,
            )[0],
        }
        for field in (
            "fixture_identity",
            "stimulus_identity",
            "dwt_counter_hz",
            "dwt_elapsed_cycles",
            "complete_samples_retained",
            "samples_analyzed",
            "stopped_partial_samples",
            "raw_word_and",
            "raw_word_or",
            "observed_transitions",
            "gpr27_before",
            "gpr27_configured",
            "gpr27_after",
            "gpio2_gdir_before",
            "gpio2_gdir_configured",
            "gpio2_gdir_after",
            "gpio2_psr_before",
            "gpio2_psr_configured",
            "gpio2_psr_after",
            "pit_ldval_configured",
            "pit_tctrl_configured",
            "dmamux_chcfg_configured",
            "dma_erq_configured",
            "dma_err_final",
            "analysis_sample_limit",
        ):
            values[field] = u32(field.upper())
        for field in (
            "mapping_values_checked",
            "mapping_failures",
            "unstable_samples",
            "tcd_citer_configured",
            "tcd_biter_configured",
            "tcd_csr_configured",
        ):
            values[field] = u16(field.upper())
        for field in (
            "packed_value_and",
            "packed_value_or",
            "first_packed_value",
            "last_packed_value",
            "edma_priority_configured",
        ):
            values[field] = u8(field.upper())
        try:
            return cls(**values)  # type: ignore[arg-type]
        except (TypeError, ValueError) as exc:
            raise FrameValidationError(str(exc)) from exc


@dataclass(frozen=True, slots=True)
class DeviceCapabilities:
    """Validated fixed and negotiated capabilities reported by INFO."""

    supported_stream_mask: constants.StreamMask
    supported_source_mask: int
    supported_checksum_mask: int
    capability_bits: constants.Capability
    supported_configuration_mask: constants.ConfigurationProfile = (
        _ALL_CONFIGURATION_PROFILES
    )
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
    adc_code_min: int = constants.ADC_CODE_MIN
    adc_code_max: int = (1 << constants.ADC_PRIMARY_RESOLUTION_BITS) - 1
    adc_reference: constants.AdcReference = (
        constants.AdcReference.VREFH_VREFL_NOMINAL_3V3
    )
    adc_clock_source: constants.AdcClockSource = (
        constants.AdcClockSource.SYNCHRONOUS_IPG
    )
    adc_clock_divider: int = constants.ADC_CLOCK_DIVIDER
    adc_hardware_average_count: int = constants.ADC_HARDWARE_AVERAGE_COUNT
    adc_reference_mv_nominal: int = constants.ADC_REFERENCE_MV_NOMINAL
    adc_input_min_mv_nominal: int = constants.ADC_INPUT_MIN_MV_NOMINAL
    adc_input_max_mv_nominal: int = constants.ADC_INPUT_MAX_MV_NOMINAL
    adc_sample_time_adck: int = constants.ADC_SAMPLE_TIME_ADCK
    adc_conversion_mode: int = 2
    adc_configuration_flags: constants.AdcConfigurationFlag = (
        _DEFAULT_ADC_CONFIGURATION_FLAGS
    )
    adc_calibration_states: tuple[
        constants.AdcCalibrationState, constants.AdcCalibrationState
    ] = (
        constants.AdcCalibrationState.NOT_RUN,
        constants.AdcCalibrationState.NOT_RUN,
    )
    adc_pins: tuple[int, int] = constants.ADC_PINS
    adc_peripherals: tuple[int, int] = constants.ADC_PERIPHERALS
    adc_channels: tuple[int, int] = constants.ADC_CHANNELS
    adc_ipg_clock_hz: int = constants.ADC_IPG_CLOCK_HZ
    adc_clock_hz: int = constants.ADC_CLOCK_HZ
    adc_calibration_deadline_us: int = constants.ADC_CALIBRATION_DEADLINE_US
    adc_calibration_cycles: tuple[int, int] = (0, 0)
    adc_initialization_error_flags: constants.AdcInitializationError = (
        constants.AdcInitializationError.NONE
    )
    adc_trigger: AdcTriggerMetadata = AdcTriggerMetadata()
    gpio_pin_map: tuple[int, ...] = constants.GPIO_PINS_BY_BIT
    gpio_packed_width_bits: int = constants.GPIO_PACKED_WIDTH_BITS
    gpio_raw_ring_depth: int = constants.GPIO_RAW_RING_DEPTH
    gpio_packed_ring_depth: int = constants.GPIO_PACKED_RING_DEPTH
    gpio_capture_diagnostic_mode: constants.GpioCaptureDiagnosticMode = (
        constants.GpioCaptureDiagnosticMode.NON_DRIVING_CAPTURE
    )
    gpio_capture_diagnostic_flags: constants.GpioCaptureDiagnosticFlag = (
        constants.GpioCaptureDiagnosticFlag.NONE
    )
    gpio_raw_samples_per_buffer: int = constants.GPIO_RAW_SAMPLES_PER_BUFFER
    gpio_raw_ring_bytes: int = constants.GPIO_RAW_RING_BYTES
    gpio_packed_ring_bytes: int = constants.GPIO_PACKED_RING_BYTES
    gpio_packet_buffer_count: int = constants.GPIO_PACKET_BUFFER_COUNT
    gpio_pit_channel: int = constants.GPIO_PIT_CHANNEL
    gpio_xbar_input: int = constants.GPIO_XBAR_INPUT
    gpio_xbar_output: int = constants.GPIO_XBAR_OUTPUT
    gpio_edma_channel: int = constants.GPIO_EDMA_CHANNEL
    gpio_dmamux_source: int = constants.GPIO_DMAMUX_SOURCE
    gpio_edma_priority: int = constants.GPIO_EDMA_PRIORITY
    gpio_xbar_active_edge: int = constants.GPIO_XBAR_ACTIVE_EDGE
    data_payload_bytes: int = constants.DATA_PAYLOAD_BYTES
    adc_pairs_per_frame: int = constants.ADC_PAIRS_PER_FRAME
    gpio_samples_per_frame: int = constants.GPIO_SAMPLES_PER_FRAME
    frame_coverage_ticks: int = constants.FRAME_COVERAGE_TICKS
    adc_dma_ring_depth: int = constants.ADC_DMA_RING_DEPTH
    adc_pair_bytes: int = constants.ADC_PAIR_BYTES
    adc_edma_channels: tuple[int, int] = constants.ADC_EDMA_CHANNELS
    adc_edma_priorities: tuple[int, int] = constants.ADC_EDMA_PRIORITIES
    adc_dmamux_sources: tuple[int, int] = constants.ADC_DMAMUX_SOURCES
    adc_dma_irq_priority: int = constants.ADC_DMA_IRQ_PRIORITY
    gpio_dma_irq_priority: int = constants.GPIO_DMA_IRQ_PRIORITY
    adc_pairs_per_buffer: int = constants.ADC_PAIRS_PER_BUFFER
    adc_dma_ring_bytes: int = constants.ADC_DMA_RING_BYTES
    packet_buffer_count: int = constants.PACKET_BUFFER_COUNT
    packet_primary_count: int = constants.PACKET_PRIMARY_COUNT
    packet_reserve_count: int = constants.PACKET_RESERVE_COUNT
    packet_ready_queue_capacity: int = constants.PACKET_READY_QUEUE_CAPACITY
    packet_transmit_queue_capacity: int = constants.PACKET_TRANSMIT_QUEUE_CAPACITY
    command_queue_capacity: int = constants.COMMAND_QUEUE_CAPACITY
    response_queue_capacity: int = constants.RESPONSE_QUEUE_CAPACITY
    nominal_payload_bytes_per_second_per_stream: int = (
        constants.NOMINAL_PAYLOAD_BYTES_PER_SECOND_PER_STREAM
    )
    nominal_framed_bytes_per_second_per_stream: int = (
        constants.NOMINAL_FRAMED_BYTES_PER_SECOND_PER_STREAM
    )

    def __post_init__(self) -> None:
        if isinstance(self.supported_stream_mask, bool) or isinstance(
            self.capability_bits, bool
        ):
            raise TypeError("capabilities contain an unknown enum value")
        try:
            stream_mask = constants.StreamMask(self.supported_stream_mask)
            capability_bits = constants.Capability(self.capability_bits)
            configuration_mask = constants.ConfigurationProfile(
                self.supported_configuration_mask
            )
        except (TypeError, ValueError) as exc:
            raise ValueError("capabilities contain an unknown enum value") from exc
        object.__setattr__(self, "supported_stream_mask", stream_mask)
        object.__setattr__(self, "capability_bits", capability_bits)
        object.__setattr__(self, "supported_configuration_mask", configuration_mask)
        try:
            diagnostic_mode = constants.GpioCaptureDiagnosticMode(
                self.gpio_capture_diagnostic_mode
            )
            diagnostic_flags = constants.GpioCaptureDiagnosticFlag(
                self.gpio_capture_diagnostic_flags
            )
        except (TypeError, ValueError) as exc:
            raise ValueError(
                "GPIO diagnostic metadata contains an unknown enum"
            ) from exc
        if int(diagnostic_flags) & ~constants.KNOWN_GPIO_CAPTURE_DIAGNOSTIC_FLAG_MASK:
            raise ValueError("GPIO diagnostic metadata contains reserved flags")
        object.__setattr__(self, "gpio_capture_diagnostic_mode", diagnostic_mode)
        object.__setattr__(self, "gpio_capture_diagnostic_flags", diagnostic_flags)
        gpio_pin_map = tuple(self.gpio_pin_map)
        object.__setattr__(self, "gpio_pin_map", gpio_pin_map)
        adc_edma_channels = tuple(self.adc_edma_channels)
        adc_edma_priorities = tuple(self.adc_edma_priorities)
        adc_dmamux_sources = tuple(self.adc_dmamux_sources)
        object.__setattr__(self, "adc_edma_channels", adc_edma_channels)
        object.__setattr__(self, "adc_edma_priorities", adc_edma_priorities)
        object.__setattr__(self, "adc_dmamux_sources", adc_dmamux_sources)
        _normalize_adc_metadata(self)

        valid_streams = int(constants.StreamMask.ADC | constants.StreamMask.GPIO)
        if int(stream_mask) & ~valid_streams:
            raise ValueError("supported stream mask contains unknown bits")
        _unsigned("supported_source_mask", self.supported_source_mask, 8)
        if self.supported_source_mask == 0 or self.supported_source_mask & ~0x03:
            raise ValueError("supported source mask contains unknown bits")
        _unsigned("supported_checksum_mask", self.supported_checksum_mask, 32)
        if self.supported_checksum_mask != constants.SUPPORTED_CHECKSUM_MASK:
            raise ValueError("supported checksum mask is incompatible with protocol v1")
        if int(capability_bits) & ~constants.KNOWN_CAPABILITY_MASK:
            raise ValueError("capability mask contains reserved protocol-v1 bits")
        if int(configuration_mask) & ~constants.KNOWN_CONFIGURATION_PROFILE_MASK:
            raise ValueError("configuration profile mask contains reserved bits")
        if bool(stream_mask) != bool(configuration_mask):
            raise ValueError(
                "configuration profile mask disagrees with supported streams"
            )
        profile_contracts = (
            (
                constants.ConfigurationProfile.HARDWARE_ADC,
                constants.Source.HARDWARE,
                constants.StreamMask.ADC,
            ),
            (
                constants.ConfigurationProfile.HARDWARE_GPIO,
                constants.Source.HARDWARE,
                constants.StreamMask.GPIO,
            ),
            (
                constants.ConfigurationProfile.HARDWARE_COMBINED,
                constants.Source.HARDWARE,
                constants.StreamMask.ADC | constants.StreamMask.GPIO,
            ),
            (
                constants.ConfigurationProfile.SYNTHETIC_ADC,
                constants.Source.SYNTHETIC,
                constants.StreamMask.ADC,
            ),
            (
                constants.ConfigurationProfile.SYNTHETIC_GPIO,
                constants.Source.SYNTHETIC,
                constants.StreamMask.GPIO,
            ),
            (
                constants.ConfigurationProfile.SYNTHETIC_COMBINED,
                constants.Source.SYNTHETIC,
                constants.StreamMask.ADC | constants.StreamMask.GPIO,
            ),
        )
        for profile, source, streams in profile_contracts:
            if configuration_mask & profile and (
                not self.supported_source_mask & (1 << int(source))
                or streams & ~stream_mask
            ):
                raise ValueError(
                    "configuration profile mask disagrees with stream/source masks"
                )

        stream_capabilities = constants.Capability.NONE
        if stream_mask & constants.StreamMask.ADC:
            stream_capabilities |= constants.Capability.ADC_STREAM
        if stream_mask & constants.StreamMask.GPIO:
            stream_capabilities |= constants.Capability.GPIO_STREAM
        source_capabilities = constants.Capability.NONE
        if self.supported_source_mask & (1 << int(constants.Source.HARDWARE)):
            source_capabilities |= constants.Capability.HARDWARE_SOURCE
        if self.supported_source_mask & (1 << int(constants.Source.SYNTHETIC)):
            source_capabilities |= constants.Capability.SYNTHETIC_SOURCE
        identity_capabilities = (
            constants.Capability.ADC_STREAM
            | constants.Capability.GPIO_STREAM
            | constants.Capability.HARDWARE_SOURCE
            | constants.Capability.SYNTHETIC_SOURCE
        )
        if capability_bits & identity_capabilities != (
            stream_capabilities | source_capabilities
        ):
            raise ValueError("capabilities disagree with stream/source masks")
        diagnostic_advertised = bool(
            capability_bits & constants.Capability.GPIO_CAPTURE_DIAGNOSTIC
        )
        diagnostic_available = bool(
            diagnostic_flags & constants.GpioCaptureDiagnosticFlag.AVAILABLE
        )
        if diagnostic_advertised != diagnostic_available:
            raise ValueError(
                "GPIO capture diagnostic metadata disagrees with capability bits"
            )

        fixed_values = (
            (self.protocol_version, constants.PROTOCOL_VERSION),
            (self.timestamp_hz, constants.TIMESTAMP_HZ),
            (self.data_frame_bytes, constants.DATA_FRAME_BYTES),
            (self.max_control_frame_bytes, constants.MAX_CONTROL_FRAME_BYTES),
            (self.adc_pair_rate_hz, constants.ADC_PAIR_RATE_HZ),
            (self.gpio_sample_rate_hz, constants.GPIO_SAMPLE_RATE_HZ),
            (self.adc_pair_period_ticks, constants.ADC_PAIR_PERIOD_TICKS),
            (self.adc1_phase_ticks, constants.ADC1_PHASE_TICKS),
            (self.gpio_sample_period_ticks, constants.GPIO_SAMPLE_PERIOD_TICKS),
            (self.gpio_packed_width_bits, constants.GPIO_PACKED_WIDTH_BITS),
            (self.gpio_raw_ring_depth, constants.GPIO_RAW_RING_DEPTH),
            (self.gpio_packed_ring_depth, constants.GPIO_PACKED_RING_DEPTH),
            (
                self.gpio_raw_samples_per_buffer,
                constants.GPIO_RAW_SAMPLES_PER_BUFFER,
            ),
            (self.gpio_raw_ring_bytes, constants.GPIO_RAW_RING_BYTES),
            (self.gpio_packed_ring_bytes, constants.GPIO_PACKED_RING_BYTES),
            (self.gpio_packet_buffer_count, constants.GPIO_PACKET_BUFFER_COUNT),
            (self.gpio_pit_channel, constants.GPIO_PIT_CHANNEL),
            (self.gpio_xbar_input, constants.GPIO_XBAR_INPUT),
            (self.gpio_xbar_output, constants.GPIO_XBAR_OUTPUT),
            (self.gpio_edma_channel, constants.GPIO_EDMA_CHANNEL),
            (self.gpio_dmamux_source, constants.GPIO_DMAMUX_SOURCE),
            (self.gpio_edma_priority, constants.GPIO_EDMA_PRIORITY),
            (self.gpio_xbar_active_edge, constants.GPIO_XBAR_ACTIVE_EDGE),
            (self.data_payload_bytes, constants.DATA_PAYLOAD_BYTES),
            (self.adc_pairs_per_frame, constants.ADC_PAIRS_PER_FRAME),
            (self.gpio_samples_per_frame, constants.GPIO_SAMPLES_PER_FRAME),
            (self.frame_coverage_ticks, constants.FRAME_COVERAGE_TICKS),
            (self.adc_dma_ring_depth, constants.ADC_DMA_RING_DEPTH),
            (self.adc_pair_bytes, constants.ADC_PAIR_BYTES),
            (self.adc_dma_irq_priority, constants.ADC_DMA_IRQ_PRIORITY),
            (self.gpio_dma_irq_priority, constants.GPIO_DMA_IRQ_PRIORITY),
            (self.adc_pairs_per_buffer, constants.ADC_PAIRS_PER_BUFFER),
            (self.adc_dma_ring_bytes, constants.ADC_DMA_RING_BYTES),
            (self.packet_buffer_count, constants.PACKET_BUFFER_COUNT),
            (self.packet_primary_count, constants.PACKET_PRIMARY_COUNT),
            (self.packet_reserve_count, constants.PACKET_RESERVE_COUNT),
            (
                self.packet_ready_queue_capacity,
                constants.PACKET_READY_QUEUE_CAPACITY,
            ),
            (
                self.packet_transmit_queue_capacity,
                constants.PACKET_TRANSMIT_QUEUE_CAPACITY,
            ),
            (self.command_queue_capacity, constants.COMMAND_QUEUE_CAPACITY),
            (self.response_queue_capacity, constants.RESPONSE_QUEUE_CAPACITY),
            (
                self.nominal_payload_bytes_per_second_per_stream,
                constants.NOMINAL_PAYLOAD_BYTES_PER_SECOND_PER_STREAM,
            ),
            (
                self.nominal_framed_bytes_per_second_per_stream,
                constants.NOMINAL_FRAMED_BYTES_PER_SECOND_PER_STREAM,
            ),
        )
        if any(
            not isinstance(actual, int)
            or isinstance(actual, bool)
            or actual != expected
            for actual, expected in fixed_values
        ):
            raise ValueError("INFO capabilities are incompatible with protocol v1")
        if gpio_pin_map != constants.GPIO_PINS_BY_BIT:
            raise ValueError("GPIO bit order must remain D6 through D13")
        if (
            adc_edma_channels != constants.ADC_EDMA_CHANNELS
            or adc_edma_priorities != constants.ADC_EDMA_PRIORITIES
            or adc_dmamux_sources != constants.ADC_DMAMUX_SOURCES
        ):
            raise ValueError("ADC DMA route metadata is incompatible with protocol v1")

    @property
    def adc_calibration(self) -> AdcCalibrationMetadata:
        """Return the bounded per-converter calibration evidence."""

        return AdcCalibrationMetadata.from_device_metadata(self)

    def adc_block_metadata(
        self,
        source: constants.Source | int,
        *,
        acquisition: AdcAcquisitionStatus | None = None,
    ) -> AdcBlockMetadata:
        """Create the immutable ADC metadata attached to decoded blocks."""

        return AdcBlockMetadata.from_device_metadata(
            self,
            source=source,
            acquisition=acquisition,
        )

    def supports_source(self, source: constants.Source | int) -> bool:
        """Return whether this device advertises ``source``."""

        try:
            selected = constants.Source(source)
        except (TypeError, ValueError) as exc:
            raise ValueError("source is not a protocol-v1 source") from exc
        return bool(self.supported_source_mask & (1 << int(selected)))

    def supports_checksum(self, algorithm: constants.ChecksumAlgorithm | int) -> bool:
        """Return whether this device advertises ``algorithm``."""

        try:
            selected = constants.ChecksumAlgorithm(algorithm)
        except (TypeError, ValueError) as exc:
            raise ValueError("checksum is not a protocol-v1 algorithm") from exc
        return bool(self.supported_checksum_mask & (1 << int(selected)))

    def supports_configuration(self, configuration: DAQConfiguration) -> bool:
        """Return whether the exact source/stream profile is advertised."""

        if not isinstance(configuration, DAQConfiguration):
            raise TypeError("configuration must be a DAQConfiguration")
        if configuration.is_control_only:
            return (
                self.supported_stream_mask is constants.StreamMask.NONE
                and self.supports_source(constants.Source.HARDWARE)
            )
        return bool(self.supported_configuration_mask & configuration.profile)

    @property
    def supported_checksum_algorithms(
        self,
    ) -> tuple[constants.ChecksumAlgorithm, ...]:
        """Return advertised checksum IDs in stable numeric order."""

        return tuple(
            algorithm
            for algorithm in sorted(constants.SUPPORTED_CHECKSUM_ALGORITHMS, key=int)
            if self.supports_checksum(algorithm)
        )

    def supports(self, capability: constants.Capability | int) -> bool:
        """Return whether every requested capability bit is advertised."""

        try:
            selected = constants.Capability(capability)
        except (TypeError, ValueError) as exc:
            raise ValueError("capability contains an unknown bit") from exc
        if int(selected) & ~constants.KNOWN_CAPABILITY_MASK:
            raise ValueError("capability contains a reserved protocol-v1 bit")
        return self.capability_bits & selected == selected


@dataclass(frozen=True, slots=True)
class DeviceInfo:
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
    supported_configuration_mask: constants.ConfigurationProfile = (
        _ALL_CONFIGURATION_PROFILES
    )
    applied_stream_mask: constants.StreamMask = constants.StreamMask.NONE
    applied_source: constants.Source = constants.Source.HARDWARE
    data_checksum_algorithm: constants.ChecksumAlgorithm = (
        constants.DEFAULT_CHECKSUM_ALGORITHM
    )
    capability_bits: constants.Capability = (
        constants.Capability.ADC_STREAM
        | constants.Capability.GPIO_STREAM
        | constants.Capability.HARDWARE_SOURCE
        | constants.Capability.SYNTHETIC_SOURCE
    )
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
    adc_code_min: int = constants.ADC_CODE_MIN
    adc_code_max: int = (1 << constants.ADC_PRIMARY_RESOLUTION_BITS) - 1
    adc_reference: constants.AdcReference = (
        constants.AdcReference.VREFH_VREFL_NOMINAL_3V3
    )
    adc_clock_source: constants.AdcClockSource = (
        constants.AdcClockSource.SYNCHRONOUS_IPG
    )
    adc_clock_divider: int = constants.ADC_CLOCK_DIVIDER
    adc_hardware_average_count: int = constants.ADC_HARDWARE_AVERAGE_COUNT
    adc_reference_mv_nominal: int = constants.ADC_REFERENCE_MV_NOMINAL
    adc_input_min_mv_nominal: int = constants.ADC_INPUT_MIN_MV_NOMINAL
    adc_input_max_mv_nominal: int = constants.ADC_INPUT_MAX_MV_NOMINAL
    adc_sample_time_adck: int = constants.ADC_SAMPLE_TIME_ADCK
    adc_conversion_mode: int = 2
    adc_configuration_flags: constants.AdcConfigurationFlag = (
        _DEFAULT_ADC_CONFIGURATION_FLAGS
    )
    adc_calibration_states: tuple[
        constants.AdcCalibrationState, constants.AdcCalibrationState
    ] = (
        constants.AdcCalibrationState.NOT_RUN,
        constants.AdcCalibrationState.NOT_RUN,
    )
    adc_pins: tuple[int, int] = constants.ADC_PINS
    adc_peripherals: tuple[int, int] = constants.ADC_PERIPHERALS
    adc_channels: tuple[int, int] = constants.ADC_CHANNELS
    adc_ipg_clock_hz: int = constants.ADC_IPG_CLOCK_HZ
    adc_clock_hz: int = constants.ADC_CLOCK_HZ
    adc_calibration_deadline_us: int = constants.ADC_CALIBRATION_DEADLINE_US
    adc_calibration_cycles: tuple[int, int] = (0, 0)
    adc_initialization_error_flags: constants.AdcInitializationError = (
        constants.AdcInitializationError.NONE
    )
    adc_trigger: AdcTriggerMetadata = AdcTriggerMetadata()
    gpio_pin_map: tuple[int, ...] = constants.GPIO_PINS_BY_BIT
    gpio_packed_width_bits: int = constants.GPIO_PACKED_WIDTH_BITS
    gpio_raw_ring_depth: int = constants.GPIO_RAW_RING_DEPTH
    gpio_packed_ring_depth: int = constants.GPIO_PACKED_RING_DEPTH
    gpio_capture_diagnostic_mode: constants.GpioCaptureDiagnosticMode = (
        constants.GpioCaptureDiagnosticMode.NON_DRIVING_CAPTURE
    )
    gpio_capture_diagnostic_flags: constants.GpioCaptureDiagnosticFlag = (
        constants.GpioCaptureDiagnosticFlag.NONE
    )
    gpio_raw_samples_per_buffer: int = constants.GPIO_RAW_SAMPLES_PER_BUFFER
    gpio_raw_ring_bytes: int = constants.GPIO_RAW_RING_BYTES
    gpio_packed_ring_bytes: int = constants.GPIO_PACKED_RING_BYTES
    gpio_packet_buffer_count: int = constants.GPIO_PACKET_BUFFER_COUNT
    gpio_pit_channel: int = constants.GPIO_PIT_CHANNEL
    gpio_xbar_input: int = constants.GPIO_XBAR_INPUT
    gpio_xbar_output: int = constants.GPIO_XBAR_OUTPUT
    gpio_edma_channel: int = constants.GPIO_EDMA_CHANNEL
    gpio_dmamux_source: int = constants.GPIO_DMAMUX_SOURCE
    gpio_edma_priority: int = constants.GPIO_EDMA_PRIORITY
    gpio_xbar_active_edge: int = constants.GPIO_XBAR_ACTIVE_EDGE
    data_payload_bytes: int = constants.DATA_PAYLOAD_BYTES
    adc_pairs_per_frame: int = constants.ADC_PAIRS_PER_FRAME
    gpio_samples_per_frame: int = constants.GPIO_SAMPLES_PER_FRAME
    frame_coverage_ticks: int = constants.FRAME_COVERAGE_TICKS
    adc_dma_ring_depth: int = constants.ADC_DMA_RING_DEPTH
    adc_pair_bytes: int = constants.ADC_PAIR_BYTES
    adc_edma_channels: tuple[int, int] = constants.ADC_EDMA_CHANNELS
    adc_edma_priorities: tuple[int, int] = constants.ADC_EDMA_PRIORITIES
    adc_dmamux_sources: tuple[int, int] = constants.ADC_DMAMUX_SOURCES
    adc_dma_irq_priority: int = constants.ADC_DMA_IRQ_PRIORITY
    gpio_dma_irq_priority: int = constants.GPIO_DMA_IRQ_PRIORITY
    adc_pairs_per_buffer: int = constants.ADC_PAIRS_PER_BUFFER
    adc_dma_ring_bytes: int = constants.ADC_DMA_RING_BYTES
    packet_buffer_count: int = constants.PACKET_BUFFER_COUNT
    packet_primary_count: int = constants.PACKET_PRIMARY_COUNT
    packet_reserve_count: int = constants.PACKET_RESERVE_COUNT
    packet_ready_queue_capacity: int = constants.PACKET_READY_QUEUE_CAPACITY
    packet_transmit_queue_capacity: int = constants.PACKET_TRANSMIT_QUEUE_CAPACITY
    command_queue_capacity: int = constants.COMMAND_QUEUE_CAPACITY
    response_queue_capacity: int = constants.RESPONSE_QUEUE_CAPACITY
    nominal_payload_bytes_per_second_per_stream: int = (
        constants.NOMINAL_PAYLOAD_BYTES_PER_SECOND_PER_STREAM
    )
    nominal_framed_bytes_per_second_per_stream: int = (
        constants.NOMINAL_FRAMED_BYTES_PER_SECOND_PER_STREAM
    )

    def __post_init__(self) -> None:
        if not isinstance(self.device_state, constants.DeviceState):
            raise TypeError("device_state must be a DeviceState")
        if not isinstance(self.board_id, constants.BoardId):
            raise TypeError("board_id must be a BoardId")
        if not isinstance(self.mcu_id, constants.McuId):
            raise TypeError("mcu_id must be an McuId")
        _unsigned("hardware_serial", self.hardware_serial, 32)
        firmware_version = tuple(self.firmware_version)
        object.__setattr__(self, "firmware_version", firmware_version)
        if len(firmware_version) != 3:
            raise ValueError("firmware_version must contain major, minor, and patch")
        for part in firmware_version:
            _unsigned("firmware version component", part, 8)
        if not isinstance(self.build_id, str):
            raise TypeError("build_id must be a string")
        try:
            encoded_build = self.build_id.encode("ascii")
        except UnicodeEncodeError as exc:
            raise ValueError("build_id must contain only ASCII") from exc
        if b"\0" in encoded_build or len(encoded_build) >= (
            constants.INFO_RESPONSE_BUILD_ID_COUNT
        ):
            raise ValueError("build_id must fit 31 ASCII bytes without embedded NUL")
        _normalize_adc_metadata(self)
        # Constructing the nested view validates and normalizes every
        # capability/layout field at this outer model boundary too.
        capabilities = self.capabilities
        if isinstance(self.data_checksum_algorithm, bool):
            raise TypeError("INFO checksum algorithm is not supported by this host")
        try:
            data_checksum = constants.ChecksumAlgorithm(self.data_checksum_algorithm)
        except (TypeError, ValueError) as exc:
            raise ValueError("INFO checksum algorithm is unknown") from exc
        if data_checksum not in HOST_SUPPORTED_CHECKSUM_ALGORITHMS:
            raise ValueError(
                "host has no implementation for checksum algorithm "
                f"{data_checksum.name}"
            )
        if not capabilities.supports_checksum(data_checksum):
            raise ValueError("INFO selected checksum is not advertised")
        object.__setattr__(self, "data_checksum_algorithm", data_checksum)
        object.__setattr__(
            self,
            "supported_stream_mask",
            capabilities.supported_stream_mask,
        )
        object.__setattr__(self, "capability_bits", capabilities.capability_bits)
        object.__setattr__(self, "gpio_pin_map", capabilities.gpio_pin_map)
        object.__setattr__(
            self,
            "gpio_capture_diagnostic_mode",
            capabilities.gpio_capture_diagnostic_mode,
        )
        object.__setattr__(
            self,
            "gpio_capture_diagnostic_flags",
            capabilities.gpio_capture_diagnostic_flags,
        )
        object.__setattr__(
            self,
            "supported_configuration_mask",
            capabilities.supported_configuration_mask,
        )
        if isinstance(self.applied_stream_mask, bool) or isinstance(
            self.applied_source, bool
        ):
            raise TypeError("INFO applied configuration contains an unknown enum")
        try:
            applied_streams = constants.StreamMask(self.applied_stream_mask)
            applied_source = constants.Source(self.applied_source)
        except (TypeError, ValueError) as exc:
            raise ValueError(
                "INFO applied configuration contains an unknown enum"
            ) from exc
        object.__setattr__(self, "applied_stream_mask", applied_streams)
        object.__setattr__(self, "applied_source", applied_source)
        if not capabilities.supports_source(applied_source):
            raise ValueError("INFO applied source is not advertised")
        if self.device_state is constants.DeviceState.IDLE:
            if applied_streams:
                raise ValueError("IDLE INFO requires an empty applied stream mask")
        elif applied_streams:
            applied = DAQConfiguration(
                stream_mask=applied_streams,
                source=applied_source,
                data_checksum_algorithm=data_checksum,
            )
            if not capabilities.supports_configuration(applied):
                raise ValueError("INFO applied configuration is not advertised")
        elif not (
            capabilities.supported_stream_mask is constants.StreamMask.NONE
            and applied_source is constants.Source.HARDWARE
        ):
            raise ValueError(
                "zero-stream CONFIGURED/RUNNING INFO requires a control-only device"
            )

    @property
    def capabilities(self) -> DeviceCapabilities:
        """Return the typed capability subset of this INFO response."""

        return DeviceCapabilities(
            supported_stream_mask=self.supported_stream_mask,
            supported_source_mask=self.supported_source_mask,
            supported_checksum_mask=self.supported_checksum_mask,
            capability_bits=self.capability_bits,
            supported_configuration_mask=self.supported_configuration_mask,
            protocol_version=self.protocol_version,
            timestamp_hz=self.timestamp_hz,
            data_frame_bytes=self.data_frame_bytes,
            max_control_frame_bytes=self.max_control_frame_bytes,
            adc_pair_rate_hz=self.adc_pair_rate_hz,
            gpio_sample_rate_hz=self.gpio_sample_rate_hz,
            adc_pair_period_ticks=self.adc_pair_period_ticks,
            adc1_phase_ticks=self.adc1_phase_ticks,
            gpio_sample_period_ticks=self.gpio_sample_period_ticks,
            adc_resolution_bits=self.adc_resolution_bits,
            adc_container_bytes=self.adc_container_bytes,
            adc_code_min=self.adc_code_min,
            adc_code_max=self.adc_code_max,
            adc_reference=self.adc_reference,
            adc_clock_source=self.adc_clock_source,
            adc_clock_divider=self.adc_clock_divider,
            adc_hardware_average_count=self.adc_hardware_average_count,
            adc_reference_mv_nominal=self.adc_reference_mv_nominal,
            adc_input_min_mv_nominal=self.adc_input_min_mv_nominal,
            adc_input_max_mv_nominal=self.adc_input_max_mv_nominal,
            adc_sample_time_adck=self.adc_sample_time_adck,
            adc_conversion_mode=self.adc_conversion_mode,
            adc_configuration_flags=self.adc_configuration_flags,
            adc_calibration_states=self.adc_calibration_states,
            adc_pins=self.adc_pins,
            adc_peripherals=self.adc_peripherals,
            adc_channels=self.adc_channels,
            adc_ipg_clock_hz=self.adc_ipg_clock_hz,
            adc_clock_hz=self.adc_clock_hz,
            adc_calibration_deadline_us=self.adc_calibration_deadline_us,
            adc_calibration_cycles=self.adc_calibration_cycles,
            adc_initialization_error_flags=(self.adc_initialization_error_flags),
            adc_trigger=self.adc_trigger,
            gpio_pin_map=self.gpio_pin_map,
            gpio_packed_width_bits=self.gpio_packed_width_bits,
            gpio_raw_ring_depth=self.gpio_raw_ring_depth,
            gpio_packed_ring_depth=self.gpio_packed_ring_depth,
            gpio_capture_diagnostic_mode=self.gpio_capture_diagnostic_mode,
            gpio_capture_diagnostic_flags=self.gpio_capture_diagnostic_flags,
            gpio_raw_samples_per_buffer=self.gpio_raw_samples_per_buffer,
            gpio_raw_ring_bytes=self.gpio_raw_ring_bytes,
            gpio_packed_ring_bytes=self.gpio_packed_ring_bytes,
            gpio_packet_buffer_count=self.gpio_packet_buffer_count,
            gpio_pit_channel=self.gpio_pit_channel,
            gpio_xbar_input=self.gpio_xbar_input,
            gpio_xbar_output=self.gpio_xbar_output,
            gpio_edma_channel=self.gpio_edma_channel,
            gpio_dmamux_source=self.gpio_dmamux_source,
            gpio_edma_priority=self.gpio_edma_priority,
            gpio_xbar_active_edge=self.gpio_xbar_active_edge,
            data_payload_bytes=self.data_payload_bytes,
            adc_pairs_per_frame=self.adc_pairs_per_frame,
            gpio_samples_per_frame=self.gpio_samples_per_frame,
            frame_coverage_ticks=self.frame_coverage_ticks,
            adc_dma_ring_depth=self.adc_dma_ring_depth,
            adc_pair_bytes=self.adc_pair_bytes,
            adc_edma_channels=self.adc_edma_channels,
            adc_edma_priorities=self.adc_edma_priorities,
            adc_dmamux_sources=self.adc_dmamux_sources,
            adc_dma_irq_priority=self.adc_dma_irq_priority,
            gpio_dma_irq_priority=self.gpio_dma_irq_priority,
            adc_pairs_per_buffer=self.adc_pairs_per_buffer,
            adc_dma_ring_bytes=self.adc_dma_ring_bytes,
            packet_buffer_count=self.packet_buffer_count,
            packet_primary_count=self.packet_primary_count,
            packet_reserve_count=self.packet_reserve_count,
            packet_ready_queue_capacity=self.packet_ready_queue_capacity,
            packet_transmit_queue_capacity=self.packet_transmit_queue_capacity,
            command_queue_capacity=self.command_queue_capacity,
            response_queue_capacity=self.response_queue_capacity,
            nominal_payload_bytes_per_second_per_stream=(
                self.nominal_payload_bytes_per_second_per_stream
            ),
            nominal_framed_bytes_per_second_per_stream=(
                self.nominal_framed_bytes_per_second_per_stream
            ),
        )

    @property
    def applied_configuration(self) -> DAQConfiguration | None:
        """Return the exact applied profile, or ``None`` while IDLE."""

        if self.device_state is constants.DeviceState.IDLE:
            return None
        return DAQConfiguration(
            stream_mask=self.applied_stream_mask,
            source=self.applied_source,
            data_checksum_algorithm=self.data_checksum_algorithm,
        )

    @property
    def adc_calibration(self) -> AdcCalibrationMetadata:
        """Return the bounded per-converter calibration evidence."""

        return AdcCalibrationMetadata.from_device_metadata(self)

    def adc_block_metadata(
        self,
        source: constants.Source | int,
        *,
        acquisition: AdcAcquisitionStatus | None = None,
    ) -> AdcBlockMetadata:
        """Create the immutable ADC metadata attached to decoded blocks."""

        return AdcBlockMetadata.from_device_metadata(
            self,
            source=source,
            acquisition=acquisition,
        )

    def supports_source(self, source: constants.Source | int) -> bool:
        """Return whether INFO advertises the requested source ID."""

        return self.capabilities.supports_source(source)

    def supports_checksum(self, algorithm: constants.ChecksumAlgorithm | int) -> bool:
        """Return whether INFO advertises the requested checksum ID."""

        return self.capabilities.supports_checksum(algorithm)

    def supports_capability(self, capability: constants.Capability | int) -> bool:
        """Return whether INFO advertises every bit in ``capability``."""

        return self.capabilities.supports(capability)

    def to_payload(self) -> bytes:
        """Encode a successful INFO response with actual ADC settings."""

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
            "<IIIIII",
            payload,
            constants.INFO_RESPONSE_SUPPORTED_CHECKSUM_MASK_OFFSET,
            self.supported_checksum_mask,
            int(self.capability_bits),
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
        payload[constants.INFO_RESPONSE_DATA_CHECKSUM_ALGORITHM_OFFSET] = int(
            self.data_checksum_algorithm
        )
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
        payload[constants.INFO_RESPONSE_GPIO_PACKED_WIDTH_BITS_OFFSET] = (
            self.gpio_packed_width_bits
        )
        payload[constants.INFO_RESPONSE_GPIO_RAW_RING_DEPTH_OFFSET] = (
            self.gpio_raw_ring_depth
        )
        payload[constants.INFO_RESPONSE_GPIO_PACKED_RING_DEPTH_OFFSET] = (
            self.gpio_packed_ring_depth
        )
        payload[constants.INFO_RESPONSE_GPIO_CAPTURE_DIAGNOSTIC_MODE_OFFSET] = int(
            self.gpio_capture_diagnostic_mode
        )
        struct.pack_into(
            "<HIIIH",
            payload,
            constants.INFO_RESPONSE_GPIO_CAPTURE_DIAGNOSTIC_FLAGS_OFFSET,
            int(self.gpio_capture_diagnostic_flags),
            self.gpio_raw_samples_per_buffer,
            self.gpio_raw_ring_bytes,
            self.gpio_packed_ring_bytes,
            self.gpio_packet_buffer_count,
        )
        resource_start = constants.INFO_RESPONSE_GPIO_PIT_CHANNEL_OFFSET
        payload[resource_start : resource_start + 7] = bytes(
            (
                self.gpio_pit_channel,
                self.gpio_xbar_input,
                self.gpio_xbar_output,
                self.gpio_edma_channel,
                self.gpio_dmamux_source,
                self.gpio_edma_priority,
                self.gpio_xbar_active_edge,
            )
        )
        _pack_adc_metadata(payload, self, "INFO_RESPONSE")
        payload[constants.INFO_RESPONSE_APPLIED_STREAM_MASK_OFFSET] = int(
            self.applied_stream_mask
        )
        payload[constants.INFO_RESPONSE_APPLIED_SOURCE_OFFSET] = int(
            self.applied_source
        )
        struct.pack_into(
            "<HHHHHI",
            payload,
            constants.INFO_RESPONSE_SUPPORTED_CONFIGURATION_MASK_OFFSET,
            int(self.supported_configuration_mask),
            self.data_payload_bytes,
            self.adc_pairs_per_frame,
            self.gpio_samples_per_frame,
            0,
            self.frame_coverage_ticks,
        )
        payload[constants.INFO_RESPONSE_ADC_DMA_RING_DEPTH_OFFSET] = (
            self.adc_dma_ring_depth
        )
        payload[constants.INFO_RESPONSE_ADC_PAIR_BYTES_OFFSET] = self.adc_pair_bytes
        for offset, values in (
            (constants.INFO_RESPONSE_ADC_EDMA_CHANNELS_OFFSET, self.adc_edma_channels),
            (
                constants.INFO_RESPONSE_ADC_EDMA_PRIORITIES_OFFSET,
                self.adc_edma_priorities,
            ),
            (
                constants.INFO_RESPONSE_ADC_DMAMUX_SOURCES_OFFSET,
                self.adc_dmamux_sources,
            ),
        ):
            payload[offset : offset + 2] = bytes(values)
        payload[constants.INFO_RESPONSE_ADC_DMA_IRQ_PRIORITY_OFFSET] = (
            self.adc_dma_irq_priority
        )
        payload[constants.INFO_RESPONSE_GPIO_DMA_IRQ_PRIORITY_OFFSET] = (
            self.gpio_dma_irq_priority
        )
        struct.pack_into(
            "<HIHHHHHBBII",
            payload,
            constants.INFO_RESPONSE_ADC_PAIRS_PER_BUFFER_OFFSET,
            self.adc_pairs_per_buffer,
            self.adc_dma_ring_bytes,
            self.packet_buffer_count,
            self.packet_primary_count,
            self.packet_reserve_count,
            self.packet_ready_queue_capacity,
            self.packet_transmit_queue_capacity,
            self.command_queue_capacity,
            self.response_queue_capacity,
            self.nominal_payload_bytes_per_second_per_stream,
            self.nominal_framed_bytes_per_second_per_stream,
        )
        return bytes(payload)

    @classmethod
    def from_payload(cls, payload: bytes | bytearray | memoryview) -> DeviceInfo:
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
            data_checksum_algorithm=constants.ChecksumAlgorithm(
                payload_bytes[constants.INFO_RESPONSE_DATA_CHECKSUM_ALGORITHM_OFFSET]
            ),
            capability_bits=constants.Capability(
                struct.unpack_from(
                    "<I",
                    payload_bytes,
                    constants.INFO_RESPONSE_CAPABILITY_BITS_OFFSET,
                )[0]
            ),
            applied_stream_mask=constants.StreamMask(
                payload_bytes[constants.INFO_RESPONSE_APPLIED_STREAM_MASK_OFFSET]
            ),
            applied_source=constants.Source(
                payload_bytes[constants.INFO_RESPONSE_APPLIED_SOURCE_OFFSET]
            ),
            supported_configuration_mask=constants.ConfigurationProfile(
                struct.unpack_from(
                    "<H",
                    payload_bytes,
                    constants.INFO_RESPONSE_SUPPORTED_CONFIGURATION_MASK_OFFSET,
                )[0]
            ),
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
            gpio_pin_map=tuple(
                payload_bytes[
                    constants.INFO_RESPONSE_GPIO_PIN_MAP_OFFSET : constants.INFO_RESPONSE_GPIO_PIN_MAP_OFFSET
                    + constants.INFO_RESPONSE_GPIO_PIN_MAP_COUNT
                ]
            ),
            gpio_packed_width_bits=payload_bytes[
                constants.INFO_RESPONSE_GPIO_PACKED_WIDTH_BITS_OFFSET
            ],
            gpio_raw_ring_depth=payload_bytes[
                constants.INFO_RESPONSE_GPIO_RAW_RING_DEPTH_OFFSET
            ],
            gpio_packed_ring_depth=payload_bytes[
                constants.INFO_RESPONSE_GPIO_PACKED_RING_DEPTH_OFFSET
            ],
            gpio_capture_diagnostic_mode=constants.GpioCaptureDiagnosticMode(
                payload_bytes[
                    constants.INFO_RESPONSE_GPIO_CAPTURE_DIAGNOSTIC_MODE_OFFSET
                ]
            ),
            gpio_capture_diagnostic_flags=constants.GpioCaptureDiagnosticFlag(
                struct.unpack_from(
                    "<H",
                    payload_bytes,
                    constants.INFO_RESPONSE_GPIO_CAPTURE_DIAGNOSTIC_FLAGS_OFFSET,
                )[0]
            ),
            gpio_raw_samples_per_buffer=struct.unpack_from(
                "<I",
                payload_bytes,
                constants.INFO_RESPONSE_GPIO_RAW_SAMPLES_PER_BUFFER_OFFSET,
            )[0],
            gpio_raw_ring_bytes=struct.unpack_from(
                "<I", payload_bytes, constants.INFO_RESPONSE_GPIO_RAW_RING_BYTES_OFFSET
            )[0],
            gpio_packed_ring_bytes=struct.unpack_from(
                "<I",
                payload_bytes,
                constants.INFO_RESPONSE_GPIO_PACKED_RING_BYTES_OFFSET,
            )[0],
            gpio_packet_buffer_count=struct.unpack_from(
                "<H",
                payload_bytes,
                constants.INFO_RESPONSE_GPIO_PACKET_BUFFER_COUNT_OFFSET,
            )[0],
            gpio_pit_channel=payload_bytes[
                constants.INFO_RESPONSE_GPIO_PIT_CHANNEL_OFFSET
            ],
            gpio_xbar_input=payload_bytes[
                constants.INFO_RESPONSE_GPIO_XBAR_INPUT_OFFSET
            ],
            gpio_xbar_output=payload_bytes[
                constants.INFO_RESPONSE_GPIO_XBAR_OUTPUT_OFFSET
            ],
            gpio_edma_channel=payload_bytes[
                constants.INFO_RESPONSE_GPIO_EDMA_CHANNEL_OFFSET
            ],
            gpio_dmamux_source=payload_bytes[
                constants.INFO_RESPONSE_GPIO_DMAMUX_SOURCE_OFFSET
            ],
            gpio_edma_priority=payload_bytes[
                constants.INFO_RESPONSE_GPIO_EDMA_PRIORITY_OFFSET
            ],
            gpio_xbar_active_edge=payload_bytes[
                constants.INFO_RESPONSE_GPIO_XBAR_ACTIVE_EDGE_OFFSET
            ],
            data_payload_bytes=struct.unpack_from(
                "<H", payload_bytes, constants.INFO_RESPONSE_DATA_PAYLOAD_BYTES_OFFSET
            )[0],
            adc_pairs_per_frame=struct.unpack_from(
                "<H", payload_bytes, constants.INFO_RESPONSE_ADC_PAIRS_PER_FRAME_OFFSET
            )[0],
            gpio_samples_per_frame=struct.unpack_from(
                "<H",
                payload_bytes,
                constants.INFO_RESPONSE_GPIO_SAMPLES_PER_FRAME_OFFSET,
            )[0],
            frame_coverage_ticks=struct.unpack_from(
                "<I", payload_bytes, constants.INFO_RESPONSE_FRAME_COVERAGE_TICKS_OFFSET
            )[0],
            adc_dma_ring_depth=payload_bytes[
                constants.INFO_RESPONSE_ADC_DMA_RING_DEPTH_OFFSET
            ],
            adc_pair_bytes=payload_bytes[constants.INFO_RESPONSE_ADC_PAIR_BYTES_OFFSET],
            adc_edma_channels=(
                payload_bytes[constants.INFO_RESPONSE_ADC_EDMA_CHANNELS_OFFSET],
                payload_bytes[constants.INFO_RESPONSE_ADC_EDMA_CHANNELS_OFFSET + 1],
            ),
            adc_edma_priorities=(
                payload_bytes[constants.INFO_RESPONSE_ADC_EDMA_PRIORITIES_OFFSET],
                payload_bytes[constants.INFO_RESPONSE_ADC_EDMA_PRIORITIES_OFFSET + 1],
            ),
            adc_dmamux_sources=(
                payload_bytes[constants.INFO_RESPONSE_ADC_DMAMUX_SOURCES_OFFSET],
                payload_bytes[constants.INFO_RESPONSE_ADC_DMAMUX_SOURCES_OFFSET + 1],
            ),
            adc_dma_irq_priority=payload_bytes[
                constants.INFO_RESPONSE_ADC_DMA_IRQ_PRIORITY_OFFSET
            ],
            gpio_dma_irq_priority=payload_bytes[
                constants.INFO_RESPONSE_GPIO_DMA_IRQ_PRIORITY_OFFSET
            ],
            adc_pairs_per_buffer=struct.unpack_from(
                "<H", payload_bytes, constants.INFO_RESPONSE_ADC_PAIRS_PER_BUFFER_OFFSET
            )[0],
            adc_dma_ring_bytes=struct.unpack_from(
                "<I", payload_bytes, constants.INFO_RESPONSE_ADC_DMA_RING_BYTES_OFFSET
            )[0],
            packet_buffer_count=struct.unpack_from(
                "<H", payload_bytes, constants.INFO_RESPONSE_PACKET_BUFFER_COUNT_OFFSET
            )[0],
            packet_primary_count=struct.unpack_from(
                "<H", payload_bytes, constants.INFO_RESPONSE_PACKET_PRIMARY_COUNT_OFFSET
            )[0],
            packet_reserve_count=struct.unpack_from(
                "<H", payload_bytes, constants.INFO_RESPONSE_PACKET_RESERVE_COUNT_OFFSET
            )[0],
            packet_ready_queue_capacity=struct.unpack_from(
                "<H",
                payload_bytes,
                constants.INFO_RESPONSE_PACKET_READY_QUEUE_CAPACITY_OFFSET,
            )[0],
            packet_transmit_queue_capacity=struct.unpack_from(
                "<H",
                payload_bytes,
                constants.INFO_RESPONSE_PACKET_TRANSMIT_QUEUE_CAPACITY_OFFSET,
            )[0],
            command_queue_capacity=payload_bytes[
                constants.INFO_RESPONSE_COMMAND_QUEUE_CAPACITY_OFFSET
            ],
            response_queue_capacity=payload_bytes[
                constants.INFO_RESPONSE_RESPONSE_QUEUE_CAPACITY_OFFSET
            ],
            nominal_payload_bytes_per_second_per_stream=struct.unpack_from(
                "<I",
                payload_bytes,
                constants.INFO_RESPONSE_NOMINAL_PAYLOAD_BYTES_PER_SECOND_PER_STREAM_OFFSET,
            )[0],
            nominal_framed_bytes_per_second_per_stream=struct.unpack_from(
                "<I",
                payload_bytes,
                constants.INFO_RESPONSE_NOMINAL_FRAMED_BYTES_PER_SECOND_PER_STREAM_OFFSET,
            )[0],
            **_unpack_adc_metadata(payload_bytes, "INFO_RESPONSE"),
        )


# ``Info`` remains as the concise Phase 01 spelling.
Info = DeviceInfo


@dataclass(frozen=True, slots=True)
class Status:
    """Device state, active configuration, and statistics-generation counters."""

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
    stats_generation: int = 1
    adc_frames_generated: int = 0
    adc_items_generated: int = 0
    adc_frames_framed_pipeline: int = 0
    adc_items_framed_pipeline: int = 0
    adc_items_emitted: int = 0
    adc_frames_transmitted: int = 0
    adc_items_transmitted_pipeline: int = 0
    adc_frames_dropped: int = 0
    gpio_frames_generated: int = 0
    gpio_items_generated: int = 0
    gpio_frames_framed_pipeline: int = 0
    gpio_items_framed_pipeline: int = 0
    gpio_items_emitted: int = 0
    gpio_frames_transmitted: int = 0
    gpio_items_transmitted_pipeline: int = 0
    gpio_frames_dropped: int = 0
    adc_payload_bytes_produced: int = 0
    adc_payload_bytes_framed: int = 0
    adc_payload_bytes_emitted: int = 0
    adc_payload_bytes_transmitted: int = 0
    adc_payload_bytes_dropped: int = 0
    adc_framed_bytes_framed: int = 0
    adc_framed_bytes_emitted: int = 0
    adc_framed_bytes_transmitted: int = 0
    gpio_payload_bytes_produced: int = 0
    gpio_payload_bytes_framed: int = 0
    gpio_payload_bytes_emitted: int = 0
    gpio_payload_bytes_transmitted: int = 0
    gpio_payload_bytes_dropped: int = 0
    gpio_framed_bytes_framed: int = 0
    gpio_framed_bytes_emitted: int = 0
    gpio_framed_bytes_transmitted: int = 0
    adc_packet_ready_depth: int = 0
    gpio_packet_ready_depth: int = 0
    adc_packet_transmit_depth: int = 0
    gpio_packet_transmit_depth: int = 0
    adc_packet_ready_high_water: int = 0
    gpio_packet_ready_high_water: int = 0
    adc_packet_transmit_high_water: int = 0
    gpio_packet_transmit_high_water: int = 0
    packet_ready_high_water: int = 0
    packet_transmit_high_water: int = 0
    packet_frames_promoted: int = 0
    packet_fairness_deferrals: int = 0
    packet_accounted_frame_skew: int = 0
    data_payload_bytes_transmitted: int = 0
    data_framed_bytes_transmitted: int = 0
    packet_pool_exhaustions: int = 0
    packet_invalid_operations: int = 0
    packet_encoding_rejections: int = 0
    packet_ready_queue_rejections: int = 0
    packet_transmit_queue_rejections: int = 0
    commands_accepted: int = 0
    commands_rejected: int = 0
    bad_checksums: int = 0
    bad_lengths: int = 0
    bad_types: int = 0
    bad_versions: int = 0
    timeouts: int = 0
    partial_usb_writes: int = 0
    state_errors: int = 0
    usb_short_capacity_deferrals: int = 0
    usb_rx_stall_events: int = 0
    usb_tx_stall_events: int = 0
    usb_io_errors: int = 0
    usb_command_queue_depth: int = 0
    usb_response_queue_depth: int = 0
    usb_lower_priority_queue_depth: int = 0
    usb_command_queue_high_water: int = 0
    usb_response_queue_high_water: int = 0
    usb_active_frame_bytes_sent: int = 0
    gpio_samples_captured: int = 0
    gpio_samples_packed: int = 0
    gpio_samples_framed: int = 0
    gpio_samples_transmitted: int = 0
    gpio_raw_samples_lost: int = 0
    gpio_packer_samples_dropped: int = 0
    gpio_raw_ring_overruns: int = 0
    gpio_dma_major_loops: int = 0
    gpio_raw_ready_depth: int = 0
    gpio_raw_ready_high_water: int = 0
    gpio_packed_ready_depth: int = 0
    gpio_packed_ready_high_water: int = 0
    packet_ready_depth: int = 0
    packet_transmit_depth: int = 0
    packet_owned_high_water: int = 0
    gpio_processing_cpu_basis_points: int = 0
    gpio_hardware_errors: int = 0
    gpio_raw_invariant_errors: int = 0
    gpio_packer_source_errors: int = 0
    gpio_packer_pipeline_errors: int = 0
    gpio_packer_chronology_errors: int = 0
    gpio_resource_conflicts: int = 0
    gpio_start_errors: int = 0
    gpio_stop_errors: int = 0
    gpio_stale_dma_completions: int = 0
    adc_resolution_bits: int = constants.ADC_RESOLUTION_BITS
    adc_container_bytes: int = constants.ADC_CONTAINER_BITS // 8
    adc_code_min: int = constants.ADC_CODE_MIN
    adc_code_max: int = (1 << constants.ADC_PRIMARY_RESOLUTION_BITS) - 1
    adc_reference: constants.AdcReference = (
        constants.AdcReference.VREFH_VREFL_NOMINAL_3V3
    )
    adc_clock_source: constants.AdcClockSource = (
        constants.AdcClockSource.SYNCHRONOUS_IPG
    )
    adc_clock_divider: int = constants.ADC_CLOCK_DIVIDER
    adc_hardware_average_count: int = constants.ADC_HARDWARE_AVERAGE_COUNT
    adc_reference_mv_nominal: int = constants.ADC_REFERENCE_MV_NOMINAL
    adc_input_min_mv_nominal: int = constants.ADC_INPUT_MIN_MV_NOMINAL
    adc_input_max_mv_nominal: int = constants.ADC_INPUT_MAX_MV_NOMINAL
    adc_sample_time_adck: int = constants.ADC_SAMPLE_TIME_ADCK
    adc_conversion_mode: int = 2
    adc_configuration_flags: constants.AdcConfigurationFlag = (
        _DEFAULT_ADC_CONFIGURATION_FLAGS
    )
    adc_calibration_states: tuple[
        constants.AdcCalibrationState, constants.AdcCalibrationState
    ] = (
        constants.AdcCalibrationState.NOT_RUN,
        constants.AdcCalibrationState.NOT_RUN,
    )
    adc_pins: tuple[int, int] = constants.ADC_PINS
    adc_peripherals: tuple[int, int] = constants.ADC_PERIPHERALS
    adc_channels: tuple[int, int] = constants.ADC_CHANNELS
    adc_ipg_clock_hz: int = constants.ADC_IPG_CLOCK_HZ
    adc_clock_hz: int = constants.ADC_CLOCK_HZ
    adc_calibration_deadline_us: int = constants.ADC_CALIBRATION_DEADLINE_US
    adc_calibration_cycles: tuple[int, int] = (0, 0)
    adc_initialization_error_flags: constants.AdcInitializationError = (
        constants.AdcInitializationError.NONE
    )
    adc_trigger: AdcTriggerMetadata = AdcTriggerMetadata()
    adc0_dma_major_loops: int = 0
    adc1_dma_major_loops: int = 0
    adc0_dma_results: int = 0
    adc1_dma_results: int = 0
    adc_paired_major_loops: int = 0
    adc_buffers_completed: int = 0
    adc_buffers_acquired: int = 0
    adc_buffers_released: int = 0
    adc_pairs_captured: int = 0
    adc_pairs_delivered: int = 0
    adc_pairs_framed: int = 0
    adc_pairs_transmitted: int = 0
    adc_raw_pairs_lost: int = 0
    adc_stop_pairs_discarded: int = 0
    adc_incomplete_conversions: int = 0
    adc_overwritten_conversions: int = 0
    adc_raw_ring_overruns: int = 0
    adc_incomplete_buffers: int = 0
    adc_raw_ready_depth: int = 0
    adc_raw_ready_high_water: int = 0
    adc_etc_error_events: int = 0
    adc_etc_error_flags: int = 0
    adc_dma_error_events: int = 0
    adc_completion_mismatches: int = 0
    adc_destination_mismatches: int = 0
    adc_schedule_exhaustions: int = 0
    adc_raw_invariant_errors: int = 0
    adc_stale_completions: int = 0
    adc_resource_conflicts: int = 0
    adc_start_errors: int = 0
    adc_stop_errors: int = 0
    adc_stale_interrupts: int = 0
    adc_packer_source_errors: int = 0
    adc_packer_pipeline_errors: int = 0
    adc_packer_chronology_errors: int = 0

    def __post_init__(self) -> None:
        if any(
            isinstance(value, bool)
            for value in (
                self.device_state,
                self.stream_mask,
                self.source,
                self.data_checksum_algorithm,
            )
        ):
            raise ValueError("status contains an unknown enum value")
        try:
            state = constants.DeviceState(self.device_state)
            stream_mask = constants.StreamMask(self.stream_mask)
            source = constants.Source(self.source)
            checksum = constants.ChecksumAlgorithm(self.data_checksum_algorithm)
        except (TypeError, ValueError) as exc:
            raise ValueError("status contains an unknown enum value") from exc
        object.__setattr__(self, "device_state", state)
        object.__setattr__(self, "stream_mask", stream_mask)
        object.__setattr__(self, "source", source)
        object.__setattr__(self, "data_checksum_algorithm", checksum)
        if state is constants.DeviceState.BOOT:
            raise ValueError("BOOT does not produce STATUS responses")
        valid_streams = int(constants.StreamMask.ADC | constants.StreamMask.GPIO)
        if int(stream_mask) & ~valid_streams:
            raise ValueError("status stream mask contains unknown bits")
        if state is constants.DeviceState.IDLE and stream_mask:
            raise ValueError("IDLE status requires an empty stream mask")
        if (
            state is not constants.DeviceState.IDLE
            and not stream_mask
            and source is not constants.Source.HARDWARE
        ):
            raise ValueError(
                "zero-stream CONFIGURED/RUNNING status requires hardware source"
            )
        if checksum not in constants.SUPPORTED_CHECKSUM_ALGORITHMS:
            raise ValueError("status checksum algorithm is not enabled")
        if checksum not in HOST_SUPPORTED_CHECKSUM_ALGORITHMS:
            raise ValueError(
                f"host has no implementation for checksum algorithm {checksum.name}"
            )
        if (
            not isinstance(self.data_frame_bytes, int)
            or isinstance(self.data_frame_bytes, bool)
            or self.data_frame_bytes != constants.DATA_FRAME_BYTES
        ):
            raise ValueError("protocol v1 data frames are exactly 4096 bytes")
        for name in (
            "adc_frames_emitted",
            "gpio_frames_emitted",
            "adc_items_dropped",
            "gpio_items_dropped",
            "gpio_samples_captured",
            "gpio_samples_packed",
            "gpio_samples_framed",
            "gpio_samples_transmitted",
            "gpio_raw_samples_lost",
            "gpio_packer_samples_dropped",
            "gpio_raw_ring_overruns",
            "gpio_dma_major_loops",
        ):
            _unsigned(name, getattr(self, name), 64)
        for name in (
            "parser_errors",
            "transport_errors",
            "gpio_hardware_errors",
            "gpio_raw_invariant_errors",
            "gpio_packer_source_errors",
            "gpio_packer_pipeline_errors",
            "gpio_packer_chronology_errors",
            "gpio_resource_conflicts",
            "gpio_start_errors",
            "gpio_stop_errors",
            "gpio_stale_dma_completions",
        ):
            _unsigned(name, getattr(self, name), 32)
        depth_limits = {
            "gpio_raw_ready_depth": constants.GPIO_RAW_RING_DEPTH,
            "gpio_raw_ready_high_water": constants.GPIO_RAW_RING_DEPTH,
            "gpio_packed_ready_depth": constants.GPIO_PACKED_RING_DEPTH,
            "gpio_packed_ready_high_water": constants.GPIO_PACKED_RING_DEPTH,
            "packet_ready_depth": constants.GPIO_PACKET_BUFFER_COUNT,
            "packet_transmit_depth": constants.GPIO_PACKET_BUFFER_COUNT,
            "packet_owned_high_water": constants.GPIO_PACKET_BUFFER_COUNT,
        }
        for name, maximum in depth_limits.items():
            _unsigned(name, getattr(self, name), 16)
            if getattr(self, name) > maximum:
                raise ValueError(f"{name} exceeds its advertised ring capacity")
        for name in _STATUS_PIPELINE_U64_FIELDS:
            _unsigned(name, getattr(self, name), 64)
        for name in _STATUS_DIAGNOSTIC_U32_FIELDS:
            _unsigned(name, getattr(self, name), 32)
        extended_depth_limits = {
            "adc_packet_ready_depth": constants.PACKET_READY_QUEUE_CAPACITY,
            "gpio_packet_ready_depth": constants.PACKET_READY_QUEUE_CAPACITY,
            "adc_packet_transmit_depth": constants.PACKET_TRANSMIT_QUEUE_CAPACITY,
            "gpio_packet_transmit_depth": constants.PACKET_TRANSMIT_QUEUE_CAPACITY,
            "adc_packet_ready_high_water": constants.PACKET_READY_QUEUE_CAPACITY,
            "gpio_packet_ready_high_water": constants.PACKET_READY_QUEUE_CAPACITY,
            "adc_packet_transmit_high_water": (
                constants.PACKET_TRANSMIT_QUEUE_CAPACITY
            ),
            "gpio_packet_transmit_high_water": (
                constants.PACKET_TRANSMIT_QUEUE_CAPACITY
            ),
            "packet_ready_high_water": constants.PACKET_READY_QUEUE_CAPACITY,
            "packet_transmit_high_water": constants.PACKET_TRANSMIT_QUEUE_CAPACITY,
            "usb_command_queue_depth": constants.COMMAND_QUEUE_CAPACITY,
            "usb_response_queue_depth": constants.RESPONSE_QUEUE_CAPACITY,
            "usb_lower_priority_queue_depth": (
                constants.PACKET_TRANSMIT_QUEUE_CAPACITY
            ),
            "usb_command_queue_high_water": constants.COMMAND_QUEUE_CAPACITY,
            "usb_response_queue_high_water": constants.RESPONSE_QUEUE_CAPACITY,
            "usb_active_frame_bytes_sent": constants.DATA_FRAME_BYTES,
        }
        for name in _STATUS_QUEUE_U16_FIELDS:
            _unsigned(name, getattr(self, name), 16)
            if getattr(self, name) > extended_depth_limits[name]:
                raise ValueError(f"{name} exceeds its advertised capacity")
        _unsigned(
            "gpio_processing_cpu_basis_points",
            self.gpio_processing_cpu_basis_points,
            16,
        )
        if self.gpio_processing_cpu_basis_points > 10_000:
            raise ValueError("GPIO processing CPU percentage exceeds 100%")
        _unsigned("stats_generation", self.stats_generation, 32)
        if self.stats_generation == 0:
            raise ValueError("stats_generation must be nonzero")
        _normalize_adc_metadata(self)
        # Constructing this nested snapshot validates every STATUS-only ADC
        # counter while retaining the schema field names on Status itself.
        AdcAcquisitionStatus.from_status_fields(self)

    @property
    def adc_calibration(self) -> AdcCalibrationMetadata:
        """Return independently reported ADC0/ADC1 calibration evidence."""

        return AdcCalibrationMetadata.from_device_metadata(self)

    @property
    def adc_acquisition(self) -> AdcAcquisitionStatus:
        """Return the detailed physical ADC DMA-to-USB status snapshot."""

        return AdcAcquisitionStatus.from_status_fields(self)

    @property
    def has_adc_errors(self) -> bool:
        """Whether initialization, trigger, conversion, or pipeline errors exist."""

        return bool(
            self.adc_initialization_error_flags
            or self.adc_trigger.error_flags
            or self.adc_trigger.trigger_error_count
            or self.adc_acquisition.has_errors
        )

    @property
    def counters(self) -> FirmwareCounters:
        """Return the firmware-only counter subset with units preserved."""

        return FirmwareCounters(
            adc_frames_emitted=self.adc_frames_emitted,
            gpio_frames_emitted=self.gpio_frames_emitted,
            adc_items_dropped=self.adc_items_dropped,
            gpio_items_dropped=self.gpio_items_dropped,
            parser_errors=self.parser_errors,
            transport_errors=self.transport_errors,
            stats_generation=self.stats_generation,
            gpio_samples_captured=self.gpio_samples_captured,
            gpio_samples_packed=self.gpio_samples_packed,
            gpio_samples_framed=self.gpio_samples_framed,
            gpio_samples_transmitted=self.gpio_samples_transmitted,
            gpio_raw_samples_lost=self.gpio_raw_samples_lost,
            gpio_packer_samples_dropped=self.gpio_packer_samples_dropped,
            gpio_raw_ring_overruns=self.gpio_raw_ring_overruns,
            gpio_dma_major_loops=self.gpio_dma_major_loops,
            gpio_processing_cpu_basis_points=(self.gpio_processing_cpu_basis_points),
            gpio_hardware_errors=self.gpio_hardware_errors,
            gpio_raw_invariant_errors=self.gpio_raw_invariant_errors,
            gpio_packer_source_errors=self.gpio_packer_source_errors,
            gpio_packer_pipeline_errors=self.gpio_packer_pipeline_errors,
            gpio_packer_chronology_errors=self.gpio_packer_chronology_errors,
            gpio_resource_conflicts=self.gpio_resource_conflicts,
            gpio_start_errors=self.gpio_start_errors,
            gpio_stop_errors=self.gpio_stop_errors,
            gpio_stale_dma_completions=self.gpio_stale_dma_completions,
            adc0_dma_major_loops=self.adc0_dma_major_loops,
            adc1_dma_major_loops=self.adc1_dma_major_loops,
            adc0_dma_results=self.adc0_dma_results,
            adc1_dma_results=self.adc1_dma_results,
            adc_paired_major_loops=self.adc_paired_major_loops,
            adc_buffers_completed=self.adc_buffers_completed,
            adc_buffers_acquired=self.adc_buffers_acquired,
            adc_buffers_released=self.adc_buffers_released,
            adc_pairs_captured=self.adc_pairs_captured,
            adc_pairs_delivered=self.adc_pairs_delivered,
            adc_pairs_framed=self.adc_pairs_framed,
            adc_pairs_transmitted=self.adc_pairs_transmitted,
            adc_raw_pairs_lost=self.adc_raw_pairs_lost,
            adc_stop_pairs_discarded=self.adc_stop_pairs_discarded,
            adc_incomplete_conversions=self.adc_incomplete_conversions,
            adc_overwritten_conversions=self.adc_overwritten_conversions,
            adc_raw_ring_overruns=self.adc_raw_ring_overruns,
            adc_incomplete_buffers=self.adc_incomplete_buffers,
            adc_raw_ready_depth=self.adc_raw_ready_depth,
            adc_raw_ready_high_water=self.adc_raw_ready_high_water,
            adc_etc_error_events=self.adc_etc_error_events,
            adc_etc_error_flags=self.adc_etc_error_flags,
            adc_dma_error_events=self.adc_dma_error_events,
            adc_completion_mismatches=self.adc_completion_mismatches,
            adc_destination_mismatches=self.adc_destination_mismatches,
            adc_schedule_exhaustions=self.adc_schedule_exhaustions,
            adc_raw_invariant_errors=self.adc_raw_invariant_errors,
            adc_stale_completions=self.adc_stale_completions,
            adc_resource_conflicts=self.adc_resource_conflicts,
            adc_start_errors=self.adc_start_errors,
            adc_stop_errors=self.adc_stop_errors,
            adc_stale_interrupts=self.adc_stale_interrupts,
            adc_packer_source_errors=self.adc_packer_source_errors,
            adc_packer_pipeline_errors=self.adc_packer_pipeline_errors,
            adc_packer_chronology_errors=self.adc_packer_chronology_errors,
            **{
                name: getattr(self, name)
                for name in (
                    *_STATUS_PIPELINE_U64_FIELDS,
                    *_STATUS_DIAGNOSTIC_U32_FIELDS,
                )
            },
        )

    @property
    def checksum_algorithm(self) -> constants.ChecksumAlgorithm:
        """Alias matching the checksum metadata carried by each data block."""

        return self.data_checksum_algorithm

    def to_payload(self) -> bytes:
        """Encode a successful STATUS response with ADC initialization state."""

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
        struct.pack_into(
            "<I",
            payload,
            constants.STATUS_RESPONSE_STATS_GENERATION_OFFSET,
            self.stats_generation,
        )
        struct.pack_into(
            "<QQQQQQQQ",
            payload,
            constants.STATUS_RESPONSE_GPIO_SAMPLES_CAPTURED_OFFSET,
            self.gpio_samples_captured,
            self.gpio_samples_packed,
            self.gpio_samples_framed,
            self.gpio_samples_transmitted,
            self.gpio_raw_samples_lost,
            self.gpio_packer_samples_dropped,
            self.gpio_raw_ring_overruns,
            self.gpio_dma_major_loops,
        )
        struct.pack_into(
            "<HHHHHHH",
            payload,
            constants.STATUS_RESPONSE_GPIO_RAW_READY_DEPTH_OFFSET,
            self.gpio_raw_ready_depth,
            self.gpio_raw_ready_high_water,
            self.gpio_packed_ready_depth,
            self.gpio_packed_ready_high_water,
            self.packet_ready_depth,
            self.packet_transmit_depth,
            self.packet_owned_high_water,
        )
        struct.pack_into(
            "<H",
            payload,
            constants.STATUS_RESPONSE_GPIO_PROCESSING_CPU_BASIS_POINTS_OFFSET,
            self.gpio_processing_cpu_basis_points,
        )
        struct.pack_into(
            "<IIIIIIIII",
            payload,
            constants.STATUS_RESPONSE_GPIO_HARDWARE_ERRORS_OFFSET,
            self.gpio_hardware_errors,
            self.gpio_raw_invariant_errors,
            self.gpio_packer_source_errors,
            self.gpio_packer_pipeline_errors,
            self.gpio_packer_chronology_errors,
            self.gpio_resource_conflicts,
            self.gpio_start_errors,
            self.gpio_stop_errors,
            self.gpio_stale_dma_completions,
        )
        _pack_adc_metadata(payload, self, "STATUS_RESPONSE")
        _pack_adc_acquisition_status(payload, self)
        for name in _STATUS_PIPELINE_U64_FIELDS:
            struct.pack_into(
                "<Q",
                payload,
                getattr(constants, f"STATUS_RESPONSE_{name.upper()}_OFFSET"),
                getattr(self, name),
            )
        for name in _STATUS_DIAGNOSTIC_U32_FIELDS:
            struct.pack_into(
                "<I",
                payload,
                getattr(constants, f"STATUS_RESPONSE_{name.upper()}_OFFSET"),
                getattr(self, name),
            )
        for name in _STATUS_QUEUE_U16_FIELDS:
            struct.pack_into(
                "<H",
                payload,
                getattr(constants, f"STATUS_RESPONSE_{name.upper()}_OFFSET"),
                getattr(self, name),
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
        gpio_counts = struct.unpack_from(
            "<QQQQQQQQ",
            payload_bytes,
            constants.STATUS_RESPONSE_GPIO_SAMPLES_CAPTURED_OFFSET,
        )
        depths = struct.unpack_from(
            "<HHHHHHH",
            payload_bytes,
            constants.STATUS_RESPONSE_GPIO_RAW_READY_DEPTH_OFFSET,
        )
        errors = struct.unpack_from(
            "<IIIIIIIII",
            payload_bytes,
            constants.STATUS_RESPONSE_GPIO_HARDWARE_ERRORS_OFFSET,
        )
        extended: dict[str, int] = {}
        for name in _STATUS_PIPELINE_U64_FIELDS:
            extended[name] = struct.unpack_from(
                "<Q",
                payload_bytes,
                getattr(constants, f"STATUS_RESPONSE_{name.upper()}_OFFSET"),
            )[0]
        for name in _STATUS_DIAGNOSTIC_U32_FIELDS:
            extended[name] = struct.unpack_from(
                "<I",
                payload_bytes,
                getattr(constants, f"STATUS_RESPONSE_{name.upper()}_OFFSET"),
            )[0]
        for name in _STATUS_QUEUE_U16_FIELDS:
            extended[name] = struct.unpack_from(
                "<H",
                payload_bytes,
                getattr(constants, f"STATUS_RESPONSE_{name.upper()}_OFFSET"),
            )[0]
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
            stats_generation=struct.unpack_from(
                "<I",
                payload_bytes,
                constants.STATUS_RESPONSE_STATS_GENERATION_OFFSET,
            )[0],
            gpio_samples_captured=gpio_counts[0],
            gpio_samples_packed=gpio_counts[1],
            gpio_samples_framed=gpio_counts[2],
            gpio_samples_transmitted=gpio_counts[3],
            gpio_raw_samples_lost=gpio_counts[4],
            gpio_packer_samples_dropped=gpio_counts[5],
            gpio_raw_ring_overruns=gpio_counts[6],
            gpio_dma_major_loops=gpio_counts[7],
            gpio_raw_ready_depth=depths[0],
            gpio_raw_ready_high_water=depths[1],
            gpio_packed_ready_depth=depths[2],
            gpio_packed_ready_high_water=depths[3],
            packet_ready_depth=depths[4],
            packet_transmit_depth=depths[5],
            packet_owned_high_water=depths[6],
            gpio_processing_cpu_basis_points=struct.unpack_from(
                "<H",
                payload_bytes,
                constants.STATUS_RESPONSE_GPIO_PROCESSING_CPU_BASIS_POINTS_OFFSET,
            )[0],
            gpio_hardware_errors=errors[0],
            gpio_raw_invariant_errors=errors[1],
            gpio_packer_source_errors=errors[2],
            gpio_packer_pipeline_errors=errors[3],
            gpio_packer_chronology_errors=errors[4],
            gpio_resource_conflicts=errors[5],
            gpio_start_errors=errors[6],
            gpio_stop_errors=errors[7],
            gpio_stale_dma_completions=errors[8],
            **extended,  # type: ignore[arg-type]
            **_unpack_adc_metadata(payload_bytes, "STATUS_RESPONSE"),
            **_unpack_adc_acquisition_status(payload_bytes),
        )


@dataclass(frozen=True, slots=True)
class FirmwareCounters:
    """Firmware-origin counters from one nonzero statistics generation."""

    adc_frames_emitted: int = 0
    gpio_frames_emitted: int = 0
    adc_items_dropped: int = 0
    gpio_items_dropped: int = 0
    parser_errors: int = 0
    transport_errors: int = 0
    stats_generation: int = 1
    adc_frames_generated: int = 0
    adc_items_generated: int = 0
    adc_frames_framed_pipeline: int = 0
    adc_items_framed_pipeline: int = 0
    adc_items_emitted: int = 0
    adc_frames_transmitted: int = 0
    adc_items_transmitted_pipeline: int = 0
    adc_frames_dropped: int = 0
    gpio_frames_generated: int = 0
    gpio_items_generated: int = 0
    gpio_frames_framed_pipeline: int = 0
    gpio_items_framed_pipeline: int = 0
    gpio_items_emitted: int = 0
    gpio_frames_transmitted: int = 0
    gpio_items_transmitted_pipeline: int = 0
    gpio_frames_dropped: int = 0
    adc_payload_bytes_produced: int = 0
    adc_payload_bytes_framed: int = 0
    adc_payload_bytes_emitted: int = 0
    adc_payload_bytes_transmitted: int = 0
    adc_payload_bytes_dropped: int = 0
    adc_framed_bytes_framed: int = 0
    adc_framed_bytes_emitted: int = 0
    adc_framed_bytes_transmitted: int = 0
    gpio_payload_bytes_produced: int = 0
    gpio_payload_bytes_framed: int = 0
    gpio_payload_bytes_emitted: int = 0
    gpio_payload_bytes_transmitted: int = 0
    gpio_payload_bytes_dropped: int = 0
    gpio_framed_bytes_framed: int = 0
    gpio_framed_bytes_emitted: int = 0
    gpio_framed_bytes_transmitted: int = 0
    packet_frames_promoted: int = 0
    packet_fairness_deferrals: int = 0
    packet_accounted_frame_skew: int = 0
    data_payload_bytes_transmitted: int = 0
    data_framed_bytes_transmitted: int = 0
    packet_pool_exhaustions: int = 0
    packet_invalid_operations: int = 0
    packet_encoding_rejections: int = 0
    packet_ready_queue_rejections: int = 0
    packet_transmit_queue_rejections: int = 0
    commands_accepted: int = 0
    commands_rejected: int = 0
    bad_checksums: int = 0
    bad_lengths: int = 0
    bad_types: int = 0
    bad_versions: int = 0
    timeouts: int = 0
    partial_usb_writes: int = 0
    state_errors: int = 0
    usb_short_capacity_deferrals: int = 0
    usb_rx_stall_events: int = 0
    usb_tx_stall_events: int = 0
    usb_io_errors: int = 0
    gpio_samples_captured: int = 0
    gpio_samples_packed: int = 0
    gpio_samples_framed: int = 0
    gpio_samples_transmitted: int = 0
    gpio_raw_samples_lost: int = 0
    gpio_packer_samples_dropped: int = 0
    gpio_raw_ring_overruns: int = 0
    gpio_dma_major_loops: int = 0
    gpio_processing_cpu_basis_points: int = 0
    gpio_hardware_errors: int = 0
    gpio_raw_invariant_errors: int = 0
    gpio_packer_source_errors: int = 0
    gpio_packer_pipeline_errors: int = 0
    gpio_packer_chronology_errors: int = 0
    gpio_resource_conflicts: int = 0
    gpio_start_errors: int = 0
    gpio_stop_errors: int = 0
    gpio_stale_dma_completions: int = 0
    adc0_dma_major_loops: int = 0
    adc1_dma_major_loops: int = 0
    adc0_dma_results: int = 0
    adc1_dma_results: int = 0
    adc_paired_major_loops: int = 0
    adc_buffers_completed: int = 0
    adc_buffers_acquired: int = 0
    adc_buffers_released: int = 0
    adc_pairs_captured: int = 0
    adc_pairs_delivered: int = 0
    adc_pairs_framed: int = 0
    adc_pairs_transmitted: int = 0
    adc_raw_pairs_lost: int = 0
    adc_stop_pairs_discarded: int = 0
    adc_incomplete_conversions: int = 0
    adc_overwritten_conversions: int = 0
    adc_raw_ring_overruns: int = 0
    adc_incomplete_buffers: int = 0
    adc_raw_ready_depth: int = 0
    adc_raw_ready_high_water: int = 0
    adc_etc_error_events: int = 0
    adc_etc_error_flags: int = 0
    adc_dma_error_events: int = 0
    adc_completion_mismatches: int = 0
    adc_destination_mismatches: int = 0
    adc_schedule_exhaustions: int = 0
    adc_raw_invariant_errors: int = 0
    adc_stale_completions: int = 0
    adc_resource_conflicts: int = 0
    adc_start_errors: int = 0
    adc_stop_errors: int = 0
    adc_stale_interrupts: int = 0
    adc_packer_source_errors: int = 0
    adc_packer_pipeline_errors: int = 0
    adc_packer_chronology_errors: int = 0

    def __post_init__(self) -> None:
        for name in (
            "adc_frames_emitted",
            "gpio_frames_emitted",
            "adc_items_dropped",
            "gpio_items_dropped",
            "gpio_samples_captured",
            "gpio_samples_packed",
            "gpio_samples_framed",
            "gpio_samples_transmitted",
            "gpio_raw_samples_lost",
            "gpio_packer_samples_dropped",
            "gpio_raw_ring_overruns",
            "gpio_dma_major_loops",
        ):
            _unsigned(name, getattr(self, name), 64)
        for name in (
            "parser_errors",
            "transport_errors",
            "gpio_hardware_errors",
            "gpio_raw_invariant_errors",
            "gpio_packer_source_errors",
            "gpio_packer_pipeline_errors",
            "gpio_packer_chronology_errors",
            "gpio_resource_conflicts",
            "gpio_start_errors",
            "gpio_stop_errors",
            "gpio_stale_dma_completions",
        ):
            _unsigned(name, getattr(self, name), 32)
        for name in _STATUS_PIPELINE_U64_FIELDS:
            _unsigned(name, getattr(self, name), 64)
        for name in _STATUS_DIAGNOSTIC_U32_FIELDS:
            _unsigned(name, getattr(self, name), 32)
        _unsigned(
            "gpio_processing_cpu_basis_points",
            self.gpio_processing_cpu_basis_points,
            16,
        )
        if self.gpio_processing_cpu_basis_points > 10_000:
            raise ValueError("GPIO processing CPU percentage exceeds 100%")
        _unsigned("stats_generation", self.stats_generation, 32)
        if self.stats_generation == 0:
            raise ValueError("stats_generation must be nonzero")
        AdcAcquisitionStatus.from_status_fields(self)

    @property
    def adc_acquisition(self) -> AdcAcquisitionStatus:
        """Return the physical ADC acquisition counters in one typed view."""

        return AdcAcquisitionStatus.from_status_fields(self)

    @property
    def items_dropped(self) -> int:
        """Total firmware-dropped logical items across both stream kinds."""

        return self.adc_items_dropped + self.gpio_items_dropped

    @property
    def has_loss(self) -> bool:
        return bool(
            self.items_dropped
            or self.adc_frames_dropped
            or self.gpio_frames_dropped
            or self.adc_payload_bytes_dropped
            or self.gpio_payload_bytes_dropped
            or self.packet_pool_exhaustions
            or self.packet_encoding_rejections
            or self.packet_ready_queue_rejections
            or self.packet_transmit_queue_rejections
            or self.adc_acquisition.has_loss
        )


@dataclass(frozen=True, slots=True)
class HostCounters:
    """Host-only parsing, queue, request, and connection counters."""

    parser_corruption_events: int = 0
    parser_resynchronizations: int = 0
    host_block_queue_drops: int = 0
    host_event_queue_drops: int = 0
    stale_blocks_discarded: int = 0
    boundary_blocks_discarded: int = 0
    late_responses: int = 0
    request_timeouts: int = 0
    protocol_failures: int = 0
    disconnects: int = 0

    def __post_init__(self) -> None:
        for name in self.__dataclass_fields__:
            _nonnegative(name, getattr(self, name))

    @property
    def has_queue_loss(self) -> bool:
        return self.host_block_queue_drops > 0


@dataclass(frozen=True, slots=True)
class LossCounters:
    """One explicit snapshot keeping firmware and host loss domains separate."""

    firmware: FirmwareCounters
    host: HostCounters
    observed_stream_gaps: int = 0

    def __post_init__(self) -> None:
        if not isinstance(self.firmware, FirmwareCounters):
            raise TypeError("firmware must be FirmwareCounters")
        if not isinstance(self.host, HostCounters):
            raise TypeError("host must be HostCounters")
        _nonnegative("observed_stream_gaps", self.observed_stream_gaps)

    @property
    def has_loss(self) -> bool:
        return (
            self.firmware.has_loss
            or self.host.has_queue_loss
            or self.observed_stream_gaps > 0
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

    def __post_init__(self) -> None:
        _nonnegative("pair_index", self.pair_index)
        if not isinstance(self.converter, AdcConverter):
            raise TypeError("converter must retain an ADC0 or ADC1 identity")
        _unsigned("code", self.code, constants.ADC_RESOLUTION_BITS)
        _unsigned("timestamp_ticks", self.timestamp_ticks, 64)

    @property
    def pin(self) -> str:
        return self.converter.pin

    @property
    def timestamp_seconds(self) -> float:
        """Nominal START-relative time on the advertised 8 MHz schedule."""

        return self.timestamp_ticks / constants.TIMESTAMP_HZ


class AdcChannelView(Sequence[int]):
    """Lazy sequence view over one converter in an interleaved wire payload."""

    __slots__ = ("_block", "converter")

    def __init__(self, block: ADCBlock, converter: AdcConverter | int) -> None:
        self._block = block
        if isinstance(converter, bool):
            raise TypeError("converter must be ADC0 or ADC1")
        try:
            self.converter = AdcConverter(converter)
        except (TypeError, ValueError) as exc:
            raise ValueError("converter must be ADC0 or ADC1") from exc

    def __len__(self) -> int:
        return self._block.item_count

    @property
    def payload_view(self) -> memoryview:
        """Zero-copy view of the shared pair buffer backing this channel."""

        return self._block.payload_view

    @property
    def byte_offset(self) -> int:
        """Byte offset of this converter's first little-endian ``uint16``."""

        return 2 * int(self.converter)

    @property
    def byte_stride(self) -> int:
        """Byte distance between consecutive values for this converter."""

        return constants.ADC_BYTES_PER_PAIR

    @property
    def item_size(self) -> int:
        return constants.ADC_CONTAINER_BITS // 8

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
        offset = position * self.byte_stride + self.byte_offset
        return struct.unpack_from("<H", self._block.payload, offset)[0]


@dataclass(frozen=True, slots=True)
class ADCBlock:
    """One fixed ADC frame; each logical item is an ADC0/ADC1 sample pair."""

    run_id: int
    sequence: int
    first_sample_ticks: int
    payload: bytes
    flags: constants.FrameFlag = constants.FrameFlag.NONE
    checksum_algorithm: constants.ChecksumAlgorithm = (
        constants.DEFAULT_CHECKSUM_ALGORITHM
    )
    metadata: AdcBlockMetadata = dataclass_field(default_factory=AdcBlockMetadata)
    gap: StreamGap | None = None

    def __post_init__(self) -> None:
        _unsigned("run_id", self.run_id, 32)
        _unsigned("sequence", self.sequence, 32)
        _unsigned("first_sample_ticks", self.first_sample_ticks, 64)
        if self.run_id == 0:
            raise ValueError("ADC blocks require a nonzero run ID")
        if not isinstance(self.payload, (bytes, bytearray, memoryview)):
            raise TypeError("ADC payload must be bytes-like")
        try:
            payload = bytes(self.payload)
        except (TypeError, ValueError) as exc:
            raise ValueError("ADC payload must be bytes-like") from exc
        object.__setattr__(self, "payload", payload)
        object.__setattr__(self, "flags", _validated_data_flags(self.flags))
        if isinstance(self.checksum_algorithm, bool):
            raise TypeError("ADC block checksum algorithm is unsupported")
        try:
            checksum = constants.ChecksumAlgorithm(self.checksum_algorithm)
        except (TypeError, ValueError) as exc:
            raise ValueError("ADC block checksum algorithm is unknown") from exc
        if checksum not in HOST_SUPPORTED_CHECKSUM_ALGORITHMS:
            raise ValueError(
                f"host has no implementation for checksum algorithm {checksum.name}"
            )
        object.__setattr__(self, "checksum_algorithm", checksum)
        if len(payload) != constants.ADC_DATA_PAYLOAD_SIZE:
            raise ValueError("ADC blocks require exactly 1012 sample pairs")
        if not isinstance(self.metadata, AdcBlockMetadata):
            raise TypeError("ADC block metadata must be AdcBlockMetadata")
        wire_source = (
            constants.Source.SYNTHETIC
            if self.flags & constants.FrameFlag.SYNTHETIC
            else constants.Source.HARDWARE
        )
        if self.metadata.source is not wire_source:
            object.__setattr__(
                self,
                "metadata",
                dataclass_replace(self.metadata, source=wire_source),
            )
        if any(
            not self.metadata.code_min <= adc0 <= self.metadata.code_max
            or not self.metadata.code_min <= adc1 <= self.metadata.code_max
            for adc0, adc1 in struct.iter_unpack("<HH", payload)
        ):
            raise ValueError(
                "ADC codes must fit the advertised "
                f"{self.metadata.resolution_bits}-bit range"
            )
        if self.gap is not None:
            if not isinstance(self.gap, StreamGap):
                raise TypeError("ADC gap metadata must be StreamGap or None")
            if (
                self.gap.kind is not constants.FrameKind.ADC_DATA
                or self.gap.run_id != self.run_id
                or self.gap.observed_sequence != self.sequence
                or self.gap.observed_first_sample_ticks != self.first_sample_ticks
            ):
                raise ValueError("ADC gap metadata does not describe this block")

    @classmethod
    def from_frame(cls, frame: Frame) -> ADCBlock:
        if frame.header.kind is not constants.FrameKind.ADC_DATA:
            raise TypeError("frame is not ADC_DATA")
        source = (
            constants.Source.SYNTHETIC
            if frame.header.flags & constants.FrameFlag.SYNTHETIC
            else constants.Source.HARDWARE
        )
        return cls(
            run_id=frame.header.run_id,
            sequence=frame.header.sequence,
            first_sample_ticks=frame.header.first_sample_ticks,
            payload=frame.payload,
            flags=frame.header.flags,
            checksum_algorithm=frame.header.checksum_algorithm,
            metadata=AdcBlockMetadata(source=source),
        )

    @property
    def data_checksum_algorithm(self) -> constants.ChecksumAlgorithm:
        """The exact algorithm that validated this frame's trailer."""

        return self.checksum_algorithm

    @property
    def item_count(self) -> int:
        """Logical pair count; this is not a combined two-channel sample rate."""

        return constants.ADC_PAIRS_PER_FRAME

    @property
    def t0_ticks(self) -> int:
        """Run-relative nominal ADC0 timestamp for the first pair."""

        return self.first_sample_ticks

    @property
    def t0(self) -> int:
        """Concise tick-domain alias for :attr:`t0_ticks`."""

        return self.t0_ticks

    @property
    def timestamp_hz(self) -> int:
        """Frequency of the advertised START-relative timestamp domain."""

        return self.metadata.timestamp_hz

    @property
    def t0_seconds(self) -> float:
        """Nominal first ADC0 time without an analog-aperture claim."""

        return self.t0_ticks / self.timestamp_hz

    @property
    def pair_period_ticks(self) -> int:
        return self.metadata.pair_period_ticks

    @property
    def pair_period(self) -> int:
        """Concise tick-domain alias for :attr:`pair_period_ticks`."""

        return self.pair_period_ticks

    @property
    def adc1_phase_ticks(self) -> int:
        return self.metadata.adc1_phase_ticks

    @property
    def adc1_phase(self) -> int:
        """Concise tick-domain alias for :attr:`adc1_phase_ticks`."""

        return self.adc1_phase_ticks

    @property
    def resolution_bits(self) -> int:
        return self.metadata.resolution_bits

    @property
    def resolution(self) -> int:
        return self.resolution_bits

    @property
    def code_range(self) -> tuple[int, int]:
        return self.metadata.code_min, self.metadata.code_max

    @property
    def source(self) -> constants.Source:
        return self.metadata.source

    @property
    def run(self) -> int:
        return self.run_id

    @property
    def calibration(self) -> AdcCalibrationMetadata:
        return self.metadata.calibration

    @property
    def trigger(self) -> AdcTriggerMetadata:
        return self.metadata.trigger

    @property
    def acquisition(self) -> AdcAcquisitionStatus | None:
        """Latest STATUS evidence known when this block was delivered, if any."""

        return self.metadata.acquisition

    @property
    def gap_before(self) -> bool:
        """Whether continuity metadata reports a gap immediately before this block."""

        return self.gap is not None or bool(self.flags & constants.FrameFlag.GAP_BEFORE)

    @property
    def payload_view(self) -> memoryview:
        """Zero-copy byte view over the interleaved little-endian pair payload."""

        return memoryview(self.payload)

    def pairs(self) -> Iterator[tuple[int, int]]:
        """Iterate decoded ``(ADC0, ADC1)`` pairs without building a container."""

        return struct.iter_unpack("<HH", self.payload)

    @property
    def adc0(self) -> AdcChannelView:
        return AdcChannelView(self, AdcConverter.ADC0)

    @property
    def adc1(self) -> AdcChannelView:
        return AdcChannelView(self, AdcConverter.ADC1)

    @property
    def end_tick_exclusive(self) -> int:
        return (
            self.first_sample_ticks + self.item_count * self.pair_period_ticks
        ) & constants.UINT64_MAX

    @property
    def first_pair_index(self) -> int:
        """Global per-converter sample index implied by the 8 MHz timestamp."""

        return self.first_sample_ticks // self.pair_period_ticks

    def pair(self, index: int) -> tuple[int, int]:
        return self.adc0[index], self.adc1[index]

    def pair_ticks(self, index: int) -> tuple[int, int]:
        if index < 0:
            index += self.item_count
        if not 0 <= index < self.item_count:
            raise IndexError("ADC pair index out of range")
        adc0_tick = (
            self.first_sample_ticks + index * self.pair_period_ticks
        ) & constants.UINT64_MAX
        return adc0_tick, (adc0_tick + self.adc1_phase_ticks) & (constants.UINT64_MAX)

    def pair_seconds(self, index: int) -> tuple[float, float]:
        """Return nominal ADC0/ADC1 START-relative times in seconds."""

        adc0_tick, adc1_tick = self.pair_ticks(index)
        return adc0_tick / self.timestamp_hz, adc1_tick / self.timestamp_hz

    def interleaved(self) -> Iterator[AdcSample]:
        """Explicitly merge ADC0/ADC1 times without claiming added bandwidth."""

        return interleave_adc(self)


# Preserve the conventional mixed-case Phase 01 spelling.
AdcBlock = ADCBlock


def interleave_adc(block: ADCBlock) -> Iterator[AdcSample]:
    """Lazily merge nominal times; this does not increase analog bandwidth."""

    adc0 = block.adc0
    adc1 = block.adc1
    for pair_index in range(block.item_count):
        adc0_tick, adc1_tick = block.pair_ticks(pair_index)
        yield AdcSample(pair_index, AdcConverter.ADC0, adc0[pair_index], adc0_tick)
        yield AdcSample(pair_index, AdcConverter.ADC1, adc1[pair_index], adc1_tick)


class GpioChannelView(Sequence[bool]):
    """Lazy Boolean view over one D6-through-D13 bit in packed GPIO samples."""

    __slots__ = ("_block", "bit", "pin")

    def __init__(self, block: GPIOBlock, pin: int) -> None:
        if not isinstance(pin, int) or isinstance(pin, bool):
            raise TypeError("GPIO pin must be one of D6 through D13")
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
class GPIOBlock:
    """One fixed GPIO frame containing packed simultaneous D6-D13 samples."""

    run_id: int
    sequence: int
    first_sample_ticks: int
    payload: bytes
    flags: constants.FrameFlag = constants.FrameFlag.NONE
    checksum_algorithm: constants.ChecksumAlgorithm = (
        constants.DEFAULT_CHECKSUM_ALGORITHM
    )

    def __post_init__(self) -> None:
        _unsigned("run_id", self.run_id, 32)
        _unsigned("sequence", self.sequence, 32)
        _unsigned("first_sample_ticks", self.first_sample_ticks, 64)
        if self.run_id == 0:
            raise ValueError("GPIO blocks require a nonzero run ID")
        if not isinstance(self.payload, (bytes, bytearray, memoryview)):
            raise TypeError("GPIO payload must be bytes-like")
        try:
            payload = bytes(self.payload)
        except (TypeError, ValueError) as exc:
            raise ValueError("GPIO payload must be bytes-like") from exc
        object.__setattr__(self, "payload", payload)
        object.__setattr__(self, "flags", _validated_data_flags(self.flags))
        if isinstance(self.checksum_algorithm, bool):
            raise TypeError("GPIO block checksum algorithm is unsupported")
        try:
            checksum = constants.ChecksumAlgorithm(self.checksum_algorithm)
        except (TypeError, ValueError) as exc:
            raise ValueError("GPIO block checksum algorithm is unknown") from exc
        if checksum not in HOST_SUPPORTED_CHECKSUM_ALGORITHMS:
            raise ValueError(
                f"host has no implementation for checksum algorithm {checksum.name}"
            )
        object.__setattr__(self, "checksum_algorithm", checksum)
        if len(payload) != constants.GPIO_DATA_PAYLOAD_SIZE:
            raise ValueError("GPIO blocks require exactly 4048 packed samples")

    @classmethod
    def from_frame(cls, frame: Frame) -> GPIOBlock:
        if frame.header.kind is not constants.FrameKind.GPIO_DATA:
            raise TypeError("frame is not GPIO_DATA")
        return cls(
            run_id=frame.header.run_id,
            sequence=frame.header.sequence,
            first_sample_ticks=frame.header.first_sample_ticks,
            payload=frame.payload,
            flags=frame.header.flags,
            checksum_algorithm=frame.header.checksum_algorithm,
        )

    @property
    def data_checksum_algorithm(self) -> constants.ChecksumAlgorithm:
        """The exact algorithm that validated this frame's trailer."""

        return self.checksum_algorithm

    @property
    def source(self) -> constants.Source:
        """Source identity encoded by the common data-frame flag."""

        return (
            constants.Source.SYNTHETIC
            if self.flags & constants.FrameFlag.SYNTHETIC
            else constants.Source.HARDWARE
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
    def timestamp_hz(self) -> int:
        """Frequency of the advertised START-relative timestamp domain."""

        return constants.TIMESTAMP_HZ

    @property
    def t0_ticks(self) -> int:
        """Nominal run-relative timestamp of the first packed GPIO byte."""

        return self.first_sample_ticks

    @property
    def t0(self) -> int:
        return self.t0_ticks

    @property
    def t0_seconds(self) -> float:
        """Nominal first packed-byte time without a GPIO-pad latency claim."""

        return self.t0_ticks / self.timestamp_hz

    @property
    def sample_period_ticks(self) -> int:
        return constants.GPIO_SAMPLE_PERIOD_TICKS

    @property
    def sample_period(self) -> int:
        return self.sample_period_ticks

    @property
    def payload_view(self) -> memoryview:
        """Alias for the zero-copy packed-sample view."""

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

    def sample_seconds(self, index: int) -> float:
        """Return one nominal packed-byte START-relative time in seconds."""

        return self.sample_ticks(index) / self.timestamp_hz

    def channel(self, pin: int) -> GpioChannelView:
        return GpioChannelView(self, pin)


# Preserve the conventional mixed-case Phase 01 spelling.
GpioBlock = GPIOBlock


def extract_gpio_channel(block: GPIOBlock, pin: int) -> GpioChannelView:
    """Return a lazy view of one pin without expanding the packed GPIO block."""

    return block.channel(pin)


class LossOrigin(Enum):
    """Best available attribution for one observed stream discontinuity."""

    OBSERVED = "observed"
    FIRMWARE = "firmware"
    HOST_QUEUE = "host_queue"
    MIXED = "mixed"


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
    firmware_reported: bool = False
    firmware_overrun: bool = False
    host_queue_drops: int = 0

    def __post_init__(self) -> None:
        if isinstance(self.kind, bool):
            raise TypeError("stream gaps apply only to ADC_DATA or GPIO_DATA")
        try:
            kind = constants.FrameKind(self.kind)
        except (TypeError, ValueError) as exc:
            raise ValueError("stream gaps apply only to ADC_DATA or GPIO_DATA") from exc
        object.__setattr__(self, "kind", kind)
        if kind not in {
            constants.FrameKind.ADC_DATA,
            constants.FrameKind.GPIO_DATA,
        }:
            raise ValueError("stream gaps apply only to ADC_DATA or GPIO_DATA")
        _unsigned("run_id", self.run_id, 32)
        _unsigned("expected_sequence", self.expected_sequence, 32)
        _unsigned("observed_sequence", self.observed_sequence, 32)
        _unsigned("expected_first_sample_ticks", self.expected_first_sample_ticks, 64)
        _unsigned("observed_first_sample_ticks", self.observed_first_sample_ticks, 64)
        _unsigned("missing_frames", self.missing_frames, 32)
        _unsigned("missing_items", self.missing_items, 64)
        _nonnegative("host_queue_drops", self.host_queue_drops)
        if self.run_id == 0:
            raise ValueError("stream gap run ID must be nonzero")
        if not isinstance(self.firmware_reported, bool) or not isinstance(
            self.firmware_overrun, bool
        ):
            raise TypeError("firmware gap markers must be booleans")
        if self.firmware_overrun and not self.firmware_reported:
            raise ValueError("firmware overrun attribution requires a gap marker")
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

    @property
    def origin(self) -> LossOrigin:
        """Attribute loss without ever relabeling host loss as firmware loss."""

        if self.firmware_reported and self.host_queue_drops:
            return LossOrigin.MIXED
        if self.firmware_reported:
            return LossOrigin.FIRMWARE
        if self.host_queue_drops:
            return LossOrigin.HOST_QUEUE
        return LossOrigin.OBSERVED

    @classmethod
    def from_expected(
        cls,
        current: ADCBlock | GPIOBlock,
        *,
        expected_sequence: int,
        expected_first_sample_ticks: int,
        host_queue_drops: int = 0,
    ) -> StreamGap | None:
        """Measure ``current`` against an explicit next-frame expectation."""

        _unsigned("expected_sequence", expected_sequence, 32)
        _unsigned("expected_first_sample_ticks", expected_first_sample_ticks, 64)
        _nonnegative("host_queue_drops", host_queue_drops)
        kind = (
            constants.FrameKind.ADC_DATA
            if isinstance(current, ADCBlock)
            else constants.FrameKind.GPIO_DATA
        )
        missing_frames = (current.sequence - expected_sequence) & constants.UINT32_MAX
        if missing_frames > constants.UINT32_MAX // 2:
            raise ValueError("duplicate or reversed sequence is not a forward gap")
        tick_delta = (
            current.first_sample_ticks - expected_first_sample_ticks
        ) & constants.UINT64_MAX
        if tick_delta > constants.UINT64_MAX // 2:
            raise ValueError("reversed timestamp is not a forward gap")
        period = (
            current.pair_period_ticks
            if isinstance(current, ADCBlock)
            else constants.GPIO_SAMPLE_PERIOD_TICKS
        )
        if tick_delta % period:
            raise ValueError("stream timestamp gap is not sample-period aligned")
        missing_items = tick_delta // period
        firmware_reported = bool(current.flags & constants.FrameFlag.GAP_BEFORE)
        if missing_frames == 0 and missing_items == 0 and not firmware_reported:
            return None
        return cls(
            kind=kind,
            run_id=current.run_id,
            expected_sequence=expected_sequence,
            observed_sequence=current.sequence,
            missing_frames=missing_frames,
            missing_items=missing_items,
            expected_first_sample_ticks=expected_first_sample_ticks,
            observed_first_sample_ticks=current.first_sample_ticks,
            firmware_reported=firmware_reported,
            firmware_overrun=bool(current.flags & constants.FrameFlag.OVERRUN_BEFORE),
            host_queue_drops=min(host_queue_drops, missing_frames),
        )

    @classmethod
    def between(
        cls,
        previous: ADCBlock | GPIOBlock,
        current: ADCBlock | GPIOBlock,
    ) -> StreamGap | None:
        """Measure a forward discontinuity between same-stream blocks."""

        if type(previous) is not type(current):
            raise ValueError("cannot compare different stream types")
        if previous.run_id != current.run_id:
            raise ValueError("a run change is an epoch boundary, not a stream gap")
        expected_sequence = (previous.sequence + 1) & constants.UINT32_MAX
        expected_ticks = previous.end_tick_exclusive
        return cls.from_expected(
            current,
            expected_sequence=expected_sequence,
            expected_first_sample_ticks=expected_ticks,
        )


ResponseValue = (
    Info
    | Configuration
    | Status
    | ChecksumBenchmarkResult
    | GpioClockDiagnosticResult
    | GpioCaptureDiagnosticResult
    | constants.DeviceState
    | int
)
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
        elif frame.header.kind is constants.FrameKind.GET_STATUS_RESPONSE:
            value = Status.from_payload(frame.payload)
        elif frame.header.kind is constants.FrameKind.STOP_RESPONSE:
            value = constants.DeviceState(
                frame.payload[constants.STOP_RESPONSE_DEVICE_STATE_OFFSET]
            )
        elif frame.header.kind is constants.FrameKind.RESET_STATS_RESPONSE:
            value = struct.unpack_from(
                "<I",
                frame.payload,
                constants.RESET_STATS_RESPONSE_STATS_GENERATION_OFFSET,
            )[0]
        elif frame.header.kind is constants.FrameKind.PING_RESPONSE:
            value = struct.unpack_from(
                "<Q", frame.payload, constants.PING_RESPONSE_NONCE_OFFSET
            )[0]
        elif frame.header.kind is constants.FrameKind.CHECKSUM_BENCHMARK_RESPONSE:
            value = ChecksumBenchmarkResult.from_payload(frame.payload)
        elif frame.header.kind is constants.FrameKind.GPIO_CLOCK_DIAGNOSTIC_RESPONSE:
            value = GpioClockDiagnosticResult.from_payload(frame.payload)
        elif frame.header.kind is constants.FrameKind.GPIO_CAPTURE_DIAGNOSTIC_RESPONSE:
            value = GpioCaptureDiagnosticResult.from_payload(frame.payload)
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
    "AdcAcquisitionStatus",
    "AdcBlock",
    "AdcBlockMetadata",
    "AdcCalibrationMetadata",
    "AdcChannelView",
    "AdcConverter",
    "AdcSample",
    "ChecksumBenchmarkRequest",
    "ChecksumBenchmarkResult",
    "CommandResponse",
    "Configuration",
    "DAQConfiguration",
    "DecodedMessage",
    "DeviceCapabilities",
    "DeviceInfo",
    "FirmwareCounters",
    "GPIOBlock",
    "GpioBlock",
    "GpioCaptureDiagnosticResult",
    "GpioChannelView",
    "GpioClockDiagnosticRequest",
    "GpioClockDiagnosticResult",
    "HostCounters",
    "Info",
    "LossCounters",
    "LossOrigin",
    "ResponseValue",
    "Status",
    "StreamGap",
    "decode_message",
    "decode_response",
    "extract_gpio_channel",
    "interleave_adc",
]
