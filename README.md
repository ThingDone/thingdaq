# teensy_daq

This project is going to run on a teensy 4.0.

We want it make a firmware based DAQ we can use on multiple projects for different customers. The idea is we are going to have python scripts that want to read data from live systems. 

We want to support the following:
1. Dual ADCs running interleaved on pins A0 and A1 at 1MHz. We want them running via DMA interlaved on some rotating buffers. 
2. 8 pins (accessible from headers on a breadboard) read out at 4MHz. Ideally we want to read this out via dma or potentially some interrupt driven system.
3. We default to sending information, but we need a command set to enable/disable different functionality
4. We want a native python api for detecting and controlling our teensy daq
5. We will support a test mode that sends out patterns for validating that we are reassembling the data properly.

Data format:
In the future, we may accept some commands, but for now we are encapselating the data we send into messages. Here is the format:

*Entire set of message must be a multiple of 512 bytes*
Header 4bytes - 0xdeadbeef
Type 2 bytes  - (0->ADC, 1->GPIO)
Size 2 bytes  - size of payload
Time 4 bytes  - 8x microseconds for resynchronization
payload  0->size byte
checksum 4bytes - Standard Adler-32

Ideally it will show up as a serial port in windows, and we can have python read out the different packets of information. It can then reassemble it according to time, and also determine if some time slice has dropped.

The command format should be similar but do not have to be multiples of 512 byte:
Header 4bytes - 0xdeadbeef
Type 2 bytes  - Command Type
Size 2 bytes  - size of payload
payload  0->size byte
checksum 4bytes - Standard Adler-32

# Testing
We will leaverage /home/bill/agents/fw_experiments/docs/guides/new-firmware-projects.md for building and testing our project here.

We want to evaluate the following:
1. Test that our firmware works and can be carefully controlled via python.
2. We will ensure our python api is well documented.
3. We will have a benchmark on how much usb bandwidth is used.
4.

## Repository layout

- `firmware/` contains the Teensy 4.0 sketch boundary, portable C++ modules,
  local build tooling, and firmware-focused host tests.
- `daq_api/` contains the installable `teensy_daq` Python package in a
  `src/` layout and its test suite.
- `doc/` contains structured architecture, protocol, decision, reference, and
  result artifacts. Start with `doc/README.md` and
  `doc/architecture/system-overview.md`.

Generated builds, captures, virtual environments, benchmark scratch data,
credentials, and language-tool caches are ignored. Small deterministic test
fixtures remain tracked under the firmware or Python test trees.

Every Markdown artifact under `doc/` must begin with YAML front matter
containing `type`, `title`, `created`, `tags`, and `related`, and must use
`[[Wiki-Links]]` for related project documents.

## Reproducible local setup

The firmware build is intentionally fixed to Teensy 4.0, USB Serial, 600 MHz,
standard `-O2`, and Teensy core 1.62.0. The helper refuses a different installed
core, performs a clean all-warnings compile with the complete
`teensy:avr:teensy40:usb=serial,speed=600,opt=o2std` FQBN, and records the
Arduino CLI, compiler, resolved menu properties, deterministic source/build
identity, source-input Git state, reproducible UTC timestamp policy, Flash/RAM
usage, command, and SHA-256 hashes in a gitignored build manifest. The exported
artifacts include the HEX, ELF, and linker map needed for pre-upload review;
ELF inspection also proves the packet banks, checksum buffers/tables, GPIO
clock diagnostic cache line, paired ADC ring/sink/two-channel TCD bank, raw
GPIO ring/sink/TCD bank, and packed GPIO ring occupy their claimed regions:

```bash
python3 firmware/tools/build_firmware.py
```

For Python API development, install the private local distribution and its
development tools from the repository root. NumPy remains an explicit optional
feature rather than a runtime requirement:

```bash
python3 -m venv .venv
.venv/bin/python -m pip install --editable './daq_api[dev,numpy]'
```

The `teensy-daq-local` distribution name and `Private :: Do Not Upload`
classifier are deliberate publication guards. Rename and review the
distribution metadata before any future package-index release.

## Protocol contract

