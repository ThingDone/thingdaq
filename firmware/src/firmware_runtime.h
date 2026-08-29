#pragma once

#include <cstddef>
#include <cstdint>

#include "acquisition_controller.h"
#include "checksum_benchmark.h"
#include "control_state.h"
#include "gpio_capture_diagnostic.h"
#include "gpio_clock_diagnostic.h"
#include "packet_buffer_pipeline.h"
#include "synthetic_source.h"
#include "usb_transport.h"

namespace teensy_daq::runtime {

struct LoopReport : acquisition::Report {
  usb::ServiceReport receive{};
  usb::ServiceReport transmit_before_producers{};
  usb::ServiceReport transmit{};
  control::PendingEvents events{};
  packet::PromotionReport packet_promotion{};
  packet::OperationStatus packet_start_status =
      packet::OperationStatus::kNotRunning;
  synthetic::OperationStatus synthetic_start_status =
      synthetic::OperationStatus::kNotRunning;
  synthetic::ServiceReport synthetic{};
  bool command_dispatched = false;
  bool response_queued = false;
  bool recovered_to_idle = false;
  bool response_reservation_abandoned = false;
  bool packet_run_started = false;
  bool synthetic_run_started = false;
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
                  benchmark::Runner *checksum_benchmark = nullptr,
                  gpio_clock::Runner *gpio_clock_diagnostic = nullptr,
                  gpio_capture::HardwareCapture *gpio_capture = nullptr,
                  gpio_packer::GpioBatchPacker *gpio_packer = nullptr,
                  gpio_diagnostic::Runner *gpio_capture_diagnostic = nullptr,
                  adc::Initializer *adc_initializer = nullptr,
                  adc_trigger::Scheduler *adc_trigger_scheduler = nullptr,
                  adc_capture::HardwareCapture *adc_capture = nullptr,
                  adc_packer::AdcFramePacker *adc_packer = nullptr)
      : control_{},
        packet_pipeline_{packet_storage},
        synthetic_source_{source_mode},
        clock_(clock),
        transport_{stream, control_.statistics(), &packet_pipeline_},
        acquisition_controller_{
            control_.statistics(), packet_pipeline_, gpio_capture, gpio_packer,
            adc_initializer, adc_trigger_scheduler, adc_capture, adc_packer},
        checksum_benchmark_(checksum_benchmark),
        gpio_clock_diagnostic_(gpio_clock_diagnostic),
        gpio_capture_diagnostic_(gpio_capture_diagnostic) {}

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
  bool physicalDrainPending() const {
    return acquisition_controller_.drainPending();
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
  void resetTransportStatisticsEpoch();
  void observeTransportQueueDepths();
  void publishPacketStatistics();
  bool dataPathQuiescent() const;
  static protocol::GpioCaptureDiagnosticResponse gpioDiagnosticResponse(
      const gpio_diagnostic::Runner &runner,
      const gpio_diagnostic::Snapshot &snapshot);

  control::ControlState control_{};
  packet::PacketBufferPipeline packet_pipeline_;
  synthetic::SyntheticSource synthetic_source_;
  synthetic::TickClock &clock_;
  usb::CdcTransport transport_;
  acquisition::Controller acquisition_controller_;
  benchmark::Runner *checksum_benchmark_ = nullptr;
  gpio_clock::Runner *gpio_clock_diagnostic_ = nullptr;
  gpio_diagnostic::Runner *gpio_capture_diagnostic_ = nullptr;
  std::uint32_t packet_stats_generation_ = 0U;
  usb::TransportSnapshot transport_stats_baseline_{};
  std::size_t transport_command_queue_high_water_ = 0U;
  std::size_t transport_response_queue_high_water_ = 0U;
};

}  // namespace teensy_daq::runtime
