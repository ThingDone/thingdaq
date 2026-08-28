---
type: research
title: Checksum Candidates
created: 2026-08-28
tags:
  - teensy-daq
  - checksum
  - crc32c
  - teensy-4-0
  - imxrt1062
related:
  - '[[Protocol-V1]]'
  - '[[ADR-002-Checksum-Selection]]'
  - '[[Firmware-Resource-Map]]'
  - '[[Phase-05-Checksum-Correctness]]'
---

# Checksum candidates

## Outcome

Three allocation-free, stateless software candidates are implemented in
`firmware/src/checksum.h`: standard Adler-32, CRC-32C Castagnoli, and
CRC-32/ISO-HDLC. The [[Protocol-V1]] codec maps checksum IDs 1, 2, and 3 through
that one interface without changing framing or packetization. Adler-32 remains
the fixed checksum for every request and response; CONFIGURE selects the data
algorithm advertised by INFO, and each data-frame header repeats the ID.

No hardware-assisted wire candidate was implemented. The i.MX RT1062 DCP is a
real general-memory CRC engine with its own channels, but its fixed algorithm
is CRC-32/MPEG-2, not CRC-32C or CRC-32/ISO-HDLC. USB, ENET, FlexCAN, and LCDIF
CRC logic is bound to those peripherals rather than exposed as an arbitrary
memory checksum. The Arm Cortex-M7 has useful scalar, bit-manipulation, and DSP
instructions, but no CRC or carry-less polynomial-multiply instruction.

## Wire semantics under evaluation

Every candidate is intended to replace only the interpretation of the fixed
32-bit trailer. Frame boundaries, header layout, payload layout, and parser
behavior remain identical.

| Property | Adler-32 | CRC-32C Castagnoli | CRC-32/ISO-HDLC |
| --- | --- | --- | --- |
| Width | 32 bits | 32 bits | 32 bits |
| Normal polynomial | Not applicable | `0x1EDC6F41` | `0x04C11DB7` |
| Reflected polynomial used by code | Not applicable | `0x82F63B78` | `0xEDB88320` |
| Initialization | `s1=1`, `s2=0` | `0xFFFFFFFF` | `0xFFFFFFFF` |
| Input/output reflection | Not applicable | Yes / yes | Yes / yes |
| Final XOR | None | `0xFFFFFFFF` | `0xFFFFFFFF` |
| Reduction modulus | 65,521 | Not applicable | Not applicable |
| Empty input | `0x00000001` | `0x00000000` | `0x00000000` |
| ASCII `123456789` | `0x091E01DE` | `0xE3069283` | `0xCBF43926` |
| `123456789` trailer bytes | `DE 01 1E 09` | `83 92 06 E3` | `26 39 F4 CB` |

Coverage is exactly the bytes from the first magic byte through the final
payload byte, including the checksum-algorithm byte in the header. The four
trailer bytes are excluded rather than treated as zero. The resulting unsigned
32-bit integer is serialized little endian. These checksums detect accidental
errors; none provides authentication or other security.

The Adler implementation reduces both accumulators after at most 5,552 input
bytes, the RFC/zlib bound that keeps unsigned 32-bit intermediate values safe
while avoiding division per byte. Both CRC implementations use four generated
256-entry slices and therefore claim 4,096 bytes of constant table storage
each. Both CRC tables are explicitly linked into memory-mapped program flash.
Build manifest schema 5 records each linked symbol and reports 4,096 flash
bytes and zero RAM bytes per CRC (8,192/0 bytes total); Adler-32 uses no table.

## Inspected implementation baseline

The inspection used the installed target selected by
`firmware/tools/build_firmware.py`, not an unpinned online core:

| Item | Inspected identity |
| --- | --- |
| FQBN | `teensy:avr:teensy40:usb=serial,speed=600,opt=o2std` |
| Board / MCU | Teensy 4.0 / NXP i.MX RT1062 |
| Core | `teensy:avr` 1.62.0; compile identity `TEENSYDUINO=160` |
| CPU / compiler | Cortex-M7 at 600 MHz / Arm GNU 15.2.1 / C++17 / `-O2` |
| Pinned register header | `~/.arduino15/packages/teensy/hardware/avr/1.62.0/cores/teensy4/imxrt.h`, SHA-256 `0f90606d1b460d8ac80ee2c1e87abbed9bb3746b1d7be4bce1e07a271123b6d2` |
| Pinned FastCRC software source | `libraries/FastCRC/FastCRCsw.cpp`, SHA-256 `f34c36ea0cae6db4e1c50569dd3f607cca6dc9dbecee07a9a813a3c3ad2c1441` |
| Pinned FastCRC hardware source | `libraries/FastCRC/FastCRChw.cpp`, SHA-256 `a8bc597680c2a40d8e332a36c770b3f1e2f50d55549d2fb82b351f3002321ae7` |

