r"""Immutable combined parsing results for TypeChecker."""

from __future__ import annotations

from dataclasses import dataclass

from ...data_structures.type_ast.ast import ConfigurationType
from ..type_constructor_frontend.source import ParsedHCSPSource


@dataclass(frozen=True, slots=True)
class ParsedTypeCheckingSource:
    r"""Bind complete HCSP input to the supplied Type in the same source."""

    program: ParsedHCSPSource
    expected_type: ConfigurationType

    def __post_init__(self) -> None:
        r"""Require a valid program record and formal Type AST."""

        if not isinstance(self.program, ParsedHCSPSource):
            raise TypeError("program must be a ParsedHCSPSource")
        if not isinstance(self.expected_type, ConfigurationType):
            raise TypeError("expected_type must be a ConfigurationType")
