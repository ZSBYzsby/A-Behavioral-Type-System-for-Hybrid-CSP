r"""Regression tests for assignment poststate. Paper reference: Table 2."""

from __future__ import annotations

import unittest

from hcsp_typechecker._internal import (
    Assert,
    Assign,
    BasicType,
    Configuration,
    Sequence,
    TypeConstructor,
    TypeConstructionRequest,
    Verdict,
)


class AssignmentPostStateTests(unittest.TestCase):
    r"""Tests for Assignment Post State."""


    def test_successive_assignments_build_poststates_before_child_judgments(self) -> None:
        r"""Verify successive assignments build poststates before child judgments."""

        process = Sequence.of(
            Assign("x", "x + 1"),
            Assign("y", "2 * x"),
            Assert("y == 2 * x"),
        )
        constructor = TypeConstructor(dl_checker=lambda _obligation: True)
        report = constructor.construct(
            TypeConstructionRequest(
                gamma={"x": BasicType.INT, "y": BasicType.INT},
                theta={},
                configurations=[Configuration({"x": 3, "y": 0}, process)],
                path_condition="x == 3",
            )
        )

        self.assertEqual(report.verdict, Verdict.TRUE)
        assignment_steps = tuple(
            step for step in report.steps if step.rule == "T-Assign"
        )
        assertion_step = next(
            step for step in report.steps if step.rule == "T-Assert"
        )
        self.assertEqual(len(assignment_steps), 2)

        first_symbols = dict(assignment_steps[0].symbolic_state)
        second_symbols = dict(assignment_steps[1].symbolic_state)
        assertion_symbols = dict(assertion_step.symbolic_state)
        self.assertEqual(first_symbols["x"], "K1__x")
        self.assertIn("K1__x", second_symbols["x"])
        self.assertIn("1", second_symbols["x"])
        self.assertIn("K1__x", assertion_symbols["y"])
        self.assertNotEqual(assertion_symbols["y"], "K1__y")
        for step in assignment_steps:
            self.assertIn('Lazy strongest post-state', step.detail)
            self.assertIn('predicate synthesis is unnecessary', step.detail)


    def test_total_assignment_adds_only_concrete_table2_postcondition(self) -> None:
        r"""Verify total assignment adds only concrete table2 postcondition."""

        process = Sequence.of(
            Assign("x", "x + 1"),
            Assert("x >= 1"),
        )
        constructor = TypeConstructor(dl_checker=lambda _obligation: True)
        report = constructor.construct(
            TypeConstructionRequest(
                gamma={"x": BasicType.INT},
                theta={},
                configurations=[Configuration({"x": 0}, process)],
                path_condition="x >= 0",
            )
        )

        self.assertEqual(report.verdict, Verdict.TRUE)
        decided = report.obligations
        self.assertEqual(
            tuple(item.rule for item in decided),
            ("T-sigma", "T-Assign-post", "T-Assert"),
        )
        self.assertTrue(all(item.verdict == Verdict.TRUE for item in decided))
        postcondition = decided[1]
        postcondition_formula = str(postcondition.formula)
        self.assertIn("Implies", postcondition_formula)
        self.assertGreaterEqual(postcondition_formula.count("K1__x"), 2)
        self.assertIn("generated lazy strongest post-state", postcondition.description)
        assertion_formula = str(decided[2].formula)
        self.assertIn("K1__x + 1", assertion_formula)
        self.assertFalse(
            any("unknown" in item.description.lower() for item in decided),
            "Sequential proofs must contain concrete premises, not synthesis tasks",
        )


    def test_partial_rhs_adds_only_concrete_definedness_formula(self) -> None:
        r"""Verify partial rhs adds only concrete definedness formula."""

        constructor = TypeConstructor(dl_checker=lambda _obligation: True)
        report = constructor.construct(
            TypeConstructionRequest(
                gamma={"x": BasicType.REAL, "y": BasicType.REAL},
                theta={},
                configurations=[
                    Configuration({"x": 2, "y": 0}, Assign("y", "1 / x"))
                ],
                path_condition="x != 0",
            )
        )

        self.assertEqual(report.verdict, Verdict.TRUE)
        assignment_premises = tuple(
            item
            for item in report.obligations
            if item.rule == "T-Assign"
        )
        self.assertEqual(len(assignment_premises), 1)
        self.assertIn("is defined", assignment_premises[0].description)
        self.assertIn("K1__x", str(assignment_premises[0].formula))
        self.assertNotIn("phi'", assignment_premises[0].description)


if __name__ == "__main__":
    unittest.main()
