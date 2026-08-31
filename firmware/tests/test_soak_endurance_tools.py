"""Phase 11/12 endurance generator, validator, and result-aggregator tests."""

from __future__ import annotations

import ast
import copy
import importlib.util
import io
import json
import struct
import subprocess
import sys
import tempfile
import unittest
from contextlib import redirect_stderr, redirect_stdout
from dataclasses import replace
from pathlib import Path
from types import ModuleType
from unittest.mock import patch

from thingdaq._generated import protocol_constants as constants
from thingdaq.models import Configuration, DeviceInfo, Status
from thingdaq.simulator import SimulatedDevice

from firmware.soak import validator as canonical_validator
from firmware.tests.test_rig_combined_capture import (
    PhysicalCombinedDevice,
    _ready_metadata,
)
from firmware.tools import aggregate_soak_results as aggregator
from firmware.tools import check_soak_conformance as conformance
from firmware.tools import generate_soak_programs as generator

ROOT = Path(__file__).resolve().parents[2]
GENERATED_DIRECTORY = ROOT / "firmware/tests/generated"
TRANSCRIPT_PATH = ROOT / "firmware/tests/fixtures/soak/service-transcripts.json"
PROTOCOL_FIXTURES = ROOT / "protocol/fixtures"
SUCCESS_PREFIX = struct.pack("<BBH", 0, 0, 0)
ALLOWED_STANDALONE_IMPORTS = {
    "__future__",
    "collections",
    "dataclasses",
    "datetime",
    "hashlib",
    "json",
    "math",
    "os",
    "resource",
    "serial",
    "struct",
    "sys",
    "time",
    "tracemalloc",
    "typing",
    "zlib",
}
ALLOWED_WINDOWS_IMPORTS = ALLOWED_STANDALONE_IMPORTS | {
    "argparse",
    "ctypes",
    "pathlib",
    "platform",
    "re",
    "threading",
}
ACCELERATED_STREAM_STEP_SECONDS = 0.25
ACCELERATED_ADC_PAIR_RATE_HZ = int(
    canonical_validator.ADC_PAIRS_PER_FRAME / (2 * ACCELERATED_STREAM_STEP_SECONDS)
)
ACCELERATED_GPIO_SAMPLE_RATE_HZ = int(
    canonical_validator.GPIO_SAMPLES_PER_FRAME / (2 * ACCELERATED_STREAM_STEP_SECONDS)
)
ACCELERATED_PAYLOAD_BYTES_PER_SECOND = int(
    (
        canonical_validator.ADC_PAIRS_PER_FRAME * canonical_validator.ADC_BYTES_PER_PAIR
        + canonical_validator.GPIO_SAMPLES_PER_FRAME
    )
    / (2 * ACCELERATED_STREAM_STEP_SECONDS)
)


def _load_module(path: Path, name: str) -> ModuleType:
    specification = importlib.util.spec_from_file_location(name, path)
    if specification is None or specification.loader is None:
        raise RuntimeError(f"could not load {path}")
    module = importlib.util.module_from_spec(specification)
    sys.modules[name] = module
    specification.loader.exec_module(module)
    return module


def _imports(source: str) -> set[str]:
    result: set[str] = set()
    for node in ast.walk(ast.parse(source)):
        if isinstance(node, ast.Import):
            result.update(alias.name.split(".", 1)[0] for alias in node.names)
        elif isinstance(node, ast.ImportFrom) and node.module is not None:
            result.add(node.module.split(".", 1)[0])
    return result


def _transcripts() -> dict[str, dict[str, object]]:
    value = json.loads(TRANSCRIPT_PATH.read_text(encoding="utf-8"))
    if not isinstance(value, dict):
        raise TypeError("service transcript fixture must be an object")
    return value


def _record_from_case(case: dict[str, object]) -> aggregator.JobRecord:
    service = copy.deepcopy(case["service"])
    metadata = copy.deepcopy(case["metadata"])
    job_id = case["job_id"]
    soak = copy.deepcopy(case.get("soak"))
    if not isinstance(service, dict) or not isinstance(metadata, dict):
        raise TypeError("fixture service and metadata must be objects")
    if not isinstance(job_id, str):
        raise TypeError("fixture job ID must be text")
    service["test_id"] = job_id
    if isinstance(soak, dict):
        prefix = service.get("stdout")
        service["stdout"] = (
            (prefix + "\n" if isinstance(prefix, str) and prefix else "")
            + aggregator.SOAK_RESULT_PREFIX
            + json.dumps(soak, sort_keys=True, separators=(",", ":"))
        )
    fragment = aggregator._fragment_from_service(
        Path(f"fixture:{job_id}"),
        service,
        metadata,
    )
    records = aggregator.group_fragments([fragment])
    if len(records) != 1:
        raise AssertionError("one fixture case must produce exactly one record")
    return records[0]


def _accepted_record(
    sequence: int,
    *,
    started: str,
    completed: str,
    mode: str = "synthetic",
    traced_growth_bytes: int = 4_096,
) -> aggregator.JobRecord:
    case = copy.deepcopy(_transcripts()["success"])
    case["job_id"] = f"10000000-0000-4000-8000-{sequence:012d}"
    metadata = case["metadata"]
    soak = case["soak"]
    if not isinstance(metadata, dict) or not isinstance(soak, dict):
        raise TypeError("accepted fixture is malformed")
    metadata["client_started_utc"] = started
    metadata["client_completed_utc"] = completed
    soak["mode"] = mode
    metrics = soak["metrics"]
    if not isinstance(metrics, dict):
        raise TypeError("accepted fixture metrics are malformed")
    memory = metrics["memory"]
    if not isinstance(memory, dict) or not isinstance(memory["tracemalloc"], dict):
        raise TypeError("accepted fixture memory is malformed")
    memory["tracemalloc"]["growth_bytes"] = traced_growth_bytes
    return _record_from_case(case)


def _release_counters(*, frames: int, source: str, dropped: int = 0) -> dict[str, int]:
    counters = {name: 0 for name in aggregator.REQUIRED_ZERO_ERROR_COUNTERS}
    for prefix, items_per_frame, item_bytes in (
        ("adc", aggregator.ADC_PAIRS_PER_FRAME, aggregator.ADC_BYTES_PER_PAIR),
        ("gpio", aggregator.GPIO_SAMPLES_PER_FRAME, 1),
    ):
        generated = frames + dropped
        generated_items = generated * items_per_frame
        transmitted_items = frames * items_per_frame
        counters.update(
            {
                f"{prefix}_frames_generated": generated,
                f"{prefix}_frames_framed_pipeline": generated,
                f"{prefix}_frames_emitted": generated,
                f"{prefix}_frames_transmitted": frames,
                f"{prefix}_frames_dropped": dropped,
                f"{prefix}_packet_filling_depth": 0,
                f"{prefix}_packet_ready_depth": 0,
                f"{prefix}_packet_transmit_depth": 0,
                f"{prefix}_frames_dropped_after_framing": dropped,
                f"{prefix}_frames_dropped_after_promotion": dropped,
                f"{prefix}_frames_evicted": dropped,
                f"{prefix}_frames_evicted_after_promotion": dropped,
                f"{prefix}_items_generated": generated_items,
                f"{prefix}_items_framed_pipeline": generated_items,
                f"{prefix}_items_emitted": generated_items,
                f"{prefix}_items_transmitted_pipeline": transmitted_items,
                f"{prefix}_items_dropped": dropped * items_per_frame,
                f"{prefix}_payload_bytes_produced": generated_items * item_bytes,
                f"{prefix}_payload_bytes_framed": generated_items * item_bytes,
                f"{prefix}_payload_bytes_emitted": generated_items * item_bytes,
                f"{prefix}_payload_bytes_transmitted": (transmitted_items * item_bytes),
                f"{prefix}_payload_bytes_dropped": (
                    dropped * items_per_frame * item_bytes
                ),
                f"{prefix}_framed_bytes_framed": (
                    generated * aggregator.DATA_FRAME_BYTES
                ),
                f"{prefix}_framed_bytes_emitted": (
                    generated * aggregator.DATA_FRAME_BYTES
                ),
                f"{prefix}_framed_bytes_transmitted": (
                    frames * aggregator.DATA_FRAME_BYTES
                ),
            }
        )
    counters.update(
        {
            "adc_stop_pairs_discarded": 0,
            "gpio_raw_samples_lost": 0,
            "data_payload_bytes_transmitted": (
                counters["adc_payload_bytes_transmitted"]
                + counters["gpio_payload_bytes_transmitted"]
            ),
            "data_framed_bytes_transmitted": (
                counters["adc_framed_bytes_transmitted"]
                + counters["gpio_framed_bytes_transmitted"]
            ),
            "packet_pressure_evictions": 2 * dropped,
            "packet_capacity_drops_without_evictable_frame": 0,
            "packet_pool_exhaustions": 2 * dropped,
            "device_state": int(constants.DeviceState.IDLE),
            "source": int(
                constants.Source.SYNTHETIC
                if source == "synthetic"
                else constants.Source.HARDWARE
            ),
        }
    )
    return counters


