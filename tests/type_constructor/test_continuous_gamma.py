r"""Definition 4.1 连续 Gamma 项及 T-ODE 使用边界测试。

测试内容
--------
1. ODE 左端的每个分量仍是普通 ``BasicType.REAL``，``ContinuousType`` 作为
   另一个 Gamma 项独立登记允许出现的演化变量集合；
2. 非空 ODE 缺少对应向量声明时拒绝，空 flow ODE 无需声明；
3. 离散赋值和通信输入只更新 Real 标量，不改写独立 ODE 向量声明；
4. 未参与 ODE 的 Real 变量不需要任何 ContinuousType 包装；
5. Gamma 只登记 process 中允许出现的完整 ODE 演化向量，ODE 左侧的真子集
   或真超集被拒绝，但成员顺序无关，隐式时钟不参加向量匹配；
6. 连续演化中恒成立的性质只来自 ODE safety，不再由 ContinuousType 重复定义；
7. 顶层/局部 Gamma 必须完整、一致地登记连续向量的所有成员。

预期行为
--------
Gamma 使用 ``x:Real`` 保存标量当前值，并用例如
``ode_x:ContinuousType(("x",))`` 的另一个键登记 ODE 集合。ContinuousType 本身
不具有表达式值；T-ODE 按成员集合匹配，方程排列不同仍视为同一个演化向量。

论文对应
--------
对应 Definition 4.1 的普通值项 ``x:B`` 与连续轨迹项
``underlined(v):R_{>=0} partial-function R^n``，以及 Table 2 [T-ODE]。
"""

from __future__ import annotations

from math import inf
import unittest

from hcsp_typechecker._internal import (
    Assert,
    Assign,
    BasicType,
    ChannelType,
    Configuration,
    ContinuousType,
    DLFormula,
    EmptyType,
    EventChoice,
    InfiniteDelayType,
    InputChannel,
    ODE,
    ODEAnnotation,
    OutputChannel,
    OutputType,
    Sequence,
    Skip,
    Verdict,
    construct_type,
)


def _approve_dl(_obligation: object) -> Verdict:
    """固定证明测试产生的非平凡 dL premise。"""

    return Verdict.TRUE


def _single_ode_gamma(name: str = "x") -> dict[str, BasicType | ContinuousType]:
    """建立一个 Real 标量及其独立单元素 ODE 向量声明。"""

    return {
        name: BasicType.REAL,
        f"ode_{name}": ContinuousType((name,)),
    }


