"""HCSP 行为类型构造器的业务入口。

本模块只负责“从 Process AST 构造 Type AST”这一项业务。Table 2 的规则展开、
符号状态和证明基础设施位于 :mod:`hcsp_typechecker.backend.common`；这样未来的
TypeChecker 可以复用同一套规则，而不需要依赖 TypeConstructor 本身。
"""

from __future__ import annotations

from typing import Any, Mapping, Sequence

from ...data_structures.type_construction.model import (
    ChannelType,
    Configuration,
    DLChecker,
    GammaType,
    ParameterEnvironment,
    TypeConstructionReport,
    TypeConstructionRequest,
)
from ..common.keymaerax import KeYmaeraXConfig
from ..common.rule_engine import Table2RuleEngine


class TypeConstructor(Table2RuleEngine):
    """按项目采用的 Table 2 规则构造 HCSP 行为类型。"""

    def construct(
        self,
        request: TypeConstructionRequest,
    ) -> TypeConstructionReport:
        """构造候选 Type AST，并返回推导与证明的完整审计报告。"""

        return self._construct_type(request)


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
