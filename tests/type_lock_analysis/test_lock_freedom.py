r"""第四接口的死锁自由、活锁自由语义与高负载回归测试。

测试内容
--------
1. 区分非空 ready 的无限等待、空 ready 的无限空闲和无出边终态；
2. 检出纯静默自环/多结点环，同时拒绝把含时间边的环当作活锁；
3. 返回从初态到反例的连续路径和 Table 3 原始迁移证据；
4. 拒绝含不可达孤立状态的非闭包图，并提供三档公共输出；
5. 用长链确认 BFS/DFS/路径重建不依赖 Python 递归。
6. 区分正常 Empty 终态与可达 Bottom 错误终止，并返回最短错误见证。

论文对应
--------
Section 4.4 Definition 4.5--4.7：死锁是 ``T --infinity,R-->`` 且
``R != empty``；活锁是无限静默推导 ``T ->^omega``；LF 同时要求二者不存在。
"""

from __future__ import annotations

from io import StringIO
import unittest

from hcsp_typechecker import (
    HCSPTypeLockAnalysisError,
    LockFreedomReport,
    TypeLockAnalysisErrorKind,
    analyze_type_lock_freedom,
    build_type_transition_graph,
)
from hcsp_typechecker.backend.type_lock_analysis import analyze_lock_freedom
from hcsp_typechecker.backend.type_operational_semantics import (
    build_type_transition_graph as build_graph_internal,
)
from hcsp_typechecker.data_structures.normalized_type_ast import (
    NormalizedConfigurationType,
    NormalizedEmptyType,
)
from hcsp_typechecker.data_structures.type_ast import (
    BottomType,
    EmptyType,
    FiniteDelayType,
    InfiniteDelayType,
    InputType,
    NoInterruptType,
    OutputType,
    ParallelType,
)
from hcsp_typechecker.data_structures.type_transition_graph import (
    CommunicationDirection,
    InfiniteTime,
    ReadyAction,
    SilentTransitionLabel,
    Table3Rule,
    TimedTransitionLabel,
    TransitionDerivation,
    TypeState,
    TypeTransition,
    TypeTransitionGraph,
)


_NORMALIZED_EMPTY = NormalizedConfigurationType((NormalizedEmptyType(),))
_TAU_DERIVATION = TransitionDerivation(Table3Rule.INTERNAL_CHOICE)
_TIME_DERIVATION = TransitionDerivation(Table3Rule.PARALLEL_TIME)


def _manual_graph(
    state_count: int,
    edges: tuple[TypeTransition, ...],
) -> TypeTransitionGraph:
    """建立内容相同但身份不同的测试状态，突出图算法而非 Type 降低。"""

    return TypeTransitionGraph(
        initial_state=0,
        states=tuple(
            TypeState(state_id, _NORMALIZED_EMPTY)
            for state_id in range(state_count)
        ),
        transitions=edges,
    )


