"""HCSP 用户输入语法的无依赖词法器。

词法器只接受 ``document/GAMMA_THETA_INPUT_SYNTAX.md`` 及
``document/HCSP_INPUT_SYNTAX.md`` 声明的 ASCII 标识符、十进制数值、关键字和运算符。
完整 source 与 Process/Expr 片段共享这一份保留字表和 token 流，因此各个
顶层分节之间的注释、行列位置和错误指示不会因文本切分而丢失。词法器执行
最长记号匹配，不借用 Python tokenizer，因而不会静默接受 Unicode 名称、
十六进制数值等额外语法。
"""

from __future__ import annotations

from dataclasses import dataclass
import re

from ..identifiers import (
    is_hcsp_identifier_continue,
    is_hcsp_identifier_start,
)
from .errors import HCSPInputError, SourcePosition


KEYWORDS = frozenset(
    {
        "skip",
        "assert",
        "call",
        "if",
        "else",
        "choose",
        "or",
        "mu",
        "invariant",
        "ode",
        "flow",
        "dot",
        "domain",
        "safety",
        "delay",
        "interrupt",
        "on",
        "true",
        "false",
        "inf",
        "not",
        "and",
        # 完整 source 的顶层分节、环境类型构造字及规范基础类型名。
        # 即使调用低层 parse_hcsp，这些词也不能退化成 Process IDENT。
        "gamma",
        "parameters",
        "theta",
        "process",
        "continuous",
        "channel",
        "where",
        "Bool",
        "Nat",
        "Int",
        "Rational",
        "Real",
    }
)

# ``None`` 不属于本项目的 Expr。把它作为“保留但非法”的源码词，而不是让它
# 落入普通 IDENT，可避免用户误以为项目支持空值。大小写不同的 ``none`` 仍只是
# 普通、区分大小写的标识符。
_UNSUPPORTED_RESERVED_WORDS = frozenset({"None"})

# 这些界限不改变数值文法，只阻止异常大的字面量在 ``int``/``Fraction`` 转换时
# 消耗失控的内存。4096 位有效数字和绝对值 10000 的十进制指数已远超 HCSP
# 模型中的通常常量规模，同时保证错误能稳定地通过 HCSPInputError 报告。
_MAX_SIGNIFICAND_DIGITS = 4096
_MAX_ABSOLUTE_DECIMAL_EXPONENT = 10_000

_MULTI_CHARACTER_TOKENS = (
    "<->",
    ":=",
    "**",
    "&&",
    "||",
    "==",
    "!=",
    "<=",
    ">=",
)
_SINGLE_CHARACTER_TOKENS = frozenset("{}(),;:?!=+-*/%^<>")
_NUMBER_PATTERN = re.compile(
    r"(?:"
    r"(?:[0-9]+\.[0-9]*|\.[0-9]+)(?:[eE][+-]?[0-9]+)?"
    r"|[0-9]+[eE][+-]?[0-9]+"
    r"|[0-9]+"
    r")"
)


@dataclass(frozen=True)
class Token:
    """一个已分类、带起始源码位置的词法记号。"""

    kind: str
    text: str
    position: SourcePosition

    @property
    def display(self) -> str:
        """返回适合错误信息的记号文本。"""

        return "end of input" if self.kind == "EOF" else repr(self.text)


