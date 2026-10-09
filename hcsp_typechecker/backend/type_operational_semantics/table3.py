r"""Derive one-step Table 3 successors directly on finite cyclic term graphs."""

from __future__ import annotations

from dataclasses import dataclass
from fractions import Fraction

from ...data_structures.regular_type_term_graph import (
    CanonicalRegularTypeNode,
    EquiRecursiveStateKey,
    RegularTypeNode,
    RegularTypeNodeKind,
    RegularTypeTermGraph,
)
from ...data_structures.type_transition_graph import (
    CommunicationDirection,
    InfiniteTime,
    ReadyAction,
    SilentTransitionLabel,
    Table3Rule,
    TimedTransitionLabel,
    TransitionDerivation,
    TransitionLabel,
)
from .regular_tree import (
    _StatePresentation,
    _present_state_key,
    minimize_regular_type_term_graph,
)


@dataclass(frozen=True, slots=True)
class DerivedTransition:
    r"""A direct Table 3 successor before assigning a state identifier."""

    target: EquiRecursiveStateKey
    label: TransitionLabel
    derivation: TransitionDerivation


@dataclass(frozen=True, slots=True)
class _RootStep:
    r"""An instantaneous replacement of one parallel root."""

    target_root: int
    derivation: TransitionDerivation


@dataclass(frozen=True, slots=True)
class _CommunicationOffer:
    r"""A communication branch exposed by a delay's angelic subgraph."""

    branch_index: int
    channel: str
    direction: CommunicationDirection
    continuation: int


@dataclass(frozen=True, slots=True)
class _WaitProfile:
    r"""A root's remaining deadline and ready set."""

    deadline: Fraction | InfiniteTime
    ready: frozenset[ReadyAction]


def derive_one_step(
    state: EquiRecursiveStateKey,
) -> tuple[DerivedTransition, ...]:
    r"""Enumerate instantaneous and maximal-time successors of a canonical state."""

    if not isinstance(state, EquiRecursiveStateKey):
        raise TypeError("Table 3 semantics requires an equi-recursive state key")

    # A parallel Bottom root terminates the whole configuration before any transition; Empty is
    # the parallel identity.
    if any(
        state.nodes[root].kind is RegularTypeNodeKind.BOTTOM
        for root in state.component_roots
    ):
        return ()

    transitions: list[DerivedTransition] = []
    roots = state.component_roots
    presentation = _present_state_key(state)

    for component_index, root in enumerate(roots):
        for step in _root_silent_steps(state, root):
            target = _replace_roots(
                state,
                {component_index: step.target_root},
            )
            transitions.append(
                DerivedTransition(
                    target,
                    SilentTransitionLabel(),
                    _with_component(
                        step.derivation,
                        component_index,
                        presentation,
                    ),
                )
            )

    offers = tuple(_communication_offers(state, root) for root in roots)
    for left_index in range(len(roots)):
        for right_index in range(left_index + 1, len(roots)):
            for left_offer in offers[left_index]:
                for right_offer in offers[right_index]:
                    if not _offers_match(left_offer, right_offer):
                        continue
                    target = _replace_roots(
                        state,
                        {
                            left_index: left_offer.continuation,
                            right_index: right_offer.continuation,
                        },
                    )
                    transitions.append(
                        _communication_transition(
                            target,
                            left_index,
                            left_offer,
                            right_index,
                            right_offer,
                            presentation,
                        )
                    )

    timed = _derive_maximal_time_step(state, presentation)
    if timed is not None:
        transitions.append(timed)
    return _deduplicate_derived(transitions)


def _communication_transition(
    target: EquiRecursiveStateKey,
    left_index: int,
    left_offer: _CommunicationOffer,
    right_index: int,
    right_offer: _CommunicationOffer,
    presentation: _StatePresentation,
) -> DerivedTransition:
    r"""Map communication participants and branches to visible display AST positions."""

    participants = [
        (
            presentation.component_indices[left_index],
            presentation.interrupt_branch_indices[left_index][
                left_offer.branch_index
            ],
        ),
        (
            presentation.component_indices[right_index],
            presentation.interrupt_branch_indices[right_index][
                right_offer.branch_index
            ],
        ),
    ]
    participants.sort(key=lambda item: item[0])
    return DerivedTransition(
        target,
        SilentTransitionLabel(),
        TransitionDerivation(
            Table3Rule.COMMUNICATION,
            component_indices=tuple(item[0] for item in participants),
            branch_indices=tuple(item[1] for item in participants),
            channel=left_offer.channel,
        ),
    )


