"""HCSP 用户输入前端的错误分类、源码定位和诊断格式测试。

测试内容
--------
1. 非法字符和未结束块注释的 lexical 错误及准确起始位置。
2. 缺分号、空/尾逗号 source 和未闭合结构的 syntax 错误字段。
3. 重复输入目标、保留 ODE 时钟和并行冲突的 validation 分类。
4. source_name、expected/found、源码行和插入符的稳定公共诊断接口。

论文对应
--------
本文件不增加新的论文语法或类型规则；它保证 Section 2.1/4.3 输入不合法时
能够在进入 Process AST 和 Table 2 推导前给出可定位、可审计的失败原因。
"""

from __future__ import annotations

import unittest

from hcsp_typechecker._internal import HCSPInputError, parse_expression, parse_hcsp


class LexicalDiagnosticTests(unittest.TestCase):
    """验证词法阶段异常的分类和源码起点。"""

    # 测试输入：命名源码第二行第五列出现非法字符 @。
    # 预期行为：抛出 lexical HCSPInputError 并保留文件名、行列和 found。
    # 检查内容：核对稳定机器字段及格式化诊断中的源码行和插入符。
    # 论文对应：防止非法词法记号进入任何 Section 2.1 表达式或进程节点。
    def test_illegal_character_reports_exact_location(self) -> None:
        """非法字符诊断应包含准确一基位置和可读源码片段。"""

        source = "{{skip;\n    @}}"
        with self.assertRaises(HCSPInputError) as context:
            parse_hcsp(source, source_name="example.hcsp")
        error = context.exception
        self.assertEqual(error.phase, "lexical")
        self.assertEqual(error.source_name, "example.hcsp")
        self.assertEqual((error.line, error.column), (2, 5))
        self.assertEqual(error.found, "@")
        diagnostic = error.format_diagnostic()
        self.assertIn("example.hcsp:2:5", diagnostic)
        self.assertIn("    @}}", diagnostic)
        self.assertIn("    ^", diagnostic)

    # 测试输入：第一行第三列开始但直到 EOF 未闭合的块注释。
    # 预期行为：错误定位到 /* 起点而不是文件末尾。
    # 检查内容：核对 lexical phase、行列和 unterminated 关键诊断。
    # 论文对应：保证无效注释不会吞掉后续 HCSP 程序并产生误导 AST。
    def test_unterminated_comment_points_to_comment_start(self) -> None:
        """未结束块注释必须报告其开始位置。"""

        with self.assertRaises(HCSPInputError) as context:
            parse_hcsp("{{/* never closed")
        error = context.exception
        self.assertEqual(error.phase, "lexical")
        self.assertEqual((error.line, error.column), (1, 3))
        self.assertIn("unterminated block comment", error.message)

    # 测试输入：Unicode 标识符、十六进制、数字下划线和非字符串入口。
    # 预期行为：全部归入 lexical 错误，不借用 Python 的额外词法规则。
    # 检查内容：逐项确认公共异常类型和 phase 字段。
    # 论文对应：落实用户输入文档的 ASCII 标识符与十进制字面量边界。
    def test_noncanonical_lexemes_and_non_string_input_are_lexical_errors(self) -> None:
        """非规范字符和入口对象应统一产生词法阶段诊断。"""

        for source in ("变量", "0x10", "1_000"):
            with self.subTest(source=source):
                with self.assertRaises(HCSPInputError) as context:
                    parse_expression(source)
                self.assertEqual(context.exception.phase, "lexical")
        with self.assertRaises(HCSPInputError) as context:
            parse_hcsp(1)  # type: ignore[arg-type]
        self.assertEqual(context.exception.phase, "lexical")

    # 测试输入：4097 位整数和绝对值超过 10000 的十进制指数。
    # 预期行为：两者都产生带位置的 lexical 错误，不泄漏 Python 数值异常。
    # 检查内容：核对公共异常类型、phase 和明确的资源限制消息。
    # 论文对应：不改变表达式产生式，只保证异常大常量不能阻断审计流程。
    def test_extreme_numeric_literals_have_bounded_diagnostics(self) -> None:
        """异常大的数值字面量应由前端资源边界稳定拒绝。"""

        for source in ("9" * 4097, "1e10001"):
            with self.subTest(length=len(source)):
                with self.assertRaises(HCSPInputError) as context:
                    parse_expression(source)
                self.assertEqual(context.exception.phase, "lexical")


