#!/usr/bin/env python3
"""Build isolated 600 MHz RLE kernels; production acquisition is not linked."""

from __future__ import annotations

import argparse
import shutil
from pathlib import Path

import build_firmware as base
import m7_performance as m7

EXPERIMENT = base.REPOSITORY_ROOT / "firmware/experiments/rle_performance"
VARIANTS = (
    [
        "baseline_O2",
        "encode_O0",
        "encode_O1",
        "encode_O3",
        "encode_Os",
        "unit_O3",
        "relaxed_O3",
    ]
    + [f"single_{opt}" for opt in ("O0", "O1", "O2", "O3", "Os")]
    + ["single_itcm_O2", "single_itcm_O3"]
)


def build(cli: str, lto: bool) -> Path:
    image = "O2-lto" if lto else "O2"
    directory = base.REPOSITORY_ROOT / "firmware/build/rle-performance" / image
    sketch = directory / "rle_performance"
    sketch.mkdir(parents=True, exist_ok=True)
    for p in EXPERIMENT.iterdir():
        if p.is_file():
            shutil.copy2(p, sketch / p.name)
    production = sketch / "production"
    production.mkdir(exist_ok=True)
    for p in (base.SKETCH_DIRECTORY / "src").rglob("*.h"):
        dest = production / p.relative_to(base.SKETCH_DIRECTORY / "src")
        dest.parent.mkdir(parents=True, exist_ok=True)
        shutil.copy2(p, dest)
    shutil.copy2(
        base.SKETCH_DIRECTORY / "src/protocol.cpp", production / "protocol_body.h"
    )
    (sketch / "protocol_support.cpp").write_text(
        '#include "production/protocol_body.h"\n'
    )
    original = (base.SKETCH_DIRECTORY / "src/rle_encoder.cpp").read_text()
    declarations = []
    for name in VARIANTS:
        declarations.append(
            f'extern "C" rle_bench::Result {name}(const std::uint8_t *, std::uint8_t *);'
        )
        if name.startswith("single"):
            placement = ".fastrun" if "itcm" in name else f".flashmem.{name}"
            text = f'''#define RLE_SINGLE_NAME {name}
#define RLE_SINGLE_ATTRIBUTES __attribute__((section("{placement}"), noinline, noipa, used, optimize("{name.split("_")[-1]}")))
#include "single_pass.h"
'''
        else:
            source = original
            if name.startswith("encode_"):
                tag = 'THINGDAQ_RLE_CODE(".flashmem.rle.encode")'
                assert source.count(tag) == 1
                source = source.replace(
                    tag, tag + f' __attribute__((optimize("{name.split("_")[-1]}")))'
                )
            if name == "relaxed_O3":
                assert source.count("noinline, noipa, used") == 1
                source = source.replace("noinline, noipa, used", "used")
            # A distinct namespace prevents cross-variant symbols being merged.
            (production / f"{name}_body.h").write_text(source)
            opt = "O3" if name in ("unit_O3", "relaxed_O3") else "O2"
            text = f'''#include "benchmark.h"
#define rle rle_{name}
#include "production/rle_encoder.h"
#pragma GCC push_options
#pragma GCC optimize ("{opt}")
#include "production/{name}_body.h"
#pragma GCC pop_options
#undef rle
extern "C" __attribute__((section(".flashmem.wrapper.{name}"), noinline, noipa, used, optimize("O2")))
rle_bench::Result {name}(const std::uint8_t *input, std::uint8_t *output) {{
  namespace codec = thingdaq::rle_{name};
  const thingdaq::protocol::ByteView decoded{{input, rle_bench::kInputBytes}};
  const auto selected = codec::sizeForAdaptiveSelection(decoded, {{2, rle_bench::kItems}}, 4095);
  if (!selected.ok()) return {{0, 1}};
  if (!selected.select_rle) return {{0, 0}};
  const auto result = codec::encode(decoded, selected.plan, {{output, rle_bench::kOutputLimit}});
  return {{static_cast<std::uint32_t>(result.bytes_written), result.ok() ? 0U : 2U}};
}}
'''
        (sketch / f"{name}.cpp").write_text(text)
    (sketch / "variants.h").write_text(
        "\n".join(
            [
                "#pragma once",
                '#include "benchmark.h"',
                f'#define RLE_BENCH_IMAGE "{image}"',
                *declarations,
                "const rle_bench::Variant variants[] = {",
                *[f'  {{"{name}", {name}}},' for name in VARIANTS],
                "};",
                "constexpr unsigned kVariantCount = sizeof(variants) / sizeof(variants[0]);",
                "",
            ]
        )
    )
    props = m7.properties(cli)
    base.validate_build_properties(props)
    compiler = base.resolve_compiler(props)
    identity = base.run_command([str(compiler), "--version"]).stdout.splitlines()[0]
    if base.COMPILER_VERSION not in identity.split():
        raise base.BuildError(identity)
    option = "o2lto" if lto else "o2std"
    command = [
        cli,
        "compile",
        "--fqbn",
        f"teensy:avr:teensy40:usb=serial,speed=600,opt={option}",
        "--clean",
        "--warnings",
        "all",
        "--build-path",
        str(directory / "compile"),
        "--output-dir",
        str(directory),
        str(sketch),
    ]
    result = base.run_command(command)
    (directory / "build.log").write_text(result.stdout + result.stderr)
    elf = directory / "rle_performance.ino.elf"
    nm = base.run_command([str(base.resolve_nm(compiler)), "-S", "-C", str(elf)]).stdout
    (directory / "symbols.txt").write_text(nm)
    symbols = base.parse_nm_symbols(nm)
    kernels = {}
    for name in VARIANTS:
        addr, size, _ = symbols[name]
        itcm = "itcm" in name
        if not (
            (0 < addr < 0x80000)
            if itcm
            else (base.PROGRAM_FLASH_START <= addr < base.PROGRAM_FLASH_END)
        ):
            raise base.BuildError(f"{name}: incorrect placement")
        members = {
            key: {"address": hex(a), "bytes": n}
            for key, (a, n, kind) in symbols.items()
            if kind.upper() == "T" and (key == name or f"::rle_{name}::" in key)
        }
        kernels[name] = {
            "address": hex(addr),
            "wrapper_or_kernel_bytes": size,
            "linked_code_bytes": sum(m["bytes"] for m in members.values()),
            "members": members,
        }
    for name, start, end in [
        ("dtcm_input", base.DTCM_START, base.DTCM_END),
        ("dtcm_output", base.DTCM_START, base.DTCM_END),
        ("ocram_input", base.OCRAM_START, base.OCRAM_END),
        ("ocram_output", base.OCRAM_START, base.OCRAM_END),
    ]:
        addr, size, _ = symbols[name]
        if not start <= addr < addr + size <= end or addr % 32 or size != 4096:
            raise base.BuildError(f"{name}: incorrect buffer placement")
    objdump = compiler.with_name("arm-none-eabi-objdump")
    (directory / "disassembly.txt").write_text(
        base.run_command([str(objdump), "-d", "-C", str(elf)]).stdout
    )
    m7.write_json(
        directory / "benchmark-manifest.json",
        {
            "kind": "rle",
            "source_commit": base.run_command(
                ["git", "rev-parse", "HEAD"]
            ).stdout.strip(),
            "source_dirty": bool(
                base.run_command(["git", "status", "--porcelain"]).stdout.strip()
            ),
            "optimization": image,
            "command": command,
            "compiler": identity,
            "cpu_hz": 600000000,
            "elf_sha256": base.sha256(elf),
            "kernels": kernels,
            "production_encoder_sha256": base.sha256(
                base.SKETCH_DIRECTORY / "src/rle_encoder.cpp"
            ),
            "builder_sha256": base.sha256(Path(__file__)),
            "sources": {
                str(p.relative_to(sketch)): base.sha256(p)
                for p in sorted(sketch.rglob("*"))
                if p.is_file()
            },
            "scope": "isolated codec selection+encoding; no acquisition/checksum/frame copy/USB in timed interval",
        },
    )
    return directory


def main() -> None:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--lto", action="store_true")
    parser.add_argument("--arduino-cli", default="arduino-cli")
    args = parser.parse_args()
    print(build(args.arduino_cli, args.lto))


if __name__ == "__main__":
    main()
