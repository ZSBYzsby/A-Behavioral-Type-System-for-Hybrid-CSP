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
from ..common.model import RuleDerivationReport, Verdict


@dataclass(frozen=True, slots=True)
class TypeCheckingRequest:
    """检查 ``<Gamma, Pi, Theta, configurations> :: expected_type`` 的内部输入。

    ``expected_type`` 是用户已经给定的规则结论，不是要求 Checker 重新构造的
    结果；共享参数、路径与配置的解释与 TypeConstructor 请求保持一致。
    """

    gamma: Mapping[str, GammaType]
    theta: Mapping[str, ChannelType]
    configurations: tuple[Configuration, ...]
    expected_type: ConfigurationType
    path_condition: object = True
    parameters: ParameterEnvironment = ParameterEnvironment()


@dataclass(frozen=True, slots=True)
class TypeCheckingReport:
    """给定 Type 的递归规则检查结果及其全部证明证据。

    ``mismatch`` 只保存明确的用户 Type 结构不匹配；环境或其他规则错误写入
    ``failure_reason``。二者分离，使公开错误分类不会把环境失败误报成 Type
    mismatch。``evidence.constructed_type`` 在本报告中表示给定 Type 已被规则
    完整消费，不表示 Checker 又构造了一棵类型。
    """

    verdict: Verdict
    expected_type: ConfigurationType
    evidence: RuleDerivationReport
    mismatch: str = ""
    failure_reason: str = ""

    @property
    def passed(self) -> bool:
        """仅当类型结构匹配且所有前提均证明为真时返回真。"""

        return self.verdict is Verdict.TRUE

    @property
    def structurally_matched(self) -> bool:
        """给定 Type 已连同全部先行 premise 被规则递归完整消费时返回真。

        公式在结构递归之前被明确否证时也会返回假；因此本属性表示“完整检查已
        形成结论”，而不是单独隔离公式后的纯语法形状判断。
        """

        return self.evidence.constructed_type is not None

    def format_detailed(self) -> str:
        """显示给定 Type 的规则匹配、公式义务和证明结果。

        证明证据的底层布局由 common 层提供，以确保 FOL/dL 公式不会在
        两套功能间出现不同的编号或遗漏；业务术语由共享 formatter 的
        ``checking`` 模式直接生成，不再依赖字符串替换。
        """

        return self.evidence.format_detailed(
            purpose="checking",
            displayed_type=self.expected_type,
        )
