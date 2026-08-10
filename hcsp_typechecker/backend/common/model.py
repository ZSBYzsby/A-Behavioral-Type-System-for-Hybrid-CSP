"""TypeConstructor 与 TypeChecker 共用的规则证据和证明结果。

这里保存三值结论、证明义务、诊断、规则轨迹与共享推导报告。它们由两个业务
后端共同产生和读取，不属于 Process/Type AST，也不属于任何一个后端的专属请求。
"""

from __future__ import annotations

from dataclasses import dataclass, replace
from enum import Enum
from typing import Any, Callable, Iterable

from ...data_structures.type_ast.ast import ConfigurationType as _ConfigurationType
from ...data_structures.type_ast.render import format_type_source

# --------------------------------------------------------------------------
# 论文对应：论文的 typing judgment 本身是可推导/不可推导的二值关系，
#           未定义 UNKNOWN；本枚举是实现为求解超时或外部证明未完成增加的
#           保守审计结果，不属于 Section 4.1 的行为类型语法。
# 角色对应：所有静态检查与证明义务共用的三值结论域。
# 构造方式：Verdict.TRUE、Verdict.FALSE、Verdict.UNKNOWN；通常由证明后端返回。
# 结果规则：FALSE 表示已发现反例/静态错误，UNKNOWN 表示尚未得到可靠结论；
#           combine 以 FALSE > UNKNOWN > TRUE 的保守优先级汇总结果。
# --------------------------------------------------------------------------
class Verdict(str, Enum):
    """类型构造诊断与证明结果共用的三值逻辑。

    ``UNKNOWN`` 不等同于类型错误：它表示结构推导已经执行，但某个公式
    未能由当前证明后端判定。只有 ``FALSE`` 才表示已经发现反例或静态错误。
    """

    TRUE = "true"
    FALSE = "false"
    UNKNOWN = "unknown"

    # 功能：把枚举值转成报告中使用的小写文本。
    # 构造/模型关系：不改变真假含义，仅提供稳定显示格式。
    def __str__(self) -> str:
        """返回适合报告与命令行展示的小写结果。"""
        return self.value

    # 功能：兼容自定义证明后端返回的 Verdict、bool 或常见状态文本。
    # 构造/模型关系：只有明确的真/假词汇被采信，其他值一律保守为 UNKNOWN。
    @classmethod
    def from_value(cls, value: Any) -> "Verdict":
        """把证明后端常见的布尔值或文本结果统一为三值结果。"""
        if isinstance(value, Verdict):
            return value
        if value is True or str(value).lower() in {"true", "yes", "valid", "proved"}:
            return cls.TRUE
        if value is False or str(value).lower() in {"false", "no", "invalid", "disproved"}:
            return cls.FALSE
        return cls.UNKNOWN

    # 功能：把多条证明义务和诊断的结论合并为一个总体结论。
    # 构造/模型关系：任一 FALSE 使整体为 FALSE；否则任一 UNKNOWN 使整体未知；
    #                空集合按全称条件的真空真返回 TRUE。
    @classmethod
    def combine(cls, values: Iterable["Verdict"]) -> "Verdict":
        """合并子结论：``FALSE`` 优先，其次 ``UNKNOWN``，最后 ``TRUE``。"""
        values = tuple(values)
        if any(value == cls.FALSE for value in values):
            return cls.FALSE
        if any(value == cls.UNKNOWN for value in values):
            return cls.UNKNOWN
        return cls.TRUE

