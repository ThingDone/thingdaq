#include "acquisition_controller.h"

#if defined(__IMXRT1062__)
#define TEENSY_DAQ_ACQUISITION_COLD_CODE(section_name) \
  __attribute__((section(section_name), noinline, noipa, used))
#else
#define TEENSY_DAQ_ACQUISITION_COLD_CODE(section_name)
#endif

namespace teensy_daq::acquisition {
namespace {

constexpr std::uint8_t streamBit(protocol_v1::StreamMask stream) {
  return static_cast<std::uint8_t>(stream);
}

constexpr bool includesAdc(Profile profile) {
  return profile == Profile::kAdc || profile == Profile::kCombined;
}

constexpr bool includesGpio(Profile profile) {
  return profile == Profile::kGpio || profile == Profile::kCombined;
}

void addConflict(Audit &audit, Conflict conflict) {
  audit.conflict_flags |= conflictBit(conflict);
}

}  // namespace

TEENSY_DAQ_ACQUISITION_COLD_CODE(".flashmem.acquisition.initialize")
protocol::AdcInitializationMetadata Controller::initialize() {
  protocol::AdcInitializationMetadata metadata{};
  bool converters_ready = false;
  if (adc_initializer_ != nullptr) {
    const adc::Snapshot &snapshot = adc_initializer_->initialize();
    metadata = adc::protocolMetadata(snapshot);
    converters_ready = snapshot.ready();
  }
  if (adc_trigger_scheduler_ != nullptr) {
    const adc_trigger::Snapshot &trigger_snapshot =
        adc_trigger_scheduler_->initialize(converters_ready);
    metadata.trigger = adc_trigger::protocolMetadata(trigger_snapshot);
  }
  return metadata;
}

void Controller::addStaticContractConflicts(Audit &audit) {
  if (!audit.contract.pins) {
    addConflict(audit, Conflict::kPinContract);
  }
  if (!audit.contract.pit) {
    addConflict(audit, Conflict::kPitContract);
  }
  if (!audit.contract.xbar) {
    addConflict(audit, Conflict::kXbarContract);
  }
  if (!audit.contract.adc_etc) {
    addConflict(audit, Conflict::kAdcEtcContract);
  }
  if (!audit.contract.edma) {
    addConflict(audit, Conflict::kEdmaContract);
  }
  if (!audit.contract.irq_priorities) {
    addConflict(audit, Conflict::kIrqPriorityContract);
  }
  if (!audit.contract.dma_memory) {
    addConflict(audit, Conflict::kDmaMemoryContract);
  }
  if (!audit.contract.cache_regions) {
    addConflict(audit, Conflict::kCacheRegionContract);
  }
}

TEENSY_DAQ_ACQUISITION_COLD_CODE(
    ".flashmem.acquisition.configuration_validation")
bool Controller::completeConfigurationValid(
    const protocol::Configuration &configuration) {
  const Profile profile = profileFor(configuration);
  return (profile == Profile::kAdc || profile == Profile::kGpio ||
          profile == Profile::kCombined) &&
         configuration.data_frame_bytes == protocol_v1::kDataFrameBytes &&
         protocol::isSupportedChecksum(
             configuration.data_checksum_algorithm);
}

TEENSY_DAQ_ACQUISITION_COLD_CODE(".flashmem.acquisition.inspect")
Audit Controller::inspect(const protocol::Configuration &configuration,
                          std::uint32_t epoch) {
  Audit audit{};
  audit.profile = profileFor(configuration);
  addStaticContractConflicts(audit);
  if (audit.profile == Profile::kNone || audit.profile == Profile::kInvalid) {
    addConflict(audit, Conflict::kInvalidProfile);
    return audit;
  }
  if (!completeConfigurationValid(configuration)) {
    addConflict(audit, Conflict::kInvalidConfiguration);
    return audit;
  }
  if (epoch == 0U) {
    addConflict(audit, Conflict::kInvalidRunId);
    return audit;
  }
  if (physical_run_active_ || physical_drain_pending_ ||
      physical_start_pending_) {
    addConflict(audit, Conflict::kControllerBusy);
  }

  if (includesAdc(audit.profile)) {
    if (adc_trigger_scheduler_ == nullptr || adc_capture_ == nullptr ||
        adc_packer_ == nullptr) {
      addConflict(audit, Conflict::kAdcComponentsMissing);
    } else {
      const adc_trigger::Snapshot &trigger =
          adc_trigger_scheduler_->snapshot();
      if (!trigger.ready()) {
        addConflict(audit, Conflict::kAdcTriggerUnavailable);
      }
      if (adc_trigger_scheduler_->running()) {
        addConflict(audit, Conflict::kAdcTriggerRunning);
      }
      if (!adc_packer_->readyForStart()) {
        addConflict(audit, Conflict::kAdcPackerBusy);
      }
      audit.adc_capture_status = adc_capture_->inspectStart(epoch);
      audit.adc_inspected = true;
      if (audit.adc_capture_status != adc_capture::StartStatus::kOk) {
        addConflict(audit, Conflict::kAdcCaptureUnavailable);
      }
    }
  }

  if (includesGpio(audit.profile)) {
    if (gpio_capture_ == nullptr || gpio_packer_ == nullptr) {
      addConflict(audit, Conflict::kGpioComponentsMissing);
    } else {
      if (!gpio_packer_->readyForStart()) {
        addConflict(audit, Conflict::kGpioPackerBusy);
      }
      audit.gpio_capture_status = gpio_capture_->inspectStart();
      audit.gpio_inspected = true;
      if (audit.gpio_capture_status != gpio_capture::StartStatus::kOk) {
        addConflict(audit, Conflict::kGpioCaptureUnavailable);
      }
    }
  }
  return audit;
}

TEENSY_DAQ_ACQUISITION_COLD_CODE(".flashmem.acquisition.readiness")
bool Controller::readyForStart(
    const protocol::Configuration &configuration, std::uint32_t epoch) {
  const Audit audit = inspect(configuration, epoch);
  if (audit.adc_inspected &&
      audit.adc_capture_status == adc_capture::StartStatus::kResourceBusy) {
    statistics_.recordAdcResourceConflict();
  }
  if (audit.gpio_inspected &&
      audit.gpio_capture_status == gpio_capture::StartStatus::kResourceBusy) {
    statistics_.recordGpioResourceConflict();
  }
  return audit.ready();
}

TEENSY_DAQ_ACQUISITION_COLD_CODE(".flashmem.acquisition.quiescence")
bool Controller::quiescent() const {
  if (physical_run_active_ || physical_drain_pending_ ||
      physical_start_pending_) {
    return false;
  }
  if (gpio_packer_ != nullptr && !gpio_packer_->readyForStart()) {
    return false;
  }
  if (gpio_capture_ != nullptr && !gpio_capture_->rawSnapshot().quiescent) {
    return false;
  }
  if (adc_trigger_scheduler_ != nullptr &&
      adc_trigger_scheduler_->running()) {
    return false;
  }
  if (adc_packer_ != nullptr && !adc_packer_->readyForStart()) {
    return false;
  }
  return adc_capture_ == nullptr || adc_capture_->rawSnapshot().quiescent;
}

TEENSY_DAQ_ACQUISITION_COLD_CODE(".flashmem.acquisition.start")
bool Controller::start(const protocol::Configuration &configuration,
                       std::uint32_t run_id, std::uint64_t epoch_ticks,
                       Report &report) {
  const Profile profile = profileFor(configuration);
  report.run_id = run_id;
  report.epoch_ticks = epoch_ticks;
  if (!readyForStart(configuration, run_id)) {
    report.internal_error = true;
    report.packet_stop = packet_pipeline_.stopProduction();
    report.packet_production_stopped = true;
    return false;
  }

  const packet::PipelineSnapshot packet = packet_pipeline_.snapshot();
  if (!packet.accepting_frames || packet.run_id != run_id ||
      packet.checksum_algorithm != configuration.data_checksum_algorithm) {
    report.internal_error = true;
    report.packet_stop = packet_pipeline_.stopProduction();
    report.packet_production_stopped = true;
    return false;
  }

  // This reservation is committed before the first packer/cache/register
  // mutation. It keeps the one run ID and one 8 MHz epoch indivisible across
  // both source paths, including every rollback branch.
  physical_stream_mask_ = configuration.stream_mask;
  physical_run_id_ = run_id;
  physical_epoch_ticks_ = epoch_ticks;
  physical_start_pending_ = true;

  if (includesAdc(profile)) {
    report.adc_packer_start_status = adc_packer_->startRun(
        run_id, configuration.data_checksum_algorithm, packet_pipeline_,
        epoch_ticks);
    report.adc_packer_started =
        report.adc_packer_start_status == adc_packer::OperationStatus::kOk;
    if (!report.adc_packer_started) {
      statistics_.recordAdcStartError();
      rollbackStart(profile, report);
      return false;
    }
  }

  if (includesGpio(profile)) {
    report.gpio_packer_start_status = gpio_packer_->startRun(
        run_id, configuration.data_checksum_algorithm, packet_pipeline_,
        epoch_ticks);
    report.gpio_packer_started =
        report.gpio_packer_start_status == gpio_packer::OperationStatus::kOk;
    if (!report.gpio_packer_started) {
      statistics_.recordGpioStartError();
      rollbackStart(profile, report);
      return false;
    }
  }

  if (includesAdc(profile)) {
    report.adc_capture_start_status = adc_capture_->prepare(run_id);
    report.adc_capture_prepared =
        report.adc_capture_start_status == adc_capture::StartStatus::kOk;
    if (!report.adc_capture_prepared) {
      if (report.adc_capture_start_status ==
          adc_capture::StartStatus::kResourceBusy) {
        statistics_.recordAdcResourceConflict();
      } else {
        statistics_.recordAdcStartError();
      }
      rollbackStart(profile, report);
      return false;
    }
  }

  if (includesGpio(profile)) {
    report.gpio_capture_start_status =
        profile == Profile::kCombined ? gpio_capture_->prepare()
                                      : gpio_capture_->start();
    report.gpio_capture_prepared =
        report.gpio_capture_start_status == gpio_capture::StartStatus::kOk;
    report.gpio_capture_started =
        profile == Profile::kGpio && report.gpio_capture_prepared;
    if (!report.gpio_capture_prepared) {
      if (report.gpio_capture_start_status ==
          gpio_capture::StartStatus::kResourceBusy) {
        statistics_.recordGpioResourceConflict();
      } else {
        statistics_.recordGpioStartError();
      }
      rollbackStart(profile, report);
      return false;
    }
  }

  // The ADC scheduler is the sole common-clock owner in combined mode. GPIO
  // DMA is already request-enabled, but PIT0 remains stopped until arm().
  if (includesAdc(profile)) {
    report.adc_trigger_armed = adc_trigger_scheduler_->arm();
    if (!report.adc_trigger_armed) {
      statistics_.recordAdcStartError();
      rollbackStart(profile, report);
      return false;
    }
    if (profile == Profile::kCombined) {
      report.gpio_capture_started = true;
    }
  }

  physical_start_pending_ = false;
  physical_run_active_ = true;
  physical_drain_pending_ = false;
  return true;
}

TEENSY_DAQ_ACQUISITION_COLD_CODE(".flashmem.acquisition.rollback")
void Controller::rollbackStart(Profile profile, Report &report) {
  // arm() already invokes target cleanup when its final readback fails. If it
  // did commit, stop the one common source before either DMA path is touched.
  if (includesAdc(profile) && adc_trigger_scheduler_->running()) {
    report.adc_trigger_stopped = adc_trigger_scheduler_->stop();
  }
  if (includesGpio(profile) && report.gpio_capture_prepared) {
    report.gpio_capture_stop =
        profile == Profile::kCombined ? gpio_capture_->stopAfterTriggers()
                                      : gpio_capture_->stop();
    report.gpio_capture_stopped = true;
  }
  if (includesAdc(profile) && report.adc_capture_prepared) {
    report.adc_capture_stop = adc_capture_->stopAfterTriggers();
    report.adc_capture_stopped = true;
  }
  if (report.gpio_packer_started) {
    report.gpio_packer_stop = gpio_packer_->stopProduction();
    report.gpio_packer_stopped = true;
  }
  if (report.adc_packer_started) {
    report.adc_packer_stop = adc_packer_->stopProduction();
    report.adc_packer_stopped = true;
  }
  report.packet_stop = packet_pipeline_.stopProduction();
  report.packet_production_stopped = true;
  report.internal_error = true;
  clearRunState();
}

TEENSY_DAQ_ACQUISITION_COLD_CODE(".flashmem.acquisition.adc_stop")
bool Controller::stopAdcPath(Report &report) {
  bool stop_error = false;
  report.adc_capture_boundary_stopped =
      adc_capture_->stopAtBoundaryBeforeTriggers();
  if (!report.adc_capture_boundary_stopped) {
    stop_error = true;
    report.internal_error = true;
  }

  report.adc_trigger_stopped = adc_trigger_scheduler_->stop();
  if (!report.adc_trigger_stopped) {
    statistics_.recordAdcStopError();
    report.internal_error = true;
    return false;
  }

  report.adc_capture_stop = adc_capture_->stopAfterTriggers();
  report.adc_capture_stopped = true;
  if (report.adc_capture_stop.status != adc_capture::OperationStatus::kOk &&
      report.adc_capture_stop.status !=
          adc_capture::OperationStatus::kNotRunning) {
    stop_error = true;
    report.internal_error = true;
  }
  if (stop_error) {
    statistics_.recordAdcStopError();
  }
  return true;
}

TEENSY_DAQ_ACQUISITION_COLD_CODE(".flashmem.acquisition.combined_stop")
bool Controller::stopCombinedPaths(Report &report) {
  // PIT0 is the source for GPIO eDMA and chained PIT1. Disable that source and
  // both ADC_ETC queues before quiescing any of the three DMA channels.
  report.adc_trigger_stopped = adc_trigger_scheduler_->stop();
  if (!report.adc_trigger_stopped) {
    statistics_.recordAdcStopError();
    report.internal_error = true;
    return false;
  }

  report.gpio_capture_stop = gpio_capture_->stopAfterTriggers();
  report.gpio_capture_stopped = true;
  if (report.gpio_capture_stop.status != gpio_capture::OperationStatus::kOk &&
      report.gpio_capture_stop.status !=
          gpio_capture::OperationStatus::kNotRunning) {
    statistics_.recordGpioStopError();
    report.internal_error = true;
  }

  report.adc_capture_stop = adc_capture_->stopAfterTriggers();
  report.adc_capture_stopped = true;
  if (report.adc_capture_stop.status != adc_capture::OperationStatus::kOk &&
      report.adc_capture_stop.status !=
          adc_capture::OperationStatus::kNotRunning) {
    statistics_.recordAdcStopError();
    report.internal_error = true;
  }
  return true;
}

TEENSY_DAQ_ACQUISITION_COLD_CODE(".flashmem.acquisition.stop")
bool Controller::stop(Report &report) {
  report.run_id = physical_run_id_;
  report.epoch_ticks = physical_epoch_ticks_;
  if (!physical_run_active_) {
    report.physical_drain_pending = physical_drain_pending_;
    return true;
  }
  const std::uint8_t adc = streamBit(protocol_v1::StreamMask::kAdc);
  const std::uint8_t gpio = streamBit(protocol_v1::StreamMask::kGpio);
  if (physical_stream_mask_ == static_cast<std::uint8_t>(adc | gpio)) {
    if (!stopCombinedPaths(report)) {
      physical_drain_pending_ = true;
      report.physical_drain_pending = true;
      return false;
    }
  } else if (physical_stream_mask_ == adc) {
    if (!stopAdcPath(report)) {
      physical_drain_pending_ = true;
      report.physical_drain_pending = true;
      return false;
    }
  } else if (physical_stream_mask_ == gpio) {
    report.gpio_capture_stop = gpio_capture_->stop();
    report.gpio_capture_stopped = true;
    if (report.gpio_capture_stop.status != gpio_capture::OperationStatus::kOk &&
        report.gpio_capture_stop.status !=
            gpio_capture::OperationStatus::kNotRunning) {
      statistics_.recordGpioStopError();
      report.internal_error = true;
    }
  } else {
    report.internal_error = true;
    return false;
  }
  physical_run_active_ = false;
  physical_drain_pending_ = true;
  report.physical_drain_pending = true;
  return true;
}

TEENSY_DAQ_ACQUISITION_COLD_CODE(".flashmem.acquisition.adc_service")
void Controller::serviceAdcPath(Report &report, bool draining) {
  (void)adc_capture_->serviceOwnership();
  const std::size_t buffer_limit =
      draining ? board::kAdcDmaRingDepth : board::kAdcFramesPerLoop;
  report.adc_packer = adc_packer_->service(packet_pipeline_, buffer_limit);
}

TEENSY_DAQ_ACQUISITION_COLD_CODE(".flashmem.acquisition.gpio_service")
void Controller::serviceGpioPath(Report &report, bool draining) {
  const std::size_t raw_limit =
      draining ? board::kGpioRawDmaRingDepth
               : board::kGpioRawBuffersPerLoop;
  const std::size_t frame_limit =
      draining ? board::kGpioPackedRingDepth
               : board::kGpioPackedFramesPerLoop;
  report.gpio_packer = gpio_packer_->service(
      packet_pipeline_, raw_limit, frame_limit);
}

TEENSY_DAQ_ACQUISITION_COLD_CODE(".flashmem.acquisition.adc_drain")
bool Controller::adcPathDrained(Report &report) {
  const adc_capture::Snapshot capture = adc_capture_->rawSnapshot();
  adc_packer::Snapshot packer = adc_packer_->snapshot(packet_pipeline_);
  if (capture.ready_depth == 0U && capture.reading_depth == 0U &&
      capture.discard_depth == 0U && packer.running) {
    report.adc_packer_stop = adc_packer_->stopProduction();
    report.adc_packer_stopped = true;
    packer = adc_packer_->snapshot(packet_pipeline_);
  }
  return capture.quiescent && packer.quiescent;
}

TEENSY_DAQ_ACQUISITION_COLD_CODE(".flashmem.acquisition.gpio_drain")
bool Controller::gpioPathDrained(Report &report) {
  const gpio_capture::Snapshot capture = gpio_capture_->rawSnapshot();
  gpio_packer::Snapshot packer = gpio_packer_->snapshot(packet_pipeline_);
  if (capture.ready_depth == 0U && capture.packing_depth == 0U &&
      packer.running) {
    report.gpio_packer_stop = gpio_packer_->stopProduction();
    report.gpio_packer_stopped = true;
    packer = gpio_packer_->snapshot(packet_pipeline_);
  }
  if (!packer.running && !packer.quiescent) {
    report.gpio_packer = gpio_packer_->service(
        packet_pipeline_, 0U, board::kGpioPackedRingDepth);
    packer = gpio_packer_->snapshot(packet_pipeline_);
  }
  return capture.quiescent && packer.quiescent;
}

TEENSY_DAQ_ACQUISITION_COLD_CODE(".flashmem.acquisition.fault_check")
bool Controller::activePathFaulted() const {
  const std::uint8_t adc = streamBit(protocol_v1::StreamMask::kAdc);
  const std::uint8_t gpio = streamBit(protocol_v1::StreamMask::kGpio);
  return ((physical_stream_mask_ & adc) != 0U &&
          adc_capture_ != nullptr && adc_capture_->rawSnapshot().faulted) ||
         ((physical_stream_mask_ & gpio) != 0U &&
          gpio_capture_ != nullptr && gpio_capture_->rawSnapshot().faulted);
}

TEENSY_DAQ_ACQUISITION_COLD_CODE(".flashmem.acquisition.clear")
void Controller::clearRunState() {
  physical_stream_mask_ = 0U;
  physical_run_id_ = 0U;
  physical_epoch_ticks_ = 0U;
  physical_run_active_ = false;
  physical_drain_pending_ = false;
  physical_start_pending_ = false;
}

TEENSY_DAQ_ACQUISITION_COLD_CODE(".flashmem.acquisition.service")
void Controller::service(Report &report) {
  report.run_id = physical_run_id_;
  report.epoch_ticks = physical_epoch_ticks_;
  if (!physical_run_active_ && !physical_drain_pending_) {
    report.physical_drain_pending = false;
    return;
  }

  if (physical_run_active_ && activePathFaulted()) {
    report.physical_fault_detected = true;
    report.internal_error = true;
    if (!stop(report)) {
      report.physical_drain_pending = true;
      return;
    }
  } else if (physical_drain_pending_ && physical_run_active_) {
    if (!stop(report)) {
      report.physical_drain_pending = true;
      return;
    }
  }

  const std::uint8_t adc = streamBit(protocol_v1::StreamMask::kAdc);
  const std::uint8_t gpio = streamBit(protocol_v1::StreamMask::kGpio);
  const bool includes_adc = (physical_stream_mask_ & adc) != 0U;
  const bool includes_gpio = (physical_stream_mask_ & gpio) != 0U;
  if ((!includes_adc && !includes_gpio) ||
      (includes_adc && (adc_capture_ == nullptr || adc_packer_ == nullptr)) ||
      (includes_gpio &&
       (gpio_capture_ == nullptr || gpio_packer_ == nullptr))) {
    report.internal_error = true;
    report.physical_drain_pending = physical_drain_pending_;
    return;
  }

  if (includes_adc) {
    serviceAdcPath(report, physical_drain_pending_);
  }
  if (includes_gpio) {
    serviceGpioPath(report, physical_drain_pending_);
  }

  if (physical_run_active_ &&
      ((includes_adc &&
        (report.adc_packer.source_error || report.adc_packer.pipeline_error)) ||
       (includes_gpio &&
        (report.gpio_packer.source_error ||
         report.gpio_packer.pipeline_error)))) {
    report.physical_fault_detected = true;
    report.internal_error = true;
    if (!stop(report)) {
      report.physical_drain_pending = true;
      return;
    }
  }

  if (!physical_drain_pending_) {
    report.physical_drain_pending = false;
    return;
  }

  const bool adc_drained = !includes_adc || adcPathDrained(report);
  const bool gpio_drained = !includes_gpio || gpioPathDrained(report);
  if (adc_drained && gpio_drained) {
    report.packet_stop = packet_pipeline_.stopProduction();
    report.packet_production_stopped = true;
    clearRunState();
  }
  report.physical_drain_pending = physical_drain_pending_;
}

TEENSY_DAQ_ACQUISITION_COLD_CODE(".flashmem.acquisition.statistics")
void Controller::publishStatistics(std::uint32_t run_id) {
  if (gpio_packer_ != nullptr) {
    const gpio_packer::Snapshot packed =
        gpio_packer_->snapshot(packet_pipeline_);
    if (packed.run_id != 0U && packed.run_id == run_id) {
      if (gpio_capture_ != nullptr) {
        const gpio_capture::Snapshot capture =
            gpio_capture_->rawSnapshot();
        stats::GpioRawCaptureProgress raw = capture.progress;
        raw.ready_depth = capture.ready_depth;
        raw.invariant_errors = capture.invariant_errors;
        raw.resource_conflicts = capture.resource_conflicts;
        raw.start_errors = capture.start_errors;
        raw.stop_errors = capture.stop_errors;
        raw.stale_dma_completions = capture.stale_dma_completions;
        statistics_.publishGpioRawCapture(raw);
      }
      statistics_.publishGpioPacker(packed.progress);
    }
  }

  if (adc_packer_ == nullptr) {
    return;
  }
  const adc_packer::Snapshot packed =
      adc_packer_->snapshot(packet_pipeline_);
  if (packed.run_id == 0U || packed.run_id != run_id) {
    return;
  }
  if (adc_capture_ != nullptr) {
    const adc_capture::Snapshot capture = adc_capture_->rawSnapshot();
    const adc_capture::Progress &source = capture.progress;
    stats::AdcCaptureProgress raw{};
    raw.adc0_major_loops = source.channel_major_loops[0];
    raw.adc1_major_loops = source.channel_major_loops[1];
    raw.adc0_results = source.channel_results[0];
    raw.adc1_results = source.channel_results[1];
    raw.paired_major_loops = source.paired_major_loops;
    raw.buffers_completed = source.buffers_completed;
    raw.buffers_acquired = source.buffers_acquired;
    raw.buffers_released = source.buffers_released;
    raw.pairs_captured = source.pairs_captured;
    raw.pairs_delivered = source.pairs_delivered;
    raw.pairs_lost = source.pairs_lost;
    raw.stop_discarded_pairs = source.stop_discarded_pairs;
    raw.incomplete_conversions = source.incomplete_conversions;
    raw.overwritten_conversions = source.overwritten_conversions;
    raw.ring_overruns = source.ring_overruns;
    raw.incomplete_buffers = source.incomplete_buffers;
    raw.ready_depth = capture.ready_depth;
    raw.ready_high_water = source.ready_high_water;
    raw.adc_etc_error_events = source.adc_etc_error_events;
    raw.adc_etc_error_flags = source.adc_etc_error_flags;
    raw.dma_error_events = source.dma_error_events;
    raw.completion_mismatches = source.completion_mismatches;
    raw.destination_mismatches = source.destination_mismatches;
    raw.schedule_exhaustions = source.schedule_exhaustions;
    raw.invariant_errors = source.invariant_errors;
    raw.stale_completions = source.stale_completions;
    raw.resource_conflicts = capture.resource_conflicts;
    raw.start_errors = capture.start_errors;
    raw.stop_errors = capture.stop_errors;
    raw.stale_interrupts = capture.stale_interrupts;
    statistics_.publishAdcCapture(raw);
  }
  statistics_.publishAdcPacker(packed.progress);
}

#undef TEENSY_DAQ_ACQUISITION_COLD_CODE

}  // namespace teensy_daq::acquisition
