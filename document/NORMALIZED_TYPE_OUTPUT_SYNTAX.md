# 规范化 Type AST 只读输出语法

状态迁移图的每个 `TypeState` 都保存一个由其最小循环项图确定性生成的
`NormalizedConfigurationType` 展示代表。为了让用户
不必学习一套完全不同的 Type 写法，状态图接口的内部 formatter 尽量复用原用户
Type 语法，只在规范化真正改变结构的地方采用新的明确写法：根部使用
`normalized type`，扁平内部选择不再使用规则分块圆括号，匿名递归使用 `mu {T}`，
递归引用使用 `recursion_position(index)`。

这是一套**只读输出语法**：项目不解析该文本，不接受用户把它作为 Type 输入，也
不提供规范化 Type AST 到原 Type AST 的反向转换。用户给定 Type 仍使用
[原 Type 输入语法](TYPE_INPUT_SYNTAX.md)。

## 使用方式

```python
from hcsp_typechecker import build_type_transition_graph

graph = build_type_transition_graph(type_ast, output="result")
```

`result` 模式会在摘要末尾用本语法打印初始规范类型；`full` 模式会在每个状态条目
中使用本语法。底层 formatter 位于内部 frontend，不是包根用户接口。

规范化文本描述的是状态的可读代表，不是状态身份。状态身份由最小循环项图决定，
所以两棵展示 AST 即使因有限递归展开写法不同，也可能对应同一个图状态；公共接口
已经在输出前完成这种等递归合并。

## 输出文法

```ebnf
normalized_type_output
    ::= "normalized" "type" configuration_type

configuration_type
    ::= process_type
      | "parallel" "{" process_type { "," process_type } "}"

process_type
    ::= "empty"
      | "bottom"
      | recursion_position
      | "internal" "{" process_type
            "," process_type { "," process_type } "}"
      | "delay" "(" duration ")"
            [ "interrupt" angelic_type ]
            "then" process_type
      | "forever" [ "interrupt" angelic_type ]
      | "mu" "{" process_type "}"

recursion_position
    ::= "recursion_position" "(" NONNEGATIVE_INTEGER ")"

angelic_type
    ::= "angelic" "{" [ communication_branch
            { "," communication_branch } ] "}"

communication_branch
    ::= IDENT "?" "->" process_type
      | IDENT "!" "->" process_type

duration
    ::= NONNEGATIVE_INTEGER
      | NONNEGATIVE_INTEGER "/" POSITIVE_INTEGER
```

formatter 固定使用四空格缩进。有限有理时延使用最简分数；分母为 1 时只输出
整数。规范化内部选择已经展平成同一层多元节点，因此分支由花括号和逗号直接界定，
不再保留原 TypeChecker 为规则分块所需的圆括号。

`bottom` 与 `empty` 始终分开：前者是不可达/异常行为，不能发生 timeout；后者是
可达的正常空通信行为，并在并行根中作为单位元删除。`angelic {}` 只表示没有通信
中断，与两种过程后继都不是同一语法类别。

## 匿名递归与递归位置

规范化 AST 内部使用 De Bruijn index，不保存原来的递归变量名。因此 `mu` 输出为
匿名块，引用直接显示递归位置：

- `recursion_position(0)`：最近一层 `mu`；
- `recursion_position(1)`：再外一层 `mu`；
- 更大的数字依此向外计数。

例如，无论原类型写成：

```text
mu Loop. forever interrupt angelic { ch? -> Loop }
```

还是：

```text
mu Again. forever interrupt angelic { ch? -> Again }
```

规范输出都使用：

```text
mu {
    forever interrupt angelic {
        ch? -> recursion_position(0)
    }
}
```

嵌套递归中的 `recursion_position(1)` 不表示状态图编号，而表示从当前位置向外数
第二个 `mu` binder。

## 完整示例

```text
normalized type parallel {
    delay(3/2) interrupt angelic {
        reset? -> mu {
            forever interrupt angelic {
                again? -> recursion_position(0)
            }
        },
        report! -> empty
    } then internal {
        empty,
        bottom
    },
    forever
}
```

该文本继续使用用户熟悉的 `parallel`、`delay`、`angelic`、`internal`、`empty`、
`bottom`、`forever` 和 `mu`。规范化已经完成的排序、展平、去重、并行单位元删除
和 alpha 等价消除，会直接反映在分支顺序、分支数量及递归位置中。

状态图还会把 `mu t.T` 与 `T[mu t.T/t]` 按等递归正规树合并。只读 formatter 不把
原 Type AST，而是从规范循环项图生成一个稳定的 De Bruijn `mu` 展示树；因此同一个
状态编号始终只有一份展示文本，但单独比较两段输出文本不能代替等递归状态键。
