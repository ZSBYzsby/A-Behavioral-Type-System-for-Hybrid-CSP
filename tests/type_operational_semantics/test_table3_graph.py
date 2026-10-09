r"""Regression tests for table3 graph. Paper reference: Table 3, Section 4.4."""

from __future__ import annotations

from fractions import Fraction
import unittest

from hcsp_typechecker.backend.type_operational_semantics import (
    TypeTransitionGraphSizeError,
    build_type_transition_graph,
    derive_one_step,
    equi_recursive_state_key,
    normalized_type_from_state_key,
)
from hcsp_typechecker.data_structures.normalized_type_ast import (
    NormalizedBottomType,
    NormalizedExternalChoiceType,
    NormalizedInfiniteDelayType,
    NormalizedInternalChoiceType,
    NormalizedMuType,
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
from hcsp_typechecker.data_structures.type_transition_graph import (
    CommunicationDirection,
    InfiniteTime,
    ReadyAction,
    SilentTransitionLabel,
    Table3Rule,
    TimedTransitionLabel,
)


class Table3OneStepTests(unittest.TestCase):
    r"""Tests for Table3 One Step."""


    def test_internal_choice_enumerates_every_non_bottom_branch(self) -> None:
        r"""Verify internal choice enumerates every non bottom branch."""

        branches = (
            FiniteDelayType(1, NoInterruptType(), EmptyType()),
            FiniteDelayType(2, NoInterruptType(), EmptyType()),
            FiniteDelayType(3, NoInterruptType(), EmptyType()),
            BottomType(),
        )

        transitions = derive_one_step(
            equi_recursive_state_key(
                normalize_type_ast(InternalChoiceType(branches))
            )
        )

        self.assertEqual(len(transitions), 3)
        self.assertTrue(
            all(isinstance(item.label, SilentTransitionLabel) for item in transitions)
        )
        self.assertTrue(
            all(
                item.derivation.rule is Table3Rule.INTERNAL_CHOICE
                for item in transitions
            )
        )


    def test_all_matching_component_pairs_are_retained_as_witnesses(self) -> None:
        r"""Verify all matching component pairs are retained as witnesses."""

        sender = InfiniteDelayType(OutputType("ch", EmptyType()))
        receiver = InfiniteDelayType(InputType("ch", EmptyType()))
        graph = build_type_transition_graph(
            ParallelType((sender, receiver, receiver))
        )

        initial_edges = graph.outgoing(graph.initial_state)
        communication_edges = tuple(
            edge
            for edge in initial_edges
            if isinstance(edge.label, SilentTransitionLabel)
        )
        self.assertEqual(len(communication_edges), 1)
        self.assertEqual(len(communication_edges[0].derivations), 2)
        self.assertTrue(
            all(
                witness.rule is Table3Rule.COMMUNICATION
                for witness in communication_edges[0].derivations
            )
        )
        self.assertEqual(
            {
                witness.component_indices
                for witness in communication_edges[0].derivations
            },
            {(0, 2), (1, 2)},
        )
        self.assertTrue(
            all(
                witness.branch_indices == (0, 0)
                for witness in communication_edges[0].derivations
            )
        )


    def test_zero_deadline_keeps_timeout_and_communication(self) -> None:
        r"""Verify zero deadline keeps timeout and communication."""

        receiver = FiniteDelayType(
            0,
            InputType("ch", EmptyType()),
            InfiniteDelayType(NoInterruptType()),
        )
        sender = InfiniteDelayType(OutputType("ch", EmptyType()))

        transitions = derive_one_step(
            equi_recursive_state_key(
                normalize_type_ast(ParallelType((receiver, sender)))
            )
        )

        self.assertEqual(len(transitions), 2)
        rules = {item.derivation.rule for item in transitions}
        self.assertEqual(
            rules,
            {Table3Rule.TIMEOUT, Table3Rule.COMMUNICATION},
        )


    def test_zero_deadline_with_bottom_cannot_timeout(self) -> None:
        r"""Verify zero deadline with bottom cannot timeout."""

        value = FiniteDelayType(0, NoInterruptType(), BottomType())

        transitions = derive_one_step(
            equi_recursive_state_key(normalize_type_ast(value))
        )

        self.assertEqual(transitions, ())


    def test_zero_deadline_bottom_keeps_only_available_communication(self) -> None:
        r"""Verify zero deadline bottom keeps only available communication."""

        receiver = FiniteDelayType(
            0,
            InputType("ch", EmptyType()),
            BottomType(),
        )
        sender = InfiniteDelayType(OutputType("ch", EmptyType()))

        transitions = derive_one_step(
            equi_recursive_state_key(
                normalize_type_ast(ParallelType((receiver, sender)))
            )
        )

        self.assertEqual(len(transitions), 1)
        self.assertEqual(
            transitions[0].derivation.rule,
            Table3Rule.COMMUNICATION,
        )


    def test_bottom_component_stops_the_entire_configuration(self) -> None:
        r"""Verify bottom component stops the entire configuration."""

        selectable = InternalChoiceType(
            (
                FiniteDelayType(1, NoInterruptType(), EmptyType()),
                InfiniteDelayType(NoInterruptType()),
            )
        )
        sender = InfiniteDelayType(OutputType("ch", EmptyType()))
        receiver = InfiniteDelayType(InputType("ch", EmptyType()))
        waiting = FiniteDelayType(2, NoInterruptType(), EmptyType())
        cases = (
            ParallelType((BottomType(), selectable)),
            ParallelType((BottomType(), sender, receiver)),
            ParallelType((BottomType(), waiting)),
        )

        for value in cases:
            with self.subTest(value=value):
                transitions = derive_one_step(
                    equi_recursive_state_key(normalize_type_ast(value))
                )
                self.assertEqual(transitions, ())


    def test_empty_component_does_not_stop_other_components(self) -> None:
        r"""Verify empty component does not stop other components."""

        value = ParallelType(
            (
                EmptyType(),
                FiniteDelayType(0, NoInterruptType(), EmptyType()),
            )
        )
        transitions = derive_one_step(
            equi_recursive_state_key(normalize_type_ast(value))
        )

        self.assertEqual(len(transitions), 1)
        self.assertEqual(transitions[0].derivation.rule, Table3Rule.TIMEOUT)


    def test_parallel_time_advances_to_the_earliest_deadline(self) -> None:
        r"""Verify parallel time advances to the earliest deadline."""

        left = FiniteDelayType(2, InputType("left", EmptyType()), EmptyType())
        right = FiniteDelayType(5, OutputType("right", EmptyType()), EmptyType())

        transitions = derive_one_step(
            equi_recursive_state_key(
                normalize_type_ast(ParallelType((left, right)))
            )
        )

        self.assertEqual(len(transitions), 1)
        transition = transitions[0]
        self.assertIsInstance(transition.label, TimedTransitionLabel)
        self.assertEqual(transition.label.duration, Fraction(2))
        self.assertEqual(
            transition.label.ready,
            frozenset(
                {
                    ReadyAction("left", CommunicationDirection.INPUT),
                    ReadyAction("right", CommunicationDirection.OUTPUT),
                }
            ),
        )
        target_ast = normalized_type_from_state_key(transition.target)
        durations = tuple(
            getattr(component, "duration", None)
            for component in target_ast.components
        )
        self.assertEqual(durations, (Fraction(0), Fraction(3)))


    def test_complementary_ready_actions_block_time(self) -> None:
        r"""Verify complementary ready actions block time."""

        left = FiniteDelayType(2, InputType("ch", EmptyType()), EmptyType())
        right = FiniteDelayType(5, OutputType("ch", EmptyType()), EmptyType())

        transitions = derive_one_step(
            equi_recursive_state_key(
                normalize_type_ast(ParallelType((left, right)))
            )
        )

        self.assertEqual(len(transitions), 1)
        self.assertIsInstance(transitions[0].label, SilentTransitionLabel)
        self.assertEqual(
            transitions[0].derivation.rule,
            Table3Rule.COMMUNICATION,
        )


class TypeTransitionGraphTests(unittest.TestCase):
    r"""Tests for Type Transition Graph."""


    def test_infinite_wait_is_an_infinity_self_loop(self) -> None:
        r"""Verify infinite wait is an infinity self loop."""

        value = InfiniteDelayType(InputType("ch", EmptyType()))

        graph = build_type_transition_graph(value)

        self.assertEqual(len(graph.states), 1)
        self.assertEqual(len(graph.transitions), 1)
        edge = graph.transitions[0]
        self.assertEqual((edge.source, edge.target), (0, 0))
        self.assertIsInstance(edge.label, TimedTransitionLabel)
        self.assertIs(edge.label.duration, InfiniteTime.VALUE)


    def test_guarded_recursion_builds_a_finite_graph(self) -> None:
        r"""Verify guarded recursion builds a finite graph."""

        recursive = MuType(
            "t",
            InfiniteDelayType(InputType("ch", TypeVar("t"))),
        )
        sender = InfiniteDelayType(OutputType("ch", EmptyType()))

        graph = build_type_transition_graph(ParallelType((recursive, sender)))

        self.assertLessEqual(len(graph.states), 3)
        self.assertTrue(
            any(
                witness.rule is Table3Rule.COMMUNICATION
                for edge in graph.transitions
                for witness in edge.derivations
            )
        )


    def test_equi_recursive_quotient_removes_unfold_only_states(self) -> None:
        r"""Verify equi recursive quotient removes unfold only states."""

        server = MuType(
            "server",
            InfiniteDelayType(InputType("request", TypeVar("server"))),
        )
        client = InfiniteDelayType(OutputType("request", EmptyType()))

        graph = build_type_transition_graph(
            ParallelType((server, client, client))
        )

        self.assertEqual(len(graph.states), 3)
        self.assertEqual(len(graph.transitions), 3)
        displayed_keys = tuple(
            equi_recursive_state_key(state.type_ast) for state in graph.states
        )
        self.assertEqual(len(set(displayed_keys)), len(graph.states))
        terminal_edges = graph.outgoing(2)
        self.assertEqual(len(terminal_edges), 1)
        self.assertEqual(
            (terminal_edges[0].source, terminal_edges[0].target),
            (2, 2),
        )
        self.assertEqual(
            terminal_edges[0].derivations[0].rule,
            Table3Rule.DELAY,
        )


    def test_table3_is_computed_on_the_regular_tree_equivalence_class(self) -> None:
        r"""Verify table3 is computed on the regular tree equivalence class."""

        loop = MuType(
            "loop",
            InfiniteDelayType(InputType("ch", TypeVar("loop"))),
        )
        unfolded = InfiniteDelayType(InputType("ch", loop))
        choice = InternalChoiceType((loop, unfolded))
        sender = InfiniteDelayType(OutputType("ch", EmptyType()))

        loop_graph = build_type_transition_graph(ParallelType((loop, sender)))
        choice_graph = build_type_transition_graph(ParallelType((choice, sender)))

        self.assertEqual(loop_graph.states, choice_graph.states)
        self.assertEqual(loop_graph.transitions, choice_graph.transitions)


    def test_internal_choice_evidence_indexes_visible_branches(self) -> None:
        r"""Verify internal choice evidence indexes visible branches."""

        recursive = MuType(
            "t",
            FiniteDelayType(
                1,
                InputType("ch", TypeVar("t")),
                BottomType(),
            ),
        )
        value = InternalChoiceType(
            (recursive, InfiniteDelayType(NoInterruptType()))
        )

        graph = build_type_transition_graph(value)
        source = graph.states[0].type_ast.components[0]

        self.assertIsInstance(source, NormalizedInternalChoiceType)
        assert isinstance(source, NormalizedInternalChoiceType)
        self.assertIsInstance(source.branches[0], NormalizedInfiniteDelayType)
        self.assertIsInstance(source.branches[1], NormalizedMuType)
        outgoing = tuple(
            edge for edge in graph.transitions if edge.source == 0
        )
        for edge in outgoing:
            target = graph.states[edge.target].type_ast.components[0]
            branch_index = edge.derivations[0].branch_indices[0]
            if isinstance(target, NormalizedInfiniteDelayType):
                self.assertEqual(branch_index, 0)
            elif isinstance(target, NormalizedMuType):
                self.assertEqual(branch_index, 1)
            else:  # pragma: no cover - failure message for a broken target shape
                self.fail(f"Unexpected internal-choice target: {target!r}")


    def test_local_evidence_indexes_visible_parallel_component(self) -> None:
        r"""Verify local evidence indexes visible parallel component."""

        choice = InternalChoiceType(
            (
                FiniteDelayType(1, NoInterruptType(), EmptyType()),
                InfiniteDelayType(NoInterruptType()),
            )
        )
        other = FiniteDelayType(2, NoInterruptType(), EmptyType())

        graph = build_type_transition_graph(ParallelType((other, choice)))
        source = graph.states[0].type_ast

        self.assertIsInstance(source.components[0], NormalizedInternalChoiceType)
        choice_edges = tuple(
            edge
            for edge in graph.transitions
            if edge.source == 0
            and edge.derivations[0].rule is Table3Rule.INTERNAL_CHOICE
        )
        self.assertEqual(len(choice_edges), 2)
        self.assertTrue(
            all(
                edge.derivations[0].component_indices == (0,)
                for edge in choice_edges
            )
        )


    def test_communication_evidence_indexes_visible_interrupt_branches(self) -> None:
        r"""Verify communication evidence indexes visible interrupt branches."""

        recursive = MuType(
            "t",
            FiniteDelayType(
                1,
                InputType("again", TypeVar("t")),
                BottomType(),
            ),
        )
        receiver = InfiniteDelayType(
            ExternalChoiceType(
                (
                    InputType("ch", recursive),
                    InputType("ch", InfiniteDelayType(NoInterruptType())),
                )
            )
        )
        sender = InfiniteDelayType(OutputType("ch", EmptyType()))

        graph = build_type_transition_graph(ParallelType((receiver, sender)))
        source = graph.states[0].type_ast
        receiver_index = next(
            index
            for index, component in enumerate(source.components)
            if isinstance(component, NormalizedInfiniteDelayType)
            and isinstance(component.interrupts, NormalizedExternalChoiceType)
        )
        receiver_component = source.components[receiver_index]
        assert isinstance(receiver_component, NormalizedInfiniteDelayType)
        assert isinstance(
            receiver_component.interrupts,
            NormalizedExternalChoiceType,
        )
        communication_edges = tuple(
            edge
            for edge in graph.transitions
            if edge.source == 0
            and edge.derivations[0].rule is Table3Rule.COMMUNICATION
        )

        self.assertEqual(len(communication_edges), 2)
        for edge in communication_edges:
            witness = edge.derivations[0]
            participant = witness.component_indices.index(receiver_index)
            branch_index = witness.branch_indices[participant]
            target = graph.states[edge.target].type_ast.components[0]
            if isinstance(target, NormalizedInfiniteDelayType):
                self.assertEqual(branch_index, 0)
            elif isinstance(target, NormalizedMuType):
                self.assertEqual(branch_index, 1)
            else:  # pragma: no cover - failure message for a broken target shape
                self.fail(f"Unexpected communication target: {target!r}")


    def test_reachable_bottom_configuration_is_not_expanded(self) -> None:
        r"""Verify reachable bottom configuration is not expanded."""

        receiver = InfiniteDelayType(InputType("ch", BottomType()))
        sender = InfiniteDelayType(
            OutputType(
                "ch",
                FiniteDelayType(0, NoInterruptType(), EmptyType()),
            )
        )

        graph = build_type_transition_graph(ParallelType((receiver, sender)))

        self.assertEqual(len(graph.states), 2)
        self.assertEqual(len(graph.transitions), 1)
        target_id = graph.transitions[0].target
        self.assertTrue(
            any(
                isinstance(component, NormalizedBottomType)
                for component in graph.states[target_id].type_ast.components
            )
        )
        self.assertEqual(graph.outgoing(target_id), ())


    def test_state_limit_aborts_without_returning_a_partial_graph(self) -> None:
        r"""Verify state limit aborts without returning a partial graph."""

        value = ParallelType(
            (
                FiniteDelayType(2, NoInterruptType(), EmptyType()),
                FiniteDelayType(5, NoInterruptType(), EmptyType()),
            )
        )

        with self.assertRaises(TypeTransitionGraphSizeError) as caught:
            build_type_transition_graph(value, max_states=2)

        self.assertEqual(caught.exception.limit_name, "max_states")
        self.assertEqual(caught.exception.limit, 2)
        self.assertIn("no partial graph was returned", str(caught.exception))


    def test_transition_limit_aborts_without_returning_a_partial_graph(self) -> None:
        r"""Verify transition limit aborts without returning a partial graph."""

        value = InternalChoiceType(
            (
                FiniteDelayType(1, NoInterruptType(), EmptyType()),
                FiniteDelayType(2, NoInterruptType(), EmptyType()),
                FiniteDelayType(3, NoInterruptType(), EmptyType()),
            )
        )

        with self.assertRaises(TypeTransitionGraphSizeError) as caught:
            build_type_transition_graph(value, max_transitions=1)

        self.assertEqual(caught.exception.limit_name, "max_transitions")
        self.assertEqual(caught.exception.limit, 1)
        self.assertIn("no partial graph was returned", str(caught.exception))


if __name__ == "__main__":
    unittest.main()
