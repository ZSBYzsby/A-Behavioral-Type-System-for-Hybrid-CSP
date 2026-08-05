r"""HCSP process AST、构造期良构检查及 Section 4.2/4.3 批注。

────────────────── 语法范畴与继承关系 ──────────────────────────────────────

本模块按论文的三个语法范畴组织节点：

* ``EventReaction`` 对应事件反应 ``E``，它不是进程或系统；
* ``Process`` 对应顺序进程 ``P``，并且继承 ``HCSP``；
* ``HCSP`` 对应系统 ``S``，即一个 ``P`` 或二元并行 ``S || S'``。

因此，事件反应只能出现在 ODE 的中断字段中；``Parallel`` 属于系统层，不能
作为 ``If``、``Sequence``、``Mu`` 等要求 ``P`` 的位置。

文件正文依次定义离散进程与事件节点、ODE 批注和隐藏时钟、递归及
Assumption 2.2、并行系统及 Assumption 2.1。类型推导不在本文件执行，而在
``checker.py`` 中按 Table 2 完成。

────────────────── 基础语法与多标量通信扩展 ───────────────────────────────

除通信参数表和内部选择的规范 AST 形状外，下面的 E/P/S 结构对应论文
Section 2.1。项目把论文的单值通信扩展为一次传递一个或多个独立标量；
同时把论文可通过顺序组合写出的 ``(P \sqcup P'); Q`` 规范化为唯一三元
``InternalChoice(P, P_prime, Q)``。构造时可省略第三个实参，但 AST 对象的
第三字段仍会保存 ``Skip()``。
不易用 ASCII 准确表示的运算符写成未渲染的 LaTeX 命令。字符串表达式会立即通过
``ensure_expr`` 转为项目自己的 ``Expr``。

.. code-block:: text

    E ::= empty
        | (ch?(x1, ..., xn) -> P) \Box E
        | (ch!(e1, ..., en) -> P) \Box E

    empty                         EmptyEvent()
    (ch?(x1,...,xn) -> P) \Box E
        EventChoice(InputChannel("ch", ("x1", ..., "xn")), P, E)
    (ch!(e1,...,en) -> P) \Box E
        EventChoice(OutputChannel("ch", (e1, ..., en)), P, E)

    P ::= skip
        | x := e
        | assert(B)
        | ch?(x1, ..., xn)
        | ch!(e1, ..., en)
        | if B then P else P'
        | <dot(v)=e & B> \unrhd E
        | P; P'
        | (P \sqcup P'); P''
        | X
        | mu X.P

    skip                          Skip()
    x := e                        Assign("x", e)
    assert(B)                     Assert(B)
    ch?(x1,...,xn)                InputChannel("ch", ("x1", ..., "xn"))
    ch!(e1,...,en)                OutputChannel("ch", (e1, ..., en))
    if B then P else P'           If(B, P, P_prime)
    <dot(v)=e & B> \unrhd E       ODE([("v", e)], B, E,
                                      annotation=ODEAnnotation(...))
    P; P'                         Sequence(P, P_prime)
    (P \sqcup P'); P''            InternalChoice(P, P_prime, P_double_prime)
    P \sqcup P'                   InternalChoice(P, P_prime)  # Q = Skip()
    X                             Var("X")
    mu X.P                        Mu("X", P,
                                      annotation=RecursionAnnotation(...))

    S ::= P
        | S || S'

    P                             任意 Process 节点可直接作为 HCSP 系统
    S || S'                       Parallel(S, S_prime)

通信构造器采用项目扩展后的多标量产生式：``InputChannel`` 必须至少给出一个
接收目标，``OutputChannel`` 必须至少给出一个输出表达式。每个目标和表达式仍
分别对应一个标量值；通信列表不是普通表达式 tuple，也不会产生 ``TupleType``。
单参数形式是构造器语法糖；AST 内部始终保存非空元组。它和其他语法糖的统一
展开写在文件头后面的“Python 语法糖与规范 AST”一节。

────────────────── Assumption 2.1 构造期检查 ───────────────────────────────

项目检查 Assumption 2.1 的 ``fv(S) \cap bv(S) = \emptyset``。输入动作
``ch?(x1,...,xn)`` 把全部 ``xi`` 加入值变量的 ``bv``，并绑定其顺序后继或
事件分支 continuation 中的同名变量；``mu X.P`` 把进程变量 ``X`` 加入
``bv``，并绑定递归体 ``P`` 中的 ``X``。如果同名变量还在绑定范围之外自由
出现，构造器会立即拒绝该 AST。

本项目约定，复合顺序前缀中出现的输入绑定可作用于该前缀的公共
顺序后继。因此 ``If(B, InputChannel("ch", ("x",)), Skip()); P(x)``
按这一已确认的作用域约定处理，不会因为某个分支没有执行输入而被
额外拒绝。这是本项目对顺序绑定范围的明确规定，并非实现遗漏。

构造 ``Parallel(S1, S2)`` 时还会检查两个分量的 ``V``、``iCh`` 和 ``oCh``
分别不相交。同一通道在两侧一端输入、一端输出是合法同步，不属于同向通道
冲突。这里 ``V = fv \uplus bv``，值变量和进程变量分别计算后参与分区。

────────────────── Assumption 2.2 构造期检查 ───────────────────────────────

构造 ``Mu("X", P)`` 时会检查 ``P`` 中受该 ``mu`` 绑定的每个 ``Var("X")``：
从递归入口到该回边的每条控制流路径都必须先经过 ``InputChannel`` 或
``OutputChannel``。赋值、断言、ODE 演化和选择节点本身都不算通信。

检查遵守词法作用域；内层同名 ``Mu("X", ...)`` 会遮蔽外层绑定。对于顺序
组合，只有此前所有可能路径都已经通信，后继中的 ``X`` 才算受保护；对于
``If`` 和内部选择，则逐分支检查。ODE 的事件 continuation 由其事件通信保护，
但 ODE 的自然结束路径不会把通信保护传给外层顺序后继。

────────────────── 公开变量收集接口 ────────────────────────────────────────

``get_vars()`` 返回子树中所有用户可见的值变量，即自由值变量与输入绑定值变量
的并集；它不等于论文中的 ``fv``，也不包含进程变量或 ODE 隐藏时钟。
``get_input_bound_vars()`` 只返回可能由输入动作引入的目标名，供检查器建立局部
Gamma 和并行分量环境。精确的 ``fv``、``bv``、``iCh``、``oCh`` 分析由文件
末尾的私有 ``_Assumption21Info`` 系列函数完成。

────────────────── 带批注 HCSP 与构造器 ────────────────────────────────────

Section 4.2/4.3 不增加新的 ``P`` 节点，而是在既有 ODE/Mu 节点上附加安全性质
或递归不变量 ``phi``；Remark 4.1 另外要求 ODE 的精确演化时长 ``d`` 由外部
提供。项目把 ODE 的 ``phi`` 与 ``d`` 放入同一个强类型批注对象，并使用下面
的记号：

.. code-block:: text

    ODE:  <dot(v)=e & B>_safety \unrhd[d] E
    mu:   mu X_invariant.P

对应构造方式为：

.. code-block:: python

    ODE(
        [("v", e)],
        B,
        E,
        annotation=ODEAnnotation(safety=safety, delay=d),
    )

    Mu(
        "X",
        P,
        annotation=RecursionAnnotation(invariant),
    )

``safety`` 和 ``invariant`` 省略时均规范化为 ``true``。每个 ODE 必须显式
提供 ``ODEAnnotation``，其中 Remark 4.1 的外部 ``delay`` 也必须显式提供：

* 有限 ``d`` 必须是可静态计算的非负有理常量；
* 有限值统一保存为精确的 ``Literal(Fraction(...))``；
* 正无穷统一保存为 ``math.inf``；
* 缺失、负数、符号变量、Bool、NaN、负无穷和非有理常量式会立即报错。

例如 ``delay=2``、``delay=Fraction(1, 2)``、``delay="1 / 4 + 1 / 4"``
和 ``delay=math.inf`` 合法；``delay="d"`` 和 ``delay=-1`` 不合法。

────────────────── Python 语法糖与规范 AST ─────────────────────────────────

下式左侧统一写便捷输入，右侧统一写规范 AST。多项组合和 ``wait(d)`` 均作为
对应 AST 类的类方法提供；直接调用类本身仍只构造论文规定的二元或递归节点。
单参数通信直接复用 AST 类的构造器。等号表示构造规范化，不是新增 AST
产生式。

.. code-block:: text

    InputChannel("ch", "x")
      = InputChannel("ch", ("x",))

    OutputChannel("ch", e)
      = OutputChannel("ch", (e,))

    Sequence.of()
      = Skip()

    Sequence.of(P1, ..., Pn)
      = Sequence(P1, ... Sequence(Pn-1, Pn) ...)

    InternalChoice.of(P1, ..., Pn, continuation=Q)
      = InternalChoice(P1, ... InternalChoice(Pn-1, Pn) ..., Q)

    EventChoice.of()
      = EmptyEvent()

    EventChoice.of((comm1, P1), ..., (commn, Pn))
      = EventChoice(comm1, P1, ...
          EventChoice(commn, Pn, EmptyEvent()) ...)

    Parallel.of(S1, ..., Sn)
      = Parallel(S1, ... Parallel(Sn-1, Sn) ...)

    ODE.wait(d)
      = Sequence(ODE._for_wait(d), Skip())

这里 ``e`` 若是字符串 ``"x"``，会按表达式规则解析为 ``Variable("x")``，
不是字符串值。``ODE._for_wait`` 是 ``ODE.wait`` 专用的私有初始化入口，
不是新的 AST 节点：它产生的仍是 ``ODE``，其规范源字段等价于
``ODE((), True, EmptyEvent(), annotation=ODEAnnotation(safety=True, delay=d))``，
并把隐藏 ``local_clock_deadline`` 设为规范化后的有限 ``d``。

``ODE.wait(d)`` 只实现源级 ``wait(d)`` 语法糖，不增加新的进程节点。
Table 2 的有限时延 ODE 证明前提使用新鲜时钟 ``t``。为了让所有 ODE 采用
统一结构，项目使每个 ``ODE`` 节点都自动拥有一个独立的 ``ODELocalClock``。
该隐藏时钟进入 ODE 时自动取 0，并以导数 1 随连续时间演化。在该 ODE 的
方程右端、演化域 ``B`` 和安全批注 ``safety`` 中，保留名 ``t`` 表示这个
时钟的当前值；用户不能再把 ``t`` 写成 ODE 方程左端，因为 ``t'=1`` 已由
节点自动提供。这个局部名不进入 Gamma、fv、bv、``get_vars()`` 或并行分区
V，因此不同 ODE（包括并行 ODE）的时钟不会发生名称碰撞。

类型检查器在构造 dL 义务时才把这个抽象时钟实体化为新鲜 Real 符号，并加入
入口等式 ``t=0`` 与演化方程 ``t'=1``。用户不再需要仅为了在本 ODE 的公式
中读取演化时间而显式声明、初始化辅助时钟。局部 ``t`` 的作用域不包含事件
分支 continuation 或 ODE 的顺序后继；那些位置若需要持久可观察的时钟，仍应
使用另一个普通状态变量并在 Gamma 中显式声明。

AST 节点类别仍与论文 Section 2.1 的 E/P/S 构造类别一致；项目差异是通信
参数表的多标量扩展、既有 ODE/Mu 节点上的批注字段，以及内部选择将论文中
等价的 ``Sequence(InternalChoice(P, P'), Q)`` 规范保存为三元
``InternalChoice(P, P', Q)``。这只改变 AST 的唯一表示，不改变 HCSP 运行语义。

────────────────────────────────────────────────────────────────────────────

"""

