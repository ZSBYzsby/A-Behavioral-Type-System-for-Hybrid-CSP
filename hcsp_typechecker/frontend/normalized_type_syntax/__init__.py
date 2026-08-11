"""规范化 Type AST 的只读、面向用户的结构化输出语法。

本子包只负责把状态图节点中的 ``NormalizedConfigurationType`` 渲染为稳定、
带缩进且尽量复用原用户 Type 产生式的文本。输出增加 ``normalized`` 根标记；
扁平内部选择省略原规则分块圆括号，匿名 ``mu`` 使用花括号，De Bruijn 引用使用
``recursion_position(index)``。该文本用于展示和审计，不是用户输入语言，因而
本子包有意不提供 parser，也不提供规范化 Type AST 到原 Type AST 的反向转换。
"""

from .serializer import format_normalized_type_ast


__all__ = ["format_normalized_type_ast"]
