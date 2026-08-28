"""Offline verification for the independent Phase 06 physical-GPIO rig."""

from __future__ import annotations

import ast
import importlib.util
import io
import os
import struct
import sys
import time
import unittest
from contextlib import redirect_stdout
from pathlib import Path
from types import ModuleType
from unittest.mock import patch

from teensy_daq._generated import protocol_constants as constants
from teensy_daq.models import Configuration, DeviceInfo, Status
from teensy_daq.protocol import encode_frame
from teensy_daq.simulator import SimulatedDevice
from teensy_daq.synthetic import synthetic_gpio_payload

ROOT = Path(__file__).resolve().parents[2]
RIG_SCRIPT = ROOT / "firmware" / "tests" / "rig_gpio_capture.py"
FIXTURES = ROOT / "protocol" / "fixtures"
SUCCESS_PREFIX = struct.pack("<BBH", 0, 0, 0)


def _load_rig_script() -> ModuleType:
    specification = importlib.util.spec_from_file_location(
        "independent_rig_gpio_capture",
        RIG_SCRIPT,
    )
    if specification is None or specification.loader is None:
        raise RuntimeError("could not load rig_gpio_capture.py")
    module = importlib.util.module_from_spec(specification)
    sys.modules[specification.name] = module
    specification.loader.exec_module(module)
    return module


rig = _load_rig_script()


