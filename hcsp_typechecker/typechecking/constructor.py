r"""项目自有 HCSP 语言的行为类型构造器（TypeConstructor）。

核心数据流如下：

``TypeConstructionRequest -> ConclusionJudgment -> RuleExpansion(premises, conclude)
-> 按顺序立即判定 FormulaPremise + 递归求解 ChildJudgmentPremise
-> 由 conclude 组合候选类型 -> 汇总三值 TypeConstructionReport``。

推导与证明现在是完全顺序的：

1. 规则展开确定性地生成子 judgment、候选行为类型、符号状态和逻辑公式。
   特别地，T-Assign 在赋值前状态中计算右值，并用“旧路径条件 + 更新后的
   symbols”表示惰性最强后置状态；它不会留下一个未知 ``phi'`` 等待搜索。
2. 统一求解器遇到 FormulaPremise 时当场调用 Z3/KeYmaera X，将已判定
   ``ProofObligation`` 立即追加到审计记录。``false`` 会否证当前规则并终止
   该分支；``unknown`` 只表示证明尚未完成，推导会继续构造候选类型，最终
   报告则保留 ``unknown``，明确说明所得类型尚不可信。
3. 这种顺序性使 ``ODE; skip`` 能分别试用纯通信规则与自然超时规则。
   已证明候选优先；若非等价的另一候选仍未决，或者全部候选都未决，选择器
   会返回一个可审计的暂定类型并报告 ``unknown``。未选候选的公式仍保留但
   标记为 inactive，不直接污染所选推导的 verdict；候选唯一性问题由专门诊断
   记录。两条已证明规则若产生非等价类型，仍报告规则歧义而不返回类型。

这不是把 Python 的递归调用直接当作论文推导树。每条 ``rule_t_*`` 规则只分析
横线下方的结论 judgment，并显式返回横线上方的 premises；统一求解器按顺序
展开子 judgment，遇到公式 premise 就立即判定，最后调用规则的 ``conclude``
函数组合子结论。配置、系统、顺序进程和事件反应分别有自己的 judgment 类，
因此其结果层次也不会混淆。

Table 2 的 T-\sqcup 在项目的规范多元 Process AST 上写成以下带公共后继的
算法化形式：

``P_i;Q :: T_i (i in I)  /  (\bigsqcup_i P_i);Q :: \bigsqcup_i T_i``  [T-\sqcup]。

该规则直接匹配 ``InternalChoice(P_1, ..., P_n, continuation=Q)``。省略公共
后继时 Q 缺省为 ``Skip()``。规则把同一 Q 分别加到每个子 judgment，但运行时仍
只会执行被选中的一条分支；这也不需要定义
通用的类型级 T-Seq。

类型构造器只接受 :mod:`hcsp_typechecker.data_structures.process_ast.ast` 中定义的节点，并使用明确的
``isinstance`` 分派。外部对象不会因拥有同名字段而被隐式解释为 HCSP。
"""

from __future__ import annotations

from dataclasses import dataclass, field, replace
from enum import Enum
from math import inf
from typing import Any, Callable, Mapping, Sequence

