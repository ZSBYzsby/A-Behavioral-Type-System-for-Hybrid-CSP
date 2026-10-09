r"""Common ASCII identifier rules across all project layers."""

from __future__ import annotations

import re
from typing import Final


HCSP_IDENTIFIER_PATTERN: Final[re.Pattern[str]] = re.compile(
    r"[A-Za-z_][A-Za-z0-9_]*\Z",
    flags=re.ASCII,
)


def is_hcsp_identifier(value: object) -> bool:
    r"""Check whether a complete string is a valid HCSP identifier."""

    return (
        isinstance(value, str)
        and HCSP_IDENTIFIER_PATTERN.fullmatch(value) is not None
    )


def is_hcsp_identifier_start(character: str) -> bool:
    r"""Check an HCSP identifier's initial character."""

    return (
        isinstance(character, str)
        and len(character) == 1
        and (
            "A" <= character <= "Z"
            or "a" <= character <= "z"
            or character == "_"
        )
    )


def is_hcsp_identifier_continue(character: str) -> bool:
    r"""Check an HCSP identifier's subsequent character."""

    return is_hcsp_identifier_start(character) or (
        isinstance(character, str)
        and len(character) == 1
        and "0" <= character <= "9"
    )
