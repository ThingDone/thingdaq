"""Offline fault-matrix tests for the standalone clock-comparison rig."""

from __future__ import annotations

import ast
import importlib.util
import io
import json
import os
import struct
import sys
import time
import unittest
from dataclasses import replace
from pathlib import Path
from types import ModuleType
from unittest.mock import patch

from thingdaq import (
    AdcTriggerMetadata,
    ClockHealthError,
    ClockHealthFlag,
    ClockHealthSample,
    ClockProfile,
    ClockProfileMetadata,
    DeviceInfo,
    Status,
    TemperatureStatus,
)
from thingdaq._generated import protocol_constants as constants

ROOT = Path(__file__).resolve().parents[2]
RIG_SCRIPT = ROOT / "firmware/tests/rig_clock_comparison.py"
COMBINED_TEST = ROOT / "firmware/tests/test_rig_combined_capture.py"


def _load_module(name: str, path: Path) -> ModuleType:
    specification = importlib.util.spec_from_file_location(name, path)
    if specification is None or specification.loader is None:
        raise RuntimeError(f"could not load {path}")
    module = importlib.util.module_from_spec(specification)
    sys.modules[name] = module
    specification.loader.exec_module(module)
    return module


rig = _load_module("independent_rig_clock_comparison", RIG_SCRIPT)
combined_fixture = _load_module("clock_combined_fixture", COMBINED_TEST)


def _ready_trigger(profile_id: ClockProfile) -> AdcTriggerMetadata:
    spec = constants.CLOCK_PROFILE_SPECS[profile_id]
    return replace(
        combined_fixture._ready_trigger(),
        dwt_clock_hz=spec.dwt_hz,
        ipg_clock_hz=spec.ipg_hz,
        initial_delays=(0, spec.phase_ipg_cycles),
        effective_delays=(1, spec.phase_ipg_cycles + 1),
        phase_ipg_cycles=spec.phase_ipg_cycles,
        trigger_counter_configured=(0, spec.phase_ipg_cycles),
        completion_delta_cycles=spec.phase_dwt_cycles,
        completion_expected_delta_cycles=spec.phase_dwt_cycles,
        completion_tolerance_cycles=spec.phase_tolerance_dwt_cycles,
    )


