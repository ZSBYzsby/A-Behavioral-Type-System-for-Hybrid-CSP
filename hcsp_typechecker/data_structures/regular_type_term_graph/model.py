r"""等递归正规树使用的有限循环 Type 项图数据结构。

``RegularTypeTermGraph`` 仍保留构造阶段的结点编号；后端完成双模拟最小化和
稳定重编号后生成 ``EquiRecursiveStateKey``。两种图都只包含实际 Type 构造，
``mu`` 与受绑定变量通过有向环表示，不占用独立结点。最小化项图既用于状态判重，
也是 Table 3 操作语义实际读取和改写的状态本体。
"""

from __future__ import annotations

from dataclasses import dataclass
from enum import Enum
from fractions import Fraction
from typing import TypeAlias

from ...identifiers import is_hcsp_identifier


class RegularTypeNodeKind(str, Enum):
    """正规 Type 项图中可观察的过程或 angelic 构造种类。"""

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
    """验证一个普通或规范项图结点的标签、载荷和子边元数。"""

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
    """最小化前有限循环 Type 项图中的一个带编号子边结点。"""

    kind: RegularTypeNodeKind
    payload: RegularTypePayload = None
    children: tuple[int, ...] = ()

    def __post_init__(self) -> None:
        """冻结子边并验证结点产生式。"""

        object.__setattr__(self, "children", tuple(self.children))
        _validate_node(self.kind, self.payload, self.children)


@dataclass(frozen=True, slots=True)
class CanonicalRegularTypeNode:
    """双模拟最小化后、使用稳定类别编号的一项正规 Type 结点。"""

    kind: RegularTypeNodeKind
    payload: RegularTypePayload = None
    children: tuple[int, ...] = ()

    def __post_init__(self) -> None:
        """冻结子边并验证规范结点产生式。"""

        object.__setattr__(self, "children", tuple(self.children))
        _validate_node(self.kind, self.payload, self.children)


def _validate_graph(
    component_roots: tuple[int, ...],
    nodes: tuple[RegularTypeNode | CanonicalRegularTypeNode, ...],
) -> None:
    """验证根、结点编号、引用范围和从配置根出发的可达性。"""

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
    """验证过程根与 angelic 子边符合 Type 项图的双类别产生式。"""

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
    """从规范 Type 构造出的有限循环项图，保留并行分量重数。"""

    component_roots: tuple[int, ...]
    nodes: tuple[RegularTypeNode, ...]

    def __post_init__(self) -> None:
        """冻结配置根和结点表并验证图内部引用。"""

        object.__setattr__(self, "component_roots", tuple(self.component_roots))
        object.__setattr__(self, "nodes", tuple(self.nodes))
        if not all(isinstance(node, RegularTypeNode) for node in self.nodes):
            raise TypeError("Regular type term graph requires RegularTypeNode values")
        _validate_graph(self.component_roots, self.nodes)


@dataclass(frozen=True, slots=True)
class EquiRecursiveStateKey:
    """正规树等价类的可哈希规范编码，也是 Table 3 的项图状态。"""

    component_roots: tuple[int, ...]
    nodes: tuple[CanonicalRegularTypeNode, ...]

    def __post_init__(self) -> None:
        """冻结最小项图并验证稳定编号引用。"""

        object.__setattr__(self, "component_roots", tuple(self.component_roots))
        object.__setattr__(self, "nodes", tuple(self.nodes))
        if not all(isinstance(node, CanonicalRegularTypeNode) for node in self.nodes):
            raise TypeError(
                "Equi-recursive state key requires CanonicalRegularTypeNode values"
            )
        _validate_graph(self.component_roots, self.nodes)
