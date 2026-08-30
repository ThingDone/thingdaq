# <soak-cli>
import argparse  # noqa: I001 - generated driver imports follow the canonical core
import ctypes
import platform
import re
import threading
from pathlib import Path

from serial.tools import list_ports


WINDOWS_REPORT_SCHEMA_VERSION = 2
WINDOWS_DEFAULT_DURATION_SECONDS = 3_600.0
WINDOWS_SMOKE_DURATION_SECONDS = 10.0
WINDOWS_MAXIMUM_DURATION_SECONDS = 86_400.0
WINDOWS_RUN_RESERVE_SECONDS = 90.0
WINDOWS_CLEANUP_RESERVE_SECONDS = 30.0
WINDOWS_DEFAULT_DISCOVERY_TIMEOUT_SECONDS = 15.0
WINDOWS_DEFAULT_OPEN_TIMEOUT_SECONDS = 3.0
WINDOWS_CLOSE_TIMEOUT_SECONDS = 1.0
TEENSY_USB_SERIAL_VID = 0x16C0
TEENSY_USB_SERIAL_PID = 0x0483
TEENSY_DAQ_PRODUCT = "Teensy DAQ"
WINDOWS_PORT_PATTERN = re.compile(r"(?i)^COM([1-9][0-9]*)$")
SOAK_CONFORMANCE_SCHEMA_VERSION = 1
SOAK_CONFORMANCE_PREFIX = "SOAK_CONFORMANCE "
_WINDOWS_RELEASE_PROFILE_REQUIREMENTS = (
    "physical_combined_mode",
    "exact_3600_second_duration",
    "non_smoke",
    "diagnostic_identity_override_disabled",
    "native_windows_host",
)


class _WindowsProcessMemoryCounters(ctypes.Structure):
    """Windows ``PROCESS_MEMORY_COUNTERS`` with architecture-sized fields."""

    _fields_ = [
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
    ]


@dataclass(frozen=True)
class _WindowsProcessMemoryApi:
    """Mockable pair of native calls needed for process-memory evidence."""

    get_current_process: Callable[[], object]
    get_process_memory_info: Callable[[object, object, int], object]


def _load_windows_process_memory_api() -> _WindowsProcessMemoryApi | None:
    """Load and type the dependency-free Windows process-memory API once."""

    dll_loader = getattr(ctypes, "WinDLL", None)
    if dll_loader is None:
        return None
    try:
        kernel32 = dll_loader("kernel32", use_last_error=True)
        psapi = dll_loader("psapi", use_last_error=True)
        get_current_process = kernel32.GetCurrentProcess
        get_current_process.argtypes = []
        get_current_process.restype = ctypes.c_void_p
        get_process_memory_info = psapi.GetProcessMemoryInfo
        get_process_memory_info.argtypes = [
            ctypes.c_void_p,
            ctypes.POINTER(_WindowsProcessMemoryCounters),
            ctypes.c_uint32,
        ]
        get_process_memory_info.restype = ctypes.c_int
    except Exception:  # noqa: BLE001 - optional native evidence fails closed
        return None
    return _WindowsProcessMemoryApi(
        get_current_process=get_current_process,
        get_process_memory_info=get_process_memory_info,
    )


_WINDOWS_PROCESS_MEMORY_API = (
    _load_windows_process_memory_api() if sys.platform == "win32" else None
)
_canonical_current_rss_bytes = _current_rss_bytes
_canonical_peak_rss_bytes = _peak_rss_bytes


def _windows_process_memory_bytes(
    api: _WindowsProcessMemoryApi | None = None,
) -> tuple[int, int] | None:
    """Return validated current/peak working-set bytes from one native call."""

    selected_api = _WINDOWS_PROCESS_MEMORY_API if api is None else api
    if selected_api is None:
        return None
    counters = _WindowsProcessMemoryCounters()
    structure_size = ctypes.sizeof(counters)
    counters.cb = structure_size
    try:
        process = selected_api.get_current_process()
        if process is None or process == 0:
            return None
        succeeded = selected_api.get_process_memory_info(
            process,
            ctypes.byref(counters),
            structure_size,
        )
    except Exception:  # noqa: BLE001 - optional native evidence fails closed
        return None
    if not succeeded or counters.cb != structure_size:
        return None
    current_bytes = int(counters.WorkingSetSize)
    peak_bytes = int(counters.PeakWorkingSetSize)
    if current_bytes < 0 or peak_bytes < current_bytes:
        return None
    return current_bytes, peak_bytes


def _current_rss_bytes() -> int | None:  # type: ignore[no-redef]
    if sys.platform != "win32":
        return _canonical_current_rss_bytes()
    memory = _windows_process_memory_bytes()
    return memory[0] if memory is not None else None


def _peak_rss_bytes() -> int | None:  # type: ignore[no-redef]
    if sys.platform != "win32":
        return _canonical_peak_rss_bytes()
    memory = _windows_process_memory_bytes()
    return memory[1] if memory is not None else None


@dataclass(frozen=True)
class WindowsPortCandidate:
    """One plausible Windows Teensy USB Serial endpoint."""

    port: str
    vid: int
    pid: int
    serial_number: str | None
    product: str | None
    manufacturer: str | None
    location: str | None
    interface: str | None
    description: str | None

    def as_dict(self) -> dict[str, object]:
        return {
            "port": self.port,
            "vid": self.vid,
            "pid": self.pid,
            "vid_pid": f"{self.vid:04X}:{self.pid:04X}",
            "serial_number": self.serial_number,
            "product": self.product,
            "manufacturer": self.manufacturer,
            "location": self.location,
            "interface": self.interface,
            "description": self.description,
        }


@dataclass(frozen=True)
class WindowsProbeResult:
    """Bounded INFO-probe evidence for one plausible endpoint."""

    candidate: WindowsPortCandidate
    observed_identity: dict[str, object] | None
    identity_mismatches: dict[str, dict[str, object]]
    latency_seconds: list[float]
    failure: dict[str, str] | None
    close: dict[str, object]

    @property
    def passed(self) -> bool:
        return self.failure is None and self.observed_identity is not None

    def as_dict(self) -> dict[str, object]:
        return {
            "candidate": self.candidate.as_dict(),
            "result": "PASS" if self.passed else "FAIL",
            "release_identity_match": not self.identity_mismatches,
            "observed_identity": self.observed_identity,
            "identity_mismatches": self.identity_mismatches,
            "info_latency_seconds": self.latency_seconds,
            "failure": self.failure,
            "close": self.close,
        }


def _optional_metadata(value: object) -> str | None:
    return value if isinstance(value, str) and value else None


def _windows_port_number(port: str) -> int:
    match = WINDOWS_PORT_PATTERN.fullmatch(port)
    return int(match.group(1)) if match is not None else 0x7FFFFFFF


def _windows_candidate_sort_key(
    candidate: WindowsPortCandidate,
) -> tuple[object, ...]:
    if candidate.product == TEENSY_DAQ_PRODUCT:
        product_rank = 0
    elif candidate.product is None:
        product_rank = 1
    else:
        product_rank = 2
    return (
        product_rank,
        (candidate.serial_number or "").casefold(),
        (candidate.location or "").casefold(),
        _windows_port_number(candidate.port),
        candidate.port.casefold(),
    )


