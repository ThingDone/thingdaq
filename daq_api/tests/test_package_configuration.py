"""Tests for the local-only Python distribution configuration."""

from __future__ import annotations

import re
import unittest
from pathlib import Path
from typing import Any, ClassVar

import tomllib
from teensy_daq import __version__

PACKAGE_ROOT = Path(__file__).resolve().parents[1]
PYPROJECT_PATH = PACKAGE_ROOT / "pyproject.toml"
MANIFEST_PATH = PACKAGE_ROOT / "MANIFEST.in"
PACKAGE_README_PATH = PACKAGE_ROOT / "README.md"
TYPED_MARKER_PATH = PACKAGE_ROOT / "src/teensy_daq/py.typed"


class PackageConfigurationTests(unittest.TestCase):
    pyproject: ClassVar[dict[str, Any]]

    @classmethod
    def setUpClass(cls) -> None:
        with PYPROJECT_PATH.open("rb") as pyproject_file:
            cls.pyproject = tomllib.load(pyproject_file)

    def test_distribution_is_an_explicit_local_placeholder(self) -> None:
        project = self.pyproject["project"]

        self.assertTrue(project["name"].endswith("-local"))
        self.assertEqual(
            {"file": "README.md", "content-type": "text/markdown"},
            project["readme"],
        )
        self.assertEqual(">=3.10,<3.15", project["requires-python"])
        self.assertIn("Private :: Do Not Upload", project["classifiers"])

    def test_semantic_version_has_one_runtime_source(self) -> None:
        project = self.pyproject["project"]
        dynamic = self.pyproject["tool"]["setuptools"]["dynamic"]

        self.assertNotIn("version", project)
        self.assertEqual(["version"], project["dynamic"])
        self.assertEqual(
            "teensy_daq._version.__version__",
            dynamic["version"]["attr"],
        )
        self.assertIsNotNone(
            re.fullmatch(
                r"(0|[1-9]\d*)\.(0|[1-9]\d*)\.(0|[1-9]\d*)"
                r"(?:[-+][0-9A-Za-z.-]+)?",
                __version__,
            )
        )

    def test_build_backend_and_supported_python_versions_are_explicit(self) -> None:
        build_system = self.pyproject["build-system"]
        classifiers = self.pyproject["project"]["classifiers"]

        self.assertEqual("setuptools.build_meta", build_system["build-backend"])
        self.assertEqual(["setuptools==84.0.0"], build_system["requires"])
        for minor in range(10, 15):
            with self.subTest(minor=minor):
                self.assertIn(
                    f"Programming Language :: Python :: 3.{minor}",
                    classifiers,
                )
        self.assertIn("Typing :: Typed", classifiers)

    def test_runtime_and_optional_dependencies_are_separated(self) -> None:
        project = self.pyproject["project"]
        extras = project["optional-dependencies"]

        self.assertTrue(
            any(item.startswith("pyserial") for item in project["dependencies"])
        )
        self.assertTrue(any(item.startswith("numpy") for item in extras["numpy"]))

        for tool in ("build", "mypy", "pytest", "ruff"):
            with self.subTest(tool=tool):
                self.assertTrue(
                    any(item.startswith(tool) for item in extras["dev"]),
                    f"development extra is missing {tool}",
                )

        self.assertFalse(
            any(item.startswith("numpy") for item in project["dependencies"])
        )
        self.assertFalse(any(item.startswith("twine") for item in extras["dev"]))

    def test_control_and_demo_console_entry_points_are_installed(self) -> None:
        scripts = self.pyproject["project"]["scripts"]

        self.assertEqual("teensy_daq.cli:main", scripts["teensy-daq"])
        self.assertEqual("teensy_daq.demo:main", scripts["teensy-daq-demo"])

    def test_runtime_package_data_is_an_explicit_typed_only_allowlist(self) -> None:
        setuptools = self.pyproject["tool"]["setuptools"]

        self.assertFalse(setuptools["include-package-data"])
        self.assertEqual(
            ["py.typed"],
            setuptools["package-data"]["teensy_daq"],
        )
        excluded_data = setuptools["exclude-package-data"]["*"]
        for pattern in (".env", "*.bin", "*.json", "*.key", "captures/*"):
            with self.subTest(pattern=pattern):
                self.assertIn(pattern, excluded_data)
        self.assertTrue(TYPED_MARKER_PATH.is_file())

    def test_source_manifest_excludes_non_runtime_inputs(self) -> None:
        manifest = MANIFEST_PATH.read_text(encoding="utf-8")

        self.assertIn("recursive-include src/teensy_daq *.py", manifest)
        self.assertIn("include src/teensy_daq/py.typed", manifest)
        self.assertIn("recursive-include examples *.py", manifest)
        for excluded in (
            "prune tests",
            "prune captures",
            "prune build",
            "prune dist",
            "prune credentials",
        ):
            with self.subTest(excluded=excluded):
                self.assertIn(excluded, manifest)

    def test_unlicensed_private_package_records_publication_boundary(self) -> None:
        project = self.pyproject["project"]
        readme = PACKAGE_README_PATH.read_text(encoding="utf-8")

        self.assertNotIn("license", project)
        self.assertNotIn("license-files", project)
        self.assertIn("Teensy®", readme)
        self.assertIn("before any PyPI submission", readme)
        self.assertIn("Do not reserve, upload, or publish", readme)


if __name__ == "__main__":
    unittest.main()
