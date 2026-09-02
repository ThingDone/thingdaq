---
type: reference
title: ThingDAQ Python Package
created: 2026-08-27
updated: 2026-09-02
tags:
  - thingdaq
  - python
  - package
  - local-development
related:
  - '[[Quickstart]]'
  - '[[Python-API]]'
  - '[[API-Reference]]'
  - '[[Hardware-Safety]]'
  - '[[System-Overview]]'
  - '[[Foundation-Reuse-Inventory]]'
  - '[[Protocol-V1]]'
  - '[[ADR-001-Wire-Protocol]]'
  - '[[ADR-007-Experimental-Aux-Input-Bank]]'
  - '[[Calibration]]'
  - '[[NumPy-Integration]]'
---

# ThingDAQ Python package

This directory contains the private, local-development Python distribution for
the ThingDAQ host API. The single authoritative installable distribution name
is `[project].name` in `pyproject.toml`, while the stable import package is
`thingdaq`.

Start with [[Quickstart]], read [[Hardware-Safety]] before connecting signals,
and use [[API-Reference]] for the stable public surface.

The base installation includes PySerial for the bounded hardware transport.
NumPy remains optional, and test, lint, type-check, and package-build tools are
available through development extras:

```bash
python3 -m pip install --editable '.[dev,numpy]'
```

See [[System-Overview]] for the package boundary and
[[Foundation-Reuse-Inventory]] for the implementation-pattern audit.

## Distribution and publication boundary

The host API and firmware are versioned independently from the wire protocol;
the current release candidate assigns semantic version `1.0.0` to both. The
host value is single-sourced in `thingdaq._version`, exposed as
`thingdaq.__version__`, and consumed by the build metadata declared in
`pyproject.toml`. Firmware single-sources its value in
`firmware/src/firmware_identity.h` and reports it through INFO. The supported
interpreter range is CPython 3.10 through 3.14; the base dependency is PySerial,
NumPy is an explicit optional extra, and build/test/lint/type tools are
development-only.

The package is fully typed and ships `py.typed`. Wheel contents are limited to
the runtime Python modules, the generated protocol constants, that marker, and
standard distribution metadata. The source distribution additionally carries
the package README, build metadata, source-manifest policy, and small runnable
Python examples. Tests, captures, firmware
builds, credentials, local calibration records, the canonical protocol JSON,
the generator, and golden fixtures are deliberately excluded. The latter three
are repository validation inputs, not runtime inputs: installed code uses the
tracked `thingdaq._generated.protocol_constants` module.

The local distribution remains marked `Private :: Do Not Upload`; package-index
availability and publication readiness require review before any PyPI
submission. Do not reserve, upload, or publish this distribution from
repository workflows. ThingDAQ is independent and is not affiliated with or
endorsed by PJRC.COM, LLC or SparkFun Electronics. Teensy® is a registered
trademark of PJRC.COM, LLC and identifies the supported hardware platform, not
the ThingDAQ product name.
The distribution declares the SPDX `MIT` license expression and includes the
project license in both wheel and source-distribution artifacts.

Build both local artifacts from the repository root with a source-derived,
fixed archive epoch:

```bash
package_source_epoch="$(git log -1 --format=%ct -- daq_api)"
SOURCE_DATE_EPOCH="${package_source_epoch}" \
  .venv/bin/python -m build --outdir daq_api/dist daq_api
```

Reproducibility checks compare sorted archive member paths and bytes after
normalizing container timestamps and ownership fields. Wheel output is also
expected to be byte-for-byte stable under the same backend, interpreter, source
state, and `SOURCE_DATE_EPOCH`.

## Synchronous public and simulator API

The synchronous `ThingDAQ` facade operates on a small `ByteTransport`
interface. `InMemoryTransport` connects that facade to `SimulatedDevice`
through encoded protocol-v1 or explicitly negotiated experimental-v2 bytes,
including arbitrary partial read/write
boundaries. `SerialTransport` implements the same interface over PySerial, so
command and streaming code does not depend on the concrete byte source. The
facade itself always starts one `BackgroundReader`; the simulator does not use
a second command decoder or direct-read shortcut:

```python
from thingdaq import ADCBlock, HostQueueLoss, StreamAnomaly, StreamGap, ThingDAQ

with ThingDAQ.simulated(read_chunk_size=47) as daq:
    info = daq.info()
    applied = daq.configure(
        adc=True,
        gpio=True,
        adc_pair_rate_hz=1_000_000,
        gpio_sample_rate_hz=4_000_000,
        adc_resolution_bits=12,
    )
    run_id = daq.start()

    for item in daq.blocks(4):  # four data blocks, plus any gap events
        if isinstance(item, StreamGap):
            print("device loss", item.stream, item.missing_items)
        elif isinstance(item, HostQueueLoss):
            print("application loss", item.stream, item.dropped_items)
        elif isinstance(item, StreamAnomaly):
            print("protocol telemetry", item.stream, item.reason)
        elif isinstance(item, ADCBlock):
            print(run_id, item.sequence, item.pair(0))

    final = daq.status()
    daq.stop()
    generation = daq.reset_stats()  # valid after STOP, or while CONFIGURED
```

`ThingDAQ.open(...)` and `ThingDAQ.simulated(...)` return the same typed
context manager. Exiting it attempts bounded STOP when needed, closes the
reader/transport deterministically, and preserves typed shutdown evidence.
Normal applications import the facade and immutable models from `thingdaq`.
Raw frames, parsers, the background reader, and byte transports remain
available for protocol tooling under the explicitly expert-only
`thingdaq.low_level` namespace; existing root imports remain stable for
compatibility.

CONFIGURE is capability-driven. The facade rejects unsupported stream, source,
checksum, exact source/stream profile, rate profile, and resolution
requirements before writing CONFIGURE. The default one-bank 1 MHz/4 MHz path
retains the fixed eight-byte protocol-v1 body. An explicit auxiliary-input or
reduced-rate request first validates protocol-v2 INFO, then uses the extended
16-byte body. The CONFIGURE echo must equal the request; before START, the
client obtains fresh INFO and requires the advertised capability table and
applied configuration to remain exact. START must repeat the same applied
configuration. CLI human/JSON output reports the mode, generated rate profile,
rates, packed width, frame counts, and resolution metadata.

### Experimental auxiliary-input simulator surface

The `experiment/aux-input-bank` branch exposes the isolated host/simulator
prototype defined by [[ADR-007-Experimental-Aux-Input-Bank]]. It does not claim
that D16-D23 or the provisional DMA resources are implemented or accepted on a
physical Teensy. `DISABLED` remains the default and therefore keeps the exact
protocol-v1, 8-bit, 1 MHz ADC-pair, and 4 MHz GPIO behavior:

```python
from thingdaq import AuxBankMode, RateProfile, Source, ThingDAQ

with ThingDAQ.simulated(gpio_pattern="walking-bit", strict=True) as daq:
    applied = daq.configure(
        adc=True,
        gpio=True,
        source=Source.SYNTHETIC,
        aux_bank_mode=AuxBankMode.INPUT,
        rate_profile=RateProfile.ADC_250KHZ_GPIO_1MHZ,
    )
    info = daq.info()  # exact supported table and applied mode/profile
    daq.start()  # performs another exact INFO check before START
    adc = daq.read_block()
    gpio = daq.read_block()
    status = daq.status()  # status.configuration == applied
```

The four closed profiles are 1 MHz/4 MHz, 500 kHz/2 MHz, 250 kHz/1 MHz,
and 125 kHz/500 kHz. `GPIOBlock` reports `packed_width_bits`, primary and
auxiliary pin maps, and `sample()` values through `0xFFFF`; `channel()` exposes
D6-D13 in bits 0-7 and, only in `INPUT` mode, D16-D23 in bits 8-15. NumPy views
remain read-only zero-copy `uint8` for one bank and use explicit little-endian
`<u2` for two banks. Alignment uses each selected period and mode-specific
equal frame coverage while retaining profile, sequence, gap, and run
boundaries.

The simulator patterns `all-zero`, `walking-bit`, `counter`, and
`high-transition` generate the primary and auxiliary bytes independently at
every profile. The same options are available through the CLI:

```bash
thingdaq monitor --simulate --duration 1 \
  --aux-bank-mode input \
  --rate-profile adc_250khz_gpio_1mhz \
  --gpio-pattern high-transition \
  --gpio-channel D6 --gpio-channel D23
```