def _root_silent_steps(
    state: EquiRecursiveStateKey,
    root: int,
) -> tuple[_RootStep, ...]:
    r"""Derive internal-choice and valid zero-delay timeout steps."""

    node = state.nodes[root]
    if node.kind is RegularTypeNodeKind.INTERNAL_CHOICE:
        return tuple(
            _RootStep(
                branch,
                TransitionDerivation(
                    Table3Rule.INTERNAL_CHOICE,
                    branch_indices=(index,),
                ),
            )
            for index, branch in enumerate(node.children)
            if state.nodes[branch].kind is not RegularTypeNodeKind.BOTTOM
        )
    if (
        node.kind is RegularTypeNodeKind.FINITE_DELAY
        and node.payload == Fraction(0)
    ):
        continuation = node.children[1]
        if state.nodes[continuation].kind is not RegularTypeNodeKind.BOTTOM:
            return (
                _RootStep(
                    continuation,
                    TransitionDerivation(Table3Rule.TIMEOUT),
                ),
            )
    return ()


def _communication_offers(
    state: EquiRecursiveStateKey,
    root: int,
) -> tuple[_CommunicationOffer, ...]:
    r"""Extract input and output interrupt offers from a delay root."""

    node = state.nodes[root]
    if node.kind not in {
        RegularTypeNodeKind.FINITE_DELAY,
        RegularTypeNodeKind.INFINITE_DELAY,
    }:
        return ()
    interrupt_root = node.children[0]
    branch_nodes = _communication_branch_nodes(state, interrupt_root)
    offers: list[_CommunicationOffer] = []
    for index, branch_id in enumerate(branch_nodes):
        branch = state.nodes[branch_id]
        if branch.kind is RegularTypeNodeKind.INPUT:
            direction = CommunicationDirection.INPUT
        elif branch.kind is RegularTypeNodeKind.OUTPUT:
            direction = CommunicationDirection.OUTPUT
        else:  # pragma: no cover - protected by term-graph invariants
            raise TypeError("Angelic branch is not a communication node")
        if not isinstance(branch.payload, str):  # defensive payload narrowing
            raise TypeError("Communication node does not contain a channel")
        offers.append(
            _CommunicationOffer(
                index,
                branch.payload,
                direction,
                branch.children[0],
            )
        )
    return tuple(offers)


def _communication_branch_nodes(
    state: EquiRecursiveStateKey,
    interrupt_root: int,
) -> tuple[int, ...]:
    r"""View an angelic root as a sequence of communication node identifiers."""

    node = state.nodes[interrupt_root]
    if node.kind is RegularTypeNodeKind.NO_INTERRUPT:
        return ()
    if node.kind in {RegularTypeNodeKind.INPUT, RegularTypeNodeKind.OUTPUT}:
        return (interrupt_root,)
    if node.kind is RegularTypeNodeKind.EXTERNAL_CHOICE:
        return node.children
    raise TypeError(
        f"Delay interrupt child has invalid kind: {node.kind.value!r}"
    )


def _offers_match(left: _CommunicationOffer, right: _CommunicationOffer) -> bool:
    r"""Match complementary input/output offers on the same channel."""

    return (
        left.channel == right.channel
        and left.direction is not right.direction
    )


def _ready_set(
    state: EquiRecursiveStateKey,
    interrupt_root: int,
) -> frozenset[ReadyAction]:
    r"""Compute the Table 3 ready set from the angelic subgraph."""

    actions: set[ReadyAction] = set()
    for branch_id in _communication_branch_nodes(state, interrupt_root):
        branch = state.nodes[branch_id]
        direction = (
            CommunicationDirection.INPUT
            if branch.kind is RegularTypeNodeKind.INPUT
            else CommunicationDirection.OUTPUT
        )
        if not isinstance(branch.payload, str):
            raise TypeError("Communication node does not contain a channel")
        actions.add(ReadyAction(branch.payload, direction))
    return frozenset(actions)


def _wait_profile(
    state: EquiRecursiveStateKey,
    root: int,
) -> _WaitProfile | None:
    r"""Return a root's deadline and ready set, or None if it cannot wait."""

    node = state.nodes[root]
    if node.kind is RegularTypeNodeKind.FINITE_DELAY:
        if node.payload == Fraction(0):
            return None
        if not isinstance(node.payload, Fraction):
            raise TypeError("Finite-delay node does not contain a rational duration")
        return _WaitProfile(node.payload, _ready_set(state, node.children[0]))
    if node.kind is RegularTypeNodeKind.INFINITE_DELAY:
        return _WaitProfile(
            InfiniteTime.VALUE,
            _ready_set(state, node.children[0]),
        )
    return None


