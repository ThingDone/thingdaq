#!/usr/bin/env python3
"""Verify the pinned Teensy toolchain and export profile-identified firmware."""

from __future__ import annotations

import argparse
import hashlib
import json
import os
import re
import shlex
import shutil
import subprocess
import sys
from collections.abc import Mapping, Sequence
from dataclasses import dataclass
from datetime import datetime, timezone
from pathlib import Path
from typing import Any

REPOSITORY_ROOT = Path(__file__).resolve().parents[2]
SKETCH_DIRECTORY = REPOSITORY_ROOT / "firmware"
CORE_ID = "teensy:avr"
CORE_VERSION = "1.62.0"
COMPILER_VERSION = "15.2.1"
DEFAULT_CPU_PROFILE_NAME = "600"
COMMON_BUILD_PROPERTIES = {
    "build.board": "TEENSY40",
    "build.flags.optimize": "-O2",
    "build.usbtype": "USB_SERIAL",
}
COMPILE_RECIPE_PROPERTIES = (
    "recipe.S.o.pattern",
    "recipe.c.o.pattern",
    "recipe.cpp.o.pattern",
)


@dataclass(frozen=True, slots=True)
class CpuProfile:
    """One complete, reviewed Teensy CPU-menu selection."""

    name: str
    fqbn: str
    cpu_hz: int
    bus_hz: int
    output_directory: Path

    @property
    def expected_build_properties(self) -> dict[str, str]:
        return {
            **COMMON_BUILD_PROPERTIES,
            "build.fcpu": str(self.cpu_hz),
        }


CPU_PROFILES = {
    "600": CpuProfile(
        name="600",
        fqbn="teensy:avr:teensy40:usb=serial,speed=600,opt=o2std",
        cpu_hz=600_000_000,
        bus_hz=150_000_000,
        output_directory=(
            SKETCH_DIRECTORY
            / "build"
            / "teensy.avr.teensy40.usb_serial.speed_600.opt_o2std"
        ),
    ),
    "528": CpuProfile(
        name="528",
        fqbn="teensy:avr:teensy40:usb=serial,speed=528,opt=o2std",
        cpu_hz=528_000_000,
        bus_hz=132_000_000,
        output_directory=(
            SKETCH_DIRECTORY
            / "build"
            / "teensy.avr.teensy40.usb_serial.speed_528.opt_o2std"
        ),
    ),
}
DEFAULT_CPU_PROFILE = CPU_PROFILES[DEFAULT_CPU_PROFILE_NAME]

# Compatibility aliases deliberately remain bound to the production profile.
# Existing no-argument release commands and baseline tooling must continue to
# resolve the accepted 600 MHz menu selection and output directory.
FQBN = DEFAULT_CPU_PROFILE.fqbn
EXPECTED_BUILD_PROPERTIES = DEFAULT_CPU_PROFILE.expected_build_properties
OUTPUT_DIRECTORY = DEFAULT_CPU_PROFILE.output_directory
MANIFEST_NAME = "build-manifest.json"
MANIFEST_SCHEMA_VERSION = 11
LINKER_MAP_NAME = "firmware.ino.map"
ARTIFACT_SUFFIXES = {".bin", ".eep", ".elf", ".hex", ".map"}
SOURCE_INPUTS = (
    SKETCH_DIRECTORY / "firmware.ino",
    SKETCH_DIRECTORY / "src",
    REPOSITORY_ROOT / "protocol/protocol-v1.json",
)
SOURCE_DATE_EPOCH_MAX = 253_402_300_799  # 9999-12-31T23:59:59Z
PROGRAM_FLASH_START = 0x60000000
PROGRAM_FLASH_END = 0x60200000
CHECKSUM_TABLE_SYMBOLS = {
    "CRC32C": "thingdaq::checksum::detail::kCrc32cTable",
    "CRC32_ISO_HDLC": "thingdaq::checksum::detail::kCrc32IsoHdlcTable",
}
CHECKSUM_TABLE_BYTES = 8 * 256 * 4
CHECKSUM_CODE_SYMBOLS = {
    "ADLER32": "thingdaq::checksum::adler32(unsigned char const*, unsigned int)",
    "CRC32C": "thingdaq::checksum::crc32c(unsigned char const*, unsigned int)",
    "CRC32_ISO_HDLC": (
        "thingdaq::checksum::crc32IsoHdlc(unsigned char const*, unsigned int)"
    ),
}
CHECKSUM_CODE_BYTES = {
    "ADLER32": 120,
    "CRC32C": 308,
    "CRC32_ISO_HDLC": 308,
}
CHECKSUM_DISPATCH_SYMBOL = (
    "thingdaq::checksum::compute(thingdaq::checksum::Algorithm, "
    "unsigned char const*, unsigned int, unsigned long&)"
)
BENCHMARK_BUFFER_SYMBOLS = {
    "DTCM_PACKET": (
        "thingdaq::benchmark::g_checksum_benchmark_dtcm_buffer",
        0x20000000,
        0x20200000,
    ),
    "OCRAM_DMA": (
        "thingdaq::benchmark::g_checksum_benchmark_ocram_buffer",
        0x20200000,
        0x20280000,
    ),
}
BENCHMARK_BUFFER_BYTES = 4096
BENCHMARK_BUFFER_ALIGNMENT = 32
PACKET_BUFFER_SYMBOLS = {
    "DTCM_PRIMARY": (
        "(anonymous namespace)::packet_storage_primary",
        105 * 4096,
        0x20000000,
        0x20200000,
    ),
    "OCRAM_RESERVE": (
        "(anonymous namespace)::packet_storage_reserve",
        95 * 4096,
        0x20200000,
        0x20280000,
    ),
}
PACKET_BUFFER_ALIGNMENT = 32
GPIO_CLOCK_DIAGNOSTIC_BUFFER_SYMBOL = (
    "thingdaq::gpio_clock::g_gpio_clock_diagnostic_buffer"
)
GPIO_CLOCK_DIAGNOSTIC_BUFFER_BYTES = 32
GPIO_CLOCK_DIAGNOSTIC_BUFFER_ALIGNMENT = 32
GPIO_RAW_DMA_BUFFER_SYMBOLS = {
    "RING": (
        "thingdaq::gpio_capture::g_gpio_raw_dma_buffers",
        4 * 4048 * 4,
    ),
    "OVERFLOW_SINK": (
        "thingdaq::gpio_capture::g_gpio_raw_dma_overflow_sink",
        32,
    ),
    "DESCRIPTORS": (
        "thingdaq::gpio_capture::g_gpio_raw_dma_descriptors",
        5 * 32,
    ),
}
GPIO_RAW_DMA_BUFFER_ALIGNMENT = 32
ADC_DMA_BUFFER_SYMBOLS = {
    "RING": (
        "thingdaq::adc_capture::g_adc_dma_buffers",
        8 * 4_064,
    ),
    "OVERFLOW_SINK": (
        "thingdaq::adc_capture::g_adc_dma_overflow_sink",
        32,
    ),
    "DESCRIPTORS": (
        "thingdaq::adc_capture::g_adc_dma_descriptors",
        2 * 12 * 32,
    ),
}
ADC_DMA_BUFFER_ALIGNMENT = 32
GPIO_PACKED_BUFFER_SYMBOL = "thingdaq::gpio_packer::g_gpio_packed_buffers"
GPIO_PACKED_BUFFER_BYTES = 4 * 4064
GPIO_PACKED_BUFFER_ALIGNMENT = 32
OCRAM_START = 0x20200000
OCRAM_END = 0x20280000
MINIMUM_RAM1_FREE_FOR_LOCALS_BYTES = 32 * 1024


