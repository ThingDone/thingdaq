"""Optional NumPy views and vectorized transforms for DAQ data blocks.

Importing :mod:`teensy_daq` never imports NumPy.  This module is loaded only
when a caller imports it explicitly or calls ``ADCBlock.as_numpy()`` or
``GPIOBlock.as_numpy()``.
"""

from __future__ import annotations

import builtins
from collections.abc import Iterable
from dataclasses import dataclass, field
from typing import Any, ClassVar

try:
    import numpy as np  # type: ignore[import-not-found]
except ModuleNotFoundError as exc:  # pragma: no cover - exercised without NumPy
    if exc.name != "numpy":
        raise
    raise ImportError(
        "optional NumPy support is not installed; install "
        "'teensy-daq-local[numpy]' or continue with the pure-Python block views"
    ) from exc

from .calibration import CalibrationRecord
from .models import ADCBlock, AdcConverter, GPIOBlock

_ADC_PAIR_DTYPE = np.dtype("<u2")
_GPIO_BYTE_DTYPE = np.dtype("u1")
_TIMESTAMP_DTYPE = np.dtype("u8")
_CALIBRATED_DTYPE = np.dtype("f8")


def _readonly(array: Any) -> Any:
    array.setflags(write=False)
    return array


def _require_adc_block(block: ADCBlock) -> ADCBlock:
    if not isinstance(block, ADCBlock):
        raise TypeError("block must be an ADCBlock")
    return block


def _require_gpio_block(block: GPIOBlock) -> GPIOBlock:
    if not isinstance(block, GPIOBlock):
        raise TypeError("block must be a GPIOBlock")
    return block


def _adc_timestamp_pairs(block: ADCBlock) -> Any:
    """Build the nominal ``(ADC0, ADC1)`` tick matrix with uint64 wrap."""

    pair_offsets = np.arange(block.item_count, dtype=_TIMESTAMP_DTYPE)
    pair_offsets *= np.uint64(block.pair_period_ticks)
    pair_offsets += np.uint64(block.first_sample_ticks)
    timestamps = np.empty((block.item_count, 2), dtype=_TIMESTAMP_DTYPE)
    timestamps[:, 0] = pair_offsets
    timestamps[:, 1] = pair_offsets + np.uint64(block.adc1_phase_ticks)
    return _readonly(timestamps)


def _gpio_timestamps(block: GPIOBlock) -> Any:
    """Build nominal packed-sample ticks with protocol uint64 wrap."""

    timestamps = np.arange(block.item_count, dtype=_TIMESTAMP_DTYPE)
    timestamps *= np.uint64(block.sample_period_ticks)
    timestamps += np.uint64(block.first_sample_ticks)
    return _readonly(timestamps)


