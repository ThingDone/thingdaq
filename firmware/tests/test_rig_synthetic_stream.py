"""Offline verification for the independent Phase 04 streaming rig program."""

from __future__ import annotations

import ast
import importlib.util
import io
import os
import sys
import time
import unittest
from contextlib import redirect_stdout
from pathlib import Path
from types import ModuleType
from unittest.mock import patch

from thingdone_daq import (
    BoardId,
    Capability,
    Info,
    McuId,
    SimulatedDevice,
    StreamMask,
)
from thingdone_daq._generated import protocol_constants as constants

ROOT = Path(__file__).resolve().parents[2]
RIG_SCRIPT = ROOT / "firmware" / "tests" / "rig_synthetic_stream.py"
FIXTURES = ROOT / "protocol" / "fixtures"


def _load_rig_script() -> ModuleType:
    specification = importlib.util.spec_from_file_location(
        "independent_rig_synthetic_stream",
        RIG_SCRIPT,
    )
    if specification is None or specification.loader is None:
        raise RuntimeError("could not load rig_synthetic_stream.py")
    module = importlib.util.module_from_spec(specification)
    sys.modules[specification.name] = module
    specification.loader.exec_module(module)
    return module


rig = _load_rig_script()


class HardwareSyntheticDevice(SimulatedDevice):
    """Streaming simulator with the current synthetic-capable INFO identity."""

    def __init__(self) -> None:
        super().__init__(build_id="thingdaq-0123456789abcdef")

    def _handle_info(self, request):  # type: ignore[no-untyped-def]
        configuration = self.configuration
        info = Info(
            device_state=self.state,
            build_id="thingdaq-0123456789abcdef",
            hardware_serial=12_345_670,
            firmware_version=(0, 7, 0),
            board_id=BoardId.TEENSY_40,
            mcu_id=McuId.IMXRT1062,
            supported_stream_mask=StreamMask.ADC | StreamMask.GPIO,
            supported_source_mask=(
                (1 << int(constants.Source.HARDWARE))
                | (1 << int(constants.Source.SYNTHETIC))
            ),
            supported_configuration_mask=constants.SUPPORTED_CONFIGURATION_MASK,
            applied_stream_mask=(
                configuration.stream_mask
                if configuration is not None
                else constants.StreamMask.NONE
            ),
            applied_source=constants.Source.SYNTHETIC,
            capability_bits=(
                Capability.ADC_STREAM
                | Capability.GPIO_STREAM
                | Capability.HARDWARE_SOURCE
                | Capability.SYNTHETIC_SOURCE
                | Capability.RESET_STATS
                | Capability.PING
                | Capability.CHECKSUM_BENCHMARK
                | Capability.GPIO_CLOCK_DIAGNOSTIC
                | Capability.GPIO_CAPTURE_DIAGNOSTIC
            ),
            gpio_capture_diagnostic_mode=(
                constants.GpioCaptureDiagnosticMode.NON_DRIVING_CAPTURE
            ),
            gpio_capture_diagnostic_flags=(
                constants.GpioCaptureDiagnosticFlag.AVAILABLE
                | constants.GpioCaptureDiagnosticFlag.DECLARATION_VALID
            ),
        )
        return self._success_response(request, info.to_payload())


