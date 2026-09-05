"""Validate every auxiliary-input rate/layout and print its analytic load."""

from __future__ import annotations

import argparse
import sys
from collections.abc import Mapping, Sequence
from dataclasses import dataclass
from datetime import UTC, datetime
from fractions import Fraction
from pathlib import Path
from typing import Any

from thingdaq import (
    ADCBlock,
    AuxBankMode,
    GPIOBlock,
    GPIOLayout,
    RateProfile,
    RateProfileTiming,
    Source,
    SyntheticGPIOPattern,
    ThingDAQ,
    synthetic_adc0_code,
    synthetic_adc1_code,
    synthetic_gpio_bank_bytes,
    validate_synthetic_block,
)
from thingdaq._generated import protocol_constants as constants

REPOSITORY_ROOT = Path(__file__).resolve().parents[2]
MATRIX_PATH = REPOSITORY_ROOT / "experiments/experiment-matrix.json"
PROTOCOL_V2_PATH = REPOSITORY_ROOT / "protocol/protocol-v2.json"
DEFAULT_FRAMES_PER_STREAM = 2
MAX_FRAMES_PER_STREAM = 16
FULL_COMBINED_PAYLOAD_HYPOTHESIS_BYTES_PER_SECOND = 12_000_000


class AuxInputPrototypeError(RuntimeError):
    """The offline prototype found contradictory formulas or metadata."""


@dataclass(frozen=True, slots=True)
class Scenario:
    """One exact stream, bank-mode, and rate-profile workload."""

    scenario_id: str
    adc: bool
    gpio: bool
    aux_bank_mode: AuxBankMode
    rate_profile: RateProfile

    @property
    def streams(self) -> str:
        return "ADC+GPIO" if self.adc else "GPIO"

    @property
    def timing(self) -> RateProfileTiming:
        return RateProfileTiming.from_profile(self.rate_profile)

    @property
    def layout(self) -> GPIOLayout:
        return GPIOLayout.from_mode(self.aux_bank_mode)


@dataclass(frozen=True, slots=True)
class CaptureSummary:
    """Validated bounded capture metadata with one exact decoded example."""

    pattern: SyntheticGPIOPattern
    protocol_version: int
    run_id: int
    adc_frames: int
    gpio_frames: int
    adc_pairs_validated: int
    primary_values_validated: int
    auxiliary_values_validated: int
    payload_bytes: int
    framed_bytes: int
    decoded_example: dict[str, Any]

    def to_dict(self) -> dict[str, Any]:
        return {
            "pattern": self.pattern.value,
            "protocol_version": self.protocol_version,
            "run_id": self.run_id,
            "adc_frames": self.adc_frames,
            "gpio_frames": self.gpio_frames,
            "adc_pairs_validated": self.adc_pairs_validated,
            "primary_values_validated": self.primary_values_validated,
            "auxiliary_values_validated": self.auxiliary_values_validated,
            "payload_bytes": self.payload_bytes,
            "framed_bytes": self.framed_bytes,
            "decoded_example": self.decoded_example,
        }


