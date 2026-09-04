"""Typed protocol models and lazy views over ADC and GPIO payloads."""

from __future__ import annotations

import struct
from collections.abc import Iterator, Sequence
from dataclasses import dataclass
from dataclasses import field as dataclass_field
from dataclasses import replace as dataclass_replace
from enum import Enum, IntEnum
from typing import TYPE_CHECKING, Any, Generic, TypeAlias, TypeVar, overload

from ._generated import protocol_constants as constants
from ._generated import protocol_v2_constants as v2_constants
from .checksum import HOST_SUPPORTED_CHECKSUM_ALGORITHMS
from .protocol import Frame, FrameValidationError
from .protocol_v2 import V2Frame

if TYPE_CHECKING:
    from .calibration import (
        CalibratedAdcChannels,
        CalibratedAdcSample,
        CalibrationRecord,
    )
    from .numpy import ADCArrayView, GPIOArrayView

_CONFIGURATION = struct.Struct("<BBBBI")
_CONFIGURATION_V2 = struct.Struct("<BBBBIII")
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
    "gpio_cache_dma_discards",
    "gpio_cache_cpu_invalidations",
    "bad_flags",
    "bad_payloads",
    "bad_request_ids",
    "responses_queued",
    "responses_completed",
    "response_queue_rejections",
    "response_reservations_abandoned",
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
    "packet_owned_depth",
    "usb_active_frame_size",
    "adc_packet_filling_depth",
    "gpio_packet_filling_depth",
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

AuxBankMode: TypeAlias = v2_constants.AuxBankMode
RateProfile: TypeAlias = v2_constants.RateProfile


@dataclass(frozen=True, slots=True)
class RateProfileTiming:
    """One generated exact-rate schedule shared by host and simulator."""

    profile: RateProfile
    adc_pair_rate_hz: int
    gpio_sample_rate_hz: int
    adc_pair_period_ticks: int
    adc1_phase_ticks: int
    gpio_sample_period_ticks: int
    gpio_master_pit_divider: int
    gpio_master_pit_load: int
    adc_pair_pit_divider: int
    adc_pair_pit_load: int
    adc_etc_predivider: int
    adc_etc_chain_length: int
    adc0_initial_delay: int
    adc1_initial_delay: int
    adc0_effective_delay: int
    adc1_effective_delay: int
    adc1_phase_ipg_cycles: int
    completion_expected_dwt_cycles: int
    disabled_frame_coverage_ticks: int
    input_frame_coverage_ticks: int

    @classmethod
    def from_profile(cls, profile: RateProfile | int) -> RateProfileTiming:
        if isinstance(profile, bool):
            raise TypeError("rate profile must be a generated RateProfile")
        try:
            selected = RateProfile(profile)
        except (TypeError, ValueError) as exc:
            raise ValueError(
                "rate profile is not one of the four exact profiles"
            ) from exc
        return cls(profile=selected, **v2_constants.RATE_PROFILE_TIMING[selected])

    @classmethod
    def from_rates(
        cls,
        adc_pair_rate_hz: int,
        gpio_sample_rate_hz: int,
    ) -> RateProfileTiming:
        if any(
            not isinstance(value, int) or isinstance(value, bool) or value <= 0
            for value in (adc_pair_rate_hz, gpio_sample_rate_hz)
        ):
            raise ValueError("ADC and GPIO rates must be positive integers")
        for profile in RateProfile:
            timing = cls.from_profile(profile)
            if (
                timing.adc_pair_rate_hz == adc_pair_rate_hz
                and timing.gpio_sample_rate_hz == gpio_sample_rate_hz
            ):
                return timing
        raise ValueError("rates must match an exact generated 4:1 ADC/GPIO profile")

    def frame_coverage_ticks(self, mode: AuxBankMode | int) -> int:
        try:
            selected = AuxBankMode(mode)
        except (TypeError, ValueError) as exc:
            raise ValueError("auxiliary bank mode must be DISABLED or INPUT") from exc
        return (
            self.disabled_frame_coverage_ticks
            if selected is AuxBankMode.DISABLED
            else self.input_frame_coverage_ticks
        )


@dataclass(frozen=True, slots=True)
class GPIOLayout:
    """Generated packed GPIO layout for one whole-bank mode."""

    aux_bank_mode: AuxBankMode
    packed_width_bits: int
    item_bytes: int
    items_per_frame: int
    payload_bytes: int
    total_frame_bytes: int
    adc_items_per_frame: int
    adc_payload_bytes: int
    adc_total_frame_bytes: int
    pins_by_bit: tuple[int, ...]
    primary_pins_by_bit: tuple[int, ...] = v2_constants.PRIMARY_GPIO_PINS_BY_BIT
    auxiliary_pins_by_bit: tuple[int, ...] = v2_constants.AUX_GPIO_PINS_BY_BIT

    @classmethod
    def from_mode(cls, mode: AuxBankMode | int) -> GPIOLayout:
        if isinstance(mode, bool):
            raise TypeError("auxiliary bank mode must be DISABLED or INPUT")
        try:
            selected = AuxBankMode(mode)
        except (TypeError, ValueError) as exc:
            raise ValueError("auxiliary bank mode must be DISABLED or INPUT") from exc
        layout = v2_constants.AUX_BANK_LAYOUTS[selected]
        pins = (
            v2_constants.PRIMARY_GPIO_PINS_BY_BIT
            if selected is AuxBankMode.DISABLED
            else v2_constants.GPIO_16_PINS_BY_BIT
        )
        return cls(
            aux_bank_mode=selected,
            packed_width_bits=layout["gpio_width_bits"],
            item_bytes=layout["gpio_bytes_per_item"],
            items_per_frame=layout["gpio_items_per_frame"],
            payload_bytes=layout["gpio_payload_bytes"],
            total_frame_bytes=layout["gpio_total_frame_bytes"],
            adc_items_per_frame=layout["adc_items_per_frame"],
            adc_payload_bytes=layout["adc_payload_bytes"],
            adc_total_frame_bytes=layout["adc_total_frame_bytes"],
            pins_by_bit=pins,
        )


RATE_PROFILE_TIMINGS = tuple(
    RateProfileTiming.from_profile(profile) for profile in RateProfile
)


