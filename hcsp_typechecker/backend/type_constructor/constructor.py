"""HCSP 行为类型构造器的业务入口。

本模块只负责“从 Process AST 构造 Type AST”这一项业务。Table 2 的规则展开、
符号状态和证明基础设施位于 :mod:`hcsp_typechecker.backend.common`；已经实现的
TypeChecker 复用同一套规则，但不依赖 TypeConstructor 本身。
"""

from __future__ import annotations

from typing import Any, Mapping, Sequence

from ...identifiers import is_hcsp_identifier
from ...data_structures.runtime_context import (
    ChannelType,
    Configuration,
    GammaType,
    ParameterEnvironment,
    normalize_channel_type,
    normalize_gamma_type,
    normalize_type,
)
from ...data_structures.type_ast.ast import ConfigurationType, ParallelType
from ..common.logic import (
    ExpressionError,
    ExpressionTranslator,
    conjunction,
)
from ..common.model import DLChecker, Verdict
from ..common.keymaerax import KeYmaeraXConfig
from ..common.rule_engine import Table2RuleEngine, _ConstructionFailure
from .model import TypeConstructionReport, TypeConstructionRequest


class TypeConstructor(Table2RuleEngine):
    """按项目采用的 Table 2 规则构造 HCSP 行为类型。"""

    def construct(
        self,
        request: TypeConstructionRequest,
    ) -> TypeConstructionReport:
        """构造候选 Type AST，并返回推导与证明的完整审计报告。"""

        return self._construct_type(request)

    def _report(
        self,
        constructed: ConfigurationType | None,
        constructed_component_types: tuple[ConfigurationType | None, ...],
    ) -> TypeConstructionReport:
        """把共享引擎证据收束成 TypeConstructor 专属报告。"""

        verdict = Verdict.combine(
            [item.verdict for item in self.obligations]
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
        """执行一次完整类型构造并返回含全部证据的三值报告。

        普通建模/类型错误会转换为 ``Diagnostic(FALSE)``。``FALSE`` 前提会
        否证当前规则并停止相应推导分支；``UNKNOWN`` 证明结果会被完整记录，
        但不会阻止后续规则继续构造类型。因而报告可能同时包含非空
        ``constructed_type`` 和 ``UNKNOWN`` verdict：这表示“推导完成，但至少一条
        必要公式尚未证明”，该类型不能作为可信结论使用。
        """
        # 同一规则引擎实例可复用，但报告和新鲜名计数必须按请求隔离。
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
    """用一次性 :class:`TypeConstructor` 从 AST 和环境构造行为类型。"""

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
