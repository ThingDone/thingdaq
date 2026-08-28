"""Tests for metadata-first, bounded physical-device discovery."""

from __future__ import annotations

import threading
import unittest
from dataclasses import dataclass

from teensy_daq import (
    BoardId,
    ByteTransport,
    DeviceNotFoundError,
    DeviceState,
    DiscoveryProbeError,
    FrameKind,
    Info,
    McuId,
    SerialPortCandidate,
    TransportClosedError,
    TransportDisconnectedError,
    TransportOpenError,
    decode_frame,
    discover,
    encode_frame,
    enumerate_candidates,
    probe_candidate,
    select_device,
)

TEENSY_VID = 0x16C0
TEENSY_PID = 0x0483


@dataclass(slots=True)
class FakePortMetadata:
    device: str
    vid: int | None
    pid: int | None
    serial_number: str | None = None
    product: str | None = None
    manufacturer: str | None = None
    location: str | None = None
    interface: str | None = None
    description: str = "n/a"


class InfoProbeTransport:
    """Thread-safe byte transport that answers only an INFO request."""

    def __init__(self, info: Info | None, *, fragment_size: int = 11) -> None:
        self.info = info
        self.fragment_size = fragment_size
        self._pending = bytearray()
        self._is_open = True
        self._lock = threading.Lock()
        self.writes: list[bytes] = []
        self.closed = threading.Event()

    @property
    def is_open(self) -> bool:
        with self._lock:
            return self._is_open

    def write(self, data: bytes | bytearray | memoryview) -> int:
        wire = bytes(data)
        with self._lock:
            if not self._is_open:
                raise TransportClosedError("probe transport is closed")
            self.writes.append(wire)
            request = decode_frame(wire)
            if request.header.kind is not FrameKind.INFO_REQUEST:
                raise AssertionError("discovery sent a non-INFO command")
            if self.info is not None:
                self._pending.extend(
                    encode_frame(
                        FrameKind.INFO_RESPONSE,
                        self.info.to_payload(),
                        request_id=request.header.request_id,
                    )
                )
            return len(wire)

    def read(self, size: int) -> bytes:
        with self._lock:
            if not self._is_open:
                raise TransportClosedError("probe transport is closed")
            returned = min(size, self.fragment_size, len(self._pending))
            result = bytes(self._pending[:returned])
            del self._pending[:returned]
            return result

    def flush(self) -> None:
        if not self.is_open:
            raise TransportClosedError("probe transport is closed")

    def close(self) -> None:
        with self._lock:
            self._is_open = False
            self._pending.clear()
            self.closed.set()


class DisconnectingProbeTransport(InfoProbeTransport):
    """Accept one INFO request, then disappear before returning a response."""

    def read(self, size: int) -> bytes:
        raise TransportDisconnectedError("candidate disconnected during INFO")


def _physical_info(hardware_serial: int, build_id: str = "physical-v1") -> Info:
    return Info(
        device_state=DeviceState.IDLE,
        build_id=build_id,
        hardware_serial=hardware_serial,
        firmware_version=(1, 2, 3),
        board_id=BoardId.TEENSY_40,
        mcu_id=McuId.IMXRT1062,
    )


def _candidate(
    port: str,
    hardware_serial: int,
    *,
    product: str | None = "Teensy DAQ",
) -> FakePortMetadata:
    return FakePortMetadata(
        device=port,
        vid=TEENSY_VID,
        pid=TEENSY_PID,
        serial_number=str(hardware_serial),
        product=product,
        manufacturer="PJRC",
        location="1-2.3",
        interface="CDC",
        description=product or "USB Serial",
    )


class EnumerationTests(unittest.TestCase):
    def test_filters_without_opening_and_preserves_metadata(self) -> None:
        ports = [
            FakePortMetadata("COM1", 0x1234, 0x5678, product="Unrelated"),
            _candidate("COM9", 900, product="USB Serial"),
            _candidate("COM4", 400, product=None),
            _candidate("COM7", 700),
        ]
        calls = 0

        def enumerate_ports() -> list[FakePortMetadata]:
            nonlocal calls
            calls += 1
            return ports

        candidates = enumerate_candidates(port_enumerator=enumerate_ports)

        self.assertEqual(1, calls)
        self.assertEqual(["COM7", "COM4", "COM9"], [item.port for item in candidates])
        preferred = candidates[0]
        self.assertTrue(preferred.preferred_product)
        self.assertEqual(TEENSY_VID, preferred.vid)
        self.assertEqual(TEENSY_PID, preferred.pid)
        self.assertEqual("700", preferred.serial_number)
        self.assertEqual("PJRC", preferred.manufacturer)
        self.assertEqual("1-2.3", preferred.location)
        self.assertEqual("CDC", preferred.interface)


