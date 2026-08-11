"""Gamma、Theta、全局参数与运行 Configuration 的领域数据结构。

本模块只描述运行上下文，不执行类型构造或类型检查。前端、TypeConstructor 与
TypeChecker 都依赖这里的同一组类，因而不会通过某个业务后端反向取得环境定义。
"""

from __future__ import annotations

from dataclasses import dataclass
from enum import Enum
from types import MappingProxyType
from typing import Any, Mapping, Sequence

from ...identifiers import is_hcsp_identifier

# --------------------------------------------------------------------------
# 论文对应：Definition 4.1 的基础类型 B ::= Bool | N | Z | Q | R | ...；
#           BOOL/NAT/INT/RATIONAL/REAL 分别实现其中的 Bool/N/Z/Q/R。
# 角色对应：Gamma 中标量变量和 Theta 中通道载荷可使用的基础值类型。
# 构造方式：BasicType.BOOL/NAT/INT/RATIONAL/REAL。
# 类型规则：数值类型按 Nat <: Int <: Rational <: Real 排列；
#           枚举本身不检查某个表达式是否具有该类型。
# --------------------------------------------------------------------------
class BasicType(str, Enum):
    """HCSP 表达式使用的基础值类型。

    本项目只保留论文中明确使用的布尔类型和四种数值类型。数值类型形成
    ``Nat <: Int <: Rational <: Real`` 的子类型链。
    """
    BOOL = "Bool"
    NAT = "Nat"
    INT = "Int"
    RATIONAL = "Rational"
    REAL = "Real"

    # 功能：返回环境、行为报告和诊断使用的规范类型名。
    # 构造/模型关系：不执行子类型比较；该工作由 is_subtype 完成。
    def __str__(self) -> str:
        """按论文中使用的类型名打印。"""
        return self.value


# 论文对应：把用户输入归一为 Definition 4.1 的基础类型 B；
#           不是 Table 2 中从表达式推导 B 的判断规则。
# 功能：把内部建模接口接受的基础类型简写转换为唯一的 BasicType 表示。
# 构造/模型关系：支持 BasicType、Python 类型对象和明确字符串别名；
#                tuple/list 及其他无法识别的对象立即抛出 TypeError。
def normalize_type(value: Any, *, subject: str = "Value type") -> BasicType:
    """把便捷写法归一化为两个类型后端共用的唯一基础值类型。

    调用方可以传入枚举、Python 类型对象或字符串别名。论文未要求积类型，
    因此 tuple/list 不能表示一个普通值的类型。表达式结果、Theta 通信签名中
    的每个独立槽位以及 Gamma 中包括 ODE 分量在内的值变量都使用
    ``BasicType``；独立的 ODE 演化向量声明使用 ``ContinuousType``。完整的
    多槽 Theta 项由
    ``ChannelType`` 逐槽调用本函数构造。
    """
    if isinstance(value, BasicType):
        return value
    if value is bool:
        return BasicType.BOOL
    if value is int:
        return BasicType.INT
    if value is float:
        return BasicType.REAL
    if isinstance(value, str):
        aliases = {
            "b": BasicType.BOOL,
            "bool": BasicType.BOOL,
            "boolean": BasicType.BOOL,
            "n": BasicType.NAT,
            "nat": BasicType.NAT,
            "natural": BasicType.NAT,
            "z": BasicType.INT,
            "int": BasicType.INT,
            "integer": BasicType.INT,
            "q": BasicType.RATIONAL,
            "rat": BasicType.RATIONAL,
            "rational": BasicType.RATIONAL,
            "r": BasicType.REAL,
            "real": BasicType.REAL,
        }
        key = value.strip().lower()
        if key in aliases:
            return aliases[key]
    raise TypeError(f"{subject} must be a BasicType, got {value!r}")


