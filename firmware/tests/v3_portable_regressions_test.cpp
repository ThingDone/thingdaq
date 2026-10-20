// Reuse the CDC fake, logical-capacity seam and short-write scheduler.
#define main legacy_pressure_regressions_main
#include "pressure_recovery_test.cpp"
#undef main
#include <cassert>
#include "deferred_codec.h"
#include "runtime_timing.h"

namespace {
namespace v3 = thingdaq::protocol_v3;
namespace codec = thingdaq::deferred_codec;
using Bytes = std::vector<std::uint8_t>;

void fixedClockSettingsAndTiming() {
  namespace td = thingdaq;
  // This harness represents only the normal board. Historical build variants
  // and generic application rollback remain in their existing separate suites.
  static_assert(td::input_experiment::kCpuHz == 600000000U);
  td::control::ControlState state;
  assert(state.completeBoot(12345678U));
  wire::Request request{};
  request.protocol_version = 3U;
  request.kind = constants::CommandKind::kConfigure;
  wire::ControlFrame response;
  const auto baseline = td::variable_rate::derive(
      td::protocol_v2::RateProfile::kAdc1mhzGpio1mhz);
  assert(baseline.ok());
  unsigned accepted = 0U;
  for (const auto& bytes : v3::kSelectableConfigurations) {
    const auto selected = td::settings::record(bytes);
    if (selected[v3::kSettingsCpuProfileOffset] !=
        static_cast<unsigned>(v3::CpuProfile::kCpu600mhz)) continue;
    ++accepted;
    request.settings = selected;
    ++request.request_id;
    assert(state.dispatch(request, response).commandAccepted());
    const auto applied = state.activeSettings();
    assert(applied.settings == selected);
    const auto timing = td::runtime_timing::project(applied.settings);
    assert(timing.ok() && timing.schedule == baseline.schedule);
    assert(timing.wire_clocks == applied.clocks);
    assert(timing.cpu.cpu_hz == 600000000U && timing.cpu.ipg_hz == 150000000U);
    assert(timing.cpu.timestamp_hz == 8000000U);
    assert(timing.schedule.adc_pair_rate_hz == 1000000U);
    assert(timing.schedule.gpio_sample_rate_hz == 1000000U);
    assert(timing.schedule.adc_pair_period_ticks == 8U);
    assert(timing.schedule.gpio_sample_period_ticks == 8U);
    assert(timing.schedule.adc1_phase_ticks == 4U);
    // Both diagnostic entry points must use the same compiled CPU/PIT clocks,
    // regardless of stream mask, source, GPIO width, or either codec policy.
    for (auto rate : {1000U, 1000000U, 4000000U}) {
      wire::GpioClockDiagnosticRequest diagnostic{};
      diagnostic.rate_hz = rate;
      diagnostic.event_count = 32U;
      const auto plan = td::gpio_clock::makePlan(diagnostic);
      const auto projected = td::gpio_clock::makePlan(diagnostic, timing.cpu.id);
      assert(plan.pit_divisor == 24000000U / rate);
      assert(plan.pit_load_value == projected.pit_load_value);
      assert(plan.cycles_per_event == 600000000U / rate);
      assert(plan.measurement_cycles == 32U * (600000000U / rate));
      assert(plan.cycles_per_event == projected.cycles_per_event);
      assert(plan.measurement_cycles == projected.measurement_cycles);
    }
    const auto generation = state.statistics().generation();
    const auto configuration = state.appliedConfiguration();
    const auto device_state = state.state();
    const auto has_configuration = state.hasConfiguration();
    assert(state.takePendingEvents().mask == 0U);
    // Known RAW-only historical tuples must still be rejected after EVERY
    // valid selection, including compressed selections and either GPIO width.
    for (const auto& unsupported : v3::kSelectableConfigurations) {
      if (unsupported[v3::kSettingsCpuProfileOffset] !=
          static_cast<unsigned>(v3::CpuProfile::kCpu450mhz)) continue;
      request.settings = td::settings::record(unsupported);
      ++request.request_id;
      assert(state.dispatch(request, response).command_error ==
             constants::ErrorCode::kUnsupportedConfiguration);
      assert(state.activeSettings().settings == applied.settings);
      assert(state.activeSettings().clocks == applied.clocks);
      const auto after = state.appliedConfiguration();
      assert(after.public_settings == configuration.public_settings);
      assert(after.stream_mask == configuration.stream_mask);
      assert(after.source == configuration.source);
      assert(after.data_checksum_algorithm == configuration.data_checksum_algorithm);
      assert(after.data_frame_bytes == configuration.data_frame_bytes);
      assert(after.aux_bank_mode == configuration.aux_bank_mode);
      assert(after.rate_profile == configuration.rate_profile);
      assert(after.protocol_version == configuration.protocol_version);
      assert(after.legacy_v2 == configuration.legacy_v2);
      assert(state.hasConfiguration() == has_configuration);
      assert(state.negotiatedVersion() == 3U && state.state() == device_state);
      assert(state.runId() == 0U && state.statistics().generation() == generation);
      assert(state.takePendingEvents().mask == 0U);
    }
  }
  assert(accepted == 48U);
}

thingdaq::stream_layout::RunLayout publicLayout(unsigned width, bool compressed,
                                               unsigned count = 12U) {
  auto selected = thingdaq::settings::kBoardDefaults;
  selected[v3::kSettingsAuxBankModeOffset] = width == 16U ? 1U : 0U;
  selected[v3::kSettingsGpioWidthBitsOffset] = static_cast<std::uint8_t>(width);
  selected[v3::kSettingsGpioPolicyOffset] = compressed ? 1U : 0U;
  selected[v3::kSettingsAdcPolicyOffset] = compressed ? 1U : 0U;
  const auto result = thingdaq::stream_layout::publicV3(selected, count, count);
  assert(result.ok());
  return result.layout;
}

// Contract oracle: explicit wire offsets and deliberately simple Adler-32.
// No firmware serializer, codec, decoder, checksum or generated fixture is used.
Bytes expectedFrame(packet::Stream source, unsigned width, unsigned encoding,
                    unsigned count, unsigned runs, const Bytes &body) {
  Bytes out(60U + body.size(), 0U);
  wire::MutableByteView view{out.data(), out.size()};
  assert(wire::storeU32(view, 0U, 0xDEADBEEFU));
  out[4] = 3U; out[5] = source == packet::Stream::kAdc ? 1U : 2U;
  out[6] = 4U; out[8] = 44U; out[10] = 1U;
  assert(wire::storeU32(view, 12U, static_cast<std::uint32_t>(out.size())));
  assert(wire::storeU32(view, 16U, static_cast<std::uint32_t>(body.size() + 12U)));
  assert(wire::storeU32(view, 20U, 1U));
  assert(wire::storeU32(view, 40U, count));
  out[44] = static_cast<std::uint8_t>(encoding);
  out[45] = static_cast<std::uint8_t>(width);
  assert(wire::storeU32(view, 48U, count * width));
  assert(wire::storeU32(view, 52U, runs));
  std::copy(body.begin(), body.end(), out.begin() + 56);
  std::uint32_t a = 1U, b = 0U;
  for (std::size_t i = 0; i < out.size() - 4U; ++i) {
    a = (a + out[i]) % 65521U; b = (b + a) % 65521U;
  }
  assert(wire::storeU32(view, out.size() - 4U, (b << 16U) | a));
  return out;
}

packet::FillHandle submit(packet::PacketBufferPipeline &pipeline,
                          packet::Stream source, const Bytes &input) {
  const auto begun = pipeline.beginFill(source);
  assert(begun.ok());
  const auto view = pipeline.writablePayload(begun.handle);
  assert(view.size == input.size());
  std::copy(input.begin(), input.end(), view.data);
  packet::FrameCompletion completion;
  completion.payload_bytes_written = input.size();
  completion.first_sample_ticks = begun.handle.sequence *
      pipeline.streamLayout(source).coverage_ticks;
  completion.flags = begun.handle.sequence == 0U ? 4U : 0U;
  assert(pipeline.finishFill(begun.handle, completion).ok());
  assert(pipeline.writablePayload(begun.handle).size == 0U);
  assert(!pipeline.cancelFill(begun.handle));
  assert(pipeline.finishFill(begun.handle, completion).status == packet::OperationStatus::kInvalidHandle);
  return begun.handle;
}

void drainPublic(packet::PacketBufferPipeline &pipeline, usb::CdcTransport &transport) {
  for (unsigned visit = 0; visit < 10000U && !pipeline.quiescent(); ++visit) {
    pipeline.serviceDeferred(100U);
    pipeline.serviceReadyFrames();
    transport.serviceTransmit();
  }
  assert(pipeline.quiescent() && !transport.hasPendingTransmission());
}

void bytesAndShortWrites() {
  for (auto width : {8U, 16U}) for (bool compressed : {false, true})
    for (auto source : {packet::Stream::kAdc, packet::Stream::kGpio})
      for (unsigned pattern = 0; pattern < 3U; ++pattern) {
        const unsigned item_bytes = source == packet::Stream::kAdc ? 4U : width / 8U;
        Bytes raw, encoded;
        unsigned encoding = 0U, runs = 0U;
        if (source == packet::Stream::kAdc) {
          // (0,4095), (4095,0), (0x123,0xABC), (0x800,0x7FF).
          const Bytes edges{0,0,255,15, 255,15,0,0, 35,1,188,10, 0,8,255,7};
          const Bytes packed{0,240,255, 255,15,0, 35,193,171, 0,248,127};
          for (unsigned repeat = 0; repeat < 3U; ++repeat) {
            append(raw, edges); append(encoded, compressed ? packed : edges);
          }
          encoding = compressed ? 2U : 0U;
        } else {
          // Profitable, incompressible, exact byte-count tie at both widths.
          const auto span = pattern == 0U ? 12U : pattern == 1U ? 1U :
              (width == 8U ? 3U : 2U);
          for (unsigned i = 0; i < 12U; ++i) {
            raw.push_back(static_cast<std::uint8_t>(i / span));
            if (width == 16U) raw.push_back(0xABU);
          }
          if (compressed && pattern == 0U) {
            encoding = 1U; runs = 1U; encoded = {12U, 0U, 0U};
            if (width == 16U) encoded.push_back(0xABU);
          } else encoded = raw;
        }
        const auto expected = expectedFrame(source, item_bytes, encoding, 12U, runs, encoded);
        assert(wire::validV3DataView({expected.data(), expected.size()}));
        // Every possible accepted prefix, including zero and trailer splits.
        for (std::size_t offset = 0; offset < expected.size(); ++offset) {
          packet::OwnedPacketBufferStorage storage;
          packet::PacketBufferPipeline pipeline(storage);
          assert(pipeline.startRun(1U, constants::kDefaultChecksumAlgorithm,
              packet::streamBit(source), publicLayout(width, compressed)) == packet::OperationStatus::kOk);
          submit(pipeline, source, raw);
          pipeline.serviceDeferred(0U);
          pipeline.serviceReadyFrames();
          FakeCdcStream stream;
          scheduleExactPrefix(stream, offset);
          stats::Statistics statistics;
          usb::CdcTransport transport(stream, statistics, &pipeline);
          const auto report = transport.serviceTransmit();
          assert(report.stalled && stream.output.size() == offset);
          assert(std::equal(stream.output.begin(), stream.output.end(), expected.begin()));
          // A control reply can overtake only a frame with zero accepted bytes.
          const auto reply = pingResponse(7U, 1U);
          assert(transport.queueResponse(reply));
          pipeline.stopProduction();
          assert(pipeline.startRun(2U) == packet::OperationStatus::kTransmissionPending);
          drainPublic(pipeline, transport);
          Bytes expected_output;
          if (offset == 0U) append(expected_output, bytes(reply));
          append(expected_output, expected);
          if (offset != 0U) append(expected_output, bytes(reply));
          assert(stream.output == expected_output);
          const auto counters = pipeline.sourceCounters(source);
          assert(counters.items_transmitted == 12U && counters.frames_dropped == 0U);
          assert(counters.wire_bytes_transmitted == expected.size());
          assert(codec::counters[packet::streamIndex(source)].completed == (compressed ? 1U : 0U));
        }
      }
}

void malformedShapes() {
  // Independent RAW/PACK12/RLE specimens, never generated by the producer.
  for (auto source : {packet::Stream::kAdc, packet::Stream::kGpio})
    for (unsigned width : {1U, 2U, 4U}) for (unsigned encoding : {0U, 1U, 2U}) {
      const bool adc = source == packet::Stream::kAdc;
      if ((adc && width != 4U) || (!adc && width == 4U) ||
          (encoding == 1U && adc) || (encoding == 2U && !adc)) continue;
      Bytes body(encoding == 1U ? width + 2U : 12U * (encoding == 2U ? 3U : width), 0U);
      if (encoding == 1U) body[0] = 12U;
      const auto valid = expectedFrame(source, width, encoding, 12U, encoding == 1U ? 1U : 0U, body);
      assert(wire::validV3DataView({valid.data(), valid.size()}));
      for (std::size_t size = 0; size < valid.size(); ++size)
        assert(!wire::validV3DataView({valid.data(), size}));
      for (const auto offset : {0U,4U,5U,8U,10U,11U,12U,16U,28U,40U,44U,45U,46U,47U,48U,52U}) {
        auto bad = valid; bad[offset] ^= 0x80U;
        assert(!wire::validV3DataView({bad.data(), bad.size()}));
      }
      for (auto flags : {8U,16U,128U}) {
        auto bad = valid; bad[6] = static_cast<std::uint8_t>(flags);
        assert(!wire::validV3DataView({bad.data(), bad.size()}));
      }
      for (auto ticks : {1ULL, 0xFFFFFFFFFFFFFFF8ULL}) {
        auto bad = valid;
        assert(wire::storeU64({bad.data(), bad.size()}, 32U, ticks));
        assert(!wire::validV3DataView({bad.data(), bad.size()}));
      }
      for (auto offset : {20U,40U}) {
        auto bad = valid;
        assert(wire::storeU32({bad.data(), bad.size()}, offset, 0U));
        assert(!wire::validV3DataView({bad.data(), bad.size()}));
      }
    }
  // Equal-size and larger RLE frames must never reach transport.
  for (unsigned width : {1U, 2U}) for (unsigned runs : {12U / (width + 2U) * width, 12U}) {
    const auto bad = expectedFrame(packet::Stream::kGpio, width, 1U, 12U, runs, Bytes(runs * (width + 2U)));
    assert(!wire::validV3DataView({bad.data(), bad.size()}));
  }
}

void pressureAndTails() {
  for (auto width : {8U, 16U}) for (bool compressed : {false, true})
    for (auto source : {packet::Stream::kAdc, packet::Stream::kGpio}) {
      packet::OwnedPacketBufferStorage storage;
      packet::PacketBufferPipeline pipeline(storage);
      assert(pipeline.startRun(1U, constants::kDefaultChecksumAlgorithm,
          packet::streamBit(source), publicLayout(width, compressed)) == packet::OperationStatus::kOk);
      assert(packet::PacketBufferPipelineTestAccess::installLogicalCapacity(pipeline, 4U));
      const Bytes raw(source == packet::Stream::kAdc ? 48U : 12U * width / 8U, 0U);
      FakeCdcStream stream;
      stats::Statistics statistics;
      usb::CdcTransport transport(stream, statistics, &pipeline);
      submit(pipeline, source, raw); pipeline.serviceDeferred(0U); pipeline.serviceReadyFrames();
      assert(pipeline.prepareFrontFrame());
      const auto front = pipeline.frontFrame();
      const Bytes pinned(front.data, front.data + front.size);
      scheduleExactPrefix(stream, 1U);
      assert(transport.serviceTransmit().bytes_written == 1U);
      // More arrivals than storage: producer admission may evict an unsent page,
      // but never the page already accepted by USB or an incomplete owner.
      for (unsigned i = 1U; i < 20U; ++i) {
        auto incoming = raw;
        if (source == packet::Stream::kGpio && i % 2U != 0U)
          for (unsigned item = 0U; item < 12U; ++item)
            incoming[item * width / 8U] = static_cast<std::uint8_t>(item);
        submit(pipeline, source, incoming); pipeline.serviceDeferred(0U); pipeline.serviceReadyFrames();
        assert(Bytes(front.data, front.data + front.size) == pinned);
      }
      assert(pipeline.snapshot().pressure_evictions > 0U);
      assert(packet::PacketBufferPipelineTestAccess::releaseLogicalCapacity(pipeline, 4U));
      const auto incomplete = pipeline.beginFill(source).handle;
      submit(pipeline, source, raw); // complete deferred STOP tail
      const auto stopped = pipeline.stopProduction();
      assert(stopped.filling_frames_canceled == 1U);
      assert(pipeline.writablePayload(incomplete).size == 0U);
      drainPublic(pipeline, transport);
      assert(std::equal(pinned.begin(), pinned.end(), stream.output.begin()));
      const auto counters = pipeline.sourceCounters(source);
      assert(counters.frames_produced == 22U);
      assert(counters.frames_transmitted + counters.frames_dropped == 22U);
      assert(counters.items_transmitted + counters.items_dropped == 264U);
      assert(counters.wire_bytes_transmitted == stream.output.size());
      std::size_t at = 0U;
      std::uint32_t next = 0U;
      while (at < stream.output.size()) {
        wire::ByteView view{stream.output.data() + at, stream.output.size() - at};
        std::uint32_t length = 0U, sequence = 0U; std::uint64_t ticks = 0U;
        assert(wire::loadU32(view, 12U, length) && length <= view.size);
        assert(wire::validV3DataView({view.data, length}));
        assert(wire::loadU32(view, 24U, sequence) && sequence >= next);
        assert(wire::loadU64(view, 32U, ticks) && ticks == sequence * 96ULL);
        assert(((view.data[6] & 10U) == 10U) == (sequence != next));
        next = sequence + 1U; at += length;
      }
      assert(next == 22U); // gap for canceled producer is followed by the STOP tail
    }
}

void invalidLeasesAndDeadlines() {
  for (auto width : {8U, 16U}) for (auto source : {packet::Stream::kAdc, packet::Stream::kGpio}) {
    packet::OwnedPacketBufferStorage storage;
    packet::PacketBufferPipeline pipeline(storage);
    assert(pipeline.startRun(1U, constants::kDefaultChecksumAlgorithm,
        packet::streamBit(source), publicLayout(width, true)) == packet::OperationStatus::kOk);
    const auto live = pipeline.beginFill(source).handle;
    for (unsigned index = static_cast<unsigned>(board::kPacketBufferCount); index <= 255U; ++index) {
      auto bad = live; bad.buffer_index = static_cast<std::uint8_t>(index);
      assert(pipeline.writablePayload(bad).size == 0U && !pipeline.cancelFill(bad));
      assert(pipeline.finishFill(bad, {}).status == packet::OperationStatus::kInvalidHandle);
    }
    assert(pipeline.cancelFill(live));
    const Bytes raw(source == packet::Stream::kAdc ? 48U : 12U * width / 8U, 0U);
    pipeline.setDeferredClock(0xFFFFFF00ULL);
    submit(pipeline, source, raw); submit(pipeline, source, raw);
    pipeline.serviceDeferred(0xFFFFFF00ULL + 79999U, 0U);
    const auto slot = packet::streamIndex(source);
    assert(codec::counters[slot].completed == 0U && codec::counters[slot].deadline_drops == 0U);
    pipeline.serviceDeferred(0xFFFFFF00ULL + 80000U, 0U);
    pipeline.serviceDeferred(0xFFFFFF00ULL + 80000U, 0U);
    assert(codec::counters[slot].deadline_drops == 2U);
    pipeline.setDeferredClock(100U);
    submit(pipeline, source, raw);
    std::vector<packet::FillHandle> held;
    while (pipeline.freeBuffers()) held.push_back(pipeline.beginFill(source).handle);
    pipeline.serviceDeferred(100U);
    // PACK12 is in-place; RLE needs a disjoint free page. Full-pool behavior
    // must preserve that distinction instead of treating both as allocation failures.
    assert(codec::counters[slot].resource_drops == (source == packet::Stream::kGpio ? 1U : 0U));
    assert(codec::counters[slot].completed == (source == packet::Stream::kAdc ? 1U : 0U));
    for (auto handle : held) assert(pipeline.cancelFill(handle));
    pipeline.stopProduction();
    FakeCdcStream stream;
    stats::Statistics statistics;
    usb::CdcTransport transport(stream, statistics, &pipeline);
    drainPublic(pipeline, transport);
    assert(pipeline.quiescent());
    const auto counters = pipeline.sourceCounters(source);
    assert(counters.frames_produced == counters.frames_dropped + counters.frames_transmitted);
    assert(pipeline.startRun(2U, constants::kDefaultChecksumAlgorithm,
        packet::streamBit(source), publicLayout(width, true)) == packet::OperationStatus::kOk);
    pipeline.setDeferredClock(0U);
    submit(pipeline, source, raw);
    std::uint64_t clock = 0U;
    const auto late = [](void *context) -> std::uint64_t {
      auto &ticks = *static_cast<std::uint64_t *>(context);
      const auto result = ticks; ticks += 80000U; return result;
    };
    pipeline.serviceDeferred(0U, 1U, late, &clock);
    assert(codec::counters[slot].deadline_drops == 1U && codec::counters[slot].completed == 0U);
    assert(codec::counters[slot].work_ticks == 80000U && codec::counters[slot].max_work_ticks == 80000U);
    pipeline.stopProduction();
    assert(pipeline.quiescent() && pipeline.sourceCounters(source).frames_dropped == 1U);
  }
  packet::OwnedPacketBufferStorage storage;
  packet::PacketBufferPipeline pipeline(storage);
  assert(pipeline.startRun(1U, constants::kDefaultChecksumAlgorithm,
      packet::kAllStreamMask, publicLayout(16U, true)) == packet::OperationStatus::kOk);
  submit(pipeline, packet::Stream::kAdc, Bytes(48U));
  submit(pipeline, packet::Stream::kGpio, Bytes(24U));
  pipeline.serviceDeferred(0U, 0U);
  assert(codec::counters[0].completed + codec::counters[1].completed == 0U);
  pipeline.serviceDeferred(0U, 100U);
  assert(codec::counters[0].completed + codec::counters[1].completed == 1U);
  pipeline.serviceDeferred(0U, 100U);
  assert(codec::counters[0].completed == 1U && codec::counters[1].completed == 1U);
  pipeline.stopProduction();
  FakeCdcStream stream;
  stats::Statistics statistics;
  usb::CdcTransport transport(stream, statistics, &pipeline);
  drainPublic(pipeline, transport);
}

void maximumCountsAndRejectedPayloads() {
  for (auto width : {8U, 16U}) for (bool compressed : {false, true})
    for (auto source : {packet::Stream::kAdc, packet::Stream::kGpio}) {
      const bool adc = source == packet::Stream::kAdc;
      const unsigned count = adc ? 1009U : width == 8U ? 4036U : 2018U;
      const unsigned item_bytes = adc ? 4U : width / 8U;
      auto selected = publicLayout(width, compressed);
      auto settings = thingdaq::settings::kBoardDefaults;
      settings[6] = width == 16U ? 1U : 0U;
      settings[7] = static_cast<std::uint8_t>(width);
      settings[8] = compressed ? 1U : 0U; settings[9] = compressed ? 1U : 0U;
      const auto maximum = thingdaq::stream_layout::publicV3(settings, adc ? count : 12U, adc ? 12U : count);
      assert(maximum.ok()); selected = maximum.layout;
      assert(!thingdaq::stream_layout::publicV3(settings, adc ? count + 1U : 12U, adc ? 12U : count + 1U).ok());
      packet::OwnedPacketBufferStorage storage;
      packet::PacketBufferPipeline pipeline(storage);
      assert(pipeline.startRun(1U, constants::kDefaultChecksumAlgorithm,
          packet::streamBit(source), selected) == packet::OperationStatus::kOk);
      const Bytes raw(count * item_bytes, 0U);
      Bytes encoded = compressed && adc ? Bytes(count * 3U, 0U) : raw;
      if (compressed && !adc) {
        encoded = {static_cast<std::uint8_t>(count), static_cast<std::uint8_t>(count >> 8U), 0U};
        if (width == 16U) encoded.push_back(0U);
      }
      const auto expected = expectedFrame(source, item_bytes, compressed ? (adc ? 2U : 1U) : 0U,
          count, compressed && !adc ? 1U : 0U, encoded);
      submit(pipeline, source, raw);
      pipeline.stopProduction();
      FakeCdcStream stream; stream.max_write_size = 7U;
      stats::Statistics statistics;
      usb::CdcTransport transport(stream, statistics, &pipeline);
      drainPublic(pipeline, transport);
      assert(stream.output == expected && pipeline.sourceCounters(source).items_transmitted == count);
      assert(expected.size() <= 4096U);

      assert(pipeline.startRun(2U, constants::kDefaultChecksumAlgorithm,
          packet::streamBit(source), selected) == packet::OperationStatus::kOk);
      // Length and checksum policy rejection must retire the producer lease
      // exactly once and leave no malformed frame queued for USB.
      for (unsigned defect = 0U; defect < (adc ? 7U : 3U); ++defect) {
        const auto handle = pipeline.beginFill(source).handle;
        const auto view = pipeline.writablePayload(handle);
        std::fill_n(view.data, view.size, std::uint8_t{0U});
        packet::FrameCompletion completion;
        completion.payload_bytes_written = view.size;
        if (defect == 0U) --completion.payload_bytes_written;
        if (defect == 1U) ++completion.payload_bytes_written;
        if (defect == 2U) completion.checksum_algorithm = static_cast<constants::ChecksumAlgorithm>(2U);
        if (defect >= 3U) {
          const auto index = defect < 5U ? defect - 3U : count * 2U - (defect - 4U);
          assert(wire::storeU16(view, index * 2U, defect % 2U ? 0x1000U : 0xFFFFU));
        }
        const auto result = pipeline.finishFill(handle, completion);
        assert(result.status == (defect < 2U ? packet::OperationStatus::kIncompletePayload :
            defect == 2U ? packet::OperationStatus::kChecksumMismatch : packet::OperationStatus::kEncodingRejected));
        assert(pipeline.writablePayload(handle).size == 0U && !pipeline.cancelFill(handle));
        assert(pipeline.sourceCounters(source).frames_dropped == defect + 1U);
      }
      pipeline.stopProduction();
      assert(pipeline.quiescent());
    }
}
} // namespace

int main(int argc, char **argv) {
  assert(argc == 2);
  const std::string test = argv[1];
  if (test == "bytes") bytesAndShortWrites();
  else if (test == "shapes") malformedShapes();
  else if (test == "pressure") pressureAndTails();
  else if (test == "leases") invalidLeasesAndDeadlines();
  else if (test == "maximum") maximumCountsAndRejectedPayloads();
  else if (test == "fixed-clock") fixedClockSettingsAndTiming();
  else assert(false);
  return failures == 0 ? 0 : 1;
}
