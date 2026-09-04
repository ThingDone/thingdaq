#include <array>
#include <cstddef>
#include <cstdint>
#include <iostream>
#include <limits>
#include <string>

#include "gpio_dual_bank_capture.h"
#include "gpio_dual_bank_packer.h"
#include "packet_buffer_pipeline.h"
#include "protocol.h"
#include "stream_layout.h"
#include "variable_rate_scheduler.h"

namespace {

namespace join = thingdaq::gpio_join;
namespace packer = thingdaq::gpio_aux_packer;
namespace packet = thingdaq::packet;
namespace protocol = thingdaq::protocol;
namespace protocol_v1 = thingdaq::protocol_v1;
namespace protocol_v2 = thingdaq::protocol_v2;
namespace rate = thingdaq::variable_rate;
namespace layout = thingdaq::stream_layout;

int failures = 0;

void expect(bool condition, const std::string &message) {
  if (!condition) {
    std::cerr << "FAIL: " << message << '\n';
    ++failures;
  }
}

class FakeSchedulePlatform final : public rate::Platform {
 public:
  bool beginTransaction() override {
    ++begin_calls;
    active = begin_ok;
    return begin_ok;
  }

  bool applyStopped(const rate::Schedule &schedule) override {
    ++apply_calls;
    applied = schedule;
    return apply_ok;
  }

  bool readback(rate::Schedule &observed) override {
    ++readback_calls;
    observed = applied;
    if (corrupt_readback) {
      ++observed.gpio_master_pit_load;
    }
    return readback_ok;
  }

  bool commitTransaction() override {
    ++commit_calls;
    if (commit_ok) {
      active = false;
    }
    return commit_ok;
  }

  bool rollbackTransaction() override {
    ++rollback_calls;
    if (rollback_ok) {
      active = false;
    }
    return rollback_ok;
  }