The shared frame codec already had the correct Adler coverage and little-endian
trailer store. The change extracts only the arithmetic into the reusable
candidate interface; encoder, decoder, parser, packetizer, and fixtures retain
their existing behavior.

## Core and library survey

### Bundled FastCRC

The core-bundled FastCRC library explicitly selects hardware only for
`KINETISK`, the Teensy 3.x family. On the i.MX RT1062 it compiles
`FastCRCsw.cpp`, which provides CRC-32/ISO-HDLC with a 4 KiB slicing-by-four
table when its default `CRC_BIGTABLES=1` is retained. It does not provide
CRC-32C. Its update interface stores mutable seed state in an object, accepts a
16-bit length, and reads aligned input through `uint32_t *` casts.

CRC-32/ISO-HDLC is therefore retained as a meaningful comparison, but the
production candidates do not directly depend on FastCRC. The local interface
is stateless, accepts `size_t`, has defined byte access for every alignment,
and uses its own generated 4 KiB slicing-by-four table for each CRC. The
additional 3 KiB per polynomial was included only after the target DWT
measurement below demonstrated that the original bytewise 1 KiB table missed
the fixed throughput and CPU gates. See the pinned upstream
[FastCRC software implementation](https://github.com/FrankBoesing/FastCRC/blob/c669a8915dcec9d16fa60ee7772b7b2200f0cdc5/src/FastCRCsw.cpp)
and
[hardware selection](https://github.com/FrankBoesing/FastCRC/blob/c669a8915dcec9d16fa60ee7772b7b2200f0cdc5/src/FastCRChw.cpp).

### Cortex-M7 instructions

The Cortex-M7 implements Armv7E-M Thumb/Thumb-2 with `RBIT`, byte reversal,
integer multiply, and 8/16-bit SIMD/DSP arithmetic. Its documented instruction
set contains no CRC instruction and no carry-less polynomial multiply. Those
DSP operations do not directly accelerate the GF(2) recurrence enough to
justify a separate unmeasured implementation. The later microbenchmark can
compare additional scalar unrolling only if linked size and target cycles
support it. Sources: the
[Cortex-M7 Technical Reference Manual](https://documentation-service.arm.com/static/5e906dc68259fe2368e2abbe)
and the
[Arm Cortex-M7 product specification](https://developer.arm.com/compute-ip/cortex-m7).

## i.MX RT1062 hardware survey

| Block | General-memory checksum? | Resource and algorithm finding | Candidate decision |
| --- | --- | --- | --- |
| DCP | Yes, through DCP work packets and its own four channels | Fixed CRC-32/MPEG-2: `poly=0x04C11DB7`, `init=0xFFFFFFFF`, non-reflected input/output, `xorout=0`; a DCP channel, command/context storage, clock setup, memory-bus traffic, barriers, alignment, and cache clean/invalidate ownership are required | Rejected: it cannot produce either evaluated CRC from the original frame bytes |
| USB1 | No | USB link CRC generation/checking is part of endpoint traffic and does not return an arbitrary buffer checksum; USB1 is already the transport owner | Rejected; never commandeer transport state |
| ENET/ENET2 | No | Ethernet FCS and CRC/error counters operate on MAC frames/descriptors, not an arbitrary memory range exposed as a digest | Rejected; would claim an unrelated MAC and bus/descriptor path |
| FlexCAN1-3 | No | CRC registers report CAN protocol state tied to message transmission/reception | Rejected; would claim CAN state and still not provide a memory API |
| LCDIF | No | `CRC_STAT` belongs to the LCD output stream | Rejected; display-stream CRC is not a memory checksum |
| eDMA/PIT/XBAR/ADC_ETC/ADC | No CRC engine | These are explicitly reserved acquisition resources in [[Firmware-Resource-Map]] | Untouched |

The pinned Teensy register header exposes the DCP base address and clock gate
but leaves its definitions as a `TODO`; its other CRC-named registers belong
to ENET, FlexCAN, or LCDIF. See the pinned
[PJRC i.MX RT register header](https://github.com/PaulStoffregen/cores/blob/7f107ee0a309f3813ed13f0d8f615497eca2ee49/teensy4/imxrt.h)
and NXP's current
[i.MX RT1060 reference-manual listing](https://www.nxp.com/products/i.MX-RT1060?tab=Documentation_Tab).

NXP's official RT1060 DCP example removes any polynomial ambiguity: it labels
the DCP parameters as CRC-32/MPEG-2 and expects `7F 04 6A DD` for its 32-byte
test string. It also places output in non-cacheable storage and warns that
cached inputs and outputs require explicit cache maintenance. The SDK driver
uses a work packet, DCP channel semaphore, barriers, context buffers, and
cache-line handling; its history includes a CRC block-boundary correctness fix.
Sources:

- [NXP RT1060 DCP example](https://github.com/nxp-mcuxpresso/legacy-mcux-sdk-examples/blob/52b428258efda7d5bd8a2ace2195ca828356743a/evkbmimxrt1060/driver_examples/dcp/dcp.c)
- [NXP DCP driver interface](https://github.com/nxp-mcuxpresso/legacy-mcux-sdk/blob/8a289764d763ad06e0c3a05c885644ed98b970af/drivers/dcp/fsl_dcp.h)
- [NXP DCP driver implementation](https://github.com/nxp-mcuxpresso/legacy-mcux-sdk/blob/8a289764d763ad06e0c3a05c885644ed98b970af/drivers/dcp/fsl_dcp.c)
- [PJRC community DCP proof of concept](https://github.com/manitou48/teensy4/blob/56d27a765200e692fb0c663292b7cffb7251dd02/dcptst.ino)

Bit-reflecting every source byte into a staging buffer could transform the DCP
input toward CRC-32/ISO-HDLC, but it adds a complete CPU read/write pass,
temporary storage, cache ownership, and a second DCP read. It still cannot
change the polynomial to Castagnoli. That is neither zero-copy nor a safe
checksum of the packet buffer and was not implemented.

## Implemented resource contract

The three candidates:

- allocate no heap memory and retain no mutable state;
- read input bytes without alignment assumptions;
- claim no interrupt, DCP channel, eDMA channel, DMAMUX source, timer, XBAR
  route, ADC, USB controller, ENET controller, or cache-maintenance ownership;
- use no table for Adler-32 and one 4,096-byte constant slicing table for each
  CRC;
- return only an unsigned 32-bit value, leaving the shared codec as the single
  owner of coverage and little-endian serialization;
- reject unknown IDs, control frames that do not use bootstrap Adler-32, and
  data completions whose ID disagrees with their active packet epoch.

Published parameter references are
[RFC 1950 section 8.2](https://www.rfc-editor.org/rfc/rfc1950.html#section-8.2)
for Adler-32 and
[RFC 3720 appendix B](https://www.rfc-editor.org/rfc/rfc3720.html#appendix-B)
for CRC-32C. Canonical vectors and independent bitwise references are compiled
separately in `firmware/tests/checksum_candidates_test.cpp`; the expanded
cross-language, corruption, negotiation, parser-recovery, and benchmark guard
results are recorded in [[Phase-05-Checksum-Correctness]].

## Target-triggered slicing decision

The first physical campaign job,
`05694247-0dc3-4a8e-9f19-e1efc24aba72`, measured the original bytewise-table
CRC-32C at 8.018 cycles/byte, 74.831 MB/s, and 10.824% projected CPU on the
representative hot DTCM frame. That missed both predeclared qualification
bounds: at least 81 MB/s and no more than 10% of the 600 MHz core. The same job
then observed a genuine ADC gap flag at sequence 110 during the CRC-32C stream;
it was retained as failed evidence and not relabeled as an accepted campaign.

Those target measurements justified the previously deferred slicing-by-four
variant. The replacement consumes 4,096 flash bytes and zero RAM bytes per
polynomial, uses alignment-safe `memcpy` loads rather than FastCRC's typed
pointer casts, retains the bytewise tail for every length, and passes the
separately compiled bitwise references, 32 input alignments, length edges, and
cross-language corpus in [[Phase-05-Checksum-Correctness]]. The exact linked
CRC bodies are 116 bytes each. Size optimization keeps total ITCM code below
the next 32 KiB RAM1 allocation boundary, preserving 79,808 bytes for
locals/stack.

The production choice remains intentionally open until the repaired target
campaign supplies hot/cold DWT measurements and three lossless 60-second
streams to the fixed policy in [[ADR-002-Checksum-Selection]].