def enumerate_windows_candidates(
    port_enumerator: Callable[[], object] | None = None,
) -> tuple[WindowsPortCandidate, ...]:
    """Enumerate only matching Teensy USB Serial COM endpoints."""

    enumerate_ports = port_enumerator or (
        lambda: list_ports.comports(include_links=False)
    )
    candidates: list[WindowsPortCandidate] = []
    seen: set[str] = set()
    metadata_records = enumerate_ports()
    if not isinstance(metadata_records, (list, tuple)):
        raise SoakFailure("discovery", "COM enumerator did not return a sequence")
    for metadata in metadata_records:
        if (
            getattr(metadata, "vid", None) != TEENSY_USB_SERIAL_VID
            or getattr(metadata, "pid", None) != TEENSY_USB_SERIAL_PID
        ):
            continue
        port = getattr(metadata, "device", None)
        if not isinstance(port, str) or WINDOWS_PORT_PATTERN.fullmatch(port) is None:
            continue
        normalized = port.casefold()
        if normalized in seen:
            continue
        seen.add(normalized)
        candidates.append(
            WindowsPortCandidate(
                port=port,
                vid=TEENSY_USB_SERIAL_VID,
                pid=TEENSY_USB_SERIAL_PID,
                serial_number=_optional_metadata(
                    getattr(metadata, "serial_number", None)
                ),
                product=_optional_metadata(getattr(metadata, "product", None)),
                manufacturer=_optional_metadata(
                    getattr(metadata, "manufacturer", None)
                ),
                location=_optional_metadata(getattr(metadata, "location", None)),
                interface=_optional_metadata(getattr(metadata, "interface", None)),
                description=_optional_metadata(getattr(metadata, "description", None)),
            )
        )
    candidates.sort(key=_windows_candidate_sort_key)
    return tuple(candidates)


class _SerialOpenAttempt:
    def __init__(self) -> None:
        self.done = threading.Event()
        self.lock = threading.Lock()
        self.cancelled = False
        self.port: SerialPort | None = None
        self.error: BaseException | None = None


def _close_raw_serial(port: SerialPort) -> None:
    try:
        port.close()
    except BaseException:  # noqa: BLE001 - late open cleanup is best effort
        return


class BoundedWindowsSerial:
    """Map PySerial failures and make close attempts time-bounded."""

    def __init__(self, port_name: str, raw_port: SerialPort) -> None:
        self.port_name = port_name
        self.raw_port = raw_port
        self.close_attempted = False
        self.close_completed = False
        self.close_timed_out = False
        self.close_error: str | None = None

    def read(self, size: int = 1) -> bytes:
        try:
            return bytes(self.raw_port.read(size))
        except (serial.SerialException, OSError) as error:
            raise SoakFailure(
                "disconnect",
                f"{self.port_name} read failed: {type(error).__name__}: {error}",
            ) from error

    def write(self, data: bytes) -> int | None:
        try:
            return self.raw_port.write(data)
        except serial.SerialTimeoutException as error:
            raise DeadlineExpired(
                f"{self.port_name} write timed out: {error}"
            ) from error
        except (serial.SerialException, OSError) as error:
            raise SoakFailure(
                "disconnect",
                f"{self.port_name} write failed: {type(error).__name__}: {error}",
            ) from error

    def close(self) -> None:
        if self.close_attempted:
            return
        self.close_attempted = True
        completed = threading.Event()
        errors: list[str] = []

        def close_worker() -> None:
            try:
                self.raw_port.close()
            except BaseException as error:  # noqa: BLE001 - retained as evidence
                errors.append(f"{type(error).__name__}: {error}")
            finally:
                completed.set()

        threading.Thread(
            target=close_worker,
            name="teensy-daq-serial-close",
            daemon=True,
        ).start()
        self.close_completed = completed.wait(WINDOWS_CLOSE_TIMEOUT_SECONDS)
        self.close_timed_out = not self.close_completed
        self.close_error = errors[0] if errors else None

    def close_summary(self) -> dict[str, object]:
        return {
            "attempted": self.close_attempted,
            "completed": self.close_completed,
            "timed_out": self.close_timed_out,
            "error": self.close_error,
        }


def open_windows_serial(
    port_name: str,
    *,
    open_timeout_seconds: float,
) -> BoundedWindowsSerial:
    """Open a COM endpoint without allowing the calling thread to hang."""

    attempt = _SerialOpenAttempt()

    def open_worker() -> None:
        opened: SerialPort | None = None
        error: BaseException | None = None
        try:
            opened = serial.Serial(
                port=port_name,
                baudrate=BAUD_RATE,
                timeout=SERIAL_READ_TIMEOUT_SECONDS,
                write_timeout=SERIAL_WRITE_TIMEOUT_SECONDS,
            )
            try:
                opened.dtr = True  # type: ignore[attr-defined]
            except (AttributeError, OSError, serial.SerialException):
                pass
        except BaseException as caught:  # noqa: BLE001 - transferred to caller
            error = caught
        close_late_port: SerialPort | None = None
        with attempt.lock:
            if attempt.cancelled:
                close_late_port = opened
            else:
                attempt.port = opened
                attempt.error = error
        attempt.done.set()
        if close_late_port is not None:
            threading.Thread(
                target=_close_raw_serial,
                args=(close_late_port,),
                name="teensy-daq-late-open-close",
                daemon=True,
            ).start()

    threading.Thread(
        target=open_worker,
        name="teensy-daq-serial-open",
        daemon=True,
    ).start()
    if not attempt.done.wait(open_timeout_seconds):
        opened_after_timeout: SerialPort | None
        with attempt.lock:
            attempt.cancelled = True
            opened_after_timeout = attempt.port
            attempt.port = None
        if opened_after_timeout is not None:
            threading.Thread(
                target=_close_raw_serial,
                args=(opened_after_timeout,),
                name="teensy-daq-open-timeout-close",
                daemon=True,
            ).start()
        raise DeadlineExpired(
            f"serial open for {port_name} exceeded {open_timeout_seconds:g} seconds"
        )
    if attempt.error is not None:
        error = attempt.error
        category = (
            "timeout"
            if isinstance(error, serial.SerialTimeoutException)
            else "serial_open"
        )
        raise SoakFailure(
            category,
            f"could not open {port_name}: {type(error).__name__}: {error}",
        ) from error
    if attempt.port is None:
        raise SoakFailure(
            "serial_open", f"serial open for {port_name} returned no port"
        )
    return BoundedWindowsSerial(port_name, attempt.port)


def _observed_probe_identity(
    info: Mapping[str, object],
    expected_info: Mapping[str, object],
) -> dict[str, object]:
    return {name: _identity_json_value(info.get(name)) for name in expected_info}


def probe_windows_candidate(
    candidate: WindowsPortCandidate,
    settings: RuntimeSettings,
    *,
    discovery_deadline: float,
    open_timeout_seconds: float,
    clock: Clock = time,
) -> WindowsProbeResult:
    """Perform a bounded, read-only, exact-identity INFO probe."""

    port: BoundedWindowsSerial | None = None
    info: dict[str, object] | None = None
    identity_mismatches: dict[str, dict[str, object]] = {}
    latencies: list[float] = []
    failure: dict[str, str] | None = None
    try:
        remaining = discovery_deadline - clock.monotonic()
        if remaining <= 0:
            raise DeadlineExpired("Windows COM discovery total deadline expired")
        port = open_windows_serial(
            candidate.port,
            open_timeout_seconds=min(open_timeout_seconds, remaining),
        )
        link = SerialLink(port, clock, read_bytes=settings.serial_read_bytes)
        remaining = discovery_deadline - clock.monotonic()
        if remaining <= STARTUP_DRAIN_SECONDS:
            raise DeadlineExpired("insufficient discovery budget for startup drain")
        link.drain_startup(STARTUP_DRAIN_SECONDS)
        info, latencies = synchronize(link, hard_deadline=discovery_deadline)
        identity_mismatches = info_identity_mismatches(info, settings)
        validate_info_identity(info, settings, expected_state=STATE_IDLE)
        usb_serial = candidate.serial_number
        if usb_serial is not None and usb_serial.isascii() and usb_serial.isdecimal():
            require(
                int(usb_serial, 10) == info["hardware_serial"],
                "identity",
                "USB descriptor serial disagrees with INFO hardware serial",
            )
    except BaseException as error:
        if isinstance(error, KeyboardInterrupt):
            raise
        failure = {
            "category": error.category if isinstance(error, SoakFailure) else "probe",
            "type": type(error).__name__,
            "message": str(error),
        }
    finally:
        if port is not None:
            port.close()
    close: dict[str, object]
    if port is not None:
        close = port.close_summary()
    else:
        close = {
            "attempted": False,
            "completed": False,
            "timed_out": False,
            "error": None,
        }
    if failure is None and (close["timed_out"] or close["error"] is not None):
        failure = {
            "category": "cleanup",
            "type": "SerialCloseError",
            "message": f"probe close did not complete cleanly: {close}",
        }
    return WindowsProbeResult(
        candidate=candidate,
        observed_identity=(
            _observed_probe_identity(info, settings.expected_info)
            if failure is None and info is not None
            else None
        ),
        identity_mismatches=identity_mismatches,
        latency_seconds=latencies,
        failure=failure,
        close=close,
    )


