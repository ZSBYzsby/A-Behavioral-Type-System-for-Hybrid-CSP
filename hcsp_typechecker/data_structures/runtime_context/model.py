r"""Domain models for typing environments and runtime configurations."""

from __future__ import annotations

from dataclasses import dataclass
from enum import Enum
from types import MappingProxyType
from typing import Any, Mapping, Sequence

from ...identifiers import is_hcsp_identifier


class BasicType(str, Enum):
    r"""Basic value types for HCSP expressions."""
    BOOL = "Bool"
    NAT = "Nat"
    INT = "Int"
    RATIONAL = "Rational"
    REAL = "Real"


    def __str__(self) -> str:
        r"""Display the paper's basic type name."""
        return self.value


def normalize_type(value: Any, *, subject: str = "Value type") -> BasicType:
    r"""Normalize convenient type inputs to the shared basic type model."""
    if isinstance(value, BasicType):
        return value
    if value is bool:
        return BasicType.BOOL
    if value is int:
        return BasicType.INT
    if value is float:
        return BasicType.REAL
    if isinstance(value, str):
        aliases = {
            "b": BasicType.BOOL,
            "bool": BasicType.BOOL,
            "boolean": BasicType.BOOL,
            "n": BasicType.NAT,
            "nat": BasicType.NAT,
            "natural": BasicType.NAT,
            "z": BasicType.INT,
            "int": BasicType.INT,
            "integer": BasicType.INT,
            "q": BasicType.RATIONAL,
            "rat": BasicType.RATIONAL,
            "rational": BasicType.RATIONAL,
            "r": BasicType.REAL,
            "real": BasicType.REAL,
        }
        key = value.strip().lower()
        if key in aliases:
            return aliases[key]
    raise TypeError(f"{subject} must be a BasicType, got {value!r}")
@dataclass(frozen=True)
class ContinuousType:
    r"""A named declaration of an allowed ODE evolution vector in Gamma."""

    variables: tuple[str, ...]

    def __init__(
        self,
        variables: Sequence[str],
    ):
        r"""Declare an ODE vector interpreted by its member set."""

        if isinstance(variables, (str, bytes)):
            raise TypeError(
                "Continuous vector variables must be a sequence of names, "
                "not one string"
            )
        normalized_variables = tuple(variables)
        if not normalized_variables:
            raise ValueError("Continuous vector variables must not be empty")
        if any(
            not is_hcsp_identifier(name)
            for name in normalized_variables
        ):
            raise ValueError("Continuous vector variables must be valid identifiers")
        if len(set(normalized_variables)) != len(normalized_variables):
            raise ValueError("Continuous vector variables must be distinct")
        object.__setattr__(self, "variables", tuple(sorted(normalized_variables)))

    def __str__(self) -> str:
        r"""Display the evolution vector as R>=0 ~> R^n."""

        dimension = len(self.variables)
        rendered = "R>=0 ~> Real" if dimension == 1 else f"R>=0 ~> R^{dimension}"
        return rendered + " on (" + ", ".join(self.variables) + ")"


# Gamma contains scalar types and vector declarations; recursion bindings live in the rule
# environment.
GammaType = BasicType | ContinuousType


def normalize_gamma_type(value: Any, *, subject: str = "Gamma entry") -> GammaType:
    r"""Normalize a Gamma scalar type or independent ODE vector declaration."""

    if isinstance(value, ContinuousType):
        return value
    try:
        return normalize_type(value, subject=subject)
    except TypeError as exc:
        raise TypeError(
            f"{subject} must be a BasicType or ContinuousType, got {value!r}"
        ) from exc


def gamma_value_type(value: Any, *, subject: str = "Gamma entry") -> BasicType:
    r"""Return a scalar Gamma type, rejecting ODE vector labels as values."""

    normalized = normalize_gamma_type(value, subject=subject)
    if isinstance(normalized, ContinuousType):
        raise TypeError(
            f"{subject} is an ODE vector declaration, not a scalar value type"
        )
    return normalized


