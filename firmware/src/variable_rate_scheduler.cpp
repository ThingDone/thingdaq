#include "variable_rate_scheduler.h"

#include <limits>

#include "rate_profile_table.h"

#if defined(__IMXRT1062__)
#define THINGDAQ_VARIABLE_RATE_COLD_CODE(section_name) \
  __attribute__((section(section_name), noinline, noipa, used))
#else
#define THINGDAQ_VARIABLE_RATE_COLD_CODE(section_name)
#endif

namespace thingdaq::variable_rate {
namespace {

const protocol_v2::RateProfileTiming *timingFor(
    protocol_v2::RateProfile profile) {
  return rate_profile::timingFor(profile);
}

bool fitsU16(std::uint64_t value) {
  return value <= std::numeric_limits<std::uint16_t>::max();
}

bool fitsU32(std::uint64_t value) {
  return value <= std::numeric_limits<std::uint32_t>::max();
}

THINGDAQ_VARIABLE_RATE_COLD_CODE(".flashmem.variable_rate.derive_known")
DeriveResult deriveKnown(const protocol_v2::RateProfileTiming &timing,
                         ClockDomains clocks) {
  DeriveResult result{};
  result.schedule.profile = timing.profile;
  result.schedule.clocks = clocks;
  result.schedule.adc_pair_rate_hz = timing.adc_pair_rate_hz;
  result.schedule.gpio_sample_rate_hz = timing.gpio_sample_rate_hz;

  if (clocks != kContractClocks) {
    result.status = Status::kClockMismatch;
    return result;
  }
  if (timing.adc_pair_rate_hz == 0U ||
      timing.gpio_sample_rate_hz == 0U) {
    result.status = Status::kGeneratedContractMismatch;
    return result;
  }
  const std::uint64_t four_adc =
      static_cast<std::uint64_t>(timing.adc_pair_rate_hz) * 4U;
  if (!fitsU32(four_adc)) {
    result.status = Status::kArithmeticOverflow;
    return result;
  }
  if (four_adc != timing.gpio_sample_rate_hz) {
    result.status = Status::kInvalidFourToOneRatio;
    return result;
  }
  if (clocks.timestamp_hz % timing.adc_pair_rate_hz != 0U ||
      clocks.timestamp_hz % timing.gpio_sample_rate_hz != 0U ||
      clocks.pit_hz % timing.gpio_sample_rate_hz != 0U ||
      clocks.ipg_hz % timing.adc_pair_rate_hz != 0U ||
      clocks.dwt_hz % timing.adc_pair_rate_hz != 0U) {
    result.status = Status::kNonIntegralDivider;
    return result;
  }

  const std::uint64_t adc_period =
      clocks.timestamp_hz / timing.adc_pair_rate_hz;
  const std::uint64_t gpio_period =
      clocks.timestamp_hz / timing.gpio_sample_rate_hz;
  const std::uint64_t pit0_divider =
      clocks.pit_hz / timing.gpio_sample_rate_hz;
  const std::uint64_t pit1_divider =
      timing.gpio_sample_rate_hz / timing.adc_pair_rate_hz;
  if ((adc_period & 1U) != 0U ||
      clocks.ipg_hz % (2U * timing.adc_pair_rate_hz) != 0U ||
      clocks.dwt_hz % (2U * timing.adc_pair_rate_hz) != 0U) {
    result.status = Status::kNonIntegralDivider;
    return result;
  }
  const std::uint64_t phase_ticks = adc_period / 2U;
  const std::uint64_t phase_ipg =
      clocks.ipg_hz / (2U * timing.adc_pair_rate_hz);
  const std::uint64_t expected_dwt =
      clocks.dwt_hz / (2U * timing.adc_pair_rate_hz);
  if (pit0_divider == 0U || pit1_divider == 0U ||
      !fitsU16(adc_period) || !fitsU16(gpio_period) ||
      !fitsU16(phase_ticks) || !fitsU16(pit0_divider) ||
      !fitsU16(pit0_divider - 1U) || !fitsU16(pit1_divider) ||
      !fitsU16(pit1_divider - 1U) || !fitsU16(phase_ipg) ||
      !fitsU16(phase_ipg + 1U) || !fitsU32(expected_dwt)) {
    result.status = Status::kArithmeticOverflow;
    return result;
  }

  Schedule &schedule = result.schedule;
  schedule.adc_pair_period_ticks =
      static_cast<std::uint16_t>(adc_period);
  schedule.adc1_phase_ticks = static_cast<std::uint16_t>(phase_ticks);
  schedule.gpio_sample_period_ticks =
      static_cast<std::uint16_t>(gpio_period);
  schedule.gpio_master_pit_divider =
      static_cast<std::uint16_t>(pit0_divider);
  schedule.gpio_master_pit_load =
      static_cast<std::uint16_t>(pit0_divider - 1U);
  schedule.adc_pair_pit_divider =
      static_cast<std::uint16_t>(pit1_divider);
  schedule.adc_pair_pit_load =
      static_cast<std::uint16_t>(pit1_divider - 1U);
  schedule.adc_etc_predivider = 0U;
  schedule.adc_etc_chain_length = 1U;
  schedule.adc0_initial_delay = 0U;
  schedule.adc1_initial_delay = static_cast<std::uint16_t>(phase_ipg);
  schedule.adc0_effective_delay = 1U;
  schedule.adc1_effective_delay =
      static_cast<std::uint16_t>(phase_ipg + 1U);
  schedule.adc1_phase_ipg_cycles =
      static_cast<std::uint16_t>(phase_ipg);
  schedule.completion_expected_dwt_cycles =
      static_cast<std::uint32_t>(expected_dwt);

  if (schedule.adc_pair_period_ticks != timing.adc_pair_period_ticks ||
      schedule.adc1_phase_ticks != timing.adc1_phase_ticks ||
      schedule.gpio_sample_period_ticks !=
          timing.gpio_sample_period_ticks ||
      schedule.gpio_master_pit_divider !=
          timing.gpio_master_pit_divider ||
      schedule.gpio_master_pit_load != timing.gpio_master_pit_load ||
      schedule.adc_pair_pit_divider != timing.adc_pair_pit_divider ||
      schedule.adc_pair_pit_load != timing.adc_pair_pit_load ||
      schedule.adc1_phase_ipg_cycles !=
          timing.adc1_phase_ipg_cycles ||
      schedule.completion_expected_dwt_cycles !=
          timing.completion_expected_dwt_cycles) {
    result.status = Status::kGeneratedContractMismatch;
    return result;
  }
  result.status = Status::kOk;
  return result;
}

}  // namespace

THINGDAQ_VARIABLE_RATE_COLD_CODE(".flashmem.variable_rate.derive")
DeriveResult derive(protocol_v2::RateProfile profile,
                    ClockDomains clocks) {
  const protocol_v2::RateProfileTiming *timing = timingFor(profile);
  if (timing == nullptr) {
    DeriveResult result{};
    result.status = Status::kUnsupportedProfile;
    return result;
  }
  return deriveKnown(*timing, clocks);
}

THINGDAQ_VARIABLE_RATE_COLD_CODE(".flashmem.variable_rate.derive_rates")
DeriveResult deriveForRates(std::uint32_t adc_pair_rate_hz,
                            std::uint32_t gpio_sample_rate_hz,
                            ClockDomains clocks) {
  if (adc_pair_rate_hz == 0U || gpio_sample_rate_hz == 0U) {
    DeriveResult result{};
    result.status = Status::kUnsupportedRatePair;
    return result;
  }
  const std::uint64_t four_adc =
      static_cast<std::uint64_t>(adc_pair_rate_hz) * 4U;
  if (!fitsU32(four_adc)) {
    DeriveResult result{};
    result.status = Status::kArithmeticOverflow;
    return result;
  }
  if (four_adc != gpio_sample_rate_hz) {
    DeriveResult result{};
    result.status = Status::kInvalidFourToOneRatio;
    return result;
  }
  for (const protocol_v2::RateProfileTiming &timing :
       rate_profile::kTimings) {
    if (timing.adc_pair_rate_hz == adc_pair_rate_hz &&
        timing.gpio_sample_rate_hz == gpio_sample_rate_hz) {
      return deriveKnown(timing, clocks);
    }
  }
  DeriveResult result{};
  result.status = Status::kUnsupportedRatePair;
  return result;
}

THINGDAQ_VARIABLE_RATE_COLD_CODE(".flashmem.variable_rate.readback_match")
bool readbackMatches(const Schedule &expected, const Schedule &observed) {
  return expected == observed;
}

THINGDAQ_VARIABLE_RATE_COLD_CODE(".flashmem.variable_rate.configure")
ConfigureResult Scheduler::configure(protocol_v2::RateProfile profile) {
  return configureDerived(derive(profile));
}

THINGDAQ_VARIABLE_RATE_COLD_CODE(".flashmem.variable_rate.configure_rates")
ConfigureResult Scheduler::configureRates(
    std::uint32_t adc_pair_rate_hz, std::uint32_t gpio_sample_rate_hz) {
  return configureDerived(
      deriveForRates(adc_pair_rate_hz, gpio_sample_rate_hz));
}

THINGDAQ_VARIABLE_RATE_COLD_CODE(".flashmem.variable_rate.configure_derived")
ConfigureResult Scheduler::configureDerived(const DeriveResult &derived) {
  ConfigureResult result{};
  result.requested = derived.schedule;
  if (!derived.ok()) {
    result.status = derived.status;
    return result;
  }
  if (faulted_) {
    result.status = Status::kFaulted;
    return result;
  }
  if (transaction_active_) {
    result.status = Status::kBusy;
    return result;
  }

  transaction_active_ = true;
  result.transaction_started = platform_.beginTransaction();
  if (!result.transaction_started) {
    transaction_active_ = false;
    result.status = Status::kPlatformBeginFailed;
    return result;
  }

  result.apply_attempted = true;
  if (!platform_.applyStopped(derived.schedule)) {
    rollback(result, Status::kPlatformApplyFailed);
    return result;
  }
  result.readback_completed = platform_.readback(result.observed);
  if (!result.readback_completed) {
    rollback(result, Status::kReadbackFailed);
    return result;
  }
  if (!readbackMatches(derived.schedule, result.observed)) {
    rollback(result, Status::kReadbackMismatch);
    return result;
  }

  result.commit_attempted = true;
  if (!platform_.commitTransaction()) {
    rollback(result, Status::kCommitFailed);
    return result;
  }
  selected_ = derived.schedule;
  configured_ = true;
  transaction_active_ = false;
  result.status = Status::kOk;
  return result;
}

THINGDAQ_VARIABLE_RATE_COLD_CODE(".flashmem.variable_rate.rollback")
void Scheduler::rollback(ConfigureResult &result, Status failure) {
  result.rollback_attempted = true;
  result.rolled_back = platform_.rollbackTransaction();
  transaction_active_ = false;
  if (!result.rolled_back) {
    faulted_ = true;
    configured_ = false;
    result.status = Status::kRollbackFailed;
    return;
  }
  result.status = failure;
}

}  // namespace thingdaq::variable_rate

#undef THINGDAQ_VARIABLE_RATE_COLD_CODE
