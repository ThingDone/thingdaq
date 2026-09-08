"""Offline verification for the independent Phase 09 recovery rig programs."""

from __future__ import annotations

import ast
import importlib.util
import io
import os
import struct
import sys
import time
import unittest
import zlib
from contextlib import redirect_stdout
from pathlib import Path
from types import ModuleType
from unittest.mock import patch

from thingdone_daq._generated import protocol_constants as constants
from thingdone_daq.models import Configuration, Info, Status
from thingdone_daq.protocol import encode_frame
from thingdone_daq.synthetic import synthetic_adc_payload, synthetic_gpio_payload

ROOT = Path(__file__).resolve().parents[2]
HOST_SCRIPT = ROOT / "firmware" / "tests" / "rig_host_stall_recovery.py"
CONTROL_SCRIPT = ROOT / "firmware" / "tests" / "rig_control_recovery.py"
FIXTURES = ROOT / "protocol" / "fixtures"

HEADER = struct.Struct("<IBBHHBBIIIIIQI")
RESPONSE_PREFIX = struct.Struct("<BBH")
ERROR_PAYLOAD = struct.Struct("<BBHBBH")
SUCCESS_PREFIX = RESPONSE_PREFIX.pack(0, 0, 0)
REQUEST_PAYLOAD_SIZES = {
    constants.FrameKind.INFO_REQUEST: 0,
    constants.FrameKind.CONFIGURE_REQUEST: constants.CONFIGURE_REQUEST_PAYLOAD_SIZE,
    constants.FrameKind.START_REQUEST: 0,
    constants.FrameKind.GET_STATUS_REQUEST: 0,
    constants.FrameKind.STOP_REQUEST: 0,
    constants.FrameKind.RESET_STATS_REQUEST: 0,
}


def _load_script(name: str, path: Path) -> ModuleType:
    specification = importlib.util.spec_from_file_location(name, path)
    if specification is None or specification.loader is None:
        raise RuntimeError(f"could not load {path.name}")
    module = importlib.util.module_from_spec(specification)
    sys.modules[specification.name] = module
    specification.loader.exec_module(module)
    return module


host_rig = _load_script("independent_rig_host_stall_recovery", HOST_SCRIPT)
control_rig = _load_script("independent_rig_control_recovery", CONTROL_SCRIPT)


