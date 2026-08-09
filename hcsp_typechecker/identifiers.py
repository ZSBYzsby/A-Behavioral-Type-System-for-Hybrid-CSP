"""项目各层共享的 HCSP 标识符词法规则。

用户输入、Expr AST、Process AST 以及后续类型环境都应使用同一种名称形状：
``[A-Za-z_][A-Za-z0-9_]*``。本模块只定义这一词法形状；``if``、``ode`` 等
保留字是否能出现在某个源码位置，仍由用户输入 lexer/parser 根据上下文判断。
"""

from __future__ import annotations

import re
from typing import Final


HCSP_IDENTIFIER_PATTERN: Final[re.Pattern[str]] = re.compile(
    r"[A-Za-z_][A-Za-z0-9_]*\Z",
    flags=re.ASCII,
)


def is_hcsp_identifier(value: object) -> bool:
    """判断对象是否是符合项目 ASCII 词法规则的完整标识符字符串。"""

    return (
        isinstance(value, str)
        and HCSP_IDENTIFIER_PATTERN.fullmatch(value) is not None
    )


def is_hcsp_identifier_start(character: str) -> bool:
    """判断单个字符能否作为 HCSP ASCII 标识符的首字符。"""

    return (
        isinstance(character, str)
        and len(character) == 1
        and (
            "A" <= character <= "Z"
            or "a" <= character <= "z"
            or character == "_"
        )
    )


def is_hcsp_identifier_continue(character: str) -> bool:
    """判断单个字符能否作为 HCSP ASCII 标识符的后续字符。"""

    return is_hcsp_identifier_start(character) or (
        isinstance(character, str)
        and len(character) == 1
        and "0" <= character <= "9"
    )
