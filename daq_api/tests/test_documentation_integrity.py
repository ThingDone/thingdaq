"""Internal documentation links and executable snippet acceptance tests."""

from __future__ import annotations

import os
import re
import subprocess
import sys
import unittest
from pathlib import Path
from urllib.parse import unquote

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

        self.assertEqual(3, len(runnable))
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


if __name__ == "__main__":
    unittest.main()
