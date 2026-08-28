"""Deterministic synthetic ADC and GPIO source formulas."""

from __future__ import annotations

import struct
from functools import lru_cache

from ._generated import protocol_constants as constants
from .models import ADCBlock, AdcConverter, GPIOBlock


class SyntheticPatternError(ValueError):
    """A decoded synthetic payload differs from its advertised formula."""


def _sample_index(value: int) -> int:
    if not isinstance(value, int) or value < 0:
        raise ValueError("sample index must be a nonnegative integer")
    return value


def synthetic_adc_code(converter: AdcConverter | int, sample_index: int) -> int:
    """Return ``2*n`` for ADC0 or ``2*n+1`` for ADC1 modulo 12 bits."""

    try:
        selected_converter = AdcConverter(converter)
    except ValueError as exc:
        raise ValueError("converter must be ADC0 or ADC1") from exc
    index = _sample_index(sample_index)
    code_mask = (1 << constants.ADC_RESOLUTION_BITS) - 1
    return (2 * index + int(selected_converter)) & code_mask


def synthetic_adc0_code(sample_index: int) -> int:
    """Return the deterministic ADC0/A0 code for logical pair index ``n``."""

    return synthetic_adc_code(AdcConverter.ADC0, sample_index)


def synthetic_adc1_code(sample_index: int) -> int:
    """Return the deterministic ADC1/A1 code for logical pair index ``n``."""

    return synthetic_adc_code(AdcConverter.ADC1, sample_index)


def synthetic_gpio_byte(sample_index: int) -> int:
    """Return the packed D6-through-D13 sample ``m modulo 256``."""

    return _sample_index(sample_index) & 0xFF


@lru_cache(maxsize=1)
def _adc_pattern_cycle() -> bytes:
    pair_period = 1 << (constants.ADC_RESOLUTION_BITS - 1)
    payload = bytearray(pair_period * constants.ADC_BYTES_PER_PAIR)
    code_mask = (1 << constants.ADC_RESOLUTION_BITS) - 1
    for index in range(pair_period):
        struct.pack_into(
            "<HH",
            payload,
            index * constants.ADC_BYTES_PER_PAIR,
            (2 * index) & code_mask,
            (2 * index + 1) & code_mask,
        )
    return bytes(payload)


@lru_cache(maxsize=1)
def _gpio_pattern_cycle() -> bytes:
    return bytes(range(256))


def _cyclic_bytes(cycle: bytes, start: int, length: int) -> bytes:
    if length == 0:
        return b""
    offset = start % len(cycle)
    first = min(length, len(cycle) - offset)
    if first == length:
        return cycle[offset : offset + length]
    remaining = length - first
    repeats, tail = divmod(remaining, len(cycle))
    return cycle[offset:] + cycle * repeats + cycle[:tail]


def _cyclic_mismatch(
    payload: bytes | bytearray | memoryview,
    cycle: bytes,
    start: int,
) -> int | None:
    """Return the first mismatched byte, with a C-level fast path per segment."""

    try:
        actual = memoryview(payload).cast("B")
    except TypeError:
        actual = memoryview(bytes(payload))
    expected = memoryview(cycle)
    try:
        position = 0
        cycle_position = start % len(cycle)
        while position < len(actual):
            segment_length = min(
                len(actual) - position,
                len(cycle) - cycle_position,
            )
            actual_segment = actual[position : position + segment_length]
            expected_segment = expected[
                cycle_position : cycle_position + segment_length
            ]
            try:
                if actual_segment != expected_segment:
                    for relative in range(segment_length):
                        if actual_segment[relative] != expected_segment[relative]:
                            return position + relative
            finally:
                actual_segment.release()
                expected_segment.release()
            position += segment_length
            cycle_position = 0
        return None
    finally:
        actual.release()
        expected.release()


def synthetic_adc_payload(
    start_index: int,
    pair_count: int = constants.ADC_PAIRS_PER_FRAME,
) -> bytes:
    """Build little-endian ADC pairs beginning at a global logical pair index."""

    first = _sample_index(start_index)
    if not isinstance(pair_count, int) or pair_count < 0:
        raise ValueError("pair_count must be a nonnegative integer")
    return _cyclic_bytes(
        _adc_pattern_cycle(),
        first * constants.ADC_BYTES_PER_PAIR,
        pair_count * constants.ADC_BYTES_PER_PAIR,
    )


