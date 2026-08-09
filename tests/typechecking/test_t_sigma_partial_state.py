r"""Table 2 [T-sigma] 的部分状态替换语义测试。

测试内容
--------
1. ``Gamma`` 是状态变量的基础类型声明环境，``state`` 允许只给其中一部分
   变量赋值，即 ``dom(state) subseteq dom(Gamma)``；
2. 已赋值变量按 Gamma 声明的 sort 代入路径公式，未赋值变量保留在
   ``phi[state]`` 中；
3. T-sigma 检查的是 ``|= phi[state]``。只要 Z3 找到一个残留变量反例，结果
   就是 false，而不是只有公式恒假时才是 false；
4. state 引入 Gamma 未声明的变量属于未定义状态，规则层必须停止类型生成，
   底层证明器也必须拒绝，不能静默忽略。

论文对应
--------
对应 Table 2 [T-sigma] 的状态前提。这里按项目与论文采用的替换写法解释
``sigma |= phi``：sigma 是 Gamma 上的部分赋值，判断目标为
``|= phi[sigma]``；Gamma 提供变量声明和替换值的 Basic Type，不要求 sigma
覆盖 Gamma 的整个定义域。
"""

from __future__ import annotations

import unittest

from hcsp_typechecker._internal import (
    BasicType,
    Configuration,
    EndType,
    Skip,
    Verdict,
    check_hcsp,
)
from hcsp_typechecker.typechecking.logic import Z3ProofEngine, z3


@unittest.skipIf(z3 is None, "z3-solver is required")
class TSigmaPartialStateTests(unittest.TestCase):
    """验证部分替换、全称有效性和未声明状态变量边界。"""

    # 测试输入：Gamma 声明 x、y，state 只提供 x=0，路径为
    #           ``x=0 and y*y>=0``。
    # 预期行为：允许缺少 y 的部分状态；替换后证明 ``y*y>=0`` 对所有 Real y
    #           有效，T-sigma 和完整检查均成功，类型为 EndType。
    # 检查内容：覆盖 dom(state) 是 dom(Gamma) 真子集时的正例。
    # 论文对应：[T-sigma] 的 ``|= phi[sigma]``。
    def test_partial_state_is_accepted_when_residual_formula_is_valid(self) -> None:
        """未赋值的 Gamma 变量保留为全称有效性检查中的自由符号。"""

        report = check_hcsp(
            gamma={"x": BasicType.REAL, "y": BasicType.REAL},
            theta={},
            configurations=[Configuration({"x": 0}, Skip())],
            path_condition="x == 0 and y * y >= 0",
        )

        self.assertEqual(report.verdict, Verdict.TRUE)
        self.assertEqual(report.inferred_type, EndType())
        obligation = next(
            item for item in report.obligations if item.rule == "T-sigma"
        )
        self.assertEqual(obligation.verdict, Verdict.TRUE)
        self.assertIn("residual path condition is valid", obligation.detail)

    # 测试输入：Gamma 声明 x、y，state 只提供 x=0，路径为
    #           ``x=0 and y>0``。
    # 预期行为：替换后 ``y>0`` 不是有效公式；Z3 给出反例，T-sigma 为 false，
    #           而不是 unknown；推导立即停止，不再访问 Skip 或生成 EndType。
    # 检查内容：覆盖“可满足但不恒真”的残留公式，防止旧实现只识别恒假公式。
    # 论文对应：[T-sigma] 要求有效性 ``|= phi[sigma]``，一个反例即可否证。
    def test_counterexample_to_residual_formula_is_false_not_unknown(self) -> None:
        """残留公式不恒真时直接使用 valid 的反例结论。"""

        report = check_hcsp(
            gamma={"x": BasicType.REAL, "y": BasicType.REAL},
            theta={},
            configurations=[Configuration({"x": 0}, Skip())],
            path_condition="x == 0 and y > 0",
        )

        self.assertEqual(report.verdict, Verdict.FALSE)
        self.assertIsNone(report.inferred_type)
        obligation = next(
            item for item in report.obligations if item.rule == "T-sigma"
        )
        self.assertEqual(obligation.verdict, Verdict.FALSE)
        self.assertIn("residual path condition is not valid", obligation.detail)
        self.assertIn("counterexample", obligation.detail)
        self.assertFalse(any(item.rule == "T-End" for item in report.steps))

    # 测试输入：局部 Gamma 只声明 x，但 state 同时给出 x 和 ghost。
    # 预期行为：ghost 没有 Basic Type，T-sigma 在创建状态证明义务之前静态失败，
    #           最终没有候选类型，并明确指出 ghost 未在局部 Gamma 声明。
    # 检查内容：覆盖规则层的 dom(state) subseteq dom(Gamma) 检查。
    # 论文对应：Gamma 必须为状态替换中的每一个已赋值变量提供类型解释。
    def test_undeclared_state_variable_stops_type_generation(self) -> None:
        """未知状态变量不能被当作与路径条件无关的多余输入忽略。"""

        report = check_hcsp(
            gamma={"x": BasicType.INT},
            theta={},
            configurations=[Configuration({"x": 0, "ghost": 1}, Skip())],
            path_condition=True,
        )

        self.assertEqual(report.verdict, Verdict.FALSE)
        self.assertIsNone(report.inferred_type)
        self.assertFalse(
            any(item.rule == "T-sigma" for item in report.obligations)
        )
        self.assertTrue(
            any(
                "not declared in the local Gamma" in item.message
                and "ghost" in item.message
                for item in report.diagnostics
            )
        )

    # 测试输入：绕过 TypeChecker，直接把未声明的 ghost 状态项交给证明引擎。
    # 预期行为：底层仍返回 false 并报告 Gamma 声明错误，不执行旧版的 continue。
    # 检查内容：防御性覆盖 state_satisfies 的公开调用边界。
    # 论文对应：未声明变量无法按 Gamma 的 Basic Type 构造替换项。
    def test_proof_engine_also_rejects_undeclared_state_variable(self) -> None:
        """底层状态证明不能依赖规则层已提前完成检查。"""

        x = z3.Int("x")
        verdict, detail = Z3ProofEngine().state_satisfies(
            x == 0,
            {"x": 0, "ghost": 1},
            {"x": x},
        )

        self.assertEqual(verdict, Verdict.FALSE)
        self.assertIn("not declared in Gamma", detail)
        self.assertIn("ghost", detail)


if __name__ == "__main__":
    unittest.main()
