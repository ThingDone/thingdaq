"""Offline verification for the independent Phase 08 combined rig."""

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
from contextlib import redirect_stdout
from itertools import pairwise
from pathlib import Path
from types import ModuleType
from typing import TypedDict
from unittest.mock import patch

from teensy_daq._generated import protocol_constants as constants
from teensy_daq.models import AdcTriggerMetadata, Configuration, DeviceInfo, Status
from teensy_daq.protocol import encode_frame
from teensy_daq.simulator import SimulatedDevice
from teensy_daq.synthetic import synthetic_adc_payload, synthetic_gpio_payload

ROOT = Path(__file__).resolve().parents[2]
RIG_SCRIPT = ROOT / "firmware" / "tests" / "rig_combined_capture.py"
FIXTURES = ROOT / "protocol" / "fixtures"
SUCCESS_PREFIX = struct.pack("<BBH", 0, 0, 0)


def _load_rig_script() -> ModuleType:
    specification = importlib.util.spec_from_file_location(
        "independent_rig_combined_capture",
        RIG_SCRIPT,
    )
    if specification is None or specification.loader is None:
        raise RuntimeError("could not load rig_combined_capture.py")
    module = importlib.util.module_from_spec(specification)
    sys.modules[specification.name] = module
    specification.loader.exec_module(module)
    return module


rig = _load_rig_script()

READY_FLAGS = (
    constants.AdcConfigurationFlag.INITIALIZED
    | constants.AdcConfigurationFlag.NO_HARDWARE_AVERAGING
    | constants.AdcConfigurationFlag.HIGH_SPEED
    | constants.AdcConfigurationFlag.SHORTEST_SAMPLE
    | constants.AdcConfigurationFlag.ROUTES_VALIDATED
    | constants.AdcConfigurationFlag.CONFIGURATION_READBACK_VALID
    | constants.AdcConfigurationFlag.CALIBRATION_COMPLETE
    | constants.AdcConfigurationFlag.PRIMARY_12_BIT
)


class ReadyAdcMetadata(TypedDict):
    adc_configuration_flags: constants.AdcConfigurationFlag
    adc_calibration_states: tuple[
        constants.AdcCalibrationState,
        constants.AdcCalibrationState,
    ]
    adc_calibration_cycles: tuple[int, int]
    adc_trigger: AdcTriggerMetadata


def _ready_trigger() -> AdcTriggerMetadata:
    return AdcTriggerMetadata(
        configuration_flags=constants.AdcTriggerConfigurationFlag(
            constants.KNOWN_ADC_TRIGGER_CONFIGURATION_FLAG_MASK
        ),
        ccm_cscmr1_configured=rig.CCM_PERCLK_24MHZ,
        ccm_ccgr1_configured=(
            rig.CCM_PIT_GATE_MASK | rig.CCM_ADC1_GATE_MASK | rig.CCM_ADC2_GATE_MASK
        ),
        ccm_ccgr2_configured=rig.CCM_XBAR_GATE_MASK,
        pair_tctrl_configured=rig.PIT_TCTRL_CHAIN,
        trigger_counter_configured=rig.ADC_TRIGGER_INITIAL_DELAYS,
        chain_configured=(rig.ADC0_CHAIN_CONFIGURED, rig.ADC1_CHAIN_CONFIGURED),
        completion_counts=(1, 1),
        completion_delta_cycles=rig.ADC_COMPLETION_EXPECTED_DWT_CYCLES,
        diagnostic_elapsed_cycles=600,
        xbar_sel_configured=(0x3900, 0x3900),
    )


def _ready_metadata() -> ReadyAdcMetadata:
    return {
        "adc_configuration_flags": READY_FLAGS,
        "adc_calibration_states": (
            constants.AdcCalibrationState.SUCCEEDED,
            constants.AdcCalibrationState.SUCCEEDED,
        ),
        "adc_calibration_cycles": (12_345, 23_456),
        "adc_trigger": _ready_trigger(),
    }


def _capture_payload() -> bytes:
    wire = (FIXTURES / "gpio-capture-diagnostic-response.bin").read_bytes()
    return wire[constants.HEADER_SIZE : -constants.TRAILER_SIZE]


