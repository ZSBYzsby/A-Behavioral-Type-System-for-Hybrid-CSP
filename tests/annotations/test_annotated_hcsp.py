r"""Regression tests for annotated HCSP. Paper reference: Section 4.2/4.3, Section 2.1, Table 2."""

from __future__ import annotations

from dataclasses import fields
from decimal import Decimal
from fractions import Fraction
import math
import unittest

from hcsp_typechecker._internal import (
    Assign,
    BasicType,
    BottomType,
    ChannelType,
    Configuration,
    ContinuousType,
    EmptyType,
    Expr,
    InputChannel,
    InfiniteDelayType,
    Literal,
    Mu,
    MuType,
    NoInterruptType,
    ODE,
    ODEAnnotation,
    ODELocalClock,
    OutputChannel,
    OutputType,
    FiniteDelayType,
    RecursionAnnotation,
    Sequence,
    Skip,
    TypeVar,
    Var,
    Verdict,
    construct_type,
    types_equivalent,
)


def _approve_dl(_obligation: object) -> Verdict:
    r"""Approve dL goals with a mock backend to isolate rule structure."""

    return Verdict.TRUE


def _select_communication_only(obligation: object) -> Verdict:
    r"""Approve the domain candidate and reject the timeout candidate."""

    role = getattr(getattr(obligation, "formula", None), "role", "")
    return Verdict.FALSE if role == "boundary" else Verdict.TRUE


class AnnotationAstTests(unittest.TestCase):
    r"""Tests for Annotation AST."""


    def test_ode_annotation_normalizes_safety_and_delay(self) -> None:
        r"""Verify ODE annotation normalizes safety and delay."""

        annotation = ODEAnnotation(safety="x <= limit", delay=2)
        self.assertIsInstance(annotation.safety, Expr)
        self.assertIsInstance(annotation.delay, Expr)
        self.assertEqual(annotation.delay, Literal(Fraction(2)))
        self.assertEqual(annotation.get_vars(), {"x", "limit"})


    def test_omitted_safety_means_true(self) -> None:
        r"""Verify omitted safety means true."""

        annotation = ODEAnnotation(delay=1)
        self.assertEqual(annotation.safety, Literal(True))


    def test_delay_and_ode_annotation_are_both_required(self) -> None:
        r"""Verify delay and ODE annotation are both required."""

        with self.assertRaisesRegex(ValueError, "explicit delay"):
            ODEAnnotation()
        with self.assertRaisesRegex(ValueError, "Every ODE requires"):
            ODE([("x", 1)], True)


    def test_finite_rational_forms_are_normalized_exactly(self) -> None:
        r"""Verify finite rational forms are normalized exactly."""

        examples = (
            (3, Fraction(3)),
            (0.5, Fraction(1, 2)),
            (Decimal("0.125"), Fraction(1, 8)),
            (Fraction(2, 3), Fraction(2, 3)),
            ("1 / 4 + 1 / 4", Fraction(1, 2)),
            ("2 ** -2", Fraction(1, 4)),
        )
        for source, expected in examples:
            with self.subTest(source=source):
                annotation = ODEAnnotation(delay=source)
                self.assertEqual(annotation.delay, Literal(expected))


    def test_positive_infinity_is_a_valid_delay(self) -> None:
        r"""Verify positive infinity is a valid delay."""

        for value in (math.inf, Decimal("Infinity")):
            with self.subTest(value=value):
                annotation = ODEAnnotation(delay=value)
                self.assertEqual(annotation.delay, math.inf)


    def test_invalid_delays_are_rejected_at_construction(self) -> None:
        r"""Verify invalid delays are rejected at construction."""

        invalid_values = (
            -1,
            "-1 / 2",
            "d",
            "sqrt(2)",
            True,
            math.nan,
            -math.inf,
            Decimal("NaN"),
            Decimal("-Infinity"),
            "1 / 0",
            "4 ** 0.5",
        )
        for value in invalid_values:
            with self.subTest(value=value):
                with self.assertRaises(ValueError):
                    ODEAnnotation(delay=value)


    def test_ode_and_mu_hold_dedicated_annotation_objects(self) -> None:
        r"""Verify ODE and mu hold dedicated annotation objects."""

        ode_annotation = ODEAnnotation(safety=True, delay=1)
        recursion_annotation = RecursionAnnotation("x >= 0")
        ode = ODE([("x", 1)], "x < 1", annotation=ode_annotation)
        recursion = Mu("X", Skip(), annotation=recursion_annotation)
        self.assertIs(ode.annotation, ode_annotation)
        self.assertIs(recursion.annotation, recursion_annotation)
        with self.assertRaises(TypeError):
            ODE([("x", 1)], True, annotation=recursion_annotation)  # type: ignore[arg-type]
        with self.assertRaises(TypeError):
            Mu("X", Skip(), annotation=ode_annotation)  # type: ignore[arg-type]


    def test_recursion_annotation_omission_means_true(self) -> None:
        r"""Verify recursion annotation omission means true."""

        recursion = Mu("X", Skip())
        self.assertEqual(recursion.annotation.invariant, Literal(True))


    def test_ode_has_one_annotation_storage_path(self) -> None:
        r"""Verify ODE has one annotation storage path."""

        self.assertEqual(
            tuple(field.name for field in fields(ODE)),
            (
                "eqs",
                "constraint",
                "interrupts",
                "annotation",
                "continuation",
                "local_clock",
            ),
        )
        clock_field = next(field for field in fields(ODE) if field.name == "local_clock")
        self.assertFalse(clock_field.init)
        self.assertFalse(clock_field.compare)


    def test_every_ode_owns_a_fresh_fixed_local_clock(self) -> None:
        r"""Verify every ODE owns a fresh fixed local clock."""

        first = ODE([], True, annotation=ODEAnnotation(delay=1))
        second = ODE([], True, annotation=ODEAnnotation(delay=2))

        self.assertIsInstance(first.local_clock, ODELocalClock)
        self.assertIsNot(first.local_clock, second.local_clock)
        self.assertNotEqual(first.local_clock, second.local_clock)
        self.assertEqual(first.local_clock.name, "t")
        self.assertEqual(first.local_clock.initial_value, Literal(Fraction(0)))
        self.assertEqual(first.local_clock.derivative, Literal(Fraction(1)))
        with self.assertRaises(TypeError):
            ODE(  # type: ignore[call-arg]
                [],
                True,
                annotation=ODEAnnotation(delay=1),
                local_clock=ODELocalClock(),
            )


