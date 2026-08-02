r"""论文 Section 4.1/4.2 行为类型的规范化抽象语法树。

────────────────── 论文类型语法与规范节点 ────────────────────────────────────

论文首先给出统一的过程类型产生式：

.. code-block:: text

    T ::= delay(delta) \unrhd A \triangleright T
        | T \sqcup T'
        | t
        | mu t.T
        | \bot

    A ::= 0
        | A \sqcap ch?.T
        | A \sqcap ch!.T

随后给出三个定义式缩写：

.. code-block:: text

    A                    := delay(infinity) \unrhd A \triangleright \bot
    delay(d) \unrhd A    := delay(d) \unrhd A \triangleright \bot
    delay(d).T            := delay(d) \unrhd 0 \triangleright T

本项目的类型来自 HCSP 推导。为了让 AST 节点直接说明推导得到的是哪一种行为，
本模块不使用一个含 ``duration/choices/fallback`` 的通用节点，而把上述互斥情况
规范化为：

* ``EndType``、``InputType``、``OutputType``、``ExternalChoiceType`` 表示 ``A``；
* ``PureDelayType`` 表示 ``delay(d).T``，即没有通信分支的纯等待；
* ``CommunicationTimeoutType`` 表示 ``delay(d) \unrhd A``，其正常后继为 ``\bot``；
* ``TimedExternalChoiceType`` 表示同时具有非空 ``A`` 和正常后继 ``T`` 的完整式；
* ``InternalChoiceType``、``TypeVar``、``MuType``、``BottomType`` 表示其余 ``T``；
* ``ParallelType`` 表示 Section 4.2 的组合配置类型 ``mathcal T``。

当 ``delta = infinity`` 时，超时事件永远不会发生，process 到 type 的转换会把
超时后继固定为 ``\bot``，再按论文定义式规范成 ``A``。因此 AST 不保存不可达的
``T``。有限时延统一保存为非负 ``Fraction``，观察节点类即可区分纯等待、通信
超时和带自然结束后继的定时外部选择。

────────────────── 规范 AST 的抽象架构 ───────────────────────────────────

Python 继承层次显式保存论文 ``mathcal T``、``T``、``A`` 的包含方向：任意
``A`` 都可按论文的无限等待缩写作为 ``T``，任意 ``T`` 都可作为单个配置类型
``mathcal T``；反方向不成立，尤其不能把并行 ``mathcal T`` 放入要求 ``T`` 的
通信后继、内部选择或递归体。

.. code-block:: text

    BehavioralType
    `-- ConfigurationType                         mathcal T
        |-- ProcessType                           T
        |   |-- AngelicType                       A
        |   |   |-- EndType                       0
        |   |   |-- InputType                     ch?.T
        |   |   |-- OutputType                    ch!.T
        |   |   `-- ExternalChoiceType            A1 \sqcap ... \sqcap An
        |   |-- BottomType                        \bot
        |   |-- TypeVar                           t
        |   |-- InternalChoiceType                T \sqcup T'
        |   |-- PureDelayType                     delay(d).T
        |   |-- CommunicationTimeoutType          delay(d) \unrhd A
        |   |-- TimedExternalChoiceType           delay(d) \unrhd A
        |   |                                      \triangleright T
        |   `-- MuType                            mu t.T
        `-- ParallelType                          mathcal T | mathcal T

上图四个抽象层只用于类别检查，不能实例化；缩进最深的类才是
实际保存在推导结果中的 AST 节点。``ParallelType`` 属于 ``ConfigurationType``
但不属于 ``ProcessType``，从继承结构上落实 ``T`` 与组合类型的边界。

────────────────── A 与 delay 的规范化决策 ───────────────────────────────

``make_external_choice`` 先根据通信分支数量为 ``A`` 选择唯一形状：

.. code-block:: text

    branches = 0       -> EndType()
    branches = 1       -> InputType(...) 或 OutputType(...)
    branches >= 2      -> ExternalChoiceType(...)

``make_timed_type(delta, A, T)`` 再完整划分统一 delay 产生式的状态空间：

.. code-block:: text

    delta = infinity                       -> A（超时后继固定为 \bot）
    delta < infinity, A = 0                -> PureDelayType(delta, T)
    delta < infinity, A != 0, T = \bot     -> CommunicationTimeoutType(delta, A)
    delta < infinity, A != 0, T != \bot    -> TimedExternalChoiceType(delta, A, T)

四种条件互斥且完备。具体 delay 节点的构造器还会拒绝属于其他分支的字段组合，
例如空 ``A`` 不能形成 ``CommunicationTimeoutType``，``\bot`` 后继不能形成
``TimedExternalChoiceType``。因此同一种论文类型不会出现多个 AST 表示。

────────────────── 构造责任与检查边界 ──────────────────────────────────────

``ConfigurationType`` 对应 ``mathcal T``，``ProcessType`` 对应 ``T``，
``AngelicType`` 对应可按论文缩写嵌入 ``T`` 的 ``A``。输入/输出节点是单分支
``A``；至少两个通信分支才使用 ``ExternalChoiceType``，而 ``EndType`` 是 ``0``
的唯一表示。

本文件只定义不可变类型 AST、规范化工厂与 alpha 等价比较，不执行 Table 2
类型推导。Gamma、Theta、路径条件和证明义务由 ``checker.py``、``logic.py``
与 dL 后端检查。与旧的宽松结果容器不同，每个具体节点仍会检查自身能够独立
判断的语法类别、分支数、有限时延和递归通信守卫条件。

────────────────────────────────────────────────────────────────────────────
"""

