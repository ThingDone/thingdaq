"""Focused tests for versioned, opt-in host-side ADC calibration."""

from __future__ import annotations

import json
import struct
import tempfile
import unittest
from dataclasses import replace
from datetime import datetime, timezone
from pathlib import Path
from unittest.mock import patch

from teensy_daq import (
    ADCBlock,
    AdcBlockMetadata,
    CalibratedAdcChannels,
    CalibrationDatabase,
    CalibrationError,
    CalibrationFormatError,
    CalibrationMismatchError,
    CalibrationRecord,
    ConverterCalibration,
    apply_correction,
    apply_corrections,
    calibration_database_from_json,
    calibration_database_to_json,
    estimate_offset_gain,
    load_calibration,
    save_calibration,
)
from teensy_daq._generated import protocol_constants as constants


def _record(
    *,
    hardware_serial: int = 12345670,
    profile: str | None = "buffer-a",
    resolution_bits: int = 12,
) -> CalibrationRecord:
    return CalibrationRecord(
        hardware_serial=hardware_serial,
        analog_front_end_profile=profile,
        adc_resolution_bits=resolution_bits,
        adc_code_range=(0, (1 << resolution_bits) - 1),
        adc_input_range_volts=(0.0, 3.3),
        adc0=ConverterCalibration(offset=-0.1, gain=0.001),
        adc1=ConverterCalibration(offset=0.2, gain=0.002),
        residual_timing_skew_seconds=1.25e-9,
        provenance="two-point bench capture; DMM asset 42",
        created_at=datetime(2026, 8, 29, 12, 34, 56, tzinfo=timezone.utc),
        notes="A0/A1 driven from the same buffered source",
    )


def _block(*, hardware_serial: int = 12345670) -> ADCBlock:
    payload = bytearray(constants.ADC_DATA_PAYLOAD_SIZE)
    for index in range(constants.ADC_PAIRS_PER_FRAME):
        struct.pack_into(
            "<HH",
            payload,
            index * constants.ADC_BYTES_PER_PAIR,
            100 + index % 3,
            200 + index % 3,
        )
    return ADCBlock(
        run_id=7,
        sequence=3,
        first_sample_ticks=16,
        payload=bytes(payload),
        metadata=AdcBlockMetadata(hardware_serial=hardware_serial),
    )


class CalibrationMathTests(unittest.TestCase):
    def test_two_point_fit_and_application_use_capture_means(self) -> None:
        calibration = estimate_offset_gain(
            [99, 100, 101],
            [1099, 1100, 1101],
            0.2,
            2.2,
        )

        self.assertAlmostEqual(0.002, calibration.gain)
        self.assertAlmostEqual(0.0, calibration.offset)
        self.assertAlmostEqual(1.0, apply_correction(500, calibration))
        self.assertEqual(
            (0.2, 1.0, 2.2),
            apply_corrections((100, 500, 1100), calibration),
        )

        with self.assertRaisesRegex(CalibrationFormatError, "finite"):
            estimate_offset_gain([float("nan")], [2], 0.0, 1.0)
        with self.assertRaisesRegex(CalibrationFormatError, "greater than zero"):
            ConverterCalibration(offset=0.0, gain=0.0)
        with self.assertRaisesRegex(CalibrationError, "capture mean"):
            estimate_offset_gain([10], [10], 0.0, 1.0)


