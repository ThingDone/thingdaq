"""Versioned, opt-in host calibration without modifying raw ADC samples."""

from __future__ import annotations

import json
import math
import os
import tempfile
from collections.abc import Iterable, Iterator, Sequence
from dataclasses import dataclass, replace
from datetime import datetime, timezone
from numbers import Real
from pathlib import Path
from typing import TYPE_CHECKING, Any, ClassVar, overload

from ._generated import protocol_constants as constants

if TYPE_CHECKING:
    from .models import ADCBlock, AdcChannelView, AdcConverter

CALIBRATION_SCHEMA_VERSION = 1
CALIBRATION_FILE_FORMAT = "teensy-daq-host-calibration"
MAX_CALIBRATION_FILE_BYTES = 1 << 20
_RECORD_FIELDS = frozenset(
    {
        "schema_version",
        "hardware_serial",
        "analog_front_end_profile",
        "adc_resolution_bits",
        "adc_code_range",
        "adc_input_range_volts",
        "adc0",
        "adc1",
        "residual_timing_skew_seconds",
        "provenance",
        "created_at",
        "notes",
    }
)


class CalibrationError(ValueError):
    """Base error for invalid or incompatible host calibration data."""


class CalibrationFormatError(CalibrationError):
    """A calibration document is malformed or uses an unsupported schema."""


class CalibrationMismatchError(CalibrationError):
    """A valid record does not describe the selected device/profile/format."""


def _finite_number(name: str, value: object) -> float:
    if isinstance(value, bool) or not isinstance(value, Real):
        raise CalibrationFormatError(f"{name} must be a finite number")
    result = float(value)
    if not math.isfinite(result):
        raise CalibrationFormatError(f"{name} must be a finite number")
    return result


def _profile(value: object) -> str | None:
    if value is None:
        return None
    if not isinstance(value, str):
        raise CalibrationFormatError(
            "analog_front_end_profile must be a string or null"
        )
    if not value or value != value.strip() or len(value) > 128:
        raise CalibrationFormatError(
            "analog_front_end_profile must be 1-128 trimmed characters"
        )
    if any(ord(character) < 0x20 for character in value):
        raise CalibrationFormatError(
            "analog_front_end_profile cannot contain control characters"
        )
    return value


def _text(name: str, value: object, *, required: bool) -> str:
    if not isinstance(value, str):
        raise CalibrationFormatError(f"{name} must be a string")
    if "\x00" in value:
        raise CalibrationFormatError(f"{name} cannot contain NUL")
    if required and not value.strip():
        raise CalibrationFormatError(f"{name} must not be empty")
    return value


@dataclass(frozen=True, slots=True)
class CalibrationKey:
    """Stable key for one device and optional external analog-front-end profile."""

    hardware_serial: int
    analog_front_end_profile: str | None = None

    def __post_init__(self) -> None:
        if (
            not isinstance(self.hardware_serial, int)
            or isinstance(self.hardware_serial, bool)
            or not 0 < self.hardware_serial <= constants.UINT32_MAX
        ):
            raise CalibrationFormatError(
                "hardware_serial must be a nonzero unsigned 32-bit integer"
            )
        object.__setattr__(
            self,
            "analog_front_end_profile",
            _profile(self.analog_front_end_profile),
        )


@dataclass(frozen=True, slots=True)
class ConverterCalibration:
    """Affine conversion from a raw ADC code to calibrated pin volts.

    The correction is ``volts = gain * raw_code + offset``.
    """

    offset: float
    gain: float

    def __post_init__(self) -> None:
        offset = _finite_number("offset", self.offset)
        gain = _finite_number("gain", self.gain)
        if gain <= 0.0:
            raise CalibrationFormatError("gain must be greater than zero")
        object.__setattr__(self, "offset", offset)
        object.__setattr__(self, "gain", gain)

    @property
    def offset_volts(self) -> float:
        return self.offset

    @property
    def gain_volts_per_code(self) -> float:
        return self.gain

    def to_dict(self) -> dict[str, float]:
        return {"offset": self.offset, "gain": self.gain}

    @classmethod
    def from_dict(cls, value: object) -> ConverterCalibration:
        data = _mapping("converter calibration", value, {"offset", "gain"})
        return cls(offset=data["offset"], gain=data["gain"])


