"""Demonstrate preloaded auxiliary output entirely in the simulator.

This example cannot select hardware. Every printed timing value and optional
artifact is deterministic simulated evidence, not a physical timing claim.
"""

from __future__ import annotations

import argparse
import sys
from collections.abc import Mapping, Sequence
from pathlib import Path
from typing import Any

from thingdaq import (
    ADCBlock,
    DeviceState,
    DigitalOutputProgram,
    GPIOBlock,
    InMemoryTransport,
    OutputBankMode,
    OutputError,
    OutputState,
    SimulatedDevice,
    SimulatedOutputSample,
    SimulatedOutputTransition,
    StreamMask,
    ThingDAQ,
)
from thingdaq._generated import protocol_constants as v1
from thingdaq._generated import protocol_v2_constants as v2

REPOSITORY_ROOT = Path(__file__).resolve().parents[2]
MATRIX_PATH = REPOSITORY_ROOT / "experiments/experiment-matrix.json"
PROTOCOL_V2_PATH = REPOSITORY_ROOT / "protocol/protocol-v2.json"
SCHEMA_VERSION = 1
ARTIFACT_KIND = "thingdaq-aux-output-simulator-demonstration"
CREATED = "2026-09-04"


class DemonstrationError(RuntimeError):
    """The deterministic simulator did not meet the demonstration contract."""


def _require(condition: bool, message: str) -> None:
    if not condition:
        raise DemonstrationError(message)


def _hex_mask(value: int | None) -> str:
    return "high-impedance" if value is None else f"0x{value:02x}"


def _program_record(program: DigitalOutputProgram) -> dict[str, Any]:
    return {
        "segments": [
            {
                "duration_samples": segment.duration_samples,
                "logical_state_mask": segment.logical_state_mask,
            }
            for segment in program.segments
        ],
        "repeat_count": program.repeat_count,
        "idle_state_mask": program.idle_state_mask,
        "duration_samples_per_play": program.duration_samples,
        "checksum_adler32": program.checksum,
    }


def _transition_record(event: SimulatedOutputTransition) -> dict[str, Any]:
    return {
        "tick": event.tick,
        "generation": event.generation,
        "run_id": event.run_id,
        "event": event.event.value,
        "state_mask": event.state_mask,
        "bank_mode": event.bank_mode.name,
        "output_state": event.output_state.name,
        "completed_repeats": event.completed_repeats,
        "segment_index": event.segment_index,
    }


def _sample_record(sample: SimulatedOutputSample) -> dict[str, Any]:
    return {
        "tick": sample.tick,
        "generation": sample.generation,
        "run_id": sample.run_id,
        "state_mask": sample.state_mask,
        "bank_mode": sample.bank_mode.name,
        "output_state": sample.output_state.name,
    }


def _combined_acquisition(daq: ThingDAQ, run_id: int) -> list[dict[str, Any]]:
    received = [daq.read_block(timeout=0.5), daq.read_block(timeout=0.5)]
    if not all(isinstance(block, (ADCBlock, GPIOBlock)) for block in received):
        raise DemonstrationError(
            "combined acquisition returned a loss event instead of data"
        )
    blocks = [block for block in received if isinstance(block, (ADCBlock, GPIOBlock))]
    _require(
        {type(block) for block in blocks} == {ADCBlock, GPIOBlock},
        "combined acquisition did not return one ADC and one GPIO block",
    )
    _require(
        all(block.run_id == run_id for block in blocks),
        "combined acquisition block run ID did not match START",
    )
    return [
        {
            "stream": "ADC" if isinstance(block, ADCBlock) else "GPIO",
            "run_id": block.run_id,
            "sequence": block.sequence,
            "first_sample_tick": block.first_sample_ticks,
            "item_count": block.item_count,
        }
        for block in blocks
    ]


def _print_acquisition(label: str, blocks: list[dict[str, Any]]) -> None:
    details = ",".join(
        f"{block['stream']}@{block['first_sample_tick']}:{block['item_count']}"
        for block in blocks
    )
    print(f"SIMULATED {label} combined_acquisition={details}")


