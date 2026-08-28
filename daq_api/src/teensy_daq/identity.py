"""Firmware identity validation shared by discovery and the public client."""

from __future__ import annotations

import re
from dataclasses import dataclass

from ._generated import protocol_constants as constants
from .models import DeviceInfo

PHASE03_MINIMUM_FIRMWARE_VERSION = (0, 3, 0)
_PHYSICAL_BUILD_ID = re.compile(r"tdaq-[0-9a-f]{16}", re.ASCII)


class IdentityValidationError(ValueError):
    """An INFO identity is internally inconsistent or misses an expectation."""


@dataclass(frozen=True, slots=True)
class DeviceIdentitySnapshot:
    """Stable INFO fields that identify one firmware image on one device."""

    protocol_version: int
    firmware_version: tuple[int, int, int]
    build_id: str
    hardware_serial: int
    board_id: constants.BoardId
    mcu_id: constants.McuId

    @classmethod
    def from_info(cls, info: DeviceInfo) -> DeviceIdentitySnapshot:
        """Capture only fields that must not change during one open session."""

        return cls(
            protocol_version=info.protocol_version,
            firmware_version=info.firmware_version,
            build_id=info.build_id,
            hardware_serial=info.hardware_serial,
            board_id=info.board_id,
            mcu_id=info.mcu_id,
        )


@dataclass(frozen=True, slots=True)
class ExpectedDeviceIdentity:
    """Optional exact identity fields a caller can pin before device mutation."""

    hardware_serial: int | None = None
    firmware_version: tuple[int, int, int] | None = None
    build_id: str | None = None
    board_id: constants.BoardId | None = None
    mcu_id: constants.McuId | None = None
    protocol_version: int = constants.PROTOCOL_VERSION

    def __post_init__(self) -> None:
        if (
            not isinstance(self.protocol_version, int)
            or isinstance(self.protocol_version, bool)
            or not 0 <= self.protocol_version <= 0xFF
        ):
            raise ValueError("expected protocol version must be an unsigned byte")
        if self.hardware_serial is not None and (
            not isinstance(self.hardware_serial, int)
            or isinstance(self.hardware_serial, bool)
            or not 0 <= self.hardware_serial <= constants.UINT32_MAX
        ):
            raise ValueError("expected hardware serial must be an unsigned uint32")
        if self.firmware_version is not None:
            version = tuple(self.firmware_version)
            if len(version) != 3 or any(
                not isinstance(part, int)
                or isinstance(part, bool)
                or not 0 <= part <= 0xFF
                for part in version
            ):
                raise ValueError(
                    "expected firmware version must contain three unsigned bytes"
                )
            object.__setattr__(self, "firmware_version", version)
        if self.build_id is not None and (
            not isinstance(self.build_id, str) or not self.build_id
        ):
            raise ValueError("expected build ID must be a nonempty string")
        if self.board_id is not None and not isinstance(
            self.board_id, constants.BoardId
        ):
            raise TypeError("expected board ID must be a BoardId")
        if self.mcu_id is not None and not isinstance(self.mcu_id, constants.McuId):
            raise TypeError("expected MCU ID must be an McuId")

    @classmethod
    def from_info(cls, info: DeviceInfo) -> ExpectedDeviceIdentity:
        """Pin every stable identity field from a prior successful INFO probe."""

        return cls(
            protocol_version=info.protocol_version,
            firmware_version=info.firmware_version,
            build_id=info.build_id,
            hardware_serial=info.hardware_serial,
            board_id=info.board_id,
            mcu_id=info.mcu_id,
        )


def validate_device_identity(
    info: DeviceInfo,
    expected: ExpectedDeviceIdentity | None = None,
) -> DeviceIdentitySnapshot:
    """Validate protocol/target/build identity and any caller-supplied pins.

    Physical Teensy targets must carry the Phase 03-or-newer semantic firmware
    version, source-derived build-ID format, and a nonzero chip serial. The
    simulator keeps its independent identity policy so transport-independent
    API tests remain valid.
    """

    snapshot = DeviceIdentitySnapshot.from_info(info)
    if snapshot.protocol_version != constants.PROTOCOL_VERSION:
        raise IdentityValidationError(
            f"protocol version {snapshot.protocol_version} is incompatible with "
            f"host protocol {constants.PROTOCOL_VERSION}"
        )

    physical = (
        snapshot.board_id is constants.BoardId.TEENSY_40
        and snapshot.mcu_id is constants.McuId.IMXRT1062
    )
    simulated = (
        snapshot.board_id is constants.BoardId.SIMULATOR
        and snapshot.mcu_id is constants.McuId.SIMULATED
    )
    if not physical and not simulated:
        raise IdentityValidationError(
            "board and MCU identity are not a supported target pair"
        )
    if physical:
        if snapshot.firmware_version < PHASE03_MINIMUM_FIRMWARE_VERSION:
            actual = ".".join(str(part) for part in snapshot.firmware_version)
            minimum = ".".join(str(part) for part in PHASE03_MINIMUM_FIRMWARE_VERSION)
            raise IdentityValidationError(
                f"firmware {actual} predates the Phase 03 minimum {minimum}"
            )
        if _PHYSICAL_BUILD_ID.fullmatch(snapshot.build_id) is None:
            raise IdentityValidationError(
                "physical firmware build ID is not source-derived tdaq-<16 hex>"
            )
        if snapshot.hardware_serial == 0:
            raise IdentityValidationError(
                "physical firmware reported hardware serial number zero"
            )

    if expected is None:
        return snapshot

    def require(label: str, wanted: object | None, actual: object) -> None:
        if wanted is not None and actual != wanted:
            raise IdentityValidationError(
                f"{label} {actual!r} does not match expected {wanted!r}"
            )

    require("protocol version", expected.protocol_version, snapshot.protocol_version)
    require("firmware version", expected.firmware_version, snapshot.firmware_version)
    require("build ID", expected.build_id, snapshot.build_id)
    require("hardware serial", expected.hardware_serial, snapshot.hardware_serial)
    require("board ID", expected.board_id, snapshot.board_id)
    require("MCU ID", expected.mcu_id, snapshot.mcu_id)
    return snapshot


__all__ = [
    "PHASE03_MINIMUM_FIRMWARE_VERSION",
    "DeviceIdentitySnapshot",
    "ExpectedDeviceIdentity",
    "IdentityValidationError",
    "validate_device_identity",
]
