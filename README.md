# HCSP Behavioral Type Checker

这是对论文 *A Behavioral Type System for Hybrid CSP* 中 Table 2 的 Python
实现。除通信载荷按项目约定扩展为多个独立标量外，项目使用 Section 2.1 的
HCSP 语法，并把 Section 4.2/4.3 要求的安全、时延和递归不变量批注随 AST
一同输入：

- 输入 `Gamma`、`Theta`、路径条件、若干 `(state, HCSP process)`，以及可选的期望类型；
- Gamma 的连续项只登记允许出现的完整 ODE 演化向量；轨迹 `phi` 只由 ODE safety 定义；
- 把待检查对象表示成 configuration、system、process 或 event conclusion judgment；
- 每个 `rule_t_*` 只返回显式 `RuleExpansion(premises, conclude)`，不在规则内递归；
- `T-Assign` 在规则展开时确定性地生成惰性最强后置状态，不把未知 `phi'` 留给证明器综合；
- 统一求解器递归处理 child judgment premises，并自底向上组合行为类型；
- 已经具体化的 formula premises（state、FOL、dL）按规则书写顺序立即化简并交给 Z3/KeYmaera X；
- 有限 ``ODE;skip`` 顺序试用两条 Table 2 规则，并根据各自 premise 的即时结果选择唯一可行结论；
- 返回 `true`、`false` 或 `unknown`，并保留推导类型、证明义务和诊断信息。

## 获取源码并准备环境

项目支持 Python 3.10–3.13。把源码上传到 GitHub 后，合作者只需克隆仓库、
建立独立虚拟环境并安装 `requirements.txt`；不需要构建 wheel 或 sdist。
以下命令都应在仓库根目录执行。

Windows PowerShell：

```powershell
py -m venv .venv
.\.venv\Scripts\python -m pip install --upgrade pip
.\.venv\Scripts\python -m pip install -r requirements.txt
.\.venv\Scripts\python -m hcsp_typechecker.doctor
```

Linux/macOS：

```bash
python3 -m venv .venv
. .venv/bin/activate
python -m pip install --upgrade pip
python -m pip install -r requirements.txt
python -m hcsp_typechecker.doctor
```

运行时 Python 依赖只有 `z3-solver`。HCSP 和表达式 AST 均由项目自身定义，
不接受外部工具对象，也不依赖 `.type` 标签或同名字段进行鸭子类型转换。

从源码运行时存在两个明确的能力层次：

1. **核心模式**只要求 Python 和 Z3，可以构造全部 Process/Type AST、推导类型、
   检查离散规则并生成 ODE 的 dL 证明义务；
2. **完整模式**额外要求 Java 17+ 和 KeYmaera X，用于真正证明 dL 义务。

KeYmaera X 是独立外部工具，本仓库不提交 `keymaerax.jar`。从其官方发行渠道
取得 jar 后，通过环境变量配置，不需要修改任何 Python 文件。Java 已通过
`JAVA_HOME` 配置或已在 `PATH` 中时，可以省略 `KEYMAERAX_JAVA`。查找顺序为
`KEYMAERAX_JAVA`、`JAVA_HOME/bin/java`、`PATH`。

Windows PowerShell：

```powershell
$env:KEYMAERAX_JAR = "C:\tools\keymaerax.jar"
$env:KEYMAERAX_JAVA = "C:\Program Files\Java\jdk-21\bin\java.exe"
$env:KEYMAERAX_HOME = "$PWD\.keymaerax-home"
$env:KEYMAERAX_TIMEOUT = "60"
python -m hcsp_typechecker.doctor --require-keymaerax
```

Linux/macOS：

```bash
export KEYMAERAX_JAR="$HOME/tools/keymaerax.jar"
export KEYMAERAX_JAVA="$(command -v java)"
export KEYMAERAX_HOME="$PWD/.keymaerax-home"
export KEYMAERAX_TIMEOUT=60
python -m hcsp_typechecker.doctor --require-keymaerax
```

若希望保留每次证明生成的 `.kyx/.kyp` 证据，还可以设置：

```text
KEYMAERAX_KEEP_ARTIFACTS=true
KEYMAERAX_ARTIFACTS=<可写输出目录>
KEYMAERAX_CLI_STYLE=auto
KEYMAERAX_TACTIC=auto
KEYMAERAX_ARITHMETIC_TOOL=Z3
```

