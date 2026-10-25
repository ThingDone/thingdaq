"""Bundled physical qualification worker; no HTTP and no firmware rewriting."""

from __future__ import annotations

import copy
import hashlib
import json
import os
import struct
import time
import zlib
from dataclasses import asdict

from protocol_v3_qualification import (
    THERMAL_LIMIT_C,
    json_hash,
    validate_capture,
)
from rig_release_sdk import host_cpu
from thingdone_daq import ADCBlock, DAQConfiguration, GPIOBlock, StreamGap, ThingDAQ
from thingdone_daq._generated import protocol_v2_constants as v2
from thingdone_daq.models import GpioClockDiagnosticRequest
from thingdone_daq.models_v3 import V3Settings
from thingdone_daq.protocol_v3 import decode_data_payload
from thingdone_daq.transport import SerialTransport

from firmware.soak.validator import CpuTracker

HEADER = struct.Struct("<IBBHHBBIIIIIQI")


def require(condition, reason):
    if not condition:
        raise ValueError(reason)


def independent_samples(kind, payload, count):
    """Small byte-lane oracle, intentionally independent of SDK codec helpers."""
    encoding, width, reserved, decoded, runs = struct.unpack_from("<BBHII", payload)
    require(reserved == 0 and decoded == count * width, "invalid data prefix")
    samples = payload[12:]
    if encoding == 0:
        require(runs == 0 and len(samples) == decoded, "invalid RAW")
        return samples
    output = bytearray()
    if encoding == 2:
        require(kind == 1 and width == 4 and runs == 0, "invalid PACK12")
        require(len(samples) == 3 * count, "invalid PACK12 length")
        for a, b, d in struct.iter_unpack("BBB", samples):
            output.extend(struct.pack("<HH", a | ((b & 15) << 8), (b >> 4) | (d << 4)))
    elif encoding == 1:
        require(kind == 2 and width in (1, 2), "invalid RLE")
        require(len(samples) == runs * (2 + width) < decoded, "invalid RLE length")
        previous = None
        for offset in range(0, len(samples), 2 + width):
            length = int.from_bytes(samples[offset : offset + 2], "little")
            value = samples[offset + 2 : offset + 2 + width]
            require(length > 0 and value != previous, "noncanonical RLE")
            require(len(output) + length * width <= decoded, "RLE overflow")
            output.extend(value * length)
            previous = value
    else:
        raise ValueError("unknown encoding")
    require(len(output) == decoded, "codec logical count mismatch")
    return bytes(output)


def empty_stream():
    return {
        "frames": 0,
        "items": 0,
        "logical_bytes": 0,
        "encoded_bytes": 0,
        "wire_bytes": 0,
        "gap_items": 0,
        "end_item": 0,
        "next_sequence": 0,
        "versions": [],
        "run_ids": [],
        "sample_checks": 0,
        "encodings": {},
        "first_ticks": 0,
        "last_ticks": 0,
        "first_host_seconds": 0,
        "last_host_seconds": 0,
        "samples": [],
    }