@dataclass(frozen=True, slots=True)
class AdcTriggerMetadata:
    """Observable selected-rate ADC_ETC schedule and completion evidence.

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

        try:
            timing = RateProfileTiming.from_rates(
                self.pair_rate_hz,
                self.gpio_master_rate_hz,
            )
        except ValueError as exc:
            raise ValueError(
                "ADC trigger schedule is not an exact rate profile"
            ) from exc

        fixed_scalars = (
            ("pit_clock_hz", constants.ADC_TRIGGER_PIT_CLOCK_HZ),
            ("dwt_clock_hz", constants.ADC_TRIGGER_DWT_CLOCK_HZ),
            ("gpio_master_rate_hz", timing.gpio_sample_rate_hz),
            ("pair_rate_hz", timing.adc_pair_rate_hz),
            ("ipg_clock_hz", constants.ADC_TRIGGER_IPG_CLOCK_HZ),
            (
                "gpio_master_pit_channel",
                constants.ADC_TRIGGER_GPIO_MASTER_PIT_CHANNEL,
            ),
            ("pair_pit_channel", constants.ADC_TRIGGER_PAIR_PIT_CHANNEL),
            ("gpio_master_pit_load", timing.gpio_master_pit_load),
            ("pair_pit_load", timing.adc_pair_pit_load),
            ("predivider", timing.adc_etc_predivider),
            ("chain_length", timing.adc_etc_chain_length),
            ("phase_ipg_cycles", timing.adc1_phase_ipg_cycles),
            (
                "completion_expected_delta_cycles",
                timing.completion_expected_dwt_cycles,
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
            raise ValueError("ADC trigger schedule is incompatible")

        fixed_pairs = (
            ("xbar_inputs", constants.ADC_TRIGGER_XBAR_INPUTS),
            ("xbar_outputs", constants.ADC_TRIGGER_XBAR_OUTPUTS),
            ("trigger_queues", constants.ADC_TRIGGER_QUEUES),
            (
                "initial_delays",
                (timing.adc0_initial_delay, timing.adc1_initial_delay),
            ),
            (
                "effective_delays",
                (timing.adc0_effective_delay, timing.adc1_effective_delay),
            ),
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

    @classmethod
    def for_rate_profile(
        cls,
        profile: RateProfile | int,
        **evidence: Any,
    ) -> AdcTriggerMetadata:
        """Build exact schedule metadata while allowing measured evidence fields."""

        timing = RateProfileTiming.from_profile(profile)
        return cls(
            gpio_master_rate_hz=timing.gpio_sample_rate_hz,
            pair_rate_hz=timing.adc_pair_rate_hz,
            gpio_master_pit_load=timing.gpio_master_pit_load,
            pair_pit_load=timing.adc_pair_pit_load,
            predivider=timing.adc_etc_predivider,
            chain_length=timing.adc_etc_chain_length,
            initial_delays=(timing.adc0_initial_delay, timing.adc1_initial_delay),
            effective_delays=(
                timing.adc0_effective_delay,
                timing.adc1_effective_delay,
            ),
            phase_ipg_cycles=timing.adc1_phase_ipg_cycles,
            completion_expected_delta_cycles=(timing.completion_expected_dwt_cycles),
            **evidence,
        )

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
    ("ADC_CACHE_DMA_DISCARDS", "adc_cache_dma_discards"),
    ("ADC_CACHE_CPU_INVALIDATIONS", "adc_cache_cpu_invalidations"),
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
    adc_cache_dma_discards: int = 0
    adc_cache_cpu_invalidations: int = 0

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
    hardware_serial: int = 0
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
        try:
            timing = next(
                item
                for item in RATE_PROFILE_TIMINGS
                if item.adc_pair_rate_hz == self.pair_rate_hz
            )
        except StopIteration as exc:
            raise ValueError("ADC block pair rate is not an exact profile") from exc
        fixed_values = (
            ("timestamp_hz", self.timestamp_hz, constants.TIMESTAMP_HZ),
            ("pair_period_ticks", self.pair_period_ticks, timing.adc_pair_period_ticks),
            ("adc1_phase_ticks", self.adc1_phase_ticks, timing.adc1_phase_ticks),
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
        _unsigned("hardware_serial", self.hardware_serial, 32)
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
            hardware_serial=getattr(value, "hardware_serial", 0),
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
    aux_bank_mode: AuxBankMode = v2_constants.DEFAULT_AUX_BANK_MODE
    rate_profile: RateProfile = v2_constants.DEFAULT_RATE_PROFILE

    def __post_init__(self) -> None:
        if any(
            isinstance(value, bool)
            for value in (
                self.stream_mask,
                self.source,
                self.data_checksum_algorithm,
                self.aux_bank_mode,
                self.rate_profile,
            )
        ):
            raise ValueError("configuration contains an unknown enum value")
        try:
            stream_mask = constants.StreamMask(self.stream_mask)
            source = constants.Source(self.source)
            checksum = constants.ChecksumAlgorithm(self.data_checksum_algorithm)
            aux_bank_mode = AuxBankMode(self.aux_bank_mode)
            rate_profile = RateProfile(self.rate_profile)
        except (TypeError, ValueError) as exc:
            raise ValueError("configuration contains an unknown enum value") from exc
        object.__setattr__(self, "stream_mask", stream_mask)
        object.__setattr__(self, "source", source)
        object.__setattr__(self, "data_checksum_algorithm", checksum)
        object.__setattr__(self, "aux_bank_mode", aux_bank_mode)
        object.__setattr__(self, "rate_profile", rate_profile)
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
        if stream_mask == constants.StreamMask.NONE and (
            aux_bank_mode is not AuxBankMode.DISABLED
            or rate_profile is not v2_constants.DEFAULT_RATE_PROFILE
        ):
            raise ValueError("the zero-stream control profile cannot use v2 extensions")
        if aux_bank_mode is AuxBankMode.INPUT and not (
            stream_mask & constants.StreamMask.GPIO
        ):
            raise ValueError("auxiliary INPUT mode requires the GPIO stream")
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
            raise ValueError("data frames are exactly 4096 bytes")

    @property
    def is_control_only(self) -> bool:
        """Whether this is the Phase 03 zero-stream hardware profile."""

        return (
            self.stream_mask == constants.StreamMask.NONE
            and self.source is constants.Source.HARDWARE
        )

    @property
    def rate_timing(self) -> RateProfileTiming:
        """Return the generated exact timing record selected by this request."""

        return RateProfileTiming.from_profile(self.rate_profile)

    @property
    def gpio_layout(self) -> GPIOLayout:
        """Return the generated packed GPIO layout selected by this request."""

        return GPIOLayout.from_mode(self.aux_bank_mode)

    @property
    def adc_pair_rate_hz(self) -> int:
        return self.rate_timing.adc_pair_rate_hz

    @property
    def gpio_sample_rate_hz(self) -> int:
        return self.rate_timing.gpio_sample_rate_hz

    @property
    def protocol_version(self) -> int:
        """Select v1 only for the exact legacy default configuration."""

        return (
            constants.PROTOCOL_VERSION
            if self.aux_bank_mode is AuxBankMode.DISABLED
            and self.rate_profile is v2_constants.DEFAULT_RATE_PROFILE
            else v2_constants.PROTOCOL_VERSION
        )

    @property
    def uses_protocol_v2(self) -> bool:
        return self.protocol_version == v2_constants.PROTOCOL_VERSION

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

    def to_payload(self, *, protocol_version: int | None = None) -> bytes:
        """Encode the v1 or explicitly selected extended configuration body."""

        selected_version = (
            self.protocol_version if protocol_version is None else protocol_version
        )
        if selected_version == constants.PROTOCOL_VERSION:
            if self.uses_protocol_v2:
                raise ValueError("an auxiliary/rate extension cannot be encoded as v1")
            return _CONFIGURATION.pack(
                int(self.stream_mask),
                int(self.source),
                int(self.data_checksum_algorithm),
                0,
                self.data_frame_bytes,
            )
        if selected_version != v2_constants.PROTOCOL_VERSION:
            raise ValueError("configuration protocol version must be 1 or 2")
        return _CONFIGURATION_V2.pack(
            int(self.stream_mask),
            int(self.source),
            int(self.data_checksum_algorithm),
            int(self.aux_bank_mode),
            self.data_frame_bytes,
            self.adc_pair_rate_hz,
            self.gpio_sample_rate_hz,
        )

    @classmethod
    def from_payload(cls, payload: bytes | bytearray | memoryview) -> DAQConfiguration:
        """Decode the eight-byte CONFIGURE request/applied-configuration body."""

        payload_bytes = bytes(payload)
        if len(payload_bytes) == constants.CONFIGURE_REQUEST_PAYLOAD_SIZE:
            raw_streams, raw_source, raw_checksum, reserved, frame_bytes = (
                _CONFIGURATION.unpack(payload_bytes)
            )
            if reserved != 0:
                raise FrameValidationError("configuration reserved byte must be zero")
            aux_bank_mode = AuxBankMode.DISABLED
            rate_profile = v2_constants.DEFAULT_RATE_PROFILE
        elif len(payload_bytes) == v2_constants.CONFIGURE_REQUEST_PAYLOAD_SIZE:
            (
                raw_streams,
                raw_source,
                raw_checksum,
                raw_aux_bank_mode,
                frame_bytes,
                adc_pair_rate_hz,
                gpio_sample_rate_hz,
            ) = _CONFIGURATION_V2.unpack(payload_bytes)
            try:
                aux_bank_mode = AuxBankMode(raw_aux_bank_mode)
                rate_profile = RateProfileTiming.from_rates(
                    adc_pair_rate_hz,
                    gpio_sample_rate_hz,
                ).profile
            except (TypeError, ValueError) as exc:
                raise FrameValidationError(str(exc)) from exc
        else:
            raise FrameValidationError("configuration body must be eight or 16 bytes")
        try:
            return cls(
                stream_mask=constants.StreamMask(raw_streams),
                source=constants.Source(raw_source),
                data_checksum_algorithm=constants.ChecksumAlgorithm(raw_checksum),
                data_frame_bytes=frame_bytes,
                aux_bank_mode=aux_bank_mode,
                rate_profile=rate_profile,
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
    bank_count: int = 1
    aux_bank_mode: AuxBankMode = AuxBankMode.DISABLED
    selected_rate_profile: RateProfile = v2_constants.DEFAULT_RATE_PROFILE
    aux_electrically_unstimulated: bool = False
    aux_external_transition_checks_run: bool = False
    configured_rate_hz: int = constants.GPIO_SAMPLE_RATE_HZ
    aux_hardware_error_flags: int = 0
    aux_diagnostic_flags: int = 0
    aux_dma_samples_captured: int = 0
    aux_complete_samples_retained: int = 0
    aux_samples_analyzed: int = 0
    aux_stopped_partial_samples: int = 0
    aux_raw_word_and: int = 0
    aux_raw_word_or: int = 0
    aux_observed_transitions: int = 0
    aux_packed_value_and: int = 0
    aux_packed_value_or: int = 0
    aux_first_packed_value: int = 0
    aux_last_packed_value: int = 0
    gpr26_before: int = 0
    gpr26_configured: int = 0
    gpr26_after: int = 0
    gpio1_gdir_before: int = 0
    gpio1_gdir_configured: int = 0
    gpio1_gdir_after: int = 0
    gpio1_psr_before: int = 0
    gpio1_psr_configured: int = 0
    gpio1_psr_after: int = 0
    aux_dmamux_chcfg_configured: int = 0
    aux_dma_erq_configured: int = 0
    aux_dma_err_final: int = 0
    aux_tcd_citer_configured: int = 0
    aux_tcd_biter_configured: int = 0
    aux_tcd_csr_configured: int = 0
    aux_edma_priority_configured: int = 0
    cache_dma_discards: tuple[int, int] = (0, 0)
    cache_cpu_invalidations: tuple[int, int] = (0, 0)

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
        if self.bank_count not in (1, 2):
            raise ValueError("GPIO capture diagnostic bank count is invalid")
        if self.aux_external_transition_checks_run and (
            self.aux_electrically_unstimulated
        ):
            raise ValueError(
                "unstimulated auxiliary bank cannot claim transition validation"
            )

    @property
    def healthy(self) -> bool:
        return self.hardware_error_flags == constants.GpioCaptureError.NONE

    @classmethod
    def from_payload(
        cls, payload: bytes | bytearray | memoryview
    ) -> GpioCaptureDiagnosticResult:
        data = bytes(payload)
        if len(data) not in (
            constants.GPIO_CAPTURE_DIAGNOSTIC_RESPONSE_PAYLOAD_SIZE,
            v2_constants.GPIO_CAPTURE_DIAGNOSTIC_RESPONSE_PAYLOAD_SIZE,
        ):
            raise FrameValidationError("GPIO diagnostic payload size is invalid")
        c = (
            v2_constants
            if len(data) == v2_constants.GPIO_CAPTURE_DIAGNOSTIC_RESPONSE_PAYLOAD_SIZE
            else constants
        )
        _success_prefix(data, len(data))

        def u8(name: str) -> int:
            return data[getattr(c, f"GPIO_CAPTURE_DIAGNOSTIC_RESPONSE_{name}_OFFSET")]

        def u16(name: str) -> int:
            return struct.unpack_from(
                "<H",
                data,
                getattr(c, f"GPIO_CAPTURE_DIAGNOSTIC_RESPONSE_{name}_OFFSET"),
            )[0]

        def u32(name: str) -> int:
            return struct.unpack_from(
                "<I",
                data,
                getattr(c, f"GPIO_CAPTURE_DIAGNOSTIC_RESPONSE_{name}_OFFSET"),
            )[0]

        values: dict[str, object] = {
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
        if c is v2_constants:
            values.update(
                bank_count=u8("BANK_COUNT"),
                aux_bank_mode=AuxBankMode(u8("AUX_BANK_MODE")),
                selected_rate_profile=RateProfile(u8("SELECTED_RATE_PROFILE")),
                aux_electrically_unstimulated=bool(u8("AUX_ELECTRICALLY_UNSTIMULATED")),
                aux_external_transition_checks_run=bool(
                    u8("AUX_EXTERNAL_TRANSITION_CHECKS_RUN")
                ),
                aux_dma_samples_captured=struct.unpack_from(
                    "<Q",
                    data,
                    c.GPIO_CAPTURE_DIAGNOSTIC_RESPONSE_AUX_DMA_SAMPLES_CAPTURED_OFFSET,
                )[0],
                cache_dma_discards=(
                    u32("PRIMARY_CACHE_DMA_DISCARDS"),
                    u32("AUX_CACHE_DMA_DISCARDS"),
                ),
                cache_cpu_invalidations=(
                    u32("PRIMARY_CACHE_CPU_INVALIDATIONS"),
                    u32("AUX_CACHE_CPU_INVALIDATIONS"),
                ),
            )
            for field in (
                "configured_rate_hz",
                "aux_hardware_error_flags",
                "aux_diagnostic_flags",
                "aux_complete_samples_retained",
                "aux_samples_analyzed",
                "aux_stopped_partial_samples",
                "aux_raw_word_and",
                "aux_raw_word_or",
                "aux_observed_transitions",
                "gpr26_before",
                "gpr26_configured",
                "gpr26_after",
                "gpio1_gdir_before",
                "gpio1_gdir_configured",
                "gpio1_gdir_after",
                "gpio1_psr_before",
                "gpio1_psr_configured",
                "gpio1_psr_after",
                "aux_dmamux_chcfg_configured",
                "aux_dma_erq_configured",
                "aux_dma_err_final",
            ):
                values[field] = u32(field.upper())
            for field in (
                "aux_tcd_citer_configured",
                "aux_tcd_biter_configured",
                "aux_tcd_csr_configured",
            ):
                values[field] = u16(field.upper())
            for field in (
                "aux_packed_value_and",
                "aux_packed_value_or",
                "aux_first_packed_value",
                "aux_last_packed_value",
                "aux_edma_priority_configured",
            ):
                values[field] = u8(field.upper())
        try:
            return cls(**values)  # type: ignore[arg-type]
        except (TypeError, ValueError) as exc:
            raise FrameValidationError(str(exc)) from exc


@dataclass(frozen=True, slots=True)
class AuxiliaryInputMetadata:
    """Validated protocol-v2 mode, pin, timing, and provisional resource table."""

    selected_rate_profile: RateProfile = v2_constants.DEFAULT_RATE_PROFILE
    applied_aux_bank_mode: AuxBankMode = v2_constants.DEFAULT_AUX_BANK_MODE
    supported_rate_profiles: tuple[RateProfileTiming, ...] = RATE_PROFILE_TIMINGS
    supported_aux_bank_modes: tuple[AuxBankMode, ...] = tuple(AuxBankMode)
    gpio_item_bytes: int = 1
    primary_gpio_pins_by_bit: tuple[int, ...] = v2_constants.PRIMARY_GPIO_PINS_BY_BIT
    auxiliary_gpio_pins_by_bit: tuple[int, ...] = v2_constants.AUX_GPIO_PINS_BY_BIT
    primary_gpio_port_bits_by_wire_bit: tuple[int, ...] = (
        v2_constants.PRIMARY_GPIO_PORT_BITS_BY_WIRE_BIT
    )
    auxiliary_gpio_port_bits_by_wire_bit: tuple[int, ...] = (
        v2_constants.AUX_GPIO_PORT_BITS_BY_WIRE_BIT
    )
    primary_gpio_capture_mask: int = v2_constants.PRIMARY_GPIO_CAPTURE_MASK
    auxiliary_gpio_capture_mask: int = v2_constants.AUX_GPIO_CAPTURE_MASK
    primary_gpio_standard_port: int = v2_constants.PRIMARY_GPIO_STANDARD_PORT
    auxiliary_gpio_standard_port: int = v2_constants.AUX_GPIO_STANDARD_PORT
    primary_gpio_fast_port: int = v2_constants.PRIMARY_GPIO_FAST_PORT
    auxiliary_gpio_fast_port: int = v2_constants.AUX_GPIO_FAST_PORT
    primary_gpio_fast_select_gpr: int = v2_constants.PRIMARY_GPIO_FAST_SELECT_GPR
    auxiliary_gpio_fast_select_gpr: int = v2_constants.AUX_GPIO_FAST_SELECT_GPR
    primary_gpio_xbar_output: int = v2_constants.GPIO_XBAR_OUTPUT
    auxiliary_gpio_xbar_output: int = v2_constants.AUX_GPIO_XBAR_OUTPUT
    primary_gpio_dmamux_source: int = v2_constants.GPIO_DMAMUX_SOURCE
    auxiliary_gpio_dmamux_source: int = v2_constants.AUX_GPIO_DMAMUX_SOURCE
    primary_gpio_edma_channel: int = v2_constants.GPIO_EDMA_CHANNEL
    auxiliary_gpio_edma_channel: int = v2_constants.AUX_GPIO_EDMA_CHANNEL
    primary_gpio_edma_priority: int = 1
    auxiliary_gpio_edma_priority: int = v2_constants.AUX_GPIO_EDMA_PRIORITY
    adc_edma_priorities: tuple[int, int] = (3, 2)
    auxiliary_gpio_dma_irq_priority: int = constants.GPIO_DMA_IRQ_PRIORITY
    paired_gpio_xbar_input: int = v2_constants.GPIO_XBAR_INPUT
    paired_gpio_join_required: bool = v2_constants.PAIRED_GPIO_JOIN_REQUIRED
    primary_gpio_raw_ring_depth: int = v2_constants.GPIO_RAW_RING_DEPTH
    auxiliary_gpio_raw_ring_depth: int = v2_constants.AUX_GPIO_RAW_RING_DEPTH
    disabled_adc_pairs_per_frame: int = v2_constants.AUX_BANK_LAYOUTS[
        AuxBankMode.DISABLED
    ]["adc_items_per_frame"]
    disabled_gpio_samples_per_frame: int = v2_constants.AUX_BANK_LAYOUTS[
        AuxBankMode.DISABLED
    ]["gpio_items_per_frame"]
    input_adc_pairs_per_frame: int = v2_constants.AUX_BANK_LAYOUTS[AuxBankMode.INPUT][
        "adc_items_per_frame"
    ]
    input_gpio_samples_per_frame: int = v2_constants.AUX_BANK_LAYOUTS[
        AuxBankMode.INPUT
    ]["gpio_items_per_frame"]

    def __post_init__(self) -> None:
        try:
            selected_profile = RateProfile(self.selected_rate_profile)
            selected_mode = AuxBankMode(self.applied_aux_bank_mode)
        except (TypeError, ValueError) as exc:
            raise ValueError("auxiliary INFO contains an unknown mode/profile") from exc
        profiles = tuple(self.supported_rate_profiles)
        modes = tuple(self.supported_aux_bank_modes)
        if profiles != RATE_PROFILE_TIMINGS or modes != tuple(AuxBankMode):
            raise ValueError("auxiliary INFO omits or reorders a generated profile")
        object.__setattr__(self, "selected_rate_profile", selected_profile)
        object.__setattr__(self, "applied_aux_bank_mode", selected_mode)
        object.__setattr__(self, "supported_rate_profiles", profiles)
        object.__setattr__(self, "supported_aux_bank_modes", modes)

        exact_values = {
            "gpio_item_bytes": GPIOLayout.from_mode(selected_mode).item_bytes,
            "primary_gpio_pins_by_bit": v2_constants.PRIMARY_GPIO_PINS_BY_BIT,
            "auxiliary_gpio_pins_by_bit": v2_constants.AUX_GPIO_PINS_BY_BIT,
            "primary_gpio_port_bits_by_wire_bit": (
                v2_constants.PRIMARY_GPIO_PORT_BITS_BY_WIRE_BIT
            ),
            "auxiliary_gpio_port_bits_by_wire_bit": (
                v2_constants.AUX_GPIO_PORT_BITS_BY_WIRE_BIT
            ),
            "primary_gpio_capture_mask": v2_constants.PRIMARY_GPIO_CAPTURE_MASK,
            "auxiliary_gpio_capture_mask": v2_constants.AUX_GPIO_CAPTURE_MASK,
            "primary_gpio_standard_port": v2_constants.PRIMARY_GPIO_STANDARD_PORT,
            "auxiliary_gpio_standard_port": v2_constants.AUX_GPIO_STANDARD_PORT,
            "primary_gpio_fast_port": v2_constants.PRIMARY_GPIO_FAST_PORT,
            "auxiliary_gpio_fast_port": v2_constants.AUX_GPIO_FAST_PORT,
            "primary_gpio_fast_select_gpr": (v2_constants.PRIMARY_GPIO_FAST_SELECT_GPR),
            "auxiliary_gpio_fast_select_gpr": (v2_constants.AUX_GPIO_FAST_SELECT_GPR),
            "primary_gpio_xbar_output": v2_constants.GPIO_XBAR_OUTPUT,
            "auxiliary_gpio_xbar_output": v2_constants.AUX_GPIO_XBAR_OUTPUT,
            "primary_gpio_dmamux_source": v2_constants.GPIO_DMAMUX_SOURCE,
            "auxiliary_gpio_dmamux_source": v2_constants.AUX_GPIO_DMAMUX_SOURCE,
            "primary_gpio_edma_channel": v2_constants.GPIO_EDMA_CHANNEL,
            "auxiliary_gpio_edma_channel": v2_constants.AUX_GPIO_EDMA_CHANNEL,
            "primary_gpio_edma_priority": 1,
            "auxiliary_gpio_edma_priority": v2_constants.AUX_GPIO_EDMA_PRIORITY,
            "adc_edma_priorities": (3, 2),
            "auxiliary_gpio_dma_irq_priority": constants.GPIO_DMA_IRQ_PRIORITY,
            "paired_gpio_xbar_input": v2_constants.GPIO_XBAR_INPUT,
            "paired_gpio_join_required": True,
            "primary_gpio_raw_ring_depth": v2_constants.GPIO_RAW_RING_DEPTH,
            "auxiliary_gpio_raw_ring_depth": v2_constants.AUX_GPIO_RAW_RING_DEPTH,
            "disabled_adc_pairs_per_frame": v2_constants.AUX_BANK_LAYOUTS[
                AuxBankMode.DISABLED
            ]["adc_items_per_frame"],
            "disabled_gpio_samples_per_frame": v2_constants.AUX_BANK_LAYOUTS[
                AuxBankMode.DISABLED
            ]["gpio_items_per_frame"],
            "input_adc_pairs_per_frame": v2_constants.AUX_BANK_LAYOUTS[
                AuxBankMode.INPUT
            ]["adc_items_per_frame"],
            "input_gpio_samples_per_frame": v2_constants.AUX_BANK_LAYOUTS[
                AuxBankMode.INPUT
            ]["gpio_items_per_frame"],
        }
        for name, expected in exact_values.items():
            actual = getattr(self, name)
            if isinstance(expected, tuple):
                actual = tuple(actual)
                object.__setattr__(self, name, actual)
            if actual != expected:
                raise ValueError(f"auxiliary INFO {name} is contradictory")

    @property
    def selected_timing(self) -> RateProfileTiming:
        return RateProfileTiming.from_profile(self.selected_rate_profile)

    @property
    def active_layout(self) -> GPIOLayout:
        return GPIOLayout.from_mode(self.applied_aux_bank_mode)

    def supports_configuration(self, configuration: DAQConfiguration) -> bool:
        return configuration.aux_bank_mode in self.supported_aux_bank_modes and any(
            timing.profile is configuration.rate_profile
            for timing in self.supported_rate_profiles
        )


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
    auxiliary: AuxiliaryInputMetadata | None = None

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
            raise ValueError("supported checksum mask is incompatible")
        is_v2 = self.protocol_version == v2_constants.PROTOCOL_VERSION
        if is_v2 != (self.auxiliary is not None):
            raise ValueError("protocol version and auxiliary metadata disagree")
        known_capability_mask = (
            v2_constants.KNOWN_CAPABILITY_MASK
            if is_v2
            else constants.KNOWN_CAPABILITY_MASK
        )
        if int(capability_bits) & ~known_capability_mask:
            raise ValueError("capability mask contains reserved bits")
        if is_v2 and int(capability_bits) & int(
            v2_constants.Capability.AUXILIARY_INPUT_BANK
            | v2_constants.Capability.EXACT_RATE_PROFILES
        ) != int(
            v2_constants.Capability.AUXILIARY_INPUT_BANK
            | v2_constants.Capability.EXACT_RATE_PROFILES
        ):
            raise ValueError("protocol-v2 INFO omits auxiliary/rate capabilities")
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

        timing = (
            self.auxiliary.selected_timing
            if self.auxiliary is not None
            else RateProfileTiming.from_profile(v2_constants.DEFAULT_RATE_PROFILE)
        )
        layout = (
            self.auxiliary.active_layout
            if self.auxiliary is not None
            else GPIOLayout.from_mode(AuxBankMode.DISABLED)
        )
        expected_gpio_priority = 1 if layout.aux_bank_mode is AuxBankMode.INPUT else 0
        expected_adc_priorities = (
            (3, 2)
            if layout.aux_bank_mode is AuxBankMode.INPUT
            else constants.ADC_EDMA_PRIORITIES
        )
        expected_adc_ring_bytes = (
            ((layout.adc_payload_bytes + 31) // 32) * 32 * constants.ADC_DMA_RING_DEPTH
        )
        fixed_values = (
            (
                self.protocol_version,
                v2_constants.PROTOCOL_VERSION if is_v2 else constants.PROTOCOL_VERSION,
            ),
            (self.timestamp_hz, constants.TIMESTAMP_HZ),
            (self.data_frame_bytes, constants.DATA_FRAME_BYTES),
            (
                self.max_control_frame_bytes,
                v2_constants.MAX_CONTROL_FRAME_BYTES
                if is_v2
                else constants.MAX_CONTROL_FRAME_BYTES,
            ),
            (self.adc_pair_rate_hz, timing.adc_pair_rate_hz),
            (self.gpio_sample_rate_hz, timing.gpio_sample_rate_hz),
            (self.adc_pair_period_ticks, timing.adc_pair_period_ticks),
            (self.adc1_phase_ticks, timing.adc1_phase_ticks),
            (self.gpio_sample_period_ticks, timing.gpio_sample_period_ticks),
            (self.gpio_packed_width_bits, layout.packed_width_bits),
            (self.gpio_raw_ring_depth, constants.GPIO_RAW_RING_DEPTH),
            (self.gpio_packed_ring_depth, constants.GPIO_PACKED_RING_DEPTH),
            (
                self.gpio_raw_samples_per_buffer,
                layout.items_per_frame,
            ),
            (
                self.gpio_raw_ring_bytes,
                layout.items_per_frame
                * v2_constants.GPIO_RAW_WORD_BYTES_PER_BANK
                * constants.GPIO_RAW_RING_DEPTH,
            ),
            (self.gpio_packed_ring_bytes, constants.GPIO_PACKED_RING_BYTES),
            (self.gpio_packet_buffer_count, constants.GPIO_PACKET_BUFFER_COUNT),
            (self.gpio_pit_channel, constants.GPIO_PIT_CHANNEL),
            (self.gpio_xbar_input, constants.GPIO_XBAR_INPUT),
            (self.gpio_xbar_output, constants.GPIO_XBAR_OUTPUT),
            (self.gpio_edma_channel, constants.GPIO_EDMA_CHANNEL),
            (self.gpio_dmamux_source, constants.GPIO_DMAMUX_SOURCE),
            (self.gpio_edma_priority, expected_gpio_priority),
            (self.gpio_xbar_active_edge, constants.GPIO_XBAR_ACTIVE_EDGE),
            (self.data_payload_bytes, layout.adc_payload_bytes),
            (self.adc_pairs_per_frame, layout.adc_items_per_frame),
            (self.gpio_samples_per_frame, layout.items_per_frame),
            (
                self.frame_coverage_ticks,
                timing.frame_coverage_ticks(layout.aux_bank_mode),
            ),
            (self.adc_dma_ring_depth, constants.ADC_DMA_RING_DEPTH),
            (self.adc_pair_bytes, constants.ADC_PAIR_BYTES),
            (self.adc_dma_irq_priority, constants.ADC_DMA_IRQ_PRIORITY),
            (self.gpio_dma_irq_priority, constants.GPIO_DMA_IRQ_PRIORITY),
            (
                self.adc_pairs_per_buffer,
                layout.adc_items_per_frame,
            ),
            (self.adc_dma_ring_bytes, expected_adc_ring_bytes),
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
            raise ValueError("INFO capabilities are incompatible")
        if gpio_pin_map != constants.GPIO_PINS_BY_BIT:
            raise ValueError("GPIO bit order must remain D6 through D13")
        if (
            adc_edma_channels != constants.ADC_EDMA_CHANNELS
            or adc_edma_priorities != expected_adc_priorities
            or adc_dmamux_sources != constants.ADC_DMAMUX_SOURCES
        ):
            raise ValueError("ADC DMA route metadata is incompatible")

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
        if not self.supported_configuration_mask & configuration.profile:
            return False
        if configuration.uses_protocol_v2:
            return self.auxiliary is not None and self.auxiliary.supports_configuration(
                configuration
            )
        return True

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
        known_mask = (
            v2_constants.KNOWN_CAPABILITY_MASK
            if self.auxiliary is not None
            else constants.KNOWN_CAPABILITY_MASK
        )
        if int(selected) & ~known_mask:
            raise ValueError("capability contains a reserved bit")
        return self.capability_bits & selected == selected


def _pack_auxiliary_info(
    payload: bytearray,
    auxiliary: AuxiliaryInputMetadata,
) -> None:
    """Pack the generated protocol-v2 INFO extension."""

    c = v2_constants
    payload[c.INFO_RESPONSE_SUPPORTED_RATE_PROFILE_MASK_OFFSET] = sum(
        1 << int(timing.profile) for timing in auxiliary.supported_rate_profiles
    )
    payload[c.INFO_RESPONSE_SELECTED_RATE_PROFILE_OFFSET] = int(
        auxiliary.selected_rate_profile
    )
    payload[c.INFO_RESPONSE_SUPPORTED_AUX_BANK_MODE_MASK_OFFSET] = sum(
        1 << int(mode) for mode in auxiliary.supported_aux_bank_modes
    )
    payload[c.INFO_RESPONSE_APPLIED_AUX_BANK_MODE_OFFSET] = int(
        auxiliary.applied_aux_bank_mode
    )
    payload[c.INFO_RESPONSE_GPIO_ITEM_BYTES_OFFSET] = auxiliary.gpio_item_bytes
    payload[c.INFO_RESPONSE_AUX_GPIO_PIN_COUNT_OFFSET] = len(
        auxiliary.auxiliary_gpio_pins_by_bit
    )
    payload[c.INFO_RESPONSE_RATE_PROFILE_COUNT_OFFSET] = len(
        auxiliary.supported_rate_profiles
    )
    start = c.INFO_RESPONSE_AUX_GPIO_PIN_MAP_OFFSET
    payload[start : start + c.INFO_RESPONSE_AUX_GPIO_PIN_MAP_COUNT] = bytes(
        auxiliary.auxiliary_gpio_pins_by_bit
    )
    start = c.INFO_RESPONSE_AUX_GPIO_PORT_BITS_OFFSET
    payload[start : start + c.INFO_RESPONSE_AUX_GPIO_PORT_BITS_COUNT] = bytes(
        auxiliary.auxiliary_gpio_port_bits_by_wire_bit
    )
    for offset, value in (
        (
            c.INFO_RESPONSE_AUX_GPIO_STANDARD_PORT_OFFSET,
            auxiliary.auxiliary_gpio_standard_port,
        ),
        (c.INFO_RESPONSE_AUX_GPIO_FAST_PORT_OFFSET, auxiliary.auxiliary_gpio_fast_port),
        (
            c.INFO_RESPONSE_AUX_GPIO_FAST_SELECT_GPR_OFFSET,
            auxiliary.auxiliary_gpio_fast_select_gpr,
        ),
        (c.INFO_RESPONSE_GPIO_RAW_WORD_BYTES_OFFSET, c.GPIO_RAW_WORD_BYTES_PER_BANK),
        (
            c.INFO_RESPONSE_PRIMARY_GPIO_STANDARD_PORT_OFFSET,
            auxiliary.primary_gpio_standard_port,
        ),
        (
            c.INFO_RESPONSE_PRIMARY_GPIO_FAST_PORT_OFFSET,
            auxiliary.primary_gpio_fast_port,
        ),
        (
            c.INFO_RESPONSE_PRIMARY_GPIO_FAST_SELECT_GPR_OFFSET,
            auxiliary.primary_gpio_fast_select_gpr,
        ),
        (
            c.INFO_RESPONSE_PRIMARY_GPIO_EDMA_CHANNEL_OFFSET,
            auxiliary.primary_gpio_edma_channel,
        ),
        (
            c.INFO_RESPONSE_AUX_GPIO_EDMA_CHANNEL_OFFSET,
            auxiliary.auxiliary_gpio_edma_channel,
        ),
        (
            c.INFO_RESPONSE_PRIMARY_GPIO_DMAMUX_SOURCE_OFFSET,
            auxiliary.primary_gpio_dmamux_source,
        ),
        (
            c.INFO_RESPONSE_AUX_GPIO_DMAMUX_SOURCE_OFFSET,
            auxiliary.auxiliary_gpio_dmamux_source,
        ),
        (
            c.INFO_RESPONSE_PRIMARY_GPIO_XBAR_OUTPUT_OFFSET,
            auxiliary.primary_gpio_xbar_output,
        ),
        (
            c.INFO_RESPONSE_AUX_GPIO_XBAR_OUTPUT_OFFSET,
            auxiliary.auxiliary_gpio_xbar_output,
        ),
        (
            c.INFO_RESPONSE_PAIRED_GPIO_XBAR_INPUT_OFFSET,
            auxiliary.paired_gpio_xbar_input,
        ),
        (
            c.INFO_RESPONSE_AUX_GPIO_EDMA_PRIORITY_OFFSET,
            auxiliary.auxiliary_gpio_edma_priority,
        ),
        (
            c.INFO_RESPONSE_PRIMARY_GPIO_EDMA_PRIORITY_OFFSET,
            auxiliary.primary_gpio_edma_priority,
        ),
        (c.INFO_RESPONSE_ADC0_EDMA_PRIORITY_OFFSET, auxiliary.adc_edma_priorities[0]),
        (c.INFO_RESPONSE_ADC1_EDMA_PRIORITY_OFFSET, auxiliary.adc_edma_priorities[1]),
        (
            c.INFO_RESPONSE_AUX_GPIO_DMA_IRQ_PRIORITY_OFFSET,
            auxiliary.auxiliary_gpio_dma_irq_priority,
        ),
        (
            c.INFO_RESPONSE_PRIMARY_GPIO_RAW_RING_DEPTH_OFFSET,
            auxiliary.primary_gpio_raw_ring_depth,
        ),
        (
            c.INFO_RESPONSE_AUX_GPIO_RAW_RING_DEPTH_OFFSET,
            auxiliary.auxiliary_gpio_raw_ring_depth,
        ),
        (
            c.INFO_RESPONSE_PAIRED_GPIO_JOIN_REQUIRED_OFFSET,
            int(auxiliary.paired_gpio_join_required),
        ),
    ):
        payload[offset] = value
    struct.pack_into(
        "<I",
        payload,
        c.INFO_RESPONSE_AUX_GPIO_CAPTURE_MASK_OFFSET,
        auxiliary.auxiliary_gpio_capture_mask,
    )
    struct.pack_into(
        "<I",
        payload,
        c.INFO_RESPONSE_PRIMARY_GPIO_CAPTURE_MASK_OFFSET,
        auxiliary.primary_gpio_capture_mask,
    )
    struct.pack_into(
        "<HHHH",
        payload,
        c.INFO_RESPONSE_DISABLED_ADC_PAIRS_PER_FRAME_OFFSET,
        auxiliary.disabled_adc_pairs_per_frame,
        auxiliary.disabled_gpio_samples_per_frame,
        auxiliary.input_adc_pairs_per_frame,
        auxiliary.input_gpio_samples_per_frame,
    )
    for index, timing in enumerate(auxiliary.supported_rate_profiles):
        base = c.INFO_RESPONSE_RATE_PROFILES_OFFSET + (
            index * c.RATE_PROFILE_INFO_PAYLOAD_SIZE
        )
        payload[base + c.RATE_PROFILE_INFO_RATE_PROFILE_OFFSET] = int(timing.profile)
        payload[base + c.RATE_PROFILE_INFO_ADC_ETC_PREDIVIDER_OFFSET] = (
            timing.adc_etc_predivider
        )
        payload[base + c.RATE_PROFILE_INFO_ADC_ETC_CHAIN_LENGTH_OFFSET] = (
            timing.adc_etc_chain_length
        )
        for offset, value in (
            (c.RATE_PROFILE_INFO_ADC_PAIR_RATE_HZ_OFFSET, timing.adc_pair_rate_hz),
            (
                c.RATE_PROFILE_INFO_GPIO_SAMPLE_RATE_HZ_OFFSET,
                timing.gpio_sample_rate_hz,
            ),
            (
                c.RATE_PROFILE_INFO_COMPLETION_EXPECTED_DWT_CYCLES_OFFSET,
                timing.completion_expected_dwt_cycles,
            ),
            (
                c.RATE_PROFILE_INFO_DISABLED_FRAME_COVERAGE_TICKS_OFFSET,
                timing.disabled_frame_coverage_ticks,
            ),
            (
                c.RATE_PROFILE_INFO_INPUT_FRAME_COVERAGE_TICKS_OFFSET,
                timing.input_frame_coverage_ticks,
            ),
        ):
            struct.pack_into("<I", payload, base + offset, value)
        for offset, value in (
            (
                c.RATE_PROFILE_INFO_ADC_PAIR_PERIOD_TICKS_OFFSET,
                timing.adc_pair_period_ticks,
            ),
            (c.RATE_PROFILE_INFO_ADC1_PHASE_TICKS_OFFSET, timing.adc1_phase_ticks),
            (
                c.RATE_PROFILE_INFO_GPIO_SAMPLE_PERIOD_TICKS_OFFSET,
                timing.gpio_sample_period_ticks,
            ),
            (
                c.RATE_PROFILE_INFO_GPIO_MASTER_PIT_DIVIDER_OFFSET,
                timing.gpio_master_pit_divider,
            ),
            (
                c.RATE_PROFILE_INFO_GPIO_MASTER_PIT_LOAD_OFFSET,
                timing.gpio_master_pit_load,
            ),
            (
                c.RATE_PROFILE_INFO_ADC_PAIR_PIT_DIVIDER_OFFSET,
                timing.adc_pair_pit_divider,
            ),
            (c.RATE_PROFILE_INFO_ADC_PAIR_PIT_LOAD_OFFSET, timing.adc_pair_pit_load),
            (c.RATE_PROFILE_INFO_ADC0_INITIAL_DELAY_OFFSET, timing.adc0_initial_delay),
            (c.RATE_PROFILE_INFO_ADC1_INITIAL_DELAY_OFFSET, timing.adc1_initial_delay),
            (
                c.RATE_PROFILE_INFO_ADC0_EFFECTIVE_DELAY_OFFSET,
                timing.adc0_effective_delay,
            ),
            (
                c.RATE_PROFILE_INFO_ADC1_EFFECTIVE_DELAY_OFFSET,
                timing.adc1_effective_delay,
            ),
            (
                c.RATE_PROFILE_INFO_ADC1_PHASE_IPG_CYCLES_OFFSET,
                timing.adc1_phase_ipg_cycles,
            ),
        ):
            struct.pack_into("<H", payload, base + offset, value)


def _unpack_auxiliary_info(payload: bytes) -> AuxiliaryInputMetadata:
    """Decode and validate the generated protocol-v2 INFO extension."""

    c = v2_constants

    def byte(offset: int) -> int:
        return payload[offset]

    def u16_at(offset: int) -> int:
        return struct.unpack_from("<H", payload, offset)[0]

    def u32_at(offset: int) -> int:
        return struct.unpack_from("<I", payload, offset)[0]

    if payload[c.INFO_RESPONSE_SUPPORTED_RATE_PROFILE_MASK_OFFSET] != (
        c.SUPPORTED_RATE_PROFILE_MASK
    ) or payload[c.INFO_RESPONSE_SUPPORTED_AUX_BANK_MODE_MASK_OFFSET] != (
        c.SUPPORTED_AUX_BANK_MODE_MASK
    ):
        raise FrameValidationError("INFO auxiliary capability masks are invalid")
    if payload[c.INFO_RESPONSE_RATE_PROFILE_COUNT_OFFSET] != len(RateProfile):
        raise FrameValidationError("INFO rate-profile count is invalid")
    if payload[c.INFO_RESPONSE_AUX_GPIO_PIN_COUNT_OFFSET] != len(
        c.AUX_GPIO_PINS_BY_BIT
    ):
        raise FrameValidationError("INFO auxiliary GPIO pin count is invalid")
    if payload[c.INFO_RESPONSE_GPIO_RAW_WORD_BYTES_OFFSET] != (
        c.GPIO_RAW_WORD_BYTES_PER_BANK
    ):
        raise FrameValidationError("INFO GPIO raw-word width is invalid")
    for offset in (
        c.INFO_RESPONSE_RESERVED_9_OFFSET,
        c.INFO_RESPONSE_RESERVED_10_OFFSET,
        c.INFO_RESPONSE_RESERVED_11_OFFSET,
    ):
        if payload[offset] != 0:
            raise FrameValidationError("INFO auxiliary reserved byte must be zero")

    timings: list[RateProfileTiming] = []
    for index, expected_profile in enumerate(RateProfile):
        base = c.INFO_RESPONSE_RATE_PROFILES_OFFSET + (
            index * c.RATE_PROFILE_INFO_PAYLOAD_SIZE
        )
        if payload[base + c.RATE_PROFILE_INFO_RESERVED_OFFSET] != 0:
            raise FrameValidationError("INFO rate-profile reserved byte must be zero")
        try:
            profile = RateProfile(
                payload[base + c.RATE_PROFILE_INFO_RATE_PROFILE_OFFSET]
            )
        except ValueError as exc:
            raise FrameValidationError("INFO rate-profile ID is invalid") from exc
        if profile is not expected_profile:
            raise FrameValidationError("INFO rate-profile table order is invalid")

        timings.append(
            RateProfileTiming(
                profile=profile,
                adc_pair_rate_hz=u32_at(
                    base + c.RATE_PROFILE_INFO_ADC_PAIR_RATE_HZ_OFFSET
                ),
                gpio_sample_rate_hz=u32_at(
                    base + c.RATE_PROFILE_INFO_GPIO_SAMPLE_RATE_HZ_OFFSET
                ),
                adc_pair_period_ticks=u16_at(
                    base + c.RATE_PROFILE_INFO_ADC_PAIR_PERIOD_TICKS_OFFSET
                ),
                adc1_phase_ticks=u16_at(
                    base + c.RATE_PROFILE_INFO_ADC1_PHASE_TICKS_OFFSET
                ),
                gpio_sample_period_ticks=u16_at(
                    base + c.RATE_PROFILE_INFO_GPIO_SAMPLE_PERIOD_TICKS_OFFSET
                ),
                gpio_master_pit_divider=u16_at(
                    base + c.RATE_PROFILE_INFO_GPIO_MASTER_PIT_DIVIDER_OFFSET
                ),
                gpio_master_pit_load=u16_at(
                    base + c.RATE_PROFILE_INFO_GPIO_MASTER_PIT_LOAD_OFFSET
                ),
                adc_pair_pit_divider=u16_at(
                    base + c.RATE_PROFILE_INFO_ADC_PAIR_PIT_DIVIDER_OFFSET
                ),
                adc_pair_pit_load=u16_at(
                    base + c.RATE_PROFILE_INFO_ADC_PAIR_PIT_LOAD_OFFSET
                ),
                adc_etc_predivider=payload[
                    base + c.RATE_PROFILE_INFO_ADC_ETC_PREDIVIDER_OFFSET
                ],
                adc_etc_chain_length=payload[
                    base + c.RATE_PROFILE_INFO_ADC_ETC_CHAIN_LENGTH_OFFSET
                ],
                adc0_initial_delay=u16_at(
                    base + c.RATE_PROFILE_INFO_ADC0_INITIAL_DELAY_OFFSET
                ),
                adc1_initial_delay=u16_at(
                    base + c.RATE_PROFILE_INFO_ADC1_INITIAL_DELAY_OFFSET
                ),
                adc0_effective_delay=u16_at(
                    base + c.RATE_PROFILE_INFO_ADC0_EFFECTIVE_DELAY_OFFSET
                ),
                adc1_effective_delay=u16_at(
                    base + c.RATE_PROFILE_INFO_ADC1_EFFECTIVE_DELAY_OFFSET
                ),
                adc1_phase_ipg_cycles=u16_at(
                    base + c.RATE_PROFILE_INFO_ADC1_PHASE_IPG_CYCLES_OFFSET
                ),
                completion_expected_dwt_cycles=u32_at(
                    base + c.RATE_PROFILE_INFO_COMPLETION_EXPECTED_DWT_CYCLES_OFFSET
                ),
                disabled_frame_coverage_ticks=u32_at(
                    base + c.RATE_PROFILE_INFO_DISABLED_FRAME_COVERAGE_TICKS_OFFSET
                ),
                input_frame_coverage_ticks=u32_at(
                    base + c.RATE_PROFILE_INFO_INPUT_FRAME_COVERAGE_TICKS_OFFSET
                ),
            )
        )

    pin_start = c.INFO_RESPONSE_AUX_GPIO_PIN_MAP_OFFSET
    bit_start = c.INFO_RESPONSE_AUX_GPIO_PORT_BITS_OFFSET
    try:
        return AuxiliaryInputMetadata(
            selected_rate_profile=RateProfile(
                byte(c.INFO_RESPONSE_SELECTED_RATE_PROFILE_OFFSET)
            ),
            applied_aux_bank_mode=AuxBankMode(
                byte(c.INFO_RESPONSE_APPLIED_AUX_BANK_MODE_OFFSET)
            ),
            supported_rate_profiles=tuple(timings),
            gpio_item_bytes=byte(c.INFO_RESPONSE_GPIO_ITEM_BYTES_OFFSET),
            auxiliary_gpio_pins_by_bit=tuple(
                payload[pin_start : pin_start + c.INFO_RESPONSE_AUX_GPIO_PIN_MAP_COUNT]
            ),
            auxiliary_gpio_port_bits_by_wire_bit=tuple(
                payload[
                    bit_start : bit_start + c.INFO_RESPONSE_AUX_GPIO_PORT_BITS_COUNT
                ]
            ),
            auxiliary_gpio_capture_mask=u32_at(
                c.INFO_RESPONSE_AUX_GPIO_CAPTURE_MASK_OFFSET
            ),
            primary_gpio_capture_mask=u32_at(
                c.INFO_RESPONSE_PRIMARY_GPIO_CAPTURE_MASK_OFFSET
            ),
            auxiliary_gpio_standard_port=byte(
                c.INFO_RESPONSE_AUX_GPIO_STANDARD_PORT_OFFSET
            ),
            auxiliary_gpio_fast_port=byte(c.INFO_RESPONSE_AUX_GPIO_FAST_PORT_OFFSET),
            auxiliary_gpio_fast_select_gpr=byte(
                c.INFO_RESPONSE_AUX_GPIO_FAST_SELECT_GPR_OFFSET
            ),
            primary_gpio_standard_port=byte(
                c.INFO_RESPONSE_PRIMARY_GPIO_STANDARD_PORT_OFFSET
            ),
            primary_gpio_fast_port=byte(c.INFO_RESPONSE_PRIMARY_GPIO_FAST_PORT_OFFSET),
            primary_gpio_fast_select_gpr=byte(
                c.INFO_RESPONSE_PRIMARY_GPIO_FAST_SELECT_GPR_OFFSET
            ),
            primary_gpio_edma_channel=byte(
                c.INFO_RESPONSE_PRIMARY_GPIO_EDMA_CHANNEL_OFFSET
            ),
            auxiliary_gpio_edma_channel=byte(
                c.INFO_RESPONSE_AUX_GPIO_EDMA_CHANNEL_OFFSET
            ),
            primary_gpio_dmamux_source=byte(
                c.INFO_RESPONSE_PRIMARY_GPIO_DMAMUX_SOURCE_OFFSET
            ),
            auxiliary_gpio_dmamux_source=byte(
                c.INFO_RESPONSE_AUX_GPIO_DMAMUX_SOURCE_OFFSET
            ),
            primary_gpio_xbar_output=byte(
                c.INFO_RESPONSE_PRIMARY_GPIO_XBAR_OUTPUT_OFFSET
            ),
            auxiliary_gpio_xbar_output=byte(
                c.INFO_RESPONSE_AUX_GPIO_XBAR_OUTPUT_OFFSET
            ),
            paired_gpio_xbar_input=byte(c.INFO_RESPONSE_PAIRED_GPIO_XBAR_INPUT_OFFSET),
            auxiliary_gpio_edma_priority=byte(
                c.INFO_RESPONSE_AUX_GPIO_EDMA_PRIORITY_OFFSET
            ),
            primary_gpio_edma_priority=byte(
                c.INFO_RESPONSE_PRIMARY_GPIO_EDMA_PRIORITY_OFFSET
            ),
            adc_edma_priorities=(
                byte(c.INFO_RESPONSE_ADC0_EDMA_PRIORITY_OFFSET),
                byte(c.INFO_RESPONSE_ADC1_EDMA_PRIORITY_OFFSET),
            ),
            auxiliary_gpio_dma_irq_priority=byte(
                c.INFO_RESPONSE_AUX_GPIO_DMA_IRQ_PRIORITY_OFFSET
            ),
            primary_gpio_raw_ring_depth=byte(
                c.INFO_RESPONSE_PRIMARY_GPIO_RAW_RING_DEPTH_OFFSET
            ),
            auxiliary_gpio_raw_ring_depth=byte(
                c.INFO_RESPONSE_AUX_GPIO_RAW_RING_DEPTH_OFFSET
            ),
            paired_gpio_join_required=bool(
                byte(c.INFO_RESPONSE_PAIRED_GPIO_JOIN_REQUIRED_OFFSET)
            ),
            disabled_adc_pairs_per_frame=u16_at(
                c.INFO_RESPONSE_DISABLED_ADC_PAIRS_PER_FRAME_OFFSET
            ),
            disabled_gpio_samples_per_frame=u16_at(
                c.INFO_RESPONSE_DISABLED_GPIO_SAMPLES_PER_FRAME_OFFSET
            ),
            input_adc_pairs_per_frame=u16_at(
                c.INFO_RESPONSE_INPUT_ADC_PAIRS_PER_FRAME_OFFSET
            ),
            input_gpio_samples_per_frame=u16_at(
                c.INFO_RESPONSE_INPUT_GPIO_SAMPLES_PER_FRAME_OFFSET
            ),
        )
    except (TypeError, ValueError) as exc:
        raise FrameValidationError(str(exc)) from exc


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
    auxiliary: AuxiliaryInputMetadata | None = None

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
                aux_bank_mode=(
                    self.auxiliary.applied_aux_bank_mode
                    if self.auxiliary is not None
                    else AuxBankMode.DISABLED
                ),
                rate_profile=(
                    self.auxiliary.selected_rate_profile
                    if self.auxiliary is not None
                    else v2_constants.DEFAULT_RATE_PROFILE
                ),
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
            auxiliary=self.auxiliary,
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
            aux_bank_mode=(
                self.auxiliary.applied_aux_bank_mode
                if self.auxiliary is not None
                else AuxBankMode.DISABLED
            ),
            rate_profile=(
                self.auxiliary.selected_rate_profile
                if self.auxiliary is not None
                else v2_constants.DEFAULT_RATE_PROFILE
            ),
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

        payload = bytearray(
            v2_constants.INFO_RESPONSE_PAYLOAD_SIZE
            if self.auxiliary is not None
            else constants.INFO_RESPONSE_PAYLOAD_SIZE
        )
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
        if self.auxiliary is not None:
            _pack_auxiliary_info(payload, self.auxiliary)
        return bytes(payload)

    @classmethod
    def from_payload(cls, payload: bytes | bytearray | memoryview) -> DeviceInfo:
        """Decode a successful INFO response payload."""

        payload_bytes = bytes(payload)
        if len(payload_bytes) == v2_constants.INFO_RESPONSE_PAYLOAD_SIZE:
            expected_size = v2_constants.INFO_RESPONSE_PAYLOAD_SIZE
            auxiliary = _unpack_auxiliary_info(payload_bytes)
        elif len(payload_bytes) == constants.INFO_RESPONSE_PAYLOAD_SIZE:
            expected_size = constants.INFO_RESPONSE_PAYLOAD_SIZE
            auxiliary = None
        else:
            raise FrameValidationError(
                "INFO payload must use the generated v1 or v2 size"
            )
        _success_prefix(payload_bytes, expected_size)
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
            auxiliary=auxiliary,
            **_unpack_adc_metadata(payload_bytes, "INFO_RESPONSE"),
        )


# ``Info`` remains as the concise Phase 01 spelling.
Info = DeviceInfo


@dataclass(frozen=True, slots=True)
class AuxiliaryGPIOStatus:
    """Protocol-v2 per-bank DMA and pairing-barrier telemetry."""

    gpio_item_bytes: int = 1
    adc_pair_rate_hz: int = v2_constants.ADC_PAIR_RATE_HZ
    gpio_sample_rate_hz: int = v2_constants.GPIO_SAMPLE_RATE_HZ
    frame_coverage_ticks: int = v2_constants.FRAME_COVERAGE_TICKS
    packet_retention_us_combined: int = 0
    packet_retention_us_single_stream: int = 0
    bank_major_loops: tuple[int, int] = (0, 0)
    bank_samples_captured: tuple[int, int] = (0, 0)
    bank_ring_overruns: tuple[int, int] = (0, 0)
    bank_stale_completions: tuple[int, int] = (0, 0)
    ready_depth: tuple[int, int] = (0, 0)
    ready_high_water: tuple[int, int] = (0, 0)
    paired_major_loops: int = 0
    buffers_completed: int = 0
    buffers_acquired: int = 0
    buffers_released: int = 0
    samples_captured: int = 0
    samples_joined: int = 0
    samples_delivered: int = 0
    samples_lost: int = 0
    raw_ring_overruns: int = 0
    generation_skew_events: int = 0
    generation_skew_samples: int = 0
    canceled_generations: int = 0
    cancellation_samples: int = 0
    stop_tail_samples: int = 0
    timestamp_mismatches: int = 0
    count_mismatches: int = 0
    destination_mismatches: int = 0
    schedule_exhaustions: int = 0
    stale_completions: int = 0
    cache_dma_discards: int = 0
    cache_cpu_invalidations: int = 0
    hardware_errors: int = 0
    invariant_errors: int = 0
    resource_conflicts: int = 0
    start_errors: int = 0
    stop_errors: int = 0
    stale_dma_completions: int = 0


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
    packet_pressure_evictions: int = 0
    packet_capacity_drops_without_evictable_frame: int = 0
    adc_frames_evicted: int = 0
    adc_frames_evicted_after_promotion: int = 0
    gpio_frames_evicted: int = 0
    gpio_frames_evicted_after_promotion: int = 0
    adc_frames_dropped_after_framing: int = 0
    adc_frames_dropped_after_promotion: int = 0
    gpio_frames_dropped_after_framing: int = 0
    gpio_frames_dropped_after_promotion: int = 0
    gpio_buffers_completed: int = 0
    gpio_buffers_acquired: int = 0
    gpio_buffers_released: int = 0
    gpio_samples_delivered: int = 0
    gpio_stop_samples_discarded: int = 0
    gpio_frames_produced: int = 0
    gpio_samples_produced: int = 0
    gpio_frames_packed: int = 0
    gpio_duplicate_samples_ignored: int = 0
    adc_frames_consumed: int = 0
    adc_pairs_consumed: int = 0
    adc_raw_gap_pairs: int = 0
    adc_raw_drop_pairs_projected: int = 0
    gpio_raw_drop_samples_projected: int = 0
    gpio_packer_drop_samples_projected: int = 0
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
    gpio_cache_dma_discards: int = 0
    gpio_cache_cpu_invalidations: int = 0
    bad_flags: int = 0
    bad_payloads: int = 0
    bad_request_ids: int = 0
    responses_queued: int = 0
    responses_completed: int = 0
    response_queue_rejections: int = 0
    response_reservations_abandoned: int = 0
    usb_command_queue_depth: int = 0
    usb_response_queue_depth: int = 0
    usb_lower_priority_queue_depth: int = 0
    usb_command_queue_high_water: int = 0
    usb_response_queue_high_water: int = 0
    usb_active_frame_bytes_sent: int = 0
    packet_owned_depth: int = 0
    usb_active_frame_size: int = 0
    adc_packet_filling_depth: int = 0
    gpio_packet_filling_depth: int = 0
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
    adc_cache_dma_discards: int = 0
    adc_cache_cpu_invalidations: int = 0
    configuration: DAQConfiguration | None = None
    auxiliary_gpio: AuxiliaryGPIOStatus | None = None

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
        if self.configuration is not None:
            if not isinstance(self.configuration, DAQConfiguration):
                raise TypeError("status configuration must be DAQConfiguration or None")
            if (
                self.configuration.stream_mask != stream_mask
                or self.configuration.source is not source
                or self.configuration.data_checksum_algorithm is not checksum
                or self.configuration.data_frame_bytes != self.data_frame_bytes
            ):
                raise ValueError("status fields contradict the applied configuration")
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
            "packet_owned_depth": constants.PACKET_BUFFER_COUNT,
            "usb_active_frame_size": constants.DATA_FRAME_BYTES,
            "adc_packet_filling_depth": constants.PACKET_BUFFER_COUNT,
            "gpio_packet_filling_depth": constants.PACKET_BUFFER_COUNT,
        }
        for name in _STATUS_QUEUE_U16_FIELDS:
            _unsigned(name, getattr(self, name), 16)
            if getattr(self, name) > extended_depth_limits[name]:
                raise ValueError(f"{name} exceeds its advertised capacity")
        current_high_water_pairs = (
            ("gpio_raw_ready_depth", "gpio_raw_ready_high_water"),
            ("gpio_packed_ready_depth", "gpio_packed_ready_high_water"),
            ("packet_ready_depth", "packet_ready_high_water"),
            ("packet_transmit_depth", "packet_transmit_high_water"),
            ("packet_owned_depth", "packet_owned_high_water"),
            ("adc_packet_ready_depth", "adc_packet_ready_high_water"),
            ("gpio_packet_ready_depth", "gpio_packet_ready_high_water"),
            ("adc_packet_transmit_depth", "adc_packet_transmit_high_water"),
            ("gpio_packet_transmit_depth", "gpio_packet_transmit_high_water"),
            ("usb_command_queue_depth", "usb_command_queue_high_water"),
            ("usb_response_queue_depth", "usb_response_queue_high_water"),
        )
        for current_name, high_water_name in current_high_water_pairs:
            if getattr(self, current_name) > getattr(self, high_water_name):
                raise ValueError(f"{current_name} exceeds {high_water_name}")
        if self.packet_ready_depth != (
            self.adc_packet_ready_depth + self.gpio_packet_ready_depth
        ):
            raise ValueError("per-source packet-ready depths do not sum to total")
        if self.packet_transmit_depth != (
            self.adc_packet_transmit_depth + self.gpio_packet_transmit_depth
        ):
            raise ValueError("per-source packet-transmit depths do not sum to total")
        if self.packet_owned_depth != (
            self.packet_ready_depth
            + self.packet_transmit_depth
            + self.adc_packet_filling_depth
            + self.gpio_packet_filling_depth
        ):
            raise ValueError("packet ownership states do not sum to owned depth")
        if self.usb_lower_priority_queue_depth != self.packet_transmit_depth:
            raise ValueError("USB and packet transmit depths disagree")
        if self.usb_active_frame_bytes_sent > self.usb_active_frame_size:
            raise ValueError("USB active-frame progress exceeds frame size")
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
            adc_cache_dma_discards=self.adc_cache_dma_discards,
            adc_cache_cpu_invalidations=self.adc_cache_cpu_invalidations,
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

    def to_payload(
        self, *, protocol_version: int = constants.PROTOCOL_VERSION
    ) -> bytes:
        """Encode a successful STATUS response with ADC initialization state."""

        use_v2 = protocol_version == v2_constants.PROTOCOL_VERSION
        payload = bytearray(
            v2_constants.STATUS_RESPONSE_PAYLOAD_SIZE
            if use_v2
            else constants.STATUS_RESPONSE_PAYLOAD_SIZE
        )
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
        if use_v2:
            configuration = self.configuration or DAQConfiguration(
                stream_mask=self.stream_mask,
                source=self.source,
                data_checksum_algorithm=self.data_checksum_algorithm,
            )
            timing = configuration.rate_timing
            layout = configuration.gpio_layout
            auxiliary = self.auxiliary_gpio or AuxiliaryGPIOStatus(
                bank_major_loops=(
                    self.gpio_dma_major_loops,
                    self.gpio_dma_major_loops,
                ),
                bank_samples_captured=(
                    self.gpio_samples_captured,
                    self.gpio_samples_captured,
                ),
                bank_ring_overruns=(
                    self.gpio_raw_ring_overruns,
                    self.gpio_raw_ring_overruns,
                ),
                bank_stale_completions=(
                    self.gpio_stale_dma_completions,
                    self.gpio_stale_dma_completions,
                ),
                ready_depth=(self.gpio_raw_ready_depth,) * 2,
                ready_high_water=(self.gpio_raw_ready_high_water,) * 2,
                paired_major_loops=self.gpio_dma_major_loops,
                buffers_completed=self.gpio_buffers_completed,
                buffers_acquired=self.gpio_buffers_acquired,
                buffers_released=self.gpio_buffers_released,
                samples_captured=self.gpio_samples_captured,
                samples_joined=self.gpio_samples_packed,
                samples_delivered=self.gpio_samples_delivered,
                samples_lost=self.gpio_raw_samples_lost,
                raw_ring_overruns=self.gpio_raw_ring_overruns,
                stop_tail_samples=self.gpio_stop_samples_discarded,
                stale_completions=self.gpio_stale_dma_completions,
                cache_dma_discards=self.gpio_cache_dma_discards,
                cache_cpu_invalidations=self.gpio_cache_cpu_invalidations,
                hardware_errors=self.gpio_hardware_errors,
                invariant_errors=self.gpio_raw_invariant_errors,
                resource_conflicts=self.gpio_resource_conflicts,
                start_errors=self.gpio_start_errors,
                stop_errors=self.gpio_stop_errors,
                stale_dma_completions=self.gpio_stale_dma_completions,
            )
            c = v2_constants
            payload[c.STATUS_RESPONSE_PROTOCOL_VERSION_OFFSET] = c.PROTOCOL_VERSION
            payload[c.STATUS_RESPONSE_AUX_BANK_MODE_OFFSET] = int(
                configuration.aux_bank_mode
            )
            payload[c.STATUS_RESPONSE_RATE_PROFILE_OFFSET] = int(
                configuration.rate_profile
            )
            payload[c.STATUS_RESPONSE_GPIO_ITEM_BYTES_OFFSET] = layout.item_bytes
            struct.pack_into(
                "<IIIIIHHHH",
                payload,
                c.STATUS_RESPONSE_ADC_PAIR_RATE_HZ_OFFSET,
                timing.adc_pair_rate_hz,
                timing.gpio_sample_rate_hz,
                timing.frame_coverage_ticks(configuration.aux_bank_mode),
                timing.frame_coverage_ticks(configuration.aux_bank_mode)
                * constants.PACKET_BUFFER_COUNT
                // 2
                // (constants.TIMESTAMP_HZ // 1_000_000),
                timing.frame_coverage_ticks(configuration.aux_bank_mode)
                * constants.PACKET_BUFFER_COUNT
                // (constants.TIMESTAMP_HZ // 1_000_000),
                *auxiliary.ready_depth,
                *auxiliary.ready_high_water,
            )
            values64 = (
                *auxiliary.bank_major_loops,
                *auxiliary.bank_samples_captured,
                auxiliary.paired_major_loops,
                auxiliary.buffers_completed,
                auxiliary.buffers_acquired,
                auxiliary.buffers_released,
                auxiliary.samples_captured,
                auxiliary.samples_joined,
                auxiliary.samples_delivered,
                auxiliary.samples_lost,
                auxiliary.raw_ring_overruns,
                auxiliary.generation_skew_events,
                auxiliary.generation_skew_samples,
                auxiliary.canceled_generations,
                auxiliary.cancellation_samples,
                auxiliary.stop_tail_samples,
            )
            struct.pack_into(
                "<" + "Q" * len(values64),
                payload,
                c.STATUS_RESPONSE_PRIMARY_GPIO_DMA_MAJOR_LOOPS_OFFSET,
                *values64,
            )
            values32 = (
                auxiliary.timestamp_mismatches,
                auxiliary.count_mismatches,
                auxiliary.destination_mismatches,
                auxiliary.schedule_exhaustions,
                auxiliary.stale_completions,
                auxiliary.cache_dma_discards,
                auxiliary.cache_cpu_invalidations,
                auxiliary.hardware_errors,
                auxiliary.invariant_errors,
                auxiliary.resource_conflicts,
                auxiliary.start_errors,
                auxiliary.stop_errors,
                auxiliary.stale_dma_completions,
            )
            struct.pack_into(
                "<" + "I" * len(values32),
                payload,
                c.STATUS_RESPONSE_PAIRED_GPIO_TIMESTAMP_MISMATCHES_OFFSET,
                *values32,
            )
            struct.pack_into(
                "<IIII",
                payload,
                c.STATUS_RESPONSE_PRIMARY_GPIO_RAW_RING_OVERRUNS_OFFSET,
                *auxiliary.bank_ring_overruns,
                *auxiliary.bank_stale_completions,
            )
        return bytes(payload)

    @classmethod
    def from_payload(cls, payload: bytes | bytearray | memoryview) -> Status:
        """Decode a successful STATUS response payload."""

        payload_bytes = bytes(payload)
        if len(payload_bytes) not in (
            constants.STATUS_RESPONSE_PAYLOAD_SIZE,
            v2_constants.STATUS_RESPONSE_PAYLOAD_SIZE,
        ):
            raise ValueError("STATUS payload has an unsupported size")
        _success_prefix(payload_bytes, len(payload_bytes))
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
        configuration = None
        auxiliary_gpio = None
        if len(payload_bytes) == v2_constants.STATUS_RESPONSE_PAYLOAD_SIZE:
            configuration = DAQConfiguration(
                stream_mask=constants.StreamMask(
                    payload_bytes[constants.STATUS_RESPONSE_STREAM_MASK_OFFSET]
                ),
                source=constants.Source(
                    payload_bytes[constants.STATUS_RESPONSE_SOURCE_OFFSET]
                ),
                data_checksum_algorithm=constants.ChecksumAlgorithm(
                    payload_bytes[
                        constants.STATUS_RESPONSE_DATA_CHECKSUM_ALGORITHM_OFFSET
                    ]
                ),
                aux_bank_mode=AuxBankMode(
                    payload_bytes[v2_constants.STATUS_RESPONSE_AUX_BANK_MODE_OFFSET]
                ),
                rate_profile=RateProfile(
                    payload_bytes[v2_constants.STATUS_RESPONSE_RATE_PROFILE_OFFSET]
                ),
            )
            c = v2_constants
            values64 = struct.unpack_from(
                "<" + "Q" * 18,
                payload_bytes,
                c.STATUS_RESPONSE_PRIMARY_GPIO_DMA_MAJOR_LOOPS_OFFSET,
            )
            values32 = struct.unpack_from(
                "<" + "I" * 13,
                payload_bytes,
                c.STATUS_RESPONSE_PAIRED_GPIO_TIMESTAMP_MISMATCHES_OFFSET,
            )
            bank_tail = struct.unpack_from(
                "<IIII",
                payload_bytes,
                c.STATUS_RESPONSE_PRIMARY_GPIO_RAW_RING_OVERRUNS_OFFSET,
            )
            auxiliary_gpio = AuxiliaryGPIOStatus(
                gpio_item_bytes=payload_bytes[c.STATUS_RESPONSE_GPIO_ITEM_BYTES_OFFSET],
                adc_pair_rate_hz=struct.unpack_from(
                    "<I", payload_bytes, c.STATUS_RESPONSE_ADC_PAIR_RATE_HZ_OFFSET
                )[0],
                gpio_sample_rate_hz=struct.unpack_from(
                    "<I", payload_bytes, c.STATUS_RESPONSE_GPIO_SAMPLE_RATE_HZ_OFFSET
                )[0],
                frame_coverage_ticks=struct.unpack_from(
                    "<I", payload_bytes, c.STATUS_RESPONSE_FRAME_COVERAGE_TICKS_OFFSET
                )[0],
                packet_retention_us_combined=struct.unpack_from(
                    "<I",
                    payload_bytes,
                    c.STATUS_RESPONSE_PACKET_RETENTION_US_COMBINED_OFFSET,
                )[0],
                packet_retention_us_single_stream=struct.unpack_from(
                    "<I",
                    payload_bytes,
                    c.STATUS_RESPONSE_PACKET_RETENTION_US_SINGLE_STREAM_OFFSET,
                )[0],
                bank_major_loops=(values64[0], values64[1]),
                bank_samples_captured=(values64[2], values64[3]),
                paired_major_loops=values64[4],
                buffers_completed=values64[5],
                buffers_acquired=values64[6],
                buffers_released=values64[7],
                samples_captured=values64[8],
                samples_joined=values64[9],
                samples_delivered=values64[10],
                samples_lost=values64[11],
                raw_ring_overruns=values64[12],
                generation_skew_events=values64[13],
                generation_skew_samples=values64[14],
                canceled_generations=values64[15],
                cancellation_samples=values64[16],
                stop_tail_samples=values64[17],
                timestamp_mismatches=values32[0],
                count_mismatches=values32[1],
                destination_mismatches=values32[2],
                schedule_exhaustions=values32[3],
                stale_completions=values32[4],
                cache_dma_discards=values32[5],
                cache_cpu_invalidations=values32[6],
                hardware_errors=values32[7],
                invariant_errors=values32[8],
                resource_conflicts=values32[9],
                start_errors=values32[10],
                stop_errors=values32[11],
                stale_dma_completions=values32[12],
                bank_ring_overruns=(bank_tail[0], bank_tail[1]),
                bank_stale_completions=(bank_tail[2], bank_tail[3]),
                ready_depth=struct.unpack_from(
                    "<HH",
                    payload_bytes,
                    c.STATUS_RESPONSE_PRIMARY_GPIO_RAW_READY_DEPTH_OFFSET,
                ),
                ready_high_water=struct.unpack_from(
                    "<HH",
                    payload_bytes,
                    c.STATUS_RESPONSE_PRIMARY_GPIO_RAW_READY_HIGH_WATER_OFFSET,
                ),
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
            configuration=configuration,
            auxiliary_gpio=auxiliary_gpio,
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
    packet_pressure_evictions: int = 0
    packet_capacity_drops_without_evictable_frame: int = 0
    adc_frames_evicted: int = 0
    adc_frames_evicted_after_promotion: int = 0
    gpio_frames_evicted: int = 0
    gpio_frames_evicted_after_promotion: int = 0
    adc_frames_dropped_after_framing: int = 0
    adc_frames_dropped_after_promotion: int = 0
    gpio_frames_dropped_after_framing: int = 0
    gpio_frames_dropped_after_promotion: int = 0
    gpio_buffers_completed: int = 0
    gpio_buffers_acquired: int = 0
    gpio_buffers_released: int = 0
    gpio_samples_delivered: int = 0
    gpio_stop_samples_discarded: int = 0
    gpio_frames_produced: int = 0
    gpio_samples_produced: int = 0
    gpio_frames_packed: int = 0
    gpio_duplicate_samples_ignored: int = 0
    adc_frames_consumed: int = 0
    adc_pairs_consumed: int = 0
    adc_raw_gap_pairs: int = 0
    adc_raw_drop_pairs_projected: int = 0
    gpio_raw_drop_samples_projected: int = 0
    gpio_packer_drop_samples_projected: int = 0
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
    gpio_cache_dma_discards: int = 0
    gpio_cache_cpu_invalidations: int = 0
    bad_flags: int = 0
    bad_payloads: int = 0
    bad_request_ids: int = 0
    responses_queued: int = 0
    responses_completed: int = 0
    response_queue_rejections: int = 0
    response_reservations_abandoned: int = 0
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
    adc_cache_dma_discards: int = 0
    adc_cache_cpu_invalidations: int = 0

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
    adc_block_queue_drops: int = 0
    gpio_block_queue_drops: int = 0
    adc_item_queue_drops: int = 0
    gpio_item_queue_drops: int = 0
    loss_report_queue_drops: int = 0

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
    observed_host_queue_losses: int = 0
    observed_stream_anomalies: int = 0
    protocol_telemetry_errors: int = 0
    telemetry_errors: tuple[str, ...] = ()

    def __post_init__(self) -> None:
        if not isinstance(self.firmware, FirmwareCounters):
            raise TypeError("firmware must be FirmwareCounters")
        if not isinstance(self.host, HostCounters):
            raise TypeError("host must be HostCounters")
        _nonnegative("observed_stream_gaps", self.observed_stream_gaps)
        _nonnegative("observed_host_queue_losses", self.observed_host_queue_losses)
        _nonnegative("observed_stream_anomalies", self.observed_stream_anomalies)
        _nonnegative("protocol_telemetry_errors", self.protocol_telemetry_errors)
        errors = tuple(self.telemetry_errors)
        if any(not isinstance(error, str) or not error for error in errors):
            raise ValueError("telemetry_errors must contain nonempty strings")
        object.__setattr__(self, "telemetry_errors", errors)

    @property
    def has_loss(self) -> bool:
        return (
            self.firmware.has_loss
            or self.host.has_queue_loss
            or self.observed_stream_gaps > 0
            or self.observed_host_queue_losses > 0
            or self.observed_stream_anomalies > 0
            or self.protocol_telemetry_errors > 0
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
    """One ADC frame; each logical item is an ADC0/ADC1 sample pair."""

    run_id: int
    sequence: int
    first_sample_ticks: int
    payload: bytes
    flags: constants.FrameFlag = constants.FrameFlag.NONE
    checksum_algorithm: constants.ChecksumAlgorithm = (
        constants.DEFAULT_CHECKSUM_ALGORITHM
    )
    metadata: AdcBlockMetadata = dataclass_field(default_factory=AdcBlockMetadata)
    aux_bank_mode: AuxBankMode = AuxBankMode.DISABLED
    rate_profile: RateProfile = v2_constants.DEFAULT_RATE_PROFILE
    protocol_version: int = constants.PROTOCOL_VERSION
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
        if isinstance(self.aux_bank_mode, bool) or isinstance(self.rate_profile, bool):
            raise TypeError("ADC block mode/rate metadata is invalid")
        try:
            mode = AuxBankMode(self.aux_bank_mode)
            profile = RateProfile(self.rate_profile)
        except (TypeError, ValueError) as exc:
            raise ValueError("ADC block mode/rate metadata is invalid") from exc
        if self.protocol_version not in {
            constants.PROTOCOL_VERSION,
            v2_constants.PROTOCOL_VERSION,
        } or isinstance(self.protocol_version, bool):
            raise ValueError("ADC block protocol version must be 1 or 2")
        if self.protocol_version == constants.PROTOCOL_VERSION and (
            mode is not AuxBankMode.DISABLED
            or profile is not v2_constants.DEFAULT_RATE_PROFILE
        ):
            raise ValueError("protocol-v1 ADC blocks require the legacy layout/rate")
        object.__setattr__(self, "aux_bank_mode", mode)
        object.__setattr__(self, "rate_profile", profile)
        layout = GPIOLayout.from_mode(mode)
        if len(payload) != layout.adc_payload_bytes:
            if mode is AuxBankMode.DISABLED:
                raise ValueError("ADC blocks require exactly 1012 sample pairs")
            raise ValueError(
                "ADC blocks in INPUT mode require exactly 506 sample pairs"
            )
        if not isinstance(self.metadata, AdcBlockMetadata):
            raise TypeError("ADC block metadata must be AdcBlockMetadata")
        timing = RateProfileTiming.from_profile(profile)
        if (
            self.metadata.pair_rate_hz != timing.adc_pair_rate_hz
            or self.metadata.pair_period_ticks != timing.adc_pair_period_ticks
            or self.metadata.adc1_phase_ticks != timing.adc1_phase_ticks
        ):
            raise ValueError("ADC block metadata disagrees with its rate profile")
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

    @classmethod
    def from_v2_frame(
        cls,
        frame: V2Frame,
        configuration: DAQConfiguration,
    ) -> ADCBlock:
        """Decode a v2 ADC frame using its already-negotiated exact profile."""

        if int(frame.header.kind) != int(constants.FrameKind.ADC_DATA):
            raise TypeError("frame is not ADC_DATA")
        if not isinstance(configuration, DAQConfiguration):
            raise TypeError("configuration must be DAQConfiguration")
        layout = configuration.gpio_layout
        timing = configuration.rate_timing
        if frame.header.item_count != layout.adc_items_per_frame:
            raise FrameValidationError(
                "protocol-v2 ADC item count disagrees with negotiated layout"
            )
        if frame.header.first_sample_ticks % timing.adc_pair_period_ticks:
            raise FrameValidationError(
                "protocol-v2 ADC timestamp disagrees with selected period"
            )
        source = (
            constants.Source.SYNTHETIC
            if int(frame.header.flags) & int(constants.FrameFlag.SYNTHETIC)
            else constants.Source.HARDWARE
        )
        return cls(
            run_id=frame.header.run_id,
            sequence=frame.header.sequence,
            first_sample_ticks=frame.header.first_sample_ticks,
            payload=frame.payload,
            flags=constants.FrameFlag(int(frame.header.flags)),
            checksum_algorithm=constants.ChecksumAlgorithm(
                int(frame.header.checksum_algorithm)
            ),
            metadata=AdcBlockMetadata(
                source=source,
                pair_rate_hz=timing.adc_pair_rate_hz,
                pair_period_ticks=timing.adc_pair_period_ticks,
                adc1_phase_ticks=timing.adc1_phase_ticks,
                trigger=AdcTriggerMetadata.for_rate_profile(configuration.rate_profile),
            ),
            aux_bank_mode=configuration.aux_bank_mode,
            rate_profile=configuration.rate_profile,
            protocol_version=v2_constants.PROTOCOL_VERSION,
        )

    @property
    def data_checksum_algorithm(self) -> constants.ChecksumAlgorithm:
        """The exact algorithm that validated this frame's trailer."""

        return self.checksum_algorithm

    @property
    def item_count(self) -> int:
        """Logical pair count; this is not a combined two-channel sample rate."""

        return len(self.payload) // constants.ADC_BYTES_PER_PAIR

    @property
    def frame_coverage_ticks(self) -> int:
        return self.item_count * self.pair_period_ticks

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

    def calibrated_channels(
        self,
        calibration: CalibrationRecord,
        *,
        hardware_serial: int | None = None,
        analog_front_end_profile: str | None = None,
    ) -> CalibratedAdcChannels:
        """Return opt-in calibrated volts while retaining both raw views."""

        from .calibration import calibrated_channels

        return calibrated_channels(
            self,
            calibration,
            hardware_serial=hardware_serial,
            analog_front_end_profile=analog_front_end_profile,
        )

    def calibrated_interleaved(
        self,
        calibration: CalibrationRecord,
        *,
        hardware_serial: int | None = None,
        analog_front_end_profile: str | None = None,
    ) -> Iterator[CalibratedAdcSample]:
        """Return calibrated timestamped samples without changing raw codes."""

        from .calibration import calibrated_interleaved

        return calibrated_interleaved(
            self,
            calibration,
            hardware_serial=hardware_serial,
            analog_front_end_profile=analog_front_end_profile,
        )

    def as_numpy(self) -> ADCArrayView:
        """Load the optional NumPy integration and borrow this payload."""

        from .numpy import adc_view

        return adc_view(self)


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
    """Lazy Boolean view over one advertised bit in packed GPIO samples."""

    __slots__ = ("_block", "bit", "pin")

    def __init__(self, block: GPIOBlock, pin: int) -> None:
        if not isinstance(pin, int) or isinstance(pin, bool):
            raise TypeError(block.pin_error_message)
        try:
            self.bit = block.pins_by_bit.index(pin)
        except ValueError as exc:
            raise ValueError(block.pin_error_message) from exc
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
        return bool(self._block.sample(position) & (1 << self.bit))


