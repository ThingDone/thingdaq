"""Offline fake-device coverage for the standalone auxiliary-input rig."""

from __future__ import annotations

import importlib.util
import sys
import time
import unittest
from dataclasses import replace
from pathlib import Path
from types import ModuleType
from unittest.mock import patch

from thingdaq import (
    AuxBankMode,
    DeviceState,
    FrameFlag,
    Source,
    StreamMask,
)
from thingdaq._generated import protocol_v2_constants as constants
from thingdaq.models import AuxiliaryGPIOStatus, Configuration, GPIOLayout
from thingdaq.simulator import SimulatedDevice

ROOT = Path(__file__).resolve().parents[2]
RIG_SCRIPT = ROOT / "firmware/tests/rig_aux_input_capture.py"
FIXTURES = ROOT / "protocol/fixtures-v2"


def _load_rig() -> ModuleType:
    specification = importlib.util.spec_from_file_location(
        "independent_rig_aux_input_capture", RIG_SCRIPT
    )
    if specification is None or specification.loader is None:
        raise RuntimeError("could not load rig_aux_input_capture.py")
    module = importlib.util.module_from_spec(specification)
    sys.modules[specification.name] = module
    specification.loader.exec_module(module)
    return module


rig = _load_rig()


def _fixture_frame(name: str):  # type: ignore[no-untyped-def]
    frames = rig.FrameParser().feed((FIXTURES / name).read_bytes())
    if len(frames) != 1:
        raise AssertionError(f"fixture {name} did not contain exactly one frame")
    return frames[0]