def probe_windows_candidates(
    candidates: tuple[WindowsPortCandidate, ...],
    settings: RuntimeSettings,
    *,
    discovery_timeout_seconds: float,
    open_timeout_seconds: float,
    clock: Clock = time,
) -> tuple[WindowsProbeResult, ...]:
    deadline = clock.monotonic() + discovery_timeout_seconds
    results: list[WindowsProbeResult] = []
    for candidate in candidates:
        if clock.monotonic() >= deadline:
            results.append(
                WindowsProbeResult(
                    candidate=candidate,
                    observed_identity=None,
                    identity_mismatches={},
                    latency_seconds=[],
                    failure={
                        "category": "timeout",
                        "type": "DeadlineExpired",
                        "message": "not probed before the discovery total deadline",
                    },
                    close={
                        "attempted": False,
                        "completed": False,
                        "timed_out": False,
                        "error": None,
                    },
                )
            )
            continue
        print(f"Probing {candidate.port}...", flush=True)
        result = probe_windows_candidate(
            candidate,
            settings,
            discovery_deadline=deadline,
            open_timeout_seconds=open_timeout_seconds,
            clock=clock,
        )
        if result.passed:
            match = (
                "matching release identity"
                if not result.identity_mismatches
                else "accepted only by diagnostic identity override"
            )
            print(f"  {candidate.port}: Teensy DAQ, {match}", flush=True)
        else:
            assert result.failure is not None
            print(
                f"  {candidate.port}: rejected "
                f"({result.failure['category']}: {result.failure['message']})",
                flush=True,
            )
        results.append(result)
    return tuple(results)


def select_windows_candidate(
    probes: tuple[WindowsProbeResult, ...],
    *,
    hardware_serial: int,
) -> WindowsPortCandidate:
    matching = [
        probe.candidate
        for probe in probes
        if probe.passed
        and probe.observed_identity is not None
        and probe.observed_identity.get("hardware_serial") == hardware_serial
    ]
    if not matching:
        raise SoakFailure(
            "discovery",
            f"no plausible COM port passed the exact identity probe for hardware "
            f"serial {hardware_serial}",
        )
    return min(matching, key=_windows_candidate_sort_key)


class WindowsPortFactory:
    def __init__(
        self,
        candidate: WindowsPortCandidate,
        *,
        open_timeout_seconds: float,
    ) -> None:
        self.candidate = candidate
        self.open_timeout_seconds = open_timeout_seconds
        self.opened: list[BoundedWindowsSerial] = []

    def __call__(self) -> SerialPort:
        port = open_windows_serial(
            self.candidate.port,
            open_timeout_seconds=self.open_timeout_seconds,
        )
        self.opened.append(port)
        return port

    def summary(self) -> list[dict[str, object]]:
        return [port.close_summary() for port in self.opened]


def windows_runtime_settings(
    mode: str,
    duration: float,
    *,
    diagnostic_identity_override: bool = False,
) -> RuntimeSettings:
    """Apply only duration/source choices to the pinned generated candidate."""

    config = json.loads(json.dumps(GENERATED_CONFIG))
    if not isinstance(config, dict):
        raise SoakFailure("configuration", "generated config is not an object")
    candidate = _mapping(config.get("candidate"), "candidate")
    soak = candidate.get("soak")
    if not isinstance(soak, dict):
        raise SoakFailure("configuration", "candidate.soak is not an object")
    internal_mode = "physical-combined" if mode == "combined" else "synthetic"
    status_interval = max(1.0, duration / 3_500.0)
    info_interval = max(30.0, duration / 400.0, status_interval)
    warmup = _number(soak.get("warmup_seconds"), "soak.warmup_seconds")
    soak.update(
        {
            "measured_duration_seconds": duration,
            "status_interval_seconds": status_interval,
            "info_interval_seconds": info_interval,
            "hard_deadline_seconds": (duration + warmup + WINDOWS_RUN_RESERVE_SECONDS),
            "service_container_limit_seconds": (
                duration
                + warmup
                + WINDOWS_RUN_RESERVE_SECONDS
                + WINDOWS_CLEANUP_RESERVE_SECONDS
            ),
        }
    )
    config["mode"] = internal_mode
    config["diagnostic_identity_override"] = diagnostic_identity_override
    return load_settings(config)


class _ConformanceClock:
    """Deterministic clock used only by the bounded entry-point self-check."""

    def __init__(self) -> None:
        self.now = 0.0

    def monotonic(self) -> float:
        return self.now

    def perf_counter(self) -> float:
        return self.now

    def sleep(self, seconds: float) -> None:
        self.now += seconds


def _conformance_payload(kind: int, first_sample_ticks: int) -> bytes:
    if kind == ADC_DATA:
        start_pair = first_sample_ticks // ADC_PAIR_PERIOD_TICKS
        offset = (start_pair * ADC_BYTES_PER_PAIR) % len(ADC_PATTERN)
        return ADC_PATTERN_DOUBLE[offset : offset + DATA_PAYLOAD_BYTES]
    start_sample = first_sample_ticks // GPIO_SAMPLE_PERIOD_TICKS
    offset = start_sample & 0xFF
    return GPIO_PATTERN_EXPANDED[offset : offset + DATA_PAYLOAD_BYTES]


def _conformance_data_frame(
    kind: int,
    *,
    sequence: int = 0,
    gap_before: bool = False,
    corrupt_checksum: bool = False,
    corrupt_pattern: bool = False,
) -> bytes:
    first_sample_ticks = sequence * FRAME_COVERAGE_TICKS
    flags = FLAG_SYNTHETIC
    if sequence == 0:
        flags |= FLAG_EPOCH_START
    if gap_before:
        flags |= FLAG_GAP_BEFORE | FLAG_OVERRUN_BEFORE
    payload = bytearray(_conformance_payload(kind, first_sample_ticks))
    if corrupt_pattern:
        payload[17] ^= 0x01
    item_count = ADC_PAIRS_PER_FRAME if kind == ADC_DATA else GPIO_SAMPLES_PER_FRAME
    header = HEADER.pack(
        MAGIC,
        PROTOCOL_VERSION,
        kind,
        flags,
        HEADER_SIZE,
        CHECKSUM_ADLER32,
        0,
        DATA_FRAME_BYTES,
        DATA_PAYLOAD_BYTES,
        7,
        sequence,
        0,
        first_sample_ticks,
        item_count,
    )
    body = header + payload
    wire = bytearray(body + TRAILER.pack(adler32(body)))
    if corrupt_checksum:
        wire[HEADER_SIZE + 29] ^= 0x80
    return bytes(wire)


