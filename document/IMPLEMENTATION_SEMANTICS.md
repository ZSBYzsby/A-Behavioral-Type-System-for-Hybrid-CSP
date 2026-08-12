# 当前代码的实现语义与论文规则落地方式

本文回答的不是“项目理论上想做什么”，而是“当前源码实际上做了什么”。它把
用户文本经过前端、数据结构、TypeConstructor、TypeChecker 和证明后端后的真实
数据流写清楚，并逐条说明 Table 2 在代码中的可执行形式。论文是规则来源，本文
则是当前实现的审计基准；两者表面形式不同时，本文会明确写出项目采用的扩展、
规范化方式或限制，不用一句“与 Table 2 一致”代替实现细节。

相关专题文档仍分别保存完整输入 EBNF、Type 语法和 Table 3 图语义：

- [完整 HCSP、Gamma、Theta 与参数输入](GAMMA_THETA_INPUT_SYNTAX.md)；
- [用户 Type 输入与 Type AST 往返](TYPE_INPUT_SYNTAX.md)；
- [TypeConstructor 逐规则构造细节](TYPE_CONSTRUCTOR.md)；
- [TypeChecker 的类型定向检查](TYPE_CHECKER.md)；
- [规范化 Type、循环项图与 Table 3](TYPE_OPERATIONAL_SEMANTICS.md)。

本文不把内部 Python 类列为稳定 API。普通用户仍只调用 README 中公布的三个包根
接口；这里出现内部类名，是为了让维护者可以把数学步骤定位到源码。

---

## 1. 一次完整请求在代码中怎样流动

### 1.1 TypeConstructor

`construct_hcsp_type(source, ...)` 的真实执行链为：

```text
完整用户文本
  -> 共享 lexer 和递归下降 parser
  -> Gamma / ParameterEnvironment / Theta / Process AST
  -> 顶层 Process 分量 + Configuration
  -> PreparedTypingEnvironment
  -> Table2RuleEngine 依次展开 premise
  -> Z3 或 KeYmaera X 当场判定公式
  -> TypeConstructor 由子结论组合 Type AST
  -> 可信 TypeAST，或结构化异常
```

前端产出的 Process AST 只在内部传递，不是公开返回值。Constructor 也不是先生成
一串 Type 文本再重新解析；它直接构造
`data_structures/type_ast/ast.py` 中的正式节点，最后才用 Type 语法序列化器打印。

### 1.2 TypeChecker

`check_hcsp_type(source, ...)` 与 Constructor 共用词法、Process AST、运行上下文、
Table 2 规则展开和证明后端，但其递归方向不同：

```text
带 type 分节的完整用户文本
  -> Process AST + 用户 Type AST + 环境
  -> 当前 Process 节点决定可用规则
  -> 当前用户 Type 节点必须匹配该规则结论
  -> 公式 premise 交证明器，子 judgment 消费对应 Type 子树
  -> 全部结构和公式均通过后，返回用户给出的 TypeAST
```

Checker 不调用 Constructor，也不先构造一棵 Type 再做整树相等比较。这一点保证
Checker 是规则定向的验证器，而不是 Constructor 的包装器。

### 1.3 Type 状态迁移图

`build_type_transition_graph(type_ast, ...)` 不再读取 HCSP 或 Gamma/Theta。它先把
正式 Type AST 单向转换为规范化 Type，再编译成等递归的循环项图，最后在项图上
穷尽项目实现的 Table 3 单步关系：

```text
TypeAST -> Normalized Type -> EquiRecursiveStateKey
        -> Table 3 单步后继 -> BFS 完整可达闭包
        -> TypeTransitionGraph
```

图节点真正用于判等和继续推导的是循环项图键；节点携带的规范 Type 只是由该键
确定性重建的可读代表。因此递归展开产生的不同有限语法树不会被误当成不同状态。

---

## 2. 前端实际接受并建立什么对象

### 2.1 顶层分节

Constructor 源码固定按以下顺序解析：

```text
gamma(...) [parameters(...) where(...)] theta(...) process {...}
```

Checker 在末尾再要求一个 `type ...` 分节。参数段可省略，省略时得到空声明和恒真
约束。解析器在一个共享 token 流上工作，不按字符串分割分节，所以词法错误、括号
错误和 validation 错误都保留全局行列。

所有用户标识符使用项目统一的 ASCII 规则：