@dataclass(frozen=True, slots=True)
class ScenarioSummary:
    """Analytic workload paired with all requested simulator captures."""

    scenario: Scenario
    captures: tuple[CaptureSummary, ...]

    @property
    def adc_payload_rate(self) -> Fraction:
        if not self.scenario.adc:
            return Fraction(0)
        return Fraction(
            self.scenario.timing.adc_pair_rate_hz
            * self.scenario.layout.adc_payload_bytes,
            self.scenario.layout.adc_items_per_frame,
        )

    @property
    def gpio_payload_rate(self) -> Fraction:
        if not self.scenario.gpio:
            return Fraction(0)
        return Fraction(
            self.scenario.timing.gpio_sample_rate_hz
            * self.scenario.layout.payload_bytes,
            self.scenario.layout.items_per_frame,
        )

    @property
    def payload_rate(self) -> Fraction:
        return self.adc_payload_rate + self.gpio_payload_rate

    @property
    def adc_framed_rate(self) -> Fraction:
        if not self.scenario.adc:
            return Fraction(0)
        return Fraction(
            self.scenario.timing.adc_pair_rate_hz
            * self.scenario.layout.adc_total_frame_bytes,
            self.scenario.layout.adc_items_per_frame,
        )

    @property
    def gpio_framed_rate(self) -> Fraction:
        if not self.scenario.gpio:
            return Fraction(0)
        return Fraction(
            self.scenario.timing.gpio_sample_rate_hz
            * self.scenario.layout.total_frame_bytes,
            self.scenario.layout.items_per_frame,
        )

    @property
    def framed_rate(self) -> Fraction:
        return self.adc_framed_rate + self.gpio_framed_rate

    @property
    def logical_item_rate(self) -> int:
        return (self.scenario.timing.adc_pair_rate_hz if self.scenario.adc else 0) + (
            self.scenario.timing.gpio_sample_rate_hz if self.scenario.gpio else 0
        )

    @property
    def logical_channel_sample_rate(self) -> int:
        adc_values = (
            2 * self.scenario.timing.adc_pair_rate_hz if self.scenario.adc else 0
        )
        gpio_values = (
            self.scenario.layout.packed_width_bits
            * self.scenario.timing.gpio_sample_rate_hz
            if self.scenario.gpio
            else 0
        )
        return adc_values + gpio_values

    @property
    def coverage_ticks(self) -> int:
        return self.scenario.timing.frame_coverage_ticks(self.scenario.aux_bank_mode)

    @property
    def disabled_reference(self) -> ScenarioSummary:
        reference = Scenario(
            scenario_id=f"{self.scenario.scenario_id}-disabled-reference",
            adc=self.scenario.adc,
            gpio=self.scenario.gpio,
            aux_bank_mode=AuxBankMode.DISABLED,
            rate_profile=self.scenario.rate_profile,
        )
        return ScenarioSummary(reference, ())

    @property
    def projected_payload_load_increase(self) -> Fraction:
        return self.payload_rate - self.disabled_reference.payload_rate

    @property
    def projected_framed_load_increase(self) -> Fraction:
        return self.framed_rate - self.disabled_reference.framed_rate

    @property
    def projected_framed_load_ratio(self) -> Fraction:
        return self.framed_rate / self.disabled_reference.framed_rate

    def to_dict(self) -> dict[str, Any]:
        timing = self.scenario.timing
        layout = self.scenario.layout
        return {
            "scenario_id": self.scenario.scenario_id,
            "streams": self.scenario.streams,
            "aux_bank_mode": self.scenario.aux_bank_mode.name,
            "rate_profile": self.scenario.rate_profile.name,
            "protocol_versions_observed": sorted(
                {capture.protocol_version for capture in self.captures}
            ),
            "adc_pair_rate_hz": timing.adc_pair_rate_hz if self.scenario.adc else 0,
            "gpio_packed_sample_rate_hz": (
                timing.gpio_sample_rate_hz if self.scenario.gpio else 0
            ),
            "logical_wire_items_per_second": self.logical_item_rate,
            "logical_channel_samples_per_second": (self.logical_channel_sample_rate),
            "gpio_width_bits": layout.packed_width_bits,
            "frame_coverage_ticks": self.coverage_ticks,
            "frame_coverage_microseconds": Fraction(
                self.coverage_ticks * 1_000_000,
                constants.TIMESTAMP_HZ,
            ).numerator,
            "payload_bytes_per_second": _fraction_record(self.payload_rate),
            "framed_bytes_per_second": _fraction_record(self.framed_rate),
            "projected_usb_load_increase": {
                "comparison": "same streams/profile with auxiliary mode DISABLED",
                "payload_bytes_per_second": _fraction_record(
                    self.projected_payload_load_increase
                ),
                "framed_bytes_per_second": _fraction_record(
                    self.projected_framed_load_increase
                ),
                "framed_ratio": _fraction_record(self.projected_framed_load_ratio),
            },
            "captures": [capture.to_dict() for capture in self.captures],
            "claim_scope": {
                "evidence_levels": ["analytic", "simulated"],
                "protocol_framed_load_hypothesis": True,
                "physical_usb_acceptance": False,
                "target_runtime_acceptance": False,
            },
        }


def _scenario_matrix() -> tuple[Scenario, ...]:
    scenarios = [
        Scenario(
            "gpio-only-8bit-4mhz",
            False,
            True,
            AuxBankMode.DISABLED,
            RateProfile.ADC_1MHZ_GPIO_4MHZ,
        ),
        Scenario(
            "gpio-only-16bit-4mhz",
            False,
            True,
            AuxBankMode.INPUT,
            RateProfile.ADC_1MHZ_GPIO_4MHZ,
        ),
    ]
    for profile in RateProfile:
        for mode in AuxBankMode:
            scenarios.append(
                Scenario(
                    "combined-"
                    + ("8bit" if mode is AuxBankMode.DISABLED else "16bit")
                    + "-"
                    + profile.name.removeprefix("ADC_").casefold(),
                    True,
                    True,
                    mode,
                    profile,
                )
            )
    return tuple(scenarios)


SCENARIOS = _scenario_matrix()


def _fraction_record(value: Fraction) -> dict[str, int | float | str]:
    return {
        "numerator": value.numerator,
        "denominator": value.denominator,
        "exact": _format_fraction(value),
        "decimal": float(value),
    }


def _format_fraction(value: Fraction) -> str:
    if value.denominator == 1:
        return str(value.numerator)
    return f"{value.numerator}/{value.denominator}"


def _frame_budget(value: str) -> int:
    try:
        selected = int(value, 10)
    except ValueError as error:
        raise argparse.ArgumentTypeError(
            "frames per stream must be a decimal integer"
        ) from error
    if not 1 <= selected <= MAX_FRAMES_PER_STREAM:
        raise argparse.ArgumentTypeError(
            f"frames per stream must be between 1 and {MAX_FRAMES_PER_STREAM}"
        )
    return selected


