r"""Render lock conclusions and counterexample paths as auditable text."""

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
    r"""Render Boolean property conclusions as English yes/no."""

    return 'yes' if value else 'no'


def _format_ready(label: TimedTransitionLabel) -> str:
    r"""Sort ready actions stably by channel and direction."""

    actions = sorted(
        (f"{action.channel}{action.direction.value}" for action in label.ready)
    )
    return "{" + ", ".join(actions) + "}"


def _format_label(transition: TypeTransition) -> str:
    r"""Render a silent or duration/ready-set transition label."""

    label = transition.label
    if isinstance(label, SilentTransitionLabel):
        return "tau"
    if isinstance(label, TimedTransitionLabel):
        duration = "infinity" if label.duration is InfiniteTime.VALUE else str(label.duration)
        return f"time({duration}, ready={_format_ready(label)})"
    return repr(label)


def _format_edge(transition: TypeTransition) -> str:
    r"""Render edge endpoints and label."""

    return f"S{transition.source} -- {_format_label(transition)} --> S{transition.target}"


def _format_derivation_tree(transition: TypeTransition, *, indent: str) -> list[str]:
    r"""Render nested Table 3 derivation evidence with an explicit stack."""

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
    r"""Render every path edge and its rule evidence."""

    if not path.transitions:
        return [f"{indent}S{path.start_state}  (empty prefix)"]
    lines: list[str] = []
    for transition in path.transitions:
        lines.append(f"{indent}{_format_edge(transition)}")
        lines.extend(_format_derivation_tree(transition, indent=indent + "  "))
    return lines


def format_lock_freedom_result(report: LockFreedomReport) -> str:
    r"""Render a concise terminal-oriented analysis result."""

    lines = [
        '=== Type behavioral correctness result ===',
        f"Reachable states : {report.reachable_state_count}",
        f"Transition count : {report.transition_count}",
        f"Deadlock-free : {_yes_no(report.deadlock_free)}",
        f"Livelock-free : {_yes_no(report.livelock_free)}",
        f"Lock-free    : {_yes_no(report.lock_free)}",
        f"Error-free : {_yes_no(report.error_free)}",
        f"Behavior correct : {_yes_no(report.behavior_correct)}",
    ]
    if report.deadlock_witness is not None:
        lines.append(
            'Deadlock witness : ' + _format_edge(report.deadlock_witness.infinite_wait)
        )
    if report.livelock_witness is not None:
        cycle = report.livelock_witness.cycle
        lines.append(
            f"Livelock witness : silent cycle starts at S{cycle.start_state}."
            f"cycle length {len(cycle.transitions)}"
        )
    if report.bottom_error_witness is not None:
        witness = report.bottom_error_witness
        lines.append(
            f"Bottom error witness : S{witness.prefix.end_state}."
            f"components {witness.component_indices}"
        )
    return "\n".join(lines)


def _witness_state_ids(report: LockFreedomReport) -> tuple[int, ...]:
    r"""Collect states referenced by the three witness kinds."""

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
    r"""Render witness states, paths, and Table 3 evidence in full."""

    lines = [format_lock_freedom_result(report), "", '=== Analysis evidence ===']
    if report.behavior_correct:
        lines.append(
            'All reachable states are deadlock-free and livelock-free, with no Bottom error termination root.'
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
