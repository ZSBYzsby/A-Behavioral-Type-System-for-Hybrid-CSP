r"""Expand Table 2 rules and solve their ordered premises for both type engines.

Each expansion separates child judgments from formula premises. Explicit work
stacks preserve premise order and stop at a definite failure without relying on
Python recursion depth. Construction produces conclusions; checking supplies
them. Environment preparation and proof evidence remain shared.
"""

from __future__ import annotations

from dataclasses import dataclass, field, replace
from enum import Enum
from math import inf
from typing import Any, Callable, Mapping, Sequence

from ...identifiers import is_hcsp_identifier
from ...data_structures.process_ast.expressions import Literal, ensure_expr
from .dl import (
    DLFormula,
    DLTranslationError,
    UntranslatedDLFormula,
    domain_formula,
    boundary_formula,
    safety_formula,
)
from ...data_structures.process_ast.ast import (
    Assert,
    Assign,
    Channel,
    EmptyEvent,
    EventChoice,
    EventReaction,
    HCSP,
    If,
    InputChannel,
    InternalChoice,
    Mu,
    ODE,
    OutputChannel,
    Parallel,
    Process,
    Sequence as SequenceHP,
    Skip,
    Var,
)
from .logic import (
    ExprResult,
    ExpressionError,
    ExpressionTranslator,
    Z3ProofEngine,
    conjunction,
    implies,
    lvalue_name,
    negation,
    simplify,
    z3,
)
from .keymaerax import KeYmaeraXBackend, KeYmaeraXConfig
from ...data_structures.type_ast.ast import (
    AngelicType,
    ConfigurationType,
    EmptyType,
    BottomType,
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
    make_external_choice,
    make_delay_type,
    types_equivalent,
)
from ...data_structures.type_ast.render import (
    format_angelic_type,
    format_configuration_type,
    format_process_type,
)
from ...data_structures.runtime_context import (
    BasicType,
    ChannelType,
    Configuration,
    ContinuousType,
    GammaType,
    ParameterEnvironment,
    gamma_value_type,
    is_subtype,
    normalize_channel_type,
    normalize_gamma_type,
    normalize_type,
)
from .environment import PreparedTypingEnvironment
from .model import (
    DLChecker,
    DLCheckResult,
    Diagnostic,
    DerivationStep,
    ProofObligation,
    RuleDerivationReport,
    Verdict,
)


@dataclass(slots=True)
class _RecBinding:
    r"""Bind a source recursion variable to a fresh behavioral type variable."""

    source_name: str
    type_var: TypeVar
    invariant: Any


@dataclass(slots=True)
class _Context:
    r"""Mutable branch-local derivation context."""

    gamma: dict[str, GammaType]
    parameters: dict[str, BasicType]
    parameter_condition: Any
    configuration_path: Any
    theta: dict[str, ChannelType]
    path: Any
    symbols: dict[str, Any]
    rec_env: dict[str, _RecBinding] = field(default_factory=dict)
    location: str = ""
    static_valid: bool = True

    def clone(self, *, location: str | None = None) -> "_Context":
        r"""Clone branch-local state while sharing the read-only channel environment."""
        return _Context(
            gamma=dict(self.gamma),
            parameters=dict(self.parameters),
            parameter_condition=self.parameter_condition,
            configuration_path=self.configuration_path,
            theta=self.theta,
            path=self.path,
            symbols=dict(self.symbols),
            rec_env=dict(self.rec_env),
            location=self.location if location is None else location,
            static_valid=self.static_valid,
        )


@dataclass(frozen=True, slots=True)
class _LazyAssignmentPostState:
    r"""The deterministic lazy strongest post-state used by T-Assign."""

    target: str
    previous_term: Any
    assigned_term: Any
    pre_path: Any
    post_context: _Context


@dataclass(frozen=True, slots=True)
class _ODEDLTerms:
    r"""Entry-state Z3 terms required to construct an ODE dL obligation."""

    precondition: Any
    equations: tuple[tuple[Any, Any], ...]
    domain: Any
    domain_definedness: Any
    safety: Any
    duration: Any | None
    clock: Any


class _ODEPostAssumption(str, Enum):
    r"""Path facts available in the three kinds of ODE successor judgment."""

    DOMAIN_AND_SAFETY = "domain-and-safety"
    SAFETY = "safety"
    NOT_DOMAIN_AND_SAFETY = "not-domain-and-safety"


class _ODETypeRule(str, Enum):
    r"""The two Table 2 rules applicable to an explicit ODE; skip."""

    COMMUNICATION_ONLY = "communication-only"
    NATURAL_TIMEOUT = "natural-timeout"


@dataclass(frozen=True, slots=True)
class _ProofRequest:
    r"""A formula premise decided at its position in the derivation."""

    obligation: ProofObligation
    state: Mapping[str, Any] | None = None
    symbols: Mapping[str, Any] | None = None
    automatically_true: bool = False


# Judgments store conclusions' inputs; rule_t_* methods only expand them into premises.
@dataclass(frozen=True, slots=True)
class _ConfigurationJudgment:
    r"""The typing judgment for a partial-state configuration <sigma, S>."""

    state: Mapping[str, Any]
    system: Any
    context: _Context


@dataclass(frozen=True, slots=True)
class _SystemJudgment:
    r"""The configuration-type judgment for S ::= P | S || S'."""

    system: Any
    context: _Context


@dataclass(frozen=True, slots=True)
class _ProcessJudgment:
    r"""The judgment for a process sequence and its terminal continuation."""

    nodes: tuple[Process, ...]
    context: _Context
    terminal: ProcessType


@dataclass(frozen=True, slots=True)
class _EventJudgment:
    r"""The angelic-type judgment for an ODE communication reaction."""

    reaction: EventReaction
    tail: tuple[Process, ...]
    context: _Context
    terminal: ProcessType


_ChildJudgment = (
    _ConfigurationJudgment
    | _SystemJudgment
    | _ProcessJudgment
    | _EventJudgment
)


# The solver decides formula premises and expands child judgments; conclude receives only child
# types.
@dataclass(frozen=True, slots=True)
class _FormulaPremise:
    r"""An ordered state, FOL, or dL formula premise."""

    request: _ProofRequest


@dataclass(frozen=True, slots=True)
class _ChildJudgmentPremise:
    r"""A child judgment that must produce a candidate type."""

    judgment: _ChildJudgment


_Premise = _FormulaPremise | _ChildJudgmentPremise


@dataclass(frozen=True, slots=True)
class _RuleExpansion:
    r"""One rule's premises and the composition of child conclusions."""

    rule: str
    premises: tuple[_Premise, ...]
    conclude: Callable[[tuple[Any, ...]], Any]
    assignment_post_state: _LazyAssignmentPostState | None = None


@dataclass(slots=True)
class _ConstructionEvalFrame:
    r"""Explicit Constructor evaluation progress for one rule."""

    expansion: _RuleExpansion
    premise_index: int = 0
    child_results: list[Any] = field(default_factory=list)
    finish: Callable[[Any], None] | None = None


@dataclass(frozen=True, slots=True)
class _ConstructionFailure:
    r"""A process fragment cannot yield a behavioral type under Table 2."""


# Propagate an internal failure sentinel without fabricating a parent containing BottomType.
_CONSTRUCTION_FAILURE = _ConstructionFailure()
_ProcessConstructionResult = ProcessType | _ConstructionFailure
_ConfigurationConstructionResult = ConfigurationType | _ConstructionFailure


@dataclass(frozen=True, slots=True)
class _ODECandidateAttempt:
    r"""An isolated ODE candidate result with uncommitted audit evidence."""

    mode: _ODETypeRule
    result: _ProcessConstructionResult
    verdict: Verdict
    obligations: tuple[ProofObligation, ...]
    diagnostics: tuple[Diagnostic, ...]
    steps: tuple[DerivationStep, ...]


