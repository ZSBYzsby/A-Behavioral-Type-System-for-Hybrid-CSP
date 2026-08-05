r"""Section 4.2/4.3 带批注 HCSP 的构造与类型转换测试。

本文件专门覆盖原始 Section 2.1 语法之外的两类输入信息：

* ODE 的安全性质 ``phi``、外部延迟 ``d`` 与自动局部时钟；
* ``mu`` 绑定的过程变量 ``X`` 的边界不变量 ``phi``。

测试既检查批注对象的规范化与拒绝条件，也检查批注确实进入证明义务、路径
条件和最终行为类型，并包含 ODE 与递归组合的场景。

测试内容
--------
1. safety/invariant 默认值、强类型字段、唯一批注路径和自动局部时钟。
2. 必填 delay 的精确有理数、正无穷规范化与全部非法边界。
3. 按 ODE 形状生成 safety/domain/boundary 义务和规范化时延类型节点。
4. 递归不变量在 T-mu 入口、T-X 回边的成立与失败路径。
5. ODE 批注和递归批注在同一循环中的组合推导。

论文对应
--------
对应 Section 4.2/4.3 的带批注 ODE、过程变量边界不变量和 Table 2 中
T-ODE、T-\unrhd、T-mu、T-X 等规则；delay 还对应 Remark 4.1。
"""

from __future__ import annotations

from dataclasses import fields
from decimal import Decimal
from fractions import Fraction
import math
import unittest

from hcsp_typechecker import (
    Assign,
    BasicType,
    BottomType,
    ChannelType,
    Configuration,
    ContinuousType,
    EndType,
    Expr,
    InputChannel,
    Literal,
    Mu,
    MuType,
    ODE,
    ODEAnnotation,
    ODELocalClock,
    OutputChannel,
    OutputType,
    PureDelayType,
    RecursionAnnotation,
    Sequence,
    Skip,
    TypeVar,
    Var,
    Verdict,
    check_hcsp,
    types_equivalent,
)


def _approve_dl(_obligation: object) -> Verdict:
    """模拟已经验证全部动态逻辑义务的可信后端。"""

    return Verdict.TRUE


