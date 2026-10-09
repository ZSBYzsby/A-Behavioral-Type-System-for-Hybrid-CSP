r"""Analyze explicit graphs in O(|V|+|E|) time with finite counterexample witnesses."""

from __future__ import annotations

from array import array
from collections import deque

from ...data_structures.type_lock_analysis import (
    BottomErrorWitness,
    DeadlockWitness,
    LivelockWitness,
    LockFreedomReport,
    TransitionPath,
)
from ...data_structures.normalized_type_ast import NormalizedBottomType
from ...data_structures.type_transition_graph import (
    InfiniteTime,
    SilentTransitionLabel,
    TimedTransitionLabel,
    TypeTransition,
    TypeTransitionGraph,
)
from .graph_index import GraphIndex


class IncompleteTransitionGraphError(ValueError):
    r"""Unreachable nodes prevent treating the graph as a reachable closure."""

    def __init__(
        self,
        unreachable_state_ids: tuple[int, ...],
        total_count: int,
    ) -> None:
        r"""Store unreachable-state counts and a compact diagnostic preview."""

        self.unreachable_state_ids = unreachable_state_ids
        self.total_count = total_count
        preview = ", ".join(f"S{state_id}" for state_id in unreachable_state_ids)
        super().__init__(
            f"{total_count} graph states are unreachable from the initial state"
            + (f"; first states: {preview}" if preview else "")
        )


def _is_deadlock_edge(transition: TypeTransition) -> bool:
    r"""Definition 4.5: infinite-time transition with a nonempty ready set."""

    label = transition.label
    return (
        isinstance(label, TimedTransitionLabel)
        and label.duration is InfiniteTime.VALUE
        and bool(label.ready)
    )


def _bottom_component_indices(
    graph: TypeTransitionGraph,
    state_id: int,
) -> tuple[int, ...]:
    r"""Find Bottom components at the normalized parallel root."""

    return tuple(
        index
        for index, component in enumerate(graph.states[state_id].type_ast.components)
        if isinstance(component, NormalizedBottomType)
    )


def _reconstruct_prefix(
    graph: TypeTransitionGraph,
    parent_edge: array,
    target: int,
) -> TransitionPath:
    r"""Reconstruct a shortest reachable prefix iteratively from BFS parent edges."""

    reverse_edges: list[TypeTransition] = []
    current = target
    while current != graph.initial_state:
        edge_id = parent_edge[current]
        if edge_id < 0:
            raise RuntimeError("reachable state has no BFS predecessor")
        transition = graph.transitions[edge_id]
        reverse_edges.append(transition)
        current = transition.source
    reverse_edges.reverse()
    return TransitionPath(
        start_state=graph.initial_state,
        transitions=tuple(reverse_edges),
        end_state=target,
    )


def _reachable_bfs(
    index: GraphIndex,
) -> tuple[bytearray, array, tuple[int, ...], int | None]:
    r"""Find reachable states, shortest paths, and the first deadlock edge."""

    graph = index.graph
    state_count = len(graph.states)
    visited = bytearray(state_count)
    parent_edge = array("q", [-1]) * state_count
    queue: deque[int] = deque([graph.initial_state])
    visited[graph.initial_state] = 1
    order: list[int] = []
    first_deadlock_edge: int | None = None

    while queue:
        state_id = queue.popleft()
        order.append(state_id)
        for position in index.edge_range(state_id):
            edge_id = index.edge_ids[position]
            transition = graph.transitions[edge_id]
            if first_deadlock_edge is None and _is_deadlock_edge(transition):
                first_deadlock_edge = edge_id
            target = transition.target
            if not visited[target]:
                visited[target] = 1
                parent_edge[target] = edge_id
                queue.append(target)
    return visited, parent_edge, tuple(order), first_deadlock_edge


