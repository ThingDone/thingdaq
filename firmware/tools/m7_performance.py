#!/usr/bin/env python3
"""Measure opt-in firmware variants, retaining normal build gate rejections.

No upload. Outputs and compiler scratch stay under firmware/build/m7-performance.
Run --matrix for whole-firmware builds; --objects compares C/C++ Cortex-M7 code.
"""

from __future__ import annotations

import argparse
import contextlib
import dataclasses
import hashlib
import io
import json
import os
import shlex
import shutil
import subprocess
import sys
from pathlib import Path

import build_firmware as base

ROOT = base.REPOSITORY_ROOT
OUT = ROOT / "firmware/build/m7-performance"
EXPERIMENT = ROOT / "firmware/experiments/m7_performance"
OPTIONS = {"Os": "osstd", "O1": "o1std", "O2": "o2std", "O3": "o3std"}


def write_json(path: Path, value: object) -> None:
    path.write_text(json.dumps(value, indent=2, sort_keys=True) + "\n")


def properties(cli: str) -> dict[str, str]:
    return base.parse_build_properties(
        base.run_command(
            [
                cli,
                "compile",
                "--fqbn",
                base.FQBN,
                "--show-properties",
                str(base.SKETCH_DIRECTORY),
            ]
        ).stdout
    )


def objects(cli: str) -> None:
    """Compare machine code, not ELF metadata or host runtime, across languages."""
    props = properties(cli)
    base.validate_build_properties(props)
    cpp = base.resolve_compiler(props)
    cc = cpp.with_name("arm-none-eabi-gcc")
    objdump = cpp.with_name("arm-none-eabi-objdump")
    objcopy = cpp.with_name("arm-none-eabi-objcopy")
    nm = base.resolve_nm(cpp)
    identity = base.run_command([str(cc), "--version"]).stdout.splitlines()[0]
    if base.COMPILER_VERSION not in identity.split():
        raise base.BuildError(f"unexpected compiler: {identity}")
    destination = OUT / "objects"
    destination.mkdir(parents=True, exist_ok=True)
    rows = []
    for opt in OPTIONS:
        for placement in ("flash", "itcm"):
            for language in ("c", "c++"):
                name = f"{opt}-{placement}-{language.replace('+', 'p')}"
                obj = destination / f"{name}.o"
                section = ".fastrun" if placement == "itcm" else ".flashmem.gpio_pack_c"
                command = [
                    str(cc if language == "c" else cpp),
                    "-x",
                    language,
                    "-std=c11" if language == "c" else "-std=c++17",
                    f"-{opt}",
                    *shlex.split(props["build.flags.cpu"]),
                    "-Wall",
                    "-Wextra",
                    "-Werror",
                    "-D__IMXRT1062__",
                    "-DTHINGDAQ_EXPERIMENT_C_PACKER=1",
                    *(
                        ["-DTHINGDAQ_EXPERIMENT_PACKER_ITCM=1"]
                        if placement == "itcm"
                        else []
                    ),
                    "-c",
                    str(base.SKETCH_DIRECTORY / "src/gpio_pack_c.c"),
                    "-o",
                    str(obj),
                ]
                base.run_command(command)
                assembly = base.run_command([str(objdump), "-dr", str(obj)]).stdout
                (destination / f"{name}.asm").write_text(assembly)
                raw = destination / f"{name}.bin"
                base.run_command(
                    [
                        str(objcopy),
                        "-O",
                        "binary",
                        "--only-section",
                        section,
                        str(obj),
                        str(raw),
                    ]
                )
                symbols = base.parse_nm_symbols(
                    base.run_command([str(nm), "-S", str(obj)]).stdout
                )
                rows.append(
                    {
                        "optimization": opt,
                        "placement": placement,
                        "language": language,
                        "code_bytes": symbols["thingdaq_pack_dual_c"][1],
                        "machine_code_sha256": base.sha256(raw),
                        "command": command,
                    }
                )
    atomic = destination / "event_word.o"
    base.run_command(
        [
            str(cc),
            "-std=c11",
            "-O2",
            *shlex.split(props["build.flags.cpu"]),
            "-Wall",
            "-Wextra",
            "-Werror",
            "-c",
            str(EXPERIMENT / "event_word.c"),
            "-o",
            str(atomic),
        ]
    )
    disassembly = base.run_command([str(objdump), "-dr", str(atomic)]).stdout
    (destination / "event_word.asm").write_text(disassembly)
    undefined = base.run_command([str(nm), "-u", str(atomic)]).stdout.strip()
    if undefined or any(
        instruction not in disassembly for instruction in ("ldrex", "strex", "dmb")
    ):
        raise base.BuildError(
            "atomic code must inline exclusive accesses/barriers without runtime helpers"
        )
    if "cpsid" in disassembly or "primask" in disassembly:
        raise base.BuildError("atomic candidate unexpectedly masks global interrupts")
    write_json(
        destination / "results.json",
        {
            "compiler": identity,
            "rows": rows,
            "atomic_disassembly_verified": True,
            "source_sha256": base.sha256(base.SKETCH_DIRECTORY / "src/gpio_pack_c.c"),
            "event_source_sha256": base.sha256(EXPERIMENT / "event_word.c"),
            "timing": "not measured; code size and instruction inspection only",
        },
    )
    print(destination / "results.json")


