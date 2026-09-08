"""Regression checks for the repository foundation."""

from __future__ import annotations

import unittest
from pathlib import Path

import tomllib

REPOSITORY_ROOT = Path(__file__).resolve().parents[2]
REQUIRED_DIRECTORIES = (
    "firmware/src",
    "firmware/tools",
    "firmware/tests",
    "daq_api/src/thingdone_daq",
    "daq_api/tests",
    "doc/architecture",
    "doc/guides",
    "doc/protocol",
    "doc/decisions",
    "doc/reference",
    "doc/results",
)
REQUIRED_FRONT_MATTER_FIELDS = ("type", "title", "created", "tags", "related")


class RepositoryLayoutTests(unittest.TestCase):
    def test_required_directories_exist(self) -> None:
        missing = [
            path
            for path in REQUIRED_DIRECTORIES
            if not (REPOSITORY_ROOT / path).is_dir()
        ]

        self.assertEqual([], missing)

    def test_python_package_uses_an_installable_src_layout(self) -> None:
        pyproject_path = REPOSITORY_ROOT / "daq_api" / "pyproject.toml"
        with pyproject_path.open("rb") as pyproject_file:
            pyproject = tomllib.load(pyproject_file)

        self.assertEqual(
            ["src"],
            pyproject["tool"]["setuptools"]["packages"]["find"]["where"],
        )
        self.assertTrue(pyproject["project"]["name"])
        self.assertTrue(
            (REPOSITORY_ROOT / "daq_api/src/thingdone_daq/__init__.py").is_file()
        )

    def test_doc_markdown_has_required_yaml_front_matter(self) -> None:
        markdown_paths = sorted((REPOSITORY_ROOT / "doc").rglob("*.md"))
        self.assertTrue(markdown_paths, "the documentation tree must not be empty")

        for markdown_path in markdown_paths:
            with self.subTest(path=markdown_path.relative_to(REPOSITORY_ROOT)):
                lines = markdown_path.read_text(encoding="utf-8").splitlines()
                self.assertGreaterEqual(len(lines), 3)
                self.assertEqual("---", lines[0])
                try:
                    closing_delimiter = lines.index("---", 1)
                except ValueError:
                    self.fail("YAML front matter has no closing delimiter")
                front_matter = lines[1:closing_delimiter]
                for field in REQUIRED_FRONT_MATTER_FIELDS:
                    self.assertTrue(
                        any(line.startswith(f"{field}:") for line in front_matter),
                        f"missing {field!r} in YAML front matter",
                    )

    def test_ignore_rules_keep_deterministic_fixtures_visible(self) -> None:
        ignore_rules = (REPOSITORY_ROOT / ".gitignore").read_text(encoding="utf-8")

        self.assertIn("firmware/build/", ignore_rules)
        self.assertIn("captures/", ignore_rules)
        self.assertIn("benchmark-scratch/", ignore_rules)
        self.assertIn(".fw_api_key", ignore_rules)
        self.assertIn("__pycache__/", ignore_rules)
        self.assertIn("!firmware/tests/fixtures/**", ignore_rules)
        self.assertIn("!daq_api/tests/fixtures/**", ignore_rules)


if __name__ == "__main__":
    unittest.main()
