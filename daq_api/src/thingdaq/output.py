"""Immutable auxiliary-output programs and protocol-v2 response models."""

from __future__ import annotations

import struct
import zlib
from collections.abc import Iterable
from dataclasses import dataclass

from ._generated import protocol_v2_constants as constants

_SEGMENT = struct.Struct("<II")
_RESPONSE_PREFIX = struct.Struct("<BBH")


class DigitalOutputError(ValueError):
    """Base error for invalid local output programs."""


class DigitalOutputProgramError(DigitalOutputError):
    """A program cannot be represented by the canonical bounded format."""


def _u32(name: str, value: int) -> int:
    if not isinstance(value, int) or isinstance(value, bool):
        raise TypeError(f"{name} must be an integer")
    if not 0 <= value <= constants.UINT32_MAX:
        raise DigitalOutputProgramError(f"{name} must be an unsigned 32-bit integer")
    return value


def _state_mask(name: str, value: int) -> int:
    _u32(name, value)
    if value & ~constants.OUTPUT_LEGAL_STATE_MASK:
        raise DigitalOutputProgramError(f"{name} may use only logical output bits 0-7")
    return value


@dataclass(frozen=True, slots=True)
class DigitalOutputSegment:
    """One canonical one-microsecond-quantized logical output interval."""

    duration_samples: int
    logical_state_mask: int

    def __post_init__(self) -> None:
        _u32("duration_samples", self.duration_samples)
        if self.duration_samples == 0:
            raise DigitalOutputProgramError("duration_samples must be positive")
        _state_mask("logical_state_mask", self.logical_state_mask)

    @classmethod
    def hold(
        cls, duration_samples: int, logical_state_mask: int
    ) -> DigitalOutputSegment:
        """Build one constant-state interval."""

        return cls(duration_samples, logical_state_mask)

    def to_bytes(self) -> bytes:
        """Return the exact canonical little-endian segment record."""

        return _SEGMENT.pack(self.duration_samples, self.logical_state_mask)


@dataclass(frozen=True, slots=True)
class DigitalOutputProgram:
    """Canonical immutable sequence plus idle and whole-program repeat policy."""

    segments: tuple[DigitalOutputSegment, ...]
    repeat_count: int = 1
    idle_state_mask: int = 0

    def __post_init__(self) -> None:
        segments = tuple(self.segments)
        object.__setattr__(self, "segments", segments)
        _u32("repeat_count", self.repeat_count)
        _state_mask("idle_state_mask", self.idle_state_mask)
        if not segments:
            raise DigitalOutputProgramError(
                "an output program needs at least one segment"
            )
        if len(segments) > constants.OUTPUT_SEGMENT_CAPACITY:
            raise DigitalOutputProgramError(
                f"an output program may contain at most {constants.OUTPUT_SEGMENT_CAPACITY} segments"
            )
        for index, segment in enumerate(segments):
            if not isinstance(segment, DigitalOutputSegment):
                raise TypeError("segments must contain DigitalOutputSegment values")
            if (
                index
                and segment.logical_state_mask == segments[index - 1].logical_state_mask
            ):
                raise DigitalOutputProgramError(
                    "adjacent equal states are noncanonical; use from_segments() to coalesce"
                )

    @classmethod
    def from_segments(
        cls,
        segments: Iterable[DigitalOutputSegment | tuple[int, int]],
        *,
        repeat_count: int = 1,
        idle_state_mask: int = 0,
    ) -> DigitalOutputProgram:
        """Validate and coalesce adjacent equal states before returning a program."""

        canonical: list[DigitalOutputSegment] = []
        for item in segments:
            segment = (
                item
                if isinstance(item, DigitalOutputSegment)
                else DigitalOutputSegment(*item)
            )
            if (
                canonical
                and canonical[-1].logical_state_mask == segment.logical_state_mask
            ):
                duration = canonical[-1].duration_samples + segment.duration_samples
                if duration > constants.UINT32_MAX:
                    raise DigitalOutputProgramError(
                        "coalesced segment duration exceeds u32"
                    )
                canonical[-1] = DigitalOutputSegment(
                    duration, segment.logical_state_mask
                )
            else:
                canonical.append(segment)
            if len(canonical) > constants.OUTPUT_SEGMENT_CAPACITY:
                raise DigitalOutputProgramError(
                    f"canonical program exceeds {constants.OUTPUT_SEGMENT_CAPACITY} segments"
                )
        return cls(tuple(canonical), repeat_count, idle_state_mask)

    @classmethod
    def hold(
        cls,
        duration_samples: int,
        logical_state_mask: int,
        *,
        idle_state_mask: int = 0,
    ) -> DigitalOutputProgram:
        """Build a finite one-play constant-state program."""

        return cls.from_segments(
            [(duration_samples, logical_state_mask)], idle_state_mask=idle_state_mask
        )

    @classmethod
    def finite(
        cls,
        segments: Iterable[DigitalOutputSegment | tuple[int, int]],
        repeat_count: int,
        *,
        idle_state_mask: int = 0,
    ) -> DigitalOutputProgram:
        """Build a program that plays exactly ``repeat_count`` times."""

        _u32("repeat_count", repeat_count)
        if repeat_count == constants.OUTPUT_REPEAT_FOREVER:
            raise DigitalOutputProgramError("finite repeat_count must be positive")
        return cls.from_segments(
            segments, repeat_count=repeat_count, idle_state_mask=idle_state_mask
        )

    @classmethod
    def forever(
        cls,
        segments: Iterable[DigitalOutputSegment | tuple[int, int]],
        *,
        idle_state_mask: int = 0,
    ) -> DigitalOutputProgram:
        """Build a program that repeats whole-program plays forever."""

        return cls.from_segments(
            segments,
            repeat_count=constants.OUTPUT_REPEAT_FOREVER,
            idle_state_mask=idle_state_mask,
        )

    @property
    def canonical_bytes(self) -> bytes:
        """Exact checksum/upload bytes, excluding transport and program metadata."""

        return b"".join(segment.to_bytes() for segment in self.segments)

    @property
    def checksum(self) -> int:
        """Adler-32 over the exact canonical segment records."""

        return zlib.adler32(self.canonical_bytes) & constants.UINT32_MAX

    @property
    def duration_samples(self) -> int:
        """Duration of one whole-program play in one-microsecond samples."""

        return sum(segment.duration_samples for segment in self.segments)