def benchmark(cli: str, opt: str) -> None:
    """Build a separate four-kernel DWT sketch; never upload automatically."""
    directory = OUT / f"benchmark-{opt}"
    sketch = directory / "m7_performance"
    sketch.mkdir(parents=True, exist_ok=True)
    shutil.copyfile(EXPERIMENT / "m7_performance.ino", sketch / "m7_performance.ino")
    for name in ("event_word.c", "event_word.h"):
        shutil.copyfile(EXPERIMENT / name, sketch / name)
    for name in ("gpio_pack_c.c", "gpio_pack_c.h"):
        shutil.copyfile(
            base.SKETCH_DIRECTORY / "src" / name, sketch / name.replace(".c", "_body.h")
        )
    for language in ("c", "cpp"):
        for placement in ("flash", "itcm"):
            defines = [
                "#define THINGDAQ_EXPERIMENT_C_PACKER 1",
                f"#define thingdaq_pack_dual_c pack_{language}_{placement}",
            ]
            if placement == "itcm":
                defines.append("#define THINGDAQ_EXPERIMENT_PACKER_ITCM 1")
            (sketch / f"pack_{language}_{placement}.{language}").write_text(
                "\n".join([*defines, '#include "gpio_pack_c_body.h"', ""])
            )
    props = properties(cli)
    base.validate_build_properties(props)
    compiler = base.resolve_compiler(props)
    compiler_identity = base.run_command(
        [str(compiler), "--version"]
    ).stdout.splitlines()[0]
    if base.COMPILER_VERSION not in compiler_identity.split():
        raise base.BuildError(f"unexpected compiler: {compiler_identity}")
    command = [
        cli,
        "compile",
        "--fqbn",
        base.FQBN,
        "--clean",
        "--warnings",
        "all",
        "--build-path",
        str(directory / "compile"),
        "--build-property",
        f"build.flags.optimize=-{opt}",
        "--build-property",
        f"build.flags.defs={props['build.flags.defs']} -DTHINGDAQ_BENCH_OPT={opt}",
        "--output-dir",
        str(directory),
        str(sketch),
    ]
    result = base.run_command(command)
    (directory / "build.log").write_text(result.stdout + result.stderr)
    elf = directory / "m7_performance.ino.elf"
    symbols = base.parse_nm_symbols(
        base.run_command([str(base.resolve_nm(compiler)), "-S", str(elf)]).stdout
    )
    placements = {}
    for language in ("c", "cpp"):
        for placement in ("flash", "itcm"):
            name = f"pack_{language}_{placement}"
            address, size, _ = symbols[name]
            valid = (
                (0 < address < 0x80000)
                if placement == "itcm"
                else (base.PROGRAM_FLASH_START <= address < base.PROGRAM_FLASH_END)
            )
            if not valid:
                raise base.BuildError(f"{name} linked in wrong memory region")
            placements[name] = {"address": hex(address), "code_bytes": size}
    for name, start, end in (
        ("dtcm_primary", base.DTCM_START, base.DTCM_END),
        ("dtcm_auxiliary", base.DTCM_START, base.DTCM_END),
        ("ocram_primary", base.OCRAM_START, base.OCRAM_END),
        ("ocram_auxiliary", base.OCRAM_START, base.OCRAM_END),
        ("events", base.DTCM_START, base.DTCM_END),
    ):
        address, size, _ = symbols[name]
        if not start <= address < address + size <= end or address % 4:
            raise base.BuildError(
                f"{name} is not aligned in its expected memory region"
            )
        placements[name] = {"address": hex(address), "data_bytes": size}
    write_json(
        directory / "benchmark-manifest.json",
        {
            "command": command,
            "compiler": compiler_identity,
            "optimization": opt,
            "kernels": placements,
            "elf_sha256": base.sha256(elf),
            "hardware_timing": None,
            "sources": {
                file.name: base.sha256(file)
                for file in sorted(sketch.iterdir())
                if file.is_file()
            },
        },
    )
    print(directory / "benchmark-manifest.json")


