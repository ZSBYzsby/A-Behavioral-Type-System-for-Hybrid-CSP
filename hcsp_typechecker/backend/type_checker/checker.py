"""按项目实际 Table 2 规则检查用户给定的行为 Type。

本模块实现真正的 *Type-directed checking*，而不是先调用 TypeConstructor
构造一个类型、再比较两棵完整 Type AST。检查器把用户 Type 作为每个规则
judgment 的右侧结论：规则展开产生公式 premise 和子 judgment，公式立即交给
与 TypeConstructor 相同的证明后端，子 judgment 则递归消费用户 Type 的对应
子树。

因此，TypeConstructor 与 TypeChecker 共享的是环境规范化、符号状态变换、
FOL/dL 公式生成和证明机制；二者的递归目标不同：前者组合子结论以构造 Type，
后者拆解给定 Type 以核对规则结论。多元外部中断按分支数量和源码顺序逐项检查；
内部选择保留用户圆括号给出的嵌套分块，每一层都按当前规则的元数和顺序逐项检查。
"""

from __future__ import annotations

from dataclasses import dataclass
from math import inf
from typing import Any, Mapping, Sequence

from ...identifiers import is_hcsp_identifier
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
    BasicType,
    Configuration,
    GammaType,
    normalize_channel_type,
    normalize_gamma_type,
    normalize_type,
)
from ..common.model import Verdict
from ..common.rule_engine import (
    Table2RuleEngine,
    _ChildJudgmentPremise,
    _ConfigurationJudgment,
    _EventJudgment,
    _FormulaPremise,
    _ProcessJudgment,
    _RuleExpansion,
    _SystemJudgment,
)
from ..common.logic import ExpressionError, ExpressionTranslator, conjunction
from .model import TypeCheckingReport, TypeCheckingRequest


@dataclass(frozen=True, slots=True)
class _ExpectedChild:
    """一个子 judgment 及其必须匹配的用户 Type 和递归 alpha 环境。"""

    expected: ConfigurationType | AngelicType
    alpha: Mapping[str, str]


