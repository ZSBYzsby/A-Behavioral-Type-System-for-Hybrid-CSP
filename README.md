# HCSP Behavioral Type Constructor and Checker

本项目把一份带 Parameters、Gamma、Theta 与批注 HCSP Process 的用户文本直接
转换为正式 Type AST，并证明构造过程中产生的必要公式；也可以由用户给出 Type，
再按同一套项目规则检查它是否成立；已有 Type AST 还可以按照 Table 3 生成完整可达
状态转移图。普通用户使用包根的 `construct_hcsp_type(...)`、
`check_hcsp_type(...)` 与 `build_type_transition_graph(...)`；解析时
生成的 Process AST、具体 Type AST 构造器、判断对象、证明义务和证明器适配器均
属于内部实现，不构成稳定调用协议。

## 运行环境

- Python 3.10–3.13；
- `z3-solver`，用于表达式类型、状态和一阶逻辑义务；
- Java 17+ 与 KeYmaera X，可选但用于真正证明非平凡 ODE 的 dL 义务。

在源码根目录安装并检查环境：

```text
python -m pip install -r requirements.txt
python -m hcsp_typechecker
```

缺少 KeYmaera X 不影响离散程序和恒真 ODE 义务；需要外部 dL 证明的程序会保守
得到 `unknown`。TypeConstructor 会记录这类未决义务并继续规则构造，尽量形成完整候选
Type AST，但该候选会被明确标为未验证、不可信。使用
`python -m hcsp_typechecker --require-keymaerax` 可把证明器缺失视为环境错误。

## 稳定用户接口

包根稳定白名单只有 `HCSPInputError`、`HCSPTypeConstructionError`、
`HCSPUntrustedTypeConstructionError`、`HCSPTypeCheckingError`、`OutputMode`、
`TypeAST`、`TypeTransitionGraph`、`construct_hcsp_type`、`check_hcsp_type` 和
`build_type_transition_graph`。

```python
from hcsp_typechecker import (
    HCSPInputError,
    HCSPTypeConstructionError,
    HCSPUntrustedTypeConstructionError,
    construct_hcsp_type,
)

source = """
gamma(x: Int)
parameters(limit: Int) where(limit >= 0)
theta(ch: channel(value: Int) where(value <= limit))
process {{ch?(x); ch!(x)}}
"""

try:
    type_ast = construct_hcsp_type(
        source,
        source_name="example.hcsp",
        output="result",  # 打印可复制、可再次作为输入的规范 Type 源码
    )
except HCSPInputError as error:
    print(error.format_diagnostic())
except HCSPUntrustedTypeConstructionError as error:
    # 类型结构已经构造完成，但至少一条必要公式仍未证明。
    # result 已按规范 Type 源码打印候选；对象仍在 error.untrusted_type 中。
    pass
except HCSPTypeConstructionError as error:
    # result 已打印失败原因和部分推导。
    pass
```

`construct_hcsp_type(...)` 在内部依次解析完整 source、建立 Process AST 和构造配置，
并在展开规则的过程中依次证明公式。Process AST 不作为公共返回值暴露。三种结果
必须区分：

- 词法、语法或输入结构错误会立即终止并抛出 `HCSPInputError`，类型构造不会启动；
- 结构/静态前提失败或必要公式得到 `false` 时，当前推导立即停止并抛出
  `HCSPTypeConstructionError`；异常保留原因、已形成的部分类型和停止前的审计日志；
- 必要公式得到 `unknown` 时，只记录未决义务并继续推导。若最终形成完整候选
  Type AST，接口抛出 `HCSPUntrustedTypeConstructionError`；其 `untrusted_type`
  属性可供审计或外部补证，但它没有通过证明验证，不能当作可信返回值。若因其他
  原因仍未形成完整类型，则抛出普通 `HCSPTypeConstructionError`。

