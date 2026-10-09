r"""Regression tests for serializer. Paper reference: Table 3."""

from __future__ import annotations

import unittest

import hcsp_typechecker.frontend.type_transition_graph_syntax as graph_syntax
from hcsp_typechecker.backend.type_operational_semantics import (
    build_type_transition_graph,
)
from hcsp_typechecker.data_structures.type_ast import (
    EmptyType,
    FiniteDelayType,
    InfiniteDelayType,
    InputType,
    NoInterruptType,
    OutputType,
    ParallelType,
)
from hcsp_typechecker.frontend.type_transition_graph_syntax import (
    format_type_transition_graph,
)


class TypeTransitionGraphSerializerTests(unittest.TestCase):
    r"""Tests for Type Transition Graph Serializer."""


    def test_timed_edge_and_nested_rule_evidence_are_rendered(self) -> None:
        r"""Verify timed edge and nested rule evidence are rendered."""

        graph = build_type_transition_graph(
            ParallelType(
                (
                    FiniteDelayType(
                        2,
                        InputType("left", EmptyType()),
                        EmptyType(),
                    ),
                    FiniteDelayType(
                        5,
                        OutputType("right", EmptyType()),
                        EmptyType(),
                    ),
                )
            )
        )

        rendered = format_type_transition_graph(graph)

        self.assertIn("S0 -- time(2, ready={left?, right!}) --> S1 by {", rendered)
        self.assertIn(
            "\n".join(
                (
                    "            P-parallel(components=[0, 1]) {",
                    "                P-unrhd-prime()",
                    "                P-unrhd-prime()",
                    "            }",
                )
            ),
            rendered,
        )
        self.assertIn("S0 = normalized type parallel {", rendered)


    def test_communication_edge_exposes_matching_witness(self) -> None:
        r"""Verify communication edge exposes matching witness."""

        graph = build_type_transition_graph(
            ParallelType(
                (
                    InfiniteDelayType(InputType("ch", EmptyType())),
                    InfiniteDelayType(OutputType("ch", EmptyType())),
                )
            )
        )

        rendered = format_type_transition_graph(graph)

        self.assertIn("S0 -- tau --> S1 by {", rendered)
        self.assertIn(
            "P-unrhd(components=[0, 1], branches=[0, 0], channel='ch')",
            rendered,
        )
        self.assertNotIn("time(", rendered)


    def test_graph_output_is_deliberately_one_way(self) -> None:
        r"""Verify graph output is deliberately one way."""

        with self.assertRaises(TypeError):
            format_type_transition_graph(EmptyType())  # type: ignore[arg-type]
        self.assertEqual(
            graph_syntax.__all__,
            ["format_type_transition_graph"],
        )
        self.assertFalse(hasattr(graph_syntax, "parse_type_transition_graph"))


if __name__ == "__main__":
    unittest.main()
