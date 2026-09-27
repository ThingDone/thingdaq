"""Keep failed health observations even when acquisition preflight stops."""

import importlib.util
from pathlib import Path
from types import SimpleNamespace

import pytest
from thingdone_daq.protocol_v2 import RuntimeHealth

SPEC = importlib.util.spec_from_file_location(
    "rig_release_sdk", Path(__file__).with_name("rig_release_sdk.py")
)
rig = importlib.util.module_from_spec(SPEC)
SPEC.loader.exec_module(rig)


def test_health_sampling_is_opt_in(monkeypatch):
    monkeypatch.delenv("AUX_INPUT_RUNTIME_HEALTH", raising=False)
    evidence = {}
    rig.sample_health(None, evidence, "idle")
    assert evidence == {}


@pytest.mark.parametrize(
    ("available", "watchdog", "timeout", "free", "failure"),
    (
        (True, False, 0, 28664, None),
        (True, True, 4000, 28664, "watchdog unexpectedly enabled"),
        (True, False, 4000, 28664, "disabled watchdog has timeout"),
        (False, False, 0, 0, "stack watermark unavailable"),
        (True, False, 0, 0, "stack watermark exhausted"),
    ),
)
def test_health_retains_observation_before_acceptance(
    monkeypatch, capsys, available, watchdog, timeout, free, failure
):
    monkeypatch.setenv("AUX_INPUT_RUNTIME_HEALTH", "1")
    health = RuntimeHealth(
        stack_available=available,
        watchdog_enabled=watchdog,
        stack_total_bytes=34432 if available else 0,
        stack_min_free_bytes=free,
        stack_max_used_bytes=34432 - free if available else 0,
        reset_cause=1,
        watchdog_timeout_ms=timeout,
    )
    daq = SimpleNamespace(get_runtime_health=lambda: health)
    evidence = {}
    if failure:
        with pytest.raises(AssertionError, match=failure):
            rig.sample_health(daq, evidence, "idle")
    else:
        rig.sample_health(daq, evidence, "idle")
    assert evidence["runtime_health"][0]["watchdog_enabled"] == watchdog
    assert evidence["runtime_health"][0]["stack_min_free_bytes"] == free
    assert evidence["runtime_health"][0]["phase"] == "idle"
    assert capsys.readouterr().out.startswith("EVENT ")


def test_sdk_case_selection_preserves_order_and_repetition(monkeypatch):
    monkeypatch.setenv("AUX_INPUT_SDK_CASES", "combined16,combined8,combined16")
    assert [row[0] for row in rig.selected_cases()] == [
        "combined16",
        "combined8",
        "combined16",
    ]


@pytest.mark.parametrize("selection", ["", "typo", "combined16,"])
def test_sdk_case_selection_rejects_unknown_cells(monkeypatch, selection):
    monkeypatch.setenv("AUX_INPUT_SDK_CASES", selection)
    with pytest.raises(ValueError, match="unknown SDK cases"):
        rig.selected_cases()


def test_sdk_default_case_selection(monkeypatch):
    monkeypatch.delenv("AUX_INPUT_SDK_CASES", raising=False)
    assert [row[0] for row in rig.selected_cases()] == list(rig.SDK_CASES)
