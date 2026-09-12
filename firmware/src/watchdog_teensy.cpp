#include "watchdog_teensy.h"

#if defined(ARDUINO_TEENSY40) && defined(__IMXRT1062__)

#include <imxrt.h>

#include "interrupt_guard_teensy.h"

namespace thingdaq::watchdog {
namespace {

// RT1060 RM rev. 3, sections 58.1 and 58.5: CLK=1 is the 32 kHz
// crystal/RC source on this chip, not the 1 kHz LPO of other WDOG parts.
constexpr std::uint32_t kClockHz = 32768U;
constexpr std::uint32_t kPrescaler = 256U;
constexpr std::uint32_t kTimeoutTicks = 512U;
constexpr std::uint32_t kConfigurationPollLimit = 100000U;
constexpr std::uint32_t kUnlock = 0xD928C520U;
constexpr std::uint32_t kRefresh = 0xB480A602U;
constexpr std::uint32_t kConfiguration =
    WDOG_CS_EN | WDOG_CS_CLK(1U) | WDOG_CS_PRES | WDOG_CS_CMD32EN |
    WDOG_CS_UPDATE | WDOG_CS_WAIT | WDOG_CS_STOP;
constexpr std::uint32_t kConfigurationMask =
    WDOG_CS_EN | WDOG_CS_CLK(3U) | WDOG_CS_PRES | WDOG_CS_CMD32EN |
    WDOG_CS_UPDATE | WDOG_CS_WAIT | WDOG_CS_STOP | WDOG_CS_DBG |
    WDOG_CS_INT | WDOG_CS_WIN | WDOG_CS_TST(3U);

bool g_initialized = false;
bool g_enabled = false;
std::uint32_t g_reset_cause = 0U;

}  // namespace

bool begin() {
  if (g_initialized) {
    return enabled();
  }
  g_initialized = true;
  g_reset_cause = SRC_SRSR;
  // Bits 0..7 are W1C; temperature reset bit 8 is cleared by writing zero.
  // Retain the boot snapshot so later diagnostics are stable and subsequent
  // boots do not misattribute an old watchdog reset to the latest reset.
  SRC_SRSR = g_reset_cause & 0xFFU;

  CCM_CCGR5 |= CCM_CCGR5_WDOG3(3U);
  // Explicitly unmask WDOG3 reset at SRC (RM 20.8.1, encoding 0xA).
  SRC_SCR = (SRC_SCR & ~SRC_SCR_MASK_WDOG3_RST(0xFU)) |
            SRC_SCR_MASK_WDOG3_RST(0xAU);
  const interrupts::Guard guard;
  // Match the existing command width, including the power-on 16-bit mode.
  if ((WDOG3_CS & WDOG_CS_CMD32EN) != 0U) {
    WDOG3_CNT = kUnlock;
  } else {
    WDOG3_CNT = kUnlock & 0xFFFFU;
    WDOG3_CNT = kUnlock >> 16U;
  }
  std::uint32_t polls = 0U;
  while ((WDOG3_CS & WDOG_CS_ULK) == 0U &&
         polls < kConfigurationPollLimit) {
    ++polls;
  }
  if ((WDOG3_CS & WDOG_CS_ULK) == 0U) {
    return false;
  }
  // Keep these adjacent and in ITCM: all writes must fit the 128 bus-clock
  // reconfiguration window. No helper call or interrupt may intervene.
  WDOG3_WIN = 0U;
  WDOG3_TOVAL = kTimeoutTicks;
  WDOG3_CS = kConfiguration;
  polls = 0U;
  while ((WDOG3_CS & WDOG_CS_RCS) == 0U &&
         polls < kConfigurationPollLimit) {
    ++polls;
  }
  g_enabled = (WDOG3_CS & WDOG_CS_RCS) != 0U &&
      (WDOG3_CS & kConfigurationMask) == kConfiguration &&
      WDOG3_TOVAL == kTimeoutTicks;
  return g_enabled;
}

void refresh() {
  if (g_enabled) {
    // CMD32EN was verified at initialization; a single 32-bit peripheral
    // write is the complete refresh sequence and cannot be split by an ISR.
    WDOG3_CNT = kRefresh;
  }
}

bool enabled() {
  return g_enabled && (WDOG3_CS & WDOG_CS_EN) != 0U;
}

std::uint32_t resetCause() { return g_reset_cause; }

std::uint32_t timeoutMs() {
  return kTimeoutTicks * kPrescaler * 1000U / kClockHz;
}

}  // namespace thingdaq::watchdog

#endif
