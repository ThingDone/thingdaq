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

The portable firmware control module implements bounded BOOT → IDLE,
CONFIGURED, and RUNNING transitions plus INFO, CONFIGURE, START, GET_STATUS,
STOP, RESET_STATS, and PING. Phase 03 uses an explicit zero-stream hardware
configuration to exercise that lifecycle without advertising or emitting ADC
or GPIO data; acquisition remains unavailable until later phases enable its
capability bits.

The Teensy USB layer retains PJRC's USB Serial VID/PID and chip-derived serial
number while overriding only the weak product string with `Teensy DAQ`. Boot
does not wait for a host or emit an unframed banner. Its portable CDC transport
uses fixed command/response queues, bounded byte and call budgets, exact
partial-write continuation, response-first frame scheduling, and exposed
queue/stall diagnostics.

Phase 04 now supplies the streaming transport's allocation-free packet
foundation while deliberately leaving source capabilities disabled until the
synthetic generators are implemented. Sixteen aligned 4,096-byte DTCM frames
move through explicit `FREE -> FILLING -> READY -> TRANSMITTING -> FREE`
ownership. ADC and GPIO retain independent production/sequence/counter state,
per-source ready FIFOs feed one bounded transmit FIFO, and every queue exposes
current and high-water depth. Frames are validated and checksummed in place
before transport admission; a partial USB write keeps immutable ownership
until the final byte succeeds.

The DTCM placement follows a reinspection of pinned Teensy core 1.62.0: USB
Serial copies writes into its own four 2,048-byte aligned `DMAMEM` buffers and
flushes those buffers before DMA. The 16 application frames cover about 8.1 ms
at the nominal combined framed rate, plus about 1.0 ms in the core ring. The
compile-time registry reserves 72,096 bytes of RAM1 project data and 97,280
bytes of future RAM2 acquisition storage; see
`doc/architecture/firmware-resource-map.md` and
`doc/reference/Foundation-Reuse-Inventory.md`.

`FirmwareRuntime` connects that transport to the portable control dispatcher
and packet pipeline. The thin sketch constructs the Teensy CDC adapter and
aligned packet storage before the runtime, binds INFO to the core-derived
hardware serial during bounded BOOT, and makes one cooperative service call per
loop. Each call performs bounded receive work, dispatches at most one command,
consumes compact START/STOP events, promotes bounded ready frames, and performs
bounded transmit work. Expected typed command errors are
state-atomic; an internal response-path failure emits an INTERNAL_ERROR when
possible, releases its queue reservation, and fails safe to IDLE. INFO exposes
the protocol version, semantic firmware version, board/MCU IDs, hardware
serial, source-derived build ID, and truthful capability masks needed to reject
a stale or incompatible image before control changes.

## Portable firmware tests

The firmware test suite host-compiles the production protocol, control,
statistics, packet-pipeline, transport, and runtime sources with
allocation-free C++17 flags.
It exercises every split and truncation point for every command, corrupt-stream
recovery, the complete state-transition matrix, idempotency, counters, and
fixed frame/queue boundaries. A bidirectional interoperability test sends
Python-encoded commands through the C++ decoder and sends C++-encoded responses
through the Python decoder; both directions must match the tracked golden
fixtures byte for byte. Dependency checks keep Arduino and Teensy core APIs in
the guarded board/USB adapters rather than the portable protocol/control
closure.

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

## Synchronous Python API and offline simulator

The Python facade now runs INFO→CONFIGURE→START→GET_STATUS→STOP→RESET_STATS
through the same background reader for serial hardware and the in-memory
simulator. Its typed models preserve raw ADC converter identity and packed GPIO
data; production iterators emit visible `StreamGap` events, strict mode raises
on any gap, and firmware versus host queue-loss counters remain separate.
NumPy is not required.

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
