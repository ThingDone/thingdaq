---
type: reference
title: Exact-candidate protocol v3 qualification runner
created: 2026-10-20
tags:
  - protocol-v3
  - qualification
  - rig
  - release
related:
  - '[[protocol-v3-upgrade]]'
  - '[[protocol-v3]]'
  - '[[protocol-v3-migration]]'
  - '[[firmware-builds]]'
  - '[[soak-harness]]'
---

# Exact-candidate protocol v3 qualification

`firmware/tools/qualify_protocol_v3.py` plans, submits, resumes and validates
one fixed-candidate campaign. The implementation is available for Phase 06;
**physical qualification remains NOT_RUN** until the complete matrix has
passing retained service evidence. The local simulator and portable C++ tests
are implementation checks, not hardware qualification.

The worker uses public v3 negotiation and the production SDK's control,
parser and block paths. Explicit v2 RAW cells use that SDK's low-level
v2 command/decoder path on the same firmware. Historical v1/v2 soak programs,
private 0x82/0x83 experiments and release-1.1.0 evidence are unchanged.
See [[protocol-v3]], [[protocol-v3-migration]] and [[protocol-v3-upgrade]].

For physical v2 captures, legacy generated-item counters count complete packets;
dropped-item counters also include explicit unframed STOP tails. Qualification
reconciles only bounded tails with matching raw-loss and delivered/captured
counters: ADC below two frames, GPIO below one frame, with bounded ADC incomplete
buffer diagnostics. Frame drops, wire gaps and unexplained raw loss still fail.
This follows the existing physical-stop accounting in the soak validator.


## Candidate preparation and freeze

Commit the firmware, SDK and qualification implementation first. Build from
that clean revision with the standard builder described in [[firmware-builds]].
The following prepares a **new** manifest from the build's public configuration
table. `BOARD_SERIAL` is the exact string returned by public v3 INFO.

```bash
BUILD=firmware/build/teensy.avr.teensy40.usb_serial.speed_600.opt_o2std
.venv/bin/python firmware/tools/qualify_protocol_v3.py prepare \
  --build-manifest "$BUILD/build-manifest.json" \
  --hardware-serial "$BOARD_SERIAL" \
  --output firmware/soak/protocol-v3-candidate.json
.venv/bin/python firmware/tools/qualify_protocol_v3.py plan \
  --candidate firmware/soak/protocol-v3-candidate.json
```

Preparation refuses an existing output. It does not rebuild, freeze, flash,
or declare a PASS. The new manifest retains the existing freezer's
`artifact`, `firmware`, `board` and `protocol` identity fields. Use
`freeze_soak_candidate.py` with explicit new candidate/lock/staging paths,
its existing two-build reproducibility check and verification workflow;
do not overwrite `firmware/soak/candidate*.json`.

Additional manifest fields bind:

- Full source revision and `source_dirty: false`.
- Firmware and build-manifest SHA-256.
- Board serial, board/MCU IDs, firmware version and firmware build ID.
- SDK version and deterministic bundled SDK archive SHA-256.
- All three public schema hashes and runner/policy/worker/HTTP-helper hashes.
- Complete capabilities payload and the policy-generated matrix.

The expected table comes from the build manifest; every submitted worker must
read **exactly the same live advertisement** before exercising a cell. Matrix
membership is generated from those tuples, including synthetic tuples. Missing
advertised support is never silently skipped. The whole candidate is hashed
into every job's provenance and worker report.

Execution also checks the firmware against its build manifest, the clean
source revision, local SDK/schema/runner hashes, and relevant Git trees against
that revision. Metadata-only commits can follow the source revision; changes
to firmware, SDK, schemas or runner inputs require a new candidate. The
deterministic SDK source archive is the execution build, rather than a package
downloaded by the rig. Record distribution wheel/sdist hashes separately at
the release freeze checkpoint.

## Matrix and acceptance

The normal 600 MHz table currently produces **62 jobs**:

| Cell | Requirement |
| --- | --- |
| 48 advertised tuples | 60 seconds each; both widths, all supported stream/source/policy combinations |
| Same-boot lifecycle | 20 one-second START/STOP cycles, alternating stopped default and RAW settings; strictly increasing run IDs |
| Default combined endurance | Three 600-second captures in separate reflashed jobs |
| Host stall | 60 seconds per width, including 250 ms with USB host reads paused; observable firmware drops required |
| Compression fallback | 60 seconds per width with physical firmware's synthetic source; both RLE and RAW observed |
| Explicit v2 RAW | Five 60-second cases: ADC-only with auxiliary DISABLED; GPIO-only and combined at both widths |
| Negative settings | Every canonical tuple absent from the advertisement, plus malformed CPU/width/resolution/mask and unsupported rates |

The v2 SDK/specification requires GPIO for auxiliary INPUT; ADC-only INPUT
remains covered by the advertised v3 cells, not by legacy compatibility.

Each capture is at most 600 seconds. Planning reuses the isolation runner's
780-second ceiling below the service's 900-second container limit. The
three soaks establish repeated ten-minute runs, **not continuous thirty-minute
or same-boot endurance**. Only the lifecycle job establishes same-boot cycles.

Negative requests bypass SDK prevalidation at the transport boundary while
preserving request correlation and recalculating the checksum. Known but
unsupported tuples must return `UNSUPPORTED_CONFIGURATION`; malformed fields
must return `INVALID_PAYLOAD`. Before/after settings, CPU clocks and STOPPED
state must remain unchanged.

Normal captures require zero firmware drops, SDK queue loss, parser corruption
or unexplained gaps. For each stream, the gate checks:

- Generated frames/items = wire-received frames/items + firmware drops.
- Leading/internal timestamp gaps and the unreceived STOP tail account for
  exactly the firmware's dropped items.
