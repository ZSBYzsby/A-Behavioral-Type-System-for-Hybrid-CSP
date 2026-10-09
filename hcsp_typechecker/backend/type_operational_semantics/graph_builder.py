r"""Compile Type ASTs into cyclic term graphs and enumerate Table 3 successors."""

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
    r"""Graph construction exceeded a requested size limit."""

    def __init__(self, limit_name: str, limit: int) -> None:
        r"""Store the exceeded limit; never expose a partial graph."""

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
    r"""Normalize the Type and build its complete critical-deadline graph by BFS."""

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
    r"""Merge equivalent edges and freeze the reachable cyclic-term graph."""

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
    r"""Require a strictly positive integer for an optional graph limit."""

    if value is None:
        return
    if isinstance(value, bool) or not isinstance(value, int):
        raise TypeError(f"{name} must be an integer or None")
    if value <= 0:
        raise ValueError(f"{name} must be positive")


__all__ = ["TypeTransitionGraphSizeError", "build_type_transition_graph"]
