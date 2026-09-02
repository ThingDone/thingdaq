"""Portable unit checks for the standalone protocol-v2 RLE rig."""

from __future__ import annotations

import ast
import importlib.util
import json
import os
import struct
import sys
import unittest
from pathlib import Path
from unittest import mock

REPOSITORY_ROOT = Path(__file__).resolve().parents[2]
RIG_PATH = REPOSITORY_ROOT / "firmware/tests/rig_rle_streaming.py"
CONTRACT_PATH = REPOSITORY_ROOT / "protocol/protocol-v2.json"


def _load_rig():
    spec = importlib.util.spec_from_file_location("thingdaq_rle_rig_test", RIG_PATH)
    if spec is None or spec.loader is None:  # pragma: no cover - import invariant
        raise RuntimeError("could not load RLE rig")
    module = importlib.util.module_from_spec(spec)
    sys.modules[spec.name] = module
    spec.loader.exec_module(module)
    return module


rig = _load_rig()


def _device_frame(
    *,
    kind: int,
    payload: bytes,
    encoding: int,
    item_count: int,
    checksum_valid: bool = True,
) -> bytes:
    total_length = rig.HEADER_SIZE + len(payload) + rig.TRAILER_SIZE
    header = rig.HEADER.pack(
        rig.MAGIC,
        rig.PROTOCOL_V2,
        kind,
        rig.FLAG_SYNTHETIC | rig.FLAG_EPOCH_START,
        rig.HEADER_SIZE,
        rig.CHECKSUM_ADLER32,
        encoding,
        total_length,
        len(payload),
        7,
        0,
        0,
        0,
        item_count,
    )
    body = header + payload
    checksum = rig.compute_checksum(body, rig.CHECKSUM_ADLER32)
    if not checksum_valid:
        checksum ^= 1
    return body + rig.TRAILER.pack(checksum)


def _constant_capture() -> object:
    capture = rig.CaptureValidator("constant", rig.CONFIGURATION_ENCODING_RLE_AUTO)
    adc_item = rig.logical_item("constant", rig.ADC_DATA, 0)
    adc_payload = struct.pack("<H", rig.ADC_PAIRS_PER_FRAME) + adc_item
    capture.observe(
        rig.Frame(
            version=rig.PROTOCOL_V2,
            kind=rig.ADC_DATA,
            flags=rig.FLAG_SYNTHETIC | rig.FLAG_EPOCH_START,
            checksum_algorithm=rig.CHECKSUM_ADLER32,
            encoding=rig.FRAME_ENCODING_RLE,
            total_length=rig.HEADER_SIZE + len(adc_payload) + rig.TRAILER_SIZE,
            run_id=7,
            sequence=0,
            request_id=0,
            first_sample_ticks=0,
            item_count=rig.ADC_PAIRS_PER_FRAME,
            payload=adc_payload,
            checksum=0,
            run_count=1,
        )
    )
    gpio_payload = rig.fixed_payload("constant", rig.GPIO_DATA)
    assert gpio_payload is not None
    capture.observe(
        rig.Frame(
            version=rig.PROTOCOL_V2,
            kind=rig.GPIO_DATA,
            flags=rig.FLAG_SYNTHETIC | rig.FLAG_EPOCH_START,
            checksum_algorithm=rig.CHECKSUM_ADLER32,
            encoding=rig.FRAME_ENCODING_RAW,
            total_length=rig.DATA_FRAME_BYTES,
            run_id=7,
            sequence=0,
            request_id=0,
            first_sample_ticks=0,
            item_count=rig.GPIO_SAMPLES_PER_FRAME,
            payload=gpio_payload,
            checksum=0,
        )
    )
    return capture


