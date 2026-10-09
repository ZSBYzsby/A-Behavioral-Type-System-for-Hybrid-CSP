r"""Lower formal Type ASTs into Table 3 normalized Types."""

from __future__ import annotations

from ..type_ast.ast import (
    AngelicType,
    BottomType,
    ConfigurationType,
    EmptyType,
    ExternalChoiceType,
    FiniteDelayType,
    InfiniteDelayType,
    InputType,
    InternalChoiceType,
    MuType,
    NoInterruptType,
    OutputType,
    ParallelType,
    ProcessType,
    TypeVar,
)
from .ast import (
    NormalizedAngelicType,
    NormalizedBottomType,
    NormalizedBoundTypeVar,
    NormalizedConfigurationType,
    NormalizedEmptyType,
    NormalizedFiniteDelayType,
    NormalizedInfiniteDelayType,
    NormalizedInputType,
    NormalizedMuType,
    NormalizedNoInterruptType,
    NormalizedOutputType,
    NormalizedProcessType,
    make_normalized_external_choice,
    make_normalized_internal_choice,
)


class TypeNormalizationError(ValueError):
    r"""A Type violates normalization prerequisites such as closure."""


def normalize_type_ast(
    value: ConfigurationType,
) -> NormalizedConfigurationType:
    r"""Convert a closed configuration Type into an immutable normalized configuration."""

    if not isinstance(value, ConfigurationType):
        raise TypeError("Type normalization requires a ConfigurationType root")

    components: list[ProcessType] = []
    pending_configurations: list[ConfigurationType] = [value]
    while pending_configurations:
        current = pending_configurations.pop()
        if isinstance(current, ParallelType):
            pending_configurations.extend(reversed(current.components))
        elif isinstance(current, ProcessType):
            components.append(current)
        else:
            raise TypeError(
                f"Unsupported configuration type: {type(current).__name__}"
            )
    normalized = tuple(_normalize_subtree(component, ()) for component in components)
    return NormalizedConfigurationType(normalized)


def _normalization_children(
    value: ProcessType | AngelicType,
    binders: tuple[str, ...],
) -> tuple[tuple[ProcessType | AngelicType, tuple[str, ...]], ...]:
    r"""Return postorder children with their recursion environments."""

    if isinstance(value, (InputType, OutputType)):
        return ((value.continuation, binders),)
    if isinstance(value, (ExternalChoiceType, InternalChoiceType)):
        return tuple((branch, binders) for branch in value.branches)
    if isinstance(value, FiniteDelayType):
        return ((value.interrupts, binders), (value.continuation, binders))
    if isinstance(value, InfiniteDelayType):
        return ((value.interrupts, binders),)
    if isinstance(value, MuType):
        return ((value.body, binders + (value.variable,)),)
    return ()


def _normalize_subtree(
    root: ProcessType,
    binders: tuple[str, ...],
) -> NormalizedProcessType:
    r"""Normalize deep continuation trees using an explicit postorder stack."""

    TaskKey = tuple[int, tuple[str, ...]]
    results: dict[TaskKey, NormalizedProcessType | NormalizedAngelicType] = {}
    pending: list[
        tuple[ProcessType | AngelicType, tuple[str, ...], bool]
    ] = [(root, binders, False)]
    while pending:
        current, environment, exiting = pending.pop()
        key: TaskKey = (id(current), environment)
        if key in results:
            continue
        children = _normalization_children(current, environment)
        if not exiting and children:
            pending.append((current, environment, True))
            pending.extend(
                (child, child_environment, False)
                for child, child_environment in reversed(children)
            )
            continue

        child_values = tuple(
            results[(id(child), child_environment)]
            for child, child_environment in children
        )
        if isinstance(current, EmptyType):
            result: NormalizedProcessType | NormalizedAngelicType = NormalizedEmptyType()
        elif isinstance(current, BottomType):
            result = NormalizedBottomType()
        elif isinstance(current, TypeVar):
            try:
                reverse_index = environment[::-1].index(current.name)
            except ValueError as exc:
                raise TypeNormalizationError(
                    f"Free type variable {current.name!r} cannot appear in a normalized state"
                ) from exc
            result = NormalizedBoundTypeVar(reverse_index)
        elif isinstance(current, NoInterruptType):
            result = NormalizedNoInterruptType()
        elif isinstance(current, InputType):
            result = NormalizedInputType(current.channel, child_values[0])
        elif isinstance(current, OutputType):
            result = NormalizedOutputType(current.channel, child_values[0])
        elif isinstance(current, ExternalChoiceType):
            result = make_normalized_external_choice(child_values)
        elif isinstance(current, InternalChoiceType):
            result = make_normalized_internal_choice(child_values)
        elif isinstance(current, FiniteDelayType):
            result = NormalizedFiniteDelayType(
                current.duration, child_values[0], child_values[1]
            )
        elif isinstance(current, InfiniteDelayType):
            result = NormalizedInfiniteDelayType(child_values[0])
        elif isinstance(current, MuType):
            result = NormalizedMuType(child_values[0])
        else:
            raise TypeError(
                f"Unsupported behavioral type: {type(current).__name__}"
            )
        results[key] = result
    normalized_root = results[(id(root), binders)]
    if not isinstance(normalized_root, NormalizedProcessType):
        raise TypeError("Process normalization produced a non-process root")
    return normalized_root
