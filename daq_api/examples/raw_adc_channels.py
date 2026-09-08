"""Read unchanged ADC0/A0 and ADC1/A1 codes from one bounded block.

The default simulator path is hardware-free. ``--real`` requires a Teensy 4.0
whose A0/A1 inputs already satisfy the limits in the hardware-safety guide.
"""

from __future__ import annotations

from _common import (
    configure_exact,
    example_parser,
    open_example,
    print_applied,
    print_target,
    require_info,
)
from thingdone_daq import ADCBlock


def main() -> int:
    arguments = example_parser("Read raw ADC0/A0 and ADC1/A1 channels").parse_args()
    with open_example(arguments) as daq:
        print("example=raw_adc_channels physical_required=false_by_default")
        print_target(arguments, require_info(daq))
        applied = configure_exact(daq, arguments, adc=True, gpio=False)
        print_applied(daq, applied)
        daq.start()
        block = daq.read_block()
        if not isinstance(block, ADCBlock):
            raise TypeError(f"expected ADCBlock, received {type(block).__name__}")
        for pair_index in range(4):
            adc0_ticks, adc1_ticks = block.pair_ticks(pair_index)
            print(
                f"pair={pair_index} adc0_raw={block.adc0[pair_index]} "
                f"adc0_ticks={adc0_ticks} adc1_raw={block.adc1[pair_index]} "
                f"adc1_ticks={adc1_ticks}"
            )
        daq.stop()
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
