/*
 * Teensy DAQ control-plane foundation firmware.
 *
 * This build centralizes exact target identity, truthful Phase 03 capability
 * metadata, and future hardware resource ownership. Command handling and
 * acquisition remain deliberately unsupported in this task.
 */

#include "src/board_config.h"
#include "src/firmware_capabilities.h"
#include "src/firmware_identity.h"
#include "src/generated/protocol_constants.h"

namespace teensy_daq {

constexpr uint32_t kSerialWaitMilliseconds = 1500U;

protocol_v1::DeviceState device_state = protocol_v1::DeviceState::kBoot;

const char *stateName(protocol_v1::DeviceState state) {
  switch (state) {
    case protocol_v1::DeviceState::kBoot:
      return "BOOT";
    case protocol_v1::DeviceState::kIdle:
      return "IDLE";
    case protocol_v1::DeviceState::kConfigured:
      return "CONFIGURED";
    case protocol_v1::DeviceState::kRunning:
      return "RUNNING";
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

  teensy_daq::device_state = teensy_daq::protocol_v1::DeviceState::kIdle;

  if (Serial) {
    Serial.print("TEENSY_DAQ build=");
    Serial.print(teensy_daq::identity::kBuildId.data());
    Serial.print(" source=");
    Serial.print(teensy_daq::identity::kSourceId.data());
    Serial.print(" built=");
    Serial.print(teensy_daq::identity::kBuildTimestampUtc.data());
    Serial.print(" state=");
    Serial.print(teensy_daq::stateName(teensy_daq::device_state));
    Serial.print(" protocol=");
    Serial.print(teensy_daq::identity::kProtocolVersion);
    Serial.print(" streams=");
    Serial.print(teensy_daq::capabilities::kSupportedStreamMask);
    Serial.println(" acquisition=unsupported control_only=yes");
  }
}

void loop() {
  // The foundation build remains IDLE. Later control-plane work will replace
  // this with bounded frame handling without changing the boot contract.
  yield();
}
