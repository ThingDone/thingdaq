"""Standalone remote serial collector for the M7 DWT timing sketch."""

from __future__ import annotations

import json
import os
import time

OPERATIONS = ("c_flash", "c_itcm", "cpp_flash", "cpp_itcm")
FIELDS = ("units", "min_cycles", "median_cycles", "max_cycles", "digest")


def expected_digest() -> int:
    """Independent seeded GPIO pin-position oracle, with uint32 wraparound."""
    low_bits = (10, 17, 16, 11, 0, 2, 1, 3)
    high_bits = (23, 22, 17, 16, 26, 27, 24, 25)
    state, result = 0x12345678, 2166136261
    for _ in range(2024):
        for bits in (low_bits, high_bits):
            state = (state * 1664525 + 1013904223) & 0xFFFFFFFF
            packed = sum(
                ((state >> bit) & 1) << index for index, bit in enumerate(bits)
            )
            result = ((result ^ packed) * 16777619) & 0xFFFFFFFF
    return result


def parse_transcript(lines: list[str], optimization: str) -> list[dict]:
    expected_banner = (
        f"cpu_hz=450000000,opt={optimization},warm_cache=1,"
        "interrupts_enabled=1,trials=101"
    )
    if not lines or lines[0] != expected_banner or lines[-1] != "done":
        raise ValueError("missing/mismatched benchmark banner or completion marker")
    if len(lines) != 13 or lines[1] != "operation,data_region," + ",".join(FIELDS):
        raise ValueError("missing, extra, or malformed timing rows")
    expected = {
        (operation, region) for operation in OPERATIONS for region in ("dtcm", "ocram")
    }
    expected.update({("atomic_publish_take", "dtcm"), ("primask_publish_take", "dtcm")})
    rows = []
    for line in lines[2:-1]:
        parts = line.split(",")
        if len(parts) != 7 or tuple(parts[:2]) not in expected:
            raise ValueError(f"unexpected or duplicate timing row: {line}")
        expected.remove(tuple(parts[:2]))
        row = dict(zip(FIELDS, (int(value) for value in parts[2:]), strict=True))
        if (
            not 0
            < row["min_cycles"]
            <= row["median_cycles"]
            <= row["max_cycles"]
            < 2**32
        ):
            raise ValueError("invalid cycle ordering/range")
        packing = parts[0] in OPERATIONS
        if row["units"] != (2024 if packing else 256):
            raise ValueError("unexpected sample/operation count")
        if row["digest"] != (expected_digest() if packing else 256):
            raise ValueError("kernel or event output disagrees with host oracle")
        rows.append({"operation": parts[0], "data_region": parts[1], **row})
    if expected:
        raise ValueError("missing timing cases")
    return rows


def main() -> int:
    import serial
    from serial.tools import list_ports

    evidence = {"result": "FAIL", "passes": [], "validator": "m7-dwt"}
    try:
        port = os.environ["SERIAL_PORT"]
        optimization = os.environ["M7_OPTIMIZATION"]
        evidence["optimization"] = optimization
        observed = next((p for p in list_ports.comports() if p.device == port), None)
        evidence["usb_serial"] = observed.serial_number if observed else None
        if (
            evidence["usb_serial"] is not None
            and str(evidence["usb_serial"]) != os.environ["EXPECTED_HARDWARE_SERIAL"]
        ):
            raise ValueError("unexpected physical USB serial")
        with serial.Serial(port, 115200, timeout=0.5, write_timeout=2) as link:
            time.sleep(0.2)
            link.reset_input_buffer()
            for trial in range(5):
                link.write(b"b")
                lines = []
                deadline = time.monotonic() + 15
                while time.monotonic() < deadline:
                    raw = link.readline()
                    if not raw:
                        continue
                    line = raw.decode("ascii").strip()
                    print(f"RAW {trial} {line}", flush=True)
                    lines.append(line)
                    if line.startswith("ERROR"):
                        raise ValueError(line)
                    if line == "done":
                        break
                evidence["passes"].append(parse_transcript(lines, optimization))
                time.sleep(0.1)
        evidence["result"] = "PASS"
    except Exception as error:  # noqa: BLE001 - preserve hardware failures
        evidence["error"] = f"{type(error).__name__}: {error}"
    print("EVIDENCE " + json.dumps(evidence, sort_keys=True), flush=True)
    return 0 if evidence["result"] == "PASS" else 1


if __name__ == "__main__":
    raise SystemExit(main())