def variant(cli: str, opt: str, kernel: str) -> bool:
    name = f"{opt}-{kernel}"
    directory = OUT / name
    directory.mkdir(parents=True, exist_ok=True)
    base.OUTPUT_DIRECTORY = directory
    base.FQBN = f"teensy:avr:teensy40:usb=serial,speed=450,opt={OPTIONS[opt]}"
    base.EXPECTED_BUILD_PROPERTIES = {
        **base.EXPECTED_BUILD_PROPERTIES,
        "build.flags.optimize": f"-{opt}",
    }
    original_identity = base.build_identity
    original_definitions = base.identity_definitions
    original_command = base.compile_command
    original_run = base.run_command
    builder_sha = base.sha256(Path(__file__))
    selection = f"m7-performance-v1:{opt}:{kernel}:{builder_sha}"

    def identity(environment=None):
        initial = original_identity(environment)
        digest = hashlib.sha256(f"{initial.source_id}:{selection}".encode()).hexdigest()
        return dataclasses.replace(
            initial, source_id=digest, build_id=f"thingdaq-{digest[:16]}"
        )

    def definitions(defs, selected):
        value = original_definitions(defs, selected)
        if opt != "O2":
            value = value.replace(
                "-DTHINGDAQ_OPTIMIZATION_O2STD=1",
                "-DTHINGDAQ_EXPERIMENT_OPTIMIZATION=1",
            )
        if kernel != "cpp-flash":
            value += " -DTHINGDAQ_EXPERIMENT_C_PACKER=1"
        if kernel == "c-itcm":
            value += " -DTHINGDAQ_EXPERIMENT_PACKER_ITCM=1"
        return value

    def command(*args):
        result = original_command(*args)
        # Arduino's core cache and compiler temporary files must remain local.
        result[2:2] = [
            "--build-path",
            str(directory / "compile"),
            "--build-property",
            f"build.flags.optimize=-{opt}",
        ]
        return result

    def run(command, **kwargs):
        # The core's "Smallest Code" menu also enables nano libc. Override the
        # optimization property in BOTH resolution and compilation to keep
        # libc constant across this experiment.
        command = list(command)
        if (
            len(command) > 1
            and command[1] == "compile"
            and not any(part.startswith("build.flags.optimize=") for part in command)
        ):
            command[2:2] = ["--build-property", f"build.flags.optimize=-{opt}"]
        return original_run(command, **kwargs)

    base.build_identity = identity
    base.identity_definitions = definitions
    base.compile_command = command
    base.run_command = run
    log = io.StringIO()
    report = {
        "variant": name,
        "optimization": opt,
        "kernel": kernel,
        "builder_sha256": builder_sha,
        "build_id": identity().build_id,
        "base_source_id": original_identity().source_id,
        "hardware_timing": None,
        "release_qualified": False,
    }
    # Remove only this variant's stale success manifest before measuring again.
    (directory / base.MANIFEST_NAME).unlink(missing_ok=True)
    try:
        with contextlib.redirect_stdout(log), contextlib.redirect_stderr(log):
            manifest_path = base.build(cli)
        manifest = json.loads(manifest_path.read_text())
        manifest["m7_experiment"] = {"selection": selection, "release_qualified": False}
        write_json(manifest_path, manifest)
        report["build_gates_passed"] = True
    except base.BuildError as error:
        report["build_gates_passed"] = False
        report["rejection"] = str(error)
        log.write(str(error) + "\n")
    (directory / "build.log").write_text(log.getvalue())
    try:
        report["memory_usage"] = base.parse_memory_usage(log.getvalue())
        compiler = base.resolve_compiler(properties(cli))
        elf = directory / "firmware.ino.elf"
        symbols = base.parse_nm_symbols(
            base.run_command(
                [str(base.resolve_nm(compiler)), "-S", "--demangle", str(elf)]
            ).stdout
        )
        report["packer_symbols"] = {
            name: {"address": hex(address), "code_bytes": size}
            for name, (address, size, _) in symbols.items()
            if name == "thingdaq_pack_dual_c" or "packDualBankBatch(" in name
        }
        report["elf_sha256"] = base.sha256(elf)
    except base.BuildError:
        pass
    write_json(directory / "result.json", report)
    print(json.dumps(report), flush=True)
    return bool(report["build_gates_passed"])