class BuildError(RuntimeError):
    """A reproducibility check or firmware build failed."""


def cpu_profile(name: str) -> CpuProfile:
    """Resolve exactly one reviewed profile and reject every other speed."""

    try:
        return CPU_PROFILES[name]
    except KeyError as error:
        supported = ", ".join(CPU_PROFILES)
        raise BuildError(
            f"unsupported CPU profile {name!r}; expected one of: {supported}"
        ) from error


def _validated_profile(profile: CpuProfile) -> CpuProfile:
    """Reject a forged profile object even in programmatic helper use."""

    registered = cpu_profile(profile.name)
    if profile != registered:
        raise BuildError(f"CPU profile {profile.name!r} does not match its registry")
    return registered


@dataclass(frozen=True, slots=True)
class BuildIdentity:
    """Deterministic source, target, and timestamp firmware metadata."""

    source_id: str
    build_fingerprint: str
    build_id: str
    cpu_profile: str
    timestamp_epoch: int
    timestamp_utc: str


def run_command(
    command: Sequence[str],
    *,
    environment: Mapping[str, str] | None = None,
) -> subprocess.CompletedProcess[str]:
    """Run one tool command and retain output for diagnostics and provenance."""

    try:
        result = subprocess.run(
            command,
            capture_output=True,
            check=False,
            env=dict(environment) if environment is not None else None,
            text=True,
        )
    except OSError as error:
        raise BuildError(f"could not run {command[0]!r}: {error}") from error

    if result.returncode != 0:
        detail = "\n".join(
            part.strip() for part in (result.stdout, result.stderr) if part.strip()
        )
        raise BuildError(
            f"command failed with exit code {result.returncode}: "
            f"{shlex.join(command)}\n{detail}"
        )
    return result


def installed_core_version(core_inventory: Any, core_id: str) -> str | None:
    """Extract an installed core version from Arduino CLI's JSON inventory."""

    if not isinstance(core_inventory, dict):
        return None
    platforms = core_inventory.get("platforms", [])
    if not isinstance(platforms, list):
        return None
    for platform in platforms:
        if isinstance(platform, dict) and platform.get("id") == core_id:
            version = platform.get("installed_version")
            return version if isinstance(version, str) else None
    return None


def parse_build_properties(output: str) -> dict[str, str]:
    """Parse the resolved key=value properties printed by Arduino CLI."""

    properties: dict[str, str] = {}
    for line in output.splitlines():
        key, separator, value = line.partition("=")
        if separator:
            properties[key] = value
    return properties


def _recipe_definitions(recipe: str) -> set[str]:
    """Return concrete ``-D`` tokens from one resolved compiler recipe."""

    try:
        tokens = shlex.split(recipe)
    except ValueError as error:
        raise BuildError(
            f"could not parse resolved compiler recipe: {error}"
        ) from error
    return {token for token in tokens if token.startswith("-D")}


def validate_build_properties(
    properties: Mapping[str, str],
    profile: CpuProfile = DEFAULT_CPU_PROFILE,
) -> None:
    """Reject a resolved menu or compile recipe outside ``profile``."""

    profile = _validated_profile(profile)

    mismatches = [
        f"{name}={properties.get(name)!r}, expected {expected!r}"
        for name, expected in profile.expected_build_properties.items()
        if properties.get(name) != expected
    ]
    definitions = set(properties.get("build.flags.defs", "").split())
    for required in ("-D__IMXRT1062__", "-DTEENSYDUINO=160"):
        if required not in definitions:
            mismatches.append(f"build.flags.defs is missing {required}")
    if "-std=gnu++17" not in properties.get("build.flags.cpp", "").split():
        mismatches.append("build.flags.cpp is missing -std=gnu++17")
    required_recipe_definitions = {
        "-DARDUINO_TEENSY40",
        f"-DF_CPU={profile.cpu_hz}",
        "-DUSB_SERIAL",
        "-D__IMXRT1062__",
        "-DTEENSYDUINO=160",
    }
    for name in COMPILE_RECIPE_PROPERTIES:
        recipe = properties.get(name, "")
        recipe_definitions = _recipe_definitions(recipe)
        missing = required_recipe_definitions - recipe_definitions
        if missing:
            mismatches.append(f"{name} is missing " + ", ".join(sorted(missing)))
        if "-O2" not in shlex.split(recipe):
            mismatches.append(f"{name} is missing -O2")
    if mismatches:
        raise BuildError(
            "resolved build properties are incompatible: " + "; ".join(mismatches)
        )


def collect_source_files(inputs: Sequence[Path] = SOURCE_INPUTS) -> tuple[Path, ...]:
    """Return every non-hidden firmware input in stable path order."""

    files: set[Path] = set()
    for source_input in inputs:
        if source_input.is_file():
            files.add(source_input.resolve())
            continue
        if source_input.is_dir():
            files.update(
                path.resolve()
                for path in source_input.rglob("*")
                if path.is_file() and not path.name.startswith(".")
            )
            continue
        raise BuildError(f"firmware source input does not exist: {source_input}")
    if not files:
        raise BuildError("firmware source input set is empty")
    return tuple(sorted(files, key=lambda path: path.as_posix()))


def source_fingerprint(
    source_files: Sequence[Path],
    *,
    root: Path = REPOSITORY_ROOT,
) -> str:
    """Hash source paths and bytes without timestamps or Git state."""

    digest = hashlib.sha256()
    resolved_root = root.resolve()
    for source_file in sorted(
        (path.resolve() for path in source_files), key=lambda path: path.as_posix()
    ):
        try:
            relative = source_file.relative_to(resolved_root).as_posix().encode("utf-8")
        except ValueError as error:
            raise BuildError(
                f"source input is outside the repository: {source_file}"
            ) from error
        content = source_file.read_bytes()
        digest.update(len(relative).to_bytes(4, "little"))
        digest.update(relative)
        digest.update(len(content).to_bytes(8, "little"))
        digest.update(content)
    return digest.hexdigest()


def resolve_build_epoch(environment: Mapping[str, str] | None = None) -> int:
    """Resolve SOURCE_DATE_EPOCH or the latest source-affecting commit time."""

    selected_environment = os.environ if environment is None else environment
    requested_epoch = selected_environment.get("SOURCE_DATE_EPOCH")
    if requested_epoch is not None:
        try:
            epoch = int(requested_epoch, 10)
        except ValueError as error:
            raise BuildError("SOURCE_DATE_EPOCH must be a decimal integer") from error
    else:
        relative_inputs = [
            str(path.relative_to(REPOSITORY_ROOT)) for path in SOURCE_INPUTS
        ]
        result = run_command(
            [
                "git",
                "-C",
                str(REPOSITORY_ROOT),
                "log",
                "-1",
                "--format=%ct",
                "--",
                *relative_inputs,
            ]
        )
        try:
            epoch = int(result.stdout.strip(), 10)
        except ValueError as error:
            raise BuildError("Git did not report a source commit timestamp") from error
    if not 0 <= epoch <= SOURCE_DATE_EPOCH_MAX:
        raise BuildError("SOURCE_DATE_EPOCH is outside the supported UTC range")
    return epoch


