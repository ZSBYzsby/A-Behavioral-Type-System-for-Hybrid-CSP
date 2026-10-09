r"""Regression tests for expression AST. Paper reference: Section 2.1."""

from __future__ import annotations

import unittest

from hcsp_typechecker._internal import (
    Assert,
    Assign,
    BinaryExpr,
    CompareExpr,
    Expr,
    Literal,
    Variable,
    ensure_expr,
)


class ExpressionAstTests(unittest.TestCase):
    r"""Tests for Expression AST."""


    def test_expr_base_class_cannot_be_instantiated(self) -> None:
        r"""Verify expr base class cannot be instantiated."""

        with self.assertRaises(TypeError):
            Expr()


    def test_process_constructor_normalizes_string_expression(self) -> None:
        r"""Verify process constructor normalizes string expression."""
        assignment = Assign("x", "y + 1")
        assertion = Assert("0 <= x < limit")

        self.assertIsInstance(assignment.target, Variable)
        self.assertIsInstance(assignment.expression, BinaryExpr)
        self.assertIsInstance(assertion.condition, CompareExpr)
        self.assertEqual(assignment.get_vars(), {"x", "y"})
        self.assertEqual(assertion.get_vars(), {"x", "limit"})


    def test_explicit_ast_is_preserved(self) -> None:
        r"""Verify explicit AST is preserved."""
        expression = BinaryExpr("+", Variable("x"), Literal(1))

        self.assertIs(ensure_expr(expression), expression)
        self.assertIs(Assign("x", expression).expression, expression)


    def test_foreign_expression_object_is_rejected(self) -> None:
        r"""Verify foreign expression object is rejected."""
        with self.assertRaisesRegex(TypeError, "project Expr"):
            Assign("x", object())  # type: ignore[arg-type]

if __name__ == "__main__":
    unittest.main()
