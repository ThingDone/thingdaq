#include <algorithm>
#include <array>
#include <cassert>
#include <fstream>
#include <limits>
#include <vector>
#include "packet_buffer_pipeline.h"
#include "adc_dma_fault.h"
#include "rle_encoder.h"
#include "usb_transport.h"
using namespace thingdaq;
namespace thingdaq::packet {
struct PacketBufferPipelineTestAccess {
  static void corruptSelectedLength(PacketBufferPipeline &p) {
    auto index = *p.transmit_queue_.front();
    p.storage_.frame(index)[protocol_v1::kHeaderTotalLengthOffset] ^= 4U;
  }
  static void gap(PacketBufferPipeline &p) {
    p.markGapBefore(*p.transmit_queue_.front());
  }
};
}
struct Sink final : usb::CdcByteStream {
  std::vector<std::uint8_t> bytes;
  bool open = true;
  int writes_remaining = -1;
  bool sessionOpen() const override { return open; }
  usb::IoCount available() override { return 0; }
  usb::IoCount read(std::uint8_t *, std::size_t) override { return 0; }
  usb::IoCount availableForWrite() override { return 4096; }
  usb::IoCount write(const std::uint8_t *data, std::size_t size) override {
    if (writes_remaining == 0) return usb::kWriteWouldBlock;
    if (writes_remaining > 0) --writes_remaining;
    size = std::min(size, std::size_t{7});
    bytes.insert(bytes.end(), data, data + size);
    return static_cast<usb::IoCount>(size);
  }
};
std::vector<std::uint8_t> pattern(int kind, std::size_t width = 2) {
  std::vector<std::uint8_t> out(2024 * width);
  std::uint32_t random = 42;
  for (std::size_t i = 0; i < 2024; ++i) {
    random = random * 1664525U + 1013904223U;
    std::uint32_t value = kind == 0 ? 0xabcdU : kind == 1 ? static_cast<std::uint32_t>(i / 40)
      : kind == 2 ? static_cast<std::uint32_t>(i % 2) : random >> 8;
    for (std::size_t j = 0; j < width; ++j) out[i * width + j] = static_cast<std::uint8_t>(value >> (8 * j));
  }
  return out;
}
void codec() {
  for (std::size_t width : {1U, 2U, 4U}) for (int kind = 0; kind < 4; ++kind) {
    auto input = pattern(kind, width);
    protocol::ByteView view{input.data(), input.size()};
    auto plan = rle::size(view, {width, 2024});
    assert(plan.ok());
    auto selected = rle::sizeForAdaptiveSelection(view, {width, 2024}, input.size() + 47);
    assert(selected.ok() && selected.select_rle == (kind < 2));
    std::vector<std::uint8_t> output(plan.encoded_payload_bytes + 1, 0xa5);
    assert(rle::encode(view, plan, {output.data(), output.size()}).ok());
    assert(output.back() == 0xa5);
    std::vector<std::uint8_t> decoded;
    for (std::size_t off = 0; off < plan.encoded_payload_bytes; off += width + 2) {
      std::uint16_t count = 0;
      assert(protocol::loadU16({output.data(), output.size()}, off, count));
      for (std::size_t i = 0; i < count; ++i)
        decoded.insert(decoded.end(), output.begin() + static_cast<long>(off + 2), output.begin() + static_cast<long>(off + 2 + width));
    }
    assert(decoded == input);
    assert(!rle::encode(view, plan, {output.data(), plan.encoded_payload_bytes - 1}).ok());
    assert(!rle::encode(view, plan, {input.data(), input.size()}).ok());
    ++plan.item_count;
    assert(!rle::encode(view, plan, {output.data(), output.size()}).ok());
  }
  std::array<std::uint8_t, 2> bytes{};
  assert(!rle::size({bytes.data(), bytes.size()}, {0, 2024}).ok());
  assert(!rle::size({bytes.data(), 1}, {2, 2024}).ok());
  assert(!rle::size({bytes.data(), 65536}, {1, 65536}).ok()); // rejected before reading
  auto plan = rle::size({bytes.data(), 2}, {1, 2});
  bytes[1] = 1; // stale sizing plan cannot publish an incorrect encoding
  std::array<std::uint8_t, 8> output{};
  assert(!rle::encode({bytes.data(), 2}, plan, {output.data(), output.size()}).ok());
}
void finish(packet::PacketBufferPipeline &p, packet::FillHandle handle, int kind) {
  auto payload = p.writablePayload(handle);
  auto data = pattern(kind);
  assert(payload.size == data.size());
  std::copy(data.begin(), data.end(), payload.data);
  packet::FrameCompletion completion{};
  completion.payload_bytes_written = payload.size;
  completion.first_sample_ticks = static_cast<std::uint64_t>(handle.sequence) * 16192;
  completion.flags = handle.sequence == 0 ? static_cast<std::uint16_t>(protocol_v1::FrameFlag::kEpochStart) : 0U;
  assert(p.finishFill(handle, completion).ok());
}
void start(packet::PacketBufferPipeline &p, std::uint32_t id) {
  auto layout = stream_layout::experimental(protocol_v2::AuxBankMode::kInput,
      static_cast<protocol_v2::RateProfile>(4));
  assert(layout.ok());
  assert(p.startRun(id, protocol_v1::kDefaultChecksumAlgorithm,
      packet::kGpioStreamMask, layout.layout) == packet::OperationStatus::kOk);
}
int main(int argc, char **argv) {
  assert(argc == 2 || argc == 3);
  adc_capture::fault_trace::reset();
  for (std::uint32_t i = 1; i <= 3; ++i)
    adc_capture::fault_trace::rememberProgress(
        i, i + 10, i + 20, i + 30, i + 40, i + 50);
  adc_capture::fault_trace::retainProgress();
  for (std::size_t i = 0; i < 6; ++i) {
    assert(adc_capture::fault_trace::detail[36 + i] == 2 + i * 10);
    assert(adc_capture::fault_trace::detail[42 + i] == 3 + i * 10);
  }
  adc_capture::fault_trace::words[0] = 1;
  adc_capture::fault_trace::rememberProgress(99, 99, 99, 99, 99, 99);
  adc_capture::fault_trace::retainProgress();
  assert(adc_capture::fault_trace::detail[42] == 3);
  adc_capture::fault_trace::reset();
  adc_capture::fault_trace::retainProgress();
  for (std::size_t i = 36; i < 96; ++i)
    assert(adc_capture::fault_trace::detail[i] == 0);
  // Thresholds crossed between observations share the first later snapshot.
  // Later snapshots never overwrite reached checkpoints, including DWT wrap.
  for (std::uint32_t generation : {0U, 3U, 16U, 2048U, 4096U})
    adc_capture::fault_trace::rememberProgress(
        generation, 0x11U, 2U, 3U, 0x03F403F3U, 0xFFFFFFFEU);
  adc_capture::fault_trace::retainProgress();
  constexpr std::array<std::uint32_t, 8> expected_phases{
      0U, 3U, 3U, 16U, 16U, 2048U, 2048U, 2048U};
  for (std::size_t i = 0; i < expected_phases.size(); ++i) {
    const std::size_t offset = 48 + i * 6;
    assert(adc_capture::fault_trace::detail[offset] == expected_phases[i]);
    assert(adc_capture::fault_trace::detail[offset + 4] == 0x03F403F3U);
    assert(adc_capture::fault_trace::detail[offset + 2] -
           adc_capture::fault_trace::detail[offset + 5] == 4U);
  }
  adc_capture::fault_trace::words[0] = 1U;
  adc_capture::fault_trace::rememberProgress(9999, 99, 99, 99, 99, 99);
  adc_capture::fault_trace::retainProgress();
  assert(adc_capture::fault_trace::detail[42] == 4096U);
  assert(adc_capture::fault_trace::detail[90] == 2048U);
  adc_capture::fault_trace::reset();
  adc_capture::fault_trace::retainProgress();
  for (std::size_t i = 36; i < 96; ++i)
    assert(adc_capture::fault_trace::detail[i] == 0);
  if (argc == 3) {
    std::ofstream status_out(argv[2], std::ios::binary);
    protocol::Request request{};
    request.kind = protocol_v1::CommandKind::kGetStatus;
    request.protocol_version = 2;
    request.request_id = 1;
    protocol::StatusResponse response{};
    response.configuration.rate_profile = protocol_v2::RateProfile::kAdc1mhzGpio1mhz;
    for (unsigned state = 0; state < 3; ++state) {
      adc_capture::fault_trace::reset();
      if (state != 2) {
        for (std::size_t i = 1; i < adc_capture::fault_trace::kWords; ++i)
          adc_capture::fault_trace::words[i] = static_cast<std::uint32_t>(i * 17);
        if (state == 1) adc_capture::fault_trace::words[0] = 1U | (2U << 8U) | (3U << 12U) | (4U << 16U);
      }
      for (std::size_t i = 0; i < adc_capture::fault_trace::kDetailWords; ++i) {
        // Unpublished data must remain hidden; reset must clear the detail too.
        if (state != 2) adc_capture::fault_trace::detail[i] = static_cast<std::uint32_t>((i + 1) * 23);
      }
      request.request_id = 1;
      protocol::ControlFrame status;
      assert(protocol::encodeStatusResponse(request, 0, response, status).ok());
      status_out.write(reinterpret_cast<const char *>(status.view().data),
                       static_cast<std::streamsize>(status.size()));
      for (std::uint32_t page = 1; page <= 48; ++page) {
        request.request_id = adc_capture::fault_trace::kDetailRequestBase + page;
        assert(protocol::encodeStatusResponse(request, 0, response, status).ok());
        status_out.write(reinterpret_cast<const char *>(status.view().data),
                         static_cast<std::streamsize>(status.size()));
      }
      assert(adc_capture::fault_trace::snapshot(0xFADC0000U) ==
             adc_capture::fault_trace::snapshot());
      assert(adc_capture::fault_trace::snapshot(0xFADC0031U) ==
             adc_capture::fault_trace::snapshot());
    }
  }
  codec();
  packet::OwnedPacketBufferStorage storage;
  packet::PacketBufferPipeline pipeline(storage);
  stats::Statistics statistics;
  Sink sink;
  usb::CdcTransport transport(sink, statistics, &pipeline);
  start(pipeline, 1);
  std::uint64_t expected_wire = 0;
  for (int kind = 0; kind < 4; ++kind) {
    auto handle = pipeline.beginFill(packet::Stream::kGpio);
    assert(handle.ok()); finish(pipeline, handle.handle, kind);
    assert(pipeline.freeBuffers() == board::kPacketBufferCount - 1);
    assert(pipeline.serviceReadyFrames(1).frames_promoted == 1);
    auto frame = pipeline.frontFrame();
    assert((frame.data[4] == input_experiment::kGpioRleVersion) == (kind < 2));
    expected_wire += frame.size;
    for (int visits = 0; pipeline.queuedFrames() && visits < 1000; ++visits) transport.serviceTransmit();
    assert(!pipeline.queuedFrames());
  }
  pipeline.stopProduction();
  assert(sink.bytes.size() == expected_wire);
  auto snapshot = pipeline.snapshot();
  assert(snapshot.source_bytes[1].framed_bytes_transmitted == expected_wire);
  assert(snapshot.source_bytes[1].payload_bytes_transmitted == 4 * 4048);
  assert(snapshot.source_bytes[1].framed_bytes_framed == expected_wire);
  assert(snapshot.source_bytes[1].framed_bytes_emitted == expected_wire);
  assert(transport.snapshot().io_errors == 0);
  std::ofstream out(argv[1], std::ios::binary);
  out.write(reinterpret_cast<const char *>(sink.bytes.data()), static_cast<std::streamsize>(sink.bytes.size()));
  out.close();

  // Exhaust FREE storage with owned producer leases. Compression must fall back
  // without evicting any existing frame or stealing an outstanding lease.
  start(pipeline, 2);
  std::vector<packet::FillHandle> leases;
  for (std::size_t i = 0; i < board::kPacketBufferCount; ++i) {
    auto acquired = pipeline.beginFill(packet::Stream::kGpio);
    assert(acquired.ok()); leases.push_back(acquired.handle);
  }
  finish(pipeline, leases.front(), 0);
  assert(pipeline.serviceReadyFrames(1).frames_promoted == 1);
  assert(pipeline.frontFrame().size == 4096);
  assert(pipeline.snapshot().pressure_evictions == 0);
  pipeline.releaseFrontFrame();
  for (std::size_t i = 1; i < leases.size(); ++i) assert(pipeline.cancelFill(leases[i]));
  pipeline.stopProduction();
  assert(pipeline.freeBuffers() == board::kPacketBufferCount);

  // A late loss annotation must checksum the selected compressed length.
  start(pipeline, 3);
  auto acquired = pipeline.beginFill(packet::Stream::kGpio);
  assert(acquired.ok()); finish(pipeline, acquired.handle, 0);
  assert(pipeline.serviceReadyFrames(1).frames_promoted == 1);
  packet::PacketBufferPipelineTestAccess::gap(pipeline);
  assert(pipeline.prepareFrontFrame());
  auto frame = pipeline.frontFrame();
  assert(frame.size == 52 && frame.data[4] == input_experiment::kGpioRleVersion);
  std::uint32_t actual = 0, expected = 0;
  assert(protocol::loadU32(frame, frame.size - 4, actual));
  assert(protocol::computeChecksum(protocol_v1::kDefaultChecksumAlgorithm,
      {frame.data, frame.size - 4}, expected).ok());
  assert(actual == expected);
  assert((frame.data[6] & 10U) == 10U);
  // Disconnect during a short write abandons only the pinned compressed frame.
  sink.writes_remaining = 1;
  transport.serviceTransmit();
  assert(transport.snapshot().active_frame_bytes_sent == 7);
  sink.open = false;
  transport.serviceTransmit();
  pipeline.stopProduction();
  assert(pipeline.freeBuffers() == board::kPacketBufferCount);
  std::uint32_t raw_run_id = 4;
  // Both ADC and ordinary 8-bit GPIO remain RAW under the experimental build.
  for (auto mode : {protocol_v2::AuxBankMode::kDisabled, protocol_v2::AuxBankMode::kInput}) {
    for (auto stream : {packet::Stream::kAdc, packet::Stream::kGpio}) {
      if (mode == protocol_v2::AuxBankMode::kInput && stream == packet::Stream::kGpio) continue;
      const auto layout = stream_layout::experimental(mode, protocol_v2::RateProfile::kAdc1mhzGpio1mhz);
      assert(pipeline.startRun(raw_run_id++, protocol_v1::kDefaultChecksumAlgorithm,
          packet::streamBit(stream), layout.layout) == packet::OperationStatus::kOk);
      auto begun = pipeline.beginFill(stream);
      assert(begun.ok());
      auto payload = pipeline.writablePayload(begun.handle);
      std::fill(payload.data, payload.data + payload.size, 0);
      packet::FrameCompletion completed{};
      completed.flags = static_cast<std::uint16_t>(protocol_v1::FrameFlag::kEpochStart);
      completed.payload_bytes_written = payload.size;
      assert(pipeline.finishFill(begun.handle, completed).ok());
      assert(pipeline.serviceReadyFrames(1).frames_promoted == 1);
      auto raw = pipeline.frontFrame();
      protocol::DecodedFrame decoded;
      assert(raw.size == 4096 && protocol::decodeFrame(raw, decoded).ok());
      assert(raw.data[4] == 2);
      pipeline.releaseFrontFrame();
      pipeline.stopProduction();
    }
  }
  // Record length and wire length must agree at ownership/transport boundaries.
  start(pipeline, raw_run_id);
  acquired = pipeline.beginFill(packet::Stream::kGpio);
  assert(acquired.ok()); finish(pipeline, acquired.handle, 0);
  assert(pipeline.serviceReadyFrames(1).frames_promoted == 1);
  packet::PacketBufferPipelineTestAccess::corruptSelectedLength(pipeline);
  assert(pipeline.frontFrame().size == 0);
  assert(!pipeline.prepareFrontFrame());

}