def _require_equal(actual: object, expected: object, label: str) -> None:
    if actual != expected:
        raise AuxInputPrototypeError(f"{label} is {actual!r}; expected {expected!r}")


def _decoded_example(
    adc_blocks: Sequence[ADCBlock],
    gpio_blocks: Sequence[GPIOBlock],
) -> dict[str, Any]:
    example: dict[str, Any] = {}
    if adc_blocks:
        adc_block = adc_blocks[0]
        adc0_tick, adc1_tick = adc_block.pair_ticks(0)
        adc0_code, adc1_code = adc_block.pair(0)
        example["adc"] = {
            "pair_index": adc_block.first_pair_index,
            "adc0_code": adc0_code,
            "adc1_code": adc1_code,
            "adc0_tick": adc0_tick,
            "adc1_tick": adc1_tick,
            "phase_ticks": adc1_tick - adc0_tick,
        }
    if gpio_blocks:
        gpio_block = gpio_blocks[0]
        packed = gpio_block.sample(0)
        example["gpio"] = {
            "packed_index": gpio_block.first_sample_index,
            "packed_hex": f"0x{packed:0{gpio_block.item_bytes * 2}X}",
            "primary_byte_hex": f"0x{packed & 0xFF:02X}",
            "auxiliary_byte_hex": (
                f"0x{packed >> 8:02X}"
                if gpio_block.aux_bank_mode is AuxBankMode.INPUT
                else None
            ),
            "tick": gpio_block.sample_ticks(0),
            "pins_by_bit": list(gpio_block.pins_by_bit),
        }
    return example


def _validate_adc_blocks(
    scenario: Scenario,
    pattern: SyntheticGPIOPattern,
    blocks: Sequence[ADCBlock],
    frames_per_stream: int,
) -> int:
    del pattern  # ADC formulas are independent of the selected GPIO workload.
    timing = scenario.timing
    layout = scenario.layout
    _require_equal(len(blocks), frames_per_stream, "ADC frame count")
    validated = 0
    for frame_index, block in enumerate(blocks):
        _require_equal(block.sequence, frame_index, "ADC sequence")
        _require_equal(
            block.first_sample_ticks,
            frame_index * timing.frame_coverage_ticks(scenario.aux_bank_mode),
            "ADC first timestamp",
        )
        _require_equal(block.aux_bank_mode, scenario.aux_bank_mode, "ADC bank mode")
        _require_equal(block.rate_profile, scenario.rate_profile, "ADC rate profile")
        _require_equal(block.item_count, layout.adc_items_per_frame, "ADC pair count")
        _require_equal(
            block.frame_coverage_ticks,
            timing.frame_coverage_ticks(scenario.aux_bank_mode),
            "ADC frame coverage",
        )
        _require_equal(block.adc1_phase_ticks, timing.adc1_phase_ticks, "ADC1 phase")
        validate_synthetic_block(block)
        for pair_offset, (adc0_code, adc1_code) in enumerate(block.pairs()):
            pair_index = block.first_pair_index + pair_offset
            _require_equal(
                adc0_code,
                synthetic_adc0_code(pair_index),
                "ADC0 synthetic formula",
            )
            _require_equal(
                adc1_code,
                synthetic_adc1_code(pair_index),
                "ADC1 synthetic formula",
            )
            adc0_tick, adc1_tick = block.pair_ticks(pair_offset)
            _require_equal(
                adc0_tick,
                block.first_sample_ticks + pair_offset * timing.adc_pair_period_ticks,
                "ADC0 timestamp",
            )
            _require_equal(
                adc1_tick - adc0_tick,
                timing.adc1_phase_ticks,
                "ADC1 phase timestamp",
            )
            validated += 1
    return validated


def _validate_gpio_blocks(
    scenario: Scenario,
    pattern: SyntheticGPIOPattern,
    blocks: Sequence[GPIOBlock],
    frames_per_stream: int,
) -> tuple[int, int]:
    timing = scenario.timing
    layout = scenario.layout
    _require_equal(len(blocks), frames_per_stream, "GPIO frame count")
    primary_validated = 0
    auxiliary_validated = 0
    for frame_index, block in enumerate(blocks):
        _require_equal(block.sequence, frame_index, "GPIO sequence")
        _require_equal(
            block.first_sample_ticks,
            frame_index * layout.items_per_frame * timing.gpio_sample_period_ticks,
            "GPIO first timestamp",
        )
        _require_equal(block.aux_bank_mode, scenario.aux_bank_mode, "GPIO bank mode")
        _require_equal(block.rate_profile, scenario.rate_profile, "GPIO rate profile")
        _require_equal(block.item_count, layout.items_per_frame, "GPIO item count")
        _require_equal(
            block.frame_coverage_ticks,
            layout.items_per_frame * timing.gpio_sample_period_ticks,
            "GPIO frame coverage",
        )
        validate_synthetic_block(block, gpio_pattern=pattern)
        for item_offset in range(block.item_count):
            item_index = block.first_sample_index + item_offset
            expected_primary, expected_auxiliary = synthetic_gpio_bank_bytes(
                item_index,
                pattern,
            )
            packed = block.sample(item_offset)
            _require_equal(
                packed & 0xFF,
                expected_primary,
                "primary GPIO synthetic formula",
            )
            primary_validated += 1
            if scenario.aux_bank_mode is AuxBankMode.INPUT:
                _require_equal(
                    packed >> 8,
                    expected_auxiliary,
                    "auxiliary GPIO synthetic formula",
                )
                auxiliary_validated += 1
            else:
                _require_equal(packed >> 8, 0, "disabled auxiliary GPIO byte")
            _require_equal(
                block.sample_ticks(item_offset),
                block.first_sample_ticks
                + item_offset * timing.gpio_sample_period_ticks,
                "GPIO timestamp",
            )
    return primary_validated, auxiliary_validated


