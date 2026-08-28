"""Synchronous transport-independent public facade for Teensy DAQ devices."""

from __future__ import annotations

from collections import deque
from collections.abc import Iterator
from types import TracebackType
from typing import Literal

from ._generated import protocol_constants as constants
from .models import (
    AdcBlock,
    CommandResponse,
    Configuration,
    GpioBlock,
    Info,
    ResponseValue,
    Status,
    decode_message,
)
from .protocol import Frame, IncrementalFrameParser, encode_frame
from .transport import ByteTransport, InMemoryTransport

DataBlock = AdcBlock | GpioBlock


class TeensyDAQError(RuntimeError):
    """Base error raised by the synchronous Teensy DAQ facade."""


class DAQClosedError(TeensyDAQError):
    """An operation was attempted after :meth:`TeensyDAQ.close`."""


class CommandTimeoutError(TeensyDAQError):
    """A bounded command exchange ended without its correlated response."""


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


class UnexpectedMessageError(TeensyDAQError):
    """The peer returned a valid frame that cannot satisfy the active operation."""


class HostBufferFullError(TeensyDAQError):
    """Data arrived while the facade's bounded deferred-block queue was full."""


class TeensyDAQ:
    """Synchronous command and streaming API over any :class:`ByteTransport`."""

    def __init__(
        self,
        transport: ByteTransport,
        *,
        read_size: int = constants.DATA_FRAME_BYTES,
        max_buffered_blocks: int = 8,
        operation_byte_budget: int = (
            2 * constants.DATA_FRAME_BYTES + constants.MAX_CONTROL_FRAME_BYTES
        ),
    ) -> None:
        if read_size <= 0:
            raise ValueError("read_size must be positive")
        if max_buffered_blocks <= 0:
            raise ValueError("max_buffered_blocks must be positive")
        if operation_byte_budget < constants.DATA_FRAME_BYTES:
            raise ValueError("operation_byte_budget must hold a complete data frame")

        self._transport = transport
        self._read_size = read_size
        self._max_buffered_blocks = max_buffered_blocks
        self._operation_byte_budget = operation_byte_budget
        self._parser = IncrementalFrameParser()
        self._buffered_blocks: deque[DataBlock] = deque()
        self._next_request_id = 1
        self._state: constants.DeviceState | None = None
        self._configuration: Configuration | None = None
        self._run_id = 0
        self._closed = False

    @classmethod
    def open(
        cls,
        transport: ByteTransport,
        **options: int,
    ) -> TeensyDAQ:
        """Open the public facade over an injected byte transport."""

        return cls(transport, **options)

    @classmethod
    def simulated(
        cls,
        *,
        read_chunk_size: int | None = None,
        write_chunk_size: int | None = None,
        read_size: int = constants.DATA_FRAME_BYTES,
        max_buffered_blocks: int = 8,
    ) -> TeensyDAQ:
        """Create the same facade wired to the deterministic local simulator."""

        transport = InMemoryTransport(
            read_chunk_size=read_chunk_size,
            write_chunk_size=write_chunk_size,
        )
        return cls(
            transport,
            read_size=read_size,
            max_buffered_blocks=max_buffered_blocks,
        )

    @property
    def transport(self) -> ByteTransport:
        """Injected byte transport used by this facade."""

        return self._transport

    @property
    def is_open(self) -> bool:
        return not self._closed and self._transport.is_open

    @property
    def state(self) -> constants.DeviceState | None:
        """Most recently observed device state, if a command has established it."""

        return self._state

    @property
    def configuration(self) -> Configuration | None:
        """Most recently applied active configuration."""

        return self._configuration

    @property
    def run_id(self) -> int:
        """Current or most recently observed run ID."""

        return self._run_id

    def info(self) -> Info:
        """Return identity/capabilities; valid in every post-boot state."""

        response = self._command(constants.FrameKind.INFO_REQUEST)
        if not isinstance(response.value, Info):
            raise UnexpectedMessageError("INFO response has no Info value")
        self._state = response.value.device_state
        self._run_id = response.run_id
        if self._state is constants.DeviceState.IDLE:
            self._configuration = None
        return response.value

    def configure(
        self,
        configuration: Configuration | None = None,
        *,
        adc: bool = True,
        gpio: bool = True,
        source: constants.Source | int = constants.Source.SYNTHETIC,
        checksum_algorithm: constants.ChecksumAlgorithm
        | int = constants.DEFAULT_CHECKSUM_ALGORITHM,
    ) -> Configuration:
        """Apply a configuration object or build one from convenient keywords."""

        if configuration is None:
            stream_mask = constants.StreamMask.NONE
            if adc:
                stream_mask |= constants.StreamMask.ADC
            if gpio:
                stream_mask |= constants.StreamMask.GPIO
            configuration = Configuration(
                stream_mask=stream_mask,
                source=constants.Source(source),
                data_checksum_algorithm=constants.ChecksumAlgorithm(checksum_algorithm),
            )

        response = self._command(
            constants.FrameKind.CONFIGURE_REQUEST,
            configuration.to_payload(),
        )
        if not isinstance(response.value, Configuration):
            raise UnexpectedMessageError(
                "CONFIGURE response has no Configuration value"
            )
        self._state = constants.DeviceState.CONFIGURED
        self._configuration = response.value
        self._run_id = response.run_id
        return response.value

    def start(self) -> int:
        """Start a new acquisition epoch and return its nonzero run ID."""

        response = self._command(constants.FrameKind.START_REQUEST)
        if not isinstance(response.value, Configuration):
            raise UnexpectedMessageError("START response has no Configuration value")
        self._state = constants.DeviceState.RUNNING
        self._configuration = response.value
        self._run_id = response.run_id
        self._buffered_blocks = deque(
            block for block in self._buffered_blocks if block.run_id == self._run_id
        )
        return self._run_id

    def status(self) -> Status:
        """Return state, active configuration, and current run counters."""

        response = self._command(constants.FrameKind.GET_STATUS_REQUEST)
        if not isinstance(response.value, Status):
            raise UnexpectedMessageError("STATUS response has no Status value")
        status = response.value
        self._state = status.device_state
        self._run_id = response.run_id
        if status.device_state is constants.DeviceState.IDLE:
            self._configuration = None
        else:
            self._configuration = Configuration(
                stream_mask=status.stream_mask,
                source=status.source,
                data_checksum_algorithm=status.data_checksum_algorithm,
                data_frame_bytes=status.data_frame_bytes,
            )
        return status

    def stop(self) -> constants.DeviceState:
        """Idempotently stop acquisition, discard configuration, and enter IDLE."""

        response = self._command(constants.FrameKind.STOP_REQUEST)
        if not isinstance(response.value, constants.DeviceState):
            raise UnexpectedMessageError("STOP response has no DeviceState value")
        self._state = response.value
        self._configuration = None
        self._run_id = response.run_id
        return response.value

    def read_block(self) -> DataBlock:
        """Read one ADC or GPIO block while preserving arbitrary chunk boundaries."""

        self._ensure_open()
        if self._buffered_blocks:
            return self._buffered_blocks.popleft()
        if self._state is not constants.DeviceState.RUNNING:
            raise TeensyDAQError("data blocks can only be read while RUNNING")

        bytes_read = 0
        while bytes_read <= self._operation_byte_budget:
            chunk = self._transport.read(self._read_size)
            if not chunk:
                raise CommandTimeoutError("no data frame became available")
            bytes_read += len(chunk)
            for frame in self._parser.feed(chunk):
                message = decode_message(frame)
                if isinstance(message, (AdcBlock, GpioBlock)):
                    self._queue_block(message)
                else:
                    raise UnexpectedMessageError(
                        "received control traffic without an active command"
                    )
            if self._buffered_blocks:
                return self._buffered_blocks.popleft()
        raise CommandTimeoutError("data-frame byte budget was exhausted")

    def blocks(self, count: int | None = None) -> Iterator[DataBlock]:
        """Yield a bounded number of blocks, or continue until the device stops."""

        if count is not None and count < 0:
            raise ValueError("block count must be nonnegative")
        emitted = 0
        while count is None or emitted < count:
            if self._state is not constants.DeviceState.RUNNING:
                return
            yield self.read_block()
            emitted += 1

    def close(self) -> None:
        """STOP an active device and unconditionally close its transport."""

        if self._closed:
            return
        try:
            if (
                self._transport.is_open
                and self._state is not constants.DeviceState.IDLE
            ):
                self.stop()
        finally:
            try:
                self._transport.close()
            finally:
                self._closed = True

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
            except Exception:  # noqa: BLE001
                # Cleanup errors must not hide the exception from the with-block.
                return False
        return False

    def _command(
        self,
        kind: constants.FrameKind,
        payload: bytes = b"",
    ) -> CommandResponse[ResponseValue]:
        self._ensure_open()
        request_id = self._allocate_request_id()
        wire = encode_frame(kind, payload, request_id=request_id)
        self._write_all(wire)

        expected_kind = constants.REQUEST_RESPONSE_KIND[kind]
        bytes_read = 0
        while bytes_read <= self._operation_byte_budget:
            chunk = self._transport.read(self._read_size)
            if not chunk:
                raise CommandTimeoutError(
                    f"{kind.name} request {request_id} received no response"
                )
            bytes_read += len(chunk)
            matched: CommandResponse[ResponseValue] | None = None
            for frame in self._parser.feed(chunk):
                message = decode_message(frame)
                if isinstance(message, (AdcBlock, GpioBlock)):
                    self._queue_block(message)
                    continue
                if isinstance(message, CommandResponse):
                    if message.request_id != request_id:
                        raise UnexpectedMessageError(
                            "response request ID does not match the active command"
                        )
                    if matched is not None:
                        raise UnexpectedMessageError(
                            "device returned duplicate responses for one command"
                        )
                    matched = message
                    continue
                if isinstance(message, Frame):
                    raise UnexpectedMessageError("device sent a request to the host")

            if matched is None:
                continue
            if not matched.ok:
                raise DeviceCommandError(kind, matched.error_code, request_id)
            if matched.kind is not expected_kind:
                raise UnexpectedMessageError(
                    f"expected {expected_kind.name}, received {matched.kind.name}"
                )
            return matched
        raise CommandTimeoutError(f"{kind.name} response byte budget was exhausted")

    def _allocate_request_id(self) -> int:
        request_id = self._next_request_id
        self._next_request_id = (request_id + 1) & constants.UINT32_MAX
        if self._next_request_id == 0:
            self._next_request_id = 1
        return request_id

    def _write_all(self, wire: bytes) -> None:
        offset = 0
        attempts_remaining = len(wire)
        while offset < len(wire) and attempts_remaining:
            written = self._transport.write(wire[offset:])
            if written <= 0 or written > len(wire) - offset:
                raise TeensyDAQError("transport made invalid write progress")
            offset += written
            attempts_remaining -= 1
        if offset != len(wire):
            raise CommandTimeoutError("request write did not make bounded progress")

    def _queue_block(self, block: DataBlock) -> None:
        if (
            self._state is constants.DeviceState.RUNNING
            and self._run_id != 0
            and block.run_id != self._run_id
        ):
            raise UnexpectedMessageError(
                f"stale data run {block.run_id}; active run is {self._run_id}"
            )
        if len(self._buffered_blocks) >= self._max_buffered_blocks:
            raise HostBufferFullError("deferred data-block queue is full")
        self._buffered_blocks.append(block)

    def _ensure_open(self) -> None:
        if self._closed or not self._transport.is_open:
            raise DAQClosedError("TeensyDAQ is closed")


__all__ = [
    "CommandTimeoutError",
    "DAQClosedError",
    "DataBlock",
    "DeviceCommandError",
    "HostBufferFullError",
    "TeensyDAQ",
    "TeensyDAQError",
    "UnexpectedMessageError",
]
