"""单样例 06：显式内部非确定选择的类型转换。

测试内容：验证两个输出分支组成的 ``P \\sqcup P'``。
预期结果：精确生成包含两个 OutputType 的 InternalChoiceType。
论文对应：Section 2.1 的内部选择与 Table 2 的 T-sqcup。
"""

import unittest

from hcsp_typechecker import (
    BasicType,
    ChannelType,
    EndType,
    InternalChoice,
    InternalChoiceType,
    OutputChannel,
    OutputType,
)
from test2._support import assert_conversion, check_process


class InternalChoiceExample(unittest.TestCase):
    """检查显式内部选择保持两条候选行为。"""

    # 测试输入：left!0 与 right!0 组成二元 InternalChoice。
    # 预期行为：生成两个输出行为的内部选择，而非外部通信选择。
    # 预期类型：InternalChoiceType((OutputType("left", EndType()), OutputType("right", EndType())))。
    # 检查内容：选择节点类别、分支通道名与各自 EndType continuation。
    # 论文对应：T-sqcup 产生 T sqcup T'。
    def test_internal_choice_converts_to_demonic_choice_type(self) -> None:
        """进程内部选择应转换为 InternalChoiceType。"""

        process = InternalChoice(
            OutputChannel("left", 0),
            OutputChannel("right", 0),
        )
        integer = ChannelType(BasicType.INT)
        report = check_process(process, theta={"left": integer, "right": integer})
        expected = InternalChoiceType(
            (OutputType("left", EndType()), OutputType("right", EndType()))
        )
        assert_conversion(self, report, expected)


if __name__ == "__main__":
    unittest.main()
