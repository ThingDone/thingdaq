"""Focused fake-clock and offline-boundary tests for the baseline prototype."""

from __future__ import annotations

import ast
import io
import json
import socket
import subprocess
import tempfile
import unittest
from pathlib import Path
from typing import Any
from unittest.mock import patch

import serial.tools.list_ports
from thingdone_daq import (
    Frame,
    FrameFlag,
    FrameKind,
    InMemoryTransport,
    SimulatedDevice,
    ThingDAQ,
    decode_frame,
    encode_frame,
)
from thingdone_daq._generated import protocol_constants as constants

from firmware.tools import baseline_prototype as baseline
from firmware.tools import experiment_evidence

ROOT = Path(__file__).resolve().parents[2]
BASELINE_PATH = ROOT / "firmware/tools/baseline_prototype.py"
PROTOCOL_PATH = ROOT / "protocol/protocol-v1.json"
MATRIX_PATH = ROOT / "experiments/experiment-matrix.json"


class FakeClock:
    """Advance deterministically at every observation and requested sleep."""

    def __init__(self) -> None:
        self.value = 100.0

    def __call__(self) -> float:
        observed = self.value
        self.value += 0.001
        return observed

    def sleep(self, seconds: float) -> None:
        self.value += seconds


class GapDevice(SimulatedDevice):
    """Replace ADC sequence one with a declared sequence-two overrun."""

    def __init__(self) -> None:
        super().__init__()
        self.injected = False

    def next_data_frame(self) -> bytes | None:
        wire = super().next_data_frame()
        if wire is None or self.injected:
            return wire
        frame = decode_frame(wire)
        if frame.header.kind is not FrameKind.ADC_DATA or frame.header.sequence != 1:
            return wire
        self.injected = True
        self._adc_items_dropped += constants.ADC_PAIRS_PER_FRAME
        self._adc_sequence += 1
        self._adc_first_ticks += constants.FRAME_COVERAGE_TICKS
        return encode_frame(
            frame.header.kind,
            frame.payload,
            flags=frame.header.flags | FrameFlag.GAP_BEFORE | FrameFlag.OVERRUN_BEFORE,
            checksum_algorithm=frame.header.checksum_algorithm,
            run_id=frame.header.run_id,
            sequence=frame.header.sequence + 1,
            first_sample_ticks=(
                frame.header.first_sample_ticks + constants.FRAME_COVERAGE_TICKS
            ),
            item_count=frame.header.item_count,
        )


class ParserCorruptDevice(SimulatedDevice):
    """Corrupt one complete data frame after encoding its checksum."""

    def __init__(self) -> None:
        super().__init__()
        self.injected = False

    def next_data_frame(self) -> bytes | None:
        wire = super().next_data_frame()
        if wire is None or self.injected:
            return wire
        self.injected = True
        corrupted = bytearray(wire)
        corrupted[-1] ^= 0x01
        return bytes(corrupted)


class CounterFaultDevice(SimulatedDevice):
    """Record one firmware transport error during the streaming window."""

    def __init__(self) -> None:
        super().__init__()
        self.injected = False

    def next_data_frame(self) -> bytes | None:
        wire = super().next_data_frame()
        if wire is not None and not self.injected:
            self.injected = True
            self.record_transport_error()
        return wire


class CleanupFaultDevice(SimulatedDevice):
    """Reject STOP so cleanup cannot be mistaken for an accepted result."""

    def _handle_stop(self, request: Frame) -> bytes:
        return self._typed_error(request, constants.ErrorCode.INTERNAL_ERROR)


def _simulated_opener(device_type: type[SimulatedDevice]) -> Any:
    def open_simulated(**kwargs: Any) -> ThingDAQ:
        transport = InMemoryTransport(
            device_type(),
            read_chunk_size=kwargs.get("read_chunk_size"),
            write_chunk_size=kwargs.get("write_chunk_size"),
            stream_interval=kwargs.get("stream_interval"),
        )
        return ThingDAQ.open(
            transport,
            strict=bool(kwargs.get("strict", False)),
            read_size=int(kwargs.get("read_size", 64 * 1024)),
            max_buffered_blocks=int(
                kwargs.get("max_buffered_blocks", baseline.DEFAULT_MAX_QUEUED_BLOCKS)
            ),
            max_buffered_events=int(kwargs.get("max_buffered_events", 32)),
            max_pending_requests=int(kwargs.get("max_pending_requests", 32)),
        )

    return open_simulated


