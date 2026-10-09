r"""Regression tests for type AST. Paper reference: Section 4.1/4.2, Section 4.1, Section 4.2."""

from __future__ import annotations

from decimal import Decimal
from fractions import Fraction
from math import inf, nan
import unittest

import hcsp_typechecker._internal as internal_api
import hcsp_typechecker.data_structures.type_ast as type_ast_api

from hcsp_typechecker._internal import (
    AngelicType,
    BehavioralType,
    BottomType,
    ConfigurationType,
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
    ProcessType,
    TypeVar,
    make_external_choice,
    make_delay_type,
    types_equivalent,
)


class AbstractTypeBaseTests(unittest.TestCase):
    r"""Tests for Abstract Type Base."""


    def test_empty_type_has_no_end_type_alias(self) -> None:
        r"""Verify empty type has no end type alias."""

        self.assertIs(type_ast_api.EmptyType, EmptyType)
        self.assertFalse(hasattr(type_ast_api, "EndType"))
        self.assertFalse(hasattr(internal_api, "EndType"))


    def test_abstract_type_categories_cannot_be_instantiated(self) -> None:
        r"""Verify abstract type categories cannot be instantiated."""

        for abstract_class in (
            BehavioralType,
            ConfigurationType,
            ProcessType,
            AngelicType,
        ):
            with self.subTest(abstract_class=abstract_class.__name__):
                with self.assertRaises(TypeError):
                    abstract_class()


class AngelicTypeNormalizationTests(unittest.TestCase):
    r"""Tests for Angelic Type Normalization."""


    def test_angelic_choice_has_one_shape_per_branch_count(self) -> None:
        r"""Verify angelic choice has one shape per branch count."""

        input_branch = InputType("in", EmptyType())
        output_branch = OutputType("out", EmptyType())
        self.assertIsInstance(make_external_choice(()), NoInterruptType)
        self.assertIs(make_external_choice((input_branch,)), input_branch)
        self.assertEqual(
            make_external_choice((input_branch, output_branch)),
            ExternalChoiceType((input_branch, output_branch)),
        )
        with self.assertRaises(ValueError):
            ExternalChoiceType(())
        with self.assertRaises(ValueError):
            ExternalChoiceType((input_branch,))
        with self.assertRaises(TypeError):
            ExternalChoiceType((input_branch, EmptyType()))  # type: ignore[arg-type]


    def test_communication_type_channels_are_identifiers(self) -> None:
        r"""Verify communication type channels are identifiers."""

        for name in ("channel", "channel_1", "_private", "Channel2"):
            with self.subTest(valid=name):
                self.assertEqual(InputType(name, EmptyType()).channel, name)
                self.assertEqual(OutputType(name, EmptyType()).channel, name)

        for name in (
            "",
            " ",
            " channel",
            "channel ",
            "1channel",
            "a-b",
            "a\nb",
            "\u03b3\u03b4_1",
            "ｃｈ",
            "K",
        ):
            with self.subTest(invalid=repr(name)):
                with self.assertRaises(ValueError):
                    InputType(name, EmptyType())
                with self.assertRaises(ValueError):
                    OutputType(name, EmptyType())


    def test_recursive_type_names_use_ascii_ident(self) -> None:
        r"""Verify recursive type names use ascii ident."""

        self.assertEqual(TypeVar("t_1").name, "t_1")
        self.assertEqual(MuType("t_1", EmptyType()).variable, "t_1")
        for name in ("\u03b1\u03b2", "ｔ", "K"):
            with self.subTest(name=name):
                with self.assertRaises(ValueError):
                    TypeVar(name)
                with self.assertRaises(ValueError):
                    MuType(name, EmptyType())


