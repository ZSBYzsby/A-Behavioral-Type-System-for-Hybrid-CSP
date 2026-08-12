"""公开接口的显式工作栈压力回归。

测试内容
--------
验证长顺序 HCSP、深 Type continuation 和深规范化/项图转换不会触发
``RecursionError``，同时仍产生与小程序完全相同的语义结果。

论文对应
--------
这些测试不改变 Table 2/3 规则，只验证规则树的实现深度不受 Python 调用栈限制。
"""

from __future__ import annotations

from io import StringIO
import unittest

from hcsp_typechecker import (
    build_type_transition_graph,
    check_hcsp_type,
    construct_hcsp_type,
)
from hcsp_typechecker._internal import EmptyType, InfiniteDelayType, InputType
from hcsp_typechecker.frontend.type_syntax import (
    format_type_source,
    parse_type_source,
)


class ExplicitWorkStackTests(unittest.TestCase):
    """锁定三个接口的核心深度遍历均使用显式工作栈。"""

    # 测试输入：两千条连续 skip 的完整用户 HCSP source。
    # 预期行为：Constructor 完整解析并构造 EmptyType，不发生 RecursionError。
    # 检查内容：公开接口的返回节点种类以及长 Sequence 的完整消费。
    # 论文对应：重复 T-Skip/T-End 不改变最终空通信行为。
    def test_constructor_handles_two_thousand_sequential_statements(self) -> None:
        """长线性程序通过前端和 Constructor 的显式栈端到端运行。"""

        statements = ";".join("skip" for _ in range(2000))
        source = f"gamma() theta() process {{{{{statements}}}}}"
        constructed = construct_hcsp_type(source, output="none")
        self.assertIsInstance(constructed, EmptyType)
        graph = build_type_transition_graph(constructed, output="none")
        self.assertEqual(len(graph.states), 1)
        self.assertEqual(len(graph.transitions), 0)

    # 测试输入：一百五十层嵌套 if，每层两分支都最终执行 skip。
    # 预期行为：控制语句块前端和 Constructor 都成功，不发生 RecursionError。
    # 检查内容：深嵌套 block/if 的显式任务栈以及最终内部选择类型构造。
    # 论文对应：重复 T-If 的二分支结构保持原有逐层括号语义。
    def test_constructor_handles_deeply_nested_control_blocks(self) -> None:
        """深嵌套控制语句不再依赖递归下降调用深度。"""

        body = "skip"
        for _ in range(150):
            body = f"if(true){{{body}}}else{{skip}}"
        constructed = construct_hcsp_type(
            f"gamma() theta() process {{{{{body}}}}}",
            output="none",
        )
        self.assertIsNotNone(constructed)

    # 测试输入：一千五百层 forever/input continuation 的用户 Type source。
    # 预期行为：Type parser 和 Checker 都完整消费该结构，不发生 RecursionError。
    # 检查内容：先独立解析深 Type，再以两千条 skip 验证 Checker 的线性规则栈。
    # 论文对应：给定 Type 的结构递归与 T-Skip/T-End 判断保持原规则含义。
    def test_type_parser_and_checker_handle_deep_inputs(self) -> None:
        """深 Type 解析与长顺序 Checker 路径均不依赖调用栈。"""

        depth = 1500
        type_source = (
            "type "
            + "forever interrupt angelic {ch? -> " * depth
            + "empty"
            + "}" * depth
        )
        parsed = parse_type_source(type_source)
        self.assertIsInstance(parsed, InfiniteDelayType)

        statements = ";".join("skip" for _ in range(2000))
        checked = check_hcsp_type(
            f"gamma() theta() process {{{{{statements}}}}} type empty",
            output="none",
        )
        self.assertIsInstance(checked, EmptyType)

    # 测试输入：三百层无穷等待/输入 continuation 的正式 Type AST。
    # 预期行为：规范化、循环项图最小化、展示重建与 Table 3 BFS 全部成功。
    # 检查内容：所得可达图保持唯一无限时间自环，而非因实现栈深度失败。
    # 论文对应：递归等价项图上的最大关键时间步语义不受 AST 表示深度影响。
    def test_transition_graph_handles_deep_type_ast(self) -> None:
        """第三接口对深 Type AST 完成规范化和状态图构造。"""

        value = EmptyType()
        for _ in range(300):
            value = InfiniteDelayType(InputType("ch", value))
        graph = build_type_transition_graph(value, max_states=4)
        self.assertEqual(len(graph.states), 1)
        self.assertEqual(len(graph.transitions), 1)

    # 测试输入：赋值右端含一千五百个加法项的完整用户 HCSP source。
    # 预期行为：表达式打印、变量收集和 Z3 翻译均不触发 RecursionError。
    # 检查内容：公开 Constructor 完成赋值规则并得到 EmptyType。
    # 论文对应：T-Assign 的表达式大小不应受 Python 调用栈深度限制。
    def test_constructor_handles_deep_arithmetic_expression(self) -> None:
        """长二元表达式树通过显式后序栈完成公式翻译。"""

        expression = "+".join("1" for _ in range(1500))
        source = f"gamma(x: Int) theta() process {{{{x := {expression}}}}}"
        constructed = construct_hcsp_type(source, output="none")
        self.assertIsInstance(constructed, EmptyType)

    # 测试输入：五百二十层无限时延/输入 continuation，并要求完整图日志。
    # 预期行为：图构造和规范 Type 文本渲染都不触发 RecursionError。
    # 检查内容：FULL 模式返回完整图，且日志含规范 Type 与转移区。
    # 论文对应：Table 3 图的展示不改变深层通信行为及其转移语义。
    def test_transition_graph_full_output_handles_deep_type(self) -> None:
        """第三接口的完整日志与核心图构造使用相同的深度保障。"""

        value = EmptyType()
        for _ in range(520):
            value = InfiniteDelayType(InputType("ch", value))
        stream = StringIO()
        graph = build_type_transition_graph(
            value,
            max_states=4,
            output="full",
            stream=stream,
        )
        self.assertEqual(len(graph.states), 1)
        self.assertIn("normalized type", stream.getvalue())
        self.assertIn("transitions", stream.getvalue())

    # 测试输入：同一份含一百八十次连续通信的完整 HCSP 用户输入。
    # 预期行为：Constructor 的真实输出可直接交给第三接口，且 FULL 日志成功。
    # 检查内容：不手工构造 Type AST，锁定接口一到接口三的共同规模承载链路。
    # 论文对应：Table 2 产生的通信 continuation 是 Table 3 的合法直接输入。
    def test_constructor_output_scale_is_accepted_by_graph_interface(self) -> None:
        """以端到端样例保证第三接口不会比 Constructor 更早栈溢出。"""

        statements = ";".join("ch!(0)" for _ in range(180))
        source = (
            "gamma() theta(ch: channel(value: Int)) "
            f"process {{{{{statements}}}}}"
        )
        constructed = construct_hcsp_type(source, output="none")
        stream = StringIO()
        graph = build_type_transition_graph(
            constructed,
            output="full",
            stream=stream,
        )
        self.assertEqual(len(graph.states), 1)
        self.assertEqual(len(graph.transitions), 1)
        self.assertIn("type transition graph", stream.getvalue())

    # 测试输入：同一份含三百个顶层空并行分量的完整 HCSP 用户输入。
    # 预期行为：Constructor 返回 ParallelType，第三接口接收该结果并得到终止图。
    # 检查内容：并行展平、规范化和 Empty 并行单位元处理使用一致的规模边界。
    # 论文对应：Table 2 的 [T-||] 输出可直接作为 Table 3 配置类型初态。
    def test_parallel_constructor_output_is_accepted_by_graph_interface(self) -> None:
        """大量并行分量沿两个公开接口连续运行且保持空行为语义。"""

        components = ",".join("{skip}" for _ in range(300))
        constructed = construct_hcsp_type(
            f"gamma() theta() process {{{components}}}",
            output="none",
        )
        graph = build_type_transition_graph(constructed, output="none")
        self.assertEqual(len(graph.states), 1)
        self.assertEqual(len(graph.transitions), 0)

    # 测试输入：同一份含一百八十次连续通信的 HCSP 和 Constructor 输出 Type。
    # 预期行为：Type 经正式用户语法序列化后，Checker 在 FULL 模式下验证成功。
    # 检查内容：Constructor→Type 文本→Checker 的完整公开链路承载同一深度。
    # 论文对应：Table 2 构造所得每层通信结论可被相同规则逐层重新验证。
    def test_constructor_output_scale_is_accepted_by_checker(self) -> None:
        """深通信 Type 的构造规模与验证规模通过真实输出保持一致。"""

        statements = ";".join("ch!(0)" for _ in range(180))
        source = (
            "gamma() theta(ch: channel(value: Int)) "
            f"process {{{{{statements}}}}}"
        )
        constructed = construct_hcsp_type(source, output="none")
        stream = StringIO()
        checked = check_hcsp_type(
            source + "\n" + format_type_source(constructed),
            output="full",
            stream=stream,
        )
        self.assertEqual(format_type_source(checked), format_type_source(constructed))
        self.assertIn("HCSP 类型检查完整日志", stream.getvalue())

    # 测试输入：同一份含三百个顶层空并行分量的 HCSP 和 Constructor 输出 Type。
    # 预期行为：Checker 逐分量消费 ParallelType，返回与构造结果相同的 Type。
    # 检查内容：并行 Process 分量、Type 分量和自动配置数量在大输入下仍一一对应。
    # 论文对应：[T-||] 的构造结果可由 Checker 对每个对应分量独立验证。
    def test_parallel_constructor_output_scale_is_accepted_by_checker(self) -> None:
        """大量并行分量的 Constructor 输出可由 Checker 原样验证。"""

        components = ",".join("{skip}" for _ in range(300))
        source = f"gamma() theta() process {{{components}}}"
        constructed = construct_hcsp_type(source, output="none")
        checked = check_hcsp_type(
            source + "\n" + format_type_source(constructed),
            output="none",
        )
        self.assertEqual(format_type_source(checked), format_type_source(constructed))


if __name__ == "__main__":
    unittest.main()
