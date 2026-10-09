r"""Regression tests for input structure boundaries."""

from __future__ import annotations

import unittest

from hcsp_typechecker.frontend.annotated_hcsp_syntax import parse_annotated_hcsp
from hcsp_typechecker.frontend.type_constructor_frontend import parse_hcsp_source
from hcsp_typechecker.data_structures.process_ast.ast import Skip
from hcsp_typechecker.frontend.type_syntax import (
    format_type_source,
    parse_type_source,
)
from hcsp_typechecker.data_structures.type_ast.ast import EmptyType
from hcsp_typechecker.frontend.typing_context_syntax import parse_typing_context


class TestInputStructureBoundaries(unittest.TestCase):
    r"""Tests for Input Structure Boundaries."""


    def test_annotated_hcsp_fragment_lowers_to_process_ast(self) -> None:
        r"""Verify annotated HCSP fragment lowers to process AST."""

        self.assertEqual(parse_annotated_hcsp("{{skip}}"), Skip())


    def test_typing_context_fragment_lowers_to_environment_objects(self) -> None:
        r"""Verify typing context fragment lowers to environment objects."""

        context = parse_typing_context(
            "gamma(x: Real) "
            "parameters(limit: Real) where(limit >= 0) "
            "theta(ch: channel(value: Real))"
        )
        self.assertEqual(tuple(context.gamma), ("x",))
        self.assertEqual(tuple(context.parameters.declarations), ("limit",))
        self.assertEqual(tuple(context.theta), ("ch",))


    def test_type_fragment_round_trips_independently(self) -> None:
        r"""Verify type fragment round trips independently."""

        value = parse_type_source("type empty")
        self.assertEqual(value, EmptyType())
        self.assertEqual(format_type_source(value), "type empty")


    def test_frontend_combines_context_and_process(self) -> None:
        r"""Verify frontend combines context and process."""

        parsed = parse_hcsp_source("gamma() theta() process {{skip}}")
        self.assertEqual(parsed.process, Skip())
        self.assertEqual(dict(parsed.gamma), {})
        self.assertEqual(dict(parsed.theta), {})


if __name__ == "__main__":
    unittest.main()