class Lexer:
    """把一个 HCSP 源字符串扫描为不可变 token 序列。"""

    def __init__(self, source: str, source_name: str) -> None:
        """验证入口类型并初始化扫描游标。"""

        if not isinstance(source, str):
            raise TypeError("HCSP source must be a string")
        if not isinstance(source_name, str) or not source_name:
            raise ValueError("source_name must be a non-empty string")
        self.source = source
        self.source_name = source_name
        self.offset = 0
        self.line = 1
        self.column = 1

    def tokenize(self) -> tuple[Token, ...]:
        """扫描全部输入并在末尾追加唯一 EOF token。"""

        tokens: list[Token] = []
        while self.offset < len(self.source):
            if self._skip_layout():
                continue
            position = self._position()
            character = self.source[self.offset]
            if self._is_identifier_start(character):
                tokens.append(self._scan_identifier(position))
                continue
            if character.isascii() and (
                character.isdigit()
                or (
                    character == "."
                    and self.offset + 1 < len(self.source)
                    and self.source[self.offset + 1].isdigit()
                )
            ):
                tokens.append(self._scan_number(position))
                continue
            matched = next(
                (
                    symbol
                    for symbol in _MULTI_CHARACTER_TOKENS
                    if self.source.startswith(symbol, self.offset)
                ),
                None,
            )
            if matched is not None:
                self._advance_text(matched)
                tokens.append(Token(matched, matched, position))
                continue
            if character in _SINGLE_CHARACTER_TOKENS:
                self._advance_text(character)
                tokens.append(Token(character, character, position))
                continue
            raise self._error(
                f"unexpected character {character!r}",
                position,
                found=character,
            )
        tokens.append(Token("EOF", "", self._position()))
        return tuple(tokens)

    def _skip_layout(self) -> bool:
        """跳过一段空白或注释，并报告是否消费了输入。"""

        if self.offset >= len(self.source):
            return False
        character = self.source[self.offset]
        if character.isspace():
            self._advance_text(
                "\r\n"
                if self.source.startswith("\r\n", self.offset)
                else character
            )
            return True
        if self.source.startswith("//", self.offset):
            while self.offset < len(self.source) and self.source[self.offset] not in "\r\n":
                self._advance_text(self.source[self.offset])
            return True
        if self.source.startswith("/*", self.offset):
            start = self._position()
            self._advance_text("/*")
            while self.offset < len(self.source) and not self.source.startswith(
                "*/", self.offset
            ):
                self._advance_text(
                    "\r\n"
                    if self.source.startswith("\r\n", self.offset)
                    else self.source[self.offset]
                )
            if self.offset >= len(self.source):
                raise self._error("unterminated block comment", start, found="EOF")
            self._advance_text("*/")
            return True
        return False

    def _scan_identifier(self, position: SourcePosition) -> Token:
        """扫描 ASCII 标识符，并识别关键字和大小写布尔字面量。"""

        start = self.offset
        while self.offset < len(self.source) and self._is_identifier_continue(
            self.source[self.offset]
        ):
            self._advance_text(self.source[self.offset])
        text = self.source[start:self.offset]
        if text in _UNSUPPORTED_RESERVED_WORDS:
            raise self._error(
                f"unsupported reserved word {text!r}",
                position,
                found=text,
            )
        lowered = text.lower()
        if lowered in {"true", "false"}:
            return Token(lowered, text, position)
        return Token(text if text in KEYWORDS else "IDENT", text, position)

    def _scan_number(self, position: SourcePosition) -> Token:
        """扫描规范十进制整数或实数，并拒绝粘连的非法后缀。"""

        match = _NUMBER_PATTERN.match(self.source, self.offset)
        if match is None:
            raise self._error("invalid numeric literal", position)
        text = match.group(0)
        self._advance_text(text)
        self._validate_numeric_size(text, position)
        if self.offset < len(self.source):
            following = self.source[self.offset]
            if self._is_identifier_continue(following) or following == ".":
                raise self._error(
                    "invalid character after numeric literal",
                    self._position(),
                    found=following,
                )
        kind = "REAL" if any(marker in text for marker in ".eE") else "INTEGER"
        return Token(kind, text, position)

    def _validate_numeric_size(
        self,
        text: str,
        position: SourcePosition,
    ) -> None:
        """拒绝会导致宿主数值转换产生异常资源开销的极端字面量。"""

        parts = re.split(r"[eE]", text, maxsplit=1)
        significand_digits = sum(character.isdigit() for character in parts[0])
        if significand_digits > _MAX_SIGNIFICAND_DIGITS:
            raise self._error(
                "numeric literal has too many significant digits "
                f"(maximum {_MAX_SIGNIFICAND_DIGITS})",
                position,
                found=text,
            )
        if len(parts) == 1:
            return
        exponent_text = parts[1].lstrip("+-")
        if (
            len(exponent_text) > 5
            or int(exponent_text) > _MAX_ABSOLUTE_DECIMAL_EXPONENT
        ):
            raise self._error(
                "decimal exponent is outside the supported range "
                f"[-{_MAX_ABSOLUTE_DECIMAL_EXPONENT}, "
                f"{_MAX_ABSOLUTE_DECIMAL_EXPONENT}]",
                position,
                found=text,
            )

    def _advance_text(self, text: str) -> None:
        """消费已知文本并正确更新 CRLF/换行位置。"""

        index = 0
        while index < len(text):
            character = text[index]
            self.offset += 1
            if character == "\r":
                if index + 1 < len(text) and text[index + 1] == "\n":
                    index += 1
                    self.offset += 1
                self.line += 1
                self.column = 1
            elif character == "\n":
                self.line += 1
                self.column = 1
            else:
                self.column += 1
            index += 1

    def _position(self) -> SourcePosition:
        """返回当前游标位置的不可变快照。"""

        return SourcePosition(self.offset, self.line, self.column)

    def _error(
        self,
        message: str,
        position: SourcePosition,
        *,
        found: str | None = None,
    ) -> HCSPInputError:
        """构造统一的词法阶段异常。"""

        return HCSPInputError(
            message,
            phase="lexical",
            source_name=self.source_name,
            source=self.source,
            position=position,
            found=found,
        )

    @staticmethod
    def _is_identifier_start(character: str) -> bool:
        """判断字符能否开始规范 ASCII 标识符。"""

        return is_hcsp_identifier_start(character)

    @staticmethod
    def _is_identifier_continue(character: str) -> bool:
        """判断字符能否继续规范 ASCII 标识符。"""

        return is_hcsp_identifier_continue(character)


def tokenize(source: str, *, source_name: str = "<input>") -> tuple[Token, ...]:
    """使用项目规范词法规则扫描一段 HCSP 用户输入。"""

    return Lexer(source, source_name).tokenize()
