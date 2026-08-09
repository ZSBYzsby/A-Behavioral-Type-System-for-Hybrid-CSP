"""HCSP 用户输入前端的 ODE、顶层系统与并行 lowering 测试。

测试内容
--------
1. 必填 flow/domain/delay、可选 safety/interrupt 及其缺省 AST。
2. dot 方程、精确有理/无穷 delay、事件反应和 ODE 局部时钟作用域。
3. ODE clause、方程、时延和 interrupt 的语法/良构负例。
4. 单块源到 Process、多块源到规范 Parallel 的转换及资源分离诊断。

论文对应
--------
ODE 案例覆盖 Section 2.1 连续演化和 Section 4.3 的安全性质、delay 批注；
顶层案例覆盖系统范畴 S 的顺序进程与并行组合以及 Assumption 2.1。
"""

from __future__ import annotations

from fractions import Fraction
from math import inf
import unittest

from hcsp_typechecker._internal import (
    Assign,
    CompareExpr,
    EmptyEvent,
    EventChoice,
    HCSPInputError,
    InputChannel,
    Literal,
    ODE,
    ODEAnnotation,
    OutputChannel,
    Parallel,
    Sequence,
    Skip,
    UnaryExpr,
    Variable,
    parse_hcsp,
)


class ODEInputTests(unittest.TestCase):
    """验证 ODE 具名配置、批注缺省和事件反应的解析。"""

    # 测试输入：两个 dot 方程、domain 和 delay 组成的最简普通 ODE。
    # 预期行为：方程保持顺序，safety 补 true，interrupt 补 EmptyEvent。
    # 检查内容：精确比较完整 ODE、ODEAnnotation 和表达式子树。
    # 论文对应：覆盖连续演化以及省略安全性质等价于 true 的约定。
    def test_minimal_ode_applies_optional_defaults(self) -> None:
        """省略 safety 和 interrupt 的 ODE 应形成唯一默认 AST。"""

        source = (
            "{{ode(flow(dot x = v, dot v = -x), "
            "domain(t <= 1), delay(1))}}"
        )
        expected = ODE(
            (
                ("x", Variable("v")),
                ("v", UnaryExpr("-", Variable("x"))),
            ),
            CompareExpr((Variable("t"), Literal(1)), ("<=",)),
            EmptyEvent(),
            annotation=ODEAnnotation(safety=True, delay=1),
        )
        self.assertEqual(parse_hcsp(source), expected)

    # 测试输入：显式 safety、1/2 delay 以及输入/输出两个中断分支。
    # 预期行为：构造精确批注和按书写顺序右结合的 EventChoice。
    # 检查内容：比较通信、各自 continuation 和最终 EmptyEvent 余项。
    # 论文对应：覆盖带安全批注连续演化及 InputChoice/OutputChoice 事件 E。
    def test_full_ode_with_safety_and_interrupts(self) -> None:
        """完整 ODE 应保留安全性质、精确时长及全部事件分支。"""

        source = """{{
            ode(
                flow(dot x = v),
                domain(t <= 1),
                safety(x <= 2),
                delay(1 / 2),
                interrupt(
                    on reset?(new_x) {x := new_x},
                    on report!(x) {skip}
                )
            )
        }}"""
        interrupts = EventChoice.of(
            (InputChannel("reset", "new_x"), Assign("x", "new_x")),
            (OutputChannel("report", "x"), Skip()),
        )
        expected = ODE(
            (("x", Variable("v")),),
            CompareExpr((Variable("t"), Literal(1)), ("<=",)),
            interrupts,
            annotation=ODEAnnotation(
                safety=CompareExpr((Variable("x"), Literal(2)), ("<=",)),
                delay=Fraction(1, 2),
            ),
        )
        self.assertEqual(parse_hcsp(source), expected)

    # 测试输入：flow()、有理常量组合 delay 和 delay(inf) 两个普通 ODE。
    # 预期行为：空用户方程合法；有限值化为 Fraction，inf 保持正无穷。
    # 检查内容：直接核对 eqs 和 annotation.delay 的内部规范值。
    # 论文对应：覆盖无用户连续变量及 Remark 4.1 的有限/无限时延批注。
    def test_empty_flow_and_delay_forms(self) -> None:
        """空 flow 与两类合法时延都应被精确保存。"""

        finite = parse_hcsp(
            "{{ode(flow(), domain(true), delay(1 / 2 + 1 / 4))}}"
        )
        infinite = parse_hcsp("{{ode(flow(), domain(true), delay(inf))}}")
        self.assertIsInstance(finite, ODE)
        self.assertIsInstance(infinite, ODE)
        assert isinstance(finite, ODE)
        assert isinstance(infinite, ODE)
        self.assertEqual(finite.eqs, ())
        self.assertEqual(finite.annotation.delay, Literal(Fraction(3, 4)))
        self.assertEqual(infinite.annotation.delay, inf)

    # 测试输入：两个相同 ODE，以及事件 continuation 单独读取 t 的 ODE。
    # 预期行为：相同源码 AST 相等但局部时钟对象新鲜；事件 t 仍是普通变量。
    # 检查内容：比较对象身份、get_vars 集合和连续公式中隐式 t 的消除。
    # 论文对应：实现 Table 2 新鲜计时器只绑定本次连续演化公式的作用域。
    def test_implicit_clock_is_fresh_and_scoped_to_continuous_formulas(self) -> None:
        """每个 ODE 的 t 应新鲜，且不捕获事件后继中的同名变量。"""

        source = (
            "{{ode(flow(dot x = t), domain(t <= 1), safety(t <= 1), delay(1))}}"
        )
        first = parse_hcsp(source)
        second = parse_hcsp(source)
        self.assertIsInstance(first, ODE)
        self.assertIsInstance(second, ODE)
        assert isinstance(first, ODE)
        assert isinstance(second, ODE)
        self.assertEqual(first, second)
        self.assertIsNot(first.local_clock, second.local_clock)
        self.assertEqual(first.get_vars(), {"x"})

        event_source = (
            "{{ode(flow(dot x = 0), domain(t <= 1), delay(1), "
            "interrupt(on report!(0) {use!(t)}))}}"
        )
        event_ode = parse_hcsp(event_source)
        self.assertIsInstance(event_ode, ODE)
        assert isinstance(event_ode, ODE)
        self.assertEqual(event_ode.get_vars(), {"x", "t"})

    # 测试输入：缺失/乱序/重复 clause、空 interrupt、重复方程和 dot t。
    # 预期行为：语法形状错误为 syntax，重复方程和保留时钟为 validation。
    # 检查内容：覆盖 ODE 固定字段顺序及用户方程向量的唯一性要求。
    # 论文对应：保证连续演化及其批注能唯一映射到 ODE AST 字段。
    def test_malformed_ode_structure_is_rejected(self) -> None:
        """ODE 必填字段、顺序、非空中断和方程左端必须严格检查。"""

        cases = (
            ("{{ode(domain(true), delay(1))}}", "syntax"),
            ("{{ode(flow(), delay(1))}}", "syntax"),
            ("{{ode(flow(), domain(true))}}", "syntax"),
            (
                "{{ode(flow(), domain(true), delay(1), safety(true))}}",
                "syntax",
            ),
            (
                "{{ode(flow(), domain(true), delay(1), interrupt())}}",
                "syntax",
            ),
            (
                "{{ode(flow(dot x = 0, dot x = 1), domain(true), delay(1))}}",
                "validation",
            ),
            (
                "{{ode(flow(dot t = 1), domain(true), delay(1))}}",
                "validation",
            ),
        )
        for source, phase in cases:
            with self.subTest(source=source):
                with self.assertRaises(HCSPInputError) as context:
                    parse_hcsp(source)
                self.assertEqual(context.exception.phase, phase)

    # 测试输入：负数、变量、布尔、取模、除零、非整数指数及 wait(inf)。
    # 预期行为：每个非法 duration 均产生 syntax 或 validation 诊断。
    # 检查内容：锁定 delay 的非负有理常量限制和 wait 的有限时长限制。
    # 论文对应：对应 ODE 外部批注 d 为非负有理数或正无穷的项目约束。
    def test_invalid_delay_and_wait_durations_are_rejected(self) -> None:
        """符号、负值和非有理时长不得进入 ODEAnnotation。"""

        invalid = (
            "{{ode(flow(), domain(true), delay(-1))}}",
            "{{ode(flow(), domain(true), delay(d))}}",
            "{{ode(flow(), domain(true), delay(true))}}",
            "{{ode(flow(), domain(true), delay(1 % 2))}}",
            "{{ode(flow(), domain(true), delay(1 / 0))}}",
            "{{ode(flow(), domain(true), delay(4 ** (1 / 2)))}}",
            "{{wait(inf)}}",
        )
        for source in invalid:
            with self.subTest(source=source):
                with self.assertRaises(HCSPInputError):
                    parse_hcsp(source)


