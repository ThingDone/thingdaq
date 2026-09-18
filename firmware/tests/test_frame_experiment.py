"""Independent wire/continuity checks for the isolated larger-ADC experiment."""

from __future__ import annotations

import importlib.util
import subprocess
import sys
from pathlib import Path

import pytest

ROOT = Path(__file__).resolve().parents[2]


def load(name, path):
    spec = importlib.util.spec_from_file_location(name, ROOT / path)
    module = importlib.util.module_from_spec(spec)
    sys.modules[name] = module
    spec.loader.exec_module(module)
    return module


@pytest.mark.parametrize("expanded", [False, True])
def test_real_encoder_layouts_and_memory_are_consistent(tmp_path, expanded):
    source = tmp_path / "frames.cpp"
    source.write_text(r"""
#include <array>
#include <cassert>
#include "packet_buffer_pipeline.h"
using namespace thingdaq;
int main() {
  static_assert(board::kPacketBufferStorageBytes == 819200U);
  static_assert(sizeof(packet::PacketFrame) == 4096U);
  assert(stream_layout::legacy().streams[0].item_count == 1012U);
  for (auto mode : {protocol_v2::AuxBankMode::kDisabled,
                    protocol_v2::AuxBankMode::kInput}) {
    for (const auto &timing : rate_profile::kTimings) {
      const auto result = stream_layout::experimental(mode, timing.profile);
      assert(result.ok());
      const bool input = mode == protocol_v2::AuxBankMode::kInput;
      const auto expected = input ? 506U * input_experiment::kAdcFrameMultiplier : 1012U;
      assert(result.layout.streams[0].item_count == expected);
      assert(result.layout.streams[1].frame_bytes == 4096U);
      packet::OwnedPacketBufferStorage storage;
      packet::PacketBufferPipeline pipeline(storage);
      assert(pipeline.startRun(1, protocol_v1::kDefaultChecksumAlgorithm,
          packet::kAllStreamMask, result.layout) == packet::OperationStatus::kOk);
      const auto adc_ticks = result.layout.streams[0].coverage_ticks;
      const auto gpio_ticks = result.layout.streams[1].coverage_ticks;
      const auto common_ticks = adc_ticks > gpio_ticks ? adc_ticks : gpio_ticks;
      assert(pipeline.recordSourceFrameDrops(packet::Stream::kAdc,
          10U * common_ticks / adc_ticks) == packet::OperationStatus::kOk);
      assert(pipeline.recordSourceFrameDrops(packet::Stream::kGpio,
          10U * common_ticks / gpio_ticks) == packet::OperationStatus::kOk);
      assert(pipeline.snapshot().accounted_frame_skew == 0U);
      for (int stream = 0; stream < 2; ++stream) {
        const auto &layout = result.layout.streams[stream];
        std::array<std::uint8_t, 4096> bytes{};
        protocol::FrameFields fields{};
        fields.kind = stream == 0 ? protocol_v1::FrameKind::kAdcData
                                  : protocol_v1::FrameKind::kGpioData;
        fields.run_id = 1;
        fields.flags = static_cast<std::uint16_t>(protocol_v1::FrameFlag::kEpochStart);
        fields.item_count = layout.item_count;
        fields.version = 2;
        const protocol::DataFrameShape shape{
            2, layout.item_count, layout.item_bytes, layout.item_period_ticks,
            layout.payload_bytes, layout.frame_bytes};
        assert(protocol::encodeDataFrameInPlace(
            fields, {bytes.data(), layout.frame_bytes},
            layout.payload_bytes, shape).ok());
        protocol::DecodedFrame decoded{};
        assert(protocol::decodeFrame({bytes.data(), layout.frame_bytes}, decoded).ok());
        assert(decoded.header.item_count == layout.item_count);
        assert(decoded.header.total_length == layout.frame_bytes);
        assert(decoded.checksum == 0);
      }
    }
  }
}
""")
    executable = tmp_path / "frames"
    flags = ["-DTHINGDAQ_EXPERIMENT_NO_DATA_CHECKSUM=1"]
    if expanded:
        flags.append("-DTHINGDAQ_EXPERIMENT_LARGE_ADC_FRAME=1")
    subprocess.run(
        [
            "g++",
            "-std=c++17",
            "-O2",
            "-Wall",
            "-Wextra",
            "-Werror",
            *flags,
            f"-I{ROOT / 'firmware/src'}",
            str(source),
            str(ROOT / "firmware/src/protocol.cpp"),
            str(ROOT / "firmware/src/packet_buffer_pipeline.cpp"),
            str(ROOT / "firmware/src/checksum.cpp"),
            "-o",
            str(executable),
        ],
        check=True,
        capture_output=True,
    )
    subprocess.run([str(executable)], check=True, capture_output=True)


def test_host_expansion_preserves_gpio_and_detects_bad_adc_continuity():
    rig = load("frame_rig", "firmware/tests/rig_aux_input_capture.py")
    adapter = load("frame_adapter", "firmware/tests/checksum_experiment_adapter.py")
    original = rig.LAYOUTS[rig.AUX_DISABLED]
    adapter._experiment_expand_adc(vars(rig))
    assert rig.LAYOUTS[rig.AUX_DISABLED] == original
    layout = rig.LAYOUTS[rig.AUX_INPUT]
    assert layout.adc_items_per_frame == 1012
    assert layout.gpio_items_per_frame == 2024
    profile = rig.PROFILE_BY_VALUE[4]
    validator = rig.AcquisitionValidator(
        1, rig.CHECKSUM_ADLER32, rig.RUN_CASES["INPUT_COMBINED"], profile, None
    )

    # Frame construction follows the independent rig's dataclass, not SDK constants.
    def frame(sequence, ticks):
        return rig.Frame(
            kind=rig.ADC_DATA,
            flags=rig.FLAG_EPOCH_START if sequence == 0 else 0,
            checksum_algorithm=rig.CHECKSUM_ADLER32,
            run_id=1,
            sequence=sequence,
            request_id=0,
            first_sample_ticks=ticks,
            item_count=1012,
            payload=bytes(4048),
            checksum=0,
        )

    validator.accept(frame(0, 0))
    validator.accept(frame(1, 8096))
    for sequence in range(3):
        validator.accept(
            rig.Frame(
                kind=rig.GPIO_DATA,
                flags=rig.FLAG_EPOCH_START if sequence == 0 else 0,
                checksum_algorithm=rig.CHECKSUM_ADLER32,
                run_id=1,
                sequence=sequence,
                request_id=0,
                first_sample_ticks=sequence * 16192,
                item_count=2024,
                payload=bytes(4048),
                checksum=0,
            )
        )
        if sequence < 2:
            validator.accept(frame(2 + sequence * 2, (2 + sequence * 2) * 8096))
            validator.accept(frame(3 + sequence * 2, (3 + sequence * 2) * 8096))
    assert validator.adc.items == 6072
    assert validator.maximum_frame_skew == 2
    with pytest.raises(rig.ProtocolFailure, match="continuity"):
        validator.accept(frame(6, 12144))