class PacedRigSerial:
    """PySerial-shaped streaming peer with reset noise and partial I/O."""

    def __init__(self) -> None:
        self.device = HardwareSyntheticDevice()
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
            rig.DATA_FRAME_BYTES / rig.TARGET_COMBINED_FRAMED_BYTES_PER_SECOND
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
    def test_standalone_rig_tracks_the_selected_data_default(self) -> None:
        self.assertEqual(rig.CHECKSUM_ADLER32, rig.BOOTSTRAP_CHECKSUM)
        self.assertEqual(rig.CHECKSUM_ADLER32, rig.DEFAULT_DATA_CHECKSUM)
        self.assertEqual(
            {
                rig.CHECKSUM_ADLER32,
                rig.CHECKSUM_CRC32C,
                rig.CHECKSUM_CRC32_ISO_HDLC,
            },
            set(rig.SUPPORTED_CHECKSUMS),
        )

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
        self.assertNotIn("import thingdone_daq", source)
        self.assertNotIn("from thingdone_daq", source)
        self.assertNotIn("protocol-v1.json", source)
        self.assertIn('os.environ.get("SERIAL_PORT")', source)
        self.assertIn('"SYNTHETIC_CAPTURE_SECONDS"', source)
        self.assertIn("MAX_STATUS_SAMPLES", source)
        self.assertIn("STOP_DRAIN_DEADLINE_SECONDS", source)

    def test_independent_codec_matches_all_golden_frames(self) -> None:
        request_kind_by_name = {
            "info-request.bin": rig.INFO_REQUEST,
            "configure-request.bin": rig.CONFIGURE_REQUEST,
            "start-request.bin": rig.START_REQUEST,
            "get-status-request.bin": rig.GET_STATUS_REQUEST,
            "stop-request.bin": rig.STOP_REQUEST,
            "reset-stats-request.bin": rig.RESET_STATS_REQUEST,
            "ping-request.bin": rig.PING_REQUEST,
            "checksum-benchmark-request.bin": rig.CHECKSUM_BENCHMARK_REQUEST,
            "gpio-clock-diagnostic-request.bin": (rig.GPIO_CLOCK_DIAGNOSTIC_REQUEST),
        }
        for name, kind in request_kind_by_name.items():
            expected = (FIXTURES / name).read_bytes()
            request_id = int.from_bytes(expected[28:32], "little")
            payload = expected[rig.HEADER_SIZE : -rig.TRAILER_SIZE]
            with self.subTest(request=name):
                self.assertEqual(
                    expected, rig.encode_request(kind, request_id, payload)
                )

        parser = rig.FrameParser()
        decoded = []
        wire = bytearray(b"reset noise\xef\xbe")
        for path in sorted(FIXTURES.glob("*-response.bin")):
            wire.extend(path.read_bytes())
        wire.extend((FIXTURES / "adc-data.bin").read_bytes())
        wire.extend((FIXTURES / "gpio-data.bin").read_bytes())
        chunk_pattern = (1, 3, 509, 4095, 17, 8192)
        offset = 0
        chunk_index = 0
        while offset < len(wire):
            count = chunk_pattern[chunk_index % len(chunk_pattern)]
            decoded.extend(parser.feed(bytes(wire[offset : offset + count])))
            offset += count
            chunk_index += 1

        self.assertEqual(13, len(decoded))
        self.assertEqual(0, parser.errors)
        self.assertGreaterEqual(parser.bytes_discarded, len(b"reset noise\xef\xbe"))
        self.assertEqual(
            {rig.ADC_DATA, rig.GPIO_DATA},
            {frame.kind for frame in decoded} & rig.DATA_KINDS,
        )

    def test_parser_recovers_after_bad_checksum_and_validator_rejects_formula(
        self,
    ) -> None:
        valid_wire = (FIXTURES / "adc-data.bin").read_bytes()
        corrupt_wire = bytearray(valid_wire)
        corrupt_wire[rig.HEADER_SIZE + 11] ^= 0x80
        parser = rig.FrameParser()
        decoded = parser.feed(bytes(corrupt_wire) + valid_wire)
        self.assertEqual(1, parser.checksum_errors)
        self.assertEqual(1, len(decoded))

        frame = decoded[0]
        bad_payload = bytearray(frame.payload)
        bad_payload[0] ^= 1
        bad_frame = rig.Frame(
            kind=frame.kind,
            flags=frame.flags,
            checksum_algorithm=frame.checksum_algorithm,
            run_id=frame.run_id,
            sequence=frame.sequence,
            request_id=frame.request_id,
            first_sample_ticks=frame.first_sample_ticks,
            item_count=frame.item_count,
            payload=bytes(bad_payload),
            checksum=frame.checksum,
        )
        validator = rig.SyntheticValidator(frame.run_id, frame.checksum_algorithm)
        with self.assertRaisesRegex(rig.ProtocolFailure, "ADC pair"):
            validator.accept(bad_frame)

    def test_running_status_uses_the_pre_request_receive_floor(self) -> None:
        validator = rig.SyntheticValidator(7, rig.CHECKSUM_ADLER32)
        validator.adc.frames = 15
        validator.gpio.frames = 16
        status = rig.StatusSnapshot(
            device_state=rig.STATE_RUNNING,
            stream_mask=rig.STREAM_BOTH,
            source=rig.SOURCE_SYNTHETIC,
            checksum=rig.CHECKSUM_ADLER32,
            data_frame_bytes=rig.DATA_FRAME_BYTES,
            adc_frames_emitted=10,
            gpio_frames_emitted=10,
            adc_items_dropped=0,
            gpio_items_dropped=0,
            parser_errors=0,
            transport_errors=0,
            stats_generation=3,
        )
        frame = rig.Frame(
            kind=rig.GET_STATUS_RESPONSE,
            flags=0,
            checksum_algorithm=rig.BOOTSTRAP_CHECKSUM,
            run_id=7,
            sequence=0,
            request_id=1,
            first_sample_ticks=0,
            item_count=0,
            payload=b"",
            checksum=0,
        )

        rig.validate_running_status(status, frame, validator, 3, (8, 9))
        with self.assertRaisesRegex(
            rig.ProtocolFailure,
            "ADC counter trails frames received before STATUS request",
        ):
            rig.validate_running_status(status, frame, validator, 3, (11, 9))

    def test_validator_tracks_largest_receive_gap(self) -> None:
        frame = rig.FrameParser().feed((FIXTURES / "adc-data.bin").read_bytes())[0]
        validator = rig.SyntheticValidator(frame.run_id, frame.checksum_algorithm)
        validator.last_receive_time = 10.0

        with patch.object(rig.time, "monotonic", return_value=10.125):
            validator.accept(frame)

        self.assertEqual(0.125, validator.maximum_receive_gap_seconds)

    def test_independent_dispatch_and_host_benchmark_cover_every_algorithm(
        self,
    ) -> None:
        for algorithm in sorted(rig.SUPPORTED_CHECKSUMS):
            with self.subTest(algorithm=rig.CHECKSUM_NAMES[algorithm]):
                self.assertEqual(
                    rig.compute_checksum_fallback(b"123456789", algorithm),
                    rig.compute_checksum(b"123456789", algorithm),
                )
                wire = rig._encode_representative_data_frame(
                    rig.GPIO_DATA,
                    algorithm,
                )
                decoded = rig.FrameParser().feed(wire)
                self.assertEqual(1, len(decoded))
                self.assertEqual(algorithm, decoded[0].checksum_algorithm)

                benchmark = rig.benchmark_host_checksum_paths(
                    algorithm,
                    batch_count=1,
                    iterations_per_batch=1,
                    warmup_operations=0,
                )
                self.assertEqual(2, len(benchmark))
                self.assertTrue(
                    all(
                        not item["performance_is_wire_compatibility"]
                        for item in benchmark
                    )
                )
                self.assertTrue(
                    all(
                        item["encode"]["minimum_bytes_per_second"] > 0
                        for item in benchmark
                    )
                )
                self.assertTrue(
                    all(
                        item["validation"]["minimum_bytes_per_second"] > 0
                        for item in benchmark
                    )
                )

        with self.assertRaisesRegex(ValueError, "processed-byte bound"):
            rig.benchmark_host_checksum_paths(
                rig.CHECKSUM_ADLER32,
                batch_count=32,
                iterations_per_batch=4_096,
                warmup_operations=4_096,
            )
        with self.assertRaisesRegex(rig.ProtocolFailure, "host lacks"):
            rig.compute_checksum(b"payload", 0xFF)

    def test_full_program_streams_statuses_stops_and_reconciles(self) -> None:
        fake = PacedRigSerial()
        output = io.StringIO()
        environment = {
            "SERIAL_PORT": "fake-rig-port",
            "SYNTHETIC_CAPTURE_SECONDS": "0.12",
            "SYNTHETIC_STATUS_INTERVAL_SECONDS": "0.02",
            "EXPECTED_BUILD_ID": "thingdaq-0123456789abcdef",
            "EXPECTED_HARDWARE_SERIAL": "12345670",
        }
        with (
            patch.object(rig, "STARTUP_DRAIN_SECONDS", 0.002),
            patch.object(rig, "SYNC_DEADLINE_SECONDS", 0.1),
            patch.object(rig, "COMMAND_DEADLINE_SECONDS", 0.1),
            patch.object(rig, "STOP_DRAIN_DEADLINE_SECONDS", 0.2),
            patch.object(rig, "STOP_DRAIN_QUIET_SECONDS", 0.002),
            patch.object(rig, "RATE_TOLERANCE_FRACTION", 0.12),
            patch.object(rig.serial, "Serial", return_value=fake),
            patch.dict(os.environ, environment, clear=False),
            redirect_stdout(output),
        ):
            exit_code = rig.main()

        report = output.getvalue()
        self.assertEqual(0, exit_code, report)
        self.assertIn('"name":"identity.build_id","pass":true', report)
        self.assertIn('"name":"latency.status_p99_seconds","pass":true', report)
        self.assertIn('"name":"memory.peak_rss_growth_bytes","pass":true', report)
        self.assertIn('"event":"capture_complete"', report)
        self.assertIn('"event":"host_checksum_benchmark"', report)
        self.assertIn('"result":"PASS"', report)
        self.assertFalse(fake.is_open)
        self.assertIn(0, fake.write_counts)
        self.assertLessEqual(max(fake.read_counts), max(fake.read_pattern))
        self.assertEqual(constants.DeviceState.IDLE, fake.device.state)


if __name__ == "__main__":
    unittest.main()
