"""Type checker 的公共数据模型。

本模块只定义数据，不执行具体的类型推导。审计代码时可以把这里看成系统的
“词汇表”：

* :class:`BasicType`、:class:`ContinuousType`、:class:`ChannelType` 描述变量
  环境 ``Gamma`` 与通道环境 ``Theta`` 中允许出现的类型；
* :class:`TypingJudgment` 是检查器的输入；
* :class:`InferenceStep`、:class:`ProofObligation`、:class:`Diagnostic` 和
  :class:`CheckReport` 是检查器输出的可审计证据。

本模块中的 ``ProofObligation`` 只保存已经完整生成的 state、FOL 或 dL 公式。
它不保存待求解的谓词变量，也不表示需要从多条约束中综合 T-Assign 的未知
``phi'``。赋值后状态由 ``checker.py`` 在规则展开时通过惰性最强后置状态确定；
这里的数据对象只负责记录后续需要证明的具体目标和证明器返回的三值结果。

HCSP 进程语法由 ``hcsp_process_ast.py`` 独立定义，行为类型语法由
``hcsp_type_ast.py`` 独立定义。本模块只在输入/输出字段的类型注解中引用
``ConfigurationType``，不再定义任何行为类型节点。

────────────────── 模型分层与数据流 ──────────────────────────────────────

本文件中的定义按检查过程分为三层：

* ``BasicType`` 表示普通值变量类型和每个表达式的结果类型，
  ``ContinuousType`` 显式标记 ``Gamma`` 中的连续实变量，``ChannelType`` 表示
  承载一个或多个独立 ``BasicType`` 槽位的 ``Theta`` 项；
* ``Configuration``、``TypingJudgment`` 表示一次检查请求；
* ``InferenceStep``、``ProofObligation``、``Diagnostic``、``CheckReport``
  表示规则执行轨迹、逻辑证据和最终结果。

除明确写出规范化逻辑的构造器外，这些类都是不可变数据容器。Table 2 规则
确定性地产生具体 ``ProofObligation``，统一求解器在该 premise 的推导位置立即
调用 FOL/dL 后端。不能因为公式已经确定或已经进入数据类，就认为对应性质
已经被证明。

────────────────── 与论文 Section 4.2/4.3 的对应 ─────────────────────────

Section 4.1 的行为类型 ``T``、angelic type ``A`` 和 Section 4.2 的组合类型
``mathcal T`` 已全部移入 ``hcsp_type_ast.py``，该文件同时保存逐节点论文对照。

Definition 4.1 的 ``Gamma`` 同时描述值变量、递归变量和连续变量。本项目将其
拆分：公开 ``TypingJudgment.gamma`` 用 ``BasicType`` 表示普通值变量，并用
``ContinuousType`` 显式保存连续向量成员和轨迹必须持续满足的 ``phi``；由于
Gamma 的 Python 映射仍按标量名索引，同一向量声明会登记在它的每个分量名下；
递归类型及边界不变量由
``checker._Context.rec_env`` 和 ``Mu`` 批注保存。连续变量的向量场仍来自对应
``ODE`` 节点，T-ODE 会把节点 safety 与精确匹配该左侧向量的 Gamma 连续
``phi`` 合并验证，而变量类别本身不再由 ODE 左端临时猜测。``Theta``
则由 ``ChannelType`` 表示项目扩展后的 refinement type
``{(eta1:B1,...,etan:Bn) | phi}``；一槽情形退化为论文的
``{eta : B | phi}``。Table 2 的公式前提被记录为 ``ProofObligation``。

────────────────────────────────────────────────────────────────────────────
"""

from __future__ import annotations

from dataclasses import dataclass, replace
from enum import Enum
from typing import Any, Callable, Iterable, Mapping, Sequence

