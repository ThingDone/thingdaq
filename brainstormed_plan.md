# ThingDAQ brainstormed plan

> Status: working design notes, not a formal specification.
>
> This document consolidates the initial README review, the confirmed product
> decisions, hardware research, protocol ideas, implementation options, risks,
> and proposed validation work. A later planning pass should turn the selected
> ideas into explicit requirements, interfaces, milestones, and acceptance
> criteria.

## 1. Product intent

Build reusable Teensy 4.0 firmware and a native Python package that together
form a small streaming data-acquisition system for live customer applications.

The device has two continuous acquisition sources:

1. Two ADC peripherals, each sampling at 1 MS/s. ADC1 samples 500 ns after
   ADC0, allowing a user who feeds the same signal to A0 and A1 to form a
   nominal 2 MS/s interleaved stream.
2. Eight digital inputs sampled as a group at 4 MS/s.

The Teensy sends framed binary data over native USB CDC, which appears as a
serial/COM port. A Python API discovers the correct device, configures it,
starts and stops acquisition, parses the two streams, reports loss, and offers
helpers for interleaving the ADC channels.

The interleaved ADC mode increases sample density but does not increase the
analog bandwidth of the Teensy input path. It is useful for smoother-looking
plots and interpolation.

## 2. Confirmed decisions from the initial discussion

| Topic | Confirmed direction |
| --- | --- |
| Target | Teensy 4.0 / i.MX RT1062 |
| ADC rate | ADC0 and ADC1 each run continuously at 1 MS/s |
| ADC phase | ADC1 is intentionally sampled 500 ns after ADC0 |
| ADC pins | A0 and A1 |
| ADC combined view | A user may feed the same signal to both pins and combine them into a nominal 2 MS/s stream |
| Digital pins | Reserving header pins D6 through D13 is acceptable |
| Digital rate | Eight pins sampled at 4 MS/s |
| Startup | Device boots idle and starts acquisition only after an explicit command |
| Discovery | Identification must be rapid even when the PC has many serial ports |
| Overrun behavior | Continue acquiring and report loss; do not stop acquisition |
| Normal testing | Prove that the complete ADC plus GPIO stream can be sustained without loss |

## 3. Important semantic clarifications

### 3.1 ADC terminology

This is not synchronized simultaneous dual-channel acquisition. It is a
deliberately phase-shifted pair:

~~~text
time:   0.0   0.5   1.0   1.5   2.0   2.5 microseconds
        ADC0  ADC1  ADC0  ADC1  ADC0  ADC1
~~~

For each integer n:

- ADC0[n] has nominal time n microseconds.
- ADC1[n] has nominal time n microseconds + 0.5 microseconds.
- A combined stream is ADC0[0], ADC1[0], ADC0[1], ADC1[1], and so on.

The firmware and API should always retain the raw identity of both converters.
Combining them should be an explicit Python operation, not an irreversible
firmware transformation.

### 3.2 Physical meaning of the combined ADC stream

Firmware cannot make one analog signal appear on both pins. To combine the
streams, the board or user wiring must drive the same signal into A0 and A1.
That has analog consequences:

- The source drives two sample-and-hold inputs rather than one.
- A low source impedance may be necessary at the fastest ADC setting.
- Buffering and anti-alias filtering may be required for a customer-ready
  analog front end.
- A0 and A1 are limited to the Teensy analog range and are not 5 V tolerant.
- The two ADCs will have different offset and gain.
- Trigger timing can be exact while their true analog aperture delays still
  differ slightly.

The Python API should therefore expose both raw channels and make calibration
optional and visible.

### 3.3 Loss semantics

USB CDC is reliable at the USB packet level, but data can still be lost before
USB transmission if firmware buffers overrun, or effectively lost to the
application if the host cannot drain its queues. Every loss must be observable
through sequence numbers, timestamps, and cumulative counters.

## 4. Pinned target and build identity

Use the proven target information from:

/home/bill/agents/fw_experiments/docs/guides/new-firmware-projects.md

Initial build identity:

- Board: Teensy 4.0
- MCU: i.MX RT1062, Cortex-M7
- CPU clock: 600 MHz
- Arduino CLI FQBN: teensy:avr:teensy40
- Teensy core: teensy:avr 1.62.0
- Installed core:
  /home/bill/.arduino15/packages/teensy/hardware/avr/1.62.0
- Installed compiler:
  /home/bill/.arduino15/packages/teensy/tools/teensy-compile/15.2.1/arm/bin/arm-none-eabi-gcc
- Compiler family/version in the pinned package: Arm GNU 15.2.1

The word avr in the package name is not the processor architecture.
Conditional low-level code should use ARDUINO_TEENSY40 and/or __IMXRT1062__.

The formal plan should pin all relevant Teensy build menu options as well as
the base FQBN, including USB type, CPU speed, and optimization. Core upgrades
must be deliberate because they can change USB buffering, clock setup,
libraries, startup code, and linker behavior.

## 5. Proposed timing architecture

### 5.1 Clock-domain observation

The normal Teensy peripheral/IPG clock is 150 MHz:

- 150 MHz divides exactly to 1 MHz.
- 75 IPG cycles equal exactly 500 ns.
- 150 MHz does not divide exactly to 4 MHz.

The Teensy startup code configures PIT/GPT to run from a 24 MHz clock:

- 24 MHz divides exactly to 4 MHz with six source clocks per sample.
- Four 4 MHz periods give exactly one 1 MHz period.
- 24 MHz also divides exactly to the proposed 8 MHz timestamp scale.

This makes a PIT-based master schedule promising for exact nominal rates.

### 5.2 Preferred clock topology to prove

Candidate topology:

~~~text
24 MHz PIT clock
    |
    +-- PIT channel 0: divide by 6 -> exact 4 MHz event
    |       |
    |       +-- XBAR -> DMA request -> GPIO2_PSR capture
    |
    +-- PIT channel 1: chained divide by 4 -> exact 1 MHz event
            |
            +-- XBAR -> ADC_ETC trigger 0 -> ADC0
            |
            +-- XBAR -> ADC_ETC trigger 4
                    with +75 IPG-clock relative delay -> ADC1
~~~

Relevant hardware definitions in the pinned core include PIT_TRIGGER0 through
PIT_TRIGGER3 as XBAR inputs. PIT channels support chaining.

Candidate register arithmetic, subject to hardware proof:

- PIT channel 0 load value 5 gives a period of 6 clocks at 24 MHz, or 4 MHz.
- PIT channel 1 chained to channel 0 with load value 3 gives one event per four
  channel-0 expirations, or 1 MHz.
