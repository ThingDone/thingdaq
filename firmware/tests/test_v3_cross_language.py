"""Python commands -> actual C++ control/USB -> public SDK frames and blocks."""

from __future__ import annotations

import struct
import subprocess
from dataclasses import replace
from itertools import cycle, groupby

import pytest
from test_firmware_runtime import COMPILE_SOURCES, FIRMWARE_SOURCE, REPOSITORY_ROOT
from test_v3_control_contract import command
from thingdone_daq import ADCBlock, DAQConfiguration, GPIOBlock, reconcile_run_counters
from thingdone_daq._generated import protocol_v3_constants as c
from thingdone_daq.models import decode_message, decode_response
from thingdone_daq.models_v3 import V3Settings, decode_v3_response
from thingdone_daq.protocol_v2 import (
    IncrementalCompatibleFrameParser,
    encode_v2_frame,
)
from thingdone_daq.protocol_v3 import decode_v3_block

FIXTURES = REPOSITORY_ROOT / "protocol/fixtures-v3"


@pytest.fixture(scope="module", params=[450, 600], ids=["historical-450", "normal-600"])
def cpp(request, tmp_path_factory):
    binary = tmp_path_factory.mktemp("v3-cross-language") / "session"
    subprocess.run(
        [
            "g++",
            "-std=c++17",
            "-O2",
            "-Wall",
            "-Wextra",
            "-Werror",
            "-Wconversion",
            "-Wsign-conversion",
            "-pedantic",
            "-fno-exceptions",
            "-fno-rtti",
            "-DTHINGDAQ_RELEASE_FIXED_1MHZ=1",
            f"-DTHINGDAQ_EXPERIMENT_CPU_HZ={request.param}000000U",
            f"-I{FIRMWARE_SOURCE}",
            str(REPOSITORY_ROOT / "firmware/tests/v3_cross_language_test.cpp"),
            *(str(path) for path in COMPILE_SOURCES),
            "-o",
            str(binary),
        ],
        capture_output=True,
        text=True,
        check=True,
    )
    return binary, request.param


def exchange(cpp, operations, *, mode="runtime", chunks=(1, 2, 7, 43, 3, 4091, 5)):
    result = subprocess.run(
        [str(cpp[0]), mode],
        input=("\n".join(operations) + "\n").encode(),
        check=True,
        capture_output=True,
        timeout=30,
    )
    parser = IncrementalCompatibleFrameParser(include_v3=True)
    frames, at = [], 0
    for size in cycle(chunks):
        frames.extend(parser.feed(result.stdout[at : at + size]))
        at += size
        if at >= len(result.stdout):
            break
    assert (
        parser.checksum_errors == parser.bytes_discarded == parser.buffered_bytes == 0
    )
    assert sum(f.header.total_length for f in frames) == len(result.stdout)
    return frames, result.stdout


def request(wire):
    return "C " + wire.hex()


def replies(frames):
    return {
        f.header.request_id: (
            decode_v3_response(f) if f.header.version == 3 else decode_response(f)
        )
        for f in frames
        if f.header.kind not in (1, 2)
    }


def capabilities(cpp):
    frames, _ = exchange(
        cpp, [request((FIXTURES / "get_capabilities-request.bin").read_bytes())]
    )
    return decode_v3_response(frames[0]).value


