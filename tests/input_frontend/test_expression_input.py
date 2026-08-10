"""HCSP 用户输入前端的词法与表达式解析测试。

测试内容
--------
1. ASCII 标识符、十进制数值、空白、注释和最长运算符匹配。
2. 字面量、一元/二元运算、布尔连接、比较、函数调用的精确 Expr AST。
3. 乘方、逻辑运算和比较的优先级、结合性及 HCSP 便捷符号规范化。
4. 文档明确排除的 Unicode 名称、容器、访问、赋值式等表达式负例。

论文对应
--------
这些测试覆盖 Section 2.1 中普通表达式 ``e`` 与布尔公式 ``B`` 的用户输入
前端；它们只验证源码到项目 ``Expr`` AST 的转换，不执行后续静态类型判断。
"""

from __future__ import annotations

from decimal import Decimal
import unittest

from hcsp_typechecker._internal import (
    BinaryExpr,
    BooleanExpr,
    CallExpr,
    CompareExpr,
    HCSPInputError,
    Literal,
    UnaryExpr,
    Variable,
    parse_expression,
    parse_hcsp,
)
from hcsp_typechecker.frontend.type_constructor_frontend import tokenize
from hcsp_typechecker.data_structures.process_ast.ast import InputChannel


class LexerInputTests(unittest.TestCase):
    """验证规范词法器的边界和 Process 记号上下文。"""

    # 测试输入：含 CRLF、Tab、单行/块注释以及紧邻注释的 ``ch?(x)``。
    # 预期行为：布局不进入 AST，跨注释通信仍构造 InputChannel。
    # 检查内容：比较完整输入节点，并核对换行后 token 的一基行列位置。
    # 论文对应：注释不改变 Section 2.1 输入动作 ``ch?x`` 的结构。
    def test_layout_comments_and_source_positions(self) -> None:
        """空白和两类注释应被忽略，同时保留准确 token 位置。"""

        process = parse_hcsp(
            "{{ch /* channel */ ? /* targets */ (x)}} // finished\r\n"
        )
        self.assertEqual(process, InputChannel("ch", "x"))

        tokens = tokenize("x\r\n\t y")
        self.assertEqual(tokens[1].text, "y")
        self.assertEqual((tokens[1].position.line, tokens[1].position.column), (2, 3))

    # 测试输入：``:= <= >= == != <-> && || ** ? !`` 全部多/单字符记号。
    # 预期行为：词法器执行最长匹配，特别是不拆分 !=、<-> 和 **。
    # 检查内容：逐项比较 token kind，排除通信 ! 与不等号互相破坏。
    # 论文对应：为赋值、通信及 Section 4 公式提供无歧义词法边界。
    def test_longest_operator_matching(self) -> None:
        """多字符运算符必须优先于其单字符前缀。"""

        source = ":= <= >= == != <-> && || ** ? !"
        kinds = tuple(token.kind for token in tokenize(source)[:-1])
        self.assertEqual(
            kinds,
            (":=", "<=", ">=", "==", "!=", "<->", "&&", "||", "**", "?", "!"),
        )

    # 测试输入：整数、三种小数形式、科学计数法和大小写布尔字面量。
    # 预期行为：整数保持 int，实数保持 Decimal，布尔统一为 Python bool。
    # 检查内容：逐个调用独立表达式入口并精确比较 Literal 节点和值。
    # 论文对应：覆盖表达式 ``e``/``B`` 中前端允许的全部字面量类别。
    def test_decimal_and_boolean_literals(self) -> None:
        """规范十进制数值和大小写布尔字面量应稳定解析。"""

        cases = {
            "0": Literal(0),
            "123": Literal(123),
            "1.": Literal(Decimal("1.")),
            ".5": Literal(Decimal(".5")),
            "1.25": Literal(Decimal("1.25")),
            "1e3": Literal(Decimal("1e3")),
            "1E-3": Literal(Decimal("1E-3")),
            "TRUE": Literal(True),
            "fAlSe": Literal(False),
        }
        for source, expected in cases.items():
            with self.subTest(source=source):
                self.assertEqual(parse_expression(source), expected)


