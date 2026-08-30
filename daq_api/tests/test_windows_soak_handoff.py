"""Dedicated Windows soak handoff discovery, lifecycle, and parity tests."""

from __future__ import annotations

import ast
import ctypes
import io
import json
import math
import sys
import tempfile
import unittest
from collections.abc import Iterator
from contextlib import contextmanager, redirect_stderr, redirect_stdout
from dataclasses import replace
from pathlib import Path
from types import ModuleType, SimpleNamespace
from unittest.mock import patch

import serial
from teensy_daq import soak as installed_soak

from firmware.tests.test_soak_endurance_tools import (
    ACCELERATED_ADC_PAIR_RATE_HZ,
    ACCELERATED_GPIO_SAMPLE_RATE_HZ,
    ACCELERATED_PAYLOAD_BYTES_PER_SECOND,
    AcceleratedSerial,
    AcceleratedSoakDevice,
    VirtualClock,
    _load_module,
)
from firmware.tools import check_soak_conformance as conformance
from firmware.tools import generate_soak_programs as generator

ROOT = Path(__file__).resolve().parents[2]
PROTOCOL_FIXTURES = ROOT / "protocol/fixtures"
WINDOWS = _load_module(
    generator.WINDOWS_OUTPUT_PATH,
    "phase_12_windows_soak_handoff",
)
TARGET_HARDWARE_SERIAL = 20_512_460


class StableTracemalloc:
    """Small deterministic tracemalloc surface for fake-clock endurance runs."""

    def __init__(self, current: int = 4_096, peak: int = 8_192) -> None:
        self.current = current
        self.peak = peak
        self.tracing = False

    def start(self) -> None:
        self.tracing = True

    def stop(self) -> None:
        self.tracing = False

    def is_tracing(self) -> bool:
        return self.tracing

    def get_traced_memory(self) -> tuple[int, int]:
        return self.current, self.peak


@contextmanager
def _accelerated_environment(
    module: ModuleType,
    *,
    tracemalloc: StableTracemalloc | None = None,
) -> Iterator[None]:
    """Patch only host rates/resources; device INFO remains release-pinned."""

    real_tracemalloc = module.tracemalloc
    was_tracing = real_tracemalloc.is_tracing()
    if tracemalloc is not None and was_tracing:
        real_tracemalloc.stop()
    contexts = (
        patch.object(module, "ADC_PAIR_RATE_HZ", ACCELERATED_ADC_PAIR_RATE_HZ),
        patch.object(
            module,
            "GPIO_SAMPLE_RATE_HZ",
            ACCELERATED_GPIO_SAMPLE_RATE_HZ,
        ),
        patch.object(
            module,
            "TARGET_COMBINED_PAYLOAD_BYTES_PER_SECOND",
            ACCELERATED_PAYLOAD_BYTES_PER_SECOND,
        ),
        patch.object(module, "_current_rss_bytes", return_value=64 * 1024**2),
        patch.object(module, "_peak_rss_bytes", return_value=64 * 1024**2),
        patch.object(
            module,
            "_available_process_memory_bytes",
            return_value=512 * 1024**2,
        ),
        patch.object(module, "_cgroup_cpu_statistics", return_value={}),
    )
    try:
        with (
            contexts[0],
            contexts[1],
            contexts[2],
            contexts[3],
            contexts[4],
            contexts[5],
            contexts[6],
        ):
            if tracemalloc is None:
                yield
            else:
                with patch.object(module, "tracemalloc", tracemalloc):
                    yield
    finally:
        if was_tracing and not real_tracemalloc.is_tracing():
            real_tracemalloc.start()
        elif not was_tracing and real_tracemalloc.is_tracing():
            real_tracemalloc.stop()


def _candidate(
    port: str,
    *,
    serial_number: str | None = None,
    product: str | None = "Teensy DAQ",
) -> object:
    return WINDOWS.WindowsPortCandidate(
        port=port,
        vid=WINDOWS.TEENSY_USB_SERIAL_VID,
        pid=WINDOWS.TEENSY_USB_SERIAL_PID,
        serial_number=serial_number,
        product=product,
        manufacturer="PJRC",
        location=f"fixture-{port}",
        interface="CDC",
        description=product or "USB Serial",
    )


def _passing_probe(candidate: object, hardware_serial: int) -> object:
    return WINDOWS.WindowsProbeResult(
        candidate=candidate,
        observed_identity={"hardware_serial": hardware_serial},
        identity_mismatches={},
        latency_seconds=[0.001, 0.002],
        failure=None,
        close={
            "attempted": True,
            "completed": True,
            "timed_out": False,
            "error": None,
        },
    )


def _attached_windows_report(
    module: ModuleType,
    *,
    host: dict[str, object],
    process_rss: dict[str, object] | None,
    duration: float = 3_600.0,
    mode: str = "combined",
    smoke: bool = False,
    diagnostic_identity_override: bool = False,
    overall_pass: bool = True,
    exact_identity: bool = True,
) -> dict[str, object]:
    settings = module.windows_runtime_settings(
        mode,
        duration,
        diagnostic_identity_override=diagnostic_identity_override,
    )
    manifest = module.GENERATED_CONFIG.get("validation_manifest")
    if not isinstance(manifest, dict):
        raise TypeError("generated validation manifest is unavailable")
    expected_info = manifest.get("expected_info")
    if not isinstance(expected_info, dict):
        raise TypeError("generated validation manifest INFO contract is unavailable")
    observed_identity = dict(expected_info)
    identity_mismatches: dict[str, dict[str, object]] = {}
    if not exact_identity:
        observed_identity["build_id"] = "tdaq-diagnostic-other"
        identity_mismatches["build_id"] = {
            "expected": expected_info["build_id"],
            "actual": observed_identity["build_id"],
        }
    candidate = module.WindowsPortCandidate(
        port="COM10",
        vid=module.TEENSY_USB_SERIAL_VID,
        pid=module.TEENSY_USB_SERIAL_PID,
        serial_number=str(settings.hardware_serial),
        product=module.TEENSY_DAQ_PRODUCT,
        manufacturer="PJRC",
        location="fixture-location",
        interface="CDC",
        description="Teensy DAQ",
    )
    probe = module.WindowsProbeResult(
        candidate=candidate,
        observed_identity=observed_identity,
        identity_mismatches=identity_mismatches,
        latency_seconds=[0.001, 0.002],
        failure=None,
        close={
            "attempted": True,
            "completed": True,
            "timed_out": False,
            "error": None,
        },
    )
    result = module.windows_failure_result(
        module.SoakFailure("fixture", "intentional fixture failure"),
        settings=settings,
        mode=mode,
    )
    if overall_pass:
        result.update(
            {
                "result": "PASS",
                "failure": None,
                "observed_identity": observed_identity,
                "cleanup": {"attempted": False, "normal_close": True},
            }
        )
    if process_rss is not None:
        result["metrics"] = {"memory": {"process_rss": process_rss}}
    parser_arguments = ["--mode", mode, "--output", "unused"]
    if smoke:
        parser_arguments.append("--smoke")
    else:
        parser_arguments.extend(("--duration", str(duration)))
    if diagnostic_identity_override:
        parser_arguments.append("--diagnostic-identity-override")
    arguments = module.build_windows_parser().parse_args(parser_arguments)
    arguments.hardware_serial = settings.hardware_serial
    with patch.object(
        module,
        "windows_host_identity",
        return_value=host,
    ) as host_identity:
        module.attach_windows_evidence(
            result,
            arguments=arguments,
            duration=duration,
            candidates=(candidate,),
            probes=(probe,),
            selected=candidate,
            lifecycle=[],
        )
    if host_identity.call_count != 1:
        raise AssertionError("host identity must be captured exactly once per report")
    windows = result.get("windows")
    if not isinstance(windows, dict) or windows.get("host") is not host:
        raise AssertionError("grading and report must share one host identity snapshot")
    return result


