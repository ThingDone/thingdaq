"""Deterministic synthetic ADC and GPIO source formulas."""

from __future__ import annotations

import struct
from enum import Enum
from functools import lru_cache

from ._generated import protocol_constants as constants
from .models import ADCBlock, AdcConverter, AuxBankMode, GPIOBlock


class SyntheticGPIOPattern(Enum):
    """Deterministic GPIO stress formulas applied independently per bank."""

    ALL_ZERO = "all-zero"
    WALKING_BIT = "walking-bit"
    COUNTER = "counter"
    HIGH_TRANSITION = "high-transition"


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


def synthetic_gpio_bank_bytes(
    sample_index: int,
    pattern: SyntheticGPIOPattern | str = SyntheticGPIOPattern.COUNTER,
) -> tuple[int, int]:
    """Return independent ``(primary, auxiliary)`` bank bytes for one sample."""

    index = _sample_index(sample_index)
    try:
        selected = SyntheticGPIOPattern(pattern)
    except (TypeError, ValueError) as exc:
        raise ValueError("unknown synthetic GPIO pattern") from exc
    if selected is SyntheticGPIOPattern.ALL_ZERO:
        return 0, 0
    if selected is SyntheticGPIOPattern.WALKING_BIT:
        return 1 << (index % 8), 1 << ((index + 3) % 8)
    if selected is SyntheticGPIOPattern.COUNTER:
        return index & 0xFF, (3 * index + 0x55) & 0xFF
    return (
        (0xAA if index % 2 == 0 else 0x55),
        (0x0F if index % 2 == 0 else 0xF0),
    )


def synthetic_gpio_value(
    sample_index: int,
    *,
    aux_bank_mode: AuxBankMode | int = AuxBankMode.DISABLED,
    pattern: SyntheticGPIOPattern | str = SyntheticGPIOPattern.COUNTER,
) -> int:
    """Return one packed 8- or 16-bit sample for the selected bank mode."""

    if isinstance(aux_bank_mode, bool):
        raise TypeError("auxiliary bank mode must be DISABLED or INPUT")
    try:
        mode = AuxBankMode(aux_bank_mode)
    except (TypeError, ValueError) as exc:
        raise ValueError("auxiliary bank mode must be DISABLED or INPUT") from exc
    primary, auxiliary = synthetic_gpio_bank_bytes(sample_index, pattern)
    return primary if mode is AuxBankMode.DISABLED else primary | (auxiliary << 8)


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


@lru_cache(maxsize=len(AuxBankMode) * len(SyntheticGPIOPattern))
def _gpio_mode_pattern_cycle(
    mode: AuxBankMode,
    pattern: SyntheticGPIOPattern,
) -> bytes:
    if mode is AuxBankMode.DISABLED and pattern is SyntheticGPIOPattern.COUNTER:
        return _gpio_pattern_cycle()
    payload = bytearray(256 * (1 if mode is AuxBankMode.DISABLED else 2))
    for index in range(256):
        value = synthetic_gpio_value(
            index,
            aux_bank_mode=mode,
            pattern=pattern,
        )
        if mode is AuxBankMode.DISABLED:
            payload[index] = value
        else:
            struct.pack_into("<H", payload, index * 2, value)
    return bytes(payload)


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
    *,
    aux_bank_mode: AuxBankMode | int = AuxBankMode.DISABLED,
    pattern: SyntheticGPIOPattern | str = SyntheticGPIOPattern.COUNTER,
) -> bytes:
    """Build packed simultaneous GPIO samples beginning at global index ``m``."""

    first = _sample_index(start_index)
    if not isinstance(sample_count, int) or sample_count < 0:
        raise ValueError("sample_count must be a nonnegative integer")
    try:
        mode = AuxBankMode(aux_bank_mode)
        selected_pattern = SyntheticGPIOPattern(pattern)
    except (TypeError, ValueError) as exc:
        raise ValueError("unknown GPIO mode/pattern") from exc
    item_bytes = 1 if mode is AuxBankMode.DISABLED else 2
    return _cyclic_bytes(
        _gpio_mode_pattern_cycle(mode, selected_pattern),
        first * item_bytes,
        sample_count * item_bytes,
    )


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
    *,
    aux_bank_mode: AuxBankMode | int = AuxBankMode.DISABLED,
    pattern: SyntheticGPIOPattern | str = SyntheticGPIOPattern.COUNTER,
) -> None:
    """Validate a packed GPIO ramp without expanding bytes into pin booleans."""

    first = _sample_index(start_index)
    if (
        not isinstance(sample_count, int)
        or isinstance(sample_count, bool)
        or sample_count < 0
    ):
        raise ValueError("sample_count must be a nonnegative integer")
    try:
        mode = AuxBankMode(aux_bank_mode)
        selected_pattern = SyntheticGPIOPattern(pattern)
    except (TypeError, ValueError) as exc:
        raise ValueError("unknown GPIO mode/pattern") from exc
    item_bytes = 1 if mode is AuxBankMode.DISABLED else 2
    if len(payload) != sample_count * item_bytes:
        raise SyntheticPatternError(
            f"GPIO payload has {len(payload)} bytes; expected "
            f"{sample_count * item_bytes}"
        )
    mismatch = _cyclic_mismatch(
        payload,
        _gpio_mode_pattern_cycle(mode, selected_pattern),
        first * item_bytes,
    )
    if mismatch is None:
        return
    sample_offset = mismatch // item_bytes
    observed = (
        payload[sample_offset]
        if item_bytes == 1
        else struct.unpack_from("<H", payload, sample_offset * item_bytes)[0]
    )
    sample_index = first + sample_offset
    raise SyntheticPatternError(
        f"GPIO sample {sample_index} is {observed}; "
        f"expected {synthetic_gpio_value(sample_index, aux_bank_mode=mode, pattern=selected_pattern)}"
    )


def validate_synthetic_block(
    block: ADCBlock | GPIOBlock,
    *,
    gpio_pattern: SyntheticGPIOPattern | str = SyntheticGPIOPattern.COUNTER,
) -> None:
    """Validate one decoded block's source marker, timestamp, count, and pattern."""

    if not isinstance(block, (ADCBlock, GPIOBlock)):
        raise TypeError("synthetic validation requires an ADCBlock or GPIOBlock")
    if not block.flags & constants.FrameFlag.SYNTHETIC:
        raise SyntheticPatternError("synthetic block is missing the SYNTHETIC flag")
    if isinstance(block, ADCBlock):
        if block.first_sample_ticks % block.pair_period_ticks:
            raise SyntheticPatternError("ADC timestamp is not pair-period aligned")
        validate_synthetic_adc_payload(
            block.payload,
            block.first_pair_index,
            block.item_count,
        )
    else:
        if block.first_sample_ticks % block.sample_period_ticks:
            raise SyntheticPatternError("GPIO timestamp is not sample-period aligned")
        validate_synthetic_gpio_payload(
            block.payload,
            block.first_sample_index,
            block.item_count,
            aux_bank_mode=block.aux_bank_mode,
            pattern=gpio_pattern,
        )


__all__ = [
    "SyntheticGPIOPattern",
    "SyntheticPatternError",
    "synthetic_adc0_code",
    "synthetic_adc1_code",
    "synthetic_adc_code",
    "synthetic_adc_payload",
    "synthetic_gpio_bank_bytes",
    "synthetic_gpio_byte",
    "synthetic_gpio_payload",
    "synthetic_gpio_value",
    "validate_synthetic_adc_payload",
    "validate_synthetic_block",
    "validate_synthetic_gpio_payload",
]
