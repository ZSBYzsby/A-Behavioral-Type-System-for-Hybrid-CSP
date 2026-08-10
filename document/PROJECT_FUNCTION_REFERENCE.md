# HCSP Behavioral Type Constructor：完整功能参考

这是对论文 *A Behavioral Type System for Hybrid CSP* 中 Table 2 的 Python
实现。除通信载荷按项目约定扩展为多个独立标量外，项目使用 Section 2.1 的
HCSP 语法，并把 Section 4.2/4.3 要求的安全、时延和递归不变量批注随 AST
一同输入：

- 用户把共享参数、`Gamma`、`Theta` 和 HCSP process 写在同一份完整 source 中；
- 唯一公共接口在内部解析 source，并结合可选初态和路径条件直接生成 Type AST；
- Gamma 的连续项只登记允许出现的完整 ODE 演化向量；轨迹 `phi` 只由 ODE safety 定义；
- 把待构造对象表示成 configuration、system、process 或 event conclusion judgment；
- 每个 `rule_t_*` 只返回显式 `RuleExpansion(premises, conclude)`，不在规则内递归；
- `T-Assign` 在规则展开时确定性地生成惰性最强后置状态，不把未知 `phi'` 留给证明器综合；
- 统一求解器递归处理 child judgment premises，并自底向上组合行为类型；
- 已经具体化的 formula premises（state、FOL、dL）按规则书写顺序立即化简并交给 Z3/KeYmaera X；结果为 `false` 时立即短路，结果为 `unknown` 时记录义务并继续规则构造；
- 有限 ``ODE;skip`` 顺序试用两条 Table 2 规则，并根据各自 premise 的即时结果选择唯一可行结论；
- 内部判定区分 `true`、`false` 和 `unknown`；公共接口只在 `true` 时返回可信
  Type AST。`false` 或无法形成类型的失败通过 `HCSPTypeConstructionError` 报告；
  `unknown` 且构造完整时通过
  `HCSPUntrustedTypeConstructionError.untrusted_type` 提供不可信候选供审计。

这项功能称为 **TypeConstructor**，因为 Type 由程序根据 HCSP 与环境主动构造，
而不是由用户提供。未来的 **TypeChecker** 将接收用户给出的 Type 并检查其正确性；
该功能尚未实现，当前公共接口也不接受用户 Type。

## 获取源码并准备环境

项目支持 Python 3.10–3.13。把源码上传到 GitHub 后，合作者只需克隆仓库、
建立独立虚拟环境并安装 `requirements.txt`；不需要构建 wheel 或 sdist。
以下命令都应在仓库根目录执行。

Windows PowerShell：

```powershell
py -m venv .venv
.\.venv\Scripts\python -m pip install --upgrade pip
.\.venv\Scripts\python -m pip install -r requirements.txt
.\.venv\Scripts\python -m hcsp_typechecker
```

Linux/macOS：

```bash
python3 -m venv .venv
. .venv/bin/activate
python -m pip install --upgrade pip
python -m pip install -r requirements.txt
python -m hcsp_typechecker
```

运行时 Python 依赖只有 `z3-solver`。HCSP 和表达式 AST 均由项目自身定义，
不接受外部工具对象，也不依赖 `.type` 标签或同名字段进行鸭子类型转换。

从源码运行时存在两个明确的能力层次：

1. **核心模式**只要求 Python 和 Z3，可以构造 Process AST、按规则构造 Type AST、
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
python -m hcsp_typechecker --require-keymaerax
```

Linux/macOS：

```bash
export KEYMAERAX_JAR="$HOME/tools/keymaerax.jar"
export KEYMAERAX_JAVA="$(command -v java)"
export KEYMAERAX_HOME="$PWD/.keymaerax-home"
export KEYMAERAX_TIMEOUT=60
python -m hcsp_typechecker --require-keymaerax
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
`python -m hcsp_typechecker` 显式加入
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

普通用户只使用包根提供的 `construct_hcsp_type(...)`。它按
[GAMMA_THETA_INPUT_SYNTAX.md](GAMMA_THETA_INPUT_SYNTAX.md) 解析一份完整输入，在
内部把共享参数、Gamma、Theta 和 Process AST 保持为同源数据，然后立即执行完整
类型构造：

```python
from hcsp_typechecker import construct_hcsp_type

source = """
gamma(x: Int)
parameters(limit: Int) where(limit >= 0)
theta(ch: channel(value: Int) where(value <= limit))
process {{ch?(x); ch!(x)}}
"""

type_ast = construct_hcsp_type(
    source,
    source_name="example.hcsp",
    output="result",
)
```