# --------------------------------------------------------------------------
# 论文对应：退化后的连续演化向量项
#           ``underlined(v) : R_{>=0} partial-function R^n``。
# 角色对应：作为 Gamma 中独立命名的声明，登记 process 允许出现的完整
#           ODE 演化变量集合；其成员本身仍分别声明为 BasicType.REAL。
# 构造方式：ContinuousType(variables=("p", "v", "a"))。
# 构造检查：向量必须非空、成员互异且都是合法变量名；成员顺序不构成语义，
#           构造器会按名称规范化，以便 T-ODE 按集合匹配。
# --------------------------------------------------------------------------
@dataclass(frozen=True)
class ContinuousType:
    """Gamma 中一个独立命名的、允许出现的 ODE 演化向量声明。

    连续项退化为 ``v : R_{>=0} partial-function R^n``，不再携带状态性质。
    连续演化中需要恒成立的 ``phi`` 只由对应 ODE 的 ``annotation.safety``
    定义，从而避免 Gamma 与 ODE 重复声明同一性质。它不是 ``p``、``v``、``a``
    等标量变量的值类型：这些成员必须各自以 ``BasicType.REAL`` 出现在 Gamma，
    而另一个声明名（例如 ``vehicle_ode``）映射到本对象。

    ``variables`` 按集合解释并规范化排序，因此 ODE 左端方程的书写顺序不影响
    匹配。ODE 的隐式局部时钟不属于用户向量，也不需要在 Gamma 中登记；没有
    用户方程为空的 ODE 同样不需要连续向量声明。
    """

    variables: tuple[str, ...]

    def __init__(
        self,
        variables: Sequence[str],
    ):
        """建立按成员集合解释的 ``R^n`` ODE 演化向量声明。"""

        if isinstance(variables, (str, bytes)):
            raise TypeError(
                "Continuous vector variables must be a sequence of names, "
                "not one string"
            )
        normalized_variables = tuple(variables)
        if not normalized_variables:
            raise ValueError("Continuous vector variables must not be empty")
        if any(
            not is_hcsp_identifier(name)
            for name in normalized_variables
        ):
            raise ValueError("Continuous vector variables must be valid identifiers")
        if len(set(normalized_variables)) != len(normalized_variables):
            raise ValueError("Continuous vector variables must be distinct")
        object.__setattr__(self, "variables", tuple(sorted(normalized_variables)))

    def __str__(self) -> str:
        """按 ``R>=0 ~> R^n`` 形式显示演化向量声明。"""

        dimension = len(self.variables)
        rendered = "R>=0 ~> Real" if dimension == 1 else f"R>=0 ~> R^{dimension}"
        return rendered + " on (" + ", ".join(self.variables) + ")"


# Gamma 项只允许标量基础类型或独立的 ODE 演化向量声明。进程变量类型保存在
# 业务后端的递归环境中，不与 Python 字符串键上的值变量混用。
GammaType = BasicType | ContinuousType


def normalize_gamma_type(value: Any, *, subject: str = "Gamma entry") -> GammaType:
    """规范化 Gamma 的标量值类型或独立 ODE 向量声明。"""

    if isinstance(value, ContinuousType):
        return value
    try:
        return normalize_type(value, subject=subject)
    except TypeError as exc:
        raise TypeError(
            f"{subject} must be a BasicType or ContinuousType, got {value!r}"
        ) from exc


def gamma_value_type(value: Any, *, subject: str = "Gamma entry") -> BasicType:
    """返回 Gamma 标量变量的基础类型，并拒绝把 ODE 向量当作值。"""

    normalized = normalize_gamma_type(value, subject=subject)
    if isinstance(normalized, ContinuousType):
        raise TypeError(
            f"{subject} is an ODE vector declaration, not a scalar value type"
        )
    return normalized


# 论文对应：服务于 Table 2 的 [T-Assign]、[T-In]、[T-Out] 表达式类型前提；
#           数值提升是项目实现策略，论文表中只写两侧具有基础类型 B。
# 功能：判断实际值类型能否安全流入期望值类型位置。
# 构造/模型关系：实现 Nat <: Int <: Rational <: Real；这里只比较基础值类型，
#                不实现行为类型子类型关系。
def is_subtype(actual: BasicType, expected: BasicType) -> bool:
    """判断表达式实际类型能否安全用于期望类型的位置。

    基础数值类型使用下方的精度等级。此处只处理基础值类型，不处理行为类型
    的等价或子类型。
    """
    actual = normalize_type(actual)
    expected = normalize_type(expected)
    if actual == expected:
        return True
    # 等级越高，可表示的数值范围/精度越宽。赋值方向只能从低等级到高等级。
    numeric_rank = {
        BasicType.NAT: 0,
        BasicType.INT: 1,
        BasicType.RATIONAL: 2,
        BasicType.REAL: 3,
    }
    return (
        actual in numeric_rank
        and expected in numeric_rank
        and numeric_rank[actual] <= numeric_rank[expected]
    )


