"""Independent wire and contract-generator gates for the public v3 boundary."""

from __future__ import annotations

import copy
import hashlib
import importlib.util
import json
import struct
import subprocess
import sys
import zlib
from itertools import product
from pathlib import Path
from typing import Any

import pytest
from thingdone_daq._generated import protocol_v3_constants as v3

ROOT = Path(__file__).resolve().parents[2]
SPEC = importlib.util.spec_from_file_location(
    "generate_protocol_v3_test", ROOT / "tools/generate_protocol.py"
)
assert SPEC is not None and SPEC.loader is not None
GEN = importlib.util.module_from_spec(SPEC)
SPEC.loader.exec_module(GEN)


def load() -> dict[str, Any]:
    return json.loads((ROOT / "protocol/protocol-v3.json").read_bytes())


def test_flash_tables_survive_partial_use_in_multiple_translation_units(tmp_path):
    """A TU using only tuples must not discard another TU's clock tables."""
    first = tmp_path / "tuples.cpp"
    first.write_text(
        '#include "generated/protocol_v3_constants.h"\n'
        "const void* tuples() {\n"
        "  return thingdaq::protocol_v3::kSelectableConfigurations;\n}\n"
    )
    second = tmp_path / "tables.cpp"
    names = (
        "DefaultSettings",
        "CpuProfiles",
        "RateProfiles",
        "SelectableConfigurations",
    )
    second.write_text(
        '#include "generated/protocol_v3_constants.h"\n'
        "#include <cstdio>\nextern const void* tuples();\n"
        "int main() {\nusing namespace thingdaq::protocol_v3;\n"
        "if (tuples() != kSelectableConfigurations) return 1;\n"
        + "".join(
            f"std::fwrite(k{name}, 1, sizeof(k{name}), stdout);\n" for name in names
        )
        + "}\n"
    )
    binary = tmp_path / "tables"
    subprocess.run(
        [
            "g++",
            "-std=c++17",
            "-O2",
            "-D__IMXRT1062__",
            "-ffunction-sections",
            "-fdata-sections",
            "-Wl,--gc-sections",
            f"-I{ROOT / 'firmware/src'}",
            str(first),
            str(second),
            "-o",
            str(binary),
        ],
        check=True,
        capture_output=True,
    )
    result = subprocess.run([str(binary)], check=True, capture_output=True)
    expected = b"".join(
        b"".join(records)
        for records in (
            v3.DEFAULT_SETTINGS,
            v3.CPU_PROFILES,
            v3.RATE_PROFILES,
            v3.SELECTABLE_CONFIGURATIONS,
        )
    )
    assert result.stdout == expected


def validate(contract: dict[str, Any]) -> None:
    old1, bytes1 = GEN.load_contract()
    old2, bytes2 = GEN.load_contract(GEN.V2_SOURCE_PATH)
    GEN.validate_v3_contract(contract, old1, bytes1, old2, bytes2)


def fixture(contract: dict[str, Any], name: str) -> dict[str, Any]:
    return next(f for f in contract["golden_fixtures"] if f["name"] == name)


def test_all_legacy_outputs_remain_byte_identical() -> None:
    old1, bytes1 = GEN.load_contract()
    old2, bytes2 = GEN.load_contract(GEN.V2_SOURCE_PATH)
    outputs = GEN.expected_all_outputs(old1, bytes1, old2, bytes2)
    assert len(outputs) == 111
    assert (
        hashlib.sha256(bytes1).hexdigest()
        == "014648d18828c07fd2c8af16c430134bc28c4988d5b95d39613114f35623f222"
    )
    assert (
        hashlib.sha256(bytes2).hexdigest()
        == "1596bab522a711aa7980b0187d157b550d9ec8f69049d9961c579b1ef2cc9c48"
    )
    manifest = "".join(
        f"{hashlib.sha256(data).hexdigest()}  {path.relative_to(ROOT)}\n"
        for path, data in sorted(outputs.items())
    )
    assert (
        hashlib.sha256(manifest.encode()).hexdigest()
        == "130f84398661a726583665f2a73017f41401ef8ad7b985e6f2bcf30bca1a1a12"
    )
    for path, data in outputs.items():
        assert path.read_bytes() == data


