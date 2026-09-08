"""Determinism and semantic drift checks for all protocol-derived artifacts."""

from __future__ import annotations

import hashlib
import importlib.util
import json
import re
import struct
import unittest
from enum import IntEnum, IntFlag
from pathlib import Path
from typing import Any, ClassVar

from thingdone_daq._generated import protocol_constants as constants

REPOSITORY_ROOT = Path(__file__).resolve().parents[2]
CONTRACT_PATH = REPOSITORY_ROOT / "protocol/protocol-v1.json"
GENERATOR_PATH = REPOSITORY_ROOT / "tools/generate_protocol.py"
CPP_PATH = REPOSITORY_ROOT / "firmware/src/generated/protocol_constants.h"
DOCUMENT_PATH = REPOSITORY_ROOT / "doc/protocol/protocol-v1.md"
MANIFEST_PATH = REPOSITORY_ROOT / "protocol/fixtures/manifest.json"

GENERATOR_SPEC = importlib.util.spec_from_file_location(
    "generate_protocol_exhaustive_test",
    GENERATOR_PATH,
)
assert GENERATOR_SPEC is not None and GENERATOR_SPEC.loader is not None
generate_protocol = importlib.util.module_from_spec(GENERATOR_SPEC)
GENERATOR_SPEC.loader.exec_module(generate_protocol)

_INTEGER_FORMATS = {"u8": "B", "u16": "H", "u32": "I", "u64": "Q"}
_INTEGER_WIDTHS = {"u8": 1, "u16": 2, "u32": 4, "u64": 8}


def _pascal(name: str) -> str:
    return "".join(part.capitalize() for part in name.lower().split("_"))


def _field_width(field: dict[str, Any]) -> int:
    field_type = field["type"]
    if field_type in _INTEGER_WIDTHS:
        return _INTEGER_WIDTHS[field_type]
    if field_type in {"bytes", "nul_ascii", "u8_array"}:
        return int(field["count"])
    if field_type == "repeated_u16_pair":
        return int(field["count"]) * 4
    raise AssertionError(f"unexpected field type {field_type!r}")