def _print_transitions(
    label: str, transitions: Sequence[SimulatedOutputTransition]
) -> None:
    for event in transitions:
        print(
            f"SIMULATED {label} transition tick={event.tick} "
            f"event={event.event.value} state={_hex_mask(event.state_mask)} "
            f"repeat={event.completed_repeats} segment={event.segment_index}"
        )


def _print_samples(label: str, samples: Sequence[SimulatedOutputSample]) -> None:
    rendered = ",".join(
        f"{sample.tick}:{_hex_mask(sample.state_mask)}" for sample in samples
    )
    print(f"SIMULATED {label} sampled_states={rendered}")


def _device(daq: ThingDAQ) -> SimulatedDevice:
    transport = daq.transport
    if not isinstance(transport, InMemoryTransport):
        raise DemonstrationError(
            "output demonstration requires the in-memory simulator transport"
        )
    return transport.device


def _finite_demonstration() -> dict[str, Any]:
    program = DigitalOutputProgram.finite(
        [(2, 0x01), (1, 0x03), (3, 0x80)],
        2,
        idle_state_mask=0x40,
    )
    with ThingDAQ.simulated(output_enabled=True) as daq:
        device = _device(daq)
        committed = daq.upload_output(program, generation=101)
        armed = daq.output_arm()
        _require(committed.state is OutputState.COMMITTED, "finite upload failed")
        _require(armed.current_state_mask == 0x40, "finite idle state was not armed")
        daq.configure(adc=True, gpio=True)
        run_id = daq.start()
        acquisition = _combined_acquisition(daq, run_id)
        device.advance_time(96)
        completed = daq.output_status()
        _require(completed.state is OutputState.HELD, "finite run did not complete")
        _require(completed.completed_repeats == 2, "finite repeat count is wrong")
        _require(completed.last_emitted_state_mask == 0x80, "finite hold is wrong")
        samples = device.sample_output(
            [0, 15, 16, 23, 24, 47, 48, 64, 72, 96], run_id=run_id
        )
        if not isinstance(samples, tuple):  # pragma: no cover - overload guard
            raise DemonstrationError("finite sampled-state query was not a sequence")
        daq.stop()
        stopped = daq.output_status()
        _require(stopped.state is OutputState.HELD, "STOP did not retain finite hold")
        transitions = tuple(
            event for event in device.output_trace if event.run_id == run_id
        )
        released = daq.output_clear()
        release_sample = device.sample_output(96, run_id=run_id)
        if not isinstance(
            release_sample, SimulatedOutputSample
        ):  # pragma: no cover - overload guard
            raise DemonstrationError("finite release query was not scalar")
        _require(released.state is OutputState.EMPTY, "finite CLEAR did not erase")
        _require(release_sample.state_mask is None, "finite CLEAR did not release pins")

        print(
            "SIMULATED finite arm="
            f"{_hex_mask(armed.current_state_mask)} generation={armed.generation}"
        )
        _print_acquisition("finite", acquisition)
        _print_transitions("finite", transitions)
        _print_samples("finite", samples)
        print(
            "SIMULATED finite completion="
            f"{completed.state.name} repeats={completed.completed_repeats} "
            f"final_hold={_hex_mask(completed.last_emitted_state_mask)}"
        )
        print(
            "SIMULATED finite stop="
            f"{stopped.state.name} hold={_hex_mask(stopped.last_emitted_state_mask)}"
        )
        print(
            "SIMULATED finite release="
            f"{released.state.name} bank={released.bank_mode.name} "
            f"pins={_hex_mask(release_sample.state_mask)}"
        )
        return {
            "name": "finite",
            "program": _program_record(program),
            "run_id": run_id,
            "acquisition": acquisition,
            "transitions": [_transition_record(event) for event in transitions],
            "sampled_state_queries": [_sample_record(sample) for sample in samples],
            "completed_repeats": completed.completed_repeats,
            "final_hold_state_mask": completed.last_emitted_state_mask,
            "stop_state": stopped.state.name,
            "release_state": released.state.name,
            "release_bank_mode": released.bank_mode.name,
            "released_state_mask": release_sample.state_mask,
        }


