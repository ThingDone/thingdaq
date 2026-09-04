#pragma once

#include "input_experiment_profile.h"

#include <cstdint>

#include "generated/protocol_v2_constants.h"

namespace thingdaq::variable_rate {

struct ClockDomains {
  std::uint32_t timestamp_hz = protocol_v2::kTimestampHz;
  std::uint32_t pit_hz = protocol_v2::kPitClockHz;
  std::uint32_t ipg_hz = protocol_v2::kIpgClockHz;
  std::uint32_t dwt_hz = input_experiment::kCpuHz;
};

constexpr bool operator==(const ClockDomains &left,
                          const ClockDomains &right) {
  return left.timestamp_hz == right.timestamp_hz &&
         left.pit_hz == right.pit_hz && left.ipg_hz == right.ipg_hz &&
         left.dwt_hz == right.dwt_hz;
}

constexpr bool operator!=(const ClockDomains &left,
                          const ClockDomains &right) {
  return !(left == right);
}

inline constexpr ClockDomains kContractClocks{};

// RT1062 TRIGn_COUNTER.INIT_DELAY is bits 15:0. Teensy core 1.62's
// ADC_ETC_TRIG_COUNTER_INIT_DELAY macro incorrectly masks to eight bits.
// The lower rate profiles require 300 and 600 IPG cycles, not 44 and 88.
constexpr std::uint32_t adcEtcInitialDelay(std::uint16_t cycles) {
  return cycles;
}

enum class Status : std::uint8_t {
  kOk,
  kUnsupportedProfile,
  kUnsupportedRatePair,
  kInvalidFourToOneRatio,
  kClockMismatch,
  kNonIntegralDivider,
  kArithmeticOverflow,
  kGeneratedContractMismatch,
  kBusy,
  kPlatformBeginFailed,
  kPlatformApplyFailed,
  kReadbackFailed,
  kReadbackMismatch,
  kCommitFailed,
  kRollbackFailed,
  kFaulted,
};

struct Schedule {
  ClockDomains clocks{};
  protocol_v2::RateProfile profile =
      protocol_v2::RateProfile::kAdc1mhzGpio4mhz;
  std::uint32_t adc_pair_rate_hz = 0U;
  std::uint32_t gpio_sample_rate_hz = 0U;
  std::uint16_t adc_pair_period_ticks = 0U;
  std::uint16_t adc1_phase_ticks = 0U;
  std::uint16_t gpio_sample_period_ticks = 0U;
  std::uint16_t gpio_master_pit_divider = 0U;
  std::uint16_t gpio_master_pit_load = 0U;
  std::uint16_t adc_pair_pit_divider = 0U;
  std::uint16_t adc_pair_pit_load = 0U;
  std::uint8_t adc_etc_predivider = 0U;
  std::uint8_t adc_etc_chain_length = 0U;
  std::uint16_t adc0_initial_delay = 0U;
  std::uint16_t adc1_initial_delay = 0U;
  std::uint16_t adc0_effective_delay = 0U;
  std::uint16_t adc1_effective_delay = 0U;
  std::uint16_t adc1_phase_ipg_cycles = 0U;
  std::uint32_t completion_expected_dwt_cycles = 0U;
};

constexpr bool operator==(const Schedule &left, const Schedule &right) {
  return left.clocks == right.clocks && left.profile == right.profile &&
         left.adc_pair_rate_hz == right.adc_pair_rate_hz &&
         left.gpio_sample_rate_hz == right.gpio_sample_rate_hz &&
         left.adc_pair_period_ticks == right.adc_pair_period_ticks &&
         left.adc1_phase_ticks == right.adc1_phase_ticks &&
         left.gpio_sample_period_ticks ==
             right.gpio_sample_period_ticks &&
         left.gpio_master_pit_divider ==
             right.gpio_master_pit_divider &&
         left.gpio_master_pit_load == right.gpio_master_pit_load &&
         left.adc_pair_pit_divider == right.adc_pair_pit_divider &&
         left.adc_pair_pit_load == right.adc_pair_pit_load &&
         left.adc_etc_predivider == right.adc_etc_predivider &&
         left.adc_etc_chain_length == right.adc_etc_chain_length &&
         left.adc0_initial_delay == right.adc0_initial_delay &&
         left.adc1_initial_delay == right.adc1_initial_delay &&
         left.adc0_effective_delay == right.adc0_effective_delay &&
         left.adc1_effective_delay == right.adc1_effective_delay &&
         left.adc1_phase_ipg_cycles == right.adc1_phase_ipg_cycles &&
         left.completion_expected_dwt_cycles ==
             right.completion_expected_dwt_cycles;
}

constexpr bool operator!=(const Schedule &left, const Schedule &right) {
  return !(left == right);
}

struct DeriveResult {
  Status status = Status::kGeneratedContractMismatch;
  Schedule schedule{};

  constexpr bool ok() const { return status == Status::kOk; }
};

// The public derivation boundary is intentionally closed over the generated
// four-profile table. It never rounds a requested rate or chooses a nearest
// divider.
DeriveResult derive(protocol_v2::RateProfile profile,
                    ClockDomains clocks = kContractClocks);
DeriveResult deriveForRates(std::uint32_t adc_pair_rate_hz,
                            std::uint32_t gpio_sample_rate_hz,
                            ClockDomains clocks = kContractClocks);
bool readbackMatches(const Schedule &expected, const Schedule &observed);

// A target adapter owns the opaque register snapshot behind this transaction.
// beginTransaction() captures it before the first write; rollbackTransaction()
// restores every touched field after any partial apply or failed readback.
class Platform {
 public:
  virtual ~Platform() = default;
  virtual bool beginTransaction() = 0;
  virtual bool applyStopped(const Schedule &schedule) = 0;
  virtual bool readback(Schedule &observed) = 0;
  virtual bool commitTransaction() = 0;
  virtual bool rollbackTransaction() = 0;
};

struct ConfigureResult {
  Status status = Status::kPlatformBeginFailed;
  Schedule requested{};
  Schedule observed{};
  bool transaction_started = false;
  bool apply_attempted = false;
  bool readback_completed = false;
  bool commit_attempted = false;
  bool rollback_attempted = false;
  bool rolled_back = false;

  constexpr bool ok() const { return status == Status::kOk; }
};

class Scheduler final {
 public:
  explicit constexpr Scheduler(Platform &platform) : platform_(platform) {}

  ConfigureResult configure(protocol_v2::RateProfile profile);
  ConfigureResult configureRates(std::uint32_t adc_pair_rate_hz,
                                 std::uint32_t gpio_sample_rate_hz);

  constexpr bool configured() const { return configured_; }
  constexpr bool faulted() const { return faulted_; }
  constexpr bool transactionActive() const { return transaction_active_; }
  constexpr const Schedule &selected() const { return selected_; }

 private:
  ConfigureResult configureDerived(const DeriveResult &derived);
  void rollback(ConfigureResult &result, Status failure);

  Platform &platform_;
  Schedule selected_{};
  bool configured_ = false;
  bool faulted_ = false;
  bool transaction_active_ = false;
};

static_assert(kContractClocks.timestamp_hz == protocol_v2::kTimestampHz);
static_assert(kContractClocks.pit_hz == protocol_v2::kPitClockHz);
static_assert(kContractClocks.ipg_hz == protocol_v2::kIpgClockHz);
static_assert(kContractClocks.dwt_hz == input_experiment::kCpuHz);

}  // namespace thingdaq::variable_rate
