r"""Type System 层中 Section 4.1/4.2 行为类型的规范化抽象语法树。

────────────────── 论文类型语法与规范节点 ──────────────────────────────────

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

* ``NoInterruptType``、``InputType``、``OutputType``、``ExternalChoiceType`` 表示 ``A``；
* ``EmptyType`` 表示没有可观察信道通信的过程行为；``skip`` 构造它；
* ``FiniteDelayType`` 统一保存有限时延 ``delay(d) \unrhd A \triangleright T``；
  它的打印形式会按字段值采用论文缩写；
* ``InfiniteDelayType`` 显式保存 ``delay(infinity) \unrhd A \triangleright \bot``；
* ``InternalChoiceType``、``TypeVar``、``MuType``、``BottomType`` 表示其余 ``T``；
* ``ParallelType`` 表示 Section 4.2 的组合配置类型 ``mathcal T``。

当 ``delta = infinity`` 时，超时事件永远不会发生，process 到 type 的转换会把
超时后继固定为 ``\bot``，再按论文定义式规范成 ``A``。因此 AST 不保存不可达的
``T``。有限时延统一保存为非负 ``Fraction``；其 continuation 的
``BottomType``/普通 ``ProcessType`` 明确区分不可达 deadline 与真实自然后继。

────────────────── 规范 AST 的抽象架构 ─────────────────────────────────────

Python 继承层次把论文 ``mathcal T``、``T``、``A`` 分为三个独立语法范畴：任意
``T`` 可作为单个配置类型 ``mathcal T``，但 ``A`` 只能作为 delay 的中断字段。
论文把 ``A`` 写作无限等待 ``T`` 的缩写；本实现将该缩写显式建成
``InfiniteDelayType(A)``，避免把两种 AST 范畴混在一起。

.. code-block:: text

    BehavioralType
    |-- ConfigurationType                         mathcal T
    |   |-- ProcessType                           T
    |   |   |-- EmptyType                         0 (empty communication behavior)
    |   |   |-- BottomType                        \bot
    |   |   |-- TypeVar                           t
    |   |   |-- InternalChoiceType                T \sqcup T'
    |   |   |-- FiniteDelayType                   delay(d) \unrhd A \triangleright T
    |   |   |-- InfiniteDelayType                 delay(infinity) \unrhd A
    |   |   `-- MuType                            mu t.T
    |   `-- ParallelType                          mathcal T | mathcal T
    `-- AngelicType                               A
        |-- NoInterruptType                       empty A
        |-- InputType                             ch?.T
        |-- OutputType                            ch!.T
        `-- ExternalChoiceType                    A1 \sqcap ... \sqcap An

上图四个抽象层只用于类别检查，不能实例化；缩进最深的类才是
实际保存在推导结果中的 AST 节点。``ParallelType`` 属于 ``ConfigurationType``
但不属于 ``ProcessType``，从继承结构上落实 ``T`` 与组合类型的边界。

────────────────── A 与 delay 的规范化决策 ─────────────────────────────────

``make_external_choice`` 先根据通信分支数量为 ``A`` 选择唯一形状：

.. code-block:: text

    branches = 0       -> NoInterruptType()
    branches = 1       -> InputType(...) 或 OutputType(...)
    branches >= 2      -> ExternalChoiceType(...)

``make_delay_type(delta, A, T)`` 直接构造统一 delay 产生式：

.. code-block:: text

    delta = infinity                       -> InfiniteDelayType(A)
    delta < infinity                       -> FiniteDelayType(delta, A, T)

有限时延允许两类语义不同的后继：``BottomType`` 表示 `T-\unrhd` 保证不会
到达的 deadline；其他 ``ProcessType`` 表示 `T-\unrhd'` 的真实后继，其中
``EmptyType`` 是真实后继没有可观察通信行为的特例。构造器不能把二者合并。

────────────────── 构造责任与检查边界 ──────────────────────────────────────

``ConfigurationType`` 对应 ``mathcal T``，``ProcessType`` 对应 ``T``，
``AngelicType`` 对应独立的 ``A``。输入/输出节点是单分支
``A``；至少两个通信分支才使用 ``ExternalChoiceType``，空中断集合则使用
``NoInterruptType``。过程终止/无通信行为由独立的 ``EmptyType`` 表示。

本文件只定义不可变类型 AST、规范化工厂与 alpha 等价比较，不执行 Table 2
类型构造。Gamma、Theta、路径条件和证明义务由后端 ``rule_engine.py``、``logic.py``
与 dL 后端检查。每个具体节点只检查不依赖推导上下文即可判断的语法类别、
分支数、有限时延和递归通信守卫条件。

────────────────────────────────────────────────────────────────────────────
"""

