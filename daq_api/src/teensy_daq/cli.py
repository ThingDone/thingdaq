"""Bounded command-line control plane for simulator and serial hardware."""

from __future__ import annotations

import argparse
import json
import signal
import sys
from collections.abc import Callable, Iterator
from contextlib import contextmanager
from dataclasses import fields, is_dataclass
from enum import Enum, IntEnum, IntFlag
from math import isfinite
from threading import current_thread, main_thread
from time import monotonic
from types import FrameType
from typing import TextIO

from ._generated import protocol_constants as constants
from .calibration import CalibrationError, CalibrationRecord, load_calibration
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
    UnexpectedHostQueueLossError,
    UnexpectedStreamAnomalyError,
    UnexpectedStreamGapError,
    UnexpectedStreamValidationError,
)
from .diagnostics import RunCounterReconciliation, reconcile_run_counters
from .discovery import (
    DeviceNotFoundError,
    DiscoveryError,
    DiscoveryProbeError,
    SerialPortCandidate,
    enumerate_candidates,
)
from .identity import ExpectedDeviceIdentity
from .models import (
    ADCBlock,
    DAQConfiguration,
    DeviceCapabilities,
    DeviceInfo,
    GPIOBlock,
    HostQueueLoss,
    LossCounters,
    Status,
    StreamAnomaly,
    StreamGap,
)
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
    COUNTER_INCONSISTENCY = 11
    INTERRUPTED = 130


class CaptureInterruptedError(TeensyDAQError):
    """A termination signal interrupted a bounded capture after safe cleanup."""

    def __init__(self, signal_name: str) -> None:
        super().__init__(f"capture interrupted by {signal_name}; STOP was attempted")
        self.signal_name = signal_name


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


def _gpio_pin(value: str) -> int:
    normalized = value.strip().upper()
    normalized = normalized.removeprefix("D")
    try:
        pin = int(normalized, 10)
    except ValueError as error:
        raise argparse.ArgumentTypeError(
            "GPIO channel must be one of D6 through D13"
        ) from error
    if pin not in constants.GPIO_PINS_BY_BIT:
        raise argparse.ArgumentTypeError("GPIO channel must be one of D6 through D13")
    return pin


def _add_output_arguments(parser: argparse.ArgumentParser) -> None:
    parser.add_argument(
        "--json",
        action="store_true",
        help="emit one machine-readable JSON object instead of human output",
    )


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
    parser.add_argument(
        "--adc-pair-rate-hz",
        type=int,
        help="require this exact INFO-advertised ADC pair rate before CONFIGURE",
    )
    parser.add_argument(
        "--gpio-sample-rate-hz",
        type=int,
        help="require this exact INFO-advertised GPIO rate before CONFIGURE",
    )
    parser.add_argument(
        "--adc-resolution-bits",
        type=int,
        help="require this exact INFO-advertised ADC resolution before CONFIGURE",
    )


