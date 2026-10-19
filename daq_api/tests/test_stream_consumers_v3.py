"""Decoded v3 consumers, wire accounting, and negotiated stream invariants."""

import builtins
import struct
from dataclasses import replace

import pytest
from thingdone_daq import (
    ADCBlock,
    BackgroundReader,
    DAQConfiguration,
    EquationState,
    GPIOBlock,
    InMemoryTransport,
    ReaderProtocolError,
    ThingDAQ,
    TimestampAligner,
    TimestampAlignmentError,
    reconcile_run_counters,
    snapshot_firmware_faults,
)
from thingdone_daq._generated import protocol_constants as legacy
from thingdone_daq._generated import protocol_v3_constants as c
from thingdone_daq.models_v3 import V3Settings, V3Status
from thingdone_daq.protocol import encode_frame
from thingdone_daq.protocol_v2 import IncrementalCompatibleFrameParser, encode_v2_frame
from thingdone_daq.protocol_v3 import (
    decode_data_payload,
    decode_v3_block,
    decode_v3_frame,
    encode_adc_payload,
    encode_gpio_payload,
    encode_v3_frame,
)
from thingdone_daq.simulator_v3 import SimulatedV3Device


def block_wire(*, adc=True, policy=1, width=8, count=37, first=80):
    payload = (
        encode_adc_payload([(0xABC, 0x123)] * count, policy=policy)
        if adc
        else encode_gpio_payload(
            [0x81 if width == 8 else 0xA581] * count,
            width_bits=width,
            policy=policy,
        )
    )
    return encode_v3_frame(
        c.FrameKind.ADC_DATA if adc else c.FrameKind.GPIO_DATA,
        payload,
        run_id=7,
        sequence=3,
        first_sample_ticks=first,
        item_count=count,
    )


def block(*, adc=True, policy=1, width=8, count=37, first=80):
    settings = replace(
        V3Settings.defaults(),
        aux_bank_mode=c.AuxBankMode.INPUT if width == 16 else c.AuxBankMode.DISABLED,
        gpio_width_bits=width,
        adc_policy=c.AdcPolicy(policy) if adc else c.AdcPolicy.PACK12,
        gpio_policy=c.GpioPolicy(policy) if not adc else c.GpioPolicy.RLE_AUTO,
    )
    wire = block_wire(adc=adc, policy=policy, width=width, count=count, first=first)
    return decode_v3_block(decode_v3_frame(wire), settings), wire


