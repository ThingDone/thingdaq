#include "firmware_runtime.h"

#if defined(__IMXRT1062__)
#define TEENSY_DAQ_RUNTIME_COLD_CODE(section_name) \
  __attribute__((section(section_name), noinline, noipa, used))
#else
#define TEENSY_DAQ_RUNTIME_COLD_CODE(section_name)
#endif

namespace teensy_daq::runtime {

TEENSY_DAQ_RUNTIME_COLD_CODE(".flashmem.runtime.begin")
bool FirmwareRuntime::begin(std::uint32_t hardware_serial) {
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
  return control_.completeBoot(hardware_serial, metadata);
}

LoopReport FirmwareRuntime::service() {
  LoopReport report{};
  report.receive = transport_.serviceReceive();
  publishPacketStatistics();
  const std::uint64_t now_ticks = clock_.nowTicks();

  protocol::ParsedCommand command{};
  protocol::ControlFrame response{};
  bool response_ready = false;
  if (transport_.takeCommand(command)) {
    report.command_dispatched = true;
    control::DispatchReadiness readiness{};
    benchmark::RunResult benchmark_result{};
    gpio_clock::RunResult gpio_clock_result{};
    gpio_diagnostic::RunResult gpio_capture_result{};
    protocol::GpioCaptureDiagnosticResponse gpio_capture_response{};
    if (command.request.kind == protocol_v1::CommandKind::kConfigure) {
      readiness.configuration_ready = dataPathQuiescent();
      if (readiness.configuration_ready &&
          physicalConfiguration(command.request.configuration)) {
        if (gpio_capture_ == nullptr || gpio_packer_ == nullptr) {
          readiness.configuration_ready = false;
        } else {
          const gpio_capture::StartStatus status =
              gpio_capture_->inspectStart();
          readiness.configuration_ready =
              status == gpio_capture::StartStatus::kOk &&
              gpio_packer_->readyForStart();
          if (status == gpio_capture::StartStatus::kResourceBusy) {
            control_.statistics().recordGpioResourceConflict();
          }
        }
      }
    } else if (command.request.kind == protocol_v1::CommandKind::kStart) {
      readiness.start_ready = dataPathQuiescent();
      if (readiness.start_ready &&
          physicalConfiguration(control_.appliedConfiguration())) {
        if (gpio_capture_ == nullptr || gpio_packer_ == nullptr) {
          readiness.start_ready = false;
        } else {
          const gpio_capture::StartStatus status =
              gpio_capture_->inspectStart();
          readiness.start_ready =
              status == gpio_capture::StartStatus::kOk &&
              gpio_packer_->readyForStart();
          if (status == gpio_capture::StartStatus::kResourceBusy) {
            control_.statistics().recordGpioResourceConflict();
          }
        }
      }
    } else if (command.request.kind ==
                   protocol_v1::CommandKind::kChecksumBenchmark &&
               control_.state() == protocol_v1::DeviceState::kIdle &&
               checksum_benchmark_ != nullptr) {
      benchmark_result =
          checksum_benchmark_->run(command.request.checksum_benchmark);
      if (benchmark_result.ok()) {
        readiness.checksum_benchmark_response = &benchmark_result.response;
        readiness.checksum_benchmark_error = protocol_v1::ErrorCode::kOk;
      } else if (benchmark_result.status ==
                 benchmark::RunStatus::kInvalidRequest) {
        readiness.checksum_benchmark_error =
            protocol_v1::ErrorCode::kInvalidPayload;
      } else {
        readiness.checksum_benchmark_error =
            protocol_v1::ErrorCode::kInternalError;
      }
    } else if (command.request.kind ==
                   protocol_v1::CommandKind::kGpioClockDiagnostic &&
               control_.state() == protocol_v1::DeviceState::kIdle &&
               gpio_clock_diagnostic_ != nullptr && dataPathQuiescent()) {
      gpio_clock_result = gpio_clock_diagnostic_->run(
          command.request.gpio_clock_diagnostic);
      if (gpio_clock_result.ok()) {
        readiness.gpio_clock_response = &gpio_clock_result.response;
        readiness.gpio_clock_error = protocol_v1::ErrorCode::kOk;
      } else if (gpio_clock_result.status ==
                 gpio_clock::RunStatus::kInvalidRequest) {
        readiness.gpio_clock_error = protocol_v1::ErrorCode::kInvalidPayload;
      } else {
        readiness.gpio_clock_error = protocol_v1::ErrorCode::kInternalError;
      }
    } else if (command.request.kind ==
                   protocol_v1::CommandKind::kGpioClockDiagnostic &&
               control_.state() == protocol_v1::DeviceState::kIdle &&
               !dataPathQuiescent()) {
      readiness.gpio_clock_error = protocol_v1::ErrorCode::kBusy;
    } else if (command.request.kind ==
                   protocol_v1::CommandKind::kGpioCaptureDiagnostic &&
               control_.state() == protocol_v1::DeviceState::kIdle &&
               gpio_capture_diagnostic_ != nullptr && dataPathQuiescent()) {
      gpio_capture_result = gpio_capture_diagnostic_->run();
      if (gpio_capture_result.ok()) {
        gpio_capture_response = gpioDiagnosticResponse(
            *gpio_capture_diagnostic_, gpio_capture_result.snapshot);
        readiness.gpio_capture_response = &gpio_capture_response;
        readiness.gpio_capture_error = protocol_v1::ErrorCode::kOk;
      } else {
        readiness.gpio_capture_error =
            protocol_v1::ErrorCode::kInternalError;
      }
    } else if (command.request.kind ==
                   protocol_v1::CommandKind::kGpioCaptureDiagnostic &&
               control_.state() == protocol_v1::DeviceState::kIdle &&
               !dataPathQuiescent()) {
      readiness.gpio_capture_error = protocol_v1::ErrorCode::kBusy;
    }
    const control::DispatchResult dispatched =
        control_.dispatch(command.request, response, readiness);
    if (dispatched.responseReady()) {
      response_ready = true;
    } else {
      recoverResponsePath(command.request, response, false, report);
    }
  }

  // Arm or stop the data path before admitting the corresponding successful
  // response. A START can therefore never be acknowledged until all resources
  // have accepted the new epoch.
  applyPendingEvents(control_.takePendingEvents(), now_ticks, report);
  if (report.internal_error && response_ready) {
    recoverResponsePath(command.request, response, false, report);
    response_ready = false;
  }
  if (response_ready) {
    report.response_queued = transport_.queueResponse(response);
    if (!report.response_queued) {
      recoverResponsePath(command.request, response, true, report);
    }
  }
  // Response-path recovery can create one STOP event after the first event
  // pass. Consume it now so a failed START cannot generate data for one loop.
  applyPendingEvents(control_.takePendingEvents(), now_ticks, report);

  // Pattern construction, framing/checksum work, queue ownership, and USB all
  // stay in this bounded cooperative path. Newly due work is promoted and
  // offered to CDC during the same visit. The production clock is polled; no
  // pacing ISR is installed.
  report.synthetic = synthetic_source_.service(now_ticks, packet_pipeline_);
  servicePhysicalPath(report);
  report.packet_promotion = packet_pipeline_.serviceReadyFrames();
  report.transmit = transport_.serviceTransmit();
  publishPacketStatistics();
  return report;
}

TEENSY_DAQ_RUNTIME_COLD_CODE(".flashmem.runtime.pending_events")
void FirmwareRuntime::applyPendingEvents(
    const control::PendingEvents &events, std::uint64_t now_ticks,
    LoopReport &report) {
  if (events.mask == 0U) {
    return;
  }
  report.events.mask = static_cast<std::uint8_t>(report.events.mask | events.mask);
  report.events.run_id = events.run_id;
  report.events.stats_generation = events.stats_generation;

  if (events.has(control::Event::kStop)) {
    if (physical_run_active_) {
      report.gpio_capture_stop = gpio_capture_->stop();
      report.gpio_capture_stopped = true;
      if (report.gpio_capture_stop.status !=
              gpio_capture::OperationStatus::kOk &&
          report.gpio_capture_stop.status !=
              gpio_capture::OperationStatus::kNotRunning) {
        control_.statistics().recordGpioStopError();
        report.internal_error = true;
      }
      physical_run_active_ = false;
      physical_drain_pending_ = true;
    } else if (!physical_drain_pending_) {
      synthetic_source_.stop();
      report.synthetic_production_stopped = true;
      report.packet_stop = packet_pipeline_.stopProduction();
      report.packet_production_stopped = true;
    }
  }
  if (events.has(control::Event::kStartEpoch)) {
    report.packet_start_status =
        packet_pipeline_.startRun(
            events.run_id,
            control_.appliedConfiguration().data_checksum_algorithm);
    report.packet_run_started =
        report.packet_start_status == packet::OperationStatus::kOk;
    if (!report.packet_run_started) {
      report.internal_error = true;
      return;
    }
    if (physicalConfiguration(control_.appliedConfiguration())) {
      report.gpio_packer_start_status = gpio_packer_->startRun(
          events.run_id,
          control_.appliedConfiguration().data_checksum_algorithm,
          packet_pipeline_, now_ticks);
      report.gpio_packer_started =
          report.gpio_packer_start_status ==
          gpio_packer::OperationStatus::kOk;
      if (!report.gpio_packer_started) {
        control_.statistics().recordGpioStartError();
        report.packet_stop = packet_pipeline_.stopProduction();
        report.packet_production_stopped = true;
        report.internal_error = true;
        return;
      }
      report.gpio_capture_start_status = gpio_capture_->start();
      report.gpio_capture_started =
          report.gpio_capture_start_status == gpio_capture::StartStatus::kOk;
      if (!report.gpio_capture_started) {
        if (report.gpio_capture_start_status ==
            gpio_capture::StartStatus::kResourceBusy) {
          control_.statistics().recordGpioResourceConflict();
        } else {
          control_.statistics().recordGpioStartError();
        }
        report.gpio_packer_stop = gpio_packer_->stopProduction();
        report.gpio_packer_stopped = true;
        report.packet_stop = packet_pipeline_.stopProduction();
        report.packet_production_stopped = true;
        report.internal_error = true;
        return;
      }
      physical_run_active_ = true;
      physical_drain_pending_ = false;
      packet_stats_generation_ = events.stats_generation;
      return;
    }

    report.synthetic_start_status = synthetic_source_.startRun(
        events.run_id, control_.appliedConfiguration(), now_ticks,
        packet_pipeline_);
    report.synthetic_run_started =
        report.synthetic_start_status == synthetic::OperationStatus::kOk;
    if (report.synthetic_run_started) {
      packet_stats_generation_ = events.stats_generation;
      return;
    }
    report.packet_stop = packet_pipeline_.stopProduction();
    report.packet_production_stopped = true;
    report.internal_error = true;
  }
}

void FirmwareRuntime::publishPacketStatistics() {
  if (packet_stats_generation_ == 0U ||
      packet_stats_generation_ != control_.statistics().generation()) {
    return;
  }

  const packet::PipelineSnapshot pipeline = packet_pipeline_.snapshot();
  stats::DataPathProgress progress{};
  const auto copy = [](const packet::SourceCounters &source,
                       stats::StreamProgress &destination) {
    destination.frames_generated = source.frames_produced;
    destination.items_generated = source.items_produced;
    destination.frames_framed = source.frames_framed;
    destination.items_framed = source.items_framed;
    destination.frames_emitted = source.frames_emitted;
    destination.items_emitted = source.items_emitted;
    destination.frames_transmitted = source.frames_transmitted;
    destination.items_transmitted = source.items_transmitted;
    destination.frames_dropped = source.frames_dropped;
    destination.items_dropped = source.items_dropped;
  };
  copy(pipeline.sources[packet::streamIndex(packet::Stream::kAdc)],
       progress.adc);
  copy(pipeline.sources[packet::streamIndex(packet::Stream::kGpio)],
       progress.gpio);
  control_.statistics().publishDataPath(progress);
  stats::PacketQueueProgress queues{};
  queues.ready_depth = pipeline.ready_queue_depth;
  queues.transmit_depth = pipeline.transmit_queue_depth;
  queues.owned_high_water = pipeline.buffers_owned_high_water;
  control_.statistics().publishPacketQueues(queues);
  if (gpio_capture_ != nullptr) {
    const gpio_capture::Snapshot capture = gpio_capture_->rawSnapshot();
    stats::GpioRawCaptureProgress raw = capture.progress;
    raw.ready_depth = capture.ready_depth;
    raw.invariant_errors = capture.invariant_errors;
    raw.resource_conflicts = capture.resource_conflicts;
    raw.start_errors = capture.start_errors;
    raw.stop_errors = capture.stop_errors;
    raw.stale_dma_completions = capture.stale_dma_completions;
    control_.statistics().publishGpioRawCapture(raw);
  }
  if (gpio_packer_ != nullptr) {
    control_.statistics().publishGpioPacker(
        gpio_packer_->snapshot(packet_pipeline_).progress);
  }
}

TEENSY_DAQ_RUNTIME_COLD_CODE(".flashmem.runtime.quiescence")
bool FirmwareRuntime::dataPathQuiescent() const {
  if (!packet_pipeline_.quiescent() || synthetic_source_.running() ||
      physical_run_active_ || physical_drain_pending_) {
    return false;
  }
  if (gpio_packer_ != nullptr && !gpio_packer_->readyForStart()) {
    return false;
  }
  return gpio_capture_ == nullptr || gpio_capture_->rawSnapshot().quiescent;
}

TEENSY_DAQ_RUNTIME_COLD_CODE(".flashmem.runtime.physical_configuration")
bool FirmwareRuntime::physicalConfiguration(
    const protocol::Configuration &configuration) const {
  return configuration.source == protocol_v1::Source::kHardware &&
         configuration.stream_mask ==
             static_cast<std::uint8_t>(protocol_v1::StreamMask::kGpio);
}

void FirmwareRuntime::servicePhysicalPath(LoopReport &report) {
  if (gpio_capture_ == nullptr || gpio_packer_ == nullptr ||
      (!physical_run_active_ && !physical_drain_pending_)) {
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
  }
  report.physical_drain_pending = physical_drain_pending_;
}

TEENSY_DAQ_RUNTIME_COLD_CODE(".flashmem.runtime.gpio_diagnostic_response")
protocol::GpioCaptureDiagnosticResponse
FirmwareRuntime::gpioDiagnosticResponse(
    const gpio_diagnostic::Runner &runner,
    const gpio_diagnostic::Snapshot &snapshot) {
  const gpio_diagnostic::FixtureDeclaration declaration =
      runner.declaration();
  const gpio_diagnostic::Plan plan = runner.plan();
  protocol::GpioCaptureDiagnosticResponse response{};
  response.mode = static_cast<protocol_v1::GpioCaptureDiagnosticMode>(
      snapshot.mode);
  response.metadata_kind =
      static_cast<std::uint8_t>(declaration.metadata_kind);
  response.drive_safety = static_cast<std::uint8_t>(declaration.drive_safety);
  response.stimulus_kind =
      static_cast<std::uint8_t>(declaration.stimulus_kind);
  response.fixture_identity = snapshot.fixture_identity;
  response.stimulus_identity = snapshot.stimulus_identity;
  response.hardware_error_flags = snapshot.hardware_error_flags;
  const auto addFlag = [&response](protocol_v1::GpioCaptureDiagnosticFlag flag,
                                   bool enabled) {
    if (enabled) {
      response.diagnostic_flags |= static_cast<std::uint32_t>(flag);
    }
  };
  addFlag(protocol_v1::GpioCaptureDiagnosticFlag::kAvailable, true);
  addFlag(protocol_v1::GpioCaptureDiagnosticFlag::kDeclarationValid,
          plan.declaration_valid);
  addFlag(protocol_v1::GpioCaptureDiagnosticFlag::kOutputDrivePermitted,
          plan.output_drive_permitted);
  addFlag(protocol_v1::GpioCaptureDiagnosticFlag::kExternalStimulusDeclared,
          plan.external_stimulus_declared);
  addFlag(protocol_v1::GpioCaptureDiagnosticFlag::kDmaCaptureExercised,
          snapshot.dma_capture_exercised);
  addFlag(
      protocol_v1::GpioCaptureDiagnosticFlag::kPackedObservationExercised,
      snapshot.packed_observation_exercised);
  addFlag(protocol_v1::GpioCaptureDiagnosticFlag::kOutputDriveExercised,
          snapshot.output_drive_exercised);
  addFlag(protocol_v1::GpioCaptureDiagnosticFlag::
              kExternalTransitionValidationExercised,
          snapshot.external_transition_validation_exercised);
  addFlag(protocol_v1::GpioCaptureDiagnosticFlag::kFinalInputSafe,
          snapshot.final_input_safe);
  response.dwt_counter_hz = snapshot.dwt_counter_hz;
  response.dwt_elapsed_cycles = snapshot.dwt_elapsed_cycles;
  response.dma_samples_captured = snapshot.dma_samples_captured;
  response.complete_samples_retained = snapshot.complete_samples_retained;
  response.samples_analyzed = snapshot.samples_analyzed;
  response.stopped_partial_samples = snapshot.stopped_partial_samples;
  response.raw_word_and = snapshot.raw_word_and;
  response.raw_word_or = snapshot.raw_word_or;
  response.observed_transitions = snapshot.observed_transitions;
  response.mapping_values_checked = snapshot.mapping_values_checked;
  response.mapping_failures = snapshot.mapping_failures;
  response.unstable_samples = snapshot.unstable_samples;
  response.packed_value_and = snapshot.packed_value_and;
  response.packed_value_or = snapshot.packed_value_or;
  response.first_packed_value = snapshot.first_packed_value;
  response.last_packed_value = snapshot.last_packed_value;
  response.gpr27_before = snapshot.registers.gpr27_before;
  response.gpr27_configured = snapshot.registers.gpr27_configured;
  response.gpr27_after = snapshot.registers.gpr27_after;
  response.gpio2_gdir_before = snapshot.registers.gpio2_gdir_before;
  response.gpio2_gdir_configured = snapshot.registers.gpio2_gdir_configured;
  response.gpio2_gdir_after = snapshot.registers.gpio2_gdir_after;
  response.gpio2_psr_before = snapshot.registers.gpio2_psr_before;
  response.gpio2_psr_configured = snapshot.registers.gpio2_psr_configured;
  response.gpio2_psr_after = snapshot.registers.gpio2_psr_after;
  response.pit_ldval_configured = snapshot.registers.pit_ldval_configured;
  response.pit_tctrl_configured = snapshot.registers.pit_tctrl_configured;
  response.dmamux_chcfg_configured =
      snapshot.registers.dmamux_chcfg_configured;
  response.dma_erq_configured = snapshot.registers.dma_erq_configured;
  response.dma_err_final = snapshot.registers.dma_err_final;
  response.tcd_citer_configured = snapshot.registers.tcd_citer_configured;
  response.tcd_biter_configured = snapshot.registers.tcd_biter_configured;
  response.tcd_csr_configured = snapshot.registers.tcd_csr_configured;
  response.edma_priority_configured =
      snapshot.registers.edma_priority_configured;
  response.analysis_sample_limit = plan.analysis_sample_limit;
  return response;
}

TEENSY_DAQ_RUNTIME_COLD_CODE(".flashmem.runtime.response_recovery")
void FirmwareRuntime::recoverResponsePath(
    const protocol::Request &request, protocol::ControlFrame &response,
    bool transport_already_recorded, LoopReport &report) {
  report.internal_error = true;
  if (!transport_already_recorded) {
    control_.statistics().recordTransportError();
  }
  report.recovered_to_idle = control_.recoverToIdle();

  response.clear();
  const protocol::Result fallback = protocol::encodeTypedErrorResponse(
      request, control_.runId(), protocol_v1::ErrorCode::kInternalError,
      response);
  if (fallback.ok() && transport_.queueResponse(response)) {
    report.response_queued = true;
    return;
  }

  report.response_reservation_abandoned =
      transport_.abandonResponseReservation();
}

#undef TEENSY_DAQ_RUNTIME_COLD_CODE

}  // namespace teensy_daq::runtime
