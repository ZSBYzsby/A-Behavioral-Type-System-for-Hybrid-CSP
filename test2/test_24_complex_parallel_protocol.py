"""单样例 24：双端握手协议的并行、条件和内部选择组合。

测试内容：左端接收 control 后回复 ack/reject；右端发送 control 后等待其一。
预期结果：两个协议端分别生成嵌套类型，再组合为 ParallelType。
论文对应：Assumption 2.1 的并行分区与 T-In/T-Out/T-If/T-sqcup/T-parallel。
"""

import unittest

from hcsp_typechecker import (
    BasicType,
    ChannelType,
    EndType,
    If,
    InputChannel,
    InputType,
    InternalChoice,
    InternalChoiceType,
    OutputChannel,
    OutputType,
    Parallel,
    ParallelType,
    Sequence,
)
from test2._support import assert_conversion, check_process


class ComplexParallelProtocolExample(unittest.TestCase):
    """检查方向互补通道上的复合并行协议。"""

    # 测试输入：左端 control?u 后按符号输出 ack/reject；右端 control!1 后内部选择
    #           ack?v 或 reject?w，两个分量变量互不共享且通道方向互补。
    # 预期行为：左分量为输入后内部选择输出，右分量为输出后内部选择输入。
    # 预期类型：ParallelType((InputType("control", InternalChoiceType((
    #     OutputType("ack", EndType()), OutputType("reject", EndType())))), OutputType("control",
    #     InternalChoiceType((InputType("ack", EndType()), InputType("reject", EndType()))))))。
    # 检查内容：ParallelType 分量、四类通信前缀及两层 InternalChoiceType。
    # 论文对应：T-parallel 与 Assumption 2.1 的 V/iCh/oCh 分离条件。
    def test_bidirectional_protocol_converts_to_two_component_type(self) -> None:
        """合法同步协议应保留每一端各自的行为结构。"""

        left = Sequence.of(
            InputChannel("control", "u"),
            If(
                "u >= 0",
                OutputChannel("ack", "u"),
                OutputChannel("reject", 0),
            ),
        )
        right = Sequence.of(
            OutputChannel("control", 1),
            InternalChoice(
                InputChannel("ack", "v"),
                InputChannel("reject", "w"),
            ),
        )
        integer = ChannelType(BasicType.INT)
        report = check_process(
            Parallel(left, right),
            theta={"control": integer, "ack": integer, "reject": integer},
        )
        expected_left = InputType(
            "control",
            InternalChoiceType(
                (OutputType("ack", EndType()), OutputType("reject", EndType()))
            ),
        )
        expected_right = OutputType(
            "control",
            InternalChoiceType(
                (InputType("ack", EndType()), InputType("reject", EndType()))
            ),
        )
        assert_conversion(
            self,
            report,
            ParallelType((expected_left, expected_right)),
            obligation_rules=("T-Out",),
        )


if __name__ == "__main__":
    unittest.main()