def test_v3_determinism_source_hashes_and_schema_formats() -> None:
    contract, source = GEN.load_contract(GEN.V3_SOURCE_PATH)
    validate(contract)
    outputs = GEN.expected_v3_outputs(contract, source)
    assert outputs == GEN.expected_v3_outputs(contract, source)
    assert len(outputs) == 31
    assert v3.SOURCE_SHA256 == hashlib.sha256(source).hexdigest()
    for path, data in outputs.items():
        assert path.read_bytes() == data
    cpp = (ROOT / "firmware/src/generated/protocol_v3_constants.h").read_text()
    assert f"Source SHA-256: {v3.SOURCE_SHA256}" in cpp
    for name, schema in contract["payload_schemas"].items():
        assert (
            struct.calcsize(getattr(v3, name.upper() + "_STRUCT_FORMAT"))
            == schema["size"]
        )
        for field in schema["fields"]:
            assert (
                getattr(v3, f"{name.upper()}_{field['name'].upper()}_OFFSET")
                == field["offset"]
            )


def test_fixtures_have_independently_valid_framing_checksums_and_hashes() -> None:
    manifest = json.loads((ROOT / "protocol/fixtures-v3/manifest.json").read_text())
    assert manifest["source_sha256"] == v3.SOURCE_SHA256
    for entry in manifest["fixtures"]:
        frame = (ROOT / "protocol/fixtures-v3" / entry["file"]).read_bytes()
        assert frame[:5] == bytes.fromhex("efbeadde03")
        assert struct.unpack_from("<HBB", frame, 8) == (44, 1, 0)
        assert struct.unpack_from("<II", frame, 12) == (len(frame), len(frame) - 48)
        assert int.from_bytes(frame[-4:], "little") == zlib.adler32(frame[:-4])
        assert hashlib.sha256(frame).hexdigest() == entry["frame_sha256"]
        assert hashlib.sha256(frame[44:-4]).hexdigest() == entry["payload_sha256"]
    # Full header, prefix and sample bytes derived without the generator helpers.
    body = bytes.fromhex(
        "efbeadde030104002c00010042000000120000000100000000000000"
        "00000000000000000000000002000000"
        "02040000080000000000000000f0ffbc3a12"
    )
    expected = body + struct.pack("<I", zlib.adler32(body))
    assert (ROOT / "protocol/fixtures-v3/adc-pack12.bin").read_bytes() == expected


def test_capabilities_are_exact_tuples_with_bounded_zero_padding() -> None:
    frame = (ROOT / "protocol/fixtures-v3/get_capabilities-response.bin").read_bytes()
    payload = frame[44:-4]
    assert len(payload) == 1404
    assert payload[:8] == bytes([0, 0, 0, 0, 2, 1, 60, 0])
    assert payload[36:56] == bytes.fromhex("030001030104000801010c0040420f0040420f00")
    records = [payload[124 + i * 20 : 144 + i * 20] for i in range(64)]
    assert tuple(records[:60]) == v3.SELECTABLE_CONFIGURATIONS
    assert len(set(records[:60])) == 60
    assert records[60:] == [bytes(20)] * 4
    assert sum(record[4] == 2 for record in records[:60]) == 12
    for record in records[:60]:
        assert record[5] == 4  # Only the existing 1 MHz/1 MHz rate ID.
        assert record[7] == (8 if record[6] == 0 else 16)
        assert struct.unpack_from("<II", record, 12) == (1_000_000, 1_000_000)
        if record[4] == 2:
            assert record[8:10] == b"\0\0"