@dataclass(frozen=True, slots=True)
class CalibrationRecord:
    """Immutable per-device, per-profile host calibration record."""

    hardware_serial: int
    adc_resolution_bits: int
    adc_code_range: tuple[int, int]
    adc_input_range_volts: tuple[float, float]
    adc0: ConverterCalibration
    adc1: ConverterCalibration
    provenance: str
    created_at: datetime
    analog_front_end_profile: str | None = None
    residual_timing_skew_seconds: float | None = None
    notes: str = ""
    schema_version: int = CALIBRATION_SCHEMA_VERSION

    def __post_init__(self) -> None:
        key = CalibrationKey(
            self.hardware_serial,
            self.analog_front_end_profile,
        )
        if (
            type(self.schema_version) is not int
            or self.schema_version != CALIBRATION_SCHEMA_VERSION
        ):
            raise CalibrationFormatError(
                f"unsupported calibration schema version {self.schema_version!r}"
            )
        if type(
            self.adc_resolution_bits
        ) is not int or self.adc_resolution_bits not in (
            constants.ADC_PRIMARY_RESOLUTION_BITS,
            constants.ADC_FALLBACK_RESOLUTION_BITS,
        ):
            raise CalibrationFormatError("adc_resolution_bits must be 10 or 12")
        code_range = tuple(self.adc_code_range)
        expected_code_range = (0, (1 << self.adc_resolution_bits) - 1)
        if any(type(item) is not int for item in code_range) or (
            code_range != expected_code_range
        ):
            raise CalibrationFormatError(
                "adc_code_range must cover the complete selected resolution"
            )
        voltage_range = tuple(
            _finite_number("adc_input_range_volts", item)
            for item in self.adc_input_range_volts
        )
        if len(voltage_range) != 2 or voltage_range[0] >= voltage_range[1]:
            raise CalibrationFormatError(
                "adc_input_range_volts must contain increasing low/high values"
            )
        if not isinstance(self.adc0, ConverterCalibration) or not isinstance(
            self.adc1, ConverterCalibration
        ):
            raise CalibrationFormatError(
                "adc0 and adc1 must be ConverterCalibration values"
            )
        skew = self.residual_timing_skew_seconds
        if skew is not None:
            skew = _finite_number("residual_timing_skew_seconds", skew)
        if (
            not isinstance(self.created_at, datetime)
            or self.created_at.tzinfo is None
            or self.created_at.utcoffset() is None
        ):
            raise CalibrationFormatError("created_at must be timezone-aware")
        created_at = self.created_at.astimezone(timezone.utc)
        object.__setattr__(self, "hardware_serial", key.hardware_serial)
        object.__setattr__(
            self, "analog_front_end_profile", key.analog_front_end_profile
        )
        object.__setattr__(self, "adc_code_range", code_range)
        object.__setattr__(self, "adc_input_range_volts", voltage_range)
        object.__setattr__(self, "residual_timing_skew_seconds", skew)
        object.__setattr__(
            self, "provenance", _text("provenance", self.provenance, required=True)
        )
        object.__setattr__(self, "notes", _text("notes", self.notes, required=False))
        object.__setattr__(self, "created_at", created_at)

    @property
    def key(self) -> CalibrationKey:
        return CalibrationKey(
            self.hardware_serial,
            self.analog_front_end_profile,
        )

    @property
    def profile(self) -> str | None:
        return self.analog_front_end_profile

    @property
    def resolution_bits(self) -> int:
        return self.adc_resolution_bits

    @property
    def code_range(self) -> tuple[int, int]:
        return self.adc_code_range

    @property
    def input_range_volts(self) -> tuple[float, float]:
        return self.adc_input_range_volts

    @property
    def adc0_offset(self) -> float:
        return self.adc0.offset

    @property
    def adc0_gain(self) -> float:
        return self.adc0.gain

    @property
    def adc1_offset(self) -> float:
        return self.adc1.offset

    @property
    def adc1_gain(self) -> float:
        return self.adc1.gain

    @property
    def converter_calibrations(
        self,
    ) -> tuple[ConverterCalibration, ConverterCalibration]:
        return self.adc0, self.adc1

    def converter(self, converter: AdcConverter | int) -> ConverterCalibration:
        from .models import AdcConverter

        if isinstance(converter, bool):
            raise TypeError("converter must be ADC0 or ADC1")
        try:
            selected = AdcConverter(converter)
        except (TypeError, ValueError) as exc:
            raise ValueError("converter must be ADC0 or ADC1") from exc
        return self.converter_calibrations[int(selected)]

    def require_compatible(
        self,
        *,
        hardware_serial: int,
        analog_front_end_profile: str | None,
        adc_resolution_bits: int,
        adc_code_range: tuple[int, int],
        adc_input_range_volts: tuple[float, float],
    ) -> None:
        """Raise before use unless all identity and ADC format fields match."""

        requested_key = CalibrationKey(hardware_serial, analog_front_end_profile)
        if requested_key != self.key:
            raise CalibrationMismatchError(
                f"calibration key {self.key!r} does not match {requested_key!r}"
            )
        if adc_resolution_bits != self.adc_resolution_bits:
            raise CalibrationMismatchError(
                "calibration ADC resolution does not match the data block"
            )
        if tuple(adc_code_range) != self.adc_code_range:
            raise CalibrationMismatchError(
                "calibration ADC code range does not match the data block"
            )
        observed_voltage_range = tuple(float(item) for item in adc_input_range_volts)
        if observed_voltage_range != self.adc_input_range_volts:
            raise CalibrationMismatchError(
                "calibration ADC input range does not match the data block"
            )

    validate_compatibility = require_compatible

    def to_dict(self) -> dict[str, object]:
        return {
            "schema_version": self.schema_version,
            "hardware_serial": self.hardware_serial,
            "analog_front_end_profile": self.analog_front_end_profile,
            "adc_resolution_bits": self.adc_resolution_bits,
            "adc_code_range": list(self.adc_code_range),
            "adc_input_range_volts": list(self.adc_input_range_volts),
            "adc0": self.adc0.to_dict(),
            "adc1": self.adc1.to_dict(),
            "residual_timing_skew_seconds": self.residual_timing_skew_seconds,
            "provenance": self.provenance,
            "created_at": self.created_at.isoformat().replace("+00:00", "Z"),
            "notes": self.notes,
        }

    @classmethod
    def from_dict(cls, value: object) -> CalibrationRecord:
        data = _mapping("calibration record", value, _RECORD_FIELDS)
        created_at = data["created_at"]
        if not isinstance(created_at, str):
            raise CalibrationFormatError("created_at must be an RFC 3339 string")
        try:
            parsed_time = datetime.fromisoformat(created_at.replace("Z", "+00:00"))
        except ValueError as exc:
            raise CalibrationFormatError(
                "created_at must be an RFC 3339 string"
            ) from exc
        return cls(
            hardware_serial=data["hardware_serial"],
            analog_front_end_profile=data["analog_front_end_profile"],
            adc_resolution_bits=data["adc_resolution_bits"],
            adc_code_range=_pair("adc_code_range", data["adc_code_range"]),
            adc_input_range_volts=_pair(
                "adc_input_range_volts", data["adc_input_range_volts"]
            ),
            adc0=ConverterCalibration.from_dict(data["adc0"]),
            adc1=ConverterCalibration.from_dict(data["adc1"]),
            residual_timing_skew_seconds=data["residual_timing_skew_seconds"],
            provenance=data["provenance"],
            created_at=parsed_time,
            notes=data["notes"],
            schema_version=data["schema_version"],
        )


