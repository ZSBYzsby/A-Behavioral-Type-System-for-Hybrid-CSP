r"""Regression tests for t sigma partial state. Paper reference: Table 2."""

from __future__ import annotations

import unittest

from hcsp_typechecker._internal import (
    BasicType,
    Configuration,
    EmptyType,
    Skip,
    Verdict,
    construct_type,
)
from hcsp_typechecker.backend.common.logic import Z3ProofEngine, z3


@unittest.skipIf(z3 is None, "z3-solver is required")
class TSigmaPartialStateTests(unittest.TestCase):
    r"""Tests for T Sigma Partial State."""
    def test_partial_state_is_accepted_when_residual_formula_is_valid(self) -> None:
        r"""Verify partial state is accepted when residual formula is valid."""

        report = construct_type(
            gamma={"x": BasicType.REAL, "y": BasicType.REAL},
            theta={},
            configurations=[Configuration({"x": 0}, Skip())],
            path_condition="x == 0 and y * y >= 0",
        )

        self.assertEqual(report.verdict, Verdict.TRUE)
        self.assertEqual(report.constructed_type, EmptyType())
        obligation = next(
            item for item in report.obligations if item.rule == "T-sigma"
        )
        self.assertEqual(obligation.verdict, Verdict.TRUE)
        self.assertIn("residual path condition is valid", obligation.detail)
    def test_counterexample_to_residual_formula_is_false_not_unknown(self) -> None:
        r"""Verify counterexample to residual formula is false not unknown."""

        report = construct_type(
            gamma={"x": BasicType.REAL, "y": BasicType.REAL},
            theta={},
            configurations=[Configuration({"x": 0}, Skip())],
            path_condition="x == 0 and y > 0",
        )

        self.assertEqual(report.verdict, Verdict.FALSE)
        self.assertIsNone(report.constructed_type)
        obligation = next(
            item for item in report.obligations if item.rule == "T-sigma"
        )
        self.assertEqual(obligation.verdict, Verdict.FALSE)
        self.assertIn("residual path condition is not valid", obligation.detail)
        self.assertIn("counterexample", obligation.detail)
        self.assertFalse(any(item.rule == "T-End" for item in report.steps))


    def test_undeclared_state_variable_stops_type_generation(self) -> None:
        r"""Verify undeclared state variable stops type generation."""

        report = construct_type(
            gamma={"x": BasicType.INT},
            theta={},
            configurations=[Configuration({"x": 0, "ghost": 1}, Skip())],
            path_condition=True,
        )

        self.assertEqual(report.verdict, Verdict.FALSE)
        self.assertIsNone(report.constructed_type)
        self.assertFalse(
            any(item.rule == "T-sigma" for item in report.obligations)
        )
        self.assertTrue(
            any(
                "not declared in Gamma" in item.message
                and "ghost" in item.message
                for item in report.diagnostics
            )
        )


    def test_proof_engine_also_rejects_undeclared_state_variable(self) -> None:
        r"""Verify proof engine also rejects undeclared state variable."""

        x = z3.Int("x")
        verdict, detail = Z3ProofEngine().state_satisfies(
            x == 0,
            {"x": 0, "ghost": 1},
            {"x": x},
        )

        self.assertEqual(verdict, Verdict.FALSE)
        self.assertIn("not declared in Gamma", detail)
        self.assertIn("ghost", detail)


if __name__ == "__main__":
    unittest.main()