from __future__ import annotations

from abc import ABC, abstractmethod
from dataclasses import dataclass
from decimal import Decimal
from fractions import Fraction
from math import inf, isinf, isnan
from typing import Any, Iterable, Mapping


# --------------------------------------------------------------------------
# 论文对应：行为类型 T/A 与组合配置类型 mathcal T 的共同 Python 根节点。
# 构造方式：不直接实例化；使用下面的具体不可变节点。
# 构造检查：抽象 __str__ 使本类保持抽象，防止形成没有论文产生式的裸节点。
# --------------------------------------------------------------------------
class BehavioralType(ABC):
    """全部行为类型和组合配置类型的抽象共同接口。"""

    @abstractmethod
    def __str__(self) -> str:
        """返回稳定、接近论文记号的审计字符串。"""


# --------------------------------------------------------------------------
# 论文对应：Section 4.2 的组合配置类型 mathcal T。
# 构造方式：不直接实例化；ProcessType 与 ParallelType 是具体语法入口。
# 构造检查：继承抽象 __str__，所以不能单独形成无结构的 configuration 类型。
# --------------------------------------------------------------------------
class ConfigurationType(BehavioralType, ABC):
    """论文组合配置类型 ``mathcal T`` 的抽象 Python 层。"""


# --------------------------------------------------------------------------
# 论文对应：Section 4.1 的过程类型 T；任意 T 同时可作为一个 mathcal T。
# 构造方式：不直接实例化；使用 End/Input/Delay/Mu 等具体过程类型。
# 构造检查：继承抽象 __str__，阻止绕过具体产生式构造裸 T。
# --------------------------------------------------------------------------
class ProcessType(ConfigurationType, ABC):
    """论文单进程行为类型 ``T`` 的抽象 Python 层。"""


# --------------------------------------------------------------------------
# 论文对应：Section 4.1 的 angelic type A；论文定义 A 为无限等待过程类型的缩写。
# 构造方式：使用 EndType、InputType、OutputType 或 ExternalChoiceType。
# 构造检查：本层保持抽象；四个具体节点给 A 建立唯一规范表示。
# --------------------------------------------------------------------------
class AngelicType(ProcessType, ABC):
    """可按论文定义式作为过程类型使用的 angelic type ``A``。"""


