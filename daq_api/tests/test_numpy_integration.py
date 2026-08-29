"""Focused optional-NumPy and no-NumPy parity tests."""

from __future__ import annotations

import importlib.util
import os
import subprocess
import sys
import textwrap
import unittest
from datetime import datetime, timezone
from pathlib import Path

from teensy_daq import (
    ADCBlock,
    AdcBlockMetadata,
    CalibrationRecord,
    ConverterCalibration,
    GPIOBlock,
    synthetic_adc_payload,
    synthetic_gpio_payload,
)
from teensy_daq._generated import protocol_constants as constants

REPOSITORY_ROOT = Path(__file__).resolve().parents[2]
PACKAGE_SOURCE = REPOSITORY_ROOT / "daq_api" / "src"
NUMPY_AVAILABLE = importlib.util.find_spec("numpy") is not None


def _record() -> CalibrationRecord:
    return CalibrationRecord(
        hardware_serial=12345670,
        analog_front_end_profile="buffer-a",
        adc_resolution_bits=12,
        adc_code_range=(0, 4095),
        adc_input_range_volts=(0.0, 3.3),
        adc0=ConverterCalibration(offset=-0.1, gain=0.001),
        adc1=ConverterCalibration(offset=0.2, gain=0.002),
        provenance="optional NumPy unit-test vector",
        created_at=datetime(2026, 8, 29, tzinfo=timezone.utc),
    )


def _adc_block(*, first_sample_ticks: int = 16) -> ADCBlock:
    return ADCBlock(
        run_id=7,
        sequence=3,
        first_sample_ticks=first_sample_ticks,
        payload=synthetic_adc_payload(0),
        metadata=AdcBlockMetadata(hardware_serial=12345670),
    )


