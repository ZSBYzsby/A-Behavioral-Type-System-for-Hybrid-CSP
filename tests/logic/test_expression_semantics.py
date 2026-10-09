r"""Regression tests for expression semantics. Paper reference: Table 2."""

from __future__ import annotations

import unittest

from hcsp_typechecker._internal import (
    Assign,
    BasicType,
    BinaryExpr,
    ChannelType,
    Configuration,
    If,
    OutputChannel,
    Skip,
    Variable,
    Verdict,
    construct_type,
)
from hcsp_typechecker.backend.common.logic import (
    ExpressionTranslator,
    Z3ProofEngine,
    z3,
)


class ExpressionSemanticTests(unittest.TestCase):
    r"""Tests for Expression Semantic."""


    def test_integer_operands_use_real_division(self) -> None:
        r"""Verify integer operands use Real division."""

        translator = ExpressionTranslator({})
        result = translator.translate("1 / 2")
        engine = Z3ProofEngine()

        self.assertEqual(result.value_type, BasicType.REAL)
        self.assertTrue(z3.is_real(result.term))
        self.assertEqual(engine.valid(result.term == z3.RealVal("1/2"))[0], Verdict.TRUE)
        self.assertEqual(engine.valid(result.term == 0)[0], Verdict.FALSE)


    def test_shared_expression_subtree_is_translated_twice(self) -> None:
        r"""Verify shared expression subtree is translated twice."""

        shared = Variable("x")
        expression = BinaryExpr("+", shared, shared)
        translator = ExpressionTranslator({"x": BasicType.INT})
        result = translator.translate(expression)
        x_term = translator.symbol("x")

        self.assertEqual(result.value_type, BasicType.INT)
        self.assertEqual(
            Z3ProofEngine().valid(result.term == x_term + x_term)[0],
            Verdict.TRUE,
        )


    def test_assignment_proves_symbolic_divisor_is_nonzero(self) -> None:
        r"""Verify assignment proves symbolic divisor is nonzero."""

        process = Assign("y", "1 / x")
        accepted = construct_type(
            gamma={"x": BasicType.REAL, "y": BasicType.REAL},
            theta={},
            configurations=[Configuration({"x": 1, "y": 0}, process)],
            path_condition="x != 0",
        )
        rejected = construct_type(
            gamma={"x": BasicType.REAL, "y": BasicType.REAL},
            theta={},
            configurations=[Configuration({"x": 0, "y": 0}, process)],
        )

        self.assertEqual(accepted.verdict, Verdict.TRUE)
        self.assertEqual(rejected.verdict, Verdict.FALSE)
        obligation = next(
            item for item in rejected.obligations if item.rule == "T-Assign"
        )
        self.assertEqual(obligation.verdict, Verdict.FALSE)


    def test_invalid_modulo_and_square_root_are_reported_cleanly(self) -> None:
        r"""Verify invalid modulo and square root are reported cleanly."""

        modulo = construct_type(
            gamma={"x": BasicType.REAL},
            theta={},
            configurations=[Configuration({"x": 0}, Assign("x", "x % 2"))],
        )
        square_root = construct_type(
            gamma={"y": BasicType.REAL},
            theta={},
            configurations=[Configuration({"y": 0}, Assign("y", "sqrt(-1)"))],
        )

        self.assertEqual(modulo.verdict, Verdict.FALSE)
        self.assertTrue(
            any("Modulo operands" in item.message for item in modulo.diagnostics)
        )
        self.assertEqual(square_root.verdict, Verdict.FALSE)
        self.assertTrue(
            any(item.rule == "T-Assign" for item in square_root.obligations)
        )


    def test_if_guard_is_defined_before_branching(self) -> None:
        r"""Verify if guard is defined before branching."""

        process = If("1 / x > 0", Skip(), Skip())
        accepted = construct_type(
            gamma={"x": BasicType.REAL},
            theta={},
            configurations=[Configuration({"x": 1}, process)],
            path_condition="x != 0",
        )
        rejected = construct_type(
            gamma={"x": BasicType.REAL},
            theta={},
            configurations=[Configuration({"x": 0}, process)],
        )

        self.assertEqual(accepted.verdict, Verdict.TRUE)
        self.assertEqual(rejected.verdict, Verdict.FALSE)
        self.assertTrue(
            any(item.rule == "T-If" for item in rejected.obligations)
        )


    def test_output_refinement_includes_definedness(self) -> None:
        r"""Verify output refinement includes definedness."""

        report = construct_type(
            gamma={},
            theta={
                "ch": ChannelType(
                    BasicType.REAL,
                    "1 / eta > 0",
                    binders="eta",
                )
            },
            configurations=[Configuration({}, OutputChannel("ch", 0))],
        )

        self.assertEqual(report.verdict, Verdict.FALSE)
        obligation = next(
            item for item in report.obligations if item.rule == "T-Out"
        )
        self.assertEqual(obligation.verdict, Verdict.FALSE)


    def test_string_does_not_masquerade_as_boolean_state(self) -> None:
        r"""Verify string does not masquerade as boolean state."""

        symbol = z3.Bool("b")
        verdict, detail = Z3ProofEngine().state_satisfies(
            symbol,
            {"b": "false"},
            {"b": symbol},
        )

        self.assertEqual(verdict, Verdict.FALSE)
        self.assertIn("must be bool", detail)


if __name__ == "__main__":
    unittest.main()