# --------------------------------------------------------------------------
# 论文对应：A ::= 0；Table 2 [T-End] 也把终端 skip 推导为同一个 0。
# 构造方式：EndType()。
# 构造检查：无字段；这是 0 的唯一 AST 表示，空 ExternalChoiceType 被禁止。
# --------------------------------------------------------------------------
@dataclass(frozen=True)
class EndType(AngelicType):
    """空 angelic choice／正常终止类型 ``0``。"""

    def __str__(self) -> str:
        """使用论文记号显示唯一的 ``0``。"""
        return "0"


# --------------------------------------------------------------------------
# 论文对应：Section 4.1 的底行为 \bot，即空 demonic choice/异常终止。
# 构造方式：BottomType()。
# 构造检查：无字段；它是正式过程类型，不等同于 Verdict.FALSE，也绝不作为
#           类型推导失败的恢复占位符；推导失败在 CheckReport 中表示为 None。
# --------------------------------------------------------------------------
@dataclass(frozen=True)
class BottomType(ProcessType):
    r"""论文中的底行为 ``\bot``。"""

    def __str__(self) -> str:
        """使用未渲染 LaTeX 记号显示底行为。"""
        return r"\bot"


# --------------------------------------------------------------------------
# 论文对应：过程类型变量 t；Table 2 [T-X] 从递归进程变量推导它。
# 构造方式：TypeVar("t")，正常由 TypeChecker 分配新鲜名称。
# 构造检查：名称必须是非空字符串；自由/绑定关系由 MuType 与 _type_key 解释。
# --------------------------------------------------------------------------
@dataclass(frozen=True)
class TypeVar(ProcessType):
    """递归行为类型中的变量引用 ``t``。"""

    name: str

    def __post_init__(self) -> None:
        """拒绝不能在审计输出和绑定环境中辨识的空变量名。"""
        if not isinstance(self.name, str) or not self.name.strip():
            raise ValueError("Type variable name must be a non-empty string")

    def __str__(self) -> str:
        """打印递归类型变量名称。"""
        return self.name


# --------------------------------------------------------------------------
# 论文对应：A 中的单输入同步分支 ch?.T；扩展后的 [T-In] 可在该次同步中接收
#           多个标量，但元数/槽位类型保存在 Theta，不进入行为类型。
# 构造方式：InputType(channel, continuation)。
# 构造检查：通道名必须是合法标识符，continuation 必须属于过程类型 T，不能是并行 mathcal T。
# --------------------------------------------------------------------------
@dataclass(frozen=True)
class InputType(AngelicType):
    """一次输入同步的 angelic type ``ch?.T``，载荷签名由 Theta 决定。"""

    channel: str
    continuation: ProcessType

    def __post_init__(self) -> None:
        """验证输入前缀的通道和顺序过程后继类别。"""
        if not isinstance(self.channel, str) or not self.channel.isidentifier():
            raise ValueError("Input type channel must be a valid identifier")
        if not isinstance(self.continuation, ProcessType):
            raise TypeError("Input type continuation must be a process type T")

    def __str__(self) -> str:
        """按论文通信前缀记号打印输入类型。"""
        return f"{self.channel}?.{self.continuation}"


# --------------------------------------------------------------------------
# 论文对应：A 中的单输出同步分支 ch!.T；扩展后的 [T-Out] 可在该次同步中发送
#           多个标量，但元数/槽位类型保存在 Theta，不进入行为类型。
# 构造方式：OutputType(channel, continuation)。
# 构造检查：通道名必须是合法标识符，continuation 必须属于过程类型 T。
# --------------------------------------------------------------------------
@dataclass(frozen=True)
class OutputType(AngelicType):
    """一次输出同步的 angelic type ``ch!.T``，载荷签名由 Theta 决定。"""

    channel: str
    continuation: ProcessType

    def __post_init__(self) -> None:
        """验证输出前缀的通道和顺序过程后继类别。"""
        if not isinstance(self.channel, str) or not self.channel.isidentifier():
            raise ValueError("Output type channel must be a valid identifier")
        if not isinstance(self.continuation, ProcessType):
            raise TypeError("Output type continuation must be a process type T")

    def __str__(self) -> str:
        """按论文通信前缀记号打印输出类型。"""
        return f"{self.channel}!.{self.continuation}"


