r"""Render transition graphs as stable, indented text."""

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
    r"""Render initial state, normalized states, edge labels, and all rule evidence."""

    if not isinstance(value, TypeTransitionGraph):
        raise TypeError("transition graph output requires a TypeTransitionGraph")
    lines = ["type transition graph {"]
    lines.append(_line(1, f"initial = S{value.initial_state}"))
    lines.extend(_render_states(value.states, 1))
    lines.extend(_render_transitions(value.transitions, 1))
    lines.append("}")
    return "\n".join(lines)


def _render_states(states: tuple[TypeState, ...], level: int) -> list[str]:
    r"""Render normalized states in identifier order."""

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
    r"""Render all edges with their merged derivation evidence."""

    if not transitions:
        return [_line(level, "transitions {}")]
    lines = [_line(level, "transitions {")]
    for transition in transitions:
        lines.extend(_render_transition(transition, level + 1))
    lines.append(_line(level, "}"))
    return lines


def _render_transition(value: TypeTransition, level: int) -> list[str]:
    r"""Render one edge with endpoints, label, and nonempty derivations."""

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
    r"""Render nested Table 3 rule premises with an explicit task stack."""

    lines: list[str] = []
    pending: list[tuple[str, TransitionDerivation | None, int]] = [
        ("visit", value, level)
    ]
    while pending:
        action, current, current_level = pending.pop()
        if action == "close":
            lines.append(_line(current_level, "}"))
            continue
        assert current is not None
        arguments: list[str] = []
        if current.component_indices:
            arguments.append(
                "components=" + _format_indices(current.component_indices)
            )
        if current.branch_indices:
            arguments.append(
                "branches=" + _format_indices(current.branch_indices)
            )
        if current.channel is not None:
            arguments.append(f"channel={current.channel!r}")
        head = current.rule.value + "(" + ", ".join(arguments) + ")"
        if not current.premises:
            lines.append(_line(current_level, head))
            continue
        lines.append(_line(current_level, head + " {"))
        pending.append(("close", None, current_level))
        pending.extend(
            ("visit", premise, current_level + 1)
            for premise in reversed(current.premises)
        )
    return lines


def _format_label(
    value: SilentTransitionLabel | TimedTransitionLabel,
) -> str:
    r"""Render tau or time(duration, ready={...}) labels."""

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
    r"""Render ready actions as channel? or channel!."""

    return value.channel + value.direction.value


def _format_time(value: Fraction | InfiniteTime) -> str:
    r"""Render exact rational or infinity durations."""

    if isinstance(value, InfiniteTime):
        return "infinity"
    if value.denominator == 1:
        return str(value.numerator)
    return f"{value.numerator}/{value.denominator}"


def _format_indices(values: tuple[int, ...]) -> str:
    r"""Render ordered component or branch indices in brackets."""

    return "[" + ", ".join(str(value) for value in values) + "]"


def _prepend_to_first_line(prefix: str, rendered: str) -> str:
    r"""Insert a state prefix after the first line's indentation."""

    lines = rendered.splitlines()
    indentation = lines[0][: len(lines[0]) - len(lines[0].lstrip())]
    lines[0] = indentation + prefix + lines[0][len(indentation) :]
    return "\n".join(lines)


def _indent_text(rendered: str, level: int) -> str:
    r"""Add four-space indentation levels to a multiline document."""

    prefix = _indent(level)
    return "\n".join(prefix + line for line in rendered.splitlines())


def _line(level: int, value: str) -> str:
    r"""Create a line at the requested indentation level."""

    return _indent(level) + value


def _indent(level: int) -> str:
    r"""Return indentation for graph output."""

    return "    " * level


__all__ = ["format_type_transition_graph"]
