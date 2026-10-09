r"""Check a supplied behavioral Type directly against the implemented Table 2 rules."""

from __future__ import annotations

from dataclasses import dataclass, replace
from math import inf
from typing import Any, Mapping, Sequence

from ...data_structures.process_ast.ast import (
    Assert,
    Assign,
    EmptyEvent,
    EventChoice,
    If,
    InputChannel,
    InternalChoice,
    Mu,
    ODE,
    OutputChannel,
    Parallel,
    Process,
    Skip,
    Var,
)
from ...data_structures.process_ast.expressions import Literal
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
)
from ...data_structures.type_ast.render import (
    format_configuration_type,
    format_process_type,
)
from ...data_structures.runtime_context import (
    Configuration,
)
from ..common.model import Verdict
from ..common.rule_engine import (
    Table2RuleEngine,
    _ChildJudgmentPremise,
    _ConfigurationJudgment,
    _EventJudgment,
    _FormulaPremise,
    _ODETypeRule,
    _ProcessJudgment,
    _RuleExpansion,
    _SystemJudgment,
)
from .model import TypeCheckingReport, TypeCheckingRequest


@dataclass(frozen=True, slots=True)
class _AlphaEnvironment:
    r"""Match internal and supplied recursion variables by lexical scope."""

    internal: Mapping[str, object]
    supplied: Mapping[str, object]

    @classmethod
    def empty(cls) -> "_AlphaEnvironment":
        r"""Create the root lexical environment without recursion bindings."""

        return cls({}, {})

    def bind(self, internal_name: str, supplied_name: str) -> "_AlphaEnvironment":
        r"""Bind a new pair of mu variables with shadowable identity."""

        identity = object()
        internal = dict(self.internal)
        supplied = dict(self.supplied)
        internal[internal_name] = identity
        supplied[supplied_name] = identity
        return _AlphaEnvironment(internal, supplied)

    def matches(self, internal_name: str, supplied_name: str) -> bool:
        r"""Check that variable references denote the same lexical recursion binder."""

        internal_identity = self.internal.get(internal_name)
        return (
            internal_identity is not None
            and self.supplied.get(supplied_name) is internal_identity
        )


@dataclass(frozen=True, slots=True)
class _ExpectedChild:
    r"""A child judgment with its expected Type and alpha-renaming environment."""

    expected: ConfigurationType | AngelicType
    alpha: _AlphaEnvironment


@dataclass(frozen=True, slots=True)
class _ODECheckAttempt:
    r"""An isolated TypeChecker attempt for one ODE candidate rule."""

    mode: _ODETypeRule
    matched: bool
    verdict: Verdict
    obligations: tuple[Any, ...]
    diagnostics: tuple[Any, ...]
    steps: tuple[Any, ...]
    mismatches: tuple[str, ...]


