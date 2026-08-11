"""按用户 Type 风格输出规范化 Type AST 的稳定只读文本。

输出只服务第三个公共接口的摘要和状态节点展示：扁平选择直接列出分支，匿名递归
使用 ``mu { ... }``，De Bruijn 引用使用 ``recursion_position(index)``。本模块
不解析文本，也不把规范化 AST 转回正式 Type AST。
"""

from __future__ import annotations

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


def format_normalized_type_ast(value: NormalizedConfigurationType) -> str:
    """以 ``normalized type`` 开头输出稳定、四空格缩进的完整配置。"""

    if not isinstance(value, NormalizedConfigurationType):
        raise TypeError(
            "normalized type output requires a NormalizedConfigurationType"
        )
    rendered = _render_configuration(value, 0)
    return _prepend_to_first_line("normalized type ", rendered)


def _render_configuration(
    value: NormalizedConfigurationType,
    level: int,
) -> str:
    """按原 ``parallel`` 风格渲染排序后的一个或多个配置分量。"""

    if len(value.components) == 1:
        return _render_process(value.components[0], level)
    components = tuple(
        _render_process(component, level + 1)
        for component in value.components
    )
    return _render_block("parallel", components, level)


def _render_process(value: NormalizedProcessType, level: int) -> str:
    """渲染一个规范过程类型，并显式显示扁平选择和 De Bruijn 位置。"""

    if isinstance(value, NormalizedEmptyType):
        return _line(level, "empty")
    if isinstance(value, NormalizedBottomType):
        return _line(level, "bottom")
    if isinstance(value, NormalizedBoundTypeVar):
        return _line(level, f"recursion_position({value.index})")
    if isinstance(value, NormalizedInternalChoiceType):
        branches = tuple(
            _render_process(branch, level + 1)
            for branch in value.branches
        )
        return _render_block("internal", branches, level)
    if isinstance(value, NormalizedFiniteDelayType):
        prefix = f"delay({_format_duration(value.duration)})"
        continuation = _render_process(value.continuation, level)
        if isinstance(value.interrupts, NormalizedNoInterruptType):
            return _prepend_to_first_line(prefix + " then ", continuation)
        interrupt = _prepend_to_first_line(
            prefix + " interrupt ",
            _render_angelic(value.interrupts, level),
        )
        return _append_document(interrupt, " then ", continuation)
    if isinstance(value, NormalizedInfiniteDelayType):
        if isinstance(value.interrupts, NormalizedNoInterruptType):
            return _line(level, "forever")
        return _prepend_to_first_line(
            "forever interrupt ",
            _render_angelic(value.interrupts, level),
        )
    if isinstance(value, NormalizedMuType):
        return _render_block(
            "mu",
            (_render_process(value.body, level + 1),),
            level,
        )
    raise TypeError(f"unsupported normalized process type: {type(value).__name__}")


def _render_angelic(value: NormalizedAngelicType, level: int) -> str:
    """按原 ``angelic { ch? -> T, ... }`` 风格输出规范通信集合。"""

    if isinstance(value, NormalizedNoInterruptType):
        return _line(level, "angelic {}")
    if isinstance(value, (NormalizedInputType, NormalizedOutputType)):
        branches = (value,)
    elif isinstance(value, NormalizedExternalChoiceType):
        branches = value.branches
    else:
        raise TypeError(
            f"unsupported normalized angelic type: {type(value).__name__}"
        )

    rendered_branches: list[str] = []
    for branch in branches:
        marker = "?" if isinstance(branch, NormalizedInputType) else "!"
        rendered_branches.append(
            _prepend_to_first_line(
                f"{branch.channel}{marker} -> ",
                _render_process(branch.continuation, level + 1),
            )
        )
    return _render_block("angelic", tuple(rendered_branches), level)


def _render_block(name: str, entries: tuple[str, ...], level: int) -> str:
    """渲染带花括号、逗号和四空格缩进的多项结构。"""

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
    """把后继类型首行接到左文档末行，并保持后续缩进。"""

    left_lines = left.splitlines()
    right_lines = right.splitlines()
    indentation = right_lines[0][: len(right_lines[0]) - len(right_lines[0].lstrip())]
    left_lines[-1] += separator + right_lines[0][len(indentation) :]
    left_lines.extend(right_lines[1:])
    return "\n".join(left_lines)


def _prepend_to_first_line(prefix: str, rendered: str) -> str:
    """把语法前缀插入已有文档首行的缩进之后。"""

    lines = rendered.splitlines()
    indentation = lines[0][: len(lines[0]) - len(lines[0].lstrip())]
    lines[0] = indentation + prefix + lines[0][len(indentation) :]
    return "\n".join(lines)


def _format_duration(value: Fraction) -> str:
    """按原用户 Type 语法输出整数或最简有理时延。"""

    if value.denominator == 1:
        return str(value.numerator)
    return f"{value.numerator}/{value.denominator}"


def _line(level: int, value: str) -> str:
    """构造一行四空格层级缩进文本。"""

    return _indent(level) + value


def _indent(level: int) -> str:
    """返回规范化 Type 输出采用的层级缩进。"""

    return "    " * level


__all__ = ["format_normalized_type_ast"]
