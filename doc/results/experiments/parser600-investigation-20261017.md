---
type: result
title: 600 MHz Parser Rejection Investigation
created: 2026-10-17
tags: [firmware, parser, reliability]
related:
  - '[[Clock600-Thermal-20261016]]'
---

# 600 MHz parser rejection investigation

**Root cause remains unresolved; no host-parser or firmware-framing defect was
established.** The original failed capture cannot be replayed: it retained one
aggregate parser error but neither the rejected bytes nor its error category.
All additional hardware and offline reproduction checks passed. No firmware,
parser implementation, or acceptance rule was changed to make this pass.
The original run remains **TEST_FAIL**.

## Original evidence and classification

The failed job is `5ec6d3c9-73f5-4537-a41f-b370c294e23e`, run 1 in
[the thermal report](clock600-thermal-20261016.md), archived at commit `334ca79`.
It completed 600 seconds and failed only
`host.parser_errors: expected 0, got 1` among 131 checks.

The host accepted 1,186,305 ADC frames and 296,576 GPIO frames. Sequence and
sample-timestamp continuity passed; these counts and payload/framed-byte totals
reconciled with firmware transmission counters. DMA, active-loss, paired-bank,
and STOP-tail checks passed. Thus there is **no observed loss of complete ADC
or GPIO frames** in this record. An aggregate parser-error count alone does not
establish missing sample data.

`FrameParser.errors` is the sum of header, checksum, and payload rejection
counters. The original runner recorded none of those categories individually
when only a final acceptance predicate failed. The saved JSON has aggregates
and temperatures, not a serial byte stream. Inspection of the rig's original
work directory found only `child.py` and `firmware.ino.hex`. The remote runner's
SHA-256 exactly matches the locally archived submitted program:
`20e548e675f6ccf7c085fa8e86264200028b0ff0d55457405a6c1a3abddd9691`.
There is no additional original wire capture to recover there.

The rig kernel log shows programming/cleanup USB re-enumerations around the
job, without an intervening capture-time disconnect/reset. That does not prove
wire or firmware correctness. The previously documented programming retry is
not evidence that it caused the parser rejection.

| Candidate explanation | Finding |
| --- | --- |
| Host parser rejects a valid frame | Not demonstrated; archived and current parsing logic passed the boundary replay. Original rejected bytes are absent. |
| Firmware emits malformed framing | Not demonstrated; no malformed frame recurred in the new captures. Original rejected bytes are absent. |
| Genuine missing complete ADC/GPIO frames | Not observed; original continuity and final transmission accounting passed. |

It is not defensible to label the original event a checksum failure, benign
startup noise, or a temperature fault. Classification between a parser defect
and malformed/extra wire bytes requires a captured recurrence. The bounded
rejection diagnostics introduced in `874a912` remain enabled for that purpose.

## Physical reproduction

Every job used the **exact archived failed-run HEX**, verified against its
manifest: `thingdaq-6c8a85596662e413`, Teensy 4.0 serial 20428100, 600 MHz CPU,
normal frames, standard Adler-32, both 12-bit ADCs and sixteen GPIO inputs at
1 MS/s each. Temperature polling and the existing 80 °C abort remained enabled.
The watchdog remains disabled. The current independent validator adds rejection
evidence while preserving the original zero-error, continuity, loss, and
conservation requirements.

| Job | Captures | Acceptance | Header/checksum/payload errors | Discarded bytes |
| --- | --- | --- | --- | ---: |
| `17374bfa-c199-4b79-bee7-60720392e0cd` | 1 × 600 s | PASS, 131 checks | 0 / 0 / 0 | 0 |
| `2691dd12-8bd0-4725-bf43-02a7012734a1` | 1 × 600 s | PASS, 131 checks | 0 / 0 / 0 | 0 |
| `08b9ddd4-beb4-411b-a986-964c4ce827d5` | 1 × 600 s | PASS, 131 checks | 0 / 0 / 0 | 0 |
| `386d9dd7-cf49-4bfc-85cc-281183b9ca70` | 40 × 10 s | PASS, 5,240 checks | 0 / 0 / 0 | 0 |

The last job repeats the same combined-input profile through serial open,
synchronization, CONFIGURE, START, STOP/drain, final grading, and serial close,
without reflashing between cells. This concentrates session and drain boundaries
rather than adding an integration matrix. All 43 captures passed **5,633 checks**
and parsed **13,541,021,056 bytes**, with no rejected frame, discarded byte,
or failed loss/reconciliation predicate. These are new passing captures, not
a replay or regrading of the original failed bytes.

## Offline investigation and repository changes

The archived failing-run parser was extracted from its frozen submitted program
and compared with the current parser. Both passed **49,636 deterministic
partition checks** covering every split of selected data/control frames,
embedded magic bytes, timestamps crossing 32 bits, end-of-soak sequence/timestamp
values, and twenty seeded mixed-frame read schedules per parser. This uses
constructed framing data, not the missing original capture. Separately, all
51 supported response/data fixtures were accepted.

`firmware/tests/test_rig_aux_input_capture.py` now includes permanent regression
coverage for every byte split of representative data/control frames, embedded
magic in a valid GPIO payload past the 32-bit timestamp boundary, and seeded
mixed-fixture chunking. The suite passed 14 tests and 29 subtests. USB transport,
packet-buffer, firmware-runtime, combined-acquisition, and protocol suites
passed another 14 tests and 92 subtests. Review of `FrameParser.feed()`,
`_partial_magic_suffix()`, `SerialLink.exchange()`, `drain_until_quiet()`,
`_final_reconciliation()`, and firmware transmit/STOP ownership found no
supported defect to patch. Passing tests do not prove absence of an intermittent
fault.

As requested, the pre-existing `doc/results/firmware-analysis-2026-09-12.md`
was committed after adding required front matter. The documentation gate also
exposed missing front matter in the existing ADC probe README; only metadata
was added there. The historical analysis body and proposed work were retained,
not executed. Documentation validation, Ruff, and whitespace checks passed.
The metadata/archive checkpoint is `3ba5789`; parser regression coverage is
`eca6b75`.

## Evidence and disposition

The [machine-readable investigation](parser600-investigation-20261017.json)
retains original-failure references, new grades and complete metrics, program
and artifact hashes, local test results, and postflight health. Full submitted
programs, firmware, service replies, replay script, and kernel log are retained
locally under `doc/results/raw/parser600-20261017/`.

The rig finished healthy with an empty queue; the exact 600 MHz image remains
flashed with capture stopped. The broader integration plan was not started.
The missing original rejection bytes and lack of a captured recurrence prevent
a defensible root-cause fix. Keep this issue open until such evidence exists;
do not clear counters, relax checks, or promote the historical failure to PASS.
