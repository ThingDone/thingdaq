"""Typed host coverage for the bounded firmware checksum benchmark wire result."""

from __future__ import annotations

import struct
import unittest
from pathlib import Path

from teensy_daq import (
    BenchmarkCacheState,
    BenchmarkMemoryRegion,
    BenchmarkVector,
    Capability,
    ChecksumAlgorithm,
    ChecksumBenchmarkRequest,
    ChecksumBenchmarkResult,
    DeviceState,
    ErrorCode,
    FrameKind,
    FrameValidationError,
    Info,
    SimulatedDevice,
    decode_frame,
    decode_response,
    encode_frame,
)
from teensy_daq._generated import protocol_constants as constants

REPOSITORY_ROOT = Path(__file__).resolve().parents[2]
FIXTURE_DIRECTORY = REPOSITORY_ROOT / "protocol/fixtures"


class ChecksumBenchmarkModelTests(unittest.TestCase):
    def test_request_matches_golden_wire_vector_and_reports_work_bound(self) -> None:
        request = ChecksumBenchmarkRequest(
            checksum_algorithm=ChecksumAlgorithm.ADLER32,
            vector=BenchmarkVector.CANONICAL_123456789,
            memory_region=BenchmarkMemoryRegion.DTCM_PACKET,
            cache_state=BenchmarkCacheState.HOT_OR_NATIVE,
            batch_count=4,
            iterations_per_batch=64,
        )
        fixture = decode_frame(
            (FIXTURE_DIRECTORY / "checksum-benchmark-request.bin").read_bytes()
        )

        self.assertEqual(
            request, ChecksumBenchmarkRequest.from_payload(fixture.payload)
        )
        self.assertEqual(fixture.payload, request.to_payload())
        self.assertEqual(256, request.operations)
        self.assertEqual(2_304, request.processed_bytes)

    def test_golden_response_decodes_all_measurements_and_q16_views(self) -> None:
        frame = decode_frame(
            (FIXTURE_DIRECTORY / "checksum-benchmark-response.bin").read_bytes()
        )
        response = decode_response(frame)

        self.assertTrue(response.ok)
        self.assertIsInstance(response.value, ChecksumBenchmarkResult)
        assert isinstance(response.value, ChecksumBenchmarkResult)
        result = response.value
        self.assertEqual(600_000_000, result.cycle_counter_hz)
        self.assertEqual(2_304, result.processed_bytes)
        self.assertEqual(10_240, result.raw_checksum_cycles)
        self.assertEqual(9_216, result.net_checksum_cycles)
        self.assertEqual(0x12345678, result.deterministic_digest)
        self.assertEqual(4.0, result.cycles_per_byte)
        self.assertEqual(150.0, result.mb_per_second)
        self.assertAlmostEqual(5.4, result.projected_cpu_percent, places=4)

    def test_request_rejects_unbounded_or_meaningless_cache_combinations(self) -> None:
        with self.assertRaisesRegex(ValueError, "duration bound"):
            ChecksumBenchmarkRequest(
                checksum_algorithm=ChecksumAlgorithm.CRC32C,
                vector=BenchmarkVector.FRAME_COVERAGE,
                memory_region=BenchmarkMemoryRegion.OCRAM_DMA,
                cache_state=BenchmarkCacheState.HOT_OR_NATIVE,
                batch_count=constants.CHECKSUM_BENCHMARK_MAX_BATCH_COUNT,
                iterations_per_batch=(
                    constants.CHECKSUM_BENCHMARK_MAX_ITERATIONS_PER_BATCH
                ),
            )

        with self.assertRaisesRegex(ValueError, "nonempty DMA-visible OCRAM"):
            ChecksumBenchmarkRequest(
                checksum_algorithm=ChecksumAlgorithm.ADLER32,
                vector=BenchmarkVector.EMPTY,
                memory_region=BenchmarkMemoryRegion.OCRAM_DMA,
                cache_state=BenchmarkCacheState.COLD_INVALIDATED,
                batch_count=1,
                iterations_per_batch=1,
            )

    def test_wire_validator_rejects_inconsistent_derived_metrics(self) -> None:
        frame = decode_frame(
            (FIXTURE_DIRECTORY / "checksum-benchmark-response.bin").read_bytes()
        )
        payload = bytearray(frame.payload)
        struct.pack_into(
            "<I",
            payload,
            constants.CHECKSUM_BENCHMARK_RESPONSE_CYCLES_PER_BYTE_Q16_OFFSET,
            1,
        )

        with self.assertRaisesRegex(FrameValidationError, "derived metrics"):
            encode_frame(
                FrameKind.CHECKSUM_BENCHMARK_RESPONSE,
                payload,
                request_id=frame.header.request_id,
            )

    def test_simulator_neither_advertises_nor_fabricates_target_measurements(
        self,
    ) -> None:
        device = SimulatedDevice()
        info_response = decode_response(
            decode_frame(
                device.receive(encode_frame(FrameKind.INFO_REQUEST, request_id=41))[0]
            )
        )
        info = info_response.value
        self.assertIsInstance(info, Info)
        assert isinstance(info, Info)
        before = device.status()
        request = ChecksumBenchmarkRequest(
            checksum_algorithm=ChecksumAlgorithm.ADLER32,
            vector=BenchmarkVector.BUFFER_64,
            memory_region=BenchmarkMemoryRegion.DTCM_PACKET,
            cache_state=BenchmarkCacheState.HOT_OR_NATIVE,
            batch_count=1,
            iterations_per_batch=1,
        )
        wire = encode_frame(
            FrameKind.CHECKSUM_BENCHMARK_REQUEST,
            request.to_payload(),
            request_id=42,
        )

        response = decode_response(decode_frame(device.receive(wire)[0]))

        self.assertFalse(info.supports_capability(Capability.CHECKSUM_BENCHMARK))
        self.assertFalse(response.ok)
        self.assertEqual(ErrorCode.UNSUPPORTED_CONFIGURATION, response.error_code)
        self.assertEqual(DeviceState.IDLE, device.state)
        self.assertEqual(before, device.status())


if __name__ == "__main__":
    unittest.main()
