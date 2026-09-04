"""Read die temperature from an otherwise unowned Teensy serial port (v2).

Uses the experiment's existing bounded serial exchange/parser. Do not open a
second serial owner during acquisition; the soak runner samples in-band instead.
No CONFIGURE, START, STOP, GPIO writes or thermal-monitor writes are issued.
"""

from __future__ import annotations

import argparse
import json
import struct
import sys
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parents[1] / "tests"))
import rig_aux_input_capture as rig


def read_temperature(link: rig.SerialLink) -> dict:
    frame, latency = link.exchange(rig.GET_TEMPERATURE_REQUEST)
    rig.response_success(frame, rig.GET_TEMPERATURE_RESPONSE)
    sensor, _reserved1, _reserved2, value = struct.unpack_from(
        "<BBHi", frame.payload, 4
    )
    return {
        "status": (
            "VALID",
            "UNAVAILABLE",
            "NOT_READY",
            "INVALID_CALIBRATION",
            "OUT_OF_RANGE",
        )[sensor],
        "celsius": value / 1000 if sensor == 0 else None,
        "millidegrees_c": value if sensor == 0 else None,
        "run_id": frame.run_id,
        "request_id": frame.request_id,
        "latency_seconds": latency,
    }


def main() -> int:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--port", required=True)
    args = parser.parse_args()
    with rig.serial.Serial(
        port=args.port,
        baudrate=rig.BAUD_RATE,
        timeout=rig.SERIAL_READ_TIMEOUT_SECONDS,
        write_timeout=rig.SERIAL_WRITE_TIMEOUT_SECONDS,
    ) as port:
        link = rig.SerialLink(port)
        link.drain_startup(rig.STARTUP_DRAIN_SECONDS)
        reading = read_temperature(link)
    print(json.dumps(reading, sort_keys=True))
    return 0 if reading["status"] == "VALID" else 1


if __name__ == "__main__":
    raise SystemExit(main())
