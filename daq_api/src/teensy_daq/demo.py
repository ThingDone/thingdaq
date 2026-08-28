"""Executable, entirely offline demonstration of the public Teensy DAQ API."""

from __future__ import annotations

import argparse
import sys
from collections import deque
from collections.abc import Callable, Sequence
from typing import TextIO

from ._generated import protocol_constants as constants
from .client import TeensyDAQ, TeensyDAQError
from .models import (
    AdcBlock,
    AdcConverter,
    GpioBlock,
    Info,
    Status,
    StreamGap,
    interleave_adc,
)

DEFAULT_FRAME_COUNT = 2
MAX_FRAME_COUNT = 256
DEFAULT_PARSER_CHUNK_SIZE = 47
MAX_PARSER_CHUNK_SIZE = constants.DATA_FRAME_BYTES
_PREVIEW_ITEMS = 16
_JOIN_ITEMS = 4


class DemoValidationError(RuntimeError):
    """The offline device returned data that did not match its contract."""


def _require(condition: bool, message: str) -> None:
    if not condition:
        raise DemoValidationError(message)


def _require_equal(label: str, observed: object, expected: object) -> None:
    if observed != expected:
        raise DemoValidationError(
            f"{label}: expected {expected!r}, observed {observed!r}"
        )


def _bounded_integer(name: str, maximum: int) -> Callable[[str], int]:
    def parse(value: str) -> int:
        try:
            parsed = int(value)
        except ValueError as exc:
            raise argparse.ArgumentTypeError(f"{name} must be an integer") from exc
        if not 1 <= parsed <= maximum:
            raise argparse.ArgumentTypeError(f"{name} must be between 1 and {maximum}")
        return parsed

    return parse


def _names_from_mask(mask: int, values: type[constants.StreamMask]) -> str:
    names = [
        str(value.name)
        for value in values
        if value.value != 0 and mask & int(value.value)
    ]
    return "+".join(names) if names else "NONE"


def _source_names(info: Info) -> str:
    return "+".join(
        source.name for source in constants.Source if info.supports_source(source)
    )


def _checksum_names(info: Info) -> str:
    return "+".join(
        algorithm.name
        for algorithm in constants.ChecksumAlgorithm
        if algorithm is not constants.ChecksumAlgorithm.NONE_RESERVED
        and info.supported_checksum_mask & (1 << int(algorithm))
    )


def _validate_capabilities(info: Info) -> None:
    required_streams = constants.StreamMask.ADC | constants.StreamMask.GPIO
    _require_equal(
        "initial device state", info.device_state, constants.DeviceState.IDLE
    )
    _require_equal(
        "simulated board identity", info.board_id, constants.BoardId.SIMULATOR
    )
    _require_equal("simulated MCU identity", info.mcu_id, constants.McuId.SIMULATED)
    _require_equal(
        "protocol version", info.protocol_version, constants.PROTOCOL_VERSION
    )
    _require_equal("data frame size", info.data_frame_bytes, constants.DATA_FRAME_BYTES)
    _require_equal("timestamp frequency", info.timestamp_hz, constants.TIMESTAMP_HZ)
    _require(
        info.supported_stream_mask & required_streams == required_streams,
        "simulator did not advertise both ADC and GPIO streams",
    )
    _require(
        info.supports_source(constants.Source.SYNTHETIC),
        "simulator did not advertise the synthetic source",
    )
    _require(
        bool(
            info.supported_checksum_mask
            & (1 << int(constants.DEFAULT_CHECKSUM_ALGORITHM))
        ),
        "simulator did not advertise the default checksum",
    )


def _validate_common_block(
    block: AdcBlock | GpioBlock,
    *,
    run_id: int,
    sequence: int,
    first_sample_ticks: int,
) -> None:
    stream = "ADC" if isinstance(block, AdcBlock) else "GPIO"
    _require_equal(f"{stream} run ID", block.run_id, run_id)
    _require_equal(f"{stream} sequence", block.sequence, sequence)
    _require_equal(
        f"{stream} first-sample timestamp",
        block.first_sample_ticks,
        first_sample_ticks,
    )
    _require(
        bool(block.flags & constants.FrameFlag.SYNTHETIC),
        f"{stream} frame is missing the SYNTHETIC flag",
    )
    _require(
        not block.flags & constants.FrameFlag.GAP_BEFORE,
        f"{stream} frame unexpectedly reports a preceding gap",
    )
    expected_epoch_start = sequence == 0
    observed_epoch_start = bool(block.flags & constants.FrameFlag.EPOCH_START)
    _require_equal(
        f"{stream} epoch-start flag", observed_epoch_start, expected_epoch_start
    )


