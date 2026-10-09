r"""Behavioral Types for Sections 4.1/4.2 with validated constructors."""

from __future__ import annotations

from abc import ABC, abstractmethod
from dataclasses import dataclass
from decimal import Decimal
from fractions import Fraction
from math import inf, isinf, isnan
from typing import Any, Iterable, Mapping

from ...identifiers import is_hcsp_identifier


class BehavioralType(ABC):
    r"""Abstract interface for behavioral and configuration types."""

    @abstractmethod
    def __str__(self) -> str:
        r"""Return a stable audit string close to paper notation."""


class ConfigurationType(BehavioralType, ABC):
    r"""Abstract category of composed configuration types."""


class ProcessType(ConfigurationType, ABC):
    r"""Abstract category of single-process behavioral types."""


class AngelicType(BehavioralType, ABC):
    r"""Interrupt/external-choice type A, distinct from process type T."""


@dataclass(frozen=True)
class NoInterruptType(AngelicType):
    r"""An angelic type with no communication interrupts."""

    def __str__(self) -> str:
        r"""Display the empty communication interrupt set."""
        return r"\emptyset"


@dataclass(frozen=True)
class EmptyType(ProcessType):
    r"""Normal empty process behavior with no further communication."""

    def __str__(self) -> str:
        r"""Use Table 2's 0 notation for empty communication behavior."""
        return "0"


@dataclass(frozen=True)
class BottomType(ProcessType):
    r"""Bottom behavior representing unreachable or erroneous termination."""

    def __str__(self) -> str:
        r"""Display Bottom using literal LaTeX notation."""
        return r"\bot"


@dataclass(frozen=True)
class TypeVar(ProcessType):
    r"""A recursive behavioral type variable reference."""

    name: str

    def __post_init__(self) -> None:
        r"""Require ASCII identifiers for type-variable names."""
        if not is_hcsp_identifier(self.name):
            raise ValueError("Type variable name must be a valid HCSP identifier")

    def __str__(self) -> str:
        r"""Display the recursive type-variable name."""
        return self.name


@dataclass(frozen=True)
class InputType(AngelicType):
    r"""One input synchronization; Theta defines its payload signature."""

    channel: str
    continuation: ProcessType

    def __post_init__(self) -> None:
        r"""Validate an input prefix's channel and process continuation."""
        if not is_hcsp_identifier(self.channel):
            raise ValueError("Input type channel must be a valid identifier")
        if not isinstance(self.continuation, ProcessType):
            raise TypeError("Input type continuation must be a process type T")

    def __str__(self) -> str:
        r"""Parenthesize the entire continuation of an input prefix."""
        return f"{self.channel}?.({self.continuation})"


@dataclass(frozen=True)
class OutputType(AngelicType):
    r"""One output synchronization; Theta defines its payload signature."""

    channel: str
    continuation: ProcessType

    def __post_init__(self) -> None:
        r"""Validate an output prefix's channel and process continuation."""
        if not is_hcsp_identifier(self.channel):
            raise ValueError("Output type channel must be a valid identifier")
        if not isinstance(self.continuation, ProcessType):
            raise TypeError("Output type continuation must be a process type T")

    def __str__(self) -> str:
        r"""Parenthesize the entire continuation of an output prefix."""
        return f"{self.channel}!.({self.continuation})"


CommunicationType = InputType | OutputType


@dataclass(frozen=True)
class ExternalChoiceType(AngelicType):
    r"""At least two externally selected communication branches."""

    branches: tuple[CommunicationType, ...]

    def __init__(self, branches: Iterable[CommunicationType]):
        r"""Freeze at least two communication branches in canonical external-choice form."""
        items = tuple(branches)
        if len(items) < 2:
            raise ValueError(
                "ExternalChoiceType requires at least two communication branches; "
                "use NoInterruptType/InputType/OutputType for zero or one branch"
            )
        if not all(isinstance(item, (InputType, OutputType)) for item in items):
            raise TypeError(
                "External choice branches must be InputType or OutputType"
            )
        object.__setattr__(self, "branches", items)

    def __str__(self) -> str:
        r"""Render parenthesized communication branches with the paper's external-choice
        notation.
        """
        return r" \sqcap ".join(f"({branch})" for branch in self.branches)