class FakeRecoveryDevice:
    """Wire-level physical peer with parser errors, pressure loss, and sessions."""

    def __init__(self, *, inject_stall_loss: bool) -> None:
        self.inject_stall_loss = inject_stall_loss
        self.state = constants.DeviceState.IDLE
        self.configuration: Configuration | None = None
        self.run_id = 0
        self.stats_generation = 1
        self.rx = bytearray()
        self.recent_ids: list[int] = []
        self.status_calls = 0
        self.stall_injected = False
        self.generated = {
            constants.FrameKind.ADC_DATA: 0,
            constants.FrameKind.GPIO_DATA: 0,
        }
        self.transmitted = {
            constants.FrameKind.ADC_DATA: 0,
            constants.FrameKind.GPIO_DATA: 0,
        }
        self.dropped = {
            constants.FrameKind.ADC_DATA: 0,
            constants.FrameKind.GPIO_DATA: 0,
        }
        self.gap_pending = {
            constants.FrameKind.ADC_DATA: False,
            constants.FrameKind.GPIO_DATA: False,
        }
        self.commands_accepted = 0
        self.commands_rejected = 0
        self.bad_checksums = 0
        self.bad_lengths = 0
        self.bad_types = 0
        self.bad_versions = 0
        self.bad_flags = 0
        self.bad_payloads = 0
        self.bad_request_ids = 0
        self.state_errors = 0
        self.parser_errors = 0
        self.packet_pool_exhaustions = 0
        self.usb_tx_stall_events = 0
        self.session_count = 0

    def begin_session(self) -> None:
        self.session_count += 1
        self.recent_ids.clear()
        self.rx.clear()

    def close_session(self) -> None:
        self.rx.clear()
        if self.state is constants.DeviceState.RUNNING and not self.inject_stall_loss:
            self._drop(adc=2, gpio=3)

    def receive(self, data: bytes) -> list[bytes]:
        self.rx.extend(data)
        responses: list[bytes] = []
        while True:
            magic_at = self.rx.find(constants.MAGIC.to_bytes(4, "little"))
            if magic_at < 0:
                retained = 0
                for length in range(min(3, len(self.rx)), 0, -1):
                    if (
                        self.rx[-length:]
                        == constants.MAGIC.to_bytes(4, "little")[:length]
                    ):
                        retained = length
                        break
                if retained:
                    del self.rx[:-retained]
                else:
                    self.rx.clear()
                break
            if magic_at:
                del self.rx[:magic_at]
            if len(self.rx) < constants.HEADER_SIZE:
                break
            fields = HEADER.unpack_from(self.rx)
            version = fields[1]
            kind = fields[2]
            flags = fields[3]
            header_length = fields[4]
            checksum = fields[5]
            reserved = fields[6]
            total_length = fields[7]
            payload_length = fields[8]
            run_id = fields[9]
            sequence = fields[10]
            request_id = fields[11]
            first_ticks = fields[12]
            item_count = fields[13]

            error: constants.ErrorCode | None = None
            counter = ""
            if version != constants.PROTOCOL_VERSION:
                error = constants.ErrorCode.UNSUPPORTED_VERSION
                counter = "bad_versions"
            elif kind not in constants.REQUEST_RESPONSE_KIND:
                error = constants.ErrorCode.UNKNOWN_FRAME_KIND
                counter = "bad_types"
            elif flags:
                error = constants.ErrorCode.INVALID_FLAGS
                counter = "bad_flags"
            elif (
                header_length != constants.HEADER_SIZE
                or total_length > constants.MAX_COMMAND_FRAME_BYTES
                or total_length < constants.MIN_FRAME_BYTES
                or total_length
                != constants.HEADER_SIZE + payload_length + constants.TRAILER_SIZE
            ):
                error = constants.ErrorCode.INVALID_LENGTH
                counter = "bad_lengths"
            elif reserved or (
                checksum != int(constants.BOOTSTRAP_CHECKSUM_ALGORITHM)
                or run_id
                or sequence
                or first_ticks
                or item_count
            ):
                error = constants.ErrorCode.INVALID_PAYLOAD
                counter = "bad_payloads"
            if error is not None:
                self._record_parser_error(counter)
                if request_id:
                    responses.append(
                        self._generic_error(request_id, kind, version, error)
                    )
                del self.rx[0]
                continue
            if len(self.rx) < total_length:
                break
            expected_checksum = (
                zlib.adler32(self.rx[: total_length - constants.TRAILER_SIZE])
                & constants.UINT32_MAX
            )
            actual_checksum = struct.unpack_from(
                "<I", self.rx, total_length - constants.TRAILER_SIZE
            )[0]
            if actual_checksum != expected_checksum:
                self._record_parser_error("bad_checksums")
                if request_id:
                    responses.append(
                        self._generic_error(
                            request_id,
                            kind,
                            version,
                            constants.ErrorCode.CHECKSUM_MISMATCH,
                        )
                    )
                del self.rx[0]
                continue
            expected_payload = REQUEST_PAYLOAD_SIZES[constants.FrameKind(kind)]
            if payload_length != expected_payload:
                self._record_parser_error("bad_lengths")
                responses.append(
                    self._generic_error(
                        request_id,
                        kind,
                        version,
                        constants.ErrorCode.INVALID_LENGTH,
                    )
                )
                del self.rx[0]
                continue

            payload = bytes(
                self.rx[constants.HEADER_SIZE : constants.HEADER_SIZE + payload_length]
            )
            del self.rx[:total_length]
            responses.extend(self._dispatch(kind, request_id, payload))
        return responses

    def next_data_pair(self) -> list[bytes]:
        if self.state is not constants.DeviceState.RUNNING:
            return []
        return [
            self._next_data(constants.FrameKind.ADC_DATA),
            self._next_data(constants.FrameKind.GPIO_DATA),
        ]

    def _dispatch(self, kind: int, request_id: int, payload: bytes) -> list[bytes]:
        request_kind = constants.FrameKind(kind)
        was_running = self.state is constants.DeviceState.RUNNING
        if request_id in self.recent_ids:
            self.commands_rejected += 1
            self.bad_request_ids += 1
            prefix = self.next_data_pair() if was_running else []
            return prefix + [
                self._typed_error(
                    request_kind,
                    request_id,
                    constants.ErrorCode.INVALID_REQUEST_ID,
                )
            ]
        self.recent_ids.append(request_id)
        self.recent_ids = self.recent_ids[-16:]

        if (
            self.inject_stall_loss
            and request_kind is constants.FrameKind.GET_STATUS_REQUEST
            and self.state is constants.DeviceState.RUNNING
            and self.status_calls == 1
            and not self.stall_injected
        ):
            self._drop(adc=5, gpio=4)
            self.stall_injected = True

        prefix = self.next_data_pair() if was_running else []
        if request_kind is constants.FrameKind.INFO_REQUEST:
            self.commands_accepted += 1
            response = self._success(
                request_kind, request_id, self._info().to_payload()
            )
        elif request_kind is constants.FrameKind.CONFIGURE_REQUEST:
            if self.state not in {
                constants.DeviceState.IDLE,
                constants.DeviceState.CONFIGURED,
            }:
                response = self._state_error(request_kind, request_id)
            else:
                configuration = Configuration.from_payload(payload)
                if (
                    configuration.stream_mask
                    != constants.StreamMask.ADC | constants.StreamMask.GPIO
                    or configuration.source is not constants.Source.HARDWARE
                ):
                    response = self._typed_error(
                        request_kind,
                        request_id,
                        constants.ErrorCode.UNSUPPORTED_CONFIGURATION,
                    )
                    self.commands_rejected += 1
                else:
                    self.configuration = configuration
                    self.state = constants.DeviceState.CONFIGURED
                    self.commands_accepted += 1
                    response = self._success(
                        request_kind,
                        request_id,
                        SUCCESS_PREFIX + configuration.to_payload(),
                    )
        elif request_kind is constants.FrameKind.START_REQUEST:
            if (
                self.state is not constants.DeviceState.CONFIGURED
                or self.configuration is None
            ):
                response = self._state_error(request_kind, request_id)
            else:
                self.run_id = (self.run_id + 1) & constants.UINT32_MAX or 1
                self._reset_epoch()
                self.state = constants.DeviceState.RUNNING
                self.commands_accepted += 1
                response = self._success(
                    request_kind,
                    request_id,
                    SUCCESS_PREFIX + self.configuration.to_payload(),
                )
        elif request_kind is constants.FrameKind.GET_STATUS_REQUEST:
            self.status_calls += 1
            self.commands_accepted += 1
            response = self._success(
                request_kind,
                request_id,
                self._status().to_payload(),
            )
        elif request_kind is constants.FrameKind.STOP_REQUEST:
            self.state = constants.DeviceState.IDLE
            self.configuration = None
            self.commands_accepted += 1
            stop_payload = bytearray(constants.STOP_RESPONSE_PAYLOAD_SIZE)
            stop_payload[:4] = SUCCESS_PREFIX
            stop_payload[constants.STOP_RESPONSE_DEVICE_STATE_OFFSET] = int(
                constants.DeviceState.IDLE
            )
            response = self._success(request_kind, request_id, bytes(stop_payload))
        elif request_kind is constants.FrameKind.RESET_STATS_REQUEST:
            if self.state not in {
                constants.DeviceState.IDLE,
                constants.DeviceState.CONFIGURED,
            }:
                response = self._state_error(request_kind, request_id)
            else:
                self._reset_counters()
                self.commands_accepted = 1
                reset_payload = bytearray(constants.RESET_STATS_RESPONSE_PAYLOAD_SIZE)
                reset_payload[:4] = SUCCESS_PREFIX
                struct.pack_into("<I", reset_payload, 4, self.stats_generation)
                response = self._success(request_kind, request_id, bytes(reset_payload))
        else:  # pragma: no cover - request subset above is exhaustive
            raise AssertionError(request_kind)
        return prefix + [response]

    def _record_parser_error(self, counter: str) -> None:
        self.parser_errors += 1
        self.commands_rejected += 1
        setattr(self, counter, getattr(self, counter) + 1)

    def _state_error(self, kind: constants.FrameKind, request_id: int) -> bytes:
        self.commands_rejected += 1
        self.state_errors += 1
        return self._typed_error(kind, request_id, constants.ErrorCode.INVALID_STATE)

    def _drop(self, *, adc: int, gpio: int) -> None:
        for kind, count in (
            (constants.FrameKind.ADC_DATA, adc),
            (constants.FrameKind.GPIO_DATA, gpio),
        ):
            self.generated[kind] += count
            self.dropped[kind] += count
            self.gap_pending[kind] = self.gap_pending[kind] or count > 0
        total = adc + gpio
        self.packet_pool_exhaustions += total
        self.usb_tx_stall_events += 1

    def _next_data(self, kind: constants.FrameKind) -> bytes:
        sequence = self.generated[kind]
        flags = constants.FrameFlag.NONE
        if sequence == 0:
            flags |= constants.FrameFlag.EPOCH_START
        if self.gap_pending[kind]:
            flags |= constants.FrameFlag.GAP_BEFORE | constants.FrameFlag.OVERRUN_BEFORE
            self.gap_pending[kind] = False
        if kind is constants.FrameKind.ADC_DATA:
            payload = synthetic_adc_payload(sequence * constants.ADC_PAIRS_PER_FRAME)
            item_count = constants.ADC_PAIRS_PER_FRAME
        else:
            payload = synthetic_gpio_payload(
                sequence * constants.GPIO_SAMPLES_PER_FRAME
            )
            item_count = constants.GPIO_SAMPLES_PER_FRAME
        wire = encode_frame(
            kind,
            payload,
            flags=flags,
            run_id=self.run_id,
            sequence=sequence,
            first_sample_ticks=sequence * constants.FRAME_COVERAGE_TICKS,
            item_count=item_count,
        )
        self.generated[kind] += 1
        self.transmitted[kind] += 1
        return wire

    def _info(self) -> Info:
        configuration = self.configuration
        return Info(
            device_state=self.state,
            build_id="thingdaq-0123456789abcdef",
            hardware_serial=12_345_670,
            firmware_version=(0, 9, 0),
            board_id=constants.BoardId.TEENSY_40,
            mcu_id=constants.McuId.IMXRT1062,
            supported_stream_mask=constants.StreamMask.ADC | constants.StreamMask.GPIO,
            supported_source_mask=1 << int(constants.Source.HARDWARE),
            supported_configuration_mask=(
                constants.ConfigurationProfile.HARDWARE_ADC
                | constants.ConfigurationProfile.HARDWARE_GPIO
                | constants.ConfigurationProfile.HARDWARE_COMBINED
            ),
            applied_stream_mask=(
                configuration.stream_mask
                if configuration is not None
                else constants.StreamMask.NONE
            ),
            applied_source=constants.Source.HARDWARE,
            capability_bits=(
                constants.Capability.ADC_STREAM
                | constants.Capability.GPIO_STREAM
                | constants.Capability.HARDWARE_SOURCE
                | constants.Capability.RESET_STATS
                | constants.Capability.PING
            ),
        )

    def _status(self) -> Status:
        adc_generated = self.generated[constants.FrameKind.ADC_DATA]
        gpio_generated = self.generated[constants.FrameKind.GPIO_DATA]
        adc_transmitted = self.transmitted[constants.FrameKind.ADC_DATA]
        gpio_transmitted = self.transmitted[constants.FrameKind.GPIO_DATA]
        adc_dropped = self.dropped[constants.FrameKind.ADC_DATA]
        gpio_dropped = self.dropped[constants.FrameKind.GPIO_DATA]
        adc_items_transmitted = adc_transmitted * constants.ADC_PAIRS_PER_FRAME
        gpio_items_transmitted = gpio_transmitted * constants.GPIO_SAMPLES_PER_FRAME
        adc_items_generated = adc_generated * constants.ADC_PAIRS_PER_FRAME
        gpio_items_generated = gpio_generated * constants.GPIO_SAMPLES_PER_FRAME
        adc_payload_transmitted = adc_transmitted * constants.DATA_PAYLOAD_BYTES
        gpio_payload_transmitted = gpio_transmitted * constants.DATA_PAYLOAD_BYTES
        adc_framed_transmitted = adc_transmitted * constants.DATA_FRAME_BYTES
        gpio_framed_transmitted = gpio_transmitted * constants.DATA_FRAME_BYTES
        configuration = self.configuration
        stream_mask = (
            configuration.stream_mask
            if configuration is not None
            else constants.StreamMask.NONE
        )
        return Status(
            device_state=self.state,
            stream_mask=stream_mask,
            source=constants.Source.HARDWARE,
            data_checksum_algorithm=constants.ChecksumAlgorithm.ADLER32,
            adc_frames_emitted=adc_transmitted,
            gpio_frames_emitted=gpio_transmitted,
            adc_items_dropped=adc_dropped * constants.ADC_PAIRS_PER_FRAME,
            gpio_items_dropped=gpio_dropped * constants.GPIO_SAMPLES_PER_FRAME,
            parser_errors=self.parser_errors,
            stats_generation=self.stats_generation,
            adc_frames_generated=adc_generated,
            adc_items_generated=adc_items_generated,
            adc_frames_framed_pipeline=adc_generated,
            adc_items_framed_pipeline=adc_items_generated,
            adc_items_emitted=adc_items_transmitted,
            adc_frames_transmitted=adc_transmitted,
            adc_items_transmitted_pipeline=adc_items_transmitted,
            adc_frames_dropped=adc_dropped,
            gpio_frames_generated=gpio_generated,
            gpio_items_generated=gpio_items_generated,
            gpio_frames_framed_pipeline=gpio_generated,
            gpio_items_framed_pipeline=gpio_items_generated,
            gpio_items_emitted=gpio_items_transmitted,
            gpio_frames_transmitted=gpio_transmitted,
            gpio_items_transmitted_pipeline=gpio_items_transmitted,
            gpio_frames_dropped=gpio_dropped,
            adc_payload_bytes_produced=adc_generated * constants.DATA_PAYLOAD_BYTES,
            adc_payload_bytes_framed=adc_generated * constants.DATA_PAYLOAD_BYTES,
            adc_payload_bytes_emitted=adc_payload_transmitted,
            adc_payload_bytes_transmitted=adc_payload_transmitted,
            adc_payload_bytes_dropped=(
                adc_dropped
                * constants.ADC_PAIRS_PER_FRAME
                * constants.ADC_BYTES_PER_PAIR
            ),
            adc_framed_bytes_framed=adc_generated * constants.DATA_FRAME_BYTES,
            adc_framed_bytes_emitted=adc_framed_transmitted,
            adc_framed_bytes_transmitted=adc_framed_transmitted,
            gpio_payload_bytes_produced=gpio_generated * constants.DATA_PAYLOAD_BYTES,
            gpio_payload_bytes_framed=gpio_generated * constants.DATA_PAYLOAD_BYTES,
            gpio_payload_bytes_emitted=gpio_payload_transmitted,
            gpio_payload_bytes_transmitted=gpio_payload_transmitted,
            gpio_payload_bytes_dropped=gpio_dropped * constants.GPIO_SAMPLES_PER_FRAME,
            gpio_framed_bytes_framed=gpio_generated * constants.DATA_FRAME_BYTES,
            gpio_framed_bytes_emitted=gpio_framed_transmitted,
            gpio_framed_bytes_transmitted=gpio_framed_transmitted,
            packet_frames_promoted=adc_transmitted + gpio_transmitted,
            data_payload_bytes_transmitted=(
                adc_payload_transmitted + gpio_payload_transmitted
            ),
            data_framed_bytes_transmitted=(
                adc_framed_transmitted + gpio_framed_transmitted
            ),
            packet_pressure_evictions=adc_dropped + gpio_dropped,
            adc_frames_evicted=adc_dropped,
            gpio_frames_evicted=gpio_dropped,
            adc_frames_dropped_after_framing=adc_dropped,
            gpio_frames_dropped_after_framing=gpio_dropped,
            packet_pool_exhaustions=self.packet_pool_exhaustions,
            commands_accepted=self.commands_accepted,
            commands_rejected=self.commands_rejected,
            bad_checksums=self.bad_checksums,
            bad_lengths=self.bad_lengths,
            bad_types=self.bad_types,
            bad_versions=self.bad_versions,
            bad_flags=self.bad_flags,
            bad_payloads=self.bad_payloads,
            bad_request_ids=self.bad_request_ids,
            state_errors=self.state_errors,
            usb_tx_stall_events=self.usb_tx_stall_events,
        )

    def _reset_epoch(self) -> None:
        self.generated = {
            constants.FrameKind.ADC_DATA: 0,
            constants.FrameKind.GPIO_DATA: 0,
        }
        self.transmitted = {
            constants.FrameKind.ADC_DATA: 0,
            constants.FrameKind.GPIO_DATA: 0,
        }
        self.dropped = {
            constants.FrameKind.ADC_DATA: 0,
            constants.FrameKind.GPIO_DATA: 0,
        }
        self.gap_pending = {
            constants.FrameKind.ADC_DATA: False,
            constants.FrameKind.GPIO_DATA: False,
        }
        self.status_calls = 0
        self.stall_injected = False
        self._reset_counters()

    def _reset_counters(self) -> None:
        self.stats_generation = (self.stats_generation + 1) & constants.UINT32_MAX or 1
        self.commands_accepted = 0
        self.commands_rejected = 0
        self.bad_checksums = 0
        self.bad_lengths = 0
        self.bad_types = 0
        self.bad_versions = 0
        self.bad_flags = 0
        self.bad_payloads = 0
        self.bad_request_ids = 0
        self.state_errors = 0
        self.parser_errors = 0
        self.packet_pool_exhaustions = 0
        self.usb_tx_stall_events = 0

    def _success(
        self,
        request_kind: constants.FrameKind,
        request_id: int,
        payload: bytes,
    ) -> bytes:
        return encode_frame(
            constants.REQUEST_RESPONSE_KIND[request_kind],
            payload,
            run_id=self.run_id,
            request_id=request_id,
        )

    def _typed_error(
        self,
        request_kind: constants.FrameKind,
        request_id: int,
        error: constants.ErrorCode,
    ) -> bytes:
        return encode_frame(
            constants.REQUEST_RESPONSE_KIND[request_kind],
            RESPONSE_PREFIX.pack(1, 0, int(error)),
            flags=constants.FrameFlag.RESPONSE_ERROR,
            run_id=self.run_id,
            request_id=request_id,
        )

    def _generic_error(
        self,
        request_id: int,
        rejected_kind: int,
        rejected_version: int,
        error: constants.ErrorCode,
    ) -> bytes:
        return encode_frame(
            constants.FrameKind.ERROR_RESPONSE,
            ERROR_PAYLOAD.pack(
                1,
                0,
                int(error),
                rejected_kind,
                rejected_version,
                0,
            ),
            flags=constants.FrameFlag.RESPONSE_ERROR,
            run_id=self.run_id,
            request_id=request_id,
        )