```text
[A-Za-z_][A-Za-z0-9_]*
```

关键字、Unicode 标识符和会在 Python 中发生 NFKC 归一化的混淆写法不会进入正式
AST。表达式也由项目前端按自己的优先级解析；公开输入不依赖 Python `ast.parse`
的 Unicode 或数字扩展。

### 2.2 Process 语句块不是任意二元 Sequence 树

语句块中的分号表示顺序执行，但前端不会机械地把全部语句右嵌套为
`Sequence(P,Q)`。当前 Process AST 为贴合项目实际 Table 2 规则，采用以下规范形：

- `If(B,P1,P2,continuation=Q)` 自己持有公共后继 `Q`；
- `InternalChoice(P1,...,Pk,continuation=Q)` 自己持有公共后继 `Q`；
- `ODE(...,continuation=Q)` 自己持有顺序后继 `Q`；
- 只有其他相邻动作继续用二元 `Sequence`；
- `Sequence.of(...)` 会把后续语句附着到上述控制节点的 `continuation` 字段；
- 直接构造 `Sequence(control_node,Q)` 会被 AST 拒绝，防止产生第二种等价结构。

所以源码：

```text
if (B) {P1} else {P2}; Q
```

内部不是 `Sequence(If(B,P1,P2),Q)`，而是
`If(B,P1,P2,continuation=Q)`。内部选择与 ODE 同理。这样每条规则可以直接把
同一个 `Q` 交给各自子 judgment，不需要额外定义一个通用的类型级 T-Seq。

当前用户源码还要求每个 ODE 显式具有顺序后继。没有实际后继时也必须写
`; skip`。原因不是 `skip` 有额外行为，而是两条 ODE 规则需要区分“deadline 后继
不可达”和“存在一个可达但没有通信行为的空后继”；第 7 节会说明双候选选择。

解析深层语句块时，前端使用显式任务栈，而不是依赖 Python 调用栈递归进入每层
控制结构。这样大输入的解析承载能力由项目的显式规模预算决定，不直接受 Python
默认递归深度限制。

### 2.3 Process AST 构造期检查

Process AST 构造器不只是保存字段，它还立即执行以下结构检查：

1. E、P、S 三个语法范畴不能混放；`Parallel` 不能成为顺序 Process 的后继；
2. 通信支持一个或多个独立标量槽，不支持一个 tuple 值；输入目标必须互异；
3. `EventChoice` 保存非空的多元通信分支表，空事件唯一表示为 `EmptyEvent`；
4. `InternalChoice` 保存至少两个分支和一个公共后继，不再编码成二元选择链；
5. Assumption 2.1 的自由/绑定变量条件、进程变量条件和并行通道条件在构造期检查；
6. `ch?(x1,...,xn)` 的输入绑定只作用于相应顺序后继或事件分支后继；
7. 并行分量不能共享可变值变量、进程变量、同向输入通道或同向输出通道；一入
   一出使用同一通道是允许的同步；
8. 完整 source 已经解析出的共享只读参数，会在并行共享变量检查中被排除；直接
   使用低层 AST API 时没有该参数上下文，仍采用严格检查；
9. `mu X.P` 在构造期检查 Assumption 2.2：回到当前 `X` 的每条路径必须先经过
   输入或输出；内层同名 `mu` 会遮蔽外层绑定；
10. 内部选择自动补出的 `Skip` 公共尾不算实际操作，因此不会把本来位于尾部的
    递归调用误判为非尾调用。

这些错误发生在 Table 2 后端启动之前。它们属于“输入不能形成项目认可的 Process
AST”，而不是“形成 AST 后某条证明义务为假”。

### 2.4 ODE 批注和隐藏时钟

每个 ODE 必须携带 `ODEAnnotation`：

- `delay` 必填，只能是可静态计算的非负有理常量或正无穷；
- 有限值统一保存为精确 `Fraction`，不是二进制浮点近似；
- `safety` 可省略，省略时规范为 `true`；
- `interrupt` 可省略，省略时规范为 `EmptyEvent`；
- `wait(d)` 语法糖已删除，不存在第二套特殊时延节点。

