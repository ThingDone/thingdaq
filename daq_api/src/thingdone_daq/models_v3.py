"""Typed public-v3 control records and correlated command/response codecs."""

from __future__ import annotations

import struct
from dataclasses import dataclass, fields

from ._generated import protocol_v3_constants as c
from ._incremental import BytesLike
from .protocol_v3 import (
    V3Frame,
    V3FrameValidationError,
    _bounded_bytes,
    _require,
    encode_v3_frame,
)

_SETTINGS = struct.Struct(c.SETTINGS_STRUCT_FORMAT)
_CLOCKS = struct.Struct(c.CPU_PROFILE_INFO_STRUCT_FORMAT)
_RATE = struct.Struct(c.RATE_PROFILE_INFO_STRUCT_FORMAT)
_OK = bytes(c.RESPONSE_PREFIX_PAYLOAD_SIZE)
_LIMITS = (
    c.MAX_DATA_FRAME_BYTES,
    c.MAX_CONTROL_FRAME_BYTES,
    c.MAX_LOGICAL_PAYLOAD_BYTES,
    c.MAX_ENCODED_SAMPLE_BYTES,
    c.MAX_ADC_PAIRS,
    c.MAX_GPIO8_SAMPLES,
    c.MAX_GPIO16_SAMPLES,
)


def _validate_limits(limits: tuple[int, ...]) -> None:
    for value, maximum in zip(limits, _LIMITS, strict=True):
        _require(
            isinstance(value, int)
            and not isinstance(value, bool)
            and 0 < value <= maximum,
            "advertised limit outside canonical bounds",
        )
    frame, control, logical, encoded, adc, gpio8, gpio16 = limits
    _require(
        control >= c.MIN_FRAME_BYTES + c.CAPABILITIES_RESPONSE_PAYLOAD_SIZE
        and frame >= c.MIN_FRAME_BYTES + c.DATA_PREFIX_BYTES + encoded
        and adc * 4 <= logical
        and gpio8 <= logical
        and gpio16 * 2 <= logical,
        "inconsistent device limits",
    )


def _pack(fmt: str, *values: int | bytes) -> bytes:
    try:
        return struct.pack(fmt, *values)
    except (struct.error, OverflowError) as exc:
        raise V3FrameValidationError("record scalar outside wire range") from exc


def _success(payload: BytesLike, size: int) -> bytes:
    data = _bounded_bytes(payload, size, size)
    _require(data[:4] == _OK, "expected successful response prefix")
    return data


@dataclass(frozen=True, slots=True)
class V3Settings:
    stream_mask: c.StreamMask
    source: c.Source
    checksum_algorithm: c.ChecksumAlgorithm
    wire_version: int
    cpu_profile: c.CpuProfile
    rate_profile: c.RateProfile
    aux_bank_mode: c.AuxBankMode
    gpio_width_bits: int
    gpio_policy: c.GpioPolicy
    adc_policy: c.AdcPolicy
    adc_resolution_bits: int
    adc_pair_rate_hz: int
    gpio_sample_rate_hz: int

    def __post_init__(self) -> None:
        for name, enum in (
            ("stream_mask", c.StreamMask),
            ("source", c.Source),
            ("checksum_algorithm", c.ChecksumAlgorithm),
            ("cpu_profile", c.CpuProfile),
            ("rate_profile", c.RateProfile),
            ("aux_bank_mode", c.AuxBankMode),
            ("gpio_policy", c.GpioPolicy),
            ("adc_policy", c.AdcPolicy),
        ):
            value = getattr(self, name)
            _require(
                isinstance(value, int) and not isinstance(value, bool),
                f"invalid {name}",
            )
            try:
                object.__setattr__(self, name, enum(value))
            except ValueError as exc:
                raise V3FrameValidationError(f"unknown {name}") from exc
        _require(1 <= int(self.stream_mask) <= 3, "invalid stream mask")
        for name in (
            "wire_version",
            "gpio_width_bits",
            "adc_resolution_bits",
            "adc_pair_rate_hz",
            "gpio_sample_rate_hz",
        ):
            value = getattr(self, name)
            _require(
                isinstance(value, int) and not isinstance(value, bool),
                f"invalid {name}",
            )
        self.to_bytes()

    def to_bytes(self) -> bytes:
        data = _pack(
            c.SETTINGS_STRUCT_FORMAT,
            self.stream_mask,
            self.source,
            self.checksum_algorithm,
            self.wire_version,
            self.cpu_profile,
            self.rate_profile,
            self.aux_bank_mode,
            self.gpio_width_bits,
            self.gpio_policy,
            self.adc_policy,
            self.adc_resolution_bits,
            0,
            self.adc_pair_rate_hz,
            self.gpio_sample_rate_hz,
        )
        if data not in c.SELECTABLE_CONFIGURATIONS:
            raise V3FrameValidationError(
                "unsupported settings tuple",
                error_code=c.ErrorCode.UNSUPPORTED_CONFIGURATION,
            )
        return data

    @classmethod
    def from_bytes(cls, payload: BytesLike) -> V3Settings:
        data = _bounded_bytes(payload, c.SETTINGS_PAYLOAD_SIZE, c.SETTINGS_PAYLOAD_SIZE)
        fields = _SETTINGS.unpack(data)
        _require(fields[11] == 0, "nonzero settings reserved byte")
        return cls(*fields[:11], *fields[12:])

    @classmethod
    def defaults(cls) -> V3Settings:
        return cls.from_bytes(c.DEFAULT_SETTINGS[0])


