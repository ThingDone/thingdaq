/*
 * Teensy DAQ foundation firmware.
 *
 * This build only proves bounded startup and an IDLE control state. Protocol
 * commands and acquisition are intentionally unsupported until their shared,
 * generated wire constants and portable control modules are added.
 */

#if __has_include("src/generated/protocol_constants.h")
#include "src/generated/protocol_constants.h"
#define TEENSY_DAQ_PROTOCOL_CONSTANTS_PRESENT 1
#else
#define TEENSY_DAQ_PROTOCOL_CONSTANTS_PRESENT 0
#endif

namespace teensy_daq {

constexpr char kBuildId[] = "teensy-daq-foundation-0.0.0";
constexpr uint32_t kSerialWaitMilliseconds = 1500;

enum class DeviceState : uint8_t {
  kBoot,
  kIdle,
};

DeviceState device_state = DeviceState::kBoot;

const char *stateName(DeviceState state) {
  switch (state) {
    case DeviceState::kBoot:
      return "BOOT";
    case DeviceState::kIdle:
      return "IDLE";
  }
  return "UNKNOWN";
}

}  // namespace teensy_daq

void setup() {
  Serial.begin(115200);

  // Native USB may enumerate after reset, but a missing host must never keep
  // the firmware in BOOT indefinitely.
  const uint32_t wait_started = millis();
  while (!Serial && millis() - wait_started <
                        teensy_daq::kSerialWaitMilliseconds) {
    yield();
  }

  teensy_daq::device_state = teensy_daq::DeviceState::kIdle;

  if (Serial) {
    Serial.print("TEENSY_DAQ build=");
    Serial.print(teensy_daq::kBuildId);
    Serial.print(" state=");
    Serial.print(teensy_daq::stateName(teensy_daq::device_state));
    Serial.print(" protocol_constants=");
    Serial.print(TEENSY_DAQ_PROTOCOL_CONSTANTS_PRESENT ? "present" : "absent");
    Serial.println(" acquisition=unsupported");
  }
}

void loop() {
  // The foundation build remains IDLE. Later control-plane work will replace
  // this with bounded frame handling without changing the boot contract.
  yield();
}
