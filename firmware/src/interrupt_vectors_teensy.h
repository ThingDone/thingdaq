#pragma once

#include <cstddef>

#include "board_config.h"
#include "interrupt_guard_teensy.h"

namespace thingdaq::interrupts {

// Runtime ownership complements the static board interrupt allocation table:
// legacy and paired GPIO are different clients of the same reserved vector.
// Claim before configuring a source, and release only after stopping it.
class VectorLease;
inline constexpr std::size_t kVectorSlotCount =
    sizeof(board::kInterruptAllocations) /
    sizeof(board::kInterruptAllocations[0]);
inline const VectorLease *g_vector_owners[kVectorSlotCount]{};

class VectorLease final {
 public:
  using Handler = void (*)();

  explicit constexpr VectorLease(IRQ_NUMBER_t irq) : irq_(irq) {}
  VectorLease(const VectorLease &) = delete;
  VectorLease &operator=(const VectorLease &) = delete;

  bool available() const {
    Guard guard;
    const std::size_t slot = slotIndex();
    return slot != kVectorSlotCount && g_vector_owners[slot] == nullptr;
  }

  bool owned() const {
    Guard guard;
    const std::size_t slot = slotIndex();
    return slot != kVectorSlotCount && g_vector_owners[slot] == this;
  }

  bool claim(Handler handler) {
    Guard guard;
    const std::size_t slot = slotIndex();
    if (handler == nullptr || slot == kVectorSlotCount ||
        g_vector_owners[slot] != nullptr) {
      return false;
    }
    NVIC_DISABLE_IRQ(irq_);
    NVIC_CLEAR_PENDING(irq_);
#if defined(THINGDAQ_HOST_REGISTER_TEST)
    previous_ = fake_imxrt::interrupt_vectors[irq_];
#else
    previous_ = _VectorsRam[static_cast<std::size_t>(irq_) +
                            board::kArmExceptionVectorCount];
#endif
    g_vector_owners[slot] = this;
    attachInterruptVector(irq_, handler);
    return true;
  }

  void release() {
    Guard guard;
    const std::size_t slot = slotIndex();
    if (slot == kVectorSlotCount || g_vector_owners[slot] != this) {
      return;
    }
    NVIC_DISABLE_IRQ(irq_);
    NVIC_CLEAR_PENDING(irq_);
    attachInterruptVector(irq_, previous_);
    g_vector_owners[slot] = nullptr;
    previous_ = nullptr;
  }

 private:
  constexpr std::size_t slotIndex() const {
    for (std::size_t slot = 0U; slot < kVectorSlotCount; ++slot) {
      if (board::kInterruptAllocations[slot].irq == irq_) {
        return slot;
      }
    }
    return kVectorSlotCount;
  }

  const IRQ_NUMBER_t irq_;
  Handler previous_ = nullptr;
};

}  // namespace thingdaq::interrupts
