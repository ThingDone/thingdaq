/*
 * Teensy DAQ control-plane foundation firmware.
 *
 * Native USB is initialized by the Teensy core before setup(). The project
 * descriptor and bounded CDC adapter live under src/; the following Phase 03
 * integration task will connect them to the portable parser/control modules.
 */

#include "src/generated/protocol_constants.h"

namespace teensy_daq {

protocol_v1::DeviceState device_state = protocol_v1::DeviceState::kBoot;

}  // namespace teensy_daq

void setup() {
  // Do not call Serial.begin(), test Serial as a boolean, wait for DTR, or
  // emit a banner into the framed byte stream. Native USB is already live,
  // and BOOT completion is independent of host enumeration or port opening.
  teensy_daq::device_state = teensy_daq::protocol_v1::DeviceState::kIdle;
}

void loop() {
  // The foundation build remains IDLE. Later control-plane work will replace
  // this with bounded frame handling without changing the boot contract.
  yield();
}
