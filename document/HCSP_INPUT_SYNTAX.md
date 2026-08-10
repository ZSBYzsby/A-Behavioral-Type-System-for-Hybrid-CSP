# HCSP Process 与表达式输入语法参考

本文档定义完整用户输入中 `process` 部分使用的 HCSP 系统、语句和表达式子语法，
以及这些片段如何转换为项目已有的 Process AST 和 `Expr` AST。包含 Gamma、Theta
和 Process 的唯一完整 `source` 根语法见
[`GAMMA_THETA_INPUT_SYNTAX.md`](GAMMA_THETA_INPUT_SYNTAX.md)。

本文件中的 Process/Expr 子语法已经由内部输入层实现，且不会改变项目中 Python
AST 节点的语义。普通用户不单独调用片段解析器，而是把本语法放在完整 source 的
`process` 分节中。没有 `type` 分节时调用 `construct_hcsp_type(...)`；需要检查
用户给定类型时追加 `type` 分节并调用 `check_hcsp_type(...)`。下面先展示构造入口：

```python
from hcsp_typechecker import construct_hcsp_type

source = """
gamma()
theta(ch: channel(value: Real), out: channel(value: Real))
process {{ch?(x); out!(x)}}
"""

type_ast = construct_hcsp_type(source, source_name="example.hcsp")
```

解析失败会抛出 `HCSPInputError`，错误信息包含词法或语法阶段、源文件名、行列位置
和源码指示符。`parse_annotated_hcsp(...)`、`parse_annotated_expression(...)` 和直接 AST 构造器仍保留
给实现、测试与语法审计，但属于内部开发接口，不从包根导出，也不承诺兼容性。
手工修改完整 Gamma、Theta、Process 输入并查看最终 Type AST 时，
在仓库根目录编辑并运行 `python demo.py`。

## 1. 总体约定

- 一个 `process_system` 由一个或多个非空语句块组成。
- `process_system` 中只有一个语句块时，该语句块就是整个顺序进程。
- `process_system` 中有多个语句块时，这些语句块互相并行。
- 同一语句块中的语句使用 `;` 连接，表示顺序组合。
- 最后一条语句后不写 `;`。
- `{...}` 只用于整个系统和可执行语句块。
- `(...)` 用于参数、条件、批注以及 ODE 的具名配置。
- `,` 用于分隔并行进程、通信参数、函数参数、ODE 方程和 ODE 中断分支。
- 空白和换行本身没有语义。
- 支持 `//` 单行注释和非嵌套的 `/* ... */` 块注释。

## 2. Process 语法

```ebnf
process_source
    ::= process_system EOF


process_system
    ::= "{"
            statement_block
            { "," statement_block }
        "}"


statement_block
    ::= "{"
            statement
            { ";" statement }
        "}"


statement
    ::= skip_statement
      | assignment_statement
      | assertion_statement
      | input_action
      | output_action
      | process_call
      | if_statement
      | choice_statement
      | recursion_statement
      | ode_statement


skip_statement
    ::= "skip"


assignment_statement
    ::= IDENT ":=" expr


assertion_statement
    ::= "assert" "(" expr ")"


input_action
    ::= IDENT "?"
        "(" identifier_list ")"


output_action
    ::= IDENT "!"
        "(" expression_list ")"



process_call
    ::= "call" IDENT


if_statement
    ::= "if"
        "(" expr ")"
        statement_block
        "else"
        statement_block


choice_statement
    ::= "choose"
        statement_block
        "or"
        statement_block
        { "or" statement_block }


recursion_statement
    ::= "mu" IDENT
        "invariant"
        "(" expr ")"
        statement_block


ode_statement
    ::= "ode" "("

            flow_clause
            ","

            domain_clause
            ","

            [ safety_clause "," ]

            delay_clause

            [ "," interrupt_clause ]

        ")"


flow_clause
    ::= "flow" "("
            [
                ode_equation
                { "," ode_equation }
            ]
        ")"


ode_equation
    ::= "dot" IDENT "=" expr


domain_clause
    ::= "domain"
        "(" expr ")"


safety_clause
    ::= "safety"
        "(" expr ")"


delay_clause
    ::= "delay"
        "(" duration ")"


interrupt_clause
    ::= "interrupt" "("
            event_branch
            { "," event_branch }
        ")"


event_branch
    ::= "on"
        communication_action
        statement_block


communication_action
    ::= input_action
      | output_action


identifier_list
    ::= IDENT
        { "," IDENT }


expression_list
    ::= expr
        { "," expr }


duration
    ::= finite_duration
      | "inf"


finite_duration
    ::= rational_constant_expression


rational_constant_expression
    ::= rational_additive_expression


rational_additive_expression
    ::= rational_multiplicative_expression
        {
            ( "+" | "-" )
            rational_multiplicative_expression
        }


rational_multiplicative_expression
    ::= rational_unary_expression
        {
            ( "*" | "/" )
            rational_unary_expression
        }


rational_unary_expression
    ::= ( "+" | "-" ) rational_unary_expression
      | rational_power_expression


rational_power_expression
    ::= rational_primary_expression
        [
            ( "**" | "^" )
            rational_unary_expression
        ]


rational_primary_expression
    ::= integer_literal
      | real_literal
      | "(" rational_constant_expression ")"
```