class AuxiliaryPhysicalDevice(SimulatedDevice):
    """Target-shaped protocol peer with exact auxiliary telemetry."""

    def __init__(self, *, fault: str | None = None) -> None:
        super().__init__(build_id="thingdaq-0123456789abcdef")
        self.fault = fault

    def _handle_info(self, request):  # type: ignore[no-untyped-def]
        configuration = self.configuration
        if configuration is None:
            name = "info-response.bin"
        else:
            mode = configuration.aux_bank_mode.name.lower()
            profile = {
                constants.RateProfile.ADC_1MHZ_GPIO_4MHZ: "adc-1mhz-gpio-4mhz",
                constants.RateProfile.ADC_500KHZ_GPIO_2MHZ: "adc-500khz-gpio-2mhz",
                constants.RateProfile.ADC_250KHZ_GPIO_1MHZ: "adc-250khz-gpio-1mhz",
                constants.RateProfile.ADC_125KHZ_GPIO_500KHZ: (
                    "adc-125khz-gpio-500khz"
                ),
            }[configuration.rate_profile]
            name = f"info-{mode}-{profile}-response.bin"
        payload = bytearray(_fixture_frame(name).payload)
        payload[4] = int(self.state)
        payload[45] = int(
            configuration.data_checksum_algorithm
            if configuration is not None
            else constants.DEFAULT_CHECKSUM_ALGORITHM
        )
        payload[58:61] = bytes((0, 8, 0))
        payload[62:66] = bytes((1, 0, 1, 0))
        payload[66:98] = b"thingdaq-0123456789abcdef\0".ljust(32, b"\0")
        payload[324] = int(
            configuration.stream_mask if configuration is not None else StreamMask.NONE
        )
        payload[325] = int(Source.HARDWARE)
        if self.fault == "wrong_mapping":
            payload[384:392] = bytes(reversed(rig.AUX_GPIO_PINS))
        return self._success_response(request, payload)

    def _handle_configure(self, request):  # type: ignore[no-untyped-def]
        if self.state not in {DeviceState.IDLE, DeviceState.CONFIGURED}:
            return self._typed_error(request, constants.ErrorCode.INVALID_STATE)
        configuration = Configuration.from_payload(request.payload)
        if (
            configuration.source is not Source.HARDWARE
            or configuration.stream_mask is StreamMask.NONE
        ):
            return self._typed_error(
                request, constants.ErrorCode.UNSUPPORTED_CONFIGURATION
            )
        self._configuration = configuration
        self._wire_protocol_version = request.header.version
        self._state = DeviceState.CONFIGURED
        return self._success_response(
            request,
            bytes(4)
            + configuration.to_payload(protocol_version=request.header.version),
        )

    def _handle_gpio_capture_diagnostic(self, request):  # type: ignore[no-untyped-def]
        return self._success_response(
            request, _fixture_frame("gpio-capture-diagnostic-response.bin").payload
        )

    def _encode_data_frame(  # type: ignore[no-untyped-def]
        self,
        kind,
        payload,
        flags,
        configuration,
        sequence,
        first_sample_ticks,
        item_count,
    ):
        physical_flags = FrameFlag(int(flags) & ~int(FrameFlag.SYNTHETIC))
        return super()._encode_data_frame(
            kind,
            payload,
            physical_flags,
            configuration,
            sequence,
            first_sample_ticks,
            item_count,
        )

    def status(self):  # type: ignore[no-untyped-def]
        base = super().status()
        active_configuration = self.configuration
        configuration = active_configuration or self._counter_configuration
        if configuration is None:
            return replace(base, source=Source.HARDWARE)
        layout = GPIOLayout.from_mode(configuration.aux_bank_mode)
        adc_frames = self._adc_frames_emitted
        gpio_frames = self._gpio_frames_emitted
        adc_items = adc_frames * layout.adc_items_per_frame
        gpio_items = gpio_frames * layout.items_per_frame
        adc_enabled = bool(configuration.stream_mask & StreamMask.ADC)
        coverage = configuration.rate_timing.frame_coverage_ticks(
            configuration.aux_bank_mode
        )
        retention = 100 * coverage * 1_000_000 // constants.TIMESTAMP_HZ
        auxiliary = AuxiliaryGPIOStatus(
            gpio_item_bytes=layout.item_bytes,
            adc_pair_rate_hz=configuration.rate_timing.adc_pair_rate_hz,
            gpio_sample_rate_hz=configuration.rate_timing.gpio_sample_rate_hz,
            frame_coverage_ticks=coverage,
            packet_retention_us_combined=retention,
            packet_retention_us_single_stream=2 * retention,
        )
        if configuration.aux_bank_mode is AuxBankMode.INPUT:
            auxiliary = AuxiliaryGPIOStatus(
                gpio_item_bytes=layout.item_bytes,
                adc_pair_rate_hz=configuration.rate_timing.adc_pair_rate_hz,
                gpio_sample_rate_hz=configuration.rate_timing.gpio_sample_rate_hz,
                frame_coverage_ticks=coverage,
                packet_retention_us_combined=retention,
                packet_retention_us_single_stream=2 * retention,
                bank_major_loops=(gpio_frames, gpio_frames),
                bank_samples_captured=(gpio_items, gpio_items),
                ready_high_water=(1 if gpio_frames else 0,) * 2,
                paired_major_loops=gpio_frames,
                buffers_completed=gpio_frames,
                buffers_acquired=gpio_frames,
                buffers_released=gpio_frames,
                samples_captured=gpio_items,
                samples_joined=gpio_items,
                samples_delivered=gpio_items,
                cache_dma_discards=2 * gpio_frames,
                cache_cpu_invalidations=2 * gpio_frames,
            )
        return replace(
            base,
            source=Source.HARDWARE,
            gpio_samples_captured=gpio_items,
            gpio_samples_packed=gpio_items,
            gpio_samples_framed=gpio_items,
            gpio_samples_transmitted=gpio_items,
            gpio_dma_major_loops=gpio_frames,
            gpio_buffers_completed=gpio_frames,
            gpio_buffers_acquired=gpio_frames,
            gpio_buffers_released=gpio_frames,
            gpio_samples_delivered=gpio_items,
            gpio_frames_produced=gpio_frames,
            gpio_samples_produced=gpio_items,
            gpio_frames_packed=gpio_frames,
            gpio_raw_ready_high_water=1 if gpio_frames else 0,
            gpio_packed_ready_high_water=1 if gpio_frames else 0,
            gpio_cache_dma_discards=gpio_frames,
            gpio_cache_cpu_invalidations=gpio_frames,
            gpio_processing_cpu_basis_points=250 if gpio_frames else 0,
            adc0_dma_major_loops=adc_frames if adc_enabled else 0,
            adc1_dma_major_loops=adc_frames if adc_enabled else 0,
            adc0_dma_results=adc_items if adc_enabled else 0,
            adc1_dma_results=adc_items if adc_enabled else 0,
            adc_paired_major_loops=adc_frames if adc_enabled else 0,
            adc_buffers_completed=adc_frames if adc_enabled else 0,
            adc_buffers_acquired=adc_frames if adc_enabled else 0,
            adc_buffers_released=adc_frames if adc_enabled else 0,
            adc_pairs_captured=adc_items if adc_enabled else 0,
            adc_pairs_delivered=adc_items if adc_enabled else 0,
            adc_pairs_framed=adc_items if adc_enabled else 0,
            adc_pairs_transmitted=adc_items if adc_enabled else 0,
            adc_raw_ready_high_water=1 if adc_frames else 0,
            adc_cache_dma_discards=adc_frames if adc_enabled else 0,
            adc_cache_cpu_invalidations=adc_frames if adc_enabled else 0,
            configuration=active_configuration,
            auxiliary_gpio=auxiliary,
        )

    def _handle_status(self, request):  # type: ignore[no-untyped-def]
        payload = bytearray(
            self.status().to_payload(protocol_version=request.header.version)
        )
        configuration = self.configuration or self._counter_configuration
        if request.header.version == constants.PROTOCOL_VERSION and configuration:
            layout = configuration.gpio_layout
            timing = configuration.rate_timing
            coverage = timing.frame_coverage_ticks(configuration.aux_bank_mode)
            payload[constants.STATUS_RESPONSE_STREAM_MASK_OFFSET] = int(
                configuration.stream_mask
            )
            payload[constants.STATUS_RESPONSE_SOURCE_OFFSET] = int(Source.HARDWARE)
            payload[constants.STATUS_RESPONSE_AUX_BANK_MODE_OFFSET] = int(
                configuration.aux_bank_mode
            )
            payload[constants.STATUS_RESPONSE_RATE_PROFILE_OFFSET] = int(
                configuration.rate_profile
            )
            payload[constants.STATUS_RESPONSE_GPIO_ITEM_BYTES_OFFSET] = (
                layout.item_bytes
            )
            for offset, value in (
                (
                    constants.STATUS_RESPONSE_ADC_PAIR_RATE_HZ_OFFSET,
                    timing.adc_pair_rate_hz,
                ),
                (
                    constants.STATUS_RESPONSE_GPIO_SAMPLE_RATE_HZ_OFFSET,
                    timing.gpio_sample_rate_hz,
                ),
                (constants.STATUS_RESPONSE_FRAME_COVERAGE_TICKS_OFFSET, coverage),
                (
                    constants.STATUS_RESPONSE_PACKET_RETENTION_US_COMBINED_OFFSET,
                    100 * coverage * 1_000_000 // constants.TIMESTAMP_HZ,
                ),
                (
                    constants.STATUS_RESPONSE_PACKET_RETENTION_US_SINGLE_STREAM_OFFSET,
                    200 * coverage * 1_000_000 // constants.TIMESTAMP_HZ,
                ),
            ):
                payload[offset : offset + 4] = int(value).to_bytes(4, "little")
        if self.fault == "skew":
            offset = constants.STATUS_RESPONSE_PAIRED_GPIO_GENERATION_SKEW_EVENTS_OFFSET
            payload[offset : offset + 8] = (1).to_bytes(8, "little")
        elif self.fault == "saturation":
            offset = constants.STATUS_RESPONSE_PACKET_READY_DEPTH_OFFSET
            payload[offset : offset + 2] = (
                rig.PACKET_READY_QUEUE_CAPACITY + 1
            ).to_bytes(2, "little")
        return self._success_response(request, payload)