解析结果不会作为公共中间对象返回，Process AST 也不会通过包根暴露。接口会自行
建立 Table 2 所需的配置，并按规则顺序一边构造类型、一边证明公式。证明义务为
`false` 时立即停止；为 `unknown` 时保留证据并继续构造。构造完整且全部义务为
`true` 时返回可信 `TypeAST`；构造完整但仍有 `unknown` 时抛出
`HCSPUntrustedTypeConstructionError`，完整候选类型只通过其 `untrusted_type`
属性提供。

接口支持以下 `output` 模式：

- `"none"`：默认值，不打印；
- `"result"`：显示最终结论；成功时按规范用户 Type 语法打印可信类型，证明未决
  时按同一语法打印完整候选及“不可信”标记，其他失败打印原因和部分进度；
- `"full"`：打印原始输入、环境摘要、内部构造完成说明、规则步骤、FOL/dL 公式、
  证明器结论、未决义务和最终可信性，但不打印 Process AST 对象/repr。

打印模式只影响展示，不改变返回对象、证明过程或异常语义。若要重定向日志，可
通过 `stream=` 传入文本流。完整的调用参数和失败处理见“输入和输出”一节。
词法、语法或 source 结构错误抛出带文件名、行、列和源码指示位置的
`HCSPInputError`。

`parse_hcsp_source`、`parse_hcsp`、`parse_expression`、`construct_type` 和直接 Python
AST 构造器仍供项目实现、测试和论文规则审计使用，但属于内部开发接口，不从包根
公开，也不承诺跨版本保持调用协议稳定。普通用户不需要构造
`TypeConstructionRequest`、内部判断或 `TypeConstructionReport`。

若要手工修改简短完整输入并查看最终结果，可在仓库根目录运行：

```text
python demo.py
```

把共享参数、Gamma、Theta 和 Process 绑定成一份完整 source 的用户输入格式已经整理在
[GAMMA_THETA_INPUT_SYNTAX.md](GAMMA_THETA_INPUT_SYNTAX.md)；该文档是统一解析器
已经实现的权威根语法，`HCSP_INPUT_SYNTAX.md` 只定义其 Process/Expr 子语法。

以下关于具体 Process/Expr 节点和 Python 构造器的内容用于维护者审计内部表示，
不是普通用户的调用方式，也不属于包根稳定接口。

其中 `If`、`Sequence` 和 `Parallel` 是二元节点，`InternalChoice` 是带公共
后继的多元节点，`E` 只能
出现在 ODE 的中断字段中。`Sequence.of(...)`、`InternalChoice.of(...)`、
`EventChoice.of(...)`、`Parallel.of(...)` 是生成上述规范递归 AST 的类方法。

`(P_1 |~| ... |~| P_n); Q` 的唯一规范表示是
`InternalChoice(P_1, ..., P_n, continuation=Q)`。
`InternalChoice(P_1, ..., P_n)` 是允许缺省公共后继的便捷写法，构造后的
`continuation` 字段仍实际保存 `Skip()`。直接写
`Sequence(InternalChoice(...), Q)` 会被拒绝；`Sequence.of(...)` 若遇到这种
便捷输入，会立即把 Q 吸收进多元选择节点。

Table 2 的 T-sqcup 在这个 AST 上分别推导 `P; Q` 和 `P'; Q`，再把结果
组成内部选择类型。因此无需引入通用的类型级 `T-Seq`。

通道名 `ch`、状态变量、进程变量和类型变量统一使用 ASCII IDENT 词法形状
`[A-Za-z_][A-Za-z0-9_]*`。用户文本还要排除语法保留字，因此 `chan`、
`channel_1`、`_private` 合法，而裸 `channel` 是环境类型构造关键字，不能作为源码
标识符。Unicode 名称、全角兼容字符、空白名称、`1channel`、`a-b`、`a.b` 以及
带首尾空格或换行的名称会在 Expr AST、Process AST、Type AST 或环境入口被拒绝。

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
生成精确 boundary 义务，未配置 KeYmaera X 时总体判定保守显示 `unknown`；规则
推导仍会尽量形成完整候选，但该候选保持未验证状态。
也可以把 domain/safety 改成例如 `t < 5 and x < 20` 与 `x >= t`；它们分别
成为演化域不变量和安全性后置条件。
用户不能把 `t` 再写成方程左端，因为 `t'=1` 已由 ODE 自动提供。局部 `t`
不进入 Gamma、`fv`、`bv`、`get_vars()` 或并行分区 `V`，也不作用于事件分支
continuation 和 ODE 的顺序后继。若这些后续位置需要一个持久时钟，应改用另一
个普通状态变量并在 Gamma 中声明。不同 ODE（包括并行 ODE）各自获得不同内部
实例，TypeConstructor 生成 dL 时将各处源名 `t` 映射到本 ODE 的同一个新鲜 Real。

