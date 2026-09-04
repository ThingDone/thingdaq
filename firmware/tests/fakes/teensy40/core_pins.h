#pragma once

#include <cstdint>

// Narrow host-test stand-in. These identities are the exact Teensy 4.0 values
// asserted by board_config.h; register behavior is supplied by the test.
#define CORE_NUM_DIGITAL 40U
#define A0 14U
#define A1 15U

#define CORE_PIN6_BIT 10U
#define CORE_PIN7_BIT 17U
#define CORE_PIN8_BIT 16U
#define CORE_PIN9_BIT 11U
#define CORE_PIN10_BIT 0U
#define CORE_PIN11_BIT 2U
#define CORE_PIN12_BIT 1U
#define CORE_PIN13_BIT 3U

#define CORE_PIN6_BITMASK (1UL << CORE_PIN6_BIT)
#define CORE_PIN7_BITMASK (1UL << CORE_PIN7_BIT)
#define CORE_PIN8_BITMASK (1UL << CORE_PIN8_BIT)
#define CORE_PIN9_BITMASK (1UL << CORE_PIN9_BIT)
#define CORE_PIN10_BITMASK (1UL << CORE_PIN10_BIT)
#define CORE_PIN11_BITMASK (1UL << CORE_PIN11_BIT)
#define CORE_PIN12_BITMASK (1UL << CORE_PIN12_BIT)
#define CORE_PIN13_BITMASK (1UL << CORE_PIN13_BIT)

#define CORE_PIN16_BIT 23U
#define CORE_PIN17_BIT 22U
#define CORE_PIN18_BIT 17U
#define CORE_PIN19_BIT 16U
#define CORE_PIN20_BIT 26U
#define CORE_PIN21_BIT 27U
#define CORE_PIN22_BIT 24U
#define CORE_PIN23_BIT 25U

// The ADC target-adapter tests intentionally compile the production Teensy
// register code on the host. Keep these symbols limited to the exact A0/A1,
// clock, and interrupt surface used by those adapters.
namespace fake_imxrt {

inline volatile std::uint32_t gpio6_gdir = 0U;
inline volatile std::uint32_t pin14_config = 0U;
inline volatile std::uint32_t pin15_config = 0U;
inline volatile std::uint32_t pin14_padconfig = 0U;
inline volatile std::uint32_t pin15_padconfig = 0U;
inline volatile std::uint32_t pin16_config = 5U;
inline volatile std::uint32_t pin17_config = 5U;
inline volatile std::uint32_t pin18_config = 5U;
inline volatile std::uint32_t pin19_config = 5U;
inline volatile std::uint32_t pin20_config = 5U;
inline volatile std::uint32_t pin21_config = 5U;
inline volatile std::uint32_t pin22_config = 5U;
inline volatile std::uint32_t pin23_config = 5U;
inline volatile std::uint32_t f_bus_actual = 150000000U;
inline volatile std::uint32_t f_cpu_actual = 600000000U;
inline bool interrupts_enabled = true;

}  // namespace fake_imxrt

#define CORE_PIN14_BIT 18U
#define CORE_PIN15_BIT 19U
#define CORE_PIN14_BITMASK (1UL << CORE_PIN14_BIT)
#define CORE_PIN15_BITMASK (1UL << CORE_PIN15_BIT)
#define GPIO6_GDIR fake_imxrt::gpio6_gdir
#define CORE_PIN14_CONFIG fake_imxrt::pin14_config
#define CORE_PIN15_CONFIG fake_imxrt::pin15_config
#define CORE_PIN14_PADCONFIG fake_imxrt::pin14_padconfig
#define CORE_PIN15_PADCONFIG fake_imxrt::pin15_padconfig
#define CORE_PIN16_CONFIG fake_imxrt::pin16_config
#define CORE_PIN17_CONFIG fake_imxrt::pin17_config
#define CORE_PIN18_CONFIG fake_imxrt::pin18_config
#define CORE_PIN19_CONFIG fake_imxrt::pin19_config
#define CORE_PIN20_CONFIG fake_imxrt::pin20_config
#define CORE_PIN21_CONFIG fake_imxrt::pin21_config
#define CORE_PIN22_CONFIG fake_imxrt::pin22_config
#define CORE_PIN23_CONFIG fake_imxrt::pin23_config
#define F_BUS_ACTUAL fake_imxrt::f_bus_actual
#define F_CPU_ACTUAL fake_imxrt::f_cpu_actual
#define F_CPU 600000000U

inline void __disable_irq() { fake_imxrt::interrupts_enabled = false; }
inline void __enable_irq() { fake_imxrt::interrupts_enabled = true; }
