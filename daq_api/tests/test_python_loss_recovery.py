"""Standalone Phase 09 Python loss and recovery adversarial tests."""

from __future__ import annotations

import struct
import threading
import time
import unittest
from collections.abc import Callable
from dataclasses import replace
from typing import Literal
from unittest.mock import patch

from teensy_daq import (
    ADCBlock,
    BackgroundReader,
    CommandResponse,
    DeviceDisconnectedError,
    DeviceInfo,
    DeviceState,
    DiscoveredDevice,
    Frame,
    FrameFlag,
    FrameKind,
    HostQueueLoss,
    IncrementalFrameParser,
    InMemoryTransport,
    SerialPortCandidate,
    SessionRecoveryPolicy,
    SimulatedDevice,
    Source,
    StreamAnomaly,
    StreamAnomalyReason,
    StreamGap,
    StreamMask,
    TeensyDAQ,
    TransportClosedError,
    TransportDisconnectedError,
    UnexpectedStreamAnomalyError,
    UnexpectedStreamGapError,
    decode_frame,
    decode_message,
    encode_frame,
    reconcile_run_counters,
    synthetic_adc_payload,
)
from teensy_daq._generated import protocol_constants as constants

_Fault = Literal["missing", "duplicate", "reordered", "cross_run"]


def _wait_until(predicate: Callable[[], bool], *, timeout: float = 1.0) -> None:
    deadline = time.monotonic() + timeout
    while not predicate():
        if time.monotonic() >= deadline:
            raise AssertionError("condition did not become true before its deadline")
        time.sleep(0.001)


def _rewrite_data_frame(
    wire: bytes,
    *,
    flags: FrameFlag | None = None,
    run_id: int | None = None,
    sequence: int | None = None,
    first_sample_ticks: int | None = None,
) -> bytes:
    frame = decode_frame(wire)
    header = frame.header
    return encode_frame(
        header.kind,
        frame.payload,
        flags=header.flags if flags is None else flags,
        checksum_algorithm=header.checksum_algorithm,
        run_id=header.run_id if run_id is None else run_id,
        sequence=header.sequence if sequence is None else sequence,
        request_id=header.request_id,
        first_sample_ticks=(
            header.first_sample_ticks
            if first_sample_ticks is None
            else first_sample_ticks
        ),
        item_count=header.item_count,
    )


def _adc_wire(run_id: int, sequence: int) -> bytes:
    flags = FrameFlag.SYNTHETIC
    if sequence == 0:
        flags |= FrameFlag.EPOCH_START
    return encode_frame(
        FrameKind.ADC_DATA,
        synthetic_adc_payload(sequence * constants.ADC_PAIRS_PER_FRAME),
        flags=flags,
        run_id=run_id,
        sequence=sequence,
        first_sample_ticks=sequence * constants.FRAME_COVERAGE_TICKS,
        item_count=constants.ADC_PAIRS_PER_FRAME,
    )


class _ContinuityFaultDevice(SimulatedDevice):
    """Inject exactly one decoded-stream fault after the first ADC frame."""

    def __init__(self, fault: _Fault, *, counters_agree: bool = True) -> None:
        super().__init__()
        self.fault = fault
        self.counters_agree = counters_agree
        self._fault_emitted = False
        self._first_adc_wire: bytes | None = None

    def next_data_frame(self) -> bytes | None:
        if (
            self.fault == "duplicate"
            and self._first_adc_wire is not None
            and not self._fault_emitted
        ):
            self._fault_emitted = True
            return self._first_adc_wire

        wire = super().next_data_frame()
        if wire is None:
            return None
        frame = decode_frame(wire)
        if frame.header.kind is not FrameKind.ADC_DATA:
            return wire
        if self._first_adc_wire is None:
            self._first_adc_wire = wire
            return wire
        if self._fault_emitted:
            return wire

        self._fault_emitted = True
        if self.fault == "missing":
            if self.counters_agree:
                self._adc_items_dropped += constants.ADC_PAIRS_PER_FRAME
            replacement = super().next_data_frame()
            if replacement is None:
                raise AssertionError("running simulator did not produce a replacement")
            replacement_frame = decode_frame(replacement)
            return _rewrite_data_frame(
                replacement,
                flags=(
                    replacement_frame.header.flags
                    | FrameFlag.GAP_BEFORE
                    | FrameFlag.OVERRUN_BEFORE
                ),
            )
        if self.fault == "reordered":
            return _rewrite_data_frame(wire, sequence=constants.UINT32_MAX)
        if self.fault == "cross_run":
            stale_run_id = (frame.header.run_id - 1) & constants.UINT32_MAX
            if stale_run_id == 0:
                stale_run_id = constants.UINT32_MAX
            return _rewrite_data_frame(wire, run_id=stale_run_id)
        raise AssertionError(f"unsupported injected fault {self.fault!r}")