# 论文对应：A 递归产生式中可以追加的 ch?.T 或 ch!.T 分支。
# 功能：为 ExternalChoiceType 与 make_external_choice 声明精确分支类别。
# 构造检查：别名本身不执行检查，两个使用方都会执行显式 isinstance 验证。
CommunicationType = InputType | OutputType


# --------------------------------------------------------------------------
# 论文对应：至少两个通信分支组成的 A1 \sqcap ... \sqcap An。
# 构造方式：ExternalChoiceType((InputType(...), OutputType(...), ...))。
# 构造检查：至少两个分支且每个分支必须是 InputType/OutputType；0 和单分支分别
#           由 EndType、InputType/OutputType 唯一表示。
# --------------------------------------------------------------------------
@dataclass(frozen=True)
class ExternalChoiceType(AngelicType):
    """至少两个由环境通信决定的 angelic choice 分支。"""

    branches: tuple[CommunicationType, ...]

    def __init__(self, branches: Iterable[CommunicationType]):
        """冻结多分支外部选择，并拒绝非规范的空、单分支或非通信分支。"""
        items = tuple(branches)
        if len(items) < 2:
            raise ValueError(
                "ExternalChoiceType requires at least two communication branches; "
                "use EndType/InputType/OutputType for zero or one branch"
            )
        if not all(isinstance(item, (InputType, OutputType)) for item in items):
            raise TypeError(
                "External choice branches must be InputType or OutputType"
            )
        object.__setattr__(self, "branches", items)

    def __str__(self) -> str:
        r"""使用 ``\sqcap`` 连接全部通信分支。"""
        return r" \sqcap ".join(str(branch) for branch in self.branches)


# 论文对应：A ::= 0 | A \sqcap ch?.T | A \sqcap ch!.T 的规范化构造入口。
# 功能：根据通信分支数返回唯一的 End/Input/Output/ExternalChoice 节点。
# 构造检查：拒绝非通信分支，避免同一个 A 拥有多种 AST 形状。
def make_external_choice(branches: Iterable[CommunicationType]) -> AngelicType:
    """把零个、一个或多个通信分支规范成唯一的 angelic type 节点。"""

    items = tuple(branches)
    if not all(isinstance(item, (InputType, OutputType)) for item in items):
        raise TypeError("Angelic choice branches must be InputType or OutputType")
    if not items:
        return EndType()
    if len(items) == 1:
        return items[0]
    return ExternalChoiceType(items)


# --------------------------------------------------------------------------
# 论文对应：过程类型 T \sqcup T'；Table 2 [T-If]/[T-\sqcup] 产生它。
# 构造方式：InternalChoiceType((left, right, ...))；二元嵌套会被结合律压平。
# 构造检查：压平后至少两个分支，每个分支必须是 ProcessType，不能放入 ParallelType。
# --------------------------------------------------------------------------
@dataclass(frozen=True)
class InternalChoiceType(ProcessType):
    """由程序内部非确定性决定的 demonic/internal choice。"""

    branches: tuple[ProcessType, ...]

    def __init__(self, branches: Iterable[ProcessType]):
        """压平嵌套内部选择，并验证分支数量与 T 语法类别。"""
        flat: list[ProcessType] = []
        for branch in branches:
            if isinstance(branch, InternalChoiceType):
                flat.extend(branch.branches)
            elif isinstance(branch, ProcessType):
                flat.append(branch)
            else:
                raise TypeError("Internal choice branches must be process types T")
        if len(flat) < 2:
            raise ValueError("InternalChoiceType requires at least two branches")
        object.__setattr__(self, "branches", tuple(flat))

    def __str__(self) -> str:
        r"""使用论文 ``\sqcup`` 记号连接并括住每个内部选择分支。"""
        return r" \sqcup ".join(f"({branch})" for branch in self.branches)