def _capture(
    scenario: Scenario,
    pattern: SyntheticGPIOPattern,
    frames_per_stream: int,
) -> CaptureSummary:
    layout = scenario.layout
    expected_block_count = frames_per_stream * (int(scenario.adc) + int(scenario.gpio))
    adc_blocks: list[ADCBlock] = []
    gpio_blocks: list[GPIOBlock] = []
    with ThingDAQ.simulated(gpio_pattern=pattern, strict=True) as daq:
        applied = daq.configure(
            adc=scenario.adc,
            gpio=scenario.gpio,
            source=Source.SYNTHETIC,
            aux_bank_mode=scenario.aux_bank_mode,
            rate_profile=scenario.rate_profile,
        )
        _require_equal(applied.aux_bank_mode, scenario.aux_bank_mode, "applied mode")
        _require_equal(applied.rate_profile, scenario.rate_profile, "applied profile")
        selected_info = daq.info()
        _require_equal(
            selected_info.applied_configuration,
            applied,
            "INFO applied configuration",
        )
        _require_equal(
            selected_info.protocol_version,
            applied.protocol_version,
            "INFO protocol version",
        )
        _require_equal(
            selected_info.adc_pair_period_ticks,
            scenario.timing.adc_pair_period_ticks,
            "INFO ADC period",
        )
        _require_equal(
            selected_info.adc1_phase_ticks,
            scenario.timing.adc1_phase_ticks,
            "INFO ADC1 phase",
        )
        _require_equal(
            selected_info.gpio_sample_period_ticks,
            scenario.timing.gpio_sample_period_ticks,
            "INFO GPIO period",
        )
        _require_equal(
            selected_info.frame_coverage_ticks,
            scenario.timing.frame_coverage_ticks(scenario.aux_bank_mode),
            "INFO frame coverage",
        )
        _require_equal(
            selected_info.gpio_packed_width_bits,
            layout.packed_width_bits,
            "INFO packed width",
        )

        run_id = daq.start()
        for item in daq.blocks(expected_block_count):
            if isinstance(item, ADCBlock):
                adc_blocks.append(item)
            elif isinstance(item, GPIOBlock):
                gpio_blocks.append(item)
            else:  # pragma: no cover - strict mode converts anomalies to errors
                raise AuxInputPrototypeError(f"simulator emitted {type(item).__name__}")

        adc_pairs_validated = (
            _validate_adc_blocks(scenario, pattern, adc_blocks, frames_per_stream)
            if scenario.adc
            else 0
        )
        primary_validated, auxiliary_validated = _validate_gpio_blocks(
            scenario,
            pattern,
            gpio_blocks,
            frames_per_stream,
        )
        status = daq.validate_stream_health()
        expected_adc_frames = frames_per_stream if scenario.adc else 0
        expected_gpio_frames = frames_per_stream if scenario.gpio else 0
        expected_payload_bytes = (
            expected_adc_frames * layout.adc_payload_bytes
            + expected_gpio_frames * layout.payload_bytes
        )
        expected_framed_bytes = (
            expected_adc_frames * layout.adc_total_frame_bytes
            + expected_gpio_frames * layout.total_frame_bytes
        )
        for label, actual, expected in (
            ("STATUS configuration", status.configuration, applied),
            ("STATUS ADC frames", status.adc_frames_emitted, expected_adc_frames),
            ("STATUS GPIO frames", status.gpio_frames_emitted, expected_gpio_frames),
            (
                "STATUS payload bytes",
                status.data_payload_bytes_transmitted,
                expected_payload_bytes,
            ),
            (
                "STATUS framed bytes",
                status.data_framed_bytes_transmitted,
                expected_framed_bytes,
            ),
        ):
            _require_equal(actual, expected, label)
        example = _decoded_example(adc_blocks, gpio_blocks)
        _require_equal(daq.stop(), constants.DeviceState.IDLE, "STOP state")
        final_status = daq.status()
        _require_equal(
            final_status.device_state,
            constants.DeviceState.IDLE,
            "final device state",
        )
        _require_equal(
            final_status.stream_mask, constants.StreamMask.NONE, "final streams"
        )
        _require_equal(final_status.configuration, None, "final configuration")

    if daq.is_open or daq.state is not constants.DeviceState.IDLE:
        raise AuxInputPrototypeError("simulator did not finish closed and IDLE")
    return CaptureSummary(
        pattern=pattern,
        protocol_version=applied.protocol_version,
        run_id=run_id,
        adc_frames=len(adc_blocks),
        gpio_frames=len(gpio_blocks),
        adc_pairs_validated=adc_pairs_validated,
        primary_values_validated=primary_validated,
        auxiliary_values_validated=auxiliary_validated,
        payload_bytes=expected_payload_bytes,
        framed_bytes=expected_framed_bytes,
        decoded_example=example,
    )