有限时延表达式不允许变量、函数、布尔运算、比较、取模或 `inf`。其最终结果必须非负；除数必须非零；乘方指数必须是整数。`inf` 只能通过 `duration` 的独立分支用于普通 ODE 的 `delay`。

## 3. 表达式语法

Process 语法中出现的每个 `expr` 都使用本节定义的统一表达式语法。语法层不分别定义数值表达式和布尔公式；表达式的实际类型由后续类型检查判断。

```ebnf
expr
    ::= or_expression


or_expression
    ::= and_expression
        { or_operator and_expression }


or_operator
    ::= "or"
      | "||"


and_expression
    ::= not_expression
        { and_operator not_expression }


and_operator
    ::= "and"
      | "&&"


not_expression
    ::= not_operator not_expression
      | comparison_expression


not_operator
    ::= "not"
      | "!"


comparison_expression
    ::= additive_expression
        {
            comparison_operator
            additive_expression
        }


comparison_operator
    ::= "=="
      | "!="
      | "<"
      | "<="
      | ">"
      | ">="
      | "<->"


additive_expression
    ::= multiplicative_expression
        {
            additive_operator
            multiplicative_expression
        }


additive_operator
    ::= "+"
      | "-"


multiplicative_expression
    ::= unary_expression
        {
            multiplicative_operator
            unary_expression
        }


multiplicative_operator
    ::= "*"
      | "/"
      | "%"


unary_expression
    ::= unary_arithmetic_operator unary_expression
      | power_expression


unary_arithmetic_operator
    ::= "+"
      | "-"


power_expression
    ::= primary_expression
        [
            power_operator
            unary_expression
        ]


power_operator
    ::= "**"
      | "^"


primary_expression
    ::= literal
      | IDENT
      | function_call
      | "(" expr ")"


function_call
    ::= IDENT
        "("
            [ argument_list ]
        ")"


argument_list
    ::= expr
        { "," expr }
        [ "," ]


literal
    ::= boolean_literal
      | integer_literal
      | real_literal


boolean_literal
    ::= "true"
      | "false"


integer_literal
    ::= decimal_digits


real_literal
    ::= decimal_digits "." [ decimal_digits ] [ exponent ]
      | "." decimal_digits [ exponent ]
      | decimal_digits exponent


exponent
    ::= ( "e" | "E" )
        [ "+" | "-" ]
        decimal_digits


decimal_digits
    ::= DIGIT
        { DIGIT }
```

`true` 和 `false` 不区分大小写。规范打印统一使用小写形式。

为避免恶意或误写的巨大字面量在精确有理数转换时耗尽内存，实现额外限制单个
数值最多含 4096 位有效数字，十进制指数绝对值不超过 10000。超出限制会产生
带源码位置的 lexical 诊断，不会泄漏宿主 Python 数值异常。

## 4. 标识符和保留字

```ebnf
IDENT
    ::= ( ASCII_LETTER | "_" )
        { ASCII_LETTER | DIGIT | "_" }
```

等价的正则表达式是：

```text
[A-Za-z_][A-Za-z0-9_]*
```

状态变量、通道名、进程变量和函数名使用同一条词法规则，并区分大小写。HCSP 关键字和表达式关键字不能作为标识符。

当前保留字包括：

```text
skip assert call if else choose or mu invariant
ode flow dot domain safety delay interrupt on
true false inf not and
None
```

完整 source 还保留环境分节和环境类型所需的下列名称：

```text
gamma parameters theta process continuous channel where
Bool Nat Int Rational Real
```

