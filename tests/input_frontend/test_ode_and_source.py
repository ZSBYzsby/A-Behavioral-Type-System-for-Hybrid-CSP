r"""Regression tests for ODE and source. Paper reference: Section 2.1, Section 4.3, Assumption
2.1.
"""

from __future__ import annotations

from fractions import Fraction
from math import inf
import unittest

from hcsp_typechecker._internal import (
    Assign,
    CompareExpr,
    EmptyEvent,
    EventChoice,
    HCSPInputError,
    InputChannel,
    Literal,
    ODE,
    ODEAnnotation,
    OutputChannel,
    Parallel,
    Skip,
    UnaryExpr,
    Variable,
    parse_hcsp,
)


class ODEInputTests(unittest.TestCase):
    r"""Tests for ODE Input."""


    def test_minimal_ode_applies_optional_defaults(self) -> None:
        r"""Verify minimal ODE applies optional defaults."""

        source = (
            "{{ode(flow(dot x = v, dot v = -x), "
            "domain(t <= 1), delay(1)); skip}}"
        )
        expected = ODE(
            (
                ("x", Variable("v")),
                ("v", UnaryExpr("-", Variable("x"))),
            ),
            CompareExpr((Variable("t"), Literal(1)), ("<=",)),
            EmptyEvent(),
            annotation=ODEAnnotation(safety=True, delay=1),
            continuation=Skip(),
        )
        self.assertEqual(parse_hcsp(source), expected)


    def test_full_ode_with_safety_and_interrupts(self) -> None:
        r"""Verify full ODE with safety and interrupts."""

        source = """{{
            ode(
                flow(dot x = v),
                domain(t <= 1),
                safety(x <= 2),
                delay(1 / 2),
                interrupt(
                    on reset?(new_x) {x := new_x},
                    on report!(x) {skip}
                )
            );
            skip
        }}"""
        interrupts = EventChoice.of(
            (InputChannel("reset", "new_x"), Assign("x", "new_x")),
            (OutputChannel("report", "x"), Skip()),
        )
        expected = ODE(
            (("x", Variable("v")),),
            CompareExpr((Variable("t"), Literal(1)), ("<=",)),
            interrupts,
            annotation=ODEAnnotation(
                safety=CompareExpr((Variable("x"), Literal(2)), ("<=",)),
                delay=Fraction(1, 2),
            ),
            continuation=Skip(),
        )
        self.assertEqual(parse_hcsp(source), expected)


    def test_empty_flow_and_delay_forms(self) -> None:
        r"""Verify empty flow and delay forms."""

        finite = parse_hcsp(
            "{{ode(flow(), domain(true), delay(1 / 2 + 1 / 4)); skip}}"
        )
        infinite = parse_hcsp(
            "{{ode(flow(), domain(true), delay(inf)); skip}}"
        )
        self.assertIsInstance(finite, ODE)
        self.assertIsInstance(infinite, ODE)
        assert isinstance(finite, ODE)
        assert isinstance(infinite, ODE)
        self.assertEqual(finite.eqs, ())
        self.assertEqual(
            finite.annotation.delay,
            Literal(Fraction(3, 4)),
        )
        self.assertEqual(infinite.annotation.delay, inf)


    def test_implicit_clock_is_fresh_and_scoped_to_continuous_formulas(self) -> None:
        r"""Verify implicit clock is fresh and scoped to continuous formulas."""

        source = (
            "{{ode(flow(dot x = t), domain(t <= 1), safety(t <= 1), "
            "delay(1)); skip}}"
        )
        first = parse_hcsp(source)
        second = parse_hcsp(source)
        self.assertIsInstance(first, ODE)
        self.assertIsInstance(second, ODE)
        assert isinstance(first, ODE)
        assert isinstance(second, ODE)
        self.assertEqual(first, second)
        self.assertIsNot(first.local_clock, second.local_clock)
        self.assertEqual(first.get_vars(), {"x"})

        event_source = (
            "{{ode(flow(dot x = 0), domain(t <= 1), delay(1), "
            "interrupt(on report!(0) {use!(t)})); skip}}"
        )
        event_ode = parse_hcsp(event_source)
        self.assertIsInstance(event_ode, ODE)
        assert isinstance(event_ode, ODE)
        self.assertEqual(event_ode.get_vars(), {"x", "t"})


    def test_malformed_ode_structure_is_rejected(self) -> None:
        r"""Verify malformed ODE structure is rejected."""

        cases = (
            (
                "{{ode(flow(), domain(true), delay(1))}}",
                "validation",
            ),
            ("{{ode(domain(true), delay(1))}}", "syntax"),
            ("{{ode(flow(), delay(1))}}", "syntax"),
            ("{{ode(flow(), domain(true))}}", "syntax"),
            (
                "{{ode(flow(), domain(true), delay(1), safety(true))}}",
                "syntax",
            ),
            (
                "{{ode(flow(), domain(true), delay(1), interrupt())}}",
                "syntax",
            ),
            (
                "{{ode(flow(dot x = 0, dot x = 1), domain(true), delay(1))}}",
                "validation",
            ),
            (
                "{{ode(flow(dot t = 1), domain(true), delay(1))}}",
                "validation",
            ),
        )
        for source, phase in cases:
            with self.subTest(source=source):
                with self.assertRaises(HCSPInputError) as context:
                    parse_hcsp(source)
                self.assertEqual(context.exception.phase, phase)


    def test_invalid_delay_and_wait_durations_are_rejected(self) -> None:
        r"""Verify invalid delay and wait durations are rejected."""

        invalid = (
            "{{ode(flow(), domain(true), delay(-1))}}",
            "{{ode(flow(), domain(true), delay(d))}}",
            "{{ode(flow(), domain(true), delay(true))}}",
            "{{ode(flow(), domain(true), delay(1 % 2))}}",
            "{{ode(flow(), domain(true), delay(1 / 0))}}",
            "{{ode(flow(), domain(true), delay(4 ** (1 / 2)))}}",
        )
        for source in invalid:
            with self.subTest(source=source):
                with self.assertRaises(HCSPInputError):
                    parse_hcsp(source)