def _release_epoch(
    *,
    index: int,
    source: str,
    seconds: float,
    dropped: int = 0,
) -> dict[str, object]:
    frames = int(seconds * aggregator.TARGET_ADC_PAIR_RATE_HZ) // (
        aggregator.ADC_PAIRS_PER_FRAME
    )
    adc_pairs = frames * aggregator.ADC_PAIRS_PER_FRAME
    gpio_samples = frames * aggregator.GPIO_SAMPLES_PER_FRAME
    payload_bytes = adc_pairs * aggregator.ADC_BYTES_PER_PAIR + gpio_samples
    framed_bytes = 2 * frames * aggregator.DATA_FRAME_BYTES
    timed: dict[str, object] = {
        "adc_frames": frames,
        "gpio_frames": frames,
        "adc_pairs": adc_pairs,
        "gpio_samples": gpio_samples,
        "payload_bytes": payload_bytes,
        "framed_bytes": framed_bytes,
    }
    negative: dict[str, object] | None = None
    if dropped:
        timed["adc_missing_frames"] = dropped
        timed["gpio_missing_frames"] = dropped
        loss = {
            "adc_frames": dropped,
            "gpio_frames": dropped,
            "packet_pressure_evictions": 2 * dropped,
            "packet_pool_exhaustions": 2 * dropped,
            "packet_capacity_drops_without_evictable_frame": 0,
        }
        negative = {
            "name": "serial_read_stall_pressure",
            "result": "PASS",
            "final_state": "IDLE",
            "loss": loss,
        }
    fixture_scope = (
        {"synthetic_formulas": "all-payload-items"}
        if source == "synthetic"
        else {
            "external_analog_stimulus": "not-declared",
            "external_digital_stimulus": "not-declared",
            "graded": "physical conversion/capture/DMA/packing/transport only",
        }
    )
    counters = _release_counters(frames=frames, source=source, dropped=dropped)
    counters["stats_generation"] = 2 * index + 1
    return {
        "index": index,
        "source": source,
        "run_id": index,
        "stats_generation": 2 * index + 1,
        "warmup_seconds": 1.0,
        "measured_elapsed_seconds": seconds,
        "timed": timed,
        "total": {
            "adc_frames": frames,
            "gpio_frames": frames,
            "adc_pairs": adc_pairs,
            "gpio_samples": gpio_samples,
        },
        "parser": {
            "errors": 0,
            "bytes_discarded": 0,
            "buffered_bytes": 0,
        },
        "fixture_scope": fixture_scope,
        "expected_negative_subcase": negative,
        "status": {"count": 10, "final_counters": counters},
        "final_counters": counters,
    }


def _release_record(
    sequence: int,
    *,
    mode: str,
    started: str,
    completed: str,
    traced_growth_bytes: int = 4_096,
) -> aggregator.JobRecord:
    case = copy.deepcopy(_transcripts()["success"])
    case["job_id"] = f"40000000-0000-4000-8000-{sequence:012d}"
    metadata = case["metadata"]
    soak = case["soak"]
    if not isinstance(metadata, dict) or not isinstance(soak, dict):
        raise TypeError("release fixture is malformed")
    program_sha256 = {
        "synthetic": "1" * 64,
        "physical-combined": "2" * 64,
        "control-stress": "3" * 64,
    }[mode]
    metadata.update(
        {
            "program_sha256": program_sha256,
            "client_started_utc": started,
            "client_completed_utc": completed,
        }
    )
    epochs = (
        [
            _release_epoch(index=1, source="hardware", seconds=300.0, dropped=1),
            _release_epoch(index=2, source="synthetic", seconds=300.0),
        ]
        if mode == "control-stress"
        else [
            _release_epoch(
                index=1,
                source="synthetic" if mode == "synthetic" else "hardware",
                seconds=600.0,
            )
        ]
    )
    streaming_seconds = sum(
        float(epoch["measured_elapsed_seconds"]) for epoch in epochs
    )
    payload_bytes = sum(int(epoch["timed"]["payload_bytes"]) for epoch in epochs)  # type: ignore[index]
    framed_bytes = sum(int(epoch["timed"]["framed_bytes"]) for epoch in epochs)  # type: ignore[index]
    adc_pairs = sum(int(epoch["timed"]["adc_pairs"]) for epoch in epochs)  # type: ignore[index]
    gpio_samples = sum(int(epoch["timed"]["gpio_samples"]) for epoch in epochs)  # type: ignore[index]
    memory = soak["metrics"]["memory"]  # type: ignore[index]
    if not isinstance(memory, dict):
        raise TypeError("release fixture memory is malformed")
    memory["tracemalloc"] = {"growth_bytes": traced_growth_bytes}
    memory["process_rss"] = {"growth_bytes": 8_192}
    memory["minimum_available_bytes"] = 512 * 1024 * 1024
    soak.update(
        {
            "mode": mode,
            "completed_utc": completed,
            "cleanup": {"attempted": False, "normal_close": True},
            "timing": {
                "measured_duration_seconds": 600.0,
                "measured_elapsed_seconds": 600.0,
                "streaming_elapsed_seconds": streaming_seconds,
            },
            "program": {
                "sha256": program_sha256,
                "validator_sha256": "4" * 64,
                "candidate_sha256": "5" * 64,
            },
            "epochs": epochs,
            "negative_subcases": [
                epoch["expected_negative_subcase"]
                for epoch in epochs
                if epoch["expected_negative_subcase"] is not None
            ],
            "metrics": {
                **soak["metrics"],  # type: ignore[dict-item]
                "epoch_count": len(epochs),
                "payload_bytes": payload_bytes,
                "framed_bytes": framed_bytes,
                "adc_pairs": adc_pairs,
                "gpio_samples": gpio_samples,
                "payload_bytes_per_streaming_second": (
                    payload_bytes / streaming_seconds
                ),
                "framed_bytes_per_streaming_second": (framed_bytes / streaming_seconds),
                "adc_pair_rate_hz": adc_pairs / streaming_seconds,
                "gpio_sample_rate_hz": gpio_samples / streaming_seconds,
                "memory": memory,
                "maximum_queues": {
                    "packet_owned_high_water": 200 if mode == "control-stress" else 2,
                    "packet_ready_high_water": 2,
                    "packet_transmit_high_water": (
                        200 if mode == "control-stress" else 2
                    ),
                },
            },
        }
    )
    return _record_from_case(case)


def _release_records() -> list[aggregator.JobRecord]:
    modes = (
        "synthetic",
        "synthetic",
        "physical-combined",
        "physical-combined",
        "physical-combined",
        "control-stress",
    )
    traced = (1_000, 1_100, 2_000, 2_200, 2_100, 3_000)
    return [
        _release_record(
            index,
            mode=mode,
            started=f"2026-08-29T{index:02d}:00:00+00:00",
            completed=f"2026-08-29T{index:02d}:10:30+00:00",
            traced_growth_bytes=traced[index - 1],
        )
        for index, mode in enumerate(modes, start=1)
    ]


def _release_indexes(
    records: list[aggregator.JobRecord],
) -> list[tuple[str, dict[str, object]]]:
    campaign_by_mode = {
        "synthetic": "phase-11-synthetic",
        "physical-combined": "phase-11-physical-combined",
        "control-stress": "phase-11-control-stress",
    }
    result: list[tuple[str, dict[str, object]]] = []
    for mode, campaign in campaign_by_mode.items():
        accepted = [
            {
                "job_id": record.job_id,
                "classification": "accepted",
                "bundle": str(TRANSCRIPT_PATH),
            }
            for record in records
            if record.soak is not None and record.soak.get("mode") == mode
        ]
        result.append(
            (
                f"fixture:{campaign}",
                {
                    "schema_version": 1,
                    "campaign": campaign,
                    "accepted": accepted,
                    "excluded": (
                        [
                            {
                                "job_id": "49999999-0000-4000-8000-000000000001",
                                "classification": "test_failure",
                                "reason": "explicit fixture exclusion",
                                "bundle": str(TRANSCRIPT_PATH),
                            }
                        ]
                        if mode == "synthetic"
                        else []
                    ),
                    "infrastructure_incidents": [],
                },
            )
        )
    return result


class VirtualClock:
    """Strictly monotonic virtual time advanced only by the fake serial peer."""

    def __init__(self) -> None:
        self.now = 0.0
        self.sleep_observer = None

    def monotonic(self) -> float:
        return self.now

    def perf_counter(self) -> float:
        return self.now

    def sleep(self, seconds: float) -> None:
        if seconds < 0:
            raise AssertionError("virtual clock cannot sleep backward")
        self.now += seconds
        if self.sleep_observer is not None:
            self.sleep_observer(seconds)

    def advance(self, seconds: float) -> None:
        if seconds < 0:
            raise AssertionError("virtual clock cannot advance backward")
        self.now += seconds