Protocol v1 uses one generated, explicitly little-endian frame contract for
firmware and Python. ADC/GPIO frames are fixed at 4,096 bytes; bounded control
frames use generated INFO, CONFIGURE, START, GET_STATUS, STOP, RESET_STATS,
and optional PING command IDs, echoed request IDs, typed responses, explicit
run identity, and capability bits over the same resynchronizable envelope. The
normative specification is
`doc/protocol/protocol-v1.md`, with rationale in
`doc/decisions/adr-001-wire-protocol.md` and the production checksum decision
in `doc/decisions/adr-002-checksum-selection.md`.

Regenerate the Python constants, C++ constants, and shared golden frames—or
check that tracked output has not drifted—with:

```bash
python3 tools/generate_protocol.py
python3 tools/generate_protocol.py --check
```

Phase 05 adds stateless firmware candidates for Adler-32, CRC-32C, and
CRC-32/ISO-HDLC behind one allocation-free checksum interface. INFO advertises
all three for data frames, CONFIGURE selects one, and each data header carries
the selected ID. INFO exposes the generated default in IDLE and the applied
selection in CONFIGURED/RUNNING; STATUS and Python ADC/GPIO block metadata
repeat it. Every command and response remains unambiguously protected by
bootstrap Adler-32. The fixed Phase 05 policy retained Adler-32 as the
production data default because CRC-32C exceeded the relative STATUS-p99 gate
and CRC-32/ISO-HDLC exceeded the relative STATUS-maximum gate; both CRCs remain
advertised and decodable. Reconfiguration returns `BUSY` until prior-run frames
have drained. The pinned-core, Cortex-M7, i.MX RT1062,
FastCRC, and hardware-accelerator findings are recorded in
`doc/research/checksum-candidates.md`; notably, the general-memory DCP computes
CRC-32/MPEG-2 rather than either evaluated CRC and is not used.

The optional IDLE-only `CHECKSUM_BENCHMARK` command measures those same narrow
firmware implementations with the verified 600 MHz DWT counter. It calibrates
and subtracts read overhead, excludes interrupts from each timed interval,
publishes an optimization-proof digest, and reports raw/net cycles, processed
bytes, Q16.16 cycles/byte, decimal MB/s, projected CPU at 8.1 MB/s, recurring
cache setup, and code/table/RAM cost. Vectors cover empty input, canonical
`123456789`, aligned 64/512-byte buffers, and an actual 4,092-byte framed
header-plus-payload. Separate 4,096-byte buffers exercise native DTCM and
DMA-visible OCRAM in hot and meaningful cold-invalidated states. The protocol
and method are specified in `doc/protocol/protocol-v1.md`.

Phase 06 adds an optional IDLE-only `GPIO_CLOCK_DIAGNOSTIC` command. It drives
the fixed 24 MHz PERCLK → PIT0 → XBARA1 rising-edge request → DMAMUX → eDMA
channel 2 path at exact divisors from 1 kHz through the immutable 4 MHz
production rate, without remapping or reading D6-D13. The response exposes the
clock gates, timer, XBAR, DMAMUX, eDMA/TCD registers, 600 MHz DWT interval,
scheduled/sample counts, route IDs, and typed hardware errors. The accepted
route and rejected dual-edge alternatives are recorded in
`doc/decisions/adr-003-gpio-clock-dma.md`.

