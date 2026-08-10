"""Gamma、参数、Theta 片段到内部环境对象的前端转换入口。"""

from __future__ import annotations

from dataclasses import dataclass
from types import MappingProxyType
from typing import Mapping

from ..type_constructor_frontend.parser import Parser, _checked_source
from ...data_structures.runtime_context import (
    ChannelType,
    GammaType,
    ParameterEnvironment,
)


@dataclass(frozen=True, slots=True)
class ParsedTypingContext:
    """用户给定 Gamma、Theta、全局参数经 lowering 后的只读环境快照。"""

    gamma: Mapping[str, GammaType]
    theta: Mapping[str, ChannelType]
    parameters: ParameterEnvironment

    def __post_init__(self) -> None:
        """复制可变映射，避免调用者随后修改解析结果。"""

        object.__setattr__(self, "gamma", MappingProxyType(dict(self.gamma)))
        object.__setattr__(self, "theta", MappingProxyType(dict(self.theta)))
        if not isinstance(self.parameters, ParameterEnvironment):
            raise TypeError("parameters must be a ParameterEnvironment")
        object.__setattr__(
            self,
            "parameters",
            ParameterEnvironment(
                self.parameters.declarations,
                self.parameters.constraint,
            ),
        )


def parse_typing_context(
    source: str,
    *,
    source_name: str = "<typing-context>",
) -> ParsedTypingContext:
    """解析 ``gamma [parameters] theta``，并要求片段随后结束。

    这与完整 source 使用完全相同的声明检查，包括连续向量、参数与 Gamma 的
    名称冲突、通道 binder 和 refinement 的结构检查。
    """

    parser = Parser(_checked_source(source, source_name), source_name)
    gamma = parser._parse_gamma_section()
    parameters = (
        parser._parse_parameter_section(forbidden_names=frozenset(gamma))
        if parser.current.kind == "parameters"
        else ParameterEnvironment()
    )
    theta = parser._parse_theta_section()
    parser._expect("EOF")
    return ParsedTypingContext(gamma, theta, parameters)
