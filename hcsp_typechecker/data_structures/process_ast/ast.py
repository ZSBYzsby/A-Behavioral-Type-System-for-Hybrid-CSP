r"""HCSP ASTs with well-formedness checks and Sections 4.2/4.3 annotations."""

from __future__ import annotations

from abc import ABC, abstractmethod
from dataclasses import InitVar, dataclass, field
from decimal import Decimal
from fractions import Fraction
from math import inf, isinf, isnan
from typing import Iterable

from ...identifiers import is_hcsp_identifier
from .expressions import (
    BinaryExpr,
    Expr,
    ExprLike,
    Literal,
    UnaryExpr,
    Variable,
    ensure_expr,
    ensure_variable,
)


class HCSP(ABC):
    r"""Base category for system syntax S."""


    @abstractmethod
    def get_vars(self) -> set[str]:
        r"""Return user value variables read, written, or introduced by input."""


    def get_input_bound_vars(self) -> set[str]:
        r"""Return input targets that T-In may introduce into Gamma."""
        return set()


class Process(HCSP, ABC):
    r"""Base category for sequential process syntax P."""
class EventReaction(ABC):
    r"""Base category for event reaction syntax E."""


    @abstractmethod
    def get_vars(self) -> set[str]:
        r"""Return value variables used by the event reaction and its continuation."""


    def get_input_bound_vars(self) -> set[str]:
        r"""Return targets written by event input branches."""
        return set()


@dataclass(frozen=True)
class Channel:
    r"""An HCSP channel identifier."""

    name: str


    def __post_init__(self) -> None:
        r"""Require the common ASCII identifier syntax for channel names."""
        if not is_hcsp_identifier(self.name):
            raise ValueError(f"Invalid channel name: {self.name!r}")


    def __str__(self) -> str:
        r"""Return the channel name used in Theta."""
        return self.name


def ensure_channel(value: str | Channel) -> Channel:
    r"""Convert a channel name to a validated Channel."""
    if isinstance(value, Channel):
        return value
    if isinstance(value, str):
        return Channel(value)
    raise TypeError(f"Expected a Channel or string name, got {value!r}")


@dataclass(frozen=True)
class Var(Process):
    r"""A process recursion variable X."""

    name: str


    def __post_init__(self) -> None:
        r"""Require a valid process variable identifier."""
        if not is_hcsp_identifier(self.name):
            raise ValueError(f"Invalid process variable: {self.name!r}")


    def get_vars(self) -> set[str]:
        r"""Process variables do not contribute to the value-variable set."""
        return set()


@dataclass(frozen=True)
class Skip(Process):
    r"""The empty process skip."""


    def get_vars(self) -> set[str]:
        r"""Skip uses no value variables."""
        return set()


@dataclass(frozen=True)
class Assign(Process):
    r"""Scalar assignment x := e."""

    target: Variable
    expression: Expr


    def __init__(self, target: str | Variable, expression: ExprLike):
        r"""Normalize the scalar target and right-hand expression."""
        object.__setattr__(self, "target", ensure_variable(target))
        object.__setattr__(self, "expression", ensure_expr(expression))


    def get_vars(self) -> set[str]:
        r"""Include the assignment target and free variables of its expression."""
        return {self.target.name} | self.expression.get_vars()


@dataclass(frozen=True)
class Assert(Process):
    r"""An assertion process assert(B)."""

    condition: Expr


    def __init__(self, condition: ExprLike):
        r"""Normalize the assertion into a strict expression AST."""
        object.__setattr__(self, "condition", ensure_expr(condition))


    def get_vars(self) -> set[str]:
        r"""Return variables in the assertion condition."""
        return self.condition.get_vars()


def _normalize_input_targets(
    targets: str | Variable | Iterable[str | Variable],
) -> tuple[Variable, ...]:
    r"""Normalize all scalar targets of one input synchronization."""

    raw_targets = (
        tuple(targets)
        if isinstance(targets, (tuple, list))
        else (targets,)
    )
    if not raw_targets:
        raise ValueError("Input communication needs at least one target")
    normalized = tuple(ensure_variable(target) for target in raw_targets)
    names = tuple(target.name for target in normalized)
    if len(set(names)) != len(names):
        raise ValueError("Input communication targets must be distinct")
    return normalized


def _normalize_output_payloads(
    payloads: ExprLike | Iterable[ExprLike],
) -> tuple[Expr, ...]:
    r"""Normalize all scalar expressions of one output synchronization."""

    raw_payloads = (
        tuple(payloads)
        if isinstance(payloads, (tuple, list))
        else (payloads,)
    )
    if not raw_payloads:
        raise ValueError("Output communication needs at least one payload")
    return tuple(ensure_expr(payload) for payload in raw_payloads)