class ContinuousGammaTests(unittest.TestCase):
    """验证独立 ODE 向量声明、Real 当前值以及 ODE 左端资格。"""

    # 测试输入：x、v、gain 都是 Real，另以 oscillator 登记 ODE 集合 {x,v}。
    # 预期行为：独立向量声明通过 T-ODE，gain 可读取但不被当成演化变量。
    # 检查内容：总体 true、正式类型存在、T-ODE 步骤显示两类 Gamma 项。
    # 论文对应：[T-ODE] 要求 v 向量连续，而 e 可读取 Gamma 中普通值变量。
    def test_explicit_continuous_vector_accepts_ordinary_real_parameter(self) -> None:
        """ODE 左端 Real 集合声明与右端普通 Real 参数可以共存。"""

        process = ODE(
            [("x", "v"), ("v", "-x * gain")],
            "x * x + v * v <= 4",
            annotation=ODEAnnotation(
                safety="x * x + v * v <= 4",
                delay=inf,
            ),
        )
        oscillator = ContinuousType(variables=("x", "v"))
        report = construct_type(
            gamma={
                "x": BasicType.REAL,
                "v": BasicType.REAL,
                "gain": BasicType.REAL,
                "oscillator": oscillator,
            },
            theta={},
            configurations=[
                Configuration({"x": 0, "v": 1, "gain": 1}, process)
            ],
            path_condition="x == 0 and v == 1 and gain == 1",
            dl_checker=_approve_dl,
        )

        self.assertEqual(report.verdict, Verdict.TRUE)
        self.assertIsNotNone(report.constructed_type)
        ode_step = next(item for item in report.steps if item.rule == "T-ODE")
        self.assertIn(("x", "Real"), ode_step.gamma)
        self.assertIn(("v", "Real"), ode_step.gamma)
        self.assertIn(("oscillator", "R>=0 ~> R^2 on (v, x)"), ode_step.gamma)
        self.assertIn(("gain", "Real"), ode_step.gamma)

    # 测试输入：Gamma 只登记单元素向量 (x)，ODE 节点 safety=x<=10。
    # 预期行为：正式 box 后置目标只含 ODE 自己的 safety，不存在 Gamma 追加性质。
    # 检查内容：捕获 DLFormula，并把 box 程序与后置公式拆开核对。
    # 论文对应：退化连续项只给出 R^n；ODE 批注是轨迹 phi 的唯一来源。
    def test_ode_annotation_is_the_only_dl_safety_goal(self) -> None:
        """Gamma 只登记演化向量，安全目标必须完全来自 ODE 批注。"""

        captured: list[object] = []

        def collect_and_approve(obligation: object) -> Verdict:
            """保存正式义务；本测试只审计公式构造，不测试外部证明器。"""

            captured.append(obligation)
            return Verdict.TRUE

        report = construct_type(
            gamma=_single_ode_gamma(),
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
            item for item in report.obligations if item.rule == "T-ODE-safety"
        )
        self.assertEqual(report.verdict, Verdict.TRUE)
        self.assertIsInstance(safety_obligation.formula, DLFormula)
        program, post = safety_obligation.formula.source.split("}]", 1)
        self.assertIn("[{", program)
        self.assertRegex(post, r"10 >= kxv\d+")
        self.assertTrue(captured)

    # 测试输入：Gamma 登记集合 {x,y}，ODE 左侧故意以 y、x 的顺序书写。
    # 预期行为：无序集合精确匹配通过，联合 safety 进入 dL box 后置目标。
    # 检查内容：总体 true、正式类型和 safety 中的常数 123。
    # 论文对应：Gamma 保存会在 process 中出现的 ODE 演化 vector。
    def test_exact_declared_ode_vector_is_accepted(self) -> None:
        """ODE 用户左侧与 Gamma 登记向量完全相同时应通过静态检查。"""

        trajectory = ContinuousType(variables=("x", "y"))
        report = construct_type(
            gamma={
                "x": BasicType.REAL,
                "y": BasicType.REAL,
                "xy_ode": trajectory,
            },
            theta={},
            configurations=[
                Configuration(
                    {"x": 0, "y": 0},
                    ODE(
                        [("y", 0), ("x", 0)],
                        True,
                        annotation=ODEAnnotation(safety="x + y >= 123", delay=1),
                    ),
                )
            ],
            dl_checker=_approve_dl,
        )

        safety = next(
            item for item in report.obligations if item.rule == "T-ODE-safety"
        )
        self.assertEqual(report.verdict, Verdict.TRUE)
        self.assertIsNotNone(report.constructed_type)
        self.assertIsInstance(safety.formula, DLFormula)
        self.assertIn("123", safety.formula.source)

    # 测试输入：Gamma 登记联合向量 {x,y}，ODE 左侧分别使用其子集和超集。
    # 预期行为：两种未登记的完整变量集合都在建立 dL 义务前被静态拒绝。
    # 检查内容：false、无正式类型、空 dL 义务和精确向量诊断。
    # 论文对应：Gamma 刻画实际允许出现的完整 ODE 演化 vector，而非分量资格集。
    def test_nonmatching_ode_vectors_are_rejected(self) -> None:
        """子集和超集都不是 Gamma 已登记的 ODE 向量集合。"""

        trajectory = ContinuousType(variables=("x", "y"))
        base_gamma = {
            "x": BasicType.REAL,
            "y": BasicType.REAL,
            "xy_ode": trajectory,
        }
        cases = (
            ("subset", [("x", 0)], base_gamma),
            (
                "superset",
                [("x", 0), ("y", 0), ("z", 0)],
                {**base_gamma, "z": BasicType.REAL},
            ),
        )
        for label, equations, gamma in cases:
            with self.subTest(label=label):
                state = {
                    name: 0
                    for name, declaration in gamma.items()
                    if isinstance(declaration, BasicType)
                }
                report = construct_type(
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
                self.assertEqual(report.verdict, Verdict.FALSE)
                self.assertIsNone(report.constructed_type)
                self.assertFalse(
                    any(item.rule.startswith("T-ODE-") for item in report.obligations)
                )
                self.assertTrue(
                    any(
                        "not declared by any ContinuousType" in item.message
                        for item in report.diagnostics
                    ),
                    report.diagnostics,
                )

    # 测试输入：Gamma 显式登记单元素向量 (x)，ODE 内还自动加入局部 t'=1。
    # 预期行为：用户向量仍精确匹配 (x)，隐式时钟不会要求出现在 Gamma 中。
    # 检查内容：总体 true、正式类型存在且没有完整向量诊断。
    # 论文对应：行政时钟服务于规则证明，不属于 process 声明的演化 vector。
    def test_implicit_clock_is_excluded_from_vector_match(self) -> None:
        """自动添加的 ODE 局部时钟不得破坏用户演化向量的精确匹配。"""

        trajectory = ContinuousType(variables=("x",))
        report = construct_type(
            gamma={"x": BasicType.REAL, "x_ode": trajectory},
            theta={},
            configurations=[
                Configuration(
                    {"x": 0},
                    ODE(
                        [("x", 0)],
                        True,
                        annotation=ODEAnnotation(safety="t >= 0", delay=1),
                    ),
                )
            ],
            dl_checker=_approve_dl,
        )

        self.assertEqual(report.verdict, Verdict.TRUE)
        self.assertIsNotNone(report.constructed_type)
        self.assertFalse(
            any("complete vector" in item.message for item in report.diagnostics)
        )

    # 测试输入：ODE 向量声明引用缺失标量 y，或引用非 Real 标量 y:Int。
    # 预期行为：环境规范化阶段拒绝缺失/错误类型的向量成员。
    # 检查内容：false、无正式类型和精确环境诊断。
    # 论文对应：一个 ODE vector 是 Gamma 中不可拆分的原子声明。
    def test_explicit_vector_registration_must_be_complete_and_consistent(self) -> None:
        """同一显式连续向量在每个 Gamma 成员下必须完整且完全一致。"""

        trajectory = ContinuousType(variables=("x", "y"))
        cases = (
            (
                {"x": BasicType.REAL, "xy_ode": trajectory},
                "missing Gamma scalar",
            ),
            (
                {
                    "x": BasicType.REAL,
                    "y": BasicType.INT,
                    "xy_ode": trajectory,
                },
                "to have BasicType.REAL",
            ),
        )
        for gamma, message in cases:
            with self.subTest(message=message):
                report = construct_type(
                    gamma=gamma,
                    theta={},
                    configurations=[Configuration({}, Skip())],
                )
                self.assertEqual(report.verdict, Verdict.FALSE)
                self.assertIsNone(report.constructed_type)
                self.assertTrue(
                    any(message in item.message for item in report.diagnostics),
                    report.diagnostics,
                )

    # 测试输入：ODE safety 错写成数值表达式 x+1，Gamma 只登记合法向量 (x)。
    # 预期行为：T-ODE 静态拒绝 safety，不调用 dL 后端，也不生成正式行为类型。
    # 检查内容：false 结论、空后端调用以及 Bool 类型错误说明。
    # 论文对应：轨迹 phi 已统一到 ODE 批注，仍必须是布尔状态公式。
    def test_ode_safety_must_be_boolean(self) -> None:
        """数值表达式不能冒充 ODE 的连续轨迹安全公式。"""

        calls: list[object] = []

        def unexpected_backend(obligation: object) -> Verdict:
            """记录静态错误后不应发生的外部证明调用。"""

            calls.append(obligation)
            return Verdict.TRUE

        report = construct_type(
            gamma=_single_ode_gamma(),
            theta={},
            configurations=[
                Configuration(
                    {"x": 0},
                    ODE(
                        [("x", 0)],
                        True,
                        annotation=ODEAnnotation(safety="x + 1", delay=1),
                    ),
                )
            ],
            path_condition="x == 0",
            dl_checker=unexpected_backend,
        )

        self.assertEqual(report.verdict, Verdict.FALSE)
        self.assertIsNone(report.constructed_type)
        self.assertEqual(calls, [])
        self.assertTrue(
            any("Bool" in item.message for item in report.diagnostics),
            report.diagnostics,
        )

    # 测试输入：ODE safety=x>=0，并可经 tick! 中断后立即执行 assert(x>=0)。
    # 预期行为：通信后继路径继承已经证明的 ODE safety 在中断点的实例。
    # 检查内容：总体 true、正式输出类型以及已证明的 T-Assert 义务。
    # 论文对应：ODE 自身 phi 描述轨迹状态空间，在任意中断点仍成立。
    def test_ode_safety_is_available_at_interrupt(self) -> None:
        """已证明的 ODE safety 必须进入通信后继上下文。"""

        process = ODE(
            [("x", 0)],
            True,
            EventChoice.of(
                (OutputChannel("tick", 0), Assert("x >= 0")),
            ),
            annotation=ODEAnnotation(safety="x >= 0", delay=inf),
        )
        report = construct_type(
            gamma=_single_ode_gamma(),
            theta={"tick": ChannelType(BasicType.INT)},
            configurations=[Configuration({"x": 0}, process)],
            path_condition="x == 0",
            dl_checker=_approve_dl,
        )

        self.assertEqual(report.verdict, Verdict.TRUE)
        self.assertEqual(
            report.constructed_type,
            InfiniteDelayType(OutputType("tick", EmptyType())),
        )
        assert_obligation = next(
            item for item in report.obligations if item.rule == "T-Assert"
        )
        self.assertEqual(assert_obligation.verdict, Verdict.TRUE)

    # 测试输入：x 正确声明为 BasicType.REAL，但 Gamma 没有登记向量 {x}。
    # 预期行为：T-ODE 静态失败、无正式类型，且 dL 后端不会被调用。
    # 检查内容：缺失 ContinuousType 向量声明诊断和空 ODE 证明义务集合。
    # 论文对应：标量 x:Real 与允许出现的 ODE vector 是两个独立 Gamma 项。
    def test_real_ode_lvalue_requires_vector_declaration(self) -> None:
        """Real 是 ODE 分量值类型，但非空 ODE 仍需独立向量声明。"""

        calls: list[object] = []

        def backend(obligation: object) -> Verdict:
            """记录不应发生的 dL 后端调用。"""

            calls.append(obligation)
            return Verdict.TRUE

        report = construct_type(
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
        self.assertIsNone(report.constructed_type)
        self.assertEqual(calls, [])
        self.assertFalse(
            any(item.rule.startswith("T-ODE-") for item in report.obligations)
        )
        self.assertTrue(
            any("not declared by any ContinuousType" in item.message for item in report.diagnostics)
        )

    # 测试输入：Real 标量 x 先执行离散赋值，再进入 Gamma 已登记的 {x} ODE。
    # 预期行为：赋值只更新 x 当前值，独立的 ode_x 向量声明保持不变。
    # 检查内容：T-Assign/T-ODE、总体 true，以及 ODE 步骤中的两类 Gamma 项。
    # 论文对应：值变量赋值不改变 process 中允许出现的 ODE vector 集合。
    def test_assignment_preserves_continuous_declaration(self) -> None:
        """离散重置 Real 分量后，独立向量声明仍允许对应 ODE。"""

        process = Sequence.of(
            Assign("x", 0),
            ODE(
                [("x", 1)],
                True,
                annotation=ODEAnnotation(delay=inf),
            ),
        )
        report = construct_type(
            gamma=_single_ode_gamma(),
            theta={},
            configurations=[Configuration({"x": 2}, process)],
            dl_checker=_approve_dl,
        )

        self.assertEqual(report.verdict, Verdict.TRUE)
        self.assertIsNotNone(report.constructed_type)
        self.assertTrue(any(item.rule == "T-Assign" for item in report.steps))
        ode_step = next(item for item in report.steps if item.rule == "T-ODE")
        self.assertIn(("x", "Real"), ode_step.gamma)
        self.assertIn(("ode_x", "R>=0 ~> Real on (x)"), ode_step.gamma)

    # 测试输入：Real 标量 x 从通道接收新值，然后进入已登记的 {x} ODE。
    # 预期行为：T-In 更新 x，且不会覆盖独立 ContinuousType 声明。
    # 检查内容：输入/ODE 两个规则步骤和 ODE 入口 Gamma 快照。
    # 论文对应：输入更新当前值；连续轨迹声明仍属于外层 Gamma。
    def test_input_preserves_continuous_declaration(self) -> None:
        """通信写入 Real 分量不能覆盖独立 ODE 向量声明。"""

        process = Sequence.of(
            InputChannel("reset", "x"),
            ODE(
                [("x", 1)],
                True,
                annotation=ODEAnnotation(delay=inf),
            ),
        )
        report = construct_type(
            gamma=_single_ode_gamma(),
            theta={"reset": ChannelType(BasicType.REAL)},
            configurations=[Configuration({}, process)],
            dl_checker=_approve_dl,
        )

        self.assertEqual(report.verdict, Verdict.TRUE)
        self.assertIsNotNone(report.constructed_type)
        self.assertTrue(any(item.rule == "T-In" for item in report.steps))
        ode_step = next(item for item in report.steps if item.rule == "T-ODE")
        self.assertIn(("x", "Real"), ode_step.gamma)
        self.assertIn(("ode_x", "R>=0 ~> Real on (x)"), ode_step.gamma)

    # 测试输入：普通 Real 变量 x 不进入任何 ODE，只把当前值发送到通道。
    # 预期行为：无需 ContinuousType 声明即可生成普通 OutputType。
    # 检查内容：总体 true 和精确输出类型。
    # 论文对应：只对实际可能出现的 ODE vector 建连续声明，普通 Real 保持普通值。
    def test_real_variable_needs_no_vector_outside_ode(self) -> None:
        """未参与 ODE 的 Real 变量不应被包装成所谓连续值类型。"""

        report = construct_type(
            gamma={"x": BasicType.REAL},
            theta={"sample": ChannelType(BasicType.REAL)},
            configurations=[Configuration({"x": 1}, OutputChannel("sample", "x"))],
            path_condition="x == 1",
        )

        self.assertEqual(report.verdict, Verdict.TRUE)
        self.assertEqual(
            report.constructed_type,
            InfiniteDelayType(OutputType("sample", EmptyType())),
        )

    # 测试输入：把独立声明键 ode_x 分别用作 state、赋值目标、输入目标和表达式。
    # 预期行为：四种用法都失败；只有声明成员 x 才具有 Real 当前值。
    # 检查内容：无正式类型，并包含“不是标量”或“未声明值变量”的定位诊断。
    # 论文对应：underlined(v) 是 ODE vector 描述，不是一个可读写的 Real 变量。
    def test_ode_vector_declaration_name_has_no_scalar_value(self) -> None:
        """ContinuousType 所在的 Gamma 键不能冒充标量程序变量。"""

        gamma = _single_ode_gamma()
        cases = (
            (
                "state",
                {},
                Configuration({"ode_x": 0}, Skip()),
                "not declared in the local Gamma",
            ),
            (
                "assignment",
                {},
                Configuration({}, Assign("ode_x", 0)),
                "names an ODE vector declaration",
            ),
            (
                "input",
                {"reset": ChannelType(BasicType.REAL)},
                Configuration({}, InputChannel("reset", "ode_x")),
                "names an ODE vector declaration",
            ),
            (
                "expression",
                {"sample": ChannelType(BasicType.REAL)},
                Configuration({}, OutputChannel("sample", "ode_x")),
                "Unbound variable",
            ),
        )
        for name, theta, configuration, message in cases:
            with self.subTest(name=name):
                report = construct_type(
                    gamma=gamma,
                    theta=theta,
                    configurations=[configuration],
                )
                self.assertEqual(report.verdict, Verdict.FALSE)
                self.assertIsNone(report.constructed_type)
                self.assertTrue(
                    any(message in item.message for item in report.diagnostics),
                    report.diagnostics,
                )

    # 测试输入：两个并行配置分别读取普通 Real x 和 y，process 中没有 ODE。
    # 预期行为：自动 Gamma 分区按普通标量拆分，不凭空制造联合连续向量。
    # 检查内容：总体 true 且产生正式并行类型。
    # 论文对应：ContinuousType 只描述实际可能出现的 ODE，不给普通 Real 分组。
    def test_parallel_real_values_are_not_grouped_without_ode(self) -> None:
        """没有 ODE 时，多个 Real 标量不会被连续向量语义强行绑定。"""

        report = construct_type(
            gamma={"x": BasicType.REAL, "y": BasicType.REAL},
            theta={
                "left": ChannelType(BasicType.REAL),
                "right": ChannelType(BasicType.REAL),
            },
            configurations=[
                Configuration({"x": 0}, OutputChannel("left", "x")),
                Configuration({"y": 0}, OutputChannel("right", "y")),
            ],
        )

        self.assertEqual(report.verdict, Verdict.TRUE)
        self.assertIsNotNone(report.constructed_type)

    # 测试输入：全局 Gamma 含 x:Real 和 ode_x 向量声明，局部 Gamma 只保留 x。
    # 预期行为：局部 Gamma 未覆盖独立向量声明，T-parallel 拒绝该分区。
    # 检查内容：false、无正式类型和全局 Gamma 覆盖诊断。
    # 论文对应：ODE vector 是独立 Gamma 项，不能通过保留成员 Real 来冒充。
    def test_local_gamma_cannot_drop_ode_vector_declaration(self) -> None:
        """局部 Gamma 必须显式保留归属本配置的 ODE 向量声明。"""

        report = construct_type(
            gamma=_single_ode_gamma(),
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
        self.assertIsNone(report.constructed_type)
        self.assertTrue(
            any("do not cover the global Gamma" in item.message for item in report.diagnostics)
        )

    # 测试输入：全局/局部 Gamma 分别以 (x,y) 和 (y,x) 声明同一 ODE 集合。
    # 预期行为：成员顺序无语义差异，局部 Gamma 与全局 Gamma 相等并通过。
    # 检查内容：true、正式类型存在且没有局部类型变化诊断。
    # 论文对应：ODE 是联立方程集合，源代码排列不改变演化 vector。
    def test_local_gamma_accepts_reordered_ode_vector(self) -> None:
        """局部 Gamma 可以用不同顺序书写同一个 ODE 成员集合。"""

        trajectory = ContinuousType(variables=("x", "y"))
        report = construct_type(
            gamma={
                "x": BasicType.REAL,
                "y": BasicType.REAL,
                "xy_ode": trajectory,
            },
            theta={},
            configurations=[
                Configuration(
                    {"x": 0, "y": 0},
                    Skip(),
                    gamma={
                        "x": BasicType.REAL,
                        "y": BasicType.REAL,
                        "xy_ode": ContinuousType(("y", "x")),
                    },
                )
            ],
        )

        self.assertEqual(report.verdict, Verdict.TRUE)
        self.assertIsNotNone(report.constructed_type)
        self.assertFalse(
            any("changes global variable types" in item.message for item in report.diagnostics)
        )


if __name__ == "__main__":
    unittest.main()
