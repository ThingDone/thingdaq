#include <array>
#include <cstddef>
#include <cstdint>
#include <iostream>
#include <limits>
#include <string>

#include "gpio_dual_bank_capture.h"
#include "gpio_dual_bank_packer.h"
#include "variable_rate_scheduler.h"

namespace {

namespace join = thingdaq::gpio_join;
namespace packer = thingdaq::gpio_aux_packer;
namespace protocol_v2 = thingdaq::protocol_v2;
namespace rate = thingdaq::variable_rate;

int failures = 0;

void expect(bool condition, const std::string &message) {
  if (!condition) {
    std::cerr << "FAIL: " << message << '\n';
    ++failures;
  }
}

class FakeCache final : public thingdaq::dma::CacheMaintenance {
 public:
  void discardBeforeDmaWrite(void *, std::size_t) override { ++discards; }
  void invalidateBeforeCpuRead(void *, std::size_t) override {
    ++invalidations;
  }

  std::uint32_t discards = 0U;
  std::uint32_t invalidations = 0U;
};

class FakeCritical final : public thingdaq::dma::CriticalSection {
 public:
  std::uint32_t enter() override {
    const std::uint32_t token = depth;
    ++depth;
    ++enters;
    return token;
  }

  void exit(std::uint32_t token) override {
    if (depth == 0U || token + 1U != depth) {
      balanced = false;
      return;
    }
    --depth;
    ++exits;
  }

  std::uint32_t depth = 0U;
  std::uint32_t enters = 0U;
  std::uint32_t exits = 0U;
  bool balanced = true;
};

struct JoinFixture {
  join::PairedRawStorage storage{};
  join::PairedOverflowSink overflow{};
  FakeCache cache{};
  FakeCritical critical{};
  join::DualBankCaptureRing ring{storage, overflow, cache, critical};
};

enum class PlatformFailure : std::uint8_t {
  kNone,
  kBegin,
  kApply,
  kReadback,
  kMismatch,
  kCommit,
  kRollback,
};

class FaultPlatform final : public rate::Platform {
 public:
  explicit FaultPlatform(PlatformFailure selected) : failure(selected) {}

  bool beginTransaction() override {
    log('B');
    ++begin_calls;
    active = failure != PlatformFailure::kBegin;
    return active;
  }

  bool applyStopped(const rate::Schedule &schedule) override {
    log('A');
    ++apply_calls;
    applied = schedule;
    return failure != PlatformFailure::kApply &&
           failure != PlatformFailure::kRollback;
  }

  bool readback(rate::Schedule &observed) override {
    log('R');
    ++readback_calls;
    observed = applied;
    if (failure == PlatformFailure::kMismatch) {
      ++observed.adc1_initial_delay;
    }
    return failure != PlatformFailure::kReadback;
  }

  bool commitTransaction() override {
    log('C');
    ++commit_calls;
    if (failure != PlatformFailure::kCommit) {
      active = false;
      return true;
    }
    return false;
  }

  bool rollbackTransaction() override {
    log('X');
    ++rollback_calls;
    if (failure != PlatformFailure::kRollback) {
      active = false;
      return true;
    }
    return false;
  }

  void log(char operation) {
    if (log_size < operations.size()) {
      operations[log_size] = operation;
      ++log_size;
    }
  }

