r"""在规范化 Type AST 上穷尽计算 Table 3 的全部一步转移。

实现采用项目确认的最大共同时间策略：时间边只前进到所有并行分量的下一个最早
有限 deadline；若全部可等待分量均为无穷时延，则生成带 ``infinity`` 的时间自循环。
内部/外部选择已经在规范化 AST 中按已确认的代数律取商。
"""

from __future__ import annotations

from dataclasses import dataclass
from fractions import Fraction

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
from .substitution import unfold_mu


@dataclass(frozen=True, slots=True)
class DerivedTransition:
    """尚未分配图状态编号的一条 Table 3 直接后继。"""

    target: NormalizedConfigurationType
    label: TransitionLabel
    derivation: TransitionDerivation


@dataclass(frozen=True, slots=True)
class _ProcessStep:
    """一个并行分量可独立完成的瞬时过程转移。"""

    target: NormalizedProcessType
    derivation: TransitionDerivation


@dataclass(frozen=True, slots=True)
class _CommunicationOffer:
    """一个 delay 分量经零或多层递归暴露出的通信分支。"""

    branch_index: int
    branch: NormalizedInputType | NormalizedOutputType
    recursion_depth: int


@dataclass(frozen=True, slots=True)
class _WaitProfile:
    """分量当前可等待的 deadline 与 ready set。"""

    deadline: Fraction | InfiniteTime
    ready: frozenset[ReadyAction]


def derive_one_step(
    state: NormalizedConfigurationType,
) -> tuple[DerivedTransition, ...]:
    """枚举给定规范状态按 Table 3 可执行的全部瞬时和最大时间转移。"""

    if not isinstance(state, NormalizedConfigurationType):
        raise TypeError("Table 3 semantics requires a normalized configuration")
    _validate_closed_configuration(state)
    transitions: list[DerivedTransition] = []
    components = state.components

    for index, component in enumerate(components):
        for process_step in _process_silent_steps(component):
            target = _replace_components(state, {index: process_step.target})
            transitions.append(
                DerivedTransition(
                    target,
                    SilentTransitionLabel(),
                    _with_component(process_step.derivation, index),
                )
            )

    offers = tuple(_communication_offers(component) for component in components)
    for left_index in range(len(components)):
        for right_index in range(left_index + 1, len(components)):
            for left_offer in offers[left_index]:
                for right_offer in offers[right_index]:
                    if not _offers_match(left_offer, right_offer):
                        continue
                    target = _replace_components(
                        state,
                        {
                            left_index: left_offer.branch.continuation,
                            right_index: right_offer.branch.continuation,
                        },
                    )
                    derivation = TransitionDerivation(
                        Table3Rule.COMMUNICATION,
                        component_indices=(left_index, right_index),
                        branch_indices=(
                            left_offer.branch_index,
                            right_offer.branch_index,
                        ),
                        channel=left_offer.branch.channel,
                    )
                    derivation = _wrap_recursion_derivation(
                        derivation,
                        left_index,
                        left_offer.recursion_depth,
                    )
                    derivation = _wrap_recursion_derivation(
                        derivation,
                        right_index,
                        right_offer.recursion_depth,
                    )
                    transitions.append(
                        DerivedTransition(
                            target,
                            SilentTransitionLabel(),
                            derivation,
                        )
                    )

    timed = _derive_maximal_time_step(state)
    if timed is not None:
        transitions.append(timed)
    return _deduplicate_derived(transitions)


def _process_silent_steps(value: NormalizedProcessType) -> tuple[_ProcessStep, ...]:
    """计算单个过程分量的 timeout、内部选择或递归继承瞬时步。"""

    if isinstance(value, NormalizedInternalChoiceType):
        return tuple(
            _ProcessStep(
                branch,
                TransitionDerivation(
                    Table3Rule.INTERNAL_CHOICE,
                    branch_indices=(index,),
                ),
            )
            for index, branch in enumerate(value.branches)
            if not isinstance(branch, NormalizedBottomType)
        )
    if isinstance(value, NormalizedFiniteDelayType) and value.duration == 0:
        return (
            _ProcessStep(
                value.continuation,
                TransitionDerivation(Table3Rule.TIMEOUT),
            ),
        )
    if isinstance(value, NormalizedMuType):
        unfolded = unfold_mu(value)
        return tuple(
            _ProcessStep(
                step.target,
                TransitionDerivation(
                    Table3Rule.RECURSION,
                    premises=(step.derivation,),
                ),
            )
            for step in _process_silent_steps(unfolded)
        )
    return ()


