"""把正式行为 Type AST 单向降低为 Table 3 规范化 Type AST。

转换保留 ``Empty``、``Bottom``、delay 和通信的可观察区别，展平并规范化并行、
内部选择和外部选择，同时把递归变量名替换为 De Bruijn index。输出仍是有限树；
本模块不执行等递归双模拟、不计算 Table 3 后继，也不提供到原 Type AST 的逆转换。
"""

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
    """闭合性等规范化前提失败时抛出的领域错误。"""


def normalize_type_ast(
    value: ConfigurationType,
) -> NormalizedConfigurationType:
    """将闭合配置 Type AST 转成不可变、可哈希的规范化配置。

    并行、内部选择和外部选择在此按项目采用的代数律规范化；递归只消除绑定名称，
    有限展开等价留给循环项图处理。自由 ``TypeVar`` 会抛出
    :class:`TypeNormalizationError`。
    """

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
    """在当前递归绑定栈下转换过程类型并消除选择与 alpha 差异。"""

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
