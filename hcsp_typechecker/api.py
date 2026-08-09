"""面向普通使用者的两阶段 HCSP 类型推导接口。

本模块是项目唯一承诺长期兼容的业务门面。用户先调用
:func:`parse_hcsp_program`，把一份完整 source 转换为不可拆分的
:class:`HCSPProgram`；再把该对象原样交给 :func:`infer_hcsp_type`，得到正式
Type AST。Process AST 构造器、Table 2 子判断、证明义务和证明器适配器都属于
内部实现，不需要由普通调用者直接组装。

``OutputMode`` 只控制最后如何展示已经得到的结果，不参与解析、推导或证明。
因此 ``none``、``result`` 和 ``full`` 三种模式得到的对象与逻辑结论完全相同。
类型推导只有在总体 verdict 为 true 时才返回 Type AST；false/unknown 会抛出
携带完整审计文本的 :class:`HCSPTypeError`，绝不使用 ``BottomType`` 或未经证明
的候选类型充当错误占位符。
"""

from __future__ import annotations

from collections.abc import Mapping, Sequence
from dataclasses import dataclass, field, replace
from enum import Enum
import sys
from typing import Any, TextIO, TypeAlias

from .input_language.errors import HCSPInputError
from .input_language.parser import parse_expression, parse_hcsp_source
from .input_language.source import ParsedHCSPSource
from .process.ast import HCSP, Process
from .type_system.ast import ConfigurationType
from .typechecking.checker import check_hcsp
from .typechecking.keymaerax import KeYmaeraXConfig
from .typechecking.model import (
    ChannelType,
    CheckReport,
    Configuration,
    GammaType,
    ParameterEnvironment,
    Verdict,
)


# 用户只需知道第二阶段返回“某个正式 Type AST”；具体节点种类仍由推导结果决定。
TypeAST: TypeAlias = ConfigurationType


class OutputMode(str, Enum):
    """控制公共接口是否打印结果以及打印到什么详细程度。"""

    NONE = "none"
    RESULT = "result"
    FULL = "full"


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
    """把调用方已经选定的一段结果一次性写到目标文本流。"""

    destination = sys.stdout if stream is None else stream
    print(text, file=destination)


def _format_environment(environment: Mapping[str, Any]) -> str:
    """用稳定、紧凑且保留声明顺序的形式显示一个环境。"""

    if not environment:
        return "{}"
    entries = ", ".join(
        f"{name}: {declaration}" for name, declaration in environment.items()
    )
    return "{" + entries + "}"


@dataclass(frozen=True, slots=True)
class HCSPProgram:
    """第一接口生成并由第二接口消费的只读 HCSP 程序模型。

    本对象把同一份 source 中得到的共享参数、Gamma、Theta 和 Process AST 永久
    绑定，避免调用方把不同输入的四部分误配后交给类型检查器。公开属性均是
    只读视图；``process_ast`` 是正式 Process/Parallel AST，``process_components``
    是顶层并行系统按源码顺序展开后的 Process 叶子，只供第二阶段建立配置。
    """

    source_text: str = field(repr=False)
    source_name: str
    _parsed: ParsedHCSPSource = field(repr=False)

    def __post_init__(self) -> None:
        """防御性检查门面对象确实来自完整 source 解析结果。"""

        if not isinstance(self.source_text, str):
            raise TypeError("HCSPProgram source_text must be a string")
        if not isinstance(self.source_name, str) or not self.source_name:
            raise ValueError("HCSPProgram source_name must be a non-empty string")
        if not isinstance(self._parsed, ParsedHCSPSource):
            raise TypeError(
                "HCSPProgram can only wrap a complete parsed HCSP source"
            )

    @property
    def process_ast(self) -> HCSP:
        """返回完整的正式 Process/Parallel AST。"""

        return self._parsed.process

    @property
    def gamma(self) -> Mapping[str, GammaType]:
        """返回 source 生成的只读 Gamma 环境。"""

        return self._parsed.gamma

    @property
    def theta(self) -> Mapping[str, ChannelType]:
        """返回 source 生成的只读 Theta 环境。"""

        return self._parsed.theta

    @property
    def parameters(self) -> ParameterEnvironment:
        """返回 source 生成的共享只读参数环境及约束。"""

        return self._parsed.parameters

    @property
    def process_components(self) -> tuple[Process, ...]:
        """按源码顺序返回顶层并行系统的 Process 叶子。"""

        return self._parsed.process_components

    def format_result(self) -> str:
        """生成只包含第一阶段正式输出对象的紧凑文本。"""

        parameter_text = _format_environment(self.parameters.declarations)
        return "\n".join(
            (
                "=== HCSP 用户输入转换结果 ===",
                "状态       : 成功",
                f"Parameters : {parameter_text}",
                f"约束 H     : {self.parameters.constraint}",
                f"Gamma      : {_format_environment(self.gamma)}",
                f"Theta      : {_format_environment(self.theta)}",
                f"Process 数 : {len(self.process_components)}",
                f"Process AST: {self.process_ast!r}",
            )
        )

    def format_full(self) -> str:
        """生成原始 source、环境和精确 AST 结构的完整前端日志。"""

        component_lines: list[str] = []
        if len(self.process_components) > 1:
            component_lines.extend(("", "--- 顶层并行分量 ---"))
            for index, component in enumerate(self.process_components, start=1):
                component_lines.extend(
                    (
                        f"K{index} 节点类型 : {type(component).__name__}",
                        f"K{index} AST      : {component!r}",
                    )
                )
        return "\n".join(
            (
                "=== HCSP 用户输入转换完整日志 ===",
                f"来源 : {self.source_name}",
                "",
                "--- 原始用户输入 ---",
                self.source_text,
                "",
                "--- 转换结果 ---",
                self.format_result(),
                *component_lines,
            )
        )


