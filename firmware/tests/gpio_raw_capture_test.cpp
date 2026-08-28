#include <array>
#include <cstddef>
#include <cstdint>
#include <iostream>
#include <limits>
#include <string>

#include "gpio_raw_capture.h"

namespace {

namespace board = teensy_daq::board;
namespace capture = teensy_daq::gpio_capture;
namespace constants = teensy_daq::protocol_v1;
namespace stats = teensy_daq::stats;

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
  }

  void invalidateBeforeCpuRead(void *address, std::size_t bytes) override {
    record(CacheEvent::Kind::kCpuInvalidate, address, bytes);
  }

  std::array<CacheEvent, 64U> events{};
  std::size_t count = 0U;

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
    ++enter_calls;
    const std::uint32_t previous = depth;
    ++depth;
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
  capture::RawBufferStorage storage{};
  capture::RawOverflowSink overflow{};
  FakeCache cache{};
  FakeCriticalSection critical{};
  capture::RawCaptureRing ring{storage, overflow, cache, critical};
};

void testSelectiveInputRemap() {
  volatile std::uint32_t gpr27 = 0xF5A55A5FU;
  volatile std::uint32_t gdir = 0xA55AA55AU;
  const std::uint32_t original_gpr27 = gpr27;
  const std::uint32_t original_gdir = gdir;

  capture::selectStandardGpioInputs(gpr27, gdir);
  expect(gpr27 ==
                 (original_gpr27 & ~board::kGpio7ToGpio2Gpr27ClearMask) &&
             gdir == (original_gdir & ~board::kGpio2PsrCaptureMask),
         "pin remap clears only D6-D13 alias and direction bits");
  expect(((gpr27 ^ original_gpr27) &
          ~board::kGpio7ToGpio2Gpr27ClearMask) == 0U &&
             ((gdir ^ original_gdir) & ~board::kGpio2PsrCaptureMask) == 0U,
         "unrelated GPR27 and GPIO2_GDIR bits remain untouched");
}

void testOwnershipCacheAndContinuousOverflow() {
  Fixture fixture{};
  const capture::PrimeResult primed = fixture.ring.prime();
  expect(primed.ok() && primed.active_destination == 0U &&
             primed.queued_destination == 1U,
         "prime reserves two distinct DMA destinations");
  expect(fixture.cache.count == board::kGpioRawDmaRingDepth + 1U,
         "prime discards every consumer buffer and the overflow sink");
  for (std::size_t index = 0U;
       index < board::kGpioRawDmaRingDepth; ++index) {
    expect(fixture.cache.events[index].kind ==
                   CacheEvent::Kind::kDmaDiscard &&
               fixture.cache.events[index].address ==
                   fixture.storage.buffers[index].words.data() &&
               fixture.cache.events[index].bytes == sizeof(capture::RawBuffer),
           "initial cache operations prepare full aligned DMA buffers");
  }
  expect(fixture.cache.events[board::kGpioRawDmaRingDepth].address ==
                 fixture.overflow.words.data() &&
             fixture.cache.events[board::kGpioRawDmaRingDepth].bytes ==
                 sizeof(capture::RawOverflowSink),
         "the DMA-only overflow destination occupies one isolated cache line");

  const std::size_t cache_calls_before_completion = fixture.cache.count;
  capture::MajorLoopResult completed = fixture.ring.onMajorLoopComplete();
  expect(completed.ok() && completed.completed_destination == 0U &&
             completed.active_destination == 1U &&
             completed.queued_destination == 2U &&
             completed.completed_first_sample == 0U,
         "first major loop rotates active and queued DMA ownership");
  expect(fixture.cache.count == cache_calls_before_completion,
         "major-loop ISR transition performs no cache maintenance");

  const capture::AcquireResult first = fixture.ring.acquireReady();
  expect(first.ok() && first.handle.buffer_index == 0U &&
             first.handle.first_sample == 0U &&
             first.handle.sample_count == constants::kGpioSamplesPerFrame &&
             first.handle.words == fixture.storage.buffers[0].words.data(),
         "CPU acquires the oldest complete raw buffer with exact provenance");
  expect(fixture.cache.events[fixture.cache.count - 1U].kind ==
                 CacheEvent::Kind::kCpuInvalidate &&
             fixture.cache.events[fixture.cache.count - 1U].address ==
                 first.handle.words &&
             fixture.cache.events[fixture.cache.count - 1U].bytes ==
                 sizeof(capture::RawBuffer),
         "CPU ownership invalidates the completed DMA buffer");

  completed = fixture.ring.onMajorLoopComplete();
  expect(completed.ok() && completed.completed_destination == 1U &&
             completed.queued_destination == 3U,
         "DMA advances while the first buffer is being packed");
  completed = fixture.ring.onMajorLoopComplete();
  expect(completed.ok() && completed.completed_destination == 2U &&
             completed.queued_destination == capture::kOverflowDestination,
         "pressure queues the DMA-only sink instead of a CPU-owned buffer");
  completed = fixture.ring.onMajorLoopComplete();
  expect(completed.ok() && completed.completed_destination == 3U &&
             completed.active_destination == capture::kOverflowDestination,
         "all four consumer buffers can remain owned while capture continues");

  capture::Snapshot snapshot = fixture.ring.snapshot();
  expect(snapshot.buffer_states[0] == capture::BufferState::kPacking &&
             snapshot.ready_depth == 3U && snapshot.running &&
             snapshot.progress.samples_lost == 0U,
         "entering the sink does not overwrite or prematurely count data");

  completed = fixture.ring.onMajorLoopComplete();
  expect(completed.ok() &&
             completed.completed_destination == capture::kOverflowDestination,
         "a complete sink loop remains a valid live acquisition transition");
  snapshot = fixture.ring.snapshot();
  expect(snapshot.progress.raw_ring_overruns == 1U &&
             snapshot.progress.samples_lost ==
                 constants::kGpioSamplesPerFrame &&
             snapshot.progress.samples_captured ==
                 5U * constants::kGpioSamplesPerFrame,
         "one overflow major loop reports its exact lost-sample count");

  expect(fixture.ring.release(first.handle) == capture::OperationStatus::kOk,
         "packer releases its cache-cleaned buffer explicitly");
  expect(fixture.cache.events[fixture.cache.count - 1U].kind ==
                 CacheEvent::Kind::kDmaDiscard &&
             fixture.cache.events[fixture.cache.count - 1U].address ==
                 first.handle.words &&
             fixture.cache.events[fixture.cache.count - 1U].bytes ==
                 sizeof(capture::RawBuffer),
         "release discards CPU cache before the buffer becomes FREE");
  expect(fixture.ring.release(first.handle) ==
             capture::OperationStatus::kInvalidHandle,
         "stale leases cannot free a buffer twice");

  completed = fixture.ring.onMajorLoopComplete();
  expect(completed.ok() &&
             completed.queued_destination == first.handle.buffer_index,
         "a released buffer re-enters the look-ahead DMA schedule");
  completed = fixture.ring.onMajorLoopComplete();
  expect(completed.ok() &&
             completed.active_destination == first.handle.buffer_index,
         "the look-ahead sink absorbs pressure until the free buffer is active");
  snapshot = fixture.ring.snapshot();
  expect(snapshot.progress.raw_ring_overruns == 3U &&
             snapshot.progress.samples_lost ==
                 3U * constants::kGpioSamplesPerFrame &&
             snapshot.buffer_states[first.handle.buffer_index] ==
                 capture::BufferState::kDmaActive,
         "continued pressure counts every lost block and preserves ownership");
  expect(fixture.critical.balanced && fixture.critical.depth == 0U &&
             fixture.critical.enter_calls == fixture.critical.exit_calls,
         "main-context transitions leave the interrupt lock balanced");
}

