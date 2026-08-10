# TypeConstructor：Process AST 到 Type AST 的实际构造过程

本文只描述当前代码真正执行的构造算法和数学操作，不判断这些操作是否与某一版
论文完全一致。人工比对时，应以本文给出的“代码实际行为”为准，再逐条与论文规则
比较。

本文描述的功能称为 **TypeConstructor**：输入是带批注的 HCSP、Gamma、Theta、
参数以及可选初态/路径条件，Type AST 由程序自行构造。用户给定 Type 的
**TypeChecker** 已作为独立功能实现，详见 [TYPE_CHECKER.md](TYPE_CHECKER.md)；
本文仍只描述 Constructor。

相关实现主要位于：

- `hcsp_typechecker/data_structures/process_ast/ast.py`：Process、Event、System AST；
- `hcsp_typechecker/backend/type_constructor/constructor.py`：TypeConstructor 业务入口；
- `hcsp_typechecker/backend/common/rule_engine.py`：judgment、premise 与 Table 2 规则展开；
- `hcsp_typechecker/backend/common/logic.py`：表达式到 Z3 项的翻译及 FOL/state 判定；
- `hcsp_typechecker/backend/common/dl.py`：ODE 证明义务到 dL 公式的翻译；
- `hcsp_typechecker/data_structures/type_ast/ast.py`：最终 Type AST 及规范化构造；
- `hcsp_typechecker/data_structures/runtime_context/model.py`：Gamma、Theta、全局参数与 Configuration；
- `hcsp_typechecker/backend/type_constructor/model.py`：TypeConstructor 的构造请求和报告名称；
- `hcsp_typechecker/backend/common/model.py`：Constructor/Checker 共用的证明义务、诊断与规则证据。

---

## 1. 构造的输入和输出

一次 `TypeConstructionRequest` 可以抽象写成：

\[
(\Gamma,\Pi,\Theta,\Phi,K),
\]

其中：

- \(\Gamma\) 是变量声明环境；
- \(\Pi=(\Delta,H)\) 是共享只读参数声明及其合法预赋值约束；
- \(\Theta\) 是通道 refinement 环境；
- \(\Phi\) 是当前路径条件；
- \(K\) 是一个或多个 `Configuration(state, process)`；
- 每个 configuration 的 `process` 可以是顺序 `Process`，或者受限的无状态
  `Parallel` 便捷结构。

内部构造结果不是单独一个 Type AST，而是 `TypeConstructionReport`：

- `constructed_type`：全部分量均完成规则结构推导时得到的 `ConfigurationType`；它在
  verdict 为 `unknown` 时是完整但未验证的候选类型；
- `constructed_component_types`：各 configuration 的分量结果；失败或尚未访问的位置为
  `None`；
- `obligations`：已经实际判定过的 state、FOL、dL 公式；
- `diagnostics`：结构错误、静态类型错误和未决选择原因；
- `steps`：按执行顺序保存的规则入口环境和结果；
- `verdict`：有效证明义务与诊断的 `true / false / unknown` 合并值。

`None` 只表示没有形成完整类型结构。非空类型是否可信必须同时查看 verdict：
`true` 表示可信，`unknown` 表示仍有必要义务未验证。两种情况都与用户 Type AST
中表示不可达错误行为的 `BottomType()` 完全不同；当前构造器不会输出它。

---

## 2. Process AST 构造阶段已经做掉的工作

TypeConstructor 接收的不是任意 Python 对象，而是已经构造好的项目 Process AST。
进入 `backend/type_constructor/constructor.py` 之前，`data_structures/process_ast/ast.py` 已经执行以下操作：

1. 字符串表达式被解析成项目自己的 `Expr` 节点；
2. 赋值左端、输入目标和通道名称被检查为合法标识符；
3. 输入/输出的单参数简写被规范成一槽元组；
4. `If`、`Sequence`、`InternalChoice`、`EventChoice`、`ODE`、`Mu` 等节点检查
   子节点所属的语法范畴；
5. 复合节点在构造时检查 Assumption 2.1；
6. `Mu` 在构造时检查 Assumption 2.2 的通信保护条件；
7. `ODEAnnotation` 把有限 delay 规范成精确 `Fraction`，并拒绝负数、符号时延、
   NaN 和负无穷；
8. 每个 `ODE` 自动建立局部时钟 `t`，其初值固定为 0、导数固定为 1；

因此，某些程序会在“Process AST 构造”阶段失败，根本不会进入 Process 到 Type
的类型构造。例如当前实现认为 `ch!x; ch?x` 同时自由使用并绑定 `x`，会直接因
`fv(P) ∩ bv(P) != empty` 抛出 `ValueError`。

---

## 3. Gamma、共享参数、Theta 和符号状态

### 3.1 Gamma

当前 Gamma 项有两类：

```python
GammaType = BasicType | ContinuousType
```

普通变量使用：

```python
BasicType.BOOL
BasicType.NAT
BasicType.INT
BasicType.RATIONAL
BasicType.REAL
```

ODE 左端变量本身仍是普通 Real 值变量：

```python
"p": BasicType.REAL
"v": BasicType.REAL
"a": BasicType.REAL
```

