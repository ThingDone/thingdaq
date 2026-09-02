"""Host-compiled tests for bounded firmware RLE and adaptive ownership."""

from __future__ import annotations

import random
import shutil
import struct
import subprocess
import tempfile
import unittest
from pathlib import Path

from thingdaq import encode_rle_payload

REPOSITORY_ROOT = Path(__file__).resolve().parents[2]
FIRMWARE_SOURCE = REPOSITORY_ROOT / "firmware/src"
CPP_TEST = REPOSITORY_ROOT / "firmware/tests/rle_encoder_test.cpp"
FIXTURE_DIRECTORY = REPOSITORY_ROOT / "protocol/fixtures-v2"
FAKE_TEENSY_INCLUDE = REPOSITORY_ROOT / "firmware/tests/fakes/teensy40"
PRODUCTION_SOURCES = (
    FIRMWARE_SOURCE / "rle_encoder.h",
    FIRMWARE_SOURCE / "rle_encoder.cpp",
    FIRMWARE_SOURCE / "packet_buffer_pipeline.h",
    FIRMWARE_SOURCE / "packet_buffer_pipeline.cpp",
)
TARGET_ISR_SOURCES = {
    FIRMWARE_SOURCE / "adc_dma_capture_teensy.cpp": (
        "adcPairDmaIsr",
        "adcEtcErrorIsr",
    ),
    FIRMWARE_SOURCE / "gpio_raw_capture_teensy.cpp": (
        "faultFromIsr",
        "dmaMajorLoopIsr",
    ),
}


def _balanced_runs(item_count: int, run_count: int) -> tuple[int, ...]:
    base, longer = divmod(item_count, run_count)
    return tuple(base + (index < longer) for index in range(run_count))


def _oracle_cases() -> tuple[tuple[int, int, bytes, bytes], ...]:
    """Build deterministic cases with the independent Python codec."""

    cases: list[tuple[int, int, bytes, bytes]] = []
    shapes = ((1, 4_048, 1_349), (4, 1_012, 674))
    randomizer = random.Random(0x524C_4546)
    for item_bytes, item_count, selection_boundary in shapes:
        values = tuple(
            bytes((seed + offset * 37) & 0xFF for offset in range(item_bytes))
            for seed in (0x11, 0x52, 0xA7)
        )
        run_counts = (
            1,
            2,
            selection_boundary - 1,
            selection_boundary,
            selection_boundary + 1,
            item_count,
        )
        for run_count in run_counts:
            logical = b"".join(
                values[index % len(values)] * length
                for index, length in enumerate(_balanced_runs(item_count, run_count))
            )
            expected = encode_rle_payload(
                logical,
                item_size=item_bytes,
                max_items=item_count,
            )
            cases.append((item_bytes, item_count, logical, expected))

        for _case in range(32):
            remaining = item_count
            lengths: list[int] = []
            while remaining:
                length = min(remaining, randomizer.randint(1, 97))
                lengths.append(length)
                remaining -= length
            logical = b"".join(
                values[index % len(values)] * length
                for index, length in enumerate(lengths)
            )
            expected = encode_rle_payload(
                logical,
                item_size=item_bytes,
                max_items=item_count,
            )
            cases.append((item_bytes, item_count, logical, expected))
    return tuple(cases)


def _write_oracle(path: Path) -> int:
    cases = _oracle_cases()
    wire = bytearray(b"RLEO")
    wire.extend(struct.pack("<I", len(cases)))
    for item_bytes, max_items, logical, expected in cases:
        wire.extend(
            struct.pack(
                "<IIII",
                item_bytes,
                max_items,
                len(logical),
                len(expected),
            )
        )
        wire.extend(logical)
        wire.extend(expected)
    path.write_bytes(wire)
    return len(cases)


def _function_body(source: str, name: str) -> str:
    marker = f"void {name}("
    start = source.index(marker)
    opening = source.index("{", start)
    depth = 0
    for offset in range(opening, len(source)):
        if source[offset] == "{":
            depth += 1
        elif source[offset] == "}":
            depth -= 1
            if depth == 0:
                return source[opening : offset + 1]
    raise AssertionError(f"unterminated function body for {name}")


