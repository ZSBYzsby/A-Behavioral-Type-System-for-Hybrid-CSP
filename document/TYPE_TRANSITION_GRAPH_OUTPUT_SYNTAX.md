# Table 3 状态迁移图只读输出语法

`build_type_transition_graph(..., output="full")` 把构造结果一次性输出为稳定文本。
格式包含初始状态、图是否完整、全部规范状态、全部转移标签，以及每条边的
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
            "complete" "=" boolean
            [ "truncation" "=" STRING ]
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

状态右侧的 `normalized_type_output` 使用
[规范化 Type AST 只读输出语法](NORMALIZED_TYPE_OUTPUT_SYNTAX.md)。图节点按等递归
正规树判重，所以 `mu t.T` 与其有限展开共用一个 `state_id`；右侧文本打印该等价类
由最小循环项图确定性生成的规范 AST 展示代表。该展示树不参与状态判等或转移计算。

## 示例

```text
type transition graph {
    initial = S0
    complete = true
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

若图因 `max_states` 或 `max_transitions` 被截断，头部会显示
`complete = false`，并额外输出 `truncation = '...'`。因此部分图不会在文本展示中
被误认为完整可达闭包。