class AcceleratedSoakDevice(PhysicalCombinedDevice):
    """Reuse the Phase 08 conservation model for both Phase 11 sources."""

    def __init__(self, settings: object, rig: ModuleType) -> None:
        super().__init__()
        self.settings = settings
        self.rig = rig
        self.last_source = constants.Source.HARDWARE
        self.pressure_adc_frames = 0
        self.pressure_gpio_frames = 0
        self.adc_gap_pending = False
        self.gpio_gap_pending = False

    def _reset_counters(self) -> None:
        super()._reset_counters()
        self.pressure_adc_frames = 0
        self.pressure_gpio_frames = 0
        self.adc_gap_pending = False
        self.gpio_gap_pending = False

    def inject_expected_pressure_loss(self, frames_per_source: int = 1) -> None:
        if self.state is not constants.DeviceState.RUNNING:
            raise AssertionError("pressure loss requires a live accelerated run")
        if frames_per_source <= 0:
            raise AssertionError("pressure loss must skip complete frames")
        self.pressure_adc_frames += frames_per_source
        self.pressure_gpio_frames += frames_per_source
        self._adc_sequence += frames_per_source
        self._gpio_sequence += frames_per_source
        self._adc_first_ticks += frames_per_source * constants.FRAME_COVERAGE_TICKS
        self._gpio_first_ticks += frames_per_source * constants.FRAME_COVERAGE_TICKS
        self._adc_item_index += frames_per_source * constants.ADC_PAIRS_PER_FRAME
        self._gpio_item_index += frames_per_source * constants.GPIO_SAMPLES_PER_FRAME
        self.adc_gap_pending = True
        self.gpio_gap_pending = True

    def _handle_info(self, request):  # type: ignore[no-untyped-def]
        configuration = self.configuration
        applied_source = (
            configuration.source if configuration is not None else self.last_source
        )
        info = DeviceInfo(
            device_state=self.state,
            build_id=self.settings.build_id,
            hardware_serial=self.settings.hardware_serial,
            firmware_version=self.settings.firmware_version,
            board_id=constants.BoardId(self.settings.board_id),
            mcu_id=constants.McuId(self.settings.mcu_id),
            supported_stream_mask=(
                constants.StreamMask.ADC | constants.StreamMask.GPIO
            ),
            supported_source_mask=0x03,
            supported_configuration_mask=constants.ConfigurationProfile(
                constants.SUPPORTED_CONFIGURATION_MASK
            ),
            applied_stream_mask=(
                configuration.stream_mask
                if configuration is not None
                else constants.StreamMask.NONE
            ),
            applied_source=applied_source,
            data_checksum_algorithm=(
                configuration.data_checksum_algorithm
                if configuration is not None
                else constants.ChecksumAlgorithm(self.settings.checksum_algorithm)
            ),
            capability_bits=constants.Capability(constants.KNOWN_CAPABILITY_MASK),
            gpio_capture_diagnostic_mode=(
                constants.GpioCaptureDiagnosticMode.NON_DRIVING_CAPTURE
            ),
            gpio_capture_diagnostic_flags=(
                constants.GpioCaptureDiagnosticFlag.AVAILABLE
                | constants.GpioCaptureDiagnosticFlag.DECLARATION_VALID
            ),
            **_ready_metadata(),
        )
        response = bytearray(self._success_response(request, info.to_payload()))
        struct.pack_into(
            "<I",
            response,
            constants.HEADER_SIZE + constants.INFO_RESPONSE_ADC_PAIR_RATE_HZ_OFFSET,
            self.rig.ADC_PAIR_RATE_HZ,
        )
        struct.pack_into(
            "<I",
            response,
            constants.HEADER_SIZE + constants.INFO_RESPONSE_GPIO_SAMPLE_RATE_HZ_OFFSET,
            self.rig.GPIO_SAMPLE_RATE_HZ,
        )
        struct.pack_into(
            "<I",
            response,
            len(response) - constants.TRAILER_SIZE,
            canonical_validator.adler32(response[: -constants.TRAILER_SIZE]),
        )
        if self.state is constants.DeviceState.RUNNING:
            self.commands_accepted += 1
        return bytes(response)

    def _handle_configure(self, request):  # type: ignore[no-untyped-def]
        configuration = Configuration.from_payload(request.payload)
        supported = (
            self._state
            in {constants.DeviceState.IDLE, constants.DeviceState.CONFIGURED}
            and configuration.stream_mask
            == constants.StreamMask.ADC | constants.StreamMask.GPIO
            and configuration.source
            in {constants.Source.HARDWARE, constants.Source.SYNTHETIC}
            and configuration.data_checksum_algorithm
            in constants.SUPPORTED_CHECKSUM_ALGORITHMS
        )
        if not supported:
            return self._typed_error(
                request, constants.ErrorCode.UNSUPPORTED_CONFIGURATION
            )
        self._configuration = configuration
        self._state = constants.DeviceState.CONFIGURED
        self.last_source = configuration.source
        return self._success_response(
            request, SUCCESS_PREFIX + configuration.to_payload()
        )

    def status(self) -> Status:
        if self.last_source is constants.Source.HARDWARE:
            base = PhysicalCombinedDevice.status(self)
            adc_received = self._adc_frames_emitted
            gpio_received = self._gpio_frames_emitted
            adc_generated = adc_received + self.pressure_adc_frames
            gpio_generated = gpio_received + self.pressure_gpio_frames
            adc_generated_items = adc_generated * constants.ADC_PAIRS_PER_FRAME
            gpio_generated_items = gpio_generated * constants.GPIO_SAMPLES_PER_FRAME
            adc_received_items = adc_received * constants.ADC_PAIRS_PER_FRAME
            gpio_received_items = gpio_received * constants.GPIO_SAMPLES_PER_FRAME
            adc_stop_tail = base.adc_stop_pairs_discarded
            gpio_stop_tail = base.gpio_raw_samples_lost
            pressure_total = self.pressure_adc_frames + self.pressure_gpio_frames
            return replace(
                base,
                adc_items_dropped=(
                    self.pressure_adc_frames * constants.ADC_PAIRS_PER_FRAME
                    + adc_stop_tail
                ),
                gpio_items_dropped=(
                    self.pressure_gpio_frames * constants.GPIO_SAMPLES_PER_FRAME
                    + gpio_stop_tail
                ),
                gpio_samples_captured=gpio_generated_items + gpio_stop_tail,
                gpio_samples_packed=gpio_generated_items,
                gpio_samples_framed=gpio_generated_items,
                gpio_samples_transmitted=gpio_received_items,
                gpio_dma_major_loops=gpio_generated,
                adc0_dma_major_loops=adc_generated,
                adc1_dma_major_loops=adc_generated,
                adc0_dma_results=adc_generated_items,
                adc1_dma_results=adc_generated_items,
                adc_paired_major_loops=adc_generated,
                adc_buffers_completed=adc_generated,
                adc_buffers_acquired=adc_generated,
                adc_buffers_released=adc_generated,
                adc_pairs_captured=adc_generated_items + adc_stop_tail,
                adc_pairs_delivered=adc_generated_items,
                adc_pairs_framed=adc_generated_items,
                adc_pairs_transmitted=adc_received_items,
                adc_frames_generated=adc_generated,
                adc_items_generated=adc_generated_items,
                adc_frames_framed_pipeline=adc_generated,
                adc_items_framed_pipeline=adc_generated_items,
                adc_items_emitted=adc_received_items,
                adc_frames_transmitted=adc_received,
                adc_items_transmitted_pipeline=adc_received_items,
                adc_frames_dropped=self.pressure_adc_frames,
                gpio_frames_generated=gpio_generated,
                gpio_items_generated=gpio_generated_items,
                gpio_frames_framed_pipeline=gpio_generated,
                gpio_items_framed_pipeline=gpio_generated_items,
                gpio_items_emitted=gpio_received_items,
                gpio_frames_transmitted=gpio_received,
                gpio_items_transmitted_pipeline=gpio_received_items,
                gpio_frames_dropped=self.pressure_gpio_frames,
                adc_payload_bytes_produced=(
                    adc_generated * constants.DATA_PAYLOAD_BYTES
                ),
                adc_payload_bytes_framed=(adc_generated * constants.DATA_PAYLOAD_BYTES),
                adc_payload_bytes_emitted=(adc_received * constants.DATA_PAYLOAD_BYTES),
                adc_payload_bytes_transmitted=(
                    adc_received * constants.DATA_PAYLOAD_BYTES
                ),
                adc_payload_bytes_dropped=(
                    self.pressure_adc_frames * constants.DATA_PAYLOAD_BYTES
                ),
                adc_framed_bytes_framed=(adc_generated * constants.DATA_FRAME_BYTES),
                adc_framed_bytes_emitted=(adc_received * constants.DATA_FRAME_BYTES),
                adc_framed_bytes_transmitted=(
                    adc_received * constants.DATA_FRAME_BYTES
                ),
                gpio_payload_bytes_produced=(
                    gpio_generated * constants.DATA_PAYLOAD_BYTES
                ),
                gpio_payload_bytes_framed=(
                    gpio_generated * constants.DATA_PAYLOAD_BYTES
                ),
                gpio_payload_bytes_emitted=(
                    gpio_received * constants.DATA_PAYLOAD_BYTES
                ),
                gpio_payload_bytes_transmitted=(
                    gpio_received * constants.DATA_PAYLOAD_BYTES
                ),
                gpio_payload_bytes_dropped=(
                    self.pressure_gpio_frames * constants.DATA_PAYLOAD_BYTES
                ),
                gpio_framed_bytes_framed=(gpio_generated * constants.DATA_FRAME_BYTES),
                gpio_framed_bytes_emitted=(gpio_received * constants.DATA_FRAME_BYTES),
                gpio_framed_bytes_transmitted=(
                    gpio_received * constants.DATA_FRAME_BYTES
                ),
                packet_pool_exhaustions=pressure_total,
                packet_owned_high_water=(
                    constants.PACKET_BUFFER_COUNT
                    if pressure_total
                    else base.packet_owned_high_water
                ),
                packet_ready_high_water=(
                    constants.PACKET_READY_QUEUE_CAPACITY
                    if pressure_total
                    else base.packet_ready_high_water
                ),
                packet_frames_promoted=adc_received + gpio_received,
                packet_accounted_frame_skew=abs(adc_generated - gpio_generated),
                data_payload_bytes_transmitted=(
                    (adc_received + gpio_received) * constants.DATA_PAYLOAD_BYTES
                ),
                data_framed_bytes_transmitted=(
                    (adc_received + gpio_received) * constants.DATA_FRAME_BYTES
                ),
                packet_pressure_evictions=pressure_total,
                adc_frames_evicted=self.pressure_adc_frames,
                gpio_frames_evicted=self.pressure_gpio_frames,
                adc_frames_dropped_after_framing=self.pressure_adc_frames,
                gpio_frames_dropped_after_framing=self.pressure_gpio_frames,
            )
        base = SimulatedDevice.status(self)
        adc_items = base.adc_items_framed_pipeline
        gpio_items = base.gpio_items_framed_pipeline
        return replace(
            base,
            source=(
                constants.Source.HARDWARE
                if self.state is constants.DeviceState.IDLE
                else constants.Source.SYNTHETIC
            ),
            commands_accepted=self.commands_accepted,
            adc_pairs_framed=adc_items,
            adc_pairs_transmitted=adc_items,
            gpio_samples_framed=gpio_items,
            gpio_samples_transmitted=gpio_items,
        )

    def _next_adc_frame(self, configuration: Configuration) -> bytes:
        if configuration.source is constants.Source.SYNTHETIC:
            return SimulatedDevice._next_adc_frame(self, configuration)
        wire = PhysicalCombinedDevice._next_adc_frame(self, configuration)
        if self.adc_gap_pending:
            self.adc_gap_pending = False
            wire = self._with_expected_gap_flags(wire)
        return wire

    def _next_gpio_frame(self, configuration: Configuration) -> bytes:
        if configuration.source is constants.Source.SYNTHETIC:
            return SimulatedDevice._next_gpio_frame(self, configuration)
        wire = PhysicalCombinedDevice._next_gpio_frame(self, configuration)
        if self.gpio_gap_pending:
            self.gpio_gap_pending = False
            wire = self._with_expected_gap_flags(wire)
        return wire

    @staticmethod
    def _with_expected_gap_flags(wire: bytes) -> bytes:
        result = bytearray(wire)
        flags = struct.unpack_from("<H", result, constants.HEADER_FLAGS_OFFSET)[0]
        flags |= int(
            constants.FrameFlag.GAP_BEFORE | constants.FrameFlag.OVERRUN_BEFORE
        )
        struct.pack_into("<H", result, constants.HEADER_FLAGS_OFFSET, flags)
        struct.pack_into(
            "<I",
            result,
            len(result) - constants.TRAILER_SIZE,
            canonical_validator.adler32(result[: -constants.TRAILER_SIZE]),
        )
        return bytes(result)