若未配置 KeYmaera X，核心模式和全部不需要真实外部证明器的自动化测试仍可
运行；需要外部 dL 证明的义务会明确返回 `unknown`，不会被猜成 `true` 或
`false`。环境诊断在这种情况下仍以成功状态退出；只有对
`python -m hcsp_typechecker.doctor` 显式加入
`--require-keymaerax` 才把缺少 Java/jar 视为部署错误。

## Section 2.1 语法

核心 AST 逐项对应论文产生式：

```text
E ::= empty
    | (ch?(x1,...,xn) -> P) [] E
    | (ch!(e1,...,en) -> P) [] E

P ::= skip | x := e | assert(B)
    | ch?(x1,...,xn) | ch!(e1,...,en)
    | if B then P else P'
    | <dot(v)=e & B> |> E
    | P; P' | P |~| P' | X | mu X.P

S ::= P | S || S'
```

其中 `If`、`Sequence` 和 `Parallel` 是二元节点，`InternalChoice` 是带公共
后继的三元节点，`E` 只能
出现在 ODE 的中断字段中。`Sequence.of(...)`、`InternalChoice.of(...)`、
`EventChoice.of(...)`、`Parallel.of(...)` 是生成上述规范递归 AST 的类方法。

`(P |~| P'); Q` 的唯一规范表示是 `InternalChoice(P, P', Q)`。
`InternalChoice(P, P')` 是允许缺省第三项的便捷写法，构造后的
`continuation` 字段仍实际保存 `Skip()`。直接写
`Sequence(InternalChoice(...), Q)` 会被拒绝；`Sequence.of(...)` 若遇到这种
便捷输入，会立即把 Q 吸收进三元选择节点。

Table 2 的 T-sqcup 在这个 AST 上分别推导 `P; Q` 和 `P'; Q`，再把结果
组成内部选择类型。因此无需引入通用的类型级 `T-Seq`。

通道名 `ch` 与项目变量名使用相同的 `str.isidentifier()` 词法规则。比如
`channel`、`channel_1`、`_private` 和 `通道_1` 合法；空白名称、`1channel`、
`a-b`、`a.b` 以及带首尾空格或换行的名称会在 Process AST、Type AST 或 Theta
环境入口立即被拒绝。

项目通过 `ODE.wait(d)` 提供源级 `wait(d)` 语法糖，但不增加额外的
`Wait` Process 节点。它展开为
使用隐藏局部时钟的 `ODE; Skip`：

```python
waiting = ODE.wait(5)

# 等价核心形状：Sequence(ODE(...), Skip())
# ODE 没有用户方程，内部时钟满足 t(0)=0、t'=1，演化域为 t<5。
```

`d` 必须是有限非负有理数，支持 int、float、Decimal、Fraction 和常量有理
算式；负数、符号量、Bool、NaN 和正负无穷都会在构造边界被拒绝。

此外，每个普通 `ODE(...)` 也会自动建立一个独立的 `ODELocalClock`：进入 ODE
时初值固定为 `0`，连续导数固定为 `1`。用户不需要为了测量 ODE 的演化时间
而在方程、Gamma 或初始状态中声明时钟：

```python
ode = ODE(
    [("x", "t + 1")],
    True,
    annotation=ODEAnnotation(safety=True, delay=5),
)

assert ode.local_clock.name == "t"
assert ode.local_clock.initial_value == Literal(0)
assert ode.local_clock.derivative == Literal(1)
```

在一个 ODE 的方程右端、演化域和 `safety` 中，保留名 `t` 直接表示该 ODE
隐式时钟的当前值；上例的 Gamma 把 `x` 声明成普通 `Real`，再用另一个键登记
`ode_x: ContinuousType(("x",))`，不需要声明或初始化 `t`。核对 Gamma 中的 ODE
向量时只读取用户写在 `ODE.eqs` 左侧的变量，自动添加的 `t` 不属于该向量。
这个默认例子的 domain/safety 都是 `true`，所以纯通信中断、无自然后继的
ODE 可直接生成 type `delay(5).(\bot)`。若 ODE 后还有顺序后继，则会按论文
生成精确 boundary 义务，未配置 KeYmaera X 时总体判定保守显示 `unknown`。
也可以把 domain/safety 改成例如 `t < 5 and x < 20` 与 `x >= t`；它们分别
成为演化域不变量和安全性后置条件。
用户不能把 `t` 再写成方程左端，因为 `t'=1` 已由 ODE 自动提供。局部 `t`
不进入 Gamma、`fv`、`bv`、`get_vars()` 或并行分区 `V`，也不作用于事件分支
continuation 和 ODE 的顺序后继。若这些后续位置需要一个持久时钟，应改用另一
个普通状态变量并在 Gamma 中声明。不同 ODE（包括并行 ODE）各自获得不同内部
实例，类型检查器生成 dL 时将各处源名 `t` 映射到本 ODE 的同一个新鲜 Real。

