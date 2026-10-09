r"""Compile normalized Types into finite regular term graphs and equi-recursive keys."""

from __future__ import annotations

from dataclasses import dataclass
from fractions import Fraction
from typing import Any, Callable, Iterable

from ...data_structures.normalized_type_ast import (
    NormalizedAngelicType,
    NormalizedBottomType,
    NormalizedBoundTypeVar,
    NormalizedConfigurationType,
    NormalizedEmptyType,
    NormalizedExternalChoiceType,
    NormalizedFiniteDelayType,
    NormalizedInfiniteDelayType,
    NormalizedInputType,
    NormalizedInternalChoiceType,
    NormalizedMuType,
    NormalizedNoInterruptType,
    NormalizedOutputType,
    NormalizedProcessType,
    make_normalized_external_choice,
    make_normalized_internal_choice,
    normalized_angelic_key,
    normalized_process_key,
)
from ...data_structures.regular_type_term_graph import (
    CanonicalRegularTypeNode,
    EquiRecursiveStateKey,
    RegularTypeNode,
    RegularTypeNodeKind,
    RegularTypeTermGraph,
)


@dataclass(frozen=True, slots=True)
class _NodeSpec:
    r"""A temporary node specification permitting singleton choices during minimization."""

    kind: RegularTypeNodeKind
    payload: str | Fraction | None
    children: tuple[int, ...]


@dataclass(frozen=True, slots=True)
class _StatePresentation:
    r"""A display AST and mappings from semantic to displayed positions."""

    type_ast: NormalizedConfigurationType
    component_indices: tuple[int, ...]
    internal_branch_indices: tuple[tuple[int, ...], ...]
    interrupt_branch_indices: tuple[tuple[int, ...], ...]


