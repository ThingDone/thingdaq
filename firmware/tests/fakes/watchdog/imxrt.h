#pragma once

#include "../teensy40/imxrt.h"

#define WDOG_CS_STOP (1U << 0)
#define WDOG_CS_WAIT (1U << 1)
#define WDOG_CS_DBG (1U << 2)
#define WDOG_CS_TST(n) (((n) & 3U) << 3)
#define WDOG_CS_UPDATE (1U << 5)
#define WDOG_CS_INT (1U << 6)
#define WDOG_CS_EN (1U << 7)
#define WDOG_CS_CLK(n) (((n) & 3U) << 8)
#define WDOG_CS_RCS (1U << 10)
#define WDOG_CS_ULK (1U << 11)
#define WDOG_CS_PRES (1U << 12)
#define WDOG_CS_CMD32EN (1U << 13)
#define WDOG_CS_WIN (1U << 15)
#define CCM_CCGR5_WDOG3(n) (((n) & 3U) << 4)
#define SRC_SCR_MASK_WDOG3_RST(n) (((n) & 15U) << 28)

namespace fake_watchdog {
inline bool accept_unlock = true;
inline bool accept_configuration = true;
inline std::uint32_t control = 0U;
inline std::uint32_t reads = 0U;
inline fake_imxrt::Register32 reset_cause{};
inline fake_imxrt::Register32 reset_control{};
inline fake_imxrt::Register32 timeout{};
inline fake_imxrt::Register32 window{};

struct Control {
  operator std::uint32_t() const {
    ++reads;
    return control;
  }
  Control &operator=(std::uint32_t value) {
    fake_imxrt::recordRegisterWrite(this, value);
    control = value | (accept_configuration ? WDOG_CS_RCS : 0U);
    return *this;
  }
};
inline Control cs{};

struct Counter {
  Counter &operator=(std::uint32_t value) {
    fake_imxrt::recordRegisterWrite(this, value);
    if (accept_unlock && (value == 0xD928U || value == 0xD928C520U)) {
      control = (control | WDOG_CS_ULK) & ~WDOG_CS_RCS;
    }
    return *this;
  }
};
inline Counter cnt{};
}  // namespace fake_watchdog

#define SRC_SRSR fake_watchdog::reset_cause
#define SRC_SCR fake_watchdog::reset_control
#define WDOG3_CS fake_watchdog::cs
#define WDOG3_CNT fake_watchdog::cnt
#define WDOG3_TOVAL fake_watchdog::timeout
#define WDOG3_WIN fake_watchdog::window
