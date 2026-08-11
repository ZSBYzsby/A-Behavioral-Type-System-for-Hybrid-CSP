r"""Table 3 状态迁移图的稳定只读输出测试。

测试内容
--------
1. 时间边输出精确时长、稳定排序的 ready set 与嵌套规则证据。
2. 通信边输出 tau、端点、信道以及分量/分支索引。
3. 截断图输出不完整标记和截断原因。
4. 输出子包拒绝错误对象，并且有意不提供 parser。

论文对应
--------
覆盖 Table 3 状态、无时边、时间边、ready set 及推导证据的展示协议；不增加新的
操作语义规则，也不执行任何图上性质分析。
"""

from __future__ import annotations

import unittest

import hcsp_typechecker.frontend.type_transition_graph_syntax as graph_syntax
from hcsp_typechecker.backend.type_operational_semantics import (
    build_type_transition_graph,
)
from hcsp_typechecker.data_structures.type_ast import (
    EmptyType,
    FiniteDelayType,
    InfiniteDelayType,
    InputType,
    InternalChoiceType,
    NoInterruptType,
    OutputType,
    ParallelType,
)
from hcsp_typechecker.frontend.type_transition_graph_syntax import (
    format_type_transition_graph,
)


class TypeTransitionGraphSerializerTests(unittest.TestCase):
    """锁定状态图全部领域字段的稳定、可审计文本形式。"""

    # 测试输入：剩余时延 2/5、ready 动作 left?/right! 的两个并行分量。
    # 预期行为：首条时间边写成 time(2, ready={left?, right!}) 并列出并行规则前提。
    # 检查内容：有理时长、ready 排序、P-parallel 和两个 P-unrhd-prime 证据。
    # 论文对应：Table 3 [P-|] 组合两个 [P-unrhd'] 时间前提。
    def test_timed_edge_and_nested_rule_evidence_are_rendered(self) -> None:
        """时间边完整输出标签与嵌套规则证据。"""

        graph = build_type_transition_graph(
            ParallelType(
                (
                    FiniteDelayType(
                        2,
                        InputType("left", EmptyType()),
                        EmptyType(),
                    ),
                    FiniteDelayType(
                        5,
                        OutputType("right", EmptyType()),
                        EmptyType(),
                    ),
                )
            )
        )

        rendered = format_type_transition_graph(graph)

        self.assertIn("S0 -- time(2, ready={left?, right!}) --> S1 by {", rendered)
        self.assertIn(
            "\n".join(
                (
                    "            P-parallel(components=[0, 1]) {",
                    "                P-unrhd-prime()",
                    "                P-unrhd-prime()",
                    "            }",
                )
            ),
            rendered,
        )
        self.assertIn("S0 = normalized type parallel {", rendered)

    # 测试输入：无穷 ch? 与 ch! 两个分量，可立即同步且没有共同时间边。
    # 预期行为：图输出 tau 边和 P-unrhd 的分量、分支、信道参数。
    # 检查内容：通信标签不伪装成时间，审计证据保留具体匹配来源。
    # 论文对应：Table 3 [P-unrhd] 在任意互补并行分量之间执行通信。
    def test_communication_edge_exposes_matching_witness(self) -> None:
        """通信边以 tau 和带信道的规则实例输出。"""

        graph = build_type_transition_graph(
            ParallelType(
                (
                    InfiniteDelayType(InputType("ch", EmptyType())),
                    InfiniteDelayType(OutputType("ch", EmptyType())),
                )
            )
        )

        rendered = format_type_transition_graph(graph)

        self.assertIn("S0 -- tau --> S1 by {", rendered)
        self.assertIn(
            "P-unrhd(components=[0, 1], branches=[0, 0], channel='ch')",
            rendered,
        )
        self.assertNotIn("time(", rendered)

    # 测试输入：三分支内部选择和 max_states=1 的显式状态上限。
    # 预期行为：输出 complete=false 与精确截断原因，且仍包含初态规范类型。
    # 检查内容：部分图不能通过展示文本伪装成完整闭包。
    # 论文对应：截断属于工程资源边界，不改变 Table 3 本身。
    def test_truncated_graph_declares_incompleteness(self) -> None:
        """图规模上限在输出头部留下机器无关的明显标记。"""

        graph = build_type_transition_graph(
            InternalChoiceType(
                (
                    FiniteDelayType(1, NoInterruptType(), EmptyType()),
                    FiniteDelayType(2, NoInterruptType(), EmptyType()),
                    FiniteDelayType(3, NoInterruptType(), EmptyType()),
                )
            ),
            max_states=1,
        )

        rendered = format_type_transition_graph(graph)

        self.assertIn("complete = false", rendered)
        self.assertIn("truncation = 'maximum state count 1 reached'", rendered)
        self.assertIn("S0 = normalized type internal {", rendered)

    # 测试输入：原 Type AST 而非图，以及 graph syntax 子包导出命名空间。
    # 预期行为：错误对象抛 TypeError；子包仅导出 formatter，不存在 parse 函数。
    # 检查内容：状态图语法保持输出单向边界。
    # 论文对应：Table 3 图由后端生成，不从未经验证的用户图文本恢复。
    def test_graph_output_is_deliberately_one_way(self) -> None:
        """整图 formatter 不接受 Type AST 且没有反向 parser。"""

        with self.assertRaises(TypeError):
            format_type_transition_graph(EmptyType())  # type: ignore[arg-type]
        self.assertEqual(
            graph_syntax.__all__,
            ["format_type_transition_graph"],
        )
        self.assertFalse(hasattr(graph_syntax, "parse_type_transition_graph"))


if __name__ == "__main__":
    unittest.main()