class _TermGraphBuilder:
    r"""Resolve De Bruijn recursion binders into finite cyclic graph placeholders."""

    def __init__(self) -> None:
        r"""Initialize nodes and recursion-binder aliases."""

        self.nodes: list[RegularTypeNode | None] = []
        self.aliases: dict[int, int] = {}

    def placeholder(self) -> int:
        r"""Allocate a binder placeholder for its future body root."""

        node_id = len(self.nodes)
        self.nodes.append(None)
        return node_id

    def node(
        self,
        kind: RegularTypeNodeKind,
        payload: str | Fraction | None = None,
        children: Iterable[int] = (),
    ) -> int:
        r"""Append a constructor node and return its temporary identifier."""

        # Evaluate child generators before allocating the parent identifier; children may append
        # nodes.
        frozen_children = tuple(children)
        node_id = len(self.nodes)
        self.nodes.append(RegularTypeNode(kind, payload, frozen_children))
        return node_id

    def process(
        self,
        value: NormalizedProcessType,
        binders: tuple[int, ...],
    ) -> int:
        r"""Compile a normalized process with an explicit work stack."""

        return self._build(value, binders, angelic=False)

    def angelic(
        self,
        value: NormalizedAngelicType,
        binders: tuple[int, ...],
    ) -> int:
        r"""Compile angelic types using the same explicit work stack."""

        return self._build(value, binders, angelic=True)

    def _build(
        self,
        root: NormalizedProcessType | NormalizedAngelicType,
        binders: tuple[int, ...],
        *,
        angelic: bool,
    ) -> int:
        r"""Append a potentially deep normalized type tree iteratively."""

        results: list[int] = []
        # visit: ("visit", value, binders, is_angelic)
        # finish: ("finish", kind, payload, result_start)
        # alias: ("alias", binder, result_start)
        pending: list[tuple[Any, ...]] = [
            ("visit", root, binders, angelic)
        ]
        while pending:
            task = pending.pop()
            tag = task[0]
            if tag == "finish":
                _, kind, payload, start = task
                children = tuple(results[start:])
                del results[start:]
                results.append(self.node(kind, payload, children))
                continue
            if tag == "alias":
                _, binder, start = task
                if len(results) != start + 1:
                    raise RuntimeError("Recursive Type body produced an invalid result")
                body = results.pop()
                self.aliases[binder] = body
                results.append(binder)
                continue

            _, value, current_binders, is_angelic = task
            if not is_angelic:
                if isinstance(value, NormalizedEmptyType):
                    results.append(self.node(RegularTypeNodeKind.EMPTY))
                elif isinstance(value, NormalizedBottomType):
                    results.append(self.node(RegularTypeNodeKind.BOTTOM))
                elif isinstance(value, NormalizedBoundTypeVar):
                    if value.index >= len(current_binders):
                        raise ValueError(
                            "Normalized type contains a free recursion position"
                        )
                    results.append(current_binders[-1 - value.index])
                elif isinstance(value, NormalizedInternalChoiceType):
                    start = len(results)
                    pending.append(
                        ("finish", RegularTypeNodeKind.INTERNAL_CHOICE, None, start)
                    )
                    for branch in reversed(value.branches):
                        pending.append(
                            ("visit", branch, current_binders, False)
                        )
                elif isinstance(value, NormalizedFiniteDelayType):
                    start = len(results)
                    pending.append(
                        (
                            "finish",
                            RegularTypeNodeKind.FINITE_DELAY,
                            value.duration,
                            start,
                        )
                    )
                    pending.append(
                        ("visit", value.continuation, current_binders, False)
                    )
                    pending.append(
                        ("visit", value.interrupts, current_binders, True)
                    )
                elif isinstance(value, NormalizedInfiniteDelayType):
                    start = len(results)
                    pending.append(
                        ("finish", RegularTypeNodeKind.INFINITE_DELAY, None, start)
                    )
                    pending.append(
                        ("visit", value.interrupts, current_binders, True)
                    )
                elif isinstance(value, NormalizedMuType):
                    binder = self.placeholder()
                    start = len(results)
                    pending.append(("alias", binder, start))
                    pending.append(
                        (
                            "visit",
                            value.body,
                            current_binders + (binder,),
                            False,
                        )
                    )
                else:
                    raise TypeError(
                        "Unsupported normalized process type: "
                        f"{type(value).__name__}"
                    )
                continue

            if isinstance(value, NormalizedNoInterruptType):
                results.append(self.node(RegularTypeNodeKind.NO_INTERRUPT))
            elif isinstance(value, NormalizedInputType):
                start = len(results)
                pending.append(
                    ("finish", RegularTypeNodeKind.INPUT, value.channel, start)
                )
                pending.append(
                    ("visit", value.continuation, current_binders, False)
                )
            elif isinstance(value, NormalizedOutputType):
                start = len(results)
                pending.append(
                    ("finish", RegularTypeNodeKind.OUTPUT, value.channel, start)
                )
                pending.append(
                    ("visit", value.continuation, current_binders, False)
                )
            elif isinstance(value, NormalizedExternalChoiceType):
                start = len(results)
                pending.append(
                    ("finish", RegularTypeNodeKind.EXTERNAL_CHOICE, None, start)
                )
                for branch in reversed(value.branches):
                    pending.append(("visit", branch, current_binders, True))
            else:
                raise TypeError(
                    "Unsupported normalized angelic type: "
                    f"{type(value).__name__}"
                )

        if len(results) != 1:
            raise RuntimeError("Regular Type conversion produced an invalid result")
        return results[0]

    def freeze(self, roots: Iterable[int]) -> RegularTypeTermGraph:
        r"""Resolve binder aliases and freeze reachable constructor nodes."""

        resolved_roots = tuple(self._resolve(root) for root in roots)
        semantic: dict[int, RegularTypeNode] = {}
        for old_id, node in enumerate(self.nodes):
            if node is None:
                continue
            semantic[old_id] = RegularTypeNode(
                node.kind,
                node.payload,
                tuple(self._resolve(child) for child in node.children),
            )

        reachable: set[int] = set()
        pending = list(resolved_roots)
        while pending:
            node_id = pending.pop()
            if node_id in reachable:
                continue
            node = semantic.get(node_id)
            if node is None:
                raise ValueError("Recursive binder did not resolve to a Type node")
            reachable.add(node_id)
            pending.extend(node.children)

        renumber = {
            old_id: new_id for new_id, old_id in enumerate(sorted(reachable))
        }
        frozen_nodes = tuple(
            RegularTypeNode(
                semantic[old_id].kind,
                semantic[old_id].payload,
                tuple(renumber[child] for child in semantic[old_id].children),
            )
            for old_id in sorted(reachable)
        )
        return RegularTypeTermGraph(
            tuple(renumber[root] for root in resolved_roots),
            frozen_nodes,
        )

    def _resolve(self, node_id: int) -> int:
        r"""Resolve binder aliases and reject pure alias recursion cycles."""

        path: list[int] = []
        current = node_id
        while self.nodes[current] is None:
            if current in path:
                raise ValueError("Unguarded recursive aliases cannot form a regular node")
            path.append(current)
            if current not in self.aliases:
                raise ValueError("Recursive binder placeholder was not resolved")
            current = self.aliases[current]
        for alias in path:
            self.aliases[alias] = current
        return current


