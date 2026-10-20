"""Advertised tuple selection, atomic application and clock readback contracts."""

import struct
from dataclasses import replace

import pytest
from thingdone_daq import (
    DeviceCapabilityError,
    InMemoryTransport,
    ThingDAQ,
    UnexpectedMessageError,
    V3AdcPolicy,
    V3AppliedSettings,
    V3Capabilities,
    V3Clocks,
    V3CpuProfile,
    V3GpioPolicy,
    V3Rate,
    V3RateProfile,
    low_level,
)
from thingdone_daq._generated import protocol_v3_constants as c
from thingdone_daq.models_v3 import V3Info, V3Status
from thingdone_daq.simulator_v3 import SimulatedV3Device


class RecordingDevice(SimulatedV3Device):
    def __init__(self):
        super().__init__()
        self.commands = []

    def _reply(self, kind, request_id, value=None, error=c.ErrorCode.OK):
        self.commands.append(kind)
        return super()._reply(kind, request_id, value, error)


def test_metadata_exports_and_read_only_selection():
    device = RecordingDevice()
    with ThingDAQ.open(InMemoryTransport(device)) as daq:
        caps = daq.get_capabilities()
        assert caps == daq.capabilities
        assert all(isinstance(item, V3Clocks) for item in caps.cpu_profiles)
        assert all(isinstance(item, V3Rate) for item in caps.rate_profiles)
        assert caps.defaults.rate_profile == V3RateProfile.ADC_1MHZ_GPIO_1MHZ
        before = list(device.commands)
        selected = caps.select_settings(
            cpu_profile=V3CpuProfile.CPU_600MHZ,
            gpio_policy=V3GpioPolicy.RAW,
            adc_policy=V3AdcPolicy.RAW,
        )
        assert selected in caps.configurations
        assert selected.cpu_profile == V3CpuProfile.CPU_600MHZ
        assert selected != caps.defaults == daq.configuration
        assert device.commands == before
        assert low_level.protocol_v3_constants is c
        command = low_level.V3Command(c.CommandKind.INFO, 123)
        assert low_level.decode_v3_frame(command.to_bytes()).header.request_id == 123


@pytest.mark.parametrize(
    "settings",
    [
        s
        for s in V3Capabilities.canonical().configurations
        if s.cpu_profile == c.CpuProfile.CPU_600MHZ
    ],
)
def test_every_advertised_tuple_can_be_selected_by_keywords_atomically(settings):
    device = RecordingDevice()
    with ThingDAQ.open(InMemoryTransport(device)) as daq:
        device.commands.clear()
        applied = daq.configure(
            adc=bool(settings.stream_mask & c.StreamMask.ADC),
            gpio=bool(settings.stream_mask & c.StreamMask.GPIO),
            source=settings.source,
            checksum_algorithm=settings.checksum_algorithm,
            cpu_profile=settings.cpu_profile,
            rate_profile=settings.rate_profile,
            aux_bank_mode=settings.aux_bank_mode,
            gpio_policy=settings.gpio_policy,
            adc_policy=settings.adc_policy,
            adc_resolution_bits=settings.adc_resolution_bits,
            adc_pair_rate_hz=settings.adc_pair_rate_hz,
            gpio_sample_rate_hz=settings.gpio_sample_rate_hz,
        )
        assert applied.settings == settings == device.settings == daq.configuration
        assert applied.clocks == daq.device_info.clocks
        assert device.commands == [
            c.CommandKind.CONFIGURE,
            c.CommandKind.GET_SETTINGS,
            c.CommandKind.INFO,
        ]
        assert applied == daq.get_settings()


def test_omissions_reset_to_advertised_defaults_and_do_not_reuse_active_settings():
    with ThingDAQ.simulated(protocol_version=3) as daq:
        defaults = daq.get_capabilities().defaults
        changed = daq.configure(
            gpio=False,
            cpu_profile=V3CpuProfile.CPU_600MHZ,
            gpio_policy=V3GpioPolicy.RAW,
            adc_policy=V3AdcPolicy.RAW,
        )
        assert changed.settings != defaults
        assert daq.get_capabilities().defaults == defaults
        assert daq.configure().settings == defaults
        assert daq.configure(gpio=False).settings.stream_mask == c.StreamMask.ADC
        assert daq.configure(adc=False).settings.stream_mask == c.StreamMask.GPIO
        assert (
            daq.configure(rate_profile=V3RateProfile.ADC_1MHZ_GPIO_1MHZ).settings
            == defaults
        )
        assert daq.configure(adc_pair_rate_hz=1_000_000).settings == defaults
        assert daq.configure(gpio_sample_rate_hz=1_000_000).settings == defaults


@pytest.mark.parametrize(
    "options",
    [
        {"cpu_profile": 3},
        {"cpu_profile": V3CpuProfile.CPU_450MHZ},
        {
            "cpu_profile": V3CpuProfile.CPU_450MHZ,
            "gpio_policy": V3GpioPolicy.RAW,
            "adc_policy": V3AdcPolicy.RAW,
        },
        {"rate_profile": 0},
        {"adc_pair_rate_hz": 2_000_000},
        {"gpio_sample_rate_hz": 4_000_000},
        {"adc_resolution_bits": 10},
        {"gpio_policy": 2},
        {"adc_policy": 2},
        {"aux_bank_mode": 2},
        {"checksum_algorithm": 2},
        {"adc": False, "gpio": False},
    ],
)
def test_unavailable_requests_fail_actionably_before_any_transaction(options):
    device = RecordingDevice()
    with ThingDAQ.open(InMemoryTransport(device)) as daq:
        before = list(device.commands)
        with pytest.raises(DeviceCapabilityError, match="get_capabilities"):
            daq.configure(**options)
        assert device.commands == before
        assert daq.configuration == device.settings == daq.capabilities.defaults