# 论文对应：所有有限 delay 构造均要求 0 <= d < infinity，且 d 是常量。
# 功能：把常用 Python 有理输入规范化为精确 Fraction。
# 构造检查：拒绝 Bool、负数、NaN、无穷和非数值对象；无穷由 make_timed_type 处理。
def _normalize_finite_duration(duration: Any) -> Fraction:
    """验证并返回一个精确的非负有限有理时延。"""

    if isinstance(duration, bool):
        raise ValueError("Type duration must be rational, not Boolean")
    if isinstance(duration, Fraction):
        value = duration
    elif isinstance(duration, int):
        value = Fraction(duration)
    elif isinstance(duration, Decimal):
        if duration.is_nan() or duration.is_infinite():
            raise ValueError("Type duration must be a finite rational number")
        value = Fraction(duration)
    elif isinstance(duration, float):
        if isnan(duration) or isinf(duration):
            raise ValueError("Type duration must be a finite rational number")
        value = Fraction(str(duration))
    else:
        raise TypeError("Type duration must be a rational number")
    if value < 0:
        raise ValueError("Type duration must be non-negative")
    return value


# 论文对应：缩写 delay(d).T := delay(d) \unrhd 0 \triangleright T。
# 构造方式：PureDelayType(duration, continuation)。
# 构造检查：duration 必须有限非负，continuation 必须是 T；它允许 BottomType，
#           从而唯一表示 delay(d) \unrhd 0 的退化情况。
# --------------------------------------------------------------------------
@dataclass(frozen=True)
class PureDelayType(ProcessType):
    """没有通信分支、到时后进入 ``T`` 的纯等待类型 ``delay(d).T``。"""

    duration: Fraction
    continuation: ProcessType

    def __init__(self, duration: Any, continuation: ProcessType):
        """规范化有限时延并验证纯等待的过程类型后继。"""
        if not isinstance(continuation, ProcessType):
            raise TypeError("Pure delay continuation must be a process type T")
        object.__setattr__(self, "duration", _normalize_finite_duration(duration))
        object.__setattr__(self, "continuation", continuation)

    def __str__(self) -> str:
        """使用论文的点号缩写显示纯等待。"""
        return f"delay({self.duration}).({self.continuation})"


# 论文对应：缩写 delay(d) \unrhd A := delay(d) \unrhd A \triangleright \bot。
# 构造方式：CommunicationTimeoutType(duration, choices)。
# 构造检查：duration 必须有限非负；A 必须非空，因为空 A 由 PureDelayType(d, \bot)
#           唯一表示。
# --------------------------------------------------------------------------
@dataclass(frozen=True)
class CommunicationTimeoutType(ProcessType):
    r"""必须在有限 ``d`` 内通信、否则进入 ``\bot`` 的超时类型。"""

    duration: Fraction
    choices: AngelicType

    def __init__(self, duration: Any, choices: AngelicType):
        """规范化有限时延，并要求至少存在一个通信分支。"""
        if not isinstance(choices, AngelicType):
            raise TypeError("Communication timeout choices must be an angelic type A")
        if isinstance(choices, EndType):
            raise ValueError(
                "Empty timeout choices must use PureDelayType(duration, BottomType())"
            )
        object.__setattr__(self, "duration", _normalize_finite_duration(duration))
        object.__setattr__(self, "choices", choices)

    def __str__(self) -> str:
        """使用论文无正常后继的通信超时缩写。"""
        return f"delay({self.duration}) \\unrhd {self.choices}"