def build_regular_type_term_graph(
    value: NormalizedConfigurationType,
) -> RegularTypeTermGraph:
    r"""Compile a closed normalized configuration without mu or variable nodes."""

    if not isinstance(value, NormalizedConfigurationType):
        raise TypeError("Regular type conversion requires a normalized configuration")
    builder = _TermGraphBuilder()
    roots = tuple(builder.process(component, ()) for component in value.components)
    return builder.freeze(roots)


def equi_recursive_state_key(
    value: NormalizedConfigurationType,
) -> EquiRecursiveStateKey:
    r"""Return a hashable state key invariant under finite mu unfolding."""

    return minimize_regular_type_term_graph(build_regular_type_term_graph(value))


def equi_recursive_equivalent(
    left: NormalizedConfigurationType,
    right: NormalizedConfigurationType,
) -> bool:
    r"""Compare normalized configurations as equi-recursive infinite regular trees."""

    return equi_recursive_state_key(left) == equi_recursive_state_key(right)


def minimize_regular_type_term_graph(
    graph: RegularTypeTermGraph,
) -> EquiRecursiveStateKey:
    r"""Minimize by greatest bisimulation and number the quotient deterministically."""

    if not isinstance(graph, RegularTypeTermGraph):
        raise TypeError("Regular-tree minimization requires RegularTypeTermGraph")
    current = graph
    maximum_rounds = max(8, len(graph.nodes) * 4 + 4)
    for _ in range(maximum_rounds):
        colors = _bisimulation_colors(current)
        reduced = _quotient_and_simplify(current, colors)
        if reduced == current:
            return EquiRecursiveStateKey(
                reduced.component_roots,
                tuple(
                    CanonicalRegularTypeNode(
                        node.kind,
                        node.payload,
                        node.children,
                    )
                    for node in reduced.nodes
                ),
            )
        current = reduced
    raise RuntimeError("Equi-recursive regular-tree minimization did not converge")


def _bisimulation_colors(graph: RegularTypeTermGraph) -> tuple[int, ...]:
    r"""Compute constructor-preserving bisimulation through partition refinement."""

    colors = _assign_colors(
        tuple((_base_key(node),) for node in graph.nodes)
    )
    while True:
        signatures = tuple(
            _node_signature(node, colors) for node in graph.nodes
        )
        next_colors = _assign_colors(signatures)
        # Compare color equivalence relations, not color numbers, to detect stable partitions.
        if _same_partition(colors, next_colors):
            return colors
        colors = next_colors


def _same_partition(left: tuple[int, ...], right: tuple[int, ...]) -> bool:
    r"""Compare partitions independently of color-number permutations."""

    if len(left) != len(right):
        return False
    left_to_right: dict[int, int] = {}
    right_to_left: dict[int, int] = {}
    for left_color, right_color in zip(left, right):
        mapped_right = left_to_right.setdefault(left_color, right_color)
        mapped_left = right_to_left.setdefault(right_color, left_color)
        if mapped_right != right_color or mapped_left != left_color:
            return False
    return True


