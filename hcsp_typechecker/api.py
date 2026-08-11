"""面向普通使用者的 HCSP TypeConstructor 与 TypeChecker 门面。

普通调用者只需把一份完整用户 source 交给 :func:`construct_hcsp_type`。接口会在
内部依次完成“源码解析 -> Process AST/环境构造 -> Table 2 类型构造与前提证明”，
成功时直接返回正式 Type AST。中间 Process AST、Gamma、Theta、参数环境和低层
构造请求不会作为公共返回值暴露，因而调用者也无法把不同 source 的内部对象误配。
若 source 末尾还包含用户 ``type`` 分节，则 :func:`check_hcsp_type` 以该 Type
为规则结论逐层检查；它不先构造另一个完整类型。

源码或路径条件无法解析时，接口立即抛出 :class:`HCSPInputError`，不会启动类型
构造。结构/静态类型错误使构造器无法形成完整类型，或必要证明义务被判定为
``false`` 时，接口抛出 :class:`HCSPTypeConstructionError`。若规则推导已经形成
完整 Type AST，但某条必要证明义务仍为 ``unknown``，接口则抛出
:class:`HCSPUntrustedTypeConstructionError`：异常的 ``untrusted_type`` 保留完整
候选类型，同时明确标记它尚未验证、不可信，绝不将它作为普通返回值。

``OutputMode`` 只控制文本展示，不参与解析、推导或证明。``result`` 输出最终结论
以及失败时的部分进度，``full`` 进一步输出原始 source、环境摘要、规则轨迹和
FOL/dL 证明证据；``none`` 供只消费返回值/异常的程序静默调用。
"""

from __future__ import annotations

from collections.abc import Mapping, Sequence
from dataclasses import dataclass, field, replace
from enum import Enum
import sys
from typing import Any, TextIO, TypeAlias

from .frontend.errors import HCSPInputError
from .frontend.type_constructor_frontend.parser import (
    parse_expression,
    parse_hcsp_source,
)
from .frontend.type_checker_frontend import parse_typechecking_source
from .frontend.type_constructor_frontend.source import ParsedHCSPSource
from .frontend.normalized_type_syntax import (
    format_normalized_type_ast as _format_normalized_type_ast,
)
from .frontend.type_transition_graph_syntax import (
    format_type_transition_graph as _format_type_transition_graph,
)
from .data_structures.process_ast.ast import HCSP, Process
from .data_structures.type_ast.ast import ConfigurationType
from .data_structures.type_ast.render import format_type_source
from .backend.type_constructor import (
    TypeConstructionErrorKind,
    TypeConstructionReport,
    classify_construction_error,
    construct_type,
)
from .backend.type_checker import (
    TypeChecker,
    TypeCheckingErrorKind,
    TypeCheckingRequest,
    classify_checking_error,
)
from .backend.type_operational_semantics import (
    build_type_transition_graph as _build_type_transition_graph,
)
from .backend.common.keymaerax import KeYmaeraXConfig
from .backend.common.model import Verdict
from .data_structures.type_transition_graph import TypeTransitionGraph
from .data_structures.runtime_context import (
    ChannelType,
    Configuration,
    GammaType,
    ParameterEnvironment,
)


# 用户只需知道接口返回“某个正式 Type AST”；具体节点种类由推导结果决定。
TypeAST: TypeAlias = ConfigurationType


class OutputMode(str, Enum):
    """控制各公共业务接口的结果展示详细程度。"""

    NONE = "none"
    RESULT = "result"
    FULL = "full"


@dataclass(frozen=True, slots=True)
class HCSPErrorDetail:
    """一条可由程序读取、也可直接展示给用户的错误证据。"""

    category: str
    verdict: str
    message: str
    rule: str = ""
    location: str = ""
    proof_kind: str = ""
    formula: str = ""
    backend_detail: str = ""


def _normalize_output_mode(value: OutputMode | str) -> OutputMode:
    """把字符串便捷写法规范成唯一的 :class:`OutputMode`。"""

    if isinstance(value, OutputMode):
        return value
    if isinstance(value, str):
        try:
            return OutputMode(value.strip().lower())
        except ValueError as exc:
            raise ValueError(
                "output must be 'none', 'result', or 'full'"
            ) from exc
    raise TypeError("output must be an OutputMode or string")


def _write_output(text: str, stream: TextIO | None) -> None:
    """把已经渲染完成的一段接口结果一次性写到目标文本流。"""

    destination = sys.stdout if stream is None else stream
    print(text, file=destination)