# --------------------------------------------------------------------------
# 论文扩展：Theta(ch) = {(eta1:B1,...,etan:Bn) | phi}；每个 Bi 仍是 BasicType，
#           refinement 对应联合谓词 phi，binders 对应各槽位的新鲜占位变量。
#           T-In/T-Out 分别同时替换全部 xi/etai 与 ei/etai。
# 角色对应：Theta(ch) 的多标量通信签名及其联合 refinement 谓词。
# 构造方式：ChannelType((B1,...,Bn), refinement=True, binders=("eta1",...,"etan"))；
#           单个 B 会规范化为一槽签名。
# 构造检查：至少一个槽位且每项都是 BasicType；binder 数量必须匹配、名称合法
#           且互异。完整环境入口先检查 refinement 是作用域闭合的 Bool 公式，
#           T-In/T-Out 再用实际通信值完成替换和证明。
# --------------------------------------------------------------------------
@dataclass(frozen=True)
class ChannelType:
    """一次通信中多个独立标量槽位的类型及联合精化谓词。

    ``binders`` 分别代表各槽本次传递的值。例如
    ``ChannelType((Int, Real), "eta1 >= 0 and eta2 >= eta1")`` 表示一次通信
    传递一个整数和一个实数，并对二者施加联合约束。这里的元组是通信签名，
    不是可赋给状态变量的 tuple 值类型。
    """

    value_types: tuple[BasicType, ...]
    refinement: Any = True
    binders: tuple[str, ...] = ()

    # 功能：把一槽或多槽声明规范化为不可变、定元数的通道签名。
    # 构造/模型关系：不创建 TupleType；每个分量独立规范化为 BasicType。
    def __init__(
        self,
        value_types: Any,
        refinement: Any = True,
        binders: Sequence[str] | str | None = None,
    ):
        """规范化槽位类型、联合精化和一一对应的占位变量。"""

        raw_types = (
            tuple(value_types)
            if isinstance(value_types, (tuple, list))
            else (value_types,)
        )
        if not raw_types:
            raise ValueError("Channel type needs at least one payload slot")
        normalized_types = tuple(
            normalize_type(value, subject="Channel payload slot type")
            for value in raw_types
        )

        if binders is None:
            normalized_binders = (
                ("eta",)
                if len(normalized_types) == 1
                else tuple(
                    f"eta{index}"
                    for index in range(1, len(normalized_types) + 1)
                )
            )
        elif isinstance(binders, str):
            normalized_binders = (binders,)
        else:
            normalized_binders = tuple(binders)
        if len(normalized_binders) != len(normalized_types):
            raise ValueError(
                "Channel refinement binder count must match payload arity"
            )
        if any(
            not is_hcsp_identifier(name)
            for name in normalized_binders
        ):
            raise ValueError("Channel refinement binders must be identifiers")
        if len(set(normalized_binders)) != len(normalized_binders):
            raise ValueError("Channel refinement binders must be distinct")

        object.__setattr__(self, "value_types", normalized_types)
        object.__setattr__(self, "refinement", refinement)
        object.__setattr__(self, "binders", normalized_binders)

    @property
    def arity(self) -> int:
        """返回一次同步通信中独立标量槽位的数量。"""

        return len(self.value_types)

    # 功能：按 refinement type 记法展示 Theta 中的一项，供详细报告使用。
    # 构造/模型关系：只改变面向用户的字符串，不改变 dataclass 的结构表示、
    #                相等性或 T-In/T-Out 的替换逻辑。
    def __str__(self) -> str:
        """返回 ``{(eta1:B1,...) | phi}`` 形式的可读通道类型。"""

        slots = ", ".join(
            f"{binder}:{value_type}"
            for binder, value_type in zip(self.binders, self.value_types)
        )
        refinement = "true" if self.refinement is True else str(self.refinement)
        return f"{{{slots} | {refinement}}}"


# 论文扩展：把 Theta 输入统一为多标量通道 refinement type 记录。
# 功能：把 Theta 项的便捷写法规范化为 ChannelType。
# 构造/模型关系：ChannelType 原样返回；单个 B 形成一槽签名，tuple/list 的
#                全部元素形成多槽类型序列。非平凡 refinement 应显式构造 ChannelType，
#                避免把类型序列误解成额外的 refinement 位置参数。
def normalize_channel_type(value: Any) -> ChannelType:
    """把简写的 ``Theta`` 项归一化为 :class:`ChannelType`。

    单个 ``B`` 表示一槽通道，``(B1,...,Bn)`` 表示多槽通道。通道签名元组不是
    ``TupleType``，也不能作为 Gamma 中某个变量的类型。
    """
    if isinstance(value, ChannelType):
        return value
    return ChannelType(value)