def make_external_choice(branches: Iterable[CommunicationType]) -> AngelicType:
    r"""Canonicalize zero, one, or multiple angelic branches."""

    items = tuple(branches)
    if not all(isinstance(item, (InputType, OutputType)) for item in items):
        raise TypeError("Angelic choice branches must be InputType or OutputType")
    if not items:
        return NoInterruptType()
    if len(items) == 1:
        return items[0]
    return ExternalChoiceType(items)


@dataclass(frozen=True)
class InternalChoiceType(ProcessType):
    r"""Internal nondeterministic choice among process types."""

    branches: tuple[ProcessType, ...]

    def __init__(self, branches: Iterable[ProcessType]):
        r"""Preserve internal-choice grouping and validate process branches."""
        items = tuple(branches)
        if not all(isinstance(branch, ProcessType) for branch in items):
            raise TypeError("Internal choice branches must be process types T")
        if len(items) < 2:
            raise ValueError("InternalChoiceType requires at least two branches")
        object.__setattr__(self, "branches", items)

    def __str__(self) -> str:
        r"""Render parenthesized internal branches with the paper's choice notation."""
        return r" \sqcup ".join(f"({branch})" for branch in self.branches)


def _normalize_finite_duration(duration: Any) -> Fraction:
    r"""Require an exact nonnegative finite rational duration."""

    if isinstance(duration, bool):
        raise ValueError("Type duration must be rational, not Boolean")
    if isinstance(duration, Fraction):
        value = duration
    elif isinstance(duration, int):
        value = Fraction(duration)
    elif isinstance(duration, Decimal):
        if duration.is_nan() or duration.is_infinite():
            raise ValueError("Type duration must be a finite rational number")
        value = Fraction(duration)
    elif isinstance(duration, float):
        if isnan(duration) or isinf(duration):
            raise ValueError("Type duration must be a finite rational number")
        value = Fraction(str(duration))
    else:
        raise TypeError("Type duration must be a rational number")
    if value < 0:
        raise ValueError("Type duration must be non-negative")
    return value


@dataclass(frozen=True)
class FiniteDelayType(ProcessType):
    r"""Finite delay with angelic interrupts and a timeout continuation."""

    duration: Fraction
    interrupts: AngelicType
    continuation: ProcessType

    def __init__(
        self,
        duration: Any,
        interrupts: AngelicType,
        continuation: ProcessType,
    ):
        r"""Validate a finite duration, interrupts, and timeout continuation."""
        if not isinstance(interrupts, AngelicType):
            raise TypeError("Finite delay interrupts must be an angelic type A")
        if not isinstance(continuation, ProcessType):
            raise TypeError("Finite delay continuation must be a process type T")
        object.__setattr__(self, "duration", _normalize_finite_duration(duration))
        object.__setattr__(self, "interrupts", interrupts)
        object.__setattr__(self, "continuation", continuation)

    def __str__(self) -> str:
        r"""Use the paper's finite-delay abbreviations according to interrupt and tail types."""
        if isinstance(self.continuation, BottomType):
            return f"delay({self.duration}) \\unrhd ({self.interrupts})"
        if isinstance(self.interrupts, NoInterruptType):
            return f"delay({self.duration}).({self.continuation})"
        return (
            f"delay({self.duration}) \\unrhd ({self.interrupts}) "
            f"\\triangleright ({self.continuation})"
        )


@dataclass(frozen=True)
class InfiniteDelayType(ProcessType):
    r"""Infinite delay with an unreachable Bottom timeout continuation."""

    interrupts: AngelicType

    def __post_init__(self) -> None:
        r"""Require an angelic interrupt set for infinite delay."""
        if not isinstance(self.interrupts, AngelicType):
            raise TypeError("Infinite delay interrupts must be an angelic type A")

    def __str__(self) -> str:
        r"""Display infinite delay, omitting an empty interrupt set."""
        if isinstance(self.interrupts, NoInterruptType):
            return "delay(infinity)"
        return f"delay(infinity) \\unrhd ({self.interrupts})"