- ADC_ETC trigger queues run asynchronously.
- Both ADC trigger queues receive the same 1 MHz source event.
- The second queue's initial delay differs by 75 cycles of the 150 MHz
  ADC_ETC/IPG clock, producing a 500 ns relative phase.

The ADC_ETC initial-delay formula uses its global predivider and IPG clock.
Because the delay formula includes a minimum one-clock delay, choose the two
register values based on their difference, not merely an absolute intuitive
value. For example, values whose effective counts differ by 75 cycles produce
the desired relative delay.

### 5.3 Timing items that require measurement

The following must be proven rather than inferred:

- PIT trigger behavior when a channel is chained.
- Routing a PIT event through XBAR to an eDMA request at 4 MHz.
- Routing one PIT/XBAR input to both ADC_ETC trigger outputs.
- ADC_ETC asynchronous trigger queue selection for ADC0 versus ADC1.
- Actual 500 ns trigger separation at the ADC hardware interface.
- Fixed latency and any jitter introduced when a 24 MHz PIT event crosses into
  the 150 MHz ADC_ETC clock domain.
- True ADC aperture separation, which may differ slightly from digital trigger
  separation.
- Resource conflicts with IntervalTimer or other libraries that use PIT.

Useful proof techniques include exporting related timer or trigger signals to
debug pins, toggling pins from DMA-completion instrumentation at low test
rates, and measuring a known waveform applied to both ADC inputs.

### 5.4 Alternative timing topology

The bundled ADC library uses QuadTimer4 channel 0 for ADC0 and channel 3 for
ADC1, routed through XBAR to ADC_ETC trigger queues 0 and 4. Its public
startTimer API configures and starts the timers independently and has no phase
control. It is useful reference code, but it should not be the final timing
mechanism without a lower-level synchronized configuration.

If the PIT topology does not work as expected, alternatives include:

- Two synchronized QuadTimer outputs with an explicit half-period phase.
- FlexPWM-generated trigger events.
- A 2 MHz master event split into alternating converter triggers.
- A slightly non-exact GPIO rate derived from the 150 MHz domain, only if the
  4 MHz requirement is not exact.

Exact-rate PIT/XBAR behavior should be investigated before choosing an
alternative.

## 6. ADC acquisition design

### 6.1 Pin routing feasibility

The pinned ADC library maps A0 and A1 as valid inputs on both ADC peripherals:

- ADC0 table:
  /home/bill/.arduino15/packages/teensy/hardware/avr/1.62.0/libraries/ADC/ADC.cpp
- ADC1 table in the same file.

Dedicate one peripheral to A0 and the other to A1. Preserve which physical ADC
is first in the protocol and never allow it to depend on initialization order.

### 6.2 Converter configuration

Initial recommendation:

- 12-bit result format stored in a 16-bit unsigned word.
- No hardware averaging at 1 MS/s.
- High-speed ADC conversion mode.
- Fast sampling mode only after checking analog source requirements.
- Calibrate both ADC modules at startup before enabling their timers.
- Treat roughly 10 effective bits as a realistic board-level expectation until
  measured.

The NXP data sheet gives approximately 0.7 microseconds for the fastest
12-bit conversion at a 40 MHz ADC clock. That fits within the 1 microsecond
period for each independent converter, but leaves limited margin. Configuration
and hardware testing must confirm:

- Every conversion completes before that ADC's next trigger.
- No ADC_ETC trigger error occurs.
- No conversion result is overwritten.
- Fast sampling still settles for the intended source impedance.
- Temperature, voltage, and different Teensy boards do not break the margin.

If 12-bit mode cannot be sustained robustly, an explicit decision is needed
between 10-bit mode, a lower sample rate, or external ADC/front-end hardware.
Do not silently alter the advertised configuration.

### 6.3 Direct interleaved DMA buffer idea

Use two eDMA channels that write into one logical sample-pair buffer:

~~~text
buffer base + 0: adc0[0]
buffer base + 2: adc1[0]
buffer base + 4: adc0[1]
buffer base + 6: adc1[1]
...
~~~

Candidate TCD behavior:

- ADC0 destination starts at buffer base with destination stride 4.
- ADC1 destination starts at buffer base + 2 with destination stride 4.
- Each channel transfers a 16-bit ADC result per conversion.
- Both channels use equal major-loop lengths.
- Scatter/gather or linked TCDs rotate through multiple buffers.
- A buffer is ready for consumers only after both DMA channels have completed
  their major loop for that buffer; ADC1 will naturally finish later.

This could produce protocol-ready ADC payloads without a CPU interleaving
copy. It must be checked for safe concurrent writes, completion races, DMA
channel priorities, and cache coherence.

### 6.4 ADC timestamp model

Recommended protocol timebase: unsigned 64-bit ticks at 8 MHz.

For an ADC frame whose first ADC0 sample is at t0:

- ADC0 pair n is at t0 + 8*n ticks.
- ADC1 pair n is at t0 + 8*n + 4 ticks.
- The combined stream has one sample every 4 ticks.

The frame header timestamp is the nominal time of its first ADC0 sample.
Capabilities or configuration metadata must explicitly advertise:

- pair rate = 1,000,000 pairs/second;
- ADC0 phase = 0 ticks;
- ADC1 phase = 4 ticks;
- combined nominal rate = 2,000,000 samples/second.

Use acquisition sample counters to construct timestamps. Do not timestamp a
buffer in its DMA interrupt, because interrupt latency is unrelated to sample
time.

### 6.5 ADC mismatch and calibration

Interleaving two ADCs can make gain, offset, and timing mismatch visible as an
alternating artifact. Suggested API model:

- Always expose raw adc0 and adc1.
- Provide an explicit interleave helper.
- Allow per-converter offset and gain correction.
- Later allow a fractional residual timing-skew correction if measurements
  justify it.
- Key saved calibration by the Teensy's hardware serial number and possibly an
  analog-front-end/profile identifier.
- Report whether returned combined data is raw or calibrated.

Possible calibration workflow:

1. Feed both pins the same stable low level.
2. Feed both pins a stable high level.
3. Estimate offset and gain differences.
4. Feed a suitable sine or edge waveform.
5. Estimate residual timing skew if needed.
6. Store calibration with provenance and date.

Initially, host-side calibration is simpler and safer than modifying raw
firmware samples.

## 7. GPIO acquisition design

### 7.1 Selected pins and source bits

D6 through D13 all map to the Teensy fast GPIO7 register and are accessible on
the breadboard headers.

| Teensy pin | GPIO7/GPIO2 source bit |
| --- | ---: |
| D6 | 10 |
| D7 | 17 |
| D8 | 16 |
| D9 | 11 |
| D10 | 0 |
| D11 | 2 |
| D12 | 1 |
| D13 | 3 |

