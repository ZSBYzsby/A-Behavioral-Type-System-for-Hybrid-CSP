"""TypeConstructor 所用的完整输入组合前端。

本子包维护共享词法与诊断，并把带批注 HCSP、Gamma、Theta、全局参数组合为一次
TypeConstructor 调用使用的内部 ``ParsedHCSPSource``。它不属于包根稳定接口。
"""

from ..errors import HCSPInputError, SourcePosition
from .lexer import Token, tokenize
from .parser import (
    parse_expression,
    parse_hcsp,
    parse_hcsp_source,
)
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
