---
type: reference
title: Teensy DAQ Python Package
created: 2026-08-27
tags:
  - teensy-daq
  - python
  - package
  - local-development
related:
  - '[[System-Overview]]'
  - '[[Foundation-Reuse-Inventory]]'
  - '[[Protocol-V1]]'
  - '[[ADR-001-Wire-Protocol]]'
---

# Teensy DAQ Python package

This directory contains the private, local-development Python distribution for
the Teensy DAQ host API. Its installable distribution name is
`teensy-daq-local`, while its stable import package is `teensy_daq`.

The base installation includes PySerial for the bounded hardware transport.
NumPy remains optional, and test, lint, type-check, and package-build tools are
available through development extras:

```bash
python3 -m pip install --editable '.[dev,numpy]'
```

The local distribution is intentionally marked `Private :: Do Not Upload`.
Choose and review public distribution metadata before publishing anything.
See [[System-Overview]] for the package boundary and
[[Foundation-Reuse-Inventory]] for the implementation-pattern audit.

## Synchronous public and simulator API

The synchronous `TeensyDAQ` facade operates on a small `ByteTransport`
interface. `InMemoryTransport` connects that facade to `SimulatedDevice`
through encoded protocol-v1 bytes, including arbitrary partial read/write
boundaries. `SerialTransport` implements the same interface over PySerial, so
command and streaming code does not depend on the concrete byte source. The
facade itself always starts one `BackgroundReader`; the simulator does not use
a second command decoder or direct-read shortcut:

```python
from teensy_daq import ADCBlock, StreamGap, TeensyDAQ

with TeensyDAQ.simulated(read_chunk_size=47) as daq:
    info = daq.info()
    applied = daq.configure(adc=True, gpio=True)
    run_id = daq.start()

    for item in daq.blocks(4):  # four data blocks, plus any gap events
        if isinstance(item, StreamGap):
            print("loss", item.origin, item.missing_items)
        elif isinstance(item, ADCBlock):
            print(run_id, item.sequence, item.pair(0))

    final = daq.status()
    daq.stop()
    generation = daq.reset_stats()  # valid after STOP, or while CONFIGURED
```

`DeviceInfo`, `DeviceCapabilities`, `AdcCalibrationMetadata`,
`AdcTriggerMetadata`, `AdcAcquisitionStatus`, `AdcBlockMetadata`,
`DAQConfiguration`, `Status`, `ADCBlock`, `GPIOBlock`,
`GpioClockDiagnosticRequest`, `GpioClockDiagnosticResult`,
`GpioCaptureDiagnosticResult`, `StreamGap`, `FirmwareCounters`, `HostCounters`,
and `LossCounters` validate
their values when constructed. The Phase 01 names
`Info`, `Configuration`, `AdcBlock`, and `GpioBlock` remain aliases. INFO,
GET_STATUS, and STOP are legal in every post-boot state; CONFIGURE and
RESET_STATS are limited to IDLE/CONFIGURED; START requires CONFIGURED; and
block reads require the RUNNING epoch established by this facade. The optional
GPIO clock diagnostic requires IDLE and its advertised capability bit. The
capture diagnostic additionally requires a fully quiescent physical GPIO
pipeline.

`DeviceInfo.adc_trigger` and `Status.adc_trigger` expose the exact 24 MHz PIT
root, 4 MHz master, chained 1 MHz pair schedule, queues 0/4, raw/effective
delays 0/75 and 1/76, configured-register readbacks, completion counts, and
typed trigger errors. `completion_timing_delta_ns` converts the first
conversion-completion IRQ delta from the 600 MHz DWT counter; it is not an
analog aperture measurement.

`DeviceInfo.data_checksum_algorithm` reports the generated device default in
IDLE and the applied selection otherwise. `Status.data_checksum_algorithm`
and each `ADCBlock`/`GPIOBlock.checksum_algorithm` preserve the same wire ID.
The host dispatch never substitutes a different polynomial: unsupported IDs or
a missing local backend raise an explicit checksum-support error.

Run the bounded host benchmark without hardware to measure encode and
validation separately for both production data layouts. The JSON report has
no pass/fail speed field because host-specific performance is not a wire
compatibility decision:

```bash
python -m teensy_daq.checksum_benchmark --algorithms all
```