@dataclass(frozen=True, slots=True)
class GPIOBlock:
    """One frame of packed simultaneous primary or primary+auxiliary GPIO."""

    run_id: int
    sequence: int
    first_sample_ticks: int
    payload: bytes
    flags: constants.FrameFlag = constants.FrameFlag.NONE
    checksum_algorithm: constants.ChecksumAlgorithm = (
        constants.DEFAULT_CHECKSUM_ALGORITHM
    )
    aux_bank_mode: AuxBankMode = AuxBankMode.DISABLED
    rate_profile: RateProfile = v2_constants.DEFAULT_RATE_PROFILE
    protocol_version: int = constants.PROTOCOL_VERSION

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
        if isinstance(self.aux_bank_mode, bool) or isinstance(self.rate_profile, bool):
            raise TypeError("GPIO block mode/rate metadata is invalid")
        try:
            mode = AuxBankMode(self.aux_bank_mode)
            profile = RateProfile(self.rate_profile)
        except (TypeError, ValueError) as exc:
            raise ValueError("GPIO block mode/rate metadata is invalid") from exc
        if self.protocol_version not in {
            constants.PROTOCOL_VERSION,
            v2_constants.PROTOCOL_VERSION,
        } or isinstance(self.protocol_version, bool):
            raise ValueError("GPIO block protocol version must be 1 or 2")
        if self.protocol_version == constants.PROTOCOL_VERSION and (
            mode is not AuxBankMode.DISABLED
            or profile is not v2_constants.DEFAULT_RATE_PROFILE
        ):
            raise ValueError("protocol-v1 GPIO blocks require the legacy layout/rate")
        object.__setattr__(self, "aux_bank_mode", mode)
        object.__setattr__(self, "rate_profile", profile)
        layout = GPIOLayout.from_mode(mode)
        if len(payload) != layout.payload_bytes:
            if mode is AuxBankMode.DISABLED:
                raise ValueError("GPIO blocks require exactly 4048 packed samples")
            raise ValueError(
                "GPIO blocks in INPUT mode require exactly 2024 packed samples"
            )

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

    @classmethod
    def from_v2_frame(
        cls,
        frame: V2Frame,
        configuration: DAQConfiguration,
    ) -> GPIOBlock:
        """Decode v2 packed samples using the negotiated whole-bank mode."""

        if int(frame.header.kind) != int(constants.FrameKind.GPIO_DATA):
            raise TypeError("frame is not GPIO_DATA")
        if not isinstance(configuration, DAQConfiguration):
            raise TypeError("configuration must be DAQConfiguration")
        layout = configuration.gpio_layout
        timing = configuration.rate_timing
        if frame.header.item_count != layout.items_per_frame:
            raise FrameValidationError(
                "protocol-v2 GPIO item count disagrees with negotiated layout"
            )
        if frame.header.first_sample_ticks % timing.gpio_sample_period_ticks:
            raise FrameValidationError(
                "protocol-v2 GPIO timestamp disagrees with selected period"
            )
        return cls(
            run_id=frame.header.run_id,
            sequence=frame.header.sequence,
            first_sample_ticks=frame.header.first_sample_ticks,
            payload=frame.payload,
            flags=constants.FrameFlag(int(frame.header.flags)),
            checksum_algorithm=constants.ChecksumAlgorithm(
                int(frame.header.checksum_algorithm)
            ),
            aux_bank_mode=configuration.aux_bank_mode,
            rate_profile=configuration.rate_profile,
            protocol_version=v2_constants.PROTOCOL_VERSION,
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
        """Count of simultaneous packed samples in the payload."""

        return self.layout.items_per_frame

    @property
    def layout(self) -> GPIOLayout:
        return GPIOLayout.from_mode(self.aux_bank_mode)

    @property
    def packed_width_bits(self) -> int:
        return self.layout.packed_width_bits

    @property
    def item_bytes(self) -> int:
        return self.layout.item_bytes

    @property
    def pins_by_bit(self) -> tuple[int, ...]:
        return self.layout.pins_by_bit

    @property
    def primary_pins_by_bit(self) -> tuple[int, ...]:
        return self.layout.primary_pins_by_bit

    @property
    def auxiliary_pins_by_bit(self) -> tuple[int, ...]:
        return self.layout.auxiliary_pins_by_bit

    @property
    def sample_mask(self) -> int:
        return (1 << self.packed_width_bits) - 1

    @property
    def pin_error_message(self) -> str:
        if self.aux_bank_mode is AuxBankMode.DISABLED:
            return "GPIO pin must be one of D6 through D13"
        return "GPIO pin must be one of D6 through D13 or D16 through D23"

    @property
    def samples(self) -> memoryview:
        """Zero-copy byte view preserving the packed wire representation."""

        return memoryview(self.payload)

    @property
    def timestamp_hz(self) -> int:
        """Frequency of the advertised START-relative timestamp domain."""

        return constants.TIMESTAMP_HZ

    @property
    def t0_ticks(self) -> int:
        """Nominal run-relative timestamp of the first packed GPIO sample."""

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
        return RateProfileTiming.from_profile(
            self.rate_profile
        ).gpio_sample_period_ticks

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
            self.first_sample_ticks + self.item_count * self.sample_period_ticks
        ) & constants.UINT64_MAX

    @property
    def frame_coverage_ticks(self) -> int:
        return self.item_count * self.sample_period_ticks

    @property
    def first_sample_index(self) -> int:
        """Global simultaneous-snapshot index implied by the 8 MHz timestamp."""

        return self.first_sample_ticks // self.sample_period_ticks

    def sample(self, index: int) -> int:
        if index < 0:
            index += self.item_count
        if not 0 <= index < self.item_count:
            raise IndexError("GPIO sample index out of range")
        if self.item_bytes == 1:
            return self.payload[index]
        return struct.unpack_from("<H", self.payload, index * self.item_bytes)[0]

    def sample_ticks(self, index: int) -> int:
        if index < 0:
            index += self.item_count
        if not 0 <= index < self.item_count:
            raise IndexError("GPIO sample index out of range")
        return (
            self.first_sample_ticks + index * self.sample_period_ticks
        ) & constants.UINT64_MAX

    def sample_seconds(self, index: int) -> float:
        """Return one nominal packed-byte START-relative time in seconds."""

        return self.sample_ticks(index) / self.timestamp_hz

    def as_numpy(self) -> GPIOArrayView:
        """Load the optional NumPy integration without expanding GPIO bits."""

        from .numpy import gpio_view

        return gpio_view(self)

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


