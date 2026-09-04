"""Deterministic auxiliary-output simulator lifecycle and trace tests."""

from __future__ import annotations

import struct
import unittest

from thingdaq import (
    ADCBlock,
    DigitalOutputProgram,
    GPIOBlock,
    InMemoryTransport,
    OutputBankMode,
    OutputError,
    OutputState,
    OutputTraceEvent,
    SimulatedDevice,
    SimulatorTraceUnavailableError,
    ThingDAQ,
)
from thingdaq._generated import protocol_v2_constants as v2
from thingdaq.protocol import IncrementalFrameParser
from thingdaq.protocol_v2 import V2Frame, decode_v2_response, encode_v2_frame


def _v2_request(
    device: SimulatedDevice,
    kind: v2.FrameKind,
    *,
    request_id: int,
    generation: int,
    payload: bytes = b"",
):
    wire = encode_v2_frame(
        kind,
        payload,
        run_id=generation,
        request_id=request_id,
    )
    response = device.receive(wire)
    assert len(response) == 1
    decoded = IncrementalFrameParser(accept_protocol_v2=True).feed(response[0])
    assert len(decoded) == 1 and isinstance(decoded[0], V2Frame)
    return decode_v2_response(decoded[0])


class OutputSimulatorTests(unittest.TestCase):
    def test_every_tick_boundary_repeat_completion_and_hold_is_exact(self) -> None:
        with ThingDAQ.simulated(output_enabled=True) as daq:
            program = DigitalOutputProgram.finite(
                [(1, 0x01), (2, 0x02), (1, 0x04)],
                3,
                idle_state_mask=0x80,
            )
            daq.upload_output(program, generation=71)
            daq.output_arm()
            daq.configure(adc=True, gpio=True)
            run_id = daq.start()
            device = daq.transport.device

            before_reads = daq.output_status()
            for _ in range(3):
                self.assertEqual(before_reads, daq.output_status())
            self.assertEqual(96, device.advance_time(96))
            expected_states = ([0x01] + [0x02] * 2 + [0x04]) * 3
            samples = device.sample_output(
                [index * 8 for index in range(len(expected_states))],
                run_id=run_id,
            )
            self.assertEqual(expected_states, [sample.state_mask for sample in samples])
            complete = daq.output_status()
            self.assertIs(OutputState.HELD, complete.state)
            self.assertEqual(3, complete.completed_repeats)
            self.assertEqual(9, complete.transitions_emitted)
            self.assertEqual(0x04, complete.last_emitted_state_mask)
            self.assertEqual(run_id, complete.common_run_id)
            self.assertEqual(12, complete.requested_duration_states)
            self.assertEqual(12, complete.states_expanded)
            self.assertEqual(12, complete.dma_states_queued)
            self.assertEqual(12, complete.dma_states_emitted)
            self.assertEqual(0, complete.held_remainder_states)
            self.assertEqual(complete.blocks_filled, complete.blocks_completed)
            self.assertEqual(96, complete.completion_tick)
            self.assertEqual(96, complete.hold_tick)
            self.assertTrue(complete.conservation_exact)
            self.assertEqual(
                [0, 8, 24, 32, 40, 56, 64, 72, 88, 96],
                [event.tick for event in device.output_trace if event.run_id == run_id],
            )

    def test_finite_boundaries_sampling_and_acquisition_are_independent(self) -> None:
        with ThingDAQ.simulated(output_enabled=True) as daq:
            program = DigitalOutputProgram.finite(
                [(2, 0x01), (1, 0x02)],
                2,
                idle_state_mask=0x80,
            )
            daq.upload_output(program, generation=77)
            armed = daq.output_arm()
            self.assertEqual(0x80, armed.current_state_mask)
            daq.configure(adc=True, gpio=True)
            run_id = daq.start()

            device = daq.transport.device
            tick_zero = daq.output_status()
            self.assertIs(OutputState.RUNNING, tick_zero.state)
            self.assertEqual(0, tick_zero.ticks_elapsed)
            self.assertEqual(1, tick_zero.transitions_emitted)

            blocks = (daq.read_block(timeout=0.5), daq.read_block(timeout=0.5))
            self.assertEqual(
                {ADCBlock, GPIOBlock},
                {type(block) for block in blocks},
            )
            self.assertEqual(tick_zero, daq.output_status())

            self.assertEqual(48, device.advance_time(48))
            completed = daq.output_status()
            self.assertIs(OutputState.HELD, completed.state)
            self.assertEqual(2, completed.completed_repeats)
            self.assertEqual(4, completed.transitions_emitted)
            self.assertEqual(0x02, completed.last_emitted_state_mask)
            self.assertEqual(
                [0x01, 0x01, 0x02, 0x02, 0x01, 0x02, 0x02],
                [
                    sample.state_mask
                    for sample in device.sample_output(
                        [0, 2, 16, 22, 24, 40, 48], run_id=run_id
                    )
                ],
            )
            self.assertEqual(
                [0, 16, 24, 40, 48],
                [event.tick for event in device.output_trace if event.run_id == run_id],
            )
            self.assertIs(OutputTraceEvent.COMPLETE, device.output_trace[-1].event)

    def test_infinite_stop_release_and_bounded_trace(self) -> None:
        device = SimulatedDevice(output_enabled=True, max_output_trace_events=4)
        with ThingDAQ.open(InMemoryTransport(device)) as daq:
            program = DigitalOutputProgram.forever(
                [(1, 0x11), (1, 0x22)], idle_state_mask=0x44
            )
            daq.upload_output(program, generation=9)
            daq.output_arm()
            daq.configure(adc=True, gpio=False)
            run_id = daq.start()
            device.advance_time(40)

            running = daq.output_status()
            self.assertIs(OutputState.RUNNING, running.state)
            self.assertEqual(2, running.completed_repeats)
            self.assertEqual(6, running.transitions_emitted)
            self.assertEqual(run_id, running.common_run_id)
            self.assertEqual(6, running.dma_states_emitted)
            self.assertEqual(4064, running.refill_lead)
            self.assertEqual(
                running.states_expanded,
                running.dma_states_emitted + running.refill_lead,
            )
            self.assertTrue(running.conservation_exact)
            self.assertGreater(device.output_trace_dropped, 0)
            with self.assertRaises(SimulatorTraceUnavailableError):
                device.sample_output(0, run_id=run_id)

            self.assertEqual(0x22, running.current_state_mask)
            daq.stop()
            held = daq.output_status()
            self.assertIs(OutputState.HELD, held.state)
            self.assertEqual(0x22, held.last_emitted_state_mask)
            self.assertEqual(0, held.refill_lead)
            self.assertEqual(4064, held.held_remainder_states)
            self.assertEqual(
                held.states_expanded,
                held.dma_states_emitted + held.held_remainder_states,
            )
            self.assertEqual(1, held.stop_operations)
            self.assertTrue(held.conservation_exact)
            released = daq.output_clear()
            self.assertIs(OutputState.EMPTY, released.state)
            self.assertIs(OutputBankMode.DISABLED, released.bank_mode)
            sample = device.sample_output(40, run_id=run_id)
            self.assertIsNone(sample.state_mask)
            self.assertIs(OutputBankMode.DISABLED, sample.bank_mode)
            self.assertIs(OutputTraceEvent.RELEASE, device.output_trace[-1].event)

    def test_disconnect_reconnect_preserves_running_epoch(self) -> None:
        device = SimulatedDevice(output_enabled=True)
        daq = ThingDAQ.open(InMemoryTransport(device))
        program = DigitalOutputProgram.forever([(1, 1), (1, 2)])
        daq.upload_output(program, generation=1)
        daq.output_arm()
        daq.configure(adc=True, gpio=True)
        run_id = daq.start()
        daq.close(stop=False)

        device.advance_time(8)
        reopened = ThingDAQ.open(InMemoryTransport(device))
        try:
            self.assertEqual(run_id, reopened.run_id)
            reopened.discover_output()
            output = reopened.output_status()
            self.assertIs(OutputState.RUNNING, output.state)
            self.assertEqual(8, output.ticks_elapsed)
            self.assertEqual(0x02, output.current_state_mask)
            self.assertEqual(run_id, reopened.read_block(timeout=0.5).run_id)
        finally:
            reopened.close(stop=False)

    def test_injected_fault_stops_common_run_and_clear_recovers(self) -> None:
        with ThingDAQ.simulated(output_enabled=True) as daq:
            daq.upload_output(
                DigitalOutputProgram.forever([(1, 0x01), (1, 0x02)]),
                generation=17,
            )
            daq.output_arm()
            daq.configure(adc=True, gpio=True)
            daq.start()
            device = daq.transport.device
            device.advance_time(8)

            fault = device.inject_output_fault(OutputError.UNDERRUN)
            self.assertIs(OutputState.FAULTED, fault.state)
            self.assertIs(OutputError.UNDERRUN, fault.output_error)
            self.assertEqual(0x02, fault.last_emitted_state_mask)
            self.assertEqual(1, fault.underruns)
            self.assertEqual(0, fault.refill_lead)
            self.assertEqual(4064, fault.held_remainder_states)
            self.assertTrue(fault.conservation_exact)
            self.assertIsNone(device.next_data_frame())
            self.assertIs(OutputTraceEvent.FAULT, device.output_trace[-1].event)

            self.assertFalse(daq.status().stream_mask)
            self.assertIs(OutputState.FAULTED, daq.output_status().state)
            self.assertIs(OutputState.EMPTY, daq.output_clear().state)

    def test_both_fault_kinds_hold_exact_state_and_stop_adc_gpio(self) -> None:
        for generation, error in enumerate(
            (OutputError.UNDERRUN, OutputError.DMA_FAULT), start=41
        ):
            with (
                self.subTest(error=error.name),
                ThingDAQ.simulated(output_enabled=True) as daq,
            ):
                daq.upload_output(
                    DigitalOutputProgram.forever([(1, 0x10), (1, 0x20), (1, 0x40)]),
                    generation=generation,
                )
                daq.output_arm()
                daq.configure(adc=True, gpio=True)
                daq.start()
                device = daq.transport.device
                device.advance_time(16)
                fault = device.inject_output_fault(error)
                self.assertIs(OutputState.FAULTED, fault.state)
                self.assertIs(error, fault.output_error)
                self.assertEqual(0x40, fault.last_emitted_state_mask)
                self.assertFalse(daq.status().stream_mask)
                self.assertIsNone(device.next_data_frame())
                with self.assertRaisesRegex(Exception, "only during a common run"):
                    device.advance_time(1)

    def test_output_clock_progress_does_not_interrupt_adc_gpio_delivery(self) -> None:
        with ThingDAQ.simulated(output_enabled=True) as daq:
            daq.upload_output(
                DigitalOutputProgram.forever([(1, 0x01), (1, 0x02)]),
                generation=52,
            )
            daq.output_arm()
            daq.configure(adc=True, gpio=True)
            run_id = daq.start()
            device = daq.transport.device
            for expected_tick in (8, 16, 24, 32):
                device.advance_time(8)
                blocks = (daq.read_block(timeout=0.5), daq.read_block(timeout=0.5))
                self.assertEqual(
                    {ADCBlock, GPIOBlock}, {type(block) for block in blocks}
                )
                self.assertTrue(all(block.run_id == run_id for block in blocks))
                self.assertEqual(expected_tick, daq.output_status().ticks_elapsed)

    def test_upload_generation_canonical_and_checksum_errors_are_typed(self) -> None:
        device = SimulatedDevice(output_enabled=True)
        begin = _v2_request(
            device,
            v2.FrameKind.OUTPUT_BEGIN_REQUEST,
            request_id=1,
            generation=10,
            payload=struct.pack("<II", 1, 0),
        )
        self.assertTrue(begin.ok)
        append = struct.pack("<II", 2, 0x33)
        self.assertTrue(
            _v2_request(
                device,
                v2.FrameKind.OUTPUT_APPEND_REQUEST,
                request_id=2,
                generation=10,
                payload=append,
            ).ok
        )
        duplicate = _v2_request(
            device,
            v2.FrameKind.OUTPUT_APPEND_REQUEST,
            request_id=3,
            generation=10,
            payload=struct.pack("<II", 3, 0x33),
        )
        self.assertFalse(duplicate.ok)
        self.assertIs(OutputError.INVALID_SEGMENT, duplicate.output_error)

        replacement = _v2_request(
            device,
            v2.FrameKind.OUTPUT_BEGIN_REQUEST,
            request_id=4,
            generation=11,
            payload=struct.pack("<II", 1, 0),
        )
        self.assertTrue(replacement.ok)
        self.assertTrue(
            _v2_request(
                device,
                v2.FrameKind.OUTPUT_APPEND_REQUEST,
                request_id=5,
                generation=11,
                payload=append,
            ).ok
        )
        checksum = _v2_request(
            device,
            v2.FrameKind.OUTPUT_COMMIT_REQUEST,
            request_id=6,
            generation=11,
            payload=struct.pack("<II", 1, 0),
        )
        self.assertFalse(checksum.ok)
        self.assertIs(OutputError.CHECKSUM_MISMATCH, checksum.output_error)
        stale = _v2_request(
            device,
            v2.FrameKind.OUTPUT_BEGIN_REQUEST,
            request_id=7,
            generation=10,
            payload=struct.pack("<II", 1, 0),
        )
        self.assertFalse(stale.ok)
        self.assertIs(OutputError.GENERATION_MISMATCH, stale.output_error)


if __name__ == "__main__":
    unittest.main()
