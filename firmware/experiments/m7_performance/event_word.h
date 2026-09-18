#pragma once
#include <stdint.h>

#ifdef __cplusplus
extern "C" {
#endif

/* CPU-only, naturally aligned normal RAM. Every concurrent access must use
 * these functions. Coalesces notifications: this is not a counter or queue.
 * Does not grant ownership of payloads, maintain DMA caches, or make a
 * multi-field snapshot coherent. No ISR spinlock waits for foreground code. */
typedef struct { uint32_t bits; } thingdaq_event_word;
void thingdaq_event_publish(thingdaq_event_word *word, uint32_t bits);
uint32_t thingdaq_event_take(thingdaq_event_word *word);

#ifdef __cplusplus
}
#endif