Phase 07 fixes one compile-time ADC route table and now applies it during
bounded BOOT initialization:
logical ADC0 is A0 through NXP ADC1 channel 7, and logical ADC1 is A1 through
NXP ADC2 channel 8. The same tuples own ADC_ETC queues 0/4, XBAR outputs
103/107, and eDMA channels 0/1 with DMAMUX sources 24/88. The selected clock,
500 ns trigger-delay arithmetic, initial 12-bit conversion budget, and explicit
10-bit fallback gate are recorded in
`doc/decisions/adr-004-adc-trigger-dma.md`. Both modules are explicitly set to
12-bit `uint16_t`, synchronous 37.5 MHz high-speed conversion with the shortest
three-ADCK sample and no hardware averaging, then calibrated independently
under a 10 ms DWT deadline. The target adapter defers Teensy core's normally
unbounded startup calibration so this is the sole ADC calibration path.
INFO/STATUS publish the actual settings, fixed A0/ADC1/channel-7 and
A1/ADC2/channel-8 routes, per-converter calibration states/cycles, and typed
initialization faults. The BOOT boundary also programs the shared PIT0 4 MHz
to chained PIT1 1 MHz source, fans PIT1 through XBARA1 to independent ADC_ETC
queues 0/4, and writes raw delays 0/75 (effective 1/76 IPG cycles, exactly
500 ns apart). A bounded stopped-to-armed-to-stopped diagnostic publishes
first conversion-completion IRQ timing, trigger errors, completion counts, and
clock/XBAR/queue/register readbacks in INFO/STATUS. That DWT delta is
completion timing, not analog aperture evidence. The fixed eDMA 0/1 adapter
now writes ADC1/ADC2 result halfwords directly to offsets 0/2 of four-byte
sample pairs with equal 1,012-result major loops and deterministic
scatter/gather rotation. A generation-and-epoch barrier publishes a buffer
only after both channels complete; cache ownership, an isolated pressure sink,
ADC_ETC overwrite evidence, mismatched completions, stale interrupts, ring
overruns, and exact discarded-pair counts are centralized in the portable ADC
DMA core. The cooperative ADC frame packer now copies each complete DMA
generation directly into one fixed packet payload, preserving little-endian
`(ADC0, ADC1)` pair identity, deriving run-relative timestamps from exact pair
counters, projecting whole raw gaps into the independent ADC sequence, and
using the negotiated checksum without heap allocation. ADC-only physical
CONFIGURE/START is enabled in firmware; combined physical ADC/GPIO remains
disabled. The Python block model binds the actual INFO-advertised timing,
resolution, calibration, trigger, and latest STATUS acquisition evidence to
zero-copy-friendly ADC0/A0 and ADC1/A1 views, validates only payload shape and
the selected code range for physical inputs, and retains explicit gap context
without implying increased analog bandwidth. The hardware rig gates remain
later Phase 07 work. STATUS extends the raw-to-USB accounting with both
DMA channel totals, paired buffers, captured/delivered/framed/transmitted pairs,
exact raw/STOP loss, queue depth, lifecycle, stale, and packer errors.

The advertised physical GPIO mode selectively returns only D6-D13 from
GPIO7 to GPIO2, keeps them inputs on START/STOP/error, and uses channel 2 to
copy fixed 32-bit `GPIO2_PSR` samples into four aligned 4,048-word OCRAM
buffers. Scatter/gather completion interrupts occur once per buffer, not at
4 MHz. Explicit `FREE → DMA_QUEUED → DMA_ACTIVE → READY → PACKING →
RELEASING` ownership and centralized cache deletion/invalidation prevent DMA
from touching CPU-owned data. The cooperative batch packer gathers GPIO2 bits
10, 17, 16, 11, 0, 2, 1, and 3 into wire bits 0-7, assembles arbitrary raw
boundaries into 4,048-byte frames, releases raw leases promptly, and stages
four complete packed buffers before the existing fixed packet ready/transmit
queues apply run, sequence, first-sample timestamp, gap flags, and the selected
checksum. When either raw or packed storage fills, acquisition remains live and
the exact loss is projected once into shared statistics. CONFIGURE accepts
either the ADC-only or GPIO-only hardware profile and rejects combined physical
acquisition or conflicting resource states before touching acquisition
registers. START snapshots one epoch and
arms buffers/DMA before enabling PIT; STOP disables the trigger and DMA route
in reverse order, then drains complete old-run work before another START.
INFO and STATUS expose pin order, rate/period, packed width, ring/resource
capacities, stage counts, queue depths, resource conflicts, lifecycle errors,
rejected stale DMA completions, and a cumulative DWT active/elapsed percentage
for the GPIO pack/copy/checksum/framing service.

The registered Port 15 fixture documentation does not establish that D6-D13
are unconnected or safe to drive and declares no machine-readable loopback or
stimulus. The autonomous GPIO capture diagnostic therefore fails closed to an
input-only mode: it reuses one bounded 4 MHz production-ring capture, reports
raw/packed observations plus before/during/after register and count evidence,
drains all leases, and restores GPIO2 inputs. It never writes a GPIO data
register, and it explicitly leaves external transition, pad-electrical, and
self-driven 256-value stable-window validation unexercised. The existing
host-C++ packer test independently covers all 256 logical GPIO bytes. The
optional `GPIO_CAPTURE_DIAGNOSTIC` command now advertises this fail-closed
evidence path while keeping its fixture policy immutable from the host.