class ClockComparisonDevice(combined_fixture.PhysicalCombinedDevice):
    """Physical-shaped peer with selectable profile and injected fault."""

    def __init__(self, profile_id: ClockProfile, fault: str | None = None) -> None:
        super().__init__()
        self.profile = ClockProfileMetadata.for_profile(profile_id)
        self.trigger = _ready_trigger(profile_id)
        self.fault = fault
        self.health_sequence = 0
        self.running_health_samples = 0
        self.loss_injected = False

    def _handle_info(self, request):  # type: ignore[no-untyped-def]
        configuration = self.configuration
        metadata = combined_fixture._ready_metadata()
        metadata["adc_trigger"] = self.trigger
        info = DeviceInfo(
            device_state=self.state,
            build_id="thingdaq-0123456789abcdef",
            clock_profile=self.profile,
            hardware_serial=12_345_670,
            firmware_version=(0, 7, 0),
            board_id=constants.BoardId.TEENSY_40,
            mcu_id=constants.McuId.IMXRT1062,
            supported_stream_mask=(
                constants.StreamMask.ADC | constants.StreamMask.GPIO
            ),
            supported_source_mask=0x03,
            supported_configuration_mask=constants.ConfigurationProfile(
                constants.SUPPORTED_CONFIGURATION_MASK
            ),
            applied_stream_mask=(
                configuration.stream_mask
                if configuration is not None
                else constants.StreamMask.NONE
            ),
            applied_source=constants.Source.HARDWARE,
            data_checksum_algorithm=(
                configuration.data_checksum_algorithm
                if configuration is not None
                else constants.DEFAULT_CHECKSUM_ALGORITHM
            ),
            capability_bits=constants.Capability(constants.KNOWN_CAPABILITY_MASK),
            gpio_capture_diagnostic_mode=(
                constants.GpioCaptureDiagnosticMode.NON_DRIVING_CAPTURE
            ),
            gpio_capture_diagnostic_flags=(
                constants.GpioCaptureDiagnosticFlag.AVAILABLE
                | constants.GpioCaptureDiagnosticFlag.DECLARATION_VALID
            ),
            adc_ipg_clock_hz=self.profile.ipg_clock_hz,
            adc_clock_hz=self.profile.adc_clock_hz,
            **metadata,
        )
        return self._success_response(request, info.to_payload())

    def status(self) -> Status:
        base = super().status()
        running = self.state is constants.DeviceState.RUNNING
        next_sequence = self.health_sequence + 1
        if (
            self.fault == "telemetry_regression"
            and running
            and (self.running_health_samples >= 1)
        ):
            sequence = self.health_sequence
        else:
            sequence = next_sequence
            self.health_sequence = next_sequence
        if running:
            self.running_health_samples += 1

        temperature_valid = self.fault != "temperature_sensor"
        flags = ClockHealthFlag.CLOCKS_VALID | ClockHealthFlag.UTILIZATION_VALID
        errors = ClockHealthError.NONE
        temperature_status = TemperatureStatus.VALID
        temperature: int | None = 42_125
        temperature_errors = 0
        if not temperature_valid:
            temperature_status = TemperatureStatus.NOT_READY
            temperature = None
            temperature_errors = max(1, sequence)
            errors |= ClockHealthError.TEMPERATURE_NOT_READY
        else:
            flags |= ClockHealthFlag.TEMPERATURE_VALID

        trigger_errors = 1 if self.fault == "trigger_error" and running else 0
        health = ClockHealthSample(
            sample_sequence=sequence,
            sample_ticks=sequence * constants.FRAME_COVERAGE_TICKS,
            clock_profile=self.profile,
            temperature_status=temperature_status,
            flags=flags,
            runtime_cpu_clock_hz=self.profile.cpu_clock_hz,
            runtime_ipg_clock_hz=self.profile.ipg_clock_hz,
            runtime_adc_clock_hz=self.profile.adc_clock_hz,
            runtime_pit_clock_hz=self.profile.pit_clock_hz,
            runtime_dwt_clock_hz=self.profile.dwt_clock_hz,
            temperature_millidegrees_celsius=temperature,
            acquisition_service_utilization_basis_points=1_200,
            usb_service_utilization_basis_points=600,
            adc_raw_ready_high_water=base.adc_raw_ready_high_water,
            gpio_raw_ready_high_water=base.gpio_raw_ready_high_water,
            packet_owned_high_water=base.packet_owned_high_water,
            usb_command_queue_high_water=base.usb_command_queue_high_water,
            usb_response_queue_high_water=base.usb_response_queue_high_water,
            error_flags=errors,
            temperature_error_count=temperature_errors,
            adc_trigger_error_count=trigger_errors,
        )
        updates: dict[str, object] = {
            "clock_health": health,
            "adc_ipg_clock_hz": self.profile.ipg_clock_hz,
            "adc_clock_hz": self.profile.adc_clock_hz,
            "adc_trigger": self.trigger,
            "adc_cache_dma_discards": base.adc_frames_emitted,
            "adc_cache_cpu_invalidations": base.adc_frames_emitted,
            "gpio_cache_dma_discards": base.gpio_frames_emitted,
            "gpio_cache_cpu_invalidations": base.gpio_frames_emitted,
            "gpio_buffers_completed": base.gpio_frames_emitted,
            "gpio_buffers_acquired": base.gpio_frames_emitted,
            "gpio_buffers_released": base.gpio_frames_emitted,
            "gpio_samples_delivered": (
                base.gpio_frames_emitted * constants.GPIO_SAMPLES_PER_FRAME
            ),
            "gpio_stop_samples_discarded": base.gpio_raw_samples_lost,
            "gpio_frames_produced": base.gpio_frames_emitted,
            "gpio_samples_produced": (
                base.gpio_frames_emitted * constants.GPIO_SAMPLES_PER_FRAME
            ),
            "gpio_frames_packed": base.gpio_frames_emitted,
            "adc_frames_consumed": base.adc_frames_emitted,
            "adc_pairs_consumed": (
                base.adc_frames_emitted * constants.ADC_PAIRS_PER_FRAME
            ),
        }
        if trigger_errors:
            updates["adc_etc_error_events"] = 1
        if self.fault == "counter_conservation" and running:
            updates["adc_items_generated"] = base.adc_items_generated + 1
        return replace(base, **updates)

    def _handle_gpio_capture_diagnostic(self, request):  # type: ignore[no-untyped-def]
        payload = bytearray(combined_fixture._capture_payload())
        struct.pack_into(
            "<I",
            payload,
            rig.CAPTURE_U32_FIELDS["dwt_counter_hz"],
            self.profile.dwt_clock_hz,
        )
        return self._success_response(request, payload)

    def _next_adc_frame(self, configuration):  # type: ignore[no-untyped-def]
        if (
            self.fault == "loss"
            and not self.loss_injected
            and self._adc_frames_emitted >= 1
        ):
            self._adc_sequence += 1
            self._adc_first_ticks += constants.FRAME_COVERAGE_TICKS
            self._adc_item_index += constants.ADC_PAIRS_PER_FRAME
            self.loss_injected = True
        return super()._next_adc_frame(configuration)


