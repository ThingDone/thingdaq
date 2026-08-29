---
type: reference
title: API Reference
created: 2026-08-29
tags:
  - teensy-daq
  - python
  - api
  - reference
related:
  - '[[Quickstart]]'
  - '[[Python-API]]'
  - '[[Protocol-V1]]'
  - '[[Calibration]]'
  - '[[NumPy-Integration]]'
  - '[[Hardware-Safety]]'
---

# Python API reference

This page describes the stable synchronous user surface. Import normal
operations and immutable models from `teensy_daq`; use
`teensy_daq.low_level` only for protocol tooling that intentionally owns raw
frames, parsers, readers, or byte transports.

## Entry points

```python
from teensy_daq import TeensyDAQ, discover, enumerate_candidates, select_device
```

| Entry point | Behavior |
| --- | --- |
| `enumerate_candidates()` | Metadata-only VID/PID filter; opens no ports |
| `discover(timeout=...)` | Bounded read-only INFO probe of plausible candidates |
| `select_device(devices, hardware_serial=...)` | Selects stable INFO/USB serial identity, never a cached port path |
| `TeensyDAQ.open(...)` | Opens transport/device/port/discovered target or performs discovery; synchronizes stable INFO |
| `TeensyDAQ.simulated(...)` | Opens the deterministic protocol peer through `InMemoryTransport` |

`TeensyDAQ.open(hardware_serial=N)` is the recommended physical selection.
`expected_identity=ExpectedDeviceIdentity(...)` can additionally pin exact
firmware/build/board/MCU/protocol identity. `session_policy="adopt"` is the
default; use `"stop"` to force an existing CONFIGURED/RUNNING device to IDLE.

Both constructors return a typed context manager. `close()` normally attempts
STOP before deterministic shutdown. `close(stop=False)` deliberately preserves
device state and should be limited to tools that explicitly need it.

## Identity and capabilities

`daq.info()` returns `DeviceInfo`; the last synchronized value is also
`daq.device_info`. Key fields include:

- `hardware_serial`, `firmware_version`, `build_id`, `board_id`, `mcu_id`;
- `device_state`, applied stream/source/checksum, and protocol version;
- supported stream/source/checksum/profile/capability masks;
- 8 MHz timestamp frequency and fixed frame sizes;
- ADC rate, phase, resolution/range, A0/A1 route, initialization calibration,
  trigger, DMA, and resource metadata; and
- GPIO rate, D6-D13 bit order, ring/resource metadata, and diagnostic policy.

`info.capabilities` returns `DeviceCapabilities` with:

```python
caps.supports_source(source)
caps.supports_checksum(algorithm)
caps.supports_configuration(configuration)
caps.supports(capability_bit)
caps.supported_checksum_algorithms
```

Models reject reserved bits, inconsistent masks, wrong fixed protocol values,
and incompatible applied configurations at decode time.

## Configure, start, and stop

Convenience configuration:

```python
applied = daq.configure(
    adc=True,
    gpio=True,
    source=Source.HARDWARE,
    checksum_algorithm=ChecksumAlgorithm.ADLER32,
    adc_pair_rate_hz=1_000_000,
    gpio_sample_rate_hz=4_000_000,
    adc_resolution_bits=12,
)
```

Or pass an explicit wire model:

```python
request = DAQConfiguration(
    stream_mask=StreamMask.ADC | StreamMask.GPIO,
    source=Source.SYNTHETIC,
    data_checksum_algorithm=ChecksumAlgorithm.CRC32C,
)
applied = daq.configure(
    request,
    adc_pair_rate_hz=1_000_000,
    gpio_sample_rate_hz=4_000_000,
    adc_resolution_bits=12,
)
```

The three numeric keywords are exact INFO preconditions, not CONFIGURE body
fields. A requirement for a disabled stream is invalid. Unsupported
stream/source/profile/checksum/rate/resolution selections raise
`DeviceCapabilityError` before CONFIGURE is written. The returned
`DAQConfiguration` is the exact device echo. A changed echo raises
`UnexpectedMessageError` while retaining the observed state for cleanup.

`daq.start()` requires CONFIGURED, verifies the echoed applied configuration,
activates a new nonzero run ID, and returns it. `daq.stop()` is idempotent in
IDLE/CONFIGURED/RUNNING and returns `DeviceState.IDLE`. `daq.configuration`,
`daq.state`, and `daq.run_id` expose the facade's latest authoritative state.

`configure_control_only()` exists for older zero-stream Phase 03 firmware; it
is not a way to request disabled acquisition from production firmware.

## Stream iteration

```python
item = daq.read_block(timeout=0.5)
for item in daq.blocks(count=10, timeout=0.5):
    ...
```

`blocks(count=N)` counts only `ADCBlock`/`GPIOBlock`; any loss reports are
additional yielded items. With `strict=False`, `StreamItem` is:

```text
ADCBlock | GPIOBlock | StreamGap | HostQueueLoss | StreamAnomaly
```

With `strict=True`, unexpected gap/queue-loss/anomaly/health evidence raises a
typed exception instead of becoming an ordinary item.

## ADCBlock

Important properties and methods:

