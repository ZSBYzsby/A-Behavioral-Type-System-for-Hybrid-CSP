r"""Regression tests for explicit work stacks. Paper reference: Table 2/3."""

from __future__ import annotations

from io import StringIO
import unittest

from hcsp_typechecker import (
    build_type_transition_graph,
    check_hcsp_type,
    construct_hcsp_type,
)
from hcsp_typechecker._internal import EmptyType, InfiniteDelayType, InputType
from hcsp_typechecker.frontend.type_syntax import (
    format_type_source,
    parse_type_source,
)


class ExplicitWorkStackTests(unittest.TestCase):
    r"""Tests for Explicit Work Stack."""


    def test_constructor_handles_two_thousand_sequential_statements(self) -> None:
        r"""Verify constructor handles two thousand sequential statements."""

        statements = ";".join("skip" for _ in range(2000))
        source = f"gamma() theta() process {{{{{statements}}}}}"
        constructed = construct_hcsp_type(source, output="none")
        self.assertIsInstance(constructed, EmptyType)
        graph = build_type_transition_graph(constructed, output="none")
        self.assertEqual(len(graph.states), 1)
        self.assertEqual(len(graph.transitions), 0)


    def test_constructor_handles_deeply_nested_control_blocks(self) -> None:
        r"""Verify constructor handles deeply nested control blocks."""

        body = "skip"
        for _ in range(150):
            body = f"if(true){{{body}}}else{{skip}}"
        constructed = construct_hcsp_type(
            f"gamma() theta() process {{{{{body}}}}}",
            output="none",
        )
        self.assertIsNotNone(constructed)


    def test_type_parser_and_checker_handle_deep_inputs(self) -> None:
        r"""Verify type parser and checker handle deep inputs."""

        depth = 1500
        type_source = (
            "type "
            + "forever interrupt angelic {ch? -> " * depth
            + "empty"
            + "}" * depth
        )
        parsed = parse_type_source(type_source)
        self.assertIsInstance(parsed, InfiniteDelayType)

        statements = ";".join("skip" for _ in range(2000))
        checked = check_hcsp_type(
            f"gamma() theta() process {{{{{statements}}}}} type empty",
            output="none",
        )
        self.assertIsInstance(checked, EmptyType)


    def test_transition_graph_handles_deep_type_ast(self) -> None:
        r"""Verify transition graph handles deep type AST."""

        value = EmptyType()
        for _ in range(300):
            value = InfiniteDelayType(InputType("ch", value))
        graph = build_type_transition_graph(value, max_states=4)
        self.assertEqual(len(graph.states), 1)
        self.assertEqual(len(graph.transitions), 1)


    def test_constructor_handles_deep_arithmetic_expression(self) -> None:
        r"""Verify constructor handles deep arithmetic expression."""

        expression = "+".join("1" for _ in range(1500))
        source = f"gamma(x: Int) theta() process {{{{x := {expression}}}}}"
        constructed = construct_hcsp_type(source, output="none")
        self.assertIsInstance(constructed, EmptyType)


    def test_transition_graph_full_output_handles_deep_type(self) -> None:
        r"""Verify transition graph full output handles deep type."""

        value = EmptyType()
        for _ in range(520):
            value = InfiniteDelayType(InputType("ch", value))
        stream = StringIO()
        graph = build_type_transition_graph(
            value,
            max_states=4,
            output="full",
            stream=stream,
        )
        self.assertEqual(len(graph.states), 1)
        self.assertIn("normalized type", stream.getvalue())
        self.assertIn("transitions", stream.getvalue())


    def test_constructor_output_scale_is_accepted_by_graph_interface(self) -> None:
        r"""Verify constructor output scale is accepted by graph interface."""

        statements = ";".join("ch!(0)" for _ in range(180))
        source = (
            "gamma() theta(ch: channel(value: Int)) "
            f"process {{{{{statements}}}}}"
        )
        constructed = construct_hcsp_type(source, output="none")
        stream = StringIO()
        graph = build_type_transition_graph(
            constructed,
            output="full",
            stream=stream,
        )
        self.assertEqual(len(graph.states), 1)
        self.assertEqual(len(graph.transitions), 1)
        self.assertIn("type transition graph", stream.getvalue())


    def test_parallel_constructor_output_is_accepted_by_graph_interface(self) -> None:
        r"""Verify parallel constructor output is accepted by graph interface."""

        components = ",".join("{skip}" for _ in range(300))
        constructed = construct_hcsp_type(
            f"gamma() theta() process {{{components}}}",
            output="none",
        )
        graph = build_type_transition_graph(constructed, output="none")
        self.assertEqual(len(graph.states), 1)
        self.assertEqual(len(graph.transitions), 0)


    def test_constructor_output_scale_is_accepted_by_checker(self) -> None:
        r"""Verify constructor output scale is accepted by checker."""

        statements = ";".join("ch!(0)" for _ in range(180))
        source = (
            "gamma() theta(ch: channel(value: Int)) "
            f"process {{{{{statements}}}}}"
        )
        constructed = construct_hcsp_type(source, output="none")
        stream = StringIO()
        checked = check_hcsp_type(
            source + "\n" + format_type_source(constructed),
            output="full",
            stream=stream,
        )
        self.assertEqual(format_type_source(checked), format_type_source(constructed))
        self.assertIn('HCSP type checking full log', stream.getvalue())


    def test_parallel_constructor_output_scale_is_accepted_by_checker(self) -> None:
        r"""Verify parallel constructor output scale is accepted by checker."""

        components = ",".join("{skip}" for _ in range(300))
        source = f"gamma() theta() process {{{components}}}"
        constructed = construct_hcsp_type(source, output="none")
        checked = check_hcsp_type(
            source + "\n" + format_type_source(constructed),
            output="none",
        )
        self.assertEqual(format_type_source(checked), format_type_source(constructed))


if __name__ == "__main__":
    unittest.main()
