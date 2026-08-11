"""等递归状态判重使用的有限循环 Type 项图数据结构。

``RegularTypeTermGraph`` 保存规范 Type 到循环图的直接编译结果；
``EquiRecursiveStateKey`` 保存双模拟最小化、选择再规范化和稳定重编号后的状态键。
本子包只定义节点与图的不变量，转换、最小化和展示重建算法位于
操作语义层的 ``regular_tree.py``。
"""

from .model import (
    CanonicalRegularTypeNode,
    EquiRecursiveStateKey,
    RegularTypeNode,
    RegularTypeNodeKind,
    RegularTypeTermGraph,
)

__all__ = [
    "CanonicalRegularTypeNode",
    "EquiRecursiveStateKey",
    "RegularTypeNode",
    "RegularTypeNodeKind",
    "RegularTypeTermGraph",
]