只有构造完整且全部证明义务均为 `true` 时，接口才正常返回可信 `TypeAST`。
`HCSPUntrustedTypeConstructionError` 是 `HCSPTypeConstructionError` 的子类；
需要读取 `untrusted_type` 时应像
示例一样先捕获它。`BottomType` 是用户 Type AST 中的正式不可达错误行为，
TypeChecker 可以读取并按规则检查；当前 TypeConstructor 不会把它作为已构造 HCSP
行为的结果。

### 检查用户给定的 Type

在同一份输入末尾增加规范 `type` 段，然后调用 TypeChecker 入口：

```python
from hcsp_typechecker import HCSPTypeCheckingError, check_hcsp_type

typed_source = """
gamma(x: Int)
theta(ch: channel(value: Int))
process {{ch?(x); ch!(x)}}
type forever interrupt angelic {
    ch? -> forever interrupt angelic {ch! -> empty}
}
"""

try:
    checked_type = check_hcsp_type(typed_source, output="result")
except HCSPTypeCheckingError as error:
    print(error.format_full())
```

TypeChecker 不会先运行 TypeConstructor 再比较两棵完整 Type AST。它以用户 Type
作为每个 Table 2 judgment 的给定结论，递归拆解 Process 与 Type：静默语句检查
同一个后继类型；通信、delay、递归和并行检查对应的 Type 子树；多元内部选择与
外部中断按分支数和书写顺序逐项检查。每条规则产生的 FOL/dL premise 仍使用与
TypeConstructor 相同的可信证明机制。Type 结构不匹配、静态规则失败或必要公式
为 `false/unknown` 时抛出 `HCSPTypeCheckingError`；只有全部规则和证明均为
`true` 时返回用户给定的正式 `TypeAST`。

### 从 Type AST 生成 Table 3 状态图

```python
from hcsp_typechecker import (
    TypeTransitionGraph,
    build_type_transition_graph,
    construct_hcsp_type,
)

type_ast = construct_hcsp_type(source)
graph = build_type_transition_graph(type_ast, output="full")

assert isinstance(graph, TypeTransitionGraph)
print(len(graph.states), len(graph.transitions), graph.complete)
```

该接口先把已有 Type AST 单向转换为操作语义专用的规范化 Type AST，再以初态为
根穷尽 Table 3 的全部可达非确定性后继。规范化会消除并行排列和空单位元差异，
把内部选择按结合/交换/幂等律展平排序去重，把外部选择按交换/幂等律排序去重，并
使用 De Bruijn index 消除递归绑定变量改名差异。规范化 AST 只作为图结点内容，
不提供转回原 Type AST 的接口。

规范状态输出沿用 `parallel`、`empty`、`internal`、`delay`、`forever` 和
`angelic`；根部增加 `normalized` 标记。由于规范内部选择已经展平，分支不再套
圆括号；匿名递归写成 `mu { ... }`，De Bruijn 引用写成
`recursion_position(index)`。该格式只用于展示和审计，不接受用户输入，也没有
parser。语法见
[规范化 Type AST 输出格式](document/NORMALIZED_TYPE_OUTPUT_SYNTAX.md)。

`build_type_transition_graph(..., output="result")` 输出图规模、完整性和初始规范
类型；`output="full"` 输出全部规范状态、边标签及 Table 3 规则证据。两个内部
formatter 不从包根公开。完整格式见
[状态迁移图输出语法](document/TYPE_TRANSITION_GRAPH_OUTPUT_SYNTAX.md)。

时间转移只前进到所有分量共同等待时的下一个最早有限 deadline；若全部分量均可
无限等待，则生成 infinity 时间边。`EmptyType` 是并行单位元，不会阻塞其他分量；
并行保留重复分量。相同源、标签和目标由多种规则实例得到时，图只保存一条边，
但在 `derivations` 中保存全部不同推导证据。

