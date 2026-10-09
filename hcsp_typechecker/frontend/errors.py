r"""Shared source positions and located frontend diagnostics."""

from __future__ import annotations

from dataclasses import dataclass
import re
import unicodedata
from typing import Literal


InputPhase = Literal["lexical", "syntax", "validation"]


def _character_display_width(character: str) -> int:
    r"""Approximate a Unicode character's width in a monospaced terminal."""

    if unicodedata.combining(character):
        return 0
    return 2 if unicodedata.east_asian_width(character) in {"F", "W"} else 1


def _diagnostic_line(line: str, caret_index: int) -> tuple[str, int]:
    r"""Expand tabs and map source character indices to display columns."""

    rendered: list[str] = []
    display_column = 0
    caret_column = 0
    for index, character in enumerate(line):
        if index == caret_index:
            caret_column = display_column
        if character == "\t":
            spaces = 4 - display_column % 4
            rendered.append(" " * spaces)
            display_column += spaces
        else:
            rendered.append(character)
            display_column += _character_display_width(character)
    if caret_index >= len(line):
        caret_column = display_column
    return "".join(rendered), caret_column


@dataclass(frozen=True)
class SourcePosition:
    r"""A zero-based source offset with one-based line and column."""

    offset: int
    line: int
    column: int


class HCSPInputError(ValueError):
    r"""An input error with source location and machine-readable phase."""

    def __init__(
        self,
        message: str,
        *,
        phase: InputPhase,
        source_name: str,
        source: str,
        position: SourcePosition,
        found: str | None = None,
        expected: tuple[str, ...] = (),
    ) -> None:
        r"""Store structured diagnostic fields and initialize ValueError text."""

        self.message = message
        self.phase = phase
        self.kind = f"input-{phase}"
        self.source_name = source_name
        self.source = source
        self.offset = position.offset
        self.line = position.line
        self.column = position.column
        self.found = found
        self.expected = expected
        super().__init__(self.format_diagnostic())

    def format_diagnostic(self) -> str:
        r"""Render a source line and aligned diagnostic caret."""

        header = (
            f"{self.source_name}:{self.line}:{self.column}: "
            f"{self.phase} error: {self.message}"
        )
        # Retain the final empty source line so an EOF caret stays on the correct line.
        lines = re.split(r"\r\n|\r|\n", self.source)
        if not lines:
            return header
        index = min(max(self.line - 1, 0), len(lines) - 1)
        source_line = lines[index]
        caret_column = min(max(self.column - 1, 0), len(source_line))
        rendered_line, rendered_caret = _diagnostic_line(source_line, caret_column)
        return "\n".join((header, rendered_line, " " * rendered_caret + "^"))

    def __str__(self) -> str:
        r"""Return a stable human-readable input diagnostic."""

        return self.format_diagnostic()


__all__ = ["HCSPInputError", "InputPhase", "SourcePosition"]
