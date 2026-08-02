"""表达式解析器的完整支持/拒绝语法测试。

正向测试不只断言解析成功，而是把结果与手工构造的项目 ``Expr`` AST 做结构
比较。这样可以发现运算符映射、优先级、链式比较或 HCSP 记号规范化发生的
意外变化。反向测试逐类覆盖模块头部列出的不支持语法。

测试内容
--------
1. 字面量、变量及 Decimal/Fraction 的规范化。
2. 一元、算术、布尔、比较、优先级和链式比较的精确 AST。
3. ``&&``、``||``、``!``、``<->`` 等 HCSP 便捷记号。
4. 简单函数调用、嵌套实参及整棵项目表达式树检查。
5. 条件式、属性、下标、lambda、推导式等明确排除语法。

论文对应
--------
论文 Section 2.1 使用表达式 ``e`` 和布尔条件 ``B``，Section 4.2/4.3 又在
路径条件、安全性质和递归不变量中使用公式。本文件验证项目为这些未展开的
表达式/公式位置选定的具体可解析子集，不扩展 HCSP 的进程产生式。
"""

from __future__ import annotations

import unittest
from decimal import Decimal
from fractions import Fraction

from hcsp_typechecker import (
    BinaryExpr,
    BooleanExpr,
    CallExpr,
    CompareExpr,
    Expr,
    Literal,
    UnaryExpr,
    Variable,
    ensure_expr,
    parse_expr,
)


def assert_project_expr_tree(test: unittest.TestCase, expression: Expr) -> None:
    """递归确认解析结果的整棵树只包含项目定义的 Expr 节点。"""

    test.assertIsInstance(expression, Expr)
    if isinstance(expression, (Literal, Variable)):
        return
    if isinstance(expression, UnaryExpr):
        assert_project_expr_tree(test, expression.operand)
        return
    if isinstance(expression, BinaryExpr):
        assert_project_expr_tree(test, expression.left)
        assert_project_expr_tree(test, expression.right)
        return
    if isinstance(expression, BooleanExpr):
        for item in expression.operands:
            assert_project_expr_tree(test, item)
        return
    if isinstance(expression, CompareExpr):
        for item in expression.operands:
            assert_project_expr_tree(test, item)
        return
    if isinstance(expression, CallExpr):
        for item in expression.arguments:
            assert_project_expr_tree(test, item)
        return
    test.fail(f"Unexpected Expr subclass: {type(expression).__name__}")


class SupportedAtomicExpressionParsingTests(unittest.TestCase):
    """验证标量字面量和变量的精确解析结果。"""

    # 测试输入：true/FALSE、整数和实数源码。
    # 预期行为：每个源码精确解析成对应值和 Python 类型的 Literal。
    # 检查内容：逐项结构比较并区分 Bool、整数和实数。
    # 论文对应：Section 2.1 的常量表达式 e 与通信载荷基础值。
    def test_boolean_and_numeric_literals(self) -> None:
        """解析器应区分布尔、整数和实数字面量。"""

        cases = {
            "true": Literal(True),
            "FALSE": Literal(False),
            "0": Literal(0),
            "42": Literal(42),
            "3.5": Literal(3.5),
        }
        for source, expected in cases.items():
            with self.subTest(source=source):
                self.assertEqual(parse_expr(source), expected)

    # 测试输入：带引号字符串、None 源码及直接 Literal 构造。
    # 预期行为：四种入口都立即抛出 TypeError。
    # 检查内容：确保已从表达式值域删除的 String/Unit 不会绕过解析边界。
    # 论文对应：项目把基础值类型收紧为 Bool/N/Z/Q/R，不加入额外基础类型。
    def test_string_and_unit_literals_are_rejected(self) -> None:
        """没有对应 BasicType 的字符串和 Unit 常量必须在构造期被拒绝。"""

        for source in ("'HCSP'", "None"):
            with self.subTest(source=source):
                with self.assertRaisesRegex(TypeError, "Unsupported literal value"):
                    parse_expr(source)
        for value in ("HCSP", None):
            with self.subTest(value=value):
                with self.assertRaisesRegex(TypeError, "Unsupported literal value"):
                    Literal(value)  # type: ignore[arg-type]

    # 测试输入：普通标识符源码 ``velocity``。
    # 预期行为：解析为 Variable("velocity")，而不是字符串 Literal。
    # 检查内容：直接比较节点类别和保存的名称。
    # 论文对应：Section 2.1 的状态变量及表达式 e 中的变量引用。
    def test_plain_identifier_becomes_variable(self) -> None:
        """普通标识符应生成 Variable，而不是字符串 Literal。"""

        self.assertEqual(parse_expr("velocity"), Variable("velocity"))

    # 测试输入：Decimal 和 Fraction 形式的精确数值。
    # 预期行为：两种数值都成为保存原值的 Literal。
    # 检查内容：确保非字符串精确数值入口不会丢失精度。
    # 论文对应：为 ODE 时延和普通算术表达式提供精确有理数表示。
    def test_explicit_decimal_and_fraction_inputs(self) -> None:
        """精确数值便捷输入必须进入项目 Literal AST。"""

        self.assertEqual(ensure_expr(Decimal("1.25")), Literal(Decimal("1.25")))
        self.assertEqual(ensure_expr(Fraction(1, 3)), Literal(Fraction(1, 3)))