from __future__ import annotations

from abc import ABC, abstractmethod
from dataclasses import dataclass, field
from decimal import Decimal
from fractions import Fraction
from math import inf, isinf, isnan
from typing import Iterable

from .expressions import (
    BinaryExpr,
    Expr,
    ExprLike,
    Literal,
    UnaryExpr,
    Variable,
    ensure_expr,
    ensure_variable,
)


# ────────────────── E/P/S 分类、标识符与原子进程 ───────────────────────────

# --------------------------------------------------------------------------
# 论文对应：Section 2.1 的系统范畴 S ::= P | S \parallel S'。
# 构造方式：HCSP 是抽象基类，不直接实例化；
#           Process 和 Parallel 提供具体节点。
# 构造检查：抽象 get_vars 阻止直接实例化裸 HCSP；
#           具体树形约束由各子类构造器立即检查。
# --------------------------------------------------------------------------
class HCSP(ABC):
    """系统语法 ``S`` 的共同基类。"""

    # 功能：抽象收集系统中全部用户可见的值变量名称，既包括自由使用，
    #       也包括 ch?(x1,...,xn) 引入的全部输入目标；进程变量 X 不属于此返回值。
    # 检查/论文关系：类型检查器用结果投影/检查 Gamma；Parallel 另由内部
    #                fv/bv 分析同时检查值变量和进程变量的 V 分离条件。
    @abstractmethod
    def get_vars(self) -> set[str]:
        """返回系统读取、写入或由输入引入的用户值变量。"""

    # 功能：从 get_vars 的值变量中单独标出多标量输入引入的全部目标变量。
    # 检查/论文关系：并行 Gamma 自动分区时，这些名称允许在输入发生前没有
    #                外部声明；T-In 随后按 Theta 各槽类型把 xi 加入局部 Gamma。
    def get_input_bound_vars(self) -> set[str]:
        """返回可由 T-In 在局部 Gamma 中新引入的输入目标变量。"""
        return set()


# --------------------------------------------------------------------------
# 论文对应：Section 2.1 的顺序进程范畴 P，同时由产生式 S ::= P 成为系统。
# 构造方式：Process 是抽象分类基类；Skip、Assign、ODE、Mu 等是具体构造器。
# 构造检查：继承 HCSP 的抽象 get_vars，因此不能形成裸 Process；
#           它还用于阻止 EventReaction 或 Parallel 混入要求 P 的位置。
# --------------------------------------------------------------------------
class Process(HCSP, ABC):
    """论文顺序进程语法 ``P`` 的共同基类。"""


# --------------------------------------------------------------------------
# 论文对应：Section 2.1 的事件反应范畴
#           E ::= empty | (ch★ \rightarrow P) \Box E。
# 构造方式：EventReaction 不直接实例化，由 EmptyEvent 和 EventChoice 构造。
# 构造检查：抽象 get_vars 阻止直接实例化裸 EventReaction；该范畴与 P、S
#           分离，保证事件反应只进入 ODE 的中断位置。
# --------------------------------------------------------------------------
class EventReaction(ABC):
    """论文事件反应语法 ``E`` 的共同基类。"""

    # 功能：抽象收集事件前缀、分支后继及其余事件分支中的用户值变量。
    # 检查/论文关系：E 不是独立系统，但 ODE 和并行分区需要把中断分支所用
    #                的变量纳入包含它的 Process；此接口本身不做类型检查。
    @abstractmethod
    def get_vars(self) -> set[str]:
        """返回事件反应及其后继使用的用户值变量；具体节点必须实现。"""

    # 功能：单独收集事件分支内 ch?(x1,...,xn) 写入的全部目标变量。
    # 检查/论文关系：结果用于 Gamma 缺失声明豁免；通道是否存在及其槽位类型
    #                仍由事件分支实际进入 T-In 时检查。
    def get_input_bound_vars(self) -> set[str]:
        """返回事件输入分支写入的目标变量。"""
        return set()


# --------------------------------------------------------------------------
# 论文扩展：多标量通信动作 ch?(x1,...,xn)、ch!(e1,...,en) 中的通道标识 ch。
# 构造方式：Channel("ch")；多数进程构造器也接受字符串并调用 ensure_channel。
# 构造检查：立即要求名称满足与状态变量相同的 Python 标识符词法规则；
#           Theta 中是否声明由 T-In/T-Out 检查。
# --------------------------------------------------------------------------
@dataclass(frozen=True)
class Channel:
    """HCSP 通道标识符。"""

    name: str

    # 功能：完成 dataclass 构造后的通道名称边界检查。
    # 检查/论文关系：拒绝非字符串及非标识符，确保 ch 可无歧义登记到 Theta。
    def __post_init__(self) -> None:
        """通道名必须满足与项目变量名相同的 ``str.isidentifier`` 规则。"""
        if not isinstance(self.name, str) or not self.name.isidentifier():
            raise ValueError(f"Invalid channel name: {self.name!r}")

    # 功能：把严格 Channel 还原为 Theta 和诊断信息使用的源码名称。
    # 检查/论文关系：不做新检查，只返回已经由 __post_init__ 验证的名称。
    def __str__(self) -> str:
        """返回通道环境 ``Theta`` 使用的名称。"""
        return self.name


# 功能：把字符串简写统一转换为 Channel，同时保留已经构造好的 Channel。
# 检查/论文关系：拒绝其他对象；字符串还会经过 Channel 的标识符词法检查。
def ensure_channel(value: str | Channel) -> Channel:
    """把字符串通道名转换为严格 ``Channel``。"""
    if isinstance(value, Channel):
        return value
    if isinstance(value, str):
        return Channel(value)
    raise TypeError(f"Expected a Channel or string name, got {value!r}")


# --------------------------------------------------------------------------
# 论文对应：Section 2.1 的进程变量产生式 P ::= X，以及递归体中的调用位置。
# 构造方式：Var("X")。
# 构造检查：立即要求 X 是 Python 合法标识符；所属 Mu 构造器负责词法绑定及
#           Assumption 2.1/2.2，未绑定引用和尾位置由 T-X 检查。
# --------------------------------------------------------------------------
@dataclass(frozen=True)
class Var(Process):
    """进程变量 ``X``。"""

    name: str

    # 功能：检查进程变量的词法形状。
    # 检查/论文关系：只保证 X 可作为变量名，
    #                不在 AST 阶段判断它是否受 mu 绑定。
    def __post_init__(self) -> None:
        """进程变量名必须是合法标识符。"""
        if not isinstance(self.name, str) or not self.name.isidentifier():
            raise ValueError(f"Invalid process variable: {self.name!r}")

    # 功能：说明 X 是控制流变量，而不是 Gamma 中的用户值变量。
    # 检查/论文关系：返回空集；X 的类型绑定保存在递归环境而不是值变量环境。
    def get_vars(self) -> set[str]:
        """进程变量不属于用户值变量集合。"""
        return set()


# --------------------------------------------------------------------------
# 论文对应：Section 2.1 的 P ::= skip；Table 2 的 T-End/T-Skip。
# 构造方式：Skip()。
# 构造检查：无参数且无需结构检查；终止或中间 no-op 的区别由上下文决定。
# --------------------------------------------------------------------------
@dataclass(frozen=True)
class Skip(Process):
    """空进程 ``skip``。"""

    # 功能：报告 skip 不读取也不写入任何用户值变量。
    # 检查/论文关系：返回空集；T-End/T-Skip 的行为在类型推导阶段决定。
    def get_vars(self) -> set[str]:
        """Skip 不读写用户值变量。"""
        return set()


# --------------------------------------------------------------------------
# 论文对应：Section 2.1 的 P ::= x := e；Table 2 的 T-Assign。
# 构造方式：Assign("x", e) 或 Assign(Variable("x"), e)。
# 构造检查：立即规范化左值和表达式；
#           Gamma 声明及赋值类型相容性由 T-Assign 检查。
# --------------------------------------------------------------------------
@dataclass(frozen=True)
class Assign(Process):
    """赋值进程 ``x := e``。"""

    target: Variable
    expression: Expr

    # 功能：把赋值的左值与右值转换为项目内部的严格表达式节点。
    # 检查/论文关系：左值必须是变量；右值语法合法，
    #                但其类型在 T-Assign 才检查。
    def __init__(self, target: str | Variable, expression: ExprLike):
        """规范化标量左值和右值表达式。"""
        object.__setattr__(self, "target", ensure_variable(target))
        object.__setattr__(self, "expression", ensure_expr(expression))

    # 功能：合并赋值目标和右值自由变量，得到该节点的用户值变量域。
    # 检查/论文关系：只收集名称，不证明 Table 2 的替换蕴含或赋值类型正确。
    def get_vars(self) -> set[str]:
        """赋值变量域包含左值和右值自由变量。"""
        return {self.target.name} | self.expression.get_vars()