  PlatformFailure failure;
  rate::Schedule applied{};
  std::array<char, 8U> operations{};
  std::size_t log_size = 0U;
  std::uint32_t begin_calls = 0U;
  std::uint32_t apply_calls = 0U;
  std::uint32_t readback_calls = 0U;
  std::uint32_t commit_calls = 0U;
  std::uint32_t rollback_calls = 0U;
  bool active = false;
};

join::CompletionResult completePair(
    JoinFixture &fixture, std::uint32_t epoch, std::uint32_t generation,
    std::uint8_t destination, std::uint64_t first_ticks,
    join::Bank first_bank = join::Bank::kPrimary) {
  const join::Bank second_bank =
      first_bank == join::Bank::kPrimary ? join::Bank::kAuxiliary
                                         : join::Bank::kPrimary;
  const join::CompletionResult first = fixture.ring.onMajorLoopComplete(
      first_bank, epoch, generation, destination, first_ticks);
  expect(first.consumed && !first.pair_ready,
         "one bank completion must remain unpublished");
  return fixture.ring.onMajorLoopComplete(
      second_bank, epoch, generation, destination, first_ticks);
}

std::size_t drainReady(JoinFixture &fixture) {
  std::size_t drained = 0U;
  while (true) {
    const join::AcquireResult acquired = fixture.ring.acquireReady();
    if (acquired.status == join::OperationStatus::kNoReadyBuffer) {
      return drained;
    }
    expect(acquired.ok() && acquired.handle.valid(),
           "a ready buffer must expose one valid paired lease");
    if (!acquired.ok()) {
      return drained;
    }
    expect(fixture.ring.release(acquired.handle) ==
               join::OperationStatus::kOk,
           "a valid paired lease must release exactly once");
    ++drained;
  }
}

std::uint32_t scatterByte(
    std::uint8_t value, const std::array<std::uint8_t, 8U> &port_bits) {
  std::uint32_t word = 0U;
  for (std::size_t bit = 0U; bit < port_bits.size(); ++bit) {
    if ((value & static_cast<std::uint8_t>(1U << bit)) != 0U) {
      word |= std::uint32_t{1U} << port_bits[bit];
    }
  }
  return word;
}

void testEveryProfileAndSchedulerFailureBoundary() {
  constexpr std::array<std::uint32_t, 4U> adc_rates{
      1000000U, 500000U, 250000U, 125000U};
  constexpr std::array<std::uint32_t, 4U> gpio_rates{
      4000000U, 2000000U, 1000000U, 500000U};
  constexpr std::array<std::uint16_t, 4U> adc_periods{8U, 16U, 32U,
                                                     64U};
  constexpr std::array<std::uint16_t, 4U> gpio_periods{2U, 4U, 8U,
                                                      16U};
  constexpr std::array<std::uint16_t, 4U> phase_ticks{4U, 8U, 16U,
                                                      32U};
  constexpr std::array<std::uint16_t, 4U> pit_loads{5U, 11U, 23U,
                                                    47U};
  constexpr std::array<std::uint16_t, 4U> ipg_phases{75U, 150U, 300U,
                                                     600U};
  constexpr std::array<std::uint32_t, 4U> dwt_deltas{300U, 600U, 1200U,
                                                     2400U};

  for (std::uint32_t raw = 0U; raw < 256U; ++raw) {
    const auto profile = static_cast<protocol_v2::RateProfile>(raw);
    const rate::DeriveResult result = rate::derive(profile);
    if (raw >= adc_rates.size()) {
      expect(result.status == rate::Status::kUnsupportedProfile,
             "every undeclared rate-profile byte must fail closed");
      continue;
    }
    const std::size_t index = static_cast<std::size_t>(raw);
    const rate::Schedule &schedule = result.schedule;
    expect(result.ok() && schedule.adc_pair_rate_hz == adc_rates[index] &&
               schedule.gpio_sample_rate_hz == gpio_rates[index] &&
               schedule.adc_pair_period_ticks == adc_periods[index] &&
               schedule.gpio_sample_period_ticks == gpio_periods[index] &&
               schedule.adc1_phase_ticks == phase_ticks[index] &&
               schedule.gpio_master_pit_load == pit_loads[index] &&
               schedule.adc_pair_pit_divider == 4U &&
               schedule.adc_pair_pit_load == 3U &&
               schedule.adc1_initial_delay == ipg_phases[index] &&
               schedule.adc1_effective_delay == ipg_phases[index] + 1U &&
               schedule.adc1_phase_ipg_cycles == ipg_phases[index] &&
               schedule.completion_expected_dwt_cycles ==
                   dwt_deltas[index],
           "each declared profile must derive every exact schedule field");
    const rate::DeriveResult by_rates =
        rate::deriveForRates(adc_rates[index], gpio_rates[index]);
    expect(by_rates.ok() && by_rates.schedule == schedule,
           "rate-pair and enum schedule selection must be identical");
  }

  expect(rate::deriveForRates(0U, 0U).status ==
             rate::Status::kUnsupportedRatePair,
         "zero rates must be rejected before division");
  expect(rate::deriveForRates(std::numeric_limits<std::uint32_t>::max(),
                              std::numeric_limits<std::uint32_t>::max())
             .status == rate::Status::kArithmeticOverflow,
         "a four-times-ADC overflow must fail before comparison");
  expect(rate::deriveForRates(500000U, 1000000U).status ==
             rate::Status::kInvalidFourToOneRatio,
         "an integral but wrong ratio must be distinguished");
  expect(rate::deriveForRates(200000U, 800000U).status ==
             rate::Status::kUnsupportedRatePair,
         "an exact integral 4:1 pair outside the table must be rejected");

  const rate::Schedule expected =
      rate::derive(protocol_v2::RateProfile::kAdc250khzGpio1mhz).schedule;
  rate::Schedule observed = expected;
#define EXPECT_READBACK_MISMATCH(field)                                      \
  do {                                                                        \
    observed = expected;                                                      \
    ++observed.field;                                                         \
    expect(!rate::readbackMatches(expected, observed),                        \
           "readback must compare " #field);                                  \
  } while (false)
  EXPECT_READBACK_MISMATCH(adc_pair_rate_hz);
  EXPECT_READBACK_MISMATCH(gpio_sample_rate_hz);
  EXPECT_READBACK_MISMATCH(adc_pair_period_ticks);
  EXPECT_READBACK_MISMATCH(adc1_phase_ticks);
  EXPECT_READBACK_MISMATCH(gpio_sample_period_ticks);
  EXPECT_READBACK_MISMATCH(gpio_master_pit_divider);
  EXPECT_READBACK_MISMATCH(gpio_master_pit_load);
  EXPECT_READBACK_MISMATCH(adc_pair_pit_divider);
  EXPECT_READBACK_MISMATCH(adc_pair_pit_load);
  EXPECT_READBACK_MISMATCH(adc_etc_predivider);
  EXPECT_READBACK_MISMATCH(adc_etc_chain_length);
  EXPECT_READBACK_MISMATCH(adc0_initial_delay);
  EXPECT_READBACK_MISMATCH(adc1_initial_delay);
  EXPECT_READBACK_MISMATCH(adc0_effective_delay);
  EXPECT_READBACK_MISMATCH(adc1_effective_delay);
  EXPECT_READBACK_MISMATCH(adc1_phase_ipg_cycles);
  EXPECT_READBACK_MISMATCH(completion_expected_dwt_cycles);
#undef EXPECT_READBACK_MISMATCH
  observed = expected;
  observed.profile = protocol_v2::RateProfile::kAdc125khzGpio500khz;
  expect(!rate::readbackMatches(expected, observed),
         "readback must compare the selected profile");
  observed = expected;
  ++observed.clocks.timestamp_hz;
  expect(!rate::readbackMatches(expected, observed),
         "readback must compare the timestamp clock");
  observed = expected;
  ++observed.clocks.pit_hz;
  expect(!rate::readbackMatches(expected, observed),
         "readback must compare the PIT clock");
  observed = expected;
  ++observed.clocks.ipg_hz;
  expect(!rate::readbackMatches(expected, observed),
         "readback must compare the IPG clock");
  observed = expected;
  ++observed.clocks.dwt_hz;
  expect(!rate::readbackMatches(expected, observed),
         "readback must compare the DWT clock");

  struct FailureCase {
    PlatformFailure injected;
    rate::Status expected_status;
    std::uint32_t apply_calls;
    std::uint32_t readback_calls;
    std::uint32_t commit_calls;
    std::uint32_t rollback_calls;
    bool faulted;
  };
  constexpr std::array<FailureCase, 7U> cases{{
      {PlatformFailure::kNone, rate::Status::kOk, 1U, 1U, 1U, 0U, false},
      {PlatformFailure::kBegin, rate::Status::kPlatformBeginFailed, 0U, 0U,
       0U, 0U, false},
      {PlatformFailure::kApply, rate::Status::kPlatformApplyFailed, 1U, 0U,
       0U, 1U, false},
      {PlatformFailure::kReadback, rate::Status::kReadbackFailed, 1U, 1U, 0U,
       1U, false},
      {PlatformFailure::kMismatch, rate::Status::kReadbackMismatch, 1U, 1U,
       0U, 1U, false},
      {PlatformFailure::kCommit, rate::Status::kCommitFailed, 1U, 1U, 1U, 1U,
       false},
      {PlatformFailure::kRollback, rate::Status::kRollbackFailed, 1U, 0U, 0U,
       1U, true},
  }};
  for (const FailureCase &test_case : cases) {
    FaultPlatform platform{test_case.injected};
    rate::Scheduler scheduler{platform};
    const rate::ConfigureResult result = scheduler.configure(
        protocol_v2::RateProfile::kAdc500khzGpio2mhz);
    expect(result.status == test_case.expected_status &&
               platform.begin_calls == 1U &&
               platform.apply_calls == test_case.apply_calls &&
               platform.readback_calls == test_case.readback_calls &&
               platform.commit_calls == test_case.commit_calls &&
               platform.rollback_calls == test_case.rollback_calls &&
               scheduler.faulted() == test_case.faulted &&
               !scheduler.transactionActive() &&
               platform.active == test_case.faulted,
           "each transactional failure boundary must roll back exactly once");
    expect(scheduler.configured() ==
               (test_case.expected_status == rate::Status::kOk),
           "only a committed exact readback may become configured");
  }

  FaultPlatform preserve_platform{PlatformFailure::kNone};
  rate::Scheduler preserve_scheduler{preserve_platform};
  expect(preserve_scheduler
             .configure(protocol_v2::RateProfile::kAdc1mhzGpio4mhz)
             .ok(),
         "preservation fixture must establish one selected schedule");
  const rate::Schedule preserved = preserve_scheduler.selected();
  preserve_platform.failure = PlatformFailure::kApply;
  const rate::ConfigureResult failed_update = preserve_scheduler.configure(
      protocol_v2::RateProfile::kAdc125khzGpio500khz);
  expect(failed_update.status == rate::Status::kPlatformApplyFailed &&
             preserve_scheduler.configured() &&
             preserve_scheduler.selected() == preserved,
         "successful rollback must preserve the previous selected schedule");
}

void testEveryPackingCombinationAndCapacityGuard() {
  constexpr std::array<std::uint8_t, 8U> primary_bits{10U, 17U, 16U, 11U,
                                                       0U,  2U,  1U,  3U};
  constexpr std::array<std::uint8_t, 8U> auxiliary_bits{23U, 22U, 17U, 16U,
                                                         26U, 27U, 24U, 25U};
  constexpr std::uint32_t primary_mask = protocol_v2::kPrimaryGpioCaptureMask;
  constexpr std::uint32_t auxiliary_mask = protocol_v2::kAuxGpioCaptureMask;
  for (std::uint32_t low = 0U; low < 256U; ++low) {
    for (std::uint32_t high = 0U; high < 256U; ++high) {
      const std::uint32_t primary = scatterByte(
          static_cast<std::uint8_t>(low), primary_bits);
      const std::uint32_t auxiliary = scatterByte(
          static_cast<std::uint8_t>(high), auxiliary_bits);
      const std::uint16_t expected = static_cast<std::uint16_t>(
          low | (high << 8U));
      const std::uint16_t packed =
          packer::packDualBankWord(primary, auxiliary);
      if (packed != expected) {
        expect(false, "all 65536 packed bank-byte combinations must agree");
        return;
      }
      const std::uint16_t with_unrelated_bits = packer::packDualBankWord(
          primary | ~primary_mask, auxiliary | ~auxiliary_mask);
      if (with_unrelated_bits != expected) {
        expect(false, "unrelated GPIO port bits must never enter the wire word");
        return;
      }
    }
  }

  constexpr std::array<std::uint8_t, 5U> low_values{0x00U, 0x01U, 0x80U,
                                                    0xA5U, 0xFFU};
  constexpr std::array<std::uint8_t, 5U> high_values{0xFFU, 0x80U, 0x01U,
                                                     0x3CU, 0x00U};
  std::array<std::uint32_t, low_values.size()> primary_words{};
  std::array<std::uint32_t, high_values.size()> auxiliary_words{};
  for (std::size_t index = 0U; index < low_values.size(); ++index) {
    primary_words[index] = scatterByte(low_values[index], primary_bits);
    auxiliary_words[index] = scatterByte(high_values[index], auxiliary_bits);
  }
  std::array<std::uint8_t, 14U> destination{};
  destination.fill(0xCCU);
  expect(packer::packDualBankBatch(
             primary_words.data(), auxiliary_words.data(), low_values.size(),
             destination.data(), 2U * low_values.size()) == low_values.size(),
         "an exact-capacity batch must pack every logical sample");
  for (std::size_t index = 0U; index < low_values.size(); ++index) {
    expect(destination[2U * index] == low_values[index] &&
               destination[2U * index + 1U] == high_values[index],
           "batch serialization must be low-byte then high-byte");
  }
  expect(destination[10U] == 0xCCU && destination[13U] == 0xCCU,
         "batch packing must not touch bytes beyond declared capacity");

  std::array<std::uint8_t, 10U> guarded{};
  guarded.fill(0x5AU);
  expect(packer::packDualBankBatch(
             primary_words.data(), auxiliary_words.data(), low_values.size(),
             guarded.data(), guarded.size() - 1U) == 0U,
         "an undersized destination must reject the complete batch");
  expect(guarded[0] == 0x5AU && guarded[guarded.size() - 1U] == 0x5AU,
         "capacity rejection must not partially modify the destination");
  expect(packer::packDualBankBatch(
             nullptr, auxiliary_words.data(), 1U, guarded.data(),
             guarded.size()) == 0U &&
             packer::packDualBankBatch(
                 primary_words.data(), nullptr, 1U, guarded.data(),
                 guarded.size()) == 0U &&
             packer::packDualBankBatch(
                 primary_words.data(), auxiliary_words.data(), 1U, nullptr,
                 guarded.size()) == 0U &&
             packer::packDualBankBatch(nullptr, nullptr, 0U, nullptr, 0U) ==
                 0U,
         "null and empty batch boundaries must remain bounded");
}

void testLongGenerationStressAcrossWrap() {
  JoinFixture fixture{};
  constexpr std::uint32_t epoch = 0xA551U;
  constexpr std::uint32_t period_ticks = 16U;
  constexpr std::uint64_t first_ticks = 64U;
  constexpr std::uint32_t initial_generation =
      std::numeric_limits<std::uint32_t>::max() - 511U;
  constexpr std::uint32_t iterations = 2048U;
  constexpr std::uint64_t coverage =
      static_cast<std::uint64_t>(join::kSamplesPerBlock) * period_ticks;
  const join::PrimeResult primed = fixture.ring.prime(
      epoch, period_ticks, initial_generation, first_ticks);
  expect(primed.ok(), "the wrap-stress ring must prime");

  for (std::uint32_t offset = 0U; offset < iterations; ++offset) {
    const std::uint32_t generation = initial_generation + offset;
    const std::uint64_t expected_ticks =
        first_ticks + static_cast<std::uint64_t>(offset) * coverage;
    const join::ReservationResult reserved =
        fixture.ring.reserveGeneration(epoch, generation);
    expect(reserved.ok() && reserved.first_sample_ticks == expected_ticks &&
               reserved.destination < join::kRingDepth,
           "steady draining must reserve an in-ring chronological generation");
    const join::Bank first_bank =
        (offset & 1U) == 0U ? join::Bank::kPrimary
                            : join::Bank::kAuxiliary;
    const join::CompletionResult completed = completePair(
        fixture, epoch, generation, reserved.destination, expected_ticks,
        first_bank);
    expect(completed.ok() && completed.pair_ready && !completed.pair_lost,
           "matched completions must publish across uint32 generation wrap");
    const join::AcquireResult acquired = fixture.ring.acquireReady();
    expect(acquired.ok() && acquired.handle.generation == generation &&
               acquired.handle.first_sample_ticks == expected_ticks,
           "acquisition order must follow timestamps rather than wrapped IDs");
    if (acquired.ok()) {
      const join::BufferHandle stale = acquired.handle;
      expect(fixture.ring.release(acquired.handle) ==
                 join::OperationStatus::kOk,
             "each stress lease must return its paired buffer");
      expect(fixture.ring.release(stale) ==
                 join::OperationStatus::kInvalidHandle,
             "a released lease token must never be reusable");
    }
  }

  const join::Snapshot snapshot = fixture.ring.snapshot();
  const std::uint64_t expected_samples =
      static_cast<std::uint64_t>(iterations) * join::kSamplesPerBlock;
  expect(snapshot.progress.bank_major_loops[0] == iterations &&
             snapshot.progress.bank_major_loops[1] == iterations &&
             snapshot.progress.paired_major_loops == iterations &&
             snapshot.progress.buffers_completed == iterations &&
             snapshot.progress.buffers_acquired == iterations &&
             snapshot.progress.buffers_released == iterations &&
             snapshot.progress.sample_instants_captured == expected_samples &&
             snapshot.progress.sample_instants_joined == expected_samples &&
             snapshot.progress.sample_instants_delivered == expected_samples &&
             snapshot.progress.sample_instants_lost == 0U &&
             snapshot.progress.raw_ring_overruns == 0U &&
             snapshot.progress.invariant_errors == 0U &&
             snapshot.progress.conserved() && fixture.critical.balanced &&
             fixture.critical.depth == 0U,
         "long wrap stress must conserve every fixed-capacity sample");
  expect(fixture.ring.cancel(epoch).ok() && fixture.ring.quiescent(),
         "wrap stress cancellation must reclaim the two prelinked tails");
}

void testSmallCapacityPressureRecoversAndConserves() {
  JoinFixture fixture{};
  constexpr std::uint32_t epoch = 0xA552U;
  constexpr std::uint32_t period_ticks = 2U;
  constexpr std::uint32_t iterations = 96U;
  constexpr std::uint64_t coverage =
      static_cast<std::uint64_t>(join::kSamplesPerBlock) * period_ticks;
  expect(join::kRingDepth == 4U,
         "the pressure test must exercise the four-pair fixed ring");
  expect(fixture.ring.prime(epoch, period_ticks).ok(),
         "the pressure-stress ring must prime");

  std::uint64_t ready_pairs = 0U;
  std::uint64_t lost_pairs = 0U;
  std::uint64_t drained_pairs = 0U;
  for (std::uint32_t generation = 0U; generation < iterations;
       ++generation) {
    const join::ReservationResult reserved =
        fixture.ring.reserveGeneration(epoch, generation);
    expect(reserved.ok() &&
               reserved.first_sample_ticks ==
                   static_cast<std::uint64_t>(generation) * coverage,
           "pressure reservations must retain exact generation timestamps");
    const join::CompletionResult completed = completePair(
        fixture, epoch, generation, reserved.destination,
        reserved.first_sample_ticks,
        (generation & 1U) == 0U ? join::Bank::kAuxiliary
                                : join::Bank::kPrimary);
    if (completed.pair_ready) {
      ++ready_pairs;
    }
    if (completed.pair_lost) {
      ++lost_pairs;
    }
    expect(completed.pair_ready != completed.pair_lost,
           "each pressure generation must be classified once");
    if ((generation + 1U) % 9U == 0U) {
      drained_pairs += drainReady(fixture);
    }
    expect(fixture.ring.snapshot().ready_depth <= join::kRingDepth,
           "ready ownership must never exceed physical capacity");
  }
  drained_pairs += drainReady(fixture);

  const join::Snapshot snapshot = fixture.ring.snapshot();
  const std::uint64_t samples = join::kSamplesPerBlock;
  expect(ready_pairs != 0U && lost_pairs != 0U &&
             ready_pairs + lost_pairs == iterations &&
             drained_pairs == ready_pairs &&
             snapshot.progress.sample_instants_captured ==
                 static_cast<std::uint64_t>(iterations) * samples &&
             snapshot.progress.sample_instants_joined == ready_pairs * samples &&
             snapshot.progress.sample_instants_delivered ==
                 ready_pairs * samples &&
             snapshot.progress.sample_instants_lost == lost_pairs * samples &&
             snapshot.progress.raw_ring_overruns == lost_pairs &&
             snapshot.progress.ready_high_water == join::kRingDepth &&
             snapshot.progress.conserved() &&
             snapshot.progress.invariant_errors == 0U,
         "small-ring pressure must recover and classify every sample exactly");
  expect(fixture.ring.cancel(epoch).ok() && fixture.ring.quiescent() &&
             fixture.critical.balanced,
         "pressure cancellation must leave fixed ownership quiescent");
}

void testSkewStopRollbackFaultAndLeaseTails() {
  {
    JoinFixture skew{};
    constexpr std::uint32_t epoch = 0xA553U;
    constexpr std::uint64_t coverage =
        static_cast<std::uint64_t>(join::kSamplesPerBlock) * 2U;
    const join::PrimeResult primed = skew.ring.prime(epoch, 2U);
    expect(primed.ok(), "the skew fixture must prime");
    const join::CompletionResult primary_zero =
        skew.ring.onMajorLoopComplete(join::Bank::kPrimary, epoch, 0U,
                                      primed.active_destination, 0U);
    const join::CompletionResult primary_one =
        skew.ring.onMajorLoopComplete(join::Bank::kPrimary, epoch, 1U,
                                      primed.queued_destination, coverage);
    const join::CompletionResult auxiliary_zero =
        skew.ring.onMajorLoopComplete(join::Bank::kAuxiliary, epoch, 0U,
                                      primed.active_destination, 0U);
    const join::CompletionResult auxiliary_one =
        skew.ring.onMajorLoopComplete(join::Bank::kAuxiliary, epoch, 1U,
                                      primed.queued_destination, coverage);
    const join::Snapshot snapshot = skew.ring.snapshot();
    expect(primary_zero.ok() &&
               primary_one.status == join::OperationStatus::kInvalidCompletion &&
               auxiliary_zero.pair_lost && auxiliary_one.pair_lost &&
               snapshot.ready_depth == 0U &&
               snapshot.progress.generation_skew_events == 1U &&
               snapshot.progress.sample_instants_captured ==
                   2U * join::kSamplesPerBlock &&
               snapshot.progress.sample_instants_lost ==
                   2U * join::kSamplesPerBlock &&
               snapshot.progress.conserved(),
           "two-bank generation skew must invalidate all unpublished pairs");
    expect(skew.ring.cancel(epoch).ok() && skew.ring.quiescent(),
           "skew cancellation must reclaim invalidated reservations");
  }

  for (const join::StopReason reason :
       std::array<join::StopReason, 3U>{join::StopReason::kStop,
                                        join::StopReason::kRollback,
                                        join::StopReason::kFault}) {
    JoinFixture fixture{};
    constexpr std::uint32_t epoch = 0xA554U;
    const join::PrimeResult primed = fixture.ring.prime(epoch, 4U);
    expect(primed.ok(), "the partial-tail fixture must prime");
    expect(fixture.ring
               .onMajorLoopComplete(join::Bank::kPrimary, epoch, 0U,
                                    primed.active_destination, 0U)
               .ok(),
           "one full primary tail must be recorded before stop");
    std::array<join::BankStopState, join::kBankCount> banks{};
    banks[0].generation = 1U;
    banks[1].generation = 0U;
    banks[1].destination = primed.active_destination;
    banks[1].first_sample_ticks = 0U;
    banks[1].sample_count = 31U;
    const join::StopReport stopped = fixture.ring.stop(banks, reason);
    const join::Snapshot snapshot = fixture.ring.snapshot();
    const bool ordinary_stop = reason == join::StopReason::kStop;
    expect(stopped.ok() && stopped.reason == reason &&
               stopped.samples_discarded == join::kSamplesPerBlock &&
               snapshot.progress.sample_instants_captured ==
                   join::kSamplesPerBlock &&
               snapshot.progress.sample_instants_lost ==
                   join::kSamplesPerBlock &&
               snapshot.progress.generation_skew_samples ==
                   join::kSamplesPerBlock - 31U &&
               snapshot.progress.stop_tail_samples ==
                   (ordinary_stop ? join::kSamplesPerBlock : 0U) &&
               snapshot.progress.cancellation_samples ==
                   (ordinary_stop ? 0U : join::kSamplesPerBlock) &&
               snapshot.progress.conserved() && fixture.ring.quiescent(),
           "STOP, rollback, and fault tails must use distinct loss counters");
  }

  {
    JoinFixture hardware_fault{};
    constexpr std::uint32_t epoch = 0xA555U;
    const join::PrimeResult primed = hardware_fault.ring.prime(epoch, 8U);
    expect(primed.ok(), "the hardware-fault fixture must prime");
    hardware_fault.ring.recordHardwareError(epoch);
    const join::CompletionResult completed = completePair(
        hardware_fault, epoch, 0U, primed.active_destination, 0U);
    const join::Snapshot snapshot = hardware_fault.ring.snapshot();
    expect(completed.pair_lost && !completed.pair_ready &&
               snapshot.progress.hardware_errors == 1U &&
               snapshot.progress.sample_instants_lost ==
                   join::kSamplesPerBlock &&
               snapshot.progress.conserved(),
           "a hardware error must poison every outstanding unpublished pair");
    expect(hardware_fault.ring.cancel(epoch, join::StopReason::kFault).ok() &&
               hardware_fault.ring.quiescent(),
           "fault cancellation must reclaim poisoned pairs");
  }

  {
    JoinFixture leased{};
    constexpr std::uint32_t epoch = 0xA556U;
    const join::PrimeResult primed = leased.ring.prime(epoch, 16U);
    expect(primed.ok() &&
               completePair(leased, epoch, 0U, primed.active_destination, 0U)
                   .pair_ready,
           "the lease-tail fixture must publish one pair");
    const join::AcquireResult acquired = leased.ring.acquireReady();
    const join::StopReport stopped = leased.ring.cancel(epoch);
    expect(acquired.ok() && stopped.reading_buffers_to_release == 1U &&
               !leased.ring.quiescent(),
           "STOP must report but never reclaim a CPU-owned paired lease");
    expect(leased.ring.release(acquired.handle) ==
                   join::OperationStatus::kOk &&
               leased.ring.quiescent(),
           "the final CPU release must complete STOP ownership cleanup");
  }
}

}  // namespace

int main() {
  testEveryProfileAndSchedulerFailureBoundary();
  testEveryPackingCombinationAndCapacityGuard();
  testLongGenerationStressAcrossWrap();
  testSmallCapacityPressureRecoversAndConserves();
  testSkewStopRollbackFaultAndLeaseTails();
  if (failures != 0) {
    std::cerr << failures << " auxiliary-input stress checks failed\n";
    return 1;
  }
  std::cout << "auxiliary-input fixed-capacity stress checks passed\n";
  return 0;
}