def _first_report_reason(report: CheckReport) -> str:
    """从诊断或第一条未通过义务中提取简洁失败原因。"""

    if report.diagnostics:
        return report.diagnostics[0].message
    for obligation in report.obligations:
        if obligation.active and obligation.verdict is not Verdict.TRUE:
            return obligation.detail or obligation.description
    if report.verdict is Verdict.UNKNOWN:
        return "存在尚未证明的前提"
    return "类型推导没有生成可信的正式 Type AST"


def _format_type_result(report: CheckReport) -> str:
    """把内部检查报告渲染成稳定的第二接口结果摘要。"""

    trusted_type = (
        report.inferred_type
        if report.verdict is Verdict.TRUE
        else None
    )
    lines = [
        "=== HCSP 到 Type AST 转换结果 ===",
        f"Verdict : {report.verdict.value}",
        "类型生成 : " + ("成功" if trusted_type is not None else "失败"),
        f"Type     : {trusted_type if trusted_type is not None else '(none)'}",
        f"Type AST : {trusted_type!r}",
    ]
    if trusted_type is None:
        lines.append(f"原因     : {_first_report_reason(report)}")
    return "\n".join(lines)


class HCSPTypeError(RuntimeError):
    """第二阶段未能得到可信 Type AST 时抛出的公共异常。

    ``verdict`` 保留 ``false`` 或 ``unknown``，``partial_types`` 保留停止前已经
    正式形成的分量类型；``format_full()`` 返回规则、FOL/dL 公式和证明器证据。
    内部 ``CheckReport`` 不作为公共构造协议暴露。
    """

    def __init__(self, program: HCSPProgram, report: CheckReport) -> None:
        """冻结用户可见的失败摘要，并保留完整内部报告供文本渲染。"""

        self.program = program
        self.verdict = report.verdict.value
        self.partial_types = report.component_types
        self.reason = _first_report_reason(report)
        self._report = report
        super().__init__(self.format_result())

    def format_result(self) -> str:
        """返回结论、空 Type AST 和首要原因的紧凑失败文本。"""

        return _format_type_result(self._report)

    def format_full(self) -> str:
        """返回输入摘要及停止点以前的完整类型推导审计日志。"""

        return "\n\n".join(
            (self.program.format_full(), self._report.format_detailed())
        )

def parse_hcsp_program(
    source: str,
    *,
    source_name: str = "<input>",
    output: OutputMode | str = OutputMode.NONE,
    stream: TextIO | None = None,
) -> HCSPProgram:
    """把完整用户 source 转换为第二阶段唯一接受的程序模型。

    source 必须依次包含 Gamma、可选 Parameters、Theta 和 Process 分节。解析失败
    时继续抛出带行列和插入符的 :class:`HCSPInputError`；若选择非静默输出，
    接口会先打印相应层级的失败诊断。
    """

    mode = _normalize_output_mode(output)
    try:
        parsed = parse_hcsp_source(source, source_name=source_name)
    except HCSPInputError as error:
        if mode is OutputMode.RESULT:
            text = "\n".join(
                (
                    "=== HCSP 用户输入转换结果 ===",
                    "状态 : 失败",
                    f"错误 : {error.source_name}:{error.line}:{error.column}: "
                    f"{error.message}",
                )
            )
            _write_output(text, stream)
        elif mode is OutputMode.FULL:
            text = "\n".join(
                (
                    "=== HCSP 用户输入转换完整日志 ===",
                    "状态 : 失败",
                    "",
                    "--- 原始用户输入 ---",
                    source if isinstance(source, str) else repr(source),
                    "",
                    "--- 错误诊断 ---",
                    error.format_diagnostic(),
                )
            )
            _write_output(text, stream)
        raise

    program = HCSPProgram(
        source_text=source,
        source_name=source_name,
        _parsed=parsed,
    )
    if mode is not OutputMode.NONE:
        rendered = (
            program.format_full()
            if mode is OutputMode.FULL
            else program.format_result()
        )
        _write_output(rendered, stream)
    return program


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
    """把用户级 Bool/字符串路径条件转换成检查器使用的表达式。"""

    if isinstance(value, str):
        return parse_expression(
            value,
            source_name=f"{source_name}:path_condition",
        )
    if isinstance(value, bool):
        return value
    raise TypeError("path_condition must be a bool or expression string")