这些名称属于完整输入层，不能再作为 Process 中的普通 IDENT。公共入口
`construct_hcsp_type(...)` 所调用的完整解析流程与内部片段解析器共享同一份
保留字表，因此不会在不同解析路径把同一源码名称解释成不同 token。

其中 `None` 是“保留但非法”的词，只用于给出明确的“不支持空值”诊断；它不属于
任何字面量产生式。小写 `none` 仍可作为普通、区分大小写的标识符。

## 5. 运算符优先级和结合性

从高到低：

| 优先级 | 形式 | 结合性 |
|---|---|---|
| 1 | 圆括号、函数调用 | — |
| 2 | `**`、`^` | 右结合 |
| 3 | 一元 `+`、一元 `-` | 右结合 |
| 4 | `*`、`/`、`%` | 左结合 |
| 5 | `+`、`-` | 左结合 |
| 6 | `==`、`!=`、`<`、`<=`、`>`、`>=`、`<->` | 链式比较 |
| 7 | `not`、`!` | 右结合 |
| 8 | `and`、`&&` | 左到右收集为同一个多元结点 |
| 9 | `or`、`||` | 左到右收集为同一个多元结点 |

例如：

```text
-x ** 2       = -(x ** 2)
(-x) ** 2     = (-x) ** 2
x ** y ** z   = x ** (y ** z)
not x < y     = not (x < y)
a or b and c  = a or (b and c)
```

链式比较保存在一个 `CompareExpr` 中：

```text
0 <= x < limit
```

表示逐段关系的合取：

```text
0 <= x and x < limit
```

## 6. Process 输入的语义约定

### 6.1 顶层并行

```text
lower_source({P}) = P

lower_source({P1, ..., Pn})
    = Parallel.of(P1, ..., Pn), n >= 2
```

外层列表是非空、有序列表，不是数学集合；不进行去重，并保留用户书写顺序。

### 6.2 顺序组合

```text
lower_block({P1; ...; Pn})
    = Sequence.of(P1, ..., Pn)
```

对于内部选择，块中位于选择之后的语句是所有分支的公共后继。解析器必须直接构造当前项目使用的多元 `InternalChoice`，不能先构造二元选择再包一层普通 `Sequence`。

### 6.3 通信

- `ch?(x1, ..., xn)` 接收一个或多个独立标量。
- `ch!(e1, ..., en)` 发送一个或多个独立标量表达式。
- 输入变量必须互不相同。
- 参数列表不能为空，不支持 unit 通信。
- 多个参数不构成 tuple 值。

### 6.4 递归

- `mu X invariant(phi) { ... }` 必须显式提供递归不变量。
- 无非平凡不变量时写 `invariant(true)`。
- `call X` 构造进程变量引用 `Var("X")`。
- 递归作用域、通信守卫、尾位置及 Assumption 2.1/2.2 由 AST 构造和
  TypeConstructor 阶段继续验证。

### 6.5 ODE

- `flow(...)`、`domain(...)` 和 `delay(...)` 必须出现。
- `safety(...)` 可以省略；省略时自动补为 `true`。
- `interrupt(...)` 可以省略；省略时构造 `EmptyEvent()`，表示连续演化过程中没有通信中断。
- 只要写出 `interrupt(...)`，其中就必须至少有一个事件分支；不接受 `interrupt()`。
- `flow()` 合法，表示没有用户声明的连续变量方程。
- ODE 方程左端写成 `dot x`，例如 `dot x = v`。
- 同一个 `flow` 中的方程左端必须互不相同。
- 每个 ODE 自动建立隐藏局部时钟 `t`，初值为 `0`，导数为 `1`。
- `t` 可以用于方程右端、`domain` 和 `safety`，但不能写在用户方程左端。
- 隐式时钟不计入用户连续变量向量，也不进入中断分支或 ODE 外部后继的作用域。
- 有限 `delay` 必须求值为非负有理数；普通 ODE 还允许 `delay(inf)`。
- 不支持 `wait(d)` 语法糖。若要表示有限等待，应显式写
  `ode(flow(), domain(t < d), delay(d))`；若它位于语句块末尾，构造器将其
  正常结束解释为隐式 `skip`，因此得到 `delay(d).0`。

## 7. Expr AST 对应关系