普通 ODE 的隐藏时钟只负责测量时间，不会把时延边界偷加进用户演化域，
因此 `delay` 仍是由用户提供的外部批注；只有带自然顺序后继的有限 ODE 才按
Table 2 额外验证恰好到达该边界。只有显式调用
`ODE.wait(d)` 时，语法糖才为自己的局部时钟加入论文规定的 `t<d` 演化域。
普通 ODE 若需要在 `d` 时自然结束，应在自己的演化域中显式写出严格边界，
例如 `t < 5`。

### Assumption 2.1 构造期检查

项目检查 `fv(S) ∩ bv(S) = ∅`。`ch?(x1,...,xn)` 把所有 `xi` 加入绑定值变量
集合，并绑定它的顺序后继或事件分支 continuation 中的同名出现；`mu X.P` 把 `X` 加入
绑定进程变量集合，并绑定递归体 `P` 中的同名出现。如果某个名称还在绑定范围
外自由出现，复合 AST 构造器会立即抛出 `ValueError`。

因此 `ch?(x,y); assert(x >= 0 and y >= 0)` 合法，而
`assert(x >= 0); ch?(x,y)`、在不同选择
分支中分别自由使用和绑定 `x`，或者在同一系统中同时自由使用和绑定进程变量
`X` 都不合法。

项目对复合顺序前缀采用已确认的作用域约定：前缀某个分支中出现的
`ch?(x1,...,xn)` 可绑定该复合前缀的公共顺序后继。因此
`Sequence.of(If(B, InputChannel("ch", ("x",)), Skip()), P_using_x)` 按项目约定合法；
实现不要求 `x` 在前缀的每个分支上都被绑定。

构造 `Parallel(S1, S2)` 时还会检查两个分量的变量全集
`V = fv ⊎ bv`、输入通道集合 `iCh` 和输出通道集合 `oCh` 必须分别不相交。
同一通道的一入一出仍合法，可用于并行同步；违反这三项会在进入类型检查器
之前抛出 `ValueError`。

### Assumption 2.2 构造期检查

构造 `Mu("X", body)` 时会立即检查 communication-guarded 条件：`body` 中
每个受该 `mu` 绑定的 `Var("X")`，在所有可到达它的控制流路径上都必须先
经过 `InputChannel` 或 `OutputChannel`。赋值、断言、`skip` 和 ODE 演化本身
都不算通信；任一路径未通信便回到 `X` 时，构造器会抛出 `ValueError`。

检查覆盖顺序、条件、内部选择和 ODE 事件 continuation，并遵守词法作用域：
内层同名 `Mu("X", ...)` 会遮蔽外层绑定。ODE 的事件 continuation 由对应
事件通信保护，但 ODE 自然结束后的外层顺序后继不会继承该保护。
实现按这些 AST 产生式直接递归，便于逐项对照论文规则；项目不再额外保证
超过 Python 递归上限的人工超深语法树仍可处理。

## Section 4.2/4.3 批注

批注不会增加新的 `P` 节点，而是附着在原有 ODE 和 `mu` 节点上：

```text
ODE:  <dot(v)=e & B>_safety |>[delay] E
mu:   mu X_invariant.P
```

对应的 Python 构造为：

```python
ode = ODE(
    [("x", 1)],
    "x < 10",
    annotation=ODEAnnotation(
        safety="x <= 10",
        delay=2,
    ),
)

loop = Mu(
    "X",
    Sequence.of(OutputChannel("tick", (0,)), Var("X")),
    annotation=RecursionAnnotation("x >= 0"),
)
```