class ExpressionTreeInputTests(unittest.TestCase):
    """验证用户表达式到项目 Expr 节点的精确 lowering。"""

    # 测试输入：全部一元、算术、布尔连接及 HCSP 运算符别名。
    # 预期行为：^ 统一为 **，! 统一为 not，&&/|| 统一为 and/or。
    # 检查内容：比较规范 Expr 节点而不是重新打印后的字符串。
    # 论文对应：覆盖 e 的算术构造和 B 的否定、合取与析取构造。
    def test_supported_operators_are_normalized(self) -> None:
        """所有受支持运算及其别名都应进入唯一内部表示。"""

        self.assertEqual(
            parse_expression("+x"),
            UnaryExpr("+", Variable("x")),
        )
        self.assertEqual(
            parse_expression("!ready"),
            UnaryExpr("not", Variable("ready")),
        )
        for source_operator, internal_operator in (
            ("+", "+"),
            ("-", "-"),
            ("*", "*"),
            ("/", "/"),
            ("%", "%"),
            ("**", "**"),
            ("^", "**"),
        ):
            with self.subTest(operator=source_operator):
                self.assertEqual(
                    parse_expression(f"x {source_operator} y"),
                    BinaryExpr(internal_operator, Variable("x"), Variable("y")),
                )
        self.assertEqual(
            parse_expression("a && b"),
            BooleanExpr("and", (Variable("a"), Variable("b"))),
        )
        self.assertEqual(
            parse_expression("a || b"),
            BooleanExpr("or", (Variable("a"), Variable("b"))),
        )

    # 测试输入：``x+y*2``、``-x**2``、``x**y**z`` 和布尔混合式。
    # 预期行为：乘法/乘方优先，乘方右结合，not 高于 and 且低于比较。
    # 检查内容：精确比较每层 BinaryExpr、UnaryExpr 和 BooleanExpr 嵌套。
    # 论文对应：确保 ODE、赋值和安全公式中的数学结合关系不被改写。
    def test_precedence_and_power_associativity(self) -> None:
        """优先级和右结合乘方必须产生规范且无歧义的树。"""

        self.assertEqual(
            parse_expression("x + y * 2"),
            BinaryExpr(
                "+",
                Variable("x"),
                BinaryExpr("*", Variable("y"), Literal(2)),
            ),
        )
        self.assertEqual(
            parse_expression("-x ** 2"),
            UnaryExpr("-", BinaryExpr("**", Variable("x"), Literal(2))),
        )
        self.assertEqual(
            parse_expression("x ^ y ^ z"),
            BinaryExpr(
                "**",
                Variable("x"),
                BinaryExpr("**", Variable("y"), Variable("z")),
            ),
        )
        self.assertEqual(
            parse_expression("not x < y or a and b"),
            BooleanExpr(
                "or",
                (
                    UnaryExpr(
                        "not",
                        CompareExpr((Variable("x"), Variable("y")), ("<",)),
                    ),
                    BooleanExpr("and", (Variable("a"), Variable("b"))),
                ),
            ),
        )

    # 测试输入：六种关系、<-> 以及 ``0 <= x < limit`` 链式比较。
    # 预期行为：<-> 规范为 ==，比较链保存在单个 CompareExpr 中。
    # 检查内容：核对操作数顺序和逐段 operator 元组，不拆成任意布尔树。
    # 论文对应：对应演化域、安全性质和递归不变量中的关系公式 B。
    def test_comparisons_and_equivalence(self) -> None:
        """单比较、等价别名和比较链应保留完整关系结构。"""

        for source_operator, internal_operator in (
            ("==", "=="),
            ("!=", "!="),
            ("<", "<"),
            ("<=", "<="),
            (">", ">"),
            (">=", ">="),
            ("<->", "=="),
        ):
            with self.subTest(operator=source_operator):
                self.assertEqual(
                    parse_expression(f"x {source_operator} y"),
                    CompareExpr(
                        (Variable("x"), Variable("y")),
                        (internal_operator,),
                    ),
                )
        self.assertEqual(
            parse_expression("0 <= x < limit"),
            CompareExpr(
                (Literal(0), Variable("x"), Variable("limit")),
                ("<=", "<"),
            ),
        )

    # 测试输入：零参数、尾逗号、多参数及嵌套普通函数调用。
    # 预期行为：参数按书写顺序形成 CallExpr.arguments，尾逗号不新增参数。
    # 检查内容：比较完整函数调用和嵌套算术子树。
    # 论文对应：支持普通表达式 e 在微分方程右端使用命名数学函数。
    def test_named_function_calls(self) -> None:
        """简单命名函数调用应支持零个、多个及嵌套位置参数。"""

        self.assertEqual(parse_expression("f()"), CallExpr("f", ()))
        self.assertEqual(
            parse_expression("f(x + 1, abs(y),)"),
            CallExpr(
                "f",
                (
                    BinaryExpr("+", Variable("x"), Literal(1)),
                    CallExpr("abs", (Variable("y"),)),
                ),
            ),
        )

    # 测试输入：Unicode/None、属性、下标、tuple/list、字符串及未定义运算。
    # 预期行为：每项都在用户输入边界抛出 HCSPInputError，不产生部分 Expr。
    # 检查内容：覆盖文档明确不支持且旧 Python AST 曾可能接受的扩展形式。
    # 论文对应：防止把 Section 2.1 未定义的表达式构造静默带入 Process AST。
    def test_unsupported_expression_forms_are_rejected(self) -> None:
        """输入前端必须拒绝规范之外的表达式形式。"""

        unsupported = (
            "变量",
            "None",
            "plant.temperature",
            "array[i]",
            "(x, y)",
            "[x, y]",
            "'text'",
            "a if ready else b",
            "lambda x: x",
            "f(x=1)",
            "x << 1",
            "x & y",
            "x in values",
            "(x := 1)",
            "0x10",
            "1_000",
        )
        for source in unsupported:
            with self.subTest(source=source):
                with self.assertRaises(HCSPInputError):
                    parse_expression(source)


if __name__ == "__main__":
    unittest.main()
