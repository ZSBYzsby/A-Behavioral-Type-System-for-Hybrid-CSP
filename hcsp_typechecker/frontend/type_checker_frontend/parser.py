"""从同一 token 流解析 TypeChecker 的环境、Process 与用户 Type。

本模块复用 Constructor 前端的完整 program prefix 语法，再从同一绝对 token
位置解析必填 ``type`` 分节；因此错误行列始终对应原始 typed source。
"""

from __future__ import annotations

from ..type_constructor_frontend.parser import Parser, _checked_source
from ..type_syntax.parser import TypeParser
from .source import ParsedTypeCheckingSource


class TypeCheckingParser(Parser):
    """在 Constructor 的 program prefix 后继续消费必填 ``type`` 分节。"""

    def parse_complete_typechecking_source(self) -> ParsedTypeCheckingSource:
        """解析 ``gamma [parameters] theta process type EOF``。"""

        program = self.parse_complete_source_without_eof()
        # 两个解析器从同一源文本得到相同 token 序列；共享 token 下标可让 Type
        # 诊断继续使用整份 source 的绝对行列，而不做字符串切片。
        type_parser = TypeParser(self.source, self.source_name)
        type_parser.index = self.index
        type_parser._expect("type")
        expected_type = type_parser._parse_configuration_type()
        self.index = type_parser.index
        self._expect("EOF")
        return ParsedTypeCheckingSource(program, expected_type)


def parse_typechecking_source(
    source: str,
    *,
    source_name: str = "<input>",
) -> ParsedTypeCheckingSource:
    """解析完整 typed source，并绑定程序记录与给定 Type AST。"""

    return TypeCheckingParser(
        _checked_source(source, source_name),
        source_name,
    ).parse_complete_typechecking_source()
