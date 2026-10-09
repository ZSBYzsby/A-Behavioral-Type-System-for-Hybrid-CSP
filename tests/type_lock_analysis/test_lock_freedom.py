r"""Regression tests for lock freedom. Paper reference: Table 3, Section 4.4, Definition 4.5."""

from __future__ import annotations

from io import StringIO
import unittest

from hcsp_typechecker import (
    HCSPTypeLockAnalysisError,
    LockFreedomReport,
    TypeLockAnalysisErrorKind,
    analyze_type_lock_freedom,
    build_type_transition_graph,
)
from hcsp_typechecker.backend.type_lock_analysis import analyze_lock_freedom
from hcsp_typechecker.backend.type_operational_semantics import (
    build_type_transition_graph as build_graph_internal,
)
from hcsp_typechecker.data_structures.normalized_type_ast import (
    NormalizedConfigurationType,
    NormalizedEmptyType,
)
from hcsp_typechecker.data_structures.type_ast import (
    BottomType,
    EmptyType,
    FiniteDelayType,
    InfiniteDelayType,
    InputType,
    NoInterruptType,
    OutputType,
    ParallelType,
)
from hcsp_typechecker.data_structures.type_transition_graph import (
    CommunicationDirection,
    InfiniteTime,
    ReadyAction,
    SilentTransitionLabel,
    Table3Rule,
    TimedTransitionLabel,
    TransitionDerivation,
    TypeState,
    TypeTransition,
    TypeTransitionGraph,
)


_NORMALIZED_EMPTY = NormalizedConfigurationType((NormalizedEmptyType(),))
_TAU_DERIVATION = TransitionDerivation(Table3Rule.INTERNAL_CHOICE)
_TIME_DERIVATION = TransitionDerivation(Table3Rule.PARALLEL_TIME)


def _manual_graph(
    state_count: int,
    edges: tuple[TypeTransition, ...],
) -> TypeTransitionGraph:
    r"""Build synthetic graphs with distinct states to isolate graph algorithms."""

    return TypeTransitionGraph(
        initial_state=0,
        states=tuple(
            TypeState(state_id, _NORMALIZED_EMPTY)
            for state_id in range(state_count)
        ),
        transitions=edges,
    )


