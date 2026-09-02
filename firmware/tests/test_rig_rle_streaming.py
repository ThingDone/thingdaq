"""Portable unit checks for the standalone protocol-v2 RLE rig."""

from __future__ import annotations

import ast
import importlib.util
import io
import json
import os
import struct
import sys
import time
import unittest
from contextlib import redirect_stdout
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


def _campaign_wire_frame(
    *,
    version: int,
    kind: int,
    payload: bytes,
    request_id: int = 0,
    run_id: int = 0,
    sequence: int = 0,
    first_sample_ticks: int = 0,
    item_count: int = 0,
    flags: int = 0,
    checksum_algorithm: int = rig.BOOTSTRAP_CHECKSUM,
    encoding: int = rig.FRAME_ENCODING_RAW,
) -> bytes:
    total_length = rig.HEADER_SIZE + len(payload) + rig.TRAILER_SIZE
    header = rig.HEADER.pack(
        rig.MAGIC,
        version,
        kind,
        flags,
        rig.HEADER_SIZE,
        checksum_algorithm,
        encoding,
        total_length,
        len(payload),
        run_id,
        sequence,
        request_id,
        first_sample_ticks,
        item_count,
    )
    body = header + payload
    return body + rig.TRAILER.pack(rig.compute_checksum(body, checksum_algorithm))


