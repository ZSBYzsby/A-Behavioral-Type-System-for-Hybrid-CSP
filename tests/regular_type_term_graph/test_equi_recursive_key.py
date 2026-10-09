r"""Regression tests for equi recursive key. Paper reference: Table 3."""

from __future__ import annotations

import unittest

from hcsp_typechecker.backend.type_operational_semantics.regular_tree import (
    build_regular_type_term_graph,
    equi_recursive_equivalent,
    equi_recursive_state_key,
    normalized_type_from_state_key,
)
from hcsp_typechecker.data_structures.normalized_type_ast import (
    NormalizedConfigurationType,
    NormalizedMuType,
    normalize_type_ast,
)
from hcsp_typechecker.data_structures.regular_type_term_graph import (
    CanonicalRegularTypeNode,
    EquiRecursiveStateKey,
    RegularTypeNodeKind,
)
from hcsp_typechecker.data_structures.type_ast import (
    EmptyType,
    InfiniteDelayType,
    InputType,
    InternalChoiceType,
    MuType,
    OutputType,
    ParallelType,
    TypeVar,
    make_external_choice,
)


class EquiRecursiveStateKeyTests(unittest.TestCase):
    r"""Tests for Equi Recursive State Key."""


    def test_mu_type_equals_its_one_step_unfolding(self) -> None:
        r"""Verify mu type equals its one step unfolding."""

        loop = MuType(
            "loop",
            InfiniteDelayType(InputType("ch", TypeVar("loop"))),
        )
        folded = normalize_type_ast(loop)
        body = folded.components[0]
        self.assertIsInstance(body, NormalizedMuType)
        unfolded = normalize_type_ast(
            InfiniteDelayType(InputType("ch", loop))
        )
        unfolded_twice = normalize_type_ast(
            InfiniteDelayType(
                InputType("ch", InfiniteDelayType(InputType("ch", loop)))
            )
        )

        self.assertNotEqual(folded, unfolded)
        self.assertTrue(equi_recursive_equivalent(folded, unfolded))
        self.assertEqual(
            equi_recursive_state_key(folded),
            equi_recursive_state_key(unfolded),
        )
        self.assertEqual(
            equi_recursive_state_key(folded),
            equi_recursive_state_key(unfolded_twice),
        )


    def test_alpha_renaming_does_not_change_the_key(self) -> None:
        r"""Verify alpha renaming does not change the key."""

        left = normalize_type_ast(
            MuType("left", InfiniteDelayType(OutputType("tick", TypeVar("left"))))
        )
        right = normalize_type_ast(
            MuType("right", InfiniteDelayType(OutputType("tick", TypeVar("right"))))
        )

        self.assertEqual(
            equi_recursive_state_key(left),
            equi_recursive_state_key(right),
        )


    def test_nested_binders_resolve_without_capture(self) -> None:
        r"""Verify nested binders resolve without capture."""

        def nested(outer: str, inner: str) -> MuType:
            r"""Build nested recursion referencing both outer and inner binders."""

            return MuType(
                outer,
                InfiniteDelayType(
                    InputType(
                        "enter",
                        MuType(
                            inner,
                            InfiniteDelayType(
                                make_external_choice(
                                    (
                                        InputType("again", TypeVar(inner)),
                                        OutputType("leave", TypeVar(outer)),
                                    )
                                )
                            ),
                        ),
                    )
                ),
            )

        left = normalize_type_ast(nested("outer", "inner"))
        right = normalize_type_ast(nested("x", "y"))

        key = equi_recursive_state_key(left)
        self.assertEqual(key, equi_recursive_state_key(right))
        self.assertGreaterEqual(len(key.nodes), 5)
        self.assertEqual(
            equi_recursive_state_key(normalized_type_from_state_key(key)),
            key,
        )


    def test_unused_mu_binder_is_semantically_transparent(self) -> None:
        r"""Verify unused mu binder is semantically transparent."""

        body = InfiniteDelayType(InputType("ready", EmptyType()))
        wrapped = normalize_type_ast(MuType("unused", body))
        plain = normalize_type_ast(body)

        self.assertEqual(
            equi_recursive_state_key(wrapped),
            equi_recursive_state_key(plain),
        )


    def test_choice_collapses_branches_equal_only_after_unfolding(self) -> None:
        r"""Verify choice collapses branches equal only after unfolding."""

        loop = MuType(
            "loop",
            InfiniteDelayType(InputType("a", TypeVar("loop"))),
        )
        unfolded = InfiniteDelayType(InputType("a", loop))
        choice = normalize_type_ast(InternalChoiceType((loop, unfolded)))
        plain = normalize_type_ast(loop)

        self.assertEqual(
            equi_recursive_state_key(choice),
            equi_recursive_state_key(plain),
        )


    def test_observable_communication_labels_remain_distinct(self) -> None:
        r"""Verify observable communication labels remain distinct."""

        input_a = normalize_type_ast(
            MuType("t", InfiniteDelayType(InputType("a", TypeVar("t"))))
        )
        input_b = normalize_type_ast(
            MuType("t", InfiniteDelayType(InputType("b", TypeVar("t"))))
        )
        output_a = normalize_type_ast(
            MuType("t", InfiniteDelayType(OutputType("a", TypeVar("t"))))
        )

        keys = {
            equi_recursive_state_key(input_a),
            equi_recursive_state_key(input_b),
            equi_recursive_state_key(output_a),
        }
        self.assertEqual(len(keys), 3)


    def test_parallel_roots_preserve_multiplicity_but_remove_empty(self) -> None:
        r"""Verify parallel roots preserve multiplicity but remove empty."""

        loop = MuType(
            "t", InfiniteDelayType(InputType("request", TypeVar("t")))
        )
        single = normalize_type_ast(loop)
        with_empty = normalize_type_ast(ParallelType((loop, EmptyType())))
        doubled = normalize_type_ast(ParallelType((loop, loop)))

        self.assertEqual(
            equi_recursive_state_key(single),
            equi_recursive_state_key(with_empty),
        )
        self.assertNotEqual(
            equi_recursive_state_key(single),
            equi_recursive_state_key(doubled),
        )


    def test_term_graph_contains_no_mu_or_variable_nodes(self) -> None:
        r"""Verify term graph contains no mu or variable nodes."""

        normalized = normalize_type_ast(
            MuType("t", InfiniteDelayType(InputType("ch", TypeVar("t"))))
        )

        graph = build_regular_type_term_graph(normalized)

        self.assertEqual(
            {node.kind for node in graph.nodes},
            {RegularTypeNodeKind.INFINITE_DELAY, RegularTypeNodeKind.INPUT},
        )


    def test_display_ast_reconstructs_the_same_regular_tree(self) -> None:
        r"""Verify display AST reconstructs the same regular tree."""

        loop = MuType(
            "loop",
            InfiniteDelayType(
                make_external_choice(
                    (
                        InputType("again", TypeVar("loop")),
                        OutputType("done", EmptyType()),
                    )
                )
            ),
        )
        original = normalize_type_ast(ParallelType((loop, loop)))
        key = equi_recursive_state_key(original)

        displayed = normalized_type_from_state_key(key)

        self.assertEqual(equi_recursive_state_key(displayed), key)


    def test_regular_graph_rejects_angelic_configuration_roots(self) -> None:
        r"""Verify regular graph rejects angelic configuration roots."""

        with self.assertRaisesRegex(ValueError, "process-type"):
            EquiRecursiveStateKey(
                (0,),
                (
                    CanonicalRegularTypeNode(
                        RegularTypeNodeKind.INPUT,
                        "ch",
                        (1,),
                    ),
                    CanonicalRegularTypeNode(RegularTypeNodeKind.EMPTY),
                ),
            )


if __name__ == "__main__":
    unittest.main()
