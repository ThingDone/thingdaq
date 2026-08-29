"""Handle live typed loss events and reconcile firmware/host loss counters.

The default simulator path is hardware-free. ``--real`` performs a short
physical capture and therefore requires an attached, safely wired Teensy 4.0.
"""

from __future__ import annotations

from _common import configure_exact, example_parser, open_example
from teensy_daq import (
    ADCBlock,
    GPIOBlock,
    HostQueueLoss,
    StreamAnomaly,
    StreamGap,
)


def main() -> int:
    arguments = example_parser(
        "Observe live STATUS and explicit loss evidence"
    ).parse_args()
    with open_example(arguments, strict=False) as daq:
        print("example=status_and_loss policy=typed-events-and-counters")
        configure_exact(daq, arguments, adc=True, gpio=True)
        run_id = daq.start()
        blocks = 0
        reports = 0
        for item in daq.blocks(2):
            if isinstance(item, (ADCBlock, GPIOBlock)):
                blocks += 1
                print(
                    f"data={type(item).__name__} sequence={item.sequence} "
                    f"first_sample_ticks={item.first_sample_ticks}"
                )
            elif isinstance(item, (StreamGap, HostQueueLoss, StreamAnomaly)):
                reports += 1
                print(f"loss_event={type(item).__name__} evidence={item!r}")

        live_status = daq.status()
        losses = daq.loss_counters(refresh=False)
        daq.validate_stream_health(live_status)
        print(
            f"run_id={run_id} state={live_status.device_state.name} blocks={blocks} "
            f"loss_events={reports} firmware_dropped={losses.firmware.items_dropped} "
            f"host_queue_drops={losses.host.host_block_queue_drops} "
            f"has_loss={str(losses.has_loss).lower()}"
        )
        daq.stop()
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
