"""Discover/select by stable hardware serial; use the simulator by default.

Run with ``--real`` to perform physical serial discovery. That path requires an
attached Teensy 4.0 and may require ``--hardware-serial`` when several exist.
"""

from __future__ import annotations

from _common import example_parser, open_example, print_target, require_info
from thingdone_daq import ThingDAQ, discover, select_device


def main() -> int:
    parser = example_parser("Discover a ThingDAQ and select its stable serial")
    arguments = parser.parse_args()

    if not arguments.real:
        with open_example(arguments) as daq:
            info = require_info(daq)
            print("example=discovery_and_selection physical_required=false")
            print_target(arguments, info)
            print("simulator_note=pass --real to enumerate USB Serial hardware")
        return 0

    devices = discover()
    print("example=discovery_and_selection physical_required=true")
    print(f"discovered_count={len(devices)}")
    for device in devices:
        print(
            f"candidate_port={device.port} "
            f"hardware_serial={device.hardware_serial} build_id={device.info.build_id}"
        )
    if arguments.hardware_serial is not None:
        selected = select_device(
            devices,
            hardware_serial=arguments.hardware_serial,
        )
    elif len(devices) == 1:
        selected = devices[0]
    else:
        raise RuntimeError(
            "connect exactly one compatible device or pass --hardware-serial"
        )
    with ThingDAQ.open(selected) as daq:
        print_target(arguments, require_info(daq))
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