class AnnotationAstTests(unittest.TestCase):
    """检查批注是强类型字段，而不是额外 HCSP 语法节点。"""

    # 测试输入：safety="x <= limit"、delay=2 的 ODEAnnotation。
    # 预期行为：safety/delay 成为 Expr，有限时延精确保存为 Fraction(2)。
    # 检查内容：同时核对 safety 的变量收集结果。
    # 论文对应：Section 4.3 给 ODE 附加安全性质 phi 和外部时延 d。
    def test_ode_annotation_normalizes_safety_and_delay(self) -> None:
        """字符串安全式和有限延迟必须立即转成精确项目表达式。"""

        annotation = ODEAnnotation(safety="x <= limit", delay=2)
        self.assertIsInstance(annotation.safety, Expr)
        self.assertIsInstance(annotation.delay, Expr)
        self.assertEqual(annotation.delay, Literal(Fraction(2)))
        self.assertEqual(annotation.get_vars(), {"x", "limit"})

    # 测试输入：只提供 delay=1，省略 safety。
    # 预期行为：safety 字段明确规范化为 Literal(True)。
    # 检查内容：避免用 None 表示论文中的恒真省略约定。
    # 论文对应：Section 4.3 规定省略批注公式时含义为 true。
    def test_omitted_safety_means_true(self) -> None:
        """论文约定省略安全性质等价于恒真，而不是缺失值。"""

        annotation = ODEAnnotation(delay=1)
        self.assertEqual(annotation.safety, Literal(True))

    # 测试输入：缺少 delay 的批注，以及完全缺失 annotation 的 ODE。
    # 预期行为：两种输入都在 AST 构造阶段抛出明确 ValueError。
    # 检查内容：分别覆盖批注内部字段缺失和整个批注对象缺失。
    # 论文对应：项目落实 Section 4.3/Remark 4.1 时要求每个 ODE 给出 d。
    def test_delay_and_ode_annotation_are_both_required(self) -> None:
        """缺少 d 或整个 ODE 批注必须在 AST 构造边界立即报错。"""

        with self.assertRaisesRegex(ValueError, "explicit delay"):
            ODEAnnotation()
        with self.assertRaisesRegex(ValueError, "Every ODE requires"):
            ODE([("x", 1)], True)

    # 测试输入：int、float、Decimal、Fraction 和常量有理算式六种 d。
    # 预期行为：全部精确规范化为期望 Fraction Literal。
    # 检查内容：逐项覆盖小数、除法、负指数而不引入浮点近似。
    # 论文对应：类型中的有限 delay(d) 需要稳定的非负有理常量。
    def test_finite_rational_forms_are_normalized_exactly(self) -> None:
        """整数、十进制、Fraction 和常量算式都应归一为精确 Fraction。"""

        examples = (
            (3, Fraction(3)),
            (0.5, Fraction(1, 2)),
            (Decimal("0.125"), Fraction(1, 8)),
            (Fraction(2, 3), Fraction(2, 3)),
            ("1 / 4 + 1 / 4", Fraction(1, 2)),
            ("2 ** -2", Fraction(1, 4)),
        )
        for source, expected in examples:
            with self.subTest(source=source):
                annotation = ODEAnnotation(delay=source)
                self.assertEqual(annotation.delay, Literal(expected))

    # 测试输入：float 和 Decimal 两种正无穷。
    # 预期行为：两者统一保存为 math.inf。
    # 检查内容：确认无限等待批注不依赖调用方的数值对象类型。
    # 论文对应：连续类型允许 ``d = infinity`` 的纯通信等待情况。
    def test_positive_infinity_is_a_valid_delay(self) -> None:
        """浮点或 Decimal 正无穷都统一保存为 math.inf。"""

        for value in (math.inf, Decimal("Infinity")):
            with self.subTest(value=value):
                annotation = ODEAnnotation(delay=value)
                self.assertEqual(annotation.delay, math.inf)

    # 测试输入：负数、变量、无理函数、Bool、NaN、负无穷、除零等 d。
    # 预期行为：每个非法时延都由 ODEAnnotation 抛出 ValueError。
    # 检查内容：覆盖符号性、符号方向、非有理性和未定义算术边界。
    # 论文对应：项目只接受 Remark 4.1 所需的非负有理数或正无穷。
    def test_invalid_delays_are_rejected_at_construction(self) -> None:
        """负数、符号量、非有理式、Bool、NaN 和负无穷都必须立即失败。"""

        invalid_values = (
            -1,
            "-1 / 2",
            "d",
            "sqrt(2)",
            True,
            math.nan,
            -math.inf,
            Decimal("NaN"),
            Decimal("-Infinity"),
            "1 / 0",
            "4 ** 0.5",
        )
        for value in invalid_values:
            with self.subTest(value=value):
                with self.assertRaises(ValueError):
                    ODEAnnotation(delay=value)

    # 测试输入：正确/互换的 ODEAnnotation 与 RecursionAnnotation。
    # 预期行为：正确对象保持身份；互换类型的两个调用都被拒绝。
    # 检查内容：防止 safety/delay 和递归 invariant 混入错误节点。
    # 论文对应：Section 4.3 分别给 ODE 与 X_phi 定义不同批注内容。
    def test_ode_and_mu_hold_dedicated_annotation_objects(self) -> None:
        """原 HCSP 节点只接受各自对应的批注类型。"""

        ode_annotation = ODEAnnotation(safety=True, delay=1)
        recursion_annotation = RecursionAnnotation("x >= 0")
        ode = ODE([("x", 1)], "x < 1", annotation=ode_annotation)
        recursion = Mu("X", Skip(), annotation=recursion_annotation)
        self.assertIs(ode.annotation, ode_annotation)
        self.assertIs(recursion.annotation, recursion_annotation)
        with self.assertRaises(TypeError):
            ODE([("x", 1)], True, annotation=recursion_annotation)  # type: ignore[arg-type]
        with self.assertRaises(TypeError):
            Mu("X", Skip(), annotation=ode_annotation)  # type: ignore[arg-type]

    # 测试输入：省略 RecursionAnnotation 的 ``Mu("X", Skip())``。
    # 预期行为：自动得到 invariant=Literal(True)。
    # 检查内容：核对默认对象已经规范化，而不是在检查器中临时猜测。
    # 论文对应：Section 4.3 对省略递归边界不变量采用 true 约定。
    def test_recursion_annotation_omission_means_true(self) -> None:
        """递归不变量省略时也按论文约定解释为 true。"""

        recursion = Mu("X", Skip())
        self.assertEqual(recursion.annotation.invariant, Literal(True))

    # 测试输入：当前 ODE dataclass 的完整字段定义。
    # 预期行为：annotation 仍是唯一批注入口，local_clock 是独立的语义字段。
    # 检查内容：正向比较当前 ODE 的完整字段集合，防止隐藏时钟混进批注。
    # 论文对应：Section 2.1 的 ODE 主体、Section 4.3 的 phi/d 批注以及
    #           Table 2 前提中的新鲜局部 t 分别有唯一位置。
    def test_ode_has_one_annotation_storage_path(self) -> None:
        """ODE 的批注与自动局部时钟应位于不同的唯一字段。"""

        self.assertEqual(
            tuple(field.name for field in fields(ODE)),
            (
                "eqs",
                "constraint",
                "interrupts",
                "annotation",
                "local_clock",
                "local_clock_deadline",
            ),
        )
        clock_field = next(field for field in fields(ODE) if field.name == "local_clock")
        deadline_field = next(
            field for field in fields(ODE) if field.name == "local_clock_deadline"
        )
        self.assertFalse(clock_field.init)
        self.assertFalse(clock_field.compare)
        self.assertFalse(deadline_field.init)
        self.assertTrue(deadline_field.compare)

    # 测试输入：构造两个没有用户方程的 ODE，不传入任何时钟参数。
    # 预期行为：两者自动获得不同 ODELocalClock，且名称/初值/导数固定为 t/0/1。
    # 检查内容：同时确认 ODE 构造器不接受用户注入 local_clock 或 deadline。
    # 论文对应：Table 2 的 ODE 前提要求每个 ODE 使用新鲜局部时钟 t。
    def test_every_ode_owns_a_fresh_fixed_local_clock(self) -> None:
        """ODE 自动时钟应独立、不可配置，并固定从零以单位速率演化。"""

        first = ODE([], True, annotation=ODEAnnotation(delay=1))
        second = ODE([], True, annotation=ODEAnnotation(delay=2))

        self.assertIsInstance(first.local_clock, ODELocalClock)
        self.assertIsNot(first.local_clock, second.local_clock)
        self.assertNotEqual(first.local_clock, second.local_clock)
        self.assertEqual(first.local_clock.name, "t")
        self.assertEqual(first.local_clock.initial_value, Literal(Fraction(0)))
        self.assertEqual(first.local_clock.derivative, Literal(Fraction(1)))
        self.assertIsNone(first.local_clock_deadline)
        with self.assertRaises(TypeError):
            ODE(  # type: ignore[call-arg]
                [],
                True,
                annotation=ODEAnnotation(delay=1),
                local_clock=ODELocalClock(),
            )
        with self.assertRaises(TypeError):
            ODE(  # type: ignore[call-arg]
                [],
                True,
                annotation=ODEAnnotation(delay=1),
                local_clock_deadline=Literal(1),
            )