class ODEAnnotationTypingTests(unittest.TestCase):
    r"""Tests for ODE Annotation Typing."""


    def test_true_safety_is_accepted_without_a_dl_backend(self) -> None:
        r"""Verify true safety is accepted without a dL backend."""

        process = Sequence.of(
            ODE(
                [("x", 0)],
                True,
                annotation=ODEAnnotation(safety=True, delay=math.inf),
            ),
            Skip(),
        )
        report = construct_type(
            gamma={"x": BasicType.REAL, "ode_x": ContinuousType(("x",))},
            theta={},
            configurations=[Configuration({"x": 0}, process)],
        )
        self.assertEqual(report.verdict, Verdict.TRUE)
        self.assertEqual(
            report.constructed_type,
            InfiniteDelayType(NoInterruptType()),
        )
        safety_obligations = [
            item for item in report.obligations if item.rule == "T-ODE-safety"
        ]
        self.assertEqual(len(safety_obligations), 1)
        self.assertEqual(safety_obligations[0].verdict, Verdict.TRUE)


    def test_delay_annotation_appears_in_the_constructed_type(self) -> None:
        r"""Verify delay annotation appears in the constructed type."""

        process = Sequence.of(
            ODE(
                [("x", 0)],
                True,
                annotation=ODEAnnotation(delay="1 / 2"),
            ),
            Skip(),
        )
        report = construct_type(
            gamma={"x": BasicType.REAL, "ode_x": ContinuousType(("x",))},
            theta={},
            configurations=[Configuration({"x": 0}, process)],
            dl_checker=_select_communication_only,
        )
        expected = FiniteDelayType(
            Fraction(1, 2), NoInterruptType(), BottomType()
        )
        self.assertEqual(report.verdict, Verdict.TRUE)
        self.assertTrue(types_equivalent(report.constructed_type, expected))
        self.assertIsInstance(report.constructed_type, FiniteDelayType)
        self.assertEqual(report.constructed_type.duration, Fraction(1, 2))
        self.assertIsInstance(report.constructed_type.continuation, BottomType)
        rules = {item.rule for item in report.obligations if item.active}
        self.assertIn("T-ODE-domain", rules)
        self.assertNotIn("T-ODE-boundary", rules)
        self.assertNotIn("T-ODE-delay", rules)


    def test_nontrivial_safety_generates_a_dl_obligation(self) -> None:
        r"""Verify nontrivial safety generates a dL obligation."""

        process = Sequence.of(
            ODE(
                [("x", 1)],
                "x <= 10",
                annotation=ODEAnnotation(safety="x <= 8", delay=2),
            ),
            Skip(),
        )
        report = construct_type(
            gamma={"x": BasicType.REAL, "ode_x": ContinuousType(("x",))},
            theta={},
            configurations=[Configuration({"x": 0}, process)],
            path_condition="x == 0",
            dl_checker=_select_communication_only,
        )
        self.assertEqual(report.verdict, Verdict.TRUE)
        rules = {item.rule for item in report.obligations if item.active}
        self.assertIn("T-ODE-safety", rules)
        self.assertIn("T-ODE-domain", rules)
        self.assertNotIn("T-ODE-boundary", rules)


    def test_outer_sequence_becomes_the_ode_fallback(self) -> None:
        r"""Verify outer sequence becomes the ODE fallback."""

        process = Sequence.of(
            ODE(
                [("x", 1)],
                "x < 1",
                annotation=ODEAnnotation(safety=True, delay=1),
            ),
            OutputChannel("done", 0),
        )
        report = construct_type(
            gamma={"x": BasicType.REAL, "ode_x": ContinuousType(("x",))},
            theta={"done": ChannelType(BasicType.INT)},
            configurations=[Configuration({"x": 0}, process)],
            path_condition="x == 0",
            dl_checker=_approve_dl,
        )
        expected = FiniteDelayType(
            1,
            NoInterruptType(),
            InfiniteDelayType(OutputType("done", EmptyType())),
        )
        self.assertEqual(report.verdict, Verdict.TRUE)
        self.assertTrue(types_equivalent(report.constructed_type, expected))


    def test_infinite_delay_discards_sequential_timeout_fallback(self) -> None:
        r"""Verify infinite delay discards sequential timeout fallback."""

        process = Sequence.of(
            ODE(
                [("x", 0)],
                True,
                annotation=ODEAnnotation(delay=math.inf),
            ),
            Skip(),
        )
        report = construct_type(
            gamma={"x": BasicType.REAL, "ode_x": ContinuousType(("x",))},
            theta={},
            configurations=[Configuration({"x": 0}, process)],
            dl_checker=_approve_dl,
        )
        self.assertEqual(report.verdict, Verdict.TRUE)
        self.assertEqual(
            report.constructed_type,
            InfiniteDelayType(NoInterruptType()),
        )
        self.assertFalse(
            any(item.rule == "T-ODE-boundary" for item in report.obligations)
        )


