#include <chrono>
#include <cstddef>
#include <cstdint>
#include <iomanip>
#include <iostream>

#include "digital_output_engine.h"

namespace {

namespace board = thingdaq::board;
namespace output = thingdaq::digital_output;

class BenchmarkCache final : public output::CacheMaintenance {
 public:
  void flushBeforeDmaRead(const void *address, std::size_t bytes) override {
    __asm__ volatile("" : : "g"(address), "g"(bytes) : "memory");
    ++calls;
  }

  std::uint64_t calls = 0U;
};

class BenchmarkCritical final : public output::CriticalSection {
 public:
  std::uint32_t enter() override { return ++entries; }
  void exit(std::uint32_t token) override {
    __asm__ volatile("" : : "g"(token) : "memory");
    ++exits;
  }

  std::uint32_t entries = 0U;
  std::uint32_t exits = 0U;
};

std::uint32_t uploadAlternatingProgram(output::Engine &engine,
                                       output::ProgramStore &program) {
  constexpr std::uint32_t generation = 71U;
  if (engine.begin(generation, 0U, 0U) != output::ProgramStatus::kOk ||
      engine.append(generation, {1U, 0x55U}) != output::ProgramStatus::kOk ||
      engine.append(generation, {1U, 0xAAU}) != output::ProgramStatus::kOk) {
    return 0U;
  }
  const std::uint32_t checksum = program.canonicalChecksum();
  if (engine.commit(generation, 2U, checksum) != output::ProgramStatus::kOk ||
      engine.arm(generation) != output::OperationStatus::kOk ||
      engine.prepareStart(81U, 0U) != output::StartStatus::kOk) {
    return 0U;
  }
  engine.commitCommonStart();
  return generation;
}

}  // namespace

int main() {
  output::ProgramStorage program_storage{};
  output::ProgramStore program{program_storage};
  output::DmaBlockStorage dma_storage{};
  BenchmarkCache cache{};
  BenchmarkCritical critical{};
  output::Engine engine{program, dma_storage, cache, critical};
  const std::uint32_t generation = uploadAlternatingProgram(engine, program);
  if (generation == 0U) {
    return 2;
  }

  constexpr std::size_t warmups = 64U;
  constexpr std::size_t iterations = 4096U;
  std::uint64_t digest = 0U;
  for (std::size_t iteration = 0U; iteration < warmups + iterations;
       ++iteration) {
    const output::Snapshot before = engine.snapshot();
    const std::uint8_t reading = before.reading_block;
    if (reading == output::kInvalidBlockIndex ||
        engine.onDmaBlockComplete(reading, generation,
                                  before.blocks[reading].lease) !=
            output::OperationStatus::kOk) {
      return 3;
    }
    const auto started = std::chrono::steady_clock::now();
    const output::ServiceReport refilled = engine.service(1U);
    const auto stopped = std::chrono::steady_clock::now();
    if (refilled.blocks_filled != 1U ||
        refilled.states_expanded != board::kAuxOutputStatesPerBlock) {
      return 4;
    }
    digest += engine.blockWords(reading)[iteration %
                                               board::kAuxOutputStatesPerBlock];
    if (iteration >= warmups) {
      static double measured_seconds = 0.0;
      measured_seconds +=
          std::chrono::duration<double>(stopped - started).count();
      if (iteration + 1U == warmups + iterations) {
        const std::uint64_t states =
            static_cast<std::uint64_t>(iterations) *
            board::kAuxOutputStatesPerBlock;
        const double states_per_second =
            static_cast<double>(states) / measured_seconds;
        constexpr double target_states_per_second = 1'000'000.0;
        constexpr double required_headroom = 10.0;
        const output::Snapshot final = engine.snapshot();
        std::cout << std::fixed << std::setprecision(3)
                  << "algorithm=rle-to-gpio1-toggle"
                  << " states=" << states
                  << " seconds=" << measured_seconds
                  << " states_per_second=" << states_per_second
                  << " target_states_per_second=" << target_states_per_second
                  << " headroom_ratio="
                  << states_per_second / target_states_per_second
                  << " required_headroom_ratio=" << required_headroom
                  << " max_blocks_per_service=1"
                  << " states_per_block=" << board::kAuxOutputStatesPerBlock
                  << " program_storage_bytes=" << sizeof(output::ProgramStorage)
                  << " dma_state_storage_bytes="
                  << sizeof(output::DmaBlockStorage)
                  << " dma_descriptor_candidate_bytes="
                  << board::kAuxOutputDmaDescriptorBytes
                  << " total_candidate_bytes="
                  << sizeof(output::ProgramStorage) +
                         board::kAuxOutputDmaAllocationBytes
                  << " blocks_filled=" << final.telemetry.blocks_filled
                  << " blocks_completed=" << final.telemetry.blocks_completed
                  << " cache_flushes=" << cache.calls
                  << " critical_entries=" << critical.entries
                  << " critical_exits=" << critical.exits
                  << " physical_timing_acceptance=false"
                  << " target_runtime_acceptance=false"
                  << " digest=" << digest << '\n';
        return states_per_second >=
                       target_states_per_second * required_headroom
                   ? 0
                   : 5;
      }
    }
  }
  return 6;
}

static_assert(sizeof(thingdaq::digital_output::ProgramStorage) == 8192U);
static_assert(sizeof(thingdaq::digital_output::DmaBlockStorage) == 16256U);
static_assert(thingdaq::board::kAuxOutputDmaAllocationBytes == 16384U);
