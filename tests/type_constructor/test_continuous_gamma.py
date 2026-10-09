r"""Regression tests for continuous Gamma. Paper reference: Definition 4.1, Table 2."""

from __future__ import annotations

from math import inf
import unittest

from hcsp_typechecker._internal import (
    Assert,
    Assign,
    BasicType,
    ChannelType,
    Configuration,
    ContinuousType,
    DLFormula,
    EmptyType,
    EventChoice,
    InfiniteDelayType,
    InputChannel,
    ODE,
    ODEAnnotation,
    OutputChannel,
    OutputType,
    Sequence,
    Skip,
    Verdict,
    construct_type,
)


def _approve_dl(_obligation: object) -> Verdict:
    r"""Approve dL goals with a mock backend to isolate rule structure."""

    return Verdict.TRUE


def _select_communication_only(obligation: object) -> Verdict:
    r"""Approve the domain candidate and reject the timeout candidate."""

    role = getattr(getattr(obligation, "formula", None), "role", "")
    return Verdict.FALSE if role == "boundary" else Verdict.TRUE


def _single_ode_gamma(name: str = "x") -> dict[str, BasicType | ContinuousType]:
    r"""Declare one Real scalar and its singleton ODE vector."""

    return {
        name: BasicType.REAL,
        f"ode_{name}": ContinuousType((name,)),
    }


def _with_explicit_skip(ode: ODE) -> ODE:
    r"""Add the explicit skip required for an ODE without a real tail."""

    result = Sequence.of(ode, Skip())
    assert isinstance(result, ODE)
    return result


