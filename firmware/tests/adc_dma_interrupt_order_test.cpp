// Deterministic register ordering around the production DMA service functions.
#include <array>
#include <cassert>
#include <cstddef>
#include <cstdint>
#include <string>

constexpr std::size_t kDmaPipelineDepth = TEST_PIPELINE_DEPTH;
constexpr std::size_t kInvalidPipelineIndex = kDmaPipelineDepth;
constexpr std::size_t kPairDispatchConverter = 1;
constexpr std::uint32_t kDmaAlignmentWaitCycles = 6000;
constexpr std::uint32_t kAdcDmaChannelMask = 3;
namespace board {
struct Converter { unsigned edma_channel; };
constexpr std::array<Converter, 2> kAdcConverterConfigurations{{{0}, {1}}};
}
bool g_hardware_prepared = true;
bool g_faulted = false;
unsigned g_stale_interrupts = 0;
unsigned g_epoch = 1;
std::uint32_t DMA_INT = 2;
std::uint32_t DMA_ERR = 0;
std::array<std::size_t, 2> active{1, 1};
unsigned completions = 0;
bool inject_before_observation = false;
bool inject_during_processing = false;
bool reject_completion = false;
struct Ring {
  unsigned errors = 0;
  void recordDmaError(unsigned, unsigned) { ++errors; }
} g_ring;
struct ClearInterrupt {
  void operator=(unsigned channel) { DMA_INT &= ~(1U << channel); }
} DMA_CINT;
struct Clock {
  std::uint32_t ticks = 0;
  operator std::uint32_t() { return ticks++; }
} ARM_DWT_CYCCNT;
void barrier() {}
void recordFaultTrace(std::uint32_t, std::uint32_t = 0, std::uint32_t = 0,
                      std::uint32_t = 0, std::uint32_t = 0) {}
void saturatingIncrement(unsigned &value) { ++value; }
std::uint32_t channelMask(std::size_t converter) { return 1U << converter; }
std::size_t hardwarePipelineIndex(std::size_t converter) {
  if (inject_before_observation) {
    // Another generation finishes after CINT but before progress is sampled.
    ++active[0];
    ++active[1];
    DMA_INT |= 2U;
    inject_before_observation = false;
  }
  return active[converter];
}
bool processInferredPairCompletion() {
  if (reject_completion) return false;
  assert(active[0] > 0 && active[1] > 0);
  --active[0];
  --active[1];
  ++completions;
  if (inject_during_processing) {
    ++active[0];
    ++active[1];
    DMA_INT |= 2U;
    inject_during_processing = false;
  }
  return true;
}

// These are extracted verbatim from adc_dma_capture_teensy.cpp by the test.
// Only register IO, progress observation and ring callbacks are simulated.
#include "adc_dma_service_under_test.h"

int main(int argc, char **argv) {
  assert(argc == 2);
  const std::string scenario = argv[1];
  bool expected_ok = true;
  unsigned expected_completions = 1;
  unsigned expected_errors = 0;
  std::array<std::size_t, 2> remaining{0, 0};
  if (scenario == "latched-accounted-completion") {
    inject_before_observation = true;
    expected_completions = 2;
  } else if (scenario == "new-completion-during-processing") {
    inject_during_processing = true;
    expected_completions = 2;
  } else if (scenario == "no-new-progress") {
    active = {0, 0};
    expected_completions = 0;
  } else if (scenario == "adc0-one-ahead" || scenario == "adc1-one-ahead" ||
             scenario == "adc0-ahead-no-common" || scenario == "adc1-ahead-no-common") {
    const bool first = scenario.find("adc0") == 0;
    const bool no_common = scenario.find("no-common") != std::string::npos;
    active = first ? std::array<std::size_t, 2>{2, 1}
                   : std::array<std::size_t, 2>{1, 2};
    remaining = first ? std::array<std::size_t, 2>{1, 0}
                      : std::array<std::size_t, 2>{0, 1};
    if (no_common) { active = remaining; expected_completions = 0; }
  } else if (scenario == "skew" || scenario == "outside-window" ||
             scenario == "invalid-destination" || scenario == "dma-error") {
    if (scenario == "skew") active = {2, 0};
    if (scenario == "outside-window")
      active = {kDmaPipelineDepth - 1, kDmaPipelineDepth - 1};
    if (scenario == "invalid-destination")
      active = {kDmaPipelineDepth, kDmaPipelineDepth};
    if (scenario == "dma-error") { active = {0, 0}; DMA_ERR = 1; }
    expected_ok = false;
    expected_completions = 0;
    expected_errors = 2;
  } else if (scenario == "ring-rejection") {
    reject_completion = true;
    expected_ok = false;
    expected_completions = 0;
  } else {
    assert(scenario == "ordinary-completion");
  }
  assert(servicePendingDmaPair() == expected_ok);
  assert(g_faulted == !expected_ok);
  assert(completions == expected_completions);
  assert(g_ring.errors == expected_errors);
  if (expected_ok) {
    assert(active == remaining);
    assert((DMA_INT & 2U) == 0);
    if (remaining[0] != remaining[1]) {
      // A later dispatch accounts the deferred pair exactly once. No callback
      // may run until both channels actually completed that generation.
      active = {1, 1};
      DMA_INT |= 2U;
      assert(servicePendingDmaPair());
      assert(completions == expected_completions + 1);
      assert(active[0] == 0 && active[1] == 0 && g_ring.errors == 0);
    }
  }
}