def make_delay_type(
    duration: Any,
    interrupts: AngelicType,
    continuation: ProcessType,
) -> ProcessType:
    r"""Build a finite or infinite delay from Table 2's d, A, and T."""

    if not isinstance(interrupts, AngelicType):
        raise TypeError("Delay interrupts must be an angelic type A")
    if not isinstance(continuation, ProcessType):
        raise TypeError("Delay continuation must be a process type T")

    if isinstance(duration, float) and isinf(duration):
        if duration > 0:
            # Infinite waiting has no timeout transition; normalize every fallback to Bottom.
            return InfiniteDelayType(interrupts)
        raise ValueError("Type duration cannot be negative infinity")
    if isinstance(duration, Decimal) and duration.is_infinite():
        if duration > 0:

            return InfiniteDelayType(interrupts)
        raise ValueError("Type duration cannot be negative infinity")

    finite = _normalize_finite_duration(duration)
    return FiniteDelayType(finite, interrupts, continuation)


@dataclass(frozen=True)
class MuType(ProcessType):
    r"""A communication-guarded recursive type mu t.T."""

    variable: str
    body: ProcessType

    def __post_init__(self) -> None:
        r"""Validate the binder, process body, and communication guards."""
        if not is_hcsp_identifier(self.variable):
            raise ValueError(
                "Recursive type variable must be a valid HCSP identifier"
            )
        if not isinstance(self.body, ProcessType):
            raise TypeError("Recursive type body must be a process type T")
        if _contains_type_var(self.body, self.variable) and not _type_var_guarded(
            self.body,
            self.variable,
        ):
            raise ValueError(
                f"Recursive type variable {self.variable!r} is not communication-guarded"
            )

    def __str__(self) -> str:
        r"""Display recursion using the paper's mu notation."""
        return f"mu {self.variable}.({self.body})"


@dataclass(frozen=True)
class ParallelType(ConfigurationType):
    r"""Composition of at least two configuration types."""

    components: tuple[ConfigurationType, ...]

    def __init__(self, components: Iterable[ConfigurationType]):
        r"""Flatten parallel types and validate component count and syntax categories."""
        flat: list[ConfigurationType] = []
        for component in components:
            if isinstance(component, ParallelType):
                flat.extend(component.components)
            elif isinstance(component, ConfigurationType):
                flat.append(component)
            else:
                raise TypeError(
                    "Parallel components must be process or configuration types"
                )
        if len(flat) < 2:
            raise ValueError("ParallelType requires at least two components")
        object.__setattr__(self, "components", tuple(flat))

    def __str__(self) -> str:
        r"""Display parenthesized configuration components separated by parallel bars."""
        return " | ".join(f"({component})" for component in self.components)


def _contains_type_var(value: BehavioralType, name: str) -> bool:
    r"""Find type-variable references not shadowed by an inner mu."""

    pending: list[BehavioralType] = [value]
    while pending:
        current = pending.pop()
        if isinstance(current, TypeVar):
            if current.name == name:
                return True
        elif isinstance(current, (InputType, OutputType)):
            pending.append(current.continuation)
        elif isinstance(current, (ExternalChoiceType, InternalChoiceType)):
            pending.extend(reversed(current.branches))
        elif isinstance(current, FiniteDelayType):
            pending.extend((current.continuation, current.interrupts))
        elif isinstance(current, InfiniteDelayType):
            pending.append(current.interrupts)
        elif isinstance(current, MuType) and current.variable != name:
            pending.append(current.body)
        elif isinstance(current, ParallelType):
            pending.extend(reversed(current.components))
    return False