def _derive_maximal_time_step(
    state: EquiRecursiveStateKey,
    presentation: _StatePresentation,
) -> DerivedTransition | None:
    r"""Advance all waiting roots to the next deadline unless complementary actions are ready."""

    profiles: list[_WaitProfile] = []
    for root in state.component_roots:
        profile = _wait_profile(state, root)
        if profile is None:
            return None
        profiles.append(profile)

    for left_index in range(len(profiles)):
        for right_index in range(left_index + 1, len(profiles)):
            right_ready = profiles[right_index].ready
            if any(
                action.complement() in right_ready
                for action in profiles[left_index].ready
            ):
                return None

    finite_deadlines = tuple(
        profile.deadline
        for profile in profiles
        if isinstance(profile.deadline, Fraction)
    )
    duration: Fraction | InfiniteTime
    if finite_deadlines:
        duration = min(finite_deadlines)
    else:
        duration = InfiniteTime.VALUE

    nodes = list(state.nodes)
    advanced: dict[int, int] = {}
    target_roots: list[int] = []
    component_derivations: list[tuple[int, TransitionDerivation]] = []
    for component_index, root in enumerate(state.component_roots):
        node = state.nodes[root]
        if node.kind is RegularTypeNodeKind.INFINITE_DELAY:
            target_root = root
        else:
            if not isinstance(duration, Fraction):
                raise ValueError("Finite delay cannot advance by infinity")
            target_root = advanced.get(root, -1)
            if target_root < 0:
                if not isinstance(node.payload, Fraction):
                    raise TypeError("Finite-delay node has an invalid duration")
                target_root = len(nodes)
                nodes.append(
                    CanonicalRegularTypeNode(
                        RegularTypeNodeKind.FINITE_DELAY,
                        node.payload - duration,
                        node.children,
                    )
                )
                advanced[root] = target_root
        target_roots.append(target_root)
        component_derivations.append(
            (
                presentation.component_indices[component_index],
                TransitionDerivation(Table3Rule.DELAY),
            )
        )

    target = _canonicalize_graph(tuple(target_roots), tuple(nodes))
    ready = frozenset(action for profile in profiles for action in profile.ready)
    if len(target_roots) == 1:
        derivation = component_derivations[0][1]
    else:
        ordered_derivations = tuple(
            sorted(component_derivations, key=lambda item: item[0])
        )
        derivation = TransitionDerivation(
            Table3Rule.PARALLEL_TIME,
            component_indices=tuple(item[0] for item in ordered_derivations),
            premises=tuple(item[1] for item in ordered_derivations),
        )
    return DerivedTransition(
        target,
        TimedTransitionLabel(duration, ready),
        derivation,
    )


def _replace_roots(
    state: EquiRecursiveStateKey,
    replacements: dict[int, int],
) -> EquiRecursiveStateKey:
    r"""Replace selected parallel roots and minimize the resulting graph."""

    roots = tuple(
        replacements.get(index, root)
        for index, root in enumerate(state.component_roots)
    )
    return _canonicalize_graph(roots, state.nodes)


def _canonicalize_graph(
    roots: tuple[int, ...],
    nodes: tuple[CanonicalRegularTypeNode, ...],
) -> EquiRecursiveStateKey:
    r"""Remove unreachable nodes and apply common bisimulation minimization."""

    reachable: set[int] = set()
    pending = list(roots)
    while pending:
        node_id = pending.pop()
        if node_id in reachable:
            continue
        reachable.add(node_id)
        pending.extend(nodes[node_id].children)
    ordered = tuple(sorted(reachable))
    renumber = {old_id: new_id for new_id, old_id in enumerate(ordered)}
    graph = RegularTypeTermGraph(
        tuple(renumber[root] for root in roots),
        tuple(
            RegularTypeNode(
                nodes[old_id].kind,
                nodes[old_id].payload,
                tuple(renumber[child] for child in nodes[old_id].children),
            )
            for old_id in ordered
        ),
    )
    return minimize_regular_type_term_graph(graph)


def _with_component(
    derivation: TransitionDerivation,
    component_index: int,
    presentation: _StatePresentation,
) -> TransitionDerivation:
    r"""Map local term-graph positions to visible configuration and branch positions."""

    visible_branches = derivation.branch_indices
    if derivation.rule is Table3Rule.INTERNAL_CHOICE:
        branch_map = presentation.internal_branch_indices[component_index]
        visible_branches = tuple(
            branch_map[index] for index in derivation.branch_indices
        )

    return TransitionDerivation(
        derivation.rule,
        component_indices=(
            presentation.component_indices[component_index],
        ) + derivation.component_indices,
        branch_indices=visible_branches,
        channel=derivation.channel,
        premises=derivation.premises,
    )


def _deduplicate_derived(
    transitions: list[DerivedTransition],
) -> tuple[DerivedTransition, ...]:
    r"""Deduplicate identical rule instances while retaining distinct edge derivations."""

    seen: set[DerivedTransition] = set()
    ordered: list[DerivedTransition] = []
    for transition in transitions:
        if transition in seen:
            continue
        seen.add(transition)
        ordered.append(transition)
    return tuple(ordered)


__all__ = ["DerivedTransition", "derive_one_step"]
