"""单样例 18：输入/输出通信守卫的简单递归协议。

测试内容：验证 ``mu X.(tick?u; ack!u; X)`` 的递归类型生成。
预期结果：``mu T.(tick?.ack!.T)``，递归变量正确绑定而不是 EndType。
论文对应：Assumption 2.2、Table 2 的 T-mu/T-X/T-In/T-Out。
"""

import unittest

from hcsp_typechecker import (
    BasicType,
    ChannelType,
    InputChannel,
    InputType,
    Mu,
    MuType,
    OutputChannel,
    OutputType,
    Sequence,
    TypeVar,
    Var,
)
from test2._support import assert_conversion, check_process


class SimpleRecursionExample(unittest.TestCase):
    """检查通信守卫回边到 MuType/TypeVar 的对应。"""

    # 测试输入：每轮 tick?u 后 ack!u，然后回到受 mu 绑定的 X。
    # 预期行为：X 转成同一 MuType 绑定的 TypeVar，输入和输出前缀均在回边之前。
    # 预期类型：MuType("T", InputType("tick", OutputType("ack", TypeVar("T"))))。
    # 检查内容：alpha 稳定的递归 Type AST 以及 T-mu、T-X 证明义务。
    # 论文对应：通信保护 recursive type ``mu t.T`` 与 X 的边界不变量判断。
    def test_guarded_protocol_converts_to_recursive_behavior_type(self) -> None:
        """合法通信守卫递归应生成 MuType。"""

        process = Mu(
            "X",
            Sequence.of(
                InputChannel("tick", "u"),
                OutputChannel("ack", "u"),
                Var("X"),
            ),
        )
        integer = ChannelType(BasicType.INT)
        report = check_process(process, theta={"tick": integer, "ack": integer})
        expected = MuType(
            "T",
            InputType("tick", OutputType("ack", TypeVar("T"))),
        )
        assert_conversion(
            self,
            report,
            expected,
            obligation_rules=("T-mu", "T-X"),
        )


if __name__ == "__main__":
    unittest.main()