  rate::Schedule applied{};
  std::uint32_t begin_calls = 0U;
  std::uint32_t apply_calls = 0U;
  std::uint32_t readback_calls = 0U;
  std::uint32_t commit_calls = 0U;
  std::uint32_t rollback_calls = 0U;
  bool begin_ok = true;
  bool apply_ok = true;
  bool readback_ok = true;
  bool commit_ok = true;
  bool rollback_ok = true;
  bool corrupt_readback = false;
  bool active = false;
};

class FakeCache final : public thingdaq::dma::CacheMaintenance {
 public:
  void discardBeforeDmaWrite(void *, std::size_t) override {
    ++discards;
  }
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

join::CompletionResult completeGeneration(
    JoinFixture &fixture, std::uint32_t epoch, std::uint32_t generation,
    std::uint8_t destination, std::uint64_t first_ticks,
    join::Bank first_bank = join::Bank::kPrimary) {
  const join::Bank second_bank =
      first_bank == join::Bank::kPrimary ? join::Bank::kAuxiliary
                                         : join::Bank::kPrimary;
  const join::CompletionResult first = fixture.ring.onMajorLoopComplete(
      first_bank, epoch, generation, destination, first_ticks);
  expect(first.consumed && !first.pair_ready,
         "one GPIO bank never publishes a raw generation");
  return fixture.ring.onMajorLoopComplete(
      second_bank, epoch, generation, destination, first_ticks);
}

void testExactSchedulesAndTransactionalRollback() {
  constexpr std::array<std::uint16_t, 4U> pit0_loads{5U, 11U, 23U,
                                                     47U};
  constexpr std::array<std::uint16_t, 4U> phase_cycles{75U, 150U, 300U,
                                                       600U};
  for (std::size_t index = 0U; index < 4U; ++index) {
    const auto profile = static_cast<protocol_v2::RateProfile>(index);
    const rate::DeriveResult derived = rate::derive(profile);
    expect(derived.ok() &&
               derived.schedule.gpio_master_pit_load == pit0_loads[index] &&
               derived.schedule.adc_pair_pit_load == 3U &&
               derived.schedule.adc1_phase_ipg_cycles ==
                   phase_cycles[index] &&
               derived.schedule.adc1_initial_delay == phase_cycles[index] &&
               derived.schedule.adc1_effective_delay ==
                   phase_cycles[index] + 1U,
           "every generated profile derives exact PIT and ADC phase values");
  }
  expect(rate::deriveForRates(500000U, 1000000U).status ==
             rate::Status::kInvalidFourToOneRatio,
         "a wrong 4:1 pair is rejected without rounding");
  expect(rate::deriveForRates(300000U, 1200000U).status ==
             rate::Status::kUnsupportedRatePair,
         "an undeclared integral-looking rate pair is rejected");
  rate::ClockDomains wrong_clocks{};
  wrong_clocks.pit_hz = 23000000U;
  expect(rate::derive(protocol_v2::RateProfile::kAdc1mhzGpio4mhz,
                      wrong_clocks)
             .status == rate::Status::kClockMismatch,
         "clock readback drift is rejected before a transaction");

  FakeSchedulePlatform platform{};
  rate::Scheduler scheduler{platform};
  const rate::ConfigureResult selected = scheduler.configure(
      protocol_v2::RateProfile::kAdc1mhzGpio4mhz);
  expect(selected.ok() && scheduler.configured() && !scheduler.faulted() &&
             platform.begin_calls == 1U && platform.apply_calls == 1U &&
             platform.readback_calls == 1U && platform.commit_calls == 1U &&
             platform.rollback_calls == 0U && !platform.active,
         "an exact readback commits one stopped-state transaction");
  const rate::Schedule original = scheduler.selected();

  platform.corrupt_readback = true;
  const rate::ConfigureResult mismatch = scheduler.configure(
      protocol_v2::RateProfile::kAdc500khzGpio2mhz);
  expect(mismatch.status == rate::Status::kReadbackMismatch &&
             mismatch.rollback_attempted && mismatch.rolled_back &&
             scheduler.selected() == original && scheduler.configured() &&
             !scheduler.faulted() && platform.rollback_calls == 1U,
         "a PIT readback mismatch rolls back and preserves the prior profile");

  platform.rollback_ok = false;
  const rate::ConfigureResult failed_rollback = scheduler.configure(
      protocol_v2::RateProfile::kAdc250khzGpio1mhz);
  expect(failed_rollback.status == rate::Status::kRollbackFailed &&
             scheduler.faulted() && !scheduler.configured(),
         "a failed rollback latches the portable scheduler faulted");
  expect(scheduler.configure(
             protocol_v2::RateProfile::kAdc125khzGpio500khz)
             .status == rate::Status::kFaulted,
         "a faulted scheduler cannot begin another register transaction");
}

void testLayoutsAreClosedOverModesAndProfiles() {
  expect(layout::legacy().valid() &&
             layout::legacy().protocol_version ==
                 protocol_v1::kProtocolVersion,
         "the legacy run layout remains the exact default");
  for (std::size_t mode_index = 0U; mode_index < 2U; ++mode_index) {
    const auto mode = static_cast<protocol_v2::AuxBankMode>(mode_index);
    for (std::size_t profile_index = 0U; profile_index < 4U;
         ++profile_index) {
      const auto profile =
          static_cast<protocol_v2::RateProfile>(profile_index);
      const layout::Result selected = layout::experimental(mode, profile);
      expect(selected.ok() && selected.layout.valid() &&
                 selected.layout.streams[0].coverage_ticks ==
                     selected.layout.streams[1].coverage_ticks &&
                 selected.layout.protocol_version ==
                     protocol_v2::kProtocolVersion,
             "all eight declared mode/profile layouts are exact");
      if (mode == protocol_v2::AuxBankMode::kInput) {
        expect(selected.layout.streams[0].item_count == 506U &&
                   selected.layout.streams[0].frame_bytes == 2072U &&
                   selected.layout.streams[1].item_count == 2024U &&
                   selected.layout.streams[1].item_bytes == 2U &&
                   selected.layout.streams[1].frame_bytes == 4096U,
               "INPUT uses equal-coverage 506-pair and 2024-word frames");
      } else {
        expect(selected.layout.streams[0].item_count == 1012U &&
                   selected.layout.streams[1].item_count == 4048U &&
                   selected.layout.streams[1].item_bytes == 1U,
               "DISABLED retains the one-bank frame shape");
      }
    }
  }
  expect(layout::experimental(
             static_cast<protocol_v2::AuxBankMode>(2U),
             protocol_v2::RateProfile::kAdc1mhzGpio4mhz)
             .status == layout::Status::kInvalidAuxBankMode,
         "mixed bank mode cannot create a firmware layout");
  expect(layout::experimentalForRates(
             protocol_v2::AuxBankMode::kInput, 300000U, 1200000U)
             .status == layout::Status::kUnsupportedRatePair,
         "arbitrary rates cannot create a firmware layout");
}

void testGenerationBarrierPackingAndStopTailConservation() {
  JoinFixture fixture{};
  const join::PrimeResult primed = fixture.ring.prime(7U, 2U);
  expect(primed.ok() && primed.active_destination == 0U &&
             primed.queued_destination == 1U &&
             fixture.cache.discards == 10U,
         "prime reserves two paired blocks and prepares both banks plus sinks");

  fixture.storage.primary[0].words[0] = std::uint32_t{1U} << 10U;
  fixture.storage.auxiliary[0].words[0] = std::uint32_t{1U} << 25U;
  fixture.storage.primary[0].words[1] = protocol_v2::kPrimaryGpioCaptureMask;
  fixture.storage.auxiliary[0].words[1] = protocol_v2::kAuxGpioCaptureMask;
  const join::CompletionResult paired = completeGeneration(
      fixture, 7U, 0U, primed.active_destination, 0U,
      join::Bank::kAuxiliary);
  expect(paired.ok() && paired.pair_ready && !paired.pair_lost &&
             fixture.ring.snapshot().ready_depth == 1U,
         "matching generation/timestamp/count completions publish once");

  const join::AcquireResult acquired = fixture.ring.acquireReady();
  std::array<std::uint8_t, 4U> bytes{};
  expect(acquired.ok() && acquired.handle.generation == 0U &&
             acquired.handle.first_sample_ticks == 0U &&
             fixture.cache.invalidations == 2U &&
             packer::packDualBankBatch(
                 acquired.handle.primary_words,
                 acquired.handle.auxiliary_words, 2U, bytes.data(),
                 bytes.size()) == 2U &&
             bytes[0] == 0x01U && bytes[1] == 0x80U &&
             bytes[2] == 0xFFU && bytes[3] == 0xFFU,
         "GPIO2 is the low byte and GPIO1 is the little-endian high byte");
  expect(fixture.ring.release(acquired.handle) ==
             join::OperationStatus::kOk,
         "a matched raw lease returns both banks together");

  const std::uint64_t generation_one_ticks = 4048U;
  const join::CompletionResult primary = fixture.ring.onMajorLoopComplete(
      join::Bank::kPrimary, 7U, 1U, primed.queued_destination,
      generation_one_ticks);
  expect(primary.ok() && primary.consumed && !primary.pair_ready,
         "one completed bank remains unpublished at STOP");
  std::array<join::BankStopState, join::kBankCount> stop{};
  stop[0].generation = 2U;
  stop[1].generation = 1U;
  stop[1].destination = primed.queued_destination;
  stop[1].first_sample_ticks = generation_one_ticks;
  stop[1].sample_count = 17U;
  const join::StopReport stopped = fixture.ring.stop(stop);
  const join::Snapshot snapshot = fixture.ring.snapshot();
  expect(stopped.ok() && stopped.samples_discarded == 2024U &&
             snapshot.progress.stop_tail_samples == 2024U &&
             snapshot.progress.generation_skew_samples == 2007U &&
             snapshot.progress.sample_instants_captured == 4048U &&
             snapshot.progress.sample_instants_joined == 2024U &&
             snapshot.progress.sample_instants_lost == 2024U &&
             snapshot.progress.conserved() && fixture.ring.quiescent() &&
             fixture.critical.balanced && fixture.critical.depth == 0U,
         "STOP accounts the unmatched full/partial tail without stale pairing");
  expect(fixture.ring.onMajorLoopComplete(
             join::Bank::kAuxiliary, 7U, 1U,
             primed.queued_destination, generation_one_ticks)
             .status == join::OperationStatus::kNotRunning &&
             fixture.ring.snapshot().progress.stale_completions == 1U,
         "a completion after STOP is stale and can never revive a bank pair");
}

void testMetadataMismatchAndRingOverrunAreLossNotPublication() {
  JoinFixture mismatch{};
  const join::PrimeResult primed = mismatch.ring.prime(11U, 4U);
  expect(primed.ok(), "metadata-mismatch fixture primes");
  const join::CompletionResult first = mismatch.ring.onMajorLoopComplete(
      join::Bank::kPrimary, 11U, 0U, primed.active_destination, 0U);
  const join::CompletionResult second = mismatch.ring.onMajorLoopComplete(
      join::Bank::kAuxiliary, 11U, 0U, primed.active_destination, 4U);
  expect(first.ok() && second.status == join::OperationStatus::kInvalidCompletion &&
             second.pair_lost && !second.pair_ready &&
             mismatch.ring.snapshot().ready_depth == 0U &&
             mismatch.ring.snapshot().progress.timestamp_mismatches != 0U &&
             mismatch.ring.snapshot().progress.conserved(),
         "contradictory timestamps discard a generation instead of pairing it");
  (void)mismatch.ring.cancel(11U);
  expect(mismatch.ring.quiescent(),
         "rollback cancellation reclaims every scheduled raw pair");

  JoinFixture oversized{};
  const join::PrimeResult oversized_prime = oversized.ring.prime(12U, 2U);
  expect(oversized_prime.ok(), "oversized-count fixture primes");
  const join::CompletionResult oversized_first =
      oversized.ring.onMajorLoopComplete(
          join::Bank::kPrimary, 12U, 0U,
          oversized_prime.active_destination, 0U,
          static_cast<std::uint32_t>(join::kSamplesPerBlock + 1U));
  const join::CompletionResult oversized_second =
      oversized.ring.onMajorLoopComplete(
          join::Bank::kAuxiliary, 12U, 0U,
          oversized_prime.active_destination, 0U);
  const join::Snapshot oversized_snapshot = oversized.ring.snapshot();
  expect(oversized_first.status ==
             join::OperationStatus::kInvalidCompletion &&
             oversized_second.pair_lost &&
             oversized_snapshot.progress.sample_instants_captured ==
                 join::kSamplesPerBlock &&
             oversized_snapshot.progress.sample_instants_lost ==
                 join::kSamplesPerBlock &&
             oversized_snapshot.progress.count_mismatches == 1U &&
             oversized_snapshot.progress.conserved(),
         "an impossible DMA count is bounded to physical capacity and lost");
  (void)oversized.ring.cancel(12U);

  JoinFixture crossed_destination{};
  const join::PrimeResult crossed_prime =
      crossed_destination.ring.prime(14U, 2U);
  expect(crossed_prime.ok(), "crossed-destination fixture primes");
  const join::CompletionResult crossed =
      crossed_destination.ring.onMajorLoopComplete(
          join::Bank::kPrimary, 14U, 0U,
          crossed_prime.queued_destination, 0U);
  (void)crossed_destination.ring.onMajorLoopComplete(
      join::Bank::kAuxiliary, 14U, 0U,
      crossed_prime.active_destination, 0U);
  (void)completeGeneration(crossed_destination, 14U, 1U,
                           crossed_prime.queued_destination, 4048U);
  const join::Snapshot crossed_snapshot =
      crossed_destination.ring.snapshot();
  expect(crossed.status == join::OperationStatus::kInvalidCompletion &&
             crossed_snapshot.ready_depth == 0U &&
             crossed_snapshot.progress.destination_mismatches == 1U &&
             crossed_snapshot.progress.sample_instants_lost == 4048U &&
             crossed_snapshot.progress.conserved(),
         "a crossed DMA destination invalidates the potentially overwritten future pair");
  (void)crossed_destination.ring.cancel(14U);

  JoinFixture pressure{};
  const join::PrimeResult pressure_prime = pressure.ring.prime(13U, 2U);
  expect(pressure_prime.ok(), "pressure fixture primes");
  std::array<std::uint8_t, 4U> destinations{
      pressure_prime.active_destination, pressure_prime.queued_destination,
      2U, 3U};
  for (std::uint32_t generation = 0U; generation < 4U; ++generation) {
    const join::CompletionResult completed = completeGeneration(
        pressure, 13U, generation, destinations[generation],
        static_cast<std::uint64_t>(generation) * 4048U);
    expect(completed.pair_ready,
           "each available fixed raw pair becomes READY under pressure");
  }
  const join::CompletionResult overflow = completeGeneration(
      pressure, 13U, 4U, join::kOverflowDestination, 4U * 4048U);
  const join::Snapshot pressured = pressure.ring.snapshot();
  expect(overflow.pair_lost && !overflow.pair_ready &&
             pressured.ready_depth == 4U &&
             pressured.progress.raw_ring_overruns == 1U &&
             pressured.progress.sample_instants_joined == 4U * 2024U &&
             pressured.progress.sample_instants_lost == 2024U &&
             pressured.progress.conserved(),
         "fixed-capacity pressure redirects a complete pair to one loss sink");
  (void)pressure.ring.cancel(13U);
  for (std::size_t index = 0U; index < 4U; ++index) {
    const join::AcquireResult ready = pressure.ring.acquireReady();
    expect(ready.ok() &&
               pressure.ring.release(ready.handle) ==
                   join::OperationStatus::kOk,
           "complete pre-STOP buffers remain drainable after cancellation");
  }
  expect(pressure.ring.quiescent(),
         "all fixed raw ownership returns to FREE after draining");
}

void testGenerationWrapPreservesChronologyAndRejectsStaleCompletions() {
  JoinFixture fixture{};
  constexpr std::uint32_t last_generation =
      std::numeric_limits<std::uint32_t>::max();
  const join::PrimeResult primed =
      fixture.ring.prime(17U, 2U, last_generation);
  expect(primed.ok() && primed.active_generation == last_generation &&
             primed.queued_generation == 0U,
         "generation ownership seeds safely across uint32 wrap");
  expect(completeGeneration(fixture, 17U, last_generation,
                            primed.active_destination, 0U)
             .pair_ready,
         "the final uint32 generation publishes as one matched pair");
  expect(fixture.ring.onMajorLoopComplete(
             join::Bank::kPrimary, 17U, last_generation,
             primed.active_destination, 0U)
             .status == join::OperationStatus::kInvalidCompletion,
         "a pre-wrap stale completion cannot satisfy the wrapped generation");
  expect(completeGeneration(fixture, 17U, 0U,
                            primed.queued_destination, 4048U)
             .pair_ready,
         "generation zero publishes only from its own matched completions");

  for (std::uint32_t expected :
       std::array<std::uint32_t, 2U>{last_generation, 0U}) {
    const join::AcquireResult acquired = fixture.ring.acquireReady();
    expect(acquired.ok() && acquired.handle.generation == expected &&
               fixture.ring.release(acquired.handle) ==
                   join::OperationStatus::kOk,
           "wrapped generations retain timestamp order and paired leases");
  }
  const join::Snapshot snapshot = fixture.ring.snapshot();
  expect(snapshot.progress.sample_instants_captured == 4048U &&
             snapshot.progress.sample_instants_joined == 4048U &&
             snapshot.progress.sample_instants_lost == 0U &&
             snapshot.progress.stale_completions == 1U &&
             snapshot.progress.conserved(),
         "generation wrap and stale rejection preserve exact conservation");
  (void)fixture.ring.cancel(17U);
}

void testAuxiliaryPackerUsesDynamicPacketShapesAndCounters() {
  JoinFixture fixture{};
  constexpr std::uint32_t run_id = 29U;
  constexpr auto profile =
      protocol_v2::RateProfile::kAdc250khzGpio1mhz;
  const layout::Result selected = layout::experimental(
      protocol_v2::AuxBankMode::kInput, profile);
  expect(selected.ok(), "selected INPUT packet layout is valid");
  const layout::FrameLayout &adc_layout = selected.layout.streams[0];
  const layout::FrameLayout &gpio_layout = selected.layout.streams[1];
  const join::PrimeResult primed = fixture.ring.prime(
      run_id, gpio_layout.item_period_ticks);
  expect(primed.ok(), "auxiliary packet fixture primes");
  fixture.storage.primary[0].words[0] = std::uint32_t{1U} << 17U;
  fixture.storage.auxiliary[0].words[0] = std::uint32_t{1U} << 26U;
  expect(completeGeneration(fixture, run_id, 0U,
                            primed.active_destination, 0U)
             .pair_ready,
         "one joined block is ready for cooperative packing");

  static packet::OwnedPacketBufferStorage packet_storage{};
  packet::PacketBufferPipeline pipeline{packet_storage};
  expect(pipeline.startRun(
             run_id, protocol_v1::ChecksumAlgorithm::kCrc32c,
             packet::kAllStreamMask, selected.layout) ==
             packet::OperationStatus::kOk,
         "packet pool binds atomically to the selected v2 layout");
  packer::AuxiliaryBatchPacker gpio_packer{fixture.ring};
  expect(gpio_packer.startRun(
             run_id, protocol_v1::ChecksumAlgorithm::kCrc32c, profile,
             pipeline, 777U) == packer::OperationStatus::kOk,
         "dual-bank packer requires the exact pipeline profile");

  const packet::BeginFillResult adc =
      pipeline.beginFill(packet::Stream::kAdc);
  protocol::MutableByteView adc_payload = pipeline.writablePayload(adc.handle);
  expect(adc.ok() && adc_payload.size == 2024U,
         "INPUT exposes the exact shorter ADC payload");
  for (std::size_t index = 0U; index < adc_payload.size; ++index) {
    adc_payload.data[index] = 0U;
  }
  packet::FrameCompletion adc_completion{};
  adc_completion.first_sample_ticks = 0U;
  adc_completion.flags = static_cast<std::uint16_t>(
      protocol_v1::FrameFlag::kEpochStart);
  adc_completion.checksum_algorithm =
      protocol_v1::ChecksumAlgorithm::kCrc32c;
  adc_completion.payload_bytes_written = adc_payload.size;
  expect(pipeline.finishFill(adc.handle, adc_completion).ok(),
         "the shared packet abstraction accepts 506 ADC pairs");

  const packer::ServiceReport packed = gpio_packer.service(pipeline, 1U);
  expect(packed.frames_packed == 1U && packed.frames_framed == 1U &&
             packed.samples_consumed == 2024U &&
             fixture.ring.snapshot().progress.sample_instants_delivered ==
                 2024U,
         "the joined raw lease feeds one exact 16-bit GPIO frame");
  const packet::PipelineSnapshot before_transport = pipeline.snapshot();
  expect(before_transport.sources[0].items_framed == 506U &&
             before_transport.sources[1].items_framed == 2024U &&
             before_transport.source_bytes[0].payload_bytes_framed == 2024U &&
             before_transport.source_bytes[0].framed_bytes_framed == 2072U &&
             before_transport.source_bytes[1].payload_bytes_framed == 4048U &&
             before_transport.source_bytes[1].framed_bytes_framed == 4096U,
         "item and byte counters derive from each profile-specific frame shape");

  expect(pipeline.serviceReadyFrames(2U).frames_promoted == 2U,
         "equal-coverage ADC and GPIO frames promote fairly");
  protocol::ByteView frame = pipeline.frontFrame();
  std::uint32_t value = 0U;
  expect(frame.size == adc_layout.frame_bytes &&
             frame.data[protocol_v1::kHeaderVersionOffset] == 2U &&
             protocol::loadU32(frame,
                               protocol_v1::kHeaderPayloadLengthOffset,
                               value) &&
             value == adc_layout.payload_bytes &&
             protocol::loadU32(frame, protocol_v1::kHeaderItemCountOffset,
                               value) &&
             value == adc_layout.item_count,
         "the shorter ADC frame carries exact v2 length and item metadata");
  pipeline.releaseFrontFrame();

  frame = pipeline.frontFrame();
  expect(frame.size == gpio_layout.frame_bytes &&
             frame.data[protocol_v1::kHeaderVersionOffset] == 2U &&
             protocol::loadU32(frame, protocol_v1::kHeaderItemCountOffset,
                               value) &&
             value == gpio_layout.item_count &&
             frame.data[protocol_v1::kHeaderSize] == 0x02U &&
             frame.data[protocol_v1::kHeaderSize + 1U] == 0x10U,
         "GPIO frame is v2 with little-endian D8/D20 sample bits");
  pipeline.releaseFrontFrame();

  const packet::PipelineSnapshot transmitted = pipeline.snapshot();
  expect(transmitted.sources[0].items_transmitted == 506U &&
             transmitted.sources[1].items_transmitted == 2024U &&
             transmitted.data_payload_bytes_transmitted == 6072U &&
             transmitted.data_framed_bytes_transmitted == 6168U,
         "transmitted item/payload/framed counters conserve both v2 streams");
  const thingdaq::stats::GpioRawCaptureProgress raw_stats =
      join::statisticsProgress(fixture.ring.snapshot());
  const packer::Snapshot packed_stats = gpio_packer.snapshot(pipeline);
  expect(raw_stats.samples_captured == 2024U &&
             raw_stats.samples_delivered == 2024U &&
             raw_stats.samples_lost == 0U &&
             packed_stats.progress.samples_packed == 2024U &&
             packed_stats.start_epoch_ticks == 777U,
         "join and packer snapshots project into existing GPIO statistics");

  gpio_packer.stopProduction();
  (void)pipeline.stopProduction();
  (void)fixture.ring.cancel(run_id);
  expect(pipeline.readyForStart() && fixture.ring.quiescent() &&
             packed_stats.progress.samples_framed == 2024U &&
             packed_stats.progress.samples_transmitted == 2024U,
         "STOP leaves packet and paired-raw ownership quiescent");
}

}  // namespace

void testV2ConfigureThroughIncrementalParser() {
  for (const auto &timing : protocol_v2::kRateProfiles) {
    for (std::uint8_t mode = 0U; mode < 2U; ++mode) {
      std::array<std::uint8_t, 16U> payload{{3U, 0U, 1U, mode}};
      protocol::MutableByteView bytes{payload.data(), payload.size()};
      protocol::storeU32(bytes, 4U, 4096U);
      protocol::storeU32(bytes, 8U, timing.adc_pair_rate_hz);
      protocol::storeU32(bytes, 12U, timing.gpio_sample_rate_hz);
      protocol::FrameFields fields{};
      fields.version = 2U;
      fields.kind = protocol_v1::FrameKind::kConfigureRequest;
      fields.request_id = 42U;
      protocol::CommandFrame frame{};
      const auto encoded = protocol::encodeFrame(
          fields, {payload.data(), payload.size()}, frame);
      expect(encoded.ok(), "v2 64-byte CONFIGURE encodes at every width/rate");
      if (!encoded.ok()) { continue; }
      for (std::size_t split = 0U; split <= frame.size(); ++split) {
        protocol::IncrementalCommandParser parser{};
        protocol::ParsedCommand command{};
        auto result = parser.feed({frame.data(), split}, command);
        expect(!result.rejection_ready, "first fragment is not rejected");
        if (!result.command_ready) {
          result = parser.feed({frame.data() + split, frame.size() - split}, command);
        }
        expect(result.command_ready && !result.rejection_ready &&
                   command.request.configuration.rate_profile == timing.profile &&
                   static_cast<std::uint8_t>(command.request.configuration.aux_bank_mode) == mode,
               "real command parser accepts v2 CONFIGURE at every fragmentation boundary");
      }
    }
  }
}

void testV2InfoPublishesActiveLayoutAndPriorities() {
  for (const auto &timing : protocol_v2::kRateProfiles) {
    for (std::uint8_t mode = 0U; mode < 2U; ++mode) {
      protocol::Request request{};
      request.kind = protocol_v1::CommandKind::kInfo;
      request.protocol_version = protocol_v2::kProtocolVersion;
      request.request_id = 1U;
      protocol::InfoResponse info{};
      info.applied_configuration.rate_profile = timing.profile;
      info.applied_configuration.aux_bank_mode =
          static_cast<protocol_v2::AuxBankMode>(mode);
      protocol::ControlFrame encoded{};
      expect(protocol::encodeInfoResponse(request, 0U, info, encoded).ok(),
             "INFO encodes at every width/rate");
      const protocol::ByteView payload{
          encoded.data() + protocol_v1::kHeaderSize,
          protocol_v2::kInfoResponsePayloadSize};
      std::uint16_t payload_bytes = 0U;
      expect(protocol::loadU16(payload, protocol_v1::kInfoResponseDataPayloadBytesOffset,
                               payload_bytes) &&
                 payload_bytes == (mode == 1U ? 2024U : 4048U),
             "INFO publishes active ADC payload size");
      expect(payload.data[protocol_v1::kInfoResponseGpioEdmaPriorityOffset] ==
                 (mode == 1U ? 1U : 0U),
             "INFO publishes active GPIO DMA priority");
      expect(payload.data[protocol_v1::kInfoResponseAdcEdmaPrioritiesOffset] ==
                 (mode == 1U ? 3U : 2U) &&
                 payload.data[protocol_v1::kInfoResponseAdcEdmaPrioritiesOffset + 1U] ==
                 (mode == 1U ? 2U : 1U),
             "INFO publishes active ADC DMA priorities");
    }
  }
}

int main() {
  testV2InfoPublishesActiveLayoutAndPriorities();
  testV2ConfigureThroughIncrementalParser();
  testExactSchedulesAndTransactionalRollback();
  testLayoutsAreClosedOverModesAndProfiles();
  testGenerationBarrierPackingAndStopTailConservation();
  testMetadataMismatchAndRingOverrunAreLossNotPublication();
  testGenerationWrapPreservesChronologyAndRejectsStaleCompletions();
  testAuxiliaryPackerUsesDynamicPacketShapesAndCounters();
  if (failures != 0) {
    std::cerr << failures << " portable auxiliary-input checks failed\n";
    return 1;
  }
  std::cout << "portable auxiliary-input scheduler/joiner checks passed\n";
  return 0;
}
