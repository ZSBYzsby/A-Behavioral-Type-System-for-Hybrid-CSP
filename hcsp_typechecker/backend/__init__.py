"""HCSP 行为类型系统的后端实现。

``common`` 保存共享规则和证明基础设施；``type_constructor`` 与
``type_checker`` 分别实现类型构造和用户给定类型的检查；
``type_operational_semantics`` 根据 Table 3 从规范化 Type AST 生成状态转移图。
稳定的用户接口仍只由包根模块导出。
"""

__all__: list[str] = []