def _assign_colors(signatures: tuple[tuple[object, ...], ...]) -> tuple[int, ...]:
    r"""Assign contiguous colors using stable signature ordering."""

    unique = {signature for signature in signatures}
    ordered = sorted(unique, key=repr)
    identifiers = {signature: index for index, signature in enumerate(ordered)}
    return tuple(identifiers[signature] for signature in signatures)


def _base_key(node: RegularTypeNode) -> tuple[object, ...]:
    r"""Return the node label without child edges."""

    payload: tuple[object, ...]
    if node.payload is None:
        payload = ("none",)
    elif isinstance(node.payload, Fraction):
        payload = (
            "fraction",
            node.payload.numerator,
            node.payload.denominator,
        )
    else:
        payload = ("string", node.payload)
    return node.kind.value, payload


def _node_signature(
    node: RegularTypeNode,
    colors: tuple[int, ...],
) -> tuple[object, ...]:
    r"""Generate a refinement signature respecting ordered or set-like constructors."""

    child_colors = tuple(colors[child] for child in node.children)
    if node.kind in {
        RegularTypeNodeKind.INTERNAL_CHOICE,
        RegularTypeNodeKind.EXTERNAL_CHOICE,
    }:
        child_colors = tuple(sorted(set(child_colors)))
    return _base_key(node), child_colors


def _quotient_and_simplify(
    graph: RegularTypeTermGraph,
    colors: tuple[int, ...],
) -> RegularTypeTermGraph:
    r"""Quotient by bisimulation and renormalize choices and parallel composition."""

    representatives: dict[int, RegularTypeNode] = {}
    for node_id, color in enumerate(colors):
        representatives.setdefault(color, graph.nodes[node_id])
    specs: dict[int, _NodeSpec] = {}
    for color, node in representatives.items():
        children = tuple(colors[child] for child in node.children)
        if node.kind in {
            RegularTypeNodeKind.INTERNAL_CHOICE,
            RegularTypeNodeKind.EXTERNAL_CHOICE,
        }:
            children = tuple(sorted(set(children)))
        specs[color] = _NodeSpec(node.kind, node.payload, children)
    roots = tuple(colors[root] for root in graph.component_roots)
    specs, roots = _simplify_choice_aliases(specs, roots)
    return _freeze_specs(specs, roots)


def _simplify_choice_aliases(
    specs: dict[int, _NodeSpec],
    roots: tuple[int, ...],
) -> tuple[dict[int, _NodeSpec], tuple[int, ...]]:
    r"""Flatten and deduplicate choices; redirect singleton choices to their branch."""

    current = dict(specs)
    current_roots = roots
    while True:
        rewritten: dict[int, _NodeSpec] = {}
        redirects: dict[int, int] = {}
        changed = False
        for node_id, spec in current.items():
            if spec.kind not in {
                RegularTypeNodeKind.INTERNAL_CHOICE,
                RegularTypeNodeKind.EXTERNAL_CHOICE,
            }:
                rewritten[node_id] = spec
                continue
            leaves = tuple(
                sorted(
                    {
                        leaf
                        for child in spec.children
                        for leaf in _choice_leaves(
                            child,
                            spec.kind,
                            current,
                            frozenset(),
                        )
                    }
                )
            )
            if len(leaves) == 1 and leaves[0] != node_id:
                redirects[node_id] = leaves[0]
                changed = True
                continue
            updated = _NodeSpec(spec.kind, spec.payload, leaves)
            rewritten[node_id] = updated
            changed = changed or updated != spec

        if redirects:
            resolver = lambda item: _resolve_redirect(item, redirects)
            current = {
                resolver(node_id): _NodeSpec(
                    spec.kind,
                    spec.payload,
                    tuple(resolver(child) for child in spec.children),
                )
                for node_id, spec in rewritten.items()
                if resolver(node_id) == node_id
            }
            current_roots = tuple(resolver(root) for root in current_roots)
            continue
        current = rewritten
        if not changed:
            return current, current_roots


