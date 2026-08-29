"""Bounded command-line control plane for simulator and serial hardware."""

from __future__ import annotations

import argparse
import sys
from dataclasses import fields
from enum import IntEnum, IntFlag
from math import isfinite
from time import monotonic
from typing import TextIO

from ._generated import protocol_constants as constants
from .client import (
    BlockTimeoutError,
    CommandTimeoutError,
    DAQStateError,
    DeviceCapabilityError,
    DeviceCommandError,
    DeviceIdentityMismatchError,
    DeviceSynchronizationError,
    MultipleDevicesFoundError,
    TeensyDAQ,
    TeensyDAQError,
)
from .discovery import (
    DeviceNotFoundError,
    DiscoveryError,
    DiscoveryProbeError,
    SerialPortCandidate,
    enumerate_candidates,
)
from .identity import ExpectedDeviceIdentity
from .models import ADCBlock, DAQConfiguration, DeviceInfo, GPIOBlock, Status, StreamGap
from .protocol import ProtocolError
from .reader import DeviceDisconnectedError, ReaderError, ReaderProtocolError
from .transport import (
    SerialPortBusyError,
    TransportDisconnectedError,
    TransportError,
    TransportOpenError,
    TransportTimeoutError,
)


class CliExitCode(IntEnum):
    """Stable process status categories for scripts and human diagnostics."""

    OK = 0
    NO_DEVICE = 3
    TIMEOUT = 4
    BUSY_PORT = 5
    WRONG_DEVICE = 6
    UNSUPPORTED_CAPABILITY = 7
    DISCONNECTED = 8
    INVALID_STATE = 9
    DEVICE_ERROR = 10


def _unsigned_serial(value: str) -> int:
    try:
        parsed = int(value, 10)
    except ValueError as error:
        raise argparse.ArgumentTypeError(
            "hardware serial must be a decimal uint32"
        ) from error
    if not 0 <= parsed <= constants.UINT32_MAX:
        raise argparse.ArgumentTypeError("hardware serial must be a decimal uint32")
    return parsed


def _semantic_version(value: str) -> tuple[int, int, int]:
    parts = value.split(".")
    if len(parts) != 3:
        raise argparse.ArgumentTypeError("firmware version must be MAJOR.MINOR.PATCH")
    try:
        parsed = tuple(int(part, 10) for part in parts)
    except ValueError as error:
        raise argparse.ArgumentTypeError(
            "firmware version must be MAJOR.MINOR.PATCH"
        ) from error
    if any(not 0 <= part <= 0xFF for part in parsed):
        raise argparse.ArgumentTypeError("firmware version fields must fit uint8")
    return parsed[0], parsed[1], parsed[2]


def _add_connection_arguments(parser: argparse.ArgumentParser) -> None:
    parser.add_argument("--port", help="current COM or /dev path")
    parser.add_argument(
        "--hardware-serial",
        type=_unsigned_serial,
        help="stable decimal hardware serial to select or verify",
    )
    parser.add_argument(
        "--expect-build-id",
        help="exact INFO build ID required before any operation",
    )
    parser.add_argument(
        "--expect-firmware",
        type=_semantic_version,
        metavar="MAJOR.MINOR.PATCH",
        help="exact semantic firmware version required before any operation",
    )
    parser.add_argument(
        "--timeout",
        type=float,
        default=1.0,
        help="finite serial and command timeout in seconds (default: 1.0)",
    )
    parser.add_argument(
        "--sync-attempts",
        type=int,
        default=4,
        help="maximum INFO synchronization attempts (default: 4)",
    )
    parser.add_argument(
        "--sync-retry-delay",
        type=float,
        default=0.05,
        help="delay between retryable INFO attempts (default: 0.05)",
    )
    parser.add_argument(
        "--simulate",
        action="store_true",
        help="use the in-memory synthetic-stream simulator",
    )


def _add_acquisition_arguments(parser: argparse.ArgumentParser) -> None:
    parser.add_argument(
        "--streams",
        choices=("adc", "gpio", "both", "none"),
        default="both",
        help="requested stream set (default: both)",
    )
    parser.add_argument(
        "--source",
        choices=("hardware", "synthetic"),
        help="requested source, or auto-select an advertised profile",
    )
    parser.add_argument(
        "--checksum",
        choices=("adler32", "crc32c", "crc32-iso-hdlc"),
        default="adler32",
        help="data-frame checksum (default: adler32)",
    )


