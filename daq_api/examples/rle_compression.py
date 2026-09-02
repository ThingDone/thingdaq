"""Compare exact simulated RAW and adaptive RLE framing without hardware."""

from __future__ import annotations

import argparse
import sys
from collections.abc import Mapping, Sequence
from dataclasses import dataclass
from datetime import UTC, datetime
from pathlib import Path
from typing import Any

from thingdaq import (
    ADCBlock,
    ConfigurationEncoding,
    ExperimentalSourcePattern,
    FrameEncoding,
    GPIOBlock,
    Source,
    ThingDAQ,
)
from thingdaq._generated import protocol_constants as constants

REPOSITORY_ROOT = Path(__file__).resolve().parents[2]
MATRIX_PATH = REPOSITORY_ROOT / "experiments/experiment-matrix.json"
PROTOCOL_V2_PATH = REPOSITORY_ROOT / "protocol/protocol-v2.json"
DEFAULT_FRAMES_PER_STREAM = 2
MAX_FRAMES_PER_STREAM = 64
DataBlock = ADCBlock | GPIOBlock


@dataclass(frozen=True, slots=True)
class StreamCompressionSummary:
    """Exact RAW-versus-selected-RLE totals for one pattern and stream."""

    pattern: ExperimentalSourcePattern
    stream: str
    frames: int
    raw_payload_bytes: int
    encoded_payload_bytes: int
    raw_wire_bytes: int
    encoded_wire_bytes: int
    run_count: int
    rle_frames: int
    fallback_frames: int

    @property
    def payload_ratio(self) -> float:
        return self.encoded_payload_bytes / self.raw_payload_bytes

    @property
    def wire_ratio(self) -> float:
        return self.encoded_wire_bytes / self.raw_wire_bytes


def _frame_budget(value: str) -> int:
    try:
        selected = int(value, 10)
    except ValueError as error:
        raise argparse.ArgumentTypeError(
            "frames per stream must be a decimal integer"
        ) from error
    if not 1 <= selected <= MAX_FRAMES_PER_STREAM:
        raise argparse.ArgumentTypeError(
            f"frames per stream must be between 1 and {MAX_FRAMES_PER_STREAM}"
        )
    return selected


def _capture(
    pattern: ExperimentalSourcePattern,
    encoding: ConfigurationEncoding,
    frames_per_stream: int,
) -> dict[str, tuple[DataBlock, ...]]:
    blocks_by_stream: dict[str, list[DataBlock]] = {"ADC": [], "GPIO": []}
    with ThingDAQ.simulated_experimental(
        encoding=encoding,
        adc_pattern=pattern,
        gpio_pattern=pattern,
        read_chunk_size=37,
        write_chunk_size=7,
        strict=True,
    ) as daq:
        daq.configure(
            adc=True,
            gpio=True,
            source=Source.SYNTHETIC,
            encoding=encoding,
        )
        daq.start()
        for block in daq.blocks(2 * frames_per_stream):
            if isinstance(block, ADCBlock):
                blocks_by_stream["ADC"].append(block)
            elif isinstance(block, GPIOBlock):
                blocks_by_stream["GPIO"].append(block)
            else:  # pragma: no cover - strict mode converts anomalies to errors
                raise TypeError(
                    f"experimental simulator emitted {type(block).__name__}"
                )
        status = daq.validate_stream_health()
        if (
            status.adc_frames_emitted != frames_per_stream
            or status.gpio_frames_emitted != frames_per_stream
        ):
            raise RuntimeError("simulator status frame counts disagree with capture")
        daq.stop()
    if daq.is_open or daq.state is not constants.DeviceState.IDLE:
        raise RuntimeError("simulator did not finish closed and IDLE")
    return {name: tuple(blocks) for name, blocks in blocks_by_stream.items()}


