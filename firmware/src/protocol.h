#pragma once

#include <array>
#include <cstddef>
#include <cstdint>

#include "generated/protocol_constants.h"

namespace teensy_daq::protocol {

struct ByteView {
  const std::uint8_t *data = nullptr;
  std::size_t size = 0U;

  constexpr bool valid() const { return data != nullptr || size == 0U; }
};

struct MutableByteView {
  std::uint8_t *data = nullptr;
  std::size_t size = 0U;

  constexpr bool valid() const { return data != nullptr || size == 0U; }
};

enum class ValidationIssue : std::uint8_t {
  kNone,
  kBadMagic,
  kBadVersion,
  kBadKind,
  kBadFlags,
  kBadLength,
  kBadChecksum,
  kBadPayload,
  kBadRequestId,
  kUnsupportedChecksum,
};

struct Result {
  protocol_v1::ErrorCode error = protocol_v1::ErrorCode::kOk;
  ValidationIssue issue = ValidationIssue::kNone;

  constexpr bool ok() const {
    return error == protocol_v1::ErrorCode::kOk;
  }

  static constexpr Result success() { return {}; }
  static constexpr Result failure(protocol_v1::ErrorCode error_code,
                                  ValidationIssue validation_issue) {
    return {error_code, validation_issue};
  }
};

bool loadU16(ByteView input, std::size_t offset, std::uint16_t &value);
bool loadU32(ByteView input, std::size_t offset, std::uint32_t &value);
bool loadU64(ByteView input, std::size_t offset, std::uint64_t &value);
bool storeU16(MutableByteView output, std::size_t offset, std::uint16_t value);
bool storeU32(MutableByteView output, std::size_t offset, std::uint32_t value);
bool storeU64(MutableByteView output, std::size_t offset, std::uint64_t value);

std::uint32_t adler32(ByteView input);
Result computeChecksum(protocol_v1::ChecksumAlgorithm algorithm, ByteView input,
                       std::uint32_t &checksum);

struct FrameHeader {
  protocol_v1::FrameKind kind = protocol_v1::FrameKind::kInfoRequest;
  std::uint16_t flags = 0U;
  protocol_v1::ChecksumAlgorithm checksum_algorithm =
      protocol_v1::kDefaultChecksumAlgorithm;
  std::uint32_t total_length = 0U;
  std::uint32_t payload_length = 0U;
  std::uint32_t run_id = 0U;
  std::uint32_t sequence = 0U;
  std::uint32_t request_id = 0U;
  std::uint64_t first_sample_ticks = 0U;
  std::uint32_t item_count = 0U;
  std::uint8_t version = protocol_v1::kProtocolVersion;
  std::uint16_t header_length =
      static_cast<std::uint16_t>(protocol_v1::kHeaderSize);
};

struct FrameFields {
  protocol_v1::FrameKind kind = protocol_v1::FrameKind::kInfoRequest;
  std::uint16_t flags = 0U;
  protocol_v1::ChecksumAlgorithm checksum_algorithm =
      protocol_v1::kDefaultChecksumAlgorithm;
  std::uint32_t run_id = 0U;
  std::uint32_t sequence = 0U;
  std::uint32_t request_id = 0U;
  std::uint64_t first_sample_ticks = 0U;
  std::uint32_t item_count = 0U;
};

struct DecodedFrame {
  FrameHeader header{};
  ByteView payload{};
  std::uint32_t checksum = 0U;
};

template <std::size_t Capacity>
class FixedFrame {
 public:
  static constexpr std::size_t capacity() { return Capacity; }

  constexpr const std::uint8_t *data() const { return storage_.data(); }
  constexpr std::uint8_t *mutableData() { return storage_.data(); }
  constexpr std::size_t size() const { return size_; }
  constexpr ByteView view() const { return {storage_.data(), size_}; }

  constexpr void clear() { size_ = 0U; }

  constexpr bool setSize(std::size_t requested_size) {
    if (requested_size > Capacity) {
      size_ = 0U;
      return false;
    }
    size_ = requested_size;
    return true;
  }

