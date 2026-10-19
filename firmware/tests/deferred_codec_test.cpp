#include <cassert>
#include <fstream>
#include <vector>
#include "packet_buffer_pipeline.h"
#include "deferred_codec.h"
using namespace thingdaq;
static packet::OwnedPacketBufferStorage storage;
static packet::PacketBufferPipeline pipeline(storage);
struct Sink : usb::CdcByteStream {
  std::vector<std::uint8_t> bytes;
  bool sessionOpen() const override { return true; }
  usb::IoCount available() override { return 0; }
  usb::IoCount read(std::uint8_t *, std::size_t) override { return 0; }
  usb::IoCount availableForWrite() override { return 4096; }
  usb::IoCount write(const std::uint8_t *data, std::size_t count) override {
    if (count > 7) count = 7;
    bytes.insert(bytes.end(), data, data + count);
    return static_cast<usb::IoCount>(count);
  }
};
static Sink sink;
static stats::Statistics statistics;
static usb::CdcTransport transport(sink, statistics, &pipeline);
static std::uint64_t fake_now = 0;
static std::uint64_t lateClock(void *) { fake_now += 80000U; return fake_now; }
static void start(std::uint32_t id) {
  auto layout = stream_layout::experimental(protocol_v2::AuxBankMode::kInput,
      static_cast<protocol_v2::RateProfile>(4));
  assert(pipeline.startRun(id, protocol_v1::kDefaultChecksumAlgorithm, packet::kAllStreamMask, layout.layout) == packet::OperationStatus::kOk);
}
static void fill(packet::Stream stream, bool noisy = false) {
  const auto handle = pipeline.beginFill(stream).handle;
  auto view = pipeline.writablePayload(handle);
  for (std::size_t i = 0; i < view.size / 2U; ++i) {
    const auto value = stream == packet::Stream::kAdc ? (i * 31U) % 4096U : noisy ? i % 2U : i / 32U;
    view.data[2*i] = static_cast<std::uint8_t>(value);
    view.data[2*i+1] = static_cast<std::uint8_t>(value >> 8U);
  }
  packet::FrameCompletion c;
  c.payload_bytes_written = view.size;
  c.first_sample_ticks = handle.sequence * pipeline.streamLayout(stream).coverage_ticks;
  c.flags = handle.sequence == 0 ? static_cast<std::uint16_t>(protocol_v1::FrameFlag::kEpochStart) : 0;
  assert(pipeline.finishFill(handle, c).ok());
  assert(pipeline.writablePayload(handle).size == 0U); // invalidated producer lease
}
static void drain(std::ofstream *out = nullptr) {
  for (unsigned i = 0; i < 1000 && !pipeline.quiescent(); ++i) {
    pipeline.serviceDeferred(100U);
    pipeline.serviceReadyFrames();
    transport.serviceTransmit();

  }
  assert(pipeline.quiescent());
  assert(pipeline.snapshot().pending_frames == 0U);
  if (out) out->write(reinterpret_cast<const char *>(sink.bytes.data()), static_cast<std::streamsize>(sink.bytes.size()));
  sink.bytes.clear();
}
int main(int argc, char **argv) {
  assert(argc == 2);
  start(1); pipeline.setDeferredClock(0);
  fill(packet::Stream::kAdc); fill(packet::Stream::kGpio);
  // No transform or selected-wire publication in acquisition context.
  const auto before = pipeline.snapshot();
  assert(before.pending_frames == 2U);
  assert(before.sources[0].frames_framed == (input_experiment::kPackAdc ? 0U : 1U));
  assert(before.sources[1].frames_framed == (input_experiment::kEncodeGpio ? 0U : 1U));
  pipeline.stopProduction(); // complete deferred pages must drain, not cancel
  std::ofstream out(argv[1], std::ios::binary); drain(&out); out.close();
  assert(pipeline.readyForStart());
  assert(pipeline.sourceCounters(packet::Stream::kAdc).frames_transmitted == 1);
  assert(pipeline.sourceCounters(packet::Stream::kGpio).frames_transmitted == 1);
  if (input_experiment::kEncodeGpio) {
    start(2); pipeline.setDeferredClock(0xFFFFFF00ULL);
    fill(packet::Stream::kGpio); pipeline.serviceDeferred(0xFFFFFF00ULL + 79999U, 0);
    assert(pipeline.sourceCounters(packet::Stream::kGpio).frames_dropped == 0);
    pipeline.serviceDeferred(0xFFFFFF00ULL + 80000U, 0); // exact boundary and uint32 wrap
    assert(deferred_codec::counters[1].deadline_drops == 1);
    assert(pipeline.sourceCounters(packet::Stream::kGpio).frames_dropped == 1);
    assert(pipeline.sourceCounters(packet::Stream::kGpio).frames_dropped_after_framing == 0);
    pipeline.setDeferredClock(100U); fill(packet::Stream::kGpio);
    pipeline.serviceDeferred(100U); pipeline.stopProduction(); pipeline.serviceReadyFrames();
    assert(pipeline.prepareFrontFrame());
    std::uint16_t flags = 0;
    assert(protocol::loadU16(pipeline.frontFrame(), protocol_v1::kHeaderFlagsOffset, flags));
    assert(flags & static_cast<std::uint16_t>(protocol_v1::FrameFlag::kGapBefore));
    drain();
    start(3); pipeline.setDeferredClock(0); fill(packet::Stream::kGpio);
    pipeline.serviceDeferred(0, 1, lateClock);
    assert(deferred_codec::counters[1].deadline_drops == 1); // late completion rejected too
    pipeline.stopProduction(); drain();
    start(4); pipeline.setDeferredClock(0); fill(packet::Stream::kGpio, true);
    pipeline.serviceDeferred(100); assert(deferred_codec::counters[1].raw == 1);
    pipeline.stopProduction(); drain();
    start(5); pipeline.setDeferredClock(0); fill(packet::Stream::kGpio);
    pipeline.serviceDeferred(100); // leave READY predecessor blocked by USB
    fill(packet::Stream::kGpio);
    pipeline.serviceDeferred(80100U, 0);
    assert(deferred_codec::counters[1].deadline_drops == 1);
    assert(pipeline.sourceCounters(packet::Stream::kGpio).frames_framed == 1);
    pipeline.stopProduction(); drain();
    start(6); pipeline.setDeferredClock(0); fill(packet::Stream::kGpio);
    std::vector<packet::FillHandle> held;
    while (pipeline.freeBuffers()) held.push_back(pipeline.beginFill(packet::Stream::kAdc).handle);
    pipeline.serviceDeferred(100);
    assert(deferred_codec::counters[1].resource_drops == 1);
    for (const auto &h : held) assert(pipeline.cancelFill(h));
    pipeline.stopProduction(); drain();
  }
  if (input_experiment::kEncodeGpio) {
    start(8); pipeline.setDeferredClock(0); fill(packet::Stream::kGpio);
    pipeline.serviceDeferred(100);
    std::vector<packet::FillHandle> held;
    while (pipeline.freeBuffers()) held.push_back(pipeline.beginFill(packet::Stream::kAdc).handle);
    const auto admitted = pipeline.beginFill(packet::Stream::kAdc);
    assert(admitted.ok()); // evicts the only READY page: a compressed GPIO record
    assert(pipeline.sourceCounters(packet::Stream::kGpio).frames_evicted == 1);
    held.push_back(admitted.handle);
    for (const auto &h : held) assert(pipeline.cancelFill(h));
    pipeline.stopProduction(); drain();
  }
  if (input_experiment::kPackAdc) {
    start(7); pipeline.setDeferredClock(0);
    auto h = pipeline.beginFill(packet::Stream::kAdc).handle;
    auto payload = pipeline.writablePayload(h);
    for (std::size_t i = 0; i < payload.size; ++i) payload.data[i] = 0;
    packet::FrameCompletion c; c.payload_bytes_written = payload.size;
    c.flags = static_cast<std::uint16_t>(protocol_v1::FrameFlag::kEpochStart);
    assert(pipeline.finishFill(h, c).ok());
    payload.data[1] = 0xF0; // deliberately corrupt a queued page to exercise defense
    pipeline.serviceDeferred(100);
    assert(deferred_codec::counters[0].resource_drops == 1);
    assert(pipeline.snapshot().encoding_rejections == 1);
    pipeline.stopProduction(); drain();
  }
}
