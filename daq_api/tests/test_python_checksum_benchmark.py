"""Host checksum backend, benchmark, and surfaced-metadata coverage."""

from __future__ import annotations

import unittest
from unittest.mock import patch

from thingdaq import (
    HOST_SUPPORTED_CHECKSUM_ALGORITHMS,
    ADCBlock,
    ChecksumAlgorithm,
    DeviceState,
    Status,
    ThingDAQ,
    UnsupportedChecksumError,
    checksum_backend,
    compute_checksum,
)
from thingdaq._generated import protocol_constants as constants
from thingdaq.checksum import _compute_checksum_fallback
from thingdaq.checksum_benchmark import (
    HostChecksumBenchmarkResult,
    benchmark_checksum_throughput,
    benchmark_report,
)


class PythonChecksumBackendTests(unittest.TestCase):
    def test_dispatch_prefers_exact_standard_library_backends_and_has_fallbacks(
        self,
    ) -> None:
        data = memoryview(bytes(range(256)) * 3)[1:-1]
        try:
            for algorithm in sorted(HOST_SUPPORTED_CHECKSUM_ALGORITHMS, key=int):
                with self.subTest(algorithm=algorithm.name):
                    fallback = _compute_checksum_fallback(data, algorithm)
                    self.assertIsNotNone(fallback)
                    self.assertEqual(fallback, compute_checksum(data, algorithm))
        finally:
            data.release()

        self.assertEqual(
            "zlib.adler32", checksum_backend(ChecksumAlgorithm.ADLER32).implementation
        )
        self.assertTrue(checksum_backend(ChecksumAlgorithm.ADLER32).accelerated)
        self.assertEqual(
            "python.slicing_by_four.crc32c",
            checksum_backend(ChecksumAlgorithm.CRC32C).implementation,
        )
        self.assertFalse(checksum_backend(ChecksumAlgorithm.CRC32C).accelerated)
        self.assertEqual(
            "zlib.crc32",
            checksum_backend(ChecksumAlgorithm.CRC32_ISO_HDLC).implementation,
        )

    def test_missing_backend_fails_with_the_wire_algorithm_id(self) -> None:
        with (
            patch("thingdaq.protocol.compute_checksum_value", return_value=None),
            self.assertRaisesRegex(
                UnsupportedChecksumError,
                "unsupported checksum algorithm 2",
            ),
        ):
            compute_checksum(b"payload", ChecksumAlgorithm.CRC32C)


class PythonChecksumBenchmarkTests(unittest.TestCase):
    def test_encode_and_validation_are_separate_bounded_measurements(self) -> None:
        results = benchmark_checksum_throughput(
            (ChecksumAlgorithm.CRC32C,),
            batch_count=2,
            iterations_per_batch=2,
            warmup_operations=1,
        )

        self.assertEqual(2, len(results))
        self.assertTrue(
            all(isinstance(item, HostChecksumBenchmarkResult) for item in results)
        )
        self.assertEqual(
            {constants.FrameKind.ADC_DATA, constants.FrameKind.GPIO_DATA},
            {item.frame_kind for item in results},
        )
        for result in results:
            self.assertEqual(constants.DATA_FRAME_BYTES, result.frame_bytes)
            self.assertEqual(
                constants.DATA_FRAME_BYTES - constants.TRAILER_SIZE,
                result.checksum_coverage_bytes,
            )
            self.assertEqual("encode", result.encode.operation)
            self.assertEqual("validation", result.validation.operation)
            self.assertEqual(4, result.encode.operations)
            self.assertEqual(4, result.validation.operations)
            self.assertGreater(result.encode.minimum_bytes_per_second, 0)
            self.assertGreater(result.validation.minimum_bytes_per_second, 0)

        report = benchmark_report(results)
        self.assertEqual("thingdaq-python-checksum-benchmark-v1", report["schema"])
        self.assertFalse(report["performance_is_wire_compatibility"])

        with self.assertRaisesRegex(ValueError, "batch_count"):
            benchmark_checksum_throughput(
                (ChecksumAlgorithm.ADLER32,),
                batch_count=0,
            )
        with self.assertRaisesRegex(ValueError, "processed-byte bound"):
            benchmark_checksum_throughput(
                (ChecksumAlgorithm.ADLER32,),
                batch_count=32,
                iterations_per_batch=4_096,
                warmup_operations=4_096,
            )


class ChecksumMetadataTests(unittest.TestCase):
    def test_info_status_and_blocks_expose_the_selected_algorithm(self) -> None:
        for algorithm in sorted(HOST_SUPPORTED_CHECKSUM_ALGORITHMS, key=int):
            with (
                self.subTest(algorithm=algorithm.name),
                ThingDAQ.simulated() as daq,
            ):
                self.assertEqual(
                    constants.DEFAULT_CHECKSUM_ALGORITHM,
                    daq.info().data_checksum_algorithm,
                )
                daq.configure(
                    adc=True,
                    gpio=False,
                    checksum_algorithm=algorithm,
                )
                configured_info = daq.info()
                self.assertEqual(
                    algorithm,
                    configured_info.data_checksum_algorithm,
                )
                self.assertTrue(configured_info.supports_checksum(algorithm))
                configured_status = daq.status()
                self.assertEqual(algorithm, configured_status.checksum_algorithm)
                daq.start()
                block = daq.read_block()
                self.assertIsInstance(block, ADCBlock)
                assert isinstance(block, ADCBlock)
                self.assertEqual(algorithm, block.checksum_algorithm)
                self.assertEqual(algorithm, block.data_checksum_algorithm)
                running = daq.status()
                self.assertEqual(DeviceState.RUNNING, running.device_state)
                self.assertEqual(algorithm, running.data_checksum_algorithm)
                daq.stop()

    def test_standalone_status_alias_is_exact(self) -> None:
        status = Status(
            device_state=DeviceState.IDLE,
            stream_mask=constants.StreamMask.NONE,
            source=constants.Source.SYNTHETIC,
            data_checksum_algorithm=ChecksumAlgorithm.CRC32_ISO_HDLC,
        )
        self.assertIs(
            ChecksumAlgorithm.CRC32_ISO_HDLC,
            status.checksum_algorithm,
        )


if __name__ == "__main__":
    unittest.main()