def _choice_leaves(
    node_id: int,
    kind: RegularTypeNodeKind,
    specs: dict[int, _NodeSpec],
    visiting: frozenset[int],
) -> tuple[int, ...]:
    r"""Collect non-choice leaves iteratively in depth-first order."""

    leaves: list[int] = []
    pending: list[tuple[int, frozenset[int]]] = [(node_id, visiting)]
    while pending:
        current, current_visiting = pending.pop()
        if current in current_visiting:
            leaves.append(current)
            continue
        spec = specs[current]
        if spec.kind is not kind:
            leaves.append(current)
            continue
        nested = current_visiting | {current}
        pending.extend(
            (child, nested) for child in reversed(spec.children)
        )
    return tuple(leaves)


def _resolve_redirect(node_id: int, redirects: dict[int, int]) -> int:
    r"""Resolve singleton-choice redirects and reject alias cycles."""

    visited: set[int] = set()
    current = node_id
    while current in redirects:
        if current in visited:
            raise ValueError("Choice simplification produced a redirect cycle")
        visited.add(current)
        current = redirects[current]
    return current


def _freeze_specs(
    specs: dict[int, _NodeSpec],
    roots: tuple[int, ...],
) -> RegularTypeTermGraph:
    r"""Remove unreachable classes and Empty parallel identities before freezing."""

    nonempty_roots = tuple(
        root for root in roots if specs[root].kind is not RegularTypeNodeKind.EMPTY
    )
    if nonempty_roots:
        normalized_roots = tuple(sorted(nonempty_roots))
    else:
        empty_roots = tuple(
            root for root in roots if specs[root].kind is RegularTypeNodeKind.EMPTY
        )
        if not empty_roots:
            raise ValueError("Regular configuration lost all roots without an Empty node")
        normalized_roots = (min(empty_roots),)

    reachable: set[int] = set()
    pending = list(normalized_roots)
    while pending:
        node_id = pending.pop()
        if node_id in reachable:
            continue
        reachable.add(node_id)
        pending.extend(specs[node_id].children)
    renumber = {
        old_id: new_id for new_id, old_id in enumerate(sorted(reachable))
    }
    nodes = tuple(
        RegularTypeNode(
            specs[old_id].kind,
            specs[old_id].payload,
            tuple(renumber[child] for child in specs[old_id].children),
        )
        for old_id in sorted(reachable)
    )
    return RegularTypeTermGraph(
        tuple(renumber[root] for root in normalized_roots),
        nodes,
    )


def normalized_type_from_state_key(
    value: EquiRecursiveStateKey,
) -> NormalizedConfigurationType:
    r"""Choose a deterministic normalized Type AST for display."""

    return _present_state_key(value).type_ast


def _present_state_key(value: EquiRecursiveStateKey) -> _StatePresentation:
    r"""Rebuild a display AST with visible-index mappings."""

    if not isinstance(value, EquiRecursiveStateKey):
        raise TypeError("State-key rendering requires EquiRecursiveStateKey")

    rendered_components = tuple(
        (term_index, _reify_process(value, root, ()))
        for term_index, root in enumerate(value.component_roots)
    )
    ordered_components = tuple(
        sorted(
            rendered_components,
            key=lambda item: (normalized_process_key(item[1]), item[0]),
        )
    )
    component_indices = _source_to_display_indices(
        tuple(term_index for term_index, _ in ordered_components),
        len(rendered_components),
    )
    internal_maps: list[tuple[int, ...]] = []
    interrupt_maps: list[tuple[int, ...]] = []
    for root in value.component_roots:
        node = value.nodes[root]
        if node.kind is RegularTypeNodeKind.INTERNAL_CHOICE:
            internal_maps.append(
                _ordered_child_index_map(
                    tuple(
                        _reify_process(value, child, (root,))
                        for child in node.children
                    ),
                    normalized_process_key,
                )
            )
        else:
            internal_maps.append(())

        if node.kind in {
            RegularTypeNodeKind.FINITE_DELAY,
            RegularTypeNodeKind.INFINITE_DELAY,
        }:
            interrupt_root = node.children[0]
            interrupt = value.nodes[interrupt_root]
            if interrupt.kind is RegularTypeNodeKind.EXTERNAL_CHOICE:
                branch_nodes = interrupt.children
            elif interrupt.kind in {
                RegularTypeNodeKind.INPUT,
                RegularTypeNodeKind.OUTPUT,
            }:
                branch_nodes = (interrupt_root,)
            else:
                branch_nodes = ()
            interrupt_maps.append(
                _ordered_child_index_map(
                    tuple(
                        _reify_angelic(value, child, (root,))
                        for child in branch_nodes
                    ),
                    normalized_angelic_key,
                )
            )
        else:
            interrupt_maps.append(())

    return _StatePresentation(
        NormalizedConfigurationType(
            process for _, process in ordered_components
        ),
        component_indices,
        tuple(internal_maps),
        tuple(interrupt_maps),
    )


