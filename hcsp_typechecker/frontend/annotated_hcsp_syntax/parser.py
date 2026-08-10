"""带批注 HCSP 片段到 Process AST 的前端转换入口。

语法和正式 AST lowering 共用 TypeConstructor 前端的同一词法器、诊断格式及
构造逻辑；这里仅提供按输入结构划分的稳定内部入口，不重复维护另一套解析器。
"""

from __future__ import annotations

from ..type_constructor_frontend.parser import parse_expression, parse_hcsp
from ...data_structures.process_ast.ast import HCSP
from ...data_structures.process_ast.expressions import Expr


def parse_annotated_hcsp(
    source: str,
    *,
    source_name: str = "<process>",
) -> HCSP:
    """把一个 ``process_system`` 片段转换为既有 Process/Parallel AST。"""

    return parse_hcsp(source, source_name=source_name)


def parse_annotated_expression(
    source: str,
    *,
    source_name: str = "<expression>",
) -> Expr:
    """按 HCSP 输入语法的严格表达式子语言构造 ``Expr``。"""

    return parse_expression(source, source_name=source_name)
