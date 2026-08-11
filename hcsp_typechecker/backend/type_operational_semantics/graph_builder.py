"""从原 Type AST 构造规范化、穷尽非确定性的一张 Table 3 可达状态图。"""

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
from .table3 import derive_one_step


def build_type_transition_graph(
    initial_type: ConfigurationType,
    *,
    max_states: int | None = None,
    max_transitions: int | None = None,
) -> TypeTransitionGraph:
    """规范化输入 Type AST，并以 BFS 穷尽所有可达 Table 3 直接转移。"""

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
    """为已规范化初态分配稳定编号、合并同边证据并冻结图。"""

    state_ids: dict[NormalizedConfigurationType, int] = {initial: 0}
    state_values: list[NormalizedConfigurationType] = [initial]
    pending: deque[int] = deque((0,))
    edge_derivations: dict[
        tuple[int, TransitionLabel, int],
        list[TransitionDerivation],
    ] = {}
    complete = True
    truncation_reason: str | None = None

    while pending and complete:
        source_id = pending.popleft()
        source = state_values[source_id]
        for derived in derive_one_step(source):
            target_id = state_ids.get(derived.target)
            if target_id is None:
                if (
                    max_transitions is not None
                    and len(edge_derivations) >= max_transitions
                ):
                    complete = False
                    truncation_reason = (
                        f"maximum transition count {max_transitions} reached"
                    )
                    break
                if max_states is not None and len(state_values) >= max_states:
                    complete = False
                    truncation_reason = f"maximum state count {max_states} reached"
                    break
                target_id = len(state_values)
                state_ids[derived.target] = target_id
                state_values.append(derived.target)
                pending.append(target_id)

            edge_key = (source_id, derived.label, target_id)
            witnesses = edge_derivations.get(edge_key)
            if witnesses is None:
                if (
                    max_transitions is not None
                    and len(edge_derivations) >= max_transitions
                ):
                    complete = False
                    truncation_reason = (
                        f"maximum transition count {max_transitions} reached"
                    )
                    break
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
        complete=complete,
        truncation_reason=truncation_reason,
    )


def _validate_limit(name: str, value: int | None) -> None:
    """验证可选图规模上限是严格正整数。"""

    if value is None:
        return
    if isinstance(value, bool) or not isinstance(value, int):
        raise TypeError(f"{name} must be an integer or None")
    if value <= 0:
        raise ValueError(f"{name} must be positive")