class _StartBurstTransport(InMemoryTransport):
    """Queue a deterministic frame burst immediately behind START_RESPONSE."""

    def __init__(self, device: SimulatedDevice, *, burst_frames: int) -> None:
        super().__init__(device)
        self._burst_frames = burst_frames
        self._burst_injected = False

    def write(self, data: bytes | bytearray | memoryview) -> int:
        request = decode_frame(bytes(data))
        written = super().write(data)
        if request.header.kind is FrameKind.START_REQUEST and not self._burst_injected:
            self._burst_injected = True
            with self._lock:
                for _ in range(self._burst_frames):
                    wire = self.device.next_data_frame()
                    if wire is None:
                        raise AssertionError("START burst device was not running")
                    self._pending.extend(wire)
        return written


class ContinuityModeMatrixTests(unittest.TestCase):
    def test_continuing_mode_reports_every_fault_and_counter_disagreement(self) -> None:
        cases: tuple[tuple[str, _Fault, bool], ...] = (
            ("missing-agreement", "missing", True),
            ("missing-disagreement", "missing", False),
            ("duplicate", "duplicate", True),
            ("reordered", "reordered", True),
            ("cross-run", "cross_run", True),
        )

        for label, fault, counters_agree in cases:
            with self.subTest(case=label):
                device = _ContinuityFaultDevice(
                    fault,
                    counters_agree=counters_agree,
                )
                with TeensyDAQ.open(InMemoryTransport(device)) as daq:
                    daq.configure(adc=True, gpio=False)
                    run_id = daq.start()
                    first = daq.read_block()
                    report = daq.read_block()

                    self.assertIsInstance(first, ADCBlock)
                    assert isinstance(first, ADCBlock)
                    self.assertEqual((run_id, 0), (first.run_id, first.sequence))

                    if fault == "missing":
                        self.assertIsInstance(report, StreamGap)
                        assert isinstance(report, StreamGap)
                        self.assertEqual(1, report.missing_frames)
                        self.assertEqual(
                            constants.ADC_PAIRS_PER_FRAME,
                            report.missing_items,
                        )
                        evidence = report.firmware_evidence
                        self.assertIsNotNone(evidence)
                        assert evidence is not None
                        self.assertIs(counters_agree, evidence.counters_match)
                        self.assertEqual(not counters_agree, bool(evidence.errors))
                        successor = daq.read_block()
                        self.assertIsInstance(successor, ADCBlock)
                        assert isinstance(successor, ADCBlock)
                        self.assertEqual(2, successor.sequence)
                    else:
                        self.assertIsInstance(report, StreamAnomaly)
                        assert isinstance(report, StreamAnomaly)
                        expected_reason = {
                            "duplicate": StreamAnomalyReason.DUPLICATE,
                            "reordered": StreamAnomalyReason.REORDERED,
                            "cross_run": StreamAnomalyReason.STALE_RUN,
                        }[fault]
                        self.assertEqual(expected_reason, report.reason)
                        if fault == "duplicate":
                            following = daq.read_block()
                            self.assertIsInstance(following, ADCBlock)
                            assert isinstance(following, ADCBlock)
                            self.assertEqual(1, following.sequence)

    def test_strict_mode_raises_every_fault_with_original_evidence(self) -> None:
        cases: tuple[tuple[str, _Fault, bool], ...] = (
            ("missing-agreement", "missing", True),
            ("missing-disagreement", "missing", False),
            ("duplicate", "duplicate", True),
            ("reordered", "reordered", True),
            ("cross-run", "cross_run", True),
        )

        for label, fault, counters_agree in cases:
            with self.subTest(case=label):
                device = _ContinuityFaultDevice(
                    fault,
                    counters_agree=counters_agree,
                )
                with TeensyDAQ.open(InMemoryTransport(device), strict=True) as daq:
                    daq.configure(adc=True, gpio=False)
                    daq.start()
                    self.assertIsInstance(daq.read_block(), ADCBlock)
                    if fault == "missing":
                        with self.assertRaises(UnexpectedStreamGapError) as gap_raised:
                            daq.read_block()
                        evidence = gap_raised.exception.gap.firmware_evidence
                        self.assertIsNotNone(evidence)
                        assert evidence is not None
                        self.assertIs(counters_agree, evidence.counters_match)
                        self.assertEqual(not counters_agree, bool(evidence.errors))
                    else:
                        with self.assertRaises(
                            UnexpectedStreamAnomalyError
                        ) as anomaly_raised:
                            daq.read_block()
                        expected_reason = {
                            "duplicate": StreamAnomalyReason.DUPLICATE,
                            "reordered": StreamAnomalyReason.REORDERED,
                            "cross_run": StreamAnomalyReason.STALE_RUN,
                        }[fault]
                        self.assertEqual(
                            expected_reason,
                            anomaly_raised.exception.anomaly.reason,
                        )


