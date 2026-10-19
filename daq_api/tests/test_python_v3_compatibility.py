"""Cross-version public-client regression matrix with hostile wire peers.

These are offline personas, not firmware qualification. The current v3-only
persona must reject explicit v2 use without silently changing its session.
"""

import struct
from dataclasses import replace

import pytest
from test_protocol_v3_codecs import patch
from test_simulator_v3 import raw_request
from test_version_negotiation import RecordingTransport
from thingdone_daq import (
    ADCBlock,
    CommandTimeoutError,
    DAQConfiguration,
    DeviceCapabilityError,
    DeviceCommandError,
    GPIOBlock,
    InMemoryTransport,
    RateProfile,
    ThingDAQ,
    UnexpectedMessageError,
)
from thingdone_daq._generated import protocol_constants as legacy
from thingdone_daq._generated import protocol_v3_constants as c
from thingdone_daq.models_v3 import V3Capabilities, V3Settings, decode_v3_response
from thingdone_daq.protocol_v3 import decode_v3_frame
from thingdone_daq.reader import ReaderProtocolError, RequestTimeoutError
from thingdone_daq.simulator import SimulatedDevice
from thingdone_daq.simulator_v3 import SimulatedV3Device


@pytest.mark.parametrize("version,gpio_period", [(1, 2), (2, 8), (3, 8)])
@pytest.mark.parametrize("chunk_size", [1, 17, None])
def test_automatic_selection_capture_stop_restart_and_reconnect(
    version, gpio_period, chunk_size
):
    device = (
        SimulatedV3Device()
        if version == 3
        else SimulatedDevice(protocol_version=version)
    )
    for connection in range(2):
        transport = RecordingTransport(
            device, read_chunk_size=chunk_size, write_chunk_size=chunk_size
        )
        with ThingDAQ.open(
            transport, strict=True, command_timeout=3, block_timeout=3
        ) as daq:
            assert daq.device_info.protocol_version == version
            daq.configure()
            assert daq.configuration.adc_pair_rate_hz == 1_000_000
            assert daq.configuration.gpio_sample_rate_hz == 8_000_000 // gpio_period
            for epoch in range(2):
                run = daq.start()
                assert run == connection * 2 + epoch + 1
                blocks = list(daq.blocks(4))
                assert [type(b) for b in blocks] == [ADCBlock, GPIOBlock] * 2
                assert [b.sequence for b in blocks] == [0, 0, 1, 1]
                for block in blocks:
                    period = 8 if isinstance(block, ADCBlock) else gpio_period
                    assert block.protocol_version == version and block.run_id == run
                    assert (
                        block.first_sample_ticks
                        == block.sequence * block.item_count * period
                    )
                    assert (
                        block.end_tick_exclusive
                        == (block.sequence + 1) * block.item_count * period
                    )
                    assert block.decoded_bytes == 4048
                daq.stop()
                boundary = len(transport.requests)
                assert daq.info().protocol_version == version
                daq.status()
                daq.configure()
                assert all(
                    f.header.version == version for f in transport.requests[boundary:]
                )
            if version < 3:
                assert not any(
                    f.header.kind
                    in (c.CommandKind.GET_CAPABILITIES, c.CommandKind.GET_SETTINGS)
                    for f in transport.requests
                )
            assert not daq.loss_counters().has_loss
        assert not transport.is_open and not daq.reader.is_running