These mappings are in:

/home/bill/.arduino15/packages/teensy/hardware/avr/1.62.0/cores/teensy4/core_pins.h

### 7.2 Fast versus standard GPIO

Teensy startup normally selects tightly coupled GPIO6 through GPIO9. eDMA
operates against standard GPIO1 through GPIO4 rather than those fast aliases.
For D6 through D13:

- Clear only the corresponding bits in IOMUXC_GPR_GPR27.
- This reroutes those pads from GPIO7 to GPIO2.
- Configure direction through GPIO2_GDIR rather than relying on pinMode after
  remapping.
- Read input state from GPIO2_PSR.
- Avoid changing unrelated GPR bits or unrelated GPIO2 pins.

The bundled OctoWS2811 implementation demonstrates selective GPR remapping and
timer/XBAR-triggered DMA:

/home/bill/.arduino15/packages/teensy/hardware/avr/1.62.0/libraries/OctoWS2811/OctoWS2811_imxrt.cpp

### 7.3 DMA and packing

Preferred capture path:

1. Exact 4 MHz PIT event.
2. XBAR routes that event to a DMA request.
3. DMA copies a fixed 32-bit GPIO2_PSR source into a rotating raw-word buffer.
4. CPU code packs the selected eight bits into one byte per sample in batches.
5. Packetizer transmits the packed byte stream.

Do not use a 4 MHz per-sample interrupt. At 600 MHz that provides only about
150 core cycles between samples before accounting for interrupt entry/exit,
ADC work, USB, cache effects, and other interrupts.

The raw internal GPIO DMA stream is 16 MB/s because it stores one 32-bit port
word per 4 MHz sample. The packed external stream is 4 MB/s.

Two possible wire bit orders:

1. User-friendly order: bit 0 through bit 7 correspond to D6 through D13.
2. Packing-friendly order:
   D10, D12, D11, D13, D6, D9, D8, D7, corresponding to source groups
   0-3, 10-11, and 16-17.

Prefer the user-friendly D6-through-D13 order unless profiling shows packing
to be a real bottleneck. The firmware can still use an optimized internal
mapping or lookup operation, and INFO must publish the mapping. Never leave
bit order implicit.

### 7.4 GPIO timestamp model

At an 8 MHz timestamp scale:

- GPIO sample m is at t0 + 2*m ticks.
- Each packed payload byte represents all eight pins at one nominal instant.
- The frame timestamp is the nominal time of its first GPIO sample.

If ADC and GPIO start from one hardware schedule, define and measure their
relative epoch. Any fixed peripheral or cross-domain latency should be
documented rather than guessed from DMA interrupt timing.

### 7.5 GPIO fallback options

If standard-GPIO DMA cannot sustain the requirement:

- Investigate FlexIO parallel input with DMA, noting that eight convenient
  header pins may not map to eight consecutive FlexIO shifter pins.
- Investigate the CSI parallel capture peripheral if its exposed pin mapping
  is usable.
- Consider keeping raw 32-bit words on the wire temporarily for a throughput
  proof, accepting 16 MB/s of GPIO payload.
- Use a carefully optimized CPU sampling loop only as a bounded experiment,
  not the default architecture.

## 8. Data-rate and memory budget

### 8.1 Packed payload rates

| Stream | Calculation | Payload rate |
| --- | --- | ---: |
| ADC | 2 converters * 1 MS/s * 2 bytes | 4 MB/s |
| GPIO | 4 MS/s * 1 packed byte | 4 MB/s |
| Combined | ADC + GPIO | 8 MB/s |

At the original 16-byte frame overhead and one 512-byte frame, payload is only
496 bytes and wire overhead is about 3.2 percent. Larger application frames
reduce parser, checksum, and dispatch overhead while USB still transmits
512-byte high-speed packets internally.

### 8.2 Candidate 4096-byte data frame

A 4096-byte total data frame is a useful starting point:

- It is a multiple of the 512-byte high-speed USB packet size.
- It keeps latency around one millisecond.
- It dramatically reduces application-frame rate compared with 512-byte
  messages.
- It must not be treated as one indivisible USB transaction on the host.

With the candidate 32-byte header plus 4-byte trailer described later, payload
is 4060 bytes:

- ADC: 1015 four-byte sample pairs, representing 1015 microseconds.
- GPIO: 4060 one-byte samples at 4 MHz, also representing 1015 microseconds.

This means one ADC frame and one GPIO frame cover the same nominal interval,
which is convenient for reassembly and scheduling.

Approximate wire rate for both packed streams with this framing is:

8 MB/s * 4096 / 4060 = about 8.071 MB/s, plus occasional status and command
responses.

### 8.3 Internal bandwidth

Likely internal traffic includes:

- 4 MB/s ADC DMA writes.
- 16 MB/s raw GPIO DMA writes.
- 16 MB/s CPU reads of raw GPIO words.
- 4 MB/s CPU writes of packed GPIO bytes.
- Roughly 8 MB/s of checksum reads.
- Roughly 8 MB/s of USB reads from framed buffers.

This is plausible for the RT1062 but should be measured, especially with cache
maintenance and OCRAM contention.

### 8.4 Buffering

Teensy 4.0 has 1 MB of RAM split across regions with different cache and bus
properties. DMA buffers should:

- Live in DMA-accessible memory, likely DMAMEM/OCRAM.
- Be aligned to at least 32-byte cache lines.
- Use explicit cache flush/invalidate/delete operations correctly.
- Have explicit ownership states so DMA, packer, packetizer, and USB never
  access a buffer inconsistently.
- Use multiple rotating buffers rather than only one ping-pong pair if host
  scheduling jitter requires more slack.

At 8 MB/s, buffering durations are short:

- 64 KiB covers about 8 ms of packed payload.
- 128 KiB covers about 16 ms.
- 256 KiB covers about 32 ms.

The system cannot compensate for a host that stops reading for long periods.
Its purpose is to remain live and report the resulting dropped blocks.

## 9. Firmware architecture

Suggested modules:

- board_config: exact pins, clock assumptions, build identity.
- acquisition_clock: PIT/XBAR/ADC_ETC setup and shared epoch.
- adc_capture: ADC configuration, calibration, DMA ring.
- gpio_capture: GPIO remapping, DMA ring, bit packing.
- sample_clock: 64-bit acquisition counters and timestamp conversion.
- frame_codec: headers, payload metadata, checksum.
- packetizer: converts ready source blocks into complete frames.
- usb_transport: non-blocking/ bounded USB CDC writes and command reads.
- command_parser: bounded incremental command decoding.
- control_state: IDLE, CONFIGURED, RUNNING, and fault/status handling.
- statistics: produced, transmitted, dropped, corrupt, queue-depth, and
  timeout counters.
