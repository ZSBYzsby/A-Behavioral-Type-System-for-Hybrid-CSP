"""把 Table 3 状态转移图渲染为稳定、带缩进的只读文本。

输出包含初态、全部规范状态、全部去重边以及每条边保存的所有规则证据。状态内容
委托 ``normalized_type_syntax`` 渲染；本模块不解析图文本，也不参与状态判重或
Table 3 推导。
"""

from __future__ import annotations

from fractions import Fraction

from ...data_structures.type_transition_graph import (
    InfiniteTime,
    ReadyAction,
    SilentTransitionLabel,
    TimedTransitionLabel,
    TransitionDerivation,
    TypeState,
    TypeTransition,
    TypeTransitionGraph,
)
from ..normalized_type_syntax import format_normalized_type_ast


def format_type_transition_graph(value: TypeTransitionGraph) -> str:
    """输出初态、规范状态、转移标签和全部规则证据的完整图文本。"""

    if not isinstance(value, TypeTransitionGraph):
        raise TypeError("transition graph output requires a TypeTransitionGraph")
    lines = ["type transition graph {"]
    lines.append(_line(1, f"initial = S{value.initial_state}"))
    lines.extend(_render_states(value.states, 1))
    lines.extend(_render_transitions(value.transitions, 1))
    lines.append("}")
    return "\n".join(lines)


def _render_states(states: tuple[TypeState, ...], level: int) -> list[str]:
    """渲染按稳定编号排列的全部规范状态。"""

    lines = [_line(level, "states {")]
    for state in states:
        rendered = _indent_text(format_normalized_type_ast(state.type_ast), level + 1)
        lines.extend(_prepend_to_first_line(f"S{state.id} = ", rendered).splitlines())
    lines.append(_line(level, "}"))
    return lines


def _render_transitions(
    transitions: tuple[TypeTransition, ...],
    level: int,
) -> list[str]:
    """渲染全部有向边，并在每条边下保留所有合并后的推导证据。"""

    if not transitions:
        return [_line(level, "transitions {}")]
    lines = [_line(level, "transitions {")]
    for transition in transitions:
        lines.extend(_render_transition(transition, level + 1))
    lines.append(_line(level, "}"))
    return lines


def _render_transition(value: TypeTransition, level: int) -> list[str]:
    """输出一条边的端点、标签和一个非空 derivations 块。"""

    label = _format_label(value.label)
    lines = [
        _line(
            level,
            f"S{value.source} -- {label} --> S{value.target} by {{",
        )
    ]
    for derivation in value.derivations:
        lines.extend(_render_derivation(derivation, level + 1))
    lines.append(_line(level, "}"))
    return lines


def _render_derivation(
    value: TransitionDerivation,
    level: int,
) -> list[str]:
    """递归输出一条 Table 3 规则实例及其嵌套前提证据。"""

    arguments: list[str] = []
    if value.component_indices:
        arguments.append(
            "components=" + _format_indices(value.component_indices)
        )
    if value.branch_indices:
        arguments.append("branches=" + _format_indices(value.branch_indices))
    if value.channel is not None:
        arguments.append(f"channel={value.channel!r}")
    head = value.rule.value + "(" + ", ".join(arguments) + ")"
    if not value.premises:
        return [_line(level, head)]
    lines = [_line(level, head + " {")]
    for premise in value.premises:
        lines.extend(_render_derivation(premise, level + 1))
    lines.append(_line(level, "}"))
    return lines


def _format_label(
    value: SilentTransitionLabel | TimedTransitionLabel,
) -> str:
    """把无时转移写为 tau，把时间转移写为 time(duration, ready={...})。"""

    if isinstance(value, SilentTransitionLabel):
        return "tau"
    if isinstance(value, TimedTransitionLabel):
        ready = ", ".join(
            _format_ready_action(action)
            for action in sorted(
                value.ready,
                key=lambda item: (item.channel, item.direction.value),
            )
        )
        return (
            f"time({_format_time(value.duration)}, "
            f"ready={{{ready}}})"
        )
    raise TypeError(f"unsupported transition label: {type(value).__name__}")


def _format_ready_action(value: ReadyAction) -> str:
    """用用户熟悉的 ``channel?`` 或 ``channel!`` 输出 ready action。"""

    return value.channel + value.direction.value


def _format_time(value: Fraction | InfiniteTime) -> str:
    """输出最简有理数或独立的 infinity 时间字面量。"""

    if isinstance(value, InfiniteTime):
        return "infinity"
    if value.denominator == 1:
        return str(value.numerator)
    return f"{value.numerator}/{value.denominator}"


def _format_indices(values: tuple[int, ...]) -> str:
    """用方括号输出有序的分量或分支索引。"""

    return "[" + ", ".join(str(value) for value in values) + "]"


def _prepend_to_first_line(prefix: str, rendered: str) -> str:
    """把状态编号前缀插入已有规范 Type 文档首行的缩进之后。"""

    lines = rendered.splitlines()
    indentation = lines[0][: len(lines[0]) - len(lines[0].lstrip())]
    lines[0] = indentation + prefix + lines[0][len(indentation) :]
    return "\n".join(lines)


def _indent_text(rendered: str, level: int) -> str:
    """给多行文档统一增加指定层数的四空格缩进。"""

    prefix = _indent(level)
    return "\n".join(prefix + line for line in rendered.splitlines())


def _line(level: int, value: str) -> str:
    """构造带四空格层级缩进的一行。"""

    return _indent(level) + value


def _indent(level: int) -> str:
    """返回状态图输出使用的层级缩进。"""

    return "    " * level


__all__ = ["format_type_transition_graph"]
