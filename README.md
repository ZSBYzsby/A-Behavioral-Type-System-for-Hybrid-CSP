# HCSP Behavioral Type Constructor and Checker

本项目把一份带 Parameters、Gamma、Theta 与批注 HCSP Process 的用户文本直接
转换为正式 Type AST，并证明构造过程中产生的必要公式；也可以由用户给出 Type，
再按同一套项目规则检查它是否成立；已有 Type AST 还可以按照 Table 3 生成完整可达
状态转移图，并在完整图上检查论文定义的死锁自由和活锁自由。普通用户使用包根的
`construct_hcsp_type(...)`、`check_hcsp_type(...)`、
`build_type_transition_graph(...)` 与 `analyze_type_lock_freedom(...)`；解析时
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
`HCSPUntrustedTypeConstructionError`、`HCSPTypeCheckingError`、
`HCSPTypeTransitionGraphError`、`HCSPTypeLockAnalysisError`、`OutputMode`、
`TypeConstructionErrorKind`、
`TypeCheckingErrorKind`、`TypeTransitionGraphErrorKind`、`HCSPErrorDetail`、
`TypeLockAnalysisErrorKind`、`TypeAST`、`TypeTransitionGraph`、
`LockFreedomReport`、`construct_hcsp_type`、`check_hcsp_type`、
`build_type_transition_graph` 和 `analyze_type_lock_freedom`。

第一次使用建议先阅读[公共接口使用手册](document/PUBLIC_API_GUIDE.md)。该手册按
实际函数签名逐项说明参数、成功返回、异常字段、输出模式、Constructor 的
`unknown` 候选、Checker 的失败语义，以及 `TypeTransitionGraph` 的遍历方式。
本 README 保留足以开始调用的摘要和输入限制；论文规则与内部实现继续放在
`document/` 的专题文档中。需要审计实现时，请从
[当前代码的实现语义与论文规则落地方式](document/IMPLEMENTATION_SEMANTICS.md)
开始：它逐条写明前端 lowering、运行上下文、Table 2 规则、ODE 候选、证明调度、
Constructor/Checker 差异和 Table 3 图算法，不以“与论文一致”概括工程实现。

四个业务接口的职责和数据流如下：

| 接口 | 输入 | 成功返回 | 失败方式 |
|---|---|---|---|
| `construct_hcsp_type` | `gamma [parameters] theta process` 完整文本 | 构造并证明可信的 `TypeAST` | 输入错误、构造失败或带不可信候选的构造异常 |
| `check_hcsp_type` | `gamma [parameters] theta process type` 完整文本 | 经规则和证明确认的用户 `TypeAST` | 输入、Type 结构、规则应用或证明异常 |
| `build_type_transition_graph` | 已有的 `TypeAST` | 完整可达的 `TypeTransitionGraph` | Type 非法、规范化失败或图规模超限异常 |
| `analyze_type_lock_freedom` | 第三接口的完整图 | 含结论和反例的 `LockFreedomReport` | 图对象非法或不是完整可达闭包 |

典型调用顺序是：

```text
HCSP 完整文本 --construct_hcsp_type--> 可信 TypeAST --build_type_transition_graph--> 完整图 --analyze_type_lock_freedom--> 锁自由报告
带 Type 的完整文本 --check_hcsp_type--> 已验证 TypeAST --build_type_transition_graph--> 完整图 --analyze_type_lock_freedom--> 锁自由报告
```

Constructor 与 Checker 是两条独立业务路径：Checker 不先调用 Constructor 再比较
结果。第三个接口也不会重新检查 Type 是否对应某个 HCSP；需要可信来源时，应使用
前两个接口的正常返回值。

四个接口共同接受 `output="none" | "result" | "full"`：`none` 完全不打印；
`result` 只打印最终摘要；`full` 打印输入、规则/证明轨迹或完整状态图。传入
`stream=` 时文本写入该文本流；未传时写入标准输出。输出档位只影响展示，不改变
返回值、证明结论或异常。以下签名中的类型名均可从包根稳定接口获得，内部 AST
构造器和后端对象不需要由普通用户操作。

