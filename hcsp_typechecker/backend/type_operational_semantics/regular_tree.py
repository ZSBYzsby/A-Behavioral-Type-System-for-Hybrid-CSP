r"""把规范 Type 转成有限正规项图，并计算等递归状态键。

``mu`` 与 De Bruijn 变量在构图时解析成循环边；随后用有限图上的双模拟分区
求无限正规树等价类。内部/外部选择在递归等价暴露出新的嵌套或重复分支后再次
按既有代数律展平、去重，配置根则删除 Empty 单位元、排序并保留并行重数。模块还
能为最小项图确定性生成仅供状态图展示的规范 Type AST 代表，并记录项图根/子边
到该展示代表可见位置的映射，供 Table 3 推导证据使用。
"""

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
    """最小化期间允许临时单分支选择的私有结点说明。"""

    kind: RegularTypeNodeKind
    payload: str | Fraction | None
    children: tuple[int, ...]


@dataclass(frozen=True, slots=True)
class _StatePresentation:
    """项图状态的规范 AST 展示以及语义位置到展示位置的映射。

    项图按循环图的稳定结点编号排列根和选择子边；规范 AST 则按最终重建出的
    ``normalized_*_key`` 排序。递归回边会在展示时重新引入 ``mu``，所以两种顺序
    不能假定相同。映射以“出现位置”而不是结点编号为键，从而保留重复并行分量。
    """

    type_ast: NormalizedConfigurationType
    component_indices: tuple[int, ...]
    internal_branch_indices: tuple[tuple[int, ...], ...]
    interrupt_branch_indices: tuple[tuple[int, ...], ...]


class _TermGraphBuilder:
    """用可解析占位符把 De Bruijn 递归绑定转换为有限循环图。"""

    def __init__(self) -> None:
        """建立空结点表和仅用于 ``mu`` binder 的别名表。"""

        self.nodes: list[RegularTypeNode | None] = []
        self.aliases: dict[int, int] = {}

    def placeholder(self) -> int:
        """分配一个稍后指向递归体根的 binder 占位编号。"""

        node_id = len(self.nodes)
        self.nodes.append(None)
        return node_id

    def node(
        self,
        kind: RegularTypeNodeKind,
        payload: str | Fraction | None = None,
        children: Iterable[int] = (),
    ) -> int:
        """追加一个实际 Type 构造结点并返回其临时编号。"""

        # ``children`` 往往是会递归追加子结点的生成器。必须先把它完全求值，再按
        # 当前表长分配父结点编号，否则父编号会误指向生成器追加的第一个子结点。
        frozen_children = tuple(children)
        node_id = len(self.nodes)
        self.nodes.append(RegularTypeNode(kind, payload, frozen_children))
        return node_id

    def process(
        self,
        value: NormalizedProcessType,
        binders: tuple[int, ...],
    ) -> int:
        """递归转换一个规范过程类型并把变量引用解析到 binder 占位符。"""

        if isinstance(value, NormalizedEmptyType):
            return self.node(RegularTypeNodeKind.EMPTY)
        if isinstance(value, NormalizedBottomType):
            return self.node(RegularTypeNodeKind.BOTTOM)
        if isinstance(value, NormalizedBoundTypeVar):
            if value.index >= len(binders):
                raise ValueError("Normalized type contains a free recursion position")
            return binders[-1 - value.index]
        if isinstance(value, NormalizedInternalChoiceType):
            return self.node(
                RegularTypeNodeKind.INTERNAL_CHOICE,
                children=(self.process(branch, binders) for branch in value.branches),
            )
        if isinstance(value, NormalizedFiniteDelayType):
            return self.node(
                RegularTypeNodeKind.FINITE_DELAY,
                value.duration,
                (
                    self.angelic(value.interrupts, binders),
                    self.process(value.continuation, binders),
                ),
            )
        if isinstance(value, NormalizedInfiniteDelayType):
            return self.node(
                RegularTypeNodeKind.INFINITE_DELAY,
                children=(self.angelic(value.interrupts, binders),),
            )
        if isinstance(value, NormalizedMuType):
            binder = self.placeholder()
            body = self.process(value.body, binders + (binder,))
            self.aliases[binder] = body
            return binder
        raise TypeError(f"Unsupported normalized process type: {type(value).__name__}")

    def angelic(
        self,
        value: NormalizedAngelicType,
        binders: tuple[int, ...],
    ) -> int:
        """转换空、单通信或多通信 angelic 类型。"""

        if isinstance(value, NormalizedNoInterruptType):
            return self.node(RegularTypeNodeKind.NO_INTERRUPT)
        if isinstance(value, NormalizedInputType):
            return self.node(
                RegularTypeNodeKind.INPUT,
                value.channel,
                (self.process(value.continuation, binders),),
            )
        if isinstance(value, NormalizedOutputType):
            return self.node(
                RegularTypeNodeKind.OUTPUT,
                value.channel,
                (self.process(value.continuation, binders),),
            )
        if isinstance(value, NormalizedExternalChoiceType):
            return self.node(
                RegularTypeNodeKind.EXTERNAL_CHOICE,
                children=(self.angelic(branch, binders) for branch in value.branches),
            )
        raise TypeError(f"Unsupported normalized angelic type: {type(value).__name__}")

    def freeze(self, roots: Iterable[int]) -> RegularTypeTermGraph:
        """解析 binder 别名、删除占位编号并冻结全部可达实际结点。"""

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
        """沿 binder 别名解析到实际构造结点并拒绝纯别名递归环。"""

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
    """把闭合规范配置转换为不含 ``mu``/变量节点的有限循环项图。

    每个递归 binder 先建立占位符，受绑定 De Bruijn 引用再连接到对应占位符；
    guardedness 保证占位符最终可解析到一个真实 Type 构造。并行分量重数予以保留。
    """

    if not isinstance(value, NormalizedConfigurationType):
        raise TypeError("Regular type conversion requires a normalized configuration")
    builder = _TermGraphBuilder()
    roots = tuple(builder.process(component, ()) for component in value.components)
    return builder.freeze(roots)