class AcceleratedSerial:
    """PySerial-shaped peer that runs 600 virtual seconds in wall-clock seconds."""

    def __init__(
        self,
        device: AcceleratedSoakDevice,
        clock: VirtualClock,
        *,
        startup_noise: bool,
    ) -> None:
        self.device = device
        self.clock = clock
        self.pending = bytearray(b"boot noise\r\n\xef\xbe" if startup_noise else b"")
        self.closed = False

    def read(self, size: int = 1) -> bytes:
        if self.closed:
            raise RuntimeError("accelerated serial port is closed")
        if self.pending:
            self.clock.advance(0.001)
            count = min(size, len(self.pending))
            result = bytes(self.pending[:count])
            del self.pending[:count]
            return result
        if self.device.state is constants.DeviceState.RUNNING:
            wire = self.device.next_data_frame()
            self.clock.advance(ACCELERATED_STREAM_STEP_SECONDS)
            return wire or b""
        self.clock.advance(0.05)
        return b""

    def write(self, data: bytes | bytearray | memoryview) -> int:
        if self.closed:
            raise RuntimeError("accelerated serial port is closed")
        wire = bytes(data)
        for response in self.device.receive(wire):
            self.pending.extend(response)
        for trailing in self.device.trailing_data:
            self.pending.extend(trailing)
        self.device.trailing_data.clear()
        return len(wire)

    def close(self) -> None:
        self.closed = True


class AcceleratedPortFactory:
    """Preserve one device across the control-stress CDC reopen sequence."""

    def __init__(
        self,
        device: AcceleratedSoakDevice,
        clock: VirtualClock,
        ports: list[AcceleratedSerial],
    ) -> None:
        self.device = device
        self.clock = clock
        self.ports = ports
        self.clock.sleep_observer = self._observe_sleep

    def _observe_sleep(self, seconds: float) -> None:
        if (
            self.device.state is constants.DeviceState.RUNNING
            and seconds >= self.device.rig.EXPECTED_NEGATIVE_STALL_SECONDS
        ):
            self.device.inject_expected_pressure_loss()

    def __call__(self) -> AcceleratedSerial:
        port = AcceleratedSerial(
            self.device,
            self.clock,
            startup_noise=not self.ports,
        )
        self.ports.append(port)
        return port


class NoResponsePort:
    """Serial peer used to prove command timeouts use injected virtual time."""

    def __init__(self, clock: VirtualClock) -> None:
        self.clock = clock

    def read(self, size: int = 1) -> bytes:
        del size
        self.clock.advance(0.05)
        return b""

    def write(self, data: bytes | bytearray | memoryview) -> int:
        return len(data)

    def close(self) -> None:
        return None


