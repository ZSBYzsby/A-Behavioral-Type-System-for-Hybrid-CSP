"""用户输入文本到项目抽象数据结构的内部前端层。

三个输入语法子包分别处理 ``annotated_hcsp_syntax``、
``typing_context_syntax`` 与 ``type_syntax``；``normalized_type_syntax`` 和
``type_transition_graph_syntax`` 分别只读输出规范状态与完整状态图，不接受用户输入。完整
TypeConstructor source 的组合、共享词法和源码诊断位于
``type_constructor_frontend``；追加用户 Type 的完整检查输入由
``type_checker_frontend`` 组合。普通用户只调用包根稳定接口；其余模块路径不承诺
兼容性。
"""
