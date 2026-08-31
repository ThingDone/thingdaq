"""Opt into calibrated volts while retaining the original ADC codes.

The simulator uses an in-memory illustrative record. ``--real`` requires both
an attached Teensy 4.0 and an explicit user-owned ``--calibration`` JSON path.
"""

from __future__ import annotations

from datetime import datetime, timezone

from _common import configure_exact, example_parser, open_example, require_info
from thingdaq import (
    ADCBlock,
    CalibrationRecord,
    ConverterCalibration,
    load_calibration,
)

SIMULATOR_CALIBRATION_SERIAL = 4_000_000_001


def main() -> int:
    parser = example_parser("Apply an explicit host-side ADC calibration")
    parser.add_argument(
        "--calibration",
        help="user-selected calibration JSON path; required with --real",
    )
    parser.add_argument(
        "--analog-front-end-profile",
        help="exact optional profile key in the calibration database",
    )
    arguments = parser.parse_args()

    with open_example(arguments) as daq:
        info = require_info(daq)
        if arguments.real:
            if arguments.calibration is None:
                parser.error("--real requires --calibration PATH")
            record = load_calibration(
                arguments.calibration,
                info.hardware_serial,
                arguments.analog_front_end_profile,
                adc_resolution_bits=info.adc_resolution_bits,
                adc_code_range=(info.adc_code_min, info.adc_code_max),
                adc_input_range_volts=(
                    info.adc_input_min_mv_nominal / 1000.0,
                    info.adc_input_max_mv_nominal / 1000.0,
                ),
            )
            calibration_serial = info.hardware_serial
        else:
            ideal_gain = 3.3 / 4095
            record = CalibrationRecord(
                hardware_serial=SIMULATOR_CALIBRATION_SERIAL,
                adc_resolution_bits=12,
                adc_code_range=(0, 4095),
                adc_input_range_volts=(0.0, 3.3),
                adc0=ConverterCalibration(offset=0.0, gain=ideal_gain),
                adc1=ConverterCalibration(offset=0.0, gain=ideal_gain),
                provenance="illustrative in-memory simulator coefficients",
                created_at=datetime(2026, 8, 29, tzinfo=timezone.utc),
            )
            calibration_serial = SIMULATOR_CALIBRATION_SERIAL

        print("example=calibrated_adc raw_preserved=true calibrated=true")
        configure_exact(daq, arguments, adc=True, gpio=False)
        daq.start()
        block = daq.read_block()
        if not isinstance(block, ADCBlock):
            raise TypeError(f"expected ADCBlock, received {type(block).__name__}")
        channels = block.calibrated_channels(
            record,
            hardware_serial=calibration_serial,
            analog_front_end_profile=arguments.analog_front_end_profile,
        )
        for pair_index in range(4):
            print(
                f"pair={pair_index} adc0_raw={block.adc0[pair_index]} "
                f"adc0_V={channels.adc0[pair_index]:.9f} "
                f"adc1_raw={block.adc1[pair_index]} "
                f"adc1_V={channels.adc1[pair_index]:.9f}"
            )
        print(f"calibration_provenance={record.provenance}")
        daq.stop()
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