# --------------------------------------------------------------------------
# 论文对应：Section 2.1 的 P ::= assert(B)；Table 2 的 T-Assert。
# 构造方式：Assert(B)，其中 B 可为 Expr 或受支持的表达式字符串。
# 构造检查：立即解析 B；它是否为 Bool 且由当前路径条件推出由 T-Assert 检查。
# --------------------------------------------------------------------------
@dataclass(frozen=True)
class Assert(Process):
    """断言进程 ``assert(B)``。"""

    condition: Expr

    # 功能：把断言条件规范化为项目表达式 AST。
    # 检查/论文关系：这里只检查表达式语法，
    #                论文前提 phi => B 留给类型检查器。
    def __init__(self, condition: ExprLike):
        """把断言条件转换为严格表达式。"""
        object.__setattr__(self, "condition", ensure_expr(condition))

    # 功能：返回断言公式 B 中出现的用户值变量。
    # 检查/论文关系：不判断变量是否在 Gamma 中，
    #                后续表达式翻译阶段负责该检查。
    def get_vars(self) -> set[str]:
        """返回断言条件中的变量。"""
        return self.condition.get_vars()


# ────────────────── 多标量通信节点 ─────────────────────────────────────────

# 功能：把一个或多个输入目标规范化为非空、无重复的标量变量元组。
# 检查/语法关系：tuple/list 只描述一次通信的参数表，不是表达式 tuple；
#                单个字符串或 Variable 是长度为 1 的便捷输入。
def _normalize_input_targets(
    targets: str | Variable | Iterable[str | Variable],
) -> tuple[Variable, ...]:
    """规范化 ``ch?(x1,...,xn)`` 的全部标量接收目标。"""

    raw_targets = (
        tuple(targets)
        if isinstance(targets, (tuple, list))
        else (targets,)
    )
    if not raw_targets:
        raise ValueError("Input communication needs at least one target")
    normalized = tuple(ensure_variable(target) for target in raw_targets)
    names = tuple(target.name for target in normalized)
    if len(set(names)) != len(names):
        raise ValueError("Input communication targets must be distinct")
    return normalized


# 功能：把一个或多个输出项规范化为非空的标量表达式元组。
# 检查/语法关系：外层 tuple/list 是通信参数表；每个分量必须独立通过
#                ensure_expr，因此嵌套 tuple/list 仍不是合法标量表达式。
def _normalize_output_payloads(
    payloads: ExprLike | Iterable[ExprLike],
) -> tuple[Expr, ...]:
    """规范化 ``ch!(e1,...,en)`` 的全部标量输出表达式。"""

    raw_payloads = (
        tuple(payloads)
        if isinstance(payloads, (tuple, list))
        else (payloads,)
    )
    if not raw_payloads:
        raise ValueError("Output communication needs at least one payload")
    return tuple(ensure_expr(payload) for payload in raw_payloads)


# --------------------------------------------------------------------------
# 项目扩展：输入动作 P ::= ch?(x1, ..., xn)，每个 xi 仍是标量变量。
# 构造方式：InputChannel("ch", ("x1", ..., "xn"))；单个 "x" 是一槽简写。
# 构造检查：立即验证通道和全部变量，拒绝空列表及重复目标；组合进更大 AST
#           时将所有 xi 计入 bv；Theta、逐槽类型和联合 refinement 由 T-In 检查。
# --------------------------------------------------------------------------
@dataclass(frozen=True)
class InputChannel(Process):
    """一次接收多个独立标量的输入动作 ``ch?(x1,...,xn)``。"""

    channel: Channel
    targets: tuple[Variable, ...]

    # 功能：规范化通道及全部接收目标，并把单目标简写转为一槽元组。
    # 检查/论文关系：本节点检查非空、名称和互异性；组成更大 AST 时，
    #                Assumption 2.1 再检查任一 xi 是否也在绑定范围外自由出现。
    def __init__(
        self,
        channel: str | Channel,
        targets: str | Variable | Iterable[str | Variable],
    ):
        """规范化输入通道和非空标量目标序列。"""
        object.__setattr__(self, "channel", ensure_channel(channel))
        object.__setattr__(self, "targets", _normalize_input_targets(targets))

    # 功能：把全部输入目标计入该进程的用户值变量域。
    # 检查/论文关系：用于 Gamma 投影和并行分区；各 xi 的类型由 T-In 从
    #                Theta 的对应槽位获得，不要求预先声明。
    def get_vars(self) -> set[str]:
        """全部输入目标都属于进程的用户值变量域。"""
        return {target.name for target in self.targets}

    # 功能：标记全部 xi 的值由当前通信输入写入。
    # 检查/论文关系：T-In 为每个 xi 建立新接收值；该集合也用于环境收集。
    def get_input_bound_vars(self) -> set[str]:
        """输入目标由当前通信动作绑定。"""
        return self.get_vars()


# --------------------------------------------------------------------------
# 项目扩展：输出动作 P ::= ch!(e1, ..., en)，每个 ei 仍是标量表达式。
# 构造方式：OutputChannel("ch", (e1, ..., en))；单个 e 是一槽简写。
# 构造检查：立即验证通道和全部表达式，拒绝空列表及非标量分量；Theta、
#           逐槽值类型和联合 refinement 蕴含由 T-Out 检查。
# --------------------------------------------------------------------------
@dataclass(frozen=True)
class OutputChannel(Process):
    """一次发送多个独立标量的输出动作 ``ch!(e1,...,en)``。"""

    channel: Channel
    payloads: tuple[Expr, ...]

    # 功能：规范化通道及全部发送表达式，并把单表达式简写转为一槽元组。
    # 检查/论文关系：本节点检查参数表非空及各 ei 的表达式语法；逐槽类型和
    #                联合 refinement 留给 T-Out。
    def __init__(
        self,
        channel: str | Channel,
        payloads: ExprLike | Iterable[ExprLike],
    ):
        """规范化输出通道和非空标量表达式序列。"""
        object.__setattr__(self, "channel", ensure_channel(channel))
        object.__setattr__(self, "payloads", _normalize_output_payloads(payloads))

    # 功能：返回全部输出表达式 ei 中的自由用户值变量并集。
    # 检查/论文关系：变量是否已在 Gamma 声明由 T-Out 的表达式翻译检查。
    def get_vars(self) -> set[str]:
        """合并全部输出分量中的自由变量。"""
        return set().union(*(payload.get_vars() for payload in self.payloads))


# ────────────────── 复合离散进程与事件反应 ─────────────────────────────────

# --------------------------------------------------------------------------
# 论文对应：Section 2.1 的 P ::= if B then P else P'；Table 2 的 T-If。
# 构造方式：If(B, then_process, else_process)，必须显式给出两个分支。
# 构造检查：立即解析 B 并要求两分支都是 Process；
#           合并分支后检查 Assumption 2.1；B 的 Bool 类型由 T-If 检查。
# --------------------------------------------------------------------------
@dataclass(frozen=True)
class If(Process):
    """二元条件进程 ``if B then P else P'``。"""

    condition: Expr
    then_branch: Process
    else_branch: Process

    # 功能：建立严格二元条件节点并规范化条件表达式。
    # 检查/论文关系：拒绝 E、Parallel 或缺失分支，保持论文的二元 P 产生式。
    def __init__(
        self,
        condition: ExprLike,
        then_branch: Process,
        else_branch: Process,
    ):
        """规范化条件，并要求两个分支都是论文顺序进程 ``P``。"""
        if not isinstance(then_branch, Process) or not isinstance(else_branch, Process):
            raise TypeError("If branches must be Process nodes")
        object.__setattr__(self, "condition", ensure_expr(condition))
        object.__setattr__(self, "then_branch", then_branch)
        object.__setattr__(self, "else_branch", else_branch)
        _validate_assumption21(self)

    # 功能：合并条件、then 分支和 else 分支的用户值变量。
    # 检查/论文关系：只做静态收集；分支分别在 phi∧B、phi∧¬B 下检查。
    def get_vars(self) -> set[str]:
        """合并条件和两个分支使用的变量。"""
        return set(_assumption21_info(self).value_variables)

    # 功能：合并两个条件分支内由输入动作绑定的变量。
    # 检查/论文关系：不把条件 B 中的普通自由变量误认为输入绑定变量。
    def get_input_bound_vars(self) -> set[str]:
        """合并两个分支引入的输入变量。"""
        return set(_assumption21_info(self).bound_value_variables)


# --------------------------------------------------------------------------
# 论文对应：Section 2.1 的事件产生式 E ::= empty。
# 构造方式：EmptyEvent()。
# 构造检查：无参数；作为事件选择递归的终点，不是 Process 或 HCSP 系统。
# --------------------------------------------------------------------------
@dataclass(frozen=True)
class EmptyEvent(EventReaction):
    """空事件反应 ``E ::= empty``。"""

    # 功能：报告空事件反应不包含用户值变量。
    # 检查/论文关系：返回空集，与 E 的递归终止分支一致。
    def get_vars(self) -> set[str]:
        """空事件不使用用户值变量。"""
        return set()


