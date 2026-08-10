# 用户 Type 输入语法

本文件定义未来 TypeChecker 使用的用户 Type 具体语法。当前项目已经提供对应的
内部前端：`hcsp_typechecker.frontend.type_syntax.parse_type_source` 与
`hcsp_typechecker.frontend.type_syntax.format_type_source`。它们只在内部开发层可用，
暂不属于包根公共接口。

解析和规范化输出满足：

```text
parse_type_source(format_type_source(T)) == T
```

其中 `T` 是任意 `ConfigurationType`。格式化器输出唯一的规范拼写；解析器还接受
有限/无穷时延中显式写出的空 Angelic Type。

## 1. 完整输入中的 Type 段

```ebnf
typed_source
    ::= gamma_section ";"
        [ parameters_section ";" ]
        theta_section ";"
        process_section ";"
        type_section
        EOF

type_section
    ::= "type" configuration_type
```

前四段沿用 [完整 HCSP 输入语法](GAMMA_THETA_INPUT_SYNTAX.md)。本文件只定义最后
的 `type_section`。

## 2. Type 语法

```ebnf
configuration_type
    ::= process_type
      | "parallel" "{"
            configuration_type "," configuration_type
            { "," configuration_type }
        "}"

process_type
    ::= "empty"
      | "bottom"
      | "internal" "{"
            process_type "," process_type { "," process_type }
        "}"
      | "delay" "(" finite_duration ")"
            [ "interrupt" angelic_type ]
            "then" process_type
      | "forever" [ "interrupt" angelic_type ]
      | "mu" IDENT "." process_type
      | IDENT

angelic_type
    ::= "angelic" "{"
            [ communication_branch { "," communication_branch } ]
        "}"

communication_branch
    ::= IDENT "?" "->" process_type
      | IDENT "!" "->" process_type

finite_duration
    ::= NONNEGATIVE_INTEGER
      | NONNEGATIVE_INTEGER "/" POSITIVE_INTEGER
```

圆括号不属于 Type 的分组语法；嵌套完全由关键字、花括号、逗号、`then` 与 `->`
确定。

## 3. AST 对应与规范输出

| Type AST | 规范输出 |
|---|---|
| `EmptyType()` | `empty` |
| `BottomType()` | `bottom` |
| `InternalChoiceType(T1,...,Tn)` | `internal {T1, ..., Tn}` |
| `FiniteDelayType(d, NoInterruptType(), T)` | `delay(d) then T` |
| `FiniteDelayType(d, A, T)` | `delay(d) interrupt A then T` |
| `InfiniteDelayType(NoInterruptType())` | `forever` |
| `InfiniteDelayType(A)` | `forever interrupt A` |
| `MuType(X,T)` | `mu X. T` |
| `TypeVar(X)` | `X` |
| `ParallelType(T1,...,Tn)` | `parallel {T1, ..., Tn}` |

`A` 由 `angelic_type` 表示：

| Angelic Type AST | 规范输出 |
|---|---|
| `NoInterruptType()` | `angelic {}` |
| `InputType(ch,T)` | `angelic {ch? -> T}` |
| `OutputType(ch,T)` | `angelic {ch! -> T}` |
| `ExternalChoiceType(...)` | `angelic {branch1, ..., branchn}` |

`angelic {}` 是空中断集合 (A)，`empty` 是无可观察通信行为的过程类型 (T)，两者
不可互换。对于 delay，解析器允许：

```text
delay(1) then empty
delay(1) interrupt angelic {} then empty
```

二者都得到 `FiniteDelayType(1, NoInterruptType(), EmptyType())`；格式化时一律输出
第一种省略中断的形式。

`bottom` 被保留以无损表达正式 `BottomType` 节点。`FiniteDelayType` 不允许把它作为
自然到时后继；无穷时延的不可达 bottom 后继由 `InfiniteDelayType` 固定隐含。

## 4. 语法范畴边界

`AngelicType` 与 `ProcessType` 是不同的 Python 抽象层。`angelic {...}` 只能出现在
`interrupt` 后，不能单独作为 `type` 段的根。一个输入/输出过程行为由无穷时延节点
表示，例如：

```text
type forever interrupt angelic {ch? -> empty}
```

对应：

```python
InfiniteDelayType(InputType("ch", EmptyType()))
```
