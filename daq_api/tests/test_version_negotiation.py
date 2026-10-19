"""Bounded INFO negotiation and latched-session compatibility regressions."""

import struct
from dataclasses import replace
from time import monotonic
from unittest.mock import patch

import pytest
from thingdone_daq import (
    CommandTimeoutError,
    DAQConfiguration,
    DeviceIdentityMismatchError,
    DiscoveryProbeError,
    InMemoryTransport,
    RateProfile,
    SerialPortCandidate,
    Source,
    StreamMask,
    ThingDAQ,
    probe_candidate,
)
from thingdone_daq._generated import protocol_constants as c
from thingdone_daq._generated import protocol_v3_constants as v3
from thingdone_daq.models_v3 import V3Response, V3Settings
from thingdone_daq.protocol import encode_frame
from thingdone_daq.protocol_v2 import IncrementalCompatibleFrameParser
from thingdone_daq.reader import BackgroundReader, ReaderProtocolError
from thingdone_daq.simulator import SimulatedDevice
from thingdone_daq.simulator_v3 import SimulatedV3Device


def rejection(
    request,
    *,
    request_id=None,
    kind=None,
    version=None,
    error=c.ErrorCode.UNSUPPORTED_VERSION,
):
    return encode_frame(
        c.FrameKind.ERROR_RESPONSE,
        struct.pack(
            "<BBHBBH",
            1,
            0,
            error,
            int(request.header.kind) if kind is None else kind,
            request.header.version if version is None else version,
            0,
        ),
        flags=c.FrameFlag.RESPONSE_ERROR,
        request_id=request.header.request_id if request_id is None else request_id,
    )


class RecordingTransport(InMemoryTransport):
    def __init__(self, device=None, *, reply=None, **kwargs):
        super().__init__(device, **kwargs)
        self.requests = []
        self.reply = reply
        self.request_parser = IncrementalCompatibleFrameParser(include_v3=True)

    def write(self, data):
        frames = self.request_parser.feed(data)
        self.requests.extend(frames)
        if self.reply is None:
            return super().write(data)
        with self._lock:
            for request in frames:
                self._pending.extend(self.reply(request))
        return len(data)


class V2OnlyDevice(SimulatedDevice):
    """V2-only peer with the release default rate, independent of v1 defaults."""

    def __init__(self):
        super().__init__()
        self._configuration = DAQConfiguration(
            stream_mask=StreamMask.ADC | StreamMask.GPIO,
            source=Source.SYNTHETIC,
            rate_profile=RateProfile.ADC_1MHZ_GPIO_1MHZ,
        )
        self._state = c.DeviceState.CONFIGURED

    def _handle_frame(self, request):
        if request.header.version != 2:
            return rejection(request)
        return super()._handle_frame(request)


class PhysicalV3Device(SimulatedV3Device):
    def info(self):
        return replace(
            super().info(),
            simulated=False,
            hardware_serial="123456",
            firmware_version="1.2.0",
            build_id="thingdaq-0123456789abcdef",
        )


def candidate(serial="123456"):
    return SerialPortCandidate("/dev/test", 0x16C0, 0x0483, serial_number=serial)


@pytest.mark.parametrize(
    "device,version,probes,gpio_rate",
    [
        (SimulatedDevice, 1, [3, 1, 1], 4_000_000),
        (V2OnlyDevice, 2, [3, 1, 2, 2], 1_000_000),
        (SimulatedV3Device, 3, [3, 3], 1_000_000),
    ],
)
def test_shared_open_prefers_v3_and_preserves_legacy_defaults(
    device, version, probes, gpio_rate
):
    transport = RecordingTransport(device())
    with ThingDAQ.open(transport, synchronization_retry_delay=0, strict=True) as daq:
        assert [
            f.header.version
            for f in transport.requests
            if f.header.kind == c.FrameKind.INFO_REQUEST
        ] == probes
        assert daq.device_info.protocol_version == version
        daq.configure()
        assert daq.configuration.adc_pair_rate_hz == 1_000_000
        assert daq.configuration.gpio_sample_rate_hz == gpio_rate
        for _ in range(2):
            daq.start()
            assert daq.read_block().protocol_version == version
            daq.stop()
            boundary = len(transport.requests)
            daq.info()
            daq.status()
            if version == 2:
                daq.get_temperature()
                daq.get_runtime_health()
            daq.configure()
            assert all(
                f.header.version == version for f in transport.requests[boundary:]
            )
        if version != 3:
            assert not any(
                f.header.kind
                in (
                    v3.FrameKind.GET_CAPABILITIES_REQUEST,
                    v3.FrameKind.GET_SETTINGS_REQUEST,
                )
                for f in transport.requests
            )
    assert not transport.is_open and not daq.reader.is_running