def _conformance_grade(transcript: bytes) -> dict[str, object]:
    parser = FrameParser(maximum_input_bytes=DATA_FRAME_BYTES)
    clock = _ConformanceClock()
    validator = StreamValidator(
        7,
        SOURCE_SYNTHETIC,
        CHECKSUM_ADLER32,
        clock,
    )
    pattern = (1, 7, 31, 257, DATA_FRAME_BYTES, 17)
    offset = 0
    chunk_index = 0
    try:
        while offset < len(transcript):
            chunk_bytes = pattern[chunk_index % len(pattern)]
            chunk_index += 1
            chunk = transcript[offset : offset + chunk_bytes]
            offset += len(chunk)
            before_errors = parser.errors
            frames = parser.feed(chunk)
            if parser.errors != before_errors:
                category = "checksum_corruption" if parser.checksum_errors else "parser"
                raise SoakFailure(
                    category,
                    "fixture transcript contains rejected wire bytes",
                )
            for frame in frames:
                validator.accept(frame)
        require(not parser.buffer, "parser", "fixture transcript ended mid-frame")
        require(
            validator.adc.frames == 1 and validator.gpio.frames == 1,
            "source_gap",
            "fixture transcript did not contain one frame from each stream",
        )
        elapsed_seconds = FRAME_COVERAGE_TICKS / TIMESTAMP_HZ
        metrics = {
            "elapsed_seconds": elapsed_seconds,
            "adc_pair_rate_hz": validator.adc.items / elapsed_seconds,
            "gpio_sample_rate_hz": validator.gpio.items / elapsed_seconds,
            "payload_bytes_per_second": (
                validator.adc.payload_bytes + validator.gpio.payload_bytes
            )
            / elapsed_seconds,
            "framed_bytes_per_second": (
                validator.adc.framed_bytes + validator.gpio.framed_bytes
            )
            / elapsed_seconds,
        }
        for name, target in (
            ("adc_pair_rate_hz", ADC_PAIR_RATE_HZ),
            ("gpio_sample_rate_hz", GPIO_SAMPLE_RATE_HZ),
            (
                "payload_bytes_per_second",
                TARGET_COMBINED_PAYLOAD_BYTES_PER_SECOND,
            ),
        ):
            value = metrics[name]
            require(
                abs(value - target) / target <= RATE_TOLERANCE_FRACTION,
                "rate",
                f"fixture {name} is outside the accepted tolerance",
            )
        return {
            "result": "PASS",
            "failure_category": None,
            "parser": {
                "bytes_received": parser.bytes_received,
                "frames_decoded": parser.frames_decoded,
                "bytes_discarded": parser.bytes_discarded,
                "errors": parser.errors,
                "buffered_bytes": len(parser.buffer),
                "high_water_bytes": parser.high_water_bytes,
            },
            "frames": {
                "adc": validator.adc.frames,
                "gpio": validator.gpio.frames,
                "maximum_skew": validator.maximum_frame_skew,
            },
            "metrics": metrics,
        }
    except SoakFailure as error:
        return {
            "result": "FAIL",
            "failure_category": error.category,
            "parser": {
                "bytes_received": parser.bytes_received,
                "frames_decoded": parser.frames_decoded,
                "bytes_discarded": parser.bytes_discarded,
                "errors": parser.errors,
                "buffered_bytes": len(parser.buffer),
                "high_water_bytes": parser.high_water_bytes,
            },
        }


def soak_conformance_vector() -> dict[str, object]:
    """Return deterministic command, frame, metric, and grading evidence."""

    configuration = CONFIGURATION.pack(
        STREAM_BOTH,
        SOURCE_SYNTHETIC,
        CHECKSUM_ADLER32,
        0,
        DATA_FRAME_BYTES,
    )
    command_inputs = (
        (INFO_REQUEST, 1, b""),
        (CONFIGURE_REQUEST, 2, configuration),
        (START_REQUEST, 3, b""),
        (GET_STATUS_REQUEST, 4, b""),
        (STOP_REQUEST, 5, b""),
        (RESET_STATS_REQUEST, 6, b""),
    )
    commands = [
        {
            "kind": kind,
            "request_id": request_id,
            "size_bytes": len(wire),
            "sha256": hashlib.sha256(wire).hexdigest(),
        }
        for kind, request_id, payload in command_inputs
        for wire in (encode_request(kind, request_id, payload),)
    ]
    adc = _conformance_data_frame(ADC_DATA)
    gpio = _conformance_data_frame(GPIO_DATA)
    valid = adc + gpio
    latency = BoundedLatency()
    for sample in (0.001, 0.010, 0.050, 0.095, 0.099):
        latency.add(sample)
    grades = {
        "valid": _conformance_grade(valid),
        "checksum_corruption": _conformance_grade(
            _conformance_data_frame(ADC_DATA, corrupt_checksum=True) + gpio
        ),
        "pattern_error": _conformance_grade(
            _conformance_data_frame(ADC_DATA, corrupt_pattern=True) + gpio
        ),
        "source_gap": _conformance_grade(
            adc + _conformance_data_frame(GPIO_DATA, sequence=2, gap_before=True)
        ),
    }
    return {
        "schema_version": SOAK_CONFORMANCE_SCHEMA_VERSION,
        "commands": commands,
        "frames": {
            "transcript_bytes": len(valid),
            "transcript_sha256": hashlib.sha256(valid).hexdigest(),
            "chunk_pattern": [1, 7, 31, 257, DATA_FRAME_BYTES, 17],
        },
        "latency": latency.summary(),
        "grades": grades,
    }


def _positive_duration(value: str) -> float:
    try:
        duration = float(value)
    except ValueError as error:
        raise argparse.ArgumentTypeError("duration must be numeric") from error
    if (
        not math.isfinite(duration)
        or not 1.0 <= duration <= WINDOWS_MAXIMUM_DURATION_SECONDS
    ):
        raise argparse.ArgumentTypeError("duration must be between 1 and 86400 seconds")
    return duration


def _positive_timeout(value: str) -> float:
    try:
        timeout = float(value)
    except ValueError as error:
        raise argparse.ArgumentTypeError("timeout must be numeric") from error
    if not math.isfinite(timeout) or not 0.1 <= timeout <= 300.0:
        raise argparse.ArgumentTypeError("timeout must be between 0.1 and 300 seconds")
    return timeout


def _hardware_serial(value: str) -> int:
    try:
        result = int(value, 0)
    except ValueError as error:
        raise argparse.ArgumentTypeError(
            "hardware serial must be decimal or 0x-prefixed hexadecimal"
        ) from error
    if not 1 <= result <= 0xFFFFFFFF:
        raise argparse.ArgumentTypeError("hardware serial must be a nonzero uint32")
    return result