## Runnable workflows

The nine scripts in `examples/` cover discovery/serial selection, raw ADC
channels, explicit interleaving, optional calibration, packed/selected GPIO,
combined timestamp alignment, live STATUS/loss handling, standalone simulator
use, and explicit clean shutdown. Every script's no-argument path uses the
simulator. Physical access is opt-in via `--real`; calibration additionally
requires an explicit user-owned path:

```bash
python examples/raw_adc_channels.py
python examples/combined_alignment.py
python examples/status_and_loss.py
python examples/raw_adc_channels.py --real --hardware-serial 20512460
```

The complete roster and physical prerequisites are in [[Quickstart]].

`DeviceInfo`, `DeviceCapabilities`, `AuxiliaryInputMetadata`, `GPIOLayout`,
`RateProfileTiming`, `AdcCalibrationMetadata`,
`AdcTriggerMetadata`, `AdcAcquisitionStatus`, `AdcBlockMetadata`,
`DAQConfiguration`, `Status`, `ADCBlock`, `GPIOBlock`,
`GpioClockDiagnosticRequest`, `GpioClockDiagnosticResult`,
`GpioCaptureDiagnosticResult`, `StreamGap`, `HostQueueLoss`, `StreamAnomaly`,
`FirmwareLossEvidence`, `FirmwareCounters`, `HostCounters`, `LossCounters`,
`FirmwareFaultSnapshot`, `RunCounterReconciliation`, `NominalEpoch`,
`AlignedInterval`, and `AlignmentLoss` validate
their values when constructed. The Phase 01 names
`Info`, `Configuration`, `AdcBlock`, and `GpioBlock` remain aliases. INFO,
GET_STATUS, and STOP are legal in every post-boot state; CONFIGURE and
RESET_STATS are limited to IDLE/CONFIGURED; START requires CONFIGURED; and
block reads require the RUNNING epoch established by this facade. The optional
GPIO clock diagnostic requires IDLE and its advertised capability bit. The
capture diagnostic additionally requires a fully quiescent physical GPIO
pipeline.

`DeviceInfo.adc_trigger` and `Status.adc_trigger` expose the exact 24 MHz PIT
root, selected master/pair schedule, queues 0/4, generated phase and delay
readbacks, configured-register readbacks, completion counts, and typed trigger
errors. `completion_timing_delta_ns` converts the first
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
python -m thingdaq.checksum_benchmark --algorithms all
```

On firmware 0.6.0 or newer, the target-only clock diagnostic returns one
read-only register/count snapshot without starting acquisition or touching a
GPIO pad:

```python
with ThingDAQ.open(hardware_serial=12345670) as daq:
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

Firmware supports ADC-only, GPIO-only, and combined physical streaming plus
the fail-closed GPIO capture diagnostic. D6 through D13 map to bits 0 through 7
at 4 MHz while A0/A1 retain one 1 MHz pair stream with a 500 ns ADC1 phase.
INFO exposes the exact applied/supported profiles, rates, phases, pin map,
aligned rings, frame sizes, queue capacities, and checksum. STATUS exposes all
per-source/shared stage, byte, queue, firmware-diagnostic, and USB counters:

```python
from thingdaq import Source, ThingDAQ

with ThingDAQ.open(hardware_serial=12345670) as daq:
    evidence = daq.gpio_capture_diagnostic()
    applied = daq.configure(adc=True, gpio=True, source=Source.HARDWARE)
    run_id = daq.start()
    adc_or_gpio = daq.read_block()
    final = daq.stop()
    print(
        run_id,
        applied.stream_mask,
        daq.device_info.gpio_pin_map,
        adc_or_gpio.item_count,
        final,
        evidence.healthy,
    )
```

For hardware, pass a discovery result or select a stable serial directly. A
selected port is INFO-probed again so hot re-enumeration cannot silently open a
different unit:

```python
from thingdaq import ExpectedDeviceIdentity, ThingDAQ, discover

devices = discover(timeout=0.2)
with ThingDAQ.open(devices[0]) as daq:
    print(daq.device_info.hardware_serial)

expected = ExpectedDeviceIdentity(
    hardware_serial=12345670,
    firmware_version=(1, 0, 0),
    build_id="thingdaq-e27556de5b898f28",
)
with ThingDAQ.open(hardware_serial=12345670, expected_identity=expected) as daq:
    print(daq.device_info.build_id)
```

Every open consumes a throwaway valid INFO and then requires a second response
with the same protocol, semantic firmware version, source-derived build ID,
board/MCU pair, and hardware serial. INFO timeouts plus typed BOOT/BUSY replies
are retried only within the configured attempt bound; unframed CDC reset noise
is discarded by the incremental parser. Physical targets must be Teensy
4.0/i.MX RT1062 firmware version 0.3.0 or newer with a nonzero serial and a
`thingdaq-` source build ID. `ExpectedDeviceIdentity` adds exact firmware, build,
and serial pins when a particular artifact is required.

### Reopen policy and recovery evidence

Every synchronized open resolves device state explicitly. The default
`SessionRecoveryPolicy.ADOPT` preserves CONFIGURED state and, for an existing
RUNNING epoch, obtains STATUS, activates the reader with the reported run and
checksum, and treats the first complete frame from each enabled source as the
new host's continuity anchor. Pre-attachment loss is not fabricated as a
sequence-zero gap; it remains visible in the firmware STATUS counters. Select
`STOP` when a new process must force a known IDLE boundary instead:

```python
from thingdaq import SessionRecoveryPolicy, ThingDAQ

adopted = ThingDAQ.open(
    hardware_serial=12345670,
    session_policy=SessionRecoveryPolicy.ADOPT,
)
adopted.close(stop=False)  # deliberately leave the device state unchanged

with ThingDAQ.open(
    hardware_serial=12345670,
    session_policy=SessionRecoveryPolicy.STOP,
) as stopped:
    assert stopped.state.name == "IDLE"
```

Command deadlines raise `CommandTimeoutError` with an immutable
`RecoveryEvidence` snapshot. Terminal `DeviceDisconnectedError` and
`ReaderProtocolError` retain both reader/parser counter snapshots and the same
facade evidence when surfaced through `ThingDAQ`. `close()` always attempts a
bounded reader/transport shutdown even if STOP fails; a resulting
`DAQShutdownError` preserves both failures plus the last identity, state, run,
STATUS, host counters, parser counters, and observed loss/telemetry evidence.

## Phase 03 control-only API and CLI

Phase 03 firmware advertises no ADC/GPIO streams yet. Its exact configuration
is `stream_mask=NONE`, `source=HARDWARE`, and `checksum=ADLER32`; use the
explicit method so this milestone profile cannot be confused with a disabled
or unsupported acquisition request:

```python
with ThingDAQ.open(hardware_serial=12345670, expected_identity=expected) as daq:
    applied = daq.configure_control_only()
    run_id = daq.start()
    running = daq.status()
    daq.stop()
    generation = daq.reset_stats()
```

`ThingDAQ.simulated(control_only=True)` exercises the identical zero-stream
CONFIGURE/START/STATUS/STOP/RESET_STATS schemas without serial hardware. The
default simulator retains its synthetic ADC/GPIO behavior.

The installed `thingdaq` command exposes bounded one-shot hardware controls:

```bash
thingdaq list
thingdaq probe --hardware-serial 12345670 --expect-build-id thingdaq-e27556de5b898f28
thingdaq status --hardware-serial 12345670
thingdaq configure --hardware-serial 12345670 --streams both --source hardware
thingdaq start --hardware-serial 12345670
thingdaq stop --hardware-serial 12345670
thingdaq reset-stats --hardware-serial 12345670
thingdaq reconcile --hardware-serial 12345670
thingdaq monitor --hardware-serial 12345670 --streams both --source hardware --duration 10
thingdaq capture --simulate --streams both --source synthetic --duration 2 --strict-loss --gpio-channel D6 --gpio-channel D13
thingdaq info --simulate --json
```

