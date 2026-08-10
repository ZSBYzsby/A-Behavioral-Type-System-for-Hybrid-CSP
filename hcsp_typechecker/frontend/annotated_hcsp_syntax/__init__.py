"""带批注 HCSP 与表达式输入结构。

本包对应用户输入中的 ``process`` 段及其表达式子语言。它把单独给出的
带批注 HCSP 文本转换为既有 Process/Parallel AST，或把表达式文本转换为
既有 :class:`~hcsp_typechecker.data_structures.process_ast.expressions.Expr`。完整 source 的
Gamma、参数、Theta 与 Process 组合由 :mod:`hcsp_typechecker.frontend` 负责。
"""

from .parser import parse_annotated_hcsp, parse_annotated_expression

__all__ = ["parse_annotated_expression", "parse_annotated_hcsp"]
