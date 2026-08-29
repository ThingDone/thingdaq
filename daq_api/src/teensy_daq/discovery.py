"""Metadata-first discovery for physical Teensy DAQ serial devices."""

from __future__ import annotations

from collections.abc import Callable, Iterable
from dataclasses import dataclass
from typing import Protocol, TypeAlias

from serial.tools import list_ports
from serial.tools.list_ports_common import ListPortInfo

from ._generated import protocol_constants as constants
from .identity import IdentityValidationError, validate_device_identity
from .models import Info
from .reader import BackgroundReader
from .transport import ByteTransport, SerialTransport

TEENSY_USB_SERIAL_VID = 0x16C0
TEENSY_USB_SERIAL_PID = 0x0483
TEENSY_DAQ_PRODUCT = "Teensy DAQ"
DEFAULT_DISCOVERY_TIMEOUT = 0.2


class DiscoveryError(RuntimeError):
    """Base error for a direct discovery or selection operation."""


class DiscoveryProbeError(DiscoveryError):
    """A plausible serial candidate did not complete a valid INFO exchange."""

    def __init__(
        self,
        candidate: SerialPortCandidate,
        message: str,
        cause: BaseException | None = None,
    ) -> None:
        super().__init__(f"{candidate.port!r}: {message}")
        self.candidate = candidate
        self.cause = cause


class DeviceNotFoundError(DiscoveryError):
    """No discovered device has the requested stable hardware identity."""


class _PortMetadata(Protocol):
    """PySerial metadata fields used without opening a serial port."""

    device: str
    description: str
    vid: int | None
    pid: int | None
    serial_number: str | None
    location: str | None
    manufacturer: str | None
    product: str | None
    interface: str | None


PortEnumerator: TypeAlias = Callable[[], Iterable[_PortMetadata]]
DiscoveryTransportFactory: TypeAlias = Callable[["SerialPortCandidate"], ByteTransport]
HardwareSerial: TypeAlias = int | str


@dataclass(frozen=True, slots=True)
class SerialPortCandidate:
    """Snapshot of a plausible Teensy USB Serial port's enumeration metadata.

    ``port`` is only the endpoint to try during this scan. The USB serial and
    the INFO hardware serial are the device identities that survive COM-port
    renumbering or a changed ``/dev`` path.
    """

    port: str
    vid: int
    pid: int
    serial_number: str | None = None
    product: str | None = None
    manufacturer: str | None = None
    location: str | None = None
    interface: str | None = None
    description: str | None = None

    def __post_init__(self) -> None:
        if not isinstance(self.port, str) or not self.port:
            raise ValueError("candidate port must be a nonempty string")
        for name in ("vid", "pid"):
            value = getattr(self, name)
            if not isinstance(value, int) or isinstance(value, bool):
                raise TypeError(f"candidate {name} must be a 16-bit integer")
            if not 0 <= value <= 0xFFFF:
                raise ValueError(f"candidate {name} must be a 16-bit integer")

    @property
    def preferred_product(self) -> bool:
        """Whether enumeration reported the expected project product string."""

        return self.product == TEENSY_DAQ_PRODUCT


@dataclass(frozen=True, slots=True)
class DeviceIdentity:
    """Stable identity learned from INFO rather than a transient port path."""

    hardware_serial: int

    def __post_init__(self) -> None:
        if (
            not isinstance(self.hardware_serial, int)
            or isinstance(self.hardware_serial, bool)
            or not 0 <= self.hardware_serial <= constants.UINT32_MAX
        ):
            raise ValueError("hardware_serial must be an unsigned 32-bit integer")


@dataclass(frozen=True, slots=True)
class DiscoveredDevice:
    """A metadata candidate that answered a compatible, physical-device INFO."""

    candidate: SerialPortCandidate
    info: Info

    @property
    def identity(self) -> DeviceIdentity:
        """Return the stable identity used across port renames and rescans."""

        return DeviceIdentity(self.info.hardware_serial)

    @property
    def port(self) -> str:
        return self.candidate.port

    @property
    def vid(self) -> int:
        return self.candidate.vid

    @property
    def pid(self) -> int:
        return self.candidate.pid

    @property
    def serial_number(self) -> str | None:
        """Return the USB descriptor serial number reported by PySerial."""

        return self.candidate.serial_number

    @property
    def product(self) -> str | None:
        return self.candidate.product

    @property
    def manufacturer(self) -> str | None:
        return self.candidate.manufacturer

    @property
    def location(self) -> str | None:
        return self.candidate.location

    @property
    def interface(self) -> str | None:
        return self.candidate.interface

    @property
    def description(self) -> str | None:
        return self.candidate.description

    @property
    def hardware_serial(self) -> int:
        """Return the protocol INFO hardware serial number."""

        return self.info.hardware_serial


