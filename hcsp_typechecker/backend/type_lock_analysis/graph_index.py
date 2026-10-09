r"""Build a compact CSR outgoing-edge index for an immutable graph."""

from __future__ import annotations

from array import array
from dataclasses import dataclass

from ...data_structures.type_transition_graph import TypeTransitionGraph


@dataclass(frozen=True, slots=True)
class GraphIndex:
    r"""Provide constant-time outgoing-edge ranges by state identifier."""

    graph: TypeTransitionGraph
    offsets: array
    edge_ids: array

    @classmethod
    def build(cls, graph: TypeTransitionGraph) -> GraphIndex:
        r"""Build a CSR index in two linear scans, preserving transition order."""

        state_count = len(graph.states)
        degrees = array("Q", [0]) * state_count
        for transition in graph.transitions:
            degrees[transition.source] += 1

        offsets = array("Q", [0]) * (state_count + 1)
        for state_id in range(state_count):
            offsets[state_id + 1] = offsets[state_id] + degrees[state_id]

        edge_ids = array("Q", [0]) * len(graph.transitions)
        cursors = list(offsets[:-1])
        for edge_id, transition in enumerate(graph.transitions):
            position = cursors[transition.source]
            edge_ids[position] = edge_id
            cursors[transition.source] += 1
        return cls(graph=graph, offsets=offsets, edge_ids=edge_ids)

    def edge_range(self, state_id: int) -> range:
        r"""Return the half-open outgoing-edge range for a state."""

        return range(self.offsets[state_id], self.offsets[state_id + 1])
