"""Independent generation, wire-vector, and compatibility checks for aux v2."""

from __future__ import annotations

import hashlib
import importlib.util
import json
import random
import struct
import unittest
import zlib
from pathlib import Path
from typing import Any, ClassVar

from thingdaq import GpioCaptureDiagnosticResult, Status, ThingDAQ, low_level
from thingdaq._generated import protocol_constants as v1_constants
from thingdaq._generated import protocol_v2_constants as constants
from thingdaq.protocol import Frame as V1Frame
from thingdaq.protocol_v2 import (
    MAX_V2_BUFFERED_BYTES,
    IncrementalV2FrameParser,
    V2ConfigurationEchoError,
    V2Frame,
    V2FrameValidationError,
    decode_compatible_frame,
    decode_v2_configuration,
    decode_v2_frame,
    select_protocol_version,
    validate_v2_configuration_echo,
)

REPOSITORY_ROOT = Path(__file__).resolve().parents[2]
V1_CONTRACT_PATH = REPOSITORY_ROOT / "protocol/protocol-v1.json"
V2_CONTRACT_PATH = REPOSITORY_ROOT / "protocol/protocol-v2.json"
V1_FIXTURE_DIRECTORY = REPOSITORY_ROOT / "protocol/fixtures"
FIXTURE_DIRECTORY = REPOSITORY_ROOT / "protocol/fixtures-v2"
MANIFEST_PATH = FIXTURE_DIRECTORY / "manifest.json"
GENERATOR_PATH = REPOSITORY_ROOT / "tools/generate_protocol.py"
CPP_PATH = REPOSITORY_ROOT / "firmware/src/generated/protocol_v2_constants.h"

GENERATOR_SPEC = importlib.util.spec_from_file_location(
    "generate_aux_input_protocol_vector_test",
    GENERATOR_PATH,
)
assert GENERATOR_SPEC is not None and GENERATOR_SPEC.loader is not None
generate_protocol = importlib.util.module_from_spec(GENERATOR_SPEC)
GENERATOR_SPEC.loader.exec_module(generate_protocol)

_HEADER = struct.Struct("<IBBHHBBIIIIIQI")
_TRAILER = struct.Struct("<I")
_CONFIGURE_REQUEST = struct.Struct("<BBBBIII")
_CONFIGURE_RESPONSE = struct.Struct("<BBHBBBBIII")
_FROZEN_V1_SHA256 = {
    "protocol/protocol-v1.json": (
        "014648d18828c07fd2c8af16c430134bc28c4988d5b95d39613114f35623f222"
    ),
    "protocol/fixtures/manifest.json": (
        "e354b6dd7749b4dcea9ee233297f5712f645c2d0a1444d990e22f02303c99568"
    ),
    "daq_api/src/thingdaq/_generated/protocol_constants.py": (
        "a5dc4cd73dd12e291c03d536c2937d14ad1d0ca84b9c8a2860ad2797fbf15961"
    ),
    "firmware/src/generated/protocol_constants.h": (
        "9604390433f7d8227432d341ecc65b9292002797da9457937ed4d5d3cc096290"
    ),
}


def _fixture(name: str) -> bytes:
    return (FIXTURE_DIRECTORY / f"{name}.bin").read_bytes()


def _reference_checksum(frame_without_trailer: bytes, algorithm: str) -> int:
    if algorithm == "ADLER32":
        return zlib.adler32(frame_without_trailer) & 0xFFFFFFFF
    if algorithm == "CRC32_ISO_HDLC":
        return zlib.crc32(frame_without_trailer) & 0xFFFFFFFF
    if algorithm == "CRC32C":
        remainder = 0xFFFFFFFF
        for value in frame_without_trailer:
            remainder ^= value
            for _ in range(8):
                remainder = (remainder >> 1) ^ (0x82F63B78 if remainder & 1 else 0)
        return remainder ^ 0xFFFFFFFF
    raise AssertionError(f"unexpected checksum algorithm {algorithm}")


def _partition(data: bytes, seed: int) -> tuple[bytes, ...]:
    randomizer = random.Random(seed)
    chunks: list[bytes] = []
    offset = 0
    while offset < len(data):
        size = randomizer.randint(1, min(701, len(data) - offset))
        chunks.append(data[offset : offset + size])
        offset += size
    return tuple(chunks)