def _infinite_demonstration() -> dict[str, Any]:
    program = DigitalOutputProgram.forever([(1, 0x0F), (2, 0xF0)], idle_state_mask=0x55)
    with ThingDAQ.simulated(output_enabled=True) as daq:
        device = _device(daq)
        committed = daq.upload_output(program, generation=102)
        armed = daq.output_arm()
        _require(committed.state is OutputState.COMMITTED, "infinite upload failed")
        daq.configure(adc=True, gpio=True)
        run_id = daq.start()
        acquisition = _combined_acquisition(daq, run_id)
        device.advance_time(56)
        running = daq.output_status()
        _require(running.state is OutputState.RUNNING, "infinite run completed")
        _require(running.completed_repeats == 2, "infinite repeat count is wrong")
        samples = device.sample_output(
            [0, 7, 8, 23, 24, 31, 32, 47, 48, 55, 56], run_id=run_id
        )
        if not isinstance(samples, tuple):  # pragma: no cover - overload guard
            raise DemonstrationError("infinite sampled-state query was not a sequence")
        daq.stop()
        stopped = daq.output_status()
        _require(stopped.state is OutputState.HELD, "infinite STOP did not hold")
        transitions = tuple(
            event for event in device.output_trace if event.run_id == run_id
        )
        released = daq.output_clear()
        release_sample = device.sample_output(56, run_id=run_id)
        if not isinstance(
            release_sample, SimulatedOutputSample
        ):  # pragma: no cover - overload guard
            raise DemonstrationError("infinite release query was not scalar")
        _require(release_sample.state_mask is None, "infinite CLEAR did not release")

        print(
            "SIMULATED infinite arm="
            f"{_hex_mask(armed.current_state_mask)} generation={armed.generation}"
        )
        _print_acquisition("infinite", acquisition)
        _print_transitions("infinite", transitions)
        _print_samples("infinite", samples)
        print(
            "SIMULATED infinite running="
            f"{running.state.name} repeats={running.completed_repeats} "
            f"current={_hex_mask(running.current_state_mask)}"
        )
        print(
            "SIMULATED infinite stop="
            f"{stopped.state.name} hold={_hex_mask(stopped.last_emitted_state_mask)}"
        )
        print(
            "SIMULATED infinite release="
            f"{released.state.name} bank={released.bank_mode.name} "
            f"pins={_hex_mask(release_sample.state_mask)}"
        )
        return {
            "name": "infinite",
            "program": _program_record(program),
            "run_id": run_id,
            "acquisition": acquisition,
            "transitions": [_transition_record(event) for event in transitions],
            "sampled_state_queries": [_sample_record(sample) for sample in samples],
            "completed_repeats_before_stop": running.completed_repeats,
            "stop_state": stopped.state.name,
            "final_hold_state_mask": stopped.last_emitted_state_mask,
            "release_state": released.state.name,
            "release_bank_mode": released.bank_mode.name,
            "released_state_mask": release_sample.state_mask,
        }