def infer_hcsp_type(
    program: HCSPProgram,
    *,
    initial_states: Mapping[str, Any]
    | Sequence[Mapping[str, Any]]
    | None = None,
    path_condition: str | bool = True,
    output: OutputMode | str = OutputMode.NONE,
    stream: TextIO | None = None,
    z3_timeout_ms: int = 5_000,
    keymaerax_timeout_seconds: float | None = None,
) -> TypeAST:
    """对第一阶段程序模型执行完整 HCSP AST 到 Type AST 的推导。

    单进程可用一个 mapping 指定部分初态；并行系统必须按源码分量顺序提供同样
    数量的 mapping。省略时每个分量使用空状态。字符串 ``path_condition`` 使用
    与 source 相同的严格表达式语法解析，语法错误仍抛 ``HCSPInputError``。
    KeYmaera X 的 jar、Java 和工作目录仍
    从项目文档规定的环境变量读取；可选超时只覆盖环境中的超时秒数。

    仅当全部结构检查和 FOL/dL 证明义务为 true 时返回正式
    :class:`TypeAST`。false 或 unknown 会抛 :class:`HCSPTypeError`，异常仍保留
    停止点以前的分量类型和完整审计日志。
    """

    if not isinstance(program, HCSPProgram):
        raise TypeError(
            "infer_hcsp_type expects the HCSPProgram returned by "
            "parse_hcsp_program"
        )
    mode = _normalize_output_mode(output)
    states = _normalize_initial_states(
        initial_states,
        len(program.process_components),
    )
    try:
        normalized_path = _normalize_path_condition(
            path_condition,
            program.source_name,
        )
    except HCSPInputError as error:
        if mode is OutputMode.RESULT:
            rendered_error = "\n".join(
                (
                    "=== HCSP 到 Type AST 转换结果 ===",
                    "Verdict : input-error",
                    "类型生成 : 失败",
                    "Type     : (none)",
                    "Type AST : None",
                    f"原因     : {error.message}",
                )
            )
            _write_output(rendered_error, stream)
        elif mode is OutputMode.FULL:
            rendered_error = "\n\n".join(
                (
                    program.format_full(),
                    "\n".join(
                        (
                            "=== 路径条件解析失败 ===",
                            error.format_diagnostic(),
                        )
                    ),
                )
            )
            _write_output(rendered_error, stream)
        raise
    configurations = tuple(
        Configuration(
            state,
            component,
            name=f"K{index}",
        )
        for index, (state, component) in enumerate(
            zip(states, program.process_components),
            start=1,
        )
    )

    keymaerax_config: KeYmaeraXConfig | None = None
    if keymaerax_timeout_seconds is not None:
        keymaerax_config = replace(
            KeYmaeraXConfig.from_environment(),
            timeout_seconds=keymaerax_timeout_seconds,
        )
    report = check_hcsp(
        gamma=program.gamma,
        theta=program.theta,
        configurations=configurations,
        path_condition=normalized_path,
        parameters=program.parameters,
        keymaerax_config=keymaerax_config,
        z3_timeout_ms=z3_timeout_ms,
    )

    if report.verdict is not Verdict.TRUE and report.inferred_type is not None:
        raise RuntimeError(
            "internal typechecker invariant violated: an untrusted verdict "
            "produced a final Type AST"
        )

    failure = (
        HCSPTypeError(program, report)
        if report.verdict is not Verdict.TRUE
        else None
    )
    if mode is not OutputMode.NONE:
        if failure is not None:
            rendered = (
                failure.format_full()
                if mode is OutputMode.FULL
                else failure.format_result()
            )
        else:
            rendered = (
                "\n\n".join((program.format_full(), report.format_detailed()))
                if mode is OutputMode.FULL
                else _format_type_result(report)
            )
        _write_output(rendered, stream)

    if failure is not None:
        raise failure
    if report.inferred_type is None:
        raise RuntimeError(
            "internal typechecker invariant violated: a true verdict did not "
            "produce a Type AST"
        )
    return report.inferred_type


__all__ = [
    "HCSPInputError",
    "HCSPProgram",
    "HCSPTypeError",
    "OutputMode",
    "TypeAST",
    "infer_hcsp_type",
    "parse_hcsp_program",
]