### 1. 从 HCSP 构造 Type

```python
construct_hcsp_type(
    source,
    *,
    source_name="<input>",
    initial_states=None,
    path_condition=True,
    output="none",
    stream=None,
    z3_timeout_ms=5000,
    keymaerax_timeout_seconds=None,
) -> TypeAST
```

- `source`：字符串，必须依次包含 `gamma`、可选 `parameters`、`theta` 和
  `process`，不能包含用户 `type` 分节。
- `source_name`：只用于日志和输入诊断中的来源名称，不参与数学语义。
- `initial_states`：可选部分初态。单 Process 可传一个变量到值的 mapping；并行
  Process 必须按源码顶层分量顺序传入等长的 mapping 序列。默认每个分量初态为空。
- `path_condition`：初始路径条件，可传 `bool` 或符合项目表达式语法的字符串；
  默认恒真。
- `z3_timeout_ms`：每次 Z3 查询的毫秒超时。
- `keymaerax_timeout_seconds`：可选的 KeYmaera X 单次证明秒数；省略时使用环境配置。
- 成功返回：已经完成规则构造且全部必要公式均证明为真的 `TypeAST`。
- 失败：源码解析失败抛 `HCSPInputError`；环境、规则或已否证公式导致构造失败时抛
  `HCSPTypeConstructionError`；形成完整 Type 但仍有 `unknown` 义务时抛其子类
  `HCSPUntrustedTypeConstructionError`，候选只通过 `error.untrusted_type` 明确取得。

`initial_states` 的两个合法形状如下；并行输入不接受一个合并后的全局 mapping：

```python
single = {"x": 0}
parallel = ({"left_state": 0}, {"right_state": 0})
```

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
    # result 模式已经打印诊断；这里按应用需要记录 error.kind 或决定退出码。
    pass
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
示例一样先捕获它。`BottomType` 是 Type AST 中正式的不可达行为：有限 ODE 使用
`T-\unrhd` 时，它表示规则保证不会抵达的 deadline 后继；无限时延也隐含同样的
不可达后继。它不是构造失败占位。`EmptyType` 则表示可达但没有通信行为的正常
过程类型，两者会由 Constructor 生成并由 Checker 分别检查。

类型构造异常还提供机器可读的 `kind`、`phase`、`rule`、`location` 和
`details`。`kind` 是 `TypeConstructionErrorKind`：环境不合法、规则推导失败、
证明被否证和证明未决分别为 `environment`、`derivation`、`proof-failed`、
`proof-unknown`。每个 `HCSPErrorDetail` 保存消息、规则、判断位置；证明错误还
保存公式类别、实际公式和证明器说明。调用方无需解析中文日志来判断失败种类。

### 2. 检查用户给定的 Type

```python
check_hcsp_type(
    source,
    *,
    source_name="<input>",
    initial_states=None,
    path_condition=True,
    output="none",
    stream=None,
    z3_timeout_ms=5000,
    keymaerax_timeout_seconds=None,
) -> TypeAST
```

- `source`：字符串，必须依次包含 `gamma`、可选 `parameters`、`theta`、
  `process` 和用户给定的 `type`；`type` 使用项目的规范 Type 输入语法。
- `source_name`、`initial_states`、`path_condition` 和两个证明超时参数与
  `construct_hcsp_type` 含义完全相同。
- 成功返回：输入中给出的同一个 `TypeAST`。成功意味着 Type 结构被完整消费、每层
  规则均适用，而且全部 FOL/dL 前提均已证明；Checker 不调用 Constructor 生成一个
  Type 再作整棵比较。
- 失败：词法、语法和输入结构错误抛 `HCSPInputError`；环境错误、Type 结构不匹配、
  规则不适用、公式为 `false` 或证明为 `unknown` 均抛
  `HCSPTypeCheckingError`。可读取 `kind`、`rule`、`details`、
  `type_structure_matched` 等字段区分失败阶段。

在同一份输入末尾增加规范 `type` 段，然后调用 TypeChecker 入口：

