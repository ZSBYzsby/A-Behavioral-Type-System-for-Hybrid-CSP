r"""Table 3 状态转移图的领域数据结构。

图边分为无时间消耗的 ``SilentTransitionLabel`` 和携带精确时长、ready set 的
``TimedTransitionLabel``。相同源、标签和目标可能由多个规则实例推出，因而一条边
保存一组 ``TransitionDerivation``，既压缩重复图边又不丢失推导证据。状态只保存
连续编号和规范 Type 展示代表；等递归项图状态键属于后端遍历过程，不泄漏进结果。

本模块验证标签、节点编号和边端点等局部结构，不负责重新执行 Table 3 或证明整张图
确为完整可达闭包；这项保证由唯一公共构造入口和操作语义后端共同提供。
"""

from __future__ import annotations

from dataclasses import dataclass
from enum import Enum
from fractions import Fraction
from typing import Iterable, TypeAlias

from ...identifiers import is_hcsp_identifier
from ..normalized_type_ast import NormalizedConfigurationType


class CommunicationDirection(str, Enum):
    """ready action 的输入或输出方向。"""

    INPUT = "?"
    OUTPUT = "!"


@dataclass(frozen=True, slots=True)
class ReadyAction:
    """等待期间对环境开放的一个带方向信道动作。"""

    channel: str
    direction: CommunicationDirection

    def __post_init__(self) -> None:
        """验证通道名称和通信方向属于项目支持的词法/枚举范围。"""

        if not is_hcsp_identifier(self.channel):
            raise ValueError("Ready-action channel must be an HCSP identifier")
        if not isinstance(self.direction, CommunicationDirection):
            raise TypeError("Ready-action direction must be CommunicationDirection")

    def complement(self) -> "ReadyAction":
        """返回同一通道、相反输入输出方向的互补 ready action。"""

        direction = (
            CommunicationDirection.OUTPUT
            if self.direction is CommunicationDirection.INPUT
            else CommunicationDirection.INPUT
        )
        return ReadyAction(self.channel, direction)


class InfiniteTime(str, Enum):
    """与有限 ``Fraction`` 分离表示的唯一正无穷时间值。"""

    VALUE = "infinity"


TimeDuration: TypeAlias = Fraction | InfiniteTime


@dataclass(frozen=True, slots=True)
class SilentTransitionLabel:
    """Table 3 中不消耗时间的无标签转移 ``mathcal T -> mathcal T'``。"""


@dataclass(frozen=True, slots=True, init=False)
class TimedTransitionLabel:
    r"""Table 3 的时间转移标签 ``\xrightarrow{d,R}``。"""

    duration: TimeDuration
    ready: frozenset[ReadyAction]

    def __init__(
        self,
        duration: Fraction | int | InfiniteTime,
        ready: Iterable[ReadyAction],
    ) -> None:
        """规范正有理/无穷时长并冻结 ready set。"""

        if isinstance(duration, bool):
            raise TypeError("Timed transition duration must not be Boolean")
        if isinstance(duration, int):
            normalized_duration: TimeDuration = Fraction(duration)
        elif isinstance(duration, (Fraction, InfiniteTime)):
            normalized_duration = duration
        else:
            raise TypeError("Timed duration must be Fraction, int, or InfiniteTime")
        if isinstance(normalized_duration, Fraction) and normalized_duration <= 0:
            raise ValueError("Timed transition duration must be strictly positive")
        ready_set = frozenset(ready)
        if not all(isinstance(action, ReadyAction) for action in ready_set):
            raise TypeError("Timed ready set must contain ReadyAction values")
        object.__setattr__(self, "duration", normalized_duration)
        object.__setattr__(self, "ready", ready_set)


TransitionLabel: TypeAlias = SilentTransitionLabel | TimedTransitionLabel


class Table3Rule(str, Enum):
    """循环项图状态图中实际生成边证据的 Table 3 规则。"""

    COMMUNICATION = "P-unrhd"
    TIMEOUT = "P-triangleright"
    INTERNAL_CHOICE = "P-sqcup"
    DELAY = "P-unrhd-prime"
    PARALLEL_TIME = "P-parallel"