class SoakGeneratorTests(unittest.TestCase):
    def test_generation_is_deterministic_and_check_mode_detects_no_drift(self) -> None:
        candidate = generator.load_object(generator.CANDIDATE_PATH)
        source = generator.VALIDATOR_PATH.read_text(encoding="utf-8")
        driver = generator.WINDOWS_DRIVER_PATH.read_text(encoding="utf-8")
        freeze_bytes = generator.CANDIDATE_FREEZE_PATH.read_bytes()
        protocol_bytes = generator.PROTOCOL_PATH.read_bytes()
        manifest_arguments = (
            candidate,
            generator.load_object(generator.PROTOCOL_PATH),
            generator.load_object(generator.CANDIDATE_FREEZE_PATH),
            source,
        )
        manifest_keywords = {
            "candidate_freeze_sha256": generator.sha256_bytes(freeze_bytes),
            "protocol_contract_sha256": generator.sha256_bytes(protocol_bytes),
        }
        manifest = generator.build_validation_manifest(
            *manifest_arguments,
            **manifest_keywords,
        )
        self.assertEqual(
            manifest,
            generator.build_validation_manifest(
                *manifest_arguments,
                **manifest_keywords,
            ),
        )
        first = generator.render_programs(source, candidate)
        second = generator.render_programs(source, candidate)
        self.assertEqual(first, second)
        self.assertEqual(set(generator.OUTPUTS.values()), set(first))
        first_windows = generator.render_windows_program(
            source, driver, candidate, manifest
        )
        second_windows = generator.render_windows_program(
            source, driver, candidate, manifest
        )
        self.assertEqual(first_windows, second_windows)
        first_package = generator.render_windows_program(
            source,
            driver,
            candidate,
            manifest,
            entry_point="installed-package",
        )
        second_package = generator.render_windows_program(
            source,
            driver,
            candidate,
            manifest,
            entry_point="installed-package",
        )
        self.assertEqual(first_package, second_package)

        with tempfile.TemporaryDirectory(prefix="soak-generation-", dir=ROOT) as raw:
            output_directory = Path(raw)
            windows_output = output_directory / "windows_soak.py"
            package_output = output_directory / "package_soak.py"
            validation_manifest_output = output_directory / "validation-manifest.json"
            generated_output = io.StringIO()
            with redirect_stdout(generated_output):
                generated_exit = generator.main(
                    [
                        "--candidate",
                        str(generator.CANDIDATE_PATH),
                        "--output-directory",
                        str(output_directory),
                        "--windows-output",
                        str(windows_output),
                        "--package-output",
                        str(package_output),
                        "--validation-manifest-output",
                        str(validation_manifest_output),
                    ]
                )
            digests_before = {
                path.name: generator.sha256_bytes(path.read_bytes())
                for path in output_directory.iterdir()
            }
            checked_output = io.StringIO()
            with redirect_stdout(checked_output):
                checked_exit = generator.main(
                    [
                        "--check",
                        "--candidate",
                        str(generator.CANDIDATE_PATH),
                        "--output-directory",
                        str(output_directory),
                        "--windows-output",
                        str(windows_output),
                        "--package-output",
                        str(package_output),
                        "--validation-manifest-output",
                        str(validation_manifest_output),
                    ]
                )
            digests_after = {
                path.name: generator.sha256_bytes(path.read_bytes())
                for path in output_directory.iterdir()
            }

        self.assertEqual(0, generated_exit, generated_output.getvalue())
        self.assertEqual(0, checked_exit, checked_output.getvalue())
        self.assertEqual(digests_before, digests_after)
        self.assertEqual(6, len(digests_before))

    def test_validation_manifest_is_complete_and_contains_no_local_identity(
        self,
    ) -> None:
        manifest = generator.load_object(generator.VALIDATION_MANIFEST_PATH)
        self.assertEqual(1, manifest["schema_version"])
        self.assertEqual(
            ["[[Phase-11-Soak-Evidence]]"],
            manifest["related"],
        )
        self.assertEqual("thingdaq-e27556de5b898f28", manifest["firmware"]["build_id"])
        self.assertEqual(
            "da645bafbf05cd342ef069a17de35ecbfd7ec6f485365cedc571d01ee87415e3",
            manifest["firmware"]["exported_hex"]["sha256"],
        )
        self.assertEqual(
            {"algorithm": 1, "name": "ADLER32"},
            {
                name: manifest["protocol"]["checksum"][name]
                for name in ("algorithm", "name")
            },
        )
        self.assertEqual(500, manifest["acquisition"]["adc1_phase_nanoseconds"])
        self.assertEqual(
            {"adc0": 14, "adc1": 15},
            manifest["acquisition"]["adc_pins_by_pair_position"],
        )
        self.assertEqual(
            list(range(6, 14)), manifest["acquisition"]["gpio_pins_by_bit"]
        )
        self.assertEqual(4096, manifest["protocol"]["frames"]["data_frame_bytes"])
        self.assertEqual(12, manifest["acquisition"]["adc_resolution_bits"])
        self.assertGreater(
            len(manifest["required_zero"]["firmware_during_stream_fields"]),
            50,
        )
        self.assertFalse(
            manifest["release_policy"]["identity_override_results_are_release_eligible"]
        )
        encoded = json.dumps(manifest, sort_keys=True)
        for forbidden in (
            "/home/",
            "\\\\Users\\\\",
            ".maestro/",
            "COM1",
            "COM10",
            "credential",
            "api_key",
        ):
            with self.subTest(forbidden=forbidden):
                self.assertNotIn(forbidden, encoded)

    def test_standalone_and_installed_entry_paths_pass_conformance_gate(self) -> None:
        result = conformance.check_conformance()

        self.assertEqual("PASS", result["result"])
        self.assertEqual(
            ["windows-standalone", "installed-package"],
            result["entry_points"],
        )
        checks = result["checks"]
        self.assertIsInstance(checks, dict)
        assert isinstance(checks, dict)
        self.assertTrue(all(checks.values()))
        self.assertEqual(
            {
                "valid": {"result": "PASS", "failure_category": None},
                "checksum_corruption": {
                    "result": "FAIL",
                    "failure_category": "checksum_corruption",
                },
                "pattern_error": {
                    "result": "FAIL",
                    "failure_category": "pattern_error",
                },
                "source_gap": {
                    "result": "FAIL",
                    "failure_category": "source_gap",
                },
            },
            result["grades"],
        )

    def test_each_generated_program_imports_in_isolation_without_numpy(self) -> None:
        for mode, filename in generator.OUTPUTS.items():
            path = GENERATED_DIRECTORY / filename
            source = path.read_text(encoding="utf-8")
            with self.subTest(mode=mode):
                self.assertEqual(ALLOWED_STANDALONE_IMPORTS, _imports(source))
                self.assertNotIn("numpy", source.lower())
                self.assertNotIn("from thingdaq", source)
                self.assertNotIn("import thingdaq", source)
                isolated = subprocess.run(
                    [
                        sys.executable,
                        "-I",
                        "-c",
                        (
                            "import importlib.util,sys;"
                            "p=sys.argv[1];"
                            "s=importlib.util.spec_from_file_location('standalone',p);"
                            "m=importlib.util.module_from_spec(s);"
                            "sys.modules[s.name]=m;"
                            "s.loader.exec_module(m);"
                            "print(m.GENERATED_CONFIG['mode'])"
                        ),
                        str(path),
                    ],
                    cwd=ROOT,
                    capture_output=True,
                    check=False,
                    text=True,
                )
                self.assertEqual(
                    0, isolated.returncode, isolated.stdout + isolated.stderr
                )
                self.assertEqual(mode, isolated.stdout.strip())

    def test_windows_program_is_standalone_and_pins_the_one_hour_profile(self) -> None:
        path = generator.WINDOWS_OUTPUT_PATH
        source = path.read_text(encoding="utf-8")
        self.assertEqual(ALLOWED_WINDOWS_IMPORTS, _imports(source))
        self.assertNotIn("numpy", source.lower())
        self.assertNotIn("from thingdaq", source)
        self.assertNotIn("import thingdaq", source)
        windows = _load_module(path, "generated_windows_soak_contract")
        settings = windows.load_settings()
        self.assertEqual("windows-standalone", windows.GENERATED_CONFIG["entry_point"])
        self.assertEqual("physical-combined", settings.mode)
        self.assertEqual(3_600.0, settings.measured_duration_seconds)
        self.assertEqual(20_512_460, settings.hardware_serial)
        self.assertEqual("thingdaq-e27556de5b898f28", settings.build_id)
        self.assertEqual(
            "da645bafbf05cd342ef069a17de35ecbfd7ec6f485365cedc571d01ee87415e3",
            settings.artifact_sha256,
        )
        manifest = generator.load_object(generator.VALIDATION_MANIFEST_PATH)
        self.assertEqual(manifest, windows.GENERATED_CONFIG["validation_manifest"])
        self.assertEqual(
            generator.sha256_bytes(generator.canonical_json_bytes(manifest)),
            settings.validation_manifest_sha256,
        )

        installed = _load_module(
            generator.PACKAGE_OUTPUT_PATH,
            "generated_installed_soak_contract",
        )
        installed_settings = installed.load_settings()
        self.assertEqual("installed-package", installed.GENERATED_CONFIG["entry_point"])
        self.assertEqual(vars(settings), vars(installed_settings))
        self.assertEqual(
            windows.soak_conformance_vector(),
            installed.soak_conformance_vector(),
        )

    def test_identity_override_is_explicit_and_always_non_release(self) -> None:
        windows = _load_module(
            generator.WINDOWS_OUTPUT_PATH,
            "generated_windows_soak_identity_override",
        )
        strict = windows.windows_runtime_settings("combined", 3_600.0)
        observed = dict(strict.expected_info)
        observed["firmware_version"] = tuple(observed["firmware_version"])
        observed["gpio_pin_map"] = tuple(observed["gpio_pin_map"])
        observed["build_id"] = "thingdaq-diagnostic-other"
        observed.update(
            {
                "device_state": windows.STATE_IDLE,
                "applied_stream_mask": windows.STREAM_NONE,
                "applied_source": windows.SOURCE_HARDWARE,
            }
        )
        with self.assertRaises(windows.SoakFailure) as caught:
            windows.validate_info_identity(
                observed,
                strict,
                expected_state=windows.STATE_IDLE,
            )
        self.assertEqual("identity", caught.exception.category)

        override = windows.windows_runtime_settings(
            "combined",
            3_600.0,
            diagnostic_identity_override=True,
        )
        windows.validate_info_identity(
            observed,
            override,
            expected_state=windows.STATE_IDLE,
        )
        mismatches = windows.info_identity_mismatches(observed, override)
        self.assertEqual(
            "thingdaq-e27556de5b898f28", mismatches["build_id"]["expected"]
        )
        self.assertEqual("thingdaq-diagnostic-other", mismatches["build_id"]["actual"])

        candidate = windows.WindowsPortCandidate(
            port="COM10",
            vid=windows.TEENSY_USB_SERIAL_VID,
            pid=windows.TEENSY_USB_SERIAL_PID,
            serial_number=str(override.hardware_serial),
            product=windows.THINGDAQ_PRODUCT,
            manufacturer="PJRC",
            location="fixture-location",
            interface="CDC",
            description="ThingDAQ",
        )
        probe = windows.WindowsProbeResult(
            candidate=candidate,
            observed_identity=windows._observed_probe_identity(
                observed, override.expected_info
            ),
            identity_mismatches=mismatches,
            latency_seconds=[0.001],
            failure=None,
            close={
                "attempted": True,
                "completed": True,
                "timed_out": False,
                "error": None,
            },
        )
        result = windows.windows_failure_result(
            windows.SoakFailure("fixture", "replaced below"),
            settings=override,
            mode="combined",
        )
        result["result"] = "PASS"
        result["failure"] = None
        result["observed_identity"] = probe.observed_identity
        arguments = windows.build_windows_parser().parse_args(
            ["--diagnostic-identity-override", "--output", "unused"]
        )
        arguments.hardware_serial = override.hardware_serial
        windows.attach_windows_evidence(
            result,
            arguments=arguments,
            duration=3_600.0,
            candidates=(candidate,),
            probes=(probe,),
            selected=candidate,
            lifecycle=[],
        )
        self.assertEqual("PASS", result["result"])
        self.assertEqual("diagnostic-identity-override", result["windows"]["profile"])
        self.assertFalse(result["windows"]["release_eligible"])
        self.assertEqual(
            mismatches,
            result["windows"]["diagnostic_identity_override"]["identity_mismatches"],
        )
        markdown = windows.render_windows_markdown(result)
        self.assertIn("**NON-RELEASE**", markdown)
        self.assertIn("thingdaq-diagnostic-other", markdown)

    def test_windows_metadata_filter_and_failure_reports_are_structured(self) -> None:
        windows = _load_module(
            generator.WINDOWS_OUTPUT_PATH,
            "generated_windows_soak_metadata",
        )

        def metadata(
            port: str,
            vid: int,
            pid: int,
            *,
            product: str | None,
        ) -> object:
            return type(
                "PortMetadata",
                (),
                {
                    "device": port,
                    "vid": vid,
                    "pid": pid,
                    "serial_number": "20512460",
                    "product": product,
                    "manufacturer": "PJRC",
                    "location": "1-2",
                    "interface": "CDC",
                    "description": product or "USB Serial",
                },
            )()

        candidates = windows.enumerate_windows_candidates(
            lambda: [
                metadata("COM10", 0x16C0, 0x0483, product=None),
                metadata("COM1", 0x16C0, 0x0483, product="ThingDAQ"),
                metadata("COM2", 0x1234, 0x5678, product="Unrelated"),
                metadata("/dev/ttyACM0", 0x16C0, 0x0483, product="ThingDAQ"),
            ]
        )
        self.assertEqual(["COM1", "COM10"], [item.port for item in candidates])
        self.assertEqual("ThingDAQ", candidates[0].product)
        self.assertIsNone(candidates[1].product)

        settings = windows.windows_runtime_settings("combined", 10.0)
        result = windows.windows_failure_result(
            windows.SoakFailure("discovery", "fixture has no device"),
            settings=settings,
            mode="combined",
        )
        arguments = windows.build_windows_parser().parse_args(
            ["--smoke", "--output", "unused"]
        )
        arguments.hardware_serial = settings.hardware_serial
        windows.attach_windows_evidence(
            result,
            arguments=arguments,
            duration=10.0,
            candidates=candidates,
            probes=(),
            selected=None,
            lifecycle=[],
        )
        with tempfile.TemporaryDirectory(prefix="windows-report-", dir=ROOT) as raw:
            json_path, markdown_path = windows.write_windows_reports(
                Path(raw) / "report",
                result,
            )
            report = json.loads(json_path.read_text(encoding="utf-8"))
            markdown = markdown_path.read_text(encoding="utf-8")
        self.assertEqual("FAIL", report["result"])
        self.assertEqual("discovery", report["failure"]["category"])
        self.assertEqual(2, report["windows"]["com_discovery"]["candidate_count"])
        self.assertTrue(markdown.startswith("---\ntype: report\n"))
        self.assertIn("[[Phase-11-Soak-Evidence]]", markdown)
        self.assertIn("## Complete machine-readable record", markdown)

    def test_generated_read_batches_preserve_physical_runner_cadence(self) -> None:
        expected = {
            "synthetic": canonical_validator.SYNTHETIC_SERIAL_READ_BYTES,
            "physical-combined": canonical_validator.PHYSICAL_SERIAL_READ_BYTES,
            "control-stress": canonical_validator.PHYSICAL_SERIAL_READ_BYTES,
        }
        self.assertEqual(64 * 1024, expected["synthetic"])
        self.assertEqual(16 * 1024, expected["physical-combined"])
        for index, (mode, filename) in enumerate(generator.OUTPUTS.items(), start=1):
            rig = _load_module(
                GENERATED_DIRECTORY / filename,
                f"generated_soak_read_batch_{index}",
            )
            settings = rig.load_settings()
            with self.subTest(mode=mode):
                self.assertEqual(expected[mode], settings.serial_read_bytes)
                clock = VirtualClock()
                link = rig.SerialLink(
                    NoResponsePort(clock),
                    clock,
                    read_bytes=settings.serial_read_bytes,
                )
                self.assertEqual(expected[mode], link.read_bytes)
                self.assertEqual(expected[mode], link.parser.maximum_input_bytes)