# --------------------------------------------------------------------------
# 项目扩展：共享只读参数环境 Delta ::= x:B,... | H。
# 功能：声明在 HCSP 执行前由用户选定、在所有并行配置间共享且执行中不可修改
#       的参数，并给出所有合法预赋值必须满足的约束 H。
# 构造/模型关系：本类只冻结构造输入；名称、基础类型、约束的 Bool 类型、约束
#                可满足性以及与 Gamma 的不相交性由业务后端统一检查。
# --------------------------------------------------------------------------
@dataclass(frozen=True)
class ParameterEnvironment:
    """所有配置共享的预赋值、只读参数声明及其合法性约束。

    ``declarations`` 的每个值最终必须规范化为 ``BasicType``。``constraint``
    只能引用这些参数，表示用户选择参数值时必须满足的性质。类型构造过程证明的是
    对每一个满足该约束的参数赋值，Table 2 推导均成立；参数不属于状态 Gamma，
    因而不参与并行状态空间分区。
    """

    declarations: Mapping[str, Any]
    constraint: Any = True

    def __init__(
        self,
        declarations: Mapping[str, Any] | None = None,
        constraint: Any = True,
    ):
        """复制声明映射，并暴露为只读参数环境。"""

        object.__setattr__(
            self,
            "declarations",
            MappingProxyType(
                {} if declarations is None else dict(declarations)
            ),
        )
        object.__setattr__(self, "constraint", constraint)


# --------------------------------------------------------------------------
# 论文对应：Section 4.2 组合配置判断中的单个 ``(sigma, P)``；Table 2
#           [T-sigma] 由 ``Gamma·Theta·phi |- P :: T`` 和 ``|= phi[sigma]``
#           得到 ``Gamma·Theta·phi |- (sigma, P) :: T``。
# 判断对应：并行规则输入中的单个 <sigma, P> configuration。
# 构造方式：Configuration(state, process, path_condition=None, name=None)。
# 构造检查：复制 state 以隔离调用方修改，但暂不验证 process 属于 HCSP；
#           路径条件和结构合法性由当前业务后端统一诊断。
# --------------------------------------------------------------------------
@dataclass(frozen=True)
class Configuration:
    """并行判断中的单个 ``<state, process>`` 配置。

    Gamma 是整个类型判断统一提供的声明环境，不存放在单个 Configuration 中。
    ``path_condition`` 可以为不同并行叶子声明独立局部路径；若使用局部路径，
    则所有并行叶子都必须提供，外层默认 ``true`` 仅表示最终路径由这些局部
    路径的合取产生。

    ``state`` 是 Gamma 中 ``BasicType`` 值变量上的部分赋值：允许
    ``dom(state)`` 是值变量定义域的真子集，未赋值变量留给
    ``|= phi[state]`` 的有效性检查；独立 ``ContinuousType`` 声明没有状态值，
    不能作为 state 键。

    严格的论文配置叶子只接受 ``Process``。项目为无状态协议保留
    ``Configuration({}, Parallel(...))`` 便捷写法；只要 Gamma、state 或路径
    非平凡，就必须改写为多个显式 Configuration，使每个叶子独立应用 T-sigma。
    """

    state: Mapping[str, Any]
    process: Any
    path_condition: Any | None = None
    name: str | None = None

    # 功能：保存一个配置及其可选局部路径，并复制可变初始状态。
    # 构造/模型关系：state=None 规范化为空状态；path/process 保持输入，
    #                后续 T-|| 展开及 configuration/system/process judgment 求解器验证。
    def __init__(
        self,
        state: Mapping[str, Any] | None,
        process: Any,
        path_condition: Any | None = None,
        name: str | None = None,
    ):
        """复制可变映射，避免调用方后续修改影响正在进行的类型构造。"""
        object.__setattr__(self, "state", {} if state is None else dict(state))
        object.__setattr__(self, "process", process)
        object.__setattr__(self, "path_condition", path_condition)
        object.__setattr__(self, "name", name)

__all__ = [
    "BasicType",
    "ChannelType",
    "Configuration",
    "ContinuousType",
    "GammaType",
    "ParameterEnvironment",
    "gamma_value_type",
    "is_subtype",
    "normalize_channel_type",
    "normalize_gamma_type",
    "normalize_type",
]