@dataclass(frozen=True, slots=True)
class V3Clocks:
    cpu_profile: c.CpuProfile
    cpu_clock_hz: int
    ipg_clock_hz: int
    adc_clock_hz: int
    pit_clock_hz: int
    timestamp_hz: int

    def to_bytes(self) -> bytes:
        data = _pack(
            c.CPU_PROFILE_INFO_STRUCT_FORMAT,
            self.cpu_profile,
            0,
            0,
            self.cpu_clock_hz,
            self.ipg_clock_hz,
            self.adc_clock_hz,
            self.pit_clock_hz,
            self.timestamp_hz,
        )
        _require(data in c.CPU_PROFILES, "unknown or contradictory CPU clocks")
        return data

    @classmethod
    def from_bytes(cls, payload: BytesLike) -> V3Clocks:
        data = _bounded_bytes(payload, _CLOCKS.size, _CLOCKS.size)
        _require(data in c.CPU_PROFILES, "unknown or contradictory CPU clock record")
        profile, _, _, *clocks = _CLOCKS.unpack(data)
        return cls(c.CpuProfile(profile), *clocks)

    @classmethod
    def for_profile(cls, profile: c.CpuProfile) -> V3Clocks:
        for data in c.CPU_PROFILES:
            if data[0] == profile:
                return cls.from_bytes(data)
        raise V3FrameValidationError("unknown CPU profile")


@dataclass(frozen=True, slots=True)
class V3Rate:
    rate_profile: c.RateProfile
    adc_pair_rate_hz: int
    gpio_sample_rate_hz: int
    adc_pair_period_ticks: int
    gpio_sample_period_ticks: int
    adc1_phase_ticks: int

    def to_bytes(self) -> bytes:
        data = _pack(
            c.RATE_PROFILE_INFO_STRUCT_FORMAT,
            self.rate_profile,
            0,
            0,
            self.adc_pair_rate_hz,
            self.gpio_sample_rate_hz,
            self.adc_pair_period_ticks,
            self.gpio_sample_period_ticks,
            self.adc1_phase_ticks,
            0,
        )
        _require(data in c.RATE_PROFILES, "unknown or contradictory rate")
        return data

    @classmethod
    def from_bytes(cls, payload: BytesLike) -> V3Rate:
        data = _bounded_bytes(payload, _RATE.size, _RATE.size)
        _require(data in c.RATE_PROFILES, "unknown or contradictory rate record")
        profile, _, _, adc, gpio, adc_ticks, gpio_ticks, phase, _ = _RATE.unpack(data)
        return cls(c.RateProfile(profile), adc, gpio, adc_ticks, gpio_ticks, phase)


