r"""Tool-independent expression ASTs owned by the process layer."""

from __future__ import annotations

import ast
import io
import re
import tokenize as python_tokenize
from abc import ABC, abstractmethod
from dataclasses import dataclass
from decimal import Decimal
from fractions import Fraction
from typing import Iterable, TypeAlias

from ...identifiers import is_hcsp_identifier


class Expr(ABC):
    r"""Abstract base for project expression nodes."""


    @abstractmethod
    def get_vars(self) -> set[str]:
        r"""Return free variable names from the concrete expression node."""


@dataclass(frozen=True)
class Literal(Expr):
    r"""A Boolean or numeric literal."""

    value: bool | int | float | Decimal | Fraction


    def __post_init__(self) -> None:
        r"""Reject arbitrary Python objects as literal values."""
        if not isinstance(
            self.value,
            (bool, int, float, Decimal, Fraction),
        ):
            raise TypeError(f"Unsupported literal value: {self.value!r}")


    def get_vars(self) -> set[str]:
        r"""Literals have no free variables."""
        return set()


    def __str__(self) -> str:
        r"""Render the literal in source-like diagnostic syntax."""
        return _format_expression(self)


@dataclass(frozen=True)
class Variable(Expr):
    r"""A scalar variable reference."""

    name: str


    def __post_init__(self) -> None:
        r"""Require a valid simple variable identifier."""
        if not is_hcsp_identifier(self.name):
            raise ValueError(f"Invalid variable name: {self.name!r}")


    def get_vars(self) -> set[str]:
        r"""The variable's free-variable set contains its own name."""
        return {self.name}


    def __str__(self) -> str:
        r"""Return the source variable name."""
        return _format_expression(self)


@dataclass(frozen=True)
class UnaryExpr(Expr):
    r"""Logical negation or unary numeric sign."""

    op: str
    operand: Expr


    def __post_init__(self) -> None:
        r"""Validate the unary operator and operand AST category."""
        if self.op not in {"not", "+", "-"}:
            raise ValueError(f"Unsupported unary operator: {self.op!r}")
        if not isinstance(self.operand, Expr):
            raise TypeError("Unary operand must be an Expr")


    def get_vars(self) -> set[str]:
        r"""Return the operand's free variables."""
        return _collect_expression_variables(self)


    def __str__(self) -> str:
        r"""Parenthesize unary expressions unambiguously."""
        return _format_expression(self)


@dataclass(frozen=True)
class BinaryExpr(Expr):
    r"""A binary arithmetic expression."""

    op: str
    left: Expr
    right: Expr


    def __post_init__(self) -> None:
        r"""Validate the binary operator and operand categories."""
        if self.op not in {"+", "-", "*", "/", "%", "**"}:
            raise ValueError(f"Unsupported binary operator: {self.op!r}")
        if not isinstance(self.left, Expr) or not isinstance(self.right, Expr):
            raise TypeError("Binary operands must be Expr instances")


    def get_vars(self) -> set[str]:
        r"""Union free variables of both operands."""
        return _collect_expression_variables(self)


    def __str__(self) -> str:
        r"""Preserve arithmetic grouping with parentheses."""
        return _format_expression(self)


@dataclass(frozen=True)
class BooleanExpr(Expr):
    r"""An n-ary and/or expression."""

    op: str
    operands: tuple[Expr, ...]


    def __init__(self, op: str, operands: Iterable["ExprLike"]):
        r"""Freeze at least two Boolean operands."""
        values = tuple(ensure_expr(item) for item in operands)
        if op not in {"and", "or"}:
            raise ValueError(f"Unsupported Boolean operator: {op!r}")
        if len(values) < 2:
            raise ValueError("BooleanExpr needs at least two operands")
        object.__setattr__(self, "op", op)
        object.__setattr__(self, "operands", values)


    def get_vars(self) -> set[str]:
        r"""Union free variables of all Boolean operands."""
        return _collect_expression_variables(self)


    def __str__(self) -> str:
        r"""Join parenthesized Boolean operands with their operator."""
        return _format_expression(self)


@dataclass(frozen=True)
class CompareExpr(Expr):
    r"""A relation supporting Python-style chained comparisons."""

    operands: tuple[Expr, ...]
    operators: tuple[str, ...]


    def __init__(
        self,
        operands: Iterable["ExprLike"],
        operators: Iterable[str],
    ):
        r"""Require n comparison operators connecting exactly n+1 operands."""
        values = tuple(ensure_expr(item) for item in operands)
        ops = tuple(operators)
        allowed = {"==", "!=", "<", "<=", ">", ">="}
        if not ops or any(op not in allowed for op in ops):
            raise ValueError(f"Unsupported comparison operators: {ops!r}")
        if len(values) != len(ops) + 1:
            raise ValueError("Comparison operands/operators have inconsistent arity")
        object.__setattr__(self, "operands", values)
        object.__setattr__(self, "operators", ops)


    def get_vars(self) -> set[str]:
        r"""Union variables in the comparison chain."""
        return _collect_expression_variables(self)


    def __str__(self) -> str:
        r"""Render comparisons in chain order."""
        return _format_expression(self)


