#pragma once

#include <cstddef>
#include <cstdint>

#include "adc_dma_capture.h"
#include "adc_frame_packer.h"
#include "adc_initializer.h"
#include "adc_trigger.h"
#include "gpio_batch_packer.h"
#include "gpio_dual_bank_capture.h"
#include "gpio_dual_bank_packer.h"
#include "gpio_raw_capture.h"
#include "packet_buffer_pipeline.h"
#include "statistics.h"
#include "stream_layout.h"
#include "variable_rate_scheduler.h"

namespace thingdaq::acquisition {

enum class Profile : std::uint8_t {
  kNone,
  kAdc,
  kGpio,
  kCombined,
  kInvalid,
};

enum class Conflict : std::uint32_t {
  kPinContract = 1U << 0U,
  kPitContract = 1U << 1U,
  kXbarContract = 1U << 2U,
  kAdcEtcContract = 1U << 3U,
  kEdmaContract = 1U << 4U,
  kIrqPriorityContract = 1U << 5U,
  kDmaMemoryContract = 1U << 6U,
  kCacheRegionContract = 1U << 7U,
  kInvalidProfile = 1U << 8U,
  kControllerBusy = 1U << 9U,
  kAdcComponentsMissing = 1U << 10U,
  kGpioComponentsMissing = 1U << 11U,
  kAdcTriggerUnavailable = 1U << 12U,
  kAdcTriggerRunning = 1U << 13U,
  kAdcPackerBusy = 1U << 14U,
  kAdcCaptureUnavailable = 1U << 15U,
  kGpioPackerBusy = 1U << 16U,
  kGpioCaptureUnavailable = 1U << 17U,
  kInvalidConfiguration = 1U << 18U,
  kInvalidRunId = 1U << 19U,
  kAuxGpioComponentsMissing = 1U << 20U,
  kAuxGpioPackerBusy = 1U << 21U,
  kAuxGpioCaptureUnavailable = 1U << 22U,
  kRateSchedulerUnavailable = 1U << 23U,
};

constexpr std::uint32_t conflictBit(Conflict conflict) {
  return static_cast<std::uint32_t>(conflict);
}

struct Audit {
  board::AcquisitionResourceContract contract =
      board::kAcquisitionResourceContract;
  Profile profile = Profile::kNone;
  adc_capture::StartStatus adc_capture_status =
      adc_capture::StartStatus::kNotQuiescent;
  gpio_capture::StartStatus gpio_capture_status =
      gpio_capture::StartStatus::kNotQuiescent;
  gpio_join::StartStatus aux_gpio_capture_status =
      gpio_join::StartStatus::kNotQuiescent;
  std::uint32_t conflict_flags = 0U;
  bool adc_inspected = false;
  bool gpio_inspected = false;
  bool aux_gpio_inspected = false;

