#include "rle_encoder.h"

#include <cstring>
#include <limits>

#if defined(__IMXRT1062__)
#define THINGDAQ_RLE_CODE(section_name) \
  __attribute__((section(section_name), noinline, noipa, used))
#else
#define THINGDAQ_RLE_CODE(section_name)
#endif

namespace thingdaq::rle {
namespace {

constexpr std::size_t kEnvelopeBytes =
    protocol_v2::kHeaderSize + protocol_v2::kTrailerSize;

bool checkedAdd(std::size_t left, std::size_t right,
                std::size_t &result) {
  if (right > std::numeric_limits<std::size_t>::max() - left) {
    return false;
  }
  result = left + right;
  return true;
}

bool checkedMultiply(std::size_t left, std::size_t right,
                     std::size_t &result) {
  if (left != 0U && right > std::numeric_limits<std::size_t>::max() / left) {
    return false;
  }
  result = left * right;
  return true;
}

THINGDAQ_RLE_CODE(".flashmem.rle.equal_item")
bool equalItem(protocol::ByteView decoded, std::size_t left,
               std::size_t right, std::size_t item_bytes) {
  if (item_bytes == 1U) {
    return decoded.data[left] == decoded.data[right];
  }
  if (item_bytes == sizeof(std::uint32_t)) {
    std::uint32_t left_value = 0U;
    std::uint32_t right_value = 0U;
    std::memcpy(&left_value, decoded.data + left, sizeof(left_value));
    std::memcpy(&right_value, decoded.data + right, sizeof(right_value));
    return left_value == right_value;
  }
  for (std::size_t offset = 0U; offset < item_bytes; ++offset) {
    if (decoded.data[left + offset] != decoded.data[right + offset]) {
      return false;
    }
  }
  return true;
}

std::uint32_t loadUnalignedU32(const std::uint8_t *source) {
  std::uint32_t value = 0U;
  std::memcpy(&value, source, sizeof(value));
  return value;
}

bool allItemsEqual(protocol::ByteView decoded, CodecShape shape) {
  if (shape.item_bytes == 1U) {
    const std::uint32_t repeated =
        static_cast<std::uint32_t>(decoded.data[0U]) * 0x01010101UL;
    std::size_t item = 1U;
    while (item + sizeof(std::uint32_t) <= decoded.size) {
      if (loadUnalignedU32(decoded.data + item) != repeated) {
        return false;
      }
      item += sizeof(std::uint32_t);
    }
    while (item < decoded.size) {
      if (decoded.data[item] != decoded.data[0U]) {
        return false;
      }
      ++item;
    }
    return true;
  }
  if (shape.item_bytes == sizeof(std::uint32_t)) {
    const std::uint32_t first = loadUnalignedU32(decoded.data);
    for (std::size_t offset = sizeof(first); offset < decoded.size;
         offset += sizeof(first)) {
      if (loadUnalignedU32(decoded.data + offset) != first) {
        return false;
      }
    }
    return true;
  }
  for (std::size_t item = 1U; item < decoded.size / shape.item_bytes;
       ++item) {
    if (!equalItem(decoded, 0U, item * shape.item_bytes,
                   shape.item_bytes)) {
      return false;
    }
  }
  return true;
}

bool rangesOverlap(protocol::ByteView input,
                   protocol::MutableByteView output) {
  if (input.size == 0U || output.size == 0U) {
    return false;
  }
  const std::uintptr_t input_begin =
      reinterpret_cast<std::uintptr_t>(input.data);
  const std::uintptr_t output_begin =
      reinterpret_cast<std::uintptr_t>(output.data);
  if (input.size > std::numeric_limits<std::uintptr_t>::max() - input_begin ||
      output.size >
          std::numeric_limits<std::uintptr_t>::max() - output_begin) {
    return true;
  }
  const std::uintptr_t input_end = input_begin + input.size;
  const std::uintptr_t output_end = output_begin + output.size;
  return input_begin < output_end && output_begin < input_end;
}

bool validCodecShape(CodecShape shape) {
  return shape.item_bytes != 0U && shape.max_items != 0U;
}

THINGDAQ_RLE_CODE(".flashmem.rle.write_record")
bool writeRecord(protocol::MutableByteView output, std::size_t &offset,
                 std::uint16_t run_length, protocol::ByteView decoded,
                 std::size_t item_offset, std::size_t item_bytes) {
  std::size_t record_bytes = 0U;
  if (!checkedAdd(item_bytes, sizeof(run_length), record_bytes) ||
      offset > output.size || record_bytes > output.size - offset ||
      !protocol::storeU16(output, offset, run_length)) {
    return false;
  }
  offset += sizeof(run_length);
  for (std::size_t index = 0U; index < item_bytes; ++index) {
    output.data[offset + index] = decoded.data[item_offset + index];
  }
  offset += item_bytes;
  return true;
}

bool dataKind(protocol_v2::FrameKind kind) {
  return kind == protocol_v2::FrameKind::kAdcData ||
         kind == protocol_v2::FrameKind::kGpioData;
}

std::uint32_t itemCount(protocol_v2::FrameKind kind) {
  return kind == protocol_v2::FrameKind::kAdcData
             ? static_cast<std::uint32_t>(protocol_v2::kAdcPairsPerFrame)
             : static_cast<std::uint32_t>(
                   protocol_v2::kGpioSamplesPerFrame);
}

std::uint64_t itemPeriodTicks(protocol_v2::FrameKind kind) {
  return kind == protocol_v2::FrameKind::kAdcData
             ? protocol_v2::kAdcPairPeriodTicks
             : protocol_v2::kGpioSamplePeriodTicks;
}

bool validFields(const DataFrameFields &fields) {
  if (!dataKind(fields.kind) || fields.run_id == 0U ||
      !protocol::isSupportedChecksum(fields.checksum_algorithm)) {
    return false;
  }
  const std::uint16_t allowed = protocol_v2::allowedFlags(fields.kind);
  if ((fields.flags & static_cast<std::uint16_t>(~allowed)) != 0U) {
    return false;
  }
  const std::uint16_t gap =
      static_cast<std::uint16_t>(protocol_v2::FrameFlag::kGapBefore);
  const std::uint16_t overrun =
      static_cast<std::uint16_t>(protocol_v2::FrameFlag::kOverrunBefore);
  if ((fields.flags & overrun) != 0U && (fields.flags & gap) == 0U) {
    return false;
  }
  if (fields.first_sample_ticks % itemPeriodTicks(fields.kind) != 0U) {
    return false;
  }
  const std::uint16_t epoch =
      static_cast<std::uint16_t>(protocol_v2::FrameFlag::kEpochStart);
  const bool epoch_start = (fields.flags & epoch) != 0U;
  const bool first_in_epoch =
      fields.sequence == 0U && fields.first_sample_ticks == 0U;
  return epoch_start == first_in_epoch;
}

bool validLogicalPayload(protocol_v2::FrameKind kind,
                         protocol::ByteView payload) {
  if (!dataKind(kind) || !payload.valid() ||
      payload.size != protocol_v2::kDataPayloadBytes) {
    return false;
  }
  if (kind == protocol_v2::FrameKind::kGpioData) {
    return true;
  }
  constexpr std::uint32_t kAdcCodeMask =
      (1UL << protocol_v2::kAdcResolutionBits) - 1UL;
  constexpr std::uint32_t kInvalidAdcCodeBits =
      static_cast<std::uint32_t>(~kAdcCodeMask) & 0xFFFFUL;
  constexpr std::uint32_t kInvalidAdcPairBits =
      kInvalidAdcCodeBits | (kInvalidAdcCodeBits << 16U);
  for (std::size_t offset = 0U; offset < payload.size;
       offset += sizeof(std::uint32_t)) {
    if ((loadUnalignedU32(payload.data + offset) & kInvalidAdcPairBits) !=
        0U) {
      return false;
    }
  }
  return true;
}

THINGDAQ_RLE_CODE(".flashmem.rle.header")
bool writeHeader(const DataFrameFields &fields,
                 protocol_v2::FrameEncoding encoding,
                 std::size_t payload_bytes, std::size_t frame_bytes,
                 protocol::MutableByteView frame) {
  if (!frame.valid() || frame_bytes > frame.size ||
      payload_bytes > std::numeric_limits<std::uint32_t>::max() ||
      frame_bytes > std::numeric_limits<std::uint32_t>::max()) {
    return false;
  }
  frame.data[protocol_v2::kHeaderVersionOffset] =
      protocol_v2::kProtocolVersion;
  frame.data[protocol_v2::kHeaderKindOffset] =
      static_cast<std::uint8_t>(fields.kind);
  frame.data[protocol_v2::kHeaderChecksumAlgorithmOffset] =
      static_cast<std::uint8_t>(fields.checksum_algorithm);
  frame.data[protocol_v2::kHeaderEncodingOffset] =
      static_cast<std::uint8_t>(encoding);
  return protocol::storeU32(frame, protocol_v2::kHeaderMagicOffset,
                            protocol_v2::kMagic) &&
         protocol::storeU16(frame, protocol_v2::kHeaderFlagsOffset,
                            fields.flags) &&
         protocol::storeU16(
             frame, protocol_v2::kHeaderHeaderLengthOffset,
             static_cast<std::uint16_t>(protocol_v2::kHeaderSize)) &&
         protocol::storeU32(frame, protocol_v2::kHeaderTotalLengthOffset,
                            static_cast<std::uint32_t>(frame_bytes)) &&
         protocol::storeU32(frame, protocol_v2::kHeaderPayloadLengthOffset,
                            static_cast<std::uint32_t>(payload_bytes)) &&
         protocol::storeU32(frame, protocol_v2::kHeaderRunIdOffset,
                            fields.run_id) &&
         protocol::storeU32(frame, protocol_v2::kHeaderSequenceOffset,
                            fields.sequence) &&
         protocol::storeU32(frame, protocol_v2::kHeaderRequestIdOffset, 0U) &&
         protocol::storeU64(frame,
                            protocol_v2::kHeaderFirstSampleTicksOffset,
                            fields.first_sample_ticks) &&
         protocol::storeU32(frame, protocol_v2::kHeaderItemCountOffset,
                            itemCount(fields.kind));
}

THINGDAQ_RLE_CODE(".flashmem.rle.checksum")
Status finishChecksum(const DataFrameFields &fields, std::size_t frame_bytes,
                      protocol::MutableByteView frame) {
  if (frame_bytes < protocol_v2::kTrailerSize || frame_bytes > frame.size) {
    return Status::kInvalidLength;
  }
  const std::size_t checksum_offset =
      frame_bytes - protocol_v2::kTrailerSize;
  std::uint32_t checksum = 0U;
  const protocol::Result computed = protocol::computeChecksum(
      fields.checksum_algorithm, {frame.data, checksum_offset}, checksum);
  if (!computed.ok()) {
    return Status::kUnsupportedChecksum;
  }
  return protocol::storeU32(frame, checksum_offset, checksum)
             ? Status::kOk
             : Status::kInvalidLength;
}

}  // namespace

THINGDAQ_RLE_CODE(".flashmem.rle.size")
SizingPlan size(protocol::ByteView decoded, CodecShape shape) {
  SizingPlan result{};
  result.shape = shape;
  result.decoded_bytes = decoded.size;
  if (!decoded.valid()) {
    result.status = Status::kInvalidView;
    return result;
  }
  if (!validCodecShape(shape)) {
    result.status = Status::kInvalidShape;
    return result;
  }
  if (decoded.size == 0U || decoded.size % shape.item_bytes != 0U) {
    result.status = Status::kInvalidLength;
    return result;
  }
  result.item_count = decoded.size / shape.item_bytes;
  if (result.item_count > shape.max_items ||
      result.item_count > protocol_v2::kRleRunLengthMax) {
    result.status = Status::kItemCountOverflow;
    return result;
  }

  result.run_count = 1U;
  for (std::size_t item = 1U; item < result.item_count; ++item) {
    const std::size_t current = item * shape.item_bytes;
    const std::size_t previous = current - shape.item_bytes;
    if (!equalItem(decoded, previous, current, shape.item_bytes)) {
      ++result.run_count;
    }
  }

  std::size_t record_bytes = 0U;
  if (!checkedAdd(shape.item_bytes, sizeof(std::uint16_t), record_bytes) ||
      !checkedMultiply(result.run_count, record_bytes,
                       result.encoded_payload_bytes) ||
      !checkedAdd(result.encoded_payload_bytes, kEnvelopeBytes,
                  result.encoded_frame_bytes)) {
    result.status = Status::kSizeOverflow;
    return result;
  }
  result.status = Status::kOk;
  return result;
}

THINGDAQ_RLE_CODE(".flashmem.rle.adaptive_size")
AdaptiveSizingResult sizeForAdaptiveSelection(
    protocol::ByteView decoded, CodecShape shape,
    std::size_t maximum_selected_frame_bytes) {
  AdaptiveSizingResult result{};
  result.plan.shape = shape;
  result.plan.decoded_bytes = decoded.size;
  if (!decoded.valid()) {
    result.status = Status::kInvalidView;
    return result;
  }
  if (!validCodecShape(shape)) {
    result.status = Status::kInvalidShape;
    return result;
  }
  if (decoded.size == 0U || decoded.size % shape.item_bytes != 0U) {
    result.status = Status::kInvalidLength;
    return result;
  }
  result.plan.item_count = decoded.size / shape.item_bytes;
  if (result.plan.item_count > shape.max_items ||
      result.plan.item_count > protocol_v2::kRleRunLengthMax) {
    result.status = Status::kItemCountOverflow;
    return result;
  }

  std::size_t record_bytes = 0U;
  std::size_t minimum_frame_bytes = 0U;
  if (!checkedAdd(shape.item_bytes, sizeof(std::uint16_t), record_bytes) ||
      !checkedAdd(kEnvelopeBytes, record_bytes, minimum_frame_bytes) ||
      maximum_selected_frame_bytes < minimum_frame_bytes) {
    result.status = Status::kInvalidLength;
    return result;
  }
  const std::size_t maximum_selected_runs =
      (maximum_selected_frame_bytes - kEnvelopeBytes) / record_bytes;
  std::size_t run_count = 1U;
  result.items_examined = 1U;
  if (shape.item_bytes == 1U) {
    std::uint8_t previous = decoded.data[0U];
    for (std::size_t item = 1U; item < result.plan.item_count; ++item) {
      const std::uint8_t current = decoded.data[item];
      ++result.items_examined;
      if (current != previous) {
        ++run_count;
        if (run_count > maximum_selected_runs) {
          result.status = Status::kOk;
          result.runs_observed = run_count;
          return result;
        }
        previous = current;
      }
    }
  } else if (shape.item_bytes == sizeof(std::uint32_t)) {
    std::uint32_t previous = loadUnalignedU32(decoded.data);
    for (std::size_t item = 1U; item < result.plan.item_count; ++item) {
      const std::uint32_t current = loadUnalignedU32(
          decoded.data + item * sizeof(std::uint32_t));
      ++result.items_examined;
      if (current != previous) {
        ++run_count;
        if (run_count > maximum_selected_runs) {
          result.status = Status::kOk;
          result.runs_observed = run_count;
          return result;
        }
        previous = current;
      }
    }
  } else {
    for (std::size_t item = 1U; item < result.plan.item_count; ++item) {
      ++result.items_examined;
      const std::size_t current = item * shape.item_bytes;
      if (!equalItem(decoded, current - shape.item_bytes, current,
                     shape.item_bytes)) {
        ++run_count;
        if (run_count > maximum_selected_runs) {
          result.status = Status::kOk;
          result.runs_observed = run_count;
          return result;
        }
      }
    }
  }

  result.plan.run_count = run_count;
  result.runs_observed = run_count;
  if (!checkedMultiply(run_count, record_bytes,
                       result.plan.encoded_payload_bytes) ||
      !checkedAdd(result.plan.encoded_payload_bytes, kEnvelopeBytes,
                  result.plan.encoded_frame_bytes)) {
    result.status = Status::kSizeOverflow;
    return result;
  }
  result.plan.status = Status::kOk;
  result.status = Status::kOk;
  result.select_rle =
      result.plan.encoded_frame_bytes <= maximum_selected_frame_bytes;
  return result;
}

THINGDAQ_RLE_CODE(".flashmem.rle.encode")
EncodeResult encode(protocol::ByteView decoded, const SizingPlan &plan,
                    protocol::MutableByteView output) {
  EncodeResult result{};
  if (!decoded.valid() || !output.valid()) {
    result.status = Status::kInvalidView;
    return result;
  }
  std::size_t expected_decoded_bytes = 0U;
  std::size_t record_bytes = 0U;
  std::size_t expected_encoded_bytes = 0U;
  std::size_t expected_frame_bytes = 0U;
  if (!plan.ok() || !validCodecShape(plan.shape) ||
      plan.decoded_bytes != decoded.size || plan.item_count == 0U ||
      plan.item_count > plan.shape.max_items ||
      plan.item_count > protocol_v2::kRleRunLengthMax ||
      plan.run_count == 0U || plan.run_count > plan.item_count ||
      !checkedMultiply(plan.item_count, plan.shape.item_bytes,
                       expected_decoded_bytes) ||
      expected_decoded_bytes != decoded.size ||
      !checkedAdd(plan.shape.item_bytes, sizeof(std::uint16_t),
                  record_bytes) ||
      !checkedMultiply(plan.run_count, record_bytes,
                       expected_encoded_bytes) ||
      expected_encoded_bytes != plan.encoded_payload_bytes ||
      !checkedAdd(expected_encoded_bytes, kEnvelopeBytes,
                  expected_frame_bytes) ||
      expected_frame_bytes != plan.encoded_frame_bytes) {
    result.status = Status::kPlanMismatch;
    return result;
  }
  if (output.size < plan.encoded_payload_bytes) {
    result.status = Status::kOutputTooSmall;
    return result;
  }
  protocol::MutableByteView bounded_output{
      output.data, plan.encoded_payload_bytes};
  if (rangesOverlap(decoded, bounded_output)) {
    result.status = Status::kOverlappingBuffers;
    return result;
  }