```python
from hcsp_typechecker import HCSPTypeCheckingError, check_hcsp_type

typed_source = """
gamma()
parameters(limit: Int) where(limit >= 0)
theta(ch: channel(value: Int) where(0 <= value and value <= limit))
process {{ch!(limit)}}
type forever interrupt angelic {
    ch! -> empty
}
"""

try:
    checked_type = check_hcsp_type(typed_source, output="result")
except HCSPTypeCheckingError as error:
    # result 模式已经打印摘要；机器逻辑可读取 error.kind、rule 和 details。
    pass
```

TypeChecker 不会先运行 TypeConstructor 再比较两棵完整 Type AST。它以用户 Type
作为每个 Table 2 judgment 的给定结论，递归拆解 Process 与 Type：静默语句检查
同一个后继类型；通信、delay、递归和并行检查对应的 Type 子树；多元内部选择与
外部中断按分支数和书写顺序逐项检查。每条规则产生的 FOL/dL premise 仍使用与
TypeConstructor 相同的可信证明机制。Type 结构不匹配、静态规则失败或必要公式
为 `false/unknown` 时抛出 `HCSPTypeCheckingError`；只有全部规则和证明均为
`true` 时返回用户给定的正式 `TypeAST`。

TypeChecker 完整支持可选的共享全局参数段 `parameters(...) where(H)`。参数声明
和约束 `H` 会被转换为 `ParameterEnvironment`，并加入相关 FOL/dL 前提的证明
背景；参数既可以出现在 HCSP 表达式中，也可以出现在 Theta refinement 中，还可
由并行分量共同读取。参数始终只读，不能作为赋值目标、通信输入目标、ODE 左端或
初始状态键。上例的通道 refinement 只有借助 `limit >= 0` 才能证明，因此也直接
展示了 TypeChecker 确实使用参数约束，而不只是解析并保存参数字段。省略参数段
等价于空参数声明与恒真约束。

`HCSPTypeCheckingError.kind` 使用独立的 `TypeCheckingErrorKind`，区分
`environment`、`type-mismatch`、`rule-application`、`proof-failed` 和
`proof-unknown`。异常还公开 `phase`、`rule`、`location`、`details`、
`type_mismatch_detected`，以及三值的 `type_structure_matched`：`True` 表示给定
Type 已被完整消费，`False` 表示明确发现结构不匹配，`None` 表示环境或前提失败
使检查尚未完整走完。

Checker 的 `unknown` 与 Constructor 不同：它会继续检查剩余 Type 结构，以便完整
报告后续是否匹配，但最终仍抛 `HCSPTypeCheckingError`，不会返回一个“暂时接受”的
Type。

### 3. 从 Type AST 生成 Table 3 状态图

```python
build_type_transition_graph(
    type_ast,
    *,
    max_states=None,
    max_transitions=None,
    output="none",
    stream=None,
) -> TypeTransitionGraph
```

- `type_ast`：由 Constructor 返回、由 Checker 验证，或通过内部审计工具得到的正式
  `TypeAST`；本接口不接收 HCSP/Type 文本。
- `max_states`、`max_transitions`：可选的严格正整数规模上限。达到上限即失败，
  不返回可能被误认为完整结果的部分图；`None` 表示不设置该项上限。
- 成功返回：完整 `TypeTransitionGraph`。`initial_state` 是初始状态编号，`states`
  保存规范化 Type 状态，`transitions` 保存动作、目标状态和 Table 3 推导证据。
- 输出：`result` 打印状态/边数量和初始规范 Type；`full` 打印所有状态、所有转移及
  规则证据。
- 失败：输入不是正式 Type、规范化失败或超过图规模上限时抛
  `HCSPTypeTransitionGraphError`；`kind`、`phase` 和相关限制字段可供程序处理。

最常见的程序化遍历方式是：

```python
initial = graph.states[graph.initial_state]
for edge in graph.outgoing(initial.id):
    print(edge.label, edge.target, edge.derivations)
```

状态的 `type_ast` 是规范化后的可读展示代表；真正的等递归判重由后端循环项图完成。

