// Standalone timing sketch; never runs acquisition or touches its DMA routes.
// Build with firmware/tools/m7_performance.py --benchmark --optimization O2.
#include <Arduino.h>
#include <algorithm>
#include "event_word.h"
#define STRINGIFY_IMPL(value) #value
#define STRINGIFY(value) STRINGIFY_IMPL(value)

extern "C" {
#define DECLARE_PACK(name) size_t name(const uint32_t *, const uint32_t *, size_t, uint8_t *, size_t)
DECLARE_PACK(pack_c_flash);
DECLARE_PACK(pack_c_itcm);
DECLARE_PACK(pack_cpp_flash);
DECLARE_PACK(pack_cpp_itcm);
}

constexpr size_t sample_count = 2024;
constexpr size_t repetitions = 101;
alignas(32) uint32_t dtcm_primary[sample_count], dtcm_auxiliary[sample_count];
DMAMEM uint32_t ocram_primary[sample_count], ocram_auxiliary[sample_count];
alignas(32) uint8_t output[sample_count * 2];
uint32_t measurements[repetitions];
thingdaq_event_word events{};
volatile uint32_t masked_events = 0;
volatile uint32_t sink = 0;
using Pack = size_t (*)(const uint32_t *, const uint32_t *, size_t, uint8_t *, size_t);

__attribute__((noinline)) void masked_publish(uint32_t bits) {
  uint32_t previous;
  __asm__ volatile("mrs %0, primask\n\tcpsid i" : "=r"(previous) : : "memory");
  masked_events |= bits;
  __asm__ volatile("msr primask, %0" : : "r"(previous) : "memory");
}

__attribute__((noinline)) uint32_t masked_take() {
  uint32_t previous;
  __asm__ volatile("mrs %0, primask\n\tcpsid i" : "=r"(previous) : : "memory");
  const uint32_t value = masked_events;
  masked_events = 0;
  __asm__ volatile("msr primask, %0" : : "r"(previous) : "memory");
  return value;
}

uint32_t cycles() {
  __asm__ volatile("dsb\n\tisb" : : : "memory");
  return ARM_DWT_CYCCNT;
}

uint32_t digest() {
  uint32_t value = 2166136261U;
  for (uint8_t byte : output) value = (value ^ byte) * 16777619U;
  return value;
}

void report(const char *operation, const char *region, uint32_t units) {
  std::sort(measurements, measurements + repetitions);
  Serial.printf("%s,%s,%lu,%lu,%lu,%lu,%lu\n", operation, region,
                static_cast<unsigned long>(units),
                static_cast<unsigned long>(measurements[0]),
                static_cast<unsigned long>(measurements[repetitions / 2]),
                static_cast<unsigned long>(measurements[repetitions - 1]),
                static_cast<unsigned long>(sink));
}

void packing(const char *name, Pack pack, const char *region,
             const uint32_t *primary, const uint32_t *auxiliary, uint32_t expected) {
  pack(primary, auxiliary, sample_count, output, sizeof(output)); // Warm caches.
  for (size_t trial = 0; trial < repetitions; ++trial) {
    const uint32_t start = cycles();
    const size_t written = pack(primary, auxiliary, sample_count, output, sizeof(output));
    measurements[trial] = cycles() - start;
    sink = digest(); // Validate/consume every output outside the timed interval.
    if (written != sample_count || sink != expected) {
      Serial.println("ERROR: kernel output mismatch");
      return;
    }
  }
  report(name, region, sample_count);
}

void run_benchmark() {
  Serial.printf("cpu_hz=%lu,opt=%s,warm_cache=1,interrupts_enabled=1,trials=101\n",
                static_cast<unsigned long>(F_CPU), STRINGIFY(THINGDAQ_BENCH_OPT));
  Serial.println("operation,data_region,units,min_cycles,median_cycles,max_cycles,digest");
  uint32_t state = 0x12345678U;
  for (size_t i = 0; i < sample_count; ++i) {
    state = state * 1664525U + 1013904223U;
    dtcm_primary[i] = ocram_primary[i] = state;
    state = state * 1664525U + 1013904223U;
    dtcm_auxiliary[i] = ocram_auxiliary[i] = state;
  }
  // Independent bit-position oracle, outside all timed regions.
  const uint8_t low_bits[] = {10, 17, 16, 11, 0, 2, 1, 3};
  const uint8_t high_bits[] = {23, 22, 17, 16, 26, 27, 24, 25};
  for (size_t i = 0; i < sample_count; ++i) {
    output[2 * i] = output[2 * i + 1] = 0;
    for (size_t bit = 0; bit < 8; ++bit) {
      output[2 * i] |= ((dtcm_primary[i] >> low_bits[bit]) & 1U) << bit;
      output[2 * i + 1] |= ((dtcm_auxiliary[i] >> high_bits[bit]) & 1U) << bit;
    }
  }
  const uint32_t expected = digest();
  const Pack functions[] = {pack_c_flash, pack_c_itcm, pack_cpp_flash, pack_cpp_itcm};
  const char *names[] = {"c_flash", "c_itcm", "cpp_flash", "cpp_itcm"};
  for (size_t i = 0; i < 4; ++i) {
    packing(names[i], functions[i], "dtcm", dtcm_primary, dtcm_auxiliary, expected);
    packing(names[i], functions[i], "ocram", ocram_primary, ocram_auxiliary, expected);
  }
  for (bool atomic : {false, true}) {
    for (size_t trial = 0; trial < repetitions; ++trial) {
      uint32_t sum = 0;
      const uint32_t start = cycles();
      for (size_t i = 0; i < 256; ++i) {
        if (atomic) {
          thingdaq_event_publish(&events, 1);
          sum += thingdaq_event_take(&events);
        } else {
          masked_publish(1);
          sum += masked_take();
        }
      }
      measurements[trial] = cycles() - start;
      sink = sum;
      if (sum != 256) { Serial.println("ERROR: event mismatch"); return; }
    }
    report(atomic ? "atomic_publish_take" : "primask_publish_take", "dtcm", 256);
  }
  Serial.println("done");
}

void setup() {
  Serial.begin(115200);
  ARM_DEMCR |= ARM_DEMCR_TRCENA;
  ARM_DWT_CTRL |= ARM_DWT_CTRL_CYCCNTENA;
}

void loop() {
  if (Serial.available() && Serial.read() == 'b') run_benchmark();
}
