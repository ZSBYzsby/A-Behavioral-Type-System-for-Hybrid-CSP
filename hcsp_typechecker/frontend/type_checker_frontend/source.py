"""TypeChecker 前端的不可变组合解析结果。"""

from __future__ import annotations

from dataclasses import dataclass

from ...data_structures.type_ast.ast import ConfigurationType
from ..type_constructor_frontend.source import ParsedHCSPSource


@dataclass(frozen=True, slots=True)
class ParsedTypeCheckingSource:
    """把一次完整 HCSP 输入与同一文本中的用户 Type 绑定。"""

    program: ParsedHCSPSource
    expected_type: ConfigurationType

    def __post_init__(self) -> None:
        """拒绝非正式的程序解析记录或 Type AST。"""

        if not isinstance(self.program, ParsedHCSPSource):
            raise TypeError("program must be a ParsedHCSPSource")
        if not isinstance(self.expected_type, ConfigurationType):
            raise TypeError("expected_type must be a ConfigurationType")
