"""用户给定行为类型的具体语法前端。

本包只处理 ``type ...`` 段：:func:`parse_type_source` 把规范文本变成
既有 Type AST，:func:`format_type_source` 则把 Type AST 写回可再次解析的
规范文本。它只负责 Type AST 往返；规则推导与正确性证明由 TypeChecker 执行。
"""

from .parser import parse_type_source
from .serializer import format_type_source

__all__ = ["format_type_source", "parse_type_source"]
