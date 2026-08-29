#pragma once

#include <cstdint>

#include "adc_initializer.h"
#include "adc_dma_capture.h"
#include "adc_frame_packer.h"
#include "adc_trigger.h"
#include "checksum_benchmark.h"
#include "control_state.h"
#include "gpio_batch_packer.h"
#include "gpio_capture_diagnostic.h"
#include "gpio_clock_diagnostic.h"
#include "gpio_raw_capture.h"
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
  gpio_packer::ServiceReport gpio_packer{};
  gpio_capture::StopReport gpio_capture_stop{};
  gpio_packer::StopReport gpio_packer_stop{};
  adc_packer::ServiceReport adc_packer{};
  adc_capture::StopReport adc_capture_stop{};
  adc_packer::StopReport adc_packer_stop{};
  gpio_capture::StartStatus gpio_capture_start_status =
      gpio_capture::StartStatus::kNotQuiescent;
  gpio_packer::OperationStatus gpio_packer_start_status =
      gpio_packer::OperationStatus::kNotRunning;
  adc_capture::StartStatus adc_capture_start_status =
      adc_capture::StartStatus::kNotQuiescent;
  adc_packer::OperationStatus adc_packer_start_status =
      adc_packer::OperationStatus::kNotRunning;
  bool command_dispatched = false;
  bool response_queued = false;
  bool internal_error = false;
  bool recovered_to_idle = false;
  bool response_reservation_abandoned = false;
  bool packet_run_started = false;
  bool synthetic_run_started = false;
  bool packet_production_stopped = false;
  bool synthetic_production_stopped = false;
  bool gpio_capture_started = false;
  bool gpio_capture_stopped = false;
  bool gpio_packer_started = false;
  bool gpio_packer_stopped = false;
  bool adc_capture_prepared = false;
  bool adc_capture_boundary_stopped = false;
  bool adc_capture_stopped = false;
  bool adc_packer_started = false;
  bool adc_packer_stopped = false;
  bool adc_trigger_armed = false;
  bool adc_trigger_stopped = false;
  bool physical_drain_pending = false;
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
        checksum_benchmark_(checksum_benchmark),
        gpio_clock_diagnostic_(gpio_clock_diagnostic),
        gpio_capture_(gpio_capture),
        gpio_packer_(gpio_packer),
        gpio_capture_diagnostic_(gpio_capture_diagnostic),
        adc_initializer_(adc_initializer),
        adc_trigger_scheduler_(adc_trigger_scheduler),
        adc_capture_(adc_capture),
        adc_packer_(adc_packer) {}

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
  bool physicalDrainPending() const { return physical_drain_pending_; }
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
  bool dataPathQuiescent() const;
  bool physicalConfiguration(const protocol::Configuration &configuration)
      const;
  bool adcPhysicalConfiguration(
      const protocol::Configuration &configuration) const;
  bool gpioPhysicalConfiguration(
      const protocol::Configuration &configuration) const;
  bool physicalPathReady(const protocol::Configuration &configuration,
                         std::uint32_t epoch);
  bool stopAdcPhysicalPath(LoopReport &report);
  void servicePhysicalPath(LoopReport &report);
  static protocol::GpioCaptureDiagnosticResponse gpioDiagnosticResponse(
      const gpio_diagnostic::Runner &runner,
      const gpio_diagnostic::Snapshot &snapshot);

  control::ControlState control_{};
  packet::PacketBufferPipeline packet_pipeline_;
  synthetic::SyntheticSource synthetic_source_;
  synthetic::TickClock &clock_;
  usb::CdcTransport transport_;
  benchmark::Runner *checksum_benchmark_ = nullptr;
  gpio_clock::Runner *gpio_clock_diagnostic_ = nullptr;
  gpio_capture::HardwareCapture *gpio_capture_ = nullptr;
  gpio_packer::GpioBatchPacker *gpio_packer_ = nullptr;
  gpio_diagnostic::Runner *gpio_capture_diagnostic_ = nullptr;
  adc::Initializer *adc_initializer_ = nullptr;
  adc_trigger::Scheduler *adc_trigger_scheduler_ = nullptr;
  adc_capture::HardwareCapture *adc_capture_ = nullptr;
  adc_packer::AdcFramePacker *adc_packer_ = nullptr;
  std::uint32_t packet_stats_generation_ = 0U;
  std::uint8_t physical_stream_mask_ = 0U;
  bool physical_run_active_ = false;
  bool physical_drain_pending_ = false;
};

}  // namespace teensy_daq::runtime