每个 ODE 自动拥有一个源级名称为 `t` 的独立局部时钟。用户可以在该 ODE 的导数
右端、演化域和 safety 中读取 `t`；实现自动加入入口 `t=0` 和导数 `t'=1`。
`t` 不能作为用户 ODE 左端，不进入 Gamma、连续向量声明、状态变量集合或 ODE
外部后继作用域。不同 ODE 的内部逻辑符号彼此新鲜。

---

## 3. Gamma、Theta、参数与 Configuration 的真实语义

### 3.1 Gamma

Gamma 中的标量类型只有：

```text
Bool, Nat, Int, Rational, Real
```

数值子类型链是：

```text
Nat <: Int <: Rational <: Real
```

Gamma 还允许独立的 `ContinuousType((x1,...,xn))` 项。它不是一个可在表达式中
读取的 tuple 状态值，也不携带轨迹性质；它只登记“允许有一个 ODE 的用户左端
变量集合恰好为 `{x1,...,xn}`”。每个成员必须另外声明为 `Real`。ODE 的隐藏
时钟 `t` 不参与集合匹配。连续演化的安全性质只来自该 ODE 自己的 safety 批注。

Gamma 是声明环境，不要求每个标量都在初态中赋值，也允许包含当前分量没有使用的
声明。当前并行实现把同一个完整 Gamma 交给每个配置子 judgment；它不按语法变量
集合裁剪局部 Gamma。真正必须互斥的是分量拥有的可变状态域，而不是 Gamma 声明
本身。状态域由 Process 使用变量与初态键合并后计算，并排除共享参数；有重叠就
拒绝。

这与论文 Table 2 中常见的 `Gamma = Gamma_1 uplus ... uplus Gamma_n` 表面写法不同，
是项目明确采用的工程语义：Gamma 可以是各分量所需声明的共同超集，而 Process
AST 和配置组合负责保证没有共享可变状态。

### 3.2 全局参数

`ParameterEnvironment` 包含基础类型声明和约束 `H`。参数：

- 可被所有并行分量共同读取；
- 可出现在 HCSP 表达式、Theta refinement、FOL 和 dL 公式中；
- 与 Gamma 名字必须不交；
- 不能作为赋值目标、输入目标、ODE 左端或初态键；
- 在正式规则前先检查类型、有定义性和可满足性。

参数约束被证明不可满足时，后端不继续。Z3 只能返回 `unknown` 时，项目保留一条
未决诊断并继续规则过程；Constructor 最终结果不可信，Checker 最终不接受。

### 3.3 Theta

每个 `ChannelType` 至少有一个槽，每槽仍是上面的单值基础类型。多槽签名表示一次
同步传多个独立标量，槽顺序有语义。一个通道还保存：

- 与槽一一对应且互异的 binder；
- 一个联合 refinement；省略时为 `true`。

refinement 中 binder 是局部名字并优先遮蔽同名外部标量；其余自由名可以来自
Gamma 标量和全局参数。环境准备阶段会主动翻译 Theta 中的每个 refinement，
包括 Process 没有使用的通道。因此未使用通道中的未绑定名字、非 Bool 公式或
静态表达式错误也会导致环境不合法，而不会被惰性忽略。

### 3.4 初态和路径条件

`Configuration(state, process, path_condition)` 中的 `state` 是部分状态：

- `dom(state)` 可以是真正 Gamma 标量键的真子集；
- 未赋值标量仍作为符号变量留在公式中；
- 未知键、连续向量声明标签和参数键都会被拒绝；
- T-sigma 判定的是参数约束蕴含代入部分状态后的路径条件，而不是要求 state
  完整枚举 Gamma。

顶层并行可以给每个配置分别提供局部路径，也可以全部使用一个全局默认路径；不能
一部分有局部路径、一部分没有，也不能同时给出非平凡全局路径和一组完整局部路径。

---

## 4. 表达式和证明器实际处理的对象

表达式 AST 本身是无类型语法树。进入规则后，`ExpressionTranslator` 才结合当前
Gamma 标量、参数、局部 binder、赋值后的符号表和 ODE 局部时钟产生：

- Z3 项；
- `Bool/Nat/Int/Rational/Real` 结果类型；
- 除零、开方非负等有定义性条件。

一阶算术、状态有效性和 refinement 使用 Z3。ODE safety、domain 与 boundary
被转换成 dL 公式并交给 KeYmaera X。证明结果采用工程上的三值：

- `true`：该 premise 已证明；
- `false`：该规则被否证，当前分支立即停止；
- `unknown`：超时、后端缺失或证明器不能决定；保留证据并继续结构推导。