def equi_recursive_state_key(
    value: NormalizedConfigurationType,
) -> EquiRecursiveStateKey:
    """返回忽略有限 ``mu`` 展开/折叠差异的稳定、可哈希状态键。

    该键而非展示 AST 是状态图判重和 Table 3 一步推导使用的状态本体。
    """

    return minimize_regular_type_term_graph(build_regular_type_term_graph(value))


def equi_recursive_equivalent(
    left: NormalizedConfigurationType,
    right: NormalizedConfigurationType,
) -> bool:
    """判断两个规范配置是否表示相同的等递归无限正规树。"""

    return equi_recursive_state_key(left) == equi_recursive_state_key(right)


def minimize_regular_type_term_graph(
    graph: RegularTypeTermGraph,
) -> EquiRecursiveStateKey:
    """按最大双模拟最小化项图，并对最终商图执行稳定编号。

    每轮先按节点标签和子类颜色求商，再重新展平、排序和去重选择节点；当商图稳定
    后，把普通节点转换为不可变 ``CanonicalRegularTypeNode`` 状态键。
    """

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
    """用稳定分区细化计算有限项图的最大构造保持双模拟。"""

    colors = _assign_colors(
        tuple((_base_key(node),) for node in graph.nodes)
    )
    while True:
        signatures = tuple(
            _node_signature(node, colors) for node in graph.nodes
        )
        next_colors = _assign_colors(signatures)
        if next_colors == colors:
            return colors
        colors = next_colors


def _assign_colors(signatures: tuple[tuple[object, ...], ...]) -> tuple[int, ...]:
    """按可比较签名的稳定排序为每个等价类分配连续编号。"""

    unique = {signature for signature in signatures}
    ordered = sorted(unique, key=repr)
    identifiers = {signature: index for index, signature in enumerate(ordered)}
    return tuple(identifiers[signature] for signature in signatures)


def _base_key(node: RegularTypeNode) -> tuple[object, ...]:
    """返回不含子边的结点标签键。"""

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
    """按有序构造或选择集合语义生成一次分区细化签名。"""

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
    """按双模拟类取商，并重新执行选择与并行的代数规范化。"""

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
    """展平同类选择；幂等化后只剩一支时把选择重定向到该分支。"""

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
    """沿同类选择边递归收集非选择叶；通信守卫保证不会有纯选择递归环。"""

    if node_id in visiting:
        return (node_id,)
    spec = specs[node_id]
    if spec.kind is not kind:
        return (node_id,)
    nested = visiting | {node_id}
    return tuple(
        leaf
        for child in spec.children
        for leaf in _choice_leaves(child, kind, specs, nested)
    )