class FakeRigSerial:
    """Partial-I/O pyserial shape backed by one persistent fake device."""

    def __init__(self, device: FakeRecoveryDevice, **_kwargs: object) -> None:
        self.device = device
        self.device.begin_session()
        self.pending = bytearray()
        self.is_open = True
        self.timeout = 0.0001
        self.read_pattern = (1, 47, 997, 4096, 8192)
        self.write_pattern = (1, 7, 19, 56)
        self.read_index = 0
        self.write_index = 0

    def read(self, size: int = 1) -> bytes:
        if not self.is_open:
            raise RuntimeError("fake serial port is closed")
        if not self.pending:
            for wire in self.device.next_data_pair():
                self.pending.extend(wire)
        if not self.pending:
            time.sleep(self.timeout)
            return b""
        limit = self.read_pattern[self.read_index % len(self.read_pattern)]
        self.read_index += 1
        count = min(size, limit, len(self.pending))
        result = bytes(self.pending[:count])
        del self.pending[:count]
        return result

    def write(self, data: bytes | bytearray | memoryview) -> int:
        if not self.is_open:
            raise RuntimeError("fake serial port is closed")
        wire = bytes(data)
        limit = self.write_pattern[self.write_index % len(self.write_pattern)]
        self.write_index += 1
        count = min(len(wire), limit)
        if count:
            for response in self.device.receive(wire[:count]):
                self.pending.extend(response)
        return count

    def close(self) -> None:
        if self.is_open:
            self.is_open = False
            self.pending.clear()
            self.device.close_session()