class DiscoveryTests(unittest.TestCase):
    def test_probes_only_matching_vid_pid_and_returns_every_valid_daq(self) -> None:
        ports = [
            FakePortMetadata("COM1", 0x1234, 0x5678, product="Serial Mouse"),
            _candidate("COM8", 800, product="USB Serial"),
            _candidate("COM3", 300),
            _candidate("COM5", 500, product=None),
            _candidate("COM6", 600),
        ]
        opened: list[str] = []
        transports: list[InfoProbeTransport] = []

        def transport_factory(candidate: SerialPortCandidate) -> ByteTransport:
            opened.append(candidate.port)
            if candidate.port == "COM5":
                raise TransportOpenError("access denied")
            info = (
                Info(device_state=DeviceState.IDLE, build_id="not-hardware")
                if candidate.port == "COM6"
                else _physical_info(int(candidate.serial_number or "0"))
            )
            transport = InfoProbeTransport(info)
            transports.append(transport)
            return transport

        devices = discover(
            0.05,
            port_enumerator=lambda: ports,
            transport_factory=transport_factory,
        )

        self.assertEqual(["COM3", "COM6", "COM5", "COM8"], opened)
        self.assertNotIn("COM1", opened)
        self.assertEqual(["COM3", "COM8"], [device.port for device in devices])
        self.assertEqual([300, 800], [device.hardware_serial for device in devices])
        self.assertEqual("PJRC", devices[0].manufacturer)
        self.assertEqual("USB Serial", devices[1].product)
        self.assertTrue(all(transport.closed.is_set() for transport in transports))
        self.assertTrue(all(len(transport.writes) == 1 for transport in transports))

    def test_timeout_or_stale_metadata_does_not_abort_other_candidates(self) -> None:
        ports = [
            _candidate("COM2", 200),
            _candidate("COM3", 300),
            _candidate("COM4", 400),
        ]
        transports: dict[str, InfoProbeTransport] = {}

        def transport_factory(candidate: SerialPortCandidate) -> ByteTransport:
            info = {
                "COM2": None,
                "COM3": _physical_info(999),
                "COM4": _physical_info(400),
            }[candidate.port]
            transport = InfoProbeTransport(info)
            transports[candidate.port] = transport
            return transport

        devices = discover(
            0.02,
            port_enumerator=lambda: ports,
            transport_factory=transport_factory,
        )

        self.assertEqual(["COM4"], [device.port for device in devices])
        self.assertTrue(
            all(transport.closed.is_set() for transport in transports.values())
        )

    def test_product_fallback_is_bounded_and_all_candidate_failures_are_isolated(
        self,
    ) -> None:
        ports = [
            FakePortMetadata(
                "COM0",
                0x9999,
                0x0001,
                serial_number="0",
                product="Teensy DAQ",
            ),
            _candidate("COM1", 101),
            _candidate("COM2", 102),
            _candidate("COM3", 103, product=None),
            _candidate("COM4", 104, product=None),
            _candidate("COM5", 105, product="USB Serial"),
            _candidate("COM6", 106, product="USB Serial"),
        ]
        opened: list[str] = []
        transports: dict[str, InfoProbeTransport] = {}

        def transport_factory(candidate: SerialPortCandidate) -> ByteTransport:
            opened.append(candidate.port)
            if candidate.port == "COM2":
                raise TransportOpenError("access denied")
            if candidate.port == "COM3":
                transport: InfoProbeTransport = InfoProbeTransport(None)
            elif candidate.port == "COM5":
                transport = DisconnectingProbeTransport(_physical_info(105))
            else:
                transport = InfoProbeTransport(
                    _physical_info(int(candidate.serial_number or "0")),
                    fragment_size=3,
                )
            transports[candidate.port] = transport
            return transport

        devices = discover(
            0.03,
            port_enumerator=lambda: ports,
            transport_factory=transport_factory,
        )

        self.assertEqual(
            ["COM1", "COM2", "COM3", "COM4", "COM5", "COM6"],
            opened,
        )
        self.assertNotIn("COM0", opened)
        self.assertEqual(
            [101, 104, 106], [device.hardware_serial for device in devices]
        )
        self.assertEqual(
            ["Teensy DAQ", None, "USB Serial"],
            [device.product for device in devices],
        )
        self.assertEqual(1, len(transports["COM3"].writes))
        self.assertTrue(
            all(len(transport.writes) <= 1 for transport in transports.values())
        )
        self.assertTrue(
            all(transport.closed.is_set() for transport in transports.values())
        )

    def test_direct_probe_rejects_nonmatching_metadata_without_opening(self) -> None:
        candidate = SerialPortCandidate("COM1", 0x1234, 0x5678)
        factory_called = False

        def transport_factory(candidate: SerialPortCandidate) -> ByteTransport:
            nonlocal factory_called
            factory_called = True
            return InfoProbeTransport(_physical_info(1))

        with self.assertRaises(DiscoveryProbeError):
            probe_candidate(candidate, transport_factory=transport_factory)

        self.assertFalse(factory_called)

    def test_stable_serial_selection_survives_port_rename(self) -> None:
        first = discover(
            0.05,
            port_enumerator=lambda: [_candidate("COM3", 12345670)],
            transport_factory=lambda candidate: InfoProbeTransport(
                _physical_info(12345670)
            ),
        )[0]
        second = discover(
            0.05,
            port_enumerator=lambda: [_candidate("COM19", 12345670)],
            transport_factory=lambda candidate: InfoProbeTransport(
                _physical_info(12345670)
            ),
        )[0]

        self.assertNotEqual(first.port, second.port)
        self.assertEqual(first.identity, second.identity)
        self.assertEqual(
            "COM19",
            select_device([second], hardware_serial=12345670).port,
        )
        self.assertEqual(
            "COM19",
            select_device([second], hardware_serial="12345670").port,
        )
        with self.assertRaises(DeviceNotFoundError):
            select_device([second], hardware_serial=77)


if __name__ == "__main__":
    unittest.main()
