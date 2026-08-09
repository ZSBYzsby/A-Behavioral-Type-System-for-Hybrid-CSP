"""表达式 AST 与构造边界测试。

测试内容
--------
1. HCSP 构造器把字符串表达式立即规范化为项目 ``Expr`` 节点。
2. 已构造的 ``Expr`` 保持对象身份，不被重复解析。
3. 外部表达式对象在项目 AST 输入边界被拒绝。
4. 抽象表达式根类 ``Expr`` 不能被直接实例化。

完整的字符串支持/拒绝语法及整棵表达式树检查集中在
``test_expression_parsing.py``，本文件不重复这些解析器测试。

论文对应
--------
覆盖 Section 2.1 中 ``e`` 和 ``B`` 进入赋值、断言等 HCSP 构造器时的项目
表示边界；表达式内部文法是本项目为论文未展开的表达式层给出的严格实现。
"""

from __future__ import annotations

import unittest

from hcsp_typechecker._internal import (
    Assert,
    Assign,
    BinaryExpr,
    CompareExpr,
    Expr,
    Literal,
    Variable,
    ensure_expr,
)


class ExpressionAstTests(unittest.TestCase):
    """验证便捷输入只在构造边界存在，内部始终保存严格 AST。"""

    # 测试输入：直接调用抽象表达式根类 ``Expr()``。
    # 预期行为：Python 在构造边界抛出 TypeError，不产生无具体语法的节点。
    # 检查内容：锁定 get_vars 是 abstractmethod，而不是延迟到调用时才失败。
    # 论文对应：表达式范畴只能由项目明确支持的具体 e/B 产生式构造。
    def test_expr_base_class_cannot_be_instantiated(self) -> None:
        """裸 Expr 不代表任何受支持表达式语法，必须保持抽象。"""

        with self.assertRaises(TypeError):
            Expr()

    # 测试输入：Assign("x", "y + 1") 和 Assert("0 <= x < limit")。
    # 预期行为：字符串立即变成 Variable/BinaryExpr/CompareExpr 节点。
    # 检查内容：核对字段类型及两个节点递归收集出的变量集合。
    # 论文对应：Section 2.1 的赋值 ``x := e`` 与断言 ``assert(B)``。
    def test_process_constructor_normalizes_string_expression(self) -> None:
        """HCSP 构造器应立即把字符串源码转换为项目表达式节点。"""
        assignment = Assign("x", "y + 1")
        assertion = Assert("0 <= x < limit")

        self.assertIsInstance(assignment.target, Variable)
        self.assertIsInstance(assignment.expression, BinaryExpr)
        self.assertIsInstance(assertion.condition, CompareExpr)
        self.assertEqual(assignment.get_vars(), {"x", "y"})
        self.assertEqual(assertion.get_vars(), {"x", "limit"})

    # 测试输入：手工构造的 ``x + 1`` BinaryExpr 对象。
    # 预期行为：ensure_expr 和 Assign 均保存同一对象，不复制或重解析。
    # 检查内容：使用对象身份断言检查 AST 构造边界的幂等性。
    # 论文对应：Section 2.1 的表达式 ``e`` 在内部已有表示时保持语义不变。
    def test_explicit_ast_is_preserved(self) -> None:
        """已构造的项目表达式应原样进入 HCSP 节点，不做二次猜测。"""
        expression = BinaryExpr("+", Variable("x"), Literal(1))

        self.assertIs(ensure_expr(expression), expression)
        self.assertIs(Assign("x", expression).expression, expression)

    # 测试输入：把任意 ``object()`` 作为赋值右值传入。
    # 预期行为：构造器抛出 TypeError，并明确要求项目 Expr。
    # 检查内容：防止外部对象凭字段或类名绕过严格表达式边界。
    # 论文对应：保证赋值产生式右侧确实属于项目实现的表达式范畴 ``e``。
    def test_foreign_expression_object_is_rejected(self) -> None:
        """任意外部对象不能通过字段或类名伪装成项目表达式。"""
        with self.assertRaisesRegex(TypeError, "project Expr"):
            Assign("x", object())  # type: ignore[arg-type]

if __name__ == "__main__":
    unittest.main()
