#include "firmware_runtime.h"

namespace teensy_daq::runtime {

bool FirmwareRuntime::begin(std::uint32_t hardware_serial) {
  return control_.completeBoot(hardware_serial);
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
    if (command.request.kind == protocol_v1::CommandKind::kConfigure) {
      readiness.configuration_ready =
          packet_pipeline_.quiescent() && !synthetic_source_.running();
    } else if (command.request.kind == protocol_v1::CommandKind::kStart) {
      readiness.start_ready =
          packet_pipeline_.readyForStart() && !synthetic_source_.running();
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
  report.packet_promotion = packet_pipeline_.serviceReadyFrames();
  report.transmit = transport_.serviceTransmit();
  publishPacketStatistics();
  return report;
}

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
    synthetic_source_.stop();
    report.synthetic_production_stopped = true;
    report.packet_stop = packet_pipeline_.stopProduction();
    report.packet_production_stopped = true;
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
}

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

}  // namespace teensy_daq::runtime
