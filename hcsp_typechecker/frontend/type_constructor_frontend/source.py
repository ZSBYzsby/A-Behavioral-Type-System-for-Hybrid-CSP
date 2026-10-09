r"""Aggregate domain models lowered from complete HCSP input."""

from __future__ import annotations

from dataclasses import dataclass, field
from types import MappingProxyType
from typing import Mapping

from ...data_structures.process_ast.ast import HCSP, Parallel, Process
from ...data_structures.runtime_context import (
    ChannelType,
    GammaType,
    ParameterEnvironment,
)


@dataclass(frozen=True, slots=True)
class ParsedHCSPSource:
    r"""The four formal model results of one complete source parse."""

    gamma: Mapping[str, GammaType]
    theta: Mapping[str, ChannelType]
    process: HCSP
    parameters: ParameterEnvironment = field(
        default_factory=ParameterEnvironment
    )

    def __post_init__(self) -> None:
        r"""Copy environments defensively and expose read-only snapshots."""

        object.__setattr__(
            self,
            "gamma",
            MappingProxyType(dict(self.gamma)),
        )
        object.__setattr__(
            self,
            "theta",
            MappingProxyType(dict(self.theta)),
        )
        if not isinstance(self.parameters, ParameterEnvironment):
            raise TypeError(
                "ParsedHCSPSource parameters must be a ParameterEnvironment"
            )
        object.__setattr__(
            self,
            "parameters",
            ParameterEnvironment(
                self.parameters.declarations,
                self.parameters.constraint,
            ),
        )

    @property
    def process_components(self) -> tuple[Process, ...]:
        r"""Return top-level process leaves in source order."""

        def flatten(system: HCSP) -> tuple[Process, ...]:
            r"""Flatten top-level Parallel iteratively, requiring Process leaves."""

            components: list[Process] = []
            pending: list[HCSP] = [system]
            while pending:
                current = pending.pop()
                if isinstance(current, Parallel):
                    pending.append(current.right)
                    pending.append(current.left)
                    continue
                if not isinstance(current, Process):
                    raise TypeError(
                        "Parsed process system has a non-Process Parallel leaf: "
                        f"{type(current).__name__}"
                    )
                components.append(current)
            return tuple(components)

        return flatten(self.process)