The Python codec uses exact standard-library C implementations for Adler-32
and CRC-32/ISO-HDLC and a bounded table-driven fallback for CRC-32C. Its
machine-readable benchmark measures full 4,096-byte ADC and GPIO encode and
validation paths separately; it records backend/platform provenance but never
uses host-specific timing to redefine wire compatibility:

```bash
PYTHONPATH=daq_api/src .venv/bin/python -m teensy_daq.checksum_benchmark
```

The portable firmware control module implements bounded BOOT → IDLE,
CONFIGURED, and RUNNING transitions plus INFO, CONFIGURE, START, GET_STATUS,
STOP, RESET_STATS, PING, optional CHECKSUM_BENCHMARK, and optional
GPIO_CLOCK_DIAGNOSTIC and GPIO_CAPTURE_DIAGNOSTIC. Synthetic mode accepts any
nonempty ADC/GPIO subset; physical mode accepts either single stream. INFO and
STATUS
distinguish source, publish the fixed GPIO hardware resources, and remain
responsive while the physical stream is running.

The Teensy USB layer retains PJRC's USB Serial VID/PID and chip-derived serial
number while overriding only the weak product string with `Teensy DAQ`. Boot
does not wait for a host or emit an unframed banner. Its portable CDC transport
uses fixed command/response queues, bounded byte and call budgets, 2,048-byte
maximum write requests, 512-byte minimum capacity admission, exact
partial/zero-write continuation, response-first frame scheduling, and exposed
request/queue/stall diagnostics. Short data tails and complete control frames
remain atomic admission units; an unexpectedly short backend result is retained
and resumed rather than abandoned.

Phase 04 supplies deterministic ADC-pair and GPIO-byte sources through the
same allocation-free packet path used by later physical acquisition. ADC0 and
ADC1 retain pair identity as `2n` and `2n + 1` modulo 12 bits; GPIO is `m`
modulo 256 with D6-through-D13 in bits 0-through-7. Both streams share one
START epoch, use independent sequences, and cover the same 8,096 ticks per
frame. Normal mode waits for each frame's real-time 8 MHz deadline. The
explicitly selected `unpaced-diagnostic` mode removes only that wait and still
uses the generator, framing, checksum, queues, and USB transport unchanged.

One hundred six aligned 4,096-byte DTCM frames move through explicit
`FREE -> FILLING -> READY -> TRANSMITTING -> FREE` ownership. Per-source ready
FIFOs feed one bounded transmit FIFO, and every queue exposes current and
high-water depth. Frames are validated and checksummed in place before
transport admission; a partial USB write keeps immutable ownership until the
final byte succeeds. Native diagnostics retain exact generated, framed,
emitted, transmitted, and dropped frame/item counts. Fixed protocol-v1 STATUS
projects transport-admitted frames and dropped items alongside the applied
synthetic source.

STOP disables production immediately, cancels only an incomplete producer-owned
fill, and drains every already complete ready or transport-owned frame. A new
START returns typed `BUSY` while that bounded drain remains, without allocating
a run ID or resetting an epoch. Once quiescent, the runtime resets every queue
deterministically, arms the packet/source epoch, and only then admits the
successful START response. Consequently no prior-run data can follow an
acknowledged new START. The STOP response itself still wins at the next frame
boundary, so remaining old-run complete frames may follow STOP, but they are
always serialized before any later successful START response.

The split packet placement follows a reinspection of pinned Teensy core 1.62.0:
USB Serial copies writes into its own four 2,048-byte aligned `DMAMEM` buffers
and flushes those buffers before DMA. A 105-frame cacheless DTCM primary bank
and 95-frame CPU-owned OCRAM reserve cover 101.200 ms at the nominal combined
framed rate, plus 1.012 ms in the core ring. This absorbs the 60.715 ms service
gap observed by the Phase 05 CRC campaign while the exact linker gate retains
at least 32 KiB for locals and stack. The compile-time registry reserves
449,440 bytes of RAM1 project data and 491,072 bytes of RAM2 storage, including
the acquisition rings, isolated benchmark buffers, and the GPIO clock
diagnostic cache line; see
`doc/architecture/firmware-resource-map.md` and
`doc/reference/Foundation-Reuse-Inventory.md`.

