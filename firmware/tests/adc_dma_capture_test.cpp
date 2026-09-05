#include <array>
#include <cstddef>
#include <cstdint>
#include <iostream>
#include <string>

#include "adc_dma_capture.h"

namespace {

namespace capture = thingdaq::adc_capture;
namespace board = thingdaq::board;
namespace constants = thingdaq::protocol_v1;

int failures = 0;

void expect(bool condition, const std::string &message) {
  if (!condition) {
    std::cerr << "FAIL: " << message << '\n';
    ++failures;
  }
}

struct CacheEvent {
  enum class Kind : std::uint8_t {
    kDmaDiscard,
    kCpuInvalidate,
  };

  Kind kind = Kind::kDmaDiscard;
  void *address = nullptr;
  std::size_t bytes = 0U;
};

class FakeCache final : public capture::CacheMaintenance {
 public:
  void discardBeforeDmaWrite(void *address, std::size_t bytes) override {
    record(CacheEvent::Kind::kDmaDiscard, address, bytes);
    if (stop_on_next_discard && stop_ring != nullptr) {
      stop_on_next_discard = false;
      const capture::Snapshot before_stop = stop_ring->snapshot();
      observed_state = before_stop.buffer_states[observed_buffer];
      nested_stop = stop_ring->stop(stop_channels);
    }
  }

  void invalidateBeforeCpuRead(void *address, std::size_t bytes) override {
    record(CacheEvent::Kind::kCpuInvalidate, address, bytes);
  }

  std::array<CacheEvent, 128U> events{};
  std::size_t count = 0U;
  capture::PairCaptureRing *stop_ring = nullptr;
  std::array<capture::ChannelStopState, capture::kConverterCount>
      stop_channels{};
  capture::StopReport nested_stop{};
  capture::BufferState observed_state = capture::BufferState::kFree;
  std::uint8_t observed_buffer = 0U;
  bool stop_on_next_discard = false;

 private:
  void record(CacheEvent::Kind kind, void *address, std::size_t bytes) {
    if (count < events.size()) {
      events[count] = {kind, address, bytes};
    }
    ++count;
  }
};

class FakeCriticalSection final : public capture::CriticalSection {
 public:
  std::uint32_t enter() override {
    const std::uint32_t previous = depth;
    ++depth;
    ++enter_calls;
    return previous;
  }

  void exit(std::uint32_t token) override {
    if (depth == 0U || token + 1U != depth) {
      balanced = false;
      return;
    }
    --depth;
    ++exit_calls;
  }

