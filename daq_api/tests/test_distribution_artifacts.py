"""Acceptance tests for built wheel/sdist contents and console metadata."""

from __future__ import annotations

import configparser
import os
import re
import shutil
import subprocess
import sys
import tarfile
import tempfile
import unittest
import zipfile
from email import policy
from email.parser import Parser
from pathlib import Path, PurePosixPath
from typing import ClassVar

from thingdaq import __version__

PACKAGE_ROOT = Path(__file__).resolve().parents[1]
TEXT_MEMBER_SUFFIXES = {".cfg", ".md", ".py", ".toml", ".txt"}
FORBIDDEN_PATH_PARTS = {
    "build",
    "captures",
    "credentials",
    "dist",
    "secrets",
    "tests",
}
FORBIDDEN_PRIVATE_SUFFIXES = {
    ".bin",
    ".csv",
    ".elf",
    ".hex",
    ".json",
    ".key",
    ".map",
    ".npy",
    ".npz",
    ".pem",
}
PUBLICATION_COMMANDS = (
    re.compile(r"\bpython(?:3)?\s+-m\s+twine\s+upload\b", re.IGNORECASE),
    re.compile(r"\btwine\s+upload\b", re.IGNORECASE),
    re.compile(r"\buv\s+publish\b", re.IGNORECASE),
    re.compile(r"\bpoetry\s+publish\b", re.IGNORECASE),
    re.compile(r"\bhatch\s+publish\b", re.IGNORECASE),
    re.compile(r"\bflit\s+publish\b", re.IGNORECASE),
)


def _metadata(contents: bytes):  # type: ignore[no-untyped-def]
    return Parser(policy=policy.default).parsestr(contents.decode("utf-8"))


