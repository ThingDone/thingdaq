"""Align ADC and GPIO blocks by their common run-relative timestamp interval.

The default simulator path is hardware-free. ``--real`` requires an attached,
safely wired Teensy 4.0; alignment does not claim external pad/aperture latency.
"""

from __future__ import annotations

from _common import configure_exact, example_parser, open_example, print_applied
from thingdone_daq import (
    ADCBlock,
    AlignedInterval,
    GPIOBlock,
    HostQueueLoss,
    StreamAnomaly,
    StreamGap,
    TimestampAligner,
)


def main() -> int:
    arguments = example_parser("Align one ADC/GPIO timestamp interval").parse_args()
    with open_example(arguments) as daq:
        print("example=combined_alignment external_latency_measured=false")
        applied = configure_exact(daq, arguments, adc=True, gpio=True)
        print_applied(daq, applied)
        daq.start()
        aligner = TimestampAligner(max_pending_intervals=2)
        complete: AlignedInterval | None = None
        for item in daq.blocks(2):
            if isinstance(item, (HostQueueLoss, StreamAnomaly)):
                raise TypeError(f"loss before alignment: {item!r}")
            if not isinstance(item, (ADCBlock, GPIOBlock, StreamGap)):
                raise TypeError(f"unexpected stream item {type(item).__name__}")
            for aligned in aligner.push(item):
                if isinstance(aligned, AlignedInterval) and aligned.complete:
                    complete = aligned
        if complete is None or complete.adc is None or complete.gpio is None:
            raise RuntimeError("simultaneous frame interval did not align")
        adc0_ticks, adc1_ticks = complete.adc_pair_ticks(0) or (None, None)
        print(
            f"run_id={complete.run_id} interval_ticks={complete.first_sample_ticks}:"
            f"{complete.end_tick_exclusive} adc0_ticks={adc0_ticks} "
            f"adc1_ticks={adc1_ticks} gpio_ticks={complete.gpio_sample_ticks(0)}"
        )
        print(
            f"raw_adc_pair={complete.adc.pair(0)} "
            f"packed_gpio=0x{complete.gpio.sample(0):02x}"
        )
        daq.stop()
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