def profile_build_fingerprint(source_id: str, profile: CpuProfile) -> str:
    """Hash the source and immutable target contract into one build identity."""

    profile = _validated_profile(profile)
    if len(source_id) != 64 or any(
        character not in "0123456789abcdef" for character in source_id
    ):
        raise BuildError("source ID must be a lowercase SHA-256")
    contract = {
        "schema": "thingdaq-profile-build-v1",
        "source_id": source_id,
        "cpu_profile": profile.name,
        "fqbn": profile.fqbn,
        "core_id": CORE_ID,
        "core_version": CORE_VERSION,
        "compiler_version": COMPILER_VERSION,
        "resolved_build_properties": profile.expected_build_properties,
        "expected_runtime_clocks": {
            "F_CPU_ACTUAL": profile.cpu_hz,
            "F_BUS_ACTUAL": profile.bus_hz,
        },
    }
    encoded = json.dumps(contract, separators=(",", ":"), sort_keys=True).encode(
        "utf-8"
    )
    return hashlib.sha256(encoded).hexdigest()


def profile_build_id(
    source_id: str, build_fingerprint: str, profile: CpuProfile
) -> str:
    """Return the bounded wire ID without changing production ID semantics."""

    profile = _validated_profile(profile)
    expected_fingerprint = profile_build_fingerprint(source_id, profile)
    if build_fingerprint != expected_fingerprint:
        raise BuildError("build fingerprint must derive from source and CPU profile")
    identity_digest = source_id if profile is DEFAULT_CPU_PROFILE else build_fingerprint
    return f"thingdaq-{identity_digest[:16]}"


def build_identity(
    environment: Mapping[str, str] | None = None,
    profile: CpuProfile = DEFAULT_CPU_PROFILE,
) -> BuildIdentity:
    """Create deterministic metadata for the current source and CPU profile."""

    profile = _validated_profile(profile)
    source_id = source_fingerprint(collect_source_files())
    build_fingerprint = profile_build_fingerprint(source_id, profile)
    epoch = resolve_build_epoch(environment)
    timestamp = datetime.fromtimestamp(epoch, tz=timezone.utc).strftime(
        "%Y-%m-%dT%H:%M:%SZ"
    )
    return BuildIdentity(
        source_id=source_id,
        build_fingerprint=build_fingerprint,
        build_id=profile_build_id(source_id, build_fingerprint, profile),
        cpu_profile=profile.name,
        timestamp_epoch=epoch,
        timestamp_utc=timestamp,
    )


def identity_definitions(
    base_definitions: str,
    identity: BuildIdentity,
    profile: CpuProfile = DEFAULT_CPU_PROFILE,
) -> str:
    """Append numeric deterministic identity and profile macros."""

    profile = _validated_profile(profile)
    if len(identity.source_id) != 64 or any(
        character not in "0123456789abcdef" for character in identity.source_id
    ):
        raise BuildError("source ID must be a lowercase SHA-256")
    expected_fingerprint = profile_build_fingerprint(identity.source_id, profile)
    if identity.build_fingerprint != expected_fingerprint:
        raise BuildError("build fingerprint must derive from source and CPU profile")
    if identity.cpu_profile != profile.name:
        raise BuildError("build identity CPU profile does not match selected profile")
    if not identity.build_id.isascii() or not 0 < len(identity.build_id) < 32:
        raise BuildError("build ID must fit the protocol's 31-byte ASCII limit")
    timestamp = datetime.fromtimestamp(identity.timestamp_epoch, tz=timezone.utc)
    expected_build_id = profile_build_id(
        identity.source_id, identity.build_fingerprint, profile
    )
    expected_timestamp = timestamp.strftime("%Y-%m-%dT%H:%M:%SZ")
    if identity.build_id != expected_build_id:
        raise BuildError("build ID does not match the selected profile identity")
    if identity.timestamp_utc != expected_timestamp:
        raise BuildError("UTC build timestamp must agree with its epoch")
    source_words = tuple(
        identity.source_id[offset : offset + 16] for offset in range(0, 64, 16)
    )
    identity_macros = (
        *(
            f"-DTHINGDAQ_SOURCE_ID_WORD{index}=0x{word}ULL"
            for index, word in enumerate(source_words)
        ),
        f"-DTHINGDAQ_BUILD_ID_WORD=0x{identity.build_id.removeprefix('thingdaq-')}ULL",
        f"-DTHINGDAQ_BUILD_EPOCH={identity.timestamp_epoch}ULL",
        f"-DTHINGDAQ_BUILD_YEAR={timestamp.year}U",
        f"-DTHINGDAQ_BUILD_MONTH={timestamp.month}U",
        f"-DTHINGDAQ_BUILD_DAY={timestamp.day}U",
        f"-DTHINGDAQ_BUILD_HOUR={timestamp.hour}U",
        f"-DTHINGDAQ_BUILD_MINUTE={timestamp.minute}U",
        f"-DTHINGDAQ_BUILD_SECOND={timestamp.second}U",
        f"-DTHINGDAQ_CPU_PROFILE_MHZ={profile.name}U",
        f"-DTHINGDAQ_EXPECTED_CPU_HZ={profile.cpu_hz}U",
        f"-DTHINGDAQ_EXPECTED_BUS_HZ={profile.bus_hz}U",
        "-DTHINGDAQ_OPTIMIZATION_O2STD=1",
    )
    return " ".join((base_definitions, *identity_macros))


def resolve_compiler(properties: dict[str, str]) -> Path:
    """Resolve the C++ compiler executable selected by the pinned core."""

    compiler_name = properties.get("compiler.cpp.cmd")
    compiler_directory = properties.get("compiler.path")
    if compiler_name and compiler_directory:
        compiler = Path(compiler_name)
        if not compiler.is_absolute():
            compiler = Path(compiler_directory) / compiler
        if compiler.is_file():
            return compiler.resolve()

    recipe = properties.get("recipe.cpp.o.pattern", "")
    if recipe:
        recipe_compiler = Path(shlex.split(recipe)[0])
        if recipe_compiler.is_file():
            return recipe_compiler.resolve()

    raise BuildError("Arduino CLI did not resolve an executable C++ compiler")


def resolve_nm(compiler: Path) -> Path:
    """Resolve the symbol inspector adjacent to the pinned cross-compiler."""

    nm = compiler.with_name("arm-none-eabi-nm")
    if not nm.is_file():
        raise BuildError(f"cross-toolchain symbol inspector does not exist: {nm}")
    return nm.resolve()


def compile_command(
    arduino_cli: Path,
    identity: BuildIdentity,
    base_definitions: str,
    base_linker_flags: str,
    profile: CpuProfile = DEFAULT_CPU_PROFILE,
) -> list[str]:
    """Return the immutable command used for every supported firmware build."""

    profile = _validated_profile(profile)
    linker_map = profile.output_directory / LINKER_MAP_NAME
    return [
        str(arduino_cli),
        "compile",
        "--fqbn",
        profile.fqbn,
        "--clean",
        "--warnings",
        "all",
        "--build-property",
        (
            "build.flags.defs="
            f"{identity_definitions(base_definitions, identity, profile)}"
        ),
        "--build-property",
        f"build.flags.ld={base_linker_flags} -Wl,-Map={linker_map},--cref",
        "--export-binaries",
        "--output-dir",
        str(profile.output_directory),
        str(SKETCH_DIRECTORY),
    ]


