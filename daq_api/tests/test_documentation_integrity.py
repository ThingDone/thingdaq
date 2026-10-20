"""Internal documentation links and executable snippet acceptance tests."""

from __future__ import annotations

import json
import os
import re
import shlex
import subprocess
import sys
import unittest
from pathlib import Path
from urllib.parse import unquote

from thingdone_daq._generated import protocol_v3_constants as v3
from thingdone_daq.cli import build_parser
from thingdone_daq.protocol_v3 import encode_adc_payload, encode_gpio_payload

REPOSITORY_ROOT = Path(__file__).resolve().parents[2]
PACKAGE_SOURCE = REPOSITORY_ROOT / "daq_api/src"
DOC_ROOT = REPOSITORY_ROOT / "doc"
MARKDOWN_FILES = (
    REPOSITORY_ROOT / "README.md",
    REPOSITORY_ROOT / "daq_api/README.md",
    *sorted(DOC_ROOT.rglob("*.md")),
)
MARKDOWN_LINK = re.compile(r"!?\[[^\]]*\]\(([^)]+)\)")
WIKI_LINK = re.compile(r"\[\[([^\]]+)\]\]")
PYTHON_FENCE = re.compile(
    r"^```python\s*\n(.*?)^```\s*$",
    re.MULTILINE | re.DOTALL,
)
URI_SCHEME = re.compile(r"^[A-Za-z][A-Za-z0-9+.-]*:")
CURRENT_GUIDES = (
    REPOSITORY_ROOT / "README.md",
    REPOSITORY_ROOT / "daq_api/README.md",
    DOC_ROOT / "README.md",
    DOC_ROOT / "guides/quickstart.md",
    DOC_ROOT / "guides/protocol-v3-migration.md",
    DOC_ROOT / "reference/api-reference.md",
)


def guide_cli_commands(document: Path) -> tuple[tuple[str, ...], ...]:
    """Share exact documented arguments with parser and built-wheel checks."""
    commands = []
    text = document.read_text().replace("\\\n", "")
    for fence in re.findall(r"^```bash\n(.*?)^```", text, re.MULTILINE | re.DOTALL):
        for line in fence.splitlines():
            args = shlex.split(line, comments=True)
            if not args:
                continue
            if Path(args[0]).name == "thingdone-daq":
                commands.append(tuple(args[1:]))
            elif args[1:3] == ["-m", "thingdone_daq.cli"]:
                commands.append(tuple(args[3:]))
    return tuple(commands)


def _python_fences(path: Path) -> tuple[tuple[int, str], ...]:
    text = path.read_text(encoding="utf-8")
    return tuple(
        (text.count("\n", 0, match.start()) + 1, match.group(1))
        for match in PYTHON_FENCE.finditer(text)
    )


