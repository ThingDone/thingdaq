#include <algorithm>
#include <cassert>
#include "packet_buffer_pipeline.h"
#include "variable_rate_scheduler.h"
#include "firmware_identity.h"
#include "gpio_clock_diagnostic.h"

namespace td = thingdaq;
int main() {
  assert(td::identity::kExpectedCpuHz == THINGDAQ_EXPERIMENT_CPU_HZ);
  const td::protocol::GpioClockDiagnosticRequest clock_request{};
  const auto clock_plan = td::gpio_clock::makePlan(clock_request);
  assert(clock_plan.measurement_cycles ==
      static_cast<std::uint64_t>(clock_request.event_count) *
      THINGDAQ_EXPERIMENT_CPU_HZ / clock_request.rate_hz);
  assert(clock_plan.cycles_per_event ==
      (THINGDAQ_EXPERIMENT_CPU_HZ + clock_request.rate_hz - 1U) / clock_request.rate_hz);
  td::protocol::Request request;
  request.kind = td::protocol_v1::CommandKind::kGpioClockDiagnostic;
  request.request_id = 1U;
  request.gpio_clock_diagnostic = clock_request;
  td::protocol::GpioClockDiagnosticResponse response;
  response.configured_rate_hz = clock_request.rate_hz;
  response.pit_load_value = clock_plan.pit_load_value;
  response.requested_event_count = clock_request.event_count;
  response.scheduled_event_count = clock_request.event_count;
  response.dma_sample_count = clock_request.event_count;
  response.dwt_counter_hz = THINGDAQ_EXPERIMENT_CPU_HZ;
  response.dwt_elapsed_cycles = clock_plan.measurement_cycles;
  response.tcd_biter = clock_plan.tcd_major_count;
  response.tcd_citer_final = clock_plan.tcd_major_count - clock_request.event_count;
  td::protocol::ControlFrame encoded;
  assert(td::protocol::encodeGpioClockDiagnosticResponse(request, 0U, response, encoded).ok());
  for (const auto &timing : td::rate_profile::kTimings) {
    const unsigned ratio = timing.profile == td::protocol_v2::RateProfile::kAdc1mhzGpio1mhz
        ? 1U : td::input_experiment::kGpioRateMultiplier;
    const unsigned weight = 4U / ratio;
    auto derived = td::variable_rate::derive(timing.profile);
    assert(derived.ok());
    assert(derived.schedule.clocks.dwt_hz == THINGDAQ_EXPERIMENT_CPU_HZ);
    assert(derived.schedule.clocks.ipg_hz == 150000000U);
    assert(derived.schedule.adc1_phase_ipg_cycles ==
           150000000U / (2U * timing.adc_pair_rate_hz));
    assert(timing.gpio_sample_rate_hz == timing.adc_pair_rate_hz *
           ratio);
    assert(timing.adc_pair_pit_divider == ratio);
    for (auto mode : {td::protocol_v2::AuxBankMode::kDisabled,
                      td::protocol_v2::AuxBankMode::kInput}) {
      auto layout = td::stream_layout::experimental(mode, timing.profile);
      assert(layout.ok());
      assert(layout.layout.streams[1].coverage_ticks ==
             layout.layout.streams[0].coverage_ticks *
             weight);
      td::packet::OwnedPacketBufferStorage storage;
      td::packet::PacketBufferPipeline pipeline(storage);
      assert(pipeline.startRun(1U, td::protocol_v1::kDefaultChecksumAlgorithm,
             td::packet::kAllStreamMask, layout.layout) == td::packet::OperationStatus::kOk);
      auto fill = [&](td::packet::Stream stream, unsigned sequence) {
        auto begun = pipeline.beginFill(stream);
        assert(begun.ok());
        auto payload = pipeline.writablePayload(begun.handle);
        std::fill(payload.data, payload.data + payload.size, 0U);
        td::packet::FrameCompletion completion;
        completion.payload_bytes_written = payload.size;
        completion.first_sample_ticks = sequence *
            layout.layout.streams[static_cast<unsigned>(stream)].coverage_ticks;
        completion.flags = sequence == 0U ?
            static_cast<std::uint16_t>(td::protocol_v1::FrameFlag::kEpochStart) : 0U;
        assert(pipeline.finishFill(begun.handle, completion).ok());
      };
      // An ADC-only burst is bounded at one GPIO frame's time coverage.
      for (unsigned i = 0; i < weight + 1U; ++i) fill(td::packet::Stream::kAdc, i);
      pipeline.serviceReadyFrames(20U);
      assert(pipeline.queuedFrames() == weight);
      assert(pipeline.readyFrames() == 1U);
      fill(td::packet::Stream::kGpio, 0U);
      pipeline.serviceReadyFrames(20U);
      assert(pipeline.queuedFrames() == weight + 2U);
      pipeline.stopProduction();
      pipeline.serviceReadyFrames(20U);
      while (pipeline.queuedFrames()) pipeline.releaseFrontFrame();
      assert(pipeline.quiescent());
    }
  }
}
