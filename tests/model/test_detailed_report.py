r"""Regression tests for detailed report. Paper reference: Section 4.2/4.3, Table 2."""

from __future__ import annotations

import unittest

from hcsp_typechecker._internal import (
    BasicType,
    ChannelType,
    TypeConstructionReport,
    Configuration,
    ContinuousType,
    EmptyType,
    InputChannel,
    ODE,
    ODEAnnotation,
    OutputChannel,
    FiniteDelayType,
    NoInterruptType,
    ProofObligation,
    Sequence,
    Skip,
    Verdict,
    construct_type,
)


class DetailedReportTests(unittest.TestCase):
    r"""Tests for Detailed Report."""

    def _report(self):
        r"""Build a two-step communication report with a controlled dL backend."""

        process = Sequence.of(
            InputChannel("ch", "x"),
            OutputChannel("ch", "x"),
        )
        return construct_type(
            gamma={},
            theta={"ch": ChannelType(BasicType.INT)},
            configurations=[Configuration({}, process)],
            path_condition=True,
        )


    def test_trace_exposes_rule_order_and_input_environment_change(self) -> None:
        r"""Verify trace exposes rule order and input environment change."""

        report = self._report()

        self.assertEqual(report.verdict, Verdict.TRUE)
        self.assertEqual(
            tuple(step.rule for step in report.steps),
            (
                "environment",
                "T-||",
                "T-sigma",
                "Proof",
                "T-In",
                "T-Out",
                "Proof",
                "T-End",
            ),
        )
        self.assertEqual(
            tuple(step.number for step in report.steps),
            (1, 2, 3, 4, 5, 6, 7, 8),
        )

        input_step = next(step for step in report.steps if step.rule == "T-In")
        output_step = next(step for step in report.steps if step.rule == "T-Out")
        self.assertEqual(input_step.gamma, ())
        self.assertEqual(output_step.gamma, (("x", "Int"),))
        self.assertTrue(
            any(name == "x" and "__input" in term for name, term in output_step.symbolic_state)
        )
        self.assertIn(
            "forever interrupt angelic {\n"
            "    ch? -> forever interrupt angelic {\n"
            "        ch! -> empty\n"
            "    }\n"
            "}",
            input_step.result,
        )
        self.assertIn(
            "forever interrupt angelic {\n"
            "    ch! -> empty\n"
            "}",
            output_step.result,
        )
        proof_steps = tuple(step for step in report.steps if step.rule == "Proof")
        self.assertEqual(len(proof_steps), 2)
        self.assertTrue(all("= true" in step.result for step in proof_steps))
        output_obligation = next(
            obligation
            for obligation in report.obligations
            if obligation.rule == "T-Out"
        )
        self.assertIsNotNone(output_obligation.proof_formula)


    def test_detailed_text_separates_construction_from_proof_evidence(self) -> None:
        r"""Verify detailed text separates construction from proof evidence."""

        rendered = self._report().format_detailed()

        expected_fragments = (
            'Overall verdict : true',
            'Rule derivation : complete',
            'Type construction : success',
            'Type trust : trusted (all obligations verified)',
            'Constructed Type source : type forever interrupt angelic {\n    ch? -> forever interrupt angelic {\n        ch! -> empty\n    }\n}',
            '=== Rule execution trace ===',
            "T-In @ K1",
            "T-Out @ K1",
            "Gamma    : x:Int",
            "Theta    : ch:{eta:Int | true}",
            '=== First-order logic (FOL) proof formulas for type construction ===',
            '[FOL01] corresponds to O01 | proved | T-sigma | STATE',
            '[FOL02] corresponds to O02 | proved | T-Out | FOL',
            'Checked formula:',
            '=== Differential dynamic logic (dL) proof formulas for type construction ===',
            '(no dL formulas)',
            '=== Sequential formula decisions ===',
            '[O02] proved | T-Out | FOL',
            'Paper premise : [T-Out]  phi => refinement{e/eta}',
            'Rule-generated formula (original):',
            'Actual prover input : see [FOL02]',
            'Proof backend : Z3 validity check',
            'Resolution : resolved',
            '=== Unresolved or failed proof obligations ===',
            '(none; all generated proof obligations were proved)',
            "Proof @ K1",
            '=== Diagnostics ===',
            '=== Summary ===',
            'Rule steps : 8',
            'Proof records : 2',
            'Proof obligations : 2 (true=2, false=0, unknown=0)',
            'Outstanding obligations : 0 (failed=0, unproved=0)',
        )
        for fragment in expected_fragments:
            with self.subTest(fragment=fragment):
                self.assertIn(fragment, rendered)
        self.assertNotIn('Compact type :', rendered)


    def test_unknown_dl_formulas_are_indexed_without_duplicate_bodies(self) -> None:
        r"""Verify unknown dL formulas are indexed without duplicate bodies."""

        process = Sequence.of(
            ODE(
                [("x", 1)],
                "x < 1",
                annotation=ODEAnnotation(safety="x <= 1", delay=1),
            ),
            Skip(),
        )
        report = construct_type(
            gamma={"x": BasicType.REAL, "ode_x": ContinuousType(("x",))},
            theta={},
            configurations=[Configuration({"x": 0}, process)],
            path_condition="x == 0",
            dl_checker=lambda _obligation: None,
        )
        rendered = report.format_detailed()

        self.assertEqual(report.verdict, Verdict.UNKNOWN)
        self.assertEqual(
            report.constructed_type,
            FiniteDelayType(1, NoInterruptType(), EmptyType()),
        )
        expected_fragments = (
            'Rule derivation : complete',
            'Type construction : success',
            'Type trust : untrusted (unverified obligations)',
            'Constructed Type source : type delay(1) then empty',
            "T-ODE-safety",
            "T-ODE-domain",
            "T-ODE-boundary",
            "[T-unrhd-prime]",
            'Proof obligations : 5',
            'Outstanding obligations : 2',
        )
        for fragment in expected_fragments:
            with self.subTest(fragment=fragment):
                self.assertIn(fragment, rendered)
        self.assertNotIn("FiniteDelayType(", rendered)
        shared_formula = str(report.obligations[1].proof_formula)
        self.assertEqual(
            rendered.splitlines().count(f"       {shared_formula}"),
            1,
        )


    def test_formula_bodies_are_printed_once_and_referenced_elsewhere(self) -> None:
        r"""Verify formula bodies are printed once and referenced elsewhere."""

        obligations = (
            ProofObligation(
                "T-Test",
                "normalized formula",
                "RAW_UNIQUE_FORMULA",
            ).decided(Verdict.TRUE, proof_formula="NORMALIZED_UNIQUE_FORMULA"),
            ProofObligation(
                "T-Test",
                "first shared formula",
                "SHARED_FORMULA",
            ).decided(Verdict.TRUE),
            ProofObligation(
                "T-Test",
                "second shared formula",
                "SHARED_FORMULA",
            ).decided(Verdict.TRUE),
        )
        report = TypeConstructionReport(
            verdict=Verdict.TRUE,
            constructed_type=EmptyType(),
            constructed_component_types=(EmptyType(),),
            obligations=obligations,
            diagnostics=(),
        )

        rendered = report.format_detailed()
        lines = rendered.splitlines()

        self.assertEqual(lines.count("       RAW_UNIQUE_FORMULA"), 1)
        self.assertEqual(lines.count("       NORMALIZED_UNIQUE_FORMULA"), 1)
        self.assertEqual(lines.count("       SHARED_FORMULA"), 1)
        self.assertIn('Actual prover input : see [FOL01]', rendered)
        self.assertIn(
            'Rule formula matches actual prover input : see [FOL02]',
            rendered,
        )
        self.assertIn(
            'Checked formula : same as [FOL02]; not repeated',
            rendered,
        )


if __name__ == "__main__":
    unittest.main()