def parse_memory_usage(output: str) -> dict[str, dict[str, int]]:
    """Parse the Teensy size summary into stable byte counts."""

    patterns = {
        "flash": re.compile(
            r"FLASH:\s+code:(\d+),\s+data:(\d+),\s+headers:(\d+)"
            r"\s+free for files:(\d+)"
        ),
        "ram1": re.compile(
            r"RAM1:\s+variables:(\d+),\s+code:(\d+),\s+padding:(\d+)"
            r"\s+free for local variables:(\d+)"
        ),
        "ram2": re.compile(r"RAM2:\s+variables:(\d+)\s+free for malloc/new:(\d+)"),
    }
    matches = {name: pattern.search(output) for name, pattern in patterns.items()}
    missing = [name for name, match in matches.items() if match is None]
    if missing:
        raise BuildError(
            "Teensy memory summary is missing " + ", ".join(sorted(missing))
        )

    flash_match = matches["flash"]
    ram1_match = matches["ram1"]
    ram2_match = matches["ram2"]
    assert flash_match is not None and ram1_match is not None and ram2_match is not None
    return {
        "flash": {
            "code_bytes": int(flash_match.group(1)),
            "data_bytes": int(flash_match.group(2)),
            "headers_bytes": int(flash_match.group(3)),
            "free_for_files_bytes": int(flash_match.group(4)),
        },
        "ram1": {
            "variables_bytes": int(ram1_match.group(1)),
            "code_bytes": int(ram1_match.group(2)),
            "padding_bytes": int(ram1_match.group(3)),
            "free_for_locals_bytes": int(ram1_match.group(4)),
        },
        "ram2": {
            "variables_bytes": int(ram2_match.group(1)),
            "free_for_heap_bytes": int(ram2_match.group(2)),
        },
    }


def validate_memory_headroom(memory_usage: dict[str, dict[str, int]]) -> None:
    """Reject a linked image that leaves too little DTCM for locals/stack."""

    available = memory_usage["ram1"]["free_for_locals_bytes"]
    if available < MINIMUM_RAM1_FREE_FOR_LOCALS_BYTES:
        raise BuildError(
            "RAM1 leaves only "
            f"{available} bytes for locals/stack; requires at least "
            f"{MINIMUM_RAM1_FREE_FOR_LOCALS_BYTES}"
        )


def parse_nm_symbols(output: str) -> dict[str, tuple[int, int, str]]:
    """Parse ``nm --print-size`` output keyed by demangled symbol name."""

    symbols: dict[str, tuple[int, int, str]] = {}
    for line in output.splitlines():
        fields = line.split(maxsplit=3)
        if len(fields) != 4:
            continue
        address_text, size_text, symbol_type, name = fields
        try:
            address = int(address_text, 16)
            size = int(size_text, 16)
        except ValueError:
            continue
        symbols[name] = (address, size, symbol_type)
    return symbols


def checksum_resource_usage(nm_output: str) -> dict[str, Any]:
    """Prove negotiated lookup tables consume flash but no runtime RAM."""

    symbols = parse_nm_symbols(nm_output)
    algorithms: dict[str, dict[str, Any]] = {
        "ADLER32": {
            "implementation": "arithmetic (no lookup table)",
            "table_flash_bytes": 0,
            "table_ram_bytes": 0,
        }
    }
    for algorithm, symbol in CHECKSUM_CODE_SYMBOLS.items():
        record = symbols.get(symbol)
        if record is None:
            raise BuildError(
                f"firmware ELF is missing checksum implementation symbol {symbol}"
            )
        address, size, symbol_type = record
        expected_size = CHECKSUM_CODE_BYTES[algorithm]
        if size != expected_size:
            raise BuildError(
                f"{symbol} occupies {size} code bytes, expected {expected_size}"
            )
        if symbol_type.upper() != "T":
            raise BuildError(f"{symbol} is not an executable text symbol")
        algorithms.setdefault(algorithm, {})
        algorithms[algorithm].update(
            {
                "code_symbol": symbol,
                "code_symbol_type": symbol_type,
                "code_address": f"0x{address:08x}",
                "implementation_code_bytes": size,
            }
        )
    for algorithm, symbol in CHECKSUM_TABLE_SYMBOLS.items():
        record = symbols.get(symbol)
        if record is None:
            raise BuildError(f"firmware ELF is missing checksum table symbol {symbol}")
        address, size, symbol_type = record
        if size != CHECKSUM_TABLE_BYTES:
            raise BuildError(
                f"{symbol} occupies {size} bytes, expected {CHECKSUM_TABLE_BYTES}"
            )
        if not PROGRAM_FLASH_START <= address < PROGRAM_FLASH_END:
            raise BuildError(
                f"{symbol} is not resident in program flash: 0x{address:08x}"
            )
        algorithms[algorithm] = {
            **algorithms[algorithm],
            "implementation": "eight-slice, 8 x 256-entry uint32 lookup table",
            "symbol": symbol,
            "symbol_type": symbol_type,
            "address": f"0x{address:08x}",
            "table_flash_bytes": size,
            "table_ram_bytes": 0,
        }
    dispatch = symbols.get(CHECKSUM_DISPATCH_SYMBOL)
    if dispatch is None:
        raise BuildError(
            "firmware ELF is missing shared checksum dispatch symbol "
            f"{CHECKSUM_DISPATCH_SYMBOL}"
        )
    dispatch_address, dispatch_size, dispatch_type = dispatch
    if dispatch_type.upper() != "T":
        raise BuildError("shared checksum dispatch is not executable text")
    return {
        "placement": "memory-mapped program flash (.progmem.checksum.*)",
        "algorithms": algorithms,
        "shared_dispatch": {
            "symbol": CHECKSUM_DISPATCH_SYMBOL,
            "symbol_type": dispatch_type,
            "address": f"0x{dispatch_address:08x}",
            "code_bytes": dispatch_size,
        },
        "total_implementation_code_bytes": sum(
            item["implementation_code_bytes"] for item in algorithms.values()
        ),
        "total_table_flash_bytes": sum(
            item["table_flash_bytes"] for item in algorithms.values()
        ),
        "total_table_ram_bytes": sum(
            item["table_ram_bytes"] for item in algorithms.values()
        ),
    }


def benchmark_buffer_usage(nm_output: str) -> dict[str, Any]:
    """Verify benchmark working buffers occupy their claimed memory regions."""

    symbols = parse_nm_symbols(nm_output)
    regions: dict[str, dict[str, Any]] = {}
    for region, (symbol, region_start, region_end) in BENCHMARK_BUFFER_SYMBOLS.items():
        record = symbols.get(symbol)
        if record is None:
            raise BuildError(f"firmware ELF is missing benchmark buffer {symbol}")
        address, size, symbol_type = record
        if size != BENCHMARK_BUFFER_BYTES:
            raise BuildError(
                f"{symbol} occupies {size} bytes, expected {BENCHMARK_BUFFER_BYTES}"
            )
        if address % BENCHMARK_BUFFER_ALIGNMENT != 0:
            raise BuildError(f"{symbol} is not cache-line aligned")
        if not region_start <= address or address + size > region_end:
            raise BuildError(
                f"{symbol} is outside its claimed {region} range: 0x{address:08x}"
            )
        if symbol_type.upper() != "B":
            raise BuildError(f"{symbol} is not zero-initialized writable storage")
        regions[region] = {
            "symbol": symbol,
            "symbol_type": symbol_type,
            "address": f"0x{address:08x}",
            "bytes": size,
            "alignment_bytes": BENCHMARK_BUFFER_ALIGNMENT,
            "range_start": f"0x{region_start:08x}",
            "range_end_exclusive": f"0x{region_end:08x}",
        }
    return {
        "working_ram_bytes": sum(item["bytes"] for item in regions.values()),
        "regions": regions,
    }


