"""Synchronous public API built on the shared transport and reader layers."""

from __future__ import annotations

from collections import deque
from collections.abc import Callable, Iterator
from threading import RLock
from types import TracebackType
from typing import Literal, TypeAlias

from ._generated import protocol_constants as constants
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
from .models import (
    ADCBlock,
    CommandResponse,
    DAQConfiguration,
    DeviceCapabilities,
    DeviceInfo,
    FirmwareCounters,
    GPIOBlock,
    HostCounters,
    LossCounters,
    ResponseValue,
    Status,
    StreamGap,
)
from .protocol import ParserCounters
from .reader import (
    BackgroundReader,
    DeviceDisconnectedError,
    QueueWaitTimeoutError,
    ReaderClosedError,
    ReaderCounters,
    ReaderProtocolError,
    RequestTimeoutError,
    StreamStoppedError,
)
from .transport import ByteTransport, InMemoryTransport, SerialTransport

DataBlock: TypeAlias = ADCBlock | GPIOBlock
StreamItem: TypeAlias = DataBlock | StreamGap
SerialTransportFactory: TypeAlias = Callable[[str], ByteTransport]


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
    """A reopened port no longer contains the selected physical DAQ."""


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


class HostBufferFullError(TeensyDAQError):
    """The compatibility injection queue has no remaining bounded capacity."""


