"""用户给定 Type 的检查请求与不可变审计结果。

TypeCheckingReport 中的 ``evidence`` 复用 TypeConstructor 已有的通用规则轨迹、
证明义务和诊断容器，但其中的 ``constructed_type`` 只在本次给定 Type 已被全部
结构规则消费时保存该给定 Type；TypeChecker 不从 Process 重新构造另一棵类型。
"""

from __future__ import annotations

from dataclasses import dataclass
from typing import Mapping

from ..runtime_context import ChannelType, GammaType, ParameterEnvironment
from ..type_ast.ast import ConfigurationType
from ..type_ast.render import format_type_source
from ..type_construction import Configuration, TypeConstructionReport, Verdict


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
    evidence: TypeConstructionReport
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

        证明证据的底层布局与 TypeConstructor 共用，以确保 FOL/dL 公式不会在
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