 private:
  std::array<std::uint8_t, Capacity> storage_{};
  std::size_t size_ = 0U;
};

using CommandFrame = FixedFrame<protocol_v1::kMaxCommandFrameBytes>;
using ControlFrame = FixedFrame<protocol_v1::kMaxControlFrameBytes>;
using DataFrame = FixedFrame<protocol_v1::kMaxDataFrameBytes>;

Result decodeFrame(ByteView input, DecodedFrame &frame);
Result encodeFrameTo(FrameFields fields, ByteView payload,
                     MutableByteView output, std::size_t &written);

// Finalize a fixed data frame around payload bytes already written directly
// into [kHeaderSize, kHeaderSize + kDataPayloadBytes). This avoids a second
// 4048-byte staging allocation/copy while still validating the payload and
// constructing the complete header/checksum before queue admission.
Result encodeDataFrameInPlace(FrameFields fields, MutableByteView frame,
                              std::size_t payload_bytes_written);

template <std::size_t Capacity>
Result encodeFrame(FrameFields fields, ByteView payload,
                   FixedFrame<Capacity> &output) {
  std::size_t written = 0U;
  const Result result = encodeFrameTo(
      fields, payload, {output.mutableData(), output.capacity()}, written);
  if (!result.ok() || !output.setSize(written)) {
    output.clear();
    return result.ok()
               ? Result::failure(protocol_v1::ErrorCode::kInvalidLength,
                                 ValidationIssue::kBadLength)
               : result;
  }
  return result;
}

struct Configuration {
  std::uint8_t stream_mask = 0U;
  protocol_v1::Source source = protocol_v1::Source::kHardware;
  protocol_v1::ChecksumAlgorithm data_checksum_algorithm =
      protocol_v1::kDefaultChecksumAlgorithm;
  std::uint32_t data_frame_bytes =
      static_cast<std::uint32_t>(protocol_v1::kDataFrameBytes);
};

struct Request {
  protocol_v1::CommandKind kind = protocol_v1::CommandKind::kInfo;
  std::uint32_t request_id = 0U;
  Configuration configuration{};
  std::uint64_t nonce = 0U;
};

struct ParsedCommand {
  CommandFrame frame{};
  Request request{};
};

Result decodeRequest(ByteView input, Request &request);

struct InfoResponse {
  protocol_v1::DeviceState device_state = protocol_v1::DeviceState::kIdle;
  std::uint8_t supported_stream_mask = 0U;
  std::uint8_t supported_source_mask = 0U;
  std::uint32_t supported_checksum_mask =
      protocol_v1::kSupportedChecksumMask;
  std::uint32_t capability_bits = 0U;
  std::uint32_t timestamp_hz = protocol_v1::kTimestampHz;
  std::uint32_t data_frame_bytes =
      static_cast<std::uint32_t>(protocol_v1::kDataFrameBytes);
  std::uint32_t max_control_frame_bytes =
      static_cast<std::uint32_t>(protocol_v1::kMaxControlFrameBytes);
  std::uint32_t adc_pair_rate_hz = protocol_v1::kAdcPairRateHz;
  std::uint32_t gpio_sample_rate_hz = protocol_v1::kGpioSampleRateHz;
  std::uint16_t adc_pair_period_ticks =
      static_cast<std::uint16_t>(protocol_v1::kAdcPairPeriodTicks);
  std::uint16_t adc1_phase_ticks =
      static_cast<std::uint16_t>(protocol_v1::kAdc1PhaseTicks);
  std::uint16_t gpio_sample_period_ticks =
      static_cast<std::uint16_t>(protocol_v1::kGpioSamplePeriodTicks);
  std::uint8_t adc_resolution_bits = protocol_v1::kAdcResolutionBits;
  std::uint8_t adc_container_bytes = protocol_v1::kAdcContainerBits / 8U;
  std::array<std::uint8_t, protocol_v1::kInfoResponseGpioPinMapCount>
      gpio_pin_map{};
  std::uint32_t hardware_serial = 0U;
  std::uint8_t firmware_version_major = 0U;
  std::uint8_t firmware_version_minor = 0U;
  std::uint8_t firmware_version_patch = 0U;
  protocol_v1::BoardId board_id = protocol_v1::BoardId::kSimulator;
  protocol_v1::McuId mcu_id = protocol_v1::McuId::kSimulated;
  std::array<std::uint8_t, protocol_v1::kInfoResponseBuildIdCount> build_id{};
};

struct StatusResponse {
  protocol_v1::DeviceState device_state = protocol_v1::DeviceState::kIdle;
  Configuration configuration{};
  std::uint64_t adc_frames_emitted = 0U;
  std::uint64_t gpio_frames_emitted = 0U;
  std::uint64_t adc_items_dropped = 0U;
  std::uint64_t gpio_items_dropped = 0U;
  std::uint32_t parser_errors = 0U;
  std::uint32_t transport_errors = 0U;
  std::uint32_t stats_generation = 1U;
};

Result encodeInfoResponse(const Request &request, std::uint32_t run_id,
                          const InfoResponse &response, ControlFrame &output);
Result encodeConfigureResponse(const Request &request, std::uint32_t run_id,
                               const Configuration &configuration,
                               ControlFrame &output);
Result encodeStartResponse(const Request &request, std::uint32_t run_id,
                           const Configuration &configuration,
                           ControlFrame &output);
Result encodeStatusResponse(const Request &request, std::uint32_t run_id,
                            const StatusResponse &response,
                            ControlFrame &output);
Result encodeStopResponse(const Request &request, std::uint32_t run_id,
                          ControlFrame &output);
Result encodeResetStatsResponse(const Request &request, std::uint32_t run_id,
                                std::uint32_t stats_generation,
                                ControlFrame &output);
Result encodePingResponse(const Request &request, std::uint32_t run_id,
                          ControlFrame &output);
Result encodeTypedErrorResponse(const Request &request, std::uint32_t run_id,
                                protocol_v1::ErrorCode error,
                                ControlFrame &output);
Result encodeRejectedFrameResponse(std::uint32_t request_id,
                                   std::uint8_t rejected_kind,
                                   std::uint8_t rejected_version,
                                   protocol_v1::ErrorCode error,
                                   ControlFrame &output);

inline constexpr std::size_t kMagicBytes = sizeof(std::uint32_t);
inline constexpr std::size_t kCommandParserStorageBytes =
    protocol_v1::kMaxCommandFrameBytes + kMagicBytes - 1U;

struct ParserCounters {
  std::uint64_t bytes_received = 0U;
  std::uint64_t bytes_discarded = 0U;
  std::uint32_t commands_accepted = 0U;
  std::uint32_t candidates_rejected = 0U;
  std::uint32_t bad_versions = 0U;
  std::uint32_t bad_kinds = 0U;
  std::uint32_t bad_flags = 0U;
  std::uint32_t bad_lengths = 0U;
  std::uint32_t bad_checksums = 0U;
  std::uint32_t bad_payloads = 0U;
  std::uint32_t bad_request_ids = 0U;
  std::uint32_t unsupported_checksums = 0U;
  std::uint32_t resynchronizations = 0U;
  std::size_t buffered_bytes = 0U;
  std::size_t high_water_mark = 0U;
};

struct FeedResult {
  std::size_t consumed = 0U;
  bool command_ready = false;
};

class IncrementalCommandParser {
 public:
  FeedResult feed(ByteView input, ParsedCommand &command);
  void reset();
  ParserCounters counters() const;

 private:
  bool drain(ParsedCommand &command);
  std::size_t findMagic() const;
  std::size_t partialMagicSuffix() const;
  void discard(std::size_t count);
  void recordFailure(const Result &failure);
  void updateHighWater();

  std::array<std::uint8_t, kCommandParserStorageBytes> buffer_{};
  std::size_t buffered_ = 0U;
  bool resynchronizing_ = false;
  ParserCounters counters_{};
};

static_assert(protocol_v1::kMaxCommandFrameBytes <=
              protocol_v1::kMaxControlFrameBytes);
static_assert(kCommandParserStorageBytes ==
              protocol_v1::kMaxCommandFrameBytes + 3U);

}  // namespace teensy_daq::protocol