def build_parser() -> argparse.ArgumentParser:
    """Build the public parser without opening serial hardware."""

    parser = argparse.ArgumentParser(
        prog="teensy-daq",
        description="Inspect and control Teensy DAQ protocol-v1 devices.",
    )
    commands = parser.add_subparsers(dest="command", required=True)

    list_parser = commands.add_parser(
        "list", help="list metadata-filtered Teensy USB Serial candidates"
    )
    list_parser.set_defaults(action="list")

    command_help = {
        "probe": "synchronize and print validated INFO",
        "status": "print decoded GET_STATUS state and counters",
        "configure": "atomically apply one advertised acquisition profile",
        "start": "start the previously configured run",
        "stop": "idempotently return the device to IDLE",
        "reset-stats": "reset counters only in IDLE or CONFIGURED",
    }
    aliases = {"probe": ["info"], "configure": ["configure-control-only"]}
    for name, help_text in command_help.items():
        command_parser = commands.add_parser(
            name,
            aliases=aliases.get(name, ()),
            help=help_text,
        )
        _add_connection_arguments(command_parser)
        if name == "configure":
            _add_acquisition_arguments(command_parser)
        command_parser.set_defaults(action=name)

    monitor_parser = commands.add_parser(
        "monitor",
        aliases=("capture",),
        help="run a bounded capture with live rates and health telemetry",
    )
    _add_connection_arguments(monitor_parser)
    _add_acquisition_arguments(monitor_parser)
    monitor_parser.add_argument(
        "--duration",
        type=float,
        default=5.0,
        help="bounded capture duration in seconds (default: 5.0)",
    )
    monitor_parser.add_argument(
        "--status-interval",
        type=float,
        default=1.0,
        help="live STATUS cadence in seconds (default: 1.0)",
    )
    monitor_parser.add_argument(
        "--block-timeout",
        type=float,
        default=0.25,
        help="maximum wait per decoded block in seconds (default: 0.25)",
    )
    monitor_parser.set_defaults(action="monitor")
    return parser


def _candidate_for_port(port: str) -> SerialPortCandidate | str:
    return next(
        (candidate for candidate in enumerate_candidates() if candidate.port == port),
        port,
    )


def _open_device(arguments: argparse.Namespace) -> TeensyDAQ:
    if arguments.timeout <= 0:
        raise ValueError("timeout must be positive")
    if arguments.sync_attempts < 2:
        raise ValueError("sync attempts must be at least two")
    if arguments.sync_retry_delay < 0:
        raise ValueError("sync retry delay must be nonnegative")
    if arguments.simulate and (
        arguments.port is not None or arguments.hardware_serial is not None
    ):
        raise ValueError("--simulate cannot be combined with a hardware target")

    expected = ExpectedDeviceIdentity(
        hardware_serial=arguments.hardware_serial,
        firmware_version=arguments.expect_firmware,
        build_id=arguments.expect_build_id,
    )
    if arguments.simulate:
        return TeensyDAQ.simulated(
            control_only=False,
            command_timeout=arguments.timeout,
            block_timeout=arguments.timeout,
            shutdown_timeout=arguments.timeout,
            expected_identity=expected,
            synchronization_attempts=arguments.sync_attempts,
            synchronization_retry_delay=arguments.sync_retry_delay,
        )

    device: SerialPortCandidate | str | None
    if arguments.port is not None:
        device = _candidate_for_port(arguments.port)
    else:
        device = None
    return TeensyDAQ.open(
        device,
        hardware_serial=(arguments.hardware_serial if device is None else None),
        expected_identity=expected,
        discovery_timeout=arguments.timeout,
        serial_open_timeout=arguments.timeout,
        serial_read_timeout=min(0.05, arguments.timeout),
        serial_write_timeout=arguments.timeout,
        serial_flush_timeout=arguments.timeout,
        serial_close_timeout=arguments.timeout,
        command_timeout=arguments.timeout,
        block_timeout=arguments.timeout,
        shutdown_timeout=arguments.timeout,
        synchronization_attempts=arguments.sync_attempts,
        synchronization_retry_delay=arguments.sync_retry_delay,
    )


