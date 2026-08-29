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
  if (physical_run_active_ || physical_drain_pending_) {
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
  if (physical_run_active_ || physical_drain_pending_) {
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
  // Combined execution remains fail-closed until the next phase task adds one
  // shared schedule arm. Its complete read-only audit is already available.
  if ((profile != Profile::kAdc && profile != Profile::kGpio) ||
      !readyForStart(configuration, run_id)) {
    report.internal_error = true;
    report.packet_stop = packet_pipeline_.stopProduction();
    report.packet_production_stopped = true;
    return false;
  }

  if (profile == Profile::kAdc) {
    report.adc_packer_start_status = adc_packer_->startRun(
        run_id, configuration.data_checksum_algorithm, packet_pipeline_,
        epoch_ticks);
    report.adc_packer_started =
        report.adc_packer_start_status == adc_packer::OperationStatus::kOk;
    if (!report.adc_packer_started) {
      statistics_.recordAdcStartError();
      report.packet_stop = packet_pipeline_.stopProduction();
      report.packet_production_stopped = true;
      report.internal_error = true;
      return false;
    }

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
      report.adc_packer_stop = adc_packer_->stopProduction();
      report.adc_packer_stopped = true;
      report.packet_stop = packet_pipeline_.stopProduction();
      report.packet_production_stopped = true;
      report.internal_error = true;
      return false;
    }

    report.adc_trigger_armed = adc_trigger_scheduler_->arm();
    if (!report.adc_trigger_armed) {
      (void)adc_trigger_scheduler_->stop();
      report.adc_capture_stop = adc_capture_->stopAfterTriggers();
      report.adc_capture_stopped = true;
      report.adc_packer_stop = adc_packer_->stopProduction();
      report.adc_packer_stopped = true;
      report.packet_stop = packet_pipeline_.stopProduction();
      report.packet_production_stopped = true;
      statistics_.recordAdcStartError();
      report.internal_error = true;
      return false;
    }

    physical_stream_mask_ = streamBit(protocol_v1::StreamMask::kAdc);
    physical_run_active_ = true;
    physical_drain_pending_ = false;
    return true;
  }

  report.gpio_packer_start_status = gpio_packer_->startRun(
      run_id, configuration.data_checksum_algorithm, packet_pipeline_,
      epoch_ticks);
  report.gpio_packer_started =
      report.gpio_packer_start_status == gpio_packer::OperationStatus::kOk;
  if (!report.gpio_packer_started) {
    statistics_.recordGpioStartError();
    report.packet_stop = packet_pipeline_.stopProduction();
    report.packet_production_stopped = true;
    report.internal_error = true;
    return false;
  }

  report.gpio_capture_start_status = gpio_capture_->start();
  report.gpio_capture_started =
      report.gpio_capture_start_status == gpio_capture::StartStatus::kOk;
  if (!report.gpio_capture_started) {
    if (report.gpio_capture_start_status ==
        gpio_capture::StartStatus::kResourceBusy) {
      statistics_.recordGpioResourceConflict();
    } else {
      statistics_.recordGpioStartError();
    }
    report.gpio_packer_stop = gpio_packer_->stopProduction();
    report.gpio_packer_stopped = true;
    report.packet_stop = packet_pipeline_.stopProduction();
    report.packet_production_stopped = true;
    report.internal_error = true;
    return false;
  }
  physical_stream_mask_ = streamBit(protocol_v1::StreamMask::kGpio);
  physical_run_active_ = true;
  physical_drain_pending_ = false;
  return true;
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

TEENSY_DAQ_ACQUISITION_COLD_CODE(".flashmem.acquisition.stop")
bool Controller::stop(Report &report) {
  if (!physical_run_active_) {
    report.physical_drain_pending = physical_drain_pending_;
    return true;
  }
  if (physical_stream_mask_ == streamBit(protocol_v1::StreamMask::kAdc)) {
    if (!stopAdcPath(report)) {
      physical_drain_pending_ = true;
      report.physical_drain_pending = true;
      return false;
    }
  } else if (physical_stream_mask_ ==
             streamBit(protocol_v1::StreamMask::kGpio)) {
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

TEENSY_DAQ_ACQUISITION_COLD_CODE(".flashmem.acquisition.service")
void Controller::service(Report &report) {
  if (!physical_run_active_ && !physical_drain_pending_) {
    report.physical_drain_pending = false;
    return;
  }

  if (physical_stream_mask_ == streamBit(protocol_v1::StreamMask::kAdc)) {
    if (physical_drain_pending_ && physical_run_active_) {
      if (!stopAdcPath(report)) {
        report.physical_drain_pending = true;
        return;
      }
      physical_run_active_ = false;
    }

    (void)adc_capture_->serviceOwnership();
    const std::size_t buffer_limit =
        physical_drain_pending_ ? board::kAdcDmaRingDepth
                                : board::kAdcFramesPerLoop;
    report.adc_packer =
        adc_packer_->service(packet_pipeline_, buffer_limit);
    if (!physical_drain_pending_) {
      return;
    }

    const adc_capture::Snapshot capture = adc_capture_->rawSnapshot();
    adc_packer::Snapshot packer = adc_packer_->snapshot(packet_pipeline_);
    if (capture.ready_depth == 0U && capture.reading_depth == 0U &&
        capture.discard_depth == 0U && packer.running) {
      report.adc_packer_stop = adc_packer_->stopProduction();
      report.adc_packer_stopped = true;
      packer = adc_packer_->snapshot(packet_pipeline_);
    }
    if (capture.quiescent && packer.quiescent) {
      report.packet_stop = packet_pipeline_.stopProduction();
      report.packet_production_stopped = true;
      physical_drain_pending_ = false;
      physical_stream_mask_ = 0U;
    }
    report.physical_drain_pending = physical_drain_pending_;
    return;
  }

  if (physical_stream_mask_ != streamBit(protocol_v1::StreamMask::kGpio) ||
      gpio_capture_ == nullptr || gpio_packer_ == nullptr) {
    report.internal_error = true;
    report.physical_drain_pending = physical_drain_pending_;
    return;
  }

  const std::size_t raw_limit =
      physical_drain_pending_ ? board::kGpioRawDmaRingDepth
                              : board::kGpioRawBuffersPerLoop;
  report.gpio_packer = gpio_packer_->service(
      packet_pipeline_, raw_limit, board::kGpioPackedFramesPerLoop);
  if (!physical_drain_pending_) {
    return;
  }

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
  }
  if (gpio_packer_->quiescent()) {
    report.packet_stop = packet_pipeline_.stopProduction();
    report.packet_production_stopped = true;
    physical_drain_pending_ = false;
    physical_stream_mask_ = 0U;
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