def _validate_adc_block(
    block: AdcBlock,
    *,
    run_id: int,
    sequence: int,
    previous: AdcBlock | None,
) -> tuple[list[int], tuple[int, ...]]:
    expected_ticks = sequence * constants.FRAME_COVERAGE_TICKS
    expected_first_pair = sequence * constants.ADC_PAIRS_PER_FRAME
    _validate_common_block(
        block,
        run_id=run_id,
        sequence=sequence,
        first_sample_ticks=expected_ticks,
    )
    _require_equal("ADC first pair index", block.first_pair_index, expected_first_pair)
    if previous is not None:
        _require_equal("ADC stream gap", StreamGap.between(previous, block), None)

    preview: list[int] = []
    tail: deque[int] = deque(maxlen=_JOIN_ITEMS)
    for interleaved_index, sample in enumerate(interleave_adc(block)):
        pair_offset, converter_offset = divmod(interleaved_index, 2)
        converter = AdcConverter(converter_offset)
        global_pair = expected_first_pair + pair_offset
        expected_tick = (
            expected_ticks
            + pair_offset * constants.ADC_PAIR_PERIOD_TICKS
            + converter_offset * constants.ADC1_PHASE_TICKS
        )
        _require_equal("ADC pair index", sample.pair_index, pair_offset)
        _require_equal("ADC converter order", sample.converter, converter)
        _require_equal("ADC sample timestamp", sample.timestamp_ticks, expected_tick)
        _require_equal(
            "ADC synthetic sample",
            sample.code,
            (2 * global_pair + converter_offset)
            & ((1 << constants.ADC_RESOLUTION_BITS) - 1),
        )
        if len(preview) < _PREVIEW_ITEMS:
            preview.append(sample.code)
        tail.append(sample.code)
    return preview, tuple(tail)


def _validate_gpio_block(
    block: GpioBlock,
    *,
    run_id: int,
    sequence: int,
    previous: GpioBlock | None,
) -> tuple[list[int], tuple[int, ...]]:
    expected_ticks = sequence * constants.FRAME_COVERAGE_TICKS
    expected_first_sample = sequence * constants.GPIO_SAMPLES_PER_FRAME
    _validate_common_block(
        block,
        run_id=run_id,
        sequence=sequence,
        first_sample_ticks=expected_ticks,
    )
    _require_equal(
        "GPIO first sample index", block.first_sample_index, expected_first_sample
    )
    if previous is not None:
        _require_equal("GPIO stream gap", StreamGap.between(previous, block), None)

    preview: list[int] = []
    tail: deque[int] = deque(maxlen=_JOIN_ITEMS)
    for offset, sample in enumerate(block.samples):
        _require_equal(
            "GPIO synthetic sample",
            sample,
            (expected_first_sample + offset) & 0xFF,
        )
        if len(preview) < _PREVIEW_ITEMS:
            preview.append(sample)
        tail.append(sample)
    return preview, tuple(tail)


def _validate_status(
    status: Status,
    *,
    state: constants.DeviceState,
    frame_count: int,
) -> None:
    _require_equal("device state", status.device_state, state)
    _require_equal("ADC frame counter", status.adc_frames_emitted, frame_count)
    _require_equal("GPIO frame counter", status.gpio_frames_emitted, frame_count)
    zero_counters = {
        "ADC dropped-item counter": status.adc_items_dropped,
        "GPIO dropped-item counter": status.gpio_items_dropped,
        "parser error counter": status.parser_errors,
        "transport error counter": status.transport_errors,
    }
    for label, observed in zero_counters.items():
        _require_equal(label, observed, 0)


def _format_decimal(values: Sequence[int]) -> str:
    return ", ".join(str(value) for value in values)


def _format_hex(values: Sequence[int]) -> str:
    return ", ".join(f"0x{value:02x}" for value in values)