def _reconstruct_silent_cycle(
    graph: TypeTransitionGraph,
    parent_edge: array,
    current: int,
    ancestor: int,
    closing_edge_id: int,
) -> TransitionPath:
    r"""Reconstruct a nonempty silent cycle from DFS parent edges and a back edge."""

    reverse_tree_edges: list[TypeTransition] = []
    cursor = current
    while cursor != ancestor:
        edge_id = parent_edge[cursor]
        if edge_id < 0:
            raise RuntimeError("active DFS state has no path to its ancestor")
        transition = graph.transitions[edge_id]
        reverse_tree_edges.append(transition)
        cursor = transition.source
    reverse_tree_edges.reverse()
    cycle_edges = tuple(reverse_tree_edges) + (graph.transitions[closing_edge_id],)
    return TransitionPath(ancestor, cycle_edges, ancestor)


def _find_silent_cycle(
    index: GraphIndex,
    reachable_order: tuple[int, ...],
) -> tuple[int, TransitionPath] | None:
    r"""Find a directed cycle in the silent-edge subgraph using iterative DFS."""

    graph = index.graph
    # DFS colors: 0 = unseen, 1 = active, 2 = complete.
    color = bytearray(len(graph.states))
    parent_edge = array("q", [-1]) * len(graph.states)

    for root in reachable_order:
        if color[root]:
            continue
        color[root] = 1
        state_stack: list[int] = [root]
        position_stack: list[int] = [index.offsets[root]]

        while state_stack:
            current = state_stack[-1]
            position = position_stack[-1]
            end = index.offsets[current + 1]
            if position >= end:
                color[current] = 2
                state_stack.pop()
                position_stack.pop()
                continue

            position_stack[-1] = position + 1
            edge_id = index.edge_ids[position]
            transition = graph.transitions[edge_id]
            if not isinstance(transition.label, SilentTransitionLabel):
                continue
            target = transition.target
            if color[target] == 0:
                color[target] = 1
                parent_edge[target] = edge_id
                state_stack.append(target)
                position_stack.append(index.offsets[target])
                continue
            if color[target] == 1:
                return target, _reconstruct_silent_cycle(
                    graph,
                    parent_edge,
                    current,
                    target,
                    edge_id,
                )
    return None


def analyze_lock_freedom(graph: TypeTransitionGraph) -> LockFreedomReport:
    r"""Analyze the complete graph and return lock and Bottom-error witnesses."""

    if not isinstance(graph, TypeTransitionGraph):
        raise TypeError("graph must be a TypeTransitionGraph")

    index = GraphIndex.build(graph)
    visited, parent_edge, order, deadlock_edge_id = _reachable_bfs(index)
    if len(order) != len(graph.states):
        unreachable = tuple(
            state_id for state_id, seen in enumerate(visited) if not seen
        )
        raise IncompleteTransitionGraphError(unreachable[:16], len(unreachable))

    deadlock_witness = None
    if deadlock_edge_id is not None:
        infinite_wait = graph.transitions[deadlock_edge_id]
        deadlock_witness = DeadlockWitness(
            prefix=_reconstruct_prefix(graph, parent_edge, infinite_wait.source),
            infinite_wait=infinite_wait,
        )

    livelock_witness = None
    silent_cycle = _find_silent_cycle(index, order)
    if silent_cycle is not None:
        entry, cycle = silent_cycle
        livelock_witness = LivelockWitness(
            prefix=_reconstruct_prefix(graph, parent_edge, entry),
            cycle=cycle,
        )

    bottom_error_witness = None
    for state_id in order:
        component_indices = _bottom_component_indices(graph, state_id)
        if not component_indices:
            continue
        bottom_error_witness = BottomErrorWitness(
            prefix=_reconstruct_prefix(graph, parent_edge, state_id),
            component_indices=component_indices,
        )
        break

    return LockFreedomReport(
        reachable_state_count=len(order),
        transition_count=len(graph.transitions),
        deadlock_witness=deadlock_witness,
        livelock_witness=livelock_witness,
        bottom_error_witness=bottom_error_witness,
    )
