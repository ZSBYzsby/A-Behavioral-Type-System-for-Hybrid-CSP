# 后端代码风格约定

本文约束 hcsp_typechecker/backend 的实现风格。目标是让共享规则层、
TypeConstructor 和 TypeChecker 在保持职责差异的同时，具有相同的阅读方式。

## 模块结构

每个后端模块依次组织为：

1. 文件头 docstring：说明职责、输入输出、依赖边界和明确不负责的内容；
2. future annotations；
3. 标准库、领域数据结构、当前后端相对导入；
4. 私有辅助记录；
5. 核心类，公开方法在私有实现方法之前；
6. 低层便捷函数和明确的 __all__。

data_structures 不能反向导入后端。backend/common 不能导入两个业务后端，
两个业务后端也不能彼此导入。

## 命名与类型标注

- 业务入口使用 construct/check，共享层使用 rule_t_*、_decide_proof 等
  描述实际动作的名称。
- 所有函数和方法都写参数、返回类型；__init__ 显式写 -> None。
- 后端 dataclass 统一使用 slots=True；只读请求、结果和 premise 还必须使用
  frozen=True，只有符号执行上下文等明确可变记录可以不冻结。
- 业务专属请求和报告放在各自 backend/<business>/model.py；共享证明证据放在
  backend/common/model.py。

## 注释与排版

- 模块、类和函数必须有简洁 docstring；复杂规则再在定义前补充论文对应、输入、
  构造约束和失败条件，不重复逐字解释显然的赋值语句。
- 中文说明负责解释实现语义；论文规则名、Python 标识符、FOL/dL 等正式术语
  保留原写法。
- 源码行宽不超过 100 字符，不使用通配符导入。
- result/full 报告属于展示层；规则函数只积累结构化证据，不直接打印。

这些约定由 tests/backend/test_backend_style.py 和依赖边界测试共同锁定。