def _format_environment(environment: Mapping[str, Any]) -> str:
    """用稳定、紧凑且保留声明顺序的形式显示一个内部环境。"""

    if not environment:
        return "{}"
    entries = ", ".join(
        f"{name}: {declaration}" for name, declaration in environment.items()
    )
    return "{" + entries + "}"


@dataclass(frozen=True, slots=True)
class _ProgramContext:
    """只在一次门面调用内部流转的完整解析上下文。

    本对象故意使用私有名称且不进入根包导出：它负责把同一份 source 产生的参数、
    Gamma、Theta 和 Process AST 绑定到一次类型构造中，而不是供用户分两阶段操作。
    """

    source_text: str = field(repr=False)
    source_name: str
    parsed: ParsedHCSPSource = field(repr=False)

    def __post_init__(self) -> None:
        """防御性检查上下文确实来自一次完整 source 解析。"""

        if not isinstance(self.source_text, str):
            raise TypeError("HCSP source must be a string")
        if not isinstance(self.source_name, str) or not self.source_name:
            raise ValueError("source_name must be a non-empty string")
        if not isinstance(self.parsed, ParsedHCSPSource):
            raise TypeError("internal program context requires ParsedHCSPSource")

    @property
    def process_ast(self) -> HCSP:
        """返回本次内部类型构造使用的完整 Process/Parallel AST。"""

        return self.parsed.process

    @property
    def gamma(self) -> Mapping[str, GammaType]:
        """返回本次内部类型构造使用的只读 Gamma。"""

        return self.parsed.gamma

    @property
    def theta(self) -> Mapping[str, ChannelType]:
        """返回本次内部类型构造使用的只读 Theta。"""

        return self.parsed.theta

    @property
    def parameters(self) -> ParameterEnvironment:
        """返回本次内部类型构造使用的共享参数环境与约束。"""

        return self.parsed.parameters

    @property
    def process_components(self) -> tuple[Process, ...]:
        """按源码顺序返回顶层并行系统的 Process 叶子。"""

        return self.parsed.process_components

    def format_full(self) -> str:
        """显示完整 source 和内部环境摘要，但不导出 Process AST 对象。"""

        return "\n".join(
            (
                "=== HCSP 类型构造完整日志 ===",
                f"来源 : {self.source_name}",
                "",
                "--- 原始用户输入 ---",
                self.source_text,
                "",
                "--- 输入解析与内部模型构造 ---",
                "状态       : 成功",
                f"Parameters : {_format_environment(self.parameters.declarations)}",
                f"约束 H     : {self.parameters.constraint}",
                f"Gamma      : {_format_environment(self.gamma)}",
                f"Theta      : {_format_environment(self.theta)}",
                f"Process 数 : {len(self.process_components)}",
                "Process AST : 已在内部构造，不作为公共对象暴露",
            )
        )


def _parse_program(source: str, source_name: str) -> _ProgramContext:
    """解析完整 source，并把内部模型绑定成一次调用专用的上下文。"""

    parsed = parse_hcsp_source(source, source_name=source_name)
    return _ProgramContext(
        source_text=source,
        source_name=source_name,
        parsed=parsed,
    )


def _first_report_reason(report: TypeConstructionReport) -> str:
    """从诊断或第一条未通过义务中提取简洁失败原因。"""

    # 同一次推导可能先记录 UNKNOWN，随后又遇到明确 FALSE。首要原因应与最终
    # verdict 同级，否则用户会在“已否证”结果中误看到较早的未决提示。
    for diagnostic in report.diagnostics:
        if diagnostic.verdict is report.verdict:
            return diagnostic.message
    for obligation in report.obligations:
        if (
            obligation.verdict is report.verdict
            and obligation.verdict is not Verdict.TRUE
        ):
            return obligation.detail or obligation.description
    if report.diagnostics:
        return report.diagnostics[0].message
    for obligation in report.obligations:
        if obligation.verdict is not Verdict.TRUE:
            return obligation.detail or obligation.description
    if report.verdict is Verdict.UNKNOWN:
        return "存在尚未证明的前提"
    return "TypeConstructor 没有生成可信的正式 Type AST"


_ENVIRONMENT_RULES = frozenset({"environment", "parameters"})


