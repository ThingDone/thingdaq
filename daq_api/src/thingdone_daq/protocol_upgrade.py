"""Demonstrate automatic v1/v2/v3 discovery and lossless capture offline.

Run from an installed package with:
    python -m thingdone_daq.protocol_upgrade
"""

from __future__ import annotations

import struct
from dataclasses import fields, replace

from thingdone_daq import (
    ADCBlock,
    DAQConfiguration,
    DeviceCapabilityError,
    DeviceCommandError,
    DeviceState,
    GPIOBlock,
    ThingDAQ,
    V3AppliedSettings,
    V3Info,
    V3Settings,
    V3Status,
)
from thingdone_daq._generated import protocol_v3_constants as c
from thingdone_daq.synthetic import (
    SyntheticGPIOPattern,
    synthetic_adc_payload,
    synthetic_gpio_payload,
    synthetic_v3_adc_payload,
)


def print_settings(label: str, settings: V3Settings) -> None:
    """Print every field of an exact advertised tuple in table-column order."""
    values = [getattr(settings, field.name) for field in fields(settings)]
    print(label, " ".join(str(getattr(value, "name", value)) for value in values))


def capture(daq: ThingDAQ, applied: V3AppliedSettings, rejected: V3Settings) -> None:
    """Validate two frames per stream, including adaptive RLE and RAW fallback."""
    run_id = daq.start()
    try:
        daq.configure(rejected)
    except DeviceCommandError as error:
        if error.error_code != c.ErrorCode.INVALID_STATE:
            raise
    else:
        raise AssertionError("running CONFIGURE unexpectedly succeeded")
    if daq.get_settings() != applied or daq.configuration != applied.settings:
        raise AssertionError("rejected CONFIGURE mutated active settings")
    print(f"run={run_id} running_reconfiguration=INVALID_STATE settings_unchanged=true")

    streams: dict[str, list[ADCBlock | GPIOBlock]] = {"adc": [], "gpio": []}
    for block in daq.blocks(4):
        if not isinstance(block, (ADCBlock, GPIOBlock)):
            raise TypeError(f"unexpected stream item: {type(block).__name__}")
        name = "adc" if isinstance(block, ADCBlock) else "gpio"
        sequence = len(streams[name])
        first = sequence * block.item_count
        if (
            block.protocol_version != 3
            or block.run_id != run_id
            or block.sequence != sequence
            or block.first_sample_ticks != first * c.ADC_PAIR_PERIOD_TICKS
            or block.flags & c.FrameFlag.GAP_BEFORE
        ):
            raise AssertionError(f"{name} run/sequence/timestamp/continuity mismatch")
        if isinstance(block, ADCBlock):
            expected = synthetic_v3_adc_payload(first, block.item_count)
            pairs = tuple(struct.iter_unpack("<HH", expected))
            if tuple(zip(block.adc0, block.adc1)) != pairs:
                raise AssertionError("ADC channel values differ from source samples")
            for offset in range(block.item_count):
                tick = (first + offset) * c.ADC_PAIR_PERIOD_TICKS
                if block.pair_ticks(offset) != (tick, tick + c.ADC1_PHASE_TICKS):
                    raise AssertionError("ADC sample timestamp mismatch")
            encoding = (
                c.Encoding.ADC_PACK12
                if applied.settings.adc_policy == c.AdcPolicy.PACK12
                else c.Encoding.RAW
            )
        else:
            pattern = (
                SyntheticGPIOPattern.ALL_ZERO
                if sequence % 2 == 0
                else SyntheticGPIOPattern.HIGH_TRANSITION
            )
            expected = synthetic_gpio_payload(
                first,
                block.item_count,
                aux_bank_mode=applied.settings.aux_bank_mode,
                pattern=pattern,
            )
            for offset in range(block.item_count):
                start = offset * block.item_bytes
                value = int.from_bytes(
                    expected[start : start + block.item_bytes], "little"
                )
                if (
                    block.sample(offset) != value
                    or block.sample_ticks(offset)
                    != (first + offset) * c.GPIO_SAMPLE_PERIOD_TICKS
                ):
                    raise AssertionError("GPIO sample value/timestamp mismatch")
            encoding = (
                c.Encoding.GPIO_RLE
                if applied.settings.gpio_policy == c.GpioPolicy.RLE_AUTO
                and sequence % 2 == 0
                else c.Encoding.RAW
            )
        if block.payload != expected:
            raise AssertionError(f"{name} decoded bytes differ from source samples")
        if block.encoded_payload is None or block.encoded_payload[0] != encoding:
            raise AssertionError(f"{name} encoding mismatch")
        streams[name].append(block)

    for name, blocks in streams.items():
        if len(blocks) != 2:
            raise AssertionError(f"expected two {name} frames")
        raw_bytes = sum(block.decoded_bytes for block in blocks)
        encoded_bytes = sum(block.encoded_sample_bytes for block in blocks)
        wire_bytes = sum(block.wire_bytes for block in blocks)
        print(
            f"run={run_id} stream={name} frames={len(blocks)} "
            f"items={sum(block.item_count for block in blocks)} equality=exact "
            f"raw_sample_bytes={raw_bytes} transmitted_sample_bytes={encoded_bytes} "
            f"transmitted_frame_bytes={wire_bytes}"
        )
        if name == "adc":
            print(
                f"run={run_id} adc_packing_saved_bytes={raw_bytes - encoded_bytes} "
                f"adc_packing_savings_percent={100 * (raw_bytes - encoded_bytes) / raw_bytes:.1f}"
            )
        else:
            rle_frames = sum(
                block.encoded_payload is not None
                and block.encoded_payload[0] == c.Encoding.GPIO_RLE
                for block in blocks
            )
            fallback_frames = (
                len(blocks) - rle_frames
                if applied.settings.gpio_policy == c.GpioPolicy.RLE_AUTO
                else 0
            )
            print(
                f"run={run_id} gpio_rle_frames={rle_frames} "
                f"gpio_raw_frames={len(blocks) - rle_frames} "
                f"gpio_fallback_frames={fallback_frames}"
            )

    daq.validate_stream_health()
    if daq.loss_counters().has_loss:
        raise AssertionError("capture reported loss")
    if daq.stop() != c.DeviceState.STOPPED:
        raise AssertionError("STOP did not finish draining")
    status = daq.status()
    if (
        not isinstance(status, V3Status)
        or status.state != c.DeviceState.STOPPED
        or status.pending_frames
    ):
        raise AssertionError("final status is not fully stopped")
    if daq.get_settings() != applied:
        raise AssertionError("STOP changed applied settings")
    print(f"run={run_id} state=STOPPED pending_frames=0 readback=exact loss=none")


