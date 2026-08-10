"""用户输入文本到项目抽象数据结构的内部前端层。

三个具体语法子包分别处理 ``annotated_hcsp_syntax``、
``typing_context_syntax`` 与 ``type_syntax``。完整 TypeConstructor source 的组合、
共享词法和源码诊断位于 ``type_constructor_frontend``；追加用户 Type 的完整检查
输入由 ``type_checker_frontend`` 组合。普通用户只调用包根 Constructor/Checker
函数；本层的模块路径不属于稳定接口。
"""
