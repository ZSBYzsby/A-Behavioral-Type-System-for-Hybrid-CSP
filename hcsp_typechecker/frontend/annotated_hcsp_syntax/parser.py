r"""Convert annotated HCSP fragments into Process ASTs."""

from __future__ import annotations

from ..type_constructor_frontend.parser import parse_expression, parse_hcsp
from ...data_structures.process_ast.ast import HCSP
from ...data_structures.process_ast.expressions import Expr


def parse_annotated_hcsp(
    source: str,
    *,
    source_name: str = "<process>",
) -> HCSP:
    r"""Parse a process_system fragment into a Process or Parallel AST."""

    return parse_hcsp(source, source_name=source_name)


def parse_annotated_expression(
    source: str,
    *,
    source_name: str = "<expression>",
) -> Expr:
    r"""Parse the strict HCSP expression fragment into Expr."""

    return parse_expression(source, source_name=source_name)