class WireTap:
    """Bounded wire accounting before SDK queues, including discarded STOP tails.

    All frames get an independent framing/checksum/chronology check. One full
    frame per encoding is decoded twice and retained; this avoids turning the
    byte oracle into the throughput bottleneck. Raw input is hashed in full.
    """

    def __init__(self, transport):
        self.transport = transport
        self.buffer = bytearray()
        self.pause_until = 0
        self.override_configure = None
        self.last_override_wire = None
        self.reset()

    @property
    def is_open(self):
        return self.transport.is_open

    def reset(self, width=1):
        require(not self.buffer, "partial frame at run boundary")
        self.width = width
        self.streams = {"adc": empty_stream(), "gpio": empty_stream()}
        self.errors = 0
        self.raw_hash = hashlib.sha256()
        self.raw_bytes = 0
        self.control_samples = []

    def write(self, data):
        if self.override_configure is not None:
            require(
                len(data) == 68 and data[4:6] == b"\x03\x11",
                "negative request boundary",
            )
            body = bytes(data[:44]) + self.override_configure
            wire = body + struct.pack("<I", zlib.adler32(body))
            self.override_configure = None
            self.last_override_wire = wire.hex()
            written = 0
            deadline = time.monotonic() + 1
            while written < len(wire):
                require(time.monotonic() < deadline, "negative write deadline")
                count = self.transport.write(wire[written:])
                require(count > 0, "negative write stalled")
                written += count
            return len(data)
        return self.transport.write(data)

    def flush(self):
        return self.transport.flush()

    def close(self):
        self.transport.close()

    def read(self, size):
        delay = self.pause_until - time.monotonic()
        if delay > 0:
            time.sleep(delay)
        data = self.transport.read(size)
        self.accept(data)
        return data

    def accept(self, data):
        self.raw_hash.update(data)
        self.raw_bytes += len(data)
        self.buffer.extend(data)
        consumed = 0
        try:
            while len(self.buffer) - consumed >= HEADER.size:
                fields = HEADER.unpack_from(self.buffer, consumed)
                (
                    magic,
                    version,
                    kind,
                    flags,
                    length,
                    checksum,
                    reserved,
                    total,
                    payload,
                    run,
                    sequence,
                    _request,
                    ticks,
                    count,
                ) = fields
                require(
                    magic == 0xDEADBEEF
                    and version in (2, 3)
                    and length == 44
                    and checksum == 1
                    and reserved == 0
                    and 48 <= total <= 4108
                    and total == payload + 48,
                    "invalid/private wire header",
                )
                if len(self.buffer) - consumed < total:
                    break
                frame = bytes(self.buffer[consumed : consumed + total])
                require(
                    zlib.adler32(frame[:-4]) == int.from_bytes(frame[-4:], "little"),
                    "wire checksum",
                )
                consumed += total
                if kind not in (1, 2):
                    # Bound raw logs independently of capture duration.
                    if len(self.control_samples) < 64:
                        self.control_samples.append(frame.hex())
                    continue
                name = "adc" if kind == 1 else "gpio"
                row = self.streams[name]
                body = frame[44:-4]
                if version == 3:
                    encoding, width, _, logical, _ = struct.unpack_from("<BBHII", body)
                    encoded = len(body) - 12
                else:
                    encoding, width = 0, 4 if kind == 1 else self.width
                    logical = encoded = len(body)
                require(count > 0 and logical == count * width, "wire item count")
                require(width == (4 if kind == 1 else self.width), "wire GPIO width")
                require(
                    ticks % 8 == 0 and ticks // 8 >= row["end_item"],
                    "wire timestamp regression",
                )
                require(sequence >= row["next_sequence"], "wire sequence regression")
                gap = ticks // 8 - row["end_item"]
                require(
                    bool(gap) == bool(sequence - row["next_sequence"]),
                    "wire sequence/tick gap disagreement",
                )
                require(not gap or flags & 2, "unflagged wire gap")
                row["gap_items"] += gap
                row["end_item"] = ticks // 8 + count
                row["next_sequence"] = sequence + 1
                now = time.monotonic()
                if not row["frames"]:
                    row["first_host_seconds"], row["first_ticks"] = now, ticks
                row["last_host_seconds"], row["last_ticks"] = now, ticks
                key = str(encoding)
                if key not in row["encodings"]:
                    if version == 3:
                        expected = independent_samples(kind, body, count)
                        require(
                            expected == decode_data_payload(kind, body, count).payload,
                            "SDK/oracle codec disagreement",
                        )
                    row["sample_checks"] += 1
                    row["samples"].append(frame.hex())
                row["encodings"][key] = row["encodings"].get(key, 0) + 1
                for key, value in (
                    ("frames", 1),
                    ("items", count),
                    ("logical_bytes", logical),
                    ("encoded_bytes", encoded),
                    ("wire_bytes", total),
                ):
                    row[key] += value
                for key, value in (("versions", version), ("run_ids", run)):
                    if value not in row[key]:
                        row[key].append(value)
        except Exception:
            self.errors += 1
            raise
        finally:
            del self.buffer[:consumed]

    def snapshot(self):
        return copy.deepcopy(
            dict(
                **self.streams,
                errors=self.errors,
                partial_bytes=len(self.buffer),
                raw_sha256=self.raw_hash.hexdigest(),
                raw_bytes=self.raw_bytes,
                control_samples=self.control_samples,
            )
        )