```python
from hcsp_typechecker import (
    HCSPTypeTransitionGraphError,
    TypeTransitionGraph,
    TypeTransitionGraphErrorKind,
    build_type_transition_graph,
    construct_hcsp_type,
)

type_ast = construct_hcsp_type(source)
graph = build_type_transition_graph(type_ast, output="full")

assert isinstance(graph, TypeTransitionGraph)
print(len(graph.states), len(graph.transitions))
```

需要由程序区分第三个接口的失败原因时，可以捕获统一异常：

```python
try:
    graph = build_type_transition_graph(
        type_ast,
        max_states=1000,
        max_transitions=5000,
        output="result",
    )
except HCSPTypeTransitionGraphError as error:
    if error.kind is TypeTransitionGraphErrorKind.SIZE_LIMIT:
        print(error.limit_name, error.limit)
```

该接口先把已有 Type AST 单向转换为操作语义专用的规范化 Type AST，再以初态为
根穷尽基于 Table 3 的关键-deadline约化关系。规范化会消除并行排列和空单位元差异，
把内部选择按结合/交换/幂等律展平排序去重，把外部选择按交换/幂等律排序去重，并
使用 De Bruijn index 消除递归绑定变量改名差异。图判重时还会把递归绑定转换为
有限循环项图并做双模拟最小化，所以 `mu t.T` 与任意有限次展开不会形成重复状态。
Table 3 直接作用于最小循环项图；每个图结点的规范化 AST 仅由该项图确定性生成，
用于输出而不参与转移计算。项目不提供转回原 Type AST 的接口。

返回的 `TypeTransitionGraph` 包含连续编号的 `states`、去重后的 `transitions` 和
`initial_state`。每个状态携带可读的规范 Type 展示代表；每条边携带 `tau` 或
`time(d, ready=R)` 标签。若不同规则实例产生同一源、标签和目标，边只保留一条，
但其 `derivations` 会保存所有不同证据。可用 `graph.outgoing(state_id)` 按稳定顺序
取得一个状态的全部出边。

规范状态输出沿用 `parallel`、`empty`、`internal`、`delay`、`forever` 和
`angelic`；根部增加 `normalized` 标记。由于规范内部选择已经展平，分支不再套
圆括号；匿名递归写成 `mu { ... }`，De Bruijn 引用写成
`recursion_position(index)`。该格式只用于展示和审计，不接受用户输入，也没有
parser。语法见
[规范化 Type AST 输出格式](document/NORMALIZED_TYPE_OUTPUT_SYNTAX.md)。

`build_type_transition_graph(..., output="result")` 输出图规模和初始规范
类型；`output="full"` 输出全部规范状态、边标签及 Table 3 规则证据。两个内部
formatter 不从包根公开。完整格式见
[状态迁移图输出语法](document/TYPE_TRANSITION_GRAPH_OUTPUT_SYNTAX.md)。

时间转移只前进到所有分量共同等待时的下一个最早有限 deadline；若全部分量均可
无限等待，则生成 infinity 时间边。`EmptyType` 是并行单位元，不会阻塞其他分量；
并行保留重复分量。相同源、标签和目标由多种规则实例得到时，图只保存一条边，
但在 `derivations` 中保存全部不同推导证据。

`max_states` 和 `max_transitions` 可限制状态爆炸。第三个接口使用
`HCSPTypeTransitionGraphError` 统一报告错误；其 `kind` 可区分 `invalid-type`、
`invalid-limit`、`normalization` 与 `size-limit`，`phase` 指明失败阶段。触及任一上限
时不会返回没有分析意义的部分图。详细结构见
[Type 操作语义与状态图](document/TYPE_OPERATIONAL_SEMANTICS.md)。

### 4. 在完整状态图上检查死锁和活锁

```python
analyze_type_lock_freedom(
    graph,
    *,
    output="none",
    stream=None,
) -> LockFreedomReport
```

第四接口只接受第三接口返回的完整 `TypeTransitionGraph`，不会重新读取 HCSP 或
重新生成图。它以 `O(|V|+|E|)` 时间完成两项判断：

