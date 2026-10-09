r"""Regression tests for ODE table2 contexts. Paper reference: Table 2."""

from __future__ import annotations

from math import inf
import unittest

from hcsp_typechecker._internal import (
    Assign,
    Assert,
    BasicType,
    ChannelType,
    Configuration,
    ContinuousType,
    EventChoice,
    InputChannel,
    ODE,
    ODEAnnotation,
    OutputChannel,
    ParameterEnvironment,
    Sequence,
    Skip,
    Verdict,
    construct_type,
)


def _approve_dl(_formula: object) -> Verdict:
    r"""Approve dL goals with a mock backend to isolate rule structure."""

    return Verdict.TRUE


def _assertion_verdict(report) -> Verdict:
    r"""Extract the unique T-Assert verdict from the report."""

    assertions = [
        obligation
        for obligation in report.obligations
        if obligation.rule == "T-Assert"
    ]
    if len(assertions) != 1:
        raise AssertionError(f"expected one T-Assert obligation, got {assertions!r}")
    return assertions[0].verdict


class ODETable2SuccessorContextTests(unittest.TestCase):
    r"""Tests for ODE Table2 Successor Context."""


    def test_communication_only_event_receives_domain_and_safety(self) -> None:
        r"""Verify communication only event receives domain and safety."""

        process = Sequence.of(
            ODE(
                [("x", 1)],
                "x < 1",
                EventChoice((OutputChannel("alarm", 0), Assert("x < 1"))),
                annotation=ODEAnnotation(safety=True, delay=inf),
            ),
            Skip(),
        )
        report = construct_type(
            gamma={"x": BasicType.REAL, "ode_x": ContinuousType(("x",))},
            theta={"alarm": ChannelType(BasicType.INT)},
            configurations=[Configuration({"x": 0}, process)],
            path_condition="x == 0",
            dl_checker=_approve_dl,
        )

        self.assertEqual(report.verdict, Verdict.TRUE)
        self.assertEqual(_assertion_verdict(report), Verdict.TRUE)


    def test_timed_event_does_not_receive_domain_assumption(self) -> None:
        r"""Verify timed event does not receive domain assumption."""

        evolution = ODE(
            [("x", 1)],
            "x < 1",
            EventChoice((OutputChannel("alarm", 0), Assert("x < 1"))),
            annotation=ODEAnnotation(safety=True, delay=1),
        )
        report = construct_type(
            gamma={"x": BasicType.REAL, "ode_x": ContinuousType(("x",))},
            theta={
                "alarm": ChannelType(BasicType.INT),
                "done": ChannelType(BasicType.INT),
            },
            configurations=[
                Configuration(
                    {"x": 0},
                    Sequence.of(evolution, OutputChannel("done", 0)),
                )
            ],
            path_condition="x == 0",
            dl_checker=_approve_dl,
        )

        self.assertEqual(report.verdict, Verdict.FALSE)
        self.assertEqual(_assertion_verdict(report), Verdict.FALSE)


    def test_timeout_continuation_receives_not_domain_and_safety(self) -> None:
        r"""Verify timeout continuation receives not domain and safety."""

        process = Sequence.of(
            ODE(
                [("x", 1)],
                "x < 1",
                annotation=ODEAnnotation(safety=True, delay=1),
            ),
            Assert("x >= 1"),
        )
        report = construct_type(
            gamma={"x": BasicType.REAL, "ode_x": ContinuousType(("x",))},
            theta={},
            configurations=[Configuration({"x": 0}, process)],
            path_condition="x == 0",
            dl_checker=_approve_dl,
        )

        self.assertEqual(report.verdict, Verdict.TRUE)
        self.assertEqual(_assertion_verdict(report), Verdict.TRUE)


    def test_ode_drops_precondition_about_unevolved_variable(self) -> None:
        r"""Verify ODE drops precondition about unevolved variable."""

        process = Sequence.of(
            InputChannel("set", ("x", "y")),
            ODE(
                [("x", 1)],
                "t < 1",
                annotation=ODEAnnotation(safety=True, delay=1),
            ),
            Assert("y > 0"),
        )
        report = construct_type(
            gamma={"x": BasicType.REAL, "ode_x": ContinuousType(("x",))},
            theta={
                "set": ChannelType(
                    (BasicType.REAL, BasicType.REAL),
                    "eta1 == 0 and eta2 > 0",
                )
            },
            configurations=[Configuration({}, process)],
            dl_checker=_approve_dl,
        )

        self.assertEqual(report.verdict, Verdict.FALSE, report.format_detailed())
        self.assertEqual(_assertion_verdict(report), Verdict.FALSE)


    def test_ode_discards_precondition_about_evolved_variable(self) -> None:
        r"""Verify ODE discards precondition about evolved variable."""

        process = Sequence.of(
            InputChannel("set", ("x", "y")),
            ODE(
                [("x", 1)],
                "t < 1",
                annotation=ODEAnnotation(safety=True, delay=1),
            ),
            Assert("x == 0"),
        )
        report = construct_type(
            gamma={"x": BasicType.REAL, "ode_x": ContinuousType(("x",))},
            theta={
                "set": ChannelType(
                    (BasicType.REAL, BasicType.REAL),
                    "eta1 == 0 and eta2 > 0",
                )
            },
            configurations=[Configuration({}, process)],
            dl_checker=_approve_dl,
        )

        self.assertEqual(report.verdict, Verdict.FALSE)
        self.assertEqual(_assertion_verdict(report), Verdict.FALSE)


    def test_ode_drops_aliased_unevolved_precondition(self) -> None:
        r"""Verify ODE drops aliased unevolved precondition."""

        process = Sequence.of(
            InputChannel("set", "y"),
            Assign("x", "y"),
            ODE(
                [("x", 1)],
                "t < 1",
                annotation=ODEAnnotation(safety=True, delay=1),
            ),
            Assert("y > 0"),
        )
        report = construct_type(
            gamma={
                "x": BasicType.REAL,
                "y": BasicType.REAL,
                "ode_x": ContinuousType(("x",)),
            },
            theta={
                "set": ChannelType(BasicType.REAL, "eta > 0")
            },
            configurations=[Configuration({}, process)],
            dl_checker=_approve_dl,
        )

        self.assertEqual(report.verdict, Verdict.FALSE, report.format_detailed())
        self.assertEqual(_assertion_verdict(report), Verdict.FALSE)


    def test_ode_keeps_gamma_domains_and_parameter_environment(self) -> None:
        r"""Verify ODE keeps Gamma domains and parameter environment."""

        process = Sequence.of(
            ODE(
                [("x", 1)],
                "t < 1",
                annotation=ODEAnnotation(safety=True, delay=1),
            ),
            Assert("count >= 0 and limit >= 0"),
        )
        report = construct_type(
            gamma={
                "x": BasicType.REAL,
                "count": BasicType.NAT,
                "ode_x": ContinuousType(("x",)),
            },
            theta={},
            parameters=ParameterEnvironment(
                {"limit": BasicType.REAL},
                "limit >= 0",
            ),
            configurations=[Configuration({"count": 0}, process)],
            dl_checker=_approve_dl,
        )

        self.assertEqual(report.verdict, Verdict.TRUE, report.format_detailed())
        self.assertEqual(_assertion_verdict(report), Verdict.TRUE)


if __name__ == "__main__":
    unittest.main()
