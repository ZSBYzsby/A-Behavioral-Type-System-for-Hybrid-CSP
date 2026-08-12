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
    # 先迭代展平顶层并行；过程/angelic 子树随后由统一后序工作栈转换。
    components: list[ProcessType] = []
    pending_configurations: list[ConfigurationType] = [value]
    while pending_configurations:
        current = pending_configurations.pop()
        if isinstance(current, ParallelType):
            pending_configurations.extend(reversed(current.components))
        elif isinstance(current, ProcessType):
            components.append(current)
        else:
            raise TypeError(
                f"Unsupported configuration type: {type(current).__name__}"
            )
    normalized = tuple(_normalize_subtree(component, ()) for component in components)
    return NormalizedConfigurationType(normalized)


def _normalization_children(
    value: ProcessType | AngelicType,
    binders: tuple[str, ...],
) -> tuple[tuple[ProcessType | AngelicType, tuple[str, ...]], ...]:
    """返回规范化后序遍历的子节点及其递归绑定环境。"""

    if isinstance(value, (InputType, OutputType)):
        return ((value.continuation, binders),)
    if isinstance(value, (ExternalChoiceType, InternalChoiceType)):
        return tuple((branch, binders) for branch in value.branches)
    if isinstance(value, FiniteDelayType):
        return ((value.interrupts, binders), (value.continuation, binders))
    if isinstance(value, InfiniteDelayType):
        return ((value.interrupts, binders),)
    if isinstance(value, MuType):
        return ((value.body, binders + (value.variable,)),)
    return ()


def _normalize_subtree(
    root: ProcessType,
    binders: tuple[str, ...],
) -> NormalizedProcessType:
    """使用显式后序栈规范化一棵过程类型，避免深 continuation 递归。"""

    TaskKey = tuple[int, tuple[str, ...]]
    results: dict[TaskKey, NormalizedProcessType | NormalizedAngelicType] = {}
    pending: list[
        tuple[ProcessType | AngelicType, tuple[str, ...], bool]
    ] = [(root, binders, False)]
    while pending:
        current, environment, exiting = pending.pop()
        key: TaskKey = (id(current), environment)
        if key in results:
            continue
        children = _normalization_children(current, environment)
        if not exiting and children:
            pending.append((current, environment, True))
            pending.extend(
                (child, child_environment, False)
                for child, child_environment in reversed(children)
            )
            continue

        child_values = tuple(
            results[(id(child), child_environment)]
            for child, child_environment in children
        )
        if isinstance(current, EmptyType):
            result: NormalizedProcessType | NormalizedAngelicType = NormalizedEmptyType()
        elif isinstance(current, BottomType):
            result = NormalizedBottomType()
        elif isinstance(current, TypeVar):
            try:
                reverse_index = environment[::-1].index(current.name)
            except ValueError as exc:
                raise TypeNormalizationError(
                    f"Free type variable {current.name!r} cannot appear in a normalized state"
                ) from exc
            result = NormalizedBoundTypeVar(reverse_index)
        elif isinstance(current, NoInterruptType):
            result = NormalizedNoInterruptType()
        elif isinstance(current, InputType):
            result = NormalizedInputType(current.channel, child_values[0])
        elif isinstance(current, OutputType):
            result = NormalizedOutputType(current.channel, child_values[0])
        elif isinstance(current, ExternalChoiceType):
            result = make_normalized_external_choice(child_values)
        elif isinstance(current, InternalChoiceType):
            result = make_normalized_internal_choice(child_values)
        elif isinstance(current, FiniteDelayType):
            result = NormalizedFiniteDelayType(
                current.duration, child_values[0], child_values[1]
            )
        elif isinstance(current, InfiniteDelayType):
            result = NormalizedInfiniteDelayType(child_values[0])
        elif isinstance(current, MuType):
            result = NormalizedMuType(child_values[0])
        else:
            raise TypeError(
                f"Unsupported behavioral type: {type(current).__name__}"
            )
        results[key] = result
    normalized_root = results[(id(root), binders)]
    if not isinstance(normalized_root, NormalizedProcessType):
        raise TypeError("Process normalization produced a non-process root")
    return normalized_root
