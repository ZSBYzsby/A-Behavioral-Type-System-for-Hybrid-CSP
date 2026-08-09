"""用户输入前端共享的源码位置和诊断异常。

词法器、语法分析器以及 Process AST lowering 都通过 :class:`HCSPInputError`
报告失败。异常保留稳定的阶段、文件名和一基行列号，既能生成带源码插入符的
用户诊断，也允许调用方读取结构化位置，而不必解析整段错误文本。
"""

from __future__ import annotations

from dataclasses import dataclass
import re
import unicodedata
from typing import Literal


InputPhase = Literal["lexical", "syntax", "validation"]


def _character_display_width(character: str) -> int:
    """近似计算一个 Unicode 字符在等宽终端中的显示列数。"""

    if unicodedata.combining(character):
        return 0
    return 2 if unicodedata.east_asian_width(character) in {"F", "W"} else 1


def _diagnostic_line(line: str, caret_index: int) -> tuple[str, int]:
    """展开制表符并返回源码显示文本及原字符索引对应的显示列。"""

    rendered: list[str] = []
    display_column = 0
    caret_column = 0
    for index, character in enumerate(line):
        if index == caret_index:
            caret_column = display_column
        if character == "\t":
            spaces = 4 - display_column % 4
            rendered.append(" " * spaces)
            display_column += spaces
        else:
            rendered.append(character)
            display_column += _character_display_width(character)
    if caret_index >= len(line):
        caret_column = display_column
    return "".join(rendered), caret_column


@dataclass(frozen=True)
class SourcePosition:
    """源文本中的零基偏移和一基行列位置。"""

    offset: int
    line: int
    column: int


class HCSPInputError(ValueError):
    """带源码位置的 HCSP 用户输入错误。"""

    def __init__(
        self,
        message: str,
        *,
        phase: InputPhase,
        source_name: str,
        source: str,
        position: SourcePosition,
        found: str | None = None,
        expected: tuple[str, ...] = (),
    ) -> None:
        """保存机器可读字段，同时初始化普通 ``ValueError`` 文本。"""

        self.message = message
        self.phase = phase
        self.source_name = source_name
        self.source = source
        self.offset = position.offset
        self.line = position.line
        self.column = position.column
        self.found = found
        self.expected = expected
        super().__init__(self.format_diagnostic())

    def format_diagnostic(self) -> str:
        """生成包含源行和插入符的可读诊断。"""

        header = (
            f"{self.source_name}:{self.line}:{self.column}: "
            f"{self.phase} error: {self.message}"
        )
        # re.split 会保留末尾换行之后的空字符串，因此 ``line`` 指向 EOF 空行时，
        # 诊断不会错误地把插入符画到上一行。
        lines = re.split(r"\r\n|\r|\n", self.source)
        if not lines:
            return header
        index = min(max(self.line - 1, 0), len(lines) - 1)
        source_line = lines[index]
        caret_column = min(max(self.column - 1, 0), len(source_line))
        rendered_line, rendered_caret = _diagnostic_line(source_line, caret_column)
        return "\n".join((header, rendered_line, " " * rendered_caret + "^"))

    def __str__(self) -> str:
        """返回稳定的用户可读诊断。"""

        return self.format_diagnostic()