def run_demo(
    patterns: Sequence[SyntheticGPIOPattern],
    *,
    frames_per_stream: int,
) -> tuple[ScenarioSummary, ...]:
    """Capture every declared scenario and return its exact analytic workload."""

    if not 1 <= frames_per_stream <= MAX_FRAMES_PER_STREAM:
        raise ValueError(
            f"frames_per_stream must be between 1 and {MAX_FRAMES_PER_STREAM}"
        )
    selected_patterns = tuple(SyntheticGPIOPattern(pattern) for pattern in patterns)
    if not selected_patterns:
        raise ValueError("at least one GPIO pattern is required")
    if len(set(selected_patterns)) != len(selected_patterns):
        raise ValueError("GPIO patterns must not be duplicated")

    summaries = tuple(
        ScenarioSummary(
            scenario,
            tuple(
                _capture(scenario, pattern, frames_per_stream)
                for pattern in selected_patterns
            ),
        )
        for scenario in SCENARIOS
    )
    full_combined = next(
        summary
        for summary in summaries
        if summary.scenario.adc
        and summary.scenario.gpio
        and summary.scenario.aux_bank_mode is AuxBankMode.INPUT
        and summary.scenario.rate_profile is RateProfile.ADC_1MHZ_GPIO_4MHZ
    )
    _require_equal(
        full_combined.payload_rate,
        Fraction(FULL_COMBINED_PAYLOAD_HYPOTHESIS_BYTES_PER_SECOND),
        "full combined payload hypothesis",
    )
    return summaries


def _load_reporter() -> Any:
    if str(REPOSITORY_ROOT) not in sys.path:
        sys.path.insert(0, str(REPOSITORY_ROOT))
    from firmware.tools import experiment_evidence

    return experiment_evidence


def _input_record(reporter: Any, path: Path) -> dict[str, Any]:
    return {
        "path": path.relative_to(REPOSITORY_ROOT).as_posix(),
        "sha256": reporter.sha256_file(path),
    }


def _acceptance_records(
    matrix: Any,
    summaries: Sequence[ScenarioSummary],
) -> list[dict[str, Any]]:
    simulated_id = "aux-input-simulator-matrix"
    capture_count = sum(len(summary.captures) for summary in summaries)
    expected_capture_count = len(SCENARIOS) * len(summaries[0].captures)
    simulated_observations: Mapping[str, tuple[object, object, list[str]]] = {
        "lifecycle_complete": (
            True,
            {
                "scenario_matrix_complete": len(summaries) == len(SCENARIOS),
                "capture_matrix_complete": capture_count == expected_capture_count,
                "configure": True,
                "info": True,
                "start": True,
                "bounded_capture": True,
                "status": True,
                "stop": True,
                "close": True,
            },
            [simulated_id],
        ),
        "synthetic_formulas_exact": (
            "every ADC code/timestamp and both GPIO bank formulas matched",
            "every ADC code/timestamp and both GPIO bank formulas matched",
            [simulated_id],
        ),
        "stream_health": (
            True,
            {
                "sequence_gaps_zero": True,
                "firmware_drops_zero": True,
                "host_queue_drops_zero": True,
                "parser_errors_zero": True,
                "transport_errors_zero": True,
            },
            [simulated_id],
        ),
        "counter_conservation": (
            True,
            {
                "scenario_selection": {
                    "left": len(summaries),
                    "right": len(SCENARIOS),
                },
                "capture_selection": {
                    "left": capture_count,
                    "right": expected_capture_count,
                },
                "status_payload_bytes": True,
                "status_framed_bytes": True,
            },
            [simulated_id],
        ),
        "queue_bounds": (0, 0, [simulated_id]),
        "final_idle_cleanup": (
            True,
            {
                "device_idle": True,
                "stream_mask_empty": True,
                "reader_closed": True,
                "transport_closed": True,
            },
            [simulated_id],
        ),
        "claim_scope_complete": (
            True,
            {
                "analytic_load_labeled_hypothesis": True,
                "simulation_labeled_nonphysical": True,
                "physical_usb_acceptance_absent": True,
                "target_runtime_acceptance_absent": True,
            },
            ["aux-input-workload-analysis", simulated_id],
        ),
    }
    experiment = matrix.experiment("aux-input-bank")
    records: list[dict[str, Any]] = []
    for check_id in experiment["required_acceptance_checks"]:
        definition = matrix.acceptance_checks[check_id]
        if check_id in simulated_observations:
            expected, observed, evidence_ids = simulated_observations[check_id]
            records.append(
                {
                    "id": check_id,
                    "description": definition["description"],
                    "state": "PASS",
                    "reason": None,
                    "operator": definition["operator"],
                    "expected": expected,
                    "observed": observed,
                    "evidence_ids": evidence_ids,
                    "required_evidence_levels": definition["required_evidence_levels"],
                }
            )
        else:
            records.append(
                {
                    "id": check_id,
                    "description": definition["description"],
                    "state": "NOT_RUN",
                    "reason": (
                        "the temporary auxiliary-input prototype is analytic and "
                        "simulated only"
                    ),
                    "operator": definition["operator"],
                    "expected": None,
                    "observed": None,
                    "evidence_ids": [],
                    "required_evidence_levels": definition["required_evidence_levels"],
                }
            )
    return records