普通 ODE 的隐藏时钟只负责测量时间，不会把时延边界偷加进用户演化域，
因此 `delay` 仍是由用户提供的外部批注；只有带自然顺序后继的有限 ODE 才按
Table 2 额外验证恰好到达该边界。ODE 若需要在 `d` 时自然结束，应在自己的
演化域中显式写出严格边界，
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
同一通道的一入一出仍合法，可用于并行同步；违反这三项会在进入 TypeConstructor
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
python demo.py
python -m unittest discover -s tests -p "test_*.py" -v
```

提交或推送前可一次运行环境诊断、隐私路径扫描和完整回归测试：

```text
python scripts/check_repository.py
```

`tests/` 当前共有 379 个自动化测试，并按职责分层组织：

```text
tests/
├── backend/        4 个后端目录边界、共享引擎和单向依赖测试
├── expressions/    24 个表达式 AST、输入边界和精确解析测试
├── frontend/       4 个前端目录边界测试
├── hcsp_syntax/    57 个 Section 2.1 AST 与 Assumption 2.1/2.2 测试
├── input_frontend/ 66 个完整 source、参数环境、Process 与表达式输入测试
├── annotations/    18 个 Section 4.2/4.3 批注与自动局部时钟测试
├── type_ast/       15 个行为类型 AST 规范化测试
├── type_constructor/ 108 个构造、Table 2 契约、参数背景、ODE 选规和通信测试
├── type_checker/   12 个给定 Type 递归检查、选择分组、日志与 Constructor 往返测试
├── type_syntax/    8 个 Type 文本与 Type AST 可逆转换测试
├── model/          14 个值类型、连续类型、通道边界、环境自检和详细报告测试
├── logic/          6 个表达式语义、偏函数有定义性和状态值测试
├── dl/             26 个 dL 公式、KeYmaera X 后端和公开 API 集成测试
├── public_api/     16 个稳定门面、案例脚本、日志模式、往返演示和失败异常测试
└── quality/        1 个全项目文档及测试审计注释完整性检查
```

表达式解析测试覆盖头部注释列出的每一种支持语法，并比较完整 `Expr` AST。
Process → Type 测试同样比较行为类型 AST，而不是只比较输出字符串。Table 2
规则、证明义务和预期结果均直接写在相应测试文件的头注释与测试函数注释中。
公开仓库的持续集成会在 Windows/Linux 和受支持 Python 版本上重复安装与运行
这些测试；真实 KeYmaera X 证明作为显式配置的完整模式 smoke test，不是核心
测试的隐含依赖。

论文第 4.3 节的递归例子也可以完全通过用户语法输入：

```python
from hcsp_typechecker import construct_hcsp_type

source = """
gamma()
theta(
    ch: channel(received: Real) where(received >= 1),
    dh: channel(sent: Real) where(sent >= 0)
)
process {{
    mu X invariant(true) {
        ch?(x);
        dh!(sqrt(x));
        call X
    }
}}
"""

