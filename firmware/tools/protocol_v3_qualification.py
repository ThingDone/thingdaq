"""Public-v3 qualification policy shared by the rig and offline evidence gate.

Historical soak campaigns deliberately retain their original policy/decoder.
This policy never treats simulated, incomplete or retried failures as release PASS.
"""

from __future__ import annotations

import hashlib
import json
import math
from dataclasses import asdict, replace

from thingdone_daq._generated import protocol_v3_constants as c
from thingdone_daq.models_v3 import V3Capabilities, V3Settings

POLICY = "public-v3-qualification-1"
THERMAL_LIMIT_C = 80
HEALTH_FIELDS = (
    "parser_errors",
    "transport_errors",
    "adc_dma_error_events",
    "adc_etc_error_events",
    "gpio_hardware_errors",
    "adc_raw_invariant_errors",
    "gpio_raw_invariant_errors",
    "packet_invalid_operations",
    "packet_encoding_rejections",
)


def json_hash(value):
    return hashlib.sha256(
        json.dumps(value, sort_keys=True, separators=(",", ":")).encode()
    ).hexdigest()


def capabilities(payload_hex):
    return V3Capabilities.from_payload(bytes.fromhex(payload_hex))


def matrix(payload_hex):
    """Use the entire advertised table, including synthetic operating cells."""
    caps = capabilities(payload_hex)
    if (
        caps.defaults != V3Settings.defaults()
        or any(p.cpu_clock_hz != 600_000_000 for p in caps.cpu_profiles)
        or any(s.cpu_profile != c.CpuProfile.CPU_600MHZ for s in caps.configurations)
    ):
        raise ValueError("qualification requires the normal fixed-600 MHz defaults")
    rows = []

    def add(name, kind, settings, seconds, cycles=1, **extra):
        # Reuse the service's 780-second planning ceiling and 600-second cell cap.
        if not 0 <= seconds <= 600 or 30 + (seconds + 5) * cycles > 780:
            raise ValueError("cell exceeds safe service budget")
        rows.append(
            dict(
                id=name,
                kind=kind,
                settings_hex=settings.to_bytes().hex(),
                seconds=seconds,
                cycles=cycles,
                **extra,
            )
        )

    for settings in sorted(caps.configurations, key=lambda s: s.to_bytes()):
        key = settings.to_bytes().hex()
        add(f"smoke-{key}", "smoke", settings, 60)
    default = caps.defaults
    raw = replace(default, gpio_policy=c.GpioPolicy.RAW, adc_policy=c.AdcPolicy.RAW)
    caps.require_supported(raw)
    add("same-boot-20", "lifecycle", default, 1, 20, alternate_hex=raw.to_bytes().hex())
    for index in range(3):
        add(f"soak-{index + 1}", "soak", default, 600)
    for mode in (c.AuxBankMode.DISABLED, c.AuxBankMode.INPUT):
        selected = caps.select_settings(aux_bank_mode=mode)
        add(f"stall-{int(mode)}", "stall", selected, 60, stall_seconds=0.25)
        synthetic = replace(selected, source=c.Source.SYNTHETIC)
        caps.require_supported(synthetic)
        add(f"fallback-{int(mode)}", "fallback", synthetic, 60)
        for mask in (1, 2, 3):
            legacy = replace(selected, stream_mask=mask, gpio_policy=0, adc_policy=0)
            caps.require_supported(legacy)
            add(f"v2-{int(mode)}-{mask}", "legacy", legacy, 60)
    # Every canonical tuple absent from the advertisement is tested on the wire.
    # Also cover a non-enum CPU request (528 MHz is not a public profile).
    unsupported = set(c.SELECTABLE_CONFIGURATIONS) - {
        s.to_bytes() for s in caps.configurations
    }
    rejected = {
        row.hex(): int(c.ErrorCode.UNSUPPORTED_CONFIGURATION) for row in unsupported
    }
    for offset, value in (
        (c.SETTINGS_CPU_PROFILE_OFFSET, 3),
        (c.SETTINGS_STREAM_MASK_OFFSET, 0),
        (c.SETTINGS_GPIO_WIDTH_BITS_OFFSET, 32),
        (c.SETTINGS_ADC_RESOLUTION_BITS_OFFSET, 10),
    ):
        payload = bytearray(default.to_bytes())
        payload[offset] = value
        rejected[bytes(payload).hex()] = int(c.ErrorCode.INVALID_PAYLOAD)
    for offset in (
        c.SETTINGS_ADC_PAIR_RATE_HZ_OFFSET,
        c.SETTINGS_GPIO_SAMPLE_RATE_HZ_OFFSET,
    ):
        payload = bytearray(default.to_bytes())
        payload[offset : offset + 4] = (2_000_000).to_bytes(4, "little")
        rejected[bytes(payload).hex()] = int(c.ErrorCode.UNSUPPORTED_CONFIGURATION)
    add(
        "unsupported",
        "negative",
        default,
        0,
        rejected_hex=sorted(rejected),
        expected_errors=rejected,
    )
    return rows