from __future__ import annotations

from abc import ABC, abstractmethod
from dataclasses import dataclass
from decimal import Decimal
from fractions import Fraction
from math import inf, isinf, isnan
from typing import Any, Iterable, Mapping

from ...identifiers import is_hcsp_identifier

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
# 构造方式：不直接实例化；使用 Empty/Delay/Mu 等具体过程类型。
# 构造检查：继承抽象 __str__，阻止绕过具体产生式构造裸 T。
# --------------------------------------------------------------------------
class ProcessType(ConfigurationType, ABC):
    """论文单进程行为类型 ``T`` 的抽象 Python 层。"""


# --------------------------------------------------------------------------
# 论文对应：Section 4.1 的 angelic type A；它只用于 delay 的中断位置。
# 构造方式：使用 NoInterruptType、InputType、OutputType 或 ExternalChoiceType。
# 构造检查：本层保持抽象；四个具体节点给 A 建立唯一规范表示。
# --------------------------------------------------------------------------
class AngelicType(BehavioralType, ABC):
    """论文中的中断/外部选择类型 ``A``，不是过程类型 ``T``。"""


# --------------------------------------------------------------------------
# 论文对应：A 的空中断集合；它与 Table 2 [T-End] 的空过程行为分开建模。
# 构造方式：NoInterruptType()。
# 构造检查：无字段；空 ExternalChoiceType 被禁止并规范到此节点。
# --------------------------------------------------------------------------
@dataclass(frozen=True)
class NoInterruptType(AngelicType):
    """没有可发生通信中断的 angelic type ``0``。

    该节点只可出现在 ``A`` 位置：它表示 ODE 的中断集合为空，不能表示
    ``skip`` 或任意已经结束的过程行为。
    """

    def __str__(self) -> str:
        """以空集显示没有可发生的通信中断。"""
        return r"\emptyset"


@dataclass(frozen=True)
class EmptyType(ProcessType):
    """不再发生信道通信的空过程行为 ``epsilon``。

    Table 2 的 ``skip``、赋值和断言等静默过程的终点均构造此节点。它和
    ``NoInterruptType`` 分属 ``T``、``A`` 两个不同语法范畴，因而不能互换。
    """

    def __str__(self) -> str:
        """保留 Table 2 对 skip/空过程通信行为使用的 ``0`` 记号。"""
        return "0"


# --------------------------------------------------------------------------
# 论文对应：Section 4.1 的底行为 \bot，即空 demonic choice/异常终止。
# 构造方式：BottomType()。
# 构造检查：无字段；它是正式过程类型，不等同于 Verdict.FALSE，也绝不作为
#           类型构造失败的恢复占位符；失败在 TypeConstructionReport 中表示为 None。
# --------------------------------------------------------------------------
@dataclass(frozen=True)
class BottomType(ProcessType):
    r"""论文中的底行为 ``\bot``。"""

    def __str__(self) -> str:
        """使用未渲染 LaTeX 记号显示底行为。"""
        return r"\bot"


# --------------------------------------------------------------------------
# 论文对应：过程类型变量 t；Table 2 [T-X] 从递归进程变量推导它。
# 构造方式：TypeVar("t")，正常由 TypeConstructor 分配新鲜名称。
# 构造检查：名称必须满足项目 ASCII IDENT；自由/绑定关系由 MuType 与 _type_key 解释。
# --------------------------------------------------------------------------
@dataclass(frozen=True)
class TypeVar(ProcessType):
    """递归行为类型中的变量引用 ``t``。"""

    name: str

    def __post_init__(self) -> None:
        """拒绝不满足项目 ASCII IDENT 的类型变量名。"""
        if not is_hcsp_identifier(self.name):
            raise ValueError("Type variable name must be a valid HCSP identifier")

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
        if not is_hcsp_identifier(self.channel):
            raise ValueError("Input type channel must be a valid identifier")
        if not isinstance(self.continuation, ProcessType):
            raise TypeError("Input type continuation must be a process type T")

    def __str__(self) -> str:
        """打印输入前缀，并用括号明确标出它所支配的完整后继类型。"""
        return f"{self.channel}?.({self.continuation})"


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
        if not is_hcsp_identifier(self.channel):
            raise ValueError("Output type channel must be a valid identifier")
        if not isinstance(self.continuation, ProcessType):
            raise TypeError("Output type continuation must be a process type T")

    def __str__(self) -> str:
        """打印输出前缀，并用括号明确标出它所支配的完整后继类型。"""
        return f"{self.channel}!.({self.continuation})"


