#pragma once

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
