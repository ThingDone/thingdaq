"""Release policy, human wire table and host regression checks."""

from __future__ import annotations

import json
import struct
from pathlib import Path

from thingdaq import (
    AuxBankMode,
    DAQConfiguration,
    DeviceInfo,
    RateProfile,
    Source,
    StreamMask,
    ThingDAQ,
)
from thingdaq._generated import protocol_v2_constants as c
from thingdaq.protocol_v2 import decode_v2_frame, encode_v2_frame
from thingdaq.simulator import SimulatedDevice
from thingdaq.transport import InMemoryTransport

ROOT = Path(__file__).resolve().parents[2]


def test_release_wire_document_matches_all_command_ids_and_sizes():
    contract = json.loads((ROOT / "protocol/protocol-v2.json").read_text())
    document = (ROOT / "doc/protocol/protocol-v2.md").read_text()
    frames = {frame["name"]: frame for frame in contract["frame_kinds"]}
    for frame in frames.values():
        if frame["class"] != "request":
            continue
        response = frames[frame["response_kind"]]
        request_size = contract["payload_schemas"][frame["payload_schema"]]["size"]
        response_size = contract["payload_schemas"][response["payload_schema"]]["size"]
        row = (
            f"| {frame['name'].removesuffix('_REQUEST')} | `0x{frame['value']:02X}` / "
            f"`0x{response['value']:02X}` | {request_size} / {response_size} |"
        )
        assert row in document
    assert f"(`0x{frames['ERROR_RESPONSE']['value']:02X}`)" in document
    policy = contract["release_policy"]
    assert policy["cpu_hz"] == 450_000_000
    assert policy["default_rate_profile"] == 4
    assert policy["supported_rate_profile_mask"] == 1 << 4
    assert policy["adc_pair_rate_hz"] == policy["gpio_sample_rate_hz"] == 1_000_000


class StopTailDevice(SimulatedDevice):
    def _handle_stop(self, request):
        tail = self.next_data_frame() or b""
        return super()._handle_stop(request) + tail


def test_v2_stop_tail_retains_layout_only_for_discarding():
    with ThingDAQ.open(InMemoryTransport(StopTailDevice()), strict=True) as daq:
        for mode in (AuxBankMode.INPUT, AuxBankMode.DISABLED, AuxBankMode.INPUT):
            daq.configure(
                source=Source.SYNTHETIC,
                aux_bank_mode=mode,
                rate_profile=RateProfile.ADC_1MHZ_GPIO_1MHZ,
            )
            daq.start()
            daq.read_block()
            daq.stop()
            daq.info()
            assert daq.get_temperature().celsius is None
        assert daq.host_counters.protocol_failures == 0


def test_release_info_450mhz_support_mask_and_idle_status():
    fixture = (
        ROOT / "protocol/fixtures-v2/info-disabled-adc-1mhz-gpio-1mhz-response.bin"
    )
    payload = bytearray(decode_v2_frame(fixture.read_bytes()).payload)
    payload[c.INFO_RESPONSE_SUPPORTED_RATE_PROFILE_MASK_OFFSET] = 16
    struct.pack_into(
        "<I", payload, c.INFO_RESPONSE_ADC_TRIGGER_DWT_CLOCK_HZ_OFFSET, 450_000_000
    )
    struct.pack_into(
        "<I", payload, c.INFO_RESPONSE_ADC_COMPLETION_EXPECTED_DELTA_CYCLES_OFFSET, 225
    )
    struct.pack_into(
        "<I", payload, c.INFO_RESPONSE_ADC_COMPLETION_TOLERANCE_CYCLES_OFFSET, 90
    )
    for index, rate in enumerate((1_000_000, 500_000, 250_000, 125_000, 1_000_000)):
        struct.pack_into(
            "<I",
            payload,
            c.INFO_RESPONSE_RATE_PROFILES_OFFSET + 48 * index + 36,
            450_000_000 // (2 * rate),
        )
    frame = decode_v2_frame(
        encode_v2_frame(c.FrameKind.INFO_RESPONSE, payload, request_id=1)
    )
    info = DeviceInfo.from_payload(frame.payload)
    assert info.adc_trigger.dwt_clock_hz == 450_000_000
    for profile in RateProfile:
        configuration = DAQConfiguration(
            stream_mask=StreamMask.ADC | StreamMask.GPIO,
            source=Source.HARDWARE,
            rate_profile=profile,
        )
        assert info.capabilities.supports_configuration(configuration) == (
            profile.value == 4
        )
    idle = DAQConfiguration(
        stream_mask=StreamMask.NONE,
        source=Source.HARDWARE,
        rate_profile=RateProfile.ADC_1MHZ_GPIO_1MHZ,
    )
    assert idle.protocol_version == 2


def test_cached_metadata_is_immutable_and_rejects_bool_profile_aliases():
    import dataclasses

    import pytest
    from thingdaq.models import AdcBlockMetadata, RateProfileTiming

    first = AdcBlockMetadata.for_rate_profile(
        RateProfile.ADC_1MHZ_GPIO_1MHZ, Source.HARDWARE
    )
    assert first is AdcBlockMetadata.for_rate_profile(
        RateProfile.ADC_1MHZ_GPIO_1MHZ, Source.HARDWARE
    )
    with pytest.raises(dataclasses.FrozenInstanceError):
        first.pair_rate_hz = 2
    RateProfileTiming.from_profile(1)
    with pytest.raises(TypeError):
        RateProfileTiming.from_profile(True)
