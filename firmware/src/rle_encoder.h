#pragma once

#include <cstddef>
#include <cstdint>

#include "generated/protocol_v2_constants.h"
#include "protocol.h"

namespace thingdaq::rle {

// The codec accepts a caller-described fixed logical-item shape so the same
// portable implementation can be tested at multiple item widths. All storage is
// supplied by the caller; no operation allocates, recurses, or retains a view.
struct CodecShape {
  std::size_t item_bytes = 0U;
  std::size_t max_items = 0U;
};

enum class Status : std::uint8_t {
  kOk = 0U,
  kInvalidView,
  kInvalidShape,
  kInvalidLength,
  kItemCountOverflow,
  kSizeOverflow,
  kOutputTooSmall,
  kOverlappingBuffers,
  kPlanMismatch,
  kInvalidItem,
  kInvalidFrameFields,
  kUnsupportedChecksum,
};

struct SizingPlan {
  Status status = Status::kInvalidView;
  CodecShape shape{};
  std::size_t decoded_bytes = 0U;
  std::size_t item_count = 0U;
  std::size_t run_count = 0U;
  std::size_t encoded_payload_bytes = 0U;
  std::size_t encoded_frame_bytes = 0U;

  constexpr bool ok() const { return status == Status::kOk; }
};

struct AdaptiveSizingResult {
  Status status = Status::kInvalidView;
  SizingPlan plan{};
  std::size_t items_examined = 0U;
  std::size_t runs_observed = 0U;
  bool select_rle = false;

  constexpr bool ok() const { return status == Status::kOk; }
};

struct EncodeResult {
  Status status = Status::kInvalidView;
  std::size_t run_count = 0U;
  std::size_t bytes_written = 0U;

  constexpr bool ok() const { return status == Status::kOk; }
};

// Read-only sizing is the mandatory first pass. It counts canonical maximal
// runs and checks every multiplication/addition before reporting a capacity.
SizingPlan size(protocol::ByteView decoded, CodecShape shape);

// Stop once the observed run count proves that a complete RLE frame cannot
// fit below the caller's strict selection ceiling. A usable sizing plan is
// returned only when every logical item was examined and RLE is selectable;
// an early RAW decision therefore cannot accidentally be passed to encode().
AdaptiveSizingResult sizeForAdaptiveSelection(
    protocol::ByteView decoded, CodecShape shape,
    std::size_t maximum_selected_frame_bytes);

// Encode exactly the supplied sizing plan into a separate caller-owned view.
// Overlap is rejected so output can never overwrite unread logical input.
EncodeResult encode(protocol::ByteView decoded, const SizingPlan &plan,
                    protocol::MutableByteView output);

}  // namespace thingdaq::rle