`safety` 或递归 `invariant` 省略时按论文约定等于 `true`。每个 `ODE` 都必须
显式提供 `ODEAnnotation`，且其中的 `delay` 必填。有限 delay 必须是可静态
计算的非负有理常量，正无穷也合法；符号变量、负数、Bool、NaN 和负无穷会在
AST 构造时立即报错。

`ODEAnnotation` 只保存用户提供的 `safety` 和 `delay`；自动 `local_clock` 是
ODE 节点的独立只读语义字段，不是第三种批注，也不接受用户构造参数。
`ODE.wait(d)` 展开所得 ODE 还会内部保存规范化后的
`local_clock_deadline=d`；普通
`ODE(...)` 的该字段为 `None`，调用方同样不能直接注入。

有限 delay 会统一保存为精确 `Fraction` 字面量。以下输入均合法：

```python
from decimal import Decimal
from fractions import Fraction

ODEAnnotation(delay=2)
ODEAnnotation(delay=0.5)                 # 规范化为 Fraction(1, 2)
ODEAnnotation(delay=Decimal("0.125"))    # 规范化为 Fraction(1, 8)
ODEAnnotation(delay=Fraction(2, 3))
ODEAnnotation(delay="1 / 4 + 1 / 4")     # 常量算式，结果为 Fraction(1, 2)
ODEAnnotation(delay=float("inf"))
```

以下输入会抛出 `ValueError`：

```python
ODEAnnotation()                 # 缺失 delay
ODEAnnotation(delay=-1)         # 负数
ODEAnnotation(delay="d")        # 符号时延
ODEAnnotation(delay="sqrt(2)")  # 不能静态确定为有理数
ODE([("x", 1)], True)           # 整个 ODEAnnotation 缺失
```

## 快速运行与测试

克隆仓库并安装依赖后，在仓库根目录运行：

```text
python tests/tmp.py
python -m unittest discover -s tests -p "test_*.py" -v
python -m unittest discover -s test2 -p "test_*.py" -v
```

提交或推送前可一次运行环境诊断、隐私路径扫描和两组回归测试：

```text
python scripts/check_repository.py
```

`tests/` 当前共有 237 个自动化测试，并按职责放在九个子目录中；`test2/`
另外提供 35 个便于逐文件审计和手工修改的 Process -> Type 单样例：

```text
tests/
├── expressions/    23 个表达式 AST、输入边界和精确解析测试
├── hcsp_syntax/    59 个 Section 2.1 AST 与 Assumption 2.1/2.2 测试
├── annotations/    19 个 Section 4.2/4.3 批注与自动局部时钟测试
├── type_ast/       10 个行为类型 AST 规范化测试
├── typechecking/   83 个转换、Table 2 契约、短路推导、ODE 选规和通信测试
├── model/         10 个值类型、连续类型、通道边界、环境自检和详细报告测试
├── logic/          6 个表达式语义、偏函数有定义性和状态值测试
├── dl/             26 个 dL 公式、KeYmaera X 后端和公开 API 集成测试
└── quality/        1 个全项目文档及测试审计注释完整性检查
```

表达式解析测试覆盖头部注释列出的每一种支持语法，并比较完整 `Expr` AST。
Process → Type 测试同样比较行为类型 AST，而不是只比较输出字符串。Table 2
规则、证明义务和预期结果均直接写在相应测试文件的头注释与测试函数注释中。
公开仓库的持续集成会在 Windows/Linux 和受支持 Python 版本上重复安装与运行
这些测试；真实 KeYmaera X 证明作为显式配置的完整模式 smoke test，不是核心
测试的隐含依赖。

论文第 4.3 节的递归例子：

```python
from hcsp_typechecker import *

program = Mu(
    "X",
    Sequence.of(
        InputChannel("ch", ("x",)),
        OutputChannel("dh", ("sqrt(x)",)),
        Var("X"),
    ),
    annotation=RecursionAnnotation(True),
)

report = check_hcsp(
    gamma={},
    theta={
        "ch": ChannelType((BasicType.REAL,), lambda eta: eta >= 1),
        "dh": ChannelType((BasicType.REAL,), lambda eta: eta >= 0),
    },
    configurations=[Configuration({}, program)],
)

print(report.verdict)       # true
print(report.inferred_type) # mu t1.(ch?.dh!.t1)
print(report.format_detailed())  # 原始公式、证明器输入、证据和遗留义务
```