- 死锁：存在可达迁移 `time(infinity, ready=R)` 且 `R` 非空；
- 活锁：只保留 `tau` 边后，可达子图中存在有向环，即存在无限静默推导。

报告提供 `deadlock_free`、`livelock_free`、`lock_free` 三个布尔属性。性质不成立
不是运行错误：接口仍正常返回 `LockFreedomReport`，其中 `deadlock_witness` 保存
初态到无限等待边的路径，`livelock_witness` 保存初态到静默环的路径和有限环。
`EmptyType` 的无出边终态、`BottomType` 的无出边状态以及
`time(infinity, ready={})` 都不满足上述死锁定义；带正时间边的环也不是活锁。

```python
from hcsp_typechecker import analyze_type_lock_freedom

report = analyze_type_lock_freedom(graph, output="full")
if not report.lock_free:
    print(report.deadlock_witness, report.livelock_witness)
```

输入不是图或含有初态不可达的孤立状态时，接口抛
`HCSPTypeLockAnalysisError`；性质为假时不抛异常。算法使用 CSR 出边索引、BFS 和
显式栈 DFS，不使用 Python 递归，也不会为大图复制邻接对象。详细设计、反例结构和
复杂度见[死锁/活锁分析](document/TYPE_LOCK_ANALYSIS.md)。

常用可选参数：

- `initial_states`：单分量传一个 mapping；并行系统按源码分量顺序传等长的
  mapping 序列；省略时每个分量使用空状态；
- `path_condition`：`bool` 或符合项目表达式语法的字符串；
- `z3_timeout_ms`：每条 Z3 义务的超时；
- `keymaerax_timeout_seconds`：本次 KeYmaera X 调用的超时覆盖。

初态只允许出现 Gamma 中声明为 `BasicType` 的键，可以是真子集；未知键、共享
参数键和 `ContinuousType` 声明标签会被拒绝。

### 输出模式

四个稳定业务接口都支持同一组输出模式：

- `output="none"`：默认，不打印；
- `output="result"`：Constructor/Checker 打印最终结论；图接口打印图规模与初始
  规范 Type；锁分析接口打印三项性质和紧凑反例。构造 `unknown` 且类型完整时显示候选 Type 及“不可信”标记；
- `output="full"`：Constructor/Checker 打印原始输入、规则轨迹、FOL/dL 公式和
  最终可信性；图接口打印全部规范状态、边标签和 Table 3 推导证据；锁分析接口打印
  可达前缀、无限等待边或静默环及相关状态。Constructor
  与 Checker 都不会打印或返回 Process AST 对象/repr。

凡日志中实际展示 Type 的位置，都统一使用
[用户 Type 输入语法](document/TYPE_INPUT_SYNTAX.md) 的规范文本，例如
`type delay(1) then empty`。不再同时打印旧数学简写或 Python AST `repr`；因此
`Type 源码 :` 后面的内容可以直接复制到完整输入的 `type` 分节中。简单类型保持
单行；并行、内部选择和 Angelic 分支块会自动换行，并统一使用四个空格缩进。

也可以使用 `OutputMode.NONE/RESULT/FULL`。`stream=` 可把文本写入文件或
`io.StringIO`；输出模式只改变展示，不改变解析、推导、证明、图遍历或异常语义。发生
`false` 时，`full` 显示实际停止点以前的轨迹；发生 `unknown` 时，它显示继续推导
得到的全部轨迹、完整候选类型（如能形成）以及仍待证明的公式。`none` 不打印，
但异常对象仍提供相应格式化信息。

