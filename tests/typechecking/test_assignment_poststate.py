"""验证 T-Assign 的惰性最强后置状态与顺序公式判定的职责边界。

测试内容：

* 自赋值和连续赋值是否依次读取各自的赋值前符号状态；
* 后继 judgment 是否在规则展开阶段就收到已经确定的符号映射；
* 普通赋值是否只生成已具体化的 Table 2 后置条件 premise，而不是
  待综合的未知 ``phi'``；
* 赋值右值的有定义性条件是否仍作为已经具体化的 FOL premise 当场判定。

预期行为：T-Assign 使用“赋值前路径 + 更新后的 symbols”惰性表示最强后置
状态。顺序证明器只判定具体 state/FOL/dL 公式，不承担谓词综合。

论文对应：新版 Table 2 的 T-Assign 前提 ``phi => phi'{e/x}``，以及 PPT 中
已具体化的赋值后置公式。
"""

from __future__ import annotations

import unittest

from hcsp_typechecker import (
    Assert,
    Assign,
    BasicType,
    Configuration,
    Sequence,
    TypeChecker,
    TypingJudgment,
    Verdict,
)


class AssignmentPostStateTests(unittest.TestCase):
    """锁定后置状态生成和具体公式证明之间的实现边界。"""

    # 测试输入：x := x + 1; y := 2*x; assert(y == 2*x)，初始路径为 x == 3。
    # 预期行为：第二次赋值看到更新后的 x，断言再同时看到更新后的 x、y；
    #           三条规则入口的 symbolic_state 依次反映这一变化。
    # 检查内容：自赋值右侧使用旧 x、连续赋值顺序、后继 judgment 的符号快照、
    #           T-Assign 轨迹中可审计的惰性最强后置状态说明。
    # 论文对应：T-Assign 的 e 在赋值前状态求值，phi' 用于后继 P :: T。
    def test_successive_assignments_build_poststates_before_child_judgments(self) -> None:
        """每个赋值都应先生成后置状态，再展开它的顺序后继 judgment。"""

        process = Sequence.of(
            Assign("x", "x + 1"),
            Assign("y", "2 * x"),
            Assert("y == 2 * x"),
        )
        checker = TypeChecker(dl_checker=lambda _obligation: True)
        report = checker.check(
            TypingJudgment(
                gamma={"x": BasicType.INT, "y": BasicType.INT},
                theta={},
                configurations=[Configuration({"x": 3, "y": 0}, process)],
                path_condition="x == 3",
            )
        )

        self.assertEqual(report.verdict, Verdict.TRUE)
        assignment_steps = tuple(
            step for step in report.steps if step.rule == "T-Assign"
        )
        assertion_step = next(
            step for step in report.steps if step.rule == "T-Assert"
        )
        self.assertEqual(len(assignment_steps), 2)

        first_symbols = dict(assignment_steps[0].symbolic_state)
        second_symbols = dict(assignment_steps[1].symbolic_state)
        assertion_symbols = dict(assertion_step.symbolic_state)
        self.assertEqual(first_symbols["x"], "K1__x")
        self.assertIn("K1__x", second_symbols["x"])
        self.assertIn("1", second_symbols["x"])
        self.assertIn("K1__x", assertion_symbols["y"])
        self.assertNotEqual(assertion_symbols["y"], "K1__y")
        for step in assignment_steps:
            self.assertIn("惰性最强后置状态", step.detail)
            self.assertIn("不需要谓词综合", step.detail)

    # 测试输入：x := x + 1; assert(x >= 1)，路径条件 x >= 0。
    # 预期行为：报告按顺序含 T-sigma、按构造成立的 T-Assign-post 和具体化后的
    #           T-Assert；不存在用于寻找未知 phi' 的 predicate-synthesis 义务。
    # 检查内容：已判定义务的规则来源和 T-Assert 公式是否已经出现 x+1 替换。
    # 论文对应：实现通过惰性最强后置状态直接满足 phi => phi'{e/x} 的选择问题。
    def test_total_assignment_adds_only_concrete_table2_postcondition(self) -> None:
        """T-Assign 应立即判定具体 premise，而不能留下未知谓词。"""

        process = Sequence.of(
            Assign("x", "x + 1"),
            Assert("x >= 1"),
        )
        checker = TypeChecker(dl_checker=lambda _obligation: True)
        report = checker.check(
            TypingJudgment(
                gamma={"x": BasicType.INT},
                theta={},
                configurations=[Configuration({"x": 0}, process)],
                path_condition="x >= 0",
            )
        )

        self.assertEqual(report.verdict, Verdict.TRUE)
        decided = report.obligations
        self.assertEqual(
            tuple(item.rule for item in decided),
            ("T-sigma", "T-Assign-post", "T-Assert"),
        )
        self.assertTrue(all(item.verdict == Verdict.TRUE for item in decided))
        postcondition = decided[1]
        postcondition_formula = str(postcondition.formula)
        self.assertIn("Implies", postcondition_formula)
        self.assertGreaterEqual(postcondition_formula.count("K1__x"), 2)
        self.assertIn("generated lazy strongest post-state", postcondition.description)
        assertion_formula = str(decided[2].formula)
        self.assertIn("K1__x + 1", assertion_formula)
        self.assertFalse(
            any("unknown" in item.description.lower() for item in decided),
            "Sequential proofs must contain concrete premises, not synthesis tasks",
        )

    # 测试输入：y := 1/x，路径条件 x != 0。
    # 预期行为：除数非零是已具体化的 T-Assign FOL premise，当场被证明；
    #           这不能与“把未知 phi' 交给证明器综合”混为一谈。
    # 检查内容：T-Assign 义务的描述和公式均只涉及明确的有定义性条件。
    # 论文对应：T-Assign 的表达式类型/求值前提与后置状态选择是两个独立职责。
    def test_partial_rhs_adds_only_concrete_definedness_formula(self) -> None:
        """顺序证明可判定具体 T-Assign 公式，但不搜索未知后置谓词。"""

        checker = TypeChecker(dl_checker=lambda _obligation: True)
        report = checker.check(
            TypingJudgment(
                gamma={"x": BasicType.REAL, "y": BasicType.REAL},
                theta={},
                configurations=[
                    Configuration({"x": 2, "y": 0}, Assign("y", "1 / x"))
                ],
                path_condition="x != 0",
            )
        )

        self.assertEqual(report.verdict, Verdict.TRUE)
        assignment_premises = tuple(
            item
            for item in report.obligations
            if item.rule == "T-Assign"
        )
        self.assertEqual(len(assignment_premises), 1)
        self.assertIn("is defined", assignment_premises[0].description)
        self.assertIn("K1__x", str(assignment_premises[0].formula))
        self.assertNotIn("phi'", assignment_premises[0].description)


if __name__ == "__main__":
    unittest.main()
