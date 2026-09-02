#pragma once

#include <cstdint>

#include "protocol.h"

namespace thingdaq::clock_health {

struct HardwareReadback {
  std::uint32_t cpu_clock_hz = 0U;
  std::uint32_t ipg_clock_hz = 0U;
  std::uint32_t adc_clock_hz = 0U;
  std::uint32_t pit_clock_hz = 0U;
  std::uint32_t dwt_clock_hz = 0U;
  protocol_v1::TemperatureStatus temperature_status =
      protocol_v1::TemperatureStatus::kUnavailable;
  std::int32_t temperature_millidegrees_celsius = 0;
  std::uint32_t error_flags = 0U;
};

// Target adapter for read-only clock-tree/TEMPMON sampling and the DWT cycle
// counter. Every implementation must keep sampleHardware() finite.
class Hardware {
 public:
  virtual ~Hardware() = default;
  virtual bool beginCycleCounter() = 0;
  virtual std::uint32_t cycleCount() const = 0;
  virtual HardwareReadback sampleHardware() = 0;
};

// Cooperative cycle accounting. DWT deltas time only bounded runtime service
// regions; the 64-bit protocol tick clock supplies the utilization interval so
// STATUS polling may span a 32-bit DWT wrap without ambiguity.
class Monitor {
 public:
  explicit constexpr Monitor(Hardware &hardware) : hardware_(hardware) {}

  bool begin(std::uint64_t now_ticks);
  void beginAcquisitionService();
  void endAcquisitionService();
  void beginUsbService();
  void endUsbService();
  protocol::ClockHealthSample sample(std::uint64_t now_ticks);

 private:
  enum class Service : std::uint8_t { kAcquisition, kUsb };

  void beginService(Service service);
  void endService(Service service);
  static void saturatingIncrement(std::uint32_t &value);
  static void saturatingAdd(std::uint64_t &value, std::uint32_t increment);
  static std::uint16_t utilizationBasisPoints(std::uint64_t service_cycles,
                                              std::uint64_t interval_cycles);

  Hardware &hardware_;
  std::uint64_t last_sample_ticks_ = 0U;
  std::uint64_t acquisition_cycles_ = 0U;
  std::uint64_t usb_cycles_ = 0U;
  std::uint32_t acquisition_start_ = 0U;
  std::uint32_t usb_start_ = 0U;
  std::uint32_t sample_sequence_ = 0U;
  std::uint32_t temperature_error_count_ = 0U;
  std::uint32_t clock_mismatch_count_ = 0U;
  std::uint32_t service_counter_error_count_ = 0U;
  bool cycle_counter_available_ = false;
  bool acquisition_active_ = false;
  bool usb_active_ = false;
  bool initialized_ = false;
};

}  // namespace thingdaq::clock_health