def _ordered_child_index_map(
    values: tuple[NormalizedProcessType | NormalizedAngelicType, ...],
    key: Callable[[Any], tuple[Any, ...]],
) -> tuple[int, ...]:
    r"""Map original child positions to their normalized sorted positions."""

    if not values:
        return ()
    ordered_sources = tuple(
        source_index
        for source_index, _ in sorted(
            enumerate(values),
            key=lambda item: (key(item[1]), item[0]),
        )
    )
    return _source_to_display_indices(ordered_sources, len(values))


def _source_to_display_indices(
    ordered_sources: tuple[int, ...],
    item_count: int,
) -> tuple[int, ...]:
    r"""Invert display order into a source-to-display index tuple."""

    if len(ordered_sources) != item_count or set(ordered_sources) != set(
        range(item_count)
    ):
        raise ValueError("Presentation ordering must be a permutation")
    result = [0] * item_count
    for display_index, source_index in enumerate(ordered_sources):
        result[source_index] = display_index
    return tuple(result)


def _reify_process(
    graph: EquiRecursiveStateKey,
    node_id: int,
    path: tuple[int, ...],
) -> NormalizedProcessType:
    r"""Reconstruct process nodes and back edges as a De Bruijn syntax tree."""

    result = _reify_iterative(graph, node_id, path, angelic=False)
    assert isinstance(result, NormalizedProcessType)
    return result


def _reify_angelic(
    graph: EquiRecursiveStateKey,
    node_id: int,
    path: tuple[int, ...],
) -> NormalizedAngelicType:
    r"""Reconstruct normalized angelic inputs, outputs, and external choices."""

    result = _reify_iterative(graph, node_id, path, angelic=True)
    assert isinstance(result, NormalizedAngelicType)
    return result