class LockFreedomSemanticsTests(unittest.TestCase):
    """锁定论文死锁/活锁定义以及反例返回协议。"""

    # 测试输入：一个永远等待输入 ch? 的无穷 delay Type。
    # 预期行为：唯一无限时间自环的 ready 集非空，报告死锁但不报告活锁。
    # 检查内容：死锁见证使用空可达前缀和原图中的无限等待边。
    # 论文对应：Definition 4.5 的 ``d=infinity`` 且 ``R != empty`` 条件。
    def test_infinite_wait_with_ready_action_is_deadlock(self) -> None:
        """非空 ready 无限等待产生可复查死锁见证。"""

        graph = build_graph_internal(
            InfiniteDelayType(InputType("ch", EmptyType()))
        )

        report = analyze_lock_freedom(graph)

        self.assertFalse(report.deadlock_free)
        self.assertTrue(report.livelock_free)
        self.assertFalse(report.lock_free)
        witness = report.deadlock_witness
        self.assertIsNotNone(witness)
        assert witness is not None
        self.assertEqual(witness.prefix.transitions, ())
        self.assertIs(witness.infinite_wait, graph.transitions[0])

    # 测试输入：无中断的无限 delay 与正常 EmptyType。
    # 预期行为：前者 ready 为空、后者无出边，二者都不被误判为死锁或活锁。
    # 检查内容：死锁不是“没有后继”的一般图论死端，而严格采用论文标签定义。
    # 论文对应：Definition 4.5 明确额外要求非空 ready set。
    def test_idle_infinity_and_empty_terminal_are_lock_free(self) -> None:
        """无限空闲与正常终态均不构成论文定义的锁。"""

        for type_ast in (InfiniteDelayType(NoInterruptType()), EmptyType()):
            with self.subTest(type_ast=type(type_ast).__name__):
                report = analyze_lock_freedom(build_graph_internal(type_ast))
                self.assertTrue(report.deadlock_free)
                self.assertTrue(report.livelock_free)
                self.assertTrue(report.lock_free)
                self.assertTrue(report.error_free)
                self.assertTrue(report.behavior_correct)

    # 测试输入：单独 BottomType 错误终态，与 EmptyType 正常终态对照。
    # 预期行为：两者都没有锁，但只有 Bottom 使 error_free/behavior_correct 为假。
    # 检查内容：错误终止不会被重命名为死锁，也不会被正常 Empty 结论掩盖。
    # 论文对应：Bottom 是异常终止；Definition 4.5--4.7 的锁自由仍保持独立。
    def test_bottom_terminal_is_reported_separately_from_lock_freedom(self) -> None:
        """Bottom 终态保持 lock_free，但不再被报告为整体行为正确。"""

        report = analyze_lock_freedom(build_graph_internal(BottomType()))

        self.assertTrue(report.deadlock_free)
        self.assertTrue(report.livelock_free)
        self.assertTrue(report.lock_free)
        self.assertFalse(report.error_free)
        self.assertFalse(report.behavior_correct)
        witness = report.bottom_error_witness
        self.assertIsNotNone(witness)
        assert witness is not None
        self.assertEqual(witness.prefix.state_ids, (0,))
        self.assertEqual(witness.component_indices, (0,))

    # 测试输入：ch 同步后接收分量进入 Bottom，发送分量仍有可执行的零时延。
    # 预期行为：报告从初态到错误状态的一步最短路径，并指出 Bottom 根位置。
    # 检查内容：只检查已成为并行根的 Bottom，不误报 delay/通信 continuation 中尚未到达的 Bottom。
    # 论文对应：同步失败后的异常终止是可达行为错误，需与锁见证分开记录。
    def test_reachable_bottom_has_a_shortest_error_witness(self) -> None:
        """可达 Bottom 错误使用 BFS 父边返回最短前缀和准确分量位置。"""

        receiver = InfiniteDelayType(InputType("ch", BottomType()))
        unmatched = analyze_lock_freedom(build_graph_internal(receiver))
        self.assertTrue(unmatched.error_free)

        sender = InfiniteDelayType(
            OutputType(
                "ch",
                FiniteDelayType(0, NoInterruptType(), EmptyType()),
            )
        )
        graph = build_graph_internal(ParallelType((receiver, sender)))
        report = analyze_lock_freedom(graph)

        self.assertTrue(report.lock_free)
        self.assertFalse(report.error_free)
        self.assertFalse(report.behavior_correct)
        witness = report.bottom_error_witness
        self.assertIsNotNone(witness)
        assert witness is not None
        self.assertEqual(len(witness.prefix.transitions), 1)
        self.assertEqual(witness.prefix.end_state, graph.transitions[0].target)
        self.assertEqual(witness.component_indices, (0,))

        output = StringIO()
        public_report = analyze_type_lock_freedom(
            graph,
            output="full",
            stream=output,
        )
        self.assertEqual(public_report, report)
        self.assertIn("Bottom 错误反例", output.getvalue())
        self.assertIn("bottom_error_witness", output.getvalue())
        self.assertIn("bottom_components = (0,)", output.getvalue())

    # 测试输入：S0 经一条时间边到 S1，S1 具有 tau 自环且另有退出边。
    # 预期行为：仍存在无限选择 tau 的执行，故报告活锁并返回 S1 自环。
    # 检查内容：前缀允许含时间边；有退出机会不会消除存在性的无限静默路径。
    # 论文对应：Definition 4.6 使用存在无限静默推导，而非“无可退出”的强公平条件。
    def test_silent_cycle_with_exit_is_livelock(self) -> None:
        """具有退出边的可达静默环仍是活锁反例。"""

        graph = _manual_graph(
            3,
            (
                TypeTransition(0, 1, TimedTransitionLabel(1, ()), (_TIME_DERIVATION,)),
                TypeTransition(1, 1, SilentTransitionLabel(), (_TAU_DERIVATION,)),
                TypeTransition(1, 2, SilentTransitionLabel(), (_TAU_DERIVATION,)),
            ),
        )

        report = analyze_lock_freedom(graph)

        self.assertTrue(report.deadlock_free)
        self.assertFalse(report.livelock_free)
        witness = report.livelock_witness
        self.assertIsNotNone(witness)
        assert witness is not None
        self.assertEqual(witness.prefix.state_ids, (0, 1))
        self.assertEqual(witness.cycle.state_ids, (1, 1))

    # 测试输入：两个状态只通过正时间边形成闭环。
    # 预期行为：报告不存在活锁，因为每轮循环都消耗正时间。
    # 检查内容：活锁搜索只投影 SilentTransitionLabel 诱导子图。
    # 论文对应：Definition 4.6 的 ``->^omega`` 不允许混入时间迁移。
    def test_timed_cycle_is_not_livelock(self) -> None:
        """正时间循环不会被静默环检测器误报。"""

        graph = _manual_graph(
            2,
            (
                TypeTransition(0, 1, TimedTransitionLabel(1, ()), (_TIME_DERIVATION,)),
                TypeTransition(1, 0, TimedTransitionLabel(1, ()), (_TIME_DERIVATION,)),
            ),
        )

        report = analyze_lock_freedom(graph)

        self.assertTrue(report.lock_free)
        self.assertIsNone(report.livelock_witness)

    # 测试输入：S0 经 tau 到 S1；S1 有非空-ready无限边，并与 S2 构成两边 tau 环。
    # 预期行为：同一报告同时给出非空死锁前缀和完整的多结点活锁环。
    # 检查内容：BFS/DFS 父边逆向重建顺序正确，两个性质不会互相短路。
    # 论文对应：Definition 4.7 的 LF 同时要求 Definition 4.5 与 4.6 均不成立。
    def test_deadlock_and_multistate_livelock_witnesses_coexist(self) -> None:
        """非初始死锁和两结点静默环可在一次分析中同时报告。"""

        ready = (ReadyAction("ch", CommunicationDirection.INPUT),)
        graph = _manual_graph(
            3,
            (
                TypeTransition(0, 1, SilentTransitionLabel(), (_TAU_DERIVATION,)),
                TypeTransition(
                    1,
                    1,
                    TimedTransitionLabel(InfiniteTime.VALUE, ready),
                    (_TIME_DERIVATION,),
                ),
                TypeTransition(1, 2, SilentTransitionLabel(), (_TAU_DERIVATION,)),
                TypeTransition(2, 1, SilentTransitionLabel(), (_TAU_DERIVATION,)),
            ),
        )

        report = analyze_lock_freedom(graph)

        self.assertFalse(report.deadlock_free)
        self.assertFalse(report.livelock_free)
        assert report.deadlock_witness is not None
        assert report.livelock_witness is not None
        self.assertEqual(report.deadlock_witness.prefix.state_ids, (0, 1))
        self.assertEqual(report.livelock_witness.prefix.state_ids, (0, 1))
        self.assertEqual(report.livelock_witness.cycle.state_ids, (1, 2, 1))

    # 测试输入：S1 是从初态不可达的孤立状态。
    # 预期行为：公共接口拒绝把它当第三接口的完整可达闭包，且不返回部分结论。
    # 检查内容：异常 kind/phase 和静默模式；性质为假与图无效保持不同协议。
    # 论文对应：死锁/活锁自由都只量化从初态可达的闭包，闭包来源必须明确。
    def test_unreachable_state_is_incomplete_graph_error(self) -> None:
        """非闭包图产生结构化第四接口异常。"""

        graph = _manual_graph(2, ())

        with self.assertRaises(HCSPTypeLockAnalysisError) as raised:
            analyze_type_lock_freedom(graph)

        self.assertIs(
            raised.exception.kind,
            TypeLockAnalysisErrorKind.INCOMPLETE_GRAPH,
        )
        self.assertEqual(raised.exception.phase, "reachability-validation")

    # 测试输入：把普通字符串作为 graph，并要求 result 输出。
    # 预期行为：抛 invalid-graph 公共异常，打印一次结构化失败且不伪造图规模。
    # 检查内容：Python 参数类型错误进入第四接口专用错误分类而非后端 AttributeError。
    # 论文对应：性质判断的论域是第三接口产生的 TypeTransitionGraph 可达闭包。
    def test_non_graph_input_has_structured_public_error(self) -> None:
        """非法根对象在进入 CSR/BFS 前由门面稳定拒绝。"""

        output = StringIO()

        with self.assertRaises(HCSPTypeLockAnalysisError) as raised:
            analyze_type_lock_freedom("not a graph", output="result", stream=output)

        error = raised.exception
        self.assertIs(error.kind, TypeLockAnalysisErrorKind.INVALID_GRAPH)
        self.assertEqual(error.phase, "input-validation")
        self.assertIsNone(error.state_count)
        self.assertIn("invalid-graph", output.getvalue())
        self.assertIn("不会返回部分性质结论", output.getvalue())

    # 测试输入：同一死锁图分别使用 none/result/full 输出。
    # 预期行为：三种模式返回同一报告；result 给结论，full 还给路径、状态和规则证据。
    # 检查内容：展示详细程度不影响分析，且完整日志不需要重新生成图。
    # 论文对应：反例由可达前缀与违反性质的最终无限等待边组成。
    def test_public_output_modes_preserve_the_report(self) -> None:
        """第四接口三档输出共享唯一分析结果。"""

        graph = build_type_transition_graph(
            InfiniteDelayType(InputType("ch", EmptyType()))
        )
        silent_stream = StringIO()
        result_stream = StringIO()
        full_stream = StringIO()

        silent = analyze_type_lock_freedom(graph, output="none", stream=silent_stream)
        result = analyze_type_lock_freedom(graph, output="result", stream=result_stream)
        full = analyze_type_lock_freedom(graph, output="full", stream=full_stream)

        self.assertIsInstance(silent, LockFreedomReport)
        self.assertEqual(silent, result)
        self.assertEqual(result, full)
        self.assertEqual(silent_stream.getvalue(), "")
        self.assertIn("死锁自由 : 否", result_stream.getvalue())
        self.assertIn("错误终止自由 : 是", result_stream.getvalue())
        self.assertIn("整体行为正确 : 否", result_stream.getvalue())
        self.assertNotIn("witness_states", result_stream.getvalue())
        self.assertIn("deadlock_witness", full_stream.getvalue())
        self.assertIn("witness_states", full_stream.getvalue())
        self.assertIn("P-unrhd-prime", full_stream.getvalue())


