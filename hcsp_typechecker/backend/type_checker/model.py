r"""Immutable requests and evidence for checking supplied Types."""

from __future__ import annotations

from dataclasses import dataclass
from typing import Mapping

from ...data_structures.runtime_context import (
    ChannelType,
    Configuration,
    GammaType,
    ParameterEnvironment,
)
from ...data_structures.type_ast.ast import ConfigurationType
from ..common.model import RuleDerivationReport, Verdict


@dataclass(frozen=True, slots=True)
class TypeCheckingRequest:
    r"""Internal input for checking configurations against an expected type."""

    gamma: Mapping[str, GammaType]
    theta: Mapping[str, ChannelType]
    configurations: tuple[Configuration, ...]
    expected_type: ConfigurationType
    path_condition: object = True
    parameters: ParameterEnvironment = ParameterEnvironment()


@dataclass(frozen=True, slots=True)
class TypeCheckingReport:
    r"""A supplied Type's rule-checking result and proof evidence."""

    verdict: Verdict
    expected_type: ConfigurationType
    evidence: RuleDerivationReport
    mismatch: str = ""
    failure_reason: str = ""

    @property
    def passed(self) -> bool:
        r"""Return true only for matching structure and proved premises."""

        return self.verdict is Verdict.TRUE

    @property
    def structurally_matched(self) -> bool:
        r"""Require complete rule consumption of the Type and preceding premises."""

        return self.evidence.constructed_type is not None

    def format_detailed(self) -> str:
        r"""Display matching, formulas, and proof results for the supplied Type."""

        return self.evidence.format_detailed(
            purpose="checking",
            displayed_type=self.expected_type,
        )
