# 共享参数、Gamma、Theta 与 HCSP Process 统一输入语法参考

本文档定义一次完整的用户输入如何把共享只读参数、类型环境
`Gamma`、通道环境 `Theta` 和一个 HCSP Process 系统绑定在同一份源码中，
以及它们如何转换为项目现有的数据
模型。这套 concrete syntax 已由内部统一解析器实现。普通用户通过包根的
`construct_hcsp_type(...)` 构造类型，或在末尾增加 `type` 分节后通过
`check_hcsp_type(...)` 检查给定类型；其中 Process
语句和表达式的详细子语法仍见
[`HCSP_INPUT_SYNTAX.md`](HCSP_INPUT_SYNTAX.md)。

当前代码不为输入文本建立第二套环境 AST：

- 可选的 `parameters(...) where(...)` 转换为现有
  `ParameterEnvironment`；
- 解析结果中的 `Gamma` 是只读 `Mapping[str, GammaType]`，其中每个值是
  `BasicType` 或 `ContinuousType`；
- 解析结果中的 `Theta` 是只读 `Mapping[str, ChannelType]`；
- Process 部分转换为项目现有的 `Process` 或 `Parallel` AST。

公共门面直接返回最终 `TypeAST`，不会暴露解析阶段生成的 Process AST。内部解析器
仍把四者作为同源数据交给 TypeConstructor，不需要为参数、Gamma、Theta 或 Process 再
建立第二套 AST。本文后续显示的 Python mapping 和节点构造形式只用于说明内部
转换结果，不是要求普通用户直接导入这些类。

## 1. 设计约定

- 完整输入固定按 `gamma`、可选 `parameters`、`theta`、`process` 的顺序书写；
  Gamma、Theta 和 Process 必须出现，无共享参数时可省略 `parameters`。
- `gamma(...)` 和 `theta(...)` 分别包围两种环境；空环境写成 `gamma()` 和
  `theta()`。
- 需要共享参数时写 `parameters(...)`；约束省略或显式写
  `where(true)` 都规范化为恒真背景。
- `process` 后必须给出一个非空 HCSP 系统；单分量和并行系统继续使用既有
  `process_system` 语法。
- 同一环境中的声明使用 `,` 分隔，最后一项后不写逗号。
- 环境不使用 `{...}`，使花括号继续只表示 HCSP 系统和可执行语句块。
- 环境不使用 `;`，使分号继续只表示 Process 语句的顺序执行。
- 类型名只有一种规范写法，并且区分大小写；不把 Python API 接受的类型别名暴露
  给用户输入层。
- 标识符统一采用 `[A-Za-z_][A-Za-z0-9_]*`。本语法中的关键字和规范类型名不能
  用作声明名。
- 空白和换行没有语义；注释沿用 HCSP 输入层的 `// ...` 和非嵌套
  `/* ... */`。
- `expr` 直接引用 `HCSP_INPUT_SYNTAX.md` 中已经实现的严格表达式语法。

## 2. 完整 EBNF

```ebnf
program_prefix
    ::= gamma
        [ parameters ]
        theta
        process


constructor_source
    ::= program_prefix
        EOF


gamma
    ::= "gamma" "("
            [
                gamma_entry
                { "," gamma_entry }
            ]
        ")"


gamma_entry
    ::= IDENT ":" gamma_type


gamma_type
    ::= basic_type
      | continuous_type


continuous_type
    ::= "continuous" "("
            identifier_list
        ")"


parameters
    ::= "parameters" "("
            [
                parameter_entry
                { "," parameter_entry }
            ]
        ")"
        [ "where" "(" expr ")" ]


parameter_entry
    ::= IDENT ":" basic_type


theta
    ::= "theta" "("
            [
                theta_entry
                { "," theta_entry }
            ]
        ")"


theta_entry
    ::= IDENT ":" channel_type


channel_type
    ::= "channel" "("
            channel_slot
            { "," channel_slot }
        ")"
        [ "where" "(" expr ")" ]


channel_slot
    ::= IDENT ":" basic_type


basic_type
    ::= "Bool"
      | "Nat"
      | "Int"
      | "Rational"
      | "Real"


identifier_list
    ::= IDENT
        { "," IDENT }


process
    ::= "process" process_system


process_system
    ::= "{"
            statement_block
            { "," statement_block }
        "}"
```