论文规则通常把前提写成“有效/可证”二值判断；`unknown` 是实现为应对不完备证明器
增加的第三种运行状态，不是论文中的新逻辑真值。

每个 `ProofObligation` 同时保存原始公式、实际送入后端的公式、规则、判断位置、
候选归属、证明器说明和是否为最终选中规则的 active 证据。ODE 双候选中未选规则
的公式仍可出现在完整审计日志中，但不会污染选中结论的最终 verdict。

---

## 5. 共用 Table 2 规则引擎怎样执行

代码没有把一条论文规则直接写成一个递归 Python 函数。每个 `rule_t_*` 只完成：

1. 检查当前结论 judgment 的静态形状；
2. 生成有序的公式 premise 和子 judgment premise；
3. 返回一个 `conclude(children)`，说明怎样由子结论组合结果。

统一求解器用显式工作栈依序处理这些 premise。公式出现时立即调用证明器；子
judgment 完成后才执行 `conclude`。所以当前架构是“边展开规则、边证明、边组合”，
不是先把所有公式加入一个池后统一求解。赋值规则也不会把未知 `phi'` 留给池综合。

Constructor 和 Checker 共享同一 `Table2RuleEngine`：

- Constructor 执行 `conclude`，由子类型组成新的 Type AST；
- Checker 不采用构造出的结论，而是把用户 Type 拆成当前规则要求的子树，再让同一
  premise 机制继续检查。

`false` 会停止当前推导分支。`unknown` 不会制造内部“无类型”标记，规则会尽量
继续到完整结构；但最终对外语义不同：Constructor 可通过专用异常交付不可信完整
候选，Checker 仍必须报检查失败。

---

## 6. 离散规则的代码级语义

以下 `phi` 表示当前符号路径，`T` 表示顺序后继的类型。类型打印语法中的
`empty` 对应 `EmptyType`，不是错误；`bottom` 对应不可达的 `BottomType`。

### 6.1 T-End 和 T-Skip

- 终端显式 `skip` 或语句表结束得到 `EmptyType`；
- 中间 `skip;P` 只递归处理 `P`，不增加 Type 节点；
- 因此静默语句最终可以有一个可达但无通信行为的空类型，不需要伪造通信。

### 6.2 T-Assert

`assert(B);P` 要求：

1. `B` 可翻译为 Bool；
2. 当前路径蕴含 `B` 及其有定义性；
3. 在原路径下继续处理 `P`。

这里 assertion 是验证点，不是 assumption。证明成功后不会把 `B` 加入后继路径。

### 6.3 T-Assign

`x := e;P` 的实现步骤为：

1. `x` 必须是 Gamma 中的基础类型标量，不能是参数或连续向量标签；
2. 在赋值前符号状态中翻译 `e`；`x := x+1` 的右侧读取旧 `x`；
3. 要求 `type(e) <: Gamma(x)`，并证明 `e` 的有定义性；
4. 创建惰性后状态：路径公式保持原 `phi`，符号表中 `x` 指向 `e` 的旧状态项；
5. 后继每次读取 `x` 时自然得到同一替换结果；
6. 登记具体的 `phi => phi'{e/x}` 证据，然后在该后状态处理 `P`。

因此 `phi'` 由赋值语义确定，不是一个等待证明器搜索的未知谓词。项目没有实现
“收集所有 assignment premise 后统一综合后置条件”的公式池。

### 6.4 T-If

`If(B,P1,P2,continuation=Q)`：

1. 检查 guard 为 Bool 并证明其有定义性；
2. 克隆两个上下文，路径分别为 `phi and B` 与 `phi and not B`；
3. 处理 `P1;Q` 和 `P2;Q`；
4. 按 then、else 固定顺序构造二分支 `InternalChoiceType`。

分支赋值不会泄漏到兄弟分支。Checker 要求给定 Type 当前层恰有两个分支，并按
同一顺序逐项消费；不会用交换律重排分支。

### 6.5 T-In

`ch?(x1,...,xn);P`：

1. Theta 必须声明 `ch`，目标数必须等于通道槽数；
2. 参数和连续向量标签不能作为输入目标；
3. 未声明目标由对应槽类型加入局部 Gamma；已声明目标必须满足
   `slot_type <: variable_type`，例如 Real 通道不能写入 Int 变量；