class LockFreedomSemanticsTests(unittest.TestCase):
    r"""Tests for Lock Freedom Semantics."""


    def test_infinite_wait_with_ready_action_is_deadlock(self) -> None:
        r"""Verify infinite wait with ready action is deadlock."""

        graph = build_graph_internal(
            InfiniteDelayType(InputType("ch", EmptyType()))
        )

        report = analyze_lock_freedom(graph)

        self.assertFalse(report.deadlock_free)
        self.assertTrue(report.livelock_free)
        self.assertFalse(report.lock_free)
        witness = report.deadlock_witness
        self.assertIsNotNone(witness)
        assert witness is not None
        self.assertEqual(witness.prefix.transitions, ())
        self.assertIs(witness.infinite_wait, graph.transitions[0])


    def test_idle_infinity_and_empty_terminal_are_lock_free(self) -> None:
        r"""Verify idle infinity and empty terminal are lock free."""

        for type_ast in (InfiniteDelayType(NoInterruptType()), EmptyType()):
            with self.subTest(type_ast=type(type_ast).__name__):
                report = analyze_lock_freedom(build_graph_internal(type_ast))
                self.assertTrue(report.deadlock_free)
                self.assertTrue(report.livelock_free)
                self.assertTrue(report.lock_free)
                self.assertTrue(report.error_free)
                self.assertTrue(report.behavior_correct)


    def test_bottom_terminal_is_reported_separately_from_lock_freedom(self) -> None:
        r"""Verify bottom terminal is reported separately from lock freedom."""

        report = analyze_lock_freedom(build_graph_internal(BottomType()))

        self.assertTrue(report.deadlock_free)
        self.assertTrue(report.livelock_free)
        self.assertTrue(report.lock_free)
        self.assertFalse(report.error_free)
        self.assertFalse(report.behavior_correct)
        witness = report.bottom_error_witness
        self.assertIsNotNone(witness)
        assert witness is not None
        self.assertEqual(witness.prefix.state_ids, (0,))
        self.assertEqual(witness.component_indices, (0,))


    def test_reachable_bottom_has_a_shortest_error_witness(self) -> None:
        r"""Verify reachable bottom has a shortest error witness."""

        receiver = InfiniteDelayType(InputType("ch", BottomType()))
        unmatched = analyze_lock_freedom(build_graph_internal(receiver))
        self.assertTrue(unmatched.error_free)

        sender = InfiniteDelayType(
            OutputType(
                "ch",
                FiniteDelayType(0, NoInterruptType(), EmptyType()),
            )
        )
        graph = build_graph_internal(ParallelType((receiver, sender)))
        report = analyze_lock_freedom(graph)

        self.assertTrue(report.lock_free)
        self.assertFalse(report.error_free)
        self.assertFalse(report.behavior_correct)
        witness = report.bottom_error_witness
        self.assertIsNotNone(witness)
        assert witness is not None
        self.assertEqual(len(witness.prefix.transitions), 1)
        self.assertEqual(witness.prefix.end_state, graph.transitions[0].target)
        self.assertEqual(witness.component_indices, (0,))

        output = StringIO()
        public_report = analyze_type_lock_freedom(
            graph,
            output="full",
            stream=output,
        )
        self.assertEqual(public_report, report)
        self.assertIn('Bottom error witness', output.getvalue())
        self.assertIn("bottom_error_witness", output.getvalue())
        self.assertIn("bottom_components = (0,)", output.getvalue())


    def test_silent_cycle_with_exit_is_livelock(self) -> None:
        r"""Verify silent cycle with exit is livelock."""

        graph = _manual_graph(
            3,
            (
                TypeTransition(0, 1, TimedTransitionLabel(1, ()), (_TIME_DERIVATION,)),
                TypeTransition(1, 1, SilentTransitionLabel(), (_TAU_DERIVATION,)),
                TypeTransition(1, 2, SilentTransitionLabel(), (_TAU_DERIVATION,)),
            ),
        )

        report = analyze_lock_freedom(graph)

        self.assertTrue(report.deadlock_free)
        self.assertFalse(report.livelock_free)
        witness = report.livelock_witness
        self.assertIsNotNone(witness)
        assert witness is not None
        self.assertEqual(witness.prefix.state_ids, (0, 1))
        self.assertEqual(witness.cycle.state_ids, (1, 1))


    def test_timed_cycle_is_not_livelock(self) -> None:
        r"""Verify timed cycle is not livelock."""

        graph = _manual_graph(
            2,
            (
                TypeTransition(0, 1, TimedTransitionLabel(1, ()), (_TIME_DERIVATION,)),
                TypeTransition(1, 0, TimedTransitionLabel(1, ()), (_TIME_DERIVATION,)),
            ),
        )

        report = analyze_lock_freedom(graph)

        self.assertTrue(report.lock_free)
        self.assertIsNone(report.livelock_witness)


    def test_deadlock_and_multistate_livelock_witnesses_coexist(self) -> None:
        r"""Verify deadlock and multistate livelock witnesses coexist."""

        ready = (ReadyAction("ch", CommunicationDirection.INPUT),)
        graph = _manual_graph(
            3,
            (
                TypeTransition(0, 1, SilentTransitionLabel(), (_TAU_DERIVATION,)),
                TypeTransition(
                    1,
                    1,
                    TimedTransitionLabel(InfiniteTime.VALUE, ready),
                    (_TIME_DERIVATION,),
                ),
                TypeTransition(1, 2, SilentTransitionLabel(), (_TAU_DERIVATION,)),
                TypeTransition(2, 1, SilentTransitionLabel(), (_TAU_DERIVATION,)),
            ),
        )

        report = analyze_lock_freedom(graph)

        self.assertFalse(report.deadlock_free)
        self.assertFalse(report.livelock_free)
        assert report.deadlock_witness is not None
        assert report.livelock_witness is not None
        self.assertEqual(report.deadlock_witness.prefix.state_ids, (0, 1))
        self.assertEqual(report.livelock_witness.prefix.state_ids, (0, 1))
        self.assertEqual(report.livelock_witness.cycle.state_ids, (1, 2, 1))


    def test_unreachable_state_is_incomplete_graph_error(self) -> None:
        r"""Verify unreachable state is incomplete graph error."""

        graph = _manual_graph(2, ())

        with self.assertRaises(HCSPTypeLockAnalysisError) as raised:
            analyze_type_lock_freedom(graph)

        self.assertIs(
            raised.exception.kind,
            TypeLockAnalysisErrorKind.INCOMPLETE_GRAPH,
        )
        self.assertEqual(raised.exception.phase, "reachability-validation")


    def test_non_graph_input_has_structured_public_error(self) -> None:
        r"""Verify non graph input has structured public error."""

        output = StringIO()

        with self.assertRaises(HCSPTypeLockAnalysisError) as raised:
            analyze_type_lock_freedom("not a graph", output="result", stream=output)

        error = raised.exception
        self.assertIs(error.kind, TypeLockAnalysisErrorKind.INVALID_GRAPH)
        self.assertEqual(error.phase, "input-validation")
        self.assertIsNone(error.state_count)
        self.assertIn("invalid-graph", output.getvalue())
        self.assertIn('no partial property result is returned', output.getvalue())


    def test_public_output_modes_preserve_the_report(self) -> None:
        r"""Verify public output modes preserve the report."""

        graph = build_type_transition_graph(
            InfiniteDelayType(InputType("ch", EmptyType()))
        )
        silent_stream = StringIO()
        result_stream = StringIO()
        full_stream = StringIO()

        silent = analyze_type_lock_freedom(graph, output="none", stream=silent_stream)
        result = analyze_type_lock_freedom(graph, output="result", stream=result_stream)
        full = analyze_type_lock_freedom(graph, output="full", stream=full_stream)

        self.assertIsInstance(silent, LockFreedomReport)
        self.assertEqual(silent, result)
        self.assertEqual(result, full)
        self.assertEqual(silent_stream.getvalue(), "")
        self.assertIn('Deadlock-free : no', result_stream.getvalue())
        self.assertIn('Error-free : yes', result_stream.getvalue())
        self.assertIn('Behavior correct : no', result_stream.getvalue())
        self.assertNotIn("witness_states", result_stream.getvalue())
        self.assertIn("deadlock_witness", full_stream.getvalue())
        self.assertIn("witness_states", full_stream.getvalue())
        self.assertIn("P-unrhd-prime", full_stream.getvalue())


class LockFreedomScalabilityTests(unittest.TestCase):
    r"""Tests for Lock Freedom Scalability."""


    def test_long_chain_and_cycle_do_not_use_python_recursion(self) -> None:
        r"""Verify long chain and cycle do not use python recursion."""

        state_count = 12_000
        edges = tuple(
            TypeTransition(
                state_id,
                state_id + 1,
                SilentTransitionLabel(),
                (_TAU_DERIVATION,),
            )
            for state_id in range(state_count - 1)
        ) + (
            TypeTransition(
                state_count - 1,
                state_count - 1,
                SilentTransitionLabel(),
                (_TAU_DERIVATION,),
            ),
        )
        graph = _manual_graph(state_count, edges)

        report = analyze_lock_freedom(graph)

        self.assertEqual(report.reachable_state_count, state_count)
        self.assertFalse(report.livelock_free)
        assert report.livelock_witness is not None
        self.assertEqual(
            len(report.livelock_witness.prefix.transitions),
            state_count - 1,
        )
        self.assertEqual(len(report.livelock_witness.cycle.transitions), 1)


if __name__ == "__main__":
    unittest.main()
