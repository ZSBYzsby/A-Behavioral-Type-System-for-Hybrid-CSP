r"""Immutable normalized Type ASTs for the Table 3 state space."""

from __future__ import annotations

from abc import ABC
from dataclasses import dataclass
from fractions import Fraction
from typing import Any, Iterable, TypeAlias

from ...identifiers import is_hcsp_identifier


class NormalizedProcessType(ABC):
    r"""Abstract category of normalized process types."""

    def __new__(cls, *args: Any, **kwargs: Any) -> "NormalizedProcessType":
        r"""Prevent direct instantiation of the abstract process category."""

        if cls is NormalizedProcessType:
            raise TypeError("NormalizedProcessType is an abstract category")
        return super().__new__(cls)


class NormalizedAngelicType(ABC):
    r"""Abstract category of normalized angelic interrupt types."""

    def __new__(cls, *args: Any, **kwargs: Any) -> "NormalizedAngelicType":
        r"""Prevent direct instantiation of the abstract angelic category."""

        if cls is NormalizedAngelicType:
            raise TypeError("NormalizedAngelicType is an abstract category")
        return super().__new__(cls)


@dataclass(frozen=True, slots=True)
class NormalizedEmptyType(NormalizedProcessType):
    r"""Normal termination with no further channel communication."""


@dataclass(frozen=True, slots=True)
class NormalizedBottomType(NormalizedProcessType):
    r"""Bottom error behavior, distinct from normal termination."""


@dataclass(frozen=True, slots=True)
class NormalizedBoundTypeVar(NormalizedProcessType):
    r"""A bound recursion variable represented by a De Bruijn index."""

    index: int

    def __post_init__(self) -> None:
        r"""Require a nonnegative integer De Bruijn index, excluding bool."""

        if isinstance(self.index, bool) or not isinstance(self.index, int):
            raise TypeError("Normalized type-variable index must be an integer")
        if self.index < 0:
            raise ValueError("Normalized type-variable index must be non-negative")


@dataclass(frozen=True, slots=True)
class NormalizedNoInterruptType(NormalizedAngelicType):
    r"""An empty angelic choice with no communication interrupt."""


@dataclass(frozen=True, slots=True)
class NormalizedInputType(NormalizedAngelicType):
    r"""Normalized input interrupt ch?.T."""

    channel: str
    continuation: NormalizedProcessType

    def __post_init__(self) -> None:
        r"""Validate the channel identifier and normalized process continuation."""

        if not is_hcsp_identifier(self.channel):
            raise ValueError("Normalized input channel must be an HCSP identifier")
        if not isinstance(self.continuation, NormalizedProcessType):
            raise TypeError("Normalized input continuation must be a process type")


@dataclass(frozen=True, slots=True)
class NormalizedOutputType(NormalizedAngelicType):
    r"""Normalized output interrupt ch!.T."""

    channel: str
    continuation: NormalizedProcessType

    def __post_init__(self) -> None:
        r"""Validate the channel identifier and normalized process continuation."""

        if not is_hcsp_identifier(self.channel):
            raise ValueError("Normalized output channel must be an HCSP identifier")
        if not isinstance(self.continuation, NormalizedProcessType):
            raise TypeError("Normalized output continuation must be a process type")


NormalizedCommunicationType: TypeAlias = NormalizedInputType | NormalizedOutputType


@dataclass(frozen=True, slots=True)
class NormalizedExternalChoiceType(NormalizedAngelicType):
    r"""External choice sorted and deduplicated by commutativity and idempotence."""

    branches: tuple[NormalizedCommunicationType, ...]

    def __post_init__(self) -> None:
        r"""Require at least two branches in canonical sorted, unique order."""

        if len(self.branches) < 2:
            raise ValueError("Normalized external choice requires at least two branches")
        if not all(
            isinstance(branch, (NormalizedInputType, NormalizedOutputType))
            for branch in self.branches
        ):
            raise TypeError("Normalized external-choice branches must be communications")
        expected = tuple(
            sorted(set(self.branches), key=normalized_angelic_key)
        )
        if self.branches != expected:
            raise ValueError(
                "Normalized external-choice branches must be sorted and unique"
            )


@dataclass(frozen=True, slots=True)
class NormalizedInternalChoiceType(NormalizedProcessType):
    r"""Internal choice flattened, sorted, and deduplicated by associative set semantics."""

    branches: tuple[NormalizedProcessType, ...]

    def __post_init__(self) -> None:
        r"""Reject nested, singleton, unsorted, or duplicate internal choices."""

        if len(self.branches) < 2:
            raise ValueError("Normalized internal choice requires at least two branches")
        if not all(
            isinstance(branch, NormalizedProcessType) for branch in self.branches
        ):
            raise TypeError("Normalized internal-choice branches must be process types")
        if any(
            isinstance(branch, NormalizedInternalChoiceType)
            for branch in self.branches
        ):
            raise ValueError("Normalized internal choices must be flattened")
        expected = tuple(
            sorted(set(self.branches), key=normalized_process_key)
        )
        if self.branches != expected:
            raise ValueError(
                "Normalized internal-choice branches must be sorted and unique"
            )


