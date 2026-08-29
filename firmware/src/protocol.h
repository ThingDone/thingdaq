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
constexpr bool isSupportedChecksum(
    protocol_v1::ChecksumAlgorithm algorithm) {
  const std::uint8_t identifier = static_cast<std::uint8_t>(algorithm);
  return identifier < 32U &&
         (protocol_v1::kSupportedChecksumMask & (1UL << identifier)) != 0U;
}
Result computeChecksum(protocol_v1::ChecksumAlgorithm algorithm, ByteView input,
                       std::uint32_t &result_checksum);

struct FrameHeader {
  protocol_v1::FrameKind kind = protocol_v1::FrameKind::kInfoRequest;
  std::uint16_t flags = 0U;
  protocol_v1::ChecksumAlgorithm checksum_algorithm =
      protocol_v1::kBootstrapChecksumAlgorithm;
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
      protocol_v1::kBootstrapChecksumAlgorithm;
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

struct ChecksumBenchmarkRequest {
  protocol_v1::ChecksumAlgorithm checksum_algorithm =
      protocol_v1::kDefaultChecksumAlgorithm;
  protocol_v1::BenchmarkVector vector =
      protocol_v1::BenchmarkVector::kEmpty;
  protocol_v1::BenchmarkMemoryRegion memory_region =
      protocol_v1::BenchmarkMemoryRegion::kDtcmPacket;
  protocol_v1::BenchmarkCacheState cache_state =
      protocol_v1::BenchmarkCacheState::kHotOrNative;
  std::uint16_t batch_count = 1U;
  std::uint16_t iterations_per_batch = 1U;
};

struct GpioClockDiagnosticRequest {
  std::uint32_t rate_hz = protocol_v1::kGpioClockProductionRateHz;
  std::uint16_t event_count = protocol_v1::kGpioClockMaxEventCount;
};

constexpr std::uint32_t benchmarkVectorBytes(
    protocol_v1::BenchmarkVector vector) {
  switch (vector) {
    case protocol_v1::BenchmarkVector::kEmpty:
      return 0U;
    case protocol_v1::BenchmarkVector::kCanonical123456789:
      return 9U;
    case protocol_v1::BenchmarkVector::kBuffer64:
      return 64U;
    case protocol_v1::BenchmarkVector::kBuffer512:
      return 512U;
    case protocol_v1::BenchmarkVector::kFrameCoverage:
      return static_cast<std::uint32_t>(protocol_v1::kDataFrameBytes -
                                        protocol_v1::kTrailerSize);
  }
  return 0U;
}

bool validChecksumBenchmarkRequest(const ChecksumBenchmarkRequest &request);
bool validGpioClockDiagnosticRequest(
    const GpioClockDiagnosticRequest &request);

struct Request {
  protocol_v1::CommandKind kind = protocol_v1::CommandKind::kInfo;
  std::uint32_t request_id = 0U;
  Configuration configuration{};
  ChecksumBenchmarkRequest checksum_benchmark{};
  GpioClockDiagnosticRequest gpio_clock_diagnostic{};
  std::uint64_t nonce = 0U;
};

struct ParsedCommand {
  CommandFrame frame{};
  Request request{};
};

Result decodeRequest(ByteView input, Request &request);

// Raw register evidence captured while the exact ADC_ETC schedule is
// configured but stopped. The final IRQ words are captured after the bounded
// completion-timing diagnostic has been stopped and acknowledged.
struct AdcTriggerHardwareEvidence {
  std::uint32_t ccm_cscmr1_configured = 0U;
  std::uint32_t ccm_ccgr1_configured = 0U;
  std::uint32_t ccm_ccgr2_configured = 0U;
  std::uint32_t pit_mcr_configured = 0U;
  std::uint32_t gpio_master_tctrl_configured = 0U;
  std::uint32_t pair_tctrl_configured = 0U;
  std::uint32_t adc_etc_ctrl_configured = 0U;
  std::array<std::uint32_t, 2U> trigger_ctrl_configured{};
  std::array<std::uint32_t, 2U> trigger_counter_configured{};
  std::array<std::uint32_t, 2U> chain_configured{};
  std::uint32_t done0_1_irq_final = 0U;
  std::uint32_t done2_err_irq_final = 0U;
  std::array<std::uint16_t, 2U> xbar_sel_configured{};
};

// The measured delta below is conversion-completion interrupt timing. It
// cross-checks the programmed digital phase but does not claim to measure the
// analog aperture at either ADC input.
struct AdcTriggerMetadata {
  std::uint16_t configuration_flags = 0U;
  std::uint32_t error_flags = 0U;
  std::uint32_t pit_clock_hz = protocol_v1::kAdcTriggerPitClockHz;
  std::uint32_t dwt_clock_hz = protocol_v1::kAdcTriggerDwtClockHz;
  std::uint32_t gpio_master_rate_hz =
      protocol_v1::kAdcTriggerGpioMasterRateHz;
  std::uint32_t pair_rate_hz = protocol_v1::kAdcTriggerPairRateHz;
  std::uint32_t ipg_clock_hz = protocol_v1::kAdcTriggerIpgClockHz;
  std::uint8_t gpio_master_pit_channel =
      protocol_v1::kAdcTriggerGpioMasterPitChannel;
  std::uint8_t pair_pit_channel =
      protocol_v1::kAdcTriggerPairPitChannel;
  std::uint8_t gpio_master_pit_load =
      protocol_v1::kAdcTriggerGpioMasterPitLoad;
  std::uint8_t pair_pit_load = protocol_v1::kAdcTriggerPairPitLoad;
  std::uint8_t predivider = protocol_v1::kAdcTriggerPredivider;
  std::uint8_t chain_length = protocol_v1::kAdcTriggerChainLength;
  std::array<std::uint8_t, 2U> xbar_inputs{
      protocol_v1::kAdcTriggerXbarInputs[0],
      protocol_v1::kAdcTriggerXbarInputs[1]};
  std::array<std::uint8_t, 2U> xbar_outputs{
      protocol_v1::kAdcTriggerXbarOutputs[0],
      protocol_v1::kAdcTriggerXbarOutputs[1]};
  std::array<std::uint8_t, 2U> trigger_queues{
      protocol_v1::kAdcTriggerQueues[0],
      protocol_v1::kAdcTriggerQueues[1]};
  std::array<std::uint16_t, 2U> initial_delays{
      protocol_v1::kAdcTriggerInitialDelays[0],
      protocol_v1::kAdcTriggerInitialDelays[1]};
  std::array<std::uint16_t, 2U> effective_delays{
      protocol_v1::kAdcTriggerEffectiveDelays[0],
      protocol_v1::kAdcTriggerEffectiveDelays[1]};
  std::uint16_t phase_ipg_cycles = protocol_v1::kAdcTriggerPhaseIpgCycles;
  AdcTriggerHardwareEvidence evidence{};
  std::array<std::uint32_t, 2U> completion_counts{};
  std::uint32_t completion_delta_cycles = 0U;
  std::uint32_t completion_expected_delta_cycles =
      protocol_v1::kAdcCompletionExpectedDwtCycles;
  std::uint32_t completion_tolerance_cycles =
      protocol_v1::kAdcCompletionToleranceDwtCycles;
  std::uint32_t diagnostic_elapsed_cycles = 0U;
  std::uint32_t trigger_error_count = 0U;
};

// Shared INFO/STATUS view of the configuration actually written to the two
// ADC modules and the terminal result of each independently bounded
// calibration. Defaults describe the primary policy before initialization;
// they never claim that calibration has run.
struct AdcInitializationMetadata {
  std::uint8_t resolution_bits = protocol_v1::kAdcPrimaryResolutionBits;
  std::uint8_t container_bytes = protocol_v1::kAdcContainerBits / 8U;
  std::uint16_t code_min = protocol_v1::kAdcCodeMin;
  std::uint16_t code_max = 4095U;
  protocol_v1::AdcReference reference =
      protocol_v1::AdcReference::kVrefhVreflNominal3v3;
  protocol_v1::AdcClockSource clock_source =
      protocol_v1::AdcClockSource::kSynchronousIpg;
  std::uint8_t clock_divider = protocol_v1::kAdcClockDivider;
  std::uint8_t hardware_average_count =
      protocol_v1::kAdcHardwareAverageCount;
  std::uint16_t reference_mv_nominal =
      protocol_v1::kAdcReferenceMvNominal;
  std::uint16_t input_min_mv_nominal =
      protocol_v1::kAdcInputMinMvNominal;
  std::uint16_t input_max_mv_nominal =
      protocol_v1::kAdcInputMaxMvNominal;
  std::uint8_t sample_time_adck = protocol_v1::kAdcSampleTimeAdck;
  std::uint8_t conversion_mode = 2U;
  std::uint16_t configuration_flags =
      static_cast<std::uint16_t>(
          protocol_v1::AdcConfigurationFlag::kNoHardwareAveraging) |
      static_cast<std::uint16_t>(
          protocol_v1::AdcConfigurationFlag::kHighSpeed) |
      static_cast<std::uint16_t>(
          protocol_v1::AdcConfigurationFlag::kShortestSample) |
      static_cast<std::uint16_t>(
          protocol_v1::AdcConfigurationFlag::kPrimary12Bit);
  std::array<protocol_v1::AdcCalibrationState, 2U> calibration_states{
      protocol_v1::AdcCalibrationState::kNotRun,
      protocol_v1::AdcCalibrationState::kNotRun,
  };
  std::array<std::uint8_t, 2U> pins{protocol_v1::kAdcPins[0],
                                    protocol_v1::kAdcPins[1]};
  std::array<std::uint8_t, 2U> peripherals{
      protocol_v1::kAdcPeripherals[0], protocol_v1::kAdcPeripherals[1]};
  std::array<std::uint8_t, 2U> channels{protocol_v1::kAdcChannels[0],
                                        protocol_v1::kAdcChannels[1]};
  std::uint32_t ipg_clock_hz = protocol_v1::kAdcIpgClockHz;
  std::uint32_t adc_clock_hz = protocol_v1::kAdcClockHz;
  std::uint32_t calibration_deadline_us =
      protocol_v1::kAdcCalibrationDeadlineUs;
  std::array<std::uint32_t, 2U> calibration_cycles{};
  std::uint32_t initialization_error_flags = 0U;
  AdcTriggerMetadata trigger{};
};

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
  protocol_v1::ChecksumAlgorithm data_checksum_algorithm =
      protocol_v1::kDefaultChecksumAlgorithm;
  std::array<std::uint8_t, protocol_v1::kInfoResponseGpioPinMapCount>
      gpio_pin_map{};
  std::uint32_t hardware_serial = 0U;
  std::uint8_t firmware_version_major = 0U;
  std::uint8_t firmware_version_minor = 0U;
  std::uint8_t firmware_version_patch = 0U;
  protocol_v1::BoardId board_id = protocol_v1::BoardId::kSimulator;
  protocol_v1::McuId mcu_id = protocol_v1::McuId::kSimulated;
  std::array<std::uint8_t, protocol_v1::kInfoResponseBuildIdCount> build_id{};
  std::uint8_t gpio_packed_width_bits = protocol_v1::kGpioPackedWidthBits;
  std::uint8_t gpio_raw_ring_depth = protocol_v1::kGpioRawRingDepth;
  std::uint8_t gpio_packed_ring_depth = protocol_v1::kGpioPackedRingDepth;
  protocol_v1::GpioCaptureDiagnosticMode gpio_capture_diagnostic_mode =
      protocol_v1::GpioCaptureDiagnosticMode::kNonDrivingCapture;
  std::uint16_t gpio_capture_diagnostic_flags = 0U;
  std::uint32_t gpio_raw_samples_per_buffer =
      protocol_v1::kGpioRawSamplesPerBuffer;
  std::uint32_t gpio_raw_ring_bytes = protocol_v1::kGpioRawRingBytes;
  std::uint32_t gpio_packed_ring_bytes = protocol_v1::kGpioPackedRingBytes;
  std::uint16_t gpio_packet_buffer_count =
      protocol_v1::kGpioPacketBufferCount;
  std::uint8_t gpio_pit_channel = protocol_v1::kGpioPitChannel;
  std::uint8_t gpio_xbar_input = protocol_v1::kGpioXbarInput;
  std::uint8_t gpio_xbar_output = protocol_v1::kGpioXbarOutput;
  std::uint8_t gpio_edma_channel = protocol_v1::kGpioEdmaChannel;
  std::uint8_t gpio_dmamux_source = protocol_v1::kGpioDmamuxSource;
  std::uint8_t gpio_edma_priority = protocol_v1::kGpioEdmaPriority;
  std::uint8_t gpio_xbar_active_edge = protocol_v1::kGpioXbarActiveEdge;
  AdcInitializationMetadata adc{};
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
  std::uint64_t gpio_samples_captured = 0U;
  std::uint64_t gpio_samples_packed = 0U;
  std::uint64_t gpio_samples_framed = 0U;
  std::uint64_t gpio_samples_transmitted = 0U;
  std::uint64_t gpio_raw_samples_lost = 0U;
  std::uint64_t gpio_packer_samples_dropped = 0U;
  std::uint64_t gpio_raw_ring_overruns = 0U;
  std::uint64_t gpio_dma_major_loops = 0U;
  std::uint16_t gpio_raw_ready_depth = 0U;
  std::uint16_t gpio_raw_ready_high_water = 0U;
  std::uint16_t gpio_packed_ready_depth = 0U;
  std::uint16_t gpio_packed_ready_high_water = 0U;
  std::uint16_t packet_ready_depth = 0U;
  std::uint16_t packet_transmit_depth = 0U;
  std::uint16_t packet_owned_high_water = 0U;
  std::uint16_t gpio_processing_cpu_basis_points = 0U;
  std::uint32_t gpio_hardware_errors = 0U;
  std::uint32_t gpio_raw_invariant_errors = 0U;
  std::uint32_t gpio_packer_source_errors = 0U;
  std::uint32_t gpio_packer_pipeline_errors = 0U;
  std::uint32_t gpio_packer_chronology_errors = 0U;
  std::uint32_t gpio_resource_conflicts = 0U;
  std::uint32_t gpio_start_errors = 0U;
  std::uint32_t gpio_stop_errors = 0U;
  std::uint32_t gpio_stale_dma_completions = 0U;
  AdcInitializationMetadata adc{};
  std::uint64_t adc0_dma_major_loops = 0U;
  std::uint64_t adc1_dma_major_loops = 0U;
  std::uint64_t adc0_dma_results = 0U;
  std::uint64_t adc1_dma_results = 0U;
  std::uint64_t adc_paired_major_loops = 0U;
  std::uint64_t adc_buffers_completed = 0U;
  std::uint64_t adc_buffers_acquired = 0U;
  std::uint64_t adc_buffers_released = 0U;
  std::uint64_t adc_pairs_captured = 0U;
  std::uint64_t adc_pairs_delivered = 0U;
  std::uint64_t adc_pairs_framed = 0U;
  std::uint64_t adc_pairs_transmitted = 0U;
  std::uint64_t adc_raw_pairs_lost = 0U;
  std::uint64_t adc_stop_pairs_discarded = 0U;
  std::uint64_t adc_incomplete_conversions = 0U;
  std::uint64_t adc_overwritten_conversions = 0U;
  std::uint64_t adc_raw_ring_overruns = 0U;
  std::uint64_t adc_incomplete_buffers = 0U;
  std::uint16_t adc_raw_ready_depth = 0U;
  std::uint16_t adc_raw_ready_high_water = 0U;
  std::uint32_t adc_etc_error_events = 0U;
  std::uint32_t adc_etc_error_flags = 0U;
  std::uint32_t adc_dma_error_events = 0U;
  std::uint32_t adc_completion_mismatches = 0U;
  std::uint32_t adc_destination_mismatches = 0U;
  std::uint32_t adc_schedule_exhaustions = 0U;
  std::uint32_t adc_raw_invariant_errors = 0U;
  std::uint32_t adc_stale_completions = 0U;
  std::uint32_t adc_resource_conflicts = 0U;
  std::uint32_t adc_start_errors = 0U;
  std::uint32_t adc_stop_errors = 0U;
  std::uint32_t adc_stale_interrupts = 0U;
  std::uint32_t adc_packer_source_errors = 0U;
  std::uint32_t adc_packer_pipeline_errors = 0U;
  std::uint32_t adc_packer_chronology_errors = 0U;
};