def _add_capture_output_arguments(parser: argparse.ArgumentParser) -> None:
    parser.add_argument(
        "--strict-loss",
        action="store_true",
        help="fail on any stream gap, anomaly, host drop, or firmware loss counter",
    )
    parser.add_argument(
        "--adc-output",
        choices=("none", "raw", "calibrated"),
        default="raw",
        help="ADC sample preview representation (default: raw)",
    )
    parser.add_argument(
        "--calibration",
        metavar="PATH",
        help="explicit calibration JSON path required for calibrated ADC output",
    )
    parser.add_argument(
        "--calibration-hardware-serial",
        type=_unsigned_serial,
        help="record identity when INFO has no serial, such as simulator captures",
    )
    parser.add_argument(
        "--analog-front-end-profile",
        help="exact optional calibration profile key",
    )
    parser.add_argument(
        "--gpio-channel",
        action="append",
        type=_gpio_pin,
        default=[],
        metavar="D6..D13",
        help="show one selected GPIO channel; repeat for multiple channels",
    )
    parser.add_argument(
        "--sample-limit",
        type=int,
        default=4,
        help="maximum ADC pairs and GPIO samples to preview (default: 4; 0 disables)",
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
    _add_output_arguments(list_parser)
    list_parser.set_defaults(action="list")

    command_help = {
        "probe": "synchronize and print validated INFO",
        "status": "print decoded GET_STATUS state and counters",
        "reconcile": "prove firmware counter conservation and print fault evidence",
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
        _add_output_arguments(command_parser)
        command_parser.set_defaults(action=name)

    monitor_parser = commands.add_parser(
        "monitor",
        aliases=("capture",),
        help="run a bounded capture with live rates and health telemetry",
    )
    _add_connection_arguments(monitor_parser)
    _add_acquisition_arguments(monitor_parser)
    _add_capture_output_arguments(monitor_parser)
    _add_output_arguments(monitor_parser)
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
    strict = bool(getattr(arguments, "strict_loss", False))
    if arguments.simulate:
        return TeensyDAQ.simulated(
            control_only=False,
            strict=strict,
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
        strict=strict,
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
        adc_pair_rate_hz=arguments.adc_pair_rate_hz,
        gpio_sample_rate_hz=arguments.gpio_sample_rate_hz,
        adc_resolution_bits=arguments.adc_resolution_bits,
    )


def _format_value(value: object) -> str:
    if isinstance(value, (IntEnum, IntFlag)):
        if isinstance(value, IntFlag):
            return _flag_names(value, type(value))
        return value.name
    if isinstance(value, tuple):
        return ",".join(_format_value(item) for item in value)
    return str(value)


def _json_value(value: object) -> object:
    """Convert typed immutable models to stable JSON-compatible values."""

    if isinstance(value, Enum):
        return value.name if value.name is not None else int(value)
    if is_dataclass(value) and not isinstance(value, type):
        return {
            item.name: _json_value(getattr(value, item.name)) for item in fields(value)
        }
    if isinstance(value, dict):
        return {str(_json_value(key)): _json_value(item) for key, item in value.items()}
    if isinstance(value, (tuple, list)):
        return [_json_value(item) for item in value]
    if isinstance(value, (set, frozenset)):
        return [_json_value(item) for item in sorted(value, key=str)]
    if isinstance(value, (bytes, bytearray, memoryview)):
        return bytes(value).hex()
    return value


def _print_json(value: object, output: TextIO) -> None:
    print(
        json.dumps(
            _json_value(value),
            allow_nan=False,
            separators=(",", ":"),
            sort_keys=True,
        ),
        file=output,
    )


@contextmanager
def _capture_signal_handlers() -> Iterator[None]:
    """Turn SIGINT/SIGTERM into exceptions so capture finalizers can STOP."""

    if current_thread() is not main_thread():
        yield
        return

    previous: dict[
        signal.Signals,
        Callable[[int, FrameType | None], object] | int | None,
    ] = {}

    def interrupted(signum: int, _frame: FrameType | None) -> None:
        raise CaptureInterruptedError(signal.Signals(signum).name)

    try:
        for selected in (signal.SIGINT, signal.SIGTERM):
            previous[selected] = signal.getsignal(selected)
            signal.signal(selected, interrupted)
        yield
    finally:
        for selected, handler in previous.items():
            signal.signal(selected, handler)


def _capture_calibration(
    daq: TeensyDAQ,
    arguments: argparse.Namespace,
) -> tuple[CalibrationRecord | None, int | None]:
    calibrated = arguments.adc_output == "calibrated"
    calibration_options = (
        arguments.calibration,
        arguments.calibration_hardware_serial,
        arguments.analog_front_end_profile,
    )
    if not calibrated:
        if any(value is not None for value in calibration_options):
            raise ValueError("calibration options require --adc-output calibrated")
        return None, None
    if arguments.streams not in {"adc", "both"}:
        raise ValueError("calibrated ADC output requires an enabled ADC stream")
    if arguments.calibration is None:
        raise ValueError("--adc-output calibrated requires --calibration PATH")
    info = daq.device_info
    if info is None:
        raise DeviceSynchronizationError("open completed without INFO")
    hardware_serial = arguments.calibration_hardware_serial or info.hardware_serial
    if hardware_serial == 0:
        raise ValueError(
            "INFO has no calibration identity; pass "
            "--calibration-hardware-serial for simulator data"
        )
    record = load_calibration(
        arguments.calibration,
        hardware_serial,
        arguments.analog_front_end_profile,
        adc_resolution_bits=info.adc_resolution_bits,
        adc_code_range=(info.adc_code_min, info.adc_code_max),
        adc_input_range_volts=(
            info.adc_input_min_mv_nominal / 1000.0,
            info.adc_input_max_mv_nominal / 1000.0,
        ),
    )
    return record, hardware_serial


def _adc_preview(
    block: ADCBlock,
    count: int,
    calibration: CalibrationRecord | None,
    calibration_hardware_serial: int | None,
    analog_front_end_profile: str | None,
) -> list[dict[str, object]]:
    selected = min(count, block.item_count)
    calibrated_channels = None
    if calibration is not None:
        calibrated_channels = block.calibrated_channels(
            calibration,
            hardware_serial=calibration_hardware_serial,
            analog_front_end_profile=analog_front_end_profile,
        )
    rows: list[dict[str, object]] = []
    for index in range(selected):
        adc0_tick, adc1_tick = block.pair_ticks(index)
        adc0: dict[str, object] = {"raw_code": block.adc0[index]}
        adc1: dict[str, object] = {"raw_code": block.adc1[index]}
        if calibrated_channels is not None:
            adc0["voltage"] = calibrated_channels.adc0[index]
            adc1["voltage"] = calibrated_channels.adc1[index]
        rows.append(
            {
                "stream": "adc",
                "sequence": block.sequence,
                "pair_index": index,
                "adc0_timestamp_ticks": adc0_tick,
                "adc1_timestamp_ticks": adc1_tick,
                "adc0": adc0,
                "adc1": adc1,
                "calibrated": calibrated_channels is not None,
                "units": "V" if calibrated_channels is not None else "code",
            }
        )
    return rows


def _gpio_preview(
    block: GPIOBlock,
    count: int,
    pins: tuple[int, ...],
) -> list[dict[str, object]]:
    selected = min(count, block.item_count)
    channels = tuple((pin, block.channel(pin)) for pin in pins)
    return [
        {
            "stream": "gpio",
            "sequence": block.sequence,
            "sample_index": index,
            "timestamp_ticks": block.sample_ticks(index),
            "packed": block.sample(index),
            "channels": {f"D{pin}": channel[index] for pin, channel in channels},
        }
        for index in range(selected)
    ]


def _print_preview(rows: list[dict[str, object]], output: TextIO) -> None:
    for row in rows:
        if row["stream"] == "adc":
            adc0 = row["adc0"]
            adc1 = row["adc1"]
            assert isinstance(adc0, dict) and isinstance(adc1, dict)
            suffix = ""
            if row["calibrated"]:
                suffix = (
                    f" adc0_V={float(adc0['voltage']):.9g}"
                    f" adc1_V={float(adc1['voltage']):.9g}"
                )
            print(
                f"adc sequence={row['sequence']} pair={row['pair_index']} "
                f"adc0_ticks={row['adc0_timestamp_ticks']} "
                f"adc1_ticks={row['adc1_timestamp_ticks']} "
                f"adc0_raw={adc0['raw_code']} adc1_raw={adc1['raw_code']}"
                f" calibrated={str(row['calibrated']).lower()}{suffix}",
                file=output,
            )
            continue
        channels = row["channels"]
        assert isinstance(channels, dict)
        packed = row["packed"]
        assert isinstance(packed, int)
        selected_channels = " ".join(
            f"{pin}={int(bool(value))}" for pin, value in channels.items()
        )
        print(
            f"gpio sequence={row['sequence']} sample={row['sample_index']} "
            f"ticks={row['timestamp_ticks']} packed=0x{packed:02x}"
            + (f" {selected_channels}" if selected_channels else ""),
            file=output,
        )


def _print_loss_counters(losses: LossCounters, output: TextIO) -> None:
    firmware = losses.firmware
    host = losses.host
    print(
        "loss "
        f"firmware_adc_frames_dropped={firmware.adc_frames_dropped} "
        f"firmware_adc_items_dropped={firmware.adc_items_dropped} "
        f"firmware_gpio_frames_dropped={firmware.gpio_frames_dropped} "
        f"firmware_gpio_items_dropped={firmware.gpio_items_dropped} "
        f"firmware_parser_errors={firmware.parser_errors} "
        f"firmware_transport_errors={firmware.transport_errors} "
        f"host_block_queue_drops={host.host_block_queue_drops} "
        f"host_adc_block_queue_drops={host.adc_block_queue_drops} "
        f"host_gpio_block_queue_drops={host.gpio_block_queue_drops} "
        f"host_loss_report_queue_drops={host.loss_report_queue_drops} "
        f"observed_stream_gaps={losses.observed_stream_gaps} "
        f"observed_host_queue_losses={losses.observed_host_queue_losses} "
        f"observed_stream_anomalies={losses.observed_stream_anomalies}",
        file=output,
    )


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


def _print_reconciliation(
    report: RunCounterReconciliation,
    output: TextIO,
) -> None:
    """Print a stable, line-oriented conservation and fault report."""

    overall = "PASS" if report.exact else "FAIL"
    if report.first_inconsistent_counter is None and not report.exact:
        overall = "SATURATED"
    print(f"run_id={report.run_id}", file=output)
    print(f"stats_generation={report.stats_generation}", file=output)
    print(f"conservation={overall}", file=output)
    print(f"equation_count={len(report.equations)}", file=output)
    for index, equation in enumerate(report.equations):
        print(
            f"equation[{index:03d}]={equation.state.name} "
            f"counter={equation.counter} actual={equation.actual} "
            f'relation="{equation.relation}" expected={equation.expected} '
            f"difference={equation.difference} unit={equation.unit}",
            file=output,
        )
    print(
        "first_inconsistent_counter=" + (report.first_inconsistent_counter or "-"),
        file=output,
    )
    print(
        "first_indeterminate_counter=" + (report.first_indeterminate_counter or "-"),
        file=output,
    )
    print(f"fault_count={len(report.fault_snapshot.faults)}", file=output)
    for index, fault in enumerate(report.fault_snapshot.faults):
        print(
            f"fault[{index:03d}]={fault.counter} value={fault.value} "
            f"unit={fault.unit} category={fault.category}",
            file=output,
        )


def _print_configuration(
    configuration: DAQConfiguration,
    output: TextIO,
    *,
    state: constants.DeviceState = constants.DeviceState.CONFIGURED,
    capabilities: DeviceCapabilities | None = None,
) -> None:
    print(f"state={state.name}", file=output)
    print(f"profile={configuration.profile.name}", file=output)
    print(
        f"streams={_flag_names(configuration.stream_mask, constants.StreamMask)}",
        file=output,
    )
    print(f"source={configuration.source.name}", file=output)
    print(f"checksum={configuration.data_checksum_algorithm.name}", file=output)
    print(f"data_frame_bytes={configuration.data_frame_bytes}", file=output)
    if (
        capabilities is not None
        and configuration.stream_mask & constants.StreamMask.ADC
    ):
        print(f"adc_pair_rate_hz={capabilities.adc_pair_rate_hz}", file=output)
        print(f"adc_resolution_bits={capabilities.adc_resolution_bits}", file=output)
    if (
        capabilities is not None
        and configuration.stream_mask & constants.StreamMask.GPIO
    ):
        print(f"gpio_sample_rate_hz={capabilities.gpio_sample_rate_hz}", file=output)


def _configuration_details(
    configuration: DAQConfiguration,
    capabilities: DeviceCapabilities | None,
) -> dict[str, object]:
    """Return the echoed wire body plus active fixed-rate INFO metadata."""

    details: dict[str, object] = {
        "profile": configuration.profile,
        "stream_mask": configuration.stream_mask,
        "source": configuration.source,
        "data_checksum_algorithm": configuration.data_checksum_algorithm,
        "data_frame_bytes": configuration.data_frame_bytes,
    }
    if (
        capabilities is not None
        and configuration.stream_mask & constants.StreamMask.ADC
    ):
        details["adc_pair_rate_hz"] = capabilities.adc_pair_rate_hz
        details["adc_resolution_bits"] = capabilities.adc_resolution_bits
    if (
        capabilities is not None
        and configuration.stream_mask & constants.StreamMask.GPIO
    ):
        details["gpio_sample_rate_hz"] = capabilities.gpio_sample_rate_hz
    return details


def _run_monitor(
    daq: TeensyDAQ,
    arguments: argparse.Namespace,
    output: TextIO,
) -> dict[str, object]:
    command_latencies_ms: list[float] = []
    json_output = bool(arguments.json)
    preview_rows: list[dict[str, object]] = []
    adc_preview_count = 0
    gpio_preview_count = 0
    stopped: constants.DeviceState | None = None
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
        if not 0 <= arguments.sample_limit <= 1_024:
            raise ValueError("sample-limit must be between 0 and 1024")
        gpio_pins = tuple(arguments.gpio_channel)
        if len(set(gpio_pins)) != len(gpio_pins):
            raise ValueError("GPIO channel selections must be unique")
        calibration, calibration_hardware_serial = _capture_calibration(daq, arguments)

        command_started = monotonic()
        configuration = _configuration_from_arguments(daq, arguments)
        command_latencies_ms.append((monotonic() - command_started) * 1_000)
        if not json_output:
            _print_configuration(
                configuration,
                output,
                capabilities=daq.capabilities,
            )

        command_started = monotonic()
        run_id = daq.start()
        command_latencies_ms.append((monotonic() - command_started) * 1_000)
        if not json_output:
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
        host_queue_losses = 0
        stream_anomalies = 0
        adc_blocks = 0
        gpio_blocks = 0
        status_samples = 0
        last_status: Status | None = None

        while monotonic() < deadline:
            now = monotonic()
            if now >= next_status:
                command_started = monotonic()
                last_status = daq.status()
                latency_ms = (monotonic() - command_started) * 1_000
                command_latencies_ms.append(latency_ms)
                status_samples += 1
                sampled_at = monotonic()
                interval = max(sampled_at - previous_sample_at, 1e-9)
                adc_rate = (adc_bytes - previous_adc_bytes) / interval
                gpio_rate = (gpio_bytes - previous_gpio_bytes) / interval
                reader = daq.reader_counters
                if not json_output:
                    print(
                        f"sample elapsed_s={sampled_at - started_at:.3f} "
                        f"adc_payload_Bps={adc_rate:.0f} "
                        f"gpio_payload_Bps={gpio_rate:.0f} gaps={gaps} "
                        f"host_queue_losses={host_queue_losses} "
                        f"stream_anomalies={stream_anomalies} "
                        f"packet_ready_hwm={last_status.packet_ready_high_water} "
                        "packet_transmit_hwm="
                        f"{last_status.packet_transmit_high_water} "
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
            elif isinstance(item, HostQueueLoss):
                host_queue_losses += 1
            elif isinstance(item, StreamAnomaly):
                stream_anomalies += item.occurrences
            elif isinstance(item, ADCBlock):
                adc_bytes += len(item.payload_view)
                adc_blocks += 1
                if arguments.adc_output != "none":
                    rows = _adc_preview(
                        item,
                        arguments.sample_limit - adc_preview_count,
                        calibration,
                        calibration_hardware_serial,
                        arguments.analog_front_end_profile,
                    )
                    adc_preview_count += len(rows)
                    preview_rows.extend(rows)
                    if not json_output:
                        _print_preview(rows, output)
            elif isinstance(item, GPIOBlock):
                gpio_bytes += len(item.payload_view)
                gpio_blocks += 1
                rows = _gpio_preview(
                    item,
                    arguments.sample_limit - gpio_preview_count,
                    gpio_pins,
                )
                gpio_preview_count += len(rows)
                preview_rows.extend(rows)
                if not json_output:
                    _print_preview(rows, output)

        command_started = monotonic()
        last_status = daq.status()
        final_latency_ms = (monotonic() - command_started) * 1_000
        command_latencies_ms.append(final_latency_ms)
        elapsed = max(monotonic() - started_at, 1e-9)
        reader = daq.reader_counters
        summary: dict[str, object] = {
            "elapsed_seconds": elapsed,
            "adc_blocks": adc_blocks,
            "gpio_blocks": gpio_blocks,
            "adc_payload_bytes": adc_bytes,
            "gpio_payload_bytes": gpio_bytes,
            "adc_payload_bytes_per_second": adc_bytes / elapsed,
            "gpio_payload_bytes_per_second": gpio_bytes / elapsed,
            "gaps": gaps,
            "host_queue_losses": host_queue_losses,
            "stream_anomalies": stream_anomalies,
            "status_samples": status_samples,
            "packet_ready_high_water": last_status.packet_ready_high_water,
            "packet_transmit_high_water": last_status.packet_transmit_high_water,
            "host_block_queue_high_water": reader.block_queue_high_water,
            "host_block_queue_drops": reader.host_block_queue_drops,
            "command_latency_max_ms": max(command_latencies_ms),
        }
        if arguments.strict_loss:
            daq.validate_stream_health(last_status)
        if not json_output:
            print(
                f"summary elapsed_s={elapsed:.3f} "
                f"adc_payload_Bps={adc_bytes / elapsed:.0f} "
                f"gpio_payload_Bps={gpio_bytes / elapsed:.0f} gaps={gaps} "
                f"host_queue_losses={host_queue_losses} "
                f"stream_anomalies={stream_anomalies} "
                f"packet_ready_hwm={last_status.packet_ready_high_water} "
                "packet_transmit_hwm="
                f"{last_status.packet_transmit_high_water} "
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
        if daq.state in {
            constants.DeviceState.CONFIGURED,
            constants.DeviceState.RUNNING,
        }:
            try:
                stopped = daq.stop()
                if not json_output:
                    print(f"final_state={stopped.name}", file=output)
            except Exception:
                if not active_error:
                    raise

    command_started = monotonic()
    final_status = daq.status()
    command_latencies_ms.append((monotonic() - command_started) * 1_000)
    losses = daq.loss_counters(refresh=False)
    if arguments.strict_loss:
        daq.validate_stream_health(final_status)
    if not json_output:
        _print_loss_counters(losses, output)
    calibration_summary = None
    if calibration is not None:
        calibration_summary = {
            "schema_version": calibration.schema_version,
            "hardware_serial": calibration.hardware_serial,
            "analog_front_end_profile": calibration.analog_front_end_profile,
            "created_at": calibration.created_at.isoformat(),
            "provenance": calibration.provenance,
        }
    return {
        "command": arguments.command,
        "configuration": _configuration_details(configuration, daq.capabilities),
        "run_id": run_id,
        "adc_output": arguments.adc_output,
        "gpio_channels": [f"D{pin}" for pin in gpio_pins],
        "sample_preview": preview_rows,
        "summary": summary,
        "capture_status": last_status,
        "final_status": final_status,
        "final_state": None if stopped is None else stopped.name,
        "loss_counters": losses,
        "calibration": calibration_summary,
    }


def _execute(arguments: argparse.Namespace, output: TextIO) -> CliExitCode:
    json_output = bool(getattr(arguments, "json", False))
    if arguments.action == "list":
        candidates = enumerate_candidates()
        if json_output:
            _print_json(
                {
                    "command": "list",
                    "metadata_only": True,
                    "candidate_count": len(candidates),
                    "candidates": candidates,
                },
                output,
            )
        else:
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
            if json_output:
                _print_json({"command": arguments.command, "info": info}, output)
            else:
                _print_info(info, output)
        elif arguments.action == "status":
            status = daq.status()
            if json_output:
                _print_json(
                    {"command": "status", "run_id": daq.run_id, "status": status},
                    output,
                )
            else:
                _print_status(status, daq.run_id, output)
        elif arguments.action == "reconcile":
            reconciliation = reconcile_run_counters(daq.status(), run_id=daq.run_id)
            if json_output:
                _print_json(
                    {
                        "command": "reconcile",
                        "exact": reconciliation.exact,
                        "report": reconciliation,
                    },
                    output,
                )
            else:
                _print_reconciliation(reconciliation, output)
            if not reconciliation.exact:
                return CliExitCode.COUNTER_INCONSISTENCY
        elif arguments.action == "configure":
            applied_configuration = _configuration_from_arguments(daq, arguments)
            if json_output:
                _print_json(
                    {
                        "command": "configure",
                        "state": daq.state,
                        "applied_configuration": _configuration_details(
                            applied_configuration,
                            daq.capabilities,
                        ),
                    },
                    output,
                )
            else:
                _print_configuration(
                    applied_configuration,
                    output,
                    capabilities=daq.capabilities,
                )
        elif arguments.action == "monitor":
            with _capture_signal_handlers():
                capture_report = _run_monitor(daq, arguments, output)
            if json_output:
                _print_json(capture_report, output)
        elif arguments.action == "start":
            run_id = daq.start()
            started_configuration = daq.configuration
            if started_configuration is None:
                raise DeviceSynchronizationError(
                    "START completed without an applied configuration"
                )
            if json_output:
                _print_json(
                    {
                        "command": "start",
                        "state": daq.state,
                        "run_id": run_id,
                        "applied_configuration": _configuration_details(
                            started_configuration,
                            daq.capabilities,
                        ),
                    },
                    output,
                )
            else:
                _print_configuration(
                    started_configuration,
                    output,
                    state=constants.DeviceState.RUNNING,
                    capabilities=daq.capabilities,
                )
                print(f"run_id={run_id}", file=output)
        elif arguments.action == "stop":
            state = daq.stop()
            if json_output:
                _print_json({"command": "stop", "state": state}, output)
            else:
                print(f"state={state.name}", file=output)
        elif arguments.action == "reset-stats":
            generation = daq.reset_stats()
            if json_output:
                _print_json(
                    {
                        "command": "reset-stats",
                        "stats_generation": generation,
                        "state": daq.state,
                    },
                    output,
                )
            else:
                print(f"stats_generation={generation}", file=output)
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
    if any(isinstance(item, CaptureInterruptedError) for item in causes):
        return CliExitCode.INTERRUPTED, "interrupted"
    if any(
        isinstance(
            item,
            (
                UnexpectedHostQueueLossError,
                UnexpectedStreamAnomalyError,
                UnexpectedStreamGapError,
                UnexpectedStreamValidationError,
            ),
        )
        for item in causes
    ):
        return CliExitCode.COUNTER_INCONSISTENCY, "loss-detected"
    if any(isinstance(item, CalibrationError) for item in causes):
        return CliExitCode.DEVICE_ERROR, "calibration"
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


def _diagnostic_hint(category: str) -> str:
    return {
        "busy-port": "close the process holding the serial port and retry",
        "calibration": "check the explicit path, serial, profile, and ADC format",
        "device-busy": "STOP the active owner or retry after it releases the device",
        "disconnected": "check the USB cable and rediscover the hardware serial",
        "interrupted": "the capture was stopped and the serial handle was closed",
        "invalid-state": "run INFO/STATUS and complete the required lifecycle step",
        "loss-detected": "inspect firmware and host loss counters before retrying",
        "no-device": "connect the device, check permissions, or pass --hardware-serial",
        "open-failed": "check the port path, permissions, and USB connection",
        "synchronization": "allow the device to finish booting and retry INFO",
        "timeout": "check the connection or increase --timeout",
        "unsupported-capability": "use a profile advertised by INFO",
        "wrong-device": "select the expected hardware serial and firmware identity",
    }.get(category, "run INFO and STATUS, then retry with an explicit target")


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
        hint = _diagnostic_hint(category)
        if bool(getattr(arguments, "json", False)):
            _print_json(
                {
                    "ok": False,
                    "exit_code": int(exit_code),
                    "error": {
                        "category": category,
                        "type": type(error).__name__,
                        "message": str(error),
                        "hint": hint,
                    },
                },
                sys.stderr,
            )
        else:
            print(f"ERROR [{category}] {error}; hint: {hint}", file=sys.stderr)
        return int(exit_code)


if __name__ == "__main__":  # pragma: no cover - exercised by console entry point
    raise SystemExit(main())


__all__ = ["CaptureInterruptedError", "CliExitCode", "build_parser", "main"]