- SDK decoded frames/items/logical bytes/wire bytes equal the independent
  wire observer's totals, including frames discarded at STOP boundaries.
- Public v3 transmitted byte counters agree with the wire observer.
- Required hardware/transport/ownership health counters are present and zero.
- CONFIGURE, START, INFO and final GET_SETTINGS agree at fixed 600 MHz.
- Before/after stopped PIT/XBARA/eDMA clock diagnostics agree with 600 MHz
  DWT timing over 8,192 events at 1 MHz, within the existing one-event tolerance.
- Normal captures of at least 60 seconds measure sample progression against
  host monotonic time within 1% of 1 MHz, for each active stream.

Host stalls pause actual transport reads rather than merely the application's
block consumer. Deliberate firmware drops must conserve samples and frame
counts; SDK queue loss or wire corruption still fails. Codec deadline/resource
drop counters are retained, and normal cells require zero. Fallback cells
must observe both encodings and a nonzero firmware RAW counter.

Public-v3 synthetic GPIO alternates all-zero even logical frames with
high-transition odd logical frames. Odd-frame primary bytes alternate `0xAA`
and `0x55`; GPIO16 auxiliary bytes alternate `0x0F` and `0xF0`, using the
absolute sample index parity. ADC uses the 12-bit channel ramps except for
pairs 0–3 of each 2,048-pair cycle: `(0,0)`, `(4095,4095)`, `(0xABC,0x123)`,
and `(0x555,0xAAA)`. These are the existing SDK validator/simulator patterns;
legacy v1/v2 sources retain their previous formulas.

The rig independently checks source bytes and SDK decoding for one complete
frame per observed encoding per stream, and retains those frames. Framing,
checksums, sequence and conservation checks cover all frames. Source checks
are bounded samples, not an all-payload replay of the entire capture. The
portable regression drives the actual firmware generator through control,
codecs and USB and validates every emitted block against the SDK pattern.

Die temperature is sampled before, during (at most ten seconds apart), and
after capture. At **80 °C or above**, the worker aborts and attempts STOP in
`finally`. `NOT_READY` retries retain every reading and are bounded by one
second and 64 attempts, using the existing variable retry intervals. Other
sensor failures abort immediately. Negative-only jobs check temperature before
and after their commands. Temperature and stopped clock diagnostics use explicit
read-only public-v2 requests through the shared SDK reader; they do not switch
the acquisition session away from v3.

## Submit and resume

Use the rig setup and physical wiring requirements in [[soak-harness]].
Credentials stay in `FW_RIG_AUTH`; the service URL may use `FW_RIG_SERVICE`.
The worker receives `SERIAL_PORT` from the rig. No credentials are embedded in
generated programs, manifests or provenance.

```bash
BUILD=firmware/build/teensy.avr.teensy40.usb_serial.speed_600.opt_o2std
EVIDENCE=.maestro/playbooks/Working/protocol-v3-qualification
.venv/bin/python firmware/tools/qualify_protocol_v3.py run \
  --candidate firmware/soak/protocol-v3-candidate.json \
  --firmware "$BUILD/firmware.ino.hex" \
  --build-manifest "$BUILD/build-manifest.json" \
  --output "$EVIDENCE"
```

Add `--cell CELL_ID` to run a single matrix cell. This leaves the complete
campaign INCONCLUSIVE until all required cells pass.

For any existing evidence directory, repeat the command with **`--resume`**.
Saved completed jobs are reused; unfinished submissions retain the exact
firmware, program and submission tag. All HTTP calls go through
`run_input_isolation.py`: every 5xx is retried at 30-second intervals until
ten continuous minutes of 5xx for that request. Before retrying `/start`,
the helper reconciles the saved tag against the rig journal or follows its
saved job ID. Queue residence and HTTP retry waits do not consume execution
timeouts. Do not execute archived raw clients or submit a replacement job to
recover a retained request.

The runner stops after a measured FAIL and retains it. `--resume` never
reflashes a completed failed cell. Investigate the retained evidence before
any further experiment. A later PASS cannot erase an earlier failed attempt
from acceptance.

## Retained evidence and offline validation

```bash
.venv/bin/python firmware/tools/qualify_protocol_v3.py validate \
  --candidate firmware/soak/protocol-v3-candidate.json \
  --output .maestro/playbooks/Working/protocol-v3-qualification
```

Each cell's `attempt-001/` retains firmware bytes, exact generated program,
provenance, submission tag, service preflight, job ID, status, unmodified
service result/stdout/stderr, and any client-side exception. The worker report
includes partial failed captures, temperatures, actual settings/clocks, SDK
counts, firmware diagnostics and independent wire accounting.

The wire observer checks every frame's framing, public version, checksum,
sequence, sample cursor and byte counts. It independently decodes one full
frame per observed encoding and compares the decoded bytes with the SDK.
Those raw frames and bounded raw control frames are retained as hex; the
entire incoming byte stream is hashed. **Full multi-gigabyte captures are not
retained**, so arbitrary offline replay of every sample is unavailable.
Production SDK decoding still validates every received data frame.

The offline validator reloads the authoritative service results, verifies
saved firmware/program/submission/job identity, then recomputes acceptance
from measurements. `qualification.json` is a derived report, never an input
authority. Every retained `*/attempt-*` participates; failures cannot be
excluded by choosing the last successful result.

- **NOT_RUN:** no attempt evidence.
- **INCONCLUSIVE:** incomplete matrix or missing/recoverable service evidence.
- **FAIL:** completed failure, mismatched identities or invalid measurements,
  including any retained failed attempt.
- **PASS:** every required physical cell passes for the exact candidate.

All outcomes except PASS return a nonzero validation exit code. Simulator
reports cannot qualify a physical board.