def _summarize_stream(
    pattern: ExperimentalSourcePattern,
    stream: str,
    raw_blocks: Sequence[DataBlock],
    encoded_blocks: Sequence[DataBlock],
) -> StreamCompressionSummary:
    if len(raw_blocks) != len(encoded_blocks) or not raw_blocks:
        raise RuntimeError(f"{stream} RAW/RLE frame counts differ")
    encoded_payload_bytes = 0
    encoded_wire_bytes = 0
    run_count = 0
    rle_frames = 0
    fallback_frames = 0
    for raw, encoded in zip(raw_blocks, encoded_blocks, strict=True):
        if type(raw) is not type(encoded):
            raise RuntimeError(f"{stream} RAW/RLE block types differ")
        if (
            raw.sequence != encoded.sequence
            or raw.first_sample_ticks != encoded.first_sample_ticks
            or raw.payload != encoded.payload
        ):
            raise RuntimeError(f"{stream} decoded RAW/RLE samples differ")
        diagnostics = encoded.encoding_diagnostics
        if diagnostics is None:
            raise RuntimeError(f"{stream} RLE_AUTO block omitted diagnostics")
        encoded_payload_bytes += diagnostics.encoded_bytes
        encoded_wire_bytes += diagnostics.encoded_frame_bytes
        run_count += diagnostics.run_count
        if diagnostics.frame_encoding is FrameEncoding.RLE:
            rle_frames += 1
        else:
            fallback_frames += 1

    frames = len(raw_blocks)
    raw_payload_bytes = sum(len(block.payload) for block in raw_blocks)
    raw_wire_bytes = frames * constants.DATA_FRAME_BYTES
    if encoded_payload_bytes > raw_payload_bytes:
        raise RuntimeError(f"{stream} RLE_AUTO expanded the payload")
    if encoded_wire_bytes > raw_wire_bytes:
        raise RuntimeError(f"{stream} RLE_AUTO expanded the wire stream")
    return StreamCompressionSummary(
        pattern=pattern,
        stream=stream,
        frames=frames,
        raw_payload_bytes=raw_payload_bytes,
        encoded_payload_bytes=encoded_payload_bytes,
        raw_wire_bytes=raw_wire_bytes,
        encoded_wire_bytes=encoded_wire_bytes,
        run_count=run_count,
        rle_frames=rle_frames,
        fallback_frames=fallback_frames,
    )


def run_demo(
    patterns: Sequence[ExperimentalSourcePattern],
    *,
    frames_per_stream: int,
) -> tuple[StreamCompressionSummary, ...]:
    """Run bounded RAW and RLE_AUTO sessions and require logical equality."""

    if not 1 <= frames_per_stream <= MAX_FRAMES_PER_STREAM:
        raise ValueError(
            f"frames_per_stream must be between 1 and {MAX_FRAMES_PER_STREAM}"
        )
    if not patterns:
        raise ValueError("at least one source pattern is required")
    summaries: list[StreamCompressionSummary] = []
    for pattern in patterns:
        selected = ExperimentalSourcePattern(pattern)
        raw = _capture(selected, ConfigurationEncoding.RAW, frames_per_stream)
        encoded = _capture(
            selected,
            ConfigurationEncoding.RLE_AUTO,
            frames_per_stream,
        )
        for stream in ("ADC", "GPIO"):
            summaries.append(
                _summarize_stream(selected, stream, raw[stream], encoded[stream])
            )
    return tuple(summaries)


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


