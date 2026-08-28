#pragma once

#include <cstdint>

#include "control_state.h"
#include "packet_buffer_pipeline.h"
#include "usb_transport.h"

namespace teensy_daq::runtime {

struct LoopReport {
  usb::ServiceReport receive{};
  usb::ServiceReport transmit{};
  control::PendingEvents events{};
  packet::PromotionReport packet_promotion{};
  packet::OperationStatus packet_start_status =
      packet::OperationStatus::kNotRunning;
  bool command_dispatched = false;
  bool response_queued = false;
  bool internal_error = false;
  bool recovered_to_idle = false;
  bool response_reservation_abandoned = false;
  bool packet_run_started = false;
  bool packet_production_stopped = false;
};

// Portable cooperative owner for the Phase 03 control plane plus Phase 04
// packet foundation. Member order is intentional: ControlState owns
// Statistics and PacketBufferPipeline owns the lower-priority source before
// CdcTransport stores either reference. The sketch supplies aligned packet
// storage and the core-derived serial at the BOOT boundary.
class FirmwareRuntime {
 public:
  FirmwareRuntime(usb::CdcByteStream &stream,
                  packet::PacketBufferStorage &packet_storage)
      : control_{},
        packet_pipeline_{packet_storage},
        transport_{stream, control_.statistics(), &packet_pipeline_} {}

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
  packet::PipelineSnapshot packetSnapshot() const {
    return packet_pipeline_.snapshot();
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
  packet::PacketBufferPipeline packet_pipeline_;
  usb::CdcTransport transport_;
};

}  // namespace teensy_daq::runtime
