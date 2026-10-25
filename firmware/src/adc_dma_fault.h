#pragma once

#include <array>
#include <cstddef>
#include <cstdint>

namespace thingdaq::adc_capture::fault_trace {
// Private GPIO-RLE STATUS suffix; never part of the public protocol.
#if defined(THINGDAQ_EXPERIMENT_GPIO_RLE) || defined(THINGDAQ_ADC_DMA_FAULT_DIAGNOSTIC)
inline constexpr std::size_t kWords = 3;
inline volatile std::uint32_t words[kWords]{};
// Opt-in requests 0xFADC0001..0030 read two immutable diagnostic words.
// Normal STATUS retains its original 12-byte summary and frame-size limit.
#if defined(THINGDAQ_ADC_DMA_FAULT_DIAGNOSTIC)
inline constexpr std::size_t kDetailWords = 112;
inline volatile std::uint32_t stop_phase = 0U;
#else
inline constexpr std::size_t kDetailWords = 96;
#endif
inline constexpr std::uint32_t kDetailRequestBase = 0xFADC0000U;
#if defined(THINGDAQ_ADC_DMA_FAULT_DIAGNOSTIC) && defined(__IMXRT1062__)
// This image borrows the idle OCRAM checksum-benchmark bytes. Access bytes
// explicitly, so no uint32_t object lifetime or aliasing is assumed. Do not
// run a checksum benchmark between acquisition prepare and trace retrieval.
std::uint8_t *diagnosticBytes();
struct DiagnosticWord {
  std::size_t index;
  operator std::uint32_t() const {
    const volatile std::uint8_t *p = diagnosticBytes() + index * 4U;
    return p[0] | (std::uint32_t{p[1]} << 8U) |
           (std::uint32_t{p[2]} << 16U) | (std::uint32_t{p[3]} << 24U);
  }
  void operator=(std::uint32_t value) const {
    volatile std::uint8_t *p = diagnosticBytes() + index * 4U;
    for (std::size_t i = 0; i < 4; ++i) p[i] = static_cast<std::uint8_t>(value >> (i * 8U));
  }
};
struct DiagnosticDetail {
  DiagnosticWord operator[](std::size_t index) const { return {index}; }
};
inline constexpr DiagnosticDetail detail{};
#else
inline volatile std::uint32_t detail[kDetailWords]{};
#endif
// Published only after triggers, DMA requests and completion IRQs are stopped.
// Successful captures expose their already-recorded phase history too, without
// adding any work to the acquisition ISR or reporting a synthetic fault.
inline bool stopped_progress = false;
// Two most recent accepted progress observations, oldest first. Each holds
// software base generation, packed indices, end DWT cycles, pending DMA IRQs,
// packed 16-bit CITER values (ADC0 low), and observation-start DWT cycles.
// Sequential reads are NOT an atomic hardware snapshot. The timestamps bound
// their sampling interval, so phase comparisons can account for read latency.
// Only the serialized DMA service writes this; prepare resets it while stopped.
inline constexpr std::size_t kProgressWords = 6;
inline std::array<std::uint32_t, 2 * kProgressWords> progress_history{};
// First observation at/after each base generation. These sparse checkpoints
// distinguish an initial phase offset, gradual drift and a later step without
// an unbounded trace or a per-capture allocation. Unreached records stay zero.
inline constexpr std::array<std::uint32_t, 8> kPhaseGenerations{
    0U, 1U, 2U, 4U, 16U, 256U, 1024U, 2048U};
inline std::array<std::uint32_t, kPhaseGenerations.size() * kProgressWords>
    phase_history{};
inline std::size_t next_phase = 0U;
inline void rememberProgress(std::uint32_t generation, std::uint32_t indices,
                             std::uint32_t cycles, std::uint32_t pending,
                             std::uint32_t remaining, std::uint32_t started) {
  if (words[0] != 0U) return;
  for (std::size_t i = 0; i < kProgressWords; ++i)
    progress_history[i] = progress_history[i + kProgressWords];
  progress_history[6] = generation;
  progress_history[7] = indices;
  progress_history[8] = cycles;
  progress_history[9] = pending;
  progress_history[10] = remaining;
  progress_history[11] = started;
  while (next_phase < kPhaseGenerations.size() &&
         generation >= kPhaseGenerations[next_phase]) {
    for (std::size_t i = 0; i < kProgressWords; ++i)
      phase_history[next_phase * kProgressWords + i] =
          progress_history[kProgressWords + i];
    ++next_phase;
  }
}
inline void retainProgress() {
  for (std::size_t i = 0; i < progress_history.size(); ++i)
    detail[36 + i] = progress_history[i];
  for (std::size_t i = 0; i < phase_history.size(); ++i)
    detail[48 + i] = phase_history[i];
}
inline void retainStoppedProgress(std::uint32_t priorities = 0U,
                                  std::uint32_t adc1_mux = 0U,
                                  std::uint32_t etc_dma = 0U,
                                  std::uint32_t etc_control = 0U) {
  if (words[0] != 0U || stopped_progress) return;
  // Healthy record word 0 is DCHPRI0..3 (low byte first). Fault records keep
  // their existing DADDR interpretation; the summary reason distinguishes them.
  detail[0] = priorities;
  detail[1] = adc1_mux;
  detail[2] = etc_dma;
  detail[3] = etc_control;
  retainProgress();
  stopped_progress = true;
}
inline void reset() {
  stopped_progress = false;
#if defined(THINGDAQ_ADC_DMA_FAULT_DIAGNOSTIC)
  stop_phase = 0U;
#endif
  for (std::size_t i = 0; i < kWords; ++i) words[i] = 0;
  for (std::size_t i = 0; i < kDetailWords; ++i) detail[i] = 0;
  progress_history.fill(0U);
  phase_history.fill(0U);
  next_phase = 0U;
}
inline std::array<std::uint32_t, kWords> snapshot(std::uint32_t request_id = 0) {
  std::array<std::uint32_t, kWords> result{};
  // The ISR publishes reason last. Once nonzero, the record stays immutable
  // until the next stopped prepare. Main cannot race that prepare operation.
  if (words[0] != 0 || stopped_progress) {
    const std::uint32_t page = request_id - kDetailRequestBase;
    if (page >= 1U && page <= kDetailWords / 2U) {
      result[0] = (words[0] & 0x7FU) | 0x80U | (page << 8U);
      result[1] = detail[(page - 1U) * 2U];
      result[2] = detail[(page - 1U) * 2U + 1U];
    } else if (words[0] != 0) {
      for (std::size_t i = 0; i < kWords; ++i) result[i] = words[i];
    }
  }
  return result;
}
#else
inline constexpr std::size_t kWords = 0;
inline void reset() {}
inline void retainStoppedProgress(std::uint32_t = 0U) {}
inline std::array<std::uint32_t, 0> snapshot(std::uint32_t = 0) { return {}; }
#endif
inline constexpr std::size_t kBytes = kWords * sizeof(std::uint32_t);
}  // namespace thingdaq::adc_capture::fault_trace
