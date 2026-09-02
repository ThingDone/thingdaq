#pragma once

#include <cstddef>
#include <cstdint>

#include "generated/protocol_v2_constants.h"
#include "protocol.h"

namespace thingdaq::rle {

// The codec accepts a caller-described fixed logical-item shape so the same
// portable implementation covers ADC pairs and GPIO samples. All storage is
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

struct EncodeResult {
  Status status = Status::kInvalidView;
  std::size_t run_count = 0U;
  std::size_t bytes_written = 0U;

  constexpr bool ok() const { return status == Status::kOk; }
};

// Read-only sizing is the mandatory first pass. It counts canonical maximal
// runs and checks every multiplication/addition before reporting a capacity.
SizingPlan size(protocol::ByteView decoded, CodecShape shape);

// Encode exactly the supplied sizing plan into a separate caller-owned view.
// Overlap is rejected so output can never overwrite unread logical input.
EncodeResult encode(protocol::ByteView decoded, const SizingPlan &plan,
                    protocol::MutableByteView output);

struct DataFrameFields {
  protocol_v2::FrameKind kind = protocol_v2::FrameKind::kAdcData;
  std::uint16_t flags = 0U;
  protocol_v1::ChecksumAlgorithm checksum_algorithm =
      protocol_v1::kDefaultChecksumAlgorithm;
  std::uint32_t run_id = 0U;
  std::uint32_t sequence = 0U;
  std::uint64_t first_sample_ticks = 0U;
};

struct FinalizeResult {
  Status status = Status::kInvalidView;
  protocol_v2::FrameEncoding encoding =
      protocol_v2::FrameEncoding::kRaw;
  std::size_t payload_bytes = 0U;
  std::size_t frame_bytes = 0U;
  std::size_t run_count = 0U;

  constexpr bool ok() const { return status == Status::kOk; }
};

// Return the generated logical codec shape for one data kind. Invalid kinds
// produce the zero shape and are rejected by every operation.
constexpr CodecShape dataShape(protocol_v2::FrameKind kind) {
  return kind == protocol_v2::FrameKind::kAdcData
             ? CodecShape{protocol_v2::kAdcBytesPerPair,
                          protocol_v2::kAdcPairsPerFrame}
         : kind == protocol_v2::FrameKind::kGpioData
             ? CodecShape{1U, protocol_v2::kGpioSamplesPerFrame}
             : CodecShape{};
}

constexpr std::size_t maximumSelectedPayloadBytes(
    protocol_v2::FrameKind kind) {
  return kind == protocol_v2::FrameKind::kAdcData
             ? protocol_v2::kAdcRleMaxSelectedPayloadBytes
         : kind == protocol_v2::FrameKind::kGpioData
             ? protocol_v2::kGpioRleMaxSelectedPayloadBytes
             : 0U;
}

constexpr std::size_t maximumSelectedFrameBytes(
    protocol_v2::FrameKind kind) {
  return kind == protocol_v2::FrameKind::kAdcData
             ? protocol_v2::kAdcRleMaxSelectedFrameBytes
         : kind == protocol_v2::FrameKind::kGpioData
             ? protocol_v2::kGpioRleMaxSelectedFrameBytes
             : 0U;
}

// RAW finalization validates the complete logical payload already resident at
// the common 44-byte payload offset, then writes the v2 header and checksum in
// place. RLE finalization writes only to a disjoint fixed-capacity page.
Status validateDataFrameInput(DataFrameFields fields,
                              protocol::ByteView decoded);
FinalizeResult finalizeRawDataFrame(DataFrameFields fields,
                                    protocol::MutableByteView frame);
FinalizeResult finalizeRleDataFrame(DataFrameFields fields,
                                    protocol::ByteView decoded,
                                    const SizingPlan &plan,
                                    protocol::MutableByteView frame);

static_assert(protocol_v1::kHeaderSize == protocol_v2::kHeaderSize);
static_assert(protocol_v1::kTrailerSize == protocol_v2::kTrailerSize);
static_assert(protocol_v1::kDataPayloadBytes ==
              protocol_v2::kDataPayloadBytes);
static_assert(protocol_v1::kDataFrameBytes == protocol_v2::kDataFrameBytes);
static_assert(protocol_v2::kAdcRleRecordBytes ==
              protocol_v2::kAdcBytesPerPair + sizeof(std::uint16_t));
static_assert(protocol_v2::kGpioRleRecordBytes ==
              1U + sizeof(std::uint16_t));

}  // namespace thingdaq::rle