class TypeChecker(Table2RuleEngine):
    r"""Check whether the supplied Type is a valid conclusion of the HCSP judgment."""

    def check(self, request: TypeCheckingRequest) -> TypeCheckingReport:
        r"""Check the supplied Type and return rule and proof evidence."""

        self.obligations = []
        self.diagnostics = []
        self.steps = []
        self._fresh_counter = 0
        self._type_var_counter = 0
        self._type_mismatches: list[str] = []

        prepared = self._prepare_typing_environment(
            gamma_source=request.gamma,
            theta_source=request.theta,
            parameter_environment=request.parameters,
            path_condition=request.path_condition,
        )
        if prepared is None:
            evidence = self._report(None, ())
            reason = (
                self.diagnostics[-1].message
                if self.diagnostics
                else "The typing environment is not well formed"
            )
            return TypeCheckingReport(
                verdict=evidence.verdict,
                expected_type=request.expected_type,
                evidence=evidence,
                failure_reason=reason,
            )
        gamma = prepared.gamma
        theta = prepared.theta
        parameters = prepared.parameters
        parameter_symbols = prepared.parameter_symbols
        parameter_condition = prepared.parameter_condition

        configurations = request.configurations
        if not configurations:
            self._diagnose(
                Verdict.FALSE,
                "A type-checking request needs at least one configuration",
                "T-||",
            )
            evidence = self._report(None, ())
            return TypeCheckingReport(
                verdict=evidence.verdict,
                expected_type=request.expected_type,
                evidence=evidence,
                failure_reason="No configuration was supplied",
            )

        component_expectations = self._top_level_expectations(
            request.expected_type,
            len(configurations),
        )
        if component_expectations is None:
            evidence = self._report(None, tuple(None for _ in configurations))
            return TypeCheckingReport(
                verdict=evidence.verdict,
                expected_type=request.expected_type,
                evidence=evidence,
                mismatch=(
                    self._last_mismatch_message()
                    or "The supplied parallel Type shape does not match the HCSP components"
                ),
            )

        before = len(self.steps)
        expansion = self.rule_t_parallel(
            configurations,
            gamma,
            theta,
            request.path_condition,
            parameters,
            parameter_symbols,
            parameter_condition,
            request.parameters.constraint,
        )
        # Do not remap remaining supplied branches after environment or ownership validation
        # fails.
        if any(item.verdict is Verdict.FALSE for item in self.diagnostics):
            matched = False
        else:
            children = tuple(
                premise
                for premise in expansion.premises
                if isinstance(premise, _ChildJudgmentPremise)
            )
            if len(children) != len(component_expectations):
                self._mismatch(
                    "T-||",
                    "The number of configuration judgments does not match the "
                    "number of supplied Type components",
                )
                matched = False
            else:
                matched = True
                for premise, expected in zip(children, component_expectations):
                    if not self._check_child(
                        premise.judgment,
                        expected,
                        _AlphaEnvironment.empty(),
                    ):
                        matched = False
                        break
        if len(self.steps) > before:
            self._finish_step(
                before,
                (
                    'All supplied parallel type components match'
                ) if matched else (
                    'The supplied parallel type does not match'
                ),
                (
                    'TypeChecker checks components in source order without constructing an '
                    'alternative Type.'
                ),
            )

        component_types: tuple[ConfigurationType | None, ...] = (
            component_expectations
            if matched
            else tuple(None for _ in configurations)
        )
        evidence = self._report(
            request.expected_type if matched else None,
            component_types,
        )
        mismatch = ""
        if not matched:
            mismatch = self._last_mismatch_message()
        return TypeCheckingReport(
            verdict=evidence.verdict,
            expected_type=request.expected_type,
            evidence=evidence,
            mismatch=mismatch,
        )

    def _top_level_expectations(
        self,
        expected: ConfigurationType,
        component_count: int,
    ) -> tuple[ConfigurationType, ...] | None:
        r"""Assign supplied top-level types to source configurations."""

        if component_count == 1:
            return (expected,)
        if not isinstance(expected, ParallelType):
            self._mismatch(
                "T-||",
                f"{component_count} HCSP components require a ParallelType",
            )
            return None
        if len(expected.components) != component_count:
            self._mismatch(
                "T-||",
                f"ParallelType has {len(expected.components)} components, "
                f"but the HCSP source has {component_count}",
            )
            return None
        return expected.components

    def _check_expansion(
        self,
        expansion: _RuleExpansion,
        expected_children: Sequence[_ExpectedChild],
    ) -> bool:
        r"""Decide ordered formulas and consume corresponding supplied Type subtrees."""

        child_index = 0
        for premise in expansion.premises:
            if isinstance(premise, _FormulaPremise):
                if self._decide_proof(premise.request).verdict is Verdict.FALSE:
                    return False
                continue
            if not isinstance(premise, _ChildJudgmentPremise):
                raise TypeError(
                    f"Unsupported premise in {expansion.rule}: "
                    f"{type(premise).__name__}"
                )
            if child_index >= len(expected_children):
                self._mismatch(
                    expansion.rule,
                    "The supplied Type has too few child conclusions for this rule",
                )
                return False
            child = expected_children[child_index]
            child_index += 1
            if not self._check_child(
                premise.judgment,
                child.expected,
                child.alpha,
            ):
                return False
        if child_index != len(expected_children):
            self._mismatch(
                expansion.rule,
                "The supplied Type has too many child conclusions for this rule",
            )
            return False
        return not any(item.verdict is Verdict.FALSE for item in self.diagnostics)

    def _check_child(
        self,
        judgment: Any,
        expected: ConfigurationType | AngelicType,
        alpha: _AlphaEnvironment,
    ) -> bool:
        r"""Dispatch checking by explicit judgment kind."""

        if isinstance(judgment, _ConfigurationJudgment):
            return self._check_configuration(judgment, expected, alpha)
        if isinstance(judgment, _SystemJudgment):
            return self._check_system(judgment, expected, alpha)
        if isinstance(judgment, _ProcessJudgment):
            if not isinstance(expected, ProcessType):
                return self._mismatch(
                    "structural",
                    f"A process judgment requires ProcessType, got {type(expected).__name__}",
                    judgment.context.location,
                )
            return self._check_process(judgment, expected, alpha)
        if isinstance(judgment, _EventJudgment):
            if not isinstance(expected, AngelicType):
                return self._mismatch(
                    "T-&",
                    f"An event judgment requires AngelicType, got {type(expected).__name__}",
                    judgment.context.location,
                )
            return self._check_event(judgment, expected, alpha)
        raise TypeError(f"Unsupported child judgment: {type(judgment).__name__}")

    def _check_configuration(
        self,
        judgment: _ConfigurationJudgment,
        expected: ConfigurationType | AngelicType,
        alpha: _AlphaEnvironment,
    ) -> bool:
        r"""Check T-sigma's state premise and system child judgment."""

        if not isinstance(expected, ConfigurationType):
            return self._mismatch(
                "T-sigma",
                "A configuration requires a configuration type",
                judgment.context.location,
            )
        step = self._start_step(
            "T-sigma",
            judgment.context.location,
            'Check initial state and supplied type '
            + format_configuration_type(expected),
            context=judgment.context,
        )
        before = len(self.diagnostics)
        expansion = self.rule_t_sigma(judgment)
        failed_statically = any(
            item.verdict is Verdict.FALSE for item in self.diagnostics[before:]
        )
        matched = (not failed_statically) and self._check_expansion(
            expansion,
            (_ExpectedChild(expected, alpha),),
        )
        self._finish_step(
            step,
            (
                'Supplied configuration type matches'
            ) if matched else (
                'Supplied configuration type does not match'
            ),
            self._premise_summary(expansion),
        )
        return matched

    def _check_system(
        self,
        judgment: _SystemJudgment,
        expected: ConfigurationType | AngelicType,
        alpha: _AlphaEnvironment,
    ) -> bool:
        r"""Check the supplied type of a Process or binary Parallel system."""

        system = judgment.system
        if isinstance(system, Process):
            if not isinstance(expected, ProcessType):
                return self._mismatch(
                    "structural",
                    f"Process requires ProcessType, got {type(expected).__name__}",
                    judgment.context.location,
                )
            return self._check_process(
                _ProcessJudgment(
                    tuple(self._as_nodes(system)),
                    judgment.context,
                    EmptyType(),
                ),
                expected,
                alpha,
            )
        if not isinstance(system, Parallel):
            return self._mismatch(
                "structural",
                f"Unsupported HCSP system node {type(system).__name__}",
                judgment.context.location,
            )
        if not isinstance(expected, ParallelType):
            return self._mismatch(
                "T-||",
                "A Parallel system requires ParallelType",
                judgment.context.location,
            )
        left_count = self._parallel_leaf_count(system.left)
        right_count = self._parallel_leaf_count(system.right)
        if len(expected.components) != left_count + right_count:
            return self._mismatch(
                "T-||",
                "ParallelType component count does not match the Parallel system",
                judgment.context.location,
            )
        left_expected = self._group_parallel_type(
            expected.components[:left_count]
        )
        right_expected = self._group_parallel_type(
            expected.components[left_count:]
        )
        expansion = self.rule_t_parallel_system(judgment)
        return self._check_expansion(
            expansion,
            (
                _ExpectedChild(left_expected, alpha),
                _ExpectedChild(right_expected, alpha),
            ),
        )

    def _check_process(
        self,
        judgment: _ProcessJudgment,
        expected: ProcessType,
        alpha: _AlphaEnvironment,
    ) -> bool:
        r"""Consume linear prefixes iteratively; dispatch only actual branches."""

        deferred_steps: list[tuple[int, _RuleExpansion]] = []
        current_judgment = judgment
        current_expected = expected
        while current_judgment.nodes:
            head = current_judgment.nodes[0]
            if not isinstance(
                head,
                (Skip, Assert, Assign, InputChannel, OutputChannel),
            ):
                break
            if isinstance(head, Skip) and len(current_judgment.nodes) == 1:
                matched = self._match_terminal(
                    current_judgment.terminal,
                    current_expected,
                    alpha,
                    current_judgment.context.location,
                )
                self._finish_linear_steps(deferred_steps, matched)
                return matched

            rule = self._rule_name(head)
            step = self._start_step(
                rule,
                current_judgment.context.location,
                f"{self._describe_process_node(head)}; supplied Type = "
                + type(current_expected).__name__,
                context=current_judgment.context,
            )
            before = len(self.diagnostics)
            next_expected = current_expected
            if isinstance(head, Skip):
                expansion = self.rule_t_skip(current_judgment)
            elif isinstance(head, Assert):
                expansion = self.rule_t_assert(current_judgment)
            elif isinstance(head, Assign):
                expansion = self.rule_t_assign(current_judgment)
            elif isinstance(head, InputChannel):
                if not (
                    isinstance(current_expected, InfiniteDelayType)
                    and isinstance(current_expected.interrupts, InputType)
                    and current_expected.interrupts.channel == head.channel.name
                ):
                    matched = self._finish_mismatch_step(
                        step,
                        "T-In requires forever interrupt input on the same channel",
                        current_judgment.context.location,
                    )
                    self._finish_linear_steps(deferred_steps, matched)
                    return matched
                expansion = self.rule_t_in(current_judgment)
                next_expected = current_expected.interrupts.continuation
            else:
                assert isinstance(head, OutputChannel)
                if not (
                    isinstance(current_expected, InfiniteDelayType)
                    and isinstance(current_expected.interrupts, OutputType)
                    and current_expected.interrupts.channel == head.channel.name
                ):
                    matched = self._finish_mismatch_step(
                        step,
                        "T-Out requires forever interrupt output on the same channel",
                        current_judgment.context.location,
                    )
                    self._finish_linear_steps(deferred_steps, matched)
                    return matched
                expansion = self.rule_t_out(current_judgment)
                next_expected = current_expected.interrupts.continuation

            child_judgments: list[_ProcessJudgment] = []
            matched = True
            for premise in expansion.premises:
                if isinstance(premise, _FormulaPremise):
                    if self._decide_proof(premise.request).verdict is Verdict.FALSE:
                        matched = False
                        break
                elif isinstance(premise, _ChildJudgmentPremise):
                    if not isinstance(premise.judgment, _ProcessJudgment):
                        raise TypeError(
                            f"{rule} linear prefix produced a non-process child"
                        )
                    child_judgments.append(premise.judgment)
                else:
                    raise TypeError(
                        f"Unsupported premise in {rule}: {type(premise).__name__}"
                    )
            if any(
                item.verdict is Verdict.FALSE
                for item in self.diagnostics[before:]
            ):
                matched = False
            if not matched or len(child_judgments) != 1:
                if matched:
                    self._mismatch(
                        rule,
                        "A linear rule must produce exactly one process child",
                        current_judgment.context.location,
                    )
                    matched = False
                self._finish_step(
                    step,
                    'The supplied Type does not match the rule conclusion',
                    self._premise_summary(expansion),
                )
                self._finish_linear_steps(deferred_steps, matched)
                return matched
            deferred_steps.append((step, expansion))
            current_judgment = child_judgments[0]
            current_expected = next_expected

        if current_judgment.nodes:
            matched = self._check_process_node(
                current_judgment,
                current_expected,
                alpha,
            )
        else:
            matched = self._match_terminal(
                current_judgment.terminal,
                current_expected,
                alpha,
                current_judgment.context.location,
            )
        self._finish_linear_steps(deferred_steps, matched)
        return matched

    def _finish_linear_steps(
        self,
        deferred: Sequence[tuple[int, _RuleExpansion]],
        matched: bool,
    ) -> None:
        r"""Complete linear audit steps in stack-unwinding order."""

        for step, expansion in reversed(deferred):
            self._finish_step(
                step,
                'The supplied Type matches the rule conclusion'
                if matched
                else 'The supplied Type does not match the rule conclusion',
                self._premise_summary(expansion),
            )

    def _check_process_node(
        self,
        judgment: _ProcessJudgment,
        expected: ProcessType,
        alpha: _AlphaEnvironment,
    ) -> bool:
        r"""Decompose the supplied type according to the current process node."""

        nodes = judgment.nodes
        context = judgment.context
        if not nodes:
            return self._match_terminal(judgment.terminal, expected, alpha, context.location)

        head = nodes[0]
        if isinstance(head, ODE) and self._needs_ode_skip_rule_selection(
            judgment
        ):
            return self._check_ode_skip_rule_candidates(
                judgment,
                expected,
                alpha,
            )
        terminal_skip = isinstance(head, Skip) and len(nodes) == 1
        if terminal_skip:
            return self._match_terminal(judgment.terminal, expected, alpha, context.location)

        rule = self._rule_name(head)
        step = self._start_step(
            rule,
            context.location,
            f"{self._describe_process_node(head)}; supplied Type = "
            + format_process_type(expected),
            context=context,
        )
        before = len(self.diagnostics)
        expansion: _RuleExpansion
        children: tuple[_ExpectedChild, ...]

        if isinstance(head, Skip):
            expansion = self.rule_t_skip(judgment)
            children = (_ExpectedChild(expected, alpha),)
        elif isinstance(head, Assert):
            expansion = self.rule_t_assert(judgment)
            children = (_ExpectedChild(expected, alpha),)
        elif isinstance(head, Assign):
            expansion = self.rule_t_assign(judgment)
            children = (_ExpectedChild(expected, alpha),)
        elif isinstance(head, InputChannel):
            if not (
                isinstance(expected, InfiniteDelayType)
                and isinstance(expected.interrupts, InputType)
                and expected.interrupts.channel == head.channel.name
            ):
                return self._finish_mismatch_step(
                    step,
                    "T-In requires forever interrupt input on the same channel",
                    context.location,
                )
            expansion = self.rule_t_in(judgment)
            children = (_ExpectedChild(expected.interrupts.continuation, alpha),)
        elif isinstance(head, OutputChannel):
            if not (
                isinstance(expected, InfiniteDelayType)
                and isinstance(expected.interrupts, OutputType)
                and expected.interrupts.channel == head.channel.name
            ):
                return self._finish_mismatch_step(
                    step,
                    "T-Out requires forever interrupt output on the same channel",
                    context.location,
                )
            expansion = self.rule_t_out(judgment)
            children = (_ExpectedChild(expected.interrupts.continuation, alpha),)
        elif isinstance(head, If):
            if not isinstance(expected, InternalChoiceType):
                return self._finish_mismatch_step(
                    step,
                    "T-If requires an InternalChoiceType",
                    context.location,
                )
            expansion = self.rule_t_if(judgment)
            if len(expected.branches) != 2:
                return self._finish_mismatch_step(
                    step,
                    "T-If requires exactly two parenthesized type branches",
                    context.location,
                )
            children = tuple(
                _ExpectedChild(branch, alpha) for branch in expected.branches
            )
        elif isinstance(head, InternalChoice):
            if not isinstance(expected, InternalChoiceType):
                return self._finish_mismatch_step(
                    step,
                    "T-sqcup requires InternalChoiceType",
                    context.location,
                )
            if len(expected.branches) != len(head.branches):
                return self._finish_mismatch_step(
                    step,
                    f"T-sqcup has {len(head.branches)} process branches but "
                    f"the supplied type node has {len(expected.branches)} branches",
                    context.location,
                )
            expansion = self.rule_t_internal_choice(judgment)
            children = tuple(
                _ExpectedChild(branch, alpha) for branch in expected.branches
            )
        elif isinstance(head, ODE):
            expansion, children = self._check_ode_shape(
                judgment,
                expected,
                alpha,
                step,
            )
            if expansion is None:
                return False
        elif isinstance(head, Mu):
            if self._observable_recursion_tail(judgment.nodes[1:]):
                return self._finish_mismatch_step(
                    step,
                    "T-mu only supports guarded tail recursion without a later sequence tail",
                    context.location,
                )
            expansion = self.rule_t_mu(judgment)
            process_children = tuple(
                premise.judgment
                for premise in expansion.premises
                if isinstance(premise, _ChildJudgmentPremise)
                and isinstance(premise.judgment, _ProcessJudgment)
            )
            if len(process_children) != 1:
                return self._finish_mismatch_step(
                    step,
                    "T-mu could not establish its recursive body judgment",
                    context.location,
                )
            body_judgment = process_children[0]
            if isinstance(expected, MuType):
                if not self._contains_type_var(expected.body, expected.variable):
                    return self._finish_mismatch_step(
                        step,
                        "A non-recursive body must not be wrapped in a redundant MuType",
                        context.location,
                    )
                binding = body_judgment.context.rec_env.get(head.variable)
                if binding is None:
                    return self._finish_mismatch_step(
                        step,
                        "T-mu did not create a recursive type-variable binding",
                        context.location,
                    )
                body_alpha = alpha.bind(
                    binding.type_var.name,
                    expected.variable,
                )
                children = (_ExpectedChild(expected.body, body_alpha),)
            else:
                children = (_ExpectedChild(expected, alpha),)
        elif isinstance(head, Var):
            binding = context.rec_env.get(head.name)
            if binding is None:
                return self._finish_mismatch_step(
                    step,
                    f"Unbound process variable {head.name!r}",
                    context.location,
                )
            if not isinstance(expected, TypeVar) or not alpha.matches(
                binding.type_var.name,
                expected.name,
            ):
                return self._finish_mismatch_step(
                    step,
                    f"T-X expects the TypeVar bound to process variable {head.name!r}",
                    context.location,
                )
            expansion = self.rule_t_x(judgment)
            children = ()
        else:
            return self._finish_mismatch_step(
                step,
                f"Unsupported Process node {type(head).__name__}",
                context.location,
            )

        static_failure = any(
            item.verdict is Verdict.FALSE for item in self.diagnostics[before:]
        )
        if static_failure:
            matched = False
        else:
            matched = self._check_expansion(expansion, children)
        self._finish_step(
            step,
            (
                'The supplied Type matches the rule conclusion'
            ) if matched else (
                'The supplied Type does not match the rule conclusion'
            ),
            self._premise_summary(expansion),
        )
        return matched

    def _attempt_ode_check_candidate(
        self,
        judgment: _ProcessJudgment,
        expected: ProcessType,
        alpha: _AlphaEnvironment,
        mode: _ODETypeRule,
    ) -> _ODECheckAttempt:
        r"""Try one ODE checking candidate, then roll back shared report state."""

        obligation_start = len(self.obligations)
        diagnostic_start = len(self.diagnostics)
        step_start = len(self.steps)
        mismatch_start = len(self._type_mismatches)
        step = self._start_step(
            "T-ODE",
            judgment.context.location,
            f"Use {mode.value} to check supplied Type = "
            + format_process_type(expected),
            context=judgment.context,
        )
        expansion, children = self._check_ode_shape(
            judgment,
            expected,
            alpha,
            step,
            candidate=mode,
        )
        static_failure = any(
            item.verdict is Verdict.FALSE
            for item in self.diagnostics[diagnostic_start:]
        )
        matched = (
            expansion is not None
            and not static_failure
            and self._check_expansion(expansion, children)
        )
        self._finish_step(
            step,
            'Candidate rule matches' if matched else 'Candidate rule does not match',
            "" if expansion is None else self._premise_summary(expansion),
        )

        obligations = tuple(self.obligations[obligation_start:])
        diagnostics = tuple(self.diagnostics[diagnostic_start:])
        steps = tuple(self.steps[step_start:])
        mismatches = tuple(self._type_mismatches[mismatch_start:])
        del self.obligations[obligation_start:]
        del self.diagnostics[diagnostic_start:]
        del self.steps[step_start:]
        del self._type_mismatches[mismatch_start:]

        verdict_inputs = [item.verdict for item in obligations]
        verdict_inputs.extend(item.verdict for item in diagnostics)
        if not matched and not any(
            item is Verdict.FALSE for item in verdict_inputs
        ):
            verdict_inputs.append(Verdict.FALSE)
        return _ODECheckAttempt(
            mode,
            matched,
            Verdict.combine(verdict_inputs),
            obligations,
            diagnostics,
            steps,
            mismatches,
        )

    def _check_ode_skip_rule_candidates(
        self,
        judgment: _ProcessJudgment,
        expected: ProcessType,
        alpha: _AlphaEnvironment,
    ) -> bool:
        r"""Check both timed ODE rules independently for ODE; skip."""

        step = self._start_step(
            "T-ODE-Select",
            judgment.context.location,
            'ODE followed by terminal skip: determine which rule accepts the supplied Type',
            context=judgment.context,
        )
        attempts = tuple(
            self._attempt_ode_check_candidate(
                judgment,
                expected,
                alpha,
                mode,
            )
            for mode in (
                _ODETypeRule.COMMUNICATION_ONLY,
                _ODETypeRule.NATURAL_TIMEOUT,
            )
        )
        proved = tuple(
            item
            for item in attempts
            if item.matched and item.verdict is Verdict.TRUE
        )
        unknown = tuple(
            item
            for item in attempts
            if item.matched and item.verdict is Verdict.UNKNOWN
        )

        selected: _ODECheckAttempt | None = None
        warning = ""
        if len(proved) == 1:
            selected = proved[0]
            # A proved matching candidate wins; an unselected UNKNOWN attempt remains audit
            # evidence only.
        elif len(proved) > 1:
            # If both candidates prove and consume the supplied Type, keep the first equivalent
            # result.
            selected = proved[0]
        elif unknown:
            selected = next(
                (
                    item
                    for item in unknown
                    if item.mode is _ODETypeRule.NATURAL_TIMEOUT
                ),
                unknown[0],
            )
            if len(unknown) > 1:
                warning = (
                    "Both ODE rule checks remain unknown; the natural-timeout "
                    "match is retained provisionally"
                )

        for attempt in attempts:
            active = attempt is selected
            self.obligations.extend(
                replace(
                    obligation,
                    active=active,
                    candidate=attempt.mode.value,
                )
                for obligation in attempt.obligations
            )
        if selected is not None:
            self.diagnostics.extend(selected.diagnostics)
            self.steps.extend(selected.steps)
            self._type_mismatches.extend(selected.mismatches)
        if warning:
            self._diagnose(
                Verdict.UNKNOWN,
                warning,
                "T-ODE-Select",
                judgment.context.location,
            )

        summary = "; ".join(
            f"{item.mode.value}: matched={item.matched}, "
            f"verdict={item.verdict.value}"
            for item in attempts
        )
        if selected is not None:
            self._finish_step(
                step,
                f"Supplied Type accepted by {selected.mode.value}",
                summary,
            )
            return True

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
            self._type_mismatches.extend(attempt.mismatches)
        if not warning:
            message = "Neither ODE rule accepts the supplied Type"
            self._diagnose(
                Verdict.FALSE,
                message,
                "T-ODE-Select",
                judgment.context.location,
            )
            if not self._type_mismatches:
                self._type_mismatches.append(message)
        self._finish_step(step, 'The supplied Type failed ODE candidate selection', summary)
        return False

    def _check_ode_shape(
        self,
        judgment: _ProcessJudgment,
        expected: ProcessType,
        alpha: _AlphaEnvironment,
        step: int,
        *,
        candidate: _ODETypeRule | None = None,
    ) -> tuple[_RuleExpansion | None, tuple[_ExpectedChild, ...]]:
        r"""Check delay structure and allocate interrupt and timeout types to premises."""

        node = judgment.nodes[0]
        assert isinstance(node, ODE)
        annotation_delay = node.annotation.delay
        duration = (
            annotation_delay.value
            if isinstance(annotation_delay, Literal)
            else annotation_delay
        )
        infinite = isinstance(duration, float) and duration == inf
        if infinite:
            if not isinstance(expected, InfiniteDelayType):
                self._finish_mismatch_step(
                    step,
                    "An infinite-delay ODE requires InfiniteDelayType",
                    judgment.context.location,
                )
                return None, ()
            expansion = self.rule_t_ode(judgment, candidate=candidate)
            return expansion, (_ExpectedChild(expected.interrupts, alpha),)

        if not isinstance(expected, FiniteDelayType):
            self._finish_mismatch_step(
                step,
                "A finite-delay ODE requires FiniteDelayType",
                judgment.context.location,
            )
            return None, ()
        if expected.duration != duration:
            self._finish_mismatch_step(
                step,
                f"ODE annotation delay is {duration}, but supplied Type uses "
                f"{expected.duration}",
                judgment.context.location,
            )
            return None, ()
        expansion = self.rule_t_ode(judgment, candidate=candidate)
        if candidate is _ODETypeRule.COMMUNICATION_ONLY:
            if not isinstance(expected.continuation, BottomType):
                self._finish_mismatch_step(
                    step,
                    "T-unrhd requires BottomType as its unreachable "
                    "deadline continuation",
                    judgment.context.location,
                )
                return None, ()
            return expansion, (_ExpectedChild(expected.interrupts, alpha),)
        # A real timeout continuation may itself be terminal skip.
        if isinstance(expected.continuation, BottomType):
            self._finish_mismatch_step(
                step,
                "T-unrhd-prime requires a reachable non-bottom continuation",
                judgment.context.location,
            )
            return None, ()
        return expansion, (
            _ExpectedChild(expected.interrupts, alpha),
            _ExpectedChild(expected.continuation, alpha),
        )

    def _check_event(
        self,
        judgment: _EventJudgment,
        expected: AngelicType,
        alpha: _AlphaEnvironment,
    ) -> bool:
        r"""Check angelic branches in their canonical source order."""

        reaction = judgment.reaction
        if isinstance(reaction, EmptyEvent):
            if not isinstance(expected, NoInterruptType):
                return self._mismatch(
                    "T-&",
                    "An empty interrupt table requires NoInterruptType",
                    judgment.context.location,
                )
            expansion = self.rule_t_external_choice(judgment)
            return self._check_expansion(expansion, ())
        if not isinstance(reaction, EventChoice):
            return self._mismatch(
                "T-&",
                f"Unsupported event node {type(reaction).__name__}",
                judgment.context.location,
            )
        if isinstance(expected, (InputType, OutputType)):
            branches = (expected,)
        elif isinstance(expected, ExternalChoiceType):
            branches = expected.branches
        else:
            return self._mismatch(
                "T-&",
                "A non-empty interrupt table requires communication angelic branches",
                judgment.context.location,
            )
        if len(branches) != len(reaction.branches):
            return self._mismatch(
                "T-&",
                f"Interrupt table has {len(reaction.branches)} branches but the "
                f"supplied angelic type has {len(branches)}",
                judgment.context.location,
            )
        expansion = self.rule_t_external_choice(judgment)
        return self._check_expansion(
            expansion,
            tuple(
                _ExpectedChild(InfiniteDelayType(branch), alpha)
                for branch in branches
            ),
        )

    def _match_terminal(
        self,
        terminal: ProcessType,
        expected: ProcessType,
        alpha: _AlphaEnvironment,
        location: str,
    ) -> bool:
        r"""Match terminal EmptyType or the recursion body's type-variable endpoint."""

        if isinstance(terminal, EmptyType) and isinstance(expected, EmptyType):
            return True
        if isinstance(terminal, TypeVar) and isinstance(expected, TypeVar):
            if alpha.matches(terminal.name, expected.name):
                return True
        return self._mismatch(
            "T-End",
            "Terminal conclusion must be "
            + format_process_type(terminal)
            + ", got "
            + format_process_type(expected),
            location,
        )

    @staticmethod
    def _parallel_leaf_count(system: Any) -> int:
        r"""Count Process leaves in a binary Parallel system."""

        count = 0
        pending = [system]
        while pending:
            current = pending.pop()
            if isinstance(current, Parallel):
                pending.extend((current.left, current.right))
            else:
                count += 1
        return count

    @staticmethod
    def _group_parallel_type(
        components: Sequence[ConfigurationType],
    ) -> ConfigurationType:
        r"""Group consecutive Type components to match the system subtree."""

        if len(components) == 1:
            return components[0]
        return ParallelType(components)

    def _finish_mismatch_step(
        self,
        step: int,
        message: str,
        location: str,
    ) -> bool:
        r"""Record a structural mismatch and complete the rule step."""

        self._mismatch(self.steps[step].rule, message, location)
        self._finish_step(step, 'The supplied Type does not match the rule conclusion', message)
        return False

    def _mismatch(
        self,
        rule: str,
        message: str,
        location: str = "judgment",
    ) -> bool:
        r"""Record a located Type mismatch and return False."""

        self._type_mismatches.append(message)
        self._diagnose(Verdict.FALSE, message, rule, location)
        return False

    def _last_mismatch_message(self) -> str:
        r"""Return the last definite mismatch diagnostic for public summaries."""

        return self._type_mismatches[-1] if self._type_mismatches else ""


__all__ = ["TypeChecker"]