def _git_output(*arguments: str) -> str:
    return subprocess.check_output(
        ["git", "-C", str(ROOT), *arguments],
        text=True,
    ).strip()


def _artifact(kind: str, path: Path) -> dict[str, Any]:
    return {
        "kind": kind,
        "path": path.relative_to(ROOT).as_posix(),
        "size_bytes": path.stat().st_size,
        "sha256": experiment_evidence.sha256_file(path),
    }


def _fixed_build_and_identity(
    matrix: experiment_evidence.ExperimentMatrix,
) -> tuple[baseline.BuildEvidence, dict[str, Any]]:
    source_id = baseline.build_firmware.source_fingerprint(
        baseline.build_firmware.collect_source_files()
    )
    source_commit = _git_output("rev-parse", "HEAD")
    source_tree = _git_output("rev-parse", "HEAD^{tree}")
    protocol = json.loads(PROTOCOL_PATH.read_text(encoding="utf-8"))
    build = baseline.BuildEvidence(
        manifest_path=MATRIX_PATH,
        manifest={
            "source": {
                "source_id": source_id,
                "build_id": f"thingdaq-{source_id[:16]}",
                "git_commit": source_commit,
            }
        },
        artifacts=(
            _artifact(
                "firmware-map",
                ROOT / "doc/architecture/firmware-resource-map.md",
            ),
        ),
        toolchains=(
            experiment_evidence.toolchain_record(
                "test-build",
                "1",
                "Pinned offline test build",
            ),
        ),
        resource_map={"test_allocation": {"bytes": 1}},
        flash_used_bytes=1_000,
        flash_headroom_bytes=2_000,
        ram1_used_bytes=3_000,
        ram1_headroom_bytes=4_000,
        ram2_used_bytes=5_000,
        ram2_headroom_bytes=6_000,
        cpu_clock_hz=600_000_000,
    )
    identity = {
        "repository": matrix.report_contract["identity"]["repository"],
        "branch": "main",
        "baseline_branch": matrix.data["branches"]["baseline"],
        "baseline_commit": source_commit,
        "source_commit": source_commit,
        "source_tree": source_tree,
        "source_clean": True,
        "source_id": source_id,
        "protocol_contract_path": "protocol/protocol-v1.json",
        "protocol_version": protocol["protocol_version"],
        "protocol_sha256": experiment_evidence.sha256_file(PROTOCOL_PATH),
        "toolchains": [*build.toolchains],
    }
    return build, identity


class BaselineCaptureTests(unittest.TestCase):
    def test_fake_clock_capture_accepts_arbitrary_stream_boundaries_and_conserves(
        self,
    ) -> None:
        for chunk_size in (1, 7, 47, constants.DATA_FRAME_BYTES):
            with self.subTest(chunk_size=chunk_size):
                clock = FakeClock()
                capture = baseline.run_capture(
                    frame_budget=6,
                    parser_chunk_size=chunk_size,
                    status_frame_interval=2,
                    clock=clock,
                    sleeper=clock.sleep,
                )

                self.assertEqual(3, capture.metrics.adc.frame_count)
                self.assertEqual(3, capture.metrics.gpio.frame_count)
                self.assertEqual(
                    3 * constants.ADC_PAIRS_PER_FRAME,
                    capture.metrics.adc.item_count,
                )
                self.assertEqual(
                    3 * constants.GPIO_SAMPLES_PER_FRAME,
                    capture.metrics.gpio.item_count,
                )
                self.assertEqual(
                    3 * constants.ADC_DATA_PAYLOAD_SIZE,
                    capture.metrics.adc.payload_bytes,
                )
                self.assertEqual(
                    3 * constants.GPIO_DATA_PAYLOAD_SIZE,
                    capture.metrics.gpio.payload_bytes,
                )
                self.assertEqual(
                    6 * constants.DATA_FRAME_BYTES,
                    capture.metrics.framed_bytes,
                )
                self.assertEqual(
                    3 * constants.FRAME_COVERAGE_TICKS / constants.TIMESTAMP_HZ,
                    capture.logical_duration_seconds,
                )
                self.assertTrue(capture.metrics.reconciliation.ok)
                for equation in baseline._conservation(capture).values():
                    self.assertEqual(equation["left"], equation["right"])
                self.assertFalse(any(capture.final_gauges.values()))
                self.assertTrue(capture.transport_closed)

    def test_gap_parser_counter_and_cleanup_faults_never_write_a_report(self) -> None:
        fault_devices = (
            ("gap", GapDevice),
            ("parser", ParserCorruptDevice),
            ("counter", CounterFaultDevice),
            ("cleanup", CleanupFaultDevice),
        )
        for name, device_type in fault_devices:
            with self.subTest(name=name), tempfile.TemporaryDirectory() as directory:
                output_directory = Path(directory)
                clock = FakeClock()
                with (
                    patch.object(
                        baseline.ThingDAQ,
                        "simulated",
                        side_effect=_simulated_opener(device_type),
                    ),
                    self.assertRaisesRegex(
                        baseline.BaselinePrototypeError,
                        "strict simulator capture failed",
                    ),
                ):
                    baseline.run_baseline(
                        output_directory=output_directory,
                        frame_budget=6,
                        parser_chunk_size=17,
                        status_frame_interval=1,
                        created="2026-09-01",
                        clock=clock,
                        sleeper=clock.sleep,
                        output=io.StringIO(),
                    )
                self.assertFalse((output_directory / "baseline.json").exists())
                self.assertFalse((output_directory / "baseline.md").exists())


