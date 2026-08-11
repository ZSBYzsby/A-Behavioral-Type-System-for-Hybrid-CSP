"""TypeConstructor 与 TypeChecker 共用的类型环境准备结果。

Gamma、Theta 和全局参数都在进入 Table 2 业务递归前完成一次规范化。实际准备
算法由 :class:`Table2RuleEngine` 执行，因为它需要共享的表达式翻译器、Z3
证明器和审计记录；本模块只定义两个后端共同消费的不可变结果，避免它被错误
归入 Constructor 或 Checker 的业务模型。
"""

from __future__ import annotations

from dataclasses import dataclass
from typing import Any

from ...data_structures.runtime_context import BasicType, ChannelType, GammaType


@dataclass(frozen=True, slots=True)
class PreparedTypingEnvironment:
    """规范化并通过公共良构检查的 Gamma、Theta 与全局参数环境。"""

    gamma: dict[str, GammaType]
    theta: dict[str, ChannelType]
    parameters: dict[str, BasicType]
    parameter_symbols: dict[str, Any]
    parameter_condition: Any


__all__ = ["PreparedTypingEnvironment"]
