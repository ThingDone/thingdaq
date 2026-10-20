"""Opt-in simulated Teensy 4.0 public-v3 peer; clocks are metadata only."""

from __future__ import annotations

import struct
from collections import deque
from dataclasses import dataclass, replace

from ._generated import protocol_v3_constants as c
from ._incremental import BoundedIncrementalParser, BytesLike
from .models_v3 import (
    V3AppliedSettings,
    V3Capabilities,
    V3Clocks,
    V3Info,
    V3Response,
    V3ResponseValue,
    V3Settings,
    V3Status,
    V3Stop,
)
from .protocol_v3 import (
    V3ChecksumMismatchError,
    V3FrameValidationError,
    compute_v3_checksum,
    encode_adc_payload,
    encode_gpio_payload,
    encode_v3_frame,
)
from .simulator import SimulatorInputError
from .synthetic import (
    SyntheticGPIOPattern,
    synthetic_gpio_payload,
    synthetic_v3_adc_payload,
)

_HEADER = struct.Struct(c.HEADER_STRUCT_FORMAT)
_U64_MAX = (1 << 64) - 1
_REQUEST_KINDS = {int(kind) for kind in c.CommandKind}


@dataclass(frozen=True)
class _Envelope:
    total_length: int


def _request_header(data: bytearray, offset: int) -> _Envelope:
    fields = _HEADER.unpack_from(data, offset)
    magic, version, _, _, size, checksum, _, total, payload = fields[:9]
    # Admit only trusted framing here. Semantic errors need correlated replies,
    # so the stricter host-side V3FrameParser cannot serve as device ingress.
    if (
        magic != c.MAGIC
        or version != c.PROTOCOL_VERSION
        or size != c.HEADER_SIZE
        or checksum != c.ChecksumAlgorithm.ADLER32
        or total != c.MIN_FRAME_BYTES + payload
        or not c.MIN_FRAME_BYTES <= total <= c.MAX_COMMAND_FRAME_BYTES
    ):
        raise V3FrameValidationError("untrusted command framing")
    return _Envelope(total)


def _request_bytes(data: bytearray, offset: int, header: _Envelope) -> bytes:
    wire = bytes(data[offset : offset + header.total_length])
    expected = compute_v3_checksum(wire[:-4])
    observed = struct.unpack_from("<I", wire, len(wire) - 4)[0]
    if expected != observed:
        raise V3ChecksumMismatchError(expected, observed)
    return wire


