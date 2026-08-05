r"""Definition 4.1 连续 Gamma 项及 T-ODE 使用边界测试。

测试内容
--------
1. ``ContinuousType`` 显式连续向量可以组成 ODE 左侧，普通 Real 参数仍可
   出现在导数、路径和 safety 中；
2. 普通 ``BasicType.REAL`` 不能冒充 ODE 左端的连续变量；
3. 离散赋值和通信输入只更新连续变量的当前值，不删除连续类别；
4. 连续变量在 ODE 外按当前 Real 值参与普通表达式和输出；
5. ``ContinuousType.phi`` 只在声明向量与 ODE 用户左侧向量按顺序精确相同时，
   与节点 safety 一同进入 dL 后置目标；子集、超集和隐式时钟都不改变匹配；
6. 顶层/局部 Gamma 必须完整、一致地登记连续向量的所有成员。

预期行为
--------
Gamma 显式区分 ``x:Real`` 与 ``x:ContinuousType``。表达式层把后者读取为 Real，
但 T-ODE 只接受后者作为微分方程左端。非法普通 Real ODE 在建立 dL 义务前
静态失败；合法连续变量经过赋值或输入后仍可继续演化。

论文对应
--------
对应 Definition 4.1 的普通值项 ``x:B`` 与连续轨迹项
``underlined(v):R_{>=0} partial-function R^n``，以及 Table 2 [T-ODE]。
"""

from __future__ import annotations

from math import inf
import unittest

from hcsp_typechecker import (
    Assert,
    Assign,
    BasicType,
    ChannelType,
    Configuration,
    ContinuousType,
    DLFormula,
    EndType,
    EventChoice,
    InputChannel,
    ODE,
    ODEAnnotation,
    OutputChannel,
    OutputType,
    Sequence,
    Skip,
    Verdict,
    check_hcsp,
)


def _approve_dl(_obligation: object) -> Verdict:
    """固定证明测试产生的非平凡 dL premise。"""

    return Verdict.TRUE