def run_demo(
    *,
    frame_count: int = DEFAULT_FRAME_COUNT,
    parser_chunk_size: int = DEFAULT_PARSER_CHUNK_SIZE,
    output: TextIO | None = None,
) -> None:
    """Run and validate one deterministic ADC/GPIO acquisition entirely in RAM."""

    if not 1 <= frame_count <= MAX_FRAME_COUNT:
        raise ValueError(f"frame_count must be between 1 and {MAX_FRAME_COUNT}")
    if not 1 <= parser_chunk_size <= MAX_PARSER_CHUNK_SIZE:
        raise ValueError(
            f"parser_chunk_size must be between 1 and {MAX_PARSER_CHUNK_SIZE}"
        )
    if output is None:
        output = sys.stdout

    print("=== Teensy DAQ // OFFLINE SYNTHETIC FLIGHT ===", file=output)
    with TeensyDAQ.simulated(
        read_chunk_size=parser_chunk_size,
        read_size=parser_chunk_size,
    ) as daq:
        info = daq.info()
        _validate_capabilities(info)
        print(
            f"DISCOVER  {info.build_id} | protocol v{info.protocol_version} | "
            f"{info.board_id.name}/{info.mcu_id.name}",
            file=output,
        )
        print(
            "CAPABLE   "
            f"streams={_names_from_mask(int(info.supported_stream_mask), constants.StreamMask)} "
            f"source={_source_names(info)} checksum={_checksum_names(info)}",
            file=output,
        )
        print(
            f"TIMING    ADC={info.adc_pair_rate_hz:,} pairs/s "
            f"GPIO={info.gpio_sample_rate_hz:,} samples/s "
            f"clock={info.timestamp_hz:,} Hz pins=D6..D13",
            file=output,
        )

        configuration = daq.configure(adc=True, gpio=True)
        _require_equal(
            "configured streams",
            configuration.stream_mask,
            constants.StreamMask.ADC | constants.StreamMask.GPIO,
        )
        _require_equal(
            "configured source", configuration.source, constants.Source.SYNTHETIC
        )
        run_id = daq.start()
        _require(run_id != 0, "START returned reserved run ID zero")
        print(
            f"LAUNCH    run={run_id} | {frame_count} frame(s)/stream | "
            f"parser chunks <= {parser_chunk_size} byte(s)",
            file=output,
        )

        adc_count = 0
        gpio_count = 0
        previous_adc: AdcBlock | None = None
        previous_gpio: GpioBlock | None = None
        adc_preview: list[int] = []
        gpio_preview: list[int] = []
        first_adc_tail: tuple[int, ...] | None = None
        first_gpio_tail: tuple[int, ...] | None = None
        adc_join: tuple[tuple[int, ...], tuple[int, ...]] | None = None
        gpio_join: tuple[tuple[int, ...], tuple[int, ...]] | None = None

        for position, block in enumerate(daq.blocks(frame_count * 2)):
            expected_adc = position % 2 == 0
            if expected_adc:
                _require(
                    isinstance(block, AdcBlock),
                    f"stream order mismatch at block {position}: expected ADC",
                )
                assert isinstance(block, AdcBlock)
                head, tail = _validate_adc_block(
                    block,
                    run_id=run_id,
                    sequence=adc_count,
                    previous=previous_adc,
                )
                if adc_count == 0:
                    adc_preview = head
                    first_adc_tail = tail
                elif adc_count == 1 and first_adc_tail is not None:
                    adc_join = (first_adc_tail, tuple(head[:_JOIN_ITEMS]))
                previous_adc = block
                print(
                    f"ADC       seq={block.sequence:03d} ticks={block.first_sample_ticks:>8} "
                    f"pairs={block.item_count}",
                    file=output,
                )
                adc_count += 1
            else:
                _require(
                    isinstance(block, GpioBlock),
                    f"stream order mismatch at block {position}: expected GPIO",
                )
                assert isinstance(block, GpioBlock)
                head, tail = _validate_gpio_block(
                    block,
                    run_id=run_id,
                    sequence=gpio_count,
                    previous=previous_gpio,
                )
                if gpio_count == 0:
                    gpio_preview = head
                    first_gpio_tail = tail
                elif gpio_count == 1 and first_gpio_tail is not None:
                    gpio_join = (first_gpio_tail, tuple(head[:_JOIN_ITEMS]))
                previous_gpio = block
                print(
                    f"GPIO      seq={block.sequence:03d} ticks={block.first_sample_ticks:>8} "
                    f"samples={block.item_count}",
                    file=output,
                )
                gpio_count += 1

        _require_equal("validated ADC frame count", adc_count, frame_count)
        _require_equal("validated GPIO frame count", gpio_count, frame_count)
        print(
            f"ADC RAMP  {_format_decimal(adc_preview)}  (A0/A1 interleaved)",
            file=output,
        )
        if adc_join is not None:
            print(
                f"ADC JOIN  {_format_decimal(adc_join[0])} -> "
                f"{_format_decimal(adc_join[1])}",
                file=output,
            )
        print(f"GPIO RAMP {_format_hex(gpio_preview)}", file=output)
        if gpio_join is not None:
            print(
                f"GPIO JOIN {_format_hex(gpio_join[0])} -> {_format_hex(gpio_join[1])}",
                file=output,
            )

        running_status = daq.status()
        _validate_status(
            running_status,
            state=constants.DeviceState.RUNNING,
            frame_count=frame_count,
        )
        print(
            "COUNTERS  "
            f"adc={running_status.adc_frames_emitted} "
            f"gpio={running_status.gpio_frames_emitted} "
            f"dropped={running_status.adc_items_dropped + running_status.gpio_items_dropped} "
            f"errors={running_status.parser_errors + running_status.transport_errors}",
            file=output,
        )

        _require_equal("STOP result", daq.stop(), constants.DeviceState.IDLE)
        final_status = daq.status()
        _validate_status(
            final_status,
            state=constants.DeviceState.IDLE,
            frame_count=frame_count,
        )
        _require_equal(
            "final stream mask", final_status.stream_mask, constants.StreamMask.NONE
        )
        print(
            f"FINAL     state={final_status.device_state.name} "
            f"adc={final_status.adc_frames_emitted} "
            f"gpio={final_status.gpio_frames_emitted} "
            f"dropped={final_status.adc_items_dropped + final_status.gpio_items_dropped} "
            f"errors={final_status.parser_errors + final_status.transport_errors}",
            file=output,
        )

    _require(not daq.is_open, "context cleanup left the transport open")
    print("CLEANUP   transport=CLOSED", file=output)
    print(
        f"PASS      validated {frame_count} ADC + {frame_count} GPIO frames; "
        "zero gaps, drops, or errors",
        file=output,
    )


