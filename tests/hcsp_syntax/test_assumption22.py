r"""Assumption 2.2 通信守卫的 AST 构造期检查测试。

测试内容
--------
1. 输入和输出都能保护直接递归回边，静默动作不能充当通信守卫。
2. ``If``、内部选择和公共顺序后继按“所有路径”解释通信保护。
3. ODE 事件 continuation 继承事件通信保护，自然结束后继不继承。
4. 内层同名 ``mu`` 遮蔽外层绑定，不同名 ``mu`` 不遮蔽外层变量。
5. 不含受绑定变量的递归真空满足条件，其他自由进程变量不受本检查约束。

论文对应
--------
对应 Section 2.1 的 Assumption 2.2：每个 ``mu X.P`` 都必须
communication-guarded；从绑定处到每个受绑定 ``X`` 的路径至少经过一个
多标量输入或输出。通信参数数量不影响守卫身份；这些测试只验证构造期良构性，
不代替 T-mu/T-X 的
尾位置和递归不变量证明。
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
    Sequence,
    Skip,
    Var,
)


class Assumption22ConstructionTests(unittest.TestCase):
    """逐路径验证 ``Mu`` 构造器执行的通信守卫检查。"""

    # 测试输入：分别构造 ``mu X.(in?x; X)`` 和 ``mu X.(out!1; X)``。
    # 预期行为：两个 Mu 都成功构造，因为回边前各有一次通信。
    # 检查内容：用输入、输出两个子测试覆盖 Assumption 2.2 认可的守卫节点。
    # 论文对应：Assumption 2.2 的通信守卫扩展到多标量输入与输出。
    def test_input_and_output_each_guard_a_recursive_call(self) -> None:
        """输入和输出动作都构成有效通信守卫。"""

        prefixes = (
            InputChannel("in", "value"),
            OutputChannel("out", 1),
        )
        for prefix in prefixes:
            with self.subTest(prefix=type(prefix).__name__):
                process = Mu("X", Sequence(prefix, Var("X")))
                self.assertIsInstance(process, Mu)

    # 测试输入：``mu X.(skip \sqcup Y)``，递归体没有受该 mu 绑定的 X。
    # 预期行为：Mu 成功构造；自由 Y 留待 T-X 的绑定检查处理。
    # 检查内容：确认条件按“每个 X 出现”量化，没有 X 时真空成立。
    # 论文对应：Assumption 2.2 只约束从当前 ``mu X`` 到其叶子 X 的路径。
    def test_absent_bound_occurrence_is_vacuously_guarded(self) -> None:
        """没有当前绑定的递归回边时，通信守卫条件真空成立。"""

        process = Mu("X", InternalChoice(Skip(), Var("Y")))
        self.assertIsInstance(process, Mu)

    # 测试输入：直接自环 ``mu X.X``。
    # 预期行为：Mu 构造器立即抛出带 Assumption 2.2 标识的 ValueError。
    # 检查内容：核对变量名和违规位置均进入诊断，不推迟到类型构造阶段。
    # 论文对应：绑定点到 X 的路径没有经过任何输入或输出通信。
    def test_direct_unguarded_recursive_call_is_rejected(self) -> None:
        """直接递归回边不满足通信守卫。"""

        with self.assertRaisesRegex(
            ValueError,
            r"Assumption 2\.2 violated.*'X'.*body",
        ):
            Mu("X", Var("X"))

    # 测试输入：分别用 skip、赋值和断言作为 X 前面的唯一动作。
    # 预期行为：三个 Mu 均在构造时被拒绝。
    # 检查内容：证明静默/离散内部动作不会被错误计算为通信动作。
    # 论文对应：Assumption 2.2 只承认输入或输出通信，不关心其参数元数。
    def test_silent_prefixes_do_not_guard_recursion(self) -> None:
        """Skip、赋值和断言都不能代替通信守卫。"""

        prefixes = (Skip(), Assign("x", 1), Assert("x >= 0"))
        for prefix in prefixes:
            with self.subTest(prefix=type(prefix).__name__):
                with self.assertRaisesRegex(ValueError, "Assumption 2.2"):
                    Mu("X", Sequence(prefix, Var("X")))

    # 测试输入：一次输入后连接 If，两个分支及内部选择叶子均为 X。
    # 预期行为：整个 Mu 成功构造，公共前缀保护后面的所有递归路径。
    # 检查内容：验证 Sequence 会把已经通信状态传入完整公共后继。
    # 论文对应：从 mu 到每个叶子 X 的路径都经过同一个 ``start?v``。
    def test_common_communication_prefix_guards_all_later_paths(self) -> None:
        """通信公共前缀可以同时保护后继中的多个递归回边。"""

        body = Sequence.of(
            InputChannel("start", "v"),
            If(
                "v >= 0",
                Var("X"),
                InternalChoice(Var("X"), Var("X")),
            ),
        )
        self.assertIsInstance(Mu("X", body), Mu)

    # 测试输入：If 的 then 分支为 ``out!1; X``，else 分支直接为 X。
    # 预期行为：构造失败，错误位置明确落在未受保护的 else 分支。
    # 检查内容：防止“任意一个分支存在通信”被误当成“每条路径通信”。
    # 论文对应：Assumption 2.2 对到达每一个 X 的路径作全称要求。
    def test_if_rejects_one_unguarded_recursive_branch(self) -> None:
        """If 的每个递归分支都必须各自受通信保护。"""

        body = If(
            True,
            Sequence.of(OutputChannel("out", 1), Var("X")),
            Var("X"),
        )
        with self.assertRaisesRegex(ValueError, r"body\.else"):
            Mu("X", body)

    # 测试输入：内部选择左支为 ``in?v; X``，右支直接为 X。
    # 预期行为：构造失败，右支不能继承另一个非确定分支中的通信。
    # 检查内容：验证选择分支的守卫状态相互独立。
    # 论文对应：到右侧 X 的路径没有经过左侧分支的 ``in?v``。
    def test_internal_choice_rejects_one_unguarded_branch(self) -> None:
        """内部选择的一支不能借用另一支的通信守卫。"""

        body = InternalChoice(
            Sequence.of(InputChannel("in", "v"), Var("X")),
            Var("X"),
        )
        with self.assertRaisesRegex(ValueError, r"body\.branches\[1\]"):
            Mu("X", body)

    # 测试输入：内部选择两支分别以输入和输出开头，随后都回到 X。
    # 预期行为：Mu 成功构造。
    # 检查内容：与单支违规用例配对，确认实现按 all 而非禁止选择节点。
    # 论文对应：两条到 X 的路径分别经过 ``left?v`` 和 ``right!1``。
    def test_all_internal_choice_branches_may_be_guarded(self) -> None:
        """选择节点合法，只要每条递归分支都有自己的通信。"""

        body = InternalChoice(
            Sequence.of(InputChannel("left", "v"), Var("X")),
            Sequence.of(OutputChannel("right", 1), Var("X")),
        )
        self.assertIsInstance(Mu("X", body), Mu)

    # 测试输入：多元内部选择的两个分支都通信，公共 continuation 为 X。
    # 预期行为：Mu 成功构造，因为到达公共 X 的两条路径都已受通信保护。
    # 检查内容：确认 Assumption 2.2 把左右出口状态分别传入第三字段。
    # 论文对应：``(P \sqcup P');Q`` 中每条到 Q 内递归回边的路径都必须通信。
    def test_choice_common_continuation_inherits_each_guarded_exit(self) -> None:
        """两个分支都通信时，公共递归后继受保护。"""

        body = InternalChoice(
            InputChannel("left", "v"),
            OutputChannel("right", 1),
            continuation=Var("X"),
        )
        self.assertIsInstance(Mu("X", body), Mu)

    # 测试输入：左分支通信、右分支 skip，公共 continuation 为 X。
    # 预期行为：构造失败，未通信的右路径不能借用左分支的保护状态。
    # 检查内容：确认合并出口仍保留 False，并在 continuation 的 X 处报错。
    # 论文对应：Assumption 2.2 对每条路径全称量化。
    def test_choice_common_continuation_rejects_one_unguarded_exit(self) -> None:
        """只有一个分支通信不足以保护公共递归后继。"""

        with self.assertRaisesRegex(ValueError, r"body\.continuation"):
            Mu(
                "X",
                InternalChoice(
                    InputChannel("left", "v"),
                    Skip(),
                    continuation=Var("X"),
                ),
            )

    # 测试输入：先执行 If；两个分支都是通信，随后公共后继为 X。
    # 预期行为：Mu 成功构造，因为到公共后继的每个出口状态都已通信。
    # 检查内容：验证分支出口状态会汇合并正确传递给 Sequence.second。
    # 论文对应：每条控制流路径分别经过输入或输出后才到达 X。
    def test_all_communicating_if_exits_guard_a_common_tail(self) -> None:
        """所有条件分支都通信时，可以保护汇合后的递归回边。"""

        body = If(
            True,
            InputChannel("left", "v"),
            OutputChannel("right", 1),
            continuation=Var("X"),
        )
        self.assertIsInstance(Mu("X", body), Mu)

    # 测试输入：If 的 then 分支输入，else 分支 skip，公共后继为 X。
    # 预期行为：构造失败，因为 else 路径未通信便能到达公共后继。
    # 检查内容：要求 Sequence 保留 If 的 False/True 两种出口状态而非只取并集。
    # 论文对应：Assumption 2.2 要求到公共 X 的两条路径都经过通信。
    def test_one_silent_if_exit_does_not_guard_a_common_tail(self) -> None:
        """只在部分条件路径通信不能保护汇合后的递归回边。"""

        with self.assertRaisesRegex(ValueError, r"body\.continuation"):
            Mu(
                "X",
                If(
                    True,
                    InputChannel("left", "v"),
                    Skip(),
                    continuation=Var("X"),
                ),
            )

    # 测试输入：ODE 的两个事件分支分别输入/输出，continuation 都是 X。
    # 预期行为：Mu 成功构造，因为事件分支语法保证先通信再执行 continuation。
    # 检查内容：递归遍历 EventChoice 的当前分支和 alternative 分支。
    # 论文对应：Section 2.1 的 ``(ch★ -> P) \Box E`` 与 Assumption 2.2。
    def test_ode_event_prefix_guards_its_continuation(self) -> None:
        """ODE 事件分支的通信前缀保护该分支 continuation。"""

        events = EventChoice(
            (InputChannel("stop", "v"), Var("X")),
            (OutputChannel("alarm", 1), Var("X")),
        )
        body = ODE(
            [("x", 1)],
            "x <= 1",
            events,
            annotation=ODEAnnotation(delay=1),
        )
        self.assertIsInstance(Mu("X", body), Mu)

    # 测试输入：含通信中断的 ODE 后面顺序连接 X。
    # 预期行为：构造失败；ODE 自然结束可不发生中断通信而直接到达 X。
    # 检查内容：区分受保护的事件 continuation 与未受保护的自然 fallback。
    # 论文对应：连续演化不是 Assumption 2.2 列出的通信动作。
    def test_ode_does_not_guard_its_sequential_fallback(self) -> None:
        """ODE 中存在事件分支也不能保护其自然结束后的公共后继。"""

        events = EventChoice((InputChannel("stop", "v"), Skip()))
        with self.assertRaisesRegex(ValueError, r"body\.continuation"):
            Mu(
                "X",
                ODE(
                    [("x", 1)],
                    "x <= 1",
                    events,
                    annotation=ODEAnnotation(delay=1),
                    continuation=Var("X"),
                ),
            )

    # 测试输入：外层和内层均绑定 X；另构造内层绑定 Y、体内引用外层 X。
    # 预期行为：同名内层遮蔽使外层真空通过；不同名内层不能遮蔽并被拒绝。
    # 检查内容：同时锁定词法遮蔽的正向和反向边界。
    # 论文对应：Assumption 2.2 只追踪“从该 binding 到其绑定的 X”。
    def test_nested_mu_respects_lexical_shadowing(self) -> None:
        """同名内层 mu 遮蔽外层绑定，不同名绑定则不会。"""

        inner = Mu(
            "X",
            Sequence.of(InputChannel("inner", "v"), Var("X")),
        )
        self.assertIsInstance(Mu("X", inner), Mu)

        different_binder = Mu("Y", Var("X"))
        with self.assertRaisesRegex(ValueError, r"mu\[Y\]\.body"):
            Mu("X", different_binder)


if __name__ == "__main__":
    unittest.main()
