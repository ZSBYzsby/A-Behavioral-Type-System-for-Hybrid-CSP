r"""Regression tests for derivation short circuit. Paper reference: Table 2."""

from __future__ import annotations

import unittest

from hcsp_typechecker._internal import (
    Assert,
    BasicType,
    ChannelType,
    Configuration,
    ContinuousType,
    EmptyType,
    If,
    InputChannel,
    InputType,
    InfiniteDelayType,
    NoInterruptType,
    ODE,
    ODEAnnotation,
    OutputChannel,
    FiniteDelayType,
    Sequence,
    Skip,
    Verdict,
    construct_type,
)


class DerivationShortCircuitTests(unittest.TestCase):
    r"""Tests for Derivation Short Circuit."""


    def test_false_formula_stops_before_sequential_successor(self) -> None:
        r"""Verify false formula stops before sequential successor."""

        report = construct_type(
            gamma={},
            theta={},
            configurations=[
                Configuration(
                    {},
                    Sequence.of(Assert(False), OutputChannel("missing", 0)),
                )
            ],
        )

        self.assertEqual(report.verdict, Verdict.FALSE)
        self.assertIsNone(report.constructed_type)
        self.assertEqual(
            tuple(item.rule for item in report.obligations),
            ("T-sigma", "T-Assert"),
        )
        self.assertFalse(any(item.rule == "T-Out" for item in report.steps))
        self.assertFalse(
            any("missing" in item.message for item in report.diagnostics)
        )


    def test_unknown_formula_is_recorded_while_ode_successor_is_constructed(self) -> None:
        r"""Verify unknown formula is recorded while ODE successor is constructed."""

        process = Sequence.of(
            ODE(
                [("x", 1)],
                "t < 1",
                annotation=ODEAnnotation(safety="x >= 0", delay=1),
            ),
            InputChannel("ch", "received"),
        )
        report = construct_type(
            gamma={"x": BasicType.REAL, "ode_x": ContinuousType(("x",))},
            theta={"ch": ChannelType(BasicType.INT)},
            configurations=[Configuration({"x": 0}, process)],
            dl_checker=lambda _obligation: None,
        )

        self.assertEqual(report.verdict, Verdict.UNKNOWN)
        self.assertEqual(
            report.constructed_type,
            FiniteDelayType(
                1,
                NoInterruptType(),
                InfiniteDelayType(InputType("ch", EmptyType())),
            ),
        )
        ode_obligations = tuple(
            item for item in report.obligations if item.rule.startswith("T-ODE")
        )
        self.assertEqual(
            tuple(item.rule for item in ode_obligations),
            ("T-ODE-safety", "T-ODE-boundary"),
        )
        self.assertTrue(
            all(item.verdict is Verdict.UNKNOWN for item in ode_obligations)
        )
        self.assertTrue(any(item.rule == "T-In" for item in report.steps))
        self.assertFalse(report.diagnostics)


    def test_failed_child_stops_later_sibling_premise(self) -> None:
        r"""Verify failed child stops later sibling premise."""

        report = construct_type(
            gamma={},
            theta={},
            configurations=[
                Configuration(
                    {},
                    If(True, Assert(False), InputChannel("missing", "x")),
                )
            ],
        )

        self.assertEqual(report.verdict, Verdict.FALSE)
        self.assertIsNone(report.constructed_type)
        self.assertFalse(any(item.rule == "T-In" for item in report.steps))
        self.assertFalse(
            any("missing" in item.message for item in report.diagnostics)
        )


    def test_parallel_report_keeps_only_completed_prefix(self) -> None:
        r"""Verify parallel report keeps only completed prefix."""

        report = construct_type(
            gamma={},
            theta={},
            configurations=[
                Configuration({}, Skip(), name="K1"),
                Configuration({}, Assert(False), name="K2"),
                Configuration({}, InputChannel("missing", "x"), name="K3"),
            ],
        )

        self.assertEqual(report.verdict, Verdict.FALSE)
        self.assertIsNone(report.constructed_type)
        self.assertEqual(report.constructed_component_types, (EmptyType(), None, None))
        self.assertFalse(any(item.location == "K3" for item in report.steps))
        self.assertFalse(
            any("missing" in item.message for item in report.diagnostics)
        )


if __name__ == "__main__":
    unittest.main()