另用一个独立命名的连续项登记 process 中允许出现的 ODE 演化向量，语义退化为
\(\mathbb R_{\ge0}\rightharpoonup\mathbb R^n\)，不再携带轨迹性质 \(\phi\)。
连续演化期间必须恒成立的 \(\phi\) 统一写在对应 ODE 的 safety 批注中。

若一个演化向量由多个标量组成，例如 \(\{p,v,a\}\)，显式记录它的成员集合：

```python
trajectory = ContinuousType(
    variables=("p", "v", "a"),
)
{
    "p": BasicType.REAL,
    "v": BasicType.REAL,
    "a": BasicType.REAL,
    "vehicle_ode": trajectory,
}
```

环境规范化要求向量声明的所有成员都作为 `BasicType.REAL` 标量存在。T-ODE
要求用户写出的 ODE 左侧变量集合与 Gamma 中某个 `variables` 集合精确相等；
成员顺序不同仍是同一个集合，只有真子集或真超集会在建立 dL 义务前静态失败。

`ContinuousType` 所在的键没有当前值，不能出现在表达式、state、赋值目标或
通信输入目标中。它只承担两项信息：

- process 中允许出现相应的 ODE 演化向量；
- `variables` 标识这个向量的完整成员集合。

ODE 的左端分量、导数右端参数、演化域和 safety 中的 Real 量都统一使用
`BasicType.REAL`。未参与任何 ODE 的 Real 无需额外的连续声明。

### 3.2 共享只读参数环境

`ParameterEnvironment(declarations, constraint)` 构成独立于 Gamma 的参数
环境 \(\Pi=(\Delta,H)\)：

- \(\Delta\) 只能声明 `BasicType`参数；
- \(H\) 只能引用 \(\Delta\) 中声明的名称；
- 检查器先验证 \(H\land TypeDomain(\Delta)\) 可满足，防止矛盾假设
  造成真空证明；
- 参数在所有并行 configuration 中使用同一组 Z3 符号，不参与
  Gamma 的局部投影、互斥性和并集覆盖检查；
- 参数可在路径、表达式、通道 refinement、递归不变式和 ODE
  公式中读取，但不能出现在 state 赋值、赋值左端、输入目标或
  ODE 左端。

Gamma 和 \(\Delta\) 的名称域必须不相交。参数由用户在 HCSP 执行前一次性
选定，类型构造结果覆盖所有满足 \(H\) 的选择，不保存某组具体参数值。

### 3.3 Theta

对通道 `ch`，`ChannelType` 保存：

\[
\Theta(ch)=((B_1,\ldots,B_n),(\eta_1,\ldots,\eta_n),R),
\]

其中：

- \(B_i\) 是每个独立标量槽的 `BasicType`；
- \(\eta_i\) 是 refinement 中引用该槽值的 binder；
- \(R\) 是联合 refinement 公式。

通信元数和载荷类型只保存在 Theta 和证明义务中，不进入最终 `InputType` 或
`OutputType`。因此两个具有相同通道名、但 Theta 签名不同的通信，在 Type AST
层只显示相同的 `ch?` 或 `ch!` 前缀。

### 3.4 每条控制流路径上的 Context

TypeConstructor 内部为每条控制流路径维护：

\[
C=(\Gamma,\Delta,H,\Theta,\Phi,\rho,\mathcal R,location,valid),
\]

其中：

- `gamma`是当前局部状态环境，`parameters`、`parameter_condition`分别是
  共享的 \(\Delta\) 和 \(H\)，`theta` 是共享通道环境；
- `path` 是 Z3 布尔公式 \(\Phi\)；
- `symbols` 是符号状态 \(\rho\)，把变量名映射到当前 Z3 项；
- `rec_env` 是递归进程变量到类型变量、不变量的绑定；
- `location` 用于报告分支位置；
- `static_valid` 表示初始环境和路径是否成功建立。

建立整个判断时，参数先获得一组共享符号。建立各初始 Context 时，
Gamma 中的 `BasicType` 值变量再获得带 configuration 前缀的新鲜符号。
两者的 Z3 sort 均为：

- `Bool` -> Z3 Bool；
- `Nat`、`Int` -> Z3 Int；
- `Rational`、`Real` -> Z3 Real。

`ContinuousType` 声明不建立 Z3 符号。各配置的初始路径实际是
\(H\land\Phi_i\)。

代码还把类型固有条件加入路径。目前只有 `Nat` 额外产生 \(x\ge 0\)。

---

## 4. 表达式翻译的数学对象

对当前 Context 中的表达式 `e`，`ExpressionTranslator` 实际返回三元组：

\[
\llbracket e\rrbracket_{\rho}=(u,B,D),
\]

其中：

- \(u\) 是 Z3 项；
- \(B\) 是推断出的 `BasicType`；
- \(D\) 是表达式求值有定义所需条件的列表。

例如：

- `x / y` 会生成除数 \(y\ne0\)；
- `sqrt(x)` 会生成 \(x\ge0\)；
- `%` 只接受 `Nat/Int`；
- ODE 分量 `x:BasicType.REAL` 的读取结果类型是 `Real`；向量声明名不可读取。

数值子类型关系为：

\[
Nat <: Int <: Rational <: Real.
\]

表达式静态类型检查与有定义性证明是两件事：类型错误直接产生诊断；偏表达式的
有定义条件通常会成为当前规则的公式 premise。

---

## 5. 统一推导器怎样工作

### 5.1 四种内部 judgment

