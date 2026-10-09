r"""Dependency-free lexical analysis of HCSP input."""

from __future__ import annotations

from dataclasses import dataclass
import re

from ...identifiers import (
    is_hcsp_identifier_continue,
    is_hcsp_identifier_start,
)
from ..errors import HCSPInputError, SourcePosition


KEYWORDS = frozenset(
    {
        "skip",
        "assert",
        "call",
        "if",
        "else",
        "choose",
        "or",
        "mu",
        "invariant",
        "ode",
        "flow",
        "dot",
        "domain",
        "safety",
        "delay",
        "interrupt",
        "on",
        "true",
        "false",
        "inf",
        "not",
        "and",
        # Reserve environment keywords even when parsing low-level Process fragments.
        "gamma",
        "parameters",
        "theta",
        "process",
        "continuous",
        "channel",
        "where",
        "Bool",
        "Nat",
        "Int",
        "Rational",
        "Real",
        # Type source language.  These words are reserved across the complete
        # user-facing grammar so a later ``type`` section shares one lexer
        # with Gamma/Theta/Process sections.
        "type",
        "empty",
        "bottom",
        "internal",
        "forever",
        "angelic",
        "then",
        "parallel",
    }
)

# Reserve invalid None to reject null values explicitly; lowercase none remains an identifier.
_UNSUPPORTED_RESERVED_WORDS = frozenset({"None"})

# Limit extreme literals before int/Fraction conversion; report excessive size as
# HCSPInputError.
_MAX_SIGNIFICAND_DIGITS = 4096
_MAX_ABSOLUTE_DECIMAL_EXPONENT = 10_000

_MULTI_CHARACTER_TOKENS = (
    "<->",
    "->",
    ":=",
    "**",
    "&&",
    "||",
    "==",
    "!=",
    "<=",
    ">=",
)
_SINGLE_CHARACTER_TOKENS = frozenset("{}(),;:.?!=+-*/%^<>")
_NUMBER_PATTERN = re.compile(
    r"(?:"
    r"(?:[0-9]+\.[0-9]*|\.[0-9]+)(?:[eE][+-]?[0-9]+)?"
    r"|[0-9]+[eE][+-]?[0-9]+"
    r"|[0-9]+"
    r")"
)


@dataclass(frozen=True)
class Token:
    r"""A classified token with its starting source position."""

    kind: str
    text: str
    position: SourcePosition

    @property
    def display(self) -> str:
        r"""Return token text suitable for diagnostics."""

        return "end of input" if self.kind == "EOF" else repr(self.text)


