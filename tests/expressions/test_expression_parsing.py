r"""Regression tests for expression parsing. Paper reference: Section 2.1, Section 4.2/4.3."""

from __future__ import annotations

import unittest
from decimal import Decimal
from fractions import Fraction

from hcsp_typechecker._internal import (
    BinaryExpr,
    BooleanExpr,
    CallExpr,
    CompareExpr,
    Expr,
    Literal,
    UnaryExpr,
    Variable,
    ensure_expr,
    parse_expr,
    parse_expression,
)


def assert_project_expr_tree(test: unittest.TestCase, expression: Expr) -> None:
    r"""Require every descendant to be a project expression node."""

    test.assertIsInstance(expression, Expr)
    if isinstance(expression, (Literal, Variable)):
        return
    if isinstance(expression, UnaryExpr):
        assert_project_expr_tree(test, expression.operand)
        return
    if isinstance(expression, BinaryExpr):
        assert_project_expr_tree(test, expression.left)
        assert_project_expr_tree(test, expression.right)
        return
    if isinstance(expression, BooleanExpr):
        for item in expression.operands:
            assert_project_expr_tree(test, item)
        return
    if isinstance(expression, CompareExpr):
        for item in expression.operands:
            assert_project_expr_tree(test, item)
        return
    if isinstance(expression, CallExpr):
        for item in expression.arguments:
            assert_project_expr_tree(test, item)
        return
    test.fail(f"Unexpected Expr subclass: {type(expression).__name__}")


class SupportedAtomicExpressionParsingTests(unittest.TestCase):
    r"""Tests for Supported Atomic Expression Parsing."""


    def test_boolean_and_numeric_literals(self) -> None:
        r"""Verify boolean and numeric literals."""

        cases = {
            "true": Literal(True),
            "FALSE": Literal(False),
            "0": Literal(0),
            "42": Literal(42),
            "3.5": Literal(3.5),
        }
        for source, expected in cases.items():
            with self.subTest(source=source):
                self.assertEqual(parse_expr(source), expected)


    def test_string_and_unit_literals_are_rejected(self) -> None:
        r"""Verify string and unit literals are rejected."""

        for source in ("'HCSP'", "None"):
            with self.subTest(source=source):
                with self.assertRaisesRegex(TypeError, "Unsupported literal value"):
                    parse_expr(source)
        for value in ("HCSP", None):
            with self.subTest(value=value):
                with self.assertRaisesRegex(TypeError, "Unsupported literal value"):
                    Literal(value)  # type: ignore[arg-type]


    def test_plain_identifier_becomes_variable(self) -> None:
        r"""Verify plain identifier becomes variable."""

        self.assertEqual(parse_expr("velocity"), Variable("velocity"))


    def test_identifiers_are_ascii_and_never_nfkc_normalized(self) -> None:
        r"""Verify identifiers are ascii and never nfkc normalized."""

        for name in ("\u03b1\u03b2", "π", "ｘ", "K"):
            with self.subTest(name=name):
                with self.assertRaises(ValueError):
                    Variable(name)
                with self.assertRaises(ValueError):
                    parse_expr(name)
                with self.assertRaises(ValueError):
                    parse_expression(name)
        with self.assertRaises(ValueError):
            CallExpr("ｆ", (Variable("x"),))
        with self.assertRaises(ValueError):
            parse_expr("ｆ(x)")


    def test_explicit_decimal_and_fraction_inputs(self) -> None:
        r"""Verify explicit decimal and fraction inputs."""

        self.assertEqual(ensure_expr(Decimal("1.25")), Literal(Decimal("1.25")))
        self.assertEqual(ensure_expr(Fraction(1, 3)), Literal(Fraction(1, 3)))


class SupportedOperatorExpressionParsingTests(unittest.TestCase):
    r"""Tests for Supported Operator Expression Parsing."""


    def test_all_supported_unary_operators(self) -> None:
        r"""Verify all supported unary operators."""

        cases = {
            "not ready": UnaryExpr("not", Variable("ready")),
            "+x": UnaryExpr("+", Variable("x")),
            "-x": UnaryExpr("-", Variable("x")),
        }
        for source, expected in cases.items():
            with self.subTest(source=source):
                self.assertEqual(parse_expr(source), expected)


    def test_all_supported_binary_arithmetic_operators(self) -> None:
        r"""Verify all supported binary arithmetic operators."""

        for operator in ("+", "-", "*", "/", "%", "**"):
            with self.subTest(operator=operator):
                self.assertEqual(
                    parse_expr(f"x {operator} y"),
                    BinaryExpr(operator, Variable("x"), Variable("y")),
                )


    def test_caret_uses_power_precedence_and_right_associativity(self) -> None:
        r"""Verify caret uses power precedence and right associativity."""

        cases = {
            "x ^ y ^ z": BinaryExpr(
                "**",
                Variable("x"),
                BinaryExpr("**", Variable("y"), Variable("z")),
            ),
            "x + y ^ z": BinaryExpr(
                "+",
                Variable("x"),
                BinaryExpr("**", Variable("y"), Variable("z")),
            ),
            "-x ^ 2": UnaryExpr(
                "-",
                BinaryExpr("**", Variable("x"), Literal(2)),
            ),
            "2 ^ -x": BinaryExpr(
                "**",
                Literal(2),
                UnaryExpr("-", Variable("x")),
            ),
        }
        for source, expected in cases.items():
            with self.subTest(source=source):
                self.assertEqual(parse_expr(source), expected)
                self.assertEqual(parse_expression(source), expected)


    def test_python_precedence_and_parentheses_shape_the_tree(self) -> None:
        r"""Verify python precedence and parentheses shape the tree."""

        self.assertEqual(
            parse_expr("x + y * 2"),
            BinaryExpr(
                "+",
                Variable("x"),
                BinaryExpr("*", Variable("y"), Literal(2)),
            ),
        )
        self.assertEqual(
            parse_expr("(x + y) * 2"),
            BinaryExpr(
                "*",
                BinaryExpr("+", Variable("x"), Variable("y")),
                Literal(2),
            ),
        )


    def test_and_or_build_nary_boolean_nodes(self) -> None:
        r"""Verify and or build nary boolean nodes."""

        self.assertEqual(
            parse_expr("a and b and c"),
            BooleanExpr(
                "and",
                (Variable("a"), Variable("b"), Variable("c")),
            ),
        )
        self.assertEqual(
            parse_expr("a or b"),
            BooleanExpr("or", (Variable("a"), Variable("b"))),
        )


    def test_all_supported_single_comparisons(self) -> None:
        r"""Verify all supported single comparisons."""

        for operator in ("==", "!=", "<", "<=", ">", ">="):
            with self.subTest(operator=operator):
                self.assertEqual(
                    parse_expr(f"x {operator} y"),
                    CompareExpr(
                        (Variable("x"), Variable("y")),
                        (operator,),
                    ),
                )


    def test_chained_comparison_preserves_operand_order(self) -> None:
        r"""Verify chained comparison preserves operand order."""

        self.assertEqual(
            parse_expr("0 <= x < limit"),
            CompareExpr(
                (Literal(0), Variable("x"), Variable("limit")),
                ("<=", "<"),
            ),
        )