def _build_parser() -> argparse.ArgumentParser:
    parser = argparse.ArgumentParser(
        description=(
            "Run the Teensy DAQ synthetic prototype entirely offline and validate "
            "every sample."
        )
    )
    parser.add_argument(
        "--frame-count",
        "--frames-per-stream",
        dest="frame_count",
        type=_bounded_integer("frame count", MAX_FRAME_COUNT),
        default=DEFAULT_FRAME_COUNT,
        metavar="N",
        help=(
            "ADC frames and GPIO frames to validate "
            f"(default: {DEFAULT_FRAME_COUNT}, maximum: {MAX_FRAME_COUNT})"
        ),
    )
    parser.add_argument(
        "--parser-chunk-size",
        "--chunk-size",
        dest="parser_chunk_size",
        type=_bounded_integer("parser chunk size", MAX_PARSER_CHUNK_SIZE),
        default=DEFAULT_PARSER_CHUNK_SIZE,
        metavar="BYTES",
        help=(
            "maximum bytes fed to the incremental parser per read "
            f"(default: {DEFAULT_PARSER_CHUNK_SIZE})"
        ),
    )
    return parser


def main(argv: Sequence[str] | None = None) -> int:
    """Console entry point; return nonzero whenever validation does not pass."""

    arguments = _build_parser().parse_args(argv)
    try:
        run_demo(
            frame_count=arguments.frame_count,
            parser_chunk_size=arguments.parser_chunk_size,
        )
    except (DemoValidationError, TeensyDAQError) as exc:
        print(f"FAIL      {exc}", file=sys.stderr)
        return 1
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
