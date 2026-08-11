r"""直接在有限循环 Type 项图上计算 Table 3 的一步操作语义。

递归 ``mu`` 与递归变量在进入本模块前已经编译成项图回边；内部/外部选择也已经
按照项目采用的结合、交换和幂等律取商。因此，本模块不选择某棵规范 Type AST
作为状态代表，也不执行语法树展开。每条转移直接读取项图根，替换相应的根或
deadline 节点，再把目标项图裁剪并按等递归正规树重新最小化。

时间语义采用项目确认的“下一个关键 deadline”策略：全部非空并行分量必须能够
共同等待，且不同分量的 ready set 中不能存在互补动作；有限 deadline 取最小值，
全部为无穷时生成 ``infinity`` 时间自循环。

规则计算始终使用项图位置；写入公开 ``TransitionDerivation`` 前，再借助同一状态
确定生成的展示映射，把分量和分支索引转换为用户实际看到的规范 AST 位置。
"""

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
    """尚未分配状态编号的一条项图级 Table 3 直接后继。"""

    target: EquiRecursiveStateKey
    label: TransitionLabel
    derivation: TransitionDerivation


@dataclass(frozen=True, slots=True)
class _RootStep:
    """一个并行根能够独立完成的瞬时替换。"""

    target_root: int
    derivation: TransitionDerivation


@dataclass(frozen=True, slots=True)
class _CommunicationOffer:
    """一个 delay 根的 angelic 子图暴露出的通信分支。"""

    branch_index: int
    channel: str
    direction: CommunicationDirection
    continuation: int


@dataclass(frozen=True, slots=True)
class _WaitProfile:
    """一个项图根当前剩余的 deadline 与 ready set。"""

    deadline: Fraction | InfiniteTime
    ready: frozenset[ReadyAction]


def derive_one_step(
    state: EquiRecursiveStateKey,
) -> tuple[DerivedTransition, ...]:
    """枚举一个规范循环项图状态的全部瞬时和最大时间转移。

    枚举内容包括内部选择、零时延且后继非 ``Bottom`` 的 timeout、任意两并行
    分量之间的互补通信，以及满足等待前提时唯一的最大关键时间步。

    ``state`` 已经是等递归正规树的最小有限表示，所以 ``[P-mu]`` 在这里表现为
    沿回边读取 continuation，而不是额外的 AST 展开规则。返回的每个目标也立即
    重新最小化，因而调用者无需再次做状态等价判定。推导证据中的索引已经转换为
    ``normalized_type_from_state_key(state)`` 所展示的可见位置。
    """

    if not isinstance(state, EquiRecursiveStateKey):
        raise TypeError("Table 3 semantics requires an equi-recursive state key")

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
    """把项图通信参与者及分支位置转换为展示 AST 的可见位置。"""

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
    """计算项图根的内部选择与合法的零时延 timeout 瞬时步。

    Table 3 的 ``[P-triangleright]`` 具有 ``T != bottom`` 前提。后继为
    ``bottom`` 表示自然演化边界不可达；即使剩余时延已经是零，也只能尝试
    angelic 通信，不能通过一条 timeout 边进入 ``bottom``。
    """

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
    """提取 delay 根的全部输入/输出中断分支。"""

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
    """把 angelic 子图根统一查看为零个或多个通信节点编号。"""

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
    """判断两个 offer 是否同信道且输入输出方向互补。"""

    return (
        left.channel == right.channel
        and left.direction is not right.direction
    )


def _ready_set(
    state: EquiRecursiveStateKey,
    interrupt_root: int,
) -> frozenset[ReadyAction]:
    """直接从 angelic 子图计算 Table 3 ready set。"""

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
    """返回项图根的剩余 deadline/ready set；不能等待时返回 ``None``。"""

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
    """在全部根可等待且无互补 ready 动作时生成唯一最大共同时间步。

    至少一个有限 deadline 时取最小正值；全部为无限 delay 时生成 ``infinity``
    自循环。存在零时延、内部选择、Bottom 或可立即同步的互补 ready 动作时不生成。
    """

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
    """替换指定并行根并把目标项图重新裁剪、最小化。"""

    roots = tuple(
        replacements.get(index, root)
        for index, root in enumerate(state.component_roots)
    )
    return _canonicalize_graph(roots, state.nodes)


def _canonicalize_graph(
    roots: tuple[int, ...],
    nodes: tuple[CanonicalRegularTypeNode, ...],
) -> EquiRecursiveStateKey:
    """删除不可达节点，建立普通项图，再复用统一双模拟最小化器。"""

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
    """把局部项图位置转换为规范配置及其选择分支的可见位置。"""

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
    """删除完全相同的规则实例，保留同边的不同推导证据。"""

    seen: set[DerivedTransition] = set()
    ordered: list[DerivedTransition] = []
    for transition in transitions:
        if transition in seen:
            continue
        seen.add(transition)
        ordered.append(transition)
    return tuple(ordered)


__all__ = ["DerivedTransition", "derive_one_step"]
