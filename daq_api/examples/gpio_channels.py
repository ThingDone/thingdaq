"""Read packed GPIO bytes and lazily extract selected D6-D13 channels.

The default simulator path is hardware-free. ``--real`` requires a Teensy 4.0
with D6-D13 used only within the hardware-safety limits.
"""

from __future__ import annotations

from _common import configure_exact, example_parser, open_example, print_applied
from thingdaq import GPIOBlock


def main() -> int:
    arguments = example_parser("Read packed GPIO and selected channels").parse_args()
    with open_example(arguments) as daq:
        print("example=gpio_channels packed_width_bits=8 pins=D6-D13")
        applied = configure_exact(daq, arguments, adc=False, gpio=True)
        print_applied(daq, applied)
        daq.start()
        block = daq.read_block()
        if not isinstance(block, GPIOBlock):
            raise TypeError(f"expected GPIOBlock, received {type(block).__name__}")
        d6 = block.channel(6)
        d13 = block.channel(13)
        for sample_index in range(8):
            print(
                f"sample={sample_index} packed=0x{block.sample(sample_index):02x} "
                f"D6={int(d6[sample_index])} D13={int(d13[sample_index])} "
                f"timestamp_ticks={block.sample_ticks(sample_index)}"
            )
        daq.stop()
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