def _report_error_details(
    report: TypeConstructionReport,
    *,
    mismatch: str = "",
    rule_category: str = "derivation",
) -> tuple[HCSPErrorDetail, ...]:
    """把诊断和未通过证明义务转换为稳定的公共错误明细。"""

    details: list[HCSPErrorDetail] = []
    for diagnostic in report.diagnostics:
        if diagnostic.verdict is Verdict.TRUE:
            continue
        if diagnostic.rule in _ENVIRONMENT_RULES:
            category = "environment"
        elif mismatch and diagnostic.message == mismatch:
            category = "type-mismatch"
        else:
            category = rule_category
        details.append(
            HCSPErrorDetail(
                category=category,
                verdict=diagnostic.verdict.value,
                message=diagnostic.message,
                rule=diagnostic.rule,
                location=diagnostic.location,
            )
        )
    for obligation in report.obligations:
        if not obligation.active or obligation.verdict is Verdict.TRUE:
            continue
        details.append(
            HCSPErrorDetail(
                category=(
                    "proof-failed"
                    if obligation.verdict is Verdict.FALSE
                    else "proof-unknown"
                ),
                verdict=obligation.verdict.value,
                message=obligation.description,
                rule=obligation.rule,
                location=obligation.location,
                proof_kind=obligation.kind,
                formula=str(
                    obligation.formula
                    if obligation.proof_formula is None
                    else obligation.proof_formula
                ),
                backend_detail=obligation.detail,
            )
        )
    return tuple(details)


def _primary_error_detail(
    details: tuple[HCSPErrorDetail, ...],
    category: str,
    fallback: str,
) -> HCSPErrorDetail:
    """选择与总体失败类别一致的首要证据，避免摘要和 verdict 错位。"""

    for detail in details:
        if detail.category == category:
            return detail
    if details:
        return details[0]
    return HCSPErrorDetail(category, "false", fallback)


def _error_phase(category: str) -> str:
    """把细分类别归并成用户可读的处理阶段。"""

    if category == "environment":
        return "environment"
    if category.startswith("proof-"):
        return "proof"
    if category == "type-mismatch":
        return "type-matching"
    return "rule-derivation"


def _error_category_explanation(category: str) -> str:
    """返回每个稳定错误类别对应的简明中文含义。"""

    return {
        "environment": "Gamma、Theta、共享参数或路径条件不满足良构要求",
        "derivation": "Table 2 规则无法为当前 Process 形成完整类型结论",
        "type-mismatch": "用户给定 Type 的当前结构与规则结论不一致",
        "rule-application": "当前 Process 或运行上下文不满足规则的静态前提",
        "proof-failed": "必要证明公式已被证明器否证或发现反例",
        "proof-unknown": "必要证明公式尚未被可信证明器判定",
    }.get(category, "处理过程未能得到可信结论")


def _render_primary_detail(detail: HCSPErrorDetail) -> tuple[str, ...]:
    """渲染 result 日志中的规则、位置和证明器说明。"""

    lines = [f"原因     : {detail.message}"]
    if detail.rule:
        lines.append(f"相关规则 : {detail.rule}")
    if detail.location:
        lines.append(f"判断位置 : {detail.location}")
    if detail.proof_kind:
        lines.append(f"证明类别 : {detail.proof_kind.upper()}")
    if detail.backend_detail:
        lines.append(f"证明器说明: {detail.backend_detail}")
    return tuple(lines)


def _detail_reason(detail: HCSPErrorDetail) -> str:
    """返回兼容旧 ``reason`` 字段且同时保留证明器解释的单行原因。"""

    if detail.backend_detail:
        return f"{detail.message}: {detail.backend_detail}"
    return detail.message


def _format_partial_types(report: TypeConstructionReport) -> str:
    """把停止前已经正式形成的分量类型显示为一行。"""

    if not report.constructed_component_types:
        return "(none)"
    return ", ".join(
        f"K{index}="
        + (
            format_type_source(component_type)
            if component_type is not None
            else "(none)"
        )
        for index, component_type in enumerate(
            report.constructed_component_types,
            start=1,
        )
    )


def _format_partial_progress(
    report: TypeConstructionReport,
) -> tuple[str, ...]:
    """生成失败摘要中的部分推导进度和停止位置。"""

    proved = sum(
        item.verdict is Verdict.TRUE for item in report.obligations
    )
    failed = sum(
        item.verdict is Verdict.FALSE for item in report.obligations
    )
    unknown = sum(
        item.verdict is Verdict.UNKNOWN for item in report.obligations
    )
    lines = [
        f"部分类型 : {_format_partial_types(report)}",
        f"推导步骤 : 已执行 {len(report.steps)} 步",
        "证明义务 : "
        f"true={proved}, false={failed}, unknown={unknown}",
    ]
    if report.steps:
        last_step = max(report.steps, key=lambda item: item.number)
        lines.append(
            "停止位置 : "
            f"{last_step.rule} @ {last_step.location or '-'}"
        )
    return tuple(lines)