`max_states` 和 `max_transitions` 可限制状态爆炸。触及上限时接口返回部分图，且
`graph.complete` 为 `False`，`graph.truncation_reason` 明确说明截断原因。当前接口
只生成图结构，不执行死锁、活锁或其他图上性质分析。详细结构见
[Type 操作语义与状态图](document/TYPE_OPERATIONAL_SEMANTICS.md)。

常用可选参数：

- `initial_states`：单分量传一个 mapping；并行系统按源码分量顺序传等长的
  mapping 序列；省略时每个分量使用空状态；
- `path_condition`：`bool` 或符合项目表达式语法的字符串；
- `z3_timeout_ms`：每条 Z3 义务的超时；
- `keymaerax_timeout_seconds`：本次 KeYmaera X 调用的超时覆盖。

初态只允许出现 Gamma 中声明为 `BasicType` 的键，可以是真子集；未知键、共享
参数键和 `ContinuousType` 声明标签会被拒绝。

### 输出模式

TypeConstructor 和 TypeChecker 两个源码接口都支持：

- `output="none"`：默认，不打印；
- `output="result"`：打印最终结论；成功时显示可信类型，`unknown` 且构造完整时
  显示完整候选类型及“不可信”标记，其他失败显示原因和部分进度；
- `output="full"`：打印原始输入、环境摘要、内部构造完成说明、规则轨迹、FOL/dL
  公式、每条证明器结论、未决义务和最终可信性；不会打印或返回 Process AST
  对象/repr。

凡日志中实际展示 Type 的位置，都统一使用
[用户 Type 输入语法](document/TYPE_INPUT_SYNTAX.md) 的规范文本，例如
`type delay(1) then empty`。不再同时打印旧数学简写或 Python AST `repr`；因此
`Type 源码 :` 后面的内容可以直接复制到完整输入的 `type` 分节中。简单类型保持
单行；并行、内部选择和 Angelic 分支块会自动换行，并统一使用四个空格缩进。

也可以使用 `OutputMode.NONE/RESULT/FULL`。`stream=` 可把文本写入文件或
`io.StringIO`；输出模式只改变展示，不改变解析、推导、证明或异常语义。发生
`false` 时，`full` 显示实际停止点以前的轨迹；发生 `unknown` 时，它显示继续推导
得到的全部轨迹、完整候选类型（如能形成）以及仍待证明的公式。`none` 不打印，
但异常对象仍提供相应格式化信息。

## 完整用户输入格式

TypeConstructor 输入固定按以下顺序书写：

```ebnf
constructor_source ::= gamma [parameters] theta process EOF
typed_source       ::= gamma [parameters] theta process type EOF
```

`check_hcsp_type(...)` 使用第二种形式；其中 `type` 分节的语法见
[用户 Type 输入语法](document/TYPE_INPUT_SYNTAX.md)。

最小示例：

```hcsp
gamma()
theta()
process {{skip}}
```

包含连续变量、参数和多槽通信的形状：

```hcsp
gamma(
    x: Real,
    v: Real,
    plant: continuous(x, v)
)
parameters(bound: Real) where(bound >= 0)
theta(
    data: channel(position: Real, velocity: Real)
        where(position <= bound)
)
process {{data!(x, v)}}
```

完整 EBNF、运算优先级、ODE/递归/事件写法见：

- [完整环境与 Process 输入语法](document/GAMMA_THETA_INPUT_SYNTAX.md)
- [Process 与表达式语法](document/HCSP_INPUT_SYNTAX.md)

## 支持范围与输入限制

### 名称与类型

- 状态变量、参数、通道、binder 和进程变量统一使用 ASCII
  `[A-Za-z_][A-Za-z0-9_]*`，且不能使用语法保留字；Unicode 和 NFKC 兼容字符
  不会被自动归一化接受。
- 标量类型只有 `Bool`、`Nat`、`Int`、`Rational`、`Real`。
- Gamma 的状态项只能是一个 `BasicType`；`continuous(x1,...,xn)` 是独立的
  ODE 向量登记，不是 tuple 状态值。其成员必须在同一 Gamma 中另行声明为
  `Real`。
