#include "firmware_runtime.h"

#if defined(__IMXRT1062__)
#define THINGDAQ_RUNTIME_COLD_CODE(section_name) \
  __attribute__((section(section_name), noinline, noipa, used))
#else
#define THINGDAQ_RUNTIME_COLD_CODE(section_name)
#endif

namespace thingdaq::runtime {
namespace {

std::uint32_t counterDelta(std::uint32_t current, std::uint32_t baseline) {
  return current - baseline;
}

}  // namespace

THINGDAQ_RUNTIME_COLD_CODE(".flashmem.runtime.begin")
bool FirmwareRuntime::begin(std::uint32_t hardware_serial) {
  return control_.completeBoot(hardware_serial,
                               acquisition_controller_.initialize());
}

LoopReport FirmwareRuntime::service() {
  LoopReport report{};
  // Output expansion gets one fixed block visit before command parsing,
  // diagnostics, checksum work, or USB can consume the cooperative loop.
  acquisition_controller_.serviceOutput(report);
  report.receive = transport_.serviceReceive();
  if (transport_.takeSessionStarted()) {
    control_.beginHostSession();
  }
  // Preserve per-epoch queue high-water marks before takeCommand() removes the
  // newly received request.  This lightweight transport-only observation
  // replaces the former complete data-path snapshot at this point.
  observeTransportQueueDepths();
  const std::uint64_t now_ticks = clock_.nowTicks();

  protocol::ParsedCommand command{};
  protocol::ControlFrame response{};
  bool response_ready = false;
  if (transport_.takeCommand(command)) {
    report.command_dispatched = true;
    if (command.rejected()) {
      report.rejected_command_dispatched = true;
      const protocol::Result encoded = protocol::encodeRejectedFrameResponse(
          command.rejected_request_id, command.rejected_kind,
          command.rejected_version, command.rejection_error, response);
      if (encoded.ok()) {
        response_ready = true;
      } else {
        report.internal_error = true;
        control_.statistics().recordTransportError();
        report.response_reservation_abandoned =
            transport_.abandonResponseReservation();
      }
    } else {
      // STATUS must include receive-queue activity from this visit and every
      // completed data-path operation. Refresh it on demand instead of paying
      // for the complete telemetry traversal on every command-free loop.
      if (command.request.kind == protocol_v1::CommandKind::kGetStatus) {
        publishPacketStatistics();
      }
      control::DispatchReadiness readiness{};
      if (command.request.kind ==
          protocol_v1::CommandKind::kResetStats) {
        readiness.statistics_reset_ready =
            dataPathQuiescent() && transport_.responseQueueDepth() == 0U;
      }
      benchmark::RunResult benchmark_result{};
      gpio_clock::RunResult gpio_clock_result{};
      gpio_diagnostic::RunResult gpio_capture_result{};
      protocol::GpioCaptureDiagnosticResponse gpio_capture_response{};
      if (command.request.kind == protocol_v1::CommandKind::kConfigure) {
        readiness.configuration_ready = dataPathQuiescent();
        if (readiness.configuration_ready &&
            acquisition::Controller::isExecutableConfiguration(
                command.request.configuration)) {
          readiness.configuration_ready =
              acquisition_controller_.readyForStart(
                  command.request.configuration,
                  control::ControlState::nextRunId(control_.runId()));
        }
      } else if (command.request.kind == protocol_v1::CommandKind::kStart) {
        readiness.start_ready = dataPathQuiescent();
        if (readiness.start_ready &&
            acquisition::Controller::isExecutableConfiguration(
                control_.appliedConfiguration())) {
          readiness.start_ready = acquisition_controller_.readyForStart(
              control_.appliedConfiguration(),
              control::ControlState::nextRunId(control_.runId()));
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
      if (dispatched.commandAccepted() &&
          command.request.kind ==
              protocol_v1::CommandKind::kResetStats) {
        resetTransportStatisticsEpoch();
        packet_stats_generation_ = 0U;
      }
      if (dispatched.responseReady()) {
        response_ready = true;
      } else {
        recoverResponsePath(command.request, response, false, report);
      }
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
    } else {
      observeTransportQueueDepths();
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
  acquisition_controller_.service(report);
  if (report.physical_fault_detected &&
      control_.state() != protocol_v1::DeviceState::kIdle) {
    recoverPhysicalFault(now_ticks, report);
  }
  // Promote and transmit only after servicing physical ownership. While the
  // high-speed core drains that bounded 8 KiB visit, service ownership again
  // so ADC/GPIO completions cannot be hidden behind USB catch-up work.
  report.packet_promotion_before_second_acquisition =
      packet_pipeline_.serviceReadyFrames();
  report.transmit_before_second_acquisition = transport_.serviceTransmit();

  // Refill again between the two physical-acquisition/USB visits. Each call
  // expands at most one 1,016-state block and never waits for host I/O.
  acquisition_controller_.serviceOutput(report);
  acquisition_controller_.service(report);
  if (report.physical_fault_detected &&
      control_.state() != protocol_v1::DeviceState::kIdle) {
    recoverPhysicalFault(now_ticks, report);
  }
  report.packet_promotion = packet_pipeline_.serviceReadyFrames();
  report.transmit = transport_.serviceTransmit();
  return report;
}

THINGDAQ_RUNTIME_COLD_CODE(".flashmem.runtime.physical_fault")
void FirmwareRuntime::recoverPhysicalFault(std::uint64_t now_ticks,
                                           LoopReport &report) {
  report.recovered_to_idle = control_.recoverToIdle();
  if (!report.recovered_to_idle) {
    report.internal_error = true;
  }
  // The controller has already initiated fail-safe source teardown. Consume
  // ControlState's STOP signal in the same visit so a failed trigger cleanup
  // is retried without leaving the externally visible state RUNNING.
  applyPendingEvents(control_.takePendingEvents(), now_ticks, report);
}

THINGDAQ_RUNTIME_COLD_CODE(".flashmem.runtime.pending_events")
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
    if (acquisition_controller_.active()) {
      if (!acquisition_controller_.stop(report)) {
        return;
      }
    } else if (!acquisition_controller_.drainPending()) {
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
            control_.appliedConfiguration().data_checksum_algorithm,
            control_.appliedConfiguration().stream_mask);
    report.packet_run_started =
        report.packet_start_status == packet::OperationStatus::kOk;
    if (!report.packet_run_started) {
      report.internal_error = true;
      return;
    }
    resetTransportStatisticsEpoch();
    if (acquisition::Controller::isExecutableConfiguration(
            control_.appliedConfiguration())) {
      if (!acquisition_controller_.start(control_.appliedConfiguration(),
                                         events.run_id, now_ticks, report)) {
        report.internal_error = true;
        return;
      }
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

THINGDAQ_RUNTIME_COLD_CODE(".flashmem.runtime.publish_statistics")
void FirmwareRuntime::publishPacketStatistics() {
  const bool data_generation_active =
      packet_stats_generation_ != 0U &&
      packet_stats_generation_ == control_.statistics().generation();
  if (data_generation_active) {
    const packet::PipelineSnapshot pipeline = packet_pipeline_.snapshot();
    stats::DataPathProgress progress{};
    const auto copy = [](const packet::SourceCounters &source,
                         const packet::SourceByteCounters &bytes,
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
      destination.frames_evicted = source.frames_evicted;
      destination.frames_evicted_after_promotion =
          source.frames_evicted_after_promotion;
      destination.frames_dropped_after_framing =
          source.frames_dropped_after_framing;
      destination.frames_dropped_after_promotion =
          source.frames_dropped_after_promotion;
      destination.payload_bytes_produced = bytes.payload_bytes_produced;
      destination.payload_bytes_framed = bytes.payload_bytes_framed;
      destination.payload_bytes_emitted = bytes.payload_bytes_emitted;
      destination.payload_bytes_transmitted =
          bytes.payload_bytes_transmitted;
      destination.payload_bytes_dropped = bytes.payload_bytes_dropped;
      destination.framed_bytes_framed = bytes.framed_bytes_framed;
      destination.framed_bytes_emitted = bytes.framed_bytes_emitted;
      destination.framed_bytes_transmitted =
          bytes.framed_bytes_transmitted;
    };
    copy(pipeline.sources[packet::streamIndex(packet::Stream::kAdc)],
         pipeline.source_bytes[packet::streamIndex(packet::Stream::kAdc)],
         progress.adc);
    copy(pipeline.sources[packet::streamIndex(packet::Stream::kGpio)],
         pipeline.source_bytes[packet::streamIndex(packet::Stream::kGpio)],
         progress.gpio);
    control_.statistics().publishDataPath(progress);
    stats::PacketQueueProgress queues{};
    queues.filling_depth_by_source = pipeline.filling_depth_by_source;
    queues.ready_depth = pipeline.ready_queue_depth;
    queues.transmit_depth = pipeline.transmit_queue_depth;
    queues.owned_depth = pipeline.buffers_owned;
    queues.ready_depth_by_source = pipeline.ready_depth_by_source;
    queues.transmit_depth_by_source = pipeline.transmit_depth_by_source;
    for (std::size_t index = 0U; index < packet::kStreamCount; ++index) {
      queues.ready_high_water_by_source[index] =
          pipeline.sources[index].ready_queue_high_water;
      queues.transmit_high_water_by_source[index] =
          pipeline.sources[index].transmit_queue_high_water;
    }
    queues.ready_high_water = pipeline.ready_queue_high_water;
    queues.transmit_high_water = pipeline.transmit_queue_high_water;
    queues.owned_high_water = pipeline.buffers_owned_high_water;
    queues.frames_promoted = pipeline.frames_promoted;
    queues.fairness_deferrals = pipeline.fairness_deferrals;
    queues.pressure_evictions = pipeline.pressure_evictions;
    queues.capacity_drops_without_evictable_frame =
        pipeline.capacity_drops_without_evictable_frame;
    queues.accounted_frame_skew = pipeline.accounted_frame_skew;
    queues.data_payload_bytes_transmitted =
        pipeline.data_payload_bytes_transmitted;
    queues.data_framed_bytes_transmitted =
        pipeline.data_framed_bytes_transmitted;
    queues.pool_exhaustions = pipeline.pool_exhaustions;
    queues.invalid_operations = pipeline.invalid_operations;
    queues.encoding_rejections = pipeline.encoding_rejections;
    queues.ready_queue_rejections = pipeline.ready_queue_rejections;
    queues.transmit_queue_rejections = pipeline.transmit_queue_rejections;
    control_.statistics().publishPacketQueues(queues);
    acquisition_controller_.publishStatistics(control_.runId());
  }
  const usb::TransportSnapshot transport = transport_.snapshot();
  if (transport.command_queue_depth > transport_command_queue_high_water_) {
    transport_command_queue_high_water_ = transport.command_queue_depth;
  }
  if (transport.response_queue_depth > transport_response_queue_high_water_) {
    transport_response_queue_high_water_ = transport.response_queue_depth;
  }
  stats::UsbProgress usb{};
  usb.short_capacity_deferrals = counterDelta(
      transport.short_capacity_deferrals,
      transport_stats_baseline_.short_capacity_deferrals);
  usb.rx_stall_events = counterDelta(
      transport.rx_stall_events, transport_stats_baseline_.rx_stall_events);
  usb.tx_stall_events = counterDelta(
      transport.tx_stall_events, transport_stats_baseline_.tx_stall_events);
  usb.io_errors = counterDelta(transport.io_errors,
                               transport_stats_baseline_.io_errors);
  usb.responses_queued = counterDelta(
      transport.responses_queued,
      transport_stats_baseline_.responses_queued);
  usb.responses_completed = counterDelta(
      transport.responses_completed,
      transport_stats_baseline_.responses_completed);
  usb.response_queue_rejections = counterDelta(
      transport.response_queue_rejections,
      transport_stats_baseline_.response_queue_rejections);
  usb.response_reservations_abandoned = counterDelta(
      transport.response_reservations_abandoned,
      transport_stats_baseline_.response_reservations_abandoned);
  usb.command_queue_depth = transport.command_queue_depth;
  usb.response_queue_depth = transport.response_queue_depth;
  usb.lower_priority_queue_depth = transport.lower_priority_queue_depth;
  usb.command_queue_high_water = transport_command_queue_high_water_;
  usb.response_queue_high_water = transport_response_queue_high_water_;
  usb.active_frame_bytes_sent = transport.active_frame_bytes_sent;
  usb.active_frame_size = transport.active_frame_size;
  control_.statistics().publishUsb(usb);
}

THINGDAQ_RUNTIME_COLD_CODE(".flashmem.runtime.reset_transport_statistics")
void FirmwareRuntime::resetTransportStatisticsEpoch() {
  transport_stats_baseline_ = transport_.snapshot();
  transport_command_queue_high_water_ =
      transport_stats_baseline_.command_queue_depth;
  transport_response_queue_high_water_ =
      transport_stats_baseline_.response_queue_depth;
}

THINGDAQ_RUNTIME_COLD_CODE(".flashmem.runtime.observe_transport_queues")
void FirmwareRuntime::observeTransportQueueDepths() {
  const usb::TransportSnapshot transport = transport_.snapshot();
  if (transport.command_queue_depth > transport_command_queue_high_water_) {
    transport_command_queue_high_water_ = transport.command_queue_depth;
  }
  if (transport.response_queue_depth > transport_response_queue_high_water_) {
    transport_response_queue_high_water_ = transport.response_queue_depth;
  }
}

THINGDAQ_RUNTIME_COLD_CODE(".flashmem.runtime.quiescence")
bool FirmwareRuntime::dataPathQuiescent() const {
  return packet_pipeline_.quiescent() && !synthetic_source_.running() &&
         acquisition_controller_.quiescent();
}

THINGDAQ_RUNTIME_COLD_CODE(".flashmem.runtime.gpio_diagnostic_response")
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

THINGDAQ_RUNTIME_COLD_CODE(".flashmem.runtime.response_recovery")
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

#undef THINGDAQ_RUNTIME_COLD_CODE

}  // namespace thingdaq::runtime
