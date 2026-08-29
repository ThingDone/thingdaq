"""Synchronous public API built on the shared transport and reader layers."""

from __future__ import annotations

from collections import deque
from collections.abc import Callable, Iterator
from dataclasses import replace
from threading import RLock
from time import sleep
from types import TracebackType
from typing import Literal, TypeAlias

from ._generated import protocol_constants as constants
from .checksum import HOST_SUPPORTED_CHECKSUM_ALGORITHMS
from .discovery import (
    DEFAULT_DISCOVERY_TIMEOUT,
    DeviceNotFoundError,
    DiscoveredDevice,
    HardwareSerial,
    SerialPortCandidate,
    select_device,
)
from .discovery import (
    discover as discover_devices,
)
from .identity import (
    DeviceIdentitySnapshot,
    ExpectedDeviceIdentity,
    IdentityValidationError,
    validate_device_identity,
)
from .models import (
    AdcAcquisitionStatus,
    ADCBlock,
    CommandResponse,
    DAQConfiguration,
    DeviceCapabilities,
    DeviceInfo,
    FirmwareCounters,
    FirmwareLossEvidence,
    GPIOBlock,
    GpioCaptureDiagnosticResult,
    GpioClockDiagnosticRequest,
    GpioClockDiagnosticResult,
    HostCounters,
    HostQueueLoss,
    LossCounters,
    ResponseValue,
    Status,
    StreamAnomaly,
    StreamAnomalyReason,
    StreamGap,
    analyze_stream_continuity,
)
from .protocol import ParserCounters
from .reader import (
    DEFAULT_MAX_QUEUED_BLOCKS,
    BackgroundReader,
    DeviceDisconnectedError,
    QueueWaitTimeoutError,
    ReaderClosedError,
    ReaderCounters,
    ReaderProtocolError,
    RequestTimeoutError,
    StreamStoppedError,
)
from .simulator import SimulatedDevice
from .synthetic import SyntheticPatternError, validate_synthetic_block
from .transport import ByteTransport, InMemoryTransport, SerialTransport

DataBlock: TypeAlias = ADCBlock | GPIOBlock
LossReport: TypeAlias = StreamGap | HostQueueLoss | StreamAnomaly
StreamItem: TypeAlias = DataBlock | LossReport
SerialTransportFactory: TypeAlias = Callable[[str], ByteTransport]


def _decimal_hardware_serial(value: str | None) -> int | None:
    if value is None or not value.isascii() or not value.isdecimal():
        return None
    parsed = int(value, 10)
    return parsed if parsed <= constants.UINT32_MAX else None


class TeensyDAQError(RuntimeError):
    """Base error raised by the synchronous Teensy DAQ facade."""


class DAQClosedError(TeensyDAQError):
    """An operation was attempted after :meth:`TeensyDAQ.close`."""


class CommandTimeoutError(TeensyDAQError):
    """A bounded command exchange ended without its correlated response."""

    def __init__(self, error: RequestTimeoutError) -> None:
        super().__init__(str(error))
        self.command = error.kind
        self.request_id = error.request_id
        self.timeout = error.timeout


class BlockTimeoutError(TeensyDAQError):
    """No decoded stream item arrived before the requested deadline."""

    def __init__(self, timeout: float) -> None:
        super().__init__(f"block wait exceeded {timeout:g} seconds")
        self.timeout = timeout


class DeviceCommandError(TeensyDAQError):
    """The device returned a typed protocol error for a command."""

    def __init__(
        self,
        command: constants.FrameKind,
        error_code: constants.ErrorCode,
        request_id: int,
    ) -> None:
        super().__init__(
            f"{command.name} request {request_id} failed with {error_code.name}"
        )
        self.command = command
        self.error_code = error_code
        self.request_id = request_id


class DAQStateError(DeviceCommandError):
    """A public operation is illegal in the current protocol state."""

    def __init__(
        self,
        operation: str,
        state: constants.DeviceState | None,
        allowed: frozenset[constants.DeviceState],
    ) -> None:
        state_name = "UNKNOWN" if state is None else state.name
        legal = ", ".join(item.name for item in sorted(allowed, key=int))
        TeensyDAQError.__init__(
            self,
            f"{operation} is not valid in {state_name}; expected {legal}",
        )
        self.command = {
            "configure": constants.FrameKind.CONFIGURE_REQUEST,
            "gpio_clock_diagnostic": (
                constants.FrameKind.GPIO_CLOCK_DIAGNOSTIC_REQUEST
            ),
            "gpio_capture_diagnostic": (
                constants.FrameKind.GPIO_CAPTURE_DIAGNOSTIC_REQUEST
            ),
            "start": constants.FrameKind.START_REQUEST,
            "reset_stats": constants.FrameKind.RESET_STATS_REQUEST,
            "stop": constants.FrameKind.STOP_REQUEST,
        }.get(operation, constants.FrameKind.GET_STATUS_REQUEST)
        self.error_code = constants.ErrorCode.INVALID_STATE
        self.request_id = 0
        self.operation = operation
        self.state = state
        self.allowed = allowed


class DeviceCapabilityError(DeviceCommandError):
    """The requested configuration is absent from the advertised capabilities."""

    def __init__(
        self,
        message: str,
        *,
        command: constants.FrameKind = constants.FrameKind.CONFIGURE_REQUEST,
        error_code: constants.ErrorCode = constants.ErrorCode.UNSUPPORTED_CONFIGURATION,
    ) -> None:
        TeensyDAQError.__init__(self, message)
        self.command = command
        self.error_code = error_code
        self.request_id = 0


class MultipleDevicesFoundError(TeensyDAQError):
    """Automatic open found more than one DAQ and needs a hardware serial."""


class DeviceIdentityMismatchError(TeensyDAQError):
    """INFO does not match the selected target or expected firmware image."""


class DeviceSynchronizationError(TeensyDAQError):
    """A bounded open did not produce two stable INFO responses."""


class UnexpectedMessageError(TeensyDAQError):
    """A valid decoded message violates the active public-API operation."""


class UnexpectedStreamGapError(TeensyDAQError):
    """Strict mode observed a stream gap instead of silently continuing."""

    def __init__(self, gap: StreamGap, block: DataBlock) -> None:
        super().__init__(
            f"unexpected {gap.kind.name} gap before sequence "
            f"{gap.observed_sequence}: {gap.missing_frames} frame(s), "
            f"{gap.missing_items} item(s), origin={gap.origin.value}"
        )
        self.gap = gap
        self.block = block


class UnexpectedHostQueueLossError(TeensyDAQError):
    """Strict mode observed decoded application-queue eviction."""

    def __init__(self, loss: HostQueueLoss) -> None:
        super().__init__(
            f"unexpected host {loss.kind.name} queue loss in run {loss.run_id}: "
            f"{loss.dropped_blocks} block(s), {loss.dropped_items} item(s), "
            f"policy={loss.policy.value}"
        )
        self.loss = loss


class UnexpectedStreamAnomalyError(TeensyDAQError):
    """Strict mode observed duplicate, reordered, stale, or bad-time data."""

    def __init__(
        self,
        anomaly: StreamAnomaly,
        block: DataBlock | None = None,
    ) -> None:
        super().__init__(
            f"unexpected {anomaly.kind.name} {anomaly.reason.value} frame "
            f"in run {anomaly.observed_run_id} at sequence "
            f"{anomaly.observed_sequence}"
        )
        self.anomaly = anomaly
        self.block = block