# 论文对应：完整的 delay(d) \unrhd A \triangleright T，其中 A 非空且 T != \bot。
# 构造方式：TimedExternalChoiceType(duration, choices, fallback)。
# 构造检查：duration 必须有限非负；空 A 应使用 PureDelayType，bottom fallback
#           应使用 CommunicationTimeoutType，从而保持三个 delay 节点互斥。
# --------------------------------------------------------------------------
@dataclass(frozen=True)
class TimedExternalChoiceType(ProcessType):
    """同时具有通信分支和正常到时后继的有限定时外部选择。"""

    duration: Fraction
    choices: AngelicType
    fallback: ProcessType

    def __init__(
        self,
        duration: Any,
        choices: AngelicType,
        fallback: ProcessType,
    ):
        """验证完整定时选择不是纯等待或无 fallback 的缩写情况。"""
        if not isinstance(choices, AngelicType):
            raise TypeError("Timed choices must be an angelic type A")
        if isinstance(choices, EndType):
            raise ValueError("Empty timed choices must use PureDelayType")
        if not isinstance(fallback, ProcessType):
            raise TypeError("Timed fallback must be a process type T")
        if isinstance(fallback, BottomType):
            raise ValueError("Bottom fallback must use CommunicationTimeoutType")
        object.__setattr__(self, "duration", _normalize_finite_duration(duration))
        object.__setattr__(self, "choices", choices)
        object.__setattr__(self, "fallback", fallback)

    def __str__(self) -> str:
        """完整显示通信选择和正常到时后继。"""
        return (
            f"delay({self.duration}) \\unrhd {self.choices} "
            f"\\triangleright {self.fallback}"
        )


# 论文对应：统一产生式 delay(delta) \unrhd A \triangleright T 及三个定义式缩写。
# 功能：把推导规则的 delta/A/T 结果分派成互斥具体节点；本函数不是 AST 节点。
# 构造检查：正无穷把不可达的超时后继规范为 bottom 并返回 A；有限情况按 A
#           是否为空、T 是否为 bottom 分派。
def make_timed_type(
    duration: Any,
    choices: AngelicType,
    fallback: ProcessType,
) -> ProcessType:
    """把论文统一时延产生式规范成一个语义明确的具体类型节点。"""

    if not isinstance(choices, AngelicType):
        raise TypeError("Timed choices must be an angelic type A")
    if not isinstance(fallback, ProcessType):
        raise TypeError("Timed fallback must be a process type T")

    if isinstance(duration, float) and isinf(duration):
        if duration > 0:
            # 论文的无限等待没有超时迁移；转换时把任何候选 fallback 规范为
            # bottom，再使用 A := delay(infinity) \unrhd A \triangleright bottom。
            return choices
        raise ValueError("Type duration cannot be negative infinity")
    if isinstance(duration, Decimal) and duration.is_infinite():
        if duration > 0:
            # Decimal 正无穷与 float 正无穷遵循同一不可超时语义。
            return choices
        raise ValueError("Type duration cannot be negative infinity")

    finite = _normalize_finite_duration(duration)
    if isinstance(choices, EndType):
        return PureDelayType(finite, fallback)
    if isinstance(fallback, BottomType):
        return CommunicationTimeoutType(finite, choices)
    return TimedExternalChoiceType(finite, choices, fallback)


