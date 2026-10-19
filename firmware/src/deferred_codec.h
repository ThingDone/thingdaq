#pragma once
#include <array>
#include <cstdint>
namespace thingdaq::deferred_codec {
// Public v3 STATUS exposes these counters. Private diagnostic pages remain
// available to legacy experiment clients without changing v1/v2 STATUS.
inline constexpr std::uint32_t kRequestBase = 0xFDEC0000U;
struct Counters {
  std::uint32_t completed = 0, raw = 0, deadline_drops = 0, resource_drops = 0;
  std::uint64_t work_ticks = 0;
  std::uint32_t max_work_ticks = 0, max_age_ticks = 0;
};
inline std::array<Counters, 2> counters{};
#if defined(THINGDAQ_DEFERRED_CODECS)
inline std::array<std::uint32_t, 3> page(std::uint32_t request) {
  const auto p = request - kRequestBase;
  if (p >= 7U && p <= 10U) {
#if defined(__IMXRT1062__)
    // Pinned Teensy core reserves this OCRAM area for its persistent fault
    // record. Read only; includes length/IPSR/CFSR/HFSR/addresses/PC and CRC.
    const auto *fault = reinterpret_cast<const volatile std::uint32_t *>(0x2027FF80U);
    const auto offset = (p - 7U) * 3U;
    return {fault[offset], fault[offset + 1U], offset + 2U < 11U ? fault[offset + 2U] : 0U};
#else
    return {};
#endif
  }
  if (p < 1 || p > 6) return {};
  const auto &c = counters[(p - 1) / 3];
  switch ((p - 1) % 3) {
    case 0: return {c.completed, c.raw, c.deadline_drops};
    case 1: return {c.resource_drops, static_cast<std::uint32_t>(c.work_ticks),
                   static_cast<std::uint32_t>(c.work_ticks >> 32)};
    default: return {c.max_work_ticks, c.max_age_ticks, 80000U};
  }
}
#endif
}
