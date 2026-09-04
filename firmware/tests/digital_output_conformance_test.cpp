#include <array>
#include <cstddef>
#include <cstdint>
#include <iostream>
#include <string>

#include "digital_output_engine.h"

namespace {

namespace output = thingdaq::digital_output;

class NullCache final : public output::CacheMaintenance {
 public:
  void flushBeforeDmaRead(const void *, std::size_t) override {}
};

class Critical final : public output::CriticalSection {
 public:
  std::uint32_t enter() override { return 1U; }
  void exit(std::uint32_t) override {}
};

struct Fixture {
  output::ProgramStorage program_storage{};
  output::ProgramStore program{program_storage};
  output::DmaBlockStorage dma_storage{};
  NullCache cache{};
  Critical critical{};
  output::Engine engine{program, dma_storage, cache, critical};
};

std::uint32_t logicalToggle(std::uint32_t physical) {
  std::uint32_t logical = 0U;
  for (std::size_t bit = 0U;
       bit < sizeof(thingdaq::protocol_v2::kOutputGpioBitsByLogicalBit); ++bit) {
    if ((physical &
         (std::uint32_t{1U}
          << thingdaq::protocol_v2::kOutputGpioBitsByLogicalBit[bit])) != 0U) {
      logical |= std::uint32_t{1U} << bit;
    }
  }
  return logical;
}

template <std::size_t SegmentCount>
void accepted(const std::string &name,
              const std::array<output::Segment, SegmentCount> &segments,
              std::uint32_t repeat_count, std::uint32_t idle_state) {
  Fixture fixture{};
  if (fixture.engine.begin(7U, repeat_count, idle_state) !=
      output::ProgramStatus::kOk) {
    std::cout << name << "|REJECT\n";
    return;
  }
  std::size_t state_count = 0U;
  for (const output::Segment &segment : segments) {
    if (fixture.engine.append(7U, segment) != output::ProgramStatus::kOk) {
      std::cout << name << "|REJECT\n";
      return;
    }
    state_count += segment.duration_samples;
  }
  const std::uint32_t checksum = fixture.program.canonicalChecksum();
  if (fixture.engine.commit(7U, SegmentCount, checksum) !=
          output::ProgramStatus::kOk ||
      fixture.engine.arm(7U) != output::OperationStatus::kOk) {
    std::cout << name << "|REJECT\n";
    return;
  }
  state_count *= repeat_count;
  std::cout << name << "|OK|" << checksum << '|';
  std::uint32_t state = idle_state;
  std::size_t emitted = 0U;
  for (std::uint64_t sequence = 0U; emitted < state_count; ++sequence) {
    bool found = false;
    for (std::size_t block = 0U;
         block < thingdaq::board::kAuxOutputDmaBlockCount; ++block) {
      const output::BlockRecord &record = fixture.engine.blockRecord(block);
      if (record.state != output::BlockState::kDmaReady ||
          record.sequence != sequence) {
        continue;
      }
      found = true;
      for (std::size_t index = 0U;
           index < record.valid_states && emitted < state_count; ++index) {
        state ^= logicalToggle(fixture.engine.blockWords(block)[index]);
        if (emitted != 0U) {
          std::cout << ',';
        }
        std::cout << state;
        ++emitted;
      }
    }
    if (!found) {
      std::cout << "|MISSING";
      break;
    }
  }
  std::cout << '\n';
}

void rejectedCases() {
  Fixture zero{};
  zero.engine.begin(1U, 1U, 0U);
  std::cout << "zero_duration|REJECT|"
            << static_cast<unsigned>(zero.engine.append(1U, {0U, 1U})) << '\n';

  Fixture high{};
  high.engine.begin(1U, 1U, 0U);
  std::cout << "high_state|REJECT|"
            << static_cast<unsigned>(high.engine.append(1U, {1U, 0x100U}))
            << '\n';

  Fixture duplicate{};
  duplicate.engine.begin(1U, 1U, 0U);
  duplicate.engine.append(1U, {1U, 0x55U});
  std::cout << "adjacent_duplicate|REJECT|"
            << static_cast<unsigned>(duplicate.engine.append(1U, {2U, 0x55U}))
            << '\n';

  Fixture empty{};
  empty.engine.begin(1U, 1U, 0U);
  std::cout << "empty|REJECT|"
            << static_cast<unsigned>(empty.engine.commit(1U, 0U, 1U)) << '\n';

  Fixture capacity{};
  capacity.engine.begin(1U, 1U, 0U);
  output::ProgramStatus capacity_status = output::ProgramStatus::kOk;
  for (std::size_t index = 0U; index <= output::kSegmentCapacity; ++index) {
    capacity_status = capacity.engine.append(
        1U, {1U, static_cast<std::uint32_t>(index & 1U)});
  }
  std::cout << "capacity|REJECT|" << static_cast<unsigned>(capacity_status)
            << '\n';

  Fixture generation{};
  generation.engine.begin(1U, 1U, 0U);
  std::cout << "generation|REJECT|"
            << static_cast<unsigned>(generation.engine.append(2U, {1U, 1U}))
            << '\n';
}

}  // namespace

int main() {
  accepted("single", std::array<output::Segment, 1>{{{1U, 0U}}}, 1U,
           0xFFU);
  accepted("finite", std::array<output::Segment, 3>{
                         {{2U, 0x01U}, {1U, 0x80U}, {3U, 0x55U}}},
           2U, 0xAAU);
  accepted("all_bits", std::array<output::Segment, 3>{
                           {{1U, 0xFFU}, {2U, 0U}, {1U, 0xA5U}}},
           3U, 0x5AU);
  rejectedCases();
  return 0;
}
