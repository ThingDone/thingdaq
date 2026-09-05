#!/usr/bin/env python3
"""Verify the pinned Teensy toolchain and export identified firmware."""

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
from itertools import pairwise
from pathlib import Path
from typing import Any

REPOSITORY_ROOT = Path(__file__).resolve().parents[2]
SKETCH_DIRECTORY = REPOSITORY_ROOT / "firmware"
FQBN = "teensy:avr:teensy40:usb=serial,speed=450,opt=o2std"
RELEASE_BUILD = True
CORE_ID = "teensy:avr"
CORE_VERSION = "1.62.0"
COMPILER_VERSION = "15.2.1"
EXPECTED_BUILD_PROPERTIES = {
    "build.board": "TEENSY40",
    "build.fcpu": "450000000",
    "build.flags.optimize": "-O2",
    "build.usbtype": "USB_SERIAL",
}
OUTPUT_DIRECTORY = (
    SKETCH_DIRECTORY / "build" / ("teensy.avr.teensy40.usb_serial.speed_450.opt_o2std")
)
MANIFEST_NAME = "build-manifest.json"
MANIFEST_SCHEMA_VERSION = 11
LINKER_MAP_NAME = "firmware.ino.map"
ARTIFACT_SUFFIXES = {".bin", ".eep", ".elf", ".hex", ".map"}
SOURCE_INPUTS = (
    SKETCH_DIRECTORY / "firmware.ino",
    SKETCH_DIRECTORY / "src",
    REPOSITORY_ROOT / "protocol/protocol-v1.json",
    REPOSITORY_ROOT / "protocol/protocol-v2.json",
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
        "thingdaq_packet_storage_primary",
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
GPIO_INPUT_RAW_RING_BYTES_PER_BANK = 4 * 2024 * 4
GPIO_RAW_OVERFLOW_SINK_BYTES_PER_BANK = 32
GPIO_RAW_DESCRIPTOR_BYTES_PER_BANK = 5 * 32
GPIO_PAIRED_JOIN_STATE_BYTES = 768
GPIO_PAIRED_JOIN_STATE_OFFSET = 0
GPIO_AUX_DESCRIPTOR_OFFSET = (
    GPIO_PAIRED_JOIN_STATE_OFFSET + GPIO_PAIRED_JOIN_STATE_BYTES
)
GPIO_PRIMARY_INPUT_OVERFLOW_SINK_OFFSET = (
    GPIO_AUX_DESCRIPTOR_OFFSET + GPIO_RAW_DESCRIPTOR_BYTES_PER_BANK
)
GPIO_AUX_OVERFLOW_SINK_OFFSET = (
    GPIO_PRIMARY_INPUT_OVERFLOW_SINK_OFFSET + GPIO_RAW_OVERFLOW_SINK_BYTES_PER_BANK
)
GPIO_AUX_INPUT_WORKSPACE_BYTES = (
    GPIO_AUX_OVERFLOW_SINK_OFFSET + GPIO_RAW_OVERFLOW_SINK_BYTES_PER_BANK
)
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
DTCM_START = 0x20000000
DTCM_END = 0x20080000
MINIMUM_RAM1_FREE_FOR_LOCALS_BYTES = 32 * 1024
MINIMUM_RAM2_FREE_FOR_HEAP_BYTES = 4 * 1024
PACKET_BUFFER_BASELINE_FRAMES = 200
PACKET_CAPACITY_CHANGE_NOTE: str | None = None
PINNED_USB_TX_BUFFER_SYMBOL = "txbuffer"
PINNED_USB_TX_BUFFER_BYTES = 4 * 2048


class BuildError(RuntimeError):
    """A reproducibility check or firmware build failed."""


@dataclass(frozen=True, slots=True)
class BuildIdentity:
    """Deterministic source and timestamp metadata embedded in the firmware."""

    source_id: str
    build_id: str
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


def validate_build_properties(properties: Mapping[str, str]) -> None:
    """Reject a menu selection that differs from the documented target."""

    mismatches = [
        f"{name}={properties.get(name)!r}, expected {expected!r}"
        for name, expected in EXPECTED_BUILD_PROPERTIES.items()
        if properties.get(name) != expected
    ]
    definitions = set(properties.get("build.flags.defs", "").split())
    for required in ("-D__IMXRT1062__", "-DTEENSYDUINO=160"):
        if required not in definitions:
            mismatches.append(f"build.flags.defs is missing {required}")
    if "-std=gnu++17" not in properties.get("build.flags.cpp", "").split():
        mismatches.append("build.flags.cpp is missing -std=gnu++17")
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


def build_identity(environment: Mapping[str, str] | None = None) -> BuildIdentity:
    """Create deterministic metadata for the current firmware source snapshot."""

    source_id = source_fingerprint(collect_source_files())
    epoch = resolve_build_epoch(environment)
    timestamp = datetime.fromtimestamp(epoch, tz=timezone.utc).strftime(
        "%Y-%m-%dT%H:%M:%SZ"
    )
    return BuildIdentity(
        source_id=source_id,
        build_id=f"thingdaq-{source_id[:16]}",
        timestamp_epoch=epoch,
        timestamp_utc=timestamp,
    )


def identity_definitions(base_definitions: str, identity: BuildIdentity) -> str:
    """Append numeric deterministic identity macros to core definitions."""

    if len(identity.source_id) != 64 or any(
        character not in "0123456789abcdef" for character in identity.source_id
    ):
        raise BuildError("source ID must be a lowercase SHA-256")
    if not identity.build_id.isascii() or not 0 < len(identity.build_id) < 32:
        raise BuildError("build ID must fit the protocol's 31-byte ASCII limit")
    timestamp = datetime.fromtimestamp(identity.timestamp_epoch, tz=timezone.utc)
    expected_build_id = f"thingdaq-{identity.source_id[:16]}"
    expected_timestamp = timestamp.strftime("%Y-%m-%dT%H:%M:%SZ")
    if identity.build_id != expected_build_id:
        raise BuildError("build ID must be derived from the source ID")
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
        f"-DTHINGDAQ_BUILD_EPOCH={identity.timestamp_epoch}ULL",
        f"-DTHINGDAQ_BUILD_YEAR={timestamp.year}U",
        f"-DTHINGDAQ_BUILD_MONTH={timestamp.month}U",
        f"-DTHINGDAQ_BUILD_DAY={timestamp.day}U",
        f"-DTHINGDAQ_BUILD_HOUR={timestamp.hour}U",
        f"-DTHINGDAQ_BUILD_MINUTE={timestamp.minute}U",
        f"-DTHINGDAQ_BUILD_SECOND={timestamp.second}U",
        "-DTHINGDAQ_OPTIMIZATION_O2STD=1",
        f"-DTHINGDAQ_RELEASE_FIXED_1MHZ={int(RELEASE_BUILD)}",
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
) -> list[str]:
    """Return the immutable command used for every supported firmware build."""

    linker_map = OUTPUT_DIRECTORY / LINKER_MAP_NAME
    return [
        str(arduino_cli),
        "compile",
        "--fqbn",
        FQBN,
        "--clean",
        "--warnings",
        "all",
        "--build-property",
        f"build.flags.defs={identity_definitions(base_definitions, identity)}",
        "--build-property",
        f"build.flags.ld={base_linker_flags} -Wl,-Map={linker_map},--cref",
        "--export-binaries",
        "--output-dir",
        str(OUTPUT_DIRECTORY),
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
    """Reject a linked image that violates either explicit runtime margin."""

    available = memory_usage["ram1"]["free_for_locals_bytes"]
    if available < MINIMUM_RAM1_FREE_FOR_LOCALS_BYTES:
        raise BuildError(
            "RAM1 leaves only "
            f"{available} bytes for locals/stack; requires at least "
            f"{MINIMUM_RAM1_FREE_FOR_LOCALS_BYTES}"
        )
    heap_available = memory_usage["ram2"]["free_for_heap_bytes"]
    if heap_available < MINIMUM_RAM2_FREE_FOR_HEAP_BYTES:
        raise BuildError(
            "RAM2 leaves only "
            f"{heap_available} bytes for heap; requires at least "
            f"{MINIMUM_RAM2_FREE_FOR_HEAP_BYTES}"
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
    packet_record = symbols.get(PACKET_BUFFER_SYMBOLS["DTCM_PRIMARY"][0])
    dtcm = regions["DTCM_PACKET"]
    if packet_record is not None and packet_record[0] == int(dtcm["address"], 16):
        dtcm["physical_allocation"] = "DTCM_PRIMARY_PACKET_PAGE_0"
        dtcm["view_offset_bytes"] = 0
        dtcm["lease"] = "IDLE benchmark only; packet/acquisition path must be quiescent"
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
    """Verify legacy and paired GPIO views over one fixed raw allocation."""

    result = dma_allocation_usage(
        nm_output,
        GPIO_RAW_DMA_BUFFER_SYMBOLS,
        owner="raw GPIO",
        alignment=GPIO_RAW_DMA_BUFFER_ALIGNMENT,
    )
    allocations = result["allocations"]
    workspace = auxiliary_input_workspace_usage(nm_output)

    def view(allocation: str, offset: int, size: int) -> dict[str, Any]:
        physical = allocations[allocation]
        start = int(physical["address"], 16) + offset
        if offset < 0 or size <= 0 or offset + size > int(physical["bytes"]):
            raise BuildError(f"GPIO {allocation} logical view escapes physical storage")
        return {
            "physical_allocation": allocation,
            "address": f"0x{start:08x}",
            "offset_bytes": offset,
            "bytes": size,
        }

    legacy = {
        "RING": view("RING", 0, int(allocations["RING"]["bytes"])),
        "OVERFLOW_SINK": view(
            "OVERFLOW_SINK", 0, GPIO_RAW_OVERFLOW_SINK_BYTES_PER_BANK
        ),
        "DESCRIPTORS": view("DESCRIPTORS", 0, GPIO_RAW_DESCRIPTOR_BYTES_PER_BANK),
    }
    input_primary = {
        "RING": view("RING", 0, GPIO_INPUT_RAW_RING_BYTES_PER_BANK),
        "OVERFLOW_SINK": workspace["views"]["PRIMARY_INPUT_OVERFLOW_SINK"],
        "DESCRIPTORS": view("DESCRIPTORS", 0, GPIO_RAW_DESCRIPTOR_BYTES_PER_BANK),
    }
    input_auxiliary = {
        "RING": view(
            "RING",
            GPIO_INPUT_RAW_RING_BYTES_PER_BANK,
            GPIO_INPUT_RAW_RING_BYTES_PER_BANK,
        ),
        "OVERFLOW_SINK": workspace["views"]["AUXILIARY_OVERFLOW_SINK"],
        "DESCRIPTORS": workspace["views"]["AUXILIARY_DESCRIPTORS"],
    }
    if 2 * GPIO_INPUT_RAW_RING_BYTES_PER_BANK != int(allocations["RING"]["bytes"]):
        raise BuildError("paired GPIO rings do not exactly cover legacy raw storage")
    result["mode_views"] = {
        "DISABLED": {"PRIMARY": legacy},
        "INPUT": {
            "PRIMARY": input_primary,
            "AUXILIARY": input_auxiliary,
        },
    }
    result["shared_input_workspace"] = workspace
    result["packet_storage_repartitioned"] = False
    return result


def auxiliary_input_workspace_usage(nm_output: str) -> dict[str, Any]:
    """Map INPUT-only state into the IDLE-only OCRAM benchmark scratch."""

    benchmark = benchmark_buffer_usage(nm_output)["regions"]["OCRAM_DMA"]
    base = int(benchmark["address"], 16)
    specifications = {
        "PAIRED_JOIN_STATE": (
            GPIO_PAIRED_JOIN_STATE_OFFSET,
            GPIO_PAIRED_JOIN_STATE_BYTES,
            "GPIO_JOIN",
        ),
        "AUXILIARY_DESCRIPTORS": (
            GPIO_AUX_DESCRIPTOR_OFFSET,
            GPIO_RAW_DESCRIPTOR_BYTES_PER_BANK,
            "AUX_GPIO_CAPTURE",
        ),
        "PRIMARY_INPUT_OVERFLOW_SINK": (
            GPIO_PRIMARY_INPUT_OVERFLOW_SINK_OFFSET,
            GPIO_RAW_OVERFLOW_SINK_BYTES_PER_BANK,
            "GPIO_CAPTURE",
        ),
        "AUXILIARY_OVERFLOW_SINK": (
            GPIO_AUX_OVERFLOW_SINK_OFFSET,
            GPIO_RAW_OVERFLOW_SINK_BYTES_PER_BANK,
            "AUX_GPIO_CAPTURE",
        ),
    }
    views: dict[str, dict[str, Any]] = {}
    spans: list[tuple[int, int, str]] = []
    for name, (offset, size, owner) in specifications.items():
        if (
            offset % GPIO_RAW_DMA_BUFFER_ALIGNMENT != 0
            or size % GPIO_RAW_DMA_BUFFER_ALIGNMENT != 0
            or offset + size > int(benchmark["bytes"])
        ):
            raise BuildError(f"auxiliary INPUT workspace view {name} is invalid")
        views[name] = {
            "physical_allocation": "CHECKSUM_BENCHMARK_OCRAM",
            "physical_symbol": benchmark["symbol"],
            "owner": owner,
            "address": f"0x{base + offset:08x}",
            "offset_bytes": offset,
            "bytes": size,
            "alignment_bytes": GPIO_RAW_DMA_BUFFER_ALIGNMENT,
        }
        spans.append((offset, offset + size, name))
    spans.sort()
    for previous, current in pairwise(spans):
        if current[0] < previous[1]:
            raise BuildError(
                f"auxiliary INPUT workspace view {previous[2]} overlaps {current[2]}"
            )
    if max(end for _, end, _ in spans) != GPIO_AUX_INPUT_WORKSPACE_BYTES:
        raise BuildError("auxiliary INPUT workspace accounting is incomplete")
    return {
        "physical_storage": benchmark,
        "lease": "INPUT acquisition only; mutually exclusive with IDLE checksum benchmark",
        "active_bytes": GPIO_AUX_INPUT_WORKSPACE_BYTES,
        "unleased_bytes": int(benchmark["bytes"]) - GPIO_AUX_INPUT_WORKSPACE_BYTES,
        "views": views,
    }


def gpio_paired_join_state_usage(nm_output: str) -> dict[str, Any]:
    """Verify the fixed paired-join view inside aligned OCRAM storage."""

    workspace = auxiliary_input_workspace_usage(nm_output)
    return {
        **workspace["views"]["PAIRED_JOIN_STATE"],
        "lease": workspace["lease"],
    }


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
    result = {
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
    result["mode_layouts"] = {
        "DISABLED": {
            "gpio_item_bytes": 1,
            "gpio_items_per_frame": 4048,
            "payload_bytes": 4048,
            "storage_bytes": size,
        },
        "INPUT": {
            "gpio_item_bytes": 2,
            "gpio_items_per_frame": 2024,
            "payload_bytes": 4048,
            "storage_bytes": size,
        },
    }
    result["storage_repartitioned"] = False
    return result


def _protocol_v2_contract() -> dict[str, Any]:
    """Load the canonical experimental contract used by target inspection."""

    path = REPOSITORY_ROOT / "protocol/protocol-v2.json"
    try:
        value = json.loads(path.read_text(encoding="utf-8"))
    except (OSError, json.JSONDecodeError) as error:
        raise BuildError(
            f"could not load experimental protocol contract: {error}"
        ) from error
    if not isinstance(value, dict):
        raise BuildError("experimental protocol contract is not a JSON object")
    return value


def auxiliary_input_resource_contract(
    contract: Mapping[str, Any] | None = None,
) -> dict[str, Any]:
    """Normalize and fail-close the target resources declared by protocol v2."""

    source = _protocol_v2_contract() if contract is None else contract
    try:
        auxiliary = source["auxiliary_input"]
        banks = auxiliary["pin_banks"]
        primary = banks["primary"]
        aux = banks["auxiliary"]
        resources = auxiliary["provisional_resources"]
        normalized = {
            "owner": "AUX_GPIO_CAPTURE",
            "pins": [int(value) for value in aux["teensy_pins"]],
            "gpio1_bits_by_wire_bit": [
                int(value) for value in aux["standard_gpio_bits_by_wire_bit"]
            ],
            "gpio1_capture_mask": int(aux["aggregate_mask"]),
            "gpio1_standard_port": int(aux["standard_gpio"]),
            "gpio6_fast_port": int(aux["fast_gpio"]),
            "gpr26_fast_select": int(aux["fast_select_gpr"]),
            "pit_channel": int(resources["clock_pit_channel"]),
            "xbar_input": int(resources["xbar_input"]),
            "primary_xbar_output": int(resources["primary_xbar_output"]),
            "auxiliary_xbar_output": int(resources["auxiliary_xbar_output"]),
            "primary_dmamux_source": int(resources["primary_dmamux_source"]),
            "auxiliary_dmamux_source": int(resources["auxiliary_dmamux_source"]),
            "primary_edma_channel": int(resources["primary_edma_channel"]),
            "auxiliary_edma_channel": int(resources["auxiliary_edma_channel"]),
            "edma_priority_order": [
                str(value) for value in resources["enabled_mode_edma_priority_order"]
            ],
            "edma_priorities": [
                int(value) for value in resources["enabled_mode_edma_priorities"]
            ],
            "gpio_dma_irq_priority": int(resources["gpio_dma_irq_priority"]),
            "raw_ring_depth_per_bank": int(resources["raw_ring_depth_per_bank"]),
            "raw_word_bytes_per_bank": int(resources["raw_word_bytes_per_bank"]),
            "paired_join_required": bool(resources["paired_join_required"]),
            "primary_gpio2_bits_by_wire_bit": [
                int(value) for value in primary["standard_gpio_bits_by_wire_bit"]
            ],
        }
    except (KeyError, TypeError, ValueError) as error:
        raise BuildError(
            f"experimental auxiliary resource contract is malformed: {error}"
        ) from error

    expected = {
        "owner": "AUX_GPIO_CAPTURE",
        "pins": list(range(16, 24)),
        "gpio1_bits_by_wire_bit": [23, 22, 17, 16, 26, 27, 24, 25],
        "gpio1_capture_mask": 0x0FC30000,
        "gpio1_standard_port": 1,
        "gpio6_fast_port": 6,
        "gpr26_fast_select": 26,
        "pit_channel": 0,
        "xbar_input": 56,
        "primary_xbar_output": 0,
        "auxiliary_xbar_output": 1,
        "primary_dmamux_source": 30,
        "auxiliary_dmamux_source": 31,
        "primary_edma_channel": 2,
        "auxiliary_edma_channel": 3,
        "edma_priority_order": ["ADC0", "ADC1", "PRIMARY_GPIO", "AUXILIARY_GPIO"],
        "edma_priorities": [3, 2, 1, 0],
        "gpio_dma_irq_priority": 64,
        "raw_ring_depth_per_bank": 4,
        "raw_word_bytes_per_bank": 4,
        "paired_join_required": True,
        "primary_gpio2_bits_by_wire_bit": [10, 17, 16, 11, 0, 2, 1, 3],
    }
    if normalized != expected:
        raise BuildError(
            "experimental auxiliary target resources differ from the pinned registry"
        )
    return {
        **normalized,
        "auxiliary_dma_interrupt": {
            "irq": 3,
            "vector": 19,
            "priority": normalized["gpio_dma_irq_priority"],
        },
        "shared_xbar_selector": {
            "register_index": 0,
            "primary_rmw_mask": "0x00ff",
            "auxiliary_rmw_mask": "0xff00",
            "combined_rmw_mask": "0xffff",
        },
        "arbitration_scope": (
            "fixed eDMA service order only; no pad-level simultaneity claim"
        ),
    }


def packet_retention_usage(
    packet_buffers: Mapping[str, Any],
    contract: Mapping[str, Any] | None = None,
    *,
    capacity_change_note: str | None = PACKET_CAPACITY_CHANGE_NOTE,
) -> dict[str, Any]:
    """Quantify conservative one-/two-stream retention in ADC-frame units.

    Legacy profiles have equal frame durations and these bounds are exact.
    Profile 4 GPIO frames span four ADC frames; these deliberately preserve
    the conservative STATUS bounds, not a maximum-retention prediction.
    """

    total_frames = int(packet_buffers["total_frames"])
    if total_frames <= 0:
        raise BuildError("packet capacity must be positive")
    if total_frames != PACKET_BUFFER_BASELINE_FRAMES and not capacity_change_note:
        raise BuildError(
            "packet capacity changed from "
            f"{PACKET_BUFFER_BASELINE_FRAMES} to {total_frames} frames without "
            "a documented capacity-change note"
        )
    source = _protocol_v2_contract() if contract is None else contract
    try:
        timestamp_hz = int(source["timing"]["timestamp_hz"])
        raw_profiles = source["rate_profiles"]
        gpio_declared_frames = int(source["gpio_capture"]["packet_buffer_count"])
        combined = source["combined_acquisition"]
        combined_declared_frames = int(combined["packet_buffer_count"])
        combined_declared_split = int(combined["packet_primary_count"]) + int(
            combined["packet_reserve_count"]
        )
    except (KeyError, TypeError, ValueError) as error:
        raise BuildError(f"experimental rate contract is malformed: {error}") from error
    if not (
        total_frames
        == gpio_declared_frames
        == combined_declared_frames
        == combined_declared_split
    ):
        raise BuildError(
            "linked packet capacity disagrees with the experimental protocol contract"
        )
    if (
        timestamp_hz <= 0
        or not isinstance(raw_profiles, list)
        or len(raw_profiles) != 5
    ):
        raise BuildError("experimental rate contract has invalid timing/profile count")

    complete_combined_intervals = total_frames // 2
    profiles: list[dict[str, Any]] = []
    for raw in raw_profiles:
        try:
            name = str(raw["name"])
            adc_rate = int(raw["adc_pair_rate_hz"])
            gpio_rate = int(raw["gpio_sample_rate_hz"])
            coverage = raw["frame_coverage_ticks"]
            modes: dict[str, dict[str, int]] = {}
            for mode in ("DISABLED", "INPUT"):
                coverage_ticks = int(coverage[mode])
                combined_ticks = coverage_ticks * complete_combined_intervals
                single_ticks = coverage_ticks * total_frames
                combined_us_numerator = combined_ticks * 1_000_000
                single_us_numerator = single_ticks * 1_000_000
                if (
                    coverage_ticks <= 0
                    or combined_us_numerator % timestamp_hz != 0
                    or single_us_numerator % timestamp_hz != 0
                ):
                    raise BuildError(
                        f"{name} {mode} retention is not integral in microseconds"
                    )
                modes[mode] = {
                    "coverage_ticks": coverage_ticks,
                    "combined_retention_us": combined_us_numerator // timestamp_hz,
                    "single_stream_retention_us": single_us_numerator // timestamp_hz,
                }
        except (KeyError, TypeError, ValueError) as error:
            raise BuildError(
                f"experimental rate profile is malformed: {error}"
            ) from error
        profiles.append(
            {
                "profile": name,
                "adc_pair_rate_hz": adc_rate,
                "gpio_sample_rate_hz": gpio_rate,
                "modes": modes,
            }
        )
    return {
        "capacity": {
            "baseline_frames": PACKET_BUFFER_BASELINE_FRAMES,
            "current_frames": total_frames,
            "delta_frames": total_frames - PACKET_BUFFER_BASELINE_FRAMES,
            "change_note": capacity_change_note,
        },
        "combined_frames_per_interval": 2,
        "coverage_units": "ADC frames; conservative lower bounds for profile 4",
        "combined_complete_intervals": complete_combined_intervals,
        "unused_frames_after_complete_intervals": total_frames % 2,
        "raw_ring_overlay_preserves_packet_capacity": True,
        "profiles": profiles,
    }


def linker_map_memory_usage(
    linker_map: str, memory_usage: Mapping[str, Mapping[str, int]]
) -> dict[str, Any]:
    """Verify linked DTCM/OCRAM sections against exact map regions and floors."""

    regions: dict[str, tuple[int, int]] = {}
    for name, origin_text, length_text in re.findall(
        r"^(DTCM|RAM)\s+(0x[0-9a-fA-F]+)\s+(0x[0-9a-fA-F]+)\s+rw$",
        linker_map,
        flags=re.MULTILINE,
    ):
        start = int(origin_text, 16)
        regions[name] = (start, start + int(length_text, 16))
    expected_regions = {
        "DTCM": (DTCM_START, DTCM_END),
        "RAM": (OCRAM_START, OCRAM_END),
    }
    if regions != expected_regions:
        raise BuildError("linker map DTCM/RAM regions differ from the pinned layout")

    sections: dict[str, tuple[int, int]] = {}
    for name in (".bss", ".bss.dma"):
        match = re.search(
            rf"^{re.escape(name)}\s+(0x[0-9a-fA-F]+)\s+(0x[0-9a-fA-F]+)$",
            linker_map,
            flags=re.MULTILINE,
        )
        if match is None:
            raise BuildError(f"linker map is missing output section {name}")
        start = int(match.group(1), 16)
        sections[name] = (start, start + int(match.group(2), 16))
    if not DTCM_START <= sections[".bss"][0] <= sections[".bss"][1] <= DTCM_END:
        raise BuildError("linked .bss section escapes DTCM")
    dma_start, dma_end = sections[".bss.dma"]
    if dma_start != OCRAM_START or not dma_start <= dma_end <= OCRAM_END:
        raise BuildError("linked .bss.dma section escapes DMA-visible OCRAM")
    linked_heap_bytes = OCRAM_END - dma_end
    reported_heap_bytes = int(memory_usage["ram2"]["free_for_heap_bytes"])
    reported_ram2_bytes = int(memory_usage["ram2"]["variables_bytes"])
    if (
        linked_heap_bytes != reported_heap_bytes
        or dma_end - dma_start != reported_ram2_bytes
    ):
        raise BuildError("linker map and Teensy RAM2 summary disagree")
    if linked_heap_bytes < MINIMUM_RAM2_FREE_FOR_HEAP_BYTES:
        raise BuildError("linked .bss.dma violates the RAM2 heap floor")
    return {
        "regions": {
            name: {
                "start": f"0x{start:08x}",
                "end_exclusive": f"0x{end:08x}",
                "bytes": end - start,
            }
            for name, (start, end) in regions.items()
        },
        "sections": {
            name: {
                "start": f"0x{start:08x}",
                "end_exclusive": f"0x{end:08x}",
                "bytes": end - start,
            }
            for name, (start, end) in sections.items()
        },
        "ram1_minimum_free_for_locals_stack_bytes": (
            MINIMUM_RAM1_FREE_FOR_LOCALS_BYTES
        ),
        "ram1_actual_free_for_locals_stack_bytes": int(
            memory_usage["ram1"]["free_for_locals_bytes"]
        ),
        "ram2_minimum_free_for_heap_bytes": MINIMUM_RAM2_FREE_FOR_HEAP_BYTES,
        "ram2_actual_free_for_heap_bytes": linked_heap_bytes,
    }


def managed_memory_usage(nm_output: str) -> dict[str, Any]:
    """Reject overlaps among every project/pinned allocation in the campaign."""

    expected: dict[str, tuple[str, int, int, int]] = {
        "packet_dtcm_primary": (
            *PACKET_BUFFER_SYMBOLS["DTCM_PRIMARY"][:2],
            DTCM_START,
            DTCM_END,
        ),
        "packet_ocram_reserve": (
            *PACKET_BUFFER_SYMBOLS["OCRAM_RESERVE"][:2],
            OCRAM_START,
            OCRAM_END,
        ),
        "checksum_dtcm": (
            BENCHMARK_BUFFER_SYMBOLS["DTCM_PACKET"][0],
            BENCHMARK_BUFFER_BYTES,
            DTCM_START,
            DTCM_END,
        ),
        "checksum_ocram": (
            BENCHMARK_BUFFER_SYMBOLS["OCRAM_DMA"][0],
            BENCHMARK_BUFFER_BYTES,
            OCRAM_START,
            OCRAM_END,
        ),
        "gpio_clock_diagnostic": (
            GPIO_CLOCK_DIAGNOSTIC_BUFFER_SYMBOL,
            GPIO_CLOCK_DIAGNOSTIC_BUFFER_BYTES,
            OCRAM_START,
            OCRAM_END,
        ),
        "gpio_raw_storage": (
            *GPIO_RAW_DMA_BUFFER_SYMBOLS["RING"],
            OCRAM_START,
            OCRAM_END,
        ),
        "gpio_overflow_sinks": (
            *GPIO_RAW_DMA_BUFFER_SYMBOLS["OVERFLOW_SINK"],
            OCRAM_START,
            OCRAM_END,
        ),
        "gpio_descriptors": (
            *GPIO_RAW_DMA_BUFFER_SYMBOLS["DESCRIPTORS"],
            OCRAM_START,
            OCRAM_END,
        ),
        "gpio_packed_storage": (
            GPIO_PACKED_BUFFER_SYMBOL,
            GPIO_PACKED_BUFFER_BYTES,
            OCRAM_START,
            OCRAM_END,
        ),
        "adc_raw_storage": (*ADC_DMA_BUFFER_SYMBOLS["RING"], OCRAM_START, OCRAM_END),
        "adc_overflow_sink": (
            *ADC_DMA_BUFFER_SYMBOLS["OVERFLOW_SINK"],
            OCRAM_START,
            OCRAM_END,
        ),
        "adc_descriptors": (
            *ADC_DMA_BUFFER_SYMBOLS["DESCRIPTORS"],
            OCRAM_START,
            OCRAM_END,
        ),
        "pinned_usb_tx": (
            PINNED_USB_TX_BUFFER_SYMBOL,
            PINNED_USB_TX_BUFFER_BYTES,
            OCRAM_START,
            OCRAM_END,
        ),
    }
    symbols = parse_nm_symbols(nm_output)
    allocations: list[dict[str, Any]] = []
    for owner, (symbol, expected_size, region_start, region_end) in expected.items():
        record = symbols.get(symbol)
        if record is None:
            raise BuildError(f"firmware ELF is missing managed allocation {symbol}")
        address, size, symbol_type = record
        if size != expected_size:
            raise BuildError(
                f"{symbol} occupies {size} bytes, expected {expected_size}"
            )
        if (
            address % 32 != 0
            or not region_start <= address
            or address + size > region_end
        ):
            raise BuildError(f"{symbol} violates its managed memory region")
        if symbol_type.upper() != "B":
            raise BuildError(f"{symbol} is not writable zero-initialized storage")
        allocations.append(
            {
                "owner": owner,
                "symbol": symbol,
                "address": f"0x{address:08x}",
                "end_exclusive": f"0x{address + size:08x}",
                "bytes": size,
                "region": "DTCM" if region_start == DTCM_START else "OCRAM",
            }
        )
    allocations.sort(key=lambda item: int(item["address"], 16))
    by_owner = {item["owner"]: item for item in allocations}
    if (
        by_owner["checksum_dtcm"]["address"]
        != by_owner["packet_dtcm_primary"]["address"]
    ):
        raise BuildError("checksum DTCM view is not packet page zero")
    for previous, current in pairwise(allocations):
        overlaps = int(current["address"], 16) < int(previous["end_exclusive"], 16)
        declared_idle_packet_view = (
            previous["owner"] == "packet_dtcm_primary"
            and current["owner"] == "checksum_dtcm"
            and current["address"] == previous["address"]
            and current["bytes"] == BENCHMARK_BUFFER_BYTES
        )
        if overlaps and not declared_idle_packet_view:
            raise BuildError(
                f"managed allocation {previous['owner']} overlaps {current['owner']}"
            )
        if declared_idle_packet_view:
            current["physical_allocation"] = previous["owner"]
            current["lease"] = (
                "IDLE benchmark only; packet/acquisition path must be quiescent"
            )
    return {
        "overlap_check": "passed",
        "allocation_count": len(allocations),
        "allocations": allocations,
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


def build(arduino_cli_name: str) -> Path:
    """Validate tool identities, compile the exact target, and write a manifest."""

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
            FQBN,
            "--show-properties",
            str(SKETCH_DIRECTORY),
        ]
    )
    properties = parse_build_properties(properties_result.stdout)
    validate_build_properties(properties)
    compiler = resolve_compiler(properties)
    nm = resolve_nm(compiler)
    compiler_identity = run_command([str(compiler), "--version"]).stdout.strip()
    compiler_first_line = compiler_identity.splitlines()[0]
    if COMPILER_VERSION not in compiler_first_line.split():
        raise BuildError(
            f"requires Arm GNU {COMPILER_VERSION}, but found {compiler_first_line}"
        )

    identity = build_identity()

    OUTPUT_DIRECTORY.mkdir(parents=True, exist_ok=True)
    (OUTPUT_DIRECTORY / LINKER_MAP_NAME).unlink(missing_ok=True)
    command = compile_command(
        arduino_cli,
        identity,
        properties["build.flags.defs"],
        properties["build.flags.ld"],
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
        for path in OUTPUT_DIRECTORY.rglob("*")
        if path.is_file() and path.suffix.lower() in ARTIFACT_SUFFIXES
    )
    artifact_suffixes = {path.suffix.lower() for path in artifacts}
    missing_artifacts = {".elf", ".hex", ".map"} - artifact_suffixes
    if missing_artifacts:
        names = ", ".join(sorted(missing_artifacts))
        raise BuildError(f"compile produced no {names} artifact in {OUTPUT_DIRECTORY}")
    elf = next(path for path in artifacts if path.suffix.lower() == ".elf")
    linker_map = next(path for path in artifacts if path.suffix.lower() == ".map")
    linker_map_text = linker_map.read_text(encoding="utf-8")
    nm_result = run_command(
        [str(nm), "--print-size", "--size-sort", "--demangle", str(elf)]
    )
    checksum_resources = checksum_resource_usage(nm_result.stdout)
    benchmark_buffers = benchmark_buffer_usage(nm_result.stdout)
    packet_buffers = packet_buffer_usage(nm_result.stdout)
    gpio_clock_diagnostic_buffer = gpio_clock_diagnostic_buffer_usage(nm_result.stdout)
    adc_dma_buffers = adc_dma_buffer_usage(nm_result.stdout)
    gpio_raw_dma_buffers = gpio_raw_dma_buffer_usage(nm_result.stdout)
    auxiliary_input_workspace = auxiliary_input_workspace_usage(nm_result.stdout)
    gpio_paired_join_state = gpio_paired_join_state_usage(nm_result.stdout)
    gpio_packed_buffers = gpio_packed_buffer_usage(nm_result.stdout)
    auxiliary_resources = auxiliary_input_resource_contract()
    packet_retention = packet_retention_usage(packet_buffers)
    linker_memory = linker_map_memory_usage(linker_map_text, memory_usage)
    managed_memory = managed_memory_usage(nm_result.stdout)

    manifest = {
        "schema_version": MANIFEST_SCHEMA_VERSION,
        "release_policy": {
            "fixed_1mhz": RELEASE_BUILD,
            "core_hz": 450000000 if RELEASE_BUILD else None,
            "protocol_version": 2 if RELEASE_BUILD else None,
            "supported_rate_profile_mask": 16 if RELEASE_BUILD else None,
            "adc_dma_active_lookahead_generations": 4 if RELEASE_BUILD else 6,
            "legacy_gpio_capture_diagnostic_enabled": not RELEASE_BUILD,
        },
        "target": {
            "fqbn": FQBN,
            "core_id": CORE_ID,
            "core_version": installed_version,
            "warnings": "all",
            "resolved_build_properties": {
                name: properties[name] for name in EXPECTED_BUILD_PROPERTIES
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
        "binary_inspection": {
            "nm_path": str(nm),
            "checksum_resources": checksum_resources,
            "checksum_benchmark_buffers": benchmark_buffers,
            "packet_buffers": packet_buffers,
            "gpio_clock_diagnostic_buffer": gpio_clock_diagnostic_buffer,
            "adc_dma_buffers": adc_dma_buffers,
            "gpio_raw_dma_buffers": gpio_raw_dma_buffers,
            "auxiliary_input_workspace": auxiliary_input_workspace,
            "gpio_paired_join_state": gpio_paired_join_state,
            "gpio_packed_buffers": gpio_packed_buffers,
            "auxiliary_input_resources": auxiliary_resources,
            "packet_retention": packet_retention,
            "linker_memory": linker_memory,
            "managed_memory": managed_memory,
        },
        "source": {
            "source_id": identity.source_id,
            "build_id": identity.build_id,
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
        "output_directory": str(OUTPUT_DIRECTORY.relative_to(REPOSITORY_ROOT)),
        "artifacts": [
            {
                "path": str(path.relative_to(OUTPUT_DIRECTORY)),
                "size_bytes": path.stat().st_size,
                "sha256": sha256(path),
            }
            for path in artifacts
        ],
    }
    manifest_path = OUTPUT_DIRECTORY / MANIFEST_NAME
    manifest_path.write_text(
        json.dumps(manifest, indent=2, sort_keys=True) + "\n", encoding="utf-8"
    )

    print(f"Arduino CLI: {cli_identity.splitlines()[0]}")
    print(f"Teensy core: {CORE_ID} {installed_version}")
    print(f"Compiler: {compiler_first_line}")
    print(f"Build ID: {identity.build_id}")
    print(f"Build timestamp: {identity.timestamp_utc}")
    print(f"Build manifest: {manifest_path}")
    return manifest_path


def parse_args(argv: Sequence[str] | None = None) -> argparse.Namespace:
    """Parse the one host-specific override without weakening target pins."""

    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument(
        "--arduino-cli",
        default="arduino-cli",
        help="Arduino CLI executable name or path (default: arduino-cli)",
    )
    return parser.parse_args(argv)


def main(argv: Sequence[str] | None = None) -> int:
    """Command-line entry point."""

    arguments = parse_args(argv)
    try:
        build(arguments.arduino_cli)
    except BuildError as error:
        print(f"error: {error}", file=sys.stderr)
        return 1
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