def _report_paths(output: Path) -> tuple[Path, Path]:
    if output.suffix.casefold() == ".json":
        return output, output.with_suffix(".md")
    if output.suffix.casefold() == ".md":
        return output.with_suffix(".json"), output
    return Path(f"{output}.json"), Path(f"{output}.md")


def _metric(
    name: str,
    value: float,
    evidence_id: str,
) -> dict[str, Any]:
    definitions = {
        "adc_pair_rate_hz": (
            "adc_pair_per_second",
            "streaming_elapsed_seconds",
            "streaming_window",
        ),
        "gpio_sample_rate_hz": (
            "gpio_sample_per_second",
            "streaming_elapsed_seconds",
            "streaming_window",
        ),
        "adc_payload_rate_bytes_per_second": (
            "byte_per_second",
            "streaming_elapsed_seconds",
            "streaming_window",
        ),
        "gpio_payload_rate_bytes_per_second": (
            "byte_per_second",
            "streaming_elapsed_seconds",
            "streaming_window",
        ),
        "combined_payload_rate_bytes_per_second": (
            "byte_per_second",
            "streaming_elapsed_seconds",
            "streaming_window",
        ),
        "adc_framed_rate_bytes_per_second": (
            "byte_per_second",
            "streaming_elapsed_seconds",
            "streaming_window",
        ),
        "gpio_framed_rate_bytes_per_second": (
            "byte_per_second",
            "streaming_elapsed_seconds",
            "streaming_window",
        ),
        "combined_framed_rate_bytes_per_second": (
            "byte_per_second",
            "streaming_elapsed_seconds",
            "streaming_window",
        ),
        "timestamp_clock_hz": ("hertz", "none", "artifact"),
        "adc_phase_ticks": ("tick", "none", "artifact"),
        "gpio_width_bits": ("bit", "none", "artifact_profile"),
    }
    unit, denominator, scope = definitions[name]
    return {
        "name": name,
        "value": value,
        "unit": unit,
        "denominator": denominator,
        "scope": scope,
        "evidence_level": "analytic",
        "evidence_ids": [evidence_id],
    }