type_ast = construct_hcsp_type(source, output="full")
# 日志按用户 Type 语法显示：type mu t1. forever interrupt angelic {...}
```

## 公共接口的输入和输出

包根 `hcsp_typechecker` 只公开以下稳定白名单：

- 两个操作：`construct_hcsp_type` 与 `check_hcsp_type`；
- 正式结果抽象基类：`TypeAST`；
- 打印模式枚举：`OutputMode`；
- 四个公共异常：`HCSPInputError`、`HCSPTypeConstructionError`、
  `HCSPUntrustedTypeConstructionError`、`HCSPTypeCheckingError`。其中
  `HCSPUntrustedTypeConstructionError` 是
  `HCSPTypeConstructionError` 的子类。

Constructor 接口的签名为：

```python
construct_hcsp_type(
    source,
    *,
    source_name="<input>",
    initial_states=None,
    path_condition=True,
    output=OutputMode.NONE,
    stream=None,
    z3_timeout_ms=5000,
    keymaerax_timeout_seconds=None,
) -> TypeAST
```

Checker 的稳定入口为：

```python
check_hcsp_type(
    source,
    *,
    source_name="<input>",
    initial_states=None,
    path_condition=True,
    output=OutputMode.NONE,
    stream=None,
    z3_timeout_ms=5000,
    keymaerax_timeout_seconds=None,
) -> TypeAST
```

它要求 source 在相同四类输入后追加 `type configuration_type`，以给定 Type
为每个规则 judgment 的结论递归检查；失败抛出 `HCSPTypeCheckingError`。

- `source` 必须包含 Gamma、可选 Parameters、Theta 和 Process；解析得到的环境和
  Process AST 只在本次调用内部存在，不作为公共结果返回；
- 单进程的 `initial_states` 可为一个变量到值的 mapping；并行系统必须按
  source 中顶层进程分量的顺序提供同样数量的 mapping；省略时各分量使用空初态；
- 初态可以只给出 Gamma 中变量的子集，但不能出现 Gamma 未声明的变量，也不能
  给共享参数或 `ContinuousType` 声明标签赋初值；若输入目标本身已在 Gamma 中
  声明为 `BasicType`，它可以有初值，之后仍会被接收动作覆盖；
- `path_condition` 默认为 `true`，也可以传入符合项目表达式语法的字符串；该
  字符串的语法错误同样以带独立来源位置的 `HCSPInputError` 报告；
- 两个 timeout 只改变相应证明器的等待上限，不改变数学规则。

只有总体 verdict 为 `true` 且已经形成可信类型时，接口才直接返回 `TypeAST`。
结构/静态失败或必要公式为 `false` 时，构造立即停止并抛出
`HCSPTypeConstructionError`。公式为 `unknown` 时不会短路：TypeConstructor 记录
它并继续构造；若最终形成完整候选类型，接口抛出
`HCSPUntrustedTypeConstructionError`，其 `untrusted_type` 属性保存该候选。候选适合
审计或交给其他工具补证，但在未决义务消除前不可信。若仍未形成完整类型，则抛出
普通 `HCSPTypeConstructionError`。类型构造异常公开 `verdict`、`reason`、
`partial_types`，并提供 `format_result()` 与 `format_full()`。词法、语法或 source
结构错误会在类型构造
开始前终止并抛出 `HCSPInputError`：

```python
from hcsp_typechecker import (
    HCSPInputError,
    HCSPTypeConstructionError,
    HCSPUntrustedTypeConstructionError,
    construct_hcsp_type,
)

try:
    type_ast = construct_hcsp_type(
        source,
        source_name="example.hcsp",
        output="result",
    )
except HCSPInputError as error:
    print(error.format_diagnostic())
except HCSPUntrustedTypeConstructionError as error:
    # result 已用规范 Type 源码打印候选；对象仍在 error.untrusted_type 中。
    pass
except HCSPTypeConstructionError as error:
    pass
