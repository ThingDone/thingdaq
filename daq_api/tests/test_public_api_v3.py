"""V3 public-session integration using the real reader, parser and wire peer."""

from dataclasses import replace
from time import monotonic, sleep

import pytest
from thingdone_daq import (
    ADCBlock,
    DeviceCommandError,
    GPIOBlock,
    HostQueueLoss,
    ThingDAQ,
    UnexpectedHostQueueLossError,
    UnexpectedMessageError,
    UnexpectedStreamGapError,
    V3AppliedSettings,
    V3Capabilities,
    V3Settings,
)
from thingdone_daq._generated import protocol_constants as legacy
from thingdone_daq._generated import protocol_v3_constants as c
from thingdone_daq.models_v3 import V3Clocks
from thingdone_daq.protocol_v2 import IncrementalCompatibleFrameParser
from thingdone_daq.protocol_v3 import V3FrameValidationError, decode_v3_frame
from thingdone_daq.simulator_v3 import SimulatedV3Device


def raw600(defaults):
    return replace(
        defaults,
        cpu_profile=c.CpuProfile.CPU_600MHZ,
        gpio_policy=c.GpioPolicy.RAW,
        adc_policy=c.AdcPolicy.RAW,
    )


def test_defaults_discovery_transitions_and_atomic_running_rejection():
    with ThingDAQ.simulated(protocol_version=3, strict=True) as daq:
        assert daq.info().simulated
        assert daq.state == c.DeviceState.STOPPED
        capabilities = daq.get_capabilities()
        defaults = capabilities.defaults
        assert daq.configuration == defaults == V3Settings.defaults()
        assert len(capabilities.configurations) == 48
        for epoch, settings in enumerate((defaults, raw600(defaults), defaults), 1):
            applied = daq.configure(settings)
            assert applied == daq.get_settings()
            assert applied.settings == settings
            assert daq.info().clocks == applied.clocks
            assert daq.start() == epoch
            with pytest.raises(DeviceCommandError) as error:
                daq.configure(raw600(defaults))
            assert error.value.error_code == c.ErrorCode.INVALID_STATE
            assert daq.get_settings() == applied
            blocks = list(daq.blocks(4))
            assert all(block.run_id == epoch for block in blocks)
            assert [b.sequence for b in blocks] == [0, 0, 1, 1]
            assert daq.validate_stream_health().run_id == epoch
            assert not daq.loss_counters().has_loss
            assert daq.stop() == c.DeviceState.STOPPED
            assert daq.stop() == c.DeviceState.STOPPED
            assert daq.get_settings() == applied
        transport, reader = daq.transport, daq.reader
    assert not transport.is_open and not reader.is_running


