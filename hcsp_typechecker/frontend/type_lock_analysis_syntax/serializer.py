"""把锁自由、Bottom 错误自由结论和反例路径渲染成可审计文本。"""

from __future__ import annotations

from ...data_structures.type_lock_analysis import LockFreedomReport, TransitionPath
from ...data_structures.type_transition_graph import (
    InfiniteTime,
    SilentTransitionLabel,
    TimedTransitionLabel,
    TypeTransition,
    TypeTransitionGraph,
)
from ..normalized_type_syntax import format_normalized_type_ast


def _yes_no(value: bool) -> str:
    """把布尔性质结论转换成稳定中文展示。"""

    return "是" if value else "否"


def _format_ready(label: TimedTransitionLabel) -> str:
    """按通道和方向稳定排序 ready set。"""

    actions = sorted(
        (f"{action.channel}{action.direction.value}" for action in label.ready)
    )
    return "{" + ", ".join(actions) + "}"


def _format_label(transition: TypeTransition) -> str:
    """渲染静默标签或带时长和 ready set 的时间标签。"""

    label = transition.label
    if isinstance(label, SilentTransitionLabel):
        return "tau"
    if isinstance(label, TimedTransitionLabel):
        duration = "infinity" if label.duration is InfiniteTime.VALUE else str(label.duration)
        return f"time({duration}, ready={_format_ready(label)})"
    return repr(label)


def _format_edge(transition: TypeTransition) -> str:
    """以状态编号和标签渲染一条有向迁移。"""

    return f"S{transition.source} -- {_format_label(transition)} --> S{transition.target}"


def _format_derivation_tree(transition: TypeTransition, *, indent: str) -> list[str]:
    """用显式工作栈完整渲染边的全部嵌套 Table 3 推导证据。"""

    lines: list[str] = []
    pending: list[tuple[str, object, int]] = [
        ("visit", derivation, 0)
        for derivation in reversed(transition.derivations)
    ]
    while pending:
        operation, payload, depth = pending.pop()
        current_indent = indent + "  " * depth
        if operation == "close":
            lines.append(current_indent + "}")
            continue
        derivation = payload
        arguments: list[str] = []
        if derivation.component_indices:
            arguments.append(f"components={derivation.component_indices}")
        if derivation.branch_indices:
            arguments.append(f"branches={derivation.branch_indices}")
        if derivation.channel is not None:
            arguments.append(f"channel={derivation.channel!r}")
        head = derivation.rule.value + "(" + ", ".join(arguments) + ")"
        if depth == 0:
            head = "by " + head
        if not derivation.premises:
            lines.append(current_indent + head)
            continue
        lines.append(current_indent + head + " {")
        pending.append(("close", None, depth))
        pending.extend(
            ("visit", premise, depth + 1)
            for premise in reversed(derivation.premises)
        )
    return lines


def _format_path(path: TransitionPath, *, indent: str) -> list[str]:
    """逐边渲染路径及每条边保存的 Table 3 规则证据。"""

    if not path.transitions:
        return [f"{indent}S{path.start_state}  (empty prefix)"]
    lines: list[str] = []
    for transition in path.transitions:
        lines.append(f"{indent}{_format_edge(transition)}")
        lines.extend(_format_derivation_tree(transition, indent=indent + "  "))
    return lines


def format_lock_freedom_result(report: LockFreedomReport) -> str:
    """生成适合终端查看的简洁分析结果。"""

    lines = [
        "=== Type 行为正确性分析结果 ===",
        f"可达状态 : {report.reachable_state_count}",
        f"迁移数量 : {report.transition_count}",
        f"死锁自由 : {_yes_no(report.deadlock_free)}",
        f"活锁自由 : {_yes_no(report.livelock_free)}",
        f"锁自由   : {_yes_no(report.lock_free)}",
        f"错误终止自由 : {_yes_no(report.error_free)}",
        f"整体行为正确 : {_yes_no(report.behavior_correct)}",
    ]
    if report.deadlock_witness is not None:
        lines.append(
            "死锁反例 : " + _format_edge(report.deadlock_witness.infinite_wait)
        )
    if report.livelock_witness is not None:
        cycle = report.livelock_witness.cycle
        lines.append(
            f"活锁反例 : 静默环入口 S{cycle.start_state}，"
            f"环长 {len(cycle.transitions)}"
        )
    if report.bottom_error_witness is not None:
        witness = report.bottom_error_witness
        lines.append(
            f"Bottom 错误反例 : S{witness.prefix.end_state}，"
            f"分量 {witness.component_indices}"
        )
    return "\n".join(lines)


def _witness_state_ids(report: LockFreedomReport) -> tuple[int, ...]:
    """收集三类反例中出现的状态，供完整报告集中显示 Type。"""

    state_ids: set[int] = set()
    if report.deadlock_witness is not None:
        state_ids.update(report.deadlock_witness.prefix.state_ids)
        state_ids.add(report.deadlock_witness.infinite_wait.target)
    if report.livelock_witness is not None:
        state_ids.update(report.livelock_witness.prefix.state_ids)
        state_ids.update(report.livelock_witness.cycle.state_ids)
    if report.bottom_error_witness is not None:
        state_ids.update(report.bottom_error_witness.prefix.state_ids)
    return tuple(sorted(state_ids))


def format_lock_freedom_full(
    report: LockFreedomReport,
    graph: TypeTransitionGraph,
) -> str:
    """生成含规范 Type 状态、路径和规则编号的完整反例报告。"""

    lines = [format_lock_freedom_result(report), "", "=== 分析证据 ==="]
    if report.behavior_correct:
        lines.append(
            "所有可达状态均无死锁、无活锁，且不含 Bottom 错误终止根。"
        )

    if report.deadlock_witness is not None:
        witness = report.deadlock_witness
        lines.extend(["deadlock_witness {", "  reachable_prefix {"])
        lines.extend(_format_path(witness.prefix, indent="    "))
        lines.extend(
            [
                "  }",
                "  infinite_wait {",
                f"    {_format_edge(witness.infinite_wait)}",
            ]
        )
        lines.extend(
            _format_derivation_tree(witness.infinite_wait, indent="      ")
        )
        lines.extend(["  }", "}"])

    if report.livelock_witness is not None:
        witness = report.livelock_witness
        lines.extend(["livelock_witness {", "  reachable_prefix {"])
        lines.extend(_format_path(witness.prefix, indent="    "))
        lines.extend(["  }", "  silent_cycle {"])
        lines.extend(_format_path(witness.cycle, indent="    "))
        lines.extend(["  }", "}"])

    if report.bottom_error_witness is not None:
        witness = report.bottom_error_witness
        lines.extend(["bottom_error_witness {", "  reachable_prefix {"])
        lines.extend(_format_path(witness.prefix, indent="    "))
        lines.extend(
            [
                "  }",
                f"  error_state = S{witness.prefix.end_state}",
                f"  bottom_components = {witness.component_indices}",
                "}",
            ]
        )

    state_ids = _witness_state_ids(report)
    if state_ids:
        lines.append("witness_states {")
        for state_id in state_ids:
            rendered = format_normalized_type_ast(graph.states[state_id].type_ast)
            rendered_lines = rendered.splitlines() or [""]
            lines.append(f"  S{state_id} = {rendered_lines[0]}")
            lines.extend(f"    {line}" for line in rendered_lines[1:])
        lines.append("}")
    return "\n".join(lines)
