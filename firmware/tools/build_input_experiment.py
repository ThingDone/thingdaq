#!/usr/bin/env python3
"""Build isolated equal-rate / CPU-clock research variants using all normal gates.

Not a public protocol revision: profile IDs are experiment-local, the GPIO
frame spans four ADC frames in equal-rate mode, and standard v2 hosts must
reject its different advertised table. Use the matching isolation validator.
"""

from __future__ import annotations

import argparse
import dataclasses
import hashlib
import json
from pathlib import Path

import build_firmware as base


def experiment_identity(identity: base.BuildIdentity, cpu_mhz: int,
                        equal_rates: bool) -> base.BuildIdentity:
    selection = f"input-rate-clock-v1:{cpu_mhz}:{int(equal_rates)}"
    source_id = hashlib.sha256(
        f"{identity.source_id}:{selection}".encode()
    ).hexdigest()
    return dataclasses.replace(identity, source_id=source_id,
                               build_id=f"thingdaq-{source_id[:16]}")


def main() -> int:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--cpu-mhz", type=int, choices=(600, 450), required=True)
    parser.add_argument("--equal-rates", action="store_true")
    parser.add_argument("--arduino-cli", default="arduino-cli")
    args = parser.parse_args()
    base.FQBN = f"teensy:avr:teensy40:usb=serial,speed={args.cpu_mhz},opt=o2std"
    base.EXPECTED_BUILD_PROPERTIES = {
        **base.EXPECTED_BUILD_PROPERTIES,
        "build.fcpu": str(args.cpu_mhz * 1_000_000),
    }
    mode = "equal" if args.equal_rates else "ratio4"
    base.OUTPUT_DIRECTORY = base.SKETCH_DIRECTORY / "build" / (
        f"input-experiment-{mode}-{args.cpu_mhz}"
    )
    original_identity = base.build_identity
    original_definitions = base.identity_definitions
    base.build_identity = lambda environment=None: experiment_identity(
        original_identity(environment), args.cpu_mhz, args.equal_rates
    )
    base.identity_definitions = lambda definitions, identity: (
        original_definitions(definitions, identity)
        + f" -DTHINGDAQ_EXPERIMENT_CPU_HZ={args.cpu_mhz * 1_000_000}U"
        + f" -DTHINGDAQ_EXPERIMENT_EQUAL_RATES={int(args.equal_rates)}"
    )
    manifest_path = base.build(args.arduino_cli)
    manifest = json.loads(manifest_path.read_text())
    manifest["input_experiment"] = {
        "cpu_mhz": args.cpu_mhz,
        "ipg_hz": 150_000_000,
        "adc_clock_hz": 37_500_000,
        "pit_hz": 24_000_000,
        "equal_rates": args.equal_rates,
        "public_protocol_compatible": not args.equal_rates and args.cpu_mhz == 600,
        "identity_policy": "sha256(source_sha256:input-rate-clock-v1:cpu_mhz:equal_flag)",
        "base_source_id": original_identity().source_id,
        "builder_sha256": hashlib.sha256(Path(__file__).read_bytes()).hexdigest(),
    }
    manifest_path.write_text(json.dumps(manifest, indent=2, sort_keys=True) + "\n")
    print(manifest_path)
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