class HostQueuePolicy(Enum):
    """Bounded decoded-queue policy responsible for application-side loss."""

    DROP_OLDEST_COMPLETE = "drop_oldest_complete"


class StreamAnomalyReason(Enum):
    """Typed non-gap continuity failures observed on a decoded data stream."""

    DUPLICATE = "duplicate"
    REORDERED = "reordered"
    STALE_RUN = "stale_run"
    TIMESTAMP_INCONSISTENT = "timestamp_inconsistent"
    FIRMWARE_EVIDENCE_MISMATCH = "firmware_evidence_mismatch"
    HOST_QUEUE_RANGE_INCONSISTENT = "host_queue_range_inconsistent"


@dataclass(frozen=True, slots=True)
class FirmwareLossEvidence:
    """Frame flags and cumulative STATUS evidence for one loss observation.

    Counter fields are ``None`` until a STATUS response was available.  The
    expected cumulative values are host inferences for the active statistics
    generation; they are never overwritten with the firmware values when the
    two disagree.
    """

    source: constants.Source
    gap_before: bool
    overrun_before: bool
    stats_generation: int | None = None
    cumulative_dropped_frames: int | None = None
    cumulative_dropped_items: int | None = None
    cumulative_dropped_bytes: int | None = None
    expected_cumulative_frames: int = 0
    expected_cumulative_items: int = 0
    flags_match: bool = True
    counters_match: bool | None = None
    errors: tuple[str, ...] = ()

    def __post_init__(self) -> None:
        if isinstance(self.source, bool):
            raise TypeError("firmware loss source is invalid")
        try:
            source = constants.Source(self.source)
        except (TypeError, ValueError) as exc:
            raise ValueError("firmware loss source is invalid") from exc
        object.__setattr__(self, "source", source)
        if not isinstance(self.gap_before, bool) or not isinstance(
            self.overrun_before, bool
        ):
            raise TypeError("firmware loss flags must be booleans")
        if self.overrun_before and not self.gap_before:
            raise ValueError("firmware overrun evidence requires GAP_BEFORE")
        for name in (
            "stats_generation",
            "cumulative_dropped_frames",
            "cumulative_dropped_items",
            "cumulative_dropped_bytes",
        ):
            value = getattr(self, name)
            if value is not None:
                _nonnegative(name, value)
        if self.stats_generation == 0:
            raise ValueError("firmware statistics generation must be nonzero")
        _nonnegative("expected_cumulative_frames", self.expected_cumulative_frames)
        _nonnegative("expected_cumulative_items", self.expected_cumulative_items)
        if not isinstance(self.flags_match, bool):
            raise TypeError("flags_match must be a boolean")
        if self.counters_match is not None and not isinstance(
            self.counters_match, bool
        ):
            raise TypeError("counters_match must be a boolean or None")
        errors = tuple(self.errors)
        if any(not isinstance(error, str) or not error for error in errors):
            raise ValueError("firmware evidence errors must be nonempty strings")
        object.__setattr__(self, "errors", errors)

    @property
    def consistent(self) -> bool:
        """Whether every available flag and counter check agrees."""

        return self.flags_match and self.counters_match is not False and not self.errors


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
    source: constants.Source = constants.Source.HARDWARE
    sequence_inferred_items: int | None = None
    firmware_evidence: FirmwareLossEvidence | None = None
    period_ticks: int | None = None
    frame_item_count: int | None = None

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
        if isinstance(self.source, bool):
            raise TypeError("stream gap source is invalid")
        try:
            source = constants.Source(self.source)
        except (TypeError, ValueError) as exc:
            raise ValueError("stream gap source is invalid") from exc
        object.__setattr__(self, "source", source)
        default_period = (
            constants.ADC_PAIR_PERIOD_TICKS
            if kind is constants.FrameKind.ADC_DATA
            else constants.GPIO_SAMPLE_PERIOD_TICKS
        )
        default_count = (
            constants.ADC_PAIRS_PER_FRAME
            if kind is constants.FrameKind.ADC_DATA
            else constants.GPIO_SAMPLES_PER_FRAME
        )
        period_ticks = (
            default_period if self.period_ticks is None else self.period_ticks
        )
        frame_item_count = (
            default_count if self.frame_item_count is None else self.frame_item_count
        )
        if (
            not isinstance(period_ticks, int)
            or isinstance(period_ticks, bool)
            or period_ticks <= 0
            or not isinstance(frame_item_count, int)
            or isinstance(frame_item_count, bool)
            or frame_item_count <= 0
        ):
            raise ValueError("stream gap timing/layout metadata must be positive")
        object.__setattr__(self, "period_ticks", period_ticks)
        object.__setattr__(self, "frame_item_count", frame_item_count)
        sequence_items = self.sequence_inferred_items
        if sequence_items is None:
            sequence_items = self.missing_frames * self.items_per_frame
            object.__setattr__(self, "sequence_inferred_items", sequence_items)
        _nonnegative("sequence_inferred_items", sequence_items)
        if sequence_items != self.missing_items:
            raise ValueError(
                "sequence and timestamp imply different missing item counts"
            )
        if self.firmware_evidence is not None:
            if not isinstance(self.firmware_evidence, FirmwareLossEvidence):
                raise TypeError(
                    "firmware_evidence must be FirmwareLossEvidence or None"
                )
            if self.firmware_evidence.source is not source:
                raise ValueError("firmware evidence source disagrees with stream gap")
            if (
                self.firmware_evidence.gap_before != self.firmware_reported
                or self.firmware_evidence.overrun_before != self.firmware_overrun
            ):
                raise ValueError("firmware evidence flags disagree with stream gap")
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
        assert self.period_ticks is not None
        return self.period_ticks

    @property
    def items_per_frame(self) -> int:
        assert self.frame_item_count is not None
        return self.frame_item_count

    @property
    def stream(self) -> constants.StreamMask:
        return (
            constants.StreamMask.ADC
            if self.kind is constants.FrameKind.ADC_DATA
            else constants.StreamMask.GPIO
        )

    @property
    def previous_sequence(self) -> int:
        return (self.expected_sequence - 1) & constants.UINT32_MAX

    @property
    def missing_start_ticks(self) -> int:
        return self.expected_first_sample_ticks

    @property
    def missing_end_ticks(self) -> int:
        return self.observed_first_sample_ticks

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
            else current.sample_period_ticks
        )
        if tick_delta % period:
            raise ValueError("stream timestamp gap is not sample-period aligned")
        missing_items = tick_delta // period
        sequence_inferred_items = missing_frames * current.item_count
        if sequence_inferred_items != missing_items:
            raise ValueError(
                "sequence and timestamp imply different missing item counts"
            )
        firmware_reported = bool(current.flags & constants.FrameFlag.GAP_BEFORE)
        if missing_frames == 0 and missing_items == 0 and not firmware_reported:
            return None
        source = current.source
        flag_errors: list[str] = []
        if bool(missing_items) != firmware_reported:
            flag_errors.append(
                "GAP_BEFORE does not match the inferred stream discontinuity"
            )
        evidence = FirmwareLossEvidence(
            source=source,
            gap_before=firmware_reported,
            overrun_before=bool(current.flags & constants.FrameFlag.OVERRUN_BEFORE),
            expected_cumulative_frames=missing_frames,
            expected_cumulative_items=missing_items,
            flags_match=not flag_errors,
            errors=tuple(flag_errors),
        )
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
            source=source,
            sequence_inferred_items=sequence_inferred_items,
            firmware_evidence=evidence,
            period_ticks=period,
            frame_item_count=current.item_count,
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
        previous_period = (
            previous.pair_period_ticks
            if isinstance(previous, ADCBlock)
            else previous.sample_period_ticks
        )
        current_period = (
            current.pair_period_ticks
            if isinstance(current, ADCBlock)
            else current.sample_period_ticks
        )
        if (
            previous_period != current_period
            or previous.item_count != current.item_count
            or previous.protocol_version != current.protocol_version
        ):
            raise ValueError("stream profile changed inside one run")
        expected_sequence = (previous.sequence + 1) & constants.UINT32_MAX
        expected_ticks = previous.end_tick_exclusive
        return cls.from_expected(
            current,
            expected_sequence=expected_sequence,
            expected_first_sample_ticks=expected_ticks,
        )