```

`output="none"`、`"result"`、`"full"` 也可分别写成
`OutputMode.NONE`、`OutputMode.RESULT`、`OutputMode.FULL`。接口不会把日志字符串
当作返回值：可信成功时始终返回 `TypeAST`；不可信候选只附着在异常上。`none`
不打印；`result` 打印最终可信结果、不可信完整候选或失败摘要；`full` 打印输入、
环境摘要、实际推导轨迹、FOL/dL 公式、证明结论、待证明义务和类型可信性，但不
暴露内部 Process AST 对象/repr。打印目标默认是标准输出，`stream=` 仅用于定向
到其他文本流。

所有日志中的 Type 都使用 [TYPE_INPUT_SYNTAX.md](TYPE_INPUT_SYNTAX.md) 的规范
用户语法，并带完整 `type` 前缀；不会再并列打印 Python Type AST `repr`。因此
`Type 源码 :` 后的文本可以直接复制回用户输入，并由 TypeChecker 再次读取。

共享参数在 HCSP 执行前由用户选定，所有合法选择必须满足 source 中同一个
`where` 约束。它们不属于任一分量的状态 Gamma，可以被所有并行 Process、通道
refinement、递归不变量和 ODE 公式读取，但不能被初态、赋值、输入动作或 ODE
左端修改。例如：

```hcsp
gamma(
    p: Real,
    v: Real,
    a: Real,
    vehicle_ode: continuous(p, v, a)
)
parameters(
    end: Real,
    vmax: Real,
    amin: Real,
    amax: Real
) where(end >= 0 and vmax >= 0 and amin < 0 and amax >= 0)
theta()
process {{skip}}
```

若参数约束记为 `H`，配置路径记为 `phi`，T-sigma 实际检查
`H -> phi[sigma]`；后续规则在背景条件 `H and phi` 下推导。因此结果表示
“对每一个满足 H 的预赋值，类型构造均成立”，而不是只检查某一组参数实例。
TypeConstructor 还会验证 `H` 可满足，拒绝用矛盾约束得到真空证明。

Gamma 中的 `p`、`v`、`a` 是具有当前值的标量；`vehicle_ode` 只登记允许出现的
完整 ODE 演化向量，不是可读取、赋值或通信更新的普通值。ODE 用户方程左侧的
变量集合必须与某个 `continuous(...)` 集合恰好相等，排列顺序没有语义差异；
真子集和真超集会被拒绝。没有显式方程的空 flow ODE 无需 continuous 声明。
连续演化中要保持的 `phi` 只写在 ODE 的 `safety(...)` 中。ODE 隐藏时钟 `t`
由节点管理，不进入 Gamma，也不参与向量匹配。

内部 `construct_type` 会形成包含 verdict、证明义务、诊断和规则轨迹的
`TypeConstructionReport`，但它不是普通用户接口。公共门面只在全部义务通过时
交付可信 Type AST；确定失败通过 `HCSPTypeConstructionError` 报告，构造完整但
证明未决则通过 `HCSPUntrustedTypeConstructionError` 报告并保留
`untrusted_type`。论文中的 `BottomType`
（`\bot`）始终是正式行为类型，不承担错误占位职责。

## 项目架构与自有 AST

实现按数据流划分为一个稳定门面、三个输入结构层和两个核心职责层：

- `hcsp_typechecker.api`：面向普通用户的门面层，分别编排 Constructor 的“完整
  source → 内部 Process AST → `TypeAST`”与 Checker 的“完整 typed source →
  逐规则验证给定 Type”，并统一打印和异常语义；中间 AST
  不作为公共结果暴露；

- `hcsp_typechecker.frontend.annotated_hcsp_syntax`：带批注 HCSP 与 Expr 的输入结构及其到
  Process/Expr AST 的片段转换；
- `hcsp_typechecker.frontend.typing_context_syntax`：Gamma、Theta、全局参数的输入结构及其到
  内部环境对象的片段转换；
- `hcsp_typechecker.frontend.type_syntax`：用户给定行为 Type 的输入结构，以及 Type AST 的
  解析与规范化输出；
- `hcsp_typechecker.frontend.type_constructor_frontend`：完整 source 的组合前端，负责共享词法、源码位置诊断，
  并将参数环境、Gamma、Theta 和 Process 绑定为一次 TypeConstructor 调用的内部输入；
- `hcsp_typechecker.frontend.type_checker_frontend`：在同一完整输入后继续解析必填
  `type` 分节，并把程序解析记录与用户 Type AST 绑定为一次 TypeChecker 输入；
- `hcsp_typechecker.data_structures.process_ast`：源语言层，`expressions.py` 定义表达式 ``e/B``，
  `ast.py` 定义 Section 2.1 的 ``E/P/S`` process AST，以及附着在 ODE/Mu 上的
  Section 4.2/4.3 批注；
- `hcsp_typechecker.data_structures.type_ast`：行为类型层，定义 Section 4.1 的行为类型
  ``T/A``、Section 4.2 的组合类型 ``mathcal T`` 和 alpha 等价比较；后续所有
  直接分析或变换 Type AST 的功能也放在这一层；
- `hcsp_typechecker.data_structures.runtime_context`：Gamma、Theta、共享参数、
  Configuration，以及基础类型、连续向量和通道 refinement 的运行上下文定义；
- `hcsp_typechecker.backend.common`：Constructor 与 Checker 共享的内部基础层；
  `rule_engine.py` 保存四类 conclusion judgment、两类 premise 和 Table 2 规则展开，
  `model.py` 保存证明义务、诊断、推导步骤与共享规则证据，`logic.py`、`dl.py`
  与 `keymaerax.py` 负责逻辑公式和证明后端；
- `hcsp_typechecker.backend.type_constructor`：TypeConstructor 的独立业务后端，
  其 `model.py` 定义构造请求和报告名称，`constructor.py` 从规则子结论组合出
  Type AST；
- `hcsp_typechecker.backend.type_checker`：TypeChecker 的独立业务后端，消费用户
  Type AST 的对应子树并检查每个规则结论；其请求和报告也由本目录的
  `model.py` 定义。它与 Constructor 均依赖 common，两个业务后端彼此不依赖；
- `hcsp_typechecker.tooling`：项目工具层，目前提供跨平台环境诊断程序。

依赖方向保持单向：`frontend` 只把文本转换为 `data_structures` 中的领域对象；
`backend.common` 只依赖领域对象并提供规则/证明基础设施；两个业务后端分别依赖
`common + data_structures`，彼此不导入；`api.py` 只在最外侧组合前端与后端。

包根 `hcsp_typechecker` 的 `__all__` 是明确的公开白名单：

```text
HCSPInputError, HCSPTypeConstructionError, HCSPTypeCheckingError,
HCSPUntrustedTypeConstructionError, OutputMode, TypeAST,
construct_hcsp_type, check_hcsp_type
```

普通调用方只依赖这八个名称。`parse_hcsp_source`、`parse_hcsp`、
`parse_expression`、`construct_type`、具体 AST 节点、判断、证明义务和后端配置只能
从相应子包取得，它们是内部实现与开发审计接口，不承诺兼容性，也不会重新从
包根导出。以后新增 Type AST 分析功能时，也应先通过门面定义清楚稳定协议，
再选择性加入根包白名单。

各 `rule_t_*` 只展开一层推导规则，process/system 结果类型仍严格分离；
`T-Assign` 通过赋值前路径与更新后的符号映射表示惰性最强后置状态；顺序求解器
只判定已经具体化的逻辑公式。

行为类型 AST 将有限连续行为统一保存为
``FiniteDelayType(d, A, T)``；它仅在打印时按 ``A``、``T`` 是否为空采用
``delay(d).T``、``delay(d) \unrhd A`` 或完整形式的论文缩写。
``d=infinity`` 时超时永远不会发生，因此 process→type 转换使用显式
``InfiniteDelayType(A)``；其 timeout fallback 固定为不可达的 ``bottom``，而顺序后继
只会保留在实际发生的通信中断分支 continuation 中。``EmptyType`` 是过程空通信行为
``0`` 的唯一表示；空和单分支外部选择分别规范为 ``NoInterruptType`` 和单个
输入/输出类型。

下面的字符串表达式和节点构造示例只用于内部实现审计；普通用户应把同样内容
写进完整 source：

```python
from hcsp_typechecker.data_structures.process_ast import (
    Assert,
    Assign,
    BinaryExpr,
    CompareExpr,
    InputChannel,
    Literal,
    OutputChannel,
    Sequence,
    Variable,
    ensure_expr,
)
from hcsp_typechecker.data_structures.runtime_context import BasicType, ChannelType

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

