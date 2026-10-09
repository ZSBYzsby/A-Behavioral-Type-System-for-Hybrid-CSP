r"""Regression tests for section21 AST. Paper reference: Section 2.1, Section 4.2/4.3."""

from __future__ import annotations

import math
from fractions import Fraction
import unittest

import hcsp_typechecker._internal as internal_api
import hcsp_typechecker.data_structures.process_ast.ast as process_ast
from hcsp_typechecker._internal import (
    Assert,
    Assign,
    Channel,
    EmptyEvent,
    EventChoice,
    EventReaction,
    Expr,
    HCSP,
    If,
    InputChannel,
    InternalChoice,
    Literal,
    Mu,
    ODE,
    ODEAnnotation,
    ODELocalClock,
    OutputChannel,
    Parallel,
    Process,
    RecursionAnnotation,
    Sequence,
    Skip,
    Var,
    Variable,
)


EXPECTED_EVENT_NODES = {"EmptyEvent", "EventChoice"}
EXPECTED_PROCESS_NODES = {
    "Skip",
    "Assign",
    "Assert",
    "InputChannel",
    "OutputChannel",
    "If",
    "ODE",
    "Sequence",
    "InternalChoice",
    "Var",
    "Mu",
}
EXPECTED_SYSTEM_ONLY_NODES = {"Parallel"}


def assert_event_reaction(test: unittest.TestCase, event: EventReaction) -> None:
    r"""Validate the paper event-reaction grammar recursively."""

    test.assertIsInstance(event, EventReaction)
    test.assertNotIsInstance(event, HCSP)
    if isinstance(event, EmptyEvent):
        return
    test.assertIsInstance(event, EventChoice)
    test.assertTrue(event.branches)
    for communication, continuation in event.branches:
        test.assertIsInstance(communication, (InputChannel, OutputChannel))
        assert_process(test, continuation)


def assert_process(test: unittest.TestCase, process: Process) -> None:
    r"""Validate the paper sequential-process grammar recursively."""

    test.assertIsInstance(process, Process)
    test.assertIsInstance(process, HCSP)
    test.assertNotIsInstance(process, Parallel)

    if isinstance(process, (Skip, Var)):
        return
    if isinstance(process, Assign):
        test.assertIsInstance(process.target, Variable)
        test.assertIsInstance(process.expression, Expr)
        return
    if isinstance(process, Assert):
        test.assertIsInstance(process.condition, Expr)
        return
    if isinstance(process, InputChannel):
        test.assertTrue(process.targets)
        test.assertTrue(
            all(isinstance(target, Variable) for target in process.targets)
        )
        return
    if isinstance(process, OutputChannel):
        test.assertTrue(process.payloads)
        test.assertTrue(
            all(isinstance(payload, Expr) for payload in process.payloads)
        )
        return
    if isinstance(process, If):
        test.assertIsInstance(process.condition, Expr)
        assert_process(test, process.then_branch)
        assert_process(test, process.else_branch)
        assert_process(test, process.continuation)
        return
    if isinstance(process, ODE):
        for variable, derivative in process.eqs:
            test.assertIsInstance(variable, str)
            test.assertIsInstance(derivative, Expr)
        test.assertIsInstance(process.constraint, Expr)
        test.assertIsInstance(process.annotation, ODEAnnotation)
        test.assertIsInstance(process.annotation.safety, Expr)
        test.assertTrue(
            isinstance(process.annotation.delay, (Expr, float))
        )
        test.assertIsInstance(process.local_clock, ODELocalClock)
        test.assertEqual(process.local_clock.initial_value, Literal(0))
        test.assertEqual(process.local_clock.derivative, Literal(1))
        assert_event_reaction(test, process.interrupts)
        assert_process(test, process.continuation)
        return
    if isinstance(process, Sequence):
        assert_process(test, process.first)
        assert_process(test, process.second)
        return
    if isinstance(process, InternalChoice):
        test.assertGreaterEqual(len(process.branches), 2)
        for branch in process.branches:
            assert_process(test, branch)
        assert_process(test, process.continuation)
        return
    if isinstance(process, Mu):
        test.assertIsInstance(process.variable, str)
        test.assertIsInstance(process.annotation, RecursionAnnotation)
        test.assertIsInstance(process.annotation.invariant, Expr)
        assert_process(test, process.body)
        return
    test.fail(f"Unsupported Process subclass escaped grammar audit: {type(process)!r}")