# 论文对应：A 递归产生式中可以追加的 ch?.T 或 ch!.T 分支。
# 功能：为 ExternalChoiceType 与 make_external_choice 声明精确分支类别。
# 构造检查：别名本身不执行检查，两个使用方都会执行显式 isinstance 验证。
CommunicationType = InputType | OutputType


# --------------------------------------------------------------------------
# 论文对应：至少两个通信分支组成的 A1 \sqcap ... \sqcap An。
# 构造方式：ExternalChoiceType((InputType(...), OutputType(...), ...))。
# 构造检查：至少两个分支且每个分支必须是 InputType/OutputType；空和单分支分别
#           由 NoInterruptType、InputType/OutputType 唯一表示。
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
                "use NoInterruptType/InputType/OutputType for zero or one branch"
            )
        if not all(isinstance(item, (InputType, OutputType)) for item in items):
            raise TypeError(
                "External choice branches must be InputType or OutputType"
            )
        object.__setattr__(self, "branches", items)

    def __str__(self) -> str:
        r"""使用 ``\sqcap`` 连接全部通信分支，并分别括住每个分支。"""
        return r" \sqcap ".join(f"({branch})" for branch in self.branches)


# 论文对应：A ::= 0 | A \sqcap ch?.T | A \sqcap ch!.T 的规范化构造入口。
# 功能：根据通信分支数返回唯一的 NoInterrupt/Input/Output/ExternalChoice 节点。
# 构造检查：拒绝非通信分支，避免同一个 A 拥有多种 AST 形状。
def make_external_choice(branches: Iterable[CommunicationType]) -> AngelicType:
    """把零个、一个或多个通信分支规范成唯一的 angelic type 节点。"""

    items = tuple(branches)
    if not all(isinstance(item, (InputType, OutputType)) for item in items):
        raise TypeError("Angelic choice branches must be InputType or OutputType")
    if not items:
        return NoInterruptType()
    if len(items) == 1:
        return items[0]
    return ExternalChoiceType(items)


# --------------------------------------------------------------------------
# 论文对应：过程类型 T \sqcup T'；Table 2 [T-If]/[T-\sqcup] 产生它。
# 构造方式：InternalChoiceType((left, right, ...))；嵌套节点保留用户括号确定的分块。
# 构造检查：当前节点至少两个分支，每个分支必须是 ProcessType，不能放入 ParallelType。
# --------------------------------------------------------------------------
@dataclass(frozen=True)
class InternalChoiceType(ProcessType):
    """由程序内部非确定性决定的 demonic/internal choice。"""

    branches: tuple[ProcessType, ...]

    def __init__(self, branches: Iterable[ProcessType]):
        """保留内部选择分块，并验证分支数量与 T 语法类别。"""
        items = tuple(branches)
        if not all(isinstance(branch, ProcessType) for branch in items):
            raise TypeError("Internal choice branches must be process types T")
        if len(items) < 2:
            raise ValueError("InternalChoiceType requires at least two branches")
        object.__setattr__(self, "branches", items)

    def __str__(self) -> str:
        r"""使用论文 ``\sqcup`` 记号连接并括住每个内部选择分支。"""
        return r" \sqcup ".join(f"({branch})" for branch in self.branches)


# 论文对应：所有有限 delay 构造均要求 0 <= d < infinity，且 d 是常量。
# 功能：把常用 Python 有理输入规范化为精确 Fraction。
# 构造检查：拒绝 Bool、负数、NaN、无穷和非数值对象；无穷由 make_delay_type 处理。
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


# 论文对应：有限统一产生式 delay(d) \unrhd A \triangleright T。
# 构造方式：FiniteDelayType(duration, interrupts, continuation)。
# 构造检查：d 为有限非负有理数；A 必须是 angelic type，T 必须是 process type。
#           BottomType 表示该有限 deadline 的自然后继不可达，对应 T-\unrhd；
#           EmptyType 表示到时后存在后继位置、但该后继没有可观察通信行为，对应
#           T-\unrhd' 的空行为特例。二者必须保持为不同的正式 AST 节点。
# --------------------------------------------------------------------------
@dataclass(frozen=True)
class FiniteDelayType(ProcessType):
    r"""有限时延的统一行为类型 ``delay(d) \unrhd A \triangleright T``。"""

    duration: Fraction
    interrupts: AngelicType
    continuation: ProcessType

    def __init__(
        self,
        duration: Any,
        interrupts: AngelicType,
        continuation: ProcessType,
    ):
        """验证统一有限时延的时长、中断集合和自然到时后继。"""
        if not isinstance(interrupts, AngelicType):
            raise TypeError("Finite delay interrupts must be an angelic type A")
        if not isinstance(continuation, ProcessType):
            raise TypeError("Finite delay continuation must be a process type T")
        object.__setattr__(self, "duration", _normalize_finite_duration(duration))
        object.__setattr__(self, "interrupts", interrupts)
        object.__setattr__(self, "continuation", continuation)

    def __str__(self) -> str:
        """按 A/T 的取值使用论文的三个有限时延缩写。"""
        if isinstance(self.continuation, BottomType):
            return f"delay({self.duration}) \\unrhd ({self.interrupts})"
        if isinstance(self.interrupts, NoInterruptType):
            return f"delay({self.duration}).({self.continuation})"
        return (
            f"delay({self.duration}) \\unrhd ({self.interrupts}) "
            f"\\triangleright ({self.continuation})"
        )