def build_windows_parser() -> argparse.ArgumentParser:
    implementation = (
        "Installed-package"
        if GENERATED_CONFIG.get("entry_point") == "installed-package"
        else "Standalone"
    )
    parser = argparse.ArgumentParser(
        description=(
            f"{implementation}, release-identity-pinned Teensy DAQ Windows soak "
            "validator"
        )
    )
    parser.add_argument(
        "--conformance-check",
        action="store_true",
        help="run the bounded deterministic protocol/validator self-check and exit",
    )
    parser.add_argument(
        "--mode",
        choices=("combined", "synthetic"),
        default="combined",
        help="combined physical acquisition (default) or firmware synthetic source",
    )
    duration = parser.add_mutually_exclusive_group()
    duration.add_argument(
        "--duration",
        type=_positive_duration,
        default=WINDOWS_DEFAULT_DURATION_SECONDS,
        metavar="SECONDS",
        help="measured streaming duration (default: 3600)",
    )
    duration.add_argument(
        "--smoke",
        action="store_true",
        help="run the same validation semantics for a 10-second diagnostic smoke",
    )
    parser.add_argument(
        "--hardware-serial",
        type=_hardware_serial,
        help="select the pinned device deterministically across COM renumbering",
    )
    parser.add_argument(
        "--port",
        help="limit probing to this plausible enumerated COM port",
    )
    parser.add_argument(
        "--diagnostic-identity-override",
        action="store_true",
        help=(
            "allow a nonmatching firmware/device identity for diagnosis; every "
            "result is prominently marked non-release"
        ),
    )
    parser.add_argument(
        "--output",
        type=Path,
        default=Path("teensy-daq-windows-soak"),
        help="report path base; .json and .md are written (default shown)",
    )
    parser.add_argument(
        "--discovery-timeout",
        type=_positive_timeout,
        default=WINDOWS_DEFAULT_DISCOVERY_TIMEOUT_SECONDS,
        metavar="SECONDS",
        help="total COM enumeration/probe deadline (default: 15)",
    )
    parser.add_argument(
        "--open-timeout",
        type=_positive_timeout,
        default=WINDOWS_DEFAULT_OPEN_TIMEOUT_SECONDS,
        metavar="SECONDS",
        help="per-COM serial-open deadline (default: 3)",
    )
    return parser


def windows_host_identity() -> dict[str, object]:
    win32 = platform.win32_ver()
    return {
        "hostname": platform.node(),
        "platform": platform.platform(),
        "system": platform.system(),
        "release": platform.release(),
        "version": platform.version(),
        "machine": platform.machine(),
        "processor": platform.processor(),
        "win32_version": list(win32),
        "python_version": platform.python_version(),
        "python_implementation": platform.python_implementation(),
        "pyserial_version": getattr(serial, "VERSION", None),
        "sys_platform": sys.platform,
    }


def _expected_settings(settings: RuntimeSettings) -> dict[str, object]:
    return {
        "protocol_version": settings.protocol_version,
        "checksum_algorithm": settings.checksum_algorithm,
        "checksum_name": settings.checksum_name,
        "firmware_version": list(settings.firmware_version),
        "build_id": settings.build_id,
        "source_id": settings.source_id,
        "artifact_name": settings.artifact_name,
        "artifact_sha256": settings.artifact_sha256,
        "fqbn": settings.fqbn,
        "hardware_serial": settings.hardware_serial,
        "board_id": settings.board_id,
        "mcu_id": settings.mcu_id,
        "validation_manifest_sha256": settings.validation_manifest_sha256,
    }


def windows_failure_result(
    error: BaseException,
    *,
    settings: RuntimeSettings | None,
    mode: str,
) -> dict[str, object]:
    message = str(error) or (
        "interrupted by Ctrl+C" if isinstance(error, KeyboardInterrupt) else "no detail"
    )
    return {
        "schema_version": RESULT_SCHEMA_VERSION,
        "result": "FAIL",
        "mode": "physical-combined" if mode == "combined" else "synthetic",
        "failure": {
            "category": error.category if isinstance(error, SoakFailure) else "program",
            "type": type(error).__name__,
            "message": message,
        },
        "expected": _expected_settings(settings) if settings is not None else None,
        "observed_identity": None,
        "timing": (
            {
                "measured_duration_seconds": settings.measured_duration_seconds,
                "hard_deadline_seconds": settings.hard_deadline_seconds,
                "service_container_limit_seconds": (
                    settings.service_container_limit_seconds
                ),
            }
            if settings is not None
            else {}
        ),
        "metrics": {},
        "epochs": [],
        "cleanup": {"attempted": False, "normal_close": False},
        "program": {
            "sha256": _program_sha256(),
            "validator_sha256": (
                settings.validator_sha256 if settings is not None else None
            ),
            "candidate_sha256": (
                settings.candidate_sha256 if settings is not None else None
            ),
            "validation_manifest_sha256": (
                settings.validation_manifest_sha256 if settings is not None else None
            ),
            "python": sys.version.split()[0],
        },
        "completed_utc": datetime.now(timezone.utc).isoformat(),
    }


def _windows_validation_reasons(
    result: Mapping[str, object],
    *,
    diagnostic_identity_override: bool,
    identity_mismatches: Mapping[str, object],
    release_requirements: Mapping[str, bool],
    process_rss: Mapping[str, object],
) -> list[str]:
    reasons: list[str] = []
    if diagnostic_identity_override:
        reasons.append(
            "NON-RELEASE: --diagnostic-identity-override was supplied; this "
            "result cannot support a release claim"
        )
        if identity_mismatches:
            reasons.append(
                "the observed INFO identity/capabilities differ from the pinned "
                "Phase 11 validation manifest"
            )
    if not release_requirements["native_windows_host"]:
        reasons.append(
            "NON-RELEASE: native Windows host identity is required "
            '(system == "Windows" and sys_platform == "win32")'
        )
    if not all(
        release_requirements[name]
        for name in (
            "physical_combined_mode",
            "exact_3600_second_duration",
            "non_smoke",
        )
    ):
        reasons.append(
            "NON-RELEASE: the release profile requires an exact 3,600-second "
            "non-smoke physical-combined run"
        )
    rss_validity_requirements = (
        "process_rss_baseline_valid",
        "process_rss_peak_valid",
        "process_rss_growth_valid",
    )
    if not all(release_requirements[name] for name in rss_validity_requirements):
        rss_values = {
            name: process_rss.get(name)
            for name in ("baseline_bytes", "peak_bytes", "growth_bytes")
        }
        unavailable = any(value is None for value in rss_values.values())
        reasons.append(
            "NON-RELEASE: complete numeric process-RSS evidence is "
            + ("unavailable" if unavailable else "invalid")
            + "; baseline_bytes, peak_bytes, and growth_bytes must be finite "
            "nonnegative numbers"
        )
    elif not release_requirements["process_rss_growth_within_limit"]:
        reasons.append(
            "NON-RELEASE: process-RSS growth "
            f"{process_rss.get('growth_bytes')} exceeds "
            f"{MAX_RSS_GROWTH_BYTES} bytes"
        )
    if not release_requirements["exact_manifest_device_identity"]:
        reasons.append(
            "NON-RELEASE: exact validation-manifest and device identity "
            "evidence is required"
        )
    if result.get("result") != "PASS":
        failure = result.get("failure")
        if isinstance(failure, Mapping):
            reasons.append(
                f"{failure.get('category', 'failure')}: "
                f"{failure.get('message', 'no detail')}"
            )
            return reasons
        reasons.append("validation did not pass")
        return reasons
    reasons.extend(
        [
            (
                "COM metadata and two stable INFO responses matched the pinned identity"
                if release_requirements["exact_manifest_device_identity"]
                else "COM metadata and two stable INFO responses identified one stable "
                "diagnostic device"
            ),
            "every decoded frame passed structure and Adler-32 validation",
            "run IDs, independent sequences, timestamps, counts, and rates reconciled",
            "live and final STATUS counters and bounded queue depths reconciled",
            "command latency requirements passed",
            "STOP reached IDLE and the serial close completed within its deadline",
        ]
    )
    if all(
        release_requirements[name]
        for name in (
            *rss_validity_requirements,
            "process_rss_growth_within_limit",
        )
    ):
        reasons.append(
            "complete numeric process-RSS evidence remained within its growth limit"
        )
    return reasons


def _is_nonnegative_finite_number(value: object) -> bool:
    return (
        isinstance(value, (int, float))
        and not isinstance(value, bool)
        and value >= 0
        and (not isinstance(value, float) or math.isfinite(value))
    )


