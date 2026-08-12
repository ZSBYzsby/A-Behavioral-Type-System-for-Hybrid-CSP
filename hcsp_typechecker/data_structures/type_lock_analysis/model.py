"""类型状态迁移图上的死锁/活锁分析结果。

本文件只定义数据，不执行图搜索。反例被保存为真正的迁移对象序列，而不是
容易失效的状态编号字符串。这样，展示层可以同时输出迁移标签和 Table 3
推导证据，调用者也可以用程序检查路径是否连续。
"""

from __future__ import annotations

from dataclasses import dataclass

from ..type_transition_graph import (
    InfiniteTime,
    SilentTransitionLabel,
    TimedTransitionLabel,
    TypeTransition,
)


@dataclass(frozen=True, slots=True)
class TransitionPath:
    """一条首尾相接的有限图路径；空路径表示起点与终点相同。"""

    start_state: int
    transitions: tuple[TypeTransition, ...]
    end_state: int

    def __post_init__(self) -> None:
        """检查边序列确实从 ``start_state`` 连续到达 ``end_state``。"""

        if not isinstance(self.start_state, int) or self.start_state < 0:
            raise ValueError("TransitionPath.start_state must be a non-negative integer")
        if not isinstance(self.end_state, int) or self.end_state < 0:
            raise ValueError("TransitionPath.end_state must be a non-negative integer")
        transitions = tuple(self.transitions)
        object.__setattr__(self, "transitions", transitions)

        current = self.start_state
        for transition in transitions:
            if not isinstance(transition, TypeTransition):
                raise TypeError("TransitionPath entries must be TypeTransition values")
            if transition.source != current:
                raise ValueError(
                    "TransitionPath is not contiguous: "
                    f"expected an edge from S{current}, got S{transition.source}"
                )
            current = transition.target
        if current != self.end_state:
            raise ValueError(
                "TransitionPath endpoint mismatch: "
                f"the edges end at S{current}, not S{self.end_state}"
            )

    @property
    def state_ids(self) -> tuple[int, ...]:
        """按访问顺序返回路径上的状态编号。"""

        return (self.start_state,) + tuple(
            transition.target for transition in self.transitions
        )


@dataclass(frozen=True, slots=True)
class DeadlockWitness:
    """可达死锁状态及其带非空 ready 集的无限时间迁移。"""

    prefix: TransitionPath
    infinite_wait: TypeTransition

    def __post_init__(self) -> None:
        """检查见证满足论文定义中的 ``infinity`` 与非空 ready 条件。"""

        transition = self.infinite_wait
        if transition.source != self.prefix.end_state:
            raise ValueError("Deadlock witness prefix does not reach the waiting state")
        label = transition.label
        if not isinstance(label, TimedTransitionLabel):
            raise ValueError("Deadlock witness must end in a timed transition")
        if label.duration is not InfiniteTime.VALUE:
            raise ValueError("Deadlock witness must use an infinite-duration transition")
        if not label.ready:
            raise ValueError("Deadlock witness must have a non-empty ready set")


@dataclass(frozen=True, slots=True)
class LivelockWitness:
    """通向一个纯静默迁移环的可达前缀及非空环。"""

    prefix: TransitionPath
    cycle: TransitionPath

    def __post_init__(self) -> None:
        """检查前缀到达环入口，且环非空、闭合并只含静默边。"""

        if self.prefix.end_state != self.cycle.start_state:
            raise ValueError("Livelock witness prefix does not reach the cycle entry")
        if self.cycle.start_state != self.cycle.end_state:
            raise ValueError("Livelock witness cycle must be closed")
        if not self.cycle.transitions:
            raise ValueError("Livelock witness cycle must contain at least one transition")
        if any(
            not isinstance(transition.label, SilentTransitionLabel)
            for transition in self.cycle.transitions
        ):
            raise ValueError("Livelock witness cycle may contain only silent transitions")


@dataclass(frozen=True, slots=True)
class LockFreedomReport:
    """完整图上的死锁自由、活锁自由结论和可复查反例。"""

    reachable_state_count: int
    transition_count: int
    deadlock_witness: DeadlockWitness | None = None
    livelock_witness: LivelockWitness | None = None

    def __post_init__(self) -> None:
        """防止报告计数与见证结构出现明显不一致。"""

        if self.reachable_state_count < 1:
            raise ValueError("Lock-freedom analysis requires at least one reachable state")
        if self.transition_count < 0:
            raise ValueError("transition_count must be non-negative")

    @property
    def deadlock_free(self) -> bool:
        """不存在论文 Definition 4.5 所定义的可达死锁状态。"""

        return self.deadlock_witness is None

    @property
    def livelock_free(self) -> bool:
        """不存在论文 Definition 4.6 所定义的可达无限静默推导。"""

        return self.livelock_witness is None

    @property
    def lock_free(self) -> bool:
        """同时满足死锁自由与活锁自由。"""

        return self.deadlock_free and self.livelock_free
