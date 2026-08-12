"""完整 HCSP 用户输入经过 lowering 后的聚合结果。

``ParsedHCSPSource`` 不建立第二套参数环境、Gamma、Theta 或 Process
AST。它只把同一份 source 中解析得到的现有
``ParameterEnvironment``、Gamma/Theta 映射和 Process/System AST 绑定在一起，
使调用方不会误配不同输入的对象。初始状态和路径条件仍不属于
concrete syntax，因此本记录不冒充内部 ``TypeConstructionRequest``。
"""

from __future__ import annotations

from dataclasses import dataclass, field
from types import MappingProxyType
from typing import Mapping

from ...data_structures.process_ast.ast import HCSP, Parallel, Process
from ...data_structures.runtime_context import (
    ChannelType,
    GammaType,
    ParameterEnvironment,
)


@dataclass(frozen=True, slots=True)
class ParsedHCSPSource:
    """一次完整用户 source 输入的四个正式模型结果。

    字段中的只读映射已经完成用户输入层能够独立执行的结构检查：声明名不重复，
    ``ContinuousType`` 的成员均有同一 Gamma 中的 ``Real`` 标量声明，并且每个
    ``ChannelType`` 都具有显式、互异且与槽位一一对应的 refinement binders。
    refinement 的自由变量解析和 Bool 静态检查仍由 Constructor/Checker 共用的
    完整环境准备阶段负责。
    """

    gamma: Mapping[str, GammaType]
    theta: Mapping[str, ChannelType]
    process: HCSP
    parameters: ParameterEnvironment = field(
        default_factory=ParameterEnvironment
    )

    def __post_init__(self) -> None:
        """防御性复制参数、Gamma 和 Theta，并暴露只读快照。"""

        object.__setattr__(
            self,
            "gamma",
            MappingProxyType(dict(self.gamma)),
        )
        object.__setattr__(
            self,
            "theta",
            MappingProxyType(dict(self.theta)),
        )
        if not isinstance(self.parameters, ParameterEnvironment):
            raise TypeError(
                "ParsedHCSPSource parameters must be a ParameterEnvironment"
            )
        object.__setattr__(
            self,
            "parameters",
            ParameterEnvironment(
                self.parameters.declarations,
                self.parameters.constraint,
            ),
        )

    @property
    def process_components(self) -> tuple[Process, ...]:
        """按源码顺序返回顶层并行系统的 Process 叶子。

        单分量 source 返回仅含 ``process`` 的元组。多分量 source 在
        ``process`` 字段中仍保留正式二元 ``Parallel`` AST；本属性只提供
        Table 2 的多 ``Configuration`` 入口所需的顶层叶子视图，不复制或
        改写 Process AST。
        """

        def flatten(system: HCSP) -> tuple[Process, ...]:
            """用显式栈展平顶层二元 Parallel，其他节点必须是 Process。"""

            components: list[Process] = []
            pending: list[HCSP] = [system]
            while pending:
                current = pending.pop()
                if isinstance(current, Parallel):
                    pending.append(current.right)
                    pending.append(current.left)
                    continue
                if not isinstance(current, Process):
                    raise TypeError(
                        "Parsed process system has a non-Process Parallel leaf: "
                        f"{type(current).__name__}"
                    )
                components.append(current)
            return tuple(components)

        return flatten(self.process)
