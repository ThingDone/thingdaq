"""Phase 11 endurance-generator, validator, and result-aggregator tests."""

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

from teensy_daq._generated import protocol_constants as constants
from teensy_daq.models import Configuration, DeviceInfo, Status
from teensy_daq.simulator import SimulatedDevice

from firmware.soak import validator as canonical_validator
from firmware.tests.test_rig_combined_capture import (
    PhysicalCombinedDevice,
    _ready_metadata,
)
from firmware.tools import aggregate_soak_results as aggregator
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


class VirtualClock:
    """Strictly monotonic virtual time advanced only by the fake serial peer."""

    def __init__(self) -> None:
        self.now = 0.0

    def monotonic(self) -> float:
        return self.now

    def perf_counter(self) -> float:
        return self.now

    def sleep(self, seconds: float) -> None:
        if seconds < 0:
            raise AssertionError("virtual clock cannot sleep backward")
        self.now += seconds

    def advance(self, seconds: float) -> None:
        self.sleep(seconds)


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

    def __call__(self) -> AcceleratedSerial:
        live_reopen = (
            bool(self.ports) and self.device.state is constants.DeviceState.RUNNING
        )
        if live_reopen:
            self.device.inject_expected_pressure_loss()
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
        first = generator.render_programs(source, candidate)
        second = generator.render_programs(source, candidate)
        self.assertEqual(first, second)
        self.assertEqual(set(generator.OUTPUTS.values()), set(first))

        with tempfile.TemporaryDirectory(prefix="soak-generation-", dir=ROOT) as raw:
            output_directory = Path(raw)
            generated_output = io.StringIO()
            with redirect_stdout(generated_output):
                generated_exit = generator.main(
                    [
                        "--candidate",
                        str(generator.CANDIDATE_PATH),
                        "--output-directory",
                        str(output_directory),
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
                    ]
                )
            digests_after = {
                path.name: generator.sha256_bytes(path.read_bytes())
                for path in output_directory.iterdir()
            }

        self.assertEqual(0, generated_exit, generated_output.getvalue())
        self.assertEqual(0, checked_exit, checked_output.getvalue())
        self.assertEqual(digests_before, digests_after)
        self.assertEqual(3, len(digests_before))

    def test_each_generated_program_imports_in_isolation_without_numpy(self) -> None:
        for mode, filename in generator.OUTPUTS.items():
            path = GENERATED_DIRECTORY / filename
            source = path.read_text(encoding="utf-8")
            with self.subTest(mode=mode):
                self.assertEqual(ALLOWED_STANDALONE_IMPORTS, _imports(source))
                self.assertNotIn("numpy", source.lower())
                self.assertNotIn("from teensy_daq", source)
                self.assertNotIn("import teensy_daq", source)
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
                    self.assertEqual("cdc_close_reopen_pressure", negative["name"])
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


if __name__ == "__main__":
    unittest.main()