4. 每槽建立独立新鲜接收符号并替换目标的旧当前值；
5. 把基础类型域约束、联合 refinement 的实例和其有定义性加入后继路径；
6. 处理 `P`，再构造
   `InfiniteDelayType(InputType(ch,T))`。

输入 refinement 是接收后可假设的条件，不生成“发送值满足 refinement”的证明。
多槽的具体类型和 binder 不写进行为 Type，仍由 Theta 决定。

### 6.6 T-Out

`ch!(e1,...,en);P`：

1. Theta 必须声明 `ch`，载荷数必须等于槽数；
2. 在当前状态翻译全部表达式；
3. 每槽要求 `type(e_i) <: slot_type_i`；
4. 证明当前路径蕴含全部表达式有定义且联合 refinement 在
   `eta_i := e_i` 后成立；
5. 状态不变地处理 `P`；
6. 构造 `InfiniteDelayType(OutputType(ch,T))`。

所以输入规则“假设 refinement”，输出规则“证明 refinement”，两者方向不同。

### 6.7 T-内部选择

项目把二元规则扩展为规范的多元形式。对于
`InternalChoice(P1,...,Pk,continuation=Q)`，分别处理每个 `P_i;Q`，然后按源码
顺序构造 `InternalChoiceType((T1,...,Tk))`。

这不是先对每个 `P_i` 求类型，再在 Type 选择外面附一个公共 `T_Q`；`Q` 的行为
属于每一个已选分支，所以被放进每个子 judgment。Type AST 在这一层保留分支分块，
供 Checker 与当前 Process 节点的元数精确对应。只有之后用于状态图的规范化 Type
才把内部选择按结合、交换和幂等律展平取商。

### 6.8 T-外部事件选择

`EventChoice((c1,P1),...,(ck,Pk))` 为每个通信守卫建立一个子 judgment。该子
judgment 先应用 T-In 或 T-Out，再继续相应分支及 ODE 公共尾。规则随后从每个
`InfiniteDelayType` 取出唯一通信前缀，形成 angelic type：

- 0 个分支：`NoInterruptType`；
- 1 个分支：直接使用 `InputType` 或 `OutputType`；
- 2 个以上：`ExternalChoiceType`。

多分支保持源码顺序；项目不要求不同分支的通道前缀唯一。Checker 要求分支数、
顺序、输入/输出方向和通道逐项匹配。

---

## 7. ODE 两条规则的实际实现

ODE 是项目对 Table 2 做工程化处理最多的部分，不能用一句“生成 dL 义务”概括。

### 7.1 进入证明前的静态检查

后端先检查：

- 用户 ODE 左端不重复，且每个变量是 Gamma 中的 `Real` 标量；
- 左端变量集合与某个 `ContinuousType` 恰好相等；
- 参数不能被连续演化；
- 每个导数是数值表达式；
- domain 和 safety 是 Bool；
- 所有偏函数的有定义性条件被保留；
- delay 已由 AST 保证为非负有理数或正无穷。

这些静态条件失败时不建立正式 delay Type。

### 7.2 dL 入口快照

每条 ODE 义务使用一个独立符号快照：当前赋值产生的 symbols 被嵌入前置状态，
隐藏时钟设为 0，并向用户方程追加 `t'=1`。用户 ODE 公式中的源名 `t` 在这个局部
作用域遮蔽 Gamma 中可能存在的普通同名变量；离开 ODE 后局部时钟被丢弃。

### 7.3 所有候选共有的 safety 义务

非恒真 safety 生成的目标在数学上表达：从当前前置路径且 `t=0` 出发，沿用户
ODE 和 `t'=1` 演化，在 `t<=d` 的相关区间内保持节点批注 safety。导数、domain、
safety 的有定义性也进入对应逻辑项。若 safety 规范化后就是 `true`，可由本地
快捷路径直接判真，不调用外部 dL 后端。

Gamma 的 `ContinuousType` 不向 safety 追加任何性质；它只检查 ODE 左端集合。

### 7.4 通信保证候选 T-unrhd

该候选表示 ODE 保证会在 deadline 前被某个通信打断，deadline 后继不可达。
除 safety 外，代码证明 domain 保持义务 `pre => [F]B`。它不增加“在 `t=d` 时
离开 B”的 boundary 义务，因为该结论本身不声明存在自然 timeout 迁移。