# --------------------------------------------------------------------------
# 论文对应：Section 2.1 的 E ::= (ch★ \rightarrow P) \Box E。
# 构造方式：EventChoice(communication, continuation, alternative)。
# 构造检查：前缀只能是多标量输入/输出，后继必须是 P，余项必须是 E；
#           alternative=None 立即规范化为 EmptyEvent。输入前缀只绑定本分支
#           continuation；与 alternative 的自由/绑定重名由 Assumption 2.1 拒绝。
# --------------------------------------------------------------------------
@dataclass(frozen=True)
class EventChoice(EventReaction):
    r"""一个事件分支 ``(ch★ \rightarrow P) \Box E``。"""

    communication: InputChannel | OutputChannel
    continuation: Process
    alternative: EventReaction

    # 功能：构造一个通信守卫的外部选择分支，并连接递归事件余项。
    # 检查/论文关系：逐层保证 Table 2 的外部选择规则
    #                所处理的每个分支都以通信开头。
    def __init__(
        self,
        communication: InputChannel | OutputChannel,
        continuation: Process,
        alternative: EventReaction | None = None,
    ):
        """验证通信前缀、其专属后继以及并列的递归事件余项。"""
        if not isinstance(communication, (InputChannel, OutputChannel)):
            raise TypeError("EventChoice prefix must be an input or output action")
        if not isinstance(continuation, Process):
            raise TypeError("EventChoice continuation must be a Process")
        if alternative is not None and not isinstance(alternative, EventReaction):
            raise TypeError("EventChoice alternative must be an EventReaction")
        object.__setattr__(self, "communication", communication)
        object.__setattr__(self, "continuation", continuation)
        object.__setattr__(
            self,
            "alternative",
            EmptyEvent() if alternative is None else alternative,
        )
        _validate_assumption21(self)

    # 功能：合并通信动作、分支后继和其余事件选择中的用户值变量。
    # 检查/论文关系：只收集变量，不检查各分支通道在 Theta 中的声明。
    def get_vars(self) -> set[str]:
        """合并当前事件、后继和其余选择分支的变量。"""
        return set(_assumption21_info(self).value_variables)

    # 功能：递归合并当前分支及剩余分支中的输入绑定变量。
    # 检查/论文关系：结果用于 Gamma 缺失声明豁免和并行变量域计算；每个
    #                分支的局部扩展仍由其实际通信前缀进入 T-In 时完成。
    def get_input_bound_vars(self) -> set[str]:
        """合并当前事件路径和其余分支引入的输入变量。"""
        return set(_assumption21_info(self).bound_value_variables)

    # 功能：把零个或多个事件分支右结合为递归的 EventChoice/EmptyEvent 树。
    # 检查/论文关系：零分支精确得到 E ::= empty；每个非空分支仍由类构造器
    #                执行通信前缀、P continuation、E alternative 和假设检查。
    @classmethod
    def of(
        cls,
        *branches: tuple[InputChannel | OutputChannel, Process],
    ) -> EventReaction:
        """把事件分支表展开成论文的递归事件反应 ``E``。"""

        for branch in branches:
            if not isinstance(branch, tuple) or len(branch) != 2:
                raise TypeError(
                    "EventChoice.of branches must be "
                    "(communication, continuation) tuples"
                )
            communication, continuation = branch
            if not isinstance(communication, (InputChannel, OutputChannel)):
                raise TypeError(
                    "EventChoice.of branch prefixes must be input or output actions"
                )
            if not isinstance(continuation, Process):
                raise TypeError(
                    "EventChoice.of branch continuations must be Process nodes"
                )

        reaction: EventReaction = EmptyEvent()
        for communication, continuation in reversed(branches):
            reaction = cls(communication, continuation, reaction)
        return reaction


# --------------------------------------------------------------------------
# 论文对应：Section 2.1 的二元顺序组合 P ::= P; P'。
# 构造方式：Sequence(first, second)。
# 构造检查：立即要求两个操作数都是 Process，并按 first 的输入作用域计算
#           second 的 fv，随后检查 Assumption 2.1。若 first 是复合进程，项目
#           采用其各分支输入绑定集合的并集来处理公共 second，详见文件头约定。
# --------------------------------------------------------------------------
@dataclass(frozen=True)
class Sequence(Process):
    """论文二元顺序组合 ``P; P'``。"""

    first: Process
    second: Process

    # 功能：保存论文规定的两个顺序操作数，不引入多元 Sequence 节点。
    # 检查/论文关系：左右两项必须属于 P，保持 E、P、S 三个范畴的边界。
    def __init__(self, first: Process, second: Process):
        """要求左右两项都是顺序进程 ``P``。"""
        if not isinstance(first, Process):
            raise TypeError("Sequence first operand must be a Process")
        if not isinstance(second, Process):
            raise TypeError("Sequence second operand must be a Process")
        trailing = first
        while isinstance(trailing, Sequence):
            trailing = trailing.second
        if isinstance(trailing, InternalChoice):
            raise ValueError(
                "InternalChoice owns its common continuation; use "
                "InternalChoice(left, right, continuation) instead of "
                "placing an InternalChoice before a later Sequence continuation"
            )
        object.__setattr__(self, "first", first)
        object.__setattr__(self, "second", second)
        _validate_assumption21(self)

    # 功能：合并前后两个顺序进程使用的用户值变量。
    # 检查/论文关系：集合不表达执行先后；
    #                符号状态更新由类型检查器按顺序处理。
    def get_vars(self) -> set[str]:
        """合并两个顺序项使用的变量。"""
        return set(_assumption21_info(self).value_variables)

    # 功能：合并顺序两侧由输入通信引入的变量。
    # 检查/论文关系：该集合用于 Gamma 声明豁免；真正的作用域捕获由
    #                _sequence_assumption21_info 计算，T-In 再建立具体类型。
    def get_input_bound_vars(self) -> set[str]:
        """合并两个顺序项引入的输入变量。"""
        return set(_assumption21_info(self).bound_value_variables)

    # 功能：把零个或多个书写项右结合为论文的二元 P; P' 树。
    # 检查/论文关系：零项等价于 Skip；非空项必须全是 Process；
    #                方法只组合 cls 节点，不产生多元 Sequence 节点。
    @classmethod
    def of(cls, *items: Process) -> Process:
        """把多个进程右结合展开成二元 ``Sequence`` AST。"""

        if not items:
            return Skip()
        if not all(isinstance(item, Process) for item in items):
            raise TypeError("Sequence.of items must all be Process nodes")
        result: Process = items[-1]
        for item in reversed(items[:-1]):
            result = _append_sequence_continuation(item, result)
        return result

# --------------------------------------------------------------------------
# 论文对应：Section 2.1 中等价的 ``(P \sqcup P'); Q``；Table 2
#           经顺序后继补全的 T-\sqcup。
# 构造方式：InternalChoice(left, right, continuation=Skip())。
# 构造检查：左分支、右分支和公共后继都必须属于 Process，并对完整
#           三元子树检查 Assumption 2.1。二元调用只是 continuation
#           缺省为 Skip() 的构造器形式，AST 对象始终含第三个字段。
# --------------------------------------------------------------------------
@dataclass(frozen=True)
class InternalChoice(Process):
    r"""三元内部选择 ``(P \sqcup P'); Q``。"""

    left: Process
    right: Process
    continuation: Process = field(default_factory=Skip)

    # 功能：验证两个选择分支和它们共享的顺序后继。
    # 检查/论文关系：拒绝 E 和 Parallel；T-\sqcup 将 continuation 同时
    #                交给左右子 judgment，不需要通用 T-Seq。
    def __post_init__(self) -> None:
        """两个分支与公共后继都必须是顺序进程。"""
        if not isinstance(self.left, Process) or not isinstance(self.right, Process):
            raise TypeError("InternalChoice branches must be Process nodes")
        if not isinstance(self.continuation, Process):
            raise TypeError("InternalChoice continuation must be a Process node")
        _validate_assumption21(self)

    # 功能：合并两个非确定分支及公共后继的用户值变量。
    # 检查/论文关系：不选择具体分支；类型检查器会保留两个带同一
    #                continuation 的完整行为类型。
    def get_vars(self) -> set[str]:
        """合并两个选择分支的变量。"""
        return set(_assumption21_info(self).value_variables)

    # 功能：合并两个分支和公共后继中的输入绑定变量。
    # 检查/论文关系：分支输入可捕获 continuation 中的同名变量；此方法只用于
    #                环境收集，不选择实际运行分支。
    def get_input_bound_vars(self) -> set[str]:
        """合并两个选择分支引入的输入变量。"""
        return set(_assumption21_info(self).bound_value_variables)

    # 功能：把一个或多个分支右结合，并把公共 continuation 存入最外层。
    # 检查/论文关系：零分支拒绝；单分支退化为普通顺序组合；多分支的
    #                每一层仍由三字段 cls 构造器执行范畴和 Assumption 2.1 检查。
    @classmethod
    def of(
        cls,
        *branches: Process,
        continuation: Process | None = None,
    ) -> Process:
        """把多个分支右结合，并把公共后继存入最外层三元节点。"""

        if not branches:
            raise ValueError("InternalChoice.of needs at least one branch")
        if not all(isinstance(branch, Process) for branch in branches):
            raise TypeError("InternalChoice.of branches must be Process nodes")
        common_tail = Skip() if continuation is None else continuation
        if not isinstance(common_tail, Process):
            raise TypeError("InternalChoice.of continuation must be a Process node")
        if len(branches) == 1:
            return (
                branches[0]
                if isinstance(common_tail, Skip)
                else Sequence.of(branches[0], common_tail)
            )
        result: Process = branches[-1]
        for branch in reversed(branches[:-1]):
            result = cls(branch, result)
        if not isinstance(result, InternalChoice):
            raise AssertionError("multiple branches must produce InternalChoice")
        return cls(result.left, result.right, common_tail)