class PacedAuxSerial:
    """Partial-read PySerial peer paced from the selected frame coverage."""

    def __init__(self, *, fault: str | None = None) -> None:
        self.device = AuxiliaryPhysicalDevice(fault=fault)
        self.pending = bytearray(b"reset noise\r\n\xef\xbe")
        self.is_open = True
        self.fault = fault
        self.data_frames = 0
        self.next_frame_at = time.monotonic()
        self.was_running = False

    def write(self, data: bytes) -> int:
        if not self.is_open:
            raise OSError("fake auxiliary device disconnected")
        before = self.device.state
        for response in self.device.receive(data):
            self.pending.extend(response)
        if (
            before is not DeviceState.RUNNING
            and self.device.state is DeviceState.RUNNING
        ):
            self.next_frame_at = time.monotonic()
        return len(data)

    def read(self, size: int = 1) -> bytes:
        if not self.is_open:
            raise OSError("fake auxiliary device disconnected")
        self._pace(size)
        if not self.pending:
            time.sleep(0.00005)
            return b""
        count = min(size, len(self.pending))
        result = bytes(self.pending[:count])
        del self.pending[:count]
        return result

    def close(self) -> None:
        self.is_open = False

    def _pace(self, size: int) -> None:
        if self.device.state is not DeviceState.RUNNING:
            return
        configuration = self.device.configuration
        assert configuration is not None
        stream_count = int(bool(configuration.stream_mask & StreamMask.ADC)) + 1
        coverage_seconds = (
            configuration.rate_timing.frame_coverage_ticks(configuration.aux_bank_mode)
            / constants.TIMESTAMP_HZ
        )
        interval = coverage_seconds / stream_count
        now = time.monotonic()
        while self.next_frame_at <= now and len(self.pending) < max(size, 65_536):
            frame = self.device.next_data_frame()
            if frame is None:
                break
            self.data_frames += 1
            if self.fault == "loss" and self.data_frames == 3:
                pass
            elif self.fault == "disconnect" and self.data_frames == 3:
                self.is_open = False
                raise OSError("deterministic fake-device disconnect")
            else:
                self.pending.extend(frame)
            self.next_frame_at += interval