def test_discovery_v3_is_read_only_and_open_revalidates_identity():
    device = PhysicalV3Device()
    transport = RecordingTransport(device)
    found = probe_candidate(candidate(), transport_factory=lambda _: transport)
    assert found.hardware_serial == 123456
    assert [f.header.version for f in transport.requests] == [3]
    assert all(f.header.kind == c.FrameKind.INFO_REQUEST for f in transport.requests)
    assert device.status().run_id == 0
    assert not transport.is_open
    with ThingDAQ.open(
        found, serial_transport_factory=lambda _: InMemoryTransport(device)
    ) as daq:
        assert daq.verified_identity.hardware_serial == 123456
    with pytest.raises(DiscoveryProbeError):
        probe_candidate(
            candidate("42"), transport_factory=lambda _: InMemoryTransport(device)
        )
    changed = PhysicalV3Device()
    changed.info = lambda: replace(device.info(), hardware_serial="654321")
    wrong = RecordingTransport(changed)
    with pytest.raises(DeviceIdentityMismatchError):
        ThingDAQ.open(found, serial_transport_factory=lambda _: wrong)
    assert not wrong.is_open
    assert all(f.header.kind == c.FrameKind.INFO_REQUEST for f in wrong.requests)


@pytest.mark.parametrize(
    "case",
    [
        "timeout",
        "checksum",
        "metadata",
        "wrong_id",
        "wrong_kind",
        "wrong_version",
        "length",
        "stale_success",
    ],
)
def test_bad_replies_never_authorize_fallback(case):
    device = SimulatedV3Device()

    def reply(request):
        if case == "timeout":
            return b""
        if case in ("checksum", "metadata", "stale_success"):
            wire = bytearray(
                V3Response(
                    v3.FrameKind.INFO_RESPONSE,
                    request.header.request_id,
                    0,
                    v3.ResponseStatus.OK,
                    v3.ErrorCode.OK,
                    device.info(),
                ).to_bytes()
            )
            if case == "metadata":
                # Valid checksum, invalid reserved INFO byte; parser must reject.
                wire[v3.HEADER_SIZE + 9] = 0xFF
                from thingdone_daq.protocol_v3 import compute_v3_checksum

                wire[-4:] = struct.pack("<I", compute_v3_checksum(wire[:-4]))
            elif case == "checksum":
                wire[-1] ^= 0x80
            else:
                return V3Response(
                    v3.FrameKind.INFO_RESPONSE,
                    1,
                    0,
                    v3.ResponseStatus.OK,
                    v3.ErrorCode.OK,
                    device.info(),
                ).to_bytes()
            return bytes(wire)
        return rejection(
            request,
            **{
                "wrong_id": {"request_id": 1},
                "wrong_kind": {"kind": int(c.FrameKind.START_REQUEST)},
                "wrong_version": {"version": 2},
                "length": {"error": c.ErrorCode.INVALID_LENGTH},
            }[case],
        )

    transport = RecordingTransport(reply=reply)
    started = monotonic()
    with (
        patch("thingdone_daq.reader.randbelow", return_value=100),
        pytest.raises((CommandTimeoutError, ReaderProtocolError)),
    ):
        ThingDAQ.open(
            transport,
            command_timeout=0.02,
            synchronization_attempts=2,
            synchronization_retry_delay=0,
        )
    assert monotonic() - started < 1
    assert 1 <= len(transport.requests) <= 2
    assert all(f.header.version == 3 for f in transport.requests)
    assert not transport.is_open


