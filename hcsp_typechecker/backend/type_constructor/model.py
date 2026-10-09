r"""Construction-specific request and report models."""

from __future__ import annotations

from dataclasses import dataclass
from typing import Any, Mapping, Sequence

from ...data_structures.runtime_context import (
    ChannelType,
    Configuration,
    GammaType,
    ParameterEnvironment,
)
from ..common.model import RuleDerivationReport
# Copy request environments and normalize configuration shorthand; the engine validates
# environment types.
@dataclass(frozen=True, slots=True)
class TypeConstructionRequest:
    r"""A complete internal type-construction request."""

    gamma: Mapping[str, GammaType]
    theta: Mapping[str, ChannelType | Any]
    configurations: tuple[Configuration, ...]
    path_condition: Any = True
    parameters: ParameterEnvironment = ParameterEnvironment()


    def __init__(
        self,
        gamma: Mapping[str, GammaType] | None,
        theta: Mapping[str, ChannelType | Any] | None,
        configurations: Sequence[Configuration | tuple[Mapping[str, Any], Any] | Any],
        path_condition: Any = True,
        parameters: ParameterEnvironment | Mapping[str, Any] | None = None,
    ) -> None:
        r"""Normalize supported environment and configuration input forms."""
        normalized_configs: list[Configuration] = []
        for item in configurations:
            if isinstance(item, Configuration):
                normalized_configs.append(item)
            elif isinstance(item, tuple) and len(item) == 2 and isinstance(item[0], Mapping):
                normalized_configs.append(Configuration(item[0], item[1]))
            else:
                normalized_configs.append(Configuration({}, item))
        object.__setattr__(self, "gamma", {} if gamma is None else dict(gamma))
        object.__setattr__(self, "theta", {} if theta is None else dict(theta))
        object.__setattr__(self, "configurations", tuple(normalized_configs))
        object.__setattr__(self, "path_condition", path_condition)
        if parameters is None:
            parameter_environment = ParameterEnvironment()
        elif isinstance(parameters, ParameterEnvironment):
            parameter_environment = parameters
        elif isinstance(parameters, Mapping):
            parameter_environment = ParameterEnvironment(parameters)
        else:
            raise TypeError(
                "parameters must be a ParameterEnvironment, mapping, or None"
            )
        object.__setattr__(self, "parameters", parameter_environment)


@dataclass(frozen=True, slots=True)
class TypeConstructionReport(RuleDerivationReport):
    r"""The construction result with rule and proof evidence."""


__all__ = [
    "TypeConstructionReport",
    "TypeConstructionRequest",
]
