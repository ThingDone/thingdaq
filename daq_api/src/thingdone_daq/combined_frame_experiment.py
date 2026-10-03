"""Experiment-only decoder for combined ADC/GPIO frames without a trailer."""

from __future__ import annotations

import struct
from dataclasses import dataclass

MAGIC = 0xDEADBEEF
PROTOCOL_VERSION = 2
FRAME_KIND = 3
NONE_DATA_CHECKSUM = 4
HEADER_SIZE = 44
ITEM_COUNT = 1012
_HEADER = struct.Struct("<IBBHHBBIIIIIQI")


@dataclass(frozen=True, slots=True)
class CombinedFrame:
    flags: int
    run_id: int
    sequence: int
    first_sample_ticks: int
    adc0: tuple[int, ...]
    adc1: tuple[int, ...]
    gpio: tuple[int, ...]
    gpio_bytes_per_sample: int

    @property
    def item_count(self) -> int:
        return len(self.adc0)


def decode_combined_frame(wire: bytes, *, gpio_bytes_per_sample: int) -> CombinedFrame:
    """Decode structure only; the format intentionally has no integrity check."""

    if gpio_bytes_per_sample not in (1, 2):
        raise ValueError("GPIO width must be one or two bytes")
    expected_size = HEADER_SIZE + ITEM_COUNT * (4 + gpio_bytes_per_sample)
    if len(wire) != expected_size:
        raise ValueError("combined frame length is inconsistent")
    (
        magic,
        version,
        kind,
        flags,
        header_size,
        checksum_algorithm,
        reserved,
        total_length,
        payload_length,
        run_id,
        sequence,
        request_id,
        first_sample_ticks,
        item_count,
    ) = _HEADER.unpack_from(wire)
    if (
        magic != MAGIC
        or version != PROTOCOL_VERSION
        or kind != FRAME_KIND
        or flags & ~0x000F
        or header_size != HEADER_SIZE
        or checksum_algorithm != NONE_DATA_CHECKSUM
        or reserved != 0
        or total_length != expected_size
        or payload_length != expected_size - HEADER_SIZE
        or run_id == 0
        or request_id != 0
        or item_count != ITEM_COUNT
    ):
        raise ValueError("combined frame header is invalid")
    adc0: list[int] = []
    adc1: list[int] = []
    gpio: list[int] = []
    item = struct.Struct("<HHB" if gpio_bytes_per_sample == 1 else "<HHH")
    for values in item.iter_unpack(wire[HEADER_SIZE:]):
        first, second, digital = values
        if first > 0xFFF or second > 0xFFF:
            raise ValueError("combined frame contains an invalid 12-bit ADC code")
        adc0.append(first)
        adc1.append(second)
        gpio.append(digital)
    return CombinedFrame(
        flags=flags,
        run_id=run_id,
        sequence=sequence,
        first_sample_ticks=first_sample_ticks,
        adc0=tuple(adc0),
        adc1=tuple(adc1),
        gpio=tuple(gpio),
        gpio_bytes_per_sample=gpio_bytes_per_sample,
    )


class CombinedSequenceTracker:
    """Count complete missing intervals from the combined frame sequence."""

    def __init__(self) -> None:
        self._run_id: int | None = None
        self._last_sequence: int | None = None
        self.dropped_frames = 0

    def observe(self, frame: CombinedFrame) -> int:
        if self._run_id != frame.run_id:
            self._run_id = frame.run_id
            self._last_sequence = frame.sequence
            return 0
        assert self._last_sequence is not None
        expected = (self._last_sequence + 1) & 0xFFFFFFFF
        gap = (frame.sequence - expected) & 0xFFFFFFFF
        if gap >= 0x80000000:
            raise ValueError("combined frame sequence moved backward or repeated")
        self._last_sequence = frame.sequence
        self.dropped_frames += gap
        return gap


__all__ = ["CombinedFrame", "CombinedSequenceTracker", "decode_combined_frame"]