class SourceAndParallelInputTests(unittest.TestCase):
    r"""Tests for Source And Parallel Input."""


    def test_single_source_block_returns_process_directly(self) -> None:
        r"""Verify single source block returns process directly."""

        process = parse_hcsp("{{skip}}")
        self.assertEqual(process, Skip())
        self.assertNotIsInstance(process, Parallel)


    def test_multiple_source_blocks_build_ordered_parallel(self) -> None:
        r"""Verify multiple source blocks build ordered parallel."""

        source = "{{left!(0)}, {middle!(0)}, {right?(x)}}"
        expected = Parallel.of(
            OutputChannel("left", 0),
            OutputChannel("middle", 0),
            InputChannel("right", "x"),
        )
        self.assertEqual(parse_hcsp(source), expected)


    def test_duplicate_blocks_and_complementary_channels_are_preserved(self) -> None:
        r"""Verify duplicate blocks and complementary channels are preserved."""

        self.assertEqual(parse_hcsp("{{skip}, {skip}}"), Parallel(Skip(), Skip()))
        self.assertEqual(
            parse_hcsp("{{ch!(0)}, {ch?(x)}}"),
            Parallel(OutputChannel("ch", 0), InputChannel("ch", "x")),
        )


    def test_parallel_resource_conflicts_are_validation_errors(self) -> None:
        r"""Verify parallel resource conflicts are validation errors."""

        invalid = (
            "{{left!(x)}, {right!(x)}}",
            "{{ch?(x)}, {ch?(y)}}",
            "{{ch!(0)}, {ch!(1)}}",
        )
        for source in invalid:
            with self.subTest(source=source):
                with self.assertRaises(HCSPInputError) as context:
                    parse_hcsp(source)
                self.assertEqual(context.exception.phase, "validation")


if __name__ == "__main__":
    unittest.main()