class ClockComparisonSerial:
    """Partial-I/O serial peer with configurable pacing and response loss."""

    def __init__(
        self,
        device: ClockComparisonDevice,
        *,
        rate_factor: float = 1.0,
        drop_running_status: bool = False,
        drop_stop: bool = False,
    ) -> None:
        self.device = device
        self.timeout = 0.001
        self.write_timeout = 0.1
        self.is_open = True
        self.pending = bytearray(b"clock rig reset noise\r\n\xef\xbe")
        self.read_pattern = (1, 509, 2_048, 8_192, 37, 65_536)
        self.write_pattern = (1, 0, 5, 17, 128, 4_096)
        self.read_index = 0
        self.write_index = 0
        self.read_counts: list[int] = []
        self.write_counts: list[int] = []
        self.frame_interval = (
            constants.FRAME_COVERAGE_TICKS / constants.TIMESTAMP_HZ / 2
        ) * rate_factor
        self.next_frame_at = time.monotonic()
        self.drop_running_status = drop_running_status
        self.drop_stop = drop_stop

    def read(self, size: int = 1) -> bytes:
        if not self.is_open:
            raise RuntimeError("fake serial port is closed")
        self._pace_data()
        if not self.pending:
            time.sleep(min(self.timeout, 0.0002))
            self._pace_data()
        if not self.pending:
            self.read_counts.append(0)
            return b""
        limit = self.read_pattern[self.read_index % len(self.read_pattern)]
        self.read_index += 1
        count = min(size, limit, len(self.pending))
        result = bytes(self.pending[:count])
        del self.pending[:count]
        self.read_counts.append(count)
        return result

    def write(self, data: bytes | bytearray | memoryview) -> int:
        if not self.is_open:
            raise RuntimeError("fake serial port is closed")
        wire = bytes(data)
        limit = self.write_pattern[self.write_index % len(self.write_pattern)]
        self.write_index += 1
        count = min(len(wire), limit)
        self.write_counts.append(count)
        if not count:
            return 0
        was_running = self.device.state is constants.DeviceState.RUNNING
        responses = self.device.receive(wire[:count])
        for response in responses:
            kind = response[5]
            if (
                self.drop_running_status
                and was_running
                and kind == int(constants.FrameKind.GET_STATUS_RESPONSE)
            ):
                continue
            if self.drop_stop and kind == int(constants.FrameKind.STOP_RESPONSE):
                continue
            self.pending.extend(response)
        if self.device.trailing_data:
            for trailing in self.device.trailing_data:
                self.pending.extend(trailing)
            self.device.trailing_data.clear()
        if not was_running and self.device.state is constants.DeviceState.RUNNING:
            self.next_frame_at = time.monotonic()
        return count

    def close(self) -> None:
        self.is_open = False

    def _pace_data(self) -> None:
        if self.pending or self.device.state is not constants.DeviceState.RUNNING:
            return
        now = time.monotonic()
        if now < self.next_frame_at:
            time.sleep(min(self.timeout, self.next_frame_at - now))
            now = time.monotonic()
        if now < self.next_frame_at:
            return
        wire = self.device.next_data_frame()
        if wire is not None:
            self.pending.extend(wire)
            self.next_frame_at += self.frame_interval


