"""为不可变 TypeTransitionGraph 建立紧凑的 CSR 出边索引。"""

from __future__ import annotations

from array import array
from dataclasses import dataclass

from ...data_structures.type_transition_graph import TypeTransitionGraph


@dataclass(frozen=True, slots=True)
class GraphIndex:
    """按状态编号提供 O(1) 出边区间的压缩稀疏行索引。"""

    graph: TypeTransitionGraph
    offsets: array
    edge_ids: array

    @classmethod
    def build(cls, graph: TypeTransitionGraph) -> GraphIndex:
        """以两次线性扫描建立稳定保持原迁移顺序的 CSR 索引。"""

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
        """返回 ``state_id`` 的出边在 ``edge_ids`` 中的半开区间。"""

        return range(self.offsets[state_id], self.offsets[state_id + 1])
