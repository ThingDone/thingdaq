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

  // Phase 03 has no acquisition engine. Consuming these compact signals here
  // proves their main-loop ownership; later phases will route the same report
  // to bounded clock/source operations without moving work into an ISR.
  report.events = control_.takePendingEvents();
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