class RLEStreamingRigTests(unittest.TestCase):
    def test_runner_is_self_contained_and_status_layout_matches_contract(self) -> None:
        source = RIG_PATH.read_text(encoding="utf-8")
        tree = ast.parse(source)
        imported_roots = {
            alias.name.split(".", 1)[0]
            for node in ast.walk(tree)
            if isinstance(node, ast.Import)
            for alias in node.names
        }
        imported_roots.update(
            node.module.split(".", 1)[0]
            for node in ast.walk(tree)
            if isinstance(node, ast.ImportFrom) and node.module
        )
        self.assertNotIn("thingdaq", imported_roots)
        self.assertEqual({"serial"}, imported_roots - set(sys.stdlib_module_names))

        contract = json.loads(CONTRACT_PATH.read_text(encoding="utf-8"))
        fields = contract["payload_schemas"]["status_response"]["fields"]
        expected = {
            name: (rig._SCALAR_FORMAT[field["type"]], field["offset"])
            for name, field in ((field["name"], field) for field in fields)
        }
        self.assertEqual(expected, rig.STATUS_FIELDS)
        self.assertIn("finally:\n        cleanup_to_idle", source)

    def test_v1_and_v2_controls_are_encoded_independently(self) -> None:
        for version in (rig.PROTOCOL_V1, rig.PROTOCOL_V2):
            with self.subTest(version=version):
                wire = rig.encode_control(version, rig.INFO_REQUEST, 9)
                header = rig.HEADER.unpack_from(wire)
                self.assertEqual(version, header[1])
                self.assertEqual(rig.FRAME_ENCODING_RAW, header[6])
                self.assertEqual(
                    rig.compute_checksum(wire[:-4], rig.BOOTSTRAP_CHECKSUM),
                    rig.TRAILER.unpack_from(wire, len(wire) - 4)[0],
                )

        payload = rig.CONFIGURATION.pack(
            rig.STREAM_BOTH,
            rig.SOURCE_SYNTHETIC_CONSTANT,
            rig.CHECKSUM_ADLER32,
            rig.CONFIGURATION_ENCODING_RLE_AUTO,
            rig.DATA_FRAME_BYTES,
        )
        with self.assertRaisesRegex(ValueError, "protocol v1"):
            rig.encode_control(rig.PROTOCOL_V1, rig.CONFIGURE_REQUEST, 10, payload)
        wire = rig.encode_control(rig.PROTOCOL_V2, rig.CONFIGURE_REQUEST, 10, payload)
        self.assertEqual(rig.PROTOCOL_V2, rig.HEADER.unpack_from(wire)[1])

    def test_checksum_is_rejected_before_zero_run_is_inspected(self) -> None:
        invalid_rle = b"\x00\x00" + rig.logical_item("constant", rig.ADC_DATA, 0)
        bad_checksum = _device_frame(
            kind=rig.ADC_DATA,
            payload=invalid_rle,
            encoding=rig.FRAME_ENCODING_RLE,
            item_count=rig.ADC_PAIRS_PER_FRAME,
            checksum_valid=False,
        )
        with self.assertRaisesRegex(rig.CodecFailure, "checksum mismatch"):
            rig.FrameParser(strict=True).feed(bad_checksum)

        valid_checksum = _device_frame(
            kind=rig.ADC_DATA,
            payload=invalid_rle,
            encoding=rig.FRAME_ENCODING_RLE,
            item_count=rig.ADC_PAIRS_PER_FRAME,
        )
        with self.assertRaisesRegex(rig.CodecFailure, "run length is zero"):
            rig.FrameParser(strict=True).feed(valid_checksum)

    def test_validator_accepts_legal_mixed_raw_and_rle_frames(self) -> None:
        capture = _constant_capture()
        combined = capture.combined_summary()
        self.assertEqual(2, combined["frames"])
        self.assertEqual(1, combined["raw_frames"])
        self.assertEqual(1, combined["rle_frames"])
        self.assertEqual(1, combined["rle_runs"])
        self.assertLess(combined["encoded_payload_ratio"], 1.0)

    def test_target_formulas_cover_transition_and_mixer_boundaries(self) -> None:
        self.assertEqual(
            bytes.fromhex("5e"),
            rig.logical_item("incompressible", rig.GPIO_DATA, 0),
        )
        adc0, adc1 = struct.unpack(
            "<HH", rig.logical_item("incompressible", rig.ADC_DATA, 0)
        )
        self.assertEqual(0xF0E, adc0)
        self.assertEqual(0xC22, adc1)
        self.assertNotEqual(
            rig.logical_item("sparse-hold", rig.ADC_DATA, 996),
            rig.logical_item("sparse-hold", rig.ADC_DATA, 997),
        )
        self.assertEqual(
            1,
            rig.expected_run_length(
                "sparse-hold", rig.ADC_DATA, 996, rig.ADC_PAIRS_PER_FRAME
            ),
        )
        self.assertEqual(
            8,
            rig.expected_run_length("slow-adc", rig.ADC_DATA, 0, 100),
        )

    def test_final_status_reconciles_raw_rle_bytes_runs_and_fallbacks(self) -> None:
        capture = _constant_capture()
        values = {name: 0 for name in rig.STATUS_FIELDS}
        values.update(
            {
                "device_state": rig.STATE_IDLE,
                "source": rig.SOURCE_HARDWARE,
                "data_checksum_algorithm": rig.CHECKSUM_ADLER32,
                "data_frame_bytes": rig.DATA_FRAME_BYTES,
                "stats_generation": 3,
                "configuration_encoding": rig.CONFIGURATION_ENCODING_RAW,
                "temporary_page_high_water": 1,
            }
        )
        combined_frames = 0
        combined_logical = 0
        combined_wire = 0
        for metrics in capture.streams.values():
            prefix = metrics.name
            logical = metrics.frames * rig.DATA_PAYLOAD_BYTES
            combined_frames += metrics.frames
            combined_logical += logical
            combined_wire += metrics.framed_bytes
            values.update(
                {
                    f"{prefix}_frames_generated": metrics.frames,
                    f"{prefix}_frames_framed_pipeline": metrics.frames,
                    f"{prefix}_frames_emitted": metrics.frames,
                    f"{prefix}_frames_transmitted": metrics.frames,
                    f"{prefix}_items_generated": metrics.logical_items,
                    f"{prefix}_items_framed_pipeline": metrics.logical_items,
                    f"{prefix}_items_emitted": metrics.logical_items,
                    f"{prefix}_items_transmitted_pipeline": metrics.logical_items,
                    f"{prefix}_payload_bytes_produced": logical,
                    f"{prefix}_payload_bytes_framed": logical,
                    f"{prefix}_payload_bytes_emitted": logical,
                    f"{prefix}_payload_bytes_transmitted": logical,
                    f"{prefix}_framed_bytes_framed": metrics.framed_bytes,
                    f"{prefix}_framed_bytes_emitted": metrics.framed_bytes,
                    f"{prefix}_framed_bytes_transmitted": metrics.framed_bytes,
                    f"{prefix}_encoded_payload_bytes_framed": (
                        metrics.encoded_payload_bytes
                    ),
                    f"{prefix}_encoded_payload_bytes_transmitted": (
                        metrics.encoded_payload_bytes
                    ),
                    f"{prefix}_raw_frames": metrics.raw_frames,
                    f"{prefix}_rle_frames": metrics.rle_frames,
                    f"{prefix}_rle_runs": metrics.rle_runs,
                    f"{prefix}_encode_cycles": 100,
                }
            )
            legacy_framed = (
                "adc_pairs_framed" if prefix == "adc" else "gpio_samples_framed"
            )
            legacy_transmitted = (
                "adc_pairs_transmitted"
                if prefix == "adc"
                else "gpio_samples_transmitted"
            )
            values[legacy_framed] = metrics.logical_items
            values[legacy_transmitted] = metrics.logical_items
            if metrics.raw_frames:
                values[f"{prefix}_fallback_frames"] = metrics.raw_frames
                values[f"{prefix}_fallback_not_smaller"] = metrics.raw_frames
        values["packet_frames_promoted"] = combined_frames
        values["data_payload_bytes_transmitted"] = combined_logical
        values["data_framed_bytes_transmitted"] = combined_wire

        result = rig.validate_final_accounting(
            rig.StatusSnapshot(values),
            capture,
            rig.CONFIGURATION_ENCODING_RLE_AUTO,
            1.0,
            100,
        )
        self.assertEqual(200, result["combined_encode_cycles"])
        self.assertEqual(2.0, result["encode_cpu_load_fraction"])
        self.assertEqual(1, result["streams"]["gpio"]["fallback_frames"])

    def test_smoke_and_endurance_bounds_fail_closed(self) -> None:
        base = {
            "SERIAL_PORT": "/dev/fake",
            "RLE_PATTERN": "constant",
        }
        with (
            mock.patch.dict(
                os.environ,
                {**base, "RLE_STREAMING_MODE": "smoke", "RLE_CAPTURE_SECONDS": "61"},
                clear=True,
            ),
            self.assertRaisesRegex(ValueError, "smoke capture"),
        ):
            rig.parse_configuration()
        with (
            mock.patch.dict(
                os.environ,
                {
                    **base,
                    "RLE_STREAMING_MODE": "endurance",
                    "RLE_CAPTURE_SECONDS": "599",
                },
                clear=True,
            ),
            self.assertRaisesRegex(ValueError, "at least 600"),
        ):
            rig.parse_configuration()


if __name__ == "__main__":
    unittest.main()