- test_source: deterministic synthetic ADC and GPIO generation.
- firmware_identity: protocol version, firmware version, build ID, and feature
  capabilities.

Likely control states:

~~~text
BOOT -> IDLE -> CONFIGURED -> RUNNING
          ^          |           |
          +----------+-----------+
                   STOP
~~~

Behavioral rules:

- Boot is bounded and never waits forever for Serial.
- IDLE answers INFO and configuration commands but emits no data stream.
- START resets or snapshots the acquisition epoch, arms buffers, and enables
  hardware in a deterministic order.
- STOP disables triggers cleanly and returns to IDLE.
- Repeated INFO and STOP commands are idempotent.
- ISRs do the minimum work: clear hardware status, rotate ownership, increment
  counters, and signal the main processing path.
- No ISR calculates checksums, parses commands, performs USB writes, or packs a
  large GPIO buffer.
- All waits, retries, and USB operations have bounds.

An RTOS is not obviously necessary. A cooperative main loop plus DMA
interrupts and explicit queues may be smaller and more deterministic. Use an
RTOS only if the simpler architecture cannot meet command responsiveness and
buffer ownership requirements.

## 10. Overrun and backpressure policy

Confirmed high-level policy: acquisition continues and loss is reported.

Recommended detailed policy:

1. DMA continues running independently of USB progress.
2. Source rings contain complete acquisition blocks with explicit ownership.
3. Packetizer creates complete frames before they enter the USB transmit
   queue.
4. Once any bytes of a frame have been sent, transport finishes that frame
   before moving to another. It never abandons a partial frame and thereby
   corrupts byte-stream framing.
5. If the ready/transmit queue is full before a new complete block can be
   admitted, discard the oldest unsent complete block so live data remains
   current.
6. Increment cumulative counters for dropped blocks and dropped samples for
   the affected source.
7. Mark the next transmitted frame with an overrun/gap flag.
8. Sequence and timestamp discontinuities independently reveal the exact gap.

Counters to consider:

- ADC conversions produced.
- ADC sample pairs framed.
- ADC sample pairs dropped.
- ADC DMA buffer overruns.
- GPIO samples produced.
- GPIO samples packed.
- GPIO samples dropped.
- GPIO DMA buffer overruns.
- Data frames produced/transmitted/dropped per type.
- USB partial-write count.
- USB write-stall or timeout count.
- Maximum ready-queue depth.
- Maximum transmit-queue depth.
- Command frames received/rejected.
- Bad command checksum/length/type counts.
- ADC_ETC trigger errors and missed/overwritten conversions.

Normal sustained-transfer tests fail if any loss or overrun counter is
nonzero. A separate negative test deliberately stops host reads and verifies
continued acquisition, accurate counters, a visible timestamp/sequence gap,
and parser recovery.

## 11. Binary protocol brainstorm

### 11.1 Protocol goals

- Versioned and evolvable.
- Easy to parse incrementally from arbitrary serial read boundaries.
- Easy to resynchronize after noise, reconnect, or a truncated read.
- Fixed unambiguous integer sizes and byte order.
- Explicit timestamp semantics.
- Explicit sample count and layout.
- Independent loss detection by sequence and time.
- Commands and responses coexist with data without ambiguity.
- Efficient in 512-byte USB packets without assuming USB packet boundaries.
- Golden byte-level test vectors shared by firmware and Python.

### 11.2 Candidate data-frame layout

The exact formal layout remains a decision, but this is a useful 32-byte
header candidate:

| Offset | Size | Field |
| ---: | ---: | --- |
| 0 | 4 | Magic, 0xDEADBEEF |
| 4 | 1 | Protocol version |
| 5 | 1 | Frame kind |
| 6 | 2 | Flags |
| 8 | 4 | Total frame bytes |
| 12 | 4 | Payload bytes |
| 16 | 4 | Per-kind sequence number |
| 20 | 8 | First-sample timestamp in 8 MHz ticks |
| 28 | 4 | Item/sample-pair count |
| 32 | variable | Payload |
| final 4 | 4 | Adler-32 or CRC-32C |

For a 4096-byte total frame, this leaves 4060 payload bytes.

Fields and serialization must be explicitly little endian if that direction
is selected. The little-endian bytes for 0xDEADBEEF are EF BE AD DE. Do not
leave endianness as an implication of the ARM host.

### 11.3 Candidate frame kinds

- ADC data.
- GPIO data.
- Status/telemetry.
- Command response.
- Asynchronous event.
- Synthetic/test data, or ordinary ADC/GPIO frames with a test-mode flag.

Keep numeric values centralized in one protocol definition and test them
across C++ and Python.

### 11.4 ADC payload

Recommended logical payload:

~~~text
uint16 adc0[0]
uint16 adc1[0]
uint16 adc0[1]
uint16 adc1[1]
...
~~~

Header item count is the number of ADC pairs, not the number of 16-bit words.
The advertised metadata supplies:

- ADC0 pin A0.
- ADC1 pin A1.
- pair period 8 ticks.
- ADC1 phase 4 ticks.
- resolution and container width.
- raw code range and reference/range information.

### 11.5 GPIO payload

Recommended logical payload:

~~~text
byte sample[0]  # all eight inputs at t0
byte sample[1]  # all eight inputs at t0 + 2 ticks
...
~~~

Header item count equals payload bytes for the packed eight-channel format.
Capabilities and INFO publish the exact bit-to-Teensy-pin map.

### 11.6 Timestamp

Use unsigned 64-bit ticks at 8 MHz, relative to a defined acquisition epoch.

Reasons:

- 125 ns ticks represent the 4 MHz GPIO period as 2 ticks.
- They represent the ADC pair period as 8 ticks.
- They represent the ADC phase offset as 4 ticks.
- A 32-bit value would wrap after only 536.870912 seconds.
- A 64-bit value effectively removes wrap handling from ordinary sessions.

Define whether START resets the timestamp to zero or returns a new epoch ID
while a monotonic device clock continues. A simple first version can reset the
stream epoch to zero on START and include a new acquisition/run identifier in
INFO/status or frame flags.

### 11.7 Sequence numbers

Use a separate monotonically increasing sequence per frame kind/stream.
Document wrap semantics. A host should report:

- missing frames;
- duplicated frames;
- reordered frames;
- timestamp discontinuities;
- differences between inferred missing samples and firmware drop counters.

### 11.8 Checksum

