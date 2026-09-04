"""Focused immutable output-model and typed client API tests."""

from __future__ import annotations

import struct
import unittest
import zlib
from pathlib import Path
from typing import Any

from thingdaq import (
    DigitalOutputAppendEcho,
    DigitalOutputCapabilities,
    DigitalOutputProgram,
    DigitalOutputProgramError,
    DigitalOutputSegment,
    DigitalOutputStatus,
    DigitalOutputUnavailableError,
    DigitalOutputUploadError,
    OutputBankMode,
    OutputError,
    OutputState,
    ThingDAQ,
)
from thingdaq._generated import protocol_constants as v1
from thingdaq._generated import protocol_v2_constants as v2
from thingdaq.models import CommandResponse
from thingdaq.protocol import IncrementalFrameParser
from thingdaq.protocol_v2 import V2Frame, decode_v2_response

ROOT = Path(__file__).resolve().parents[2]


def _status(
    state: OutputState,
    generation: int,
    *,
    program: DigitalOutputProgram | None = None,
    accepted: int = 0,
) -> DigitalOutputStatus:
    return DigitalOutputStatus(
        state=state,
        bank_mode=(
            OutputBankMode.OUTPUT
            if state in {OutputState.ARMED, OutputState.RUNNING, OutputState.HELD}
            else OutputBankMode.DISABLED
        ),
        fault_latched=False,
        generation=generation,
        idle_state_mask=0 if program is None else program.idle_state_mask,
        current_state_mask=0,
        last_emitted_state_mask=0,
        repeat_count=0 if program is None else program.repeat_count,
        completed_repeats=0,
        segment_count=(
            len(program.segments)
            if program is not None and state is not OutputState.LOADING
            else 0
        ),
        accepted_segment_count=accepted,
        program_checksum=(
            program.checksum
            if program is not None and state is not OutputState.LOADING
            else 0
        ),
        current_segment_index=0,
        ticks_elapsed=0,
        transitions_emitted=0,
        output_error=OutputError.NONE,
    )


class DigitalOutputModelTests(unittest.TestCase):
    def test_builder_coalesces_and_checksums_exact_canonical_bytes(self) -> None:
        program = DigitalOutputProgram.finite(
            [(2, 0x11), DigitalOutputSegment.hold(3, 0x11), (7, 0x22)],
            4,
            idle_state_mask=0x80,
        )
        self.assertEqual(
            (DigitalOutputSegment(5, 0x11), DigitalOutputSegment(7, 0x22)),
            program.segments,
        )
        expected = struct.pack("<IIII", 5, 0x11, 7, 0x22)
        self.assertEqual(expected, program.canonical_bytes)
        self.assertEqual(zlib.adler32(expected) & 0xFFFFFFFF, program.checksum)
        self.assertEqual(12, program.duration_samples)
        self.assertEqual(4, program.repeat_count)

    def test_forever_hold_and_invalid_programs_are_typed_and_immutable(self) -> None:
        forever = DigitalOutputProgram.forever([(1, 0), (1, 1)])
        hold = DigitalOutputProgram.hold(10, 0xAA, idle_state_mask=0x55)
        self.assertEqual(0, forever.repeat_count)
        self.assertEqual((DigitalOutputSegment(10, 0xAA),), hold.segments)
        with self.assertRaises(ValueError):
            DigitalOutputSegment(0, 0)
        with self.assertRaises(ValueError):
            DigitalOutputSegment(1, 0x100)
        with self.assertRaises(DigitalOutputProgramError):
            DigitalOutputProgram(())
        with self.assertRaises(DigitalOutputProgramError):
            DigitalOutputProgram(
                (DigitalOutputSegment(1, 1), DigitalOutputSegment(2, 1))
            )

    def test_generated_v2_info_and_output_fixtures_decode_on_shared_parser(
        self,
    ) -> None:
        parser = IncrementalFrameParser(accept_protocol_v2=True)
        names_and_types = {
            "info-response.bin": DigitalOutputCapabilities,
            "output-begin-response.bin": DigitalOutputStatus,
            "output-append-response.bin": DigitalOutputAppendEcho,
        }
        for name, expected_type in names_and_types.items():
            with self.subTest(name=name):
                decoded = parser.feed(
                    (ROOT / "protocol/fixtures-v2" / name).read_bytes()
                )
                self.assertEqual(1, len(decoded))
                self.assertIsInstance(decoded[0], V2Frame)
                self.assertIsInstance(
                    decode_v2_response(decoded[0]).value, expected_type
                )