class RecursionAnnotationTypingTests(unittest.TestCase):
    r"""Tests for Recursion Annotation Typing."""


    def test_invariant_holds_at_entry_and_after_one_unfolding(self) -> None:
        r"""Verify invariant holds at entry and after one unfolding."""

        process = Mu(
            "X",
            Sequence.of(
                OutputChannel("tick", 0),
                Assign("x", "x + 1"),
                Var("X"),
            ),
            annotation=RecursionAnnotation("x >= 0"),
        )
        report = construct_type(
            gamma={"x": BasicType.INT},
            theta={"tick": ChannelType(BasicType.INT)},
            configurations=[Configuration({"x": 0}, process)],
            path_condition="x >= 0",
        )
        self.assertEqual(report.verdict, Verdict.TRUE)
        self.assertTrue(
            types_equivalent(
                report.constructed_type,
                MuType(
                    "T",
                    InfiniteDelayType(OutputType("tick", TypeVar("T"))),
                ),
            )
        )
        rules = {item.rule for item in report.obligations}
        self.assertIn("T-mu", rules)
        self.assertIn("T-X", rules)


    def test_invariant_violation_at_recursion_boundary_is_rejected(self) -> None:
        r"""Verify invariant violation at recursion boundary is rejected."""

        process = Mu(
            "X",
            Sequence.of(
                OutputChannel("tick", 0),
                Assign("x", -1),
                Var("X"),
            ),
            annotation=RecursionAnnotation("x >= 0"),
        )
        report = construct_type(
            gamma={"x": BasicType.INT},
            theta={"tick": ChannelType(BasicType.INT)},
            configurations=[Configuration({"x": 0}, process)],
            path_condition="x >= 0",
        )
        self.assertEqual(report.verdict, Verdict.FALSE)
        boundary = [item for item in report.obligations if item.rule == "T-X"]
        self.assertEqual(len(boundary), 1)
        self.assertEqual(boundary[0].verdict, Verdict.FALSE)


    def test_ode_and_recursion_annotations_work_together(self) -> None:
        r"""Verify ODE and recursion annotations work together."""

        process = Mu(
            "X",
            Sequence.of(
                ODE(
                    [("x", 0)],
                    "x < 1",
                    annotation=ODEAnnotation(safety="x <= 1", delay=1),
                ),
                OutputChannel("tick", 0),
                Var("X"),
            ),
            annotation=RecursionAnnotation("x <= 1"),
        )
        report = construct_type(
            gamma={"x": BasicType.REAL, "ode_x": ContinuousType(("x",))},
            theta={"tick": ChannelType(BasicType.INT)},
            configurations=[Configuration({"x": 0}, process)],
            path_condition="x <= 1",
            dl_checker=_approve_dl,
        )
        self.assertEqual(report.verdict, Verdict.TRUE)
        rules = {item.rule for item in report.obligations}
        self.assertTrue(
            {"T-mu", "T-X", "T-ODE-safety", "T-ODE-boundary"} <= rules
        )


if __name__ == "__main__":
    unittest.main()
