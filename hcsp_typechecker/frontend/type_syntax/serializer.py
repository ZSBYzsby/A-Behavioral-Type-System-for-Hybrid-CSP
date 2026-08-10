"""将共享 Type AST 渲染函数作为 Type 前端的序列化入口。"""

from __future__ import annotations

from ...data_structures.type_ast.ast import ConfigurationType
from ...data_structures.type_ast.render import (
    format_type_source as _format_type_source,
)


def format_type_source(value: ConfigurationType) -> str:
    """输出以 ``type`` 开头、可由 :func:`parse_type_source` 无损读回的文本。"""

    return _format_type_source(value)
