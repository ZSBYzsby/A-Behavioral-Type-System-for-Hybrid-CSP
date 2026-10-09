r"""Regression tests for serializer. Paper reference: Table 3."""

from __future__ import annotations

from fractions import Fraction
import unittest

import hcsp_typechecker.frontend.normalized_type_syntax as normalized_syntax
from hcsp_typechecker.data_structures.normalized_type_ast import normalize_type_ast
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
from hcsp_typechecker.frontend.normalized_type_syntax import (
    format_normalized_type_ast,
)


class NormalizedTypeSerializerTests(unittest.TestCase):
    r"""Tests for Normalized Type Serializer."""


    def test_complete_normalized_tree_reuses_user_type_style(self) -> None:
        r"""Verify complete normalized tree reuses user type style."""

        recursive = MuType(
            "loop",
            InfiniteDelayType(InputType("again", TypeVar("loop"))),
        )
        delayed = FiniteDelayType(
            Fraction(3, 2),
            ExternalChoiceType(
                (
                    OutputType("report", EmptyType()),
                    InputType("reset", recursive),
                )
            ),
            InternalChoiceType((BottomType(), EmptyType())),
        )

        rendered = format_normalized_type_ast(
            normalize_type_ast(
                ParallelType((delayed, InfiniteDelayType(NoInterruptType())))
            )
        )

        for fragment in (
            "normalized type parallel {",
            "delay(3/2) interrupt",
            "angelic {",
            "again? ->",
            "report! ->",
            "mu {",
            "again? -> recursion_position(0)",
            "internal {",
            "empty",
            "bottom",
            "forever",
        ):
            with self.subTest(fragment=fragment):
                self.assertIn(fragment, rendered)
        self.assertTrue(
            all(
                not line or (len(line) - len(line.lstrip())) % 4 == 0
                for line in rendered.splitlines()
            )
        )
        for hidden_implementation_spelling in (
            "NormalizedConfigurationType(",
            "NormalizedFiniteDelayType(",
            "NormalizedInfiniteDelayType(",
            "NormalizedNoInterruptType(",
            "NormalizedExternalChoiceType(",
            "NormalizedInputType(",
            "NormalizedOutputType(",
            "Fraction(",
            "index=",
            "(empty)",
            "(bottom)",
            "mu X",
        ):
            with self.subTest(hidden=hidden_implementation_spelling):
                self.assertNotIn(hidden_implementation_spelling, rendered)


    def test_equivalent_original_shapes_have_identical_output(self) -> None:
        r"""Verify equivalent original shapes have identical output."""

        first = FiniteDelayType(1, NoInterruptType(), EmptyType())
        second = InfiniteDelayType(
            ExternalChoiceType(
                (InputType("ch", EmptyType()), OutputType("dh", EmptyType()))
            )
        )
        left = ParallelType((second, EmptyType(), first))
        right = ParallelType((first, second))

        self.assertEqual(
            format_normalized_type_ast(normalize_type_ast(left)),
            format_normalized_type_ast(normalize_type_ast(right)),
        )


    def test_nested_mu_displays_de_bruijn_recursion_positions(self) -> None:
        r"""Verify nested mu displays de bruijn recursion positions."""

        nested = MuType(
            "outer",
            InfiniteDelayType(
                InputType(
                    "enter",
                    MuType(
                        "inner",
                        InfiniteDelayType(
                            ExternalChoiceType(
                                (
                                    InputType("again", TypeVar("inner")),
                                    OutputType("leave", TypeVar("outer")),
                                )
                            )
                        ),
                    ),
                )
            ),
        )

        rendered = format_normalized_type_ast(normalize_type_ast(nested))

        self.assertEqual(rendered.count("mu {"), 2)
        self.assertIn("again? -> recursion_position(0)", rendered)
        self.assertIn("leave! -> recursion_position(1)", rendered)
        self.assertNotIn("outer", rendered)
        self.assertNotIn("inner", rendered)


    def test_output_syntax_is_deliberately_one_way(self) -> None:
        r"""Verify output syntax is deliberately one way."""

        with self.assertRaises(TypeError):
            format_normalized_type_ast(EmptyType())  # type: ignore[arg-type]
        self.assertEqual(
            normalized_syntax.__all__,
            ["format_normalized_type_ast"],
        )
        self.assertFalse(hasattr(normalized_syntax, "parse_normalized_type_ast"))


if __name__ == "__main__":
    unittest.main()
