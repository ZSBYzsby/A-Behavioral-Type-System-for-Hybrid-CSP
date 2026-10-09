r"""Parse the program and supplied Type from one shared token stream."""

from __future__ import annotations

from ..type_constructor_frontend.parser import Parser, _checked_source
from ..type_syntax.parser import TypeParser
from .source import ParsedTypeCheckingSource


class TypeCheckingParser(Parser):
    r"""Extend the Constructor program prefix with a required type section."""

    def parse_complete_typechecking_source(self) -> ParsedTypeCheckingSource:
        r"""Parse gamma [parameters] theta process type EOF."""

        program = self.parse_complete_source_without_eof()
        # Share absolute token indices to preserve diagnostics against the entire source.
        type_parser = TypeParser(self.source, self.source_name)
        type_parser.index = self.index
        type_parser._expect("type")
        expected_type = type_parser._parse_configuration_type()
        self.index = type_parser.index
        self._expect("EOF")
        return ParsedTypeCheckingSource(program, expected_type)


def parse_typechecking_source(
    source: str,
    *,
    source_name: str = "<input>",
) -> ParsedTypeCheckingSource:
    r"""Bind a parsed program and its supplied Type from complete input."""

    return TypeCheckingParser(
        _checked_source(source, source_name),
        source_name,
    ).parse_complete_typechecking_source()