@unittest.skipUnless(NUMPY_AVAILABLE, "NumPy is an optional dependency")
class NumPyIntegrationTests(unittest.TestCase):
    @classmethod
    def setUpClass(cls) -> None:
        import numpy
        from teensy_daq import numpy as teensy_numpy

        cls.numpy = numpy
        cls.teensy_numpy = teensy_numpy

    def test_adc_and_gpio_wire_views_are_read_only_zero_copy_and_keep_owner(
        self,
    ) -> None:
        adc = _adc_block()
        gpio = GPIOBlock(7, 4, 16, synthetic_gpio_payload(0))

        adc_view = adc.as_numpy()
        gpio_view = gpio.as_numpy()

        self.assertEqual((constants.ADC_PAIRS_PER_FRAME, 2), adc_view.pairs.shape)
        self.assertEqual("<u2", adc_view.pairs.dtype.str)
        self.assertEqual((4, 2), adc_view.pairs.strides)
        self.assertFalse(adc_view.pairs.flags.owndata)
        self.assertFalse(adc_view.pairs.flags.writeable)
        self.assertTrue(adc_view.pairs.flags.aligned)
        self.assertTrue(self.numpy.shares_memory(adc_view.pairs, adc_view.adc0))
        self.assertTrue(self.numpy.shares_memory(adc_view.pairs, adc_view.adc1))
        self.assertEqual([0, 1], adc_view.pairs[0].tolist())
        self.assertIs(adc.payload, adc_view.payload_owner)

        adc_base = adc_view.pairs
        while isinstance(adc_base, self.numpy.ndarray):
            adc_base = adc_base.base
        self.assertIsInstance(adc_base, memoryview)
        self.assertIs(adc.payload, adc_base.obj)

        self.assertEqual((constants.GPIO_SAMPLES_PER_FRAME,), gpio_view.packed.shape)
        self.assertEqual("|u1", gpio_view.packed.dtype.str)
        self.assertFalse(gpio_view.packed.flags.owndata)
        self.assertFalse(gpio_view.packed.flags.writeable)
        self.assertEqual([0, 1, 2, 3], gpio_view.packed[:4].tolist())
        self.assertIs(gpio.payload, gpio_view.payload_owner)

        with self.assertRaises(ValueError):
            adc_view.pairs.setflags(write=True)
        with self.assertRaises(ValueError):
            gpio_view.packed.setflags(write=True)

        retained_pairs = adc_view.pairs
        del adc_view, adc
        self.assertEqual([0, 1], retained_pairs[0].tolist())

    def test_vectorized_interleaving_and_timestamps_match_pure_python_at_wrap(
        self,
    ) -> None:
        block = _adc_block(first_sample_ticks=constants.UINT64_MAX - 3)
        array = self.teensy_numpy.interleave_adc(block)
        pure = tuple(block.interleaved())

        self.assertFalse(array.calibrated)
        self.assertEqual("code", array.units)
        self.assertFalse(array.timing_skew_applied)
        self.assertEqual(
            [sample.code for sample in pure],
            array.raw_codes.tolist(),
        )
        self.assertEqual(
            [sample.timestamp_ticks for sample in pure],
            array.timestamp_ticks.tolist(),
        )
        self.assertEqual(
            [int(sample.converter) for sample in pure],
            array.converter_indices().tolist(),
        )
        self.assertEqual(
            [sample.pair_index for sample in pure],
            array.pair_indices().tolist(),
        )
        self.assertTrue(
            self.numpy.shares_memory(array.raw_codes, block.as_numpy().pairs)
        )
        self.assertFalse(array.raw_codes.flags.writeable)
        self.assertFalse(array.timestamp_ticks.flags.writeable)
        self.assertEqual(
            array.timestamp_ticks[1] / block.timestamp_hz,
            array.timestamp_seconds()[1],
        )

    def test_vectorized_calibration_matches_pure_python_and_keeps_raw_codes(
        self,
    ) -> None:
        block = _adc_block()
        record = _record()
        pure = block.calibrated_channels(
            record,
            analog_front_end_profile="buffer-a",
        )

        calibrated = self.teensy_numpy.calibrate_adc(
            block,
            record,
            analog_front_end_profile="buffer-a",
        )
        interleaved = calibrated.interleaved()

        self.assertTrue(calibrated.calibrated)
        self.assertEqual("V", calibrated.units)
        self.assertFalse(calibrated.timing_skew_applied)
        self.numpy.testing.assert_allclose(calibrated.adc0, tuple(pure.adc0))
        self.numpy.testing.assert_allclose(calibrated.adc1, tuple(pure.adc1))
        self.assertEqual(tuple(block.adc0), tuple(calibrated.raw_adc0.tolist()))
        self.assertEqual(tuple(block.adc1), tuple(calibrated.raw_adc1.tolist()))
        self.assertTrue(calibrated.values.flags.owndata)
        self.assertFalse(calibrated.values.flags.writeable)
        self.assertTrue(interleaved.calibrated)
        self.assertEqual("V", interleaved.units)
        self.assertEqual(
            [
                sample.raw_code
                for sample in block.calibrated_interleaved(
                    record,
                    analog_front_end_profile="buffer-a",
                )
            ],
            interleaved.raw_codes.tolist(),
        )

        pure_values = [
            sample.voltage
            for sample in block.calibrated_interleaved(
                record,
                analog_front_end_profile="buffer-a",
            )
        ]
        self.numpy.testing.assert_allclose(pure_values, interleaved.values)

    def test_gpio_expands_only_explicit_selected_channels_and_matches_lazy_views(
        self,
    ) -> None:
        block = GPIOBlock(9, 2, constants.UINT64_MAX - 1, synthetic_gpio_payload(0))
        view = block.as_numpy()

        self.assertEqual((constants.GPIO_SAMPLES_PER_FRAME,), view.packed.shape)
        selected = view.channels((6, 9, 13))
        self.assertEqual((6, 9, 13), selected.pins)
        self.assertEqual((0, 3, 7), selected.bits)
        self.assertEqual(
            (constants.GPIO_SAMPLES_PER_FRAME, 3),
            selected.values.shape,
        )
        self.assertEqual(
            list(block.channel(6)),
            selected.for_pin(6).tolist(),
        )
        self.assertEqual(
            list(block.channel(9)),
            selected.for_pin(9).tolist(),
        )
        self.assertEqual(
            [block.sample_ticks(index) for index in range(block.item_count)],
            selected.timestamps().tolist(),
        )
        self.assertFalse(selected.values.flags.writeable)
        self.assertTrue(self.numpy.shares_memory(selected.raw_bytes, view.packed))

        all_channels = view.channels(range(6, 14))
        self.assertEqual(
            (constants.GPIO_SAMPLES_PER_FRAME, 8), all_channels.values.shape
        )
        with self.assertRaisesRegex(ValueError, "at least one"):
            view.channels(())
        with self.assertRaisesRegex(ValueError, "unique"):
            view.channels((6, 6))
        with self.assertRaisesRegex(ValueError, "D6 through D13"):
            view.channels((5,))

    def test_convenience_functions_validate_types_and_preserve_shapes(self) -> None:
        adc = _adc_block()
        gpio = GPIOBlock(7, 0, 0, synthetic_gpio_payload(0))

        self.assertEqual(
            (constants.ADC_PAIRS_PER_FRAME, 2),
            self.teensy_numpy.adc_pairs(adc).shape,
        )
        self.assertEqual(
            (constants.ADC_PAIRS_PER_FRAME * 2,),
            self.teensy_numpy.adc_timestamps(adc, interleaved=True).shape,
        )
        self.assertEqual(
            (constants.GPIO_SAMPLES_PER_FRAME,),
            self.teensy_numpy.gpio_bytes(gpio).shape,
        )
        self.assertEqual(
            (constants.GPIO_SAMPLES_PER_FRAME,),
            self.teensy_numpy.extract_gpio_channel(gpio, 13).values.shape,
        )
        with self.assertRaisesRegex(TypeError, "ADCBlock"):
            self.teensy_numpy.adc_view(gpio)
        with self.assertRaisesRegex(TypeError, "GPIOBlock"):
            self.teensy_numpy.gpio_view(adc)
        with self.assertRaisesRegex(TypeError, "bool"):
            self.teensy_numpy.adc_timestamps(adc, interleaved=1)


