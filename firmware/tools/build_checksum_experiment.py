#!/usr/bin/env python3
"""Build isolated checksum A/B variants with normal release memory/toolchain gates.

The no-data-checksum variant is NOT wire compatible and must only be used with
run_input_isolation.py --checksum-experiment. Production builders never enable
these flags.
"""

from __future__ import annotations

import argparse
import dataclasses
import hashlib
import json
from pathlib import Path

import build_firmware as base

MODES = {
    "baseline": "",
    "none": "THINGDAQ_EXPERIMENT_NO_DATA_CHECKSUM",
}


def main() -> int:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--mode", choices=MODES, required=True)
    parser.add_argument(
        "--large-adc-frame",
        action="store_true",
        help="research-only: double 16-input ADC payload to 4048 bytes",
    )
    parser.add_argument("--arduino-cli", default="arduino-cli")
    args = parser.parse_args()
    mode = args.mode
    frame_suffix = ":adc-frame-4096" if args.large_adc_frame else ""
    base.OUTPUT_DIRECTORY = (
        base.SKETCH_DIRECTORY
        / "build"
        / (f"checksum-{mode}" + ("-adc4096" if args.large_adc_frame else ""))
    )
    original_identity = base.build_identity
    original_definitions = base.identity_definitions
    original_command = base.compile_command

    def identity(environment=None):
        original = original_identity(environment)
        source_id = hashlib.sha256(
            f"{original.source_id}:checksum-experiment-v1:{mode}{frame_suffix}".encode()
        ).hexdigest()
        return dataclasses.replace(
            original, source_id=source_id, build_id=f"thingdaq-{source_id[:16]}"
        )

    base.build_identity = identity
    base.identity_definitions = lambda definitions, selected: (
        original_definitions(definitions, selected)
        + (f" -D{MODES[mode]}=1" if MODES[mode] else "")
        + (" -DTHINGDAQ_EXPERIMENT_LARGE_ADC_FRAME=1" if args.large_adc_frame else "")
    )
    # Keep transient compiler products inside this checkout as well.
    base.compile_command = lambda *parameters: (
        original_command(*parameters)
        + ["--build-path", str(base.OUTPUT_DIRECTORY / "compile")]
    )
    manifest_path = base.build(args.arduino_cli)
    manifest = json.loads(manifest_path.read_text())
    manifest["checksum_experiment"] = {
        "mode": mode,
        "data_integrity_checked": mode != "none",
        "wire_compatible": mode != "none",
        "control_checksums": "unchanged",
        "base_source_id": original_identity().source_id,
        "builder_sha256": hashlib.sha256(Path(__file__).read_bytes()).hexdigest(),
        "identity_policy": "sha256(source_id:checksum-experiment-v1:mode)",
    }
    if args.large_adc_frame:
        manifest["frame_experiment"] = {
            "input_adc_frame_bytes": 4096,
            "input_adc_pairs_per_frame": 1012,
            "gpio_frame_bytes": 4096,
            "packet_pool_bytes": 819200,
            "wire_compatible": False,
        }
        manifest["checksum_experiment"]["wire_compatible"] = False
        manifest["checksum_experiment"]["identity_policy"] = (
            "sha256(source_id:checksum-experiment-v1:mode:adc-frame-4096)"
        )
    manifest_path.write_text(json.dumps(manifest, indent=2, sort_keys=True) + "\n")
    print(manifest_path)
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