def test_fixed_clock_settings_lifecycle(cpp):
    caps = capabilities(cpp)
    clocks = caps.cpu_profiles[0]
    assert len(caps.cpu_profiles) == 1
    assert clocks.cpu_clock_hz == cpp[1] * 1_000_000
    assert clocks.ipg_clock_hz == 150_000_000 and clocks.pit_clock_hz == 24_000_000
    assert clocks.adc_clock_hz == 37_500_000 and clocks.timestamp_hz == 8_000_000
    assert len(caps.configurations) == (48 if cpp[1] == 600 else 12)
    assert all(s.cpu_profile == clocks.cpu_profile for s in caps.configurations)
    raw = replace(caps.defaults, source=1, gpio_policy=0, adc_policy=0)
    selected = [raw, replace(caps.defaults, source=1), raw]
    operations = [
        request(command(16, request_id=1)),
        request(command(29, request_id=2)),
    ]
    for run, settings in enumerate(selected, 1):
        base = run * 20
        operations += [
            request(command(17, settings.to_bytes(), base)),
            request(command(17, settings.to_bytes(), base + 1)),  # idempotent
            request(command(29, request_id=base + 2)),
            request(command(18, request_id=base + 3)),
            request(command(17, raw.to_bytes(), base + 4)),  # running
            request(encode_v2_frame(16, request_id=base + 5)),  # legacy probe
            request(command(29, request_id=base + 6)),
            "T 32256",
            request(command(20, request_id=base + 7)),
            request(command(19, request_id=base + 8)),
            request(command(16, request_id=base + 9)),
            request(encode_v2_frame(16, request_id=base + 10)),
            request(command(29, request_id=base + 11)),
        ]
    frames, _ = exchange(cpp, operations)
    responses = replies(frames)
    assert len(responses) == 2 + 12 * len(selected)
    assert responses[1].value.clocks == responses[2].value.clocks == clocks
    assert responses[2].value.settings == caps.defaults
    for run, settings in enumerate(selected, 1):
        base = run * 20
        for offset in (0, 1, 2, 3, 6, 11):
            response = responses[base + offset]
            assert response.error_code == c.ErrorCode.OK
            assert response.value.settings == settings
            assert response.value.clocks == clocks
            assert response.run_id == (run - 1 if offset < 3 else run)
        assert responses[base + 4].error_code == c.ErrorCode.INVALID_STATE
        assert responses[base + 5].error_code == c.ErrorCode.UNSUPPORTED_CONFIGURATION
        for offset in (7, 8, 9, 10):
            assert responses[base + offset].error_code == c.ErrorCode.OK
        assert responses[base + 8].value.state == c.DeviceState.STOPPED
        assert responses[base + 8].value.pending_frames == 0
        assert responses[base + 9].value.clocks == clocks
        data = [f for f in frames if f.header.run_id == run and f.header.kind in (1, 2)]
        assert data
        for frame in data:
            assert_samples(decode_v3_block(frame, settings))
        for kind in (1, 2):
            first = next(f for f in data if f.header.kind == kind)
            assert first.header.sequence == first.header.first_sample_ticks == 0

    # A newly constructed runtime models boot, rather than a host reconnect.
    frames, _ = exchange(
        cpp, [request(command(k, request_id=i)) for i, k in enumerate((16, 28, 29), 1)]
    )
    boot = replies(frames)
    assert all(r.run_id == 0 and r.error_code == 0 for r in boot.values())
    assert boot[1].value.clocks == boot[3].value.clocks == clocks
    assert boot[2].value.defaults == boot[3].value.settings == caps.defaults


def test_unsupported_settings_preserve_fixed_clock_state(cpp):
    caps = capabilities(cpp)
    raw = replace(caps.defaults, source=1, gpio_policy=0, adc_policy=0)
    other_cpu = c.CpuProfile.CPU_450MHZ if cpp[1] == 600 else c.CpuProfile.CPU_600MHZ
    # Known enums with unsupported membership/rates, plus an unknown CPU ID.
    candidates = [
        (
            replace(raw, cpu_profile=other_cpu).to_bytes(),
            c.ErrorCode.UNSUPPORTED_CONFIGURATION,
        ),
        (
            raw.to_bytes()[:16] + struct.pack("<I", 2_000_000),
            c.ErrorCode.UNSUPPORTED_CONFIGURATION,
        ),
        (
            raw.to_bytes()[:12] + struct.pack("<I", 2_000_000) + raw.to_bytes()[16:],
            c.ErrorCode.UNSUPPORTED_CONFIGURATION,
        ),
        (
            raw.to_bytes()[:4] + b"\x03" + raw.to_bytes()[5:],
            c.ErrorCode.INVALID_PAYLOAD,
        ),
    ]
    operations = [request(command(17, raw.to_bytes(), 1))]
    for i, (payload, _) in enumerate(candidates):
        base = 10 + i * 3
        operations += [
            request(command(17, payload, base)),
            request(command(29, request_id=base + 1)),
            request(command(16, request_id=base + 2)),
        ]
    frames, _ = exchange(cpp, operations)
    responses = replies(frames)
    assert len(responses) == 1 + 3 * len(candidates)
    for i, (_, error) in enumerate(candidates):
        base = 10 + i * 3
        assert responses[base].error_code == error
        assert responses[base + 1].value == responses[1].value
        assert responses[base + 2].value.clocks == caps.cpu_profiles[0]
    assert all(r.run_id == 0 for r in responses.values())