@dataclass(frozen=True)
class InputChannel(Process):
    r"""One input action receiving multiple independent scalar values."""

    channel: Channel
    targets: tuple[Variable, ...]


    def __init__(
        self,
        channel: str | Channel,
        targets: str | Variable | Iterable[str | Variable],
    ):
        r"""Normalize a channel and nonempty scalar input targets."""
        object.__setattr__(self, "channel", ensure_channel(channel))
        object.__setattr__(self, "targets", _normalize_input_targets(targets))


    def get_vars(self) -> set[str]:
        r"""Include every input target in the process value-variable set."""
        return {target.name for target in self.targets}


    def get_input_bound_vars(self) -> set[str]:
        r"""Return targets bound by this input action."""
        return self.get_vars()


@dataclass(frozen=True)
class OutputChannel(Process):
    r"""One output action sending multiple independent scalar values."""

    channel: Channel
    payloads: tuple[Expr, ...]


    def __init__(
        self,
        channel: str | Channel,
        payloads: ExprLike | Iterable[ExprLike],
    ):
        r"""Normalize a channel and nonempty scalar payload expressions."""
        object.__setattr__(self, "channel", ensure_channel(channel))
        object.__setattr__(self, "payloads", _normalize_output_payloads(payloads))


    def get_vars(self) -> set[str]:
        r"""Union free variables of all output payloads."""
        return set().union(*(payload.get_vars() for payload in self.payloads))


@dataclass(frozen=True)
class If(Process):
    r"""A conditional with two branches and a shared sequential continuation."""

    condition: Expr
    then_branch: Process
    else_branch: Process
    continuation: Process


    def __init__(
        self,
        condition: ExprLike,
        then_branch: Process,
        else_branch: Process,
        *,
        continuation: Process | None = None,
    ):
        r"""Validate the condition, both branches, and shared continuation."""
        if not isinstance(then_branch, Process) or not isinstance(else_branch, Process):
            raise TypeError("If branches must be Process nodes")
        common_tail = Skip() if continuation is None else continuation
        if not isinstance(common_tail, Process):
            raise TypeError("If continuation must be a Process node")
        object.__setattr__(self, "condition", ensure_expr(condition))
        object.__setattr__(self, "then_branch", then_branch)
        object.__setattr__(self, "else_branch", else_branch)
        object.__setattr__(self, "continuation", common_tail)
        _validate_assumption21(self)


    def get_vars(self) -> set[str]:
        r"""Union variables of the condition, branches, and continuation."""
        return set(_assumption21_info(self).value_variables)


    def get_input_bound_vars(self) -> set[str]:
        r"""Union input targets introduced by both branches and the continuation."""
        return set(_assumption21_info(self).bound_value_variables)


@dataclass(frozen=True)
class EmptyEvent(EventReaction):
    r"""An empty event reaction."""


    def get_vars(self) -> set[str]:
        r"""An empty event uses no value variables."""
        return set()


@dataclass(frozen=True)
class EventChoice(EventReaction):
    r"""A nonempty choice of communication reactions."""

    branches: tuple[tuple[InputChannel | OutputChannel, Process], ...]


    def __init__(
        self,
        *branches: tuple[InputChannel | OutputChannel, Process],
    ):
        r"""Validate nonempty communication branches and their process continuations."""
        if not branches:
            raise ValueError("EventChoice requires at least one event branch")
        normalized: list[tuple[InputChannel | OutputChannel, Process]] = []
        for index, branch in enumerate(branches):
            if not isinstance(branch, tuple) or len(branch) != 2:
                raise TypeError(
                    "EventChoice branches must be "
                    "(communication, continuation) tuples"
                )
            communication, continuation = branch
            if not isinstance(communication, (InputChannel, OutputChannel)):
                raise TypeError(
                    f"EventChoice branch {index} prefix must be an input or output action"
                )
            if not isinstance(continuation, Process):
                raise TypeError(
                    f"EventChoice branch {index} continuation must be a Process"
                )
            normalized.append((communication, continuation))
        object.__setattr__(self, "branches", tuple(normalized))
        _validate_assumption21(self)


    def get_vars(self) -> set[str]:
        r"""Union value variables used by all event branches."""
        return set(_assumption21_info(self).value_variables)


    def get_input_bound_vars(self) -> set[str]:
        r"""Union input targets introduced by all event branches."""
        return set(_assumption21_info(self).bound_value_variables)


    @classmethod
    def of(
        cls,
        *branches: tuple[InputChannel | OutputChannel, Process],
    ) -> EventReaction:
        r"""Canonicalize event branches into EmptyEvent or EventChoice."""
        return EmptyEvent() if not branches else cls(*branches)