def packet_buffer_usage(nm_output: str) -> dict[str, Any]:
    """Verify both fixed packet banks occupy their claimed memory regions."""

    symbols = parse_nm_symbols(nm_output)
    banks: dict[str, dict[str, Any]] = {}
    for bank, (
        symbol,
        expected_size,
        region_start,
        region_end,
    ) in PACKET_BUFFER_SYMBOLS.items():
        record = symbols.get(symbol)
        if record is None:
            raise BuildError(f"firmware ELF is missing packet buffer bank {symbol}")
        address, size, symbol_type = record
        if size != expected_size:
            raise BuildError(
                f"{symbol} occupies {size} bytes, expected {expected_size}"
            )
        if address % PACKET_BUFFER_ALIGNMENT != 0:
            raise BuildError(f"{symbol} is not cache-line aligned")
        if not region_start <= address or address + size > region_end:
            raise BuildError(
                f"{symbol} is outside its claimed {bank} range: 0x{address:08x}"
            )
        if symbol_type.upper() != "B":
            raise BuildError(f"{symbol} is not writable packet storage")
        banks[bank] = {
            "symbol": symbol,
            "symbol_type": symbol_type,
            "address": f"0x{address:08x}",
            "bytes": size,
            "frames": size // BENCHMARK_BUFFER_BYTES,
            "alignment_bytes": PACKET_BUFFER_ALIGNMENT,
            "range_start": f"0x{region_start:08x}",
            "range_end_exclusive": f"0x{region_end:08x}",
        }
    return {
        "total_bytes": sum(item["bytes"] for item in banks.values()),
        "total_frames": sum(item["frames"] for item in banks.values()),
        "banks": banks,
    }


def gpio_clock_diagnostic_buffer_usage(nm_output: str) -> dict[str, Any]:
    """Verify the isolated clock-diagnostic cache line is DMA-visible OCRAM."""

    symbols = parse_nm_symbols(nm_output)
    record = symbols.get(GPIO_CLOCK_DIAGNOSTIC_BUFFER_SYMBOL)
    if record is None:
        raise BuildError(
            "firmware ELF is missing GPIO clock diagnostic buffer "
            f"{GPIO_CLOCK_DIAGNOSTIC_BUFFER_SYMBOL}"
        )
    address, size, symbol_type = record
    if size != GPIO_CLOCK_DIAGNOSTIC_BUFFER_BYTES:
        raise BuildError(
            f"{GPIO_CLOCK_DIAGNOSTIC_BUFFER_SYMBOL} occupies {size} bytes, "
            f"expected {GPIO_CLOCK_DIAGNOSTIC_BUFFER_BYTES}"
        )
    if address % GPIO_CLOCK_DIAGNOSTIC_BUFFER_ALIGNMENT != 0:
        raise BuildError("GPIO clock diagnostic buffer is not cache-line aligned")
    if not OCRAM_START <= address or address + size > OCRAM_END:
        raise BuildError(
            "GPIO clock diagnostic buffer is outside DMA-visible OCRAM: "
            f"0x{address:08x}"
        )
    if symbol_type.upper() != "B":
        raise BuildError(
            "GPIO clock diagnostic buffer is not zero-initialized writable storage"
        )
    return {
        "symbol": GPIO_CLOCK_DIAGNOSTIC_BUFFER_SYMBOL,
        "symbol_type": symbol_type,
        "address": f"0x{address:08x}",
        "bytes": size,
        "alignment_bytes": GPIO_CLOCK_DIAGNOSTIC_BUFFER_ALIGNMENT,
        "range_start": f"0x{OCRAM_START:08x}",
        "range_end_exclusive": f"0x{OCRAM_END:08x}",
    }


def dma_allocation_usage(
    nm_output: str,
    expected_symbols: Mapping[str, tuple[str, int]],
    *,
    owner: str,
    alignment: int,
) -> dict[str, Any]:
    """Verify a fixed DMA ring, pressure sink, and TCD bank in OCRAM."""

    symbols = parse_nm_symbols(nm_output)
    allocations: dict[str, dict[str, Any]] = {}
    for allocation, (symbol, expected_size) in expected_symbols.items():
        record = symbols.get(symbol)
        if record is None:
            raise BuildError(f"firmware ELF is missing {owner} DMA {symbol}")
        address, size, symbol_type = record
        if size != expected_size:
            raise BuildError(
                f"{symbol} occupies {size} bytes, expected {expected_size}"
            )
        if address % alignment != 0:
            raise BuildError(f"{symbol} is not cache-line aligned")
        if not OCRAM_START <= address or address + size > OCRAM_END:
            raise BuildError(f"{symbol} is outside DMA-visible OCRAM: 0x{address:08x}")
        if symbol_type.upper() != "B":
            raise BuildError(f"{symbol} is not zero-initialized writable storage")
        allocations[allocation] = {
            "symbol": symbol,
            "symbol_type": symbol_type,
            "address": f"0x{address:08x}",
            "bytes": size,
            "alignment_bytes": alignment,
            "range_start": f"0x{OCRAM_START:08x}",
            "range_end_exclusive": f"0x{OCRAM_END:08x}",
        }
    return {
        "total_bytes": sum(item["bytes"] for item in allocations.values()),
        "allocations": allocations,
    }


def gpio_raw_dma_buffer_usage(nm_output: str) -> dict[str, Any]:
    """Verify the raw GPIO ring, pressure sink, and TCD bank."""

    return dma_allocation_usage(
        nm_output,
        GPIO_RAW_DMA_BUFFER_SYMBOLS,
        owner="raw GPIO",
        alignment=GPIO_RAW_DMA_BUFFER_ALIGNMENT,
    )


def adc_dma_buffer_usage(nm_output: str) -> dict[str, Any]:
    """Verify the paired ADC ring, pressure sink, and two TCD banks."""

    return dma_allocation_usage(
        nm_output,
        ADC_DMA_BUFFER_SYMBOLS,
        owner="ADC",
        alignment=ADC_DMA_BUFFER_ALIGNMENT,
    )


