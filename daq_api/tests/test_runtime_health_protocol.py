"""Runtime health stays available during streams and rejects contradictory records."""

import struct

import pytest
from thingdone_daq import (
    DeviceCommandError,
    InMemoryTransport,
    RuntimeHealth,
    Source,
    ThingDAQ,
)
from thingdone_daq._generated import protocol_v2_constants as c
from thingdone_daq.models import decode_message
from thingdone_daq.protocol_v2 import (
    IncrementalV2FrameParser,
    V2FrameValidationError,
    decode_runtime_health_payload,
    decode_v2_frame,
    encode_v2_frame,
)
from thingdone_daq.simulator import SimulatedDevice


def health_payload(**overrides):
    fields = {
        "status": 0,
        "reserved": 0,
        "error": 0,
        "flags": 3,
        "total": 34816,
        "free": 20000,
        "used": 14816,
        "reset": 0x10,
        "timeout": 10000,
        "reserved1": 0,
    }
    fields.update(overrides)
    return struct.pack("<BBH7I", *fields.values())


def test_runtime_health_round_trip_fragmentation_and_public_model():
    wire = encode_v2_frame(
        c.FrameKind.GET_RUNTIME_HEALTH_RESPONSE, health_payload(), request_id=27
    )
    parser = IncrementalV2FrameParser()
    frames = []
    for byte in wire:
        frames.extend(parser.feed(bytes([byte])))
    assert len(frames) == 1
    response = decode_message(frames[0])
    assert response.request_id == 27
    assert response.value == RuntimeHealth(True, True, 34816, 20000, 14816, 0x10, 10000)


@pytest.mark.parametrize(
    "overrides",
    [
        {"flags": 4},
        {"reserved": 1},
        {"reserved1": 1},
        {"status": 1},
        {"error": 1},
        {"free": 34817},
        {"used": 1},
        {"flags": 2},
        {"flags": 1},
        {"timeout": 0},
        {"total": 0, "free": 0, "used": 0},
    ],
)
def test_rejects_ambiguous_health_records(overrides):
    with pytest.raises(V2FrameValidationError):
        decode_runtime_health_payload(health_payload(**overrides))
    with pytest.raises(V2FrameValidationError):
        encode_v2_frame(
            c.FrameKind.GET_RUNTIME_HEALTH_RESPONSE,
            health_payload(**overrides),
            request_id=27,
        )


@pytest.mark.parametrize("size", [0, 4, 31, 33])
def test_rejects_wrong_payload_length(size):
    with pytest.raises(V2FrameValidationError):
        decode_runtime_health_payload(bytes(size))


def test_independent_availability_and_zero_free_watermark():
    unavailable = decode_runtime_health_payload(bytes(32))
    assert unavailable == RuntimeHealth(False, False, 0, 0, 0, 0, 0)
    stack_only = decode_runtime_health_payload(
        health_payload(flags=1, timeout=0, free=0, used=34816)
    )
    assert stack_only.stack_available and stack_only.stack_min_free_bytes == 0
    watchdog_only = decode_runtime_health_payload(
        health_payload(flags=2, total=0, free=0, used=0)
    )
    assert watchdog_only.watchdog_enabled and not watchdog_only.stack_available


def test_request_requires_empty_payload():
    wire = encode_v2_frame(c.FrameKind.GET_RUNTIME_HEALTH_REQUEST, request_id=27)
    assert decode_v2_frame(wire).payload == b""
    with pytest.raises(V2FrameValidationError):
        encode_v2_frame(c.FrameKind.GET_RUNTIME_HEALTH_REQUEST, b"x", request_id=27)


def test_public_runtime_health_during_acquisition():
    expected = RuntimeHealth(False, False, 0, 0, 0, 0, 0)
    with ThingDAQ.simulated() as daq:
        assert daq.get_runtime_health() == expected
        daq.configure(source=Source.SYNTHETIC)
        assert daq.get_runtime_health() == expected
        run_id = daq.start()
        assert daq.get_runtime_health() == expected
        assert daq.run_id == run_id
        daq.stop()
        assert daq.get_runtime_health() == expected


def test_simulator_replay_preserves_typed_error_correlation():
    device = SimulatedDevice()
    wire = encode_v2_frame(c.FrameKind.GET_RUNTIME_HEALTH_REQUEST, request_id=27)
    assert decode_message(decode_v2_frame(device.receive(wire)[0])).ok
    rejected = decode_message(decode_v2_frame(device.receive(wire)[0]))
    assert rejected.kind is c.FrameKind.GET_RUNTIME_HEALTH_RESPONSE
    assert rejected.request_id == 27
    assert not rejected.ok
    assert rejected.error_code == c.ErrorCode.INVALID_REQUEST_ID
    assert rejected.value is None


@pytest.mark.parametrize("generic", [False, True])
def test_public_runtime_health_surfaces_device_rejection(generic):
    class RejectHealthDevice(SimulatedDevice):
        def _handle_frame(self, request):
            if request.header.kind == c.FrameKind.GET_RUNTIME_HEALTH_REQUEST:
                reject = self._generic_error if generic else self._typed_error
                return reject(request, c.ErrorCode.INVALID_STATE)
            return super()._handle_frame(request)

    with ThingDAQ(InMemoryTransport(RejectHealthDevice())) as daq:
        daq.synchronize()
        with pytest.raises(DeviceCommandError) as caught:
            daq.get_runtime_health()
        assert caught.value.command is c.FrameKind.GET_RUNTIME_HEALTH_REQUEST
        assert caught.value.error_code == c.ErrorCode.INVALID_STATE
        assert caught.value.request_id != 0