@dataclass(frozen=True, slots=True)
class TransitionDerivation:
    """一条状态图边的一次具体 Table 3 规则应用证据。

    ``component_indices`` 与 ``branch_indices`` 均引用该边源状态所展示的规范
    Type AST，而不是后端循环项图的内部结点或子边编号。通信证据中的两个元组
    按相同位置配对：第 ``i`` 个分量采用第 ``i`` 个中断分支。``premises`` 保存
    ``P-parallel`` 等组合规则的直接子证据，不额外制造递归展开边。
    """

    rule: Table3Rule
    component_indices: tuple[int, ...] = ()
    branch_indices: tuple[int, ...] = ()
    channel: str | None = None
    premises: tuple["TransitionDerivation", ...] = ()

    def __post_init__(self) -> None:
        """验证规则标签、索引、可选通道和递归前提证据的结构。"""

        if not isinstance(self.rule, Table3Rule):
            raise TypeError("Transition derivation requires a Table3Rule")
        for value in self.component_indices + self.branch_indices:
            if isinstance(value, bool) or not isinstance(value, int) or value < 0:
                raise ValueError("Transition derivation indices must be non-negative ints")
        if self.channel is not None and not is_hcsp_identifier(self.channel):
            raise ValueError("Transition derivation channel must be an HCSP identifier")
        if not all(
            isinstance(premise, TransitionDerivation) for premise in self.premises
        ):
            raise TypeError("Transition derivation premises must be derivations")


@dataclass(frozen=True, slots=True)
class TypeState:
    """由编号引用的等递归状态及其项图确定性生成的规范 AST 展示代表。"""

    id: int
    type_ast: NormalizedConfigurationType

    def __post_init__(self) -> None:
        """验证非负状态编号和规范化配置根。"""

        if isinstance(self.id, bool) or not isinstance(self.id, int) or self.id < 0:
            raise ValueError("Type-state id must be a non-negative integer")
        if not isinstance(self.type_ast, NormalizedConfigurationType):
            raise TypeError("Type state must contain a normalized configuration")


@dataclass(frozen=True, slots=True)
class TypeTransition:
    """连接两个状态编号并保存全部等价规则应用证据的有向边。"""

    source: int
    target: int
    label: TransitionLabel
    derivations: tuple[TransitionDerivation, ...]

    def __post_init__(self) -> None:
        """验证端点、标签类别和至少一份规则推导证据。"""

        for endpoint in (self.source, self.target):
            if isinstance(endpoint, bool) or not isinstance(endpoint, int) or endpoint < 0:
                raise ValueError("Transition endpoints must be non-negative integers")
        if not isinstance(self.label, (SilentTransitionLabel, TimedTransitionLabel)):
            raise TypeError("Transition label must be silent or timed")
        if not self.derivations or not all(
            isinstance(item, TransitionDerivation) for item in self.derivations
        ):
            raise ValueError("Transition requires at least one derivation witness")


@dataclass(frozen=True, slots=True)
class TypeTransitionGraph:
    """按等递归状态取商后的完整关键-deadline约化有向图。

    ``states`` 必须按 ``0..n-1`` 连续编号，``initial_state`` 和每条边端点必须引用
    其中的状态。正常公共构造保证 ``transitions`` 是从初态出发的完整可达闭包。
    """

    initial_state: int
    states: tuple[TypeState, ...]
    transitions: tuple[TypeTransition, ...]

    def __post_init__(self) -> None:
        """验证连续状态编号和合法边端点。"""

        if not self.states:
            raise ValueError("Type transition graph requires at least one state")
        expected_ids = tuple(range(len(self.states)))
        actual_ids = tuple(state.id for state in self.states)
        if actual_ids != expected_ids:
            raise ValueError("Type transition graph state ids must be contiguous")
        if self.initial_state not in expected_ids:
            raise ValueError("Initial state id is not present in the graph")
        if any(
            edge.source not in expected_ids or edge.target not in expected_ids
            for edge in self.transitions
        ):
            raise ValueError("Type transition refers to an unknown state")

    def outgoing(self, state_id: int) -> tuple[TypeTransition, ...]:
        """按图内稳定顺序返回指定状态的全部出边；未知编号抛出 ``KeyError``。"""

        if state_id < 0 or state_id >= len(self.states):
            raise KeyError(f"Unknown type-state id: {state_id}")
        return tuple(edge for edge in self.transitions if edge.source == state_id)
