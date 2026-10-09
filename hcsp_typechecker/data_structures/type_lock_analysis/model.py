r"""Immutable graph analysis results and finite counterexample witnesses."""

from __future__ import annotations

from dataclasses import dataclass

from ..type_transition_graph import (
    InfiniteTime,
    SilentTransitionLabel,
    TimedTransitionLabel,
    TypeTransition,
)


@dataclass(frozen=True, slots=True)
class TransitionPath:
    r"""A connected finite path; an empty path has identical endpoints."""

    start_state: int
    transitions: tuple[TypeTransition, ...]
    end_state: int

    def __post_init__(self) -> None:
        r"""Validate that the edge sequence connects the path endpoints."""

        if not isinstance(self.start_state, int) or self.start_state < 0:
            raise ValueError("TransitionPath.start_state must be a non-negative integer")
        if not isinstance(self.end_state, int) or self.end_state < 0:
            raise ValueError("TransitionPath.end_state must be a non-negative integer")
        transitions = tuple(self.transitions)
        object.__setattr__(self, "transitions", transitions)

        current = self.start_state
        for transition in transitions:
            if not isinstance(transition, TypeTransition):
                raise TypeError("TransitionPath entries must be TypeTransition values")
            if transition.source != current:
                raise ValueError(
                    "TransitionPath is not contiguous: "
                    f"expected an edge from S{current}, got S{transition.source}"
                )
            current = transition.target
        if current != self.end_state:
            raise ValueError(
                "TransitionPath endpoint mismatch: "
                f"the edges end at S{current}, not S{self.end_state}"
            )

    @property
    def state_ids(self) -> tuple[int, ...]:
        r"""Return visited state identifiers in path order."""

        return (self.start_state,) + tuple(
            transition.target for transition in self.transitions
        )


@dataclass(frozen=True, slots=True)
class DeadlockWitness:
    r"""A reachable deadlock with an infinite-time edge and nonempty ready set."""

    prefix: TransitionPath
    infinite_wait: TypeTransition

    def __post_init__(self) -> None:
        r"""Require an infinite-time edge with a nonempty ready set."""

        transition = self.infinite_wait
        if transition.source != self.prefix.end_state:
            raise ValueError("Deadlock witness prefix does not reach the waiting state")
        label = transition.label
        if not isinstance(label, TimedTransitionLabel):
            raise ValueError("Deadlock witness must end in a timed transition")
        if label.duration is not InfiniteTime.VALUE:
            raise ValueError("Deadlock witness must use an infinite-duration transition")
        if not label.ready:
            raise ValueError("Deadlock witness must have a non-empty ready set")


@dataclass(frozen=True, slots=True)
class LivelockWitness:
    r"""A reachable prefix followed by a nonempty silent cycle."""

    prefix: TransitionPath
    cycle: TransitionPath

    def __post_init__(self) -> None:
        r"""Require a prefix reaching a nonempty, closed, silent cycle."""

        if self.prefix.end_state != self.cycle.start_state:
            raise ValueError("Livelock witness prefix does not reach the cycle entry")
        if self.cycle.start_state != self.cycle.end_state:
            raise ValueError("Livelock witness cycle must be closed")
        if not self.cycle.transitions:
            raise ValueError("Livelock witness cycle must contain at least one transition")
        if any(
            not isinstance(transition.label, SilentTransitionLabel)
            for transition in self.cycle.transitions
        ):
            raise ValueError("Livelock witness cycle may contain only silent transitions")


@dataclass(frozen=True, slots=True)
class BottomErrorWitness:
    r"""A shortest prefix to a state containing parallel Bottom roots."""

    prefix: TransitionPath
    component_indices: tuple[int, ...]

    def __post_init__(self) -> None:
        r"""Validate component indices identifying displayed Bottom roots."""

        indices = tuple(self.component_indices)
        object.__setattr__(self, "component_indices", indices)
        if not indices:
            raise ValueError("Bottom error witness requires at least one component")
        if any(
            isinstance(index, bool) or not isinstance(index, int) or index < 0
            for index in indices
        ):
            raise ValueError("Bottom component indices must be non-negative integers")
        if tuple(sorted(set(indices))) != indices:
            raise ValueError("Bottom component indices must be sorted and unique")


@dataclass(frozen=True, slots=True)
class LockFreedomReport:
    r"""Lock and Bottom-error conclusions with inspectable witnesses."""

    reachable_state_count: int
    transition_count: int
    deadlock_witness: DeadlockWitness | None = None
    livelock_witness: LivelockWitness | None = None
    bottom_error_witness: BottomErrorWitness | None = None

    def __post_init__(self) -> None:
        r"""Reject inconsistent graph counts and witness structures."""

        if self.reachable_state_count < 1:
            raise ValueError("Lock-freedom analysis requires at least one reachable state")
        if self.transition_count < 0:
            raise ValueError("transition_count must be non-negative")

    @property
    def deadlock_free(self) -> bool:
        r"""No reachable deadlock exists under Definition 4.5."""

        return self.deadlock_witness is None

    @property
    def livelock_free(self) -> bool:
        r"""No reachable infinite silent derivation exists under Definition 4.6."""

        return self.livelock_witness is None

    @property
    def lock_free(self) -> bool:
        r"""Require both deadlock freedom and livelock freedom."""

        return self.deadlock_free and self.livelock_free

    @property
    def error_free(self) -> bool:
        r"""No reachable state contains a parallel Bottom error root."""

        return self.bottom_error_witness is None

    @property
    def behavior_correct(self) -> bool:
        r"""Require paper-defined lock freedom and the additional Bottom-error check."""

        return self.lock_free and self.error_free