def _failed_probe(candidate: object, message: str) -> object:
    return WINDOWS.WindowsProbeResult(
        candidate=candidate,
        observed_identity=None,
        identity_mismatches={},
        latency_seconds=[],
        failure={
            "category": "serial_open",
            "type": "SerialException",
            "message": message,
        },
        close={
            "attempted": False,
            "completed": False,
            "timed_out": False,
            "error": None,
        },
    )


def _metadata(
    port: str,
    vid: int,
    pid: int,
    *,
    serial_number: str | None,
    product: str | None,
) -> SimpleNamespace:
    return SimpleNamespace(
        device=port,
        vid=vid,
        pid=pid,
        serial_number=serial_number,
        product=product,
        manufacturer="PJRC" if vid == 0x16C0 else "Unrelated",
        location=f"usb-{port}",
        interface="CDC",
        description=product or "USB Serial",
    )


class PartialWriteSerial(AcceleratedSerial):
    """Deliver each request to the established device parser in short writes."""

    def __init__(
        self,
        device: AcceleratedSoakDevice,
        clock: VirtualClock,
    ) -> None:
        super().__init__(device, clock, startup_noise=False)
        self.write_sizes = (1, 2, 5, 7, 11)
        self.write_count = 0

    def write(self, data: bytes | bytearray | memoryview) -> int:
        maximum = self.write_sizes[self.write_count % len(self.write_sizes)]
        self.write_count += 1
        consumed = min(maximum, len(data))
        super().write(bytes(data[:consumed]))
        return consumed


class DelayedStatusSerial(AcceleratedSerial):
    """Advance virtual time before returning each queued STATUS response."""

    def __init__(
        self,
        device: AcceleratedSoakDevice,
        clock: VirtualClock,
    ) -> None:
        super().__init__(device, clock, startup_noise=False)
        self.status_delay_pending = False

    def write(self, data: bytes | bytearray | memoryview) -> int:
        wire = bytes(data)
        kind = WINDOWS.HEADER.unpack_from(wire)[2]
        written = super().write(wire)
        self.status_delay_pending = kind == WINDOWS.GET_STATUS_REQUEST
        return written

    def read(self, size: int = 1) -> bytes:
        if self.status_delay_pending and self.pending:
            self.clock.advance(0.037)
            self.status_delay_pending = False
        return super().read(size)


class DropStopSerial(AcceleratedSerial):
    """Apply STOP at the device but discard every STOP response."""

    def write(self, data: bytes | bytearray | memoryview) -> int:
        wire = bytes(data)
        kind = WINDOWS.HEADER.unpack_from(wire)[2]
        responses = self.device.receive(wire)
        if kind != WINDOWS.STOP_REQUEST:
            for response in responses:
                self.pending.extend(response)
        for trailing in self.device.trailing_data:
            self.pending.extend(trailing)
        self.device.trailing_data.clear()
        return len(wire)


class DisconnectOnceSerial(AcceleratedSerial):
    """Raise one Windows-shaped read error during a running stream."""

    def __init__(
        self,
        device: AcceleratedSoakDevice,
        clock: VirtualClock,
    ) -> None:
        super().__init__(device, clock, startup_noise=False)
        self.disconnected = False

    def read(self, size: int = 1) -> bytes:
        if (
            not self.disconnected
            and self.device.state.value == WINDOWS.STATE_RUNNING
            and self.clock.monotonic() >= 1.0
        ):
            self.disconnected = True
            raise OSError("fixture device disconnected")
        return super().read(size)


class InterruptOnceSerial(AcceleratedSerial):
    """Raise Ctrl+C once, then allow bounded cleanup exchanges to finish."""

    def __init__(
        self,
        device: AcceleratedSoakDevice,
        clock: VirtualClock,
    ) -> None:
        super().__init__(device, clock, startup_noise=False)
        self.interrupted = False

    def read(self, size: int = 1) -> bytes:
        if (
            not self.interrupted
            and self.device.state.value == WINDOWS.STATE_RUNNING
            and self.clock.monotonic() >= 1.0
        ):
            self.interrupted = True
            raise KeyboardInterrupt
        return super().read(size)


class WindowsDiscoveryTests(unittest.TestCase):
    def test_metadata_filter_selection_and_com_renumbering(self) -> None:
        records = [
            _metadata(
                "COM10",
                0x16C0,
                0x0483,
                serial_number=None,
                product=None,
            ),
            _metadata(
                "COM1",
                0x16C0,
                0x0483,
                serial_number=str(TARGET_HARDWARE_SERIAL),
                product="Teensy DAQ",
            ),
            _metadata(
                "COM2",
                0x1234,
                0x5678,
                serial_number="busy-port",
                product="Unrelated busy device",
            ),
            _metadata(
                "COM3",
                0x9999,
                0x0001,
                serial_number="access-denied-port",
                product="Unrelated protected device",
            ),
            _metadata(
                "/dev/ttyACM0",
                0x16C0,
                0x0483,
                serial_number=str(TARGET_HARDWARE_SERIAL),
                product="Teensy DAQ",
            ),
        ]
        candidates = WINDOWS.enumerate_windows_candidates(lambda: records)

        self.assertEqual(["COM1", "COM10"], [item.port for item in candidates])
        self.assertEqual("Teensy DAQ", candidates[0].product)
        self.assertIsNone(candidates[1].product)
        probes = (
            _passing_probe(candidates[0], 11_111_111),
            _passing_probe(candidates[1], TARGET_HARDWARE_SERIAL),
        )
        selected = WINDOWS.select_windows_candidate(
            probes,
            hardware_serial=TARGET_HARDWARE_SERIAL,
        )
        self.assertEqual("COM10", selected.port)

        renumbered = _candidate("COM7", serial_number=None, product=None)
        selected_after_renumber = WINDOWS.select_windows_candidate(
            (
                _passing_probe(_candidate("COM10"), 11_111_111),
                _passing_probe(renumbered, TARGET_HARDWARE_SERIAL),
            ),
            hardware_serial=TARGET_HARDWARE_SERIAL,
        )
        self.assertEqual("COM7", selected_after_renumber.port)

    def test_busy_and_access_denied_ports_fail_bounded_open(self) -> None:
        errors = (
            serial.SerialException("port is busy"),
            PermissionError(13, "Access is denied", "COM10"),
        )
        for error in errors:
            with self.subTest(error=type(error).__name__):
                with (
                    patch.object(WINDOWS.serial, "Serial", side_effect=error),
                    self.assertRaises(WINDOWS.SoakFailure) as caught,
                ):
                    WINDOWS.open_windows_serial(
                        "COM10",
                        open_timeout_seconds=0.5,
                    )
                self.assertEqual("serial_open", caught.exception.category)
                self.assertIn("COM10", str(caught.exception))

    def test_busy_teensy_does_not_block_matching_hardware_serial(self) -> None:
        busy = _candidate("COM1", serial_number=str(TARGET_HARDWARE_SERIAL))
        matching = _candidate("COM10", serial_number=None, product=None)
        probes = (
            _failed_probe(busy, "Access is denied because the port is busy"),
            _passing_probe(matching, TARGET_HARDWARE_SERIAL),
        )

        selected = WINDOWS.select_windows_candidate(
            probes,
            hardware_serial=TARGET_HARDWARE_SERIAL,
        )

        self.assertEqual("COM10", selected.port)
        self.assertEqual("serial_open", probes[0].failure["category"])