代码没有让每条规则自行递归，而是显式建立四种子 judgment：

1. `_ConfigurationJudgment(state, system, context)`；
2. `_SystemJudgment(system, context)`；
3. `_ProcessJudgment(nodes, context, terminal)`；
4. `_EventJudgment(reaction, tail, context, terminal)`。

每条 `rule_t_*` 只展开当前一层，返回：

```text
RuleExpansion(rule, premises, conclude)
```

premise 只有两类：

- `FormulaPremise`：state、FOL 或 dL 公式；
- `ChildJudgmentPremise`：需要递归求解的子 judgment。

`conclude` 只负责使用已经求得的子类型构造父 Type AST。

### 5.2 按序证明、`false` 短路与 `unknown` 保留

`_solve_rule_expansion` 按 premises 的保存顺序逐项处理：

1. 遇到公式 premise，立即交给对应证明器；
2. verdict 为 `true` 时照常继续；
3. verdict 为 `false` 表示该必要 premise 已被反例否证，立即停止当前规则；
4. verdict 为 `unknown` 只表示当前证明器未能判定：义务及原因写入报告，然后继续
   求解剩余 premise；
5. 遇到子 judgment 时递归求解；子 judgment 真正无法形成类型后，后续兄弟
   premise 不再访问；
6. 全部所需子类型都已形成时调用 `conclude` 构造父类型；此前出现的 `unknown`
   不阻止构造，但最终 verdict 会把该类型标为不可信。

因此代码仍然是一边证明、一边推导，而不是先生成公式池再统一证明。差别在于
`unknown` 不再被误当成否定：检查器会尽量推导到根节点并保留完整候选 Type AST；
`false` 和结构/静态失败仍只留下实际停止点以前的证明义务、步骤与部分类型。

### 5.3 Sequence 没有对应的 Type AST 节点

二元 `Sequence(P,Q)` 在进入过程判断时由 `_as_nodes` 递归展开成：

```text
[P 的顺序节点..., Q 的顺序节点...]
```

TypeConstructor 每次处理列表头，并把剩余列表作为 continuation 子 judgment。因此代码
没有通用的 `SequenceType`，也没有“先得到 P 的类型，再把 Q 的类型接到所有
终点”的后处理算法。后继是在推导 P 时就沿控制流传下去的。

`InternalChoice` 是例外：它自己保存公共 `continuation`，构造时把该后继分别
交给左右两个子 judgment。

---

## 6. 顶层 configuration 和并行系统

### 6.1 环境规范化

`TypeConstructor.construct` 首先统一规范化 Gamma、共享参数和 Theta。非法变量类型、
非法参数约束、Gamma/参数名称重叠、非法通道名和非法通道签名都会在
进入 Process 规则以前得到失败诊断。不可满足的参数约束也会直接被拒绝。

### 6.2 顶层多个 Configuration

即使只有一个 configuration，代码也统一经过 `rule_t_parallel`。

单 configuration 未提供局部 Gamma 时，直接使用完整全局 Gamma。

多个 configuration 未提供局部 Gamma 时，代码按下式自动投影：

\[
\Gamma_i=\Gamma\restriction
((vars(P_i)\cup dom(\sigma_i))\setminus dom(\Delta)).
\]

输入动作绑定的目标允许不预先出现在 Gamma；除此之外，进程使用但 Gamma 未
声明的变量会报错。

若显式提供局部 Gamma，则代码要求：

1. 局部名称必须来自全局 Gamma；
2. 同名项必须与全局项完全相等，包括值变量项与 ODE 向量声明项的区别；
3. 任意两个分量的 Gamma 定义域不相交；
4. 全部局部 Gamma 的定义域并集精确覆盖全局 Gamma。

自动并行分区先按各配置实际使用的值变量分配 `BasicType` 项；只有某个配置的
process 真正包含已登记 ODE 时，匹配的独立 `ContinuousType` 声明项才归该配置。
普通 Real 的读写不会凭空拖入一个未出现的 ODE 向量声明。
参数环境不做局部投影：每个分量都读取同一个完整 \(\Delta,H\)。

局部路径条件要么所有 configuration 都提供，要么都不提供。若使用局部路径，
外层路径必须是默认 `true`。

各 configuration 按输入顺序形成子 judgment。某一分量因 `false` 或结构/静态
错误而无法形成类型后，后续分量不再推导；已经完成的前缀仍保留在
`constructed_component_types` 中，失败和未访问位置为 `None`。某个公式仅为
`unknown` 时，该分量仍继续构造，并可在 `constructed_component_types` 中保留
不可信的完整候选类型。

若全部成功：

- 一个分量直接返回该分量类型；
- 多个分量构造 `ParallelType((T1,...,Tn))`。

`ParallelType` 会压平嵌套并行，但保留分量次序。

### 6.3 T-sigma 的实际状态检查

对 configuration \((\sigma,P)\)，代码先要求：

\[
dom(\sigma)\subseteq dom(\Gamma_{value}),
\]

其中 \(\Gamma_{value}\) 只包含 `BasicType` 项，不包含独立的 ODE 向量声明。
参数不属于 \(\Gamma_{value}\)，因此 \(dom(\sigma)\cap dom(\Delta)\) 必须为空。

state 可以只是 Gamma 值变量的子集。随后代码把 state 中的具体值代入路径公式：