`FirmwareRuntime` connects that transport to the portable control dispatcher,
polled 8 MHz clock, deterministic source, and packet pipeline. The thin sketch
constructs the Teensy CDC/clock adapters and aligned packet storage before the
runtime, binds INFO to the core-derived hardware serial during bounded BOOT,
and makes one cooperative service call per loop. Each call performs bounded
receive work, dispatches at most one command, applies compact START/STOP events
before admitting their successful responses, generates at most two due
synthetic frames, promotes bounded ready frames, and performs bounded transmit
work. No pacing ISR is installed.
Expected typed command errors are
state-atomic; an internal response-path failure emits an INTERNAL_ERROR when
possible, releases its queue reservation, and fails safe to IDLE. INFO exposes
the protocol version, semantic firmware version, board/MCU IDs, hardware
serial, source-derived build ID, and truthful capability masks needed to reject
a stale or incompatible image before control changes.

## Portable firmware tests

The firmware test suite host-compiles the production protocol, control,
statistics, checksum benchmark, GPIO clock diagnostic, synthetic-source,
safe GPIO capture diagnostic, packet-pipeline, transport, and runtime sources
with allocation-free C++17 flags.
It exercises every split and truncation point for every command, corrupt-stream
recovery, the complete state-transition matrix, idempotency, counters, and
fixed frame/queue boundaries. A bidirectional interoperability test sends
Python-encoded commands through the C++ decoder and sends C++-encoded responses
through the Python decoder; both directions must match the tracked golden
fixtures byte for byte. Dependency checks keep Arduino and Teensy core APIs in
the guarded board/USB adapters rather than the portable protocol/control
closure.

The benchmark tests inject a deterministic wrapping cycle counter and verify
overhead subtraction, interrupt-mask restoration, warm-up exclusion, hot DTCM,
cold OCRAM cache costs, real production-frame coverage, duration bounds, and
unchanged acquisition state/counters. They also fail closed on aggregate cycle
overflow and require repeatable metrics/digests under an `-O3 -flto` host
build with explicit compiler barriers and observable publication. A separate
correctness suite checks published values, independent bitwise references, 32
input alignments, length/reduction edges, 97 seeded C++/Python buffers with
byte-identical little-endian results, representative corruption classes,
negotiation transitions, and parser recovery after every candidate's bad
trailer. The finite corruption matrix and its non-security limitations are
recorded in `doc/results/phase-05-checksum-correctness.md`. The pinned build
additionally inspects ELF symbols for exact checksum-body sizes, lookup-table
Flash residency, and the two benchmark-buffer addresses and alignments.
The complete pre-rig correctness, generated-table, package-build, pinned-image,
resource-delta, and repeated host-timing gate is recorded in
`doc/results/phase-05-checksum-local-gate.md`.
The accepted candidate-isolated on-device microbenchmarks and sequential
60-second Adler-32, CRC-32C, and CRC-32/ISO-HDLC streams are recorded in
`doc/results/phase-05-checksum-physical-campaign.md`; the fixed-policy checksum
selection is documented in `doc/decisions/adr-002-checksum-selection.md`. The
clean selected-image rebuild and three consecutive 60-second Adler-32
acceptance runs are consolidated in
`doc/results/phase-05-checksum-benchmark.md`.

The GPIO clock tests independently prove exact PIT/DWT divisor arithmetic,
request duration and TCD bounds, dead/duplicate/short-window classification,
unarmed resource behavior, protocol round trips, IDLE-only state atomicity,
and simulator refusal to fabricate target-only evidence. The pinned target
build and hardware spike additionally validate the explicit register adapter;
the accepted evidence is consolidated in
`doc/decisions/adr-003-gpio-clock-dma.md`.

The raw GPIO host test exhausts the ownership scheduler through normal
rotation, CPU packing leases, stopped partial buffers, stale handles, and
sustained sink pressure. It also proves cache calls occur only at ownership
boundaries, exact raw losses combine with later packet drops without overflow,
and the selective GPR27/GDIR helper cannot modify unrelated bits. The pinned
build separately verifies the four-buffer ring, one-line sink, and five TCDs
are exact, 32-byte-aligned OCRAM allocations.