`list` uses VID/PID metadata and opens nothing. Every other command performs
the synchronized identity check before its operation. `configure` and `start`
release the port without undoing their new device state so the next invocation
can continue the lifecycle; normal Python context-manager cleanup still STOPs
by default. `monitor` and its `capture` alias own one bounded
CONFIGURE→START→capture→STOP session. They print live ADC/GPIO payload rates,
gap counts, device/host queue high-water marks, and STATUS command latency, and
always attempt STOP and close from a finalizer. `--streams` accepts `adc`,
`gpio`, `both`, or the legacy control-only `none`; `--source` accepts `hardware`
or `synthetic`, and omission selects an advertised exact profile. Diagnostics
are typed and machine-visible: no device (exit 3),
timeout (4), busy/denied port (5), wrong identity (6), unsupported capability
(7), disconnect (8), invalid state (9), other device errors (10), and a
counter inconsistency or saturation that prevents an exact proof (11).

Every command accepts `--json` after its command name. One-shot operations
emit one JSON document containing typed INFO, STATUS, applied configuration,
or reconciliation data. Bounded `monitor`/`capture` buffers only its explicitly
limited sample preview and emits one final document with the running and
post-STOP STATUS snapshots, exact applied configuration, rates, selected
samples, firmware counters, host counters, and observed loss domains. The
default `--sample-limit 4` previews raw ADC0/A0 and ADC1/A1 codes plus packed
GPIO bytes; `--gpio-channel D6` through `D13` adds only the requested lazy bit
views and can be repeated. Set `--sample-limit 0` for telemetry only.

Calibrated preview is opt-in and requires an explicit user path:

```bash
thingdaq capture --hardware-serial 12345670 --streams adc --source hardware \
  --adc-output calibrated --calibration /explicit/path/calibration.json \
  --analog-front-end-profile buffered-input --duration 10 --strict-loss --json
```

Each calibrated row remains visibly marked, retains both raw codes, and adds
volts plus record provenance; no implicit calibration file is searched. For
offline simulator calibration tests, `--calibration-hardware-serial` supplies
the explicit record identity because simulator INFO intentionally has no
physical serial. `--strict-loss` raises on gaps, anomalies, host queue loss,
parser corruption, nonzero firmware drop/error counters, or inconsistent
telemetry. Human output prints both firmware and host loss summaries. SIGINT
and SIGTERM are converted to a typed interruption while the capture finalizer
attempts STOP and deterministic reader close; interrupted capture exits 130.

`reconcile` captures one STATUS snapshot and prints the run/generation,
source-wise frame/item/byte conservation equations, the first inconsistent or
saturated counter, and typed firmware faults. A live snapshot includes current
filling/ready/transmit ownership in its equations; after STOP, exact zero-depth
equations provide the strongest whole-run proof. The same API is available as
`reconcile_run_counters(status)` and `snapshot_firmware_faults(status)`.
Saturated operands are reported as indeterminate rather than mistaken for
either equality or a wrap.

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

The optional `thingdaq.numpy` module vectorizes the same models without
changing that baseline. `block.as_numpy().pairs` is a read-only, zero-copy
`(item_count, 2)` `<u2` view in ADC0/ADC1 order (1,012 rows for the legacy
layout and 506 for auxiliary-input mode), and a legacy GPIO block's
corresponding `packed` view is read-only, zero-copy `uint8`. Auxiliary-input
GPIO blocks instead use read-only, zero-copy little-endian `uint16`. Explicit
methods generate
interleaved ticks, calibrated `float64` voltages, or Boolean columns only for
requested GPIO pins. The arrays retain the immutable payload owner and source
block; no eight-channel GPIO expansion occurs unless the caller names all
eight pins. See [[NumPy-Integration]] for endianness, alignment, lifetime,
allocation, and pure-Python parity details.

Per-unit host calibration is a separate opt-in layer. Immutable schema-v1
records are keyed by the physical hardware serial and an optional exact analog
front-end profile, live only at a user-selected JSON path, and are checked
against the block identity, resolution, code range, and nominal input range
before use. `block.calibrated_channels(record, ...)` returns lazy voltage views
with `calibrated=True`, `units="V"`, and direct access to the raw block and
channels. `block.calibrated_interleaved(record, ...)` retains each sample's
`raw_code` beside its calibrated `voltage`. Neither operation changes the raw
payload or timestamps; schema-v1 timing skew is provenance-only and is not
applied. The formulas, safe-store contract, workflow, and limitations are in
[[Calibration]].