def is_subtype(actual: BasicType, expected: BasicType) -> bool:
    r"""Check whether an actual value type safely fits an expected type."""
    actual = normalize_type(actual)
    expected = normalize_type(expected)
    if actual == expected:
        return True
    # Wider numeric types have higher ranks; assignment only promotes to wider types.
    numeric_rank = {
        BasicType.NAT: 0,
        BasicType.INT: 1,
        BasicType.RATIONAL: 2,
        BasicType.REAL: 3,
    }
    return (
        actual in numeric_rank
        and expected in numeric_rank
        and numeric_rank[actual] <= numeric_rank[expected]
    )


@dataclass(frozen=True)
class ChannelType:
    r"""Scalar communication slots with a joint refinement predicate."""

    value_types: tuple[BasicType, ...]
    refinement: Any = True
    binders: tuple[str, ...] = ()


    def __init__(
        self,
        value_types: Any,
        refinement: Any = True,
        binders: Sequence[str] | str | None = None,
    ):
        r"""Normalize slot types, joint refinement, and corresponding binders."""

        raw_types = (
            tuple(value_types)
            if isinstance(value_types, (tuple, list))
            else (value_types,)
        )
        if not raw_types:
            raise ValueError("Channel type needs at least one payload slot")
        normalized_types = tuple(
            normalize_type(value, subject="Channel payload slot type")
            for value in raw_types
        )

        if binders is None:
            normalized_binders = (
                ("eta",)
                if len(normalized_types) == 1
                else tuple(
                    f"eta{index}"
                    for index in range(1, len(normalized_types) + 1)
                )
            )
        elif isinstance(binders, str):
            normalized_binders = (binders,)
        else:
            normalized_binders = tuple(binders)
        if len(normalized_binders) != len(normalized_types):
            raise ValueError(
                "Channel refinement binder count must match payload arity"
            )
        if any(
            not is_hcsp_identifier(name)
            for name in normalized_binders
        ):
            raise ValueError("Channel refinement binders must be identifiers")
        if len(set(normalized_binders)) != len(normalized_binders):
            raise ValueError("Channel refinement binders must be distinct")

        object.__setattr__(self, "value_types", normalized_types)
        object.__setattr__(self, "refinement", refinement)
        object.__setattr__(self, "binders", normalized_binders)

    @property
    def arity(self) -> int:
        r"""Return the number of scalar slots in one synchronization."""

        return len(self.value_types)


    def __str__(self) -> str:
        r"""Display the channel signature and joint refinement."""

        slots = ", ".join(
            f"{binder}:{value_type}"
            for binder, value_type in zip(self.binders, self.value_types)
        )
        refinement = "true" if self.refinement is True else str(self.refinement)
        return f"{{{slots} | {refinement}}}"


def normalize_channel_type(value: Any) -> ChannelType:
    r"""Normalize a shorthand Theta entry into ChannelType."""
    if isinstance(value, ChannelType):
        return value
    return ChannelType(value)


@dataclass(frozen=True)
class ParameterEnvironment:
    r"""Shared read-only parameter declarations and their admissibility constraint."""

    declarations: Mapping[str, Any]
    constraint: Any = True

    def __init__(
        self,
        declarations: Mapping[str, Any] | None = None,
        constraint: Any = True,
    ):
        r"""Copy declarations and expose a read-only parameter mapping."""

        object.__setattr__(
            self,
            "declarations",
            MappingProxyType(
                {} if declarations is None else dict(declarations)
            ),
        )
        object.__setattr__(self, "constraint", constraint)


@dataclass(frozen=True)
class Configuration:
    r"""One <state, process> configuration in a parallel judgment."""

    state: Mapping[str, Any]
    process: Any
    path_condition: Any | None = None
    name: str | None = None


    def __init__(
        self,
        state: Mapping[str, Any] | None,
        process: Any,
        path_condition: Any | None = None,
        name: str | None = None,
    ):
        r"""Copy mutable mappings to isolate active construction from caller changes."""
        object.__setattr__(self, "state", {} if state is None else dict(state))
        object.__setattr__(self, "process", process)
        object.__setattr__(self, "path_condition", path_condition)
        object.__setattr__(self, "name", name)

__all__ = [
    "BasicType",
    "ChannelType",
    "Configuration",
    "ContinuousType",
    "GammaType",
    "ParameterEnvironment",
    "gamma_value_type",
    "is_subtype",
    "normalize_channel_type",
    "normalize_gamma_type",
    "normalize_type",
]
