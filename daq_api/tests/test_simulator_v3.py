"""Public-v3 device tests through real command bytes and the existing transport."""

import struct
import zlib
from dataclasses import replace

import pytest
from thingdone_daq._generated import protocol_v3_constants as c
from thingdone_daq.models_v3 import (
    V3Capabilities,
    V3Command,
    V3Info,
    V3Settings,
    V3Status,
    V3Stop,
    decode_v3_response,
)
from thingdone_daq.protocol import encode_frame
from thingdone_daq.protocol_v3 import (
    V3FrameParser,
    compute_v3_checksum,
    decode_data_payload,
    decode_v3_block,
    decode_v3_frame,
)
from thingdone_daq.simulator import SimulatorInputError
from thingdone_daq.simulator_v3 import SimulatedV3Device
from thingdone_daq.transport import InMemoryTransport


def command(device, kind, request_id, settings=None):
    request = V3Command(kind, request_id, settings)
    responses = device.receive(request.to_bytes())
    assert len(responses) == 1
    response = decode_v3_response(decode_v3_frame(responses[0]))
    response.validate_for(request)
    return response


def raw_request(kind=c.CommandKind.CONFIGURE, request_id=1, payload=None, **fields):
    payload = V3Settings.defaults().to_bytes() if payload is None else payload
    header = {
        "magic": c.MAGIC,
        "version": 3,
        "kind": kind,
        "flags": 0,
        "size": 44,
        "checksum": 1,
        "reserved": 0,
        "total": 48 + len(payload),
        "length": len(payload),
        "run": 0,
        "sequence": 0,
        "request": request_id,
        "ticks": 0,
        "count": 0,
    }
    header.update(fields)
    wire = struct.pack(c.HEADER_STRUCT_FORMAT, *header.values()) + payload
    return wire + struct.pack("<I", compute_v3_checksum(wire))


@pytest.mark.parametrize(
    ("settings_hex", "cpu_hz"),
    [
        ("030001030104000801010c0040420f0040420f00", 600_000_000),
        ("030001030104011001010c0040420f0040420f00", 600_000_000),
        ("030001030204000800000c0040420f0040420f00", 450_000_000),
    ],
)
def test_wire_lifecycle_with_literal_settings_and_independent_response_checks(
    settings_hex, cpu_hz
):
    device = SimulatedV3Device()
    request_id = 0

    def exchange(kind, payload=b"", *, run=0, error=0):
        nonlocal request_id
        request_id += 1
        request = raw_request(kind=kind, request_id=request_id, payload=payload)
        # Cross-check the shared request checksum with an independent backend.
        assert int.from_bytes(request[-4:], "little") == zlib.adler32(request[:-4])
        responses = device.receive(request)
        assert len(responses) == 1
        response = responses[0]
        assert response[:6] == bytes.fromhex("efbeadde03") + bytes([kind + 0x80])
        assert struct.unpack_from("<H", response, 6)[0] == (0x8000 if error else 0)
        assert response[8:12] == bytes.fromhex("2c000100")
        assert struct.unpack_from("<IIIIIQI", response, 12) == (
            len(response),
            len(response) - 48,
            run,
            0,
            request_id,
            0,
            0,
        )
        assert int.from_bytes(response[-4:], "little") == zlib.adler32(response[:-4])
        assert response[44:48] == struct.pack("<BBH", bool(error), 0, error)
        if error:
            assert len(response) == 52
        return response[48:-4]

    defaults = bytes.fromhex("030001030104000801010c0040420f0040420f00")
    assert exchange(0x1D)[:20] == defaults
    settings = bytes.fromhex(settings_hex)
    applied = exchange(0x11, settings)
    expected_clocks = struct.pack(
        "<B3xIIIII", settings[4], cpu_hz, 150_000_000, 37_500_000, 24_000_000, 8_000_000
    )
    assert applied == settings + expected_clocks
    assert exchange(0x1D) == applied

    # Malformed/unsupported stopped requests must leave the complete applied
    # settings and clocks untouched, even if an early field could be applied.
    for offset, value, error in ((4, 2, 8), (3, 2, 8), (11, 1, 5)):
        bad = bytearray(defaults)
        bad[offset] = value
        exchange(0x11, bad, error=error)
        assert exchange(0x1D) == applied

    assert exchange(0x12, run=1) == applied
    exchange(0x11, defaults, run=1, error=7)
    exchange(0x12, run=1, error=7)
    assert exchange(0x1D, run=1) == applied
    # No streaming request means no pending tail; STOP is immediately stopped.
    stopped = bytes.fromhex("010000000100000000000000")
    assert exchange(0x14, run=1) == stopped
    assert exchange(0x14, run=1) == stopped
    assert exchange(0x1D, run=1) == applied
    assert exchange(0x12, run=2) == applied
    exchange(0x14, run=2)
    device.reboot()
    assert exchange(0x1D)[:20] == defaults