class Table2RuleEngine:
    r"""Shared rule expansion, symbolic execution, and proof decisions."""

    def __init__(
        self,
        *,
        dl_checker: DLChecker | None = None,
        keymaerax_config: KeYmaeraXConfig | None = None,
        z3_timeout_ms: int = 5_000,
    ) -> None:
        r"""Configure the dL backend and per-obligation Z3 timeout."""
        if dl_checker is not None and keymaerax_config is not None:
            raise ValueError(
                "Specify either dl_checker or keymaerax_config, not both"
            )
        self.dl_checker: DLChecker = (
            dl_checker
            if dl_checker is not None
            else KeYmaeraXBackend(keymaerax_config)
        )
        self.proof_engine = Z3ProofEngine(z3_timeout_ms)
        self.obligations: list[ProofObligation] = []
        self.diagnostics: list[Diagnostic] = []
        self.steps: list[DerivationStep] = []
        self._fresh_counter = 0
        self._type_var_counter = 0

    def _prepare_typing_environment(
        self,
        *,
        gamma_source: Mapping[str, GammaType],
        theta_source: Mapping[str, ChannelType | Any],
        parameter_environment: ParameterEnvironment,
        path_condition: Any,
    ) -> PreparedTypingEnvironment | None:
        r"""Normalize and validate the common typing environments."""

        try:
            invalid_gamma_names = {
                repr(name)
                for name in gamma_source
                if not is_hcsp_identifier(name)
            }
            if invalid_gamma_names:
                raise ValueError(
                    "Invalid Gamma names: "
                    + ", ".join(sorted(invalid_gamma_names))
                )
            gamma = {
                name: normalize_gamma_type(value, subject="Gamma entry")
                for name, value in gamma_source.items()
            }
            self._validate_continuous_vectors(gamma)

            invalid_parameter_names = {
                repr(name)
                for name in parameter_environment.declarations
                if not is_hcsp_identifier(name)
            }
            if invalid_parameter_names:
                raise ValueError(
                    "Invalid parameter names: "
                    + ", ".join(sorted(invalid_parameter_names))
                )
            parameters = {
                name: normalize_type(value, subject="Parameter declaration")
                for name, value in parameter_environment.declarations.items()
            }
            overlap = set(gamma) & set(parameters)
            if overlap:
                raise ValueError(
                    "Gamma and the shared parameter environment overlap: "
                    + ", ".join(sorted(overlap))
                )
            theta = {
                self._channel_name(name): normalize_channel_type(value)
                for name, value in theta_source.items()
            }
        except (TypeError, ValueError) as exc:
            self._diagnose(
                Verdict.FALSE,
                f"Invalid typing environment: {exc}",
                "environment",
            )
            return None

        try:
            self._validate_theta_refinements(gamma, theta, parameters)
        except ExpressionError as exc:
            self._diagnose(
                Verdict.FALSE,
                f"Invalid Theta environment: {exc}",
                "environment",
            )
            return None

        parameter_symbols: dict[str, Any] = {}
        translator = ExpressionTranslator(
            parameters,
            parameter_symbols,
            name_prefix="parameter__",
        )
        try:
            for name, value_type in parameters.items():
                translator.symbol(name, value_type)
            constraint_result = translator.boolean_result(
                parameter_environment.constraint
            )
            parameter_condition = conjunction(
                self._defined_term(constraint_result),
                *(
                    domain_constraint
                    for name, value_type in parameters.items()
                    for domain_constraint in self._type_domain_constraints(
                        value_type,
                        parameter_symbols[name],
                    )
                ),
            )
        except ExpressionError as exc:
            self._diagnose(
                Verdict.FALSE,
                f"Invalid shared parameter constraint: {exc}",
                "parameters",
            )
            return None

        parameter_verdict, detail = self.proof_engine.satisfiable(
            parameter_condition
        )
        if parameter_verdict is Verdict.FALSE:
            self._diagnose(
                Verdict.FALSE,
                "Shared parameter constraint must be satisfiable: " + detail,
                "parameters",
            )
            return None
        if parameter_verdict is Verdict.UNKNOWN:
            self._diagnose(
                Verdict.UNKNOWN,
                "Shared parameter constraint satisfiability is unknown; "
                "Table 2 rule processing continues, but the resulting "
                "conclusion is untrusted: "
                + detail,
                "parameters",
            )

        step = self._start_step(
            "environment",
            "judgment",
            'Normalize Gamma, Theta, and shared parameters',
            gamma=gamma,
            parameters=parameters,
            parameter_constraint=parameter_environment.constraint,
            theta=theta,
            path=path_condition,
        )
        self._finish_step(
            step,
            (
                'Environment normalized; parameter constraint satisfiability remains unresolved'
                if parameter_verdict is Verdict.UNKNOWN
                else 'Environment normalization succeeded'
            ),
            (
                'Constructor and Checker share the normalized typing environments shown here.'
                + (
                    (
                        ' The parameter constraint was not disproved as unsatisfiable; '
                        'continue symbolic derivation with a final UNKNOWN, untrusted '
                        'verdict.'
                    )
                    if parameter_verdict is Verdict.UNKNOWN
                    else ""
                )
            ),
        )
        return PreparedTypingEnvironment(
            gamma=gamma,
            theta=theta,
            parameters=parameters,
            parameter_symbols=parameter_symbols,
            parameter_condition=parameter_condition,
        )

    # Configuration and parallel rules
    def rule_t_parallel(
        self,
        configurations: Sequence[Configuration],
        gamma: Mapping[str, GammaType],
        theta: Mapping[str, ChannelType],
        default_path: Any,
        parameters: Mapping[str, BasicType],
        parameter_symbols: Mapping[str, Any],
        parameter_condition: Any,
        parameter_constraint: Any,
    ) -> _RuleExpansion:
        r"""[T-||] Expand the top-level judgment into configuration premises."""

        parallel_step = self._start_step(
            "T-||",
            "judgment",
            f"Check {len(configurations)} configurations and their state ownership",
            gamma=gamma,
            parameters=parameters,
            parameter_constraint=parameter_constraint,
            theta=theta,
            path=default_path,
        )

        component_gammas = [dict(gamma) for _configuration in configurations]
        valid_component_gammas: list[bool] = []
        owned_value_domains: list[set[str]] = []
        # Check low-level configuration ownership too; unused Gamma declarations own no state.
        for index, configuration in enumerate(configurations, start=1):
            owned_values = (
                self._process_vars(configuration.process)
                | set(configuration.state)
            ) - set(parameters)
            missing = (
                owned_values
                - set(gamma)
                - self._input_bound_vars(configuration.process)
            )
            for name in sorted(missing):
                self._diagnose(
                    Verdict.FALSE,
                    f"Variable {name!r} is used but not declared in Gamma",
                    "T-||",
                    f"K{index}",
                )
            valid_component_gammas.append(not missing)
            owned_value_domains.append(owned_values)

        # Shared Gamma does not permit shared mutable state; Theta provides communication and
        # parameters are read-only.
        for left in range(len(owned_value_domains)):
            for right in range(left + 1, len(owned_value_domains)):
                overlap = owned_value_domains[left] & owned_value_domains[right]
                if overlap:
                    self._diagnose(
                        Verdict.FALSE,
                        "Parallel components share state variables: "
                        + ", ".join(sorted(overlap)),
                        "T-||",
                        f"K{left + 1}|K{right + 1}",
                    )
                    valid_component_gammas[left] = False
                    valid_component_gammas[right] = False

        # Local paths must cover all configurations; a nontrivial global path cannot compete
        # with them.
        local_path_flags = tuple(
            configuration.path_condition is not None
            for configuration in configurations
        )
        if any(local_path_flags) and not all(local_path_flags):
            self._diagnose(
                Verdict.FALSE,
                "Parallel configurations must either all provide local path "
                "conditions or all use the global default path",
                "T-||",
                "judgment",
            )
            valid_component_gammas = [False] * len(configurations)
        elif all(local_path_flags) and not self._is_default_true_path(default_path):
            self._diagnose(
                Verdict.FALSE,
                "A non-trivial global path cannot be combined with explicit local "
                "paths; leave the global path as true so the local conjunction "
                "defines the [T-||] conclusion",
                "T-||",
                "judgment",
            )
            valid_component_gammas = [False] * len(configurations)

        # Build premises without solving inside the rule; preserve invalid component positions.
        premises: list[_Premise] = []
        for index, (configuration, component_gamma, gamma_is_valid) in enumerate(
            zip(configurations, component_gammas, valid_component_gammas), start=1
        ):
            if not gamma_is_valid:
                continue
            location = configuration.name or f"K{index}"
            context = self._initial_context(
                component_gamma,
                parameters,
                parameter_symbols,
                parameter_condition,
                dict(theta),
                default_path
                if configuration.path_condition is None
                else configuration.path_condition,
                location,
            )
            premises.append(
                _ChildJudgmentPremise(
                    _ConfigurationJudgment(
                        state=dict(configuration.state),
                        system=configuration.process,
                        context=context,
                    )
                )
            )

        validity = tuple(valid_component_gammas)

        def conclude(children: tuple[Any, ...]) -> list[_ConfigurationConstructionResult]:
            r"""Compose configuration results in their original component positions."""

            child_iterator = iter(children)
            types: list[_ConfigurationConstructionResult] = [
                next(child_iterator) if valid else _CONSTRUCTION_FAILURE
                for valid in validity
            ]
            readable_types = ", ".join(
                "(failed)"
                if isinstance(item, _ConstructionFailure)
                else format_configuration_type(item)
                for item in types
            )
            self._finish_step(
                parallel_step,
                f"Component types = [{readable_types}]",
                self._premise_summary(expansion)
                + (
                    ' Explicit child judgments solved; configurations share Gamma/Theta '
                    'with disjoint state ownership.'
                ),
            )
            return types

        expansion = _RuleExpansion("T-||", tuple(premises), conclude)
        return expansion

    def rule_t_sigma(
        self,
        judgment: _ConfigurationJudgment,
    ) -> _RuleExpansion:
        r"""[T-sigma] Generate validity of phi[sigma] and a system judgment."""

        context = judgment.context
        if not context.static_valid:
            return _RuleExpansion(
                "T-sigma",
                (),
                lambda _children: _CONSTRUCTION_FAILURE,
            )
        assigned_parameters = set(judgment.state) & set(context.parameters)
        if assigned_parameters:
            self._diagnose(
                Verdict.FALSE,
                "Initial state cannot assign shared read-only parameters: "
                + ", ".join(sorted(assigned_parameters)),
                "T-sigma",
                context.location,
            )
            return _RuleExpansion(
                "T-sigma",
                (),
                lambda _children: _CONSTRUCTION_FAILURE,
            )
        value_gamma = self._value_gamma(context.gamma)
        undeclared_state_variables = set(judgment.state) - set(value_gamma)
        if undeclared_state_variables:
            names = ", ".join(
                repr(name)
                for name in sorted(undeclared_state_variables, key=repr)
            )
            self._diagnose(
                Verdict.FALSE,
                "Initial state contains variables not declared in Gamma: "
                + names,
                "T-sigma",
                context.location,
            )
            return _RuleExpansion(
                "T-sigma",
                (),
                lambda _children: _CONSTRUCTION_FAILURE,
            )
        # Splitting Configuration({}, Parallel(...)) is sound only with empty Gamma/state and a
        # true path.
        if isinstance(judgment.system, Parallel) and (
            judgment.state
            or context.gamma
            or not self._is_true(context.path)
        ):
            self._diagnose(
                Verdict.FALSE,
                "A stateful Parallel system must be supplied as separate "
                "Configuration leaves with disjoint state ownership and paths",
                "T-||",
                context.location,
            )
            return _RuleExpansion(
                "T-sigma",
                (),
                lambda _children: _CONSTRUCTION_FAILURE,
            )
        state_premise = self._state_premise(
            "T-sigma",
            (
                f"Every admissible shared-parameter assignment makes the "
                f"initial state of {context.location} satisfy its path condition"
            ),
            implies(
                context.parameter_condition,
                context.configuration_path,
            ),
            judgment.state,
            context.symbols,
        )
        system_premise = _ChildJudgmentPremise(
            _SystemJudgment(judgment.system, context)
        )
        return _RuleExpansion(
            "T-sigma",
            (state_premise, system_premise),
            lambda children: children[0],
        )

    # Structural process rules
    def _solve_rule_expansion(
        self,
        expansion: _RuleExpansion,
    ) -> Any:
        r"""Solve rule premises in their declared order."""

        final_result: list[Any] = []
        stack = [_ConstructionEvalFrame(expansion)]
        while stack:
            frame = stack[-1]
            if frame.premise_index >= len(frame.expansion.premises):
                result = frame.expansion.conclude(tuple(frame.child_results))
                stack.pop()
                if frame.finish is not None:
                    frame.finish(result)
                if not stack:
                    final_result.append(result)
                    break
                parent = stack[-1]
                parent.child_results.append(result)
                if isinstance(result, _ConstructionFailure):
                    parent.child_results.extend(
                        _CONSTRUCTION_FAILURE
                        for remaining in parent.expansion.premises[
                            parent.premise_index:
                        ]
                        if isinstance(remaining, _ChildJudgmentPremise)
                    )
                    parent.premise_index = len(parent.expansion.premises)
                continue

            premise = frame.expansion.premises[frame.premise_index]
            frame.premise_index += 1
            if isinstance(premise, _FormulaPremise):
                if self._decide_proof(premise.request).verdict is Verdict.FALSE:
                    result = _CONSTRUCTION_FAILURE
                    stack.pop()
                    if frame.finish is not None:
                        frame.finish(result)
                    if not stack:
                        final_result.append(result)
                        break
                    parent = stack[-1]
                    parent.child_results.append(result)
                    parent.child_results.extend(
                        _CONSTRUCTION_FAILURE
                        for remaining in parent.expansion.premises[
                            parent.premise_index:
                        ]
                        if isinstance(remaining, _ChildJudgmentPremise)
                    )
                    parent.premise_index = len(parent.expansion.premises)
                continue
            if isinstance(premise, _ChildJudgmentPremise):
                child_expansion, finish = self._prepare_child_judgment(
                    premise.judgment
                )
                stack.append(
                    _ConstructionEvalFrame(child_expansion, finish=finish)
                )
                continue
            raise TypeError(
                f"Unsupported premise in {frame.expansion.rule}: "
                f"{type(premise).__name__}"
            )
        return final_result[0]

    def _prepare_child_judgment(
        self,
        judgment: _ChildJudgment,
    ) -> tuple[_RuleExpansion, Callable[[Any], None]]:
        r"""Prepare an explicit child frame while preserving audit step order."""

        if isinstance(judgment, _ConfigurationJudgment):
            context = judgment.context
            step = self._start_step(
                "T-sigma",
                context.location,
                f"Check initial state sigma = {dict(judgment.state)!r}",
                context=context,
            )
            expansion = self.rule_t_sigma(judgment)
            def finish(result: Any) -> None:
                r"""Complete the T-sigma audit step."""

                text = (
                    'Derivation failed; no configuration type was constructed'
                    if isinstance(result, _ConstructionFailure)
                    else 'State premise decided immediately; candidate type = '
                    + format_configuration_type(result)
                )
                self._finish_step(step, text, self._premise_summary(expansion))
            return expansion, finish

        if isinstance(judgment, _SystemJudgment):
            system = judgment.system
            context = judgment.context
            if isinstance(system, Process):
                return self._prepare_child_judgment(
                    _ProcessJudgment(
                        tuple(self._as_nodes(system)), context, EmptyType()
                    )
                )
            if isinstance(system, Parallel):
                step = self._start_step(
                    "T-||", context.location,
                    "Derive the binary system composition S || S'", context=context,
                )
                expansion = self.rule_t_parallel_system(judgment)
                def finish(result: Any) -> None:
                    r"""Complete the parallel system audit step."""

                    text = (
                        'Derivation failed; a parallel system branch has no configuration type'
                        if isinstance(result, _ConstructionFailure)
                        else 'Parallel configuration type = ' + format_configuration_type(result)
                    )
                    self._finish_step(step, text, self._premise_summary(expansion))
                return expansion, finish
            self._diagnose(
                Verdict.FALSE,
                "Configuration process is not an HCSP Process or Parallel system: "
                f"{system.__class__.__name__}", "structural", context.location,
            )
            return _RuleExpansion(
                "structural", (), lambda _children: _CONSTRUCTION_FAILURE
            ), lambda _result: None

        if isinstance(judgment, _ProcessJudgment):
            return self._prepare_process_judgment(judgment)
        if isinstance(judgment, _EventJudgment):
            node = judgment.reaction
            context = judgment.context
            step = self._start_step(
                "T-&", context.location,
                "empty event reaction" if isinstance(node, EmptyEvent)
                else f"Event branch table ({len(node.branches)} communication branches)",
                context=context,
            )
            expansion = self.rule_t_external_choice(judgment)
            def finish(result: Any) -> None:
                r"""Complete the event reaction audit step."""

                if isinstance(result, _ConstructionFailure):
                    text = 'Derivation failed; the event reaction has no angelic type'
                elif isinstance(node, EmptyEvent):
                    text = 'Event-choice recursion result = ' + format_angelic_type(result)
                else:
                    text = 'Event-choice type = ' + format_angelic_type(result)
                self._finish_step(step, text, self._premise_summary(expansion))
            return expansion, finish
        raise TypeError(f"Unsupported child judgment: {type(judgment).__name__}")

    def _prepare_process_judgment(
        self,
        judgment: _ProcessJudgment,
    ) -> tuple[_RuleExpansion, Callable[[Any], None]]:
        r"""Prepare a process rule, delegating ambiguous ODEs to isolated candidate selection."""

        nodes = judgment.nodes
        context = judgment.context
        if not nodes:
            step = self._start_step(
                "T-End", context.location,
                'Empty continuation; use termination type 0', context=context,
            )
            expansion = self.rule_t_end(judgment)
            def finish(result: Any) -> None:
                r"""Complete the implicit termination audit step."""

                self._finish_step(
                    step, 'Candidate type = ' + format_process_type(result),
                    self._premise_summary(expansion),
                )
            return expansion, finish

        head = nodes[0]
        if isinstance(head, ODE) and self._needs_ode_skip_rule_selection(judgment):

            result = self._solve_ode_skip_rule_candidates(judgment)
            return _RuleExpansion("T-ODE-select", (), lambda _children: result), lambda _r: None

        terminal_skip = isinstance(head, Skip) and len(nodes) == 1
        rule = "T-End" if terminal_skip else self._rule_name(head)
        step = self._start_step(
            rule, context.location, self._describe_process_node(head), context=context,
        )
        if isinstance(head, Skip):
            expansion = self.rule_t_end(judgment) if terminal_skip else self.rule_t_skip(judgment)
        elif isinstance(head, Assert): expansion = self.rule_t_assert(judgment)
        elif isinstance(head, Assign): expansion = self.rule_t_assign(judgment)
        elif isinstance(head, InputChannel): expansion = self.rule_t_in(judgment)
        elif isinstance(head, OutputChannel): expansion = self.rule_t_out(judgment)
        elif isinstance(head, If): expansion = self.rule_t_if(judgment)
        elif isinstance(head, InternalChoice): expansion = self.rule_t_internal_choice(judgment)
        elif isinstance(head, ODE): expansion = self.rule_t_ode(judgment)
        elif isinstance(head, Mu): expansion = self.rule_t_mu(judgment)
        elif isinstance(head, Var): expansion = self.rule_t_x(judgment)
        else:
            self._diagnose(
                Verdict.FALSE,
                "Process is not a node from process_ast: "
                f"{head.__class__.__name__}", "structural", context.location,
            )
            expansion = _RuleExpansion(
                "structural", (), lambda _children: _CONSTRUCTION_FAILURE
            )
        def finish(result: Any) -> None:
            r"""Complete the current process audit step."""

            text = (
                'Derivation failed; no behavioral type was constructed'
                if isinstance(result, _ConstructionFailure)
                else 'Candidate type = ' + format_process_type(result)
            )
            self._finish_step(
                step, text,
                self._premise_summary(expansion) + " " + self._rule_explanation(rule),
            )
        return expansion, finish

    def _solve_child_judgment(self, judgment: _ChildJudgment) -> Any:
        r"""Dispatch child judgments through the common derivation solver."""

        if isinstance(judgment, _ConfigurationJudgment):
            return self._solve_configuration_judgment(judgment)
        if isinstance(judgment, _SystemJudgment):
            return self._solve_system_judgment(judgment)
        if isinstance(judgment, _ProcessJudgment):
            return self._solve_process_judgment(judgment)
        if isinstance(judgment, _EventJudgment):
            return self._solve_event_judgment(judgment)
        raise TypeError(f"Unsupported child judgment: {type(judgment).__name__}")

    def _solve_configuration_judgment(
        self,
        judgment: _ConfigurationJudgment,
    ) -> _ConfigurationConstructionResult:
        r"""Solve configuration premises generated by T-sigma."""

        context = judgment.context
        step = self._start_step(
            "T-sigma",
            context.location,
            f"Check initial state sigma = {dict(judgment.state)!r}",
            context=context,
        )
        expansion = self.rule_t_sigma(judgment)
        result = self._solve_rule_expansion(expansion)
        result_text = (
            'Derivation failed; no configuration type was constructed'
            if isinstance(result, _ConstructionFailure)
            else (
                'State premise decided immediately; candidate type = '
                + format_configuration_type(result)
            )
        )
        self._finish_step(
            step,
            result_text,
            self._premise_summary(expansion),
        )
        return result

    def _solve_system_judgment(
        self,
        judgment: _SystemJudgment,
    ) -> _ConfigurationConstructionResult:
        r"""Solve the system judgment for a process or binary parallel composition."""

        system = judgment.system
        context = judgment.context
        if isinstance(system, Process):
            return self._solve_process_judgment(
                _ProcessJudgment(
                    tuple(self._as_nodes(system)),
                    context,
                    EmptyType(),
                )
            )
        if isinstance(system, Parallel):
            return self._solve_parallel_system_judgment(judgment)
        self._diagnose(
            Verdict.FALSE,
            "Configuration process is not an HCSP Process or Parallel system: "
            f"{system.__class__.__name__}",
            "structural",
            context.location,
        )
        return _CONSTRUCTION_FAILURE

    def _solve_process_judgment(
        self,
        judgment: _ProcessJudgment,
    ) -> _ProcessConstructionResult:
        r"""Expand and solve a sequential process judgment."""

        nodes = judgment.nodes
        context = judgment.context
        if not nodes:
            end_step = self._start_step(
                "T-End",
                context.location,
                'Empty continuation; use termination type 0',
                context=context,
            )
            expansion = self.rule_t_end(judgment)
            result = self._solve_rule_expansion(expansion)
            self._finish_step(
                end_step,
                'Candidate type = ' + format_process_type(result),
                self._premise_summary(expansion),
            )
            return result

        head = nodes[0]

        # ODE; skip can mean no natural successor or an actual empty successor; try both rules
        # in isolation.
        if isinstance(head, ODE) and self._needs_ode_skip_rule_selection(
            judgment
        ):
            return self._solve_ode_skip_rule_candidates(judgment)

        # T-End handles terminal skip; T-Skip handles skip before a successor. Empty nodes mean
        # implicit termination.
        terminal_skip = isinstance(head, Skip) and len(nodes) == 1
        rule = "T-End" if terminal_skip else self._rule_name(head)
        rule_step = self._start_step(
            rule,
            context.location,
            self._describe_process_node(head),
            context=context,
        )


        if isinstance(head, Skip):
            expansion = (
                self.rule_t_end(judgment)
                if terminal_skip
                else self.rule_t_skip(judgment)
            )
        elif isinstance(head, Assert):
            expansion = self.rule_t_assert(judgment)
        elif isinstance(head, Assign):
            expansion = self.rule_t_assign(judgment)
        elif isinstance(head, InputChannel):
            expansion = self.rule_t_in(judgment)
        elif isinstance(head, OutputChannel):
            expansion = self.rule_t_out(judgment)
        elif isinstance(head, If):
            expansion = self.rule_t_if(judgment)
        elif isinstance(head, InternalChoice):
            expansion = self.rule_t_internal_choice(judgment)
        elif isinstance(head, ODE):
            expansion = self.rule_t_ode(judgment)
        elif isinstance(head, Mu):
            expansion = self.rule_t_mu(judgment)
        elif isinstance(head, Var):
            expansion = self.rule_t_x(judgment)
        else:
            self._diagnose(
                Verdict.FALSE,
                "Process is not a node from hcsp_typechecker.data_structures.process_ast.ast: "
                f"{head.__class__.__name__}",
                "structural",
                context.location,
            )
            expansion = _RuleExpansion(
                "structural",
                (),
                lambda _children: _CONSTRUCTION_FAILURE,
            )

        result = self._solve_rule_expansion(expansion)

        if isinstance(result, _ConstructionFailure):
            result_text = 'Derivation failed; no behavioral type was constructed'
        else:
            result_text = 'Candidate type = ' + format_process_type(result)
        self._finish_step(
            rule_step,
            result_text,
            self._premise_summary(expansion)
            + " "
            + self._rule_explanation(rule),
        )
        return result


    def _needs_ode_skip_rule_selection(
        self,
        judgment: _ProcessJudgment,
    ) -> bool:
        r"""Recognize an ODE whose combined continuation is exactly terminal skip."""

        if not judgment.nodes or not isinstance(judgment.nodes[0], ODE):
            return False
        node = judgment.nodes[0]
        tail = tuple(self._as_nodes(node.continuation)) + judgment.nodes[1:]
        return len(tail) == 1 and isinstance(tail[0], Skip)

    def _attempt_ode_candidate(
        self,
        judgment: _ProcessJudgment,
        mode: _ODETypeRule,
    ) -> _ODECandidateAttempt:
        r"""Try one ODE candidate and roll back public evidence before returning."""

        obligation_start = len(self.obligations)
        diagnostic_start = len(self.diagnostics)
        step_start = len(self.steps)
        context = judgment.context
        candidate_step = self._start_step(
            "T-ODE",
            context.location,
            f"Try ODE candidate rule {mode.value}",
            context=context,
        )
        expansion = self.rule_t_ode(judgment, candidate=mode)
        result = self._solve_rule_expansion(expansion)
        self._finish_step(
            candidate_step,
            (
                'The candidate did not produce a type'
                if isinstance(result, _ConstructionFailure)
                else 'Candidate type = ' + format_process_type(result)
            ),
            self._premise_summary(expansion),
        )

        obligations = tuple(self.obligations[obligation_start:])
        diagnostics = tuple(self.diagnostics[diagnostic_start:])
        steps = tuple(self.steps[step_start:])
        del self.obligations[obligation_start:]
        del self.diagnostics[diagnostic_start:]
        del self.steps[step_start:]

        verdict_inputs = [item.verdict for item in obligations]
        verdict_inputs.extend(item.verdict for item in diagnostics)
        if isinstance(result, _ConstructionFailure) and not any(
            item is Verdict.FALSE for item in verdict_inputs
        ):
            verdict_inputs.append(Verdict.FALSE)
        return _ODECandidateAttempt(
            mode=mode,
            result=result,
            verdict=Verdict.combine(verdict_inputs),
            obligations=obligations,
            diagnostics=diagnostics,
            steps=steps,
        )

    @staticmethod
    def _ode_attempts_have_equivalent_types(
        attempts: Sequence[_ODECandidateAttempt],
    ) -> bool:
        r"""Check whether completed ODE candidates yield equivalent behavioral types."""

        if not attempts or isinstance(attempts[0].result, _ConstructionFailure):
            return False
        first = attempts[0].result
        return all(
            not isinstance(attempt.result, _ConstructionFailure)
            and types_equivalent(first, attempt.result)
            for attempt in attempts[1:]
        )

    def _commit_ode_candidate_evidence(
        self,
        attempts: Sequence[_ODECandidateAttempt],
        selected: _ODECandidateAttempt | None,
    ) -> None:
        r"""Retain both attempts' formulas and mark the candidate used in the verdict."""

        for attempt in attempts:
            is_selected = attempt is selected
            self.obligations.extend(
                replace(
                    obligation,
                    active=is_selected,
                    candidate=attempt.mode.value,
                )
                for obligation in attempt.obligations
            )
        if selected is not None:
            self.diagnostics.extend(selected.diagnostics)
            self.steps.extend(selected.steps)

    @staticmethod
    def _ode_attempt_summary(attempt: _ODECandidateAttempt) -> str:
        r"""Summarize candidate evidence for the T-ODE-Select step."""

        proofs = ", ".join(
            f"{item.rule}={item.verdict.value}"
            for item in attempt.obligations
        ) or "no formulas"
        result = (
            "failure"
            if isinstance(attempt.result, _ConstructionFailure)
            else format_process_type(attempt.result)
        )
        return (
            f"{attempt.mode.value}: verdict={attempt.verdict.value}, "
            f"type={result}, proofs=[{proofs}]"
        )

    def _solve_ode_skip_rule_candidates(
        self,
        judgment: _ProcessJudgment,
    ) -> _ProcessConstructionResult:
        r"""Try both timed ODE rules for ODE; skip."""

        context = judgment.context
        selection_step = self._start_step(
            "T-ODE-Select",
            context.location,
            'ODE followed by terminal skip: try both Table 2 rules in isolation',
            context=context,
        )
        attempts = tuple(
            self._attempt_ode_candidate(judgment, mode)
            for mode in (
                _ODETypeRule.COMMUNICATION_ONLY,
                _ODETypeRule.NATURAL_TIMEOUT,
            )
        )
        complete = tuple(
            attempt
            for attempt in attempts
            if not isinstance(attempt.result, _ConstructionFailure)
        )
        proved = tuple(
            attempt
            for attempt in complete
            if attempt.verdict is Verdict.TRUE
        )
        unknown = tuple(
            attempt
            for attempt in complete
            if attempt.verdict is Verdict.UNKNOWN
        )

        selected: _ODECandidateAttempt | None = None
        selection_warning = ""
        if proved:
            if self._ode_attempts_have_equivalent_types(proved):
                selected = proved[0]
                # A proved candidate selects the rule; an unselected UNKNOWN attempt cannot
                # weaken its trust.
            else:
                selection_warning = (
                    "Both ODE rules were proved but generated non-equivalent "
                    "types; this contradicts the expected rule exclusivity"
                )
        elif unknown:
            if self._ode_attempts_have_equivalent_types(unknown):
                selected = unknown[0]
            else:
                # UNKNOWN permits continued construction. Prefer the explicit-skip candidate
                # when neither rule is proved.
                selected = next(
                    (
                        item
                        for item in unknown
                        if item.mode is _ODETypeRule.NATURAL_TIMEOUT
                    ),
                    unknown[0],
                )
                selection_warning = (
                    "ODE rule selection remains unknown and candidate types "
                    "are non-equivalent; the natural-timeout candidate is "
                    "retained provisionally"
                )

        self._commit_ode_candidate_evidence(attempts, selected)
        summaries = "; ".join(
            self._ode_attempt_summary(attempt) for attempt in attempts
        )
        if selection_warning:
            self._diagnose(
                Verdict.UNKNOWN,
                selection_warning,
                "T-ODE-Select",
                context.location,
            )

        if selected is not None:
            self._finish_step(
                selection_step,
                f"Selected {selected.mode.value}: "
                + format_process_type(selected.result),
                summaries,
            )
            return selected.result

        # Keep both attempts' structural diagnostics when no candidate succeeds.
        seen: set[tuple[Verdict, str, str, str]] = set()
        for attempt in attempts:
            for diagnostic in attempt.diagnostics:
                key = (
                    diagnostic.verdict,
                    diagnostic.message,
                    diagnostic.rule,
                    diagnostic.location,
                )
                if key not in seen:
                    self.diagnostics.append(diagnostic)
                    seen.add(key)
        verdict = Verdict.UNKNOWN if complete else Verdict.FALSE
        self._diagnose(
            verdict,
            (
                selection_warning
                or "Neither ODE rule satisfies all of its Table 2 premises"
            ),
            "T-ODE-Select",
            context.location,
        )
        self._finish_step(
            selection_step,
            'The two ODE candidate rules did not yield a unique complete conclusion',
            summaries,
        )
        return _CONSTRUCTION_FAILURE

    def rule_t_end(self, judgment: _ProcessJudgment) -> _RuleExpansion:
        r"""[T-End] Derive type 0 for explicit or implicit terminal skip."""

        return _RuleExpansion(
            "T-End",
            (),
            lambda _children: judgment.terminal,
        )

    def rule_t_skip(
        self,
        judgment: _ProcessJudgment,
    ) -> _RuleExpansion:
        r"""[T-Skip] Continue with the same context and successor judgment."""

        premise = self._process_premise(
            judgment.nodes[1:],
            judgment.context,
            judgment.terminal,
        )
        return _RuleExpansion("T-Skip", (premise,), lambda children: children[0])

    def rule_t_assert(
        self,
        judgment: _ProcessJudgment,
    ) -> _RuleExpansion:
        r"""[T-Assert] Prove phi => B without assuming the assertion afterward."""

        node = judgment.nodes[0]
        context = judgment.context
        premises: list[_Premise] = []
        try:
            condition = self._translator(context).boolean_result(node.condition)
            premises.append(
                self._fol_premise(
                    "T-Assert",
                    f"Assertion holds at {context.location}",
                    implies(context.path, self._defined_term(condition)),
                )
            )
        except ExpressionError as exc:
            self._diagnose(Verdict.FALSE, str(exc), "T-Assert", context.location)
            return _RuleExpansion(
                "T-Assert",
                (),
                lambda _children: _CONSTRUCTION_FAILURE,
            )
        premises.append(
            self._process_premise(
                judgment.nodes[1:],
                context,
                judgment.terminal,
            )
        )
        return _RuleExpansion(
            "T-Assert",
            tuple(premises),
            lambda children: children[0],
        )

    def rule_t_assign(
        self,
        judgment: _ProcessJudgment,
    ) -> _RuleExpansion:
        r"""[T-Assign] Update symbolic state using the Table 2 substitution premise."""

        node = judgment.nodes[0]
        context = judgment.context
        next_context = context.clone()
        post_state: _LazyAssignmentPostState | None = None
        premises: list[_Premise] = []
        try:
            target = lvalue_name(node.target)
            if target in context.parameters:
                raise ExpressionError(
                    f"Assignment target {target!r} is a shared read-only parameter"
                )
            target_declaration = context.gamma.get(target)
            if target_declaration is None:
                raise ExpressionError(f"Assignment target {target!r} is not declared in Gamma")
            if not isinstance(target_declaration, BasicType):
                raise ExpressionError(
                    f"Assignment target {target!r} names an ODE vector declaration, "
                    "not a scalar variable"
                )
            # Evaluate the right-hand side entirely in the pre-assignment state, including
            # self-assignment.
            result = self._translator(context).translate(node.expression)
            expected = target_declaration
            if not is_subtype(result.value_type, expected):
                self._diagnose(
                    Verdict.FALSE,
                    f"Assignment to {target!r} expects {expected}, got {result.value_type}",
                    "T-Assign",
                    context.location,
                )
                return _RuleExpansion(
                    "T-Assign",
                    (),
                    lambda _children: _CONSTRUCTION_FAILURE,
                )
            definedness = self._definedness_premise(
                "T-Assign",
                f"Right-hand side assigned to {target!r} is defined",
                context,
                result,
            )
            if definedness is not None:
                premises.append(definedness)

            post_state = self._lazy_assignment_post_state(
                context,
                target,
                result.term,
            )
            next_context = post_state.post_context
            # Record phi => phi'{e/x} even when the lazy post-state makes it valid by
            # construction; no predicate synthesis occurs.
            premises.append(
                self._fol_premise(
                    "T-Assign-post",
                    (
                        "Table 2 postcondition premise phi => phi'{e/x}; "
                        "phi' is the generated lazy strongest post-state"
                    ),
                    implies(context.path, post_state.pre_path),
                )
            )
        except ExpressionError as exc:
            self._diagnose(Verdict.FALSE, str(exc), "T-Assign", context.location)
            return _RuleExpansion(
                "T-Assign",
                (),
                lambda _children: _CONSTRUCTION_FAILURE,
            )
        premises.append(
            self._process_premise(
                judgment.nodes[1:],
                next_context,
                judgment.terminal,
            )
        )
        return _RuleExpansion(
            "T-Assign",
            tuple(premises),
            lambda children: children[0],
            assignment_post_state=post_state,
        )

    def rule_t_if(
        self,
        judgment: _ProcessJudgment,
    ) -> _RuleExpansion:
        r"""[T-If] Check both branches of a binary conditional."""

        node = judgment.nodes[0]
        tail = tuple(self._as_nodes(node.continuation)) + judgment.nodes[1:]
        context = judgment.context
        then_context = context.clone(location=f"{context.location}.then")
        else_context = context.clone(location=f"{context.location}.else")
        try:
            guard_result = self._translator(context).boolean_result(node.condition)
        except ExpressionError as exc:
            self._diagnose(Verdict.FALSE, str(exc), "T-If", context.location)
            return _RuleExpansion(
                "T-If",
                (),
                lambda _children: _CONSTRUCTION_FAILURE,
            )

        then_context.path = conjunction(context.path, guard_result.term)
        else_context.path = conjunction(context.path, negation(guard_result.term))
        premises: list[_Premise] = []
        definedness = self._definedness_premise(
            "T-If",
            "The branch guard is defined before either branch is selected",
            context,
            guard_result,
        )
        if definedness is not None:
            premises.append(definedness)
        premises.extend((
            self._process_premise(
                tuple(self._as_nodes(node.then_branch)) + tail,
                then_context,
                judgment.terminal,
            ),
            self._process_premise(
                tuple(self._as_nodes(node.else_branch)) + tail,
                else_context,
                judgment.terminal,
            ),
        ))

        def conclude(children: tuple[Any, ...]) -> _ProcessConstructionResult:
            r"""Combine conditional branch types into an internal choice."""

            then_type, else_type = children
            if isinstance(then_type, _ConstructionFailure) or isinstance(
                else_type,
                _ConstructionFailure,
            ):
                return _CONSTRUCTION_FAILURE
            return InternalChoiceType((then_type, else_type))

        return _RuleExpansion("T-If", tuple(premises), conclude)

    def rule_t_in(
        self,
        judgment: _ProcessJudgment,
    ) -> _RuleExpansion:
        r"""[T-In] Extend Gamma slot by slot and assume joint refinement."""

        node = judgment.nodes[0]
        context = judgment.context
        channel = node.channel.name
        channel_type = context.theta.get(channel)
        if channel_type is None:
            self._diagnose(
                Verdict.FALSE,
                f"Input channel {channel!r} is not declared in Theta",
                "T-In",
                context.location,
            )
            return _RuleExpansion("T-In", (), lambda _children: _CONSTRUCTION_FAILURE)

        if len(node.targets) != channel_type.arity:
            self._diagnose(
                Verdict.FALSE,
                f"Input on {channel!r} expects {channel_type.arity} payload "
                f"slots, got {len(node.targets)} targets",
                "T-In",
                context.location,
            )
            return _RuleExpansion("T-In", (), lambda _children: _CONSTRUCTION_FAILURE)

        # Clone the received-value context so sibling branches retain their original state.
        next_context = context.clone()
        try:
            self._fresh_counter += 1
            received_terms: list[Any] = []
            domain_constraints: list[Any] = []
            incompatible_target = False
            for index, (variable, value_type) in enumerate(
                zip(node.targets, channel_type.value_types),
                start=1,
            ):
                name = lvalue_name(variable)
                if name in context.parameters:
                    raise ExpressionError(
                        f"Input target {name!r} is a shared read-only parameter"
                    )
                existing_entry = next_context.gamma.get(name)
                if isinstance(existing_entry, ContinuousType):
                    raise ExpressionError(
                        f"Input target {name!r} names an ODE vector declaration, "
                        "not a scalar variable"
                    )
                existing = (
                    None
                    if existing_entry is None
                    else gamma_value_type(existing_entry)
                )
                # Input requires channel-slot type <: target type; the reverse relation cannot
                # safely store arbitrary payloads.
                if existing is not None and not is_subtype(value_type, existing):
                    self._diagnose(
                        Verdict.FALSE,
                        f"Input target {index} {name!r} has type {existing}, "
                        f"channel slot carries {value_type}",
                        "T-In",
                        context.location,
                    )
                    incompatible_target = True
            if incompatible_target:
                return _RuleExpansion(
                    "T-In",
                    (),
                    lambda _children: _CONSTRUCTION_FAILURE,
                )

            for variable, value_type in zip(
                node.targets,
                channel_type.value_types,
            ):
                name = lvalue_name(variable)
                existing_entry = next_context.gamma.get(name)
                # Input updates scalar entries without changing ODE vector declarations.
                next_context.gamma[name] = (
                    value_type if existing_entry is None else existing_entry
                )

            translator = self._translator(next_context)
            for variable, value_type in zip(
                node.targets,
                channel_type.value_types,
            ):
                name = lvalue_name(variable)
                # One synchronization shares a suffix, while distinct target names retain
                # independent symbols.
                received = translator.fresh_symbol(
                    name,
                    value_type,
                    f"__input{self._fresh_counter}",
                )
                next_context.symbols[name] = received
                received_terms.append(received)
                domain_constraints.extend(
                    self._type_domain_constraints(value_type, received)
                )
            refinement = translator.refinement_result(
                channel_type,
                received_terms,
            )
            next_context.path = conjunction(
                context.path,
                self._defined_term(refinement),
                *domain_constraints,
            )
        except ExpressionError as exc:
            self._diagnose(Verdict.FALSE, str(exc), "T-In", context.location)
            return _RuleExpansion("T-In", (), lambda _children: _CONSTRUCTION_FAILURE)

        premise = self._process_premise(
            judgment.nodes[1:],
            next_context,
            judgment.terminal,
        )

        def conclude(children: tuple[Any, ...]) -> _ProcessConstructionResult:
            r"""Wrap the continuation with an input prefix."""

            continuation = children[0]
            if isinstance(continuation, _ConstructionFailure):
                return _CONSTRUCTION_FAILURE
            # Wrap the angelic input prefix in infinite delay with Bottom as the unreachable
            # timeout.
            return InfiniteDelayType(InputType(channel, continuation))

        return _RuleExpansion("T-In", (premise,), conclude)

    def rule_t_out(
        self,
        judgment: _ProcessJudgment,
    ) -> _RuleExpansion:
        r"""[T-Out] Check payload types and prove instantiated joint refinement."""

        node = judgment.nodes[0]
        context = judgment.context
        channel = node.channel.name
        channel_type = context.theta.get(channel)
        if channel_type is None:
            self._diagnose(
                Verdict.FALSE,
                f"Output channel {channel!r} is not declared in Theta",
                "T-Out",
                context.location,
            )
            return _RuleExpansion("T-Out", (), lambda _children: _CONSTRUCTION_FAILURE)

        if len(node.payloads) != channel_type.arity:
            self._diagnose(
                Verdict.FALSE,
                f"Output on {channel!r} expects {channel_type.arity} payload "
                f"slots, got {len(node.payloads)} expressions",
                "T-Out",
                context.location,
            )
            return _RuleExpansion("T-Out", (), lambda _children: _CONSTRUCTION_FAILURE)

        premises: list[_Premise] = []
        try:
            translator = self._translator(context)
            results = tuple(
                translator.translate(payload)
                for payload in node.payloads
            )
            incompatible_payload = False
            for index, (result, expected) in enumerate(
                zip(results, channel_type.value_types),
                start=1,
            ):
                if not is_subtype(result.value_type, expected):
                    self._diagnose(
                        Verdict.FALSE,
                        f"Output on {channel!r} slot {index} expects {expected}, "
                        f"got {result.value_type}",
                        "T-Out",
                        context.location,
                    )
                    incompatible_payload = True
            if incompatible_payload:
                return _RuleExpansion(
                    "T-Out",
                    (),
                    lambda _children: _CONSTRUCTION_FAILURE,
                )
            refinement = translator.refinement_result(
                channel_type,
                tuple(result.term for result in results),
            )
            well_defined = tuple(
                condition
                for result in results
                for condition in result.definedness
            ) + refinement.definedness
            premises.append(
                self._fol_premise(
                    "T-Out",
                    f"Payloads sent on {channel!r} satisfy their joint refinement",
                    implies(
                        context.path,
                        conjunction(*well_defined, refinement.term),
                    ),
                )
            )
        except ExpressionError as exc:
            self._diagnose(Verdict.FALSE, str(exc), "T-Out", context.location)
            return _RuleExpansion("T-Out", (), lambda _children: _CONSTRUCTION_FAILURE)

        premises.append(
            self._process_premise(
                judgment.nodes[1:],
                context,
                judgment.terminal,
            )
        )

        def conclude(children: tuple[Any, ...]) -> _ProcessConstructionResult:
            r"""Wrap the continuation with an output prefix."""

            continuation = children[0]
            if isinstance(continuation, _ConstructionFailure):
                return _CONSTRUCTION_FAILURE
            # Wrap output symmetrically as a process type, not a bare angelic branch.
            return InfiniteDelayType(OutputType(channel, continuation))

        return _RuleExpansion("T-Out", tuple(premises), conclude)

    def rule_t_internal_choice(
        self,
        judgment: _ProcessJudgment,
    ) -> _RuleExpansion:
        r"""[T-sqcup] Check every internal-choice branch with its continuation."""

        node = judgment.nodes[0]
        # Append both the choice-owned continuation and outer judgment tail to each branch.
        tail = tuple(self._as_nodes(node.continuation)) + judgment.nodes[1:]
        context = judgment.context
        premises = tuple(
            self._process_premise(
                tuple(self._as_nodes(branch)) + tail,
                context.clone(location=f"{context.location}.choice[{index}]"),
                judgment.terminal,
            )
            for index, branch in enumerate(node.branches)
        )

        def conclude(children: tuple[Any, ...]) -> _ProcessConstructionResult:
            r"""Combine branch results into an internal choice."""
            if any(isinstance(child, _ConstructionFailure) for child in children):
                return _CONSTRUCTION_FAILURE
            return InternalChoiceType(children)

        return _RuleExpansion("T-sqcup", premises, conclude)

    def rule_t_external_choice(
        self,
        judgment: _EventJudgment,
    ) -> _RuleExpansion:
        r"""[T-&] Expand communication reactions into child judgments."""

        node = judgment.reaction
        context = judgment.context
        if isinstance(node, EmptyEvent):
            return _RuleExpansion(
                "T-&",
                (),
                lambda _children: NoInterruptType(),
            )
        if not isinstance(node, EventChoice):
            raise TypeError(
                "Event reaction must be EmptyEvent or EventChoice, got "
                f"{type(node).__name__}"
            )

        premises = tuple(
            self._process_premise(
                (communication,)
                + tuple(self._as_nodes(continuation))
                + judgment.tail,
                context.clone(location=f"{context.location}.external[{index}]"),
                judgment.terminal,
            )
            for index, (communication, continuation) in enumerate(node.branches)
        )

        def conclude(children: tuple[Any, ...]) -> AngelicType | _ConstructionFailure:
            r"""Combine communication branches into a canonical angelic type."""
            if any(isinstance(child, _ConstructionFailure) for child in children):
                return _CONSTRUCTION_FAILURE
            # Extract the communication prefix from InfiniteDelayType when composing an angelic
            # event table.
            branches = tuple(
                child.interrupts
                if isinstance(child, InfiniteDelayType)
                and isinstance(child.interrupts, (InputType, OutputType))
                else None
                for child in children
            )
            if any(branch is None for branch in branches):
                self._diagnose(
                    Verdict.FALSE,
                    "External branch did not construct a communication prefix",
                    "T-&",
                    context.location,
                )
                return _CONSTRUCTION_FAILURE
            return make_external_choice(branches)

        return _RuleExpansion("T-&", premises, conclude)

    def _solve_event_judgment(
        self,
        judgment: _EventJudgment,
    ) -> AngelicType | _ConstructionFailure:
        r"""Solve an event judgment and record its premises and result."""

        node = judgment.reaction
        context = judgment.context
        event_step = self._start_step(
            "T-&",
            context.location,
            (
                "empty event reaction"
                if isinstance(node, EmptyEvent)
                else f"Event branch table ({len(node.branches)} communication branches)"
                if isinstance(node, EventChoice)
                else repr(node)
            ),
            context=context,
        )
        expansion = self.rule_t_external_choice(judgment)
        result = self._solve_rule_expansion(expansion)
        if isinstance(result, _ConstructionFailure):
            result_text = 'Derivation failed; the event reaction has no angelic type'
        elif isinstance(node, EmptyEvent):
            result_text = 'Event-choice recursion result = ' + format_angelic_type(result)
        else:
            result_text = 'Event-choice type = ' + format_angelic_type(result)
        self._finish_step(
            event_step,
            result_text,
            self._premise_summary(expansion),
        )
        return result

    # ODE rules and externally discharged dL obligations
    @staticmethod
    def _validate_continuous_vectors(gamma: Mapping[str, GammaType]) -> None:
        r"""Require declared Real scalar members in each continuous vector."""

        for declaration_name, declaration in gamma.items():
            if not isinstance(declaration, ContinuousType):
                continue
            for member in declaration.variables:
                member_declaration = gamma.get(member)
                if member_declaration is None:
                    raise ValueError(
                        f"ODE vector declaration {declaration_name!r} references "
                        f"missing Gamma scalar {member!r}"
                    )
                if member_declaration is not BasicType.REAL:
                    raise ValueError(
                        f"ODE vector declaration {declaration_name!r} requires "
                        f"member {member!r} to have BasicType.REAL, got "
                        f"{member_declaration}"
                    )

    @staticmethod
    def _value_gamma(gamma: Mapping[str, GammaType]) -> dict[str, BasicType]:
        r"""Project Gamma onto entries with scalar values."""

        return {
            name: declaration
            for name, declaration in gamma.items()
            if isinstance(declaration, BasicType)
        }

    @staticmethod
    def _declares_continuous_vector(
        gamma: Mapping[str, GammaType],
        evolved: Sequence[str],
    ) -> bool:
        r"""Check registration of the complete ODE evolution vector."""

        ode_vector = frozenset(evolved)
        return any(
            isinstance(declaration, ContinuousType)
            and frozenset(declaration.variables) == ode_vector
            for declaration in gamma.values()
        )

    def rule_t_ode(
        self,
        judgment: _ProcessJudgment,
        candidate: _ODETypeRule | None = None,
    ) -> _RuleExpansion:
        r"""Expand continuous-evolution rules with safety and delay annotations."""

        node = judgment.nodes[0]
        tail = tuple(self._as_nodes(node.continuation)) + judgment.nodes[1:]
        context = judgment.context
        annotation = node.annotation
        equations = node.eqs

        evolved: list[str] = []
        translator = self._translator(context)
        # A temporary local t shadows Gamma's t for checking; the later dL snapshot remains
        # separate.
        self._fresh_counter += 1
        ode_scope_clock = (
            None
            if z3 is None
            else z3.Real(f"@hcsp_ode_scope_clock_{self._fresh_counter}")
        )
        ode_local_symbols = (
            {}
            if ode_scope_clock is None
            else {node.local_clock.name: ode_scope_clock}
        )
        derivative_definedness: list[Any] = []
        static_type_error = False

        for variable, derivative in equations:
            name = str(variable)
            if name in evolved:
                self._diagnose(
                    Verdict.FALSE,
                    f"Duplicate ODE variable {name!r}",
                    "T-ODE",
                    context.location,
                )
                static_type_error = True
                continue
            evolved.append(name)
            if name in context.parameters:
                self._diagnose(
                    Verdict.FALSE,
                    f"ODE variable {name!r} is a shared read-only parameter",
                    "T-ODE",
                    context.location,
                )
                static_type_error = True
                continue
            gamma_entry = context.gamma.get(name)
            if gamma_entry is None:
                self._diagnose(
                    Verdict.FALSE,
                    f"ODE variable {name!r} is not declared in Gamma",
                    "T-ODE",
                    context.location,
                )
                static_type_error = True
            elif gamma_entry is not BasicType.REAL:
                self._diagnose(
                    Verdict.FALSE,
                    f"ODE variable {name!r} must have BasicType.REAL, "
                    f"got {gamma_entry}",
                    "T-ODE",
                    context.location,
                )
                static_type_error = True
            try:
                derivative_result = translator.translate(
                    derivative,
                    local_symbols=ode_local_symbols,
                )
                if not self._require_numeric_type(
                    derivative_result.value_type,
                    f"derivative of {name}",
                    context,
                ):
                    static_type_error = True
                derivative_definedness.extend(
                    derivative_result.definedness
                )
            except ExpressionError as exc:
                self._diagnose(Verdict.FALSE, str(exc), "T-ODE", context.location)
                static_type_error = True

        if (
            evolved
            and not static_type_error
            and not self._declares_continuous_vector(context.gamma, evolved)
        ):
            self._diagnose(
                Verdict.FALSE,
                "ODE evolution vector "
                f"{tuple(evolved)!r} is not declared by any ContinuousType in Gamma",
                "T-ODE",
                context.location,
            )
            static_type_error = True
        try:
            domain_result = translator.boolean_result(
                node.constraint,
                local_symbols=ode_local_symbols,
            )
            safety_result = translator.boolean_result(
                annotation.safety,
                local_symbols=ode_local_symbols,
            )
            # Preserve definedness conditions by origin: domain, vector field, or safety goal.
            domain = conjunction(
                *derivative_definedness,
                *domain_result.definedness,
                domain_result.term,
            )
            safety = conjunction(
                *derivative_definedness,
                *safety_result.definedness,
                safety_result.term,
            )
        except ExpressionError as exc:
            self._diagnose(Verdict.FALSE, str(exc), "T-ODE", context.location)
            return _RuleExpansion("T-ODE", (), lambda _children: _CONSTRUCTION_FAILURE)

        if static_type_error:
            return _RuleExpansion(
                "T-ODE",
                (),
                lambda _children: _CONSTRUCTION_FAILURE,
            )

        # Infinite delay has no natural-timeout fallback.
        duration_annotation = annotation.delay
        if isinstance(duration_annotation, Literal):
            # Keep the exact duration value in Type ASTs, without expression-layer nodes.
            duration: Any = duration_annotation.value
        else:

            duration = duration_annotation
        infinite_duration = isinstance(duration, float) and duration == inf
        if candidate is _ODETypeRule.NATURAL_TIMEOUT and infinite_duration:
            self._diagnose(
                Verdict.FALSE,
                "The natural-timeout ODE rule requires a finite delay",
                "T-ODE",
                context.location,
            )
            return _RuleExpansion(
                "T-ODE",
                (),
                lambda _children: _CONSTRUCTION_FAILURE,
            )
        # Only isolated ODE; skip selection supplies candidate; finite real tails use the
        # timeout rule.
        communication_rule = (
            candidate is _ODETypeRule.COMMUNICATION_ONLY
            or (candidate is None and infinite_duration)
        )

        # Use an independent entry snapshot to embed substituted state into dL without changing
        # runtime state.
        try:
            dl_terms = self._ode_dl_terms(node, context, evolved)
            dl_term_error: str | None = None
        except (ExpressionError, DLTranslationError) as exc:
            dl_terms = None
            dl_term_error = str(exc)

        # Only trivially true safety and derivative definedness pass locally; Gamma adds no
        # safety property.
        if self._is_true(safety):
            safety_problem: DLFormula | UntranslatedDLFormula = DLFormula(
                "true",
                (),
                (),
                "safety",
            )
        elif dl_terms is None:
            safety_problem = UntranslatedDLFormula(
                "safety",
                dl_term_error or "failed to prepare ODE symbolic terms",
            )
        else:
            safety_problem = self._make_dl_formula(
                "safety",
                safety_formula,
                precondition=dl_terms.precondition,
                equations=dl_terms.equations,
                domain=dl_terms.domain,
                safety=dl_terms.safety,
                duration=dl_terms.duration,
                clock=dl_terms.clock,
                infinite_duration=infinite_duration,
            )
        premises: list[_Premise] = [
            self._dl_premise(
                "T-ODE-safety",
                "The ODE preserves its annotated safety until delay d",
                safety_problem,
                automatically_true=self._is_true(safety),
            )
        ]

        # Prove domain preservation in the unrestricted dynamics. Assuming B inside the ODE
        # would weaken the obligation.
        if communication_rule:

            domain_is_trivially_true = self._is_true(domain)
            if domain_is_trivially_true:
                domain_problem: DLFormula | UntranslatedDLFormula = DLFormula(
                    "true",
                    (),
                    (),
                    "domain",
                )
            elif dl_terms is None:
                domain_problem = UntranslatedDLFormula(
                    "domain",
                    dl_term_error or "failed to prepare ODE symbolic terms",
                )
            else:
                domain_problem = self._make_dl_formula(
                    "domain",
                    domain_formula,
                    precondition=dl_terms.precondition,
                    equations=dl_terms.equations,
                    domain=dl_terms.domain,
                    domain_definedness=dl_terms.domain_definedness,
                )
            premises.append(
                self._dl_premise(
                    "T-ODE-domain",
                    "The ODE remains in its domain until an interrupt is taken",
                    domain_problem,
                    automatically_true=domain_is_trivially_true,
                )
            )

        # Require the exact boundary premise only for finite delay with a natural successor.
        if not communication_rule:
            if dl_terms is None:
                boundary_problem: DLFormula | UntranslatedDLFormula = (
                    UntranslatedDLFormula(
                        "boundary",
                        dl_term_error or "failed to prepare ODE symbolic terms",
                    )
                )
            else:
                boundary_problem = self._make_dl_formula(
                    "boundary",
                    boundary_formula,
                    precondition=dl_terms.precondition,
                    equations=dl_terms.equations,
                    domain=dl_terms.domain,
                    domain_definedness=dl_terms.domain_definedness,
                    duration=dl_terms.duration,
                    clock=dl_terms.clock,
                )
            premises.append(
                self._dl_premise(
                    "T-ODE-boundary",
                    "Before delay d the ODE remains in B, and at d it satisfies not B",
                    boundary_problem,
                )
            )

        if communication_rule:
            # Do not append placeholder skip to event tails; genuine infinite-ODE tails still
            # follow interrupts.
            event_tail = (
                ()
                if candidate is _ODETypeRule.COMMUNICATION_ONLY
                and len(tail) == 1
                and isinstance(tail[0], Skip)
                else tail
            )
            interrupt_context = self._ode_post_context(
                node,
                context,
                evolved,
                assumption=_ODEPostAssumption.DOMAIN_AND_SAFETY,
            )
            if interrupt_context is None:
                return _RuleExpansion(
                    "T-ODE",
                    (),
                    lambda _children: _CONSTRUCTION_FAILURE,
                )
            premises.append(
                self._event_premise(
                    node.interrupts,
                    event_tail,
                    interrupt_context,
                    judgment.terminal,
                )
            )

            def conclude_without_timeout(
                children: tuple[Any, ...],
            ) -> _ProcessConstructionResult:
                r"""Combine communication reactions with an unreachable deadline continuation."""

                choices = children[0]
                if isinstance(choices, _ConstructionFailure):
                    return _CONSTRUCTION_FAILURE
                # The communication-only rule has no reachable deadline successor. Bottom cannot
                # be replaced by EmptyType.
                return make_delay_type(duration, choices, BottomType())

            return _RuleExpansion(
                "T-ODE",
                tuple(premises),
                conclude_without_timeout,
            )

        # Use the tail as the timeout fallback and append it to each interrupt continuation.
        fallback_context = self._ode_post_context(
            node,
            context,
            evolved,
            assumption=_ODEPostAssumption.NOT_DOMAIN_AND_SAFETY,
        )
        if fallback_context is None:
            return _RuleExpansion(
                "T-ODE",
                (),
                lambda _children: _CONSTRUCTION_FAILURE,
            )
        # Interrupts use safety; natural termination uses not B and safety, as specified by
        # Table 2.
        interrupt_context = self._ode_post_context(
            node,
            context,
            evolved,
            assumption=_ODEPostAssumption.SAFETY,
        )
        if interrupt_context is None:
            return _RuleExpansion(
                "T-ODE",
                (),
                lambda _children: _CONSTRUCTION_FAILURE,
            )
        premises.extend(
            (
                self._event_premise(
                    node.interrupts,
                    tail,
                    interrupt_context,
                    judgment.terminal,
                ),
                self._process_premise(
                    tail,
                    fallback_context,
                    judgment.terminal,
                ),
            )
        )

        def conclude_with_timeout(
            children: tuple[Any, ...],
        ) -> _ProcessConstructionResult:
            r"""Combine communication interrupts and the finite-timeout continuation."""

            choices, fallback = children
            if isinstance(choices, _ConstructionFailure) or isinstance(
                fallback,
                _ConstructionFailure,
            ):
                return _CONSTRUCTION_FAILURE
            return make_delay_type(duration, choices, fallback)

        return _RuleExpansion("T-ODE", tuple(premises), conclude_with_timeout)

    def _ode_dl_terms(
        self,
        node: ODE,
        context: _Context,
        evolved: Sequence[str],
    ) -> _ODEDLTerms:
        r"""Snapshot entry-state symbols for ODE modalities."""

        self._fresh_counter += 1
        ode_symbols = dict(context.symbols)
        value_gamma = self._value_gamma(context.gamma)
        value_environment = {**context.parameters, **value_gamma}
        snapshot_translator = ExpressionTranslator(
            value_environment,
            ode_symbols,
        )
        equalities: list[Any] = []


        for name in dict.fromkeys(evolved):
            if name not in value_gamma:
                raise DLTranslationError(
                    f"cannot build dL formula for undeclared ODE variable {name!r}"
                )
            if value_gamma[name] is not BasicType.REAL:
                raise DLTranslationError(
                    f"dL ODE variable {name!r} is not declared as BasicType.REAL"
                )
            old_value = ode_symbols.get(name)
            if old_value is None:
                old_value = snapshot_translator.symbol(name, value_gamma[name])
            fresh_value = snapshot_translator.fresh_symbol(
                name,
                value_gamma[name],
                f"__dlentry{self._fresh_counter}",
            )
            ode_symbols[name] = fresh_value
            equalities.append(fresh_value == old_value)

        if z3 is None:
            raise DLTranslationError("z3-solver is required to materialize ODE clocks")
        # Internal @ names cannot be captured by ASCII user identifiers; suffixes isolate ODE
        # instances.
        clock = z3.Real(f"@hcsp_ode_clock_{self._fresh_counter}")
        clock_initial = snapshot_translator.translate(
            node.local_clock.initial_value
        ).term
        equalities.append(clock == clock_initial)
        ode_local_symbols = {node.local_clock.name: clock}

        precondition = conjunction(context.path, *equalities)
        translator = ExpressionTranslator(value_environment, ode_symbols)
        translated_equations: list[tuple[Any, Any]] = []
        derivative_definedness: list[Any] = []
        for variable, derivative in node.eqs:
            name = str(variable)

            if (
                name not in ode_symbols
                or value_gamma.get(name) is not BasicType.REAL
            ):
                raise DLTranslationError(
                    f"cannot materialize dL equation for {name!r}"
                )
            derivative_result = translator.translate(
                derivative,
                local_symbols=ode_local_symbols,
            )
            derivative_definedness.extend(
                derivative_result.definedness
            )
            translated_equations.append(
                (ode_symbols[name], derivative_result.term)
            )

        clock_derivative = translator.translate(
            node.local_clock.derivative
        ).term
        translated_equations.append((clock, clock_derivative))

        domain_result = translator.boolean_result(
            node.constraint,
            local_symbols=ode_local_symbols,
        )
        domain = domain_result.term
        domain_definedness = conjunction(
            *derivative_definedness,
            *domain_result.definedness,
        )
        safety_result = translator.boolean_result(
            node.annotation.safety,
            local_symbols=ode_local_symbols,
        )
        safety = conjunction(
            domain_definedness,
            *safety_result.definedness,
            safety_result.term,
        )
        delay = node.annotation.delay
        if isinstance(delay, float) and delay == inf:
            duration_term = None
        else:
            duration_result = translator.translate(delay)
            if duration_result.definedness:
                raise DLTranslationError(
                    "finite ODE delay must be an everywhere-defined rational"
                )
            duration_term = duration_result.term
        return _ODEDLTerms(
            precondition,
            tuple(translated_equations),
            domain,
            domain_definedness,
            safety,
            duration_term,
            clock,
        )

    @staticmethod
    def _make_dl_formula(
        role: str,
        builder: Any,
        **arguments: Any,
    ) -> DLFormula | UntranslatedDLFormula:
        r"""Record unsupported dL translation conservatively as UNKNOWN."""

        try:
            return builder(**arguments)
        except DLTranslationError as exc:
            return UntranslatedDLFormula(role, str(exc))

    def _ode_post_context(
        self,
        node: ODE,
        context: _Context,
        evolved: Sequence[str],
        *,
        assumption: _ODEPostAssumption,
    ) -> _Context | None:
        r"""Create fresh symbolic state and path facts after ODE termination or interruption."""
        post = context.clone()
        self._fresh_counter += 1
        translator = self._translator(post)
        # The shared fresh suffix identifies one ODE post-state snapshot.
        for name in evolved:
            if name in post.gamma:
                post.symbols[name] = translator.fresh_symbol(
                    name,
                    post.gamma[name],
                    f"__ode{self._fresh_counter}",
                )
        translator = self._translator(post)
        try:
            uses_local_clock = (
                node.local_clock.name in node.annotation.safety.get_vars()
                or (
                    assumption != _ODEPostAssumption.SAFETY
                    and (
                        node.local_clock.name in node.constraint.get_vars()
                    )
                )
            )
            local_symbols: dict[str, Any] = {}
            post_clock = None
            if uses_local_clock:
                if z3 is None:
                    raise ExpressionError(
                        "z3-solver is required to eliminate the ODE local clock"
                    )
                post_clock = z3.Real(
                    f"@hcsp_ode_post_clock_{self._fresh_counter}"
                )
                local_symbols[node.local_clock.name] = post_clock
            safety_result = translator.boolean_result(
                node.annotation.safety,
                local_symbols=local_symbols,
            )
            safety = self._defined_term(safety_result)
            if assumption != _ODEPostAssumption.SAFETY:
                domain_result = translator.boolean_result(
                    node.constraint,
                    local_symbols=local_symbols,
                )
                domain_term = domain_result.term
                domain_definedness = list(domain_result.definedness)
                if assumption == _ODEPostAssumption.DOMAIN_AND_SAFETY:
                    domain_condition = conjunction(
                        *domain_definedness,
                        domain_term,
                    )
                else:
                    domain_condition = conjunction(
                        *domain_definedness,
                        negation(domain_term),
                    )
                condition = conjunction(domain_condition, safety)
            else:
                condition = safety
            # Successors retain Gamma and parameters, but only intrinsic type constraints and
            # rule-specific path facts.
            environment_condition = conjunction(
                context.parameter_condition,
                *(
                    constraint
                    for name, value_type in self._value_gamma(post.gamma).items()
                    for constraint in self._type_domain_constraints(
                        value_type,
                        post.symbols[name],
                    )
                ),
            )
            if post_clock is not None:
                condition = conjunction(post_clock >= 0, condition)
                post.path = conjunction(
                    environment_condition,
                    z3.Exists([post_clock], condition),
                )
            else:
                post.path = conjunction(environment_condition, condition)
        except ExpressionError as exc:
            self._diagnose(Verdict.FALSE, str(exc), "T-ODE", context.location)
            return None
        return post

    # Recursive rules
    def rule_t_mu(
        self,
        judgment: _ProcessJudgment,
    ) -> _RuleExpansion:
        r"""[T-mu] Introduce a boundary invariant and solve the recursive type equation."""

        node = judgment.nodes[0]
        tail = self._observable_recursion_tail(judgment.nodes[1:])
        context = judgment.context
        if tail:
            self._diagnose(
                Verdict.UNKNOWN,
                "Sequential continuation after a recursive process is outside "
                "the guarded tail-recursive fragment implemented here",
                "T-mu",
                context.location,
            )
            return _RuleExpansion(
                "T-mu",
                (),
                lambda _children: _CONSTRUCTION_FAILURE,
            )

        source_name = node.variable
        body = node.body
        # The boundary invariant comes only from the binding RecursionAnnotation.
        invariant = node.annotation.invariant

        premises: list[_Premise] = []
        try:
            invariant_at_entry = self._translator(context).boolean_result(
                invariant
            )
            premises.append(
                self._fol_premise(
                    "T-mu",
                    f"Entry path entails recursion invariant for {source_name}",
                    implies(
                        context.path,
                        self._defined_term(invariant_at_entry),
                    ),
                )
            )
        except ExpressionError as exc:
            self._diagnose(Verdict.FALSE, str(exc), "T-mu", context.location)
            return _RuleExpansion(
                "T-mu",
                (),
                lambda _children: _CONSTRUCTION_FAILURE,
            )

        # Use separate source and type variable names to keep alpha equivalence independent of
        # source spelling.
        self._type_var_counter += 1
        type_var = TypeVar(f"t{self._type_var_counter}")
        binding = _RecBinding(source_name, type_var, invariant)
        body_context = self._fresh_recursion_context(context, binding)
        if body_context is None:
            return _RuleExpansion(
                "T-mu",
                (),
                lambda _children: _CONSTRUCTION_FAILURE,
            )
        premises.append(
            self._process_premise(
                tuple(self._as_nodes(body)),
                body_context,
                EmptyType(),
            )
        )

        def conclude(children: tuple[Any, ...]) -> _ProcessConstructionResult:
            r"""Add MuType only when the body references the guarded recursion variable."""

            body_type = children[0]
            if isinstance(body_type, _ConstructionFailure):
                return _CONSTRUCTION_FAILURE
            if self._contains_type_var(body_type, type_var.name):
                if not self._guarded(body_type, type_var.name):
                    self._diagnose(
                        Verdict.FALSE,
                        f"Recursive type variable {type_var.name} is not communication-guarded",
                        "T-mu",
                        context.location,
                    )
                    return _CONSTRUCTION_FAILURE
                return MuType(type_var.name, body_type)
            return body_type

        return _RuleExpansion("T-mu", tuple(premises), conclude)

    def rule_t_x(
        self,
        judgment: _ProcessJudgment,
    ) -> _RuleExpansion:
        r"""[T-X] Check the recursion invariant and tail-position restriction."""

        node = judgment.nodes[0]
        tail = self._observable_recursion_tail(judgment.nodes[1:])
        context = judgment.context
        name = node.name
        binding = context.rec_env.get(name)
        if binding is None:
            self._diagnose(
                Verdict.FALSE,
                f"Unbound process variable {name!r}",
                "T-X",
                context.location,
            )
            return _RuleExpansion("T-X", (), lambda _children: _CONSTRUCTION_FAILURE)
        if tail:
            self._diagnose(
                Verdict.FALSE,
                f"Recursive call {name!r} must be in tail position",
                "T-X",
                context.location,
            )
            return _RuleExpansion(
                "T-X",
                (),
                lambda _children: _CONSTRUCTION_FAILURE,
            )
        premise = self._recursion_boundary_premise(binding, context)
        if premise is None:
            return _RuleExpansion(
                "T-X",
                (),
                lambda _children: _CONSTRUCTION_FAILURE,
            )
        premises = (premise,)
        return _RuleExpansion(
            "T-X",
            premises,
            lambda _children: binding.type_var,
        )

    def _recursion_boundary_premise(
        self,
        binding: _RecBinding,
        context: _Context,
    ) -> _FormulaPremise | None:
        r"""Build a recursion-boundary premise; return None for invalid expressions."""
        try:
            invariant = self._translator(context).boolean_result(
                binding.invariant
            )
            return self._fol_premise(
                "T-X",
                f"Recursive body re-establishes invariant for {binding.source_name}",
                implies(context.path, self._defined_term(invariant)),
            )
        except ExpressionError as exc:
            self._diagnose(Verdict.FALSE, str(exc), "T-X", context.location)
            return None

    # Helpers
    @staticmethod
    def _observable_recursion_tail(
        tail: Sequence[Process],
    ) -> tuple[Process, ...]:
        r"""Remove behavior-free skips following a recursion call."""

        return tuple(node for node in tail if not isinstance(node, Skip))

    @staticmethod
    def _lazy_assignment_post_state(
        context: _Context,
        target: str,
        assigned_term: Any,
    ) -> _LazyAssignmentPostState:
        r"""Compute a lazy strongest post-state without predicate synthesis."""

        if target not in context.symbols:

            raise ExpressionError(
                f"Assignment target {target!r} has no symbol in the current state"
            )
        post_context = context.clone()
        previous_term = context.symbols[target]
        post_context.symbols[target] = assigned_term
        return _LazyAssignmentPostState(
            target=target,
            previous_term=previous_term,
            assigned_term=assigned_term,
            pre_path=context.path,
            post_context=post_context,
        )

    def _initial_context(
        self,
        gamma: Mapping[str, GammaType],
        parameters: Mapping[str, BasicType],
        parameter_symbols: Mapping[str, Any],
        parameter_condition: Any,
        theta: dict[str, ChannelType],
        path_condition: Any,
        location: str,
    ) -> _Context:
        r"""Create initial symbols, path conditions, and intrinsic type constraints."""
        symbols: dict[str, Any] = dict(parameter_symbols)
        value_gamma = self._value_gamma(gamma)
        value_environment = {**parameters, **value_gamma}
        translator = ExpressionTranslator(
            value_environment,
            symbols,
            name_prefix=f"{location}__",
        )
        static_valid = True
        for name, value_type in value_gamma.items():
            try:
                translator.symbol(name, value_type)
            except ExpressionError as exc:
                self._diagnose(Verdict.FALSE, str(exc), "environment", location)
                static_valid = False
        if not static_valid:
            configuration_path = z3.BoolVal(False) if z3 is not None else False
            path = configuration_path
        else:
            try:
                path_result = translator.boolean_result(path_condition)
                configuration_path = conjunction(
                    self._defined_term(path_result),
                    *(
                        constraint
                        for name, value_type in value_gamma.items()
                        for constraint in self._type_domain_constraints(
                            value_type,
                            symbols[name],
                        )
                    ),
                )
                path = conjunction(parameter_condition, configuration_path)
            except ExpressionError as exc:
                self._diagnose(Verdict.FALSE, str(exc), "environment", location)
                configuration_path = z3.BoolVal(False) if z3 is not None else False
                path = z3.BoolVal(False) if z3 is not None else False
                static_valid = False
        return _Context(
            gamma=dict(gamma),
            parameters=dict(parameters),
            parameter_condition=parameter_condition,
            configuration_path=configuration_path,
            theta=theta,
            path=path,
            symbols=symbols,
            rec_env={},
            location=location,
            static_valid=static_valid,
        )

    def _fresh_recursion_context(
        self,
        context: _Context,
        binding: _RecBinding,
    ) -> _Context | None:
        r"""Abstract the recursion-entry state using its invariant."""
        self._fresh_counter += 1
        symbols: dict[str, Any] = {
            name: context.symbols[name] for name in context.parameters
        }
        value_gamma = self._value_gamma(context.gamma)
        value_environment = {**context.parameters, **value_gamma}
        translator = ExpressionTranslator(
            value_environment,
            symbols,
            name_prefix=f"{context.location}__rec{self._fresh_counter}__",
        )
        for name, value_type in value_gamma.items():
            translator.symbol(name, value_type)
        try:
            path_result = translator.boolean_result(binding.invariant)
            path = conjunction(
                context.parameter_condition,
                self._defined_term(path_result),
                *(
                    constraint
                    for name, value_type in value_gamma.items()
                    for constraint in self._type_domain_constraints(
                        value_type,
                        symbols[name],
                    )
                ),
            )
        except ExpressionError as exc:
            self._diagnose(Verdict.FALSE, str(exc), "T-mu", context.location)
            return None
        rec_env = dict(context.rec_env)
        rec_env[binding.source_name] = binding
        return _Context(
            gamma=dict(context.gamma),
            parameters=dict(context.parameters),
            parameter_condition=context.parameter_condition,
            configuration_path=self._defined_term(path_result),
            theta=context.theta,
            path=path,
            symbols=symbols,
            rec_env=rec_env,
            location=f"{context.location}.{binding.source_name}",
            static_valid=context.static_valid,
        )

    def rule_t_parallel_system(
        self,
        judgment: _SystemJudgment,
    ) -> _RuleExpansion:
        r"""Expand binary Parallel into left and right system judgments."""

        node = judgment.system
        context = judgment.context
        if context.gamma or not self._is_true(context.path):
            # Retain this local guard so new dispatch paths cannot treat stateful systems as
            # stateless shorthand.
            self._diagnose(
                Verdict.FALSE,
                "Internal Parallel sugar requires an empty Gamma and true path",
                "T-||",
                context.location,
            )
            return _RuleExpansion(
                "T-||",
                (),
                lambda _children: _CONSTRUCTION_FAILURE,
            )
        overlap = self._process_vars(node.left) & self._process_vars(node.right)
        if overlap:
            self._diagnose(
                Verdict.FALSE,
                "Parallel system components share variables: "
                + ", ".join(sorted(overlap)),
                "T-||",
                context.location,
            )
            return _RuleExpansion(
                "T-||",
                (),
                lambda _children: _CONSTRUCTION_FAILURE,
            )

        left_context = context.clone(location=f"{context.location}.parallel.left")
        right_context = context.clone(location=f"{context.location}.parallel.right")
        premises = (
            _ChildJudgmentPremise(_SystemJudgment(node.left, left_context)),
            _ChildJudgmentPremise(_SystemJudgment(node.right, right_context)),
        )

        def conclude(children: tuple[Any, ...]) -> _ConfigurationConstructionResult:
            r"""Combine left and right results into ParallelType."""

            left_type, right_type = children
            if isinstance(left_type, _ConstructionFailure) or isinstance(
                right_type,
                _ConstructionFailure,
            ):
                return _CONSTRUCTION_FAILURE
            return ParallelType((left_type, right_type))

        return _RuleExpansion("T-||", premises, conclude)

    def _solve_parallel_system_judgment(
        self,
        judgment: _SystemJudgment,
    ) -> _ConfigurationConstructionResult:
        r"""Solve parallel system premises and record their composition."""

        context = judgment.context
        parallel_step = self._start_step(
            "T-||",
            context.location,
            "Derive the binary system composition S || S'",
            context=context,
        )
        expansion = self.rule_t_parallel_system(judgment)
        result = self._solve_rule_expansion(expansion)
        result_text = (
            'Derivation failed; a parallel system branch has no configuration type'
            if isinstance(result, _ConstructionFailure)
            else 'Parallel configuration type = ' + format_configuration_type(result)
        )
        self._finish_step(
            parallel_step,
            result_text,
            self._premise_summary(expansion),
        )
        return result

    def _translator(self, context: _Context) -> ExpressionTranslator:
        r"""Create an expression translator using the branch's symbol table."""
        return ExpressionTranslator(
            {**context.parameters, **self._value_gamma(context.gamma)},
            context.symbols,
        )

    def _validate_theta_refinements(
        self,
        gamma: Mapping[str, GammaType],
        theta: Mapping[str, ChannelType],
        parameters: Mapping[str, BasicType],
    ) -> None:
        r"""Validate all Theta refinements as well-formed Boolean formulas."""

        translator = ExpressionTranslator(
            {**parameters, **self._value_gamma(gamma)},
            name_prefix="theta__",
        )
        for channel_name, channel_type in theta.items():
            values = tuple(
                translator.fresh_symbol(
                    f"{channel_name}_{binder}",
                    value_type,
                    "__refinement",
                )
                for binder, value_type in zip(
                    channel_type.binders,
                    channel_type.value_types,
                )
            )
            try:
                translator.refinement_result(channel_type, values)
            except ExpressionError as exc:
                raise ExpressionError(
                    f"Theta channel {channel_name!r} has an invalid refinement: {exc}"
                ) from exc

    @staticmethod
    def _defined_term(result: ExprResult) -> Any:
        r"""Combine an expression value with its definedness conditions."""

        return conjunction(*result.definedness, result.term)

    def _definedness_premise(
        self,
        rule: str,
        description: str,
        context: _Context,
        result: ExprResult,
    ) -> _FormulaPremise | None:
        r"""Generate explicit definedness premises under the current path condition."""

        if not result.definedness:
            return None
        condition = simplify(conjunction(*result.definedness))
        if self._is_true(condition):
            return None
        return self._fol_premise(
            rule,
            description,
            implies(context.path, condition),
        )

    @staticmethod
    def _display_term(value: Any) -> str:
        r"""Simplify Z3 terms and display other values safely."""

        try:
            return str(simplify(value))
        except Exception:
            return str(value)

    def _start_step(
        self,
        rule: str,
        location: str,
        subject: str,
        *,
        context: _Context | None = None,
        gamma: Mapping[str, GammaType] | None = None,
        parameters: Mapping[str, BasicType] | None = None,
        parameter_constraint: Any = None,
        theta: Mapping[str, ChannelType] | None = None,
        path: Any = None,
        symbols: Mapping[str, Any] | None = None,
    ) -> int:
        r"""Record a preorder environment snapshot and reserve the rule-result slot."""

        active_gamma = context.gamma if context is not None else (gamma or {})
        active_parameters = (
            context.parameters if context is not None else (parameters or {})
        )
        active_parameter_constraint = (
            context.parameter_condition
            if context is not None
            else parameter_constraint
        )
        active_theta = context.theta if context is not None else (theta or {})
        active_path = context.path if context is not None else path
        active_symbols = context.symbols if context is not None else (symbols or {})
        step = DerivationStep(
            number=len(self.steps) + 1,
            rule=rule,
            location=location,
            subject=subject,
            gamma=tuple(
                (name, str(value_type))
                for name, value_type in sorted(active_gamma.items())
            ),
            parameters=tuple(
                (name, str(value_type))
                for name, value_type in sorted(active_parameters.items())
            ),
            parameter_constraint=(
                ""
                if active_parameter_constraint is None
                else self._display_term(active_parameter_constraint)
            ),
            theta=tuple(
                (name, str(channel_type))
                for name, channel_type in sorted(active_theta.items())
            ),
            path_condition=(
                "" if active_path is None else self._display_term(active_path)
            ),
            symbolic_state=tuple(
                (name, self._display_term(term))
                for name, term in sorted(active_symbols.items())
                if name not in active_parameters
            ),
        )
        self.steps.append(step)
        return len(self.steps) - 1

    def _finish_step(self, index: int, result: str, detail: str = "") -> None:
        r"""Complete a step without changing its identifier or snapshot."""

        self.steps[index] = self.steps[index].completed(result, detail)

    @staticmethod
    def _rule_name(node: Any) -> str:
        r"""Select the Table 2 rule name for a process node."""

        if isinstance(node, Skip):
            return "T-Skip"
        if isinstance(node, Assert):
            return "T-Assert"
        if isinstance(node, Assign):
            return "T-Assign"
        if isinstance(node, InputChannel):
            return "T-In"
        if isinstance(node, OutputChannel):
            return "T-Out"
        if isinstance(node, If):
            return "T-If"
        if isinstance(node, InternalChoice):
            return "T-sqcup"
        if isinstance(node, ODE):
            return "T-ODE"
        if isinstance(node, Mu):
            return "T-mu"
        if isinstance(node, Var):
            return "T-X"
        return "structural"

    @staticmethod
    def _describe_process_node(node: Any) -> str:
        r"""Describe an AST node using concise paper-like syntax."""

        if isinstance(node, Skip):
            return "skip"
        if isinstance(node, Assert):
            return f"assert({node.condition})"
        if isinstance(node, Assign):
            return f"{node.target} := {node.expression}"
        if isinstance(node, InputChannel):
            targets = ", ".join(str(target) for target in node.targets)
            return f"{node.channel}?({targets})"
        if isinstance(node, OutputChannel):
            payloads = ", ".join(str(payload) for payload in node.payloads)
            return f"{node.channel}!({payloads})"
        if isinstance(node, If):
            return f"if {node.condition} then P else P'"
        if isinstance(node, InternalChoice):
            return "(P \\sqcup P'); Q"
        if isinstance(node, ODE):
            equations = ", ".join(
                f"{name}'={derivative}" for name, derivative in node.eqs
            ) or "(only local t'=1)"
            return (
                f"<{equations} & {node.constraint}> "
                f"[safety={node.annotation.safety}, delay={node.annotation.delay}]"
            )
        if isinstance(node, Mu):
            return f"mu {node.variable} [invariant={node.annotation.invariant}].P"
        if isinstance(node, Var):
            return node.name
        return repr(node)

    @staticmethod
    def _rule_explanation(rule: str) -> str:
        r"""Explain the rule without conflating derivation with proof success."""

        explanations = {
            (
                'T-Skip'
            ): (
                'skip preserves Gamma, the path condition, and symbolic state; check the '
                'continuation.'
            ),
            (
                'T-Assert'
            ): (
                'Generate an FOL obligation that the path condition implies the assertion; '
                'assert is not assume.'
            ),
            "T-Assign": (
                (
                    'Construct a lazy strongest post-state deterministically using phi -> '
                    "phi'{e/x}; the prover does not synthesize an unknown phi'."
                )
            ),
            (
                'T-In'
            ): (
                'Read slot types from Theta, bind fresh received values, and assume the '
                'refinement.'
            ),
            (
                'T-Out'
            ): (
                'Check each output expression type and prove that the actual payload '
                'satisfies the refinement.'
            ),
            "T-If": 'Check the two branches under phi and B, and phi and not B.',
            "T-sqcup": (
                (
                    'Pass the shared continuation to every internal-choice child judgment, '
                    'then combine their complete branch types.'
                )
            ),
            "T-ODE": (
                (
                    'Check that Gamma registers the complete ODE vector; use node safety '
                    'to generate safety, domain, and boundary dL obligations.'
                )
            ),
            "T-mu": 'Bind a recursive type variable and boundary invariant, then check the body.',
            "T-X": 'Check the invariant on the recursive back edge and return the type variable.',
            "structural": 'The object is not a supported HCSP process node.',
        }
        return explanations.get(rule, "")

    @staticmethod
    def _process_premise(
        nodes: Sequence[Process],
        context: _Context,
        terminal: ProcessType,
    ) -> _ChildJudgmentPremise:
        r"""Create a process premise without solving it."""

        return _ChildJudgmentPremise(
            _ProcessJudgment(tuple(nodes), context, terminal)
        )

    @staticmethod
    def _event_premise(
        reaction: EventReaction,
        tail: Sequence[Process],
        context: _Context,
        terminal: ProcessType,
    ) -> _ChildJudgmentPremise:
        r"""Create an event premise without solving it."""

        interrupt_context = context.clone(
            location=f"{context.location}.interrupt"
        )
        return _ChildJudgmentPremise(
            _EventJudgment(
                reaction,
                tuple(tail),
                interrupt_context,
                terminal,
            )
        )

    @staticmethod
    def _state_premise(
        rule: str,
        description: str,
        formula: Any,
        state: Mapping[str, Any],
        symbols: Mapping[str, Any],
    ) -> _FormulaPremise:
        r"""Create an ordered phi[sigma] validity premise."""

        return _FormulaPremise(
            _ProofRequest(
                ProofObligation(
                    rule=rule,
                    description=description,
                    formula=formula,
                    kind="state",
                ),
                state=dict(state),
                symbols=dict(symbols),
            )
        )

    @staticmethod
    def _fol_premise(
        rule: str,
        description: str,
        formula: Any,
    ) -> _FormulaPremise:
        r"""Create an ordered first-order logic premise."""

        return _FormulaPremise(
            _ProofRequest(
                ProofObligation(
                    rule=rule,
                    description=description,
                    formula=formula,
                    kind="fol",
                )
            )
        )

    @staticmethod
    def _dl_premise(
        rule: str,
        description: str,
        formula: Any,
        *,
        automatically_true: bool = False,
    ) -> _FormulaPremise:
        r"""Create an ordered differential dynamic logic premise."""

        return _FormulaPremise(
            _ProofRequest(
                ProofObligation(
                    rule=rule,
                    description=description,
                    formula=formula,
                    kind="dl",
                ),
                automatically_true=automatically_true,
            )
        )

    @staticmethod
    def _premise_summary(expansion: _RuleExpansion) -> str:
        r"""Render explicit premises as a compact derivation-tree summary."""

        descriptions: list[str] = []
        for premise in expansion.premises:
            if isinstance(premise, _FormulaPremise):
                obligation = premise.request.obligation
                descriptions.append(
                    f"formula[{obligation.kind}:{obligation.rule}]"
                )
                continue
            child = premise.judgment
            if isinstance(child, _ConfigurationJudgment):
                descriptions.append(f"configuration[{child.context.location}]")
            elif isinstance(child, _SystemJudgment):
                descriptions.append(f"system[{child.context.location}]")
            elif isinstance(child, _ProcessJudgment):
                subject = (
                    "T-End"
                    if not child.nodes
                    else Table2RuleEngine._describe_process_node(child.nodes[0])
                )
                descriptions.append(f"process[{subject}]@{child.context.location}")
            elif isinstance(child, _EventJudgment):
                descriptions.append(f"event[E]@{child.context.location}")
        summary = (
            "Premises: " + ", ".join(descriptions) + "."
            if descriptions
            else "Premises: (none)."
        )
        post_state = expansion.assignment_post_state
        if post_state is None:
            return summary
        target = post_state.target
        return (
            summary
            + ' Lazy strongest post-state: '
            + (
                f"Before assignment {target}="
                f"{Table2RuleEngine._display_term(post_state.previous_term)}; "
            )
            + f"Right-hand side={Table2RuleEngine._display_term(post_state.assigned_term)}; "
            + f"Post-assignment symbols[{target}]="
            + f"{Table2RuleEngine._display_term(post_state.post_context.symbols[target])}; "
            + "phi' is determined by the symbolic mapping; predicate synthesis is unnecessary."
        )

    def _decide_proof(self, request: _ProofRequest) -> ProofObligation:
        r"""Simplify, dispatch, decide, and record a formula at its premise position."""

        proof_location = next(
            (
                step.location
                for step in reversed(self.steps)
                if step.rule != "Proof" and step.location
            ),
            "",
        )
        obligation = replace(
            request.obligation,
            location=request.obligation.location or proof_location,
        )
        proof_step = self._start_step(
            "Proof",
            proof_location or obligation.rule,
            obligation.description,
        )
        proof_formula = obligation.formula
        try:
            if obligation.kind == "state":
                if request.state is None or request.symbols is None:
                    verdict = Verdict.FALSE
                    detail = "invalid state proof request"
                else:
                    proof_formula = simplify(obligation.formula)
                    verdict, detail = self.proof_engine.state_satisfies(
                        proof_formula,
                        request.state,
                        request.symbols,
                    )
            elif obligation.kind == "fol":
                proof_formula = simplify(obligation.formula)
                verdict, detail = self.proof_engine.valid(proof_formula)
            elif obligation.kind == "dl":
                if request.automatically_true:
                    verdict = Verdict.TRUE
                    detail = (
                        "the annotated safety/domain formula is "
                        "syntactically true"
                    )
                else:
                    backend_result = self.dl_checker(obligation)
                    if isinstance(backend_result, DLCheckResult):
                        verdict = backend_result.verdict
                        detail = backend_result.detail
                    else:
                        verdict = Verdict.from_value(backend_result)
                        detail = (
                            "configured dL checker returned no decision"
                            if backend_result is None
                            else "result returned by the configured dL checker"
                        )
            else:
                verdict = Verdict.UNKNOWN
                detail = f"unsupported proof kind: {obligation.kind}"
        except Exception as exc:
            verdict = Verdict.UNKNOWN
            detail = f"proof checker failed: {exc}"

        decided = obligation.decided(
            verdict,
            detail,
            proof_formula=proof_formula,
        )
        self.obligations.append(decided)
        self._finish_step(
            proof_step,
            (
                'Immediate verdict = false; the current rule is disproved'
                if verdict is Verdict.FALSE
                else (
                    'Immediate verdict = unknown; record the unresolved obligation and continue'
                    if verdict is Verdict.UNKNOWN
                    else 'Immediate verdict = true; continue derivation'
                )
            ),
            f"{obligation.kind.upper()} obligation processed in derivation order.{detail}",
        )
        return decided

    def _report(
        self,
        constructed: ConfigurationType | None,
        constructed_component_types: tuple[ConfigurationType | None, ...],
    ) -> RuleDerivationReport:
        r"""Combine obligations and diagnostics into an immutable three-valued report."""
        verdict = Verdict.combine(
            [item.verdict for item in self.obligations if item.active]
            + [item.verdict for item in self.diagnostics]
        )
        return RuleDerivationReport(
            verdict=verdict,
            constructed_type=constructed,
            constructed_component_types=constructed_component_types,
            obligations=tuple(self.obligations),
            diagnostics=tuple(self.diagnostics),
            steps=tuple(self.steps),
        )

    def _diagnose(
        self,
        verdict: Verdict,
        message: str,
        rule: str = "",
        location: str = "",
    ) -> None:
        r"""Append a diagnostic with its rule and location."""
        self.diagnostics.append(Diagnostic(verdict, message, rule, location))

    @staticmethod
    def _channel_name(channel: str | Channel) -> str:
        r"""Normalize a Channel or string to its Theta key."""
        if isinstance(channel, str):
            # Apply the same identifier rules to Theta keys and Process/Type channels.
            return Channel(channel).name
        if isinstance(channel, Channel):
            return channel.name
        raise TypeError(
            "Theta keys must be strings or hcsp_typechecker Channel objects"
        )

    def _as_nodes(self, process: Process) -> list[Process]:
        r"""Flatten binary Sequence iteratively in execution order."""

        nodes: list[Process] = []
        pending: list[Process] = [process]
        while pending:
            current = pending.pop()
            if isinstance(current, SequenceHP):
                pending.append(current.second)
                pending.append(current.first)
            else:
                nodes.append(current)
        return nodes

    @staticmethod
    def _is_true(formula: Any) -> bool:
        r"""Recognize a syntactically simplified true formula."""
        if formula is True:
            return True
        return z3 is not None and z3.is_true(simplify(formula))

    @staticmethod
    def _is_default_true_path(value: Any) -> bool:
        r"""Recognize the default unconstrained true path input."""

        if value is True:
            return True
        if z3 is not None and isinstance(value, z3.BoolRef):
            return z3.is_true(simplify(value))
        try:
            expression = ensure_expr(value)
        except (TypeError, ValueError):
            return False
        return isinstance(expression, Literal) and expression.value is True

    def _require_numeric_type(
        self,
        value_type: BasicType,
        subject: str,
        context: _Context,
    ) -> bool:
        r"""Check a numeric type and diagnose failure."""
        if value_type not in {
            BasicType.NAT,
            BasicType.INT,
            BasicType.RATIONAL,
            BasicType.REAL,
        }:
            self._diagnose(
                Verdict.FALSE,
                f"{subject} must be numeric, got {value_type}",
                "expression-type",
                context.location,
            )
            return False
        return True

    def _type_domain_constraints(
        self,
        value_type: GammaType,
        symbol: Any,
    ) -> tuple[Any, ...]:
        r"""Generate intrinsic basic-type constraints; Nat requires x >= 0."""

        value_type = gamma_value_type(value_type)
        if value_type == BasicType.NAT:
            return (symbol >= 0,)
        return ()

    def _contains_type_var(self, value: ProcessType, name: str) -> bool:
        r"""Find a free type variable using an explicit work stack."""

        pending: list[ProcessType | AngelicType] = [value]
        while pending:
            current = pending.pop()
            if isinstance(current, TypeVar):
                if current.name == name:
                    return True
            elif isinstance(current, (InputType, OutputType)):
                pending.append(current.continuation)
            elif isinstance(current, (ExternalChoiceType, InternalChoiceType)):
                pending.extend(current.branches)
            elif isinstance(current, FiniteDelayType):
                pending.extend((current.interrupts, current.continuation))
            elif isinstance(current, InfiniteDelayType):
                pending.append(current.interrupts)
            elif isinstance(current, MuType) and current.variable != name:
                pending.append(current.body)
        return False

    def _guarded(
        self,
        value: ProcessType,
        name: str,
        under_communication: bool = False,
    ) -> bool:
        r"""Require recursion variables to be protected by communication prefixes."""
        pending: list[tuple[ProcessType | AngelicType, bool]] = [
            (value, under_communication)
        ]
        while pending:
            current, protected = pending.pop()
            if isinstance(current, TypeVar):
                if current.name == name and not protected:
                    return False
            elif isinstance(current, (InputType, OutputType)):
                pending.append((current.continuation, True))
            elif isinstance(current, (ExternalChoiceType, InternalChoiceType)):
                pending.extend((branch, protected) for branch in current.branches)
            elif isinstance(current, FiniteDelayType):
                pending.extend(
                    (
                        (current.interrupts, protected),
                        (current.continuation, protected),
                    )
                )
            elif isinstance(current, InfiniteDelayType):
                pending.append((current.interrupts, protected))
            elif isinstance(current, MuType) and current.variable != name:
                pending.append((current.body, protected))
        return True

    def _process_vars(self, process: Any) -> set[str]:
        r"""Collect value names for Gamma and parallel ownership checks."""
        if not isinstance(process, HCSP):
            return set()
        return process.get_vars()

    def _input_bound_vars(self, process: Any) -> set[str]:
        r"""Collect input targets, which need not be predeclared in Gamma."""
        if not isinstance(process, HCSP):
            return set()
        return process.get_input_bound_vars()
