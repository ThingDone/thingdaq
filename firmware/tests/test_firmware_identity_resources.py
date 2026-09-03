"""Host-compiled checks for firmware identity, capabilities, and resources."""

from __future__ import annotations

import shutil
import subprocess
import tempfile
import unittest
from pathlib import Path

REPOSITORY_ROOT = Path(__file__).resolve().parents[2]
FIRMWARE_SOURCE = REPOSITORY_ROOT / "firmware/src"
CPP_TEST = REPOSITORY_ROOT / "firmware/tests/identity_resource_test.cpp"


class FirmwareIdentityResourceTests(unittest.TestCase):
    def test_identity_header_accepts_only_reviewed_clock_profiles(self) -> None:
        compiler = shutil.which("g++")
        if compiler is None:
            self.skipTest("g++ is required for portable firmware tests")

        for (
            profile_mhz,
            cpu_hz,
            bus_hz,
            adc_hz,
            phase_cycles,
            completion_cycles,
            tolerance_cycles,
            conversion_time_ps,
            conversion_margin_ps,
        ) in (
            (600, 600_000_000, 150_000_000, 37_500_000, 75, 300, 120, 866_667, 133_333),
            (528, 528_000_000, 132_000_000, 33_000_000, 66, 264, 106, 984_849, 15_151),
            (450, 450_000_000, 150_000_000, 37_500_000, 75, 225, 90, 866_667, 133_333),
        ):
            with self.subTest(profile_mhz=profile_mhz):
                source = f"""#include "firmware_identity.h"
static_assert(thingdaq::identity::kCpuProfileMhz == {profile_mhz}U);
static_assert(thingdaq::identity::kExpectedCpuHz == {cpu_hz}U);
static_assert(thingdaq::identity::kExpectedBusHz == {bus_hz}U);
static_assert(thingdaq::identity::kExpectedDwtHz == {cpu_hz}U);
static_assert(thingdaq::identity::kExpectedIpgHz == {bus_hz}U);
static_assert(thingdaq::identity::kExpectedAdcClockHz == {adc_hz}U);
static_assert(thingdaq::identity::kExpectedPitHz == 24000000U);
static_assert(thingdaq::identity::kExpectedGpioSampleRateHz == 4000000U);
static_assert(thingdaq::identity::kExpectedAdcPairRateHz == 1000000U);
static_assert(thingdaq::identity::kAdcNominalPhaseIpgCycles == {phase_cycles}U);
static_assert(thingdaq::identity::kAdcCompletionExpectedDwtCycles == {completion_cycles}U);
static_assert(thingdaq::identity::kAdcCompletionToleranceDwtCycles == {tolerance_cycles}U);
static_assert(thingdaq::identity::kAdcPrimaryConversionTimePicoseconds == {conversion_time_ps}U);
static_assert(thingdaq::identity::kAdcPrimaryConversionMarginPicoseconds == {conversion_margin_ps}U);
static_assert(thingdaq::identity::kGpioClockMaximumMeasurementCycles == {cpu_hz // 10}U);
static_assert(thingdaq::identity::divideCeil(0U, 7U) == 0U);
static_assert(thingdaq::identity::divideCeil(1U, 3U) == 1U);
static_assert(thingdaq::identity::divideCeil(3U, 3U) == 1U);
static_assert(thingdaq::identity::divideCeil(4U, 3U) == 2U);
static_assert(thingdaq::identity::dwtCyclesForNanoseconds(1U) == 1U);
static_assert(thingdaq::identity::dwtCyclesForNanoseconds(500U) == {completion_cycles}U);
static_assert(thingdaq::identity::dwtCyclesForNanoseconds(200U) == {tolerance_cycles}U);
static_assert(thingdaq::identity::dwtCyclesForMicroseconds(1U) == {cpu_hz // 1_000_000}U);
static_assert(thingdaq::identity::dwtCyclesForMicroseconds(10000U) == {cpu_hz // 100}U);
static_assert(static_cast<unsigned long long>(thingdaq::identity::kAdcNominalPhaseIpgCycles) *
                  thingdaq::identity::kExpectedDwtHz /
                  thingdaq::identity::kExpectedIpgHz ==
              thingdaq::identity::kAdcCompletionExpectedDwtCycles);
static_assert(static_cast<unsigned long long>(thingdaq::identity::kAdcNominalPhaseIpgCycles) *
                  1000000000ULL /
                  thingdaq::identity::kExpectedIpgHz == 500U);
static_assert(thingdaq::identity::runtimeClocksMatchProfile(
    {cpu_hz}U, {bus_hz}U));
static_assert(!thingdaq::identity::runtimeClocksMatchProfile(
    {cpu_hz - 1}U, {bus_hz}U));
static_assert(thingdaq::identity::runtimeAcquisitionClocksMatchProfile(
    {cpu_hz}U, {bus_hz}U, 24000000U, {adc_hz}U, 4U));
static_assert(!thingdaq::identity::runtimeAcquisitionClocksMatchProfile(
    {cpu_hz}U, {bus_hz}U, 24000000U, {adc_hz - 1}U, 4U));
static_assert(!thingdaq::identity::runtimeAcquisitionClocksMatchProfile(
    {cpu_hz}U, {bus_hz}U, 23999999U, {adc_hz}U, 4U));
static_assert(!thingdaq::identity::runtimeAcquisitionClocksMatchProfile(
    {cpu_hz}U, {bus_hz}U, 24000000U, {adc_hz}U, 3U));
"""
                result = subprocess.run(
                    [
                        compiler,
                        "-std=c++17",
                        "-fsyntax-only",
                        f"-I{FIRMWARE_SOURCE}",
                        f"-DTHINGDAQ_CPU_PROFILE_MHZ={profile_mhz}",
                        f"-DTHINGDAQ_EXPECTED_CPU_HZ={cpu_hz}",
                        f"-DTHINGDAQ_EXPECTED_BUS_HZ={bus_hz}",
                        "-x",
                        "c++",
                        "-",
                    ],
                    input=source,
                    capture_output=True,
                    check=False,
                    text=True,
                )
                self.assertEqual(0, result.returncode, result.stderr)

        invalid = subprocess.run(
            [
                compiler,
                "-std=c++17",
                "-fsyntax-only",
                f"-I{FIRMWARE_SOURCE}",
                "-DTHINGDAQ_CPU_PROFILE_MHZ=720",
                "-DTHINGDAQ_EXPECTED_CPU_HZ=720000000",
                "-DTHINGDAQ_EXPECTED_BUS_HZ=144000000",
                "-x",
                "c++",
                "-",
            ],
            input='#include "firmware_identity.h"\n',
            capture_output=True,
            check=False,
            text=True,
        )
        self.assertNotEqual(0, invalid.returncode)
        self.assertIn("explicit 600, 528, or 450 MHz", invalid.stderr)

        contradictory_profiles = (
            (600, 528_000_000, 132_000_000, "invalid ThingDAQ 600 MHz"),
            (528, 600_000_000, 150_000_000, "invalid ThingDAQ 528 MHz"),
            (450, 528_000_000, 132_000_000, "invalid ThingDAQ 450 MHz"),
        )
        for profile, cpu_hz, bus_hz, diagnostic in contradictory_profiles:
            with self.subTest(profile=profile, contradictory_cpu_hz=cpu_hz):
                contradictory = subprocess.run(
                    [
                        compiler,
                        "-std=c++17",
                        "-fsyntax-only",
                        f"-I{FIRMWARE_SOURCE}",
                        f"-DTHINGDAQ_CPU_PROFILE_MHZ={profile}",
                        f"-DTHINGDAQ_EXPECTED_CPU_HZ={cpu_hz}",
                        f"-DTHINGDAQ_EXPECTED_BUS_HZ={bus_hz}",
                        "-x",
                        "c++",
                        "-",
                    ],
                    input='#include "firmware_identity.h"\n',
                    capture_output=True,
                    check=False,
                    text=True,
                )
                self.assertNotEqual(0, contradictory.returncode)
                self.assertIn(diagnostic, contradictory.stderr)

    def test_board_registry_rejects_unsupported_arduino_targets(self) -> None:
        compiler = shutil.which("g++")
        if compiler is None:
            self.skipTest("g++ is required for portable firmware tests")

        unsupported_definitions = (
            ("-DARDUINO=10819",),
            ("-DARDUINO=10819", "-DARDUINO_TEENSY41", "-D__IMXRT1062__"),
            ("-DARDUINO=10819", "-DARDUINO_TEENSY40"),
        )
        for definitions in unsupported_definitions:
            with self.subTest(definitions=definitions):
                compile_result = subprocess.run(
                    [
                        compiler,
                        "-std=c++17",
                        "-fsyntax-only",
                        f"-I{FIRMWARE_SOURCE}",
                        *definitions,
                        "-x",
                        "c++",
                        "-",
                    ],
                    input='#include "board_config.h"\n',
                    capture_output=True,
                    check=False,
                    text=True,
                )
                self.assertNotEqual(0, compile_result.returncode)
                self.assertIn(
                    "require Teensy 4.0 / i.MX RT1062",
                    compile_result.stderr,
                )

    def test_portable_headers_compile_and_validate_the_production_registry(
        self,
    ) -> None:
        compiler = shutil.which("g++")
        if compiler is None:
            self.skipTest("g++ is required for portable firmware tests")

        with tempfile.TemporaryDirectory(prefix="thingdaq-cpp-") as directory:
            executable = Path(directory) / "identity-resource-test"
            compile_result = subprocess.run(
                [
                    compiler,
                    "-std=c++17",
                    "-Wall",
                    "-Wextra",
                    "-Werror",
                    "-pedantic",
                    f"-I{FIRMWARE_SOURCE}",
                    str(CPP_TEST),
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
                [str(executable)],
                capture_output=True,
                check=False,
                text=True,
            )
            self.assertEqual(
                0,
                run_result.returncode,
                run_result.stdout + run_result.stderr,
            )


if __name__ == "__main__":
    unittest.main()