def test_advertised_table_matches_independent_allowed_configuration_matrix() -> None:
    # Freeze the release policy without reading its generated constants:
    # CPU 600 accepts both codecs, CPU 450 accepts RAW only; aux width is tied
    # to bank mode. No 528 MHz or higher-rate profile enters this matrix.
    expected = set()
    for cpu, policies in ((1, (0, 1)), (2, (0,))):
        for stream, source, aux, gpio_policy, adc_policy in product(
            (1, 2, 3), (0, 1), (0, 1), policies, policies
        ):
            expected.add(
                bytes(
                    [
                        stream,
                        source,
                        1,
                        3,
                        cpu,
                        4,
                        aux,
                        16 if aux else 8,
                        gpio_policy,
                        adc_policy,
                        12,
                        0,
                    ]
                )
                + bytes.fromhex("40420f0040420f00")
            )
    assert len(expected) == 60
    assert set(v3.SELECTABLE_CONFIGURATIONS) == expected
    payload = (
        ROOT / "protocol/fixtures-v3/get_capabilities-response.bin"
    ).read_bytes()[44:-4]
    assert payload[6] == len(expected)
    assert {
        payload[offset : offset + 20] for offset in range(124, 1324, 20)
    } == expected


@pytest.mark.parametrize(
    ("name", "expected"),
    [
        ("adc-raw", bytes.fromhex("0000ff0fbc0a2301")),
        ("adc-pack12", bytes.fromhex("00f0ffbc3a12")),
        ("gpio8-rle", bytes.fromhex("040012040034")),
        ("gpio16-rle", bytes.fromhex("040034120400cdab")),
        ("gpio8-raw", bytes.fromhex("00ff00ff")),
        ("gpio16-raw", bytes.fromhex("0000ffff0000ffff")),
    ],
)
def test_hand_derived_codec_sample_bytes(name: str, expected: bytes) -> None:
    assert (ROOT / "protocol/fixtures-v3" / f"{name}.bin").read_bytes()[
        56:-4
    ] == expected


@pytest.mark.parametrize(
    ("path", "value"),
    [
        (("protocol_version",), 0x83),
        (("header", "size"), 48),
        (("limits", "max_logical_payload_bytes"), 2**32),
        (("limits", "max_configuration_tuples"), 65),
        (("generated_outputs", "fixture_directory"), "protocol/fixtures"),
        (("timing", "timestamp_hz"), 600_000_000),
        (("cpu_profiles", 0, "cpu_clock_hz"), 528_000_000),
        (("cpu_profiles", 1, "adc_clock_hz"), 0),
        (("rate_profiles", 0, "gpio_sample_rate_hz"), 4_000_000),
        (("defaults", "cpu_profile"), 2),
        (("command_kinds", 5, "value"), 27),
        (("command_kinds", 5, "response_kind"), "INFO_RESPONSE"),
        (("enums", "encoding", 1, "value"), 0),
        (("enums", "encoding", 1, "value"), 256),
        (("payload_schemas", "data_prefix", "fields", 2, "required"), 1),
        (("payload_schemas", "settings", "fields", 1, "offset"), 0),
        (("selectable_configurations", 0, "gpio_width_bits"), 16),
        (("selectable_configurations", 0, "wire_version"), 2),
        (("selectable_configurations", 0, "stream_mask"), 0),
        (("selectable_configurations", 0, "aux_bank_mode"), 3),
        (("selectable_configurations", 0, "rate_profile"), 0),
        (("selectable_configurations", 48, "adc_policy"), 1),
    ],
)
def test_rejects_inconsistent_contract(path: tuple[str | int, ...], value: Any) -> None:
    contract = load()
    target: Any = contract
    for key in path[:-1]:
        target = target[key]
    target[path[-1]] = value
    with pytest.raises(GEN.ContractError):
        validate(contract)