class SimulatedV3Device:
    """Explicit v3 persona for the existing :class:`InMemoryTransport`.

    Board defaults include HARDWARE source, meaning emulated board input here;
    INFO always identifies this device as simulated. Like the normal firmware,
    it advertises only fixed 600 MHz configurations. No physical timing claims
    are made. Direct ``next_data_frame`` calls transfer whole
    frames; the transport reports any partial data tail through
    ``set_transport_pending_data`` so STOP cannot prematurely report STOPPED.
    """

    def __init__(
        self,
        *,
        build_id: str = "thingdaq-simulator-v3",
        max_receive_bytes: int = c.MAX_CONTROL_FRAME_BYTES,
        max_requests_per_receive: int = 8,
    ) -> None:
        if max_receive_bytes < c.MIN_FRAME_BYTES:
            raise ValueError("max_receive_bytes must hold at least one frame")
        if max_requests_per_receive <= 0:
            raise ValueError("max_requests_per_receive must be positive")
        self._build_id = build_id
        self._max_receive_bytes = max_receive_bytes
        self._max_requests_per_receive = max_requests_per_receive
        canonical = V3Capabilities.canonical()
        cpu = canonical.defaults.cpu_profile
        self._capabilities = replace(
            canonical,
            cpu_profiles=tuple(
                p for p in canonical.cpu_profiles if p.cpu_profile == cpu
            ),
            configurations=tuple(
                s for s in canonical.configurations if s.cpu_profile == cpu
            ),
        )
        self._request_parser = BoundedIncrementalParser(
            magic_bytes=c.MAGIC.to_bytes(4, "little"),
            header_size=c.HEADER_SIZE,
            max_frame_bytes=c.MAX_COMMAND_FRAME_BYTES,
            decode_header=_request_header,
            decode_frame=_request_bytes,
            validation_error=V3FrameValidationError,
            checksum_error=V3ChecksumMismatchError,
        )
        self._recent_request_ids: deque[int] = deque(maxlen=16)
        self.reboot()
        self.info().to_payload()  # Validate identity at construction.

    @property
    def state(self) -> c.DeviceState:
        return self._state

    @property
    def settings(self) -> V3Settings:
        return self._settings

    @property
    def run_id(self) -> int:
        return self._run_id

    @property
    def max_receive_bytes(self) -> int:
        return self._max_receive_bytes

    def reboot(self) -> None:
        """Reset board settings, counters and replay state (use while detached)."""
        self._settings = self._capabilities.defaults
        self._state = c.DeviceState.STOPPED
        self._run_id = 0
        self._pending_data = False
        self._transport_errors = 0
        self._reset_epoch()
        self._request_parser.reset()
        self._recent_request_ids.clear()

    def begin_host_session(self) -> None:
        """Reconnect clears parser/replay state, preserving settings and run."""
        self._request_parser.reset_session()
        self._recent_request_ids.clear()

    def record_transport_error(self) -> None:
        self._transport_errors = min(self._transport_errors + 1, _U64_MAX)

    def set_transport_pending_data(self, pending: bool) -> None:
        """Report the existing transport's single complete-or-partial data frame."""
        self._pending_data = pending
        if not pending and self._state == c.DeviceState.DRAINING:
            self._state = c.DeviceState.STOPPED

    def discard_transport_data(self) -> None:
        """Account for an incomplete frame discarded when a transport closes."""
        if self._pending_data:
            stream = self._last_stream_index
            self._frames_dropped[stream] = min(
                self._frames_dropped[stream] + 1, _U64_MAX
            )
            self._items_dropped[stream] = min(
                self._items_dropped[stream] + self._last_item_count, _U64_MAX
            )
            self._gap_before[stream] = True
            self._epoch_start[stream] = self._last_epoch_start
        self.set_transport_pending_data(False)

    def info(self) -> V3Info:
        return V3Info(
            c.BoardId.TEENSY_40,
            c.McuId.IMXRT1062,
            True,
            "SIM-TEENSY40-V3",
            "0.3.0-sim",
            self._build_id,
            V3Clocks.for_profile(self._settings.cpu_profile),
        )

    def status(self) -> V3Status:
        return V3Status(
            self._state,
            self._run_id,
            int(self._pending_data),
            self._frames[0],
            self._frames_dropped[0],
            self._items[0],
            self._items_dropped[0],
            self._frames[1],
            self._frames_dropped[1],
            self._items[1],
            self._items_dropped[1],
        )

    def receive(self, data: BytesLike) -> tuple[bytes, ...]:
        if memoryview(data).nbytes > self._max_receive_bytes:
            raise SimulatorInputError(
                f"receive accepts at most {self._max_receive_bytes} bytes"
            )
        return tuple(
            self._handle_request(wire, busy=index >= self._max_requests_per_receive)
            for index, wire in enumerate(self._request_parser.feed(data))
        )

    def _reply(
        self,
        kind: int,
        request_id: int,
        value: V3ResponseValue | None = None,
        error: c.ErrorCode = c.ErrorCode.OK,
    ) -> bytes:
        known = kind in _REQUEST_KINDS
        return V3Response(
            c.COMMAND_RESPONSE_KINDS[c.CommandKind(kind)]
            if known
            else c.FrameKind.ERROR_RESPONSE,
            request_id,
            self._run_id,
            c.ResponseStatus.OK if error == c.ErrorCode.OK else c.ResponseStatus.ERROR,
            error,
            value,
            None if known else kind,
        ).to_bytes()

    def _handle_request(self, wire: bytes, *, busy: bool) -> bytes:
        (
            _,
            _,
            kind,
            flags,
            _,
            _,
            reserved,
            _,
            payload_size,
            run,
            sequence,
            request_id,
            ticks,
            count,
        ) = _HEADER.unpack_from(wire)
        if kind not in _REQUEST_KINDS:
            # Unknown kinds precede replay validation; zero IDs are the sole
            # correlation exception and must report INVALID_REQUEST_ID.
            if request_id and request_id not in self._recent_request_ids:
                self._recent_request_ids.append(request_id)
            error = (
                c.ErrorCode.UNKNOWN_FRAME_KIND
                if request_id
                else c.ErrorCode.INVALID_REQUEST_ID
            )
            return self._reply(kind, request_id, error=error)
        if request_id == 0 or request_id in self._recent_request_ids:
            return self._reply(kind, request_id, error=c.ErrorCode.INVALID_REQUEST_ID)
        self._recent_request_ids.append(request_id)
        if flags:
            return self._reply(kind, request_id, error=c.ErrorCode.INVALID_FLAGS)
        expected = c.SETTINGS_PAYLOAD_SIZE if kind == c.CommandKind.CONFIGURE else 0
        if payload_size != expected:
            return self._reply(kind, request_id, error=c.ErrorCode.INVALID_LENGTH)
        if reserved or run or sequence or ticks or count:
            return self._reply(kind, request_id, error=c.ErrorCode.INVALID_PAYLOAD)
        candidate = None
        unsupported = False
        if kind == c.CommandKind.CONFIGURE:
            try:
                candidate = V3Settings.from_bytes(wire[c.HEADER_SIZE : -4])
                self._capabilities.require_supported(candidate)
            except V3FrameValidationError as exc:
                if exc.error_code != c.ErrorCode.UNSUPPORTED_CONFIGURATION:
                    return self._reply(kind, request_id, error=exc.error_code)
                unsupported = True
        if busy:
            return self._reply(kind, request_id, error=c.ErrorCode.BUSY)
        if kind in (c.CommandKind.CONFIGURE, c.CommandKind.START):
            if self._state == c.DeviceState.RUNNING:
                return self._reply(kind, request_id, error=c.ErrorCode.INVALID_STATE)
            if self._state == c.DeviceState.DRAINING or self._pending_data:
                return self._reply(kind, request_id, error=c.ErrorCode.BUSY)
        if unsupported:
            return self._reply(
                kind, request_id, error=c.ErrorCode.UNSUPPORTED_CONFIGURATION
            )
        value: V3ResponseValue
        if kind == c.CommandKind.INFO:
            value = self.info()
        elif kind == c.CommandKind.GET_CAPABILITIES:
            value = self._capabilities
        elif kind == c.CommandKind.GET_STATUS:
            value = self.status()
        elif kind == c.CommandKind.STOP:
            self._state = (
                c.DeviceState.DRAINING if self._pending_data else c.DeviceState.STOPPED
            )
            value = V3Stop(self._state, self._run_id, int(self._pending_data))
        else:
            if kind == c.CommandKind.CONFIGURE:
                assert candidate is not None
                self._settings = candidate
            elif kind == c.CommandKind.START:
                self._run_id = (self._run_id + 1) & 0xFFFFFFFF or 1
                self._reset_epoch()
                self._state = c.DeviceState.RUNNING
            value = V3AppliedSettings(
                self._settings, V3Clocks.for_profile(self._settings.cpu_profile)
            )
        return self._reply(kind, request_id, value)

    def _reset_epoch(self) -> None:
        self._frames = [0, 0]
        self._items = [0, 0]
        self._frames_dropped = [0, 0]
        self._items_dropped = [0, 0]
        self._gap_before = [False, False]
        self._epoch_start = [True, True]
        self._last_epoch_start = False
        self._next_stream_index = 0
        self._last_stream_index = 0
        self._last_item_count = 0

    def next_data_frame(self) -> bytes | None:
        if self._state != c.DeviceState.RUNNING or self._pending_data:
            return None
        settings = self._settings
        streams = [
            index
            for index, mask in enumerate((c.StreamMask.ADC, c.StreamMask.GPIO))
            if settings.stream_mask & mask
        ]
        stream = streams[self._next_stream_index % len(streams)]
        first = self._items[stream]
        sequence = self._frames[stream]
        if stream == 0:
            count = c.MAX_ADC_PAIRS
            # Reuse the legacy ramp with v3 edge pairs and nibble patterns.
            pairs = tuple(
                struct.iter_unpack("<HH", synthetic_v3_adc_payload(first, count))
            )
            payload = encode_adc_payload(pairs, policy=settings.adc_policy)
            kind = c.FrameKind.ADC_DATA
        else:
            count = c.MAX_LOGICAL_PAYLOAD_BYTES // (settings.gpio_width_bits // 8)
            pattern = (
                SyntheticGPIOPattern.ALL_ZERO
                if sequence % 2 == 0
                else SyntheticGPIOPattern.HIGH_TRANSITION
            )
            raw = synthetic_gpio_payload(
                first, count, aux_bank_mode=settings.aux_bank_mode, pattern=pattern
            )
            samples = (
                tuple(raw)
                if settings.gpio_width_bits == 8
                else tuple(value for (value,) in struct.iter_unpack("<H", raw))
            )
            payload = encode_gpio_payload(
                samples,
                width_bits=settings.gpio_width_bits,
                policy=settings.gpio_policy,
            )
            kind = c.FrameKind.GPIO_DATA
        if (first + count) * c.ADC_PAIR_PERIOD_TICKS > _U64_MAX:
            self._state = c.DeviceState.STOPPED
            return None
        flags = c.FrameFlag.EPOCH_START if self._epoch_start[stream] else c.FrameFlag(0)
        if self._gap_before[stream]:
            flags |= c.FrameFlag.GAP_BEFORE
        if settings.source == c.Source.SYNTHETIC:
            flags |= c.FrameFlag.SYNTHETIC
        wire = encode_v3_frame(
            kind,
            payload,
            flags=flags,
            run_id=self._run_id,
            sequence=sequence & 0xFFFFFFFF,
            first_sample_ticks=first * c.ADC_PAIR_PERIOD_TICKS,
            item_count=count,
        )
        self._frames[stream] = min(sequence + 1, _U64_MAX)
        self._items[stream] = min(first + count, _U64_MAX)
        self._gap_before[stream] = False
        self._last_epoch_start = self._epoch_start[stream]
        self._epoch_start[stream] = False
        self._last_stream_index = stream
        self._last_item_count = count
        self._next_stream_index = (self._next_stream_index + 1) % len(streams)
        return wire