On firmware 0.6.0 or newer, the target-only clock diagnostic returns one
read-only register/count snapshot without starting acquisition or touching a
GPIO pad:

```python
with TeensyDAQ.open(hardware_serial=12345670) as daq:
    evidence = daq.gpio_clock_diagnostic(rate_hz=4_000_000, event_count=8192)
    if not evidence.healthy:
        raise RuntimeError(evidence.hardware_error_flags)
    print(evidence.measured_rate_hz, evidence.count_error)
```

Accepted rates must divide both the 24 MHz PIT clock and 600 MHz DWT clock
exactly and cannot exceed the immutable 4 MHz production rate. The simulator
does not advertise this capability and raises `DeviceCapabilityError` instead
of fabricating target register evidence. See [[Protocol-V1]] and
[[ADR-003-GPIO-Clock-DMA]].

Firmware 0.7.0 adds physical GPIO-only streaming and the fail-closed capture
diagnostic. D6 through D13 map to bits 0 through 7 at 4 MHz. INFO exposes the
fixed rings/resources, and STATUS exposes stage counts and resource/lifecycle
errors:

```python
from teensy_daq import Source, TeensyDAQ

with TeensyDAQ.open(hardware_serial=12345670) as daq:
    evidence = daq.gpio_capture_diagnostic()
    applied = daq.configure(adc=False, gpio=True, source=Source.HARDWARE)
    run_id = daq.start()
    block = daq.read_gpio_block()
    final = daq.stop()
    print(
        run_id,
        applied.stream_mask,
        daq.device_info.gpio_pin_map,
        block.item_count,
        final,
        evidence.healthy,
    )
```

For hardware, pass a discovery result or select a stable serial directly. A
selected port is INFO-probed again so hot re-enumeration cannot silently open a
different unit:

```python
from teensy_daq import ExpectedDeviceIdentity, TeensyDAQ, discover

devices = discover(timeout=0.2)
with TeensyDAQ.open(devices[0]) as daq:
    print(daq.device_info.hardware_serial)

expected = ExpectedDeviceIdentity(
    hardware_serial=12345670,
    firmware_version=(0, 3, 0),
    build_id="tdaq-39300273210c1c89",
)
with TeensyDAQ.open(hardware_serial=12345670, expected_identity=expected) as daq:
    print(daq.device_info.build_id)
```

Every open consumes a throwaway valid INFO and then requires a second response
with the same protocol, semantic firmware version, source-derived build ID,
board/MCU pair, and hardware serial. INFO timeouts plus typed BOOT/BUSY replies
are retried only within the configured attempt bound; unframed CDC reset noise
is discarded by the incremental parser. Physical targets must be Teensy
4.0/i.MX RT1062 firmware version 0.3.0 or newer with a nonzero serial and a
`tdaq-` source build ID. `ExpectedDeviceIdentity` adds exact firmware, build,
and serial pins when a particular artifact is required.

## Phase 03 control-only API and CLI

Phase 03 firmware advertises no ADC/GPIO streams yet. Its exact configuration
is `stream_mask=NONE`, `source=HARDWARE`, and `checksum=ADLER32`; use the
explicit method so this milestone profile cannot be confused with a disabled
or unsupported acquisition request:

```python
with TeensyDAQ.open(hardware_serial=12345670, expected_identity=expected) as daq:
    applied = daq.configure_control_only()
    run_id = daq.start()
    running = daq.status()
    daq.stop()
    generation = daq.reset_stats()
```

`TeensyDAQ.simulated(control_only=True)` exercises the identical zero-stream
CONFIGURE/START/STATUS/STOP/RESET_STATS schemas without serial hardware. The
default simulator retains its synthetic ADC/GPIO behavior.

The installed `teensy-daq` command exposes bounded one-shot hardware controls:

```bash
teensy-daq list
teensy-daq probe --hardware-serial 12345670 --expect-build-id tdaq-39300273210c1c89
teensy-daq status --hardware-serial 12345670
teensy-daq configure --hardware-serial 12345670
teensy-daq start --hardware-serial 12345670
teensy-daq stop --hardware-serial 12345670
teensy-daq reset-stats --hardware-serial 12345670
```