class DistributionArtifactTests(unittest.TestCase):
    """Build once, then independently inspect both distribution formats."""

    wheel_path: ClassVar[Path]
    sdist_path: ClassVar[Path]
    wheel_files: ClassVar[dict[str, bytes]]
    sdist_files: ClassVar[dict[str, bytes]]

    @classmethod
    def setUpClass(cls) -> None:
        temporary = tempfile.TemporaryDirectory()
        cls.addClassCleanup(temporary.cleanup)
        workspace = Path(temporary.name)
        source = workspace / "daq_api"
        shutil.copytree(
            PACKAGE_ROOT,
            source,
            ignore=shutil.ignore_patterns(
                "*.egg-info",
                "__pycache__",
                ".mypy_cache",
                ".pytest_cache",
                ".ruff_cache",
                "build",
                "dist",
            ),
        )

        # These sentinels prove the exclusion rules instead of merely relying
        # on the checkout to contain no private build inputs.
        bait = {
            ".env": "PYPI_TOKEN=must-not-ship\n",
            "calibration.json": '{"local": true}\n',
            "build/generated.py": "raise AssertionError('must not ship')\n",
            "captures/bulk-capture.bin": "bulk capture sentinel\n",
            "credentials/pypi-token.txt": "credential sentinel\n",
            "dist/old-build.whl": "old build sentinel\n",
            "src/thingdaq/captures/raw.npy": "bulk array sentinel\n",
            "src/thingdaq/credentials/operator.pem": "credential sentinel\n",
            "src/thingdaq/local-calibration.json": '{"local": true}\n',
        }
        for relative, contents in bait.items():
            path = source / relative
            path.parent.mkdir(parents=True, exist_ok=True)
            path.write_text(contents, encoding="utf-8")

        output = workspace / "artifacts"
        environment = os.environ.copy()
        environment.update(
            {
                "PIP_DISABLE_PIP_VERSION_CHECK": "1",
                "PYTHONHASHSEED": "0",
                "SOURCE_DATE_EPOCH": "1787986800",
            }
        )
        completed = subprocess.run(
            [
                sys.executable,
                "-m",
                "build",
                "--outdir",
                str(output),
                str(source),
            ],
            cwd=workspace,
            env=environment,
            capture_output=True,
            check=False,
            text=True,
            timeout=120,
        )
        if completed.returncode:
            raise AssertionError(
                "distribution build failed:\n"
                f"stdout:\n{completed.stdout}\nstderr:\n{completed.stderr}"
            )

        wheels = tuple(output.glob("*.whl"))
        sdists = tuple(output.glob("*.tar.gz"))
        if len(wheels) != 1 or len(sdists) != 1:
            raise AssertionError(
                f"expected one wheel and one sdist, found {wheels!r}, {sdists!r}"
            )
        cls.wheel_path = wheels[0]
        cls.sdist_path = sdists[0]

        with zipfile.ZipFile(cls.wheel_path) as archive:
            cls.wheel_files = {
                name: archive.read(name)
                for name in archive.namelist()
                if not name.endswith("/")
            }
        with tarfile.open(cls.sdist_path, "r:gz") as archive:
            cls.sdist_files = {}
            for member in archive.getmembers():
                if not member.isfile():
                    continue
                extracted = archive.extractfile(member)
                if extracted is None:
                    raise AssertionError(f"could not read sdist member {member.name}")
                parts = PurePosixPath(member.name).parts
                normalized = PurePosixPath(*parts[1:]).as_posix()
                cls.sdist_files[normalized] = extracted.read()

    def test_wheel_contains_exact_runtime_sources_and_typed_marker(self) -> None:
        expected_runtime = {
            path.relative_to(PACKAGE_ROOT / "src").as_posix()
            for path in (PACKAGE_ROOT / "src/thingdaq").rglob("*.py")
        }
        expected_runtime.add("thingdaq/py.typed")
        observed_runtime = {
            name for name in self.wheel_files if name.startswith("thingdaq/")
        }

        self.assertEqual(expected_runtime, observed_runtime)
        self.assertTrue(
            any(name.endswith(".dist-info/RECORD") for name in self.wheel_files)
        )

    def test_sdist_contains_runtime_and_all_examples_but_not_tests(self) -> None:
        expected_runtime = {
            "src/" + path.relative_to(PACKAGE_ROOT / "src").as_posix()
            for path in (PACKAGE_ROOT / "src/thingdaq").rglob("*.py")
        }
        expected_runtime.add("src/thingdaq/py.typed")
        expected_examples = {
            path.relative_to(PACKAGE_ROOT).as_posix()
            for path in (PACKAGE_ROOT / "examples").glob("*.py")
        }

        self.assertTrue(expected_runtime.issubset(self.sdist_files))
        self.assertTrue(expected_examples.issubset(self.sdist_files))
        self.assertTrue(
            {
                "LICENSE",
                "MANIFEST.in",
                "README.md",
                "pyproject.toml",
                "PKG-INFO",
            }.issubset(self.sdist_files)
        )

    def test_license_is_included_in_both_distribution_formats(self) -> None:
        expected = (PACKAGE_ROOT / "LICENSE").read_bytes()
        wheel_license_names = [
            name
            for name in self.wheel_files
            if name.endswith(".dist-info/licenses/LICENSE")
        ]

        self.assertEqual(1, len(wheel_license_names))
        self.assertEqual(expected, self.wheel_files[wheel_license_names[0]])
        self.assertEqual(expected, self.sdist_files["LICENSE"])

    def test_archive_metadata_matches_private_typed_project(self) -> None:
        wheel_metadata_name = next(
            name for name in self.wheel_files if name.endswith(".dist-info/METADATA")
        )
        wheel_metadata = _metadata(self.wheel_files[wheel_metadata_name])
        sdist_metadata = _metadata(self.sdist_files["PKG-INFO"])

        for metadata in (wheel_metadata, sdist_metadata):
            with self.subTest(archive=metadata["Name"]):
                self.assertEqual("thingdaq-local", metadata["Name"])
                self.assertEqual(__version__, metadata["Version"])
                self.assertEqual("<3.15,>=3.10", metadata["Requires-Python"])
                self.assertIn(
                    "Private :: Do Not Upload",
                    metadata.get_all("Classifier", []),
                )
                self.assertIn(
                    "Typing :: Typed",
                    metadata.get_all("Classifier", []),
                )
                requirements = metadata.get_all("Requires-Dist", [])
                self.assertEqual(
                    ["pyserial>=3.5"],
                    [item for item in requirements if "extra ==" not in item],
                )
                self.assertEqual(
                    {"dev", "numpy"}, set(metadata.get_all("Provides-Extra"))
                )
                self.assertIsNone(metadata.get("License"))
                self.assertEqual("MIT", metadata.get("License-Expression"))

        wheel_descriptor_name = next(
            name for name in self.wheel_files if name.endswith(".dist-info/WHEEL")
        )
        wheel_descriptor = _metadata(self.wheel_files[wheel_descriptor_name])
        self.assertEqual("true", wheel_descriptor["Root-Is-Purelib"])
        self.assertEqual(["py3-none-any"], wheel_descriptor.get_all("Tag"))

    def test_console_metadata_targets_execute_from_the_built_wheel(self) -> None:
        entry_points_name = next(
            name
            for name in self.wheel_files
            if name.endswith(".dist-info/entry_points.txt")
        )
        parser = configparser.ConfigParser()
        parser.read_string(self.wheel_files[entry_points_name].decode("utf-8"))
        self.assertEqual(
            {
                "thingdaq": "thingdaq.cli:main",
                "thingdaq-demo": "thingdaq.demo:main",
                "thingdaq-soak": "thingdaq.soak:main",
            },
            dict(parser["console_scripts"]),
        )

        environment = os.environ.copy()
        environment["PYTHONPATH"] = os.pathsep.join(
            filter(
                None,
                (str(self.wheel_path), environment.get("PYTHONPATH")),
            )
        )
        cases = (
            (
                (
                    "from thingdaq.cli import main; "
                    "raise SystemExit(main(['info', '--simulate', '--json']))"
                ),
                '"device_state":"IDLE"',
            ),
            (
                (
                    "from thingdaq.demo import main; "
                    "raise SystemExit(main(['--frame-count','1',"
                    "'--parser-chunk-size','31']))"
                ),
                "PASS      validated 1 ADC + 1 GPIO frames",
            ),
            (
                (
                    "from thingdaq.soak import main; "
                    "raise SystemExit(main(['--conformance-check']))"
                ),
                'SOAK_CONFORMANCE {"commands":',
            ),
        )
        wheel_import_guard = (
            "import thingdaq; "
            "assert '.whl/' in thingdaq.__file__.replace('\\\\', '/'); "
        )
        for program, expected in cases:
            with self.subTest(expected=expected):
                completed = subprocess.run(
                    [sys.executable, "-c", wheel_import_guard + program],
                    cwd=PACKAGE_ROOT.parent,
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
                rendered = (
                    completed.stdout.replace(" ", "")
                    if expected.startswith('"')
                    else completed.stdout
                )
                self.assertIn(expected, rendered)
                self.assertEqual("", completed.stderr)

    def test_no_private_or_publication_material_is_packaged(self) -> None:
        for archive_name, members in (
            ("wheel", self.wheel_files),
            ("sdist", self.sdist_files),
        ):
            for name, contents in members.items():
                with self.subTest(archive=archive_name, member=name):
                    path = PurePosixPath(name)
                    lowered_parts = {part.casefold() for part in path.parts}
                    self.assertTrue(FORBIDDEN_PATH_PARTS.isdisjoint(lowered_parts))
                    self.assertNotIn(path.name.casefold(), {".env", "calibration.json"})
                    self.assertNotIn(path.suffix.casefold(), FORBIDDEN_PRIVATE_SUFFIXES)
                    if path.suffix.casefold() in TEXT_MEMBER_SUFFIXES:
                        text = contents.decode("utf-8")
                        for command in PUBLICATION_COMMANDS:
                            self.assertIsNone(command.search(text))


if __name__ == "__main__":
    unittest.main()