def assert_system(test: unittest.TestCase, system: HCSP) -> None:
    r"""Validate S ::= P | S || S' recursively."""

    test.assertIsInstance(system, HCSP)
    if isinstance(system, Process):
        assert_process(test, system)
        return
    test.assertIsInstance(system, Parallel)
    assert_system(test, system.left)
    assert_system(test, system.right)


class Section21NodeInventoryTests(unittest.TestCase):
    r"""Tests for Section21 Node Inventory."""


    def test_abstract_process_categories_cannot_be_instantiated(self) -> None:
        r"""Verify abstract process categories cannot be instantiated."""

        for abstract_class in (HCSP, Process, EventReaction):
            with self.subTest(abstract_class=abstract_class.__name__):
                with self.assertRaises(TypeError):
                    abstract_class()


    def test_event_node_inventory_is_exact(self) -> None:
        r"""Verify event node inventory is exact."""

        nodes = EventReaction.__subclasses__()
        actual = {node.__name__ for node in nodes}
        self.assertEqual(actual, EXPECTED_EVENT_NODES)


    def test_process_node_inventory_is_exact(self) -> None:
        r"""Verify process node inventory is exact."""

        nodes = Process.__subclasses__()
        actual = {node.__name__ for node in nodes}
        self.assertEqual(actual, EXPECTED_PROCESS_NODES)


    def test_system_only_node_inventory_is_exact(self) -> None:
        r"""Verify system only node inventory is exact."""

        nodes = [node for node in HCSP.__subclasses__() if node is not Process]
        actual = {node.__name__ for node in nodes}
        self.assertEqual(actual, EXPECTED_SYSTEM_ONLY_NODES)


class Section21EventGrammarTests(unittest.TestCase):
    r"""Tests for Section21 Event Grammar."""


    def test_empty_event_production(self) -> None:
        r"""Verify empty event production."""

        assert_event_reaction(self, EmptyEvent())


    def test_recursive_input_and_output_choice_productions(self) -> None:
        r"""Verify recursive input and output choice productions."""

        reaction = EventChoice(
            (InputChannel("sense", "x"), Assign("x", "x + 1")),
            (OutputChannel("ack", 0), Skip()),
        )
        assert_event_reaction(self, reaction)


    def test_event_choice_class_method_builds_one_nary_event_node(self) -> None:
        r"""Verify event choice class method builds one nary event node."""

        self.assertIsInstance(EventChoice.of(), EmptyEvent)
        reaction = EventChoice.of(
            (InputChannel("left", "x"), Skip()),
            (OutputChannel("right", 1), Assign("y", 0)),
            (OutputChannel("audit", 2), Skip()),
        )
        assert_event_reaction(self, reaction)
        self.assertEqual(len(reaction.branches), 3)


    def test_event_choice_rejects_noncommunication_prefix(self) -> None:
        r"""Verify event choice rejects noncommunication prefix."""

        with self.assertRaises(TypeError):
            EventChoice((Assign("x", 1), Skip()))  # type: ignore[arg-type]


    def test_event_choice_rejects_nonprocess_continuation(self) -> None:
        r"""Verify event choice rejects nonprocess continuation."""

        with self.assertRaises(TypeError):
            EventChoice((InputChannel("c", "x"), EmptyEvent()))  # type: ignore[arg-type]
        with self.assertRaises(TypeError):
            EventChoice(
                (InputChannel("c", "x"), Parallel(Skip(), Skip())),
            )  # type: ignore[arg-type]


    def test_event_choice_rejects_empty_branch_table(self) -> None:
        r"""Verify event choice rejects empty branch table."""

        with self.assertRaises(ValueError):
            EventChoice()