def legacy_compatibility(version: int) -> None:
    """Negotiate an explicit legacy persona and verify its historical rates."""
    with ThingDAQ.simulated(protocol_version=version, strict=True) as daq:
        info = daq.device_info
        expected_gpio_rate = 4_000_000 if version == 1 else 1_000_000
        if info is None or info.protocol_version != version:
            raise AssertionError("automatic legacy negotiation selected wrong version")
        applied = daq.configure()
        if not isinstance(applied, DAQConfiguration) or (
            applied.adc_pair_rate_hz != 1_000_000
            or applied.gpio_sample_rate_hz != expected_gpio_rate
        ):
            raise AssertionError("legacy defaults changed")
        run_id = daq.start()
        counts = {"adc": 0, "gpio": 0}
        for block in daq.blocks(4):
            if not isinstance(block, (ADCBlock, GPIOBlock)):
                raise TypeError("unexpected legacy stream event")
            name = "adc" if isinstance(block, ADCBlock) else "gpio"
            first = counts[name] * block.item_count
            expected = (
                synthetic_adc_payload(first, block.item_count)
                if isinstance(block, ADCBlock)
                else synthetic_gpio_payload(first, block.item_count)
            )
            if (
                block.protocol_version != version
                or block.run_id != run_id
                or block.sequence != counts[name]
                or block.payload != expected
            ):
                raise AssertionError("legacy capture differs from source")
            counts[name] += 1
        if counts != {"adc": 2, "gpio": 2}:
            raise AssertionError("legacy capture missing a stream")
        daq.validate_stream_health()
        if daq.stop() != DeviceState.IDLE or daq.loss_counters().has_loss:
            raise AssertionError("legacy capture did not stop cleanly")
        if daq.info().protocol_version != version:
            raise AssertionError("STOP changed legacy wire version")
        transport, reader = daq.transport, daq.reader
    if transport.is_open or reader.is_running:
        raise AssertionError("legacy transport/reader did not close")
    print(
        f"compatibility persona=v{version} negotiated=v{version} "
        f"adc_pair_rate_hz=1000000 gpio_sample_rate_hz={expected_gpio_rate} "
        "equality=exact loss=none final_state=IDLE "
        "transport_closed=true reader_stopped=true PASS"
    )