事件分支在 `B and safety` 的 ODE 后上下文中处理，结果 A 与 `BottomType` 组合为：

```text
FiniteDelayType(d, A, BottomType())
```

`BottomType` 在这里是正式不可达行为，不是错误恢复值。若 `d=infinity`，构造
`InfiniteDelayType(A)`；其自然到时后继同样固定为不可达。

### 7.5 自然 timeout 候选 T-unrhd-prime

有限 delay 且存在可达顺序后继时，代码额外建立 boundary dL 义务，表达：

```text
t < d  -> B
t = d  -> not B
```

通信中断分支在 `safety` 上下文处理；自然结束 fallback 在
`not B and safety` 上下文处理。这里按照项目决定直接使用 Table 2 给出的 ODE
后置条件，不额外保留进入 ODE 前、且不涉及演化变量的 frame facts。若用户需要
后继证明这些事实，必须通过足够强的 safety/domain/其他批注重新建立。

最终构造：

```text
FiniteDelayType(d, A, T_fallback)
```

`T_fallback` 可以是 `EmptyType`，表示 deadline 后继可达但不再发生通信；它不能
用 `BottomType` 代替。

### 7.6 为什么 ODE;skip 要试两条规则

源码要求无实际后继也显式写 `skip`，而“真实后继恰好就是空行为”在语法上也是
同一个 `skip`。所以 Constructor 对有限 `ODE;skip` 在隔离证据区分别试用两条
规则：

1. 每个候选拥有独立证明义务、诊断和推导步骤；
2. 已证明候选优先；若已证明候选的类型相互等价，选第一个规范代表；
3. 两个候选都证明为真但类型不等价，报告规则互斥性被破坏，不能伪造唯一类型；
4. 没有已证候选但存在完整 `unknown` 候选时，等价者取规范代表；不等价时优先
   保留自然 timeout 候选并显式标为临时、不可信；
5. 结构失败或被否证的候选不会成为最终结论；其证据仅用于完整审计；
6. 有已证明候选时，未选中的 `unknown` 候选不降低可信性，因为项目把两条规则的
   适用条件视为互斥。

有限非 `skip` 后继只使用自然 timeout 规则。无穷 delay 没有自然 timeout，只使用
通信保证形式。

Checker 不自行发明另一套 ODE 规则。它先根据用户 Type 的 delay、A、以及后继是
`BottomType` 还是普通 ProcessType 筛选可匹配候选，再用同一套静态检查、dL 义务
和 `ODE;skip` 隔离机制验证。因而 Bottom 后继不会被错误当作可 timeout 后继。

---

## 8. 递归规则的实际实现

### 8.1 Process AST 层

`Mu(X,P,invariant=I)` 的批注不变量省略时为 true。构造期 Assumption 2.2 已要求
回边经过通信。项目只实现通信守卫的尾递归片段：`mu` 后不能再有可观察顺序后继；
自动补出的空 `Skip` 会被忽略。

### 8.2 T-mu

Constructor：

1. 证明当前路径蕴含递归不变量 `I`；
2. 为源过程变量建立新鲜 TypeVar，而不是复用源码名字；
3. 为 Gamma 标量建立全新符号，只保留参数约束、基础类型域和 `I`，不沿用调用点
   的具体赋值历史；
4. 在该抽象递归入口处理递归体，终端为新鲜 TypeVar；
5. 若结果确实引用该 TypeVar，再检查类型级通信守卫并构造 `MuType`；
6. 若递归体实际没有回边，不保留冗余 `MuType`，直接返回体类型。

### 8.3 T-X

`Var(X)` 必须解析到当前词法环境中的绑定，位于尾位置，并证明当前路径重新蕴含
该绑定的不变量；结论是对应新鲜 TypeVar。内层同名 `mu` 会遮蔽外层。

Checker 为源码绑定器和用户 Type 绑定器建立同一个不透明身份，而不是简单保存
字符串到字符串的映射。这样内外层都叫 `X` 或 `t` 时，alpha 等价仍按词法作用域
正确匹配，不会把重名递归绑定器混为一层。

---

## 9. 顶层 T-sigma 与并行

### 9.1 T-sigma