def _windows_release_requirements(
    result: Mapping[str, object],
    *,
    arguments: argparse.Namespace,
    duration: float,
    host: Mapping[str, object],
    exact_manifest_device_identity: bool,
    process_rss: Mapping[str, object],
) -> dict[str, bool]:
    baseline = process_rss.get("baseline_bytes")
    peak = process_rss.get("peak_bytes")
    growth = process_rss.get("growth_bytes")
    growth_valid = _is_nonnegative_finite_number(growth)
    growth_within_limit = (
        growth_valid
        and isinstance(growth, (int, float))
        and growth <= MAX_RSS_GROWTH_BYTES
    )
    return {
        "physical_combined_mode": arguments.mode == "combined",
        "exact_3600_second_duration": duration == WINDOWS_DEFAULT_DURATION_SECONDS,
        "non_smoke": not bool(arguments.smoke),
        "diagnostic_identity_override_disabled": not bool(
            arguments.diagnostic_identity_override
        ),
        "native_windows_host": (
            host.get("system") == "Windows" and host.get("sys_platform") == "win32"
        ),
        "overall_pass": result.get("result") == "PASS",
        "exact_manifest_device_identity": exact_manifest_device_identity,
        "process_rss_baseline_valid": _is_nonnegative_finite_number(baseline),
        "process_rss_peak_valid": _is_nonnegative_finite_number(peak),
        "process_rss_growth_valid": growth_valid,
        "process_rss_growth_within_limit": growth_within_limit,
    }


def attach_windows_evidence(
    result: dict[str, object],
    *,
    arguments: argparse.Namespace,
    duration: float,
    candidates: tuple[WindowsPortCandidate, ...],
    probes: tuple[WindowsProbeResult, ...],
    selected: WindowsPortCandidate | None,
    lifecycle: list[dict[str, object]],
) -> None:
    diagnostic_override = bool(arguments.diagnostic_identity_override)
    host = windows_host_identity()
    selected_probe = next(
        (
            probe
            for probe in probes
            if selected is not None and probe.candidate == selected and probe.passed
        ),
        None,
    )
    identity_mismatches = (
        selected_probe.identity_mismatches if selected_probe is not None else {}
    )
    generated_manifest = GENERATED_CONFIG.get("validation_manifest")
    manifest_map = generated_manifest if isinstance(generated_manifest, Mapping) else {}
    manifest_expected = manifest_map.get("expected_info")
    manifest_expected_map = (
        manifest_expected if isinstance(manifest_expected, Mapping) else {}
    )
    expected = result.get("expected")
    expected_map = expected if isinstance(expected, Mapping) else {}
    program = result.get("program")
    program_map = program if isinstance(program, Mapping) else {}
    manifest_sha256 = GENERATED_CONFIG.get("validation_manifest_sha256")
    release_identity_match = (
        selected_probe is not None
        and not identity_mismatches
        and bool(manifest_expected_map)
        and isinstance(manifest_sha256, str)
        and len(manifest_sha256) == 64
        and selected_probe.observed_identity == dict(manifest_expected_map)
        and expected_map.get("validation_manifest_sha256") == manifest_sha256
        and program_map.get("validation_manifest_sha256") == manifest_sha256
    )
    metrics = result.get("metrics")
    metrics_map = metrics if isinstance(metrics, Mapping) else {}
    memory = metrics_map.get("memory")
    memory_map = memory if isinstance(memory, Mapping) else {}
    process_rss_value = memory_map.get("process_rss")
    process_rss = process_rss_value if isinstance(process_rss_value, Mapping) else {}
    release_requirements = _windows_release_requirements(
        result,
        arguments=arguments,
        duration=duration,
        host=host,
        exact_manifest_device_identity=release_identity_match,
        process_rss=process_rss,
    )
    release_profile = all(
        release_requirements[name] for name in _WINDOWS_RELEASE_PROFILE_REQUIREMENTS
    )
    result["report_schema_version"] = WINDOWS_REPORT_SCHEMA_VERSION
    result["windows"] = {
        "profile": (
            "diagnostic-identity-override"
            if diagnostic_override
            else ("release" if release_profile else "diagnostic")
        ),
        "release_eligible": all(release_requirements.values()),
        "release_requirements": release_requirements,
        "diagnostic_identity_override": {
            "requested": diagnostic_override,
            "release_eligible": False if diagnostic_override else None,
            "identity_mismatches": identity_mismatches,
        },
        "requested_mode": arguments.mode,
        "requested_duration_seconds": duration,
        "smoke": bool(arguments.smoke),
        "requested_hardware_serial": arguments.hardware_serial,
        "explicit_port": arguments.port,
        "host": host,
        "com_discovery": {
            "teensy_vid": TEENSY_USB_SERIAL_VID,
            "teensy_pid": TEENSY_USB_SERIAL_PID,
            "preferred_product": TEENSY_DAQ_PRODUCT,
            "candidate_count": len(candidates),
            "candidates": [candidate.as_dict() for candidate in candidates],
            "probes": [probe.as_dict() for probe in probes],
            "selected": selected.as_dict() if selected is not None else None,
            "selected_release_identity_match": release_identity_match,
        },
        "serial_lifecycle": lifecycle,
        "generation": {
            "entry_point": GENERATED_CONFIG.get("entry_point"),
            "generator_schema_version": GENERATED_CONFIG.get(
                "generator_schema_version"
            ),
            "windows_driver_sha256": GENERATED_CONFIG.get("windows_driver_sha256"),
            "windows_profile_sha256": GENERATED_CONFIG.get("windows_profile_sha256"),
            "validation_manifest_sha256": GENERATED_CONFIG.get(
                "validation_manifest_sha256"
            ),
        },
        "validation_manifest": {
            "schema_version": manifest_map.get("schema_version"),
            "kind": manifest_map.get("kind"),
            "related": manifest_map.get("related"),
            "semantic_sha256": GENERATED_CONFIG.get("validation_manifest_sha256"),
        },
        "validation_reasons": _windows_validation_reasons(
            result,
            diagnostic_identity_override=diagnostic_override,
            identity_mismatches=identity_mismatches,
            release_requirements=release_requirements,
            process_rss=process_rss,
        ),
    }


def _mark_close_failure(
    result: dict[str, object],
    lifecycle: list[dict[str, object]],
) -> bool:
    failed = any(
        not item.get("attempted")
        or not item.get("completed")
        or item.get("timed_out")
        or item.get("error") is not None
        for item in lifecycle
    )
    if not failed or result.get("result") != "PASS":
        return failed
    result["result"] = "FAIL"
    result["failure"] = {
        "category": "cleanup",
        "type": "SerialCloseError",
        "message": f"serial close did not complete cleanly: {lifecycle}",
    }
    cleanup = result.get("cleanup")
    if isinstance(cleanup, dict):
        cleanup["normal_close"] = False
        cleanup["serial_lifecycle"] = lifecycle
    return True


def _markdown_cell(value: object) -> str:
    if value is None:
        return "n/a"
    return str(value).replace("|", "\\|").replace("\r", " ").replace("\n", " ")


def _metric(value: object, *, scale: float = 1.0, digits: int = 3) -> str:
    if not isinstance(value, (int, float)) or isinstance(value, bool):
        return "n/a"
    return f"{float(value) * scale:.{digits}f}"


