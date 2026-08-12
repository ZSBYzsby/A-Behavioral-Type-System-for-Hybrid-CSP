"""面向普通使用者的 HCSP TypeConstructor、TypeChecker 与状态图门面。

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

已有的正式 Type AST 可交给 :func:`build_type_transition_graph`。第三个接口依次验证
Type 根和规模选项，把 Type 降低为规范 AST 与双模拟最小循环项图，再穷尽 Table 3
关键-deadline状态空间。成功返回不含后端项图编号的 ``TypeTransitionGraph``；失败
统一抛出 :class:`HCSPTypeTransitionGraphError`，并通过 ``kind``/``phase`` 区分
失败阶段。和另外两个接口一样，它支持 ``none``、``result`` 与 ``full`` 三档输出。
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
from .data_structures.normalized_type_ast import TypeNormalizationError
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
    TypeTransitionGraphSizeError,
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
    """控制三个公共接口的文本输出详细程度。

    ``NONE`` 不写任何文本，适合把返回值和异常交给上层程序自行处理；``RESULT``
    只写最终结论、正式 Type 或首要错误；``FULL`` 还写输入、规则推导、证明义务，
    或状态图的全部状态与边。输出模式从不改变解析、证明、返回值和异常类型。
    """

    NONE = "none"
    RESULT = "result"
    FULL = "full"


class TypeTransitionGraphErrorKind(str, Enum):
    """第三个接口可由调用者稳定区分的输入、规范化和规模失败类别。"""

    INVALID_TYPE = "invalid-type"
    INVALID_LIMIT = "invalid-limit"
    NORMALIZATION = "normalization"
    SIZE_LIMIT = "size-limit"


@dataclass(frozen=True, slots=True)
class HCSPErrorDetail:
    """一条可由程序读取、也可直接展示给用户的错误证据。

    ``category`` 和 ``verdict`` 用于稳定分类；``message`` 是人类可读原因；
    ``rule``/``location`` 指向失败的推导规则和内部判断位置。证明相关错误还会在
    ``proof_kind``、``formula``、``backend_detail`` 中保存 FOL/dL 类别、实际待证
    公式和证明器说明。非证明错误的后三个字段为空字符串。
    """

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

    ``kind`` 的稳定取值为 ``environment``、``derivation``、``proof-failed`` 和
    ``proof-unknown``。需要读取完整未验证候选时，应先单独捕获子类
    :class:`HCSPUntrustedTypeConstructionError`，再访问 ``untrusted_type``。
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
    错误、证明反例与证明未决；对应稳定值为 ``environment``、
    ``type-mismatch``、``rule-application``、``proof-failed`` 与
    ``proof-unknown``。``details`` 保留所有参与最终结论的错误证据。

    ``expected_type`` 保存用户给定的正式 Type AST；
    ``type_mismatch_detected`` 表示是否明确发现结构不匹配；三值字段
    ``type_structure_matched`` 为 ``True`` 时结构已完整消费，为 ``False`` 时已经
    明确不匹配，为 ``None`` 时环境或规则前提使结构检查没有走完。
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


class HCSPTypeTransitionGraphError(RuntimeError):
    """Type AST 未能生成完整关键-deadline状态图时抛出的公共异常。

    ``kind`` 与 ``phase`` 区分非法 Type 根、非法规模选项、Type 规范化失败和图规模
    越界；``details`` 提供与另外两个业务接口一致的结构化错误证据。达到规模上限
    时 ``limit_name``/``limit`` 保存具体限制；非法选项使用
    ``option_name``/``option_value`` 原样保存调用值。异常保存可读的输入 Type 文本，
    但绝不携带或返回部分状态图。
    """

    def __init__(
        self,
        kind: TypeTransitionGraphErrorKind,
        reason: str,
        type_ast: object,
        *,
        limit_name: str = "",
        limit: int | None = None,
        option_name: str = "",
        option_value: object = None,
    ) -> None:
        """冻结机器可读错误字段和完整日志所需的输入 Type 文本。"""

        if not isinstance(kind, TypeTransitionGraphErrorKind):
            raise TypeError("graph error kind must be TypeTransitionGraphErrorKind")
        self.verdict = "error"
        self.kind = kind
        self.phase = {
            TypeTransitionGraphErrorKind.INVALID_TYPE: "input-validation",
            TypeTransitionGraphErrorKind.INVALID_LIMIT: "option-validation",
            TypeTransitionGraphErrorKind.NORMALIZATION: "normalization",
            TypeTransitionGraphErrorKind.SIZE_LIMIT: "graph-construction",
        }[kind]
        self.reason = reason
        self.limit_name = limit_name
        self.limit = limit
        self.option_name = option_name
        self.option_value = option_value
        self.details = (
            HCSPErrorDetail(
                category=kind.value,
                verdict="error",
                message=reason,
                rule=(
                    "critical-deadline-graph"
                    if kind is TypeTransitionGraphErrorKind.SIZE_LIMIT
                    else "type-normalization"
                    if kind is TypeTransitionGraphErrorKind.NORMALIZATION
                    else "public-interface"
                ),
                location=(
                    option_name
                    if kind is TypeTransitionGraphErrorKind.INVALID_LIMIT
                    else "Type AST root"
                ),
            ),
        )
        self.primary_detail = self.details[0]
        self._input_type = (
            format_type_source(type_ast)
            if isinstance(type_ast, ConfigurationType)
            else repr(type_ast)
        )
        super().__init__(self.format_result())

    def format_result(self) -> str:
        """返回失败类别、阶段、原因和可选规模上限的紧凑结果。"""

        explanations = {
            TypeTransitionGraphErrorKind.INVALID_TYPE: (
                "输入对象不是项目支持的正式 Type AST 配置根"
            ),
            TypeTransitionGraphErrorKind.INVALID_LIMIT: (
                "状态或转移数量上限不是严格正整数或 None"
            ),
            TypeTransitionGraphErrorKind.NORMALIZATION: (
                "Type AST 无法转换为闭合的等递归规范状态"
            ),
            TypeTransitionGraphErrorKind.SIZE_LIMIT: (
                "完整可达图超出调用者允许的构造规模"
            ),
        }
        lines = [
            "=== HCSP Type 状态图构造结果 ===",
            "Verdict : error",
            "图构造 : 失败",
            f"错误类别 : {self.kind.value}",
            f"错误阶段 : {self.phase}",
            f"类别说明 : {explanations[self.kind]}",
            f"原因     : {self.reason}",
        ]
        if self.limit_name:
            lines.append(f"规模上限 : {self.limit_name}={self.limit}")
        if self.option_name:
            lines.append(
                f"非法选项 : {self.option_name}={self.option_value!r}"
            )
        lines.append("返回结果 : 无（不会返回部分状态图）")
        return "\n".join(lines)

    def format_full(self) -> str:
        """返回输入 Type、各处理阶段和最终失败摘要的完整日志。"""

        if self.kind is TypeTransitionGraphErrorKind.INVALID_TYPE:
            stages = (
                "Type 根验证 : 失败",
                "Type 规范化 : 未启动",
                "状态图遍历 : 未启动",
            )
        elif self.kind is TypeTransitionGraphErrorKind.INVALID_LIMIT:
            stages = (
                "Type 根验证 : 成功",
                "选项验证   : 失败",
                "Type 规范化 : 未启动",
                "状态图遍历 : 未启动",
            )
        elif self.kind is TypeTransitionGraphErrorKind.NORMALIZATION:
            stages = (
                "Type 根验证 : 成功",
                "选项验证   : 成功",
                "Type 规范化 : 失败",
                "状态图遍历 : 未启动",
            )
        else:
            stages = (
                "Type 根验证 : 成功",
                "选项验证   : 成功",
                "Type 规范化 : 成功",
                "状态图遍历 : 失败（达到规模上限）",
            )
        result_lines = self.format_result().splitlines()
        return "\n\n".join(
            (
                "=== HCSP Type 状态图构造完整错误日志 ===\n"
                "\n".join(stages),
                "--- 输入 Type ---\n" + self._input_type,
                "=== 状态图构造失败摘要 ===\n"
                + "\n".join(result_lines[1:]),
            )
        )


def _write_graph_error(
    error: HCSPTypeTransitionGraphError,
    mode: OutputMode,
    stream: TextIO | None,
) -> None:
    """按照第三个接口的输出模式至多打印一次结构化错误。"""

    if mode is OutputMode.NONE:
        return
    _write_output(
        error.format_full()
        if mode is OutputMode.FULL
        else error.format_result(),
        stream,
    )


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
    """解析一份完整 HCSP 输入，构造并证明其行为 Type AST。

    输入文本必须按 ``gamma [parameters] theta process`` 的顺序包含全部分节，且
    不能包含用户 ``type`` 分节。接口在内部完成词法/语法分析、运行上下文和
    Process AST 构造、Table 2 规则推导，以及各条 FOL/dL 前提的证明。中间
    Process AST 不作为公共结果暴露。

    Parameters
    ----------
    source:
        完整用户输入字符串。
    source_name:
        出现在输入诊断和完整日志中的来源名称；不参与数学语义。
    initial_states:
        可选部分初态。单个顶层 Process 传一个 ``变量 -> Python 值`` mapping；
        并行系统按源码顶层分量顺序传等长的 mapping 序列；``None`` 为每个分量
        建立空初态。状态键必须是 Gamma 中的标量变量，不能是参数或连续向量标签。
    path_condition:
        全局初始路径条件。可传 Python ``bool``，或使用严格表达式语法的字符串。
    output:
        ``none``、``result``、``full`` 或相应 :class:`OutputMode`。
    stream:
        接收输出文本的文件式对象；``None`` 表示 ``sys.stdout``。
    z3_timeout_ms:
        每次 Z3 查询的毫秒超时。
    keymaerax_timeout_seconds:
        本次调用覆盖的 KeYmaera X 单次证明秒数；``None`` 使用环境配置。

    Returns
    -------
    TypeAST
        规则推导完整、且全部必要证明义务均为 ``true`` 的可信配置类型。

    Raises
    ------
    HCSPInputError
        ``source`` 或字符串路径条件存在词法、语法或前端良构错误；类型构造不会启动。
    HCSPUntrustedTypeConstructionError
        已形成完整候选 Type，但至少一条必要义务为 ``unknown``。候选只保存在
        ``error.untrusted_type``，不会伪装成可信返回值。
    HCSPTypeConstructionError
        环境无效、规则无法应用、未形成完整类型，或必要公式被证明为 ``false``。
    TypeError, ValueError
        Python 调用参数本身不符合接口形状，例如并行初态数量错误或输出模式非法。

    Notes
    -----
    证明器返回 ``unknown`` 时，Constructor 会保留证据并继续推导，以尽量形成
    完整候选；只有 ``false`` 或无法应用规则才会立即阻止该推导继续。输出模式仅
    影响展示，不影响这一逻辑。
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
    """验证用户给出的 Type 是否对应同一输入中的 HCSP Process。

    输入文本必须按 ``gamma [parameters] theta process type`` 的顺序书写。接口会
    把 Process 与 Type 分别解析为内部 AST，再把用户 Type 当作每个 Table 2 判断
    的给定结论逐层消费；它不会先调用 TypeConstructor 构造另一棵 Type 后做整树
    比较。内部选择和外部中断均按用户语法保留的当前层分组、元数和书写顺序检查。

    Parameters
    ----------
    source:
        含用户 ``type`` 分节的完整输入字符串。
    source_name:
        只用于输入诊断与日志的来源名称。
    initial_states:
        可选部分初态；单进程传一个 mapping，并行系统传与顶层分量等长的序列。
    path_condition:
        Python ``bool`` 或严格表达式语法字符串形式的全局初始路径条件。
    output, stream:
        文本详细程度和目标文本流；语义与 :func:`construct_hcsp_type` 相同。
    z3_timeout_ms:
        每次 Z3 查询的毫秒超时。
    keymaerax_timeout_seconds:
        本次调用覆盖的 KeYmaera X 单次证明秒数；``None`` 使用环境配置。

    Returns
    -------
    TypeAST
        输入 ``type`` 分节解析出的同一个正式 Type AST。正常返回表示 Type 结构被
        全部规则完整消费，并且所有必要证明义务均为 ``true``。

    Raises
    ------
    HCSPInputError
        Process、上下文、Type 或字符串路径条件存在前端输入错误。
    HCSPTypeCheckingError
        环境无效、Type 结构不匹配、规则不适用、证明为 ``false`` 或证明为
        ``unknown``。可用 ``kind``、``phase``、``rule``、``location`` 和
        ``details`` 区分原因。
    TypeError, ValueError
        Python 调用参数不符合接口形状。

    Notes
    -----
    ``unknown`` 时 Checker 会继续核对剩余 Type 结构以产生更完整的审计证据，但
    最终仍抛出 ``HCSPTypeCheckingError(kind="proof-unknown")``；它不会返回一个
    “暂时接受”的 Type。
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
    """从正式 Type AST 构造 Table 3 关键-deadline完整可达图。

    接口先验证配置类型根，单向转换为规范化 Type AST，再建立等递归循环项图并按
    双模拟状态取商，最后穷尽 Table 3 的 ``tau``、通信、timeout、内部选择和共同
    时间转移。时间边只走到下一个关键 deadline，而不是枚举任意更短时间片。

    Parameters
    ----------
    type_ast:
        正式配置 ``TypeAST``，通常来自 :func:`construct_hcsp_type`，或已经由
        :func:`check_hcsp_type` 验证。本接口不接收 Type 文本或规范化 Type AST。
    max_states, max_transitions:
        可选严格正整数上限。任一上限被触及时整个调用失败，不返回部分图；
        ``None`` 表示不限制该计数。
    output:
        ``none`` 静默；``result`` 打印图规模和初始规范 Type；``full`` 打印全部
        状态、边标签以及 Table 3 推导证据。
    stream:
        输出目标；``None`` 表示 ``sys.stdout``。

    Returns
    -------
    TypeTransitionGraph
        从 ``initial_state`` 可达的完整状态闭包。``states`` 按连续编号保存规范
        Type 展示代表；``transitions`` 保存标签和全部合并后的规则推导证据。

    Raises
    ------
    HCSPTypeTransitionGraphError
        输入根非法、规模选项非法、Type 无法规范化，或状态/边数量超过上限。异常
        不携带部分图，可按 ``kind`` 和 ``phase`` 稳定区分阶段。

    Notes
    -----
    图状态身份来自等递归循环项图，而不是展示 AST 的 Python 结构相等性。因此
    ``mu t.T`` 与其有限次展开不会产生重复状态。当前接口只构造图，不执行死锁、
    活锁或其他图上性质分析。
    """

    mode = _normalize_output_mode(output)
    if not isinstance(type_ast, ConfigurationType):
        error = HCSPTypeTransitionGraphError(
            TypeTransitionGraphErrorKind.INVALID_TYPE,
            "type_ast 必须是 TypeAST/ConfigurationType",
            type_ast,
        )
        _write_graph_error(error, mode, stream)
        raise error

    for limit_name, limit in (
        ("max_states", max_states),
        ("max_transitions", max_transitions),
    ):
        if (
            limit is not None
            and (
                isinstance(limit, bool)
                or not isinstance(limit, int)
                or limit <= 0
            )
        ):
            error = HCSPTypeTransitionGraphError(
                TypeTransitionGraphErrorKind.INVALID_LIMIT,
                f"{limit_name} 必须是严格正整数或 None",
                type_ast,
                option_name=limit_name,
                option_value=limit,
            )
            _write_graph_error(error, mode, stream)
            raise error

    try:
        graph = _build_type_transition_graph(
            type_ast,
            max_states=max_states,
            max_transitions=max_transitions,
        )
    except TypeNormalizationError as cause:
        error = HCSPTypeTransitionGraphError(
            TypeTransitionGraphErrorKind.NORMALIZATION,
            str(cause),
            type_ast,
        )
        _write_graph_error(error, mode, stream)
        raise error from cause
    except TypeTransitionGraphSizeError as cause:
        error = HCSPTypeTransitionGraphError(
            TypeTransitionGraphErrorKind.SIZE_LIMIT,
            "完整状态图超过允许的规模上限",
            type_ast,
            limit_name=cause.limit_name,
            limit=cause.limit,
        )
        _write_graph_error(error, mode, stream)
        raise error from cause
    if mode is OutputMode.RESULT:
        lines = [
            "Table 3 状态迁移图结果",
            f"初始状态 : S{graph.initial_state}",
            f"状态数量 : {len(graph.states)}",
            f"转移数量 : {len(graph.transitions)}",
        ]
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
    "HCSPTypeTransitionGraphError",
    "HCSPUntrustedTypeConstructionError",
    "OutputMode",
    "TypeAST",
    "TypeCheckingErrorKind",
    "TypeConstructionErrorKind",
    "TypeTransitionGraphErrorKind",
    "TypeTransitionGraph",
    "build_type_transition_graph",
    "construct_hcsp_type",
    "check_hcsp_type",
]
