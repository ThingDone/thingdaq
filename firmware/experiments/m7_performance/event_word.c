#include "event_word.h"

_Static_assert(__atomic_always_lock_free(sizeof(uint32_t), 0),
               "32-bit event operations must never use libatomic locks");

void thingdaq_event_publish(thingdaq_event_word *word, uint32_t bits) {
  __atomic_fetch_or(&word->bits, bits, __ATOMIC_RELEASE);
}

uint32_t thingdaq_event_take(thingdaq_event_word *word) {
  return __atomic_exchange_n(&word->bits, 0U, __ATOMIC_ACQUIRE);
}
