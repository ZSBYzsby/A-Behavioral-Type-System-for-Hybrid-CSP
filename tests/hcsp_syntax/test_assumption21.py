r"""Assumption 2.1 完整构造期检查测试。

测试内容
--------
1. 验证 ``ch?(x1,...,xn)`` 绑定顺序后继和事件 continuation 中的同名值变量；
   按项目约定，复合前缀分支中的输入也可绑定公共顺序后继。
2. 拒绝先自由使用后输入绑定，以及跨选择/事件分支的自由与绑定重名。
3. 验证 ``mu X.P`` 绑定体内 X，并拒绝系统中自由/绑定进程变量重名。
4. 验证并行分量的 ``V``、``iCh`` 和 ``oCh`` 必须分别不相交。
5. 验证互补通道合法、嵌套并行汇总资源，并拒绝 ODE 状态变量被中断输入重绑。
6. 验证每个 ODE 的隐藏局部时钟不进入 ``V``，并行 ODE 不会发生时钟冲突。

论文对应
--------
对应 Section 2.1 的 Assumption 2.1。项目在复合 AST 构造时强制
``fv(S) \cap bv(S) = \emptyset``，并在 ``Parallel`` 构造时继续强制
``V``、``iCh``、``oCh`` 三项分离条件。
"""

from __future__ import annotations

import unittest

from hcsp_typechecker._internal import (
    Assert,
    Assign,
    EmptyEvent,
    EventChoice,
    If,
    InputChannel,
    InternalChoice,
    Mu,
    ODE,
    ODEAnnotation,
    OutputChannel,
    Parallel,
    Sequence,
    Skip,
    Var,
)


