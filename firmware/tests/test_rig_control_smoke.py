"""Offline verification for the independent ThingDAQ 1.0 basic rig script."""

from __future__ import annotations

import ast
import importlib.util
import io
import os
import sys
import time
import unittest
from contextlib import redirect_stdout
from dataclasses import replace
from pathlib import Path
from types import ModuleType
from unittest.mock import patch

from thingdaq import (
    BoardId,
    Capability,
    ConfigurationProfile,
    GpioCaptureDiagnosticFlag,
    Info,
    McuId,
    SimulatedDevice,
    Source,
    StreamMask,
)

ROOT = Path(__file__).resolve().parents[2]
RIG_SCRIPT = ROOT / "firmware" / "tests" / "rig_control_smoke.py"
FIXTURES = ROOT / "protocol" / "fixtures"


def _load_rig_script() -> ModuleType:
    specification = importlib.util.spec_from_file_location(
        "independent_rig_control_smoke",
        RIG_SCRIPT,
    )
    if specification is None or specification.loader is None:
        raise RuntimeError("could not load rig_control_smoke.py")
    module = importlib.util.module_from_spec(specification)
    sys.modules[specification.name] = module
    specification.loader.exec_module(module)
    return module


rig = _load_rig_script()


class ProductionControlDevice(SimulatedDevice):
    """Simulator with the production 1.0 control and capability identity."""

    def __init__(self) -> None:
        super().__init__(
            control_only=False,
            build_id="thingdaq-0123456789abcdef",
        )

    def _handle_info(self, request):  # type: ignore[no-untyped-def]
        configuration = self.configuration
        info = Info(
            device_state=self.state,
            build_id="thingdaq-0123456789abcdef",
            hardware_serial=12_345_670,
            firmware_version=(1, 0, 0),
            board_id=BoardId.TEENSY_40,
            mcu_id=McuId.IMXRT1062,
            supported_stream_mask=StreamMask.ADC | StreamMask.GPIO,
            supported_source_mask=0b11,
            supported_configuration_mask=(
                ConfigurationProfile.HARDWARE_ADC
                | ConfigurationProfile.HARDWARE_GPIO
                | ConfigurationProfile.HARDWARE_COMBINED
                | ConfigurationProfile.SYNTHETIC_ADC
                | ConfigurationProfile.SYNTHETIC_GPIO
                | ConfigurationProfile.SYNTHETIC_COMBINED
            ),
            applied_stream_mask=(
                configuration.stream_mask
                if configuration is not None
                else StreamMask.NONE
            ),
            applied_source=(
                configuration.source if configuration is not None else Source.HARDWARE
            ),
            capability_bits=(
                Capability.ADC_STREAM
                | Capability.GPIO_STREAM
                | Capability.HARDWARE_SOURCE
                | Capability.SYNTHETIC_SOURCE
                | Capability.RESET_STATS
                | Capability.PING
                | Capability.CHECKSUM_BENCHMARK
                | Capability.GPIO_CLOCK_DIAGNOSTIC
                | Capability.GPIO_CAPTURE_DIAGNOSTIC
            ),
            gpio_capture_diagnostic_flags=(
                GpioCaptureDiagnosticFlag.AVAILABLE
                | GpioCaptureDiagnosticFlag.DECLARATION_VALID
            ),
        )
        return self._success_response(request, info.to_payload())

    def status(self):  # type: ignore[no-untyped-def]
        status = super().status()
        if self.configuration is None:
            return replace(status, source=Source.HARDWARE)
        return status


