#pragma once

#include <array>
#include <cstddef>
#include <cstdint>

#include "generated/protocol_v2_constants.h"

namespace thingdaq::digital_output {

inline constexpr std::size_t kSegmentCapacity =
    protocol_v2::kOutputSegmentCapacity;
inline constexpr std::uint32_t kLegalStateMask =
    protocol_v2::kOutputLegalStateMask;

struct Segment {
  std::uint32_t duration_samples = 0U;
  std::uint32_t logical_state_mask = 0U;
};

// The payload allocation is deliberately exactly two packet pages. Metadata
// lives in ProgramStore so a future target adapter can place only this object
// in the proposed DTCM packet-page repartition.
struct ProgramStorage {
  std::array<Segment, kSegmentCapacity> segments{};
};

enum class ProgramState : std::uint8_t {
  kEmpty,
  kLoading,
  kCommitted,
};

enum class ProgramStatus : std::uint8_t {
  kOk,
  kInvalidGeneration,
  kInvalidLifecycle,
  kInvalidSegment,
  kCapacityExceeded,
  kSegmentCountMismatch,
  kChecksumMismatch,
};

struct ProgramSnapshot {
  ProgramState state = ProgramState::kEmpty;
  std::uint32_t generation = 0U;
  std::uint32_t repeat_count = 0U;
  std::uint32_t idle_state_mask = 0U;
  std::uint32_t checksum = 0U;
  std::uint64_t duration_samples = 0U;
  std::size_t segment_count = 0U;
  bool immutable = false;
};

// Main-loop-only immutable upload store. It owns no heap memory and accepts
// exactly the canonical little-endian segment representation used by Python.
class ProgramStore final {
 public:
  explicit constexpr ProgramStore(ProgramStorage &storage)
      : storage_(storage) {}

  ProgramStore(const ProgramStore &) = delete;
  ProgramStore &operator=(const ProgramStore &) = delete;

  ProgramStatus begin(std::uint32_t generation,
                      std::uint32_t repeat_count,
                      std::uint32_t idle_state_mask);
  ProgramStatus append(std::uint32_t generation, const Segment &segment);
  ProgramStatus commit(std::uint32_t generation,
                       std::size_t expected_segment_count,
                       std::uint32_t expected_checksum);
  void clear();

  constexpr ProgramSnapshot snapshot() const {
    return {state_, generation_, repeat_count_, idle_state_mask_, checksum_,
            duration_samples_, segment_count_,
            state_ == ProgramState::kCommitted};
  }
  constexpr const Segment &segment(std::size_t index) const {
    return storage_.segments[index];
  }
  constexpr bool committed() const {
    return state_ == ProgramState::kCommitted;
  }

  std::uint32_t canonicalChecksum() const;

 private:
  ProgramStorage &storage_;
  ProgramState state_ = ProgramState::kEmpty;
  std::uint32_t generation_ = 0U;
  std::uint32_t repeat_count_ = 0U;
  std::uint32_t idle_state_mask_ = 0U;
  std::uint32_t checksum_ = 0U;
  std::uint64_t duration_samples_ = 0U;
  std::size_t segment_count_ = 0U;
};

static_assert(sizeof(Segment) == protocol_v2::kOutputSegmentBytes);
static_assert(sizeof(ProgramStorage) ==
              protocol_v2::kOutputSegmentCapacity *
                  protocol_v2::kOutputSegmentBytes);

}  // namespace thingdaq::digital_output