class DocumentationIntegrityTests(unittest.TestCase):
    def test_every_relative_markdown_link_targets_an_existing_file(self) -> None:
        for document in MARKDOWN_FILES:
            text = document.read_text(encoding="utf-8")
            for raw_target in MARKDOWN_LINK.findall(text):
                target = raw_target.strip().split(maxsplit=1)[0].strip("<>")
                if not target or target.startswith("#") or URI_SCHEME.match(target):
                    continue
                relative = unquote(target.split("#", 1)[0].split("?", 1)[0])
                resolved = (document.parent / relative).resolve()
                with self.subTest(
                    document=document.relative_to(REPOSITORY_ROOT),
                    target=target,
                ):
                    self.assertTrue(
                        resolved.exists(), f"missing link target {resolved}"
                    )

    def test_every_wiki_link_resolves_to_one_document_filename(self) -> None:
        targets: dict[str, list[Path]] = {}
        for document in DOC_ROOT.rglob("*.md"):
            targets.setdefault(document.stem.casefold(), []).append(document)

        for document in MARKDOWN_FILES:
            text = document.read_text(encoding="utf-8")
            for raw_target in WIKI_LINK.findall(text):
                target = raw_target.split("|", 1)[0].split("#", 1)[0].strip()
                matches = targets.get(target.casefold(), [])
                with self.subTest(
                    document=document.relative_to(REPOSITORY_ROOT),
                    target=target,
                ):
                    self.assertEqual(
                        1,
                        len(matches),
                        f"wiki target resolves to {matches!r}",
                    )

    def test_all_python_fences_compile_and_simulator_fences_execute(self) -> None:
        runnable: list[tuple[Path, int, str]] = []
        for document in MARKDOWN_FILES:
            for line, code in _python_fences(document):
                with self.subTest(
                    document=document.relative_to(REPOSITORY_ROOT),
                    line=line,
                    action="compile",
                ):
                    compile(code, f"{document}:{line}", "exec")
                if "ThingDAQ.simulated" in code:
                    runnable.append((document, line, code))

        self.assertEqual(11, len(runnable))
        environment = {
            key: value
            for key in ("LANG", "LC_ALL", "PATH", "SYSTEMROOT", "TMPDIR")
            if (value := os.environ.get(key)) is not None
        }
        environment["PYTHONNOUSERSITE"] = "1"
        environment["PYTHONPATH"] = str(PACKAGE_SOURCE)
        guard = """
import socket
import serial

def forbidden(*args, **kwargs):
    raise AssertionError("simulator snippet attempted hardware or network access")

socket.create_connection = forbidden
socket.socket = forbidden
serial.Serial = forbidden
serial.serial_for_url = forbidden
"""
        for document, line, code in runnable:
            with self.subTest(
                document=document.relative_to(REPOSITORY_ROOT),
                line=line,
                action="execute",
            ):
                completed = subprocess.run(
                    [sys.executable, "-c", guard + "\n" + code],
                    cwd=REPOSITORY_ROOT,
                    env=environment,
                    capture_output=True,
                    check=False,
                    text=True,
                    timeout=30,
                )
                self.assertEqual(
                    0,
                    completed.returncode,
                    completed.stdout + completed.stderr,
                )
                self.assertEqual("", completed.stderr)

    def test_quickstart_lists_every_public_example(self) -> None:
        quickstart = (DOC_ROOT / "guides/quickstart.md").read_text(encoding="utf-8")
        documented = {
            name
            for name in re.findall(r"daq_api/examples/([A-Za-z0-9_]+\.py)", quickstart)
            if not name.startswith("_")
        }
        public_examples = {
            path.name
            for path in (REPOSITORY_ROOT / "daq_api/examples").glob("*.py")
            if not path.name.startswith("_")
        }

        self.assertEqual(public_examples, documented)

    def test_v3_contract_tables_match_canonical_schema(self) -> None:
        schema = json.loads((REPOSITORY_ROOT / "protocol/protocol-v3.json").read_text())
        document = (DOC_ROOT / "protocol/protocol-v3.md").read_text()
        for fields in (
            schema["header"]["fields"],
            schema["payload_schemas"]["settings"]["fields"],
        ):
            for field in fields:
                self.assertIn(
                    f"| {field['offset']} | {field['type']} | `{field['name']}` |",
                    document,
                )
        kinds = {kind["name"]: kind for kind in schema["frame_kinds"]}
        for kind in kinds.values():
            if kind["class"] != "request":
                continue
            response = kinds[kind["response_kind"]]
            name = kind["name"].removesuffix("_REQUEST")
            if name == "GET_STATUS":
                name += " (STATUS)"
            request_size = schema["payload_schemas"][kind["payload_schema"]]["size"]
            response_size = schema["payload_schemas"][response["payload_schema"]][
                "size"
            ]
            self.assertIn(
                f"| {name} | `0x{kind['value']:02X} / 0x{response['value']:02X}` "
                f"| {request_size} | {response_size} |",
                document,
            )
        for error in schema["enums"]["error_code"]:
            self.assertIn(f"| {error['name']} | {error['value']} |", document)

    def test_current_guide_cli_commands_parse_without_hardware(self) -> None:
        parser = build_parser()
        for document in CURRENT_GUIDES:
            commands = guide_cli_commands(document)
            self.assertTrue(commands, str(document))
            for args in commands:
                with self.subTest(document=document, command=args):
                    parser.parse_args(args)

    def test_v3_documented_packing_examples_match_runtime(self) -> None:
        document = (DOC_ROOT / "protocol/protocol-v3.md").read_text()
        cases = (
            (
                encode_adc_payload([(0xABC, 0x123)], policy=v3.AdcPolicy.RAW),
                "BC 0A 23 01",
            ),
            (encode_adc_payload([(0xABC, 0x123)]), "BC 3A 12"),
            (encode_adc_payload([(0, 0), (4095, 4095)]), "00 00 00 FF FF FF"),
            (
                encode_gpio_payload([0xAA] * 6 + [0x55] * 4, width_bits=8),
                "06 00 AA 04 00 55",
            ),
            (encode_gpio_payload([0x1234] * 3, width_bits=16), "03 00 34 12"),
            (encode_gpio_payload([0xAA] * 3, width_bits=8), "AA AA AA"),
        )
        for payload, expected in cases:
            with self.subTest(expected=expected):
                self.assertIn(f"`{expected}`", document)
                self.assertEqual(bytes.fromhex(expected), payload[12:])
        for payload in (cases[1][0], cases[3][0]):
            self.assertIn(f"`{payload[:12].hex(' ').upper()}`", document)


if __name__ == "__main__":
    unittest.main()
