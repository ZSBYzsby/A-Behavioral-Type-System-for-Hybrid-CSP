r"""Regression tests for expression input. Paper reference: Section 2.1."""

from __future__ import annotations

from decimal import Decimal
import unittest

from hcsp_typechecker._internal import (
    BinaryExpr,
    BooleanExpr,
    CallExpr,
    CompareExpr,
    HCSPInputError,
    Literal,
    UnaryExpr,
    Variable,
    parse_expression,
    parse_hcsp,
)
from hcsp_typechecker.frontend.type_constructor_frontend import tokenize
from hcsp_typechecker.data_structures.process_ast.ast import InputChannel


class LexerInputTests(unittest.TestCase):
    r"""Tests for Lexer Input."""


    def test_layout_comments_and_source_positions(self) -> None:
        r"""Verify layout comments and source positions."""

        process = parse_hcsp(
            "{{ch /* channel */ ? /* targets */ (x)}} // finished\r\n"
        )
        self.assertEqual(process, InputChannel("ch", "x"))

        tokens = tokenize("x\r\n\t y")
        self.assertEqual(tokens[1].text, "y")
        self.assertEqual((tokens[1].position.line, tokens[1].position.column), (2, 3))


    def test_longest_operator_matching(self) -> None:
        r"""Verify longest operator matching."""

        source = ":= <= >= == != <-> && || ** ? !"
        kinds = tuple(token.kind for token in tokenize(source)[:-1])
        self.assertEqual(
            kinds,
            (":=", "<=", ">=", "==", "!=", "<->", "&&", "||", "**", "?", "!"),
        )


    def test_decimal_and_boolean_literals(self) -> None:
        r"""Verify decimal and boolean literals."""

        cases = {
            "0": Literal(0),
            "123": Literal(123),
            "1.": Literal(Decimal("1.")),
            ".5": Literal(Decimal(".5")),
            "1.25": Literal(Decimal("1.25")),
            "1e3": Literal(Decimal("1e3")),
            "1E-3": Literal(Decimal("1E-3")),
            "TRUE": Literal(True),
            "fAlSe": Literal(False),
        }
        for source, expected in cases.items():
            with self.subTest(source=source):
                self.assertEqual(parse_expression(source), expected)


class ExpressionTreeInputTests(unittest.TestCase):
    r"""Tests for Expression Tree Input."""


    def test_supported_operators_are_normalized(self) -> None:
        r"""Verify supported operators are normalized."""

        self.assertEqual(
            parse_expression("+x"),
            UnaryExpr("+", Variable("x")),
        )
        self.assertEqual(
            parse_expression("!ready"),
            UnaryExpr("not", Variable("ready")),
        )
        for source_operator, internal_operator in (
            ("+", "+"),
            ("-", "-"),
            ("*", "*"),
            ("/", "/"),
            ("%", "%"),
            ("**", "**"),
            ("^", "**"),
        ):
            with self.subTest(operator=source_operator):
                self.assertEqual(
                    parse_expression(f"x {source_operator} y"),
                    BinaryExpr(internal_operator, Variable("x"), Variable("y")),
                )
        self.assertEqual(
            parse_expression("a && b"),
            BooleanExpr("and", (Variable("a"), Variable("b"))),
        )
        self.assertEqual(
            parse_expression("a || b"),
            BooleanExpr("or", (Variable("a"), Variable("b"))),
        )


    def test_precedence_and_power_associativity(self) -> None:
        r"""Verify precedence and power associativity."""

        self.assertEqual(
            parse_expression("x + y * 2"),
            BinaryExpr(
                "+",
                Variable("x"),
                BinaryExpr("*", Variable("y"), Literal(2)),
            ),
        )
        self.assertEqual(
            parse_expression("-x ** 2"),
            UnaryExpr("-", BinaryExpr("**", Variable("x"), Literal(2))),
        )
        self.assertEqual(
            parse_expression("x ^ y ^ z"),
            BinaryExpr(
                "**",
                Variable("x"),
                BinaryExpr("**", Variable("y"), Variable("z")),
            ),
        )
        self.assertEqual(
            parse_expression("not x < y or a and b"),
            BooleanExpr(
                "or",
                (
                    UnaryExpr(
                        "not",
                        CompareExpr((Variable("x"), Variable("y")), ("<",)),
                    ),
                    BooleanExpr("and", (Variable("a"), Variable("b"))),
                ),
            ),
        )


    def test_comparisons_and_equivalence(self) -> None:
        r"""Verify comparisons and equivalence."""

        for source_operator, internal_operator in (
            ("==", "=="),
            ("!=", "!="),
            ("<", "<"),
            ("<=", "<="),
            (">", ">"),
            (">=", ">="),
            ("<->", "=="),
        ):
            with self.subTest(operator=source_operator):
                self.assertEqual(
                    parse_expression(f"x {source_operator} y"),
                    CompareExpr(
                        (Variable("x"), Variable("y")),
                        (internal_operator,),
                    ),
                )
        self.assertEqual(
            parse_expression("0 <= x < limit"),
            CompareExpr(
                (Literal(0), Variable("x"), Variable("limit")),
                ("<=", "<"),
            ),
        )


    def test_named_function_calls(self) -> None:
        r"""Verify named function calls."""

        self.assertEqual(parse_expression("f()"), CallExpr("f", ()))
        self.assertEqual(
            parse_expression("f(x + 1, abs(y),)"),
            CallExpr(
                "f",
                (
                    BinaryExpr("+", Variable("x"), Literal(1)),
                    CallExpr("abs", (Variable("y"),)),
                ),
            ),
        )


    def test_unsupported_expression_forms_are_rejected(self) -> None:
        r"""Verify unsupported expression forms are rejected."""

        unsupported = (
            "\u03b1\u03b2",
            "None",
            "plant.temperature",
            "array[i]",
            "(x, y)",
            "[x, y]",
            "'text'",
            "a if ready else b",
            "lambda x: x",
            "f(x=1)",
            "x << 1",
            "x & y",
            "x in values",
            "(x := 1)",
            "0x10",
            "1_000",
        )
        for source in unsupported:
            with self.subTest(source=source):
                with self.assertRaises(HCSPInputError):
                    parse_expression(source)


if __name__ == "__main__":
    unittest.main()
