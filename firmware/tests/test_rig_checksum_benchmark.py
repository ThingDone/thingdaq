"""Offline verification for the independent Phase 05 checksum rig campaign."""

from __future__ import annotations

import ast
import importlib.util
import io
import math
import os
import stat
import struct
import sys
import time
import unittest
from contextlib import redirect_stdout
from pathlib import Path
from types import ModuleType
from unittest.mock import patch

from teensy_daq import (
    BoardId,
    Capability,
    Info,
    McuId,
    SimulatedDevice,
    StreamMask,
)
from teensy_daq._generated import protocol_constants as constants

ROOT = Path(__file__).resolve().parents[2]
RIG_SCRIPT = ROOT / "firmware" / "tests" / "rig_checksum_benchmark.py"
FIXTURES = ROOT / "protocol" / "fixtures"


def _load_rig_script() -> ModuleType:
    specification = importlib.util.spec_from_file_location(
        "independent_rig_checksum_benchmark",
        RIG_SCRIPT,
    )
    if specification is None or specification.loader is None:
        raise RuntimeError("could not load rig_checksum_benchmark.py")
    module = importlib.util.module_from_spec(specification)
    sys.modules[specification.name] = module
    specification.loader.exec_module(module)
    return module


rig = _load_rig_script()


class HardwareBenchmarkDevice(SimulatedDevice):
    """Streaming simulator with independently fabricated target measurements."""

    def __init__(self) -> None:
        super().__init__(build_id="tdaq-0123456789abcdef")
        self.benchmark_requests: list[object] = []
        self.configured_checksums: list[int] = []

    def _handle_info(self, request):  # type: ignore[no-untyped-def]
        info = Info(
            device_state=self.state,
            build_id="tdaq-0123456789abcdef",
            hardware_serial=12_345_670,
            firmware_version=(0, 6, 0),
            board_id=BoardId.TEENSY_40,
            mcu_id=McuId.IMXRT1062,
            supported_stream_mask=StreamMask.ADC | StreamMask.GPIO,
            supported_source_mask=1 << int(constants.Source.SYNTHETIC),
            data_checksum_algorithm=self.status().data_checksum_algorithm,
            capability_bits=(
                Capability.ADC_STREAM
                | Capability.GPIO_STREAM
                | Capability.SYNTHETIC_SOURCE
                | Capability.RESET_STATS
                | Capability.PING
                | Capability.CHECKSUM_BENCHMARK
                | Capability.GPIO_CLOCK_DIAGNOSTIC
            ),
        )
        return self._success_response(request, info.to_payload())

    def _handle_configure(self, request):  # type: ignore[no-untyped-def]
        self.configured_checksums.append(request.payload[2])
        return super()._handle_configure(request)

    def _handle_checksum_benchmark(self, request):  # type: ignore[no-untyped-def]
        selection = rig.BenchmarkSelection(
            *rig.BENCHMARK_REQUEST.unpack(request.payload)
        )
        self.benchmark_requests.append(selection)
        operations = selection.operations
        operation_cycles = selection.buffer_bytes * 2 + 10
        batch_cycles = operation_cycles * selection.iterations_per_batch
        net_cycles = batch_cycles * selection.batch_count
        overhead_cycles = 6
        raw_cycles = net_cycles + operations * overhead_cycles
        cache_setup_cycles = (
            operations * (selection.buffer_bytes // 32 + 5)
            if selection.cache_state == rig.CACHE_COLD_INVALIDATED
            else 0
        )
        total_cycles = net_cycles + cache_setup_cycles
        if selection.processed_bytes:
            cycles_per_byte_q16 = total_cycles * 65_536 // selection.processed_bytes
            bytes_per_second = (
                rig.BENCHMARK_CYCLE_COUNTER_HZ
                * selection.processed_bytes
                // total_cycles
            )
            mb_per_second_q16 = bytes_per_second * 65_536 // 1_000_000
            projected_cpu_q16 = (
                cycles_per_byte_q16
                * rig.BENCHMARK_TARGET_FRAMED_BYTES_PER_SECOND
                * 100
                // rig.BENCHMARK_CYCLE_COUNTER_HZ
            )
        else:
            cycles_per_byte_q16 = 0
            mb_per_second_q16 = 0
            projected_cpu_q16 = 0

        payload = bytearray(rig.SUCCESS_PAYLOAD_SIZE[rig.CHECKSUM_BENCHMARK_RESPONSE])
        rig.RESPONSE_PREFIX.pack_into(payload, 0, 0, 0, 0)
        payload[4:12] = request.payload
        values_u32 = {
            12: selection.buffer_bytes,
            16: rig.BENCHMARK_CYCLE_COUNTER_HZ,
            20: overhead_cycles,
            24: 120 if selection.checksum_algorithm == rig.CHECKSUM_ADLER32 else 308,
            28: (0 if selection.checksum_algorithm == rig.CHECKSUM_ADLER32 else 8_192),
            32: rig.BENCHMARK_WORKING_RAM_BYTES,
            36: rig.expected_benchmark_digest(
                rig.EXPECTED_VECTOR_CHECKSUMS[selection.checksum_algorithm][
                    selection.vector
                ],
                operations,
            ),
            72: batch_cycles,
            76: batch_cycles,
            80: cycles_per_byte_q16,
            84: mb_per_second_q16,
            88: projected_cpu_q16,
            92: rig.BENCHMARK_TARGET_FRAMED_BYTES_PER_SECOND,
        }
        for offset, value in values_u32.items():
            struct.pack_into("<I", payload, offset, value)
        for offset, value in {
            40: selection.processed_bytes,
            48: raw_cycles,
            56: net_cycles,
            64: cache_setup_cycles,
        }.items():
            struct.pack_into("<Q", payload, offset, value)
        return self._success_response(request, payload)


class PacedRigSerial:
    """PySerial-shaped peer with reset noise, partial I/O, and target pacing."""

    def __init__(self) -> None:
        self.device = HardwareBenchmarkDevice()
        self.timeout = 0.001
        self.write_timeout = 0.1
        self.is_open = True
        self.pending = bytearray(b"late reset text\r\n\xef\xbe")
        self.read_pattern = (1, 509, 2_048, 8_192, 37, 65_536)
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


class RigChecksumBenchmarkTests(unittest.TestCase):
    def test_program_is_executable_one_file_stdlib_plus_pyserial(self) -> None:
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
                "array",
                "collections",
                "dataclasses",
                "gc",
                "json",
                "math",
                "os",
                "re",
                "serial",
                "struct",
                "sys",
                "threading",
                "time",
                "typing",
                "zlib",
            },
            imports,
        )
        self.assertNotIn("teensy_daq", source)
        self.assertNotIn("protocol-v1.json", source)
        self.assertIn('os.environ.get("SERIAL_PORT")', source)
        self.assertIn('"CHECKSUM_CAPTURE_SECONDS"', source)
        self.assertIn('"CHECKSUM_BENCHMARK_BATCH_COUNT"', source)
        self.assertIn('"CHECKSUM_CAMPAIGN_ALGORITHM"', source)
        self.assertTrue(RIG_SCRIPT.stat().st_mode & stat.S_IXUSR)

    def test_optional_campaign_selector_accepts_names_and_ids(self) -> None:
        with patch.dict(os.environ, {}, clear=True):
            self.assertIsNone(
                rig._optional_checksum_environment("CHECKSUM_CAMPAIGN_ALGORITHM")
            )
        for raw, expected in (
            ("ADLER32", rig.CHECKSUM_ADLER32),
            ("crc32c", rig.CHECKSUM_CRC32C),
            ("CRC32-ISO-HDLC", rig.CHECKSUM_CRC32_ISO_HDLC),
            ("0x2", rig.CHECKSUM_CRC32C),
        ):
            with (
                self.subTest(raw=raw),
                patch.dict(
                    os.environ,
                    {"CHECKSUM_CAMPAIGN_ALGORITHM": raw},
                    clear=True,
                ),
            ):
                self.assertEqual(
                    expected,
                    rig._optional_checksum_environment("CHECKSUM_CAMPAIGN_ALGORITHM"),
                )
        for raw in ("", "CRC64", "99"):
            with (
                self.subTest(raw=raw),
                patch.dict(
                    os.environ,
                    {"CHECKSUM_CAMPAIGN_ALGORITHM": raw},
                    clear=True,
                ),
                self.assertRaises(ValueError),
            ):
                rig._optional_checksum_environment("CHECKSUM_CAMPAIGN_ALGORITHM")

    def test_vectors_and_profile_matrix_are_fixed_and_bounded(self) -> None:
        records = rig.validate_independent_vectors()
        self.assertEqual(15, len(records))
        self.assertEqual(
            0xE3069283,
            rig.reference_checksum(b"123456789", rig.CHECKSUM_CRC32C),
        )
        self.assertEqual(
            0xCBF43926,
            rig.compute_checksum(b"123456789", rig.CHECKSUM_CRC32_ISO_HDLC),
        )
        for algorithm in sorted(rig.SUPPORTED_CHECKSUMS):
            selections = rig.benchmark_selections(
                algorithm,
                batch_count=rig.MAX_BENCHMARK_BATCH_COUNT,
                iterations_per_batch=rig.MAX_BENCHMARK_ITERATIONS_PER_BATCH,
            )
            self.assertEqual(14, len(selections))
            self.assertLessEqual(
                max(selection.processed_bytes for selection in selections),
                rig.MAX_BENCHMARK_PROCESSED_BYTES,
            )
            self.assertTrue(
                all(
                    selection.cache_state != rig.CACHE_COLD_INVALIDATED
                    or (
                        selection.vector != rig.VECTOR_EMPTY
                        and selection.memory_region == rig.MEMORY_OCRAM_DMA
                    )
                    for selection in selections
                )
            )
        self.assertEqual(528, len(rig.SYNTHETIC_CRC32C_PAYLOAD_CHECKSUMS))

        body = rig.benchmark_vector_bytes(
            rig.VECTOR_FRAME_COVERAGE,
            rig.CHECKSUM_CRC32C,
        )
        header_checksum = rig._table_crc32(body[: rig.HEADER_SIZE], rig.CRC32C_TABLE)
        payload_checksum = rig._table_crc32(
            body[rig.HEADER_SIZE :],
            rig.CRC32C_TABLE,
        )
        combined = (
            rig._gf2_matrix_times(
                rig.CRC32C_PAYLOAD_SHIFT_OPERATOR,
                header_checksum,
            )
            ^ payload_checksum
        )
        self.assertEqual(rig._table_crc32(body, rig.CRC32C_TABLE), combined)
        shift_0, shift_1, shift_2, shift_3 = rig.CRC32C_PAYLOAD_SHIFT_BYTE_TABLES
        table_shifted = (
            shift_0[header_checksum & 0xFF]
            ^ shift_1[(header_checksum >> 8) & 0xFF]
            ^ shift_2[(header_checksum >> 16) & 0xFF]
            ^ shift_3[header_checksum >> 24]
        )
        self.assertEqual(
            rig._gf2_matrix_times(
                rig.CRC32C_PAYLOAD_SHIFT_OPERATOR,
                header_checksum,
            ),
            table_shifted,
        )

    def test_independent_codec_matches_fixtures_and_recovers_bad_trailer(self) -> None:
        for path in sorted(FIXTURES.glob("*-request.bin")):
            expected = path.read_bytes()
            kind = expected[5]
            request_id = int.from_bytes(expected[28:32], "little")
            payload = expected[rig.HEADER_SIZE : -rig.TRAILER_SIZE]
            with self.subTest(request=path.name):
                self.assertEqual(
                    expected,
                    rig.encode_request(kind, request_id, payload),
                )

        parser = rig.FrameParser()
        decoded = []
        wire = bytearray(b"reset noise\xef\xbe")
        for path in sorted(FIXTURES.glob("*-response.bin")):
            wire.extend(path.read_bytes())
        wire.extend((FIXTURES / "adc-data.bin").read_bytes())
        wire.extend((FIXTURES / "gpio-data.bin").read_bytes())
        for offset in range(0, len(wire), 509):
            decoded.extend(parser.feed(bytes(wire[offset : offset + 509])))
        self.assertEqual(13, len(decoded))
        self.assertEqual(0, parser.errors)

        valid = (FIXTURES / "gpio-data.bin").read_bytes()
        damaged = bytearray(valid)
        damaged[-1] ^= 0x80
        recovered = rig.FrameParser()
        self.assertEqual(1, len(recovered.feed(bytes(damaged) + valid)))
        self.assertEqual(1, recovered.checksum_errors)

    def test_synthetic_crc32c_parser_and_formula_checks_are_independent(self) -> None:
        payload = rig.ADC_PATTERN_DOUBLE[: rig.DATA_PAYLOAD_BYTES]
        header = rig.HEADER.pack(
            rig.MAGIC,
            rig.PROTOCOL_VERSION,
            rig.ADC_DATA,
            rig.FLAG_SYNTHETIC | rig.FLAG_EPOCH_START,
            rig.HEADER_SIZE,
            rig.CHECKSUM_CRC32C,
            0,
            rig.DATA_FRAME_BYTES,
            rig.DATA_PAYLOAD_BYTES,
            7,
            0,
            0,
            0,
            rig.ADC_PAIRS_PER_FRAME,
        )
        body = header + payload
        valid = body + rig.TRAILER.pack(rig.compute_checksum(body, rig.CHECKSUM_CRC32C))
        oracle = rig.build_synthetic_crc32c_oracle(7, 0.01)
        expected_sequences = (
            math.ceil(0.01 * rig.TIMESTAMP_HZ / rig.FRAME_COVERAGE_TICKS)
            + rig.CRC32C_ORACLE_DRAIN_MARGIN_FRAMES
        )
        self.assertEqual(expected_sequences, oracle.sequences_per_stream)
        self.assertEqual(2 * expected_sequences, oracle.entry_count)
        self.assertEqual(oracle.entry_count * 4, oracle.storage_bytes)
        parser = rig.FrameParser()
        parser.synthetic_crc32c_oracle = oracle
        frames = parser.feed(valid)
        self.assertEqual(1, len(frames))
        self.assertEqual(1, parser.synthetic_crc32c_combined_checks)
        self.assertEqual(1, parser.synthetic_crc32c_oracle_checks)
        self.assertEqual(0, parser.full_crc32c_data_checks)
        rig.SyntheticValidator(7, rig.CHECKSUM_CRC32C).accept(frames[0])

        changed_payload = bytearray(payload)
        changed_payload[0] ^= 1
        changed_body = header + bytes(changed_payload)
        changed_wire = changed_body + rig.TRAILER.pack(
            rig.compute_checksum(changed_body, rig.CHECKSUM_CRC32C)
        )
        checksum_guard = rig.FrameParser()
        checksum_guard.synthetic_crc32c_oracle = oracle
        self.assertEqual([], checksum_guard.feed(changed_wire))
        self.assertEqual(1, checksum_guard.checksum_errors)

        formula_guard = rig.FrameParser()
        formula_guard.synthetic_crc32c_oracle = oracle
        formula_frames = formula_guard.feed(bytes(changed_body) + valid[-4:])
        self.assertEqual(1, len(formula_frames))
        with self.assertRaisesRegex(rig.ProtocolFailure, "ADC pair"):
            rig.SyntheticValidator(7, rig.CHECKSUM_CRC32C).accept(formula_frames[0])

    def test_benchmark_decoder_rejects_a_wrong_target_digest(self) -> None:
        device = HardwareBenchmarkDevice()
        selection = rig.BenchmarkSelection(
            checksum_algorithm=rig.CHECKSUM_CRC32C,
            vector=rig.VECTOR_FRAME_COVERAGE,
            memory_region=rig.MEMORY_DTCM_PACKET,
            cache_state=rig.CACHE_HOT_OR_NATIVE,
            batch_count=1,
            iterations_per_batch=2,
        )
        responses = device.receive(
            rig.encode_request(
                rig.CHECKSUM_BENCHMARK_REQUEST,
                91,
                selection.to_payload(),
            )
        )
        frame = rig.FrameParser().feed(responses[0])[0]
        measurement = rig.decode_benchmark_measurement(frame, selection)
        self.assertEqual(
            rig.expected_benchmark_digest(
                rig.EXPECTED_VECTOR_CHECKSUMS[rig.CHECKSUM_CRC32C][
                    rig.VECTOR_FRAME_COVERAGE
                ],
                2,
            ),
            measurement.deterministic_digest,
        )

        bad_payload = bytearray(frame.payload)
        bad_payload[36] ^= 1
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
        with self.assertRaisesRegex(
            rig.ProtocolFailure,
            "raw/resource fields disagree",
        ):
            rig.decode_benchmark_measurement(bad_frame, selection)

    def test_full_campaign_benchmarks_and_streams_all_candidates(self) -> None:
        fake = PacedRigSerial()
        output = io.StringIO()
        original_switch_interval = sys.getswitchinterval()
        environment = {
            "SERIAL_PORT": "fake-rig-port",
            "CHECKSUM_CAPTURE_SECONDS": "0.12",
            "CHECKSUM_STATUS_INTERVAL_SECONDS": "0.02",
            "CHECKSUM_BENCHMARK_BATCH_COUNT": "1",
            "CHECKSUM_BENCHMARK_ITERATIONS_PER_BATCH": "2",
            "EXPECTED_BUILD_ID": "tdaq-0123456789abcdef",
            "EXPECTED_HARDWARE_SERIAL": "12345670",
        }
        with (
            patch.object(rig, "STARTUP_DRAIN_SECONDS", 0.002),
            patch.object(rig, "SYNC_DEADLINE_SECONDS", 0.1),
            patch.object(rig, "COMMAND_DEADLINE_SECONDS", 0.1),
            patch.object(rig, "BENCHMARK_DEADLINE_SECONDS", 0.1),
            patch.object(rig, "STOP_DRAIN_DEADLINE_SECONDS", 0.2),
            patch.object(rig, "STOP_DRAIN_QUIET_SECONDS", 0.002),
            # The fake computes CRC-32C twice in one Python process (device
            # encode plus rig validation), unlike the 600 MHz target. Keep the
            # flow/timing checks active without grading this host's fake speed.
            patch.object(rig, "RATE_TOLERANCE_FRACTION", 0.50),
            patch.object(rig.serial, "Serial", return_value=fake),
            patch.dict(os.environ, environment, clear=False),
            redirect_stdout(output),
        ):
            exit_code = rig.main()

        report = output.getvalue()
        self.assertEqual(0, exit_code, report)
        self.assertEqual(15, report.count('"event":"independent_vector"'))
        self.assertEqual(42, report.count('"event":"device_checksum_benchmark"'))
        self.assertEqual(3, report.count("CANDIDATE "))
        self.assertIn(
            '"firmware_internal_depth_available_in_protocol_v1":false', report
        )
        self.assertIn('"total_reported_flash_bytes":120', report)
        self.assertIn('"total_reported_flash_bytes":8500', report)
        self.assertIn('"result":"PASS"', report)
        self.assertEqual(
            [
                rig.CHECKSUM_ADLER32,
                rig.CHECKSUM_CRC32C,
                rig.CHECKSUM_CRC32_ISO_HDLC,
            ],
            fake.device.configured_checksums,
        )
        self.assertEqual(42, len(fake.device.benchmark_requests))
        self.assertIn('"crc32c_full_data_checks":0', report)
        self.assertIn('"crc32c_synthetic_combined_checks":', report)
        self.assertIn(
            '"host_serial_reader":{"capacity_bytes":524288,'
            '"capacity_chunks":32,"enabled":true',
            report,
        )
        self.assertFalse(fake.is_open)
        self.assertIn(0, fake.write_counts)
        self.assertLessEqual(max(fake.read_counts), rig.SERIAL_READ_BYTES)
        self.assertEqual(original_switch_interval, sys.getswitchinterval())
        self.assertEqual(constants.DeviceState.IDLE, fake.device.state)

    def test_selected_campaign_benchmarks_and_streams_only_one_candidate(self) -> None:
        fake = PacedRigSerial()
        output = io.StringIO()
        with (
            patch.object(rig, "STARTUP_DRAIN_SECONDS", 0.002),
            patch.object(rig, "SYNC_DEADLINE_SECONDS", 0.1),
            patch.object(rig, "COMMAND_DEADLINE_SECONDS", 0.1),
            patch.object(rig, "BENCHMARK_DEADLINE_SECONDS", 0.1),
            patch.object(rig, "STOP_DRAIN_DEADLINE_SECONDS", 0.2),
            patch.object(rig, "STOP_DRAIN_QUIET_SECONDS", 0.002),
            patch.object(rig, "RATE_TOLERANCE_FRACTION", 0.50),
            redirect_stdout(output),
        ):
            summary = rig.run_campaign(
                fake,
                capture_seconds=0.12,
                status_interval_seconds=0.02,
                benchmark_batch_count=1,
                benchmark_iterations_per_batch=2,
                expected_build_id="tdaq-0123456789abcdef",
                expected_hardware_serial=12_345_670,
                selected_checksum_algorithm=rig.CHECKSUM_CRC32C,
            )

        self.assertEqual("PASS", summary["result"])
        self.assertEqual(3, summary["advertised_candidate_count"])
        self.assertEqual([rig.CHECKSUM_CRC32C], summary["campaign_candidate_ids"])
        self.assertEqual(1, summary["candidate_count"])
        self.assertEqual([rig.CHECKSUM_CRC32C], fake.device.configured_checksums)
        self.assertEqual(14, len(fake.device.benchmark_requests))
        validation = summary["candidates"][0]["stream"]["checksum_validation"]
        expected_data_frames = sum(
            summary["candidates"][0]["stream"]["frames"][key] for key in ("adc", "gpio")
        )
        self.assertEqual(
            expected_data_frames, validation["crc32c_synthetic_combined_checks"]
        )
        self.assertEqual(expected_data_frames, validation["crc32c_oracle_checks"])
        self.assertEqual(0, validation["crc32c_full_data_checks"])
        self.assertGreater(validation["crc32c_oracle_entry_count"], 0)
        self.assertEqual(
            validation["crc32c_oracle_entry_count"] * 4,
            validation["crc32c_oracle_storage_bytes"],
        )
        self.assertEqual(1, output.getvalue().count("CANDIDATE "))
        self.assertEqual(constants.DeviceState.IDLE, fake.device.state)


if __name__ == "__main__":
    unittest.main()
