# Independent sampling-rate and input-width experiments

This follow-up separates the two changes in `experiment/aux-input-bank`.
CPU clock stays at 600 MHz, data is uncompressed, checksum is Adler-32, and
no output engine or external stimulus is enabled. The Teensy serial is 20428100.
Unconnected inputs test acquisition/transport, not electrical pin mapping.

## Design

1. Eight inputs, ADC + GPIO: exercise each of the four selectable rate pairs.
2. Eight versus sixteen inputs at the same rate: change only bank width.
3. GPIO-only counterparts: separate the second GPIO DMA channel from ADC interaction.
4. Run the paired-bank diagnostic separately, never as an eight-input prerequisite.

The existing standalone branch validator is reused. Its stream chronology,
checksums, active-loss checks, bounded STOP-tail accounting and cleanup remain
enabled. Each submission cold-flashes one identified artifact and preserves its
HEX, manifest, complete runner and raw service result under the evidence directory.

## Confirmed first defect

Protocol v2 CONFIGURE is 64 bytes. The firmware still imposed v1's 56-byte command
limit, and its incremental parser retained only 59 bytes. Valid v2 configurations
were therefore rejected with INVALID_LENGTH, before testing any rate or extra pin.
The runner also discarded the legacy-version generic rejection and reported a
timeout. Fixed in auxiliary-input commit `b38bcdd`.

A new C++ test reproduced eight failures (both widths, all rates) before the fix.
It now tests the real parser across every fragmentation boundary. The parser,
USB and portable gates passed (7 tests, 35 subtests); the runner gate passed
(7 tests, 21 subtests); the pinned Teensy build passed.

Physical evidence: `9924586f-17cc-41a6-8f03-85ad8a46aaa4` captured the original
INVALID_LENGTH response; `838876ad-4537-42fe-a2d9-b0fb2ecfee46` confirmed that
CONFIGURE and metadata now pass, exposing a separate START failure. Investigation
continues; no sustainable-rate or sixteen-input success is claimed here yet.

## Reproduction

Build the auxiliary-input branch with its `firmware/tools/build_firmware.py`, then
from main run:

```bash
python firmware/tools/run_input_isolation.py \
  --worktree .maestro/playbooks/Working/aux-input-bank \
  --evidence-dir .maestro/playbooks/Working/input-isolation/new-run \
  --case CONTROL_COMBINED --profile 0 --seconds 5
```

Profiles 0–3 are ADC/GPIO 1 MHz/4 MHz, 500 kHz/2 MHz, 250 kHz/1 MHz,
125 kHz/500 kHz. Use INPUT_COMBINED for sixteen inputs, CONTROL_GPIO or
INPUT_GPIO to remove ADC, and `--diagnostic` only for the separate paired-bank
diagnostic campaign. The private service token is read from `/home/bill/.fw_api_key`
and is never included in evidence.