class SupportedHCSPNotationParsingTests(unittest.TestCase):
    r"""Tests for Supported HCSP Notation Parsing."""


    def test_double_ampersand_and_double_bar(self) -> None:
        r"""Verify double ampersand and double bar."""

        self.assertEqual(
            parse_expr("a && b"),
            BooleanExpr("and", (Variable("a"), Variable("b"))),
        )
        self.assertEqual(
            parse_expr("a || b"),
            BooleanExpr("or", (Variable("a"), Variable("b"))),
        )


    def test_bang_not_does_not_corrupt_not_equal(self) -> None:
        r"""Verify bang not does not corrupt not equal."""

        self.assertEqual(
            parse_expr("!ready"),
            UnaryExpr("not", Variable("ready")),
        )
        self.assertEqual(
            parse_expr("x != y"),
            CompareExpr((Variable("x"), Variable("y")), ("!=",)),
        )


    def test_equivalence_notation_becomes_equality(self) -> None:
        r"""Verify equivalence notation becomes equality."""

        self.assertEqual(
            parse_expr("ready <-> enabled"),
            CompareExpr(
                (Variable("ready"), Variable("enabled")),
                ("==",),
            ),
        )


class SupportedFunctionExpressionParsingTests(unittest.TestCase):
    r"""Tests for Supported Function Expression Parsing."""


    def test_zero_one_and_multiple_argument_calls(self) -> None:
        r"""Verify zero one and multiple argument calls."""

        cases = {
            "f()": CallExpr("f", ()),
            "sqrt(x)": CallExpr("sqrt", (Variable("x"),)),
            "max(x, y, 0)": CallExpr(
                "max",
                (Variable("x"), Variable("y"), Literal(0)),
            ),
        }
        for source, expected in cases.items():
            with self.subTest(source=source):
                self.assertEqual(parse_expr(source), expected)


    def test_nested_function_and_operator_arguments(self) -> None:
        r"""Verify nested function and operator arguments."""

        self.assertEqual(
            parse_expr("f(x + 1, abs(y))"),
            CallExpr(
                "f",
                (
                    BinaryExpr("+", Variable("x"), Literal(1)),
                    CallExpr("abs", (Variable("y"),)),
                ),
            ),
        )


    def test_complex_parse_contains_only_project_nodes(self) -> None:
        r"""Verify complex parse contains only project nodes."""

        expression = parse_expr(
            "0 <= f(x + 1) < limit and (ready or !stopped)"
        )
        assert_project_expr_tree(self, expression)
        self.assertEqual(
            expression.get_vars(),
            {"x", "limit", "ready", "stopped"},
        )


class UnsupportedExpressionParsingTests(unittest.TestCase):
    r"""Tests for Unsupported Expression Parsing."""


    def test_every_documented_unsupported_form_is_rejected(self) -> None:
        r"""Verify every documented unsupported form is rejected."""

        unsupported_sources = (
            "1 if ready else 0",
            "plant.temperature",
            "obj.f(x)",
            "array[i]",
            "functions[i](x)",
            "lambda x: x + 1",
            "[f(x) for x in values]",
            "(x, 1)",
            "[x, 1]",
            "(x,)",
            "()",
            "{'x': 1}",
            "{x, y}",
            "f(x=1)",
            "x // y",
            "x << 1",
            "x >> 1",
            "x & y",
            "x | y",
            "x in values",
            "x is None",
            "(x := 1)",
        )
        for source in unsupported_sources:
            with self.subTest(source=source):
                with self.assertRaises(ValueError):
                    parse_expr(source)
        for value in ((1, "x"), [1, "x"]):
            with self.subTest(value=value):
                with self.assertRaises(TypeError):
                    ensure_expr(value)  # type: ignore[arg-type]


    def test_empty_or_non_string_source_is_rejected(self) -> None:
        r"""Verify empty or non string source is rejected."""

        for source in ("", "   "):
            with self.subTest(source=source):
                with self.assertRaises(ValueError):
                    parse_expr(source)
        with self.assertRaises(ValueError):
            parse_expr(1)  # type: ignore[arg-type]


if __name__ == "__main__":
    unittest.main()