@dataclass(frozen=True, slots=True)
class CalibrationDatabase:
    """Immutable collection serialized in one explicitly selected JSON file."""

    records: tuple[CalibrationRecord, ...] = ()
    schema_version: int = CALIBRATION_SCHEMA_VERSION

    def __post_init__(self) -> None:
        if (
            type(self.schema_version) is not int
            or self.schema_version != CALIBRATION_SCHEMA_VERSION
        ):
            raise CalibrationFormatError(
                f"unsupported calibration database schema {self.schema_version!r}"
            )
        records = tuple(self.records)
        if any(not isinstance(record, CalibrationRecord) for record in records):
            raise CalibrationFormatError("records must be CalibrationRecord values")
        keys = tuple(record.key for record in records)
        if len(set(keys)) != len(keys):
            raise CalibrationFormatError("calibration keys must be unique")
        object.__setattr__(self, "records", records)

    def select(
        self,
        hardware_serial: int,
        analog_front_end_profile: str | None = None,
    ) -> CalibrationRecord:
        key = CalibrationKey(hardware_serial, analog_front_end_profile)
        for record in self.records:
            if record.key == key:
                return record
        raise CalibrationMismatchError(f"no calibration record for {key!r}")

    def with_record(self, record: CalibrationRecord) -> CalibrationDatabase:
        if not isinstance(record, CalibrationRecord):
            raise TypeError("record must be a CalibrationRecord")
        retained = tuple(item for item in self.records if item.key != record.key)
        return replace(self, records=(*retained, record))

    def to_dict(self) -> dict[str, object]:
        return {
            "format": CALIBRATION_FILE_FORMAT,
            "schema_version": self.schema_version,
            "records": [record.to_dict() for record in self.records],
        }

    @classmethod
    def from_dict(cls, value: object) -> CalibrationDatabase:
        data = _mapping(
            "calibration database", value, {"format", "schema_version", "records"}
        )
        if data["format"] != CALIBRATION_FILE_FORMAT:
            raise CalibrationFormatError("unrecognized calibration file format")
        records = data["records"]
        if not isinstance(records, list):
            raise CalibrationFormatError("records must be a JSON array")
        return cls(
            records=tuple(CalibrationRecord.from_dict(item) for item in records),
            schema_version=data["schema_version"],
        )


