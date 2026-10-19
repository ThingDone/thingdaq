#include <algorithm>
#include <cassert>
#include "packet_buffer_pipeline.h"
#include "variable_rate_scheduler.h"
#include "firmware_identity.h"
#include "gpio_clock_diagnostic.h"
#include "adc_initializer.h"
#include "adc_trigger.h"
#include "runtime_timing.h"

namespace td = thingdaq;
namespace {
void testRuntimeProjection() {
  using namespace td::protocol_v3;
  std::array<unsigned, 3U> counts{};
  for (const auto& bytes : kSelectableConfigurations) {
    const auto selected = td::settings::record(bytes);
    const auto projected = td::runtime_timing::project(selected);
    assert(projected.ok());
    const auto id = selected[kSettingsCpuProfileOffset];
    ++counts[id];
    const unsigned cpu_hz = id == 1U ? 600000000U : 450000000U;
    assert(projected.cpu.cpu_hz == cpu_hz);
    assert(projected.cpu.ipg_hz == 150000000U);
    assert(projected.cpu.adc_hz == 37500000U);
    assert(projected.cpu.pit_hz == 24000000U);
    assert(projected.cpu.timestamp_hz == 8000000U);
    const auto& schedule = projected.schedule;
    assert(schedule.adc_pair_rate_hz == 1000000U);
    assert(schedule.gpio_sample_rate_hz == 1000000U);
    assert(schedule.adc_pair_period_ticks == 8U);
    assert(schedule.gpio_sample_period_ticks == 8U);
    assert(schedule.adc1_phase_ticks == 4U);
    assert(schedule.gpio_master_pit_divider == 24U);
    assert(schedule.gpio_master_pit_load == 23U);
    assert(schedule.adc_pair_pit_divider == 1U);
    assert(schedule.adc_pair_pit_load == 0U);
    assert(schedule.adc_etc_predivider == 0U);
    assert(schedule.adc_etc_chain_length == 1U);
    assert(schedule.adc0_initial_delay == 0U);
    assert(schedule.adc1_initial_delay == 75U);
    assert(schedule.adc0_effective_delay == 1U);
    assert(schedule.adc1_effective_delay == 76U);
    assert(schedule.completion_expected_dwt_cycles == (id == 1U ? 300U : 225U));
    assert(projected.completion_tolerance_cycles == (id == 1U ? 120U : 90U));
    assert(projected.calibration_deadline_cycles == cpu_hz / 100U);
    assert(projected.stop_deadline_cycles == cpu_hz / 100U);
    assert(projected.diagnostic_deadline_cycles == cpu_hz / 500U);
    assert(projected.dma_alignment_cycles == cpu_hz / 100000U);
    assert(projected.wire_clocks == td::settings::record(kCpuProfiles[id - 1U]));
    const auto adc = projected.adcSettings();
    assert(adc.ipg_clock_hz == 150000000U && adc.adc_clock_hz == 37500000U);
    assert(adc.resolution_bits == 12U && adc.clock_divider == 4U);
    const auto trigger = projected.triggerSnapshot();
    assert(!trigger.ready() && trigger.configuration_flags == 0U);
    assert(trigger.dwt_clock_hz == cpu_hz);
    assert(trigger.gpio_master_pit_load == 23U && trigger.pair_pit_load == 0U);
    assert(trigger.completion_expected_delta_cycles == (id == 1U ? 300U : 225U));
    assert(trigger.completion_tolerance_cycles == (id == 1U ? 120U : 90U));
    if (id == 2U) {
      assert(selected[kSettingsGpioPolicyOffset] == 0U);
      assert(selected[kSettingsAdcPolicyOffset] == 0U);
    }
    // Changing any byte outside the exact table cannot silently round a rate,
    // accept a reserved field, or enable a codec on an unlisted CPU.
    for (std::size_t i = 0U; i < selected.size(); ++i) {
      auto bad = selected;
      bad[i] = 255U;
      assert(!td::runtime_timing::project(bad).ok());
    }
  }
  assert(counts[1] == 48U && counts[2] == 12U);
  for (auto id : {CpuProfile::kCpu600mhz, CpuProfile::kCpu450mhz}) {
    const auto defaults = td::settings::defaultsFor(id);
    assert(td::settings::boardSupports(defaults));
    assert(defaults[kSettingsCpuProfileOffset] == static_cast<unsigned>(id));
    assert(defaults[kSettingsAdcPolicyOffset] == (id == CpuProfile::kCpu600mhz ? 1U : 0U));
    assert(defaults[kSettingsGpioPolicyOffset] == (id == CpuProfile::kCpu600mhz ? 1U : 0U));
    const auto projected = td::runtime_timing::project(defaults);
    assert(projected.ok());
    td::protocol::GpioClockDiagnosticRequest request{};
    request.rate_hz = 4000000U;
    request.event_count = 101U;
    const auto plan = td::gpio_clock::makePlan(request, id);
    assert(plan.pit_load_value == 5U);
    assert(plan.cycles_per_event == (id == CpuProfile::kCpu600mhz ? 150U : 113U));
    assert(plan.measurement_cycles == (id == CpuProfile::kCpu600mhz ? 15150U : 11363U));
    // Legacy derivation still rejects clocks that differ from the build.
    if (projected.cpu.cpu_hz != THINGDAQ_EXPERIMENT_CPU_HZ) {
      assert(td::variable_rate::derive(
          td::protocol_v2::RateProfile::kAdc1mhzGpio1mhz,
          projected.schedule.clocks).status == td::variable_rate::Status::kClockMismatch);
    }
  }
  assert(!td::board_profile::cpuFor(static_cast<CpuProfile>(3U)).valid());
  assert(td::board_profile::cpuIdForHz(528000000U) == 0U);
  assert(!td::board_profile::rateFor(static_cast<RateProfile>(0U)).valid());
  assert(!td::runtime_timing::project(td::settings::defaultsFor(static_cast<CpuProfile>(3U))).ok());
  assert(td::gpio_clock::makePlan({}, static_cast<CpuProfile>(3U)).rate_hz == 0U);
  auto compressed450 = td::settings::kBoardDefaults;
  compressed450[kSettingsCpuProfileOffset] = 2U;
  assert(!td::runtime_timing::project(compressed450).ok());
  const auto* legacy = td::rate_profile::legacyTimingFor(
      td::protocol_v2::RateProfile::kAdc1mhzGpio1mhz);
  assert(legacy->completion_expected_dwt_cycles == 300U);
  assert(legacy->adc1_phase_ipg_cycles == 75U);
  assert(legacy->input_frame_coverage_ticks == 4048U);
}
}  // namespace