class UnexpectedStreamValidationError(UnexpectedMessageError):
    """Strict validation found corrupt data or a nonzero health counter."""

    def __init__(self, category: str, message: str) -> None:
        super().__init__(f"strict stream validation failed ({category}): {message}")
        self.category = category


class HostBufferFullError(TeensyDAQError):
    """The compatibility injection queue has no remaining bounded capacity."""


class TeensyDAQ:
    """State-aware synchronous DAQ API over one :class:`BackgroundReader`.

    ``strict=False`` is the production policy: :meth:`blocks` emits typed
    stream gaps, anomalies, and host queue losses while keeping the live stream
    moving. ``strict=True`` raises the corresponding typed exception. Host
    queue eviction never supplies firmware attribution, and firmware flags and
    cumulative counters remain independent evidence on each stream gap.
    """

    def __init__(
        self,
        transport: ByteTransport,
        *,
        strict: bool = False,
        read_size: int = 64 * 1024,
        max_buffered_blocks: int = DEFAULT_MAX_QUEUED_BLOCKS,
        max_buffered_events: int = 32,
        max_pending_requests: int = 32,
        command_timeout: float = 1.0,
        block_timeout: float = 1.0,
        shutdown_timeout: float = 1.0,
        idle_sleep: float = 0.001,
        operation_byte_budget: int | None = None,
        expected_identity: ExpectedDeviceIdentity | None = None,
        reopened_identity: DeviceIdentitySnapshot | None = None,
    ) -> None:
        if not isinstance(strict, bool):
            raise TypeError("strict must be a boolean")
        if operation_byte_budget is not None and (
            not isinstance(operation_byte_budget, int)
            or isinstance(operation_byte_budget, bool)
            or operation_byte_budget < constants.DATA_FRAME_BYTES
        ):
            raise ValueError("operation_byte_budget must hold a complete data frame")
        if expected_identity is not None and not isinstance(
            expected_identity, ExpectedDeviceIdentity
        ):
            raise TypeError("expected_identity must be ExpectedDeviceIdentity")
        if reopened_identity is not None and not isinstance(
            reopened_identity, DeviceIdentitySnapshot
        ):
            raise TypeError("reopened_identity must be DeviceIdentitySnapshot")

        self._transport = transport
        self._strict = strict
        self._max_buffered_blocks = max_buffered_blocks
        self._command_timeout = float(command_timeout)
        self._block_timeout = float(block_timeout)
        self._expected_identity = expected_identity
        self._reopened_identity = reopened_identity
        self._verified_identity: DeviceIdentitySnapshot | None = None
        self._reader = BackgroundReader(
            transport,
            read_size=read_size,
            max_pending_requests=max_pending_requests,
            max_queued_blocks=max_buffered_blocks,
            max_queued_events=max_buffered_events,
            request_timeout=command_timeout,
            queue_timeout=block_timeout,
            shutdown_timeout=shutdown_timeout,
            idle_sleep=idle_sleep,
        )
        self._lock = RLock()
        self._pending_items: deque[StreamItem] = deque()
        self._state: constants.DeviceState | None = None
        self._configuration: DAQConfiguration | None = None
        self._device_info: DeviceInfo | None = None
        self._last_status: Status | None = None
        self._run_id = 0
        self._expected_sequence: dict[constants.FrameKind, int] = {}
        self._expected_ticks: dict[constants.FrameKind, int] = {}
        self._previous_sequence: dict[constants.FrameKind, int] = {}
        self._inferred_missing_frames: dict[constants.FrameKind, int] = {}
        self._inferred_missing_items: dict[constants.FrameKind, int] = {}
        self._loss_stats_generation: int | None = None
        self._observed_stream_gaps = 0
        self._observed_host_queue_losses = 0
        self._observed_stream_anomalies = 0
        self._protocol_telemetry_errors = 0
        self._telemetry_error_messages: set[str] = set()
        self._host_loss_baseline = HostCounters()
        self._stream_parser_error_baseline = 0
        self._stream_host_drop_baseline = 0
        self._stream_loss_report_drop_baseline = 0
        self._closed = False
        self._reader.start()

    @classmethod
    def open(
        cls,
        device: ByteTransport
        | DiscoveredDevice
        | SerialPortCandidate
        | str
        | None = None,
        *,
        hardware_serial: HardwareSerial | None = None,
        discovery_timeout: float = DEFAULT_DISCOVERY_TIMEOUT,
        serial_transport_factory: SerialTransportFactory | None = None,
        serial_open_timeout: float = 1.0,
        serial_read_timeout: float = 0.05,
        serial_write_timeout: float = 0.25,
        serial_flush_timeout: float = 0.5,
        serial_close_timeout: float = 0.5,
        strict: bool = False,
        read_size: int = 64 * 1024,
        max_buffered_blocks: int = DEFAULT_MAX_QUEUED_BLOCKS,
        max_buffered_events: int = 32,
        max_pending_requests: int = 32,
        command_timeout: float = 1.0,
        block_timeout: float = 1.0,
        shutdown_timeout: float = 1.0,
        idle_sleep: float = 0.001,
        operation_byte_budget: int | None = None,
        expected_identity: ExpectedDeviceIdentity | None = None,
        synchronization_attempts: int = 4,
        synchronization_retry_delay: float = 0.05,
    ) -> TeensyDAQ:
        """Open a transport, discovered device, port, or selected serial number.

        With no ``device``, discovery is performed once. A lone result opens
        directly; multiple results require ``hardware_serial`` so a transient
        COM or ``/dev`` path is never treated as device identity. Every open
        performs INFO through the same reader used for subsequent operations.
        """

        if device is not None and hardware_serial is not None:
            raise ValueError("pass either device or hardware_serial, not both")

        selected: DiscoveredDevice | SerialPortCandidate | str | None = None
        expected_serial: int | None = None
        reopened_identity: DeviceIdentitySnapshot | None = None
        if device is None:
            devices = discover_devices(timeout=discovery_timeout)
            if hardware_serial is not None:
                chosen = select_device(devices, hardware_serial=hardware_serial)
            elif not devices:
                raise DeviceNotFoundError("no compatible Teensy DAQ was discovered")
            elif len(devices) > 1:
                raise MultipleDevicesFoundError(
                    "multiple Teensy DAQs were discovered; select hardware_serial"
                )
            else:
                chosen = devices[0]
            selected = chosen
            expected_serial = chosen.hardware_serial
            reopened_identity = DeviceIdentitySnapshot.from_info(chosen.info)
        elif isinstance(device, DiscoveredDevice):
            selected = device
            expected_serial = device.hardware_serial
            reopened_identity = DeviceIdentitySnapshot.from_info(device.info)
        elif isinstance(device, SerialPortCandidate):
            selected = device
            expected_serial = _decimal_hardware_serial(device.serial_number)
        elif isinstance(device, str):
            selected = device
        elif isinstance(device, ByteTransport):
            transport = device
        else:
            raise TypeError(
                "device must be a byte transport, discovered device, candidate, "
                "port path, or None"
            )

        if selected is not None:
            port = selected.port if not isinstance(selected, str) else selected
            if serial_transport_factory is None:
                transport = SerialTransport(
                    port,
                    open_timeout=serial_open_timeout,
                    read_timeout=serial_read_timeout,
                    write_timeout=serial_write_timeout,
                    flush_timeout=serial_flush_timeout,
                    close_timeout=serial_close_timeout,
                )
            else:
                transport = serial_transport_factory(port)

        if expected_serial is not None:
            if (
                expected_identity is not None
                and expected_identity.hardware_serial is not None
                and expected_identity.hardware_serial != expected_serial
            ):
                raise DeviceIdentityMismatchError(
                    "selected hardware serial conflicts with expected_identity"
                )
            expected_identity = replace(
                expected_identity or ExpectedDeviceIdentity(),
                hardware_serial=expected_serial,
            )

        daq = cls(
            transport,
            strict=strict,
            read_size=read_size,
            max_buffered_blocks=max_buffered_blocks,
            max_buffered_events=max_buffered_events,
            max_pending_requests=max_pending_requests,
            command_timeout=command_timeout,
            block_timeout=block_timeout,
            shutdown_timeout=shutdown_timeout,
            idle_sleep=idle_sleep,
            operation_byte_budget=operation_byte_budget,
            expected_identity=expected_identity,
            reopened_identity=reopened_identity,
        )
        try:
            daq.synchronize(
                attempts=synchronization_attempts,
                retry_delay=synchronization_retry_delay,
            )
            return daq
        except BaseException:
            try:
                daq.close(stop=False)
            except Exception:  # noqa: BLE001, S110 - preserve opening failure
                pass
            raise

    @classmethod
    def simulated(
        cls,
        *,
        control_only: bool = False,
        read_chunk_size: int | None = None,
        write_chunk_size: int | None = None,
        stream_interval: float | None = None,
        strict: bool = False,
        read_size: int = 64 * 1024,
        max_buffered_blocks: int = DEFAULT_MAX_QUEUED_BLOCKS,
        max_buffered_events: int = 32,
        max_pending_requests: int = 32,
        command_timeout: float = 1.0,
        block_timeout: float = 1.0,
        shutdown_timeout: float = 1.0,
        idle_sleep: float = 0.001,
        expected_identity: ExpectedDeviceIdentity | None = None,
        synchronization_attempts: int = 4,
        synchronization_retry_delay: float = 0.05,
    ) -> TeensyDAQ:
        """Open the public API over the deterministic protocol simulator."""

        transport = InMemoryTransport(
            device=SimulatedDevice(control_only=control_only),
            read_chunk_size=read_chunk_size,
            write_chunk_size=write_chunk_size,
            stream_interval=stream_interval,
        )
        return cls.open(
            transport,
            strict=strict,
            read_size=read_size,
            max_buffered_blocks=max_buffered_blocks,
            max_buffered_events=max_buffered_events,
            max_pending_requests=max_pending_requests,
            command_timeout=command_timeout,
            block_timeout=block_timeout,
            shutdown_timeout=shutdown_timeout,
            idle_sleep=idle_sleep,
            expected_identity=expected_identity,
            synchronization_attempts=synchronization_attempts,
            synchronization_retry_delay=synchronization_retry_delay,
        )

    @property
    def transport(self) -> ByteTransport:
        return self._transport

    @property
    def reader(self) -> BackgroundReader:
        return self._reader

    @property
    def is_open(self) -> bool:
        return not self._closed and self._transport.is_open and self._reader.is_running

    @property
    def strict(self) -> bool:
        return self._strict

    @property
    def state(self) -> constants.DeviceState | None:
        return self._state

    @property
    def configuration(self) -> DAQConfiguration | None:
        return self._configuration

    @property
    def device_info(self) -> DeviceInfo | None:
        return self._device_info

    @property
    def verified_identity(self) -> DeviceIdentitySnapshot | None:
        """Stable identity established by two valid synchronized INFO replies."""

        return self._verified_identity

    @property
    def capabilities(self) -> DeviceCapabilities | None:
        info = self._device_info
        return None if info is None else info.capabilities

    @property
    def run_id(self) -> int:
        return self._run_id

    @property
    def reader_counters(self) -> ReaderCounters:
        return self._reader.counters

    @property
    def parser_counters(self) -> ParserCounters:
        return self._reader.parser_counters

    @property
    def host_counters(self) -> HostCounters:
        reader = self._reader.counters
        parser = self._reader.parser_counters
        return HostCounters(
            parser_corruption_events=parser.corruption_events,
            parser_resynchronizations=parser.resynchronizations,
            host_block_queue_drops=reader.host_block_queue_drops,
            host_event_queue_drops=reader.host_event_queue_drops,
            stale_blocks_discarded=reader.stale_blocks_discarded,
            boundary_blocks_discarded=reader.boundary_blocks_discarded,
            late_responses=reader.late_responses,
            request_timeouts=reader.request_timeouts,
            protocol_failures=reader.protocol_failures,
            disconnects=reader.disconnects,
            adc_block_queue_drops=reader.adc_block_queue_drops,
            gpio_block_queue_drops=reader.gpio_block_queue_drops,
            adc_item_queue_drops=reader.adc_item_queue_drops,
            gpio_item_queue_drops=reader.gpio_item_queue_drops,
            loss_report_queue_drops=reader.loss_report_queue_drops,
        )

    def _host_counters_since_loss_baseline(self) -> HostCounters:
        current = self.host_counters
        baseline = self._host_loss_baseline

        def delta(name: str) -> int:
            value = getattr(current, name)
            previous = getattr(baseline, name)
            if value < previous:
                raise ReaderProtocolError(f"host counter {name} moved backwards")
            return value - previous

        return HostCounters(
            parser_corruption_events=delta("parser_corruption_events"),
            parser_resynchronizations=delta("parser_resynchronizations"),
            host_block_queue_drops=delta("host_block_queue_drops"),
            host_event_queue_drops=delta("host_event_queue_drops"),
            stale_blocks_discarded=delta("stale_blocks_discarded"),
            boundary_blocks_discarded=delta("boundary_blocks_discarded"),
            late_responses=delta("late_responses"),
            request_timeouts=delta("request_timeouts"),
            protocol_failures=delta("protocol_failures"),
            disconnects=delta("disconnects"),
            adc_block_queue_drops=delta("adc_block_queue_drops"),
            gpio_block_queue_drops=delta("gpio_block_queue_drops"),
            adc_item_queue_drops=delta("adc_item_queue_drops"),
            gpio_item_queue_drops=delta("gpio_item_queue_drops"),
            loss_report_queue_drops=delta("loss_report_queue_drops"),
        )

    def _reset_loss_observations(self) -> None:
        self._observed_stream_gaps = 0
        self._observed_host_queue_losses = 0
        self._observed_stream_anomalies = 0
        self._protocol_telemetry_errors = 0
        self._telemetry_error_messages.clear()
        self._host_loss_baseline = self.host_counters
        self._stream_host_drop_baseline = (
            self._host_loss_baseline.host_block_queue_drops
        )
        self._stream_loss_report_drop_baseline = (
            self._host_loss_baseline.loss_report_queue_drops
        )

    def synchronize(
        self,
        *,
        attempts: int = 4,
        retry_delay: float = 0.05,
    ) -> DeviceInfo:
        """Discard one valid INFO, then require a stable authoritative INFO.

        Reset/startup noise is handled by the incremental parser. A timeout,
        BOOT-state rejection, or BUSY response may be retried only within the
        explicit attempt count. Two identity-equal successes are required so a
        late response or hot re-enumeration cannot authorize device mutation.
        """

        if not isinstance(attempts, int) or isinstance(attempts, bool) or attempts < 2:
            raise ValueError("synchronization attempts must be an integer at least two")
        if (
            not isinstance(retry_delay, (int, float))
            or isinstance(retry_delay, bool)
            or retry_delay < 0
        ):
            raise ValueError("synchronization retry delay must be nonnegative")

        with self._lock:
            first_identity: DeviceIdentitySnapshot | None = None
            last_retryable: TeensyDAQError | None = None
            for attempt in range(attempts):
                try:
                    info, identity = self._read_info()
                except CommandTimeoutError as error:
                    last_retryable = error
                except DeviceCommandError as error:
                    if error.error_code not in {
                        constants.ErrorCode.BUSY,
                        constants.ErrorCode.INVALID_STATE,
                    }:
                        raise
                    last_retryable = error
                else:
                    if first_identity is None:
                        first_identity = identity
                        last_retryable = None
                    elif identity != first_identity:
                        raise DeviceIdentityMismatchError(
                            "firmware identity changed between synchronization probes"
                        )
                    else:
                        self._verified_identity = identity
                        return info

                if attempt + 1 < attempts and retry_delay:
                    sleep(float(retry_delay))

            if last_retryable is not None:
                raise last_retryable
            raise DeviceSynchronizationError(
                f"only one valid INFO response arrived in {attempts} attempts"
            )

    def info(self) -> DeviceInfo:
        """Return validated identity/capabilities in every post-boot state."""

        with self._lock:
            info, _ = self._read_info()
            return info

    def configure(
        self,
        configuration: DAQConfiguration | None = None,
        *,
        adc: bool = True,
        gpio: bool = True,
        source: constants.Source | int | None = None,
        checksum_algorithm: constants.ChecksumAlgorithm
        | int = constants.DEFAULT_CHECKSUM_ALGORITHM,
    ) -> DAQConfiguration:
        """Apply an atomic configuration without starting acquisition."""

        with self._lock:
            self._require_verified_identity()
            self._require_state(
                "configure",
                constants.DeviceState.IDLE,
                constants.DeviceState.CONFIGURED,
            )
            if configuration is None:
                if not isinstance(adc, bool) or not isinstance(gpio, bool):
                    raise TypeError("adc and gpio selectors must be booleans")
                stream_mask = constants.StreamMask.NONE
                if adc:
                    stream_mask |= constants.StreamMask.ADC
                if gpio:
                    stream_mask |= constants.StreamMask.GPIO
                capabilities = self.capabilities
                selected_checksum = constants.ChecksumAlgorithm(checksum_algorithm)
                if source is None:
                    if stream_mask is constants.StreamMask.NONE:
                        source = constants.Source.HARDWARE
                    else:
                        candidates = (
                            constants.Source.HARDWARE,
                            constants.Source.SYNTHETIC,
                        )
                        source = constants.Source.SYNTHETIC
                    if capabilities is not None and stream_mask:
                        for candidate in candidates:
                            candidate_configuration = DAQConfiguration(
                                stream_mask=stream_mask,
                                source=candidate,
                                data_checksum_algorithm=selected_checksum,
                            )
                            if capabilities.supports_configuration(
                                candidate_configuration
                            ):
                                source = candidate
                                break
                configuration = DAQConfiguration(
                    stream_mask=stream_mask,
                    source=constants.Source(source),
                    data_checksum_algorithm=selected_checksum,
                )
            elif not isinstance(configuration, DAQConfiguration):
                raise TypeError("configuration must be DAQConfiguration")
            self._validate_configuration_capabilities(configuration)

            response = self._command(
                constants.FrameKind.CONFIGURE_REQUEST,
                configuration.to_payload(),
            )
            if not isinstance(response.value, DAQConfiguration):
                raise UnexpectedMessageError(
                    "CONFIGURE response has no DAQConfiguration value"
                )
            self._state = constants.DeviceState.CONFIGURED
            self._configuration = response.value
            self._run_id = response.run_id
            self._last_status = None
            return response.value

    def configure_control_only(self) -> DAQConfiguration:
        """Apply the exact zero-stream profile advertised by Phase 03 firmware."""

        return self.configure(DAQConfiguration.control_only())

    def start(self) -> int:
        """Start a configured acquisition and return its nonzero run ID."""

        with self._lock:
            self._require_verified_identity()
            self._require_state("start", constants.DeviceState.CONFIGURED)
            host_baseline = self.host_counters
            parser_error_baseline = self._reader.parser_counters.corruption_events
            response = self._command(constants.FrameKind.START_REQUEST)
            if not isinstance(response.value, DAQConfiguration):
                raise UnexpectedMessageError(
                    "START response has no DAQConfiguration value"
                )
            if response.run_id == 0:
                raise UnexpectedMessageError("START response has run ID zero")
            self._state = constants.DeviceState.RUNNING
            self._configuration = response.value
            self._run_id = response.run_id
            self._pending_items.clear()
            self._initialize_stream_expectations(response.value)
            self._host_loss_baseline = host_baseline
            self._stream_host_drop_baseline = host_baseline.host_block_queue_drops
            self._stream_loss_report_drop_baseline = (
                host_baseline.loss_report_queue_drops
            )
            self._stream_parser_error_baseline = parser_error_baseline
            self._observed_stream_gaps = 0
            self._observed_host_queue_losses = 0
            self._observed_stream_anomalies = 0
            self._protocol_telemetry_errors = 0
            self._telemetry_error_messages.clear()
            self._loss_stats_generation = None
            self._last_status = None
            return self._run_id

    def status(self) -> Status:
        """Return current state, active configuration, and firmware counters."""

        with self._lock:
            response = self._command(constants.FrameKind.GET_STATUS_REQUEST)
            if not isinstance(response.value, Status):
                raise UnexpectedMessageError("STATUS response has no Status value")
            status = response.value
            self._state = status.device_state
            self._run_id = response.run_id
            self._last_status = status
            if status.device_state is constants.DeviceState.IDLE:
                self._configuration = None
            else:
                self._configuration = DAQConfiguration(
                    stream_mask=status.stream_mask,
                    source=status.source,
                    data_checksum_algorithm=status.data_checksum_algorithm,
                    data_frame_bytes=status.data_frame_bytes,
                )
            return status

    def reset_stats(self) -> int:
        """Reset firmware counters in IDLE/CONFIGURED and return the generation."""

        with self._lock:
            self._require_verified_identity()
            self._require_state(
                "reset_stats",
                constants.DeviceState.IDLE,
                constants.DeviceState.CONFIGURED,
            )
            capabilities = self.capabilities
            if capabilities is not None and not capabilities.supports(
                constants.Capability.RESET_STATS
            ):
                raise DeviceCapabilityError(
                    "device does not advertise RESET_STATS",
                    command=constants.FrameKind.RESET_STATS_REQUEST,
                )
            response = self._command(constants.FrameKind.RESET_STATS_REQUEST)
            if (
                not isinstance(response.value, int)
                or isinstance(response.value, bool)
                or response.value == 0
            ):
                raise UnexpectedMessageError(
                    "RESET_STATS response has no nonzero generation"
                )
            self._clear_stream_expectations()
            self._loss_stats_generation = response.value
            self._reset_loss_observations()
            self._last_status = None
            return response.value

    def gpio_clock_diagnostic(
        self,
        *,
        rate_hz: int = constants.GPIO_CLOCK_PRODUCTION_RATE_HZ,
        event_count: int = constants.GPIO_CLOCK_MAX_EVENT_COUNT,
    ) -> GpioClockDiagnosticResult:
        """Measure the isolated PIT/XBARA/eDMA trigger path while IDLE."""

        request = GpioClockDiagnosticRequest(rate_hz=rate_hz, event_count=event_count)
        with self._lock:
            self._require_verified_identity()
            self._require_state("gpio_clock_diagnostic", constants.DeviceState.IDLE)
            capabilities = self.capabilities
            if capabilities is not None and not capabilities.supports(
                constants.Capability.GPIO_CLOCK_DIAGNOSTIC
            ):
                raise DeviceCapabilityError(
                    "device does not advertise GPIO clock diagnostics",
                    command=constants.FrameKind.GPIO_CLOCK_DIAGNOSTIC_REQUEST,
                )
            response = self._command(
                constants.FrameKind.GPIO_CLOCK_DIAGNOSTIC_REQUEST,
                request.to_payload(),
            )
            if not isinstance(response.value, GpioClockDiagnosticResult):
                raise UnexpectedMessageError(
                    "GPIO clock diagnostic response has no snapshot value"
                )
            if response.value.request != request:
                raise UnexpectedMessageError(
                    "GPIO clock diagnostic response changed the requested window"
                )
            return response.value

    def gpio_capture_diagnostic(self) -> GpioCaptureDiagnosticResult:
        """Run the build-authorized, safe GPIO capture diagnostic while IDLE."""

        with self._lock:
            self._require_verified_identity()
            self._require_state("gpio_capture_diagnostic", constants.DeviceState.IDLE)
            capabilities = self.capabilities
            if capabilities is not None and not capabilities.supports(
                constants.Capability.GPIO_CAPTURE_DIAGNOSTIC
            ):
                raise DeviceCapabilityError(
                    "device does not advertise GPIO capture diagnostics",
                    command=constants.FrameKind.GPIO_CAPTURE_DIAGNOSTIC_REQUEST,
                )
            response = self._command(
                constants.FrameKind.GPIO_CAPTURE_DIAGNOSTIC_REQUEST
            )
            if not isinstance(response.value, GpioCaptureDiagnosticResult):
                raise UnexpectedMessageError(
                    "GPIO capture diagnostic response has no snapshot value"
                )
            return response.value

    def stop(self) -> constants.DeviceState:
        """Idempotently stop acquisition/configuration and enter IDLE."""

        with self._lock:
            self._require_verified_identity()
            self._require_state(
                "stop",
                constants.DeviceState.IDLE,
                constants.DeviceState.CONFIGURED,
                constants.DeviceState.RUNNING,
            )
            response = self._command(constants.FrameKind.STOP_REQUEST)
            if response.value is not constants.DeviceState.IDLE:
                raise UnexpectedMessageError("STOP response did not enter IDLE")
            self._state = constants.DeviceState.IDLE
            self._configuration = None
            self._run_id = response.run_id
            self._clear_stream_expectations(preserve_inferred=True)
            self._pending_items.clear()
            self._last_status = None
            return constants.DeviceState.IDLE

    def read_block(self, *, timeout: float | None = None) -> StreamItem:
        """Return one block or, in production mode, its preceding gap event."""

        selected_timeout = self._block_timeout if timeout is None else timeout
        if (
            not isinstance(selected_timeout, (int, float))
            or isinstance(selected_timeout, bool)
            or selected_timeout <= 0
        ):
            raise ValueError("timeout must be positive")
        selected_timeout = float(selected_timeout)

        with self._lock:
            self._require_state("read_block", constants.DeviceState.RUNNING)
            if self._reader.active_run_id != self._run_id:
                raise UnexpectedMessageError(
                    "block reads require a RUNNING epoch established by this "
                    "TeensyDAQ instance"
                )
            if self._pending_items:
                return self._pending_items.popleft()

        try:
            reader_item = self._reader.get_stream_item(timeout=selected_timeout)
        except QueueWaitTimeoutError as error:
            raise BlockTimeoutError(error.timeout) from error
        except StreamStoppedError as error:
            raise UnexpectedMessageError(
                "the active stream stopped while waiting for a block"
            ) from error

        with self._lock:
            self._ensure_open()
            if isinstance(reader_item, HostQueueLoss):
                return self._process_host_queue_loss(reader_item)
            if isinstance(reader_item, StreamAnomaly):
                return self._process_reader_anomaly(reader_item)
            return self._process_block(reader_item)

    def blocks(
        self,
        count: int | None = None,
        *,
        timeout: float | None = None,
    ) -> Iterator[StreamItem]:
        """Yield blocks plus visible gap events; ``count`` counts only blocks."""

        if count is not None and (
            not isinstance(count, int) or isinstance(count, bool) or count < 0
        ):
            raise ValueError("block count must be a nonnegative integer or None")
        emitted_blocks = 0
        while count is None or emitted_blocks < count:
            with self._lock:
                if self._state is not constants.DeviceState.RUNNING:
                    return
            item = self.read_block(timeout=timeout)
            yield item
            if isinstance(item, (ADCBlock, GPIOBlock)):
                emitted_blocks += 1

    def loss_counters(self, *, refresh: bool = True) -> LossCounters:
        """Return loss domains separately, optionally refreshing GET_STATUS."""

        if refresh:
            firmware = self.status().counters
            firmware_observed = True
        else:
            status = self._last_status
            firmware = status.counters if status is not None else FirmwareCounters()
            firmware_observed = status is not None
        counter_errors = (
            self._counter_reconciliation_errors(firmware) if firmware_observed else ()
        )
        new_errors = tuple(
            error
            for error in counter_errors
            if error not in self._telemetry_error_messages
        )
        if new_errors:
            self._telemetry_error_messages.update(new_errors)
            self._protocol_telemetry_errors += len(new_errors)
        if self._strict and counter_errors:
            raise UnexpectedStreamValidationError(
                "protocol_telemetry",
                "; ".join(counter_errors),
            )
        return LossCounters(
            firmware=firmware,
            host=self._host_counters_since_loss_baseline(),
            observed_stream_gaps=self._observed_stream_gaps,
            observed_host_queue_losses=self._observed_host_queue_losses,
            observed_stream_anomalies=self._observed_stream_anomalies,
            protocol_telemetry_errors=self._protocol_telemetry_errors,
            telemetry_errors=tuple(sorted(self._telemetry_error_messages)),
        )

    def validate_stream_health(self, status: Status | None = None) -> Status:
        """Strictly reject parser, host-queue, and firmware health failures.

        Passing an already retrieved status avoids another command round trip.
        This check is explicit so production callers may continue to use
        :meth:`loss_counters` for observe-and-report behavior even when the
        facade's block policy is strict.
        """

        with self._lock:
            self._ensure_open()
            snapshot = self.status() if status is None else status
            if not isinstance(snapshot, Status):
                raise TypeError("status must be a Status snapshot")
            counter_errors = self._counter_reconciliation_errors(snapshot.counters)
            if counter_errors:
                raise UnexpectedStreamValidationError(
                    "protocol_telemetry",
                    "; ".join(counter_errors),
                )
            parser_errors = (
                self._reader.parser_counters.corruption_events
                - self._stream_parser_error_baseline
            )
            if parser_errors:
                raise UnexpectedStreamValidationError(
                    "parser_errors",
                    f"observed {parser_errors} new rejected frame candidate(s)",
                )
            host_drops = (
                self._reader.counters.host_block_queue_drops
                - self._stream_host_drop_baseline
            )
            if host_drops:
                raise UnexpectedStreamValidationError(
                    "host_queue_drops",
                    f"dropped {host_drops} decoded block(s)",
                )
            loss_report_drops = (
                self._reader.counters.loss_report_queue_drops
                - self._stream_loss_report_drop_baseline
            )
            if loss_report_drops:
                raise UnexpectedStreamValidationError(
                    "loss_report_queue_drops",
                    "bounded host loss-report storage discarded "
                    f"{loss_report_drops} report(s)",
                )
            if self._protocol_telemetry_errors:
                raise UnexpectedStreamValidationError(
                    "protocol_telemetry",
                    "observed "
                    f"{self._protocol_telemetry_errors} continuity/evidence "
                    "disagreement(s)",
                )
            if snapshot.adc_items_dropped or snapshot.gpio_items_dropped:
                raise UnexpectedStreamValidationError(
                    "firmware_drops",
                    "firmware reported "
                    f"{snapshot.adc_items_dropped} ADC pair(s) and "
                    f"{snapshot.gpio_items_dropped} GPIO sample(s) dropped",
                )
            if snapshot.has_adc_errors:
                acquisition_errors = ", ".join(
                    f"{name}={value}"
                    for name, value in snapshot.adc_acquisition.nonzero_error_fields
                )
                raise UnexpectedStreamValidationError(
                    "firmware_adc_errors",
                    "firmware reported ADC initialization="
                    f"{int(snapshot.adc_initialization_error_flags)}, trigger="
                    f"{int(snapshot.adc_trigger.error_flags)}, trigger_events="
                    f"{snapshot.adc_trigger.trigger_error_count}"
                    + (f", {acquisition_errors}" if acquisition_errors else ""),
                )
            if snapshot.parser_errors:
                raise UnexpectedStreamValidationError(
                    "firmware_parser_errors",
                    f"firmware reported {snapshot.parser_errors} parser error(s)",
                )
            if snapshot.transport_errors:
                raise UnexpectedStreamValidationError(
                    "firmware_transport_errors",
                    f"firmware reported {snapshot.transport_errors} transport error(s)",
                )
            return snapshot

    def close(self, *, stop: bool = True) -> None:
        """Close idempotently, normally STOPping configured/running firmware.

        ``stop=False`` is intended for one-shot control-plane tools that must
        release the serial handle while deliberately preserving device state.
        Context-manager cleanup retains the safe default and always requests
        STOP before closing.
        """

        if not isinstance(stop, bool):
            raise TypeError("stop must be a boolean")

        with self._lock:
            if self._closed:
                return
            stop_error: BaseException | None = None
            if (
                stop
                and self._reader.is_running
                and self._state
                in {
                    constants.DeviceState.CONFIGURED,
                    constants.DeviceState.RUNNING,
                }
            ):
                try:
                    self.stop()
                except BaseException as error:  # noqa: BLE001 - close regardless
                    stop_error = error
            try:
                self._reader.close()
            finally:
                self._closed = True
                self._pending_items.clear()
                self._clear_stream_expectations()
            if stop_error is not None:
                raise stop_error

    def __enter__(self) -> TeensyDAQ:  # noqa: PYI034
        self._ensure_open()
        return self

    def __exit__(
        self,
        exception_type: type[BaseException] | None,
        exception: BaseException | None,
        traceback: TracebackType | None,
    ) -> Literal[False]:
        if exception_type is None:
            self.close()
        else:
            try:
                self.close()
            except Exception:  # noqa: BLE001, S110 - preserve block exception
                pass
        return False

    def _command(
        self,
        kind: constants.FrameKind,
        payload: bytes = b"",
        *,
        timeout: float | None = None,
    ) -> CommandResponse[ResponseValue]:
        self._ensure_open()
        try:
            response = self._reader.request(
                kind,
                payload,
                timeout=self._command_timeout if timeout is None else timeout,
            )
        except RequestTimeoutError as error:
            raise CommandTimeoutError(error) from error
        except ReaderClosedError as error:
            raise DAQClosedError("TeensyDAQ is closed") from error
        if not response.ok:
            raise DeviceCommandError(kind, response.error_code, response.request_id)
        expected_kind = constants.REQUEST_RESPONSE_KIND[kind]
        if response.kind is not expected_kind:
            raise UnexpectedMessageError(
                f"expected {expected_kind.name}, received {response.kind.name}"
            )
        return response

    def _read_info(self) -> tuple[DeviceInfo, DeviceIdentitySnapshot]:
        response = self._command(constants.FrameKind.INFO_REQUEST)
        if not isinstance(response.value, DeviceInfo):
            raise UnexpectedMessageError("INFO response has no DeviceInfo value")
        info = response.value
        try:
            identity = validate_device_identity(info, self._expected_identity)
        except IdentityValidationError as error:
            raise DeviceIdentityMismatchError(str(error)) from error
        if self._reopened_identity is not None and identity != self._reopened_identity:
            raise DeviceIdentityMismatchError(
                "reopened firmware identity differs from the discovery probe"
            )
        if self._verified_identity is not None and identity != self._verified_identity:
            raise DeviceIdentityMismatchError(
                "firmware identity changed during the open session"
            )

        previous_run_id = self._run_id
        self._device_info = info
        self._state = info.device_state
        self._run_id = response.run_id
        if previous_run_id != response.run_id:
            self._clear_stream_expectations()
            self._pending_items.clear()
            self._loss_stats_generation = None
            self._reset_loss_observations()
        if info.device_state is constants.DeviceState.IDLE:
            self._configuration = None
        else:
            self._configuration = info.applied_configuration
        return info, identity

    def _require_verified_identity(self) -> None:
        if self._verified_identity is None:
            self.synchronize()

    def _require_state(
        self,
        operation: str,
        *allowed: constants.DeviceState,
    ) -> None:
        self._ensure_open()
        if self._state is None:
            self.info()
        legal = frozenset(allowed)
        if self._state not in legal:
            raise DAQStateError(operation, self._state, legal)

    def _validate_configuration_capabilities(
        self,
        configuration: DAQConfiguration,
    ) -> None:
        if (
            configuration.data_checksum_algorithm
            not in HOST_SUPPORTED_CHECKSUM_ALGORITHMS
        ):
            raise DeviceCapabilityError(
                "host has no implementation for requested checksum "
                f"{configuration.data_checksum_algorithm.name}",
                error_code=constants.ErrorCode.UNSUPPORTED_CHECKSUM,
            )
        capabilities = self.capabilities
        if capabilities is None:
            return
        unsupported_streams = int(configuration.stream_mask) & ~int(
            capabilities.supported_stream_mask
        )
        if unsupported_streams:
            raise DeviceCapabilityError("device does not advertise requested streams")
        if not capabilities.supports_source(configuration.source):
            raise DeviceCapabilityError("device does not advertise requested source")
        if not capabilities.supports_checksum(configuration.data_checksum_algorithm):
            raise DeviceCapabilityError(
                "device does not advertise requested checksum",
                error_code=constants.ErrorCode.UNSUPPORTED_CHECKSUM,
            )
        if not capabilities.supports_configuration(configuration):
            raise DeviceCapabilityError(
                "device does not advertise the exact requested source/stream profile",
                error_code=constants.ErrorCode.UNSUPPORTED_CONFIGURATION,
            )

    def _initialize_stream_expectations(
        self,
        configuration: DAQConfiguration,
    ) -> None:
        self._clear_stream_expectations()
        if configuration.stream_mask & constants.StreamMask.ADC:
            self._expected_sequence[constants.FrameKind.ADC_DATA] = 0
            self._expected_ticks[constants.FrameKind.ADC_DATA] = 0
            self._inferred_missing_frames[constants.FrameKind.ADC_DATA] = 0
            self._inferred_missing_items[constants.FrameKind.ADC_DATA] = 0
        if configuration.stream_mask & constants.StreamMask.GPIO:
            self._expected_sequence[constants.FrameKind.GPIO_DATA] = 0
            self._expected_ticks[constants.FrameKind.GPIO_DATA] = 0
            self._inferred_missing_frames[constants.FrameKind.GPIO_DATA] = 0
            self._inferred_missing_items[constants.FrameKind.GPIO_DATA] = 0

    def _clear_stream_expectations(self, *, preserve_inferred: bool = False) -> None:
        self._expected_sequence.clear()
        self._expected_ticks.clear()
        self._previous_sequence.clear()
        if not preserve_inferred:
            self._inferred_missing_frames.clear()
            self._inferred_missing_items.clear()

    def _observe_loss_stats_generation(self, observed: int) -> str | None:
        if self._loss_stats_generation is None:
            self._loss_stats_generation = observed
            return None
        if self._loss_stats_generation == observed:
            return None
        return (
            "firmware statistics generation changed within the active run: "
            f"expected {self._loss_stats_generation}, observed {observed}"
        )

    def _process_block(self, block: DataBlock) -> StreamItem:
        kind = (
            constants.FrameKind.ADC_DATA
            if isinstance(block, ADCBlock)
            else constants.FrameKind.GPIO_DATA
        )
        if kind not in self._expected_sequence:
            raise UnexpectedMessageError(
                f"received disabled {kind.name} stream for the active configuration"
            )

        configuration = self._configuration
        if configuration is None:
            raise UnexpectedMessageError(
                f"{kind.name} arrived without an active configuration"
            )
        if block.source is not configuration.source:
            raise UnexpectedMessageError(
                f"{kind.name} source flag disagrees with the active configuration"
            )

        if isinstance(block, ADCBlock):
            info = self._device_info
            if info is None:
                raise UnexpectedMessageError(
                    "ADC_DATA arrived without active configuration/INFO metadata"
                )
            acquisition: AdcAcquisitionStatus | None = None
            status = self._last_status
            if (
                status is not None
                and status.device_state is constants.DeviceState.RUNNING
                and status.source is configuration.source
                and status.stream_mask & constants.StreamMask.ADC
            ):
                acquisition = status.adc_acquisition
            try:
                block = replace(
                    block,
                    metadata=info.adc_block_metadata(
                        configuration.source,
                        acquisition=acquisition,
                    ),
                    gap=None,
                )
            except (TypeError, ValueError) as error:
                raise UnexpectedMessageError(
                    f"ADC_DATA contradicts advertised ADC metadata: {error}"
                ) from error

        continuity = analyze_stream_continuity(
            block,
            expected_sequence=self._expected_sequence[kind],
            expected_first_sample_ticks=self._expected_ticks[kind],
            active_run_id=self._run_id,
            previous_sequence=self._previous_sequence.get(kind),
        )
        if continuity is None:
            self._advance_expectation(kind, block)
            self._validate_clean_block(block)
            return block

        if isinstance(continuity, StreamAnomaly):
            anomaly = self._finalize_anomaly_evidence(continuity)
            self._observed_stream_anomalies += anomaly.occurrences
            self._protocol_telemetry_errors += anomaly.occurrences
            self._telemetry_error_messages.add(
                f"{anomaly.kind.name} {anomaly.reason.value} at run/sequence "
                f"{anomaly.observed_run_id}/{anomaly.observed_sequence}"
            )
            retain_block = anomaly.reason not in {
                StreamAnomalyReason.DUPLICATE,
                StreamAnomalyReason.REORDERED,
                StreamAnomalyReason.STALE_RUN,
            }
            if retain_block:
                self._advance_expectation(kind, block)
            if self._strict:
                raise UnexpectedStreamAnomalyError(anomaly, block)
            if retain_block:
                self._pending_items.append(block)
            return anomaly

        self._inferred_missing_frames[kind] += continuity.missing_frames
        self._inferred_missing_items[kind] += continuity.missing_items
        gap = self._finalize_gap_evidence(continuity)
        self._advance_expectation(kind, block)
        if isinstance(block, ADCBlock):
            block = replace(block, gap=gap)
        self._observed_stream_gaps += 1
        evidence = gap.firmware_evidence
        if evidence is not None and not evidence.consistent:
            self._protocol_telemetry_errors += 1
            self._telemetry_error_messages.update(evidence.errors)
        if self._strict:
            raise UnexpectedStreamGapError(gap, block)
        self._pending_items.append(block)
        return gap

    def _advance_expectation(
        self,
        kind: constants.FrameKind,
        block: DataBlock,
    ) -> None:
        self._previous_sequence[kind] = block.sequence
        self._expected_sequence[kind] = (block.sequence + 1) & constants.UINT32_MAX
        self._expected_ticks[kind] = block.end_tick_exclusive

    def _validate_clean_block(self, block: DataBlock) -> None:
        if not self._strict:
            return
        parser_errors = (
            self._reader.parser_counters.corruption_events
            - self._stream_parser_error_baseline
        )
        if parser_errors:
            raise UnexpectedStreamValidationError(
                "parser_errors",
                f"observed {parser_errors} new rejected frame candidate(s)",
            )
        if (
            self._configuration is not None
            and self._configuration.source is constants.Source.SYNTHETIC
        ):
            try:
                validate_synthetic_block(block)
            except SyntheticPatternError as error:
                raise UnexpectedStreamValidationError(
                    "synthetic_pattern",
                    str(error),
                ) from error

    def _finalize_gap_evidence(self, gap: StreamGap) -> StreamGap:
        evidence = self._firmware_evidence(
            gap.kind,
            gap.source,
            gap.firmware_evidence,
        )
        return replace(gap, firmware_evidence=evidence)

    def _finalize_anomaly_evidence(
        self,
        anomaly: StreamAnomaly,
    ) -> StreamAnomaly:
        evidence = self._firmware_evidence(
            anomaly.kind,
            anomaly.source,
            anomaly.firmware_evidence,
        )
        return replace(anomaly, firmware_evidence=evidence)

    def _firmware_evidence(
        self,
        kind: constants.FrameKind,
        source: constants.Source,
        base: FirmwareLossEvidence | None,
    ) -> FirmwareLossEvidence:
        inferred_frames = self._inferred_missing_frames.get(kind, 0)
        inferred_items = self._inferred_missing_items.get(kind, 0)
        gap_before = False if base is None else base.gap_before
        overrun_before = False if base is None else base.overrun_before
        flags_match = True if base is None else base.flags_match
        errors = [] if base is None else list(base.errors)
        stats_generation: int | None = None
        dropped_frames: int | None = None
        dropped_items: int | None = None
        dropped_bytes: int | None = None
        counters_match: bool | None = None
        try:
            status = self.status()
        except (
            CommandTimeoutError,
            DeviceCommandError,
            UnexpectedMessageError,
        ) as error:
            errors.append(f"firmware loss counters unavailable: {error}")
        else:
            stats_generation = status.stats_generation
            generation_error = self._observe_loss_stats_generation(stats_generation)
            if generation_error is not None:
                errors.append(generation_error)
            if kind is constants.FrameKind.ADC_DATA:
                dropped_frames = status.adc_frames_dropped
                dropped_items = status.adc_items_dropped
                dropped_bytes = status.adc_payload_bytes_dropped
                expected_bytes = inferred_items * constants.ADC_BYTES_PER_PAIR
            else:
                dropped_frames = status.gpio_frames_dropped
                dropped_items = status.gpio_items_dropped
                dropped_bytes = status.gpio_payload_bytes_dropped
                expected_bytes = inferred_items
            items_per_frame = (
                constants.ADC_PAIRS_PER_FRAME
                if kind is constants.FrameKind.ADC_DATA
                else constants.GPIO_SAMPLES_PER_FRAME
            )
            bytes_per_item = (
                constants.ADC_BYTES_PER_PAIR
                if kind is constants.FrameKind.ADC_DATA
                else 1
            )
            counter_units_match = (
                dropped_items == dropped_frames * items_per_frame
                and dropped_bytes == dropped_items * bytes_per_item
            )
            if (
                dropped_frames == inferred_frames
                and dropped_items == inferred_items
                and dropped_bytes == expected_bytes
                and counter_units_match
            ):
                counters_match = True
            elif (
                dropped_frames >= inferred_frames
                and dropped_items >= inferred_items
                and dropped_bytes >= expected_bytes
                and counter_units_match
            ):
                # STATUS may cover later frames already drained by the reader
                # but not yet consumed by the application. Preserve the
                # ahead-of-consumer evidence without declaring a false error;
                # loss_counters() requires exact equality at reconciliation.
                counters_match = None
            else:
                counters_match = False
                errors.append(
                    f"{kind.name} cumulative loss counters disagree: "
                    f"host inferred frames/items/bytes="
                    f"{inferred_frames}/{inferred_items}/{expected_bytes}, "
                    f"firmware reported {dropped_frames}/{dropped_items}/"
                    f"{dropped_bytes}"
                )

        return FirmwareLossEvidence(
            source=source,
            gap_before=gap_before,
            overrun_before=overrun_before,
            stats_generation=stats_generation,
            cumulative_dropped_frames=dropped_frames,
            cumulative_dropped_items=dropped_items,
            cumulative_dropped_bytes=dropped_bytes,
            expected_cumulative_frames=inferred_frames,
            expected_cumulative_items=inferred_items,
            flags_match=flags_match,
            counters_match=counters_match,
            errors=tuple(errors),
        )

    def _counter_reconciliation_errors(
        self,
        firmware: FirmwareCounters,
    ) -> tuple[str, ...]:
        errors: list[str] = []
        generation_error = self._observe_loss_stats_generation(
            firmware.stats_generation
        )
        if generation_error is not None:
            errors.append(generation_error)
        for kind, inferred_items in self._inferred_missing_items.items():
            inferred_frames = self._inferred_missing_frames[kind]
            if kind is constants.FrameKind.ADC_DATA:
                actual_frames = firmware.adc_frames_dropped
                actual_items = firmware.adc_items_dropped
                actual_bytes = firmware.adc_payload_bytes_dropped
                expected_bytes = inferred_items * constants.ADC_BYTES_PER_PAIR
            else:
                actual_frames = firmware.gpio_frames_dropped
                actual_items = firmware.gpio_items_dropped
                actual_bytes = firmware.gpio_payload_bytes_dropped
                expected_bytes = inferred_items
            if (
                actual_frames != inferred_frames
                or actual_items != inferred_items
                or actual_bytes != expected_bytes
            ):
                errors.append(
                    f"{kind.name} cumulative loss counters disagree: host "
                    f"inferred frames/items/bytes={inferred_frames}/"
                    f"{inferred_items}/{expected_bytes}, firmware reported "
                    f"{actual_frames}/{actual_items}/{actual_bytes}"
                )
        return tuple(errors)

    def _process_host_queue_loss(self, loss: HostQueueLoss) -> StreamItem:
        kind = loss.kind
        configuration = self._configuration
        range_valid = (
            configuration is not None
            and kind in self._expected_sequence
            and loss.run_id == self._run_id
            and loss.source is configuration.source
            and loss.contiguous
            and loss.first_sequence == self._expected_sequence[kind]
            and loss.first_sample_ticks == self._expected_ticks[kind]
        )
        if not range_valid:
            anomaly = StreamAnomaly(
                reason=StreamAnomalyReason.HOST_QUEUE_RANGE_INCONSISTENT,
                kind=kind,
                source=loss.source,
                active_run_id=self._run_id,
                observed_run_id=loss.run_id,
                expected_sequence=self._expected_sequence.get(kind),
                observed_sequence=loss.first_sequence,
                expected_first_sample_ticks=self._expected_ticks.get(kind),
                observed_first_sample_ticks=loss.first_sample_ticks,
            )
            self._observed_stream_anomalies += 1
            self._protocol_telemetry_errors += 1
            self._telemetry_error_messages.add(
                f"{kind.name} host queue range is inconsistent with the "
                "application continuity baseline"
            )
            self._observed_host_queue_losses += 1
            if kind in self._expected_sequence and loss.run_id == self._run_id:
                self._previous_sequence[kind] = loss.last_sequence
                self._expected_sequence[kind] = (
                    loss.last_sequence + 1
                ) & constants.UINT32_MAX
                self._expected_ticks[kind] = loss.end_sample_ticks
            if self._strict:
                raise UnexpectedStreamAnomalyError(anomaly)
            self._pending_items.append(loss)
            return anomaly

        self._previous_sequence[kind] = loss.last_sequence
        self._expected_sequence[kind] = (loss.last_sequence + 1) & constants.UINT32_MAX
        self._expected_ticks[kind] = loss.end_sample_ticks
        self._observed_host_queue_losses += 1
        if self._strict:
            raise UnexpectedHostQueueLossError(loss)
        return loss

    def _process_reader_anomaly(self, anomaly: StreamAnomaly) -> StreamAnomaly:
        self._observed_stream_anomalies += anomaly.occurrences
        self._protocol_telemetry_errors += anomaly.occurrences
        self._telemetry_error_messages.add(
            f"{anomaly.kind.name} {anomaly.reason.value} at run/sequence "
            f"{anomaly.observed_run_id}/{anomaly.observed_sequence}"
        )
        if self._strict:
            raise UnexpectedStreamAnomalyError(anomaly)
        return anomaly

    def _queue_block(self, block: DataBlock) -> None:
        """Compatibility hook for tests that inject an already decoded block."""

        with self._lock:
            if (
                self._state is constants.DeviceState.RUNNING
                and self._run_id != 0
                and block.run_id != self._run_id
            ):
                raise UnexpectedMessageError(
                    f"stale data run {block.run_id}; active run is {self._run_id}"
                )
            if len(self._pending_items) >= self._max_buffered_blocks:
                raise HostBufferFullError("deferred stream-item queue is full")
            self._pending_items.append(block)

    def _ensure_open(self) -> None:
        if self._closed:
            raise DAQClosedError("TeensyDAQ is closed")
        if not self._reader.is_running:
            counters = self._reader.counters
            if counters.disconnects:
                raise DeviceDisconnectedError("device reader is disconnected")
            if counters.protocol_failures:
                raise ReaderProtocolError("device reader terminated on protocol error")
            raise DAQClosedError("TeensyDAQ reader is not running")
        if not self._transport.is_open:
            raise DAQClosedError("TeensyDAQ transport is closed")


__all__ = [
    "BlockTimeoutError",
    "CommandTimeoutError",
    "DAQClosedError",
    "DAQStateError",
    "DataBlock",
    "DeviceCapabilityError",
    "DeviceCommandError",
    "DeviceIdentityMismatchError",
    "DeviceSynchronizationError",
    "HostBufferFullError",
    "LossReport",
    "MultipleDevicesFoundError",
    "StreamItem",
    "TeensyDAQ",
    "TeensyDAQError",
    "UnexpectedHostQueueLossError",
    "UnexpectedMessageError",
    "UnexpectedStreamAnomalyError",
    "UnexpectedStreamGapError",
    "UnexpectedStreamValidationError",
]