def test_default_identity_and_settings_are_explicitly_simulated():
    device = SimulatedV3Device()
    info = command(device, c.CommandKind.INFO, 1).value
    assert isinstance(info, V3Info)
    assert info.simulated and info.hardware_serial.startswith("SIM-")
    assert info.clocks.cpu_clock_hz == 600_000_000
    caps = command(device, c.CommandKind.GET_CAPABILITIES, 2).value
    assert isinstance(caps, V3Capabilities)
    assert len(caps.configurations) == 60
    assert caps.defaults == device.settings == V3Settings.defaults()
    assert (
        caps.defaults.adc_pair_rate_hz == caps.defaults.gpio_sample_rate_hz == 1_000_000
    )
    assert caps.defaults.aux_bank_mode == c.AuxBankMode.DISABLED
    assert caps.defaults.gpio_policy == c.GpioPolicy.RLE_AUTO
    assert caps.defaults.adc_policy == c.AdcPolicy.PACK12
    assert (
        command(device, c.CommandKind.GET_SETTINGS, 3).value.settings == caps.defaults
    )
    assert device.state == c.DeviceState.STOPPED


@pytest.mark.parametrize("settings", V3Capabilities.canonical().configurations)
def test_every_advertised_tuple_configures_and_streams(settings):
    device = SimulatedV3Device()
    configured = command(device, c.CommandKind.CONFIGURE, 1, settings)
    assert configured.value.settings == settings
    assert command(device, c.CommandKind.GET_SETTINGS, 2).value == configured.value
    assert (
        command(device, c.CommandKind.INFO, 3).value.clocks == configured.value.clocks
    )
    started = command(device, c.CommandKind.START, 4)
    assert started.run_id == 1 and started.value == configured.value
    seen = {c.FrameKind.ADC_DATA: [], c.FrameKind.GPIO_DATA: []}
    for _ in range(8):
        frame = decode_v3_frame(device.next_data_frame())
        block = decode_v3_block(frame, settings)
        history = seen[frame.header.kind]
        assert frame.header.sequence == len(history)
        assert (
            frame.header.first_sample_ticks
            == len(history) * frame.header.item_count * 8
        )
        assert bool(frame.header.flags & c.FrameFlag.EPOCH_START) == (not history)
        assert bool(frame.header.flags & c.FrameFlag.SYNTHETIC) == (
            settings.source == c.Source.SYNTHETIC
        )
        assert block.run_id == 1
        history.append(frame)
    for kind, frames in seen.items():
        if not frames:
            continue
        if kind == c.FrameKind.GPIO_DATA:
            expected_encodings = (
                [c.Encoding.GPIO_RLE, c.Encoding.RAW]
                if settings.gpio_policy == c.GpioPolicy.RLE_AUTO
                else [c.Encoding.RAW] * 2
            )
            assert [frame.payload[0] for frame in frames[:2]] == expected_encodings
            for index, frame in enumerate(frames):
                decoded = decode_data_payload(
                    kind, frame.payload, frame.header.item_count
                )
                pattern = (
                    bytes([0xAA, 0x55])
                    if settings.gpio_width_bits == 8
                    else bytes([0xAA, 0x0F, 0x55, 0xF0])
                )
                expected = (
                    bytes(decoded.decoded_bytes)
                    if index % 2 == 0
                    else pattern * (decoded.decoded_bytes // len(pattern))
                )
                assert decoded.payload == expected
        else:
            first = 0
            for frame in frames:
                decoded = decode_data_payload(
                    kind, frame.payload, frame.header.item_count
                )
                expected_encoding = (
                    c.Encoding.ADC_PACK12
                    if settings.adc_policy == c.AdcPolicy.PACK12
                    else c.Encoding.RAW
                )
                assert decoded.encoding == expected_encoding
                for offset, pair in enumerate(
                    struct.iter_unpack("<HH", decoded.payload)
                ):
                    phase = (first + offset) % 2048
                    edges = ((0, 0), (4095, 4095), (0xABC, 0x123), (0x555, 0xAAA))
                    assert pair == (
                        edges[phase] if phase < 4 else (2 * phase, 2 * phase + 1)
                    )
                first += frame.header.item_count
    stopped = command(device, c.CommandKind.STOP, 5).value
    assert stopped == V3Stop(c.DeviceState.STOPPED, 1, 0)
    status = command(device, c.CommandKind.GET_STATUS, 6).value
    assert isinstance(status, V3Status)
    assert status.adc_frames_produced == len(seen[c.FrameKind.ADC_DATA])
    assert status.gpio_frames_produced == len(seen[c.FrameKind.GPIO_DATA])
    assert status.adc_items_produced == sum(
        f.header.item_count for f in seen[c.FrameKind.ADC_DATA]
    )
    assert status.gpio_items_produced == sum(
        f.header.item_count for f in seen[c.FrameKind.GPIO_DATA]
    )
    assert device.next_data_frame() is None
    assert command(device, c.CommandKind.STOP, 7).value == stopped
    assert command(device, c.CommandKind.GET_SETTINGS, 8).value == configured.value
    assert command(device, c.CommandKind.START, 9).run_id == 2
    assert (
        device.status().adc_frames_produced == device.status().gpio_frames_produced == 0
    )


def test_atomic_configuration_state_reboot_and_reconnect():
    device = SimulatedV3Device()
    defaults = device.settings
    raw = replace(
        defaults,
        cpu_profile=c.CpuProfile.CPU_450MHZ,
        gpio_policy=c.GpioPolicy.RAW,
        adc_policy=c.AdcPolicy.RAW,
    )
    command(device, c.CommandKind.CONFIGURE, 1, raw)
    assert device.info().clocks.cpu_clock_hz == 450_000_000
    command(device, c.CommandKind.START, 2)
    assert (
        command(device, c.CommandKind.CONFIGURE, 3, defaults).error_code
        == c.ErrorCode.INVALID_STATE
    )
    assert (
        command(device, c.CommandKind.START, 4).error_code == c.ErrorCode.INVALID_STATE
    )
    assert device.settings == raw and device.run_id == 1
    device.begin_host_session()
    assert command(device, c.CommandKind.GET_SETTINGS, 1).value.settings == raw
    assert device.state == c.DeviceState.RUNNING
    command(device, c.CommandKind.STOP, 2)
    command(device, c.CommandKind.CONFIGURE, 3, defaults)
    assert device.info().clocks.cpu_clock_hz == 600_000_000
    command(device, c.CommandKind.CONFIGURE, 4, raw)
    device.reboot()
    assert device.settings == defaults and device.run_id == 0
    assert command(device, c.CommandKind.START, 1).run_id == 1


@pytest.mark.parametrize(
    ("field", "value", "error"),
    [
        ("flags", 1, c.ErrorCode.INVALID_FLAGS),
        ("reserved", 1, c.ErrorCode.INVALID_PAYLOAD),
        ("run", 1, c.ErrorCode.INVALID_PAYLOAD),
        ("sequence", 1, c.ErrorCode.INVALID_PAYLOAD),
        ("ticks", 8, c.ErrorCode.INVALID_PAYLOAD),
        ("count", 1, c.ErrorCode.INVALID_PAYLOAD),
        ("request", 0, c.ErrorCode.INVALID_REQUEST_ID),
        ("kind", 0x15, c.ErrorCode.UNKNOWN_FRAME_KIND),
    ],
)
def test_malformed_envelope_errors_do_not_mutate(field, value, error):
    device = SimulatedV3Device()
    wire = raw_request(**{field: value})
    response = decode_v3_response(decode_v3_frame(device.receive(wire)[0]))
    assert response.error_code == error
    assert device.settings == V3Settings.defaults() and device.run_id == 0


@pytest.mark.parametrize(
    ("offset", "value", "error"),
    [
        (0, 0, c.ErrorCode.INVALID_PAYLOAD),
        (4, 255, c.ErrorCode.INVALID_PAYLOAD),
        (11, 1, c.ErrorCode.INVALID_PAYLOAD),
        (4, 2, c.ErrorCode.UNSUPPORTED_CONFIGURATION),
        (7, 16, c.ErrorCode.UNSUPPORTED_CONFIGURATION),
        (3, 2, c.ErrorCode.UNSUPPORTED_CONFIGURATION),
    ],
)
def test_bad_settings_are_atomic_and_state_precedes_tuple_membership(
    offset, value, error
):
    device = SimulatedV3Device()
    payload = bytearray(device.settings.to_bytes())
    payload[offset] = value
    for request_id in (1, 3):
        if request_id == 3:
            command(device, c.CommandKind.START, 2)
        response = decode_v3_response(
            decode_v3_frame(
                device.receive(raw_request(request_id=request_id, payload=payload))[0]
            )
        )
        assert response.error_code == (
            c.ErrorCode.INVALID_STATE
            if request_id == 3 and error == c.ErrorCode.UNSUPPORTED_CONFIGURATION
            else error
        )
        assert device.settings == V3Settings.defaults()


def test_request_replay_bounds_corruption_and_chunked_recovery():
    device = SimulatedV3Device(max_requests_per_receive=1)
    wire = V3Command(c.CommandKind.INFO, 1).to_bytes()
    broken = bytearray(wire)
    broken[-1] ^= 1
    assert device.receive(broken) == ()
    assert device.receive(encode_frame(0x10, request_id=20)) == ()
    for byte in wire[:-1]:
        assert device.receive(bytes([byte])) == ()
    assert len(device.receive(wire[-1:])) == 1
    assert (
        command(device, c.CommandKind.INFO, 1).error_code
        == c.ErrorCode.INVALID_REQUEST_ID
    )
    for request_id in range(2, 18):
        assert (
            command(device, c.CommandKind.INFO, request_id).error_code == c.ErrorCode.OK
        )
    assert command(device, c.CommandKind.INFO, 1).error_code == c.ErrorCode.OK
    batch = b"".join(V3Command(c.CommandKind.START, i).to_bytes() for i in (18, 19))
    responses = [
        decode_v3_response(decode_v3_frame(wire)) for wire in device.receive(batch)
    ]
    assert [r.error_code for r in responses] == [c.ErrorCode.OK, c.ErrorCode.BUSY]
    assert device.run_id == 1
    with pytest.raises(SimulatorInputError):
        device.receive(bytes(device.max_receive_bytes + 1))
    response = decode_v3_response(
        decode_v3_frame(device.receive(raw_request(request_id=20, payload=b""))[0])
    )
    assert response.error_code == c.ErrorCode.INVALID_LENGTH


@pytest.mark.parametrize("readinto", [False, True])
def test_partial_frame_stop_drain_blocks_restart_and_configuration(readinto):
    device = SimulatedV3Device()
    transport = InMemoryTransport(device, write_chunk_size=7)
    parser = V3FrameParser()

    def write(kind, request_id, settings=None):
        wire = V3Command(kind, request_id, settings).to_bytes()
        while wire:
            count = transport.write(wire)
            assert count
            wire = wire[count:]

    def read(size):
        if readinto:
            buffer = bytearray(size)
            return bytes(buffer[: transport.readinto(buffer)])
        return transport.read(size)

    write(c.CommandKind.START, 1)
    assert decode_v3_response(parser.feed(read(4096))[0]).run_id == 1
    transport.request_stream_frame()
    assert parser.feed(read(5)) == []
    write(c.CommandKind.STOP, 2)
    assert device.state == c.DeviceState.DRAINING
    write(c.CommandKind.START, 3)
    write(c.CommandKind.CONFIGURE, 4, device.settings)
    write(c.CommandKind.GET_STATUS, 5)
    frames = []
    while transport.pending_bytes:
        frames.extend(parser.feed(read(17)))
    assert frames[0].header.kind == c.FrameKind.ADC_DATA
    responses = [decode_v3_response(frame) for frame in frames[1:]]
    assert responses[0].value == V3Stop(c.DeviceState.DRAINING, 1, 1)
    assert [r.error_code for r in responses[1:3]] == [c.ErrorCode.BUSY] * 2
    assert responses[3].value.pending_frames == 1
    assert device.state == c.DeviceState.STOPPED
    write(c.CommandKind.GET_STATUS, 6)
    assert decode_v3_response(parser.feed(read(4096))[0]).value.pending_frames == 0
    write(c.CommandKind.START, 7)
    assert decode_v3_response(parser.feed(read(4096))[0]).run_id == 2
    transport.close()


def test_v3_response_capacity_is_reserved_before_command_mutation():
    device = SimulatedV3Device()
    transport = InMemoryTransport(
        device, max_pending_bytes=c.MAX_DATA_FRAME_BYTES + c.MAX_CONTROL_FRAME_BYTES
    )
    for request_id in (1, 2, 3):
        assert (
            transport.write(
                V3Command(c.CommandKind.GET_CAPABILITIES, request_id).to_bytes()
            )
            == 48
        )
    assert transport.write(V3Command(c.CommandKind.START, 4).to_bytes()) == 0
    assert device.run_id == 0
    transport.close()


def test_transport_close_accounts_for_discarded_tail():
    device = SimulatedV3Device()
    transport = InMemoryTransport(device)
    transport.write(V3Command(c.CommandKind.START, 1).to_bytes())
    transport.read(4096)
    transport.request_stream_frame()
    transport.read(1)
    transport.close()
    assert device.status().adc_frames_dropped == 1
    assert device.status().adc_items_dropped == c.MAX_ADC_PAIRS
    assert device.status().pending_frames == 0
    device.next_data_frame()  # GPIO
    frame = decode_v3_frame(device.next_data_frame())
    assert frame.header.flags & c.FrameFlag.GAP_BEFORE
    assert frame.header.flags & c.FrameFlag.EPOCH_START
