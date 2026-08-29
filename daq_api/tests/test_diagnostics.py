"""Firmware counter conservation, saturation, and fault-snapshot tests."""

from __future__ import annotations

import io
import unittest
from dataclasses import replace

from teensy_daq import (
    ChecksumAlgorithm,
    DeviceState,
    EquationState,
    Source,
    Status,
    StreamMask,
    reconcile_run_counters,
    snapshot_firmware_faults,
)
from teensy_daq._generated import protocol_constants as constants
from teensy_daq.cli import _print_reconciliation


def _adc_status(*, live: bool = False) -> Status:
    generated = 2
    framed = 1 if live else 2
    transmitted = 0 if live else 2
    ready = 1 if live else 0
    filling = 1 if live else 0
    emitted = transmitted
    return Status(
        device_state=DeviceState.RUNNING if live else DeviceState.IDLE,
        stream_mask=StreamMask.ADC if live else StreamMask.NONE,
        source=Source.SYNTHETIC,
        data_checksum_algorithm=ChecksumAlgorithm.ADLER32,
        adc_frames_emitted=emitted,
        adc_frames_generated=generated,
        adc_items_generated=generated * constants.ADC_PAIRS_PER_FRAME,
        adc_frames_framed_pipeline=framed,
        adc_items_framed_pipeline=framed * constants.ADC_PAIRS_PER_FRAME,
        adc_items_emitted=emitted * constants.ADC_PAIRS_PER_FRAME,
        adc_frames_transmitted=transmitted,
        adc_items_transmitted_pipeline=(transmitted * constants.ADC_PAIRS_PER_FRAME),
        adc_payload_bytes_produced=generated * constants.DATA_PAYLOAD_BYTES,
        adc_payload_bytes_framed=framed * constants.DATA_PAYLOAD_BYTES,
        adc_payload_bytes_emitted=emitted * constants.DATA_PAYLOAD_BYTES,
        adc_payload_bytes_transmitted=(transmitted * constants.DATA_PAYLOAD_BYTES),
        adc_framed_bytes_framed=framed * constants.DATA_FRAME_BYTES,
        adc_framed_bytes_emitted=emitted * constants.DATA_FRAME_BYTES,
        adc_framed_bytes_transmitted=(transmitted * constants.DATA_FRAME_BYTES),
        adc_packet_filling_depth=filling,
        adc_packet_ready_depth=ready,
        adc_packet_ready_high_water=ready,
        packet_ready_depth=ready,
        packet_ready_high_water=ready,
        packet_owned_depth=filling + ready,
        packet_owned_high_water=filling + ready,
        packet_frames_promoted=emitted,
        data_payload_bytes_transmitted=(transmitted * constants.DATA_PAYLOAD_BYTES),
        data_framed_bytes_transmitted=(transmitted * constants.DATA_FRAME_BYTES),
    )


