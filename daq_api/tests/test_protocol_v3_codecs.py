"""Independent wire examples, malformed records and existing block-view checks."""

import random
import struct
import zlib
from dataclasses import replace
from itertools import pairwise
from pathlib import Path

import pytest
from thingdone_daq._generated import protocol_v3_constants as c
from thingdone_daq.models import ADCBlock, GPIOBlock
from thingdone_daq.models_v3 import (
    V3AppliedSettings,
    V3Capabilities,
    V3Clocks,
    V3Command,
    V3Info,
    V3Response,
    V3Settings,
    V3Status,
    V3Stop,
    decode_v3_response,
)
from thingdone_daq.protocol_v3 import (
    V3ChecksumMismatchError,
    V3FrameParser,
    V3FrameValidationError,
    decode_data_payload,
    decode_v3_block,
    decode_v3_frame,
    encode_adc_payload,
    encode_gpio_payload,
    encode_v3_frame,
)

FIXTURES = Path(__file__).resolve().parents[2] / "protocol/fixtures-v3"


def fixture(name: str) -> bytes:
    return (FIXTURES / f"{name}.bin").read_bytes()


def patch(wire: bytes, offset: int, data: bytes) -> bytes:
    changed = bytearray(wire)
    changed[offset : offset + len(data)] = data
    changed[-4:] = struct.pack("<I", zlib.adler32(changed[:-4]))
    return bytes(changed)


@pytest.mark.parametrize("path", sorted(FIXTURES.glob("*.bin")), ids=lambda p: p.stem)
def test_golden_frames_and_typed_controls(path: Path) -> None:
    wire = path.read_bytes()
    frame = decode_v3_frame(wire)
    assert frame.to_bytes() == wire
    if frame.header.kind >= 128:
        assert decode_v3_response(frame).to_bytes() == wire
    elif frame.header.kind >= 16:
        assert V3Command.from_frame(frame).to_bytes() == wire


