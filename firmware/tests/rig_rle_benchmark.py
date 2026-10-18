"""Independent RLE timing transcript oracle; reused serial collector, no capture."""

from __future__ import annotations

import struct

VARIANTS = (
    "baseline_O2",
    "encode_O0",
    "encode_O1",
    "encode_O3",
    "encode_Os",
    "unit_O3",
    "relaxed_O3",
    "single_O0",
    "single_O1",
    "single_O2",
    "single_O3",
    "single_Os",
    "single_itcm_O2",
    "single_itcm_O3",
    "span_O2",
    "span_O3",
    "span_Os",
    "hybrid_Os",
    "hybrid_O3",
)
PATTERNS = (
    "constant",
    "runs32",
    "runs3",
    "runs2",
    "alternating",
    "random",
    "pulses",
    "last_change",
)
FIELDS = (
    "items",
    "min_cycles",
    "median_cycles",
    "max_cycles",
    "encoded_bytes",
    "encoded_digest",
    "input_digest",
)


def fnv(data: bytes) -> int:
    result = 2166136261
    for byte in data:
        result = ((result ^ byte) * 16777619) & 0xFFFFFFFF
    return result


def corpus(pattern: str) -> bytes:
    values = []
    state = 0x12345678
    for i in range(2024):
        state = (state * 1664525 + 1013904223) & 0xFFFFFFFF
        value = {
            "constant": 0x5AA5,
            "runs32": 0xFFFF if (i // 32) & 1 else 0,
            "runs3": 0xAAAA if (i // 3) & 1 else 0x5555,
            "runs2": 0xFFFF if (i // 2) & 1 else 0,
            "alternating": 0xFFFF if i & 1 else 0,
            "random": state >> 16,
            "pulses": int(i % 127 == 0),
            "last_change": int(i == 2023),
        }[pattern]
        values.append(value)
    return struct.pack("<2024H", *values)


def encode_reference(source: bytes) -> bytes:
    values = struct.unpack("<2024H", source)
    records = []
    start = 0
    for end in range(1, len(values) + 1):
        if end == len(values) or values[end] != values[start]:
            records.append(struct.pack("<HH", end - start, values[start]))
            start = end
    encoded = b"".join(records)
    if len(encoded) > 4044:
        encoded = b""
    return encoded


def expected(pattern: str) -> dict:
    source = corpus(pattern)
    encoded = encode_reference(source)
    return {
        "encoded_bytes": len(encoded),
        "encoded_digest": fnv(encoded),
        "input_digest": fnv(source + bytes([0xA5]) * 48),
    }


def parse_transcript(lines: list[str], optimization: str) -> list[dict]:
    banner = f"cpu_hz=600000000,opt={optimization},warm_cache=1,interrupts_enabled=1,trials=31,acquisition=0"
    header = "variant,pattern,region," + ",".join(FIELDS)
    wanted = {(v, p, r) for v in VARIANTS for p in PATTERNS for r in ("dtcm", "ocram")}
    if (
        len(lines) != len(wanted) + 3
        or lines[0] != banner
        or lines[1] != header
        or lines[-1] != "done"
    ):
        raise ValueError("incomplete or mismatched benchmark transcript")
    references = {p: expected(p) for p in PATTERNS}
    rows = []
    for line in lines[2:-1]:
        parts = line.split(",")
        if len(parts) != 10 or tuple(parts[:3]) not in wanted:
            raise ValueError("duplicate or unknown timing case")
        wanted.remove(tuple(parts[:3]))
        row = dict(zip(FIELDS, map(int, parts[3:]), strict=True))
        if (
            row["items"] != 2024
            or not 0
            < row["min_cycles"]
            <= row["median_cycles"]
            <= row["max_cycles"]
            < 2**32
        ):
            raise ValueError("invalid sample count or cycle ordering")
        if any(row[k] != value for k, value in references[parts[1]].items()):
            raise ValueError(
                "encoder output or input disagrees with independent oracle"
            )
        rows.append(dict(variant=parts[0], pattern=parts[1], region=parts[2], **row))
    return rows


def main() -> int:
    from rig_m7_benchmark import main as collect

    return collect(parse=parse_transcript, validator="rle-dwt", pass_timeout=60)


if __name__ == "__main__":
    raise SystemExit(main())