# 功能：把一个顺序后继追加到已有进程，同时保持内部选择三元规范形。
# 检查/论文关系：普通顺序树按结合律向右追加；若执行前缀最后是
#                InternalChoice，后继必须进入其 continuation 字段，不产生旧嵌套形状。
def _append_sequence_continuation(
    prefix: Process,
    continuation: Process,
) -> Process:
    """为 ``Sequence.of`` 生成不含外置选择后继的唯一规范 AST。"""

    if isinstance(prefix, InternalChoice):
        combined = (
            continuation
            if isinstance(prefix.continuation, Skip)
            else _append_sequence_continuation(
                prefix.continuation,
                continuation,
            )
        )
        return InternalChoice(prefix.left, prefix.right, combined)
    if isinstance(prefix, Sequence):
        return Sequence(
            prefix.first,
            _append_sequence_continuation(prefix.second, continuation),
        )
    return Sequence(prefix, continuation)


# ────────────────── ODE 批注、局部时钟与 wait ──────────────────────────────

# 每个 ODE 的自动时钟在 ODE 公式范围内使用这个固定源级名称。它不是用户状态
# 变量声明：变量分析会把该名称从方程右端、演化域和 safety 的自由变量中消去，
# dL 翻译则为每个 ODE 分配彼此不同的内部逻辑符号。
ODE_LOCAL_CLOCK_NAME = "t"

# 功能：把 ODE 方程向量统一为不可变的 (变量名, Expr) 元组。
# 检查/论文关系：构造期验证每项形状、左端词法和右端表达式语法，并拒绝把
#                保留名 t 再写成方程左端；同一用户变量是否重复求导以及
#                变量/导数的 Real 类型留给 T-ODE 检查。
def _normalize_equations(
    equations: Iterable[tuple[str, ExprLike]],
) -> tuple[tuple[str, Expr], ...]:
    """验证并规范化 ODE 方程向量。"""

    try:
        iterator = iter(equations)
    except TypeError as exc:
        raise TypeError(
            "ODE equations must be an iterable of (variable, derivative) tuples"
        ) from exc

    normalized: list[tuple[str, Expr]] = []
    for index, equation in enumerate(iterator):
        if not isinstance(equation, tuple) or len(equation) != 2:
            raise TypeError(
                f"ODE equation {index} must be a "
                "(variable, derivative) tuple"
            )
        variable, derivative = equation
        if not isinstance(variable, str) or not variable.isidentifier():
            raise ValueError(f"Invalid ODE variable: {variable!r}")
        if variable == ODE_LOCAL_CLOCK_NAME:
            raise ValueError(
                "ODE variable 't' is reserved for the automatic local clock; "
                "its equation t'=1 is added automatically"
            )
        normalized.append((variable, ensure_expr(derivative)))
    return tuple(normalized)


# 功能：精确求值 ODE 外部时延批注中的无变量有理常量表达式。
# 检查/论文关系：实现 Remark 4.1 的外部常量 d；
#                拒绝变量、函数、Bool 和非有理形式。
def _evaluate_rational_constant(expression: Expr) -> Fraction:
    """把无变量的有理常量表达式精确计算为 :class:`Fraction`。

    ODE 的 delay 是模型批注，不是运行期状态表达式。这里仅接受数值字面量以及
    由 ``+ - * / **`` 构成、结果仍为有理数的常量表达式；变量、函数调用、
    布尔值和其他表达式节点都会在 AST 构造边界被拒绝。
    """

    if isinstance(expression, Literal):
        value = expression.value
        if isinstance(value, bool):
            raise ValueError("ODE delay must be a rational number, not Boolean")
        if isinstance(value, int):
            return Fraction(value)
        if isinstance(value, Fraction):
            return value
        if isinstance(value, Decimal):
            if value.is_nan() or value.is_infinite():
                raise ValueError("ODE finite delay must be a rational number")
            return Fraction(value)
        if isinstance(value, float):
            if isnan(value) or isinf(value):
                raise ValueError("ODE finite delay must be a rational number")
            # 采用用户可见的十进制文本，而不是暴露二进制浮点的巨大分母。
            return Fraction(str(value))
        raise ValueError("ODE delay must be a numeric rational constant")

    if isinstance(expression, UnaryExpr) and expression.op in {"+", "-"}:
        operand = _evaluate_rational_constant(expression.operand)
        return operand if expression.op == "+" else -operand

    if isinstance(expression, BinaryExpr):
        left = _evaluate_rational_constant(expression.left)
        right = _evaluate_rational_constant(expression.right)
        try:
            if expression.op == "+":
                return left + right
            if expression.op == "-":
                return left - right
            if expression.op == "*":
                return left * right
            if expression.op == "/":
                return left / right
            if expression.op == "**":
                if right.denominator != 1:
                    raise ValueError(
                        "ODE delay exponent must be an integer"
                    )
                return left ** right.numerator
        except ZeroDivisionError as exc:
            raise ValueError(
                "ODE delay constant expression divides by zero"
            ) from exc

    raise ValueError(
        "ODE delay must be a constant rational expression or positive infinity"
    )


# 功能：把每个 ODE 的必填时延规范化为精确非负 Fraction 或正无穷。
# 检查/论文关系：对应类型中的 0<=d<=infinity 及 Remark 4.1；
#                项目用有理数精确表示有限 d。
def _normalize_ode_delay(delay: ExprLike | None) -> Literal | float:
    """验证必填 delay，并规范化为非负有理数字面量或 ``math.inf``。"""

    if delay is None:
        raise ValueError(
            "ODE annotation requires an explicit delay: "
            "a non-negative rational number or positive infinity"
        )

    expression = ensure_expr(delay)
    if isinstance(expression, Literal):
        value = expression.value
        if isinstance(value, float) and isinf(value):
            if value > 0:
                return inf
            raise ValueError("ODE delay cannot be negative infinity")
        if isinstance(value, Decimal) and value.is_infinite():
            if value > 0:
                return inf
            raise ValueError("ODE delay cannot be negative infinity")

    rational = _evaluate_rational_constant(expression)
    if rational < 0:
        raise ValueError("ODE delay must be non-negative")
    # 所有有限时延均以精确有理数字面量保存；
    # Fraction(3, 1) 的显示仍为 3。
    return Literal(rational)


# --------------------------------------------------------------------------
# 论文对应：Section 4.3 为 ODE 附加安全性质 phi；Remark 4.1 说明规则
#           Table 2 两条 T-\unrhd 规则使用的精确演化时间 d 由外部提供。
# 构造方式：项目用 ODEAnnotation(safety=phi, delay=d) 统一承载两者；
#           delay 必填，phi 省略时按论文解释为 true。
# 构造检查：立即解析 phi，并要求 d 是非负有理常量或正无穷；phi 的 Bool
#           类型及沿 ODE 的不变性由 T-ODE 和后续 dL 义务检查。
# --------------------------------------------------------------------------
@dataclass(frozen=True)
class ODEAnnotation:
    """连续演化的安全性质 ``phi`` 与外部精确时长 ``d``。

    ``safety`` 是要求在整个演化期间（包括中断瞬间）成立的一阶公式。论文规定
    省略 ``phi`` 等价于 ``true``，所以本字段默认规范化为 ``Literal(True)``。

    ``delay`` 对应 Remark 4.1 中由模型外部提供的精确时长 ``d``。本项目要求
    每个 ODE 都显式提供它；有限值必须是可静态计算的非负有理常量，并统一保存
    为 ``Literal(Fraction(...))``。正无穷表示没有有限超时边界；缺失、符号
    时延、负值、NaN 和负无穷均在构造时拒绝。
    """

    safety: Expr
    delay: Literal | float

    # 功能：规范化安全公式并调用统一的时延边界检查。
    # 检查/论文关系：实现省略 phi 等于 true；不允许省略项目要求的 d。
    def __init__(
        self,
        *,
        safety: ExprLike = True,
        delay: ExprLike | None = None,
    ):
        """规范化安全公式，并严格验证必填的有理数/正无穷时延。"""
        object.__setattr__(self, "safety", ensure_expr(safety))
        object.__setattr__(self, "delay", _normalize_ode_delay(delay))

    # 功能：返回安全性质 phi 的语法变量名；合法 d 按定义不含变量。
    # 检查/论文关系：批注对象本身尚不知道所属 ODE，故会如实返回 t；附着到
    #                ODE 后，节点级变量分析再把局部时钟 t 从 Gamma/fv/V 中消去。
    def get_vars(self) -> set[str]:
        """返回安全公式的语法变量名；合法 delay 按定义不含变量。"""
        return set(self.safety.get_vars())


# --------------------------------------------------------------------------
# 论文对应：Table 2 的有限时延 ODE 前提引入新鲜时钟 t，入口满足 t=0，
#           并与原连续方程一起满足 dot(t)=1。
# 构造方式：项目为统一 ODE 结构，使每次 ODE(...) 构造都自动建立独立实例；
#           该对象直到生成 dL 义务时才实体化为一个新鲜 Real 符号。
# 构造检查：名称、初值和导数固定为 t、精确的 0 和 1，不接受自定义值；
#           t 只绑定本 ODE 的方程右端、演化域和 safety，不进入源 HCSP 的
#           Gamma、fv、bv、get_vars() 或 V。
# --------------------------------------------------------------------------
@dataclass(frozen=True, eq=False)
class ODELocalClock:
    """每个 ODE 自动拥有、可在其公式中通过 ``t`` 读取的局部计时器。"""

    name: str = field(default=ODE_LOCAL_CLOCK_NAME, init=False)

    initial_value: Literal = field(
        default_factory=lambda: Literal(Fraction(0)),
        init=False,
    )
    derivative: Literal = field(
        default_factory=lambda: Literal(Fraction(1)),
        init=False,
    )