class SourceAndParallelInputTests(unittest.TestCase):
    """验证外层非空语句块列表到 Process 或 Parallel 的 lowering。"""

    # 测试输入：只有 ``{skip}`` 一个内层语句块的完整 source。
    # 预期行为：直接返回 Skip，不生成不存在于论文语法的一元 Parallel。
    # 检查内容：比较节点类别和精确 AST。
    # 论文对应：对应系统产生式 S ::= P。
    def test_single_source_block_returns_process_directly(self) -> None:
        """单块 source 应退化为该 Process 本身。"""

        process = parse_hcsp("{{skip}}")
        self.assertEqual(process, Skip())
        self.assertNotIsInstance(process, Parallel)

    # 测试输入：三个使用不同通道的顶层语句块。
    # 预期行为：按书写顺序生成 Parallel.of 的规范右结合树。
    # 检查内容：精确比较三分量结构，不按集合去重或重新排序。
    # 论文对应：对应系统层反复使用二元 S || S' 的多分量表面写法。
    def test_multiple_source_blocks_build_ordered_parallel(self) -> None:
        """多块 source 应保持顺序 lower 为规范并行系统。"""

        source = "{{left!(0)}, {middle!(0)}, {right?(x)}}"
        expected = Parallel.of(
            OutputChannel("left", 0),
            OutputChannel("middle", 0),
            InputChannel("right", "x"),
        )
        self.assertEqual(parse_hcsp(source), expected)

    # 测试输入：两个 skip 重复块，以及同一通道一端输出一端输入。
    # 预期行为：重复块不去重；互补通信方向通过并行构造检查。
    # 检查内容：比较 Parallel 两侧并验证合法同步通道不会被误报同向冲突。
    # 论文对应：外层列表是有序多重列表，并符合 Assumption 2.1 的 iCh/oCh 分离。
    def test_duplicate_blocks_and_complementary_channels_are_preserved(self) -> None:
        """顶层块不做集合去重，同一通道的互补方向允许同步。"""

        self.assertEqual(parse_hcsp("{{skip}, {skip}}"), Parallel(Skip(), Skip()))
        self.assertEqual(
            parse_hcsp("{{ch!(0)}, {ch?(x)}}"),
            Parallel(OutputChannel("ch", 0), InputChannel("ch", "x")),
        )

    # 测试输入：共享变量、同向输入通道和同向输出通道的三个并行系统。
    # 预期行为：源码语法通过后在 AST lowering 阶段产生 validation 错误。
    # 检查内容：确认 Parser 不绕过 Parallel 构造器的 Assumption 2.1 检查。
    # 论文对应：对应并行分量 V、iCh 和 oCh 分别不相交的 Assumption 2.1。
    def test_parallel_resource_conflicts_are_validation_errors(self) -> None:
        """并行共享状态或同向通道必须由正式 AST 构造器拒绝。"""

        invalid = (
            "{{left!(x)}, {right!(x)}}",
            "{{ch?(x)}, {ch?(y)}}",
            "{{ch!(0)}, {ch!(1)}}",
        )
        for source in invalid:
            with self.subTest(source=source):
                with self.assertRaises(HCSPInputError) as context:
                    parse_hcsp(source)
                self.assertEqual(context.exception.phase, "validation")


if __name__ == "__main__":
    unittest.main()
