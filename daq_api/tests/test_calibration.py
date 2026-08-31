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

from thingdaq import (
    CALIBRATION_SCHEMA_VERSION,
    MAX_CALIBRATION_FILE_BYTES,
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
from thingdaq._generated import protocol_constants as constants


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

    def test_known_affine_vectors_preserve_inputs_and_do_not_clip(self) -> None:
        low_capture = [98.0, 100.0, 102.0]
        high_capture = [898.0, 900.0, 902.0]
        calibration = estimate_offset_gain(
            low_capture,
            high_capture,
            0.25,
            2.65,
        )

        self.assertAlmostEqual(0.003, calibration.gain)
        self.assertAlmostEqual(-0.05, calibration.offset)
        raw_codes = [-100.0, 100.0, 500.0, 1_200.0]
        observed = apply_corrections(raw_codes, calibration)
        for actual, expected in zip(observed, (-0.35, 0.25, 1.45, 3.55), strict=True):
            self.assertAlmostEqual(expected, actual)
        self.assertEqual([-100.0, 100.0, 500.0, 1_200.0], raw_codes)
        self.assertEqual([98.0, 100.0, 102.0], low_capture)
        self.assertEqual([898.0, 900.0, 902.0], high_capture)


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
                '{"format":"thingdaq-host-calibration",'
                '"schema_version":1,"records":[],"extra":NaN}'
            )
        with self.assertRaisesRegex(CalibrationFormatError, "schema"):
            calibration_database_from_json(
                '{"format":"thingdaq-host-calibration",'
                '"schema_version":1.0,"records":[]}'
            )

    def test_unsupported_schemas_require_explicit_migration(self) -> None:
        document = json.loads(
            calibration_database_to_json(CalibrationDatabase((_record(),)))
        )
        self.assertEqual(CALIBRATION_SCHEMA_VERSION, document["schema_version"])

        for version in (0, CALIBRATION_SCHEMA_VERSION + 1):
            with self.subTest(scope="database", version=version):
                changed = dict(document)
                changed["schema_version"] = version
                with self.assertRaisesRegex(
                    CalibrationFormatError,
                    "unsupported calibration database schema",
                ):
                    calibration_database_from_json(json.dumps(changed))

            with self.subTest(scope="record", version=version):
                changed = json.loads(json.dumps(document))
                changed["records"][0]["schema_version"] = version
                with self.assertRaisesRegex(
                    CalibrationFormatError,
                    "unsupported calibration schema version",
                ):
                    calibration_database_from_json(json.dumps(changed))

        changed = json.loads(json.dumps(document))
        changed["records"][0]["unreviewed_migration_field"] = True
        with self.assertRaisesRegex(CalibrationFormatError, "unknown"):
            calibration_database_from_json(json.dumps(changed))

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
                    "thingdaq.calibration.os.replace",
                    side_effect=OSError("injected replace failure"),
                ),
                self.assertRaisesRegex(OSError, "injected replace failure"),
            ):
                save_calibration(path, replace(_record(), notes="replacement"))

            self.assertEqual(original, path.read_bytes())
            self.assertFalse(tuple(path.parent.glob(f".{path.name}.*.tmp")))

    def test_failed_atomic_fsync_preserves_existing_database_and_cleans_temp(
        self,
    ) -> None:
        with tempfile.TemporaryDirectory() as directory:
            path = Path(directory) / "my-calibrations.json"
            save_calibration(path, _record())
            original = path.read_bytes()

            with (
                patch(
                    "thingdaq.calibration.os.fsync",
                    side_effect=OSError("injected fsync failure"),
                ),
                self.assertRaisesRegex(OSError, "injected fsync failure"),
            ):
                save_calibration(path, replace(_record(), notes="replacement"))

            self.assertEqual(original, path.read_bytes())
            self.assertFalse(tuple(path.parent.glob(f".{path.name}.*.tmp")))

    def test_store_rejects_symlinks_before_read_or_replacement(self) -> None:
        with tempfile.TemporaryDirectory() as directory:
            target = Path(directory) / "target.json"
            link = Path(directory) / "selected.json"
            save_calibration(target, _record())
            original = target.read_bytes()
            link.symlink_to(target)

            with self.assertRaisesRegex(CalibrationFormatError, "symbolic link"):
                load_calibration(link, 12345670, "buffer-a")
            with self.assertRaisesRegex(CalibrationFormatError, "symbolic link"):
                save_calibration(link, replace(_record(), notes="replacement"))

            self.assertEqual(original, target.read_bytes())

    def test_store_rejects_invalid_utf8_and_oversized_documents(self) -> None:
        with tempfile.TemporaryDirectory() as directory:
            path = Path(directory) / "selected.json"
            path.write_bytes(b"\xff")
            with self.assertRaisesRegex(CalibrationFormatError, "valid UTF-8"):
                load_calibration(path, 12345670, "buffer-a")

            path.write_bytes(b" " * (MAX_CALIBRATION_FILE_BYTES + 1))
            with self.assertRaisesRegex(CalibrationFormatError, "1 MiB limit"):
                load_calibration(path, 12345670, "buffer-a")


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
        with self.assertRaisesRegex(CalibrationMismatchError, "input range"):
            block.calibrated_channels(
                replace(_record(), adc_input_range_volts=(0.0, 3.2)),
                analog_front_end_profile="buffer-a",
            )

    def test_optional_skew_vectors_round_trip_but_never_change_nominal_ticks(
        self,
    ) -> None:
        block = _block()
        expected_ticks = [16, 20, 24, 28]

        for skew in (None, -2.5e-9, 0.0, 3.75e-9):
            with self.subTest(skew=skew):
                record = replace(_record(), residual_timing_skew_seconds=skew)
                database = calibration_database_from_json(
                    calibration_database_to_json(CalibrationDatabase((record,)))
                )
                selected = database.select(12345670, "buffer-a")
                samples = tuple(
                    sample
                    for _, sample in zip(
                        range(4),
                        block.calibrated_interleaved(
                            selected,
                            analog_front_end_profile="buffer-a",
                        ),
                        strict=False,
                    )
                )

                self.assertEqual(skew, selected.residual_timing_skew_seconds)
                self.assertEqual(
                    expected_ticks,
                    [sample.timestamp_ticks for sample in samples],
                )
                self.assertTrue(
                    all(not sample.timing_skew_applied for sample in samples)
                )

        for invalid in (float("nan"), float("inf"), float("-inf")):
            with (
                self.subTest(invalid=invalid),
                self.assertRaisesRegex(
                    CalibrationFormatError,
                    "finite",
                ),
            ):
                replace(_record(), residual_timing_skew_seconds=invalid)


if __name__ == "__main__":
    unittest.main()