| 输入形式 | AST 结点 |
|---|---|
| 布尔、整数、实数字面量 | `Literal` |
| `x` | `Variable` |
| `not e`、`!e`、`+e`、`-e` | `UnaryExpr` |
| `+`、`-`、`*`、`/`、`%` | `BinaryExpr` |
| `**`、`^` | `BinaryExpr("**", ...)` |
| `and`、`&&`、`or`、`||` | `BooleanExpr` |
| 单个或链式比较 | `CompareExpr` |
| `f(e1, ..., en)` | `CallExpr` |

表达式语法本身不执行类型检查。例如，解析器能够构造 `1 and 2` 的表达式树，但后续类型检查必须因为 `and` 的操作数不是 Bool 而拒绝它。

函数调用在解析阶段允许任意普通函数名和任意数量的位置参数。后续证明后端只对部分函数具有专门语义；不能翻译的函数形式应在表达式静态类型检查或证明阶段产生明确诊断。

## 8. 明确不支持的表达式

- 表达式级条件：`a if B else b`；
- 属性访问和方法调用：`plant.temperature`、`obj.f(x)`；
- 下标、切片和动态调用：`array[i]`、`functions[i](x)`；
- lambda、生成器和各种推导式；
- tuple、list、dict 和 set 值；
- 字符串、bytes、复数、`None` 和省略号字面量；
- 关键字参数、`*args` 和 `**kwargs`；
- `//`、`@`、`<<`、`>>`、`&`、`|` 等未定义运算；
- `in`、`not in`、`is`、`is not`；
- 表达式内部赋值、海象运算和解构左值。

## 9. Process 片段示例

```hcsp
{
    {
        start?(x);
        x := x + 1;

        ode(
            flow(
                dot x = v,
                dot v = -x
            ),
            domain(t <= 1 and x <= limit),
            safety(x <= limit),
            delay(1),
            interrupt(
                on reset?(new_x, new_v) {
                    x := new_x;
                    v := new_v
                },
                on report!(x, v) {
                    skip
                }
            )
        );

        finished!(x)
    },

    {
        start!(initial_value);
        finished?(result)
    }
}
```

## 10. 公共完整入口与内部兼容边界

普通用户完整的 TypeConstructor 入口是：

```python
from hcsp_typechecker import construct_hcsp_type

type_ast = construct_hcsp_type(
    complete_source,
    source_name="example.hcsp",
    output="none",  # 也可为 "result" 或 "full"
)
```

它解析 `GAMMA_THETA_INPUT_SYNTAX.md` 规定的 `constructor_source`，在内部构造
参数、Gamma、Theta 和 Process AST，随后进行类型构造与公式证明。若追加 `type`
分节，则调用 `check_hcsp_type(...)` 递归检查用户 Type；详见
[TYPE_CHECKER.md](TYPE_CHECKER.md)。两个接口的输出和异常协议集中记录在
[README](../README.md#稳定用户接口)，本语法文档不重复维护。

以下入口只属于内部开发与审计层：

```python
from hcsp_typechecker.frontend.annotated_hcsp_syntax import (
    parse_annotated_expression,
    parse_annotated_hcsp,
)
from hcsp_typechecker.frontend.type_constructor_frontend import parse_hcsp_source
```

- `parse_annotated_hcsp(...)` 解析一个非空 `process_system` 片段并 lower 为 Process/Parallel AST；
- `parse_annotated_expression(...)` 使用第 3 节的严格表达式文法构造 `Expr`；
- `parse_hcsp_source(...)` 是公共门面内部共用的 program prefix 解析实现，返回内部
  `ParsedHCSPSource`；
- `parse_expr(...)` 是 Process 表达式节点的旧便捷构造入口。

这些名称不从包根公开，其签名和返回记录均不属于用户兼容性承诺。它们共享以下
实现边界：只接受 ASCII `IDENT` 和本文档列出的十进制数值；`^` 与 `**` 都按
高优先级、右结合乘方解析并保存为 `BinaryExpr("**", ...)`；函数实参允许空表和
尾逗号，通信参数和顶层块列表不允许尾逗号；`&&`、`||`、`!`、`<->` 和大小写
不敏感的布尔字面量都规范化为对应 Expr 节点。

内部 `parse_expr(...)` 还保留部分旧 Python 数值字面量便利输入，但与严格前端
共享 ASCII IDENT 边界，并在 Python 建树前把 `^` token 改写成真正的 `**`，
不会继承异或优先级、左结合性或 Python 的 Unicode/NFKC 标识符扩展。