# --------------------------------------------------------------------------
# 论文对应：保存 Table 2 横线以上需要独立判定的前提，例如 [T-Assert] 的
#           ``phi => B``、[T-Assign] 的 ``phi => phi'{e/x}``、
#           [T-Out] 的 ``phi => refinement{e/eta}``、
#           ODE 规则按形状产生的 safety/domain/boundary dL 前提，以及
#           [T-sigma] 的 ``|= phi[sigma]``。
#           ProofObligation 是实现证据对象，不属于论文的类型语法。
# 结果对应：某条 Table 2 规则产生的一条独立 FOL、dL 或初态证明义务。
# 构造方式：ProofObligation(rule, description, formula, kind="fol",
#                            verdict=UNKNOWN, detail="", proof_formula=None)。
# 构造检查：本类只冻结公式和元数据，不调用 Z3/KeYmaera X；共享规则引擎的
#           顺序 premise 求解器在规则当前位置立即化简、判定并写回不可变
#           副本。当前规则确定性地产生义务，不保存已经废弃的 ODE 候选状态。
# --------------------------------------------------------------------------
@dataclass(frozen=True, slots=True)
class ProofObligation:
    """某条类型规则产生的一个可独立审计的逻辑证明目标。

    ``kind`` 为 ``fol`` 时交给 Z3 一阶逻辑后端；``dl`` 表示动态逻辑公式，需要
    外部证明器、注解结果或保守地返回 ``UNKNOWN``。``formula`` 永远保留规则
    最初生成的公式；判定完成后，``proof_formula`` 保存实际交给后端的化简式。
    """

    rule: str
    description: str
    formula: Any
    kind: str = "fol"
    verdict: Verdict = Verdict.UNKNOWN
    detail: str = ""
    proof_formula: Any | None = None

    # 功能：保留规则原始公式和来源信息，写入证明器实际输入、结论及说明。
    # 构造/模型关系：formula 始终对应规则生成的 premise；proof_formula 对应
    #                证明器真正收到的化简式。两者分离，防止审计证据被覆盖。
    def decided(
        self,
        verdict: Verdict,
        detail: str = "",
        proof_formula: Any | None = None,
    ) -> "ProofObligation":
        """返回写入判定结果和实际证明器输入后的不可变副本。"""

        return replace(
            self,
            verdict=verdict,
            detail=detail,
            proof_formula=(
                self.formula if proof_formula is None else proof_formula
            ),
        )


# --------------------------------------------------------------------------
# 论文对应：用于判定 Table 2 [T-unrhd]、[T-unrhd']、[T-unrhd''] 中的
#           differential dynamic logic/ODE 前提；论文只要求这些前提成立，
#           本类额外保留证明器不能决定时的 UNKNOWN 和原因。
# 结果对应：dL 后端对单条 ProofObligation 的三值判定和证据说明。
# 构造方式：DLCheckResult(verdict, detail="")。
# 构造检查：纯数据容器，不自行解析证明器输出；KeYmaeraXBackend 负责映射状态。
# --------------------------------------------------------------------------
@dataclass(frozen=True, slots=True)
class DLCheckResult:
    """外部 dL 后端返回的判定和可审计说明。

    自定义 ``dl_checker`` 也可只返回 ``bool``、``Verdict`` 或字符串；
    KeYmaera X 适配器使用本对象额外保留超时、反例、环境缺失等原因。
    """

    verdict: Verdict
    detail: str = ""


# --------------------------------------------------------------------------
# 论文对应：记录某条 Section 4.3/Table 2 规则为何不可应用，或输入为何不满足
#           Definition 4.1 的环境形状；它是审计设施，不是论文中的判断式。
# 结果对应：无法表示成已判定公式义务的结构错误、类型错误或定位信息。
# 构造方式：Diagnostic(verdict, message, rule="", location="")。
# 构造检查：纯数据容器；当前业务后端负责选择 verdict、规则和位置。
# --------------------------------------------------------------------------
@dataclass(frozen=True, slots=True)
class Diagnostic:
    """面向用户的错误、未知结果或规则定位信息。"""

    verdict: Verdict
    message: str
    rule: str = ""
    location: str = ""


