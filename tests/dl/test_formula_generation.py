r"""Regression tests for formula generation. Paper reference: Table 2, Section 4.3."""

from __future__ import annotations

from math import inf
import unittest

from hcsp_typechecker._internal import (
    Assign,
    BasicType,
    ChannelType,
    Configuration,
    ContinuousType,
    DLFormula,
    ODE,
    ODEAnnotation,
    OutputChannel,
    Sequence,
    Skip,
    UntranslatedDLFormula,
    Verdict,
    construct_type,
)


def _approve_and_collect(storage: list[object]):
    r"""Collect dL obligations while approving them with a mock backend."""

    def checker(obligation: object) -> Verdict:
        r"""Return a controlled dL verdict for rule and formula tests."""

        storage.append(obligation)
        return Verdict.TRUE

    return checker


def _select_timeout_and_collect(storage: list[object]):
    r"""Collect dL goals and select the boundary candidate."""

    def checker(obligation: object) -> Verdict:
        r"""Return a controlled dL verdict for rule and formula tests."""

        storage.append(obligation)
        role = getattr(getattr(obligation, "formula", None), "role", "")
        return Verdict.FALSE if role == "domain" else Verdict.TRUE

    return checker


def _local_clock_name(test: unittest.TestCase, formula: DLFormula) -> str:
    r"""Recover the fresh local clock name from the prover symbol mapping."""

    clocks = [
        safe
        for safe, original in formula.symbol_map
        if original.startswith("@hcsp_ode_clock_")
    ]
    test.assertEqual(len(clocks), 1, formula.symbol_map)
    return clocks[0]