class Section21ProcessGrammarTests(unittest.TestCase):
    r"""Tests for Section21 Process Grammar."""


    def test_all_atomic_and_compound_process_productions(self) -> None:
        r"""Verify all atomic and compound process productions."""

        processes = (
            Skip(),
            Assign("x", "x + 1"),
            Assert("x >= 0"),
            InputChannel("in", "x"),
            OutputChannel("out", "x"),
            If("x >= 0", Assign("x", 1), Assign("x", -1)),
            ODE(
                [("x", 1)],
                "x <= 10",
                EventChoice.of((InputChannel("stop", "u"), Skip())),
                annotation=ODEAnnotation(delay=math.inf),
            ),
            Sequence(Assign("x", 0), Skip()),
            InternalChoice(Assign("x", 1), Assign("x", 2)),
            Var("X"),
            Mu("X", Sequence(InputChannel("tick", "u"), Var("X"))),
        )
        for process in processes:
            with self.subTest(node=type(process).__name__):
                assert_process(self, process)


    def test_communication_requires_explicit_target_and_payload(self) -> None:
        r"""Verify communication requires explicit target and payload."""

        input_process = InputChannel("stop", ("u", "ready"))
        output_process = OutputChannel("stop", (0, "ready"))
        self.assertEqual(
            input_process.targets,
            (Variable("u"), Variable("ready")),
        )
        self.assertEqual(
            output_process.payloads,
            (Literal(0), Variable("ready")),
        )
        self.assertEqual(InputChannel("one", "x").targets, (Variable("x"),))
        self.assertEqual(OutputChannel("one", 1).payloads, (Literal(1),))
        assert_process(self, input_process)
        assert_process(self, output_process)
        with self.assertRaisesRegex(ValueError, "at least one target"):
            InputChannel("stop", ())
        with self.assertRaisesRegex(ValueError, "must be distinct"):
            InputChannel("stop", ("u", "u"))
        with self.assertRaisesRegex(ValueError, "at least one payload"):
            OutputChannel("stop", ())
        with self.assertRaises(TypeError):
            OutputChannel("stop", ((1, 2),))
        with self.assertRaises(TypeError):
            InputChannel("stop")  # type: ignore[call-arg]
        with self.assertRaises(TypeError):
            OutputChannel("stop")  # type: ignore[call-arg]


    def test_communication_enforces_identifier_channel_names(self) -> None:
        r"""Verify communication enforces identifier channel names."""

        for name in ("channel", "channel_1", "_private", "Channel2"):
            with self.subTest(valid=name):
                self.assertEqual(Channel(name).name, name)
                self.assertEqual(InputChannel(name, "x").channel.name, name)
                self.assertEqual(OutputChannel(name, 0).channel.name, name)

        invalid_names = (
            "",
            " ",
            "\t",
            "\n",
            " channel",
            "channel ",
            "1channel",
            "a-b",
            "a.b",
            "a/b",
            "a\nb",
            "\u03b3\u03b4_1",
            "ｃｈ",
            "K",
        )
        for name in invalid_names:
            with self.subTest(name=repr(name)):
                with self.assertRaisesRegex(ValueError, "Invalid channel name"):
                    Channel(name)
                with self.assertRaisesRegex(ValueError, "Invalid channel name"):
                    InputChannel(name, "x")
                with self.assertRaisesRegex(ValueError, "Invalid channel name"):
                    OutputChannel(name, 0)


    def test_process_value_and_recursion_names_use_ascii_ident(self) -> None:
        r"""Verify process value and recursion names use ascii ident."""

        self.assertEqual(Assign("_x1", 0).target, Variable("_x1"))
        self.assertEqual(
            InputChannel("ch", "received_1").targets,
            (Variable("received_1"),),
        )
        self.assertEqual(Var("Loop_1").name, "Loop_1")

        for name in ("\u03b1\u03b2", "ｘ", "K"):
            with self.subTest(name=name):
                with self.assertRaises((TypeError, ValueError)):
                    Assign(name, 0)
                with self.assertRaises((TypeError, ValueError)):
                    InputChannel("ch", name)
                with self.assertRaises(ValueError):
                    Var(name)


    def test_if_is_binary_and_requires_two_process_branches(self) -> None:
        r"""Verify if is binary and requires two process branches."""

        node = If(True, Skip(), Assign("x", 1))
        self.assertIsInstance(node.then_branch, Process)
        self.assertIsInstance(node.else_branch, Process)
        self.assertIsInstance(node.continuation, Skip)
        with self.assertRaises(TypeError):
            If(True, Skip())  # type: ignore[call-arg]
        with self.assertRaises(TypeError):
            If(True, Skip(), Skip(), Skip())  # type: ignore[call-arg]
        with self.assertRaises(TypeError):
            If(True, Skip(), Skip(), continuation=EmptyEvent())  # type: ignore[arg-type]
        with self.assertRaises(TypeError):
            If(True, Skip(), EmptyEvent())  # type: ignore[arg-type]
        with self.assertRaises(TypeError):
            If(True, Parallel(Skip(), Skip()), Skip())  # type: ignore[arg-type]


    def test_ode_requires_event_reaction_interrupts(self) -> None:
        r"""Verify ODE requires event reaction interrupts."""

        without_interrupt = ODE(
            [("x", 1)],
            True,
            annotation=ODEAnnotation(delay=1),
        )
        self.assertIsInstance(without_interrupt.interrupts, EmptyEvent)
        self.assertIsInstance(without_interrupt.annotation, ODEAnnotation)
        self.assertIsInstance(without_interrupt.continuation, Skip)
        with self.assertRaises(ValueError):
            ODE([("x", 1)], True)
        with self.assertRaises(TypeError):
            ODE(
                [("x", 1)],
                True,
                Skip(),
                annotation=ODEAnnotation(delay=1),
            )  # type: ignore[arg-type]
        with self.assertRaises(TypeError):
            ODE([("x", 1)], True, annotation=True)  # type: ignore[arg-type]
        with self.assertRaisesRegex(TypeError, r"equation 0"):
            ODE([("x", 1, 2)], True, annotation=ODEAnnotation(delay=1))  # type: ignore[list-item]
        with self.assertRaisesRegex(TypeError, r"equations must be an iterable"):
            ODE(None, True, annotation=ODEAnnotation(delay=1))  # type: ignore[arg-type]


    def test_sequence_is_binary_p_composition(self) -> None:
        r"""Verify sequence is binary p composition."""

        node = Sequence(Assign("x", 1), Skip())
        assert_process(self, node)
        with self.assertRaises(TypeError):
            Sequence(Skip())  # type: ignore[call-arg]
        with self.assertRaises(TypeError):
            Sequence(Skip(), Skip(), Skip())  # type: ignore[call-arg]
        with self.assertRaises(TypeError):
            Sequence(EmptyEvent(), Skip())  # type: ignore[arg-type]
        with self.assertRaises(TypeError):
            Sequence(Parallel(Skip(), Skip()), Skip())  # type: ignore[arg-type]
        with self.assertRaises(TypeError):
            Sequence(Skip(), EmptyEvent())  # type: ignore[arg-type]
        for terminal in (
            If(True, Skip(), Skip()),
            InternalChoice(Skip(), Skip()),
            ODE([], True, annotation=ODEAnnotation(delay=1)),
        ):
            with self.subTest(terminal=type(terminal).__name__):
                with self.assertRaisesRegex(ValueError, "owns its common continuation"):
                    Sequence(terminal, Assert(True))

        normalized_if = Sequence.of(
            If(True, Skip(), Skip()),
            Assert(True),
        )
        normalized_ode = Sequence.of(
            ODE([], True, annotation=ODEAnnotation(delay=1)),
            Assert(True),
        )
        self.assertIsInstance(normalized_if, If)
        self.assertIsInstance(normalized_if.continuation, Assert)
        self.assertIsInstance(normalized_ode, ODE)
        self.assertIsInstance(normalized_ode.continuation, Assert)


    def test_internal_choice_is_nary_p_composition(self) -> None:
        r"""Verify internal choice is nary p composition."""

        node = InternalChoice(Skip(), Assign("x", 1), continuation=Assert(True))
        assert_process(self, node)
        self.assertEqual(len(node.branches), 2)
        self.assertIsInstance(node.continuation, Assert)
        defaulted = InternalChoice(Skip(), Skip())
        self.assertIsInstance(defaulted.continuation, Skip)
        with self.assertRaisesRegex(ValueError, "owns its common continuation"):
            Sequence(defaulted, Assert(True))
        normalized = Sequence.of(defaulted, Assert(True))
        self.assertIsInstance(normalized, InternalChoice)
        self.assertIsInstance(normalized.continuation, Assert)
        with self.assertRaises(ValueError):
            InternalChoice(Skip())  # type: ignore[call-arg]
        self.assertEqual(len(InternalChoice(Skip(), Skip(), Skip()).branches), 3)
        with self.assertRaises(TypeError):
            InternalChoice(EmptyEvent(), Skip())  # type: ignore[arg-type]
        with self.assertRaises(TypeError):
            InternalChoice(Skip(), Parallel(Skip(), Skip()))  # type: ignore[arg-type]
        with self.assertRaises(TypeError):
            InternalChoice(Skip(), Skip(), EmptyEvent())  # type: ignore[arg-type]


    def test_mu_binds_one_process_variable_and_one_process_body(self) -> None:
        r"""Verify mu binds one process variable and one process body."""

        node = Mu(
            "X",
            Sequence(InputChannel("c", "x"), Var("X")),
            annotation=RecursionAnnotation("y >= 0"),
        )
        assert_process(self, node)
        with self.assertRaises(ValueError):
            Mu("not a name", Skip())
        with self.assertRaises(ValueError):
            Mu("\u03b1\u03b2", Skip())
        with self.assertRaises(TypeError):
            Mu("X", EmptyEvent())  # type: ignore[arg-type]
        with self.assertRaises(TypeError):
            Mu("X", Parallel(Skip(), Skip()))  # type: ignore[arg-type]
        with self.assertRaises(TypeError):
            Mu("X", Skip(), annotation=True)  # type: ignore[arg-type]


    def test_nary_class_methods_expand_to_canonical_process_trees(self) -> None:
        r"""Verify nary class methods expand to canonical process trees."""

        self.assertIsInstance(Sequence.of(), Skip)
        only = Assign("only", 0)
        self.assertIs(Sequence.of(only), only)
        with self.assertRaises(ValueError):
            InternalChoice.of()
        with self.assertRaises(ValueError):
            InternalChoice.of(only)
        sequential = Sequence.of(Assign("x", 0), Assert(True), Skip())
        choice = InternalChoice.of(
            Assign("x", 0),
            Assign("x", 1),
            Skip(),
            continuation=Assert(True),
        )
        self.assertIsInstance(sequential, Sequence)
        self.assertIsInstance(sequential.second, Sequence)
        self.assertIsInstance(choice, InternalChoice)
        self.assertEqual(len(choice.branches), 3)
        self.assertIsInstance(choice.continuation, Assert)
        assert_process(self, sequential)
        assert_process(self, choice)


    def test_ode_binds_the_automatic_local_clock_name_t(self) -> None:
        r"""Verify ODE binds the automatic local clock name t."""

        first = ODE(
            [("x", "t + 1")],
            "t <= 1",
            annotation=ODEAnnotation(safety="x >= t", delay=1),
        )
        second = ODE([], True, annotation=ODEAnnotation(safety=True, delay=2))

        self.assertEqual(first.get_vars(), {"x"})
        self.assertEqual(first.local_clock.name, "t")
        self.assertEqual(first.local_clock.initial_value, Literal(0))
        self.assertEqual(first.local_clock.derivative, Literal(1))
        self.assertIsNot(first.local_clock, second.local_clock)
        self.assertEqual(
            ODE(
                first.eqs,
                first.constraint,
                first.interrupts,
                annotation=first.annotation,
                continuation=Assert("t >= 0"),
            ).get_vars(),
            {"x", "t"},
        )
        with self.assertRaisesRegex(ValueError, "reserved.*local clock"):
            ODE(
                [("t", 1)],
                True,
                annotation=ODEAnnotation(delay=1),
            )
        with self.assertRaisesRegex(ValueError, "Invalid ODE variable"):
            ODE(
                [("\u03b1\u03b2", 1)],
                True,
                annotation=ODEAnnotation(delay=1),
            )
        assert_process(self, first)