# --------------------------------------------------------------------------
# 论文对应：Section 2.1 的连续演化
#           <dot(v)=e & B> \unrhd E；Section 4.3 附加安全性质 phi，
#           Remark 4.1 提供类型规则需要的外部精确时长 d。
# 构造方式：ODE(eqs, B, E, annotation=ODEAnnotation(...))。
# 构造检查：立即规范化方程和 B，要求中断属于 E 且批注存在、类型正确；
#           自动建立名为 t、初值 0、导数 1 的局部时钟，并禁止用户方程覆盖它；
#           普通 ODE 的隐藏截止边界为 None，仅 ODE.wait(d) 使用的私有工厂
#           在初始化节点时把它设为有限 d，两个隐藏字段都不是用户参数；
#           同时检查连续状态/公式的 fv 与事件输入 bv 不交；Real 类型、
#           重复导数、B/phi 的 Bool 类型和 dL 义务由 T-ODE 检查。
# --------------------------------------------------------------------------
@dataclass(frozen=True)
class ODE(Process):
    r"""带批注连续演化 ``<dot(v)=e & B>_phi \unrhd[d] E``。"""

    eqs: tuple[tuple[str, Expr], ...]
    constraint: Expr
    interrupts: EventReaction
    annotation: ODEAnnotation
    # 局部时钟按对象身份保持新鲜，但不参与 ODE 的源语法结构相等性；否则两个
    # 文字完全相同的 ODE 会仅因内部行政变量不同而比较为不等。
    local_clock: ODELocalClock = field(compare=False, init=False)
    # 普通 ODE 没有内部截止边界；ODE.wait(d) 把这里设为规范化后的有限 d。
    # 该字段影响演化语义和结构相等性，但不接受 ODE(...) 调用方直接传入。
    local_clock_deadline: Literal | None = field(default=None, init=False)

    # 功能：把原始 ODE 产生式、唯一批注对象和自动局部时钟组合为不可变节点。
    # 检查/论文关系：缺省中断规范化为 empty；项目要求包含外部 d 的批注对象；
    #                local_clock/local_clock_deadline 不开放构造参数，
    #                避免用户伪造时钟的初值、速率、保留名或演化截止边界。
    def __init__(
        self,
        eqs: Iterable[tuple[str, ExprLike]],
        constraint: ExprLike,
        interrupts: EventReaction | None = None,
        *,
        annotation: ODEAnnotation | None = None,
    ):
        """规范化原始 ODE，并附加安全性质/外部时长批注与自动局部时钟。"""

        self._initialize(
            eqs,
            constraint,
            interrupts,
            annotation,
            local_clock_deadline=None,
        )

    # 功能：以单一原子路径写入 ODE 全部字段，再执行构造期检查。
    # 检查/论文关系：普通入口传 None；ODE.wait(d) 的私有工厂传有限 d，
    #                避免对已经构造完毕的冻结 AST 再做二次修改。
    def _initialize(
        self,
        eqs: Iterable[tuple[str, ExprLike]],
        constraint: ExprLike,
        interrupts: EventReaction | None,
        annotation: ODEAnnotation | None,
        *,
        local_clock_deadline: Literal | None,
    ) -> None:
        """原子初始化普通 ODE 或 ``ODE.wait(d)`` 的内部 ODE。"""

        if interrupts is not None and not isinstance(interrupts, EventReaction):
            raise TypeError("ODE interrupts must be an EventReaction")
        if annotation is None:
            raise ValueError(
                "Every ODE requires ODEAnnotation with an explicit delay"
            )
        if not isinstance(annotation, ODEAnnotation):
            raise TypeError("ODE annotation must be an ODEAnnotation")
        if local_clock_deadline is not None:
            if not isinstance(local_clock_deadline, Literal):
                raise TypeError("ODE local-clock deadline must be a Literal")
            if local_clock_deadline != annotation.delay:
                raise ValueError(
                    "ODE local-clock deadline must equal its finite delay"
                )
        object.__setattr__(self, "eqs", _normalize_equations(eqs))
        object.__setattr__(self, "constraint", ensure_expr(constraint))
        object.__setattr__(
            self,
            "interrupts",
            EmptyEvent() if interrupts is None else interrupts,
        )
        object.__setattr__(
            self,
            "annotation",
            annotation,
        )
        object.__setattr__(self, "local_clock", ODELocalClock())
        object.__setattr__(
            self,
            "local_clock_deadline",
            local_clock_deadline,
        )
        _validate_assumption21(self)

    # 功能：为 ODE.wait(d) 一次性构造带隐藏截止边界的 ODE。
    # 检查/论文关系：复用 ODEAnnotation 的精确有理数检查，并额外
    #                拒绝普通 ODE 可接受、但 ODE.wait(d) 不接受的正无穷。
    @classmethod
    def _for_wait(cls, duration: ExprLike) -> "ODE":
        """构造 ``ODE.wait(d)`` 展开中的有限截止 ODE。"""

        annotation = ODEAnnotation(safety=True, delay=duration)
        if not isinstance(annotation.delay, Literal):
            raise ValueError(
                "wait duration must be a finite non-negative rational number"
            )
        evolution = object.__new__(cls)
        evolution._initialize(
            (),
            True,
            None,
            annotation,
            local_clock_deadline=annotation.delay,
        )
        return evolution

    # 功能：把源级 ``wait(d)`` 展开为带隐藏截止时钟的 ODE; Skip。
    # 检查/论文关系：Section 2.1 使用严格演化域 ``t<d``；d 必须是
    #                有限非负有理数，返回值仍是规范二元 Sequence，不引入
    #                Wait 节点。
    @classmethod
    def wait(cls, duration: ExprLike) -> Sequence:
        """构造源级 ``wait(d)`` 的规范核心 AST 展开。"""

        return Sequence(cls._for_wait(duration), Skip())

    # 功能：收集演化左端、导数、演化域、批注和中断分支的用户值变量。
    # 检查/论文关系：为 Gamma 和 dL 声明提供源变量域；隐藏 local_clock 具有
    #                独立局部作用域，刻意不进入返回集合。
    def get_vars(self) -> set[str]:
        """收集方程、演化域、安全批注和事件反应中的用户值变量。"""
        return set(_assumption21_info(self).value_variables)

    # 功能：返回 ODE 外部事件选择中由多标量输入绑定的全部变量。
    # 检查/论文关系：连续方程本身不绑定输入变量，只有中断 E 的 T-In 会绑定。
    def get_input_bound_vars(self) -> set[str]:
        """返回 ODE 事件反应引入的输入变量。"""
        return set(_assumption21_info(self).bound_value_variables)


# ────────────────── 递归批注与 Assumption 2.2 ──────────────────────────────

# --------------------------------------------------------------------------
# 论文对应：Section 4.3 给递归变量 X_phi 配置的边界不变量 phi。
# 构造方式：RecursionAnnotation(phi)；省略 phi 时按论文解释为 true。
# 构造检查：立即解析 phi；
#           Bool 类型及每次展开入口/出口成立性由 T-\mu/T-X 检查。
# --------------------------------------------------------------------------
@dataclass(frozen=True)
class RecursionAnnotation:
    """Section 4.3 进程变量 ``X`` 的边界不变量批注。"""

    invariant: Expr

    # 功能：把递归边界不变量规范化为严格 Expr。
    # 检查/论文关系：实现省略批注等于 true，不在 AST 阶段证明不变量。
    def __init__(self, invariant: ExprLike = True):
        """省略不变量时按论文约定规范化为恒真公式。"""
        object.__setattr__(self, "invariant", ensure_expr(invariant))

    # 功能：返回边界不变量 phi 中出现的用户值变量。
    # 检查/论文关系：这些变量参与 Gamma 和 FOL 义务，不包含进程变量 X。
    def get_vars(self) -> set[str]:
        """返回边界不变量中出现的用户值变量。"""
        return self.invariant.get_vars()


# --------------------------------------------------------------------------
# 论文对应：Section 2.1 的 P ::= mu X.P，以及 Section 4.3 的 X_phi 批注；
#           Table 2 的 T-\mu/T-X 和 Assumption 2.2。
# 构造方式：Mu("X", body, annotation=RecursionAnnotation(phi))。
# 构造检查：立即验证 X、body 和批注类别；省略批注规范化为 true；
#           把 body 中的 X 转为绑定进程变量并检查 Assumption 2.1，
#           同时要求每个受绑定 X 的回边均经过输入或输出通信；
#           尾位置和边界不变量仍由 T-\mu/T-X 检查。
# --------------------------------------------------------------------------
@dataclass(frozen=True)
class Mu(Process):
    """带边界不变量的递归进程 ``mu X_phi.P``。"""

    variable: str
    body: Process
    annotation: RecursionAnnotation

    # 功能：绑定一个进程变量，并把边界不变量附着到唯一的 mu 节点。
    # 检查/论文关系：body 必须是 P，且所有受本节点绑定的 X 回边必须通信保护。
    def __init__(
        self,
        variable: str,
        body: Process,
        *,
        annotation: RecursionAnnotation | None = None,
    ):
        """绑定进程变量，并附加唯一的 Section 4.3 递归批注对象。"""
        if not isinstance(variable, str) or not variable.isidentifier():
            raise ValueError(f"Invalid recursive variable: {variable!r}")
        if not isinstance(body, Process):
            raise TypeError("Mu body must be a Process")
        if annotation is not None and not isinstance(annotation, RecursionAnnotation):
            raise TypeError("Mu annotation must be a RecursionAnnotation")
        _validate_assumption22(variable, body)
        object.__setattr__(self, "variable", variable)
        object.__setattr__(self, "body", body)
        object.__setattr__(
            self,
            "annotation",
            RecursionAnnotation() if annotation is None else annotation,
        )
        _validate_assumption21(self)

    # 功能：合并递归体与边界不变量使用的用户值变量。
    # 检查/论文关系：不把绑定的进程变量 X 当成 Gamma 中的值变量。
    def get_vars(self) -> set[str]:
        """合并递归体与边界不变量中的用户值变量。"""
        return set(_assumption21_info(self).value_variables)

    # 功能：返回递归体各通信路径引入的输入绑定变量。
    # 检查/论文关系：构造时已独立验证每条递归回边的通信保护；此方法只汇总
    #                可由 T-In 新引入、因而无需预先出现在 Gamma 的目标变量。
    def get_input_bound_vars(self) -> set[str]:
        """返回递归体引入的输入变量。"""
        return set(_assumption21_info(self).bound_value_variables)


