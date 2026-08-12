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
    """按词法作用域关联内部递归变量与用户 Type 变量。

    两侧名称分别映射到同一个不透明绑定身份，而不是直接互相映射字符串。
    因此内层 ``mu t.`` 即使复用外层名字 ``t``，也会在 ``supplied`` 中遮蔽
    外层身份；退出该子判断后，父环境仍保持原绑定。
    """

    internal: Mapping[str, object]
    supplied: Mapping[str, object]

    @classmethod
    def empty(cls) -> "_AlphaEnvironment":
        """建立不含递归绑定的根词法环境。"""

        return cls({}, {})

    def bind(self, internal_name: str, supplied_name: str) -> "_AlphaEnvironment":
        """为一对新进入的 ``mu`` 绑定建立唯一且可遮蔽的身份。"""

        identity = object()
        internal = dict(self.internal)
        supplied = dict(self.supplied)
        internal[internal_name] = identity
        supplied[supplied_name] = identity
        return _AlphaEnvironment(internal, supplied)

    def matches(self, internal_name: str, supplied_name: str) -> bool:
        """判断两个变量引用是否指向同一层词法递归绑定。"""

        internal_identity = self.internal.get(internal_name)
        return (
            internal_identity is not None
            and self.supplied.get(supplied_name) is internal_identity
        )


@dataclass(frozen=True, slots=True)
class _ExpectedChild:
    """一个子 judgment 及其必须匹配的用户 Type 和递归 alpha 环境。"""

    expected: ConfigurationType | AngelicType
    alpha: _AlphaEnvironment


@dataclass(frozen=True, slots=True)
class _ODECheckAttempt:
    """TypeChecker 对一条 ODE 候选规则的隔离匹配结果。"""

    mode: _ODETypeRule
    matched: bool
    verdict: Verdict
    obligations: tuple[Any, ...]
    diagnostics: tuple[Any, ...]
    steps: tuple[Any, ...]
    mismatches: tuple[str, ...]


class TypeChecker(Table2RuleEngine):
    """递归验证用户 Type 是否能成为给定 HCSP judgment 的结论。

    本类与 TypeConstructor 分别继承共享 ``Table2RuleEngine``；它只调用已审计的
    规则展开、符号执行和证明工具，不调用 TypeConstructor，也不调用规则的
    ``conclude`` 组合函数。
    """

    def check(self, request: TypeCheckingRequest) -> TypeCheckingReport:
        """以用户 Type 为结论递归检查全部适用规则并返回审计报告。

        方法先执行与 Constructor 相同的环境准备，再按源码结构拆解给定 Type。
        公式 ``FALSE`` 会使当前检查失败；``UNKNOWN`` 会保留证据并继续检查剩余
        结构，但最终报告不会把该 Type 判为通过。本方法不调用 Constructor，
        也不负责打印或构造公共异常。
        """

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
        # rule_t_parallel 已对共享 Gamma 和状态所有权做完整静态检查。发生错误时不应
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
        """按规则顺序判定公式，并递归消费给定 Type 的对应子树。

        ``FALSE`` 公式立即拒绝该规则；``UNKNOWN`` 只保留在证明证据中，结构递归
        继续进行。因而本方法返回真只表示当前规则没有确定失败，最终是否通过仍由
        全部证明义务的三值汇总决定。
        """

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
        alpha: _AlphaEnvironment,
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
        alpha: _AlphaEnvironment,
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
        alpha: _AlphaEnvironment,
    ) -> bool:
        """迭代消费线性规则前缀，并仅对真正分支结构进入分派函数。"""

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
                f"{self._describe_process_node(head)}；给定 Type = "
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
                    "给定 Type 与规则结论不匹配",
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
        """按递归返回顺序完成显式栈消费过的线性规则日志。"""

        for step, expansion in reversed(deferred):
            self._finish_step(
                step,
                "给定 Type 与规则结论匹配"
                if matched
                else "给定 Type 与规则结论不匹配",
                self._premise_summary(expansion),
            )

    def _check_process_node(
        self,
        judgment: _ProcessJudgment,
        expected: ProcessType,
        alpha: _AlphaEnvironment,
    ) -> bool:
        """按当前 Process 头结点拆解并检查给定 ProcessType。"""

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
            "给定 Type 与规则结论匹配" if matched else "给定 Type 与规则结论不匹配",
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
        """隔离检查一个 ODE 候选，随后回滚共享报告状态。"""

        obligation_start = len(self.obligations)
        diagnostic_start = len(self.diagnostics)
        step_start = len(self.steps)
        mismatch_start = len(self._type_mismatches)
        step = self._start_step(
            "T-ODE",
            judgment.context.location,
            f"按 {mode.value} 检查给定 Type = "
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
            "候选规则匹配" if matched else "候选规则不匹配",
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
        r"""对 ``ODE;skip`` 的 ``T-\unrhd``/``T-\unrhd'`` 分别检查。"""

        step = self._start_step(
            "T-ODE-Select",
            judgment.context.location,
            "ODE 后继为终端 skip：检查给定 Type 可由哪条规则推出",
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
            # 两条 ODE 规则的适用条件互斥。一个候选已证明接受给定 Type 时，
            # 另一个 UNKNOWN 候选只作为未选中的审计记录保存，不影响结论。
        elif len(proved) > 1:
            # Checker 的右侧 Type 已固定；若两条规则都证明并完整消费同一棵
            # supplied Type，它们在本次检查中给出等价结论。保留第一条即可，
            # 与 Constructor 对等价候选的规范化策略一致。
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
                f"给定 Type 由 {selected.mode.value} 接受",
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
        self._finish_step(step, "给定 Type 未通过 ODE 候选选择", summary)
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
        # 非 skip 后继或显式选择的 T-\unrhd' 都把 continuation 作为真实子
        # judgment；该真实后继本身允许是终端 skip。
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
        alpha: _AlphaEnvironment,
        location: str,
    ) -> bool:
        """匹配 T-End 的 EmptyType 或递归体的类型变量终点。"""

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
        """计算二元 Parallel 系统中的 Process 叶子数。"""

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