def finite(value):
    return (
        isinstance(value, (int, float))
        and not isinstance(value, bool)
        and math.isfinite(value)
    )


def valid_counter(value):
    return isinstance(value, int) and not isinstance(value, bool) and value >= 0


def validate_capture(cell, capture):
    """Recompute acceptance from measurements, not the runner's PASS label."""
    problems = []

    def need(condition, reason):
        if not condition:
            problems.append(reason)

    settings = V3Settings.from_bytes(bytes.fromhex(capture["settings_hex"]))
    legacy = cell["kind"] == "legacy"
    stall = cell["kind"] == "stall"
    expected_version = 2 if legacy else 3
    need(
        finite(capture["duration_seconds"])
        and capture["duration_seconds"] >= cell["seconds"],
        "capture too short/invalid",
    )
    need(capture["stopped"] is True, "STOP/drain incomplete")
    need(capture["readback_hex"] == capture["settings_hex"], "stale settings readback")
    expected_clocks = asdict(
        next(
            p
            for p in capabilities(capture["capabilities_hex"]).cpu_profiles
            if p.cpu_profile == settings.cpu_profile
        )
    )
    need(capture["clocks_before"] == expected_clocks, "initial clock mismatch")
    need(capture["clocks_after"] == expected_clocks, "stale final clocks")
    measurements = capture["clock_measurements"]
    need(len(measurements) == 2, "missing before/after physical clock measurements")
    for measurement in measurements:
        need(
            measurement["dwt_counter_hz"] == 600_000_000
            and measurement["pit_clock_hz"] == 24_000_000
            and measurement["pit_load_value"] == 23
            and measurement["request"]["rate_hz"] == 1_000_000
            and measurement["request"]["event_count"] == 8192
            and measurement["hardware_error_flags"] == 0
            and measurement["dwt_elapsed_cycles"] > 0
            and measurement["scheduled_event_count"]
            == measurement["dwt_elapsed_cycles"] // 600
            and abs(measurement["scheduled_event_count"] - 8192) <= 1
            and abs(
                measurement["dma_sample_count"] - measurement["scheduled_event_count"]
            )
            <= 1,
            "physical DWT/PIT/eDMA clock measurement failed",
        )
    temperatures = capture["temperatures"]
    for phase in ("before", "running", "after"):
        need(
            any(t["phase"] == phase and t["status"] == "VALID" for t in temperatures),
            f"missing {phase} temperature",
        )
    need(
        all(
            t["status"] in ("VALID", "NOT_READY")
            and (
                t["status"] == "NOT_READY"
                or (finite(t["celsius"]) and -40 <= t["celsius"] < THERMAL_LIMIT_C)
            )
            for t in temperatures
        ),
        "thermal abort or invalid temperature",
    )
    need(capture["parser_errors"] == 0, "SDK parser corruption")
    need(capture["host_queue_drops"] == 0, "host queue loss")
    need(capture["stream_anomalies"] == 0, "SDK stream anomaly")
    oracle = capture["oracle"]
    need(oracle["errors"] == 0, "independent wire oracle failure")
    need(oracle["partial_bytes"] == 0, "truncated wire frame")
    status = capture["status"]
    if not legacy:
        need(status["state"] == int(c.DeviceState.STOPPED), "firmware not stopped")
        need(status["pending_frames"] == 0, "pending firmware frames")
    else:
        need(status["device_state"] == 1, "legacy firmware not IDLE")
        need(status["packet_owned_depth"] == 0, "legacy STOP tail not drained")
    for field in HEALTH_FIELDS:
        need(status.get(field) == 0, f"unavailable/nonzero health: {field}")
    total_drops = 0
    for name, bit, width in (
        ("adc", 1, 4),
        ("gpio", 2, settings.gpio_width_bits // 8),
    ):
        wire = oracle[name]
        need(
            all(
                valid_counter(wire[k])
                for k in (
                    "frames",
                    "items",
                    "logical_bytes",
                    "encoded_bytes",
                    "wire_bytes",
                    "gap_items",
                    "end_item",
                    "sample_checks",
                )
            ),
            f"{name} invalid wire counters",
        )
        need(
            wire["end_item"] == wire["items"] + wire["gap_items"],
            f"{name} wire cursor accounting",
        )
        active = bool(int(settings.stream_mask) & bit)
        need(bool(wire["items"]) == active, f"{name} stream mask mismatch")
        for wire_metric, sdk_metric in (
            ("frames", "frames"),
            ("items", "items"),
            ("logical_bytes", "decoded_bytes"),
            ("wire_bytes", "wire_bytes"),
        ):
            need(
                capture["reader_delta"][f"{name}_{sdk_metric}_received"]
                == wire[wire_metric],
                f"{name} SDK/oracle {wire_metric} mismatch",
            )
        if not active:
            continue
        need(capture["sdk_items"][name] > 0, f"{name} no application data")
        need(wire["versions"] == [expected_version], f"{name} private/wrong version")
        need(wire["run_ids"] == [capture["run_id"]], f"{name} run mismatch")
        need(wire["sample_checks"] > 0, f"{name} missing independent codec check")
        need(wire["logical_bytes"] == wire["items"] * width, f"{name} logical bytes")
        # The independent cursor accounts for leading and internal gaps; final
        # producer counters also bind the otherwise invisible STOP tail.
        if legacy:
            produced = status[f"{name}_frames_generated"]
            dropped = status[f"{name}_frames_dropped"]
            items_produced = status[f"{name}_items_generated"]
            items_dropped = status[f"{name}_items_dropped"]
            need(
                status[f"{name}_frames_transmitted"] == wire["frames"],
                f"{name} legacy transmit accounting",
            )
        else:
            produced = status[f"{name}_frames_produced"]
            dropped = status[f"{name}_frames_dropped"]
            items_produced = status[f"{name}_items_produced"]
            items_dropped = status[f"{name}_items_dropped"]
            for metric in ("logical_bytes", "encoded_bytes", "wire_bytes"):
                need(
                    status[f"{name}_{metric}_transmitted"] == wire[metric],
                    f"{name} transmitted {metric} mismatch",
                )
            for counter in ("codec_deadline_drops", "codec_resource_drops"):
                value = status[f"{name}_{counter}"]
                need(
                    isinstance(value, int) and (stall or value == 0),
                    f"{name} {counter}",
                )
        total_drops += items_dropped
        need(
            all(
                valid_counter(v)
                for v in (produced, dropped, items_produced, items_dropped)
            ),
            f"{name} invalid firmware counters",
        )
        need(produced == wire["frames"] + dropped, f"{name} frame conservation")
        need(
            items_produced == wire["items"] + items_dropped, f"{name} item conservation"
        )
        need(wire["gap_items"] <= items_dropped, f"{name} unexplained sample gap")
        need(
            items_produced - wire["end_item"] == items_dropped - wire["gap_items"],
            f"{name} tail accounting",
        )
        need(stall or dropped == items_dropped == 0, f"{name} unexpected drops")
        if cell["seconds"] >= 60 and not stall:
            elapsed = wire["last_host_seconds"] - wire["first_host_seconds"]
            measured = (
                (wire["last_ticks"] - wire["first_ticks"]) / 8 / elapsed
                if elapsed > 0
                else 0
            )
            need(
                abs(measured / 1_000_000 - 1) <= 0.01,
                f"{name} measured rate outside 1%",
            )
    if stall:
        need(
            capture["stall_seconds"] >= cell["stall_seconds"],
            "host stall not exercised",
        )
        need(total_drops > 0, "stall produced no observable drop")
    if cell["kind"] == "fallback":
        encodings = oracle["gpio"]["encodings"]
        need(
            encodings.get("0", 0) > 0 and encodings.get("1", 0) > 0,
            "RLE/RAW fallback unobserved",
        )
        need(status["gpio_codec_raw"] > 0, "firmware RAW fallback counter absent")
    return problems


def validate_evidence(candidate, records):
    """All attempts are authoritative; success never erases an earlier failure."""
    required = {row["id"]: row for row in matrix(candidate["capabilities_hex"])}
    errors, missing, seen, jobs = [], [], set(), set()
    outcomes = []
    for record in records:
        label = record.get("cell_id", "?")
        problems = []
        if record.get("retention_error") and record.get("outcome") == "INCONCLUSIVE":
            outcomes.append(
                {
                    "cell_id": label,
                    "problems": [record["retention_error"]],
                    "outcome": "INCONCLUSIVE",
                }
            )
            continue
        try:
            cell = required[label]
            seen.add(label)
            job = record["job_id"]
            if not job or job in jobs:
                problems.append("missing/duplicate job ID")
            jobs.add(job)
            if record["candidate_sha256"] != json_hash(candidate):
                problems.append("candidate identity mismatch")
            if record["physical"] is not True:
                problems.append("physical evidence missing")
            if record["outcome"] != "PASS":
                problems.append(f"retained attempt outcome {record['outcome']}")
            info = record["info"]
            for key in (
                "hardware_serial",
                "build_id",
                "firmware_version",
                "board_id",
                "mcu_id",
            ):
                if info[key] != candidate["identity"][key]:
                    problems.append(f"observed {key} mismatch")
            if info["simulated"] is not False or info["protocol_version"] != 3:
                problems.append("nonphysical/nonpublic INFO")
            if record["capabilities_hex"] != candidate["capabilities_hex"]:
                problems.append("advertisement changed")
            if record["cell"] != cell:
                problems.append("matrix cell changed")
            if cell["kind"] == "negative":
                for phase in ("before", "after"):
                    if not any(
                        t["phase"] == phase
                        and t["status"] == "VALID"
                        and finite(t["celsius"])
                        and -40 <= t["celsius"] < THERMAL_LIMIT_C
                        for t in record["temperatures"]
                    ):
                        problems.append(
                            f"missing/unsafe negative-test {phase} temperature"
                        )
                checks = record["rejections"]
                if [r["settings_hex"] for r in checks] != cell["rejected_hex"]:
                    problems.append("missing negative tuples")
                for check in checks:
                    if (
                        check["error_code"]
                        != cell["expected_errors"][check["settings_hex"]]
                        or check["before"] != check["after"]
                        or check["before"] != cell["settings_hex"]
                        or check["cpu_clock_hz"] != 600_000_000
                        or check["state"] != int(c.DeviceState.STOPPED)
                    ):
                        problems.append("negative request accepted/mutated settings")
            else:
                captures = record["captures"]
                if len(captures) != cell["cycles"]:
                    problems.append("missing captures/lifecycle cycles")
                previous = None
                for index, capture in enumerate(captures):
                    expected = (
                        cell.get("alternate_hex") if index % 2 else cell["settings_hex"]
                    )
                    expected = expected or cell["settings_hex"]
                    if capture["settings_hex"] != expected:
                        problems.append("configuration sequence mismatch")
                    if capture["capabilities_hex"] != candidate["capabilities_hex"]:
                        problems.append("capture advertisement mismatch")
                    if previous is not None and capture["run_id"] != previous + 1:
                        problems.append("same-boot run ID reset/jump")
                    previous = capture["run_id"]
                    problems.extend(validate_capture(cell, capture))
        except (KeyError, TypeError, ValueError, OverflowError) as error:
            problems.append(f"missing/malformed evidence: {error}")
        errors.extend(f"{label}: {problem}" for problem in problems)
        outcomes.append(
            {
                "cell_id": label,
                "problems": problems,
                "outcome": "FAIL" if problems else "PASS",
            }
        )
    missing = sorted(required.keys() - seen)
    outcome = (
        "FAIL"
        if errors
        else "NOT_RUN"
        if not records
        else "INCONCLUSIVE"
        if missing or any(r["outcome"] == "INCONCLUSIVE" for r in outcomes)
        else "PASS"
    )
    return {
        "policy": POLICY,
        "outcome": outcome,
        "missing_cells": missing,
        "problems": errors,
        "attempts": outcomes,
        "physical_qualification": outcome,
        "checks": {
            "matrix_complete": not missing,
            "all_attempts_valid": not errors
            and all(r["outcome"] == "PASS" for r in outcomes),
            "physical_evidence_present": bool(records)
            and all(r.get("physical") is True for r in records),
        },
        "endurance": "three separate reflashed 600-second jobs; lifecycle is same-boot only",
    }
