"""Exact protocol-v1 checksum backends for the Python host.

The public codec keeps one dispatch entry per wire identifier.  Standard-library
C implementations are used only where their parameters exactly match protocol
v1; the table-driven implementations are bounded fallbacks and the only path
for CRC-32C in a stock Python installation.
"""

from __future__ import annotations

import sys
import zlib
from collections.abc import Callable, Mapping
from dataclasses import dataclass
from types import MappingProxyType

from ._generated import protocol_constants as constants

BytesLike = bytes | bytearray | memoryview
_ChecksumFunction = Callable[[BytesLike], int]


@dataclass(frozen=True, slots=True)
class ChecksumBackend:
    """The exact implementation selected for one protocol checksum."""

    algorithm: constants.ChecksumAlgorithm
    implementation: str
    accelerated: bool
    fallback_implementation: str


def _byte_view(data: BytesLike) -> memoryview:
    """Return a contiguous one-dimensional byte view for every public input."""

    try:
        return memoryview(data).cast("B")
    except TypeError:
        return memoryview(bytes(data))


def _pure_adler32(data: BytesLike) -> int:
    """RFC 1950 Adler-32, reducing bounded chunks to cap integer growth."""

    view = _byte_view(data)
    try:
        sum_1 = 1
        sum_2 = 0
        offset = 0
        while offset < len(view):
            end = min(offset + 5_552, len(view))
            for value in view[offset:end]:
                sum_1 += value
                sum_2 += sum_1
            sum_1 %= 65_521
            sum_2 %= 65_521
            offset = end
        return (sum_2 << 16) | sum_1
    finally:
        view.release()


def _make_reflected_crc_table(polynomial: int) -> tuple[tuple[int, ...], ...]:
    first_slice: list[int] = []
    for index in range(256):
        remainder = index
        for _ in range(8):
            remainder = (remainder >> 1) ^ (polynomial if remainder & 1 else 0)
        first_slice.append(remainder)
    slices = [tuple(first_slice)]
    for _ in range(3):
        previous = slices[-1]
        slices.append(
            tuple((value >> 8) ^ slices[0][value & 0xFF] for value in previous)
        )
    return tuple(slices)


_CRC32C_TABLE = _make_reflected_crc_table(0x82F63B78)
_CRC32_ISO_HDLC_TABLE = _make_reflected_crc_table(0xEDB88320)


def _pure_reflected_crc32(
    data: BytesLike,
    table: tuple[tuple[int, ...], ...],
) -> int:
    view = _byte_view(data)
    try:
        remainder = constants.UINT32_MAX
        word_bytes = len(view) & ~3
        slice_0, slice_1, slice_2, slice_3 = table
        if sys.byteorder == "little":
            words = view[:word_bytes].cast("I")
            try:
                for word in words:
                    remainder ^= word
                    remainder = (
                        slice_3[remainder & 0xFF]
                        ^ slice_2[(remainder >> 8) & 0xFF]
                        ^ slice_1[(remainder >> 16) & 0xFF]
                        ^ slice_0[remainder >> 24]
                    )
            finally:
                words.release()
        else:
            for offset in range(0, word_bytes, 4):
                remainder ^= int.from_bytes(view[offset : offset + 4], "little")
                remainder = (
                    slice_3[remainder & 0xFF]
                    ^ slice_2[(remainder >> 8) & 0xFF]
                    ^ slice_1[(remainder >> 16) & 0xFF]
                    ^ slice_0[remainder >> 24]
                )
        for value in view[word_bytes:]:
            remainder = (remainder >> 8) ^ slice_0[(remainder ^ value) & 0xFF]
        return remainder ^ constants.UINT32_MAX
    finally:
        view.release()


def _pure_crc32c(data: BytesLike) -> int:
    return _pure_reflected_crc32(data, _CRC32C_TABLE)


def _pure_crc32_iso_hdlc(data: BytesLike) -> int:
    return _pure_reflected_crc32(data, _CRC32_ISO_HDLC_TABLE)


