"""单样例 03：输入后立即输出同一值的顺序通信。

测试内容：验证 ``in?x; out!x`` 的通信前缀嵌套和输入绑定作用域。
预期结果：``InputType('in', OutputType('out', EndType()))``。
论文对应：Section 2.1 的顺序进程以及 Table 2 的 T-In、T-Out。
"""

import unittest

from hcsp_typechecker import (
    BasicType,
    ChannelType,
    EndType,
    InputChannel,
    InputType,
    OutputChannel,
    OutputType,
    Sequence,
)
from test2._support import assert_conversion, check_process


class InputOutputSequenceExample(unittest.TestCase):
    """检查输入引入的新鲜变量能在后继输出中使用。"""

    # 测试输入：空 Gamma，两个 Int 单槽通道，以及进程 in?x; out!x。
    # 预期行为：x 由 T-In 加入局部环境，随后通过 out 输出，得到两层类型前缀。
    # 预期类型：InputType("in", OutputType("out", EndType()))。
    # 检查内容：输入/输出顺序、终止后继和 T-Out refinement 证明义务。
    # 论文对应：Table 2 的 T-In/T-Out 与输入绑定变量的顺序作用域。
    def test_input_then_output_builds_nested_prefixes(self) -> None:
        """输入和输出应按程序顺序嵌套到 Type AST。"""

        process = Sequence.of(InputChannel("in", "x"), OutputChannel("out", "x"))
        report = check_process(
            process,
            theta={
                "in": ChannelType(BasicType.INT),
                "out": ChannelType(BasicType.INT),
            },
        )
        expected = InputType("in", OutputType("out", EndType()))
        assert_conversion(self, report, expected, obligation_rules=("T-Out",))


if __name__ == "__main__":
    unittest.main()