def write_report(
    output: Path,
    patterns: Sequence[SyntheticGPIOPattern],
    frames_per_stream: int,
    summaries: Sequence[ScenarioSummary],
) -> tuple[Path, Path]:
    """Emit temporary evidence through the repository's shared reporter."""

    reporter = _load_reporter()
    matrix = reporter.load_experiment_matrix(MATRIX_PATH)
    experiment = matrix.experiment("aux-input-bank")
    analytic_id = "aux-input-workload-analysis"
    simulated_id = "aux-input-simulator-matrix"
    pattern_names = [pattern.value for pattern in patterns]
    command = [
        "python",
        "daq_api/examples/aux_input_matrix.py",
        "--frames-per-stream",
        str(frames_per_stream),
    ]
    for pattern in pattern_names:
        command.extend(("--pattern", pattern))
    full_combined = next(
        summary
        for summary in summaries
        if summary.scenario.adc
        and summary.scenario.gpio
        and summary.scenario.aux_bank_mode is AuxBankMode.INPUT
        and summary.scenario.rate_profile is RateProfile.ADC_1MHZ_GPIO_4MHZ
    )
    report = {
        "schema_version": matrix.report_contract["schema_version"],
        "matrix_schema_version": matrix.schema_version,
        "experiment_id": "aux-input-bank",
        "title": experiment["title"],
        "created": datetime.now(UTC).date().isoformat(),
        "result": "INCONCLUSIVE",
        "reason": (
            "analytic and simulator checks passed; firmware-build, host benchmark, "
            "rig, live USB, and physical checks were not run"
        ),
        "summary": (
            "Temporary no-hardware evidence for every exact auxiliary-input mode/rate "
            "profile. The 12 MB/s full-combined value is a protocol-load hypothesis, "
            "not physical USB acceptance."
        ),
        "identity": reporter.capture_identity(
            matrix,
            "aux-input-bank",
            root=REPOSITORY_ROOT,
        ),
        "evidence": [
            {
                "id": analytic_id,
                "level": "analytic",
                "result": "PASS",
                "reason": None,
                "method": (
                    "exact rational workload calculation from generated mode layouts, "
                    "rate profiles, item counts, and complete-frame sizes"
                ),
                "command": {
                    "argv": command,
                    "network": False,
                    "serial_hardware": False,
                    "firmware_upload": False,
                    "user_input": False,
                },
                "inputs": [
                    _input_record(reporter, MATRIX_PATH),
                    _input_record(reporter, PROTOCOL_V2_PATH),
                    _input_record(
                        reporter,
                        REPOSITORY_ROOT
                        / "daq_api/src/thingdaq/_generated/protocol_v2_constants.py",
                    ),
                    _input_record(reporter, Path(__file__).resolve()),
                ],
                "method_version": "aux-input-workload-v1",
                "workload_matrix": [summary.to_dict() for summary in summaries],
                "full_combined_payload_hypothesis_bytes_per_second": (
                    FULL_COMBINED_PAYLOAD_HYPOTHESIS_BYTES_PER_SECOND
                ),
                "physical_usb_acceptance": False,
            },
            {
                "id": simulated_id,
                "level": "simulated",
                "result": "PASS",
                "reason": None,
                "method": (
                    "bounded public-API captures with exact ADC codes, half-period "
                    "phase/timestamps, independent GPIO-bank formulas, STATUS "
                    "conservation, STOP, and closed cleanup"
                ),
                "command": {
                    "argv": command,
                    "network": False,
                    "serial_hardware": False,
                    "firmware_upload": False,
                    "user_input": False,
                },
                "inputs": [
                    _input_record(reporter, PROTOCOL_V2_PATH),
                    _input_record(
                        reporter,
                        REPOSITORY_ROOT / "daq_api/src/thingdaq/client.py",
                    ),
                    _input_record(
                        reporter,
                        REPOSITORY_ROOT / "daq_api/src/thingdaq/models.py",
                    ),
                    _input_record(
                        reporter,
                        REPOSITORY_ROOT / "daq_api/src/thingdaq/simulator.py",
                    ),
                    _input_record(
                        reporter,
                        REPOSITORY_ROOT / "daq_api/src/thingdaq/synthetic.py",
                    ),
                    _input_record(reporter, Path(__file__).resolve()),
                ],
                "simulator_identity": "ThingDAQ SimulatedDevice protocol-v1/v2",
                "protocol_identity": (
                    "protocol/protocol-v2.json sha256:"
                    + reporter.sha256_file(PROTOCOL_V2_PATH)
                ),
                "deterministic_budget": {
                    "scenarios": len(summaries),
                    "patterns": pattern_names,
                    "frames_per_stream": frames_per_stream,
                    "captures": sum(len(summary.captures) for summary in summaries),
                },
            },
        ],
        "metrics": [
            _metric(
                "adc_pair_rate_hz",
                full_combined.scenario.timing.adc_pair_rate_hz,
                analytic_id,
            ),
            _metric(
                "gpio_sample_rate_hz",
                full_combined.scenario.timing.gpio_sample_rate_hz,
                analytic_id,
            ),
            _metric(
                "adc_payload_rate_bytes_per_second",
                float(full_combined.adc_payload_rate),
                analytic_id,
            ),
            _metric(
                "gpio_payload_rate_bytes_per_second",
                float(full_combined.gpio_payload_rate),
                analytic_id,
            ),
            _metric(
                "combined_payload_rate_bytes_per_second",
                float(full_combined.payload_rate),
                analytic_id,
            ),
            _metric(
                "adc_framed_rate_bytes_per_second",
                float(full_combined.adc_framed_rate),
                analytic_id,
            ),
            _metric(
                "gpio_framed_rate_bytes_per_second",
                float(full_combined.gpio_framed_rate),
                analytic_id,
            ),
            _metric(
                "combined_framed_rate_bytes_per_second",
                float(full_combined.framed_rate),
                analytic_id,
            ),
            _metric("timestamp_clock_hz", constants.TIMESTAMP_HZ, analytic_id),
            _metric(
                "adc_phase_ticks",
                full_combined.scenario.timing.adc1_phase_ticks,
                analytic_id,
            ),
            _metric(
                "gpio_width_bits",
                full_combined.scenario.layout.packed_width_bits,
                analytic_id,
            ),
        ],
        "acceptance": _acceptance_records(matrix, summaries),
        "limitations": [
            {
                "id": limitation_id,
                "statement": matrix.claim_limitations[limitation_id]["statement"],
                "applies_to_evidence_levels": matrix.claim_limitations[limitation_id][
                    "applies_to_evidence_levels"
                ],
            }
            for limitation_id in experiment["required_limitations"]
        ],
        "artifacts": [],
        "related": [
            "[[ADR-007-Experimental-Aux-Input-Bank]]",
            "[[Experiment-Baseline]]",
            "[[Acquisition-Pipeline]]",
        ],
    }
    json_path, markdown_path = _report_paths(output)
    reporter.write_report_pair(
        matrix,
        report,
        json_path,
        markdown_path,
        root=REPOSITORY_ROOT,
    )
    return json_path, markdown_path