from .expressions import Expr, ExprLike, Literal, ensure_expr
from .hcsp_type_ast import ConfigurationType as _ConfigurationType


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
    """检查结果的三值逻辑。

    ``UNKNOWN`` 不等同于类型错误：它表示结构类型检查已经执行，但某个公式
    未能由当前证明后端判定。只有 ``FALSE`` 才表示已经发现反例或静态错误。
    """

    TRUE = "true"
    FALSE = "false"
    UNKNOWN = "unknown"

    # 功能：把枚举值转成报告中使用的小写文本。
    # 检查/模型关系：不改变真假含义，仅提供稳定显示格式。
    def __str__(self) -> str:
        """返回适合报告与命令行展示的小写结果。"""
        return self.value

    # 功能：兼容自定义证明后端返回的 Verdict、bool 或常见状态文本。
    # 检查/模型关系：只有明确的真/假词汇被采信，其他值一律保守为 UNKNOWN。
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
    # 检查/模型关系：任一 FALSE 使整体为 FALSE；否则任一 UNKNOWN 使整体未知；
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
    # 检查/模型关系：不执行子类型比较；该工作由 is_subtype 完成。
    def __str__(self) -> str:
        """按论文中使用的类型名打印。"""
        return self.value


# 论文对应：把用户输入归一为 Definition 4.1 的基础类型 B；
#           不是 Table 2 中从表达式推导 B 的判断规则。
# 功能：把公开 API 接受的基础类型简写转换为唯一的 BasicType 表示。
# 检查/模型关系：支持 BasicType、Python 类型对象和明确字符串别名；
#                tuple/list 及其他无法识别的对象立即抛出 TypeError。
def normalize_type(value: Any, *, subject: str = "Value type") -> BasicType:
    """把便捷写法归一化为检查器内部唯一的基础值类型。

    调用方可以传入枚举、Python 类型对象或字符串别名。论文未要求积类型，
    因此 tuple/list 不能表示一个普通值的类型。表达式结果、Theta 通信签名中
    的每个独立槽位以及 Gamma 中的普通变量都使用 ``BasicType``；Gamma 中的
    连续变量由 ``ContinuousType`` 额外包装。完整的多槽 Theta 项由
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
# 论文对应：Definition 4.1 的连续变量项
#           ``underlined(v) : R_{>=0} partial-function phi``。
# 角色对应：在公开 Gamma 中显式区分连续实变量与同为 Real 的普通值变量。
# 构造方式：单变量写 ContinuousType()；非平凡轨迹性质写成
#           ContinuousType(phi="x >= 0")；多变量向量写成
#           ContinuousType(variables=("p", "v", "a"), phi=...)。
# 构造检查：当前 HCSP/dL 语义只允许实值连续轨迹，其他基础类型立即拒绝；
#           显式向量必须非空、成员互异且都是合法变量名；phi 在构造时立即转
#           成项目 Expr，布尔类型和有效性只在左侧向量精确匹配的 T-ODE 检查。
# --------------------------------------------------------------------------
@dataclass(frozen=True)
class ContinuousType:
    """一个连续向量的成员、当前值类型及持续性质 ``phi``。

    论文用一个向量项表示 ``v : R_{>=0} partial-function R^n``。项目的 Gamma
    仍按标量变量名索引，因此同一个显式向量声明必须登记在它的每个成员名下。
    例如 ``trajectory = ContinuousType(variables=("p", "v", "a"), phi=...)``
    后，Gamma 的 ``p``、``v``、``a`` 三项都使用 ``trajectory``。省略
    ``variables`` 时，声明表示由当前 Gamma 键确定的单元素向量，保留
    ``{"x": ContinuousType(phi=...)}`` 的简洁写法。

    表达式读取变量时使用 ``value_type`` 所示的当前 Real 值；T-ODE 额外要求
    方程左端具有这个连续标记。只有 ODE 的用户方程左侧向量与 ``variables``
    （或省略时的单元素向量）按顺序精确相等，``phi`` 才是该 ODE 必须验证的
    轨迹条件。ODE 的隐式局部时钟不属于用户向量。构造 dL 义务时，匹配到的
    ``phi`` 与节点 safety 一同进入后置目标，不能作为演化域中的已知假设。
    """

    value_type: BasicType = BasicType.REAL
    variables: tuple[str, ...] | None = None
    phi: Expr = Literal(True)

    def __init__(
        self,
        value_type: Any = BasicType.REAL,
        *,
        variables: Sequence[str] | None = None,
        phi: ExprLike = True,
    ):
        """建立连续实向量类型，并规范化成员及全程状态性质 ``phi``。"""

        normalized = normalize_type(
            value_type,
            subject="Continuous variable value type",
        )
        if normalized != BasicType.REAL:
            raise TypeError(
                "Continuous variables must have current value type Real, "
                f"got {normalized}"
            )
        object.__setattr__(self, "value_type", normalized)
        if variables is None:
            normalized_variables = None
        else:
            if isinstance(variables, (str, bytes)):
                raise TypeError(
                    "Continuous vector variables must be a sequence of names, "
                    "not one string"
                )
            normalized_variables = tuple(variables)
            if not normalized_variables:
                raise ValueError("Continuous vector variables must not be empty")
            if any(
                not isinstance(name, str) or not name.isidentifier()
                for name in normalized_variables
            ):
                raise ValueError(
                    "Continuous vector variables must be valid identifiers"
                )
            if len(set(normalized_variables)) != len(normalized_variables):
                raise ValueError("Continuous vector variables must be distinct")
        object.__setattr__(self, "variables", normalized_variables)
        object.__setattr__(self, "phi", ensure_expr(phi))

    def effective_variables(self, gamma_name: str) -> tuple[str, ...]:
        """返回声明的正式向量；省略 ``variables`` 时使用当前 Gamma 键。"""

        return self.variables if self.variables is not None else (gamma_name,)

    def __str__(self) -> str:
        """按 Definition 4.1 的 ``R>=0 -> phi`` 形式显示声明。"""

        # phi=true 不增加约束，沿用已有的值域显示，避免详细报告把所有旧模型
        # 误写成性质发生了变化；非平凡 phi 则显式展示 Definition 4.1 的性质。
        if isinstance(self.phi, Literal) and self.phi.value is True:
            rendered = "R>=0 ~> Real"
        else:
            rendered = f"R>=0 ~> ({self.phi})"
        if self.variables is None:
            return rendered
        return rendered + " on (" + ", ".join(self.variables) + ")"


# Gamma 项只允许普通基础类型或显式连续实轨迹类型。进程变量类型保存在
# checker 的递归环境中，不与 Python 字符串键上的值变量混用。
GammaType = BasicType | ContinuousType


def normalize_gamma_type(value: Any, *, subject: str = "Gamma entry") -> GammaType:
    """规范化 Gamma 项，同时保留普通 Real 与连续 Real 的类别差异。"""

    if isinstance(value, ContinuousType):
        return value
    try:
        return normalize_type(value, subject=subject)
    except TypeError as exc:
        raise TypeError(
            f"{subject} must be a BasicType or ContinuousType, got {value!r}"
        ) from exc


def gamma_value_type(value: Any, *, subject: str = "Gamma entry") -> BasicType:
    """返回 Gamma 变量在普通表达式中读取当前值时使用的基础类型。"""

    normalized = normalize_gamma_type(value, subject=subject)
    return (
        normalized.value_type
        if isinstance(normalized, ContinuousType)
        else normalized
    )


# 论文对应：服务于 Table 2 的 [T-Assign]、[T-In]、[T-Out] 表达式类型前提；
#           数值提升是项目实现策略，论文表中只写两侧具有基础类型 B。
# 功能：判断实际值类型能否安全流入期望值类型位置。
# 检查/模型关系：实现 Nat <: Int <: Rational <: Real；这里只比较基础值类型，
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
    # 检查/模型关系：不创建 TupleType；每个分量独立规范化为 BasicType。
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
            not isinstance(name, str) or not name.isidentifier()
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
    # 检查/模型关系：只改变面向用户的字符串，不改变 dataclass 的结构表示、
    #                相等性或 T-In/T-Out 的替换逻辑。
    def __str__(self) -> str:
        """返回 ``{(eta1:B1,...) | phi}`` 形式的可读通道类型。"""

        slots = ", ".join(
            f"{binder}:{value_type}"
            for binder, value_type in zip(self.binders, self.value_types)
        )
        refinement = "true" if self.refinement is True else str(self.refinement)
        return f"{{{slots} | {refinement}}}"


# 论文扩展：把公开输入统一为多标量通道 refinement type 记录。
# 功能：把 Theta 项的便捷写法规范化为 ChannelType。
# 检查/模型关系：ChannelType 原样返回；单个 B 形成一槽签名，tuple/list 的
#                全部元素形成多槽类型序列。非平凡 refinement 应显式构造 ChannelType，
#                避免把类型序列与旧式位置简写混淆。
def normalize_channel_type(value: Any) -> ChannelType:
    """把简写的 ``Theta`` 项归一化为 :class:`ChannelType`。

    单个 ``B`` 表示一槽通道，``(B1,...,Bn)`` 表示多槽通道。通道签名元组不是
    ``TupleType``，也不能作为 Gamma 中某个变量的类型。
    """
    if isinstance(value, ChannelType):
        return value
    return ChannelType(value)


# --------------------------------------------------------------------------
# 论文对应：Section 4.2 组合配置判断中的单个 ``(sigma, P)``；Table 2
#           [T-sigma] 由 ``Gamma·Theta·phi |- P :: T`` 和 ``|= phi[sigma]``
#           得到 ``Gamma·Theta·phi |- (sigma, P) :: T``。
# 判断对应：并行规则输入中的单个 <sigma, P> configuration。
# 构造方式：Configuration(state, process, gamma=None, path_condition=None, name=None)。
# 构造检查：复制 state 以隔离调用方修改，但暂不验证 process 属于 HCSP；
#           局部 Gamma、路径条件和结构合法性由 TypeChecker 统一诊断。
# --------------------------------------------------------------------------
@dataclass(frozen=True)
class Configuration:
    """并行判断中的单个 ``<state, process>`` 配置。

    ``gamma`` 和 ``path_condition`` 可以为不同并行叶子声明独立局部环境，
    但不是不受约束的“覆盖”：TypeChecker 要求局部 Gamma 两两不交、与全局
    Gamma 同型且并集恰为全局 Gamma。若使用局部路径，则所有并行叶子都必须
    提供，外层默认 ``true`` 仅表示最终路径由这些局部路径的合取产生。

    ``state`` 是 Gamma 所声明状态空间上的部分赋值：允许
    ``dom(state)`` 是局部 ``dom(Gamma)`` 的真子集，未赋值变量留给
    ``|= phi[state]`` 的有效性检查；但 state 不得引入 Gamma 未声明的变量。

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
    # 检查/模型关系：state=None 规范化为空状态；gamma/path/process 保持输入，
    #                后续 T-|| 展开及 configuration/system/process judgment 求解器验证。
    def __init__(
        self,
        state: Mapping[str, Any] | None,
        process: Any,
        gamma: Mapping[str, GammaType] | None = None,
        path_condition: Any | None = None,
        name: str | None = None,
    ):
        """复制可变映射，避免调用方后续修改影响正在进行的检查。"""
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
#           expected_types 是项目的结果断言接口，不是论文判断的额外前提。
# 判断对应：一次完整输入 Gamma、Theta、phi 和 configurations 的请求。
# 构造方式：TypingJudgment(gamma, theta, configurations, path_condition=True,
#                           expected_types=None)。
# 构造检查：复制环境并把进程、(state, process) 简写统一包装为 Configuration；
#           环境项的具体类型规范化留给 TypeChecker.check。
# --------------------------------------------------------------------------
@dataclass(frozen=True)
class TypingJudgment:
    """一次完整的类型检查请求。

    对应 ``Gamma; Theta |- configurations : types``。``expected_types`` 可选：
    提供时额外校验推导结果，未提供时仅返回推导出的行为类型。
    """

    gamma: Mapping[str, GammaType]
    theta: Mapping[str, ChannelType | Any]
    configurations: tuple[Configuration, ...]
    path_condition: Any = True
    expected_types: tuple[_ConfigurationType, ...] | None = None

    # 功能：把公开 API 的多种配置写法规范化成不可变 Configuration 元组。
    # 检查/模型关系：不按 expected_types 反推类型；它只在推导完成后用于比较。
    def __init__(
        self,
        gamma: Mapping[str, GammaType] | None,
        theta: Mapping[str, ChannelType | Any] | None,
        configurations: Sequence[Configuration | tuple[Mapping[str, Any], Any] | Any],
        path_condition: Any = True,
        expected_types: Sequence[_ConfigurationType] | None = None,
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
        object.__setattr__(
            self,
            "expected_types",
            None if expected_types is None else tuple(expected_types),
        )


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
# 构造检查：本类只冻结公式和元数据，不调用 Z3/KeYmaera X；checker.py 的
#           顺序 premise 求解器在规则当前位置立即化简、判定并写回不可变
#           副本。ODE 候选规则中未被选中的义务会标记 active=False。
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
    active: bool = True
    candidate: str = ""

    # 功能：保留规则原始公式和来源信息，写入证明器实际输入、结论及说明。
    # 检查/模型关系：formula 始终对应规则生成的 premise；proof_formula 对应
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

    旧的自定义 ``dl_checker`` 仍可只返回 ``bool``、``Verdict`` 或字符串；
    KeYmaera X 适配器使用本对象额外保留超时、反例、环境缺失等原因。
    """

    verdict: Verdict
    detail: str = ""


# --------------------------------------------------------------------------
# 论文对应：记录某条 Section 4.3/Table 2 规则为何不可应用，或输入为何不满足
#           Definition 4.1 的环境形状；它是审计设施，不是论文中的判断式。
# 结果对应：无法表示成已判定公式义务的结构错误、类型错误或定位信息。
# 构造方式：Diagnostic(verdict, message, rule="", location="")。
# 构造检查：纯数据容器；TypeChecker._diagnose 负责选择 verdict、规则和位置。
# --------------------------------------------------------------------------
@dataclass(frozen=True)
class Diagnostic:
    """面向用户的错误、未知结果或规则定位信息。"""

    verdict: Verdict
    message: str
    rule: str = ""
    location: str = ""


# --------------------------------------------------------------------------
# 论文对应：记录检查器实际应用 Section 4.2/4.3、Table 2 规则和每条
#           公式 premise 的顺序立即判定；论文只给出推导树，不定义运行时轨迹类。
# 结果对应：一条规则应用时的进程片段、Gamma、Theta、路径条件、符号状态和
#           候选类型，或单条公式的当场判定。它与 ProofObligation 分工：
#           本类说明“如何推导/何时证明”，后者保存具体公式及其证明结果。
# 构造方式：通常由 TypeChecker._start_step 创建，再用 completed 写入结果。
# 构造检查：所有环境和公式均保存为展示字符串，不能反向参与类型推导。
# --------------------------------------------------------------------------
@dataclass(frozen=True)
class InferenceStep:
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
    theta: tuple[tuple[str, str], ...] = ()
    path_condition: str = ""
    symbolic_state: tuple[tuple[str, str], ...] = ()
    result: str = ""
    detail: str = ""

    # 功能：保留规则入口快照，只补充递归推导完成后才能得到的结果。
    # 检查/模型关系：不改变证明义务结论；result 是候选类型的显示文本。
    def completed(self, result: str, detail: str = "") -> "InferenceStep":
        """返回写入规则结果和补充说明后的不可变副本。"""

        return replace(self, result=result, detail=detail)


# --------------------------------------------------------------------------
# 论文对应：inferred_type/component_types 保存 Section 4.2 判断右侧的 T 或
#           ``mathcal T``；无法形成正式类型的分量用 None 表示，而绝不借用论文
#           中有独立语义的 BottomType。steps 保存规则推导轨迹，obligations
#           保存 Table 2 前提的判定证据。verdict/diagnostics 是项目面向工具
#           使用者增加的三值审计层。
# 结果对应：一次类型判断的最终不可变审计报告。
# 构造方式：由 TypeChecker._report 汇总 verdict、推导类型、义务和诊断。
# 构造检查：本类不重新计算总体 verdict；调用方应信任 _report 使用
#           Verdict.combine 的结果，并可通过 passed/summary 读取。
# --------------------------------------------------------------------------
@dataclass(frozen=True)
class CheckReport:
    """类型检查的最终审计报告。

    报告同时保留总体结论、推导类型、全部证明义务和诊断，避免调用方只能看到
    一个布尔值却无法追溯失败原因。``inferred_type is None`` 表示结构或静态
    类型前提未能形成 Table 2 类型，或推导在 false/unknown 公式 premise 处
    停止；``component_types`` 中的 None 保留对应配置的失败或未访问位置。此时
    ``obligations`` 与 ``steps`` 只保存停止点以前已经实际处理的推导前缀，不会
    用未验证的后继拼出候选类型。
    """

    verdict: Verdict
    inferred_type: _ConfigurationType | None
    component_types: tuple[_ConfigurationType | None, ...]
    obligations: tuple[ProofObligation, ...]
    diagnostics: tuple[Diagnostic, ...]
    steps: tuple[InferenceStep, ...] = ()

    # 功能：提供传统布尔式成功查询，仅 TRUE 被视为通过。
    # 检查/模型关系：UNKNOWN 必须保持不通过，避免把未证明义务当成成功。
    @property
    def passed(self) -> bool:
        """仅当所有结构检查和证明义务均为 ``TRUE`` 时返回真。"""
        return self.verdict == Verdict.TRUE

    # 功能：统计证明义务的 true/false/unknown 数量并显示推导类型和诊断数。
    # 检查/模型关系：这是展示函数，不重新合并 verdict 或隐藏失败证据。
    def summary(self) -> str:
        """生成紧凑的单行统计，适合测试失败信息和命令行输出。"""
        active = tuple(item for item in self.obligations if item.active)
        proved = sum(item.verdict == Verdict.TRUE for item in active)
        disproved = sum(item.verdict == Verdict.FALSE for item in active)
        unknown = sum(item.verdict == Verdict.UNKNOWN for item in active)
        return (
            f"{self.verdict.value}: type={self.inferred_type}; "
            f"obligations(proved={proved}, false={disproved}, unknown={unknown}); "
            f"diagnostics={len(self.diagnostics)}; steps={len(self.steps)}"
        )

    # 功能：把实现规则名转换为论文 Table 2 中便于人工审计的 premise 形状。
    # 检查/模型关系：只提供公式来源说明；实际公式仍以 obligation.formula 为准。
    @staticmethod
    def _paper_premise(obligation: ProofObligation) -> str:
        """返回证明义务在论文规则中的简写形状或表达式侧条件说明。"""

        exact_shapes = {
            "T-sigma": "[T-sigma]  |= phi[sigma]",
            "T-Assert": "[T-Assert]  phi => B",
            "T-Assign-post": "[T-Assign]  phi => phi'{e/x}",
            "T-Out": "[T-Out]  phi => refinement{e/eta}",
            "T-ODE-safety": (
                "[T-unrhd/T-unrhd-prime]  "
                "(phi and t=0) => [ODE,t'=1]"
                "(t<=d => (safety and GammaPhi))"
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
    # 检查/模型关系：不声称 dL 一定使用 KeYmaera X，因为公共 API 允许注入后端。
    @staticmethod
    def _proof_backend(kind: str) -> str:
        """返回 state/FOL/dL 义务的用户可读证明后端说明。"""

        return {
            "state": "初始状态代入 + Z3 表达式求值",
            "fol": "Z3 有效性检查（检查公式否定式是否不可满足）",
            "dl": "配置的 dL 后端（通常为 KeYmaera X）",
        }.get(kind, f"未知证明类别 {kind!r}")

    # 功能：把可能跨多行的 Z3/dL 公式统一缩进成独立文本块。
    # 检查/模型关系：只改变显示缩进，不截断、化简或重写公式内容。
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

    # 功能：按逻辑类别集中展示本次运行实际检查过的完整公式。
    # 检查/模型关系：FOL 清单同时包含普通 Z3 有效性义务和 T-sigma 的状态
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
    ) -> None:
        """把指定 proof kind 的证明器输入按 FOL/dL 类别显式列出。"""

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
            return

        status_labels = {
            Verdict.TRUE: "已证明",
            Verdict.FALSE: "未通过",
            Verdict.UNKNOWN: "待证明",
        }
        for formula_index, (source_index, obligation) in enumerate(
            selected,
            start=1,
        ):
            activity = "有效" if obligation.active else "未选候选"
            candidate = (
                f" | candidate={obligation.candidate}"
                if obligation.candidate
                else ""
            )
            lines.extend(
                (
                    "",
                    f"[{label}{formula_index:02d}] 对应 O{source_index:02d} | "
                    f"{activity} | {status_labels[obligation.verdict]} | "
                    f"{obligation.rule} | {obligation.kind.upper()}"
                    f"{candidate}",
                    f"     公式用途 : {obligation.description}",
                    f"     判定后端 : {self._proof_backend(obligation.kind)}",
                )
            )
            self._append_formula_block(
                lines,
                "实际检查公式",
                (
                    obligation.formula
                    if obligation.proof_formula is None
                    else obligation.proof_formula
                ),
            )
            lines.append(f"     判定结果 : {obligation.verdict.value}")

    # 功能：把结构化轨迹、证明义务和诊断统一渲染为可直接阅读的中文报告。
    # 检查/模型关系：只读取已经冻结的证据，不重新运行规则或证明器，也不会
    #                把候选类型生成成功误写成全部证明义务为真。
    def format_detailed(self) -> str:
        """生成包含 FOL/dL 清单、原始公式、证明器输入和遗留义务的报告。"""

        verdict_explanations = {
            Verdict.TRUE: "全部结构检查、静态类型前提和证明义务均已通过",
            Verdict.FALSE: "至少发现结构/静态类型错误或未满足的证明义务",
            Verdict.UNKNOWN: "推导在未决证明义务或不支持的规则边界处停止",
        }
        lines = [
            "=== 类型检查详细报告 ===",
            f"总体结论 : {self.verdict.value}",
            f"结论说明 : {verdict_explanations[self.verdict]}",
            "类型生成 : " + ("成功" if self.inferred_type is not None else "失败"),
            f"推导类型 : {self.inferred_type if self.inferred_type is not None else '(none)'}",
            f"Type AST : {self.inferred_type!r}",
        ]

        if len(self.component_types) > 1:
            lines.extend(("", "=== 配置分量类型 ==="))
            for index, component_type in enumerate(self.component_types, start=1):
                lines.append(f"K{index}: {component_type if component_type is not None else '(failed)'}")

        active_obligations = tuple(
            item for item in self.obligations if item.active
        )
        inactive_obligations = tuple(
            item for item in self.obligations if not item.active
        )
        proved = sum(
            item.verdict == Verdict.TRUE for item in active_obligations
        )
        disproved = sum(
            item.verdict == Verdict.FALSE for item in active_obligations
        )
        unknown = sum(
            item.verdict == Verdict.UNKNOWN for item in active_obligations
        )

        # 先按逻辑类别给出完整公式清单，使用户无需在混合的顺序证据中逐条
        # 搜索 FOL 或 dL。后面的顺序记录仍保留规则原始公式、证明器输入和
        # 证据说明，用于追溯每条公式在推导树中的确切出现位置。
        self._append_formula_inventory(
            lines,
            title="=== 本次检查的一阶逻辑（FOL）公式 ===",
            kinds=frozenset({"state", "fol"}),
            label="FOL",
            empty_message="(无一阶逻辑公式)",
        )
        self._append_formula_inventory(
            lines,
            title="=== 本次检查的微分动态逻辑（dL）公式 ===",
            kinds=frozenset({"dl"}),
            label="DL",
            empty_message="(无 dL 公式)",
        )

        lines.extend(
            (
                "",
                "=== 顺序公式判定记录 ===",
                f"有效义务 : {len(active_obligations)}",
                f"未选候选 : {len(inactive_obligations)}",
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
            activity = "有效" if obligation.active else "未选候选"
            candidate = (
                f" | candidate={obligation.candidate}"
                if obligation.candidate
                else ""
            )
            lines.extend(
                (
                    "",
                    f"[O{index:02d}] {activity} | "
                    f"{status_labels[obligation.verdict]} | "
                    f"{obligation.rule} | {obligation.kind.upper()}"
                    f"{candidate}",
                    f"     论文前提 : {self._paper_premise(obligation)}",
                    f"     证明目标 : {obligation.description}",
                    f"     判定后端 : {self._proof_backend(obligation.kind)}",
                )
            )
            self._append_formula_block(
                lines,
                "规则生成公式（原始）",
                obligation.formula,
            )
            self._append_formula_block(
                lines,
                "证明器实际输入",
                (
                    obligation.formula
                    if obligation.proof_formula is None
                    else obligation.proof_formula
                ),
            )
            lines.append(f"     判定结果 : {obligation.verdict.value}")
            if obligation.detail:
                lines.append(f"     证明器说明: {obligation.detail}")
            lines.append(
                "     处理状态 : "
                + (
                    retention_labels[obligation.verdict]
                    if obligation.active
                    else "所属 ODE 候选规则未被选中；仅保留供审计"
                )
            )

        unresolved = tuple(
            (index, obligation)
            for index, obligation in enumerate(self.obligations, start=1)
            if obligation.active and obligation.verdict != Verdict.TRUE
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

        inactive_unresolved = tuple(
            (index, obligation)
            for index, obligation in enumerate(self.obligations, start=1)
            if not obligation.active and obligation.verdict != Verdict.TRUE
        )
        lines.extend(("", "=== 未选 ODE 候选的未决证据 ==="))
        if not inactive_unresolved:
            lines.append("(无)")
        for index, obligation in inactive_unresolved:
            lines.append(
                f"[O{index:02d}] {obligation.candidate or '-'} | "
                f"{status_labels[obligation.verdict]} | {obligation.rule}"
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
                lines.append(f"     规则结果 : {step.result}")
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
                f"有效义务 : {len(active_obligations)} "
                f"(true={proved}, false={disproved}, unknown={unknown})",
                f"未选候选 : {len(inactive_obligations)}",
                f"遗留义务 : {len(unresolved)} "
                f"(未通过={disproved}, 待证明={unknown})",
                f"诊断数量 : {len(self.diagnostics)}",
            )
        )
        return "\n".join(lines)


# 论文对应：为 Section 4.3/Table 2 的 ODE 相关 dL 前提提供可替换判定后端；
#           论文未规定 Python callable 接口或 UNKNOWN 返回形式。
# 功能：声明 TypeChecker 可注入的最小动态逻辑证明器接口。
# 检查/模型关系：输入为单条 ProofObligation；bool/文本会经 Verdict.from_value
#                规范化，None 表示无法处理并应保守得到 UNKNOWN。
DLChecker = Callable[
    [ProofObligation],
    DLCheckResult | Verdict | bool | str | None,
]