  if (plan.run_count == 1U) {
    if (!allItemsEqual(decoded, plan.shape)) {
      result.status = Status::kPlanMismatch;
      return result;
    }
    std::size_t output_offset = 0U;
    if (!writeRecord(bounded_output, output_offset,
                     static_cast<std::uint16_t>(plan.item_count), decoded,
                     0U, plan.shape.item_bytes)) {
      result.status = Status::kPlanMismatch;
      return result;
    }
    result.status = Status::kOk;
    result.run_count = 1U;
    result.bytes_written = output_offset;
    return result;
  }

  std::size_t output_offset = 0U;
  std::size_t run_start = 0U;
  std::uint16_t run_length = 1U;
  for (std::size_t item = 1U; item < plan.item_count; ++item) {
    const std::size_t current = item * plan.shape.item_bytes;
    const std::size_t previous = current - plan.shape.item_bytes;
    if (equalItem(decoded, previous, current, plan.shape.item_bytes)) {
      ++run_length;
      continue;
    }
    if (!writeRecord(bounded_output, output_offset, run_length, decoded,
                     run_start, plan.shape.item_bytes)) {
      result.status = Status::kPlanMismatch;
      return result;
    }
    ++result.run_count;
    run_start = current;
    run_length = 1U;
  }
  if (!writeRecord(bounded_output, output_offset, run_length, decoded,
                   run_start, plan.shape.item_bytes)) {
    result.status = Status::kPlanMismatch;
    return result;
  }
  ++result.run_count;
  result.bytes_written = output_offset;
  if (result.run_count != plan.run_count ||
      result.bytes_written != plan.encoded_payload_bytes) {
    result.status = Status::kPlanMismatch;
    return result;
  }
  result.status = Status::kOk;
  return result;
}

THINGDAQ_RLE_CODE(".flashmem.rle.finalize_raw")
FinalizeResult finalizeRawDataFrame(DataFrameFields fields,
                                    protocol::MutableByteView frame) {
  FinalizeResult result{};
  result.encoding = protocol_v2::FrameEncoding::kRaw;
  result.payload_bytes = protocol_v2::kDataPayloadBytes;
  result.frame_bytes = protocol_v2::kDataFrameBytes;
  if (!frame.valid()) {
    result.status = Status::kInvalidView;
    return result;
  }
  if (frame.size < result.frame_bytes) {
    result.status = Status::kOutputTooSmall;
    return result;
  }
  const protocol::ByteView payload{
      frame.data + protocol_v2::kHeaderSize,
      protocol_v2::kDataPayloadBytes};
  result.status = validateDataFrameInput(fields, payload);
  if (result.status != Status::kOk) {
    return result;
  }
  if (!writeHeader(fields, result.encoding, result.payload_bytes,
                   result.frame_bytes, frame)) {
    result.status = Status::kInvalidLength;
    return result;
  }
  result.status = finishChecksum(fields, result.frame_bytes, frame);
  return result;
}

THINGDAQ_RLE_CODE(".flashmem.rle.finalize_rle")
FinalizeResult finalizeRleDataFrame(DataFrameFields fields,
                                    protocol::ByteView decoded,
                                    const SizingPlan &plan,
                                    protocol::MutableByteView frame) {
  FinalizeResult result{};
  result.encoding = protocol_v2::FrameEncoding::kRle;
  result.payload_bytes = plan.encoded_payload_bytes;
  result.frame_bytes = plan.encoded_frame_bytes;
  result.run_count = plan.run_count;
  if (!decoded.valid() || !frame.valid()) {
    result.status = Status::kInvalidView;
    return result;
  }
  const CodecShape expected_shape = dataShape(fields.kind);
  if (!plan.ok() || plan.shape.item_bytes != expected_shape.item_bytes ||
      plan.shape.max_items != expected_shape.max_items ||
      plan.decoded_bytes != protocol_v2::kDataPayloadBytes ||
      plan.item_count != expected_shape.max_items) {
    result.status = Status::kPlanMismatch;
    return result;
  }
  if (result.payload_bytes == 0U ||
      result.payload_bytes > maximumSelectedPayloadBytes(fields.kind) ||
      result.frame_bytes > maximumSelectedFrameBytes(fields.kind) ||
      result.frame_bytes >= protocol_v2::kDataFrameBytes) {
    result.status = Status::kInvalidLength;
    return result;
  }
  if (frame.size < result.frame_bytes) {
    result.status = Status::kOutputTooSmall;
    return result;
  }
  result.status = validateDataFrameInput(fields, decoded);
  if (result.status != Status::kOk) {
    return result;
  }

  protocol::MutableByteView encoded_payload{
      frame.data + protocol_v2::kHeaderSize, result.payload_bytes};
  const EncodeResult encoded = encode(decoded, plan, encoded_payload);
  if (!encoded.ok()) {
    result.status = encoded.status;
    return result;
  }
  if (!writeHeader(fields, result.encoding, result.payload_bytes,
                   result.frame_bytes, frame)) {
    result.status = Status::kInvalidLength;
    return result;
  }
  result.status = finishChecksum(fields, result.frame_bytes, frame);
  return result;
}

THINGDAQ_RLE_CODE(".flashmem.rle.validate")
Status validateDataFrameInput(DataFrameFields fields,
                              protocol::ByteView decoded) {
  if (!decoded.valid()) {
    return Status::kInvalidView;
  }
  if (!validFields(fields)) {
    return protocol::isSupportedChecksum(fields.checksum_algorithm)
               ? Status::kInvalidFrameFields
               : Status::kUnsupportedChecksum;
  }
  return validLogicalPayload(fields.kind, decoded) ? Status::kOk
                                                   : Status::kInvalidItem;
}

}  // namespace thingdaq::rle

#undef THINGDAQ_RLE_CODE