class ContinuousGammaTests(unittest.TestCase):
    r"""Tests for Continuous Gamma."""


    def test_explicit_continuous_vector_accepts_ordinary_real_parameter(self) -> None:
        r"""Verify explicit continuous vector accepts ordinary Real parameter."""

        process = _with_explicit_skip(ODE(
            [("x", "v"), ("v", "-x * gain")],
            "x * x + v * v <= 4",
            annotation=ODEAnnotation(
                safety="x * x + v * v <= 4",
                delay=inf,
            ),
        ))
        oscillator = ContinuousType(variables=("x", "v"))
        report = construct_type(
            gamma={
                "x": BasicType.REAL,
                "v": BasicType.REAL,
                "gain": BasicType.REAL,
                "oscillator": oscillator,
            },
            theta={},
            configurations=[
                Configuration({"x": 0, "v": 1, "gain": 1}, process)
            ],
            path_condition="x == 0 and v == 1 and gain == 1",
            dl_checker=_approve_dl,
        )

        self.assertEqual(report.verdict, Verdict.TRUE)
        self.assertIsNotNone(report.constructed_type)
        ode_step = next(item for item in report.steps if item.rule == "T-ODE")
        self.assertIn(("x", "Real"), ode_step.gamma)
        self.assertIn(("v", "Real"), ode_step.gamma)
        self.assertIn(("oscillator", "R>=0 ~> R^2 on (v, x)"), ode_step.gamma)
        self.assertIn(("gain", "Real"), ode_step.gamma)


    def test_ode_annotation_is_the_only_dl_safety_goal(self) -> None:
        r"""Verify ODE annotation is the only dL safety goal."""

        captured: list[object] = []

        def collect_and_approve(obligation: object) -> Verdict:
            r"""Collect dL formulas with a mock successful proof verdict."""

            captured.append(obligation)
            return _select_communication_only(obligation)

        report = construct_type(
            gamma=_single_ode_gamma(),
            theta={},
            configurations=[
                Configuration(
                    {"x": 0},
                    _with_explicit_skip(ODE(
                        [("x", 0)],
                        True,
                        annotation=ODEAnnotation(safety="x <= 10", delay=1),
                    )),
                )
            ],
            path_condition="x == 0",
            dl_checker=collect_and_approve,
        )

        safety_obligation = next(
            item for item in report.obligations if item.rule == "T-ODE-safety"
        )
        self.assertEqual(report.verdict, Verdict.TRUE)
        self.assertIsInstance(safety_obligation.formula, DLFormula)
        program, post = safety_obligation.formula.source.split("}]", 1)
        self.assertIn("[{", program)
        self.assertRegex(post, r"10 >= kxv\d+")
        self.assertTrue(captured)


    def test_exact_declared_ode_vector_is_accepted(self) -> None:
        r"""Verify exact declared ODE vector is accepted."""

        trajectory = ContinuousType(variables=("x", "y"))
        report = construct_type(
            gamma={
                "x": BasicType.REAL,
                "y": BasicType.REAL,
                "xy_ode": trajectory,
            },
            theta={},
            configurations=[
                Configuration(
                    {"x": 0, "y": 0},
                    _with_explicit_skip(ODE(
                        [("y", 0), ("x", 0)],
                        True,
                        annotation=ODEAnnotation(safety="x + y >= 123", delay=1),
                    )),
                )
            ],
            dl_checker=_select_communication_only,
        )

        safety = next(
            item for item in report.obligations if item.rule == "T-ODE-safety"
        )
        self.assertEqual(report.verdict, Verdict.TRUE)
        self.assertIsNotNone(report.constructed_type)
        self.assertIsInstance(safety.formula, DLFormula)
        self.assertIn("123", safety.formula.source)


    def test_nonmatching_ode_vectors_are_rejected(self) -> None:
        r"""Verify nonmatching ODE vectors are rejected."""

        trajectory = ContinuousType(variables=("x", "y"))
        base_gamma = {
            "x": BasicType.REAL,
            "y": BasicType.REAL,
            "xy_ode": trajectory,
        }
        cases = (
            ("subset", [("x", 0)], base_gamma),
            (
                "superset",
                [("x", 0), ("y", 0), ("z", 0)],
                {**base_gamma, "z": BasicType.REAL},
            ),
        )
        for label, equations, gamma in cases:
            with self.subTest(label=label):
                state = {
                    name: 0
                    for name, declaration in gamma.items()
                    if isinstance(declaration, BasicType)
                }
                report = construct_type(
                    gamma=gamma,
                    theta={},
                    configurations=[
                        Configuration(
                            state,
                            _with_explicit_skip(ODE(
                                equations,
                                True,
                                annotation=ODEAnnotation(safety=True, delay=1),
                            )),
                        )
                    ],
                    dl_checker=_approve_dl,
                )
                self.assertEqual(report.verdict, Verdict.FALSE)
                self.assertIsNone(report.constructed_type)
                self.assertFalse(
                    any(item.rule.startswith("T-ODE-") for item in report.obligations)
                )
                self.assertTrue(
                    any(
                        "not declared by any ContinuousType" in item.message
                        for item in report.diagnostics
                    ),
                    report.diagnostics,
                )


    def test_implicit_clock_is_excluded_from_vector_match(self) -> None:
        r"""Verify implicit clock is excluded from vector match."""

        trajectory = ContinuousType(variables=("x",))
        report = construct_type(
            gamma={"x": BasicType.REAL, "x_ode": trajectory},
            theta={},
            configurations=[
                Configuration(
                    {"x": 0},
                    _with_explicit_skip(ODE(
                        [("x", 0)],
                        True,
                        annotation=ODEAnnotation(safety="t >= 0", delay=1),
                    )),
                )
            ],
            dl_checker=_select_communication_only,
        )

        self.assertEqual(report.verdict, Verdict.TRUE)
        self.assertIsNotNone(report.constructed_type)
        self.assertFalse(
            any("complete vector" in item.message for item in report.diagnostics)
        )


    def test_explicit_vector_registration_must_be_complete_and_consistent(self) -> None:
        r"""Verify explicit vector registration must be complete and consistent."""

        trajectory = ContinuousType(variables=("x", "y"))
        cases = (
            (
                {"x": BasicType.REAL, "xy_ode": trajectory},
                "missing Gamma scalar",
            ),
            (
                {
                    "x": BasicType.REAL,
                    "y": BasicType.INT,
                    "xy_ode": trajectory,
                },
                "to have BasicType.REAL",
            ),
        )
        for gamma, message in cases:
            with self.subTest(message=message):
                report = construct_type(
                    gamma=gamma,
                    theta={},
                    configurations=[Configuration({}, Skip())],
                )
                self.assertEqual(report.verdict, Verdict.FALSE)
                self.assertIsNone(report.constructed_type)
                self.assertTrue(
                    any(message in item.message for item in report.diagnostics),
                    report.diagnostics,
                )


    def test_ode_safety_must_be_boolean(self) -> None:
        r"""Verify ODE safety must be boolean."""

        calls: list[object] = []

        def unexpected_backend(obligation: object) -> Verdict:
            r"""Record unexpected prover calls after static validation failure."""

            calls.append(obligation)
            return Verdict.TRUE

        report = construct_type(
            gamma=_single_ode_gamma(),
            theta={},
            configurations=[
                Configuration(
                    {"x": 0},
                    _with_explicit_skip(ODE(
                        [("x", 0)],
                        True,
                        annotation=ODEAnnotation(safety="x + 1", delay=1),
                    )),
                )
            ],
            path_condition="x == 0",
            dl_checker=unexpected_backend,
        )

        self.assertEqual(report.verdict, Verdict.FALSE)
        self.assertIsNone(report.constructed_type)
        self.assertEqual(calls, [])
        self.assertTrue(
            any("Bool" in item.message for item in report.diagnostics),
            report.diagnostics,
        )


    def test_ode_safety_is_available_at_interrupt(self) -> None:
        r"""Verify ODE safety is available at interrupt."""

        process = _with_explicit_skip(ODE(
            [("x", 0)],
            True,
            EventChoice.of(
                (OutputChannel("tick", 0), Assert("x >= 0")),
            ),
            annotation=ODEAnnotation(safety="x >= 0", delay=inf),
        ))
        report = construct_type(
            gamma=_single_ode_gamma(),
            theta={"tick": ChannelType(BasicType.INT)},
            configurations=[Configuration({"x": 0}, process)],
            path_condition="x == 0",
            dl_checker=_approve_dl,
        )

        self.assertEqual(report.verdict, Verdict.TRUE)
        self.assertEqual(
            report.constructed_type,
            InfiniteDelayType(OutputType("tick", EmptyType())),
        )
        assert_obligation = next(
            item for item in report.obligations if item.rule == "T-Assert"
        )
        self.assertEqual(assert_obligation.verdict, Verdict.TRUE)


    def test_real_ode_lvalue_requires_vector_declaration(self) -> None:
        r"""Verify Real ODE lvalue requires vector declaration."""

        calls: list[object] = []

        def backend(obligation: object) -> Verdict:
            r"""Collect dL proof calls for the current test."""

            calls.append(obligation)
            return Verdict.TRUE

        report = construct_type(
            gamma={"x": BasicType.REAL},
            theta={},
            configurations=[
                Configuration(
                    {"x": 0},
                    _with_explicit_skip(ODE(
                        [("x", 1)],
                        True,
                        annotation=ODEAnnotation(delay=inf),
                    )),
                )
            ],
            dl_checker=backend,
        )

        self.assertEqual(report.verdict, Verdict.FALSE)
        self.assertIsNone(report.constructed_type)
        self.assertEqual(calls, [])
        self.assertFalse(
            any(item.rule.startswith("T-ODE-") for item in report.obligations)
        )
        self.assertTrue(
            any("not declared by any ContinuousType" in item.message for item in report.diagnostics)
        )


    def test_assignment_preserves_continuous_declaration(self) -> None:
        r"""Verify assignment preserves continuous declaration."""

        process = Sequence.of(
            Assign("x", 0),
            ODE(
                [("x", 1)],
                True,
                annotation=ODEAnnotation(delay=inf),
            ),
            Skip(),
        )
        report = construct_type(
            gamma=_single_ode_gamma(),
            theta={},
            configurations=[Configuration({"x": 2}, process)],
            dl_checker=_approve_dl,
        )

        self.assertEqual(report.verdict, Verdict.TRUE)
        self.assertIsNotNone(report.constructed_type)
        self.assertTrue(any(item.rule == "T-Assign" for item in report.steps))
        ode_step = next(item for item in report.steps if item.rule == "T-ODE")
        self.assertIn(("x", "Real"), ode_step.gamma)
        self.assertIn(("ode_x", "R>=0 ~> Real on (x)"), ode_step.gamma)


    def test_input_preserves_continuous_declaration(self) -> None:
        r"""Verify input preserves continuous declaration."""

        process = Sequence.of(
            InputChannel("reset", "x"),
            ODE(
                [("x", 1)],
                True,
                annotation=ODEAnnotation(delay=inf),
            ),
            Skip(),
        )
        report = construct_type(
            gamma=_single_ode_gamma(),
            theta={"reset": ChannelType(BasicType.REAL)},
            configurations=[Configuration({}, process)],
            dl_checker=_approve_dl,
        )

        self.assertEqual(report.verdict, Verdict.TRUE)
        self.assertIsNotNone(report.constructed_type)
        self.assertTrue(any(item.rule == "T-In" for item in report.steps))
        ode_step = next(item for item in report.steps if item.rule == "T-ODE")
        self.assertIn(("x", "Real"), ode_step.gamma)
        self.assertIn(("ode_x", "R>=0 ~> Real on (x)"), ode_step.gamma)


    def test_real_variable_needs_no_vector_outside_ode(self) -> None:
        r"""Verify Real variable needs no vector outside ODE."""

        report = construct_type(
            gamma={"x": BasicType.REAL},
            theta={"sample": ChannelType(BasicType.REAL)},
            configurations=[Configuration({"x": 1}, OutputChannel("sample", "x"))],
            path_condition="x == 1",
        )

        self.assertEqual(report.verdict, Verdict.TRUE)
        self.assertEqual(
            report.constructed_type,
            InfiniteDelayType(OutputType("sample", EmptyType())),
        )


    def test_ode_vector_declaration_name_has_no_scalar_value(self) -> None:
        r"""Verify ODE vector declaration name has no scalar value."""

        gamma = _single_ode_gamma()
        cases = (
            (
                "state",
                {},
                Configuration({"ode_x": 0}, Skip()),
                "not declared in Gamma",
            ),
            (
                "assignment",
                {},
                Configuration({}, Assign("ode_x", 0)),
                "names an ODE vector declaration",
            ),
            (
                "input",
                {"reset": ChannelType(BasicType.REAL)},
                Configuration({}, InputChannel("reset", "ode_x")),
                "names an ODE vector declaration",
            ),
            (
                "expression",
                {"sample": ChannelType(BasicType.REAL)},
                Configuration({}, OutputChannel("sample", "ode_x")),
                "Unbound variable",
            ),
        )
        for name, theta, configuration, message in cases:
            with self.subTest(name=name):
                report = construct_type(
                    gamma=gamma,
                    theta=theta,
                    configurations=[configuration],
                )
                self.assertEqual(report.verdict, Verdict.FALSE)
                self.assertIsNone(report.constructed_type)
                self.assertTrue(
                    any(message in item.message for item in report.diagnostics),
                    report.diagnostics,
                )


    def test_parallel_real_values_are_not_grouped_without_ode(self) -> None:
        r"""Verify parallel Real values are not grouped without ODE."""

        report = construct_type(
            gamma={"x": BasicType.REAL, "y": BasicType.REAL},
            theta={
                "left": ChannelType(BasicType.REAL),
                "right": ChannelType(BasicType.REAL),
            },
            configurations=[
                Configuration({"x": 0}, OutputChannel("left", "x")),
                Configuration({"y": 0}, OutputChannel("right", "y")),
            ],
        )

        self.assertEqual(report.verdict, Verdict.TRUE)
        self.assertIsNotNone(report.constructed_type)


    def test_shared_gamma_may_contain_unused_ode_vector_declaration(self) -> None:
        r"""Verify shared Gamma may contain unused ODE vector declaration."""

        report = construct_type(
            gamma=_single_ode_gamma(),
            theta={},
            configurations=[
                Configuration(
                    {"x": 0},
                    Skip(),
                )
            ],
        )

        self.assertEqual(report.verdict, Verdict.TRUE)
        self.assertIsNotNone(report.constructed_type)


if __name__ == "__main__":
    unittest.main()