def test_stop_drain_rejects_configuration_then_starts_new_epoch(cpp):
    caps = capabilities(cpp)
    original = replace(caps.defaults, source=1)
    raw = replace(
        original, gpio_policy=0, adc_policy=0, gpio_width_bits=16, aux_bank_mode=1
    )
    frames, _ = exchange(
        cpp,
        [
            request(command(17, original.to_bytes(), 1)),
            request(command(18, request_id=2)),
            "A 32256",  # service until old DATA is partially sent
            "Q " + command(20, request_id=3).hex(),
            "Q " + command(17, raw.to_bytes(), 4).hex(),
            "Q " + command(19, request_id=5).hex(),
            "Q " + command(29, request_id=6).hex(),
            "T 0",  # process queued requests, then finish draining USB
            request(command(19, request_id=7)),
            request(command(17, raw.to_bytes(), 8)),
            request(command(18, request_id=9)),
            "T 32256",
            request(command(20, request_id=10)),
        ],
    )
    responses = replies(frames)
    assert len(responses) == 10
    assert responses[4].error_code == c.ErrorCode.BUSY
    assert all(r.error_code == 0 for key, r in responses.items() if key != 4)
    assert responses[5].value.state == c.DeviceState.DRAINING
    assert responses[5].value.pending_frames > 0
    assert responses[6].value == responses[1].value
    assert responses[7].value.state == c.DeviceState.STOPPED
    assert responses[7].value.pending_frames == 0
    assert responses[8].value == responses[9].value
    assert responses[9].value.settings == raw
    assert responses[9].value.clocks == caps.cpu_profiles[0]
    assert responses[2].run_id == responses[6].run_id == 1
    assert responses[9].run_id == 2
    for run, settings in ((1, original), (2, raw)):
        data = [f for f in frames if f.header.run_id == run and f.header.kind in (1, 2)]
        assert data
        for frame in data:
            assert_samples(decode_v3_block(frame, settings))


