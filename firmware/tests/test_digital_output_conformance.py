"""Cross-language canonical program and expansion conformance tests."""

from __future__ import annotations

import shutil
import subprocess
import tempfile
import unittest
import zlib
from pathlib import Path

from thingdaq import (
    DigitalOutputProgram,
    DigitalOutputProgramError,
    DigitalOutputSegment,
)
from thingdaq._generated import protocol_v2_constants as v2
from thingdaq.protocol import FrameValidationError
from thingdaq.protocol_v2 import encode_v2_frame

REPOSITORY_ROOT = Path(__file__).resolve().parents[2]
FIRMWARE_SOURCE = REPOSITORY_ROOT / "firmware/src"
CPP_TEST = REPOSITORY_ROOT / "firmware/tests/digital_output_conformance_test.cpp"

ACCEPTED = {
    "single": ([(1, 0x00)], 1, 0xFF),
    "finite": ([(2, 0x01), (1, 0x80), (3, 0x55)], 2, 0xAA),
    "all_bits": ([(1, 0xFF), (2, 0x00), (1, 0xA5)], 3, 0x5A),
}


def _expanded_states(program: DigitalOutputProgram) -> list[int]:
    one_play = [
        segment.logical_state_mask
        for segment in program.segments
        for _ in range(segment.duration_samples)
    ]
    return one_play * program.repeat_count


class DigitalOutputConformanceTests(unittest.TestCase):
    @classmethod
    def setUpClass(cls) -> None:
        compiler = shutil.which("g++")
        if compiler is None:
            raise unittest.SkipTest("g++ is required for cross-language conformance")
        cls.temporary = tempfile.TemporaryDirectory(
            prefix="thingdaq-output-conformance-"
        )
        cls.executable = Path(cls.temporary.name) / "output-conformance"
        compiled = subprocess.run(
            [
                compiler,
                "-std=c++17",
                "-O3",
                "-Wall",
                "-Wextra",
                "-Werror",
                "-Wconversion",
                "-Wsign-conversion",
                "-pedantic",
                f"-I{FIRMWARE_SOURCE}",
                str(CPP_TEST),
                str(FIRMWARE_SOURCE / "digital_output_program.cpp"),
                str(FIRMWARE_SOURCE / "digital_output_engine.cpp"),
                "-o",
                str(cls.executable),
            ],
            capture_output=True,
            check=False,
            text=True,
        )
        if compiled.returncode:
            raise AssertionError(compiled.stdout + compiled.stderr)

    @classmethod
    def tearDownClass(cls) -> None:
        cls.temporary.cleanup()

    def test_python_and_cpp_checksum_and_expansion_are_identical(self) -> None:
        completed = subprocess.run(
            [str(self.executable)], capture_output=True, check=False, text=True
        )
        self.assertEqual(0, completed.returncode, completed.stderr)
        records = {
            line.split("|", 1)[0]: line for line in completed.stdout.splitlines()
        }
        for name, (segments, repeat_count, idle_state) in ACCEPTED.items():
            with self.subTest(program=name):
                program = DigitalOutputProgram.finite(
                    segments,
                    repeat_count,
                    idle_state_mask=idle_state,
                )
                fields = records[name].split("|")
                self.assertEqual("OK", fields[1])
                self.assertEqual(program.checksum, int(fields[2]))
                self.assertEqual(
                    _expanded_states(program),
                    [int(value) for value in fields[3].split(",")],
                )
                self.assertEqual(
                    zlib.adler32(program.canonical_bytes) & v2.UINT32_MAX,
                    program.checksum,
                )

    def test_simulator_matches_python_and_cpp_expansion_at_every_sample(self) -> None:
        from thingdaq import ThingDAQ

        for generation, (name, values) in enumerate(ACCEPTED.items(), start=201):
            segments, repeat_count, idle_state = values
            with (
                self.subTest(program=name),
                ThingDAQ.simulated(output_enabled=True) as daq,
            ):
                program = DigitalOutputProgram.finite(
                    segments,
                    repeat_count,
                    idle_state_mask=idle_state,
                )
                daq.upload_output(program, generation=generation)
                daq.output_arm()
                daq.configure(adc=True, gpio=True)
                run_id = daq.start()
                states = _expanded_states(program)
                daq.transport.device.advance_time(len(states) * v2.OUTPUT_PERIOD_TICKS)
                sampled = daq.transport.device.sample_output(
                    [index * v2.OUTPUT_PERIOD_TICKS for index in range(len(states))],
                    run_id=run_id,
                )
                self.assertEqual(states, [sample.state_mask for sample in sampled])

    def test_python_cpp_and_wire_reject_the_same_noncanonical_classes(self) -> None:
        completed = subprocess.run(
            [str(self.executable)], capture_output=True, check=False, text=True
        )
        records = {
            line.split("|", 1)[0]: line for line in completed.stdout.splitlines()
        }
        self.assertTrue(
            {
                "zero_duration",
                "high_state",
                "adjacent_duplicate",
                "empty",
                "capacity",
                "generation",
            }
            <= records.keys()
        )
        self.assertTrue(
            all("|REJECT|" in records[name] for name in records if name not in ACCEPTED)
        )

        invalid_builders = (
            lambda: DigitalOutputSegment(0, 1),
            lambda: DigitalOutputSegment(1, 0x100),
            lambda: DigitalOutputProgram(
                (DigitalOutputSegment(1, 0x55), DigitalOutputSegment(2, 0x55))
            ),
            lambda: DigitalOutputProgram(()),
            lambda: DigitalOutputProgram(
                tuple(
                    DigitalOutputSegment(1, index & 1)
                    for index in range(v2.OUTPUT_SEGMENT_CAPACITY + 1)
                )
            ),
        )
        for build in invalid_builders:
            with (
                self.subTest(builder=build),
                self.assertRaises(DigitalOutputProgramError),
            ):
                build()

        for payload in (
            (0).to_bytes(4, "little") + (1).to_bytes(4, "little"),
            (1).to_bytes(4, "little") + (0x100).to_bytes(4, "little"),
        ):
            with (
                self.subTest(payload=payload.hex()),
                self.assertRaises(FrameValidationError),
            ):
                encode_v2_frame(
                    v2.FrameKind.OUTPUT_APPEND_REQUEST,
                    payload,
                    run_id=1,
                    request_id=1,
                )


if __name__ == "__main__":
    unittest.main()