class RigIndependenceAndCodecTests(unittest.TestCase):
    def test_each_program_is_single_file_standard_library_plus_pyserial(self) -> None:
        allowed = {
            "__future__",
            "collections",
            "dataclasses",
            "json",
            "math",
            "os",
            "re",
            "serial",
            "struct",
            "sys",
            "time",
            "typing",
            "zlib",
        }
        for path in (HOST_SCRIPT, CONTROL_SCRIPT):
            source = path.read_text(encoding="utf-8")
            tree = ast.parse(source)
            imports: set[str] = set()
            for node in ast.walk(tree):
                if isinstance(node, ast.Import):
                    imports.update(alias.name.split(".", 1)[0] for alias in node.names)
                elif isinstance(node, ast.ImportFrom) and node.module is not None:
                    imports.add(node.module.split(".", 1)[0])
            with self.subTest(script=path.name):
                self.assertEqual(allowed, imports)
                self.assertNotIn("import thingdone_daq", source)
                self.assertNotIn("from thingdone_daq", source)
                self.assertNotIn("protocol-v1.json", source)
                self.assertIn('os.environ.get("SERIAL_PORT")', source)

    def test_independent_encoders_and_parsers_match_shared_fixtures(self) -> None:
        for rig in (host_rig, control_rig):
            for kind in rig.REQUEST_PAYLOAD_SIZE:
                fixture_name = {
                    rig.INFO_REQUEST: "info-request.bin",
                    rig.CONFIGURE_REQUEST: "configure-request.bin",
                    rig.START_REQUEST: "start-request.bin",
                    rig.GET_STATUS_REQUEST: "get-status-request.bin",
                    rig.STOP_REQUEST: "stop-request.bin",
                    rig.RESET_STATS_REQUEST: "reset-stats-request.bin",
                }[kind]
                expected = (FIXTURES / fixture_name).read_bytes()
                request_id = int.from_bytes(expected[28:32], "little")
                payload = expected[rig.HEADER_SIZE : -rig.TRAILER_SIZE]
                with self.subTest(script=rig.__name__, request=fixture_name):
                    self.assertEqual(
                        expected, rig.encode_request(kind, request_id, payload)
                    )

            parser = rig.FrameParser()
            decoded = []
            for name in (
                "info-response.bin",
                "get-status-response.bin",
                "adc-data.bin",
                "gpio-data.bin",
            ):
                wire = (FIXTURES / name).read_bytes()
                for offset in range(0, len(wire), 37):
                    decoded.extend(parser.feed(wire[offset : offset + 37]))
            self.assertEqual(
                [
                    rig.INFO_RESPONSE,
                    rig.GET_STATUS_RESPONSE,
                    rig.ADC_DATA,
                    rig.GPIO_DATA,
                ],
                [frame.kind for frame in decoded],
            )
            self.assertEqual(0, parser.errors)

    def test_host_tracker_reconciles_sequence_timestamp_and_flags(self) -> None:
        tracker = host_rig.CombinedTracker(7)
        for sequence in (0, 3):
            flags = (
                host_rig.FLAG_EPOCH_START
                if sequence == 0
                else (host_rig.FLAG_GAP_BEFORE | host_rig.FLAG_OVERRUN_BEFORE)
            )
            wire = encode_frame(
                constants.FrameKind.ADC_DATA,
                synthetic_adc_payload(sequence * constants.ADC_PAIRS_PER_FRAME),
                flags=constants.FrameFlag(flags),
                run_id=7,
                sequence=sequence,
                first_sample_ticks=sequence * constants.FRAME_COVERAGE_TICKS,
                item_count=constants.ADC_PAIRS_PER_FRAME,
            )
            frame = host_rig.FrameParser().feed(wire)[0]
            tracker.accept(frame)
        self.assertEqual(2, tracker.adc.missing_frames)
        self.assertEqual(2, tracker.adc.missing_before(4))
        self.assertEqual(1, tracker.adc.gap_flag_frames)