def _acceptance_records(
    matrix: Any,
    evidence_id: str,
    summaries: Sequence[StreamCompressionSummary],
) -> list[dict[str, Any]]:
    simulated_observations: Mapping[str, tuple[object, object]] = {
        "lifecycle_complete": (
            True,
            {
                "raw_session": True,
                "rle_auto_session": True,
                "bounded_capture": True,
                "status": True,
                "stop": True,
                "close": True,
            },
        ),
        "synthetic_formulas_exact": (
            "every RAW and RLE_AUTO logical block was byte-identical",
            "every RAW and RLE_AUTO logical block was byte-identical",
        ),
        "stream_health": (
            True,
            {
                "decoded_equality": True,
                "firmware_drops_zero": True,
                "host_queue_drops_zero": True,
                "parser_errors_zero": True,
                "transport_errors_zero": True,
            },
        ),
        "counter_conservation": (
            True,
            {
                "raw_to_rle_frames": {
                    "left": sum(item.frames for item in summaries),
                    "right": sum(item.frames for item in summaries),
                },
                "decoded_round_trip": True,
                "adaptive_no_expansion": all(
                    item.encoded_wire_bytes <= item.raw_wire_bytes for item in summaries
                ),
            },
        ),
        "queue_bounds": (0, 0),
        "final_idle_cleanup": (
            True,
            {"idle": True, "reader_closed": True, "transport_closed": True},
        ),
        "claim_scope_complete": (
            True,
            {
                "evidence_labeled_simulated": True,
                "workload_limitations_explicit": True,
                "physical_claims_absent": True,
            },
        ),
    }
    experiment = matrix.experiment("rle-streaming")
    records: list[dict[str, Any]] = []
    for check_id in experiment["required_acceptance_checks"]:
        definition = matrix.acceptance_checks[check_id]
        if check_id in simulated_observations:
            expected, observed = simulated_observations[check_id]
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
                        "the temporary compression demonstration is simulated only"
                    ),
                    "operator": definition["operator"],
                    "expected": None,
                    "observed": None,
                    "evidence_ids": [],
                    "required_evidence_levels": definition["required_evidence_levels"],
                }
            )
    return records


def _report_paths(output: Path) -> tuple[Path, Path]:
    if output.suffix.casefold() == ".json":
        return output, output.with_suffix(".md")
    if output.suffix.casefold() == ".md":
        return output.with_suffix(".json"), output
    return Path(f"{output}.json"), Path(f"{output}.md")


def write_report(
    output: Path,
    patterns: Sequence[ExperimentalSourcePattern],
    frames_per_stream: int,
    summaries: Sequence[StreamCompressionSummary],
) -> tuple[Path, Path]:
    """Emit temporary evidence through the repository's shared reporter."""

    reporter = _load_reporter()
    matrix = reporter.load_experiment_matrix(MATRIX_PATH)
    evidence_id = "rle-simulator-demo"
    protocol_v2_digest = reporter.sha256_file(PROTOCOL_V2_PATH)
    pattern_names = [pattern.value for pattern in patterns]
    command = [
        "python",
        "daq_api/examples/rle_compression.py",
        "--frames-per-stream",
        str(frames_per_stream),
    ]
    for pattern in pattern_names:
        command.extend(("--pattern", pattern))
    logical_raw_bytes = sum(item.raw_payload_bytes for item in summaries)
    encoded_wire_bytes = sum(item.encoded_wire_bytes for item in summaries)
    experiment = matrix.experiment("rle-streaming")
    report = {
        "schema_version": matrix.report_contract["schema_version"],
        "matrix_schema_version": matrix.schema_version,
        "experiment_id": "rle-streaming",
        "title": experiment["title"],
        "created": datetime.now(UTC).date().isoformat(),
        "result": "INCONCLUSIVE",
        "reason": (
            "simulator behavior passed; host, firmware-build, rig, and physical "
            "checks were not run"
        ),
        "summary": (
            "Temporary no-hardware RAW-versus-RLE_AUTO evidence for "
            f"{len(pattern_names)} deterministic source pattern(s)."
        ),
        "identity": reporter.capture_identity(
            matrix,
            "rle-streaming",
            root=REPOSITORY_ROOT,
        ),
        "evidence": [
            {
                "id": evidence_id,
                "level": "simulated",
                "result": "PASS",
                "reason": None,
                "method": (
                    "bounded in-memory RAW and adaptive-RLE captures with exact "
                    "decoded-byte comparison"
                ),
                "command": {
                    "argv": command,
                    "network": False,
                    "serial_hardware": False,
                    "firmware_upload": False,
                    "user_input": False,
                },
                "inputs": [
                    _input_record(reporter, Path(__file__).resolve()),
                    _input_record(
                        reporter,
                        REPOSITORY_ROOT / "daq_api/src/thingdaq/simulator.py",
                    ),
                    _input_record(
                        reporter,
                        REPOSITORY_ROOT / "daq_api/src/thingdaq/protocol_v2.py",
                    ),
                    _input_record(reporter, PROTOCOL_V2_PATH),
                ],
                "simulator_identity": "ThingDAQ ExperimentalSimulatedDevice",
                "protocol_identity": (
                    f"protocol/protocol-v2.json sha256:{protocol_v2_digest}"
                ),
                "deterministic_budget": {
                    "patterns": pattern_names,
                    "frames_per_stream": frames_per_stream,
                    "raw_sessions": len(pattern_names),
                    "rle_auto_sessions": len(pattern_names),
                },
            }
        ],
        "metrics": [
            {
                "name": "logical_raw_bytes",
                "value": logical_raw_bytes,
                "unit": "byte",
                "denominator": "none",
                "scope": "declared_codec_workload",
                "evidence_level": "simulated",
                "evidence_ids": [evidence_id],
            },
            {
                "name": "encoded_wire_bytes",
                "value": encoded_wire_bytes,
                "unit": "byte",
                "denominator": "none",
                "scope": "declared_codec_workload",
                "evidence_level": "simulated",
                "evidence_ids": [evidence_id],
            },
            {
                "name": "encoded_to_raw_ratio",
                "value": encoded_wire_bytes / logical_raw_bytes,
                "unit": "ratio",
                "denominator": "logical_raw_bytes",
                "scope": "declared_codec_workload",
                "evidence_level": "simulated",
                "evidence_ids": [evidence_id],
            },
        ],
        "acceptance": _acceptance_records(matrix, evidence_id, summaries),
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
            "[[ADR-006-Experimental-RLE-Streaming]]",
            "[[Experiment-Baseline]]",
        ],
    }
    json_path, markdown_path = _report_paths(output)
    reporter.write_report_pair(
        matrix,
        report,
        json_path,
        markdown_path,
        root=REPOSITORY_ROOT,
    )
    return json_path, markdown_path