@dataclass(frozen=True, slots=True, eq=False)
class ADCArrayView:
    """Read-only zero-copy ``(pair, converter)`` view over one ADC block.

    ``pairs`` has shape ``(item_count, 2)`` and explicit wire dtype ``<u2``.
    Its columns are ADC0/A0 then ADC1/A1.  The array and all channel slices
    borrow the immutable payload buffer; the NumPy base chain keeps that bytes
    object alive even if the source block goes out of scope.
    """

    raw_block: ADCBlock
    pairs: Any = field(init=False, repr=False)

    calibrated: ClassVar[bool] = False
    units: ClassVar[str] = "code"
    wire_endianness: ClassVar[str] = "little"
    ownership: ClassVar[str] = "borrowed-read-only"
    converter_order: ClassVar[tuple[AdcConverter, AdcConverter]] = (
        AdcConverter.ADC0,
        AdcConverter.ADC1,
    )
    pins: ClassVar[tuple[str, str]] = ("A0", "A1")

    def __post_init__(self) -> None:
        block = _require_adc_block(self.raw_block)
        pairs = np.frombuffer(
            block.payload_view,
            dtype=_ADC_PAIR_DTYPE,
            count=block.item_count * 2,
        ).reshape(block.item_count, 2)
        object.__setattr__(self, "pairs", _readonly(pairs))

    @property
    def raw_pairs(self) -> Any:
        return self.pairs

    @property
    def adc0(self) -> Any:
        return self.pairs[:, 0]

    @property
    def adc1(self) -> Any:
        return self.pairs[:, 1]

    @property
    def raw_adc0(self) -> Any:
        return self.adc0

    @property
    def raw_adc1(self) -> Any:
        return self.adc1

    @property
    def payload_owner(self) -> builtins.bytes:
        """Immutable bytes object retained by the array's NumPy base chain."""

        return self.raw_block.payload

    @property
    def run_id(self) -> int:
        return self.raw_block.run_id

    @property
    def sequence(self) -> int:
        return self.raw_block.sequence

    @property
    def t0_ticks(self) -> int:
        return self.raw_block.t0_ticks

    @property
    def timestamp_hz(self) -> int:
        return self.raw_block.timestamp_hz

    @property
    def pair_period_ticks(self) -> int:
        return self.raw_block.pair_period_ticks

    @property
    def adc1_phase_ticks(self) -> int:
        return self.raw_block.adc1_phase_ticks

    @property
    def resolution_bits(self) -> int:
        return self.raw_block.resolution_bits

    @property
    def code_range(self) -> tuple[int, int]:
        return self.raw_block.code_range

    @property
    def item_count(self) -> int:
        return self.raw_block.item_count

    @property
    def source(self) -> Any:
        return self.raw_block.source

    @property
    def metadata(self) -> Any:
        return self.raw_block.metadata

    def timestamp_pairs(self) -> Any:
        """Vectorize nominal ADC0/ADC1 ticks in the same shape as ``pairs``."""

        return _adc_timestamp_pairs(self.raw_block)

    def interleaved(self) -> ADCInterleavedArray:
        """Explicitly flatten ADC0/ADC1 codes and nominal times pair-major."""

        codes = _readonly(self.pairs.reshape(-1))
        timestamps = _readonly(self.timestamp_pairs().reshape(-1))
        return ADCInterleavedArray(
            raw_block=self.raw_block,
            raw_codes=codes,
            values=codes,
            timestamp_ticks=timestamps,
        )

    def calibrated_array(
        self,
        calibration: CalibrationRecord,
        *,
        hardware_serial: int | None = None,
        analog_front_end_profile: str | None = None,
    ) -> CalibratedADCArray:
        """Vectorize affine calibration after the core compatibility checks."""

        channels = self.raw_block.calibrated_channels(
            calibration,
            hardware_serial=hardware_serial,
            analog_front_end_profile=analog_front_end_profile,
        )
        coefficients = channels.calibration_record.converter_calibrations
        gains = np.asarray(
            (coefficients[0].gain, coefficients[1].gain),
            dtype=_CALIBRATED_DTYPE,
        )
        offsets = np.asarray(
            (coefficients[0].offset, coefficients[1].offset),
            dtype=_CALIBRATED_DTYPE,
        )
        values = np.empty(self.pairs.shape, dtype=_CALIBRATED_DTYPE)
        np.multiply(self.pairs, gains, out=values)
        np.add(values, offsets, out=values)
        return CalibratedADCArray(
            raw_view=self,
            calibration_record=channels.calibration_record,
            values=_readonly(values),
        )

    # ``calibrated`` is a visible Boolean marker, so the operation cannot use
    # that name.  Keep a concise verb while retaining the marker's public name.
    calibrate = calibrated_array


@dataclass(frozen=True, slots=True, eq=False)
class CalibratedADCArray:
    """Vectorized calibrated voltage pairs retaining their raw zero-copy view."""

    raw_view: ADCArrayView
    calibration_record: CalibrationRecord
    values: Any

    calibrated: ClassVar[bool] = True
    units: ClassVar[str] = "V"
    timing_skew_applied: ClassVar[bool] = False
    converter_order: ClassVar[tuple[AdcConverter, AdcConverter]] = (
        AdcConverter.ADC0,
        AdcConverter.ADC1,
    )
    pins: ClassVar[tuple[str, str]] = ("A0", "A1")

    def __post_init__(self) -> None:
        if not isinstance(self.raw_view, ADCArrayView):
            raise TypeError("raw_view must be an ADCArrayView")
        if not isinstance(self.calibration_record, CalibrationRecord):
            raise TypeError("calibration_record must be a CalibrationRecord")
        if (
            not isinstance(self.values, np.ndarray)
            or self.values.shape != self.raw_view.pairs.shape
            or self.values.dtype != _CALIBRATED_DTYPE
        ):
            raise TypeError("values must be a float64 ADC pair array")
        _readonly(self.values)

    @property
    def raw_block(self) -> ADCBlock:
        return self.raw_view.raw_block

    @property
    def raw_pairs(self) -> Any:
        return self.raw_view.pairs

    @property
    def raw_adc0(self) -> Any:
        return self.raw_view.adc0

    @property
    def raw_adc1(self) -> Any:
        return self.raw_view.adc1

    @property
    def adc0(self) -> Any:
        return self.values[:, 0]

    @property
    def adc1(self) -> Any:
        return self.values[:, 1]

    def timestamp_pairs(self) -> Any:
        return self.raw_view.timestamp_pairs()

    def interleaved(self) -> ADCInterleavedArray:
        """Return calibrated values on the explicit ADC0/ADC1 time grid."""

        return ADCInterleavedArray(
            raw_block=self.raw_block,
            raw_codes=_readonly(self.raw_pairs.reshape(-1)),
            values=_readonly(self.values.reshape(-1)),
            timestamp_ticks=_readonly(self.timestamp_pairs().reshape(-1)),
            calibration_record=self.calibration_record,
        )


