"""Fake-device and static safety tests for the auxiliary output rig."""

from __future__ import annotations

import contextlib
import importlib.util
import io
import json
import os
import struct
import sys
import unittest
from pathlib import Path
from typing import Any, cast
from unittest.mock import patch

ROOT = Path(__file__).resolve().parents[2]
RIG_PATH = ROOT / "firmware/tests/rig_aux_output_loopback.py"
SPEC = importlib.util.spec_from_file_location("rig_aux_output_loopback", RIG_PATH)
assert SPEC is not None and SPEC.loader is not None
rig = importlib.util.module_from_spec(SPEC)
sys.modules[SPEC.name] = rig
SPEC.loader.exec_module(rig)


def fixture_json(serial: int = 0x10203040) -> str:
    return json.dumps(
        {
            "schema_version": rig.FIXTURE_SCHEMA_VERSION,
            "hardware_serial": serial,
            "connections": [
                {
                    "output_pin": output,
                    "input_pin": input_pin,
                    "series_resistance_ohms": 330,
                }
                for output, input_pin in zip(
                    rig.OUTPUT_PINS, rig.INPUT_PINS, strict=True
                )
            ],
            "io_voltage_volts": 3.3,
            "external_drivers": False,
            "authorized_profiles": [rig.PROFILE_ID],
        },
        sort_keys=True,
    )


def response_wire(
    request: bytes,
    *,
    error: int = 0,
    hardware_serial: int = 0x10203040,
) -> bytes:
    fields = rig.HEADER.unpack_from(request)
    request_kind = fields[2]
    request_id = fields[11]
    kind = rig.REQUEST_RESPONSE_KIND[request_kind]
    flags = rig.FLAG_RESPONSE_ERROR if error else 0
    if error:
        payload = rig.RESPONSE_PREFIX.pack(1, 0, error)
    else:
        payload = bytearray(rig.SUCCESS_PAYLOAD_SIZE[kind])
        rig.RESPONSE_PREFIX.pack_into(payload, 0, 0, 0, 0)
        if kind == rig.INFO_RESPONSE:
            payload[4] = rig.STATE_IDLE
            payload[5] = rig.PROTOCOL_VERSION
            payload[6] = rig.STREAM_BOTH
            struct.pack_into("<I", payload, 12, rig.REQUIRED_OUTPUT_CAPABILITIES)
            struct.pack_into("<I", payload, 16, rig.TIMESTAMP_HZ)
            struct.pack_into("<I", payload, 28, rig.ADC_PAIR_RATE_HZ)
            struct.pack_into("<I", payload, 32, rig.GPIO_SAMPLE_RATE_HZ)
            struct.pack_into("<H", payload, 36, rig.ADC_PAIR_PERIOD_TICKS)
            struct.pack_into("<H", payload, 38, rig.ADC1_PHASE_TICKS)
            struct.pack_into("<H", payload, 40, rig.GPIO_SAMPLE_PERIOD_TICKS)
            payload[45] = rig.BOOTSTRAP_CHECKSUM
            payload[46:54] = bytes(rig.INPUT_PINS)
            struct.pack_into("<I", payload, 54, hardware_serial)
            payload[66:77] = b"fake-build\0"
            payload[376] = rig.OUTPUT_BANK_DISABLED
            payload[377:380] = bytes((8, 8, 1))
            payload[380:388] = bytes(rig.OUTPUT_PINS)
            payload[388:396] = bytes(rig.OUTPUT_GPIO_BITS)
            struct.pack_into("<I", payload, 396, rig.OUTPUT_RATE_HZ)
            struct.pack_into("<I", payload, 400, rig.OUTPUT_PERIOD_TICKS)
            struct.pack_into("<I", payload, 404, rig.OUTPUT_CAPACITY_SEGMENTS)
            struct.pack_into("<I", payload, 408, rig.OUTPUT_LEGAL_STATE_MASK)
        payload = bytes(payload)
    total = rig.HEADER_SIZE + len(payload) + rig.TRAILER_SIZE
    header = rig.HEADER.pack(
        rig.MAGIC,
        rig.PROTOCOL_VERSION,
        kind,
        flags,
        rig.HEADER_SIZE,
        rig.BOOTSTRAP_CHECKSUM,
        0,
        total,
        len(payload),
        fields[9],
        0,
        request_id,
        0,
        0,
    )
    body = header + payload
    return cast(
        bytes,
        body + rig.TRAILER.pack(rig.compute_checksum(body, rig.BOOTSTRAP_CHECKSUM)),
    )


