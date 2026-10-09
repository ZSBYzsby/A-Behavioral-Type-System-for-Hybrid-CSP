r"""Regression tests for graph demo. Paper reference: Table 3, Table 2."""

from __future__ import annotations

from contextlib import redirect_stdout
from io import StringIO
import unittest

from examples import demo_type_transition_graph as transition_graph_demo
from hcsp_typechecker import build_type_transition_graph


class GraphDemoPipelineTests(unittest.TestCase):
    r"""Tests for Graph Demo Pipeline."""


    def test_every_example_builds_a_nontrivial_graph(self) -> None:
        r"""Verify every example builds a nontrivial graph."""

        examples = transition_graph_demo.build_examples()

        self.assertEqual(len(examples), 3)
        for example in examples:
            with self.subTest(title=example.title):
                graph = build_type_transition_graph(example.type_ast)
                self.assertGreaterEqual(len(graph.states), 2)
                self.assertGreaterEqual(len(graph.transitions), 1)


    def test_main_prints_all_parallel_semantics_features(self) -> None:
        r"""Verify main prints all parallel semantics features."""

        output = StringIO()
        with redirect_stdout(output):
            exit_code = transition_graph_demo.main()

        rendered = output.getvalue()
        self.assertEqual(exit_code, 0)
        self.assertEqual(rendered.count('Input Type AST in user syntax'), 3)
        self.assertEqual(rendered.count("type transition graph {"), 3)
        self.assertIn('Recursive server with two competing clients', rendered)
        self.assertIn('Request/reply server, client, and watchdog', rendered)
        self.assertIn('Internal choice, staggered deadlines', rendered)
        self.assertNotIn("P-mu", rendered)
        self.assertIn("P-unrhd", rendered)
        self.assertIn("P-sqcup", rendered)
        self.assertIn("time(1", rendered)
        self.assertIn('Demo complete: all transition graphs were constructed successfully', rendered)


if __name__ == "__main__":
    unittest.main()
