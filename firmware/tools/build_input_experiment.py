#!/usr/bin/env python3
"""Build isolated equal-rate / CPU-clock research variants using all normal gates.

Not a public protocol revision: profile IDs are experiment-local, and standard
v2 hosts must reject a different advertised table. The optional larger frame
keeps checksums and uses the fixed 450 MHz / 1 MHz release policy. Use the
matching isolation validator and explicit --frame-experiment opt-in.
"""

from __future__ import annotations

import argparse
import dataclasses
import hashlib
import json
from pathlib import Path

import build_firmware as base


def experiment_identity(
    identity: base.BuildIdentity,
    cpu_mhz: int,
    equal_rates: bool,
    *,
    release_fixed_1mhz: bool = False,
    large_adc_frame: bool = False,
) -> base.BuildIdentity:
    selection = f"input-rate-clock-v1:{cpu_mhz}:{int(equal_rates)}"
    if release_fixed_1mhz or large_adc_frame:
        selection += (
            f":release={int(release_fixed_1mhz)}:large-adc={int(large_adc_frame)}"
        )
    source_id = hashlib.sha256(f"{identity.source_id}:{selection}".encode()).hexdigest()
    return dataclasses.replace(
        identity, source_id=source_id, build_id=f"thingdaq-{source_id[:16]}"
    )


def large_frame_retention(packet_buffers: dict) -> dict:
    """Project the existing retention calculation onto the compiled ADC layout."""
    contract = base._protocol_v2_contract()
    for profile in contract["rate_profiles"]:
        profile["frame_coverage_ticks"]["INPUT"] *= 2
    result = base.packet_retention_usage(packet_buffers, contract)
    # This candidate enables only release profile 4. The other historical
    # profiles do not have this candidate's time-coverage relationship.
    result["profiles"] = result["profiles"][-1:]
    result["coverage_units"] = "ADC frames; conservative bounds for release profile 4"
    return result


def main() -> int:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--cpu-mhz", type=int, choices=(600, 450), required=True)
    parser.add_argument("--equal-rates", action="store_true")
    parser.add_argument("--release-fixed-1mhz", action="store_true")
    parser.add_argument("--large-adc-frame", action="store_true")
    parser.add_argument("--arduino-cli", default="arduino-cli")
    args = parser.parse_args()
    if args.release_fixed_1mhz and (args.cpu_mhz != 450 or args.equal_rates):
        parser.error(
            "--release-fixed-1mhz requires --cpu-mhz 450 without --equal-rates"
        )
    if args.large_adc_frame and not args.release_fixed_1mhz:
        parser.error("--large-adc-frame requires --release-fixed-1mhz")
    base.RELEASE_BUILD = args.release_fixed_1mhz
    base.FQBN = f"teensy:avr:teensy40:usb=serial,speed={args.cpu_mhz},opt=o2std"
    base.EXPECTED_BUILD_PROPERTIES = {
        **base.EXPECTED_BUILD_PROPERTIES,
        "build.fcpu": str(args.cpu_mhz * 1_000_000),
    }
    mode = "equal" if args.equal_rates else "ratio4"
    if args.release_fixed_1mhz:
        mode = "release-large-adc" if args.large_adc_frame else "release"
    base.OUTPUT_DIRECTORY = (
        base.SKETCH_DIRECTORY / "build" / (f"input-experiment-{mode}-{args.cpu_mhz}")
    )
    original_identity = base.build_identity
    original_definitions = base.identity_definitions
    base.build_identity = lambda environment=None: experiment_identity(
        original_identity(environment),
        args.cpu_mhz,
        args.equal_rates,
        release_fixed_1mhz=args.release_fixed_1mhz,
        large_adc_frame=args.large_adc_frame,
    )
    base.identity_definitions = lambda definitions, identity: (
        original_definitions(definitions, identity)
        + f" -DTHINGDAQ_EXPERIMENT_CPU_HZ={args.cpu_mhz * 1_000_000}U"
        + f" -DTHINGDAQ_EXPERIMENT_EQUAL_RATES={int(args.equal_rates)}"
        + (" -DTHINGDAQ_EXPERIMENT_LARGE_ADC_FRAME=1" if args.large_adc_frame else "")
    )
    manifest_path = base.build(args.arduino_cli)
    manifest = json.loads(manifest_path.read_text())
    if args.large_adc_frame:
        inspection = manifest["binary_inspection"]
        inspection["packet_retention"] = large_frame_retention(
            inspection["packet_buffers"]
        )
    manifest["input_experiment"] = {
        "cpu_mhz": args.cpu_mhz,
        "ipg_hz": 150_000_000,
        "adc_clock_hz": 37_500_000,
        "pit_hz": 24_000_000,
        "equal_rates": args.equal_rates,
        "release_fixed_1mhz": args.release_fixed_1mhz,
        "large_adc_frame": args.large_adc_frame,
        "data_checksum": "standard-adler32",
        "public_protocol_compatible": not args.large_adc_frame
        and (args.release_fixed_1mhz or (not args.equal_rates and args.cpu_mhz == 600)),
        "identity_policy": "sha256(source_sha256:input-rate-clock-v1:cpu_mhz:equal_flag[:release=flag:large-adc=flag])",
        "base_source_id": original_identity().source_id,
        "builder_sha256": hashlib.sha256(Path(__file__).read_bytes()).hexdigest(),
    }
    manifest_path.write_text(json.dumps(manifest, indent=2, sort_keys=True) + "\n")
    print(manifest_path)
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