class FakeDevice:
    def __init__(
        self,
        *,
        stop_error: int = 0,
        zero_writes: int = 0,
        hardware_serial: int = 0x10203040,
    ) -> None:
        self.stop_error = stop_error
        self.zero_writes = zero_writes
        self.hardware_serial = hardware_serial
        self.pending = bytearray()
        self.requests: list[int] = []
        self.closed = False

    def write(self, data: bytes) -> int:
        if self.zero_writes:
            self.zero_writes -= 1
            return 0
        kind = rig.HEADER.unpack_from(data)[2]
        self.requests.append(kind)
        error = self.stop_error if kind == rig.STOP_REQUEST else 0
        self.pending.extend(
            response_wire(data, error=error, hardware_serial=self.hardware_serial)
        )
        return len(data)

    def read(self, size: int = 1) -> bytes:
        result = bytes(self.pending[:size])
        del self.pending[:size]
        return result

    def close(self) -> None:
        self.closed = True


def gpio_samples(program: Any, lag: int, count: int = 4096) -> list[tuple[int, int]]:
    samples: list[tuple[int, int]] = []
    for index in range(count):
        ticks = index * rig.GPIO_SAMPLE_PERIOD_TICKS
        state = (
            program.idle_state
            if ticks < lag
            else program.state_at((ticks - lag) // rig.OUTPUT_PERIOD_TICKS)
        )
        samples.append((ticks, state))
    return samples


class FixtureInterlockTests(unittest.TestCase):
    def test_exact_fixture_authorizes_only_its_device_and_owner(self) -> None:
        declaration = rig.parse_fixture_declaration(fixture_json())
        self.assertIsNotNone(declaration)
        interlock = rig.DriveInterlock(declaration)
        permit = interlock.authorize(0x10203040)
        interlock.validate(permit)

        with self.assertRaisesRegex(rig.InterlockDenied, "identities"):
            interlock.authorize(0x10203041)
        with self.assertRaisesRegex(rig.InterlockDenied, "refused"):
            rig.DriveInterlock(declaration).validate(permit)
        with self.assertRaisesRegex(rig.InterlockDenied, "no fixture"):
            rig.DriveInterlock(None).authorize(0x10203040)

    def test_missing_or_mismatched_fixture_never_writes_a_drive_request(self) -> None:
        for interlock, permit in (
            (rig.DriveInterlock(None), None),
            (
                rig.DriveInterlock(rig.parse_fixture_declaration(fixture_json())),
                None,
            ),
        ):
            device = FakeDevice()
            link = rig.SerialLink(device, interlock)
            with self.assertRaises(rig.InterlockDenied):
                link.exchange(rig.OUTPUT_ARM_REQUEST, permit=permit)
            self.assertEqual([], device.requests)
            self.assertEqual(0, link.drive_requests_written)

        declaration = rig.parse_fixture_declaration(fixture_json())
        assert declaration is not None
        interlock = rig.DriveInterlock(declaration)
        with self.assertRaises(rig.InterlockDenied):
            interlock.authorize(0x10203041)
        self.assertEqual([], FakeDevice().requests)

    def test_authorized_fake_device_accepts_arm_and_stalled_host_write(self) -> None:
        declaration = rig.parse_fixture_declaration(fixture_json())
        assert declaration is not None
        interlock = rig.DriveInterlock(declaration)
        permit = interlock.authorize(declaration.hardware_serial)
        device = FakeDevice(zero_writes=2)
        link = rig.SerialLink(device, interlock)
        with patch.object(rig.time, "sleep", return_value=None):
            frame, _latency = link.exchange(rig.OUTPUT_ARM_REQUEST, permit=permit)
        self.assertEqual(rig.OUTPUT_ARM_RESPONSE, frame.kind)
        self.assertEqual([rig.OUTPUT_ARM_REQUEST], device.requests)
        self.assertEqual(1, link.drive_requests_written)
        with self.assertRaisesRegex(rig.InterlockDenied, "non-drive"):
            link.exchange(rig.INFO_REQUEST, permit=permit)
        self.assertEqual([rig.OUTPUT_ARM_REQUEST], device.requests)

    def test_static_guards_keep_permits_at_the_serial_boundary(self) -> None:
        rig_source = RIG_PATH.read_text(encoding="utf-8")
        target_source = (ROOT / "firmware/src/digital_output_teensy.cpp").read_text(
            encoding="utf-8"
        )
        validate = rig_source.index("self.interlock.validate(permit)")
        encode = rig_source.index(
            "wire = encode_request(kind, request_id, payload, run_id=run_id)"
        )
        write = rig_source.index("self._write_all(wire, deadline)")
        self.assertLess(validate, encode)
        self.assertLess(validate, write)
        self.assertEqual(
            1,
            rig_source.count("return _DrivePermit("),
            "only DriveInterlock.authorize may mint a drive permit",
        )
        self.assertEqual(
            "frozenset({OUTPUT_ARM_REQUEST, START_REQUEST})",
            rig_source[
                rig_source.index("DRIVE_COMMAND_KINDS =")
                + len("DRIVE_COMMAND_KINDS =") : rig_source.index(
                    "\n", rig_source.index("DRIVE_COMMAND_KINDS =")
                )
            ].strip(),
        )
        self.assertEqual(1, target_source.count("claimPins(idle)"))
        self.assertLess(
            target_source.index("inspectTargetArm()"),
            target_source.index("claimPins(idle)"),
        )


class LoopbackGradingTests(unittest.TestCase):
    def test_stable_lag_is_unique_and_a_shift_is_rejected(self) -> None:
        program = rig.walking_program()
        stable = gpio_samples(program, 6)
        self.assertEqual(6, rig.infer_loopback_lag(program, stable))
        shifted = stable[:2048] + gpio_samples(program, 10)[2048:]
        with self.assertRaisesRegex(rig.CampaignFailure, "one bounded fixed lag"):
            rig.infer_loopback_lag(program, shifted)

    def test_bit_swap_stale_skip_and_duplicate_transitions_fail(self) -> None:
        program = rig.walking_program()
        swapped = [
            (ticks, ((state & 1) << 1) | ((state & 2) >> 1) | (state & ~3))
            for ticks, state in gpio_samples(program, 4)
        ]
        with self.assertRaises(rig.CampaignFailure):
            rig.infer_loopback_lag(program, swapped)

        exact = gpio_samples(program, 4, 96)
        mutations = {
            "skipped": exact[:20] + exact[24:],
            "duplicate": exact[:20] + [exact[19]] + exact[20:],
            "stale": exact[:20] + [(exact[20][0], exact[19][1])] + exact[21:],
        }
        for name, samples in mutations.items():
            with self.subTest(name=name):
                grader = rig.IntervalGrader(program, 4)
                for ticks, state in samples:
                    grader.accept(ticks, state)
                with self.assertRaises(rig.CampaignFailure):
                    grader.finish()

    def test_acquisition_loss_and_sequence_discontinuity_are_rejected(self) -> None:
        program = rig.walking_program()
        validator = rig.CaptureValidator(program, rig.BOOTSTRAP_CHECKSUM, 9, 4, False)
        validator.grader = rig.IntervalGrader(program, 4)
        payload = bytes(
            program.state_at(max(0, (index * 2 - 4) // 8))
            for index in range(rig.GPIO_SAMPLES_PER_FRAME)
        )
        first = rig.Frame(
            rig.GPIO_DATA,
            0,
            rig.BOOTSTRAP_CHECKSUM,
            9,
            0,
            0,
            0,
            rig.GPIO_SAMPLES_PER_FRAME,
            payload,
        )
        validator.accept(first)
        lost = rig.Frame(
            rig.GPIO_DATA,
            rig.FLAG_GAP_BEFORE,
            rig.BOOTSTRAP_CHECKSUM,
            9,
            2,
            0,
            2 * rig.FRAME_COVERAGE_TICKS,
            rig.GPIO_SAMPLES_PER_FRAME,
            payload,
        )
        with self.assertRaisesRegex(rig.CampaignFailure, "discontinuous"):
            validator.accept(lost)


class RecoveryAndReportTests(unittest.TestCase):
    def test_main_missing_or_mismatched_fixture_is_inconclusive_and_non_driving(
        self,
    ) -> None:
        for fixture in (None, fixture_json(0x10203041)):
            with self.subTest(fixture=fixture):
                device = FakeDevice(hardware_serial=0x10203040)
                environment = {"SERIAL_PORT": "fake"}
                if fixture is not None:
                    environment["AUX_OUTPUT_FIXTURE_JSON"] = fixture
                output = io.StringIO()
                with (
                    patch.dict(os.environ, environment, clear=True),
                    patch.object(rig.serial, "Serial", return_value=device),
                    patch.object(rig, "STARTUP_DRAIN_SECONDS", 0.0),
                    contextlib.redirect_stdout(output),
                ):
                    result = rig.main()
                records = [
                    line
                    for line in output.getvalue().splitlines()
                    if line.startswith(rig.RESULT_PREFIX)
                ]
                self.assertEqual(0, result, output.getvalue())
                self.assertEqual(1, len(records), output.getvalue())
                payload = json.loads(records[0][len(rig.RESULT_PREFIX) :])
                self.assertEqual("INCONCLUSIVE", payload["result"])
                self.assertEqual(0, payload["evidence"]["drive_requests_written"])
                self.assertEqual([rig.INFO_REQUEST, rig.STOP_REQUEST], device.requests)
                self.assertTrue(device.closed)

    def test_disconnect_reopen_replaces_and_closes_fake_device(self) -> None:
        declaration = rig.parse_fixture_declaration(fixture_json())
        assert declaration is not None
        interlock = rig.DriveInterlock(declaration)
        old = FakeDevice()
        replacement = FakeDevice()
        campaign = rig.Campaign(
            "fake-port",
            rig.SerialLink(old, interlock),
            interlock,
            interlock.authorize(declaration.hardware_serial),
            rig.DeviceInfo(declaration.hardware_serial, "fake-build", 1, 0),
            rig.MemoryMonitor(),
        )
        with (
            patch.object(rig.serial, "Serial", return_value=replacement),
            patch.object(rig, "REOPEN_SETTLE_SECONDS", 0.0),
        ):
            campaign._disconnect_reopen()
        self.assertTrue(old.closed)
        self.assertIs(replacement, campaign.link.port)

    def test_stop_failure_is_explicit_and_report_retains_failure(self) -> None:
        device = FakeDevice(stop_error=3)
        link = rig.SerialLink(device, rig.DriveInterlock(None))
        frame, _ = link.exchange(rig.STOP_REQUEST)
        with self.assertRaisesRegex(rig.CampaignFailure, "rejected"):
            rig.response_success(frame, rig.STOP_RESPONSE)
        report = rig.build_result(
            result="FAIL",
            reason="final STOP/hold attempt failed",
            fixture_sha256=None,
            info=None,
            cases=[],
            failures=["final STOP failed: fake disconnect"],
            memory=rig.MemoryMonitor(),
            drive_requests_written=0,
        )
        self.assertEqual("FAIL", report["result"])
        self.assertIn("final STOP failed", report["evidence"]["failures"][0])

    def test_main_emits_one_result_on_each_preflight_exit(self) -> None:
        scenarios: tuple[tuple[dict[str, str], OSError | None], ...] = (
            ({}, None),
            ({"SERIAL_PORT": "fake", "AUX_OUTPUT_MODE": "invalid"}, None),
            (
                {"SERIAL_PORT": "fake", "AUX_OUTPUT_FIXTURE_JSON": "{"},
                None,
            ),
            (
                {"SERIAL_PORT": "fake", "AUX_OUTPUT_FIXTURE_JSON": "[]"},
                None,
            ),
            ({"SERIAL_PORT": "fake"}, OSError("fake open failure")),
        )
        for environment, serial_error in scenarios:
            with self.subTest(environment=environment, serial_error=serial_error):
                output = io.StringIO()
                serial_patch = (
                    patch.object(rig.serial, "Serial", side_effect=serial_error)
                    if serial_error is not None
                    else contextlib.nullcontext()
                )
                with (
                    patch.dict(os.environ, environment, clear=True),
                    serial_patch,
                    contextlib.redirect_stdout(output),
                ):
                    result = rig.main()
                records = [
                    line
                    for line in output.getvalue().splitlines()
                    if line.startswith(rig.RESULT_PREFIX)
                ]
                self.assertEqual(1, len(records), output.getvalue())
                payload = json.loads(records[0][len(rig.RESULT_PREFIX) :])
                self.assertIn(payload["result"], {"NOT_RUN", "FAIL"})
                self.assertNotEqual(0, result)


if __name__ == "__main__":
    unittest.main()
