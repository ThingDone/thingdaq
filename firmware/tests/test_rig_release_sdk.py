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
    ("available", "watchdog", "free", "failure"),
    (
        (True, True, 28664, None),
        (True, False, 28664, "watchdog not enabled/validated"),
        (False, True, 0, "stack watermark unavailable"),
        (True, True, 0, "stack watermark exhausted"),
    ),
)
def test_health_retains_observation_before_acceptance(
    monkeypatch, capsys, available, watchdog, free, failure
):
    monkeypatch.setenv("AUX_INPUT_RUNTIME_HEALTH", "1")
    health = RuntimeHealth(
        stack_available=available,
        watchdog_enabled=watchdog,
        stack_total_bytes=34432 if available else 0,
        stack_min_free_bytes=free,
        stack_max_used_bytes=34432 - free if available else 0,
        reset_cause=1,
        watchdog_timeout_ms=4000 if watchdog else 0,
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