def test_correlated_rejection_allowed_only_for_info_negotiation():
    transport = RecordingTransport(reply=rejection)
    with (
        BackgroundReader(
            transport, parser=IncrementalCompatibleFrameParser(include_v3=True)
        ) as reader,
        pytest.raises(ReaderProtocolError, match="version"),
    ):
        reader.request(v3.FrameKind.INFO_REQUEST, protocol_version=3)


def test_reconnect_refreshes_metadata_and_settings_and_discards_old_responses():
    device = SimulatedV3Device()
    first = RecordingTransport(device)
    with patch("thingdone_daq.reader.randbelow", return_value=10):
        daq = ThingDAQ.open(first)
        old = replace(V3Settings.defaults(), gpio_policy=v3.GpioPolicy.RAW)
        daq.configure(old)
        daq.start()
        daq.close(stop=False)
    # Reset the peer; transport reopening must neither reuse configuration nor IDs.
    device = SimulatedV3Device()
    second = RecordingTransport(device)
    stale = V3Response(
        v3.FrameKind.INFO_RESPONSE,
        11,
        0,
        v3.ResponseStatus.OK,
        v3.ErrorCode.OK,
        replace(device.info(), build_id="stale"),
    ).to_bytes()
    second._pending.extend(stale)
    with (
        patch("thingdone_daq.reader.randbelow", return_value=100),
        ThingDAQ.open(second) as reopened,
    ):
        assert reopened.configuration == V3Settings.defaults()
        assert reopened.device_info.build_id != "stale"
        assert reopened.reader_counters.late_responses == 1
        assert [f.header.kind for f in second.requests] == [
            v3.FrameKind.INFO_REQUEST,
            v3.FrameKind.INFO_REQUEST,
            v3.FrameKind.GET_CAPABILITIES_REQUEST,
            v3.FrameKind.GET_SETTINGS_REQUEST,
            v3.FrameKind.GET_STATUS_REQUEST,
        ]


@pytest.mark.parametrize("policy", ["adopt", "stop"])
def test_v3_reopen_existing_run_uses_fresh_settings(policy):
    device = SimulatedV3Device()
    first = ThingDAQ.open(InMemoryTransport(device))
    settings = replace(V3Settings.defaults(), adc_policy=v3.AdcPolicy.RAW)
    first.configure(settings)
    first.start()
    first.close(stop=False)
    with ThingDAQ.open(InMemoryTransport(device), session_policy=policy) as reopened:
        assert reopened.configuration == settings
        if policy == "adopt":
            assert reopened.read_block().run_id == first.run_id
        else:
            assert reopened.state == v3.DeviceState.STOPPED


def test_huge_noise_is_bounded_and_does_not_downgrade():
    transport = RecordingTransport(reply=lambda _: b"noise" * 100_000)
    daq = ThingDAQ(transport, read_size=1024, command_timeout=0.02)
    try:
        with pytest.raises(CommandTimeoutError):
            daq.synchronize(attempts=2, retry_delay=0)
        assert (
            daq.parser_counters.high_water_mark <= daq.reader._parser.max_buffered_bytes
        )
        assert all(f.header.version == 3 for f in transport.requests)
        assert daq.reader_counters.maximum_read_bytes <= 1024
    finally:
        daq.close(stop=False)


def test_exhausted_versions_have_one_deadline_and_no_reopen():
    from thingdone_daq.reader import ProtocolVersionRejected

    transport = RecordingTransport(reply=rejection)
    with pytest.raises(ProtocolVersionRejected):
        ThingDAQ.open(transport, command_timeout=0.1, synchronization_retry_delay=0)
    assert [f.header.version for f in transport.requests] == [3, 1, 2]
    assert not transport.is_open


def test_timeout_after_explicit_rejection_retries_only_selected_legacy_version():
    transport = RecordingTransport(
        reply=lambda request: rejection(request) if request.header.version == 3 else b""
    )
    with pytest.raises(CommandTimeoutError):
        ThingDAQ.open(
            transport,
            command_timeout=0.02,
            synchronization_attempts=2,
            synchronization_retry_delay=0,
        )
    assert [f.header.version for f in transport.requests] == [3, 1, 1]


