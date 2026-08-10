"""用户给定 Type 的检查请求与不可变审计结果。

TypeCheckingReport 中的 ``evidence`` 使用两个后端共享的规则轨迹、证明义务和
诊断容器。共享证据中的 ``constructed_type`` 字段在 Checker 语境下是“已经被
全部规则消费的结论 Type”：它保存用户给定 Type，而不是重新构造的另一棵类型。
"""

from __future__ import annotations

from dataclasses import dataclass
from typing import Mapping

from ...data_structures.runtime_context import (
    ChannelType,
    Configuration,
    GammaType,
    ParameterEnvironment,
)
from ...data_structures.type_ast.ast import ConfigurationType
from ...data_structures.type_ast.render import format_type_source
from ..common.model import RuleDerivationReport, Verdict


@dataclass(frozen=True, slots=True)
class TypeCheckingRequest:
    """检查 ``<Gamma, Theta, P> :: expected_type`` 所需的正式内部输入。"""

    gamma: Mapping[str, GammaType]
    theta: Mapping[str, ChannelType]
    configurations: tuple[Configuration, ...]
    expected_type: ConfigurationType
    path_condition: object = True
    parameters: ParameterEnvironment = ParameterEnvironment()


@dataclass(frozen=True, slots=True)
class TypeCheckingReport:
    """给定 Type 的递归规则检查结果及其全部证明证据。"""

    verdict: Verdict
    expected_type: ConfigurationType
    evidence: RuleDerivationReport
    mismatch: str = ""

    @property
    def passed(self) -> bool:
        """仅当类型结构匹配且所有前提均证明为真时返回真。"""

        return self.verdict is Verdict.TRUE

    @property
    def structurally_matched(self) -> bool:
        """给定 Type 已被规则递归完整消费时返回真。"""

        return self.evidence.constructed_type is not None

    def format_detailed(self) -> str:
        """显示给定 Type 的规则匹配、公式义务和证明结果。

        证明证据的底层布局由 common 层提供，以确保 FOL/dL 公式不会在
        两套功能间出现不同的编号或遗漏；这里只把展示术语改为“检查给定 Type”。
        """

        rendered = self.evidence.format_detailed()
        replacements = (
            ("=== 类型构造与证明详细报告 ===", "=== 给定 Type 检查与证明详细报告 ==="),
            ("规则推导 :", "规则检查 :"),
            ("类型构造 :", "Type 匹配 :"),
            ("构造 Type 源码 :", "给定 Type 源码 :"),
            ("本次类型构造的", "本次类型检查的"),
            ("配置分量候选类型", "配置分量给定类型"),
            ("配置分量类型", "配置分量给定类型"),
        )
        for old, new in replacements:
            rendered = rendered.replace(old, new)
        lines = rendered.splitlines()
        for index, line in enumerate(lines):
            if line.startswith("给定 Type 源码 :"):
                lines[index] = (
                    "给定 Type 源码 : "
                    + format_type_source(self.expected_type)
                )
                break
        return "\n".join(lines)
