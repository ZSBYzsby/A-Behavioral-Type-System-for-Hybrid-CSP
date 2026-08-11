"""Table 3 状态迁移图的只读、面向用户的文本输出语法。

本子包把不可变 ``TypeTransitionGraph`` 渲染为状态、边、标签和规则证据清晰分区的
文本。节点类型复用 ``normalized_type_syntax``；输出不作为用户输入，因而有意不
提供 parser。
"""

from .serializer import format_type_transition_graph


__all__ = ["format_type_transition_graph"]
