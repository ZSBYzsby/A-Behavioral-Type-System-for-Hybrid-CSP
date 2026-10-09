"""Require English source documentation, diagnostics, tests, and submission documents."""

from __future__ import annotations

import ast
import re
import unittest
from pathlib import Path

from scripts.check_repository import find_non_english_text


PROJECT_ROOT = Path(__file__).resolve().parents[2]
EXCLUDED_DIRECTORY_NAMES = frozenset(
    {
        ".git",
        ".tmp",
        ".venv",
        "build",
        "dist",
        "venv",
        "__pycache__",
    }
)


class DocumentationCoverageTests(unittest.TestCase):
    """Keep submission files in English and require descriptions of Python code units."""


    def test_documentation_and_runtime_language_are_consistent(self) -> None:
        """Check English submission text and Python docstrings, including test fixtures."""
        missing: list[str] = []
        missing.extend(find_non_english_text())

        for path in sorted(PROJECT_ROOT.rglob("*.py")):
            relative = path.relative_to(PROJECT_ROOT)
            directory_parts = relative.parts[:-1]
            if any(
                part in EXCLUDED_DIRECTORY_NAMES or part.endswith(".egg-info")
                for part in directory_parts
            ):
                continue


            source = path.read_text(encoding="utf-8-sig")
            tree = ast.parse(source, filename=str(path))
            docstring_values: set[int] = set()
            for node in ast.walk(tree):
                if not isinstance(
                    node,
                    (ast.Module, ast.ClassDef, ast.FunctionDef, ast.AsyncFunctionDef),
                ):
                    continue
                name = getattr(node, "name", "module")
                line = getattr(node, "lineno", 1)
                docstring = ast.get_docstring(node)
                if docstring is None:
                    missing.append(f"{relative}:{line}: {name}: missing docstring")
                    continue
                docstring_values.add(id(node.body[0].value))
                if re.search(r"[\u4e00-\u9fff]", docstring.splitlines()[0]):
                    missing.append(f"{relative}:{line}: {name}: summary is not English")

            for node in ast.walk(tree):
                if (
                    isinstance(node, ast.Constant)
                    and isinstance(node.value, str)
                    and id(node) not in docstring_values
                    and re.search(r"[\u4e00-\u9fff]", node.value)
                ):
                    missing.append(f"{relative}:{node.lineno}: runtime text is not English")

        self.assertFalse(
            missing,
            "Documentation/language violations:\n" + "\n".join(missing),
        )


if __name__ == "__main__":
    unittest.main()
