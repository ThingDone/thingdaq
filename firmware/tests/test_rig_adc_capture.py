"""Offline verification for the independent Phase 07 physical-ADC rig."""

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
from pathlib import Path
from types import ModuleType
from typing import TypedDict
from unittest.mock import patch

from thingdaq._generated import protocol_constants as constants
from thingdaq.models import AdcTriggerMetadata, Configuration, DeviceInfo, Status
from thingdaq.protocol import encode_frame
from thingdaq.simulator import SimulatedDevice
from thingdaq.synthetic import synthetic_adc_payload

ROOT = Path(__file__).resolve().parents[2]
RIG_SCRIPT = ROOT / "firmware" / "tests" / "rig_adc_capture.py"
FIXTURES = ROOT / "protocol" / "fixtures"
SUCCESS_PREFIX = struct.pack("<BBH", 0, 0, 0)

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


def _load_rig_script() -> ModuleType:
    specification = importlib.util.spec_from_file_location(
        "independent_rig_adc_capture",
        RIG_SCRIPT,
    )
    if specification is None or specification.loader is None:
        raise RuntimeError("could not load rig_adc_capture.py")
    module = importlib.util.module_from_spec(specification)
    sys.modules[specification.name] = module
    specification.loader.exec_module(module)
    return module


rig = _load_rig_script()


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
        chain_configured=(
            rig.ADC0_CHAIN_CONFIGURED,
            rig.ADC1_CHAIN_CONFIGURED,
        ),
        completion_counts=(
            rig.ADC_TRIGGER_DIAGNOSTIC_COMPLETION_TARGET,
            rig.ADC_TRIGGER_DIAGNOSTIC_COMPLETION_TARGET,
        ),
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


