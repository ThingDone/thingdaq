#include "firmware_runtime.h"

namespace teensy_daq::runtime {

bool FirmwareRuntime::begin(std::uint32_t hardware_serial) {
  return control_.completeBoot(hardware_serial);
}

LoopReport FirmwareRuntime::service() {
  LoopReport report{};
  report.receive = transport_.serviceReceive();
  publishPacketStatistics();

  protocol::ParsedCommand command{};
  if (transport_.takeCommand(command)) {
    report.command_dispatched = true;
    protocol::ControlFrame response{};
    const control::DispatchResult dispatched =
        control_.dispatch(command.request, response);
    if (dispatched.responseReady()) {
      report.response_queued = transport_.queueResponse(response);
      if (!report.response_queued) {
        recoverResponsePath(command.request, response, true, report);
      }
    } else {
      recoverResponsePath(command.request, response, false, report);
    }
  }

  report.events = control_.takePendingEvents();
  const std::uint64_t now_ticks = clock_.nowTicks();
  if (report.events.has(control::Event::kStop)) {
    synthetic_source_.stop();
    report.synthetic_production_stopped = true;
    packet_pipeline_.stopProduction();
    report.packet_production_stopped = true;
  }
  if (report.events.has(control::Event::kStartEpoch)) {
    report.packet_start_status =
        packet_pipeline_.startRun(report.events.run_id);
    report.packet_run_started =
        report.packet_start_status == packet::OperationStatus::kOk;
    if (report.packet_run_started) {
      report.synthetic_start_status = synthetic_source_.startRun(
          report.events.run_id, control_.appliedConfiguration(), now_ticks,
          packet_pipeline_);
      report.synthetic_run_started =
          report.synthetic_start_status == synthetic::OperationStatus::kOk;
      if (report.synthetic_run_started) {
        packet_stats_generation_ = report.events.stats_generation;
      } else {
        packet_pipeline_.stopProduction();
        report.packet_production_stopped = true;
        report.internal_error = true;
      }
    }
  }

  // Pattern construction, framing/checksum work, queue ownership, and USB all
  // stay in this bounded cooperative path. The production clock is polled;
  // no pacing ISR is installed.
  report.synthetic = synthetic_source_.service(now_ticks, packet_pipeline_);
  report.packet_promotion = packet_pipeline_.serviceReadyFrames();
  report.transmit = transport_.serviceTransmit();
  publishPacketStatistics();
  return report;
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