def parse_args(argv: Sequence[str] | None = None) -> argparse.Namespace:
    parser = argparse.ArgumentParser(
        description=(
            "Run every exact auxiliary-input layout/rate workload without hardware, "
            "validate deterministic samples/timestamps, and print analytic framed load."
        )
    )
    parser.add_argument(
        "--pattern",
        action="append",
        choices=[pattern.value for pattern in SyntheticGPIOPattern],
        help="GPIO formula to run; repeat as needed (default: all)",
    )
    parser.add_argument(
        "--frames-per-stream",
        type=_frame_budget,
        default=DEFAULT_FRAMES_PER_STREAM,
        help=f"frames per enabled stream and pattern (default: {DEFAULT_FRAMES_PER_STREAM})",
    )
    parser.add_argument(
        "--output",
        type=Path,
        help="temporary report prefix or .json/.md path; writes both formats",
    )
    return parser.parse_args(argv)


def _print_example(summary: ScenarioSummary, capture: CaptureSummary) -> None:
    parts = [
        f"EXAMPLE scenario={summary.scenario.scenario_id}",
        f"pattern={capture.pattern.value}",
    ]
    adc = capture.decoded_example.get("adc")
    if isinstance(adc, dict):
        parts.append(
            "adc="
            f"pair[{adc['pair_index']}]=(ADC0:{adc['adc0_code']}@{adc['adc0_tick']},"
            f"ADC1:{adc['adc1_code']}@{adc['adc1_tick']})"
        )
    gpio = capture.decoded_example.get("gpio")
    if isinstance(gpio, dict):
        parts.append(
            "gpio="
            f"packed[{gpio['packed_index']}]={gpio['packed_hex']}@{gpio['tick']}"
            f"(primary:{gpio['primary_byte_hex']},"
            f"auxiliary:{gpio['auxiliary_byte_hex'] or 'DISABLED'})"
        )
    print(" ".join(parts))


def main(argv: Sequence[str] | None = None) -> int:
    arguments = parse_args(argv)
    patterns = tuple(
        SyntheticGPIOPattern(value)
        for value in (
            arguments.pattern
            if arguments.pattern is not None
            else [pattern.value for pattern in SyntheticGPIOPattern]
        )
    )
    print(
        "example=aux_input_matrix physical_required=false "
        "evidence=analytic,simulated serial_hardware=false "
        "physical_usb_acceptance=false "
        f"patterns={len(patterns)} frames_per_stream={arguments.frames_per_stream}"
    )
    summaries = run_demo(patterns, frames_per_stream=arguments.frames_per_stream)
    print(
        "CLAIM full_combined_16_input_payload_bytes_per_second="
        f"{FULL_COMBINED_PAYLOAD_HYPOTHESIS_BYTES_PER_SECOND} "
        "status=protocol_load_hypothesis until_measured_on_hardware=true "
        "physical_usb_acceptance=false"
    )
    for summary in summaries:
        framed_ratio = summary.projected_framed_load_ratio
        print(
            f"SCENARIO id={summary.scenario.scenario_id} "
            f"streams={summary.scenario.streams} "
            f"mode={summary.scenario.aux_bank_mode.name} "
            f"profile={summary.scenario.rate_profile.name} "
            "protocol_versions="
            f"{','.join(str(version) for version in sorted({capture.protocol_version for capture in summary.captures}))} "
            f"width_bits={summary.scenario.layout.packed_width_bits} "
            f"logical_items_per_second={summary.logical_item_rate} "
            f"logical_samples_per_second={summary.logical_channel_sample_rate} "
            f"payload_bytes_per_second={_format_fraction(summary.payload_rate)} "
            f"framed_bytes_per_second={_format_fraction(summary.framed_rate)} "
            f"framed_bytes_per_second_decimal={float(summary.framed_rate):.6f} "
            f"frame_coverage_ticks={summary.coverage_ticks} "
            f"frame_coverage_microseconds={summary.coverage_ticks // 8} "
            "projected_usb_framed_load_increase_bytes_per_second="
            f"{_format_fraction(summary.projected_framed_load_increase)} "
            f"projected_usb_framed_load_ratio={_format_fraction(framed_ratio)} "
            f"projected_usb_framed_load_increase_percent="
            f"{float((framed_ratio - 1) * 100):.6f} "
            "physical_usb_acceptance=false"
        )
        for capture in summary.captures:
            _print_example(summary, capture)
    capture_count = sum(len(summary.captures) for summary in summaries)
    print(
        f"PASS scenarios={len(summaries)} captures={capture_count} "
        "adc_phase_and_timestamps=exact primary_formula=exact "
        "auxiliary_formula=exact status_conservation=exact final_cleanup=IDLE"
    )
    if arguments.output is not None:
        json_path, markdown_path = write_report(
            arguments.output,
            patterns,
            arguments.frames_per_stream,
            summaries,
        )
        print(f"report_json={json_path} report_markdown={markdown_path}")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