class SupportedOperatorExpressionParsingTests(unittest.TestCase):
    """验证一元、算术、布尔和比较运算的 AST 映射。"""

    # 测试输入：``not ready``、``+x``、``-x``。
    # 预期行为：三个源码分别映射为 not、正号、负号 UnaryExpr。
    # 检查内容：逐项比较运算符字符串和唯一操作数。
    # 论文对应：Section 2.1/4.3 的 e、B 和公式允许一元逻辑/算术运算。
    def test_all_supported_unary_operators(self) -> None:
        """not、正号和负号应分别形成 UnaryExpr。"""

        cases = {
            "not ready": UnaryExpr("not", Variable("ready")),
            "+x": UnaryExpr("+", Variable("x")),
            "-x": UnaryExpr("-", Variable("x")),
        }
        for source, expected in cases.items():
            with self.subTest(source=source):
                self.assertEqual(parse_expr(source), expected)

    # 测试输入：x 与 y 上的 ``+ - * / % **`` 六种二元算术式。
    # 预期行为：每个运算符原样成为 BinaryExpr.op。
    # 检查内容：用子测试逐一比较左右变量和运算符映射。
    # 论文对应：Section 2.1 的表达式 e 及 ODE 导数表达式使用算术项。
    def test_all_supported_binary_arithmetic_operators(self) -> None:
        """六种内部算术运算符都应映射为 BinaryExpr。"""

        for operator in ("+", "-", "*", "/", "%", "**"):
            with self.subTest(operator=operator):
                self.assertEqual(
                    parse_expr(f"x {operator} y"),
                    BinaryExpr(operator, Variable("x"), Variable("y")),
                )

    # 测试输入：HCSP 风格乘方 ``x ^ 2``。
    # 预期行为：内部统一为 BinaryExpr("**", x, 2)。
    # 检查内容：确认兼容预处理不会把 ^ 保留成异或运算。
    # 论文对应：为论文数学表达式中的幂运算提供明确内部表示。
    def test_hcsp_caret_is_normalized_to_power(self) -> None:
        """HCSP 的 ^ 乘方记号应统一保存为内部 **。"""

        self.assertEqual(
            parse_expr("x ^ 2"),
            BinaryExpr("**", Variable("x"), Literal(2)),
        )

    # 测试输入：``x + y * 2`` 与 ``(x + y) * 2``。
    # 预期行为：乘法优先和显式括号产生两棵不同且正确的 AST。
    # 检查内容：完整比较嵌套 BinaryExpr 结构，而非仅比较求值结果。
    # 论文对应：e 的语法树必须忠实保存 ODE/赋值公式的运算结合关系。
    def test_python_precedence_and_parentheses_shape_the_tree(self) -> None:
        """解析树应保留乘法优先级和显式括号结构。"""

        self.assertEqual(
            parse_expr("x + y * 2"),
            BinaryExpr(
                "+",
                Variable("x"),
                BinaryExpr("*", Variable("y"), Literal(2)),
            ),
        )
        self.assertEqual(
            parse_expr("(x + y) * 2"),
            BinaryExpr(
                "*",
                BinaryExpr("+", Variable("x"), Variable("y")),
                Literal(2),
            ),
        )

    # 测试输入：三项 ``a and b and c`` 与二项 ``a or b``。
    # 预期行为：形成保留源层级和操作数顺序的 BooleanExpr。
    # 检查内容：核对 n 元 operands，不把链拆成任意二叉结合树。
    # 论文对应：Section 4 的路径条件、安全性质和不变量使用合取/析取。
    def test_and_or_build_nary_boolean_nodes(self) -> None:
        """连续 and/or 应形成保留源层级的 BooleanExpr。"""

        self.assertEqual(
            parse_expr("a and b and c"),
            BooleanExpr(
                "and",
                (Variable("a"), Variable("b"), Variable("c")),
            ),
        )
        self.assertEqual(
            parse_expr("a or b"),
            BooleanExpr("or", (Variable("a"), Variable("b"))),
        )

    # 测试输入：x、y 上的 ``== != < <= > >=`` 六种比较。
    # 预期行为：每种比较形成含一个 operator 的 CompareExpr。
    # 检查内容：逐项核对操作数顺序和比较符，不做字符串猜测。
    # 论文对应：Section 2.1 的 B 与 Section 4 公式中的关系谓词。
    def test_all_supported_single_comparisons(self) -> None:
        """六种比较符都应形成单操作符 CompareExpr。"""

        for operator in ("==", "!=", "<", "<=", ">", ">="):
            with self.subTest(operator=operator):
                self.assertEqual(
                    parse_expr(f"x {operator} y"),
                    CompareExpr(
                        (Variable("x"), Variable("y")),
                        (operator,),
                    ),
                )

    # 测试输入：链式约束 ``0 <= x < limit``。
    # 预期行为：保存三个操作数和按序排列的 ``<=``、``<``。
    # 检查内容：确保链式比较不会错误复制中间变量或拆乱关系。
    # 论文对应：ODE 演化域和安全性质常用上下界合取的简写。
    def test_chained_comparison_preserves_operand_order(self) -> None:
        """链式比较应保存全部操作数和逐段关系。"""

        self.assertEqual(
            parse_expr("0 <= x < limit"),
            CompareExpr(
                (Literal(0), Variable("x"), Variable("limit")),
                ("<=", "<"),
            ),
        )