def synthetic_gpio_payload(
    start_index: int,
    sample_count: int = constants.GPIO_SAMPLES_PER_FRAME,
) -> bytes:
    """Build packed simultaneous GPIO samples beginning at global index ``m``."""

    first = _sample_index(start_index)
    if not isinstance(sample_count, int) or sample_count < 0:
        raise ValueError("sample_count must be a nonnegative integer")
    return _cyclic_bytes(_gpio_pattern_cycle(), first, sample_count)


def validate_synthetic_adc_payload(
    payload: bytes | bytearray | memoryview,
    start_index: int,
    pair_count: int = constants.ADC_PAIRS_PER_FRAME,
) -> None:
    """Validate an ADC ramp in bounded cyclic views without expanding samples."""

    first = _sample_index(start_index)
    if (
        not isinstance(pair_count, int)
        or isinstance(pair_count, bool)
        or pair_count < 0
    ):
        raise ValueError("pair_count must be a nonnegative integer")
    expected_bytes = pair_count * constants.ADC_BYTES_PER_PAIR
    if len(payload) != expected_bytes:
        raise SyntheticPatternError(
            f"ADC payload has {len(payload)} bytes; expected {expected_bytes}"
        )
    mismatch = _cyclic_mismatch(
        payload,
        _adc_pattern_cycle(),
        first * constants.ADC_BYTES_PER_PAIR,
    )
    if mismatch is None:
        return
    pair_offset = mismatch // constants.ADC_BYTES_PER_PAIR
    observed_adc0, observed_adc1 = struct.unpack_from(
        "<HH",
        payload,
        pair_offset * constants.ADC_BYTES_PER_PAIR,
    )
    sample_index = first + pair_offset
    raise SyntheticPatternError(
        f"ADC pair {sample_index} is ({observed_adc0}, {observed_adc1}); "
        f"expected ({synthetic_adc0_code(sample_index)}, "
        f"{synthetic_adc1_code(sample_index)})"
    )


def validate_synthetic_gpio_payload(
    payload: bytes | bytearray | memoryview,
    start_index: int,
    sample_count: int = constants.GPIO_SAMPLES_PER_FRAME,
) -> None:
    """Validate a packed GPIO ramp without expanding bytes into pin booleans."""

    first = _sample_index(start_index)
    if (
        not isinstance(sample_count, int)
        or isinstance(sample_count, bool)
        or sample_count < 0
    ):
        raise ValueError("sample_count must be a nonnegative integer")
    if len(payload) != sample_count:
        raise SyntheticPatternError(
            f"GPIO payload has {len(payload)} bytes; expected {sample_count}"
        )
    mismatch = _cyclic_mismatch(payload, _gpio_pattern_cycle(), first)
    if mismatch is None:
        return
    observed_view = memoryview(payload).cast("B")
    try:
        observed = observed_view[mismatch]
    finally:
        observed_view.release()
    sample_index = first + mismatch
    raise SyntheticPatternError(
        f"GPIO sample {sample_index} is {observed}; "
        f"expected {synthetic_gpio_byte(sample_index)}"
    )


def validate_synthetic_block(block: ADCBlock | GPIOBlock) -> None:
    """Validate one decoded block's source marker, timestamp, count, and pattern."""

    if not isinstance(block, (ADCBlock, GPIOBlock)):
        raise TypeError("synthetic validation requires an ADCBlock or GPIOBlock")
    if not block.flags & constants.FrameFlag.SYNTHETIC:
        raise SyntheticPatternError("synthetic block is missing the SYNTHETIC flag")
    if isinstance(block, ADCBlock):
        if block.first_sample_ticks % constants.ADC_PAIR_PERIOD_TICKS:
            raise SyntheticPatternError("ADC timestamp is not pair-period aligned")
        validate_synthetic_adc_payload(
            block.payload,
            block.first_pair_index,
            block.item_count,
        )
    else:
        if block.first_sample_ticks % constants.GPIO_SAMPLE_PERIOD_TICKS:
            raise SyntheticPatternError("GPIO timestamp is not sample-period aligned")
        validate_synthetic_gpio_payload(
            block.payload,
            block.first_sample_index,
            block.item_count,
        )


__all__ = [
    "SyntheticPatternError",
    "synthetic_adc0_code",
    "synthetic_adc1_code",
    "synthetic_adc_code",
    "synthetic_adc_payload",
    "synthetic_gpio_byte",
    "synthetic_gpio_payload",
    "validate_synthetic_adc_payload",
    "validate_synthetic_block",
    "validate_synthetic_gpio_payload",
]