The README currently calls for standard Adler-32. That is inexpensive and can
support framing validation, while USB itself already performs CRC and retry.
CRC-32C would give stronger accidental-error detection and is worth
considering because there is no compatibility burden yet.

Whichever is selected, specify:

- exact algorithm and initialization;
- final xor if applicable;
- which bytes are covered;
- whether the checksum field is excluded or treated as zero;
- serialized byte order;
- canonical empty and nonempty test vectors.

The checksum is not a security mechanism.

### 11.9 Resynchronization

The Python parser must not trust that one read equals one frame. It should:

1. Accumulate arbitrary byte chunks.
2. Scan for magic.
3. Validate version, kind, header size, frame size, payload size, and maximums.
4. Wait for the declared complete frame.
5. Validate checksum.
6. On failure, advance carefully and resume scanning.
7. Handle multiple complete frames in one read.
8. Preserve a bounded suffix when a possible magic prefix spans reads.

Magic can naturally occur in a payload, so plausible metadata and checksum are
part of resynchronization.

### 11.10 USB alignment

Data frames may be fixed at 4096 bytes or another multiple of 512, but USB CDC
remains a byte stream:

- A frame can arrive across many serial reads.
- One read can contain several frames.
- A 4096-byte write becomes multiple USB transfers.
- Application framing must never depend on a USB short packet.

Teensy USB Serial ignores the configured baud rate and operates at native USB
speed. Host code should use large block reads and writes, not byte-at-a-time
calls.

### 11.11 Command framing

Commands do not need 512-byte alignment. Two plausible designs:

1. A compact command envelope sharing magic/version/length/checksum fields.
2. The same general frame header with variable total size and command-specific
   payloads.

Prefer sharing parsing and validation machinery without forcing meaningless
data-only fields into commands. Commands should contain a request ID so
responses can be matched even while data frames are arriving.

Device-to-host responses use typed frames and therefore can be demultiplexed
from data on the same CDC stream.

## 12. Initial command set

Keep the first version small:

- INFO or GET_CAPABILITIES
  - protocol version;
  - firmware semantic version;
  - build ID/hash;
  - board and MCU identity;
  - hardware serial number;
  - supported streams, rates, phase offsets, and pin maps;
  - maximum frame and queue sizes.
- GET_STATUS
  - current state;
  - active configuration;
  - run/acquisition ID;
  - all overrun and transport counters;
  - queue depths and hardware error flags.
- CONFIGURE
  - enable ADC and/or GPIO;
  - select normal or synthetic source;
  - possibly choose frame size from a constrained set;
  - later select ADC resolution or calibration mode.
- START
  - starts a new acquisition run;
  - returns run ID and exact applied configuration.
- STOP
  - idempotently returns to IDLE.
- RESET_STATS
  - clears counters only when semantics are safe and explicit.
- PING
  - optional, because INFO already supplies a strong identity probe.

Every response should include request ID, success/error status, and a bounded
machine-readable error code. Unknown command versions or payloads must be
rejected rather than partially applied.

Command processing should remain responsive during full-rate streaming.
Measure response latency under load.

## 13. Rapid device discovery

### 13.1 Two-stage discovery

Do not open every serial port on the machine.

~~~text
pyserial list_ports metadata
    |
    +-- filter VID/PID
    +-- filter USB product string
    +-- retain hardware serial number
            |
            +-- open only plausible candidates
                    |
                    +-- short INFO exchange
                            |
                            +-- validate protocol identity
~~~

For the pinned Teensy USB Serial mode, the core currently uses:

- VID 0x16C0.
- PID 0x0483.
- Default product string USB Serial.

The core declares USB manufacturer, product, and serial descriptors as weak
symbols. Firmware can override the product descriptor with a name such as
ThingDAQ without patching the installed core:

/home/bill/.arduino15/packages/teensy/hardware/avr/1.62.0/cores/teensy4/usb_desc.c

The default USB serial number is generated from chip identity and should be
used to distinguish multiple DAQs and track a unit across COM-port renumbering.

Do not invent a new USB VID/PID without appropriate assignment/permission.
Using the actual Teensy hardware's existing USB identity plus a product string
and protocol probe avoids that issue for initial development.

### 13.2 Python discovery behavior

Suggested API:

~~~python
devices = thingdaq.discover(timeout=0.2)
~~~

Each result should include:

- COM/device path.
- USB VID/PID.
- USB serial number.
- product/manufacturer strings when available.
- firmware/protocol identity after the INFO probe.
- capabilities and current state.

Discovery behavior:

- Enumeration-only filtering should be fast and non-invasive.
- Only matching VID/PID candidates are opened.
- Prefer matching product string ThingDAQ.
- If Windows or another OS does not expose the product string reliably, fall
  back to probing only matching Teensy USB Serial candidates.
- Bound every open, read, and probe.
- Handle access-denied ports without failing the entire discovery.
- Return all matching DAQs, not only the first.
- Allow selection by hardware serial number.
- Support hot unplug/replug and changed COM names.

An INFO probe should be compact and immediately answerable while IDLE.

## 14. Python package design

### 14.1 Core API ideas

Possible public surface:

~~~python
from thingdaq import discover, ThingDAQ

devices = discover()
daq = ThingDAQ.open(devices[0])
info = daq.info()
daq.configure(adc=True, gpio=True)
daq.start()

for block in daq.blocks():
    ...

daq.stop()
daq.close()
~~~

Useful types:

- DeviceInfo.
- DeviceCapabilities.
- DAQConfiguration.
- ADCBlock.
- GPIOBlock.
- Status.
- StreamGap or LossReport.
- Calibration.
- ProtocolError, DeviceDisconnected, CommandTimeout, and DeviceBusy errors.

### 14.2 Reader architecture

For sustained 8 MB/s:

- Use a dedicated reader loop/thread or equivalent background task.
- Request large chunks from pyserial.
- Parse incrementally from a reusable bytearray/ring buffer.
- Avoid per-byte Python operations.
- Avoid unnecessary payload copies.
- Expose memoryview or bytes at the low-level API.
- Offer optional NumPy views/conversions on ordinary user hosts.
- Keep NumPy optional because the remote rig test environment supplies
  pyserial but not arbitrary packages.
- Bound the host-side decoded-block queue.
- If the Python consumer falls behind, report host-side queue loss separately
  from firmware-reported loss.

Start with a clear synchronous API and background reader. Add asyncio support
later only if a real application needs it.

### 14.3 ADC API

Expose:

- raw adc0 array;
- raw adc1 array;
- t0 and pair period;
- adc1 phase offset;
- sequence, run ID, and loss metadata;
- an explicit interleaved() helper;
- optional calibrated_interleaved() helper.

