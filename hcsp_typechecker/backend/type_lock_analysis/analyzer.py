"""以 O(|V|+|E|) 显式图算法判断 Type 图的死锁与活锁自由性。

实现不使用 Python 递归：BFS 同时建立最短可达前缀，显式栈 DFS 在静默
迁移子图中寻找有向环。因而其可承载规模与第三接口生成的显式图相匹配，
不会因用户类型较深而触发 Python 递归上限。
"""

from __future__ import annotations

from array import array
from collections import deque

from ...data_structures.type_lock_analysis import (
    DeadlockWitness,
    LivelockWitness,
    LockFreedomReport,
    TransitionPath,
)
from ...data_structures.type_transition_graph import (
    InfiniteTime,
    SilentTransitionLabel,
    TimedTransitionLabel,
    TypeTransition,
    TypeTransitionGraph,
)
from .graph_index import GraphIndex


class IncompleteTransitionGraphError(ValueError):
    """图含有从初始状态不可达的结点，不能视为完整可达闭包。"""

    def __init__(
        self,
        unreachable_state_ids: tuple[int, ...],
        total_count: int,
    ) -> None:
        """保存不可达状态预览和总数，并构造紧凑错误原因。"""

        self.unreachable_state_ids = unreachable_state_ids
        self.total_count = total_count
        preview = ", ".join(f"S{state_id}" for state_id in unreachable_state_ids)
        super().__init__(
            f"{total_count} graph states are unreachable from the initial state"
            + (f"; first states: {preview}" if preview else "")
        )


def _is_deadlock_edge(transition: TypeTransition) -> bool:
    """实现 Definition 4.5：无限时间迁移且 ready 集非空。"""

    label = transition.label
    return (
        isinstance(label, TimedTransitionLabel)
        and label.duration is InfiniteTime.VALUE
        and bool(label.ready)
    )


def _reconstruct_prefix(
    graph: TypeTransitionGraph,
    parent_edge: array,
    target: int,
) -> TransitionPath:
    """从 BFS 父边数组迭代重建初始状态到 ``target`` 的最短路径。"""

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
    """扫描所有可达边，并记录最短路径树与首条可达死锁边。"""

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
    """由 DFS 树父边和一条返祖边重建非空静默环。"""

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
    """在静默边诱导子图上用显式栈 DFS 寻找一个有向环。"""

    graph = index.graph
    color = bytearray(len(graph.states))  # 0=未见，1=活动栈，2=已完成
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
    """分析一张完整可达 Type 图，并返回死锁/活锁结论与反例见证。"""

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

    return LockFreedomReport(
        reachable_state_count=len(order),
        transition_count=len(graph.transitions),
        deadlock_witness=deadlock_witness,
        livelock_witness=livelock_witness,
    )
