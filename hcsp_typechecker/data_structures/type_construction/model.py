"""TypeConstructor 的内部输入、证明证据与报告数据模型。

本模块只定义数据，不执行具体的类型推导。审计代码时可以把这里看成系统的
“词汇表”：

* :class:`BasicType`、:class:`ContinuousType`、:class:`ChannelType` 描述变量
  环境 ``Gamma`` 与通道环境 ``Theta`` 中允许出现的声明；其中 ``BasicType``
  项给标量值变量定型，连续项则独立登记 process 中允许出现的 ODE 演化向量；
* :class:`TypeConstructionRequest` 是类型构造器的输入；
* :class:`DerivationStep`、:class:`ProofObligation`、:class:`Diagnostic` 和
  :class:`TypeConstructionReport` 是类型构造器输出的可审计证据。

本模块中的 ``ProofObligation`` 只保存已经完整生成的 state、FOL 或 dL 公式。
它不保存待求解的谓词变量，也不表示需要从多条约束中综合 T-Assign 的未知
``phi'``。赋值后状态由 ``backend/common/rule_engine.py`` 在规则展开时通过惰性最强后置状态确定；
这里的数据对象只负责记录后续需要证明的具体目标和证明器返回的三值结果。

HCSP 进程语法由 ``data_structures/process_ast/ast.py`` 独立定义，行为类型语法由
``data_structures/type_ast/ast.py`` 独立定义。本模块只在构造请求和构造报告中引用这些
结构，不定义任何 Process AST 或 Type AST 节点。

────────────────── 模型分层与数据流 ────────────────────────────────────────

本文件中的定义按类型构造过程分为三层：

* ``BasicType`` 表示标量值变量类型和每个表达式的结果类型，
  ``ContinuousType`` 是 ``Gamma`` 中独立的 ODE 向量声明，``ChannelType`` 表示
  承载一个或多个独立 ``BasicType`` 槽位的 ``Theta`` 项；
* ``Configuration``、``TypeConstructionRequest`` 表示一次类型构造请求；
* ``DerivationStep``、``ProofObligation``、``Diagnostic``、
  ``TypeConstructionReport``
  表示规则执行轨迹、逻辑证据和最终结果。

除明确写出规范化逻辑的构造器外，这些类都是不可变数据容器。Table 2 规则
确定性地产生具体 ``ProofObligation``，统一求解器在该 premise 的推导位置立即
调用 FOL/dL 后端。不能因为公式已经确定或已经进入数据类，就认为对应性质
已经被证明。

────────────────── 与论文 Section 4.2/4.3 的对应 ───────────────────────────

Section 4.1 的行为类型 ``T``、angelic type ``A`` 和 Section 4.2 的组合类型
``mathcal T`` 由 ``data_structures/type_ast/ast.py`` 定义；本模块只保存推导请求及其证据。

Definition 4.1 的 ``Gamma`` 同时描述值变量、递归变量和连续演化项。本项目将其
拆分：``TypeConstructionRequest.gamma`` 用 ``BasicType`` 表示包括 ODE 分量在内的
所有标量值变量，并用单独命名的 ``ContinuousType`` 项保存允许出现的 ODE
向量成员；
递归类型及边界不变量由
``constructor._Context.rec_env`` 和 ``Mu`` 批注保存。连续演化项的向量场仍来自对应
``ODE`` 节点，T-ODE 要求节点左侧的完整变量集合已由 Gamma 登记；连续演化中
必须恒成立的 ``phi`` 只来自 ODE 节点的 safety 批注。``Theta``
则由 ``ChannelType`` 表示项目扩展后的 refinement type
``{(eta1:B1,...,etan:Bn) | phi}``；一槽情形退化为论文的
``{eta : B | phi}``。Table 2 的公式前提被记录为 ``ProofObligation``。

────────────────────────────────────────────────────────────────────────────
"""

from __future__ import annotations

from dataclasses import dataclass, replace
from enum import Enum
from types import MappingProxyType
from typing import Any, Callable, Iterable, Mapping, Sequence

from ...identifiers import is_hcsp_identifier
from ..process_ast.expressions import Expr, ExprLike, Literal, ensure_expr
from ..type_ast.ast import ConfigurationType as _ConfigurationType
from ..type_ast.render import format_type_source


