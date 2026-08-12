"""把行为 Type AST 渲染为带缩进、可再次输入的规范 Type 语法。"""

from __future__ import annotations

from fractions import Fraction
from typing import Any

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

    return _render_iterative(value, level, "configuration")


def format_process_type(value: ProcessType) -> str:
    """输出缩进过程类型 ``T``；内部选择分支固定带圆括号。"""

    return _render_process_type(value, 0)


def _render_process_type(value: ProcessType, level: int) -> str:
    """在指定缩进层级渲染过程类型 ``T``。"""

    return _render_iterative(value, level, "process")


def format_angelic_type(value: AngelicType) -> str:
    """输出带缩进的中断类型 ``A`` 规范语法。"""

    return _render_angelic_type(value, 0)


def _render_angelic_type(value: AngelicType, level: int) -> str:
    """在指定缩进层级渲染中断类型 ``A``。"""

    return _render_iterative(value, level, "angelic")


def _render_parenthesized_process(value: ProcessType, level: int) -> str:
    """给一个 internal 分支添加保持规则分块所需的圆括号。"""

    return _render_iterative(value, level, "parenthesized")


def _parenthesize_rendered(rendered: str, level: int) -> str:
    """给已经渲染的 internal 分支补上保持分组所需的圆括号。"""

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


def _render_iterative(value: Any, level: int, mode: str) -> str:
    """用显式后序工作栈渲染 Type，避免深 continuation 消耗调用栈。"""

    results: list[str] = []
    pending: list[tuple[Any, ...]] = [("visit", value, level, mode)]
    while pending:
        task = pending.pop()
        if task[0] == "finish":
            _, kind, current, current_level, start = task
            if kind == "communication":
                if not results:
                    raise RuntimeError("communication rendering lost its continuation")
                children = [results.pop()]
            else:
                children = results[start:]
                del results[start:]
            if kind == "parallel":
                rendered = _render_block("parallel", children, current_level)
            elif kind == "internal":
                rendered = _render_block("internal", children, current_level)
            elif kind == "finite-simple":
                prefix = f"delay({_format_duration(current.duration)})"
                rendered = _prepend_to_first_line(prefix + " then ", children[0])
            elif kind == "finite-interrupt":
                prefix = f"delay({_format_duration(current.duration)})"
                rendered = _append_document(
                    _prepend_to_first_line(prefix + " interrupt ", children[0]),
                    " then ",
                    children[1],
                )
            elif kind == "infinite":
                rendered = _prepend_to_first_line("forever interrupt ", children[0])
            elif kind == "mu":
                rendered = _prepend_to_first_line(
                    f"mu {current.variable}. ", children[0]
                )
            elif kind == "angelic":
                rendered = _render_block("angelic", children, current_level)
            elif kind == "communication":
                marker = "?" if isinstance(current, InputType) else "!"
                rendered = _prepend_to_first_line(
                    f"{current.channel}{marker} -> ", children[0]
                )
            elif kind == "parenthesized":
                rendered = _parenthesize_rendered(children[0], current_level)
            else:
                raise RuntimeError(f"unsupported render task: {kind}")
            results.append(rendered)
            continue

        _, current, current_level, current_mode = task
        if current_mode == "configuration":
            if isinstance(current, ParallelType):
                start = len(results)
                pending.append(("finish", "parallel", current, current_level, start))
                for component in reversed(current.components):
                    pending.append(
                        ("visit", component, current_level + 1, "configuration")
                    )
            elif isinstance(current, ProcessType):
                pending.append(("visit", current, current_level, "process"))
            else:
                raise TypeError(
                    f"unsupported configuration type: {type(current).__name__}"
                )
            continue
        if current_mode == "parenthesized":
            start = len(results)
            pending.append(
                ("finish", "parenthesized", current, current_level, start)
            )
            pending.append(("visit", current, current_level, "process"))
            continue
        if current_mode == "angelic":
            if isinstance(current, NoInterruptType):
                results.append(_line(current_level, "angelic {}"))
                continue
            if isinstance(current, (InputType, OutputType)):
                branches = (current,)
            elif isinstance(current, ExternalChoiceType):
                branches = current.branches
            else:
                raise TypeError(
                    f"unsupported angelic type: {type(current).__name__}"
                )
            start = len(results)
            pending.append(("finish", "angelic", current, current_level, start))
            for branch in reversed(branches):
                pending.append(
                    ("finish", "communication", branch, current_level + 1, -1)
                )
                pending.append(
                    ("visit", branch.continuation, current_level + 1, "process")
                )
            continue

        if isinstance(current, EmptyType):
            results.append(_line(current_level, "empty"))
        elif isinstance(current, BottomType):
            results.append(_line(current_level, "bottom"))
        elif isinstance(current, InternalChoiceType):
            start = len(results)
            pending.append(("finish", "internal", current, current_level, start))
            for branch in reversed(current.branches):
                pending.append(
                    ("visit", branch, current_level + 1, "parenthesized")
                )
        elif isinstance(current, FiniteDelayType):
            start = len(results)
            if isinstance(current.interrupts, NoInterruptType):
                pending.append(
                    ("finish", "finite-simple", current, current_level, start)
                )
                pending.append(
                    ("visit", current.continuation, current_level, "process")
                )
            else:
                pending.append(
                    ("finish", "finite-interrupt", current, current_level, start)
                )
                pending.append(
                    ("visit", current.continuation, current_level, "process")
                )
                pending.append(
                    ("visit", current.interrupts, current_level, "angelic")
                )
        elif isinstance(current, InfiniteDelayType):
            if isinstance(current.interrupts, NoInterruptType):
                results.append(_line(current_level, "forever"))
            else:
                start = len(results)
                pending.append(("finish", "infinite", current, current_level, start))
                pending.append(
                    ("visit", current.interrupts, current_level, "angelic")
                )
        elif isinstance(current, MuType):
            start = len(results)
            pending.append(("finish", "mu", current, current_level, start))
            pending.append(("visit", current.body, current_level, "process"))
        elif isinstance(current, TypeVar):
            results.append(_line(current_level, current.name))
        else:
            raise TypeError(f"unsupported process type: {type(current).__name__}")
    if len(results) != 1:
        raise RuntimeError("Type rendering produced an invalid result")
    return results[0]


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