class SupportedHCSPNotationParsingTests(unittest.TestCase):
    """验证 parse_expr 接受的 HCSP 布尔便捷记号。"""

    # 测试输入：HCSP 记号 ``a && b`` 和 ``a || b``。
    # 预期行为：分别规范化成内部 and/or BooleanExpr。
    # 检查内容：比较规范化后的运算符及左右变量顺序。
    # 论文对应：对应论文公式中的逻辑合取和析取。
    def test_double_ampersand_and_double_bar(self) -> None:
        """&& 与 || 应分别规范化为 and 与 or。"""

        self.assertEqual(
            parse_expr("a && b"),
            BooleanExpr("and", (Variable("a"), Variable("b"))),
        )
        self.assertEqual(
            parse_expr("a || b"),
            BooleanExpr("or", (Variable("a"), Variable("b"))),
        )

    # 测试输入：逻辑非 ``!ready`` 和不等式 ``x != y``。
    # 预期行为：前者成为 not；后者继续成为 !=，不被预处理破坏。
    # 检查内容：同时覆盖最长记号优先和单字符 ! 替换边界。
    # 论文对应：对应公式中的否定及关系谓词不等号。
    def test_bang_not_does_not_corrupt_not_equal(self) -> None:
        """! 应成为 not，而 != 必须继续表示不等比较。"""

        self.assertEqual(
            parse_expr("!ready"),
            UnaryExpr("not", Variable("ready")),
        )
        self.assertEqual(
            parse_expr("x != y"),
            CompareExpr((Variable("x"), Variable("y")), ("!=",)),
        )

    # 测试输入：布尔等价便捷式 ``ready <-> enabled``。
    # 预期行为：按项目约定规范化为布尔相等 CompareExpr。
    # 检查内容：核对两个变量和内部 ``==``，不残留 <-> 文本。
    # 论文对应：为 Section 4 公式中的逻辑等价提供可交给求解器的表示。
    def test_equivalence_notation_becomes_equality(self) -> None:
        """<-> 应按项目约定规范化成布尔相等关系。"""

        self.assertEqual(
            parse_expr("ready <-> enabled"),
            CompareExpr(
                (Variable("ready"), Variable("enabled")),
                ("==",),
            ),
        )


