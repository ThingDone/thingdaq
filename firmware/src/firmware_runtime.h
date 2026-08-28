#pragma once

#include <cstdint>

#include "checksum_benchmark.h"
#include "control_state.h"
#include "packet_buffer_pipeline.h"
#include "synthetic_source.h"
#include "usb_transport.h"

namespace teensy_daq::runtime {

struct LoopReport {
  usb::ServiceReport receive{};
  usb::ServiceReport transmit{};
  control::PendingEvents events{};
  packet::PromotionReport packet_promotion{};
  packet::StopReport packet_stop{};
  packet::OperationStatus packet_start_status =
      packet::OperationStatus::kNotRunning;
  synthetic::OperationStatus synthetic_start_status =
      synthetic::OperationStatus::kNotRunning;
  synthetic::ServiceReport synthetic{};
  bool command_dispatched = false;
  bool response_queued = false;
  bool internal_error = false;
  bool recovered_to_idle = false;
  bool response_reservation_abandoned = false;
  bool packet_run_started = false;
  bool synthetic_run_started = false;
  bool packet_production_stopped = false;
  bool synthetic_production_stopped = false;
};

// Portable cooperative owner for the control plane, deterministic source, and
// packet pipeline. Member order is intentional: ControlState owns Statistics
// and PacketBufferPipeline owns the lower-priority source before CdcTransport
// stores either reference. The sketch supplies the clock, aligned storage,
// and core-derived serial at the BOOT boundary.
class FirmwareRuntime {
 public:
  FirmwareRuntime(usb::CdcByteStream &stream,
                  packet::PacketBufferStorage &packet_storage,
                  synthetic::TickClock &clock,
                  synthetic::Mode source_mode = synthetic::Mode::kRealtime,
                  benchmark::Runner *checksum_benchmark = nullptr)
      : control_{},
        packet_pipeline_{packet_storage},
        synthetic_source_{source_mode},
        clock_(clock),
        transport_{stream, control_.statistics(), &packet_pipeline_},
        checksum_benchmark_(checksum_benchmark) {}

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
  synthetic::Snapshot syntheticSnapshot() const {
    return synthetic_source_.snapshot();
  }
  bool hasPendingTransmission() const {
    return transport_.hasPendingTransmission();
  }

 private:
  void applyPendingEvents(const control::PendingEvents &events,
                          std::uint64_t now_ticks, LoopReport &report);
  void recoverResponsePath(const protocol::Request &request,
                           protocol::ControlFrame &response,
                           bool transport_already_recorded,
                           LoopReport &report);
  void publishPacketStatistics();

  control::ControlState control_{};
  packet::PacketBufferPipeline packet_pipeline_;
  synthetic::SyntheticSource synthetic_source_;
  synthetic::TickClock &clock_;
  usb::CdcTransport transport_;
  benchmark::Runner *checksum_benchmark_ = nullptr;
  std::uint32_t packet_stats_generation_ = 0U;
};

}  // namespace teensy_daq::runtime