class ProtocolGenerationDriftTests(unittest.TestCase):
    contract: ClassVar[dict[str, Any]]
    source_bytes: ClassVar[bytes]
    cpp: ClassVar[str]
    document: ClassVar[str]

    @classmethod
    def setUpClass(cls) -> None:
        cls.source_bytes = CONTRACT_PATH.read_bytes()
        cls.contract = json.loads(cls.source_bytes)
        cls.cpp = CPP_PATH.read_text(encoding="utf-8")
        cls.document = DOCUMENT_PATH.read_text(encoding="utf-8")

    def test_generator_is_deterministic_and_every_output_is_current(self) -> None:
        generate_protocol.validate_contract(self.contract)

        first = generate_protocol.expected_outputs(self.contract, self.source_bytes)
        second = generate_protocol.expected_outputs(self.contract, self.source_bytes)

        self.assertEqual(first, second)
        self.assertEqual(26, len(first))
        for path, expected in first.items():
            with self.subTest(path=path.relative_to(REPOSITORY_ROOT)):
                self.assertTrue(path.is_file())
                self.assertEqual(expected, path.read_bytes())

    def test_source_hash_reaches_python_cpp_manifest_and_all_fixtures(self) -> None:
        source_hash = hashlib.sha256(self.source_bytes).hexdigest()
        manifest = json.loads(MANIFEST_PATH.read_text(encoding="utf-8"))

        self.assertEqual(source_hash, constants.SOURCE_SHA256)
        self.assertEqual(source_hash, manifest["source_sha256"])
        self.assertIn(f"Source SHA-256: {source_hash}", self.cpp)
        self.assertEqual(
            {entry["name"] for entry in self.contract["frame_kinds"]},
            {entry["kind"] for entry in manifest["fixtures"]},
        )

    def test_scalar_limits_timing_and_data_layout_match_python_and_cpp(self) -> None:
        limits = self.contract["limits"]
        timing = self.contract["timing"]
        layouts = self.contract["data_layouts"]
        data_payload_bytes = (
            int(limits["data_frame_bytes"])
            - int(self.contract["header"]["size"])
            - int(self.contract["trailer"]["size"])
        )
        expected_scalars = {
            "PROTOCOL_VERSION": int(self.contract["protocol_version"]),
            "HEADER_SIZE": int(self.contract["header"]["size"]),
            "TRAILER_SIZE": int(self.contract["trailer"]["size"]),
            "MIN_FRAME_BYTES": int(limits["min_frame_bytes"]),
            "DATA_FRAME_BYTES": int(limits["data_frame_bytes"]),
            "MAX_DATA_FRAME_BYTES": int(limits["max_data_frame_bytes"]),
            "DATA_PAYLOAD_BYTES": data_payload_bytes,
            "MAX_CONTROL_FRAME_BYTES": int(limits["max_control_frame_bytes"]),
            "MAX_COMMAND_FRAME_BYTES": int(limits["max_command_frame_bytes"]),
            "MAX_COMMAND_PAYLOAD_BYTES": int(limits["max_command_payload_bytes"]),
            "TIMESTAMP_HZ": int(timing["timestamp_hz"]),
            "ADC_PAIR_RATE_HZ": int(timing["adc_pair_rate_hz"]),
            "ADC_PAIR_PERIOD_TICKS": int(timing["adc_pair_period_ticks"]),
            "ADC1_PHASE_TICKS": int(timing["adc1_phase_ticks"]),
            "GPIO_SAMPLE_RATE_HZ": int(timing["gpio_sample_rate_hz"]),
            "GPIO_SAMPLE_PERIOD_TICKS": int(timing["gpio_sample_period_ticks"]),
            "FRAME_COVERAGE_TICKS": (
                int(layouts["adc"]["items_per_frame"])
                * int(timing["adc_pair_period_ticks"])
            ),
            "ADC_BYTES_PER_PAIR": int(layouts["adc"]["bytes_per_item"]),
            "ADC_PAIRS_PER_FRAME": int(layouts["adc"]["items_per_frame"]),
            "ADC_RESOLUTION_BITS": int(layouts["adc"]["resolution_bits"]),
            "ADC_CONTAINER_BITS": int(layouts["adc"]["container_bits"]),
            "GPIO_SAMPLES_PER_FRAME": int(layouts["gpio"]["items_per_frame"]),
        }

        self.assertEqual("little", constants.BYTE_ORDER)
        self.assertIn("kWireIsLittleEndian = true", self.cpp)
        self.assertEqual(int(self.contract["magic"]), constants.MAGIC)
        self.assertIn(f"kMagic = 0x{int(self.contract['magic']):08X}U", self.cpp)
        for python_name, expected in expected_scalars.items():
            with self.subTest(constant=python_name):
                self.assertEqual(expected, getattr(constants, python_name))
                self.assertRegex(
                    self.cpp,
                    rf"\bk{_pascal(python_name)}\b[^\n]*=\s*{expected}U;",
                )

        self.assertEqual(
            tuple(layouts["gpio"]["pins_by_bit"]),
            constants.GPIO_PINS_BY_BIT,
        )
        cpp_pins = ", ".join(f"{int(pin)}U" for pin in layouts["gpio"]["pins_by_bit"])
        self.assertIn(f"kGpioPinsByBit[] = {{{cpp_pins}}};", self.cpp)

    def test_header_and_payload_offsets_match_python_and_cpp(self) -> None:
        header = self.contract["header"]
        expected_header_format = "<" + "".join(
            _INTEGER_FORMATS[field["type"]] for field in header["fields"]
        )
        self.assertEqual(expected_header_format, constants.HEADER_STRUCT_FORMAT)
        self.assertEqual(int(header["size"]), struct.calcsize(expected_header_format))

        for field in header["fields"]:
            python_name = f"HEADER_{field['name'].upper()}_OFFSET"
            cpp_name = f"kHeader{_pascal(field['name'])}Offset"
            with self.subTest(header_field=field["name"]):
                self.assertEqual(int(field["offset"]), getattr(constants, python_name))
                self.assertIn(
                    f"{cpp_name} = {int(field['offset'])}U;",
                    self.cpp,
                )

        for schema_name, schema in self.contract["payload_schemas"].items():
            python_prefix = schema_name.upper()
            cpp_prefix = _pascal(schema_name)
            with self.subTest(schema=schema_name, property="size"):
                self.assertEqual(
                    int(schema["size"]),
                    getattr(constants, f"{python_prefix}_PAYLOAD_SIZE"),
                )
                self.assertIn(
                    f"k{cpp_prefix}PayloadSize = {int(schema['size'])}U;",
                    self.cpp,
                )
            for field in schema["fields"]:
                python_field = field["name"].upper()
                cpp_field = _pascal(field["name"])
                with self.subTest(schema=schema_name, field=field["name"]):
                    self.assertEqual(
                        int(field["offset"]),
                        getattr(
                            constants,
                            f"{python_prefix}_{python_field}_OFFSET",
                        ),
                    )
                    self.assertIn(
                        f"k{cpp_prefix}{cpp_field}Offset = {int(field['offset'])}U;",
                        self.cpp,
                    )
                    if "count" in field:
                        self.assertEqual(
                            int(field["count"]),
                            getattr(
                                constants,
                                f"{python_prefix}_{python_field}_COUNT",
                            ),
                        )
                        self.assertIn(
                            f"k{cpp_prefix}{cpp_field}Count = {int(field['count'])}U;",
                            self.cpp,
                        )

    def test_every_enum_matches_source_python_and_cpp(self) -> None:
        enum_specs: tuple[
            tuple[str, list[dict[str, Any]], type[IntEnum | IntFlag], str, int],
            ...,
        ] = (
            (
                "frame_kinds",
                self.contract["frame_kinds"],
                constants.FrameKind,
                "FrameKind",
                8,
            ),
            (
                "command_kinds",
                self.contract["command_kinds"],
                constants.CommandKind,
                "CommandKind",
                8,
            ),
            ("flags", self.contract["flags"], constants.FrameFlag, "FrameFlag", 16),
            (
                "checksum_algorithms",
                self.contract["checksum_algorithms"],
                constants.ChecksumAlgorithm,
                "ChecksumAlgorithm",
                8,
            ),
            (
                "response_status",
                self.contract["enums"]["response_status"],
                constants.ResponseStatus,
                "ResponseStatus",
                8,
            ),
            (
                "error_code",
                self.contract["enums"]["error_code"],
                constants.ErrorCode,
                "ErrorCode",
                16,
            ),
            (
                "device_state",
                self.contract["enums"]["device_state"],
                constants.DeviceState,
                "DeviceState",
                8,
            ),
            (
                "stream_mask",
                self.contract["enums"]["stream_mask"],
                constants.StreamMask,
                "StreamMask",
                8,
            ),
            (
                "capability_bits",
                self.contract["enums"]["capability_bits"],
                constants.Capability,
                "Capability",
                32,
            ),
            (
                "source",
                self.contract["enums"]["source"],
                constants.Source,
                "Source",
                8,
            ),
            (
                "board_id",
                self.contract["enums"]["board_id"],
                constants.BoardId,
                "BoardId",
                16,
            ),
            (
                "mcu_id",
                self.contract["enums"]["mcu_id"],
                constants.McuId,
                "McuId",
                16,
            ),
            (
                "benchmark_vector",
                self.contract["enums"]["benchmark_vector"],
                constants.BenchmarkVector,
                "BenchmarkVector",
                8,
            ),
            (
                "benchmark_memory_region",
                self.contract["enums"]["benchmark_memory_region"],
                constants.BenchmarkMemoryRegion,
                "BenchmarkMemoryRegion",
                8,
            ),
            (
                "benchmark_cache_state",
                self.contract["enums"]["benchmark_cache_state"],
                constants.BenchmarkCacheState,
                "BenchmarkCacheState",
                8,
            ),
        )

        for source_name, entries, python_enum, cpp_name, bits in enum_specs:
            expected = {entry["name"]: int(entry["value"]) for entry in entries}
            observed = {
                member.name: int(member)
                for member in python_enum
                if member.name != "NONE"
            }
            match = re.search(
                rf"enum class {cpp_name} : std::uint{bits}_t \{{(?P<body>.*?)\n\}};",
                self.cpp,
                re.DOTALL,
            )
            with self.subTest(enum=source_name):
                self.assertEqual(expected, observed)
                self.assertIsNotNone(match)
            assert match is not None
            cpp_body = match.group("body")
            for name, value in expected.items():
                with self.subTest(enum=source_name, member=name):
                    self.assertIn(f"k{_pascal(name)} = {value}U,", cpp_body)

    def test_normative_document_tables_match_machine_readable_values(self) -> None:
        for field in self.contract["header"]["fields"]:
            with self.subTest(table="header", field=field["name"]):
                self.assertIn(
                    f"| {field['offset']} | {_field_width(field)} | "
                    f"`{field['type']}` | No |",
                    self.document,
                )
        for entry in self.contract["frame_kinds"]:
            with self.subTest(table="frame kinds", member=entry["name"]):
                self.assertIn(
                    f"| `0x{int(entry['value']):02X}` | `{entry['name']}` |",
                    self.document,
                )
        for entry in self.contract["flags"]:
            with self.subTest(table="flags", member=entry["name"]):
                self.assertIn(
                    f"| `0x{int(entry['value']):04X}` | `{entry['name']}` |",
                    self.document,
                )
        for entry in self.contract["checksum_algorithms"]:
            with self.subTest(table="checksums", member=entry["name"]):
                self.assertIn(
                    f"| {entry['value']} | `{entry['name']}` |",
                    self.document,
                )
        for entry in self.contract["enums"]["capability_bits"]:
            with self.subTest(table="capabilities", member=entry["name"]):
                self.assertIn(
                    f"| `0x{int(entry['value']):08X}` | `{entry['name']}` |",
                    self.document,
                )
        for entry in self.contract["enums"]["error_code"]:
            with self.subTest(table="errors", member=entry["name"]):
                self.assertIn(
                    f"| {entry['value']} | `{entry['name']}` |",
                    self.document,
                )
        for bit, pin in enumerate(self.contract["data_layouts"]["gpio"]["pins_by_bit"]):
            with self.subTest(table="GPIO pins", bit=bit):
                self.assertIn(f"| {bit} | D{pin} |", self.document)


if __name__ == "__main__":
    unittest.main()
