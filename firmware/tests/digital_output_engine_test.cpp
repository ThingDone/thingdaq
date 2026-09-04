#include <array>
#include <cstddef>
#include <cstdint>
#include <iostream>
#include <string>

#include "digital_output_engine.h"

namespace {

namespace board = thingdaq::board;
namespace output = thingdaq::digital_output;
namespace v2 = thingdaq::protocol_v2;

int failures = 0;

void expect(bool condition, const std::string &message) {
  if (!condition) {
    std::cerr << "FAIL: " << message << '\n';
    ++failures;
  }
}

class RecordingCache final : public output::CacheMaintenance {
 public:
  void flushBeforeDmaRead(const void *address, std::size_t bytes) override {
    last_address = address;
    last_bytes = bytes;
    ++calls;
  }

  const void *last_address = nullptr;
  std::size_t last_bytes = 0U;
  std::uint32_t calls = 0U;
};

class RecordingCritical final : public output::CriticalSection {
 public:
  std::uint32_t enter() override {
    ++entries;
    ++depth;
    return depth;
  }

  void exit(std::uint32_t token) override {
    expect(token == depth && depth != 0U,
           "critical-section token and nesting are balanced");
    --depth;
    ++exits;
  }

  std::uint32_t entries = 0U;
  std::uint32_t exits = 0U;
  std::uint32_t depth = 0U;
};

struct Fixture {
  output::ProgramStorage program_storage{};
  output::ProgramStore program{program_storage};
  output::DmaBlockStorage dma_storage{};
  RecordingCache cache{};
  RecordingCritical critical{};
  output::Engine engine{program, dma_storage, cache, critical};
};

std::uint32_t checksumFor(output::ProgramStore &program) {
  return program.canonicalChecksum();
}

void testProgramValidationChecksumAndImmutability() {
  Fixture fixture{};
  expect(fixture.engine.begin(0U, 1U, 0U) ==
             output::ProgramStatus::kInvalidGeneration,
         "zero upload generation is rejected");
  expect(fixture.engine.begin(11U, 2U, 0x100U) ==
             output::ProgramStatus::kInvalidSegment,
         "idle state rejects bits outside the eight-bit bank");
  expect(fixture.engine.begin(11U, 2U, 0U) == output::ProgramStatus::kOk,
         "valid upload begins in fixed storage");
  expect(fixture.engine.begin(11U, 2U, 0U) ==
                 output::ProgramStatus::kInvalidGeneration &&
             fixture.engine.begin(10U, 2U, 0U) ==
                 output::ProgramStatus::kOk,
         "replacement BEGIN requires a distinct loading generation");
  expect(fixture.engine.append(12U, {2U, 1U}) ==
             output::ProgramStatus::kInvalidGeneration,
         "mixed upload generation is rejected");
  expect(fixture.engine.append(10U, {0U, 1U}) ==
             output::ProgramStatus::kInvalidSegment,
         "zero-duration segment is rejected");
  expect(fixture.engine.append(10U, {2U, 1U}) ==
             output::ProgramStatus::kOk &&
             fixture.engine.append(10U, {1U, 1U}) ==
                 output::ProgramStatus::kInvalidSegment &&
             fixture.engine.append(10U, {1U, 5U}) ==
                 output::ProgramStatus::kOk,
         "canonical segments reject adjacent equal states");

  const std::uint32_t checksum = checksumFor(fixture.program);
  expect(checksum == 0x0058000AU,
         "canonical checksum is Adler-32 over little-endian records");
  expect(fixture.engine.commit(10U, 1U, checksum) ==
             output::ProgramStatus::kSegmentCountMismatch &&
             fixture.engine.commit(10U, 2U, checksum + 1U) ==
                 output::ProgramStatus::kChecksumMismatch &&
             fixture.engine.commit(10U, 2U, checksum) ==
                 output::ProgramStatus::kOk,
         "commit validates count and end-to-end checksum");
  expect(fixture.engine.append(10U, {1U, 7U}) ==
             output::ProgramStatus::kInvalidLifecycle &&
             fixture.program.snapshot().immutable &&
             fixture.program.snapshot().segment_count == 2U,
         "committed bytes are immutable until CLEAR");

  Fixture capacity{};
  expect(capacity.engine.begin(12U, 1U, 0U) ==
             output::ProgramStatus::kOk,
         "capacity fixture begins");
  for (std::size_t index = 0U; index < output::kSegmentCapacity; ++index) {
    expect(capacity.engine.append(
               12U, {1U, static_cast<std::uint32_t>(index & 1U)}) ==
               output::ProgramStatus::kOk,
           "every fixed-capacity segment slot is usable");
  }
  expect(capacity.engine.append(12U, {1U, 0U}) ==
             output::ProgramStatus::kCapacityExceeded &&
             capacity.engine.commit(12U, output::kSegmentCapacity,
                                    checksumFor(capacity.program)) ==
                 output::ProgramStatus::kOk,
         "the 1,024-segment store rejects overflow and commits in place");
}

void testFiniteExpansionOwnershipAndCompletionHold() {
  Fixture fixture{};
  expect(fixture.engine.begin(21U, 2U, 0U) == output::ProgramStatus::kOk &&
             fixture.engine.append(21U, {2U, 1U}) ==
                 output::ProgramStatus::kOk &&
             fixture.engine.append(21U, {1U, 5U}) ==
                 output::ProgramStatus::kOk,
         "finite program uploads");
  expect(fixture.engine.commit(21U, 2U, checksumFor(fixture.program)) ==
             output::ProgramStatus::kOk &&
             fixture.engine.arm(21U) == output::OperationStatus::kOk,
         "finite program commits and arms");

  output::Snapshot armed = fixture.engine.snapshot();
  expect(armed.state == v2::OutputState::kArmed &&
             armed.bank_mode == v2::OutputBankMode::kOutput &&
             armed.ready_depth == 1U && armed.reading_depth == 0U &&
             armed.refill_lead == 6U && armed.expansion_finished &&
             fixture.cache.calls == 1U && fixture.cache.last_bytes == 24U,
         "ARM prefills the complete bounded finite schedule before START");
  const std::uint8_t ready = static_cast<std::uint8_t>(
      armed.blocks[0].state == output::BlockState::kDmaReady ? 0U : 1U);
  expect(fixture.engine.blockWords(ready)[0] == 0x00800000U &&
             fixture.engine.blockWords(ready)[1] == 0U &&
             fixture.engine.blockWords(ready)[2] == 0x00020000U &&
             fixture.engine.blockWords(ready)[3] == 0x00020000U,
         "logical absolute states expand to bounded GPIO1 toggle words");

  expect(fixture.engine.prepareStart(91U, 1000U) ==
             output::StartStatus::kOk,
         "START preparation promotes one immutable block to DMA_READING");
  output::Snapshot prepared = fixture.engine.snapshot();
  expect(prepared.prepared && prepared.reading_depth == 1U &&
             prepared.state == v2::OutputState::kArmed,
         "preparation does not expose RUNNING before common clock commit");
  fixture.engine.rollbackPreparedStart();
  prepared = fixture.engine.snapshot();
  expect(!prepared.prepared && prepared.ready_depth == 1U &&
             prepared.run_id == 0U &&
             prepared.telemetry.dma_states_emitted == 0U,
         "pre-clock rollback restores DMA_READY without an output event");

  expect(fixture.engine.prepareStart(91U, 1000U) ==
             output::StartStatus::kOk,
         "rolled-back program remains reusable");
  fixture.engine.commitCommonStart();
  output::Snapshot running = fixture.engine.snapshot();
  const std::uint8_t reading = running.reading_block;
  const std::uint32_t lease = running.blocks[reading].lease;
  expect(running.state == v2::OutputState::kRunning &&
             fixture.engine.onDmaBlockComplete(reading, 20U, lease) ==
                 output::OperationStatus::kInvalidCompletion &&
             fixture.engine.onDmaBlockComplete(reading, 21U, lease) ==
                 output::OperationStatus::kOk,
         "generation-indexed completion rejects stale DMA then advances ownership");
  const output::Snapshot held = fixture.engine.snapshot();
  expect(held.state == v2::OutputState::kHeld &&
             held.last_emitted_state_mask == 5U &&
             held.telemetry.dma_states_emitted == 6U &&
             held.telemetry.transitions_emitted == 4U &&
             held.telemetry.completed_repeats == 2U &&
             held.telemetry.blocks_completed == 1U &&
             held.current_segment_index == 1U &&
             held.current_segment_remaining == 0U &&
             held.completion_tick == 1048U && held.hold_tick == 1048U &&
             held.ready_depth == 0U && held.reading_depth == 0U,
         "finite completion holds the last emitted state at the exact tick");
}

void uploadInfiniteAlternating(Fixture &fixture, std::uint32_t generation) {
  expect(fixture.engine.begin(generation, 0U, 0U) ==
                 output::ProgramStatus::kOk &&
             fixture.engine.append(generation, {1U, 1U}) ==
                 output::ProgramStatus::kOk &&
             fixture.engine.append(generation, {1U, 2U}) ==
                 output::ProgramStatus::kOk &&
             fixture.engine.commit(generation, 2U,
                                   checksumFor(fixture.program)) ==
                 output::ProgramStatus::kOk &&
             fixture.engine.arm(generation) == output::OperationStatus::kOk,
         "infinite alternating program uploads, commits, and arms");
}

void testBoundedRefillStopAndUnderrunFault() {
  Fixture fixture{};
  uploadInfiniteAlternating(fixture, 31U);
  output::Snapshot armed = fixture.engine.snapshot();
  expect(armed.ready_depth == board::kAuxOutputDmaBlockCount &&
             armed.refill_lead ==
                 board::kAuxOutputDmaBlockCount *
                     board::kAuxOutputStatesPerBlock &&
             armed.telemetry.ready_high_water ==
                 board::kAuxOutputDmaBlockCount &&
             fixture.cache.calls == board::kAuxOutputDmaBlockCount,
         "ARM performs the four-block prefill with exact refill runway");
  expect(fixture.engine.prepareStart(101U, 500U) ==
             output::StartStatus::kOk,
         "infinite program prepares");
  fixture.engine.commitCommonStart();
  output::Snapshot running = fixture.engine.snapshot();
  std::uint8_t reading = running.reading_block;
  std::uint32_t lease = running.blocks[reading].lease;
  expect(fixture.engine.onDmaBlockComplete(reading, 31U, lease) ==
             output::OperationStatus::kOk,
         "DMA completion reclaims the first block and advances the ring");
  const output::ServiceReport refilled = fixture.engine.service(99U);
  expect(refilled.blocks_filled == 1U &&
             refilled.states_expanded == board::kAuxOutputStatesPerBlock,
         "one free ring slot bounds refill even when the caller asks for more");
  running = fixture.engine.snapshot();
  reading = running.reading_block;
  const output::StopReport stopped =
      fixture.engine.stopAfterTriggersAtProgress(1U);
  const output::Snapshot held = fixture.engine.snapshot();
  expect(stopped.ok() && stopped.dma_quiesced &&
             stopped.active_states_emitted == 1U &&
             held.state == v2::OutputState::kHeld &&
             held.last_emitted_state_mask == 1U &&
             held.telemetry.dma_states_emitted ==
                 board::kAuxOutputStatesPerBlock + 1U &&
             held.hold_tick ==
                 500U + (board::kAuxOutputStatesPerBlock + 1U) *
                            v2::kOutputPeriodTicks &&
             held.ready_depth == 0U && held.reading_depth == 0U,
         "STOP after the shared trigger holds the physically emitted prefix");
  expect(fixture.engine.clear(false) == output::OperationStatus::kReleaseFailed &&
             fixture.engine.snapshot().fault_latched &&
             fixture.engine.snapshot().bank_mode == v2::OutputBankMode::kOutput,
         "failed release remains driven and fault-latched");
  expect(fixture.engine.clear(true) == output::OperationStatus::kOk &&
             fixture.engine.snapshot().state == v2::OutputState::kEmpty &&
             fixture.engine.snapshot().bank_mode ==
                 v2::OutputBankMode::kDisabled &&
             fixture.program_storage.segments[0].duration_samples == 0U &&
             fixture.program_storage.segments[1].logical_state_mask == 0U,
         "successful CLEAR erases fixed storage and releases the bank");

  Fixture underrun{};
  uploadInfiniteAlternating(underrun, 32U);
  expect(underrun.engine.prepareStart(102U, 0U) == output::StartStatus::kOk,
         "underrun fixture prepares");
  underrun.engine.commitCommonStart();
  output::OperationStatus completion = output::OperationStatus::kOk;
  for (std::size_t block = 0U;
       block < board::kAuxOutputDmaBlockCount; ++block) {
    const output::Snapshot before = underrun.engine.snapshot();
    const std::uint8_t active = before.reading_block;
    completion = underrun.engine.onDmaBlockComplete(
        active, 32U, before.blocks[active].lease);
  }
  const output::Snapshot faulted = underrun.engine.snapshot();
  expect(completion == output::OperationStatus::kNotReady &&
             faulted.state == v2::OutputState::kFaulted &&
             faulted.error == v2::OutputError::kUnderrun &&
             faulted.telemetry.underruns == 1U &&
             faulted.telemetry.dma_states_emitted ==
                 board::kAuxOutputDmaBlockCount *
                     board::kAuxOutputStatesPerBlock &&
             faulted.last_emitted_state_mask == 2U &&
             faulted.ready_depth == 0U && faulted.reading_depth == 0U,
         "missing cooperative refills fail-stop instead of replaying stale data");

  Fixture dma_fault{};
  uploadInfiniteAlternating(dma_fault, 33U);
  expect(dma_fault.engine.prepareStart(103U, 700U) ==
             output::StartStatus::kOk,
         "DMA-fault fixture prepares");
  dma_fault.engine.commitCommonStart();
  expect(dma_fault.engine.recordDmaFault(3U) ==
             output::OperationStatus::kOk,
         "bounded DMA-fault progress is accepted");
  const output::Snapshot dma_faulted = dma_fault.engine.snapshot();
  expect(dma_faulted.state == v2::OutputState::kFaulted &&
             dma_faulted.error == v2::OutputError::kDmaFault &&
             dma_faulted.telemetry.dma_errors == 1U &&
             dma_faulted.telemetry.dma_states_emitted == 3U &&
             dma_faulted.last_emitted_state_mask == 1U &&
             dma_faulted.hold_tick == 724U,
         "DMA fault latches exact emitted-prefix evidence and hold state");
}

void testRingWrapGenerationReuseAndCounterConservation() {
  Fixture fixture{};
  uploadInfiniteAlternating(fixture, 41U);
  expect(fixture.engine.inspectStart(0U) == output::StartStatus::kInvalidRunId &&
             fixture.engine.prepareStart(201U, 900U) ==
                 output::StartStatus::kOk,
         "START rejects run zero and accepts a valid prepared epoch");
  output::Snapshot prepared = fixture.engine.snapshot();
  const std::uint8_t first_block = prepared.reading_block;
  const std::uint32_t first_lease = prepared.blocks[first_block].lease;
  fixture.engine.commitCommonStart();
  expect(fixture.engine.clear() == output::OperationStatus::kAlreadyActive,
         "CLEAR cannot cancel active DMA ownership");

  constexpr std::size_t kCompletedBlocks = 10U;
  for (std::size_t completed = 0U; completed < kCompletedBlocks; ++completed) {
    const output::Snapshot before = fixture.engine.snapshot();
    const std::uint8_t reading = before.reading_block;
    expect(reading != output::kInvalidBlockIndex &&
               before.reading_depth == 1U && before.ready_depth == 3U,
           "ring exposes exactly one DMA reader and three immutable ready blocks");
    expect(fixture.engine.onDmaBlockComplete(
               reading, 41U, before.blocks[reading].lease) ==
               output::OperationStatus::kOk,
           "ring completion advances to the oldest ready block");
    const output::ServiceReport refilled = fixture.engine.service(1U);
    const output::Snapshot after = fixture.engine.snapshot();
    expect(refilled.blocks_filled == 1U &&
               refilled.states_expanded == board::kAuxOutputStatesPerBlock &&
               after.reading_depth == 1U && after.ready_depth == 3U &&
               after.refill_lead ==
                   board::kAuxOutputDmaBlockCount *
                       board::kAuxOutputStatesPerBlock &&
               after.telemetry.blocks_completed == completed + 1U &&
               after.telemetry.blocks_filled ==
                   board::kAuxOutputDmaBlockCount + completed + 1U &&
               after.telemetry.dma_states_emitted ==
                   (completed + 1U) * board::kAuxOutputStatesPerBlock &&
               after.telemetry.states_expanded ==
                   after.telemetry.blocks_filled *
                       board::kAuxOutputStatesPerBlock,
           "refill wrap conserves block, state, ownership, and runway counters");
  }
  const output::StopReport stopped = fixture.engine.stopAfterTriggersAtProgress(0U);
  expect(stopped.ok() && fixture.engine.clear() == output::OperationStatus::kOk,
         "wrapped ring can be stopped, quiesced, and cleared");

  uploadInfiniteAlternating(fixture, 41U);
  expect(fixture.engine.prepareStart(202U, 1000U) == output::StartStatus::kOk,
         "a cleared upload generation can be reused with a fresh lease");
  fixture.engine.commitCommonStart();
  const output::Snapshot reused = fixture.engine.snapshot();
  expect(reused.blocks[reused.reading_block].lease != first_lease &&
             fixture.engine.onDmaBlockComplete(first_block, 41U, first_lease) ==
                 output::OperationStatus::kInvalidCompletion &&
             fixture.engine.snapshot().telemetry.dma_states_emitted == 0U,
         "lease identity rejects stale completion even when generation is reused");
}

void testMaximumSegmentProgramAndFiniteWrapStress() {
  Fixture fixture{};
  expect(fixture.engine.begin(51U, 2U, 0U) == output::ProgramStatus::kOk,
         "maximum-segment stress upload begins");
  for (std::size_t index = 0U; index < output::kSegmentCapacity; ++index) {
    expect(fixture.engine.append(
               51U, {1U, static_cast<std::uint32_t>(index & 1U)}) ==
               output::ProgramStatus::kOk,
           "maximum-segment stress upload remains canonical");
  }
  expect(fixture.engine.commit(51U, output::kSegmentCapacity,
                               checksumFor(fixture.program)) ==
                 output::ProgramStatus::kOk &&
             fixture.engine.arm(51U) == output::OperationStatus::kOk &&
             fixture.engine.prepareStart(301U, 10U) == output::StartStatus::kOk,
         "maximum-segment finite program commits, prefills, and prepares");
  fixture.engine.commitCommonStart();

  std::size_t completions = 0U;
  while (fixture.engine.snapshot().state == v2::OutputState::kRunning) {
    const output::Snapshot before = fixture.engine.snapshot();
    const std::uint8_t reading = before.reading_block;
    expect(reading != output::kInvalidBlockIndex,
           "finite stress retains one reading owner until completion");
    expect(fixture.engine.onDmaBlockComplete(
               reading, 51U, before.blocks[reading].lease) ==
               output::OperationStatus::kOk,
           "finite stress block completion succeeds");
    ++completions;
  }
  const output::Snapshot held = fixture.engine.snapshot();
  expect(completions == 3U && held.state == v2::OutputState::kHeld &&
             held.telemetry.states_expanded == 2048U &&
             held.telemetry.dma_states_emitted == 2048U &&
             held.telemetry.transitions_emitted == 2047U &&
             held.telemetry.completed_repeats == 2U &&
             held.telemetry.blocks_filled == held.telemetry.blocks_completed &&
             held.ready_depth == 0U && held.reading_depth == 0U &&
             held.last_emitted_state_mask == 1U &&
             held.completion_tick == 10U + 2048U * v2::kOutputPeriodTicks,
         "small-duration maximum-capacity stress conserves all finite counters");
}

}  // namespace

int main() {
  static_assert(sizeof(output::ProgramStorage) == 8192U);
  static_assert(sizeof(output::DmaBlockStorage) == 16256U);
  testProgramValidationChecksumAndImmutability();
  testFiniteExpansionOwnershipAndCompletionHold();
  testBoundedRefillStopAndUnderrunFault();
  testRingWrapGenerationReuseAndCounterConservation();
  testMaximumSegmentProgramAndFiniteWrapStress();
  if (failures != 0) {
    std::cerr << failures << " digital output assertion(s) failed\n";
    return 1;
  }
  std::cout << "digital output engine tests passed\n";
  return 0;
}
