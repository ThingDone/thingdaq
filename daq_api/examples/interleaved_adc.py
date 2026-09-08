"""Explicitly interleave ADC0 then ADC1 while retaining converter identity.

The default simulator path is hardware-free. ``--real`` requires a safely wired
Teensy 4.0. The denser nominal grid does not increase analog bandwidth.
"""

from __future__ import annotations

from itertools import islice

from _common import configure_exact, example_parser, open_example, print_applied
from thingdone_daq import ADCBlock


def main() -> int:
    arguments = example_parser("Explicitly interleave ADC0/A0 and ADC1/A1").parse_args()
    with open_example(arguments) as daq:
        print("example=interleaved_adc analog_bandwidth_increased=false")
        applied = configure_exact(daq, arguments, adc=True, gpio=False)
        print_applied(daq, applied)
        daq.start()
        block = daq.read_block()
        if not isinstance(block, ADCBlock):
            raise TypeError(f"expected ADCBlock, received {type(block).__name__}")
        for sample in islice(block.interleaved(), 8):
            print(
                f"pair={sample.pair_index} converter={sample.converter.name} "
                f"pin={sample.pin} raw_code={sample.code} "
                f"timestamp_ticks={sample.timestamp_ticks}"
            )
        daq.stop()
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