@dataclass(frozen=True)
class CallExpr(Expr):
    r"""A named function call such as sqrt(x)."""

    name: str
    arguments: tuple[Expr, ...]


    def __init__(self, name: str, arguments: Iterable["ExprLike"]):
        r"""Require a simple function name; reject attribute and dynamic calls."""
        if not is_hcsp_identifier(name):
            raise ValueError(f"Invalid function name: {name!r}")
        object.__setattr__(self, "name", name)
        object.__setattr__(
            self,
            "arguments",
            tuple(ensure_expr(item) for item in arguments),
        )


    def get_vars(self) -> set[str]:
        r"""Collect argument variables without treating the function name as a variable."""
        return _collect_expression_variables(self)


    def __str__(self) -> str:
        r"""Render a named function call."""
        return _format_expression(self)


ScalarLiteral: TypeAlias = bool | int | float | Decimal | Fraction


ExprLike: TypeAlias = Expr | ScalarLiteral | str


def ensure_expr(value: ExprLike) -> Expr:
    r"""Normalize convenient Python inputs into strict expression ASTs."""
    if isinstance(value, Expr):
        return value
    if isinstance(value, (bool, int, float, Decimal, Fraction)):
        return Literal(value)
    if isinstance(value, str):
        return parse_expr(value)
    raise TypeError(
        "Expression must be a project Expr, scalar literal, or string source; "
        f"got {type(value).__name__}"
    )


def _collect_expression_variables(root: Expr) -> set[str]:
    r"""Collect expression variables with an explicit stack."""

    variables: set[str] = set()
    pending: list[Expr] = [root]
    while pending:
        node = pending.pop()
        if isinstance(node, Literal):
            continue
        if isinstance(node, Variable):
            variables.add(node.name)
            continue
        if isinstance(node, UnaryExpr):
            pending.append(node.operand)
            continue
        if isinstance(node, BinaryExpr):
            pending.extend((node.right, node.left))
            continue
        if isinstance(node, (BooleanExpr, CompareExpr)):
            pending.extend(reversed(node.operands))
            continue
        if isinstance(node, CallExpr):
            pending.extend(reversed(node.arguments))
            continue
        raise TypeError(
            "Expression variable analysis received an unsupported node: "
            f"{type(node).__name__}"
        )
    return variables


def _format_expression(root: Expr) -> str:
    r"""Format expressions iteratively while preserving existing diagnostic syntax."""

    rendered: dict[int, str] = {}
    pending: list[tuple[Expr, bool]] = [(root, False)]
    while pending:
        node, exiting = pending.pop()
        key = id(node)
        if key in rendered:
            continue
        if isinstance(node, Literal):
            rendered[key] = str(node.value)
            continue
        if isinstance(node, Variable):
            rendered[key] = node.name
            continue
        if isinstance(node, UnaryExpr):
            children = (node.operand,)
        elif isinstance(node, BinaryExpr):
            children = (node.left, node.right)
        elif isinstance(node, (BooleanExpr, CompareExpr)):
            children = node.operands
        elif isinstance(node, CallExpr):
            children = node.arguments
        else:
            raise TypeError(f"Unsupported expression node: {type(node).__name__}")
        if not exiting:
            pending.append((node, True))
            pending.extend((child, False) for child in reversed(children))
            continue
        child_text = tuple(rendered[id(child)] for child in children)
        if isinstance(node, UnaryExpr):
            separator = " " if node.op == "not" else ""
            text = f"{node.op}{separator}({child_text[0]})"
        elif isinstance(node, BinaryExpr):
            text = f"({child_text[0]} {node.op} {child_text[1]})"
        elif isinstance(node, BooleanExpr):
            text = "(" + f" {node.op} ".join(child_text) + ")"
        elif isinstance(node, CompareExpr):
            parts = [child_text[0]]
            for operator, operand in zip(node.operators, child_text[1:]):
                parts.extend((operator, operand))
            text = "(" + " ".join(parts) + ")"
        else:
            assert isinstance(node, CallExpr)
            text = f"{node.name}(" + ", ".join(child_text) + ")"
        rendered[key] = text
    return rendered[id(root)]


