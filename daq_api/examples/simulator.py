"""Run a complete deterministic acquisition without serial hardware."""

from __future__ import annotations

from thingdaq import ADCBlock, ChecksumAlgorithm, GPIOBlock, ThingDAQ


def main() -> int:
    print("example=simulator physical_required=false deterministic=true")
    with ThingDAQ.simulated(strict=True) as daq:
        applied = daq.configure(
            adc=True,
            gpio=True,
            checksum_algorithm=ChecksumAlgorithm.CRC32C,
            adc_pair_rate_hz=1_000_000,
            gpio_sample_rate_hz=4_000_000,
            adc_resolution_bits=12,
        )
        print(
            f"applied_profile={applied.profile.name} "
            f"checksum={applied.data_checksum_algorithm.name}"
        )
        run_id = daq.start()
        for item in daq.blocks(2):
            if isinstance(item, ADCBlock):
                print(f"adc_pair0={item.pair(0)} sequence={item.sequence}")
            elif isinstance(item, GPIOBlock):
                print(f"gpio_byte0=0x{item.sample(0):02x} sequence={item.sequence}")
            else:
                raise TypeError(f"strict simulator emitted {type(item).__name__}")
        status = daq.validate_stream_health()
        print(
            f"run_id={run_id} state={status.device_state.name} "
            f"adc_frames={status.adc_frames_emitted} "
            f"gpio_frames={status.gpio_frames_emitted}"
        )
        daq.stop()
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