@pytest.mark.parametrize("case", ["duplicate", "missing-default", "too-many"])
def test_rejects_invalid_tuple_tables(case: str) -> None:
    contract = load()
    records = contract["selectable_configurations"]
    if case == "duplicate":
        records.append(copy.deepcopy(records[0]))
    elif case == "missing-default":
        records.remove(contract["defaults"])
    else:
        records.extend(copy.deepcopy(records[:5]))
    with pytest.raises(GEN.ContractError):
        validate(contract)


@pytest.mark.parametrize(
    ("name", "section", "field", "value"),
    [
        ("get_capabilities-response", "values", "configuration_count", 65),
        ("get_capabilities-response", "values", "cpu_profile_count", 0),
        ("get_capabilities-response", "values", "max_data_frame_bytes", 2**32 - 1),
        ("info-response", "values", "hardware_serial", "real-device"),
        ("info-error", "values", "error_code", 0),
        ("stop-response", "values", "pending_frames", 1),
        ("adc-pack12", "prefix", "encoding", 1),
        ("gpio8-raw", "prefix", "encoding", 2),
        ("adc-pack12", "prefix", "decoded_bytes", 2**32 - 1),
        ("adc-pack12", "prefix", "run_count", 1),
        ("gpio8-rle", "prefix", "run_count", 0),
        ("gpio16-rle", "prefix", "run_count", 9),
    ],
)
def test_rejects_invalid_golden_metadata(
    name: str, section: str, field: str, value: Any
) -> None:
    contract = load()
    fixture(contract, name)["payload"][section][field] = value
    with pytest.raises(GEN.ContractError):
        validate(contract)


@pytest.mark.parametrize(
    ("name", "sample_hex"),
    [
        ("adc-raw", "0000ffffbc0a2301"),  # Out-of-range ADC1.
        ("adc-pack12", "00f0ffbc3a"),  # Truncated pair.
        ("gpio8-rle", "000012080034"),  # Zero-length run.
        ("gpio8-rle", "ffff12040034"),  # Expansion beyond declared count.
        ("gpio8-rle", "030012040034"),  # Too few logical samples.
        ("gpio8-rle", "040012040012"),  # Nonmaximal runs.
        ("gpio16-rle", "040034120400"),  # Truncated record.
    ],
)
def test_rejects_invalid_encoded_golden_samples(name: str, sample_hex: str) -> None:
    contract = load()
    fixture(contract, name)["payload"]["sample_hex"] = sample_hex
    with pytest.raises(GEN.ContractError):
        validate(contract)


def test_rejects_nonzero_unused_table_slot() -> None:
    contract = load()
    values = fixture(contract, "get_capabilities-response")["payload"]["values"]
    values["configurations"][63]["source"] = 1
    with pytest.raises(GEN.ContractError, match="unused table slots"):
        validate(contract)


@pytest.mark.parametrize("protocol", ["all", "v1", "v2", "v3"])
def test_cli_check_selects_version_without_writing(protocol: str) -> None:
    result = subprocess.run(
        [
            sys.executable,
            str(ROOT / "tools/generate_protocol.py"),
            "--check",
            "--protocol",
            protocol,
        ],
        cwd=ROOT,
        capture_output=True,
        text=True,
        check=False,
    )
    assert result.returncode == 0, result.stderr
    assert "current" in result.stdout


@pytest.mark.parametrize(
    ("name", "changes"),
    [
        ("adc-raw", {"adc_policy": 1}),
        ("gpio8-rle", {"gpio_policy": 0}),
        ("gpio16-raw", {"gpio_width_bits": 8, "aux_bank_mode": 0}),
        ("adc-pack12", {"stream_mask": 2}),
        ("gpio8-raw", {"source": 1}),
    ],
)
def test_rejects_data_inconsistent_with_active_settings(
    name: str, changes: dict[str, int]
) -> None:
    contract = load()
    fixture(contract, name)["settings"].update(changes)
    with pytest.raises(GEN.ContractError):
        validate(contract)