class Assumption21ConstructionTests(unittest.TestCase):
    """覆盖 fv/bv 作用域和并行资源分离的全部 Assumption 2.1 条件。"""

    # 测试输入：``sensor?x; assert(x>=0)`` 与
    #           ``(if B then sensor?x else skip); assert(x>=0)``。
    # 预期行为：直接输入和复合前缀分支中的输入都绑定公共顺序后继 x。
    # 检查内容：固定已确认的项目作用域约定，防止再被误改为 definitely-bound 分析。
    # 论文对应：扩展输入动作绑定全部 xi；公共后继的处理采用项目约定。
    def test_input_target_binds_sequence_continuation(self) -> None:
        """输入目标变量在该输入的顺序后继中属于绑定出现。"""

        process = Sequence(
            InputChannel("sensor", "x"),
            Assert("x >= 0"),
        )
        self.assertIsInstance(process, Sequence)

        branched_prefix = If(
            True,
            InputChannel("sensor", "x"),
            Skip(),
            continuation=Assert("x >= 0"),
        )
        self.assertIsInstance(branched_prefix, If)
        self.assertIsInstance(branched_prefix.continuation, Assert)

    # 测试输入：``assert(x >= 0); sensor?x``，先自由读取再绑定 x。
    # 预期行为：Sequence 因 x 同属 fv 和 bv 抛出 ValueError。
    # 检查内容：核对诊断明确包含 overlap 和冲突变量 x。
    # 论文对应：Assumption 2.1 的 ``fv(S) \cap bv(S) = \emptyset``。
    def test_input_cannot_bind_a_previously_free_variable(self) -> None:
        """先自由使用再由输入绑定同名变量违反 Barendregt 约定。"""

        with self.assertRaisesRegex(
            ValueError,
            r"free and bound variables overlap: x",
        ):
            Sequence(
                Assert("x >= 0"),
                InputChannel("sensor", "x"),
            )

    # 测试输入：内部选择 ``left?x \sqcup assert(x >= 0)``。
    # 预期行为：一支绑定、一支自由读取 x，InternalChoice 构造失败。
    # 检查内容：证明选择分支互不构成作用域，集合合并后仍检查 fv/bv。
    # 论文对应：Section 2.1 内部选择及 Assumption 2.1。
    def test_choice_rejects_free_and_bound_name_overlap(self) -> None:
        """不同选择分支不能分别自由使用和绑定同一个值变量。"""

        with self.assertRaisesRegex(ValueError, r"overlap: x"):
            InternalChoice(
                InputChannel("left", "x"),
                Assert("x >= 0"),
            )

    # 测试输入：事件分支 ``(sensor?x -> assert(x >= 0)) \Box empty``。
    # 预期行为：EventChoice 成功构造，continuation 中的 x 已被输入绑定。
    # 检查内容：确认事件通信只把目标作用到本分支 continuation。
    # 论文对应：Section 2.1 的输入事件反应产生式 E。
    def test_event_input_binds_its_branch_continuation(self) -> None:
        """事件输入目标在本分支 continuation 中属于绑定出现。"""

        reaction = EventChoice(
            (InputChannel("sensor", "x"), Assert("x >= 0")),
        )
        self.assertIsInstance(reaction, EventChoice)

    # 测试输入：一支 ``sensor?x``，另一支 continuation 自由读取 x。
    # 预期行为：外层 EventChoice 因跨分支 fv/bv 重名而被拒绝。
    # 检查内容：确认输入不绑定 alternative 事件分支中的 x。
    # 论文对应：递归 ``\Box`` 事件选择及 Assumption 2.1 的全局不交。
    def test_event_alternative_cannot_reuse_input_target_name(self) -> None:
        """事件输入目标不能在另一事件分支中作为自由变量出现。"""

        other_branch = (OutputChannel("report", 1), Assert("x >= 0"))
        with self.assertRaisesRegex(ValueError, r"overlap: x"):
            EventChoice(
                other_branch,
                (InputChannel("sensor", "x"), Skip()),
            )

    # 测试输入：通信保护的 ``mu X.(guard!None; X)``。
    # 预期行为：Mu 成功构造；体内 X 被 mu 绑定，不计为自由进程变量。
    # 检查内容：同时满足 Assumption 2.1 的作用域和 Assumption 2.2 的守卫。
    # 论文对应：``mu X.P`` 把 X 绑定在递归体 P 中。
    def test_mu_binds_occurrences_in_its_body(self) -> None:
        """Mu 绑定器会从递归体的自由进程变量中移除自身名称。"""

        recursive = Mu(
            "X",
            Sequence(OutputChannel("guard", 0), Var("X")),
        )
        self.assertIsInstance(recursive, Mu)

    # 测试输入：``X \sqcup mu X.(guard!None; X)``。
    # 预期行为：自由 X 与另一分支绑定 X 重名，InternalChoice 构造失败。
    # 检查内容：递归体已通信保护，从而隔离 Assumption 2.1 的失败原因。
    # 论文对应：进程变量同样必须满足 ``fv(S) \cap bv(S) = \emptyset``。
    def test_mu_free_and_bound_process_names_cannot_overlap(self) -> None:
        """同一系统不能同时自由使用和绑定同名进程变量。"""

        recursive = Mu(
            "X",
            Sequence(OutputChannel("guard", 0), Var("X")),
        )
        with self.assertRaisesRegex(
            ValueError,
            r"overlap: X \(process variable\)",
        ):
            InternalChoice(Var("X"), recursive)

    # 测试输入：并行 ``x := 1 || assert(x >= 0)``。
    # 预期行为：两侧仅自由使用 x，但因共享 V 而抛出 ValueError。
    # 检查内容：隔离并行变量分离检查，不让 fv/bv overlap 抢先触发。
    # 论文对应：Assumption 2.1 的 ``V(S1) \cap V(S2) = \emptyset``。
    def test_parallel_rejects_shared_value_variables(self) -> None:
        """并行分量的完整值变量集合 V 必须不相交。"""

        with self.assertRaisesRegex(
            ValueError,
            r"parallel components share variables: x",
        ):
            Parallel(Assign("x", 1), Assert("x >= 0"))

    # 测试输入：并行 ``mu X.skip || mu X.skip``。
    # 预期行为：两侧都绑定 X，各自 fv/bv 合法，但并行 V 共享而失败。
    # 检查内容：验证 V 也包含 Mu 引入的绑定进程变量。
    # 论文对应：Assumption 2.1 中 V 是自由与绑定变量的不交并集。
    def test_parallel_rejects_shared_process_variables(self) -> None:
        """并行 V 分离检查覆盖绑定进程变量名称。"""

        with self.assertRaisesRegex(
            ValueError,
            r"share variables: X \(process variable\)",
        ):
            Parallel(Mu("X", Skip()), Mu("X", Skip()))

    # 测试输入：``c?x || c?y``，变量互异但输入通道相同。
    # 预期行为：因共享输入通道 c 抛出 ValueError。
    # 检查内容：隔离通道冲突原因，避免误由变量集合触发。
    # 论文对应：Assumption 2.1 的 ``iCh(S1) \cap iCh(S2) = \emptyset``。
    def test_parallel_rejects_shared_input_channels(self) -> None:
        """两个并行分量不能在同一通道上都执行输入。"""

        with self.assertRaisesRegex(ValueError, r"share input channels: c"):
            Parallel(
                InputChannel("c", "x"),
                InputChannel("c", "y"),
            )

    # 测试输入：``c!1 || c!2``，两侧都在 c 上输出。
    # 预期行为：因共享输出通道 c 抛出 ValueError。
    # 检查内容：核对方向敏感的输出通道集合和错误信息。
    # 论文对应：Assumption 2.1 的 ``oCh(S1) \cap oCh(S2) = \emptyset``。
    def test_parallel_rejects_shared_output_channels(self) -> None:
        """两个并行分量不能在同一通道上都执行输出。"""

        with self.assertRaisesRegex(ValueError, r"share output channels: c"):
            Parallel(OutputChannel("c", 1), OutputChannel("c", 2))

    # 测试输入：``c?x || c!1``，同一通道但方向互补且变量分离。
    # 预期行为：Parallel 成功构造，可由两侧在 c 上同步。
    # 检查内容：证明只禁止同向集合相交，不错误禁止输入/输出配对。
    # 论文对应：HCSP 并行通信同步与 Assumption 2.1 的方向化通道集合。
    def test_parallel_allows_complementary_channel_directions(self) -> None:
        """同一通道的一入一出是合法同步，不属于同向通道冲突。"""

        system = Parallel(
            InputChannel("c", "x"),
            OutputChannel("c", 1),
        )
        self.assertIsInstance(system, Parallel)

    # 测试输入：外层 c!0 与内层 ``d!1 || c!2`` 并行。
    # 预期行为：外层检测到内层汇总的输出通道 c 并拒绝。
    # 检查内容：验证检查覆盖整个子系统，而不只比较直接子节点。
    # 论文对应：任意 ``S1 \parallel S2`` 的 oCh 都必须不相交。
    def test_nested_parallel_checks_aggregated_channels(self) -> None:
        """外层并行会检查整个嵌套子系统汇总后的通道集合。"""

        nested = Parallel(
            OutputChannel("d", 1),
            OutputChannel("c", 2),
        )
        with self.assertRaisesRegex(ValueError, r"share output channels: c"):
            Parallel(OutputChannel("c", 0), nested)

    # 测试输入：两个没有用户状态变量的 ODE 直接并行。
    # 预期行为：Parallel 构造成功；两侧自动时钟不同且均不进入 get_vars()/V。
    # 检查内容：确认隐藏时钟具有真正的 ODE 局部作用域，而非共享普通变量名。
    # 论文对应：Assumption 2.1 的 V 分离只约束源程序变量，不包含新鲜局部 t。
    def test_parallel_ode_clocks_are_fresh_and_excluded_from_v(self) -> None:
        """并行 ODE 的自动局部时钟不会造成虚假的变量分区冲突。"""

        left = ODE([], True, annotation=ODEAnnotation(delay=1))
        right = ODE([], True, annotation=ODEAnnotation(delay=2))
        system = Parallel(left, right)

        self.assertIs(system.left, left)
        self.assertIs(system.right, right)
        self.assertIsNot(left.local_clock, right.local_clock)
        self.assertEqual(left.get_vars(), set())
        self.assertEqual(right.get_vars(), set())

    # 测试输入：ODE 自由状态变量 x，外部中断为 ``stop?x -> skip``。
    # 预期行为：ODE 因 x 同时属于连续状态 fv 和输入 bv 而失败。
    # 检查内容：覆盖连续演化与事件输入组合中的 fv/bv 冲突。
    # 论文对应：Assumption 2.1 对整个 ODE 进程的变量集合适用。
    def test_ode_variable_cannot_be_rebound_by_interrupt_input(self) -> None:
        """ODE 状态变量不能同时作为中断输入绑定目标。"""

        interrupts = EventChoice((InputChannel("stop", "x"), Skip()))
        with self.assertRaisesRegex(ValueError, r"overlap: x"):
            ODE(
                [("x", 1)],
                "x <= 10",
                interrupts,
                annotation=ODEAnnotation(delay=1),
            )


if __name__ == "__main__":
    unittest.main()