class ODEAnnotationTypingTests(unittest.TestCase):
    """检查 safety/delay 如何生成证明义务与互斥的规范时延类型。"""

    # 测试输入：静止 ODE、safety=true、delay=infinity，且不配置 dL 后端。
    # 预期行为：总结果为 true，并记录一条本地通过的 safety 义务。
    # 检查内容：核对恒真安全式不被错误降级为 unknown。
    # 论文对应：T-ODE 的 phi=true 特例及无限延迟纯通信类型。
    def test_true_safety_is_accepted_without_a_dl_backend(self) -> None:
        """安全性质 true 应本地判真，不能因为没有外部证明器变成 unknown。"""

        process = ODE(
            [("x", 0)],
            True,
            annotation=ODEAnnotation(safety=True, delay=math.inf),
        )
        report = check_hcsp(
            gamma={"x": BasicType.REAL, "ode_x": ContinuousType(("x",))},
            theta={},
            configurations=[Configuration({"x": 0}, process)],
        )
        self.assertEqual(report.verdict, Verdict.TRUE)
        self.assertIsInstance(report.inferred_type, EndType)
        safety_obligations = [
            item for item in report.obligations if item.rule == "T-ODE-safety"
        ]
        self.assertEqual(len(safety_obligations), 1)
        self.assertEqual(safety_obligations[0].verdict, Verdict.TRUE)

    # 测试输入：静止 ODE，批注明确给出 delay=3。
    # 预期行为：可信 dL 后端批准域前提后，得到 PureDelayType(3, bottom)。
    # 检查内容：比较完整类型；无自然后继时只登记 domain，不登记 boundary。
    # 论文对应：Section 4.3 纯通信中断形式的外部时延批注。
    def test_delay_annotation_appears_in_the_inferred_type(self) -> None:
        """有限 d 必须原样形成 delay(d)，而不是由检查器重新计算。"""

        process = ODE(
            [("x", 0)],
            True,
            annotation=ODEAnnotation(delay=3),
        )
        report = check_hcsp(
            gamma={"x": BasicType.REAL, "ode_x": ContinuousType(("x",))},
            theta={},
            configurations=[Configuration({"x": 0}, process)],
            dl_checker=_approve_dl,
        )
        expected = PureDelayType(3, BottomType())
        self.assertEqual(report.verdict, Verdict.TRUE)
        self.assertTrue(types_equivalent(report.inferred_type, expected))
        rules = {item.rule for item in report.obligations}
        self.assertIn("T-ODE-domain", rules)
        self.assertNotIn("T-ODE-boundary", rules)

    # 测试输入：x'=1、域 x<=10、安全式 x<=8、delay=2。
    # 预期行为：可信 mock 后端批准后结果为 true。
    # 检查内容：报告必须同时含 T-ODE-safety 和 T-ODE-domain 义务。
    # 论文对应：T-ODE 与带安全性质的连续演化规则需要 dL 验证。
    def test_nontrivial_safety_generates_a_dl_obligation(self) -> None:
        """非恒真安全性质必须交给 dL 后端验证。"""

        process = ODE(
            [("x", 1)],
            "x <= 10",
            annotation=ODEAnnotation(safety="x <= 8", delay=2),
        )
        report = check_hcsp(
            gamma={"x": BasicType.REAL, "ode_x": ContinuousType(("x",))},
            theta={},
            configurations=[Configuration({"x": 0}, process)],
            path_condition="x == 0",
            dl_checker=_approve_dl,
        )
        self.assertEqual(report.verdict, Verdict.TRUE)
        rules = {item.rule for item in report.obligations}
        self.assertIn("T-ODE-safety", rules)
        self.assertIn("T-ODE-domain", rules)

    # 测试输入：delay 源码 ``1 / 2`` 的静止 ODE。
    # 预期行为：PureDelayType.duration 为精确 Fraction(1,2)，不混入 Expr。
    # 检查内容：确认合法 d 不产生冗余 T-ODE-delay，并保留精确类型字段。
    # 论文对应：Remark 4.1 的外部 d 直接进入行为类型。
    def test_fractional_delay_appears_exactly_in_the_inferred_type(self) -> None:
        """有限常量算式应以精确有理数进入 PureDelayType。"""

        process = ODE(
            [("x", 0)],
            True,
            annotation=ODEAnnotation(safety=True, delay="1 / 2"),
        )
        report = check_hcsp(
            gamma={"x": BasicType.REAL, "ode_x": ContinuousType(("x",))},
            theta={},
            configurations=[Configuration({"x": 0}, process)],
            dl_checker=_approve_dl,
        )
        self.assertEqual(report.verdict, Verdict.TRUE)
        self.assertIsInstance(report.inferred_type, PureDelayType)
        self.assertEqual(
            report.inferred_type.duration,
            Fraction(1, 2),
        )
        self.assertFalse(
            any(item.rule == "T-ODE-delay" for item in report.obligations)
        )

    # 测试输入：有限时延 ODE 后顺序连接具有 Int 载荷的 ``done!0``。
    # 预期行为：无通信分支使结果成为 PureDelayType，continuation 是 done!。
    # 检查内容：比较 duration 和 OutputType continuation 的完整结构。
    # 论文对应：新版 Table 2 带自然结束后继的第二条 T-\unrhd 规则。
    def test_outer_sequence_becomes_the_ode_fallback(self) -> None:
        """ODE; P 使用带 fallback 的规则，并把 d 写入该类型。"""

        process = Sequence.of(
            ODE(
                [("x", 1)],
                "x < 1",
                annotation=ODEAnnotation(safety=True, delay=1),
            ),
            OutputChannel("done", 0),
        )
        report = check_hcsp(
            gamma={"x": BasicType.REAL, "ode_x": ContinuousType(("x",))},
            theta={"done": ChannelType(BasicType.INT)},
            configurations=[Configuration({"x": 0}, process)],
            path_condition="x == 0",
            dl_checker=_approve_dl,
        )
        expected = PureDelayType(
            1,
            OutputType("done", EndType()),
        )
        self.assertEqual(report.verdict, Verdict.TRUE)
        self.assertTrue(types_equivalent(report.inferred_type, expected))

    # 测试输入：delay=infinity 的无中断 ODE 后仍顺序连接 Skip。
    # 预期行为：结果为 true，超时后继 Skip 被设置为 bottom，最终 A 为 0。
    # 检查内容：不生成有限边界义务，也不把不可达 tail 保存在 timeout fallback。
    # 论文对应：A := delay(infinity) \unrhd A \triangleright bottom；本例 A=0。
    def test_infinite_delay_discards_sequential_timeout_fallback(self) -> None:
        """无限时延后的顺序项不能成为一个永远不会触发的超时分支。"""

        process = Sequence.of(
            ODE(
                [("x", 0)],
                True,
                annotation=ODEAnnotation(delay=math.inf),
            ),
            Skip(),
        )
        report = check_hcsp(
            gamma={"x": BasicType.REAL, "ode_x": ContinuousType(("x",))},
            theta={},
            configurations=[Configuration({"x": 0}, process)],
            dl_checker=_approve_dl,
        )
        self.assertEqual(report.verdict, Verdict.TRUE)
        self.assertEqual(report.inferred_type, EndType())
        self.assertFalse(
            any(item.rule == "T-ODE-boundary" for item in report.obligations)
        )