@dataclass(frozen=True, slots=True)
class V3AppliedSettings:
    settings: V3Settings
    clocks: V3Clocks

    def to_payload(self) -> bytes:
        _require(
            self.settings.cpu_profile == self.clocks.cpu_profile,
            "settings/clock mismatch",
        )
        return _OK + self.settings.to_bytes() + self.clocks.to_bytes()

    @classmethod
    def from_payload(cls, payload: BytesLike) -> V3AppliedSettings:
        data = _success(payload, c.SETTINGS_RESPONSE_PAYLOAD_SIZE)
        result = cls(V3Settings.from_bytes(data[4:24]), V3Clocks.from_bytes(data[24:]))
        result.to_payload()
        return result


def _ascii_encode(value: str, size: int) -> bytes:
    _require(
        0 < len(value) < size and all(32 <= ord(ch) <= 126 for ch in value),
        "identity must be nonempty printable ASCII with room for terminator",
    )
    return value.encode("ascii").ljust(size, b"\0")


def _ascii_decode(data: bytes) -> str:
    text, separator, padding = data.partition(b"\0")
    _require(
        bool(text)
        and bool(separator)
        and not any(padding)
        and all(32 <= value <= 126 for value in text),
        "invalid NUL-padded identity",
    )
    return text.decode("ascii")


@dataclass(frozen=True, slots=True)
class V3Info:
    board_id: c.BoardId
    mcu_id: c.McuId
    simulated: bool
    hardware_serial: str
    firmware_version: str
    build_id: str
    clocks: V3Clocks
    protocol_version: int = c.PROTOCOL_VERSION
    adc_resolution_bits: int = 12

    def to_payload(self) -> bytes:
        _require(
            self.board_id == c.BoardId.TEENSY_40 and self.mcu_id == c.McuId.IMXRT1062,
            "unknown board/MCU",
        )
        _require(isinstance(self.simulated, bool), "simulated must be boolean")
        _require(
            self.protocol_version == c.PROTOCOL_VERSION
            and self.adc_resolution_bits == 12,
            "unsupported protocol/resolution",
        )
        _require(
            not self.simulated or self.hardware_serial.startswith("SIM-"),
            "simulated identity requires SIM- serial",
        )
        return _pack(
            c.INFO_RESPONSE_STRUCT_FORMAT,
            0,
            0,
            0,
            self.board_id,
            self.mcu_id,
            self.simulated,
            self.protocol_version,
            self.adc_resolution_bits,
            0,
            _ascii_encode(self.hardware_serial, c.INFO_RESPONSE_HARDWARE_SERIAL_COUNT),
            _ascii_encode(
                self.firmware_version, c.INFO_RESPONSE_FIRMWARE_VERSION_COUNT
            ),
            _ascii_encode(self.build_id, c.INFO_RESPONSE_BUILD_ID_COUNT),
            self.clocks.to_bytes(),
        )

    @classmethod
    def from_payload(cls, payload: BytesLike) -> V3Info:
        data = _success(payload, c.INFO_RESPONSE_PAYLOAD_SIZE)
        (
            _,
            _,
            _,
            board,
            mcu,
            simulated,
            version,
            resolution,
            reserved,
            serial,
            firmware,
            build,
            clocks,
        ) = struct.unpack(c.INFO_RESPONSE_STRUCT_FORMAT, data)
        _require(reserved == 0 and simulated in (0, 1), "invalid INFO reserved/boolean")
        _require(
            board == c.BoardId.TEENSY_40 and mcu == c.McuId.IMXRT1062,
            "unknown board/MCU",
        )
        result = cls(
            c.BoardId(board),
            c.McuId(mcu),
            bool(simulated),
            _ascii_decode(serial),
            _ascii_decode(firmware),
            _ascii_decode(build),
            V3Clocks.from_bytes(clocks),
            version,
            resolution,
        )
        result.to_payload()
        return result


def _table(data: bytes, count: int, capacity: int, size: int) -> tuple[bytes, ...]:
    _require(1 <= count <= capacity, "table count outside capacity")
    _require(not any(data[count * size :]), "unused table records must be zero")
    records = tuple(data[i * size : (i + 1) * size] for i in range(count))
    _require(len(set(records)) == count, "duplicate table records")
    return records


