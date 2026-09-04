#include "digital_output_program.h"

#include "checksum.h"

#if defined(__IMXRT1062__)
#define THINGDAQ_OUTPUT_PROGRAM_COLD_CODE(section_name) \
  __attribute__((section(section_name), noinline, noipa, used))
#else
#define THINGDAQ_OUTPUT_PROGRAM_COLD_CODE(section_name)
#endif

namespace thingdaq::digital_output {
namespace {

void updateAdlerByte(std::uint8_t value, std::uint32_t &first,
                     std::uint32_t &second) {
  first += value;
  if (first >= checksum::kAdler32Modulus) {
    first -= checksum::kAdler32Modulus;
  }
  second += first;
  if (second >= checksum::kAdler32Modulus) {
    second -= checksum::kAdler32Modulus;
  }
}

void updateAdlerU32(std::uint32_t value, std::uint32_t &first,
                    std::uint32_t &second) {
  for (std::uint8_t byte = 0U; byte < 4U; ++byte) {
    updateAdlerByte(static_cast<std::uint8_t>(value & 0xFFU), first, second);
    value >>= 8U;
  }
}

}  // namespace

THINGDAQ_OUTPUT_PROGRAM_COLD_CODE(".flashmem.output.program.begin")
ProgramStatus ProgramStore::begin(std::uint32_t generation,
                                  std::uint32_t repeat_count,
                                  std::uint32_t idle_state_mask) {
  if (generation == 0U) {
    return ProgramStatus::kInvalidGeneration;
  }
  if ((idle_state_mask & ~kLegalStateMask) != 0U) {
    return ProgramStatus::kInvalidSegment;
  }
  if (state_ == ProgramState::kCommitted) {
    return ProgramStatus::kInvalidLifecycle;
  }
  if (state_ == ProgramState::kLoading && generation == generation_) {
    return ProgramStatus::kInvalidGeneration;
  }
  state_ = ProgramState::kLoading;
  generation_ = generation;
  repeat_count_ = repeat_count;
  idle_state_mask_ = idle_state_mask;
  checksum_ = 0U;
  duration_samples_ = 0U;
  segment_count_ = 0U;
  return ProgramStatus::kOk;
}

THINGDAQ_OUTPUT_PROGRAM_COLD_CODE(".flashmem.output.program.append")
ProgramStatus ProgramStore::append(std::uint32_t generation,
                                   const Segment &segment_value) {
  if (generation == 0U || generation != generation_) {
    return ProgramStatus::kInvalidGeneration;
  }
  if (state_ != ProgramState::kLoading) {
    return ProgramStatus::kInvalidLifecycle;
  }
  if (segment_value.duration_samples == 0U ||
      (segment_value.logical_state_mask & ~kLegalStateMask) != 0U ||
      (segment_count_ != 0U &&
       storage_.segments[segment_count_ - 1U].logical_state_mask ==
           segment_value.logical_state_mask)) {
    return ProgramStatus::kInvalidSegment;
  }
  if (segment_count_ == kSegmentCapacity) {
    return ProgramStatus::kCapacityExceeded;
  }
  storage_.segments[segment_count_] = segment_value;
  ++segment_count_;
  duration_samples_ += segment_value.duration_samples;
  return ProgramStatus::kOk;
}

THINGDAQ_OUTPUT_PROGRAM_COLD_CODE(".flashmem.output.program.commit")
ProgramStatus ProgramStore::commit(std::uint32_t generation,
                                   std::size_t expected_segment_count,
                                   std::uint32_t expected_checksum) {
  if (generation == 0U || generation != generation_) {
    return ProgramStatus::kInvalidGeneration;
  }
  if (state_ != ProgramState::kLoading) {
    return ProgramStatus::kInvalidLifecycle;
  }
  if (segment_count_ == 0U || expected_segment_count != segment_count_) {
    return ProgramStatus::kSegmentCountMismatch;
  }
  const std::uint32_t actual_checksum = canonicalChecksum();
  if (actual_checksum != expected_checksum) {
    return ProgramStatus::kChecksumMismatch;
  }
  checksum_ = actual_checksum;
  state_ = ProgramState::kCommitted;
  return ProgramStatus::kOk;
}

THINGDAQ_OUTPUT_PROGRAM_COLD_CODE(".flashmem.output.program.clear")
void ProgramStore::clear() {
  for (Segment &segment_value : storage_.segments) {
    segment_value = {};
  }
  state_ = ProgramState::kEmpty;
  generation_ = 0U;
  repeat_count_ = 0U;
  idle_state_mask_ = 0U;
  checksum_ = 0U;
  duration_samples_ = 0U;
  segment_count_ = 0U;
}

THINGDAQ_OUTPUT_PROGRAM_COLD_CODE(".flashmem.output.program.checksum")
std::uint32_t ProgramStore::canonicalChecksum() const {
  std::uint32_t first = checksum::kAdler32Initial;
  std::uint32_t second = 0U;
  for (std::size_t index = 0U; index < segment_count_; ++index) {
    updateAdlerU32(storage_.segments[index].duration_samples, first, second);
    updateAdlerU32(storage_.segments[index].logical_state_mask, first, second);
  }
  return (second << 16U) | first;
}

}  // namespace thingdaq::digital_output

#undef THINGDAQ_OUTPUT_PROGRAM_COLD_CODE