Example conceptual behavior:

~~~python
combined = adc_block.interleaved()
# [adc0[0], adc1[0], adc0[1], adc1[1], ...]
~~~

Never label this helper as higher analog bandwidth. Documentation should say
that it creates a denser nominal sample grid from two converters.

### 14.4 GPIO API

Expose:

- packed bytes or an efficient array view;
- exact bit-to-pin mapping;
- t0 and 2-tick sample period;
- utilities to extract one or several logical channels;
- sequence, run ID, and loss metadata.

Avoid eagerly expanding every byte into eight Python booleans because that
multiplies memory traffic. NumPy-oriented unpacking can be optional.

### 14.5 Loss reporting

Do not hide gaps by concatenating arrays silently. Options include:

- Attach gap metadata to the first block after loss.
- Emit a StreamGap event in the iterator.
- Invoke a registered callback.
- In strict/testing mode, raise immediately on any gap.

Production mode should continue delivering live blocks while making loss
impossible to overlook. Test mode should treat any unexpected loss as failure.

## 15. Synthetic test mode

### 15.1 Purpose

Synthetic data validates:

- sample ordering;
- ADC interleaving convention;
- timestamps;
- sequence numbers;
- DMA/rotating-buffer boundaries if injected early enough in the pipeline;
- packetization;
- checksums;
- USB transport;
- Python incremental parsing;
- loss detection.

It does not validate analog conversion quality or physical GPIO capture unless
the hardware is stimulated externally. Keep synthetic and physical-loopback
tests distinct.

### 15.2 ADC pattern

Recommended conceptual pattern:

~~~text
ADC0[n] = (2*n) modulo code_range
ADC1[n] = (2*n + 1) modulo code_range
~~~

Interleaving produces a contiguous ramp:

~~~text
0, 1, 2, 3, 4, 5, ...
~~~

This detects swapped channels, duplicated/missing values, bad buffer strides,
and wrong pair boundaries.

### 15.3 GPIO pattern

Recommended conceptual pattern:

~~~text
GPIO[m] = m modulo 256
~~~

The pattern exercises every bit and makes dropped, duplicated, or reordered
samples obvious.

### 15.4 Pattern origin options

Define at least two test levels eventually:

1. Packetizer synthetic mode: bypasses physical acquisition and proves maximum
   protocol/USB/host throughput.
2. Acquisition-pipeline synthetic or hardware-loopback mode: exercises DMA and
   buffer ownership as much as possible.

Host-only parser tests should also inject:

- bad checksum;
- impossible size;
- unknown version/type;
- truncated frame;
- duplicated frame;
- missing sequence;
- leading garbage;
- magic within payload;
- several frames in one read;
- every possible split point across reads.

## 16. Verification strategy

### 16.1 Host unit tests on every change

Test without hardware:

- C/Python golden frame encodings.
- Header and checksum test vectors.
- Parser with arbitrary chunk boundaries.
- Parser resynchronization after corruption.
- Maximum/minimum sizes and integer overflow defenses.
- ADC payload decoding and interleaving.
- GPIO bit mapping.
- Timestamp calculations.
- Sequence/gap detection.
- Firmware-versus-host counter reconciliation.
- Discovery filtering with mocked list_ports entries.
- Command request/response matching and timeout paths.
- Disconnect/reconnect behavior with fake serial objects.
- Calibration math and provenance.

Property-based tests would be valuable for parser chunking and corruption, but
the baseline test suite should not require unusual packages in the rig-side
single-file acceptance test.

### 16.2 Compile-only gate

For every firmware change:

- Build exact Teensy 4.0 FQBN and pinned core.
- Make warnings visible and preferably fatal for project code.
- Record flash and RAM usage.
- Record build options and compiler identity.
- Retain artifact SHA-256.
- Reject a build missing firmware/protocol/build identity.

### 16.3 Hardware milestones

#### Milestone A: identity and control

- Firmware boots IDLE.
- USB product name and unique serial are visible.
- Python discovery finds it without opening unrelated ports.
- INFO, CONFIGURE, START, STOP, and STATUS work with bounded timeouts.
- Reopening the COM port does not require an unbounded boot wait.

#### Milestone B: synthetic USB throughput

- Generate protocol-ready ADC and GPIO synthetic frames at the full combined
  8 MB/s payload rate.
- Run parser and checksum verification continuously.
- Verify commands remain responsive.
- Establish baseline CPU, RAM, queue-depth, and USB behavior before physical
  acquisition is added.

#### Milestone C: GPIO hardware spike

- Reserve D6-D13.
- Remap only their GPIO bits from GPIO7 to GPIO2.
- Prove PIT/XBAR-triggered GPIO2_PSR DMA at exact 4 MHz.
- Capture a known external byte pattern.
- Verify packing, bit order, timestamps, and zero DMA overruns.
- Measure CPU cost of packing and checksum.

#### Milestone D: ADC hardware spike

- Configure and calibrate both ADCs.
- Prove 1 MS/s per ADC.
- Prove 500 ns nominal trigger separation.
- Direct DMA into alternating halfwords if feasible.
- Apply one signal to both pins and inspect raw mismatch.
- Verify no ADC_ETC errors or overwritten results.
- Measure usable resolution/noise at speed.

#### Milestone E: combined acquisition

- Run ADC and GPIO timers/DMA together.
- Establish a common run epoch and verify nominal relative timing.
- Stream both sources at about 8 MB/s payload.
- Exercise commands while streaming.
- Verify no source, packetizer, USB, or host overruns.

#### Milestone F: hardening

- Deliberate host stall and recovery.
- USB unplug/replug.
- Repeated START/STOP.
- Invalid and corrupted commands.
- Long-duration Windows run.
- Multiple Teensy/serial devices attached during discovery.
- Documentation and example applications.

### 16.4 Sustained-transfer acceptance

Suggested progression:

- 10-second smoke.
- 1-minute normal hardware test.
- 10-minute regression/benchmark.
- At least 1-hour release-candidate Windows test.

For a normal zero-loss run require:

- expected payload bytes and samples;
- no frame checksum failures;
- no sequence gap, duplication, or reordering;
- no timestamp discontinuity;
- all firmware source-drop counters remain zero;
- all firmware DMA/ADC_ETC error counters remain zero;
- host parser and queue drop counters remain zero;
- correct final sample formulas in synthetic mode;
- command response latency remains within an explicit bound;
- process memory remains bounded.

Record both payload throughput and total framed byte throughput. Measuring true
USB bus utilization, including transaction overhead, requires lower-level USB
instrumentation; application byte rate alone is not the same metric.