def _clock_payload(rate_hz: int, event_count: int) -> bytes:
    payload = bytearray(constants.GPIO_CLOCK_DIAGNOSTIC_RESPONSE_PAYLOAD_SIZE)
    payload[:4] = SUCCESS_PREFIX
    major_count = 2 * event_count + rig.GPIO_CLOCK_DUPLICATE_GUARD_EVENTS
    elapsed_cycles = event_count * (rig.GPIO_CLOCK_DWT_HZ // rate_hz)
    u32_values = {
        4: rate_hz,
        8: rig.GPIO_SAMPLE_RATE_HZ,
        12: rig.GPIO_CLOCK_PIT_HZ,
        16: rig.GPIO_CLOCK_PIT_HZ // rate_hz - 1,
        20: event_count,
        24: event_count,
        28: event_count,
        32: rig.GPIO_CLOCK_DWT_HZ,
        36: elapsed_cycles,
        40: 0,
        44: rig.CCM_PERCLK_24MHZ,
        48: rig.CCM_PIT_GATE_MASK,
        52: rig.CCM_XBAR_GATE_MASK,
        56: rig.CCM_DMA_GATE_MASK,
        60: 0,
        64: rig.GPIO_CLOCK_PIT_HZ // rate_hz - 1,
        68: max(0, rig.GPIO_CLOCK_PIT_HZ // rate_hz - 2),
        72: 1,
        76: 1,
        84: rig.DMAMUX_ENABLE | rig.GPIO_DMAMUX_SOURCE,
        88: 2,
        92: 0,
        96: rig.EDMA_CHANNEL_MASK,
        100: 0,
        104: 0,
        108: 0x2025F000,
        112: 0x2025F004,
        116: 4,
        120: rig.DIAGNOSTIC_SOURCE_WORD,
    }
    for offset, value in u32_values.items():
        struct.pack_into("<I", payload, offset, value)
    u16_values = {
        80: rig.GPIO_XBAR_INPUT,
        82: 5,
        124: major_count - event_count,
        126: major_count,
        128: rig.TCD_DREQ,
        130: rig.TCD_32BIT_ATTRIBUTES,
        138: 0,
    }
    for offset, value in u16_values.items():
        struct.pack_into("<H", payload, offset, value)
    payload[132:138] = bytes(
        (
            rig.GPIO_PIT_CHANNEL,
            rig.GPIO_XBAR_INPUT,
            rig.GPIO_XBAR_OUTPUT,
            rig.GPIO_EDMA_CHANNEL,
            rig.GPIO_DMAMUX_SOURCE,
            rig.GPIO_EDMA_PRIORITY,
        )
    )
    return bytes(payload)


def _capture_payload() -> bytes:
    wire = (FIXTURES / "gpio-capture-diagnostic-response.bin").read_bytes()
    return wire[constants.HEADER_SIZE : -constants.TRAILER_SIZE]


class PhysicalGpioDevice(SimulatedDevice):
    """Protocol peer with physical GPIO flags and exact Phase 06 metadata."""

    def __init__(self) -> None:
        super().__init__(build_id="tdaq-0123456789abcdef")

    def _handle_info(self, request):  # type: ignore[no-untyped-def]
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
            data_checksum_algorithm=self.status().data_checksum_algorithm,
            capability_bits=constants.Capability(constants.KNOWN_CAPABILITY_MASK),
            gpio_capture_diagnostic_mode=(
                constants.GpioCaptureDiagnosticMode.NON_DRIVING_CAPTURE
            ),
            gpio_capture_diagnostic_flags=(
                constants.GpioCaptureDiagnosticFlag.AVAILABLE
                | constants.GpioCaptureDiagnosticFlag.DECLARATION_VALID
            ),
        )
        return self._success_response(request, info.to_payload())

    def _handle_configure(self, request):  # type: ignore[no-untyped-def]
        configuration = Configuration.from_payload(request.payload)
        if not (
            self._state
            in {constants.DeviceState.IDLE, constants.DeviceState.CONFIGURED}
            and configuration.stream_mask == constants.StreamMask.GPIO
            and configuration.source == constants.Source.HARDWARE
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

    def _handle_gpio_clock_diagnostic(self, request):  # type: ignore[no-untyped-def]
        rate_hz, event_count, reserved = struct.unpack("<IHH", request.payload)
        if reserved:
            return self._typed_error(request, constants.ErrorCode.INVALID_PAYLOAD)
        return self._success_response(request, _clock_payload(rate_hz, event_count))

    def _handle_gpio_capture_diagnostic(self, request):  # type: ignore[no-untyped-def]
        return self._success_response(request, _capture_payload())

    def status(self) -> Status:
        configuration = self._configuration
        samples = self._gpio_frames_emitted * constants.GPIO_SAMPLES_PER_FRAME
        return Status(
            device_state=self._state,
            stream_mask=(
                configuration.stream_mask
                if configuration is not None
                else constants.StreamMask.NONE
            ),
            source=(
                configuration.source
                if configuration is not None
                else constants.Source.HARDWARE
            ),
            data_checksum_algorithm=(
                configuration.data_checksum_algorithm
                if configuration is not None
                else constants.DEFAULT_CHECKSUM_ALGORITHM
            ),
            adc_frames_emitted=0,
            gpio_frames_emitted=self._gpio_frames_emitted,
            stats_generation=self._stats_generation,
            gpio_samples_captured=samples,
            gpio_samples_packed=samples,
            gpio_samples_framed=samples,
            gpio_samples_transmitted=samples,
            gpio_dma_major_loops=self._gpio_frames_emitted,
            gpio_raw_ready_high_water=1 if samples else 0,
            gpio_packed_ready_high_water=1 if samples else 0,
            packet_owned_high_water=1 if samples else 0,
            gpio_processing_cpu_basis_points=500 if samples else 0,
        )

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
        self._gpio_first_ticks = (
            self._gpio_first_ticks + constants.FRAME_COVERAGE_TICKS
        ) & constants.UINT64_MAX
        self._gpio_item_index += constants.GPIO_SAMPLES_PER_FRAME
        self._gpio_frames_emitted += 1
        return wire


class PacedRigSerial:
    """PySerial-shaped physical peer with reset noise and partial I/O."""

    def __init__(self) -> None:
        self.device = PhysicalGpioDevice()
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
        self.frame_interval = rig.FRAME_COVERAGE_TICKS / rig.TIMESTAMP_HZ
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
                "itertools",
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
        self.assertNotIn("teensy_daq", source)
        self.assertNotIn("protocol-v1.json", source)
        self.assertIn('os.environ.get("SERIAL_PORT")', source)
        self.assertIn('"GPIO_CAPTURE_SECONDS"', source)
        self.assertIn("ELECTRICAL_STIMULUS", source)

    def test_independent_codec_matches_relevant_golden_frames(self) -> None:
        request_kind_by_name = {
            "info-request.bin": rig.INFO_REQUEST,
            "configure-request.bin": rig.CONFIGURE_REQUEST,
            "start-request.bin": rig.START_REQUEST,
            "get-status-request.bin": rig.GET_STATUS_REQUEST,
            "stop-request.bin": rig.STOP_REQUEST,
            "reset-stats-request.bin": rig.RESET_STATS_REQUEST,
            "gpio-clock-diagnostic-request.bin": rig.GPIO_CLOCK_DIAGNOSTIC_REQUEST,
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
            "configure-response.bin",
            "start-response.bin",
            "get-status-response.bin",
            "stop-response.bin",
            "reset-stats-response.bin",
            "gpio-clock-diagnostic-response.bin",
            "gpio-capture-diagnostic-response.bin",
            "gpio-data.bin",
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

    def test_diagnostic_graders_accept_exact_evidence_and_reject_false_claims(
        self,
    ) -> None:
        info = {
            "gpio_pit_channel": rig.GPIO_PIT_CHANNEL,
            "gpio_xbar_input": rig.GPIO_XBAR_INPUT,
            "gpio_xbar_output": rig.GPIO_XBAR_OUTPUT,
            "gpio_edma_channel": rig.GPIO_EDMA_CHANNEL,
            "gpio_dmamux_source": rig.GPIO_DMAMUX_SOURCE,
            "gpio_edma_priority": rig.GPIO_EDMA_PRIORITY,
            "gpio_capture_diagnostic_mode": rig.GPIO_DIAGNOSTIC_NON_DRIVING,
            "gpio_capture_diagnostic_flags": (
                rig.GPIO_DIAGNOSTIC_AVAILABLE | rig.GPIO_DIAGNOSTIC_DECLARATION_VALID
            ),
        }
        clock_wire = encode_frame(
            constants.FrameKind.GPIO_CLOCK_DIAGNOSTIC_RESPONSE,
            _clock_payload(1_000, 64),
            request_id=1,
        )
        clock = rig.decode_clock_diagnostic(rig.FrameParser().feed(clock_wire)[0])
        with redirect_stdout(io.StringIO()):
            rig.grade_clock_diagnostic(
                rig.Evidence(),
                clock,
                label="low_rate",
                rate_hz=1_000,
                event_count=64,
                info=info,
            )
        bad_clock = dict(clock)
        bad_clock["dma_sample_count"] += 2
        with (
            redirect_stdout(io.StringIO()),
            self.assertRaisesRegex(rig.ProtocolFailure, "clock diagnostic"),
        ):
            rig.grade_clock_diagnostic(
                rig.Evidence(),
                bad_clock,
                label="low_rate",
                rate_hz=1_000,
                event_count=64,
                info=info,
            )

        capture_wire = encode_frame(
            constants.FrameKind.GPIO_CAPTURE_DIAGNOSTIC_RESPONSE,
            _capture_payload(),
            request_id=2,
        )
        capture = rig.decode_capture_diagnostic(rig.FrameParser().feed(capture_wire)[0])
        with redirect_stdout(io.StringIO()):
            exercised, mode = rig.grade_capture_diagnostic(
                rig.Evidence(), capture, info
            )
        self.assertFalse(exercised)
        self.assertEqual("NON_DRIVING_CAPTURE", mode)

        bad_capture = dict(capture)
        bad_capture["diagnostic_flags"] |= rig.GPIO_DIAGNOSTIC_OUTPUT_DRIVE_EXERCISED
        with (
            redirect_stdout(io.StringIO()),
            self.assertRaisesRegex(rig.ProtocolFailure, "mapping diagnostic"),
        ):
            rig.grade_capture_diagnostic(rig.Evidence(), bad_capture, info)

    def test_physical_validator_rejects_synthetic_gap_sequence_and_timestamp(
        self,
    ) -> None:
        synthetic = rig.FrameParser().feed((FIXTURES / "gpio-data.bin").read_bytes())[0]
        physical = rig.Frame(
            kind=rig.GPIO_DATA,
            flags=rig.FLAG_EPOCH_START,
            checksum_algorithm=synthetic.checksum_algorithm,
            run_id=synthetic.run_id,
            sequence=0,
            request_id=0,
            first_sample_ticks=0,
            item_count=rig.GPIO_SAMPLES_PER_FRAME,
            payload=synthetic.payload,
            checksum=synthetic.checksum,
        )
        validator = rig.PhysicalGpioValidator(
            physical.run_id,
            physical.checksum_algorithm,
        )
        validator.accept(physical)
        self.assertEqual(1, validator.gpio.frames)

        mutations = (
            ("SYNTHETIC", {"flags": rig.FLAG_SYNTHETIC}),
            ("gap/overrun", {"flags": rig.FLAG_GAP_BEFORE}),
            ("sequence", {"sequence": 7}),
            ("timestamp", {"first_sample_ticks": rig.FRAME_COVERAGE_TICKS + 2}),
        )
        for message, changes in mutations:
            candidate_validator = rig.PhysicalGpioValidator(
                physical.run_id,
                physical.checksum_algorithm,
            )
            candidate_validator.accept(physical)
            fields = {
                "kind": rig.GPIO_DATA,
                "flags": 0,
                "checksum_algorithm": physical.checksum_algorithm,
                "run_id": physical.run_id,
                "sequence": 1,
                "request_id": 0,
                "first_sample_ticks": rig.FRAME_COVERAGE_TICKS,
                "item_count": rig.GPIO_SAMPLES_PER_FRAME,
                "payload": physical.payload,
                "checksum": physical.checksum,
            }
            fields.update(changes)
            with (
                self.subTest(message=message),
                self.assertRaisesRegex(rig.ProtocolFailure, message),
            ):
                candidate_validator.accept(rig.Frame(**fields))

    def test_full_program_runs_diagnostics_streams_status_and_stops(self) -> None:
        fake = PacedRigSerial()
        output = io.StringIO()
        environment = {
            "SERIAL_PORT": "fake-rig-port",
            "GPIO_CAPTURE_SECONDS": "0.12",
            "GPIO_STATUS_INTERVAL_SECONDS": "0.02",
            "GPIO_LOW_RATE_HZ": "1000",
            "GPIO_LOW_RATE_EVENT_COUNT": "64",
            "GPIO_PRODUCTION_EVENT_COUNT": "8192",
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
            patch.object(rig, "RATE_TOLERANCE_FRACTION", 0.20),
            patch.object(rig.serial, "Serial", return_value=fake),
            patch.dict(os.environ, environment, clear=False),
            redirect_stdout(output),
        ):
            exit_code = rig.main()

        report = output.getvalue()
        self.assertEqual(0, exit_code, report)
        self.assertIn('"name":"identity.build_id","pass":true', report)
        self.assertIn('"event":"clock_diagnostic_complete"', report)
        self.assertIn('"event":"mapping_diagnostic_complete"', report)
        self.assertIn("external electrical stimulus was not exercised", report)
        self.assertIn('"event":"capture_complete"', report)
        self.assertIn('"result":"PASS"', report)
        self.assertFalse(fake.is_open)
        self.assertIn(0, fake.write_counts)
        self.assertLessEqual(max(fake.read_counts), max(fake.read_pattern))
        self.assertEqual(constants.DeviceState.IDLE, fake.device.state)


if __name__ == "__main__":
    unittest.main()