def test_typed_v3_unsupported_response_permits_legacy_probe():
    device = SimulatedDevice()

    def reply(request):
        if request.header.version == 3:
            return V3Response(
                v3.FrameKind.INFO_RESPONSE,
                request.header.request_id,
                0,
                v3.ResponseStatus.ERROR,
                v3.ErrorCode.UNSUPPORTED_VERSION,
            ).to_bytes()
        return b"".join(device.receive(request.to_bytes()))

    transport = RecordingTransport(reply=reply)
    with ThingDAQ.open(transport, synchronization_retry_delay=0) as daq:
        assert daq.device_info.protocol_version == 1
    assert [f.header.version for f in transport.requests] == [3, 1, 1]


def test_discovery_legacy_uses_same_fallback_policy_without_configuring():
    from test_discovery import InfoProbeTransport, _physical_info

    transport = InfoProbeTransport(_physical_info(123456))
    found = probe_candidate(candidate(), transport_factory=lambda _: transport)
    assert found.hardware_serial == 123456
    assert [wire[4] for wire in transport.writes] == [3, 1]
    assert transport.closed.is_set()


def test_v3_identity_pins_support_contract_ascii_fields():
    from thingdone_daq import ExpectedDeviceIdentity, select_device

    device = PhysicalV3Device()
    original_info = device.info()
    device.info = lambda: replace(
        original_info,
        hardware_serial="board-abc",
        firmware_version="v3-release",
        build_id="vendor-build",
    )
    found = probe_candidate(
        candidate("board-abc"), transport_factory=lambda _: InMemoryTransport(device)
    )
    assert select_device([found], hardware_serial="board-abc") == found
    with ThingDAQ.open(
        InMemoryTransport(device),
        expected_identity=ExpectedDeviceIdentity.from_info(found.info),
    ) as daq:
        assert daq.verified_identity.hardware_serial == "board-abc"
    bad = RecordingTransport(device)
    with pytest.raises(DeviceIdentityMismatchError):
        ThingDAQ.open(bad, expected_identity=ExpectedDeviceIdentity(build_id="wrong"))
    assert all(f.header.kind == c.FrameKind.INFO_REQUEST for f in bad.requests)
    assert not bad.is_open


@pytest.mark.parametrize("value", [float("nan"), float("inf")])
def test_nonfinite_probe_deadlines_are_rejected(value):
    with pytest.raises(ValueError):
        probe_candidate(candidate(), timeout=value)
    transport = InMemoryTransport()
    try:
        with pytest.raises(ValueError):
            BackgroundReader(transport, request_timeout=value)
    finally:
        transport.close()


def test_open_candidate_checks_nondecimal_usb_serial_before_session_mutation():
    device = PhysicalV3Device()
    original = device.info()
    device.info = lambda: replace(original, hardware_serial="board-abc")
    transport = RecordingTransport(device)
    with pytest.raises(DeviceIdentityMismatchError, match="USB serial"):
        ThingDAQ.open(
            candidate("board-other"),
            session_policy="stop",
            serial_transport_factory=lambda _: transport,
        )
    assert not transport.is_open
    assert all(f.header.kind == c.FrameKind.INFO_REQUEST for f in transport.requests)


def test_open_construction_failure_closes_transport_without_probe_or_reopen():
    transport = RecordingTransport()
    with pytest.raises(ValueError):
        ThingDAQ.open(transport, command_timeout=float("inf"))
    assert not transport.is_open
    assert transport.requests == []


def test_conflicting_identity_pin_does_not_open_a_port():
    from thingdone_daq import ExpectedDeviceIdentity

    opened = []
    with pytest.raises(DeviceIdentityMismatchError):
        ThingDAQ.open(
            candidate(),
            expected_identity=ExpectedDeviceIdentity(hardware_serial=42),
            serial_transport_factory=lambda port: opened.append(port),
        )
    assert opened == []