class CalibrationStore:
    """JSON persistence bound to an explicit path; no implicit path is used."""

    __slots__ = ("path",)

    def __init__(self, path: str | os.PathLike[str]) -> None:
        if not isinstance(path, (str, os.PathLike)) or not os.fspath(path):
            raise TypeError("calibration path must be explicitly selected")
        self.path = Path(path)

    def read(self) -> CalibrationDatabase:
        return calibration_database_from_json(_read_text(self.path))

    def write(self, database: CalibrationDatabase) -> None:
        if not isinstance(database, CalibrationDatabase):
            raise TypeError("database must be a CalibrationDatabase")
        _atomic_write(self.path, calibration_database_to_json(database))

    def save(self, record: CalibrationRecord) -> None:
        database = self.read() if self.path.exists() else CalibrationDatabase()
        self.write(database.with_record(record))

    def load(
        self,
        hardware_serial: int,
        analog_front_end_profile: str | None = None,
        *,
        adc_resolution_bits: int | None = None,
        adc_code_range: tuple[int, int] | None = None,
        adc_input_range_volts: tuple[float, float] | None = None,
    ) -> CalibrationRecord:
        record = self.read().select(hardware_serial, analog_front_end_profile)
        if (
            adc_resolution_bits is not None
            and adc_resolution_bits != record.adc_resolution_bits
        ):
            raise CalibrationMismatchError(
                "calibration ADC resolution does not match the requested format"
            )
        if (
            adc_code_range is not None
            and tuple(adc_code_range) != record.adc_code_range
        ):
            raise CalibrationMismatchError(
                "calibration ADC code range does not match the requested format"
            )
        if (
            adc_input_range_volts is not None
            and tuple(float(item) for item in adc_input_range_volts)
            != record.adc_input_range_volts
        ):
            raise CalibrationMismatchError(
                "calibration ADC input range does not match the requested format"
            )
        return record


def estimate_offset_gain(
    low_capture: Iterable[float],
    high_capture: Iterable[float],
    expected_low_volts: float,
    expected_high_volts: float,
) -> ConverterCalibration:
    """Fit ``volts = gain * code + offset`` to two supplied capture means."""

    low_mean = _capture_mean("low_capture", low_capture)
    high_mean = _capture_mean("high_capture", high_capture)
    low_volts = _finite_number("expected_low_volts", expected_low_volts)
    high_volts = _finite_number("expected_high_volts", expected_high_volts)
    if high_mean <= low_mean:
        raise CalibrationError("high capture mean must exceed low capture mean")
    if high_volts <= low_volts:
        raise CalibrationError("expected high voltage must exceed low voltage")
    gain = (high_volts - low_volts) / (high_mean - low_mean)
    return ConverterCalibration(offset=low_volts - gain * low_mean, gain=gain)


