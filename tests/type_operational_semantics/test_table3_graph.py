r"""Table 3 单步规则与完整 Type 状态转移图的回归测试。

测试内容
--------
1. 多元内部选择穷尽所有非 bottom 分支。
2. 所有并行通信配对均产生证据，相同图边合并而不丢推导来源。
3. 零时延边界同时保留 timeout 和可用通信。
4. 并行时间只走到最早有限 deadline，互补 ready 动作阻止时间。
5. 无穷等待产生 infinity 自循环，递归回边直接形成有限回图。
6. 等递归且选择幂等的同一项图类具有唯一、完备的出边集合。
7. 图规模上限明确产生不完整图，不伪装为完整闭包。

论文对应
--------
逐项覆盖 Section 4.4 Table 3 的 [P-unrhd]、[P-triangleright]、[P-sqcup]、
[P-unrhd'] 与 [P-|]；[P-mu] 在有限项图中编译为回边，不再通过 AST 展开执行。
"""

from __future__ import annotations

from fractions import Fraction
import unittest

from hcsp_typechecker.backend.type_operational_semantics import (
    build_type_transition_graph,
    derive_one_step,
    equi_recursive_state_key,
    normalized_type_from_state_key,
)
from hcsp_typechecker.data_structures.normalized_type_ast import normalize_type_ast
from hcsp_typechecker.data_structures.type_ast import (
    BottomType,
    EmptyType,
    ExternalChoiceType,
    FiniteDelayType,
    InfiniteDelayType,
    InputType,
    InternalChoiceType,
    MuType,
    NoInterruptType,
    OutputType,
    ParallelType,
    TypeVar,
)
from hcsp_typechecker.data_structures.type_transition_graph import (
    CommunicationDirection,
    InfiniteTime,
    ReadyAction,
    SilentTransitionLabel,
    Table3Rule,
    TimedTransitionLabel,
)


class Table3OneStepTests(unittest.TestCase):
    """直接检查规范化状态的一步后继是否穷尽且遵守优先条件。"""

    # 测试输入：含三个正常分支和一个 bottom 分支的多元内部选择。
    # 预期行为：规范化后每个不同非 bottom 分支各有一条 silent 边，bottom 不可选。
    # 检查内容：[P-sqcup] 的多元推广、幂等规范化和 bottom 前提。
    # 论文对应：Table 3 [P-sqcup] 只允许选择 T != bottom 的内部选择分支。
    def test_internal_choice_enumerates_every_non_bottom_branch(self) -> None:
        """多元内部选择保留全部语义不同的非确定性结果。"""

        branches = (
            FiniteDelayType(1, NoInterruptType(), EmptyType()),
            FiniteDelayType(2, NoInterruptType(), EmptyType()),
            FiniteDelayType(3, NoInterruptType(), EmptyType()),
            BottomType(),
        )

        transitions = derive_one_step(
            equi_recursive_state_key(
                normalize_type_ast(InternalChoiceType(branches))
            )
        )

        self.assertEqual(len(transitions), 3)
        self.assertTrue(
            all(isinstance(item.label, SilentTransitionLabel) for item in transitions)
        )
        self.assertTrue(
            all(
                item.derivation.rule is Table3Rule.INTERNAL_CHOICE
                for item in transitions
            )
        )

    # 测试输入：一个 ch! 分量和两个完全相同的 ch? 分量并行等待。
    # 预期行为：两种接收者选择得到同一状态边，图边保存两份通信规则证据。
    # 检查内容：通信枚举不依赖分量位置，边去重不丢非确定性推导来源。
    # 论文对应：Table 3 [P-unrhd] 可选择任意两个具有互补通信的并行分量。
    def test_all_matching_component_pairs_are_retained_as_witnesses(self) -> None:
        """相同目标的多种通信配对聚合在同一状态图边。"""

        sender = InfiniteDelayType(OutputType("ch", EmptyType()))
        receiver = InfiniteDelayType(InputType("ch", EmptyType()))
        graph = build_type_transition_graph(
            ParallelType((sender, receiver, receiver))
        )

        initial_edges = graph.outgoing(graph.initial_state)
        communication_edges = tuple(
            edge
            for edge in initial_edges
            if isinstance(edge.label, SilentTransitionLabel)
        )
        self.assertEqual(len(communication_edges), 1)
        self.assertEqual(len(communication_edges[0].derivations), 2)
        self.assertTrue(
            all(
                witness.rule is Table3Rule.COMMUNICATION
                for witness in communication_edges[0].derivations
            )
        )

    # 测试输入：delay(0) 输入分量与同通道无穷输出分量并行。
    # 预期行为：当前状态同时存在 timeout 和通信两条不同 silent 后继。
    # 检查内容：边界时刻不擅自加入通信优先策略，完整保存 Table 3 非确定性。
    # 论文对应：[P-triangleright] 与 [P-unrhd] 的前提在该状态同时成立。
    def test_zero_deadline_keeps_timeout_and_communication(self) -> None:
        """零时延边界同时枚举自然到时和同步中断。"""

        receiver = FiniteDelayType(
            0,
            InputType("ch", EmptyType()),
            InfiniteDelayType(NoInterruptType()),
        )
        sender = InfiniteDelayType(OutputType("ch", EmptyType()))

        transitions = derive_one_step(
            equi_recursive_state_key(
                normalize_type_ast(ParallelType((receiver, sender)))
            )
        )

        self.assertEqual(len(transitions), 2)
        rules = {item.derivation.rule for item in transitions}
        self.assertEqual(
            rules,
            {Table3Rule.TIMEOUT, Table3Rule.COMMUNICATION},
        )

    # 测试输入：剩余时延 2 和 5、ready set 不互补的两个并行 delay。
    # 预期行为：只有一条 duration=2 的共同时间边，目标剩余时延为 0 和 3。
    # 检查内容：最大共同等待选择最早 deadline，并合并两个 ready set。
    # 论文对应：[P-unrhd'] 与 [P-|] 使用同一 d 同步推进全部并行分量。
    def test_parallel_time_advances_to_the_earliest_deadline(self) -> None:
        """连续时间不会产生无关键事件的任意中间切分。"""

        left = FiniteDelayType(2, InputType("left", EmptyType()), EmptyType())
        right = FiniteDelayType(5, OutputType("right", EmptyType()), EmptyType())

        transitions = derive_one_step(
            equi_recursive_state_key(
                normalize_type_ast(ParallelType((left, right)))
            )
        )

        self.assertEqual(len(transitions), 1)
        transition = transitions[0]
        self.assertIsInstance(transition.label, TimedTransitionLabel)
        self.assertEqual(transition.label.duration, Fraction(2))
        self.assertEqual(
            transition.label.ready,
            frozenset(
                {
                    ReadyAction("left", CommunicationDirection.INPUT),
                    ReadyAction("right", CommunicationDirection.OUTPUT),
                }
            ),
        )
        target_ast = normalized_type_from_state_key(transition.target)
        durations = tuple(
            getattr(component, "duration", None)
            for component in target_ast.components
        )
        self.assertEqual(durations, (Fraction(0), Fraction(3)))

    # 测试输入：两个正时延分量在同一 ch 上分别准备输入和输出。
    # 预期行为：不存在时间边，只产生立即通信的 silent 边。
    # 检查内容：互补 ready set 阻止时间跨越已经可执行的同步。
    # 论文对应：[P-|] 前提 R1 与 complement(R2) 的交集必须为空。
    def test_complementary_ready_actions_block_time(self) -> None:
        """已经可同步的通信优先于任何正时间流逝。"""

        left = FiniteDelayType(2, InputType("ch", EmptyType()), EmptyType())
        right = FiniteDelayType(5, OutputType("ch", EmptyType()), EmptyType())

        transitions = derive_one_step(
            equi_recursive_state_key(
                normalize_type_ast(ParallelType((left, right)))
            )
        )

        self.assertEqual(len(transitions), 1)
        self.assertIsInstance(transitions[0].label, SilentTransitionLabel)
        self.assertEqual(
            transitions[0].derivation.rule,
            Table3Rule.COMMUNICATION,
        )