class RecursionAnnotationTypingTests(unittest.TestCase):
    """检查过程变量边界不变量的入口与回边义务。"""

    # 测试输入：tick 输出后 x:=x+1 并回到 X，invariant 为 x>=0。
    # 预期行为：结果 true，类型 alpha 等价于 mu T.tick!.T。
    # 检查内容：报告必须同时出现通过的 T-mu 入口和 T-X 回边义务。
    # 论文对应：Section 4.3 的边界不变量及 Table 2 T-mu/T-X。
    def test_invariant_holds_at_entry_and_after_one_unfolding(self) -> None:
        """T-mu 与 T-X 应分别验证入口和递归回边。"""

        process = Mu(
            "X",
            Sequence.of(
                OutputChannel("tick", 0),
                Assign("x", "x + 1"),
                Var("X"),
            ),
            annotation=RecursionAnnotation("x >= 0"),
        )
        report = check_hcsp(
            gamma={"x": BasicType.INT},
            theta={"tick": ChannelType(BasicType.INT)},
            configurations=[Configuration({"x": 0}, process)],
            path_condition="x >= 0",
        )
        self.assertEqual(report.verdict, Verdict.TRUE)
        self.assertTrue(
            types_equivalent(
                report.inferred_type,
                MuType("T", OutputType("tick", TypeVar("T"))),
            )
        )
        rules = {item.rule for item in report.obligations}
        self.assertIn("T-mu", rules)
        self.assertIn("T-X", rules)

    # 测试输入：tick 后执行 x:=-1，再回到要求 x>=0 的 X。
    # 预期行为：总结果 false，唯一 T-X 义务也为 false。
    # 检查内容：隔离递归出口无法重新建立边界不变量的失败。
    # 论文对应：T-X 要求每次递归回边重新满足 X_phi 的 phi。
    def test_invariant_violation_at_recursion_boundary_is_rejected(self) -> None:
        """递归体若不能重新建立 phi，T-X 必须产生反例。"""

        process = Mu(
            "X",
            Sequence.of(
                OutputChannel("tick", 0),
                Assign("x", -1),
                Var("X"),
            ),
            annotation=RecursionAnnotation("x >= 0"),
        )
        report = check_hcsp(
            gamma={"x": BasicType.INT},
            theta={"tick": ChannelType(BasicType.INT)},
            configurations=[Configuration({"x": 0}, process)],
            path_condition="x >= 0",
        )
        self.assertEqual(report.verdict, Verdict.FALSE)
        boundary = [item for item in report.obligations if item.rule == "T-X"]
        self.assertEqual(len(boundary), 1)
        self.assertEqual(boundary[0].verdict, Verdict.FALSE)

    # 测试输入：带 safety/delay 的 ODE、tick 输出和递归 X 的组合循环。
    # 预期行为：可信 dL 后端下整体结果为 true。
    # 检查内容：同时要求 T-mu、T-X、ODE-safety、ODE-boundary 四类义务。
    # 论文对应：Section 4.3 两种批注在同一 HCSP 进程中的组合推导。
    def test_ode_and_recursion_annotations_work_together(self) -> None:
        """组合场景同时使用 ODE safety/d 与 X 的边界不变量。"""

        process = Mu(
            "X",
            Sequence.of(
                ODE(
                    [("x", 0)],
                    "x < 1",
                    annotation=ODEAnnotation(safety="x <= 1", delay=1),
                ),
                OutputChannel("tick", 0),
                Var("X"),
            ),
            annotation=RecursionAnnotation("x <= 1"),
        )
        report = check_hcsp(
            gamma={"x": BasicType.REAL, "ode_x": ContinuousType(("x",))},
            theta={"tick": ChannelType(BasicType.INT)},
            configurations=[Configuration({"x": 0}, process)],
            path_condition="x <= 1",
            dl_checker=_approve_dl,
        )
        self.assertEqual(report.verdict, Verdict.TRUE)
        rules = {item.rule for item in report.obligations}
        self.assertTrue(
            {"T-mu", "T-X", "T-ODE-safety", "T-ODE-boundary"} <= rules
        )


if __name__ == "__main__":
    unittest.main()