class SoakValidatorFailureTests(unittest.TestCase):
    def test_physical_adc_range_check_covers_every_high_nibble(self) -> None:
        adc_wire = (PROTOCOL_FIXTURES / "adc-data.bin").read_bytes()
        parsed = canonical_validator.FrameParser().feed(adc_wire)[0]
        physical = replace(
            parsed,
            flags=canonical_validator.FLAG_EPOCH_START,
            payload=bytes(len(parsed.payload)),
        )
        canonical_validator.StreamValidator(
            physical.run_id,
            canonical_validator.SOURCE_HARDWARE,
            physical.checksum_algorithm,
            VirtualClock(),
        ).accept(physical)

        for byte_index in (
            1,
            len(physical.payload) // 2 + 1,
            len(physical.payload) - 1,
        ):
            invalid = bytearray(physical.payload)
            invalid[byte_index] = 0x10
            validator = canonical_validator.StreamValidator(
                physical.run_id,
                canonical_validator.SOURCE_HARDWARE,
                physical.checksum_algorithm,
                VirtualClock(),
            )
            with self.subTest(byte_index=byte_index):
                with self.assertRaises(canonical_validator.SoakFailure) as caught:
                    validator.accept(replace(physical, payload=bytes(invalid)))
                self.assertEqual("physical_range", caught.exception.category)

    def test_cgroup_cpu_tracker_reports_boundary_deltas(self) -> None:
        with patch.object(
            canonical_validator,
            "_cgroup_cpu_statistics",
            side_effect=[
                {"nr_periods": 10, "nr_throttled": 2, "throttled_usec": 5_000},
                {"nr_periods": 20, "nr_throttled": 7, "throttled_usec": 17_000},
            ],
        ):
            cpu = canonical_validator.CpuTracker()
            cpu.sample()
        summary = cpu.summary()
        self.assertEqual(10, summary["delta"]["nr_periods"])
        self.assertEqual(5, summary["delta"]["nr_throttled"])
        self.assertEqual(12_000, summary["delta"]["throttled_usec"])

    def test_wire_and_resource_failures_match_transcript_categories(self) -> None:
        clock = VirtualClock()
        adc_wire = (PROTOCOL_FIXTURES / "adc-data.bin").read_bytes()
        adc_frame = canonical_validator.FrameParser().feed(adc_wire)[0]
        observed: set[str] = set()

        corrupt_wire = bytearray(adc_wire)
        corrupt_wire[canonical_validator.HEADER_SIZE + 17] ^= 0x80
        link = canonical_validator.SerialLink(NoResponsePort(clock), clock)
        before_errors = link.parser.errors
        link.parser.feed(bytes(corrupt_wire))
        with self.assertRaises(canonical_validator.SoakFailure) as caught:
            link._raise_new_parser_error(before_errors)
        observed.add(caught.exception.category)

        bad_payload = bytearray(adc_frame.payload)
        bad_payload[0] ^= 1
        stream = canonical_validator.StreamValidator(
            adc_frame.run_id,
            canonical_validator.SOURCE_SYNTHETIC,
            adc_frame.checksum_algorithm,
            clock,
        )
        with self.assertRaises(canonical_validator.SoakFailure) as caught:
            stream.accept(replace(adc_frame, payload=bytes(bad_payload)))
        observed.add(caught.exception.category)

        stream = canonical_validator.StreamValidator(
            adc_frame.run_id,
            canonical_validator.SOURCE_SYNTHETIC,
            adc_frame.checksum_algorithm,
            clock,
        )
        stream.accept(adc_frame)
        with self.assertRaises(canonical_validator.SoakFailure) as caught:
            stream.accept(
                replace(
                    adc_frame,
                    flags=canonical_validator.FLAG_SYNTHETIC,
                    sequence=2,
                    first_sample_ticks=2 * canonical_validator.FRAME_COVERAGE_TICKS,
                )
            )
        observed.add(caught.exception.category)

        status_values = {
            name: 0
            for names in (
                canonical_validator._STATUS_BASE_FIELDS,
                canonical_validator._STATUS_GPIO_U64_FIELDS,
                canonical_validator._STATUS_GPIO_U16_FIELDS,
                canonical_validator._STATUS_GPIO_U32_FIELDS,
                canonical_validator._STATUS_ADC_U64_FIELDS,
                canonical_validator._STATUS_ADC_U32_FIELDS,
                canonical_validator._STATUS_PIPELINE_U64_FIELDS,
                canonical_validator._STATUS_QUEUE_U16_FIELDS,
                canonical_validator._STATUS_PACKET_U64_FIELDS,
                canonical_validator._STATUS_PACKET_U32_FIELDS,
                canonical_validator._STATUS_DIAGNOSTIC_U32_FIELDS,
                canonical_validator._STATUS_USB_U32_FIELDS,
                canonical_validator._STATUS_USB_U16_FIELDS,
                canonical_validator._STATUS_CACHE_U32_FIELDS,
                canonical_validator._STATUS_PARSER_DETAIL_U32_FIELDS,
                canonical_validator._STATUS_RESPONSE_U32_FIELDS,
                canonical_validator._STATUS_PRESSURE_U64_FIELDS,
                canonical_validator._STATUS_EVICTION_U64_FIELDS,
                canonical_validator._STATUS_DROP_BOUNDARY_U64_FIELDS,
                canonical_validator._STATUS_GPIO_PIPELINE_DETAIL_U64_FIELDS,
                canonical_validator._STATUS_GPIO_PACKER_DETAIL_U64_FIELDS,
                canonical_validator._STATUS_ADC_PIPELINE_DETAIL_U64_FIELDS,
                canonical_validator._STATUS_DROP_PROJECTION_U64_FIELDS,
            )
            for name in names
        }
        status_values.update(
            {
                "device_state": canonical_validator.STATE_IDLE,
                "source": canonical_validator.SOURCE_SYNTHETIC,
                "checksum": canonical_validator.CHECKSUM_ADLER32,
                "data_frame_bytes": canonical_validator.DATA_FRAME_BYTES,
                "stats_generation": 1,
                "adc_raw_ready_depth": 0,
                "adc_raw_ready_high_water": 0,
                "packet_ready_depth": 1,
                "packet_owned_depth": 1,
                "usb_active_frame_size": 0,
                "adc_packet_filling_depth": 0,
                "gpio_packet_filling_depth": 0,
            }
        )
        with self.assertRaises(canonical_validator.SoakFailure) as caught:
            canonical_validator.validate_status_invariants(
                canonical_validator.StatusSnapshot(status_values),
                source=canonical_validator.SOURCE_SYNTHETIC,
            )
        observed.add(caught.exception.category)

        latency = canonical_validator.BoundedLatency()
        latency.add(canonical_validator.STATUS_P99_LIMIT_SECONDS + 0.001)
        latency_p99 = latency.summary()["p99_seconds"]
        with self.assertRaises(canonical_validator.SoakFailure) as caught:
            canonical_validator.require(
                isinstance(latency_p99, float)
                and latency_p99 <= canonical_validator.STATUS_P99_LIMIT_SECONDS,
                "latency_violation",
                "fixture STATUS latency exceeded",
            )
        observed.add(caught.exception.category)

        memory = object.__new__(canonical_validator.MemoryTracker)
        memory.baseline_traced_bytes = 0
        memory.maximum_traced_bytes = canonical_validator.MAX_TRACED_GROWTH_BYTES + 1
        with self.assertRaises(canonical_validator.SoakFailure) as caught:
            canonical_validator.require(
                memory.traced_growth_bytes
                <= canonical_validator.MAX_TRACED_GROWTH_BYTES,
                "memory_growth",
                "fixture traced memory exceeded",
            )
        observed.add(caught.exception.category)

        timeout_clock = VirtualClock()
        timeout_link = canonical_validator.SerialLink(
            NoResponsePort(timeout_clock), timeout_clock
        )
        with self.assertRaises(canonical_validator.DeadlineExpired) as caught:
            timeout_link.exchange(canonical_validator.INFO_REQUEST, timeout=0.10)
        observed.add(caught.exception.category)

        expected = {
            str(case["soak"]["failure"]["category"])
            for case in _transcripts().values()
            if isinstance(case.get("soak"), dict)
            and case["soak"].get("result") == "FAIL"
        }
        self.assertEqual(expected, observed)

    def test_latency_percentiles_use_bounded_nearest_rank(self) -> None:
        latency = canonical_validator.BoundedLatency()
        for milliseconds in range(1, 101):
            latency.add(milliseconds / 1_000)
        summary = latency.summary()
        self.assertEqual(100, summary["count"])
        self.assertEqual(0.050, summary["p50_seconds"])
        self.assertEqual(0.095, summary["p95_seconds"])
        self.assertEqual(0.099, summary["p99_seconds"])
        self.assertEqual(0.100, summary["maximum_seconds"])

    def test_streaming_memory_sampling_avoids_tracing_and_filesystem_probes(
        self,
    ) -> None:
        canonical_validator.tracemalloc.stop()
        try:
            with (
                patch.object(
                    canonical_validator,
                    "_current_rss_bytes",
                    return_value=64 * 1024**2,
                ),
                patch.object(
                    canonical_validator,
                    "_peak_rss_bytes",
                    return_value=64 * 1024**2,
                ),
                patch.object(
                    canonical_validator,
                    "_available_process_memory_bytes",
                    return_value=512 * 1024**2,
                ),
            ):
                memory = canonical_validator.MemoryTracker()
                memory.begin_streaming()

            self.assertFalse(canonical_validator.tracemalloc.is_tracing())
            with (
                patch.object(
                    canonical_validator,
                    "_current_rss_bytes",
                    side_effect=AssertionError("streaming current RSS probe"),
                ),
                patch.object(
                    canonical_validator,
                    "_available_process_memory_bytes",
                    side_effect=AssertionError("streaming available-memory probe"),
                ),
                patch.object(
                    canonical_validator,
                    "_peak_rss_bytes",
                    return_value=70 * 1024**2,
                ),
            ):
                memory.sample_streaming(checkpoint=True)

            with (
                patch.object(
                    canonical_validator,
                    "_current_rss_bytes",
                    return_value=65 * 1024**2,
                ),
                patch.object(
                    canonical_validator,
                    "_peak_rss_bytes",
                    return_value=70 * 1024**2,
                ),
                patch.object(
                    canonical_validator,
                    "_available_process_memory_bytes",
                    return_value=500 * 1024**2,
                ),
            ):
                memory.end_streaming()

            summary = memory.summary()
            self.assertTrue(canonical_validator.tracemalloc.is_tracing())
            self.assertEqual(1, summary["coverage"]["streaming_windows"])
            self.assertEqual(1, summary["coverage"]["streaming_samples"])
            self.assertEqual(6 * 1024**2, summary["process_rss"]["growth_bytes"])
            self.assertEqual(500 * 1024**2, summary["minimum_available_bytes"])
        finally:
            canonical_validator.tracemalloc.stop()