class WindowsWireAndFaultTests(unittest.TestCase):
    def test_fragmented_multi_frame_reads_partial_writes_and_delayed_status(
        self,
    ) -> None:
        transcript = (PROTOCOL_FIXTURES / "adc-data.bin").read_bytes() + (
            PROTOCOL_FIXTURES / "gpio-data.bin"
        ).read_bytes()
        parser = WINDOWS.FrameParser(maximum_input_bytes=WINDOWS.DATA_FRAME_BYTES)
        pattern = (1, 7, 31, 257, 4_096, 17)
        frames = []
        offset = 0
        pattern_index = 0
        while offset < len(transcript):
            count = pattern[pattern_index % len(pattern)]
            frames.extend(parser.feed(transcript[offset : offset + count]))
            offset += count
            pattern_index += 1
        self.assertEqual(
            [WINDOWS.ADC_DATA, WINDOWS.GPIO_DATA],
            [frame.kind for frame in frames],
        )
        self.assertEqual(2, len(WINDOWS.FrameParser().feed(transcript)))
        self.assertEqual(0, parser.errors)
        self.assertEqual(b"", bytes(parser.buffer))

        settings = WINDOWS.windows_runtime_settings("combined", 10.0)
        partial_clock = VirtualClock()
        partial_device = AcceleratedSoakDevice(settings, installed_soak)
        partial_port = PartialWriteSerial(partial_device, partial_clock)
        partial_link = WINDOWS.SerialLink(
            partial_port,
            partial_clock,
            read_bytes=settings.serial_read_bytes,
        )
        info_frame, _latency = partial_link.exchange(WINDOWS.INFO_REQUEST)
        info = WINDOWS.decode_info(info_frame)
        self.assertEqual(TARGET_HARDWARE_SERIAL, info["hardware_serial"])
        self.assertGreater(partial_port.write_count, 5)

        delayed_clock = VirtualClock()
        delayed_device = AcceleratedSoakDevice(settings, installed_soak)
        delayed_port = DelayedStatusSerial(delayed_device, delayed_clock)
        delayed_link = WINDOWS.SerialLink(
            delayed_port,
            delayed_clock,
            read_bytes=settings.serial_read_bytes,
        )
        status_frame, latency = delayed_link.exchange(WINDOWS.GET_STATUS_REQUEST)
        status = WINDOWS.decode_status(status_frame)
        self.assertEqual(WINDOWS.STATE_IDLE, status.device_state)
        self.assertAlmostEqual(0.038, latency, places=9)

    def test_wrong_identity_checksum_corruption_and_sequence_gap_are_classified(
        self,
    ) -> None:
        settings = WINDOWS.windows_runtime_settings("combined", 10.0)
        observed = dict(settings.expected_info)
        observed.update(
            {
                "device_state": WINDOWS.STATE_IDLE,
                "applied_stream_mask": WINDOWS.STREAM_NONE,
                "applied_source": WINDOWS.SOURCE_HARDWARE,
            }
        )
        for field, value in (
            ("build_id", "tdaq-wrong-build"),
            ("supported_checksum_mask", 0),
            ("data_checksum_algorithm", 2),
        ):
            wrong = dict(observed)
            wrong[field] = value
            with self.subTest(field=field):
                with self.assertRaises(WINDOWS.SoakFailure) as caught:
                    WINDOWS.validate_info_identity(
                        wrong,
                        settings,
                        expected_state=WINDOWS.STATE_IDLE,
                    )
                self.assertEqual("identity", caught.exception.category)

        vector = WINDOWS.soak_conformance_vector()
        self.assertEqual(
            ("FAIL", "checksum_corruption"),
            (
                vector["grades"]["checksum_corruption"]["result"],
                vector["grades"]["checksum_corruption"]["failure_category"],
            ),
        )
        self.assertEqual(
            ("FAIL", "source_gap"),
            (
                vector["grades"]["source_gap"]["result"],
                vector["grades"]["source_gap"]["failure_category"],
            ),
        )
        self.assertEqual(
            ("FAIL", "pattern_error"),
            (
                vector["grades"]["pattern_error"]["result"],
                vector["grades"]["pattern_error"]["failure_category"],
            ),
        )

    def test_counter_disagreement_disconnect_ctrl_c_and_stop_failure_cleanup(
        self,
    ) -> None:
        cases: list[tuple[str, int, dict[str, object], object, object]] = []

        counter_clock = VirtualClock()
        counter_settings = WINDOWS.windows_runtime_settings("combined", 5.0)
        counter_device = AcceleratedSoakDevice(counter_settings, installed_soak)
        healthy_status = counter_device.status

        def disagreeing_status() -> object:
            status = healthy_status()
            if counter_device.state.value == WINDOWS.STATE_RUNNING:
                return replace(status, packet_pool_exhaustions=1)
            return status

        counter_port = AcceleratedSerial(
            counter_device,
            counter_clock,
            startup_noise=False,
        )
        with (
            _accelerated_environment(WINDOWS),
            patch.object(counter_device, "status", side_effect=disagreeing_status),
            redirect_stdout(io.StringIO()),
        ):
            code, result = WINDOWS.run_generated(
                counter_settings,
                lambda: counter_port,
                clock=counter_clock,
            )
        cases.append(("counter", code, result, counter_device, counter_port))

        disconnect_clock = VirtualClock()
        disconnect_settings = WINDOWS.windows_runtime_settings("combined", 5.0)
        disconnect_device = AcceleratedSoakDevice(
            disconnect_settings,
            installed_soak,
        )
        disconnect_raw = DisconnectOnceSerial(disconnect_device, disconnect_clock)
        disconnect_port = WINDOWS.BoundedWindowsSerial("COM10", disconnect_raw)
        with _accelerated_environment(WINDOWS), redirect_stdout(io.StringIO()):
            code, result = WINDOWS.run_generated(
                disconnect_settings,
                lambda: disconnect_port,
                clock=disconnect_clock,
            )
        cases.append(("disconnect", code, result, disconnect_device, disconnect_port))

        interrupt_clock = VirtualClock()
        interrupt_settings = WINDOWS.windows_runtime_settings("combined", 5.0)
        interrupt_device = AcceleratedSoakDevice(interrupt_settings, installed_soak)
        interrupt_port = InterruptOnceSerial(interrupt_device, interrupt_clock)
        with _accelerated_environment(WINDOWS), redirect_stdout(io.StringIO()):
            code, result = WINDOWS.run_generated(
                interrupt_settings,
                lambda: interrupt_port,
                clock=interrupt_clock,
            )
        cases.append(("ctrl_c", code, result, interrupt_device, interrupt_port))

        stop_clock = VirtualClock()
        stop_settings = WINDOWS.windows_runtime_settings("combined", 5.0)
        stop_device = AcceleratedSoakDevice(stop_settings, installed_soak)
        stop_port = DropStopSerial(stop_device, stop_clock, startup_noise=False)
        with _accelerated_environment(WINDOWS), redirect_stdout(io.StringIO()):
            code, result = WINDOWS.run_generated(
                stop_settings,
                lambda: stop_port,
                clock=stop_clock,
            )
        cases.append(("stop", code, result, stop_device, stop_port))

        expected = {
            "counter": ("counter_disagreement", "SoakFailure"),
            "disconnect": ("disconnect", "SoakFailure"),
            "ctrl_c": ("program", "KeyboardInterrupt"),
            "stop": ("timeout", "DeadlineExpired"),
        }
        for name, code, result, device, port in cases:
            with self.subTest(name=name):
                self.assertEqual(1, code)
                self.assertEqual("FAIL", result["result"])
                self.assertEqual(expected[name][0], result["failure"]["category"])
                self.assertEqual(expected[name][1], result["failure"]["type"])
                self.assertTrue(result["cleanup"]["attempted"])
                self.assertEqual(WINDOWS.STATE_IDLE, device.state.value)
                if isinstance(port, WINDOWS.BoundedWindowsSerial):
                    self.assertTrue(port.close_summary()["completed"])
                else:
                    self.assertTrue(port.closed)