def _resolve_redirect(node_id: int, redirects: dict[int, int]) -> int:
    """解析单分支选择重定向并防御性拒绝别名环。"""

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
    """删除不可达商类、规范并行 Empty 单位元并冻结连续编号项图。"""

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
    """为规范循环项图生成一个确定的规范 Type AST 展示代表。

    该转换只服务于状态图输出，不参与 Table 3 推导或状态判等。项图回边被重新
    写成 De Bruijn ``mu``；无回边的普通节点不会被多余的 ``mu`` 包裹。由于同一
    项图节点可能从多个位置到达，展示树可以复制共享子图，但其正规树语义保持不变。
    """

    return _present_state_key(value).type_ast


def _present_state_key(value: EquiRecursiveStateKey) -> _StatePresentation:
    """重建规范 AST，并记录项图位置在该 AST 中对应的可见索引。

    ``component_indices[i]`` 是项图第 ``i`` 个根在展示配置中的位置。另两个映射
    分别把该根为内部选择或 delay 时的项图分支位置转换为展示分支位置。不存在
    对应分支类别时保存空元组。
    """

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
    """返回子边原位置到最终规范排序位置的双射。"""

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
    """把按展示顺序排列的原位置转换为 ``原位置 -> 展示位置`` 元组。"""

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
    """沿当前 DFS 路径把一个过程节点及回边重建为 De Bruijn 语法树。"""

    if node_id in path:
        return NormalizedBoundTypeVar(len(path) - 1 - path.index(node_id))

    node = graph.nodes[node_id]
    nested_path = path + (node_id,)
    if node.kind is RegularTypeNodeKind.EMPTY:
        return NormalizedEmptyType()
    if node.kind is RegularTypeNodeKind.BOTTOM:
        return NormalizedBottomType()
    if node.kind is RegularTypeNodeKind.INTERNAL_CHOICE:
        body = make_normalized_internal_choice(
            _reify_process(graph, child, nested_path)
            for child in node.children
        )
    elif node.kind is RegularTypeNodeKind.FINITE_DELAY:
        if not isinstance(node.payload, Fraction):
            raise TypeError("Finite-delay state node has an invalid duration")
        body = NormalizedFiniteDelayType(
            node.payload,
            _reify_angelic(graph, node.children[0], nested_path),
            _reify_process(graph, node.children[1], nested_path),
        )
    elif node.kind is RegularTypeNodeKind.INFINITE_DELAY:
        body = NormalizedInfiniteDelayType(
            _reify_angelic(graph, node.children[0], nested_path)
        )
    else:
        raise TypeError(
            f"Process root has invalid regular-node kind: {node.kind.value!r}"
        )

    if _references_binder(body, 0):
        return NormalizedMuType(body)
    return _remove_unused_binder(body, 0)


def _reify_angelic(
    graph: EquiRecursiveStateKey,
    node_id: int,
    path: tuple[int, ...],
) -> NormalizedAngelicType:
    """把项图中的 angelic 子结构重建为规范输入、输出或外部选择。"""

    node = graph.nodes[node_id]
    if node.kind is RegularTypeNodeKind.NO_INTERRUPT:
        return NormalizedNoInterruptType()
    if node.kind is RegularTypeNodeKind.INPUT:
        if not isinstance(node.payload, str):
            raise TypeError("Input state node has an invalid channel")
        return NormalizedInputType(
            node.payload,
            _reify_process(graph, node.children[0], path),
        )
    if node.kind is RegularTypeNodeKind.OUTPUT:
        if not isinstance(node.payload, str):
            raise TypeError("Output state node has an invalid channel")
        return NormalizedOutputType(
            node.payload,
            _reify_process(graph, node.children[0], path),
        )
    if node.kind is RegularTypeNodeKind.EXTERNAL_CHOICE:
        branches = tuple(
            _reify_angelic(graph, child, path) for child in node.children
        )
        if not all(
            isinstance(branch, (NormalizedInputType, NormalizedOutputType))
            for branch in branches
        ):
            raise TypeError("External-choice state node contains a non-communication")
        return make_normalized_external_choice(branches)
    raise TypeError(
        f"Angelic root has invalid regular-node kind: {node.kind.value!r}"
    )