class AcceleratedCampaignTests(unittest.TestCase):
    def test_failure_retains_active_epoch_and_host_pressure_evidence(self) -> None:
        rig = _load_module(
            GENERATED_DIRECTORY / generator.OUTPUTS["physical-combined"],
            "generated_soak_active_failure",
        )
        clock = VirtualClock()
        ports: list[AcceleratedSerial] = []
        settings = rig.load_settings()
        device = AcceleratedSoakDevice(settings, rig)
        healthy_status = device.status

        def status_with_pressure() -> Status:
            status = healthy_status()
            if device.state is constants.DeviceState.RUNNING:
                return replace(status, packet_pool_exhaustions=1)
            return status

        with (
            patch.object(rig, "ADC_PAIR_RATE_HZ", ACCELERATED_ADC_PAIR_RATE_HZ),
            patch.object(rig, "GPIO_SAMPLE_RATE_HZ", ACCELERATED_GPIO_SAMPLE_RATE_HZ),
            patch.object(
                rig,
                "TARGET_COMBINED_PAYLOAD_BYTES_PER_SECOND",
                ACCELERATED_PAYLOAD_BYTES_PER_SECOND,
            ),
            patch.object(rig, "_current_rss_bytes", return_value=64 * 1024**2),
            patch.object(rig, "_peak_rss_bytes", return_value=64 * 1024**2),
            patch.object(
                rig,
                "_available_process_memory_bytes",
                return_value=512 * 1024**2,
            ),
            patch.object(rig, "_cgroup_cpu_statistics", return_value={}),
            patch.object(device, "status", side_effect=status_with_pressure),
        ):
            exit_code, result = rig.run_generated(
                settings,
                AcceleratedPortFactory(device, clock, ports),
                clock=clock,
            )

        self.assertEqual(1, exit_code)
        self.assertEqual("counter_disagreement", result["failure"]["category"])
        active = result["metrics"]["active_epoch"]
        self.assertEqual(1, active["index"])
        self.assertEqual("hardware", active["source"])
        self.assertEqual(
            1, active["last_status_nonzero_errors"]["packet_pool_exhaustions"]
        )
        cleanup = result["cleanup"]["pre_stop_status"]
        self.assertEqual(constants.DeviceState.RUNNING, cleanup["state"])
        self.assertEqual(1, cleanup["nonzero_errors"]["packet_pool_exhaustions"])
        self.assertIn("packet_owned_high_water", cleanup["queues"])
        self.assertEqual(0, active["parser"]["errors"])
        self.assertIn("maximum_receive_gap_seconds", active)

    def test_control_stress_read_stall_preserves_one_parser_session(self) -> None:
        rig = _load_module(
            GENERATED_DIRECTORY / generator.OUTPUTS["control-stress"],
            "generated_soak_read_stall",
        )
        clock = VirtualClock()
        ports: list[AcceleratedSerial] = []
        settings = replace(rig.load_settings(), measured_duration_seconds=24.0)
        device = AcceleratedSoakDevice(settings, rig)
        output = io.StringIO()

        with (
            patch.object(rig, "ADC_PAIR_RATE_HZ", ACCELERATED_ADC_PAIR_RATE_HZ),
            patch.object(rig, "GPIO_SAMPLE_RATE_HZ", ACCELERATED_GPIO_SAMPLE_RATE_HZ),
            patch.object(
                rig,
                "TARGET_COMBINED_PAYLOAD_BYTES_PER_SECOND",
                ACCELERATED_PAYLOAD_BYTES_PER_SECOND,
            ),
            patch.object(rig, "RATE_TOLERANCE_FRACTION", 0.12),
            patch.object(rig, "_current_rss_bytes", return_value=64 * 1024**2),
            patch.object(rig, "_peak_rss_bytes", return_value=64 * 1024**2),
            patch.object(
                rig,
                "_available_process_memory_bytes",
                return_value=512 * 1024**2,
            ),
            redirect_stdout(output),
        ):
            exit_code, result = rig.run_generated(
                settings,
                AcceleratedPortFactory(device, clock, ports),
                clock=clock,
            )

        self.assertEqual(0, exit_code, output.getvalue() + repr(result))
        negative = result["negative_subcases"][0]
        self.assertEqual("serial_read_stall_pressure", negative["name"])
        self.assertEqual("continuous", negative["transport_session"])
        self.assertEqual(negative["parser_before"], negative["parser_after"])
        self.assertGreater(negative["loss"]["adc_frames"], 0)
        self.assertGreater(negative["loss"]["gpio_frames"], 0)

    def test_all_generated_600_second_modes_execute_with_a_fake_clock(self) -> None:
        for index, (mode, filename) in enumerate(generator.OUTPUTS.items(), start=1):
            rig = _load_module(
                GENERATED_DIRECTORY / filename,
                f"generated_soak_accelerated_{index}",
            )
            clock = VirtualClock()
            ports: list[AcceleratedSerial] = []
            output = io.StringIO()

            with (
                patch.object(rig, "ADC_PAIR_RATE_HZ", ACCELERATED_ADC_PAIR_RATE_HZ),
                patch.object(
                    rig,
                    "GPIO_SAMPLE_RATE_HZ",
                    ACCELERATED_GPIO_SAMPLE_RATE_HZ,
                ),
                patch.object(
                    rig,
                    "TARGET_COMBINED_PAYLOAD_BYTES_PER_SECOND",
                    ACCELERATED_PAYLOAD_BYTES_PER_SECOND,
                ),
                patch.object(rig, "RATE_TOLERANCE_FRACTION", 0.12),
                patch.object(rig, "_current_rss_bytes", return_value=64 * 1024**2),
                patch.object(rig, "_peak_rss_bytes", return_value=64 * 1024**2),
                patch.object(
                    rig,
                    "_available_process_memory_bytes",
                    return_value=512 * 1024**2,
                ),
                redirect_stdout(output),
            ):
                settings = rig.load_settings()
                device = AcceleratedSoakDevice(settings, rig)
                exit_code, result = rig.run_generated(
                    settings,
                    AcceleratedPortFactory(device, clock, ports),
                    clock=clock,
                )

            with self.subTest(mode=mode):
                self.assertEqual(600.0, settings.measured_duration_seconds)
                self.assertEqual(0, exit_code, output.getvalue() + repr(result))
                self.assertEqual("PASS", result["result"])
                self.assertEqual(mode, result["mode"])
                self.assertGreaterEqual(
                    result["timing"]["measured_elapsed_seconds"], 600.0
                )
                self.assertLess(
                    result["timing"]["script_elapsed_seconds"],
                    settings.hard_deadline_seconds,
                )
                timed_payload = sum(
                    epoch["timed"]["payload_bytes"] for epoch in result["epochs"]
                )
                self.assertEqual(result["metrics"]["payload_bytes"], timed_payload)
                self.assertTrue(
                    any(
                        epoch["total"]["adc_frames"] + epoch["total"]["gpio_frames"]
                        > epoch["timed"]["adc_frames"] + epoch["timed"]["gpio_frames"]
                        for epoch in result["epochs"]
                    ),
                    "warm-up frames must be excluded from timed metrics",
                )
                self.assertTrue(all(port.closed for port in ports))
                self.assertEqual(constants.DeviceState.IDLE, device.state)
                if mode == "control-stress":
                    sources = [epoch["source"] for epoch in result["epochs"]]
                    self.assertGreater(len(sources), 2)
                    self.assertEqual(
                        ["hardware", "synthetic", "hardware", "synthetic"],
                        sources[:4],
                    )
                    self.assertGreater(result["metrics"]["cdc_reopen_count"], 0)
                    self.assertEqual(
                        1, result["metrics"]["expected_negative_subcase_count"]
                    )
                    self.assertEqual(1, len(result["negative_subcases"]))
                    negative = result["negative_subcases"][0]
                    self.assertEqual("serial_read_stall_pressure", negative["name"])
                    self.assertEqual("PASS", negative["result"])
                    self.assertEqual("IDLE", negative["final_state"])
                    loss = negative["loss"]
                    self.assertGreater(loss["adc_frames"], 0)
                    self.assertGreater(loss["gpio_frames"], 0)
                    self.assertEqual(
                        loss["adc_frames"] + loss["gpio_frames"],
                        loss["packet_pressure_evictions"],
                    )
                    self.assertEqual(
                        0, loss["packet_capacity_drops_without_evictable_frame"]
                    )
                    lossy_epochs = [
                        epoch
                        for epoch in result["epochs"]
                        if epoch["expected_negative_subcase"] is not None
                    ]
                    self.assertEqual(1, len(lossy_epochs))
                    self.assertEqual("hardware", lossy_epochs[0]["source"])
                    self.assertTrue(
                        all(
                            epoch["timed"]["adc_missing_frames"] == 0
                            and epoch["timed"]["gpio_missing_frames"] == 0
                            for epoch in result["epochs"]
                            if epoch is not lossy_epochs[0]
                        )
                    )
                else:
                    self.assertEqual(1, result["metrics"]["epoch_count"])