class RigProgramFlowTests(unittest.TestCase):
    def test_host_stall_program_reconciles_expected_loss_and_returns_idle(self) -> None:
        device = FakeRecoveryDevice(inject_stall_loss=True)
        port = FakeRigSerial(device)
        output = io.StringIO()
        with (
            patch.object(host_rig, "STARTUP_DRAIN_SECONDS", 0.001),
            patch.object(host_rig, "STOP_DRAIN_QUIET_SECONDS", 0.0001),
            patch.object(host_rig.serial, "Serial", return_value=port),
            patch.dict(
                os.environ,
                {
                    "BASELINE_FRAMES_PER_SOURCE": "2",
                    "EXPECTED_BUILD_ID": "thingdaq-0123456789abcdef",
                    "EXPECTED_HARDWARE_SERIAL": "12345670",
                    "RECOVERY_DEADLINE_SECONDS": "2",
                    "SERIAL_PORT": "fake-host-stall",
                    "STALL_SECONDS": "0.2",
                },
            ),
            redirect_stdout(output),
        ):
            exit_code = host_rig.main()
        self.assertEqual(0, exit_code, output.getvalue())
        self.assertEqual(constants.DeviceState.IDLE, device.state)
        self.assertTrue(device.stall_injected)
        self.assertFalse(port.is_open)
        self.assertIn('"event":"expected_negative_loss"', output.getvalue())
        self.assertIn(
            "expected_negative_loss.adc.sequence_missing_frames", output.getvalue()
        )
        self.assertIn("unexpected_firmware_or_hardware_errors", output.getvalue())

    def test_control_program_recovers_and_completes_one_hundred_cycles(self) -> None:
        device = FakeRecoveryDevice(inject_stall_loss=False)
        opened: list[FakeRigSerial] = []

        def open_port(**_kwargs: object) -> FakeRigSerial:
            port = FakeRigSerial(device)
            opened.append(port)
            return port

        output = io.StringIO()
        with (
            patch.object(control_rig, "STARTUP_DRAIN_SECONDS", 0.001),
            patch.object(control_rig, "CYCLE_DRAIN_QUIET_SECONDS", 0.0001),
            patch.object(control_rig.serial, "Serial", side_effect=open_port),
            patch.dict(
                os.environ,
                {
                    "CONTROL_RECOVERY_CYCLES": "100",
                    "EXPECTED_BUILD_ID": "thingdaq-0123456789abcdef",
                    "EXPECTED_HARDWARE_SERIAL": "12345670",
                    "REOPEN_DEADLINE_SECONDS": "2",
                    "REOPEN_PAUSE_SECONDS": "0",
                    "SERIAL_PORT": "fake-control-recovery",
                },
            ),
            redirect_stdout(output),
        ):
            exit_code = control_rig.main()
        self.assertEqual(0, exit_code, output.getvalue())
        self.assertEqual(constants.DeviceState.IDLE, device.state)
        self.assertGreaterEqual(device.session_count, 2)
        self.assertIn('"case":"truncated_then_garbage"', output.getvalue())
        self.assertIn('"cycle":100', output.getvalue())
        self.assertIn('"event":"cdc_reopen"', output.getvalue())
        self.assertIn('"scope":"cdc_close_reopen"', output.getvalue())
        self.assertTrue(all(not port.is_open for port in opened))


if __name__ == "__main__":
    unittest.main()