### 16.5 Negative overrun acceptance

Deliberately pause or slow host reads:

- Firmware acquisition continues.
- Old unsent complete blocks are dropped according to policy.
- Counters increase by the actual lost sample quantities.
- The next delivered frame reports overrun.
- Sequence and timestamp gaps agree with counters.
- Parser resumes at a valid frame boundary.
- STOP and STATUS remain functional.

### 16.6 Remote firmware rig

Follow the referenced new-project guide:

- Compile locally; the rig flashes but does not compile.
- Use the service-owned current run_my_program.py client.
- Keep top-level test_firmware.py self-contained.
- Read SERIAL_PORT from the environment.
- Use bounded serial reads, retries, and total deadlines.
- The rig-side environment has Python 3.13, pyserial, minimalmodbus, and the
  standard library; do not assume the installable user Python package or NumPy
  is present.
- Synchronize/probe before grading.
- Validate INFO protocol and build identity before data behavior.
- Print expected and actual details on failure.
- Never run multiple hardware submissions in parallel.
- Preserve program success separately from Python test exit status.

The remote rig is useful for deterministic flash/reset/protocol evidence, but
the final sustained-throughput requirement also needs testing on the intended
Windows host and USB controller.

## 17. Proposed repository shape

One possible shape consistent with the firmware guide:

~~~text
thingdaq/
  firmware/
    firmware.ino
    acquisition_clock.cpp
    acquisition_clock.h
    adc_capture.cpp
    adc_capture.h
    gpio_capture.cpp
    gpio_capture.h
    frame_codec.cpp
    frame_codec.h
    control.cpp
    control.h
    statistics.h
    usb_names.c
  src/
    thingdaq/
      __init__.py
      discovery.py
      device.py
      protocol.py
      streams.py
      calibration.py
      errors.py
  tests/
    test_protocol.py
    test_parser.py
    test_discovery.py
    test_streams.py
    fixtures/
      golden_frames.bin
  test_firmware.py
  pyproject.toml
  protocol.md
  README.md
  brainstormed_plan.md
~~~

The Arduino sketch directory and ino basename must match for Arduino CLI. If
using firmware/firmware.ino, compile the firmware directory. Before adding any
helper or class, search the repository and pinned Teensy libraries for an
existing implementation that can be reused safely.

Keep generated builds, captures, virtual environments, credentials, and large
benchmark outputs out of source control. Keep small deterministic golden
frames and transcripts in source control.

## 18. Suggested implementation order

1. Convert selected brainstorm decisions into protocol.md and explicit
   acceptance criteria.
2. Scaffold the pinned build and Python package.
3. Implement frame codec independently in C++ and Python with shared golden
   vectors.
4. Implement USB identity, rapid discovery, INFO, state machine, and bounded
   command handling.
5. Implement full-rate synthetic transport and prove Windows/Python throughput.
6. In parallel with protocol maturation, perform the exact-rate PIT/XBAR GPIO
   DMA spike because it is the largest low-level uncertainty.
7. Implement production GPIO capture and packing.
8. Implement low-level ADC_ETC phase scheduling and ADC DMA.
9. Combine sources under one run epoch.
10. Add overrun pressure behavior and reconciliation.
11. Add calibration support, examples, documentation, and long-duration tests.
12. Archive reproducible hardware and benchmark evidence for releases.

The first meaningful vertical slice is:

~~~text
discover -> INFO -> START synthetic -> parse 8 MB/s -> STATUS -> STOP
~~~

That proves identity, command framing, streaming framing, Python parsing,
checksums, and basic throughput before mixing in difficult peripheral code.

## 19. Risks and focused experiments

| Risk | Early experiment or mitigation |
| --- | --- |
| Exact 4 MHz cannot be divided from 150 MHz IPG | Prove chained 24 MHz PIT events through XBAR |
| PIT/XBAR cannot trigger desired GPIO DMA behavior | Minimal GPIO2_PSR DMA sketch before full firmware |
| DMA cannot access fast GPIO7 | Selectively remap D6-D13 to standard GPIO2 |
| GPIO packing consumes too much CPU | Benchmark optimized batch packing; retain raw-word diagnostic mode |
| 12-bit conversion misses 1 microsecond period | Test fastest settings across boards/conditions; expose errors |
| ADC source does not settle | Define source-impedance/front-end requirements; test with buffered source |
| Interleaved ADC mismatch looks worse | Preserve raw channels and provide explicit calibration |
| ADC trigger phase differs from aperture phase | Measure with a shared waveform and document/calibrate residual |
| Two DMA channels race on one interleaved buffer | Require both completion states; test TCD layout thoroughly |
| DMA/cache corruption | Align buffers and centralize cache-maintenance ownership |
| Windows CDC cannot sustain framed stream | Prove synthetic 8 MB/s early with efficient Python reads |
| Python consumer falls behind | Dedicated reader, bounded queues, separate host-loss reporting |
| USB writer blocks acquisition | Decouple DMA rings and transmit queue; never wait in acquisition ISR |
| Partial-frame drop breaks parser | Finish any started frame; drop only complete unsent blocks |
| Device discovery scans too many ports | Metadata filter by VID/PID/product before INFO probe |
| Product metadata unavailable or cached | Fall back to probing only matching Teensy VID/PID candidates |
| Multiple DAQs attached | Select and persist by hardware serial number |
| USB VID/PID ownership | Keep actual Teensy identity during development; do not invent IDs |
| Timestamp drift or inconsistent epochs | Derive timestamps from the hardware schedule/sample counters |
| Timer resource conflicts | Reserve PIT/XBAR/DMA channels centrally and avoid hidden library ownership |
| Stock ADC helper is not phase-aware | Own low-level acquisition setup rather than calling startTimer |
| Buffering masks host stalls only briefly | Report gaps; do not promise indefinite buffering |
| Commands starve behind data | Prioritize command parsing/responses and measure latency under full load |

## 20. Decisions still to formalize

Recommended defaults are included so the formal planner has a starting point.

