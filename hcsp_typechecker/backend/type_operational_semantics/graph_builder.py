"""把正式 Type AST 编译成循环项图并穷尽 Table 3 可达状态。

图遍历以 ``EquiRecursiveStateKey`` 为真实状态，规范 Type AST 只作为确定性展示
代表。每个后继在入队前再次裁剪和最小化；相同源、标签和目标合并成一条边，同时
累积不同规则证据。状态或边达到调用者上限时整体失败，不返回部分闭包。
"""

from __future__ import annotations

from collections import deque

from ...data_structures.normalized_type_ast import (
    NormalizedConfigurationType,
    normalize_type_ast,
)
from ...data_structures.type_ast import ConfigurationType
from ...data_structures.type_transition_graph import (
    TransitionDerivation,
    TransitionLabel,
    TypeState,
    TypeTransition,
    TypeTransitionGraph,
)
from .regular_tree import (
    equi_recursive_state_key,
    normalized_type_from_state_key,
)
from .table3 import derive_one_step


class TypeTransitionGraphSizeError(RuntimeError):
    """状态图达到用户指定规模上限时抛出的完整构造失败。"""

    def __init__(self, limit_name: str, limit: int) -> None:
        """保存触发的上限名称和值，并说明不会返回部分状态图。"""

        self.limit_name = limit_name
        self.limit = limit
        super().__init__(
            f"Type transition graph exceeded {limit_name}={limit}; "
            "no partial graph was returned"
        )


def build_type_transition_graph(
    initial_type: ConfigurationType,
    *,
    max_states: int | None = None,
    max_transitions: int | None = None,
) -> TypeTransitionGraph:
    """规范化输入 Type AST，并以 BFS 构造完整关键-deadline可达图。

    ``max_states`` 与 ``max_transitions`` 为可选严格正整数；上限包括初态和去重后的
    有向边。触及上限会抛出 :class:`TypeTransitionGraphSizeError`。
    """

    _validate_limit("max_states", max_states)
    _validate_limit("max_transitions", max_transitions)
    initial = normalize_type_ast(initial_type)
    return _build_normalized_graph(
        initial,
        max_states=max_states,
        max_transitions=max_transitions,
    )


def _build_normalized_graph(
    initial: NormalizedConfigurationType,
    *,
    max_states: int | None,
    max_transitions: int | None,
) -> TypeTransitionGraph:
    """以最小循环项图作为状态本体，合并同边证据并冻结可达图。

    Table 3 直接作用于 ``state_keys`` 中的项图。``state_values`` 仅保存由该规范
    项图确定性重建的可读 AST 代表，因此展示形式不会反过来影响状态判重或出边。
    同一 ``(source, label, target)`` 的多份推导只合并边，不合并证据。
    """

    initial_key = equi_recursive_state_key(initial)
    state_ids = {initial_key: 0}
    state_keys = [initial_key]
    state_values: list[NormalizedConfigurationType] = [
        normalized_type_from_state_key(initial_key)
    ]
    pending: deque[int] = deque((0,))
    edge_derivations: dict[
        tuple[int, TransitionLabel, int],
        list[TransitionDerivation],
    ] = {}
    while pending:
        source_id = pending.popleft()
        source = state_keys[source_id]
        for derived in derive_one_step(source):
            target_key = derived.target
            target_id = state_ids.get(target_key)
            if target_id is None:
                if (
                    max_transitions is not None
                    and len(edge_derivations) >= max_transitions
                ):
                    raise TypeTransitionGraphSizeError(
                        "max_transitions",
                        max_transitions,
                    )
                if max_states is not None and len(state_values) >= max_states:
                    raise TypeTransitionGraphSizeError("max_states", max_states)
                target_id = len(state_values)
                state_ids[target_key] = target_id
                state_keys.append(target_key)
                state_values.append(normalized_type_from_state_key(target_key))
                pending.append(target_id)

            edge_key = (source_id, derived.label, target_id)
            witnesses = edge_derivations.get(edge_key)
            if witnesses is None:
                if (
                    max_transitions is not None
                    and len(edge_derivations) >= max_transitions
                ):
                    raise TypeTransitionGraphSizeError(
                        "max_transitions",
                        max_transitions,
                    )
                witnesses = []
                edge_derivations[edge_key] = witnesses
            if derived.derivation not in witnesses:
                witnesses.append(derived.derivation)

    states = tuple(
        TypeState(index, value) for index, value in enumerate(state_values)
    )
    transitions = tuple(
        TypeTransition(source, target, label, tuple(witnesses))
        for (source, label, target), witnesses in edge_derivations.items()
    )
    return TypeTransitionGraph(
        initial_state=0,
        states=states,
        transitions=transitions,
    )


def _validate_limit(name: str, value: int | None) -> None:
    """验证可选图规模上限是严格正整数。"""

    if value is None:
        return
    if isinstance(value, bool) or not isinstance(value, int):
        raise TypeError(f"{name} must be an integer or None")
    if value <= 0:
        raise ValueError(f"{name} must be positive")


__all__ = ["TypeTransitionGraphSizeError", "build_type_transition_graph"]