@pytest.mark.parametrize("adc,width", [(True, 8), (False, 8), (False, 16)])
@pytest.mark.parametrize("policy", [0, 1])
def test_views_keep_logical_shape_timing_and_actual_encoding(adc, width, policy):
    value, wire = block(adc=adc, policy=policy, width=width)
    assert value.item_count == 37
    assert value.first_sample_ticks == 80
    assert value.end_tick_exclusive == 80 + 37 * 8
    assert value.decoded_bytes == 37 * (4 if adc else width // 8)
    assert value.wire_bytes == len(wire)
    assert (
        value.encoded_sample_bytes
        == len(wire) - c.MIN_FRAME_BYTES - c.DATA_PREFIX_BYTES
    )
    assert (
        value.encoding == (c.Encoding.ADC_PACK12 if adc else c.Encoding.GPIO_RLE)
        if policy
        else value.encoding == c.Encoding.RAW
    )
    if adc:
        assert list(value.adc0) == [0xABC] * 37
        assert list(value.adc1) == [0x123] * 37
        assert value.adc1_phase_ticks == 4 and value.pair_period_ticks == 8
    else:
        assert value.sample_period_ticks == 8
        assert [value.sample(i) for i in range(37)] == [
            0x81 if width == 8 else 0xA581
        ] * 37
    # The current aligner rejects the equal-rate profile even for short frames.
    with pytest.raises(TimestampAlignmentError, match="per-sample timestamps"):
        TimestampAligner().push(value)
    with pytest.raises(ValueError, match="Adler-32"):
        replace(value, checksum_algorithm=legacy.ChecksumAlgorithm.CRC32C)


@pytest.mark.parametrize("adc,width", [(True, 8), (False, 8), (False, 16)])
@pytest.mark.parametrize("policy", [0, 1])
def test_optional_numpy_views_use_decoded_storage(adc, width, policy):
    np = pytest.importorskip("numpy")
    value, _ = block(adc=adc, policy=policy, width=width)
    view = value.as_numpy()
    assert view.payload_owner is value.payload
    if adc:
        assert view.pairs.tolist() == [[0xABC, 0x123]] * 37
        assert view.pairs.shape == (37, 2)
        assert not view.pairs.flags.writeable
        from thingdone_daq.numpy import adc_timestamps

        assert adc_timestamps(value).tolist() == [
            [80 + i * 8, 84 + i * 8] for i in range(37)
        ]
        assert np.shares_memory(view.adc0, view.adc1) is False
    else:
        assert view.packed.tolist() == [0x81 if width == 8 else 0xA581] * 37
        assert not view.packed.flags.writeable
        assert view.timestamps().tolist() == [80 + i * 8 for i in range(37)]
        for pin in value.pins_by_bit:
            assert view.channel(pin).values.tolist() == list(value.channel(pin))


def test_pack12_all_codes_against_independent_literal_packing_without_numpy(
    monkeypatch,
):
    original_import = builtins.__import__

    def no_numpy(name, *args, **kwargs):
        if name.split(".")[0] == "numpy":
            raise AssertionError("NumPy must remain optional")
        return original_import(name, *args, **kwargs)

    monkeypatch.setattr(builtins, "__import__", no_numpy)
    for offset in range(0, 4096, c.MAX_ADC_PAIRS):
        pairs = [
            (i, 4095 - i) for i in range(offset, min(offset + c.MAX_ADC_PAIRS, 4096))
        ]
        packed = b"".join(((a | (b << 12)).to_bytes(3, "little")) for a, b in pairs)
        prefix = struct.pack(
            c.DATA_PREFIX_STRUCT_FORMAT, c.Encoding.ADC_PACK12, 4, 0, len(pairs) * 4, 0
        )
        actual = decode_data_payload(c.FrameKind.ADC_DATA, prefix + packed, len(pairs))
        assert actual.payload == b"".join(struct.pack("<HH", a, b) for a, b in pairs)
    value, _ = block()
    assert list(value.adc1) == [0x123] * 37


@pytest.mark.parametrize("width", [8, 16])
def test_public_stream_metrics_mixed_encoding_and_interleaved_control(width):
    with ThingDAQ.simulated(protocol_version=3, strict=True) as daq:
        daq.configure(aux_bank_mode=int(width == 16))
        daq.start()
        before = daq.reader_counters
        blocks = []
        for _ in range(8):
            blocks.append(daq.read_block())
            status = daq.status()
            assert reconcile_run_counters(status).exact
            assert snapshot_firmware_faults(status).clear
            assert daq.get_settings().settings == daq.configuration
        after = daq.reader_counters
        for cls, stream in ((ADCBlock, "adc"), (GPIOBlock, "gpio")):
            selected = [b for b in blocks if isinstance(b, cls)]
            for metric, expected in (
                ("frames", len(selected)),
                ("items", sum(b.item_count for b in selected)),
                ("decoded_bytes", sum(b.decoded_bytes for b in selected)),
                ("wire_bytes", sum(b.wire_bytes for b in selected)),
            ):
                name = f"{stream}_{metric}_received"
                assert getattr(after, name) - getattr(before, name) == expected
        assert [b.encoding for b in blocks if isinstance(b, GPIOBlock)] == [
            c.Encoding.GPIO_RLE,
            c.Encoding.RAW,
        ] * 2
        daq.stop()
        assert daq.start() == 2
        assert daq.read_block().first_sample_ticks == 0


@pytest.mark.parametrize(
    "selected,observed", [(1, 2), (1, 3), (2, 1), (2, 3), (3, 1), (3, 2)]
)
def test_reader_rejects_unnegotiated_data_versions(selected, observed):
    settings = V3Settings.defaults()
    legacy_config = DAQConfiguration(legacy.StreamMask.ADC, legacy.Source.HARDWARE)
    if observed == 3:
        wire = block_wire()
    else:
        encoder = encode_frame if observed == 1 else encode_v2_frame
        wire = encoder(
            legacy.FrameKind.ADC_DATA,
            bytes(4048),
            run_id=7,
            item_count=1012,
            flags=legacy.FrameFlag.EPOCH_START,
        )
    device = SimulatedV3Device()
    incoming = iter((wire,))
    device.next_data_frame = lambda: next(incoming, None)
    transport = InMemoryTransport(device=device)
    with BackgroundReader(
        transport, parser=IncrementalCompatibleFrameParser(include_v3=True)
    ) as reader:
        if selected == 3:
            reader.activate_v3_run(7, settings)
        else:
            reader.activate_run(
                7, configuration=legacy_config, protocol_version=selected
            )
        transport.request_stream_frame()
        with pytest.raises(ReaderProtocolError, match="unnegotiated data wire version"):
            reader.get_block(timeout=1)
        assert reader.counters.adc_frames_received == 0


@pytest.mark.parametrize("adc", [True, False])
def test_reader_rejects_compression_against_raw_policy(adc):
    settings = replace(
        V3Settings.defaults(), adc_policy=c.AdcPolicy.RAW, gpio_policy=c.GpioPolicy.RAW
    )
    device = SimulatedV3Device()
    device.next_data_frame = lambda: block_wire(adc=adc)
    transport = InMemoryTransport(device=device)
    with BackgroundReader(
        transport, parser=IncrementalCompatibleFrameParser(include_v3=True)
    ) as reader:
        reader.activate_v3_run(7, settings)
        transport.request_stream_frame()
        with pytest.raises(ReaderProtocolError) as caught:
            reader.get_block(timeout=1)
        assert "encoding differs from policy" in str(caught.value.cause)


def test_v3_diagnostics_keep_logical_loss_and_do_not_invent_wire_counts():
    status = V3Status(c.DeviceState.STOPPED, 9, 0, 3, 1, 21, 5, 4, 1, 110, 19)
    report = reconcile_run_counters(status)
    assert report.exact and report.run_id == 9
    assert report.stats_generation is None
    assert len(report.equations) == 5
    faults = report.fault_snapshot
    assert [(f.counter, f.value) for f in faults.faults] == [
        ("adc_items_dropped", 5),
        ("gpio_items_dropped", 19),
        ("adc_frames_dropped", 1),
        ("gpio_frames_dropped", 1),
    ]
    assert (
        reconcile_run_counters(
            replace(status, pending_frames=6)
        ).first_inconsistent_counter
        == "pending_frames"
    )
    assert (
        reconcile_run_counters(
            replace(status, adc_items_dropped=22)
        ).first_inconsistent_counter
        == "adc_items_dropped"
    )
    saturated = reconcile_run_counters(
        replace(status, adc_items_produced=legacy.UINT64_MAX)
    )
    assert saturated.equations[1].state is EquationState.SATURATED
    with pytest.raises(ValueError, match="run_id"):
        reconcile_run_counters(status, run_id=10)


def test_cached_v3_loss_diagnostics_survive_stop_and_reset_on_start(monkeypatch):
    device = SimulatedV3Device()
    monkeypatch.setattr("thingdone_daq.client.SimulatedV3Device", lambda: device)
    with ThingDAQ.simulated(protocol_version=3) as daq:
        daq.start()
        daq.read_block()
        device._items_dropped[0] = 5
        device._frames_dropped[0] = 1
        current = daq.loss_counters()
        assert current.firmware.adc_items_dropped == 5
        assert daq.loss_counters(refresh=False).firmware == current.firmware
        daq.stop()
        assert daq.loss_counters(refresh=False).firmware == current.firmware
        daq.start()
        assert not daq.loss_counters(refresh=False).has_loss


@pytest.mark.parametrize("version", [1, 2])
@pytest.mark.parametrize("checksum", legacy.SUPPORTED_CHECKSUM_ALGORITHMS)
def test_legacy_checksums_and_received_wire_metrics(version, checksum):
    config = DAQConfiguration(legacy.StreamMask.ADC, legacy.Source.HARDWARE, checksum)
    encoder = encode_frame if version == 1 else encode_v2_frame
    wire = encoder(
        legacy.FrameKind.ADC_DATA,
        bytes(4048),
        run_id=7,
        item_count=1012,
        flags=legacy.FrameFlag.EPOCH_START,
        checksum_algorithm=checksum,
    )
    device = SimulatedV3Device()
    incoming = iter((wire,))
    device.next_data_frame = lambda: next(incoming, None)
    transport = InMemoryTransport(device=device)
    with BackgroundReader(transport) as reader:
        reader.activate_run(7, checksum, config, protocol_version=version)
        transport.request_stream_frame()
        value = reader.get_block(timeout=1)
        assert value.encoding == c.Encoding.RAW
        assert value.checksum_algorithm == checksum
        assert reader.counters.adc_items_received == 1012
        assert reader.counters.adc_decoded_bytes_received == 4048
        assert reader.counters.adc_wire_bytes_received == len(wire)


@pytest.mark.parametrize("adc,width", [(True, 8), (False, 8), (False, 16)])
@pytest.mark.parametrize("policy", [0, 1])
def test_stop_tail_decodes_and_accounts_without_delivering(
    monkeypatch, adc, width, policy
):
    class TailDevice(SimulatedV3Device):
        tail = None

        def receive(self, data):
            responses = super().receive(data)
            if (
                responses
                and decode_v3_frame(responses[0]).header.kind
                == c.FrameKind.STOP_RESPONSE
                and self.tail is not None
            ):
                responses += (self.tail,)
                self.tail = None
            return responses

    device = TailDevice()
    monkeypatch.setattr("thingdone_daq.client.SimulatedV3Device", lambda: device)
    with ThingDAQ.simulated(protocol_version=3, read_chunk_size=17) as daq:
        daq.configure(
            aux_bank_mode=int(width == 16), adc_policy=policy, gpio_policy=policy
        )
        daq.start()
        frame = decode_v3_frame(block_wire(adc=adc, width=width, policy=policy))
        device.tail = encode_v3_frame(
            frame.header.kind,
            frame.payload,
            run_id=daq.run_id,
            sequence=3,
            first_sample_ticks=80,
            item_count=37,
        )
        tail_size = len(device.tail)
        daq.stop()
        # A subsequent matched response fences all bytes preceding it.
        daq.status()
        stream = "adc" if adc else "gpio"
        counters = daq.reader_counters
        assert getattr(counters, f"{stream}_stale_blocks_discarded") == 1
        assert getattr(counters, f"{stream}_items_received") == 37
        assert getattr(counters, f"{stream}_wire_bytes_received") == tail_size
        assert counters.queued_blocks == 0
        daq.start()
        assert daq.read_block().first_sample_ticks == 0


@pytest.mark.parametrize("width", [8, 16])
@pytest.mark.parametrize("adc_policy,gpio_policy", [(0, 0), (0, 1), (1, 0), (1, 1)])
def test_synthetic_soak_uses_actual_block_sizes(width, adc_policy, gpio_policy):
    from thingdone_daq.streaming import run_synthetic_soak

    with ThingDAQ.simulated(protocol_version=3, strict=True) as daq:
        daq.configure(
            aux_bank_mode=int(width == 16),
            adc_policy=adc_policy,
            gpio_policy=gpio_policy,
        )
        result = run_synthetic_soak(daq, frame_count=8, status_frame_interval=2)
        assert result.reconciliation.ok
        assert result.final_status.state == c.DeviceState.STOPPED
        assert result.reconciliation.adc_firmware_frames_emitted is None
        assert result.reconciliation.firmware_parser_errors is None
        assert result.reconciliation.firmware_transport_errors is None
        assert result.adc.item_count == 4 * c.MAX_ADC_PAIRS
        assert result.gpio.item_count == 4 * c.MAX_LOGICAL_PAYLOAD_BYTES // (width // 8)
        assert result.adc.decoded_bytes == result.gpio.decoded_bytes == 4 * 4048
        assert result.adc.payload_bytes == 4 * (
            12 + c.MAX_ADC_PAIRS * (3 if adc_policy else 4)
        )
        assert result.gpio.payload_bytes == (
            4 * (12 + 4048)
            if gpio_policy == 0
            else 4 * 12 + 2 * (2 + width // 8) + 2 * 4048
        )
        for metrics, stream in ((result.adc, "adc"), (result.gpio, "gpio")):
            assert metrics.framed_bytes == metrics.payload_bytes + 4 * c.MIN_FRAME_BYTES
            assert metrics.framed_bytes == getattr(
                result.reader_counters, f"{stream}_wire_bytes_received"
            )
        assert daq.configuration.adc_policy == adc_policy
        assert daq.configuration.gpio_policy == gpio_policy


@pytest.mark.parametrize("fault", ["loss", "frame_counter", "run_id"])
def test_v3_soak_rejects_bad_status_and_stops(monkeypatch, fault):
    from thingdone_daq import UnexpectedStreamValidationError
    from thingdone_daq.streaming import run_synthetic_soak

    class BadStatus(SimulatedV3Device):
        def _reply(self, kind, request_id, value=None, error=c.ErrorCode.OK):
            if (
                kind == c.CommandKind.GET_STATUS
                and isinstance(value, V3Status)
                and value.run_id != self.run_id
            ):
                return encode_v3_frame(
                    c.FrameKind.GET_STATUS_RESPONSE,
                    value.to_payload(),
                    run_id=value.run_id,
                    request_id=request_id,
                )
            return super()._reply(kind, request_id, value, error)

        def status(self):
            value = super().status()
            if self.state == c.DeviceState.RUNNING and value.adc_frames_produced:
                if fault == "loss":
                    value = replace(value, adc_items_dropped=1)
                elif fault == "frame_counter":
                    value = replace(value, adc_frames_produced=0)
                else:
                    value = replace(value, run_id=value.run_id + 1)
            return value

    device = BadStatus()
    monkeypatch.setattr("thingdone_daq.client.SimulatedV3Device", lambda: device)
    with ThingDAQ.simulated(protocol_version=3) as daq:
        with pytest.raises((UnexpectedStreamValidationError, ReaderProtocolError)):
            run_synthetic_soak(daq, frame_count=4, status_frame_interval=2)
        assert device.state == c.DeviceState.STOPPED
