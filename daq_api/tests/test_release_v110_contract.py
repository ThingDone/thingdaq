"""Release policy, human wire table and host regression checks."""

from __future__ import annotations

import json
from pathlib import Path

from thingdaq import AuxBankMode, RateProfile, Source, ThingDAQ
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