def test_valid_but_unadvertised_combination_is_rejected():
    device = RecordingDevice()
    device._capabilities = replace(
        device._capabilities, configurations=(device.settings,)
    )
    with ThingDAQ.open(InMemoryTransport(device)) as daq:
        before = list(device.commands)
        with pytest.raises(DeviceCapabilityError, match="not advertised"):
            daq.configure(gpio_policy=V3GpioPolicy.RAW)
        assert device.commands == before


@pytest.mark.parametrize(
    "option",
    [
        "source",
        "checksum_algorithm",
        "cpu_profile",
        "rate_profile",
        "aux_bank_mode",
        "gpio_policy",
        "adc_policy",
        "adc_resolution_bits",
        "adc_pair_rate_hz",
        "gpio_sample_rate_hz",
    ],
)
@pytest.mark.parametrize("value", [True, 1.0, "1"])
def test_scalar_selector_types_are_not_silently_coerced(option, value):
    with (
        ThingDAQ.simulated(protocol_version=3) as daq,
        pytest.raises(TypeError, match=option),
    ):
        daq.configure(**{option: value})


@pytest.mark.parametrize(
    "options",
    [
        {"adc": True},
        {"gpio": True},
        {"checksum_algorithm": c.ChecksumAlgorithm.ADLER32},
        {"cpu_profile": V3CpuProfile.CPU_600MHZ},
        {"gpio_policy": V3GpioPolicy.RLE_AUTO},
        {"adc_policy": V3AdcPolicy.PACK12},
    ],
)
def test_complete_settings_object_rejects_explicit_overrides_even_equal_ones(options):
    with (
        ThingDAQ.simulated(protocol_version=3) as daq,
        pytest.raises(ValueError, match="do not combine"),
    ):
        daq.configure(daq.capabilities.defaults, **options)


class WrongInfoClock(RecordingDevice):
    tamper = False

    def _reply(self, kind, request_id, value=None, error=c.ErrorCode.OK):
        if self.tamper and isinstance(value, V3Info):
            other = (
                c.CpuProfile.CPU_450MHZ
                if value.clocks.cpu_profile == c.CpuProfile.CPU_600MHZ
                else c.CpuProfile.CPU_600MHZ
            )
            value = replace(value, clocks=V3Clocks.for_profile(other))
        return super()._reply(kind, request_id, value, error)


@pytest.mark.parametrize("operation", ["configure", "get_settings"])
def test_actual_info_clocks_must_match_applied_echo_and_readback(operation):
    device = WrongInfoClock()
    with ThingDAQ.open(InMemoryTransport(device)) as daq:
        before = daq.configuration
        device.tamper = True
        with pytest.raises(UnexpectedMessageError, match="INFO clocks"):
            if operation == "configure":
                daq.configure(gpio_policy=V3GpioPolicy.RAW)
            else:
                daq.get_settings()
        assert daq.configuration == before


def test_open_checks_initial_settings_against_synchronized_info_clocks():
    device = WrongInfoClock()
    device.tamper = True
    transport = InMemoryTransport(device)
    with pytest.raises(UnexpectedMessageError, match="INFO clocks"):
        ThingDAQ.open(transport)
    assert not transport.is_open


def test_echo_and_readback_agree_but_disagree_with_request_is_rejected():
    class WrongSettings(RecordingDevice):
        tamper = False

        def _reply(self, kind, request_id, value=None, error=c.ErrorCode.OK):
            if self.tamper and isinstance(value, V3AppliedSettings):
                value = replace(
                    value,
                    settings=replace(value.settings, gpio_policy=c.GpioPolicy.RAW),
                )
            return super()._reply(kind, request_id, value, error)

    device = WrongSettings()
    with ThingDAQ.open(InMemoryTransport(device)) as daq:
        device.tamper = True
        with pytest.raises(UnexpectedMessageError, match="differ from request"):
            daq.configure()


@pytest.mark.parametrize(
    "options",
    [
        {"cpu_profile": V3CpuProfile.CPU_600MHZ},
        {"gpio_policy": V3GpioPolicy.RLE_AUTO},
        {"adc_policy": V3AdcPolicy.PACK12},
    ],
)
def test_legacy_configuration_never_silently_ignores_v3_selectors(options):
    with ThingDAQ.simulated() as daq:
        before = daq.reader_counters.responses_matched
        with pytest.raises(DeviceCapabilityError, match="requires protocol v3"):
            daq.configure(**options)
        assert daq.reader_counters.responses_matched == before
        applied = daq.configure()
        assert applied.adc_pair_rate_hz == 1_000_000
        assert applied.gpio_sample_rate_hz == 4_000_000


def test_public_status_diagnostics_have_independent_fixed_offsets():
    # 16-byte state prefix, 8 logical counters, then 22 diagnostic u64s.
    prefix = struct.pack("<BBHBBHII", 0, 0, 0, 1, 0, 0, 7, 0)
    counts = (8, 1, 8064, 1008, 2, 0, 8064, 0)
    diagnostics = tuple((1 << 32) + i for i in range(22))
    payload = prefix + struct.pack("<30Q", *counts, *diagnostics)
    assert len(payload) == 256
    status = V3Status.from_payload(payload)
    assert status.adc_codec_completed == 1 << 32
    assert status.adc_codec_max_age_ticks == (1 << 32) + 6
    assert status.gpio_codec_completed == (1 << 32) + 7
    assert status.adc_wire_bytes_transmitted == (1 << 32) + 14
    assert status.gpio_retention_ticks == (1 << 32) + 21
    assert status.to_payload() == payload