@dataclass(frozen=True, slots=True)
class V3Capabilities:
    defaults: V3Settings
    cpu_profiles: tuple[V3Clocks, ...]
    rate_profiles: tuple[V3Rate, ...]
    configurations: tuple[V3Settings, ...]
    max_data_frame_bytes: int = c.MAX_DATA_FRAME_BYTES
    max_control_frame_bytes: int = c.MAX_CONTROL_FRAME_BYTES
    max_logical_payload_bytes: int = c.MAX_LOGICAL_PAYLOAD_BYTES
    max_encoded_sample_bytes: int = c.MAX_ENCODED_SAMPLE_BYTES
    max_adc_pairs: int = c.MAX_ADC_PAIRS
    max_gpio8_samples: int = c.MAX_GPIO8_SAMPLES
    max_gpio16_samples: int = c.MAX_GPIO16_SAMPLES

    def to_payload(self) -> bytes:
        limits = (
            self.max_data_frame_bytes,
            self.max_control_frame_bytes,
            self.max_logical_payload_bytes,
            self.max_encoded_sample_bytes,
            self.max_adc_pairs,
            self.max_gpio8_samples,
            self.max_gpio16_samples,
        )
        _validate_limits(limits)
        counts = (
            len(self.cpu_profiles),
            len(self.rate_profiles),
            len(self.configurations),
        )
        for count, capacity in zip(
            counts,
            (c.MAX_CPU_PROFILES, c.MAX_RATE_PROFILES, c.MAX_CONFIGURATION_TUPLES),
        ):
            _require(1 <= count <= capacity, "table count outside capacity")
        cpus = tuple(record.to_bytes() for record in self.cpu_profiles)
        rates = tuple(record.to_bytes() for record in self.rate_profiles)
        settings = tuple(record.to_bytes() for record in self.configurations)
        _require(
            len(set(cpus)) == counts[0]
            and len(set(rates)) == counts[1]
            and len(set(settings)) == counts[2],
            "duplicate table records",
        )
        self.defaults.to_bytes()
        _require(
            self.defaults in self.configurations, "defaults absent from configurations"
        )
        cpu_ids = {record.cpu_profile for record in self.cpu_profiles}
        rate_ids = {record.rate_profile for record in self.rate_profiles}
        _require(
            all(
                record.cpu_profile in cpu_ids and record.rate_profile in rate_ids
                for record in self.configurations
            ),
            "tuple references absent profile",
        )
        return _pack(
            c.CAPABILITIES_RESPONSE_STRUCT_FORMAT,
            0,
            0,
            0,
            *counts,
            0,
            *limits,
            self.defaults.to_bytes(),
            b"".join(cpus).ljust(c.MAX_CPU_PROFILES * _CLOCKS.size, b"\0"),
            b"".join(rates).ljust(c.MAX_RATE_PROFILES * _RATE.size, b"\0"),
            b"".join(settings).ljust(
                c.MAX_CONFIGURATION_TUPLES * _SETTINGS.size, b"\0"
            ),
        )

    @classmethod
    def from_payload(cls, payload: BytesLike) -> V3Capabilities:
        data = _success(payload, c.CAPABILITIES_RESPONSE_PAYLOAD_SIZE)
        fields = struct.unpack(c.CAPABILITIES_RESPONSE_STRUCT_FORMAT, data)
        _, _, _, nc, nr, ns, reserved, *tail = fields
        _require(reserved == 0, "nonzero capability reserved field")
        limits = tuple(tail[:7])
        _validate_limits(limits)
        default, cpus, rates, settings = tail[7:]
        cpu_records = _table(cpus, nc, c.MAX_CPU_PROFILES, _CLOCKS.size)
        rate_records = _table(rates, nr, c.MAX_RATE_PROFILES, _RATE.size)
        settings_records = _table(
            settings, ns, c.MAX_CONFIGURATION_TUPLES, _SETTINGS.size
        )
        result = cls(
            V3Settings.from_bytes(default),
            tuple(V3Clocks.from_bytes(record) for record in cpu_records),
            tuple(V3Rate.from_bytes(record) for record in rate_records),
            tuple(V3Settings.from_bytes(record) for record in settings_records),
            *limits,
        )
        result.to_payload()
        return result

    @classmethod
    def canonical(cls) -> V3Capabilities:
        return cls(
            V3Settings.defaults(),
            tuple(map(V3Clocks.from_bytes, c.CPU_PROFILES)),
            tuple(map(V3Rate.from_bytes, c.RATE_PROFILES)),
            tuple(map(V3Settings.from_bytes, c.SELECTABLE_CONFIGURATIONS)),
        )

    def require_supported(self, settings: V3Settings) -> None:
        self.to_payload()
        settings.to_bytes()
        if settings not in self.configurations:
            raise V3FrameValidationError(
                "settings not advertised by device",
                error_code=c.ErrorCode.UNSUPPORTED_CONFIGURATION,
            )

    def select_settings(
        self,
        *,
        adc: bool | None = None,
        gpio: bool | None = None,
        source: c.Source | int | None = None,
        checksum_algorithm: c.ChecksumAlgorithm | int | None = None,
        cpu_profile: c.CpuProfile | int | None = None,
        rate_profile: c.RateProfile | int | None = None,
        aux_bank_mode: c.AuxBankMode | int | None = None,
        gpio_policy: c.GpioPolicy | int | None = None,
        adc_policy: c.AdcPolicy | int | None = None,
        adc_resolution_bits: int | None = None,
        adc_pair_rate_hz: int | None = None,
        gpio_sample_rate_hz: int | None = None,
    ) -> V3Settings:
        """Select one advertised tuple, filling omitted options from defaults.

        Explicit rates select an advertised rate record; a profile selects its
        complete rate pair. Clock selection never silently changes encoding.
        This method is read-only and can be used before CONFIGURE.
        """
        self.to_payload()
        for name, enabled in (("adc", adc), ("gpio", gpio)):
            if enabled is not None and not isinstance(enabled, bool):
                raise TypeError(f"{name} selector must be a boolean or None")
        options = {
            "source": source,
            "checksum_algorithm": checksum_algorithm,
            "cpu_profile": cpu_profile,
            "rate_profile": rate_profile,
            "aux_bank_mode": aux_bank_mode,
            "gpio_policy": gpio_policy,
            "adc_policy": adc_policy,
            "adc_resolution_bits": adc_resolution_bits,
            "adc_pair_rate_hz": adc_pair_rate_hz,
            "gpio_sample_rate_hz": gpio_sample_rate_hz,
        }
        for name, value in options.items():
            if value is not None and (
                not isinstance(value, int) or isinstance(value, bool)
            ):
                raise TypeError(f"{name} must be an integer or enum, not {value!r}")
        requested = {
            field.name: getattr(self.defaults, field.name)
            for field in fields(V3Settings)
        }
        requested.update(
            {key: value for key, value in options.items() if value is not None}
        )
        mask = int(self.defaults.stream_mask)
        for enabled, bit in ((adc, c.StreamMask.ADC), (gpio, c.StreamMask.GPIO)):
            if enabled is not None:
                mask = mask | int(bit) if enabled else mask & ~int(bit)
        requested["stream_mask"] = mask
        if aux_bank_mode is not None:
            widths = {
                record.gpio_width_bits
                for record in self.configurations
                if record.aux_bank_mode == aux_bank_mode
            }
            if len(widths) == 1:
                requested["gpio_width_bits"] = widths.pop()
        if any(
            value is not None
            for value in (rate_profile, adc_pair_rate_hz, gpio_sample_rate_hz)
        ):
            rates = tuple(
                rate
                for rate in self.rate_profiles
                if (rate_profile is None or rate.rate_profile == rate_profile)
                and (
                    adc_pair_rate_hz is None
                    or rate.adc_pair_rate_hz == adc_pair_rate_hz
                )
                and (
                    gpio_sample_rate_hz is None
                    or rate.gpio_sample_rate_hz == gpio_sample_rate_hz
                )
            )
            if len(rates) != 1:
                raise V3FrameValidationError(
                    "rates/profile do not select one advertised rate record; "
                    "inspect get_capabilities().rate_profiles",
                    error_code=c.ErrorCode.UNSUPPORTED_CONFIGURATION,
                )
            rate = rates[0]
            requested.update(
                rate_profile=rate.rate_profile,
                adc_pair_rate_hz=rate.adc_pair_rate_hz,
                gpio_sample_rate_hz=rate.gpio_sample_rate_hz,
            )
        for record in self.configurations:
            if all(getattr(record, key) == value for key, value in requested.items()):
                return record
        raise V3FrameValidationError(
            f"settings tuple not advertised: {requested}; "
            "inspect get_capabilities().configurations and select a complete tuple "
            "(450 MHz requires RAW GPIO and ADC policies)",
            error_code=c.ErrorCode.UNSUPPORTED_CONFIGURATION,
        )