class CampaignFakeSerial:
    """Stateful v1/v2 peer for full-program pattern and fault executions."""

    def __init__(self, pattern: str, fault: str | None = None) -> None:
        self.pattern = pattern
        self.fault = fault
        self.is_open = True
        self.closed = False
        self.state = rig.STATE_IDLE
        self.run_id = 73
        self.stats_generation = 1
        self.stream_mask = rig.STREAM_NONE
        self.source = rig.SOURCE_HARDWARE
        self.checksum = rig.CHECKSUM_ADLER32
        self.configuration_encoding = rig.CONFIGURATION_ENCODING_RAW
        self.pending = bytearray()
        self.requests = bytearray()
        self.read_pattern = (1, 7, 53, 4096, rig.SERIAL_READ_BYTES)
        self.write_pattern = (1, 0, 11, 64)
        self.read_index = 0
        self.write_index = 0
        self.read_counts: list[int] = []
        self.write_counts: list[int] = []
        self.generated_kinds: list[int] = []
        self.disconnected = False
        self.disconnect_when_empty = False
        self.ever_started = False
        self.metrics = {
            rig.ADC_DATA: self._empty_metrics(),
            rig.GPIO_DATA: self._empty_metrics(),
        }

    @staticmethod
    def _empty_metrics() -> dict[str, int]:
        return {
            "frames": 0,
            "items": 0,
            "encoded_payload": 0,
            "wire": 0,
            "raw_frames": 0,
            "rle_frames": 0,
            "runs": 0,
        }

    def read(self, size: int = 1) -> bytes:
        if not self.is_open:
            raise RuntimeError("fake serial port is closed")
        if self.disconnected:
            raise OSError("injected serial disconnect")
        if not self.pending and self.state == rig.STATE_RUNNING:
            self._queue_next_data_frame()
        if not self.pending:
            time.sleep(0.00005)
            self.read_counts.append(0)
            return b""
        limit = self.read_pattern[self.read_index % len(self.read_pattern)]
        self.read_index += 1
        count = min(size, limit, len(self.pending))
        result = bytes(self.pending[:count])
        del self.pending[:count]
        self.read_counts.append(count)
        if self.disconnect_when_empty and not self.pending:
            self.disconnected = True
        return result

    def write(self, data: bytes | bytearray | memoryview) -> int:
        if not self.is_open:
            raise RuntimeError("fake serial port is closed")
        if self.disconnected:
            raise OSError("injected serial disconnect")
        wire = bytes(data)
        limit = self.write_pattern[self.write_index % len(self.write_pattern)]
        self.write_index += 1
        count = min(len(wire), limit)
        self.write_counts.append(count)
        if count:
            self.requests.extend(wire[:count])
            self._consume_requests()
        return count

    def close(self) -> None:
        self.is_open = False
        self.closed = True

    def _consume_requests(self) -> None:
        while len(self.requests) >= rig.HEADER_SIZE:
            fields = rig.HEADER.unpack_from(self.requests)
            if fields[0] != rig.MAGIC or fields[4] != rig.HEADER_SIZE:
                raise AssertionError("fake received malformed request header")
            total_length = fields[7]
            if len(self.requests) < total_length:
                return
            request = bytes(self.requests[:total_length])
            del self.requests[:total_length]
            payload_end = total_length - rig.TRAILER_SIZE
            expected = rig.compute_checksum(request[:payload_end], fields[5])
            observed = rig.TRAILER.unpack_from(request, payload_end)[0]
            if expected != observed:
                raise AssertionError("fake received a bad request checksum")
            self._handle_request(
                version=fields[1],
                kind=fields[2],
                request_id=fields[11],
                payload=request[rig.HEADER_SIZE : payload_end],
            )

    def _handle_request(
        self, *, version: int, kind: int, request_id: int, payload: bytes
    ) -> None:
        response_kind = rig.REQUEST_RESPONSE_KIND[kind]
        run_id = self.run_id if self.ever_started else 0
        if kind == rig.INFO_REQUEST:
            response_payload = self._info_payload(version)
        elif kind == rig.RESET_STATS_REQUEST:
            self.stats_generation += 1
            self.metrics = {
                rig.ADC_DATA: self._empty_metrics(),
                rig.GPIO_DATA: self._empty_metrics(),
            }
            response_payload = bytearray(8)
            rig.RESPONSE_PREFIX.pack_into(response_payload, 0, 0, 0, 0)
            struct.pack_into("<I", response_payload, 4, self.stats_generation)
        elif kind == rig.CONFIGURE_REQUEST:
            (
                self.stream_mask,
                self.source,
                self.checksum,
                self.configuration_encoding,
                frame_bytes,
            ) = rig.CONFIGURATION.unpack(payload)
            if frame_bytes != rig.DATA_FRAME_BYTES:
                raise AssertionError("fake received a noncanonical frame size")
            self.state = rig.STATE_CONFIGURED
            response_payload = self._configuration_payload()
        elif kind == rig.START_REQUEST:
            self.state = rig.STATE_RUNNING
            self.ever_started = True
            run_id = self.run_id
            response_payload = self._configuration_payload()
        elif kind == rig.GET_STATUS_REQUEST:
            response_payload = self._status_payload(version)
        elif kind == rig.STOP_REQUEST:
            cleanup_refused = self.fault == "cleanup_failure" and self.ever_started
            if not cleanup_refused:
                self.state = rig.STATE_IDLE
                self.stream_mask = rig.STREAM_NONE
                self.source = rig.SOURCE_HARDWARE
                self.configuration_encoding = rig.CONFIGURATION_ENCODING_RAW
            response_payload = bytearray(8)
            rig.RESPONSE_PREFIX.pack_into(response_payload, 0, 0, 0, 0)
            response_payload[4] = self.state
        else:  # pragma: no cover - the runner owns the finite command set
            raise AssertionError(f"unexpected request kind 0x{kind:02x}")
        self.pending.extend(
            _campaign_wire_frame(
                version=version,
                kind=response_kind,
                payload=bytes(response_payload),
                request_id=request_id,
                run_id=run_id,
            )
        )

    def _configuration_payload(self) -> bytearray:
        payload = bytearray(12)
        rig.RESPONSE_PREFIX.pack_into(payload, 0, 0, 0, 0)
        rig.CONFIGURATION.pack_into(
            payload,
            4,
            self.stream_mask,
            self.source,
            self.checksum,
            self.configuration_encoding,
            rig.DATA_FRAME_BYTES,
        )
        return payload

    def _info_payload(self, version: int) -> bytearray:
        payload = bytearray(rig.SUCCESS_PAYLOAD_SIZE[version][rig.INFO_RESPONSE])
        rig.RESPONSE_PREFIX.pack_into(payload, 0, 0, 0, 0)
        payload[4] = self.state
        payload[5] = version
        payload[6] = rig.STREAM_BOTH
        payload[7] = (
            rig.V1_SOURCE_MASK if version == rig.PROTOCOL_V1 else rig.V2_SOURCE_MASK
        )
        struct.pack_into(
            "<I", payload, 8, sum(1 << value for value in rig.SUPPORTED_CHECKSUMS)
        )
        struct.pack_into(
            "<I",
            payload,
            12,
            rig.KNOWN_V1_CAPABILITY_MASK
            if version == rig.PROTOCOL_V1
            else rig.KNOWN_V2_CAPABILITY_MASK,
        )
        struct.pack_into(
            "<I",
            payload,
            24,
            rig.MAX_V1_CONTROL_FRAME_BYTES
            if version == rig.PROTOCOL_V1
            else rig.MAX_V2_CONTROL_FRAME_BYTES,
        )
        payload[45] = rig.CHECKSUM_ADLER32
        struct.pack_into("<I", payload, 54, 0xAABBCCDD)
        payload[58:61] = bytes((0, 7, 0))
        struct.pack_into("<H", payload, 62, 1)
        struct.pack_into("<H", payload, 64, 1)
        build_id = b"rle-campaign-fake"
        payload[66 : 66 + len(build_id)] = build_id
        struct.pack_into("<I", payload, 192, rig.CPU_DWT_HZ)
        return payload

    def _queue_next_data_frame(self) -> None:
        if len(self.generated_kinds) >= 2:
            return
        kind = rig.ADC_DATA if not self.generated_kinds else rig.GPIO_DATA
        self.generated_kinds.append(kind)
        wire, encoded_payload, run_count, encoding = self._data_frame(kind)
        metrics = self.metrics[kind]
        item_count = (
            rig.ADC_PAIRS_PER_FRAME
            if kind == rig.ADC_DATA
            else rig.GPIO_SAMPLES_PER_FRAME
        )
        metrics["frames"] += 1
        metrics["items"] += item_count
        metrics["encoded_payload"] += encoded_payload
        metrics["wire"] += rig.HEADER_SIZE + encoded_payload + rig.TRAILER_SIZE
        metrics["raw_frames"] += encoding == rig.FRAME_ENCODING_RAW
        metrics["rle_frames"] += encoding == rig.FRAME_ENCODING_RLE
        metrics["runs"] += run_count
        self.pending.extend(wire)
        if self.fault == "disconnect" and len(self.generated_kinds) == 1:
            self.disconnect_when_empty = True

    def _data_frame(self, kind: int) -> tuple[bytes, int, int, int]:
        item_count = (
            rig.ADC_PAIRS_PER_FRAME
            if kind == rig.ADC_DATA
            else rig.GPIO_SAMPLES_PER_FRAME
        )
        item_bytes = rig.ADC_BYTES_PER_PAIR if kind == rig.ADC_DATA else 1
        logical = b"".join(
            rig.logical_item(self.pattern, kind, index) for index in range(item_count)
        )
        rle_payload = bytearray()
        logical_index = 0
        remaining = item_count
        while remaining:
            run_length = rig.expected_run_length(
                self.pattern, kind, logical_index, remaining
            )
            rle_payload.extend(struct.pack("<H", run_length))
            rle_payload.extend(rig.logical_item(self.pattern, kind, logical_index))
            logical_index += run_length
            remaining -= run_length
        use_rle = (
            self.configuration_encoding == rig.CONFIGURATION_ENCODING_RLE_AUTO
            and len(rle_payload) < len(logical)
        )
        payload = bytes(rle_payload) if use_rle else logical
        encoding = rig.FRAME_ENCODING_RLE if use_rle else rig.FRAME_ENCODING_RAW
        run_count = len(rle_payload) // (item_bytes + 2) if use_rle else 0

        first_attack = len(self.generated_kinds) == 1
        if first_attack and self.fault == "corrupt_rle":
            payload = struct.pack("<H", 0) + rig.logical_item(self.pattern, kind, 0)
            encoding = rig.FRAME_ENCODING_RLE
            run_count = 1
        elif first_attack and self.fault == "noncanonical_rle":
            item = rig.logical_item(self.pattern, kind, 0)
            payload = (
                struct.pack("<H", 1) + item + struct.pack("<H", item_count - 1) + item
            )
            encoding = rig.FRAME_ENCODING_RLE
            run_count = 2
        elif first_attack and self.fault == "decode_bound":
            payload = struct.pack("<H", item_count + 1) + rig.logical_item(
                self.pattern, kind, 0
            )
            encoding = rig.FRAME_ENCODING_RLE
            run_count = 1

        wire = _campaign_wire_frame(
            version=rig.PROTOCOL_V2,
            kind=kind,
            payload=payload,
            run_id=self.run_id,
            sequence=0,
            first_sample_ticks=0,
            item_count=item_count,
            flags=rig.FLAG_SYNTHETIC | rig.FLAG_EPOCH_START,
            checksum_algorithm=self.checksum,
            encoding=encoding,
        )
        if first_attack and self.fault == "checksum_damage":
            damaged = bytearray(wire)
            damaged[-1] ^= 1
            wire = bytes(damaged)
        elif first_attack and self.fault == "truncated_rle":
            wire = wire[:-1]
        return wire, len(payload), run_count, encoding

    def _status_payload(self, version: int) -> bytearray:
        size = rig.SUCCESS_PAYLOAD_SIZE[version][rig.GET_STATUS_RESPONSE]
        payload = bytearray(size)
        values = {name: 0 for name in rig.STATUS_FIELDS}
        values.update(
            {
                "device_state": self.state,
                "stream_mask": (
                    self.stream_mask
                    if self.state == rig.STATE_RUNNING
                    else rig.STREAM_NONE
                ),
                "source": (
                    self.source
                    if self.state == rig.STATE_RUNNING
                    else rig.SOURCE_HARDWARE
                ),
                "data_checksum_algorithm": self.checksum,
                "data_frame_bytes": rig.DATA_FRAME_BYTES,
                "stats_generation": self.stats_generation,
                "configuration_encoding": (
                    self.configuration_encoding
                    if self.state == rig.STATE_RUNNING
                    else rig.CONFIGURATION_ENCODING_RAW
                ),
                "packet_accounted_frame_skew": abs(
                    self.metrics[rig.ADC_DATA]["frames"]
                    - self.metrics[rig.GPIO_DATA]["frames"]
                ),
                "temporary_page_high_water": int(
                    any(item["rle_frames"] for item in self.metrics.values())
                ),
            }
        )
        combined_frames = 0
        combined_logical = 0
        combined_wire = 0
        for kind, prefix, item_count in (
            (rig.ADC_DATA, "adc", rig.ADC_PAIRS_PER_FRAME),
            (rig.GPIO_DATA, "gpio", rig.GPIO_SAMPLES_PER_FRAME),
        ):
            metrics = self.metrics[kind]
            frames = metrics["frames"]
            items = metrics["items"]
            logical = frames * rig.DATA_PAYLOAD_BYTES
            combined_frames += frames
            combined_logical += logical
            combined_wire += metrics["wire"]
            values.update(
                {
                    f"{prefix}_frames_emitted": frames,
                    f"{prefix}_frames_generated": frames,
                    f"{prefix}_frames_framed_pipeline": frames,
                    f"{prefix}_frames_transmitted": frames,
                    f"{prefix}_items_generated": items,
                    f"{prefix}_items_framed_pipeline": items,
                    f"{prefix}_items_emitted": items,
                    f"{prefix}_items_transmitted_pipeline": items,
                    f"{prefix}_payload_bytes_produced": logical,
                    f"{prefix}_payload_bytes_framed": logical,
                    f"{prefix}_payload_bytes_emitted": logical,
                    f"{prefix}_payload_bytes_transmitted": logical,
                    f"{prefix}_framed_bytes_framed": metrics["wire"],
                    f"{prefix}_framed_bytes_emitted": metrics["wire"],
                    f"{prefix}_framed_bytes_transmitted": metrics["wire"],
                    f"{prefix}_encoded_payload_bytes_framed": metrics[
                        "encoded_payload"
                    ],
                    f"{prefix}_encoded_payload_bytes_transmitted": metrics[
                        "encoded_payload"
                    ],
                    f"{prefix}_raw_frames": metrics["raw_frames"],
                    f"{prefix}_rle_frames": metrics["rle_frames"],
                    f"{prefix}_rle_runs": metrics["runs"],
                    f"{prefix}_fallback_frames": metrics["raw_frames"],
                    f"{prefix}_fallback_not_smaller": metrics["raw_frames"],
                    f"{prefix}_encode_cycles": frames * 100,
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
            values[legacy_framed] = items
            values[legacy_transmitted] = items
            if prefix == "gpio":
                values["gpio_samples_captured"] = items
                values["gpio_samples_packed"] = items
                values["gpio_samples_produced"] = items
                values["gpio_samples_delivered"] = items
                values["gpio_frames_packed"] = frames
                values["gpio_frames_produced"] = frames
            else:
                values["adc_frames_consumed"] = frames
                values["adc_pairs_consumed"] = items
            if items != frames * item_count:
                raise AssertionError("fake stream item accounting drifted")
        values["packet_frames_promoted"] = combined_frames
        values["data_payload_bytes_transmitted"] = combined_logical
        values["data_framed_bytes_transmitted"] = combined_wire
        if self.fault == "counter_disagreement" and self.state == rig.STATE_IDLE:
            values["gpio_encoded_payload_bytes_transmitted"] += 1
        for name, (fmt, offset) in rig.STATUS_FIELDS.items():
            if offset + struct.calcsize(fmt) <= size:
                struct.pack_into(fmt, payload, offset, values[name])
        return payload


def _run_campaign_fake(
    pattern: str, fault: str | None = None
) -> tuple[int, dict[str, object], CampaignFakeSerial, str]:
    fake = CampaignFakeSerial(pattern, fault)
    output = io.StringIO()
    environment = {
        "SERIAL_PORT": "fake-rle-campaign",
        "RLE_STREAMING_MODE": "smoke",
        "RLE_CAPTURE_SECONDS": "0.05",
        "RLE_WARMUP_SECONDS": "0",
        "RLE_STATUS_INTERVAL_SECONDS": "0.05",
        "RLE_PATTERN": pattern,
        "RLE_ENCODING": "RLE_AUTO",
    }
    with (
        mock.patch.object(rig, "STARTUP_DRAIN_SECONDS", 0),
        mock.patch.object(rig, "STOP_DRAIN_DEADLINE_SECONDS", 0.05),
        mock.patch.object(rig, "STOP_DRAIN_QUIET_SECONDS", 0.0002),
        mock.patch.object(rig.serial, "Serial", return_value=fake),
        mock.patch.dict(os.environ, environment, clear=True),
        redirect_stdout(output),
    ):
        exit_code = rig.main()
    transcript = output.getvalue()
    result_lines = [
        line.removeprefix(rig.RLE_RESULT_PREFIX)
        for line in transcript.splitlines()
        if line.startswith(rig.RLE_RESULT_PREFIX)
    ]
    if len(result_lines) != 1:
        raise AssertionError(f"expected one result line, got {transcript!r}")
    return exit_code, json.loads(result_lines[0]), fake, transcript


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

    def test_full_program_executes_every_target_pattern_with_partial_io(self) -> None:
        for pattern in rig.PATTERN_SOURCE:
            with self.subTest(pattern=pattern):
                exit_code, result, fake, transcript = _run_campaign_fake(pattern)
                self.assertEqual(0, exit_code, transcript)
                self.assertEqual("PASS", result["result"])
                self.assertIsNone(result["failure_class"])
                cleanup = result["cleanup"]
                self.assertTrue(cleanup["stop_attempted"])
                self.assertTrue(cleanup["stop_succeeded"])
                self.assertTrue(cleanup["idle_confirmed"])
                self.assertEqual([], cleanup["errors"])
                streams = result["host"]["streams"]
                self.assertEqual(1, streams["adc"]["frames"])
                self.assertEqual(1, streams["gpio"]["frames"])
                if pattern in {"alternating", "incompressible"}:
                    self.assertEqual(2, result["host"]["combined"]["raw_frames"])
                    self.assertEqual(0, result["host"]["combined"]["rle_frames"])
                else:
                    self.assertEqual(0, result["host"]["combined"]["raw_frames"])
                    self.assertEqual(2, result["host"]["combined"]["rle_frames"])
                self.assertTrue(fake.closed)
                self.assertEqual(rig.STATE_IDLE, fake.state)
                self.assertIn(0, fake.write_counts)
                self.assertLessEqual(max(fake.read_counts), rig.SERIAL_READ_BYTES)

    def test_full_program_rejects_every_adversarial_rle_envelope(self) -> None:
        for fault in (
            "corrupt_rle",
            "truncated_rle",
            "noncanonical_rle",
            "checksum_damage",
            "decode_bound",
        ):
            with self.subTest(fault=fault):
                exit_code, result, fake, transcript = _run_campaign_fake(
                    "constant", fault
                )
                self.assertEqual(1, exit_code, transcript)
                self.assertEqual("FAIL", result["result"])
                self.assertEqual("codec", result["failure_class"])
                self.assertTrue(result["cleanup"]["stop_attempted"])
                self.assertTrue(result["cleanup"]["idle_confirmed"])
                self.assertTrue(fake.closed)

    def test_full_program_classifies_counter_disconnect_and_cleanup_faults(
        self,
    ) -> None:
        exit_code, result, fake, transcript = _run_campaign_fake(
            "constant", "counter_disagreement"
        )
        self.assertEqual(1, exit_code, transcript)
        self.assertEqual("FAIL", result["result"])
        self.assertEqual("firmware", result["failure_class"])
        self.assertIn("conservation mismatch", result["reason"])
        self.assertTrue(result["cleanup"]["idle_confirmed"])
        self.assertTrue(fake.closed)

        exit_code, result, fake, transcript = _run_campaign_fake(
            "constant", "disconnect"
        )
        self.assertEqual(2, exit_code, transcript)
        self.assertEqual("INCONCLUSIVE", result["result"])
        self.assertEqual("service", result["failure_class"])
        self.assertTrue(result["cleanup"]["stop_attempted"])
        self.assertTrue(result["cleanup"]["errors"])
        self.assertTrue(fake.closed)

        exit_code, result, fake, transcript = _run_campaign_fake(
            "constant", "cleanup_failure"
        )
        self.assertEqual(2, exit_code, transcript)
        self.assertEqual("INCONCLUSIVE", result["result"])
        self.assertEqual("service", result["failure_class"])
        self.assertFalse(result["cleanup"]["idle_confirmed"])
        self.assertTrue(result["cleanup"]["errors"])
        self.assertTrue(fake.closed)


if __name__ == "__main__":
    unittest.main()
