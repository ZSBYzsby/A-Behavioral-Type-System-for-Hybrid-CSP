"""HCSP TypeConstructor 使用的内部数据结构层。

``process_ast`` 定义带批注 HCSP 的 Process AST，``type_ast`` 定义行为 Type AST，
``runtime_context`` 汇集 Gamma、Theta 和共享参数，``type_construction`` 则保存
Configuration、构造请求、证明义务、推导轨迹和报告。算法、前端和证明后端只引用
这些结构，不在自身模块中重复定义状态模型。
"""