# --------------------------------------------------------------------------
# 论文对应：记录业务后端实际应用 Section 4.2/4.3、Table 2 规则和每条
#           公式 premise 的顺序立即判定；论文只给出推导树，不定义运行时轨迹类。
# 结果对应：一条规则应用时的进程片段、Gamma、Theta、路径条件、符号状态和
#           候选类型，或单条公式的当场判定。它与 ProofObligation 分工：
#           本类说明“如何推导/何时证明”，后者保存具体公式及其证明结果。
# 构造方式：通常由共享规则引擎创建，再用 completed 写入结果。
# 构造检查：所有环境和公式均保存为展示字符串，不能反向参与类型推导。
# --------------------------------------------------------------------------
@dataclass(frozen=True, slots=True)
class DerivationStep:
    """一次类型规则应用或单条公式立即判定的不可变执行快照。

    ``number`` 是进入规则时分配的先序编号，因此条件、选择或递归产生嵌套
    推导时，报告仍按用户阅读源程序的顺序展示。公式步骤在相应规则与其后继之间
    立即出现；单条公式和证明器证据仍查看 ``ProofObligation``。
    """

    number: int
    rule: str
    location: str
    subject: str
    gamma: tuple[tuple[str, str], ...] = ()
    parameters: tuple[tuple[str, str], ...] = ()
    parameter_constraint: str = ""
    theta: tuple[tuple[str, str], ...] = ()
    path_condition: str = ""
    symbolic_state: tuple[tuple[str, str], ...] = ()
    result: str = ""
    detail: str = ""

    # 功能：保留规则入口快照，只补充递归推导完成后才能得到的结果。
    # 构造/模型关系：不改变证明义务结论；result 是候选类型的显示文本。
    def completed(self, result: str, detail: str = "") -> "DerivationStep":
        """返回写入规则结果和补充说明后的不可变副本。"""

        return replace(self, result=result, detail=detail)