`list` uses VID/PID metadata and opens nothing. Every other command performs
the synchronized identity check before its operation. `configure` and `start`
release the port without undoing their new device state so the next invocation
can continue the lifecycle; normal Python context-manager cleanup still STOPs
by default. Diagnostics are typed and machine-visible: no device (exit 3),
timeout (4), busy/denied port (5), wrong identity (6), unsupported capability
(7), disconnect (8), invalid state (9), and other device errors (10).

The simulator advertises only the deterministic synthetic source. Each
successful START allocates a new run ID, resets both stream epochs and
counters, and produces ADC then GPIO frames in a repeatable round-robin order
when both streams are enabled. INFO and STOP are idempotent; closing the facade
stops an active run before closing its transport. Simulator data production is
demand-driven so offline frame counts remain deterministic under a background
thread; every command, response, and data frame still crosses the shared wire,
parser, decoder, and reader path.

## Stream data and loss policy

ADC blocks always retain separate `adc0`/A0 and `adc1`/A1 lazy channel views.
Each view exposes the shared zero-copy `payload_view` plus its byte offset and
four-byte stride, so optional array consumers can use the native pair buffer
without changing the pure-Python path. `t0_ticks`, `pair_period_ticks`,
`adc1_phase_ticks`, `resolution_bits`, `sequence`, `run_id`, `gap`, and
`calibration` expose the actual INFO-advertised format and run context. The
facade validates every raw code against the advertised 12-bit or explicitly
gated 10-bit range; hardware inputs may otherwise vary freely or float and are
never checked against the synthetic ramp formula.

`interleave_adc(block)` and `block.interleaved()` are explicit operations that
emit timestamped samples in ADC0, ADC1 order while retaining converter
identity. They create a denser nominal two-converter time grid; they do not
increase either input's analog bandwidth. GPIO payloads remain packed, and
`block.channel(pin)` lazily extracts D6-D13 without an eager eightfold Boolean
expansion. None of these operations imports or requires NumPy.

`Status.adc_acquisition` exposes the complete physical dual-DMA, pair,
framing, loss, ADC_ETC/eDMA conversion-error, lifecycle, and packer snapshot.
`Status.has_adc_errors` includes initialization and trigger errors as well as
those live counters. If a RUNNING STATUS has been polled, subsequently
delivered ADC blocks retain that immutable snapshot as `block.acquisition`;
otherwise it is `None` rather than fabricated per-frame evidence.

Production mode is the default. A sequence, timestamp, or firmware-flagged
discontinuity causes `blocks()` to emit `StreamGap` immediately before the
current data block and then continue. `strict=True` instead raises
`UnexpectedStreamGapError`, with both the gap and current block attached. For
ADC data, the following block also retains the same `StreamGap` in
`block.gap`, including in production mode where the gap event is yielded first.
`StreamGap.origin` never infers firmware loss from a host queue eviction:
firmware `GAP_BEFORE`/`OVERRUN_BEFORE`, host queue-drop attribution, and an
otherwise observed discontinuity remain separate. `loss_counters()` combines
an explicit `FirmwareCounters` and `HostCounters` snapshot without adding the
two domains together.

## Production transport and background reader

`SerialTransport` configures finite PySerial read and write timeouts and adds
bounded open, flush, and close behavior. Busy, locked, and access-denied opens
raise `SerialPortBusyError`; disconnects and timeouts retain separate types. A
write may report partial progress;
`BackgroundReader` serializes concurrent command writes and retries each
unwritten suffix within the command's overall deadline. Its default 64 KiB
reads are deliberately larger than USB packets because USB CDC is one byte
stream, not a packet-preserving message API.

`BackgroundReader` owns exactly one `IncrementalFrameParser`. One non-daemon
thread continuously feeds arbitrary read chunks into it, matches concurrent
responses by echoed request ID, and separates decoded ADC/GPIO blocks from
other non-response frames. Pending requests, block queues, and event queues are
all bounded. Request timeout removes the pending entry; an eventual unmatched
reply increments `late_responses`. STOP, close, parser failure, and disconnect
wake blocked callers and cancel outstanding requests with typed exceptions.

