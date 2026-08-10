"""既有 Type AST 到规范用户 Type 源码的无损序列化。"""

from __future__ import annotations

from fractions import Fraction

from ...data_structures.type_ast.ast import (
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


def format_type_source(value: ConfigurationType) -> str:
    """输出以 ``type`` 开头、可由 :func:`parse_type_source` 无损读回的文本。"""

    if not isinstance(value, ConfigurationType):
        raise TypeError("type source root must be a configuration type")
    return f"type {_format_configuration(value)}"


def _format_configuration(value: ConfigurationType) -> str:
    """格式化 ``mathcal T``；并行是唯一非过程 configuration 节点。"""

    if isinstance(value, ParallelType):
        return "parallel {" + ", ".join(
            _format_configuration(component) for component in value.components
        ) + "}"
    if isinstance(value, ProcessType):
        return _format_process(value)
    raise TypeError(f"unsupported configuration type: {type(value).__name__}")


def _format_process(value: ProcessType) -> str:
    """格式化过程类型 ``T``，只产生规范且无圆括号的具体语法。"""

    if isinstance(value, EmptyType):
        return "empty"
    if isinstance(value, BottomType):
        return "bottom"
    if isinstance(value, InternalChoiceType):
        return "internal {" + ", ".join(
            _format_process(branch) for branch in value.branches
        ) + "}"
    if isinstance(value, FiniteDelayType):
        interrupt = ""
        if not isinstance(value.interrupts, NoInterruptType):
            interrupt = f" interrupt {_format_angelic(value.interrupts)}"
        return (
            f"delay({_format_duration(value.duration)}){interrupt} then "
            f"{_format_process(value.continuation)}"
        )
    if isinstance(value, InfiniteDelayType):
        if isinstance(value.interrupts, NoInterruptType):
            return "forever"
        return f"forever interrupt {_format_angelic(value.interrupts)}"
    if isinstance(value, MuType):
        return f"mu {value.variable}. {_format_process(value.body)}"
    if isinstance(value, TypeVar):
        return value.name
    raise TypeError(f"unsupported process type: {type(value).__name__}")


def _format_angelic(value: AngelicType) -> str:
    """格式化中断类型 ``A``；空、单分支、多分支均保留唯一 AST 信息。"""

    if isinstance(value, NoInterruptType):
        return "angelic {}"
    if isinstance(value, InputType):
        return f"angelic {{{value.channel}? -> {_format_process(value.continuation)}}}"
    if isinstance(value, OutputType):
        return f"angelic {{{value.channel}! -> {_format_process(value.continuation)}}}"
    if isinstance(value, ExternalChoiceType):
        branches: list[str] = []
        for branch in value.branches:
            marker = "?" if isinstance(branch, InputType) else "!"
            branches.append(
                f"{branch.channel}{marker} -> {_format_process(branch.continuation)}"
            )
        return "angelic {" + ", ".join(branches) + "}"
    raise TypeError(f"unsupported angelic type: {type(value).__name__}")


def _format_duration(value: Fraction) -> str:
    """把规范 ``Fraction`` 写成无损的整数字面量或最简分数。"""

    if value.denominator == 1:
        return str(value.numerator)
    return f"{value.numerator}/{value.denominator}"