@dataclass(frozen=True, slots=True)
class V3Stop:
    state: c.DeviceState
    run_id: int
    pending_frames: int

    def to_payload(self) -> bytes:
        _require(self.state in tuple(c.DeviceState), "unknown device state")
        _require(
            self.state != c.DeviceState.STOPPED or self.pending_frames == 0,
            "STOPPED requires an empty queue",
        )
        _require(
            self.state != c.DeviceState.DRAINING or self.pending_frames > 0,
            "DRAINING requires pending frames",
        )
        _require(
            self.state == c.DeviceState.STOPPED or self.run_id != 0,
            "active state requires a run",
        )
        return _pack(
            c.STOP_RESPONSE_STRUCT_FORMAT,
            0,
            0,
            0,
            self.state,
            0,
            0,
            self.run_id,
            self.pending_frames,
        )

    @classmethod
    def from_payload(cls, payload: BytesLike) -> V3Stop:
        data = _success(payload, c.STOP_RESPONSE_PAYLOAD_SIZE)
        _, _, _, state, reserved, reserved2, run, pending = struct.unpack(
            c.STOP_RESPONSE_STRUCT_FORMAT, data
        )
        _require(reserved == reserved2 == 0, "nonzero state reserved field")
        try:
            result = cls(c.DeviceState(state), run, pending)
        except ValueError as exc:
            raise V3FrameValidationError("unknown device state") from exc
        result.to_payload()
        return result