\[
H\Rightarrow\Phi[\sigma].
\]

若还有未赋值的 Gamma 值变量，它们保留为自由 Z3 常量；参数符号也保留
在含件公式中。证明器通过有效性检查，对所有满足 \(H\) 的参数预赋值和所有
未指定状态值作全称检查，而不是任选一组值使公式成立。

state 通过后，才进入 system/process 子 judgment。

### 6.4 `Parallel` AST 便捷入口

`Configuration({}, Parallel(...))` 只允许在空 Gamma、空 state、完整路径为 true
时使用。代码递归推导左右系统并构造 `ParallelType`。

有状态并行或带非平凡参数约束的并行不能通过这一入口处理，必须拆成
多个显式 `Configuration`，使 T-|| 对局部 Gamma 和共享参数分别建模。

---

## 7. 每一种离散 Process 节点的类型构造

### 7.1 终端 `Skip` 和隐式终端

当顺序节点列表为空，或者当前只有最后一个显式 `Skip()` 时：

\[
skip \longmapsto terminal.
\]

普通顶层的 `terminal` 是 `EmptyType()`，所以得到空通信行为 `0`。

规则没有 premise，也不修改 Context。

### 7.2 中间 `Skip; P`

中间 `Skip` 只递归推导剩余节点：

\[
type(skip;P,C)=type(P,C).
\]

Gamma、路径条件和符号状态全部保持不变，不生成 Type AST 前缀。

### 7.3 `Assert(B); P`

先翻译条件：

\[
\llbracket B\rrbracket_\rho=(b,Bool,D_B).
\]

代码生成并立即证明：

\[
\Phi\Rightarrow(D_B\land b).
\]

证明成功后，在原 Context 下继续推导 `P`。`Assert` 是验证操作，不是 Assume，
因此后继路径仍是 \(\Phi\)，不会变成 \(\Phi\land B\)。最终类型就是 `P` 的类型，
没有 `AssertType` 节点。

### 7.4 `Assign(x,e); P`

代码执行以下操作：

1. 要求 `x` 不是共享参数，并且已在 Gamma 声明；
2. 在赋值前符号状态 \(\rho\) 中求值
   \(\llbracket e\rrbracket_\rho=(u,B_e,D_e)\)；
3. 检查 \(B_e <: base(\Gamma(x))\)；
4. 若 \(D_e\) 非平凡，证明 \(\Phi\Rightarrow D_e\)；
5. 建立新符号映射：

\[
\rho'(x)=u,
\qquad
\rho'(y)=\rho(y)\quad(y\ne x).
\]

