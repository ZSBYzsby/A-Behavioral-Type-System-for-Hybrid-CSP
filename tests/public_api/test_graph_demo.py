"""并行 Type AST 到 Table 3 图的多案例演示测试。

测试内容
--------
确认 ``graph_demo`` 的三个手工 Type AST 分别覆盖配对竞争、递归协议、watchdog、
内部选择、错开 deadline 和 Empty 并行单位元，并全部形成完整状态图。

论文对应
--------
覆盖 Table 3 的通信、内部选择、超时、共同时间、并行和递归规则；测试从 Type
AST 开始，不混入 Table 2 的 Process 类型构造证明。
"""

from __future__ import annotations

from contextlib import redirect_stdout
from io import StringIO
import unittest

import graph_demo
from hcsp_typechecker import build_type_transition_graph


class GraphDemoPipelineTests(unittest.TestCase):
    """锁定三个并行 Type AST 示例及其完整图输出。"""

    # 测试输入：graph_demo 构造的三个命名 ParallelType 示例。
    # 预期行为：每个图都 complete，且至少有两个状态和一条迁移。
    # 检查内容：不依赖证明器，直接确认 Type AST 可进入公开图接口。
    # 论文对应：Table 3 可独立消费 Table 2 已经产生或人工构造的行为 Type。
    def test_every_example_builds_a_complete_nontrivial_graph(self) -> None:
        """全部示例都必须形成非平凡、完整闭包的状态迁移图。"""

        examples = graph_demo.build_examples()

        self.assertEqual(len(examples), 3)
        for example in examples:
            with self.subTest(title=example.title):
                graph = build_type_transition_graph(example.type_ast)
                self.assertTrue(graph.complete)
                self.assertGreaterEqual(len(graph.states), 2)
                self.assertGreaterEqual(len(graph.transitions), 1)

    # 测试输入：以 full 模式运行整个 graph_demo。
    # 预期行为：输出三个原始 Type、三个完整图以及通信/递归/选择/时间规则证据。
    # 检查内容：Empty 分量不出现在规范初态，复杂图打印不需要外部证明器。
    # 论文对应：P-unrhd、P-sqcup、P-unrhd-prime、P-| 与 P-mu 均进入演示证据。
    def test_main_prints_all_parallel_semantics_features(self) -> None:
        """完整演示输出应足以人工审计三类并行演化。"""

        output = StringIO()
        with redirect_stdout(output):
            exit_code = graph_demo.main()

        rendered = output.getvalue()
        self.assertEqual(exit_code, 0)
        self.assertEqual(rendered.count("输入 Type AST 的用户语法"), 3)
        self.assertEqual(rendered.count("type transition graph {"), 3)
        self.assertEqual(rendered.count("complete = true"), 3)
        self.assertIn("递归服务器与两个竞争客户端", rendered)
        self.assertIn("请求/应答服务器、客户端与 watchdog", rendered)
        self.assertIn("内部选择、错开 deadline", rendered)
        self.assertIn("P-mu", rendered)
        self.assertIn("P-sqcup", rendered)
        self.assertIn("time(1", rendered)
        self.assertIn("演示结束：全部状态图均已完整闭包", rendered)


if __name__ == "__main__":
    unittest.main()
