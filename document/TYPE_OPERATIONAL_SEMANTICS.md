# 规范化 Type AST 与 Table 3 状态转移图

本文说明当前项目如何把一个已有正式 Type AST 转换为规范状态，并穷尽论文
Section 4.4 Table 3 的可达转移。当前范围只包含规范化数据结构、图数据结构和图生成；
不包含死锁、活锁、终止性或其他图上性质分析。

## 稳定接口

```python
from hcsp_typechecker import (
    TypeAST,
    TypeTransitionGraph,
    build_type_transition_graph,
)

graph: TypeTransitionGraph = build_type_transition_graph(
    type_ast,
    output="full",
)
```

`result` 模式打印图规模、完整性和初始规范类型；上面的 `full` 模式打印所有状态、
边标签和规则证据。规范 Type 格式没有 parser，也不是用户 Type 输入语法，定义见
[规范化 Type AST 只读输出语法](NORMALIZED_TYPE_OUTPUT_SYNTAX.md)。

完整图文本语法见
[状态迁移图只读输出语法](TYPE_TRANSITION_GRAPH_OUTPUT_SYNTAX.md)。

完整签名为：

```python
build_type_transition_graph(
    type_ast: TypeAST,
    *,
    max_states: int | None = None,
    max_transitions: int | None = None,
    output: OutputMode | str = OutputMode.NONE,
    stream: TextIO | None = None,
) -> TypeTransitionGraph
```

规模上限必须是正整数。达到任一上限时返回已构造的部分图，设置
`complete=False`，并用 `truncation_reason` 说明原因。

## 数据结构与后端边界

```text
data_structures/
├── type_ast/                  原始 Type AST
├── normalized_type_ast/       Table 3 规范状态 AST 与单向转换
├── regular_type_term_graph/   等递归正规树的有限循环项图与状态键
└── type_transition_graph/     状态、边、标签和推导证据

backend/
└── type_operational_semantics/
    ├── regular_tree.py        正规项图转换、双模拟最小化与稳定状态键
    ├── table3.py              循环项图上的全部一步转移
    └── graph_builder.py       BFS 可达闭包与同边证据合并

frontend/
├── normalized_type_syntax/    贴近用户 Type 风格的规范状态只读输出
└── type_transition_graph_syntax/  状态、边、标签与规则证据的只读输出
```

数据结构层不导入后端。Table 3 算法不会写入 TypeConstructor 或 TypeChecker，也不
依赖 Gamma、Theta、共享参数或证明器。

## 单向规范化

项目只提供：

```python
normalize_type_ast(TypeAST) -> NormalizedConfigurationType
```

不提供规范化 AST 转回原 Type AST 的入口。原 AST 继续服务于用户 Type 语法、
TypeConstructor 和 TypeChecker；规范化 AST 只服务于状态图。

规范配置根保存一个非空、稳定排序的过程分量元组。单分量表示顺序类型，多分量
表示并行类型；正常空配置恰好保存一个 `NormalizedEmptyType`。

## 规范等价

并行组合执行：

- 结合律展平；
- 交换律排序；
- 删除 `EmptyType` 单位元；
- 保留重复分量，不使用幂等律。

内部选择执行：

- 结合律展平；
- 交换律排序；
- 幂等律去重；
- 去重后仅一支时直接返回该分支。

外部选择执行：

- 交换律排序；
- 幂等律删除完全相同的通信分支；
- 零、单、多分支分别使用 NoInterrupt、Input/Output、ExternalChoice 节点。

递归绑定删除原变量名并使用 De Bruijn index。规范化拒绝自由 TypeVar；有限零时延、
Bottom、内部选择中的 Empty 分支等具有操作语义意义的结构不会被提前消除。

这里的规范化 AST 仍然是有限语法树，因此其 Python 结构相等性有意区分
``mu t.T`` 和一次展开后的 ``T[mu t.T/t]``。但 Table 3 不在这棵展示树上执行；
它在下一层的有限循环项图上执行，所以折叠与展开写法不会产生不同的出边。

## 等递归正规树状态键

状态图判重在规范化 AST 之上再建立一层内部表示：

1. 把每个 ``mu`` binder 与 De Bruijn 引用解析成有向回边；
2. 得到不含 ``mu``/TypeVar 节点的有限循环 ``RegularTypeTermGraph``；
3. 对有限图做最大双模拟分区和商图最小化；
4. 对内部/外部选择重新执行展平、交换和幂等规范化；
5. 删除配置根的 Empty 单位元、稳定排序根，但保留并行分量重数；
6. 生成不可变、可哈希的 ``EquiRecursiveStateKey``。

因此 ``mu t.T``、``T[mu t.T/t]`` 以及任意有限次展开共享同一个状态编号。
通道名、输入/输出方向、delay 时长、顺序子结构和并行重数仍是可观察结构，不会被
该商错误合并。最小项图既是状态键，也是 Table 3 的正式运行状态。为了输出，后端
会从项图确定性生成一棵带 De Bruijn ``mu`` 的规范 AST 代表；该代表不参与推导。

## 图模型

`TypeTransitionGraph` 保存：

- `initial_state`：初始状态编号；
- `states`：连续编号的 `TypeState` 元组，每项携带由其项图确定性生成的规范配置
  AST 展示代表；
- `transitions`：`TypeTransition` 元组；
- `complete` 与 `truncation_reason`：可达闭包是否完整。

边标签只有两类：

- `SilentTransitionLabel` 对应不耗时的 `mathcal T -> mathcal T'`；
- `TimedTransitionLabel(duration, ready)` 对应 `d,R` 时间转移。

有限时间使用精确 `Fraction`，无穷时间使用独立 `InfiniteTime.VALUE`。ready set 是
`frozenset[ReadyAction]`，每个动作保存通道和输入/输出方向。

一条边可保存多个 `TransitionDerivation`。这表示不同分量/分支配对产生相同源、标签
和目标时，图结构合并重复边，但仍保留不同 Table 3 规则实例供审计。

## Table 3 单步规则

后端直接读取每个最小循环项图状态并枚举：

1. 内部选择的每个不同非 Bottom 分支；
2. 每个零时延 timeout；
3. 任意两并行分量之间的全部互补通信分支配对；
4. 满足共同等待前提时唯一的下一个关键 deadline 时间步。

论文的 ``[P-mu]`` 在这一实现层被编译为项图回边：通信 continuation 可以直接回到
已有节点，无需先构造 ``T[mu t.T/t]`` 这样的临时 AST。因此状态边证据只保存真正
发生的内部选择、通信、timeout 或时间规则，不再保存行政性的递归展开步骤。

零时延 timeout 与边界处可用通信若同时满足 Table 3 前提，两条边都会保留。

## 关键 deadline

若全部非空并行分量均可等待，且不同分量的 ready set 中不存在互补动作，则收集
全部有限正剩余时延并取最小值。所有分量共同前进该时长：有限 delay 减去它，无穷
delay 保持不变。

如果全部分量都是无穷 delay，则生成 infinity 时间边。若存在零时延、内部选择、
Bottom 或其他不能等待的分量，不生成共同时间边。互补通信已经可用时也不允许时间
越过该同步点。

## 图遍历

图生成器以最小 ``EquiRecursiveStateKey`` 为状态本体进行 BFS。Table 3 的目标项图
在每一步后立即删除不可达节点、重新最小化并用作目标状态键；已访问的递归状态形成
回边而不复制语法树。每个 ``TypeState`` 的规范 AST 只负责展示。遍历直到队列为空，
或达到用户指定的状态/边上限。
