"""Program and collect one M7 microbenchmark with the established rig client."""

from __future__ import annotations

import argparse
import json
import stat
from pathlib import Path

import build_firmware as build
import m7_performance
import run_input_isolation as rig


def main() -> int:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--build-dir", required=True, type=Path)
    parser.add_argument("--evidence-dir", required=True, type=Path)
    parser.add_argument("--service", required=True)
    parser.add_argument("--serial", type=int, default=20428100)
    parser.add_argument("--auth-file", type=Path, default=Path.home() / ".fw_api_key")
    args = parser.parse_args()
    if args.evidence_dir.exists():
        parser.error("choose a new immutable evidence directory")
    if stat.S_IMODE(args.auth_file.stat().st_mode) & 0o077:
        parser.error("credential file must be private")
    manifest_bytes = (args.build_dir / "benchmark-manifest.json").read_bytes()
    manifest = json.loads(manifest_bytes)
    elf = args.build_dir / "m7_performance.ino.elf"
    if build.sha256(elf) != manifest["elf_sha256"]:
        parser.error("ELF does not match benchmark manifest")
    # Derive HEX directly from the verified ELF: the original microbenchmark
    # manifest pins ELF but has no HEX checksum. Never trust a neighboring HEX.
    props = m7_performance.properties("arduino-cli")
    build.validate_build_properties(props)
    objcopy = build.resolve_compiler(props).with_name("arm-none-eabi-objcopy")
    health = rig.service_preflight(args.service)
    args.evidence_dir.mkdir(parents=True)
    hex_path = args.evidence_dir / "firmware.ino.hex"
    build.run_command(
        [str(objcopy), "-O", "ihex", "-R", ".eeprom", str(elf), str(hex_path)]
    )
    firmware = hex_path.read_bytes()
    source = (build.REPOSITORY_ROOT / "firmware/tests/rig_m7_benchmark.py").read_text()
    program = rig.make_program(
        source,
        {
            "M7_OPTIMIZATION": manifest["optimization"],
            "EXPECTED_HARDWARE_SERIAL": str(args.serial),
        },
    )
    (args.evidence_dir / "rig-program.py").write_text(program)
    (args.evidence_dir / "benchmark-manifest.json").write_bytes(manifest_bytes)
    (args.evidence_dir / "provenance.json").write_text(
        json.dumps(
            {
                "health": health,
                "service": args.service,
                "elf_sha256": build.sha256(elf),
                "hex_sha256": rig.digest(firmware),
                "manifest_sha256": rig.digest(manifest_bytes),
                "program_sha256": rig.digest(program.encode()),
                "optimization": manifest["optimization"],
                "hardware_serial": args.serial,
            },
            indent=2,
            sort_keys=True,
        )
        + "\n"
    )
    result = rig.submit_program(
        args.service,
        args.auth_file.read_text().strip(),
        firmware,
        program,
        args.evidence_dir,
        180,
    )
    summary = rig.classify_result(result, expected_cells=1)
    (args.evidence_dir / "summary.json").write_text(
        json.dumps(summary, indent=2, sort_keys=True) + "\n"
    )
    print(json.dumps(summary), flush=True)
    return 0 if summary["outcome"] == "PASS" else 1


if __name__ == "__main__":
    raise SystemExit(main())
