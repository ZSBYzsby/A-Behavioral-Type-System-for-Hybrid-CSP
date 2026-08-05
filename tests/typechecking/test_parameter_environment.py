r"""共享只读参数环境的类型推导与安全边界测试。

测试内容
--------
参数在执行前由用户预赋值，所有合法赋值满足参数环境约束。检查约束传播、
并行共享、全称初态证明、约束可满足性，以及赋值、输入、ODE 和初态的只读边界。

论文对应
--------
参数环境 H 独立于状态 Gamma；T-sigma 证明 H => phi[sigma]，后续规则在 H and phi 下推导。
"""

from __future__ import annotations

import unittest

from hcsp_typechecker import (
    Assert,
    Assign,
    BasicType,
    ChannelType,
    Configuration,
    ContinuousType,
    DLCheckResult,
    ODE,
    ODEAnnotation,
    OutputChannel,
    InputChannel,
    ParallelType,
    ParameterEnvironment,
    Mu,
    Sequence,
    Var,
    Verdict,
    check_hcsp,
)


def _approve_dl(_obligation: object) -> DLCheckResult:
    """让非 dL 专项测试只观察参数环境如何进入规则。"""

    return DLCheckResult(Verdict.TRUE, "approved by parameter-environment test")


class ParameterEnvironmentTests(unittest.TestCase):
    """检查共享参数的约束传播、并行共享和只读性质。"""

    # 测试输入：约束 limit >= 0 和相同断言。
    # 预期行为：参数约束作为背景假设，推导成功。
    # 检查内容：约束传播与详细报告展示。
    # 论文对应：公式在参数环境 H 下判定。
    def test_constraint_is_a_background_assumption(self) -> None:
        """参数约束应推出断言，而不是被 T-sigma 当作无条件真命题。"""

        report = check_hcsp(
            gamma={},
            theta={},
            configurations=[Assert("limit >= 0")],
            parameters=ParameterEnvironment(
                {"limit": BasicType.REAL},
                "limit >= 0",
            ),
        )

        self.assertEqual(report.verdict, Verdict.TRUE, report.format_detailed())
        self.assertIsNotNone(report.inferred_type)
        self.assertIn("Parameters: limit:Real", report.format_detailed())
        self.assertIn("参数约束", report.format_detailed())

    # 测试输入：H 为 limit >= 0，局部初态条件为 limit > 0。
    # 预期行为：由于边界赋值 limit = 0，全称证明失败。
    # 检查内容：初态不是只对某一个参数实例检查。
    # 论文对应：T-sigma 前提 H => phi[sigma]。
    def test_initial_path_is_proved_for_every_admissible_assignment(self) -> None:
        """H 只能推出真正随 H 成立的局部初态条件。"""

        report = check_hcsp(
            gamma={},
            theta={},
            configurations=[
                Configuration(
                    {},
                    Assert(True),
                    path_condition="limit > 0",
                )
            ],
            parameters=ParameterEnvironment(
                {"limit": BasicType.REAL},
                "limit >= 0",
            ),
        )

        self.assertEqual(report.verdict, Verdict.FALSE)
        self.assertIsNone(report.inferred_type)
        self.assertEqual(report.obligations[0].rule, "T-sigma")

    # 测试输入：不可满足的参数约束 x > 0 and x < 0。
    # 预期行为：在进入类型推导前拒绝该环境。
    # 检查内容：禁止利用矛盾假设真空地证明任意结论。
    # 论文对应：参数域 H 必须非空。
    def test_unsatisfiable_parameter_constraint_is_rejected(self) -> None:
        """矛盾参数约束不能用真空蕴含伪造成功推导。"""

        report = check_hcsp(
            gamma={},
            theta={},
            configurations=[Assert(True)],
            parameters=ParameterEnvironment(
                {"x": BasicType.REAL},
                "x > 0 and x < 0",
            ),
        )

        self.assertEqual(report.verdict, Verdict.FALSE)
        self.assertTrue(
            any("unsatisfiable" in item.message for item in report.diagnostics)
        )

    # 测试输入：两个并行配置读取同一个 limit 参数。
    # 预期行为：两个配置均推导成功，得到并行类型。
    # 检查内容：参数跨配置共享，但不进入局部 Gamma 划分。
    # 论文对应：并行规则共享 H，仅状态环境互斥。
    def test_parameters_are_shared_without_entering_gamma_partition(self) -> None:
        """两个配置可以读取同一参数，同时保持局部状态 Gamma 不相交。"""

        left = Sequence.of(Assert("limit >= 0"), OutputChannel("left", 0))
        right = Sequence.of(Assert("limit >= 0"), OutputChannel("right", 0))
        report = check_hcsp(
            gamma={},
            theta={
                "left": ChannelType(BasicType.INT),
                "right": ChannelType(BasicType.INT),
            },
            configurations=(
                Configuration({}, left, gamma={}, name="Left"),
                Configuration({}, right, gamma={}, name="Right"),
            ),
            parameters=ParameterEnvironment(
                {"limit": BasicType.REAL},
                "limit >= 0",
            ),
        )

        self.assertEqual(report.verdict, Verdict.TRUE, report.format_detailed())
        self.assertIsInstance(report.inferred_type, ParallelType)

    # 测试输入：尝试通过赋值、输入、ODE 左端和初态改写 limit。
    # 预期行为：所有改写方式均被拒绝。
    # 检查内容：参数的语法和语义只读边界。
    # 论文对应：预赋值参数在 HCSP 执行期间保持不变。
    def test_parameters_cannot_be_modified_by_hcsp(self) -> None:
        """赋值、输入目标、ODE 左端和初态都不能写共享参数。"""

        parameter_environment = ParameterEnvironment(
            {"limit": BasicType.REAL},
            "limit >= 0",
        )
        cases = (
            (
                "assignment",
                Assign("limit", 1),
                {},
                {},
            ),
            (
                "input",
                InputChannel("set", "limit"),
                {},
                {"set": ChannelType(BasicType.REAL)},
            ),
            (
                "ode",
                ODE(
                    [("limit", 0)],
                    True,
                    annotation=ODEAnnotation(delay=1),
                ),
                {},
                {},
            ),
        )
        for name, process, gamma, theta in cases:
            with self.subTest(name=name):
                report = check_hcsp(
                    gamma=gamma,
                    theta=theta,
                    configurations=[process],
                    parameters=parameter_environment,
                    dl_checker=_approve_dl,
                )
                self.assertEqual(report.verdict, Verdict.FALSE)
                self.assertTrue(
                    any("read-only parameter" in item.message for item in report.diagnostics),
                    report.format_detailed(),
                )

        initial_state_report = check_hcsp(
            gamma={},
            theta={},
            configurations=[Configuration({"limit": 1}, Assert(True))],
            parameters=parameter_environment,
        )
        self.assertEqual(initial_state_report.verdict, Verdict.FALSE)
        self.assertTrue(
            any(
                "Initial state cannot assign" in item.message
                for item in initial_state_report.diagnostics
            )
        )

    # 测试输入：安全后置条件引用参数 limit 的 ODE。
    # 预期行为：dL 义务接收参数约束和参数符号。
    # 检查内容：H 进入 ODE 前提，limit 不进入演化向量。
    # 论文对应：ODE 规则的前提在 H and phi 下证明。
    def test_parameter_constraint_reaches_dl_precondition(self) -> None:
        """ODE 证明前件应包含参数约束，参数本身不进入演化向量。"""

        captured: list[object] = []

        def capture(obligation: object) -> DLCheckResult:
            """记录 dL 证明义务并在本测试中批准它。"""

            captured.append(obligation)
            return DLCheckResult(Verdict.TRUE, "captured")

        report = check_hcsp(
            gamma={
                "x": BasicType.REAL,
                "flow": ContinuousType(("x",)),
            },
            theta={},
            configurations=[
                Configuration(
                    {"x": 0},
                    ODE(
                        [("x", 1)],
                        True,
                        annotation=ODEAnnotation(
                            safety="x <= limit",
                            delay=1,
                        ),
                    ),
                )
            ],
            parameters=ParameterEnvironment(
                {"limit": BasicType.REAL},
                "limit >= 1",
            ),
            dl_checker=capture,
        )

        self.assertEqual(report.verdict, Verdict.TRUE, report.format_detailed())
        self.assertTrue(captured)
        formula = captured[0].formula  # type: ignore[attr-defined]
        self.assertTrue(
            any(
                "limit" in source_name or "limit" in target_name
                for source_name, target_name in formula.symbol_map
            )
        )

    # 测试输入：递归程序每轮断言 limit >= 0。
    # 预期行为：递归入口刷新状态时仍保留参数假设。
    # 检查内容：参数符号与约束跨递归边传播。
    # 论文对应：递归规则共享不变的 H。
    def test_parameter_constraint_persists_at_recursive_entry(self) -> None:
        """递归抽象状态应刷新私有状态，但继续使用同一参数预赋值。"""

        process = Mu(
            "X",
            Sequence.of(
                Assert("limit >= 0"),
                OutputChannel("tick", 0),
                Var("X"),
            ),
        )
        report = check_hcsp(
            gamma={},
            theta={"tick": ChannelType(BasicType.INT)},
            configurations=[process],
            parameters=ParameterEnvironment(
                {"limit": BasicType.REAL},
                "limit >= 0",
            ),
        )

        self.assertEqual(report.verdict, Verdict.TRUE, report.format_detailed())

    # 测试输入：x 同时声明为状态变量和共享参数。
    # 预期行为：在推导前拒绝名称冲突。
    # 检查内容：Gamma 与 H 的声明域相互独立。
    # 论文对应：可变状态与只读参数属于不同环境。
    def test_parameter_names_cannot_overlap_state_gamma(self) -> None:
        """同一名称不能同时表示共享参数和分量私有状态。"""

        report = check_hcsp(
            gamma={"x": BasicType.REAL},
            theta={},
            configurations=[Assert(True)],
            parameters=ParameterEnvironment({"x": BasicType.REAL}),
        )

        self.assertEqual(report.verdict, Verdict.FALSE)
        self.assertTrue(
            any("overlap" in item.message for item in report.diagnostics)
        )


if __name__ == "__main__":
    unittest.main()
