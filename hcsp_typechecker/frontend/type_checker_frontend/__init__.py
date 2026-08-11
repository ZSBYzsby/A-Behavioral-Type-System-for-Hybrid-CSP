"""TypeChecker 的完整 ``environment + process + type`` 组合前端。

本子包只解析并绑定同源数据，不执行 Table 2 规则或证明；稳定用户入口仍是包根
``check_hcsp_type``。
"""

from .parser import parse_typechecking_source
from .source import ParsedTypeCheckingSource

__all__ = ["ParsedTypeCheckingSource", "parse_typechecking_source"]
