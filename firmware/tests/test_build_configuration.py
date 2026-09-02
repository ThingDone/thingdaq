"""Tests for the pinned firmware build boundary and cooperative sketch."""

from __future__ import annotations

import importlib.util
import io
import subprocess
import sys
import tempfile
import unittest
from contextlib import redirect_stderr
from copy import deepcopy
from pathlib import Path
from unittest.mock import patch

REPOSITORY_ROOT = Path(__file__).resolve().parents[2]
BUILD_HELPER_PATH = REPOSITORY_ROOT / "firmware/tools/build_firmware.py"
SPEC = importlib.util.spec_from_file_location("build_firmware", BUILD_HELPER_PATH)
assert SPEC is not None and SPEC.loader is not None
build_firmware = importlib.util.module_from_spec(SPEC)
sys.modules[SPEC.name] = build_firmware
SPEC.loader.exec_module(build_firmware)


class BuildConfigurationTests(unittest.TestCase):
    @staticmethod
    def _profile_manifest(
        profile: build_firmware.CpuProfile,
    ) -> dict[str, object]:
        source_id = "6" * 64
        fingerprint = build_firmware.profile_build_fingerprint(source_id, profile)
        build_id = build_firmware.profile_build_id(source_id, fingerprint, profile)
        memory = {
            "flash": {"code_bytes": 1, "data_bytes": 2},
            "ram1": {"variables_bytes": 3},
            "ram2": {"variables_bytes": 4},
        }
        inspection = {
            "nm_path": "/tools/arm-none-eabi-nm",
            "packet_buffers": {"total_bytes": 819_200},
        }
        contract = build_firmware.stable_linker_resource_contract(memory, inspection)
        variant_hash = "a" * 64 if profile.name == "600" else "b" * 64
        return {
            "schema_version": build_firmware.MANIFEST_SCHEMA_VERSION,
            "target": {
                "cpu_profile": profile.name,
                "fqbn": profile.fqbn,
                "core_id": build_firmware.CORE_ID,
                "core_version": build_firmware.CORE_VERSION,
                "warnings": "all",
                "resolved_build_properties": profile.expected_build_properties,
                "compile_time_clocks": {"F_CPU": profile.cpu_hz},
                "expected_runtime_clocks": {
                    "F_CPU_ACTUAL": profile.cpu_hz,
                    "F_BUS_ACTUAL": profile.bus_hz,
                },
            },
            "arduino_cli": {"path": "/tools/arduino-cli", "identity": "1.4.1"},
            "compiler": {"path": "/tools/g++", "identity": "15.2.1"},
            "binary_inspection": inspection,
            "profile_parity": {
                "policy": "thingdaq-clock-profile-parity-v1",
                "stable_linker_resource_contract_sha256": (
                    build_firmware._canonical_sha256(contract)
                ),
                "identical_artifact_suffixes": [".eep", ".map"],
                "same_size_profile_variant_artifact_suffixes": [
                    ".bin",
                    ".elf",
                    ".hex",
                ],
            },
            "source": {
                "source_id": source_id,
                "build_fingerprint": fingerprint,
                "build_id": build_id,
                "cpu_profile": profile.name,
                "timestamp_epoch": 1,
                "timestamp_utc": "1970-01-01T00:00:01Z",
                "inputs": ["firmware/firmware.ino"],
                "git_commit": "c" * 40,
                "firmware_inputs_clean": True,
                "firmware_input_changes": [],
            },
            "memory_usage": memory,
            "command": [
                "/tools/arduino-cli",
                "compile",
                "--fqbn",
                profile.fqbn,
                "--clean",
                "--export-binaries",
                "--output-dir",
                str(profile.output_directory),
                str(build_firmware.SKETCH_DIRECTORY),
            ],
            "sketch_directory": "firmware",
            "output_directory": profile.output_directory.relative_to(
                build_firmware.REPOSITORY_ROOT
            ).as_posix(),
            "artifacts": [
                {"path": "firmware.ino.eep", "size_bytes": 1, "sha256": "e" * 64},
                {
                    "path": "firmware.ino.elf",
                    "size_bytes": 2,
                    "sha256": variant_hash,
                },
                {
                    "path": "firmware.ino.hex",
                    "size_bytes": 3,
                    "sha256": variant_hash,
                },
                {"path": "firmware.ino.map", "size_bytes": 4, "sha256": "d" * 64},
            ],
        }

    def test_helper_pins_both_complete_targets_and_isolated_exports(self) -> None:
        self.assertEqual("teensy:avr", build_firmware.CORE_ID)
        self.assertEqual("1.62.0", build_firmware.CORE_VERSION)
        self.assertEqual(11, build_firmware.MANIFEST_SCHEMA_VERSION)
        self.assertEqual(
            "teensy:avr:teensy40:usb=serial,speed=600,opt=o2std",
            build_firmware.FQBN,
        )
        self.assertIs(
            build_firmware.DEFAULT_CPU_PROFILE,
            build_firmware.CPU_PROFILES["600"],
        )
        self.assertEqual(
            build_firmware.OUTPUT_DIRECTORY,
            build_firmware.CPU_PROFILES["600"].output_directory,
        )

        source_id = "a" * 64
        output_directories: set[Path] = set()
        build_ids: set[str] = set()
        expected = {
            "600": (600_000_000, 150_000_000),
            "528": (528_000_000, 132_000_000),
        }
        for name, profile in build_firmware.CPU_PROFILES.items():
            with self.subTest(profile=name):
                fingerprint = build_firmware.profile_build_fingerprint(
                    source_id, profile
                )
                build_id = build_firmware.profile_build_id(
                    source_id, fingerprint, profile
                )
                identity = build_firmware.BuildIdentity(
                    source_id=source_id,
                    build_fingerprint=fingerprint,
                    build_id=build_id,
                    cpu_profile=name,
                    timestamp_epoch=1_700_000_000,
                    timestamp_utc="2023-11-14T22:13:20Z",
                )
                command = build_firmware.compile_command(
                    Path("/tools/arduino-cli"),
                    identity,
                    "-D__IMXRT1062__ -DTEENSYDUINO=160",
                    "-Wl,--gc-sections -T/imxrt1062.ld",
                    profile,
                )

                self.assertEqual(
                    f"teensy:avr:teensy40:usb=serial,speed={name},opt=o2std",
                    profile.fqbn,
                )
                self.assertEqual("/tools/arduino-cli", command[0])
                self.assertIn("--export-binaries", command)
                self.assertEqual(
                    str(profile.output_directory),
                    command[command.index("--output-dir") + 1],
                )
                self.assertEqual("compile", command[1])
                self.assertNotIn("upload", command)
                self.assertIn("--clean", command)
                self.assertEqual("all", command[command.index("--warnings") + 1])
                build_properties = [
                    command[index + 1]
                    for index, value in enumerate(command)
                    if value == "--build-property"
                ]
                definitions = next(
                    value
                    for value in build_properties
                    if value.startswith("build.flags.defs=")
                )
                self.assertIn(
                    "-DTHINGDAQ_SOURCE_ID_WORD0=0x" + "a" * 16 + "ULL",
                    definitions,
                )
                self.assertIn(
                    "-DTHINGDAQ_SOURCE_ID_WORD3=0x" + "a" * 16 + "ULL",
                    definitions,
                )
                self.assertIn(
                    "-DTHINGDAQ_BUILD_ID_WORD=0x"
                    f"{build_id.removeprefix('thingdaq-')}ULL",
                    definitions,
                )
                self.assertIn("-DTHINGDAQ_BUILD_EPOCH=1700000000ULL", definitions)
                self.assertIn("-DTHINGDAQ_BUILD_YEAR=2023U", definitions)
                self.assertIn("-DTHINGDAQ_BUILD_SECOND=20U", definitions)
                self.assertIn(f"-DTHINGDAQ_CPU_PROFILE_MHZ={name}U", definitions)
                self.assertIn(
                    f"-DTHINGDAQ_EXPECTED_CPU_HZ={expected[name][0]}U",
                    definitions,
                )
                self.assertIn(
                    f"-DTHINGDAQ_EXPECTED_BUS_HZ={expected[name][1]}U",
                    definitions,
                )
                self.assertIn("-DTHINGDAQ_OPTIMIZATION_O2STD=1", definitions)
                linker_flags = next(
                    value
                    for value in build_properties
                    if value.startswith("build.flags.ld=")
                )
                self.assertIn("-Wl,--gc-sections -T/imxrt1062.ld", linker_flags)
                self.assertIn(
                    f"-Wl,-Map={profile.output_directory / build_firmware.LINKER_MAP_NAME},--cref",
                    linker_flags,
                )
                output_directories.add(profile.output_directory)
                build_ids.add(identity.build_id)

        self.assertEqual(2, len(output_directories))
        self.assertEqual(2, len(build_ids))

    def test_memory_summary_is_recorded_exactly(self) -> None:
        summary = build_firmware.parse_memory_usage(
            """Memory Usage on Teensy 4.0:
  FLASH: code:22368, data:4040, headers:8404   free for files:1996804
   RAM1: variables:10080, code:20648, padding:12120   free for local variables:481440
   RAM2: variables:12416  free for malloc/new:511872
"""
        )

        self.assertEqual(22_368, summary["flash"]["code_bytes"])
        self.assertEqual(4_040, summary["flash"]["data_bytes"])
        self.assertEqual(10_080, summary["ram1"]["variables_bytes"])
        self.assertEqual(12_416, summary["ram2"]["variables_bytes"])
        build_firmware.validate_memory_headroom(summary)
        with self.assertRaisesRegex(build_firmware.BuildError, "missing ram2"):
            build_firmware.parse_memory_usage(
                "FLASH: code:1, data:2, headers:3 free for files:4\nRAM1: variables:5, code:6, padding:7 free for local variables:8"
            )

        summary["ram1"]["free_for_locals_bytes"] = 32_767
        with self.assertRaisesRegex(build_firmware.BuildError, "locals/stack"):
            build_firmware.validate_memory_headroom(summary)

    def test_checksum_table_provenance_requires_flash_residency(self) -> None:
        symbols = (
            "00000304 00000078 T "
            "thingdaq::checksum::adler32(unsigned char const*, unsigned int)\n"
            "0000037c 00000134 T "
            "thingdaq::checksum::crc32c(unsigned char const*, unsigned int)\n"
            "000004b0 00000134 T "
            "thingdaq::checksum::crc32IsoHdlc(unsigned char const*, unsigned int)\n"
            "000005e4 00000054 T "
            "thingdaq::checksum::compute(thingdaq::checksum::Algorithm, "
            "unsigned char const*, unsigned int, unsigned long&)\n"
            "60002000 00002000 u "
            "thingdaq::checksum::detail::kCrc32cTable\n"
            "60004000 00002000 u "
            "thingdaq::checksum::detail::kCrc32IsoHdlcTable"
        )
        resources = build_firmware.checksum_resource_usage(symbols)

        self.assertEqual(16_384, resources["total_table_flash_bytes"])
        self.assertEqual(736, resources["total_implementation_code_bytes"])
        self.assertEqual(0, resources["total_table_ram_bytes"])
        self.assertEqual(
            8_192,
            resources["algorithms"]["CRC32C"]["table_flash_bytes"],
        )
        with self.assertRaisesRegex(build_firmware.BuildError, "not resident"):
            build_firmware.checksum_resource_usage(
                symbols.replace("60002000", "20002000")
            )
        with self.assertRaisesRegex(build_firmware.BuildError, "missing"):
            build_firmware.checksum_resource_usage("\n".join(symbols.splitlines()[:-1]))

    def test_benchmark_buffer_provenance_requires_real_regions(self) -> None:
        symbols = (
            "200012c0 00001000 B "
            "thingdaq::benchmark::g_checksum_benchmark_dtcm_buffer\n"
            "20200000 00001000 B "
            "thingdaq::benchmark::g_checksum_benchmark_ocram_buffer"
        )
        resources = build_firmware.benchmark_buffer_usage(symbols)

        self.assertEqual(8_192, resources["working_ram_bytes"])
        self.assertEqual("0x200012c0", resources["regions"]["DTCM_PACKET"]["address"])
        self.assertEqual("0x20200000", resources["regions"]["OCRAM_DMA"]["address"])
        with self.assertRaisesRegex(build_firmware.BuildError, "outside"):
            build_firmware.benchmark_buffer_usage(
                symbols.replace("20200000 00001000", "20002000 00001000")
            )
        with self.assertRaisesRegex(build_firmware.BuildError, "missing"):
            build_firmware.benchmark_buffer_usage(symbols.splitlines()[0])

    def test_packet_buffer_provenance_requires_split_target_regions(self) -> None:
        symbols = (
            "200022c0 00069000 b (anonymous namespace)::packet_storage_primary\n"
            "20200000 0005f000 b (anonymous namespace)::packet_storage_reserve"
        )
        resources = build_firmware.packet_buffer_usage(symbols)

        self.assertEqual(200, resources["total_frames"])
        self.assertEqual(819_200, resources["total_bytes"])
        self.assertEqual("0x200022c0", resources["banks"]["DTCM_PRIMARY"]["address"])
        self.assertEqual("0x20200000", resources["banks"]["OCRAM_RESERVE"]["address"])
        with self.assertRaisesRegex(build_firmware.BuildError, "outside"):
            build_firmware.packet_buffer_usage(
                symbols.replace("20200000 0005f000", "2006c4c0 0005f000")
            )
        with self.assertRaisesRegex(build_firmware.BuildError, "missing"):
            build_firmware.packet_buffer_usage(symbols.splitlines()[0])

    def test_gpio_clock_diagnostic_buffer_requires_isolated_ocram_line(self) -> None:
        symbols = (
            "2025f000 00000020 B thingdaq::gpio_clock::g_gpio_clock_diagnostic_buffer"
        )
        resource = build_firmware.gpio_clock_diagnostic_buffer_usage(symbols)

        self.assertEqual(32, resource["bytes"])
        self.assertEqual("0x2025f000", resource["address"])
        with self.assertRaisesRegex(build_firmware.BuildError, "cache-line aligned"):
            build_firmware.gpio_clock_diagnostic_buffer_usage(
                symbols.replace("2025f000", "2025f004")
            )
        with self.assertRaisesRegex(build_firmware.BuildError, "outside"):
            build_firmware.gpio_clock_diagnostic_buffer_usage(
                symbols.replace("2025f000", "2005f000")
            )
        with self.assertRaisesRegex(build_firmware.BuildError, "missing"):
            build_firmware.gpio_clock_diagnostic_buffer_usage("")

    def test_raw_gpio_dma_buffers_require_exact_aligned_ocram_storage(self) -> None:
        symbols = (
            "2025f020 0000fd00 B "
            "thingdaq::gpio_capture::g_gpio_raw_dma_buffers\n"
            "2026ed20 00000020 B "
            "thingdaq::gpio_capture::g_gpio_raw_dma_overflow_sink\n"
            "2026ed40 000000a0 B "
            "thingdaq::gpio_capture::g_gpio_raw_dma_descriptors"
        )
        resources = build_firmware.gpio_raw_dma_buffer_usage(symbols)

        self.assertEqual(64_960, resources["total_bytes"])
        self.assertEqual("0x2025f020", resources["allocations"]["RING"]["address"])
        self.assertEqual(160, resources["allocations"]["DESCRIPTORS"]["bytes"])
        with self.assertRaisesRegex(build_firmware.BuildError, "cache-line aligned"):
            build_firmware.gpio_raw_dma_buffer_usage(
                symbols.replace("2026ed40 000000a0", "2026ed44 000000a0")
            )
        with self.assertRaisesRegex(build_firmware.BuildError, "outside"):
            build_firmware.gpio_raw_dma_buffer_usage(
                symbols.replace("2025f020 0000fd00", "2005f020 0000fd00")
            )
        with self.assertRaisesRegex(build_firmware.BuildError, "missing"):
            build_firmware.gpio_raw_dma_buffer_usage(symbols.splitlines()[0])

    def test_adc_dma_buffers_require_exact_aligned_ocram_storage(self) -> None:
        symbols = (
            "20277000 00007f00 B "
            "thingdaq::adc_capture::g_adc_dma_buffers\n"
            "2027ef00 00000020 B "
            "thingdaq::adc_capture::g_adc_dma_overflow_sink\n"
            "2027ef20 00000300 B "
            "thingdaq::adc_capture::g_adc_dma_descriptors"
        )
        resources = build_firmware.adc_dma_buffer_usage(symbols)

        self.assertEqual(33_312, resources["total_bytes"])
        self.assertEqual("0x20277000", resources["allocations"]["RING"]["address"])
        self.assertEqual(768, resources["allocations"]["DESCRIPTORS"]["bytes"])
        with self.assertRaisesRegex(build_firmware.BuildError, "cache-line aligned"):
            build_firmware.adc_dma_buffer_usage(
                symbols.replace("2027ef20 00000300", "2027ef24 00000300")
            )
        with self.assertRaisesRegex(build_firmware.BuildError, "outside"):
            build_firmware.adc_dma_buffer_usage(
                symbols.replace("20277000 00007f00", "20077000 00007f00")
            )
        with self.assertRaisesRegex(build_firmware.BuildError, "missing"):
            build_firmware.adc_dma_buffer_usage(symbols.splitlines()[0])

    def test_packed_gpio_ring_requires_exact_aligned_ocram_storage(self) -> None:
        symbols = "2026ede0 00003f80 B thingdaq::gpio_packer::g_gpio_packed_buffers"
        resource = build_firmware.gpio_packed_buffer_usage(symbols)

        self.assertEqual(16_256, resource["bytes"])
        self.assertEqual(4, resource["buffers"])
        self.assertEqual(4_064, resource["stride_bytes"])
        self.assertEqual("0x2026ede0", resource["address"])
        with self.assertRaisesRegex(build_firmware.BuildError, "cache-line aligned"):
            build_firmware.gpio_packed_buffer_usage(
                symbols.replace("2026ede0", "2026ede4")
            )
        with self.assertRaisesRegex(build_firmware.BuildError, "outside"):
            build_firmware.gpio_packed_buffer_usage(
                symbols.replace("2026ede0", "2006ede0")
            )
        with self.assertRaisesRegex(build_firmware.BuildError, "missing"):
            build_firmware.gpio_packed_buffer_usage("")

    def test_core_mismatch_stops_before_compile_or_upload(self) -> None:
        responses = [
            subprocess.CompletedProcess(
                args=[],
                returncode=0,
                stdout="arduino-cli Version: 1.4.1\n",
                stderr="",
            ),
            subprocess.CompletedProcess(
                args=[],
                returncode=0,
                stdout=(
                    '{"platforms": [{"id": "teensy:avr", '
                    '"installed_version": "1.61.0"}]}\n'
                ),
                stderr="",
            ),
        ]

        with (
            patch.object(
                build_firmware.shutil,
                "which",
                return_value="/tools/arduino-cli",
            ),
            patch.object(
                build_firmware,
                "run_command",
                side_effect=responses,
            ) as run_command,
            self.assertRaisesRegex(
                build_firmware.BuildError,
                "requires teensy:avr 1.62.0",
            ),
        ):
            build_firmware.build("arduino-cli")

        commands = [call.args[0] for call in run_command.call_args_list]
        self.assertEqual(2, len(commands))
        self.assertFalse(any("compile" in command for command in commands))
        self.assertFalse(any("upload" in command for command in commands))

    def test_core_inventory_must_report_the_pinned_version(self) -> None:
        inventory = {
            "platforms": [
                {"id": "arduino:avr", "installed_version": "1.8.6"},
                {"id": "teensy:avr", "installed_version": "1.62.0"},
            ]
        }

        self.assertEqual(
            "1.62.0",
            build_firmware.installed_core_version(inventory, "teensy:avr"),
        )
        self.assertIsNone(
            build_firmware.installed_core_version(inventory, "missing:core")
        )

    def test_source_fingerprint_is_path_aware_and_timestamp_independent(self) -> None:
        with tempfile.TemporaryDirectory(prefix="thingdaq-source-") as directory:
            root = Path(directory)
            first = root / "first.h"
            second = root / "second.h"
            first.write_bytes(b"same bytes\n")
            second.write_bytes(b"same bytes\n")

            first_hash = build_firmware.source_fingerprint([first], root=root)
            repeated_hash = build_firmware.source_fingerprint([first], root=root)
            second_hash = build_firmware.source_fingerprint([second], root=root)

        self.assertEqual(first_hash, repeated_hash)
        self.assertNotEqual(first_hash, second_hash)

    def test_source_date_epoch_is_validated_and_formatted_in_utc(self) -> None:
        epoch = build_firmware.resolve_build_epoch({"SOURCE_DATE_EPOCH": "0"})
        self.assertEqual(0, epoch)
        with self.assertRaisesRegex(build_firmware.BuildError, "decimal integer"):
            build_firmware.resolve_build_epoch({"SOURCE_DATE_EPOCH": "tomorrow"})

    @staticmethod
    def _resolved_properties(
        profile: build_firmware.CpuProfile,
    ) -> dict[str, str]:
        recipe = (
            "arm-none-eabi-g++ -c -O2 -D__IMXRT1062__ "
            "-DTEENSYDUINO=160 -DARDUINO_TEENSY40 "
            f"-DF_CPU={profile.cpu_hz} -DUSB_SERIAL"
        )
        return {
            **profile.expected_build_properties,
            "build.flags.defs": "-D__IMXRT1062__ -DTEENSYDUINO=160",
            "build.flags.cpp": "-std=gnu++17 -fno-exceptions",
            **{name: recipe for name in build_firmware.COMPILE_RECIPE_PROPERTIES},
        }

    def test_resolved_target_properties_fail_closed_for_each_profile(self) -> None:
        for name, profile in build_firmware.CPU_PROFILES.items():
            with self.subTest(profile=name):
                properties = self._resolved_properties(profile)
                build_firmware.validate_build_properties(properties, profile)

                properties["build.fcpu"] = "720000000"
                with self.assertRaisesRegex(build_firmware.BuildError, "build.fcpu"):
                    build_firmware.validate_build_properties(properties, profile)

                properties = self._resolved_properties(profile)
                properties["recipe.cpp.o.pattern"] = properties[
                    "recipe.cpp.o.pattern"
                ].replace(f"-DF_CPU={profile.cpu_hz}", "-DF_CPU=720000000")
                with self.assertRaisesRegex(build_firmware.BuildError, "F_CPU"):
                    build_firmware.validate_build_properties(properties, profile)

    def test_profile_selection_and_cli_default_fail_closed(self) -> None:
        self.assertEqual("600", build_firmware.parse_args([]).cpu_profile)
        self.assertIs(
            build_firmware.cpu_profile("528"), build_firmware.CPU_PROFILES["528"]
        )
        with self.assertRaisesRegex(build_firmware.BuildError, "unsupported CPU"):
            build_firmware.cpu_profile("720")
        with redirect_stderr(io.StringIO()), self.assertRaises(SystemExit):
            build_firmware.parse_args(["--cpu-profile", "720"])
        forged = build_firmware.CpuProfile(
            name="600",
            fqbn="teensy:avr:teensy40:usb=serial,speed=720,opt=o2std",
            cpu_hz=720_000_000,
            bus_hz=144_000_000,
            output_directory=Path("/tmp/forged"),
        )
        with self.assertRaisesRegex(build_firmware.BuildError, "registry"):
            build_firmware.profile_build_fingerprint("5" * 64, forged)

    def test_unsupported_build_profile_stops_before_tool_lookup(self) -> None:
        with (
            patch.object(build_firmware.shutil, "which") as which,
            self.assertRaisesRegex(build_firmware.BuildError, "unsupported CPU"),
        ):
            build_firmware.build("arduino-cli", "720")
        which.assert_not_called()

    def test_build_identity_is_source_stable_and_profile_specific(self) -> None:
        source_id = "5" * 64
        first = build_firmware.profile_build_fingerprint(
            source_id, build_firmware.CPU_PROFILES["600"]
        )
        repeated = build_firmware.profile_build_fingerprint(
            source_id, build_firmware.CPU_PROFILES["600"]
        )
        candidate = build_firmware.profile_build_fingerprint(
            source_id, build_firmware.CPU_PROFILES["528"]
        )

        self.assertEqual(first, repeated)
        self.assertNotEqual(first, candidate)
        self.assertEqual(64, len(first))
        self.assertEqual(64, len(candidate))
        production_id = build_firmware.profile_build_id(
            source_id, first, build_firmware.CPU_PROFILES["600"]
        )
        candidate_id = build_firmware.profile_build_id(
            source_id, candidate, build_firmware.CPU_PROFILES["528"]
        )
        self.assertEqual("thingdaq-5555555555555555", production_id)
        self.assertEqual(f"thingdaq-{candidate[:16]}", candidate_id)
        self.assertNotEqual(production_id, candidate_id)

    def test_profile_parity_allows_only_declared_metadata_and_artifacts(self) -> None:
        production = self._profile_manifest(build_firmware.CPU_PROFILES["600"])
        candidate = self._profile_manifest(build_firmware.CPU_PROFILES["528"])

        result = build_firmware.validate_profile_parity(production, candidate)

        self.assertEqual(["600", "528"], result["profiles"])
        self.assertEqual(4, result["artifact_count"])
        self.assertNotEqual(result["build_ids"]["600"], result["build_ids"]["528"])

        resource_drift = deepcopy(candidate)
        resource_drift["memory_usage"]["ram1"]["variables_bytes"] = 5  # type: ignore[index]
        resource_drift["profile_parity"][  # type: ignore[index]
            "stable_linker_resource_contract_sha256"
        ] = build_firmware._canonical_sha256(
            build_firmware.stable_linker_resource_contract(
                resource_drift["memory_usage"],  # type: ignore[arg-type]
                resource_drift["binary_inspection"],  # type: ignore[arg-type]
            )
        )
        with self.assertRaisesRegex(build_firmware.BuildError, "resource drift"):
            build_firmware.validate_profile_parity(production, resource_drift)

        map_drift = deepcopy(candidate)
        map_drift["artifacts"][-1]["sha256"] = "f" * 64  # type: ignore[index]
        with self.assertRaisesRegex(build_firmware.BuildError, r"\.map drift"):
            build_firmware.validate_profile_parity(production, map_drift)

        contradictory_clock = deepcopy(candidate)
        contradictory_clock["target"]["expected_runtime_clocks"][  # type: ignore[index]
            "F_BUS_ACTUAL"
        ] = 150_000_000
        with self.assertRaisesRegex(build_firmware.BuildError, "target mismatch"):
            build_firmware.validate_profile_manifest(contradictory_clock)

    def test_sketch_boot_is_independent_of_host_open_and_has_no_banner(self) -> None:
        sketch = (REPOSITORY_ROOT / "firmware/firmware.ino").read_text(encoding="utf-8")
        usb_adapter = (REPOSITORY_ROOT / "firmware/src/teensy_usb.cpp").read_text(
            encoding="utf-8"
        )
        usb_header = (REPOSITORY_ROOT / "firmware/src/teensy_usb.h").read_text(
            encoding="utf-8"
        )

        self.assertNotIn("kBuildId[] =", sketch)
        self.assertIn('include "src/firmware_runtime.h"', sketch)
        self.assertIn('include "src/teensy_usb.h"', sketch)
        self.assertIn("firmware_runtime.begin", sketch)
        clock_adapter = (REPOSITORY_ROOT / "firmware/src/teensy_clock.cpp").read_text(
            encoding="utf-8"
        )
        self.assertIn("runtimeProfileClocksValid", sketch)
        self.assertIn("runtimeClocksMatchProfile", clock_adapter)
        self.assertIn("F_CPU_ACTUAL", clock_adapter)
        self.assertIn("F_BUS_ACTUAL", clock_adapter)
        self.assertIn("hardwareSerialNumber()", sketch)
        self.assertIn("firmware_runtime.service()", sketch)
        self.assertNotIn("while (!Serial", sketch)
        self.assertNotIn("Serial.begin(115200)", sketch)
        self.assertNotIn("Serial.print", sketch)
        self.assertIn('include "firmware_identity.h"', usb_header)
        self.assertIn("usb_string_product_name =", usb_adapter)
        self.assertNotIn("usb_string_serial_number =", usb_adapter)


if __name__ == "__main__":
    unittest.main()
