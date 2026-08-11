"""Gamma、Theta 与全局参数输入结构。

本包处理完整用户输入中不含 ``process`` 的类型上下文前缀，并返回项目已有的
Gamma 映射、Theta 映射和 :class:`ParameterEnvironment`。完整 source 的组合入口
位于 :mod:`hcsp_typechecker.frontend.type_constructor_frontend`；追加用户 Type 的
输入再由 :mod:`hcsp_typechecker.frontend.type_checker_frontend` 组合。
"""

from .parser import ParsedTypingContext, parse_typing_context

__all__ = ["ParsedTypingContext", "parse_typing_context"]