@dataclass(frozen=True)
class Sequence(Process):
    r"""Binary sequential composition P; P'."""

    first: Process
    second: Process


    def __init__(self, first: Process, second: Process):
        r"""Require process operands and reject externally attached control-node continuations."""
        if not isinstance(first, Process):
            raise TypeError("Sequence first operand must be a Process")
        if not isinstance(second, Process):
            raise TypeError("Sequence second operand must be a Process")
        trailing = first
        while isinstance(trailing, Sequence):
            trailing = trailing.second
        if isinstance(trailing, (If, InternalChoice, ODE)):
            raise ValueError(
                f"{type(trailing).__name__} owns its common continuation; "
                "store the later process in that node's continuation field "
                "instead of placing the control node before an outer Sequence"
            )
        object.__setattr__(self, "first", first)
        object.__setattr__(self, "second", second)
        _validate_assumption21(self)


    def get_vars(self) -> set[str]:
        r"""Union variables used by both sequential operands."""
        return set(_assumption21_info(self).value_variables)


    def get_input_bound_vars(self) -> set[str]:
        r"""Union input targets introduced by both sequential operands."""
        return set(_assumption21_info(self).bound_value_variables)


    @classmethod
    def of(cls, *items: Process) -> Process:
        r"""Build a right-associated binary Sequence from multiple processes."""

        if not items:
            return Skip()
        if not all(isinstance(item, Process) for item in items):
            raise TypeError("Sequence.of items must all be Process nodes")
        result: Process = items[-1]
        for item in reversed(items[:-1]):
            if isinstance(item, (If, InternalChoice, ODE, Sequence)):
                result = _append_sequence_continuation(item, result)
            else:
                result = _unchecked_sequence(item, result)
        # Validate the completed tree once; validating each growing Sequence repeats scans with
        # quadratic cost.
        _validate_assumption21(result)
        return result


def _unchecked_sequence(first: Process, second: Process) -> Sequence:
    r"""Build an internal Sequence whose operand categories are already validated."""

    value = object.__new__(Sequence)
    object.__setattr__(value, "first", first)
    object.__setattr__(value, "second", second)
    return value
@dataclass(frozen=True)
class InternalChoice(Process):
    r"""An n-ary internal choice with a shared continuation."""

    branches: tuple[Process, ...]
    continuation: Process


    def __init__(
        self,
        *branches: Process,
        continuation: Process | None = None,
    ) -> None:
        r"""Require at least two process branches and normalize the shared continuation."""
        if len(branches) < 2:
            raise ValueError("InternalChoice requires at least two Process branches")
        if not all(isinstance(branch, Process) for branch in branches):
            raise TypeError("InternalChoice branches must be Process nodes")
        common_tail = Skip() if continuation is None else continuation
        if not isinstance(common_tail, Process):
            raise TypeError("InternalChoice continuation must be a Process node")
        object.__setattr__(self, "branches", tuple(branches))
        object.__setattr__(self, "continuation", common_tail)
        _validate_assumption21(self)


    def get_vars(self) -> set[str]:
        r"""Union variables of all choice branches and their continuation."""
        return set(_assumption21_info(self).value_variables)


    def get_input_bound_vars(self) -> set[str]:
        r"""Union input targets of all choice branches and their continuation."""
        return set(_assumption21_info(self).bound_value_variables)


    @classmethod
    def of(
        cls,
        *branches: Process,
        continuation: Process | None = None,
    ) -> "InternalChoice":
        r"""Build the canonical n-ary internal-choice representation."""
        return cls(*branches, continuation=continuation)


def _append_sequence_continuation(
    prefix: Process,
    continuation: Process,
) -> Process:
    r"""Attach continuations inside control nodes to preserve canonical Sequence structure."""

    if isinstance(prefix, If):
        combined = (
            continuation
            if isinstance(prefix.continuation, Skip)
            else _append_sequence_continuation(prefix.continuation, continuation)
        )
        return If(
            prefix.condition,
            prefix.then_branch,
            prefix.else_branch,
            continuation=combined,
        )
    if isinstance(prefix, InternalChoice):
        combined = (
            continuation
            if isinstance(prefix.continuation, Skip)
            else _append_sequence_continuation(
                prefix.continuation,
                continuation,
            )
        )
        return InternalChoice(*prefix.branches, continuation=combined)
    if isinstance(prefix, ODE):
        combined = (
            continuation
            if isinstance(prefix.continuation, Skip)
            else _append_sequence_continuation(prefix.continuation, continuation)
        )
        return ODE(
            prefix.eqs,
            prefix.constraint,
            prefix.interrupts,
            annotation=prefix.annotation,
            continuation=combined,
        )
    if isinstance(prefix, Sequence):
        return Sequence(
            prefix.first,
            _append_sequence_continuation(prefix.second, continuation),
        )
    return Sequence(prefix, continuation)


# ODE-local t is excluded from user-variable analysis and receives a fresh internal dL symbol.
ODE_LOCAL_CLOCK_NAME = "t"