@dataclass(frozen=True, slots=True, eq=False)
class ADCInterleavedArray:
    """Explicit ADC0/ADC1 sample vectors with raw identity and nominal ticks.

    Even indices are ADC0/A0 and odd indices are ADC1/A1.  ``raw_codes``
    remains a read-only zero-copy view.  ``values`` is that same view for raw
    data or a read-only float64 array for calibrated data.
    """

    raw_block: ADCBlock
    raw_codes: Any
    values: Any
    timestamp_ticks: Any
    calibration_record: CalibrationRecord | None = None

    converter_order: ClassVar[tuple[AdcConverter, AdcConverter]] = (
        AdcConverter.ADC0,
        AdcConverter.ADC1,
    )
    pins: ClassVar[tuple[str, str]] = ("A0", "A1")
    timing_skew_applied: ClassVar[bool] = False

    def __post_init__(self) -> None:
        block = _require_adc_block(self.raw_block)
        expected_shape = (block.item_count * 2,)
        if (
            not isinstance(self.raw_codes, np.ndarray)
            or self.raw_codes.shape != expected_shape
            or self.raw_codes.dtype != _ADC_PAIR_DTYPE
        ):
            raise TypeError("raw_codes must be a little-endian uint16 sample array")
        if (
            not isinstance(self.timestamp_ticks, np.ndarray)
            or self.timestamp_ticks.shape != expected_shape
            or self.timestamp_ticks.dtype != _TIMESTAMP_DTYPE
        ):
            raise TypeError("timestamp_ticks must be a uint64 sample array")
        expected_dtype = (
            _ADC_PAIR_DTYPE if self.calibration_record is None else _CALIBRATED_DTYPE
        )
        if (
            not isinstance(self.values, np.ndarray)
            or self.values.shape != expected_shape
            or self.values.dtype != expected_dtype
        ):
            raise TypeError("values have the wrong shape or dtype")
        if self.calibration_record is not None and not isinstance(
            self.calibration_record, CalibrationRecord
        ):
            raise TypeError("calibration_record must be a CalibrationRecord or None")
        _readonly(self.raw_codes)
        _readonly(self.values)
        _readonly(self.timestamp_ticks)

    @property
    def calibrated(self) -> bool:
        return self.calibration_record is not None

    @property
    def units(self) -> str:
        return "V" if self.calibrated else "code"

    @property
    def codes(self) -> Any:
        return self.raw_codes

    def timestamp_seconds(self) -> Any:
        """Convert retained integer ticks to START-relative float64 seconds."""

        seconds = self.timestamp_ticks.astype(_CALIBRATED_DTYPE, copy=True)
        seconds /= self.raw_block.timestamp_hz
        return _readonly(seconds)

    def pair_indices(self) -> Any:
        """Return one repeated pair index per explicitly interleaved sample."""

        indices = np.repeat(
            np.arange(self.raw_block.item_count, dtype=_TIMESTAMP_DTYPE),
            2,
        )
        return _readonly(indices)

    def converter_indices(self) -> Any:
        """Return ``0, 1, 0, 1, ...`` matching ``converter_order``."""

        indices = np.empty(self.raw_block.item_count * 2, dtype=np.dtype("u1"))
        indices[0::2] = int(AdcConverter.ADC0)
        indices[1::2] = int(AdcConverter.ADC1)
        return _readonly(indices)