def _normalize_duration(duration: Any) -> Fraction:
    r"""Require a nonnegative exact rational delay."""

    if isinstance(duration, bool):
        raise TypeError("Normalized duration must not be Boolean")
    if isinstance(duration, Fraction):
        value = duration
    elif isinstance(duration, int):
        value = Fraction(duration)
    else:
        raise TypeError("Normalized duration must be an int or Fraction")
    if value < 0:
        raise ValueError("Normalized duration must be non-negative")
    return value


@dataclass(frozen=True, slots=True, init=False)
class NormalizedFiniteDelayType(NormalizedProcessType):
    r"""Normalized finite delay with interrupts and a timeout continuation."""

    duration: Fraction
    interrupts: NormalizedAngelicType
    continuation: NormalizedProcessType

    def __init__(
        self,
        duration: int | Fraction,
        interrupts: NormalizedAngelicType,
        continuation: NormalizedProcessType,
    ) -> None:
        r"""Freeze an exact duration, interrupt type, and timeout continuation."""

        if not isinstance(interrupts, NormalizedAngelicType):
            raise TypeError("Normalized finite delay requires an angelic type")
        if not isinstance(continuation, NormalizedProcessType):
            raise TypeError("Normalized finite delay requires a process continuation")
        object.__setattr__(self, "duration", _normalize_duration(duration))
        object.__setattr__(self, "interrupts", interrupts)
        object.__setattr__(self, "continuation", continuation)


@dataclass(frozen=True, slots=True)
class NormalizedInfiniteDelayType(NormalizedProcessType):
    r"""Infinite delay with a semantically unreachable Bottom timeout continuation."""

    interrupts: NormalizedAngelicType

    def __post_init__(self) -> None:
        r"""Require a normalized angelic interrupt type for infinite delay."""

        if not isinstance(self.interrupts, NormalizedAngelicType):
            raise TypeError("Normalized infinite delay requires an angelic type")


@dataclass(frozen=True, slots=True)
class NormalizedMuType(NormalizedProcessType):
    r"""Nameless recursion using De Bruijn variable references."""

    body: NormalizedProcessType

    def __post_init__(self) -> None:
        r"""Require a process body with communication-guarded recursion references."""

        if not isinstance(self.body, NormalizedProcessType):
            raise TypeError("Normalized recursive body must be a process type")
        if not _target_binder_guarded(self.body, 0, False):
            raise ValueError("Normalized recursive variable is not communication-guarded")


def make_normalized_internal_choice(
    branches: Iterable[NormalizedProcessType],
) -> NormalizedProcessType:
    r"""Flatten and deduplicate internal choice, returning a lone branch directly."""

    flat: list[NormalizedProcessType] = []
    for branch in branches:
        if not isinstance(branch, NormalizedProcessType):
            raise TypeError("Normalized internal-choice branch must be a process type")
        if isinstance(branch, NormalizedInternalChoiceType):
            flat.extend(branch.branches)
        else:
            flat.append(branch)
    if not flat:
        raise ValueError("Normalized internal choice cannot be empty")
    unique = tuple(sorted(set(flat), key=normalized_process_key))
    if len(unique) == 1:
        return unique[0]
    return NormalizedInternalChoiceType(unique)


def make_normalized_external_choice(
    branches: Iterable[NormalizedCommunicationType],
) -> NormalizedAngelicType:
    r"""Canonicalize zero, one, or multiple external-choice branches."""

    items = tuple(branches)
    if not all(
        isinstance(branch, (NormalizedInputType, NormalizedOutputType))
        for branch in items
    ):
        raise TypeError("Normalized external-choice branch must be a communication")
    unique = tuple(sorted(set(items), key=normalized_angelic_key))
    if not unique:
        return NormalizedNoInterruptType()
    if len(unique) == 1:
        return unique[0]
    return NormalizedExternalChoiceType(unique)


def normalized_process_key(value: NormalizedProcessType) -> tuple[Any, ...]:
    r"""Compute a stable total-order process key using iterative postorder traversal."""

    return _normalized_key(value)


def normalized_angelic_key(value: NormalizedAngelicType) -> tuple[Any, ...]:
    r"""Compute a stable angelic key using iterative postorder traversal."""

    return _normalized_key(value)


def _normalized_children(
    value: NormalizedProcessType | NormalizedAngelicType,
) -> tuple[NormalizedProcessType | NormalizedAngelicType, ...]:
    r"""Return direct children needed to compute structural keys."""

    if isinstance(value, (NormalizedInputType, NormalizedOutputType)):
        return (value.continuation,)
    if isinstance(value, (NormalizedExternalChoiceType, NormalizedInternalChoiceType)):
        return value.branches
    if isinstance(value, NormalizedFiniteDelayType):
        return (value.interrupts, value.continuation)
    if isinstance(value, NormalizedInfiniteDelayType):
        return (value.interrupts,)
    if isinstance(value, NormalizedMuType):
        return (value.body,)
    return ()