- 参数只能具有 `BasicType`，必须与 Gamma 不交，并且在 HCSP 中只读。
- 通道至少有一个槽；多槽表示一次通信中的若干独立标量，不表示 tuple 值。

### 表达式

- 支持 Bool/十进制数值、变量、圆括号、简单函数调用、`+ - * / % ** ^`、
  六种比较、比较链、`not/and/or`，以及 `!`、`&&`、`||`、`<->` 记号。
- `^` 与 `**` 都表示高优先级、右结合乘方。
- 不支持字符串、Unit、tuple/list/dict/set、属性、下标、lambda、关键字参数、
  表达式级条件、赋值表达式或任意 Python 代码。
- 语法树本身不区分数值式与 Bool 式；具体位置所需类型和除零、平方根定义域等
  条件由类型构造过程中的表达式静态类型检查处理。

### Process、递归与 ODE

- Process 以论文 Section 2.1 的核心结构为基础，并使用项目确认的多标量通信
  扩展；顶层多个语句块表示并行系统。
- 构造结果必须满足项目实现的 Assumption 2.1 与通信守卫递归 Assumption 2.2。
- `mu X invariant(phi) {...}` 必须提供递归不变量；`call X` 表示回边。
- 每个 `ode(...)` 必须提供 `delay`；有限值必须是可静态计算的非负有理数，
  也允许 `inf`。`safety` 省略时为 `true`，`interrupt` 省略时表示无中断。
- 每个 ODE 自动具有局部时钟 `t`，入口为 0、导数为 1；`t` 可在该 ODE 的
  方程右端、domain 和 safety 中读取，不进入 Gamma，也不能写在 `dot` 左端。
- 非空 ODE 的用户方程左端集合必须与 Gamma 中某个 `continuous(...)` 集合恰好
  相等；隐藏时钟不参与比较。
- 不支持 `wait(d)`。有限等待请显式写空 flow ODE，例如
  `ode(flow(), domain(t < 1), delay(1))`。

### 证明边界

- Z3 处理项目支持的一阶逻辑片段；不可靠或不支持的翻译不会猜测结论。
- 非平凡 ODE 证明由 KeYmaera X 完成；证明器缺失、超时或公式超出可靠翻译
  子集时得到 `unknown`。规则构造继续进行，但最终候选会作为不可信异常结果，
  不会被当作成功。
- Python callable、原始 Z3 项和自定义 dL 回调只属于内部开发接口，不能写入
  用户 source。

## TypeConstructor 与 TypeChecker

**TypeConstructor** 接收带批注 HCSP、Gamma、Theta 和参数环境，自行构造
Type AST；**TypeChecker** 在这些输入后再接收一个用户 Type，以该 Type 为规则
结论递归检查。两者共享表达式语义、符号上下文、证明义务和证明后端，但不会互相
冒充：Checker 不借用 Constructor 的完整构造结果完成检查。

顶层 Python 包名 ``hcsp_typechecker`` 作为整个行为类型项目的总命名空间保留，
同时容纳 TypeConstructor 与 TypeChecker；具体实现类仍是内部接口，包根只导出
上述两个面向用户的函数和公共结果/异常类型。

## 示例、测试与更多文档

- `python demo.py`：运行若干简短示例和一个复杂 ODE/delay 示例，展示完整的单接口流程；
- `python type_demo.py`：把 `demo.py` 第六个复杂 ODE 先交给 TypeConstructor，
  再把生成的缩进 Type 源码交回 TypeChecker，验证完整往返；
- `python new_demo.py`：分别演示 TypeChecker 接受正确 Type 和拒绝错误 Type；
- `python -m unittest discover -s tests -p "test_*.py"`：运行全部自动化测试；
- `python scripts/check_repository.py`：运行隐私扫描、环境检查和全部测试。

内部架构、真实转换算法、证明后端和测试职责不放在根 README 中，统一从
[项目文档索引](document/INDEX.md) 进入。