# 论文对应：无穷时延 delay(infinity) \unrhd A \triangleright \bot。
# 功能：显式保留无穷时延，避免把它和单独的 A（通信选择）混为一类 AST。
# 构造检查：只保存 A；不可达的 \bot 后继是该节点的固定语义，不能由调用者改写。
# --------------------------------------------------------------------------
@dataclass(frozen=True)
class InfiniteDelayType(ProcessType):
    """无穷时延及其通信中断集合；其自然到时后继固定为不可达的 bottom。"""

    interrupts: AngelicType

    def __post_init__(self) -> None:
        """无穷时延只能携带论文范畴 A 中的通信中断集合。"""
        if not isinstance(self.interrupts, AngelicType):
            raise TypeError("Infinite delay interrupts must be an angelic type A")

    def __str__(self) -> str:
        """显示无穷时延；空中断集合只显示 delay(infinity)。"""
        if isinstance(self.interrupts, NoInterruptType):
            return "delay(infinity)"
        return f"delay(infinity) \\unrhd ({self.interrupts})"


# 论文对应：统一产生式 delay(delta) \unrhd A \triangleright T。
# 功能：按时延是否无穷构造两种正式 delay AST 节点；本函数不是 AST 节点。
# 构造检查：有限情形原样保留 BottomType 或普通 T；无穷情形的 BottomType 后继由
#           InfiniteDelayType 固定表达，调用方传入的普通 continuation 不进入结果。
def make_delay_type(
    duration: Any,
    interrupts: AngelicType,
    continuation: ProcessType,
) -> ProcessType:
    """把 Table 2 的 d、A、T 构造成有限或无穷时延节点。"""

    if not isinstance(interrupts, AngelicType):
        raise TypeError("Delay interrupts must be an angelic type A")
    if not isinstance(continuation, ProcessType):
        raise TypeError("Delay continuation must be a process type T")

    if isinstance(duration, float) and isinf(duration):
        if duration > 0:
            # 论文的无限等待没有超时迁移；转换时把任何候选 fallback 规范为
            # bottom，再使用 A := delay(infinity) \unrhd A \triangleright bottom。
            return InfiniteDelayType(interrupts)
        raise ValueError("Type duration cannot be negative infinity")
    if isinstance(duration, Decimal) and duration.is_infinite():
        if duration > 0:
            # Decimal 正无穷与 float 正无穷遵循同一不可超时语义。
            return InfiniteDelayType(interrupts)
        raise ValueError("Type duration cannot be negative infinity")

    finite = _normalize_finite_duration(duration)
    return FiniteDelayType(finite, interrupts, continuation)


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
        if not is_hcsp_identifier(self.variable):
            raise ValueError(
                "Recursive type variable must be a valid HCSP identifier"
            )
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
# 构造检查：压平后至少两个 configuration 分量；状态所有权仍由 [T-||] 检查。
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
    """迭代查找未被同名内层 ``mu`` 遮蔽的类型变量。"""

    pending: list[BehavioralType] = [value]
    while pending:
        current = pending.pop()
        if isinstance(current, TypeVar):
            if current.name == name:
                return True
        elif isinstance(current, (InputType, OutputType)):
            pending.append(current.continuation)
        elif isinstance(current, (ExternalChoiceType, InternalChoiceType)):
            pending.extend(reversed(current.branches))
        elif isinstance(current, FiniteDelayType):
            pending.extend((current.continuation, current.interrupts))
        elif isinstance(current, InfiniteDelayType):
            pending.append(current.interrupts)
        elif isinstance(current, MuType) and current.variable != name:
            pending.append(current.body)
        elif isinstance(current, ParallelType):
            pending.extend(reversed(current.components))
    return False