class WindowsProcessMemoryTests(unittest.TestCase):
    def test_native_api_reports_exact_working_sets_and_fails_closed(self) -> None:
        counters_type = WINDOWS._WindowsProcessMemoryCounters
        counters_size = ctypes.sizeof(counters_type)
        current_bytes = 73_400_320
        peak_bytes = 91_226_112
        calls: list[tuple[object, int, int]] = []

        def populate_counters(
            process: object,
            counters_pointer: object,
            structure_size: int,
        ) -> int:
            counters = ctypes.cast(
                counters_pointer,
                ctypes.POINTER(counters_type),
            ).contents
            calls.append((process, structure_size, counters.cb))
            counters.WorkingSetSize = current_bytes
            counters.PeakWorkingSetSize = peak_bytes
            return 1

        api = WINDOWS._WindowsProcessMemoryApi(
            get_current_process=lambda: 0xCAFE,
            get_process_memory_info=populate_counters,
        )
        with (
            patch.object(WINDOWS.sys, "platform", "win32"),
            patch.object(WINDOWS, "_WINDOWS_PROCESS_MEMORY_API", api),
        ):
            self.assertEqual(current_bytes, WINDOWS._current_rss_bytes())
            self.assertEqual(peak_bytes, WINDOWS._peak_rss_bytes())

        self.assertEqual(
            [(0xCAFE, counters_size, counters_size)] * 2,
            calls,
        )
        self.assertEqual(
            [
                ("cb", ctypes.c_uint32),
                ("PageFaultCount", ctypes.c_uint32),
                ("PeakWorkingSetSize", ctypes.c_size_t),
                ("WorkingSetSize", ctypes.c_size_t),
                ("QuotaPeakPagedPoolUsage", ctypes.c_size_t),
                ("QuotaPagedPoolUsage", ctypes.c_size_t),
                ("QuotaPeakNonPagedPoolUsage", ctypes.c_size_t),
                ("QuotaNonPagedPoolUsage", ctypes.c_size_t),
                ("PagefileUsage", ctypes.c_size_t),
                ("PeakPagefileUsage", ctypes.c_size_t),
            ],
            counters_type._fields_,
        )

        def raise_os_error(*_arguments: object) -> object:
            raise OSError("fixture API failure")

        def memory_result(
            *,
            succeeded: int = 1,
            current: int = current_bytes,
            peak: int = peak_bytes,
            reported_size: int = counters_size,
        ) -> object:
            def get_process_memory_info(
                _process: object,
                counters_pointer: object,
                _structure_size: int,
            ) -> int:
                counters = ctypes.cast(
                    counters_pointer,
                    ctypes.POINTER(counters_type),
                ).contents
                counters.cb = reported_size
                counters.WorkingSetSize = current
                counters.PeakWorkingSetSize = peak
                return succeeded

            return get_process_memory_info

        invalid_apis = (
            (
                "null-process",
                WINDOWS._WindowsProcessMemoryApi(
                    get_current_process=lambda: 0,
                    get_process_memory_info=populate_counters,
                ),
            ),
            (
                "process-call-error",
                WINDOWS._WindowsProcessMemoryApi(
                    get_current_process=raise_os_error,
                    get_process_memory_info=populate_counters,
                ),
            ),
            (
                "memory-call-error",
                WINDOWS._WindowsProcessMemoryApi(
                    get_current_process=lambda: 0xCAFE,
                    get_process_memory_info=raise_os_error,
                ),
            ),
            (
                "memory-call-failed",
                WINDOWS._WindowsProcessMemoryApi(
                    get_current_process=lambda: 0xCAFE,
                    get_process_memory_info=memory_result(succeeded=0),
                ),
            ),
            (
                "structure-size-mismatch",
                WINDOWS._WindowsProcessMemoryApi(
                    get_current_process=lambda: 0xCAFE,
                    get_process_memory_info=memory_result(reported_size=0),
                ),
            ),
            (
                "peak-below-current",
                WINDOWS._WindowsProcessMemoryApi(
                    get_current_process=lambda: 0xCAFE,
                    get_process_memory_info=memory_result(
                        current=current_bytes,
                        peak=current_bytes - 1,
                    ),
                ),
            ),
        )
        for name, invalid_api in invalid_apis:
            with self.subTest(failure=name):
                self.assertIsNone(WINDOWS._windows_process_memory_bytes(invalid_api))

        with patch.object(WINDOWS, "_WINDOWS_PROCESS_MEMORY_API", None):
            self.assertIsNone(WINDOWS._windows_process_memory_bytes())

    def test_non_windows_rss_delegates_without_native_api_calls(self) -> None:
        with (
            patch.object(WINDOWS.sys, "platform", "linux"),
            patch.object(
                WINDOWS,
                "_canonical_current_rss_bytes",
                return_value=111_222_333,
            ) as current_rss,
            patch.object(
                WINDOWS,
                "_canonical_peak_rss_bytes",
                return_value=444_555_666,
            ) as peak_rss,
            patch.object(WINDOWS, "_windows_process_memory_bytes") as native_rss,
        ):
            self.assertEqual(111_222_333, WINDOWS._current_rss_bytes())
            self.assertEqual(444_555_666, WINDOWS._peak_rss_bytes())

        current_rss.assert_called_once_with()
        peak_rss.assert_called_once_with()
        native_rss.assert_not_called()

    def test_memory_tracker_records_numeric_rss_with_bounded_evidence(self) -> None:
        mib = 1024**2
        current_samples = iter((64 * mib, 65 * mib, 66 * mib))
        peak_samples = iter((70 * mib, 72 * mib, 74 * mib, 80 * mib))

        def current_rss() -> int:
            return next(current_samples, 66 * mib)

        def peak_rss() -> int:
            return next(peak_samples, 80 * mib)

        tracing = StableTracemalloc()
        streaming_samples = WINDOWS.MAX_COUNTER_SAMPLES + 3
        with (
            patch.object(WINDOWS, "tracemalloc", tracing),
            patch.object(WINDOWS, "_current_rss_bytes", side_effect=current_rss),
            patch.object(WINDOWS, "_peak_rss_bytes", side_effect=peak_rss),
            patch.object(
                WINDOWS,
                "_available_process_memory_bytes",
                return_value=512 * mib,
            ),
        ):
            tracker = WINDOWS.MemoryTracker()
            tracker.begin_streaming()
            for _index in range(streaming_samples):
                tracker.sample_streaming(checkpoint=True)
            tracker.end_streaming()
            memory = tracker.summary()

        self.assertEqual(
            {
                "baseline_bytes": 64 * mib,
                "final_bytes": 66 * mib,
                "maximum_current_bytes": 66 * mib,
                "peak_bytes": 80 * mib,
                "growth_bytes": 10 * mib,
            },
            memory["process_rss"],
        )
        self.assertEqual(streaming_samples + 3, memory["sample_count"])
        self.assertEqual(
            streaming_samples,
            memory["coverage"]["streaming_samples"],
        )
        self.assertEqual(1, memory["coverage"]["streaming_windows"])
        self.assertEqual(
            WINDOWS.MAX_COUNTER_SAMPLES,
            len(memory["bounded_checkpoints"]),
        )
        self.assertTrue(tracing.is_tracing())

    def test_unavailable_windows_rss_remains_none_and_is_not_release_eligible(
        self,
    ) -> None:
        tracing = StableTracemalloc()
        with (
            patch.object(WINDOWS.sys, "platform", "win32"),
            patch.object(WINDOWS, "_WINDOWS_PROCESS_MEMORY_API", None),
            patch.object(WINDOWS, "tracemalloc", tracing),
            patch.object(
                WINDOWS,
                "_available_process_memory_bytes",
                return_value=None,
            ),
        ):
            memory = WINDOWS.MemoryTracker().summary()

        process_rss = memory["process_rss"]
        self.assertEqual(
            {
                "baseline_bytes": None,
                "final_bytes": None,
                "maximum_current_bytes": None,
                "peak_bytes": None,
                "growth_bytes": None,
            },
            process_rss,
        )
        result = _attached_windows_report(
            WINDOWS,
            host={"system": "Windows", "sys_platform": "win32"},
            process_rss=process_rss,
        )
        windows = result["windows"]
        requirements = windows["release_requirements"]
        self.assertEqual("PASS", result["result"])
        self.assertEqual("release", windows["profile"])
        self.assertFalse(windows["release_eligible"])
        self.assertFalse(requirements["process_rss_baseline_valid"])
        self.assertFalse(requirements["process_rss_peak_valid"])
        self.assertFalse(requirements["process_rss_growth_valid"])
        self.assertTrue(
            any(
                "process-RSS evidence is unavailable" in reason
                for reason in windows["validation_reasons"]
            )
        )


