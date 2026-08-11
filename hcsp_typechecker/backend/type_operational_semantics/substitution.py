"""规范化递归类型的 De Bruijn 移位、替换和单步展开。"""

from __future__ import annotations

from ...data_structures.normalized_type_ast import (
    NormalizedAngelicType,
    NormalizedBottomType,
    NormalizedBoundTypeVar,
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
)


def unfold_mu(value: NormalizedMuType) -> NormalizedProcessType:
    """按 ``mu t.T -> T{mu t.T/t}`` 对最外层递归绑定展开一次。"""

    if not isinstance(value, NormalizedMuType):
        raise TypeError("unfold_mu requires a NormalizedMuType")
    lifted_replacement = _shift_process(value, 1, 0)
    substituted = _substitute_process(value.body, 0, lifted_replacement, 0)
    return _shift_process(substituted, -1, 0)


def _shift_process(
    value: NormalizedProcessType,
    amount: int,
    cutoff: int,
) -> NormalizedProcessType:
    """把大于等于 cutoff 的自由 De Bruijn index 整体移动 amount。"""

    if isinstance(value, (NormalizedEmptyType, NormalizedBottomType)):
        return value
    if isinstance(value, NormalizedBoundTypeVar):
        if value.index < cutoff:
            return value
        shifted = value.index + amount
        if shifted < 0:
            raise ValueError("De Bruijn shift escaped the normalized type scope")
        return NormalizedBoundTypeVar(shifted)
    if isinstance(value, NormalizedInternalChoiceType):
        return make_normalized_internal_choice(
            _shift_process(branch, amount, cutoff) for branch in value.branches
        )
    if isinstance(value, NormalizedFiniteDelayType):
        return NormalizedFiniteDelayType(
            value.duration,
            _shift_angelic(value.interrupts, amount, cutoff),
            _shift_process(value.continuation, amount, cutoff),
        )
    if isinstance(value, NormalizedInfiniteDelayType):
        return NormalizedInfiniteDelayType(
            _shift_angelic(value.interrupts, amount, cutoff)
        )
    if isinstance(value, NormalizedMuType):
        return NormalizedMuType(
            _shift_process(value.body, amount, cutoff + 1)
        )
    raise TypeError(f"Unsupported normalized process type: {type(value).__name__}")


def _shift_angelic(
    value: NormalizedAngelicType,
    amount: int,
    cutoff: int,
) -> NormalizedAngelicType:
    """在 angelic type 的全部通信 continuation 中执行 De Bruijn 移位。"""

    if isinstance(value, NormalizedNoInterruptType):
        return value
    if isinstance(value, NormalizedInputType):
        return NormalizedInputType(
            value.channel,
            _shift_process(value.continuation, amount, cutoff),
        )
    if isinstance(value, NormalizedOutputType):
        return NormalizedOutputType(
            value.channel,
            _shift_process(value.continuation, amount, cutoff),
        )
    if isinstance(value, NormalizedExternalChoiceType):
        return make_normalized_external_choice(
            _shift_communication(branch, amount, cutoff)
            for branch in value.branches
        )
    raise TypeError(f"Unsupported normalized angelic type: {type(value).__name__}")


def _shift_communication(
    value: NormalizedInputType | NormalizedOutputType,
    amount: int,
    cutoff: int,
) -> NormalizedInputType | NormalizedOutputType:
    """移动一个通信分支 continuation 中的 De Bruijn index。"""

    shifted = _shift_angelic(value, amount, cutoff)
    if not isinstance(shifted, (NormalizedInputType, NormalizedOutputType)):
        raise TypeError("Communication shift returned a non-communication type")
    return shifted


def _substitute_process(
    value: NormalizedProcessType,
    target: int,
    replacement: NormalizedProcessType,
    depth: int,
) -> NormalizedProcessType:
    """在给定 binder depth 下替换目标 De Bruijn 变量。"""

    if isinstance(value, (NormalizedEmptyType, NormalizedBottomType)):
        return value
    if isinstance(value, NormalizedBoundTypeVar):
        if value.index == target + depth:
            return _shift_process(replacement, depth, 0)
        return value
    if isinstance(value, NormalizedInternalChoiceType):
        return make_normalized_internal_choice(
            _substitute_process(branch, target, replacement, depth)
            for branch in value.branches
        )
    if isinstance(value, NormalizedFiniteDelayType):
        return NormalizedFiniteDelayType(
            value.duration,
            _substitute_angelic(value.interrupts, target, replacement, depth),
            _substitute_process(value.continuation, target, replacement, depth),
        )
    if isinstance(value, NormalizedInfiniteDelayType):
        return NormalizedInfiniteDelayType(
            _substitute_angelic(value.interrupts, target, replacement, depth)
        )
    if isinstance(value, NormalizedMuType):
        return NormalizedMuType(
            _substitute_process(value.body, target, replacement, depth + 1)
        )
    raise TypeError(f"Unsupported normalized process type: {type(value).__name__}")


def _substitute_angelic(
    value: NormalizedAngelicType,
    target: int,
    replacement: NormalizedProcessType,
    depth: int,
) -> NormalizedAngelicType:
    """在所有通信 continuation 中替换目标 De Bruijn 变量。"""

    if isinstance(value, NormalizedNoInterruptType):
        return value
    if isinstance(value, NormalizedInputType):
        return NormalizedInputType(
            value.channel,
            _substitute_process(value.continuation, target, replacement, depth),
        )
    if isinstance(value, NormalizedOutputType):
        return NormalizedOutputType(
            value.channel,
            _substitute_process(value.continuation, target, replacement, depth),
        )
    if isinstance(value, NormalizedExternalChoiceType):
        return make_normalized_external_choice(
            _substitute_communication(branch, target, replacement, depth)
            for branch in value.branches
        )
    raise TypeError(f"Unsupported normalized angelic type: {type(value).__name__}")


def _substitute_communication(
    value: NormalizedInputType | NormalizedOutputType,
    target: int,
    replacement: NormalizedProcessType,
    depth: int,
) -> NormalizedInputType | NormalizedOutputType:
    """替换一个通信分支 continuation 中的目标递归变量。"""

    substituted = _substitute_angelic(value, target, replacement, depth)
    if not isinstance(substituted, (NormalizedInputType, NormalizedOutputType)):
        raise TypeError("Communication substitution returned non-communication")
    return substituted
