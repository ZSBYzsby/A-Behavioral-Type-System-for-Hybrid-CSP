"""HCSP 用户输入前端的语句、顺序和控制流 lowering 测试。

测试内容
--------
1. skip、赋值、断言、输入、输出和 call 的精确 Process AST。
2. 语句块分号的唯一顺序组合含义和非法空项/尾分号边界。
3. if、内部选择及递归的块结构、规范 AST 和构造期良构失败。
4. If、内部选择之后的块内语句直接进入控制节点的公共 continuation。

论文对应
--------
这些测试覆盖 Section 2.1 的离散 Process 产生式以及项目的多标量通信和多元
控制节点规范形；递归批注与通信保护对应 Section 4.2/4.3 和 Assumption 2.2。
"""

from __future__ import annotations

from fractions import Fraction
import unittest

from hcsp_typechecker._internal import (
    Assert,
    Assign,
    BinaryExpr,
    CompareExpr,
    HCSPInputError,
    If,
    InputChannel,
    InternalChoice,
    Literal,
    Mu,
    ODE,
    OutputChannel,
    RecursionAnnotation,
    Sequence,
    Skip,
    Var,
    Variable,
    parse_hcsp,
)


class AtomicStatementInputTests(unittest.TestCase):
    """验证每个不含子块的用户语句到 Process 节点的映射。"""

    # 测试输入：``skip``、赋值和带比较公式的 assert 三种源码。
    # 预期行为：分别构造 Skip、Assign 和 Assert，表达式立即成为 Expr。
    # 检查内容：比较目标变量、算术右值及断言 CompareExpr 的精确结构。
    # 论文对应：覆盖 Section 2.1 的 skip、x:=e 与 assert(B) 产生式。
    def test_skip_assignment_and_assertion(self) -> None:
        """基本离散语句应直接构造对应 Process 节点。"""

        self.assertEqual(parse_hcsp("{{skip}}"), Skip())
        self.assertEqual(
            parse_hcsp("{{x := y + 1}}"),
            Assign(
                "x",
                BinaryExpr("+", Variable("y"), Literal(1)),
            ),
        )
        self.assertEqual(
            parse_hcsp("{{assert(x >= 0)}}"),
            Assert(CompareExpr((Variable("x"), Literal(0)), (">=",))),
        )

    # 测试输入：单槽/多槽 ch? 和含复合表达式的单槽/多槽 ch!。
    # 预期行为：通信参数保存为标量元组，绝不产生 tuple 表达式。
    # 检查内容：比较 InputChannel.targets 与 OutputChannel.payloads 的顺序。
    # 论文对应：覆盖项目对 Section 2.1 输入/输出动作的多标量扩展。
    def test_single_and_multi_scalar_communications(self) -> None:
        """输入目标和输出表达式列表应保持非空标量序列。"""

        self.assertEqual(parse_hcsp("{{ch?(x)}}"), InputChannel("ch", "x"))
        self.assertEqual(
            parse_hcsp("{{ch?(x, y, z)}}"),
            InputChannel("ch", ("x", "y", "z")),
        )
        self.assertEqual(parse_hcsp("{{ch!(x)}}"), OutputChannel("ch", "x"))
        self.assertEqual(
            parse_hcsp("{{ch!(x, y + 1, 0)}}"),
            OutputChannel(
                "ch",
                (
                    Variable("x"),
                    BinaryExpr("+", Variable("y"), Literal(1)),
                    Literal(0),
                ),
            ),
        )

    # 测试输入：自由 ``call Loop`` 与已移除语法糖 ``wait(1/2)``。
    # 预期行为：call 构造 Var；wait 不再作为语句接受。
    # 检查内容：确认前端不再偷偷展开 wait，用户必须显式写 ODE。
    # 论文对应：call 对应 Section 2.1 的变量 X；时延统一由带批注 ODE 表示。
    def test_process_call_is_supported_and_wait_is_rejected(self) -> None:
        """call 应 lower 为进程变量节点，wait 语法糖应得到语法诊断。"""

        self.assertEqual(parse_hcsp("{{call Loop}}"), Var("Loop"))
        with self.assertRaises(HCSPInputError):
            parse_hcsp("{{wait(1 / 2)}}")

    # 测试输入：空/重复输入目标、空/尾逗号输出和表达式型输入目标。
    # 预期行为：各项均抛出 syntax 或 validation HCSPInputError。
    # 检查内容：锁定通信参数非空、输入互异和输入只能是标识符的边界。
    # 论文对应：保证一次多标量通信仍由一个或多个独立标量组成。
    def test_invalid_communication_arguments_are_rejected(self) -> None:
        """通信参数表的非空、互异和标量目标约束必须在前端落实。"""

        invalid_sources = (
            "{{ch?()}}",
            "{{ch?(x, x)}}",
            "{{ch?(x + 1)}}",
            "{{ch!()}}",
            "{{ch!(x,)}}",
        )
        for source in invalid_sources:
            with self.subTest(source=source):
                with self.assertRaises(HCSPInputError):
                    parse_hcsp(source)