class IndependentLossDomainTests(unittest.TestCase):
    def test_host_queue_loss_with_zero_firmware_loss(self) -> None:
        transport = _StartBurstTransport(SimulatedDevice(), burst_frames=3)
        with TeensyDAQ.open(transport, max_buffered_blocks=2) as daq:
            daq.configure(adc=True, gpio=False)
            daq.start()
            _wait_until(lambda: daq.reader_counters.adc_block_queue_drops == 1)
            host_loss = daq.read_block()
            retained = daq.read_block()
            counters = daq.loss_counters()

        self.assertIsInstance(host_loss, HostQueueLoss)
        assert isinstance(host_loss, HostQueueLoss)
        self.assertEqual((0, 0), (host_loss.first_sequence, host_loss.last_sequence))
        self.assertEqual(1, host_loss.dropped_blocks)
        self.assertEqual(constants.ADC_PAIRS_PER_FRAME, host_loss.dropped_items)
        self.assertIsInstance(retained, ADCBlock)
        assert isinstance(retained, ADCBlock)
        self.assertEqual(1, retained.sequence)
        self.assertFalse(counters.firmware.has_loss)
        self.assertEqual(1, counters.host.adc_block_queue_drops)
        self.assertEqual(0, counters.observed_stream_gaps)
        self.assertEqual(1, counters.observed_host_queue_losses)

    def test_firmware_loss_with_zero_host_queue_loss(self) -> None:
        device = _ContinuityFaultDevice("missing", counters_agree=True)
        with TeensyDAQ.open(InMemoryTransport(device), max_buffered_blocks=4) as daq:
            daq.configure(adc=True, gpio=False)
            daq.start()
            self.assertIsInstance(daq.read_block(), ADCBlock)
            gap = daq.read_block()
            successor = daq.read_block()
            counters = daq.loss_counters()

        self.assertIsInstance(gap, StreamGap)
        assert isinstance(gap, StreamGap)
        self.assertEqual(1, gap.missing_frames)
        self.assertIsInstance(successor, ADCBlock)
        self.assertEqual(1, counters.firmware.adc_frames_dropped)
        self.assertEqual(
            constants.ADC_PAIRS_PER_FRAME,
            counters.firmware.adc_items_dropped,
        )
        self.assertEqual(0, counters.host.host_block_queue_drops)
        self.assertEqual(1, counters.observed_stream_gaps)
        self.assertEqual(0, counters.observed_host_queue_losses)

    def test_firmware_and_host_queue_loss_remain_independently_exact(self) -> None:
        device = _ContinuityFaultDevice("missing", counters_agree=True)
        transport = _StartBurstTransport(device, burst_frames=3)
        with TeensyDAQ.open(transport, max_buffered_blocks=2) as daq:
            daq.configure(adc=True, gpio=False)
            daq.start()
            _wait_until(lambda: daq.reader_counters.adc_block_queue_drops == 1)
            host_loss = daq.read_block()
            firmware_gap = daq.read_block()
            successor = daq.read_block()
            counters = daq.loss_counters()

        self.assertIsInstance(host_loss, HostQueueLoss)
        assert isinstance(host_loss, HostQueueLoss)
        self.assertEqual((0, 0), (host_loss.first_sequence, host_loss.last_sequence))
        self.assertEqual(1, host_loss.dropped_blocks)
        self.assertIsInstance(firmware_gap, StreamGap)
        assert isinstance(firmware_gap, StreamGap)
        self.assertEqual(
            (1, 2),
            (
                firmware_gap.expected_sequence,
                firmware_gap.observed_sequence,
            ),
        )
        evidence = firmware_gap.firmware_evidence
        self.assertIsNotNone(evidence)
        assert evidence is not None
        self.assertTrue(evidence.consistent)
        self.assertIsInstance(successor, ADCBlock)
        assert isinstance(successor, ADCBlock)
        self.assertEqual(2, successor.sequence)
        self.assertEqual(1, counters.firmware.adc_frames_dropped)
        self.assertEqual(1, counters.host.adc_block_queue_drops)
        self.assertEqual(1, counters.observed_stream_gaps)
        self.assertEqual(1, counters.observed_host_queue_losses)


