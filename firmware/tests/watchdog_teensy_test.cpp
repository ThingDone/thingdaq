#include <cassert>
#include <cstdint>
#include <string>

#include <imxrt.h>
#include <core_pins.h>

#include "watchdog_teensy.h"

int main(int argc, char **argv) {
  assert(argc == 2);
  const std::string mode = argv[1];
  fake_watchdog::control = mode == "wide" ? WDOG_CS_CMD32EN : 0U;
  fake_watchdog::accept_unlock = mode != "unlock-failure";
  fake_watchdog::accept_configuration = mode != "config-failure";
  SRC_SRSR = 0x181U;
  SRC_SCR = 0x50001234U;
  fake_imxrt::interrupts_enabled = mode != "masked";
  const bool initially_enabled = fake_imxrt::interrupts_enabled;
  fake_imxrt::clearRegisterWrites();

  const bool expected = mode != "unlock-failure" && mode != "config-failure";
  assert(thingdaq::watchdog::begin() == expected);
  assert(fake_imxrt::interrupts_enabled == initially_enabled);
  assert(thingdaq::watchdog::enabled() == expected);
  assert(thingdaq::watchdog::resetCause() == 0x181U);
  assert(SRC_SRSR == 0x81U);
  assert(SRC_SCR == 0xA0001234U);
  assert(thingdaq::watchdog::timeoutMs() == 4000U);
  assert(fake_watchdog::reads <= 100020U);

  const auto writes_before_retry = fake_imxrt::register_write_count;
  assert(thingdaq::watchdog::begin() == expected);
  assert(fake_imxrt::register_write_count == writes_before_retry);
  thingdaq::watchdog::refresh();
  assert(fake_imxrt::register_write_count == writes_before_retry + (expected ? 1U : 0U));
  if (expected) {
    assert(WDOG3_TOVAL == 512U);
    const auto &last = fake_imxrt::register_writes[writes_before_retry];
    assert(last.address == &WDOG3_CNT && last.value == 0xB480A602U);
    assert((WDOG3_CS & (WDOG_CS_INT | WDOG_CS_WIN | WDOG_CS_DBG)) == 0U);
  }
  // Unlock must honor the initial command width.
  std::uint32_t counter_writes = 0U;
  for (std::size_t i = 0; i < writes_before_retry; ++i) {
    const auto &write = fake_imxrt::register_writes[i];
    if (write.address == &WDOG3_CNT) {
      assert(write.value == (mode == "wide" ? 0xD928C520U :
          counter_writes == 0U ? 0xC520U : 0xD928U));
      ++counter_writes;
    }
  }
  assert(counter_writes == (mode == "wide" ? 1U : 2U));
}
