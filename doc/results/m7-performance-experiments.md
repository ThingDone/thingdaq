---
type: result
title: M7 C, Atomics, Optimization and ITCM Experiments
created: 2026-09-18
tags:
  - thingdaq
  - firmware
  - performance
related:
  - '[[firmware-runtime-hardening]]'
  - '[[firmware-resource-map]]'
---

# M7 C, atomics, optimization and ITCM experiments

This is a compiler and correctness experiment, **not a measured hardware speedup**.
No local Teensy serial device was attached; no image was uploaded during this
compiler-only phase. The subsequent [remote hardware test](m7-hardware-tests.md)
encountered a baseline USB disconnect followed by programming failures, so timing
remains unmeasured. The release
build keeps its existing C++ packer, optimization and synchronization behavior.
The experimental C packer is enabled only by an explicit build definition.

## Results

Pinned target: Teensy 4.0, core 1.62.0, Arm GNU 15.2.1, 450 MHz, USB Serial.
The matrix changes whole-firmware optimization and the dual-bank packing kernel.
LTO is off. Libc is held constant: the runner explicitly removes the nano-libc
selection otherwise implicit in the core's `osstd` menu. Existing per-function
attributes remain, including the checksum CRC functions' explicit `O3` and
several ISR functions' `Os`; this is not a claim that every function follows
the global flag.

| Global optimization | Packer | ITCM code bytes | Stack/locals bytes | Existing build gates |
| --- | --- | ---: | ---: | --- |
| `-Os` | Original C++ / C flash | 28,984 | 34,496 | Rejected: Adler32 code-size pin |
| `-Os` | C ITCM | 29,208 | 34,496 | Rejected: Adler32 code-size pin |
| `-O1` | Original C++ / C flash | 32,712 | 34,496 | Rejected: Adler32 code-size pin |
| `-O1` | C ITCM | 32,920 | 1,728 | Rejected: stack floor |
| `-O2` | Original C++ / C flash | 32,520 | 34,464 | Passed |
| `-O2` | C ITCM | 32,744 | 34,464 | Passed; 24 bytes before next bank |
| `-O3` | Original C++ / C flash | 37,720 | 1,696 | Rejected: stack floor |
| `-O3` | C ITCM | 37,944 | 1,696 | Rejected: stack floor |

Every row keeps the 200-frame packet pool and 4,096-byte OCRAM heap margin.
The 32,768-byte minimum stack/locals floor is unchanged. Rejected variants have
no success manifest, and `--variant` exits nonzero. `--matrix` records expected
rejections and completes the comparison; it does not qualify those images.
The Adler32 size pin expects 120 bytes; `-Os` emits 98 and `-O1` emits 108.
Those size changes are not correctness failures, but require explicit resource
baseline review before the normal build can accept them. No gate was relaxed.

The linker allocates ITCM in 32 KiB banks taken from the same FlexRAM pool as
DTCM. Consequently a small code increase can remove **32 KiB** from available
stack space. The baseline already executes ordinary `.text` in ITCM; `.flashmem`
functions are the candidates for movement. This matches the pinned core's
`imxrt1062.ld` and PJRC's [memory allocation documentation](https://www.pjrc.com/store/teensy40.html).

### C versus C++

The opt-in C11 kernel in `firmware/src/gpio_pack_c.c` implements the existing
GPIO2/GPIO1 wire mapping behind a small C ABI. `gpio_dual_bank_packer.cpp` forwards
to it only with `THINGDAQ_EXPERIMENT_C_PACKER=1`. The original implementation is
retained as the control and correctness oracle.

Compiling the **same kernel source** as C11 and C++17 gives byte-identical M7
machine code for every optimization and placement combination:

| Optimization | C bytes | C++ bytes | Flash versus ITCM kernel bytes |
| --- | ---: | ---: | --- |
| `-Os` | 214 | 214 | Identical |
| `-O1` | 206 | 206 | Identical |
| `-O2` | 218 | 218 | Identical |
| `-O3` | 218 | 218 | Identical |

The original C++ production kernel is 240 bytes at `-O2`; the experimental
kernel is 218 bytes plus a 4-byte forwarding function in flash. The experiment
writes the two bytes directly instead of constructing a combined 16-bit value.
The identical C/C++ control shows that this reduction comes from the source
expression change, not the language. Code size alone is not timing evidence.

### Atomics versus global interrupt masking

