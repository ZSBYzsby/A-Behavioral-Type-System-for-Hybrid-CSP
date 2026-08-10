"""TypeConstructor 专属的请求模型与报告名称。

运行上下文来自 data_structures.runtime_context；证明证据来自 backend.common。
本模块只组织“构造 Type”这一业务所需的输入，并为共享规则报告提供业务名称。
"""

from __future__ import annotations

from dataclasses import dataclass
from typing import Any, Mapping, Sequence

from ...data_structures.runtime_context import (
    ChannelType,
    Configuration,
    GammaType,
    ParameterEnvironment,
)
from ..common.model import RuleDerivationReport

# --------------------------------------------------------------------------
# 论文对应：Section 4.2 的两类判断
#           ``Gamma·Theta·phi |- P :: T`` 与
#           ``Gamma·Theta·phi |- K :: mathcal T`` 的统一程序输入表示。
#           configurations 表示 P 或组合配置 K；path_condition 表示前提 phi。
# 判断对应：一次完整输入 Gamma、Theta、phi 和 configurations 的构造请求。
# 构造方式：TypeConstructionRequest(gamma, theta, configurations,
#                                   path_condition=True)。
# 构造检查：复制环境并把进程、(state, process) 简写统一包装为 Configuration；
#           环境项的具体类型规范化留给 TypeConstructor.construct。
# --------------------------------------------------------------------------
@dataclass(frozen=True, slots=True)
class TypeConstructionRequest:
    """一次完整的类型构造请求。

    对应 ``Gamma; Pi; Theta |- configurations : types``，其中 ``Pi``
    是可选的共享只读参数环境。请求只包含构造类型所需的左侧信息；由用户给定
    候选 Type AST 并判断其是否匹配属于独立 ``TypeChecker`` 的职责。
    """

    gamma: Mapping[str, GammaType]
    theta: Mapping[str, ChannelType | Any]
    configurations: tuple[Configuration, ...]
    path_condition: Any = True
    parameters: ParameterEnvironment = ParameterEnvironment()

    # 功能：把低层构造接口的多种配置写法规范化成不可变 Configuration 元组。
    # 构造/模型关系：请求不接收期望类型，Type AST 始终由规则从 Process AST 构造。
    def __init__(
        self,
        gamma: Mapping[str, GammaType] | None,
        theta: Mapping[str, ChannelType | Any] | None,
        configurations: Sequence[Configuration | tuple[Mapping[str, Any], Any] | Any],
        path_condition: Any = True,
        parameters: ParameterEnvironment | Mapping[str, Any] | None = None,
    ) -> None:
        """规范化环境与配置的多种便捷输入形式。"""
        normalized_configs: list[Configuration] = []
        for item in configurations:
            if isinstance(item, Configuration):
                normalized_configs.append(item)
            elif isinstance(item, tuple) and len(item) == 2 and isinstance(item[0], Mapping):
                normalized_configs.append(Configuration(item[0], item[1]))
            else:
                normalized_configs.append(Configuration({}, item))
        object.__setattr__(self, "gamma", {} if gamma is None else dict(gamma))
        object.__setattr__(self, "theta", {} if theta is None else dict(theta))
        object.__setattr__(self, "configurations", tuple(normalized_configs))
        object.__setattr__(self, "path_condition", path_condition)
        if parameters is None:
            parameter_environment = ParameterEnvironment()
        elif isinstance(parameters, ParameterEnvironment):
            parameter_environment = parameters
        elif isinstance(parameters, Mapping):
            parameter_environment = ParameterEnvironment(parameters)
        else:
            raise TypeError(
                "parameters must be a ParameterEnvironment, mapping, or None"
            )
        object.__setattr__(self, "parameters", parameter_environment)


@dataclass(frozen=True, slots=True)
class TypeConstructionReport(RuleDerivationReport):
    """TypeConstructor 的正式构造结果及其完整规则、证明证据。"""


__all__ = [
    "TypeConstructionReport",
    "TypeConstructionRequest",
]