struct ChecksumBenchmarkResponse {
  ChecksumBenchmarkRequest request{};
  std::uint32_t buffer_bytes = 0U;
  std::uint32_t cycle_counter_hz = 0U;
  std::uint32_t timer_overhead_cycles = 0U;
  std::uint32_t implementation_code_bytes = 0U;
  std::uint32_t table_bytes = 0U;
  std::uint32_t working_ram_bytes = 0U;
  std::uint32_t deterministic_digest = 0U;
  std::uint64_t processed_bytes = 0U;
  std::uint64_t raw_checksum_cycles = 0U;
  std::uint64_t net_checksum_cycles = 0U;
  std::uint64_t cache_setup_cycles = 0U;
  std::uint32_t min_batch_cycles = 0U;
  std::uint32_t max_batch_cycles = 0U;
  std::uint32_t cycles_per_byte_q16 = 0U;
  std::uint32_t mb_per_second_q16 = 0U;
  std::uint32_t projected_cpu_percent_q16 = 0U;
  std::uint32_t target_framed_bytes_per_second =
      protocol_v1::kChecksumBenchmarkTargetFramedBytesPerSecond;
};

// Read-only register and count evidence from one bounded, IDLE-only
// PIT/XBARA/eDMA clock measurement. Configuration fields are captured while
// armed; terminal fields are captured after the trigger has been stopped.
struct GpioClockDiagnosticResponse {
  std::uint32_t configured_rate_hz = 0U;
  std::uint32_t production_rate_hz =
      protocol_v1::kGpioClockProductionRateHz;
  std::uint32_t pit_clock_hz = protocol_v1::kGpioClockPitHz;
  std::uint32_t pit_load_value = 0U;
  std::uint32_t requested_event_count = 0U;
  std::uint32_t scheduled_event_count = 0U;
  std::uint32_t dma_sample_count = 0U;
  std::uint32_t dwt_counter_hz = 0U;
  std::uint32_t dwt_elapsed_cycles = 0U;
  std::uint32_t hardware_error_flags = 0U;
  std::uint32_t ccm_cscmr1_configured = 0U;
  std::uint32_t ccm_ccgr1_configured = 0U;
  std::uint32_t ccm_ccgr2_configured = 0U;
  std::uint32_t ccm_ccgr5_configured = 0U;
  std::uint32_t pit_mcr_configured = 0U;
  std::uint32_t pit_ldval_configured = 0U;
  std::uint32_t pit_cval_final = 0U;
  std::uint32_t pit_tctrl_configured = 0U;
  std::uint32_t pit_tflg_final = 0U;
  std::uint16_t xbar_sel_configured = 0U;
  std::uint16_t xbar_ctrl_configured = 0U;
  std::uint32_t dmamux_chcfg_configured = 0U;
  std::uint32_t dma_cr_configured = 0U;
  std::uint32_t dma_es_final = 0U;
  std::uint32_t dma_erq_configured = 0U;
  std::uint32_t dma_err_final = 0U;
  std::uint32_t dma_hrs_final = 0U;
  std::uint32_t tcd_saddr = 0U;
  std::uint32_t tcd_daddr = 0U;
  std::uint32_t tcd_nbytes = 0U;
  std::uint32_t last_sample_word = 0U;
  std::uint16_t tcd_citer_final = 0U;
  std::uint16_t tcd_biter = 0U;
  std::uint16_t tcd_csr_final = 0U;
  std::uint16_t tcd_attr = 0U;
  std::uint8_t pit_channel = 0U;
  std::uint8_t xbar_input = 0U;
  std::uint8_t xbar_output = 0U;
  std::uint8_t edma_channel = 0U;
  std::uint8_t dmamux_source = 0U;
  std::uint8_t edma_priority = 0U;
  std::uint16_t tcd_soff = 0U;
};

