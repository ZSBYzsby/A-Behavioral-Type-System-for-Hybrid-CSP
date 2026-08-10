"""用户输入文本到项目抽象数据结构的内部前端层。

三个具体语法子包分别处理 ``annotated_hcsp_syntax``、
``typing_context_syntax`` 与 ``type_syntax``。完整 TypeConstructor source 的组合、
共享词法和源码诊断位于 ``type_constructor_frontend``。普通用户始终只调用包根
``construct_hcsp_type``；本层的模块路径不属于稳定接口。
"""
