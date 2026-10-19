"""Independent wire oracles and deterministic bounds for the public Python stack.

Reuse the frozen-vector patcher and raw command envelope builder; samples below
are packed from literal wire layouts, never the production sample encoders.
"""

import struct
from dataclasses import replace

import pytest
from test_protocol_v3_codecs import fixture, patch
from test_simulator_v3 import raw_request
from thingdone_daq import StreamGap
from thingdone_daq.models import analyze_stream_continuity
from thingdone_daq.models_v3 import V3Settings
from thingdone_daq.protocol_v2 import IncrementalCompatibleFrameParser
from thingdone_daq.protocol_v3 import (
    V3FrameParser,
    V3FrameValidationError,
    decode_data_payload,
    decode_v3_block,
    decode_v3_frame,
)


@pytest.mark.parametrize("encoding", [0, 2], ids=["raw", "pack12"])
@pytest.mark.parametrize("channel", [0, 1])
def test_all_adc_codes_in_each_lane_with_independent_other_channel(encoding, channel):
    for start in range(0, 4096, 1012):
        codes = range(start, min(start + 1012, 4096))
        pairs = [(code, 0xA5B) if channel == 0 else (0xA5B, code) for code in codes]
        raw = b"".join(struct.pack("<HH", a, b) for a, b in pairs)
        samples = (
            raw
            if encoding == 0
            else b"".join((a | b << 12).to_bytes(3, "little") for a, b in pairs)
        )
        payload = struct.pack("<BBHII", encoding, 4, 0, len(raw), 0) + samples
        wire = raw_request(
            kind=1, request_id=0, payload=payload, run=7, count=len(pairs), ticks=80
        )
        settings = replace(V3Settings.defaults(), adc_policy=int(encoding == 2))
        block = decode_v3_block(decode_v3_frame(wire), settings)
        assert block.payload == raw
        assert list(block.adc0) == [a for a, _ in pairs]
        assert list(block.adc1) == [b for _, b in pairs]
        assert block.first_sample_ticks == 80
        assert block.end_tick_exclusive == 80 + len(pairs) * 8
        assert block.adc1_phase_ticks == 4


@pytest.mark.parametrize("channel", [0, 1])
@pytest.mark.parametrize("nibble", range(1, 16))
def test_every_unused_raw_adc_high_nibble_is_rejected(channel, nibble):
    # PACK12 has no unused nibble: every bit belongs to one of the two channels.
    raw = bytearray.fromhex("bc0a2301")
    raw[channel * 2 + 1] |= nibble << 4
    payload = bytes.fromhex("000400000400000000000000") + raw
    with pytest.raises(V3FrameValidationError, match="ADC code"):
        decode_data_payload(1, payload, 1)


@pytest.mark.parametrize(
    "kind,width,encoding",
    [(1, 4, 0), (1, 4, 2), (2, 1, 0), (2, 1, 1), (2, 2, 0), (2, 2, 1)],
)
def test_maximum_valid_counts_bound_every_expansion(monkeypatch, kind, width, encoding):
    count = 4048 // width
    value = 0xA581 if width == 2 else 0x81
    if kind == 1:
        expected = bytes.fromhex("bc0a2301") * count
        samples = expected if encoding == 0 else bytes.fromhex("bc3a12") * count
    else:
        expected = value.to_bytes(width, "little") * count
        samples = (
            count.to_bytes(2, "little") + value.to_bytes(width, "little")
            if encoding == 1
            else expected
        )
    payload = (
        struct.pack("<BBHII", encoding, width, 0, 4048, int(encoding == 1)) + samples
    )
    allocations = []

    class BoundedExpansion(bytearray):
        def __init__(self, size=0):
            assert size <= 4048
            allocations.append(size)
            super().__init__(size)

        def extend(self, data):
            assert len(self) + len(data) <= 4048
            allocations.append(len(self) + len(data))
            super().extend(data)

    monkeypatch.setattr(
        "thingdone_daq.protocol_v3.bytearray", BoundedExpansion, raising=False
    )
    decoded = decode_data_payload(kind, payload, count)
    assert decoded.payload == expected
    assert decoded.decoded_bytes == 4048
    assert decoded.item_count == count
    assert decoded.encoded_sample_bytes == len(samples)
    if encoding:
        assert max(allocations) == 4048
    else:
        assert allocations == []
    allocations.clear()
    with pytest.raises(V3FrameValidationError):
        decode_data_payload(kind, payload, count + 1)
    assert allocations == []


@pytest.fixture
def forbid_decoded_allocation(monkeypatch):
    def forbidden_allocation(*args):
        pytest.fail("malformed samples allocated a decoded buffer")

    monkeypatch.setattr(
        "thingdone_daq.protocol_v3.bytearray", forbidden_allocation, raising=False
    )


@pytest.mark.parametrize("width", [1, 2])
@pytest.mark.parametrize(
    "lengths", [(0,), (7,), (9,), (65535,), (4, 5), (4, 3), (4, 0)]
)
def test_hostile_rle_validates_all_runs_before_any_expansion(
    forbid_decoded_allocation, width, lengths
):
    samples = b"".join(
        struct.pack("<H", length) + (i + 1).to_bytes(width, "little")
        for i, length in enumerate(lengths)
    )
    payload = struct.pack("<BBHII", 1, width, 0, 8 * width, len(lengths)) + samples

    with pytest.raises(V3FrameValidationError):
        decode_data_payload(2, payload, 8)