配置叶子先检查部分 state，再证明“所有满足参数约束的参数赋值都使该配置的初始
状态满足路径条件”。之后才处理 Process/System 子 judgment。state 中缺少某个
Gamma 标量是允许的，该符号仍留在有效性公式中；state 多出未知名字则直接失败。

`Configuration({}, Parallel(...))` 只作为空 Gamma、空 state、true 路径的无状态
便捷入口。只要有状态或非平凡路径，顶层并行必须拆成多个 Configuration 叶子，
让每个分量分别经过 T-sigma。

### 9.2 T-parallel

项目接受一个或多个配置，并：

1. 把完整 Gamma、Theta 和参数环境交给每个分量；
2. 计算各分量实际拥有的可变状态域；
3. 拒绝未声明且又不是输入新绑定的变量；
4. 拒绝两个分量拥有同一可变状态；
5. 逐分量构造或检查 Type；
6. 按源码配置顺序构造/匹配 `ParallelType`。

并行分量的次序在 Table 3 图规范化阶段会按交换、结合和幂等语义取商，但正式
Type AST 与 Checker 的输入匹配仍保留源码分量顺序，便于把规则子 judgment 与
用户 Type 分量一一对应。

---

## 10. Constructor 和 Checker 的相同与不同

两者共用：

- 环境规范化和全部 Theta refinement 预检查；
- 表达式静态类型、有定义性和符号状态；
- T-sigma、T-parallel、离散规则、ODE dL 公式和递归上下文；
- `false` 短路、`unknown` 留证据继续的内部调度；
- Z3、KeYmaera X、证明义务和详细日志格式。

两者不同：

| 情形 | Constructor | Checker |
|---|---|---|
| 子 judgment 成功 | 组合一个新 Type 节点 | 消费用户 Type 的对应子树 |
| Type 分组 | 按 Process 当前规则产生 | 必须由用户括号给出并精确匹配 |
| 内部选择 | 构造同元数、同顺序分支 | 检查同元数、同顺序，不搜索 AC 重排 |
| 递归变量 | 生成新鲜内部 TypeVar | 用 alpha 环境对应用户 TypeVar |
| 证明 `unknown` 且结构完整 | 抛不可信构造异常并携带候选 | 抛检查异常，不返回暂时接受的 Type |
| Type 来源 | 后端生成 | 用户 `type` 分节提供 |

Constructor 的可信输出在同一 Gamma、Theta、参数、初态、路径和证明后端条件下，
序列化成规范 Type 输入后应被 Checker 接受。自动化测试用该往返性质覆盖离散语句、
分支、递归、并行和 ODE。它不是“所有 Python 对象在所有环境下必然往返”的承诺：
改变证明超时、KeYmaera X 可用性、初态或路径条件，结果当然可能不同。

---

## 11. 正式 Type AST 中各个空值的区别

当前实现保留三个不能混用的概念：

- `NoInterruptType`：Angelic Type 的空中断集合，只能放在 A 位置；
- `EmptyType`：可达、但以后不再发生通信的正常 Process Type；`skip` 构造它；
- `BottomType`：不可达的 Process Type；用于 T-unrhd 或无限时延的 deadline 后继。

因此：

```text
delay(d, no interrupts, EmptyType)
```

表示等待到 d 后到达正常空行为；而

```text
delay(d, A, BottomType)
```

表示规则保证 deadline 后继不会被到达。构造失败从不使用 `BottomType` 占位，
而是用内部 failure 标记和结构化异常表示。

Type AST 还刻意保留内部选择的括号分块和并行分量顺序，供 Checker 精确匹配；
状态图使用的规范化 Type 是另一种数据结构，才对内部选择、外部选择和并行执行
相应的结合/交换/幂等取商。

---

## 12. Table 3 图后端的实际语义

第三接口先做单向规范化：

- 多元内部选择递归展平、排序、去重；
- 多元外部选择排序、去重；
- 并行分量展平、排序、去重；
- 递归绑定器转换成位置化绑定，不再以用户变量名判等；
- delay、Bottom、Empty 和通信方向保持语义区别。

规范 Type 随后被最小化成等递归循环项图。Table 3 单步规则作用于这个项图，不是
作用于打印 AST。实现枚举所有非确定性后继：内部选择的每个分支、任意可同步的
并行分量对、通信后继和时间后继都会产生边。并行中处于第几个分量不构成标签语义。