class TimedTypeNormalizationTests(unittest.TestCase):
    r"""Tests for Timed Type Normalization."""


    def test_unified_delay_rule_dispatches_to_distinct_nodes(self) -> None:
        r"""Verify unified delay rule dispatches to distinct nodes."""

        communication = InputType("ch", EmptyType())
        self.assertEqual(
            make_delay_type(1, NoInterruptType(), EmptyType()),
            FiniteDelayType(1, NoInterruptType(), EmptyType()),
        )
        self.assertEqual(
            make_delay_type(1, communication, EmptyType()),
            FiniteDelayType(1, communication, EmptyType()),
        )


    def test_infinite_delay_discards_timeout_fallback(self) -> None:
        r"""Verify infinite delay discards timeout fallback."""

        communication = InputType("ch", EmptyType())
        self.assertEqual(
            make_delay_type(inf, communication, BottomType()),
            InfiniteDelayType(communication),
        )
        self.assertEqual(
            make_delay_type(inf, communication, EmptyType()),
            InfiniteDelayType(communication),
        )
        self.assertEqual(
            make_delay_type(inf, NoInterruptType(), EmptyType()),
            InfiniteDelayType(NoInterruptType()),
        )


    def test_finite_delay_distinguishes_bottom_from_empty(self) -> None:
        r"""Verify finite delay distinguishes bottom from empty."""

        communication = OutputType("ch", EmptyType())
        with self.assertRaises(TypeError):
            FiniteDelayType(1, "not-an-interrupt", EmptyType())  # type: ignore[arg-type]
        self.assertEqual(
            make_delay_type(1, communication, BottomType()),
            FiniteDelayType(1, communication, BottomType()),
        )
        self.assertNotEqual(
            FiniteDelayType(1, communication, BottomType()),
            FiniteDelayType(1, communication, EmptyType()),
        )


    def test_duration_is_exact_and_checked_at_type_boundary(self) -> None:
        r"""Verify duration is exact and checked at type boundary."""

        self.assertEqual(
            FiniteDelayType(0.5, NoInterruptType(), EmptyType()).duration,
            Fraction(1, 2),
        )
        self.assertEqual(
            FiniteDelayType(
                Decimal("0.125"), NoInterruptType(), EmptyType()
            ).duration,
            Fraction(1, 8),
        )
        communication = InputType("ch", EmptyType())
        self.assertEqual(
            make_delay_type(Decimal("Infinity"), communication, EmptyType()),
            InfiniteDelayType(communication),
        )
        for invalid in (-1, True, nan, -inf, Decimal("NaN")):
            with self.subTest(invalid=invalid):
                with self.assertRaises((TypeError, ValueError)):
                    FiniteDelayType(invalid, NoInterruptType(), EmptyType())


class TypeLayerAndRecursionTests(unittest.TestCase):
    r"""Tests for Type Layer And Recursion."""


    def test_configuration_type_cannot_appear_inside_process_type(self) -> None:
        r"""Verify configuration type cannot appear inside process type."""

        combined = ParallelType((EmptyType(), BottomType()))
        with self.assertRaises(TypeError):
            InputType("ch", combined)  # type: ignore[arg-type]
        with self.assertRaises(TypeError):
            InternalChoiceType((EmptyType(), combined))  # type: ignore[arg-type]
        with self.assertRaises(TypeError):
            MuType("t", combined)  # type: ignore[arg-type]
        with self.assertRaises(ValueError):
            InternalChoiceType((EmptyType(),))
        with self.assertRaises(ValueError):
            ParallelType((EmptyType(),))
        with self.assertRaises(TypeError):
            ProcessType()


    def test_internal_choice_preserves_parenthesized_grouping(self) -> None:
        r"""Verify internal choice preserves parenthesized grouping."""

        a = InfiniteDelayType(OutputType("a", EmptyType()))
        b = InfiniteDelayType(OutputType("b", EmptyType()))
        c = InfiniteDelayType(OutputType("c", EmptyType()))
        left_grouped = InternalChoiceType((InternalChoiceType((a, b)), c))
        right_grouped = InternalChoiceType((a, InternalChoiceType((b, c))))

        self.assertNotEqual(left_grouped, right_grouped)
        self.assertFalse(types_equivalent(left_grouped, right_grouped))


    def test_recursive_type_requires_a_communication_guard(self) -> None:
        r"""Verify recursive type requires a communication guard."""

        with self.assertRaises(ValueError):
            MuType("t", TypeVar("t"))
        with self.assertRaises(ValueError):
            MuType(
                "t",
                FiniteDelayType(1, NoInterruptType(), TypeVar("t")),
            )
        guarded = MuType(
            "t",
            InfiniteDelayType(InputType("ch", TypeVar("t"))),
        )
        self.assertEqual(
            guarded.body,
            InfiniteDelayType(InputType("ch", TypeVar("t"))),
        )


    def test_alpha_equivalence_covers_timed_nodes(self) -> None:
        r"""Verify alpha equivalence covers timed nodes."""

        left = MuType(
            "t",
            FiniteDelayType(
                1,
                InputType("ch", TypeVar("t")),
                InfiniteDelayType(OutputType("done", EmptyType())),
            ),
        )
        right = MuType(
            "u",
            FiniteDelayType(
                Fraction(1),
                InputType("ch", TypeVar("u")),
                InfiniteDelayType(OutputType("done", EmptyType())),
            ),
        )
        changed = MuType(
            "u",
            FiniteDelayType(
                1,
                OutputType("ch", TypeVar("u")),
                InfiniteDelayType(OutputType("done", EmptyType())),
            ),
        )
        self.assertTrue(types_equivalent(left, right))
        self.assertFalse(types_equivalent(left, changed))