def _normalize_equations(
    equations: Iterable[tuple[str, ExprLike]],
) -> tuple[tuple[str, Expr], ...]:
    r"""Validate and normalize the ODE equation vector."""

    try:
        iterator = iter(equations)
    except TypeError as exc:
        raise TypeError(
            "ODE equations must be an iterable of (variable, derivative) tuples"
        ) from exc

    normalized: list[tuple[str, Expr]] = []
    for index, equation in enumerate(iterator):
        if not isinstance(equation, tuple) or len(equation) != 2:
            raise TypeError(
                f"ODE equation {index} must be a "
                "(variable, derivative) tuple"
            )
        variable, derivative = equation
        if not is_hcsp_identifier(variable):
            raise ValueError(f"Invalid ODE variable: {variable!r}")
        if variable == ODE_LOCAL_CLOCK_NAME:
            raise ValueError(
                "ODE variable 't' is reserved for the automatic local clock; "
                "its equation t'=1 is added automatically"
            )
        normalized.append((variable, ensure_expr(derivative)))
    return tuple(normalized)


def _evaluate_rational_constant(expression: Expr) -> Fraction:
    r"""Evaluate a variable-free rational constant exactly as Fraction."""

    if isinstance(expression, Literal):
        value = expression.value
        if isinstance(value, bool):
            raise ValueError("ODE delay must be a rational number, not Boolean")
        if isinstance(value, int):
            return Fraction(value)
        if isinstance(value, Fraction):
            return value
        if isinstance(value, Decimal):
            if value.is_nan() or value.is_infinite():
                raise ValueError("ODE finite delay must be a rational number")
            return Fraction(value)
        if isinstance(value, float):
            if isnan(value) or isinf(value):
                raise ValueError("ODE finite delay must be a rational number")
            # Use decimal source text rather than binary floating-point denominators.
            return Fraction(str(value))
        raise ValueError("ODE delay must be a numeric rational constant")

    if isinstance(expression, UnaryExpr) and expression.op in {"+", "-"}:
        operand = _evaluate_rational_constant(expression.operand)
        return operand if expression.op == "+" else -operand

    if isinstance(expression, BinaryExpr):
        left = _evaluate_rational_constant(expression.left)
        right = _evaluate_rational_constant(expression.right)
        try:
            if expression.op == "+":
                return left + right
            if expression.op == "-":
                return left - right
            if expression.op == "*":
                return left * right
            if expression.op == "/":
                return left / right
            if expression.op == "**":
                if right.denominator != 1:
                    raise ValueError(
                        "ODE delay exponent must be an integer"
                    )
                return left ** right.numerator
        except ZeroDivisionError as exc:
            raise ValueError(
                "ODE delay constant expression divides by zero"
            ) from exc

    raise ValueError(
        "ODE delay must be a constant rational expression or positive infinity"
    )


def _normalize_ode_delay(delay: ExprLike | None) -> Literal | float:
    r"""Require a delay annotation and normalize rational or infinite duration."""

    if delay is None:
        raise ValueError(
            "ODE annotation requires an explicit delay: "
            "a non-negative rational number or positive infinity"
        )

    expression = ensure_expr(delay)
    if isinstance(expression, Literal):
        value = expression.value
        if isinstance(value, float) and isinf(value):
            if value > 0:
                return inf
            raise ValueError("ODE delay cannot be negative infinity")
        if isinstance(value, Decimal) and value.is_infinite():
            if value > 0:
                return inf
            raise ValueError("ODE delay cannot be negative infinity")

    rational = _evaluate_rational_constant(expression)
    if rational < 0:
        raise ValueError("ODE delay must be non-negative")

    return Literal(rational)


@dataclass(frozen=True)
class ODEAnnotation:
    r"""Continuous-evolution safety and exact external duration annotations."""

    safety: Expr
    delay: Literal | float


    def __init__(
        self,
        *,
        safety: ExprLike = True,
        delay: ExprLike | None = None,
    ):
        r"""Normalize safety and require an exact rational or infinite delay."""
        object.__setattr__(self, "safety", ensure_expr(safety))
        object.__setattr__(self, "delay", _normalize_ode_delay(delay))


    def get_vars(self) -> set[str]:
        r"""Return safety formula variables; valid delay annotations contain no variables."""
        return set(self.safety.get_vars())


@dataclass(frozen=True, eq=False)
class ODELocalClock:
    r"""An automatically allocated ODE-local clock readable as t."""

    name: str = field(default=ODE_LOCAL_CLOCK_NAME, init=False)

    initial_value: Literal = field(
        default_factory=lambda: Literal(Fraction(0)),
        init=False,
    )
    derivative: Literal = field(
        default_factory=lambda: Literal(Fraction(1)),
        init=False,
    )


