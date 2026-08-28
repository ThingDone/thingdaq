#include "firmware_runtime.h"

namespace teensy_daq::runtime {

bool FirmwareRuntime::begin(std::uint32_t hardware_serial) {
  return control_.completeBoot(hardware_serial);
}

LoopReport FirmwareRuntime::service() {
  LoopReport report{};
  report.receive = transport_.serviceReceive();

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
  if (report.events.has(control::Event::kStop)) {
    packet_pipeline_.stopProduction();
    report.packet_production_stopped = true;
  }
  if (report.events.has(control::Event::kStartEpoch)) {
    report.packet_start_status =
        packet_pipeline_.startRun(report.events.run_id);
    report.packet_run_started =
        report.packet_start_status == packet::OperationStatus::kOk;
  }

  // All frame construction and queue ownership changes stay in this bounded
  // cooperative path. A future pacing ISR may only publish compact event/time
  // state for source code serviced before this promotion step.
  report.packet_promotion = packet_pipeline_.serviceReadyFrames();
  report.transmit = transport_.serviceTransmit();
  return report;
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