def assert_samples(block, *, controlled=False):
    first = block.first_sample_ticks // 8
    assert block.end_tick_exclusive == block.first_sample_ticks + block.item_count * 8
    if isinstance(block, ADCBlock):
        edges = [(0, 4095), (4095, 0), (0x123, 0xABC), (0x800, 0x7FF)]
        pairs = [
            edges[i % 4]
            if controlled
            else ((2 * (first + i)) % 4096, (2 * (first + i) + 1) % 4096)
            for i in range(block.item_count)
        ]
        assert list(block.adc0) == [p[0] for p in pairs]
        assert list(block.adc1) == [p[1] for p in pairs]
        assert [block.pair_ticks(i) for i in range(block.item_count)] == [
            ((first + i) * 8, (first + i) * 8 + 4) for i in range(block.item_count)
        ]
    else:
        assert isinstance(block, GPIOBlock)
        width = block.item_bytes
        pattern = block.sequence % 4
        span = [12, 1, 3 if width == 1 else 2, 6][pattern]
        expected = [
            (i // span + (0xAB00 if width == 2 else 0))
            if controlled
            else (first + i) % (1 << (width * 8))
            for i in range(block.item_count)
        ]
        assert [block.sample(i) for i in range(block.item_count)] == expected
        assert [block.sample_ticks(i) for i in range(block.item_count)] == [
            (first + i) * 8 for i in range(block.item_count)
        ]


def test_generated_golden_control_bytes(cpp):
    # These fixtures can go through the full runtime without starting hardware.
    names = ["info", "get_capabilities", "get_settings", "configure"]
    frames, wire = exchange(
        cpp,
        [request((FIXTURES / f"{name}-request.bin").read_bytes()) for name in names],
        chunks=(1,),
    )
    responses = replies(frames)
    assert len(responses) == 4
    assert all(r.error_code == 0 for r in responses.values() if r.request_id != 2)
    if cpp[1] == 600:
        # Identity-dependent INFO and build-specific capabilities are deliberately
        # not copied from simulator fixtures; applied clocks/settings are exact.
        assert wire.endswith((FIXTURES / "configure-response.bin").read_bytes())
        # Golden START/STOP exercise actual control transitions with no claim
        # that the controlled-producer seam constitutes hardware evidence.
        names = ["configure", "get_settings", "start", "get_status", "stop"]
        golden, output = exchange(
            cpp,
            [
                request((FIXTURES / f"{name}-request.bin").read_bytes())
                for name in names
            ],
            mode="codec",
        )
        offset = 0
        for name, frame in zip(names, golden, strict=True):
            observed = output[offset : offset + frame.header.total_length]
            offset += frame.header.total_length
            if name != "get_status":
                assert observed == (FIXTURES / f"{name}-response.bin").read_bytes()
            else:
                status = decode_v3_response(frame).value
                assert (
                    status.state == 3
                    and status.adc_items_produced == status.gpio_items_produced == 0
                )
    else:
        assert responses[2].error_code == 8  # unsupported fixed-clock tuple


@pytest.mark.parametrize("chunks", [(1,), (1, 2, 7, 43, 3, 4091, 5)])
def test_all_advertised_synthetic_tuples_and_v2_sessions(cpp, chunks):
    caps = capabilities(cpp)
    selected = [s for s in caps.configurations if s.source == 1]
    assert len(selected) == (24 if cpp[1] == 600 else 6)
    # Every advertised width/policy/stream-mask combination, then legacy RAW,
    # then public v3 again in the SAME runtime process.
    legacy = [DAQConfiguration(3, 1, aux_bank_mode=w, rate_profile=4) for w in (0, 1)]
    sessions = [*selected, *legacy, selected[-1]]
    operations, records = [], []
    next_id = 100
    for settings in sessions:
        version = 3 if isinstance(settings, V3Settings) else 2
        encode = command if version == 3 else encode_v2_frame

        def send(kind, payload=b"", encode=encode):
            nonlocal next_id
            next_id += 1
            operations.append(request(encode(kind, payload, request_id=next_id)))
            return next_id

        configure = send(
            17,
            settings.to_bytes()
            if version == 3
            else settings.to_payload(protocol_version=2),
        )
        start = send(18)
        operations.append("T 32256" if version == 3 else "T 32384")
        info = send(16)
        readback = send(29) if version == 3 else None
        operations.append("T 32256" if version == 3 else "T 32384")
        send(20)
        status = send(19)
        records.append((settings, configure, start, info, readback, status))
    frames, _ = exchange(cpp, operations, chunks=chunks)
    responses = replies(frames)
    assert len(responses) == next_id - 100
    assert all(r.error_code == 0 for r in responses.values()), responses
    for run, (
        settings,
        config_id,
        start_id,
        info_id,
        readback_id,
        status_id,
    ) in enumerate(records, 1):
        version = 3 if isinstance(settings, V3Settings) else 2
        assert responses[start_id].run_id == responses[info_id].run_id == run
        if version == 3:
            assert responses[config_id].value == responses[readback_id].value
            assert responses[config_id].value.settings == settings
            assert responses[config_id].value.clocks == caps.cpu_profiles[0]
        else:
            assert responses[config_id].value == settings
        status = responses[status_id].value
        if version == 3:
            assert status.state == 1 and status.pending_frames == 0
            assert reconcile_run_counters(status).exact
        for kind, name in [(1, "adc"), (2, "gpio")]:
            data = [
                f for f in frames if f.header.run_id == run and f.header.kind == kind
            ]
            width = (
                settings.gpio_width_bits
                if version == 3
                else (16 if settings.aux_bank_mode else 8)
            )
            count = (
                (1008 if kind == 1 else 4032 // (width // 8))
                if version == 3
                else (
                    (1012 if width == 8 else 506) if kind == 1 else 4048 // (width // 8)
                )
            )
            expected_frames = (
                ((8064 if version == 3 else 8096) // count)
                if int(settings.stream_mask) & kind
                else 0
            )
            assert len(data) == expected_frames
            total = 0
            for sequence, frame in enumerate(data):
                assert frame.header.version == version
                assert frame.header.sequence == sequence
                assert frame.header.item_count == count
                assert frame.header.first_sample_ticks == sequence * count * 8
                block = (
                    decode_v3_block(frame, settings)
                    if version == 3
                    else decode_message(frame, configuration=settings)
                )
                assert_samples(block)
                compressed_adc = version == 3 and kind == 1 and settings.adc_policy == 1
                assert block.encoding == (2 if compressed_adc else 0)
                expected_wire = (60 if version == 3 else 48) + count * (
                    3 if compressed_adc else 4 if kind == 1 else width // 8
                )
                assert block.wire_bytes == frame.header.total_length == expected_wire
                total += expected_wire
            assert getattr(status, f"{name}_items_dropped") == 0
            assert getattr(status, f"{name}_frames_dropped") == 0
            if version == 3:
                assert getattr(status, f"{name}_wire_bytes_transmitted") == total
                assert getattr(status, f"{name}_items_produced") == len(data) * count
                assert getattr(status, f"{name}_frames_produced") == len(data)
                policy = settings.adc_policy if kind == 1 else settings.gpio_policy
                assert getattr(status, f"{name}_codec_completed") == (
                    len(data) if policy else 0
                )
                assert getattr(status, f"{name}_codec_raw") == (
                    len(data) if policy and kind == 2 else 0
                )
                assert getattr(status, f"{name}_codec_deadline_drops") == 0
                assert getattr(status, f"{name}_codec_resource_drops") == 0
            else:
                assert getattr(status, f"{name}_frames_transmitted") == len(data)
                assert getattr(status, f"{name}_framed_bytes_transmitted") == total


def test_controlled_mixed_codecs_through_control_and_usb(cpp):
    configs = [s for s in capabilities(cpp).configurations if s.stream_mask == 3]
    operations, records = [], []
    for run, settings in enumerate(configs, 1):
        base = run * 10
        operations += [
            request(command(17, settings.to_bytes(), base)),
            request(command(18, request_id=base + 1)),
        ]
        for pattern in range(4):
            operations += [
                f"P {pattern}",
                request(command(29, request_id=base + 2 + pattern)),
            ]
        operations.append(request(command(20, request_id=base + 6)))
        records.append(settings)
    frames, _ = exchange(cpp, operations, mode="codec", chunks=(1, 17, 2, 61, 3))
    responses = replies(frames)
    assert len(responses) == len(configs) * 7
    assert all(r.error_code == 0 for r in responses.values()), responses
    for run, settings in enumerate(records, 1):
        data = [f for f in frames if f.header.run_id == run and f.header.kind in (1, 2)]
        assert len(data) == 8
        for frame in data:
            block = decode_v3_block(frame, settings)
            assert block.item_count == 12
            assert block.first_sample_ticks == block.sequence * 96
            assert_samples(block, controlled=True)
            assert responses[run * 10 + 2 + block.sequence].value.settings == settings
            if isinstance(block, ADCBlock):
                encoding = 2 if settings.adc_policy else 0
                size = 36 if settings.adc_policy else 48
            else:
                values = [block.sample(i) for i in range(12)]
                runs = sum(1 for _ in groupby(values))
                profitable = runs * (2 + block.item_bytes) < 12 * block.item_bytes
                encoding = 1 if settings.gpio_policy and profitable else 0
                size = (
                    runs * (2 + block.item_bytes) if encoding else 12 * block.item_bytes
                )
            assert block.encoding == encoding
            assert block.wire_bytes == frame.header.total_length == 60 + size
        gpio = [
            decode_v3_block(f, settings).encoding for f in data if f.header.kind == 2
        ]
        assert gpio == ([1, 0, 0, 1] if settings.gpio_policy else [0] * 4)


def test_runtime_loss_counters_match_sequence_gaps_and_decoded_items(cpp):
    settings = replace(capabilities(cpp).defaults, source=1)
    frames, _ = exchange(
        cpp,
        [
            request(command(17, settings.to_bytes())),
            request(command(18, request_id=2)),
            "T 32256",
            "S 220",
            "T 32256",
            request(command(20, request_id=3)),
            request(command(19, request_id=4)),
        ],
    )
    status = replies(frames)[4].value
    assert status.state == 1 and status.pending_frames == 0
    assert reconcile_run_counters(status).exact
    assert status.adc_items_dropped + status.gpio_items_dropped > 0
    for kind, name, count in [(1, "adc", 1008), (2, "gpio", 4032)]:
        data = [f for f in frames if f.header.kind == kind]
        produced = (220 * 1008 + 8064) // count
        assert getattr(status, f"{name}_frames_produced") == produced
        assert getattr(status, f"{name}_items_produced") == produced * count
        assert getattr(status, f"{name}_frames_dropped") == produced - len(data)
        assert (
            getattr(status, f"{name}_items_dropped") == (produced - len(data)) * count
        )
        assert getattr(status, f"{name}_wire_bytes_transmitted") == sum(
            f.header.total_length for f in data
        )
        previous = -1
        for frame in data:
            assert frame.header.sequence > previous
            if frame.header.sequence != previous + 1:
                assert frame.header.flags & 10 == 10
            block = decode_v3_block(frame, settings)
            assert frame.header.first_sample_ticks == frame.header.sequence * count * 8
            assert_samples(block)
            previous = frame.header.sequence
