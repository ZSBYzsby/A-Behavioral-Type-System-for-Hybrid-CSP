"""把行为 Type AST 渲染为带缩进、可再次输入的规范 Type 语法。"""

from __future__ import annotations

from fractions import Fraction

from .ast import (
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
    """输出带 ``type`` 前缀和四空格缩进的完整源码。"""

    if not isinstance(value, ConfigurationType):
        raise TypeError("type source root must be a configuration type")
    rendered = _render_configuration_type(value, 0)
    return _prepend_to_first_line("type ", rendered)


def format_configuration_type(value: ConfigurationType) -> str:
    """输出不带 ``type`` 前缀的缩进 configuration type 语法。"""

    return _render_configuration_type(value, 0)


def _render_configuration_type(
    value: ConfigurationType,
    level: int,
) -> str:
    """在指定缩进层级渲染 configuration type。"""

    if isinstance(value, ParallelType):
        components = [
            _render_configuration_type(component, level + 1)
            for component in value.components
        ]
        return _render_block("parallel", components, level)
    if isinstance(value, ProcessType):
        return _render_process_type(value, level)
    raise TypeError(
        f"unsupported configuration type: {type(value).__name__}"
    )


def format_process_type(value: ProcessType) -> str:
    """输出缩进过程类型 ``T``；内部选择分支固定带圆括号。"""

    return _render_process_type(value, 0)


def _render_process_type(value: ProcessType, level: int) -> str:
    """在指定缩进层级渲染过程类型 ``T``。"""

    if isinstance(value, EmptyType):
        return _line(level, "empty")
    if isinstance(value, BottomType):
        return _line(level, "bottom")
    if isinstance(value, InternalChoiceType):
        branches = [
            _render_parenthesized_process(branch, level + 1)
            for branch in value.branches
        ]
        return _render_block("internal", branches, level)
    if isinstance(value, FiniteDelayType):
        prefix = f"delay({_format_duration(value.duration)})"
        if isinstance(value.interrupts, NoInterruptType):
            rendered = _render_process_type(value.continuation, level)
            return _prepend_to_first_line(prefix + " then ", rendered)
        interrupt = _render_angelic_type(value.interrupts, level)
        rendered = _prepend_to_first_line(prefix + " interrupt ", interrupt)
        return _append_document(
            rendered,
            " then ",
            _render_process_type(value.continuation, level),
        )
    if isinstance(value, InfiniteDelayType):
        if isinstance(value.interrupts, NoInterruptType):
            return _line(level, "forever")
        return _prepend_to_first_line(
            "forever interrupt ",
            _render_angelic_type(value.interrupts, level),
        )
    if isinstance(value, MuType):
        return _prepend_to_first_line(
            f"mu {value.variable}. ",
            _render_process_type(value.body, level),
        )
    if isinstance(value, TypeVar):
        return _line(level, value.name)
    raise TypeError(f"unsupported process type: {type(value).__name__}")


def format_angelic_type(value: AngelicType) -> str:
    """输出带缩进的中断类型 ``A`` 规范语法。"""

    return _render_angelic_type(value, 0)


def _render_angelic_type(value: AngelicType, level: int) -> str:
    """在指定缩进层级渲染中断类型 ``A``。"""

    if isinstance(value, NoInterruptType):
        return _line(level, "angelic {}")
    if isinstance(value, (InputType, OutputType)):
        branch_values = (value,)
    elif isinstance(value, ExternalChoiceType):
        branch_values = value.branches
    else:
        raise TypeError(f"unsupported angelic type: {type(value).__name__}")

    branches: list[str] = []
    for branch in branch_values:
        marker = "?" if isinstance(branch, InputType) else "!"
        branches.append(
            _prepend_to_first_line(
                f"{branch.channel}{marker} -> ",
                _render_process_type(branch.continuation, level + 1),
            )
        )
    return _render_block("angelic", branches, level)


def _render_parenthesized_process(value: ProcessType, level: int) -> str:
    """给一个 internal 分支添加保持规则分块所需的圆括号。"""

    rendered = _render_process_type(value, level)
    lines = rendered.splitlines()
    indentation = _indent(level)
    first = lines[0][len(indentation) :]
    if len(lines) == 1:
        return indentation + "(" + first + ")"
    return "\n".join(
        (
            indentation + "(",
            _indent_text(rendered, 1),
            indentation + ")",
        )
    )


def _render_block(name: str, entries: list[str], level: int) -> str:
    """渲染以花括号包围、以逗号分隔的缩进列表。"""

    if not entries:
        return _line(level, f"{name} {{}}")
    lines = [_line(level, f"{name} {{")]
    for index, entry in enumerate(entries):
        entry_lines = entry.splitlines()
        if index + 1 < len(entries):
            entry_lines[-1] += ","
        lines.extend(entry_lines)
    lines.append(_line(level, "}"))
    return "\n".join(lines)


def _append_document(left: str, separator: str, right: str) -> str:
    """把右侧文档首行接到左侧末行，并保留后续缩进。"""

    left_lines = left.splitlines()
    right_lines = right.splitlines()
    indentation = right_lines[0][: len(right_lines[0]) - len(right_lines[0].lstrip())]
    left_lines[-1] += separator + right_lines[0][len(indentation) :]
    left_lines.extend(right_lines[1:])
    return "\n".join(left_lines)


def _prepend_to_first_line(prefix: str, rendered: str) -> str:
    """把前缀放在文档首行现有缩进之后。"""

    lines = rendered.splitlines()
    indentation = lines[0][: len(lines[0]) - len(lines[0].lstrip())]
    lines[0] = indentation + prefix + lines[0][len(indentation) :]
    return "\n".join(lines)


def _indent_text(rendered: str, levels: int) -> str:
    """给文档中的每一行增加指定层数的四空格缩进。"""

    prefix = _indent(levels)
    return "\n".join(prefix + line for line in rendered.splitlines())


def _line(level: int, value: str) -> str:
    """构造带指定缩进的单行。"""

    return _indent(level) + value


def _indent(level: int) -> str:
    """返回项目 Type 规范输出采用的四空格缩进。"""

    return "    " * level


def _format_duration(value: Fraction) -> str:
    """把规范有理时延写成整数或最简分数。"""

    if value.denominator == 1:
        return str(value.numerator)
    return f"{value.numerator}/{value.denominator}"


__all__ = [
    "format_angelic_type",
    "format_configuration_type",
    "format_process_type",
    "format_type_source",
]