class DigitalOutputClientTests(unittest.TestCase):
    def setUp(self) -> None:
        self.daq = ThingDAQ.simulated(control_only=True, command_timeout=0.1)
        self.original_request = self.daq._reader.request
        info_frame = IncrementalFrameParser(accept_protocol_v2=True).feed(
            (ROOT / "protocol/fixtures-v2/info-response.bin").read_bytes()
        )[0]
        assert isinstance(info_frame, V2Frame)
        capabilities = decode_v2_response(info_frame).value
        assert isinstance(capabilities, DigitalOutputCapabilities)
        self.capabilities = capabilities
        self.calls: list[tuple[v2.FrameKind, bytes, int]] = []
        self.program: DigitalOutputProgram | None = None
        self.accepted = 0
        self.corrupt_append_echo = False

        def request(
            kind: Any, payload: bytes = b"", **options: Any
        ) -> CommandResponse[Any]:
            if options.get("protocol_version", 1) == 1:
                return self.original_request(kind, payload, **options)
            selected = v2.FrameKind(kind)
            generation = options.get("run_id", 0)
            if selected is v2.FrameKind.INFO_REQUEST:
                return self._response(selected, 0, self.capabilities)
            self.calls.append((selected, bytes(payload), generation))
            if selected is v2.FrameKind.OUTPUT_BEGIN_REQUEST:
                assert self.program is not None
                self.accepted = 0
                value: object = _status(
                    OutputState.LOADING, generation, program=self.program
                )
            elif selected is v2.FrameKind.OUTPUT_APPEND_REQUEST:
                self.accepted += 1
                value = DigitalOutputAppendEcho(
                    self.accepted, DigitalOutputSegment(*struct.unpack("<II", payload))
                )
                if self.corrupt_append_echo:
                    value = DigitalOutputAppendEcho(self.accepted + 1, value.segment)
            elif selected is v2.FrameKind.OUTPUT_COMMIT_REQUEST:
                assert self.program is not None
                value = _status(
                    OutputState.COMMITTED,
                    generation,
                    program=self.program,
                    accepted=self.accepted,
                )
            elif selected in {
                v2.FrameKind.OUTPUT_ARM_REQUEST,
                v2.FrameKind.OUTPUT_STATUS_REQUEST,
            }:
                value = _status(
                    OutputState.ARMED,
                    generation,
                    program=self.program,
                    accepted=self.accepted,
                )
            else:
                value = _status(OutputState.EMPTY, generation)
            return self._response(selected, generation, value)

        self.daq._reader.request = request  # type: ignore[method-assign]

    def tearDown(self) -> None:
        self.daq._reader.request = self.original_request  # type: ignore[method-assign]
        self.daq.close()

    @staticmethod
    def _response(
        request: v2.FrameKind, generation: int, value: object
    ) -> CommandResponse[Any]:
        return CommandResponse(
            kind=v2.REQUEST_RESPONSE_KIND[request],  # type: ignore[arg-type]
            request_id=1,
            run_id=generation,
            status=v1.ResponseStatus.OK,
            error_code=v1.ErrorCode.OK,
            value=value,
        )

    def test_upload_arm_status_clear_are_bounded_correlated_and_exact(self) -> None:
        program = DigitalOutputProgram.finite(
            [(5, 1), (7, 2), (9, 4)], 3, idle_state_mask=0x80
        )
        self.program = program
        committed = self.daq.upload_output(program, generation=77)
        self.assertIs(OutputState.COMMITTED, committed.state)
        self.assertIs(OutputState.ARMED, self.daq.output_arm().state)
        self.assertIs(OutputState.ARMED, self.daq.output_status().state)
        self.assertIs(OutputState.EMPTY, self.daq.output_clear().state)
        self.assertEqual(
            [
                v2.FrameKind.OUTPUT_BEGIN_REQUEST,
                v2.FrameKind.OUTPUT_APPEND_REQUEST,
                v2.FrameKind.OUTPUT_APPEND_REQUEST,
                v2.FrameKind.OUTPUT_APPEND_REQUEST,
                v2.FrameKind.OUTPUT_COMMIT_REQUEST,
                v2.FrameKind.OUTPUT_ARM_REQUEST,
                v2.FrameKind.OUTPUT_STATUS_REQUEST,
                v2.FrameKind.OUTPUT_CLEAR_REQUEST,
            ],
            [call[0] for call in self.calls],
        )
        self.assertTrue(all(len(payload) <= 8 for _, payload, _ in self.calls))
        self.assertTrue(all(generation == 77 for _, _, generation in self.calls))
        self.assertEqual(struct.pack("<II", 3, 0x80), self.calls[0][1])
        self.assertEqual(
            struct.pack("<II", len(program.segments), program.checksum),
            self.calls[4][1],
        )

    def test_v1_acquisition_remains_usable_and_output_is_opt_in(self) -> None:
        self.assertIsNone(self.daq.output_capabilities)
        configured = self.daq.configure_control_only()
        self.assertFalse(configured.stream_mask)
        run_id = self.daq.start()
        self.assertGreater(run_id, 0)
        self.assertIs(v1.DeviceState.IDLE, self.daq.stop())

    def test_interrupted_upload_clears_partial_device_state(self) -> None:
        self.program = DigitalOutputProgram.from_segments([(2, 1), (3, 2)])
        self.corrupt_append_echo = True
        with self.assertRaises(DigitalOutputUploadError) as raised:
            self.daq.upload_output(self.program, generation=91)
        self.assertIsNone(raised.exception.cleanup_error)
        self.assertEqual(v2.FrameKind.OUTPUT_CLEAR_REQUEST, self.calls[-1][0])
        self.assertIsNone(self.daq._output_generation)

    def test_missing_capability_is_a_typed_unavailable_error(self) -> None:
        def unavailable(
            kind: Any, payload: bytes = b"", **options: Any
        ) -> CommandResponse[Any]:
            if options.get("protocol_version", 1) == 1:
                return self.original_request(kind, payload, **options)
            return CommandResponse(
                kind=v2.FrameKind.ERROR_RESPONSE,  # type: ignore[arg-type]
                request_id=1,
                run_id=0,
                status=v1.ResponseStatus.ERROR,
                error_code=v1.ErrorCode.UNSUPPORTED_VERSION,
            )

        self.daq._reader.request = unavailable  # type: ignore[method-assign]
        with self.assertRaises(DigitalOutputUnavailableError):
            self.daq.discover_output()
        self.assertFalse(self.daq.configure_control_only().stream_mask)


if __name__ == "__main__":
    unittest.main()
