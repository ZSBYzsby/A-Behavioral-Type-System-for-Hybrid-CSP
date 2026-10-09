r"""Regression tests for table2 rule contract. Paper reference: Table 2."""

from __future__ import annotations

from math import inf
import unittest
from typing import Any, Mapping, Sequence as TypingSequence

from hcsp_typechecker._internal import (
    Assert,
    Assign,
    BasicType,
    ChannelType,
    Configuration,
    ContinuousType,
    EventChoice,
    If,
    InputChannel,
    InternalChoice,
    Mu,
    ODE,
    ODEAnnotation,
    OutputChannel,
    Sequence,
    Skip,
    TypeConstructor,
    TypeConstructionRequest,
    Var,
    Verdict,
    construct_type,
)


def _approve_dl(_obligation: object) -> Verdict:
    r"""Approve dL goals with a mock backend to isolate rule structure."""

    return Verdict.TRUE


def _select_boundary_rule(obligation: object) -> Verdict:
    r"""Reject domain preservation and approve the boundary candidate."""

    formula = getattr(obligation, "formula", None)
    return (
        Verdict.FALSE
        if getattr(formula, "role", "") == "domain"
        else Verdict.TRUE
    )


def _construct_one(
    process: object,
    *,
    gamma: Mapping[str, BasicType | ContinuousType] | None = None,
    theta: Mapping[str, ChannelType] | None = None,
    state: Mapping[str, Any] | None = None,
    path: object = True,
    dl_checker: object = _approve_dl,
):
    r"""Wrap one process in T-sigma and retain full construction evidence."""

    return construct_type(
        gamma={} if gamma is None else gamma,
        theta={} if theta is None else theta,
        configurations=[Configuration(state, process)],
        path_condition=path,
        dl_checker=dl_checker,  # type: ignore[arg-type]
    )


def _obligation_signature(report: object) -> tuple[tuple[str, str], ...]:
    r"""Extract rule and formula-kind pairs in generation order."""

    return tuple(
        (obligation.rule, obligation.kind)
        for obligation in report.obligations  # type: ignore[attr-defined]
        if obligation.active
    )


def _step_rules(report: object) -> tuple[str, ...]:
    r"""Extract rule names including immediate Proof steps."""

    return tuple(step.rule for step in report.steps)  # type: ignore[attr-defined]


