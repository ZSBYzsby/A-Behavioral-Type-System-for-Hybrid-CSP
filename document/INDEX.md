# 项目文档索引

根目录 `README.md` 只说明普通用户接口、完整输入形状和受支持边界。维护者、
审计者和希望逐条核对论文规则的读者从本目录进入详细说明。

公开 API 的权威入口是 [README 的稳定用户接口](../README.md#稳定用户接口)；完整
调用参数、返回对象、异常字段和端到端示例见
[公共接口使用手册](PUBLIC_API_GUIDE.md)。内部数据流见
[完整功能参考的公共接口部分](PROJECT_FUNCTION_REFERENCE.md#公共接口的输入和输出)。
各语法文档只维护自身 EBNF 与 lowering 约束，不重复定义输出和异常协议。

若目标是审计“代码到底实施了哪些数学操作”，应首先阅读
[当前代码的实现语义与论文规则落地方式](IMPLEMENTATION_SEMANTICS.md)。该文档明确
区分论文判断形式、项目数据表示和工程扩展，并逐条说明实际 Table 2/3 算法；它
不会用“与论文一致”代替代码行为。

## 用户输入

- [共享参数、Gamma、Theta 与 Process 完整语法](GAMMA_THETA_INPUT_SYNTAX.md)
- [用户给定 Type 的输入语法与 Type AST 往返](TYPE_INPUT_SYNTAX.md)
- [Process 与表达式子语法](HCSP_INPUT_SYNTAX.md)

## TypeConstructor、TypeChecker 与 Table 3 图接口

- [三个稳定接口的详细使用手册](PUBLIC_API_GUIDE.md)
- [当前代码的实现语义与论文规则落地方式](IMPLEMENTATION_SEMANTICS.md)
- [TypeConstructor：Process AST 到 Type AST 的真实构造过程](TYPE_CONSTRUCTOR.md)
- [TypeChecker：检查用户给定 Type 的规则递归过程](TYPE_CHECKER.md)
- [第三接口：规范化 Type AST、循环项图与 Table 3 状态转移图](TYPE_OPERATIONAL_SEMANTICS.md)
- [规范化 Type AST 的只读输出语法](NORMALIZED_TYPE_OUTPUT_SYNTAX.md)
- [Table 3 状态迁移图的只读输出语法](TYPE_TRANSITION_GRAPH_OUTPUT_SYNTAX.md)
- [完整项目功能参考](PROJECT_FUNCTION_REFERENCE.md)
- [后端代码风格约定](BACKEND_CODE_STYLE.md)

## 文档边界

- 本目录描述当前源码版本的功能与实现。
- `gpt_need/` 保存本地论文、PPT 和历史审计材料，不是当前公开文档来源。
- `case_study/` 保存论文案例及其专用说明，案例文件不会取代这里的通用语法和
  接口文档。