@dataclass(frozen=True)
class ODE(Process):
    r"""Annotated continuous evolution with interrupts and a shared continuation."""

    eqs: tuple[tuple[str, Expr], ...]
    constraint: Expr
    interrupts: EventReaction
    annotation: ODEAnnotation
    continuation: Process
    # Fresh local clock identities do not participate in source-level ODE structural equality.
    local_clock: ODELocalClock = field(compare=False, init=False)


    def __init__(
        self,
        eqs: Iterable[tuple[str, ExprLike]],
        constraint: ExprLike,
        interrupts: EventReaction | None = None,
        *,
        annotation: ODEAnnotation | None = None,
        continuation: Process | None = None,
    ):
        r"""Normalize ODE equations, annotations, and the automatic local clock."""

        self._initialize(
            eqs,
            constraint,
            interrupts,
            annotation,
            continuation,
        )


    def _initialize(
        self,
        eqs: Iterable[tuple[str, ExprLike]],
        constraint: ExprLike,
        interrupts: EventReaction | None,
        annotation: ODEAnnotation | None,
        continuation: Process | None,
    ) -> None:
        r"""Initialize an annotated ODE and its hidden clock atomically."""

        if interrupts is not None and not isinstance(interrupts, EventReaction):
            raise TypeError("ODE interrupts must be an EventReaction")
        if annotation is None:
            raise ValueError(
                "Every ODE requires ODEAnnotation with an explicit delay"
            )
        if not isinstance(annotation, ODEAnnotation):
            raise TypeError("ODE annotation must be an ODEAnnotation")
        common_tail = Skip() if continuation is None else continuation
        if not isinstance(common_tail, Process):
            raise TypeError("ODE continuation must be a Process node")
        object.__setattr__(self, "eqs", _normalize_equations(eqs))
        object.__setattr__(self, "constraint", ensure_expr(constraint))
        object.__setattr__(
            self,
            "interrupts",
            EmptyEvent() if interrupts is None else interrupts,
        )
        object.__setattr__(
            self,
            "annotation",
            annotation,
        )
        object.__setattr__(self, "continuation", common_tail)
        object.__setattr__(self, "local_clock", ODELocalClock())
        _validate_assumption21(self)


    def get_vars(self) -> set[str]:
        r"""Collect value variables from equations, formulas, reactions, and continuation."""
        return set(_assumption21_info(self).value_variables)


    def get_input_bound_vars(self) -> set[str]:
        r"""Return input targets introduced by reactions and continuation."""
        return set(_assumption21_info(self).bound_value_variables)


@dataclass(frozen=True)
class RecursionAnnotation:
    r"""The recursion-boundary invariant from Section 4.3."""

    invariant: Expr


    def __init__(self, invariant: ExprLike = True):
        r"""Default an omitted recursion invariant to true."""
        object.__setattr__(self, "invariant", ensure_expr(invariant))


    def get_vars(self) -> set[str]:
        r"""Return value variables in the boundary invariant."""
        return self.invariant.get_vars()


@dataclass(frozen=True)
class Mu(Process):
    r"""A recursive process with a boundary invariant."""

    variable: str
    body: Process
    annotation: RecursionAnnotation


    def __init__(
        self,
        variable: str,
        body: Process,
        *,
        annotation: RecursionAnnotation | None = None,
    ):
        r"""Bind a process variable and its Section 4.3 recursion annotation."""
        if not is_hcsp_identifier(variable):
            raise ValueError(f"Invalid recursive variable: {variable!r}")
        if not isinstance(body, Process):
            raise TypeError("Mu body must be a Process")
        if annotation is not None and not isinstance(annotation, RecursionAnnotation):
            raise TypeError("Mu annotation must be a RecursionAnnotation")
        _validate_assumption22(variable, body)
        object.__setattr__(self, "variable", variable)
        object.__setattr__(self, "body", body)
        object.__setattr__(
            self,
            "annotation",
            RecursionAnnotation() if annotation is None else annotation,
        )
        _validate_assumption21(self)


    def get_vars(self) -> set[str]:
        r"""Union value variables in the recursion body and invariant."""
        return set(_assumption21_info(self).value_variables)


    def get_input_bound_vars(self) -> set[str]:
        r"""Return input targets introduced by the recursion body."""
        return set(_assumption21_info(self).bound_value_variables)