@dataclass(frozen=True, slots=True)
class StreamAnomaly:
    """Typed duplicate, reorder, stale-run, or timestamp telemetry report."""

    reason: StreamAnomalyReason
    kind: constants.FrameKind
    source: constants.Source
    active_run_id: int
    observed_run_id: int
    observed_sequence: int
    observed_first_sample_ticks: int
    expected_sequence: int | None = None
    expected_first_sample_ticks: int | None = None
    sequence_inferred_items: int | None = None
    timestamp_inferred_items: int | None = None
    firmware_evidence: FirmwareLossEvidence | None = None
    occurrences: int = 1

    def __post_init__(self) -> None:
        if any(
            isinstance(value, bool) for value in (self.reason, self.kind, self.source)
        ):
            raise TypeError("stream anomaly metadata is invalid")
        try:
            reason = StreamAnomalyReason(self.reason)
            kind = constants.FrameKind(self.kind)
            source = constants.Source(self.source)
        except (TypeError, ValueError) as exc:
            raise ValueError("stream anomaly metadata is invalid") from exc
        if kind not in {
            constants.FrameKind.ADC_DATA,
            constants.FrameKind.GPIO_DATA,
        }:
            raise ValueError("stream anomalies require an ADC or GPIO data kind")
        object.__setattr__(self, "reason", reason)
        object.__setattr__(self, "kind", kind)
        object.__setattr__(self, "source", source)
        _unsigned("active_run_id", self.active_run_id, 32)
        _unsigned("observed_run_id", self.observed_run_id, 32)
        if self.active_run_id == 0 or self.observed_run_id == 0:
            raise ValueError("stream anomalies require nonzero run identities")
        _unsigned("observed_sequence", self.observed_sequence, 32)
        _unsigned("observed_first_sample_ticks", self.observed_first_sample_ticks, 64)
        for name, bits in (
            ("expected_sequence", 32),
            ("expected_first_sample_ticks", 64),
        ):
            value = getattr(self, name)
            if value is not None:
                _unsigned(name, value, bits)
        for name in ("sequence_inferred_items", "timestamp_inferred_items"):
            value = getattr(self, name)
            if value is not None:
                _nonnegative(name, value)
        _nonnegative("occurrences", self.occurrences)
        if self.occurrences == 0:
            raise ValueError("stream anomaly occurrences must be positive")
        if self.firmware_evidence is not None:
            if not isinstance(self.firmware_evidence, FirmwareLossEvidence):
                raise TypeError(
                    "firmware_evidence must be FirmwareLossEvidence or None"
                )
            if self.firmware_evidence.source is not source:
                raise ValueError("firmware evidence source disagrees with anomaly")

    @property
    def run_id(self) -> int:
        return self.observed_run_id

    @property
    def stream(self) -> constants.StreamMask:
        return (
            constants.StreamMask.ADC
            if self.kind is constants.FrameKind.ADC_DATA
            else constants.StreamMask.GPIO
        )

    @classmethod
    def stale_run(
        cls,
        block: ADCBlock | GPIOBlock,
        *,
        active_run_id: int,
    ) -> StreamAnomaly:
        kind = (
            constants.FrameKind.ADC_DATA
            if isinstance(block, ADCBlock)
            else constants.FrameKind.GPIO_DATA
        )
        return cls(
            reason=StreamAnomalyReason.STALE_RUN,
            kind=kind,
            source=block.source,
            active_run_id=active_run_id,
            observed_run_id=block.run_id,
            observed_sequence=block.sequence,
            observed_first_sample_ticks=block.first_sample_ticks,
            firmware_evidence=FirmwareLossEvidence(
                source=block.source,
                gap_before=bool(block.flags & constants.FrameFlag.GAP_BEFORE),
                overrun_before=bool(block.flags & constants.FrameFlag.OVERRUN_BEFORE),
            ),
        )

    def merged_with(self, other: StreamAnomaly) -> StreamAnomaly:
        """Coalesce repeated stale reports while retaining the newest evidence."""

        if (
            self.reason is not other.reason
            or self.kind is not other.kind
            or self.source is not other.source
            or self.active_run_id != other.active_run_id
            or self.observed_run_id != other.observed_run_id
        ):
            raise ValueError("cannot merge unrelated stream anomalies")
        return dataclass_replace(
            other,
            occurrences=self.occurrences + other.occurrences,
        )