def _underrun_demonstration() -> dict[str, Any]:
    program = DigitalOutputProgram.forever([(2, 0x11), (2, 0x22)])
    with ThingDAQ.simulated(output_enabled=True) as daq:
        device = _device(daq)
        committed = daq.upload_output(program, generation=103)
        daq.output_arm()
        _require(committed.state is OutputState.COMMITTED, "underrun upload failed")
        daq.configure(adc=True, gpio=True)
        run_id = daq.start()
        acquisition = _combined_acquisition(daq, run_id)
        device.advance_time(16)
        fault = device.inject_output_fault(OutputError.UNDERRUN)
        common = daq.status()
        reported = daq.output_status()
        no_data_after_fault = device.next_data_frame() is None
        _require(fault.state is OutputState.FAULTED, "underrun did not fault output")
        _require(
            reported.output_error is OutputError.UNDERRUN, "fault was not reported"
        )
        _require(common.device_state is DeviceState.IDLE, "fault did not stop epoch")
        _require(common.stream_mask == StreamMask.NONE, "fault left acquisition active")
        _require(no_data_after_fault, "fault left simulated data delivery active")
        _require(
            reported.last_emitted_state_mask == 0x22,
            "underrun did not hold the last emitted state",
        )
        transitions = tuple(
            event for event in device.output_trace if event.run_id == run_id
        )
        recovered = daq.output_clear()
        release_sample = device.sample_output(16, run_id=run_id)
        if not isinstance(
            release_sample, SimulatedOutputSample
        ):  # pragma: no cover - overload guard
            raise DemonstrationError("fault release query was not scalar")
        _require(recovered.state is OutputState.EMPTY, "CLEAR did not recover fault")
        _require(recovered.bank_mode is OutputBankMode.DISABLED, "CLEAR left output on")
        _require(release_sample.state_mask is None, "fault CLEAR did not release pins")

        _print_acquisition("underrun", acquisition)
        _print_transitions("underrun", transitions)
        print(
            "SIMULATED underrun fault="
            f"{reported.output_error.name} output={reported.state.name} "
            f"hold={_hex_mask(reported.last_emitted_state_mask)} "
            f"common_epoch={common.device_state.name} "
            f"streams={common.stream_mask.name} data_after_fault={not no_data_after_fault}"
        )
        print(
            "SIMULATED underrun recovery="
            f"{recovered.state.name} bank={recovered.bank_mode.name} "
            f"pins={_hex_mask(release_sample.state_mask)}"
        )
        return {
            "name": "underrun",
            "program": _program_record(program),
            "run_id": run_id,
            "acquisition": acquisition,
            "transitions": [_transition_record(event) for event in transitions],
            "fault": reported.output_error.name,
            "fault_state": reported.state.name,
            "held_state_mask": reported.last_emitted_state_mask,
            "common_epoch_state": common.device_state.name,
            "active_stream_mask": int(common.stream_mask),
            "data_available_after_fault": not no_data_after_fault,
            "recovery_state": recovered.state.name,
            "recovery_bank_mode": recovered.bank_mode.name,
            "released_state_mask": release_sample.state_mask,
        }


def run_demonstration() -> dict[str, Any]:
    """Run all deterministic output scenarios and return primitive evidence."""

    print(
        "example=preloaded_output mode=simulator hardware_accessed=false "
        "timing=SIMULATED"
    )
    finite = _finite_demonstration()
    infinite = _infinite_demonstration()
    underrun = _underrun_demonstration()
    result = {
        "schema_version": SCHEMA_VERSION,
        "kind": ARTIFACT_KIND,
        "created": CREATED,
        "evidence_level": "simulated",
        "simulated": True,
        "hardware_accessed": False,
        "timing_claim": "simulated-only",
        "timestamp_hz": v1.TIMESTAMP_HZ,
        "output_state_rate_hz": v2.OUTPUT_RATE_HZ,
        "output_period_ticks": v2.OUTPUT_PERIOD_TICKS,
        "scenarios": [finite, infinite, underrun],
    }
    print("SIMULATED PASS finite+infinite+underrun output demonstration")
    return result


def _load_reporter() -> Any:
    if str(REPOSITORY_ROOT) not in sys.path:
        sys.path.insert(0, str(REPOSITORY_ROOT))
    from firmware.tools import experiment_evidence

    return experiment_evidence


def _input_record(reporter: Any, path: Path) -> dict[str, Any]:
    return {
        "path": path.relative_to(REPOSITORY_ROOT).as_posix(),
        "sha256": reporter.sha256_file(path),
    }