def _validate_assumption22(variable: str, body: Process) -> None:
    r"""Check Assumption 2.2 for all references to the bound recursion variable."""

    results: list[frozenset[bool]] = []
    pending: list[tuple[object, ...]] = [
        ("eval", body, False, "body", False)
    ]
    while pending:
        task = pending.pop()
        tag = task[0]
        if tag == "union":
            count = task[1]
            combined: set[bool] = set()
            if count:
                for item in results[-count:]:
                    combined.update(item)
                del results[-count:]
            results.append(frozenset(combined))
            continue
        if tag == "chain":
            _, continuation, location, shadowed = task
            states = results.pop()
            pending.append(("union", len(states)))
            for state in sorted(states, reverse=True):
                pending.append(
                    ("eval", continuation, state, location, shadowed)
                )
            continue
        if tag == "discard":
            results.pop()
            continue

        _, node, guarded, location, shadowed = task
        if isinstance(node, Var):
            if not shadowed and node.name == variable and not guarded:
                raise ValueError(
                    "Assumption 2.2 violated: recursion "
                    f"{variable!r} is not communication-guarded at {location}; "
                    "every bound occurrence must be preceded by input or output communication"
                )
            results.append(frozenset({guarded}))
            continue
        if isinstance(node, (Skip, Assign, Assert)):
            results.append(frozenset({guarded}))
            continue
        if isinstance(node, (InputChannel, OutputChannel)):
            results.append(frozenset({True}))
            continue
        if isinstance(node, Sequence):
            pending.append(("chain", node.second, f"{location}.second", shadowed))
            pending.append(("eval", node.first, guarded, f"{location}.first", shadowed))
            continue
        if isinstance(node, If):
            pending.append(
                ("chain", node.continuation, f"{location}.continuation", shadowed)
            )
            pending.append(("union", 2))
            pending.append(("eval", node.else_branch, guarded, f"{location}.else", shadowed))
            pending.append(("eval", node.then_branch, guarded, f"{location}.then", shadowed))
            continue
        if isinstance(node, InternalChoice):
            pending.append(
                ("chain", node.continuation, f"{location}.continuation", shadowed)
            )
            pending.append(("union", len(node.branches)))
            for index in reversed(range(len(node.branches))):
                branch = node.branches[index]
                pending.append(
                    (
                        "eval",
                        branch,
                        guarded,
                        f"{location}.branches[{index}]",
                        shadowed,
                    )
                )
            continue
        if isinstance(node, ODE):
            # The ODE's natural successor determines its exit summary; event paths are validated
            # separately.
            if isinstance(node.interrupts, EventChoice):
                for index in reversed(range(len(node.interrupts.branches))):
                    _communication, continuation = node.interrupts.branches[index]
                    branch_location = f"{location}.interrupts.branches[{index}]"
                    pending.append(("discard",))
                    pending.append(
                        ("chain", node.continuation, branch_location + ".common", shadowed)
                    )
                    pending.append(
                        ("eval", continuation, True, branch_location, shadowed)
                    )
            elif not isinstance(node.interrupts, EmptyEvent):
                raise TypeError(
                    "Assumption 2.2 analysis received an unsupported EventReaction: "
                    f"{type(node.interrupts).__name__}"
                )
            pending.append(
                ("eval", node.continuation, guarded, f"{location}.continuation", shadowed)
            )
            continue
        if isinstance(node, Mu):
            pending.append(
                (
                    "eval",
                    node.body,
                    guarded,
                    f"{location}.mu[{node.variable}].body",
                    shadowed or node.variable == variable,
                )
            )
            continue
        raise TypeError(
            "Assumption 2.2 analysis received an unsupported Process node: "
            f"{type(node).__name__}"
        )
    if len(results) != 1:
        raise RuntimeError("Assumption 2.2 analysis produced an invalid result")


@dataclass(frozen=True)
class Parallel(HCSP):
    r"""Binary system composition S || S'."""

    left: HCSP
    right: HCSP
    _shared_parameters: InitVar[Iterable[str] | None] = field(
        default=None,
        kw_only=True,
    )


    def __post_init__(self, _shared_parameters: Iterable[str] | None) -> None:
        r"""Validate system operands and Assumption 2.1 parallel resource separation."""
        if not isinstance(self.left, HCSP) or not isinstance(self.right, HCSP):
            raise TypeError("Parallel operands must be HCSP systems")
        if isinstance(_shared_parameters, (str, bytes)):
            raise TypeError(
                "Parallel shared_parameters must be an iterable of names, "
                "not a bare string"
            )
        parameter_names = frozenset(_shared_parameters or ())
        invalid_names = {
            repr(name)
            for name in parameter_names
            if not is_hcsp_identifier(name)
        }
        if invalid_names:
            raise ValueError(
                "Invalid Parallel shared parameter names: "
                + ", ".join(sorted(invalid_names))
            )
        _validate_assumption21(
            self,
            shared_parameters=parameter_names,
        )


    def get_vars(self) -> set[str]:
        r"""Union value variables used by both parallel systems."""
        return set(_assumption21_info(self).value_variables)


    def get_input_bound_vars(self) -> set[str]:
        r"""Union input targets introduced by both parallel systems."""
        return set(_assumption21_info(self).bound_value_variables)


    @classmethod
    def of(
        cls,
        *systems: HCSP,
        shared_parameters: Iterable[str] | None = None,
    ) -> HCSP:
        r"""Build a right-associated binary Parallel from multiple systems."""

        if len(systems) < 2:
            raise ValueError("Parallel.of needs at least two systems")
        if not all(isinstance(system, HCSP) for system in systems):
            raise TypeError("Parallel.of items must all be HCSP systems")
        if isinstance(shared_parameters, (str, bytes)):
            raise TypeError(
                "Parallel.of shared_parameters must be an iterable of names, "
                "not a bare string"
            )
        parameter_names = frozenset(shared_parameters or ())
        result: HCSP = systems[-1]
        for system in reversed(systems[:-1]):
            result = cls(
                system,
                result,
                _shared_parameters=parameter_names,
            )
        return result