class TypeTransitionGraphTests(unittest.TestCase):
    """检查递归闭包、无穷时间自循环和显式截断元数据。"""

    # 测试输入：无匹配者的无穷 ch? 等待。
    # 预期行为：完整图只有一个状态和一条 infinity/ready={ch?} 自循环。
    # 检查内容：无穷 delay 在关键 deadline 策略下保持同一规范状态。
    # 论文对应：[P-unrhd'] 的 infinity+d=infinity，也是后续死锁定义所需图形。
    def test_infinite_wait_is_an_infinity_self_loop(self) -> None:
        """无穷等待不会制造无限多个重复状态。"""

        value = InfiniteDelayType(InputType("ch", EmptyType()))

        graph = build_type_transition_graph(value)

        self.assertTrue(graph.complete)
        self.assertEqual(len(graph.states), 1)
        self.assertEqual(len(graph.transitions), 1)
        edge = graph.transitions[0]
        self.assertEqual((edge.source, edge.target), (0, 0))
        self.assertIsInstance(edge.label, TimedTransitionLabel)
        self.assertIs(edge.label.duration, InfiniteTime.VALUE)

    # 测试输入：mu t.delay(infinity) interrupt ch?->t 与一次 ch! 并行。
    # 预期行为：通信直接沿递归项图回边发生，且不会复制 AST 展开状态。
    # 检查内容：递归协议在有限循环项图上完成通信并形成有限可达图。
    # 论文对应：[P-mu] 已被回边编码，实际边只记录继承后的通信规则。
    def test_guarded_recursion_builds_a_finite_graph(self) -> None:
        """递归后继通过规范状态键闭合为有限图。"""

        recursive = MuType(
            "t",
            InfiniteDelayType(InputType("ch", TypeVar("t"))),
        )
        sender = InfiniteDelayType(OutputType("ch", EmptyType()))

        graph = build_type_transition_graph(ParallelType((recursive, sender)))

        self.assertTrue(graph.complete)
        self.assertLessEqual(len(graph.states), 3)
        self.assertTrue(
            any(
                witness.rule is Table3Rule.COMMUNICATION
                for edge in graph.transitions
                for witness in edge.derivations
            )
        )

    # 测试输入：一个递归 request 服务端与两个相同的一次性客户端并行。
    # 预期行为：图恰有“两个客户端、一个客户端、零客户端”三个状态；服务端展开态不另占节点。
    # 检查内容：每次同步后的 mu 折叠/展开差异按正规树等价合并，最终 infinity 边回到零客户端状态自身。
    # 论文对应：[P-mu] 的递归方程被项图回边吸收，[P-unrhd] 直接沿回边执行。
    def test_equi_recursive_quotient_removes_unfold_only_states(self) -> None:
        """状态图按等递归树而不是 mu 的有限展开深度判重。"""

        server = MuType(
            "server",
            InfiniteDelayType(InputType("request", TypeVar("server"))),
        )
        client = InfiniteDelayType(OutputType("request", EmptyType()))

        graph = build_type_transition_graph(
            ParallelType((server, client, client))
        )

        self.assertTrue(graph.complete)
        self.assertEqual(len(graph.states), 3)
        self.assertEqual(len(graph.transitions), 3)
        displayed_keys = tuple(
            equi_recursive_state_key(state.type_ast) for state in graph.states
        )
        self.assertEqual(len(set(displayed_keys)), len(graph.states))
        terminal_edges = graph.outgoing(2)
        self.assertEqual(len(terminal_edges), 1)
        self.assertEqual(
            (terminal_edges[0].source, terminal_edges[0].target),
            (2, 2),
        )
        self.assertEqual(
            terminal_edges[0].derivations[0].rule,
            Table3Rule.DELAY,
        )

    # 测试输入：递归循环 L、其一次展开 U，以及幂等选择 C=L sqcup U，分别与发送者并行。
    # 预期行为：三者具有同一初始项图状态，并暴露完全相同的通信和时间转移。
    # 检查内容：Table 3 不再依赖等价类第一次遇到的 AST 代表。
    # 论文对应：等递归方程与内部选择幂等律共同取商后，操作语义定义在商类上。
    def test_table3_is_computed_on_the_regular_tree_equivalence_class(self) -> None:
        """递归等价选择代表不能改变状态的可执行通信行为。"""

        loop = MuType(
            "loop",
            InfiniteDelayType(InputType("ch", TypeVar("loop"))),
        )
        unfolded = InfiniteDelayType(InputType("ch", loop))
        choice = InternalChoiceType((loop, unfolded))
        sender = InfiniteDelayType(OutputType("ch", EmptyType()))

        loop_graph = build_type_transition_graph(ParallelType((loop, sender)))
        choice_graph = build_type_transition_graph(ParallelType((choice, sender)))

        self.assertEqual(loop_graph.states, choice_graph.states)
        self.assertEqual(loop_graph.transitions, choice_graph.transitions)

    # 测试输入：会产生多个可达状态的两个有限并行 delay，max_states=2。
    # 预期行为：图在达到上限时返回 complete=False 和明确截断原因。
    # 检查内容：资源限制不能让部分图伪装为完整可达闭包。
    # 论文对应：不改变 Table 3；这是状态空间爆炸时对实现完备性的审计标记。
    def test_state_limit_marks_the_graph_as_truncated(self) -> None:
        """受限生成结果通过结构字段明确声明不完整。"""

        value = ParallelType(
            (
                FiniteDelayType(2, NoInterruptType(), EmptyType()),
                FiniteDelayType(5, NoInterruptType(), EmptyType()),
            )
        )

        graph = build_type_transition_graph(value, max_states=2)

        self.assertFalse(graph.complete)
        self.assertEqual(len(graph.states), 2)
        self.assertIn("maximum state count 2", graph.truncation_reason or "")

    # 测试输入：具有多条后继的内部选择和 max_transitions=1。
    # 预期行为：部分图只加入首条边及其目标，不留下无入边的提前分配目标状态。
    # 检查内容：边上限检查先于新目标状态注册，保持部分图内部引用一致。
    # 论文对应：限制只截断 Table 3 枚举，不应伪造未被任何已保存转移到达的状态。
    def test_transition_limit_does_not_leave_an_orphan_state(self) -> None:
        """边数截断时图中每个非初态仍由至少一条已保存边到达。"""

        value = InternalChoiceType(
            (
                FiniteDelayType(1, NoInterruptType(), EmptyType()),
                FiniteDelayType(2, NoInterruptType(), EmptyType()),
                FiniteDelayType(3, NoInterruptType(), EmptyType()),
            )
        )

        graph = build_type_transition_graph(value, max_transitions=1)

        self.assertFalse(graph.complete)
        self.assertEqual(len(graph.transitions), 1)
        self.assertEqual(len(graph.states), 2)
        self.assertEqual(graph.transitions[0].target, 1)


if __name__ == "__main__":
    unittest.main()
