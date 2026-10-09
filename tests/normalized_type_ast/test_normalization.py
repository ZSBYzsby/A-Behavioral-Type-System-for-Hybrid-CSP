r"""Regression tests for normalization. Paper reference: Table 3, Section 4.1."""

from __future__ import annotations

from fractions import Fraction
import unittest

import hcsp_typechecker.data_structures.normalized_type_ast as normalized_api
from hcsp_typechecker.data_structures.normalized_type_ast import (
    NormalizedBoundTypeVar,
    NormalizedBottomType,
    NormalizedConfigurationType,
    NormalizedEmptyType,
    NormalizedExternalChoiceType,
    NormalizedFiniteDelayType,
    NormalizedInfiniteDelayType,
    NormalizedInputType,
    NormalizedInternalChoiceType,
    NormalizedMuType,
    NormalizedOutputType,
    TypeNormalizationError,
    normalize_type_ast,
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


class NormalizedTypeConversionTests(unittest.TestCase):
    r"""Tests for Normalized Type Conversion."""


    def test_parallel_is_sorted_and_empty_is_only_a_unit(self) -> None:
        r"""Verify parallel is sorted and empty is only a unit."""

        first = FiniteDelayType(1, NoInterruptType(), EmptyType())
        second = InfiniteDelayType(NoInterruptType())
        left = ParallelType((second, EmptyType(), first, first))
        right = ParallelType((first, ParallelType((first, second))))

        normalized_left = normalize_type_ast(left)
        normalized_right = normalize_type_ast(right)

        self.assertEqual(normalized_left, normalized_right)
        self.assertEqual(len(normalized_left.components), 3)
        self.assertEqual(
            normalize_type_ast(ParallelType((EmptyType(), EmptyType()))),
            NormalizedConfigurationType((NormalizedEmptyType(),)),
        )


    def test_internal_choice_is_flattened_sorted_and_idempotent(self) -> None:
        r"""Verify internal choice is flattened sorted and idempotent."""

        a = FiniteDelayType(1, NoInterruptType(), EmptyType())
        b = FiniteDelayType(2, NoInterruptType(), EmptyType())
        nested = InternalChoiceType(
            (b, InternalChoiceType((a, b)), a)
        )

        normalized = normalize_type_ast(nested).components[0]

        self.assertIsInstance(normalized, NormalizedInternalChoiceType)
        self.assertEqual(len(normalized.branches), 2)
        duplicate = normalize_type_ast(InternalChoiceType((a, a)))
        self.assertIsInstance(duplicate.components[0], NormalizedFiniteDelayType)


    def test_external_choice_is_sorted_and_exactly_deduplicated(self) -> None:
        r"""Verify external choice is sorted and exactly deduplicated."""

        first = InputType("ch", EmptyType())
        second = OutputType(
            "dh",
            FiniteDelayType(1, NoInterruptType(), EmptyType()),
        )
        value = InfiniteDelayType(ExternalChoiceType((second, first, first)))

        normalized = normalize_type_ast(value).components[0]

        self.assertIsInstance(normalized, NormalizedInfiniteDelayType)
        self.assertIsInstance(normalized.interrupts, NormalizedExternalChoiceType)
        self.assertEqual(len(normalized.interrupts.branches), 2)
        self.assertIsInstance(normalized.interrupts.branches[0], NormalizedInputType)
        self.assertIsInstance(normalized.interrupts.branches[1], NormalizedOutputType)


    def test_recursive_names_become_de_bruijn_indices(self) -> None:
        r"""Verify recursive names become de bruijn indices."""

        left = MuType("t", InfiniteDelayType(InputType("ch", TypeVar("t"))))
        right = MuType("loop", InfiniteDelayType(InputType("ch", TypeVar("loop"))))

        normalized = normalize_type_ast(left)

        self.assertEqual(normalized, normalize_type_ast(right))
        root = normalized.components[0]
        self.assertIsInstance(root, NormalizedMuType)
        self.assertEqual(
            root.body.interrupts.continuation,
            NormalizedBoundTypeVar(0),
        )
        with self.assertRaises(TypeNormalizationError):
            normalize_type_ast(TypeVar("free"))


    def test_zero_delay_is_retained_and_conversion_is_one_way(self) -> None:
        r"""Verify zero delay is retained and conversion is one way."""

        normalized = normalize_type_ast(
            FiniteDelayType(0, NoInterruptType(), EmptyType())
        )

        delay = normalized.components[0]
        self.assertIsInstance(delay, NormalizedFiniteDelayType)
        self.assertEqual(delay.duration, Fraction(0))
        self.assertFalse(hasattr(normalized_api, "denormalize_type_ast"))


    def test_finite_bottom_and_empty_remain_distinct(self) -> None:
        r"""Verify finite bottom and empty remain distinct."""

        bottom = normalize_type_ast(
            FiniteDelayType(1, NoInterruptType(), BottomType())
        ).components[0]
        empty = normalize_type_ast(
            FiniteDelayType(1, NoInterruptType(), EmptyType())
        ).components[0]

        self.assertIsInstance(bottom, NormalizedFiniteDelayType)
        self.assertIsInstance(bottom.continuation, NormalizedBottomType)
        self.assertIsInstance(empty, NormalizedFiniteDelayType)
        self.assertIsInstance(empty.continuation, NormalizedEmptyType)
        self.assertNotEqual(bottom, empty)


if __name__ == "__main__":
    unittest.main()