class PhysicalCombinedDevice(SimulatedDevice):
    """Physical-shaped combined peer with fully reconciled telemetry."""

    def __init__(self) -> None:
        super().__init__(build_id="tdaq-0123456789abcdef")
        self.commands_accepted = 0
        self.trailing_data: list[bytes] = []

    def _reset_counters(self) -> None:
        super()._reset_counters()
        self.commands_accepted = 0

    def _handle_info(self, request):  # type: ignore[no-untyped-def]
        configuration = self.configuration
        info = DeviceInfo(
            device_state=self.state,
            build_id="tdaq-0123456789abcdef",
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
            **_ready_metadata(),
        )
        return self._success_response(request, info.to_payload())

    def _handle_configure(self, request):  # type: ignore[no-untyped-def]
        configuration = Configuration.from_payload(request.payload)
        if not (
            self._state
            in {constants.DeviceState.IDLE, constants.DeviceState.CONFIGURED}
            and configuration.stream_mask
            == constants.StreamMask.ADC | constants.StreamMask.GPIO
            and configuration.source is constants.Source.HARDWARE
            and configuration.data_checksum_algorithm
            in constants.SUPPORTED_CHECKSUM_ALGORITHMS
        ):
            return self._typed_error(
                request, constants.ErrorCode.UNSUPPORTED_CONFIGURATION
            )
        self._configuration = configuration
        self._state = constants.DeviceState.CONFIGURED
        return self._success_response(
            request, SUCCESS_PREFIX + configuration.to_payload()
        )

    def _handle_gpio_capture_diagnostic(self, request):  # type: ignore[no-untyped-def]
        return self._success_response(request, _capture_payload())

    def _handle_reset_stats(self, request):  # type: ignore[no-untyped-def]
        response = super()._handle_reset_stats(request)
        self.commands_accepted = 1
        return response

    def _handle_start(self, request):  # type: ignore[no-untyped-def]
        response = super()._handle_start(request)
        self.commands_accepted = 1
        return response

    def _handle_status(self, request):  # type: ignore[no-untyped-def]
        response = super()._handle_status(request)
        self.commands_accepted += 1
        return response

    def _handle_stop(self, request):  # type: ignore[no-untyped-def]
        configuration = self._configuration
        if configuration is not None:
            if self._adc_frames_emitted < self._gpio_frames_emitted:
                self.trailing_data.append(self._next_adc_frame(configuration))
            elif self._gpio_frames_emitted < self._adc_frames_emitted:
                self.trailing_data.append(self._next_gpio_frame(configuration))
        response = super()._handle_stop(request)
        self.commands_accepted += 1
        return response

    def status(self) -> Status:
        configuration = self._configuration
        adc_frames = self._adc_frames_emitted
        gpio_frames = self._gpio_frames_emitted
        adc_items = adc_frames * constants.ADC_PAIRS_PER_FRAME
        gpio_items = gpio_frames * constants.GPIO_SAMPLES_PER_FRAME
        adc_payload = adc_frames * constants.DATA_PAYLOAD_BYTES
        gpio_payload = gpio_frames * constants.DATA_PAYLOAD_BYTES
        adc_framed = adc_frames * constants.DATA_FRAME_BYTES
        gpio_framed = gpio_frames * constants.DATA_FRAME_BYTES
        any_frames = bool(adc_frames or gpio_frames)
        stopped = self._state is constants.DeviceState.IDLE and any_frames
        adc_stop_tail = 37 if stopped else 0
        gpio_stop_tail = 149 if stopped else 0
        return Status(
            device_state=self._state,
            stream_mask=(
                configuration.stream_mask
                if configuration is not None
                else constants.StreamMask.NONE
            ),
            source=constants.Source.HARDWARE,
            data_checksum_algorithm=(
                configuration.data_checksum_algorithm
                if configuration is not None
                else constants.DEFAULT_CHECKSUM_ALGORITHM
            ),
            adc_frames_emitted=adc_frames,
            gpio_frames_emitted=gpio_frames,
            adc_items_dropped=adc_stop_tail,
            gpio_items_dropped=gpio_stop_tail,
            stats_generation=self._stats_generation,
            commands_accepted=self.commands_accepted,
            gpio_samples_captured=gpio_items + gpio_stop_tail,
            gpio_samples_packed=gpio_items,
            gpio_samples_framed=gpio_items,
            gpio_samples_transmitted=gpio_items,
            gpio_dma_major_loops=gpio_frames,
            gpio_raw_samples_lost=gpio_stop_tail,
            gpio_raw_ready_high_water=1 if gpio_frames else 0,
            gpio_packed_ready_high_water=1 if gpio_frames else 0,
            gpio_processing_cpu_basis_points=500 if gpio_frames else 0,
            adc0_dma_major_loops=adc_frames,
            adc1_dma_major_loops=adc_frames,
            adc0_dma_results=adc_items,
            adc1_dma_results=adc_items,
            adc_paired_major_loops=adc_frames,
            adc_buffers_completed=adc_frames,
            adc_buffers_acquired=adc_frames,
            adc_buffers_released=adc_frames,
            adc_pairs_captured=adc_items + adc_stop_tail,
            adc_pairs_delivered=adc_items,
            adc_pairs_framed=adc_items,
            adc_pairs_transmitted=adc_items,
            adc_raw_pairs_lost=adc_stop_tail,
            adc_stop_pairs_discarded=adc_stop_tail,
            adc_incomplete_buffers=1 if stopped else 0,
            adc_raw_ready_high_water=1 if adc_frames else 0,
            adc_frames_generated=adc_frames,
            adc_items_generated=adc_items,
            adc_frames_framed_pipeline=adc_frames,
            adc_items_framed_pipeline=adc_items,
            adc_items_emitted=adc_items,
            adc_frames_transmitted=adc_frames,
            adc_items_transmitted_pipeline=adc_items,
            gpio_frames_generated=gpio_frames,
            gpio_items_generated=gpio_items,
            gpio_frames_framed_pipeline=gpio_frames,
            gpio_items_framed_pipeline=gpio_items,
            gpio_items_emitted=gpio_items,
            gpio_frames_transmitted=gpio_frames,
            gpio_items_transmitted_pipeline=gpio_items,
            adc_payload_bytes_produced=adc_payload,
            adc_payload_bytes_framed=adc_payload,
            adc_payload_bytes_emitted=adc_payload,
            adc_payload_bytes_transmitted=adc_payload,
            adc_framed_bytes_framed=adc_framed,
            adc_framed_bytes_emitted=adc_framed,
            adc_framed_bytes_transmitted=adc_framed,
            gpio_payload_bytes_produced=gpio_payload,
            gpio_payload_bytes_framed=gpio_payload,
            gpio_payload_bytes_emitted=gpio_payload,
            gpio_payload_bytes_transmitted=gpio_payload,
            gpio_framed_bytes_framed=gpio_framed,
            gpio_framed_bytes_emitted=gpio_framed,
            gpio_framed_bytes_transmitted=gpio_framed,
            adc_packet_ready_high_water=1 if adc_frames else 0,
            gpio_packet_ready_high_water=1 if gpio_frames else 0,
            adc_packet_transmit_high_water=1 if adc_frames else 0,
            gpio_packet_transmit_high_water=1 if gpio_frames else 0,
            packet_ready_high_water=2 if any_frames else 0,
            packet_transmit_high_water=2 if any_frames else 0,
            packet_owned_high_water=2 if any_frames else 0,
            packet_frames_promoted=adc_frames + gpio_frames,
            packet_accounted_frame_skew=abs(adc_frames - gpio_frames),
            data_payload_bytes_transmitted=adc_payload + gpio_payload,
            data_framed_bytes_transmitted=adc_framed + gpio_framed,
            **_ready_metadata(),
        )

    def _next_adc_frame(self, configuration: Configuration) -> bytes:
        flags = constants.FrameFlag.NONE
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
        self._adc_first_ticks += constants.FRAME_COVERAGE_TICKS
        self._adc_item_index += constants.ADC_PAIRS_PER_FRAME
        self._adc_frames_emitted += 1
        return wire

    def _next_gpio_frame(self, configuration: Configuration) -> bytes:
        flags = constants.FrameFlag.NONE
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
        self._gpio_first_ticks += constants.FRAME_COVERAGE_TICKS
        self._gpio_item_index += constants.GPIO_SAMPLES_PER_FRAME
        self._gpio_frames_emitted += 1
        return wire


