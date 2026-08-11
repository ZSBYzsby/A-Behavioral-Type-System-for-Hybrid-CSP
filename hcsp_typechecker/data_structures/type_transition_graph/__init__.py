"""行为 Type 的 Table 3 状态转移图数据结构。

本子包只定义图、状态、边标签和规则推导证据；从规范化 Type AST 计算后继及遍历
可达状态的算法位于后端 ``type_operational_semantics``。
"""

from .model import (
    CommunicationDirection,
    InfiniteTime,
    ReadyAction,
    SilentTransitionLabel,
    Table3Rule,
    TimedTransitionLabel,
    TransitionDerivation,
    TransitionLabel,
    TypeState,
    TypeTransition,
    TypeTransitionGraph,
)

__all__ = [
    "CommunicationDirection",
    "InfiniteTime",
    "ReadyAction",
    "SilentTransitionLabel",
    "Table3Rule",
    "TimedTransitionLabel",
    "TransitionDerivation",
    "TransitionLabel",
    "TypeState",
    "TypeTransition",
    "TypeTransitionGraph",
]
