# Table 3 状态迁移图只读输出语法

`build_type_transition_graph(..., output="full")` 把构造结果一次性输出为稳定文本。
格式包含初始状态、全部规范状态、全部转移标签，以及每条边的
Table 3 推导证据。底层 formatter 只服务接口内部展示和审计，不提供 parser，也
不允许用户用文本伪造状态图。

## 接口

```python
from hcsp_typechecker import build_type_transition_graph

graph = build_type_transition_graph(type_ast, output="full")
```

## 输出文法

```ebnf
graph_output
    ::= "type" "transition" "graph" "{"
            "initial" "=" state_id
            states_block
            transitions_block
        "}"

states_block
    ::= "states" "{" state_entry { state_entry } "}"

state_entry
    ::= state_id "=" normalized_type_output

transitions_block
    ::= "transitions" "{}"
      | "transitions" "{" transition { transition } "}"

transition
    ::= state_id "--" transition_label "-->" state_id
        "by" "{" derivation { derivation } "}"

transition_label
    ::= "tau"
      | "time" "(" time_duration ","
            "ready=" "{" [ ready_action { "," ready_action } ] "}"
        ")"

ready_action
    ::= IDENT "?" | IDENT "!"

time_duration
    ::= POSITIVE_INTEGER
      | POSITIVE_INTEGER "/" POSITIVE_INTEGER
      | "infinity"

derivation
    ::= RULE_NAME "(" [ derivation_arguments ] ")"
        [ "{" derivation { derivation } "}" ]

derivation_arguments
    ::= named_argument { "," named_argument }

named_argument
    ::= "components=" index_list
      | "branches=" index_list
      | "channel=" STRING

index_list
    ::= "[" NONNEGATIVE_INTEGER
        { "," NONNEGATIVE_INTEGER } "]"

state_id
    ::= "S" NONNEGATIVE_INTEGER
```

空格和换行不参与语义；formatter 固定使用四空格缩进。`tau` 表示不消耗时间的
转移。时间边中的 ready set 按信道名和方向稳定排序。相同图边的多份推导证据会
全部列在同一个 `by` 块中；递归或并行规则的前提证据嵌套在所属规则块中。

`components=[...]` 中的编号从零开始，指向该边源状态右侧
`normalized_type_output` 实际展示的并行分量。`branches=[...]` 同样从零开始，
指向相应可见分量中的内部选择或 Angelic 分支；通信规则中两个列表的同一位置组成
一个“参与分量—所选中断分支”对。编号不暴露循环项图的内部结点顺序，重复并行
分量也各自拥有独立的可见位置。

当前 `RULE_NAME` 及其证据含义为：

- `P-unrhd`：通信同步，保存两个分量、两个 Angelic 分支和通道；
- `P-triangleright`：零时延 timeout，保存发生 timeout 的分量；
- `P-sqcup`：内部选择，保存分量和被选分支；
- `P-unrhd-prime`：单分量时间推进；
- `P-parallel`：并行共同时间推进，`components` 与嵌套前提按同一顺序对应。

递归规则 `P-mu` 不单独出现在输出中。递归已经在状态身份中编译为项图回边，证据
编号针对经过前导递归展开后可执行的分量或分支；不会生成仅用于展开递归的行政边。

状态右侧的 `normalized_type_output` 使用
[规范化 Type AST 只读输出语法](NORMALIZED_TYPE_OUTPUT_SYNTAX.md)。图节点按等递归
正规树判重，所以 `mu t.T` 与其有限展开共用一个 `state_id`；右侧文本打印该等价类
由最小循环项图确定性生成的规范 AST 展示代表。该展示树不参与状态判等或转移计算。

## 示例

```text
type transition graph {
    initial = S0
    states {
        S0 = normalized type delay(2) then empty
        S1 = normalized type delay(0) then empty
        S2 = normalized type empty
    }
    transitions {
        S0 -- time(2, ready={}) --> S1 by {
            P-unrhd-prime()
        }
        S1 -- tau --> S2 by {
            P-triangleright(components=[0])
        }
    }
}
```

状态图输出永远表示完整的可达闭包。若构造过程达到 `max_states` 或
`max_transitions`，接口抛出 `HCSPTypeTransitionGraphError`，其 `kind` 为
`size-limit`，不会调用成功结果 formatter，也不会输出或返回部分图。错误文本由
第三个接口自己的 `result/full` 错误 formatter 负责，不属于本页定义的成功图语法。
`output="result"` 也不使用本页完整图文法，只输出状态数、边数和初始规范 Type。