def _acceptance_records(matrix: Any) -> list[dict[str, Any]]:
    evidence_id = "aux-output-simulator-demonstration"
    observations: Mapping[str, tuple[object, object]] = {
        "lifecycle_complete": (
            True,
            {
                "output_begin_append_commit": True,
                "output_arm": True,
                "configure_combined": True,
                "start_common_epoch": True,
                "bounded_adc_gpio_capture": True,
                "finite_completion": True,
                "infinite_stop_hold": True,
                "fault_status": True,
                "clear_release": True,
            },
        ),
        "stream_health": (
            True,
            {
                "combined_blocks_present": True,
                "run_ids_exact": True,
                "unexpected_loss_events_zero": True,
                "injected_underrun_reconciled": True,
            },
        ),
        "final_idle_cleanup": (
            True,
            {
                "finite_clear_empty": True,
                "infinite_clear_empty": True,
                "fault_clear_empty": True,
                "all_output_banks_disabled": True,
                "all_output_pins_released": True,
                "all_transports_closed": True,
            },
        ),
        "claim_scope_complete": (
            True,
            {
                "every_timing_line_labeled_simulated": True,
                "hardware_access_absent": True,
                "physical_timing_claim_absent": True,
                "firmware_target_claim_absent": True,
            },
        ),
    }
    experiment = matrix.experiment("aux-output-bank")
    records: list[dict[str, Any]] = []
    for check_id in experiment["required_acceptance_checks"]:
        definition = matrix.acceptance_checks[check_id]
        if check_id in observations:
            expected, observed = observations[check_id]
            records.append(
                {
                    "id": check_id,
                    "description": definition["description"],
                    "state": "PASS",
                    "reason": None,
                    "operator": definition["operator"],
                    "expected": expected,
                    "observed": observed,
                    "evidence_ids": [evidence_id],
                    "required_evidence_levels": definition["required_evidence_levels"],
                }
            )
        else:
            records.append(
                {
                    "id": check_id,
                    "description": definition["description"],
                    "state": "NOT_RUN",
                    "reason": (
                        "the temporary output demonstration is simulated only; "
                        "the complete prototype gate runs separately"
                    ),
                    "operator": definition["operator"],
                    "expected": None,
                    "observed": None,
                    "evidence_ids": [],
                    "required_evidence_levels": definition["required_evidence_levels"],
                }
            )
    return records


def _metric(
    name: str,
    value: float,
    *,
    unit: str,
    denominator: str,
    scope: str,
) -> dict[str, Any]:
    return {
        "name": name,
        "value": value,
        "unit": unit,
        "denominator": denominator,
        "scope": scope,
        "evidence_level": "simulated",
        "evidence_ids": ["aux-output-simulator-demonstration"],
    }


def _report_paths(output: Path) -> tuple[Path, Path]:
    if output.suffix.casefold() == ".json":
        return output, output.with_suffix(".md")
    if output.suffix.casefold() == ".md":
        return output.with_suffix(".json"), output
    return Path(f"{output}.json"), Path(f"{output}.md")