class Lexer:
    r"""Scan HCSP source into an immutable token sequence."""

    def __init__(self, source: str, source_name: str) -> None:
        r"""Validate source input and initialize the scanning cursor."""

        if not isinstance(source, str):
            raise TypeError("HCSP source must be a string")
        if not isinstance(source_name, str) or not source_name:
            raise ValueError("source_name must be a non-empty string")
        self.source = source
        self.source_name = source_name
        self.offset = 0
        self.line = 1
        self.column = 1

    def tokenize(self) -> tuple[Token, ...]:
        r"""Scan all input and append one EOF token."""

        tokens: list[Token] = []
        while self.offset < len(self.source):
            if self._skip_layout():
                continue
            position = self._position()
            character = self.source[self.offset]
            if self._is_identifier_start(character):
                tokens.append(self._scan_identifier(position))
                continue
            if character.isascii() and (
                character.isdigit()
                or (
                    character == "."
                    and self.offset + 1 < len(self.source)
                    and self.source[self.offset + 1].isdigit()
                )
            ):
                tokens.append(self._scan_number(position))
                continue
            matched = next(
                (
                    symbol
                    for symbol in _MULTI_CHARACTER_TOKENS
                    if self.source.startswith(symbol, self.offset)
                ),
                None,
            )
            if matched is not None:
                self._advance_text(matched)
                tokens.append(Token(matched, matched, position))
                continue
            if character in _SINGLE_CHARACTER_TOKENS:
                self._advance_text(character)
                tokens.append(Token(character, character, position))
                continue
            raise self._error(
                f"unexpected character {character!r}",
                position,
                found=character,
            )
        tokens.append(Token("EOF", "", self._position()))
        return tuple(tokens)

    def _skip_layout(self) -> bool:
        r"""Consume whitespace or comments and report whether the cursor advanced."""

        if self.offset >= len(self.source):
            return False
        character = self.source[self.offset]
        if character.isspace():
            self._advance_text(
                "\r\n"
                if self.source.startswith("\r\n", self.offset)
                else character
            )
            return True
        if self.source.startswith("//", self.offset):
            while self.offset < len(self.source) and self.source[self.offset] not in "\r\n":
                self._advance_text(self.source[self.offset])
            return True
        if self.source.startswith("/*", self.offset):
            start = self._position()
            self._advance_text("/*")
            while self.offset < len(self.source) and not self.source.startswith(
                "*/", self.offset
            ):
                self._advance_text(
                    "\r\n"
                    if self.source.startswith("\r\n", self.offset)
                    else self.source[self.offset]
                )
            if self.offset >= len(self.source):
                raise self._error("unterminated block comment", start, found="EOF")
            self._advance_text("*/")
            return True
        return False

    def _scan_identifier(self, position: SourcePosition) -> Token:
        r"""Scan ASCII identifiers, keywords, and Boolean literals."""

        start = self.offset
        while self.offset < len(self.source) and self._is_identifier_continue(
            self.source[self.offset]
        ):
            self._advance_text(self.source[self.offset])
        text = self.source[start:self.offset]
        if text in _UNSUPPORTED_RESERVED_WORDS:
            raise self._error(
                f"unsupported reserved word {text!r}",
                position,
                found=text,
            )
        lowered = text.lower()
        if lowered in {"true", "false"}:
            return Token(lowered, text, position)
        return Token(text if text in KEYWORDS else "IDENT", text, position)

    def _scan_number(self, position: SourcePosition) -> Token:
        r"""Scan decimal numbers and reject attached invalid suffixes."""

        match = _NUMBER_PATTERN.match(self.source, self.offset)
        if match is None:
            raise self._error("invalid numeric literal", position)
        text = match.group(0)
        self._advance_text(text)
        self._validate_numeric_size(text, position)
        if self.offset < len(self.source):
            following = self.source[self.offset]
            if self._is_identifier_continue(following) or following == ".":
                raise self._error(
                    "invalid character after numeric literal",
                    self._position(),
                    found=following,
                )
        kind = "REAL" if any(marker in text for marker in ".eE") else "INTEGER"
        return Token(kind, text, position)

    def _validate_numeric_size(
        self,
        text: str,
        position: SourcePosition,
    ) -> None:
        r"""Reject extreme numeric literals before costly host conversion."""

        parts = re.split(r"[eE]", text, maxsplit=1)
        significand_digits = sum(character.isdigit() for character in parts[0])
        if significand_digits > _MAX_SIGNIFICAND_DIGITS:
            raise self._error(
                "numeric literal has too many significant digits "
                f"(maximum {_MAX_SIGNIFICAND_DIGITS})",
                position,
                found=text,
            )
        if len(parts) == 1:
            return
        exponent_text = parts[1].lstrip("+-")
        if (
            len(exponent_text) > 5
            or int(exponent_text) > _MAX_ABSOLUTE_DECIMAL_EXPONENT
        ):
            raise self._error(
                "decimal exponent is outside the supported range "
                f"[-{_MAX_ABSOLUTE_DECIMAL_EXPONENT}, "
                f"{_MAX_ABSOLUTE_DECIMAL_EXPONENT}]",
                position,
                found=text,
            )

    def _advance_text(self, text: str) -> None:
        r"""Consume text while tracking CRLF and newline positions."""

        index = 0
        while index < len(text):
            character = text[index]
            self.offset += 1
            if character == "\r":
                if index + 1 < len(text) and text[index + 1] == "\n":
                    index += 1
                    self.offset += 1
                self.line += 1
                self.column = 1
            elif character == "\n":
                self.line += 1
                self.column = 1
            else:
                self.column += 1
            index += 1

    def _position(self) -> SourcePosition:
        r"""Snapshot the current source position."""

        return SourcePosition(self.offset, self.line, self.column)

    def _error(
        self,
        message: str,
        position: SourcePosition,
        *,
        found: str | None = None,
    ) -> HCSPInputError:
        r"""Create a lexical-phase diagnostic."""

        return HCSPInputError(
            message,
            phase="lexical",
            source_name=self.source_name,
            source=self.source,
            position=position,
            found=found,
        )

    @staticmethod
    def _is_identifier_start(character: str) -> bool:
        r"""Check an ASCII identifier's first character."""

        return is_hcsp_identifier_start(character)

    @staticmethod
    def _is_identifier_continue(character: str) -> bool:
        r"""Check an ASCII identifier's subsequent character."""

        return is_hcsp_identifier_continue(character)


def tokenize(source: str, *, source_name: str = "<input>") -> tuple[Token, ...]:
    r"""Tokenize HCSP input using the project lexical rules."""

    return Lexer(source, source_name).tokenize()
