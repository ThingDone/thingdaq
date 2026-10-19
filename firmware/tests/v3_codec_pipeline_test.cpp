#include <cassert>
#include <cstdint>
#include <fstream>
#include <vector>
#include "packet_buffer_pipeline.h"
#include "deferred_codec.h"
using namespace thingdaq;
static packet::OwnedPacketBufferStorage storage;
static packet::PacketBufferPipeline pipeline(storage);
static auto checksum = protocol_v1::kDefaultChecksumAlgorithm;
static std::uint32_t epoch = 0U;

static settings::Record selection(unsigned width, unsigned policies) {
  auto value = settings::kBoardDefaults;
  value[protocol_v3::kSettingsAuxBankModeOffset] = width == 16U ? 1U : 0U;
  value[protocol_v3::kSettingsGpioWidthBitsOffset] = static_cast<std::uint8_t>(width);
  value[protocol_v3::kSettingsGpioPolicyOffset] = static_cast<std::uint8_t>(policies & 1U);
  value[protocol_v3::kSettingsAdcPolicyOffset] = static_cast<std::uint8_t>((policies >> 1U) & 1U);
  return value;
}
static void start(unsigned width = 16U, unsigned policies = 3U, bool maximum = false) {
  const auto result = stream_layout::publicV3(selection(width, policies),
      maximum ? 1009U : 12U, maximum ? (width == 8U ? 4036U : 2018U) : 12U);
  assert(result.ok());
  assert(pipeline.startRun(++epoch, checksum, packet::kAllStreamMask, result.layout) == packet::OperationStatus::kOk);
  pipeline.setDeferredClock(0U);
}
static packet::FillHandle fill(packet::Stream stream, unsigned pattern = 0U) {
  const auto begun = pipeline.beginFill(stream);
  assert(begun.ok());
  const auto view = pipeline.writablePayload(begun.handle);
  const auto &layout = pipeline.streamLayout(stream);
  for (std::size_t i = 0; i < layout.item_count; ++i) {
    if (stream == packet::Stream::kAdc) {
      const auto a = i % 2U ? 4095U : i % 4096U;
      const auto b = i % 2U ? 0U : (i * 31U) % 4096U;
      assert(protocol::storeU16(view, i * 4U, static_cast<std::uint16_t>(a)));
      assert(protocol::storeU16(view, i * 4U + 2U, static_cast<std::uint16_t>(b)));
    } else {
      // Constant, incompressible, exact tie (12 items), and profitable spans.
      const auto value = pattern == 0U ? 0U : pattern == 1U ? i % 2U :
          pattern == 2U ? i / (layout.item_bytes == 1U ? 3U : 2U) : i / 8U;
      view.data[i * layout.item_bytes] = static_cast<std::uint8_t>(value);
      if (layout.item_bytes == 2U) view.data[i * 2U + 1U] = 0xABU;
    }
  }
  packet::FrameCompletion c;
  c.checksum_algorithm = checksum;
  c.payload_bytes_written = view.size;
  c.first_sample_ticks = begun.handle.sequence * layout.coverage_ticks;
  c.flags = begun.handle.sequence == 0U ? 4U : 0U;
  assert(pipeline.finishFill(begun.handle, c).ok());
  assert(pipeline.writablePayload(begun.handle).size == 0U);
  return begun.handle;
}
static void drain(std::ofstream *output = nullptr) {
  for (unsigned pass = 0; pass < 100U && !pipeline.quiescent(); ++pass) {
    pipeline.serviceDeferred(100U);
    pipeline.serviceReadyFrames();
    while (pipeline.frontFrame().size != 0U) {
      const auto bytes = pipeline.frontFrame();
      assert(pipeline.prepareFrontFrame());
      pipeline.markFrontFrameStarted();
      if (output) output->write(reinterpret_cast<const char *>(bytes.data), static_cast<std::streamsize>(bytes.size));
      pipeline.releaseFrontFrame();
    }
  }
  assert(pipeline.quiescent());
}
static std::uint64_t lateClock(void *) { return 80000U; }
int main(int argc, char **argv) {
  assert(argc == 2);
  std::ofstream output(argv[1], std::ios::binary);
  for (auto width : {8U, 16U}) for (unsigned policies = 0; policies < 4U; ++policies)
    for (auto algorithm : {1U}) for (auto maximum : {false, true})
      for (unsigned pattern = 0; pattern < 4U; ++pattern) {
        checksum = static_cast<protocol_v1::ChecksumAlgorithm>(algorithm);
        start(width, policies, maximum);
        fill(packet::Stream::kAdc); fill(packet::Stream::kGpio, pattern);
        const auto before = pipeline.snapshot();
        assert(before.pending_frames == 2U);
        assert(before.sources[0].frames_framed == ((policies & 2U) ? 0U : 1U));
        assert(before.sources[1].frames_framed == ((policies & 1U) ? 0U : 1U));
        pipeline.serviceDeferred(100U, 0U);
        assert(pipeline.snapshot().sources[0].frames_framed == before.sources[0].frames_framed);
        pipeline.stopProduction(); // complete deferred STOP tails still drain
        drain(&output);
        assert(pipeline.sourceCounters(packet::Stream::kAdc).items_transmitted == (maximum ? 1009U : 12U));
        assert(deferred_codec::counters[0].completed == ((policies & 2U) ? 1U : 0U));
        assert(deferred_codec::counters[1].completed == ((policies & 1U) ? 1U : 0U));
      }
  output.close();
  checksum = protocol_v1::kDefaultChecksumAlgorithm;
  start();
  pipeline.setDeferredClock(0xFFFFFF00ULL); fill(packet::Stream::kGpio);
  pipeline.serviceDeferred(0xFFFFFF00ULL + 79999U, 0U);
  assert(deferred_codec::counters[1].deadline_drops == 0U);
  pipeline.serviceDeferred(0xFFFFFF00ULL + 80000U, 0U);
  assert(deferred_codec::counters[1].deadline_drops == 1U);
  pipeline.setDeferredClock(100U); fill(packet::Stream::kGpio);
  pipeline.serviceDeferred(100U);
  assert(pipeline.recordSourceFrameDrops(packet::Stream::kAdc, 1U) == packet::OperationStatus::kOk);
  pipeline.serviceReadyFrames();
  assert(pipeline.prepareFrontFrame());
  std::uint16_t flags = 0U;
  assert(protocol::loadU16(pipeline.frontFrame(), 6U, flags) && (flags & 10U) == 10U);
  // A started frame stays byte-for-byte immutable while another codec runs.
  pipeline.markFrontFrameStarted();
  auto front = pipeline.frontFrame();
  const std::vector<std::uint8_t> saved(front.data, front.data + front.size);
  fill(packet::Stream::kAdc); pipeline.serviceDeferred(100U);
  assert(std::vector<std::uint8_t>(front.data, front.data + front.size) == saved);
  pipeline.releaseFrontFrame(); pipeline.stopProduction(); drain();
  start(); fill(packet::Stream::kGpio);
  pipeline.serviceDeferred(0U, 1U, lateClock);
  assert(deferred_codec::counters[1].deadline_drops == 1U);
  pipeline.stopProduction(); drain();
  start(); fill(packet::Stream::kGpio);
  std::vector<packet::FillHandle> held;
  while (pipeline.freeBuffers()) held.push_back(pipeline.beginFill(packet::Stream::kAdc).handle);
  pipeline.serviceDeferred(100U);
  assert(deferred_codec::counters[1].resource_drops == 1U);
  for (auto h : held) assert(pipeline.cancelFill(h));
  pipeline.stopProduction(); drain();
  // Invalid ADC inputs are rejected even when RAW is selected.
  for (auto policies : {0U, 2U}) {
    start(8U, policies);
    auto h = pipeline.beginFill(packet::Stream::kAdc).handle;
    auto view = pipeline.writablePayload(h);
    for (std::size_t i = 0; i < view.size; ++i) view.data[i] = 0U;
    view.data[view.size - 1U] = 0x10U;
    packet::FrameCompletion c; c.payload_bytes_written = view.size; c.flags = 4U;
    assert(pipeline.finishFill(h, c).status == packet::OperationStatus::kEncodingRejected);
    assert(pipeline.sourceCounters(packet::Stream::kAdc).frames_dropped == 1U);
    pipeline.stopProduction(); drain();
  }
  assert(!stream_layout::publicV3(selection(8U, 3U), 1010U, 12U).ok());
  assert(!stream_layout::publicV3(selection(8U, 3U), 12U, 4037U).ok());
  assert(!stream_layout::publicV3(selection(16U, 3U), 12U, 2019U).ok());
  for (auto algorithm : {2U, 3U}) {
    const auto layout = stream_layout::publicV3(selection(8U, 3U), 12U, 12U);
    assert(pipeline.startRun(++epoch, static_cast<protocol_v1::ChecksumAlgorithm>(algorithm),
        packet::kAllStreamMask, layout.layout) == packet::OperationStatus::kUnsupportedChecksum);
  }
  auto unsupported = selection(8U, 3U);
  unsupported[protocol_v3::kSettingsCpuProfileOffset] = 2U;
  assert(!stream_layout::publicV3(unsupported, 12U, 12U).ok());
}
