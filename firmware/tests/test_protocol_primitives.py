"""Host-compiled tests for the portable fixed-capacity protocol layer."""

from __future__ import annotations

import shutil
import struct
import subprocess
import tempfile
import unittest
from pathlib import Path

from thingdaq import decode_frame, decode_response, encode_frame
from thingdaq._generated import protocol_constants as constants

REPOSITORY_ROOT = Path(__file__).resolve().parents[2]
FIRMWARE_SOURCE = REPOSITORY_ROOT / "firmware/src"
CPP_TEST = REPOSITORY_ROOT / "firmware/tests/protocol_primitives_test.cpp"
PROTOCOL_SOURCE = FIRMWARE_SOURCE / "protocol.cpp"
PROTOCOL_HEADER = FIRMWARE_SOURCE / "protocol.h"
FIXTURE_DIRECTORY = REPOSITORY_ROOT / "protocol/fixtures"


class ProtocolPrimitiveTests(unittest.TestCase):
    def test_portable_protocol_and_python_interop_match_golden_frames(self) -> None:
        compiler = shutil.which("g++")
        if compiler is None:
            self.skipTest("g++ is required for portable firmware tests")

        with tempfile.TemporaryDirectory(prefix="thingdaq-protocol-") as directory:
            executable = Path(directory) / "protocol-primitives-test"
            compile_result = subprocess.run(
                [
                    compiler,
                    "-std=c++17",
                    "-Wall",
                    "-Wextra",
                    "-Werror",
                    "-Wconversion",
                    "-Wsign-conversion",
                    "-pedantic",
                    "-fno-exceptions",
                    "-fno-rtti",
                    f"-I{FIRMWARE_SOURCE}",
                    str(CPP_TEST),
                    str(PROTOCOL_SOURCE),
                    str(FIRMWARE_SOURCE / "checksum.cpp"),
                    "-o",
                    str(executable),
                ],
                capture_output=True,
                check=False,
                text=True,
            )
            self.assertEqual(
                0,
                compile_result.returncode,
                compile_result.stdout + compile_result.stderr,
            )
            run_result = subprocess.run(
                [str(executable), str(FIXTURE_DIRECTORY)],
                capture_output=True,
                check=False,
                text=True,
            )
            self.assertEqual(
                0,
                run_result.returncode,
                run_result.stdout + run_result.stderr,
            )

            python_commands = Path(directory) / "python-commands"
            cpp_responses = Path(directory) / "cpp-responses"
            python_commands.mkdir()
            cpp_responses.mkdir()
            configuration = struct.pack(
                "<BBBBI",
                3,
                constants.Source.SYNTHETIC,
                constants.ChecksumAlgorithm.ADLER32,
                0,
                constants.DATA_FRAME_BYTES,
            )
            request_specs = (
                ("info-request.bin", constants.FrameKind.INFO_REQUEST, b"", 1),
                (
                    "configure-request.bin",
                    constants.FrameKind.CONFIGURE_REQUEST,
                    configuration,
                    2,
                ),
                ("start-request.bin", constants.FrameKind.START_REQUEST, b"", 3),
                (
                    "get-status-request.bin",
                    constants.FrameKind.GET_STATUS_REQUEST,
                    b"",
                    4,
                ),
                ("stop-request.bin", constants.FrameKind.STOP_REQUEST, b"", 5),
                (
                    "reset-stats-request.bin",
                    constants.FrameKind.RESET_STATS_REQUEST,
                    b"",
                    6,
                ),
                (
                    "ping-request.bin",
                    constants.FrameKind.PING_REQUEST,
                    struct.pack("<Q", 0x0123456789ABCDEF),
                    7,
                ),
                (
                    "checksum-benchmark-request.bin",
                    constants.FrameKind.CHECKSUM_BENCHMARK_REQUEST,
                    struct.pack(
                        "<BBBBHH",
                        constants.ChecksumAlgorithm.ADLER32,
                        constants.BenchmarkVector.CANONICAL_123456789,
                        constants.BenchmarkMemoryRegion.DTCM_PACKET,
                        constants.BenchmarkCacheState.HOT_OR_NATIVE,
                        4,
                        64,
                    ),
                    8,
                ),
                (
                    "gpio-clock-diagnostic-request.bin",
                    constants.FrameKind.GPIO_CLOCK_DIAGNOSTIC_REQUEST,
                    struct.pack("<IHH", 1_000_000, 4096, 0),
                    9,
                ),
                (
                    "gpio-capture-diagnostic-request.bin",
                    constants.FrameKind.GPIO_CAPTURE_DIAGNOSTIC_REQUEST,
                    b"",
                    10,
                ),
            )
            for name, kind, payload, request_id in request_specs:
                python_wire = encode_frame(
                    kind,
                    payload,
                    request_id=request_id,
                )
                self.assertEqual((FIXTURE_DIRECTORY / name).read_bytes(), python_wire)
                (python_commands / name).write_bytes(python_wire)

            interop_result = subprocess.run(
                [
                    str(executable),
                    str(FIXTURE_DIRECTORY),
                    str(python_commands),
                    str(cpp_responses),
                ],
                capture_output=True,
                check=False,
                text=True,
            )
            self.assertEqual(
                0,
                interop_result.returncode,
                interop_result.stdout + interop_result.stderr,
            )

            response_specs = (
                ("info-response.bin", constants.FrameKind.INFO_RESPONSE, 1),
                (
                    "configure-response.bin",
                    constants.FrameKind.CONFIGURE_RESPONSE,
                    2,
                ),
                ("start-response.bin", constants.FrameKind.START_RESPONSE, 3),
                (
                    "get-status-response.bin",
                    constants.FrameKind.GET_STATUS_RESPONSE,
                    4,
                ),
                ("stop-response.bin", constants.FrameKind.STOP_RESPONSE, 5),
                (
                    "reset-stats-response.bin",
                    constants.FrameKind.RESET_STATS_RESPONSE,
                    6,
                ),
                ("ping-response.bin", constants.FrameKind.PING_RESPONSE, 7),
                (
                    "checksum-benchmark-response.bin",
                    constants.FrameKind.CHECKSUM_BENCHMARK_RESPONSE,
                    8,
                ),
                (
                    "gpio-clock-diagnostic-response.bin",
                    constants.FrameKind.GPIO_CLOCK_DIAGNOSTIC_RESPONSE,
                    9,
                ),
                (
                    "gpio-capture-diagnostic-response.bin",
                    constants.FrameKind.GPIO_CAPTURE_DIAGNOSTIC_RESPONSE,
                    10,
                ),
                ("error-response.bin", constants.FrameKind.ERROR_RESPONSE, 11),
            )
            for name, kind, request_id in response_specs:
                cpp_wire = (cpp_responses / name).read_bytes()
                self.assertEqual((FIXTURE_DIRECTORY / name).read_bytes(), cpp_wire)
                frame = decode_frame(cpp_wire)
                response = decode_response(frame)
                self.assertEqual(kind, frame.header.kind)
                self.assertEqual(request_id, response.request_id)

    def test_production_protocol_has_no_heap_or_packed_wire_access(self) -> None:
        production_source = "\n".join(
            path.read_text(encoding="utf-8")
            for path in (PROTOCOL_HEADER, PROTOCOL_SOURCE)
        )
        forbidden = (
            "std::vector",
            "std::string",
            "malloc(",
            "calloc(",
            "realloc(",
            "free(",
            "operator new",
            "#include <Arduino",
            "__attribute__((packed))",
            "#pragma pack",
            "reinterpret_cast",
        )
        for token in forbidden:
            with self.subTest(token=token):
                self.assertNotIn(token, production_source)

        self.assertIn("std::array", production_source)
        self.assertIn("loadU32", production_source)
        self.assertIn("storeU32", production_source)
        self.assertIn("kMaxCommandFrameBytes", production_source)


if __name__ == "__main__":
    unittest.main()