@dataclass(frozen=True, slots=True)
class HostQueueLoss:
    """Exact decoded application-queue eviction, separate from firmware loss."""

    kind: constants.FrameKind
    source: constants.Source
    run_id: int
    first_sequence: int
    last_sequence: int
    first_sample_ticks: int
    end_sample_ticks: int
    dropped_blocks: int
    dropped_items: int
    policy: HostQueuePolicy = HostQueuePolicy.DROP_OLDEST_COMPLETE
    firmware_gap_blocks: int = 0
    firmware_overrun_blocks: int = 0
    contiguous: bool = True
    period_ticks: int | None = None
    frame_item_count: int | None = None

    def __post_init__(self) -> None:
        if any(
            isinstance(value, bool) for value in (self.kind, self.source, self.policy)
        ):
            raise TypeError("host queue loss metadata is invalid")
        try:
            kind = constants.FrameKind(self.kind)
            source = constants.Source(self.source)
            policy = HostQueuePolicy(self.policy)
        except (TypeError, ValueError) as exc:
            raise ValueError("host queue loss metadata is invalid") from exc
        if kind not in {
            constants.FrameKind.ADC_DATA,
            constants.FrameKind.GPIO_DATA,
        }:
            raise ValueError("host queue loss requires an ADC or GPIO data kind")
        object.__setattr__(self, "kind", kind)
        object.__setattr__(self, "source", source)
        object.__setattr__(self, "policy", policy)
        default_period = (
            constants.ADC_PAIR_PERIOD_TICKS
            if kind is constants.FrameKind.ADC_DATA
            else constants.GPIO_SAMPLE_PERIOD_TICKS
        )
        default_count = (
            constants.ADC_PAIRS_PER_FRAME
            if kind is constants.FrameKind.ADC_DATA
            else constants.GPIO_SAMPLES_PER_FRAME
        )
        period_ticks = (
            default_period if self.period_ticks is None else self.period_ticks
        )
        frame_item_count = (
            default_count if self.frame_item_count is None else self.frame_item_count
        )
        if (
            not isinstance(period_ticks, int)
            or isinstance(period_ticks, bool)
            or period_ticks <= 0
            or not isinstance(frame_item_count, int)
            or isinstance(frame_item_count, bool)
            or frame_item_count <= 0
        ):
            raise ValueError("host queue timing/layout metadata must be positive")
        object.__setattr__(self, "period_ticks", period_ticks)
        object.__setattr__(self, "frame_item_count", frame_item_count)
        _unsigned("run_id", self.run_id, 32)
        _unsigned("first_sequence", self.first_sequence, 32)
        _unsigned("last_sequence", self.last_sequence, 32)
        _unsigned("first_sample_ticks", self.first_sample_ticks, 64)
        _unsigned("end_sample_ticks", self.end_sample_ticks, 64)
        for name in (
            "dropped_blocks",
            "dropped_items",
            "firmware_gap_blocks",
            "firmware_overrun_blocks",
        ):
            _nonnegative(name, getattr(self, name))
        if self.run_id == 0 or self.dropped_blocks == 0 or self.dropped_items == 0:
            raise ValueError("host queue loss requires a nonempty active run range")
        if self.dropped_items != self.dropped_blocks * self.items_per_block:
            raise ValueError("host queue block and item counts disagree")
        if self.firmware_gap_blocks > self.dropped_blocks:
            raise ValueError("host queue gap evidence exceeds dropped blocks")
        if self.firmware_overrun_blocks > self.firmware_gap_blocks:
            raise ValueError("host queue overrun evidence requires gap evidence")
        if not isinstance(self.contiguous, bool):
            raise TypeError("host queue range continuity must be a boolean")
        if self.contiguous:
            expected_last = (
                self.first_sequence + self.dropped_blocks - 1
            ) & constants.UINT32_MAX
            if self.last_sequence != expected_last:
                raise ValueError("contiguous host queue range has a sequence hole")
            expected_end = (
                self.first_sample_ticks + self.dropped_items * self.item_period_ticks
            ) & constants.UINT64_MAX
            if self.end_sample_ticks != expected_end:
                raise ValueError("contiguous host queue range has a timestamp hole")

    @property
    def stream(self) -> constants.StreamMask:
        return (
            constants.StreamMask.ADC
            if self.kind is constants.FrameKind.ADC_DATA
            else constants.StreamMask.GPIO
        )

    @property
    def item_period_ticks(self) -> int:
        assert self.period_ticks is not None
        return self.period_ticks

    @property
    def items_per_block(self) -> int:
        assert self.frame_item_count is not None
        return self.frame_item_count

    @property
    def origin(self) -> LossOrigin:
        return LossOrigin.HOST_QUEUE

    @property
    def host_queue_drops(self) -> int:
        """Compatibility alias for the exact dropped block count."""

        return self.dropped_blocks

    @property
    def missing_frames(self) -> int:
        return self.dropped_blocks

    @property
    def missing_items(self) -> int:
        return self.dropped_items

    @classmethod
    def from_block(cls, block: ADCBlock | GPIOBlock) -> HostQueueLoss:
        kind = (
            constants.FrameKind.ADC_DATA
            if isinstance(block, ADCBlock)
            else constants.FrameKind.GPIO_DATA
        )
        return cls(
            kind=kind,
            source=block.source,
            run_id=block.run_id,
            first_sequence=block.sequence,
            last_sequence=block.sequence,
            first_sample_ticks=block.first_sample_ticks,
            end_sample_ticks=block.end_tick_exclusive,
            dropped_blocks=1,
            dropped_items=block.item_count,
            firmware_gap_blocks=int(bool(block.flags & constants.FrameFlag.GAP_BEFORE)),
            firmware_overrun_blocks=int(
                bool(block.flags & constants.FrameFlag.OVERRUN_BEFORE)
            ),
            period_ticks=(
                block.pair_period_ticks
                if isinstance(block, ADCBlock)
                else block.sample_period_ticks
            ),
            frame_item_count=block.item_count,
        )

    def can_merge(self, other: HostQueueLoss) -> bool:
        return (
            self.kind is other.kind
            and self.source is other.source
            and self.run_id == other.run_id
            and self.item_period_ticks == other.item_period_ticks
            and self.items_per_block == other.items_per_block
            and other.first_sequence
            == ((self.last_sequence + 1) & constants.UINT32_MAX)
            and other.first_sample_ticks == self.end_sample_ticks
        )

    def merged_with(self, other: HostQueueLoss) -> HostQueueLoss:
        """Coalesce one same-source contiguous eviction without losing units."""

        if not self.can_merge(other):
            raise ValueError("cannot merge noncontiguous host queue losses")
        return HostQueueLoss(
            kind=self.kind,
            source=self.source,
            run_id=self.run_id,
            first_sequence=self.first_sequence,
            last_sequence=other.last_sequence,
            first_sample_ticks=self.first_sample_ticks,
            end_sample_ticks=other.end_sample_ticks,
            dropped_blocks=self.dropped_blocks + other.dropped_blocks,
            dropped_items=self.dropped_items + other.dropped_items,
            policy=self.policy,
            firmware_gap_blocks=(self.firmware_gap_blocks + other.firmware_gap_blocks),
            firmware_overrun_blocks=(
                self.firmware_overrun_blocks + other.firmware_overrun_blocks
            ),
            period_ticks=self.item_period_ticks,
            frame_item_count=self.items_per_block,
        )

    def aggregated_with(self, other: HostQueueLoss) -> HostQueueLoss:
        """Boundedly retain exact units for noncontiguous same-source loss."""

        if (
            self.kind is not other.kind
            or self.source is not other.source
            or self.run_id != other.run_id
            or self.item_period_ticks != other.item_period_ticks
            or self.items_per_block != other.items_per_block
        ):
            raise ValueError("cannot aggregate unrelated host queue losses")
        if self.can_merge(other) and self.contiguous and other.contiguous:
            return self.merged_with(other)
        return HostQueueLoss(
            kind=self.kind,
            source=self.source,
            run_id=self.run_id,
            first_sequence=self.first_sequence,
            last_sequence=other.last_sequence,
            first_sample_ticks=self.first_sample_ticks,
            end_sample_ticks=other.end_sample_ticks,
            dropped_blocks=self.dropped_blocks + other.dropped_blocks,
            dropped_items=self.dropped_items + other.dropped_items,
            policy=self.policy,
            firmware_gap_blocks=(self.firmware_gap_blocks + other.firmware_gap_blocks),
            firmware_overrun_blocks=(
                self.firmware_overrun_blocks + other.firmware_overrun_blocks
            ),
            contiguous=False,
            period_ticks=self.item_period_ticks,
            frame_item_count=self.items_per_block,
        )