class RLEEncoderTests(unittest.TestCase):
    def test_portable_codec_and_adaptive_page_ownership(self) -> None:
        compiler = shutil.which("g++")
        if compiler is None:
            self.skipTest("g++ is required for portable firmware tests")

        with tempfile.TemporaryDirectory(prefix="thingdaq-rle-") as directory:
            executable = Path(directory) / "rle-encoder-test"
            oracle = Path(directory) / "python-rle-oracle.bin"
            oracle_cases = _write_oracle(oracle)
            self.assertEqual(76, oracle_cases)
            compiled = subprocess.run(
                [
                    compiler,
                    "-std=c++17",
                    "-O2",
                    "-Wall",
                    "-Wextra",
                    "-Werror",
                    "-Wconversion",
                    "-Wsign-conversion",
                    "-pedantic",
                    "-fno-exceptions",
                    "-fno-rtti",
                    "-DTHINGDAQ_TESTING=1",
                    f"-I{FIRMWARE_SOURCE}",
                    str(CPP_TEST),
                    str(FIRMWARE_SOURCE / "rle_encoder.cpp"),
                    str(FIRMWARE_SOURCE / "packet_buffer_pipeline.cpp"),
                    str(FIRMWARE_SOURCE / "protocol.cpp"),
                    str(FIRMWARE_SOURCE / "checksum.cpp"),
                    "-o",
                    str(executable),
                ],
                capture_output=True,
                check=False,
                text=True,
            )
            self.assertEqual(0, compiled.returncode, compiled.stdout + compiled.stderr)
            completed = subprocess.run(
                [str(executable), str(FIXTURE_DIRECTORY), str(oracle)],
                capture_output=True,
                check=False,
                text=True,
            )
            self.assertEqual(
                0, completed.returncode, completed.stdout + completed.stderr
            )

    def test_production_transform_is_allocation_and_isr_free(self) -> None:
        source = "\n".join(
            path.read_text(encoding="utf-8") for path in PRODUCTION_SOURCES
        )
        for token in (
            "std::vector",
            "std::deque",
            "std::string",
            "malloc(",
            "calloc(",
            "realloc(",
            "free(",
            "operator new",
            "new ",
            "delete ",
            "arm_dcache",
            "attachInterrupt",
            "IntervalTimer",
            "DMAChannel",
            "isr(",
        ):
            with self.subTest(token=token):
                self.assertNotIn(token, source)
        self.assertIn("BufferState::kTransforming", source)
        self.assertIn("takeTransformBuffer", source)
        self.assertIn("plan.encoded_frame_bytes <", source)

    def test_target_sections_and_interrupt_callers_keep_rle_cooperative(
        self,
    ) -> None:
        compiler = shutil.which("g++")
        readelf = shutil.which("readelf")
        nm = shutil.which("nm")
        if compiler is None or readelf is None or nm is None:
            self.skipTest("g++, readelf, and nm are required for target object checks")

        forbidden_isr_tokens = (
            "finishFill",
            "serviceReadyFrames",
            "computeChecksum",
            "finalizeRle",
            "rle::",
        )
        for path, functions in TARGET_ISR_SOURCES.items():
            source = path.read_text(encoding="utf-8")
            for function in functions:
                body = _function_body(source, function)
                for token in forbidden_isr_tokens:
                    with self.subTest(path=path.name, function=function, token=token):
                        self.assertNotIn(token, body)

        expected_sections = {
            "rle_encoder.cpp": {
                ".flashmem.rle.size",
                ".flashmem.rle.encode",
                ".flashmem.rle.validate",
                ".flashmem.rle.finalize_raw",
                ".flashmem.rle.finalize_rle",
            },
            "packet_buffer_pipeline.cpp": {
                ".flashmem.packet.finish_v2",
                ".flashmem.packet.take_transform",
                ".flashmem.packet.recycle_transform",
                ".flashmem.packet.snapshot",
            },
        }
        with tempfile.TemporaryDirectory(prefix="thingdaq-rle-target-") as directory:
            for source_name, sections in expected_sections.items():
                source_path = FIRMWARE_SOURCE / source_name
                object_path = Path(directory) / f"{source_path.stem}.o"
                compiled = subprocess.run(
                    [
                        compiler,
                        "-std=c++17",
                        "-O2",
                        "-Wall",
                        "-Wextra",
                        "-Werror",
                        "-Wconversion",
                        "-Wsign-conversion",
                        "-pedantic",
                        "-fno-exceptions",
                        "-fno-rtti",
                        "-ffunction-sections",
                        "-DARDUINO=10819",
                        "-DARDUINO_TEENSY40=1",
                        "-D__IMXRT1062__=1",
                        f"-I{FAKE_TEENSY_INCLUDE}",
                        f"-I{FIRMWARE_SOURCE}",
                        "-c",
                        str(source_path),
                        "-o",
                        str(object_path),
                    ],
                    capture_output=True,
                    check=False,
                    text=True,
                )
                self.assertEqual(
                    0,
                    compiled.returncode,
                    compiled.stdout + compiled.stderr,
                )
                section_table = subprocess.run(
                    [readelf, "--wide", "--sections", str(object_path)],
                    capture_output=True,
                    check=False,
                    text=True,
                )
                self.assertEqual(0, section_table.returncode, section_table.stderr)
                for section in sections:
                    with self.subTest(source=source_name, section=section):
                        self.assertIn(section, section_table.stdout)

                undefined = subprocess.run(
                    [nm, "--undefined-only", str(object_path)],
                    capture_output=True,
                    check=False,
                    text=True,
                )
                self.assertEqual(0, undefined.returncode, undefined.stderr)
                for token in (
                    "arm_dcache",
                    "attachInterrupt",
                    "DMAChannel",
                    "malloc",
                    "calloc",
                    "realloc",
                    "operator new",
                    "_Zn",
                ):
                    with self.subTest(source=source_name, undefined=token):
                        self.assertNotIn(token, undefined.stdout)

            resource_object = Path(directory) / "rle-resource-probe.o"
            resource_probe = subprocess.run(
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
                    "-DARDUINO=10819",
                    "-DARDUINO_TEENSY40=1",
                    "-D__IMXRT1062__=1",
                    f"-I{FAKE_TEENSY_INCLUDE}",
                    f"-I{FIRMWARE_SOURCE}",
                    "-x",
                    "c++",
                    "-c",
                    "-",
                    "-o",
                    str(resource_object),
                ],
                input="""
#include <cstddef>
#include "packet_buffer_pipeline.h"

namespace board = thingdaq::board;
namespace packet = thingdaq::packet;
namespace v1 = thingdaq::protocol_v1;
namespace v2 = thingdaq::protocol_v2;

static_assert(board::kPacketBufferPrimaryCount == 105U);
static_assert(board::kPacketBufferReserveCount == 95U);
static_assert(board::kPacketBufferCount == 200U);
static_assert(v1::kDataPayloadBytes == 4048U);
static_assert(v1::kDataFrameBytes == 4096U);
static_assert(v1::kDataFrameBytes == v2::kDataFrameBytes);
static_assert(sizeof(packet::PacketBufferPrimaryStorage) == 430080U);
static_assert(sizeof(packet::PacketBufferReserveStorage) == 389120U);
static_assert(sizeof(packet::PacketBufferPrimaryStorage) +
                  sizeof(packet::PacketBufferReserveStorage) ==
              819200U);
static_assert(sizeof(packet::PacketBufferPipeline) <=
              board::kPacketPipelineStateBudgetBytes);
""",
                capture_output=True,
                check=False,
                text=True,
            )
            self.assertEqual(
                0,
                resource_probe.returncode,
                resource_probe.stdout + resource_probe.stderr,
            )


if __name__ == "__main__":
    unittest.main()