def _default_port_enumerator() -> Iterable[ListPortInfo]:
    return list_ports.comports(include_links=False)


def _optional_text(value: str | None) -> str | None:
    return value if value else None


def _product_rank(product: str | None) -> int:
    if product == TEENSY_DAQ_PRODUCT:
        return 0
    if product is None:
        return 1
    return 2


def _candidate_sort_key(candidate: SerialPortCandidate) -> tuple[object, ...]:
    return (
        _product_rank(candidate.product),
        (candidate.serial_number or "").casefold(),
        (candidate.location or "").casefold(),
        candidate.port.casefold(),
    )


def enumerate_candidates(
    *,
    port_enumerator: PortEnumerator | None = None,
) -> tuple[SerialPortCandidate, ...]:
    """Return matching Teensy USB Serial metadata without opening any port.

    All ``0x16C0:0x0483`` ports remain plausible because product strings may be
    missing or cached by the operating system. Exact ``Teensy DAQ`` product
    matches are ordered first, followed by missing and then other product
    strings. No nonmatching VID/PID is returned or opened by :func:`discover`.
    """

    enumerate_ports = port_enumerator or _default_port_enumerator
    candidates: list[SerialPortCandidate] = []
    seen_paths: set[str] = set()
    for metadata in enumerate_ports():
        if (
            metadata.vid != TEENSY_USB_SERIAL_VID
            or metadata.pid != TEENSY_USB_SERIAL_PID
        ):
            continue
        port = metadata.device
        if not isinstance(port, str) or not port or port in seen_paths:
            continue
        seen_paths.add(port)
        candidates.append(
            SerialPortCandidate(
                port=port,
                vid=TEENSY_USB_SERIAL_VID,
                pid=TEENSY_USB_SERIAL_PID,
                serial_number=_optional_text(metadata.serial_number),
                product=_optional_text(metadata.product),
                manufacturer=_optional_text(metadata.manufacturer),
                location=_optional_text(metadata.location),
                interface=_optional_text(metadata.interface),
                description=_optional_text(metadata.description),
            )
        )
    candidates.sort(key=_candidate_sort_key)
    return tuple(candidates)


def _validate_timeout(timeout: float) -> float:
    if (
        not isinstance(timeout, (int, float))
        or isinstance(timeout, bool)
        or timeout <= 0
    ):
        raise ValueError("discovery timeout must be positive")
    return float(timeout)


def _serial_transport_factory(
    candidate: SerialPortCandidate,
    timeout: float,
) -> ByteTransport:
    return SerialTransport(
        candidate.port,
        open_timeout=timeout,
        read_timeout=min(0.05, timeout),
        write_timeout=timeout,
        flush_timeout=timeout,
        close_timeout=timeout,
    )


def _usb_serial_as_int(serial_number: str | None) -> int | None:
    if (
        serial_number is None
        or not serial_number.isascii()
        or not serial_number.isdecimal()
    ):
        return None
    return int(serial_number, 10)


def _validate_physical_info(candidate: SerialPortCandidate, info: Info) -> None:
    try:
        validate_device_identity(info)
    except IdentityValidationError as error:
        raise DiscoveryProbeError(
            candidate,
            f"INFO identity is incompatible: {error}",
            error,
        ) from error
    if (
        info.board_id is not constants.BoardId.TEENSY_40
        or info.mcu_id is not constants.McuId.IMXRT1062
    ):
        raise DiscoveryProbeError(
            candidate, "INFO did not identify a Teensy 4.0 / i.MX RT1062 device"
        )

    enumerated_serial = _usb_serial_as_int(candidate.serial_number)
    if enumerated_serial is not None and enumerated_serial != info.hardware_serial:
        raise DiscoveryProbeError(
            candidate,
            "USB serial metadata changed before the INFO probe completed",
        )


