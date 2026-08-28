"""Tests for local-only Python distribution metadata and dependency groups."""

from __future__ import annotations

import unittest
from pathlib import Path
from typing import Any, ClassVar

import tomllib

PYPROJECT_PATH = Path(__file__).resolve().parents[1] / "pyproject.toml"


class PackageConfigurationTests(unittest.TestCase):
    pyproject: ClassVar[dict[str, Any]]

    @classmethod
    def setUpClass(cls) -> None:
        with PYPROJECT_PATH.open("rb") as pyproject_file:
            cls.pyproject = tomllib.load(pyproject_file)

    def test_distribution_is_an_explicit_local_placeholder(self) -> None:
        project = self.pyproject["project"]

        self.assertEqual("teensy-daq-local", project["name"])
        self.assertEqual("README.md", project["readme"])
        self.assertEqual(">=3.10", project["requires-python"])
        self.assertIn("Private :: Do Not Upload", project["classifiers"])

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


if __name__ == "__main__":
    unittest.main()