class TeensyDAQ:
    """State-aware synchronous DAQ API over one :class:`BackgroundReader`.

    ``strict=False`` is the production policy: :meth:`blocks` emits a
    :class:`StreamGap` immediately before the current block and keeps the live
    stream moving. ``strict=True`` raises :class:`UnexpectedStreamGapError`
    with both models attached. Host queue drops and firmware gap/overrun flags
    remain independently attributed in every gap and counter snapshot.
    """

    def __init__(
        self,
        transport: ByteTransport,
        *,
        strict: bool = False,
        read_size: int = 64 * 1024,
        max_buffered_blocks: int = 8,
        max_buffered_events: int = 32,
        max_pending_requests: int = 32,
        command_timeout: float = 1.0,
        block_timeout: float = 1.0,
        shutdown_timeout: float = 1.0,
        idle_sleep: float = 0.001,
        operation_byte_budget: int | None = None,
    ) -> None:
        if not isinstance(strict, bool):
            raise TypeError("strict must be a boolean")
        if operation_byte_budget is not None and (
            not isinstance(operation_byte_budget, int)
            or isinstance(operation_byte_budget, bool)
            or operation_byte_budget < constants.DATA_FRAME_BYTES
        ):
            raise ValueError("operation_byte_budget must hold a complete data frame")

        self._transport = transport
        self._strict = strict
        self._max_buffered_blocks = max_buffered_blocks
        self._command_timeout = float(command_timeout)
        self._block_timeout = float(block_timeout)
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
        self._last_host_queue_drops = 0
        self._unattributed_host_queue_drops = 0
        self._observed_stream_gaps = 0
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
        max_buffered_blocks: int = 8,
        max_buffered_events: int = 32,
        max_pending_requests: int = 32,
        command_timeout: float = 1.0,
        block_timeout: float = 1.0,
        shutdown_timeout: float = 1.0,
        idle_sleep: float = 0.001,
        operation_byte_budget: int | None = None,
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
        elif isinstance(device, DiscoveredDevice):
            selected = device
            expected_serial = device.hardware_serial
        elif isinstance(device, (SerialPortCandidate, str)):
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
        )
        try:
            info = daq.info()
            if expected_serial is not None and info.hardware_serial != expected_serial:
                raise DeviceIdentityMismatchError(
                    f"selected hardware serial {expected_serial} reopened as "
                    f"{info.hardware_serial}"
                )
            return daq
        except BaseException:
            try:
                daq.close()
            except Exception:  # noqa: BLE001, S110 - preserve opening failure
                pass
            raise

    @classmethod
    def simulated(
        cls,
        *,
        read_chunk_size: int | None = None,
        write_chunk_size: int | None = None,
        stream_interval: float | None = None,
        strict: bool = False,
        read_size: int = 64 * 1024,
        max_buffered_blocks: int = 8,
        max_buffered_events: int = 32,
        max_pending_requests: int = 32,
        command_timeout: float = 1.0,
        block_timeout: float = 1.0,
        shutdown_timeout: float = 1.0,
        idle_sleep: float = 0.001,
    ) -> TeensyDAQ:
        """Open the public API over the deterministic protocol simulator."""

        transport = InMemoryTransport(
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
        )

    def info(self) -> DeviceInfo:
        """Return identity and capabilities; valid in every post-boot state."""

        with self._lock:
            response = self._command(constants.FrameKind.INFO_REQUEST)
            if not isinstance(response.value, DeviceInfo):
                raise UnexpectedMessageError("INFO response has no DeviceInfo value")
            info = response.value
            self._device_info = info
            self._state = info.device_state
            self._run_id = response.run_id
            if info.device_state is constants.DeviceState.IDLE:
                self._configuration = None
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
                if source is None:
                    source = (
                        constants.Source.HARDWARE
                        if capabilities is not None
                        and capabilities.supports_source(constants.Source.HARDWARE)
                        else constants.Source.SYNTHETIC
                    )
                configuration = DAQConfiguration(
                    stream_mask=stream_mask,
                    source=constants.Source(source),
                    data_checksum_algorithm=constants.ChecksumAlgorithm(
                        checksum_algorithm
                    ),
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

    def start(self) -> int:
        """Start a configured acquisition and return its nonzero run ID."""

        with self._lock:
            self._require_state("start", constants.DeviceState.CONFIGURED)
            host_drop_baseline = self._reader.counters.host_block_queue_drops
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
            self._last_host_queue_drops = host_drop_baseline
            self._unattributed_host_queue_drops = 0
            self._observed_stream_gaps = 0
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
            self._last_status = None
            return response.value

    def stop(self) -> constants.DeviceState:
        """Idempotently stop acquisition/configuration and enter IDLE."""

        with self._lock:
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
            self._expected_sequence.clear()
            self._expected_ticks.clear()
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
            block = self._reader.get_block(timeout=selected_timeout)
        except QueueWaitTimeoutError as error:
            raise BlockTimeoutError(error.timeout) from error
        except StreamStoppedError as error:
            raise UnexpectedMessageError(
                "the active stream stopped while waiting for a block"
            ) from error

        with self._lock:
            self._ensure_open()
            return self._process_block(block)

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
        else:
            status = self._last_status
            firmware = status.counters if status is not None else FirmwareCounters()
        return LossCounters(
            firmware=firmware,
            host=self.host_counters,
            observed_stream_gaps=self._observed_stream_gaps,
        )

    def close(self) -> None:
        """STOP when needed, then close the reader and transport idempotently."""

        with self._lock:
            if self._closed:
                return
            stop_error: BaseException | None = None
            if self._reader.is_running and self._state in {
                constants.DeviceState.CONFIGURED,
                constants.DeviceState.RUNNING,
            }:
                try:
                    self.stop()
                except BaseException as error:  # noqa: BLE001 - close regardless
                    stop_error = error
            try:
                self._reader.close()
            finally:
                self._closed = True
                self._pending_items.clear()
                self._expected_sequence.clear()
                self._expected_ticks.clear()
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
    ) -> CommandResponse[ResponseValue]:
        self._ensure_open()
        try:
            response = self._reader.request(
                kind,
                payload,
                timeout=self._command_timeout,
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

    def _initialize_stream_expectations(
        self,
        configuration: DAQConfiguration,
    ) -> None:
        self._expected_sequence.clear()
        self._expected_ticks.clear()
        if configuration.stream_mask & constants.StreamMask.ADC:
            self._expected_sequence[constants.FrameKind.ADC_DATA] = 0
            self._expected_ticks[constants.FrameKind.ADC_DATA] = 0
        if configuration.stream_mask & constants.StreamMask.GPIO:
            self._expected_sequence[constants.FrameKind.GPIO_DATA] = 0
            self._expected_ticks[constants.FrameKind.GPIO_DATA] = 0

    def _process_block(self, block: DataBlock) -> StreamItem:
        if block.run_id != self._run_id:
            raise UnexpectedMessageError(
                f"stale data run {block.run_id}; active run is {self._run_id}"
            )
        kind = (
            constants.FrameKind.ADC_DATA
            if isinstance(block, ADCBlock)
            else constants.FrameKind.GPIO_DATA
        )
        if kind not in self._expected_sequence:
            raise UnexpectedMessageError(
                f"received disabled {kind.name} stream for the active configuration"
            )

        total_host_drops = self._reader.counters.host_block_queue_drops
        if total_host_drops < self._last_host_queue_drops:
            raise ReaderProtocolError("host queue-drop counter moved backwards")
        self._unattributed_host_queue_drops += (
            total_host_drops - self._last_host_queue_drops
        )
        self._last_host_queue_drops = total_host_drops

        try:
            gap = StreamGap.from_expected(
                block,
                expected_sequence=self._expected_sequence[kind],
                expected_first_sample_ticks=self._expected_ticks[kind],
                host_queue_drops=self._unattributed_host_queue_drops,
            )
        except ValueError as error:
            raise UnexpectedMessageError(
                f"{kind.name} sequence/timestamp continuity is invalid: {error}"
            ) from error

        self._expected_sequence[kind] = (block.sequence + 1) & constants.UINT32_MAX
        self._expected_ticks[kind] = block.end_tick_exclusive
        if gap is None:
            return block

        self._unattributed_host_queue_drops -= gap.host_queue_drops
        self._observed_stream_gaps += 1
        if self._strict:
            raise UnexpectedStreamGapError(gap, block)
        self._pending_items.append(block)
        return gap

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
        if self._closed or not self._transport.is_open:
            raise DAQClosedError("TeensyDAQ is closed")
        if not self._reader.is_running:
            counters = self._reader.counters
            if counters.disconnects:
                raise DeviceDisconnectedError("device reader is disconnected")
            if counters.protocol_failures:
                raise ReaderProtocolError("device reader terminated on protocol error")
            raise DAQClosedError("TeensyDAQ reader is not running")


__all__ = [
    "BlockTimeoutError",
    "CommandTimeoutError",
    "DAQClosedError",
    "DAQStateError",
    "DataBlock",
    "DeviceCapabilityError",
    "DeviceCommandError",
    "DeviceIdentityMismatchError",
    "HostBufferFullError",
    "MultipleDevicesFoundError",
    "StreamItem",
    "TeensyDAQ",
    "TeensyDAQError",
    "UnexpectedMessageError",
    "UnexpectedStreamGapError",
]