`statement_block`、各类 `statement`、ODE、通信和 `expr` 的完整产生式由
`HCSP_INPUT_SYNTAX.md` 定义。`constructor_source` 供 TypeConstructor 使用；
TypeChecker 在同一个 `program_prefix` 后追加必填 `type` 分节，完整形式见
[TYPE_INPUT_SYNTAX.md](TYPE_INPUT_SYNTAX.md)。Gamma、参数、Theta 和 Process 的
单独解析入口即使为了测试而保留，也只是片段级 API，不是完整 source 的替代写法。

## 3. Gamma 的转换规则

### 3.1 标量声明

```hcsp
gamma(
    ready: Bool,
    count: Nat,
    offset: Int,
    ratio: Rational,
    position: Real
)
```

逐项转换为：

```python
{
    "ready": BasicType.BOOL,
    "count": BasicType.NAT,
    "offset": BasicType.INT,
    "ratio": BasicType.RATIONAL,
    "position": BasicType.REAL,
}
```

用户输入层只接受 `Bool`、`Nat`、`Int`、`Rational`、`Real` 这五种规范类型名。
不支持 `String`、`Unit`、`Any`、tuple 类型，也不接受 `bool`、`integer`、`R`
等 Python API 便捷别名。

### 3.2 连续演化向量声明

```hcsp
gamma(
    p: Real,
    v: Real,
    a: Real,
    vehicle_motion: continuous(p, v, a)
)
```

转换为：

```python
{
    "p": BasicType.REAL,
    "v": BasicType.REAL,
    "a": BasicType.REAL,
    "vehicle_motion": ContinuousType(("p", "v", "a")),
}
```

`vehicle_motion` 是一个独立的 ODE 向量声明名，不是可以出现在表达式里的标量
变量。`continuous(p, v, a)` 也不会隐式建立 `p`、`v`、`a`；每个成员必须在同一
Gamma 中另行声明为 `Real`。成员声明可以写在向量声明之前或之后，解析器应在读完
整个 Gamma 后统一检查。

连续向量成员按集合解释：成员的书写顺序不影响与 ODE 方程左端的匹配。不同的
continuous 声明可以共享部分或全部成员；当前模型也允许不同声明名登记完全相同的
向量。一个具有用户方程的 ODE 必须与某个 continuous 声明的完整成员集合恰好
匹配；只匹配真子集或真超集都不成立。

ODE 自动建立的隐藏局部时钟 `t` 不属于用户演化向量，不写入 Gamma，也不参加
成员集合比较。因此 `t` 不能写入 `continuous(...)` 的成员列表；普通标量声明
仍可使用名称 `t`，但它在 ODE 自身的 flow、domain 和 safety 中会被隐藏局部时钟
遮蔽。没有用户方程的空 flow ODE 同样不需要 continuous 声明。

### 3.3 Gamma 的结构检查

- 同一 Gamma 中的所有键共享一个命名空间，标量声明名和 continuous 声明名都
  必须唯一；重复声明应定位到第二次出现的位置并报错，不能由字典静默覆盖。
- continuous 的成员列表必须非空，成员必须互异且都是合法 IDENT。
- 每个 continuous 成员都必须另有一个同名的 `Real` 标量声明。
- 隐式 ODE 时钟名 `t` 不能作为 continuous 的成员。
- continuous 声明本身不携带安全性质。连续演化需要保持的性质只来自对应 ODE
  的 `safety(...)` 批注。
- `gamma()` 是合法的空 Gamma。

## 4. 共享只读参数的转换规则

```hcsp
parameters(
    end: Real,
    vmax: Real,
    amin: Real,
    amax: Real
) where(
    end >= 0 and vmax >= 0 and amin < 0 and amax >= 0
)
```

该分节转换为：

```python
ParameterEnvironment(
    {
        "end": BasicType.REAL,
        "vmax": BasicType.REAL,
        "amin": BasicType.REAL,
        "amax": BasicType.REAL,
    },
    parse_annotated_expression(
        "end >= 0 and vmax >= 0 and amin < 0 and amax >= 0"
    ),
)
```