| Topic | Recommended starting point | Status |
| --- | --- | --- |
| ADC result mode | 12-bit code in uint16, no averaging | Provisional; verify timing and analog quality |
| Clock generation | 24 MHz PIT at 4 MHz plus chained 1 MHz, ADC_ETC +75-cycle phase | Provisional; hardware spike required |
| Timestamp | uint64 at 8 MHz, relative to START epoch | Recommended |
| Data frame size | Fixed 4096 bytes | Recommended; benchmark latency |
| Header | Version, kind, flags, lengths, sequence, uint64 time, item count | Recommended |
| Checksum | Consider CRC-32C; retain Adler-32 if simplicity/compatibility wins | Open |
| Data byte order | Little endian | Recommended |
| ADC payload | Direct interleaved uint16 pairs | Recommended |
| GPIO wire bit order | D6 through D13 mapped to bits 0 through 7 | Recommended |
| Drop policy | Drop oldest complete unsent block and remain live | Recommended |
| USB identity | Existing Teensy VID/PID plus product name ThingDAQ | Recommended |
| Host dependency | pyserial required, NumPy optional | Recommended |
| Python style | Synchronous public API with background reader first | Recommended |
| Calibration location | Host-side, keyed by device serial | Recommended initially |
| Release soak | At least one hour on Windows at full combined rate | Recommended |
| Command latency limit | Define after synthetic throughput baseline | Open |
| ADC phase tolerance | Define after trigger/aperture measurements | Open |
| GPIO rate tolerance | Exact nominal 4 MHz is intended; quantify measured tolerance | Open |
| Analog front end | Document 0-3.3 V, impedance, protection, filtering | Needs product decision |

## 21. Documentation requirements

The formal README/protocol/API documentation should clearly state:

- This is Teensy 4.0 firmware, not a generic arbitrary-board library.
- Exact pins and voltage limits.
- ADC0/ADC1 sample order and 500 ns phase.
- The combined 2 MS/s view does not increase analog bandwidth.
- Need to drive both A0 and A1 with the same signal for combination.
- Raw versus calibrated data.
- Digital bit-to-pin mapping.
- Timestamp epoch, units, and per-source sample offsets.
- Frame byte order, lengths, checksum, and versioning.
- Discovery behavior and hardware serial selection.
- Device boots IDLE and requires START.
- Continuous overrun behavior and all loss-reporting mechanisms.
- Sustained throughput claims, test host, duration, and evidence.
- Python examples for discovery, raw ADC, interleaved ADC, GPIO, loss
  handling, status, and clean shutdown.

README cleanup notes from the initial version:

- Replace interlaved with interleaved where intended.
- Clarify that the ADCs are phase-interleaved, not simultaneous.
- Replace vague phrase entire set of message with a precise total-frame-length
  invariant.
- Fix spelling such as encapsulating and leverage.
- Complete the unfinished fourth testing list item.
- Separate requirements from future possibilities.
- Add exact build/core identity.
- Link to protocol.md rather than making the README the only byte-level
  specification.

## 22. Reference material

Local references:

- Current project intent:
  /home/bill/agents/thingdaq/README.md
- Firmware build and rig guide:
  /home/bill/agents/fw_experiments/docs/guides/new-firmware-projects.md
- Teensy ADC pin tables:
  /home/bill/.arduino15/packages/teensy/hardware/avr/1.62.0/libraries/ADC/ADC.cpp
- Teensy ADC timer/ADC_ETC implementation:
  /home/bill/.arduino15/packages/teensy/hardware/avr/1.62.0/libraries/ADC/ADC_Module.cpp
- ADC DMA example:
  /home/bill/.arduino15/packages/teensy/hardware/avr/1.62.0/libraries/ADC/examples/adc_timer_dma/adc_timer_dma.ino
- AnalogBufferDMA implementation:
  /home/bill/.arduino15/packages/teensy/hardware/avr/1.62.0/libraries/ADC/AnalogBufferDMA.cpp
- Digital pin/GPIO mappings:
  /home/bill/.arduino15/packages/teensy/hardware/avr/1.62.0/cores/teensy4/core_pins.h
- PIT, DMA, XBAR, ADC_ETC register definitions:
  /home/bill/.arduino15/packages/teensy/hardware/avr/1.62.0/cores/teensy4/imxrt.h
- Fast-GPIO startup selection:
  /home/bill/.arduino15/packages/teensy/hardware/avr/1.62.0/cores/teensy4/startup.c
- Standard-GPIO remapping and timer/XBAR/DMA example:
  /home/bill/.arduino15/packages/teensy/hardware/avr/1.62.0/libraries/OctoWS2811/OctoWS2811_imxrt.cpp
- USB descriptor defaults and weak overrides:
  /home/bill/.arduino15/packages/teensy/hardware/avr/1.62.0/cores/teensy4/usb_desc.h
  /home/bill/.arduino15/packages/teensy/hardware/avr/1.62.0/cores/teensy4/usb_desc.c

External references:

- Teensy 4.0 specifications:
  https://www.pjrc.com/store/teensy40.html
- Teensy USB Serial buffering and 512-byte packet behavior:
  https://www.pjrc.com/teensy/td_serial.html
- Annotated i.MX RT1060 reference manual:
  https://www.pjrc.com/teensy/IMXRT1060RM_rev3_annotations.pdf
- i.MX RT1060 data sheet and ADC characteristics:
  https://www.nxp.com/docs/en/nxp/data-sheets/IMXRT1060CEC.pdf
- NXP clock/peripheral synchronization example:
  https://www.nxp.com/docs/en/user-guide/3PPMSMCRTUG_rev3.pdf
- NXP ADC_ETC/eDMA example documentation:
  https://mcuxpresso.nxp.com/mcuxsdk/latest/html/examples/driver_examples/adc_etc/adc_etc_edma/readme.html
- NXP MIMXRT1062 ADC_ETC API reference:
  https://mcuxpresso.nxp.com/mcuxsdk/latest/html/api/devices/MIMXRT1062/index.html

## 23. Condensed recommended direction

If the formal planning agent needs one concise architecture to start from:

1. Pin Teensy core 1.62.0 and exact Teensy 4.0 build options.
2. Boot IDLE with USB product string ThingDAQ.
3. Discover by USB metadata, then verify with a bounded INFO exchange.
4. Use a 24 MHz PIT schedule for exact 4 MHz GPIO and chained 1 MHz ADC
   triggers.
5. Use ADC_ETC asynchronous trigger queues with a 75-IPG-cycle relative delay
   to make ADC1 500 ns later.
6. DMA ADC0 and ADC1 into alternating uint16 slots.
7. DMA GPIO2_PSR as 32-bit words after remapping D6-D13, then batch-pack to one
   byte per sample.
8. Use uint64 timestamps at 8 MHz and independent per-stream sequence numbers.
9. Send typed, checksummed 4096-byte data frames over USB CDC.
10. Keep acquisition independent of USB; on pressure drop the oldest complete
    unsent block, continue live, and report exact loss.
11. Give Python users raw channels plus an explicit calibrated interleave
    helper.
12. Prove full 8 MB/s payload first with deterministic synthetic data, then
    GPIO hardware, ADC hardware, combined acquisition, and a one-hour Windows
    zero-loss release soak.
