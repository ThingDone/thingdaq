"""Standalone, input-only TDUSB1 synthetic USB benchmark for the remote rig."""

from __future__ import annotations

import json
import os
import statistics
import struct
import time

import serial

HEADER = struct.Struct("<8s6I")
MODES = {
    1: "gpio-4k",
    2: "gpio-8k",
    3: "separate-4k",
    4: "coalesced-8k",
    5: "combined-8k",
}
PATTERNS = {n: (bytes(range(256)) * 32)[: n - HEADER.size] for n in (4096, 8192)}


class Checker:
    def __init__(self, run, mode):
        self.run, self.mode = run, mode
        self.sequence = self.wire_bytes = self.payload_bytes = 0
        self.adc_bytes = self.gpio_bytes = 0
        self.done = None

    def accept(self, frame):
        magic, run, sequence, size, kind, adc, gpio = HEADER.unpack_from(frame)
        if run != self.run or sequence != self.sequence or size != len(frame):
            raise ValueError("frame length, run ID, or sequence mismatch")
        if magic == b"TDEND001":
            if size != 96 or kind != self.mode or adc or gpio:
                raise ValueError("invalid END frame")
            values = struct.unpack_from("<8Q", frame, HEADER.size)
            keys = (
                "wire_bytes",
                "elapsed_us",
                "write_calls",
                "write_active_us",
                "frames",
                "short_writes",
                "offered_wire_bytes_per_second",
                "stop_reason",
            )
            self.done = dict(zip(keys, values, strict=True))
            if (
                self.done["wire_bytes"] != self.wire_bytes
                or self.done["frames"] != self.sequence
            ):
                raise ValueError("device/host byte or frame accounting mismatch")
            if (
                not self.done["elapsed_us"]
                or not self.sequence
                or self.done["stop_reason"] != 1
            ):
                raise ValueError("empty or prematurely stopped run")
            return
        expected_size = 8192 if self.mode in (2, 5) else 4096
        expected_kind = (
            3
            if self.mode == 5
            else (1 if self.mode in (3, 4) and sequence % 3 < 2 else 2)
        )
        payload = expected_size - HEADER.size
        expected_adc = (
            payload * 2 // 3
            if expected_kind == 3
            else (payload if expected_kind == 1 else 0)
        )
        if magic != b"TDATA001" or (size, kind, adc, gpio) != (
            expected_size,
            expected_kind,
            expected_adc,
            payload - expected_adc,
        ):
            raise ValueError("unexpected data shape")
        if frame[HEADER.size :] != PATTERNS[size]:
            raise ValueError("synthetic payload corruption")
        self.sequence += 1
        self.wire_bytes += size
        self.payload_bytes += payload
        self.adc_bytes += adc
        self.gpio_bytes += gpio


def read_exact(port, count, deadline):
    result = bytearray()
    while len(result) < count:
        if time.monotonic() > deadline:
            raise TimeoutError("diagnostic response deadline")
        result.extend(port.read(count - len(result)))
    return bytes(result)


def identify(port):
    port.write(b"INFO\n")
    response = read_exact(port, 64, time.monotonic() + 5)
    if response[:8] != b"TDINFO01":
        raise ValueError("wrong diagnostic interface")
    build = response[8:40].split(b"\0", 1)[0].decode("ascii")
    values = struct.unpack_from("<6I", response, 40)
    result = dict(
        zip(
            (
                "hardware_serial",
                "core_hz",
                "high_speed",
                "working_bytes",
                "core_tx_buffers",
                "core_tx_buffer_bytes",
            ),
            values,
            strict=True,
        )
    )
    result["build_id"] = build
    if build != os.environ["EXPECTED_BUILD_ID"] or result["hardware_serial"] != int(
        os.environ["EXPECTED_HARDWARE_SERIAL"]
    ):
        raise ValueError("unexpected hardware/firmware identity")
    if result["core_hz"] != 450000000 or result["working_bytes"] != 8192:
        raise ValueError("unexpected clock or working allocation")
    return result


