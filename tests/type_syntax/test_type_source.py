r"""Regression tests for type source. Paper reference: Section 4.1, Section 4.2, Table 2."""

from __future__ import annotations

import unittest
from fractions import Fraction
from textwrap import dedent

from hcsp_typechecker.frontend.errors import (
    HCSPInputError,
)
from hcsp_typechecker.frontend.type_syntax import (
    format_type_source,
    parse_type_source,
)
from hcsp_typechecker.data_structures.type_ast import (
    BottomType,
    EmptyType,
    ExternalChoiceType,
    FiniteDelayType,
    InfiniteDelayType,
    InputType,
    InternalChoiceType,
    MuType,
    NoInterruptType,
    OutputType,
    ParallelType,
    TypeVar,
)


class TypeSourceRoundTripTests(unittest.TestCase):
    r"""Tests for Type Source Round Trip."""


    def test_format_then_parse_preserves_complete_type_ast(self) -> None:
        r"""Verify format then parse preserves complete type AST."""

        value = ParallelType(
            (
                FiniteDelayType(
                    Fraction(3, 2),
                    ExternalChoiceType(
                        (
                            InputType("reset", EmptyType()),
                            OutputType("alarm", BottomType()),
                        )
                    ),
                    InternalChoiceType(
                        (
                            EmptyType(),
                            InfiniteDelayType(OutputType("done", EmptyType())),
                        )
                    ),
                ),
                MuType(
                    "X",
                    InfiniteDelayType(InputType("tick", TypeVar("X"))),
                ),
            )
        )

        source = format_type_source(value)
        self.assertEqual(parse_type_source(source), value)
        self.assertEqual(
            source,
            dedent(
                """\
                type parallel {
                    delay(3/2) interrupt angelic {
                        reset? -> empty,
                        alarm! -> bottom
                    } then internal {
                        (empty),
                        (
                            forever interrupt angelic {
                                done! -> empty
                            }
                        )
                    },
                    mu X. forever interrupt angelic {
                        tick? -> X
                    }
                }"""
            ),
        )


    def test_empty_angelic_is_accepted_and_canonicalized_when_delayed(self) -> None:
        r"""Verify empty angelic is accepted and canonicalized when delayed."""

        finite = parse_type_source(
            "type delay(1) interrupt angelic {} then empty"
        )
        infinite = parse_type_source("type forever interrupt angelic {}")

        self.assertEqual(
            finite,
            FiniteDelayType(Fraction(1), NoInterruptType(), EmptyType()),
        )
        self.assertEqual(infinite, InfiniteDelayType(NoInterruptType()))
        self.assertEqual(format_type_source(finite), "type delay(1) then empty")
        self.assertEqual(format_type_source(infinite), "type forever")


    def test_multiple_angelic_and_internal_branches_remain_distinct(self) -> None:
        r"""Verify multiple angelic and internal branches remain distinct."""

        value = parse_type_source(
            "type delay(0) interrupt angelic {a? -> empty, b! -> empty} "
            "then internal {(empty), (forever)}"
        )

        self.assertEqual(
            value,
            FiniteDelayType(
                Fraction(0),
                ExternalChoiceType(
                    (InputType("a", EmptyType()), OutputType("b", EmptyType()))
                ),
                InternalChoiceType(
                    (EmptyType(), InfiniteDelayType(NoInterruptType()))
                ),
            ),
        )


    def test_parentheses_preserve_nested_internal_choice_blocks(self) -> None:
        r"""Verify parentheses preserve nested internal choice blocks."""

        source = "type internal {(internal {(empty), (forever)}), (bottom)}"
        value = parse_type_source(source)

        self.assertEqual(
            value,
            InternalChoiceType(
                (
                    InternalChoiceType(
                        (EmptyType(), InfiniteDelayType(NoInterruptType()))
                    ),
                    BottomType(),
                )
            ),
        )
        self.assertEqual(
            format_type_source(value),
            dedent(
                """\
                type internal {
                    (
                        internal {
                            (empty),
                            (forever)
                        }
                    ),
                    (bottom)
                }"""
            ),
        )


class TypeSourceDiagnosticsTests(unittest.TestCase):
    r"""Tests for Type Source Diagnostics."""


    def test_angelic_type_cannot_be_the_type_root(self) -> None:
        r"""Verify angelic type cannot be the type root."""

        with self.assertRaises(HCSPInputError) as caught:
            parse_type_source("type angelic {ch? -> empty}")


    def test_internal_choice_requires_parenthesized_branches(self) -> None:
        r"""Verify internal choice requires parenthesized branches."""

        with self.assertRaises(HCSPInputError) as caught:
            parse_type_source("type internal {empty, forever}")
        self.assertIn("must be parenthesized", str(caught.exception))
        self.assertEqual(caught.exception.phase, "syntax")


    def test_finite_delay_preserves_bottom_and_empty_continuations(self) -> None:
        r"""Verify finite delay preserves bottom and empty continuations."""

        bottom = parse_type_source("type delay(1) then bottom")
        empty = parse_type_source("type delay(1) then empty")
        self.assertEqual(
            bottom,
            FiniteDelayType(1, NoInterruptType(), BottomType()),
        )
        self.assertEqual(
            empty,
            FiniteDelayType(1, NoInterruptType(), EmptyType()),
        )
        self.assertNotEqual(bottom, empty)
        self.assertEqual(parse_type_source(format_type_source(bottom)), bottom)


    def test_syntax_errors_preserve_source_diagnostics(self) -> None:
        r"""Verify syntax errors preserve source diagnostics."""

        for source in (
            "type delay(1) empty",
            "type forever interrupt angelic {ch? -> empty,}",
        ):
            with self.subTest(source=source), self.assertRaises(HCSPInputError) as caught:
                parse_type_source(source, source_name="expected.type")
            self.assertEqual(caught.exception.source_name, "expected.type")
            self.assertEqual(caught.exception.phase, "syntax")