`Status.adc_acquisition` exposes the complete physical dual-DMA, pair,
framing, loss, ADC_ETC/eDMA conversion-error, lifecycle, and packer snapshot.
`Status.has_adc_errors` includes initialization and trigger errors as well as
those live counters. If a RUNNING STATUS has been polled, subsequently
delivered ADC blocks retain that immutable snapshot as `block.acquisition`;
otherwise it is `None` rather than fabricated per-frame evidence.

Production mode is the default. Each ADC/GPIO source owns an independent
run/sequence/timestamp baseline. A forward discontinuity causes `blocks()` to
emit `StreamGap` immediately before the current data block and then continue.
The report carries the acquisition source, run, expected/observed sequences,
missing tick interval, sequence- and timestamp-inferred item counts, frame
flags, statistics generation, and cumulative firmware block/item/byte
counters. Sequence and timestamp inferences must agree; `GAP_BEFORE`,
`OVERRUN_BEFORE`, and cumulative STATUS values are retained verbatim and any
disagreement appears in `FirmwareLossEvidence.errors` and
`LossCounters.telemetry_errors`.

Duplicates, reordered frames, stale-run frames, flag-only gaps, and
timestamp-inconsistent frames are distinct `StreamAnomaly` values; duplicate,
reordered, and stale data are reported but not delivered as application data.
Decoded application-queue eviction is never converted into a `StreamGap`:
`HostQueueLoss` reports the exact source, run, first/last sequence, time range,
complete block count, logical item count, and `DROP_OLDEST_COMPLETE` policy.
The serial reader continues draining while these bounded reports accumulate.
`strict=True` raises `UnexpectedStreamGapError`,
`UnexpectedStreamAnomalyError`, or `UnexpectedHostQueueLossError` promptly
with the typed report attached. START, RESET_STATS, run changes/reconnects, and
modular uint32 sequence wrap reset or advance the appropriate baselines without
joining epochs.

## Optional bounded ADC/GPIO alignment

Raw delivery remains the primary path: `read_block()` and `blocks()` expose
each typed block or loss/anomaly report as soon as the application consumes it.
Applications that need equal-time cross-stream records feed data blocks and
`StreamGap` values into `TimestampAligner`, while handling `HostQueueLoss` and
`StreamAnomaly` as application/control evidence without constructing a
combined payload:

```python
from thingdaq import AlignedInterval, AlignmentLoss, TimestampAligner

aligner = TimestampAligner(max_pending_intervals=8)

for raw_item in daq.blocks():
    # raw_item remains available immediately with its typed payload.
    for aligned_item in aligner.push(raw_item):
        if isinstance(aligned_item, AlignmentLoss):
            print("missing", aligned_item.missing_streams)
        elif isinstance(aligned_item, AlignedInterval):
            print(aligned_item.adc, aligned_item.gpio)

# Call at a finite timeout, STOP, or other application boundary.
for final_item in aligner.flush():
    print(final_item)
```

Alignment keys are the nonzero run ID and first-sample timestamp. ADC and GPIO
must select the same protocol/mode/rate profile, cover the same generated frame
interval, and report the same physical or synthetic source. The event-time
lateness window retains at most the configured
number of unresolved timestamps, accepts bounded out-of-order arrival, and
emits `AlignmentLoss` before an `AlignedInterval` whose absent side is
explicitly `None`. A skipped interval with neither side is one loss record with
an exact `interval_count`. `flush()` resolves a terminal delayed side
immediately; `align_by_timestamp()` performs that flush automatically for a
finite iterable. Per-source sequence/timestamp discontinuities remain separate
`StreamGap` events and are also attached to `AlignedInterval.stream_gaps`.

`AlignedInterval` retains the original block objects. Its
`adc_payload_view` and `gpio_payload_view` point at their original immutable
bytes, so alignment never forces an allocated combined copy. ADC pair times
remain `(t + 8n, t + 8n + 4)` with ADC0/ADC1 identity, while packed GPIO-byte
times remain `t + 2m`. `NominalEpoch` converts those ticks using the advertised
8 MHz frequency and exposes START as relative tick zero.
`NominalEpoch.external_latency_ticks` is deliberately `None`: these are
schedule times, not measurements of external GPIO-pad propagation or ADC
aperture latency.