def _type_var_guarded(
    value: BehavioralType,
    name: str,
    under_communication: bool = False,
) -> bool:
    r"""Require communication guards on every free reference to a type variable."""

    pending: list[tuple[BehavioralType, bool]] = [(value, under_communication)]
    while pending:
        current, guarded = pending.pop()
        if isinstance(current, TypeVar):
            if current.name == name and not guarded:
                return False
        elif isinstance(current, (InputType, OutputType)):
            pending.append((current.continuation, True))
        elif isinstance(current, (ExternalChoiceType, InternalChoiceType)):
            pending.extend((branch, guarded) for branch in current.branches)
        elif isinstance(current, FiniteDelayType):
            pending.extend(
                ((current.interrupts, guarded), (current.continuation, guarded))
            )
        elif isinstance(current, InfiniteDelayType):
            pending.append((current.interrupts, guarded))
        elif isinstance(current, MuType) and current.variable != name:
            pending.append((current.body, guarded))
        elif isinstance(current, ParallelType):
            pending.extend((component, guarded) for component in current.components)
    return True


def _duration_key(duration: Fraction) -> tuple[int, int]:
    r"""Return the reduced numerator and denominator of a finite delay."""
    return duration.numerator, duration.denominator


def _type_key(value: BehavioralType, bound: Mapping[str, int] | None = None) -> Any:
    r"""Compute alpha-invariant structural keys using an explicit stack."""

    initial_bound = {} if bound is None else dict(bound)
    results: list[Any] = []
    # Save the result-stack boundary to recover child keys in their original order.
    pending: list[tuple[Any, ...]] = [("visit", value, initial_bound)]
    while pending:
        task = pending.pop()
        if task[0] == "finish":
            _, tag, payload, start = task
            children = tuple(results[start:])
            del results[start:]
            if tag in {"in", "out"}:
                results.append((tag, payload, children[0]))
            elif tag in {"external", "internal", "parallel"}:
                results.append((tag, children))
            elif tag == "finite-delay":
                results.append((tag, payload, children[0], children[1]))
            elif tag in {"infinite-delay", "mu"}:
                results.append((tag, children[0]))
            else:
                raise RuntimeError(f"Unsupported Type key task: {tag}")
            continue

        _, current, current_bound = task
        if isinstance(current, NoInterruptType):
            results.append(("no-interrupt",))
        elif isinstance(current, EmptyType):
            results.append(("empty",))
        elif isinstance(current, BottomType):
            results.append(("bottom",))
        elif isinstance(current, TypeVar):
            if current.name in current_bound:
                results.append(("bound", current_bound[current.name]))
            else:
                results.append(("free", current.name))
        elif isinstance(current, (InputType, OutputType)):
            tag = "in" if isinstance(current, InputType) else "out"
            start = len(results)
            pending.append(("finish", tag, current.channel, start))
            pending.append(("visit", current.continuation, current_bound))
        elif isinstance(current, (ExternalChoiceType, InternalChoiceType)):
            tag = (
                "external"
                if isinstance(current, ExternalChoiceType)
                else "internal"
            )
            start = len(results)
            pending.append(("finish", tag, None, start))
            for branch in reversed(current.branches):
                pending.append(("visit", branch, current_bound))
        elif isinstance(current, FiniteDelayType):
            start = len(results)
            pending.append(
                ("finish", "finite-delay", _duration_key(current.duration), start)
            )
            pending.append(("visit", current.continuation, current_bound))
            pending.append(("visit", current.interrupts, current_bound))
        elif isinstance(current, InfiniteDelayType):
            start = len(results)
            pending.append(("finish", "infinite-delay", None, start))
            pending.append(("visit", current.interrupts, current_bound))
        elif isinstance(current, MuType):
            nested_bound = dict(current_bound)
            nested_bound[current.variable] = len(current_bound)
            start = len(results)
            pending.append(("finish", "mu", None, start))
            pending.append(("visit", current.body, nested_bound))
        elif isinstance(current, ParallelType):
            start = len(results)
            pending.append(("finish", "parallel", None, start))
            for component in reversed(current.components):
                pending.append(("visit", component, current_bound))
        else:
            raise TypeError(
                f"Unsupported behavioral type: {type(current).__name__}"
            )
    if len(results) != 1:
        raise RuntimeError("Type key construction produced an invalid result")
    return results[0]


def types_equivalent(left: BehavioralType, right: BehavioralType) -> bool:
    r"""Compare structural types modulo mu-bound variable renaming."""
    return _type_key(left) == _type_key(right)