Both decoded queues use a **drop-oldest complete item** policy when full. The
newest data therefore remains visible during consumer stalls. The
`host_block_queue_drops` and `host_event_queue_drops` reader counters describe
only those local Python queue evictions: they never include firmware sequence
gaps, `GAP_BEFORE`/`OVERRUN_BEFORE` flags, or the firmware counters returned by
GET_STATUS. `stale_blocks_discarded` separately records blocks rejected because
their run ID is not the active START epoch.

Hardware-capable transports may implement `readinto(buffer)`. The reader
detects that optional extension and repeatedly fills one fixed 64 KiB
`bytearray`; transports that only implement the original `read(size)` contract
remain compatible. The default data queue holds 512 complete frames (about
2 MiB), enough to absorb a large read and ordinary command-response jitter
while remaining explicitly bounded. Reader snapshots include current and
high-water queue depths, maximum read size, reusable-read call count, and
per-source receive, queue-drop, STOP-boundary, and stale-run accounting.

## Strict synthetic soaks and metrics

`validate_synthetic_block()` checks complete ADC and GPIO payloads against
their periodic formulas using bulk memory views on the normal path. It does
not expand packed GPIO bits, materialize ADC sample objects, import NumPy, or
loop over individual bytes. `strict=True` applies formula and parser checks to
ordinary facade reads in addition to the existing run/sequence/timestamp/gap
policy. `validate_stream_health()` explicitly grades firmware and host health
counters without changing production `loss_counters()` behavior.

For a complete bounded run, use the reusable soak layer:

```python
from teensy_daq import TeensyDAQ, run_synthetic_soak

with TeensyDAQ.open(hardware_serial=12345670, strict=True) as daq:
    metrics = run_synthetic_soak(
        daq,
        duration=10.0,
        status_interval=0.25,
    )

print(metrics.payload_bytes_per_second)
print(metrics.framed_bytes_per_second)
print(metrics.command_latency.p99_seconds)
print(metrics.queues.block_queue_high_water)
print(metrics.memory.peak_bytes)
metrics.reconciliation.require_exact()
```

The runner owns CONFIGURE→START→capture→STOP→final STATUS for its epoch and
leaves the open facade in IDLE. STATUS requests use the same background reader
as data. After STOP, the runner waits for the finite firmware drain to settle
and reconciles each source's firmware-emitted count with wire-decoded frames,
validated consumer frames, bounded queue drops, and deliberate boundary/stale
discards. Command latency retention is bounded and reports how many samples,
if any, were discarded from its percentile window. `frame_count=` is an
alternative deterministic bound for offline simulator checks; real acceptance
soaks normally use `duration=`.

## Metadata-first device discovery

Discovery never opens unrelated serial ports. `enumerate_candidates()` uses
PySerial metadata only, filters for the Teensy USB Serial VID/PID
`0x16C0:0x0483`, preserves the port path, USB serial, product, manufacturer,
location, interface, and description, and orders the exact `Teensy DAQ`
product string first. Matching VID/PID entries with missing, default, or cached
product strings remain candidates so platform metadata quirks do not hide a
DAQ.

`discover(timeout=0.2)` opens only those candidates and performs one bounded,
state-preserving INFO request through `SerialTransport` and
`BackgroundReader`. Busy, access-denied, disconnected, timed-out, stale, and
incompatible candidates are omitted independently; every valid device is
returned with both its USB metadata and decoded `Info`. Each call enumerates
again, and `DeviceIdentity` plus `select_device()` use the hardware serial
rather than treating a COM number or `/dev` path as persistent identity:

```python
from teensy_daq import discover, enumerate_candidates, select_device

candidates = enumerate_candidates()  # metadata only; opens nothing
devices = discover(timeout=0.2)
daq_port = select_device(devices, hardware_serial=12345670)
print(daq_port.port, daq_port.info.firmware_version)
```

Opening a returned `DiscoveredDevice` then performs the two-probe session
synchronization and requires the complete firmware identity to remain equal to
the discovery result, catching an image change or hot re-enumeration before a
state-changing command can be issued.

## Executable offline demo

Both entry points below run the same bounded synthetic acquisition. They print
the discovered capabilities, ADC and GPIO ramps (including frame joins), final
counters, and the clean IDLE landing. Every sample is checked and a mismatch
returns a nonzero exit status:

```bash
python -m teensy_daq.demo --frame-count 2 --parser-chunk-size 17
teensy-daq-demo --frame-count 2 --parser-chunk-size 17
```