| Member | Meaning |
| --- | --- |
| `run_id`, `sequence`, `first_sample_ticks`, `flags` | Wire identity and continuity |
| `item_count` | 1,012 converter pairs |
| `adc0`, `adc1` | Lazy unchanged raw-code views for A0/A1 |
| `pair(i)` / `pairs()` | One or all `(ADC0, ADC1)` pairs |
| `pair_ticks(i)` / `pair_seconds(i)` | Nominal ADC0/ADC1 times |
| `interleaved()` | ADC0 then ADC1 `AdcSample` iterator with identity/ticks |
| `resolution_bits`, `code_range`, `source` | Applied data interpretation |
| `calibration`, `trigger`, `acquisition` | Firmware evidence attached to the block |
| `calibrated_channels(record, ...)` | Explicit lazy voltage channel views |
| `calibrated_interleaved(record, ...)` | Explicit timestamped voltage samples |
| `as_numpy()` | Lazy optional NumPy integration |

For pair `i`, ADC0 is at `t0 + 8i` ticks and ADC1 at `t0 + 8i + 4` ticks.
`AdcSample` includes `pair_index`, `converter`, `pin`, `code`, and
`timestamp_ticks`. Interleaving does not increase analog bandwidth; see
[[Hardware-Safety]].

## GPIOBlock

Important properties and methods:

| Member | Meaning |
| --- | --- |
| `run_id`, `sequence`, `first_sample_ticks`, `flags` | Wire identity and continuity |
| `item_count` | 4,048 packed snapshots |
| `samples` / `payload_view` | Read-only packed-byte view |
| `sample(i)` | One packed D6-D13 byte |
| `sample_ticks(i)` / `sample_seconds(i)` | Nominal time at `t0 + 2i` ticks |
| `channel(pin)` | Lazy Boolean view for exactly one D6-D13 pin |
| `as_numpy()` | Optional zero-copy packed array and selected-channel operations |

The bit map is fixed: D6 through D13 occupy bits 0 through 7. There is no eager
eight-channel expansion.

## Calibration

Stable public names include:

- `CalibrationRecord`, `CalibrationDatabase`, `CalibrationStore`, and
  `CalibrationKey`;
- `ConverterCalibration`;
- `estimate_offset_gain()`, `apply_correction()`, and `apply_corrections()`;
- `save_calibration(path, record)` and
  `load_calibration(path, serial, profile, ...)`; and
- `calibrated_channels()` / `calibrated_interleaved()`.

There is no default calibration path. Records are immutable, schema-versioned,
atomically written to an explicit path, and matched against serial, optional
case-sensitive profile, resolution, complete code range, and nominal input
range before use. Calibrated results retain source blocks, raw codes,
provenance, and a visible `calibrated=True` marker. Residual timing skew is
recorded but not applied. See [[Calibration]].

## Timestamp alignment

`TimestampAligner(max_pending_intervals=N)` accepts `ADCBlock`, `GPIOBlock`, or
`StreamGap` through `push()`. It returns zero or more:

```text
AlignedInterval | AlignmentLoss | StreamGap
```

`flush()` marks unresolved sides at an explicit wall-clock/STOP boundary;
`finish()` marks end-of-input and rejects later pushes. `AlignedInterval`
retains both blocks, run/source, first/end ticks, present/missing streams, and
nominal seconds. `align_by_timestamp(iterable, ...)` is the finite iterable
convenience form.

## STATUS, loss, and reconciliation

`daq.status()` returns the full immutable firmware `Status`. Its nested
`counters`/ADC evidence expose per-source acquisition, framing, transmission,
drop, queue, parser, transport, lifecycle, and diagnostic values.

`daq.loss_counters(refresh=True)` returns `LossCounters` containing independent:

- `firmware: FirmwareLossEvidence`;
- `host: HostCounters`;
- observed stream-gap, host-queue-loss, and anomaly counts; and
- protocol telemetry disagreement evidence.

`daq.validate_stream_health(status=None)` returns a healthy STATUS or raises
`UnexpectedStreamValidationError`. `reconcile_run_counters(status, run_id=...)`
returns a detailed `RunCounterReconciliation` with conservation equations and
fault snapshot. Applications should inspect both live events and cumulative
counters.

## Exceptions

| Category | Principal public exception |
| --- | --- |
| Closed/illegal lifecycle | `DAQClosedError`, `DAQStateError` |
| Unsupported request | `DeviceCapabilityError` |
| Typed firmware rejection | `DeviceCommandError` |
| Bounded command/block wait | `CommandTimeoutError`, `BlockTimeoutError` |
| Identity/synchronization | `DeviceIdentityMismatchError`, `DeviceSynchronizationError` |
| Discovery selection | `DeviceNotFoundError`, `MultipleDevicesFoundError` |
| Disconnect/protocol | `DeviceDisconnectedError`, `ReaderProtocolError`, `ProtocolError` |
| Loss/anomaly/health | `UnexpectedStreamGapError`, `UnexpectedHostQueueLossError`, `UnexpectedStreamAnomalyError`, `UnexpectedStreamValidationError` |
| Calibration | `CalibrationFormatError`, `CalibrationMismatchError` |
| Cleanup | `DAQShutdownError` |

Transport-specific open, busy, timeout, and disconnect errors are also public.
Command timeouts and terminal reader failures carry `RecoveryEvidence` when
available.

## CLI and examples

The `teensy-daq` console script provides metadata-only `list`, INFO (`info` or
`probe`), STATUS, reconciliation, configure/start/stop/reset, and bounded
monitor/capture commands. `--json` emits one machine-readable document.
Capture can select raw or explicitly calibrated ADC previews, selected GPIO
channels, strict loss policy, and simulator mode. SIGINT/SIGTERM are converted
into cleanup-aware interruption so STOP is attempted before exit 130.

All repository examples run against the simulator by default; the physical
path requires `--real`. See [[Quickstart]] for the exact commands and hardware
requirements.