def analyze_stream_continuity(
    current: ADCBlock | GPIOBlock,
    *,
    expected_sequence: int,
    expected_first_sample_ticks: int,
    active_run_id: int,
    previous_sequence: int | None = None,
) -> StreamGap | StreamAnomaly | None:
    """Classify one frame without conflating forward loss with other failures.

    ``previous_sequence`` is explicit so sequence ``UINT32_MAX`` at a fresh
    epoch is reordered, while the same value after a delivered wrap is a true
    duplicate.
    """

    _unsigned("expected_sequence", expected_sequence, 32)
    _unsigned("expected_first_sample_ticks", expected_first_sample_ticks, 64)
    _unsigned("active_run_id", active_run_id, 32)
    if previous_sequence is not None:
        _unsigned("previous_sequence", previous_sequence, 32)
        if expected_sequence != ((previous_sequence + 1) & constants.UINT32_MAX):
            raise ValueError("previous and expected stream sequences disagree")
    kind = (
        constants.FrameKind.ADC_DATA
        if isinstance(current, ADCBlock)
        else constants.FrameKind.GPIO_DATA
    )
    evidence = FirmwareLossEvidence(
        source=current.source,
        gap_before=bool(current.flags & constants.FrameFlag.GAP_BEFORE),
        overrun_before=bool(current.flags & constants.FrameFlag.OVERRUN_BEFORE),
    )
    if current.run_id != active_run_id:
        return StreamAnomaly.stale_run(current, active_run_id=active_run_id)

    sequence_delta = (current.sequence - expected_sequence) & constants.UINT32_MAX
    tick_delta = (
        current.first_sample_ticks - expected_first_sample_ticks
    ) & constants.UINT64_MAX
    period = (
        current.pair_period_ticks
        if isinstance(current, ADCBlock)
        else current.sample_period_ticks
    )
    if sequence_delta > constants.UINT32_MAX // 2:
        reason = (
            StreamAnomalyReason.DUPLICATE
            if previous_sequence is not None and current.sequence == previous_sequence
            else StreamAnomalyReason.REORDERED
        )
        if evidence.gap_before:
            evidence = dataclass_replace(
                evidence,
                flags_match=False,
                errors=("firmware marked a gap on a duplicate or reordered frame",),
            )
        return StreamAnomaly(
            reason=reason,
            kind=kind,
            source=current.source,
            active_run_id=active_run_id,
            observed_run_id=current.run_id,
            expected_sequence=expected_sequence,
            observed_sequence=current.sequence,
            expected_first_sample_ticks=expected_first_sample_ticks,
            observed_first_sample_ticks=current.first_sample_ticks,
            firmware_evidence=evidence,
        )

    sequence_items = sequence_delta * current.item_count
    timestamp_items: int | None = None
    if tick_delta <= constants.UINT64_MAX // 2 and tick_delta % period == 0:
        timestamp_items = tick_delta // period
    if timestamp_items is None or timestamp_items != sequence_items:
        sequence_implies_gap = sequence_delta > 0
        if evidence.gap_before != sequence_implies_gap:
            evidence = dataclass_replace(
                evidence,
                flags_match=False,
                errors=(
                    "GAP_BEFORE does not match the sequence-inferred stream discontinuity",
                ),
            )
        return StreamAnomaly(
            reason=StreamAnomalyReason.TIMESTAMP_INCONSISTENT,
            kind=kind,
            source=current.source,
            active_run_id=active_run_id,
            observed_run_id=current.run_id,
            expected_sequence=expected_sequence,
            observed_sequence=current.sequence,
            expected_first_sample_ticks=expected_first_sample_ticks,
            observed_first_sample_ticks=current.first_sample_ticks,
            sequence_inferred_items=sequence_items,
            timestamp_inferred_items=timestamp_items,
            firmware_evidence=evidence,
        )

    firmware_reported = evidence.gap_before
    if sequence_delta == 0:
        if not firmware_reported:
            return None
        return StreamAnomaly(
            reason=StreamAnomalyReason.FIRMWARE_EVIDENCE_MISMATCH,
            kind=kind,
            source=current.source,
            active_run_id=active_run_id,
            observed_run_id=current.run_id,
            expected_sequence=expected_sequence,
            observed_sequence=current.sequence,
            expected_first_sample_ticks=expected_first_sample_ticks,
            observed_first_sample_ticks=current.first_sample_ticks,
            sequence_inferred_items=0,
            timestamp_inferred_items=0,
            firmware_evidence=dataclass_replace(
                evidence,
                flags_match=False,
                errors=("firmware marked a gap where continuity is complete",),
            ),
        )

    return StreamGap.from_expected(
        current,
        expected_sequence=expected_sequence,
        expected_first_sample_ticks=expected_first_sample_ticks,
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
DecodedMessage = AdcBlock | GpioBlock | CommandResponse[ResponseValue] | Frame | V2Frame


def decode_response(frame: Frame | V2Frame) -> CommandResponse[ResponseValue]:
    """Decode any typed or generic response into a request-correlated model."""

    try:
        kind = constants.FrameKind(int(frame.header.kind))
    except ValueError as exc:
        raise TypeError("frame kind is not supported by the public API") from exc
    response_kinds = set(constants.REQUEST_RESPONSE_KIND.values()) | {
        constants.FrameKind.ERROR_RESPONSE
    }
    if kind not in response_kinds:
        raise TypeError("frame is not a command response")
    raw_status, _, raw_error = _RESPONSE_PREFIX.unpack_from(frame.payload)
    status = constants.ResponseStatus(raw_status)
    error = constants.ErrorCode(raw_error)
    value: ResponseValue | None = None
    rejected_kind: int | None = None
    rejected_version: int | None = None
    if status is constants.ResponseStatus.OK:
        if kind is constants.FrameKind.INFO_RESPONSE:
            value = Info.from_payload(frame.payload)
        elif kind in {
            constants.FrameKind.CONFIGURE_RESPONSE,
            constants.FrameKind.START_RESPONSE,
        }:
            value = Configuration.from_payload(frame.payload[4:])
        elif kind is constants.FrameKind.GET_STATUS_RESPONSE:
            value = Status.from_payload(frame.payload)
        elif kind is constants.FrameKind.STOP_RESPONSE:
            value = constants.DeviceState(
                frame.payload[constants.STOP_RESPONSE_DEVICE_STATE_OFFSET]
            )
        elif kind is constants.FrameKind.RESET_STATS_RESPONSE:
            value = struct.unpack_from(
                "<I",
                frame.payload,
                constants.RESET_STATS_RESPONSE_STATS_GENERATION_OFFSET,
            )[0]
        elif kind is constants.FrameKind.PING_RESPONSE:
            value = struct.unpack_from(
                "<Q", frame.payload, constants.PING_RESPONSE_NONCE_OFFSET
            )[0]
        elif kind is constants.FrameKind.CHECKSUM_BENCHMARK_RESPONSE:
            value = ChecksumBenchmarkResult.from_payload(frame.payload)
        elif kind is constants.FrameKind.GPIO_CLOCK_DIAGNOSTIC_RESPONSE:
            value = GpioClockDiagnosticResult.from_payload(frame.payload)
        elif kind is constants.FrameKind.GPIO_CAPTURE_DIAGNOSTIC_RESPONSE:
            value = GpioCaptureDiagnosticResult.from_payload(frame.payload)
    elif kind is constants.FrameKind.ERROR_RESPONSE:
        rejected_kind = frame.payload[constants.ERROR_RESPONSE_REJECTED_KIND_OFFSET]
        rejected_version = frame.payload[
            constants.ERROR_RESPONSE_REJECTED_VERSION_OFFSET
        ]
    return CommandResponse(
        kind=kind,
        request_id=frame.header.request_id,
        run_id=frame.header.run_id,
        status=status,
        error_code=error,
        value=value,
        rejected_kind=rejected_kind,
        rejected_version=rejected_version,
    )


def decode_message(
    frame: Frame | V2Frame,
    *,
    configuration: DAQConfiguration | None = None,
) -> DecodedMessage:
    """Decode data and response frames; validated request frames remain frames."""

    try:
        kind = constants.FrameKind(int(frame.header.kind))
    except ValueError:
        return frame
    if kind is constants.FrameKind.ADC_DATA:
        if isinstance(frame, V2Frame):
            if configuration is None:
                raise FrameValidationError(
                    "protocol-v2 ADC_DATA requires negotiated configuration"
                )
            return ADCBlock.from_v2_frame(frame, configuration)
        return AdcBlock.from_frame(frame)
    if kind is constants.FrameKind.GPIO_DATA:
        if isinstance(frame, V2Frame):
            if configuration is None:
                raise FrameValidationError(
                    "protocol-v2 GPIO_DATA requires negotiated configuration"
                )
            return GPIOBlock.from_v2_frame(frame, configuration)
        return GpioBlock.from_frame(frame)
    if kind in set(constants.REQUEST_RESPONSE_KIND.values()) | {
        constants.FrameKind.ERROR_RESPONSE
    }:
        return decode_response(frame)
    return frame


__all__ = [
    "RATE_PROFILE_TIMINGS",
    "ADCBlock",
    "AdcAcquisitionStatus",
    "AdcBlock",
    "AdcBlockMetadata",
    "AdcCalibrationMetadata",
    "AdcChannelView",
    "AdcConverter",
    "AdcSample",
    "AdcTriggerMetadata",
    "AuxBankMode",
    "AuxiliaryGPIOStatus",
    "AuxiliaryInputMetadata",
    "ChecksumBenchmarkRequest",
    "ChecksumBenchmarkResult",
    "CommandResponse",
    "Configuration",
    "DAQConfiguration",
    "DecodedMessage",
    "DeviceCapabilities",
    "DeviceInfo",
    "FirmwareCounters",
    "FirmwareLossEvidence",
    "GPIOBlock",
    "GPIOLayout",
    "GpioBlock",
    "GpioCaptureDiagnosticResult",
    "GpioChannelView",
    "GpioClockDiagnosticRequest",
    "GpioClockDiagnosticResult",
    "HostCounters",
    "HostQueueLoss",
    "HostQueuePolicy",
    "Info",
    "LossCounters",
    "LossOrigin",
    "RateProfile",
    "RateProfileTiming",
    "ResponseValue",
    "Status",
    "StreamAnomaly",
    "StreamAnomalyReason",
    "StreamGap",
    "analyze_stream_continuity",
    "decode_message",
    "decode_response",
    "extract_gpio_channel",
    "interleave_adc",
]
