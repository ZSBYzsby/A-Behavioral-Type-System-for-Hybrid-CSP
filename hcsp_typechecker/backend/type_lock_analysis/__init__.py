"""类型状态迁移图上的可扩展死锁/活锁分析后端。"""

from .analyzer import IncompleteTransitionGraphError, analyze_lock_freedom

__all__ = ["IncompleteTransitionGraphError", "analyze_lock_freedom"]
