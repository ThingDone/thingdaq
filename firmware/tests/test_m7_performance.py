"""C ABI correctness, integration and event publication under contention."""

from __future__ import annotations

import shutil
import subprocess
import tempfile
import unittest
from pathlib import Path

ROOT = Path(__file__).resolve().parents[2]
SRC = ROOT / "firmware/src"
EXPERIMENT = ROOT / "firmware/experiments/m7_performance"


class M7PerformanceTests(unittest.TestCase):
    def test_c_kernel_and_atomic_publication(self) -> None:
        cc, cpp = shutil.which("gcc"), shutil.which("g++")
        if cc is None or cpp is None:
            self.skipTest("GCC and G++ required")
        with tempfile.TemporaryDirectory() as temporary:
            out = Path(temporary)
            for opt in ("Os", "O1", "O2", "O3"):
                with self.subTest(optimization=opt):
                    common = [
                        f"-{opt}",
                        "-Wall",
                        "-Wextra",
                        "-Werror",
                        "-Wconversion",
                        "-Wsign-conversion",
                    ]
                    objects = []
                    for source in (SRC / "gpio_pack_c.c", EXPERIMENT / "event_word.c"):
                        obj = out / f"{source.stem}.o"
                        subprocess.run(
                            [
                                cc,
                                "-std=c11",
                                *common,
                                "-DTHINGDAQ_EXPERIMENT_C_PACKER=1",
                                "-c",
                                str(source),
                                "-o",
                                str(obj),
                            ],
                            check=True,
                            capture_output=True,
                        )
                        objects.append(str(obj))
                    executable = out / "test"
                    subprocess.run(
                        [
                            cpp,
                            "-std=c++17",
                            *common,
                            "-pthread",
                            f"-I{SRC}",
                            f"-I{EXPERIMENT}",
                            str(ROOT / "firmware/tests/m7_performance_test.cpp"),
                            *objects,
                            "-o",
                            str(executable),
                        ],
                        check=True,
                        capture_output=True,
                    )
                    subprocess.run([str(executable)], check=True, timeout=30)
            # Run the established join/packer/loss/layout suite through the C ABI.
            executable = out / "integration"
            sources = [
                "variable_rate_scheduler.cpp",
                "gpio_dual_bank_capture.cpp",
                "gpio_dual_bank_packer.cpp",
                "packet_buffer_pipeline.cpp",
                "protocol.cpp",
                "checksum.cpp",
            ]
            subprocess.run(
                [
                    cpp,
                    "-std=c++17",
                    "-O2",
                    "-Wall",
                    "-Wextra",
                    "-Werror",
                    "-DTHINGDAQ_EXPERIMENT_C_PACKER=1",
                    f"-I{SRC}",
                    str(ROOT / "firmware/tests/aux_input_portable_test.cpp"),
                    *(str(SRC / source) for source in sources),
                    str(out / "gpio_pack_c.o"),
                    "-o",
                    str(executable),
                ],
                check=True,
                capture_output=True,
            )
            subprocess.run([str(executable)], check=True, timeout=30)