## 输入和输出

`check_hcsp(...)` 的环境输入为：

1. `gamma`：普通变量类型和允许出现的 ODE 演化向量环境；
2. `theta`：通道 refinement 类型环境；
3. `path_condition`：默认 `True`；
4. `configurations`：进程或 `(state, process)` 列表；
5. `expected_types`：可选的 HCSP 行为类型列表。

并行的有状态系统应按 Table 2 写成多个 `Configuration(state, process, gamma=...,
path_condition=...)`：局部 Gamma 必须两两不交、类型与全局 Gamma 一致，并且
它们的并集恰好等于全局 Gamma；若使用局部路径，所有并行叶子都必须提供，
外层 `path_condition` 保持默认 `True`，表示结论路径由局部路径合取产生。
`Configuration({}, Parallel(...))` 仅作为空 Gamma、空 state、`True` 路径的
无状态协议便捷写法保留；有状态 `Parallel` 必须拆成多个配置叶子。

ODE 与递归批注不再通过第二个映射覆盖，而是直接位于
`Configuration.process` 的 AST 中。这保证审计时一个进程只有一份批注来源。

Gamma 显式区分“具有当前值的标量变量”和“允许出现的 ODE 演化向量声明”。
包括 ODE 分量在内的标量都写成 ``BasicType``；``ContinuousType`` 放在独立键
下，只保存一个 ODE 的变量集合。例如：

```python
gamma = {
    "mode": BasicType.INT,      # 普通离散状态
    "gain": BasicType.REAL,     # 普通实数参数
    "x": BasicType.REAL,        # x 的当前值是 Real
    "ode_x": ContinuousType(("x",)),  # process 中允许出现 ODE vector {x}
}
```

多分量 ODE 向量同样只登记一次；例如车辆的 `p`、`v`、`a` 各自仍是普通
`Real` 变量：

```python
vehicle_trajectory = ContinuousType(
    variables=("p", "v", "a"),
)
gamma = {
    "p": BasicType.REAL,
    "v": BasicType.REAL,
    "a": BasicType.REAL,
    "vehicle_ode": vehicle_trajectory,
}
```

``ContinuousType`` 不是普通值的另一种数值精度，也不是 tuple 值。它只在 Gamma
中登记 process 允许出现的完整 ODE 演化向量，语义为从非负时间到 ``R^n`` 的
轨迹；它本身没有可读取、赋值或通信更新的标量值。ODE 用户方程左侧的变量
集合必须与一个已登记的 ``variables`` 集合相等，方程排列顺序没有语义差异；
真子集和真超集仍会被静态拒绝。没有显式方程的 ``ODE.wait(d)`` 对应空集合，
无需 ``ContinuousType`` 声明。连续演化中需要恒成立的 ``phi`` 只写在对应 ODE
的 ``annotation.safety`` 中，不再由 Gamma 重复定义。ODE 的隐藏局部时钟 ``t``
由节点自行管理，不进入 Gamma，也不参与向量匹配。

返回 `CheckReport`：

- `verdict`：`true / false / unknown`；
- `inferred_type`：组合后的行为类型；结构/静态前提失败或逻辑 premise 为
  `false/unknown`、导致推导停止时为 `None`；
- `component_types`：每个 configuration 的行为类型，失败位置保留为 `None`；
- `obligations`：按推导顺序已经完成判定的公式及结果；其中 `formula` 保留规则
  生成的原始 premise，`proof_formula` 保存实际送入证明器的化简公式；ODE
  候选义务还以 `active/candidate` 区分最终采用与仅供审计的证据；
- `diagnostics`：结构错误、类型不匹配和不支持项。
- `format_detailed()`：按义务编号打印论文 premise、两层公式、判定后端、证明器
  说明，并在独立区域集中列出所有 `false/unknown` 遗留义务。

论文中的 `BottomType`（`\bot`）始终是正式行为类型，例如有限时延没有正常
后继时的类型结果。它不承担错误恢复职责；未声明通道、非法守卫等导致无法按
Table 2 形成类型时，报告使用 `None`，具体原因保存在 `diagnostics` 中。若类型
静态类型前提（例如赋值两侧基础类型、Bool 守卫、通信槽位类型、ODE 导数
类型）失败时，Table 2 规则不能成立，因而不生成正式类型。普通规则的逻辑
premise 只有判为 `true` 才继续；一旦为 `false` 或 `unknown`，当前推导立即
停止，未访问的后继不再生成步骤、证明义务或候选类型。报告仍完整保留停止点
以前的部分轨迹。``ODE;skip`` 是选规场景：每条候选规则在自己的非真 premise
处停止，选择器只会采用所有 premise 均已证明且结论唯一的候选。