The GPIO batch-packer test exhausts all 256 packed values, unrelated GPIO2-bit
noise, raw batches split across frame boundaries, exact two-tick timestamps,
selected checksums, sequence/gap projection, packed-ring pressure, and
produced/packed/framed/transmitted/dropped reconciliation. Its repeatable host
microbenchmark measures the selected allocation-free, four-sample-unrolled
shift/mask loop; one local run sustained 2,481.196 MB/s of packed payload versus
the 4 MB/s production requirement. This host observation is not a substitute
for the later target CPU/queue gate. The pinned build link-verifies the four
4,064-byte-stride packed buffers in OCRAM.

The separate synthetic-pipeline stress executable exercises every packet
ownership transition, fixed-queue full/empty and ring-wrap edges, unequal-source
fairness, 32-bit sequence rollover, STOP/reset cleanup, and stale-run rejection.
It also sends long real-time and unpaced ADC/GPIO runs through deterministic
full, partial, zero, and recovered fake-CDC writes while incrementally received
PING commands arrive behind active data frames; every resulting frame checksum,
timestamp, sequence, formula, and ownership-stage counter is reconciled.

After installing the development environment above, run the focused gate from
the repository root:

```bash
.venv/bin/python -m pytest -q firmware/tests
```

`firmware/tests/rig_control_smoke.py` is the separately graded hardware test.
It is a single-file Python 3.13 script that depends only on the standard
library and PySerial, reads the rig-provided `SERIAL_PORT`, independently
encodes and validates protocol v1, and leaves the board in IDLE. Its offline
tests compare the independent codec with every control fixture and exercise the
full lifecycle through reset noise and partial serial I/O before any rig time
is used.

`firmware/tests/rig_synthetic_stream.py` is the corresponding Phase 04
full-rate acceptance program. It remains independent of `daq_api`, parses and
checks every ADC/GPIO frame as it arrives, interleaves bounded STATUS requests,
and prints JSON `EVENT`, expected-versus-actual `METRIC`, and final `SUMMARY`
records. It defaults to a 10-second capture; set
`SYNTHETIC_CAPTURE_SECONDS=60` for the soak. Optional `EXPECTED_BUILD_ID` and
`EXPECTED_HARDWARE_SERIAL` pins reject a flashed artifact or board mismatch;
`SYNTHETIC_CHECKSUM_ALGORITHM` accepts `ADLER32`, `CRC32C`, or
`CRC32_ISO_HDLC` and defaults to the selected production Adler-32. The rig
uses zlib only for exact matching variants, retains its own bounded pure-Python
fallbacks, and emits separate non-grading host encode/validation benchmark
events before acquisition.
The program enforces the 1% per-source and combined payload/framed rate bounds,
100 ms STATUS p99 and 250 ms maximum response latency, zero parser/formula/gap/
drop errors, bounded process RSS, a finite post-STOP drain, and exact final
firmware-to-host frame reconciliation before returning success in IDLE.

`firmware/tests/rig_checksum_benchmark.py` is the standalone Phase 05 checksum
campaign. Before opening the serial port it checks all 15 algorithm/vector
combinations against embedded values through separate bitwise and streaming
implementations. It then discovers the device-advertised candidates and, for
each one in sequence, runs the meaningful 14-profile DTCM/OCRAM hot/cold
microbenchmark matrix followed by a full-rate synthetic ADC/GPIO capture. Every
frame trailer, payload formula, sequence, timestamp, STATUS snapshot, and final
counter is checked without importing `daq_api` or retaining bulk captures.
Machine-readable `EVENT`, per-algorithm `CANDIDATE`, and final `SUMMARY` JSON
records include cycles/byte, projected CPU, throughput, implementation/table
Flash, benchmark RAM, command latency, parser queue high water, and all exposed
drop/error counters. Protocol v1 does not expose firmware queue depth, so the
record says so explicitly and reports its fixed capacity plus the observable
gap/drop/counter exhaustion evidence.