// Bounded evidence from the safe, IDLE-only GPIO capture diagnostic. Fixture
// declaration fields are byte-for-byte policy metadata and never authorize a
// host request to drive pins.
struct GpioCaptureDiagnosticResponse {
  protocol_v1::GpioCaptureDiagnosticMode mode =
      protocol_v1::GpioCaptureDiagnosticMode::kNonDrivingCapture;
  std::uint8_t metadata_kind = 0U;
  std::uint8_t drive_safety = 0U;
  std::uint8_t stimulus_kind = 0U;
  std::uint32_t fixture_identity = 0U;
  std::uint32_t stimulus_identity = 0U;
  std::uint32_t hardware_error_flags = 0U;
  std::uint32_t diagnostic_flags = 0U;
  std::uint32_t dwt_counter_hz = 0U;
  std::uint32_t dwt_elapsed_cycles = 0U;
  std::uint64_t dma_samples_captured = 0U;
  std::uint32_t complete_samples_retained = 0U;
  std::uint32_t samples_analyzed = 0U;
  std::uint32_t stopped_partial_samples = 0U;
  std::uint32_t raw_word_and = 0U;
  std::uint32_t raw_word_or = 0U;
  std::uint32_t observed_transitions = 0U;
  std::uint16_t mapping_values_checked = 0U;
  std::uint16_t mapping_failures = 0U;
  std::uint16_t unstable_samples = 0U;
  std::uint8_t packed_value_and = 0U;
  std::uint8_t packed_value_or = 0U;
  std::uint8_t first_packed_value = 0U;
  std::uint8_t last_packed_value = 0U;
  std::uint32_t gpr27_before = 0U;
  std::uint32_t gpr27_configured = 0U;
  std::uint32_t gpr27_after = 0U;
  std::uint32_t gpio2_gdir_before = 0U;
  std::uint32_t gpio2_gdir_configured = 0U;
  std::uint32_t gpio2_gdir_after = 0U;
  std::uint32_t gpio2_psr_before = 0U;
  std::uint32_t gpio2_psr_configured = 0U;
  std::uint32_t gpio2_psr_after = 0U;
  std::uint32_t pit_ldval_configured = 0U;
  std::uint32_t pit_tctrl_configured = 0U;
  std::uint32_t dmamux_chcfg_configured = 0U;
  std::uint32_t dma_erq_configured = 0U;
  std::uint32_t dma_err_final = 0U;
  std::uint16_t tcd_citer_configured = 0U;
  std::uint16_t tcd_biter_configured = 0U;
  std::uint16_t tcd_csr_configured = 0U;
  std::uint8_t edma_priority_configured = 0U;
  std::uint32_t analysis_sample_limit =
      protocol_v1::kGpioCaptureDiagnosticAnalysisSamples;
};

// Fill processed-byte and fixed-point derived fields from the raw measurement.
// Returns false on an invalid request, zero nonempty work, or integer overflow.
bool populateChecksumBenchmarkMetrics(ChecksumBenchmarkResponse &response);

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
Result encodeChecksumBenchmarkResponse(
    const Request &request, std::uint32_t run_id,
    const ChecksumBenchmarkResponse &response, ControlFrame &output);
Result encodeGpioClockDiagnosticResponse(
    const Request &request, std::uint32_t run_id,
    const GpioClockDiagnosticResponse &response, ControlFrame &output);
Result encodeGpioCaptureDiagnosticResponse(
    const Request &request, std::uint32_t run_id,
    const GpioCaptureDiagnosticResponse &response, ControlFrame &output);
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
