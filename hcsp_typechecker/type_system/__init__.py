"""行为类型 AST 及其纯结构操作。

该内部层独立保存论文中的类型结构，未来针对 Type AST 的规范化、分析和变换
实现应继续放在这里，而不反向依赖 Process 解析器或类型推导器。普通用户通过
包根接口取得 ``TypeAST``，不依赖这里的具体节点导入路径。
"""

from .ast import (
    AngelicType,
    BehavioralType,
    BottomType,
    CommunicationTimeoutType,
    ConfigurationType,
    EndType,
    ExternalChoiceType,
    InputType,
    InternalChoiceType,
    MuType,
    OutputType,
    ParallelType,
    ProcessType,
    PureDelayType,
    TimedExternalChoiceType,
    TypeVar,
    make_external_choice,
    make_timed_type,
    types_equivalent,
)

__all__ = [
    "AngelicType",
    "BehavioralType",
    "BottomType",
    "CommunicationTimeoutType",
    "ConfigurationType",
    "EndType",
    "ExternalChoiceType",
    "InputType",
    "InternalChoiceType",
    "MuType",
    "OutputType",
    "ParallelType",
    "ProcessType",
    "PureDelayType",
    "TimedExternalChoiceType",
    "TypeVar",
    "make_external_choice",
    "make_timed_type",
    "types_equivalent",
]