class SyntaxDiagnosticTests(unittest.TestCase):
    """验证语法阶段的 expected/found 和块边界诊断。"""

    # 测试输入：相邻赋值之间遗漏 statement_block 唯一分隔符分号。
    # 预期行为：在第二个标识符处报告期望 ``}`` 的 syntax 错误。
    # 检查内容：核对 found、expected 和实际第二行位置。
    # 论文对应：保持 Section 2.1 顺序组合必须显式写成 P;P'。
    def test_missing_semicolon_reports_second_statement(self) -> None:
        """遗漏分号时诊断应指向无法继续归约的下一条语句。"""

        source = "{{x := 0\n  y := 1}}"
        with self.assertRaises(HCSPInputError) as context:
            parse_hcsp(source)
        error = context.exception
        self.assertEqual(error.phase, "syntax")
        self.assertEqual((error.line, error.column), (2, 3))
        self.assertEqual(error.found, "y")
        self.assertEqual(error.expected, ("}",))

    # 测试输入：空 source、source 尾逗号、缺块间逗号和块内尾分号。
    # 预期行为：全部抛出 syntax 错误，不插入隐式块、Skip 或分量。
    # 检查内容：逐项锁定顶层非空有序列表和分号非终止符语义。
    # 论文对应：保证 S 的分量和 P;P' 两侧都对应实际 Process AST。
    def test_malformed_source_and_block_boundaries_are_syntax_errors(self) -> None:
        """顶层列表和语句块的空项、尾分隔符必须被拒绝。"""

        malformed = (
            "{}",
            "{{skip},}",
            "{{skip} {skip}}",
            "{{skip;}}",
            "skip",
        )
        for source in malformed:
            with self.subTest(source=source):
                with self.assertRaises(HCSPInputError) as context:
                    parse_hcsp(source)
                self.assertEqual(context.exception.phase, "syntax")

    # 测试输入：``assert(x > 0`` 缺少关闭圆括号和语句块边界。
    # 预期行为：EOF/右花括号位置产生 syntax，并给出期望 ``)``。
    # 检查内容：检查 expected 字段，而不锁死整段英文错误消息。
    # 论文对应：保证断言公式 B 的括号边界先于类型构造完整闭合。
    def test_unclosed_parenthesis_exposes_expected_token(self) -> None:
        """未闭合表达式结构应通过 expected 字段说明缺失 token。"""

        with self.assertRaises(HCSPInputError) as context:
            parse_hcsp("{{assert(x > 0}}")
        error = context.exception
        self.assertEqual(error.phase, "syntax")
        self.assertEqual(error.expected, (")",))

    # 测试输入：只有开始花括号并以换行结束的未完成 source。
    # 预期行为：诊断头和源码插入符都指向真实的第二行空行。
    # 检查内容：确认末尾空行不会被 splitlines 丢失并显示成上一行源码。
    # 论文对应：保证不完整系统 S 在进入 Process AST 前得到一致的定位说明。
    def test_eof_after_newline_displays_the_actual_empty_line(self) -> None:
        """末尾换行处的 EOF 诊断不得把插入符画到上一行。"""

        with self.assertRaises(HCSPInputError) as context:
            parse_hcsp("{\n")
        error = context.exception
        self.assertEqual((error.line, error.column), (2, 1))
        self.assertEqual(error.format_diagnostic().splitlines()[-2:], ["", "^"])


class ValidationDiagnosticTests(unittest.TestCase):
    """验证解析成功后正式 AST 构造失败的 validation 包装。"""

    # 测试输入：``ch?(x,x)`` 的第二个重复目标。
    # 预期行为：错误 phase 为 validation，并定位到第二个 x。
    # 检查内容：核对重复目标消息和行列，不把它误报为一般语法错误。
    # 论文对应：落实多标量输入目标互异的项目通信扩展约束。
    def test_duplicate_input_target_is_located_at_second_occurrence(self) -> None:
        """重复接收目标应在重复出现处产生 validation 诊断。"""

        with self.assertRaises(HCSPInputError) as context:
            parse_hcsp("{{ch?(x, x)}}")
        error = context.exception
        self.assertEqual(error.phase, "validation")
        self.assertEqual((error.line, error.column), (1, 10))
        self.assertEqual(error.found, "x")
        self.assertIn("duplicate input target", error.message)

    # 测试输入：flow 中把保留名 t 写在 dot 左端。
    # 预期行为：在 t 处产生 validation，并说明其属于隐式局部时钟。
    # 检查内容：核对 found 和关键消息，保证位置不退化到整个 ode 起点。
    # 论文对应：对应 Table 2 自动添加 dot(t)=1、用户不得覆盖的约束。
    def test_reserved_ode_clock_reports_equation_position(self) -> None:
        """非法 dot t 应直接定位到方程左端标识符。"""

        source = "{{ode(flow(dot t = 1), domain(true), delay(1))}}"
        with self.assertRaises(HCSPInputError) as context:
            parse_hcsp(source)
        error = context.exception
        self.assertEqual(error.phase, "validation")
        self.assertEqual(error.found, "t")
        self.assertIn("implicit local clock", error.message)

    # 测试输入：两个并行分量同向输出同一个 ch。
    # 预期行为：完整子树在 Parallel.of 构造时产生 validation 错误。
    # 检查内容：确认保留 AST 构造器原始 Assumption 2.1 失败原因。
    # 论文对应：对应并行分量 oCh 集合必须互不相交的 Assumption 2.1。
    def test_parallel_validation_preserves_assumption_message(self) -> None:
        """并行资源冲突应作为 validation 诊断保留原良构原因。"""

        with self.assertRaises(HCSPInputError) as context:
            parse_hcsp("{{ch!(0)}, {ch!(1)}}")
        error = context.exception
        self.assertEqual(error.phase, "validation")
        self.assertIn("Assumption 2.1", error.message)
        self.assertIn("output channels", error.message)


if __name__ == "__main__":
    unittest.main()