def gpio_packed_buffer_usage(nm_output: str) -> dict[str, Any]:
    """Verify the fixed CPU-owned packed GPIO ring is aligned in OCRAM."""

    symbols = parse_nm_symbols(nm_output)
    record = symbols.get(GPIO_PACKED_BUFFER_SYMBOL)
    if record is None:
        raise BuildError(
            f"firmware ELF is missing packed GPIO ring {GPIO_PACKED_BUFFER_SYMBOL}"
        )
    address, size, symbol_type = record
    if size != GPIO_PACKED_BUFFER_BYTES:
        raise BuildError(
            f"{GPIO_PACKED_BUFFER_SYMBOL} occupies {size} bytes, "
            f"expected {GPIO_PACKED_BUFFER_BYTES}"
        )
    if address % GPIO_PACKED_BUFFER_ALIGNMENT != 0:
        raise BuildError("packed GPIO ring is not cache-line aligned")
    if not OCRAM_START <= address or address + size > OCRAM_END:
        raise BuildError(f"packed GPIO ring is outside OCRAM: 0x{address:08x}")
    if symbol_type.upper() != "B":
        raise BuildError("packed GPIO ring is not zero-initialized writable storage")
    return {
        "symbol": GPIO_PACKED_BUFFER_SYMBOL,
        "symbol_type": symbol_type,
        "address": f"0x{address:08x}",
        "bytes": size,
        "buffers": 4,
        "stride_bytes": 4064,
        "payload_bytes_per_buffer": 4048,
        "alignment_bytes": GPIO_PACKED_BUFFER_ALIGNMENT,
        "range_start": f"0x{OCRAM_START:08x}",
        "range_end_exclusive": f"0x{OCRAM_END:08x}",
    }


def git_source_state() -> dict[str, Any]:
    """Record the Git commit and dirtiness of the exact firmware inputs."""

    commit = run_command(
        ["git", "-C", str(REPOSITORY_ROOT), "rev-parse", "HEAD"]
    ).stdout.strip()
    if len(commit) != 40 or any(
        character not in "0123456789abcdef" for character in commit
    ):
        raise BuildError("Git did not report a full lowercase commit identity")

    relative_inputs = [str(path.relative_to(REPOSITORY_ROOT)) for path in SOURCE_INPUTS]
    status = run_command(
        [
            "git",
            "-C",
            str(REPOSITORY_ROOT),
            "status",
            "--porcelain=v1",
            "--untracked-files=all",
            "--",
            *relative_inputs,
        ]
    ).stdout.splitlines()
    return {
        "git_commit": commit,
        "firmware_inputs_clean": not status,
        "firmware_input_changes": status,
    }


def sha256(path: Path) -> str:
    """Hash one exported build artifact."""

    digest = hashlib.sha256()
    with path.open("rb") as artifact_file:
        for chunk in iter(lambda: artifact_file.read(1024 * 1024), b""):
            digest.update(chunk)
    return digest.hexdigest()


def _canonical_sha256(value: Any) -> str:
    """Hash one JSON-compatible value with a stable representation."""

    encoded = json.dumps(value, separators=(",", ":"), sort_keys=True).encode("utf-8")
    return hashlib.sha256(encoded).hexdigest()


def stable_linker_resource_contract(
    memory_usage: Mapping[str, Any],
    binary_inspection: Mapping[str, Any],
) -> dict[str, Any]:
    """Project the profile-invariant linker and fixed-resource evidence."""

    return {
        "memory_usage": memory_usage,
        "binary_inspection": {
            name: value
            for name, value in binary_inspection.items()
            if name != "nm_path"
        },
    }


def _required_mapping(
    value: Mapping[str, Any], name: str, location: str = "manifest"
) -> Mapping[str, Any]:
    selected = value.get(name)
    if not isinstance(selected, dict):
        raise BuildError(f"{location}.{name} must be an object")
    return selected


def validate_profile_manifest(manifest: Mapping[str, Any]) -> CpuProfile:
    """Validate one manifest's closed profile, identity, and output contract."""

    if manifest.get("schema_version") != MANIFEST_SCHEMA_VERSION:
        raise BuildError("profile manifest schema version is not current")
    target = _required_mapping(manifest, "target")
    name = target.get("cpu_profile")
    if not isinstance(name, str):
        raise BuildError("manifest.target.cpu_profile must be a string")
    profile = cpu_profile(name)
    expected_target = {
        "fqbn": profile.fqbn,
        "core_id": CORE_ID,
        "core_version": CORE_VERSION,
        "warnings": "all",
        "resolved_build_properties": profile.expected_build_properties,
        "compile_time_clocks": {"F_CPU": profile.cpu_hz},
        "expected_runtime_clocks": {
            "F_CPU_ACTUAL": profile.cpu_hz,
            "F_BUS_ACTUAL": profile.bus_hz,
        },
    }
    mismatches = [
        name
        for name, expected in expected_target.items()
        if target.get(name) != expected
    ]
    if mismatches:
        raise BuildError("profile manifest target mismatch: " + ", ".join(mismatches))

    source = _required_mapping(manifest, "source")
    source_id = source.get("source_id")
    if not isinstance(source_id, str):
        raise BuildError("manifest.source.source_id must be a string")
    fingerprint = profile_build_fingerprint(source_id, profile)
    expected_source = {
        "build_fingerprint": fingerprint,
        "build_id": profile_build_id(source_id, fingerprint, profile),
        "cpu_profile": profile.name,
    }
    identity_mismatches = [
        name
        for name, expected in expected_source.items()
        if source.get(name) != expected
    ]
    if identity_mismatches:
        raise BuildError(
            "profile manifest build identity mismatch: "
            + ", ".join(identity_mismatches)
        )

    expected_output = profile.output_directory.relative_to(REPOSITORY_ROOT).as_posix()
    if manifest.get("output_directory") != expected_output:
        raise BuildError("profile manifest output directory is not isolated")

    compiler = _required_mapping(manifest, "compiler")
    compiler_identity = compiler.get("identity")
    if not isinstance(compiler_identity, str) or COMPILER_VERSION not in (
        compiler_identity.split()
    ):
        raise BuildError("profile manifest compiler identity is not pinned")

    command = manifest.get("command")
    if not isinstance(command, list) or not all(
        isinstance(argument, str) for argument in command
    ):
        raise BuildError("profile manifest command must be a string array")
    required_options = {
        "--clean",
        "--export-binaries",
        "--fqbn",
        "--output-dir",
    }
    if not required_options.issubset(command):
        raise BuildError("profile manifest command is missing required options")
    fqbn_index = command.index("--fqbn")
    output_index = command.index("--output-dir")
    if fqbn_index + 1 >= len(command) or command[fqbn_index + 1] != profile.fqbn:
        raise BuildError("profile manifest command FQBN is contradictory")
    if output_index + 1 >= len(command) or command[output_index + 1] != str(
        profile.output_directory
    ):
        raise BuildError("profile manifest command output directory is contradictory")
    if any("upload" in argument.casefold() for argument in command):
        raise BuildError("profile manifest command contains an upload action")

    memory_usage = _required_mapping(manifest, "memory_usage")
    binary_inspection = _required_mapping(manifest, "binary_inspection")
    parity = _required_mapping(manifest, "profile_parity")
    expected_parity_policy = {
        "policy": "thingdaq-clock-profile-parity-v1",
        "identical_artifact_suffixes": [".eep", ".map"],
        "same_size_profile_variant_artifact_suffixes": [
            ".bin",
            ".elf",
            ".hex",
        ],
    }
    parity_mismatches = [
        name
        for name, expected in expected_parity_policy.items()
        if parity.get(name) != expected
    ]
    if parity_mismatches:
        raise BuildError(
            "profile manifest parity policy mismatch: " + ", ".join(parity_mismatches)
        )
    contract = stable_linker_resource_contract(memory_usage, binary_inspection)
    if parity.get("stable_linker_resource_contract_sha256") != _canonical_sha256(
        contract
    ):
        raise BuildError("profile manifest linker/resource contract hash is invalid")
    _manifest_artifacts(manifest)
    return profile