  constexpr bool has(Conflict conflict) const {
    return (conflict_flags & conflictBit(conflict)) != 0U;
  }
  constexpr bool ready() const {
    return profile != Profile::kNone && profile != Profile::kInvalid &&
           conflict_flags == 0U;
  }
};

// Physical acquisition details are a base of runtime::LoopReport so existing
// diagnostics remain source compatible while orchestration moves behind this
// single owner.
struct Report {
  packet::StopReport packet_stop{};
  gpio_packer::ServiceReport gpio_packer{};
  gpio_capture::StopReport gpio_capture_stop{};
  gpio_packer::StopReport gpio_packer_stop{};
  gpio_aux_packer::ServiceReport aux_gpio_packer{};
  gpio_join::StopReport aux_gpio_capture_stop{};
  adc_packer::ServiceReport adc_packer{};
  adc_capture::StopReport adc_capture_stop{};
  adc_packer::StopReport adc_packer_stop{};
  gpio_capture::StartStatus gpio_capture_start_status =
      gpio_capture::StartStatus::kNotQuiescent;
  gpio_packer::OperationStatus gpio_packer_start_status =
      gpio_packer::OperationStatus::kNotRunning;
  gpio_join::StartStatus aux_gpio_capture_start_status =
      gpio_join::StartStatus::kNotQuiescent;
  gpio_aux_packer::OperationStatus aux_gpio_packer_start_status =
      gpio_aux_packer::OperationStatus::kNotRunning;
  adc_capture::StartStatus adc_capture_start_status =
      adc_capture::StartStatus::kNotQuiescent;
  adc_packer::OperationStatus adc_packer_start_status =
      adc_packer::OperationStatus::kNotRunning;
  bool gpio_capture_started = false;
  bool gpio_capture_prepared = false;
  bool gpio_capture_stopped = false;
  bool gpio_packer_started = false;
  bool gpio_packer_stopped = false;
  bool aux_gpio_capture_started = false;
  bool aux_gpio_capture_prepared = false;
  bool aux_gpio_capture_stopped = false;
  bool aux_gpio_packer_started = false;
  bool aux_gpio_packer_stopped = false;
  bool adc_capture_prepared = false;
  bool adc_capture_boundary_stopped = false;
  bool adc_capture_stopped = false;
  bool adc_packer_started = false;
  bool adc_packer_stopped = false;
  bool adc_trigger_armed = false;
  bool adc_trigger_stopped = false;
  bool rate_configured = false;
  bool rate_restored = false;
  variable_rate::Status rate_configure_status =
      variable_rate::Status::kUnsupportedProfile;
  bool packet_production_stopped = false;
  bool physical_drain_pending = false;
  bool physical_fault_detected = false;
  bool internal_error = false;
  std::uint32_t run_id = 0U;
  std::uint64_t epoch_ticks = 0U;
};

// The sole physical-acquisition orchestrator. It composes the proven Phase 06
// and Phase 07 engines without owning their storage, performs one read-only
// all-resource audit, and preserves the accepted single-source lifecycle.
// Combined mode prepares all three fixed DMA channels before enabling the
// ADC_ETC/PIT1/PIT0 schedule exactly once.
class Controller {
 public:
  constexpr Controller(
      stats::Statistics &statistics,
      packet::PacketBufferPipeline &packet_pipeline,
      gpio_capture::HardwareCapture *gpio_capture = nullptr,
      gpio_packer::GpioBatchPacker *gpio_packer = nullptr,
      adc::Initializer *adc_initializer = nullptr,
      adc_trigger::Scheduler *adc_trigger_scheduler = nullptr,
      adc_capture::HardwareCapture *adc_capture = nullptr,
      adc_packer::AdcFramePacker *adc_packer = nullptr,
      variable_rate::Scheduler *rate_scheduler = nullptr,
      gpio_join::HardwareCapture *aux_gpio_capture = nullptr,
      gpio_aux_packer::AuxiliaryBatchPacker *aux_gpio_packer = nullptr)
      : statistics_(statistics),
        packet_pipeline_(packet_pipeline),
        gpio_capture_(gpio_capture),
        gpio_packer_(gpio_packer),
        adc_initializer_(adc_initializer),
        adc_trigger_scheduler_(adc_trigger_scheduler),
        adc_capture_(adc_capture),
        adc_packer_(adc_packer),
        rate_scheduler_(rate_scheduler),
        aux_gpio_capture_(aux_gpio_capture),
        aux_gpio_packer_(aux_gpio_packer) {}

  protocol::AdcInitializationMetadata initialize();
  Audit inspect(const protocol::Configuration &configuration,
                std::uint32_t epoch);
  bool readyForStart(const protocol::Configuration &configuration,
                     std::uint32_t epoch);
  bool start(const protocol::Configuration &configuration,
             std::uint32_t run_id, std::uint64_t epoch_ticks,
             Report &report);
  bool stop(Report &report);
  void service(Report &report);
  void publishStatistics(std::uint32_t run_id);
  bool quiescent() const;

  constexpr bool active() const { return physical_run_active_; }
  constexpr bool drainPending() const { return physical_drain_pending_; }
  constexpr std::uint8_t activeStreamMask() const {
    return physical_stream_mask_;
  }
  constexpr std::uint32_t activeRunId() const { return physical_run_id_; }
  constexpr std::uint64_t epochTicks() const { return physical_epoch_ticks_; }