class FakeRigSerial:
    """PySerial-shaped physical peer with startup noise and partial I/O."""

    def __init__(self) -> None:
        self.device = ProductionControlDevice()
        self.timeout = 0.001
        self.write_timeout = 0.1
        self.is_open = True
        self.pending = bytearray(b"late reset text\r\n\xef\xbe")
        self.read_pattern = (1, 7, 2, 13, 3)
        self.write_pattern = (1, 0, 5, 2, 11)
        self.read_index = 0
        self.write_index = 0
        self.read_counts: list[int] = []
        self.write_counts: list[int] = []

    def read(self, size: int = 1) -> bytes:
        if not self.is_open:
            raise RuntimeError("fake serial port is closed")
        if not self.pending:
            time.sleep(min(self.timeout, 0.0001))
            self.read_counts.append(0)
            return b""
        limit = self.read_pattern[self.read_index % len(self.read_pattern)]
        self.read_index += 1
        count = min(size, limit, len(self.pending))
        result = bytes(self.pending[:count])
        del self.pending[:count]
        self.read_counts.append(count)
        return result

    def write(self, data: bytes | bytearray | memoryview) -> int:
        if not self.is_open:
            raise RuntimeError("fake serial port is closed")
        wire = bytes(data)
        limit = self.write_pattern[self.write_index % len(self.write_pattern)]
        self.write_index += 1
        count = min(len(wire), limit)
        self.write_counts.append(count)
        if count:
            for response in self.device.receive(wire[:count]):
                self.pending.extend(response)
        return count

    def close(self) -> None:
        self.is_open = False


class RigScriptIndependenceTests(unittest.TestCase):
    def test_script_is_single_file_standard_library_plus_pyserial(self) -> None:
        source = RIG_SCRIPT.read_text(encoding="utf-8")
        tree = ast.parse(source)
        imports: set[str] = set()
        for node in ast.walk(tree):
            if isinstance(node, ast.Import):
                imports.update(alias.name.split(".", 1)[0] for alias in node.names)
            elif isinstance(node, ast.ImportFrom) and node.module is not None:
                imports.add(node.module.split(".", 1)[0])

        self.assertEqual(
            {
                "__future__",
                "dataclasses",
                "os",
                "re",
                "serial",
                "struct",
                "sys",
                "time",
                "typing",
                "zlib",
            },
            imports,
        )
        self.assertNotIn("import thingdaq", source)
        self.assertNotIn("from thingdaq", source)
        self.assertNotIn("protocol-v1.json", source)
        self.assertIn('os.environ.get("SERIAL_PORT")', source)

    def test_independent_encoder_and_parser_match_every_control_fixture(self) -> None:
        for path in sorted(FIXTURES.glob("*-request.bin")):
            expected = path.read_bytes()
            kind = expected[5]
            request_id = int.from_bytes(expected[28:32], "little")
            payload = expected[rig.HEADER_SIZE : -rig.TRAILER_SIZE]
            with self.subTest(request=path.name):
                self.assertEqual(
                    expected,
                    rig.encode_request(kind, request_id, payload),
                )

        for path in sorted(FIXTURES.glob("*-response.bin")):
            expected = path.read_bytes()
            parser = rig.FrameParser()
            decoded = []
            prefix = b"reset noise\xef\xbe"
            for byte in prefix + expected:
                decoded.extend(parser.feed(bytes((byte,))))
            with self.subTest(response=path.name):
                self.assertEqual(1, len(decoded))
                self.assertEqual(expected[5], decoded[0].kind)
                self.assertEqual(
                    int.from_bytes(expected[28:32], "little"),
                    decoded[0].request_id,
                )
                self.assertGreaterEqual(parser.bytes_discarded, len(prefix))

    def test_full_rig_flow_passes_with_reset_noise_and_partial_io(self) -> None:
        fake = FakeRigSerial()
        output = io.StringIO()
        with (
            patch.object(rig, "STARTUP_DRAIN_SECONDS", 0.002),
            patch.object(rig, "SYNC_DEADLINE_SECONDS", 0.1),
            patch.object(rig, "COMMAND_DEADLINE_SECONDS", 0.2),
            patch.object(rig, "CORRUPT_SILENCE_SECONDS", 0.002),
            patch.object(rig.serial, "Serial", return_value=fake),
            patch.dict(os.environ, {"SERIAL_PORT": "fake-rig-port"}),
            redirect_stdout(output),
        ):
            exit_code = rig.main()

        self.assertEqual(0, exit_code, output.getvalue())
        self.assertIn("PASS: ThingDAQ 1.0 identity", output.getvalue())
        self.assertIn("invalid CONFIGURE error", output.getvalue())
        self.assertIn("final parser_errors", output.getvalue())
        self.assertFalse(fake.is_open)
        self.assertIn(0, fake.write_counts)
        self.assertLessEqual(max(fake.read_counts), max(fake.read_pattern))


if __name__ == "__main__":
    unittest.main()
