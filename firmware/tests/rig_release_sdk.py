"""Bounded on-board release acceptance through the bundled public Python SDK."""

from __future__ import annotations

import dataclasses
import json
import os
import time
from pathlib import Path

from thingdaq import (
    ADCBlock,
    AuxBankMode,
    DAQConfiguration,
    DeviceCapabilityError,
    DeviceCommandError,
    DeviceState,
    ErrorCode,
    ExpectedDeviceIdentity,
    GPIOBlock,
    RateProfile,
    Source,
    StreamMask,
    ThingDAQ,
)
from thingdaq._generated import protocol_v2_constants as c


def temperature(daq):
    readings = []
    for _ in range(5):
        reading = daq.get_temperature()
        readings.append({"status": reading.status.name, "celsius": reading.celsius})
        if reading.celsius is not None:
            return readings
        time.sleep(0.02)
    raise AssertionError(f"no valid die temperature: {readings}")


def main():
    evidence = {
        "result": "FAIL",
        "validator": "public-sdk",
        "cells": [],
        "electrical_stimulus": "NOT_CONNECTED",
    }
    for name in ("cpu.max", "cpu.stat"):
        path = Path("/sys/fs/cgroup") / name
        if path.exists():
            evidence[name] = path.read_text()
    try:
        expected = ExpectedDeviceIdentity(
            hardware_serial=int(os.environ["EXPECTED_HARDWARE_SERIAL"]),
            build_id=os.environ["EXPECTED_BUILD_ID"],
            firmware_version=(1, 1, 0),
            protocol_version=2,
        )
        duration = float(os.environ["AUX_INPUT_CAPTURE_SECONDS"]) / 5
        with ThingDAQ.open(
            os.environ["SERIAL_PORT"],
            expected_identity=expected,
            strict=True,
            max_buffered_blocks=2048,
            read_size=16384,
        ) as daq:
            info = daq.info()
            assert info.protocol_version == 2
            assert info.adc_trigger.dwt_clock_hz == 450_000_000
            assert info.auxiliary.supported_rate_profile_mask == 16
            evidence["idle_temperature"] = temperature(daq)
            clock = daq.gpio_clock_diagnostic()
            assert clock.healthy and clock.dwt_counter_hz == 450_000_000
            assert clock.configured_rate_hz == 1_000_000
            evidence["clock_diagnostic"] = {
                "rate_hz": clock.configured_rate_hz,
                "dwt_hz": clock.dwt_counter_hz,
            }
            try:
                daq.gpio_clock_diagnostic(rate_hz=4_000_000)
            except DeviceCommandError as error:
                assert error.error_code is ErrorCode.UNSUPPORTED_CONFIGURATION
            else:
                raise AssertionError("firmware accepted a 4 MHz diagnostic")
            for rejected in list(RateProfile)[:4]:
                try:
                    daq.configure(rate_profile=rejected)
                except DeviceCapabilityError:
                    pass
                else:
                    raise AssertionError(f"SDK accepted unsupported profile {rejected}")
                raw = DAQConfiguration(
                    stream_mask=StreamMask.ADC | StreamMask.GPIO,
                    source=Source.HARDWARE,
                    rate_profile=rejected,
                )
                response = daq._reader.request(
                    c.FrameKind.CONFIGURE_REQUEST,
                    raw.to_payload(protocol_version=2),
                    protocol_version=2,
                )
                assert response.error_code is ErrorCode.UNSUPPORTED_CONFIGURATION
                assert daq.status().device_state is DeviceState.IDLE
            assert not int(info.capabilities.capability_bits) & int(
                c.Capability.GPIO_CAPTURE_DIAGNOSTIC
            )
            response = daq._reader.request(
                c.FrameKind.GPIO_CAPTURE_DIAGNOSTIC_REQUEST, protocol_version=2
            )
            assert response.error_code is ErrorCode.UNSUPPORTED_CONFIGURATION
            assert daq.status().device_state is DeviceState.IDLE
            evidence["legacy_capture_diagnostic"] = "REJECTED_BEFORE_CAPTURE"
            previous_run = None
            cells = [
                (AuxBankMode.DISABLED, StreamMask.ADC),
                (AuxBankMode.DISABLED, StreamMask.GPIO),
                (AuxBankMode.DISABLED, StreamMask.ADC | StreamMask.GPIO),
                (AuxBankMode.INPUT, StreamMask.GPIO),
                (AuxBankMode.INPUT, StreamMask.ADC | StreamMask.GPIO),
            ]
            for mode, streams in cells:
                daq.reset_stats()
                configuration = daq.configure(
                    source=Source.HARDWARE,
                    adc=bool(streams & StreamMask.ADC),
                    gpio=bool(streams & StreamMask.GPIO),
                    aux_bank_mode=mode,
                )
                assert configuration.rate_profile is RateProfile.ADC_1MHZ_GPIO_1MHZ
                run_id = daq.start()
                if previous_run is not None:
                    assert run_id == previous_run + 1
                previous_run = run_id
                started = time.monotonic()
                cpu_started = time.process_time()
                counts = {"adc_pairs": 0, "gpio_samples": 0}
                sampled = False
                during = []
                while time.monotonic() - started < duration:
                    try:
                        block = daq.read_block(timeout=1)
                    except Exception:
                        evidence["failure_timing"] = {
                            "wall": time.monotonic() - started,
                            "cpu": time.process_time() - cpu_started,
                        }
                        evidence["reader_counters"] = dataclasses.asdict(
                            daq._reader.counters
                        )
                        evidence["failure_status"] = dataclasses.asdict(daq.status())
                        evidence["failure_host"] = dataclasses.asdict(daq.host_counters)
                        raise
                    assert isinstance(block, (ADCBlock, GPIOBlock)), repr(block)
                    if isinstance(block, ADCBlock):
                        assert block.pair_period_ticks == 8
                        counts["adc_pairs"] += block.item_count
                    else:
                        assert block.sample_period_ticks == 8
                        assert block.packed_width_bits == (
                            16 if mode is AuxBankMode.INPUT else 8
                        )
                        counts["gpio_samples"] += block.item_count
                    if not sampled and time.monotonic() - started > duration / 2:
                        during = temperature(daq)
                        sampled = True
                assert bool(counts["adc_pairs"]) == bool(streams & StreamMask.ADC)
                assert bool(counts["gpio_samples"]) == bool(streams & StreamMask.GPIO)
                losses = daq.loss_counters()
                assert not losses.has_loss, repr(losses)
                assert daq.stop() is DeviceState.IDLE
                assert daq.status().device_state is DeviceState.IDLE
                evidence["cells"].append(
                    {
                        "mode": mode.name,
                        "streams": int(streams),
                        "run_id": run_id,
                        "counts": counts,
                        "seconds": duration,
                        "during_temperature": during,
                        "after_temperature": temperature(daq),
                    }
                )
            evidence["result"] = "PASS"
    except Exception as error:  # noqa: BLE001 - preserve the failed hardware result
        evidence["error"] = f"{type(error).__name__}: {error}"
        evidence["cause"] = repr(getattr(error, "cause", None))
        evidence["recovery"] = repr(getattr(error, "evidence", None))
    cpu_stat = Path("/sys/fs/cgroup/cpu.stat")
    if cpu_stat.exists():
        evidence["cpu.stat.after"] = cpu_stat.read_text()
    print("EVIDENCE " + json.dumps(evidence, sort_keys=True), flush=True)
    return 0 if evidence["result"] == "PASS" else 1