class PacedCombinedSerial:
    """PySerial-shaped combined peer with reset noise and partial I/O."""

    def __init__(self) -> None:
        self.device = PhysicalCombinedDevice()
        self.timeout = 0.001
        self.write_timeout = 0.1
        self.is_open = True
        self.pending = bytearray(b"late reset text\r\n\xef\xbe")
        self.read_pattern = (1, 509, 2048, 8192, 37, 65_536)
        self.write_pattern = (1, 0, 5, 17, 128)
        self.read_index = 0
        self.write_index = 0
        self.read_counts: list[int] = []
        self.write_counts: list[int] = []
        self.frame_interval = (
            constants.FRAME_COVERAGE_TICKS / constants.TIMESTAMP_HZ / 2
        )
        self.next_frame_at = time.monotonic()

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
        for response in self.device.receive(wire[:count]):
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


class CombinedRigTests(unittest.TestCase):
    def test_program_is_one_file_standard_library_plus_pyserial(self) -> None:
        source = RIG_SCRIPT.read_text(encoding="utf-8")
        tree = ast.parse(source)
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
                "json",
                "math",
                "os",
                "re",
                "resource",
                "serial",
                "struct",
                "sys",
                "time",
                "typing",
                "zlib",
            },
            imports,
        )
        self.assertNotIn("from teensy_daq", source)
        self.assertNotIn("protocol-v1.json", source)
        self.assertIn('os.environ.get("SERIAL_PORT")', source)
        self.assertIn("COMBINED_CAPTURE_SECONDS", source)
        self.assertIn("ADC_FIXTURE_STIMULUS_JSON", source)

    def test_codec_matches_golden_control_and_both_data_frames(self) -> None:
        request_kind_by_name = {
            "info-request.bin": rig.INFO_REQUEST,
            "configure-request.bin": rig.CONFIGURE_REQUEST,
            "start-request.bin": rig.START_REQUEST,
            "get-status-request.bin": rig.GET_STATUS_REQUEST,
            "stop-request.bin": rig.STOP_REQUEST,
            "reset-stats-request.bin": rig.RESET_STATS_REQUEST,
            "gpio-capture-diagnostic-request.bin": (
                rig.GPIO_CAPTURE_DIAGNOSTIC_REQUEST
            ),
        }
        for name, kind in request_kind_by_name.items():
            expected = (FIXTURES / name).read_bytes()
            request_id = int.from_bytes(expected[28:32], "little")
            payload = expected[rig.HEADER_SIZE : -rig.TRAILER_SIZE]
            with self.subTest(request=name):
                self.assertEqual(
                    expected, rig.encode_request(kind, request_id, payload)
                )

        names = (
            "info-response.bin",
            "get-status-response.bin",
            "gpio-capture-diagnostic-response.bin",
            "adc-data.bin",
            "gpio-data.bin",
        )
        wire = b"reset noise\xef\xbe" + b"".join(
            (FIXTURES / name).read_bytes() for name in names
        )
        parser = rig.FrameParser()
        decoded = []
        for offset in range(0, len(wire), 509):
            decoded.extend(parser.feed(wire[offset : offset + 509]))
        self.assertEqual(len(names), len(decoded))
        self.assertEqual(0, parser.errors)
        bulk_parser = rig.FrameParser()
        bulk_wire = (
            (FIXTURES / "adc-data.bin").read_bytes()
            + (FIXTURES / "gpio-data.bin").read_bytes()
        ) * 2
        self.assertEqual(4, len(bulk_parser.feed(bulk_wire)))
        self.assertEqual(0, bulk_parser.errors)
        self.assertFalse(bulk_parser.buffer)
        status = rig.decode_status(decoded[1])
        self.assertEqual(143, len(status.values))
        previous = rig.StatusSnapshot(
            values={
                **status.values,
                "commands_accepted": 10,
                "gpio_processing_cpu_basis_points": 8_000,
            },
            adc_metadata=status.adc_metadata,
            adc_resolution_bits=status.adc_resolution_bits,
            adc_container_bytes=status.adc_container_bytes,
        )
        current = rig.StatusSnapshot(
            values={
                **status.values,
                "commands_accepted": 9,
                "gpio_processing_cpu_basis_points": 100,
            },
            adc_metadata=status.adc_metadata,
            adc_resolution_bits=status.adc_resolution_bits,
            adc_container_bytes=status.adc_container_bytes,
        )
        self.assertEqual(
            {"commands_accepted": (10, 9)},
            current.regressions_from(previous),
        )
        status.values["gpio_raw_samples_lost"] = 4_048
        with self.assertRaisesRegex(
            rig.ProtocolFailure,
            r'"gpio_raw_samples_lost":4048',
        ):
            rig.validate_status_accounting(status)

        for fixture_name in ("adc-data.bin", "gpio-data.bin"):
            corrupted = bytearray((FIXTURES / fixture_name).read_bytes())
            corrupted[-1] ^= 0x80
            bad_parser = rig.FrameParser()
            self.assertEqual([], bad_parser.feed(corrupted))
            self.assertEqual(1, bad_parser.checksum_errors)

    def test_fixture_parser_and_combined_validator_enforce_scope_and_layout(
        self,
    ) -> None:
        declaration = {
            "schema": "teensy-daq-adc-stimulus-v1",
            "fixture_id": "divider-v1",
            "stimulus_id": "two-levels",
            "channels": {
                "adc0": {
                    "pin": "A0",
                    "minimum_code": 100,
                    "maximum_code": 200,
                    "mean_minimum_code": 149.0,
                    "mean_maximum_code": 151.0,
                },
                "adc1": {
                    "pin": "A1",
                    "minimum_code": 300,
                    "maximum_code": 400,
                    "mean_minimum_code": 349.0,
                    "mean_maximum_code": 351.0,
                },
            },
        }
        fixture = rig.load_fixture_stimulus(json.dumps(declaration))
        self.assertIsNotNone(fixture)
        assert fixture is not None
        validator = rig.CombinedValidator(7, rig.CHECKSUM_ADLER32, 12, fixture)
        adc_payload = struct.pack("<HH", 150, 350) * rig.ADC_PAIRS_PER_FRAME
        validator.accept(
            rig.Frame(
                rig.ADC_DATA,
                rig.FLAG_EPOCH_START,
                rig.CHECKSUM_ADLER32,
                7,
                0,
                0,
                0,
                rig.ADC_PAIRS_PER_FRAME,
                adc_payload,
                0,
            )
        )
        validator.accept(
            rig.Frame(
                rig.GPIO_DATA,
                rig.FLAG_EPOCH_START,
                rig.CHECKSUM_ADLER32,
                7,
                0,
                0,
                0,
                rig.GPIO_SAMPLES_PER_FRAME,
                bytes(range(256)) * 15 + bytes(range(208)),
                0,
            )
        )
        self.assertEqual(1, validator.adc.frames)
        self.assertEqual(1, validator.gpio.frames)
        self.assertEqual((150.0, 350.0), validator.means())
        self.assertEqual(0, validator.gpio_payload_and)
        self.assertEqual(0xFF, validator.gpio_payload_or)
        self.assertEqual(rig.GPIO_SAMPLES_PER_FRAME - 1, validator.gpio_transitions)
        with redirect_stdout(io.StringIO()):
            self.assertTrue(validator.grade_analog_fixture(rig.Evidence()))

        bad = rig.CombinedValidator(7, rig.CHECKSUM_ADLER32, 12, None)
        bad.accept(
            rig.Frame(
                rig.ADC_DATA,
                rig.FLAG_EPOCH_START,
                rig.CHECKSUM_ADLER32,
                7,
                0,
                0,
                0,
                rig.ADC_PAIRS_PER_FRAME,
                struct.pack("<HH", 1, 2) * rig.ADC_PAIRS_PER_FRAME,
                0,
            )
        )
        bad.accept(
            rig.Frame(
                rig.GPIO_DATA,
                rig.FLAG_EPOCH_START,
                rig.CHECKSUM_ADLER32,
                7,
                0,
                0,
                0,
                rig.GPIO_SAMPLES_PER_FRAME,
                bytes(rig.GPIO_SAMPLES_PER_FRAME),
                0,
            )
        )
        with self.assertRaisesRegex(rig.ProtocolFailure, "outside"):
            bad.accept(
                rig.Frame(
                    rig.ADC_DATA,
                    0,
                    rig.CHECKSUM_ADLER32,
                    7,
                    1,
                    0,
                    rig.FRAME_COVERAGE_TICKS,
                    rig.ADC_PAIRS_PER_FRAME,
                    struct.pack("<HH", 4096, 1) * rig.ADC_PAIRS_PER_FRAME,
                    0,
                )
            )

        wrong_pin = json.dumps(declaration).replace('"pin": "A1"', '"pin": "A2"')
        with self.assertRaisesRegex(ValueError, "must declare pin A1"):
            rig.load_fixture_stimulus(wrong_pin)

    def test_bulk_gpio_transition_counter_matches_scalar_reference(self) -> None:
        patterns = (
            bytes(rig.GPIO_SAMPLES_PER_FRAME),
            b"\x00\xff" * (rig.GPIO_SAMPLES_PER_FRAME // 2),
            bytes(range(256)) * 15 + bytes(range(208)),
            bytes((index * 73 + index // 11) & 0xFF for index in range(4048)),
        )
        for payload in patterns:
            expected = sum(left != right for left, right in pairwise(payload))
            with self.subTest(expected=expected):
                self.assertEqual(
                    expected,
                    rig.count_adjacent_byte_transitions(payload),
                )

    def test_full_program_configures_combined_streams_and_reconciles_all_counters(
        self,
    ) -> None:
        fake = PacedCombinedSerial()
        output = io.StringIO()
        environment = {
            "SERIAL_PORT": "fake-combined-port",
            "COMBINED_CAPTURE_SECONDS": "0.14",
            "COMBINED_WARMUP_SECONDS": "0.02",
            "COMBINED_STATUS_INTERVAL_SECONDS": "0.02",
            "EXPECTED_BUILD_ID": "tdaq-0123456789abcdef",
            "EXPECTED_HARDWARE_SERIAL": "12345670",
        }
        with (
            patch.object(rig, "STARTUP_DRAIN_SECONDS", 0.002),
            patch.object(rig, "SYNC_DEADLINE_SECONDS", 0.1),
            patch.object(rig, "COMMAND_DEADLINE_SECONDS", 0.1),
            patch.object(rig, "DIAGNOSTIC_DEADLINE_SECONDS", 0.1),
            patch.object(rig, "STOP_DRAIN_DEADLINE_SECONDS", 0.2),
            patch.object(rig, "STOP_DRAIN_QUIET_SECONDS", 0.002),
            patch.object(rig, "RATE_TOLERANCE_FRACTION", 0.25),
            patch.object(rig.serial, "Serial", return_value=fake),
            patch.dict(os.environ, environment, clear=True),
            redirect_stdout(output),
        ):
            exit_code = rig.main()

        report = output.getvalue()
        self.assertEqual(0, exit_code, report)
        self.assertIn('"name":"identity.supported_configuration_mask"', report)
        self.assertIn('"event":"digital_diagnostic_complete"', report)
        self.assertIn("ANALOG_STIMULUS:", report)
        self.assertIn("DIGITAL_STIMULUS:", report)
        self.assertIn('"name":"epoch.four_gpio_events_per_adc_pair"', report)
        self.assertIn('"name":"final.all_status_fields_classified"', report)
        self.assertIn('"name":"final.host_firmware_command_reconciliation"', report)
        self.assertIn('"event":"final_firmware_counters"', report)
        self.assertIn('"result":"PASS"', report)
        self.assertFalse(fake.is_open)
        self.assertIn(0, fake.write_counts)
        self.assertEqual(constants.DeviceState.IDLE, fake.device.state)


if __name__ == "__main__":
    unittest.main()