## Production transport and background reader

`SerialTransport` configures finite PySerial read and write timeouts and adds
bounded open, flush, and close behavior. Busy, locked, and access-denied opens
raise `SerialPortBusyError`; disconnects and timeouts retain separate types. A
write may report partial progress;
`BackgroundReader` serializes concurrent command writes and retries each
unwritten suffix within the command's overall deadline. Its default 64 KiB
reads are deliberately larger than USB packets because USB CDC is one byte
stream, not a packet-preserving message API.

`BackgroundReader` owns exactly one bounded compatible v1/v2 parser. One
non-daemon thread continuously feeds arbitrary read chunks into it, matches concurrent
responses by echoed request ID, and separates decoded ADC/GPIO blocks from
other non-response frames. Pending requests, block queues, and event queues are
all bounded. Request timeout removes the pending entry; an eventual unmatched
reply increments `late_responses`. STOP, close, parser failure, and disconnect
wake blocked callers and cancel outstanding requests with typed exceptions.

Both decoded queues use a **drop-oldest complete item** policy when full. The
newest data therefore remains visible during consumer stalls. The
`host_block_queue_drops` and per-source block/item counters describe only those
local Python evictions: they never include firmware sequence gaps,
`GAP_BEFORE`/`OVERRUN_BEFORE` flags, or firmware GET_STATUS counters. A bounded
coalescing report queue preserves exact `HostQueueLoss` units independently of
the data queue. `stale_blocks_discarded` counts rejected run identities and the
facade also emits a typed `STALE_RUN` anomaly before returning current-run data.

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
from thingdaq import ThingDAQ, run_synthetic_soak

with ThingDAQ.open(hardware_serial=12345670, strict=True) as daq:
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

## Identity-pinned Windows soak command

The installed distribution includes `thingdaq-soak`, an identity-pinned
Windows COM-port validator equivalent to the standalone
`scripts/windows_soak.py` handoff. The console script executes the generated
implementation packaged as `thingdaq.soak`; it does not locate or import the
repository script. Both paths accept the same operational arguments and write
the same complete JSON plus structured-Markdown report schema:

```powershell
thingdaq-soak --duration 3600 --mode combined `
  --output thingdaq-windows-soak

thingdaq-soak --smoke --mode synthetic `
  --hardware-serial 20512460 --output thingdaq-smoke
```

Both entry paths embed and verify the deterministic Phase 11 release contract
from `firmware/soak/validation-manifest.json`. Normal execution refuses every
firmware/device INFO mismatch, including a different hardware serial, build,
version, capability mask, rate, phase, pin map, frame size, or resolution. A
COM number is discovery metadata and is never treated as persistent identity.

For diagnosis only, `--diagnostic-identity-override` permits a different
parseable identity (and permits `--hardware-serial` to select a different
unit). The console, JSON, and Markdown all mark such a run as non-release, list
the mismatched INFO fields, and force `release_eligible` to `false` even if the
stream itself passes:

```powershell
thingdaq-soak --diagnostic-identity-override `
  --hardware-serial 12345670 --smoke --output non-release-diagnostic
```

Use the bounded offline self-check to verify command encoding, fragmented frame
parsing, formula validation, rate/latency metrics, and deterministic fixture
grading without opening a COM port:

```powershell
thingdaq-soak --conformance-check
```

Repository validation additionally runs
`firmware/tools/check_soak_conformance.py` to compare the installed and
standalone implementations byte-for-byte outside role metadata and against the
golden protocol fixtures. See [[soak-harness]] and
[[Phase-11-Soak-Evidence]] for the accepted identity and claim boundaries.

## Metadata-first device discovery

Discovery never opens unrelated serial ports. `enumerate_candidates()` uses
PySerial metadata only, filters for the Teensy USB Serial VID/PID
`0x16C0:0x0483`, preserves the port path, USB serial, product, manufacturer,
location, interface, and description, and orders the exact `ThingDAQ`
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
from thingdaq import discover, enumerate_candidates, select_device

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
python -m thingdaq.demo --frame-count 2 --parser-chunk-size 17
thingdaq-demo --frame-count 2 --parser-chunk-size 17
```
