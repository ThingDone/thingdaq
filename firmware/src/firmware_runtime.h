#pragma once

#include <cstdint>

#include "control_state.h"
#include "usb_transport.h"

namespace teensy_daq::runtime {

struct LoopReport {
  usb::ServiceReport receive{};
  usb::ServiceReport transmit{};
  control::PendingEvents events{};
  bool command_dispatched = false;
  bool response_queued = false;
  bool internal_error = false;
  bool recovered_to_idle = false;
  bool response_reservation_abandoned = false;
};

// Portable cooperative owner for the complete Phase 03 control plane. Member
// declaration order is intentional: ControlState owns Statistics before the
// transport stores its reference. The board sketch owns only the concrete CDC
// adapter and supplies the core-derived serial number at the BOOT boundary.
class FirmwareRuntime {
 public:
  explicit FirmwareRuntime(usb::CdcByteStream &stream)
      : control_{}, transport_{stream, control_.statistics()} {}

  bool begin(std::uint32_t hardware_serial);
  LoopReport service();

  constexpr protocol_v1::DeviceState state() const {
    return control_.state();
  }
  constexpr std::uint32_t runId() const { return control_.runId(); }
  constexpr std::uint32_t hardwareSerial() const {
    return control_.hardwareSerial();
  }
  constexpr const stats::Statistics &statistics() const {
    return control_.statistics();
  }
  usb::TransportSnapshot transportSnapshot() const {
    return transport_.snapshot();
  }
  bool hasPendingTransmission() const {
    return transport_.hasPendingTransmission();
  }

 private:
  void recoverResponsePath(const protocol::Request &request,
                           protocol::ControlFrame &response,
                           bool transport_already_recorded,
                           LoopReport &report);

  control::ControlState control_{};
  usb::CdcTransport transport_;
};

}  // namespace teensy_daq::runtime