class LockFreedomScalabilityTests(unittest.TestCase):
    """验证图分析与第三接口一样不依赖 Python 递归深度。"""

    # 测试输入：12000 个状态的 tau 长链，最后一个状态带 tau 自环。
    # 预期行为：在线性时间内返回完整 12000 边环见证入口，不触发 RecursionError。
    # 检查内容：CSR、BFS、显式栈 DFS 和长前缀重建均处理超过递归上限的规模。
    # 论文对应：有限状态定理允许用图搜索决定活锁；工程实现不得受调用栈限制。
    def test_long_chain_and_cycle_do_not_use_python_recursion(self) -> None:
        """上万状态长路径的活锁分析保持栈安全。"""

        state_count = 12_000
        edges = tuple(
            TypeTransition(
                state_id,
                state_id + 1,
                SilentTransitionLabel(),
                (_TAU_DERIVATION,),
            )
            for state_id in range(state_count - 1)
        ) + (
            TypeTransition(
                state_count - 1,
                state_count - 1,
                SilentTransitionLabel(),
                (_TAU_DERIVATION,),
            ),
        )
        graph = _manual_graph(state_count, edges)

        report = analyze_lock_freedom(graph)

        self.assertEqual(report.reachable_state_count, state_count)
        self.assertFalse(report.livelock_free)
        assert report.livelock_witness is not None
        self.assertEqual(
            len(report.livelock_witness.prefix.transitions),
            state_count - 1,
        )
        self.assertEqual(len(report.livelock_witness.cycle.transitions), 1)


if __name__ == "__main__":
    unittest.main()