def ensure_variable(value: str | Variable) -> Variable:
    r"""Normalize assignment/input targets to scalar Variable nodes."""
    if isinstance(value, Variable):
        return value
    if is_hcsp_identifier(value):
        return Variable(value)
    raise TypeError(f"Expected a scalar variable name, got {value!r}")


def _normalize_expression_tokens(text: str) -> str:
    r"""Validate ASCII names and rewrite the ^ token as **."""

    try:
        tokens = list(
            python_tokenize.generate_tokens(io.StringIO(text).readline)
        )
    except (IndentationError, python_tokenize.TokenError) as exc:
        raise ValueError(f"Cannot tokenize expression {text!r}: {exc}") from exc

    for token in tokens:
        if (
            token.type == python_tokenize.NAME
            and not is_hcsp_identifier(token.string)
        ):
            raise ValueError(
                "Expression identifiers must match "
                f"[A-Za-z_][A-Za-z0-9_]*: {token.string!r}"
            )

    # Pass token types and text to untokenize; replacing ^ with ** invalidates original end
    # coordinates.
    normalized = (
        (
            token.type,
            "**"
            if token.type == python_tokenize.OP and token.string == "^"
            else token.string,
        )
        for token in tokens
    )
    return python_tokenize.untokenize(normalized)


def parse_expr(text: str) -> Expr:
    r"""Parse the supported expression-string fragment."""
    if not isinstance(text, str) or not text.strip():
        raise ValueError("Expression source must be a non-empty string")


    normalized = re.sub(r"\btrue\b", "True", text, flags=re.IGNORECASE)
    normalized = re.sub(r"\bfalse\b", "False", normalized, flags=re.IGNORECASE)
    normalized = normalized.replace("&&", " and ").replace("||", " or ")
    normalized = re.sub(r"!(?!=)", " not ", normalized)
    normalized = normalized.replace("<->", " == ")
    normalized = _normalize_expression_tokens(normalized)
    try:
        node = ast.parse(normalized.strip(), mode="eval").body
    except SyntaxError as exc:
        raise ValueError(f"Cannot parse expression {text!r}: {exc.msg}") from exc
    return _from_python_ast(node)


def _from_python_ast(node: ast.AST) -> Expr:
    r"""Convert supported Python expression AST nodes into project nodes."""
    if isinstance(node, ast.Constant):
        return Literal(node.value)
    if isinstance(node, ast.Name):
        if node.id == "True":
            return Literal(True)
        if node.id == "False":
            return Literal(False)
        return Variable(node.id)
    if isinstance(node, ast.UnaryOp):
        operators = {
            ast.Not: "not",
            ast.UAdd: "+",
            ast.USub: "-",
        }
        op = operators.get(type(node.op))
        if op is None:
            raise ValueError(f"Unsupported unary syntax: {ast.dump(node)}")
        return UnaryExpr(op, _from_python_ast(node.operand))
    if isinstance(node, ast.BinOp):
        operators = {
            ast.Add: "+",
            ast.Sub: "-",
            ast.Mult: "*",
            ast.Div: "/",
            ast.Mod: "%",
            ast.Pow: "**",
        }
        op = operators.get(type(node.op))
        if op is None:
            raise ValueError(f"Unsupported binary syntax: {ast.dump(node)}")
        return BinaryExpr(
            op,
            _from_python_ast(node.left),
            _from_python_ast(node.right),
        )
    if isinstance(node, ast.BoolOp):
        if isinstance(node.op, ast.And):
            op = "and"
        elif isinstance(node.op, ast.Or):
            op = "or"
        else:
            raise ValueError(f"Unsupported Boolean syntax: {ast.dump(node)}")
        return BooleanExpr(op, (_from_python_ast(item) for item in node.values))
    if isinstance(node, ast.Compare):
        operators = {
            ast.Eq: "==",
            ast.NotEq: "!=",
            ast.Lt: "<",
            ast.LtE: "<=",
            ast.Gt: ">",
            ast.GtE: ">=",
        }
        ops: list[str] = []
        for item in node.ops:
            op = operators.get(type(item))
            if op is None:
                raise ValueError(f"Unsupported comparison: {ast.dump(item)}")
            ops.append(op)
        return CompareExpr(
            [_from_python_ast(node.left)]
            + [_from_python_ast(item) for item in node.comparators],
            ops,
        )
    if isinstance(node, ast.Call) and isinstance(node.func, ast.Name):
        if node.keywords:
            raise ValueError("Keyword arguments are not supported in expressions")
        return CallExpr(
            node.func.id,
            (_from_python_ast(item) for item in node.args),
        )
    raise ValueError(f"Unsupported expression syntax: {ast.dump(node)}")
