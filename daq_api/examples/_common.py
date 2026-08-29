"""Shared target selection and exact protocol-v1 configuration for examples."""

from __future__ import annotations

import argparse

from teensy_daq import (
    ChecksumAlgorithm,
    DAQConfiguration,
    DeviceInfo,
    Source,
    StreamMask,
    TeensyDAQ,
)

EXPECTED_ADC_PAIR_RATE_HZ = 1_000_000
EXPECTED_GPIO_SAMPLE_RATE_HZ = 4_000_000
EXPECTED_ADC_RESOLUTION_BITS = 12


def _hardware_serial(value: str) -> int:
    try:
        serial = int(value, 10)
    except ValueError as error:
        raise argparse.ArgumentTypeError(
            "hardware serial must be a decimal integer"
        ) from error
    if not 0 < serial <= 0xFFFFFFFF:
        raise argparse.ArgumentTypeError(
            "hardware serial must be a nonzero decimal uint32"
        )
    return serial


def example_parser(description: str) -> argparse.ArgumentParser:
    parser = argparse.ArgumentParser(description=description)
    parser.add_argument(
        "--real",
        action="store_true",
        help="use an attached Teensy 4.0; the simulator is the default",
    )
    parser.add_argument(
        "--hardware-serial",
        type=_hardware_serial,
        help="stable INFO serial to select when --real is used",
    )
    return parser


def open_example(arguments: argparse.Namespace, *, strict: bool = False) -> TeensyDAQ:
    """Open a simulator by default, or an explicitly requested physical target."""

    if arguments.hardware_serial is not None and not arguments.real:
        raise ValueError("--hardware-serial requires --real")
    if arguments.real:
        return TeensyDAQ.open(
            hardware_serial=arguments.hardware_serial,
            strict=strict,
        )
    return TeensyDAQ.simulated(strict=strict)


def require_info(daq: TeensyDAQ) -> DeviceInfo:
    info = daq.device_info
    if info is None:
        raise RuntimeError("open completed without a synchronized INFO response")
    return info


def configure_exact(
    daq: TeensyDAQ,
    arguments: argparse.Namespace,
    *,
    adc: bool,
    gpio: bool,
    checksum: ChecksumAlgorithm = ChecksumAlgorithm.ADLER32,
) -> DAQConfiguration:
    """Require the fixed user-facing v1 rates/resolution before CONFIGURE."""

    return daq.configure(
        adc=adc,
        gpio=gpio,
        source=Source.HARDWARE if arguments.real else Source.SYNTHETIC,
        checksum_algorithm=checksum,
        adc_pair_rate_hz=EXPECTED_ADC_PAIR_RATE_HZ if adc else None,
        gpio_sample_rate_hz=EXPECTED_GPIO_SAMPLE_RATE_HZ if gpio else None,
        adc_resolution_bits=EXPECTED_ADC_RESOLUTION_BITS if adc else None,
    )


def print_applied(daq: TeensyDAQ, configuration: DAQConfiguration) -> None:
    capabilities = daq.capabilities
    if capabilities is None:
        raise RuntimeError("applied configuration has no INFO capabilities")
    streams = []
    if configuration.stream_mask & StreamMask.ADC:
        streams.append("ADC")
    if configuration.stream_mask & StreamMask.GPIO:
        streams.append("GPIO")
    print(
        "applied_configuration="
        f"profile:{configuration.profile.name},"
        f"streams:{'+'.join(streams) or 'NONE'},"
        f"source:{configuration.source.name},"
        f"checksum:{configuration.data_checksum_algorithm.name},"
        f"frame_bytes:{configuration.data_frame_bytes}"
    )
    if configuration.stream_mask & StreamMask.ADC:
        print(
            f"applied_adc=rate_hz:{capabilities.adc_pair_rate_hz},"
            f"resolution_bits:{capabilities.adc_resolution_bits}"
        )
    if configuration.stream_mask & StreamMask.GPIO:
        print(f"applied_gpio=rate_hz:{capabilities.gpio_sample_rate_hz}")


def print_target(arguments: argparse.Namespace, info: DeviceInfo) -> None:
    mode = "hardware" if arguments.real else "simulator"
    print(
        f"mode={mode} board={info.board_id.name} "
        f"hardware_serial={info.hardware_serial} build_id={info.build_id}"
    )