  std::uint32_t enter_calls = 0U;
  std::uint32_t exit_calls = 0U;
  std::uint32_t depth = 0U;
  bool balanced = true;
};

struct Fixture {
  capture::PairBufferStorage storage{};
  capture::PairOverflowSink overflow{};
  FakeCache cache{};
  FakeCriticalSection critical{};
  capture::PairCaptureRing ring{storage, overflow, cache, critical};
};

std::uint16_t &strided(std::uint16_t *first, std::size_t pair) {
  auto *const bytes = reinterpret_cast<std::uint8_t *>(first);
  return *reinterpret_cast<std::uint16_t *>(
      bytes + pair * sizeof(capture::SamplePair));
}

capture::CompletionResult complete(
    Fixture &fixture, std::uint32_t epoch, std::uint32_t generation,
    std::uint8_t destination, std::uint8_t first_converter) {
  const std::uint8_t second_converter =
      static_cast<std::uint8_t>(1U - first_converter);
  const capture::CompletionResult first =
      fixture.ring.onMajorLoopComplete(first_converter, epoch, generation,
                                       destination);
  expect(first.consumed && !first.pair_ready,
         "one channel completion never publishes a pair buffer");
  return fixture.ring.onMajorLoopComplete(
      second_converter, epoch, generation, destination);
}

void testDirectPairLayoutDualBarrierAndCacheOwnership() {
  Fixture fixture{};
  const capture::PrimeResult primed = fixture.ring.prime(7U);
  expect(primed.ok() && primed.epoch == 7U &&
             primed.active_destination == 0U &&
             primed.queued_destination == 1U,
         "prime reserves one shared active and queued destination");
  expect(fixture.cache.count == board::kAdcDmaRingDepth + 1U,
         "prime discards every ADC buffer and the isolated sink");
  expect(fixture.ring.snapshot().progress.cache_dma_discards ==
                 board::kAdcDmaRingDepth + 1U &&
             fixture.ring.snapshot().progress.cache_cpu_invalidations == 0U,
         "ADC cache telemetry counts each completed ownership operation");
  for (std::size_t index = 0U; index < board::kAdcDmaRingDepth; ++index) {
    expect(fixture.cache.events[index].kind ==
                   CacheEvent::Kind::kDmaDiscard &&
               fixture.cache.events[index].address ==
                   fixture.storage.buffers[index].pairs.data() &&
               fixture.cache.events[index].bytes ==
                   sizeof(capture::PairBuffer),
           "each whole aligned pair buffer crosses the cache boundary");
  }

  std::uint16_t *const adc0 = fixture.ring.destinationHalfword(0U, 0U);
  std::uint16_t *const adc1 = fixture.ring.destinationHalfword(0U, 1U);
  expect(adc0 != nullptr && adc1 == adc0 + 1,
         "ADC0 and ADC1 destinations begin at pair offsets zero and two");
  for (std::size_t pair = 0U; pair < constants::kAdcPairsPerFrame; ++pair) {
    strided(adc0, pair) = static_cast<std::uint16_t>(pair);
    strided(adc1, pair) = static_cast<std::uint16_t>(0x8000U + pair);
  }
  expect(fixture.storage.buffers[0].pairs[17].adc0 == 17U &&
             fixture.storage.buffers[0].pairs[17].adc1 == 0x8011U,
         "four-byte destination strides create direct adc0,adc1 pairs");

  const std::size_t cache_before_completion = fixture.cache.count;
  const capture::CompletionResult adc1_first =
      fixture.ring.onMajorLoopComplete(1U, 7U, 0U, 0U);
  capture::Snapshot snapshot = fixture.ring.snapshot();
  expect(adc1_first.ok() && adc1_first.consumed && !adc1_first.pair_ready &&
             snapshot.ready_depth == 0U &&
             snapshot.buffer_states[0] ==
                 capture::BufferState::kDmaOwned,
         "ADC1-first completion remains DMA-owned behind the barrier");
  expect(fixture.cache.count == cache_before_completion,
         "neither completion ISR performs cache maintenance");

  const capture::CompletionResult paired =
      fixture.ring.onMajorLoopComplete(0U, 7U, 0U, 0U);
  snapshot = fixture.ring.snapshot();
  expect(paired.ok() && paired.pair_ready && !paired.pair_lost &&
             paired.future_destination == 2U &&
             snapshot.ready_depth == 1U &&
             snapshot.progress.paired_major_loops == 1U &&
             snapshot.progress.pairs_captured ==
                 constants::kAdcPairsPerFrame,
         "matching dual completions publish exactly one generation");

  const capture::AcquireResult acquired = fixture.ring.acquireReady();
  expect(acquired.ok() && acquired.handle.buffer_index == 0U &&
             acquired.handle.epoch == 7U &&
             acquired.handle.first_pair == 0U &&
             acquired.handle.pair_count == constants::kAdcPairsPerFrame &&
             acquired.handle.pairs[17].adc0 == 17U &&
             acquired.handle.pairs[17].adc1 == 0x8011U,
         "CPU lease retains direct converter identity and provenance");
  expect(fixture.cache.events[fixture.cache.count - 1U].kind ==
                 CacheEvent::Kind::kCpuInvalidate &&
             fixture.cache.events[fixture.cache.count - 1U].address ==
                 acquired.handle.pairs,
         "CPU invalidation occurs only after the dual barrier");
  expect(fixture.ring.snapshot().progress.cache_cpu_invalidations == 1U,
         "ADC CPU-invalidation telemetry advances with the acquired lease");
  expect(fixture.ring.release(acquired.handle) ==
                 capture::OperationStatus::kOk &&
             fixture.cache.events[fixture.cache.count - 1U].kind ==
                 CacheEvent::Kind::kDmaDiscard,
         "release discards CPU cache before the buffer becomes reusable");
  expect(fixture.ring.snapshot().progress.cache_dma_discards ==
             board::kAdcDmaRingDepth + 2U,
         "ADC DMA-discard telemetry advances before lease recycling");
  expect(fixture.ring.release(acquired.handle) ==
             capture::OperationStatus::kInvalidHandle,
         "a stale lease cannot release the same pair buffer twice");
}

void testExplicitLookaheadReservationsRemainGenerationOrdered() {
  Fixture fixture{};
  const capture::PrimeResult primed = fixture.ring.prime(9U);
  const capture::ReservationResult third =
      fixture.ring.reserveGeneration(9U, 2U);
  const capture::ReservationResult fourth =
      fixture.ring.reserveGeneration(9U, 3U);
  const capture::ReservationResult duplicate =
      fixture.ring.reserveGeneration(9U, 3U);
  const capture::ReservationResult skipped =
      fixture.ring.reserveGeneration(9U, 5U);
  expect(primed.ok() && third.ok() && fourth.ok() && duplicate.ok() &&
             third.destination == 2U && fourth.destination == 3U &&
             duplicate.destination == fourth.destination && !skipped.ok(),
         "explicit lookahead reserves sequential generations idempotently");

  const std::array<capture::ChannelStopState, 2U> stopped{{
      {0U, 0U, primed.active_destination},
      {0U, 0U, primed.active_destination},
  }};
  expect(fixture.ring.stop(stopped).ok() && fixture.ring.quiescent(),
         "unstarted lookahead generations reclaim cleanly at STOP");
}

void testDeterministicRotationAndExactPressureLoss() {
  Fixture fixture{};
  expect(fixture.ring.prime(11U).ok(), "pressure fixture primes");
  for (std::uint32_t generation = 0U;
       generation < board::kAdcDmaRingDepth; ++generation) {
    const capture::CompletionResult paired = complete(
        fixture, 11U, generation,
        static_cast<std::uint8_t>(generation),
        static_cast<std::uint8_t>(generation & 1U));
    expect(paired.pair_ready,
           "each consumer destination becomes ready after both channels");
  }
  capture::Snapshot snapshot = fixture.ring.snapshot();
  expect(snapshot.ready_depth == board::kAdcDmaRingDepth &&
             snapshot.progress.pairs_lost == 0U,
         "all fixed buffers may remain CPU-pending without overwrite");

  const capture::CompletionResult overflow = complete(
      fixture, 11U, static_cast<std::uint32_t>(board::kAdcDmaRingDepth),
      capture::kOverflowDestination, 0U);
  snapshot = fixture.ring.snapshot();
  expect(overflow.pair_lost && !overflow.pair_ready &&
             snapshot.progress.ring_overruns == 1U &&
             snapshot.progress.pairs_lost ==
                 constants::kAdcPairsPerFrame &&
             snapshot.progress.pairs_captured ==
                 (board::kAdcDmaRingDepth + 1U) *
                     constants::kAdcPairsPerFrame,
         "one paired sink generation reports one exact frame of lost pairs");

  const capture::AcquireResult oldest = fixture.ring.acquireReady();
  expect(oldest.ok() && oldest.handle.first_pair == 0U &&
             fixture.ring.release(oldest.handle) ==
                 capture::OperationStatus::kOk,
         "the oldest retained pair generation drains first");
  const capture::CompletionResult next_overflow_first =
      fixture.ring.onMajorLoopComplete(
          0U, 11U,
          static_cast<std::uint32_t>(board::kAdcDmaRingDepth + 1U),
          capture::kOverflowDestination);
  expect(next_overflow_first.future_destination == oldest.handle.buffer_index,
         "a released buffer re-enters the deterministic future schedule");
  const capture::CompletionResult next_overflow_second =
      fixture.ring.onMajorLoopComplete(
          1U, 11U,
          static_cast<std::uint32_t>(board::kAdcDmaRingDepth + 1U),
          capture::kOverflowDestination);
  snapshot = fixture.ring.snapshot();
  expect(next_overflow_second.pair_lost &&
             snapshot.progress.ring_overruns == 2U &&
             snapshot.progress.pairs_lost ==
                 2U * constants::kAdcPairsPerFrame,
         "continued pressure counts every complete lost pair generation");
}

void testErrorsMismatchAndDeferredDiscardRemainLive() {
  Fixture fixture{};
  expect(fixture.ring.prime(19U).ok(), "error fixture primes");
  fixture.ring.recordAdcEtcError(19U, 0x01U, 0x00010000U);
  const std::size_t cache_before = fixture.cache.count;
  const capture::CompletionResult corrupt =
      complete(fixture, 19U, 0U, 0U, 0U);
  capture::Snapshot snapshot = fixture.ring.snapshot();
  expect(corrupt.pair_lost && !corrupt.pair_ready &&
             snapshot.progress.adc_etc_error_events == 1U &&
             snapshot.progress.adc_etc_error_flags == 0x00010000U &&
             snapshot.progress.overwritten_conversions == 1U &&
             snapshot.progress.incomplete_buffers == 1U &&
             snapshot.progress.pairs_lost ==
                 constants::kAdcPairsPerFrame &&
             snapshot.discard_depth == 1U,
         "ADC_ETC evidence taints and drops the whole affected generation");
  expect(fixture.cache.count == cache_before,
         "corrupt completion defers cache cleanup out of the ISR");
  expect(fixture.ring.serviceDiscarded(1U) == 1U &&
             fixture.cache.events[fixture.cache.count - 1U].kind ==
                 CacheEvent::Kind::kDmaDiscard,
         "cooperative service centralizes corrupt-buffer cache cleanup");

  // A whole ADC0 buffer arriving before ADC1 finishes the prior generation is
  // beyond normal 500 ns IRQ skew. Both affected generations are discarded,
  // but future descriptors continue toward the pressure sink.
  const capture::CompletionResult adc0_generation1 =
      fixture.ring.onMajorLoopComplete(0U, 19U, 1U, 1U);
  expect(adc0_generation1.consumed,
         "the first channel may advance one generation independently");
  const capture::CompletionResult adc0_generation2 =
      fixture.ring.onMajorLoopComplete(0U, 19U, 2U, 2U);
  expect(adc0_generation2.consumed && !adc0_generation2.ok(),
         "a channel lead beyond one full major loop is detected");
  const capture::CompletionResult adc1_generation1 =
      fixture.ring.onMajorLoopComplete(1U, 19U, 1U, 1U);
  const capture::CompletionResult adc1_generation2 =
      fixture.ring.onMajorLoopComplete(1U, 19U, 2U, 2U);
  snapshot = fixture.ring.snapshot();
  expect(adc1_generation1.pair_lost && adc1_generation2.pair_lost &&
             snapshot.progress.completion_mismatches != 0U &&
             snapshot.progress.pairs_lost ==
                 3U * constants::kAdcPairsPerFrame &&
             snapshot.running,
         "completion mismatch is counted while the acquisition stays live");

  expect(fixture.ring.serviceDiscarded() == 2U,
         "both mismatch-tainted consumer buffers are reclaimed cooperatively");
}

void testStaleGenerationAndStopAccounting() {
  Fixture fixture{};
  expect(fixture.ring.prime(23U).ok(), "stop fixture primes");
  const capture::CompletionResult first =
      fixture.ring.onMajorLoopComplete(0U, 23U, 0U, 0U);
  const capture::CompletionResult duplicate =
      fixture.ring.onMajorLoopComplete(0U, 23U, 0U, 0U);
  const capture::CompletionResult wrong_epoch =
      fixture.ring.onMajorLoopComplete(1U, 22U, 0U, 0U);
  expect(first.consumed && !duplicate.consumed &&
             !wrong_epoch.consumed,
         "duplicate-generation and prior-epoch completions are rejected");
  capture::Snapshot snapshot = fixture.ring.snapshot();
  expect(snapshot.progress.channel_major_loops[0] == 1U &&
             snapshot.progress.channel_major_loops[1] == 0U &&
             snapshot.progress.stale_completions == 2U,
         "stale interrupts cannot advance ownership or channel totals");

  const std::array<capture::ChannelStopState, 2U> stopped{{
      {1U, 17U, 1U},
      {0U, 16U, 0U},
  }};
  const capture::StopReport report = fixture.ring.stop(stopped);
  snapshot = fixture.ring.snapshot();
  expect(report.ok() && report.pairs_discarded ==
                            constants::kAdcPairsPerFrame + 17U &&
             snapshot.progress.pairs_lost ==
                 constants::kAdcPairsPerFrame + 17U &&
             snapshot.progress.stop_discarded_pairs ==
                 constants::kAdcPairsPerFrame + 17U &&
             snapshot.progress.incomplete_conversions ==
                 constants::kAdcPairsPerFrame + 1U &&
             snapshot.progress.completion_mismatches != 0U &&
             snapshot.quiescent,
         "STOP counts each incomplete generation and converter result exactly");
  expect(fixture.critical.balanced && fixture.critical.depth == 0U &&
             fixture.critical.enter_calls == fixture.critical.exit_calls,
         "all main-context ownership transitions balance the IRQ lock");
}

void testDmaGenerationWrapKeepsThePairBarrierUnambiguous() {
  Fixture fixture{};
  constexpr std::uint32_t first_generation = 0xFFFFFFFEU;
  const capture::PrimeResult primed =
      fixture.ring.prime(29U, first_generation, 9000U);
  expect(primed.ok() && primed.active_generation == first_generation &&
             primed.queued_generation == 0xFFFFFFFFU,
         "prime can seed a near-wrap DMA generation for bounded testing");
  const capture::CompletionResult before_wrap = complete(
      fixture, 29U, first_generation, primed.active_destination, 0U);
  const capture::CompletionResult at_wrap = complete(
      fixture, 29U, 0xFFFFFFFFU, primed.queued_destination, 1U);
  expect(before_wrap.pair_ready && before_wrap.future_generation == 0U &&
             at_wrap.pair_ready && at_wrap.future_generation == 1U,
         "per-channel generation arithmetic wraps modulo 2^32");
  const capture::AcquireResult first = fixture.ring.acquireReady();
  const capture::AcquireResult second = fixture.ring.acquireReady();
  expect(first.ok() && second.ok() && first.handle.first_pair == 9000U &&
             second.handle.first_pair ==
                 9000U + constants::kAdcPairsPerFrame,
         "64-bit pair chronology remains monotonic across DMA generation wrap");
  expect(fixture.ring.release(first.handle) ==
                 capture::OperationStatus::kOk &&
             fixture.ring.release(second.handle) ==
                 capture::OperationStatus::kOk,
         "wrapped generations retain independent valid leases");
}

void testStopDoesNotInventLossForUnstartedTaintedGenerations() {
  Fixture mismatch{};
  expect(mismatch.ring.prime(31U).ok(), "mismatch STOP fixture primes");
  (void)mismatch.ring.onMajorLoopComplete(0U, 31U, 0U, 0U);
  (void)mismatch.ring.onMajorLoopComplete(0U, 31U, 1U, 1U);
  const std::array<capture::ChannelStopState, 2U> stopped{{
      {2U, 0U, 2U},
      {0U, 0U, 0U},
  }};
  const capture::StopReport mismatch_report = mismatch.ring.stop(stopped);
  expect(mismatch_report.ok() &&
             mismatch_report.pairs_discarded ==
                 2U * constants::kAdcPairsPerFrame,
         "STOP does not invent pair loss for queued tainted generations");

  Fixture overwrite{};
  expect(overwrite.ring.prime(37U).ok(), "overwrite STOP fixture primes");
  overwrite.ring.recordAdcEtcError(37U, 0x01U, 0x00010000U);
  const std::array<capture::ChannelStopState, 2U> no_dma_progress{{
      {0U, 0U, 0U},
      {0U, 0U, 0U},
  }};
  const capture::StopReport overwrite_report =
      overwrite.ring.stop(no_dma_progress);
  const capture::Snapshot overwrite_snapshot = overwrite.ring.snapshot();
  expect(overwrite_report.ok() && overwrite_report.pairs_discarded == 1U &&
             overwrite_snapshot.progress.pairs_lost == 1U &&
             overwrite_snapshot.progress.overwritten_conversions == 1U,
         "a latched ADC_ETC overwrite contributes one evidenced lost pair");
}

void testStopAcrossEveryBufferOwnershipState() {
  {
    Fixture fixture{};
    expect(fixture.ring.prime(41U).ok(),
           "FREE/DMA_OWNED STOP fixture primes");
    const capture::Snapshot before = fixture.ring.snapshot();
    const std::array<capture::ChannelStopState, 2U> stopped{{
        {0U, 0U, 0U},
        {0U, 0U, 0U},
    }};
    const capture::StopReport report = fixture.ring.stop(stopped);
    const capture::Snapshot after = fixture.ring.snapshot();
    expect(before.buffer_states[0] == capture::BufferState::kDmaOwned &&
               before.buffer_states[1] == capture::BufferState::kDmaOwned &&
               before.buffer_states[2] == capture::BufferState::kFree &&
               report.ok() && report.buffers_discarded == 2U &&
               report.pairs_discarded == 0U && after.quiescent,
           "STOP reclaims DMA_OWNED buffers and preserves untouched FREE buffers without invented loss");
  }

  {
    Fixture fixture{};
    expect(fixture.ring.prime(43U).ok(), "READY STOP fixture primes");
    expect(complete(fixture, 43U, 0U, 0U, 0U).pair_ready,
           "READY STOP fixture publishes one buffer");
    const std::array<capture::ChannelStopState, 2U> stopped{{
        {1U, 0U, 1U},
        {1U, 0U, 1U},
    }};
    const capture::StopReport report = fixture.ring.stop(stopped);
    capture::Snapshot snapshot = fixture.ring.snapshot();
    expect(report.ok() && report.ready_buffers_to_drain == 1U &&
               report.reading_buffers_to_release == 0U &&
               snapshot.ready_depth == 1U && !snapshot.quiescent,
           "STOP preserves a complete READY buffer for post-trigger drain");
    const capture::AcquireResult ready = fixture.ring.acquireReady();
    expect(ready.ok() && fixture.ring.release(ready.handle) ==
                             capture::OperationStatus::kOk &&
               fixture.ring.quiescent(),
           "a READY lease remains readable and releasable after STOP");
  }

  {
    Fixture fixture{};
    expect(fixture.ring.prime(47U).ok(), "READING STOP fixture primes");
    expect(complete(fixture, 47U, 0U, 0U, 1U).pair_ready,
           "READING STOP fixture publishes one buffer");
    const capture::AcquireResult reading = fixture.ring.acquireReady();
    const std::array<capture::ChannelStopState, 2U> stopped{{
        {1U, 0U, 1U},
        {1U, 0U, 1U},
    }};
    const capture::StopReport report = fixture.ring.stop(stopped);
    const capture::Snapshot snapshot = fixture.ring.snapshot();
    expect(reading.ok() && report.ok() &&
               report.reading_buffers_to_release == 1U &&
               snapshot.reading_depth == 1U && !snapshot.quiescent,
           "STOP reports but never steals an active READING lease");
    expect(fixture.ring.release(reading.handle) ==
                   capture::OperationStatus::kOk &&
               fixture.ring.quiescent(),
           "the pre-STOP READING lease releases cleanly afterward");
  }

  {
    Fixture fixture{};
    expect(fixture.ring.prime(53U).ok(), "RELEASING STOP fixture primes");
    expect(complete(fixture, 53U, 0U, 0U, 0U).pair_ready,
           "RELEASING STOP fixture publishes one buffer");
    const capture::AcquireResult releasing = fixture.ring.acquireReady();
    fixture.cache.stop_ring = &fixture.ring;
    fixture.cache.stop_channels = {{
        {1U, 0U, 1U},
        {1U, 0U, 1U},
    }};
    fixture.cache.observed_buffer = releasing.handle.buffer_index;
    fixture.cache.stop_on_next_discard = true;
    const capture::OperationStatus released =
        fixture.ring.release(releasing.handle);
    expect(released == capture::OperationStatus::kOk &&
               fixture.cache.observed_state ==
                   capture::BufferState::kReleasing &&
               fixture.cache.nested_stop.ok() && fixture.ring.quiescent(),
           "a concurrent STOP observes RELEASING ownership without invalidating the release");
  }

  {
    Fixture fixture{};
    expect(fixture.ring.prime(59U).ok(),
           "DISCARD_PENDING STOP fixture primes");
    fixture.ring.recordAdcEtcError(59U, 0x01U, 0x00010000U);
    expect(complete(fixture, 59U, 0U, 0U, 1U).pair_lost,
           "ADC_ETC evidence produces a DISCARD_PENDING buffer");
    const capture::Snapshot pending = fixture.ring.snapshot();
    const std::array<capture::ChannelStopState, 2U> stopped{{
        {1U, 0U, 1U},
        {1U, 0U, 1U},
    }};
    const capture::StopReport report = fixture.ring.stop(stopped);
    const capture::Snapshot after = fixture.ring.snapshot();
    expect(pending.discard_depth == 1U && report.ok() && after.quiescent &&
               after.progress.pairs_lost == constants::kAdcPairsPerFrame &&
               after.progress.stop_discarded_pairs == 0U,
           "STOP services DISCARD_PENDING ownership without double-counting its prior loss");
  }

  {
    Fixture fixture{};
    expect(fixture.ring.prime(61U).ok(), "overflow STOP fixture primes");
    for (std::uint32_t generation = 0U;
         generation < board::kAdcDmaRingDepth; ++generation) {
      expect(complete(fixture, 61U, generation,
                      static_cast<std::uint8_t>(generation), 0U)
                 .pair_ready,
             "overflow STOP fixture fills one retained ring buffer");
    }
    const std::array<capture::ChannelStopState, 2U> stopped{{
        {static_cast<std::uint32_t>(board::kAdcDmaRingDepth), 10U,
         capture::kOverflowDestination},
        {static_cast<std::uint32_t>(board::kAdcDmaRingDepth), 7U,
         capture::kOverflowDestination},
    }};
    const capture::StopReport report = fixture.ring.stop(stopped);
    capture::Snapshot snapshot = fixture.ring.snapshot();
    expect(report.ok() && report.pairs_discarded == 10U &&
               report.ready_buffers_to_drain == board::kAdcDmaRingDepth &&
               snapshot.progress.ring_overruns == 1U &&
               snapshot.progress.incomplete_conversions == 3U,
           "STOP accounts partial overflow-sink ownership by exact max/difference pairs");
    for (std::size_t index = 0U; index < board::kAdcDmaRingDepth; ++index) {
      const capture::AcquireResult ready = fixture.ring.acquireReady();
      expect(ready.ok() && fixture.ring.release(ready.handle) ==
                               capture::OperationStatus::kOk,
             "each retained buffer drains after overflow STOP");
    }
    snapshot = fixture.ring.snapshot();
    expect(snapshot.quiescent,
           "all ownership states converge to quiescent after bounded drain");
  }
}

void testReleaseLookaheadRetainsForegroundHeadroom() {
  for (const std::uint32_t depth : {4U, 6U}) {
    Fixture fixture{};
    expect(fixture.ring.prime(71U, 0U, 0U, 506U).ok(),
           "INPUT-rate headroom fixture primes");
    for (std::uint32_t generation = 2U; generation < depth; ++generation) {
      expect(fixture.ring.reserveGeneration(71U, generation).ok(),
             "hardware look-ahead is reserved before START");
    }
    // Three completions arrive while foreground work is delayed. Hardware
    // keeps appending one future descriptor per paired completion.
    capture::ReservationResult future{};
    for (std::uint32_t generation = 0U; generation < 3U; ++generation) {
      for (std::uint8_t converter = 0U; converter < 2U; ++converter) {
        expect(fixture.ring.onMajorLoopComplete(
                   converter, 71U, generation,
                   static_cast<std::uint8_t>(generation)).ok(),
               "paired completion remains valid during foreground latency");
      }
      future = fixture.ring.reserveGeneration(71U, generation + depth);
      expect(future.ok(), "future generation reservation remains live");
    }
    expect((future.destination == capture::kOverflowDestination) == (depth == 6U),
           "four-entry release look-ahead survives latency that exhausts six-entry look-ahead");
    expect(fixture.ring.snapshot().ready_depth == 3U,
           "all three completed buffers remain available for framing");
  }
}

}  // namespace

int main() {
  testDirectPairLayoutDualBarrierAndCacheOwnership();
  testExplicitLookaheadReservationsRemainGenerationOrdered();
  testDeterministicRotationAndExactPressureLoss();
  testErrorsMismatchAndDeferredDiscardRemainLive();
  testStaleGenerationAndStopAccounting();
  testDmaGenerationWrapKeepsThePairBarrierUnambiguous();
  testStopDoesNotInventLossForUnstartedTaintedGenerations();
  testStopAcrossEveryBufferOwnershipState();
  testReleaseLookaheadRetainsForegroundHeadroom();
  if (failures != 0) {
    std::cerr << failures << " ADC DMA capture assertion(s) failed\n";
    return 1;
  }
  std::cout << "ADC DMA capture tests passed\n";
  return 0;
}