def _flag_names(value: IntFlag, enum_type: type[IntFlag]) -> str:
    names = [
        member.name
        for member in enum_type
        if member.name is not None and int(member) != 0 and int(value) & int(member)
    ]
    return ",".join(names) if names else "NONE"


def _source_names(mask: int) -> str:
    names = [source.name for source in constants.Source if mask & (1 << int(source))]
    return ",".join(names) if names else "NONE"


def _configuration_from_arguments(
    daq: TeensyDAQ,
    arguments: argparse.Namespace,
) -> DAQConfiguration:
    stream_masks = {
        "adc": constants.StreamMask.ADC,
        "gpio": constants.StreamMask.GPIO,
        "both": constants.StreamMask.ADC | constants.StreamMask.GPIO,
        "none": constants.StreamMask.NONE,
    }
    checksum_algorithms = {
        "adler32": constants.ChecksumAlgorithm.ADLER32,
        "crc32c": constants.ChecksumAlgorithm.CRC32C,
        "crc32-iso-hdlc": constants.ChecksumAlgorithm.CRC32_ISO_HDLC,
    }
    stream_mask = stream_masks[arguments.streams]
    checksum = checksum_algorithms[arguments.checksum]
    source = (
        None if arguments.source is None else constants.Source[arguments.source.upper()]
    )
    return daq.configure(
        adc=bool(stream_mask & constants.StreamMask.ADC),
        gpio=bool(stream_mask & constants.StreamMask.GPIO),
        source=source,
        checksum_algorithm=checksum,
    )


def _format_value(value: object) -> str:
    if isinstance(value, (IntEnum, IntFlag)):
        if isinstance(value, IntFlag):
            return _flag_names(value, type(value))
        return value.name
    if isinstance(value, tuple):
        return ",".join(_format_value(item) for item in value)
    return str(value)