参数只能使用五种 `BasicType`，不支持 `continuous(...)`。参数声明名必须
互异，且不能同时出现在 Gamma 中。约束的自由变量只能是当前分节声明的
参数；其 Bool 类型、有定义性和可满足性由 TypeConstructor 统一验证。省略整个
`parameters` 分节等价于空声明和恒真约束。

共享参数不属于 Gamma 状态，因此可被多个并行 Process 同时读取，不会
违反并行状态分离。该例外只在解析完整 source、已知参数声明时用于构造
`Parallel` AST；内部低层 `parse_annotated_hcsp(...)` 和直接 `Parallel(...)` 仍保持原来的严格
Assumption 2.1 检查。赋值、输入目标、ODE 左端或初始 state 对参数的修改始终
由 TypeConstructor 拒绝。

## 5. Theta 的转换规则

### 5.1 单槽通道

```hcsp
theta(
    sensor: channel(value: Real) where(0 <= value and value <= 100),
    tick: channel(code: Nat)
)
```

转换结果等价于：

```python
{
    "sensor": ChannelType(
        (BasicType.REAL,),
        refinement=parse_annotated_expression("0 <= value and value <= 100"),
        binders=("value",),
    ),
    "tick": ChannelType(
        (BasicType.NAT,),
        refinement=True,
        binders=("code",),
    ),
}
```

省略 `where(...)` 时，refinement 恒为 `true`。显式书写 `where(true)` 也应规范化
为同一个恒真表示，避免产生两种没有语义差异的内部结构。

### 5.2 多槽通道

```hcsp
theta(
    state: channel(position: Real, velocity: Real)
        where(position >= 0 and velocity >= 0),
    result: channel(index: Nat, accepted: Bool)
)
```

第一项转换为：

```python
ChannelType(
    (BasicType.REAL, BasicType.REAL),
    refinement=parse_annotated_expression(
        "position >= 0 and velocity >= 0"
    ),
    binders=("position", "velocity"),
)
```

槽位顺序具有语义，必须与 `ch?(x1, ..., xn)` 的目标顺序和
`ch!(e1, ..., en)` 的载荷顺序一一对应。这里的多槽签名不是 tuple 值类型；每个
槽位仍单独承载一个 `BasicType` 标量。

### 5.3 refinement 中名称的作用域

- 每个槽位名都是当前 channel 声明的局部 binder，只在该声明自己的
  `where(...)` 中有效。
- 同一个 channel 内的 binder 必须互异；不同 channel 可以重复使用同一 binder
  名称。
- binder 在自己的 refinement 中优先于外层同名 Gamma 标量或共享只读参数，
  即采用通常的局部绑定遮蔽规则。
- refinement 除了引用本通道的 binders，还可以引用 Gamma 中的标量变量以及
  完整类型判断提供的共享只读参数。
- `ContinuousType` 的声明名没有标量值，不能作为 refinement 表达式中的变量。
- refinement 最终必须具有 `Bool` 类型。统一解析器只负责把语法合法的内容保存为
  `Expr`；未绑定名称、类型错误和表达式未定义条件在通道实际参与 T-In/T-Out 时
  由 TypeConstructor 中的表达式静态类型检查和证明检查处理。当前实现不会主动
  遍历验证未使用通道的 refinement，因此
  “source 解析成功”本身不代表整个 Theta 已完成语义检查。

### 5.4 Theta 的结构检查

- 同一 Theta 中的通道名必须唯一；重复声明不能静默覆盖。
- `channel(...)` 至少包含一个槽位，因此不支持零参数的 unit 通信。
- 每个槽位只能使用 `BasicType`，不能使用 `continuous(...)` 或 tuple 类型。
- binder 数量由语法天然与槽位数量一致，并且同一通道内必须互异。
- `where(...)` 省略时使用 `true`，给出时必须按项目严格 `expr` 语法解析成
  `Expr`。
- 用户文本只能产生项目 `Expr` refinement；Python callable 和原始 Z3 公式属于
  程序化 API 能力，不属于本 concrete syntax。
- `theta()` 是合法的空 Theta。

## 6. 完整示例

