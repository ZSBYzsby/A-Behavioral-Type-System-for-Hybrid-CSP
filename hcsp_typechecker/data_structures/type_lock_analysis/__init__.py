"""死锁/活锁分析结果及反例见证的数据结构。"""

from .model import (
    DeadlockWitness,
    LivelockWitness,
    LockFreedomReport,
    TransitionPath,
)

__all__ = [
    "DeadlockWitness",
    "LivelockWitness",
    "LockFreedomReport",
    "TransitionPath",
]