int main() {
  testRuntimeProjection();
  assert(td::identity::kExpectedCpuHz == THINGDAQ_EXPERIMENT_CPU_HZ);
  constexpr unsigned ipg = THINGDAQ_EXPERIMENT_CPU_HZ == 528000000U ? 132000000U : 150000000U;
  const td::adc::Settings adc{};
  assert(adc.ipg_clock_hz == ipg);
  assert(adc.adc_clock_hz == ipg / 4U);
  assert(adc.resolution_bits == 12U);
  const td::adc_trigger::Snapshot trigger{};
  assert(trigger.phase_ipg_cycles == ipg / 2000000U);
  assert(trigger.initial_delays[1] == ipg / 2000000U);
  assert(trigger.effective_delays[1] == ipg / 2000000U + 1U);
  td::protocol::Request info_request{};
  info_request.kind = td::protocol_v1::CommandKind::kInfo;
  info_request.request_id = 1U;
  info_request.protocol_version = 2U;
  td::protocol::InfoResponse info{};
  info.supported_stream_mask = 3U;
  info.supported_source_mask = 3U;
  info.applied_configuration.protocol_version = 2U;
  info.applied_configuration.rate_profile = td::protocol_v2::RateProfile::kAdc1mhzGpio1mhz;
  td::protocol::ControlFrame info_frame{};
  assert(td::protocol::encodeInfoResponse(info_request, 0U, info, info_frame).ok());
  td::protocol::DecodedFrame decoded_info{};
  assert(td::protocol::decodeFrame(info_frame.view(), decoded_info).ok());
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
    assert(derived.schedule.clocks.ipg_hz == ipg);
    assert(derived.schedule.adc1_phase_ipg_cycles ==
           ipg / (2U * timing.adc_pair_rate_hz));
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
