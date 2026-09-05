"""The v2-only temperature command preserves v1 and rejects ambiguous readings."""

import struct

import pytest
from thingdaq._generated import protocol_v2_constants as c
from thingdaq.protocol_v2 import (
    IncrementalV2FrameParser,
    V2FrameValidationError,
    decode_temperature_payload,
    decode_v2_frame,
    encode_v2_frame,
)


@pytest.mark.parametrize("value", [-40000, -5000, 0, 42500, 150000])
def test_temperature_round_trip(value):
    payload = struct.pack("<BBHBBHi", 0, 0, 0, 0, 0, 0, value)
    wire = encode_v2_frame(c.FrameKind.GET_TEMPERATURE_RESPONSE, payload, request_id=26)
    frame = decode_v2_frame(wire)
    reading = decode_temperature_payload(frame.payload)
    assert reading.celsius == value / 1000
    parser = IncrementalV2FrameParser()
    frames = []
    for byte in wire:
        frames.extend(parser.feed(bytes([byte])))
    assert len(frames) == 1


@pytest.mark.parametrize("status", [1, 2, 3, 4])
def test_unavailable_is_not_zero_degrees(status):
    reading = decode_temperature_payload(
        struct.pack("<BBHBBHi", 0, 0, 0, status, 0, 0, 0)
    )
    assert reading.millidegrees_c is None
    assert reading.celsius is None


@pytest.mark.parametrize(
    "sensor,reserved,value",
    [
        (5, 0, 0),
        (0, 1, 42000),
        (0, 0, -40001),
        (0, 0, 150001),
        (2, 0, 1000),
    ],
)
def test_bad_temperature_fields(sensor, reserved, value):
    with pytest.raises(V2FrameValidationError):
        decode_temperature_payload(
            struct.pack("<BBHBBHi", 0, 0, 0, sensor, reserved, 0, value)
        )


def test_request_is_empty():
    wire = encode_v2_frame(c.FrameKind.GET_TEMPERATURE_REQUEST, request_id=26)
    assert decode_v2_frame(wire).payload == b""
    with pytest.raises(V2FrameValidationError):
        encode_v2_frame(c.FrameKind.GET_TEMPERATURE_REQUEST, b"x", request_id=26)


def test_public_temperature_command_idle_configured_and_running():
    from thingdaq import Source, TemperatureStatus, ThingDAQ

    with ThingDAQ.simulated() as daq:
        assert daq.get_temperature().status is TemperatureStatus.UNAVAILABLE
        daq.configure(source=Source.SYNTHETIC)
        assert daq.get_temperature().celsius is None
        daq.start()
        assert daq.get_temperature().celsius is None
        daq.stop()
        assert daq.get_temperature().celsius is None


def test_fast_adc_range_check_covers_every_uint16():
    from thingdaq.protocol import adc_payload_codes_valid

    for code in range(65536):
        payload = struct.pack("<HH", code, code)
        assert adc_payload_codes_valid(payload) == (code <= 4095)


def test_simulator_temperature_replay_uses_correlated_typed_error():
    from thingdaq.simulator import SimulatedDevice

    device = SimulatedDevice()
    request = encode_v2_frame(c.FrameKind.GET_TEMPERATURE_REQUEST, request_id=26)
    assert decode_v2_frame(device.receive(request)[0]).payload[0] == 0
    rejected = decode_v2_frame(device.receive(request)[0])
    assert rejected.header.kind is c.FrameKind.GET_TEMPERATURE_RESPONSE
    assert rejected.header.request_id == 26
    assert len(rejected.payload) == 4
    assert (
        int.from_bytes(rejected.payload[2:4], "little")
        == c.ErrorCode.INVALID_REQUEST_ID
    )