def _print_info(info: DeviceInfo, output: TextIO) -> None:
    firmware = ".".join(str(part) for part in info.firmware_version)
    print(f"state={info.device_state.name}", file=output)
    print(f"protocol_version={info.protocol_version}", file=output)
    print(f"firmware_version={firmware}", file=output)
    print(f"build_id={info.build_id}", file=output)
    print(f"hardware_serial={info.hardware_serial}", file=output)
    print(f"board={info.board_id.name}", file=output)
    print(f"mcu={info.mcu_id.name}", file=output)
    print(
        "streams=" + _flag_names(info.supported_stream_mask, constants.StreamMask),
        file=output,
    )
    print(f"sources={_source_names(info.supported_source_mask)}", file=output)
    print(
        "capabilities=" + _flag_names(info.capability_bits, constants.Capability),
        file=output,
    )
    print(f"checksum_mask=0x{info.supported_checksum_mask:08x}", file=output)
    print(
        "configuration_profiles="
        + _flag_names(
            info.supported_configuration_mask,
            constants.ConfigurationProfile,
        ),
        file=output,
    )
    print(
        "applied_streams="
        + _flag_names(info.applied_stream_mask, constants.StreamMask),
        file=output,
    )
    print(f"applied_source={info.applied_source.name}", file=output)
    print(f"checksum={info.data_checksum_algorithm.name}", file=output)
    print(f"data_frame_bytes={info.data_frame_bytes}", file=output)
    print(f"data_payload_bytes={info.data_payload_bytes}", file=output)
    print(f"max_control_frame_bytes={info.max_control_frame_bytes}", file=output)
    print(f"timestamp_hz={info.timestamp_hz}", file=output)
    print(f"adc_resolution_bits={info.adc_resolution_bits}", file=output)
    print(f"adc_pair_rate_hz={info.adc_pair_rate_hz}", file=output)
    print(f"adc_pair_period_ticks={info.adc_pair_period_ticks}", file=output)
    print(f"adc1_phase_ticks={info.adc1_phase_ticks}", file=output)
    print(f"adc_pairs_per_frame={info.adc_pairs_per_frame}", file=output)
    print(f"adc_pairs_per_buffer={info.adc_pairs_per_buffer}", file=output)
    print(f"adc_dma_ring_depth={info.adc_dma_ring_depth}", file=output)
    print(f"adc_dma_ring_bytes={info.adc_dma_ring_bytes}", file=output)
    print("adc_pins=" + ",".join(map(str, info.adc_pins)), file=output)
    print(
        "adc_edma_channels=" + ",".join(map(str, info.adc_edma_channels)),
        file=output,
    )
    print(
        "adc_dmamux_sources=" + ",".join(map(str, info.adc_dmamux_sources)),
        file=output,
    )
    print(f"gpio_sample_rate_hz={info.gpio_sample_rate_hz}", file=output)
    print(f"gpio_sample_period_ticks={info.gpio_sample_period_ticks}", file=output)
    print(f"gpio_samples_per_frame={info.gpio_samples_per_frame}", file=output)
    print(f"gpio_packed_width_bits={info.gpio_packed_width_bits}", file=output)
    print("gpio_pin_map=" + ",".join(map(str, info.gpio_pin_map)), file=output)
    print(f"gpio_raw_ring_depth={info.gpio_raw_ring_depth}", file=output)
    print(f"gpio_packed_ring_depth={info.gpio_packed_ring_depth}", file=output)
    print(f"gpio_packet_buffer_count={info.gpio_packet_buffer_count}", file=output)
    print(f"packet_buffer_count={info.packet_buffer_count}", file=output)
    print(f"packet_primary_count={info.packet_primary_count}", file=output)
    print(f"packet_reserve_count={info.packet_reserve_count}", file=output)
    print(
        f"packet_ready_queue_capacity={info.packet_ready_queue_capacity}",
        file=output,
    )
    print(
        f"packet_transmit_queue_capacity={info.packet_transmit_queue_capacity}",
        file=output,
    )
    print(f"command_queue_capacity={info.command_queue_capacity}", file=output)
    print(f"response_queue_capacity={info.response_queue_capacity}", file=output)
    print(
        f"gpio_capture_diagnostic_mode={info.gpio_capture_diagnostic_mode.name}",
        file=output,
    )


def _print_status(status: Status, run_id: int, output: TextIO) -> None:
    print(f"run_id={run_id}", file=output)
    for status_field in fields(status):
        value = getattr(status, status_field.name)
        print(f"{status_field.name}={_format_value(value)}", file=output)


def _print_configuration(configuration: DAQConfiguration, output: TextIO) -> None:
    print("state=CONFIGURED", file=output)
    print(f"profile={configuration.profile.name}", file=output)
    print(
        f"streams={_flag_names(configuration.stream_mask, constants.StreamMask)}",
        file=output,
    )
    print(f"source={configuration.source.name}", file=output)
    print(f"checksum={configuration.data_checksum_algorithm.name}", file=output)