# 功能：沿 AST 路径递归传播“在到达当前位置前是否已经通信”的状态。
# 检查/论文关系：Assumption 2.2 要求从绑定 mu X 到每个叶子 X 的语法树路径
#                至少经过一次输入/输出通信；状态集合保留分支汇合前的所有可能值。
def _assumption22_exit_states(
    node: Process,
    variable: str | None,
    guarded: bool,
    location: str,
) -> frozenset[bool]:
    """验证目标递归变量，并返回进程正常出口处可能的通信状态。

    ``variable`` 是当前正在检查的外层绑定名；进入同名内层 ``Mu`` 后使用
    ``None`` 表示该外层绑定已被遮蔽。``guarded`` 是当前路径的入口状态。
    返回集合中的每个布尔值对应一类正常结束路径，供 ``Sequence`` 的后继
    继续检查；ODE 事件中断 continuation 是独立路径，不计入自然结束集合。
    """

    if isinstance(node, Var):
        # 只有与当前绑定同名的叶子才是本次 Assumption 2.2 所检查的回边。
        if variable is not None and node.name == variable and not guarded:
            raise ValueError(
                "Assumption 2.2 violated: recursion "
                f"{variable!r} is not communication-guarded at {location}; "
                "every bound occurrence must be preceded by input or output communication"
            )
        return frozenset({guarded})

    if isinstance(node, (Skip, Assign, Assert)):
        # 这些内部动作不构成通信，也不改变入口保护状态。
        return frozenset({guarded})

    if isinstance(node, (InputChannel, OutputChannel)):
        # 任一输入或输出动作都会保护同一路径上后续出现的目标回边。
        return frozenset({True})

    if isinstance(node, If):
        # 两个分支从相同入口状态出发；并集保留各自可能的出口状态。
        then_states = _assumption22_exit_states(
            node.then_branch,
            variable,
            guarded,
            f"{location}.then",
        )
        else_states = _assumption22_exit_states(
            node.else_branch,
            variable,
            guarded,
            f"{location}.else",
        )
        return then_states | else_states

    if isinstance(node, Sequence):
        # first 的每种正常出口状态都必须分别传入公共 second；因此只要存在
        # 未通信出口，second 中的目标回边仍会在 guarded=False 下被检查。
        first_states = _assumption22_exit_states(
            node.first,
            variable,
            guarded,
            f"{location}.first",
        )
        result: set[bool] = set()
        for state in sorted(first_states):
            result.update(
                _assumption22_exit_states(
                    node.second,
                    variable,
                    state,
                    f"{location}.second",
                )
            )
        return frozenset(result)

    if isinstance(node, InternalChoice):
        # 内部选择的一个分支不能借用另一个分支的通信；左右分支
        # 的每种出口状态都必须分别传入同一个 continuation。
        left_states = _assumption22_exit_states(
            node.left,
            variable,
            guarded,
            f"{location}.left",
        )
        right_states = _assumption22_exit_states(
            node.right,
            variable,
            guarded,
            f"{location}.right",
        )
        result: set[bool] = set()
        for state in sorted(left_states | right_states):
            result.update(
                _assumption22_exit_states(
                    node.continuation,
                    variable,
                    state,
                    f"{location}.continuation",
                )
            )
        return frozenset(result)

    if isinstance(node, ODE):
        # 每个事件 continuation 先由自己的事件通信保护；ODE 自然结束则不
        # 发生通信，所以外层顺序后继只能继承 ODE 的入口状态。
        _validate_assumption22_event(
            node.interrupts,
            variable,
            guarded,
            f"{location}.interrupts",
        )
        return frozenset({guarded})

    if isinstance(node, Mu):
        # 同名内层 mu 遮蔽外层目标；不同名内层 mu 不遮蔽，仍检查其中的
        # 外层变量引用。无论哪种情况，body 的出口状态都传回外部后继。
        nested_variable = None if node.variable == variable else variable
        return _assumption22_exit_states(
            node.body,
            nested_variable,
            guarded,
            f"{location}.mu[{node.variable}].body",
        )

    raise TypeError(
        "Assumption 2.2 analysis received an unsupported Process node: "
        f"{type(node).__name__}"
    )


# 功能：递归检查 ODE 事件反应中由通信前缀引出的 continuation。
# 检查/论文关系：EventChoice 的多标量输入/输出前缀本身满足一次通信；
#                alternative 是并列事件分支，只保留 ODE 入口原有状态，
#                不能继承前一事件分支的通信。
def _validate_assumption22_event(
    reaction: EventReaction,
    variable: str | None,
    guarded: bool,
    location: str,
) -> None:
    """验证每个 ODE 事件分支，不把事件出口混入 ODE 的自然结束路径。

    当前分支的 continuation 固定以 ``True`` 开始，因为其通信前缀已经发生；
    递归检查 alternative 时继续传入原 ``guarded``，避免不同事件分支之间共享
    保护状态。
    """

    if isinstance(reaction, EmptyEvent):
        return
    if isinstance(reaction, EventChoice):
        _assumption22_exit_states(
            reaction.continuation,
            variable,
            True,
            f"{location}.continuation",
        )
        _validate_assumption22_event(
            reaction.alternative,
            variable,
            guarded,
            f"{location}.alternative",
        )
        return
    raise TypeError(
        "Assumption 2.2 analysis received an unsupported EventReaction: "
        f"{type(reaction).__name__}"
    )


# 功能：作为 Mu 构造器的单一入口，检查该绑定对应的全部递归回边。
# 检查/论文关系：从未通信状态开始分析 body；没有 X 出现时条件真空成立。
def _validate_assumption22(variable: str, body: Process) -> None:
    """从未通信状态进入递归体，验证绑定 ``variable`` 的全部叶子出现。"""

    _assumption22_exit_states(body, variable, False, "body")


# ────────────────── 并行系统与 Assumption 2.1 ──────────────────────────────

# --------------------------------------------------------------------------
# 论文对应：Section 2.1 的系统组合 S ::= S \parallel S'；
#           Table 2 的 T-\parallel 和 Assumption 2.1。
# 构造方式：Parallel(left_system, right_system)。
# 构造检查：立即要求左右均属于 HCSP，先检查完整系统的 fv 与 bv 不相交，
#           再检查两个分量的 V、iCh 和 oCh 分别不相交；
#           一入一出的互补通道仍可用于同步。
# --------------------------------------------------------------------------
@dataclass(frozen=True)
class Parallel(HCSP):
    """二元系统组合 ``S || S'``。"""

    left: HCSP
    right: HCSP

    # 功能：验证二元并行两侧的语法范畴及变量、同向通道资源分离。
    # 检查/论文关系：构造时执行 fv/bv、V、iCh、oCh 全部 Assumption 2.1 条件。
    def __post_init__(self) -> None:
        """两个并行项都必须是系统 ``S``。"""
        if not isinstance(self.left, HCSP) or not isinstance(self.right, HCSP):
            raise TypeError("Parallel operands must be HCSP systems")
        _validate_assumption21(self)

    # 功能：返回已经通过构造期分离检查的两个分量用户值变量并集。
    # 检查/论文关系：类型检查器用该集合投影/核对分量 Gamma；进程变量分离
    #                已由构造期的内部摘要检查，不混入此公开值变量接口。
    def get_vars(self) -> set[str]:
        """合并两个并行系统使用的用户值变量。"""
        return set(_assumption21_info(self).value_variables)

    # 功能：合并各并行分量中的输入绑定变量。
    # 检查/论文关系：用于 Gamma 缺失声明豁免；Parallel 构造期仍禁止两个
    #                分量共享该目标名，因此此并集不表示允许共享状态。
    def get_input_bound_vars(self) -> set[str]:
        """合并两个并行系统引入的输入变量。"""
        return set(_assumption21_info(self).bound_value_variables)

    # 功能：把两个或更多系统右结合展开为论文的二元 Parallel 树。
    # 检查/论文关系：每层均由 cls 构造器检查 S 范畴、fv/bv 和资源分离；
    #                方法不引入多元并行节点。
    @classmethod
    def of(cls, *systems: HCSP) -> HCSP:
        """把多个系统右结合展开成二元 ``Parallel`` AST。"""

        if len(systems) < 2:
            raise ValueError("Parallel.of needs at least two systems")
        if not all(isinstance(system, HCSP) for system in systems):
            raise TypeError("Parallel.of items must all be HCSP systems")
        result: HCSP = systems[-1]
        for system in reversed(systems[:-1]):
            result = cls(system, result)
        return result


# --------------------------------------------------------------------------
# 论文对应：Assumption 2.1 中 fv、bv、V=fv\uplus bv、iCh 和 oCh。
# 构造方式：仅由内部分析函数生成，不属于 HCSP 的 E/P/S 节点。
# 构造检查：论文的 fv/bv 在实现中按值变量与进程变量两个命名空间拆开保存，
#           因而共有六个存储字段；本对象只保存集合，冲突统一由验证函数报告。
# --------------------------------------------------------------------------
@dataclass(frozen=True)
class _Assumption21Info:
    """一个 HCSP 子树的 Assumption 2.1 静态集合摘要。

    ``free/bound_value_variables`` 保存 Gamma 中具有标量值的状态变量（包括 ODE
    分量）；
    ``free/bound_process_variables`` 保存 ``Var``/``Mu`` 名称。两类变量不会互相
    冲突，但在各自命名空间内都必须满足 ``fv ∩ bv = empty``，并分别参与并行
    分量的 V 分离检查。最后两个字段直接对应论文的 ``iCh`` 与 ``oCh``。
    """

    free_value_variables: frozenset[str] = frozenset()
    bound_value_variables: frozenset[str] = frozenset()
    free_process_variables: frozenset[str] = frozenset()
    bound_process_variables: frozenset[str] = frozenset()
    input_channels: frozenset[str] = frozenset()
    output_channels: frozenset[str] = frozenset()

    # 功能：在值变量命名空间内计算 V_value=fv_value∪bv_value。
    # 检查/论文关系：输入目标也属于系统状态域，供 Gamma 投影和 Parallel
    #                的值变量分量不相交检查使用。
    @property
    def value_variables(self) -> frozenset[str]:
        """返回自由与绑定值变量的并集。"""

        return self.free_value_variables | self.bound_value_variables

    # 功能：在进程变量命名空间内计算 V_process=fv_process∪bv_process。
    # 检查/论文关系：Mu 绑定名和自由 Var 名都参与 Parallel 的名称分离检查，
    #                但它们不进入返回用户状态变量的 get_vars/Gamma。
    @property
    def process_variables(self) -> frozenset[str]:
        """返回自由与绑定进程变量的并集。"""

        return self.free_process_variables | self.bound_process_variables


