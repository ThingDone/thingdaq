---
type: reference
title: 1 MHz Parallel Output Idea
created: 2026-09-04
tags:
  - thingdaq
  - digital-output
  - docgraph-alias
related:
  - '[[output_idea]]'
  - '[[Clock-Compression-IO-Report]]'
---

# 1 MHz parallel output idea

> [!IMPORTANT]
> Release 1.1.0 uses [[Protocol-V2]]: 450 MHz core, both ADCs and GPIO at
> 1 MHz, with 8 or 16 GPIO inputs. Phase-numbered results and legacy v1
> examples below are historical; their 600 MHz / 4 MHz claims are not current
> release settings. Use live INFO metadata. `TimestampAligner` does not support
> the new unequal-duration ADC/GPIO frames; use block sample timestamps.

The original deferred proposal is [[output_idea]]. This stable DocGraph alias
lets synthesis reports cite it by its published title while preserving the
established `doc/output_idea.md` path.