void testStopDrainsCompleteBuffersAndCountsPartialLoss() {
  Fixture fixture{};
  expect(fixture.ring.prime().ok(), "stop fixture primes");
  expect(fixture.ring.onMajorLoopComplete().ok(),
         "stop fixture completes one whole buffer");
  const capture::AcquireResult packing = fixture.ring.acquireReady();
  expect(packing.ok(), "stop fixture owns one packing lease");

  const capture::StopReport stopped = fixture.ring.stop(17U);
  capture::Snapshot snapshot = fixture.ring.snapshot();
  expect(stopped.ok() && stopped.active_samples_discarded == 17U &&
             stopped.ready_buffers_to_drain == 0U &&
             stopped.packing_buffers_to_release == 1U,
         "STOP reports exact partial and outstanding CPU ownership");
  expect(!snapshot.running && !snapshot.quiescent &&
             snapshot.progress.samples_captured ==
                 constants::kGpioSamplesPerFrame + 17U &&
             snapshot.progress.samples_lost == 17U &&
             snapshot.progress.stop_discarded_samples == 17U &&
             snapshot.progress.raw_ring_overruns == 0U,
         "STOP distinguishes a partial shutdown discard from ring pressure");
  expect(fixture.ring.prime().status ==
             capture::OperationStatus::kNotQuiescent,
         "a new run cannot invalidate an outstanding packing lease");
  expect(fixture.ring.release(packing.handle) == capture::OperationStatus::kOk &&
             fixture.ring.quiescent(),
         "releasing the final stopped-run lease makes the ring restart-safe");
  expect(fixture.ring.prime().ok(),
         "a quiescent ring can start a new ownership epoch");
  expect(fixture.ring.release(packing.handle) ==
             capture::OperationStatus::kInvalidHandle,
         "a previous-run lease cannot affect the restarted ring");
}

