# TypeChecker：用户给定 Type 的规则检查过程

TypeChecker 接收一份依次包含 Gamma、可选 Parameters、Theta、批注 HCSP Process
和用户 Type 的完整输入，检查该 Type 是否能够成为项目实际 Table 2 规则的结论。

这里的“项目实际规则”包括多槽通信、控制节点自持公共后继、共享全 Gamma、只读
参数、ODE 隐式时钟、`ODE;skip` 双候选、三值证明和尾递归限制，并不等于把论文
排版中的规则逐字翻译成 Python。各项真实算法和相对论文表面的差异统一列在
[当前代码的实现语义与论文规则落地方式](IMPLEMENTATION_SEMANTICS.md)；本文重点
说明 Checker 怎样消费用户 Type，而不是重复 Constructor 的每条公式推导。

相关实现按后端职责分布在：

- `hcsp_typechecker/backend/type_checker/checker.py`：TypeChecker 的类型定向递归；
- `hcsp_typechecker/backend/common/environment.py`：与 Constructor 共用的规范环境结果；
- `hcsp_typechecker/backend/common/rule_engine.py`：与 Constructor 共用的 Table 2
  规则展开、符号状态和证明调度；
- `hcsp_typechecker/backend/common/logic.py`、`dl.py`、`keymaerax.py`：FOL/dL
  公式与证明后端；
- `hcsp_typechecker/backend/type_checker/model.py`：检查请求和检查报告；

TypeChecker 不导入 `backend/type_constructor`；两个业务后端只在 common 层汇合。

## 公共入口

```python
from hcsp_typechecker import check_hcsp_type

type_ast = check_hcsp_type(source, output="result")
```

完整签名为：

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

成功时返回解析后的用户 `TypeAST`。输入语法错误抛出 `HCSPInputError`；Type
结构与规则不匹配、静态前提失败、公式被否证或证明未决时抛出
`HCSPTypeCheckingError`。`output` 支持 `none`、`result`、`full`，只影响展示。
`initial_states` 与 `path_condition` 的含义和 TypeConstructor 相同。