class TypeChecker(Table2RuleEngine):
    """递归验证用户 Type 是否能成为给定 HCSP judgment 的结论。

    本类与 TypeConstructor 分别继承共享 ``Table2RuleEngine``；它只调用已审计的
    规则展开、符号执行和证明工具，不调用 TypeConstructor，也不调用规则的
    ``conclude`` 组合函数。
    """

    def check(self, request: TypeCheckingRequest) -> TypeCheckingReport:
        """规范化环境，然后以用户 Type 为目标递归检查全部 Table 2 规则。"""

        self.obligations = []
        self.diagnostics = []
        self.steps = []
        self._fresh_counter = 0
        self._type_var_counter = 0
        self._type_mismatches: list[str] = []

        prepared = self._prepare_environment(request)
        if prepared is None:
            evidence = self._report(None, ())
            return TypeCheckingReport(
                evidence.verdict,
                request.expected_type,
                evidence,
                "The typing environment is not well formed",
            )
        gamma, theta, parameters, parameter_symbols, parameter_condition = prepared

        configurations = request.configurations
        if not configurations:
            self._diagnose(
                Verdict.FALSE,
                "A type-checking request needs at least one configuration",
                "T-||",
            )
            evidence = self._report(None, ())
            return TypeCheckingReport(
                evidence.verdict,
                request.expected_type,
                evidence,
                "No configuration was supplied",
            )

        component_expectations = self._top_level_expectations(
            request.expected_type,
            len(configurations),
        )
        if component_expectations is None:
            evidence = self._report(None, tuple(None for _ in configurations))
            return TypeCheckingReport(
                evidence.verdict,
                request.expected_type,
                evidence,
                "The supplied parallel Type shape does not match the HCSP components",
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
        # rule_t_parallel 已对 Gamma 分区做完整静态检查。发生静态错误时不应
        # 尝试把余下的 Type 分支错配到别的配置。
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
                    if not self._check_child(premise.judgment, expected, {}):
                        matched = False
                        break
        if len(self.steps) > before:
            self._finish_step(
                before,
                "给定并行类型的全部分量均匹配" if matched else "给定并行类型不匹配",
                "TypeChecker 按源码顺序逐项检查配置分量，不构造替代 Type。",
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
            evidence.verdict,
            request.expected_type,
            evidence,
            mismatch,
        )

    def _prepare_environment(
        self,
        request: TypeCheckingRequest,
    ) -> tuple[
        dict[str, GammaType],
        dict[str, Any],
        dict[str, BasicType],
        dict[str, Any],
        Any,
    ] | None:
        """执行 Constructor/Checker 共用的 Gamma、Theta 与参数规范化。"""

        try:
            invalid_gamma_names = {
                repr(name) for name in request.gamma if not is_hcsp_identifier(name)
            }
            if invalid_gamma_names:
                raise ValueError(
                    "Invalid Gamma names: " + ", ".join(sorted(invalid_gamma_names))
                )
            gamma = {
                name: normalize_gamma_type(value, subject="Gamma entry")
                for name, value in request.gamma.items()
            }
            self._validate_continuous_vectors(gamma)

            invalid_parameter_names = {
                repr(name)
                for name in request.parameters.declarations
                if not is_hcsp_identifier(name)
            }
            if invalid_parameter_names:
                raise ValueError(
                    "Invalid parameter names: "
                    + ", ".join(sorted(invalid_parameter_names))
                )
            parameters = {
                name: normalize_type(value, subject="Parameter declaration")
                for name, value in request.parameters.declarations.items()
            }
            overlap = set(gamma) & set(parameters)
            if overlap:
                raise ValueError(
                    "Gamma and the shared parameter environment overlap: "
                    + ", ".join(sorted(overlap))
                )
            theta = {
                self._channel_name(name): normalize_channel_type(value)
                for name, value in request.theta.items()
            }
        except (TypeError, ValueError) as exc:
            self._diagnose(
                Verdict.FALSE,
                f"Invalid typing environment: {exc}",
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
            constraint = translator.boolean_result(request.parameters.constraint)
            parameter_condition = conjunction(
                self._defined_term(constraint),
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
                "type checking continues but cannot be trusted: " + detail,
                "parameters",
            )

        step = self._start_step(
            "environment",
            "judgment",
            "规范化 TypeChecker 的 Gamma、Theta 与共享参数",
            gamma=gamma,
            parameters=parameters,
            parameter_constraint=request.parameters.constraint,
            theta=theta,
            path=request.path_condition,
        )
        self._finish_step(
            step,
            "环境规范化成功",
            "后续规则与 TypeConstructor 使用完全相同的符号类型环境。",
        )
        return gamma, theta, parameters, parameter_symbols, parameter_condition

    def _top_level_expectations(
        self,
        expected: ConfigurationType,
        component_count: int,
    ) -> tuple[ConfigurationType, ...] | None:
        """把顶层给定 Type 分配给源码的配置分量。"""

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
        """按规则书写顺序证明公式，并递归检查给定的子类型。"""

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
        alpha: Mapping[str, str],
    ) -> bool:
        """按显式 judgment 类别分派给对应的给定类型检查函数。"""

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
        alpha: Mapping[str, str],
    ) -> bool:
        """检查 [T-sigma] 的状态前提和系统子判断。"""

        if not isinstance(expected, ConfigurationType):
            return self._mismatch(
                "T-sigma",
                "A configuration requires a configuration type",
                judgment.context.location,
            )
        step = self._start_step(
            "T-sigma",
            judgment.context.location,
            "检查初始状态与给定类型 "
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
            "给定配置类型匹配" if matched else "给定配置类型不匹配",
            self._premise_summary(expansion),
        )
        return matched

    def _check_system(
        self,
        judgment: _SystemJudgment,
        expected: ConfigurationType | AngelicType,
        alpha: Mapping[str, str],
    ) -> bool:
        """检查系统层 Process 或二元 Parallel 的给定类型。"""

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
        alpha: Mapping[str, str],
    ) -> bool:
        """按当前 Process 头结点拆解并检查给定 ProcessType。"""

        nodes = judgment.nodes
        context = judgment.context
        if not nodes:
            return self._match_terminal(judgment.terminal, expected, alpha, context.location)

        head = nodes[0]
        terminal_skip = isinstance(head, Skip) and len(nodes) == 1
        if terminal_skip:
            return self._match_terminal(judgment.terminal, expected, alpha, context.location)

        rule = self._rule_name(head)
        step = self._start_step(
            rule,
            context.location,
            f"{self._describe_process_node(head)}；给定 Type = "
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
            if judgment.nodes[1:]:
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
                body_alpha = dict(alpha)
                body_alpha[binding.type_var.name] = expected.variable
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
            expected_name = alpha.get(binding.type_var.name)
            if not isinstance(expected, TypeVar) or expected.name != expected_name:
                return self._finish_mismatch_step(
                    step,
                    f"T-X expects recursive TypeVar {expected_name!r}",
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
            "给定 Type 与规则结论匹配" if matched else "给定 Type 与规则结论不匹配",
            self._premise_summary(expansion),
        )
        return matched

    def _check_ode_shape(
        self,
        judgment: _ProcessJudgment,
        expected: ProcessType,
        alpha: Mapping[str, str],
        step: int,
    ) -> tuple[_RuleExpansion | None, tuple[_ExpectedChild, ...]]:
        """检查 ODE 的 delay 外形，并把 A/T 分配给事件和自然后继。"""

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
            expansion = self.rule_t_ode(judgment)
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
        expansion = self.rule_t_ode(judgment)
        return expansion, (
            _ExpectedChild(expected.interrupts, alpha),
            _ExpectedChild(expected.continuation, alpha),
        )

    def _check_event(
        self,
        judgment: _EventJudgment,
        expected: AngelicType,
        alpha: Mapping[str, str],
    ) -> bool:
        """按规范多元分支顺序检查 ODE 外部中断的 angelic type。"""

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
        alpha: Mapping[str, str],
        location: str,
    ) -> bool:
        """匹配 T-End 的 EmptyType 或递归体的类型变量终点。"""

        if isinstance(terminal, EmptyType) and isinstance(expected, EmptyType):
            return True
        if isinstance(terminal, TypeVar) and isinstance(expected, TypeVar):
            if alpha.get(terminal.name) == expected.name:
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
        """计算二元 Parallel 系统中的 Process 叶子数。"""

        if isinstance(system, Parallel):
            return TypeChecker._parallel_leaf_count(
                system.left
            ) + TypeChecker._parallel_leaf_count(system.right)
        return 1

    @staticmethod
    def _group_parallel_type(
        components: Sequence[ConfigurationType],
    ) -> ConfigurationType:
        """把一个或多个连续 Type 分量恢复为对应的系统子类型。"""

        if len(components) == 1:
            return components[0]
        return ParallelType(components)

    def _finish_mismatch_step(
        self,
        step: int,
        message: str,
        location: str,
    ) -> bool:
        """记录 Type 结构不匹配并完成当前规则步骤。"""

        self._mismatch(self.steps[step].rule, message, location)
        self._finish_step(step, "给定 Type 与规则结论不匹配", message)
        return False

    def _mismatch(
        self,
        rule: str,
        message: str,
        location: str = "judgment",
    ) -> bool:
        """记录可定位的用户 Type 结构错误并返回 False。"""

        self._type_mismatches.append(message)
        self._diagnose(Verdict.FALSE, message, rule, location)
        return False

    def _last_mismatch_message(self) -> str:
        """返回最后一条明确失败诊断，供公共异常摘要使用。"""

        return self._type_mismatches[-1] if self._type_mismatches else ""


__all__ = ["TypeChecker"]