def write_report(
    output: Path, result: dict[str, Any]
) -> tuple[Path, Path, dict[str, Any]]:
    """Emit temporary evidence through the shared experiment reporter."""

    reporter = _load_reporter()
    matrix = reporter.load_experiment_matrix(MATRIX_PATH)
    experiment = matrix.experiment("aux-output-bank")
    command = ["python", "daq_api/examples/preloaded_output.py"]
    evidence_id = "aux-output-simulator-demonstration"
    report = {
        "schema_version": matrix.report_contract["schema_version"],
        "matrix_schema_version": matrix.schema_version,
        "experiment_id": "aux-output-bank",
        "title": experiment["title"],
        "created": CREATED,
        "result": "INCONCLUSIVE",
        "reason": (
            "the finite, infinite, STOP/hold, CLEAR/release, and underrun "
            "simulations passed; host, target-build, and physical checks were not run"
        ),
        "summary": (
            "Temporary no-hardware evidence for preloaded D16-D23 output behavior "
            "on the deterministic common-epoch simulator. Every timing value is "
            "simulated and makes no firmware, USB, electrical, or physical claim."
        ),
        "identity": reporter.capture_identity(
            matrix,
            "aux-output-bank",
            root=REPOSITORY_ROOT,
        ),
        "evidence": [
            {
                "id": evidence_id,
                "level": "simulated",
                "result": "PASS",
                "reason": None,
                "method": (
                    "public protocol-v2 upload/arm/status/CLEAR commands, explicit "
                    "common-clock advancement, bounded transition/state queries, "
                    "combined ADC/GPIO block reads, STOP, and injected underrun"
                ),
                "command": {
                    "argv": command,
                    "network": False,
                    "serial_hardware": False,
                    "firmware_upload": False,
                    "user_input": False,
                },
                "inputs": [
                    _input_record(reporter, MATRIX_PATH),
                    _input_record(reporter, PROTOCOL_V2_PATH),
                    _input_record(
                        reporter, REPOSITORY_ROOT / "daq_api/src/thingdaq/output.py"
                    ),
                    _input_record(
                        reporter, REPOSITORY_ROOT / "daq_api/src/thingdaq/client.py"
                    ),
                    _input_record(
                        reporter, REPOSITORY_ROOT / "daq_api/src/thingdaq/simulator.py"
                    ),
                    _input_record(reporter, Path(__file__).resolve()),
                ],
                "simulator_identity": "ThingDAQ SimulatedDevice protocol-v1/v2",
                "protocol_identity": (
                    "protocol/protocol-v2.json sha256:"
                    + reporter.sha256_file(PROTOCOL_V2_PATH)
                ),
                "deterministic_budget": {
                    "scenarios": len(result["scenarios"]),
                    "combined_data_blocks_per_scenario": 2,
                    "explicit_advanced_ticks": 168,
                    "injected_underruns": 1,
                },
                "timing_claim": result["timing_claim"],
                "hardware_accessed": result["hardware_accessed"],
                "scenarios": result["scenarios"],
            }
        ],
        "metrics": [
            _metric(
                "timestamp_clock_hz",
                result["timestamp_hz"],
                unit="hertz",
                denominator="none",
                scope="artifact",
            ),
            _metric(
                "output_state_rate_hz",
                float(result["output_state_rate_hz"]),
                unit="hertz",
                denominator="streaming_elapsed_seconds",
                scope="output_window",
            ),
            _metric(
                "output_underruns",
                1,
                unit="event",
                denominator="none",
                scope="run",
            ),
        ],
        "acceptance": _acceptance_records(matrix),
        "limitations": [
            {
                "id": limitation_id,
                "statement": matrix.claim_limitations[limitation_id]["statement"],
                "applies_to_evidence_levels": matrix.claim_limitations[limitation_id][
                    "applies_to_evidence_levels"
                ],
            }
            for limitation_id in experiment["required_limitations"]
        ],
        "artifacts": [],
        "related": [
            "[[ADR-008-Experimental-Aux-Output-Bank]]",
            "[[1-MHz-Parallel-Output-Idea]]",
            "[[Acquisition-Pipeline]]",
            "[[Protocol-V1]]",
        ],
    }
    json_path, markdown_path = _report_paths(output)
    normalized = reporter.write_report_pair(
        matrix,
        report,
        json_path,
        markdown_path,
        root=REPOSITORY_ROOT,
    )
    return json_path, markdown_path, normalized


def parse_args(argv: Sequence[str] | None = None) -> argparse.Namespace:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument(
        "--output",
        type=Path,
        help="temporary report prefix or .json/.md path; writes both shared-schema formats",
    )
    return parser.parse_args(argv)


def main(argv: Sequence[str] | None = None) -> int:
    arguments = parse_args(argv)
    result = run_demonstration()
    if arguments.output is not None:
        json_path, markdown_path, report = write_report(arguments.output, result)
        print(
            f"SIMULATED report={report['result']} artifact_json={json_path} "
            f"artifact_markdown={markdown_path}"
        )
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