@dataclass(frozen=True, slots=True)
class DigitalOutputCapabilities:
    """Exact experimental-v2 output metadata required before control."""

    capability_bits: constants.Capability
    bank_mode: constants.OutputBankMode
    pins_by_logical_bit: tuple[int, ...]
    gpio_bits_by_logical_bit: tuple[int, ...]
    rate_hz: int
    period_ticks: int
    capacity_segments: int
    state_width_bits: int
    duration_quantum_us: int
    legal_state_mask: int

    @classmethod
    def from_info_payload(cls, payload: bytes) -> DigitalOutputCapabilities:
        """Decode and require the complete fixed output capability contract."""

        if len(payload) != constants.INFO_RESPONSE_PAYLOAD_SIZE:
            raise ValueError("protocol-v2 INFO payload has the wrong size")
        if (
            payload[constants.INFO_RESPONSE_PROTOCOL_VERSION_OFFSET]
            != constants.PROTOCOL_VERSION
        ):
            raise ValueError("INFO does not identify protocol v2")
        bits = constants.Capability(
            struct.unpack_from(
                "<I", payload, constants.INFO_RESPONSE_CAPABILITY_BITS_OFFSET
            )[0]
        )
        if int(bits) & ~constants.KNOWN_CAPABILITY_MASK:
            raise ValueError("INFO contains unknown protocol-v2 capability bits")
        required = (
            constants.Capability.PRELOADED_AUXILIARY_OUTPUT
            | constants.Capability.COMMON_EPOCH_OUTPUT
        )
        if bits & required != required:
            raise ValueError("INFO omits required output capabilities")
        pins_start = constants.INFO_RESPONSE_OUTPUT_PIN_MAP_OFFSET
        gpio_start = constants.INFO_RESPONSE_OUTPUT_GPIO_BITS_BY_LOGICAL_BIT_OFFSET
        result = cls(
            capability_bits=bits,
            bank_mode=constants.OutputBankMode(
                payload[constants.INFO_RESPONSE_OUTPUT_BANK_MODE_OFFSET]
            ),
            pins_by_logical_bit=tuple(payload[pins_start : pins_start + 8]),
            gpio_bits_by_logical_bit=tuple(payload[gpio_start : gpio_start + 8]),
            rate_hz=struct.unpack_from(
                "<I", payload, constants.INFO_RESPONSE_OUTPUT_RATE_HZ_OFFSET
            )[0],
            period_ticks=struct.unpack_from(
                "<I", payload, constants.INFO_RESPONSE_OUTPUT_PERIOD_TICKS_OFFSET
            )[0],
            capacity_segments=struct.unpack_from(
                "<I", payload, constants.INFO_RESPONSE_OUTPUT_CAPACITY_SEGMENTS_OFFSET
            )[0],
            state_width_bits=payload[
                constants.INFO_RESPONSE_OUTPUT_STATE_WIDTH_BITS_OFFSET
            ],
            duration_quantum_us=payload[
                constants.INFO_RESPONSE_OUTPUT_DURATION_QUANTUM_US_OFFSET
            ],
            legal_state_mask=struct.unpack_from(
                "<I", payload, constants.INFO_RESPONSE_OUTPUT_LEGAL_STATE_MASK_OFFSET
            )[0],
        )
        expected = (
            result.bank_mode is constants.OutputBankMode.DISABLED
            and payload[constants.INFO_RESPONSE_OUTPUT_PIN_COUNT_OFFSET] == 8
            and result.pins_by_logical_bit == constants.OUTPUT_PINS_BY_LOGICAL_BIT
            and result.gpio_bits_by_logical_bit
            == constants.OUTPUT_GPIO_BITS_BY_LOGICAL_BIT
            and result.rate_hz == constants.OUTPUT_RATE_HZ
            and result.period_ticks == constants.OUTPUT_PERIOD_TICKS
            and result.capacity_segments == constants.OUTPUT_SEGMENT_CAPACITY
            and result.state_width_bits == constants.OUTPUT_STATE_WIDTH_BITS
            and result.duration_quantum_us == constants.OUTPUT_DURATION_QUANTUM_US
            and result.legal_state_mask == constants.OUTPUT_LEGAL_STATE_MASK
        )
        if not expected:
            raise ValueError(
                "INFO output pin/rate/capacity metadata disagrees with the host contract"
            )
        return result