def capture(port, mode, seconds, rate=0):
    duration_ms = round(seconds * 1000)
    port.write(f"RUN {mode} {duration_ms} {rate}\n".encode("ascii"))
    ack = read_exact(port, 32, time.monotonic() + 5)
    magic, run, actual_mode, actual_ms, actual_rate, transfer, reserved = HEADER.unpack(
        ack
    )
    expected_transfer = 4096 if mode in (1, 3) else 8192
    if magic != b"TDACK001" or (
        actual_mode,
        actual_ms,
        actual_rate,
        transfer,
        reserved,
    ) != (mode, duration_ms, rate, expected_transfer, 0):
        raise ValueError("RUN acknowledgment mismatch")
    checker = Checker(run, mode)
    buffered = bytearray()
    started, cpu_started = time.monotonic(), time.process_time()
    deadline = started + seconds + 5
    while checker.done is None:
        if time.monotonic() > deadline:
            raise TimeoutError("stream deadline")
        buffered.extend(port.read(65536))
        offset = 0
        while len(buffered) - offset >= HEADER.size:
            size = struct.unpack_from("<I", buffered, offset + 16)[0]
            if size not in (96, 4096, 8192):
                raise ValueError("invalid bounded frame length")
            if len(buffered) - offset < size:
                break
            checker.accept(buffered[offset : offset + size])
            offset += size
            if checker.done is not None:
                break
        if offset:
            del buffered[:offset]
    elapsed, cpu = time.monotonic() - started, time.process_time() - cpu_started
    if buffered:
        raise ValueError("unexpected trailing stream data")
    device_seconds = checker.done["elapsed_us"] / 1e6
    if not seconds * 0.99 <= device_seconds <= seconds + 0.5:
        raise ValueError("device duration out of bounds")
    if checker.done["offered_wire_bytes_per_second"] != rate:
        raise ValueError("device rate selection mismatch")
    return {
        "mode": MODES[mode],
        "mode_id": mode,
        "run_id": run,
        "requested_seconds": seconds,
        "offered_wire_bytes_per_second": rate,
        "wire_bytes": checker.wire_bytes,
        "payload_bytes": checker.payload_bytes,
        "adc_bytes": checker.adc_bytes,
        "gpio_bytes": checker.gpio_bytes,
        "frames": checker.sequence,
        "host_elapsed_seconds": elapsed,
        "host_cpu_seconds": cpu,
        "host_percent_one_core": 100 * cpu / elapsed,
        "host_wire_MBps": checker.wire_bytes / elapsed / 1e6,
        "host_payload_MBps": checker.payload_bytes / elapsed / 1e6,
        "device_wire_MBps": checker.wire_bytes / device_seconds / 1e6,
        "device_payload_MBps": checker.payload_bytes / device_seconds / 1e6,
        "device": checker.done,
        "every_payload_byte_verified": True,
        "sequence_errors": 0,
        "result": "PASS",
    }


def main():
    rows, warmups = [], []
    seconds = float(os.environ.get("AUX_INPUT_CAPTURE_SECONDS", "3"))
    if not 1 <= seconds <= 15:
        raise ValueError("benchmark duration must be 1..15 seconds")
    result = {
        "schema": "thingdaq.usb-throughput/v1",
        "result": "FAIL",
        "measurements": rows,
        "warmups": warmups,
    }
    try:
        with serial.Serial(
            os.environ["SERIAL_PORT"], 115200, timeout=0.005, write_timeout=1
        ) as port:
            time.sleep(0.3)
            port.reset_input_buffer()
            result["identity"] = identify(port)
            # Make the offered load exceed the physical acquisition's 6 MB/s.
            for rate in (6000000, 12000000, 24000000):
                row = capture(port, 1, seconds, rate)
                row["phase"] = "rate-sweep"
                rows.append(row)
                print("USB_RESULT " + json.dumps(row, sort_keys=True), flush=True)
            for repeat, order in enumerate(
                ((1, 2, 3, 4, 5), (3, 4, 5, 1, 2), (5, 1, 2, 3, 4))
            ):
                for mode in order:
                    warmups.append(capture(port, mode, 0.25))
                    row = capture(port, mode, seconds)
                    row.update(phase="saturation", repeat=repeat)
                    rows.append(row)
                    print("USB_RESULT " + json.dumps(row, sort_keys=True), flush=True)
            result["final_identity"] = identify(port)
            if result["final_identity"] != result["identity"]:
                raise ValueError("identity changed during benchmark")
        result["medians"] = {
            name: {
                key: statistics.median(
                    row[key]
                    for row in rows
                    if row["mode"] == name and row["phase"] == "saturation"
                )
                for key in (
                    "host_wire_MBps",
                    "host_payload_MBps",
                    "device_wire_MBps",
                    "device_payload_MBps",
                    "host_percent_one_core",
                )
            }
            for name in MODES.values()
        }
        result["result"] = "PASS"
    except Exception as error:  # noqa: BLE001 - preserve partial remote measurements
        result["error"] = f"{type(error).__name__}: {error}"
    print("EVIDENCE " + json.dumps(result, sort_keys=True), flush=True)
    return 0 if result["result"] == "PASS" else 1


if __name__ == "__main__":
    raise SystemExit(main())
