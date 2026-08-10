"""HCSP 项目的领域数据结构层。

``process_ast`` 定义带批注 HCSP 的 Process AST，``type_ast`` 定义行为 Type AST，
``runtime_context`` 汇集 Gamma、Theta、共享参数和 Configuration。Constructor、
Checker 的请求、报告与证明轨迹属于后端实现，不放在本层。
"""
