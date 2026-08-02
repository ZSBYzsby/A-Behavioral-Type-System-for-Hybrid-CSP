"""多标量同步通信的 Process -> Type 专项测试。

测试内容
--------

1. ``ch?(x1,...,xn)`` 一次建立多个独立标量绑定，并假设联合 refinement；
2. ``ch!(e1,...,en)`` 逐槽检查 BasicType，并证明联合 refinement；
3. 输入、输出参数数量必须与 ``Theta(ch)`` 的槽位元数完全一致；
4. 每个槽位独立报告类型错误，不把整组通信载荷当作 TupleType；
5. 并行的一入一出共享同一多槽签名，但行为类型仍只记录一次 ch?/ch!。

论文对应
--------

这些测试覆盖协作者确认的 T-In/T-Out 多标量扩展：通道签名从一个 ``B`` 扩展为
``B1,...,Bn``，普通变量与表达式结果仍分别只有一个 ``BasicType``。行为类型
继续抽象为 ``ch?.T``/``ch!.T``，通信元数和联合 refinement 只保存在 Theta。
"""

from __future__ import annotations

import unittest

from hcsp_typechecker import (
    Assert,
    BasicType,
    ChannelType,
    Configuration,
    EndType,
    InputChannel,
    InputType,
    OutputChannel,
    OutputType,
    Parallel,
    ParallelType,
    Sequence,
    Verdict,
    check_hcsp,
    types_equivalent,
)