def render_windows_markdown(result: Mapping[str, object]) -> str:
    completed = result.get("completed_utc")
    created = (
        str(completed)[:10]
        if isinstance(completed, str) and len(completed) >= 10
        else datetime.now(timezone.utc).date().isoformat()
    )
    windows = result.get("windows")
    windows_map = windows if isinstance(windows, Mapping) else {}
    override = windows_map.get("diagnostic_identity_override")
    override_map = override if isinstance(override, Mapping) else {}
    override_requested = override_map.get("requested") is True
    raw_mismatches = override_map.get("identity_mismatches")
    mismatch_map = raw_mismatches if isinstance(raw_mismatches, Mapping) else {}
    mismatch_lines = [
        (
            f"| {_markdown_cell(name)} | "
            f"{_markdown_cell(values.get('expected'))} | "
            f"{_markdown_cell(values.get('actual'))} |"
        )
        for name, raw_values in sorted(mismatch_map.items())
        for values in ([raw_values] if isinstance(raw_values, Mapping) else [{}])
    ] or ["| None | n/a | n/a |"]
    override_warning = (
        [
            "> [!WARNING]",
            (
                "> `--diagnostic-identity-override` was supplied. This report is "
                "**NON-RELEASE** regardless of PASS/FAIL; it does not validate the "
                "accepted Phase 11 firmware/device identity."
            ),
            "",
        ]
        if override_requested
        else []
    )
    discovery = windows_map.get("com_discovery")
    discovery_map = discovery if isinstance(discovery, Mapping) else {}
    selected = discovery_map.get("selected")
    selected_map = selected if isinstance(selected, Mapping) else {}
    host = windows_map.get("host")
    host_map = host if isinstance(host, Mapping) else {}
    expected = result.get("expected")
    expected_map = expected if isinstance(expected, Mapping) else {}
    observed = result.get("observed_identity")
    observed_map = observed if isinstance(observed, Mapping) else {}
    metrics = result.get("metrics")
    metrics_map = metrics if isinstance(metrics, Mapping) else {}
    latency = metrics_map.get("latency")
    latency_map = latency if isinstance(latency, Mapping) else {}
    status_latency = latency_map.get("status")
    status_latency_map = status_latency if isinstance(status_latency, Mapping) else {}
    command_latency = latency_map.get("all_commands")
    command_latency_map = (
        command_latency if isinstance(command_latency, Mapping) else {}
    )
    memory = metrics_map.get("memory")
    memory_map = memory if isinstance(memory, Mapping) else {}
    traced = memory_map.get("tracemalloc")
    traced_map = traced if isinstance(traced, Mapping) else {}
    rss = memory_map.get("process_rss")
    rss_map = rss if isinstance(rss, Mapping) else {}
    failure = result.get("failure")
    failure_map = failure if isinstance(failure, Mapping) else {}
    reasons = windows_map.get("validation_reasons")
    reason_lines = (
        [f"- {_markdown_cell(reason)}" for reason in reasons]
        if isinstance(reasons, list)
        else ["- Validation detail unavailable"]
    )
    epochs = result.get("epochs")
    epoch = epochs[0] if isinstance(epochs, list) and epochs else {}
    epoch_map = epoch if isinstance(epoch, Mapping) else {}
    counters = epoch_map.get("final_counters")
    counter_map = counters if isinstance(counters, Mapping) else {}
    parser = epoch_map.get("parser")
    parser_map = parser if isinstance(parser, Mapping) else {}
    counter_lines = [
        f"| {_markdown_cell(name)} | {_markdown_cell(value)} |"
        for name, value in sorted(counter_map.items())
    ] or ["| n/a | n/a |"]
    raw_json = json.dumps(result, indent=2, sort_keys=True)
    return "\n".join(
        [
            "---",
            "type: report",
            "title: Teensy DAQ Windows Soak Report",
            f"created: {created}",
            "tags:",
            "  - teensy-daq",
            "  - windows",
            "  - soak-validation",
            "related:",
            "  - '[[Phase-11-Soak-Evidence]]'",
            "  - '[[Quickstart]]'",
            "  - '[[Hardware-Safety]]'",
            "  - '[[Protocol-V1]]'",
            "---",
            "",
            "# Teensy DAQ Windows soak report",
            "",
            *override_warning,
            "## Outcome",
            "",
            (
                f"**{_markdown_cell(result.get('result'))}"
                f"{' (NON-RELEASE DIAGNOSTIC)' if override_requested else ''}** — "
                f"{_markdown_cell(failure_map.get('category', 'all checks passed'))}: "
                f"{_markdown_cell(failure_map.get('message', 'validation completed'))}"
            ),
            "",
            *reason_lines,
            "",
            "| Run property | Value |",
            "| --- | --- |",
            f"| Profile | {_markdown_cell(windows_map.get('profile'))} |",
            f"| Release eligible | {_markdown_cell(windows_map.get('release_eligible'))} |",
            f"| Diagnostic identity override | {_markdown_cell(override_requested)} |",
            f"| Mode | {_markdown_cell(result.get('mode'))} |",
            f"| Requested duration (s) | {_markdown_cell(windows_map.get('requested_duration_seconds'))} |",
            f"| Completed UTC | {_markdown_cell(completed)} |",
            "",
            "## Host, COM, and device identity",
            "",
            "| Identity | Value |",
            "| --- | --- |",
            f"| Hostname | {_markdown_cell(host_map.get('hostname'))} |",
            f"| Platform | {_markdown_cell(host_map.get('platform'))} |",
            f"| Python | {_markdown_cell(host_map.get('python_implementation'))} {_markdown_cell(host_map.get('python_version'))} |",
            f"| PySerial | {_markdown_cell(host_map.get('pyserial_version'))} |",
            f"| COM port | {_markdown_cell(selected_map.get('port'))} |",
            f"| USB VID:PID | {_markdown_cell(selected_map.get('vid_pid'))} |",
            f"| USB product | {_markdown_cell(selected_map.get('product'))} |",
            f"| USB serial | {_markdown_cell(selected_map.get('serial_number'))} |",
            f"| INFO hardware serial | {_markdown_cell(observed_map.get('hardware_serial'))} |",
            f"| Firmware version | {_markdown_cell(observed_map.get('firmware_version'))} |",
            f"| Build ID | {_markdown_cell(observed_map.get('build_id'))} |",
            f"| Expected source ID | {_markdown_cell(expected_map.get('source_id'))} |",
            f"| Expected HEX SHA-256 | {_markdown_cell(expected_map.get('artifact_sha256'))} |",
            f"| Validation manifest SHA-256 | {_markdown_cell(expected_map.get('validation_manifest_sha256'))} |",
            "",
            "## Release identity comparison",
            "",
            "| INFO field | Expected | Actual |",
            "| --- | --- | --- |",
            *mismatch_lines,
            "",
            "## Rates, latency, and memory",
            "",
            "| Metric | Value |",
            "| --- | ---: |",
            f"| Payload B/s | {_metric(metrics_map.get('payload_bytes_per_streaming_second'))} |",
            f"| Framed B/s | {_metric(metrics_map.get('framed_bytes_per_streaming_second'))} |",
            f"| ADC pairs/s | {_metric(metrics_map.get('adc_pair_rate_hz'))} |",
            f"| GPIO samples/s | {_metric(metrics_map.get('gpio_sample_rate_hz'))} |",
            f"| STATUS p99 (ms) | {_metric(status_latency_map.get('p99_seconds'), scale=1_000.0)} |",
            f"| STATUS maximum (ms) | {_metric(status_latency_map.get('maximum_seconds'), scale=1_000.0)} |",
            f"| Any-command maximum (ms) | {_metric(command_latency_map.get('maximum_seconds'), scale=1_000.0)} |",
            f"| Tracemalloc growth (bytes) | {_markdown_cell(traced_map.get('growth_bytes'))} |",
            f"| Process RSS growth (bytes) | {_markdown_cell(rss_map.get('growth_bytes'))} |",
            f"| Parser bytes / frames | {_markdown_cell(parser_map.get('bytes_received'))} / {_markdown_cell(parser_map.get('frames_decoded'))} |",
            f"| Parser errors / retained bytes | {_markdown_cell(parser_map.get('errors'))} / {_markdown_cell(parser_map.get('buffered_bytes'))} |",
            "",
            "## Final firmware counters",
            "",
            "| Counter | Value |",
            "| --- | ---: |",
            *counter_lines,
            "",
            "## Complete machine-readable record",
            "",
            "```json",
            raw_json,
            "```",
            "",
        ]
    )