不要解析中文日志来决定程序分支。输入异常读取 `phase/line/column`；Constructor 和
Checker 异常读取 `kind/phase/rule/location/details`；图异常读取
`kind/phase/limit_name/limit`。全部字段、取值和捕获顺序见
[公共接口使用手册的异常章节](document/PUBLIC_API_GUIDE.md#7-统一异常处理)。

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
  TypeConstructor 与 TypeChecker 都会把参数约束加入证明背景；并行分量可以共享
  读取参数，但赋值、通信输入、ODE 演化和初始状态均不能改写参数。
- 通道至少有一个槽；多槽表示一次通信中的若干独立标量，不表示 tuple 值。

### 表达式

- 支持 Bool/十进制数值、变量、圆括号、简单函数调用、`+ - * / % ** ^`、
  六种比较、比较链、`not/and/or`，以及 `!`、`&&`、`||`、`<->` 记号。
- `^` 与 `**` 都表示高优先级、右结合乘方。
- 不支持字符串、Unit、tuple/list/dict/set、属性、下标、lambda、关键字参数、
  表达式级条件、赋值表达式或任意 Python 代码。
- 语法树本身不区分数值式与 Bool 式；具体位置所需类型和除零、平方根定义域等
  条件由 Constructor/Checker 共用的表达式静态类型检查处理。

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
- 三个公开接口的核心树遍历使用显式工作栈，不通过提高 Python 递归上限规避
  问题；长顺序 Process、深 Type continuation 和规范化项图转换因此不会仅因
  Python 调用栈深度而失败。项目还以端到端压力测试保证 TypeConstructor 在已测
  规模生成的深通信 Type 和大并行 Type，可以先按正式 Type 语法交给 TypeChecker
  重新验证，也可以原样交给状态图接口；前三个树/图构造接口不存在不同的人工 AST
  深度上限，第四接口也不使用递归图搜索。
  状态图仍可用 `max_states`/`max_transitions` 控制 Table 3 可达状态爆炸，达到
  上限时按接口契约整体报错。

### 证明边界

- Z3 处理项目支持的一阶逻辑片段；不可靠或不支持的翻译不会猜测结论。
- 非平凡 ODE 证明由 KeYmaera X 完成；证明器缺失、超时或公式超出可靠翻译
  子集时得到 `unknown`。Constructor 会继续规则构造，并把完整候选作为不可信
  异常结果；Checker 会继续核对剩余 Type 结构，最后以 `proof-unknown` 报错。
  两者都不会把未验证结论当作成功。
- Python callable、原始 Z3 项和自定义 dL 回调只属于内部开发接口，不能写入
  用户 source。

## TypeConstructor 与 TypeChecker

**TypeConstructor** 接收带批注 HCSP、Gamma、Theta 和参数环境，自行构造
Type AST；**TypeChecker** 在这些输入后再接收一个用户 Type，以该 Type 为规则
结论递归检查。两者共享表达式语义、符号上下文、证明义务和证明后端，但不会互相
冒充：Checker 不借用 Constructor 的完整构造结果完成检查。

顶层 Python 包名 ``hcsp_typechecker`` 作为整个行为类型项目的总命名空间保留，
同时容纳 TypeConstructor 与 TypeChecker；具体实现类仍是内部接口，包根只导出
这两个 Table 2 面向用户的函数及其公共结果/异常类型。Table 3 图接口保持为前文
单独说明的第三项稳定业务能力。

## 示例、测试与更多文档

- `python demo.py`：运行若干简短示例和一个复杂 ODE/delay 示例，展示完整的单接口流程；
- `python type_demo.py`：把 `demo.py` 第六个复杂 ODE 先交给 TypeConstructor，
  再把生成的缩进 Type 源码交回 TypeChecker，验证完整往返；
- `python new_demo.py`：分别演示 TypeChecker 接受正确 Type 和拒绝错误 Type；
- `python graph_demo.py`：从几个并行、递归和多 deadline Type AST 构造完整
  Table 3 状态图；
- `python -m unittest discover -s tests -p "test_*.py"`：运行全部自动化测试；
- `python scripts/check_repository.py`：运行隐私扫描、环境检查和全部测试。
- [公共接口使用手册](document/PUBLIC_API_GUIDE.md)：四个接口的逐参数契约、完整
  异常字段、输出模式和可复制示例；

内部架构、真实转换算法、证明后端和测试职责不放在根 README 中，统一从
[项目文档索引](document/INDEX.md) 进入。
