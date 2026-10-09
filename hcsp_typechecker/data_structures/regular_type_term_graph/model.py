r"""Finite term-graph representations of equi-recursive regular trees."""

from __future__ import annotations

from dataclasses import dataclass
from enum import Enum
from fractions import Fraction
from typing import TypeAlias

from ...identifiers import is_hcsp_identifier


class RegularTypeNodeKind(str, Enum):
    r"""Observable process and angelic constructors in a regular Type graph."""

    EMPTY = "empty"
    BOTTOM = "bottom"
    NO_INTERRUPT = "no_interrupt"
    INPUT = "input"
    OUTPUT = "output"
    EXTERNAL_CHOICE = "external_choice"
    INTERNAL_CHOICE = "internal_choice"
    FINITE_DELAY = "finite_delay"
    INFINITE_DELAY = "infinite_delay"


RegularTypePayload: TypeAlias = str | Fraction | None


def _validate_node(
    kind: RegularTypeNodeKind,
    payload: RegularTypePayload,
    children: tuple[int, ...],
) -> None:
    r"""Validate node labels, payloads, and child-edge arity."""

    if not isinstance(kind, RegularTypeNodeKind):
        raise TypeError("Regular type node kind must be RegularTypeNodeKind")
    if not all(
        not isinstance(child, bool) and isinstance(child, int) and child >= 0
        for child in children
    ):
        raise ValueError("Regular type node children must be non-negative integers")

    if kind in {RegularTypeNodeKind.INPUT, RegularTypeNodeKind.OUTPUT}:
        if not isinstance(payload, str) or not is_hcsp_identifier(payload):
            raise ValueError("Communication regular node requires an HCSP channel")
        if len(children) != 1:
            raise ValueError("Communication regular node requires one continuation")
        return

    if kind is RegularTypeNodeKind.FINITE_DELAY:
        if not isinstance(payload, Fraction) or payload < 0:
            raise ValueError("Finite-delay regular node requires non-negative Fraction")
        if len(children) != 2:
            raise ValueError("Finite-delay regular node requires interrupts and continuation")
        return

    if payload is not None:
        raise ValueError(f"Regular node {kind.value!r} does not accept a payload")

    if kind in {
        RegularTypeNodeKind.EMPTY,
        RegularTypeNodeKind.BOTTOM,
        RegularTypeNodeKind.NO_INTERRUPT,
    }:
        if children:
            raise ValueError(f"Regular leaf {kind.value!r} cannot have children")
        return
    if kind is RegularTypeNodeKind.INFINITE_DELAY:
        if len(children) != 1:
            raise ValueError("Infinite-delay regular node requires one interrupt child")
        return
    if kind in {
        RegularTypeNodeKind.EXTERNAL_CHOICE,
        RegularTypeNodeKind.INTERNAL_CHOICE,
    }:
        if len(children) < 2:
            raise ValueError("Regular choice node requires at least two children")
        return
    raise TypeError(f"Unsupported regular type node kind: {kind!r}")


@dataclass(frozen=True, slots=True)
class RegularTypeNode:
    r"""A pre-minimization cyclic Type node with numbered child edges."""

    kind: RegularTypeNodeKind
    payload: RegularTypePayload = None
    children: tuple[int, ...] = ()

    def __post_init__(self) -> None:
        r"""Freeze child edges and validate the node constructor."""

        object.__setattr__(self, "children", tuple(self.children))
        _validate_node(self.kind, self.payload, self.children)


@dataclass(frozen=True, slots=True)
class CanonicalRegularTypeNode:
    r"""A bisimulation-minimized Type node with stable class identifiers."""

    kind: RegularTypeNodeKind
    payload: RegularTypePayload = None
    children: tuple[int, ...] = ()

    def __post_init__(self) -> None:
        r"""Freeze child edges and validate the canonical constructor."""

        object.__setattr__(self, "children", tuple(self.children))
        _validate_node(self.kind, self.payload, self.children)