from ..identifiers import is_hcsp_identifier
from ..data_structures.process_ast.expressions import Literal, ensure_expr
from .dl import (
    DLFormula,
    DLTranslationError,
    UntranslatedDLFormula,
    domain_formula,
    boundary_formula,
    safety_formula,
)
from ..data_structures.process_ast.ast import (
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
from ..data_structures.type_ast.ast import (
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
    make_external_choice,
    make_delay_type,
    types_equivalent,
)
from ..data_structures.type_construction.model import (
    BasicType,
    ChannelType,
    TypeConstructionReport,
    Configuration,
    ContinuousType,
    DLChecker,
    DLCheckResult,
    Diagnostic,
    DerivationStep,
    ParameterEnvironment,
    ProofObligation,
    TypeConstructionRequest,
    Verdict,
    GammaType,
    gamma_value_type,
    is_subtype,
    normalize_channel_type,
    normalize_gamma_type,
    normalize_type,
)


@dataclass
class _RecBinding:
    """源过程变量与新鲜行为类型变量之间的递归绑定。"""

    source_name: str
    type_var: TypeVar
    invariant: Any


@dataclass
class _Context:
    """一次控制流分支上的可变推导上下文。

    ``path`` 是当前符号状态必须满足的条件，``symbols`` 把程序变量映射到其
    当前 Z3 项，``rec_env`` 保存作用域内递归变量。``static_valid`` 记录初始
    路径是否通过 Bool 静态检查；失败上下文不能继续生成正式类型。分支规则
    必须 clone 上下文，以免一个分支的赋值泄漏到另一个分支。
    """

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
        """复制分支局部状态；只共享只读使用的通道环境。"""
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


@dataclass(frozen=True)
class _LazyAssignmentPostState:
    """T-Assign 为后继 judgment 确定性构造的惰性最强后置状态。

    经典最强后置条件会显式引入旧值并形成存在量词。本项目保存等价而更紧凑的
    符号执行表示：``path`` 仍约束赋值前符号，``post_context.symbols[target]``
    则改为在赋值前符号上求值的右值项。后继公式读取 ``target`` 时会自动完成
    Table 2 中的 ``{e/x}`` 替换。

    本对象是规则展开阶段已经算出的状态变换见证，不是未知谓词，也不是需要
    证明器求解的公式 premise；因此它绝不能作为证明请求。
    """

    target: str
    previous_term: Any
    assigned_term: Any
    pre_path: Any
    post_context: _Context


@dataclass(frozen=True)
class _ODEDLTerms:
    """一条 ODE 在入口符号快照下生成 dL 公式所需的 Z3 中间项。

    ``precondition`` 额外包含新鲜 ODE 分量与赋值后当前值之间的等式，以及
    当前 ODE 局部时钟的初始化等式 ``t=0``。``equations`` 则在用户方程后附加
    该时钟的 ``t'=1``；``clock`` 保存同一个 Z3 Real 项，供用户 ODE 公式、
    有限安全性和准确边界公式共同引用。``safety`` 保存 ODE 节点批注的安全
    目标；这是当前 ODE 必须证明的唯一轨迹性质，不能作为 dL 连续程序的演化域
    假设。Gamma 只登记允许出现的演化向量，不再提供第二份安全性质。
    ``domain`` 保留论文中的原始 ``B``，``domain_definedness`` 单独保存向量场
    和 B 的有定义条件，
    防止边界公式把“B 无定义”误当成合法的 ``not B``。这样时钟既真正属于
    这一个 ODE，又不会进入用户 Gamma。
    """

    precondition: Any
    equations: tuple[tuple[Any, Any], ...]
    domain: Any
    domain_definedness: Any
    safety: Any
    duration: Any | None
    clock: Any


class _ODEPostAssumption(str, Enum):
    """Table 2 在三种 ODE 后继 judgment 中允许使用的路径事实。"""

    DOMAIN_AND_SAFETY = "domain-and-safety"
    SAFETY = "safety"
    NOT_DOMAIN_AND_SAFETY = "not-domain-and-safety"


class _ODETypeRule(str, Enum):
    """``ODE; skip`` 可能适用的两个 Table 2 候选规则。"""

    COMMUNICATION_ONLY = "communication-only"
    NATURAL_TIMEOUT = "natural-timeout"


@dataclass(frozen=True)
class _ProofRequest:
    """一条将在当前推导位置立即判定的 Table 2 公式前提。

    请求中的公式已经完全具体化，不负责搜索 T-Assign 的未知 ``phi'``。
    FOL/dL 只需保存 ``obligation``；T-sigma 还冻结部分 state 和 Gamma symbols，
    供证明器构造并检查 ``|= phi[state]``。
    ``automatically_true`` 仅用于语法上恒真的 safety/domain。
    """

    obligation: ProofObligation
    state: Mapping[str, Any] | None = None
    symbols: Mapping[str, Any] | None = None
    automatically_true: bool = False


# --------------------------------------------------------------------------
# 显式推导树中“横线下方”的四类结论 judgment。它们只保存应用规则所需的
# 输入，不执行任何推导；相应 ``rule_t_*`` 方法负责把它们展开成 premises。
# --------------------------------------------------------------------------
@dataclass(frozen=True)
class _ConfigurationJudgment:
    """判断一个部分状态与系统组成的配置 ``<sigma, S>`` 的类型。"""

    state: Mapping[str, Any]
    system: Any
    context: _Context


@dataclass(frozen=True)
class _SystemJudgment:
    """判断系统层 ``S ::= P | S || S'`` 的配置类型。"""

    system: Any
    context: _Context


@dataclass(frozen=True)
class _ProcessJudgment:
    r"""判断规范化顺序节点列表及 terminal continuation 的过程类型。

    ``nodes[0]`` 是当前规则的进程头，``nodes[1:]`` 是普通 Sequence 的后继。
    ``InternalChoice`` 的公共后继不放在 nodes tail，而是直接保存在节点的
    ``continuation`` 字段中，由 T-\sqcup 分别交给两个分支子 judgment。
    """

    nodes: tuple[Process, ...]
    context: _Context
    terminal: ProcessType


@dataclass(frozen=True)
class _EventJudgment:
    """判断 ODE 通信中断反应 ``E`` 所产生的 angelic type。"""

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


# --------------------------------------------------------------------------
# 显式推导树中“横线上方”的两类 premise，以及一次规则展开的完整结果。
# FormulaPremise 由统一求解器当场判定；ChildJudgmentPremise 由同一求解器递归
# 展开。``conclude`` 只接收子 judgment 的结果，公式 premise 没有类型结果。
# --------------------------------------------------------------------------
@dataclass(frozen=True)
class _FormulaPremise:
    """一条按推导顺序立即判定的 state、FOL 或 dL 逻辑前提。"""

    request: _ProofRequest


@dataclass(frozen=True)
class _ChildJudgmentPremise:
    """一条必须递归构造候选类型的子 judgment 前提。"""

    judgment: _ChildJudgment


_Premise = _FormulaPremise | _ChildJudgmentPremise


@dataclass(frozen=True)
class _RuleExpansion:
    """某条 Table 2 规则的 premises 与由子结论组合父结论的方法。

    ``assignment_post_state`` 只可能由 T-Assign 提供。它记录规则展开时已经
    确定的惰性最强后置状态，供后继 judgment 和审计轨迹使用；它不是公式
    premise，统一求解器不会把它交给证明器。
    """

    rule: str
    premises: tuple[_Premise, ...]
    conclude: Callable[[tuple[Any, ...]], Any]
    assignment_post_state: _LazyAssignmentPostState | None = None


@dataclass(frozen=True)
class _ConstructionFailure:
    r"""表示某个进程片段无法按 Table 2 构造行为类型。

    这是类型构造器内部的控制状态，不继承 ``BehavioralType``，也不会进入正式的
    type AST。这样论文中的 ``BottomType``/``\bot`` 就不会再与实现错误、非法
    输入或缺失环境声明混为一谈。
    """


# 所有递归类型规则都返回正式行为类型或内部失败标记。失败标记使用单例，便于
# 组合规则用身份判断直接向外传播，而不构造含有伪造 ``BottomType`` 的父节点。
_CONSTRUCTION_FAILURE = _ConstructionFailure()
_ProcessConstructionResult = ProcessType | _ConstructionFailure
_ConfigurationConstructionResult = ConfigurationType | _ConstructionFailure


@dataclass(frozen=True)
class _ODECandidateAttempt:
    """一次 ODE 候选规则的隔离执行结果。"""

    mode: _ODETypeRule
    result: _ProcessConstructionResult
    verdict: Verdict
    obligations: tuple[ProofObligation, ...]
    diagnostics: tuple[Diagnostic, ...]
    steps: tuple[DerivationStep, ...]


class TypeConstructor:
    """按论文 Table 2 构造并验证 HCSP 行为类型。

    实例可重复调用 ``construct``；每次调用都会清空上次报告。ODE 的 safety/delay
    直接来自 AST 中唯一的 ``ODEAnnotation``，动态逻辑义务可委托
    ``dl_checker`` 外部后端。非项目 AST 会产生结构诊断，不参与兼容性推断。
    """

    def __init__(
        self,
        *,
        dl_checker: DLChecker | None = None,
        keymaerax_config: KeYmaeraXConfig | None = None,
        z3_timeout_ms: int = 5_000,
    ):
        """配置 KeYmaera X/自定义 dL 后端和每个 Z3 义务的超时。

        ``dl_checker`` 是测试或特殊部署使用的注入点；未提供时自动建立
        KeYmaera X 适配器，并从 ``KEYMAERAX_JAR``、``KEYMAERAX_JAVA`` 等
        环境变量探测工具。二者不能同时指定，避免同一义务的信任来源含糊。
        """
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

    def construct(
        self,
        request: TypeConstructionRequest,
    ) -> TypeConstructionReport:
        """执行一次完整类型构造并返回含全部证据的三值报告。

        普通建模/类型错误会转换为 ``Diagnostic(FALSE)``。``FALSE`` 前提会
        否证当前规则并停止相应推导分支；``UNKNOWN`` 证明结果会被完整记录，
        但不会阻止后续规则继续构造类型。因而报告可能同时包含非空
        ``constructed_type`` 和 ``UNKNOWN`` verdict：这表示“推导完成，但至少一条
        必要公式尚未证明”，该类型不能作为可信结论使用。
        """
        # TypeConstructor 实例可复用，但报告和新鲜名计数必须按构造请求隔离。
        self.obligations = []
        self.diagnostics = []
        self.steps = []
        self._fresh_counter = 0
        self._type_var_counter = 0

        # 在进入规则前集中规范化 Gamma/Theta，避免每条规则接受不同输入别名。
        try:
            invalid_gamma_names = {
                repr(name)
                for name in request.gamma
                if not is_hcsp_identifier(name)
            }
            if invalid_gamma_names:
                raise ValueError(
                    "Invalid Gamma names: "
                    + ", ".join(sorted(invalid_gamma_names))
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
                name: normalize_type(
                    value,
                    subject="Parameter declaration",
                )
                for name, value in request.parameters.declarations.items()
            }
            shared_names = set(gamma) & set(parameters)
            if shared_names:
                raise ValueError(
                    "Gamma and the shared parameter environment overlap: "
                    + ", ".join(sorted(shared_names))
                )
            theta = {
                self._channel_name(name): normalize_channel_type(value)
                for name, value in request.theta.items()
            }
        except (TypeError, ValueError) as exc:
            self._diagnose(Verdict.FALSE, f"Invalid typing environment: {exc}", "environment")
            return self._report(None, ())

        parameter_symbols: dict[str, Any] = {}
        parameter_translator = ExpressionTranslator(
            parameters,
            parameter_symbols,
            name_prefix="parameter__",
        )
        try:
            for name, value_type in parameters.items():
                parameter_translator.symbol(name, value_type)
            parameter_constraint_result = parameter_translator.boolean_result(
                request.parameters.constraint
            )
            parameter_condition = conjunction(
                self._defined_term(parameter_constraint_result),
                *(
                    constraint
                    for name, value_type in parameters.items()
                    for constraint in self._type_domain_constraints(
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
            return self._report(None, ())

        parameter_verdict, parameter_detail = self.proof_engine.satisfiable(
            parameter_condition
        )
        if parameter_verdict is Verdict.FALSE:
            self._diagnose(
                parameter_verdict,
                "Shared parameter constraint must be satisfiable: "
                + parameter_detail,
                "parameters",
            )
            return self._report(None, ())
        if parameter_verdict is Verdict.UNKNOWN:
            # 不可满足会让所有后续蕴含式真空成立，必须立即拒绝；求解器未能决定
            # 可满足性却不等于已经发现矛盾。保留符号约束继续推导，并让最终
            # UNKNOWN 诊断明确降低候选类型的可信度。
            self._diagnose(
                Verdict.UNKNOWN,
                "Shared parameter constraint satisfiability is unknown; "
                "type construction continues, but the constructed type is untrusted: "
                + parameter_detail,
                "parameters",
            )

        environment_step = self._start_step(
            "environment",
            "judgment",
            "规范化类型环境 Gamma 与 Theta",
            gamma=gamma,
            parameters=parameters,
            parameter_constraint=request.parameters.constraint,
            theta=theta,
            path=request.path_condition,
        )
        self._finish_step(
            environment_step,
            (
                "环境规范化完成；参数约束可满足性未决"
                if parameter_verdict is Verdict.UNKNOWN
                else "环境规范化成功"
            ),
            (
                "后续规则统一使用这里展示的基础类型和通道 refinement type。"
                + (
                    " 参数约束未被判定为不可满足，因此继续符号推导；"
                    "最终类型保持 UNKNOWN、不可信。"
                    if parameter_verdict is Verdict.UNKNOWN
                    else ""
                )
            ),
        )

        if not request.configurations:
            self._diagnose(
                Verdict.FALSE,
                "A construction request needs at least one configuration",
                "T-||",
            )
            return self._report(None, ())

        # 即使只有一个配置也经 T-|| 入口处理，以保持 Gamma 分区和 T-sigma 一致。
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
        # 内部失败状态绝不暴露为行为类型；公开报告用 None 保留失败分量的位置。
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

    # ------------------------------------------------------------------
    # Configuration and parallel rules
    # ------------------------------------------------------------------
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
        """[T-||] 把顶层判断展开为各配置的显式子 judgment。

        多配置判断若未显式给出局部 ``gamma``，会依据各进程/初始状态出现的
        变量投影全局环境。所有局部 Gamma 必须两两不交，并且其不交并集必须
        精确恢复判断入口的全局 Gamma；显式局部声明不得新增变量或改变类型。

        ``path_condition`` 是没有局部路径时的公共默认值。若配置显式给出局部
        路径，则所有配置都必须给出，并且外层只能保留默认 ``true``；此时论文
        [T-||] 结论中的路径由这些局部路径的合取确定，避免同时接受两套可能
        冲突的全局/局部前置条件。通道环境 ``Theta`` 按论文规则共享。
        """

        parallel_step = self._start_step(
            "T-||",
            "judgment",
            f"检查 {len(configurations)} 个配置并建立状态变量分区",
            gamma=gamma,
            parameters=parameters,
            parameter_constraint=parameter_constraint,
            theta=theta,
            path=default_path,
        )

        component_gammas: list[dict[str, GammaType]] = []
        valid_component_gammas: list[bool] = []
        used_domains: list[set[str]] = []
        # 第一遍只计算每个配置的局部变量域，随后才能进行两两不相交检查。
        for index, configuration in enumerate(configurations, start=1):
            if configuration.gamma is not None:
                try:
                    invalid_local_names = {
                        repr(name)
                        for name in configuration.gamma
                        if not is_hcsp_identifier(name)
                    }
                    if invalid_local_names:
                        raise ValueError(
                            "Invalid local Gamma names: "
                            + ", ".join(sorted(invalid_local_names))
                        )
                    component_gamma = {
                        name: normalize_gamma_type(
                            value,
                            subject="Gamma entry",
                        )
                        for name, value in configuration.gamma.items()
                    }
                    self._validate_continuous_vectors(component_gamma)
                    gamma_is_valid = True
                    extra_names = set(component_gamma) - set(gamma)
                    if extra_names:
                        self._diagnose(
                            Verdict.FALSE,
                            "Local Gamma contains variables absent from the global Gamma: "
                            + ", ".join(sorted(extra_names)),
                            "T-||",
                            f"K{index}",
                        )
                        gamma_is_valid = False
                    incompatible = {
                        name
                        for name, value_type in component_gamma.items()
                        if name in gamma and gamma[name] != value_type
                    }
                    if incompatible:
                        details = ", ".join(
                            f"{name} (global {gamma[name]}, local {component_gamma[name]})"
                            for name in sorted(incompatible)
                        )
                        self._diagnose(
                            Verdict.FALSE,
                            "Local Gamma changes global variable types: " + details,
                            "T-||",
                            f"K{index}",
                        )
                        gamma_is_valid = False
                except (TypeError, ValueError) as exc:
                    self._diagnose(
                        Verdict.FALSE,
                        f"Invalid Gamma for configuration {index}: {exc}",
                        "T-||",
                        f"K{index}",
                    )
                    component_gamma = {}
                    gamma_is_valid = False
            elif len(configurations) == 1:
                # 单配置无需分区，保留完整 Gamma 也允许路径条件使用辅助变量。
                component_gamma = dict(gamma)
                gamma_is_valid = True
            else:
                variables = self._process_vars(configuration.process) | set(configuration.state)
                # 共享参数可被所有配置读取，但不属于任何分量的可变 Gamma。
                variables -= set(parameters)
                # 独立 ContinuousType 项只跟随真正含相应 ODE 的配置；标量成员
                # 在 ODE 外仍是普通 Real，不会仅因读写其中一个成员就拖入整组。
                variables = self._expand_continuous_vector_domain(
                    gamma,
                    variables,
                    self._process_ode_vectors(configuration.process),
                )
                component_gamma = {
                    name: value_type for name, value_type in gamma.items() if name in variables
                }
                missing = (
                    variables
                    - set(component_gamma)
                    - self._input_bound_vars(configuration.process)
                )
                for name in sorted(missing):
                    self._diagnose(
                        Verdict.FALSE,
                        f"Variable {name!r} is used but not declared in Gamma",
                        "T-||",
                        f"K{index}",
                    )
                gamma_is_valid = not missing
            component_gammas.append(component_gamma)
            valid_component_gammas.append(gamma_is_valid)
            used_domains.append(set(component_gamma))

        # 论文要求并行分量的状态空间互不相交；共享通信通过 Theta 表达。
        for left in range(len(used_domains)):
            for right in range(left + 1, len(used_domains)):
                overlap = used_domains[left] & used_domains[right]
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

        # [T-||] 结论中的 Gamma 正是各前提 Gamma 的不交并集。只检查两两不交
        # 还不够，否则局部配置可以悄悄遗漏全局变量。前面的类型一致性检查已
        # 排除额外键和改型；这里再锁定并集的定义域。
        if all(valid_component_gammas):
            combined_domain = set().union(*used_domains) if used_domains else set()
            missing_from_components = set(gamma) - combined_domain
            if missing_from_components:
                self._diagnose(
                    Verdict.FALSE,
                    "Parallel component Gammas do not cover the global Gamma: "
                    + ", ".join(sorted(missing_from_components)),
                    "T-||",
                    "judgment",
                )
                valid_component_gammas = [False] * len(configurations)

        # ``path_condition`` 是默认路径，不是第二套可与局部路径并存的结论。
        # 全部局部路径存在时，外层 true 表示“由局部合取生成”；部分覆盖或同时
        # 给出非平凡全局路径都会使同一个 TypeConstructionRequest 含义不唯一。
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

        # 第二遍只构造子 judgment，不在规则函数内部递归求解。无效 Gamma 的
        # 分量不会产生伪造子判断，conclude 会在原位置恢复内部失败标记。
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
            """把有效配置子结论放回原分量位置并完成顶层 T-|| 轨迹。"""

            child_iterator = iter(children)
            types: list[_ConfigurationConstructionResult] = [
                next(child_iterator) if valid else _CONSTRUCTION_FAILURE
                for valid in validity
            ]
            readable_types = ", ".join(
                "(failed)" if isinstance(item, _ConstructionFailure) else str(item)
                for item in types
            )
            self._finish_step(
                parallel_step,
                f"分量类型 = [{readable_types}]",
                self._premise_summary(expansion)
                + " 显式子 judgments 已求解；各配置共享 Theta，状态 Gamma 分区互不相交。",
            )
            return types

        expansion = _RuleExpansion("T-||", tuple(premises), conclude)
        return expansion

    def rule_t_sigma(
        self,
        judgment: _ConfigurationJudgment,
    ) -> _RuleExpansion:
        """[T-sigma] 展开为 ``|= phi[sigma]`` 和系统类型子 judgment。

        Gamma 是状态变量的类型声明环境，因此只要求
        ``dom(sigma) subseteq dom(Gamma)``。Gamma 中未被 sigma 赋值的变量继续
        留在替换后的公式里；sigma 中未由 Gamma 声明的变量则没有类型解释，
        属于静态错误，不能进入证明器或产生正式候选类型。
        """

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
                "Initial state contains variables not declared in the local "
                "Gamma: "
                + names,
                "T-sigma",
                context.location,
            )
            return _RuleExpansion(
                "T-sigma",
                (),
                lambda _children: _CONSTRUCTION_FAILURE,
            )
        # 论文配置叶子严格是 (sigma, P)，而不是 (sigma, S1 || S2)。项目仍为
        # 最常见的无状态协议保留 ``Configuration({}, Parallel(...))`` 便捷写法：
        # 在空 Gamma、空 state 和 true 路径下，拆成左右空上下文不会丢失任何
        # 状态信息。只要存在状态或路径约束，就必须由调用方提交多个显式
        # Configuration，使每个叶子分别经过 T-sigma 和顶层 T-||。
        if isinstance(judgment.system, Parallel) and (
            judgment.state
            or context.gamma
            or not self._is_true(context.path)
        ):
            self._diagnose(
                Verdict.FALSE,
                "A stateful Parallel system must be supplied as separate "
                "Configuration leaves with disjoint local Gammas and paths",
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

    # ------------------------------------------------------------------
    # Structural process rules
    # ------------------------------------------------------------------
    def _solve_rule_expansion(
        self,
        expansion: _RuleExpansion,
    ) -> Any:
        """按写出顺序求解一条规则的全部 premises。

        ``false`` 表示公式前提已被反例否证，会立即返回内部失败标记；
        ``unknown`` 仅表示当前证明器尚不能建立该前提，证明义务已经记录后仍会
        继续求解剩余 premise，并允许 ``conclude`` 构造候选类型。最终报告通过
        UNKNOWN verdict 告知调用者该类型尚不可信。子 judgment 的结构/静态
        失败仍会停止后续兄弟 premise；此时仅用失败占位补齐 ``conclude`` 所需
        的子结论形状，使顶层并行报告能显示此前完成的配置分量，而不会构造
        含错误子树的父行为类型。
        """

        child_results: list[Any] = []
        for index, premise in enumerate(expansion.premises):
            if isinstance(premise, _FormulaPremise):
                decided = self._decide_proof(premise.request)
                if decided.verdict is Verdict.FALSE:
                    return _CONSTRUCTION_FAILURE
            elif isinstance(premise, _ChildJudgmentPremise):
                child_result = self._solve_child_judgment(premise.judgment)
                child_results.append(child_result)
                if isinstance(child_result, _ConstructionFailure):
                    child_results.extend(
                        _CONSTRUCTION_FAILURE
                        for remaining in expansion.premises[index + 1 :]
                        if isinstance(remaining, _ChildJudgmentPremise)
                    )
                    return expansion.conclude(tuple(child_results))
            else:  # pragma: no cover - _Premise 是封闭的内部联合类型
                raise TypeError(
                    f"Unsupported premise in {expansion.rule}: "
                    f"{type(premise).__name__}"
                )
        return expansion.conclude(tuple(child_results))

    def _solve_child_judgment(self, judgment: _ChildJudgment) -> Any:
        """按 judgment 类别分派；这是推导树递归求解的唯一入口。"""

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
        """求解 ``<sigma,S>``；[T-sigma] 本身只负责产生 premises。"""

        context = judgment.context
        step = self._start_step(
            "T-sigma",
            context.location,
            f"检查初始状态 sigma = {dict(judgment.state)!r}",
            context=context,
        )
        expansion = self.rule_t_sigma(judgment)
        result = self._solve_rule_expansion(expansion)
        result_text = (
            "推导失败，未构造正式配置类型"
            if isinstance(result, _ConstructionFailure)
            else f"状态前提已当场判定；候选类型 = {result}"
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
        """按 ``S ::= P | S || S'`` 求解显式系统 judgment。"""

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
        """展开并求解一个顺序进程 judgment。"""

        nodes = judgment.nodes
        context = judgment.context
        if not nodes:
            end_step = self._start_step(
                "T-End",
                context.location,
                "顺序后继为空，使用终止类型 0",
                context=context,
            )
            expansion = self.rule_t_end(judgment)
            result = self._solve_rule_expansion(expansion)
            self._finish_step(
                end_step,
                f"候选类型 = {result}",
                self._premise_summary(expansion),
            )
            return result

        head = nodes[0]

        # Table 2 严格区分终端 ``skip`` 的 T-End 与中间 ``skip # P`` 的
        # T-Skip。空 nodes 则是 ch!/assert/assign 等前缀剥离后隐含的终端 skip。
        terminal_skip = isinstance(head, Skip) and len(nodes) == 1
        rule = "T-End" if terminal_skip else self._rule_name(head)
        rule_step = self._start_step(
            rule,
            context.location,
            self._describe_process_node(head),
            context=context,
        )

        # 严格 isinstance 分派是本项目语言的唯一节点识别机制。
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
            result_text = "推导失败，未构造正式行为类型"
        else:
            result_text = f"候选类型 = {result}"
        self._finish_step(
            rule_step,
            result_text,
            self._premise_summary(expansion)
            + " "
            + self._rule_explanation(rule),
        )
        return result

    def rule_t_end(self, judgment: _ProcessJudgment) -> _RuleExpansion:
        """[T-End] 直接把终端 ``skip``（含隐式终端）推导为 ``0``。

        显式 ``Skip`` 必须是当前节点序列的最后一项；空节点序列表示通信、赋值、
        断言等前缀省略书写的终端 ``skip``。含后继的 ``skip # P`` 只能由
        :meth:`rule_t_skip` 处理。
        """

        return _RuleExpansion(
            "T-End",
            (),
            lambda _children: judgment.terminal,
        )

    def rule_t_skip(
        self,
        judgment: _ProcessJudgment,
    ) -> _RuleExpansion:
        """[T-Skip] 唯一 premise 是同一上下文中的顺序后继 judgment。"""

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
        """[T-Assert] 生成 ``phi => B``，并在原路径条件下继续。

        Assert 是验证点而非 Assume，因此成功后不会把 ``B`` 加入后继路径。
        若条件本身不是 Bool，则静态 premise 失败并且不推导后继类型。
        """

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
        """[T-Assign] 按当前 Table 2 的替换前提更新符号状态。

        新规则写作 ``phi -> phi'{e/x}``。本方法先在赋值前状态中计算右值，再由
        ``_lazy_assignment_post_state`` 确定性地产生后继状态。后继对 ``x`` 的
        每次读取都会自动形成相同的 ``{e/x}`` 替换；顺序证明器只判定右值
        有定义性等已经具体化的公式，不搜索或综合未知谓词 ``phi'``。右值基础
        类型与左值声明不兼容时，本规则直接失败，不保留终端候选类型。
        """

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
            # 右值必须完全在赋值前状态中求值；尤其 x := x + 1 的右侧 x 不能
            # 被误读成赋值后的 x。
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
            # phi' 在这里由赋值语义唯一确定；不把未知谓词留给证明器。
            post_state = self._lazy_assignment_post_state(
                context,
                target,
                result.term,
            )
            next_context = post_state.post_context
            # Table 2 把 ``phi => phi'{e/x}`` 明确列为逻辑 premise。惰性
            # 后状态以旧 path 和新 symbols 表示 phi'，将它沿本次赋值拉回
            # 赋值前状态后正好得到原 path。因此这里仍登记一条具体、按构造
            # 成立的公式证据；证明器只判定该公式，不综合未知 phi'。
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
        """[T-If] 检查论文中的二元 ``if B then P else P'``。

        then 分支使用 ``phi ∧ B``，else 分支使用 ``phi ∧ ¬B``；两个分支分别
        克隆符号上下文，避免一个分支的赋值影响另一个分支。
        """

        node = judgment.nodes[0]
        tail = judgment.nodes[1:]
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
            """把 then/else 两个子类型组合成内部选择类型。"""

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
        """[T-In] 逐槽扩展 ``Gamma``，并把联合精化加入 ``phi``。

        每个接收值使用独立新鲜符号，不能沿用输入前变量的旧符号值。若 xi
        未声明，T-In 将其加入局部环境；若已经声明，则逐槽检查类型兼容并
        覆盖当前值。最后同时执行 ``phi{x1/eta1,...,xn/etan}``。已有目标与槽位
        类型不兼容时，输入前缀及其后继都不形成正式类型。
        """

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

        # 输入建立一个带新接收值的顺序后继上下文；兄弟分支仍保留原上下文。
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
                if existing is not None and not (
                    is_subtype(existing, value_type)
                    or is_subtype(value_type, existing)
                ):
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
                # 输入只建立或更新标量值项；独立 ODE 向量声明不会被通信改写。
                next_context.gamma[name] = (
                    value_type if existing_entry is None else existing_entry
                )

            translator = self._translator(next_context)
            for variable, value_type in zip(
                node.targets,
                channel_type.value_types,
            ):
                name = lvalue_name(variable)
                # 同一通信动作共享计数后缀，但变量名不同，所得符号仍两两独立。
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
            """在已求得的 continuation 外层添加输入通信前缀。"""

            continuation = children[0]
            if isinstance(continuation, _ConstructionFailure):
                return _CONSTRUCTION_FAILURE
            # ``ch?`` 本身不是过程类型 T，而是中断类型 A 中的一个分支。
            # [T-In] 使用论文的缩写展开：delay(infinity) unrhd (ch?.T) ▷ bottom。
            return InfiniteDelayType(InputType(channel, continuation))

        return _RuleExpansion("T-In", (premise,), conclude)

    def rule_t_out(
        self,
        judgment: _ProcessJudgment,
    ) -> _RuleExpansion:
        """[T-Out] 逐槽检查类型并证明联合 refinement 的实例。

        输入规则可以假设通道精化；输出规则必须证明自己满足精化，这一方向
        差异是通信安全性的关键。多槽替换一次完成：
        ``phi => refinement[e1/eta1,...,en/etan]``。任一载荷的静态基础类型不满足
        槽位声明时，规则在生成 refinement 证明义务之前失败。
        """

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
            """在已求得的 continuation 外层添加输出通信前缀。"""

            continuation = children[0]
            if isinstance(continuation, _ConstructionFailure):
                return _CONSTRUCTION_FAILURE
            # 与 [T-In] 对称：裸输出动作是无穷等待的过程类型，而非裸 A。
            return InfiniteDelayType(OutputType(channel, continuation))

        return _RuleExpansion("T-Out", tuple(premises), conclude)

    def rule_t_internal_choice(
        self,
        judgment: _ProcessJudgment,
    ) -> _RuleExpansion:
        r"""[T-sqcup] 分别检查多元内部选择各分支的完整行为。

        将节点的显式 ``continuation`` 同时加到每个子 judgment，得到所有
        ``P_i;Q`` 的类型后组合为 ``T_1 \sqcup ... \sqcup T_n``。省略公共后继时 Q
        已由 AST 构造器缺省为 ``Skip()``。规则只共享推导上的后继，不表示
        运行时同时执行全部分支。
        """

        node = judgment.nodes[0]
        # 规范 AST 中当前选择自己持有 Q；``judgment.nodes[1:]`` 是从外层
        # judgment 传入的合法顺序尾。两部分都必须依次附加到每个分支。
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
            """把全部分支子类型组合成内部非确定选择类型。"""
            if any(isinstance(child, _ConstructionFailure) for child in children):
                return _CONSTRUCTION_FAILURE
            return InternalChoiceType(children)

        return _RuleExpansion("T-sqcup", premises, conclude)

    def rule_t_external_choice(
        self,
        judgment: _EventJudgment,
    ) -> _RuleExpansion:
        """[T-&] 把多元事件反应展开为每个通信分支的子 judgment。

        ``EventChoice`` 的构造器已经保证每个分支由输入或输出守卫。论文语法
        没有要求通道名前缀唯一，因此重复前缀仍按不同分支保留。
        """

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
            """把全部通信分支合成规范 angelic type。"""
            if any(isinstance(child, _ConstructionFailure) for child in children):
                return _CONSTRUCTION_FAILURE
            # 每个事件分支以一次输入/输出动作开头。T-In/T-Out 现在严格
            # 返回展开后的 ``InfiniteDelayType``；在事件表的 A 位置重新
            # 取出其中唯一的通信前缀，避免把 A 与 T 混为同一个 AST 范畴。
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
        """求解一个显式事件反应 judgment，并记录其 premises 与结果。"""

        node = judgment.reaction
        context = judgment.context
        event_step = self._start_step(
            "T-&",
            context.location,
            (
                "empty event reaction"
                if isinstance(node, EmptyEvent)
                else f"事件分支表（{len(node.branches)} 个通信分支）"
                if isinstance(node, EventChoice)
                else repr(node)
            ),
            context=context,
        )
        expansion = self.rule_t_external_choice(judgment)
        result = self._solve_rule_expansion(expansion)
        if isinstance(result, _ConstructionFailure):
            result_text = "推导失败，事件反应没有正式 angelic type"
        elif isinstance(node, EmptyEvent):
            result_text = f"事件选择递归结束 = {result}"
        else:
            result_text = f"事件选择类型 = {result}"
        self._finish_step(
            event_step,
            result_text,
            self._premise_summary(expansion),
        )
        return result

    # ------------------------------------------------------------------
    # ODE rules and externally discharged dL obligations
    # ------------------------------------------------------------------
    @staticmethod
    def _needs_ode_skip_rule_selection(
        judgment: _ProcessJudgment,
    ) -> bool:
        """仅识别有限 ODE 后精确只有一个终端 ``skip`` 的重叠形状。"""

        if len(judgment.nodes) != 2 or not isinstance(
            judgment.nodes[1], Skip
        ):
            return False
        node = judgment.nodes[0]
        if not isinstance(node, ODE):
            return False
        return not (
            isinstance(node.annotation.delay, float)
            and node.annotation.delay == inf
        )

    def _attempt_ode_candidate(
        self,
        judgment: _ProcessJudgment,
        mode: _ODETypeRule,
    ) -> _ODECandidateAttempt:
        """隔离执行一个 ODE 候选，返回证据后回滚公开报告列表。"""

        obligation_start = len(self.obligations)
        diagnostic_start = len(self.diagnostics)
        step_start = len(self.steps)
        context = judgment.context
        candidate_step = self._start_step(
            "T-ODE",
            context.location,
            f"试用 ODE 候选规则 {mode.value}",
            context=context,
        )
        expansion = self.rule_t_ode(judgment, candidate=mode)
        result = self._solve_rule_expansion(expansion)
        self._finish_step(
            candidate_step,
            (
                "候选未构造正式类型"
                if isinstance(result, _ConstructionFailure)
                else f"候选类型 = {result}"
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
        if (
            isinstance(result, _ConstructionFailure)
            and Verdict.FALSE not in verdict_inputs
        ):
            # UNKNOWN 已不再使规则求解停止。因此候选仍返回失败标记时，必然还
            # 存在一个公式结论之外的结构/静态失败；即使此前也记录了 UNKNOWN，
            # 该候选仍应按 FALSE 排除，而不能伪装成“只有证明尚未完成”。
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
        """判断一组可行候选是否只是同一类型的等价推导。"""

        if not attempts:
            return False
        first = attempts[0].result
        if isinstance(first, _ConstructionFailure):
            return False
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
        """保留全部候选公式，但只让被选规则参与最终 verdict。"""

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
        """生成用于选择步骤的单行候选证据摘要。"""

        proofs = ", ".join(
            f"{item.rule}={item.verdict.value}"
            for item in attempt.obligations
        ) or "no formulas"
        constructed = (
            "failure"
            if isinstance(attempt.result, _ConstructionFailure)
            else str(attempt.result)
        )
        return (
            f"{attempt.mode.value}: verdict={attempt.verdict.value}, "
            f"type={constructed}, proofs=[{proofs}]"
        )

    def _solve_ode_skip_rule_candidates(
        self,
        judgment: _ProcessJudgment,
    ) -> _ProcessConstructionResult:
        """顺序试用 ``ODE;skip`` 的两条规则并选择可审计的候选类型。

        先在已经证明为 TRUE 的候选中按类型等价类选择。两个已证候选若非等价
        则属于真实规则歧义，不返回类型。一条候选已证、另一条非等价候选仍为
        UNKNOWN 时，保留已证候选作为暂定类型，但整体仍为 UNKNOWN，因为规则
        唯一性尚未建立；若未决候选产生的是等价类型，则不影响已证结论。

        没有已证类型时，只要至少一个 UNKNOWN 候选完成了结构推导，就按
        ``natural-timeout``、``communication-only`` 的固定顺序选择。前者优先
        是因为当前 AST 明确含有顺序后继 ``skip``，自然超时规则会保留这个后继；
        这只是未验证临时候选的确定性优先级，不是新增的 Table 2 规则，UNKNOWN
        诊断会明确禁止把它当作已证类型。两个候选都被 FALSE 排除时才报告无法
        推导。
        """

        context = judgment.context
        selection_step = self._start_step(
            "T-ODE-Select",
            context.location,
            "ODE 后继为终端 skip：顺序试用两条 Table 2 规则",
            context=context,
        )
        attempts = tuple(
            self._attempt_ode_candidate(judgment, mode)
            for mode in (
                _ODETypeRule.COMMUNICATION_ONLY,
                _ODETypeRule.NATURAL_TIMEOUT,
            )
        )

        proved = tuple(
            attempt
            for attempt in attempts
            if attempt.verdict == Verdict.TRUE
            and not isinstance(attempt.result, _ConstructionFailure)
        )
        unknown = tuple(
            attempt
            for attempt in attempts
            if attempt.verdict == Verdict.UNKNOWN
            and not isinstance(attempt.result, _ConstructionFailure)
        )

        selected: _ODECandidateAttempt | None = None
        selection_is_untrusted = False
        untrusted_reason = ""
        proved_are_ambiguous = (
            len(proved) > 1
            and not self._ode_attempts_have_equivalent_types(proved)
        )
        if proved and not proved_are_ambiguous:
            selected = proved[0]
            non_equivalent_unknown = tuple(
                attempt
                for attempt in unknown
                if not types_equivalent(selected.result, attempt.result)
            )
            if non_equivalent_unknown:
                # 已证明候选可以提供有用的暂定类型，但另一条非等价规则尚未被
                # 排除，因此不能把“存在一棵已证推导”误报成“结论已经唯一”。
                selection_is_untrusted = True
                unresolved = ", ".join(
                    attempt.mode.value for attempt in non_equivalent_unknown
                )
                untrusted_reason = (
                    "The selected ODE rule is proved, but the non-equivalent "
                    f"candidate(s) {unresolved} remain unknown; rule uniqueness "
                    "has not been established"
                )
        elif not proved and unknown:
            priority = {
                _ODETypeRule.NATURAL_TIMEOUT: 0,
                _ODETypeRule.COMMUNICATION_ONLY: 1,
            }
            selected = min(unknown, key=lambda attempt: priority[attempt.mode])
            selection_is_untrusted = True
            untrusted_reason = (
                "No ODE rule candidate has been proved; the deterministic "
                f"temporary candidate {selected.mode.value} was retained"
            )

        self._commit_ode_candidate_evidence(attempts, selected)
        summaries = "; ".join(
            self._ode_attempt_summary(attempt) for attempt in attempts
        )

        # 候选隔离执行时会暂存结构诊断。选中某一候选时只提交该候选的诊断；
        # 若没有候选可选，则仍须把真正导致失败的结构原因带回公开报告，否则用户
        # 只能看到笼统的“两个规则都不可用”，无法定位未声明变量等源程序错误。
        if selected is None:
            seen_diagnostics: set[tuple[Verdict, str, str, str]] = set()
            for attempt in attempts:
                for diagnostic in attempt.diagnostics:
                    key = (
                        diagnostic.verdict,
                        diagnostic.message,
                        diagnostic.rule,
                        diagnostic.location,
                    )
                    if key not in seen_diagnostics:
                        self.diagnostics.append(diagnostic)
                        seen_diagnostics.add(key)

        if selected is not None:
            if selection_is_untrusted:
                self._diagnose(
                    Verdict.UNKNOWN,
                    untrusted_reason
                    + "; type construction can complete, but the retained type is "
                    "untrusted until all competing proof obligations are resolved",
                    "T-ODE-Select",
                    context.location,
                )
            self._finish_step(
                selection_step,
                (
                    f"保留未证候选 {selected.mode.value}: {selected.result}"
                    if selection_is_untrusted
                    else f"选中已证候选 {selected.mode.value}: {selected.result}"
                ),
                summaries,
            )
            return selected.result

        if proved_are_ambiguous:
            self._diagnose(
                Verdict.UNKNOWN,
                "Both ODE rules were proved but generated non-equivalent types; "
                "the Table 2 derivation is ambiguous",
                "T-ODE-Select",
                context.location,
            )
            result_text = "两个已证候选类型不等价，无法唯一选择"
        else:
            self._diagnose(
                Verdict.FALSE,
                "Neither ODE rule satisfies all of its Table 2 premises",
                "T-ODE-Select",
                context.location,
            )
            result_text = "两条 ODE 候选规则均不可用"
        self._finish_step(selection_step, result_text, summaries)
        return _CONSTRUCTION_FAILURE

    @staticmethod
    def _validate_continuous_vectors(gamma: Mapping[str, GammaType]) -> None:
        """验证每个独立 ODE 向量声明的成员都是已声明 Real 标量。

        ``ContinuousType`` 所在的 Gamma 键只是向量声明名，不是状态变量。
        声明中的每个成员必须在另一个 Gamma 项中具有 ``BasicType.REAL``；不再
        把同一个 ContinuousType 复制到各标量键。多个向量声明可以共享成员。
        """

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
        """投影 Gamma 中真正具有当前标量值的 BasicType 项。"""

        return {
            name: declaration
            for name, declaration in gamma.items()
            if isinstance(declaration, BasicType)
        }

    @staticmethod
    def _expand_continuous_vector_domain(
        gamma: Mapping[str, GammaType],
        names: set[str],
        ode_vectors: set[frozenset[str]],
    ) -> set[str]:
        """把当前配置实际使用的 ODE 向量声明加入自动 Gamma 分区。"""

        expanded = set(names)
        for declaration_name, declaration in gamma.items():
            if not isinstance(declaration, ContinuousType):
                continue
            members = frozenset(declaration.variables)
            if members in ode_vectors:
                expanded.add(declaration_name)
        return expanded

    @staticmethod
    def _declares_continuous_vector(
        gamma: Mapping[str, GammaType],
        evolved: Sequence[str],
    ) -> bool:
        """判断 Gamma 是否登记了当前 ODE 的完整演化变量集合。

        ``evolved`` 只来自用户写出的 ``node.eqs``，不含随后追加到 dL 程序的
        隐式局部时钟。方程顺序不构成向量声明语义，重复左端变量已由 T-ODE
        的独立静态检查拒绝。
        """

        ode_vector = frozenset(evolved)
        return any(
            isinstance(declaration, ContinuousType)
            and frozenset(declaration.variables) == ode_vector
            for declaration in gamma.values()
        )

    def rule_t_ode(self, judgment: _ProcessJudgment) -> _RuleExpansion:
        """实现带 ``safety``/``delay`` 批注的连续演化类型规则。

        原始 ODE 语法仍由 ``eqs``、``constraint`` 和 ``interrupts`` 构成；
        Section 4.3 的两个额外输入只从 ``node.annotation`` 读取。延迟 ``d``
        与推导出的 ``A/T`` 由 ``make_delay_type`` 统一构造成有限或无穷时延类型。
        ``d=infinity`` 没有超时迁移，其不可达 fallback 固定为 bottom。dL 安全目标只检查节点自己的
        ``annotation.safety``。Gamma 中的 ODE 分量本身声明为普通 ``Real``，另
        由一个独立 ``ContinuousType`` 项登记允许出现的完整演化变量集合；用户
        左侧必须与其中一个集合精确相等，但方程书写顺序不影响匹配。隐式局部
        时钟不参与向量比较。

        没有后继时使用纯通信中断规则；有非终端后继时使用带 fallback
        规则。唯一重叠形状 ``ODE; skip`` 由外层顺序选择器两条规则都试用，
        本方法的 ``candidate`` 参数只在该隔离尝试中指定当前规则。

        ``node.local_clock`` 由 ODE 构造器自动建立，不要求用户放入 Gamma 或
        初始状态。ODE 方程右端、演化域和节点 safety 中的 ``t`` 在局部作用域
        内绑定到这个时钟。生成 dL 前提时，它
        被实体化为本 ODE 独占的新鲜 Real：
        入口自动加入 ``t=0``，连续方程自动加入 ``t'=1``；离开 ODE 后即被丢弃。
        用户演化向量未登记，或导数、演化域、safety 的静态类型失败时，不生成
        任何时延类型；只有静态前提成立后才建立 dL 证明义务。
        """

        node = judgment.nodes[0]
        tail = judgment.nodes[1:]
        context = judgment.context
        annotation = node.annotation
        equations = node.eqs
        evolved: list[str] = []
        translator = self._translator(context)
        # 这里只为表达式静态检查创建一个临时局部 Real。正式 dL 义务稍后由
        # _ode_dl_terms 创建自己的时钟快照；两者都通过 local_symbols 让源名
        # t 遮蔽同名的普通 Gamma 变量，而不修改持久上下文。
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
        # 每个演化变量只能出现一次，并且其当前值必须在 Gamma 中声明为 Real。
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
            # 偏函数侧条件按其来源保存：源演化域和向量场的侧条件仍由相应
            # Table 2 前提检查；节点 safety 的侧条件属于当前 ODE 的待证安全目标。
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

        # ODEAnnotation 已在 AST 构造边界保证 d 是非负有理数或正无穷。
        # 正无穷稍后走“永不超时”分支，不生成自然结束 fallback。
        duration_annotation = annotation.delay
        if isinstance(duration_annotation, Literal):
            # ODEAnnotation 已把有限 d 规范成 Literal(Fraction(...))；类型 AST
            # 只保存数值本身，不把表达式 AST 混入行为类型层。
            duration: Any = duration_annotation.value
        else:
            # ODEAnnotation 的另一个合法结果只能是正无穷 math.inf。
            duration = duration_annotation
        infinite_duration = isinstance(duration, float) and duration == inf
        # 有限 ODE 总有自然到时后继。若源程序在此结束，空节点序列会由 T-End
        # 直接构造 EmptyType；不再人为补造 ``Skip()``，以免把“空通信行为”
        # 错写为某个过程语法糖。正无穷时延没有到时迁移。
        communication_rule = infinite_duration

        # 为 dL 模态建立独立入口快照。它不改变 HCSP AST，也不改变离开 ODE
        # 后的符号状态；仅用于把当前赋值替换后的状态正确嵌入连续演化公式。
        try:
            dl_terms = self._ode_dl_terms(node, context, evolved)
            dl_term_error: str | None = None
        except (ExpressionError, DLTranslationError) as exc:
            dl_terms = None
            dl_term_error = str(exc)

        # 只有节点批注 safety（连同导数有定义条件）为 true 时才可本地直接通过；
        # Gamma 只登记向量，不再向这条逻辑目标追加性质。
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

        # 没有顺序后继时采用只含通信中断的规则；无限 delay 即使写有 tail，
        # 自然超时也永远不会发生。Table 2 在这两种情况下要求在未把 B 预设为
        # 真的动力系统中证明 B 保持，即 ``pre -> [F]B``；
        # 若把待验证的性质写进程序域，证明义务会被错误削弱。
        if communication_rule:
            # 演化域为 true 时，这项前提可在本地直接判真；否则必须把完整域
            # 交给证明器。
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

        # Table 2 只有“有限 d 且存在自然后继 T”的规则需要精确边界 premise。
        # 纯通信中断形式 ``delay(d) \unrhd A`` 的 d 是外部批注，不声称存在一条
        # 自然超时迁移，因此不能额外强加“在 t=d 离开 B”的 boundary 义务。
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
            # 无限演化没有自然到时后继；tail 仍传给通信分支，因为它可能被通信
            # 提前中断，分支 continuation 完成后仍应执行外层 tail。
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
                    tail,
                    interrupt_context,
                    judgment.terminal,
                )
            )

            def conclude_without_timeout(
                children: tuple[Any, ...],
            ) -> _ProcessConstructionResult:
                """组合无自然超时分支的 ODE 通信反应。"""

                choices = children[0]
                if isinstance(choices, _ConstructionFailure):
                    return _CONSTRUCTION_FAILURE
                # 正无穷 delay 的自然到时后继固定为不可达的 BottomType；AST 用
                # InfiniteDelayType 显式记录该时延，而不把它误降为裸 A。
                return make_delay_type(duration, choices, EmptyType())

            return _RuleExpansion(
                "T-ODE",
                tuple(premises),
                conclude_without_timeout,
            )

        # 运行到这里必然是已选自然超时规则：自然到时后把 tail 推导为
        # timed type 的 fallback；通信中断分支也在自己的 continuation 后接 tail。
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
        # 当前 Table 2 在通信中断分支只允许使用 safety；自然结束分支则使用
        # ``not B and safety``。不能把纯通信规则的 ``B and safety`` 搬到这里。
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
            """组合 ODE 通信中断子类型与有限时延自然后继子类型。"""

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
        """在 ODE 入口建立可用于 dL 模态的符号快照。

        离散赋值规则把 ``symbols[x]`` 直接替换成右值项；而 ODE 左端必须是
        KeYmaera X 的变量。这里为每个演化变量创建新鲜入口符号 ``x0``，并把
        ``x0 = 当前值`` 加入前置条件。随后为 ``node.local_clock`` 创建一个
        新鲜 Real 符号，把 ``t=0`` 加入前置条件并把 ``t'=1`` 加入方程。ODE
        方程右端、域和安全式中的源名 ``t`` 都绑定到这个符号，保证它们读取
        同一个当前演化时间，而该局部时钟不会泄漏到后继上下文。
        """

        self._fresh_counter += 1
        ode_symbols = dict(context.symbols)
        value_gamma = self._value_gamma(context.gamma)
        value_environment = {**context.parameters, **value_gamma}
        snapshot_translator = ExpressionTranslator(
            value_environment,
            ode_symbols,
        )
        equalities: list[Any] = []

        # ``evolved`` 可能因前面的结构错误含重复名；dL 公式只为每个名字建一次
        # 快照，结构错误本身已经由 T-ODE 诊断为 FALSE。
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
        # ``@`` 不是项目变量 ASCII IDENT 的合法首字符，所以用户
        # 不可能在 HCSP 表达式中捕获这个内部名称。每次调用的计数后缀又保证
        # 不同 ODE 实例（含并行分量）获得不同的逻辑符号。
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
            # 重复和无效变量已在结构层诊断；这里拒绝生成可能含歧义的公式。
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
        """调用一个严格 dL 构造器，并把不支持的子集保守记录为 UNKNOWN。"""

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
        """为 ODE 结束/中断后创建新的符号状态与路径条件。

        所有演化变量都换成新鲜符号，因为离开连续演化时其数值通常无法由简单
        代入得到。当前 Table 2 对三种后继给出不同前置条件：纯通信规则的事件
        后继使用 ``B & safety``；带自然超时规则的通信后继只使用 ``safety``；
        自然结束后继使用 ``not B & safety``。调用方必须显式选择其中一种，避免
        用单个布尔开关混淆两个不同规则。

        后继路径获得节点 safety 在中断/结束时刻的实例。若 domain 或 safety
        使用了局部 ``t``，离开 ODE 时不能把这个名字泄漏到 Gamma。
        这里用一个新鲜 Real 翻译它，并以 ``exists t>=0`` 投影掉局部时钟；所得
        条件仍是实际 ODE 后状态的保守后置事实。事件 continuation 或顺序后继中
        另行出现的 ``t`` 不受这个量词绑定。
        """
        post = context.clone()
        self._fresh_counter += 1
        translator = self._translator(post)
        # 同一 ODE 的所有新鲜变量共享计数后缀，表示同一后状态快照。
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
            if post_clock is not None:
                condition = conjunction(post_clock >= 0, condition)
                post.path = conjunction(
                    post.parameter_condition,
                    z3.Exists([post_clock], condition),
                )
            else:
                post.path = conjunction(post.parameter_condition, condition)
        except ExpressionError as exc:
            self._diagnose(Verdict.FALSE, str(exc), "T-ODE", context.location)
            return None
        return post

    # ------------------------------------------------------------------
    # Recursive rules
    # ------------------------------------------------------------------
    def rule_t_mu(
        self,
        judgment: _ProcessJudgment,
    ) -> _RuleExpansion:
        """[T-mu] 引入递归边界不变式，并求解行为类型方程。

        Section 2.1 只包含显式 ``mu X.P``；递归回边必须由进程体中的 ``Var(X)``
        写出。``Mu`` 构造器已按 Assumption 2.2 拒绝未受通信保护的源码回边；
        本规则在生成行为类型后仍复核相同结构不变量。仅当类型体确实引用新鲜
        类型变量时才构造 ``MuType``。不变量不是 Bool 时静态前提失败，不进入
        递归体推导。
        """

        node = judgment.nodes[0]
        tail = judgment.nodes[1:]
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
        # X 的边界不变量只来自绑定处的 RecursionAnnotation。
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

        # 类型变量与源程序变量分开命名，避免 alpha 等价判断受到源名称影响。
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
            """用递归体子类型决定是否需要构造通信保护的 MuType。"""

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
        """[T-X] 在显式递归调用处检查边界不变式和尾位置限制。"""

        node = judgment.nodes[0]
        tail = judgment.nodes[1:]
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
        """构造递归回边不变式公式 premise；表达式非法时返回 ``None``。"""
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

    # ------------------------------------------------------------------
    # Helpers
    # ------------------------------------------------------------------
    @staticmethod
    def _lazy_assignment_post_state(
        context: _Context,
        target: str,
        assigned_term: Any,
    ) -> _LazyAssignmentPostState:
        """计算赋值的惰性最强后置状态，不生成待综合谓词或证明义务。

        若赋值前符号映射为 ``rho``，本函数返回的后继映射 ``rho'`` 满足
        ``rho'(target) = eval(e, rho)``，其余变量保持 ``rho'(y) = rho(y)``；
        路径公式仍是赋值前符号上的 ``phi``。二者共同表示经典公式
        ``exists x_old. phi[x_old/x] and x = e[x_old/x]``，但不会引入存在量词。
        """

        if target not in context.symbols:
            # 正常上下文会在 _initial_context 中为 Gamma 的每个变量建符号；
            # 保留显式检查，防止后续内部重构悄悄产生不完整状态。
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
        """为一个配置建立初始 Z3 符号、路径条件和类型固有约束。

        名称前缀包含配置位置，确保并行分量中即使误用同名符号也不会在 Z3
        层意外合并。``Nat >= 0`` 等类型域事实在此统一加入路径条件。
        """
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
        """从不变式建立递归体入口的抽象状态。

        不沿用调用点的具体符号值，而为所有变量建立新鲜符号并仅假设递归
        不变式；这正是循环不变式证明中“任意一次迭代”的抽象。
        """
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
        """把无状态 ``Parallel`` 便捷写法展开为左右系统子 judgment。

        论文 [T-||] 的正式入口仍是顶层多个 ``Configuration``。这里只处理
        :meth:`rule_t_sigma` 已确认的空 state、空 Gamma、true 路径情形；此时
        左右复制到的都是空状态上下文，等价于两个显式 ``({}, P)`` 配置。
        ``Parallel`` 不是 ``Process``，因此结果只可能是 ``ParallelType``，
        不会成为某个顺序 process 的 continuation。
        """

        node = judgment.system
        context = judgment.context
        if context.gamma or not self._is_true(context.path):
            # 正常只能由 rule_t_sigma 的防线阻止；保留局部检查，避免以后新增
            # 内部分派入口时重新把有状态系统当作无状态便捷写法处理。
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
            """把左右系统子类型组合为二元 ParallelType。"""

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
        """求解二元系统并行 judgment，并记录显式左右 premises。"""

        context = judgment.context
        parallel_step = self._start_step(
            "T-||",
            context.location,
            "推导二元系统组合 S || S'",
            context=context,
        )
        expansion = self.rule_t_parallel_system(judgment)
        result = self._solve_rule_expansion(expansion)
        result_text = (
            "推导失败，至少一个并行系统分支没有正式配置类型"
            if isinstance(result, _ConstructionFailure)
            else f"并行配置类型 = {result}"
        )
        self._finish_step(
            parallel_step,
            result_text,
            self._premise_summary(expansion),
        )
        return result

    def _translator(self, context: _Context) -> ExpressionTranslator:
        """创建读取并更新当前分支符号表的表达式翻译器。"""
        return ExpressionTranslator(
            {**context.parameters, **self._value_gamma(context.gamma)},
            context.symbols,
        )

    @staticmethod
    def _defined_term(result: ExprResult) -> Any:
        """把表达式值与其求值有定义条件合成为一个公式。"""

        return conjunction(*result.definedness, result.term)

    def _definedness_premise(
        self,
        rule: str,
        description: str,
        context: _Context,
        result: ExprResult,
    ) -> _FormulaPremise | None:
        """在当前路径下为偏表达式生成显式有定义性 premise。

        常量非零除数等经化简已显然为真的条件不会增加证明记录噪声；
        可能为零或确定为零的条件则保留，由 Z3 给出证明或反例。
        """

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
        """尽量化简逻辑项；原始用户字符串等非 Z3 值则安全地直接显示。"""

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
        """按进入规则的先序顺序保存环境快照，并返回待补结果的列表下标。"""

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
        """在不改变规则入口编号和环境快照的前提下写入规则结果。"""

        self.steps[index] = self.steps[index].completed(result, detail)

    @staticmethod
    def _rule_name(node: Any) -> str:
        """返回进程节点在当前实现中对应的 Table 2 规则名。"""

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
        """把严格 AST 节点转换为接近论文语法的简短用户说明。"""

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
        """给详细报告补充规则作用，同时避免把结构推导与证明结论混淆。"""

        explanations = {
            "T-Skip": "skip 不改变 Gamma、路径条件或符号状态，继续检查顺序后继。",
            "T-Assert": "生成路径条件蕴含断言的 FOL 义务；断言不是 assume。",
            "T-Assign": (
                "按 phi -> phi'{e/x} 确定性生成惰性最强后置状态；"
                "不把未知 phi' 交给证明器综合。"
            ),
            "T-In": "从 Theta 取得各槽类型，为接收目标建立新鲜值并假设 refinement。",
            "T-Out": "逐槽检查输出表达式类型，并证明实际载荷满足 refinement。",
            "T-If": "分别在 phi∧B 和 phi∧¬B 下检查两个分支。",
            "T-sqcup": (
                "把多元内部选择节点的公共 continuation 分别交给"
                "全部子 judgment，再组合各个完整分支类型。"
            ),
            "T-ODE": (
                "核对 Gamma 已登记完整 ODE 演化向量，并仅用节点 safety "
                "生成 safety、domain、boundary 的 dL 义务。"
            ),
            "T-mu": "引入递归类型变量和边界不变量，再检查递归体。",
            "T-X": "检查递归回边的边界不变量，并返回对应类型变量。",
            "structural": "当前对象不属于项目定义的 HCSP 进程节点。",
        }
        return explanations.get(rule, "")

    @staticmethod
    def _process_premise(
        nodes: Sequence[Process],
        context: _Context,
        terminal: ProcessType,
    ) -> _ChildJudgmentPremise:
        """构造顺序进程子 judgment premise，不立即执行它。"""

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
        """构造事件反应子 judgment premise，不立即执行它。"""

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
        """构造将按顺序立即判定的 ``|= phi[sigma]`` 状态前提。

        ``state`` 可以是 ``symbols`` 的真子集；未替换的 Gamma 符号由有效性
        检查按全称语义处理。T-sigma 在调用本方法前已经拒绝未声明状态变量，
        ``Z3ProofEngine`` 仍会重复检查这一边界以避免其他调用方绕过规则层。
        """

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
        """构造将按顺序立即判定的一阶逻辑 premise。"""

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
        """构造将按顺序立即判定的动态逻辑 premise。

        safety/domain 语法上为 true 时保留 ``automatically_true``，求解器在
        当前位置直接写入 TRUE，不调用外部后端。
        """

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
        """把显式 premises 渲染成审计报告中的紧凑推导树说明。"""

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
                    else TypeConstructor._describe_process_node(child.nodes[0])
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
            + " 惰性最强后置状态: "
            + f"赋值前 {target}={TypeConstructor._display_term(post_state.previous_term)}; "
            + f"右值={TypeConstructor._display_term(post_state.assigned_term)}; "
            + f"赋值后 symbols[{target}]="
            + f"{TypeConstructor._display_term(post_state.post_context.symbols[target])}; "
            + "phi' 已由该符号映射确定，不需要谓词综合。"
        )

    def _decide_proof(self, request: _ProofRequest) -> ProofObligation:
        """在当前 premise 位置立即化简、分派、判定并记录一条公式。

        ``formula`` 仍保留规则原始生成式，``proof_formula`` 保存实际交给
        后端的化简式。外部后端异常保守记为 UNKNOWN；调用方只会在 FALSE 时
        终止当前规则，UNKNOWN 则保留证据并继续构造一个明确标为不可信的类型。
        """

        obligation = request.obligation
        proof_step = self._start_step(
            "Proof",
            obligation.rule,
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
                "立即判定 = false；当前规则被否证"
                if verdict is Verdict.FALSE
                else (
                    "立即判定 = unknown；记录未决义务并继续推导"
                    if verdict is Verdict.UNKNOWN
                    else "立即判定 = true；继续推导"
                )
            ),
            f"{obligation.kind.upper()} 义务已按推导顺序处理。{detail}",
        )
        return decided

    def _report(
        self,
        constructed: ConfigurationType | None,
        constructed_component_types: tuple[ConfigurationType | None, ...],
    ) -> TypeConstructionReport:
        """合并义务与诊断的三值结果，构造不可变最终报告。"""
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

    def _diagnose(
        self,
        verdict: Verdict,
        message: str,
        rule: str = "",
        location: str = "",
    ) -> None:
        """追加一条带规则和位置的诊断；不可恢复处由调用者立即返回失败。"""
        self.diagnostics.append(Diagnostic(verdict, message, rule, location))

    @staticmethod
    def _channel_name(channel: str | Channel) -> str:
        """把项目 Channel 或字符串规范成 Theta 的通道键。"""
        if isinstance(channel, str):
            # Theta 是另一条公开通道名输入路径，必须与 process/type AST 使用
            # 完全相同的标识符规则，不能让非法名称绕过 Channel 构造边界。
            return Channel(channel).name
        if isinstance(channel, Channel):
            return channel.name
        raise TypeError(
            "Theta keys must be strings or hcsp_typechecker Channel objects"
        )

    def _as_nodes(self, process: Process) -> list[Process]:
        """递归展开论文二元 ``Sequence``，保持从左到右的执行次序。"""

        if isinstance(process, SequenceHP):
            return self._as_nodes(process.first) + self._as_nodes(process.second)
        return [process]

    @staticmethod
    def _is_true(formula: Any) -> bool:
        """识别 Python/Z3 中语法化简后恒真的公式。"""
        if formula is True:
            return True
        return z3 is not None and z3.is_true(simplify(formula))

    @staticmethod
    def _is_default_true_path(value: Any) -> bool:
        """识别“未另行约束”的公开路径输入 ``true``。

        该检查发生在各配置建立独立 Z3 符号之前，因此先识别 Python/Z3 真值，
        再使用项目表达式解析器接受字符串 ``"true"`` 等等价便捷写法。
        """

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
        """检查数值表达式类型；失败时记录诊断并返回 ``False``。"""
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
        """返回基础值类型固有的逻辑约束；当前仅 ``Nat`` 需要 ``x >= 0``。"""

        value_type = gamma_value_type(value_type)
        if value_type == BasicType.NAT:
            return (symbol >= 0,)
        return ()

    def _contains_type_var(self, value: ProcessType, name: str) -> bool:
        """递归判断行为类型中是否含指定自由类型变量。"""

        if isinstance(value, TypeVar):
            return value.name == name
        if isinstance(value, (InputType, OutputType)):
            return self._contains_type_var(value.continuation, name)
        if isinstance(value, (ExternalChoiceType, InternalChoiceType)):
            return any(
                self._contains_type_var(branch, name)
                for branch in value.branches
            )
        if isinstance(value, FiniteDelayType):
            return self._contains_type_var(
                value.interrupts,
                name,
            ) or self._contains_type_var(value.continuation, name)
        if isinstance(value, InfiniteDelayType):
            return self._contains_type_var(value.interrupts, name)
        if isinstance(value, MuType):
            return value.variable != name and self._contains_type_var(
                value.body,
                name,
            )
        return False

    def _guarded(
        self,
        value: ProcessType,
        name: str,
        under_communication: bool = False,
    ) -> bool:
        """防御性复核递归类型变量是否受输入/输出通信前缀保护。

        ``under_communication`` 一旦经过 InputType/OutputType 即为真；仅经过
        纯等待、选择等构造不算通信保护。遇到同名内层 ``MuType`` 时停止追踪，
        因为该名字已被新的绑定遮蔽。正常项目 AST 已在 ``Mu`` 构造时通过
        Assumption 2.2；此处防止后续类型转换代码破坏该性质。
        """
        if isinstance(value, TypeVar):
            return value.name != name or under_communication
        if isinstance(value, (InputType, OutputType)):
            return self._guarded(value.continuation, name, True)
        if isinstance(value, (ExternalChoiceType, InternalChoiceType)):
            return all(
                self._guarded(branch, name, under_communication)
                for branch in value.branches
            )
        if isinstance(value, FiniteDelayType):
            return self._guarded(
                value.interrupts,
                name,
                under_communication,
            ) and self._guarded(value.continuation, name, under_communication)
        if isinstance(value, InfiniteDelayType):
            return self._guarded(value.interrupts, name, under_communication)
        if isinstance(value, MuType):
            return value.variable == name or self._guarded(
                value.body,
                name,
                under_communication,
            )
        return True

    def _process_vars(self, process: Any) -> set[str]:
        """从项目 HCSP 节点读取状态变量，用于并行 Gamma 自动分区。

        外部对象返回空集并会在实际推导阶段产生结构错误；这里不调用其同名
        方法，避免重新引入鸭子类型兼容。
        """
        if not isinstance(process, HCSP):
            return set()
        return process.get_vars()

    def _process_ode_vectors(self, process: Any) -> set[frozenset[str]]:
        """收集进程树中真正出现的非空 ODE 左端变量集合。"""

        if isinstance(process, ODE):
            current = (
                {frozenset(name for name, _derivative in process.eqs)}
                if process.eqs
                else set()
            )
            return current | self._event_ode_vectors(process.interrupts)
        if isinstance(process, SequenceHP):
            return self._process_ode_vectors(process.first) | self._process_ode_vectors(
                process.second
            )
        if isinstance(process, If):
            return self._process_ode_vectors(
                process.then_branch
            ) | self._process_ode_vectors(process.else_branch)
        if isinstance(process, InternalChoice):
            return set().union(
                *(self._process_ode_vectors(branch) for branch in process.branches),
                self._process_ode_vectors(process.continuation),
            )
        if isinstance(process, Mu):
            return self._process_ode_vectors(process.body)
        if isinstance(process, Parallel):
            return self._process_ode_vectors(process.left) | self._process_ode_vectors(
                process.right
            )
        return set()

    def _event_ode_vectors(self, reaction: EventReaction) -> set[frozenset[str]]:
        """收集 ODE 中断事件各 continuation 内嵌的 ODE 向量。"""

        if isinstance(reaction, EmptyEvent):
            return set()
        if isinstance(reaction, EventChoice):
            return set().union(
                *(self._process_ode_vectors(continuation)
                  for _communication, continuation in reaction.branches)
            )
        return set()

    def _input_bound_vars(self, process: Any) -> set[str]:
        """收集输入写入的目标；这些变量可以不预先出现在 Gamma。"""
        if not isinstance(process, HCSP):
            return set()
        return process.get_input_bound_vars()


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
    """按设计 PPT 的输入形式提供无状态便捷 API。

    该函数负责构造 :class:`TypeConstructionRequest` 和一次性
    :class:`TypeConstructor`。需要重用 ODE 配置或自定义构造流程时，可直接
    实例化 ``TypeConstructor``。
    ``parameters`` 可传入 :class:`ParameterEnvironment`；只传声明映射时
    约束默认为 ``True``。
    """

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
    NoInterruptType,