def _format_type_result(
    report: TypeConstructionReport,
    *,
    failure_kind: TypeConstructionErrorKind | None = None,
    primary_detail: HCSPErrorDetail | None = None,
) -> str:
    """把内部类型构造报告渲染成稳定的单入口结果摘要。"""

    constructed_type = report.constructed_type
    proof_counts = {
        verdict: sum(
            obligation.verdict is verdict
            for obligation in report.obligations
        )
        for verdict in Verdict
    }
    proof_summary = (
        f"true={proof_counts[Verdict.TRUE]}, "
        f"false={proof_counts[Verdict.FALSE]}, "
        f"unknown={proof_counts[Verdict.UNKNOWN]}"
    )
    is_trusted = (
        report.verdict is Verdict.TRUE and constructed_type is not None
    )
    is_untrusted = (
        report.verdict is Verdict.UNKNOWN and constructed_type is not None
    )
    construction_status = "已完成" if constructed_type is not None else "未完成"
    if is_trusted:
        proof_status = "全部通过"
        trust_status = "可信（已验证）"
    elif is_untrusted:
        proof_status = "存在未验证义务"
        trust_status = "不可信（未验证）"
    elif constructed_type is not None:
        proof_status = "存在未通过义务"
        trust_status = "不可信（已发现未通过义务）"
    else:
        proof_status = (
            "未通过"
            if report.verdict is Verdict.FALSE
            else "存在未决前提"
        )
        trust_status = "不适用（未形成完整类型）"
    lines = [
        "=== HCSP 类型构造结果 ===",
        f"Verdict : {report.verdict.value}",
        f"类型构造 : {construction_status}",
        "Type AST 生成 : " + ("成功" if constructed_type is not None else "失败"),
        f"证明状态 : {proof_status}",
        f"类型可信性 : {trust_status}",
    ]
    if failure_kind is not None:
        lines.extend(
            (
                f"错误类别 : {failure_kind.value}",
                f"错误阶段 : {_error_phase(failure_kind.value)}",
                "类别说明 : "
                + _error_category_explanation(failure_kind.value),
            )
        )
    if is_untrusted:
        lines.extend(
            (
                "完整候选 Type 源码 : "
                + format_type_source(constructed_type),
                "处理结果 : 候选类型仅通过异常的 untrusted_type 属性提供，"
                "未作为可信 Type AST 返回",
                f"证明义务 : {proof_summary}",
            )
        )
    elif constructed_type is not None and report.verdict is Verdict.TRUE:
        lines.append("Type 源码 : " + format_type_source(constructed_type))
    elif constructed_type is not None:
        lines.extend(
            (
                "完整候选 Type 源码 : "
                + format_type_source(constructed_type),
                "处理结果 : 候选类型没有作为可信 Type AST 返回",
            )
        )
    else:
        lines.append("Type 源码 : (none)")
        lines.extend(_format_partial_progress(report))
    if primary_detail is not None:
        lines.extend(_render_primary_detail(primary_detail))
    return "\n".join(lines)


def _format_input_error_result(
    error: HCSPInputError,
    *,
    operation: str,
) -> str:
    """把解析错误显示成带业务名称和机器可读分类的紧凑结果。"""

    return "\n".join(
        (
            f"=== HCSP {operation}输入错误 ===",
            "Verdict : input-error",
            "结果     : 失败",
            f"错误类别 : input-{error.phase}",
            "错误阶段 : input",
            f"原因     : {error.message}",
            f"位置     : {error.source_name}:{error.line}:{error.column}",
            f"{operation}进度 : 未启动（输入解析阶段已终止）",
        )
    )


def _format_input_error_full(
    source: Any,
    source_name: str,
    error: HCSPInputError,
    *,
    operation: str,
) -> str:
    """显示原始输入、精确定位和后端未启动的完整解析失败日志。"""

    return "\n".join(
        (
            f"=== HCSP {operation}完整错误日志 ===",
            f"来源 : {source_name}",
            "Verdict : input-error",
            f"错误类别 : input-{error.phase}",
            "错误阶段 : input",
            "",
            "--- 原始用户输入 ---",
            source if isinstance(source, str) else repr(source),
            "",
            "--- 输入解析失败 ---",
            error.format_diagnostic(),
            "",
            f"--- {operation} ---",
            "未启动：输入尚未形成合法的内部 AST 与环境。",
        )
    )