`firmware/experiments/m7_performance/event_word.c` provides an aligned 32-bit,
CPU-only, coalescing notification word. Producers use release `fetch_or`;
consumers use acquire `exchange(0)`. GCC emits `LDREX`, `STREX`, a retry branch
and `DMB`, with no `CPSID`, PRIMASK manipulation or undefined library helpers.
A compile-time assertion requires always-lock-free 32-bit operations.
See [GCC's atomic built-ins](https://gcc.gnu.org/onlinedocs/gcc/_005f_005fatomic-Builtins.html)
and the [Arm M7 guide, exclusive accesses](https://documentation-service.arm.com/static/61efd8352dd99944d05142d1).

The contract matters: repeated bits coalesce, so this cannot count completed
buffers. Payload ownership must be established separately. Acquire/release
orders CPU publication; it does not invalidate DMA caches, serialize peripheral
register transactions or make multiple fields one atomic snapshot. Exclusive
retry loops are lock-free, not a bounded execution-time guarantee. The target
benchmark compares uncontended operation cost; it does not establish worst-case
interrupt latency or retry rates under nested IRQs.

The existing production guards remain for these reasons:

| Guarded operation | Why a word-level atomic is insufficient |
| --- | --- |
| ADC/GPIO ring ownership | Buffer state, generation, destination and loss accounting change together. Requires a redesigned ownership protocol or proven SPSC handoff. |
| DMA/trigger start and stop | Multi-register hardware sequencing, pending IRQ handling and descriptor lifetime must agree. |
| Hardware/raw snapshots | Several counters and hardware fields form a coherent record. Independent atomic loads would change that contract. |
| Watchdog unlock/refresh | Hardware access ordering/window requirements are separate from shared-memory atomics. |
| DWT setup/startup stack painting | Hardware setup and startup invariants, not an event publication problem. |

A CPU event word is a candidate for a future ISR-to-main notification boundary,
not a replacement for `dma::CriticalSection`. Do not put a spinning mutex in an
ISR that can preempt its owner. A future SPSC queue may need only acquire/release
loads and stores, without an exclusive RMW, if its ownership constraints hold.

## Reproducing the experiments

From the repository root:

```bash
python3 firmware/tools/m7_performance.py --objects
python3 firmware/tools/m7_performance.py --matrix
python3 firmware/tools/m7_performance.py --variant --optimization O2 --kernel c-itcm
python3 firmware/tools/m7_performance.py --benchmark --optimization O2
```

`--objects` compares C/C++ section bytes and inspects atomic disassembly.
`--matrix` builds all 12 complete firmware variants using the existing builder
and resource gates. The source fingerprint, option selection and builder hash
produce separate firmware identities. All binaries, logs, linker maps, assembly
and scratch output stay in ignored `firmware/build/m7-performance/`. The tracked
[evidence snapshot](m7-performance-evidence.json) includes source/tool hashes,
linked kernel addresses, image hashes, memory measurements and gate outcomes.
For matching full-firmware build timestamps after committing the sources, set
`SOURCE_DATE_EPOCH` to the archived `build_timestamp_epoch`.

`--benchmark` builds a **separate microbenchmark sketch**, not acquisition
firmware. Select `Os`, `O1`, `O2` or `O3`; all four have been build-checked. Its
manifest verifies code and data placement from the ELF. Once that sketch is
programmed onto an available test board, send ASCII `b` over its USB serial port.
It prints CSV with 101-trial minimum/median/maximum DWT cycle counts:

- Four kernel variants: C/C++ crossed with flash/ITCM.
- Each packs 2,024 samples from DTCM and OCRAM into DTCM.
- Two notification implementations: PRIMASK save/restore versus atomic OR/exchange.
- Kernel output is checked against an independent bit-position oracle outside
  the timed interval. Event totals are also checked. A mismatch prints `ERROR`.

The packing `units` column is samples; the event `units` column is publish/take
pairs (256). Divide cycles by units for cycles/sample or cycles/pair. Timing
includes function call and DWT fence/read overhead, with no subtraction. Caches
are warmed and interrupts remain enabled except during the individual PRIMASK
operations. Maximum observations include incidental interrupts and serial
activity. OCRAM input is CPU-filled and warm; it does not simulate the cache
state immediately after DMA invalidation. These results must be followed by
physical combined-acquisition tests, stack watermark sampling, CPU utilization,
loss counters and worst-case ISR latency before selecting a production variant.

## Validation and next decisions

Firmware regression suite: 203 passed, 835 subtests passed, one evidence-dependent
test skipped. New tests compile the C kernel with all four optimization levels,
check mapping/tails/nulls/capacity/overflow/sentinels, run the existing auxiliary
join/packer suite through the C ABI, and exercise 100,000 release/acquire payload
handoffs plus concurrent independent bit publishers. Host concurrency tests and
M7 instruction inspection complement each other; neither proves on-board timing.

The default release build and all three `-O2` experiment builds pass the unchanged
resource gates. All four standalone benchmark builds verify expected function
and data placement. No whole-firmware `-O3` image meets the stack floor.

The next hardware comparison should start with `-O2` flash versus ITCM packing.
Before adding more ITCM code, move enough genuinely cold code to flash to recover
bank headroom. Then measure selective per-function optimization. C can be useful
for module boundaries, but this kernel supplies no evidence for an inherent C
speed advantage. A DMA queue migration needs its own state-transition proof and
interrupt-interleaving tests before removing any existing ring guard.
