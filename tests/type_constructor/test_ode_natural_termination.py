r"""Regression tests for ODE natural termination. Paper reference: Table 2."""

from __future__ import annotations

import unittest
from typing import Any, Mapping

from hcsp_typechecker._internal import (
    Assert,
    BottomType,
    Configuration,
    EmptyType,
    FiniteDelayType,
    NoInterruptType,
    ODE,
    ODEAnnotation,
    Skip,
    TypeConstructionRequest,
    TypeConstructor,
    Verdict,
)


def _backend(
    answers: Mapping[str, Verdict],
    calls: list[str],
):
    r"""Return controlled verdicts by dL role and record invocation order."""

    def decide(obligation: Any) -> Verdict:
        r"""Read the dL role and reject any role without an explicit test verdict."""

        role = getattr(getattr(obligation, "formula", None), "role", "")
        calls.append(role)
        return answers.get(role, Verdict.TRUE)

    return decide


def _finite_ode(*, continuation: object | None = None) -> ODE:
    r"""Build finite evolution with nontrivial domain and boundary goals."""

    return ODE(
        (),
        "t < 1",
        annotation=ODEAnnotation(safety=True, delay=1),
        continuation=continuation,
    )


def _construct(process: object, answers: Mapping[str, Verdict], calls: list[str]):
    r"""Construct an ODE test type in empty environments."""

    return TypeConstructor(dl_checker=_backend(answers, calls)).construct(
        TypeConstructionRequest(
            gamma={},
            theta={},
            configurations=[Configuration({}, process)],
        )
    )


class FiniteODETerminationTests(unittest.TestCase):
    r"""Tests for Finite ODE Termination."""


    def test_ode_defaults_to_an_owned_skip_continuation(self) -> None:
        r"""Verify ODE defaults to an owned skip continuation."""

        ode = _finite_ode()
        self.assertIsInstance(ode.continuation, Skip)


    def test_skip_selects_communication_rule_when_only_domain_holds(self) -> None:
        r"""Verify skip selects communication rule when only domain holds."""

        calls: list[str] = []
        report = _construct(
            _finite_ode(continuation=Skip()),
            {"domain": Verdict.TRUE, "boundary": Verdict.FALSE},
            calls,
        )

        self.assertEqual(report.verdict, Verdict.TRUE)
        self.assertEqual(
            report.constructed_type,
            FiniteDelayType(1, NoInterruptType(), BottomType()),
        )
        self.assertEqual(calls, ["domain", "boundary"])
        active_rules = {
            item.rule for item in report.obligations if item.active
        }
        self.assertIn("T-ODE-domain", active_rules)
        self.assertNotIn("T-ODE-boundary", active_rules)


    def test_skip_selects_timeout_rule_when_only_boundary_holds(self) -> None:
        r"""Verify skip selects timeout rule when only boundary holds."""

        calls: list[str] = []
        report = _construct(
            _finite_ode(continuation=Skip()),
            {"domain": Verdict.FALSE, "boundary": Verdict.TRUE},
            calls,
        )

        self.assertEqual(report.verdict, Verdict.TRUE)
        self.assertEqual(
            report.constructed_type,
            FiniteDelayType(1, NoInterruptType(), EmptyType()),
        )
        self.assertEqual(calls, ["domain", "boundary"])
        active_rules = {
            item.rule for item in report.obligations if item.active
        }
        self.assertIn("T-ODE-boundary", active_rules)
        self.assertNotIn("T-ODE-domain", active_rules)


    def test_proved_candidate_dominates_inactive_unknown_candidate(self) -> None:
        r"""Verify proved candidate dominates inactive unknown candidate."""

        calls: list[str] = []
        report = _construct(
            _finite_ode(continuation=Skip()),
            {"domain": Verdict.TRUE, "boundary": Verdict.UNKNOWN},
            calls,
        )

        self.assertEqual(report.verdict, Verdict.TRUE)
        self.assertEqual(
            report.constructed_type,
            FiniteDelayType(1, NoInterruptType(), BottomType()),
        )
        self.assertEqual(calls, ["domain", "boundary"])
        boundary = next(
            item for item in report.obligations if item.rule == "T-ODE-boundary"
        )
        self.assertEqual(boundary.verdict, Verdict.UNKNOWN)
        self.assertFalse(boundary.active)


    def test_unknown_candidates_keep_an_untrusted_type(self) -> None:
        r"""Verify unknown candidates keep an untrusted type."""

        calls: list[str] = []
        report = _construct(
            _finite_ode(continuation=Skip()),
            {"domain": Verdict.UNKNOWN, "boundary": Verdict.UNKNOWN},
            calls,
        )

        self.assertEqual(report.verdict, Verdict.UNKNOWN)
        self.assertEqual(
            report.constructed_type,
            FiniteDelayType(1, NoInterruptType(), EmptyType()),
        )
        self.assertEqual(calls, ["domain", "boundary"])
        self.assertEqual(
            {item.candidate for item in report.obligations if item.candidate},
            {"communication-only", "natural-timeout"},
        )


    def test_non_skip_successor_uses_only_timeout_rule(self) -> None:
        r"""Verify non skip successor uses only timeout rule."""

        calls: list[str] = []
        report = _construct(
            _finite_ode(continuation=Assert(True)),
            {"boundary": Verdict.TRUE},
            calls,
        )

        self.assertEqual(report.verdict, Verdict.TRUE)
        self.assertEqual(calls, ["boundary"])
        self.assertNotIn("T-ODE-Select", {step.rule for step in report.steps})


if __name__ == "__main__":
    unittest.main()