def _run_monitor(
    daq: TeensyDAQ,
    arguments: argparse.Namespace,
    output: TextIO,
) -> None:
    command_latencies_ms: list[float] = []
    active_error = False
    try:
        for name in ("duration", "status_interval", "block_timeout"):
            value = getattr(arguments, name)
            if not isinstance(value, (int, float)) or not isfinite(value) or value <= 0:
                raise ValueError(
                    f"{name.replace('_', '-')} must be finite and positive"
                )
        if arguments.duration > 3_600:
            raise ValueError("duration must not exceed 3600 seconds")

        command_started = monotonic()
        configuration = _configuration_from_arguments(daq, arguments)
        command_latencies_ms.append((monotonic() - command_started) * 1_000)
        _print_configuration(configuration, output)

        command_started = monotonic()
        run_id = daq.start()
        command_latencies_ms.append((monotonic() - command_started) * 1_000)
        print("state=RUNNING", file=output)
        print(f"run_id={run_id}", file=output)

        started_at = monotonic()
        deadline = started_at + float(arguments.duration)
        next_status = started_at
        previous_sample_at = started_at
        previous_adc_bytes = 0
        previous_gpio_bytes = 0
        adc_bytes = 0
        gpio_bytes = 0
        gaps = 0
        last_status: Status | None = None

        while monotonic() < deadline:
            now = monotonic()
            if now >= next_status:
                command_started = monotonic()
                last_status = daq.status()
                latency_ms = (monotonic() - command_started) * 1_000
                command_latencies_ms.append(latency_ms)
                sampled_at = monotonic()
                interval = max(sampled_at - previous_sample_at, 1e-9)
                adc_rate = (adc_bytes - previous_adc_bytes) / interval
                gpio_rate = (gpio_bytes - previous_gpio_bytes) / interval
                reader = daq.reader_counters
                print(
                    f"sample elapsed_s={sampled_at - started_at:.3f} "
                    f"adc_payload_Bps={adc_rate:.0f} "
                    f"gpio_payload_Bps={gpio_rate:.0f} gaps={gaps} "
                    f"packet_ready_hwm={last_status.packet_ready_high_water} "
                    f"packet_transmit_hwm={last_status.packet_transmit_high_water} "
                    f"host_block_queue_hwm={reader.block_queue_high_water} "
                    f"command_latency_ms={latency_ms:.3f}",
                    file=output,
                    flush=True,
                )
                previous_sample_at = sampled_at
                previous_adc_bytes = adc_bytes
                previous_gpio_bytes = gpio_bytes
                next_status = sampled_at + float(arguments.status_interval)

            now = monotonic()
            wait = min(
                float(arguments.block_timeout),
                max(deadline - now, 0.0),
                max(next_status - now, 0.0),
            )
            if wait <= 0:
                continue
            try:
                item = daq.read_block(timeout=wait)
            except BlockTimeoutError:
                continue
            if isinstance(item, StreamGap):
                gaps += 1
            elif isinstance(item, ADCBlock):
                adc_bytes += len(item.payload_view)
            elif isinstance(item, GPIOBlock):
                gpio_bytes += len(item.payload_view)

        command_started = monotonic()
        last_status = daq.status()
        final_latency_ms = (monotonic() - command_started) * 1_000
        command_latencies_ms.append(final_latency_ms)
        elapsed = max(monotonic() - started_at, 1e-9)
        reader = daq.reader_counters
        print(
            f"summary elapsed_s={elapsed:.3f} "
            f"adc_payload_Bps={adc_bytes / elapsed:.0f} "
            f"gpio_payload_Bps={gpio_bytes / elapsed:.0f} gaps={gaps} "
            f"packet_ready_hwm={last_status.packet_ready_high_water} "
            f"packet_transmit_hwm={last_status.packet_transmit_high_water} "
            f"host_block_queue_hwm={reader.block_queue_high_water} "
            f"host_block_queue_drops={reader.host_block_queue_drops} "
            f"command_latency_max_ms={max(command_latencies_ms):.3f}",
            file=output,
            flush=True,
        )
    except BaseException:
        active_error = True
        raise
    finally:
        try:
            stopped = daq.stop()
            print(f"final_state={stopped.name}", file=output)
        except Exception:
            if not active_error:
                raise


def _execute(arguments: argparse.Namespace, output: TextIO) -> CliExitCode:
    if arguments.action == "list":
        candidates = enumerate_candidates()
        print(f"candidate_count={len(candidates)}", file=output)
        for candidate in candidates:
            print(
                f"port={candidate.port} vid=0x{candidate.vid:04x} "
                f"pid=0x{candidate.pid:04x} "
                f"usb_serial={candidate.serial_number or '-'} "
                f"product={candidate.product or '-'} "
                f"location={candidate.location or '-'}",
                file=output,
            )
        return CliExitCode.OK

    daq = _open_device(arguments)
    active_error = False
    try:
        if arguments.action == "probe":
            info = daq.device_info
            if info is None:
                raise DeviceSynchronizationError("open completed without INFO")
            _print_info(info, output)
        elif arguments.action == "status":
            _print_status(daq.status(), daq.run_id, output)
        elif arguments.action == "configure":
            configuration = _configuration_from_arguments(daq, arguments)
            _print_configuration(configuration, output)
        elif arguments.action == "monitor":
            _run_monitor(daq, arguments, output)
        elif arguments.action == "start":
            run_id = daq.start()
            print("state=RUNNING", file=output)
            print(f"run_id={run_id}", file=output)
        elif arguments.action == "stop":
            print(f"state={daq.stop().name}", file=output)
        elif arguments.action == "reset-stats":
            print(f"stats_generation={daq.reset_stats()}", file=output)
        else:  # pragma: no cover - argparse constrains action
            raise AssertionError(f"unknown CLI action {arguments.action!r}")
        return CliExitCode.OK
    except BaseException:
        active_error = True
        raise
    finally:
        try:
            daq.close(stop=False)
        except Exception:
            if not active_error:
                raise