class CalibrationPersistenceTests(unittest.TestCase):
    def test_database_json_is_strict_and_round_trips_all_provenance(self) -> None:
        database = CalibrationDatabase((_record(), _record(profile=None)))
        encoded = calibration_database_to_json(database)

        self.assertEqual(database, calibration_database_from_json(encoded))
        decoded = json.loads(encoded)
        self.assertEqual(1, decoded["schema_version"])
        self.assertEqual(1, decoded["records"][0]["schema_version"])
        self.assertEqual(
            "two-point bench capture; DMM asset 42",
            decoded["records"][0]["provenance"],
        )
        self.assertEqual("2026-08-29T12:34:56Z", decoded["records"][0]["created_at"])

        with self.assertRaisesRegex(CalibrationFormatError, "duplicate"):
            calibration_database_from_json(
                '{"format":"a","format":"b","schema_version":1,"records":[]}'
            )
        with self.assertRaisesRegex(CalibrationFormatError, "non-finite"):
            calibration_database_from_json(
                '{"format":"teensy-daq-host-calibration",'
                '"schema_version":1,"records":[],"extra":NaN}'
            )
        with self.assertRaisesRegex(CalibrationFormatError, "schema"):
            calibration_database_from_json(
                '{"format":"teensy-daq-host-calibration",'
                '"schema_version":1.0,"records":[]}'
            )

    def test_explicit_store_path_atomically_upserts_by_device_and_profile(self) -> None:
        with tempfile.TemporaryDirectory() as directory:
            path = Path(directory) / "my-calibrations.json"
            first = _record()
            second = _record(hardware_serial=76543210, profile=None)

            save_calibration(path, first)
            save_calibration(path, second)

            self.assertEqual(first, load_calibration(path, 12345670, "buffer-a"))
            self.assertEqual(second, load_calibration(path, 76543210))
            self.assertFalse(tuple(path.parent.glob(f".{path.name}.*.tmp")))
            with self.assertRaises(CalibrationMismatchError):
                load_calibration(path, 12345670, "wrong-profile")
            with self.assertRaisesRegex(CalibrationMismatchError, "resolution"):
                load_calibration(
                    path,
                    12345670,
                    "buffer-a",
                    adc_resolution_bits=10,
                )

    def test_failed_atomic_replace_preserves_existing_database(self) -> None:
        with tempfile.TemporaryDirectory() as directory:
            path = Path(directory) / "my-calibrations.json"
            save_calibration(path, _record())
            original = path.read_bytes()

            with (
                patch(
                    "teensy_daq.calibration.os.replace",
                    side_effect=OSError("injected replace failure"),
                ),
                self.assertRaisesRegex(OSError, "injected replace failure"),
            ):
                save_calibration(path, replace(_record(), notes="replacement"))

            self.assertEqual(original, path.read_bytes())
            self.assertFalse(tuple(path.parent.glob(f".{path.name}.*.tmp")))


class CalibratedViewTests(unittest.TestCase):
    def test_opt_in_views_are_marked_and_keep_raw_channels_unchanged(self) -> None:
        block = _block()
        raw_payload = block.payload
        calibrated = block.calibrated_channels(
            _record(),
            analog_front_end_profile="buffer-a",
        )

        self.assertIsInstance(calibrated, CalibratedAdcChannels)
        self.assertTrue(calibrated.calibrated)
        self.assertEqual("V", calibrated.units)
        self.assertFalse(calibrated.timing_skew_applied)
        self.assertIs(block, calibrated.raw_block)
        self.assertEqual((100, 101, 102), calibrated.raw_adc0[:3])
        self.assertEqual((200, 201, 202), calibrated.raw_adc1[:3])
        for observed, expected in zip(
            calibrated.adc0[:3], (0.0, 0.001, 0.002), strict=True
        ):
            self.assertAlmostEqual(expected, observed)
        for observed, expected in zip(
            calibrated.adc1[:3], (0.6, 0.602, 0.604), strict=True
        ):
            self.assertAlmostEqual(expected, observed)
        self.assertIs(raw_payload, block.payload)

        samples = tuple(
            sample
            for _, sample in zip(
                range(4),
                block.calibrated_interleaved(
                    _record(),
                    analog_front_end_profile="buffer-a",
                ),
                strict=False,
            )
        )
        self.assertEqual([100, 200, 101, 201], [sample.raw_code for sample in samples])
        self.assertEqual(
            [16, 20, 24, 28], [sample.timestamp_ticks for sample in samples]
        )
        self.assertTrue(all(sample.calibrated for sample in samples))
        self.assertTrue(all(not sample.timing_skew_applied for sample in samples))

    def test_wrong_device_profile_and_resolution_are_rejected_before_use(self) -> None:
        block = _block()
        with self.assertRaisesRegex(CalibrationMismatchError, "key"):
            block.calibrated_channels(
                _record(hardware_serial=999),
                analog_front_end_profile="buffer-a",
            )
        with self.assertRaisesRegex(CalibrationMismatchError, "key"):
            block.calibrated_channels(_record())
        with self.assertRaisesRegex(CalibrationMismatchError, "resolution"):
            block.calibrated_channels(
                _record(resolution_bits=10),
                analog_front_end_profile="buffer-a",
            )


if __name__ == "__main__":
    unittest.main()