@pytest.mark.parametrize("width", [8, 16])
@pytest.mark.parametrize("count", [1, 2, 3, 4, 32, 100, 2024])
def test_gpio_roundtrip_and_profitability(width: int, count: int) -> None:
    rng = random.Random(77)
    for values in (
        [0x12] * count,
        [i % 2 for i in range(count)],
        [rng.randrange(1 << width) for _ in range(count)],
    ):
        for policy in c.GpioPolicy:
            payload = encode_gpio_payload(values, width_bits=width, policy=policy)
            decoded = decode_data_payload(c.FrameKind.GPIO_DATA, payload, count)
            expected = b"".join(v.to_bytes(width // 8, "little") for v in values)
            assert decoded.payload == expected
            run_count = 1 + sum(a != b for a, b in pairwise(values))
            rle_size = run_count * (2 + width // 8)
            use_rle = policy == c.GpioPolicy.RLE_AUTO and rle_size < len(expected)
            assert decoded.encoding == (
                c.Encoding.GPIO_RLE if use_rle else c.Encoding.RAW
            )
            assert decoded.encoded_sample_bytes == (
                rle_size if use_rle else len(expected)
            )


@pytest.mark.parametrize(
    ("width", "values", "encoding", "wire"),
    [
        (8, [0x12] * 3, c.Encoding.RAW, "121212"),  # exact tie
        (16, [0x1234] * 2, c.Encoding.RAW, "34123412"),  # exact tie
        (8, [0x12] * 4 + [0x34] * 4, c.Encoding.GPIO_RLE, "040012040034"),
        (16, [0x1234] * 4 + [0xABCD] * 4, c.Encoding.GPIO_RLE, "040034120400cdab"),
    ],
)
def test_hand_derived_gpio(
    width: int, values: list[int], encoding: c.Encoding, wire: str
) -> None:
    payload = encode_gpio_payload(values, width_bits=width)
    assert payload[0] == encoding
    assert payload[12:] == bytes.fromhex(wire)


def test_hand_derived_adc_and_all_bit_positions() -> None:
    pairs = [(0, 4095), (0xABC, 0x123)]
    assert encode_adc_payload(pairs)[12:] == bytes.fromhex("00f0ffbc3a12")
    assert encode_adc_payload(pairs, policy=c.AdcPolicy.RAW)[12:] == bytes.fromhex(
        "0000ff0fbc0a2301"
    )
    pairs += [(1 << bit, 0) for bit in range(12)]
    pairs += [(0, 1 << bit) for bit in range(12)]
    pairs += [(4095, 4095), (0, 0)]
    rng = random.Random(109)
    pairs += [
        (rng.randrange(4096), rng.randrange(4096))
        for _ in range(c.MAX_ADC_PAIRS - len(pairs))
    ]
    raw = b"".join(struct.pack("<HH", *pair) for pair in pairs)
    for policy in c.AdcPolicy:
        encoded = encode_adc_payload(pairs, policy=policy)
        decoded = decode_data_payload(c.FrameKind.ADC_DATA, encoded, len(pairs))
        assert decoded.payload == raw
        assert decoded.decoded_bytes == 4048
        assert decoded.encoded_sample_bytes == (
            3036 if policy == c.AdcPolicy.PACK12 else 4048
        )


# Literal wire bytes keep each decoder assertion independent of the encoder.
# ADC0 occupies bits 0..11; ADC1 occupies bits 12..23 of the LE packed word.
@pytest.mark.parametrize(
    ("channel", "packed_words"),
    [
        (
            0,
            (
                "010000 020000 040000 080000 100000 200000 400000 800000 "
                "000100 000200 000400 000800"
            ),
        ),
        (
            1,
            (
                "001000 002000 004000 008000 000001 000002 000004 000008 "
                "000010 000020 000040 000080"
            ),
        ),
    ],
)
def test_pack12_walking_bits_against_literal_bytes(channel, packed_words):
    prefix = bytes.fromhex("020400000400000000000000")
    for bit, packed in enumerate(packed_words.split()):
        pair = (1 << bit, 0) if channel == 0 else (0, 1 << bit)
        expected = prefix + bytes.fromhex(packed)
        assert encode_adc_payload([pair]) == expected
        decoded = decode_data_payload(1, expected, 1)
        assert struct.unpack("<HH", decoded.payload) == pair


@pytest.mark.parametrize(
    ("pair", "packed"),
    [
        ((0, 0), "000000"),
        ((4095, 4095), "ffffff"),
        ((4095, 0), "ff0f00"),
        ((0, 4095), "00f0ff"),
        ((0xABC, 0x123), "bc3a12"),
        ((0x123, 0xABC), "23c1ab"),
        ((0x555, 0xAAA), "55a5aa"),
    ],
)
def test_pack12_boundaries_and_channel_order_from_literal_bytes(pair, packed):
    payload = bytes.fromhex("020400000400000000000000" + packed)
    assert encode_adc_payload([pair]) == payload
    assert struct.unpack("<HH", decode_data_payload(1, payload, 1).payload) == pair


@pytest.mark.parametrize(
    ("width", "values", "literal"),
    [
        # Two records cost six/eight bytes. Ties MUST select RAW; adding one
        # repeated item makes RLE profitable, including the 16-bit value lane.
        (8, [0x12] * 3 + [0x34] * 3, "000100000600000000000000121212343434"),
        (8, [0x12] * 3 + [0x34] * 4, "010100000700000002000000030012040034"),
        (16, [0x1234] * 2 + [0xABCD] * 2, "00020000080000000000000034123412cdabcdab"),
        (16, [0x1234] * 2 + [0xABCD] * 3, "010200000a00000002000000020034120300cdab"),
    ],
)
def test_multirun_profitability_boundary_from_literal_bytes(width, values, literal):
    payload = bytes.fromhex(literal)
    assert encode_gpio_payload(values, width_bits=width) == payload
    decoded = decode_data_payload(2, payload, len(values))
    assert decoded.payload == b"".join(
        value.to_bytes(width // 8, "little") for value in values
    )


@pytest.mark.parametrize("path", sorted(FIXTURES.glob("*.bin")), ids=lambda p: p.stem)
def test_every_golden_frame_at_every_transport_split(path):
    wire = path.read_bytes()
    for split in range(1, len(wire)):
        parser = V3FrameParser()
        assert parser.feed(wire[:split]) == [], (path.name, split)
        frames = parser.feed(wire[split:])
        assert len(frames) == 1, (path.name, split)
        assert frames[0].to_bytes() == wire
        assert parser.buffered_bytes == 0


@pytest.mark.parametrize("offset", range(8, 36, 4))
@pytest.mark.parametrize("value", [0, 0xFFFFFFFF])
def test_each_capability_limit_rejects_zero_and_unbounded_values(offset, value):
    payload = bytearray(fixture("get_capabilities-response")[44:-4])
    struct.pack_into("<I", payload, offset, value)
    with pytest.raises(V3FrameValidationError):
        V3Capabilities.from_payload(payload)


@pytest.mark.parametrize("value", [-1, 4096, 65535, 1 << 100, True, 1.5])
@pytest.mark.parametrize("policy", list(c.AdcPolicy))
def test_adc_never_masks_invalid_codes(value: int, policy: c.AdcPolicy) -> None:
    for pair in ((value, 0), (0, value)):
        with pytest.raises(V3FrameValidationError):
            encode_adc_payload([pair], policy=policy)


@pytest.mark.parametrize(
    ("kind", "width", "count", "encoding", "runs", "samples"),
    [
        (1, 4, 1, 0, 0, "00100000"),  # RAW ADC >4095
        (1, 4, 1, 0, 0, "0000ffff"),
        (1, 4, 1, 1, 1, "010000000000"),  # GPIO encoding on ADC
        (2, 1, 8, 2, 0, "000000"),  # ADC encoding on GPIO
        (1, 4, 1, 2, 1, "000000"),  # PACK12 run count
        (1, 4, 1, 2, 0, "0000"),  # truncated packed pair
        (1, 4, 1, 2, 0, "00000000"),  # extra byte
        (2, 1, 8, 1, 1, "000012"),  # zero run
        (2, 1, 8, 1, 1, "ffff12"),  # overflowing run
        (2, 1, 8, 1, 2, "040012050034"),  # cumulative overflow
        (2, 1, 8, 1, 1, "070012"),  # insufficient coverage
        (2, 1, 8, 1, 2, "040012040012"),  # nonmaximal adjacent runs
        (2, 1, 8, 1, 2, "04001204"),  # truncated record
        (2, 1, 3, 1, 1, "030012"),  # tie must be RAW
        (2, 2, 2, 1, 1, "02003412"),  # 16-bit tie
        (2, 2, 8, 1, 1, "080034"),  # truncated u16 value
        (2, 1, 8, 1, 0, "080012"),  # zero records
        (2, 1, 8, 1, 9, "080012"),  # too many records
        (2, 1, 1, 0, 1, "12"),  # RAW run count
        (2, 1, 1, 3, 0, "12"),  # unknown encoding
        (2, 4, 1, 0, 0, "00000000"),  # wrong GPIO width
        (1, 2, 1, 0, 0, "0000"),  # wrong ADC width
    ],
)
def test_malformed_sample_payload(
    kind: int, width: int, count: int, encoding: int, runs: int, samples: str
) -> None:
    payload = struct.pack(
        "<BBHII", encoding, width, 0, count * width, runs
    ) + bytes.fromhex(samples)
    with pytest.raises(V3FrameValidationError):
        decode_data_payload(kind, payload, count)


@pytest.mark.parametrize("count", [0, -1, 1013, 2**32 - 1])
def test_adc_count_bound_precedes_expansion(count: int) -> None:
    with pytest.raises(V3FrameValidationError):
        decode_data_payload(c.FrameKind.ADC_DATA, encode_adc_payload([(0, 0)]), count)


@pytest.mark.parametrize(
    ("name", "offset", "data"),
    [
        ("adc-pack12", 4, b"\x83"),
        ("adc-pack12", 5, b"\xff"),
        ("adc-pack12", 6, b"\x10\0"),
        ("adc-pack12", 6, b"\x08\0"),
        ("adc-pack12", 8, b"\x30\0"),
        ("adc-pack12", 10, b"\x02"),
        ("adc-pack12", 11, b"\x01"),
        ("adc-pack12", 12, b"\xff\xff\xff\xff"),
        ("adc-pack12", 20, bytes(4)),
        ("adc-pack12", 28, b"\x01\0\0\0"),
        ("adc-pack12", 32, b"\x01"),
        ("adc-pack12", 32, struct.pack("<Q", 2**64 - 8)),
        ("adc-pack12", 40, b"\xff\xff\xff\xff"),
        ("adc-pack12", 46, b"\x01"),
        ("adc-pack12", 48, b"\xff\xff\xff\xff"),
        ("info-request", 28, bytes(4)),
        ("info-request", 20, b"\x01"),
        ("info-response", 24, b"\x01"),
        ("info-response", 44, b"\x01"),
        ("info-response", 45, b"\x01"),
        ("info-response", 46, b"\x01"),
        ("info-response", 52, b"\x02"),
        ("info-response", 55, b"\x01"),
        ("info-response", 56, b"X"),  # simulated serial without SIM-
        ("info-response", 56, b"\xff"),
        ("info-response", 56, b"A" * 32),  # unterminated
        ("info-response", 87, b"A"),  # nonzero padding
        ("start-response", 20, bytes(4)),
        ("get_status-response", 52, b"\x02"),  # payload run differs
        ("get_status-response", 56, b"\x01"),  # STOPPED with queue
        ("get_status-response", 68, b"\x01"),  # drops > produced
        ("stop-response", 48, b"\x03"),  # RUNNING
        ("unknown-command-error", 49, b"\x01"),
    ],
)
def test_checksumming_does_not_legitimize_bad_fields(
    name: str, offset: int, data: bytes
) -> None:
    with pytest.raises(V3FrameValidationError):
        decode_v3_frame(patch(fixture(name), offset, data))


@pytest.mark.parametrize(
    ("offset", "data"),
    [
        (4, b"\0"),
        (4, b"\x03"),
        (5, b"\x02"),
        (6, b"\0"),
        (6, b"\x41"),
        (7, b"\x01"),
        (8, struct.pack("<I", 0xFFFFFFFF)),
        (56, b"\x03"),
        (57, b"\x01"),
        (60, struct.pack("<I", 528000000)),
        (80, c.CPU_PROFILES[0]),  # duplicate CPU ID
        (104, b"\x01"),
        (124, bytes(20)),
        (124 + 20, c.SELECTABLE_CONFIGURATIONS[0]),  # duplicate tuple
        (124 + 60 * 20, b"\x01"),  # unused slot
    ],
)
def test_capability_table_bounds_and_consistency(offset: int, data: bytes) -> None:
    payload = bytearray(fixture("get_capabilities-response")[44:-4])
    payload[offset : offset + len(data)] = data
    with pytest.raises(V3FrameValidationError):
        V3Capabilities.from_payload(payload)


def test_selectability_is_exact_advertised_membership() -> None:
    all_caps = V3Capabilities.canonical()
    assert len(all_caps.configurations) == 60
    assert all_caps.to_payload() == fixture("get_capabilities-response")[44:-4]
    subset = replace(all_caps, configurations=(all_caps.defaults,))
    assert V3Capabilities.from_payload(subset.to_payload()) == subset
    subset.require_supported(subset.defaults)
    raw450 = replace(
        subset.defaults,
        cpu_profile=c.CpuProfile.CPU_450MHZ,
        adc_policy=c.AdcPolicy.RAW,
        gpio_policy=c.GpioPolicy.RAW,
    )
    all_caps.require_supported(raw450)
    with pytest.raises(V3FrameValidationError, match="not advertised"):
        subset.require_supported(raw450)
    with pytest.raises(V3FrameValidationError):
        replace(subset, cpu_profiles=(all_caps.cpu_profiles[1],)).to_payload()
    with pytest.raises(V3FrameValidationError):
        replace(subset, configurations=(raw450,)).to_payload()


@pytest.mark.parametrize(
    ("field", "value", "error"),
    [
        ("source", 9, c.ErrorCode.INVALID_PAYLOAD),
        ("stream_mask", 4, c.ErrorCode.INVALID_PAYLOAD),
        ("cpu_profile", 3, c.ErrorCode.INVALID_PAYLOAD),
        ("gpio_width_bits", 16, c.ErrorCode.UNSUPPORTED_CONFIGURATION),
        ("cpu_profile", c.CpuProfile.CPU_450MHZ, c.ErrorCode.UNSUPPORTED_CONFIGURATION),
        ("adc_pair_rate_hz", 2000000, c.ErrorCode.UNSUPPORTED_CONFIGURATION),
    ],
)
def test_settings_reject_unknown_and_contradictory_fields(
    field: str, value: int, error: c.ErrorCode
) -> None:
    with pytest.raises(V3FrameValidationError) as caught:
        replace(V3Settings.defaults(), **{field: value})
    assert caught.value.error_code == error


def test_response_correlation_and_exact_applied_echo() -> None:
    settings = V3Settings.defaults()
    request = V3Command(c.CommandKind.CONFIGURE, 91, settings)
    response = V3Response(
        c.FrameKind.CONFIGURE_RESPONSE,
        91,
        0,
        c.ResponseStatus.OK,
        c.ErrorCode.OK,
        V3AppliedSettings(settings, V3Clocks.for_profile(settings.cpu_profile)),
    )
    decoded = decode_v3_response(decode_v3_frame(response.to_bytes()))
    decoded.validate_for(request)
    with pytest.raises(V3FrameValidationError):
        replace(decoded, request_id=90).validate_for(request)
    with pytest.raises(V3FrameValidationError):
        replace(decoded, kind=c.FrameKind.START_RESPONSE).validate_for(request)
    with pytest.raises(V3FrameValidationError):
        decoded.validate_for(
            replace(request, settings=replace(settings, adc_policy=c.AdcPolicy.RAW))
        )
    with pytest.raises(V3FrameValidationError):
        V3AppliedSettings(
            settings, V3Clocks.for_profile(c.CpuProfile.CPU_450MHZ)
        ).to_payload()
    error = V3Response(
        c.FrameKind.INFO_RESPONSE,
        0,
        0,
        c.ResponseStatus.ERROR,
        c.ErrorCode.INVALID_REQUEST_ID,
    )
    assert decode_v3_response(decode_v3_frame(error.to_bytes())) == error
    with pytest.raises(V3FrameValidationError):
        replace(error, error_code=c.ErrorCode.INVALID_STATE).to_bytes()


@pytest.mark.parametrize(
    "name",
    ["adc-raw", "adc-pack12", "gpio8-raw", "gpio8-rle", "gpio16-raw", "gpio16-rle"],
)
def test_existing_block_access_and_byte_accounting(name: str) -> None:
    frame = decode_v3_frame(fixture(name))
    settings = replace(
        V3Settings.defaults(),
        adc_policy=c.AdcPolicy.RAW if name == "adc-raw" else c.AdcPolicy.PACK12,
        aux_bank_mode=c.AuxBankMode.INPUT if "16" in name else c.AuxBankMode.DISABLED,
        gpio_width_bits=16 if "16" in name else 8,
    )
    block = decode_v3_block(frame, settings)
    assert block.protocol_version == 3
    assert block.item_count == frame.header.item_count
    assert block.decoded_bytes == len(block.payload)
    assert block.encoded_payload == frame.payload
    assert block.encoded_sample_bytes == len(frame.payload) - 12
    assert block.wire_bytes == len(fixture(name))
    assert block.frame_coverage_ticks == block.item_count * 8
    if isinstance(block, ADCBlock):
        assert tuple(block.adc0) == (0, 0xABC)
        assert tuple(block.adc1) == (4095, 0x123)
        assert block.adc1_phase_ticks == 4
    else:
        assert isinstance(block, GPIOBlock)
        expected = (
            [0x1234] * 4 + [0xABCD] * 4
            if "16-rle" in name
            else [0x12] * 4 + [0x34] * 4
            if "rle" in name
            else [0, (1 << settings.gpio_width_bits) - 1] * 2
        )
        assert [block.sample(i) for i in range(block.item_count)] == expected
        assert block.sample(-1) == expected[-1]
        assert block.sample_ticks(-1) == 8 * (block.item_count - 1)
        assert tuple(block.channel(6)) == tuple(bool(v & 1) for v in expected)
        if settings.gpio_width_bits == 16:
            assert tuple(block.channel(16)) == tuple(bool(v & 256) for v in expected)
        with pytest.raises(IndexError):
            block.sample(block.item_count)


def test_data_policy_source_width_and_stream_validation() -> None:
    defaults = V3Settings.defaults()
    invalid = [
        ("adc-raw", defaults),
        ("adc-pack12", replace(defaults, adc_policy=c.AdcPolicy.RAW)),
        ("gpio8-rle", replace(defaults, gpio_policy=c.GpioPolicy.RAW)),
        ("gpio16-raw", defaults),
        ("gpio8-raw", replace(defaults, stream_mask=c.StreamMask.ADC)),
        ("adc-pack12", replace(defaults, source=c.Source.SYNTHETIC)),
    ]
    for name, settings in invalid:
        with pytest.raises(V3FrameValidationError):
            decode_v3_block(decode_v3_frame(fixture(name)), settings)


def test_parser_chunks_corruption_and_bounded_storage() -> None:
    valid = fixture("adc-pack12")
    bad_checksum = bytearray(valid)
    bad_checksum[-1] ^= 1
    bad_payload = patch(valid, 46, b"\x01")
    oversized = patch(valid, 12, b"\xff" * 4)
    wire = b"noise" * 5000 + oversized + bad_payload + bad_checksum + valid
    for chunk_size in (1, 7, 44, 4108, len(wire)):
        parser = V3FrameParser()
        frames = []
        for offset in range(0, len(wire), chunk_size):
            frames.extend(parser.feed(wire[offset : offset + chunk_size]))
        assert [frame.to_bytes() for frame in frames] == [valid]
        assert parser.counters.header_errors == 1
        assert parser.counters.payload_errors == 1
        assert parser.counters.checksum_errors == 1
        assert parser.high_water_mark <= c.MAX_DATA_FRAME_BYTES + 3
        assert parser.buffered_bytes == 0
    with pytest.raises(V3ChecksumMismatchError):
        decode_v3_frame(bad_checksum)
    for length in range(len(valid)):
        with pytest.raises(V3FrameValidationError):
            decode_v3_frame(valid[:length])
    with pytest.raises(V3FrameValidationError):
        decode_v3_frame(valid + b"x")
    parser = V3FrameParser()
    assert parser.feed(valid[:-1]) == []
    assert parser.feed(valid[-1:])[0].to_bytes() == valid
    parser.reset()
    assert parser.counters.frames_decoded == 0


def test_maximum_gpio_frames_and_input_bounds() -> None:
    for width in (8, 16):
        values = [0] * (4048 // (width // 8))
        for policy in c.GpioPolicy:
            payload = encode_gpio_payload(values, width_bits=width, policy=policy)
            frame = encode_v3_frame(
                c.FrameKind.GPIO_DATA, payload, run_id=1, item_count=len(values)
            )
            assert len(frame) <= c.MAX_DATA_FRAME_BYTES
            assert decode_data_payload(
                2, decode_v3_frame(frame).payload, len(values)
            ).payload == bytes(4048)
        with pytest.raises(V3FrameValidationError):
            encode_gpio_payload(values + [0], width_bits=width)
        with pytest.raises(V3FrameValidationError):
            encode_gpio_payload([1 << width], width_bits=width)
    with pytest.raises(V3FrameValidationError):
        encode_adc_payload([(0, 0)] * 1013)
    with pytest.raises(V3FrameValidationError):
        encode_adc_payload([])
    with pytest.raises(V3FrameValidationError):
        encode_gpio_payload([])
    with pytest.raises(V3FrameValidationError):
        decode_data_payload(2, bytes(100000), 1)


def test_state_and_info_models_reject_contradictions() -> None:
    info = V3Info.from_payload(fixture("info-response")[44:-4])
    with pytest.raises(V3FrameValidationError):
        replace(info, build_id="bad\n").to_payload()
    for state in (
        V3Stop(c.DeviceState.DRAINING, 1, 0),
        V3Stop(c.DeviceState.RUNNING, 0, 0),
        V3Status(c.DeviceState.STOPPED, 1, 0, adc_items_dropped=1),
    ):
        with pytest.raises(V3FrameValidationError):
            state.to_payload()


def test_build_specific_capabilities_preserve_limits_and_defaults() -> None:
    canonical = V3Capabilities.canonical()
    defaults = replace(
        canonical.defaults,
        cpu_profile=c.CpuProfile.CPU_450MHZ,
        gpio_policy=c.GpioPolicy.RAW,
        adc_policy=c.AdcPolicy.RAW,
    )
    caps = replace(
        canonical,
        defaults=defaults,
        cpu_profiles=(canonical.cpu_profiles[1],),
        configurations=(defaults,),
        max_data_frame_bytes=4096,
        max_control_frame_bytes=1536,
        max_logical_payload_bytes=4036,
        max_encoded_sample_bytes=4036,
        max_adc_pairs=1009,
        max_gpio8_samples=4036,
        max_gpio16_samples=2018,
    )
    assert V3Capabilities.from_payload(caps.to_payload()) == caps
    caps.require_supported(defaults)
    for field, value in (
        ("max_data_frame_bytes", 4095),
        ("max_control_frame_bytes", 1451),
        ("max_logical_payload_bytes", 4035),
    ):
        with pytest.raises(V3FrameValidationError):
            replace(caps, **{field: value}).to_payload()