def _manifest_artifacts(
    manifest: Mapping[str, Any],
) -> dict[str, Mapping[str, Any]]:
    raw = manifest.get("artifacts")
    if not isinstance(raw, list):
        raise BuildError("manifest.artifacts must be a list")
    artifacts: dict[str, Mapping[str, Any]] = {}
    for index, record in enumerate(raw):
        if not isinstance(record, dict):
            raise BuildError(f"manifest.artifacts[{index}] must be an object")
        path = record.get("path")
        if not isinstance(path, str) or not path:
            raise BuildError(f"manifest.artifacts[{index}].path must be a string")
        relative = Path(path)
        if relative.is_absolute() or len(relative.parts) != 1:
            raise BuildError(f"manifest artifact path is not local: {path!r}")
        if path in artifacts:
            raise BuildError(f"manifest contains duplicate artifact {path!r}")
        size = record.get("size_bytes")
        digest = record.get("sha256")
        if not isinstance(size, int) or isinstance(size, bool) or size < 0:
            raise BuildError(f"manifest artifact size is invalid: {path!r}")
        if not isinstance(digest, str) or re.fullmatch(r"[0-9a-f]{64}", digest) is None:
            raise BuildError(f"manifest artifact SHA-256 is invalid: {path!r}")
        artifacts[path] = record
    suffixes = {Path(path).suffix.casefold() for path in artifacts}
    missing = {".elf", ".hex", ".map"} - suffixes
    if missing:
        raise BuildError(
            "profile manifest is missing artifacts: " + ", ".join(sorted(missing))
        )
    if LINKER_MAP_NAME not in artifacts:
        raise BuildError("profile manifest does not identify the exact linker map")
    return artifacts


def validate_profile_parity(
    first: Mapping[str, Any], second: Mapping[str, Any]
) -> dict[str, Any]:
    """Separate allowed profile metadata from linker/resource drift."""

    first_profile = validate_profile_manifest(first)
    second_profile = validate_profile_manifest(second)
    if {first_profile.name, second_profile.name} != set(CPU_PROFILES):
        raise BuildError("profile parity requires exactly the 600 and 528 manifests")

    first_source = _required_mapping(first, "source")
    second_source = _required_mapping(second, "source")
    profile_identity_fields = {"build_fingerprint", "build_id", "cpu_profile"}
    first_stable_source = {
        name: value
        for name, value in first_source.items()
        if name not in profile_identity_fields
    }
    second_stable_source = {
        name: value
        for name, value in second_source.items()
        if name not in profile_identity_fields
    }
    if first_stable_source != second_stable_source:
        raise BuildError("profile manifests do not share identical source provenance")
    if first_source["build_id"] == second_source["build_id"]:
        raise BuildError("profile manifests do not have distinct build identities")

    for name in ("arduino_cli", "compiler"):
        if first.get(name) != second.get(name):
            raise BuildError(f"profile manifests disagree on {name}")
    if first.get("sketch_directory") != second.get("sketch_directory"):
        raise BuildError("profile manifests disagree on the sketch directory")

    first_contract = stable_linker_resource_contract(
        _required_mapping(first, "memory_usage"),
        _required_mapping(first, "binary_inspection"),
    )
    second_contract = stable_linker_resource_contract(
        _required_mapping(second, "memory_usage"),
        _required_mapping(second, "binary_inspection"),
    )
    if first_contract != second_contract:
        raise BuildError("unexpected cross-profile linker, memory, or resource drift")

    first_artifacts = _manifest_artifacts(first)
    second_artifacts = _manifest_artifacts(second)
    if first_artifacts.keys() != second_artifacts.keys():
        raise BuildError("profile manifests contain different artifact sets")
    identical_suffixes = {".eep", ".map"}
    variant_suffixes = {".bin", ".elf", ".hex"}
    for name, first_record in first_artifacts.items():
        second_record = second_artifacts[name]
        if first_record.get("size_bytes") != second_record.get("size_bytes"):
            raise BuildError(f"unexpected cross-profile artifact size drift: {name}")
        suffix = Path(name).suffix.casefold()
        first_hash = first_record.get("sha256")
        second_hash = second_record.get("sha256")
        if suffix in identical_suffixes and first_hash != second_hash:
            raise BuildError(f"unexpected cross-profile {suffix} drift: {name}")
        if suffix in variant_suffixes and first_hash == second_hash:
            raise BuildError(f"profile-specific artifact did not vary: {name}")
        if suffix not in identical_suffixes | variant_suffixes:
            raise BuildError(f"profile parity has no artifact policy for {name}")

    contract_hash = _canonical_sha256(first_contract)
    return {
        "profiles": sorted((first_profile.name, second_profile.name), reverse=True),
        "source_id": first_source["source_id"],
        "build_ids": {
            first_profile.name: first_source["build_id"],
            second_profile.name: second_source["build_id"],
        },
        "stable_linker_resource_contract_sha256": contract_hash,
        "artifact_count": len(first_artifacts),
    }


