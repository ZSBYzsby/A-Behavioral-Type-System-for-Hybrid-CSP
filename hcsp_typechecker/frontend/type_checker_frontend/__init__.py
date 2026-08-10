"""TypeChecker 的完整 ``environment + process + type`` 组合前端。"""

from .parser import parse_typechecking_source
from .source import ParsedTypeCheckingSource

__all__ = ["ParsedTypeCheckingSource", "parse_typechecking_source"]