@dataclass(frozen=True, slots=True)
class V3Status(V3Stop):
    adc_frames_produced: int = 0
    adc_frames_dropped: int = 0
    adc_items_produced: int = 0
    adc_items_dropped: int = 0
    gpio_frames_produced: int = 0
    gpio_frames_dropped: int = 0
    gpio_items_produced: int = 0
    gpio_items_dropped: int = 0
    adc_codec_completed: int = 0
    adc_codec_raw: int = 0
    adc_codec_deadline_drops: int = 0
    adc_codec_resource_drops: int = 0
    adc_codec_work_ticks: int = 0
    adc_codec_max_work_ticks: int = 0
    adc_codec_max_age_ticks: int = 0
    gpio_codec_completed: int = 0
    gpio_codec_raw: int = 0
    gpio_codec_deadline_drops: int = 0
    gpio_codec_resource_drops: int = 0
    gpio_codec_work_ticks: int = 0
    gpio_codec_max_work_ticks: int = 0
    gpio_codec_max_age_ticks: int = 0
    adc_wire_bytes_transmitted: int = 0
    adc_items_per_frame: int = 0
    adc_max_frame_bytes: int = 0
    adc_retention_ticks: int = 0
    gpio_wire_bytes_transmitted: int = 0
    gpio_items_per_frame: int = 0
    gpio_max_frame_bytes: int = 0
    gpio_retention_ticks: int = 0

    def to_payload(self) -> bytes:
        prefix = V3Stop.to_payload(self)
        counts = (
            self.adc_frames_produced,
            self.adc_frames_dropped,
            self.adc_items_produced,
            self.adc_items_dropped,
            self.gpio_frames_produced,
            self.gpio_frames_dropped,
            self.gpio_items_produced,
            self.gpio_items_dropped,
        )
        _require(
            all(
                0 <= dropped <= produced
                for produced, dropped in zip(counts[::2], counts[1::2])
            ),
            "dropped count exceeds produced",
        )
        diagnostics = (
            self.adc_codec_completed,
            self.adc_codec_raw,
            self.adc_codec_deadline_drops,
            self.adc_codec_resource_drops,
            self.adc_codec_work_ticks,
            self.adc_codec_max_work_ticks,
            self.adc_codec_max_age_ticks,
            self.gpio_codec_completed,
            self.gpio_codec_raw,
            self.gpio_codec_deadline_drops,
            self.gpio_codec_resource_drops,
            self.gpio_codec_work_ticks,
            self.gpio_codec_max_work_ticks,
            self.gpio_codec_max_age_ticks,
            self.adc_wire_bytes_transmitted,
            self.adc_items_per_frame,
            self.adc_max_frame_bytes,
            self.adc_retention_ticks,
            self.gpio_wire_bytes_transmitted,
            self.gpio_items_per_frame,
            self.gpio_max_frame_bytes,
            self.gpio_retention_ticks,
        )
        return prefix + _pack("<30Q", *counts, *diagnostics)

    @classmethod
    def from_payload(cls, payload: BytesLike) -> V3Status:
        data = _success(payload, c.STATUS_RESPONSE_PAYLOAD_SIZE)
        stop = V3Stop.from_payload(data[: c.STOP_RESPONSE_PAYLOAD_SIZE])
        result = cls(
            stop.state,
            stop.run_id,
            stop.pending_frames,
            *struct.unpack_from("<30Q", data, c.STOP_RESPONSE_PAYLOAD_SIZE),
        )
        result.to_payload()
        return result