class Table2RuleContractTests(unittest.TestCase):
    r"""Tests for Table2 Rule Contract."""


    def test_t_end_and_t_skip_follow_the_exact_source_shape(self) -> None:
        r"""Verify t end and t skip follow the exact source shape."""

        terminal = _construct_one(Skip())
        self.assertEqual(terminal.verdict, Verdict.TRUE)
        terminal_steps = _step_rules(terminal)
        self.assertIn("T-End", terminal_steps)
        self.assertNotIn("T-Skip", terminal_steps)
        self.assertEqual(
            _obligation_signature(terminal),
            (("T-sigma", "state"),),
        )

        theta = {"done": ChannelType(BasicType.INT)}
        intermediate = _construct_one(
            Sequence.of(Skip(), OutputChannel("done", 0)),
            theta=theta,
        )
        self.assertEqual(intermediate.verdict, Verdict.TRUE)
        intermediate_steps = _step_rules(intermediate)
        self.assertIn("T-Skip", intermediate_steps)
        self.assertIn("T-End", intermediate_steps)
        self.assertLess(
            intermediate_steps.index("T-Skip"),
            intermediate_steps.index("T-Out"),
        )
        self.assertEqual(
            _obligation_signature(intermediate),
            (("T-sigma", "state"), ("T-Out", "fol")),
        )


    def test_discrete_rules_generate_exact_table2_formula_sets(self) -> None:
        r"""Verify discrete rules generate exact table2 formula sets."""

        integer_channel = ChannelType(BasicType.INT)
        cases: TypingSequence[
            tuple[
                str,
                object,
                Mapping[str, BasicType | ContinuousType],
                Mapping[str, ChannelType],
                Mapping[str, Any],
                object,
                tuple[tuple[str, str], ...],
                str,
            ]
        ] = (
            (
                "T-Assert",
                Assert("x >= 0"),
                {"x": BasicType.INT},
                {},
                {"x": 0},
                "x >= 0",
                (("T-sigma", "state"), ("T-Assert", "fol")),
                "T-Assert",
            ),
            (
                "T-Assign",
                Assign("x", "x + 1"),
                {"x": BasicType.INT},
                {},
                {"x": 0},
                True,
                (("T-sigma", "state"), ("T-Assign-post", "fol")),
                "T-Assign",
            ),
            (
                "T-If",
                If("x >= 0", Skip(), Skip()),
                {"x": BasicType.INT},
                {},
                {"x": 0},
                True,
                (("T-sigma", "state"),),
                "T-If",
            ),
            (
                "T-In",
                InputChannel("data", "x"),
                {},
                {"data": integer_channel},
                {},
                True,
                (("T-sigma", "state"),),
                "T-In",
            ),
            (
                "T-Out",
                OutputChannel("data", 1),
                {},
                {"data": integer_channel},
                {},
                True,
                (("T-sigma", "state"), ("T-Out", "fol")),
                "T-Out",
            ),
            (
                "T-sqcup",
                InternalChoice(Skip(), Skip()),
                {},
                {},
                {},
                True,
                (("T-sigma", "state"),),
                "T-sqcup",
            ),
        )

        for (
            name,
            process,
            gamma,
            theta,
            state,
            path,
            expected,
            expected_step,
        ) in cases:
            with self.subTest(rule=name):
                report = _construct_one(
                    process,
                    gamma=gamma,
                    theta=theta,
                    state=state,
                    path=path,
                )
                self.assertEqual(report.verdict, Verdict.TRUE)
                self.assertEqual(_obligation_signature(report), expected)
                self.assertIn(expected_step, _step_rules(report))

        assignment = _construct_one(
            Assign("x", "x + 1"),
            gamma={"x": BasicType.INT},
            state={"x": 0},
        )
        post_premise = assignment.obligations[1]
        self.assertIn("Implies", str(post_premise.formula))
        self.assertIn("phi => phi'{e/x}", post_premise.description)


    def test_external_choice_and_communication_only_ode_formula_set(self) -> None:
        r"""Verify external choice and communication only ODE formula set."""

        integer_channel = ChannelType(BasicType.INT)
        process = Sequence.of(
            ODE(
                [("x", 0)],
                True,
                EventChoice.of(
                    (OutputChannel("left", 0), Skip()),
                    (OutputChannel("right", 1), Skip()),
                ),
                annotation=ODEAnnotation(safety=True, delay=inf),
            ),
            Skip(),
        )
        report = _construct_one(
            process,
            gamma={"x": BasicType.REAL, "ode_x": ContinuousType(("x",))},
            theta={"left": integer_channel, "right": integer_channel},
            state={"x": 0},
        )

        self.assertEqual(report.verdict, Verdict.TRUE)
        self.assertEqual(
            _obligation_signature(report),
            (
                ("T-sigma", "state"),
                ("T-ODE-safety", "dl"),
                ("T-ODE-domain", "dl"),
                ("T-Out", "fol"),
                ("T-Out", "fol"),
            ),
        )
        self.assertIn("T-&", _step_rules(report))
        ode_roles = tuple(
            obligation.formula.role
            for obligation in report.obligations
            if obligation.kind == "dl" and obligation.active
        )
        self.assertEqual(ode_roles, ("safety", "domain"))


    def test_finite_ode_with_fallback_has_exact_boundary_formula_set(self) -> None:
        r"""Verify finite ODE with fallback has exact boundary formula set."""

        process = Sequence.of(
            ODE(
                [("x", 1)],
                "x < 1",
                annotation=ODEAnnotation(safety="x <= 1", delay=1),
            ),
            Skip(),
        )
        report = _construct_one(
            process,
            gamma={"x": BasicType.REAL, "ode_x": ContinuousType(("x",))},
            state={"x": 0},
            path="x == 0",
            dl_checker=_select_boundary_rule,
        )

        self.assertEqual(report.verdict, Verdict.TRUE)
        self.assertEqual(
            _obligation_signature(report),
            (
                ("T-sigma", "state"),
                ("T-ODE-safety", "dl"),
                ("T-ODE-boundary", "dl"),
            ),
        )
        ode_roles = tuple(
            obligation.formula.role
            for obligation in report.obligations
            if obligation.kind == "dl" and obligation.active
        )
        self.assertEqual(
            ode_roles,
            ("safety", "boundary"),
        )
        boundary_source = next(
            item.formula.source
            for item in report.obligations
            if item.active and item.rule == "T-ODE-boundary"
        )
        # The prover may reverse comparison operands; retain both the strict-domain and
        # equality-boundary parts.
        self.assertIn("1 >", boundary_source)
        self.assertIn("1 =", boundary_source)
        self.assertIn("-> !(", boundary_source)


    def test_recursion_configuration_and_parallel_formula_sets(self) -> None:
        r"""Verify recursion configuration and parallel formula sets."""

        recursive = Mu(
            "X",
            Sequence.of(InputChannel("tick", "u"), Var("X")),
        )
        recursion_report = _construct_one(
            recursive,
            theta={"tick": ChannelType(BasicType.INT)},
        )
        self.assertEqual(recursion_report.verdict, Verdict.TRUE)
        self.assertEqual(
            _obligation_signature(recursion_report),
            (
                ("T-sigma", "state"),
                ("T-mu", "fol"),
                ("T-X", "fol"),
            ),
        )
        recursion_steps = _step_rules(recursion_report)
        self.assertIn("T-mu", recursion_steps)
        self.assertIn("T-X", recursion_steps)

        constructor = TypeConstructor(dl_checker=_approve_dl)
        parallel_report = constructor.construct(
            TypeConstructionRequest(
                gamma={"left": BasicType.INT, "right": BasicType.INT},
                theta={},
                configurations=(
                    Configuration(
                        {"left": 0},
                        Skip(),
                        path_condition="left == 0",
                        name="left",
                    ),
                    Configuration(
                        {"right": 1},
                        Skip(),
                        path_condition="right == 1",
                        name="right",
                    ),
                ),
            )
        )
        self.assertEqual(parallel_report.verdict, Verdict.TRUE)
        self.assertEqual(
            _obligation_signature(parallel_report),
            (("T-sigma", "state"), ("T-sigma", "state")),
        )
        self.assertEqual(_step_rules(parallel_report).count("T-||"), 1)


if __name__ == "__main__":
    unittest.main()