def _communication_offers(
    value: NormalizedProcessType,
    recursion_depth: int = 0,
) -> tuple[_CommunicationOffer, ...]:
    """提取 delay 顶层全部通信分支，并记录递归透明展开层数。"""

    if isinstance(value, (NormalizedFiniteDelayType, NormalizedInfiniteDelayType)):
        return tuple(
            _CommunicationOffer(index, branch, recursion_depth)
            for index, branch in enumerate(_communication_branches(value.interrupts))
        )
    if isinstance(value, NormalizedMuType):
        return _communication_offers(unfold_mu(value), recursion_depth + 1)
    return ()


def _communication_branches(
    value: NormalizedAngelicType,
) -> tuple[NormalizedInputType | NormalizedOutputType, ...]:
    """把规范 angelic type 统一查看为零个或多个通信分支。"""

    if isinstance(value, NormalizedNoInterruptType):
        return ()
    if isinstance(value, (NormalizedInputType, NormalizedOutputType)):
        return (value,)
    if isinstance(value, NormalizedExternalChoiceType):
        return value.branches
    raise TypeError(f"Unsupported normalized angelic type: {type(value).__name__}")


def _offers_match(left: _CommunicationOffer, right: _CommunicationOffer) -> bool:
    """判断两个通信 offer 是否同信道且输入输出方向互补。"""

    if left.branch.channel != right.branch.channel:
        return False
    return isinstance(left.branch, NormalizedInputType) != isinstance(
        right.branch,
        NormalizedInputType,
    )


def _ready_set(value: NormalizedAngelicType) -> frozenset[ReadyAction]:
    """根据 Table 3 的定义计算一个 angelic type 的 ready set。"""

    actions: set[ReadyAction] = set()
    for branch in _communication_branches(value):
        direction = (
            CommunicationDirection.INPUT
            if isinstance(branch, NormalizedInputType)
            else CommunicationDirection.OUTPUT
        )
        actions.add(ReadyAction(branch.channel, direction))
    return frozenset(actions)


def _wait_profile(value: NormalizedProcessType) -> _WaitProfile | None:
    """返回分量的剩余 deadline/ready set；不能等待时返回 None。"""

    if isinstance(value, NormalizedFiniteDelayType):
        if value.duration == 0:
            return None
        return _WaitProfile(value.duration, _ready_set(value.interrupts))
    if isinstance(value, NormalizedInfiniteDelayType):
        return _WaitProfile(InfiniteTime.VALUE, _ready_set(value.interrupts))
    if isinstance(value, NormalizedMuType):
        return _wait_profile(unfold_mu(value))
    return None


def _advance_process(
    value: NormalizedProcessType,
    duration: Fraction | InfiniteTime,
) -> _ProcessStep:
    """让一个已确认可等待的分量前进共同时间并给出规则证据。"""

    if isinstance(value, NormalizedFiniteDelayType):
        if not isinstance(duration, Fraction) or duration > value.duration:
            raise ValueError("Finite delay cannot advance by the requested duration")
        return _ProcessStep(
            NormalizedFiniteDelayType(
                value.duration - duration,
                value.interrupts,
                value.continuation,
            ),
            TransitionDerivation(Table3Rule.DELAY),
        )
    if isinstance(value, NormalizedInfiniteDelayType):
        return _ProcessStep(value, TransitionDerivation(Table3Rule.DELAY))
    if isinstance(value, NormalizedMuType):
        step = _advance_process(unfold_mu(value), duration)
        return _ProcessStep(
            step.target,
            TransitionDerivation(
                Table3Rule.RECURSION,
                premises=(step.derivation,),
            ),
        )
    raise ValueError(f"Process type {type(value).__name__} cannot wait")


