r"""Regression tests for statements and control. Paper reference: Section 2.1, Section 4.2/4.3,
Assumption 2.2.
"""

from __future__ import annotations

from fractions import Fraction
import unittest

from hcsp_typechecker._internal import (
    Assert,
    Assign,
    BinaryExpr,
    CompareExpr,
    HCSPInputError,
    If,
    InputChannel,
    InternalChoice,
    Literal,
    Mu,
    ODE,
    OutputChannel,
    RecursionAnnotation,
    Sequence,
    Skip,
    Var,
    Variable,
    parse_hcsp,
)


class AtomicStatementInputTests(unittest.TestCase):
    r"""Tests for Atomic Statement Input."""


    def test_skip_assignment_and_assertion(self) -> None:
        r"""Verify skip assignment and assertion."""

        self.assertEqual(parse_hcsp("{{skip}}"), Skip())
        self.assertEqual(
            parse_hcsp("{{x := y + 1}}"),
            Assign(
                "x",
                BinaryExpr("+", Variable("y"), Literal(1)),
            ),
        )
        self.assertEqual(
            parse_hcsp("{{assert(x >= 0)}}"),
            Assert(CompareExpr((Variable("x"), Literal(0)), (">=",))),
        )


    def test_single_and_multi_scalar_communications(self) -> None:
        r"""Verify single and multi scalar communications."""

        self.assertEqual(parse_hcsp("{{ch?(x)}}"), InputChannel("ch", "x"))
        self.assertEqual(
            parse_hcsp("{{ch?(x, y, z)}}"),
            InputChannel("ch", ("x", "y", "z")),
        )
        self.assertEqual(parse_hcsp("{{ch!(x)}}"), OutputChannel("ch", "x"))
        self.assertEqual(
            parse_hcsp("{{ch!(x, y + 1, 0)}}"),
            OutputChannel(
                "ch",
                (
                    Variable("x"),
                    BinaryExpr("+", Variable("y"), Literal(1)),
                    Literal(0),
                ),
            ),
        )


    def test_process_call_is_supported_and_wait_is_rejected(self) -> None:
        r"""Verify process call is supported and wait is rejected."""

        self.assertEqual(parse_hcsp("{{call Loop}}"), Var("Loop"))
        with self.assertRaises(HCSPInputError):
            parse_hcsp("{{wait(1 / 2)}}")


    def test_invalid_communication_arguments_are_rejected(self) -> None:
        r"""Verify invalid communication arguments are rejected."""

        invalid_sources = (
            "{{ch?()}}",
            "{{ch?(x, x)}}",
            "{{ch?(x + 1)}}",
            "{{ch!()}}",
            "{{ch!(x,)}}",
        )
        for source in invalid_sources:
            with self.subTest(source=source):
                with self.assertRaises(HCSPInputError):
                    parse_hcsp(source)


class StatementBlockInputTests(unittest.TestCase):
    r"""Tests for Statement Block Input."""


    def test_semicolon_builds_sequence_in_source_order(self) -> None:
        r"""Verify semicolon builds sequence in source order."""

        self.assertEqual(
            parse_hcsp("{{ch?(x); x := x + 1; out!(x)}}"),
            Sequence.of(
                InputChannel("ch", "x"),
                Assign("x", BinaryExpr("+", Variable("x"), Literal(1))),
                OutputChannel("out", "x"),
            ),
        )


    def test_empty_or_malformed_statement_blocks_are_rejected(self) -> None:
        r"""Verify empty or malformed statement blocks are rejected."""

        malformed = (
            "{{}}",
            "{{; skip}}",
            "{{skip;}}",
            "{{skip;; skip}}",
            "{{skip skip}}",
        )
        for source in malformed:
            with self.subTest(source=source):
                with self.assertRaises(HCSPInputError):
                    parse_hcsp(source)


class CompoundControlInputTests(unittest.TestCase):
    r"""Tests for Compound Control Input."""


    def test_if_statement_and_following_continuation(self) -> None:
        r"""Verify if statement and following continuation."""

        source = """{{
            if (x >= 0) {positive!(x)} else {negative!(x)};
            done!(x)
        }}"""
        expected = If(
            CompareExpr((Variable("x"), Literal(0)), (">=",)),
            OutputChannel("positive", "x"),
            OutputChannel("negative", "x"),
            continuation=OutputChannel("done", "x"),
        )
        self.assertEqual(parse_hcsp(source), expected)


    def test_choice_owns_its_common_continuation(self) -> None:
        r"""Verify choice owns its common continuation."""

        source = "{{choose {left!(0)} or {right!(0)}; done!(0)}}"
        self.assertEqual(
            parse_hcsp(source),
            InternalChoice(
                OutputChannel("left", 0),
                OutputChannel("right", 0),
                continuation=OutputChannel("done", 0),
            ),
        )


    def test_multi_branch_choice_preserves_branch_order_and_tail(self) -> None:
        r"""Verify multi branch choice preserves branch order and tail."""

        source = (
            "{{choose {a!(0)} or {b!(0)} or {c!(0)}; "
            "done!(0); skip}}"
        )
        self.assertEqual(
            parse_hcsp(source),
            InternalChoice.of(
                OutputChannel("a", 0),
                OutputChannel("b", 0),
                OutputChannel("c", 0),
                continuation=Sequence.of(OutputChannel("done", 0), Skip()),
            ),
        )


    def test_annotated_guarded_recursion(self) -> None:
        r"""Verify annotated guarded recursion."""

        source = "{{mu Loop invariant(x >= 0) {tick!(x); call Loop}}}"
        self.assertEqual(
            parse_hcsp(source),
            Mu(
                "Loop",
                Sequence.of(OutputChannel("tick", "x"), Var("Loop")),
                annotation=RecursionAnnotation(
                    CompareExpr((Variable("x"), Literal(0)), (">=",))
                ),
            ),
        )


    def test_malformed_control_and_unguarded_recursion_are_rejected(self) -> None:
        r"""Verify malformed control and unguarded recursion are rejected."""

        cases = (
            ("{{mu Loop {tick!(0)}}}", "syntax"),
            ("{{if (true) {skip}}}", "syntax"),
            ("{{choose {skip}}}", "syntax"),
            ("{{mu Loop invariant(true) {call Loop}}}", "validation"),
        )
        for source, phase in cases:
            with self.subTest(source=source):
                with self.assertRaises(HCSPInputError) as context:
                    parse_hcsp(source)
                self.assertEqual(context.exception.phase, phase)


if __name__ == "__main__":
    unittest.main()
