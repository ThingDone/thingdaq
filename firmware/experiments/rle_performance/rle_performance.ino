// Isolated CPU microbenchmark: no capture DMA, no output pins, interrupts on.
#include <Arduino.h>
#include <algorithm>
#include <cstring>
#include "benchmark.h"
#include "variants.h"
using namespace rle_bench;
constexpr std::size_t kTrials = 31;
alignas(32) std::uint8_t dtcm_input[kBufferBytes], dtcm_output[kBufferBytes];
DMAMEM std::uint8_t ocram_input[kBufferBytes], ocram_output[kBufferBytes];
std::uint8_t reference[kBufferBytes];
std::uint32_t measurements[kTrials];
volatile std::uint32_t sink;
const char *patterns[] = {"constant", "runs32", "runs3", "runs2", "alternating", "random", "pulses", "last_change"};

std::uint32_t digest(const std::uint8_t *p, std::size_t n) {
  std::uint32_t value = 2166136261U;
  for (std::size_t i = 0; i < n; ++i) value = (value ^ p[i]) * 16777619U;
  return value;
}
void fill(std::uint8_t *p, unsigned pattern) {
  std::memset(p, 0xa5, kBufferBytes);
  std::uint32_t state = 0x12345678;
  for (std::size_t i = 0; i < kItems; ++i) {
    state = state * 1664525U + 1013904223U;
    std::uint16_t v = 0;
    switch (pattern) {
      case 0: v = 0x5aa5; break;
      case 1: v = (i / 32) & 1 ? 0xffff : 0; break;
      case 2: v = (i / 3) & 1 ? 0xaaaa : 0x5555; break;
      case 3: v = (i / 2) & 1 ? 0xffff : 0; break;
      case 4: v = i & 1 ? 0xffff : 0; break;
      case 5: v = state >> 16; break;
      case 6: v = i % 127 == 0 ? 1 : 0; break;
      case 7: v = i + 1 == kItems ? 1 : 0; break;
    }
    p[2 * i] = v; p[2 * i + 1] = v >> 8;
  }
}
std::uint16_t valueAt(const std::uint8_t *p, std::size_t i) {
  return p[2 * i] | (std::uint16_t(p[2 * i + 1]) << 8);
}
std::size_t oracle(const std::uint8_t *p) {
  std::size_t used = 0;
  for (std::size_t i = 0; i < kItems;) {
    const auto value = valueAt(p, i);
    std::size_t end = i + 1;
    while (end < kItems && valueAt(p, end) == value) ++end;
    if (used + 4 > kOutputLimit) return 0;
    const auto count = end - i;
    reference[used++] = count; reference[used++] = count >> 8;
    reference[used++] = value; reference[used++] = value >> 8;
    i = end;
  }
  return used;
}
std::uint32_t cycles() {
  __asm__ volatile("dsb\n\tisb" : : : "memory");
  return ARM_DWT_CYCCNT;
}
bool measure(const Variant &variant, unsigned pattern, unsigned region) {
  auto *input = region ? ocram_input : dtcm_input;
  auto *output = region ? ocram_output : dtcm_output;
  fill(input, pattern);
  const auto input_digest = digest(input, kBufferBytes);
  const auto bytes = oracle(input);
  std::memset(output, 0xa5, kBufferBytes);
  variant.function(input, output);  // Warm code/data cache before measurements.
  for (std::size_t trial = 0; trial < kTrials; ++trial) {
    // Outside timing; preserves warm-data conditions and detects every overwrite.
    std::memset(output, 0xa5, kBufferBytes);
    const auto start = cycles();
    const auto result = variant.function(input, output);
    measurements[trial] = cycles() - start;
    sink = digest(output, result.bytes <= kOutputLimit ? result.bytes : 0);
    if (result.error || result.bytes != bytes ||
        digest(input, kBufferBytes) != input_digest ||
        (bytes && std::memcmp(output, reference, bytes))) return false;
    for (std::size_t i = bytes ? bytes : kOutputLimit; i < kBufferBytes; ++i)
      if (output[i] != 0xa5) return false;
  }
  std::sort(measurements, measurements + kTrials);
  Serial.printf("%s,%s,%s,%u,%lu,%lu,%lu,%u,%lu,%lu\n", variant.name,
      patterns[pattern], region ? "ocram" : "dtcm", unsigned(kItems),
      (unsigned long)measurements[0], (unsigned long)measurements[kTrials / 2],
      (unsigned long)measurements[kTrials - 1], unsigned(bytes),
      (unsigned long)sink, (unsigned long)input_digest);
  return true;
}
void run_benchmark() {
  std::uint32_t primask;
  __asm__ volatile("mrs %0, primask" : "=r"(primask));
  if (primask || F_CPU_ACTUAL != 600000000U || tempmonGetTemp() >= 80.0f) {
    Serial.println("ERROR: clock/interrupt/temperature precondition"); return;
  }
  Serial.printf("cpu_hz=%lu,opt=%s,warm_cache=1,interrupts_enabled=1,trials=31,acquisition=0\n",
      (unsigned long)F_CPU_ACTUAL, RLE_BENCH_IMAGE);
  Serial.println("variant,pattern,region,items,min_cycles,median_cycles,max_cycles,encoded_bytes,encoded_digest,input_digest");
  static unsigned pass = 0;
  // Rotate kernel order between serial requests to expose ordering effects.
  for (unsigned p = 0; p < sizeof(patterns) / sizeof(patterns[0]); ++p)
    for (unsigned r = 0; r < 2; ++r)
      for (unsigned k = 0; k < kVariantCount; ++k)
        if (tempmonGetTemp() >= 80.0f) {
          Serial.println("ERROR: temperature cutoff"); return;
        } else if (!measure(variants[(k + pass) % kVariantCount], p, r)) {
          Serial.println("ERROR: output/input/canary mismatch"); return;
        }
  ++pass;
  Serial.println("done");
}
void setup() {
  Serial.begin(115200);
  ARM_DEMCR |= ARM_DEMCR_TRCENA;
  ARM_DWT_CTRL |= ARM_DWT_CTRL_CYCCNTENA;
}
void loop() { if (Serial.available() && Serial.read() == 'b') run_benchmark(); }