def main() -> int:
    print(
        "example=protocol_upgrade simulated=true physical_required=false "
        "cpu_policy=fixed_600mhz hardware_throughput=not_measured"
    )
    with ThingDAQ.simulated(protocol_version=3, strict=True) as daq:
        info = daq.info()
        if not isinstance(info, V3Info) or not info.simulated:
            raise AssertionError("expected explicitly simulated v3 identity")
        print(
            f"board={info.board_id.name} mcu={info.mcu_id.name} "
            f"serial={info.hardware_serial} firmware={info.firmware_version} "
            f"build={info.build_id} protocol={info.protocol_version}"
        )
        capabilities = daq.get_capabilities()
        defaults = capabilities.defaults
        print("settings_columns:", " ".join(field.name for field in fields(defaults)))
        print_settings("defaults:", defaults)
        print(f"supported_tuples={len(capabilities.configurations)}")
        for index, settings in enumerate(capabilities.configurations):
            print_settings(f"tuple[{index:02d}]:", settings)
        print(
            f"max_data_frame_bytes={capabilities.max_data_frame_bytes} "
            f"max_logical_payload_bytes={capabilities.max_logical_payload_bytes} "
            "byte_counts=captured_data_only frame_bytes=header+prefix+samples+checksum"
        )
        raw = replace(
            defaults,
            gpio_policy=c.GpioPolicy.RAW,
            adc_policy=c.AdcPolicy.RAW,
        )
        capabilities.require_supported(raw)
        before = daq.get_settings()
        try:
            daq.configure(
                cpu_profile=c.CpuProfile.CPU_450MHZ,
                gpio_policy=c.GpioPolicy.RAW,
                adc_policy=c.AdcPolicy.RAW,
            )
        except DeviceCapabilityError:
            current_info = daq.info()
            if (
                not isinstance(current_info, V3Info)
                or daq.get_settings() != before
                or current_info.clocks != before.clocks
            ):
                raise AssertionError("unsupported CPU request mutated settings")
        else:
            raise AssertionError("nonadvertised CPU profile unexpectedly accepted")
        print("cpu_450mhz=not_advertised rejected=true settings_unchanged=true")
        for selection in (None, raw, None):
            applied = daq.configure() if selection is None else daq.configure(selection)
            expected = defaults if selection is None else selection
            current_info = daq.info()
            if (
                not isinstance(applied, V3AppliedSettings)
                or not isinstance(current_info, V3Info)
                or applied.settings != expected
                or daq.get_settings() != applied
                or current_info.clocks != applied.clocks
                or applied.clocks.cpu_clock_hz != 600_000_000
            ):
                raise AssertionError("stopped configuration/readback mismatch")
            clocks = applied.clocks
            print(
                f"applied_cpu_hz={clocks.cpu_clock_hz} ipg_hz={clocks.ipg_clock_hz} "
                f"adc_hz={clocks.adc_clock_hz} pit_hz={clocks.pit_clock_hz} "
                f"timestamp_hz={clocks.timestamp_hz} readback=exact"
            )
            capture(daq, applied, raw if selection is None else defaults)
        print("reset_to_defaults=true cpu_hz=600000000")
        transport, reader = daq.transport, daq.reader
    if transport.is_open or reader.is_running:
        raise AssertionError("transport/reader did not close")
    print("compatibility persona=v3 negotiated=v3 compressed_capture=exact PASS")
    for version in (1, 2):
        legacy_compatibility(version)
    print(
        "PASS runs=3 equality=exact final_state=STOPPED transport_closed=true reader_stopped=true"
    )
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