# 功能：逐字段取并集，合并不形成“前项绑定后项”关系的静态摘要。
# 检查/论文关系：用于 If、内部选择、并行以及事件 alternatives。选择分支的
#                bound 集合也会合并，从而落实项目约定的复合前缀公共后继作用域；
#                跨分支的自由/绑定重名随后仍会由 _validate_assumption21 拒绝。
def _merge_assumption21_info(
    *items: _Assumption21Info,
) -> _Assumption21Info:
    """逐字段并集合并若干彼此并列的 Assumption 2.1 摘要。"""

    return _Assumption21Info(
        free_value_variables=frozenset().union(
            *(item.free_value_variables for item in items)
        ),
        bound_value_variables=frozenset().union(
            *(item.bound_value_variables for item in items)
        ),
        free_process_variables=frozenset().union(
            *(item.free_process_variables for item in items)
        ),
        bound_process_variables=frozenset().union(
            *(item.bound_process_variables for item in items)
        ),
        input_channels=frozenset().union(
            *(item.input_channels for item in items)
        ),
        output_channels=frozenset().union(
            *(item.output_channels for item in items)
        ),
    )


# 功能：按输入前缀的作用域连接两个顺序片段的 fv/bv 信息。
# 检查/论文关系：first 的 bound_value_variables 中每个 x 都捕获 second 中的
#                自由 x，所以计算 fv_second - bv_first；这也明确实现了复合
#                first 的分支输入可绑定公共 second 的项目约定。mu X 的作用域
#                仅限其 body，故进程变量集合只取并集，不跨分号捕获。
def _sequence_assumption21_info(
    first: _Assumption21Info,
    second: _Assumption21Info,
) -> _Assumption21Info:
    """计算 ``first; second`` 中输入绑定对公共后继自由值变量的捕获。"""

    return _Assumption21Info(
        free_value_variables=(
            first.free_value_variables
            | (second.free_value_variables - first.bound_value_variables)
        ),
        bound_value_variables=(
            first.bound_value_variables | second.bound_value_variables
        ),
        free_process_variables=(
            first.free_process_variables | second.free_process_variables
        ),
        bound_process_variables=(
            first.bound_process_variables | second.bound_process_variables
        ),
        input_channels=first.input_channels | second.input_channels,
        output_channels=first.output_channels | second.output_channels,
    )


# 功能：按各产生式递归计算 fv、bv、iCh 和 oCh。
# 检查/论文关系：ch?(x1,...,xn) 绑定全部输入目标；mu X.P 是进程变量绑定；
#                赋值目标和 ODE 连续状态是用户状态域中的自由值变量；ODE
#                公式中的 t 由该 ODE 的自动局部时钟绑定，不进入任何集合。
def _assumption21_info(
    node: HCSP | EventReaction,
) -> _Assumption21Info:
    """严格按 E/P/S 产生式递归计算一个子树的 Assumption 2.1 摘要。"""

    if isinstance(node, Var):
        # 裸 X 在遇到所属 Mu 前是自由进程变量；Mu 分支会按名称消去它。
        return _Assumption21Info(
            free_process_variables=frozenset({node.name}),
        )
    if isinstance(node, Skip):
        return _Assumption21Info()
    if isinstance(node, Assign):
        # 赋值不是本项目 fv/bv 意义下的绑定器；左值和右值变量都属于用户状态域。
        return _Assumption21Info(
            free_value_variables=(
                frozenset({node.target.name})
                | frozenset(node.expression.get_vars())
            ),
        )
    if isinstance(node, Assert):
        return _Assumption21Info(
            free_value_variables=frozenset(node.condition.get_vars()),
        )
    if isinstance(node, InputChannel):
        # 一次多标量输入绑定全部目标，同时把 ch 记入输入通道集合。
        return _Assumption21Info(
            bound_value_variables=frozenset(
                target.name for target in node.targets
            ),
            input_channels=frozenset({node.channel.name}),
        )
    if isinstance(node, OutputChannel):
        return _Assumption21Info(
            free_value_variables=frozenset(node.get_vars()),
            output_channels=frozenset({node.channel.name}),
        )
    if isinstance(node, If):
        # B 只贡献自由值变量；两个并列分支逐字段合并。
        condition = _Assumption21Info(
            free_value_variables=frozenset(node.condition.get_vars()),
        )
        return _merge_assumption21_info(
            condition,
            _assumption21_info(node.then_branch),
            _assumption21_info(node.else_branch),
        )
    if isinstance(node, EmptyEvent):
        return _Assumption21Info()
    if isinstance(node, EventChoice):
        # 输入事件前缀只顺序绑定本分支 continuation；alternative 与该分支
        # 并列合并，因此不能被当前通信前缀捕获。
        branch = _sequence_assumption21_info(
            _assumption21_info(node.communication),
            _assumption21_info(node.continuation),
        )
        return _merge_assumption21_info(
            branch,
            _assumption21_info(node.alternative),
        )
    if isinstance(node, Sequence):
        # 只有顺序产生式需要执行前项输入对后项自由值变量的捕获。
        return _sequence_assumption21_info(
            _assumption21_info(node.first),
            _assumption21_info(node.second),
        )
    if isinstance(node, InternalChoice):
        # 左右分支先并列合并，之后作为一个复合顺序前缀绑定公共
        # continuation；这与原 ``Sequence(InternalChoice(...), Q)`` 形状一致。
        branches = _merge_assumption21_info(
            _assumption21_info(node.left),
            _assumption21_info(node.right),
        )
        return _sequence_assumption21_info(
            branches,
            _assumption21_info(node.continuation),
        )
    if isinstance(node, ODE):
        # 方程右端、演化域和 safety 中的 t 由本 ODE 的 local_clock 绑定；
        # 它既不属于用户 fv/bv，也不参与并行分区 V。事件分支不在这个局部
        # 作用域内，故其中独立出现的 t 仍由事件子树按普通用户变量统计。
        free_value_variables = set(node.constraint.get_vars())
        free_value_variables.update(node.annotation.safety.get_vars())
        for variable, derivative in node.eqs:
            free_value_variables.add(variable)
            free_value_variables.update(derivative.get_vars())
        free_value_variables.discard(node.local_clock.name)
        continuous = _Assumption21Info(
            free_value_variables=frozenset(free_value_variables),
        )
        return _merge_assumption21_info(
            continuous,
            _assumption21_info(node.interrupts),
        )
    if isinstance(node, Mu):
        # 仅从 body 的自由进程变量中消去本次绑定名；边界不变量中的名称都是
        # 值变量，不受进程变量 X 的词法绑定影响。
        body = _assumption21_info(node.body)
        return _Assumption21Info(
            free_value_variables=(
                body.free_value_variables
                | frozenset(node.annotation.invariant.get_vars())
            ),
            bound_value_variables=body.bound_value_variables,
            free_process_variables=(
                body.free_process_variables - {node.variable}
            ),
            bound_process_variables=(
                body.bound_process_variables | {node.variable}
            ),
            input_channels=body.input_channels,
            output_channels=body.output_channels,
        )
    if isinstance(node, Parallel):
        # 此处先汇总整棵系统；左右分量之间的资源冲突由验证函数单独比较。
        return _merge_assumption21_info(
            _assumption21_info(node.left),
            _assumption21_info(node.right),
        )
    raise TypeError(
        "Assumption 2.1 analysis received an unsupported AST node: "
        f"{type(node).__name__}"
    )


# 功能：先检查整棵子树的 fv/bv，再对 Parallel 额外比较左右资源集合。
# 检查/论文关系：第一阶段分别验证值变量和进程变量的 Barendregt 条件；
#                第二阶段验证左右 V_value、V_process、iCh、oCh 均不相交。
#                输入与输出集合分开比较，所以同一通道的一入一出仍可同步。
def _validate_assumption21(
    node: HCSP | EventReaction,
) -> None:
    """验证全局自由/绑定分离，并在并行节点验证左右资源分离。"""

    info = _assumption21_info(node)
    shared_value_roles = (
        info.free_value_variables & info.bound_value_variables
    )
    shared_process_roles = (
        info.free_process_variables & info.bound_process_variables
    )
    if shared_value_roles or shared_process_roles:
        labels = list(sorted(shared_value_roles))
        labels.extend(
            f"{name} (process variable)"
            for name in sorted(shared_process_roles)
        )
        raise ValueError(
            "Assumption 2.1 violated: free and bound variables overlap: "
            + ", ".join(labels)
        )

    if not isinstance(node, Parallel):
        return

    left = _assumption21_info(node.left)
    right = _assumption21_info(node.right)
    shared_values = left.value_variables & right.value_variables
    shared_processes = (
        left.process_variables & right.process_variables
    )
    if shared_values or shared_processes:
        labels = list(sorted(shared_values))
        labels.extend(
            f"{name} (process variable)"
            for name in sorted(shared_processes)
        )
        raise ValueError(
            "Assumption 2.1 violated: parallel components share "
            f"variables: {', '.join(labels)}"
        )

    shared_inputs = left.input_channels & right.input_channels
    if shared_inputs:
        raise ValueError(
            "Assumption 2.1 violated: parallel components share "
            "input channels: "
            + ", ".join(sorted(shared_inputs))
        )

    shared_outputs = left.output_channels & right.output_channels
    if shared_outputs:
        raise ValueError(
            "Assumption 2.1 violated: parallel components share "
            "output channels: "
            + ", ".join(sorted(shared_outputs))
        )