时间规则采用项目明确选择的“最大关键时间步”：一次只走到所有可共同等待分量的
下一个关键 deadline，不枚举可分解为 `d1+d2` 的任意中间等待点。`EmptyType` 不阻塞
其他分量等待，`BottomType` 不允许产生 timeout 后继。

BFS 以循环项图键去重状态，以 `(source,label,target)` 去重边；同一边的不同规则
推导保存在 `derivations` 中。规模上限是失败保护而不是截断语义：达到
`max_states` 或 `max_transitions` 会抛出结构化图异常，不返回可能被误认为完整的
部分图。

---

## 13. 当前项目相对论文表面的明确扩展与限制

下表是人工核对时最容易遗漏的部分：

| 项目 | 当前代码行为 |
|---|---|
| 多标量通信 | `ch?(x1,...,xn)` / `ch!(e1,...,en)`；Type 只记方向和通道，槽签名留在 Theta |
| 选择节点 | Process 的内部/外部选择直接是多元节点，不是重复二元嵌套 |
| 顺序控制规范形 | If、InternalChoice、ODE 自持公共后继；禁止外置 `Sequence(control,Q)` |
| ODE 批注 | safety 可省略为 true；delay 必填且为非负有理数或正无穷 |
| ODE 时钟 | 每个 ODE 隐式拥有局部 `t=0,t'=1`，不进入 Gamma 或连续向量 |
| ODE 空后继 | 用户显式写 `;skip`；后端隔离试用通信保证和自然 timeout 两候选 |
| ContinuousType | 只登记完整 ODE 左端集合，不保存轨迹性质 |
| Gamma 并行语义 | 每个分量看到完整 Gamma；另行检查实际可变状态所有权不交 |
| 共享参数 | 独立只读环境，可跨并行读取并进入 refinement/FOL/dL |
| 赋值后置条件 | 惰性确定性最强后状态；不综合未知谓词 `phi'` |
| Assert | 验证但不把断言加入后继假设 |
| 证明结果 | 工程三值 true/false/unknown；unknown 继续结构推导但不算可信成功 |
| Checker 选择匹配 | 按当前 Process 节点的元数、括号分块和顺序精确匹配，不搜索交换/结合变形 |
| 递归 | 通信守卫的尾递归片段；抽象入口只保留参数约束、类型域和递归不变量 |
| Table 3 时间 | 只生成到下一最大关键 deadline 的时间边 |
| 状态等价 | 在等递归循环项图上取商；打印规范 AST 不参与状态判等 |

这些行为有的是论文规则的直接算法化，有的是项目为明确输入、证明器边界、可扩展性
或状态图有限表示做出的决定。修改其中任何一项时，至少需要同步对应专题文档、规则
单元测试、Constructor/Checker 往返测试，以及公开接口的 result/full 日志测试。

---

## 14. 源码定位表

| 功能 | 当前权威实现 |
|---|---|
| 完整 source 与 Process lowering | `frontend/type_constructor_frontend/parser.py` |
| Type 输入解析 | `frontend/type_syntax/parser.py` |
| Process/ODE/Assumption AST | `data_structures/process_ast/ast.py` |
| 正式 Type AST | `data_structures/type_ast/ast.py` |
| Gamma/Theta/参数/Configuration | `data_structures/runtime_context/model.py` |
| 共享环境准备 | `backend/common/environment.py`、`rule_engine.py` |
| Table 2 规则与证明调度 | `backend/common/rule_engine.py` |
| Constructor 结果组合 | `backend/type_constructor/constructor.py` |
| Checker 类型定向消费 | `backend/type_checker/checker.py` |
| 表达式/Z3 | `backend/common/logic.py` |
| dL 公式 | `backend/common/dl.py` |
| KeYmaera X | `backend/common/keymaerax.py` |
| 规范化 Type AST | `data_structures/normalized_type_ast/` |
| 等递归项图 | `backend/type_operational_semantics/regular_tree.py` |
| Table 3 单步 | `backend/type_operational_semantics/table3.py` |
| 可达图 BFS | `backend/type_operational_semantics/graph_builder.py` |
| 三个公开接口和结构化异常 | `api.py` |

这张表说明“某项行为由哪里决定”。前端 EBNF 文档不是 Table 2 语义实现，Type
AST 的 `__str__` 也不是图状态判等算法；审计时应进入相应权威层，而不是从展示文本
反推内部语义。
