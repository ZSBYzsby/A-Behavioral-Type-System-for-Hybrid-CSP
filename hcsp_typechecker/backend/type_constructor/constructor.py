r"""Behavioral type construction using the shared Table 2 engine."""

from __future__ import annotations

from typing import Any, Mapping, Sequence

from ...data_structures.runtime_context import (
    ChannelType,
    Configuration,
    GammaType,
    ParameterEnvironment,
)
from ...data_structures.type_ast.ast import ConfigurationType, ParallelType
from ..common.model import DLChecker, Verdict
from ..common.keymaerax import KeYmaeraXConfig
from ..common.rule_engine import Table2RuleEngine, _ConstructionFailure
from .model import TypeConstructionReport, TypeConstructionRequest


class TypeConstructor(Table2RuleEngine):
    r"""Construct HCSP behavioral Types using the implemented Table 2 rules."""

    def construct(
        self,
        request: TypeConstructionRequest,
    ) -> TypeConstructionReport:
        r"""Execute a request and return the type, verdict, and evidence."""

        return self._construct_type(request)

    def _report(
        self,
        constructed: ConfigurationType | None,
        constructed_component_types: tuple[ConfigurationType | None, ...],
    ) -> TypeConstructionReport:
        r"""Convert shared engine evidence into a construction report."""

        verdict = Verdict.combine(
            [item.verdict for item in self.obligations if item.active]
            + [item.verdict for item in self.diagnostics]
        )
        return TypeConstructionReport(
            verdict=verdict,
            constructed_type=constructed,
            constructed_component_types=constructed_component_types,
            obligations=tuple(self.obligations),
            diagnostics=tuple(self.diagnostics),
            steps=tuple(self.steps),
        )

    def _construct_type(
        self,
        request: TypeConstructionRequest,
    ) -> TypeConstructionReport:
        r"""Run complete construction and retain all proof evidence."""
        # Reset reports and fresh-name counters for each request on a reused engine.
        self.obligations = []
        self.diagnostics = []
        self.steps = []
        self._fresh_counter = 0
        self._type_var_counter = 0

        prepared = self._prepare_typing_environment(
            gamma_source=request.gamma,
            theta_source=request.theta,
            parameter_environment=request.parameters,
            path_condition=request.path_condition,
        )
        if prepared is None:
            return self._report(None, ())
        gamma = prepared.gamma
        theta = prepared.theta
        parameters = prepared.parameters
        parameter_symbols = prepared.parameter_symbols
        parameter_condition = prepared.parameter_condition

        if not request.configurations:
            self._diagnose(
                Verdict.FALSE,
                "A construction request needs at least one configuration",
                "T-||",
            )
            return self._report(None, ())

        # Use T-|| even for one configuration to preserve common Gamma and T-sigma checks.
        parallel_expansion = self.rule_t_parallel(
            request.configurations,
            gamma,
            theta,
            request.path_condition,
            parameters,
            parameter_symbols,
            parameter_condition,
            request.parameters.constraint,
        )
        raw_constructed_component_types = self._solve_rule_expansion(
            parallel_expansion
        )
        # Expose failed components as None, never as an internal failure sentinel or fabricated
        # Type.
        constructed_component_types: tuple[ConfigurationType | None, ...] = tuple(
            None if isinstance(item, _ConstructionFailure) else item
            for item in raw_constructed_component_types
        )
        successful_components = tuple(
            item for item in constructed_component_types if item is not None
        )
        constructed: ConfigurationType | None
        if (
            not constructed_component_types
            or len(successful_components) != len(constructed_component_types)
        ):
            constructed = None
        elif len(successful_components) == 1:
            constructed = successful_components[0]
        else:
            constructed = ParallelType(successful_components)

        return self._report(constructed, constructed_component_types)

def construct_type(
    *,
    gamma: Mapping[str, GammaType] | None,
    theta: Mapping[str, ChannelType | Any] | None,
    configurations: Sequence[Configuration | tuple[Mapping[str, Any], Any] | Any],
    path_condition: Any = True,
    parameters: ParameterEnvironment | Mapping[str, Any] | None = None,
    dl_checker: DLChecker | None = None,
    keymaerax_config: KeYmaeraXConfig | None = None,
    z3_timeout_ms: int = 5_000,
) -> TypeConstructionReport:
    r"""Construct a type from internal ASTs, contexts, and configurations."""

    request = TypeConstructionRequest(
        gamma=gamma,
        theta=theta,
        configurations=configurations,
        path_condition=path_condition,
        parameters=parameters,
    )
    return TypeConstructor(
        dl_checker=dl_checker,
        keymaerax_config=keymaerax_config,
        z3_timeout_ms=z3_timeout_ms,
    ).construct(request)
