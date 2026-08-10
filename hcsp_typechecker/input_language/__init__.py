"""共享参数、Gamma、Theta、HCSP Process 与 Expr 的内部解析前端。

普通用户应调用包根 ``construct_hcsp_type``，由 TypeConstructor 在内部启动完整解析；这里的
片段解析器、聚合记录、Token 和源码位置类型只供实现、测试与语法审计使用，
不属于稳定用户接口。
"""

from .errors import HCSPInputError, SourcePosition
from .lexer import Token, tokenize
from .parser import parse_expression, parse_hcsp, parse_hcsp_source
from .source import ParsedHCSPSource

__all__ = [
    "HCSPInputError",
    "ParsedHCSPSource",
    "SourcePosition",
    "Token",
    "parse_expression",
    "parse_hcsp",
    "parse_hcsp_source",
    "tokenize",
]