class HCSPTypeConstructionError(RuntimeError):
    """TypeConstructor 未能得到可信 Type AST 时抛出的公共异常。

    ``verdict`` 是 ``false`` 或 ``unknown``；``reason`` 给出首要失败原因；
    ``kind/phase/rule/location`` 给出机器可读分类与首要位置；``details`` 保存
    全部有效错误证据；``partial_types`` 保留各配置已经形成的分量类型。
    ``format_full()`` 可用于在捕获异常后再次读取全部规则、FOL/dL 公式和证明器
    证据。内部 Process AST 与内部构造报告没有公共属性。
    """

    def __init__(
        self,
        context: _ProgramContext,
        report: TypeConstructionReport,
    ) -> None:
        """冻结公共失败摘要，并私下保留渲染完整日志所需的证据。"""

        self.source_name = context.source_name
        self.verdict = report.verdict.value
        self.partial_types = report.constructed_component_types
        self.kind = classify_construction_error(report)
        self.phase = _error_phase(self.kind.value)
        self.details = _report_error_details(report)
        self.primary_detail = _primary_error_detail(
            self.details,
            self.kind.value,
            _first_report_reason(report),
        )
        self.reason = _detail_reason(self.primary_detail)
        self.rule = self.primary_detail.rule
        self.location = self.primary_detail.location
        self._context = context
        self._report = report
        super().__init__(self.format_result())

    def format_result(self) -> str:
        """返回失败原因、部分类型和停止进度的紧凑文本。"""

        return _format_type_result(
            self._report,
            failure_kind=self.kind,
            primary_detail=self.primary_detail,
        )

    def format_full(self) -> str:
        """返回原始输入及停止点以前的完整类型构造审计日志。"""

        result_lines = self.format_result().splitlines()
        return "\n\n".join(
            (
                self._context.format_full(),
                self._report.format_detailed(),
                "=== 类型构造失败摘要 ===\n"
                + "\n".join(result_lines[1:]),
            )
        )


class HCSPUntrustedTypeConstructionError(HCSPTypeConstructionError):
    """类型构造完成、但必要证明义务仍未验证时抛出的公共异常。

    ``untrusted_type`` 是规则推导得到的完整 Type AST。它便于用户审计
    推导结构或在外部补充证明，但不表示构造正确性已经得到证明。该异常是
    :class:`HCSPTypeConstructionError` 的子类，因此调用者可以统一捕获所有
    TypeConstructor 失败，也可以单独读取尚未验证的完整候选类型。
    """

    def __init__(
        self,
        context: _ProgramContext,
        report: TypeConstructionReport,
    ) -> None:
        """保留完整但未验证的候选类型及其全部审计证据。"""

        if report.verdict is not Verdict.UNKNOWN:
            raise ValueError(
                "HCSPUntrustedTypeConstructionError requires an unknown verdict"
            )
        if report.constructed_type is None:
            raise ValueError(
                "HCSPUntrustedTypeConstructionError requires a complete "
                "constructed type"
            )
        self.untrusted_type: TypeAST = report.constructed_type
        super().__init__(context, report)


class HCSPTypeCheckingError(RuntimeError):
    """用户给定 Type 未被 Table 2 规则验证时抛出的结构化公共异常。

    ``kind`` 和 ``phase`` 可供程序区分环境错误、Type 结构不匹配、规则应用
    错误、证明反例与证明未决；``details`` 保留所有参与最终结论的错误证据。
    """

    def __init__(
        self,
        source_name: str,
        report: object,
        source_text: str = "",
    ) -> None:
        """保存最小的机器可读检查结论与内部审计报告。"""

        self.source_name = source_name
        self._source_text = source_text
        self._report = report
        self.verdict = report.verdict.value
        self.expected_type = report.expected_type
        self.kind = classify_checking_error(report)
        self.phase = _error_phase(self.kind.value)
        self.details = _report_error_details(
            report.evidence,
            mismatch=report.mismatch,
            rule_category="rule-application",
        )
        self.primary_detail = _primary_error_detail(
            self.details,
            self.kind.value,
            report.mismatch
            or report.failure_reason
            or _first_report_reason(report.evidence),
        )
        self.reason = _detail_reason(self.primary_detail)
        self.rule = self.primary_detail.rule
        self.location = self.primary_detail.location
        self.type_mismatch_detected = bool(report.mismatch)
        self.type_structure_matched: bool | None = (
            False
            if report.mismatch
            else True
            if report.evidence.constructed_type is not None
            else None
        )
        super().__init__(self.format_result())

    def format_result(self) -> str:
        """渲染给定 Type、检查结论及其首要失败原因。"""

        if self.kind is TypeCheckingErrorKind.ENVIRONMENT:
            structure_status = "未启动（环境无效）"
        elif self.kind is TypeCheckingErrorKind.TYPE_MISMATCH:
            structure_status = "不匹配"
        else:
            structure_status = "已按规则检查，最终结论未通过"
        lines = [
            "=== HCSP 类型检查结果 ===",
            f"Verdict : {self.verdict}",
            "检查结论 : 失败",
            f"错误类别 : {self.kind.value}",
            f"错误阶段 : {self.phase}",
            "类别说明 : " + _error_category_explanation(self.kind.value),
            f"Type 结构 : {structure_status}",
            "给定 Type 源码 : " + format_type_source(self.expected_type),
        ]
        lines.extend(_render_primary_detail(self.primary_detail))
        return "\n".join(lines)

    def format_full(self) -> str:
        """渲染用户 Type 与 Table 2 规则、证明义务的完整审计记录。"""

        sections = [
            "=== HCSP 类型检查完整日志 ===\n"
            f"来源 : {self.source_name}",
        ]
        if self._source_text:
            sections.append("--- 原始用户输入 ---\n" + self._source_text)
        result_lines = self.format_result().splitlines()
        sections.extend(
            (
                self._report.format_detailed(),
                "=== Type 检查失败摘要 ===\n"
                + "\n".join(result_lines[1:]),
            )
        )
        return "\n\n".join(sections)