V3ResponseValue = V3Info | V3Capabilities | V3AppliedSettings | V3Stop | V3Status


@dataclass(frozen=True, slots=True)
class V3Command:
    kind: c.CommandKind
    request_id: int
    settings: V3Settings | None = None

    def to_bytes(self) -> bytes:
        _require(self.kind in tuple(c.CommandKind), "unknown command kind")
        _require(
            (self.kind == c.CommandKind.CONFIGURE) == (self.settings is not None),
            "only CONFIGURE carries settings",
        )
        return encode_v3_frame(
            int(self.kind),
            self.settings.to_bytes() if self.settings else b"",
            request_id=self.request_id,
        )

    @classmethod
    def from_frame(cls, frame: V3Frame) -> V3Command:
        from .protocol_v3 import decode_v3_frame

        frame = decode_v3_frame(frame.to_bytes())
        try:
            kind = c.CommandKind(frame.header.kind)
        except ValueError as exc:
            raise V3FrameValidationError("frame is not a command") from exc
        return cls(
            kind,
            frame.header.request_id,
            V3Settings.from_bytes(frame.payload)
            if kind == c.CommandKind.CONFIGURE
            else None,
        )


@dataclass(frozen=True, slots=True)
class V3Response:
    kind: c.FrameKind
    request_id: int
    run_id: int
    status: c.ResponseStatus
    error_code: c.ErrorCode
    value: V3ResponseValue | None = None
    rejected_kind: int | None = None

    @property
    def ok(self) -> bool:
        return self.status == c.ResponseStatus.OK

    def to_bytes(self) -> bytes:
        _require(
            self.status in tuple(c.ResponseStatus)
            and self.error_code in tuple(c.ErrorCode),
            "unknown response status/error",
        )
        if self.status == c.ResponseStatus.OK:
            _require(
                self.error_code == c.ErrorCode.OK
                and self.value is not None
                and self.rejected_kind is None,
                "invalid success response",
            )
            assert self.value is not None
            payload = self.value.to_payload()
            flags = 0
        else:
            _require(
                self.error_code != c.ErrorCode.OK and self.value is None,
                "invalid error response",
            )
            payload = _pack(
                c.RESPONSE_PREFIX_STRUCT_FORMAT, self.status, 0, self.error_code
            )
            if self.kind == c.FrameKind.ERROR_RESPONSE:
                _require(
                    self.rejected_kind is not None,
                    "generic error requires rejected kind",
                )
                assert self.rejected_kind is not None
                payload += _pack("<BBH", self.rejected_kind, 0, 0)
            else:
                _require(
                    self.rejected_kind is None, "typed error cannot carry rejected kind"
                )
            flags = int(c.FrameFlag.RESPONSE_ERROR)
        return encode_v3_frame(
            self.kind,
            payload,
            request_id=self.request_id,
            run_id=self.run_id,
            flags=flags,
        )

    def validate_for(self, command: V3Command) -> None:
        """Check correlation and exact CONFIGURE echo without mutating any state."""
        _require(self.request_id == command.request_id, "response request ID mismatch")
        expected = c.COMMAND_RESPONSE_KINDS[command.kind]
        _require(self.kind == expected, "response kind mismatch")
        if (
            self.status == c.ResponseStatus.OK
            and command.kind == c.CommandKind.CONFIGURE
        ):
            _require(
                isinstance(self.value, V3AppliedSettings)
                and self.value.settings == command.settings,
                "applied settings differ from CONFIGURE request",
            )


