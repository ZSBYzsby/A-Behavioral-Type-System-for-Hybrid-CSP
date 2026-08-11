"""HCSP 项目的领域数据结构层。

``process_ast`` 定义带批注 HCSP 的 Process AST，``type_ast`` 定义用户和 Table 2
使用的行为 Type AST，``normalized_type_ast`` 定义 Table 3 状态空间使用的规范化
Type AST，``regular_type_term_graph`` 保存等递归正规树的有限循环编码，
``type_transition_graph`` 保存状态和边，``runtime_context`` 汇集 Gamma、Theta、
共享参数和 Configuration。Constructor、Checker 与操作语义算法属于后端实现，
不放在本层。
"""