def _validate_graph(
    component_roots: tuple[int, ...],
    nodes: tuple[RegularTypeNode | CanonicalRegularTypeNode, ...],
) -> None:
    r"""Validate roots, identifiers, references, and root reachability."""

    if not component_roots:
        raise ValueError("Regular type term graph requires a configuration root")
    if not nodes:
        raise ValueError("Regular type term graph requires at least one node")
    limit = len(nodes)
    references = component_roots + tuple(
        child for node in nodes for child in node.children
    )
    if any(
        isinstance(reference, bool)
        or not isinstance(reference, int)
        or reference < 0
        or reference >= limit
        for reference in references
    ):
        raise ValueError("Regular type term graph contains an invalid node reference")

    reachable: set[int] = set()
    pending = list(component_roots)
    while pending:
        node_id = pending.pop()
        if node_id in reachable:
            continue
        reachable.add(node_id)
        pending.extend(nodes[node_id].children)
    if len(reachable) != len(nodes):
        raise ValueError("Regular type term graph cannot contain unreachable nodes")
    _validate_node_sorts(component_roots, nodes)


def _validate_node_sorts(
    component_roots: tuple[int, ...],
    nodes: tuple[RegularTypeNode | CanonicalRegularTypeNode, ...],
) -> None:
    r"""Check process/angelic sorts of roots and child edges."""

    process_kinds = {
        RegularTypeNodeKind.EMPTY,
        RegularTypeNodeKind.BOTTOM,
        RegularTypeNodeKind.INTERNAL_CHOICE,
        RegularTypeNodeKind.FINITE_DELAY,
        RegularTypeNodeKind.INFINITE_DELAY,
    }
    communication_kinds = {
        RegularTypeNodeKind.INPUT,
        RegularTypeNodeKind.OUTPUT,
    }
    angelic_kinds = communication_kinds | {
        RegularTypeNodeKind.NO_INTERRUPT,
        RegularTypeNodeKind.EXTERNAL_CHOICE,
    }
    if any(nodes[root].kind not in process_kinds for root in component_roots):
        raise ValueError("Regular configuration roots must be process-type nodes")

    for node in nodes:
        if node.kind is RegularTypeNodeKind.INTERNAL_CHOICE:
            if any(nodes[child].kind not in process_kinds for child in node.children):
                raise ValueError("Internal-choice children must be process-type nodes")
        elif node.kind is RegularTypeNodeKind.FINITE_DELAY:
            interrupt, continuation = node.children
            if nodes[interrupt].kind not in angelic_kinds:
                raise ValueError("Finite-delay interrupt child must be angelic")
            if nodes[continuation].kind not in process_kinds:
                raise ValueError("Finite-delay continuation must be a process type")
        elif node.kind is RegularTypeNodeKind.INFINITE_DELAY:
            if nodes[node.children[0]].kind not in angelic_kinds:
                raise ValueError("Infinite-delay interrupt child must be angelic")
        elif node.kind in communication_kinds:
            if nodes[node.children[0]].kind not in process_kinds:
                raise ValueError("Communication continuation must be a process type")
        elif node.kind is RegularTypeNodeKind.EXTERNAL_CHOICE:
            if any(
                nodes[child].kind not in communication_kinds
                for child in node.children
            ):
                raise ValueError(
                    "External-choice children must be communication nodes"
                )


@dataclass(frozen=True, slots=True)
class RegularTypeTermGraph:
    r"""A finite cyclic Type graph preserving parallel multiplicity."""

    component_roots: tuple[int, ...]
    nodes: tuple[RegularTypeNode, ...]

    def __post_init__(self) -> None:
        r"""Freeze roots and nodes, then validate references."""

        object.__setattr__(self, "component_roots", tuple(self.component_roots))
        object.__setattr__(self, "nodes", tuple(self.nodes))
        if not all(isinstance(node, RegularTypeNode) for node in self.nodes):
            raise TypeError("Regular type term graph requires RegularTypeNode values")
        _validate_graph(self.component_roots, self.nodes)


@dataclass(frozen=True, slots=True)
class EquiRecursiveStateKey:
    r"""A hashable canonical regular-tree class used as a Table 3 state."""

    component_roots: tuple[int, ...]
    nodes: tuple[CanonicalRegularTypeNode, ...]

    def __post_init__(self) -> None:
        r"""Freeze the minimized graph and validate stable identifiers."""

        object.__setattr__(self, "component_roots", tuple(self.component_roots))
        object.__setattr__(self, "nodes", tuple(self.nodes))
        if not all(isinstance(node, CanonicalRegularTypeNode) for node in self.nodes):
            raise TypeError(
                "Equi-recursive state key requires CanonicalRegularTypeNode values"
            )
        _validate_graph(self.component_roots, self.nodes)