def temperature(daq, samples, phase):
    deadline = time.monotonic() + 1
    for attempt in range(64):
        # Temperature remains a read-only v2 diagnostic on the firmware. The
        # facade intentionally rejects legacy methods inside a v3 session;
        # its shared reader still decodes this explicit public-v2 request.
        reading = legacy_command(daq, v2.FrameKind.GET_TEMPERATURE_REQUEST).value
        row = {
            "phase": phase,
            "status": reading.status.name,
            "celsius": reading.celsius,
            "host_monotonic_seconds": time.monotonic(),
            "attempt": attempt + 1,
        }
        samples.append(row)
        print("TEMPERATURE " + json.dumps(row), flush=True)
        if reading.status.name == "NOT_READY" and time.monotonic() < deadline:
            time.sleep(
                min(
                    (0.007, 0.013, 0.023, 0.037)[attempt % 4],
                    max(0, deadline - time.monotonic()),
                )
            )
            continue
        require(
            reading.status.name == "VALID" and reading.celsius is not None,
            "temperature unavailable",
        )
        require(reading.celsius < THERMAL_LIMIT_C, "80 C thermal abort")
        return
    raise ValueError("temperature NOT_READY retry budget exhausted")


def legacy_command(daq, kind, payload=b""):
    response = daq._reader.request(kind, payload, protocol_version=2)
    require(response.ok, f"legacy command {kind} failed: {response.error_code}")
    return response


def clock_measurement(daq):
    request = GpioClockDiagnosticRequest(rate_hz=1_000_000)
    value = legacy_command(daq, 24, request.to_payload()).value
    require(
        value.healthy and value.dwt_counter_hz == 600_000_000,
        "physical clock diagnostic failed",
    )
    return asdict(value)