@dataclass(frozen=True)
class _Assumption21Info:
    r"""Static sets summarizing Assumption 2.1 for an HCSP subtree."""

    free_value_variables: frozenset[str] = frozenset()
    bound_value_variables: frozenset[str] = frozenset()
    free_process_variables: frozenset[str] = frozenset()
    bound_process_variables: frozenset[str] = frozenset()
    input_channels: frozenset[str] = frozenset()
    output_channels: frozenset[str] = frozenset()


    @property
    def value_variables(self) -> frozenset[str]:
        r"""Union free and bound value variables."""

        return self.free_value_variables | self.bound_value_variables


    @property
    def process_variables(self) -> frozenset[str]:
        r"""Union free and bound process variables."""

        return self.free_process_variables | self.bound_process_variables


def _merge_assumption21_info(
    *items: _Assumption21Info,
) -> _Assumption21Info:
    r"""Union the fields of independent Assumption 2.1 summaries."""

    return _Assumption21Info(
        free_value_variables=frozenset().union(
            *(item.free_value_variables for item in items)
        ),
        bound_value_variables=frozenset().union(
            *(item.bound_value_variables for item in items)
        ),
        free_process_variables=frozenset().union(
            *(item.free_process_variables for item in items)
        ),
        bound_process_variables=frozenset().union(
            *(item.bound_process_variables for item in items)
        ),
        input_channels=frozenset().union(
            *(item.input_channels for item in items)
        ),
        output_channels=frozenset().union(
            *(item.output_channels for item in items)
        ),
    )


def _sequence_assumption21_info(
    first: _Assumption21Info,
    second: _Assumption21Info,
) -> _Assumption21Info:
    r"""Account for input binders capturing free variables in sequential continuations."""

    return _Assumption21Info(
        free_value_variables=(
            first.free_value_variables
            | (second.free_value_variables - first.bound_value_variables)
        ),
        bound_value_variables=(
            first.bound_value_variables | second.bound_value_variables
        ),
        free_process_variables=(
            first.free_process_variables | second.free_process_variables
        ),
        bound_process_variables=(
            first.bound_process_variables | second.bound_process_variables
        ),
        input_channels=first.input_channels | second.input_channels,
        output_channels=first.output_channels | second.output_channels,
    )


def _assumption21_children(
    node: HCSP | EventReaction,
) -> tuple[HCSP | EventReaction, ...]:
    r"""Return direct children for Assumption 2.1 postorder evaluation."""

    if isinstance(node, If):
        return (node.then_branch, node.else_branch, node.continuation)
    if isinstance(node, EventChoice):
        return tuple(
            child
            for communication, continuation in node.branches
            for child in (communication, continuation)
        )
    if isinstance(node, Sequence):
        return (node.first, node.second)
    if isinstance(node, InternalChoice):
        return (*node.branches, node.continuation)
    if isinstance(node, ODE):
        return (node.interrupts, node.continuation)
    if isinstance(node, Mu):
        return (node.body,)
    if isinstance(node, Parallel):
        return (node.left, node.right)
    return ()


