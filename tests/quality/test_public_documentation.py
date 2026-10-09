r"""Regression tests for public documentation. Paper reference: Table 3."""

from __future__ import annotations

import re
import unittest
from pathlib import Path

import hcsp_typechecker


PROJECT_ROOT = Path(__file__).resolve().parents[2]
README = PROJECT_ROOT / "README.md"
DOCUMENT_ROOT = PROJECT_ROOT / "document"
PUBLIC_API_GUIDE = DOCUMENT_ROOT / "PUBLIC_API_GUIDE.md"
FUNCTION_REFERENCE = DOCUMENT_ROOT / "PROJECT_FUNCTION_REFERENCE.md"


class PublicDocumentationTests(unittest.TestCase):
    r"""Tests for Public Documentation."""


    def test_public_names_and_feature_status_match_the_code(self) -> None:
        r"""Verify public names and feature status match the code."""

        api_text = PUBLIC_API_GUIDE.read_text(encoding="utf-8")
        reference_text = FUNCTION_REFERENCE.read_text(encoding="utf-8")
        for public_name in hcsp_typechecker.__all__:
            self.assertIn(public_name, api_text)
            self.assertIn(public_name, reference_text)

        combined = "\n".join(
            path.read_text(encoding="utf-8")
            for path in (README, *sorted(DOCUMENT_ROOT.glob("*.md")))
        )
        stale_patterns = (
            r"TypeChecker.{0,30}(?:not (?:yet )?implemented|unimplemented)",
            r"future\s+\*\*TypeChecker\*\*",
            r"public interface.{0,30}does not accept (?:user|supplied) Types?",
            r"tests/` currently contains \d+ (?:automated )?tests",
        )
        for pattern in stale_patterns:
            self.assertIsNone(re.search(pattern, combined, flags=re.DOTALL | re.IGNORECASE))


    def test_local_markdown_links_resolve(self) -> None:
        r"""Verify local markdown links resolve."""

        missing: list[str] = []
        paths = (
            README,
            *sorted(DOCUMENT_ROOT.glob("*.md")),
        )
        for document_path in paths:
            text = document_path.read_text(encoding="utf-8")
            for raw_target in re.findall(r"\[[^\]]+\]\(([^)]+)\)", text):
                target = raw_target.strip().strip("<>")
                if not target or target.startswith(("#", "http://", "https://")):
                    continue
                relative_target = target.split("#", 1)[0]
                # Only check .md navigation links; mathematical notation can resemble Markdown
                # links.
                if not relative_target.lower().endswith(".md"):
                    continue
                resolved = (document_path.parent / relative_target).resolve()
                if not resolved.exists():
                    missing.append(
                        f"{document_path.relative_to(PROJECT_ROOT)} -> {target}"
                    )

        self.assertFalse(
            missing,
            "Broken local documentation links:\n" + "\n".join(missing),
        )


if __name__ == "__main__":
    unittest.main()