def apply_correction(raw_code: float, calibration: ConverterCalibration) -> float:
    """Apply one immutable affine correction without clamping the result."""

    if not isinstance(calibration, ConverterCalibration):
        raise TypeError("calibration must be a ConverterCalibration")
    code = _finite_number("raw_code", raw_code)
    return calibration.gain * code + calibration.offset


def apply_corrections(
    raw_codes: Iterable[float], calibration: ConverterCalibration
) -> tuple[float, ...]:
    """Return calibrated volts for supplied raw codes without mutating input."""

    return tuple(apply_correction(code, calibration) for code in raw_codes)


class CalibratedAdcChannelView(Sequence[float]):
    """Lazy volts view retaining the corresponding untouched raw-code view."""

    __slots__ = ("calibration", "raw")
    calibrated: ClassVar[bool] = True
    units: ClassVar[str] = "V"

    def __init__(self, raw: AdcChannelView, calibration: ConverterCalibration) -> None:
        self.raw = raw
        self.calibration = calibration

    def __len__(self) -> int:
        return len(self.raw)

    @property
    def converter(self) -> AdcConverter:
        return self.raw.converter

    @property
    def pin(self) -> str:
        return self.converter.pin

    @overload
    def __getitem__(self, index: int) -> float: ...

    @overload
    def __getitem__(self, index: slice) -> tuple[float, ...]: ...

    def __getitem__(self, index: int | slice) -> float | tuple[float, ...]:
        if isinstance(index, slice):
            return tuple(
                self[position] for position in range(*index.indices(len(self)))
            )
        return apply_correction(self.raw[index], self.calibration)


@dataclass(frozen=True, slots=True)
class CalibratedAdcChannels:
    """Opt-in calibrated channel views plus their source block and record."""

    adc0: CalibratedAdcChannelView
    adc1: CalibratedAdcChannelView
    raw_block: ADCBlock
    calibration_record: CalibrationRecord
    calibrated: ClassVar[bool] = True
    units: ClassVar[str] = "V"
    timing_skew_applied: ClassVar[bool] = False

    def __post_init__(self) -> None:
        from .models import ADCBlock, AdcConverter

        if not isinstance(self.adc0, CalibratedAdcChannelView) or not isinstance(
            self.adc1, CalibratedAdcChannelView
        ):
            raise TypeError("adc0 and adc1 must be calibrated channel views")
        if self.adc0.converter is not AdcConverter.ADC0 or (
            self.adc1.converter is not AdcConverter.ADC1
        ):
            raise ValueError("calibrated channel views are in the wrong order")
        if not isinstance(self.raw_block, ADCBlock):
            raise TypeError("raw_block must be an ADCBlock")
        if not isinstance(self.calibration_record, CalibrationRecord):
            raise TypeError("calibration_record must be a CalibrationRecord")

    @property
    def raw_adc0(self) -> AdcChannelView:
        return self.adc0.raw

    @property
    def raw_adc1(self) -> AdcChannelView:
        return self.adc1.raw


@dataclass(frozen=True, slots=True)
class CalibratedAdcSample:
    """One calibrated voltage retaining raw code, converter, and nominal time."""

    pair_index: int
    converter: AdcConverter
    raw_code: int
    voltage: float
    timestamp_ticks: int
    calibrated: ClassVar[bool] = True
    units: ClassVar[str] = "V"
    timing_skew_applied: ClassVar[bool] = False

    def __post_init__(self) -> None:
        from .models import AdcConverter

        if (
            not isinstance(self.pair_index, int)
            or isinstance(self.pair_index, bool)
            or self.pair_index < 0
        ):
            raise ValueError("pair_index must be a nonnegative integer")
        if not isinstance(self.converter, AdcConverter):
            raise TypeError("converter must retain an ADC0 or ADC1 identity")
        if (
            not isinstance(self.raw_code, int)
            or isinstance(self.raw_code, bool)
            or not 0 <= self.raw_code <= 0xFFFF
        ):
            raise ValueError("raw_code must be an unsigned 16-bit integer")
        object.__setattr__(self, "voltage", _finite_number("voltage", self.voltage))
        if (
            not isinstance(self.timestamp_ticks, int)
            or isinstance(self.timestamp_ticks, bool)
            or not 0 <= self.timestamp_ticks <= constants.UINT64_MAX
        ):
            raise ValueError("timestamp_ticks must be an unsigned 64-bit integer")

    @property
    def value(self) -> float:
        return self.voltage

    @property
    def pin(self) -> str:
        return self.converter.pin

    @property
    def timestamp_seconds(self) -> float:
        return self.timestamp_ticks / constants.TIMESTAMP_HZ


