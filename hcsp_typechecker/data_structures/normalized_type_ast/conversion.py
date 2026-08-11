"""把现有行为 Type AST 单向转换为 Table 3 规范化 Type AST。"""

from __future__ import annotations

from ..type_ast.ast import (
    AngelicType,
    BottomType,
    ConfigurationType,
    EmptyType,
    ExternalChoiceType,
    FiniteDelayType,
    InfiniteDelayType,
    InputType,
    InternalChoiceType,
    MuType,
    NoInterruptType,
    OutputType,
    ParallelType,
    ProcessType,
    TypeVar,
)
from .ast import (
    NormalizedAngelicType,
    NormalizedBottomType,
    NormalizedBoundTypeVar,
    NormalizedConfigurationType,
    NormalizedEmptyType,
    NormalizedFiniteDelayType,
    NormalizedInfiniteDelayType,
    NormalizedInputType,
    NormalizedMuType,
    NormalizedNoInterruptType,
    NormalizedOutputType,
    NormalizedProcessType,
    make_normalized_external_choice,
    make_normalized_internal_choice,
)


class TypeNormalizationError(ValueError):
    """原 Type AST 含自由变量或不受支持结构时的规范化错误。"""


def normalize_type_ast(
    value: ConfigurationType,
) -> NormalizedConfigurationType:
    """将原配置 Type AST 转成唯一、不可变且可哈希的规范化配置。"""

    if not isinstance(value, ConfigurationType):
        raise TypeError("Type normalization requires a ConfigurationType root")
    components = _normalize_configuration(value, ())
    return NormalizedConfigurationType(components)


def _normalize_configuration(
    value: ConfigurationType,
    binders: tuple[str, ...],
) -> tuple[NormalizedProcessType, ...]:
    """展平原并行配置并逐个规范化其过程分量。"""

    if isinstance(value, ParallelType):
        flattened: list[NormalizedProcessType] = []
        for component in value.components:
            flattened.extend(_normalize_configuration(component, binders))
        return tuple(flattened)
    if isinstance(value, ProcessType):
        return (_normalize_process(value, binders),)
    raise TypeError(f"Unsupported configuration type: {type(value).__name__}")


def _normalize_process(
    value: ProcessType,
    binders: tuple[str, ...],
) -> NormalizedProcessType:
    """递归转换一个过程类型并消除选择与递归命名差异。"""

    if isinstance(value, EmptyType):
        return NormalizedEmptyType()
    if isinstance(value, BottomType):
        return NormalizedBottomType()
    if isinstance(value, TypeVar):
        try:
            reverse_index = binders[::-1].index(value.name)
        except ValueError as exc:
            raise TypeNormalizationError(
                f"Free type variable {value.name!r} cannot appear in a normalized state"
            ) from exc
        return NormalizedBoundTypeVar(reverse_index)
    if isinstance(value, InternalChoiceType):
        return make_normalized_internal_choice(
            _normalize_process(branch, binders) for branch in value.branches
        )
    if isinstance(value, FiniteDelayType):
        return NormalizedFiniteDelayType(
            value.duration,
            _normalize_angelic(value.interrupts, binders),
            _normalize_process(value.continuation, binders),
        )
    if isinstance(value, InfiniteDelayType):
        return NormalizedInfiniteDelayType(
            _normalize_angelic(value.interrupts, binders)
        )
    if isinstance(value, MuType):
        return NormalizedMuType(
            _normalize_process(value.body, binders + (value.variable,))
        )
    raise TypeError(f"Unsupported process type: {type(value).__name__}")


def _normalize_angelic(
    value: AngelicType,
    binders: tuple[str, ...],
) -> NormalizedAngelicType:
    """规范化空、单分支或多分支 angelic type。"""

    if isinstance(value, NoInterruptType):
        return NormalizedNoInterruptType()
    if isinstance(value, InputType):
        return NormalizedInputType(
            value.channel,
            _normalize_process(value.continuation, binders),
        )
    if isinstance(value, OutputType):
        return NormalizedOutputType(
            value.channel,
            _normalize_process(value.continuation, binders),
        )
    if isinstance(value, ExternalChoiceType):
        return make_normalized_external_choice(
            _normalize_communication(branch, binders)
            for branch in value.branches
        )
    raise TypeError(f"Unsupported angelic type: {type(value).__name__}")


def _normalize_communication(
    value: InputType | OutputType,
    binders: tuple[str, ...],
) -> NormalizedInputType | NormalizedOutputType:
    """转换一个多元外部选择中的输入或输出通信分支。"""

    normalized = _normalize_angelic(value, binders)
    if not isinstance(normalized, (NormalizedInputType, NormalizedOutputType)):
        raise TypeError("External-choice branch did not normalize to communication")
    return normalized
