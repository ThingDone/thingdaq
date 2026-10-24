---
type: report
title: Frozen public protocol v3 release candidate and Phase 06 handoff
created: 2026-10-20
tags:
  - protocol-v3
  - release-candidate
  - reproducibility
  - qualification
related:
  - '[[protocol-v3-upgrade]]'
  - '[[protocol-v3]]'
  - '[[protocol-v3-migration]]'
  - '[[protocol-v3-local-gates]]'
  - '[[protocol-v3-qualification]]'
  - '[[soak-harness]]'
  - '[[hardware-safety]]'
---

# Frozen public protocol v3 release candidate

**Historical Phase 05 freeze, superseded on 2026-10-24.** The active candidate
and artifact paths are documented in [[protocol-v3-identity-recovery]]. The
original manifests are retained under `firmware/soak/history/*-20261020.json`;
the commands and identities below describe that historical candidate.

**Physical qualification: NOT_RUN. Release approval: pending Phase 06.**
No rig request, flash, physical capture or remote package publication occurred
at this checkpoint.

Firmware and SDK versions are independently **1.2.0**; the public wire version
is **3**. Two standard builds from clean, pushed source revision
`eb8a890da5646ff18074a9103678b8e6acc0c900` reproduced all four exported artifacts
(HEX, ELF, MAP and EEP) and the build manifest byte for byte. Both used build ID
`thingdaq-67539aafb5b130a5`.

The normal defaults are fixed CPU 600 MHz, ADC pair/GPIO rates 1 MHz,
auxiliary DISABLED, GPIO width 8, GPIO RLE_AUTO, ADC PACK12, both streams,
hardware source and ADLER32. Runtime CPU switching is unsupported. Explicit
v2 RAW operation remains part of qualification; historical v1/v2 campaigns,
fixtures and private codec experiments are unchanged.

## Frozen identity and retained artifacts

- Candidate: `firmware/soak/protocol-v3-candidate.json`.
- Two-build lock: `firmware/soak/protocol-v3-candidate-freeze.json`.
- Verification evidence: `doc/results/protocol-v3-release-candidate-validation.json`.
- Local artifact root: `.maestro/playbooks/Working/phase05-freeze/`.
- Expected Teensy 4.0 / i.MX RT1062 serial: **20428100** (board/MCU IDs 1/1).

The board pin comes from retained
`doc/results/experiments/clock600-fixed-endurance-20261018.json`; it is a
historical target identity, not a fresh public-v3 observation. Phase 06 must
verify the live decimal INFO serial and all candidate fields before accepting
measurements.

The candidate includes the entire 63-job matrix, capability payload, input
hashes, and paths/sizes/hashes for 15 retained files. The lock protects 498
source/package/test files, the candidate's semantic digest, and all five
staged build files. Firmware, SDK ZIP, runner/schema snapshots and wheel/sdist
bytes are retained locally under the artifact root; Git tracks their manifests
and this report. A fresh clone needs those retained bytes copied to the recorded
paths and verified before execution. Do not silently substitute a new build.

| Artifact relative to local artifact root | SHA-256 |
| --- | --- |
| `frozen/firmware.ino.hex` | `2a64e61f071b4ff9d981c3ea0217049dd40b64fad2ae448267a70c5b47fd25e7` |
| `frozen/firmware.ino.elf` | `8588c3e54a092b78c2afc9f175fe9f2002210ebc22f5d95540de0f0c6708c0c5` |
| `frozen/firmware.ino.map` | `22a877e2e24596a770415c341bc8b0decef044122d1222ed56f86075feb5277b` |
| `frozen/firmware.ino.eep` | `c4a8b44f3ab62332bf41f3a70722fa89e6b79ebcc2335152b8b0ff4e52650f77` |
| `frozen/build-manifest.json` | `e629c55af5bfd14517e2191e59a0ffabef66af0ded18eeb9322e9c96bce94b3f` |
| `inputs/sdk.zip` | `c22e520af516077d4b92527699c6c602dd857d0ef4627c453f5a20be32090f1f` |
| `distributions/thingdone_daq-1.2.0-py3-none-any.whl` | `8ba2f35029405407582ef699e4cad3b2d3a210c93d11ffc0b64cff3eb36ee51c` |
| `distributions/thingdone_daq-1.2.0.tar.gz` | `701d4559e426591683eae72773c78d88de80d38e24c30516d860767dbbd0f22f` |

Canonical candidate SHA-256:
`4781d273db15091039b841b51680a31143b02a6eec4d94ac23ec2898634540b4`.
This is the runner's sorted, compact JSON digest, not the indented file digest.
The evidence JSON records both forms and the lock file digest.
All runner and v1/v2/v3 schema hashes are in the candidate's `inputs` mapping;
their exact files are copied beneath `inputs/`. The deterministic SDK ZIP is
the source bundle embedded by the runner; the wheel and sdist are separate
distribution artifacts.

## Passing local gates

The full implementation gate in [[protocol-v3-local-gates]] passed **2,648 tests
with five expected unsupported-combination skips**, including throughput,
without retries. Its log digest is
`d4127e98c6489788069a55b028de8fd18a19b8b3cf8260fe4f022c9c8102aa09`.
That gate's discovery/documentation changes were committed as the frozen
revision above. No implementation or test inputs changed during this freeze.

Additional checks at this checkpoint:

| Gate | Result |
| --- | --- |
| Two standard target builds | All artifacts and manifests byte-identical |
| ELF placement, headroom and allocation ownership | PASS on both builds |
| Freeze and qualification regression suites | 76 passed in 22.35 seconds |
| Protocol generation | 142 outputs current |
| Ruff format/lint | 203 files formatted; lint passed |
| SDK mypy | 34 source files passed |
| Historical soak generation and standalone/installed conformance | PASS |
| Fresh isolated wheel/sdist build and strict Twine | PASS for both artifacts |
| Fresh installed-wheel isolated offline upgrade demo | PASS, including exact v3 data and v1/v2 compatibility |
| Documentation and repository layout | 11 passed, 1,379 subtests passed |
| Freeze, candidate, SDK/runner/schema and retained-artifact checks | PASS; 498 protected files, 15 retained files, 63 jobs |
| Empty physical-evidence validator | Expected NOT_RUN and exit status 1 |
| Report's executable artifact-verification example and whitespace | PASS |

Toolchain: Arduino CLI 1.4.1, Teensy core 1.62.0, Arm GNU 15.2.1,
FQBN `teensy:avr:teensy40:usb=serial,speed=600,opt=o2std`.
RAM1 locals headroom is 33,024 bytes; RAM2 heap headroom is 4,096 bytes.
Builds emitted the existing missing-udev-rule warning but passed every binary
gate. Build/package/test logs and their hashes are retained in the evidence
JSON. The first regression invocation used a nonexistent test filename and
collected no tests; the corrected existing suites produced the result above.

## Phase 06 setup

Complete the Phase 06 playbook's existing visible setup gate before running
the campaign:

1. Make the existing rig available with Teensy 4.0 serial **20428100**, a working
   USB data connection, flash/reset access and the service's `SERIAL_PORT`
   assignment. Close competing serial consumers.
2. Use the existing safe input fixture: A0/D14 and A1/D15, primary GPIO D6–D13,
   and D16–D23 for the 16-bit cells. Follow [[hardware-safety]] for 0–3.3 V
   limits, common reference and protection. No new external waveform generator
   is required for this acquisition/transport campaign; analog accuracy and
   externally stimulated pin/timing claims remain unqualified.
3. Provide the configured service URL in `FW_RIG_SERVICE` and its credential
   in `FW_RIG_AUTH` through the existing local environment. Preserve read-only
   journal access; set `FW_RIG_SSH` if its host differs from the service host.
   No credentials belong in commands, manifests or retained logs.
4. Preserve the service's 900-second job limit and the runner's 780-second
   planning ceiling. The 80 °C abort and bounded temperature-NOT_READY retries
   remain enabled.

The 63 jobs comprise 48 sixty-second advertised-tuple captures, one twenty-cycle
same-boot lifecycle job, three separate ten-minute default combined captures,
two host stalls, two compression-fallback captures, six v2 RAW captures and
one negative-request job. Separate reflashes do not establish continuous
thirty-minute or same-boot endurance. See [[protocol-v3-qualification]] for
conservation, timing and acceptance requirements.

## Verification and execution

Run from the repository root. These checks are offline:

```bash
.venv/bin/python firmware/tools/freeze_soak_candidate.py --check \
  --lock firmware/soak/protocol-v3-candidate-freeze.json
.venv/bin/python firmware/tools/qualify_protocol_v3.py plan \
  --candidate firmware/soak/protocol-v3-candidate.json
.venv/bin/python - <<'PY'
import hashlib
import json
import sys
from pathlib import Path

sys.path.insert(0, "firmware/tools")
import qualify_protocol_v3 as qualification

candidate = json.loads(Path("firmware/soak/protocol-v3-candidate.json").read_text())
qualification.check_candidate(candidate)
qualification.verify_artifacts(
    candidate, Path(candidate["artifact"]["path"]),
    Path(candidate["build_manifest_path"]),
)
retained = candidate["retained_artifacts"]
records = (retained["firmware"] + [retained["build_manifest"]]
           + retained["inputs"] + retained["distributions"])
for record in records:
    data = Path(record["path"]).read_bytes()
    assert len(data) == record["size_bytes"], record["path"]
    assert hashlib.sha256(data).hexdigest() == record["sha256"], record["path"]
print("PASS: candidate inputs and all 15 retained artifacts")
PY
```

After setup and Phase 06 availability checks, submit this exact staged image:

```bash
: "${FW_RIG_SERVICE:?Configure the existing rig service URL}"
: "${FW_RIG_AUTH:?Provide the existing rig credential in the environment}"
FROZEN=.maestro/playbooks/Working/phase05-freeze/frozen
EVIDENCE=.maestro/playbooks/Working/protocol-v3-qualification
.venv/bin/python firmware/tools/qualify_protocol_v3.py run \
  --candidate firmware/soak/protocol-v3-candidate.json \
  --firmware "$FROZEN/firmware.ino.hex" \
  --build-manifest "$FROZEN/build-manifest.json" \
  --output "$EVIDENCE"
```

For an existing campaign directory, repeat the same command with `--resume`.
All HTTP goes through `run_input_isolation.py`: retry every 5xx after 30 seconds
until ten continuous minutes for that request; reconcile saved submission tags
against the journal before retrying `/start`, or follow the saved job ID.
Queue residence does not consume execution or retry budgets. Never submit a
replacement job to recover an ambiguous request or execute archived clients.

Validate retained measurements with:

```bash
.venv/bin/python firmware/tools/qualify_protocol_v3.py validate \
  --candidate firmware/soak/protocol-v3-candidate.json \
  --output .maestro/playbooks/Working/protocol-v3-qualification
```

Only a complete passing matrix qualifies this candidate. Missing measurements,
failed attempts and mismatched artifacts cannot become PASS. The freeze's
empty-evidence check used a separate `phase05-freeze/not-run/` directory and
did not create or submit a Phase 06 campaign.

Metadata-only evidence commits may follow the frozen source revision. Changes
to binary inputs, defaults, SDK decoding or runner semantics require a new
candidate identity and invalidate affected qualification. Keep this candidate
and its failures, if any, as history; do not overwrite them with replacement
artifacts or borrow prior physical results.
