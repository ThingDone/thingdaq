"""Deterministic synthetic ADC and GPIO source formulas."""

from __future__ import annotations

import struct

from ._generated import protocol_constants as constants
from .models import AdcConverter


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


def synthetic_adc_payload(
    start_index: int,
    pair_count: int = constants.ADC_PAIRS_PER_FRAME,
) -> bytes:
    """Build little-endian ADC pairs beginning at a global logical pair index."""

    first = _sample_index(start_index)
    if not isinstance(pair_count, int) or pair_count < 0:
        raise ValueError("pair_count must be a nonnegative integer")
    payload = bytearray(pair_count * constants.ADC_BYTES_PER_PAIR)
    for offset in range(pair_count):
        index = first + offset
        struct.pack_into(
            "<HH",
            payload,
            offset * constants.ADC_BYTES_PER_PAIR,
            synthetic_adc0_code(index),
            synthetic_adc1_code(index),
        )
    return bytes(payload)


def synthetic_gpio_payload(
    start_index: int,
    sample_count: int = constants.GPIO_SAMPLES_PER_FRAME,
) -> bytes:
    """Build packed simultaneous GPIO samples beginning at global index ``m``."""

    first = _sample_index(start_index)
    if not isinstance(sample_count, int) or sample_count < 0:
        raise ValueError("sample_count must be a nonnegative integer")
    return bytes(synthetic_gpio_byte(first + offset) for offset in range(sample_count))


__all__ = [
    "synthetic_adc0_code",
    "synthetic_adc1_code",
    "synthetic_adc_code",
    "synthetic_adc_payload",
    "synthetic_gpio_byte",
    "synthetic_gpio_payload",
]