class WindowsOneHourProfileTests(unittest.TestCase):
    def test_complete_3600_second_profile_has_exact_bounded_arithmetic(self) -> None:
        clock = VirtualClock()
        settings = WINDOWS.windows_runtime_settings("combined", 3_600.0)
        device = AcceleratedSoakDevice(settings, installed_soak)
        port = AcceleratedSerial(device, clock, startup_noise=True)
        stable_tracing = StableTracemalloc()

        with (
            _accelerated_environment(WINDOWS, tracemalloc=stable_tracing),
            redirect_stdout(io.StringIO()),
        ):
            exit_code, result = WINDOWS.run_generated(
                settings,
                lambda: port,
                clock=clock,
            )

        self.assertEqual(0, exit_code, repr(result.get("failure")))
        self.assertEqual("PASS", result["result"])
        self.assertEqual("physical-combined", result["mode"])
        self.assertEqual(3_600.0, settings.measured_duration_seconds)
        self.assertEqual(1, result["metrics"]["epoch_count"])
        epoch = result["epochs"][0]
        timed = epoch["timed"]
        metrics = result["metrics"]

        self.assertEqual(
            timed["adc_frames"] * WINDOWS.ADC_PAIRS_PER_FRAME,
            timed["adc_pairs"],
        )
        self.assertEqual(
            timed["gpio_frames"] * WINDOWS.GPIO_SAMPLES_PER_FRAME,
            timed["gpio_samples"],
        )
        self.assertEqual(
            timed["adc_pairs"] * WINDOWS.ADC_BYTES_PER_PAIR + timed["gpio_samples"],
            timed["payload_bytes"],
        )
        self.assertEqual(
            (timed["adc_frames"] + timed["gpio_frames"]) * WINDOWS.DATA_FRAME_BYTES,
            timed["framed_bytes"],
        )
        self.assertEqual(timed["payload_bytes"], metrics["payload_bytes"])
        self.assertEqual(timed["framed_bytes"], metrics["framed_bytes"])

        target_adc_pairs = ACCELERATED_ADC_PAIR_RATE_HZ * 3_600.0
        target_gpio_samples = ACCELERATED_GPIO_SAMPLE_RATE_HZ * 3_600.0
        target_payload_bytes = ACCELERATED_PAYLOAD_BYTES_PER_SECOND * 3_600.0
        self.assertTrue(
            math.isclose(timed["adc_pairs"], target_adc_pairs, rel_tol=0.01)
        )
        self.assertTrue(
            math.isclose(timed["gpio_samples"], target_gpio_samples, rel_tol=0.01)
        )
        self.assertTrue(
            math.isclose(timed["payload_bytes"], target_payload_bytes, rel_tol=0.01)
        )

        status_latency = metrics["latency"]["status"]
        self.assertEqual(3_501, status_latency["count"])
        self.assertLessEqual(
            status_latency["p99_seconds"],
            WINDOWS.STATUS_P99_LIMIT_SECONDS,
        )
        self.assertLessEqual(
            status_latency["maximum_seconds"],
            WINDOWS.STATUS_MAXIMUM_LIMIT_SECONDS,
        )
        self.assertGreater(epoch["status"]["count"], status_latency["count"])

        queues = metrics["maximum_queues"]
        queue_limits = {
            "packet_owned_high_water": WINDOWS.PACKET_BUFFER_COUNT,
            "packet_ready_high_water": WINDOWS.PACKET_QUEUE_CAPACITY,
            "packet_transmit_high_water": WINDOWS.PACKET_QUEUE_CAPACITY,
            "adc_raw_ready_high_water": WINDOWS.ADC_RAW_RING_DEPTH,
            "gpio_raw_ready_high_water": WINDOWS.GPIO_RAW_RING_DEPTH,
            "gpio_packed_ready_high_water": WINDOWS.GPIO_PACKED_RING_DEPTH,
            "usb_command_queue_high_water": WINDOWS.COMMAND_QUEUE_CAPACITY,
            "usb_response_queue_high_water": WINDOWS.RESPONSE_QUEUE_CAPACITY,
        }
        for name, limit in queue_limits.items():
            with self.subTest(queue=name):
                self.assertGreaterEqual(queues[name], 0)
                self.assertLessEqual(queues[name], limit)

        memory = metrics["memory"]
        self.assertEqual(0, memory["tracemalloc"]["growth_bytes"])
        self.assertEqual(0, memory["process_rss"]["growth_bytes"])
        traced_checkpoints = [
            item["traced_bytes"]
            for item in memory["bounded_checkpoints"]
            if item["traced_bytes"] is not None
        ]
        rss_checkpoints = [
            item["rss_bytes"]
            for item in memory["bounded_checkpoints"]
            if item["rss_bytes"] is not None
        ]
        self.assertEqual([stable_tracing.current], sorted(set(traced_checkpoints)))
        self.assertEqual([64 * 1024**2], sorted(set(rss_checkpoints)))
        self.assertEqual(1, memory["coverage"]["streaming_windows"])
        self.assertLessEqual(
            len(memory["bounded_checkpoints"]),
            WINDOWS.MAX_COUNTER_SAMPLES,
        )
        self.assertEqual(0, epoch["parser"]["errors"])
        self.assertEqual(0, epoch["parser"]["buffered_bytes"])
        self.assertEqual(WINDOWS.STATE_IDLE, device.state.value)
        self.assertTrue(port.closed)