路径公式对象本身仍保存为赋值前的 \(\Phi\)。旧 `x` 符号可能继续出现在该公式
中，作为历史逻辑参数；后继表达式中对 `x` 的读取则从 \(\rho'\) 得到 \(u\)。
代码不显式构造存在量词形式的最强后置公式。

当前实现还登记一条 `T-Assign-post` 义务。其实际公式是：

\[
\Phi\Rightarrow\Phi,
\]

因为 `_LazyAssignmentPostState.pre_path` 就是原路径。它记录“后状态已经由符号
映射确定”这一事实，不搜索未知谓词 \(\Phi'\)。

赋值成功后用 \((\Phi,\rho')\) 推导 `P`，最终类型仍是 `P` 的类型，没有
`AssignType` 节点。赋值目标必须是 `BasicType` 值变量；独立的
`ContinuousType` 声明没有当前值，不能被赋值；共享参数即使具有值类型，
也因为在 HCSP 执行前已预赋值而禁止作为赋值目标。

### 7.5 `ch?(x1,...,xn); P`

代码先从 Theta 取得通道槽位类型和 refinement：

\[
((B_1,\ldots,B_n),(\eta_1,\ldots,\eta_n),R).
\]

实际步骤为：

1. 检查通道存在且输入元数等于 Theta 元数，并拒绝把共享参数作为输入目标；
2. 对已存在的目标变量，代码要求它的基础类型与槽位类型在数值子类型链上
   可比较，即实际条件是

\[
existing_i <: B_i\quad\lor\quad B_i <: existing_i.
\]

   这是一项双向“可比较性”检查，不是单向赋值检查；
3. 新目标加入局部 Gamma，类型取对应的 \(B_i\)；
4. 已存在目标保留原 `BasicType` 项；独立 ODE 向量声明不受通信更新影响；
5. 为每个槽建立新鲜接收符号 \(r_i\)，并更新

\[
\rho'(x_i)=r_i;
\]

6. 把输入 refinement 作为后继假设加入路径：

\[
\Phi'=\Phi\land Def(R[r/\eta])\land R[r/\eta]
       \land TypeDomain(r_1)\land\cdots\land TypeDomain(r_n).
\]

`Nat` 接收值的 `TypeDomain` 是 \(r_i\ge0\)，其他当前为空。

还有一个必须按源码理解的细节：若已有声明与通道槽类型不同、但在数值子类型链
上可比较，Gamma 会保留已有声明，而新鲜 Z3 符号按通道槽类型建立。也就是说，
当前代码没有把二者先统一成一个共同类型；后续表达式的静态类型标签来自 Gamma，
缓存符号的 Z3 sort 则来自本次输入槽。

输入 refinement 不产生需要证明的 FOL premise；环境给出的输入值被假设满足
该 refinement。后继推导成功后生成：

```python
InfiniteDelayType(InputType(channel, continuation_type))
```

`InputType` 是中断/外部选择类型 \(A\) 的分支；T-In 再以无穷时延包装它，
使整个通信行为成为过程类型 \(T\)。载荷数量、槽位类型、变量名和 refinement
均不存入 Type AST。

### 7.6 `ch!(e1,...,en); P`

代码执行：

1. 检查通道存在、元数一致；
2. 翻译每个 \(e_i\) 得到 \((u_i,B_i',D_i)\)；
3. 单向检查 \(B_i' <: B_i\)；
4. 实例化联合 refinement \(R[u_1/\eta_1,\ldots,u_n/\eta_n]\)；
5. 证明：

\[
\Phi\Rightarrow
\left(\bigwedge_i D_i\right)
\land Def(R[u/\eta])
\land R[u/\eta].
\]

输出不会改变 Gamma、路径或符号状态。后继推导成功后生成：

```python
InfiniteDelayType(OutputType(channel, continuation_type))
```

### 7.7 `If(B,P1,P2); Q`

代码先要求 `B` 为 Bool。若 `B` 是偏表达式，还单独证明：

\[
\Phi\Rightarrow Def(B).
\]

然后克隆两个 Context：

\[
C_{then}.path=\Phi\land B,
\qquad
C_{else}.path=\Phi\land\neg B.
\]

外层顺序后继 `Q` 被附加到两个分支：

\[
T_1=type(P_1;Q,C_{then}),
\qquad
T_2=type(P_2;Q,C_{else}).
\]

两个子 judgment 都成功后生成：

```python
InternalChoiceType((T1, T2))
```

内部选择构造器保留嵌套 `InternalChoiceType`，使规范 Type 文本能够用每个分支的
圆括号直接表达本层 T-If 的两个子 judgment。由于求解器严格顺序执行，then 分支
因 `false` 或结构/静态错误而无法形成类型时，else 分支不会继续检查；then 分支
只有未决公式时仍会形成候选子类型，else 分支会继续推导。

### 7.8 多元 `InternalChoice(P1,...,Pn, continuation=Q)`

该节点表示全部选择分支共享同一个后继。代码分别推导：

\[
T_1=type(P_1;Q;tail,C_1),
\qquad
T_2=type(P_2;Q;tail,C_2).
\]

`C1`、`C2` 是原 Context 的独立克隆，防止一个分支中的赋值或输入污染另一个
分支。两边成功后生成 `InternalChoiceType((T1,T2))`。

若构造时省略 `Q`，AST 中实际保存 `Skip()`。外层再写
`Sequence(InternalChoice(...),Q)` 的非规范形状会在 Process AST 阶段被拒绝。

---

## 8. EventReaction 到 angelic type

EventReaction 只在 ODE 的 interrupts 字段中出现。

### 8.1 `EmptyEvent`

空事件反应构造为 `NoInterruptType()`。它表示 ODE 没有通信中断；这和
`EmptyType()` 表示的过程空通信行为不同。

### 8.2 `EventChoice((communication_1,P_1),...,(communication_n,P_n))`

对每个事件分支，代码构造完整顺序行为：

```text
communication; P; ODE 外层 tail
```

因为 `communication` 必须是输入或输出，成功结果必须是 `InputType` 或
`OutputType`。其余事件 `E` 递归构造。

分支合并使用 `make_external_choice`：

- 零分支 -> `NoInterruptType()`；
- 一个通信分支 -> 直接返回该 `InputType/OutputType`；
- 两个及以上 -> `ExternalChoiceType((branch1,...,branchn))`。

外部选择保留源分支次序，也保留通道名相同的不同分支。代码不按通道去重、排序
或应用交换律。

---

## 9. ODE 的完整类型构造

设 Process 节点包含：

\[
\dot x_1=e_1,\ldots,\dot x_n=e_n,
\quad B,
\quad E,
\quad safety=S,
\quad delay=d.
\]

每个 ODE 还自动拥有局部时钟 \(t\)，满足入口 \(t=0\) 和导数 \(\dot t=1\)。

### 9.1 静态检查

代码首先检查：

1. ODE 左端变量不得重复；
2. 每个左端变量不得是共享只读参数，并且必须在 Gamma 中声明；
3. 每个左端变量必须是 `BasicType.REAL`；
4. 非空左侧变量集合必须由独立 `ContinuousType` 项精确登记；
5. 每个导数表达式必须是数值类型；
6. 演化域 `B` 必须是 Bool；
7. ODE 自身的 safety `S` 必须是 Bool；
8. 导数、`B` 和 `S` 的偏表达式有定义条件被收集。

源表达式中的名字 `t` 在本 ODE 的导数右端、`B` 和 `S` 中被局部时钟遮蔽，
不会读取同名 Gamma 项。该时钟只在 dL 动力系统构造阶段追加，不进入上述
连续向量精确登记检查。

任一静态检查失败时，不生成 dL 义务，也不生成任何时延 Type AST。

### 9.2 ODE 入口的 dL 符号快照

离散赋值后，当前演化变量的 `symbols[x]` 可能是一个复合表达式，而 dL 方程左端
必须是变量。因此 `_ode_dl_terms` 为每个演化变量创建新鲜入口变量 \(x_i^0\)，
并加入等式：

\[
x_i^0=\rho(x_i).
\]

再创建本 ODE 独占的新鲜时钟 \(\tau\)，加入：

\[
\tau=0,
\qquad
\dot\tau=1.
\]

于是 dL 前置条件是（其中当前路径 \(\Phi\) 已包含 \(H\)）：

\[
Pre=\Phi\land\bigwedge_i(x_i^0=\rho(x_i))\land(\tau=0).
\]

基础动力系统是：

\[
F^*=\{\dot x_1^0=e_1,\ldots,\dot x_n^0=e_n,\dot\tau=1\}.
\]

令 ODE 用户方程左侧的变量集合为

\[
V_{ODE}=\{x_1,\ldots,x_n\}.
\]

检查器要求 Gamma 中存在 `variables` 恰好等于 \(V_{ODE}\) 的独立
`ContinuousType` 声明。没有精确匹配时 T-ODE 静态失败；匹配
成功只表示这个 ODE 演化向量允许在 process 中出现，不会向 dL 公式添加性质。
没有用户方程的空 flow ODE 使用空向量，不需要 Gamma 声明。dL 连续程序始终
使用上面的无假设动力系统 \(F^*\)。

ODE 的 delay 批注不会自动添加到演化域；若要在给定时间边界自然结束，必须在
用户演化域中显式写出相应的时钟条件。

### 9.3 safety dL 义务

记 \(D_F,D_B,D_S\) 分别为导数、源演化域表达式和节点 safety 的有定义条件。
节点 safety 是连续演化中恒成立性质的唯一来源。

在没有走本地恒真捷径时，有限 delay 实际生成：

\[
Pre\Rightarrow[F^*]
(\tau\le d\Rightarrow(D_F\land D_B\land D_S\land S)).
\]

在没有走本地恒真捷径时，无限 delay 实际生成：

\[
Pre\Rightarrow[F^*](D_F\land D_B\land D_S\land S).
\]

注意待验证的源演化域 `B` 不会进入 dL 程序域；它只通过有定义性间接出现在
safety 后置条件中。Gamma 只在静态阶段核对演化向量；参数约束 \(H\) 作为路径
的一部分进入 dL 前件，参数本身不进入演化向量。

若规则层用于捷径判断的公式
\(D_F\land D_S\land S\) 语法化简为 true，则该义务直接记为 true，不调用
KeYmaera X；这一步的捷径判断没有包含 \(D_B\)。只有未走捷径、真正建立 dL
公式时，后置条件才按上式包含 \(D_B\)。无法翻译为受支持 dL 子集时，保存
`UntranslatedDLFormula`，通常由后端产生 unknown。

### 9.4 纯通信规则的 domain 义务

当代码选择“只有通信中断、没有自然 timeout 后继”的 ODE 规则时，生成：

\[
Pre\Rightarrow[F^*](D_F\land D_B\land B^*).
\]

`B*` 是这条公式要证明的不变量，不放入 dL 程序域。若域整体语法为 true，该义务
直接判 true。

### 9.5 自然 timeout 规则的 boundary 义务

有限 delay 且存在自然顺序后继时，代码生成：

\[
Pre\Rightarrow[F^*]
\left(
(\tau<d\Rightarrow D_F\land D_B\land B^*)
\land
(\tau=d\Rightarrow D_F\land D_B\land\neg B^*)
\right).
\]

同样，`F*` 不带演化域。公式要求在 `d` 之前保持域，而在 `d` 时域已经失效。

### 9.6 ODE 离开后的符号 Context

ODE 的 dL 证明义务不直接计算解析解。离开 ODE 时，代码把每个演化变量替换为
新鲜后状态符号：

\[
\rho_{post}(x_i)=x_i^{post}.
\]

然后仅按所选规则给后继建立以下路径条件。为准确表示源码，先记：

\[
\widehat B=Def(B(post))\land B(post),
\qquad
\widehat S=Def(S(post))\land S(post).
\]

这里把已经由同一条 dL 安全义务证明的节点 safety 在 ODE 结束/中断时刻的
实例交给后继；它不是未经检查的路径假设。

三种情况分别为：

1. 纯通信规则的事件后继：

\[
\Phi_{event}=\widehat B\land\widehat S;
\]

2. 带自然 timeout 规则的通信事件后继：

\[
\Phi_{event}=\widehat S;
\]

3. 带自然 timeout 规则的自然后继：

\[
\Phi_{fallback}=Def(B(post))\land\neg B(post)\land\widehat S.
\]

这些后继条件不再附加导数表达式的有定义性；导数相关条件只留在此前的 dL
证明义务中。

这些后继路径会替换原路径，而不是再与 ODE 入口路径 \(\Phi\) 合取；入口与连续
演化正确性的联系由前面的 dL premise 承担。

若 `B` 或 `S` 使用局部时钟，代码建立一个新鲜后状态时钟并将它投影掉：

\[
\exists\tau\ge0.\ condition(\tau).
\]

局部时钟不会进入事件 continuation 或外层顺序后继的 Gamma。

### 9.7 ODE 类型的组合与规范化

事件反应得到 angelic type \(A\)，自然后继得到 process type \(T\)，随后调用：

```python
make_delay_type(d, A, T)
```

有限 \(d\) 的唯一规范形为：

| `A` | `T` | 实际 Type AST |
|---|---|---|
| `NoInterruptType()` | 任意 `T` | `FiniteDelayType(d,A,T)`，打印为 `delay(d).T` |
| 非空通信选择 | `EmptyType()` | `FiniteDelayType(d,A,T)`，打印为 `delay(d) \unrhd A` |
| 非空通信选择 | 非空通信后继 `T` | `FiniteDelayType(d,A,T)`，打印为完整式 |

特别地，位于语句块末尾、无事件的有限 ODE 隐式以正常 `skip` 结束，得到：

```python
FiniteDelayType(d, NoInterruptType(), EmptyType())
```

正无穷 delay 构造 `InfiniteDelayType(A)`；其自然到时后继固定为不可达的
`BottomType()`，不作为普通字段存储。因此：

- 有通信事件时，结果是 `InfiniteDelayType(InputType/OutputType/ExternalChoiceType)`；
- 没有事件时，结果是 `InfiniteDelayType(NoInterruptType())`。

无限 ODE 即使具有外层 tail，自然 timeout 也不会进入 tail；但通信提前中断的
每个事件分支仍会在自己的 continuation 后执行该 tail。

### 9.8 末尾有限 ODE 的空边界后继

有限 ODE 总是采用带自然到时后继的规则。若它位于语句块末尾，构造器不会补造
`Skip()`；而是让空的后继节点序列直接经过 `[T-End]`，得到 `EmptyType()`。

因此以下两种源码位置在行为类型的通信抽象上得到相同的边界后继：

```text
ode(..., delay(d))
ode(..., delay(d)); skip
```

前者不会因为缺少显式语法节点而丢失 `T`，也不会把正常自然结束写成
`BottomType()`。无穷时延则没有自然到时迁移，使用上一节的
`InfiniteDelayType(A)` 规则。

---

## 10. 递归 Process 的类型构造

### 10.1 `Mu(X,P,invariant=I)`

当前实现只支持没有外层顺序 tail 的递归节点。若出现 `Mu(...); Q`，会因该结构
超出当前递归构造能力而产生 `unknown` 诊断且无法形成父类型。这里是缺少结构推导
规则，不是“证明器对一条已生成公式返回 unknown”，因此没有可继续构造的递归类型。

递归入口先证明：

\[
\Phi\Rightarrow Def(I)\land I.
\]

然后分配与源名字无关的新鲜类型变量，例如 `t1`，记录：

```text
X -> (TypeVar("t1"), invariant I)
```

递归体不是在当前具体符号状态下直接检查。代码为 Gamma 中所有值变量重新建立
新鲜符号，并把递归体入口路径替换为：

\[
H\land I\land Def(I)\land TypeDomain(\Gamma).
\]

因此递归体表示“任意一次满足不变量的迭代入口”，不会继承进入 `Mu` 前变量的
具体赋值项。

### 10.2 `Var(X)`

遇到递归回边时，代码要求：

1. `X` 已在 `rec_env` 绑定；
2. `Var(X)` 后没有顺序 tail；
3. 当前路径重新建立不变量：

\[
\Phi_{body}\Rightarrow Def(I)\land I.
\]

证明成功后，`Var(X)` 构造为相应 `TypeVar("t1")`。

### 10.3 是否保留 `MuType`

递归体类型求得后：

- 若类型体中实际出现 `t1`，代码复核所有出现都经过 `InputType` 或
  `OutputType`，然后构造 `MuType("t1",body_type)`；
- 若类型体没有引用 `t1`，说明该递归绑定在类型层无实际回边，直接返回
  `body_type`，不保留空的 `MuType` 包装。

Delay、内部选择和并行本身不算通信守卫；只有输入/输出类型前缀把
`under_communication` 置为 true。

---

## 11. Type AST 的规范化规则

类型构造规则不会任意构造多个等价形状，而是通过 Type AST 构造器保持以下规范：

1. 正常终止只有 `EmptyType()`；
2. `BottomType()` 仅保留为 Type AST 的论文节点，当前 TypeConstructor 不生成它；
3. 外部选择：零分支为 `NoInterruptType`，单分支直接使用通信类型，多分支才使用
   `ExternalChoiceType`；
4. 嵌套 `InternalChoiceType` 保留分块和顺序，不压平、不排序；
5. 所有有限 delay 均使用 `FiniteDelayType(d,A,T)`；三种论文缩写只影响显示；
6. 正无穷 delay 由 `InfiniteDelayType(A)` 显式保存，普通后继固定为不可达 bottom；
7. `ParallelType` 压平嵌套并行，但不排序；
8. `MuType` 的绑定变量支持 alpha 改名。

`types_equivalent` 实际只比较规范结构并忽略 `MuType` 绑定变量名称。它不实现：

- 内部/外部选择交换律；
- 并行交换律；
- 子类型关系；
- 行为双模拟；
- 不同通道 refinement 的语义等价。

有限 delay 使用精确 `Fraction` 比较，所以 `1`、`1.0`、`Fraction(1,1)` 在规范
类型中具有同一个时延键。

---

## 12. 证明义务的三种判定方式

### 12.1 State premise

对 T-sigma，将具体 state 代入局部路径，然后检查
\(H\Rightarrow\Phi[\sigma]\) 的有效性。state 中未知的 Gamma 值变量、ODE 向量声明名或
共享参数名都会被拒绝；Gamma 值变量中未出现在 state 的项保留，并与参数一起
按全称有效性检查。

### 12.2 FOL premise

Z3 通过检查公式否定是否不可满足来判定有效性：

\[
valid(F)\quad\text{iff}\quad unsat(\neg F).
\]

- `unsat` -> true；
- `sat` -> false，并保存反例模型；
- solver unknown/timeout -> unknown。

### 12.3 dL premise

dL 公式交给配置的 KeYmaera X 后端或调用方注入的 `dl_checker`。语法恒真的
safety/domain 可以本地直接判 true。后端缺失、翻译不支持、超时或未完成证明
都保守成为 unknown。

`false` 会阻止当前规则构造类型；`unknown` 会作为待证明义务保留，但不会阻止
规则继续构造候选类型。只有 `true` 结论对应的最终类型才是可信类型。

---

## 13. 最终 verdict 和部分结果

最终 verdict 合并：

1. 所有按当前确定性规则生成的证明义务；
2. 所有 diagnostics。

优先级为：

\[
false > unknown > true.
\]

但是“总体 verdict 的合并”和“是否形成类型”是两件事：

- 某个必要 premise 为 `false` 时，推导短路，通常有 `constructed_type=None`；
- 某个公式 premise 为 `unknown` 时继续推导；若所有结构步骤仍可完成，最终同时
  得到 `verdict=unknown` 与非空 `constructed_type`，后者是完整但不可信的候选；
- 结构规则本身无法展开时也可能得到 `unknown` 且 `constructed_type=None`；
- 当前 TypeConstructor 的合法结果不包含 `BottomType`；

公共单入口不会把 `verdict=unknown` 的候选伪装成正常返回值。推导完整时它抛出
`HCSPUntrustedTypeConstructionError`，并将候选放在 `error.untrusted_type`；未形成
完整类型时抛出普通 `HCSPTypeConstructionError`。两者的详细日志均保留实际证明
公式和三值结论。

---

## 14. 几个完整的小例子

### 14.1 `ch?x; ch!x`

初始 Gamma 为空，Theta 声明 `ch:Real`：

1. T-In 建立新鲜值 \(r\)，得到 `Gamma={x:Real}`、`symbols[x]=r`；
2. 输入 refinement 加入路径；
3. T-Out 读取同一个 \(r\)，证明输出 refinement；
4. 终端得到 `EmptyType()`；
5. 逐层包装：

```python
InfiniteDelayType(
    InputType("ch", InfiniteDelayType(OutputType("ch", EmptyType())))
)
```

显示为：

```text
delay(inf) interrupt angelic {ch? -> delay(inf) interrupt angelic {ch! -> empty}}
```

### 14.2 `x := x + 1; ch!x`

若 `symbols[x]=x0`，赋值后：

\[
symbols[x]=x0+1.
\]

T-Out 对 `x` 的读取直接得到 `x0+1`，因此 refinement 证明使用更新后的值。
赋值本身不产生行为前缀，最终类型只保留：

```text
ch!.(0)
```

### 14.3 `if B then ch1!0 else ch2!0`

两个分支分别在 \(\Phi\land B\) 和 \(\Phi\land\neg B\) 下推导，结果为：

```python
InternalChoiceType((
    InfiniteDelayType(OutputType("ch1", EmptyType())),
    InfiniteDelayType(OutputType("ch2", EmptyType())),
))
```

### 14.4 有限、无事件、具有自然后继的 ODE

若 ODE 的事件反应为空，外层 tail 推导为 `T`，并且自然 timeout 候选被唯一
选中，则：

```python
make_delay_type(d, NoInterruptType(), T)
```

规范结果是：

```python
FiniteDelayType(d, NoInterruptType(), T)
```

---

## 15. 人工审计时最值得单独核对的实现选择

以下不是本文对正确性的判断，只是当前代码中真实存在、容易影响论文比对的
具体选择：

1. Sequence 通过传递剩余节点实现，不存在通用 Type 级顺序组合；
2. T-Assign 不综合未知后置谓词，而用旧路径和更新后的符号映射表示后状态；
3. 当前 `T-Assign-post` 的实际证明公式是 \(\Phi\Rightarrow\Phi\)；
4. 输入已有变量的类型检查使用双向“可比较”关系，而输出使用单向子类型关系；
5. 输入 refinement 被加入路径作为假设，输出 refinement 必须证明；
6. If 和 InternalChoice 的兄弟子 judgment 按顺序求解；第一个因 `false` 或结构
   错误而无法形成类型时会阻止第二个，但公式 `unknown` 不会；
7. ODE 后状态不计算解析解，而用新鲜变量和 `B/safety` 条件抽象；
8. ODE 的三类后继分别使用 `B∧safety`、`safety`、`¬B∧safety`；
9. safety/domain/boundary 的 dL 程序均使用不带演化域的动力系统；
10. 有限末尾 ODE 的空后继直接经 `[T-End]` 构造为 `EmptyType()`，不补造 `Skip()`；
11. 正无穷 delay 由 `InfiniteDelayType` 保存；不可达的 bottom 后继不作为可改写字段；
12. 递归体从仅满足不变量的新鲜抽象状态开始，不继承进入 `Mu` 前的具体符号项；
13. Type 等价只忽略递归绑定变量改名，选择和并行的次序仍参与比较。