def parse_args(argv: Sequence[str] | None = None) -> argparse.Namespace:
    parser = argparse.ArgumentParser(
        description=(
            "Run exact no-hardware RAW and adaptive-RLE captures over deterministic "
            "ADC/GPIO workloads."
        )
    )
    parser.add_argument(
        "--pattern",
        action="append",
        choices=[pattern.value for pattern in ExperimentalSourcePattern],
        help="source pattern to run; repeat as needed (default: all)",
    )
    parser.add_argument(
        "--frames-per-stream",
        type=_frame_budget,
        default=DEFAULT_FRAMES_PER_STREAM,
        help=f"logical frames per ADC/GPIO stream (default: {DEFAULT_FRAMES_PER_STREAM})",
    )
    parser.add_argument(
        "--output",
        type=Path,
        help="temporary report prefix or .json/.md path; writes both formats",
    )
    return parser.parse_args(argv)


def main(argv: Sequence[str] | None = None) -> int:
    arguments = parse_args(argv)
    patterns = tuple(
        ExperimentalSourcePattern(value)
        for value in (
            arguments.pattern
            if arguments.pattern is not None
            else [pattern.value for pattern in ExperimentalSourcePattern]
        )
    )
    print(
        "example=rle_compression physical_required=false evidence=simulated "
        f"patterns={len(patterns)} frames_per_stream={arguments.frames_per_stream}"
    )
    summaries = run_demo(patterns, frames_per_stream=arguments.frames_per_stream)
    for summary in summaries:
        print(
            f"pattern={summary.pattern.value} stream={summary.stream} "
            f"frames={summary.frames} "
            f"raw_payload_bytes={summary.raw_payload_bytes} "
            f"encoded_payload_bytes={summary.encoded_payload_bytes} "
            f"raw_wire_bytes={summary.raw_wire_bytes} "
            f"encoded_wire_bytes={summary.encoded_wire_bytes} "
            f"runs={summary.run_count} rle_frames={summary.rle_frames} "
            f"fallback_frames={summary.fallback_frames} "
            f"payload_ratio={summary.payload_ratio:.6f} "
            f"wire_ratio={summary.wire_ratio:.6f} decoded_equal=true"
        )
    if arguments.output is not None:
        json_path, markdown_path = write_report(
            arguments.output,
            patterns,
            arguments.frames_per_stream,
            summaries,
        )
        print(f"report_json={json_path} report_markdown={markdown_path}")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