完整 source 必须依次包含 `gamma`、可选 `parameters`、`theta`、`process` 和
`type`。`source_name` 只用于诊断；`initial_states` 对单分量是一个部分状态 mapping，
对并行系统是与顶层分量等长的 mapping 序列；`path_condition` 可以是 bool 或项目
表达式字符串。`z3_timeout_ms` 和 `keymaerax_timeout_seconds` 分别控制一阶逻辑和
dL 证明等待时间。所有逐参数约束和可复制示例见
[公共接口使用手册](PUBLIC_API_GUIDE.md#4-checker-接口)。

## 错误分类与诊断

TypeChecker 不把所有失败压成一条普通字符串。`HCSPTypeCheckingError` 提供：

- `kind`：`TypeCheckingErrorKind`，取值为 `environment`、`type-mismatch`、
  `rule-application`、`proof-failed` 或 `proof-unknown`；
- `phase`：归并后的 `environment`、`type-matching`、`rule-derivation` 或 `proof`；
- `rule`、`location`：首要失败对应的 Table 2 规则和判断位置；
- `details`：全部参与最终结论的 `HCSPErrorDetail`；证明明细还包含公式类别、
  实际公式和证明器说明；
- `type_mismatch_detected`：是否明确发现用户 Type 结构不匹配；
- `type_structure_matched`：`True` 表示完整消费，`False` 表示明确不匹配，
  `None` 表示环境或前提失败使结构检查没有完整结束。

词法、语法和前端 validation 仍使用带源码行列与插入符的 `HCSPInputError`。
`result` 只显示首要证据；`full` 显示原始输入、全部规则步骤、证明公式、证明器
说明和所有诊断。两种模式都会在抛异常前打印，因此调用方捕获后不应重复打印
同一个 `format_result()` 或 `format_full()`。

## 实际算法

Checker 不调用 `TypeConstructor.construct`，也不先构造一棵完整类型再做末端
等价比较。内部判断同时携带 Process 片段、符号上下文和该位置的用户 Type：

1. Gamma、Theta、参数、初态和路径使用与 Constructor 相同的规范化与静态边界；
2. 当前 Process 节点决定可使用的规则，用户 Type 决定该规则横线下结论的类型
   外形；
3. 规则产生的 FOL/state/dL premise 立即交给同一证明后端；
4. 规则的子 judgment 分别取得用户 Type 的对应子树并继续递归；
5. 全部 Type 子树被恰好消费且全部有效证明义务为 true 时检查成功。

第 1 步会主动遍历全部 Theta refinement，而不是只检查 Process 实际使用的通道。
所以未使用通道中的未绑定名称、非 Bool refinement 或其他静态表达式错误，也会在
进入 Type 结构递归前归入 `environment` 错误。

证明器返回 `false` 时当前规则立即失败；返回 `unknown` 时，Checker 保留未决
义务并继续消费后续 Type 结构，以便完整报告还能说明其余分支是否匹配。但
`unknown` 不会被当作成功：检查结束后仍抛出 `HCSPTypeCheckingError(kind="proof-unknown")`。
这与 Constructor 的区别是，Checker 不会通过异常交付“不可信的新类型”；它只会
在报告中保留用户给定 Type 已检查到何处。

主要规则映射如下：

- `skip`/空顺序尾只接受 `EmptyType`（用户语法 `empty`）；
- `assert`、赋值和中间 `skip` 不改变所检查的顺序后继 Type；
- 输入/输出动作只接受同通道的 `InfiniteDelayType(InputType/OutputType)`，并继续
  检查通信 continuation；
- `if` 在规则层有恰好两个子 judgment；多元内部选择有与 Process 分支数相同的
  子 judgment。用户 Type 中每个 `internal` 分支必须带圆括号，AST 保留其嵌套
  分块；Checker 只按当前节点的元数和源码顺序逐项检查，不搜索其他结合方式，
  也不使用结合律或交换律；
- ODE 的有限/无穷时延必须与批注一致，且源码必须显式写出后继。前端将
  `ODE;Q` 规范为自持 `continuation=Q` 的 ODE 节点。`ODE;skip`
  分别按 `T-\unrhd` 和 `T-\unrhd'` 检查：前者要求给定 continuation 是
  `BottomType` 且只检查 A，后者要求非 bottom continuation，并同时检查 A 和真实的
  `skip :: EmptyType`；因此给定 Type 的后继形状可以先排除不匹配规则，Checker
  再证明剩余候选。有限非 skip 后继只检查 prime
  规则；无穷节点没有自然 timeout；
- 多元 EventChoice 要求规范 Angelic Type 具有同样分支数，并逐项核对输入/输出
  方向、通道和 continuation；
- 递归维护源过程变量和用户 `MuType` 变量的 alpha 对应，回边只接受对应
  `TypeVar`；
- 并行 Type 分量必须与顶层配置数量和顺序一致。

这些是项目 Constructor 已实现规则的检查形式；多标量通信、隐式 ODE 时钟、
有限 ODE boundary、安全批注、输入 refinement 假设、输出 refinement 证明、
惰性赋值后状态和并行状态所有权等扩展均沿用同一份规则展开代码。

## Constructor 往返性质

对于 Constructor 已可信构造的类型 `T`，规范序列化后应能被 Checker 接受：

```python
from hcsp_typechecker import construct_hcsp_type, check_hcsp_type
from hcsp_typechecker.frontend.type_syntax import format_type_source

constructed = construct_hcsp_type(program_source)
checked = check_hcsp_type(
    program_source + "\n" + format_type_source(constructed)
)
assert checked == constructed
```

自动化测试覆盖离散语句、条件、多元及嵌套内部选择、多元外部中断、递归、并行和
ODE，并额外验证选择分组不允许换序，监视 Constructor 的完整入口以防止 Checker
退化为“构造后比较”。