# --------------------------------------------------------------------------
# 论文对应：过程类型产生式 mu t.T；递归变量必须受 angelic communication prefix 保护。
# 构造方式：MuType(variable, body)。
# 构造检查：名称非空、body 属于 T；若 body 引用该变量，则每条到该引用的路径
#           都必须先经过 InputType 或 OutputType。
# --------------------------------------------------------------------------
@dataclass(frozen=True)
class MuType(ProcessType):
    """满足通信守卫条件的最小不动点递归类型 ``mu t.T``。"""

    variable: str
    body: ProcessType

    def __post_init__(self) -> None:
        """验证递归绑定名称、过程类型体以及论文要求的通信守卫条件。"""
        if not isinstance(self.variable, str) or not self.variable.strip():
            raise ValueError("Recursive type variable must be a non-empty string")
        if not isinstance(self.body, ProcessType):
            raise TypeError("Recursive type body must be a process type T")
        if _contains_type_var(self.body, self.variable) and not _type_var_guarded(
            self.body,
            self.variable,
        ):
            raise ValueError(
                f"Recursive type variable {self.variable!r} is not communication-guarded"
            )

    def __str__(self) -> str:
        """按论文 ``mu`` 绑定记号显示递归类型。"""
        return f"mu {self.variable}.({self.body})"


# --------------------------------------------------------------------------
# 论文对应：Section 4.2 的 mathcal T ::= T | mathcal T | mathcal T。
# 构造方式：ParallelType((left, right, ...))；嵌套二元并行按结合律压平。
# 构造检查：压平后至少两个 configuration 分量；Gamma 分区仍由 [T-||] 检查。
# --------------------------------------------------------------------------
@dataclass(frozen=True)
class ParallelType(ConfigurationType):
    """至少两个 HCSP configuration 的组合类型 ``mathcal T``。"""

    components: tuple[ConfigurationType, ...]

    def __init__(self, components: Iterable[ConfigurationType]):
        """压平嵌套并行并验证组合类型的分量数量和语法层次。"""
        flat: list[ConfigurationType] = []
        for component in components:
            if isinstance(component, ParallelType):
                flat.extend(component.components)
            elif isinstance(component, ConfigurationType):
                flat.append(component)
            else:
                raise TypeError(
                    "Parallel components must be process or configuration types"
                )
        if len(flat) < 2:
            raise ValueError("ParallelType requires at least two components")
        object.__setattr__(self, "components", tuple(flat))

    def __str__(self) -> str:
        """使用论文并行竖线连接并括住每个配置类型。"""
        return " | ".join(f"({component})" for component in self.components)


# 功能：判断类型中是否存在指定名称的自由类型变量引用。
# 检查/论文关系：遇到同名 MuType 时停止，以遵守 mu t.T 的词法遮蔽。
def _contains_type_var(value: BehavioralType, name: str) -> bool:
    """递归查找未被同名内层 ``mu`` 遮蔽的类型变量。"""

    if isinstance(value, TypeVar):
        return value.name == name
    if isinstance(value, (InputType, OutputType)):
        return _contains_type_var(value.continuation, name)
    if isinstance(value, (ExternalChoiceType, InternalChoiceType)):
        return any(_contains_type_var(branch, name) for branch in value.branches)
    if isinstance(value, PureDelayType):
        return _contains_type_var(value.continuation, name)
    if isinstance(value, CommunicationTimeoutType):
        return _contains_type_var(value.choices, name)
    if isinstance(value, TimedExternalChoiceType):
        return _contains_type_var(
            value.choices,
            name,
        ) or _contains_type_var(value.fallback, name)
    if isinstance(value, MuType):
        return value.variable != name and _contains_type_var(value.body, name)
    if isinstance(value, ParallelType):
        return any(
            _contains_type_var(component, name)
            for component in value.components
        )
    return False