class TypeRenderingTests(unittest.TestCase):
    r"""Tests for Type Rendering."""


    def test_communication_prefix_parenthesizes_complete_continuation(self) -> None:
        r"""Verify communication prefix parenthesizes complete continuation."""

        value = InputType(
            "in",
            InternalChoiceType(
                (
                    InfiniteDelayType(OutputType("left", EmptyType())),
                    InfiniteDelayType(OutputType("right", EmptyType())),
                )
            ),
        )

        self.assertEqual(
            str(value),
            r"in?.((delay(infinity) \unrhd (left!.(0))) \sqcup "
            r"(delay(infinity) \unrhd (right!.(0))))",
        )


    def test_timed_type_parenthesizes_choices_and_fallback(self) -> None:
        r"""Verify timed type parenthesizes choices and fallback."""

        choices = ExternalChoiceType(
            (
                InputType("reset", EmptyType()),
                OutputType("alarm", EmptyType()),
            )
        )
        fallback = InternalChoiceType(
            (
                InfiniteDelayType(OutputType("left", EmptyType())),
                InfiniteDelayType(OutputType("right", EmptyType())),
            )
        )

        self.assertEqual(
            str(FiniteDelayType(2, choices, fallback)),
            r"delay(2) \unrhd ((reset?.(0)) \sqcap (alarm!.(0))) "
            r"\triangleright ((delay(infinity) \unrhd (left!.(0))) \sqcup "
            r"(delay(infinity) \unrhd (right!.(0))))",
        )
        self.assertEqual(
            str(FiniteDelayType(2, choices, EmptyType())),
            r"delay(2) \unrhd ((reset?.(0)) \sqcap (alarm!.(0))) "
            r"\triangleright (0)",
        )
        self.assertEqual(
            str(FiniteDelayType(2, choices, BottomType())),
            r"delay(2) \unrhd ((reset?.(0)) \sqcap (alarm!.(0)))",
        )


    def test_parallel_type_parenthesizes_complete_components(self) -> None:
        r"""Verify parallel type parenthesizes complete components."""

        recursive = MuType(
            "t",
            InternalChoiceType(
                (
                    InfiniteDelayType(InputType("ch", TypeVar("t"))),
                    InfiniteDelayType(OutputType("stop", EmptyType())),
                )
            ),
        )
        delayed = FiniteDelayType(
            1,
            NoInterruptType(),
            InfiniteDelayType(OutputType("done", EmptyType())),
        )

        self.assertEqual(
            str(ParallelType((recursive, delayed))),
            r"(mu t.((delay(infinity) \unrhd (ch?.(t))) \sqcup "
            r"(delay(infinity) \unrhd (stop!.(0))))) "
            r"| (delay(1).(delay(infinity) \unrhd (done!.(0))))",
        )


if __name__ == "__main__":
    unittest.main()