def _normalize_initial_states(
    value: Mapping[str, Any] | Sequence[Mapping[str, Any]] | None,
    component_count: int,
) -> tuple[Mapping[str, Any], ...]:
    """把单进程或并行分量初态转换成与 Process 叶子一一对应的元组。"""

    if value is None:
        return tuple({} for _ in range(component_count))
    if isinstance(value, Mapping):
        if component_count != 1:
            raise ValueError(
                "parallel HCSP input requires one initial-state mapping per "
                "top-level process component"
            )
        return (dict(value),)
    if isinstance(value, (str, bytes)) or not isinstance(value, Sequence):
        raise TypeError(
            "initial_states must be a mapping, a sequence of mappings, or None"
        )
    states = tuple(value)
    if len(states) != component_count:
        raise ValueError(
            "initial_states count must match the number of top-level process "
            f"components ({component_count})"
        )
    if any(not isinstance(state, Mapping) for state in states):
        raise TypeError("every initial state must be a mapping")
    return tuple(dict(state) for state in states)


def _normalize_path_condition(value: str | bool, source_name: str) -> Any:
    """把用户级 Bool/字符串路径条件转换成 TypeConstructor 使用的表达式。"""

    if isinstance(value, str):
        return parse_expression(
            value,
            source_name=f"{source_name}:path_condition",
        )
    if isinstance(value, bool):
        return value
    raise TypeError("path_condition must be a bool or expression string")


def _build_configurations(
    context: _ProgramContext,
    initial_states: Mapping[str, Any]
    | Sequence[Mapping[str, Any]]
    | None,
) -> tuple[Configuration, ...]:
    """为每个顶层 Process 分量建立一一对应的内部配置。"""

    states = _normalize_initial_states(
        initial_states,
        len(context.process_components),
    )
    return tuple(
        Configuration(state, component, name=f"K{index}")
        for index, (state, component) in enumerate(
            zip(states, context.process_components),
            start=1,
        )
    )


