# 第四接口：Type 状态图上的死锁与活锁分析

本文件说明当前代码怎样在第三接口返回的完整 `TypeTransitionGraph` 上实现论文
Definition 4.5--4.7 的死锁自由、活锁自由和锁自由判断。这里描述的是实际代码行为，
包括数据结构、算法、反例、复杂度和工程边界。

## 1. 接口契约

```python
from hcsp_typechecker import analyze_type_lock_freedom

report = analyze_type_lock_freedom(graph, output="result")
```

输入必须是 `build_type_transition_graph(type_ast)` 得到的完整可达图。成功总是返回
`LockFreedomReport`；发现死锁或活锁是正常性质结论，不是 Python 异常。输入不是图时
抛 `invalid-graph`；图中存在从初态不可达的孤立状态时抛 `incomplete-graph`。
接口可以验证所有已存状态都可达，但无法仅凭结果对象反推出是否有人手工删掉了某条
本应存在的 Table 3 边；因此完整性保证以“图来自第三接口”为调用前提。

## 2. 当前实现采用的数学判定

### 2.1 死锁

状态 `S` 是死锁见证源，当且仅当图中有迁移
`S -- time(infinity, ready=R) --> S'` 且 `R` 非空。这直接实现 Definition 4.5。
`EmptyType` 或 `BottomType` 的无出边状态不是这种死锁；
`time(infinity, ready={})` 也不满足非空 ready 条件。

### 2.2 活锁

代码只保留 `SilentTransitionLabel`（展示为 `tau`）边。如果该可达有向子图存在环，
就存在无限静默推导 `T ->^omega`，因而满足 Definition 4.6。判断采用存在语义：
环上即使还有退出边，只要可以一直选择静默环，仍是活锁。含正时间边的循环不是
纯静默环。

### 2.3 锁自由

`report.lock_free` 等价于
`report.deadlock_free and report.livelock_free`。两种反例独立搜索，可以同时存在。

## 3. 报告与反例数据

`LockFreedomReport` 保存状态/边计数、三个布尔结论，以及可选的
`deadlock_witness` 和 `livelock_witness`。`TransitionPath` 保存真正的
`TypeTransition` 序列，并在构造时验证边首尾相接。

死锁见证由初态到死锁状态的 BFS 最短 `prefix` 和最终 `infinite_wait` 边组成。
活锁见证由初态到环入口的 `prefix` 以及至少一条边、首尾相同且全部为 `tau` 的
`cycle` 组成。调用者可以继续读取每条边的标签和 Table 3 `derivations`。

## 4. 高负载算法

### 4.1 CSR 出边索引

分析器首先用两遍线性扫描建立压缩稀疏行索引。`offsets[s]..offsets[s+1]` 是状态
`s` 的出边区间，`edge_ids` 保持原图迁移顺序。紧凑整数数组避免为每个状态复制
Python 邻接 list/dict。

### 4.2 BFS 可达性与死锁

BFS 一次完成可达扫描、最短前缀父边记录、首条死锁边搜索和完整闭包检查。访问数
若小于图状态数，接口拒绝这张非闭包图，不返回部分性质结论。

### 4.3 显式栈 DFS 静默环

活锁使用三色 DFS，但状态栈和下一条出边位置都显式保存在数组/list 中。遇到指向
当前活动栈祖先的静默边时，以 DFS 父边和返祖边重建有限环。BFS 前缀和 DFS 环均用
循环重建，不使用递归函数。

### 4.4 复杂度

对 `|V|` 个状态和 `|E|` 条边，时间和辅助空间均为 `O(|V|+|E|)`，Python 调用栈
为 `O(1)`。回归测试包含 12000 状态长静默链和末端自环，覆盖 CSR、BFS、DFS 与
长前缀重建。真正限制来自显式图内存，而不是 Python 递归上限。

## 5. 输出与错误

- `none`：不打印；
- `result`：图规模、三项性质和紧凑反例；
- `full`：再输出可达前缀、无限等待边或静默环、规则证据和相关规范 Type 状态。

完整模式不会重复打印整张图；完整图由第三接口的 `full` 模式负责。图对象无效时
抛 `HCSPTypeLockAnalysisError`，提供 `kind`、`phase`、`reason`、`details` 和
`format_result()/format_full()`；性质为假时不抛异常。

## 6. 模块位置

```text
hcsp_typechecker/
    data_structures/type_lock_analysis/   报告、路径和反例
    backend/type_lock_analysis/           CSR、BFS、显式栈 DFS
    frontend/type_lock_analysis_syntax/   result/full 只读展示
    api.py                                公共参数、异常与输出调度
```

数据结构不依赖搜索后端，后端不打印，展示层不重新判断性质。这与项目前三个接口的
数据结构—后端—前端/门面分层保持一致。
