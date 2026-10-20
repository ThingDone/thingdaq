#pragma once

#include "adc_initializer.h"
#include "adc_trigger.h"
#include "variable_rate_scheduler.h"

namespace thingdaq::runtime_timing {

// A value projection, never mutable global active state. A hardware owner may
// publish it only after applying and verifying the complete selected tuple.
struct Projection {
  variable_rate::Status status = variable_rate::Status::kUnsupportedRatePair;
  board_profile::Cpu cpu{};
  variable_rate::Schedule schedule{};
  settings::Clocks wire_clocks{};
  std::uint32_t completion_tolerance_cycles = 0U;
  std::uint32_t calibration_deadline_cycles = 0U;
  std::uint32_t diagnostic_deadline_cycles = 0U;
  std::uint32_t stop_deadline_cycles = 0U;
  std::uint32_t dma_alignment_cycles = 0U;

  constexpr bool ok() const { return status == variable_rate::Status::kOk; }

  adc::Settings adcSettings(const adc::ResolutionGate& gate = {}) const {
    auto value = adc::settingsFor(gate);
    value.ipg_clock_hz = cpu.ipg_hz;
    value.adc_clock_hz = cpu.adc_hz;
    return value;
  }

  adc_trigger::Snapshot triggerSnapshot() const {
    adc_trigger::Snapshot value{};
    value.pit_clock_hz = cpu.pit_hz;
    value.dwt_clock_hz = cpu.cpu_hz;
    value.ipg_clock_hz = cpu.ipg_hz;
    value.gpio_master_rate_hz = schedule.gpio_sample_rate_hz;
    value.pair_rate_hz = schedule.adc_pair_rate_hz;
    // Exact public tuples use loads 23/0, which fit the legacy diagnostic
    // fields. The general scheduler retains 16-bit loads for historical rates.
    value.gpio_master_pit_load =
        static_cast<std::uint8_t>(schedule.gpio_master_pit_load);
    value.pair_pit_load =
        static_cast<std::uint8_t>(schedule.adc_pair_pit_load);
    value.predivider = schedule.adc_etc_predivider;
    value.chain_length = schedule.adc_etc_chain_length;
    value.initial_delays = {schedule.adc0_initial_delay, schedule.adc1_initial_delay};
    value.effective_delays = {schedule.adc0_effective_delay, schedule.adc1_effective_delay};
    value.phase_ipg_cycles = schedule.adc1_phase_ipg_cycles;
    value.completion_expected_delta_cycles = schedule.completion_expected_dwt_cycles;
    value.completion_tolerance_cycles = completion_tolerance_cycles;
    // Readiness/evidence stays clear until measured by the hardware owner.
    return value;
  }
};

inline Projection project(const settings::Record& selected) {
  Projection value{};
  const auto derived = variable_rate::derive(selected);
  value.status = derived.status;
  if (!derived.ok()) return value;
  const auto id = selected[protocol_v3::kSettingsCpuProfileOffset];
  value.cpu = board_profile::cpuFor(static_cast<protocol_v3::CpuProfile>(id));
  value.schedule = derived.schedule;
  value.wire_clocks = settings::clocksFor(id);
  // Preserve the existing 200 ns completion tolerance and real-time deadlines.
  // Use the frozen contract as a duration reference, not the build's DWT rate.
  value.completion_tolerance_cycles = static_cast<std::uint32_t>(
      static_cast<std::uint64_t>(protocol_v1::kAdcCompletionToleranceDwtCycles) *
      value.cpu.cpu_hz / protocol_v1::kAdcTriggerDwtClockHz);
  value.calibration_deadline_cycles = (value.cpu.cpu_hz / 1000000U) *
      protocol_v1::kAdcCalibrationDeadlineUs;
  value.diagnostic_deadline_cycles = (value.cpu.cpu_hz / 1000000U) *
      protocol_v1::kAdcTriggerDiagnosticDeadlineUs;
  value.stop_deadline_cycles = (value.cpu.cpu_hz / 1000000U) * 10000U;
  value.dma_alignment_cycles = (value.cpu.cpu_hz / 1000000U) * 10U;
  return value;
}

}  // namespace thingdaq::runtime_timing