def _derive_maximal_time_step(
    state: NormalizedConfigurationType,
) -> DerivedTransition | None:
    """在全部分量可等待且无互补 ready 动作时生成唯一最大共同时间步。"""

    profiles: list[_WaitProfile] = []
    for component in state.components:
        profile = _wait_profile(component)
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

    process_steps = tuple(
        _advance_process(component, duration) for component in state.components
    )
    target = NormalizedConfigurationType(step.target for step in process_steps)
    ready = frozenset(
        action for profile in profiles for action in profile.ready
    )
    if len(process_steps) == 1:
        derivation = process_steps[0].derivation
    else:
        derivation = TransitionDerivation(
            Table3Rule.PARALLEL_TIME,
            component_indices=tuple(range(len(process_steps))),
            premises=tuple(step.derivation for step in process_steps),
        )
    return DerivedTransition(
        target,
        TimedTransitionLabel(duration, ready),
        derivation,
    )


def _replace_components(
    state: NormalizedConfigurationType,
    replacements: dict[int, NormalizedProcessType],
) -> NormalizedConfigurationType:
    """替换指定并行分量并重新执行并行规范化。"""

    components = tuple(
        replacements.get(index, component)
        for index, component in enumerate(state.components)
    )
    return NormalizedConfigurationType(components)


def _with_component(
    derivation: TransitionDerivation,
    component_index: int,
) -> TransitionDerivation:
    """把局部过程规则证据关联到规范配置中的分量出现位置。"""

    return TransitionDerivation(
        derivation.rule,
        component_indices=(component_index,) + derivation.component_indices,
        branch_indices=derivation.branch_indices,
        channel=derivation.channel,
        premises=derivation.premises,
    )


def _wrap_recursion_derivation(
    derivation: TransitionDerivation,
    component_index: int,
    depth: int,
) -> TransitionDerivation:
    """按通信 offer 穿过的递归层数包裹 ``[P-mu]`` 证据。"""

    wrapped = derivation
    for _ in range(depth):
        wrapped = TransitionDerivation(
            Table3Rule.RECURSION,
            component_indices=(component_index,),
            premises=(wrapped,),
        )
    return wrapped


def _deduplicate_derived(
    transitions: list[DerivedTransition],
) -> tuple[DerivedTransition, ...]:
    """删除完全相同的规则实例，但保留同边的不同推导证据供图层合并。"""

    seen: set[DerivedTransition] = set()
    ordered: list[DerivedTransition] = []
    for transition in transitions:
        if transition in seen:
            continue
        seen.add(transition)
        ordered.append(transition)
    return tuple(ordered)


def _validate_closed_configuration(state: NormalizedConfigurationType) -> None:
    """防御性检查规范状态中的 De Bruijn 引用均落在所属递归作用域内。"""

    for component in state.components:
        _validate_closed_process(component, 0)


def _validate_closed_process(value: NormalizedProcessType, depth: int) -> None:
    """在当前 binder depth 下递归检查一个规范过程类型。"""

    if isinstance(value, (NormalizedEmptyType, NormalizedBottomType)):
        return
    if isinstance(value, NormalizedBoundTypeVar):
        if value.index >= depth:
            raise ValueError("Normalized state contains a free type variable")
        return
    if isinstance(value, NormalizedInternalChoiceType):
        for branch in value.branches:
            _validate_closed_process(branch, depth)
        return
    if isinstance(value, NormalizedFiniteDelayType):
        _validate_closed_angelic(value.interrupts, depth)
        _validate_closed_process(value.continuation, depth)
        return
    if isinstance(value, NormalizedInfiniteDelayType):
        _validate_closed_angelic(value.interrupts, depth)
        return
    if isinstance(value, NormalizedMuType):
        _validate_closed_process(value.body, depth + 1)
        return
    raise TypeError(f"Unsupported normalized process type: {type(value).__name__}")


def _validate_closed_angelic(value: NormalizedAngelicType, depth: int) -> None:
    """检查 angelic type 的全部通信 continuation 均为闭合过程类型。"""

    for branch in _communication_branches(value):
        _validate_closed_process(branch.continuation, depth)