def capture(daq, tap, cell, settings, record):
    legacy = cell["kind"] == "legacy"
    result = {"settings_hex": settings.to_bytes().hex(), "temperatures": []}
    # Append before any action, so failures retain the partial attempt.
    record["captures"].append(result)
    # Legacy CONFIGURE enters CONFIGURED, where the historical clock diagnostic
    # is forbidden. Measure while IDLE, then verify its applied clock readback.
    clock_before = clock_measurement(daq) if legacy else None
    if legacy:
        config = DAQConfiguration(
            int(settings.stream_mask),
            int(settings.source),
            aux_bank_mode=int(settings.aux_bank_mode),
            rate_profile=4,
        )
        response = legacy_command(daq, 17, config.to_payload(protocol_version=2))
        require(response.value == config, "legacy CONFIGURE echo")
        applied = daq.get_settings()
    else:
        applied = daq.configure(settings)
    require(applied.settings == settings, "configuration echo/readback mismatch")
    result["clocks_before"] = asdict(applied.clocks)
    result["capabilities_hex"] = record["capabilities_hex"]
    temperature(daq, result["temperatures"], "before")
    result["clock_measurements"] = [clock_before or clock_measurement(daq)]
    tap.reset(settings.gpio_width_bits // 8)
    before_parser = daq.parser_counters.corruption_events
    before_host = daq.reader_counters.host_block_queue_drops
    before_reader = asdict(daq.reader_counters)
    result["stream_anomalies"] = 0
    result["stall_seconds"] = 0
    result["host_before"] = host_cpu()
    cpu = CpuTracker()
    cpu_started, wall_started = time.process_time(), time.monotonic()
    started_run = False
    try:
        run = legacy_command(daq, 18).run_id if legacy else daq.start()
        started_run = True
        result["run_id"] = run
        started = time.monotonic()
        next_temperature = started + min(10, cell["seconds"] / 2)
        stalled = False
        counts = {"adc": 0, "gpio": 0}
        while time.monotonic() - started < cell["seconds"]:
            if (
                cell["kind"] == "stall"
                and not stalled
                and time.monotonic() - started >= 1
            ):
                result["stall_seconds"] = cell["stall_seconds"]
                tap.pause_until = time.monotonic() + cell["stall_seconds"]
                time.sleep(cell["stall_seconds"])
                stalled = True
            block = (
                daq._reader.get_stream_item(timeout=1)
                if legacy
                else daq.read_block(timeout=1)
            )
            if isinstance(block, (ADCBlock, GPIOBlock)):
                require(
                    block.run_id == run
                    and block.protocol_version == (2 if legacy else 3)
                    and int(block.source) == int(settings.source),
                    "SDK block identity",
                )
                require(
                    block.pair_period_ticks == 8
                    if isinstance(block, ADCBlock)
                    else block.sample_period_ticks == 8
                    and block.packed_width_bits == settings.gpio_width_bits,
                    "SDK sample timing/layout mismatch",
                )
                counts["adc" if isinstance(block, ADCBlock) else "gpio"] += (
                    block.item_count
                )
            elif not (cell["kind"] == "stall" and isinstance(block, StreamGap)):
                result["stream_anomalies"] += 1
                raise ValueError(f"unexpected SDK event {block!r}")
            if time.monotonic() >= next_temperature:
                temperature(daq, result["temperatures"], "running")
                next_temperature = time.monotonic() + 10
        result["duration_seconds"] = time.monotonic() - started
        result["sdk_items"] = counts
    finally:
        if started_run:
            if legacy:
                legacy_command(daq, 20)
            else:
                daq.stop()
        cpu.sample()
        result["host_after"] = host_cpu()
        result["host_cpu"] = {
            **cpu.summary(),
            "process_seconds": time.process_time() - cpu_started,
            "wall_seconds": time.monotonic() - wall_started,
        }
        # No added acquisition-time commands. Retain ownership even when the
        # stream raised a gap: the original failure must remain a failure.
        try:
            result["ownership_after_stop"] = asdict(legacy_command(daq, 19).value)
        except Exception as error:  # noqa: BLE001 - preserve the original stream failure
            result["ownership_error"] = f"{type(error).__name__}: {error}"
        result["oracle"] = tap.snapshot()
        result["parser_errors"] = daq.parser_counters.corruption_events - before_parser
        result["host_queue_drops"] = (
            daq.reader_counters.host_block_queue_drops - before_host
        )
    require("ownership_error" not in result, "post-STOP ownership unavailable")
    status = legacy_command(daq, 19).value if legacy else daq.status()
    if legacy:
        # v2 STOP reports IDLE before USB drain; wait on actual packet ownership.
        deadline = time.monotonic() + 2
        while status.packet_owned_depth:
            require(time.monotonic() < deadline, "legacy STOP drain deadline")
            time.sleep(0.005)
            status = legacy_command(daq, 19).value
    result["oracle"] = tap.snapshot()
    result["reader_delta"] = {
        name: value - before_reader[name]
        for name, value in asdict(daq.reader_counters).items()
    }
    result["status"] = asdict(status)
    result["stopped"] = int(status.device_state if legacy else status.state) == 1
    if not legacy and cell["kind"] != "stall":
        daq.validate_stream_health(status)
    # Explicit v2 commands bypass the v3 session state; the stopped readback is
    # still public v3 and verifies the same applied RAW tuple at fixed 600 MHz.
    applied = daq.get_settings()
    result["readback_hex"] = applied.settings.to_bytes().hex()
    result["clocks_after"] = asdict(daq.info().clocks)
    result["clock_measurements"].append(clock_measurement(daq))
    temperature(daq, result["temperatures"], "after")
    problems = validate_capture(cell, result)
    require(not problems, "; ".join(problems))


def run(candidate, cell, transport):
    tap = WireTap(transport)
    record = {
        "cell_id": cell["id"],
        "cell": cell,
        "candidate_sha256": json_hash(candidate),
        "outcome": "FAIL",
        "physical": False,
        "captures": [],
        "rejections": [],
    }
    try:
        # Observe mode for deliberate firmware drops; all normal paths explicitly
        # enforce health and zero unexplained loss before acceptance.
        with ThingDAQ.open(tap, strict=False, max_buffered_blocks=2048) as daq:
            info = daq.info()
            record["info"] = asdict(info)
            record["physical"] = not info.simulated
            for key, expected in candidate["identity"].items():
                require(getattr(info, key) == expected, f"candidate {key} mismatch")
            require(
                not info.simulated and info.protocol_version == 3,
                "physical public-v3 required",
            )
            record["capabilities_hex"] = daq.get_capabilities().to_payload().hex()
            require(
                record["capabilities_hex"] == candidate["capabilities_hex"],
                "advertised tuples differ",
            )
            settings = V3Settings.from_bytes(bytes.fromhex(cell["settings_hex"]))
            if cell["kind"] == "negative":
                record["temperatures"] = []
                temperature(daq, record["temperatures"], "before")
                daq.configure(settings)
                for payload in cell["rejected_hex"]:
                    before = daq.get_settings()
                    # Send a well-formed SDK request but replace its payload at
                    # the transport boundary. Invalid tuples must reach firmware
                    # instead of being rejected by the SDK's canonical table.
                    tap.override_configure = bytes.fromhex(payload)
                    response = daq._reader.request(
                        17, settings.to_bytes(), protocol_version=3
                    )
                    after = daq.get_settings()
                    row = {
                        "settings_hex": payload,
                        "error_code": int(response.error_code),
                        "before": before.settings.to_bytes().hex(),
                        "after": after.settings.to_bytes().hex(),
                        "cpu_clock_hz": after.clocks.cpu_clock_hz,
                        "state": int(daq.status().state),
                        "request_wire_hex": tap.last_override_wire,
                    }
                    record["rejections"].append(row)
                    require(
                        response.error_code == cell["expected_errors"][payload]
                        and before == after,
                        "unsupported tuple accepted/mutated",
                    )
                temperature(daq, record["temperatures"], "after")
            else:
                previous = None
                for index in range(cell["cycles"]):
                    selected = (
                        V3Settings.from_bytes(bytes.fromhex(cell["alternate_hex"]))
                        if index % 2 and "alternate_hex" in cell
                        else settings
                    )
                    capture(daq, tap, cell, selected, record)
                    run_id = record["captures"][-1]["run_id"]
                    require(
                        previous is None or run_id == previous + 1,
                        "same-boot run reset/jump",
                    )
                    previous = run_id
            record["outcome"] = "PASS"
    except Exception as error:  # noqa: BLE001 - preserve failed physical evidence
        record["outcome"] = "FAIL"
        record["error"] = f"{type(error).__name__}: {error}"
        record["failure_oracle"] = tap.snapshot()
    finally:
        tap.close()
    return record


def main():
    candidate = json.loads(os.environ["QUALIFICATION_CANDIDATE"])
    cell = json.loads(os.environ["QUALIFICATION_CELL"])
    # Starts only once the container is executing, so queue residence never
    # consumes this setup window. Serial must stay closed until readback passes.
    deadline = time.monotonic() + 30
    while True:
        setup = host_cpu()
        if (
            setup.get("cpu.max", "").split() == ["200000", "100000"]
            and len(setup.get("affinity", [])) >= 2
        ):
            record = run(candidate, cell, SerialTransport(os.environ["SERIAL_PORT"]))
            break
        if time.monotonic() >= deadline:
            record = {
                "cell_id": cell["id"],
                "candidate_sha256": json_hash(candidate),
                "outcome": "FAIL",
                "captures": [],
                "error": "two-core host CPU allocation not established before serial open",
            }
            break
        time.sleep(0.25)
    record["host_setup"] = setup
    print("QUALIFICATION " + json.dumps(record, sort_keys=True), flush=True)
    return 0 if record["outcome"] == "PASS" else 1
