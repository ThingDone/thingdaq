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
    parser.add_argument("--usb-throughput", action="store_true")
    parser.add_argument("--usb-write-bytes", type=int, choices=(1024, 2048, 4096))
    parser.add_argument("--pipeline-batch-scale", type=int, choices=(1, 2), default=1)
    args = parser.parse_args()
    if args.pipeline_batch_scale != 1 and args.usb_write_bytes is None:
        parser.error("--pipeline-batch-scale requires --usb-write-bytes")
    if args.usb_throughput and args.usb_write_bytes is not None:
        parser.error("acquisition USB write experiments cannot use --usb-throughput")
    if args.usb_throughput and (args.large_adc_frame or args.mode != "none"):
        parser.error("--usb-throughput requires --mode none without --large-adc-frame")
    mode = args.mode
    frame_suffix = ":adc-frame-4096" if args.large_adc_frame else ""
    if args.usb_throughput:
        frame_suffix = ":usb-throughput-v1"
    acquisition_suffix = (
        f"-usb{args.usb_write_bytes}-batch{args.pipeline_batch_scale}"
        if args.usb_write_bytes is not None
        else ""
    )
    if acquisition_suffix:
        frame_suffix += f":acquisition-v1{acquisition_suffix}"
    base.OUTPUT_DIRECTORY = (
        base.SKETCH_DIRECTORY
        / "build"
        / (
            "usb-throughput"
            if args.usb_throughput
            else f"checksum-{mode}"
            + ("-adc4096" if args.large_adc_frame else "")
            + acquisition_suffix
        )
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
        + (" -DTHINGDAQ_EXPERIMENT_USB_THROUGHPUT=1" if args.usb_throughput else "")
        + (
            f" -DTHINGDAQ_EXPERIMENT_USB_WRITE_BYTES={args.usb_write_bytes}"
            f" -DTHINGDAQ_EXPERIMENT_PIPELINE_BATCH_SCALE={args.pipeline_batch_scale}"
            if args.usb_write_bytes is not None
            else ""
        )
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
    if args.usb_throughput:
        manifest["usb_throughput_experiment"] = {
            "interface": "TDUSB1",
            "wire_compatible": False,
            "working_bytes": 8192,
            "allocation": "borrowed idle DTCM packet pages",
            "modes": {
                "1": "gpio-4k",
                "2": "gpio-8k",
                "3": "separate-4k",
                "4": "coalesced-8k",
                "5": "combined-8k",
            },
            "header_bytes": 32,
            "synthetic_prebuilt_payload": True,
        }
        manifest["checksum_experiment"]["control_checksums"] = (
            "ASCII diagnostic interface has no checksum"
        )
        manifest["checksum_experiment"]["identity_policy"] = (
            "sha256(source_id:checksum-experiment-v1:mode:usb-throughput-v1)"
        )
    if acquisition_suffix:
        manifest["acquisition_usb_experiment"] = {
            "max_write_bytes": args.usb_write_bytes,
            "pipeline_batch_scale": args.pipeline_batch_scale,
            "adc_buffers_per_visit": 2 * args.pipeline_batch_scale,
            "gpio_buffers_per_visit": 2 * args.pipeline_batch_scale,
            "packet_promotions_per_visit": 4 * args.pipeline_batch_scale,
            "tx_bytes_per_visit": 8192,
            "tx_calls_per_visit": 8,
            "tx_visits_per_loop": 2,
            "packet_pool_bytes": 819200,
        }
        manifest["checksum_experiment"]["identity_policy"] = (
            f"sha256(source_id:checksum-experiment-v1:{mode}{frame_suffix})"
        )
    manifest_path.write_text(json.dumps(manifest, indent=2, sort_keys=True) + "\n")
    print(manifest_path)
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