# 功能：检查目标类型变量的每条出现路径是否经过输入或输出通信前缀。
# 检查/论文关系：Delay、内部选择和并行本身不构成论文要求的通信守卫。
def _type_var_guarded(
    value: BehavioralType,
    name: str,
    under_communication: bool = False,
) -> bool:
    """递归验证指定类型变量的全部自由出现均受通信保护。"""

    if isinstance(value, TypeVar):
        return value.name != name or under_communication
    if isinstance(value, (InputType, OutputType)):
        return _type_var_guarded(value.continuation, name, True)
    if isinstance(value, (ExternalChoiceType, InternalChoiceType)):
        return all(
            _type_var_guarded(branch, name, under_communication)
            for branch in value.branches
        )
    if isinstance(value, PureDelayType):
        return _type_var_guarded(value.continuation, name, under_communication)
    if isinstance(value, CommunicationTimeoutType):
        return _type_var_guarded(value.choices, name, under_communication)
    if isinstance(value, TimedExternalChoiceType):
        return _type_var_guarded(
            value.choices,
            name,
            under_communication,
        ) and _type_var_guarded(value.fallback, name, under_communication)
    if isinstance(value, MuType):
        return value.variable == name or _type_var_guarded(
            value.body,
            name,
            under_communication,
        )
    if isinstance(value, ParallelType):
        return all(
            _type_var_guarded(component, name, under_communication)
            for component in value.components
        )
    return True


# 功能：把精确 Fraction 编码为稳定、无浮点误差的比较键。
# 检查/论文关系：确保论文中的同一个有理时延不会因输入表示不同而不等价。
def _duration_key(duration: Fraction) -> tuple[int, int]:
    """返回有限有理时延的最简分子和分母。"""
    return duration.numerator, duration.denominator


# 论文对应：mu t.T 是绑定结构，受绑定 t 的改名不改变递归类型。
# 功能：递归编码全部规范节点，用绑定层级替代受绑定变量的具体名称。
# 检查/论文关系：只实现 alpha 等价；选择和并行仍按保存顺序比较。
def _type_key(value: BehavioralType, bound: Mapping[str, int] | None = None) -> Any:
    """递归生成忽略递归绑定变量改名的规范结构键。"""

    current_bound = {} if bound is None else dict(bound)
    if isinstance(value, EndType):
        return ("end",)
    if isinstance(value, BottomType):
        return ("bottom",)
    if isinstance(value, TypeVar):
        if value.name in current_bound:
            return ("bound", current_bound[value.name])
        return ("free", value.name)
    if isinstance(value, InputType):
        return (
            "in",
            value.channel,
            _type_key(value.continuation, current_bound),
        )
    if isinstance(value, OutputType):
        return (
            "out",
            value.channel,
            _type_key(value.continuation, current_bound),
        )
    if isinstance(value, ExternalChoiceType):
        return (
            "external",
            tuple(_type_key(branch, current_bound) for branch in value.branches),
        )
    if isinstance(value, InternalChoiceType):
        return (
            "internal",
            tuple(_type_key(branch, current_bound) for branch in value.branches),
        )
    if isinstance(value, PureDelayType):
        return (
            "pure-delay",
            _duration_key(value.duration),
            _type_key(value.continuation, current_bound),
        )
    if isinstance(value, CommunicationTimeoutType):
        return (
            "communication-timeout",
            _duration_key(value.duration),
            _type_key(value.choices, current_bound),
        )
    if isinstance(value, TimedExternalChoiceType):
        return (
            "timed-external-choice",
            _duration_key(value.duration),
            _type_key(value.choices, current_bound),
            _type_key(value.fallback, current_bound),
        )
    if isinstance(value, MuType):
        nested_bound = dict(current_bound)
        nested_bound[value.variable] = len(current_bound)
        return ("mu", _type_key(value.body, nested_bound))
    if isinstance(value, ParallelType):
        return (
            "parallel",
            tuple(
                _type_key(component, current_bound)
                for component in value.components
            ),
        )
    raise TypeError(f"Unsupported behavioral type: {type(value).__name__}")


# 论文对应：比较 Section 4.1/4.2 规范类型是否仅有 mu 绑定变量改名差异。
# 功能：比较类型 AST 的 alpha 等价结构键。
# 检查/论文关系：不实现子类型、双模拟或选择/并行的交换律等价。
def types_equivalent(left: BehavioralType, right: BehavioralType) -> bool:
    """按规范结构比较类型，并忽略 ``mu`` 绑定变量的命名差异。"""
    return _type_key(left) == _type_key(right)