class ClockComparisonRigTests(unittest.TestCase):
    def _run_case(
        self,
        profile_id: ClockProfile,
        *,
        fault: str | None = None,
        rate_factor: float = 1.0,
        drop_running_status: bool = False,
        drop_stop: bool = False,
    ) -> tuple[int, dict[str, object], ClockComparisonSerial, str]:
        device = ClockComparisonDevice(profile_id, fault)
        serial_peer = ClockComparisonSerial(
            device,
            rate_factor=rate_factor,
            drop_running_status=drop_running_status,
            drop_stop=drop_stop,
        )
        profile = rig.CLOCK_PROFILE_SPECS[int(profile_id)]
        environment = {
            "SERIAL_PORT": "fake-clock-port",
            "CLOCK_COMPARISON_MODE": "smoke",
            "CLOCK_CAPTURE_SECONDS": "0.12",
            "CLOCK_WARMUP_SECONDS": "0.02",
            "CLOCK_STATUS_INTERVAL_SECONDS": "0.02",
            "EXPECTED_BUILD_ID": "thingdaq-0123456789abcdef",
            "EXPECTED_HARDWARE_SERIAL": "12345670",
            "EXPECTED_CLOCK_PROFILE": str(
                600 if profile_id is ClockProfile.PRODUCTION_600_MHZ else 528
            ),
            "EXPECTED_FQBN": profile.fqbn,
        }
        output = io.StringIO()
        with (
            patch.object(rig, "STARTUP_DRAIN_SECONDS", 0.001),
            patch.object(rig, "SYNC_DEADLINE_SECONDS", 0.08),
            patch.object(rig, "COMMAND_DEADLINE_SECONDS", 0.06),
            patch.object(rig, "DIAGNOSTIC_DEADLINE_SECONDS", 0.06),
            patch.object(rig, "STOP_DRAIN_DEADLINE_SECONDS", 0.04),
            patch.object(rig, "STOP_DRAIN_QUIET_SECONDS", 0.001),
            patch.object(rig, "RATE_TOLERANCE_FRACTION", 0.35),
            patch.object(rig.serial, "Serial", return_value=serial_peer),
            patch.dict(os.environ, environment, clear=True),
            patch("sys.stdout", output),
        ):
            exit_code = rig.main()

        report = output.getvalue()
        result_lines = [
            line.removeprefix(rig.CLOCK_RESULT_PREFIX)
            for line in report.splitlines()
            if line.startswith(rig.CLOCK_RESULT_PREFIX)
        ]
        self.assertEqual(1, len(result_lines), report)
        summary = json.loads(result_lines[0])
        self.assertFalse(serial_peer.is_open)
        return exit_code, summary, serial_peer, report

    def test_program_remains_one_file_standard_library_plus_pyserial(self) -> None:
        tree = ast.parse(RIG_SCRIPT.read_text(encoding="utf-8"))
        imports: set[str] = set()
        for node in ast.walk(tree):
            if isinstance(node, ast.Import):
                imports.update(alias.name.split(".", 1)[0] for alias in node.names)
            elif isinstance(node, ast.ImportFrom) and node.module is not None:
                imports.add(node.module.split(".", 1)[0])
        self.assertEqual(
            {
                "__future__",
                "collections",
                "dataclasses",
                "itertools",
                "json",
                "math",
                "os",
                "re",
                "resource",
                "serial",
                "statistics",
                "struct",
                "sys",
                "time",
                "typing",
                "zlib",
            },
            imports,
        )
        self.assertNotIn("thingdaq", imports)

    def test_full_fake_runs_pass_for_both_exact_profiles(self) -> None:
        for profile_id in ClockProfile:
            with self.subTest(profile=profile_id.name):
                exit_code, summary, peer, report = self._run_case(profile_id)
                self.assertEqual(0, exit_code, report)
                self.assertEqual("PASS", summary["result"])
                self.assertEqual("PASS", summary["performance_result"])
                self.assertEqual("EVIDENCE_READY", summary["thermal_result"])
                self.assertEqual(
                    rig.CLOCK_PROFILE_SPECS[int(profile_id)].fqbn,
                    summary["identity"]["clock_profile"]["fqbn"],
                )
                self.assertTrue(summary["cleanup"]["idle_confirmed"])
                self.assertEqual(constants.DeviceState.IDLE, peer.device.state)
                self.assertIn(0, peer.write_counts)

    def test_loss_trigger_rate_and_counter_faults_are_firmware_failures(self) -> None:
        cases = (
            ("loss", 1.0, "sequence"),
            ("trigger_error", 1.0, "adc_etc_error_events"),
            ("counter_conservation", 1.0, "adc_items_generated"),
            (None, 2.5, "rate.adc_pair_rate_hz"),
        )
        for fault, rate_factor, reason in cases:
            with self.subTest(fault=fault or "rate_drift"):
                exit_code, summary, peer, report = self._run_case(
                    ClockProfile.EXPERIMENTAL_528_MHZ,
                    fault=fault,
                    rate_factor=rate_factor,
                )
                self.assertEqual(1, exit_code, report)
                self.assertEqual("FAIL", summary["result"])
                self.assertEqual("firmware", summary["failure_class"])
                self.assertIn(reason, json.dumps(summary))
                self.assertTrue(summary["cleanup"]["idle_confirmed"])
                self.assertEqual(constants.DeviceState.IDLE, peer.device.state)

    def test_telemetry_regression_and_sensor_failure_have_distinct_results(
        self,
    ) -> None:
        exit_code, summary, _peer, report = self._run_case(
            ClockProfile.PRODUCTION_600_MHZ,
            fault="telemetry_regression",
        )
        self.assertEqual(1, exit_code, report)
        self.assertEqual("FAIL", summary["result"])
        self.assertEqual("firmware", summary["failure_class"])
        self.assertIn("sample sequence did not advance", summary["reason"])

        exit_code, summary, _peer, report = self._run_case(
            ClockProfile.EXPERIMENTAL_528_MHZ,
            fault="temperature_sensor",
        )
        self.assertEqual(3, exit_code, report)
        self.assertEqual("INCONCLUSIVE", summary["result"])
        self.assertEqual("PASS", summary["performance_result"])
        self.assertEqual("telemetry", summary["failure_class"])
        self.assertEqual("INCONCLUSIVE", summary["thermal_result"])
        self.assertIn("steady-state temperature", summary["reason"])

    def test_service_timeout_and_cleanup_failure_are_infrastructure_results(
        self,
    ) -> None:
        exit_code, summary, _peer, report = self._run_case(
            ClockProfile.EXPERIMENTAL_528_MHZ,
            drop_running_status=True,
        )
        self.assertEqual(2, exit_code, report)
        self.assertEqual("INCONCLUSIVE", summary["result"])
        self.assertEqual("infrastructure", summary["failure_class"])
        self.assertIn("DeadlineExpired", summary["reason"])
        self.assertTrue(summary["cleanup"]["idle_confirmed"])

        exit_code, summary, _peer, report = self._run_case(
            ClockProfile.PRODUCTION_600_MHZ,
            drop_stop=True,
        )
        self.assertEqual(2, exit_code, report)
        self.assertEqual("INCONCLUSIVE", summary["result"])
        self.assertEqual("infrastructure", summary["failure_class"])
        self.assertFalse(summary["cleanup"]["stop_succeeded"])
        self.assertIn("DeadlineExpired", summary["cleanup"]["error"])


if __name__ == "__main__":
    unittest.main()