def construct_hcsp_type(
    source: str,
    *,
    source_name: str = "<input>",
    initial_states: Mapping[str, Any]
    | Sequence[Mapping[str, Any]]
    | None = None,
    path_condition: str | bool = True,
    output: OutputMode | str = OutputMode.NONE,
    stream: TextIO | None = None,
    z3_timeout_ms: int = 5_000,
    keymaerax_timeout_seconds: float | None = None,
) -> TypeAST:
    """把完整用户 source 直接转换成可信 Type AST。

    source 必须依次包含 Gamma、可选 Parameters、Theta 和 Process 分节。单进程可
    用一个 mapping 指定部分初态；并行系统必须按源码分量顺序提供同样数量的
    mapping。字符串 ``path_condition`` 使用 source 的严格表达式语法解析。

    输入解析失败会在启动类型构造前抛出 :class:`HCSPInputError`。仅当结构检查、
    静态类型前提和全部 FOL/dL 证明义务均为 true 时返回 :class:`TypeAST`。
    无法形成完整类型或 verdict 为 false 时抛出
    :class:`HCSPTypeConstructionError`；构造完成但 verdict 为 unknown 时抛出
    :class:`HCSPUntrustedTypeConstructionError`，其
    ``untrusted_type`` 属性保留完整但不可信的候选类型。``output`` 只选择
    ``none``、``result`` 或 ``full`` 展示层级，不改变返回对象和逻辑结论。
    """

    mode = _normalize_output_mode(output)
    try:
        context = _parse_program(source, source_name)
    except HCSPInputError as error:
        if mode is not OutputMode.NONE:
            rendered = (
                _format_input_error_full(
                    source,
                    source_name,
                    error,
                    operation="类型构造",
                )
                if mode is OutputMode.FULL
                else _format_input_error_result(
                    error,
                    operation="类型构造",
                )
            )
            _write_output(rendered, stream)
        raise

    try:
        normalized_path = _normalize_path_condition(
            path_condition,
            context.source_name,
        )
    except HCSPInputError as error:
        if mode is not OutputMode.NONE:
            rendered = (
                "\n\n".join(
                    (
                        context.format_full(),
                        "\n".join(
                            (
                                "=== 路径条件解析失败 ===",
                                "Verdict : input-error",
                                f"错误类别 : {error.kind}",
                                "错误阶段 : input",
                                error.format_diagnostic(),
                                "",
                                "类型构造未启动。",
                            )
                        ),
                    )
                )
                if mode is OutputMode.FULL
                else _format_input_error_result(
                    error,
                    operation="类型构造",
                )
            )
            _write_output(rendered, stream)
        raise

    configurations = _build_configurations(context, initial_states)
    keymaerax_config: KeYmaeraXConfig | None = None
    if keymaerax_timeout_seconds is not None:
        keymaerax_config = replace(
            KeYmaeraXConfig.from_environment(),
            timeout_seconds=keymaerax_timeout_seconds,
        )
    report = construct_type(
        gamma=context.gamma,
        theta=context.theta,
        configurations=configurations,
        path_condition=normalized_path,
        parameters=context.parameters,
        keymaerax_config=keymaerax_config,
        z3_timeout_ms=z3_timeout_ms,
    )

    if report.verdict is Verdict.TRUE and report.constructed_type is None:
        raise RuntimeError(
            "internal TypeConstructor invariant violated: a true verdict did not "
            "produce a Type AST"
        )

    if report.verdict is Verdict.UNKNOWN and report.constructed_type is not None:
        failure: HCSPTypeConstructionError | None = (
            HCSPUntrustedTypeConstructionError(
                context,
                report,
            )
        )
    elif report.verdict is not Verdict.TRUE:
        failure = HCSPTypeConstructionError(context, report)
    else:
        failure = None
    if mode is not OutputMode.NONE:
        if failure is not None:
            rendered = (
                failure.format_full()
                if mode is OutputMode.FULL
                else failure.format_result()
            )
        else:
            rendered = (
                "\n\n".join((context.format_full(), report.format_detailed()))
                if mode is OutputMode.FULL
                else _format_type_result(report)
            )
        _write_output(rendered, stream)

    if failure is not None:
        raise failure
    if report.constructed_type is None:
        raise RuntimeError(
            "internal TypeConstructor invariant violated: successful "
            "construction lost its Type AST"
        )
    return report.constructed_type