void testStopCountsPartialOverflowAndPreservesReadyOrder() {
  Fixture fixture{};
  expect(fixture.ring.prime().ok(), "overflow-stop fixture primes");
  for (std::size_t index = 0U;
       index < board::kGpioRawDmaRingDepth; ++index) {
    expect(fixture.ring.onMajorLoopComplete().ok(),
           "overflow-stop fixture completes each consumer buffer");
  }

  const capture::StopReport stopped = fixture.ring.stop(19U);
  capture::Snapshot snapshot = fixture.ring.snapshot();
  expect(stopped.ok() && stopped.active_samples_discarded == 19U &&
             stopped.ready_buffers_to_drain ==
                 board::kGpioRawDmaRingDepth &&
             snapshot.progress.raw_ring_overruns == 1U &&
             snapshot.progress.samples_lost == 19U &&
             snapshot.progress.stop_discarded_samples == 0U,
         "STOP counts a partial pressure-sink loop as exact overrun loss");

  for (std::size_t expected = 0U;
       expected < board::kGpioRawDmaRingDepth; ++expected) {
    const capture::AcquireResult ready = fixture.ring.acquireReady();
    expect(ready.ok() &&
               ready.handle.first_sample ==
                   expected * constants::kGpioSamplesPerFrame &&
               fixture.ring.release(ready.handle) ==
                   capture::OperationStatus::kOk,
           "STOP preserves complete raw buffers in source-sample order");
  }
  expect(fixture.ring.quiescent(),
         "draining stopped ready buffers returns every owner to FREE");
}

void testLateCompletionAfterStopCannotReopenOwnership() {
  Fixture fixture{};
  expect(fixture.ring.prime().ok(), "late-completion fixture primes");
  expect(fixture.ring.onMajorLoopComplete().ok(),
         "late-completion fixture retains one ready buffer");
  const capture::StopReport stopped = fixture.ring.stop(0U);
  const capture::Snapshot before_late = fixture.ring.snapshot();
  const std::size_t cache_calls_before_late = fixture.cache.count;

  const capture::MajorLoopResult late =
      fixture.ring.onMajorLoopComplete();
  const capture::Snapshot after_late = fixture.ring.snapshot();
  expect(stopped.ok() && late.status == capture::OperationStatus::kNotRunning,
         "a completion racing after STOP is rejected as stale");
  expect(!after_late.running && after_late.ready_depth == 1U &&
             after_late.progress.major_loops_completed ==
                 before_late.progress.major_loops_completed &&
             after_late.progress.samples_captured ==
                 before_late.progress.samples_captured &&
             after_late.progress.samples_lost ==
                 before_late.progress.samples_lost &&
             fixture.cache.count == cache_calls_before_late,
         "a stale completion changes no owner, counter, or cache boundary");

  const capture::AcquireResult retained = fixture.ring.acquireReady();
  expect(retained.ok() && retained.handle.first_sample == 0U &&
             fixture.ring.release(retained.handle) ==
                 capture::OperationStatus::kOk &&
             fixture.ring.quiescent(),
         "the pre-STOP complete buffer remains drainable after the race");
}

void testCommonStatisticsProjectionAndSaturation() {
  stats::Statistics statistics{};
  stats::DataPathProgress packets{};
  packets.gpio.items_dropped = 9U;
  statistics.publishDataPath(packets);

  stats::GpioRawCaptureProgress raw{};
  raw.major_loops_completed = 7U;
  raw.raw_ring_overruns = 2U;
  raw.samples_captured = 7U * constants::kGpioSamplesPerFrame;
  raw.samples_lost = 2U * constants::kGpioSamplesPerFrame;
  raw.ready_high_water = board::kGpioRawDmaRingDepth;
  statistics.publishGpioRawCapture(raw);

  stats::Snapshot snapshot = statistics.snapshot();
  expect(snapshot.gpio_raw_capture.raw_ring_overruns == 2U &&
             snapshot.gpio_raw_capture.samples_lost == raw.samples_lost &&
             snapshot.gpio_items_dropped == raw.samples_lost + 9U,
         "common statistics retain raw overruns and project all GPIO losses");

  packets.gpio.items_dropped = std::numeric_limits<std::uint64_t>::max();
  statistics.publishDataPath(packets);
  snapshot = statistics.snapshot();
  expect(snapshot.gpio_items_dropped ==
             std::numeric_limits<std::uint64_t>::max(),
         "packet plus raw GPIO loss projection saturates without wrapping");
}

}  // namespace

int main() {
  testSelectiveInputRemap();
  testOwnershipCacheAndContinuousOverflow();
  testStopDrainsCompleteBuffersAndCountsPartialLoss();
  testStopCountsPartialOverflowAndPreservesReadyOrder();
  testLateCompletionAfterStopCannotReopenOwnership();
  testCommonStatisticsProjectionAndSaturation();
  if (failures != 0) {
    std::cerr << failures << " raw GPIO capture assertion(s) failed\n";
    return 1;
  }
  std::cout << "raw GPIO capture tests passed\n";
  return 0;
}
