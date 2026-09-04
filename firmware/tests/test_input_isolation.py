"""Offline coverage for the cold-boot experiment submission wrapper."""

import importlib.util
import sys
from pathlib import Path

import pytest

SPEC = importlib.util.spec_from_file_location(
    "input_isolation", Path(__file__).parents[1] / "tools/run_input_isolation.py"
)
isolation = importlib.util.module_from_spec(SPEC)
SPEC.loader.exec_module(isolation)


def test_program_preserves_future_imports_and_registers_dataclasses(monkeypatch):
    source = '''from __future__ import annotations
from dataclasses import dataclass
import os
@dataclass
class Case:
    width: int = 8
def main():
    assert Case().width == 8
    assert os.environ["AUX_INPUT_RUN_DIAGNOSTIC"] == "0"
    return 7
if __name__ == "__main__":
    raise AssertionError("must call main only once")
'''
    monkeypatch.setenv("AUX_INPUT_RUN_DIAGNOSTIC", "1")
    try:
        with pytest.raises(SystemExit) as stopped:
            exec(isolation.make_program(source, {"AUX_INPUT_RUN_DIAGNOSTIC": "0"}), {})
        assert stopped.value.code == 7
    finally:
        sys.modules.pop("input_isolation_rig", None)


def test_digest_is_sha256():
    assert isolation.digest(b"abc") == "ba7816bf8f01cfea414140de5dae2223b00361a396177a9cb410ff61f20015ad"