def _accelerated_adler32(data: BytesLike) -> int:
    view = _byte_view(data)
    try:
        return zlib.adler32(view, 1) & constants.UINT32_MAX
    finally:
        view.release()


def _accelerated_crc32_iso_hdlc(data: BytesLike) -> int:
    view = _byte_view(data)
    try:
        return zlib.crc32(view, 0) & constants.UINT32_MAX
    finally:
        view.release()


_CHECKSUM_FUNCTIONS: Mapping[constants.ChecksumAlgorithm, _ChecksumFunction] = (
    MappingProxyType(
        {
            constants.ChecksumAlgorithm.ADLER32: _accelerated_adler32,
            constants.ChecksumAlgorithm.CRC32C: _pure_crc32c,
            constants.ChecksumAlgorithm.CRC32_ISO_HDLC: (_accelerated_crc32_iso_hdlc),
        }
    )
)
_FALLBACK_FUNCTIONS: Mapping[constants.ChecksumAlgorithm, _ChecksumFunction] = (
    MappingProxyType(
        {
            constants.ChecksumAlgorithm.ADLER32: _pure_adler32,
            constants.ChecksumAlgorithm.CRC32C: _pure_crc32c,
            constants.ChecksumAlgorithm.CRC32_ISO_HDLC: _pure_crc32_iso_hdlc,
        }
    )
)
_CHECKSUM_BACKENDS: Mapping[constants.ChecksumAlgorithm, ChecksumBackend] = (
    MappingProxyType(
        {
            constants.ChecksumAlgorithm.ADLER32: ChecksumBackend(
                algorithm=constants.ChecksumAlgorithm.ADLER32,
                implementation="zlib.adler32",
                accelerated=True,
                fallback_implementation="python.adler32",
            ),
            constants.ChecksumAlgorithm.CRC32C: ChecksumBackend(
                algorithm=constants.ChecksumAlgorithm.CRC32C,
                implementation="python.slicing_by_four.crc32c",
                accelerated=False,
                fallback_implementation="python.slicing_by_four.crc32c",
            ),
            constants.ChecksumAlgorithm.CRC32_ISO_HDLC: ChecksumBackend(
                algorithm=constants.ChecksumAlgorithm.CRC32_ISO_HDLC,
                implementation="zlib.crc32",
                accelerated=True,
                fallback_implementation="python.slicing_by_four.crc32_iso_hdlc",
            ),
        }
    )
)

HOST_SUPPORTED_CHECKSUM_ALGORITHMS = frozenset(_CHECKSUM_FUNCTIONS)
HOST_SUPPORTED_CHECKSUM_MASK = sum(
    1 << int(algorithm) for algorithm in HOST_SUPPORTED_CHECKSUM_ALGORITHMS
)


def checksum_backend(
    algorithm: constants.ChecksumAlgorithm,
) -> ChecksumBackend | None:
    """Return backend metadata, or ``None`` when this host cannot compute it."""

    return _CHECKSUM_BACKENDS.get(algorithm)


def compute_checksum_value(
    data: BytesLike,
    algorithm: constants.ChecksumAlgorithm,
) -> int | None:
    """Compute ``algorithm`` exactly, or return ``None`` when unavailable."""

    implementation = _CHECKSUM_FUNCTIONS.get(algorithm)
    return None if implementation is None else implementation(data)


def _compute_checksum_fallback(
    data: BytesLike,
    algorithm: constants.ChecksumAlgorithm,
) -> int | None:
    """Testable pure-Python reference/fallback for every enabled variant."""

    implementation = _FALLBACK_FUNCTIONS.get(algorithm)
    return None if implementation is None else implementation(data)


__all__ = [
    "HOST_SUPPORTED_CHECKSUM_ALGORITHMS",
    "HOST_SUPPORTED_CHECKSUM_MASK",
    "ChecksumBackend",
    "checksum_backend",
]