class _DisconnectAfterDrainTransport:
    """Deliver a prefix, then fail the next read as a physical disconnect."""

    def __init__(self, *, read_chunk_size: int = 113) -> None:
        self._condition = threading.Condition()
        self._pending = bytearray()
        self._read_chunk_size = read_chunk_size
        self._is_open = True
        self._disconnect_after_drain = False

    @property
    def is_open(self) -> bool:
        with self._condition:
            return self._is_open

    def write(self, data: bytes | bytearray | memoryview) -> int:
        with self._condition:
            self._require_open()
            return len(data)

    def read(self, size: int) -> bytes:
        with self._condition:
            self._require_open()
            if not self._pending and not self._disconnect_after_drain:
                self._condition.wait(0.01)
                self._require_open()
            if self._pending:
                returned = min(size, self._read_chunk_size, len(self._pending))
                result = bytes(self._pending[:returned])
                del self._pending[:returned]
                return result
            if self._disconnect_after_drain:
                self._is_open = False
                raise TransportDisconnectedError("injected mid-frame disconnect")
            return b""

    def flush(self) -> None:
        with self._condition:
            self._require_open()

    def close(self) -> None:
        with self._condition:
            self._is_open = False
            self._pending.clear()
            self._condition.notify_all()

    def inject_prefix_then_disconnect(self, prefix: bytes) -> None:
        with self._condition:
            self._require_open()
            self._pending.extend(prefix)
            self._disconnect_after_drain = True
            self._condition.notify_all()

    def _require_open(self) -> None:
        if not self._is_open:
            raise TransportClosedError("disconnect transport is closed")


