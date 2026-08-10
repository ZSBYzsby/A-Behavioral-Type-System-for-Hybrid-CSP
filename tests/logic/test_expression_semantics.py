"""表达式静态类型、求值有定义性与状态值边界测试。

测试内容
--------
1. 整数操作数的 ``/`` 显式提升为实数除法。
2. 除零、负数平方根和实数取模不会泄漏 Z3 异常或被误判为真。
3. 赋值、if 和通道 refinement 会在对应规则位置立即判定偏表达式侧条件。
4. Bool 状态值必须是真正的 Python bool，不能用非空字符串冒充。

论文对应
--------
这些测试覆盖 Table 2 的表达式求值/基础类型前提，以及 T-Assign、T-If、T-Out
和 T-sigma 对未定义表达式或不合法具体状态的保守拒绝。
"""

from __future__ import annotations

import unittest

from hcsp_typechecker._internal import (
    Assign,
    BasicType,
    ChannelType,
    Configuration,
    If,
    OutputChannel,
    Skip,
    Verdict,
    construct_type,
)
from hcsp_typechecker.backend.common.logic import (
    ExpressionTranslator,
    Z3ProofEngine,
    z3,
)


class ExpressionSemanticTests(unittest.TestCase):
    """验证项目表达式到 Z3 的语义保持和偏函数侧条件。"""

    # 测试输入：无变量环境中的 ``1 / 2``。
    # 预期行为：结果类型和 Z3 sort 都是 Real，数值等于 1/2 而不是整数 0。
    # 检查内容：直接检查翻译结果，并分别证明正确等式与否定错误等式。
    # 论文对应：基础数值类型提升及数学除法的表达式求值前提。
    def test_integer_operands_use_real_division(self) -> None:
        """整数操作数不得让 ``/`` 退化为 Z3 整数除法。"""

        translator = ExpressionTranslator({})
        result = translator.translate("1 / 2")
        engine = Z3ProofEngine()

        self.assertEqual(result.value_type, BasicType.REAL)
        self.assertTrue(z3.is_real(result.term))
        self.assertEqual(engine.valid(result.term == z3.RealVal("1/2"))[0], Verdict.TRUE)
        self.assertEqual(engine.valid(result.term == 0)[0], Verdict.FALSE)

    # 测试输入：Real 赋值 ``y := 1 / x``，分别在 x!=0 和 x=0 的入口状态运行。
    # 预期行为：前者通过，后者由 T-Assign 的除数非零 premise 判为 false。
    # 检查内容：核对 verdict 和显式 T-Assign 义务，防止采用 Z3 的全除法语义。
    # 论文对应：T-Assign 要求右值表达式在当前状态下能够成功求值。
    def test_assignment_proves_symbolic_divisor_is_nonzero(self) -> None:
        """符号除法必须产生当前路径蕴含除数非零的证明义务。"""

        process = Assign("y", "1 / x")
        accepted = construct_type(
            gamma={"x": BasicType.REAL, "y": BasicType.REAL},
            theta={},
            configurations=[Configuration({"x": 1, "y": 0}, process)],
            path_condition="x != 0",
        )
        rejected = construct_type(
            gamma={"x": BasicType.REAL, "y": BasicType.REAL},
            theta={},
            configurations=[Configuration({"x": 0, "y": 0}, process)],
        )

        self.assertEqual(accepted.verdict, Verdict.TRUE)
        self.assertEqual(rejected.verdict, Verdict.FALSE)
        obligation = next(
            item for item in rejected.obligations if item.rule == "T-Assign"
        )
        self.assertEqual(obligation.verdict, Verdict.FALSE)

    # 测试输入：Real 变量上的 ``x % 2`` 和常量表达式 ``sqrt(-1)``。
    # 预期行为：两次检查都返回 false，且调用方看不到原始 Z3Exception。
    # 检查内容：前者产生清晰类型诊断，后者产生未定义性反例义务。
    # 论文对应：表达式类型前提和“求值失败则规则不可应用”的要求。
    def test_invalid_modulo_and_square_root_are_reported_cleanly(self) -> None:
        """不合法算术必须成为审计结果，而不能使类型构造器崩溃。"""

        modulo = construct_type(
            gamma={"x": BasicType.REAL},
            theta={},
            configurations=[Configuration({"x": 0}, Assign("x", "x % 2"))],
        )
        square_root = construct_type(
            gamma={"y": BasicType.REAL},
            theta={},
            configurations=[Configuration({"y": 0}, Assign("y", "sqrt(-1)"))],
        )

        self.assertEqual(modulo.verdict, Verdict.FALSE)
        self.assertTrue(
            any("Modulo operands" in item.message for item in modulo.diagnostics)
        )
        self.assertEqual(square_root.verdict, Verdict.FALSE)
        self.assertTrue(
            any(item.rule == "T-Assign" for item in square_root.obligations)
        )

    # 测试输入：守卫 ``1 / x > 0``，入口路径分别保证和不保证 x!=0。
    # 预期行为：已保证有定义时通过；x=0 时即使两个分支都是 Skip 也判 false。
    # 检查内容：要求失败报告中存在独立 T-If 有定义性 premise。
    # 论文对应：T-If 在按 B/非 B 分支前必须先能求得布尔守卫 B。
    def test_if_guard_is_defined_before_branching(self) -> None:
        """未定义守卫不能因两个分支恰好相同而被忽略。"""

        process = If("1 / x > 0", Skip(), Skip())
        accepted = construct_type(
            gamma={"x": BasicType.REAL},
            theta={},
            configurations=[Configuration({"x": 1}, process)],
            path_condition="x != 0",
        )
        rejected = construct_type(
            gamma={"x": BasicType.REAL},
            theta={},
            configurations=[Configuration({"x": 0}, process)],
        )

        self.assertEqual(accepted.verdict, Verdict.TRUE)
        self.assertEqual(rejected.verdict, Verdict.FALSE)
        self.assertTrue(
            any(item.rule == "T-If" for item in rejected.obligations)
        )

    # 测试输入：refinement ``1 / eta > 0`` 的 Real 通道上发送 0。
    # 预期行为：输出类型仍可构造，但 refinement 证明义务为 false。
    # 检查内容：核对 T-Out 统一包含除数非零条件和精化公式本身。
    # 论文对应：T-Out 的 ``phi => refinement[e/eta]`` 必须可定义且成立。
    def test_output_refinement_includes_definedness(self) -> None:
        """通道精化中的除零不能被 Z3 的全函数除法掩盖。"""

        report = construct_type(
            gamma={},
            theta={
                "ch": ChannelType(
                    BasicType.REAL,
                    "1 / eta > 0",
                    binders="eta",
                )
            },
            configurations=[Configuration({}, OutputChannel("ch", 0))],
        )

        self.assertEqual(report.verdict, Verdict.FALSE)
        obligation = next(
            item for item in report.obligations if item.rule == "T-Out"
        )
        self.assertEqual(obligation.verdict, Verdict.FALSE)

    # 测试输入：Bool 符号 b 与具体状态值字符串 ``"false"``。
    # 预期行为：状态检查返回 false，并说明 Bool 状态值类型不合法。
    # 检查内容：直接覆盖 Z3ProofEngine 的具体值转换边界。
    # 论文对应：T-sigma 的 sigma 必须按 Gamma 中的基础类型解释。
    def test_string_does_not_masquerade_as_boolean_state(self) -> None:
        """非空字符串不能再因 Python truthiness 被转换成 Z3 true。"""

        symbol = z3.Bool("b")
        verdict, detail = Z3ProofEngine().state_satisfies(
            symbol,
            {"b": "false"},
            {"b": symbol},
        )

        self.assertEqual(verdict, Verdict.FALSE)
        self.assertIn("must be bool", detail)


if __name__ == "__main__":
    unittest.main()