class MultiScalarCommunicationTests(unittest.TestCase):
    """验证多槽通信的环境更新、证明义务和行为类型抽象。"""

    # 测试输入：data?(x,ready) 后断言 x>=0 and ready，Theta 给出同一联合精化。
    # 预期行为：两个输入目标分别进入 Gamma，断言可由输入 refinement 证明。
    # 检查内容：核对 true、InputType 以及 T-Assert 证明义务。
    # 论文对应：扩展 T-In 同时执行 phi{x/eta1,ready/eta2}。
    def test_multi_input_binds_each_scalar_and_assumes_joint_refinement(self) -> None:
        """联合输入 refinement 应同时约束全部新接收标量。"""

        process = Sequence.of(
            InputChannel("data", ("x", "ready")),
            Assert("x >= 0 and ready"),
        )
        report = check_hcsp(
            gamma={},
            theta={
                "data": ChannelType(
                    (BasicType.INT, BasicType.BOOL),
                    "eta1 >= 0 and eta2",
                )
            },
            configurations=[Configuration({}, process)],
        )

        self.assertEqual(report.verdict, Verdict.TRUE)
        self.assertTrue(
            types_equivalent(report.inferred_type, InputType("data", EndType()))
        )
        self.assertIn("T-Assert", {item.rule for item in report.obligations})

    # 测试输入：路径 x<limit 下经 pair!(x,limit) 输出，refinement 是二元 callable。
    # 预期行为：两个 Int 槽位分别通过检查，联合精化证明为 true。
    # 检查内容：核对 OutputType 和 T-Out 证明义务结论。
    # 论文对应：扩展 T-Out 同时执行 phi{x/left,limit/right}。
    def test_multi_output_proves_callable_joint_refinement(self) -> None:
        """多参数 refinement callable 应按槽位顺序接收全部输出项。"""

        report = check_hcsp(
            gamma={"x": BasicType.INT, "limit": BasicType.INT},
            theta={
                "pair": ChannelType(
                    (BasicType.INT, BasicType.INT),
                    lambda left, right: left < right,
                    binders=("left", "right"),
                )
            },
            path_condition="x < limit",
            configurations=[
                Configuration(
                    {"x": 1, "limit": 2},
                    OutputChannel("pair", ("x", "limit")),
                )
            ],
        )

        self.assertEqual(report.verdict, Verdict.TRUE)
        self.assertTrue(
            types_equivalent(report.inferred_type, OutputType("pair", EndType()))
        )
        t_out = [item for item in report.obligations if item.rule == "T-Out"]
        self.assertEqual(len(t_out), 1)
        self.assertEqual(t_out[0].verdict, Verdict.TRUE)

    # 测试输入：二槽通道分别用于单目标输入和三表达式输出。
    # 预期行为：T-In/T-Out 都返回 false 且不产生候选行为类型。
    # 检查内容：分别核对期望元数与实际 targets/expressions 数量诊断。
    # 论文对应：扩展通信的 x/e 参数表必须与 Theta(ch) 的 B 列表等长。
    def test_input_and_output_arity_must_match_channel_signature(self) -> None:
        """通信参数数量与通道签名不一致时不能执行 refinement 替换。"""

        channel = ChannelType((BasicType.INT, BasicType.BOOL))
        reports = (
            check_hcsp(
                gamma={},
                theta={"data": channel},
                configurations=[Configuration({}, InputChannel("data", "x"))],
            ),
            check_hcsp(
                gamma={},
                theta={"data": channel},
                configurations=[
                    Configuration({}, OutputChannel("data", (1, True, 2)))
                ],
            ),
        )

        expected_fragments = ("got 1 targets", "got 3 expressions")
        for report, fragment in zip(reports, expected_fragments):
            with self.subTest(fragment=fragment):
                self.assertEqual(report.verdict, Verdict.FALSE)
                self.assertIsNone(report.inferred_type)
                self.assertTrue(
                    any(fragment in item.message for item in report.diagnostics)
                )

    # 测试输入：mixed!(true,1) 对应通道签名 (Int,Bool)。
    # 预期行为：两个槽位分别报告 Bool->Int 与 Nat->Bool 不兼容，总体 false。
    # 检查内容：诊断必须带 slot 1/2，推导仍只生成一次 OutputType 动作。
    # 论文对应：多标量扩展逐个检查 Gamma·phi |- ei:Bi，不合并成 tuple 判断。
    def test_each_output_slot_is_type_checked_independently(self) -> None:
        """交换槽位类型不能被整个参数表的外层形状掩盖。"""

        report = check_hcsp(
            gamma={},
            theta={
                "mixed": ChannelType((BasicType.INT, BasicType.BOOL))
            },
            configurations=[
                Configuration({}, OutputChannel("mixed", (True, 1)))
            ],
        )

        self.assertEqual(report.verdict, Verdict.FALSE)
        self.assertTrue(
            types_equivalent(report.inferred_type, OutputType("mixed", EndType()))
        )
        messages = tuple(item.message for item in report.diagnostics)
        self.assertTrue(any("slot 1 expects Int, got Bool" in text for text in messages))
        self.assertTrue(any("slot 2 expects Bool, got Nat" in text for text in messages))

    # 测试输入：同一 pair 通道上的 pair?(x,y) 与 pair!(1,2) 并行。
    # 预期行为：共享二槽 Theta 签名后整体 true，类型为一个输入和一个输出分量。
    # 检查内容：确认载荷元数不复制进 InputType/OutputType，仍是一次同步动作。
    # 论文对应：组合规则保留通信拓扑，连续/值数据细节由 Gamma/Theta 消解。
    def test_parallel_multi_input_and_output_keep_one_behavior_action(self) -> None:
        """多标量同步不改变行为类型层的通信动作数量。"""

        system = Parallel(
            InputChannel("pair", ("x", "y")),
            OutputChannel("pair", (1, 2)),
        )
        report = check_hcsp(
            gamma={},
            theta={
                "pair": ChannelType((BasicType.INT, BasicType.INT))
            },
            configurations=[Configuration({}, system)],
        )
        expected = ParallelType(
            (
                InputType("pair", EndType()),
                OutputType("pair", EndType()),
            )
        )

        self.assertEqual(report.verdict, Verdict.TRUE)
        self.assertTrue(types_equivalent(report.inferred_type, expected))


if __name__ == "__main__":
    unittest.main()
