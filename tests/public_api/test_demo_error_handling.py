r"""Regression tests for demo error handling. Paper reference: Table 2."""

from __future__ import annotations

from contextlib import redirect_stdout
from io import StringIO
import unittest

from examples import demo_type_construction as construction_demo
from examples import demo_type_checking as checking_demo


class DemoStructuredErrorTests(unittest.TestCase):
    r"""Tests for Demo Structured Error."""


    def test_constructor_demo_reports_structured_input_error(self) -> None:
        r"""Verify constructor demo reports structured input error."""

        output = StringIO()
        with redirect_stdout(output):
            outcome = construction_demo._run_example(
                99,
                'Invalid input',
                'Check structured input diagnostics',
                "gamma() theta() process {{skip",
            )

        rendered = output.getvalue()
        self.assertEqual(outcome, "failed")
        self.assertIn('Script outcome: invalid input [input-syntax]', rendered)
        self.assertIn("demo-example-99.hcsp:", rendered)


    def test_constructor_demo_reports_structured_proof_failure(self) -> None:
        r"""Verify constructor demo reports structured proof failure."""

        output = StringIO()
        with redirect_stdout(output):
            outcome = construction_demo._run_example(
                100,
                'Disproved assertion',
                'Check structured proof failure',
                "gamma() theta() process {{assert(false)}}",
            )

        rendered = output.getvalue()
        self.assertEqual(outcome, "failed")
        self.assertIn("[proof-failed/proof]", rendered)
        self.assertIn('rule T-Assert', rendered)
        self.assertIn('judgment location K1', rendered)


    def test_checker_demo_requires_the_expected_error_kind(self) -> None:
        r"""Verify checker demo requires the expected error kind."""

        output = StringIO()
        with redirect_stdout(output):
            exit_code = checking_demo.main()

        rendered = output.getvalue()
        self.assertEqual(exit_code, 0)
        self.assertIn("[type-mismatch/type-matching]", rendered)
        self.assertIn('rule T-Out', rendered)
        self.assertNotIn('Python return object', rendered)


if __name__ == "__main__":
    unittest.main()