  static constexpr Profile profileFor(
      const protocol::Configuration &configuration) {
    if (configuration.source != protocol_v1::Source::kHardware) {
      return Profile::kNone;
    }
    const std::uint8_t adc =
        static_cast<std::uint8_t>(protocol_v1::StreamMask::kAdc);
    const std::uint8_t gpio =
        static_cast<std::uint8_t>(protocol_v1::StreamMask::kGpio);
    if (configuration.stream_mask == adc) {
      return Profile::kAdc;
    }
    if (configuration.stream_mask == gpio) {
      return Profile::kGpio;
    }
    if (configuration.stream_mask == static_cast<std::uint8_t>(adc | gpio)) {
      return Profile::kCombined;
    }
    return configuration.stream_mask == 0U ? Profile::kNone
                                            : Profile::kInvalid;
  }

  static constexpr bool isHardwareConfiguration(
      const protocol::Configuration &configuration) {
    const Profile profile = profileFor(configuration);
    return profile == Profile::kAdc || profile == Profile::kGpio ||
           profile == Profile::kCombined;
  }

  static constexpr bool isExecutableConfiguration(
      const protocol::Configuration &configuration) {
    const Profile profile = profileFor(configuration);
    return profile == Profile::kAdc || profile == Profile::kGpio ||
           profile == Profile::kCombined;
  }

  static stream_layout::Result runLayout(
      const protocol::Configuration &configuration);

 private:
  bool stopAdcPath(Report &report);
  bool stopCombinedPaths(Report &report);
  void rollbackStart(Profile profile, Report &report);
  void serviceAdcPath(Report &report, bool draining);
  void serviceGpioPath(Report &report, bool draining);
  bool adcPathDrained(Report &report);
  bool gpioPathDrained(Report &report);
  bool activePathFaulted() const;
  void clearRunState();
  static void addStaticContractConflicts(Audit &audit);
  static bool completeConfigurationValid(
      const protocol::Configuration &configuration);

  stats::Statistics &statistics_;
  packet::PacketBufferPipeline &packet_pipeline_;
  gpio_capture::HardwareCapture *gpio_capture_ = nullptr;
  gpio_packer::GpioBatchPacker *gpio_packer_ = nullptr;
  adc::Initializer *adc_initializer_ = nullptr;
  adc_trigger::Scheduler *adc_trigger_scheduler_ = nullptr;
  adc_capture::HardwareCapture *adc_capture_ = nullptr;
  adc_packer::AdcFramePacker *adc_packer_ = nullptr;
  variable_rate::Scheduler *rate_scheduler_ = nullptr;
  gpio_join::HardwareCapture *aux_gpio_capture_ = nullptr;
  gpio_aux_packer::AuxiliaryBatchPacker *aux_gpio_packer_ = nullptr;
  std::uint8_t physical_stream_mask_ = 0U;
  std::uint32_t physical_run_id_ = 0U;
  std::uint64_t physical_epoch_ticks_ = 0U;
  protocol_v2::AuxBankMode physical_aux_bank_mode_ =
      protocol_v2::kDefaultAuxBankMode;
  protocol_v2::RateProfile physical_rate_profile_ =
      protocol_v2::kDefaultRateProfile;
  protocol_v2::RateProfile previous_rate_profile_ =
      protocol_v2::kDefaultRateProfile;
  bool restore_rate_on_rollback_ = false;
  bool physical_run_active_ = false;
  bool physical_drain_pending_ = false;
  bool physical_start_pending_ = false;
};

static_assert(board::kAcquisitionResourceContract.valid());
static_assert(protocol_v1::kGpioSamplesPerFrame *
                      protocol_v1::kGpioSamplePeriodTicks ==
                  protocol_v1::kAdcPairsPerFrame *
                      protocol_v1::kAdcPairPeriodTicks,
              "combined ADC/GPIO frames must cover the same epoch interval");
static_assert(4U * protocol_v1::kGpioSamplePeriodTicks ==
                  protocol_v1::kAdcPairPeriodTicks,
              "four GPIO samples must cover one ADC pair period");
static_assert(protocol_v1::kAdc1PhaseTicks * 2U ==
                  protocol_v1::kAdcPairPeriodTicks,
              "ADC1 must retain the nominal half-period phase");

}  // namespace thingdaq::acquisition