def calibrated_channels(
    block: ADCBlock,
    calibration: CalibrationRecord,
    *,
    hardware_serial: int | None = None,
    analog_front_end_profile: str | None = None,
) -> CalibratedAdcChannels:
    """Create lazy calibrated views only after exact compatibility checks."""

    from .models import ADCBlock

    if not isinstance(block, ADCBlock):
        raise TypeError("block must be an ADCBlock")
    if not isinstance(calibration, CalibrationRecord):
        raise TypeError("calibration must be a CalibrationRecord")
    metadata_serial = block.metadata.hardware_serial
    selected_serial = metadata_serial if hardware_serial is None else hardware_serial
    if not selected_serial:
        raise CalibrationMismatchError(
            "ADC block has no hardware serial; pass hardware_serial explicitly"
        )
    if metadata_serial and selected_serial != metadata_serial:
        raise CalibrationMismatchError(
            "explicit hardware serial contradicts ADC block metadata"
        )
    input_range = (
        constants.ADC_INPUT_MIN_MV_NOMINAL / 1000.0,
        constants.ADC_INPUT_MAX_MV_NOMINAL / 1000.0,
    )
    calibration.require_compatible(
        hardware_serial=selected_serial,
        analog_front_end_profile=analog_front_end_profile,
        adc_resolution_bits=block.resolution_bits,
        adc_code_range=block.code_range,
        adc_input_range_volts=input_range,
    )
    return CalibratedAdcChannels(
        adc0=CalibratedAdcChannelView(block.adc0, calibration.adc0),
        adc1=CalibratedAdcChannelView(block.adc1, calibration.adc1),
        raw_block=block,
        calibration_record=calibration,
    )


def calibrated_interleaved(
    block: ADCBlock,
    calibration: CalibrationRecord,
    *,
    hardware_serial: int | None = None,
    analog_front_end_profile: str | None = None,
) -> Iterator[CalibratedAdcSample]:
    """Lazily interleave calibrated volts while preserving every raw code."""

    channels = calibrated_channels(
        block,
        calibration,
        hardware_serial=hardware_serial,
        analog_front_end_profile=analog_front_end_profile,
    )

    def samples() -> Iterator[CalibratedAdcSample]:
        from .models import AdcConverter

        for pair_index in range(block.item_count):
            adc0_tick, adc1_tick = block.pair_ticks(pair_index)
            yield CalibratedAdcSample(
                pair_index,
                AdcConverter.ADC0,
                block.adc0[pair_index],
                channels.adc0[pair_index],
                adc0_tick,
            )
            yield CalibratedAdcSample(
                pair_index,
                AdcConverter.ADC1,
                block.adc1[pair_index],
                channels.adc1[pair_index],
                adc1_tick,
            )

    return samples()


def calibration_database_to_json(database: CalibrationDatabase) -> str:
    if not isinstance(database, CalibrationDatabase):
        raise TypeError("database must be a CalibrationDatabase")
    return (
        json.dumps(
            database.to_dict(),
            allow_nan=False,
            ensure_ascii=False,
            indent=2,
            sort_keys=True,
        )
        + "\n"
    )


def calibration_database_from_json(text: str) -> CalibrationDatabase:
    if not isinstance(text, str):
        raise TypeError("calibration JSON must be text")
    try:
        value = json.loads(
            text,
            object_pairs_hook=_unique_object,
            parse_constant=_reject_json_constant,
        )
    except (json.JSONDecodeError, UnicodeError) as exc:
        raise CalibrationFormatError(f"invalid calibration JSON: {exc}") from exc
    return CalibrationDatabase.from_dict(value)


def save_calibration(path: str | os.PathLike[str], record: CalibrationRecord) -> None:
    """Atomically add or replace one keyed record at an explicit path."""

    CalibrationStore(path).save(record)


