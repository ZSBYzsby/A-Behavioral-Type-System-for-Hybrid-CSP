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

    return _render_iterative(value, level, is_angelic=False)


def _render_angelic(value: NormalizedAngelicType, level: int) -> str:
    """按原 ``angelic { ch? -> T, ... }`` 风格输出规范通信集合。"""

    return _render_iterative(value, level, is_angelic=True)


def _render_iterative(
    value: NormalizedProcessType | NormalizedAngelicType,
    level: int,
    *,
    is_angelic: bool,
) -> str:
    """用显式后序工作栈渲染深层 continuation 和递归体。"""

    results: list[str] = []
    pending: list[tuple[object, ...]] = [
        ("angelic" if is_angelic else "process", value, level)
    ]
    while pending:
        task = pending.pop()
        tag = task[0]
        if tag == "finish":
            _, kind, node, node_level, start = task
            children = tuple(results[start:])
            del results[start:]
            if kind == "internal":
                results.append(_render_block("internal", children, node_level))
            elif kind == "finite":
                prefix = f"delay({_format_duration(node.duration)})"
                if isinstance(node.interrupts, NormalizedNoInterruptType):
                    results.append(
                        _prepend_to_first_line(prefix + " then ", children[0])
                    )
                else:
                    interrupt = _prepend_to_first_line(
                        prefix + " interrupt ", children[0]
                    )
                    results.append(_append_document(interrupt, " then ", children[1]))
            elif kind == "infinite":
                results.append(
                    _prepend_to_first_line("forever interrupt ", children[0])
                )
            elif kind == "mu":
                results.append(_render_block("mu", children, node_level))
            elif kind == "angelic":
                rendered_branches = []
                for branch, continuation in zip(node, children):
                    marker = (
                        "?" if isinstance(branch, NormalizedInputType) else "!"
                    )
                    rendered_branches.append(
                        _prepend_to_first_line(
                            f"{branch.channel}{marker} -> ", continuation
                        )
                    )
                results.append(
                    _render_block("angelic", tuple(rendered_branches), node_level)
                )
            else:
                raise RuntimeError(f"unsupported normalized render task: {kind}")
            continue

        _, node, node_level = task
        if tag == "angelic":
            if isinstance(node, NormalizedNoInterruptType):
                results.append(_line(node_level, "angelic {}"))
                continue
            if isinstance(node, (NormalizedInputType, NormalizedOutputType)):
                branches = (node,)
            elif isinstance(node, NormalizedExternalChoiceType):
                branches = node.branches
            else:
                raise TypeError(
                    "unsupported normalized angelic type: "
                    f"{type(node).__name__}"
                )
            start = len(results)
            pending.append(("finish", "angelic", branches, node_level, start))
            for branch in reversed(branches):
                pending.append(("process", branch.continuation, node_level + 1))
            continue

        if isinstance(node, NormalizedEmptyType):
            results.append(_line(node_level, "empty"))
        elif isinstance(node, NormalizedBottomType):
            results.append(_line(node_level, "bottom"))
        elif isinstance(node, NormalizedBoundTypeVar):
            results.append(_line(node_level, f"recursion_position({node.index})"))
        elif isinstance(node, NormalizedInternalChoiceType):
            start = len(results)
            pending.append(("finish", "internal", node, node_level, start))
            for branch in reversed(node.branches):
                pending.append(("process", branch, node_level + 1))
        elif isinstance(node, NormalizedFiniteDelayType):
            start = len(results)
            pending.append(("finish", "finite", node, node_level, start))
            pending.append(("process", node.continuation, node_level))
            if not isinstance(node.interrupts, NormalizedNoInterruptType):
                pending.append(("angelic", node.interrupts, node_level))
        elif isinstance(node, NormalizedInfiniteDelayType):
            if isinstance(node.interrupts, NormalizedNoInterruptType):
                results.append(_line(node_level, "forever"))
            else:
                start = len(results)
                pending.append(("finish", "infinite", node, node_level, start))
                pending.append(("angelic", node.interrupts, node_level))
        elif isinstance(node, NormalizedMuType):
            start = len(results)
            pending.append(("finish", "mu", node, node_level, start))
            pending.append(("process", node.body, node_level + 1))
        else:
            raise TypeError(
                f"unsupported normalized process type: {type(node).__name__}"
            )

    if len(results) != 1:
        raise RuntimeError("normalized Type rendering produced invalid results")
    return results[0]


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
