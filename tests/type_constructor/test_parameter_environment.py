r"""Regression tests for parameter environment."""

from __future__ import annotations

import unittest

from hcsp_typechecker._internal import (
    Assert,
    Assign,
    BasicType,
    ChannelType,
    Configuration,
    ContinuousType,
    DLCheckResult,
    ODE,
    ODEAnnotation,
    OutputChannel,
    InputChannel,
    ParallelType,
    ParameterEnvironment,
    Mu,
    Sequence,
    Skip,
    Var,
    Verdict,
    construct_type,
)


def _approve_dl(_obligation: object) -> DLCheckResult:
    r"""Approve dL goals with a mock backend to isolate rule structure."""

    return DLCheckResult(Verdict.TRUE, "approved by parameter-environment test")


class ParameterEnvironmentTests(unittest.TestCase):
    r"""Tests for Parameter Environment."""


    def test_constraint_is_a_background_assumption(self) -> None:
        r"""Verify constraint is a background assumption."""

        report = construct_type(
            gamma={},
            theta={},
            configurations=[Assert("limit >= 0")],
            parameters=ParameterEnvironment(
                {"limit": BasicType.REAL},
                "limit >= 0",
            ),
        )

        self.assertEqual(report.verdict, Verdict.TRUE, report.format_detailed())
        self.assertIsNotNone(report.constructed_type)
        self.assertIn("Parameters: limit:Real", report.format_detailed())
        self.assertIn('Parameter constraint', report.format_detailed())


    def test_initial_path_is_proved_for_every_admissible_assignment(self) -> None:
        r"""Verify initial path is proved for every admissible assignment."""

        report = construct_type(
            gamma={},
            theta={},
            configurations=[
                Configuration(
                    {},
                    Assert(True),
                    path_condition="limit > 0",
                )
            ],
            parameters=ParameterEnvironment(
                {"limit": BasicType.REAL},
                "limit >= 0",
            ),
        )

        self.assertEqual(report.verdict, Verdict.FALSE)
        self.assertIsNone(report.constructed_type)
        self.assertEqual(report.obligations[0].rule, "T-sigma")


    def test_unsatisfiable_parameter_constraint_is_rejected(self) -> None:
        r"""Verify unsatisfiable parameter constraint is rejected."""

        report = construct_type(
            gamma={},
            theta={},
            configurations=[Assert(True)],
            parameters=ParameterEnvironment(
                {"x": BasicType.REAL},
                "x > 0 and x < 0",
            ),
        )

        self.assertEqual(report.verdict, Verdict.FALSE)
        self.assertTrue(
            any("unsatisfiable" in item.message for item in report.diagnostics)
        )


    def test_parameters_are_shared_without_becoming_mutable_state(self) -> None:
        r"""Verify parameters are shared without becoming mutable state."""

        left = Sequence.of(Assert("limit >= 0"), OutputChannel("left", 0))
        right = Sequence.of(Assert("limit >= 0"), OutputChannel("right", 0))
        report = construct_type(
            gamma={},
            theta={
                "left": ChannelType(BasicType.INT),
                "right": ChannelType(BasicType.INT),
            },
            configurations=(
                Configuration({}, left, name="Left"),
                Configuration({}, right, name="Right"),
            ),
            parameters=ParameterEnvironment(
                {"limit": BasicType.REAL},
                "limit >= 0",
            ),
        )

        self.assertEqual(report.verdict, Verdict.TRUE, report.format_detailed())
        self.assertIsInstance(report.constructed_type, ParallelType)


    def test_parameters_cannot_be_modified_by_hcsp(self) -> None:
        r"""Verify parameters cannot be modified by HCSP."""

        parameter_environment = ParameterEnvironment(
            {"limit": BasicType.REAL},
            "limit >= 0",
        )
        cases = (
            (
                "assignment",
                Assign("limit", 1),
                {},
                {},
            ),
            (
                "input",
                InputChannel("set", "limit"),
                {},
                {"set": ChannelType(BasicType.REAL)},
            ),
            (
                "ode",
                Sequence.of(
                    ODE(
                        [("limit", 0)],
                        True,
                        annotation=ODEAnnotation(delay=1),
                    ),
                    Skip(),
                ),
                {},
                {},
            ),
        )
        for name, process, gamma, theta in cases:
            with self.subTest(name=name):
                report = construct_type(
                    gamma=gamma,
                    theta=theta,
                    configurations=[process],
                    parameters=parameter_environment,
                    dl_checker=_approve_dl,
                )
                self.assertEqual(report.verdict, Verdict.FALSE)
                self.assertTrue(
                    any("read-only parameter" in item.message for item in report.diagnostics),
                    report.format_detailed(),
                )

        initial_state_report = construct_type(
            gamma={},
            theta={},
            configurations=[Configuration({"limit": 1}, Assert(True))],
            parameters=parameter_environment,
        )
        self.assertEqual(initial_state_report.verdict, Verdict.FALSE)
        self.assertTrue(
            any(
                "Initial state cannot assign" in item.message
                for item in initial_state_report.diagnostics
            )
        )


    def test_parameter_constraint_reaches_dl_precondition(self) -> None:
        r"""Verify parameter constraint reaches dL precondition."""

        captured: list[object] = []

        def capture(obligation: object) -> DLCheckResult:
            r"""Collect the obligation before returning mock approval."""

            captured.append(obligation)
            role = getattr(getattr(obligation, "formula", None), "role", "")
            verdict = Verdict.FALSE if role == "boundary" else Verdict.TRUE
            return DLCheckResult(verdict, "captured")

        report = construct_type(
            gamma={
                "x": BasicType.REAL,
                "flow": ContinuousType(("x",)),
            },
            theta={},
            configurations=[
                Configuration(
                    {"x": 0},
                    Sequence.of(
                        ODE(
                            [("x", 1)],
                            True,
                            annotation=ODEAnnotation(
                                safety="x <= limit",
                                delay=1,
                            ),
                        ),
                        Skip(),
                    ),
                )
            ],
            parameters=ParameterEnvironment(
                {"limit": BasicType.REAL},
                "limit >= 1",
            ),
            dl_checker=capture,
        )

        self.assertEqual(report.verdict, Verdict.TRUE, report.format_detailed())
        self.assertTrue(captured)
        formula = captured[0].formula  # type: ignore[attr-defined]
        self.assertTrue(
            any(
                "limit" in source_name or "limit" in target_name
                for source_name, target_name in formula.symbol_map
            )
        )


    def test_parameter_constraint_persists_at_recursive_entry(self) -> None:
        r"""Verify parameter constraint persists at recursive entry."""

        process = Mu(
            "X",
            Sequence.of(
                Assert("limit >= 0"),
                OutputChannel("tick", 0),
                Var("X"),
            ),
        )
        report = construct_type(
            gamma={},
            theta={"tick": ChannelType(BasicType.INT)},
            configurations=[process],
            parameters=ParameterEnvironment(
                {"limit": BasicType.REAL},
                "limit >= 0",
            ),
        )

        self.assertEqual(report.verdict, Verdict.TRUE, report.format_detailed())


    def test_parameter_names_cannot_overlap_state_gamma(self) -> None:
        r"""Verify parameter names cannot overlap state Gamma."""

        report = construct_type(
            gamma={"x": BasicType.REAL},
            theta={},
            configurations=[Assert(True)],
            parameters=ParameterEnvironment({"x": BasicType.REAL}),
        )

        self.assertEqual(report.verdict, Verdict.FALSE)
        self.assertTrue(
            any("overlap" in item.message for item in report.diagnostics)
        )


    def test_parameter_names_must_be_ascii_ident_strings(self) -> None:
        r"""Verify parameter names must be ascii ident strings."""

        environments = (
            ParameterEnvironment({"\u03b1\u03b2": BasicType.REAL}),
            ParameterEnvironment({1: BasicType.REAL}),  # type: ignore[dict-item]
        )
        for parameters in environments:
            with self.subTest(parameters=parameters):
                report = construct_type(
                    gamma={},
                    theta={},
                    configurations=[Assert(True)],
                    parameters=parameters,
                )
                self.assertEqual(report.verdict, Verdict.FALSE)
                self.assertTrue(
                    any(
                        "Invalid parameter names" in item.message
                        for item in report.diagnostics
                    )
                )


if __name__ == "__main__":
    unittest.main()
