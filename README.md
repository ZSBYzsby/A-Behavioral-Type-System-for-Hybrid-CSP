# HCSP Behavioral Type Checker

本项目把一份带 Parameters、Gamma、Theta 与批注 HCSP Process 的用户文本转换为
Process AST，并按照项目实现的类型规则推导正式 Type AST。普通用户只需要包根的
两个接口；Process/Type AST 构造器、判断对象、证明义务和证明器适配器均属于内部
实现，不构成稳定调用协议。

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
得到 `unknown`。使用 `python -m hcsp_typechecker --require-keymaerax` 可把证明器
缺失视为环境错误。

## 两个稳定用户接口

```python
from hcsp_typechecker import (
    HCSPInputError,
    HCSPTypeError,
    infer_hcsp_type,
    parse_hcsp_program,
)

source = """
gamma(x: Int)
parameters(limit: Int) where(limit >= 0)
theta(ch: channel(value: Int) where(value <= limit))
process {{ch?(x); ch!(x)}}
"""

try:
    program = parse_hcsp_program(
        source,
        source_name="example.hcsp",
        output="result",
    )
    type_ast = infer_hcsp_type(program, output="result")
except HCSPInputError as error:
    print(error.format_diagnostic())
except HCSPTypeError as error:
    print(error.format_full())
```

### `parse_hcsp_program`

第一接口返回只读 `HCSPProgram`，其中同源绑定：

- `parameters`：共享只读参数声明和约束；
- `gamma`：状态类型与连续向量环境；
- `theta`：通道签名及 refinement 环境；
- `process_ast`：正式 Process 或 Parallel AST；
- `process_components`：按源码顺序展开的顶层 Process 分量。

该聚合对象是第二接口唯一接受的程序参数，避免用户把不同 source 的环境和 AST
误配。Gamma、Theta 在内部表示为只读有限映射，而不是另一套重复 AST。

### `infer_hcsp_type`

第二接口自动为 `process_components` 建立配置、分割 Gamma、加入共享参数背景并
执行证明。只有总体结论为 `true` 时才直接返回正式 `TypeAST`。`false` 或
`unknown` 会抛出 `HCSPTypeError`；异常保留 `verdict`、首要原因、已经形成的
分量类型和完整审计日志，不会用 `BottomType` 或候选类型冒充成功结果。

常用可选参数：

- `initial_states`：单分量传一个 mapping；并行系统按源码分量顺序传等长的
  mapping 序列；省略时每个分量使用空状态；
- `path_condition`：`bool` 或符合项目表达式语法的字符串；
- `z3_timeout_ms`：每条 Z3 义务的超时；
- `keymaerax_timeout_seconds`：本次 KeYmaera X 调用的超时覆盖。

初态只允许出现 Gamma 中声明为 `BasicType` 的键，可以是真子集；未知键、共享
参数键和 `ContinuousType` 声明标签会被拒绝。

### 输出模式

两个接口均支持：

- `output="none"`：默认，不打印；
- `output="result"`：只打印本阶段最终结果；
- `output="full"`：打印输入模型、规则轨迹、FOL/dL 公式、证明器结论和停止原因。

也可以使用 `OutputMode.NONE/RESULT/FULL`。`stream=` 可把文本写入文件或
`io.StringIO`；输出模式只改变展示，不改变解析、推导或返回值。

## 完整用户输入格式

一份输入固定按以下顺序书写：

```ebnf
source ::= gamma [parameters] theta process EOF
```

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
  条件由第二阶段检查。

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
- `wait(d)` 是有限非负有理时延语法糖，不增加新的 Process AST 节点。

### 证明边界

- Z3 处理项目支持的一阶逻辑片段；不可靠或不支持的翻译不会猜测结论。
- 非平凡 ODE 证明由 KeYmaera X 完成；证明器缺失、超时或公式超出可靠翻译
  子集时得到 `unknown`，不会被当作成功。
- Python callable、原始 Z3 项和自定义 dL 回调只属于内部开发接口，不能写入
  用户 source。

## 示例、测试与更多文档

- `python demo.py`：运行几个无需外部证明器的简短示例，展示完整的两阶段接口；
- `python -m unittest discover -s tests -p "test_*.py"`：运行全部自动化测试；
- `python scripts/check_repository.py`：运行隐私扫描、环境检查和全部测试。

内部架构、真实转换算法、证明后端和测试职责不放在根 README 中，统一从
[项目文档索引](document/INDEX.md) 进入。