class Section21SystemGrammarTests(unittest.TestCase):
    r"""Tests for Section21 System Grammar."""


    def test_process_is_a_system(self) -> None:
        r"""Verify process is a system."""

        assert_system(self, Assign("x", 1))


    def test_parallel_is_binary_and_recursively_accepts_systems(self) -> None:
        r"""Verify parallel is binary and recursively accepts systems."""

        system = Parallel(
            Assign("x", 1),
            Parallel(OutputChannel("c", 0), Skip()),
        )
        assert_system(self, system)


    def test_parallel_rejects_event_reaction(self) -> None:
        r"""Verify parallel rejects event reaction."""

        with self.assertRaises(TypeError):
            Parallel(EmptyEvent(), Skip())  # type: ignore[arg-type]
        with self.assertRaises(TypeError):
            Parallel(Skip(), EmptyEvent())  # type: ignore[arg-type]


    def test_parallel_class_method_builds_only_binary_system_tree(self) -> None:
        r"""Verify parallel class method builds only binary system tree."""

        with self.assertRaises(ValueError):
            Parallel.of(Skip())
        system = Parallel.of(Skip(), Assign("x", 1), OutputChannel("c", 0))
        self.assertIsInstance(system, Parallel)
        self.assertIsInstance(system.right, Parallel)
        assert_system(self, system)


    def test_parallel_rejects_missing_or_extra_operands(self) -> None:
        r"""Verify parallel rejects missing or extra operands."""

        with self.assertRaises(TypeError):
            Parallel(Skip())  # type: ignore[call-arg]
        with self.assertRaises(TypeError):
            Parallel(Skip(), Skip(), Skip())  # type: ignore[call-arg]


    def test_event_reaction_is_neither_process_nor_system(self) -> None:
        r"""Verify event reaction is neither process nor system."""

        event = EventChoice.of((InputChannel("c", "x"), Skip()))
        self.assertIsInstance(event, EventReaction)
        self.assertNotIsInstance(event, Process)
        self.assertNotIsInstance(event, HCSP)


if __name__ == "__main__":
    unittest.main()