def probe_candidate(
    candidate: SerialPortCandidate,
    *,
    timeout: float = DEFAULT_DISCOVERY_TIMEOUT,
    transport_factory: DiscoveryTransportFactory | None = None,
) -> DiscoveredDevice:
    """Open one plausible candidate and perform a short, read-only INFO probe.

    This direct form raises :class:`DiscoveryProbeError` on busy, denied,
    disconnected, timed-out, or incompatible candidates. :func:`discover`
    catches those per-candidate failures so the rest of a scan can continue.
    """

    selected_timeout = _validate_timeout(timeout)
    if candidate.vid != TEENSY_USB_SERIAL_VID or candidate.pid != TEENSY_USB_SERIAL_PID:
        raise DiscoveryProbeError(
            candidate, "candidate VID/PID is not Teensy USB Serial"
        )

    transport: ByteTransport | None = None
    reader: BackgroundReader | None = None
    try:
        if transport_factory is None:
            transport = _serial_transport_factory(candidate, selected_timeout)
        else:
            transport = transport_factory(candidate)
        reader = BackgroundReader(
            transport,
            max_pending_requests=1,
            max_queued_blocks=1,
            max_queued_events=1,
            request_timeout=selected_timeout,
            queue_timeout=selected_timeout,
            shutdown_timeout=selected_timeout,
        )
        reader.start()
        response = reader.request(
            constants.FrameKind.INFO_REQUEST,
            timeout=selected_timeout,
        )
        if (
            not response.ok
            or response.kind is not constants.FrameKind.INFO_RESPONSE
            or not isinstance(response.value, Info)
        ):
            raise DiscoveryProbeError(candidate, "device rejected or malformed INFO")
        _validate_physical_info(candidate, response.value)
        return DiscoveredDevice(candidate=candidate, info=response.value)
    except DiscoveryProbeError:
        raise
    except Exception as error:
        raise DiscoveryProbeError(candidate, "INFO probe failed", error) from error
    finally:
        if reader is not None:
            try:
                reader.close()
            except Exception:  # noqa: BLE001, S110 - bounded best-effort probe cleanup
                pass
        elif transport is not None:
            try:
                transport.close()
            except Exception:  # noqa: BLE001, S110 - bounded best-effort probe cleanup
                pass


def discover(
    timeout: float = DEFAULT_DISCOVERY_TIMEOUT,
    *,
    port_enumerator: PortEnumerator | None = None,
    transport_factory: DiscoveryTransportFactory | None = None,
) -> tuple[DiscoveredDevice, ...]:
    """Return every compatible DAQ found by one fresh metadata/probe scan.

    A failed, busy, access-denied, disconnected, or non-DAQ candidate is
    omitted without aborting the remaining scan. Calling ``discover`` again
    performs a fresh enumeration, so no COM/device path is cached as identity.
    """

    selected_timeout = _validate_timeout(timeout)
    devices: list[DiscoveredDevice] = []
    for candidate in enumerate_candidates(port_enumerator=port_enumerator):
        try:
            device = probe_candidate(
                candidate,
                timeout=selected_timeout,
                transport_factory=transport_factory,
            )
        except DiscoveryProbeError:
            continue
        devices.append(device)
    return tuple(devices)


def _matches_hardware_serial(
    device: DiscoveredDevice,
    hardware_serial: HardwareSerial,
) -> bool:
    if isinstance(hardware_serial, int) and not isinstance(hardware_serial, bool):
        return device.hardware_serial == hardware_serial
    if isinstance(hardware_serial, str):
        if device.serial_number == hardware_serial:
            return True
        serial_as_int = _usb_serial_as_int(hardware_serial)
        return serial_as_int is not None and device.hardware_serial == serial_as_int
    return False


def select_device(
    devices: Iterable[DiscoveredDevice],
    *,
    hardware_serial: HardwareSerial,
) -> DiscoveredDevice:
    """Select one current endpoint by INFO integer or USB string serial.

    Matching never uses the port path. If duplicate metadata entries describe
    the same serial, the preferred product metadata and current path ordering
    provide a deterministic endpoint for this scan.
    """

    if isinstance(hardware_serial, bool) or not isinstance(hardware_serial, (int, str)):
        raise TypeError("hardware_serial must be an integer or nonempty string")
    if isinstance(hardware_serial, int) and not (
        0 <= hardware_serial <= constants.UINT32_MAX
    ):
        raise ValueError("integer hardware_serial must be an unsigned 32-bit value")
    if isinstance(hardware_serial, str) and not hardware_serial:
        raise ValueError("hardware_serial string must be nonempty")

    matches = [
        device
        for device in devices
        if _matches_hardware_serial(device, hardware_serial)
    ]
    if not matches:
        raise DeviceNotFoundError(
            f"no discovered Teensy DAQ has hardware serial {hardware_serial!r}; "
            "perform a fresh discover() scan and verify USB/serial permissions"
        )
    return min(matches, key=lambda device: _candidate_sort_key(device.candidate))


__all__ = [
    "DEFAULT_DISCOVERY_TIMEOUT",
    "TEENSY_DAQ_PRODUCT",
    "TEENSY_USB_SERIAL_PID",
    "TEENSY_USB_SERIAL_VID",
    "DeviceIdentity",
    "DeviceNotFoundError",
    "DiscoveredDevice",
    "DiscoveryError",
    "DiscoveryProbeError",
    "HardwareSerial",
    "SerialPortCandidate",
    "discover",
    "enumerate_candidates",
    "probe_candidate",
    "select_device",
]