def load_calibration(
    path: str | os.PathLike[str],
    hardware_serial: int,
    analog_front_end_profile: str | None = None,
    *,
    adc_resolution_bits: int | None = None,
    adc_code_range: tuple[int, int] | None = None,
    adc_input_range_volts: tuple[float, float] | None = None,
) -> CalibrationRecord:
    """Load one exact device/profile record from an explicit path."""

    return CalibrationStore(path).load(
        hardware_serial,
        analog_front_end_profile,
        adc_resolution_bits=adc_resolution_bits,
        adc_code_range=adc_code_range,
        adc_input_range_volts=adc_input_range_volts,
    )


def _capture_mean(name: str, values: Iterable[float]) -> float:
    if isinstance(values, (str, bytes, bytearray)):
        raise CalibrationError(f"{name} must be an iterable of numeric samples")
    samples = tuple(_finite_number(name, value) for value in values)
    if not samples:
        raise CalibrationError(f"{name} must contain at least one sample")
    return math.fsum(samples) / len(samples)


def _pair(name: str, value: object) -> tuple[Any, Any]:
    if not isinstance(value, (list, tuple)) or len(value) != 2:
        raise CalibrationFormatError(f"{name} must contain exactly two values")
    return value[0], value[1]


def _mapping(
    name: str, value: object, fields: set[str] | frozenset[str]
) -> dict[str, Any]:
    if not isinstance(value, dict):
        raise CalibrationFormatError(f"{name} must be a JSON object")
    actual = set(value)
    if actual != fields:
        missing = sorted(fields - actual)
        unknown = sorted(actual - fields)
        raise CalibrationFormatError(
            f"{name} fields differ (missing={missing}, unknown={unknown})"
        )
    return value


def _unique_object(pairs: list[tuple[str, Any]]) -> dict[str, Any]:
    result: dict[str, Any] = {}
    for key, value in pairs:
        if key in result:
            raise CalibrationFormatError(f"duplicate JSON field {key!r}")
        result[key] = value
    return result


def _reject_json_constant(value: str) -> None:
    raise CalibrationFormatError(f"non-finite JSON number {value!r} is forbidden")


def _read_text(path: Path) -> str:
    if path.is_symlink():
        raise CalibrationFormatError("calibration path must not be a symbolic link")
    with path.open("rb") as handle:
        contents = handle.read(MAX_CALIBRATION_FILE_BYTES + 1)
    if len(contents) > MAX_CALIBRATION_FILE_BYTES:
        raise CalibrationFormatError("calibration file exceeds the 1 MiB limit")
    try:
        return contents.decode("utf-8")
    except UnicodeDecodeError as exc:
        raise CalibrationFormatError("calibration file is not valid UTF-8") from exc


def _atomic_write(path: Path, contents: str) -> None:
    if path.is_symlink():
        raise CalibrationFormatError("calibration path must not be a symbolic link")
    if len(contents.encode("utf-8")) > MAX_CALIBRATION_FILE_BYTES:
        raise CalibrationFormatError("calibration file exceeds the 1 MiB limit")
    parent = path.parent
    if not parent.is_dir():
        raise FileNotFoundError(
            f"calibration parent directory does not exist: {parent}"
        )
    descriptor, temporary_name = tempfile.mkstemp(
        dir=parent,
        prefix=f".{path.name}.",
        suffix=".tmp",
        text=True,
    )
    temporary_path = Path(temporary_name)
    try:
        with os.fdopen(descriptor, "w", encoding="utf-8", newline="\n") as handle:
            handle.write(contents)
            handle.flush()
            os.fsync(handle.fileno())
        os.replace(temporary_path, path)
    finally:
        try:
            temporary_path.unlink()
        except FileNotFoundError:
            pass


__all__ = [
    "CALIBRATION_FILE_FORMAT",
    "CALIBRATION_SCHEMA_VERSION",
    "MAX_CALIBRATION_FILE_BYTES",
    "CalibratedAdcChannelView",
    "CalibratedAdcChannels",
    "CalibratedAdcSample",
    "CalibrationDatabase",
    "CalibrationError",
    "CalibrationFormatError",
    "CalibrationKey",
    "CalibrationMismatchError",
    "CalibrationRecord",
    "CalibrationStore",
    "ConverterCalibration",
    "apply_correction",
    "apply_corrections",
    "calibrated_channels",
    "calibrated_interleaved",
    "calibration_database_from_json",
    "calibration_database_to_json",
    "estimate_offset_gain",
    "load_calibration",
    "save_calibration",
]