def _reify_iterative(
    graph: EquiRecursiveStateKey,
    root: int,
    path: tuple[int, ...],
    *,
    angelic: bool,
) -> NormalizedProcessType | NormalizedAngelicType:
    r"""Reify cyclic graphs using an explicit postorder stack."""

    results: list[NormalizedProcessType | NormalizedAngelicType] = []
    pending: list[tuple[Any, ...]] = [("visit", root, path, angelic)]
    while pending:
        task = pending.pop()
        if task[0] == "finish":
            _, kind, node, start = task
            children = tuple(results[start:])
            del results[start:]
            if kind == "internal":
                body = make_normalized_internal_choice(children)
            elif kind == "finite":
                if not isinstance(node.payload, Fraction):
                    raise TypeError("Finite-delay state node has an invalid duration")
                body = NormalizedFiniteDelayType(
                    node.payload, children[0], children[1]
                )
            elif kind == "infinite":
                body = NormalizedInfiniteDelayType(children[0])
            elif kind in {"input", "output"}:
                if not isinstance(node.payload, str):
                    raise TypeError("Communication state node has an invalid channel")
                constructor = (
                    NormalizedInputType if kind == "input" else NormalizedOutputType
                )
                results.append(constructor(node.payload, children[0]))
                continue
            elif kind == "external":
                if not all(
                    isinstance(child, (NormalizedInputType, NormalizedOutputType))
                    for child in children
                ):
                    raise TypeError(
                        "External-choice state node contains a non-communication"
                    )
                results.append(make_normalized_external_choice(children))
                continue
            else:
                raise RuntimeError(f"Unsupported reification task: {kind}")
            assert isinstance(body, NormalizedProcessType)
            if _references_binder(body, 0):
                results.append(NormalizedMuType(body))
            else:
                results.append(_remove_unused_binder(body, 0))
            continue

        _, current_id, current_path, is_angelic = task
        if not is_angelic and current_id in current_path:
            results.append(
                NormalizedBoundTypeVar(
                    len(current_path) - 1 - current_path.index(current_id)
                )
            )
            continue
        node = graph.nodes[current_id]
        if is_angelic:
            if node.kind is RegularTypeNodeKind.NO_INTERRUPT:
                results.append(NormalizedNoInterruptType())
            elif node.kind in {
                RegularTypeNodeKind.INPUT,
                RegularTypeNodeKind.OUTPUT,
            }:
                start = len(results)
                kind = "input" if node.kind is RegularTypeNodeKind.INPUT else "output"
                pending.append(("finish", kind, node, start))
                pending.append(("visit", node.children[0], current_path, False))
            elif node.kind is RegularTypeNodeKind.EXTERNAL_CHOICE:
                start = len(results)
                pending.append(("finish", "external", node, start))
                for child in reversed(node.children):
                    pending.append(("visit", child, current_path, True))
            else:
                raise TypeError(
                    f"Angelic root has invalid regular-node kind: {node.kind.value!r}"
                )
            continue

        nested_path = current_path + (current_id,)
        if node.kind is RegularTypeNodeKind.EMPTY:
            results.append(NormalizedEmptyType())
        elif node.kind is RegularTypeNodeKind.BOTTOM:
            results.append(NormalizedBottomType())
        elif node.kind is RegularTypeNodeKind.INTERNAL_CHOICE:
            start = len(results)
            pending.append(("finish", "internal", node, start))
            for child in reversed(node.children):
                pending.append(("visit", child, nested_path, False))
        elif node.kind is RegularTypeNodeKind.FINITE_DELAY:
            start = len(results)
            pending.append(("finish", "finite", node, start))
            pending.append(("visit", node.children[1], nested_path, False))
            pending.append(("visit", node.children[0], nested_path, True))
        elif node.kind is RegularTypeNodeKind.INFINITE_DELAY:
            start = len(results)
            pending.append(("finish", "infinite", node, start))
            pending.append(("visit", node.children[0], nested_path, True))
        else:
            raise TypeError(
                f"Process root has invalid regular-node kind: {node.kind.value!r}"
            )
    if len(results) != 1:
        raise RuntimeError("Regular Type reification produced an invalid result")
    return results[0]


def _references_binder(value: NormalizedProcessType, depth: int) -> bool:
    r"""Check whether a process references the candidate virtual binder."""

    pending: list[tuple[object, int, bool]] = [(value, depth, False)]
    while pending:
        current, current_depth, angelic = pending.pop()
        if not angelic:
            if isinstance(current, (NormalizedEmptyType, NormalizedBottomType)):
                continue
            if isinstance(current, NormalizedBoundTypeVar):
                if current.index == current_depth:
                    return True
                continue
            if isinstance(current, NormalizedInternalChoiceType):
                pending.extend((branch, current_depth, False) for branch in current.branches)
            elif isinstance(current, NormalizedFiniteDelayType):
                pending.append((current.continuation, current_depth, False))
                pending.append((current.interrupts, current_depth, True))
            elif isinstance(current, NormalizedInfiniteDelayType):
                pending.append((current.interrupts, current_depth, True))
            elif isinstance(current, NormalizedMuType):
                pending.append((current.body, current_depth + 1, False))
            else:
                raise TypeError(
                    f"Unsupported normalized process: {type(current).__name__}"
                )
            continue
        if isinstance(current, NormalizedNoInterruptType):
            continue
        if isinstance(current, (NormalizedInputType, NormalizedOutputType)):
            pending.append((current.continuation, current_depth, False))
        elif isinstance(current, NormalizedExternalChoiceType):
            pending.extend((branch, current_depth, True) for branch in current.branches)
        else:
            raise TypeError(
                f"Unsupported normalized angelic type: {type(current).__name__}"
            )
    return False