@pytest.mark.parametrize("running", [False, True])
@pytest.mark.parametrize(
    "kind", [legacy.FrameKind.INFO_REQUEST, legacy.FrameKind.CONFIGURE_REQUEST]
)
def test_explicit_v2_request_on_current_v3_only_persona_is_bounded_and_nonmutating(
    running,
    kind,
):
    with ThingDAQ.simulated(protocol_version=3) as daq:
        before = daq.get_settings()
        if running:
            daq.start()
        payload = b""
        if kind == legacy.FrameKind.CONFIGURE_REQUEST:
            payload = DAQConfiguration(
                stream_mask=legacy.StreamMask.ADC | legacy.StreamMask.GPIO,
                source=legacy.Source.HARDWARE,
                rate_profile=RateProfile.ADC_1MHZ_GPIO_1MHZ,
            ).to_payload(protocol_version=2)
        with pytest.raises(RequestTimeoutError):
            daq.reader.request(kind, payload, protocol_version=2, timeout=0.02)
        assert daq.reader_counters.pending_requests == 0
        assert daq.info().protocol_version == 3
        assert daq.get_settings() == before
        if running:
            assert daq.read_block().protocol_version == 3
            daq.stop()
        assert daq.start() > 0
        assert daq.read_block().protocol_version == 3


@pytest.mark.parametrize("kind", range(0x15, 0x1C))
def test_reserved_legacy_commands_return_correlated_error_without_mutation(kind):
    device = SimulatedV3Device()
    before = device.settings, device.status(), device.info()
    wire = raw_request(kind=kind, request_id=42, payload=b"")
    replies = device.receive(wire)
    assert len(replies) == 1
    reply = decode_v3_response(decode_v3_frame(replies[0]))
    assert reply.request_id == 42 and not reply.ok
    assert reply.error_code == c.ErrorCode.UNKNOWN_FRAME_KIND
    assert reply.kind == c.FrameKind.ERROR_RESPONSE
    assert (device.settings, device.status(), device.info()) == before


class FaultyMetadataPeer(SimulatedV3Device):
    """Rechecksum real replies so metadata failures cannot hide as CRC failures."""

    fault = None

    def _reply(self, kind, request_id, value=None, error=c.ErrorCode.OK):
        if kind == c.CommandKind.GET_CAPABILITIES and self.fault == "missing":
            return super()._reply(
                kind, request_id, error=c.ErrorCode.UNKNOWN_FRAME_KIND
            )
        wire = super()._reply(kind, request_id, value, error)
        if kind == c.CommandKind.GET_CAPABILITIES:
            offsets = {
                "empty_clocks": (4, b"\0"),
                "empty_rates": (5, b"\0"),
                "too_many_tuples": (6, b"\xff"),
                "duplicate_clock": (80, c.CPU_PROFILES[0]),
                "duplicate_tuple": (144, c.SELECTABLE_CONFIGURATIONS[0]),
                "unused_slot": (1324, b"\x01"),
            }
            if self.fault in offsets:
                offset, data = offsets[self.fault]
                return patch(wire, c.HEADER_SIZE + offset, data)
        if kind == c.CommandKind.GET_SETTINGS and self.fault == "readback":
            # RAW at 600 MHz is valid in isolation, but contradicts CONFIGURE.
            return patch(wire, c.HEADER_SIZE + 4 + 8, b"\0")
        return wire


@pytest.mark.parametrize(
    "fault",
    [
        "missing",
        "empty_clocks",
        "empty_rates",
        "too_many_tuples",
        "duplicate_clock",
        "duplicate_tuple",
        "unused_slot",
    ],
)
def test_missing_or_malformed_capabilities_fail_open_without_downgrade_or_configuration(
    fault,
):
    device = FaultyMetadataPeer()
    device.fault = fault
    before = device.settings
    transport = RecordingTransport(device)
    expected = (
        DeviceCommandError
        if fault == "missing"
        else (CommandTimeoutError, ReaderProtocolError)
    )
    with pytest.raises(expected):
        ThingDAQ.open(transport, command_timeout=0.2, synchronization_attempts=2)
    assert not transport.is_open
    assert device.settings == before and device.run_id == 0
    assert all(frame.header.version == 3 for frame in transport.requests)
    assert [frame.header.kind for frame in transport.requests] == [
        c.CommandKind.INFO,
        c.CommandKind.INFO,
        c.CommandKind.GET_CAPABILITIES,
    ]