@dataclass(frozen=True, slots=True, eq=False)
class GPIOArrayView:
    """Read-only zero-copy packed-byte view over one GPIO block.

    ``packed`` has shape ``(item_count,)`` and dtype ``uint8``.  Each byte is
    one simultaneous D6-through-D13 snapshot in bit order; creating this view
    does not expand any Boolean channel.
    """

    raw_block: GPIOBlock
    packed: Any = field(init=False, repr=False)

    calibrated: ClassVar[bool] = False
    units: ClassVar[str] = "packed-bits"
    ownership: ClassVar[str] = "borrowed-read-only"
    pins: ClassVar[tuple[int, ...]] = tuple(range(6, 14))
    bits: ClassVar[tuple[int, ...]] = tuple(range(8))

    def __post_init__(self) -> None:
        block = _require_gpio_block(self.raw_block)
        packed = np.frombuffer(
            block.payload_view,
            dtype=_GPIO_BYTE_DTYPE,
            count=block.item_count,
        )
        object.__setattr__(self, "packed", _readonly(packed))

    @property
    def bytes(self) -> Any:
        return self.packed

    @property
    def payload_owner(self) -> builtins.bytes:
        return self.raw_block.payload

    @property
    def run_id(self) -> int:
        return self.raw_block.run_id

    @property
    def sequence(self) -> int:
        return self.raw_block.sequence

    @property
    def t0_ticks(self) -> int:
        return self.raw_block.t0_ticks

    @property
    def timestamp_hz(self) -> int:
        return self.raw_block.timestamp_hz

    @property
    def sample_period_ticks(self) -> int:
        return self.raw_block.sample_period_ticks

    @property
    def item_count(self) -> int:
        return self.raw_block.item_count

    @property
    def source(self) -> Any:
        return self.raw_block.source

    def timestamps(self) -> Any:
        """Vectorize the nominal tick for each packed simultaneous sample."""

        return _gpio_timestamps(self.raw_block)

    def channel(self, pin: int) -> GPIOChannelArray:
        """Explicitly allocate one selected pin's Boolean sample vector."""

        channel = self.raw_block.channel(pin)
        values = np.not_equal(
            np.bitwise_and(self.packed, np.uint8(1 << channel.bit)),
            0,
        )
        return GPIOChannelArray(
            raw_view=self,
            pin=channel.pin,
            bit=channel.bit,
            values=_readonly(values),
        )

    def channels(self, pins: Iterable[int]) -> GPIOChannelsArray:
        """Explicitly allocate Boolean columns for exactly the requested pins."""

        try:
            selected_pins = tuple(pins)
        except TypeError as exc:
            raise TypeError("pins must be an iterable of D6 through D13 pins") from exc
        if not selected_pins:
            raise ValueError("at least one GPIO pin must be selected")
        if len(set(selected_pins)) != len(selected_pins):
            raise ValueError("GPIO pin selections must be unique")
        channel_views = tuple(self.raw_block.channel(pin) for pin in selected_pins)
        selected_bits = tuple(channel.bit for channel in channel_views)
        masks = np.asarray(
            tuple(1 << bit for bit in selected_bits),
            dtype=_GPIO_BYTE_DTYPE,
        )
        values = np.not_equal(
            np.bitwise_and(self.packed[:, np.newaxis], masks[np.newaxis, :]),
            0,
        )
        return GPIOChannelsArray(
            raw_view=self,
            pins=selected_pins,
            bits=selected_bits,
            values=_readonly(values),
        )


@dataclass(frozen=True, slots=True, eq=False)
class GPIOChannelArray:
    """One explicitly selected Boolean GPIO vector with pin/bit identity."""

    raw_view: GPIOArrayView
    pin: int
    bit: int
    values: Any

    calibrated: ClassVar[bool] = False
    units: ClassVar[str] = "bool"

    def __post_init__(self) -> None:
        if not isinstance(self.raw_view, GPIOArrayView):
            raise TypeError("raw_view must be a GPIOArrayView")
        channel = self.raw_view.raw_block.channel(self.pin)
        if channel.bit != self.bit:
            raise ValueError("pin and bit do not describe the same GPIO channel")
        expected_shape = (self.raw_view.raw_block.item_count,)
        if (
            not isinstance(self.values, np.ndarray)
            or self.values.shape != expected_shape
            or self.values.dtype != np.dtype("bool")
        ):
            raise TypeError("values must be a Boolean selected-channel vector")
        _readonly(self.values)

    @property
    def raw_block(self) -> GPIOBlock:
        return self.raw_view.raw_block

    @property
    def raw_bytes(self) -> Any:
        return self.raw_view.packed

    def timestamps(self) -> Any:
        return self.raw_view.timestamps()