def check_hcsp_type(
    source: str,
    *,
    source_name: str = "<input>",
    initial_states: Mapping[str, Any]
    | Sequence[Mapping[str, Any]]
    | None = None,
    path_condition: str | bool = True,
    output: OutputMode | str = OutputMode.NONE,
    stream: TextIO | None = None,
    z3_timeout_ms: int = 5_000,
    keymaerax_timeout_seconds: float | None = None,
) -> TypeAST:
    """检查完整 ``gamma [parameters] theta process type`` 输入中的给定 Type。

    输入 Type 必须使用 ``frontend.type_syntax`` 的规范语法；初态与路径条件的
    约束和 TypeConstructor 入口一致。检查器按源码顺序
    展开 Process 的 Table 2 规则、生成同样的 FOL/dL 前提，并将每个规则结论与
    用户给定 Type AST 比对；内部选择按用户圆括号保留的当前层分块逐项检查，
    外部中断按 AST 分支顺序逐项检查。所有前提证明为真时返回原用户 Type AST，否则抛出
    :class:`HCSPTypeCheckingError`。
    """

    mode = _normalize_output_mode(output)
    try:
        parsed = parse_typechecking_source(source, source_name=source_name)
    except HCSPInputError as error:
        if mode is not OutputMode.NONE:
            _write_output(
                (
                    _format_input_error_full(
                        source,
                        source_name,
                        error,
                        operation="类型检查",
                    )
                    if mode is OutputMode.FULL
                    else _format_input_error_result(
                        error,
                        operation="类型检查",
                    )
                ),
                stream,
            )
        raise
    components = parsed.program.process_components
    try:
        normalized_path = _normalize_path_condition(path_condition, source_name)
    except HCSPInputError as error:
        if mode is not OutputMode.NONE:
            _write_output(
                (
                    _format_input_error_full(
                        source,
                        source_name,
                        error,
                        operation="类型检查",
                    )
                    if mode is OutputMode.FULL
                    else _format_input_error_result(
                        error,
                        operation="类型检查",
                    )
                ),
                stream,
            )
        raise
    states = _normalize_initial_states(initial_states, len(components))
    configurations = tuple(
        Configuration(state, component, name=f"K{index}")
        for index, (state, component) in enumerate(zip(states, components), 1)
    )
    keymaerax_config = None
    if keymaerax_timeout_seconds is not None:
        keymaerax_config = replace(
            KeYmaeraXConfig.from_environment(),
            timeout_seconds=keymaerax_timeout_seconds,
        )
    report = TypeChecker(
        keymaerax_config=keymaerax_config,
        z3_timeout_ms=z3_timeout_ms,
    ).check(
        TypeCheckingRequest(
            parsed.program.gamma,
            parsed.program.theta,
            configurations,
            parsed.expected_type,
            path_condition=normalized_path,
            parameters=parsed.program.parameters,
        )
    )
    if report.verdict is Verdict.TRUE:
        if mode is not OutputMode.NONE:
            result_text = "\n".join(
                (
                    "=== HCSP 类型检查结果 ===",
                    "Verdict : true",
                    "Type 结构 : 与全部规则结论匹配",
                    "证明状态 : 全部前提已验证",
                    "Type 源码 : "
                    + format_type_source(parsed.expected_type),
                )
            )
            _write_output(
                (
                    "\n\n".join(
                        (
                            "=== HCSP 类型检查完整日志 ===\n"
                            f"来源 : {source_name}\n\n"
                            "--- 原始用户输入 ---\n"
                            f"{source}",
                            report.format_detailed(),
                        )
                    )
                    if mode is OutputMode.FULL
                    else result_text
                ),
                stream,
            )
        return parsed.expected_type
    error = HCSPTypeCheckingError(source_name, report, source)
    if mode is not OutputMode.NONE:
        _write_output(
            error.format_full() if mode is OutputMode.FULL else error.format_result(),
            stream,
        )
    raise error


def build_type_transition_graph(
    type_ast: TypeAST,
    *,
    max_states: int | None = None,
    max_transitions: int | None = None,
    output: OutputMode | str = OutputMode.NONE,
    stream: TextIO | None = None,
) -> TypeTransitionGraph:
    """按 Table 3 穷尽给定 Type AST 的可达规范状态和全部非确定性转移。

    接口先把现有 Type AST 单向转换为规范化 Type AST，再以最大关键 deadline
    策略生成状态图。可选规模上限只用于防止状态爆炸；触及上限时返回图的
    ``complete`` 为 false，并在 ``truncation_reason`` 中说明原因。``result`` 输出
    图规模、完整性和初始规范类型；``full`` 输出全部状态、转移和规则证据。
    """

    if not isinstance(type_ast, ConfigurationType):
        raise TypeError("type_ast must be a TypeAST/ConfigurationType")
    mode = _normalize_output_mode(output)
    graph = _build_type_transition_graph(
        type_ast,
        max_states=max_states,
        max_transitions=max_transitions,
    )
    if mode is OutputMode.RESULT:
        lines = [
            "Table 3 状态迁移图结果",
            f"初始状态 : S{graph.initial_state}",
            f"状态数量 : {len(graph.states)}",
            f"转移数量 : {len(graph.transitions)}",
            "完整闭包 : " + ("是" if graph.complete else "否"),
        ]
        if graph.truncation_reason is not None:
            lines.append("截断原因 : " + graph.truncation_reason)
        initial = graph.states[graph.initial_state].type_ast
        lines.append("初始规范 Type :")
        lines.extend(
            "    " + line
            for line in _format_normalized_type_ast(initial).splitlines()
        )
        _write_output("\n".join(lines), stream)
    elif mode is OutputMode.FULL:
        _write_output(_format_type_transition_graph(graph), stream)
    return graph


__all__ = [
    "HCSPErrorDetail",
    "HCSPInputError",
    "HCSPTypeConstructionError",
    "HCSPTypeCheckingError",
    "HCSPUntrustedTypeConstructionError",
    "OutputMode",
    "TypeAST",
    "TypeCheckingErrorKind",
    "TypeConstructionErrorKind",
    "TypeTransitionGraph",
    "build_type_transition_graph",
    "construct_hcsp_type",
    "check_hcsp_type",
]