```hcsp
gamma(
    p: Real,
    v: Real,
    mode: Int,
    enabled: Bool,
    vehicle_motion: continuous(p, v)
)

parameters(
    limit: Real
) where(limit >= 0)

theta(
    command: channel(acceleration: Real)
        where(-2 <= acceleration and acceleration <= 2),
    state: channel(position_out: Real, velocity_out: Real),
    switch: channel(next_mode: Int, active: Bool)
        where(0 <= next_mode and next_mode <= 3)
)

process {
    {
        command?(a);
        ode(
            flow(
                dot p = v,
                dot v = a
            ),
            domain(t <= 1),
            safety(p * p + v * v <= 100),
            delay(1)
        );
        state!(p, v)
    }
}
```

该输入在内部解析为四项同源数据。共享参数转换为
`ParameterEnvironment({"limit": BasicType.REAL}, limit >= 0)`，其他两个环境分别为：

```python
gamma = {
    "p": BasicType.REAL,
    "v": BasicType.REAL,
    "mode": BasicType.INT,
    "enabled": BasicType.BOOL,
    "vehicle_motion": ContinuousType(("p", "v")),
}

theta = {
    "command": ChannelType(
        (BasicType.REAL,),
        parse_annotated_expression("-2 <= acceleration and acceleration <= 2"),
        ("acceleration",),
    ),
    "state": ChannelType(
        (BasicType.REAL, BasicType.REAL),
        True,
        ("position_out", "velocity_out"),
    ),
    "switch": ChannelType(
        (BasicType.INT, BasicType.BOOL),
        parse_annotated_expression("0 <= next_mode and next_mode <= 3"),
        ("next_mode", "active"),
    ),
}
```

内部 `ParsedHCSPSource.process` 字段保存由 `process {...}` 生成的正式 Process
AST；它不是字符串，也不会复制一套新的进程节点定义。该内部记录只在
`parse_hcsp_source(...)` 与 TypeConstructor 之间传递，不是公共接口的返回值。

## 7. 完整输入入口与内部片段接口

TypeConstructor 用户只调用一次包根构造接口：

```python
from hcsp_typechecker import construct_hcsp_type

type_ast = construct_hcsp_type(
    source,
    source_name="example.hcsp",
    initial_states=None,
    path_condition=True,
    output="full",
)
```

接口在内部把同一份 source 的参数、Gamma、Theta 和 Process AST 绑定后立即进入
类型构造；这些中间对象不会交给普通调用者。调用者不需要、也不能通过包根构造
内部判断、`TypeConstructionRequest` 或内部解析记录。

不含 `type` 段时由 TypeConstructor 主动构造类型；在同一 source 后追加
`type configuration_type` 时，由 TypeChecker 检查给定 Type。Type 段语法见
[TYPE_INPUT_SYNTAX.md](TYPE_INPUT_SYNTAX.md)，检查算法见
[TYPE_CHECKER.md](TYPE_CHECKER.md)。

两个公共接口的参数、输出模式、返回值和异常只在
[README 的稳定用户接口](../README.md#稳定用户接口) 与
[完整功能参考](PROJECT_FUNCTION_REFERENCE.md#公共接口的输入和输出) 中集中说明，
本语法文档不再复制这些展示层规则。

内部仍有以下实现入口：

```python
from hcsp_typechecker.frontend.annotated_hcsp_syntax import parse_annotated_hcsp
from hcsp_typechecker.frontend.type_constructor_frontend import parse_hcsp_source
from hcsp_typechecker.frontend.typing_context_syntax import parse_typing_context
from hcsp_typechecker.backend.type_constructor import construct_type
```

`parse_hcsp_source(...)` 返回内部 `ParsedHCSPSource`，
`parse_typing_context(...)` 只解析 `gamma [parameters] theta` 前缀，
`parse_annotated_hcsp(...)` 只解析 `process_system` 片段，`construct_type(...)`
接受内部 `TypeConstructionRequest`。
它们只用于
实现、测试和论文规则审计，不从包根公开，也不属于用户兼容性承诺。

内部实现不会边解析边无条件覆盖最终字典：它保留声明 token，在写入前检查重复键，
并在 Gamma 读完后统一检查 continuous 的向前引用、重复成员和成员 Real 类型。
所有顶层部分共享同一个 token 流，没有先按文本切段，因此注释、全局行列位置和
错误指示范围保持一致。