class SupportedFunctionExpressionParsingTests(unittest.TestCase):
    """验证简单命名函数调用及嵌套参数。"""

    # 测试输入：f()、sqrt(x)、max(x, y, 0) 三种参数数量。
    # 预期行为：形成保存函数名和有序位置实参的 CallExpr。
    # 检查内容：分别覆盖零、一、多个实参的精确节点结构。
    # 论文对应：支持 ODE 导数和普通表达式 e 中的命名数学函数。
    def test_zero_one_and_multiple_argument_calls(self) -> None:
        """简单函数名应支持零个、一个或多个位置实参。"""

        cases = {
            "f()": CallExpr("f", ()),
            "sqrt(x)": CallExpr("sqrt", (Variable("x"),)),
            "max(x, y, 0)": CallExpr(
                "max",
                (Variable("x"), Variable("y"), Literal(0)),
            ),
        }
        for source, expected in cases.items():
            with self.subTest(source=source):
                self.assertEqual(parse_expr(source), expected)

    # 测试输入：``f(x + 1, abs(y))`` 嵌套组合。
    # 预期行为：外层 CallExpr 包含算术节点和内层 CallExpr。
    # 检查内容：比较完整递归结构及实参顺序。
    # 论文对应：验证复杂 e 可组合用于赋值、输出和 ODE 方程右端。
    def test_nested_function_and_operator_arguments(self) -> None:
        """函数实参可以递归包含其他受支持表达式。"""

        self.assertEqual(
            parse_expr("f(x + 1, abs(y))"),
            CallExpr(
                "f",
                (
                    BinaryExpr("+", Variable("x"), Literal(1)),
                    CallExpr("abs", (Variable("y"),)),
                ),
            ),
        )

    # 测试输入：函数、链式比较、布尔连接和逻辑非的组合公式。
    # 预期行为：整棵树均为项目 Expr，变量集为四个源变量。
    # 检查内容：递归遍历所有子节点并核对 get_vars 的完整结果。
    # 论文对应：模拟 Section 4 安全公式/路径条件中的真实组合表达式。
    def test_complex_parse_contains_only_project_nodes(self) -> None:
        """组合解析结果的每个子节点都必须属于项目 Expr 层次。"""

        expression = parse_expr(
            "0 <= f(x + 1) < limit and (ready or !stopped)"
        )
        assert_project_expr_tree(self, expression)
        self.assertEqual(
            expression.get_vars(),
            {"x", "limit", "ready", "stopped"},
        )


class UnsupportedExpressionParsingTests(unittest.TestCase):
    """逐类验证模块头部明确排除的表达式语法。"""

    # 测试输入：条件式、属性、下标、lambda、tuple/list、关键字参数等清单。
    # 预期行为：未支持源码由 parse_expr 拒绝，直接 tuple/list 由 ensure_expr 拒绝。
    # 检查内容：逐类锁定 expressions.py 头部声明的源码及对象输入边界。
    # 论文对应：论文未定义这些表达式扩展；项目不得静默扩大 e/B 语法。
    def test_every_documented_unsupported_form_is_rejected(self) -> None:
        """不支持的控制流、访问、容器和运算必须在解析边界失败。"""

        unsupported_sources = (
            "1 if ready else 0",
            "plant.temperature",
            "obj.f(x)",
            "array[i]",
            "functions[i](x)",
            "lambda x: x + 1",
            "[f(x) for x in values]",
            "(x, 1)",
            "[x, 1]",
            "(x,)",
            "()",
            "{'x': 1}",
            "{x, y}",
            "f(x=1)",
            "x // y",
            "x << 1",
            "x >> 1",
            "x & y",
            "x | y",
            "x in values",
            "x is None",
            "(x := 1)",
        )
        for source in unsupported_sources:
            with self.subTest(source=source):
                with self.assertRaises(ValueError):
                    parse_expr(source)
        for value in ((1, "x"), [1, "x"]):
            with self.subTest(value=value):
                with self.assertRaises(TypeError):
                    ensure_expr(value)  # type: ignore[arg-type]

    # 测试输入：空串、全空白串和非字符串整数输入。
    # 预期行为：parse_expr 对三种非法源码入口均抛出 ValueError。
    # 检查内容：覆盖词法空输入和 API 参数类型边界。
    # 论文对应：保证进入 Section 2.1 表达式位置的源码具有明确语法内容。
    def test_empty_or_non_string_source_is_rejected(self) -> None:
        """parse_expr 只接受非空字符串源码。"""

        for source in ("", "   "):
            with self.subTest(source=source):
                with self.assertRaises(ValueError):
                    parse_expr(source)
        with self.assertRaises(ValueError):
            parse_expr(1)  # type: ignore[arg-type]


if __name__ == "__main__":
    unittest.main()
