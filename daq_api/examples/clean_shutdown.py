"""Guarantee STOP and close in an explicit try/finally lifecycle.

The default simulator path is hardware-free. ``--real`` requires an attached,
safely wired Teensy 4.0 and demonstrates the same bounded cleanup sequence.
"""

from __future__ import annotations

from _common import configure_exact, example_parser, open_example
from thingdone_daq import ADCBlock, DeviceState


def main() -> int:
    arguments = example_parser("Always STOP and close a DAQ session").parse_args()
    daq = open_example(arguments)
    final_state: DeviceState | None = None
    try:
        print("example=clean_shutdown cleanup=try-finally")
        configure_exact(daq, arguments, adc=True, gpio=False)
        daq.start()
        block = daq.read_block()
        if not isinstance(block, ADCBlock):
            raise TypeError(f"expected ADCBlock, received {type(block).__name__}")
        print(f"captured_sequence={block.sequence} adc_pair0={block.pair(0)}")
    finally:
        try:
            if daq.is_open and daq.state in {
                DeviceState.CONFIGURED,
                DeviceState.RUNNING,
            }:
                final_state = daq.stop()
        finally:
            daq.close(stop=False)
    print(
        f"final_state={None if final_state is None else final_state.name} closed=true"
    )
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
