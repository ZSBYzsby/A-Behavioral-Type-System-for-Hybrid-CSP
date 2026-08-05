"""单样例 05：条件分支与公共顺序后继的组合。

测试内容：验证 ``if`` 两个分支都连接外层 ``done!0`` 后继。
预期结果：两个通信序列构成 InternalChoiceType，且公共 tail 不丢失。
论文对应：Table 2 的 T-If 与顺序 continuation 推导。
"""

import unittest

from hcsp_typechecker import (
    BasicType,
    ChannelType,
    EndType,
    If,
    InternalChoiceType,
    OutputChannel,
    OutputType,
    Sequence,
)
from test2._support import assert_conversion, check_process


class IfCommonTailExample(unittest.TestCase):
    """检查条件分支对公共 continuation 的传播。"""

    # 测试输入：flag:Bool；then 输出 left，else 输出 right，之后统一输出 done。
    # 预期行为：显示为 (left!.(done!.(0))) sqcup (right!.(done!.(0)))。
    # 预期类型：InternalChoiceType((
    #     OutputType("left", OutputType("done", EndType())),
    #     OutputType("right", OutputType("done", EndType()))))。
    # 检查内容：InternalChoiceType 两分支及每一分支末尾相同的 done 前缀。
    # 论文对应：T-If 的两个 process 子 judgment 和顺序后继类型传递。
    def test_if_branches_both_receive_the_outer_continuation(self) -> None:
        """公共后继必须同时附加到 if 的两个分支。"""

        process = Sequence.of(
            If(
                "flag",
                OutputChannel("left", 0),
                OutputChannel("right", 0),
            ),
            OutputChannel("done", 0),
        )
        integer = ChannelType(BasicType.INT)
        report = check_process(
            process,
            gamma={"flag": BasicType.BOOL},
            theta={"left": integer, "right": integer, "done": integer},
            state={"flag": True},
        )
        expected = InternalChoiceType(
            (
                OutputType("left", OutputType("done", EndType())),
                OutputType("right", OutputType("done", EndType())),
            )
        )
        assert_conversion(self, report, expected)


if __name__ == "__main__":
    unittest.main()