## 项目自有 AST

项目将三类语法树和检查数据明确分开：

- `hcsp_typechecker.expressions`：表达式 ``e/B`` 的 AST 和字符串解析；
- `hcsp_typechecker.hcsp_process_ast`：Section 2.1 的 ``E/P/S`` process AST，
  以及附着在 ODE/Mu 上的 Section 4.2/4.3 批注；
- `hcsp_typechecker.hcsp_type_ast`：Section 4.1 的行为类型 ``T/A``、
  Section 4.2 的组合类型 ``mathcal T`` 及 alpha 等价比较；
- `hcsp_typechecker.checker`：四类 conclusion judgment、两类 premise、
  `RuleExpansion` 和统一递归求解器；各 `rule_t_*` 只展开一层推导规则，
  process/system 结果类型仍严格分离；`T-Assign` 通过赋值前路径与更新后的
  符号映射表示惰性最强后置状态；顺序求解器只判定已经具体化的逻辑公式；
- `hcsp_typechecker.model`：Gamma/Theta 的值与通道类型、typing judgment、
  proof obligation、diagnostic 和最终报告。

行为类型 AST 不使用一个通用 ``DelayType`` 混合全部连续行为，而按推导结果
保存为互斥节点：``PureDelayType(d, T)`` 表示无通信的 ``delay(d).T``，
``CommunicationTimeoutType(d, A)`` 表示有限时间内必须通信，
``TimedExternalChoiceType(d, A, T)`` 表示通信中断和自然结束后继同时存在。
``d=infinity`` 时超时永远不会发生，因此 process→type 转换把 timeout fallback
固定为 ``bottom``，再按论文定义式规范成 angelic type ``A``；顺序后继只会保留
在实际发生的通信中断分支 continuation 中。``EndType`` 是 ``0`` 的唯一表示；
空和单分支外部选择分别规范为 ``EndType`` 和单个输入/输出类型。

字符串表达式只是一种构造器便捷输入，会立即解析成项目节点：

```python
from hcsp_typechecker import *

expr = BinaryExpr("+", Variable("x"), Literal(1))
hp = Sequence.of(
    Assign("x", expr),
    Assert(CompareExpr((Variable("x"), Literal(0)), (">=",))),
)

# 普通表达式结果都是标量基础类型；Gamma 另用 ContinuousType 登记 ODE 集合。
scalar_value = ensure_expr("x + 1")
multi_channel = ChannelType(
    (BasicType.INT, BasicType.BOOL),
    "eta1 >= 0 and eta2",
)
multi_input = InputChannel("data", ("x", "ready"))
multi_output = OutputChannel("data", ("x", "ready"))
```

检查器使用 `isinstance` 分派。不是 `HCSP` 子类的对象会产生结构错误，即使它
拥有 `type`、`hps` 或 `expr` 等同名字段也不会被接受。

表达式层只支持标量字面量、变量、算术、比较、布尔连接和简单函数调用。
论文未要求普通积类型，因此项目不定义 tuple 表达式或 ``TupleType``；字符串形式
和 Python tuple/list 对象都会在普通表达式构造边界被拒绝。表达式结果对应
单个 ``BasicType``。Gamma 的 ``BasicType`` 项才有当前标量值；
``ContinuousType`` 项只是独立的 ODE 向量声明，不能用于表达式。
``ChannelType`` 保存一个非空的
``BasicType`` 槽位序列；``InputChannel`` 和 ``OutputChannel`` 保存同元数的目标变量
或载荷表达式序列。这里的 Python tuple 只是通信参数列表，不是可赋给变量或由表达式
求值得到的 tuple 值。每个载荷表达式都独立产生一个标量值，refinement 可以同时引用
全部槽位的 binder。
表达式级 `a if B else b` 不受支持；条件控制流统一使用进程节点
`If(B, P, P')`。

