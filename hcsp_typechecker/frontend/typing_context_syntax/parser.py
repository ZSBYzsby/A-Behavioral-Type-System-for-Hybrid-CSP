r"""Parse typing-context fragments into internal environments."""

from __future__ import annotations

from dataclasses import dataclass
from types import MappingProxyType
from typing import Mapping

from ..type_constructor_frontend.parser import Parser, _checked_source
from ...data_structures.runtime_context import (
    ChannelType,
    GammaType,
    ParameterEnvironment,
)


@dataclass(frozen=True, slots=True)
class ParsedTypingContext:
    r"""Read-only lowered Gamma, Theta, and parameter snapshots."""

    gamma: Mapping[str, GammaType]
    theta: Mapping[str, ChannelType]
    parameters: ParameterEnvironment

    def __post_init__(self) -> None:
        r"""Copy mutable mappings to protect parsed context snapshots."""

        object.__setattr__(self, "gamma", MappingProxyType(dict(self.gamma)))
        object.__setattr__(self, "theta", MappingProxyType(dict(self.theta)))
        if not isinstance(self.parameters, ParameterEnvironment):
            raise TypeError("parameters must be a ParameterEnvironment")
        object.__setattr__(
            self,
            "parameters",
            ParameterEnvironment(
                self.parameters.declarations,
                self.parameters.constraint,
            ),
        )


def parse_typing_context(
    source: str,
    *,
    source_name: str = "<typing-context>",
) -> ParsedTypingContext:
    r"""Parse gamma [parameters] theta followed by EOF."""

    parser = Parser(_checked_source(source, source_name), source_name)
    gamma = parser._parse_gamma_section()
    parameters = (
        parser._parse_parameter_section(forbidden_names=frozenset(gamma))
        if parser.current.kind == "parameters"
        else ParameterEnvironment()
    )
    theta = parser._parse_theta_section()
    parser._expect("EOF")
    return ParsedTypingContext(gamma, theta, parameters)