def build(
    arduino_cli_name: str,
    cpu_profile_name: str = DEFAULT_CPU_PROFILE_NAME,
) -> Path:
    """Validate tools, compile one exact profile, and write its manifest."""

    profile = cpu_profile(cpu_profile_name)

    resolved_cli = shutil.which(arduino_cli_name)
    if resolved_cli is None:
        raise BuildError(f"Arduino CLI executable not found: {arduino_cli_name!r}")
    arduino_cli = Path(resolved_cli).resolve()

    cli_identity = run_command([str(arduino_cli), "version"]).stdout.strip()
    core_result = run_command([str(arduino_cli), "core", "list", "--format", "json"])
    try:
        core_inventory = json.loads(core_result.stdout)
    except json.JSONDecodeError as error:
        raise BuildError("Arduino CLI returned invalid core inventory JSON") from error

    installed_version = installed_core_version(core_inventory, CORE_ID)
    if installed_version != CORE_VERSION:
        found = installed_version or "not installed"
        raise BuildError(
            f"requires {CORE_ID} {CORE_VERSION}, but found {found}; "
            "install the pinned core before building"
        )

    properties_result = run_command(
        [
            str(arduino_cli),
            "compile",
            "--fqbn",
            profile.fqbn,
            "--show-properties",
            str(SKETCH_DIRECTORY),
        ]
    )
    properties = parse_build_properties(properties_result.stdout)
    validate_build_properties(properties, profile)
    compiler = resolve_compiler(properties)
    nm = resolve_nm(compiler)
    compiler_identity = run_command([str(compiler), "--version"]).stdout.strip()
    compiler_first_line = compiler_identity.splitlines()[0]
    if COMPILER_VERSION not in compiler_first_line.split():
        raise BuildError(
            f"requires Arm GNU {COMPILER_VERSION}, but found {compiler_first_line}"
        )

    identity = build_identity(profile=profile)

    profile.output_directory.mkdir(parents=True, exist_ok=True)
    (profile.output_directory / LINKER_MAP_NAME).unlink(missing_ok=True)
    command = compile_command(
        arduino_cli,
        identity,
        properties["build.flags.defs"],
        properties["build.flags.ld"],
        profile,
    )
    compile_environment = dict(os.environ)
    compile_environment["SOURCE_DATE_EPOCH"] = str(identity.timestamp_epoch)
    compile_environment["TZ"] = "UTC"
    compile_result = run_command(command, environment=compile_environment)
    if compile_result.stdout:
        print(compile_result.stdout, end="")
    if compile_result.stderr:
        print(compile_result.stderr, end="", file=sys.stderr)
    memory_usage = parse_memory_usage(
        f"{compile_result.stdout}\n{compile_result.stderr}"
    )
    validate_memory_headroom(memory_usage)

    artifacts = sorted(
        path
        for path in profile.output_directory.rglob("*")
        if path.is_file() and path.suffix.lower() in ARTIFACT_SUFFIXES
    )
    artifact_suffixes = {path.suffix.lower() for path in artifacts}
    missing_artifacts = {".elf", ".hex", ".map"} - artifact_suffixes
    if missing_artifacts:
        names = ", ".join(sorted(missing_artifacts))
        raise BuildError(
            f"compile produced no {names} artifact in {profile.output_directory}"
        )
    elf = next(path for path in artifacts if path.suffix.lower() == ".elf")
    nm_result = run_command(
        [str(nm), "--print-size", "--size-sort", "--demangle", str(elf)]
    )
    checksum_resources = checksum_resource_usage(nm_result.stdout)
    benchmark_buffers = benchmark_buffer_usage(nm_result.stdout)
    packet_buffers = packet_buffer_usage(nm_result.stdout)
    gpio_clock_diagnostic_buffer = gpio_clock_diagnostic_buffer_usage(nm_result.stdout)
    adc_dma_buffers = adc_dma_buffer_usage(nm_result.stdout)
    gpio_raw_dma_buffers = gpio_raw_dma_buffer_usage(nm_result.stdout)
    gpio_packed_buffers = gpio_packed_buffer_usage(nm_result.stdout)
    binary_inspection = {
        "nm_path": str(nm),
        "checksum_resources": checksum_resources,
        "checksum_benchmark_buffers": benchmark_buffers,
        "packet_buffers": packet_buffers,
        "gpio_clock_diagnostic_buffer": gpio_clock_diagnostic_buffer,
        "adc_dma_buffers": adc_dma_buffers,
        "gpio_raw_dma_buffers": gpio_raw_dma_buffers,
        "gpio_packed_buffers": gpio_packed_buffers,
    }
    parity_contract = stable_linker_resource_contract(memory_usage, binary_inspection)

    manifest = {
        "schema_version": MANIFEST_SCHEMA_VERSION,
        "target": {
            "cpu_profile": profile.name,
            "fqbn": profile.fqbn,
            "core_id": CORE_ID,
            "core_version": installed_version,
            "warnings": "all",
            "resolved_build_properties": {
                name: properties[name] for name in profile.expected_build_properties
            },
            "compile_time_clocks": {"F_CPU": profile.cpu_hz},
            "expected_runtime_clocks": {
                "F_CPU_ACTUAL": profile.cpu_hz,
                "F_BUS_ACTUAL": profile.bus_hz,
            },
        },
        "arduino_cli": {
            "path": str(arduino_cli),
            "identity": cli_identity,
        },
        "compiler": {
            "path": str(compiler),
            "identity": compiler_first_line,
        },
        "binary_inspection": binary_inspection,
        "profile_parity": {
            "policy": "thingdaq-clock-profile-parity-v1",
            "stable_linker_resource_contract_sha256": _canonical_sha256(
                parity_contract
            ),
            "identical_artifact_suffixes": [".eep", ".map"],
            "same_size_profile_variant_artifact_suffixes": [
                ".bin",
                ".elf",
                ".hex",
            ],
        },
        "source": {
            "source_id": identity.source_id,
            "build_fingerprint": identity.build_fingerprint,
            "build_id": identity.build_id,
            "cpu_profile": identity.cpu_profile,
            "timestamp_epoch": identity.timestamp_epoch,
            "timestamp_utc": identity.timestamp_utc,
            "timestamp_policy": (
                "SOURCE_DATE_EPOCH when set; otherwise latest Git commit "
                "affecting firmware inputs"
            ),
            "inputs": [
                str(path.relative_to(REPOSITORY_ROOT))
                for path in collect_source_files()
            ],
            **git_source_state(),
        },
        "memory_usage": memory_usage,
        "command": command,
        "sketch_directory": str(SKETCH_DIRECTORY.relative_to(REPOSITORY_ROOT)),
        "output_directory": str(profile.output_directory.relative_to(REPOSITORY_ROOT)),
        "artifacts": [
            {
                "path": str(path.relative_to(profile.output_directory)),
                "size_bytes": path.stat().st_size,
                "sha256": sha256(path),
            }
            for path in artifacts
        ],
    }
    manifest_path = profile.output_directory / MANIFEST_NAME
    manifest_path.write_text(
        json.dumps(manifest, indent=2, sort_keys=True) + "\n", encoding="utf-8"
    )

    print(f"Arduino CLI: {cli_identity.splitlines()[0]}")
    print(f"Teensy core: {CORE_ID} {installed_version}")
    print(f"Compiler: {compiler_first_line}")
    print(f"CPU profile: {profile.name} MHz")
    print(f"Build ID: {identity.build_id}")
    print(f"Build timestamp: {identity.timestamp_utc}")
    print(f"Build manifest: {manifest_path}")
    return manifest_path


def parse_args(argv: Sequence[str] | None = None) -> argparse.Namespace:
    """Parse host tooling and one closed CPU-profile selection."""

    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument(
        "--arduino-cli",
        default="arduino-cli",
        help="Arduino CLI executable name or path (default: arduino-cli)",
    )
    parser.add_argument(
        "--cpu-profile",
        choices=tuple(CPU_PROFILES),
        default=DEFAULT_CPU_PROFILE_NAME,
        help=(
            "reviewed CPU menu profile "
            f"(default: {DEFAULT_CPU_PROFILE_NAME}, the production target)"
        ),
    )
    parser.add_argument(
        "--compare-profile-manifest",
        type=Path,
        help=(
            "after building, require profile parity with the other profile's "
            "build manifest"
        ),
    )
    return parser.parse_args(argv)


def main(argv: Sequence[str] | None = None) -> int:
    """Command-line entry point."""

    arguments = parse_args(argv)
    try:
        manifest_path = build(arguments.arduino_cli, arguments.cpu_profile)
        if arguments.compare_profile_manifest is not None:
            try:
                built_manifest = json.loads(manifest_path.read_text(encoding="utf-8"))
                reference_manifest = json.loads(
                    arguments.compare_profile_manifest.read_text(encoding="utf-8")
                )
            except (OSError, json.JSONDecodeError) as error:
                raise BuildError(f"could not load profile manifest: {error}") from error
            if not isinstance(built_manifest, dict) or not isinstance(
                reference_manifest, dict
            ):
                raise BuildError("profile manifests must contain JSON objects")
            parity = validate_profile_parity(built_manifest, reference_manifest)
            print(
                "Profile parity: "
                f"{', '.join(parity['profiles'])} MHz; "
                f"contract {parity['stable_linker_resource_contract_sha256']}"
            )
    except BuildError as error:
        print(f"error: {error}", file=sys.stderr)
        return 1
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