class BaselineOfflineBoundaryTests(unittest.TestCase):
    def test_source_and_cli_have_no_serial_network_upload_or_prompt_surface(
        self,
    ) -> None:
        source = BASELINE_PATH.read_text(encoding="utf-8")
        tree = ast.parse(source)
        imported_roots: set[str] = set()
        called_names: set[str] = set()
        called_attributes: set[str] = set()
        for node in ast.walk(tree):
            if isinstance(node, ast.Import):
                imported_roots.update(
                    alias.name.split(".", 1)[0] for alias in node.names
                )
            elif isinstance(node, ast.ImportFrom) and node.module is not None:
                imported_roots.add(node.module.split(".", 1)[0])
            elif isinstance(node, ast.Call):
                if isinstance(node.func, ast.Name):
                    called_names.add(node.func.id)
                elif isinstance(node.func, ast.Attribute):
                    called_attributes.add(node.func.attr)

        self.assertTrue(
            imported_roots.isdisjoint(
                {"ftplib", "http", "requests", "serial", "socket", "urllib"}
            )
        )
        self.assertNotIn("input", called_names)
        self.assertNotIn("getpass", called_names)
        self.assertTrue(
            called_attributes.isdisjoint(
                {"comports", "open_serial", "upload", "urlopen"}
            )
        )
        arguments = vars(baseline.parse_args([]))
        forbidden_options = {
            "api_key",
            "credential",
            "password",
            "port",
            "rig",
            "serial_port",
            "token",
            "upload",
        }
        self.assertTrue(forbidden_options.isdisjoint(arguments))

    def test_default_command_clock_produces_byte_identical_reports(self) -> None:
        matrix = experiment_evidence.load_experiment_matrix(MATRIX_PATH)
        build, identity = _fixed_build_and_identity(matrix)

        with tempfile.TemporaryDirectory() as directory:
            parent = Path(directory)
            first_directory = parent / "first"
            second_directory = parent / "second"
            with (
                patch.object(
                    baseline,
                    "build_or_load_manifest",
                    return_value=build,
                ),
                patch.object(
                    baseline.experiment_evidence,
                    "capture_identity",
                    return_value=identity,
                ),
            ):
                first = baseline.run_baseline(
                    output_directory=first_directory,
                    frame_budget=8,
                    parser_chunk_size=31,
                    status_frame_interval=2,
                    created="2026-09-01",
                    baseline_commit=identity["baseline_commit"],
                    output=io.StringIO(),
                )
                second = baseline.run_baseline(
                    output_directory=second_directory,
                    frame_budget=8,
                    parser_chunk_size=31,
                    status_frame_interval=2,
                    created="2026-09-01",
                    baseline_commit=identity["baseline_commit"],
                    output=io.StringIO(),
                )

            self.assertEqual(first, second)
            self.assertEqual(
                (first_directory / "baseline.json").read_bytes(),
                (second_directory / "baseline.json").read_bytes(),
            )
            self.assertEqual(
                (first_directory / "baseline.md").read_bytes(),
                (second_directory / "baseline.md").read_bytes(),
            )
            simulator_record = next(
                item for item in first["evidence"] if item["id"] == "simulator-capture"
            )
            self.assertEqual(
                baseline.DETERMINISTIC_CLOCK_BASIS,
                simulator_record["command_latency"]["clock_basis"],
            )

    def test_full_fake_clock_baseline_is_offline_pass_and_byte_identical(
        self,
    ) -> None:
        matrix = experiment_evidence.load_experiment_matrix(MATRIX_PATH)
        build, identity = _fixed_build_and_identity(matrix)
        real_subprocess_run = subprocess.run

        def guarded_subprocess_run(*args: Any, **kwargs: Any) -> Any:
            command = args[0] if args else kwargs.get("args", [])
            command_text = " ".join(str(part) for part in command).casefold()
            self.assertNotIn("upload", command_text)
            self.assertNotIn("curl", command_text)
            self.assertNotIn("wget", command_text)
            return real_subprocess_run(*args, **kwargs)

        with tempfile.TemporaryDirectory() as directory:
            parent = Path(directory)
            first_directory = parent / "first"
            second_directory = parent / "second"
            with (
                patch.object(
                    baseline,
                    "build_or_load_manifest",
                    return_value=build,
                ),
                patch.object(
                    baseline.experiment_evidence,
                    "capture_identity",
                    return_value=identity,
                ),
                patch(
                    "builtins.input", side_effect=AssertionError("prompted")
                ) as prompt,
                patch.object(
                    serial.tools.list_ports,
                    "comports",
                    side_effect=AssertionError("enumerated serial ports"),
                ) as ports,
                patch.object(
                    socket,
                    "create_connection",
                    side_effect=AssertionError("opened network connection"),
                ) as connection,
                patch.object(
                    socket,
                    "socket",
                    side_effect=AssertionError("created network socket"),
                ) as network_socket,
                patch.object(
                    subprocess,
                    "run",
                    side_effect=guarded_subprocess_run,
                ),
            ):
                first_clock = FakeClock()
                first = baseline.run_baseline(
                    output_directory=first_directory,
                    frame_budget=8,
                    parser_chunk_size=31,
                    status_frame_interval=2,
                    created="2026-09-01",
                    baseline_commit=identity["baseline_commit"],
                    clock=first_clock,
                    sleeper=first_clock.sleep,
                    output=io.StringIO(),
                )
                second_clock = FakeClock()
                second = baseline.run_baseline(
                    output_directory=second_directory,
                    frame_budget=8,
                    parser_chunk_size=31,
                    status_frame_interval=2,
                    created="2026-09-01",
                    baseline_commit=identity["baseline_commit"],
                    clock=second_clock,
                    sleeper=second_clock.sleep,
                    output=io.StringIO(),
                )

            prompt.assert_not_called()
            ports.assert_not_called()
            connection.assert_not_called()
            network_socket.assert_not_called()
            self.assertEqual("PASS", first["result"])
            self.assertEqual(first, second)
            self.assertEqual(
                (first_directory / "baseline.json").read_bytes(),
                (second_directory / "baseline.json").read_bytes(),
            )
            self.assertEqual(
                (first_directory / "baseline.md").read_bytes(),
                (second_directory / "baseline.md").read_bytes(),
            )

            metrics = {item["name"]: item["value"] for item in first["metrics"]}
            self.assertEqual(
                4 * constants.ADC_PAIRS_PER_FRAME,
                metrics["adc_pairs_observed"],
            )
            self.assertEqual(
                4 * constants.GPIO_SAMPLES_PER_FRAME,
                metrics["gpio_samples_observed"],
            )
            conservation = next(
                item
                for item in first["acceptance"]
                if item["id"] == "counter_conservation"
            )
            self.assertEqual("PASS", conservation["state"])
            self.assertTrue(
                all(
                    equation["left"] == equation["right"]
                    for equation in conservation["observed"].values()
                )
            )
            simulator_record = next(
                item for item in first["evidence"] if item["id"] == "simulator-capture"
            )
            reader_counters = simulator_record["counter_snapshot"]["host_reader"]
            self.assertNotIn("read_calls", reader_counters)
            self.assertNotIn("readinto_calls", reader_counters)
            self.assertEqual(
                8,
                reader_counters["adc_frames_received"]
                + reader_counters["gpio_frames_received"],
            )
            for record in first["evidence"]:
                self.assertEqual(
                    {
                        "network": False,
                        "serial_hardware": False,
                        "firmware_upload": False,
                        "user_input": False,
                    },
                    {
                        name: record["command"][name]
                        for name in (
                            "network",
                            "serial_hardware",
                            "firmware_upload",
                            "user_input",
                        )
                    },
                )


if __name__ == "__main__":
    unittest.main()