def _causes(error: BaseException) -> tuple[BaseException, ...]:
    found: list[BaseException] = []
    pending: list[BaseException] = [error]
    visited: set[int] = set()
    while pending:
        current = pending.pop()
        if id(current) in visited:
            continue
        visited.add(id(current))
        found.append(current)
        linked = getattr(current, "cause", None)
        for candidate in (linked, current.__cause__, current.__context__):
            if isinstance(candidate, BaseException):
                pending.append(candidate)
    return tuple(found)


def _diagnostic(error: BaseException) -> tuple[CliExitCode, str]:
    causes = _causes(error)
    if any(isinstance(item, DAQStateError) for item in causes):
        return CliExitCode.INVALID_STATE, "invalid-state"
    command_errors = [item for item in causes if isinstance(item, DeviceCommandError)]
    if any(item.error_code is constants.ErrorCode.BUSY for item in command_errors):
        return CliExitCode.BUSY_PORT, "device-busy"
    if any(
        item.error_code
        in {
            constants.ErrorCode.UNSUPPORTED_CONFIGURATION,
            constants.ErrorCode.UNSUPPORTED_CHECKSUM,
        }
        for item in command_errors
    ) or any(isinstance(item, DeviceCapabilityError) for item in causes):
        return CliExitCode.UNSUPPORTED_CAPABILITY, "unsupported-capability"
    if any(
        isinstance(item, (CommandTimeoutError, TransportTimeoutError))
        for item in causes
    ):
        return CliExitCode.TIMEOUT, "timeout"
    if any(isinstance(item, SerialPortBusyError) for item in causes):
        return CliExitCode.BUSY_PORT, "busy-port"
    if any(
        isinstance(
            item,
            (
                DeviceIdentityMismatchError,
                DiscoveryProbeError,
                ProtocolError,
                ReaderProtocolError,
            ),
        )
        for item in causes
    ):
        return CliExitCode.WRONG_DEVICE, "wrong-device"
    if any(
        isinstance(
            item,
            (
                DeviceDisconnectedError,
                TransportDisconnectedError,
            ),
        )
        for item in causes
    ):
        return CliExitCode.DISCONNECTED, "disconnected"
    if any(
        isinstance(item, (DeviceNotFoundError, MultipleDevicesFoundError))
        for item in causes
    ):
        return CliExitCode.NO_DEVICE, "no-device"
    if any(isinstance(item, DeviceSynchronizationError) for item in causes):
        return CliExitCode.TIMEOUT, "synchronization"
    if any(isinstance(item, TransportOpenError) for item in causes):
        return CliExitCode.DEVICE_ERROR, "open-failed"
    return CliExitCode.DEVICE_ERROR, "device-error"


def main(argv: list[str] | None = None) -> int:
    """Run one bounded CLI operation and return a stable diagnostic exit code."""

    arguments = build_parser().parse_args(argv)
    try:
        return int(_execute(arguments, sys.stdout))
    except (
        DiscoveryError,
        ProtocolError,
        ReaderError,
        TeensyDAQError,
        TransportError,
        TypeError,
        ValueError,
    ) as error:
        exit_code, category = _diagnostic(error)
        print(f"ERROR [{category}] {error}", file=sys.stderr)
        return int(exit_code)


if __name__ == "__main__":  # pragma: no cover - exercised by console entry point
    raise SystemExit(main())


__all__ = ["CliExitCode", "build_parser", "main"]