class SoakAggregatorTests(unittest.TestCase):
    def test_fixture_transcripts_cover_success_and_every_failure_boundary(self) -> None:
        transcripts = _transcripts()
        records = [_record_from_case(case) for case in transcripts.values()]
        result = aggregator.aggregate(records)
        classifications = {
            run["job_id"]: run["classification"] for run in result["runs"]
        }
        self.assertEqual(1, result["classification_counts"]["accepted"])
        self.assertEqual(7, result["classification_counts"]["test_failure"])
        self.assertEqual(1, result["classification_counts"]["upload_failure"])
        self.assertEqual(1, result["classification_counts"]["service_failure"])
        self.assertEqual(1, result["classification_counts"]["program_failure"])
        self.assertEqual(len(transcripts), result["run_count"])
        self.assertEqual(
            "upload_failure",
            classifications[transcripts["upload_failure"]["job_id"]],
        )
        self.assertEqual(
            "service_failure",
            classifications[transcripts["service_failure"]["job_id"]],
        )
        truncated_id = transcripts["truncated_result"]["job_id"]
        truncated = next(run for run in result["runs"] if run["job_id"] == truncated_id)
        self.assertEqual("program_failure", truncated["classification"])
        self.assertTrue(
            any("truncated/invalid" in problem for problem in truncated["problems"])
        )

    def test_units_warmup_metrics_and_missing_fields_are_explicit(self) -> None:
        record = _record_from_case(_transcripts()["success"])
        run = aggregator.record_summary(record)
        metrics = run["metrics"]
        self.assertEqual(12.3, metrics["status_p99_milliseconds"])
        self.assertEqual(21.0, metrics["status_maximum_milliseconds"])
        self.assertEqual(34.5, metrics["command_maximum_milliseconds"])
        self.assertEqual("ms", aggregator.metric_unit("status_p99_milliseconds"))
        self.assertEqual("B/s", aggregator.metric_unit("payload_bytes_per_second"))
        self.assertEqual("Hz", aggregator.metric_unit("adc_pair_rate_hz"))
        self.assertEqual(8_000_000.0, metrics["payload_bytes_per_second"])

        sparse = aggregator.comparable_metrics(
            {"timing": {"measured_duration_seconds": 600.0}, "metrics": {}}
        )
        self.assertEqual(600.0, sparse["measured_duration_seconds"])
        self.assertIsNone(sparse["status_p99_milliseconds"])
        self.assertIsNone(sparse["payload_bytes_per_second"])

    def test_artifact_identity_and_missing_evidence_do_not_count(self) -> None:
        accepted_case = _transcripts()["success"]
        accepted = _record_from_case(accepted_case)
        self.assertEqual("accepted", aggregator.classify(accepted)[0])

        mismatch_case = copy.deepcopy(accepted_case)
        mismatch_case["job_id"] = "20000000-0000-4000-8000-000000000001"
        mismatch_case["metadata"]["artifact_sha256"] = "a" * 64
        mismatch = _record_from_case(mismatch_case)
        classification, disposition, problems = aggregator.classify(mismatch)
        self.assertEqual("evidence_failure", classification)
        self.assertEqual("diagnose_harness", disposition)
        self.assertIn("job metadata artifact_sha256 mismatch", problems)

        missing_case = copy.deepcopy(accepted_case)
        missing_case["job_id"] = "20000000-0000-4000-8000-000000000002"
        del missing_case["metadata"]["program_sha256"]
        missing = _record_from_case(missing_case)
        classification, _disposition, problems = aggregator.classify(missing)
        self.assertEqual("evidence_failure", classification)
        self.assertIn("job metadata program_sha256 is missing", problems)

    def test_retry_classification_keeps_infrastructure_separate_from_test_exit(
        self,
    ) -> None:
        transcripts = _transcripts()
        expected = {
            "upload_failure": ("upload_failure", "infrastructure_retry_once", -130),
            "service_failure": ("service_failure", "infrastructure_retry_once", -120),
            "pattern_error": ("test_failure", "release_candidate_failure", 1),
        }
        for name, wanted in expected.items():
            run = aggregator.record_summary(_record_from_case(transcripts[name]))
            with self.subTest(case=name):
                self.assertEqual(wanted[0], run["classification"])
                self.assertEqual(wanted[1], run["disposition"])
                self.assertEqual(wanted[2], run["test_exit_status"])

    def test_sequential_timestamps_and_cross_run_trends_are_ordered(self) -> None:
        first = _accepted_record(
            1,
            started="2026-08-29T12:00:00+00:00",
            completed="2026-08-29T12:10:30+00:00",
            traced_growth_bytes=1_000,
        )
        second = _accepted_record(
            2,
            started="2026-08-29T12:11:00+00:00",
            completed="2026-08-29T12:21:30+00:00",
            traced_growth_bytes=2_000,
        )
        third = _accepted_record(
            3,
            started="2026-08-29T12:22:00+00:00",
            completed="2026-08-29T12:32:30+00:00",
            traced_growth_bytes=3_000,
        )
        result = aggregator.aggregate([third, first, second])
        self.assertTrue(result["accepted_jobs_are_sequential"])
        self.assertTrue(all(run["sequential_to_previous"] for run in result["runs"]))
        growth = result["trends"]["synthetic"]["traced_growth_bytes"]
        self.assertEqual("B", growth["unit"])
        self.assertEqual([1_000.0, 2_000.0, 3_000.0], growth["values"])
        self.assertTrue(growth["monotonic_increase"])

        overlap = _accepted_record(
            4,
            started="2026-08-29T12:20:00+00:00",
            completed="2026-08-29T12:40:00+00:00",
        )
        overlapping_result = aggregator.aggregate([first, second, overlap])
        self.assertFalse(overlapping_result["accepted_jobs_are_sequential"])

    def test_uniform_identity_detects_distinct_but_self_consistent_artifacts(
        self,
    ) -> None:
        first = _accepted_record(
            11,
            started="2026-08-29T13:00:00+00:00",
            completed="2026-08-29T13:10:30+00:00",
        )
        second_case = copy.deepcopy(_transcripts()["success"])
        second_case["job_id"] = "30000000-0000-4000-8000-000000000012"
        second_case["metadata"]["artifact_sha256"] = "a" * 64
        second_case["metadata"]["client_started_utc"] = "2026-08-29T13:11:00+00:00"
        second_case["metadata"]["client_completed_utc"] = "2026-08-29T13:21:30+00:00"
        second_case["soak"]["expected"]["artifact_sha256"] = "a" * 64
        second = _record_from_case(second_case)
        result = aggregator.aggregate([first, second])
        self.assertEqual({"accepted": 2}, result["classification_counts"])
        self.assertFalse(result["accepted_identity_is_uniform"])
        self.assertEqual(2, len(result["accepted_identity_sets"]["artifact_sha256"]))

    def test_phase_11_release_gate_accepts_complete_six_job_campaign(self) -> None:
        records = _release_records()
        aggregate_result = aggregator.aggregate(records)
        release = aggregator.evaluate_phase_11_release(
            records,
            aggregate_result,
            _release_indexes(records),
        )

        self.assertEqual("PASS", release["result"], release["problems"])
        self.assertTrue(all(release["checks"].values()))
        self.assertEqual(6, len(release["run_evidence"]))
        self.assertEqual(1, len(release["excluded_jobs"]))
        self.assertEqual([], release["infrastructure_incidents"])
        self.assertEqual(
            [[0, 7, 0]], aggregate_result["accepted_identity_sets"]["firmware_version"]
        )

    def test_phase_11_release_gate_fails_closed_on_each_policy_boundary(self) -> None:
        mutations: dict[str, object] = {}

        mixed_identity = _release_records()
        mixed_soak = mixed_identity[0].soak
        if mixed_soak is None:
            self.fail("release fixture has no SOAK_RESULT")
        mixed_soak["expected"]["artifact_sha256"] = "a" * 64  # type: ignore[index]
        mixed_identity[0].metadata["artifact_sha256"] = "a" * 64
        mutations["identity"] = mixed_identity

        short = _release_records()
        short_soak = short[0].soak
        if short_soak is None:
            self.fail("release fixture has no SOAK_RESULT")
        short_soak["timing"]["measured_duration_seconds"] = 60.0  # type: ignore[index]
        mutations["duration_and_evidence"] = short

        bad_latency = _release_records()
        latency_soak = bad_latency[0].soak
        if latency_soak is None:
            self.fail("release fixture has no SOAK_RESULT")
        latency_soak["metrics"]["latency"]["status"]["p99_seconds"] = 0.2  # type: ignore[index]
        mutations["latency"] = bad_latency

        broken_conservation = _release_records()
        conservation_soak = broken_conservation[0].soak
        if conservation_soak is None:
            self.fail("release fixture has no SOAK_RESULT")
        del conservation_soak["epochs"][0]["status"]["final_counters"][  # type: ignore[index]
            "adc_payload_bytes_produced"
        ]
        mutations["conservation"] = broken_conservation

        monotonic_resources = _release_records()
        for record, growth in zip(monotonic_resources[2:5], (1_000, 2_000, 3_000)):
            if record.soak is None:
                self.fail("release fixture has no SOAK_RESULT")
            record.soak["metrics"]["memory"]["tracemalloc"][  # type: ignore[index]
                "growth_bytes"
            ] = growth
        mutations["resources"] = monotonic_resources

        for expected_check, raw_records in mutations.items():
            if not isinstance(raw_records, list):
                self.fail("release mutation is not a record list")
            records = raw_records
            aggregate_result = aggregator.aggregate(records)
            release = aggregator.evaluate_phase_11_release(
                records,
                aggregate_result,
                _release_indexes(records),
            )
            with self.subTest(check=expected_check):
                self.assertEqual("FAIL", release["result"])
                self.assertFalse(release["checks"][expected_check])

        missing_lineage = _release_records()
        indexes = _release_indexes(missing_lineage)
        del indexes[0][1]["infrastructure_incidents"]
        release = aggregator.evaluate_phase_11_release(
            missing_lineage,
            aggregator.aggregate(missing_lineage),
            indexes,
        )
        self.assertEqual("FAIL", release["result"])
        self.assertFalse(release["checks"]["campaign_indexes"])


class SoakAggregatorCliTests(unittest.TestCase):
    def test_saved_bundle_parse_and_strict_exit_codes(self) -> None:
        case = copy.deepcopy(_transcripts()["success"])
        service = case["service"]
        soak = case["soak"]
        if not isinstance(service, dict) or not isinstance(soak, dict):
            self.fail("success fixture is malformed")
        service["test_id"] = case["job_id"]
        service["stdout"] = aggregator.SOAK_RESULT_PREFIX + json.dumps(soak)
        bundle = {
            "job_id": case["job_id"],
            "service_result": service,
            "job_metadata": case["metadata"],
        }
        with tempfile.TemporaryDirectory(prefix="soak-aggregate-", dir=ROOT) as raw:
            path = Path(raw) / "accepted.json"
            path.write_text(json.dumps(bundle), encoding="utf-8")
            stdout = io.StringIO()
            stderr = io.StringIO()
            with redirect_stdout(stdout), redirect_stderr(stderr):
                exit_code = aggregator.main(["--strict", str(path)])
            self.assertEqual(0, exit_code, stderr.getvalue())
            parsed = json.loads(stdout.getvalue())
            self.assertEqual({"accepted": 1}, parsed["classification_counts"])

            stdout = io.StringIO()
            stderr = io.StringIO()
            with redirect_stdout(stdout), redirect_stderr(stderr):
                release_exit = aggregator.main(
                    ["--strict", "--phase-11-release", str(path)]
                )
            self.assertEqual(1, release_exit, stderr.getvalue())
            release_result = json.loads(stdout.getvalue())
            self.assertEqual("FAIL", release_result["release_gate"]["result"])


if __name__ == "__main__":
    unittest.main()