def _normalized_key(
    root: NormalizedProcessType | NormalizedAngelicType,
) -> tuple[Any, ...]:
    r"""Compute immutable keys for deep Types with an explicit stack."""

    results: dict[int, tuple[Any, ...]] = {}
    pending = [(root, False)]
    while pending:
        current, exiting = pending.pop()
        key = id(current)
        if key in results:
            continue
        children = _normalized_children(current)
        if not exiting and children:
            pending.append((current, True))
            pending.extend((child, False) for child in reversed(children))
            continue
        child_keys = tuple(results[id(child)] for child in children)
        if isinstance(current, NormalizedEmptyType): value = ("00-empty",)
        elif isinstance(current, NormalizedBottomType): value = ("01-bottom",)
        elif isinstance(current, NormalizedBoundTypeVar): value = ("02-bound", current.index)
        elif isinstance(current, NormalizedInternalChoiceType): value = ("03-internal", child_keys)
        elif isinstance(current, NormalizedFiniteDelayType):
            value = ("04-finite", current.duration.numerator, current.duration.denominator, child_keys[0], child_keys[1])
        elif isinstance(current, NormalizedInfiniteDelayType): value = ("05-infinite", child_keys[0])
        elif isinstance(current, NormalizedMuType): value = ("06-mu", child_keys[0])
        elif isinstance(current, NormalizedNoInterruptType): value = ("00-none",)
        elif isinstance(current, NormalizedInputType): value = ("01-input", current.channel, child_keys[0])
        elif isinstance(current, NormalizedOutputType): value = ("02-output", current.channel, child_keys[0])
        elif isinstance(current, NormalizedExternalChoiceType): value = ("03-external", child_keys)
        else:
            raise TypeError(f"Unsupported normalized type: {type(current).__name__}")
        results[key] = value
    return results[id(root)]


def _target_binder_guarded(
    value: NormalizedProcessType,
    nested_depth: int,
    under_communication: bool,
) -> bool:
    r"""Require communication before every reference to the target outer mu binder."""

    pending: list[tuple[object, int, bool, bool]] = [
        (value, nested_depth, under_communication, False)
    ]
    while pending:
        current, depth, protected, angelic = pending.pop()
        if not angelic:
            if isinstance(current, (NormalizedEmptyType, NormalizedBottomType)):
                continue
            if isinstance(current, NormalizedBoundTypeVar):
                if current.index == depth and not protected:
                    return False
                continue
            if isinstance(current, NormalizedInternalChoiceType):
                pending.extend(
                    (branch, depth, protected, False)
                    for branch in current.branches
                )
                continue
            if isinstance(current, NormalizedFiniteDelayType):
                pending.append((current.continuation, depth, protected, False))
                pending.append((current.interrupts, depth, protected, True))
                continue
            if isinstance(current, NormalizedInfiniteDelayType):
                pending.append((current.interrupts, depth, protected, True))
                continue
            if isinstance(current, NormalizedMuType):
                pending.append((current.body, depth + 1, protected, False))
                continue
            raise TypeError(
                f"Unsupported normalized process type: {type(current).__name__}"
            )

        if isinstance(current, NormalizedNoInterruptType):
            continue
        if isinstance(current, (NormalizedInputType, NormalizedOutputType)):
            pending.append((current.continuation, depth, True, False))
            continue
        if isinstance(current, NormalizedExternalChoiceType):
            pending.extend(
                (branch, depth, protected, True)
                for branch in current.branches
            )
            continue
        raise TypeError(
            f"Unsupported normalized angelic type: {type(current).__name__}"
        )
    return True


@dataclass(frozen=True, slots=True, init=False)
class NormalizedConfigurationType:
    r"""Canonical parallel configuration with Empty as its identity."""

    components: tuple[NormalizedProcessType, ...]

    def __init__(self, components: Iterable[NormalizedProcessType]) -> None:
        r"""Remove Empty roots, sort components, and preserve parallel multiplicity."""

        items = tuple(components)
        if not all(isinstance(item, NormalizedProcessType) for item in items):
            raise TypeError("Normalized configuration components must be process types")
        nonempty = tuple(
            item for item in items if not isinstance(item, NormalizedEmptyType)
        )
        if nonempty:
            canonical = tuple(sorted(nonempty, key=normalized_process_key))
        else:
            canonical = (NormalizedEmptyType(),)
        object.__setattr__(self, "components", canonical)

    @property
    def is_empty(self) -> bool:
        r"""Recognize the canonical empty configuration."""

        return len(self.components) == 1 and isinstance(
            self.components[0], NormalizedEmptyType
        )