The campaign defaults to 10 seconds per advertised candidate. Physical
acceptance sets `CHECKSUM_CAPTURE_SECONDS=60`; optional
`CHECKSUM_STATUS_INTERVAL_SECONDS`, `CHECKSUM_BENCHMARK_BATCH_COUNT`, and
`CHECKSUM_BENCHMARK_ITERATIONS_PER_BATCH` remain strictly bounded. Set
`CHECKSUM_CAMPAIGN_ALGORITHM` to an advertised name or numeric ID to run one
candidate in an isolated job; omitting it retains the all-candidates sequential
campaign. As with the other rig programs, `EXPECTED_BUILD_ID` and
`EXPECTED_HARDWARE_SERIAL` can pin the exact artifact and board. The
network-disabled rig retains a bounded slicing-by-eight CRC-32C implementation
for arbitrary data and all independent vectors. During the fixed synthetic
campaign it additionally proves each payload against the complete source
formula, combines the actual 44-byte header CRC with one of 528 precomputed
payload CRCs, and reports how many trailers used that equivalent bounded path.
This validates every received byte and trailer without retaining stream frames
or making the service host's Python speed part of the device result. A dedicated
reader drains the TTY into at most 32 16 KiB chunks while validation runs;
the campaign disables cyclic garbage collection, reports that queue's exact
capacity/high water/final occupancy, and still fails on any target-side gap or
drop instead of hiding sustained backpressure.

`firmware/tests/rig_gpio_capture.py` is the standalone Phase 06 physical-GPIO
acceptance program. It verifies the exact Teensy 4.0 identity, D6-through-D13
bit order, fixed ring/resource metadata, and selected checksum without
importing `daq_api`. Before streaming, it runs bounded exact-divisor clock/DMA
windows at 1 kHz and 4 MHz, checks the PIT/XBAR/DMAMUX/eDMA register snapshots
and DWT/event/sample ratios, and invokes the build-time fixture-policy capture
diagnostic. A declared self-driven sweep must prove all 256 values with stable
windows; the registered documentation-only fixture instead remains input-only
and produces the explicit line `ELECTRICAL_STIMULUS: external electrical
stimulus was not exercised`.

The physical capture defaults to 10 seconds and interleaves STATUS requests
while independently checking every GPIO frame checksum, run ID, sequence,
timestamp, flags, item count, and fixed 4,096-byte shape. It requires 4 MHz
sample/payload throughput within 1%, responsive STATUS, no more than 50% of
one 600 MHz core in the measured GPIO processing service, zero firmware DMA/
cache/packer/frame/transport losses or errors, bounded host parser/RSS state,
empty queues after STOP, and exact final firmware-to-wire reconciliation.
Use `GPIO_CAPTURE_SECONDS=60` for the soak. Optional controls are
`GPIO_STATUS_INTERVAL_SECONDS`, `GPIO_LOW_RATE_HZ`,
`GPIO_LOW_RATE_EVENT_COUNT`, `GPIO_PRODUCTION_EVENT_COUNT`, and
`GPIO_CHECKSUM_ALGORITHM`; `EXPECTED_BUILD_ID` and
`EXPECTED_HARDWARE_SERIAL` pin the artifact and board as in the earlier rig
programs.

The accepted clean artifact, local throughput/resource gate, repaired
frame-boundary STOP behavior, and sequential diagnostic, 10-second smoke, and
60-second physical stream evidence are consolidated in
`doc/results/phase-06-gpio-dma.md`.

`firmware/tests/rig_adc_capture.py` is the standalone Phase 07 physical
dual-ADC acceptance program. It independently grades the Teensy 4.0 identity,
both bounded calibration results, fixed A0/ADC1/channel-7 and
A1/ADC2/channel-8 routes, exact 1 MHz/500 ns trigger arithmetic, and the
PIT/XBAR/ADC_ETC register snapshot. The BOOT one-pair completion check is
treated only as digital timing evidence. Because protocol v1 deliberately has
no variable-rate ADC configuration, the preliminary capture limits volume
with `ADC_REDUCED_CAPTURE_FRAMES` while retaining the production 1 MHz
schedule; it does not misreport that epoch as a lower hardware rate. A second,
timed epoch then checks every physical ADC frame's checksum, four-byte
little-endian `adc0, adc1` pair layout, advertised code range, count, run,
sequence, timestamp, flags, and final firmware-to-host accounting while
polling STATUS under load.