@dataclass(frozen=True, slots=True)
class DigitalOutputAppendEcho:
    """Exact successful response echo for one appended segment."""

    accepted_segment_count: int
    segment: DigitalOutputSegment


@dataclass(frozen=True, slots=True)
class DigitalOutputStatus:
    """Immutable output lifecycle, cursor, hold, and fault snapshot."""

    state: constants.OutputState
    bank_mode: constants.OutputBankMode
    fault_latched: bool
    generation: int
    idle_state_mask: int
    current_state_mask: int
    last_emitted_state_mask: int
    repeat_count: int
    completed_repeats: int
    segment_count: int
    accepted_segment_count: int
    program_checksum: int
    current_segment_index: int
    ticks_elapsed: int
    transitions_emitted: int
    output_error: constants.OutputError
    current_segment_remaining: int = 0
    common_run_id: int = 0
    requested_duration_states: int = 0
    states_expanded: int = 0
    dma_states_queued: int = 0
    dma_states_emitted: int = 0
    held_remainder_states: int = 0
    blocks_filled: int = 0
    blocks_completed: int = 0
    start_tick: int = 0
    completion_tick: int = 0
    hold_tick: int = 0
    ready_depth: int = 0
    ready_high_water: int = 0
    refill_lead: int = 0
    refill_lead_high_water: int = 0
    cache_flushes: int = 0
    start_operations: int = 0
    stop_operations: int = 0
    invalid_operations: int = 0
    resource_conflicts: int = 0
    underruns: int = 0
    stale_completions: int = 0
    dma_errors: int = 0
    start_errors: int = 0
    stop_errors: int = 0
    conservation_errors: int = 0
    conservation_exact: bool = True

    @classmethod
    def from_payload(cls, payload: bytes) -> DigitalOutputStatus:
        if len(payload) != constants.OUTPUT_STATUS_RESPONSE_PAYLOAD_SIZE:
            raise ValueError("output status payload has the wrong size")
        if payload[1] or payload[7] or any(payload[61:64]) or any(payload[209:224]):
            raise ValueError("output status reserved fields must be zero")
        masks = [
            struct.unpack_from("<I", payload, offset)[0] for offset in (12, 16, 20)
        ]
        if any(mask & ~constants.OUTPUT_LEGAL_STATE_MASK for mask in masks):
            raise ValueError("output status contains an invalid logical state mask")
        fault = payload[6]
        if fault not in (0, 1):
            raise ValueError("output fault_latched must be zero or one")
        result = cls(
            state=constants.OutputState(payload[4]),
            bank_mode=constants.OutputBankMode(payload[5]),
            fault_latched=bool(fault),
            generation=struct.unpack_from("<I", payload, 8)[0],
            idle_state_mask=masks[0],
            current_state_mask=masks[1],
            last_emitted_state_mask=masks[2],
            repeat_count=struct.unpack_from("<I", payload, 24)[0],
            completed_repeats=struct.unpack_from("<I", payload, 28)[0],
            segment_count=struct.unpack_from("<I", payload, 32)[0],
            accepted_segment_count=struct.unpack_from("<I", payload, 36)[0],
            program_checksum=struct.unpack_from("<I", payload, 40)[0],
            current_segment_index=struct.unpack_from("<I", payload, 44)[0],
            ticks_elapsed=struct.unpack_from("<Q", payload, 48)[0],
            transitions_emitted=struct.unpack_from("<I", payload, 56)[0],
            output_error=constants.OutputError(payload[60]),
            current_segment_remaining=struct.unpack_from("<I", payload, 64)[0],
            common_run_id=struct.unpack_from("<I", payload, 68)[0],
            requested_duration_states=struct.unpack_from("<Q", payload, 72)[0],
            states_expanded=struct.unpack_from("<Q", payload, 80)[0],
            dma_states_queued=struct.unpack_from("<Q", payload, 88)[0],
            dma_states_emitted=struct.unpack_from("<Q", payload, 96)[0],
            held_remainder_states=struct.unpack_from("<Q", payload, 104)[0],
            blocks_filled=struct.unpack_from("<Q", payload, 112)[0],
            blocks_completed=struct.unpack_from("<Q", payload, 120)[0],
            start_tick=struct.unpack_from("<Q", payload, 128)[0],
            completion_tick=struct.unpack_from("<Q", payload, 136)[0],
            hold_tick=struct.unpack_from("<Q", payload, 144)[0],
            ready_depth=struct.unpack_from("<H", payload, 152)[0],
            ready_high_water=struct.unpack_from("<H", payload, 154)[0],
            refill_lead=struct.unpack_from("<I", payload, 156)[0],
            refill_lead_high_water=struct.unpack_from("<I", payload, 160)[0],
            cache_flushes=struct.unpack_from("<I", payload, 164)[0],
            start_operations=struct.unpack_from("<I", payload, 168)[0],
            stop_operations=struct.unpack_from("<I", payload, 172)[0],
            invalid_operations=struct.unpack_from("<I", payload, 176)[0],
            resource_conflicts=struct.unpack_from("<I", payload, 180)[0],
            underruns=struct.unpack_from("<I", payload, 184)[0],
            stale_completions=struct.unpack_from("<I", payload, 188)[0],
            dma_errors=struct.unpack_from("<I", payload, 192)[0],
            start_errors=struct.unpack_from("<I", payload, 196)[0],
            stop_errors=struct.unpack_from("<I", payload, 200)[0],
            conservation_errors=struct.unpack_from("<I", payload, 204)[0],
            conservation_exact=bool(payload[208]),
        )
        if payload[208] not in (0, 1):
            raise ValueError("output conservation_exact must be zero or one")
        if result.generation == 0 and result.state is not constants.OutputState.EMPTY:
            raise ValueError("nonempty output status generation must be nonzero")
        output_mode_states = {
            constants.OutputState.ARMED,
            constants.OutputState.RUNNING,
            constants.OutputState.HELD,
            constants.OutputState.FAULTED,
        }
        if (result.state in output_mode_states) != (
            result.bank_mode is constants.OutputBankMode.OUTPUT
        ):
            raise ValueError("output status lifecycle and bank mode disagree")
        if result.fault_latched != (result.state is constants.OutputState.FAULTED):
            raise ValueError("output status lifecycle and fault latch disagree")
        if result.fault_latched and result.output_error is constants.OutputError.NONE:
            raise ValueError("faulted output status omits its output error")
        if (
            result.segment_count > constants.OUTPUT_SEGMENT_CAPACITY
            or result.accepted_segment_count > constants.OUTPUT_SEGMENT_CAPACITY
            or result.accepted_segment_count < result.segment_count
        ):
            raise ValueError("output status segment counts are inconsistent")
        expected_exact = (
            result.dma_states_queued == result.states_expanded
            and result.states_expanded
            == result.dma_states_emitted
            + result.refill_lead
            + result.held_remainder_states
            and result.conservation_errors == 0
        )
        error_response_without_telemetry = payload[0] == int(
            constants.ResponseStatus.ERROR
        ) and not any(payload[64:209])
        if (
            result.conservation_exact != expected_exact
            and not error_response_without_telemetry
        ):
            raise ValueError("output status conservation flag disagrees with counters")
        return result


def decode_append_echo(payload: bytes) -> DigitalOutputAppendEcho:
    """Decode one successful exact append echo."""

    if len(payload) != constants.OUTPUT_APPEND_RESPONSE_PAYLOAD_SIZE:
        raise ValueError("OUTPUT_APPEND response payload has the wrong size")
    status, reserved, error = _RESPONSE_PREFIX.unpack_from(payload)
    if (
        status != constants.ResponseStatus.OK
        or reserved
        or error != constants.ErrorCode.OK
    ):
        raise ValueError("successful OUTPUT_APPEND response prefix is invalid")
    return DigitalOutputAppendEcho(
        struct.unpack_from("<I", payload, 4)[0],
        DigitalOutputSegment(*struct.unpack_from("<II", payload, 8)),
    )


__all__ = [
    "DigitalOutputAppendEcho",
    "DigitalOutputCapabilities",
    "DigitalOutputError",
    "DigitalOutputProgram",
    "DigitalOutputProgramError",
    "DigitalOutputSegment",
    "DigitalOutputStatus",
]
