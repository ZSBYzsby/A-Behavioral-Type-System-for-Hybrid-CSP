"""Check a source checkout before sharing it through GitHub.

The script is intentionally independent of wheel/sdist tooling.  It scans
repository text for developer-home paths, reports the active Python/Z3 and
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
        if not path.is_file() or any(part in IGNORED_PARTS for part in path.parts):
            continue
        if path.suffix.lower() in TEXT_SUFFIXES or path.name in {
            ".gitignore",
            ".gitattributes",
        }:
            yield path


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
    """不经过 shell 运行一个仓库检查，并打印该阶段的标题。"""

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
    """运行全部源码共享检查，并返回适合作为进程退出码的状态。"""

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
            "TypeConstructor regression tests",
        ),
    )
    for command, description in commands:
        if not run_command(command, description):
            return 1
    print("\nAll source-sharing checks passed.")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