@pytest.mark.parametrize(
    "count,decoded", [(0, 0), (1013, 4052), (0xFFFFFFFF, 0xFFFFFFFC), (1, 0xFFFFFFFF)]
)
@pytest.mark.parametrize("samples", [b"\0\0", b"\0\0\0", b"\0\0\0\0"])
def test_hostile_pack12_lengths_reject_before_expansion(
    forbid_decoded_allocation, count, decoded, samples
):
    payload = struct.pack("<BBHII", 2, 4, 0, decoded, 0) + samples

    with pytest.raises(V3FrameValidationError):
        decode_data_payload(1, payload, count)


@pytest.mark.parametrize(
    "factory",
    [V3FrameParser, lambda: IncrementalCompatibleFrameParser(include_v3=True)],
)
def test_every_split_of_mixed_stream_control_and_encodings(factory):
    wires = [
        fixture(name)
        for name in (
            "gpio8-rle",
            "info-response",
            "adc-pack12",
            "gpio8-raw",
            "get_status-response",
            "adc-raw",
        )
    ]
    stream = b"".join(wires)
    for split in range(len(stream) + 1):
        parser = factory()
        frames = parser.feed(stream[:split]) + parser.feed(stream[split:])
        assert [f.to_bytes() for f in frames] == wires, split
        assert parser.counters.corruption_events == 0
        assert parser.buffered_bytes == 0
        assert parser.high_water_mark <= parser.max_buffered_bytes


@pytest.mark.parametrize(
    "name",
    ["adc-raw", "adc-pack12", "gpio8-raw", "gpio8-rle", "gpio16-raw", "gpio16-rle"],
)
@pytest.mark.parametrize("damage", ["checksum", "truncated"])
@pytest.mark.parametrize("chunk_size", [1, 17, 65536])
def test_corrupted_and_truncated_streams_keep_exact_loss_and_timestamps(
    name, damage, chunk_size
):
    base = decode_v3_frame(fixture(name))
    count = base.header.item_count
    wires = [
        raw_request(
            kind=base.header.kind,
            request_id=0,
            payload=base.payload,
            run=7,
            sequence=i,
            ticks=i * count * 8,
            count=count,
        )
        for i in range(3)
    ]
    damaged = (
        wires[1][:-2]
        if damage == "truncated"
        else wires[1][:-1] + bytes([wires[1][-1] ^ 0x80])
    )
    control = fixture("info-response")
    stream = wires[0] + damaged + control + wires[2]
    parser = IncrementalCompatibleFrameParser(include_v3=True)
    frames = []
    for offset in range(0, len(stream), chunk_size):
        frames.extend(parser.feed(stream[offset : offset + chunk_size]))
    assert [frame.to_bytes() for frame in frames] == [wires[0], control, wires[2]]
    assert parser.counters.checksum_errors == 1
    assert parser.counters.bytes_discarded == len(damaged)
    assert parser.counters.resynchronizations == 1
    assert parser.buffered_bytes == 0
    settings = replace(
        V3Settings.defaults(),
        adc_policy=int(name != "adc-raw"),
        gpio_width_bits=16 if "16" in name else 8,
        aux_bank_mode=int("16" in name),
    )
    first, following = [
        decode_v3_block(frame, settings) for frame in (frames[0], frames[2])
    ]
    gap = analyze_stream_continuity(
        following,
        expected_sequence=1,
        expected_first_sample_ticks=count * 8,
        active_run_id=7,
        previous_sequence=0,
    )
    assert isinstance(gap, StreamGap)
    assert gap.missing_frames == 1
    assert gap.missing_items == count
    assert gap.expected_first_sample_ticks == count * 8
    assert gap.observed_first_sample_ticks == count * 16
    assert gap.sequence_inferred_items is None
    assert not gap.firmware_reported and not gap.firmware_overrun
    assert gap.host_queue_drops == 0
    assert StreamGap.between(first, following).missing_items == count


@pytest.mark.parametrize("version", [0x82, 0x83])
@pytest.mark.parametrize(
    "factory",
    [V3FrameParser, lambda: IncrementalCompatibleFrameParser(include_v3=True)],
)
def test_hostile_private_versions_and_lengths_have_bounded_storage(factory, version):
    valid = fixture("adc-pack12")
    private = patch(valid, 4, bytes([version]))
    oversized = patch(valid, 12, b"\xff" * 8)
    parser = factory()
    hostile = (private + oversized + b"noise" * 10) * 1000
    assert parser.feed(hostile) == []
    assert parser.high_water_mark <= parser.max_buffered_bytes
    assert parser.buffered_bytes <= 3
    assert parser.counters.frames_decoded == 0
    assert parser.counters.header_errors == 2000
    assert [f.to_bytes() for f in parser.feed(valid)] == [valid]
    assert parser.counters.bytes_discarded == len(hostile)
    assert parser.buffered_bytes == 0


@pytest.mark.parametrize("name", ["adc-pack12", "gpio8-rle", "gpio16-rle"])
def test_terminal_truncation_waits_for_evidence_and_reset_discards_partial_epoch(name):
    wire = fixture(name)
    parser = IncrementalCompatibleFrameParser(include_v3=True)
    assert parser.feed(wire[:-1]) == []
    assert parser.buffered_bytes == len(wire) - 1
    assert parser.counters.corruption_events == 0
    assert parser.feed(b"") == []  # EOF alone cannot quantify unobserved loss.
    parser.reset_session()
    assert parser.buffered_bytes == 0
    fresh = patch(wire, 20, struct.pack("<I", 9))
    frames = parser.feed(fresh)
    assert len(frames) == 1 and frames[0].header.run_id == 9
    assert parser.counters.frames_decoded == 1
    assert parser.counters.corruption_events == 0
