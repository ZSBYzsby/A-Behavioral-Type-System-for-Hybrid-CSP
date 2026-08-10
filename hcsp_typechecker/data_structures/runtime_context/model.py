"""运行上下文的语义分组定义。

Gamma、Theta 与共享参数的类与 TypeConstructor 请求/报告曾共同定义在同一模块。为
保证现有 AST、前端、构造器和测试始终使用同一组类对象，本模块重导出其既有定义，
并将运行上下文作为独立的数据结构层对外组织；后续若需要拆分实现文件，无需改变
任何使用方的导入边界。
"""

from ..type_construction.model import (
    BasicType,
    ChannelType,
    ContinuousType,
    GammaType,
    ParameterEnvironment,
    gamma_value_type,
    is_subtype,
    normalize_channel_type,
    normalize_gamma_type,
    normalize_type,
)

__all__ = [
    "BasicType",
    "ChannelType",
    "ContinuousType",
    "GammaType",
    "ParameterEnvironment",
    "gamma_value_type",
    "is_subtype",
    "normalize_channel_type",
    "normalize_gamma_type",
    "normalize_type",
]