class StatementBlockInputTests(unittest.TestCase):
    """验证分号和复合语句块的顺序语义。"""

    # 测试输入：输入、赋值和输出由两个分号连接的非空语句块。
    # 预期行为：按书写顺序形成 Sequence.of 的规范右结合 AST。
    # 检查内容：完整比较三项树，证明分号只表示顺序组合而非语句终止符。
    # 论文对应：对应 Section 2.1 的二元顺序组合 P;P'。
    def test_semicolon_builds_sequence_in_source_order(self) -> None:
        """语句之间的分号应构造唯一顺序组合树。"""

        self.assertEqual(
            parse_hcsp("{{ch?(x); x := x + 1; out!(x)}}"),
            Sequence.of(
                InputChannel("ch", "x"),
                Assign("x", BinaryExpr("+", Variable("x"), Literal(1))),
                OutputChannel("out", "x"),
            ),
        )

    # 测试输入：空块、前导/尾随/连续分号及遗漏分号的语句块。
    # 预期行为：所有形式均被拒绝，空行为必须显式写 skip。
    # 检查内容：逐项确认不会静默插入 Skip 或把分号当可选终止符。
    # 论文对应：保持 P;P' 两侧都必须存在合法 Process 的语法要求。
    def test_empty_or_malformed_statement_blocks_are_rejected(self) -> None:
        """语句块必须非空且分号两侧都存在一条语句。"""

        malformed = (
            "{{}}",
            "{{; skip}}",
            "{{skip;}}",
            "{{skip;; skip}}",
            "{{skip skip}}",
        )
        for source in malformed:
            with self.subTest(source=source):
                with self.assertRaises(HCSPInputError):
                    parse_hcsp(source)


class CompoundControlInputTests(unittest.TestCase):
    """验证 if、内部选择和带批注递归的 lowering。"""

    # 测试输入：二元 if 及其后一个块内公共顺序语句。
    # 预期行为：if 构造终端 If，后继直接保存在其 continuation 字段。
    # 检查内容：比较条件、两个分支及公共 done 后继的精确规范形。
    # 论文对应：覆盖 Section 2.1 的 if B then P else P' 与顺序组合。
    def test_if_statement_and_following_continuation(self) -> None:
        """if 必须有两个块分支，并可作为一条语句接续后继。"""

        source = """{{
            if (x >= 0) {positive!(x)} else {negative!(x)};
            done!(x)
        }}"""
        expected = If(
            CompareExpr((Variable("x"), Literal(0)), (">=",)),
            OutputChannel("positive", "x"),
            OutputChannel("negative", "x"),
            continuation=OutputChannel("done", "x"),
        )
        self.assertEqual(parse_hcsp(source), expected)

    # 测试输入：二分支 choose 后紧随 ``done!(0)``。
    # 预期行为：后继直接写入多元 InternalChoice.continuation。
    # 检查内容：明确排除旧的 Sequence(InternalChoice(...), done) 结构。
    # 论文对应：对应项目规范化的 ``(P_1 \sqcup ... \sqcup P_n);Q`` 多元表示。
    def test_choice_owns_its_common_continuation(self) -> None:
        """内部选择后面的块内语句必须成为两个分支的公共后继。"""

        source = "{{choose {left!(0)} or {right!(0)}; done!(0)}}"
        self.assertEqual(
            parse_hcsp(source),
            InternalChoice(
                OutputChannel("left", 0),
                OutputChannel("right", 0),
                continuation=OutputChannel("done", 0),
            ),
        )

    # 测试输入：三分支 choose 和由两条语句组成的公共后继。
    # 预期行为：三个分支直接保存在同一个 InternalChoice 中，完整后继单独保存。
    # 检查内容：比较多元分支顺序及 continuation 的 Sequence.of 结构。
    # 论文对应：对应 Table 2 可直接推广的多分支内部选择，不增加嵌套节点。
    def test_multi_branch_choice_preserves_branch_order_and_tail(self) -> None:
        """多分支选择应保持顺序并共享完整的剩余语句块。"""

        source = (
            "{{choose {a!(0)} or {b!(0)} or {c!(0)}; "
            "done!(0); skip}}"
        )
        self.assertEqual(
            parse_hcsp(source),
            InternalChoice.of(
                OutputChannel("a", 0),
                OutputChannel("b", 0),
                OutputChannel("c", 0),
                continuation=Sequence.of(OutputChannel("done", 0), Skip()),
            ),
        )

    # 测试输入：带显式 invariant、通信前缀和回边 call 的 mu。
    # 预期行为：构造 Mu、RecursionAnnotation 和通信保护的 Var 回边。
    # 检查内容：比较递归名、体的顺序树及不变量 CompareExpr。
    # 论文对应：对应 Section 4.2/4.3 的带边界不变量递归变量。
    def test_annotated_guarded_recursion(self) -> None:
        """合法通信保护递归应完整保留不变量批注。"""

        source = "{{mu Loop invariant(x >= 0) {tick!(x); call Loop}}}"
        self.assertEqual(
            parse_hcsp(source),
            Mu(
                "Loop",
                Sequence.of(OutputChannel("tick", "x"), Var("Loop")),
                annotation=RecursionAnnotation(
                    CompareExpr((Variable("x"), Literal(0)), (">=",))
                ),
            ),
        )

    # 测试输入：缺 invariant 的 mu、缺 else 的 if、单分支 choose 和裸递归回边。
    # 预期行为：前三项为 syntax，未通信保护的回边为 validation 错误。
    # 检查内容：同时锁定复合语句必填部分和 Assumption 2.2 构造期边界。
    # 论文对应：保持二元条件/选择文法及递归通信保护假设。
    def test_malformed_control_and_unguarded_recursion_are_rejected(self) -> None:
        """复合控制语句缺失结构或违反递归保护时必须失败。"""

        cases = (
            ("{{mu Loop {tick!(0)}}}", "syntax"),
            ("{{if (true) {skip}}}", "syntax"),
            ("{{choose {skip}}}", "syntax"),
            ("{{mu Loop invariant(true) {call Loop}}}", "validation"),
        )
        for source, phase in cases:
            with self.subTest(source=source):
                with self.assertRaises(HCSPInputError) as context:
                    parse_hcsp(source)
                self.assertEqual(context.exception.phase, phase)


if __name__ == "__main__":
    unittest.main()