def _device_info(
    state: constants.DeviceState,
    configuration: Configuration | None = None,
) -> DeviceInfo:
    return DeviceInfo(
        device_state=state,
        build_id="thingdaq-0123456789abcdef",
        hardware_serial=12_345_670,
        firmware_version=(0, 7, 0),
        board_id=constants.BoardId.TEENSY_40,
        mcu_id=constants.McuId.IMXRT1062,
        supported_stream_mask=constants.StreamMask.ADC | constants.StreamMask.GPIO,
        supported_source_mask=0x03,
        applied_stream_mask=(
            configuration.stream_mask
            if configuration is not None
            else constants.StreamMask.NONE
        ),
        applied_source=(
            configuration.source
            if configuration is not None
            else constants.Source.HARDWARE
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


class PhysicalAdcDevice(SimulatedDevice):
    """Protocol peer with physical ADC flags and exact Phase 07 metadata."""

    def __init__(self) -> None:
        super().__init__(build_id="thingdaq-0123456789abcdef")

    def _handle_info(self, request):  # type: ignore[no-untyped-def]
        info = _device_info(self.state, self.configuration)
        return self._success_response(request, info.to_payload())

    def _handle_configure(self, request):  # type: ignore[no-untyped-def]
        configuration = Configuration.from_payload(request.payload)
        if not (
            self._state
            in {constants.DeviceState.IDLE, constants.DeviceState.CONFIGURED}
            and configuration.stream_mask == constants.StreamMask.ADC
            and configuration.source == constants.Source.HARDWARE
            and configuration.data_checksum_algorithm
            in constants.SUPPORTED_CHECKSUM_ALGORITHMS
        ):
            return self._typed_error(
                request,
                constants.ErrorCode.UNSUPPORTED_CONFIGURATION,
            )
        self._configuration = configuration
        self._state = constants.DeviceState.CONFIGURED
        return self._success_response(
            request,
            SUCCESS_PREFIX + configuration.to_payload(),
        )

    def status(self) -> Status:
        configuration = self._configuration
        frames = self._adc_frames_emitted
        pairs = frames * constants.ADC_PAIRS_PER_FRAME
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
            adc_frames_emitted=frames,
            stats_generation=self._stats_generation,
            packet_owned_high_water=1 if frames else 0,
            adc0_dma_major_loops=frames,
            adc1_dma_major_loops=frames,
            adc0_dma_results=pairs,
            adc1_dma_results=pairs,
            adc_paired_major_loops=frames,
            adc_buffers_completed=frames,
            adc_buffers_acquired=frames,
            adc_buffers_released=frames,
            adc_pairs_captured=pairs,
            adc_pairs_delivered=pairs,
            adc_pairs_framed=pairs,
            adc_pairs_transmitted=pairs,
            adc_raw_ready_high_water=1 if frames else 0,
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
        self._adc_first_ticks = (
            self._adc_first_ticks + constants.FRAME_COVERAGE_TICKS
        ) & constants.UINT64_MAX
        self._adc_item_index += constants.ADC_PAIRS_PER_FRAME
        self._adc_frames_emitted = (self._adc_frames_emitted + 1) & constants.UINT64_MAX
        return wire


class PacedRigSerial:
    """PySerial-shaped physical peer with reset noise and partial I/O."""

    def __init__(self) -> None:
        self.device = PhysicalAdcDevice()
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
        self.frame_interval = constants.ADC_PAIRS_PER_FRAME / constants.ADC_PAIR_RATE_HZ
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


class RigScriptIndependenceTests(unittest.TestCase):
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
        self.assertNotIn("import thingdaq", source)
        self.assertNotIn("from thingdaq", source)
        self.assertNotIn("protocol-v1.json", source)
        self.assertIn('os.environ.get("SERIAL_PORT")', source)
        self.assertIn('"ADC_CAPTURE_SECONDS"', source)
        self.assertIn("ADC_FIXTURE_STIMULUS_JSON", source)

    def test_independent_codec_matches_relevant_golden_frames(self) -> None:
        request_kind_by_name = {
            "info-request.bin": rig.INFO_REQUEST,
            "configure-request.bin": rig.CONFIGURE_REQUEST,
            "start-request.bin": rig.START_REQUEST,
            "get-status-request.bin": rig.GET_STATUS_REQUEST,
            "stop-request.bin": rig.STOP_REQUEST,
            "reset-stats-request.bin": rig.RESET_STATS_REQUEST,
        }
        for name, kind in request_kind_by_name.items():
            expected = (FIXTURES / name).read_bytes()
            request_id = int.from_bytes(expected[28:32], "little")
            payload = expected[rig.HEADER_SIZE : -rig.TRAILER_SIZE]
            with self.subTest(request=name):
                self.assertEqual(
                    expected,
                    rig.encode_request(kind, request_id, payload),
                )

        names = (
            "info-response.bin",
            "configure-response.bin",
            "start-response.bin",
            "get-status-response.bin",
            "stop-response.bin",
            "reset-stats-response.bin",
            "adc-data.bin",
        )
        wire = b"reset noise\xef\xbe" + b"".join(
            (FIXTURES / name).read_bytes() for name in names
        )
        parser = rig.FrameParser()
        decoded = []
        offset = 0
        pattern = (1, 3, 509, 4095, 17, 8192)
        index = 0
        while offset < len(wire):
            count = pattern[index % len(pattern)]
            decoded.extend(parser.feed(wire[offset : offset + count]))
            offset += count
            index += 1
        self.assertEqual(len(names), len(decoded))
        self.assertEqual(0, parser.errors)
        self.assertGreaterEqual(parser.bytes_discarded, len(b"reset noise\xef\xbe"))

        corrupted = bytearray((FIXTURES / "adc-data.bin").read_bytes())
        corrupted[-1] ^= 0x80
        bad_parser = rig.FrameParser()
        self.assertEqual([], bad_parser.feed(corrupted))
        self.assertEqual(1, bad_parser.checksum_errors)

        for algorithm in constants.SUPPORTED_CHECKSUM_ALGORITHMS:
            algorithm_wire = encode_frame(
                constants.FrameKind.ADC_DATA,
                synthetic_adc_payload(0),
                flags=constants.FrameFlag.EPOCH_START,
                checksum_algorithm=algorithm,
                run_id=1,
                item_count=constants.ADC_PAIRS_PER_FRAME,
            )
            with self.subTest(checksum=algorithm.name):
                algorithm_frames = rig.FrameParser().feed(algorithm_wire)
                self.assertEqual(1, len(algorithm_frames))
                self.assertEqual(int(algorithm), algorithm_frames[0].checksum_algorithm)

    def test_fixture_parser_is_strict_and_declares_analog_scope(self) -> None:
        self.assertIsNone(rig.load_fixture_stimulus(None))
        declaration = {
            "schema": "thingdaq-adc-stimulus-v1",
            "fixture_id": "divider-v1",
            "stimulus_id": "midscale-dc",
            "channels": {
                "adc0": {
                    "pin": "A0",
                    "minimum_code": 100,
                    "maximum_code": 200,
                    "mean_minimum_code": 145.0,
                    "mean_maximum_code": 155.0,
                },
                "adc1": {
                    "pin": "A1",
                    "minimum_code": 300,
                    "maximum_code": 400,
                    "mean_minimum_code": 345.0,
                    "mean_maximum_code": 355.0,
                },
            },
        }
        fixture = rig.load_fixture_stimulus(json.dumps(declaration))
        self.assertIsNotNone(fixture)
        assert fixture is not None
        self.assertTrue(fixture.grades_analog_quality)
        self.assertEqual(("A0", "A1"), tuple(c.pin for c in fixture.channels))

        validator = rig.PhysicalAdcValidator(
            9,
            rig.CHECKSUM_ADLER32,
            12,
            fixture,
        )
        validator.accept(
            rig.Frame(
                kind=rig.ADC_DATA,
                flags=rig.FLAG_EPOCH_START,
                checksum_algorithm=rig.CHECKSUM_ADLER32,
                run_id=9,
                sequence=0,
                request_id=0,
                first_sample_ticks=0,
                item_count=rig.ADC_PAIRS_PER_FRAME,
                payload=(struct.pack("<HH", 150, 350) * rig.ADC_PAIRS_PER_FRAME),
                checksum=0,
            )
        )
        with redirect_stdout(io.StringIO()):
            self.assertTrue(validator.grade_fixture(rig.Evidence(), label="fixture"))

        invalid_pin = json.dumps(declaration).replace(
            '"pin": "A1"',
            '"pin": "A2"',
        )
        with self.assertRaisesRegex(ValueError, "must declare pin A1"):
            rig.load_fixture_stimulus(invalid_pin)

        fractional_code = json.dumps(declaration).replace(
            '"minimum_code": 100', '"minimum_code": 100.5'
        )
        with self.assertRaisesRegex(ValueError, "integer ADC code"):
            rig.load_fixture_stimulus(fractional_code)

        too_wide = rig.FixtureStimulus(
            "fixture",
            "stimulus",
            (
                rig.ChannelStimulus("A0", 0, 4095),
                rig.ChannelStimulus("A1", 0, 4095),
            ),
        )
        with self.assertRaisesRegex(rig.ProtocolFailure, "advertised ADC range"):
            rig.PhysicalAdcValidator(1, rig.CHECKSUM_ADLER32, 10, too_wide)

    def test_metadata_grader_accepts_exact_evidence_and_rejects_bad_delay(
        self,
    ) -> None:
        wire = encode_frame(
            constants.FrameKind.INFO_RESPONSE,
            _device_info(constants.DeviceState.IDLE).to_payload(),
            request_id=1,
        )
        frame = rig.FrameParser().feed(wire)[0]
        info = rig.decode_info(frame)
        with redirect_stdout(io.StringIO()):
            resolution = rig.grade_info(
                rig.Evidence(),
                info,
                expected_build_id="thingdaq-0123456789abcdef",
                expected_hardware_serial=12_345_670,
            )
        self.assertEqual(12, resolution)

        metadata = dict(info["adc_metadata"])
        metadata["trigger_effective_delays"] = (1, 75)
        with (
            redirect_stdout(io.StringIO()),
            self.assertRaisesRegex(rig.ProtocolFailure, "calibration/register/timing"),
        ):
            rig.grade_adc_metadata(
                rig.Evidence(),
                metadata,
                resolution_bits=12,
                label="mutated",
            )

    def test_physical_validator_checks_layout_range_sequence_and_timestamps(
        self,
    ) -> None:
        payload = struct.pack("<HH", 123, 456) * rig.ADC_PAIRS_PER_FRAME
        first = rig.Frame(
            kind=rig.ADC_DATA,
            flags=rig.FLAG_EPOCH_START,
            checksum_algorithm=rig.CHECKSUM_ADLER32,
            run_id=17,
            sequence=0,
            request_id=0,
            first_sample_ticks=0,
            item_count=rig.ADC_PAIRS_PER_FRAME,
            payload=payload,
            checksum=0,
        )
        validator = rig.PhysicalAdcValidator(17, rig.CHECKSUM_ADLER32, 12, None)
        validator.accept(first)
        self.assertEqual((123.0, 456.0), validator.means())
        self.assertEqual(
            [rig.ADC_PAIRS_PER_FRAME, rig.ADC_PAIRS_PER_FRAME],
            validator.channel_counts,
        )

        mutations = (
            ("SYNTHETIC", {"flags": rig.FLAG_SYNTHETIC}),
            ("gap/overrun", {"flags": rig.FLAG_GAP_BEFORE}),
            ("sequence", {"sequence": 7}),
            (
                "timestamp",
                {"first_sample_ticks": rig.ADC_FRAME_COVERAGE_TICKS + 8},
            ),
            ("item count", {"item_count": rig.ADC_PAIRS_PER_FRAME - 1}),
            ("four-byte pairs", {"payload": payload[:-2]}),
            (
                "outside",
                {
                    "payload": struct.pack("<HH", 4096, 456)
                    + payload[rig.ADC_BYTES_PER_PAIR :]
                },
            ),
        )
        for message, changes in mutations:
            candidate = rig.PhysicalAdcValidator(
                17,
                rig.CHECKSUM_ADLER32,
                12,
                None,
            )
            candidate.accept(first)
            fields = {
                "kind": rig.ADC_DATA,
                "flags": 0,
                "checksum_algorithm": rig.CHECKSUM_ADLER32,
                "run_id": 17,
                "sequence": 1,
                "request_id": 0,
                "first_sample_ticks": rig.ADC_FRAME_COVERAGE_TICKS,
                "item_count": rig.ADC_PAIRS_PER_FRAME,
                "payload": payload,
                "checksum": 0,
            }
            fields.update(changes)
            with (
                self.subTest(message=message),
                self.assertRaisesRegex(rig.ProtocolFailure, message),
            ):
                candidate.accept(rig.Frame(**fields))

    def test_full_program_runs_bounded_and_full_rate_epochs_then_stops(self) -> None:
        fake = PacedRigSerial()
        output = io.StringIO()
        environment = {
            "SERIAL_PORT": "fake-rig-port",
            "ADC_CAPTURE_SECONDS": "0.12",
            "ADC_STATUS_INTERVAL_SECONDS": "0.02",
            "ADC_REDUCED_CAPTURE_FRAMES": "2",
            "EXPECTED_BUILD_ID": "thingdaq-0123456789abcdef",
            "EXPECTED_HARDWARE_SERIAL": "12345670",
        }
        with (
            patch.object(rig, "STARTUP_DRAIN_SECONDS", 0.002),
            patch.object(rig, "SYNC_DEADLINE_SECONDS", 0.1),
            patch.object(rig, "COMMAND_DEADLINE_SECONDS", 0.1),
            patch.object(rig, "STOP_DRAIN_DEADLINE_SECONDS", 0.2),
            patch.object(rig, "STOP_DRAIN_QUIET_SECONDS", 0.002),
            patch.object(rig, "RATE_TOLERANCE_FRACTION", 0.20),
            patch.object(rig.serial, "Serial", return_value=fake),
            patch.dict(os.environ, environment, clear=True),
            redirect_stdout(output),
        ):
            exit_code = rig.main()

        report = output.getvalue()
        self.assertEqual(0, exit_code, report)
        self.assertIn('"name":"identity.build_id","pass":true', report)
        self.assertIn('"event":"adc_boot_diagnostic_complete"', report)
        self.assertIn('"event":"reduced_capture_complete"', report)
        self.assertIn("A0/A1 are unstimulated", report)
        self.assertIn("analog quality and analog aperture were not graded", report)
        self.assertIn('"event":"capture_complete"', report)
        self.assertIn('"name":"queue.adc_raw_ready_high_water","pass":true', report)
        self.assertIn('"name":"queue.packet_owned_high_water","pass":true', report)
        self.assertIn('"result":"PASS"', report)
        self.assertFalse(fake.is_open)
        self.assertIn(0, fake.write_counts)
        self.assertLessEqual(max(fake.read_counts), max(fake.read_pattern))
        self.assertEqual(constants.DeviceState.IDLE, fake.device.state)


if __name__ == "__main__":
    unittest.main()