@pytest.mark.parametrize("settings", V3Capabilities.canonical().configurations)
def test_generic_tuple_through_public_blocks_or_host_rejection(settings):
    with ThingDAQ.simulated(
        protocol_version=3, strict=True, stream_interval=0.003
    ) as daq:
        if settings.cpu_profile != c.CpuProfile.CPU_600MHZ:
            before = daq.get_settings()
            requests = daq.reader_counters.responses_matched
            with pytest.raises(V3FrameValidationError, match="not advertised"):
                daq.configure(settings)
            assert daq.reader_counters.responses_matched == requests
            assert daq.get_settings() == before
            return
        assert daq.configure(settings).settings == settings
        daq.start()
        blocks = list(daq.blocks(4))
        for block in blocks:
            assert block.protocol_version == 3 and block.run_id == daq.run_id
            assert block.first_sample_ticks == block.sequence * block.item_count * 8
            if isinstance(block, ADCBlock):
                assert settings.stream_mask & c.StreamMask.ADC
                pairs = list(zip(block.adc0, block.adc1))
                first = block.first_sample_ticks // 8
                edges = ((0, 0), (4095, 4095), (0xABC, 0x123), (0x555, 0xAAA))
                for offset, pair in enumerate(pairs):
                    phase = (first + offset) % 2048
                    assert pair == (
                        edges[phase] if phase < 4 else (2 * phase, 2 * phase + 1)
                    )
                assert block.encoded_payload[0] == (
                    c.Encoding.ADC_PACK12
                    if settings.adc_policy == c.AdcPolicy.PACK12
                    else c.Encoding.RAW
                )
                assert block.decoded_bytes == block.item_count * 4
            else:
                assert isinstance(block, GPIOBlock)
                assert settings.stream_mask & c.StreamMask.GPIO
                pattern = (
                    b"\xaa\x55"
                    if settings.gpio_width_bits == 8
                    else b"\xaa\x0f\x55\xf0"
                )
                expected = (
                    bytes(len(block.payload))
                    if block.sequence % 2 == 0
                    else pattern * (len(block.payload) // len(pattern))
                )
                assert block.payload == expected
                expected_encoding = (
                    c.Encoding.GPIO_RLE
                    if settings.gpio_policy == c.GpioPolicy.RLE_AUTO
                    and block.sequence % 2 == 0
                    else c.Encoding.RAW
                )
                assert block.encoded_payload[0] == expected_encoding
                assert block.sample(0) == int.from_bytes(
                    expected[: settings.gpio_width_bits // 8], "little"
                )
        assert daq.validate_stream_health().state == c.DeviceState.RUNNING
        daq.stop()


@pytest.mark.parametrize("chunk", [1, 17, 53, None])
def test_chunked_transport_default_start_stop_restart(chunk):
    with ThingDAQ.simulated(
        protocol_version=3,
        read_chunk_size=chunk,
        write_chunk_size=chunk,
        command_timeout=3,
        block_timeout=3,
        strict=True,
    ) as daq:
        assert daq.start() == 1  # Board defaults are already configured.
        assert all(isinstance(b, (ADCBlock, GPIOBlock)) for b in daq.blocks(4))
        assert daq.stop() == c.DeviceState.STOPPED
        assert daq.configure().settings == daq.capabilities.defaults
        assert daq.start() == 2
        assert [b.sequence for b in daq.blocks(2)] == [0, 0]
        daq.validate_stream_health()


def test_capabilities_are_wire_discovered_and_gate_configuration(monkeypatch):
    device = SimulatedV3Device()
    device._capabilities = replace(
        device._capabilities, configurations=(device.settings,)
    )
    monkeypatch.setattr("thingdone_daq.client.SimulatedV3Device", lambda: device)
    with ThingDAQ.simulated(protocol_version=3) as daq:
        assert daq.get_capabilities().configurations == (device.settings,)
        requests = daq.reader_counters.responses_matched
        with pytest.raises(V3FrameValidationError, match="not advertised"):
            daq.configure(raw600(device.settings))
        assert daq.reader_counters.responses_matched == requests
        assert daq.configuration == device.settings


def test_legacy_defaults_and_parser_remain_opt_in():
    with ThingDAQ.simulated() as daq:
        assert daq.info().protocol_version == 1
        assert daq.configure().gpio_sample_rate_hz == 4_000_000
        with pytest.raises(TypeError, match="protocol v3"):
            daq.configure(V3Settings.defaults())
    from thingdone_daq.models_v3 import V3Command

    wire = V3Command(c.CommandKind.INFO, 1).to_bytes()
    assert not IncrementalCompatibleFrameParser().feed(wire)
    assert len(IncrementalCompatibleFrameParser(include_v3=True).feed(wire)) == 1


def test_configure_options_and_contradictions():
    with ThingDAQ.simulated(protocol_version=3) as daq:
        applied = daq.configure(
            adc=False, aux_bank_mode=1, source=legacy.Source.SYNTHETIC
        )
        assert applied.settings.stream_mask == c.StreamMask.GPIO
        assert applied.settings.gpio_width_bits == 16
        assert applied.settings.source == c.Source.SYNTHETIC
        for options in (
            {"source": True},
            {"rate_profile": True},
            {"checksum_algorithm": True},
        ):
            with pytest.raises(TypeError):
                daq.configure(**options)
        with pytest.raises(ValueError, match="do not combine"):
            daq.configure(daq.capabilities.defaults, gpio=False)
        assert daq.get_settings() == applied


@pytest.mark.parametrize(
    "bad_command",
    [c.CommandKind.CONFIGURE, c.CommandKind.GET_SETTINGS, c.CommandKind.START],
)
def test_contradictory_applied_echo_is_rejected_and_close_stops(
    monkeypatch, bad_command
):
    class WrongEcho(SimulatedV3Device):
        tamper = False

        def _reply(self, kind, request_id, value=None, error=c.ErrorCode.OK):
            if (
                self.tamper
                and kind == bad_command
                and isinstance(value, V3AppliedSettings)
            ):
                changed = raw600(value.settings)
                value = V3AppliedSettings(
                    changed, V3Clocks.for_profile(changed.cpu_profile)
                )
            return super()._reply(kind, request_id, value, error)

    device = WrongEcho()
    monkeypatch.setattr("thingdone_daq.client.SimulatedV3Device", lambda: device)
    with ThingDAQ.simulated(protocol_version=3) as daq:
        device.tamper = True
        with pytest.raises(UnexpectedMessageError):
            daq.start() if bad_command == c.CommandKind.START else daq.configure()
    assert device.state == c.DeviceState.STOPPED


@pytest.mark.parametrize("strict", [False, True])
def test_decompressed_queue_loss_remains_visible(strict):
    with ThingDAQ.simulated(
        protocol_version=3, strict=strict, max_buffered_blocks=1, stream_interval=0.001
    ) as daq:
        daq.start()
        for _ in range(6):
            daq.transport.request_stream_frame()
        deadline = monotonic() + 2
        while daq.reader_counters.host_block_queue_drops < 3 and monotonic() < deadline:
            sleep(0.001)
        assert daq.reader_counters.host_block_queue_drops >= 3
        if strict:
            with pytest.raises(UnexpectedHostQueueLossError):
                daq.read_block()
        else:
            assert isinstance(daq.read_block(), HostQueueLoss)


def test_missing_compressed_frame_retains_sequence_and_logical_loss(monkeypatch):
    class MissingFrame(SimulatedV3Device):
        def next_data_frame(self):
            wire = super().next_data_frame()
            if wire is not None:
                header = decode_v3_frame(wire).header
                if header.kind == c.FrameKind.ADC_DATA and header.sequence == 0:
                    return super().next_data_frame()
            return wire

    monkeypatch.setattr("thingdone_daq.client.SimulatedV3Device", MissingFrame)
    with ThingDAQ.simulated(protocol_version=3, strict=True) as daq:
        daq.start()
        assert isinstance(daq.read_block(), GPIOBlock)
        with pytest.raises(UnexpectedStreamGapError) as error:
            daq.read_block()
        assert error.value.gap.missing_frames == 1
        assert error.value.gap.missing_items == c.MAX_ADC_PAIRS
        assert error.value.block.run_id == daq.run_id


class VariableFrames(SimulatedV3Device):
    """Legal short frames: changing logical counts must not invent item loss."""

    drop_second = False

    def next_data_frame(self):
        from thingdone_daq.protocol_v3 import (
            encode_adc_payload,
            encode_gpio_payload,
            encode_v3_frame,
        )

        if self.state != c.DeviceState.RUNNING or self._pending_data:
            return None
        adc = self.settings.stream_mask == c.StreamMask.ADC
        index = 0 if adc else 1
        sequence, first = self._frames[index], self._items[index]
        count = (3, 5, 2, 4)[sequence % 4]
        self._frames[index] += 1
        self._items[index] += count
        if self.drop_second and sequence == 1:
            self._frames_dropped[index] += 1
            self._items_dropped[index] += count
            return self.next_data_frame()
        payload = (
            encode_adc_payload(
                [(0xABC, 0x123)] * count, policy=self.settings.adc_policy
            )
            if adc
            else encode_gpio_payload(
                [0x12] * count,
                width_bits=self.settings.gpio_width_bits,
                policy=self.settings.gpio_policy,
            )
        )
        flags = c.FrameFlag.EPOCH_START if sequence == 0 else c.FrameFlag(0)
        if self.drop_second and sequence == 2:
            flags |= c.FrameFlag.GAP_BEFORE
        return encode_v3_frame(
            c.FrameKind.ADC_DATA if adc else c.FrameKind.GPIO_DATA,
            payload,
            run_id=self.run_id,
            sequence=sequence,
            first_sample_ticks=first * 8,
            item_count=count,
            flags=flags,
        )


@pytest.mark.parametrize("adc,width", [(True, 8), (False, 8), (False, 16)])
def test_variable_frames_use_timestamps_for_missing_items(monkeypatch, adc, width):
    device = VariableFrames()
    device.drop_second = True
    monkeypatch.setattr("thingdone_daq.client.SimulatedV3Device", lambda: device)
    with ThingDAQ.simulated(protocol_version=3, strict=True) as daq:
        daq.configure(adc=adc, gpio=not adc, aux_bank_mode=int(width == 16))
        daq.start()
        first = daq.read_block()
        assert first.item_count == 3
        with pytest.raises(UnexpectedStreamGapError) as error:
            daq.read_block()
        gap = error.value.gap
        assert gap.missing_frames == 1 and gap.missing_items == 5
        assert gap.sequence_inferred_items is None
        assert gap.firmware_evidence.consistent
        assert error.value.block.first_sample_ticks == 64
        from thingdone_daq import StreamGap

        assert StreamGap.between(first, error.value.block).missing_items == 5


def test_variable_frames_queue_losses_aggregate_exact_logical_units(monkeypatch):
    monkeypatch.setattr("thingdone_daq.client.SimulatedV3Device", VariableFrames)
    with ThingDAQ.simulated(protocol_version=3, max_buffered_blocks=1) as daq:
        daq.configure(gpio=False)
        daq.start()
        for _ in range(4):
            daq.transport.request_stream_frame()
        deadline = monotonic() + 2
        while daq.reader_counters.adc_frames_received < 4 and monotonic() < deadline:
            sleep(0.001)
        loss = daq.read_block()
        assert isinstance(loss, HostQueueLoss)
        assert loss.dropped_blocks == 3 and loss.dropped_items == 10
        assert loss.contiguous and loss.end_sample_ticks == 80
        block = daq.read_block()
        assert block.sequence == 3 and block.first_sample_ticks == 80


def test_stop_waits_for_partial_frame_drain(monkeypatch):
    from threading import Event

    from thingdone_daq.transport import InMemoryTransport

    partial, stopped = Event(), Event()
    states = []

    class DrainDevice(SimulatedV3Device):
        def _reply(self, kind, request_id, value=None, error=c.ErrorCode.OK):
            if kind == c.CommandKind.STOP:
                states.append(value.state)
                stopped.set()
            return super()._reply(kind, request_id, value, error)

    class PausingTransport(InMemoryTransport):
        def readinto(self, buffer):
            count = super().readinto(buffer)
            if self._pending_data_bytes and not partial.is_set():
                partial.set()
                assert stopped.wait(2)
            return count

    monkeypatch.setattr("thingdone_daq.client.SimulatedV3Device", DrainDevice)
    monkeypatch.setattr("thingdone_daq.client.InMemoryTransport", PausingTransport)
    with ThingDAQ.simulated(protocol_version=3, read_chunk_size=53) as daq:
        daq.start()
        daq.transport.request_stream_frame()
        assert partial.wait(2)
        assert daq.stop() == c.DeviceState.STOPPED
        assert states == [c.DeviceState.DRAINING]
        assert daq.status().pending_frames == 0
        assert daq.configure().settings == daq.capabilities.defaults
        assert daq.start() == 2
        assert daq.read_block().sequence == 0


@pytest.mark.parametrize(
    "counter",
    [
        "adc_codec_deadline_drops",
        "gpio_codec_resource_drops",
        "parser_errors",
        "transport_errors",
        "adc_dma_error_events",
        "adc_etc_error_events",
        "gpio_hardware_errors",
        "adc_raw_invariant_errors",
        "gpio_raw_invariant_errors",
        "packet_invalid_operations",
        "packet_encoding_rejections",
    ],
)
def test_strict_health_rejects_available_v3_diagnostics(counter):
    from thingdone_daq import UnexpectedStreamValidationError, snapshot_firmware_faults

    with ThingDAQ.simulated(protocol_version=3) as daq:
        baseline = daq.status()
        assert getattr(baseline, counter) is None
        assert daq.validate_stream_health(baseline) == baseline
        status = replace(baseline, **{counter: 7})
        faults = snapshot_firmware_faults(status)
        assert faults.first_fault.counter == counter
        assert faults.first_fault.value == 7
        with pytest.raises(UnexpectedStreamValidationError, match=counter):
            daq.validate_stream_health(status)