class AuxiliaryRigFakeDeviceTests(unittest.TestCase):
    def _run(self, case, profile, *, fault: str | None = None):  # type: ignore[no-untyped-def]
        port = PacedAuxSerial(fault=fault)
        with (
            patch.object(rig, "STARTUP_DRAIN_SECONDS", 0.001),
            patch.object(rig, "STOP_DRAIN_QUIET_SECONDS", 0.001),
            patch.object(rig, "emit_event", lambda *_args, **_kwargs: None),
        ):
            return rig.run_acceptance(
                port,
                case=case,
                profile=profile,
                capture_seconds=1.1,
                warmup_seconds=0.0,
                status_interval_seconds=0.02,
                checksum_algorithm=rig.CHECKSUM_ADLER32,
                expected_build_id="thingdaq-0123456789abcdef",
                expected_hardware_serial=0x12345678,
                fixture=None,
            )

    def test_every_control_input_gpio_combined_profile_is_accepted(self) -> None:
        for case in rig.RUN_CASES.values():
            for profile in rig.PROFILES:
                with self.subTest(case=case.name, profile=profile.name):
                    result = self._run(case, profile)
                    self.assertEqual([], result.evidence.failures)
                    self.assertEqual("NOT_RUN", result.stimulus_grade)
                    self.assertGreaterEqual(int(result.metrics["status_count"]), 2)

    def test_loss_and_disconnect_fail_closed_and_attempt_cleanup(self) -> None:
        case = rig.RUN_CASES["INPUT_COMBINED"]
        profile = rig.PROFILES[-1]
        for fault, expected in (
            ("loss", "continuity"),
            ("disconnect", "disconnect"),
        ):
            with self.subTest(fault=fault):
                result = self._run(case, profile, fault=fault)
                self.assertTrue(result.evidence.failures)
                self.assertIn(
                    expected,
                    " ".join(result.evidence.failures).lower(),
                )

    def test_skew_wrong_mapping_and_saturation_fake_runs_are_rejected(self) -> None:
        case = rig.RUN_CASES["INPUT_COMBINED"]
        profile = rig.PROFILES[0]
        for fault, expected in (
            ("skew", "skew"),
            ("wrong_mapping", "pin map"),
            ("saturation", "exceeds"),
        ):
            with self.subTest(fault=fault):
                result = self._run(case, profile, fault=fault)
                self.assertTrue(result.evidence.failures)
                self.assertIn(expected, " ".join(result.evidence.failures).lower())

    def test_malformed_control_is_rejected_without_leaving_idle(self) -> None:

        malformed = bytearray(rig.encode_request(rig.INFO_REQUEST, 7))
        malformed[4] = 0xFF
        peer = AuxiliaryPhysicalDevice()
        self.assertEqual((), peer.receive(malformed))
        self.assertEqual(DeviceState.IDLE, peer.state)

    def test_fixture_declaration_is_required_before_stimulus_is_graded(self) -> None:
        diagnostic = rig.decode_capture_diagnostic(
            _fixture_frame("gpio-capture-diagnostic-response.bin")
        )
        evidence = rig.Evidence()
        self.assertEqual(
            "NOT_RUN", rig.grade_capture_diagnostic(evidence, diagnostic, None)
        )
        self.assertEqual([], evidence.failures)
        with self.assertRaisesRegex(ValueError, "authorized=true"):
            rig.load_fixture_declaration(
                '{"schema":"thingdaq.aux-input-stimulus/v1","authorized":false}'
            )


if __name__ == "__main__":
    unittest.main()