def _remove_unused_binder(
    value: NormalizedProcessType,
    depth: int,
) -> NormalizedProcessType:
    r"""Remove an unused binder and lower outer De Bruijn indices."""

    results: list[NormalizedProcessType | NormalizedAngelicType] = []
    pending: list[tuple[Any, ...]] = [("visit", value, depth, False)]
    while pending:
        task = pending.pop()
        if task[0] == "finish":
            _, kind, current, start = task
            children = tuple(results[start:])
            del results[start:]
            if kind == "internal":
                results.append(make_normalized_internal_choice(children))
            elif kind == "finite":
                results.append(
                    NormalizedFiniteDelayType(
                        current.duration, children[0], children[1]
                    )
                )
            elif kind == "infinite":
                results.append(NormalizedInfiniteDelayType(children[0]))
            elif kind == "mu":
                results.append(NormalizedMuType(children[0]))
            elif kind == "input":
                results.append(NormalizedInputType(current.channel, children[0]))
            elif kind == "output":
                results.append(NormalizedOutputType(current.channel, children[0]))
            elif kind == "external":
                results.append(make_normalized_external_choice(children))
            else:
                raise RuntimeError(f"Unsupported binder-removal task: {kind}")
            continue
        _, current, current_depth, angelic = task
        if not angelic:
            if isinstance(current, (NormalizedEmptyType, NormalizedBottomType)):
                results.append(current)
            elif isinstance(current, NormalizedBoundTypeVar):
                if current.index == current_depth:
                    raise ValueError("Cannot remove a referenced recursion binder")
                results.append(
                    NormalizedBoundTypeVar(current.index - 1)
                    if current.index > current_depth
                    else current
                )
            elif isinstance(current, NormalizedInternalChoiceType):
                start = len(results)
                pending.append(("finish", "internal", current, start))
                for branch in reversed(current.branches):
                    pending.append(("visit", branch, current_depth, False))
            elif isinstance(current, NormalizedFiniteDelayType):
                start = len(results)
                pending.append(("finish", "finite", current, start))
                pending.append(("visit", current.continuation, current_depth, False))
                pending.append(("visit", current.interrupts, current_depth, True))
            elif isinstance(current, NormalizedInfiniteDelayType):
                start = len(results)
                pending.append(("finish", "infinite", current, start))
                pending.append(("visit", current.interrupts, current_depth, True))
            elif isinstance(current, NormalizedMuType):
                start = len(results)
                pending.append(("finish", "mu", current, start))
                pending.append(("visit", current.body, current_depth + 1, False))
            else:
                raise TypeError(
                    f"Unsupported normalized process: {type(current).__name__}"
                )
            continue
        if isinstance(current, NormalizedNoInterruptType):
            results.append(current)
        elif isinstance(current, (NormalizedInputType, NormalizedOutputType)):
            start = len(results)
            kind = "input" if isinstance(current, NormalizedInputType) else "output"
            pending.append(("finish", kind, current, start))
            pending.append(("visit", current.continuation, current_depth, False))
        elif isinstance(current, NormalizedExternalChoiceType):
            start = len(results)
            pending.append(("finish", "external", current, start))
            for branch in reversed(current.branches):
                pending.append(("visit", branch, current_depth, True))
        else:
            raise TypeError(
                f"Unsupported normalized angelic type: {type(current).__name__}"
            )
    if len(results) != 1 or not isinstance(results[0], NormalizedProcessType):
        raise RuntimeError("Binder removal produced an invalid process result")
    return results[0]


def _remove_unused_binder_angelic(
    value: NormalizedAngelicType,
    depth: int,
) -> NormalizedAngelicType:
    r"""Remove the same unused binder from angelic continuations."""

    # Reuse iterative process traversal through a temporary infinite-delay wrapper.
    wrapped = _remove_unused_binder(NormalizedInfiniteDelayType(value), depth)
    assert isinstance(wrapped, NormalizedInfiniteDelayType)
    return wrapped.interrupts


__all__ = [
    "build_regular_type_term_graph",
    "equi_recursive_equivalent",
    "equi_recursive_state_key",
    "minimize_regular_type_term_graph",
    "normalized_type_from_state_key",
]