class NoNumPyIntegrationTests(unittest.TestCase):
    def test_base_package_and_equivalent_pure_python_paths_forbid_numpy_import(
        self,
    ) -> None:
        script = textwrap.dedent(
            """
            import builtins
            import sys
            from datetime import datetime, timezone

            original_import = builtins.__import__
            def guarded_import(
                name, globals=None, locals=None, fromlist=(), level=0
            ):
                if level == 0 and name.partition('.')[0] == 'numpy':
                    raise ModuleNotFoundError(
                        "NumPy deliberately unavailable", name='numpy'
                    )
                return original_import(name, globals, locals, fromlist, level)
            builtins.__import__ = guarded_import

            from teensy_daq import (
                ADCBlock, AdcBlockMetadata, CalibrationRecord,
                ConverterCalibration, GPIOBlock, synthetic_adc_payload,
                synthetic_gpio_payload,
            )

            record = CalibrationRecord(
                hardware_serial=12345670,
                analog_front_end_profile=None,
                adc_resolution_bits=12,
                adc_code_range=(0, 4095),
                adc_input_range_volts=(0.0, 3.3),
                adc0=ConverterCalibration(offset=0.0, gain=0.001),
                adc1=ConverterCalibration(offset=0.0, gain=0.002),
                provenance='network-disabled container test',
                created_at=datetime(2026, 8, 29, tzinfo=timezone.utc),
            )
            adc = ADCBlock(
                3, 0, 16, synthetic_adc_payload(0),
                metadata=AdcBlockMetadata(hardware_serial=12345670),
            )
            gpio = GPIOBlock(3, 0, 16, synthetic_gpio_payload(0))

            assert adc.pair(0) == (0, 1)
            first = next(adc.interleaved())
            assert (first.code, first.converter.name, first.timestamp_ticks) == (
                0, 'ADC0', 16,
            )
            calibrated = adc.calibrated_channels(record)
            assert calibrated.calibrated and calibrated.units == 'V'
            assert calibrated.raw_adc0[1] == 2
            assert calibrated.adc1[1] == 0.006
            assert gpio.payload_view.obj is gpio.payload
            assert gpio.channel(13)[128]
            assert gpio.sample_ticks(2) == 20
            assert 'numpy' not in sys.modules

            try:
                adc.as_numpy()
            except ImportError as exc:
                assert "optional NumPy support is not installed" in str(exc)
            else:
                raise AssertionError('missing NumPy did not fail explicitly')
            """
        )
        environment = os.environ.copy()
        existing_path = environment.get("PYTHONPATH")
        environment["PYTHONPATH"] = str(PACKAGE_SOURCE) + (
            os.pathsep + existing_path if existing_path else ""
        )
        completed = subprocess.run(
            [sys.executable, "-c", script],
            cwd=REPOSITORY_ROOT,
            env=environment,
            capture_output=True,
            check=False,
            text=True,
            timeout=10,
        )
        self.assertEqual(0, completed.returncode, completed.stdout + completed.stderr)


if __name__ == "__main__":
    unittest.main()