def _assumption21_info(
    node: HCSP | EventReaction,
) -> _Assumption21Info:
    r"""Compute free/bound variables and input/output channels iteratively."""

    pending: list[tuple[HCSP | EventReaction, bool]] = [(node, False)]
    results: dict[int, _Assumption21Info] = {}
    while pending:
        current, exiting = pending.pop()
        key = id(current)
        if key in results:
            continue
        children = _assumption21_children(current)
        if not exiting and children:
            pending.append((current, True))
            pending.extend((child, False) for child in reversed(children))
            continue

        def info(child: HCSP | EventReaction) -> _Assumption21Info:
            r"""Read a child summary completed during postorder traversal."""

            return results[id(child)]

        if isinstance(current, Var):
            value = _Assumption21Info(
                free_process_variables=frozenset({current.name})
            )
        elif isinstance(current, Skip):
            value = _Assumption21Info()
        elif isinstance(current, Assign):
            value = _Assumption21Info(
                free_value_variables=frozenset(
                    {current.target.name} | current.expression.get_vars()
                )
            )
        elif isinstance(current, Assert):
            value = _Assumption21Info(
                free_value_variables=frozenset(current.condition.get_vars())
            )
        elif isinstance(current, InputChannel):
            value = _Assumption21Info(
                bound_value_variables=frozenset(
                    target.name for target in current.targets
                ),
                input_channels=frozenset({current.channel.name}),
            )
        elif isinstance(current, OutputChannel):
            variables: set[str] = set()
            for payload in current.payloads:
                variables.update(payload.get_vars())
            value = _Assumption21Info(
                free_value_variables=frozenset(variables),
                output_channels=frozenset({current.channel.name}),
            )
        elif isinstance(current, If):
            condition = _Assumption21Info(
                free_value_variables=frozenset(current.condition.get_vars())
            )
            prefix = _merge_assumption21_info(
                condition,
                info(current.then_branch),
                info(current.else_branch),
            )
            value = _sequence_assumption21_info(
                prefix, info(current.continuation)
            )
        elif isinstance(current, EmptyEvent):
            value = _Assumption21Info()
        elif isinstance(current, EventChoice):
            value = _merge_assumption21_info(
                *(
                    _sequence_assumption21_info(
                        info(communication), info(continuation)
                    )
                    for communication, continuation in current.branches
                )
            )
        elif isinstance(current, Sequence):
            value = _sequence_assumption21_info(
                info(current.first), info(current.second)
            )
        elif isinstance(current, InternalChoice):
            prefix = _merge_assumption21_info(
                *(info(branch) for branch in current.branches)
            )
            value = _sequence_assumption21_info(
                prefix, info(current.continuation)
            )
        elif isinstance(current, ODE):
            variables = set(current.constraint.get_vars())
            variables.update(current.annotation.safety.get_vars())
            for variable, derivative in current.eqs:
                variables.add(variable)
                variables.update(derivative.get_vars())
            variables.discard(current.local_clock.name)
            prefix = _merge_assumption21_info(
                _Assumption21Info(
                    free_value_variables=frozenset(variables)
                ),
                info(current.interrupts),
            )
            value = _sequence_assumption21_info(
                prefix, info(current.continuation)
            )
        elif isinstance(current, Mu):
            body = info(current.body)
            value = _Assumption21Info(
                free_value_variables=(
                    body.free_value_variables
                    | frozenset(current.annotation.invariant.get_vars())
                ),
                bound_value_variables=body.bound_value_variables,
                free_process_variables=(
                    body.free_process_variables - {current.variable}
                ),
                bound_process_variables=(
                    body.bound_process_variables | {current.variable}
                ),
                input_channels=body.input_channels,
                output_channels=body.output_channels,
            )
        elif isinstance(current, Parallel):
            value = _merge_assumption21_info(
                info(current.left), info(current.right)
            )
        else:
            raise TypeError(
                "Assumption 2.1 analysis received an unsupported AST node: "
                f"{type(current).__name__}"
            )
        results[key] = value
    return results[id(node)]


def _validate_assumption21(
    node: HCSP | EventReaction,
    *,
    shared_parameters: frozenset[str] = frozenset(),
) -> None:
    r"""Check free/bound separation and disjoint resources across parallel components."""

    info = _assumption21_info(node)
    shared_value_roles = (
        info.free_value_variables & info.bound_value_variables
    )
    shared_process_roles = (
        info.free_process_variables & info.bound_process_variables
    )
    if shared_value_roles or shared_process_roles:
        labels = list(sorted(shared_value_roles))
        labels.extend(
            f"{name} (process variable)"
            for name in sorted(shared_process_roles)
        )
        raise ValueError(
            "Assumption 2.1 violated: free and bound variables overlap: "
            + ", ".join(labels)
        )

    if not isinstance(node, Parallel):
        return

    left = _assumption21_info(node.left)
    right = _assumption21_info(node.right)
    shared_values = (
        left.value_variables & right.value_variables
    ) - shared_parameters
    shared_processes = (
        left.process_variables & right.process_variables
    )
    if shared_values or shared_processes:
        labels = list(sorted(shared_values))
        labels.extend(
            f"{name} (process variable)"
            for name in sorted(shared_processes)
        )
        raise ValueError(
            "Assumption 2.1 violated: parallel components share "
            f"variables: {', '.join(labels)}"
        )

    shared_inputs = left.input_channels & right.input_channels
    if shared_inputs:
        raise ValueError(
            "Assumption 2.1 violated: parallel components share "
            "input channels: "
            + ", ".join(sorted(shared_inputs))
        )

    shared_outputs = left.output_channels & right.output_channels
    if shared_outputs:
        raise ValueError(
            "Assumption 2.1 violated: parallel components share "
            "output channels: "
            + ", ".join(sorted(shared_outputs))
        )