class DiagnosticReconciliationTests(unittest.TestCase):
    def test_stopped_and_live_queue_snapshots_reconcile_exactly(self) -> None:
        for status in (_adc_status(), _adc_status(live=True)):
            with self.subTest(state=status.device_state.name):
                report = reconcile_run_counters(status, run_id=17)
                self.assertTrue(report.exact)
                self.assertIsNone(report.first_inconsistent_counter)
                self.assertIsNone(report.first_indeterminate_counter)
                self.assertEqual(17, report.run_id)

    def test_pressure_drop_reconciles_every_packet_ownership_stage(self) -> None:
        pairs = constants.ADC_PAIRS_PER_FRAME
        payload = constants.DATA_PAYLOAD_BYTES
        frame = constants.DATA_FRAME_BYTES
        status = replace(
            _adc_status(live=True),
            adc_packet_filling_depth=0,
            packet_owned_depth=1,
            adc_frames_generated=3,
            adc_items_generated=3 * pairs,
            adc_frames_framed_pipeline=3,
            adc_items_framed_pipeline=3 * pairs,
            adc_frames_emitted=1,
            adc_items_emitted=pairs,
            adc_frames_transmitted=1,
            adc_items_transmitted_pipeline=pairs,
            adc_frames_dropped=1,
            adc_items_dropped=pairs,
            adc_payload_bytes_produced=3 * payload,
            adc_payload_bytes_framed=3 * payload,
            adc_payload_bytes_emitted=payload,
            adc_payload_bytes_transmitted=payload,
            adc_payload_bytes_dropped=payload,
            adc_framed_bytes_framed=3 * frame,
            adc_framed_bytes_emitted=frame,
            adc_framed_bytes_transmitted=frame,
            adc_frames_dropped_after_framing=1,
            adc_frames_evicted=1,
            packet_pressure_evictions=1,
            packet_pool_exhaustions=1,
            packet_frames_promoted=1,
            data_payload_bytes_transmitted=payload,
            data_framed_bytes_transmitted=frame,
        )

        report = reconcile_run_counters(status, run_id=18)

        self.assertTrue(report.exact)
        self.assertEqual("adc_items_dropped", report.fault_snapshot.faults[0].counter)
        self.assertIn(
            "packet_pressure_evictions",
            {fault.counter for fault in report.fault_snapshot.faults},
        )

    def test_first_inconsistent_and_saturated_counters_are_distinct(self) -> None:
        inconsistent = replace(
            _adc_status(),
            adc_items_generated=2 * constants.ADC_PAIRS_PER_FRAME - 1,
        )
        failed = reconcile_run_counters(inconsistent)
        self.assertFalse(failed.exact)
        self.assertEqual("adc_items_generated", failed.first_inconsistent_counter)
        self.assertIsNone(failed.first_indeterminate_counter)

        saturated = replace(_adc_status(), adc_items_generated=constants.UINT64_MAX)
        indeterminate = reconcile_run_counters(saturated)
        self.assertFalse(indeterminate.exact)
        self.assertIsNone(indeterminate.first_inconsistent_counter)
        self.assertEqual(
            "adc_items_generated", indeterminate.first_indeterminate_counter
        )
        self.assertEqual(EquationState.SATURATED, indeterminate.equations[0].state)

    def test_fault_snapshot_preserves_counter_units_and_categories(self) -> None:
        status = replace(
            _adc_status(),
            adc_dma_error_events=2,
            response_queue_rejections=1,
            partial_usb_writes=3,
        )

        snapshot = snapshot_firmware_faults(status, run_id=19)

        faults = {fault.counter: fault for fault in snapshot.faults}
        self.assertEqual("events", faults["adc_dma_error_events"].unit)
        self.assertEqual("response", faults["response_queue_rejections"].category)
        self.assertEqual("writes", faults["partial_usb_writes"].unit)
        self.assertEqual(19, snapshot.run_id)

    def test_extended_status_fields_round_trip_and_report_first_failure(self) -> None:
        status = replace(
            _adc_status(live=True),
            gpio_buffers_completed=7,
            gpio_buffers_acquired=6,
            gpio_buffers_released=6,
            gpio_samples_delivered=24_288,
            gpio_frames_produced=5,
            gpio_samples_produced=20_240,
            gpio_frames_packed=5,
            adc_frames_consumed=2,
            adc_pairs_consumed=2_024,
            responses_queued=9,
            responses_completed=8,
            usb_active_frame_size=1_276,
            usb_active_frame_bytes_sent=511,
        )
        self.assertEqual(status, Status.from_payload(status.to_payload()))

        report = reconcile_run_counters(
            replace(status, adc_items_generated=status.adc_items_generated - 1),
            run_id=20,
        )
        output = io.StringIO()
        _print_reconciliation(report, output)
        rendered = output.getvalue()
        self.assertIn("conservation=FAIL", rendered)
        self.assertIn("first_inconsistent_counter=adc_items_generated", rendered)
        self.assertIn("unit=ADC pairs", rendered)


if __name__ == "__main__":  # pragma: no cover
    unittest.main()