TypeConstructor 使用 `isinstance` 分派。不是 `HCSP` 子类的对象会产生结构错误，即使它
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
携带隐藏局部时钟。TypeConstructor 据此生成正式的 dL 义务，并默认通过项目内建
适配器调用 KeYmaera X：

```python
from hcsp_typechecker import construct_hcsp_type

source = """
gamma(x: Real, ode_x: continuous(x))
theta(done: channel(value: Int))
process {{
    ode(
        flow(dot x = 1),
        domain(x < 1),
        safety(x <= 1),
        delay(1)
    );
    done!(0)
}}
"""

type_ast = construct_hcsp_type(
    source,
    initial_states={"x": 0},
    path_condition="x == 0",
    output="full",
)
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
带自然顺序后继的有限 ODE，其 boundary 义务仍需证明。`false` 会否证当前规则并
立即停止；`unknown` 只留下待证明义务，后续类型结构仍继续推导。

当前可靠翻译子集包括实数/整数常量与变量、`+ - * / ^`、数值比较以及
`not/and/or/implies`。整数参数在 dL 中按实数过近似；布尔状态变量、字符串、
tuple/list、`mod`、表达式级条件和未解释函数不会被不可靠地拼成公式，而会保守
返回 `unknown`。测试或证明后端开发所用的 `dl_checker`、`keymaerax_config`
注入点属于内部 `construct_type` 协议，不是普通用户接口；公共门面从环境变量读取
KeYmaera X 配置，只额外公开 `keymaerax_timeout_seconds` 作为本次调用的超时覆盖。

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