class ContinuousGammaTests(unittest.TestCase):
    """验证连续声明、当前值读取以及 ODE 左端资格。"""

    # 测试输入：x、v 为连续 Real，gain 为普通 Real；ODE 使用三者构造向量场。
    # 预期行为：连续向量通过 T-ODE，普通参数可读取但不被误当成演化变量。
    # 检查内容：总体 true、正式类型存在、T-ODE 步骤显示两类 Gamma 项。
    # 论文对应：[T-ODE] 要求 v 向量连续，而 e 可读取 Gamma 中普通值变量。
    def test_explicit_continuous_vector_accepts_ordinary_real_parameter(self) -> None:
        """ODE 左端连续声明与右端普通 Real 参数可以共存。"""

        process = ODE(
            [("x", "v"), ("v", "-x * gain")],
            "x * x + v * v <= 4",
            annotation=ODEAnnotation(
                safety="x * x + v * v <= 4",
                delay=inf,
            ),
        )
        oscillator = ContinuousType(variables=("x", "v"))
        report = check_hcsp(
            gamma={"x": oscillator, "v": oscillator, "gain": BasicType.REAL},
            theta={},
            configurations=[
                Configuration({"x": 0, "v": 1, "gain": 1}, process)
            ],
            path_condition="x == 0 and v == 1 and gain == 1",
            dl_checker=_approve_dl,
        )

        self.assertEqual(report.verdict, Verdict.TRUE)
        self.assertIsNotNone(report.inferred_type)
        ode_step = next(item for item in report.steps if item.rule == "T-ODE")
        self.assertIn(("x", "R>=0 ~> Real on (x, v)"), ode_step.gamma)
        self.assertIn(("v", "R>=0 ~> Real on (x, v)"), ode_step.gamma)
        self.assertIn(("gain", "Real"), ode_step.gamma)

    # 测试输入：ODE 节点 safety=x<=10，Gamma 把连续 x 声明为
    #           ContinuousType(phi="x >= 0")。
    # 预期行为：x>=0 与 x<=10 都出现在 box 后置目标，程序域不预设 x>=0；
    #           因而错误的 Gamma 连续条件能够使这条证明义务失败。
    # 检查内容：捕获正式 DLFormula，并把 box 程序与后置公式拆开核对。
    # 论文对应：Definition 4.1 的 underlined(x):R>=0 -> phi 要求连续轨迹始终
    #           位于 phi 描述的状态空间。
    def test_continuous_phi_is_part_of_the_dl_safety_goal(self) -> None:
        """Gamma 连续性质必须由 dL 证明，不能作为程序域假设。"""

        captured: list[object] = []

        def collect_and_approve(obligation: object) -> Verdict:
            """保存正式义务；本测试只审计公式构造，不测试外部证明器。"""

            captured.append(obligation)
            return Verdict.TRUE

        report = check_hcsp(
            gamma={"x": ContinuousType(phi="x >= 0")},
            theta={},
            configurations=[
                Configuration(
                    {"x": 0},
                    ODE(
                        [("x", 0)],
                        True,
                        annotation=ODEAnnotation(safety="x <= 10", delay=1),
                    ),
                )
            ],
            path_condition="x == 0",
            dl_checker=collect_and_approve,
        )

        safety_obligation = next(
            item
            for item in report.obligations
            if item.rule == "T-ODE-safety"
        )
        self.assertEqual(report.verdict, Verdict.TRUE)
        self.assertIsInstance(safety_obligation.formula, DLFormula)
        self.assertNotEqual(safety_obligation.formula.source, "true")
        program, post = safety_obligation.formula.source.split("}]", 1)
        self.assertIn("[{", program)
        self.assertNotRegex(program, r"0 <= kxv\d+")
        self.assertRegex(post, r"0 <= kxv\d+")
        self.assertRegex(post, r"10 >= kxv\d+")
        self.assertTrue(captured)

    # 测试输入：Gamma 声明联合向量 (x,y) 的 phi=x+y>=123，ODE 左侧也恰好
    #           是有序向量 (x,y)，节点 safety=true。
    # 预期行为：联合 phi 出现在 dL box 的后置目标，而不进入连续程序域。
    # 检查内容：捕获正式 safety DLFormula，并分别检查 program/post 文本。
    # 论文对应：连续约束属于完整 underlined(v)，精确向量匹配时由 T-ODE 验证。
    def test_joint_phi_applies_to_exact_ode_vector(self) -> None:
        """ODE 用户左侧与声明向量完全相同时必须验证联合 phi。"""

        captured: list[object] = []

        def collect_and_approve(obligation: object) -> Verdict:
            """保存精确向量测试生成的 dL 义务并固定批准证明结果。"""

            captured.append(obligation)
            return Verdict.TRUE

        trajectory = ContinuousType(
            variables=("x", "y"),
            phi="x + y >= 123",
        )
        report = check_hcsp(
            gamma={"x": trajectory, "y": trajectory},
            theta={},
            configurations=[
                Configuration(
                    {"x": 0, "y": 0},
                    ODE(
                        [("x", 0), ("y", 0)],
                        True,
                        annotation=ODEAnnotation(safety=True, delay=1),
                    ),
                )
            ],
            dl_checker=collect_and_approve,
        )

        safety = next(
            item for item in report.obligations if item.rule == "T-ODE-safety"
        )
        self.assertEqual(report.verdict, Verdict.TRUE)
        self.assertIsInstance(safety.formula, DLFormula)
        program, post = safety.formula.source.split("}]", 1)
        self.assertNotIn("123", program)
        self.assertIn("123", post)
        self.assertTrue(captured)

    # 测试输入：Gamma 仍声明联合向量 (x,y)，但 ODE 左侧分别取子向量 (x)、
    #           逆序向量 (y,x) 和超向量 (x,y,z)。联合 phi 故意写成非 Bool 的
    #           x+y；若错误触发，T-ODE 会立即产生 Bool 类型错误。
    # 预期行为：三种不精确匹配都不要求该联合 phi，推导保持 true。
    # 检查内容：verdict、正式类型以及无 Bool 类型诊断。
    # 论文对应：phi 只约束声明时的完整有序连续向量，不向子集或超集传播。
    def test_joint_phi_does_not_apply_to_nonmatching_ode_vectors(self) -> None:
        """子集、成员顺序不同和超集都不能触发联合向量 phi。"""

        trajectory = ContinuousType(variables=("x", "y"), phi="x + y")
        cases = (
            (
                "subset",
                [("x", 0)],
                {"x": trajectory, "y": trajectory},
                {"x": 0, "y": 0},
            ),
            (
                "reordered",
                [("y", 0), ("x", 0)],
                {"x": trajectory, "y": trajectory},
                {"x": 0, "y": 0},
            ),
            (
                "superset",
                [("x", 0), ("y", 0), ("z", 0)],
                {
                    "x": trajectory,
                    "y": trajectory,
                    "z": ContinuousType(),
                },
                {"x": 0, "y": 0, "z": 0},
            ),
        )
        for label, equations, gamma, state in cases:
            with self.subTest(label=label):
                report = check_hcsp(
                    gamma=gamma,
                    theta={},
                    configurations=[
                        Configuration(
                            state,
                            ODE(
                                equations,
                                True,
                                annotation=ODEAnnotation(safety=True, delay=1),
                            ),
                        )
                    ],
                    dl_checker=_approve_dl,
                )
                self.assertEqual(report.verdict, Verdict.TRUE, report.diagnostics)
                self.assertIsNotNone(report.inferred_type)
                self.assertFalse(
                    any("Bool" in item.message for item in report.diagnostics),
                    report.diagnostics,
                )

    # 测试输入：显式单元素向量 (x) 的 phi 故意使用非 Bool 表达式 x+1；ODE
    #           用户左侧只有 x，但生成的 dL 动力系统还会自动追加隐式 t'=1。
    # 预期行为：仍视为精确匹配并因 phi 非 Bool 静态失败，证明时钟未参加比较。
    # 检查内容：false、空 dL 后端调用以及 Bool 诊断。
    # 论文对应：局部计时变量服务于规则证明，不属于 underlined(v) 的成员。
    def test_implicit_clock_is_excluded_from_vector_match(self) -> None:
        """自动添加的 ODE 局部时钟不得破坏用户连续向量的精确匹配。"""

        calls: list[object] = []
        trajectory = ContinuousType(variables=("x",), phi="x + 1")
        report = check_hcsp(
            gamma={"x": trajectory},
            theta={},
            configurations=[
                Configuration(
                    {"x": 0},
                    ODE(
                        [("x", 0)],
                        True,
                        annotation=ODEAnnotation(safety=True, delay=1),
                    ),
                )
            ],
            dl_checker=lambda obligation: calls.append(obligation),
        )

        self.assertEqual(report.verdict, Verdict.FALSE)
        self.assertIsNone(report.inferred_type)
        self.assertEqual(calls, [])
        self.assertTrue(
            any("Bool" in item.message for item in report.diagnostics),
            report.diagnostics,
        )

    # 测试输入：显式向量 (x,y) 只登记 x，或在 y 下登记不同 phi。
    # 预期行为：环境规范化阶段拒绝不完整/不一致向量，不进入任何类型规则。
    # 检查内容：false、无正式类型和精确环境诊断。
    # 论文对应：一个 underlined(v) 是单一 Gamma 项，逐标量存储必须保持原子性。
    def test_explicit_vector_registration_must_be_complete_and_consistent(self) -> None:
        """同一显式连续向量在每个 Gamma 成员下必须完整且完全一致。"""

        complete = ContinuousType(variables=("x", "y"), phi="x >= 0")
        inconsistent = ContinuousType(variables=("x", "y"), phi="y >= 0")
        cases = (
            ({"x": complete}, "missing Gamma member"),
            ({"x": complete, "y": inconsistent}, "inconsistent Gamma declaration"),
        )
        for gamma, message in cases:
            with self.subTest(message=message):
                report = check_hcsp(
                    gamma=gamma,
                    theta={},
                    configurations=[Configuration({}, Skip())],
                )
                self.assertEqual(report.verdict, Verdict.FALSE)
                self.assertIsNone(report.inferred_type)
                self.assertTrue(
                    any(message in item.message for item in report.diagnostics),
                    report.diagnostics,
                )

    # 测试输入：连续 x 的 phi 错写成数值表达式 x+1，并在 ODE 中演化 x。
    # 预期行为：T-ODE 静态拒绝该声明，不调用 dL 后端，也不生成正式行为类型。
    # 检查内容：false 结论、空后端调用以及 Bool 类型错误说明。
    # 论文对应：Definition 4.1 明确要求 phi 是关于连续变量的一阶公式。
    def test_continuous_phi_must_be_boolean_when_used_by_ode(self) -> None:
        """数值表达式不能冒充连续轨迹公式 phi。"""

        calls: list[object] = []

        def unexpected_backend(obligation: object) -> Verdict:
            """记录静态错误后不应发生的外部证明调用。"""

            calls.append(obligation)
            return Verdict.TRUE

        report = check_hcsp(
            gamma={"x": ContinuousType(phi="x + 1")},
            theta={},
            configurations=[
                Configuration(
                    {"x": 0},
                    ODE(
                        [("x", 0)],
                        True,
                        annotation=ODEAnnotation(delay=1),
                    ),
                )
            ],
            path_condition="x == 0",
            dl_checker=unexpected_backend,
        )

        self.assertEqual(report.verdict, Verdict.FALSE)
        self.assertIsNone(report.inferred_type)
        self.assertEqual(calls, [])
        self.assertTrue(
            any("Bool" in item.message for item in report.diagnostics),
            report.diagnostics,
        )

    # 测试输入：Gamma 声明 x 的连续性质 x>=0；ODE 节点 safety=true，并可经
    #           tick! 中断后立即执行 assert(x>=0)。
    # 预期行为：ODE 的通信后继路径继承已经证明的 Gamma 连续条件在中断点的实例，
    #           T-Assert 可由后继路径直接推出。
    # 检查内容：总体 true、正式输出类型以及已证明的 T-Assert 义务。
    # 论文对应：连续类型性质描述轨迹状态空间，在连续段的任意中断点仍成立。
    def test_continuous_phi_is_available_at_ode_interrupt(self) -> None:
        """已证明的 Gamma 连续条件必须进入 ODE 通信后继上下文。"""

        process = ODE(
            [("x", 0)],
            True,
            EventChoice.of(
                (OutputChannel("tick", 0), Assert("x >= 0")),
            ),
            annotation=ODEAnnotation(safety=True, delay=inf),
        )
        report = check_hcsp(
            gamma={"x": ContinuousType(phi="x >= 0")},
            theta={"tick": ChannelType(BasicType.INT)},
            configurations=[Configuration({"x": 0}, process)],
            path_condition="x == 0",
            dl_checker=_approve_dl,
        )

        self.assertEqual(report.verdict, Verdict.TRUE)
        self.assertEqual(report.inferred_type, OutputType("tick", EndType()))
        assert_obligation = next(
            item for item in report.obligations if item.rule == "T-Assert"
        )
        self.assertEqual(assert_obligation.verdict, Verdict.TRUE)

    # 测试输入：x 只声明为普通 BasicType.REAL，却出现在 ODE 方程左端。
    # 预期行为：T-ODE 静态失败、无正式类型，且 dL 后端不会被调用。
    # 检查内容：ContinuousType 定位诊断和空 ODE 证明义务集合。
    # 论文对应：普通 x:R 与 underlined(x):trajectory 是不同 Gamma 项。
    def test_ordinary_real_cannot_be_an_ode_lvalue(self) -> None:
        """普通 Real 声明不能依靠 ODE 语法被隐式升级成连续变量。"""

        calls: list[object] = []

        def backend(obligation: object) -> Verdict:
            """记录不应发生的 dL 后端调用。"""

            calls.append(obligation)
            return Verdict.TRUE

        report = check_hcsp(
            gamma={"x": BasicType.REAL},
            theta={},
            configurations=[
                Configuration(
                    {"x": 0},
                    ODE(
                        [("x", 1)],
                        True,
                        annotation=ODEAnnotation(delay=inf),
                    ),
                )
            ],
            dl_checker=backend,
        )

        self.assertEqual(report.verdict, Verdict.FALSE)
        self.assertIsNone(report.inferred_type)
        self.assertEqual(calls, [])
        self.assertFalse(
            any(item.rule.startswith("T-ODE-") for item in report.obligations)
        )
        self.assertTrue(
            any("must have ContinuousType" in item.message for item in report.diagnostics)
        )

    # 测试输入：连续 x 先执行离散赋值 x:=0，再进入 x'=1 的 ODE。
    # 预期行为：赋值使用 x 的 Real 当前值类型，后继 Gamma 仍将 x 标记为连续。
    # 检查内容：T-Assign 和 T-ODE 都执行、总体 true、ODE 步骤仍显示连续声明。
    # 论文对应：连续变量在 ODE 外表示当前状态值，但其轨迹类别不能被赋值删除。
    def test_assignment_preserves_continuous_declaration(self) -> None:
        """离散重置连续变量后仍可把它作为 ODE 左端。"""

        process = Sequence.of(
            Assign("x", 0),
            ODE(
                [("x", 1)],
                True,
                annotation=ODEAnnotation(delay=inf),
            ),
        )
        report = check_hcsp(
            gamma={"x": ContinuousType()},
            theta={},
            configurations=[Configuration({"x": 2}, process)],
            dl_checker=_approve_dl,
        )

        self.assertEqual(report.verdict, Verdict.TRUE)
        self.assertIsNotNone(report.inferred_type)
        self.assertTrue(any(item.rule == "T-Assign" for item in report.steps))
        ode_step = next(item for item in report.steps if item.rule == "T-ODE")
        self.assertIn(("x", "R>=0 ~> Real"), ode_step.gamma)

    # 测试输入：连续 x 从 Real 通道接收新值，然后进入 x'=1 的 ODE。
    # 预期行为：T-In 更新当前符号但保留 ContinuousType，随后 T-ODE 成功。
    # 检查内容：输入/ODE 两个规则步骤和 ODE 入口 Gamma 快照。
    # 论文对应：输入更新当前值；连续轨迹声明仍属于外层 Gamma。
    def test_input_preserves_continuous_declaration(self) -> None:
        """通信写入连续变量不能把它降级成普通通道载荷类型。"""

        process = Sequence.of(
            InputChannel("reset", "x"),
            ODE(
                [("x", 1)],
                True,
                annotation=ODEAnnotation(delay=inf),
            ),
        )
        report = check_hcsp(
            gamma={"x": ContinuousType()},
            theta={"reset": ChannelType(BasicType.REAL)},
            configurations=[Configuration({}, process)],
            dl_checker=_approve_dl,
        )

        self.assertEqual(report.verdict, Verdict.TRUE)
        self.assertIsNotNone(report.inferred_type)
        self.assertTrue(any(item.rule == "T-In" for item in report.steps))
        ode_step = next(item for item in report.steps if item.rule == "T-ODE")
        self.assertIn(("x", "R>=0 ~> Real"), ode_step.gamma)

    # 测试输入：连续 x 不进入 ODE，只把当前值发送到 Real 通道。
    # 预期行为：表达式翻译把 x 读取为 Real，生成普通 OutputType。
    # 检查内容：总体 true 和精确输出类型，不要求变量必须在每个进程中演化。
    # 论文对应：连续变量未出现在 ODE 内时表示其当前状态值。
    def test_continuous_variable_reads_as_real_outside_ode(self) -> None:
        """连续变量的当前值可用于普通表达式、断言和通信。"""

        report = check_hcsp(
            gamma={"x": ContinuousType()},
            theta={"sample": ChannelType(BasicType.REAL)},
            configurations=[Configuration({"x": 1}, OutputChannel("sample", "x"))],
            path_condition="x == 1",
        )

        self.assertEqual(report.verdict, Verdict.TRUE)
        self.assertEqual(report.inferred_type, OutputType("sample", EndType()))

    # 测试输入：Gamma 声明联合向量 (x,y)，两个并行配置分别只读取 x 和 y。
    # 预期行为：自动 Gamma 分区把任一成员扩展成完整向量，因而检测到两个配置
    #           共享同一状态向量并拒绝推导。
    # 检查内容：false、无正式组合类型及并行共享状态诊断同时列出 x/y。
    # 论文对应：Definition 4.1 的一个连续向量不能被 T-parallel 拆给两个分量。
    def test_parallel_partition_keeps_continuous_vector_atomic(self) -> None:
        """并行自动分区不得拆散一个显式连续向量。"""

        trajectory = ContinuousType(variables=("x", "y"))
        report = check_hcsp(
            gamma={"x": trajectory, "y": trajectory},
            theta={
                "left": ChannelType(BasicType.REAL),
                "right": ChannelType(BasicType.REAL),
            },
            configurations=[
                Configuration({"x": 0}, OutputChannel("left", "x")),
                Configuration({"y": 0}, OutputChannel("right", "y")),
            ],
        )

        self.assertEqual(report.verdict, Verdict.FALSE)
        self.assertIsNone(report.inferred_type)
        self.assertTrue(
            any(
                "Parallel components share state variables" in item.message
                and "x" in item.message
                and "y" in item.message
                for item in report.diagnostics
            ),
            report.diagnostics,
        )

    # 测试输入：全局 Gamma 将 x 声明为连续，局部 Gamma 将同名 x 声明为普通 Real。
    # 预期行为：T-parallel 在进入配置推导前拒绝类别变化并返回 None。
    # 检查内容：局部/全局 Gamma 同型检查包含 continuous-vs-ordinary 差异。
    # 论文对应：T-parallel 的 Gamma 分区必须保持原环境项，而不只比较底层 sort。
    def test_local_gamma_cannot_drop_continuous_marker(self) -> None:
        """局部 Gamma 不得把连续 Real 悄悄改写成普通 Real。"""

        report = check_hcsp(
            gamma={"x": ContinuousType()},
            theta={},
            configurations=[
                Configuration(
                    {"x": 0},
                    Skip(),
                    gamma={"x": BasicType.REAL},
                )
            ],
        )

        self.assertEqual(report.verdict, Verdict.FALSE)
        self.assertIsNone(report.inferred_type)
        self.assertTrue(
            any("changes global variable types" in item.message for item in report.diagnostics)
        )

    # 测试输入：全局和局部 Gamma 都把 x 声明为连续 Real，但分别使用 x>=0
    #           和默认 true 两个不同轨迹性质。
    # 预期行为：T-parallel 把 phi 视为 ContinuousType 的正式组成部分并拒绝改写。
    # 检查内容：false、无正式类型及局部 Gamma 类型变化诊断。
    # 论文对应：Definition 4.1 的连续类型包含 phi，不能只比较底层 Real 值域。
    def test_local_gamma_cannot_change_continuous_phi(self) -> None:
        """并行局部 Gamma 不得丢弃或替换连续轨迹性质。"""

        report = check_hcsp(
            gamma={"x": ContinuousType(phi="x >= 0")},
            theta={},
            configurations=[
                Configuration(
                    {"x": 0},
                    Skip(),
                    gamma={"x": ContinuousType()},
                )
            ],
        )

        self.assertEqual(report.verdict, Verdict.FALSE)
        self.assertIsNone(report.inferred_type)
        self.assertTrue(
            any(
                "changes global variable types" in item.message
                for item in report.diagnostics
            )
        )


if __name__ == "__main__":
    unittest.main()
