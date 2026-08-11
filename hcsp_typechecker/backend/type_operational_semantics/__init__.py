"""Table 3 行为 Type 操作语义与完整可达状态图生成后端。

本子包依次完成规范 Type 到循环项图的编译与双模拟最小化、循环项图上的一步规则
枚举，以及以等递归状态键为节点的 BFS 可达闭包。它只消费正式 Type AST，不读取
Process AST、Gamma、Theta、参数环境或证明器，也不执行后续死锁/活锁分析。
"""

from .graph_builder import (
    TypeTransitionGraphSizeError,
    build_type_transition_graph,
)
from .regular_tree import (
    build_regular_type_term_graph,
    equi_recursive_equivalent,
    equi_recursive_state_key,
    minimize_regular_type_term_graph,
    normalized_type_from_state_key,
)
from .table3 import DerivedTransition, derive_one_step

__all__ = [
    "DerivedTransition",
    "TypeTransitionGraphSizeError",
    "build_type_transition_graph",
    "build_regular_type_term_graph",
    "derive_one_step",
    "equi_recursive_equivalent",
    "equi_recursive_state_key",
    "minimize_regular_type_term_graph",
    "normalized_type_from_state_key",
]