# 功能：检查目标类型变量的每条出现路径是否经过输入或输出通信前缀。
# 检查/论文关系：Delay、内部选择和并行本身不构成论文要求的通信守卫。
def _type_var_guarded(
    value: BehavioralType,
    name: str,
    under_communication: bool = False,
) -> bool:
    """迭代验证指定类型变量的全部自由出现均受通信保护。"""

    pending: list[tuple[BehavioralType, bool]] = [(value, under_communication)]
    while pending:
        current, guarded = pending.pop()
        if isinstance(current, TypeVar):
            if current.name == name and not guarded:
                return False
        elif isinstance(current, (InputType, OutputType)):
            pending.append((current.continuation, True))
        elif isinstance(current, (ExternalChoiceType, InternalChoiceType)):
            pending.extend((branch, guarded) for branch in current.branches)
        elif isinstance(current, FiniteDelayType):
            pending.extend(
                ((current.interrupts, guarded), (current.continuation, guarded))
            )
        elif isinstance(current, InfiniteDelayType):
            pending.append((current.interrupts, guarded))
        elif isinstance(current, MuType) and current.variable != name:
            pending.append((current.body, guarded))
        elif isinstance(current, ParallelType):
            pending.extend((component, guarded) for component in current.components)
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
    """用显式工作栈生成忽略递归绑定变量改名的规范结构键。"""

    initial_bound = {} if bound is None else dict(bound)
    results: list[Any] = []
    # ``finish`` 任务保存本节点开始前的结果栈长度，从而按原顺序收集子键。
    pending: list[tuple[Any, ...]] = [("visit", value, initial_bound)]
    while pending:
        task = pending.pop()
        if task[0] == "finish":
            _, tag, payload, start = task
            children = tuple(results[start:])
            del results[start:]
            if tag in {"in", "out"}:
                results.append((tag, payload, children[0]))
            elif tag in {"external", "internal", "parallel"}:
                results.append((tag, children))
            elif tag == "finite-delay":
                results.append((tag, payload, children[0], children[1]))
            elif tag in {"infinite-delay", "mu"}:
                results.append((tag, children[0]))
            else:
                raise RuntimeError(f"Unsupported Type key task: {tag}")
            continue

        _, current, current_bound = task
        if isinstance(current, NoInterruptType):
            results.append(("no-interrupt",))
        elif isinstance(current, EmptyType):
            results.append(("empty",))
        elif isinstance(current, BottomType):
            results.append(("bottom",))
        elif isinstance(current, TypeVar):
            if current.name in current_bound:
                results.append(("bound", current_bound[current.name]))
            else:
                results.append(("free", current.name))
        elif isinstance(current, (InputType, OutputType)):
            tag = "in" if isinstance(current, InputType) else "out"
            start = len(results)
            pending.append(("finish", tag, current.channel, start))
            pending.append(("visit", current.continuation, current_bound))
        elif isinstance(current, (ExternalChoiceType, InternalChoiceType)):
            tag = (
                "external"
                if isinstance(current, ExternalChoiceType)
                else "internal"
            )
            start = len(results)
            pending.append(("finish", tag, None, start))
            for branch in reversed(current.branches):
                pending.append(("visit", branch, current_bound))
        elif isinstance(current, FiniteDelayType):
            start = len(results)
            pending.append(
                ("finish", "finite-delay", _duration_key(current.duration), start)
            )
            pending.append(("visit", current.continuation, current_bound))
            pending.append(("visit", current.interrupts, current_bound))
        elif isinstance(current, InfiniteDelayType):
            start = len(results)
            pending.append(("finish", "infinite-delay", None, start))
            pending.append(("visit", current.interrupts, current_bound))
        elif isinstance(current, MuType):
            nested_bound = dict(current_bound)
            nested_bound[current.variable] = len(current_bound)
            start = len(results)
            pending.append(("finish", "mu", None, start))
            pending.append(("visit", current.body, nested_bound))
        elif isinstance(current, ParallelType):
            start = len(results)
            pending.append(("finish", "parallel", None, start))
            for component in reversed(current.components):
                pending.append(("visit", component, current_bound))
        else:
            raise TypeError(
                f"Unsupported behavioral type: {type(current).__name__}"
            )
    if len(results) != 1:
        raise RuntimeError("Type key construction produced an invalid result")
    return results[0]


# 论文对应：比较 Section 4.1/4.2 规范类型是否仅有 mu 绑定变量改名差异。
# 功能：比较类型 AST 的 alpha 等价结构键。
# 检查/论文关系：不实现子类型、双模拟或选择/并行的交换律等价。
def types_equivalent(left: BehavioralType, right: BehavioralType) -> bool:
    """按规范结构比较类型，并忽略 ``mu`` 绑定变量的命名差异。"""
    return _type_key(left) == _type_key(right)