# --------------------------------------------------------------------------
# 论文对应：论文的 typing judgment 本身是可推导/不可推导的二值关系，
#           未定义 UNKNOWN；本枚举是实现为求解超时或外部证明未完成增加的
#           保守审计结果，不属于 Section 4.1 的行为类型语法。
# 角色对应：所有静态检查与证明义务共用的三值结论域。
# 构造方式：Verdict.TRUE、Verdict.FALSE、Verdict.UNKNOWN；通常由证明后端返回。
# 结果规则：FALSE 表示已发现反例/静态错误，UNKNOWN 表示尚未得到可靠结论；
#           combine 以 FALSE > UNKNOWN > TRUE 的保守优先级汇总结果。
# --------------------------------------------------------------------------
class Verdict(str, Enum):
    """类型构造诊断与证明结果共用的三值逻辑。

    ``UNKNOWN`` 不等同于类型错误：它表示结构推导已经执行，但某个公式
    未能由当前证明后端判定。只有 ``FALSE`` 才表示已经发现反例或静态错误。
    """

    TRUE = "true"
    FALSE = "false"
    UNKNOWN = "unknown"

    # 功能：把枚举值转成报告中使用的小写文本。
    # 构造/模型关系：不改变真假含义，仅提供稳定显示格式。
    def __str__(self) -> str:
        """返回适合报告与命令行展示的小写结果。"""
        return self.value

    # 功能：兼容自定义证明后端返回的 Verdict、bool 或常见状态文本。
    # 构造/模型关系：只有明确的真/假词汇被采信，其他值一律保守为 UNKNOWN。
    @classmethod
    def from_value(cls, value: Any) -> "Verdict":
        """把证明后端常见的布尔值或文本结果统一为三值结果。"""
        if isinstance(value, Verdict):
            return value
        if value is True or str(value).lower() in {"true", "yes", "valid", "proved"}:
            return cls.TRUE
        if value is False or str(value).lower() in {"false", "no", "invalid", "disproved"}:
            return cls.FALSE
        return cls.UNKNOWN

    # 功能：把多条证明义务和诊断的结论合并为一个总体结论。
    # 构造/模型关系：任一 FALSE 使整体为 FALSE；否则任一 UNKNOWN 使整体未知；
    #                空集合按全称条件的真空真返回 TRUE。
    @classmethod
    def combine(cls, values: Iterable["Verdict"]) -> "Verdict":
        """合并子结论：``FALSE`` 优先，其次 ``UNKNOWN``，最后 ``TRUE``。"""
        values = tuple(values)
        if any(value == cls.FALSE for value in values):
            return cls.FALSE
        if any(value == cls.UNKNOWN for value in values):
            return cls.UNKNOWN
        return cls.TRUE


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
    """把便捷写法归一化为类型构造器内部唯一的基础值类型。

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
# constructor 的递归环境中，不与 Python 字符串键上的值变量混用。
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
#           且互异。refinement 的语法和替换由 ExpressionTranslator/T-In/T-Out 检查。
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
#                可满足性以及与 Gamma 的不相交性由 TypeConstructor 统一检查。
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
# 构造方式：Configuration(state, process, gamma=None, path_condition=None, name=None)。
# 构造检查：复制 state 以隔离调用方修改，但暂不验证 process 属于 HCSP；
#           局部 Gamma、路径条件和结构合法性由 TypeConstructor 统一诊断。
# --------------------------------------------------------------------------
@dataclass(frozen=True)
class Configuration:
    """并行判断中的单个 ``<state, process>`` 配置。

    ``gamma`` 和 ``path_condition`` 可以为不同并行叶子声明独立局部环境，
    但不是不受约束的“覆盖”：TypeConstructor 要求局部 Gamma 两两不交、与全局
    Gamma 同型且并集恰为全局 Gamma。若使用局部路径，则所有并行叶子都必须
    提供，外层默认 ``true`` 仅表示最终路径由这些局部路径的合取产生。

    ``state`` 是 Gamma 中 ``BasicType`` 值变量上的部分赋值：允许
    ``dom(state)`` 是局部值变量定义域的真子集，未赋值变量留给
    ``|= phi[state]`` 的有效性检查；独立 ``ContinuousType`` 声明没有状态值，
    不能作为 state 键。

    严格的论文配置叶子只接受 ``Process``。项目为无状态协议保留
    ``Configuration({}, Parallel(...))`` 便捷写法；只要 Gamma、state 或路径
    非平凡，就必须改写为多个显式 Configuration，使每个叶子独立应用 T-sigma。
    """

    state: Mapping[str, Any]
    process: Any
    gamma: Mapping[str, GammaType] | None = None
    path_condition: Any | None = None
    name: str | None = None

    # 功能：保存一个配置及其可选局部环境声明，并复制可变初始状态。
    # 构造/模型关系：state=None 规范化为空状态；gamma/path/process 保持输入，
    #                后续 T-|| 展开及 configuration/system/process judgment 求解器验证。
    def __init__(
        self,
        state: Mapping[str, Any] | None,
        process: Any,
        gamma: Mapping[str, GammaType] | None = None,
        path_condition: Any | None = None,
        name: str | None = None,
    ):
        """复制可变映射，避免调用方后续修改影响正在进行的类型构造。"""
        object.__setattr__(self, "state", {} if state is None else dict(state))
        object.__setattr__(self, "process", process)
        object.__setattr__(self, "gamma", gamma)
        object.__setattr__(self, "path_condition", path_condition)
        object.__setattr__(self, "name", name)


# --------------------------------------------------------------------------
# 论文对应：Section 4.2 的两类判断
#           ``Gamma·Theta·phi |- P :: T`` 与
#           ``Gamma·Theta·phi |- K :: mathcal T`` 的统一程序输入表示。
#           configurations 表示 P 或组合配置 K；path_condition 表示前提 phi。
# 判断对应：一次完整输入 Gamma、Theta、phi 和 configurations 的构造请求。
# 构造方式：TypeConstructionRequest(gamma, theta, configurations,
#                                   path_condition=True)。
# 构造检查：复制环境并把进程、(state, process) 简写统一包装为 Configuration；
#           环境项的具体类型规范化留给 TypeConstructor.construct。
# --------------------------------------------------------------------------
@dataclass(frozen=True)
class TypeConstructionRequest:
    """一次完整的类型构造请求。

    对应 ``Gamma; Pi; Theta |- configurations : types``，其中 ``Pi``
    是可选的共享只读参数环境。请求只包含构造类型所需的左侧信息；由用户给定
    候选 Type AST 并判断其是否匹配属于未来 ``TypeChecker`` 的职责。
    """

    gamma: Mapping[str, GammaType]
    theta: Mapping[str, ChannelType | Any]
    configurations: tuple[Configuration, ...]
    path_condition: Any = True
    parameters: ParameterEnvironment = ParameterEnvironment()

    # 功能：把低层构造接口的多种配置写法规范化成不可变 Configuration 元组。
    # 构造/模型关系：请求不接收期望类型，Type AST 始终由规则从 Process AST 构造。
    def __init__(
        self,
        gamma: Mapping[str, GammaType] | None,
        theta: Mapping[str, ChannelType | Any] | None,
        configurations: Sequence[Configuration | tuple[Mapping[str, Any], Any] | Any],
        path_condition: Any = True,
        parameters: ParameterEnvironment | Mapping[str, Any] | None = None,
    ):
        """规范化环境与配置的多种便捷输入形式。"""
        normalized_configs: list[Configuration] = []
        for item in configurations:
            if isinstance(item, Configuration):
                normalized_configs.append(item)
            elif isinstance(item, tuple) and len(item) == 2 and isinstance(item[0], Mapping):
                normalized_configs.append(Configuration(item[0], item[1]))
            else:
                normalized_configs.append(Configuration({}, item))
        object.__setattr__(self, "gamma", {} if gamma is None else dict(gamma))
        object.__setattr__(self, "theta", {} if theta is None else dict(theta))
        object.__setattr__(self, "configurations", tuple(normalized_configs))
        object.__setattr__(self, "path_condition", path_condition)
        if parameters is None:
            parameter_environment = ParameterEnvironment()
        elif isinstance(parameters, ParameterEnvironment):
            parameter_environment = parameters
        elif isinstance(parameters, Mapping):
            parameter_environment = ParameterEnvironment(parameters)
        else:
            raise TypeError(
                "parameters must be a ParameterEnvironment, mapping, or None"
            )
        object.__setattr__(self, "parameters", parameter_environment)


# --------------------------------------------------------------------------
# 论文对应：保存 Table 2 横线以上需要独立判定的前提，例如 [T-Assert] 的
#           ``phi => B``、[T-Assign] 的 ``phi => phi'{e/x}``、
#           [T-Out] 的 ``phi => refinement{e/eta}``、
#           ODE 规则按形状产生的 safety/domain/boundary dL 前提，以及
#           [T-sigma] 的 ``|= phi[sigma]``。
#           ProofObligation 是实现证据对象，不属于论文的类型语法。
# 结果对应：某条 Table 2 规则产生的一条独立 FOL、dL 或初态证明义务。
# 构造方式：ProofObligation(rule, description, formula, kind="fol",
#                            verdict=UNKNOWN, detail="", proof_formula=None)。
# 构造检查：本类只冻结公式和元数据，不调用 Z3/KeYmaera X；共享规则引擎的
#           顺序 premise 求解器在规则当前位置立即化简、判定并写回不可变
#           副本。当前规则确定性地产生义务，不保存已经废弃的 ODE 候选状态。
# --------------------------------------------------------------------------
@dataclass(frozen=True)
class ProofObligation:
    """某条类型规则产生的一个可独立审计的逻辑证明目标。

    ``kind`` 为 ``fol`` 时交给 Z3 一阶逻辑后端；``dl`` 表示动态逻辑公式，需要
    外部证明器、注解结果或保守地返回 ``UNKNOWN``。``formula`` 永远保留规则
    最初生成的公式；判定完成后，``proof_formula`` 保存实际交给后端的化简式。
    """

    rule: str
    description: str
    formula: Any
    kind: str = "fol"
    verdict: Verdict = Verdict.UNKNOWN
    detail: str = ""
    proof_formula: Any | None = None

    # 功能：保留规则原始公式和来源信息，写入证明器实际输入、结论及说明。
    # 构造/模型关系：formula 始终对应规则生成的 premise；proof_formula 对应
    #                证明器真正收到的化简式。两者分离，防止审计证据被覆盖。
    def decided(
        self,
        verdict: Verdict,
        detail: str = "",
        proof_formula: Any | None = None,
    ) -> "ProofObligation":
        """返回写入判定结果和实际证明器输入后的不可变副本。"""

        return replace(
            self,
            verdict=verdict,
            detail=detail,
            proof_formula=(
                self.formula if proof_formula is None else proof_formula
            ),
        )


# --------------------------------------------------------------------------
# 论文对应：用于判定 Table 2 [T-unrhd]、[T-unrhd']、[T-unrhd''] 中的
#           differential dynamic logic/ODE 前提；论文只要求这些前提成立，
#           本类额外保留证明器不能决定时的 UNKNOWN 和原因。
# 结果对应：dL 后端对单条 ProofObligation 的三值判定和证据说明。
# 构造方式：DLCheckResult(verdict, detail="")。
# 构造检查：纯数据容器，不自行解析证明器输出；KeYmaeraXBackend 负责映射状态。
# --------------------------------------------------------------------------
@dataclass(frozen=True)
class DLCheckResult:
    """外部 dL 后端返回的判定和可审计说明。

    自定义 ``dl_checker`` 也可只返回 ``bool``、``Verdict`` 或字符串；
    KeYmaera X 适配器使用本对象额外保留超时、反例、环境缺失等原因。
    """

    verdict: Verdict
    detail: str = ""


# --------------------------------------------------------------------------
# 论文对应：记录某条 Section 4.3/Table 2 规则为何不可应用，或输入为何不满足
#           Definition 4.1 的环境形状；它是审计设施，不是论文中的判断式。
# 结果对应：无法表示成已判定公式义务的结构错误、类型错误或定位信息。
# 构造方式：Diagnostic(verdict, message, rule="", location="")。
# 构造检查：纯数据容器；TypeConstructor._diagnose 负责选择 verdict、规则和位置。
# --------------------------------------------------------------------------
@dataclass(frozen=True)
class Diagnostic:
    """面向用户的错误、未知结果或规则定位信息。"""

    verdict: Verdict
    message: str
    rule: str = ""
    location: str = ""


# --------------------------------------------------------------------------
# 论文对应：记录类型构造器实际应用 Section 4.2/4.3、Table 2 规则和每条
#           公式 premise 的顺序立即判定；论文只给出推导树，不定义运行时轨迹类。
# 结果对应：一条规则应用时的进程片段、Gamma、Theta、路径条件、符号状态和
#           候选类型，或单条公式的当场判定。它与 ProofObligation 分工：
#           本类说明“如何推导/何时证明”，后者保存具体公式及其证明结果。
# 构造方式：通常由 TypeConstructor._start_step 创建，再用 completed 写入结果。
# 构造检查：所有环境和公式均保存为展示字符串，不能反向参与类型推导。
# --------------------------------------------------------------------------
@dataclass(frozen=True)
class DerivationStep:
    """一次类型规则应用或单条公式立即判定的不可变执行快照。

    ``number`` 是进入规则时分配的先序编号，因此条件、选择或递归产生嵌套
    推导时，报告仍按用户阅读源程序的顺序展示。公式步骤在相应规则与其后继之间
    立即出现；单条公式和证明器证据仍查看 ``ProofObligation``。
    """

    number: int
    rule: str
    location: str
    subject: str
    gamma: tuple[tuple[str, str], ...] = ()
    parameters: tuple[tuple[str, str], ...] = ()
    parameter_constraint: str = ""
    theta: tuple[tuple[str, str], ...] = ()
    path_condition: str = ""
    symbolic_state: tuple[tuple[str, str], ...] = ()
    result: str = ""
    detail: str = ""

    # 功能：保留规则入口快照，只补充递归推导完成后才能得到的结果。
    # 构造/模型关系：不改变证明义务结论；result 是候选类型的显示文本。
    def completed(self, result: str, detail: str = "") -> "DerivationStep":
        """返回写入规则结果和补充说明后的不可变副本。"""

        return replace(self, result=result, detail=detail)


# --------------------------------------------------------------------------
# 论文对应：constructed_type/constructed_component_types 保存 Section 4.2
#           判断右侧的 T 或
#           ``mathcal T``；无法形成正式类型的分量用 None 表示，而绝不借用论文
#           中有独立语义的 BottomType。steps 保存规则推导轨迹，obligations
#           保存 Table 2 前提的判定证据。verdict/diagnostics 是项目面向工具
#           使用者增加的三值审计层。
# 结果对应：一次类型构造及其正确性证明的最终不可变审计报告。
# 构造方式：由 TypeConstructor._report 汇总 verdict、构造类型、义务和诊断。
# 构造检查：本类不重新计算总体 verdict；调用方应信任 _report 使用
#           Verdict.combine 的结果。UNKNOWN 与非空 constructed_type 可同时出现：
#           它表示规则推导已完成，但候选类型尚未被所有义务证实。
# --------------------------------------------------------------------------
@dataclass(frozen=True)
class TypeConstructionReport:
    """类型构造与伴随证明的最终审计报告。

    报告同时保留总体结论、构造类型、全部证明义务和诊断，避免调用方只能看到
    一个布尔值却无法追溯失败原因。``constructed_type is None`` 表示未能形成
    唯一的完整 Table 2 类型；原因可以是结构/静态前提失败，也可以是规则
    候选尚无法唯一确定。``constructed_component_types`` 中的 None 保留对应
    配置的失败或未访问位置。

    ``verdict == UNKNOWN`` 时 ``constructed_type`` 可以非空。这不是“构造结果已
    被证明正确”，
    而是“Table 2 规则推导已形成完整候选类型，但至少一条必要证明义务
    仍未决”。调用方必须将该类型标记为未验证、不可信；``passed`` 仍只在
    verdict 为 TRUE 时成立。
    """

    verdict: Verdict
    constructed_type: _ConfigurationType | None
    constructed_component_types: tuple[_ConfigurationType | None, ...]
    obligations: tuple[ProofObligation, ...]
    diagnostics: tuple[Diagnostic, ...]
    steps: tuple[DerivationStep, ...] = ()

    # 功能：提供传统布尔式成功查询，仅 TRUE 被视为通过。
    # 构造/模型关系：UNKNOWN 必须保持不通过，避免把未证明义务当成成功。
    @property
    def passed(self) -> bool:
        """仅当所有结构检查和证明义务均为 ``TRUE`` 时返回真。"""
        return self.verdict == Verdict.TRUE

    # 功能：统计证明义务的 true/false/unknown 数量并显示构造类型和诊断数。
    # 构造/模型关系：这是展示函数，不重新合并 verdict 或隐藏失败证据。
    def summary(self) -> str:
        """生成紧凑的单行统计，适合测试失败信息和命令行输出。"""
        proved = sum(
            item.verdict == Verdict.TRUE for item in self.obligations
        )
        disproved = sum(
            item.verdict == Verdict.FALSE for item in self.obligations
        )
        unknown = sum(
            item.verdict == Verdict.UNKNOWN for item in self.obligations
        )
        if self.constructed_type is None:
            type_summary = "(none)"
        elif self.verdict is Verdict.TRUE:
            type_summary = format_type_source(self.constructed_type)
        else:
            type_summary = format_type_source(self.constructed_type)
        trust_summary = (
            "trusted"
            if self.verdict is Verdict.TRUE
            else "untrusted"
            if self.constructed_type is not None
            else "unavailable"
        )
        return (
            f"{self.verdict.value}: type={type_summary}; trust={trust_summary}; "
            f"obligations(proved={proved}, false={disproved}, unknown={unknown}); "
            f"diagnostics={len(self.diagnostics)}; steps={len(self.steps)}"
        )

    # 功能：把实现规则名转换为论文 Table 2 中便于人工审计的 premise 形状。
    # 构造/模型关系：只提供公式来源说明；实际公式仍以 obligation.formula 为准。
    @staticmethod
    def _paper_premise(obligation: ProofObligation) -> str:
        """返回证明义务在论文规则中的简写形状或表达式侧条件说明。"""

        exact_shapes = {
            "T-sigma": "[T-sigma-param]  H => phi[sigma]",
            "T-Assert": "[T-Assert]  phi => B",
            "T-Assign-post": "[T-Assign]  phi => phi'{e/x}",
            "T-Out": "[T-Out]  phi => refinement{e/eta}",
            "T-ODE-safety": (
                "[T-unrhd/T-unrhd-prime]  "
                "(phi and t=0) => [ODE,t'=1]"
                "(t<=d => safety)"
            ),
            "T-ODE-domain": "[T-unrhd]  phi => [ODE]B",
            "T-ODE-boundary": (
                "[T-unrhd-prime]  (phi and t=0) => "
                "[ODE,t'=1]"
                "((t<d => B) and (t=d => not B))"
            ),
            "T-mu": "[T-mu]  phi => invariant",
            "T-X": "[T-X]  phi => invariant",
        }
        if obligation.rule in exact_shapes:
            return exact_shapes[obligation.rule]
        if obligation.rule in {"T-Assign", "T-If"}:
            return (
                f"[{obligation.rule}] 表达式类型 judgment 所需的有定义性侧条件"
            )
        return f"[{obligation.rule}] 规则展开产生的具体公式 premise"

    # 功能：说明不同 proof kind 对应的实际判定机制。
    # 构造/模型关系：不声称 dL 一定使用 KeYmaera X，因为低层 TypeConstructor
    #                构造器允许注入其他可信后端。
    @staticmethod
    def _proof_backend(kind: str) -> str:
        """返回 state/FOL/dL 义务的用户可读证明后端说明。"""

        return {
            "state": "初始状态代入 + Z3 表达式求值",
            "fol": "Z3 有效性检查（检查公式否定式是否不可满足）",
            "dl": "配置的 dL 后端（通常为 KeYmaera X）",
        }.get(kind, f"未知证明类别 {kind!r}")

    # 功能：把可能跨多行的 Z3/dL 公式统一缩进成独立文本块。
    # 构造/模型关系：只改变显示缩进，不截断、化简或重写公式内容。
    @staticmethod
    def _append_formula_block(
        lines: list[str],
        label: str,
        value: Any,
    ) -> None:
        """向报告追加带标题和稳定缩进的完整公式文本。"""

        rendered = str(value)
        formula_lines = rendered.splitlines() or [""]
        lines.append(f"     {label}:")
        lines.extend(f"       {line}" for line in formula_lines)

    # 功能：按逻辑类别集中展示本次类型构造实际证明过的完整公式。
    # 构造/模型关系：FOL 清单同时包含普通 Z3 有效性义务和 T-sigma 的状态
    #                代入公式；dL 清单包含 ODE safety/domain/boundary。清单只
    #                重排现有 ProofObligation，不重新化简、证明或改变 active。
    def _append_formula_inventory(
        self,
        lines: list[str],
        *,
        title: str,
        kinds: frozenset[str],
        label: str,
        empty_message: str,
    ) -> dict[int, str]:
        """列出指定类别的证明器输入，并返回义务序号到公式编号的映射。

        两条义务可能来自不同规则候选，却恰好交给证明器同一个公式。此时仍为
        每条义务保留独立编号和结论，但公式正文只在首次出现处打印一次。
        """

        selected = tuple(
            (source_index, obligation)
            for source_index, obligation in enumerate(
                self.obligations,
                start=1,
            )
            if obligation.kind in kinds
        )
        lines.extend(("", title, f"公式数量 : {len(selected)}"))
        if not selected:
            lines.append(empty_message)
            return {}

        status_labels = {
            Verdict.TRUE: "已证明",
            Verdict.FALSE: "未通过",
            Verdict.UNKNOWN: "待证明",
        }
        references: dict[int, str] = {}
        displayed_formulas: dict[str, str] = {}
        for formula_index, (source_index, obligation) in enumerate(
            selected,
            start=1,
        ):
            formula_reference = f"{label}{formula_index:02d}"
            references[source_index] = formula_reference
            lines.extend(
                (
                    "",
                    f"[{formula_reference}] 对应 O{source_index:02d} | "
                    f"{status_labels[obligation.verdict]} | "
                    f"{obligation.rule} | {obligation.kind.upper()}",
                    f"     公式用途 : {obligation.description}",
                    f"     判定后端 : {self._proof_backend(obligation.kind)}",
                )
            )
            proof_formula = (
                obligation.formula
                if obligation.proof_formula is None
                else obligation.proof_formula
            )
            rendered_formula = str(proof_formula)
            previous_reference = displayed_formulas.get(rendered_formula)
            if previous_reference is None:
                self._append_formula_block(
                    lines,
                    "实际检查公式",
                    proof_formula,
                )
                displayed_formulas[rendered_formula] = formula_reference
            else:
                lines.append(
                    "     实际检查公式 : "
                    f"与 [{previous_reference}] 相同，不重复展开"
                )
            lines.append(f"     判定结果 : {obligation.verdict.value}")
        return references

    # 功能：把结构化轨迹、证明义务和诊断统一渲染为可直接阅读的中文报告。
    # 构造/模型关系：只读取已经冻结的证据，不重新运行规则或证明器，也不会
    #                把候选类型生成成功误写成全部证明义务为真。
    def format_detailed(self) -> str:
        """生成包含 FOL/dL 清单、原始公式、证明器输入和遗留义务的报告。"""

        derivation_complete = self.constructed_type is not None
        type_trusted = self.verdict is Verdict.TRUE and derivation_complete
        if type_trusted:
            trust_status = "可信（全部义务已验证）"
        elif not derivation_complete:
            trust_status = "不适用（未形成完整类型）"
        elif self.verdict is Verdict.UNKNOWN:
            trust_status = "不可信（存在未验证义务）"
        else:
            trust_status = "不可信（存在未通过义务）"
        verdict_explanations = {
            Verdict.TRUE: "全部结构检查、静态类型前提和证明义务均已通过",
            Verdict.FALSE: "至少发现结构/静态类型错误或未满足的证明义务",
            Verdict.UNKNOWN: (
                "规则推导已完成，但至少一条必要证明义务仍未决；"
                "构造类型是完整候选，但尚未验证、不可信"
                if derivation_complete
                else "规则推导未能形成唯一完整类型，且存在未决前提或诊断"
            ),
        }
        lines = [
            "=== 类型构造与证明详细报告 ===",
            f"总体结论 : {self.verdict.value}",
            f"结论说明 : {verdict_explanations[self.verdict]}",
            "规则推导 : " + ("已完成" if derivation_complete else "未完成"),
            "类型构造 : " + ("成功" if derivation_complete else "失败"),
            f"类型可信性 : {trust_status}",
            "构造 Type 源码 : "
            + (
                format_type_source(self.constructed_type)
                if derivation_complete
                else "(none)"
            ),
        ]

        if len(self.constructed_component_types) > 1:
            if type_trusted:
                component_heading = "=== 配置分量类型 ==="
            elif self.verdict is Verdict.UNKNOWN:
                component_heading = "=== 配置分量候选类型（未验证） ==="
            else:
                component_heading = "=== 配置分量候选类型（存在未通过义务） ==="
            lines.extend(("", component_heading))
            for index, component_type in enumerate(
                self.constructed_component_types,
                start=1,
            ):
                rendered_component = (
                    format_type_source(component_type)
                    if component_type is not None
                    else "(failed)"
                )
                lines.append(f"K{index}: {rendered_component}")

        proved = sum(
            item.verdict == Verdict.TRUE for item in self.obligations
        )
        disproved = sum(
            item.verdict == Verdict.FALSE for item in self.obligations
        )
        unknown = sum(
            item.verdict == Verdict.UNKNOWN for item in self.obligations
        )

        # 先按逻辑类别给出完整公式清单，使用户无需在混合的顺序证据中逐条
        # 搜索 FOL 或 dL。后面的顺序记录保留规则原始公式，并通过公式编号
        # 引用这里唯一展开的证明器输入，避免完整日志重复打印同一正文。
        formula_references = self._append_formula_inventory(
            lines,
            title="=== 本次类型构造的一阶逻辑（FOL）证明公式 ===",
            kinds=frozenset({"state", "fol"}),
            label="FOL",
            empty_message="(无一阶逻辑公式)",
        )
        formula_references.update(self._append_formula_inventory(
            lines,
            title="=== 本次类型构造的微分动态逻辑（dL）证明公式 ===",
            kinds=frozenset({"dl"}),
            label="DL",
            empty_message="(无 dL 公式)",
        ))

        lines.extend(
            (
                "",
                "=== 顺序公式判定记录 ===",
                f"证明义务 : {len(self.obligations)}",
                f"已证明   : {proved}",
                f"未通过   : {disproved}",
                f"待证明   : {unknown}",
            )
        )
        if not self.obligations:
            lines.append("(无公式判定记录)")
        status_labels = {
            Verdict.TRUE: "已证明",
            Verdict.FALSE: "未通过",
            Verdict.UNKNOWN: "待证明",
        }
        retention_labels = {
            Verdict.TRUE: "已解决；保留公式和证明证据供审计",
            Verdict.FALSE: "未通过；保留为必须修正或确认的证明义务",
            Verdict.UNKNOWN: "未解决；仍需可信证明后端或人工证明",
        }
        for index, obligation in enumerate(self.obligations, start=1):
            lines.extend(
                (
                    "",
                    f"[O{index:02d}] {status_labels[obligation.verdict]} | "
                    f"{obligation.rule} | {obligation.kind.upper()}",
                    f"     论文前提 : {self._paper_premise(obligation)}",
                    f"     证明目标 : {obligation.description}",
                    f"     判定后端 : {self._proof_backend(obligation.kind)}",
                )
            )
            proof_formula = (
                obligation.formula
                if obligation.proof_formula is None
                else obligation.proof_formula
            )
            formula_reference = formula_references.get(index)
            if str(obligation.formula) == str(proof_formula):
                if formula_reference is None:
                    self._append_formula_block(
                        lines,
                        "规则公式 / 证明器实际输入",
                        obligation.formula,
                    )
                else:
                    lines.append(
                        "     规则生成公式与证明器实际输入相同 : "
                        f"见 [{formula_reference}]"
                    )
            else:
                self._append_formula_block(
                    lines,
                    "规则生成公式（原始）",
                    obligation.formula,
                )
                if formula_reference is None:
                    self._append_formula_block(
                        lines,
                        "证明器实际输入",
                        proof_formula,
                    )
                else:
                    lines.append(
                        f"     证明器实际输入 : 见 [{formula_reference}]"
                    )
            lines.append(f"     判定结果 : {obligation.verdict.value}")
            if obligation.detail:
                lines.append(f"     证明器说明: {obligation.detail}")
            lines.append(
                "     处理状态 : "
                + retention_labels[obligation.verdict]
            )

        unresolved = tuple(
            (index, obligation)
            for index, obligation in enumerate(self.obligations, start=1)
            if obligation.verdict != Verdict.TRUE
        )
        lines.extend(("", "=== 未解决或未通过的证明义务 ==="))
        if not unresolved:
            lines.append("(无；所有已生成证明义务均已证明)")
        for index, obligation in unresolved:
            next_action = (
                "修正程序/批注，或检查是否存在反例"
                if obligation.verdict == Verdict.FALSE
                else "配置可信证明后端、增加证明策略，或人工证明"
            )
            lines.append(
                f"[O{index:02d}] {status_labels[obligation.verdict]} | "
                f"{obligation.rule} | 后续操作：{next_action}"
            )

        lines.extend(("", "=== 规则执行过程 ==="))
        if not self.steps:
            lines.append("(未记录规则步骤)")
        for step in sorted(self.steps, key=lambda item: item.number):
            location = step.location or "-"
            lines.append(f"[{step.number:02d}] {step.rule} @ {location}")
            lines.append(f"     检查对象 : {step.subject}")
            if step.gamma:
                lines.append(
                    "     Gamma    : "
                    + ", ".join(f"{name}:{value_type}" for name, value_type in step.gamma)
                )
            else:
                lines.append("     Gamma    : {}")
            if step.parameters:
                lines.append(
                    "     Parameters: "
                    + ", ".join(
                        f"{name}:{value_type}"
                        for name, value_type in step.parameters
                    )
                )
                lines.append(
                    "     参数约束 : "
                    + (step.parameter_constraint or "True")
                )
            if step.theta:
                lines.append(
                    "     Theta    : "
                    + ", ".join(f"{name}:{channel_type}" for name, channel_type in step.theta)
                )
            if step.path_condition:
                lines.append(f"     路径条件 : {step.path_condition}")
            if step.symbolic_state:
                lines.append(
                    "     符号状态 : "
                    + ", ".join(f"{name}={term}" for name, term in step.symbolic_state)
                )
            if step.result:
                result_lines = step.result.splitlines()
                lines.append(f"     规则结果 : {result_lines[0]}")
                lines.extend(
                    f"                  {line}"
                    for line in result_lines[1:]
                )
            if step.detail:
                lines.append(f"     说明     : {step.detail}")

        lines.extend(("", "=== 诊断信息 ==="))
        if not self.diagnostics:
            lines.append("(无诊断；未发现结构或类型错误)")
        for index, diagnostic in enumerate(self.diagnostics, start=1):
            lines.append(
                f"[{index:02d}] {diagnostic.verdict.value} "
                f"{diagnostic.rule or '-'} @ {diagnostic.location or '-'}"
            )
            lines.append(f"     {diagnostic.message}")

        lines.extend(
            (
                "",
                "=== 汇总 ===",
                f"规则步骤 : {len(self.steps)}",
                f"证明记录 : {len(self.obligations)}",
                f"证明义务 : {len(self.obligations)} "
                f"(true={proved}, false={disproved}, unknown={unknown})",
                f"遗留义务 : {len(unresolved)} "
                f"(未通过={disproved}, 待证明={unknown})",
                f"诊断数量 : {len(self.diagnostics)}",
            )
        )
        return "\n".join(lines)


# 论文对应：为 Section 4.3/Table 2 的 ODE 相关 dL 前提提供可替换判定后端；
#           论文未规定 Python callable 接口或 UNKNOWN 返回形式。
# 功能：声明 TypeConstructor 可注入的最小动态逻辑证明器接口。
# 构造/模型关系：输入为单条 ProofObligation；bool/文本会经 Verdict.from_value
#                规范化，None 表示无法处理并应保守得到 UNKNOWN。
DLChecker = Callable[
    [ProofObligation],
    DLCheckResult | Verdict | bool | str | None,
]