# --------------------------------------------------------------------------
# 论文对应：constructed_type/constructed_component_types 保存 Section 4.2
#           判断右侧的 T 或
#           ``mathcal T``；无法形成正式类型的分量用 None 表示，而绝不借用论文
#           中有独立语义的 BottomType。steps 保存规则推导轨迹，obligations
#           保存 Table 2 前提的判定证据。verdict/diagnostics 是项目面向工具
#           使用者增加的三值审计层。
# 结果对应：一次类型构造及其正确性证明的最终不可变审计报告。
# 构造方式：由业务后端或共享规则引擎汇总 verdict、结论类型、义务和诊断。
# 构造检查：本类不重新计算总体 verdict；调用方应信任 _report 使用
#           Verdict.combine 的结果。UNKNOWN 与非空 constructed_type 可同时出现：
#           它表示规则推导已完成，但候选类型尚未被所有义务证实。
# --------------------------------------------------------------------------
@dataclass(frozen=True, slots=True)
class RuleDerivationReport:
    """Table 2 规则执行与伴随证明的共享审计报告。

    报告同时保留总体结论、构造类型、全部证明义务和诊断，避免调用方只能看到
    一个布尔值却无法追溯失败原因。``constructed_type is None`` 表示未能形成
    唯一的完整 Table 2 类型；原因可以是结构/静态前提失败，也可以是规则
    候选尚无法唯一确定。``constructed_component_types`` 中的 None 保留对应
    配置的失败或未访问位置。

    ``verdict == UNKNOWN`` 时 ``constructed_type`` 可以非空。这不是“构造结果已
    被证明正确”，
    而是“Table 2 规则推导已形成完整候选类型，但至少一条必要证明义务
    仍未决”。调用方必须将该类型标记为未验证、不可信；``passed`` 仍只在
    verdict 为 TRUE 时成立。
    """

    verdict: Verdict
    constructed_type: _ConfigurationType | None
    constructed_component_types: tuple[_ConfigurationType | None, ...]
    obligations: tuple[ProofObligation, ...]
    diagnostics: tuple[Diagnostic, ...]
    steps: tuple[DerivationStep, ...] = ()

    # 功能：提供传统布尔式成功查询，仅 TRUE 被视为通过。
    # 构造/模型关系：UNKNOWN 必须保持不通过，避免把未证明义务当成成功。
    @property
    def passed(self) -> bool:
        """仅当所有结构检查和证明义务均为 ``TRUE`` 时返回真。"""
        return self.verdict == Verdict.TRUE

    # 功能：统计证明义务的 true/false/unknown 数量并显示构造类型和诊断数。
    # 构造/模型关系：这是展示函数，不重新合并 verdict 或隐藏失败证据。
    def summary(self) -> str:
        """生成紧凑的单行统计，适合测试失败信息和命令行输出。"""
        proved = sum(
            item.verdict == Verdict.TRUE for item in self.obligations
        )
        disproved = sum(
            item.verdict == Verdict.FALSE for item in self.obligations
        )
        unknown = sum(
            item.verdict == Verdict.UNKNOWN for item in self.obligations
        )
        if self.constructed_type is None:
            type_summary = "(none)"
        elif self.verdict is Verdict.TRUE:
            type_summary = format_type_source(self.constructed_type)
        else:
            type_summary = format_type_source(self.constructed_type)
        trust_summary = (
            "trusted"
            if self.verdict is Verdict.TRUE
            else "untrusted"
            if self.constructed_type is not None
            else "unavailable"
        )
        return (
            f"{self.verdict.value}: type={type_summary}; trust={trust_summary}; "
            f"obligations(proved={proved}, false={disproved}, unknown={unknown}); "
            f"diagnostics={len(self.diagnostics)}; steps={len(self.steps)}"
        )

    # 功能：把实现规则名转换为论文 Table 2 中便于人工审计的 premise 形状。
    # 构造/模型关系：只提供公式来源说明；实际公式仍以 obligation.formula 为准。
    @staticmethod
    def _paper_premise(obligation: ProofObligation) -> str:
        """返回证明义务在论文规则中的简写形状或表达式侧条件说明。"""

        exact_shapes = {
            "T-sigma": "[T-sigma-param]  H => phi[sigma]",
            "T-Assert": "[T-Assert]  phi => B",
            "T-Assign-post": "[T-Assign]  phi => phi'{e/x}",
            "T-Out": "[T-Out]  phi => refinement{e/eta}",
            "T-ODE-safety": (
                "[T-unrhd/T-unrhd-prime]  "
                "(phi and t=0) => [ODE,t'=1]"
                "(t<=d => safety)"
            ),
            "T-ODE-domain": "[T-unrhd]  phi => [ODE]B",
            "T-ODE-boundary": (
                "[T-unrhd-prime]  (phi and t=0) => "
                "[ODE,t'=1]"
                "((t<d => B) and (t=d => not B))"
            ),
            "T-mu": "[T-mu]  phi => invariant",
            "T-X": "[T-X]  phi => invariant",
        }
        if obligation.rule in exact_shapes:
            return exact_shapes[obligation.rule]
        if obligation.rule in {"T-Assign", "T-If"}:
            return (
                f"[{obligation.rule}] 表达式类型 judgment 所需的有定义性侧条件"
            )
        return f"[{obligation.rule}] 规则展开产生的具体公式 premise"

    # 功能：说明不同 proof kind 对应的实际判定机制。
    # 构造/模型关系：不声称 dL 一定使用 KeYmaera X，因为低层业务后端
    #                允许注入其他可信证明器。
    @staticmethod
    def _proof_backend(kind: str) -> str:
        """返回 state/FOL/dL 义务的用户可读证明后端说明。"""

        return {
            "state": "初始状态代入 + Z3 表达式求值",
            "fol": "Z3 有效性检查（检查公式否定式是否不可满足）",
            "dl": "配置的 dL 后端（通常为 KeYmaera X）",
        }.get(kind, f"未知证明类别 {kind!r}")

    # 功能：把可能跨多行的 Z3/dL 公式统一缩进成独立文本块。
    # 构造/模型关系：只改变显示缩进，不截断、化简或重写公式内容。
    @staticmethod
    def _append_formula_block(
        lines: list[str],
        label: str,
        value: Any,
    ) -> None:
        """向报告追加带标题和稳定缩进的完整公式文本。"""

        rendered = str(value)
        formula_lines = rendered.splitlines() or [""]
        lines.append(f"     {label}:")
        lines.extend(f"       {line}" for line in formula_lines)

    # 功能：按逻辑类别集中展示本次类型构造实际证明过的完整公式。
    # 构造/模型关系：FOL 清单同时包含普通 Z3 有效性义务和 T-sigma 的状态
    #                代入公式；dL 清单包含 ODE safety/domain/boundary。清单只
    #                重排现有 ProofObligation，不重新化简、证明或改变 active。
    def _append_formula_inventory(
        self,
        lines: list[str],
        *,
        title: str,
        kinds: frozenset[str],
        label: str,
        empty_message: str,
    ) -> dict[int, str]:
        """列出指定类别的证明器输入，并返回义务序号到公式编号的映射。

        两条义务可能来自不同规则候选，却恰好交给证明器同一个公式。此时仍为
        每条义务保留独立编号和结论，但公式正文只在首次出现处打印一次。
        """

        selected = tuple(
            (source_index, obligation)
            for source_index, obligation in enumerate(
                self.obligations,
                start=1,
            )
            if obligation.kind in kinds
        )
        lines.extend(("", title, f"公式数量 : {len(selected)}"))
        if not selected:
            lines.append(empty_message)
            return {}

        status_labels = {
            Verdict.TRUE: "已证明",
            Verdict.FALSE: "未通过",
            Verdict.UNKNOWN: "待证明",
        }
        references: dict[int, str] = {}
        displayed_formulas: dict[str, str] = {}
        for formula_index, (source_index, obligation) in enumerate(
            selected,
            start=1,
        ):
            formula_reference = f"{label}{formula_index:02d}"
            references[source_index] = formula_reference
            lines.extend(
                (
                    "",
                    f"[{formula_reference}] 对应 O{source_index:02d} | "
                    f"{status_labels[obligation.verdict]} | "
                    f"{obligation.rule} | {obligation.kind.upper()}",
                    f"     公式用途 : {obligation.description}",
                    f"     判定后端 : {self._proof_backend(obligation.kind)}",
                )
            )
            proof_formula = (
                obligation.formula
                if obligation.proof_formula is None
                else obligation.proof_formula
            )
            rendered_formula = str(proof_formula)
            previous_reference = displayed_formulas.get(rendered_formula)
            if previous_reference is None:
                self._append_formula_block(
                    lines,
                    "实际检查公式",
                    proof_formula,
                )
                displayed_formulas[rendered_formula] = formula_reference
            else:
                lines.append(
                    "     实际检查公式 : "
                    f"与 [{previous_reference}] 相同，不重复展开"
                )
            lines.append(f"     判定结果 : {obligation.verdict.value}")
        return references

    # 功能：把结构化轨迹、证明义务和诊断统一渲染为可直接阅读的中文报告。
    # 构造/模型关系：只读取已经冻结的证据，不重新运行规则或证明器，也不会
    #                把候选类型生成成功误写成全部证明义务为真。
    def format_detailed(self) -> str:
        """生成包含 FOL/dL 清单、原始公式、证明器输入和遗留义务的报告。"""

        derivation_complete = self.constructed_type is not None
        type_trusted = self.verdict is Verdict.TRUE and derivation_complete
        if type_trusted:
            trust_status = "可信（全部义务已验证）"
        elif not derivation_complete:
            trust_status = "不适用（未形成完整类型）"
        elif self.verdict is Verdict.UNKNOWN:
            trust_status = "不可信（存在未验证义务）"
        else:
            trust_status = "不可信（存在未通过义务）"
        verdict_explanations = {
            Verdict.TRUE: "全部结构检查、静态类型前提和证明义务均已通过",
            Verdict.FALSE: "至少发现结构/静态类型错误或未满足的证明义务",
            Verdict.UNKNOWN: (
                "规则推导已完成，但至少一条必要证明义务仍未决；"
                "构造类型是完整候选，但尚未验证、不可信"
                if derivation_complete
                else "规则推导未能形成唯一完整类型，且存在未决前提或诊断"
            ),
        }
        lines = [
            "=== 类型构造与证明详细报告 ===",
            f"总体结论 : {self.verdict.value}",
            f"结论说明 : {verdict_explanations[self.verdict]}",
            "规则推导 : " + ("已完成" if derivation_complete else "未完成"),
            "类型构造 : " + ("成功" if derivation_complete else "失败"),
            f"类型可信性 : {trust_status}",
            "构造 Type 源码 : "
            + (
                format_type_source(self.constructed_type)
                if derivation_complete
                else "(none)"
            ),
        ]

        if len(self.constructed_component_types) > 1:
            if type_trusted:
                component_heading = "=== 配置分量类型 ==="
            elif self.verdict is Verdict.UNKNOWN:
                component_heading = "=== 配置分量候选类型（未验证） ==="
            else:
                component_heading = "=== 配置分量候选类型（存在未通过义务） ==="
            lines.extend(("", component_heading))
            for index, component_type in enumerate(
                self.constructed_component_types,
                start=1,
            ):
                rendered_component = (
                    format_type_source(component_type)
                    if component_type is not None
                    else "(failed)"
                )
                lines.append(f"K{index}: {rendered_component}")

        proved = sum(
            item.verdict == Verdict.TRUE for item in self.obligations
        )
        disproved = sum(
            item.verdict == Verdict.FALSE for item in self.obligations
        )
        unknown = sum(
            item.verdict == Verdict.UNKNOWN for item in self.obligations
        )

        # 先按逻辑类别给出完整公式清单，使用户无需在混合的顺序证据中逐条
        # 搜索 FOL 或 dL。后面的顺序记录保留规则原始公式，并通过公式编号
        # 引用这里唯一展开的证明器输入，避免完整日志重复打印同一正文。
        formula_references = self._append_formula_inventory(
            lines,
            title="=== 本次类型构造的一阶逻辑（FOL）证明公式 ===",
            kinds=frozenset({"state", "fol"}),
            label="FOL",
            empty_message="(无一阶逻辑公式)",
        )
        formula_references.update(self._append_formula_inventory(
            lines,
            title="=== 本次类型构造的微分动态逻辑（dL）证明公式 ===",
            kinds=frozenset({"dl"}),
            label="DL",
            empty_message="(无 dL 公式)",
        ))

        lines.extend(
            (
                "",
                "=== 顺序公式判定记录 ===",
                f"证明义务 : {len(self.obligations)}",
                f"已证明   : {proved}",
                f"未通过   : {disproved}",
                f"待证明   : {unknown}",
            )
        )
        if not self.obligations:
            lines.append("(无公式判定记录)")
        status_labels = {
            Verdict.TRUE: "已证明",
            Verdict.FALSE: "未通过",
            Verdict.UNKNOWN: "待证明",
        }
        retention_labels = {
            Verdict.TRUE: "已解决；保留公式和证明证据供审计",
            Verdict.FALSE: "未通过；保留为必须修正或确认的证明义务",
            Verdict.UNKNOWN: "未解决；仍需可信证明后端或人工证明",
        }
        for index, obligation in enumerate(self.obligations, start=1):
            lines.extend(
                (
                    "",
                    f"[O{index:02d}] {status_labels[obligation.verdict]} | "
                    f"{obligation.rule} | {obligation.kind.upper()}",
                    f"     论文前提 : {self._paper_premise(obligation)}",
                    f"     证明目标 : {obligation.description}",
                    f"     判定后端 : {self._proof_backend(obligation.kind)}",
                )
            )
            proof_formula = (
                obligation.formula
                if obligation.proof_formula is None
                else obligation.proof_formula
            )
            formula_reference = formula_references.get(index)
            if str(obligation.formula) == str(proof_formula):
                if formula_reference is None:
                    self._append_formula_block(
                        lines,
                        "规则公式 / 证明器实际输入",
                        obligation.formula,
                    )
                else:
                    lines.append(
                        "     规则生成公式与证明器实际输入相同 : "
                        f"见 [{formula_reference}]"
                    )
            else:
                self._append_formula_block(
                    lines,
                    "规则生成公式（原始）",
                    obligation.formula,
                )
                if formula_reference is None:
                    self._append_formula_block(
                        lines,
                        "证明器实际输入",
                        proof_formula,
                    )
                else:
                    lines.append(
                        f"     证明器实际输入 : 见 [{formula_reference}]"
                    )
            lines.append(f"     判定结果 : {obligation.verdict.value}")
            if obligation.detail:
                lines.append(f"     证明器说明: {obligation.detail}")
            lines.append(
                "     处理状态 : "
                + retention_labels[obligation.verdict]
            )

        unresolved = tuple(
            (index, obligation)
            for index, obligation in enumerate(self.obligations, start=1)
            if obligation.verdict != Verdict.TRUE
        )
        lines.extend(("", "=== 未解决或未通过的证明义务 ==="))
        if not unresolved:
            lines.append("(无；所有已生成证明义务均已证明)")
        for index, obligation in unresolved:
            next_action = (
                "修正程序/批注，或检查是否存在反例"
                if obligation.verdict == Verdict.FALSE
                else "配置可信证明后端、增加证明策略，或人工证明"
            )
            lines.append(
                f"[O{index:02d}] {status_labels[obligation.verdict]} | "
                f"{obligation.rule} | 后续操作：{next_action}"
            )

        lines.extend(("", "=== 规则执行过程 ==="))
        if not self.steps:
            lines.append("(未记录规则步骤)")
        for step in sorted(self.steps, key=lambda item: item.number):
            location = step.location or "-"
            lines.append(f"[{step.number:02d}] {step.rule} @ {location}")
            lines.append(f"     检查对象 : {step.subject}")
            if step.gamma:
                lines.append(
                    "     Gamma    : "
                    + ", ".join(f"{name}:{value_type}" for name, value_type in step.gamma)
                )
            else:
                lines.append("     Gamma    : {}")
            if step.parameters:
                lines.append(
                    "     Parameters: "
                    + ", ".join(
                        f"{name}:{value_type}"
                        for name, value_type in step.parameters
                    )
                )
                lines.append(
                    "     参数约束 : "
                    + (step.parameter_constraint or "True")
                )
            if step.theta:
                lines.append(
                    "     Theta    : "
                    + ", ".join(f"{name}:{channel_type}" for name, channel_type in step.theta)
                )
            if step.path_condition:
                lines.append(f"     路径条件 : {step.path_condition}")
            if step.symbolic_state:
                lines.append(
                    "     符号状态 : "
                    + ", ".join(f"{name}={term}" for name, term in step.symbolic_state)
                )
            if step.result:
                result_lines = step.result.splitlines()
                lines.append(f"     规则结果 : {result_lines[0]}")
                lines.extend(
                    f"                  {line}"
                    for line in result_lines[1:]
                )
            if step.detail:
                lines.append(f"     说明     : {step.detail}")

        lines.extend(("", "=== 诊断信息 ==="))
        if not self.diagnostics:
            lines.append("(无诊断；未发现结构或类型错误)")
        for index, diagnostic in enumerate(self.diagnostics, start=1):
            lines.append(
                f"[{index:02d}] {diagnostic.verdict.value} "
                f"{diagnostic.rule or '-'} @ {diagnostic.location or '-'}"
            )
            lines.append(f"     {diagnostic.message}")

        lines.extend(
            (
                "",
                "=== 汇总 ===",
                f"规则步骤 : {len(self.steps)}",
                f"证明记录 : {len(self.obligations)}",
                f"证明义务 : {len(self.obligations)} "
                f"(true={proved}, false={disproved}, unknown={unknown})",
                f"遗留义务 : {len(unresolved)} "
                f"(未通过={disproved}, 待证明={unknown})",
                f"诊断数量 : {len(self.diagnostics)}",
            )
        )
        return "\n".join(lines)

# 论文对应：为 Section 4.3/Table 2 的 ODE 相关 dL 前提提供可替换判定后端；
#           论文未规定 Python callable 接口或 UNKNOWN 返回形式。
# 功能：声明 规则后端可注入的最小动态逻辑证明器接口。
# 构造/模型关系：输入为单条 ProofObligation；bool/文本会经 Verdict.from_value
#                规范化，None 表示无法处理并应保守得到 UNKNOWN。
DLChecker = Callable[
    [ProofObligation],
    DLCheckResult | Verdict | bool | str | None,
]

__all__ = [
    "DLCheckResult",
    "DLChecker",
    "DerivationStep",
    "Diagnostic",
    "ProofObligation",
    "RuleDerivationReport",
    "Verdict",
]
