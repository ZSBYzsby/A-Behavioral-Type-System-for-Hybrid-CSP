# 项目文档索引

根目录 `README.md` 只说明普通用户接口、完整输入形状和受支持边界。维护者、
审计者和希望逐条核对论文规则的读者从本目录进入详细说明。

## 用户输入

- [共享参数、Gamma、Theta 与 Process 完整语法](GAMMA_THETA_INPUT_SYNTAX.md)
- [用户给定 Type 的输入语法与 Type AST 往返](TYPE_INPUT_SYNTAX.md)
- [Process 与表达式子语法](HCSP_INPUT_SYNTAX.md)

## TypeConstructor 与内部实现

- [TypeConstructor：Process AST 到 Type AST 的真实构造过程](TYPE_CONSTRUCTOR.md)
- [TypeChecker：检查用户给定 Type 的规则递归过程](TYPE_CHECKER.md)
- [完整项目功能参考](PROJECT_FUNCTION_REFERENCE.md)
- [后端代码风格约定](BACKEND_CODE_STYLE.md)

## 文档边界

- 本目录描述当前源码版本的功能与实现。
- `gpt_need/` 保存本地论文、PPT 和历史审计材料，不是当前公开文档来源。
- `case_study/` 保存论文案例及其专用说明，案例文件不会取代这里的通用语法和
  接口文档。