def _u16(payload: bytes, offset: int) -> int:
    return int(struct.unpack_from("<H", payload, offset)[0])


def _u32(payload: bytes, offset: int) -> int:
    return int(struct.unpack_from("<I", payload, offset)[0])


class AuxiliaryInputProtocolV2VectorTests(unittest.TestCase):
    contract: ClassVar[dict[str, Any]]
    manifest: ClassVar[dict[str, Any]]
    entries: ClassVar[dict[str, dict[str, Any]]]

    @classmethod
    def setUpClass(cls) -> None:
        cls.contract = json.loads(V2_CONTRACT_PATH.read_text(encoding="utf-8"))
        cls.manifest = json.loads(MANIFEST_PATH.read_text(encoding="utf-8"))
        cls.entries = {str(entry["file"]): entry for entry in cls.manifest["fixtures"]}

    def test_both_versions_generate_deterministically_to_disjoint_paths(self) -> None:
        v1_contract, v1_source = generate_protocol.load_contract(V1_CONTRACT_PATH)
        v2_contract, v2_source = generate_protocol.load_contract(V2_CONTRACT_PATH)
        generate_protocol.validate_contract(v1_contract)
        generate_protocol.validate_v2_contract(v2_contract, v1_contract, v1_source)

        v1_first = generate_protocol.expected_outputs(v1_contract, v1_source)
        v1_second = generate_protocol.expected_outputs(v1_contract, v1_source)
        v2_first = generate_protocol.expected_v2_outputs(v2_contract, v2_source)
        v2_second = generate_protocol.expected_v2_outputs(v2_contract, v2_source)
        combined = generate_protocol.expected_all_outputs(
            v1_contract,
            v1_source,
            v2_contract,
            v2_source,
        )

        self.assertEqual(v1_first, v1_second)
        self.assertEqual(v2_first, v2_second)
        self.assertEqual(26, len(v1_first))
        self.assertEqual(75, len(v2_first))
        self.assertEqual(101, len(combined))
        self.assertTrue(set(v1_first).isdisjoint(v2_first))
        for path, expected in combined.items():
            with self.subTest(path=path.relative_to(REPOSITORY_ROOT)):
                self.assertTrue(path.is_file())
                self.assertEqual(expected, path.read_bytes())
        for fixture_directory, outputs in (
            (V1_FIXTURE_DIRECTORY, v1_first),
            (FIXTURE_DIRECTORY, v2_first),
        ):
            expected_fixtures = {
                path
                for path in outputs
                if path.parent == fixture_directory and path.suffix == ".bin"
            }
            self.assertEqual(
                expected_fixtures,
                set(fixture_directory.glob("*.bin")),
            )

    def test_original_v1_contract_constants_and_fixtures_are_frozen(self) -> None:
        for relative_path, expected_sha256 in _FROZEN_V1_SHA256.items():
            with self.subTest(path=relative_path):
                contents = (REPOSITORY_ROOT / relative_path).read_bytes()
                self.assertEqual(
                    expected_sha256,
                    hashlib.sha256(contents).hexdigest(),
                )
        v1_manifest = json.loads(
            (V1_FIXTURE_DIRECTORY / "manifest.json").read_text(encoding="utf-8")
        )
        self.assertEqual(23, len(v1_manifest["fixtures"]))
        for entry in v1_manifest["fixtures"]:
            frame = (V1_FIXTURE_DIRECTORY / entry["file"]).read_bytes()
            with self.subTest(fixture=entry["file"]):
                self.assertEqual(
                    entry["frame_sha256"], hashlib.sha256(frame).hexdigest()
                )

    def test_generated_python_cpp_and_manifest_pin_the_v2_contract(self) -> None:
        source_sha256 = hashlib.sha256(V2_CONTRACT_PATH.read_bytes()).hexdigest()
        cpp = CPP_PATH.read_text(encoding="utf-8")
        self.assertEqual(source_sha256, constants.SOURCE_SHA256)
        self.assertEqual(source_sha256, self.manifest["source_sha256"])
        self.assertEqual(
            _FROZEN_V1_SHA256["protocol/protocol-v1.json"],
            self.manifest["v1_source_sha256"],
        )
        self.assertIn(f"Source SHA-256: {source_sha256}", cpp)
        self.assertIn("namespace thingdaq::protocol_v2", cpp)
        self.assertIn("enum class AuxBankMode", cpp)
        self.assertIn("enum class RateProfile", cpp)
        self.assertIn("inline constexpr RateProfileTiming kRateProfiles[]", cpp)
        self.assertEqual(2, constants.PROTOCOL_VERSION)
        self.assertEqual(16, constants.CONFIGURE_REQUEST_PAYLOAD_SIZE)
        self.assertEqual(20, constants.CONFIGURE_RESPONSE_PAYLOAD_SIZE)
        self.assertEqual(632, constants.INFO_RESPONSE_PAYLOAD_SIZE)
        self.assertEqual(1476, constants.STATUS_RESPONSE_PAYLOAD_SIZE)
        self.assertEqual(272, constants.GPIO_CAPTURE_DIAGNOSTIC_RESPONSE_PAYLOAD_SIZE)
        self.assertEqual(
            (6, 7, 8, 9, 10, 11, 12, 13), constants.PRIMARY_GPIO_PINS_BY_BIT
        )
        self.assertEqual(tuple(range(16, 24)), constants.AUX_GPIO_PINS_BY_BIT)
        self.assertEqual(0x0FC30000, constants.AUX_GPIO_CAPTURE_MASK)
        self.assertEqual(3, constants.AUX_GPIO_EDMA_CHANNEL)

    def test_every_fixture_has_an_independently_valid_envelope_and_hash(self) -> None:
        self.assertEqual(constants.HEADER_SIZE, _HEADER.size)
        self.assertEqual(72, len(self.manifest["fixtures"]))
        self.assertEqual(
            set(self.entries),
            {path.name for path in FIXTURE_DIRECTORY.glob("*.bin")},
        )
        kind_values = {
            entry["name"]: int(entry["value"]) for entry in self.contract["frame_kinds"]
        }
        for entry in self.manifest["fixtures"]:
            frame = (FIXTURE_DIRECTORY / entry["file"]).read_bytes()
            fields = _HEADER.unpack_from(frame)
            checksum = _TRAILER.unpack_from(frame, len(frame) - _TRAILER.size)[0]
            with self.subTest(fixture=entry["file"]):
                self.assertEqual(0xDEADBEEF, fields[0])
                self.assertEqual(2, fields[1])
                self.assertEqual(kind_values[entry["kind"]], fields[2])
                self.assertEqual(44, fields[4])
                self.assertEqual(0, fields[6])
                self.assertEqual(len(frame), fields[7])
                self.assertEqual(len(frame) - 48, fields[8])
                self.assertEqual(entry["run_id"], fields[9])
                self.assertEqual(entry["sequence"], fields[10])
                self.assertEqual(entry["request_id"], fields[11])
                self.assertEqual(entry["first_sample_ticks"], fields[12])
                self.assertEqual(entry["item_count"], fields[13])
                self.assertEqual(
                    entry["frame_sha256"], hashlib.sha256(frame).hexdigest()
                )
                self.assertEqual(
                    entry["payload_sha256"],
                    hashlib.sha256(frame[44:-4]).hexdigest(),
                )
                self.assertEqual(
                    _reference_checksum(frame[:-4], entry["checksum_algorithm"]),
                    checksum,
                )

    def test_gpio_width_and_rate_matrix_has_exact_little_endian_samples(self) -> None:
        entries = [
            entry
            for entry in self.manifest["fixtures"]
            if entry.get("case") == "gpio-mode-profile-matrix"
        ]
        self.assertEqual(8, len(entries))
        self.assertEqual(
            {
                (mode.name, profile.name)
                for mode in constants.AuxBankMode
                for profile in constants.RateProfile
            },
            {(entry["aux_bank_mode"], entry["rate_profile"]) for entry in entries},
        )
        for entry in entries:
            frame = decode_v2_frame((FIXTURE_DIRECTORY / entry["file"]).read_bytes())
            mode = constants.AuxBankMode[entry["aux_bank_mode"]]
            profile = constants.RateProfile[entry["rate_profile"]]
            layout = constants.AUX_BANK_LAYOUTS[mode]
            start = 17 * int(profile)
            with self.subTest(mode=mode.name, profile=profile.name):
                self.assertEqual(
                    layout["gpio_items_per_frame"], frame.header.item_count
                )
                self.assertEqual(layout["gpio_payload_bytes"], len(frame.payload))
                if mode is constants.AuxBankMode.DISABLED:
                    expected = bytes(
                        (start + index) & 0xFF
                        for index in range(layout["gpio_items_per_frame"])
                    )
                else:
                    expected = b"".join(
                        struct.pack(
                            "<H",
                            ((0x80 + 3 * (start + index)) & 0xFF) << 8
                            | ((start + index) & 0xFF),
                        )
                        for index in range(layout["gpio_items_per_frame"])
                    )
                    self.assertEqual(
                        (start & 0xFF) | (((0x80 + 3 * start) & 0xFF) << 8),
                        _u16(frame.payload, 0),
                    )
                self.assertEqual(expected, frame.payload)

    def test_extended_configure_matrix_pins_modes_rates_and_applied_echoes(
        self,
    ) -> None:
        requests = [
            entry
            for entry in self.manifest["fixtures"]
            if entry.get("case") == "configure-mode-profile-matrix"
            and entry["kind"] == "CONFIGURE_REQUEST"
        ]
        self.assertEqual(8, len(requests))
        for request_entry in requests:
            request = decode_v2_frame(
                (FIXTURE_DIRECTORY / request_entry["file"]).read_bytes()
            )
            response_name = request_entry["file"].replace(
                "-request.bin", "-response.bin"
            )
            response = decode_v2_frame((FIXTURE_DIRECTORY / response_name).read_bytes())
            requested = decode_v2_configuration(request.payload)
            applied = validate_v2_configuration_echo(request.payload, response.payload)
            mode = constants.AuxBankMode[request_entry["aux_bank_mode"]]
            profile = constants.RateProfile[request_entry["rate_profile"]]
            timing = constants.RATE_PROFILE_TIMING[profile]
            raw_request = _CONFIGURE_REQUEST.unpack(request.payload)
            raw_response = _CONFIGURE_RESPONSE.unpack(response.payload)
            with self.subTest(mode=mode.name, profile=profile.name):
                self.assertEqual(request.header.request_id, response.header.request_id)
                self.assertEqual(requested, applied)
                self.assertEqual(mode, requested.aux_bank_mode)
                self.assertEqual(profile, requested.rate_profile)
                self.assertEqual(timing["adc_pair_rate_hz"], requested.adc_pair_rate_hz)
                self.assertEqual(
                    timing["gpio_sample_rate_hz"], requested.gpio_sample_rate_hz
                )
                self.assertEqual(int(mode), raw_request[3])
                self.assertEqual(constants.DATA_FRAME_BYTES, raw_request[4])
                self.assertEqual((0, 0, 0), raw_response[:3])
                self.assertEqual(raw_request, raw_response[3:])

    def test_info_matrix_exposes_exact_layout_timing_maps_and_resources(self) -> None:
        entries = [
            entry
            for entry in self.manifest["fixtures"]
            if entry.get("case") == "info-mode-profile-matrix"
        ]
        self.assertEqual(8, len(entries))
        for entry in entries:
            frame = decode_v2_frame((FIXTURE_DIRECTORY / entry["file"]).read_bytes())
            payload = frame.payload
            mode = constants.AuxBankMode[entry["aux_bank_mode"]]
            profile = constants.RateProfile[entry["rate_profile"]]
            layout = constants.AUX_BANK_LAYOUTS[mode]
            timing = constants.RATE_PROFILE_TIMING[profile]
            with self.subTest(mode=mode.name, profile=profile.name):
                self.assertEqual(
                    int(mode),
                    payload[constants.INFO_RESPONSE_APPLIED_AUX_BANK_MODE_OFFSET],
                )
                self.assertEqual(
                    int(profile),
                    payload[constants.INFO_RESPONSE_SELECTED_RATE_PROFILE_OFFSET],
                )
                self.assertEqual(
                    layout["gpio_width_bits"],
                    payload[constants.INFO_RESPONSE_GPIO_PACKED_WIDTH_BITS_OFFSET],
                )
                self.assertEqual(
                    layout["gpio_bytes_per_item"],
                    payload[constants.INFO_RESPONSE_GPIO_ITEM_BYTES_OFFSET],
                )
                self.assertEqual(
                    layout["adc_items_per_frame"],
                    _u16(payload, constants.INFO_RESPONSE_ADC_PAIRS_PER_FRAME_OFFSET),
                )
                self.assertEqual(
                    layout["gpio_items_per_frame"],
                    _u16(
                        payload, constants.INFO_RESPONSE_GPIO_SAMPLES_PER_FRAME_OFFSET
                    ),
                )
                self.assertEqual(
                    timing["adc_pair_rate_hz"],
                    _u32(payload, constants.INFO_RESPONSE_ADC_PAIR_RATE_HZ_OFFSET),
                )
                self.assertEqual(
                    timing["gpio_sample_rate_hz"],
                    _u32(payload, constants.INFO_RESPONSE_GPIO_SAMPLE_RATE_HZ_OFFSET),
                )
                self.assertEqual(
                    constants.PRIMARY_GPIO_PINS_BY_BIT,
                    tuple(
                        payload[
                            constants.INFO_RESPONSE_GPIO_PIN_MAP_OFFSET : constants.INFO_RESPONSE_GPIO_PIN_MAP_OFFSET
                            + 8
                        ]
                    ),
                )
                self.assertEqual(
                    constants.AUX_GPIO_PINS_BY_BIT,
                    tuple(
                        payload[
                            constants.INFO_RESPONSE_AUX_GPIO_PIN_MAP_OFFSET : constants.INFO_RESPONSE_AUX_GPIO_PIN_MAP_OFFSET
                            + 8
                        ]
                    ),
                )
                self.assertEqual(
                    constants.AUX_GPIO_CAPTURE_MASK,
                    _u32(payload, constants.INFO_RESPONSE_AUX_GPIO_CAPTURE_MASK_OFFSET),
                )
                self.assertEqual(
                    constants.AUX_GPIO_EDMA_CHANNEL,
                    payload[constants.INFO_RESPONSE_AUX_GPIO_EDMA_CHANNEL_OFFSET],
                )
                self.assertEqual(
                    constants.AUX_GPIO_DMAMUX_SOURCE,
                    payload[constants.INFO_RESPONSE_AUX_GPIO_DMAMUX_SOURCE_OFFSET],
                )
                self.assertEqual(
                    constants.AUX_GPIO_XBAR_OUTPUT,
                    payload[constants.INFO_RESPONSE_AUX_GPIO_XBAR_OUTPUT_OFFSET],
                )
                self.assertEqual(
                    1, payload[constants.INFO_RESPONSE_PAIRED_GPIO_JOIN_REQUIRED_OFFSET]
                )

        representative = decode_v2_frame(
            _fixture("info-input-adc-500khz-gpio-2mhz-response")
        ).payload
        for index, profile in enumerate(constants.RateProfile):
            base = constants.INFO_RESPONSE_RATE_PROFILES_OFFSET + (
                index * constants.RATE_PROFILE_INFO_PAYLOAD_SIZE
            )
            timing = constants.RATE_PROFILE_TIMING[profile]
            with self.subTest(profile_table=profile.name):
                self.assertEqual(int(profile), representative[base])
                self.assertEqual(
                    timing["adc_pair_rate_hz"],
                    _u32(
                        representative,
                        base + constants.RATE_PROFILE_INFO_ADC_PAIR_RATE_HZ_OFFSET,
                    ),
                )
                self.assertEqual(
                    timing["gpio_sample_rate_hz"],
                    _u32(
                        representative,
                        base + constants.RATE_PROFILE_INFO_GPIO_SAMPLE_RATE_HZ_OFFSET,
                    ),
                )
                self.assertEqual(
                    timing["adc1_phase_ipg_cycles"],
                    _u16(
                        representative,
                        base + constants.RATE_PROFILE_INFO_ADC1_PHASE_IPG_CYCLES_OFFSET,
                    ),
                )
                self.assertEqual(
                    timing["completion_expected_dwt_cycles"],
                    _u32(
                        representative,
                        base
                        + constants.RATE_PROFILE_INFO_COMPLETION_EXPECTED_DWT_CYCLES_OFFSET,
                    ),
                )

    def test_extended_status_and_idle_diagnostic_are_typed_host_evidence(
        self,
    ) -> None:
        status_frame = decode_v2_frame(_fixture("get-status-response"))
        status = Status.from_payload(status_frame.payload)
        self.assertIsNotNone(status.configuration)
        self.assertIsNotNone(status.auxiliary_gpio)
        assert status.configuration is not None
        assert status.auxiliary_gpio is not None
        self.assertIs(
            constants.AuxBankMode.DISABLED, status.configuration.aux_bank_mode
        )
        self.assertIs(
            constants.RateProfile.ADC_1MHZ_GPIO_4MHZ,
            status.configuration.rate_profile,
        )
        self.assertEqual(1, status.auxiliary_gpio.gpio_item_bytes)
        self.assertEqual(101_200, status.auxiliary_gpio.packet_retention_us_combined)
        self.assertEqual(
            202_400, status.auxiliary_gpio.packet_retention_us_single_stream
        )
        self.assertEqual((0, 0), status.auxiliary_gpio.bank_ring_overruns)
        self.assertEqual((0, 0), status.auxiliary_gpio.bank_stale_completions)

        diagnostic_frame = decode_v2_frame(_fixture("gpio-capture-diagnostic-response"))
        diagnostic = GpioCaptureDiagnosticResult.from_payload(diagnostic_frame.payload)
        self.assertEqual(2, diagnostic.bank_count)
        self.assertIs(constants.AuxBankMode.INPUT, diagnostic.aux_bank_mode)
        self.assertEqual(2_031, diagnostic.aux_dma_samples_captured)
        self.assertEqual((8, 8), diagnostic.cache_dma_discards)
        self.assertTrue(diagnostic.aux_electrically_unstimulated)
        self.assertFalse(diagnostic.aux_external_transition_checks_run)

    def test_all_semantic_rejections_and_error_responses_are_explicit(self) -> None:
        rejected = [
            entry
            for entry in self.manifest["fixtures"]
            if entry["expectation"] == "reject"
        ]
        error_responses = [
            entry
            for entry in self.manifest["fixtures"]
            if entry["expectation"] == "accept-error"
        ]
        self.assertEqual(9, len(rejected))
        self.assertEqual(5, len(error_responses))
        self.assertEqual(
            {
                "unsupported-rates",
                "wrong-four-to-one-ratio",
                "mixed-bank-mode",
                "output-bank-mode",
                "nonintegral-timestamps",
                "duplicate-aux-pins",
                "bad-gpio-width",
                "bad-frame-counts",
                "nonintegral-profile-metadata",
            },
            {entry["case"] for entry in rejected},
        )
        for entry in rejected:
            with self.subTest(fixture=entry["file"]):
                with self.assertRaises(V2FrameValidationError) as captured:
                    decode_v2_frame((FIXTURE_DIRECTORY / entry["file"]).read_bytes())
                self.assertEqual(entry["expected_rejection"], captured.exception.reason)
        for entry in error_responses:
            frame = decode_v2_frame((FIXTURE_DIRECTORY / entry["file"]).read_bytes())
            status, reserved, error_code = struct.unpack("<BBH", frame.payload)
            with self.subTest(fixture=entry["file"]):
                self.assertEqual(1, status)
                self.assertEqual(0, reserved)
                self.assertEqual(
                    int(constants.ErrorCode[entry["expected_error_code"]]),
                    error_code,
                )

    def test_contradictory_applied_echo_is_rejected_only_after_correlation(
        self,
    ) -> None:
        entry = self.entries[
            "malformed-contradictory-configure-echo-configure-response.bin"
        ]
        request = decode_v2_frame(_fixture(entry["correlates_to"]))
        response = decode_v2_frame((FIXTURE_DIRECTORY / entry["file"]).read_bytes())
        self.assertEqual("reject-client", entry["expectation"])
        with self.assertRaises(V2ConfigurationEchoError) as captured:
            validate_v2_configuration_echo(request.payload, response.payload)
        self.assertEqual(entry["expected_rejection"], captured.exception.reason)

    def test_v2_parser_is_bounded_under_fragmentation_and_recovers(self) -> None:
        accepted = tuple(
            (FIXTURE_DIRECTORY / entry["file"]).read_bytes()
            for entry in self.manifest["fixtures"]
            if entry["expectation"] in {"accept", "accept-error", "reject-client"}
        )
        stream = b"".join(accepted)
        for seed in (0, 19, 65_537):
            parser = IncrementalV2FrameParser()
            decoded: list[V2Frame] = []
            for chunk in _partition(stream, seed):
                decoded.extend(parser.feed(chunk))
                self.assertLessEqual(parser.buffered_bytes, MAX_V2_BUFFERED_BYTES)
                self.assertLessEqual(parser.high_water_mark, MAX_V2_BUFFERED_BYTES)
            with self.subTest(seed=seed):
                self.assertEqual(accepted, tuple(frame.to_bytes() for frame in decoded))
                self.assertEqual(0, parser.corruption_events)
                self.assertEqual(0, parser.buffered_bytes)

        sentinel = _fixture("ping-request")
        for entry in self.manifest["fixtures"]:
            if entry["expectation"] != "reject":
                continue
            malformed = (FIXTURE_DIRECTORY / entry["file"]).read_bytes()
            parser = IncrementalV2FrameParser()
            decoded = []
            for chunk in _partition(malformed + sentinel, 7):
                decoded.extend(parser.feed(chunk))
            with self.subTest(recovery=entry["file"]):
                self.assertEqual([sentinel], [frame.to_bytes() for frame in decoded])
                self.assertGreater(parser.corruption_events, 0)
                self.assertLessEqual(parser.high_water_mark, MAX_V2_BUFFERED_BYTES)

        corrupted = bytearray(_fixture("gpio-16bit-adc-1mhz-gpio-4mhz"))
        corrupted[constants.HEADER_SIZE + 31] ^= 0x80
        parser = IncrementalV2FrameParser()
        decoded = parser.feed(corrupted + sentinel)
        self.assertEqual([sentinel], [frame.to_bytes() for frame in decoded])
        self.assertEqual(1, parser.checksum_errors)
        self.assertEqual(0, parser.buffered_bytes)

    def test_version_selection_and_compatible_decoder_preserve_v1_fallback(
        self,
    ) -> None:
        self.assertEqual(1, select_protocol_version())
        self.assertEqual(
            2,
            select_protocol_version(aux_bank_mode=constants.AuxBankMode.INPUT),
        )
        self.assertEqual(
            2,
            select_protocol_version(
                adc_pair_rate_hz=500_000,
                gpio_sample_rate_hz=2_000_000,
            ),
        )
        with self.assertRaisesRegex(TypeError, "auxiliary bank mode"):
            select_protocol_version(aux_bank_mode=True)
        with self.assertRaises(V2FrameValidationError) as captured:
            select_protocol_version(
                adc_pair_rate_hz=300_000,
                gpio_sample_rate_hz=1_200_000,
            )
        self.assertEqual("nonintegral_timestamps", captured.exception.reason)

        v1_wire = (V1_FIXTURE_DIRECTORY / "ping-request.bin").read_bytes()
        v2_wire = _fixture("ping-request")
        v1_frame = decode_compatible_frame(v1_wire)
        v2_frame = decode_compatible_frame(v2_wire)
        self.assertIsInstance(v1_frame, V1Frame)
        self.assertIsInstance(v2_frame, V2Frame)
        self.assertEqual(v1_wire, v1_frame.to_bytes())
        self.assertEqual(v2_wire, v2_frame.to_bytes())
        self.assertEqual(v1_constants.PROTOCOL_VERSION, v1_frame.header.version)
        self.assertEqual(constants.PROTOCOL_VERSION, v2_frame.header.version)
        self.assertIs(decode_compatible_frame, low_level.decode_compatible_frame)
        self.assertIs(constants, low_level.protocol_v2_constants)

        with ThingDAQ.simulated(control_only=True) as daq:
            self.assertEqual(v1_constants.PROTOCOL_VERSION, daq.info().protocol_version)


if __name__ == "__main__":
    unittest.main()
