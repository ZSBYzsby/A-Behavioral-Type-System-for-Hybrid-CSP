r"""Immutable states, labels, transitions, and Table 3 derivations."""

from __future__ import annotations

from dataclasses import dataclass
from enum import Enum
from fractions import Fraction
from typing import Iterable, TypeAlias

from ...identifiers import is_hcsp_identifier
from ..normalized_type_ast import NormalizedConfigurationType


class CommunicationDirection(str, Enum):
    r"""Input or output direction of a ready action."""

    INPUT = "?"
    OUTPUT = "!"


@dataclass(frozen=True, slots=True)
class ReadyAction:
    r"""A directed channel action offered while waiting."""

    channel: str
    direction: CommunicationDirection

    def __post_init__(self) -> None:
        r"""Validate the channel identifier and communication direction."""

        if not is_hcsp_identifier(self.channel):
            raise ValueError("Ready-action channel must be an HCSP identifier")
        if not isinstance(self.direction, CommunicationDirection):
            raise TypeError("Ready-action direction must be CommunicationDirection")

    def complement(self) -> "ReadyAction":
        r"""Return the opposite-direction ready action on the same channel."""

        direction = (
            CommunicationDirection.OUTPUT
            if self.direction is CommunicationDirection.INPUT
            else CommunicationDirection.INPUT
        )
        return ReadyAction(self.channel, direction)


class InfiniteTime(str, Enum):
    r"""A unique positive-infinity duration distinct from finite Fraction values."""

    VALUE = "infinity"


TimeDuration: TypeAlias = Fraction | InfiniteTime


@dataclass(frozen=True, slots=True)
class SilentTransitionLabel:
    r"""A zero-time silent Table 3 transition label."""


@dataclass(frozen=True, slots=True, init=False)
class TimedTransitionLabel:
    r"""A timed label carrying a duration and ready set."""

    duration: TimeDuration
    ready: frozenset[ReadyAction]

    def __init__(
        self,
        duration: Fraction | int | InfiniteTime,
        ready: Iterable[ReadyAction],
    ) -> None:
        r"""Normalize a positive rational or infinite duration and freeze its ready set."""

        if isinstance(duration, bool):
            raise TypeError("Timed transition duration must not be Boolean")
        if isinstance(duration, int):
            normalized_duration: TimeDuration = Fraction(duration)
        elif isinstance(duration, (Fraction, InfiniteTime)):
            normalized_duration = duration
        else:
            raise TypeError("Timed duration must be Fraction, int, or InfiniteTime")
        if isinstance(normalized_duration, Fraction) and normalized_duration <= 0:
            raise ValueError("Timed transition duration must be strictly positive")
        ready_set = frozenset(ready)
        if not all(isinstance(action, ReadyAction) for action in ready_set):
            raise TypeError("Timed ready set must contain ReadyAction values")
        object.__setattr__(self, "duration", normalized_duration)
        object.__setattr__(self, "ready", ready_set)


TransitionLabel: TypeAlias = SilentTransitionLabel | TimedTransitionLabel


class Table3Rule(str, Enum):
    r"""Table 3 rules recorded as edge evidence."""

    COMMUNICATION = "P-unrhd"
    TIMEOUT = "P-triangleright"
    INTERNAL_CHOICE = "P-sqcup"
    DELAY = "P-unrhd-prime"
    PARALLEL_TIME = "P-parallel"


@dataclass(frozen=True, slots=True)
class TransitionDerivation:
    r"""Evidence for one concrete Table 3 rule application."""

    rule: Table3Rule
    component_indices: tuple[int, ...] = ()
    branch_indices: tuple[int, ...] = ()
    channel: str | None = None
    premises: tuple["TransitionDerivation", ...] = ()

    def __post_init__(self) -> None:
        r"""Validate rule labels, indices, channels, and nested premise evidence."""

        if not isinstance(self.rule, Table3Rule):
            raise TypeError("Transition derivation requires a Table3Rule")
        for value in self.component_indices + self.branch_indices:
            if isinstance(value, bool) or not isinstance(value, int) or value < 0:
                raise ValueError("Transition derivation indices must be non-negative ints")
        if self.channel is not None and not is_hcsp_identifier(self.channel):
            raise ValueError("Transition derivation channel must be an HCSP identifier")
        if not all(
            isinstance(premise, TransitionDerivation) for premise in self.premises
        ):
            raise TypeError("Transition derivation premises must be derivations")


@dataclass(frozen=True, slots=True)
class TypeState:
    r"""An equi-recursive state identifier and canonical display AST."""

    id: int
    type_ast: NormalizedConfigurationType

    def __post_init__(self) -> None:
        r"""Require a nonnegative state identifier and normalized configuration root."""

        if isinstance(self.id, bool) or not isinstance(self.id, int) or self.id < 0:
            raise ValueError("Type-state id must be a non-negative integer")
        if not isinstance(self.type_ast, NormalizedConfigurationType):
            raise TypeError("Type state must contain a normalized configuration")


@dataclass(frozen=True, slots=True)
class TypeTransition:
    r"""A directed edge retaining all equivalent rule derivations."""

    source: int
    target: int
    label: TransitionLabel
    derivations: tuple[TransitionDerivation, ...]

    def __post_init__(self) -> None:
        r"""Validate endpoints, label kind, and nonempty derivation evidence."""

        for endpoint in (self.source, self.target):
            if isinstance(endpoint, bool) or not isinstance(endpoint, int) or endpoint < 0:
                raise ValueError("Transition endpoints must be non-negative integers")
        if not isinstance(self.label, (SilentTransitionLabel, TimedTransitionLabel)):
            raise TypeError("Transition label must be silent or timed")
        if not self.derivations or not all(
            isinstance(item, TransitionDerivation) for item in self.derivations
        ):
            raise ValueError("Transition requires at least one derivation witness")


@dataclass(frozen=True, slots=True)
class TypeTransitionGraph:
    r"""The complete critical-deadline graph quotiented by equi-recursive state identity."""

    initial_state: int
    states: tuple[TypeState, ...]
    transitions: tuple[TypeTransition, ...]

    def __post_init__(self) -> None:
        r"""Require contiguous state identifiers and valid edge endpoints."""

        if not self.states:
            raise ValueError("Type transition graph requires at least one state")
        expected_ids = tuple(range(len(self.states)))
        actual_ids = tuple(state.id for state in self.states)
        if actual_ids != expected_ids:
            raise ValueError("Type transition graph state ids must be contiguous")
        if self.initial_state not in expected_ids:
            raise ValueError("Initial state id is not present in the graph")
        if any(
            edge.source not in expected_ids or edge.target not in expected_ids
            for edge in self.transitions
        ):
            raise ValueError("Type transition refers to an unknown state")

    def outgoing(self, state_id: int) -> tuple[TypeTransition, ...]:
        r"""Return outgoing edges in stable order; unknown identifiers raise KeyError."""

        if state_id < 0 or state_id >= len(self.states):
            raise KeyError(f"Unknown type-state id: {state_id}")
        return tuple(edge for edge in self.transitions if edge.source == state_id)