class WindowsReportParityAndCompatibilityTests(unittest.TestCase):
    def test_release_requirements_fail_closed_and_preserve_entry_point_parity(
        self,
    ) -> None:
        host = {
            "system": "Windows",
            "sys_platform": "win32",
            "snapshot": "one-call-fixture",
        }
        process_rss = {
            "baseline_bytes": 64 * 1024**2,
            "peak_bytes": 72 * 1024**2,
            "growth_bytes": 8 * 1024**2,
        }
        expected_requirements = {
            "physical_combined_mode",
            "exact_3600_second_duration",
            "non_smoke",
            "diagnostic_identity_override_disabled",
            "native_windows_host",
            "overall_pass",
            "exact_manifest_device_identity",
            "process_rss_baseline_valid",
            "process_rss_peak_valid",
            "process_rss_growth_valid",
            "process_rss_growth_within_limit",
        }
        reports = [
            _attached_windows_report(
                module,
                host=dict(host),
                process_rss=dict(process_rss),
            )
            for module in (WINDOWS, installed_soak)
        ]
        graded = []
        for report in reports:
            windows = report["windows"]
            self.assertEqual("release", windows["profile"])
            requirements = windows["release_requirements"]
            self.assertEqual(expected_requirements, set(requirements))
            self.assertTrue(all(requirements.values()))
            self.assertTrue(windows["release_eligible"])
            self.assertEqual(
                all(requirements.values()),
                windows["release_eligible"],
            )
            graded.append(
                {
                    name: windows[name]
                    for name in (
                        "profile",
                        "release_eligible",
                        "release_requirements",
                        "validation_reasons",
                    )
                }
            )
        self.assertEqual(graded[0], graded[1])

    def test_release_classification_matrix(self) -> None:
        mib = 1024**2
        native_windows: dict[str, object] = {
            "system": "Windows",
            "sys_platform": "win32",
        }
        complete_rss: dict[str, object] = {
            "baseline_bytes": 64 * mib,
            "peak_bytes": 72 * mib,
            "growth_bytes": 8 * mib,
        }
        requirement_names = (
            "physical_combined_mode",
            "exact_3600_second_duration",
            "non_smoke",
            "diagnostic_identity_override_disabled",
            "native_windows_host",
            "overall_pass",
            "exact_manifest_device_identity",
            "process_rss_baseline_valid",
            "process_rss_peak_valid",
            "process_rss_growth_valid",
            "process_rss_growth_within_limit",
        )

        def classification_case(
            name: str,
            *,
            reason: str,
            host: dict[str, object] = native_windows,
            process_rss: dict[str, object] = complete_rss,
            duration: float = WINDOWS.WINDOWS_DEFAULT_DURATION_SECONDS,
            mode: str = "combined",
            smoke: bool = False,
            diagnostic_identity_override: bool = False,
            overall_pass: bool = True,
            exact_identity: bool = True,
            profile: str = "release",
            release_eligible: bool = False,
            failed_requirements: frozenset[str] = frozenset(),
        ) -> SimpleNamespace:
            return SimpleNamespace(**locals())

        non_release_profile_reason = (
            "exact 3,600-second non-smoke physical-combined run"
        )
        host_cases: tuple[tuple[str, dict[str, object]], ...] = (
            ("linux", {"system": "Linux", "sys_platform": "linux"}),
            ("macos", {"system": "Darwin", "sys_platform": "darwin"}),
            ("unknown", {"system": None, "sys_platform": None}),
        )
        cases: tuple[SimpleNamespace, ...] = (
            classification_case(
                "native-windows-release",
                release_eligible=True,
                reason="complete numeric process-RSS evidence remained within",
            ),
            *(
                classification_case(
                    f"{name}-host",
                    host=host,
                    profile="diagnostic",
                    failed_requirements=frozenset({"native_windows_host"}),
                    reason="native Windows host identity",
                )
                for name, host in host_cases
            ),
            classification_case(
                "missing-rss",
                process_rss={
                    "baseline_bytes": 64 * mib,
                    "peak_bytes": 72 * mib,
                },
                failed_requirements=frozenset(
                    {
                        "process_rss_growth_valid",
                        "process_rss_growth_within_limit",
                    }
                ),
                reason="process-RSS evidence is unavailable",
            ),
            classification_case(
                "malformed-rss",
                process_rss={
                    "baseline_bytes": "64 MiB",
                    "peak_bytes": 72 * mib,
                    "growth_bytes": 8 * mib,
                },
                failed_requirements=frozenset({"process_rss_baseline_valid"}),
                reason="process-RSS evidence is invalid",
            ),
            classification_case(
                "negative-rss",
                process_rss={
                    "baseline_bytes": -1,
                    "peak_bytes": 72 * mib,
                    "growth_bytes": 8 * mib,
                },
                failed_requirements=frozenset({"process_rss_baseline_valid"}),
                reason="process-RSS evidence is invalid",
            ),
            classification_case(
                "non-finite-rss",
                process_rss={
                    "baseline_bytes": 64 * mib,
                    "peak_bytes": float("inf"),
                    "growth_bytes": 8 * mib,
                },
                failed_requirements=frozenset({"process_rss_peak_valid"}),
                reason="process-RSS evidence is invalid",
            ),
            classification_case(
                "over-limit-rss",
                process_rss={
                    "baseline_bytes": 64 * mib,
                    "peak_bytes": 100 * mib,
                    "growth_bytes": WINDOWS.MAX_RSS_GROWTH_BYTES + 1,
                },
                failed_requirements=frozenset({"process_rss_growth_within_limit"}),
                reason="process-RSS growth",
            ),
            classification_case(
                "short-duration",
                duration=3_599.0,
                profile="diagnostic",
                failed_requirements=frozenset({"exact_3600_second_duration"}),
                reason=non_release_profile_reason,
            ),
            classification_case(
                "smoke",
                smoke=True,
                profile="diagnostic",
                failed_requirements=frozenset({"non_smoke"}),
                reason=non_release_profile_reason,
            ),
            classification_case(
                "synthetic",
                mode="synthetic",
                profile="diagnostic",
                failed_requirements=frozenset({"physical_combined_mode"}),
                reason=non_release_profile_reason,
            ),
            classification_case(
                "identity-mismatch",
                exact_identity=False,
                failed_requirements=frozenset({"exact_manifest_device_identity"}),
                reason="exact validation-manifest and device identity evidence",
            ),
            classification_case(
                "overall-fail",
                overall_pass=False,
                failed_requirements=frozenset({"overall_pass"}),
                reason="intentional fixture failure",
            ),
            classification_case(
                "diagnostic-identity-override",
                diagnostic_identity_override=True,
                profile="diagnostic-identity-override",
                failed_requirements=frozenset(
                    {"diagnostic_identity_override_disabled"}
                ),
                reason="--diagnostic-identity-override was supplied",
            ),
        )

        for case in cases:
            with self.subTest(classification=case.name):
                result = _attached_windows_report(
                    WINDOWS,
                    host=dict(case.host),
                    process_rss=case.process_rss,
                    duration=case.duration,
                    mode=case.mode,
                    smoke=case.smoke,
                    diagnostic_identity_override=(case.diagnostic_identity_override),
                    overall_pass=case.overall_pass,
                    exact_identity=case.exact_identity,
                )
                windows = result["windows"]
                requirements = windows["release_requirements"]
                expected_requirements = {
                    name: name not in case.failed_requirements
                    for name in requirement_names
                }

                self.assertEqual(requirement_names, tuple(requirements))
                self.assertEqual(expected_requirements, requirements)
                self.assertEqual(case.profile, windows["profile"])
                self.assertEqual(
                    case.release_eligible,
                    windows["release_eligible"],
                )
                self.assertEqual(
                    all(requirements.values()),
                    windows["release_eligible"],
                )
                self.assertTrue(
                    any(
                        case.reason in reason
                        for reason in windows["validation_reasons"]
                    )
                )
                if case.name == "native-windows-release":
                    self.assertEqual("PASS", result["result"])
                    self.assertEqual("physical-combined", result["mode"])

    def test_release_grading_agrees_across_json_and_markdown_reports(self) -> None:
        process_rss: dict[str, object] = {
            "baseline_bytes": 64 * 1024**2,
            "peak_bytes": 72 * 1024**2,
            "growth_bytes": 8 * 1024**2,
        }
        cases: tuple[tuple[str, dict[str, object], str, bool], ...] = (
            (
                "release",
                {"system": "Windows", "sys_platform": "win32"},
                "release",
                True,
            ),
            (
                "diagnostic",
                {"system": "Linux", "sys_platform": "linux"},
                "diagnostic",
                False,
            ),
        )
        with tempfile.TemporaryDirectory(
            prefix="windows-release-matrix-",
            dir=ROOT,
        ) as raw:
            output_directory = Path(raw)
            for name, host, expected_profile, expected_eligible in cases:
                result = _attached_windows_report(
                    WINDOWS,
                    host=host,
                    process_rss=dict(process_rss),
                )
                base = output_directory / name
                json_path, markdown_path = WINDOWS.write_windows_reports(base, result)
                json_report = json.loads(json_path.read_text(encoding="utf-8"))
                markdown = markdown_path.read_text(encoding="utf-8")
                embedded_report = json.loads(
                    markdown.split("```json\n", 1)[1].split("\n```", 1)[0]
                )
                expected_grading = {
                    key: result["windows"][key]
                    for key in (
                        "profile",
                        "release_eligible",
                        "release_requirements",
                    )
                }

                with self.subTest(report=name):
                    self.assertEqual(result, json_report)
                    self.assertEqual(json_report, embedded_report)
                    self.assertEqual(
                        expected_grading,
                        {key: json_report["windows"][key] for key in expected_grading},
                    )
                    self.assertEqual(
                        expected_grading,
                        {
                            key: embedded_report["windows"][key]
                            for key in expected_grading
                        },
                    )
                    self.assertEqual(
                        all(expected_grading["release_requirements"].values()),
                        expected_grading["release_eligible"],
                    )
                    self.assertEqual(expected_profile, expected_grading["profile"])
                    self.assertEqual(
                        expected_eligible,
                        expected_grading["release_eligible"],
                    )
                    self.assertIn(
                        f"| Profile | {expected_profile} |",
                        markdown,
                    )
                    self.assertIn(
                        f"| Release eligible | {expected_eligible} |",
                        markdown,
                    )
                    self.assertEqual(
                        WINDOWS.render_windows_markdown(json_report),
                        markdown,
                    )

    def test_release_profile_requires_one_native_windows_host_snapshot(self) -> None:
        process_rss = {
            "baseline_bytes": 64 * 1024**2,
            "peak_bytes": 65 * 1024**2,
            "growth_bytes": 1024**2,
        }
        cases = (
            ("native", {"system": "Windows", "sys_platform": "win32"}, True),
            ("linux", {"system": "Linux", "sys_platform": "linux"}, False),
            ("macos", {"system": "Darwin", "sys_platform": "darwin"}, False),
            (
                "wine-nonnative",
                {"system": "Windows", "sys_platform": "linux"},
                False,
            ),
            ("unknown", {"system": None, "sys_platform": None}, False),
        )
        for name, host, native in cases:
            with self.subTest(host=name):
                result = _attached_windows_report(
                    WINDOWS,
                    host=host,
                    process_rss=dict(process_rss),
                )
                windows = result["windows"]
                requirements = windows["release_requirements"]
                self.assertEqual(native, requirements["native_windows_host"])
                self.assertEqual(
                    "release" if native else "diagnostic", windows["profile"]
                )
                self.assertEqual(native, windows["release_eligible"])
                if not native:
                    self.assertTrue(
                        any(
                            "native Windows host identity" in reason
                            for reason in windows["validation_reasons"]
                        )
                    )

    def test_invalid_process_rss_evidence_is_explicitly_non_release(self) -> None:
        mib = 1024**2
        cases = (
            (
                "unavailable",
                {"baseline_bytes": 64 * mib, "peak_bytes": 72 * mib},
                "process_rss_growth_valid",
                "unavailable",
            ),
            (
                "nonnumeric",
                {
                    "baseline_bytes": 64 * mib,
                    "peak_bytes": "72 MiB",
                    "growth_bytes": 8 * mib,
                },
                "process_rss_peak_valid",
                "invalid",
            ),
            (
                "boolean",
                {
                    "baseline_bytes": 64 * mib,
                    "peak_bytes": 72 * mib,
                    "growth_bytes": True,
                },
                "process_rss_growth_valid",
                "invalid",
            ),
            (
                "negative",
                {
                    "baseline_bytes": -1,
                    "peak_bytes": 72 * mib,
                    "growth_bytes": 8 * mib,
                },
                "process_rss_baseline_valid",
                "invalid",
            ),
            (
                "nan",
                {
                    "baseline_bytes": 64 * mib,
                    "peak_bytes": float("nan"),
                    "growth_bytes": 8 * mib,
                },
                "process_rss_peak_valid",
                "invalid",
            ),
            (
                "infinite",
                {
                    "baseline_bytes": 64 * mib,
                    "peak_bytes": 72 * mib,
                    "growth_bytes": float("inf"),
                },
                "process_rss_growth_valid",
                "invalid",
            ),
            (
                "over-limit",
                {
                    "baseline_bytes": 64 * mib,
                    "peak_bytes": 100 * mib,
                    "growth_bytes": WINDOWS.MAX_RSS_GROWTH_BYTES + 1,
                },
                "process_rss_growth_within_limit",
                "exceeds",
            ),
        )
        for name, process_rss, failed_requirement, reason_fragment in cases:
            with self.subTest(evidence=name):
                result = _attached_windows_report(
                    WINDOWS,
                    host={"system": "Windows", "sys_platform": "win32"},
                    process_rss=process_rss,
                )
                self.assertEqual("PASS", result["result"])
                windows = result["windows"]
                self.assertEqual("release", windows["profile"])
                self.assertFalse(windows["release_eligible"])
                self.assertFalse(windows["release_requirements"][failed_requirement])
                self.assertEqual(
                    all(windows["release_requirements"].values()),
                    windows["release_eligible"],
                )
                self.assertTrue(
                    any(
                        reason_fragment in reason
                        for reason in windows["validation_reasons"]
                    )
                )

    def test_short_diagnostic_pass_stays_pass_with_unavailable_rss(self) -> None:
        result = _attached_windows_report(
            WINDOWS,
            host={"system": "Windows", "sys_platform": "win32"},
            process_rss=None,
            duration=WINDOWS.WINDOWS_SMOKE_DURATION_SECONDS,
            smoke=True,
        )
        self.assertEqual("PASS", result["result"])
        windows = result["windows"]
        self.assertEqual("diagnostic", windows["profile"])
        self.assertFalse(windows["release_eligible"])
        self.assertFalse(windows["release_requirements"]["non_smoke"])
        self.assertFalse(windows["release_requirements"]["exact_3600_second_duration"])
        self.assertTrue(
            any(
                "process-RSS evidence is unavailable" in reason
                for reason in windows["validation_reasons"]
            )
        )

    def test_pass_and_exact_identity_are_independent_release_predicates(self) -> None:
        process_rss = {
            "baseline_bytes": 64 * 1024**2,
            "peak_bytes": 65 * 1024**2,
            "growth_bytes": 1024**2,
        }
        cases = (
            ("failed-run", False, True, "overall_pass"),
            (
                "identity-mismatch",
                True,
                False,
                "exact_manifest_device_identity",
            ),
        )
        for name, overall_pass, exact_identity, failed_requirement in cases:
            with self.subTest(requirement=name):
                result = _attached_windows_report(
                    WINDOWS,
                    host={"system": "Windows", "sys_platform": "win32"},
                    process_rss=dict(process_rss),
                    overall_pass=overall_pass,
                    exact_identity=exact_identity,
                )
                windows = result["windows"]
                self.assertEqual("release", windows["profile"])
                self.assertFalse(windows["release_eligible"])
                self.assertFalse(windows["release_requirements"][failed_requirement])

    def assert_report_contract(self, base: Path) -> dict[str, object]:
        json_path = Path(f"{base}.json")
        markdown_path = Path(f"{base}.md")
        self.assertTrue(json_path.is_file())
        self.assertTrue(markdown_path.is_file())
        report = json.loads(json_path.read_text(encoding="utf-8"))
        markdown = markdown_path.read_text(encoding="utf-8")
        self.assertEqual(1, report["schema_version"])
        self.assertEqual(2, report["report_schema_version"])
        for name in (
            "result",
            "failure",
            "expected",
            "observed_identity",
            "timing",
            "metrics",
            "epochs",
            "cleanup",
            "program",
            "completed_utc",
            "windows",
        ):
            self.assertIn(name, report)
        windows = report["windows"]
        self.assertIsInstance(windows, dict)
        assert isinstance(windows, dict)
        for name in (
            "profile",
            "release_eligible",
            "release_requirements",
            "host",
            "com_discovery",
            "serial_lifecycle",
            "generation",
            "validation_manifest",
            "validation_reasons",
            "reports",
        ):
            self.assertIn(name, windows)
        self.assertTrue(markdown.startswith("---\ntype: report\n"))
        self.assertIn("title: Teensy DAQ Windows Soak Report", markdown)
        self.assertIn("  - windows", markdown)
        for link in (
            "[[Phase-11-Soak-Evidence]]",
            "[[Quickstart]]",
            "[[Hardware-Safety]]",
            "[[Protocol-V1]]",
        ):
            self.assertIn(link, markdown)
        embedded = markdown.split("```json\n", 1)[1].split("\n```", 1)[0]
        self.assertEqual(report, json.loads(embedded))
        self.assertNotIn(b"\r\n", markdown_path.read_bytes())
        return report

    def test_main_writes_schema_valid_reports_for_all_runtime_exit_classes(
        self,
    ) -> None:
        candidate = _candidate(
            "COM10",
            serial_number=str(TARGET_HARDWARE_SERIAL),
        )
        probe = _passing_probe(candidate, TARGET_HARDWARE_SERIAL)

        class ReportFactory:
            def __init__(self, lifecycle: list[dict[str, object]]) -> None:
                self.lifecycle = lifecycle

            def summary(self) -> list[dict[str, object]]:
                return self.lifecycle

        clean_lifecycle = [
            {
                "attempted": True,
                "completed": True,
                "timed_out": False,
                "error": None,
            }
        ]
        failed_lifecycle = [
            {
                "attempted": True,
                "completed": False,
                "timed_out": True,
                "error": None,
            }
        ]

        def generated_result(
            settings: object,
            _factory: object,
            *,
            failure_category: str | None,
        ) -> tuple[int, dict[str, object]]:
            if failure_category is not None:
                result = WINDOWS.windows_failure_result(
                    WINDOWS.SoakFailure(failure_category, "fixture failure"),
                    settings=settings,
                    mode="combined",
                )
                return 1, result
            result = WINDOWS.windows_failure_result(
                WINDOWS.SoakFailure("fixture", "replaced by PASS"),
                settings=settings,
                mode="combined",
            )
            result.update(
                {
                    "result": "PASS",
                    "failure": None,
                    "cleanup": {"attempted": False, "normal_close": True},
                }
            )
            return 0, result

        scenarios = (
            ("success", 0, None, clean_lifecycle, None),
            ("discovery", 2, "enumeration", clean_lifecycle, "discovery"),
            ("ctrl-c", 130, "interrupt", clean_lifecycle, "program"),
            ("disconnect", 1, "runner", clean_lifecycle, "disconnect"),
            ("stop-timeout", 1, "runner-timeout", clean_lifecycle, "timeout"),
            ("close-timeout", 1, None, failed_lifecycle, "cleanup"),
        )
        with tempfile.TemporaryDirectory(
            prefix="windows-exit-reports-",
            dir=ROOT,
        ) as raw:
            output_directory = Path(raw)
            for name, expected_code, injection, lifecycle, category in scenarios:
                base = output_directory / name
                enum_patch = patch.object(
                    WINDOWS,
                    "enumerate_windows_candidates",
                    return_value=(candidate,),
                )
                probe_patch = patch.object(
                    WINDOWS,
                    "probe_windows_candidates",
                    return_value=(probe,),
                )
                if injection == "enumeration":
                    enum_patch = patch.object(
                        WINDOWS,
                        "enumerate_windows_candidates",
                        side_effect=WINDOWS.SoakFailure(
                            "discovery",
                            "fixture enumeration failed",
                        ),
                    )
                elif injection == "interrupt":
                    probe_patch = patch.object(
                        WINDOWS,
                        "probe_windows_candidates",
                        side_effect=KeyboardInterrupt,
                    )
                run_failure = (
                    "disconnect"
                    if injection == "runner"
                    else ("timeout" if injection == "runner-timeout" else None)
                )
                factory = ReportFactory(lifecycle)
                with (
                    enum_patch,
                    probe_patch,
                    patch.object(
                        WINDOWS,
                        "WindowsPortFactory",
                        return_value=factory,
                    ),
                    patch.object(
                        WINDOWS,
                        "run_generated",
                        side_effect=lambda settings, factory, failure=run_failure: (
                            generated_result(
                                settings,
                                factory,
                                failure_category=failure,
                            )
                        ),
                    ),
                    redirect_stdout(io.StringIO()),
                    redirect_stderr(io.StringIO()),
                ):
                    exit_code = WINDOWS.main(["--smoke", "--output", str(base)])
                with self.subTest(exit=name):
                    self.assertEqual(expected_code, exit_code)
                    report = self.assert_report_contract(base)
                    self.assertEqual(
                        "PASS" if category is None else "FAIL",
                        report["result"],
                    )
                    if category is not None:
                        self.assertEqual(category, report["failure"]["category"])
                    if name == "ctrl-c":
                        self.assertEqual(
                            "interrupted by Ctrl+C",
                            report["failure"]["message"],
                        )

    def test_standalone_and_installed_validators_are_byte_conformant(self) -> None:
        result = conformance.check_conformance()
        self.assertEqual("PASS", result["result"])
        self.assertTrue(all(result["checks"].values()))
        self.assertEqual(
            WINDOWS.soak_conformance_vector(),
            installed_soak.soak_conformance_vector(),
        )

        outputs = []
        for module in (WINDOWS, installed_soak):
            stream = io.StringIO()
            with redirect_stdout(stream):
                exit_code = module.main(["--conformance-check"])
            self.assertEqual(0, exit_code)
            outputs.append(stream.getvalue().encode("utf-8"))
        self.assertEqual(outputs[0], outputs[1])
        self.assertTrue(outputs[0].startswith(b"SOAK_CONFORMANCE "))

    def test_windows_source_is_utf8_crlf_safe_and_has_no_external_dependency(
        self,
    ) -> None:
        path = generator.WINDOWS_OUTPUT_PATH
        source_bytes = path.read_bytes()
        source = source_bytes.decode("utf-8")
        tree = ast.parse(source)
        imports: set[str] = set()
        for node in ast.walk(tree):
            if isinstance(node, ast.Import):
                imports.update(alias.name.split(".", 1)[0] for alias in node.names)
            elif isinstance(node, ast.ImportFrom) and node.module is not None:
                imports.add(node.module.split(".", 1)[0])
        self.assertEqual({"serial"}, imports - sys.stdlib_module_names)
        self.assertTrue(
            {
                "argparse",
                "pathlib",
                "platform",
                "threading",
                "tracemalloc",
            }.issubset(imports)
        )
        for forbidden in (
            "numpy",
            "teensy_daq",
            "firmware.soak",
            "requests",
            "socket",
            "urllib",
            "http",
            "subprocess",
            "aiohttp",
        ):
            with self.subTest(forbidden=forbidden):
                self.assertNotIn(forbidden, imports)
        compile(source, r"C:\TeensyDAQ\windows_soak.py", "exec")
        compile(
            source.replace("\n", "\r\n"),
            r"C:\TeensyDAQ\windows_soak_crlf.py",
            "exec",
        )
        self.assertEqual(source, source.encode("utf-8").decode("utf-8"))
        self.assertNotIn(b"\x00", source_bytes)

        with (
            patch.object(WINDOWS, "resource", None),
            patch("builtins.open", side_effect=FileNotFoundError),
            patch.object(WINDOWS.os, "sysconf", side_effect=OSError),
        ):
            self.assertIsNone(WINDOWS._peak_rss_bytes())
            self.assertIsNone(WINDOWS._current_rss_bytes())
            self.assertIsNone(WINDOWS._available_process_memory_bytes())
            self.assertEqual({}, WINDOWS._cgroup_cpu_statistics())

        relative_file_opens = []
        for node in ast.walk(tree):
            if not isinstance(node, ast.Call) or not node.args:
                continue
            if not isinstance(node.func, ast.Name) or node.func.id != "open":
                continue
            first = node.args[0]
            if isinstance(first, ast.Constant) and isinstance(first.value, str):
                if not first.value.startswith(("/proc/", "/sys/")):
                    relative_file_opens.append(first.value)
            elif isinstance(first, ast.Name) and first.id == "path":
                continue
            elif not isinstance(first, ast.Name) or first.id != "__file__":
                relative_file_opens.append(ast.unparse(first))
        self.assertEqual([], relative_file_opens)


if __name__ == "__main__":
    unittest.main()