class DLFormulaGenerationTests(unittest.TestCase):
    r"""Tests for dL Formula Generation."""


    def test_safety_and_domain_are_formal_box_modalities(self) -> None:
        r"""Verify safety and domain are formal box modalities."""

        captured: list[object] = []
        process = Sequence.of(
            ODE(
                [("x", "t + 1")],
                "t <= 10 and x <= 10",
                annotation=ODEAnnotation(
                    safety="x >= t and t <= 2",
                    delay=inf,
                ),
            ),
            Skip(),
        )
        report = construct_type(
            gamma={"x": BasicType.REAL, "ode_x": ContinuousType(("x",))},
            theta={},
            configurations=[Configuration({"x": 0}, process)],
            path_condition="x == 0",
            dl_checker=_approve_and_collect(captured),
        )

        self.assertEqual(report.verdict, Verdict.TRUE)
        formulas = {
            item.rule: item.formula
            for item in report.obligations
            if item.kind == "dl"
        }
        safety = formulas["T-ODE-safety"]
        domain = formulas["T-ODE-domain"]
        self.assertIsInstance(safety, DLFormula)
        self.assertIsInstance(domain, DLFormula)
        safety_clock = _local_clock_name(self, safety)
        domain_clock = _local_clock_name(self, domain)
        self.assertIn(f"{safety_clock}'=1", safety.source)
        self.assertIn(f"'=({safety_clock} + 1)", safety.source)
        self.assertNotIn(f"{safety_clock}<=2 ->", safety.source)
        self.assertIn(f" >= {safety_clock}", safety.source)
        self.assertTrue(
            f"{safety_clock} = 0" in safety.source
            or f"0 = {safety_clock}" in safety.source
        )
        self.assertIn("[{", safety.source)
        self.assertIn("}](", safety.source)
        safety_program = safety.source.split("}]", 1)[0]
        domain_program = domain.source.split("}]", 1)[0]
        safety_post = safety.source.split("}]", 1)[1]
        self.assertIn(" >= ", safety_post)
        self.assertNotRegex(domain.source, r"0 <= kxv\d+")
        self.assertNotIn("10 >=", safety_program)
        self.assertNotIn("10 >=", domain_program)
        self.assertIn("-> [{", domain.source)
        self.assertIn(f"{domain_clock}'=1", domain.source)
        self.assertIn(f"'=({domain_clock} + 1)", domain.source)
        self.assertIn(f"10 >= {domain_clock}", domain.source)
        self.assertTrue(
            f"{domain_clock} = 0" in domain.source
            or f"0 = {domain_clock}" in domain.source
        )
        self.assertNotIn("K1__", safety.source)
        self.assertNotIn("__dlentry", safety.source)
        self.assertNotIn("T-ODE-boundary", formulas)


    def test_boundary_uses_strict_before_and_not_domain_at_deadline(self) -> None:
        r"""Verify boundary uses strict before and not domain at deadline."""

        captured: list[object] = []
        process = Sequence.of(
            ODE(
                [("x", 1)],
                "x < 1",
                annotation=ODEAnnotation(safety="x <= 1", delay=1),
            ),
            OutputChannel("done", 0),
        )
        report = construct_type(
            gamma={"x": BasicType.REAL, "ode_x": ContinuousType(("x",))},
            theta={"done": ChannelType(BasicType.INT)},
            configurations=[Configuration({"x": 0}, process)],
            path_condition="x == 0",
            dl_checker=_approve_and_collect(captured),
        )

        boundary = next(
            item.formula
            for item in report.obligations
            if item.rule == "T-ODE-boundary"
        )
        self.assertIsInstance(boundary, DLFormula)
        clock = _local_clock_name(self, boundary)
        self.assertIn("[{", boundary.source)
        self.assertNotIn("<{", boundary.source)
        boundary_program = boundary.source.split("}]", 1)[0]
        self.assertNotIn("1 >", boundary_program)
        self.assertIn(f"1 > {clock}", boundary.source)
        self.assertIn(f"1 = {clock}", boundary.source)
        self.assertIn("-> !(", boundary.source)


    def test_exact_rational_delay_is_serialized_for_keymaerax(self) -> None:
        r"""Verify exact rational delay is serialized for KeYmaera X."""

        captured: list[object] = []
        process = Sequence.of(
            ODE(
                [("x", 1)],
                "2 * x < 1",
                annotation=ODEAnnotation(
                    safety="2 * x <= 1",
                    delay="1 / 2",
                ),
            ),
            OutputChannel("done", 0),
        )
        report = construct_type(
            gamma={"x": BasicType.REAL, "ode_x": ContinuousType(("x",))},
            theta={"done": ChannelType(BasicType.INT)},
            configurations=[Configuration({"x": 0}, process)],
            path_condition="x == 0",
            dl_checker=_approve_and_collect(captured),
        )

        boundary = next(
            item.formula
            for item in report.obligations
            if item.rule == "T-ODE-boundary"
        )
        self.assertEqual(report.verdict, Verdict.TRUE)
        self.assertIsInstance(boundary, DLFormula)
        clock = _local_clock_name(self, boundary)
        self.assertIn(f"(1/2) > {clock}", boundary.source)
        self.assertIn(f"(1/2) = {clock}", boundary.source)


    def test_assignment_before_ode_is_materialized_at_entry(self) -> None:
        r"""Verify assignment before ODE is materialized at entry."""

        captured: list[object] = []
        process = Sequence.of(
            Assign("x", "x + 1"),
            ODE(
                [("x", 0)],
                True,
                annotation=ODEAnnotation(safety="x >= 1", delay=1),
            ),
            Skip(),
        )
        report = construct_type(
            gamma={"x": BasicType.REAL, "ode_x": ContinuousType(("x",))},
            theta={},
            configurations=[Configuration({"x": 0}, process)],
            path_condition="x == 0",
            dl_checker=_approve_and_collect(captured),
        )

        safety = next(
            item.formula
            for item in report.obligations
            if item.rule == "T-ODE-safety"
        )
        self.assertIsInstance(safety, DLFormula)
        original_names = {original for _safe, original in safety.symbol_map}
        self.assertIn("K1__x", original_names)
        self.assertTrue(
            any("__dlentry" in name for name in original_names),
            safety.symbol_map,
        )
        self.assertIn(" + 1", safety.source)
        self.assertIn(" = ", safety.source)


    def test_infinite_delay_safety_becomes_an_invariant(self) -> None:
        r"""Verify infinite delay safety becomes an invariant."""

        captured: list[object] = []
        process = Sequence.of(
            ODE(
                [("x", 0)],
                "x >= 0",
                annotation=ODEAnnotation(safety="x >= 0", delay=inf),
            ),
            Skip(),
        )
        report = construct_type(
            gamma={"x": BasicType.REAL, "ode_x": ContinuousType(("x",))},
            theta={},
            configurations=[Configuration({"x": 0}, process)],
            path_condition="x >= 0",
            dl_checker=_approve_and_collect(captured),
        )

        safety = next(
            item.formula
            for item in report.obligations
            if item.rule == "T-ODE-safety"
        )
        self.assertIsInstance(safety, DLFormula)
        clock = _local_clock_name(self, safety)
        self.assertIn("-> [{", safety.source)
        self.assertIn(f"{clock}'=1", safety.source)
        self.assertTrue(
            f"{clock} = 0" in safety.source
            or f"0 = {clock}" in safety.source
        )


    def test_hidden_clock_supports_ode_without_user_equations(self) -> None:
        r"""Verify hidden clock supports ODE without user equations."""

        captured: list[object] = []
        process = Sequence.of(
            ODE((), "t < 1", annotation=ODEAnnotation(delay=1)),
            Skip(),
        )
        report = construct_type(
            gamma={},
            theta={},
            configurations=[Configuration({}, process)],
            dl_checker=_select_timeout_and_collect(captured),
        )

        boundary = next(
            item.formula
            for item in report.obligations
            if item.rule == "T-ODE-boundary"
        )
        self.assertEqual(report.verdict, Verdict.TRUE)
        self.assertIsInstance(boundary, DLFormula)
        clock = _local_clock_name(self, boundary)
        self.assertIn(f"[{{{clock}'=1}}]", boundary.source)
        self.assertIn(f"1 > {clock}", boundary.source)
        self.assertIn(f"1 = {clock}", boundary.source)
        self.assertIn("-> !(", boundary.source)
        self.assertTrue(
            f"{clock} = 0" in boundary.source
            or f"0 = {clock}" in boundary.source
        )


    def test_partial_ode_derivative_enters_definedness_obligation(self) -> None:
        r"""Verify partial ODE derivative enters definedness obligation."""

        captured: list[object] = []
        process = Sequence.of(
            ODE(
                [("x", "1 / y")],
                "t < 1",
                annotation=ODEAnnotation(safety=True, delay=1),
            ),
            OutputChannel("done", 0),
        )
        report = construct_type(
            gamma={
                "x": BasicType.REAL,
                "y": BasicType.REAL,
                "ode_x": ContinuousType(("x",)),
            },
            theta={"done": ChannelType(BasicType.INT)},
            configurations=[Configuration({"x": 0, "y": 0}, process)],
            path_condition="x == 0 and y == 0",
            dl_checker=_approve_and_collect(captured),
        )

        safety = next(
            item.formula
            for item in report.obligations
            if item.rule == "T-ODE-safety"
        )
        self.assertIsInstance(safety, DLFormula)
        self.assertNotEqual(safety.source, "true")
        self.assertIn("!= 0", safety.source)
        self.assertNotRegex(safety.source, r"\[\{[^}]+ & ")


    def test_uninterpreted_derivative_is_not_string_spliced(self) -> None:
        r"""Verify uninterpreted derivative is not string spliced."""

        process = Sequence.of(
            ODE(
                [("x", "mystery(x)")],
                True,
                annotation=ODEAnnotation(safety="x >= 0", delay=1),
            ),
            Skip(),
        )
        report = construct_type(
            gamma={"x": BasicType.REAL, "ode_x": ContinuousType(("x",))},
            theta={},
            configurations=[Configuration({"x": 0}, process)],
            path_condition="x == 0",
        )

        safety = next(
            item
            for item in report.obligations
            if item.rule == "T-ODE-safety"
        )
        self.assertEqual(safety.verdict, Verdict.UNKNOWN)
        self.assertIsInstance(safety.formula, UntranslatedDLFormula)
        self.assertIn("unsupported dL term", safety.formula.reason)


    def test_boolean_state_in_precondition_is_rejected_conservatively(self) -> None:
        r"""Verify boolean state in precondition is rejected conservatively."""

        process = Sequence.of(
            ODE(
                [("x", 0)],
                True,
                annotation=ODEAnnotation(safety="x >= 0", delay=1),
            ),
            Skip(),
        )
        report = construct_type(
            gamma={
                "x": BasicType.REAL,
                "flag": BasicType.BOOL,
                "ode_x": ContinuousType(("x",)),
            },
            theta={},
            configurations=[Configuration({"x": 0, "flag": True}, process)],
            path_condition="flag and x == 0",
        )

        safety = next(
            item
            for item in report.obligations
            if item.rule == "T-ODE-safety"
        )
        self.assertEqual(safety.verdict, Verdict.UNKNOWN)
        self.assertIsInstance(safety.formula, UntranslatedDLFormula)
        self.assertIn("Boolean state variable", safety.formula.reason)


    def test_archive_declares_every_variable_and_tactic(self) -> None:
        r"""Verify archive declares every variable and tactic."""

        formula = DLFormula(
            "(kxv0=kxv0)",
            ("kxv0",),
            (("kxv0", "K1__x"),),
            "smoke",
        )
        archive = formula.to_archive(
            entry_name='unsafe "name"\nline',
            tactic="auto",
        )

        self.assertIn('ArchiveEntry "unsafe \'name\' line"', archive)
        self.assertIn("ProgramVariables\n  Real kxv0;\nEnd.", archive)
        self.assertIn("Problem\n  (kxv0=kxv0)\nEnd.", archive)
        self.assertIn('Tactic "HCSP Proof"\n  auto\nEnd.', archive)
        self.assertTrue(archive.endswith("End.\n"))


if __name__ == "__main__":
    unittest.main()