The full-rate epoch defaults to 10 seconds; use `ADC_CAPTURE_SECONDS=60` for
the soak. Optional controls are `ADC_STATUS_INTERVAL_SECONDS`,
`ADC_REDUCED_CAPTURE_FRAMES`, and `ADC_CHECKSUM_ALGORITHM`, with the shared
`EXPECTED_BUILD_ID` and `EXPECTED_HARDWARE_SERIAL` identity pins. If the rig
has an analog stimulus, `ADC_FIXTURE_STIMULUS_JSON` must use schema
`teensy-daq-adc-stimulus-v1`, name the fixture/stimulus, and declare exact A0
and A1 minimum/maximum accepted codes; optional complete mean-code bounds make
analog-quality grading explicit. Without that declaration the program prints
that A0/A1 are unstimulated and that neither analog quality nor aperture was
graded. No code-range or DC declaration is promoted to analog-aperture
evidence.

## Synchronous Python API and offline simulator

The Python facade runs INFO→CONFIGURE→START→GET_STATUS→STOP→RESET_STATS and
optional diagnostics through the same background reader for serial hardware
and the in-memory simulator. `TeensyDAQ.gpio_clock_diagnostic()` returns a
typed, read-only register/count result after identity, capability, and IDLE
checks; the simulator rejects it rather than fabricate hardware evidence. The
stream models preserve raw ADC converter identity and packed GPIO data;
production iterators emit visible `StreamGap` events, strict mode raises on any
gap, and firmware versus host queue-loss counters remain separate. NumPy is
not required.

The Phase 04 streaming path uses one reusable 64 KiB receive buffer whenever a
transport offers `readinto`, retains bounded decoded queues (512 data frames by
default, about 2 MiB of payload storage), and exposes zero-copy payload views.
Strict synthetic validation checks the complete ADC/GPIO formulas as bulk
cyclic views in addition to run IDs, independent sequences, timestamps, gap
flags, parser errors, firmware counters, and host drops. `run_synthetic_soak()`
wraps the synchronous API with interleaved STATUS commands, separate payload
and framed throughput, bounded command-latency samples, queue/parser/Python
memory high-water marks, graceful STOP, final STATUS, and exact
firmware-to-wire-to-consumer reconciliation.

The dedicated Phase 04 correctness/performance suite runs multi-second paced
streams at the nominal and above-target schedules through seeded random read
boundaries, validates a separate two-epoch wire corpus, and stress-tests the
drop-oldest host queue. Its benchmark excludes corpus construction, measures
incremental parsing plus full formula validation across three deterministic
chunk distributions, and requires at least 1.25 times the approximately
8.095 MB/s framed target. Use `-s` to retain the structured platform and timing
record printed by the guard:

```bash
.venv/bin/python -m pytest -q -s \
  daq_api/tests/test_streaming_correctness_performance.py
```

Physical GPIO is configured with
`TeensyDAQ.configure(adc=False, gpio=True, source=Source.HARDWARE)`. Phase 03's
zero-stream profile remains available through `TeensyDAQ.configure_control_only()`
and `TeensyDAQ.simulated(control_only=True)` for legacy probing. Serial opens
discard one valid INFO
probe, require a second identity-equal response, retry reset/BOOT noise within
an explicit bound, and validate the protocol, Teensy target, minimum firmware,
source-derived build ID, and hardware serial before mutation. The installed
`teensy-daq` CLI lists filtered USB candidates and provides `probe`, `status`,
`configure`, `start`, `stop`, and `reset-stats` commands with typed nonzero exit
codes for timeout, busy port, wrong device, unsupported capability, disconnect,
and illegal state. Exact artifact pins can be supplied with
`--expect-build-id`, `--expect-firmware`, and `--hardware-serial`; see
`daq_api/README.md` for the full command reference.

After installing `daq_api`, run the complete synthetic flow without a Teensy,
serial port, or credentials. The demo validates every ADC/GPIO sample, stream
timestamp, sequence, and counter before printing `PASS`; any mismatch exits
nonzero. Frame count is per stream, and parser chunk size deliberately
exercises arbitrary byte boundaries:

```bash
.venv/bin/python -m teensy_daq.demo --frame-count 2 --parser-chunk-size 17
.venv/bin/teensy-daq-demo --frame-count 2 --parser-chunk-size 17
```