def test_mismatched_readback_leaves_last_verified_configuration_and_recovers():
    device = FaultyMetadataPeer()
    with ThingDAQ.open(InMemoryTransport(device)) as daq:
        before = daq.configuration
        device.fault = "readback"
        with pytest.raises(UnexpectedMessageError, match="GET_SETTINGS differs"):
            daq.configure(gpio=False)
        assert daq.configuration == before
        device.fault = None
        assert daq.get_settings().settings == device.settings
        assert daq.configure().settings == before
        daq.start()
        assert daq.read_block().protocol_version == 3


def test_unadvertised_tuple_never_reaches_device_and_reconnect_refreshes_table():
    device = SimulatedV3Device()
    device._capabilities = replace(
        device._capabilities, configurations=(device.settings,)
    )
    transport = RecordingTransport(device)
    with ThingDAQ.open(transport) as daq:
        before = len(transport.requests)
        with pytest.raises(DeviceCapabilityError, match="not advertised"):
            daq.configure(adc_policy=c.AdcPolicy.RAW)
        assert len(transport.requests) == before
        assert daq.configuration == device.settings
    # A new image advertises more tuples; an external client selects RAW.
    changed = replace(V3Settings.defaults(), adc_policy=c.AdcPolicy.RAW)
    device._capabilities = V3Capabilities.canonical()
    device.reboot()
    device._settings = changed
    device._build_id = "reconnected-new-image"
    with ThingDAQ.open(InMemoryTransport(device)) as daq:
        assert len(daq.capabilities.configurations) == 60
        assert daq.device_info.build_id == "reconnected-new-image"
        assert daq.configuration == changed
        assert daq.configure(adc_policy=c.AdcPolicy.RAW).settings == changed
        daq.start()
        assert daq.read_block().encoding == c.Encoding.RAW


class StaleReplyPeer(SimulatedV3Device):
    def _reply(self, kind, request_id, value=None, error=c.ErrorCode.OK):
        wire = super()._reply(kind, request_id, value, error)
        stale_id = 0xFFFFFFFF if request_id != 0xFFFFFFFF else 0xFFFFFFFE
        stale = patch(wire, 28, struct.pack("<I", stale_id))
        data = b""
        if kind == c.CommandKind.GET_STATUS and self.state == c.DeviceState.RUNNING:
            data = self.next_data_frame() or b""
        return stale + data + wire


@pytest.mark.parametrize("chunk_size", [1, 17, None])
def test_wrong_request_ids_and_mixed_control_stream_chunks_never_match(chunk_size):
    transport = RecordingTransport(StaleReplyPeer(), read_chunk_size=chunk_size)
    with ThingDAQ.open(transport, command_timeout=3) as daq:
        daq.configure()
        daq.start()
        for sequence in range(4):
            status = daq.status()
            assert status.run_id == daq.run_id
            # GET_STATUS injects one stream frame between wrong-ID and real replies.
            block = daq.reader.get_block(timeout=1)
            assert block.sequence == sequence // 2
            assert block.run_id == daq.run_id
        counters = daq.reader_counters
        assert counters.late_responses == counters.responses_matched
        assert counters.pending_requests == 0
        assert counters.adc_frames_received == counters.gpio_frames_received == 2
        assert daq.parser_counters.corruption_events == 0


@pytest.mark.parametrize("private_version", [0x82, 0x83])
def test_private_info_response_never_authorizes_fallback(private_version):
    device = SimulatedV3Device()

    def private_reply(request):
        wire = device.receive(request.to_bytes())[0]
        return patch(wire, 4, bytes([private_version]))

    transport = RecordingTransport(reply=private_reply)
    with pytest.raises(CommandTimeoutError):
        ThingDAQ.open(
            transport,
            command_timeout=0.02,
            synchronization_attempts=2,
            synchronization_retry_delay=0,
        )
    assert 1 <= len(transport.requests) <= 2
    assert all(frame.header.version == 3 for frame in transport.requests)
    assert not transport.is_open