表达式翻译结果同时保存 Z3 项、`BasicType` 和求值有定义条件。`/` 始终按实数
除法处理，整数操作数会先显式提升；除数非零、`sqrt` 参数非负等条件由相应
Table 2 规则在相应 premise 位置立即判定。`%` 只接受 Nat/Int。因而除零、负数平方根
或 Real 取模会得到可审计的 `false` 义务/诊断，不会沿用 Z3 的全函数扩展，
也不会把原始 `Z3Exception` 泄漏给用户。

## ODE 证明后端

`ODEAnnotation` 保存论文随程序给出的 `safety` 与 `delay`；ODE 自身还自动
携带隐藏局部时钟。类型检查器据此生成正式的 dL 义务，并默认通过项目内建
适配器调用 KeYmaera X：

```python
from hcsp_typechecker import *

program = Sequence.of(
    ODE(
        [("x", 1)],
        "x < 1",
        annotation=ODEAnnotation(safety="x <= 1", delay=1),
    ),
    OutputChannel("done", (0,)),
)

report = check_hcsp(
    gamma={
        "x": BasicType.REAL,
        "ode_x": ContinuousType(("x",)),
    },
    theta={"done": ChannelType((BasicType.INT,))},
    path_condition="x == 0",
    configurations=[Configuration({"x": 0}, program)],
    keymaerax_config=KeYmaeraXConfig.from_environment(),
)

print(report.format_detailed())
```

内建后端会生成单目标 `.kyx` archive，以独立进程运行 KeYmaera X，并兼容
5.1.x 的 `-prove` 参数和新版 `prove` 子命令。它处理三类 ODE 义务：

- 安全性：`pre_with_t=0 → [{ODE,t'=1}](t≤d → safety)`；
- 纯通信中断时的演化域：`pre_with_t=0 → [{ODE,t'=1}]B`；
- 有限 ODE 具有自然顺序后继时的准确边界：在无域动力学
  `{ODE,t'=1}` 上证明 `(t<d → B) ∧ (t=d → ¬B)`。纯通信中断形式没有
  自然超时迁移，因此不生成这条义务。

后继 judgment 也严格按新版 Table 2 区分：纯通信规则的事件分支在
`B ∧ safety` 下检查；带自然超时规则的通信分支只使用 `safety`；其自然后继
使用 `¬B ∧ safety`。这三种条件由不同的内部枚举值表示，不再共用含义模糊的
布尔开关。

`delay=∞` 时不再比较 `t` 与有限边界，但自动时钟仍属于该 ODE；若安全性或
演化域公式不是恒真，生成的 dL 模态仍会包含入口 `t=0` 和方程 `t'=1`。

KeYmaera X 的 `PROVED` 映射为 `true`；明确的反例状态映射为 `false`；未完成、
超时、解析失败、环境缺失和超出可靠翻译子集均映射为 `unknown`。特别地，
`safety=true` 会记录一条直接成立的 safety 义务，无需为该义务启动外部进程；
带自然顺序后继的有限 ODE，其 boundary 义务仍需证明。

当前可靠翻译子集包括实数/整数常量与变量、`+ - * / ^`、数值比较以及
`not/and/or/implies`。整数参数在 dL 中按实数过近似；布尔状态变量、字符串、
tuple/list、`mod`、表达式级条件和未解释函数不会被不可靠地拼成公式，而会保守
返回 `unknown`。如测试或特殊部署确需替换证明器，仍可显式传入
`dl_checker`；不能同时传入 `dl_checker` 和 `keymaerax_config`。

## 判定语义

一阶逻辑和 dL 前提检查的都是“有效性”，不是仅寻找一个满足赋值。一阶逻辑
由 Z3 检查其否定是否不可满足；dL 由 KeYmaera X 尝试证明公式。这与 PPT 中
笼统写的“检查可满足性”不同，但与论文 Table 2 的
`phi => B`、`phi => refinement`、`pre => [ODE]post` 等全称前提一致：

- 否定不可满足：`true`；
- KeYmaera X 返回 `PROVED`：`true`；
- Z3 或 KeYmaera X 给出反例：`false`；
- 求解/证明未完成、超时或工具不可用：`unknown`。

当前范围是 Table 2 的类型构造与 proof obligations，不包含论文 Table 3 的
类型级状态空间搜索（deadlock/livelock model checking）。