def main() -> int:
    parser = argparse.ArgumentParser(description=__doc__)
    mode = parser.add_mutually_exclusive_group(required=True)
    mode.add_argument("--objects", action="store_true")
    mode.add_argument("--benchmark", action="store_true")
    mode.add_argument("--matrix", action="store_true")
    mode.add_argument("--variant", action="store_true")
    parser.add_argument("--optimization", choices=OPTIONS, default="O2")
    parser.add_argument(
        "--kernel", choices=("cpp-flash", "c-flash", "c-itcm"), default="cpp-flash"
    )
    parser.add_argument("--arduino-cli", default="arduino-cli")
    args = parser.parse_args()
    OUT.mkdir(parents=True, exist_ok=True)
    (OUT / "tmp").mkdir(exist_ok=True)
    os.environ["TMPDIR"] = str(OUT / "tmp")
    os.environ["ARDUINO_BUILD_CACHE_PATH"] = str(OUT / "cache")
    if args.objects:
        objects(args.arduino_cli)
    elif args.benchmark:
        benchmark(args.arduino_cli, args.optimization)
    elif args.variant:
        return 0 if variant(args.arduino_cli, args.optimization, args.kernel) else 1
    else:
        rows = []
        for opt in OPTIONS:
            for kernel in ("cpp-flash", "c-flash", "c-itcm"):
                result_path = OUT / f"{opt}-{kernel}/result.json"
                result_path.unlink(missing_ok=True)
                completed = subprocess.run(
                    [
                        sys.executable,
                        __file__,
                        "--variant",
                        "--optimization",
                        opt,
                        "--kernel",
                        kernel,
                        "--arduino-cli",
                        args.arduino_cli,
                    ],
                    check=False,
                )
                row = json.loads(result_path.read_text())
                if completed.returncode != (0 if row["build_gates_passed"] else 1):
                    raise base.BuildError(
                        f"variant process failed unexpectedly: {opt}-{kernel}"
                    )
                rows.append(row)
        write_json(OUT / "matrix.json", rows)
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
