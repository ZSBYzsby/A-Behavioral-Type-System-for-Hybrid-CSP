"""Check a source checkout before sharing it through GitHub.

The script is intentionally independent of wheel/sdist tooling. It scans
submission text for Chinese characters and developer-home paths, reports Python/Z3 and
optional KeYmaera X environment, then runs the maintained test suite.

Run it from any working directory with::

    python scripts/check_repository.py
"""

from __future__ import annotations

from pathlib import Path
import re
import subprocess
import sys
from typing import Iterable, Sequence


PROJECT_ROOT = Path(__file__).resolve().parents[1]
TEXT_SUFFIXES = {
    ".py",
    ".md",
    ".toml",
    ".txt",
    ".yml",
    ".yaml",
    ".json",
    ".rst",
    ".sh",
    ".ps1",
    ".gitignore",
    ".gitattributes",
}
IGNORED_PARTS = {
    ".git",
    ".venv",
    "venv",
    "__pycache__",
    "build",
    "dist",
    ".keymaerax-home",
    ".keymaerax-artifacts",
    "keymaerax-artifacts",
    "gpt_need",
    ".tmp",
    "tmp",
    "C%3A",
}


def _source_files() -> Iterable[Path]:
    """Yield shareable repository text while excluding generated local data."""

    for path in PROJECT_ROOT.rglob("*"):
        if not path.is_file() or any(
            part in IGNORED_PARTS or part.endswith(".egg-info") for part in path.parts
        ):
            continue
        if path.suffix.lower() in TEXT_SUFFIXES or path.name in {
            ".gitignore",
            ".gitattributes",
        }:
            yield path


def find_non_english_text() -> tuple[str, ...]:
    """Find Chinese characters or obsolete language copies in submission files."""

    chinese = re.compile(
        r"[\u3400-\u4dbf\u4e00-\u9fff\uf900-\ufaff"
        r"\U00020000-\U0002ffff\U00030000-\U000323af]"
    )
    matches: list[str] = []
    for path in _source_files():
        relative = path.relative_to(PROJECT_ROOT)
        if chinese.search(str(relative)) or path.name.endswith(".zh-CN.md"):
            matches.append(f"{relative}: filename is not part of the English submission")
        try:
            text = path.read_text(encoding="utf-8-sig")
        except (OSError, UnicodeError) as exc:
            matches.append(f"{relative}: unreadable: {exc}")
            continue
        for line_number, line in enumerate(text.splitlines(), start=1):
            if chinese.search(line):
                matches.append(f"{relative}:{line_number}: Chinese characters found")
    return tuple(matches)


def find_private_paths() -> tuple[str, ...]:
    """Find common developer-home absolute paths accidentally left in source."""

    patterns = (
        re.compile(r"[A-Za-z]:\\Users\\[^\\\s]+", re.IGNORECASE),
        re.compile(r"/" + r"home/[^/\s]+"),
        re.compile(r"/" + r"Users/[^/\s]+"),
    )
    matches: list[str] = []
    for path in _source_files():
        try:
            text = path.read_text(encoding="utf-8-sig")
        except (OSError, UnicodeError) as exc:
            matches.append(f"{path.relative_to(PROJECT_ROOT)}: unreadable: {exc}")
            continue
        for line_number, line in enumerate(text.splitlines(), start=1):
            if any(pattern.search(line) for pattern in patterns):
                matches.append(
                    f"{path.relative_to(PROJECT_ROOT)}:{line_number}: {line.strip()}"
                )
    return tuple(matches)


def run_command(arguments: Sequence[str], description: str) -> bool:
    r"""Run a repository check without a shell and display its stage."""

    print(f"\n=== {description} ===", flush=True)
    completed = subprocess.run(
        list(arguments),
        cwd=PROJECT_ROOT,
        check=False,
        shell=False,
    )
    if completed.returncode != 0:
        print(f"FAILED ({completed.returncode}): {' '.join(arguments)}")
        return False
    return True


def main() -> int:
    r"""Run all source-sharing checks and return a process exit status."""

    language_issues = find_non_english_text()
    print("=== Submission language scan ===")
    if language_issues:
        print("Submission files must use English:")
        for issue in language_issues:
            print(f"  {issue}")
        return 1
    print("No Chinese characters or Chinese-language document copies found.")

    private_paths = find_private_paths()
    print("=== Repository privacy scan ===")
    if private_paths:
        print("Developer-specific absolute paths found:")
        for match in private_paths:
            print(f"  {match}")
        return 1
    print("No developer-home absolute paths found.")

    python = sys.executable
    commands: tuple[tuple[list[str], str], ...] = (
        ([python, "-m", "hcsp_typechecker"], "Environment doctor"),
        (
            [
                python,
                "-m",
                "unittest",
                "discover",
                "-s",
                "tests",
                "-p",
                "test_*.py",
            ],
            "TypeConstructor/TypeChecker regression tests",
        ),
    )
    for command, description in commands:
        if not run_command(command, description):
            return 1
    print("\nAll source-sharing checks passed.")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