def decode_v3_response(frame: V3Frame) -> V3Response:
    """Decode a structurally validated response; also used by the frame codec."""
    kind = frame.header.kind
    _require(
        kind in c.COMMAND_RESPONSE_KINDS.values() or kind == c.FrameKind.ERROR_RESPONSE,
        "frame is not a response",
    )
    data = _bounded_bytes(
        frame.payload,
        c.RESPONSE_PREFIX_PAYLOAD_SIZE,
        c.MAX_CONTROL_FRAME_BYTES - c.MIN_FRAME_BYTES,
    )
    status, reserved, error = struct.unpack_from(c.RESPONSE_PREFIX_STRUCT_FORMAT, data)
    _require(
        status in tuple(c.ResponseStatus)
        and error in tuple(c.ErrorCode)
        and reserved == 0,
        "invalid response prefix",
    )
    _require(
        bool(frame.header.flags & c.FrameFlag.RESPONSE_ERROR)
        == (status == c.ResponseStatus.ERROR)
        and (status == c.ResponseStatus.OK) == (error == c.ErrorCode.OK),
        "response flag/status/error disagree",
    )
    _require(
        frame.header.request_id != 0 or error == c.ErrorCode.INVALID_REQUEST_ID,
        "zero request ID only allowed for INVALID_REQUEST_ID",
    )
    value: V3ResponseValue | None = None
    rejected = None
    if status == c.ResponseStatus.ERROR:
        if kind == c.FrameKind.ERROR_RESPONSE:
            _require(
                len(data) == c.ERROR_RESPONSE_PAYLOAD_SIZE and not any(data[5:]),
                "invalid generic error size/reserved",
            )
            rejected = data[4]
        else:
            _require(
                len(data) == c.RESPONSE_PREFIX_PAYLOAD_SIZE,
                "error must contain only prefix",
            )
    elif kind == c.FrameKind.INFO_RESPONSE:
        value = V3Info.from_payload(data)
    elif kind == c.FrameKind.GET_CAPABILITIES_RESPONSE:
        value = V3Capabilities.from_payload(data)
    elif kind in (
        c.FrameKind.CONFIGURE_RESPONSE,
        c.FrameKind.START_RESPONSE,
        c.FrameKind.GET_SETTINGS_RESPONSE,
    ):
        value = V3AppliedSettings.from_payload(data)
    elif kind == c.FrameKind.GET_STATUS_RESPONSE:
        value = V3Status.from_payload(data)
    elif kind == c.FrameKind.STOP_RESPONSE:
        value = V3Stop.from_payload(data)
        _require(value.state != c.DeviceState.RUNNING, "STOP cannot report RUNNING")
    else:
        raise V3FrameValidationError("generic response requires error status")
    if isinstance(value, V3Stop):
        _require(value.run_id == frame.header.run_id, "state/header run ID mismatch")
    return V3Response(
        kind,
        frame.header.request_id,
        frame.header.run_id,
        c.ResponseStatus(status),
        c.ErrorCode(error),
        value,
        rejected,
    )