def _references_binder(value: NormalizedProcessType, depth: int) -> bool:
    """判断过程树是否引用当前待决定是否保留的虚拟 binder。"""

    if isinstance(value, (NormalizedEmptyType, NormalizedBottomType)):
        return False
    if isinstance(value, NormalizedBoundTypeVar):
        return value.index == depth
    if isinstance(value, NormalizedInternalChoiceType):
        return any(_references_binder(branch, depth) for branch in value.branches)
    if isinstance(value, NormalizedFiniteDelayType):
        return _references_binder_angelic(
            value.interrupts, depth
        ) or _references_binder(value.continuation, depth)
    if isinstance(value, NormalizedInfiniteDelayType):
        return _references_binder_angelic(value.interrupts, depth)
    if isinstance(value, NormalizedMuType):
        return _references_binder(value.body, depth + 1)
    raise TypeError(f"Unsupported normalized process: {type(value).__name__}")


def _references_binder_angelic(
    value: NormalizedAngelicType,
    depth: int,
) -> bool:
    """在 angelic continuation 中查询目标虚拟 binder。"""

    if isinstance(value, NormalizedNoInterruptType):
        return False
    if isinstance(value, (NormalizedInputType, NormalizedOutputType)):
        return _references_binder(value.continuation, depth)
    if isinstance(value, NormalizedExternalChoiceType):
        return any(
            _references_binder(branch.continuation, depth)
            for branch in value.branches
        )
    raise TypeError(f"Unsupported normalized angelic type: {type(value).__name__}")


def _remove_unused_binder(
    value: NormalizedProcessType,
    depth: int,
) -> NormalizedProcessType:
    """删除一个未被引用的虚拟 binder，并下移其外层 De Bruijn index。"""

    if isinstance(value, (NormalizedEmptyType, NormalizedBottomType)):
        return value
    if isinstance(value, NormalizedBoundTypeVar):
        if value.index == depth:
            raise ValueError("Cannot remove a referenced recursion binder")
        if value.index > depth:
            return NormalizedBoundTypeVar(value.index - 1)
        return value
    if isinstance(value, NormalizedInternalChoiceType):
        return make_normalized_internal_choice(
            _remove_unused_binder(branch, depth) for branch in value.branches
        )
    if isinstance(value, NormalizedFiniteDelayType):
        return NormalizedFiniteDelayType(
            value.duration,
            _remove_unused_binder_angelic(value.interrupts, depth),
            _remove_unused_binder(value.continuation, depth),
        )
    if isinstance(value, NormalizedInfiniteDelayType):
        return NormalizedInfiniteDelayType(
            _remove_unused_binder_angelic(value.interrupts, depth)
        )
    if isinstance(value, NormalizedMuType):
        return NormalizedMuType(_remove_unused_binder(value.body, depth + 1))
    raise TypeError(f"Unsupported normalized process: {type(value).__name__}")


def _remove_unused_binder_angelic(
    value: NormalizedAngelicType,
    depth: int,
) -> NormalizedAngelicType:
    """在 angelic continuation 中删除同一未使用虚拟 binder。"""

    if isinstance(value, NormalizedNoInterruptType):
        return value
    if isinstance(value, NormalizedInputType):
        return NormalizedInputType(
            value.channel,
            _remove_unused_binder(value.continuation, depth),
        )
    if isinstance(value, NormalizedOutputType):
        return NormalizedOutputType(
            value.channel,
            _remove_unused_binder(value.continuation, depth),
        )
    if isinstance(value, NormalizedExternalChoiceType):
        return make_normalized_external_choice(
            _remove_unused_binder_angelic(branch, depth)
            for branch in value.branches
        )
    raise TypeError(f"Unsupported normalized angelic type: {type(value).__name__}")


__all__ = [
    "build_regular_type_term_graph",
    "equi_recursive_equivalent",
    "equi_recursive_state_key",
    "minimize_regular_type_term_graph",
    "normalized_type_from_state_key",
]