@dataclass(frozen=True, slots=True, eq=False)
class GPIOChannelsArray:
    """Explicit Boolean matrix for caller-selected GPIO pins only."""

    raw_view: GPIOArrayView
    pins: tuple[int, ...]
    bits: tuple[int, ...]
    values: Any

    calibrated: ClassVar[bool] = False
    units: ClassVar[str] = "bool"

    def __post_init__(self) -> None:
        if not isinstance(self.raw_view, GPIOArrayView):
            raise TypeError("raw_view must be a GPIOArrayView")
        if len(self.pins) != len(self.bits) or not self.pins:
            raise ValueError("pins and bits must describe selected GPIO channels")
        expected_shape = (self.raw_view.raw_block.item_count, len(self.pins))
        if (
            not isinstance(self.values, np.ndarray)
            or self.values.shape != expected_shape
            or self.values.dtype != np.dtype("bool")
        ):
            raise TypeError("values must be a Boolean selected-channel matrix")
        _readonly(self.values)

    @property
    def raw_block(self) -> GPIOBlock:
        return self.raw_view.raw_block

    @property
    def raw_bytes(self) -> Any:
        return self.raw_view.packed

    def timestamps(self) -> Any:
        return self.raw_view.timestamps()

    def for_pin(self, pin: int) -> Any:
        """Return one existing matrix column without another Boolean expansion."""

        if not isinstance(pin, int) or isinstance(pin, bool):
            raise TypeError("GPIO pin must be one of the selected pins")
        try:
            column = self.pins.index(pin)
        except ValueError as exc:
            raise ValueError("GPIO pin was not selected") from exc
        return self.values[:, column]


def adc_view(block: ADCBlock) -> ADCArrayView:
    """Return the optional zero-copy NumPy view for an ADC block."""

    return ADCArrayView(block)


def gpio_view(block: GPIOBlock) -> GPIOArrayView:
    """Return the optional zero-copy NumPy view for a GPIO block."""

    return GPIOArrayView(block)


def adc_pairs(block: ADCBlock) -> Any:
    """Return a read-only zero-copy little-endian ADC pair array."""

    return adc_view(block).pairs


def gpio_bytes(block: GPIOBlock) -> Any:
    """Return a read-only zero-copy packed GPIO-byte array."""

    return gpio_view(block).packed


def adc_timestamps(block: ADCBlock, *, interleaved: bool = False) -> Any:
    """Vectorize nominal ADC ticks as pair columns or explicit sample order."""

    if not isinstance(interleaved, bool):
        raise TypeError("interleaved must be a bool")
    timestamps = adc_view(block).timestamp_pairs()
    return _readonly(timestamps.reshape(-1)) if interleaved else timestamps


def gpio_timestamps(block: GPIOBlock) -> Any:
    """Vectorize nominal ticks for packed GPIO snapshots."""

    return gpio_view(block).timestamps()


def interleave_adc(block: ADCBlock) -> ADCInterleavedArray:
    """Vectorize explicit ADC0/ADC1 interleaving without a bandwidth claim."""

    return adc_view(block).interleaved()


def calibrate_adc(
    block: ADCBlock,
    calibration: CalibrationRecord,
    *,
    hardware_serial: int | None = None,
    analog_front_end_profile: str | None = None,
) -> CalibratedADCArray:
    """Vectorize opt-in calibration while retaining raw pairs and metadata."""

    return adc_view(block).calibrated_array(
        calibration,
        hardware_serial=hardware_serial,
        analog_front_end_profile=analog_front_end_profile,
    )


def extract_gpio_channels(block: GPIOBlock, pins: Iterable[int]) -> GPIOChannelsArray:
    """Vectorize only the explicitly selected GPIO pin columns."""

    return gpio_view(block).channels(pins)


def extract_gpio_channel(block: GPIOBlock, pin: int) -> GPIOChannelArray:
    """Vectorize one explicitly selected GPIO pin as a Boolean vector."""

    return gpio_view(block).channel(pin)


__all__ = [
    "ADCArrayView",
    "ADCInterleavedArray",
    "CalibratedADCArray",
    "GPIOArrayView",
    "GPIOChannelArray",
    "GPIOChannelsArray",
    "adc_pairs",
    "adc_timestamps",
    "adc_view",
    "calibrate_adc",
    "extract_gpio_channel",
    "extract_gpio_channels",
    "gpio_bytes",
    "gpio_timestamps",
    "gpio_view",
    "interleave_adc",
]
