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
        """用显式工作栈转换规范过程类型并解析递归位置。"""

        return self._build(value, binders, angelic=False)

    def angelic(
        self,
        value: NormalizedAngelicType,
        binders: tuple[int, ...],
    ) -> int:
        """用同一显式工作栈转换空、单通信或多通信 angelic 类型。"""

        return self._build(value, binders, angelic=True)

    def _build(
        self,
        root: NormalizedProcessType | NormalizedAngelicType,
        binders: tuple[int, ...],
        *,
        angelic: bool,
    ) -> int:
        """把一棵可能很深的规范类型树迭代地追加到有限项图。"""

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
        # 颜色编号本身只是实现细节；比较同色关系，避免同一稳定划分因编号
        # 置换而在两轮之间振荡。
        if _same_partition(colors, next_colors):
            return colors
        colors = next_colors


def _same_partition(left: tuple[int, ...], right: tuple[int, ...]) -> bool:
    """线性判断两组颜色是否定义同一个等价关系，忽略颜色编号置换。"""

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
    """沿同类选择边迭代收集非选择叶，并保持原深度优先顺序。"""

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

    result = _reify_iterative(graph, node_id, path, angelic=False)
    assert isinstance(result, NormalizedProcessType)
    return result


def _reify_angelic(
    graph: EquiRecursiveStateKey,
    node_id: int,
    path: tuple[int, ...],
) -> NormalizedAngelicType:
    """把项图中的 angelic 子结构重建为规范输入、输出或外部选择。"""

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
    """用显式后序栈把有限循环项图重建为用于展示的 De Bruijn AST。"""

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
    """判断过程树是否引用当前待决定是否保留的虚拟 binder。"""

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
    """删除一个未被引用的虚拟 binder，并下移其外层 De Bruijn index。"""

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
    """在 angelic continuation 中删除同一未使用虚拟 binder。"""

    # 复用过程入口的显式工作栈，并取临时无穷时延包装中的 angelic 子树。
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