class ParserAndDisconnectRecoveryTests(unittest.TestCase):
    def test_truncated_frame_garbage_and_valid_frames_resynchronize(self) -> None:
        truncated = _adc_wire(9, 0)[:-113]
        garbage = b"\x13\x37" * 96
        valid = (
            encode_frame(FrameKind.INFO_REQUEST, request_id=101),
            encode_frame(FrameKind.PING_REQUEST, bytes(8), request_id=102),
        )
        stream = truncated + garbage + b"".join(valid)
        parser = IncrementalFrameParser()
        decoded: list[Frame] = []

        for offset in range(0, len(stream), 97):
            decoded.extend(parser.feed(stream[offset : offset + 97]))
            self.assertLessEqual(parser.buffered_bytes, parser.max_buffered_bytes)
            self.assertLessEqual(parser.high_water_mark, parser.max_buffered_bytes)

        self.assertEqual(list(valid), [frame.to_bytes() for frame in decoded])
        self.assertEqual(0, parser.buffered_bytes)
        self.assertGreaterEqual(parser.corruption_events, 1)
        self.assertGreaterEqual(parser.resynchronizations, 1)

    def test_adversarial_declared_lengths_never_expand_parser_storage(self) -> None:
        template = encode_frame(FrameKind.INFO_REQUEST, request_id=201)
        sentinel = encode_frame(FrameKind.INFO_REQUEST, request_id=202)
        declared_lengths = (
            (constants.UINT32_MAX, constants.UINT32_MAX - constants.MIN_FRAME_BYTES),
            (constants.DATA_FRAME_BYTES + 1, constants.DATA_FRAME_BYTES - 47),
            (constants.MAX_CONTROL_FRAME_BYTES + 1, 1_233),
            (constants.MIN_FRAME_BYTES - 1, 0),
            (64, 16),
        )
        stream = bytearray()
        iterations = 512
        for index in range(iterations):
            total_length, payload_length = declared_lengths[
                index % len(declared_lengths)
            ]
            malformed = bytearray(template)
            struct.pack_into(
                "<I",
                malformed,
                constants.HEADER_TOTAL_LENGTH_OFFSET,
                total_length,
            )
            struct.pack_into(
                "<I",
                malformed,
                constants.HEADER_PAYLOAD_LENGTH_OFFSET,
                payload_length,
            )
            stream.extend(malformed)
            stream.extend(sentinel)

        parser = IncrementalFrameParser()
        decoded: list[Frame] = []
        for offset in range(0, len(stream), 131):
            decoded.extend(parser.feed(stream[offset : offset + 131]))
            self.assertLessEqual(parser.buffered_bytes, parser.max_buffered_bytes)
            self.assertLessEqual(parser.high_water_mark, parser.max_buffered_bytes)

        self.assertEqual(iterations, len(decoded))
        self.assertTrue(all(frame.to_bytes() == sentinel for frame in decoded))
        self.assertGreaterEqual(parser.header_errors, iterations)
        self.assertEqual(0, parser.buffered_bytes)

    def test_disconnect_mid_frame_preserves_bounded_parser_evidence(self) -> None:
        wire = _adc_wire(41, 0)
        prefix = wire[: len(wire) // 2 + 17]
        transport = _DisconnectAfterDrainTransport(read_chunk_size=113)
        reader = BackgroundReader(
            transport,
            read_size=257,
            queue_timeout=0.5,
            shutdown_timeout=0.5,
        )
        reader.start()
        try:
            reader.activate_run(41)
            transport.inject_prefix_then_disconnect(prefix)
            with self.assertRaises(DeviceDisconnectedError) as raised:
                reader.get_block(timeout=0.5)

            parser_evidence = raised.exception.parser_counters
            reader_evidence = raised.exception.reader_counters
            self.assertIsNotNone(parser_evidence)
            self.assertIsNotNone(reader_evidence)
            assert parser_evidence is not None
            assert reader_evidence is not None
            self.assertEqual(len(prefix), parser_evidence.buffered_bytes)
            self.assertEqual(len(prefix), parser_evidence.bytes_received)
            self.assertLessEqual(
                parser_evidence.high_water_mark,
                IncrementalFrameParser.max_buffered_bytes,
            )
            self.assertEqual(0, parser_evidence.frames_decoded)
            self.assertEqual(1, reader_evidence.disconnects)
            self.assertEqual(len(prefix), reader_evidence.bytes_read)
        finally:
            reader.close()

        self.assertFalse(reader.is_running)
        self.assertFalse(transport.is_open)


class _StableSerialDevice(SimulatedDevice):
    """Simulator with a stable nonzero USB/INFO serial and probe counters."""

    def __init__(self, hardware_serial: int) -> None:
        super().__init__()
        self.hardware_serial = hardware_serial
        self.info_requests = 0
        self.status_requests = 0

    def _handle_info(self, request: Frame) -> bytes:
        self.info_requests += 1
        original = decode_frame(super()._handle_info(request))
        info = replace(
            DeviceInfo.from_payload(original.payload),
            hardware_serial=self.hardware_serial,
        )
        return encode_frame(
            FrameKind.INFO_RESPONSE,
            info.to_payload(),
            flags=original.header.flags,
            run_id=original.header.run_id,
            request_id=original.header.request_id,
        )

    def _handle_status(self, request: Frame) -> bytes:
        self.status_requests += 1
        return super()._handle_status(request)

    def arm_counter_and_sequence_wrap(self) -> None:
        self._adc_sequence = constants.UINT32_MAX
        self._adc_first_ticks = (
            constants.UINT64_MAX + 1 - constants.FRAME_COVERAGE_TICKS
        )
        self._adc_item_index = 0
        self._stats_generation = constants.UINT32_MAX


def _probe_info(device: SimulatedDevice, *, request_id: int) -> DeviceInfo:
    responses = device.receive(
        encode_frame(FrameKind.INFO_REQUEST, request_id=request_id)
    )
    if len(responses) != 1:
        raise AssertionError("fake discovery INFO did not return exactly one response")
    message = decode_message(decode_frame(responses[0]))
    if not isinstance(message, CommandResponse) or not isinstance(
        message.value, DeviceInfo
    ):
        raise TypeError("fake discovery INFO returned the wrong model")
    return message.value


def _discovered(port: str, serial: int, info: DeviceInfo) -> DiscoveredDevice:
    return DiscoveredDevice(
        candidate=SerialPortCandidate(
            port=port,
            vid=0x16C0,
            pid=0x0483,
            serial_number=str(serial),
            product="Teensy DAQ",
            manufacturer="PJRC",
            interface="CDC",
        ),
        info=info,
    )


class ReconnectAndWrapRecoveryTests(unittest.TestCase):
    def test_renamed_port_reprobes_adopts_wraps_and_cleans_up(self) -> None:
        hardware_serial = 12_345_670
        device = _StableSerialDevice(hardware_serial)
        opened_ports: list[str] = []
        transports: list[InMemoryTransport] = []

        def transport_factory(port: str) -> InMemoryTransport:
            opened_ports.append(port)
            transport = InMemoryTransport(device)
            transports.append(transport)
            return transport

        initial_endpoint = _discovered(
            "/dev/ttyACM0",
            hardware_serial,
            _probe_info(device, request_id=0x7000_0001),
        )
        initial = TeensyDAQ.open(
            initial_endpoint,
            serial_transport_factory=transport_factory,
            synchronization_retry_delay=0,
        )
        initial.configure(adc=True, gpio=False, source=Source.SYNTHETIC)
        run_id = initial.start()
        initial.close(stop=False)
        self.assertEqual(DeviceState.RUNNING, device.state)
        self.assertFalse(initial.reader.is_running)

        device.arm_counter_and_sequence_wrap()
        renamed_endpoint = _discovered(
            "/dev/ttyACM7",
            hardware_serial,
            _probe_info(device, request_id=0x7000_0002),
        )
        info_before_reopen = device.info_requests
        status_before_reopen = device.status_requests

        with (
            patch(
                "teensy_daq.client.discover_devices",
                return_value=(renamed_endpoint,),
            ),
            TeensyDAQ.open(
                hardware_serial=hardware_serial,
                serial_transport_factory=transport_factory,
                session_policy=SessionRecoveryPolicy.ADOPT,
                synchronization_retry_delay=0,
            ) as reopened,
        ):
            self.assertEqual(info_before_reopen + 2, device.info_requests)
            self.assertEqual(status_before_reopen + 1, device.status_requests)
            self.assertEqual(DeviceState.RUNNING, reopened.state)
            self.assertEqual(run_id, reopened.run_id)
            self.assertIsNotNone(reopened.configuration)
            assert reopened.configuration is not None
            self.assertEqual(StreamMask.ADC, reopened.configuration.stream_mask)
            self.assertIsNotNone(reopened.verified_identity)
            assert reopened.verified_identity is not None
            self.assertEqual(
                hardware_serial,
                reopened.verified_identity.hardware_serial,
            )

            before_wrap = reopened.read_block()
            after_wrap = reopened.read_block()
            self.assertIsInstance(before_wrap, ADCBlock)
            self.assertIsInstance(after_wrap, ADCBlock)
            assert isinstance(before_wrap, ADCBlock)
            assert isinstance(after_wrap, ADCBlock)
            self.assertEqual(constants.UINT32_MAX, before_wrap.sequence)
            self.assertEqual(
                constants.UINT64_MAX + 1 - constants.FRAME_COVERAGE_TICKS,
                before_wrap.first_sample_ticks,
            )
            self.assertEqual(
                (0, 0),
                (
                    after_wrap.sequence,
                    after_wrap.first_sample_ticks,
                ),
            )

            live_status = reopened.status()
            live_report = reconcile_run_counters(live_status, run_id=run_id)
            self.assertEqual(constants.UINT32_MAX, live_report.stats_generation)
            self.assertTrue(live_report.exact)
            live_losses = reopened.loss_counters(refresh=False)
            self.assertEqual(0, live_losses.observed_stream_gaps)
            self.assertEqual(0, live_losses.host.host_block_queue_drops)
            self.assertFalse(live_losses.firmware.has_loss)

            self.assertEqual(DeviceState.IDLE, reopened.stop())
            self.assertEqual(1, reopened.reset_stats())
            idle_status = reopened.status()
            idle_report = reconcile_run_counters(idle_status, run_id=run_id)
            self.assertEqual(1, idle_report.stats_generation)
            self.assertTrue(idle_report.exact)

        self.assertEqual(
            ["/dev/ttyACM0", "/dev/ttyACM7"],
            opened_ports,
        )
        self.assertEqual(DeviceState.IDLE, device.state)
        self.assertFalse(initial.is_open)
        self.assertFalse(reopened.is_open)
        self.assertEqual(0, initial.reader.pending_count)
        self.assertEqual(0, reopened.reader.pending_count)
        self.assertTrue(all(not transport.is_open for transport in transports))
        self.assertTrue(
            all(not reader.is_running for reader in (initial.reader, reopened.reader))
        )


if __name__ == "__main__":  # pragma: no cover
    unittest.main()
