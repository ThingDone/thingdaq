"""Reject incomplete or misleading hardware timing evidence."""

import importlib.util
from pathlib import Path

import pytest

SPEC = importlib.util.spec_from_file_location(
    "m7_collector", Path(__file__).with_name("rig_m7_benchmark.py")
)
collector = importlib.util.module_from_spec(SPEC)
SPEC.loader.exec_module(collector)


def transcript():
    lines = [
        "cpu_hz=450000000,opt=O2,warm_cache=1,interrupts_enabled=1,trials=101",
        "operation,data_region,units,min_cycles,median_cycles,max_cycles,digest",
    ]
    for operation in collector.OPERATIONS:
        for region in ("dtcm", "ocram"):
            lines.append(f"{operation},{region},2024,100,110,120,1784290555")
    for operation in ("atomic_publish_take", "primask_publish_take"):
        lines.append(f"{operation},dtcm,256,100,110,120,256")
    return [*lines, "done"]


def test_complete_transcript_and_independent_digest():
    assert collector.expected_digest() == 1784290555
    assert len(collector.parse_transcript(transcript(), "O2")) == 10


@pytest.mark.parametrize(
    "mutation",
    [
        "missing",
        "duplicate",
        "wrong_opt",
        "corruption",
        "event_total",
        "bad_cycles",
        "overflow_cycles",
        "bad_count",
        "missing_done",
        "firmware_error",
    ],
)
def test_invalid_evidence_is_rejected(mutation):
    lines = transcript()
    if mutation == "missing":
        lines.pop(2)
    elif mutation == "duplicate":
        lines[3] = lines[2]
    elif mutation == "wrong_opt":
        lines[0] = lines[0].replace("O2", "O3")
    elif mutation == "corruption":
        lines[2] = lines[2].replace("1784290555", "1784290554")
    elif mutation == "event_total":
        lines[-2] = lines[-2][:-3] + "255"
    elif mutation == "bad_cycles":
        lines[2] = lines[2].replace("100,110", "111,110")
    elif mutation == "overflow_cycles":
        lines[2] = lines[2].replace("120,", "4294967296,")
    elif mutation == "bad_count":
        lines[2] = lines[2].replace("2024,", "2023,")
    elif mutation == "missing_done":
        lines.pop()
    else:
        lines[3] = "ERROR: kernel output mismatch"
    with pytest.raises(ValueError):
        collector.parse_transcript(lines, "O2")