def _report_paths(base: Path) -> tuple[Path, Path]:
    if base.suffix.casefold() in {".json", ".md"}:
        base = base.with_suffix("")
    return Path(f"{base}.json"), Path(f"{base}.md")


def _atomic_text_write(path: Path, contents: str) -> None:
    path.parent.mkdir(parents=True, exist_ok=True)
    temporary = path.with_name(path.name + ".tmp")
    try:
        with temporary.open("w", encoding="utf-8", newline="\n") as handle:
            handle.write(contents)
        os.replace(temporary, path)
    finally:
        try:
            temporary.unlink()
        except FileNotFoundError:
            pass


def write_windows_reports(
    base: Path,
    result: dict[str, object],
) -> tuple[Path, Path]:
    json_path, markdown_path = _report_paths(base)
    windows = result.get("windows")
    if isinstance(windows, dict):
        windows["reports"] = {
            "json": str(json_path),
            "markdown": str(markdown_path),
        }
    _atomic_text_write(
        json_path,
        json.dumps(result, indent=2, sort_keys=True) + "\n",
    )
    _atomic_text_write(markdown_path, render_windows_markdown(result))
    return json_path, markdown_path


def _windows_emit_event(name: str, **fields: object) -> None:
    if name == "sync_retry":
        print(
            f"Synchronization retry {fields.get('attempt')}: {fields.get('error')}",
            flush=True,
        )
    elif name == "synchronized":
        print(
            f"Identity synchronized in {fields.get('attempts')} attempt(s)", flush=True
        )
    elif name == "warmup_complete":
        print("Warm-up complete; measured validation started", flush=True)
    elif name == "status_checkpoint":
        elapsed = fields.get("elapsed_seconds")
        planned = fields.get("planned_seconds")
        percent = (
            min(100.0, 100.0 * float(elapsed) / float(planned))
            if isinstance(elapsed, (int, float))
            and isinstance(planned, (int, float))
            and planned > 0
            else 0.0
        )
        print(
            f"Progress {percent:5.1f}% | "
            f"ADC frames {fields.get('adc_frames')} | "
            f"GPIO frames {fields.get('gpio_frames')} | "
            f"STATUS {fields.get('status_count')}",
            flush=True,
        )
    elif name == "epoch_complete":
        measured = fields.get("measured_elapsed_seconds")
        measured_seconds = (
            float(measured)
            if isinstance(measured, (int, float)) and not isinstance(measured, bool)
            else 0.0
        )
        print(
            f"Stream complete: {measured_seconds:.3f}s, "
            f"{fields.get('payload_bytes')} payload bytes",
            flush=True,
        )


def main(argv: list[str] | None = None) -> int:
    arguments = build_windows_parser().parse_args(argv)
    if arguments.conformance_check:
        print(
            SOAK_CONFORMANCE_PREFIX
            + json.dumps(
                soak_conformance_vector(),
                sort_keys=True,
                separators=(",", ":"),
            )
        )
        return 0
    duration = (
        WINDOWS_SMOKE_DURATION_SECONDS if arguments.smoke else float(arguments.duration)
    )
    settings: RuntimeSettings | None = None
    candidates: tuple[WindowsPortCandidate, ...] = ()
    probes: tuple[WindowsProbeResult, ...] = ()
    selected: WindowsPortCandidate | None = None
    factory: WindowsPortFactory | None = None
    exit_code = 2
    try:
        settings = windows_runtime_settings(
            arguments.mode,
            duration,
            diagnostic_identity_override=arguments.diagnostic_identity_override,
        )
        if arguments.diagnostic_identity_override:
            print(
                "WARNING: diagnostic identity override enabled; every outcome is "
                "NON-RELEASE and cannot validate the Phase 11 candidate identity",
                flush=True,
            )
        requested_serial = (
            settings.hardware_serial
            if arguments.hardware_serial is None
            else arguments.hardware_serial
        )
        if (
            requested_serial != settings.hardware_serial
            and not arguments.diagnostic_identity_override
        ):
            raise SoakFailure(
                "identity",
                f"this release validator is pinned to hardware serial "
                f"{settings.hardware_serial}; requested {requested_serial}",
            )
        arguments.hardware_serial = requested_serial
        print(
            f"Scanning for Teensy DAQ {TEENSY_USB_SERIAL_VID:04X}:"
            f"{TEENSY_USB_SERIAL_PID:04X} COM ports...",
            flush=True,
        )
        candidates = enumerate_windows_candidates()
        if arguments.port is not None:
            candidates = tuple(
                candidate
                for candidate in candidates
                if candidate.port.casefold() == arguments.port.casefold()
            )
            if not candidates:
                raise SoakFailure(
                    "discovery",
                    f"{arguments.port!r} is not an enumerated plausible Teensy COM port",
                )
        if not candidates:
            raise SoakFailure(
                "discovery",
                "no COM ports matched Teensy USB Serial VID/PID metadata",
            )
        probes = probe_windows_candidates(
            candidates,
            settings,
            discovery_timeout_seconds=arguments.discovery_timeout,
            open_timeout_seconds=arguments.open_timeout,
        )
        selected = select_windows_candidate(
            probes,
            hardware_serial=requested_serial,
        )
        print(
            f"Selected {selected.port} by INFO hardware serial {requested_serial}; "
            f"starting {duration:g}s {arguments.mode} validation",
            flush=True,
        )
        factory = WindowsPortFactory(
            selected,
            open_timeout_seconds=arguments.open_timeout,
        )
        global emit_event
        emit_event = _windows_emit_event
        exit_code, result = run_generated(settings, factory)
        lifecycle = factory.summary()
        if _mark_close_failure(result, lifecycle):
            exit_code = 1
    except BaseException as error:  # noqa: BLE001 - all exits receive reports
        result = windows_failure_result(
            error,
            settings=settings,
            mode=arguments.mode,
        )
        lifecycle = factory.summary() if factory is not None else []
        exit_code = 130 if isinstance(error, KeyboardInterrupt) else 2
    attach_windows_evidence(
        result,
        arguments=arguments,
        duration=duration,
        candidates=candidates,
        probes=probes,
        selected=selected,
        lifecycle=lifecycle,
    )
    try:
        json_path, markdown_path = write_windows_reports(arguments.output, result)
    except BaseException as error:  # noqa: BLE001 - report failure must be explicit
        print(
            f"FAIL report_write: {type(error).__name__}: {error}",
            file=sys.stderr,
            flush=True,
        )
        return 3
    failure = result.get("failure")
    failure_map = failure if isinstance(failure, Mapping) else {}
    if result.get("result") == "PASS":
        pass_label = (
            "PASS (NON-RELEASE DIAGNOSTIC IDENTITY OVERRIDE)"
            if arguments.diagnostic_identity_override
            else "PASS"
        )
        print(f"{pass_label} | JSON {json_path} | Markdown {markdown_path}", flush=True)
    else:
        print(
            f"FAIL {failure_map.get('category', 'validation')}: "
            f"{failure_map.get('message', 'no detail')} | "
            f"JSON {json_path} | Markdown {markdown_path}",
            flush=True,
        )
    return exit_code


if __name__ == "__main__":
    raise SystemExit(main())
# </soak-cli>
