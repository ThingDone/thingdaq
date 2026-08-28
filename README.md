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
artifacts include the HEX, ELF, and linker map needed for pre-upload review:

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
`doc/decisions/adr-001-wire-protocol.md`.

Regenerate the Python constants, C++ constants, and shared golden frames—or
check that tracked output has not drifted—with:

```bash
python3 tools/generate_protocol.py
python3 tools/generate_protocol.py --check
```

Phase 05 adds stateless firmware candidates for Adler-32, CRC-32C, and
CRC-32/ISO-HDLC behind one allocation-free checksum interface. INFO advertises
all three for data frames, CONFIGURE selects one, and each data header carries
the selected ID; every command and response remains unambiguously protected by
bootstrap Adler-32. Reconfiguration returns `BUSY` until prior-run frames have
drained. The pinned-core, Cortex-M7, i.MX RT1062,
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

The portable firmware control module implements bounded BOOT → IDLE,
CONFIGURED, and RUNNING transitions plus INFO, CONFIGURE, START, GET_STATUS,
STOP, RESET_STATS, PING, and optional CHECKSUM_BENCHMARK. Phase 04 accepts nonempty ADC/GPIO subsets only
for the implemented synthetic source; INFO and STATUS distinguish that source
from the still-unavailable physical path.

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

Ninety-six aligned 4,096-byte DTCM frames move through explicit
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

The DTCM placement follows a reinspection of pinned Teensy core 1.62.0: USB
Serial copies writes into its own four 2,048-byte aligned `DMAMEM` buffers and
flushes those buffers before DMA. The 96 application frames cover about 48.6 ms
at the nominal combined framed rate, plus about 1.0 ms in the core ring. This
retains six complete 64 KiB host-read batches: five cover the measured 39.8 ms
rig scheduling pause and one remains as bounded margin. The compile-time
registry reserves 405,920 bytes of RAM1 project data and 101,376 bytes of RAM2
storage, including one isolated benchmark buffer in each region; see
`doc/architecture/firmware-resource-map.md` and
`doc/reference/Foundation-Reuse-Inventory.md`.

`FirmwareRuntime` connects that transport to the portable control dispatcher,
polled 8 MHz clock, deterministic source, and packet pipeline. The thin sketch
constructs the Teensy CDC/clock adapters and aligned packet storage before the
runtime, binds INFO to the core-derived hardware serial during bounded BOOT,
and makes one cooperative service call per loop. Each call performs bounded
receive work, dispatches at most one command, applies compact START/STOP events
before admitting their successful responses, generates at most four due
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
statistics, checksum benchmark, synthetic-source, packet-pipeline, transport, and runtime sources with
allocation-free C++17 flags.
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
unchanged acquisition state/counters. The pinned build additionally inspects
ELF symbols for exact checksum-body sizes, lookup-table Flash residency, and
the two benchmark-buffer addresses and alignments.

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
`EXPECTED_HARDWARE_SERIAL` pins reject a flashed artifact or board mismatch.
The program enforces the 1% per-source and combined payload/framed rate bounds,
100 ms STATUS p99 and 250 ms maximum response latency, zero parser/formula/gap/
drop errors, bounded process RSS, a finite post-STOP drain, and exact final
firmware-to-host frame reconciliation before returning success in IDLE.

## Synchronous Python API and offline simulator

The Python facade now runs INFO→CONFIGURE→START→GET_STATUS→STOP→RESET_STATS
through the same background reader for serial hardware and the in-memory
simulator. Its typed models preserve raw ADC converter identity and packed GPIO
data; production iterators emit visible `StreamGap` events, strict mode raises
on any gap, and firmware versus host queue-loss counters remain separate.
NumPy is not required.

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

Phase 03's zero-stream hardware profile is available through
`TeensyDAQ.configure_control_only()` and
`TeensyDAQ.simulated(control_only=True)`. Serial opens discard one valid INFO
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
