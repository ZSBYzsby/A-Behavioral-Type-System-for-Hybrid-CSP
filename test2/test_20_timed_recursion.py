"""单样例 20：wait、输出和递归回边的复合行为。

测试内容：验证 ``mu X.(wait(1); tick!0; X)`` 的类型嵌套。
预期结果：``mu T.(delay(1).tick!.T)``，wait 本身不充当通信守卫。
论文对应：有限 ODE 类型规则、T-Out、T-mu/T-X 和 Assumption 2.2。
"""

import unittest

from hcsp_typechecker import (
    BasicType,
    ChannelType,
    Mu,
    MuType,
    ODE,
    OutputChannel,
    OutputType,
    PureDelayType,
    Sequence,
    TypeVar,
    Var,
)
from test2._support import assert_conversion, check_process


class TimedRecursionExample(unittest.TestCase):
    """检查连续 delay 与通信守卫递归的顺序组合。"""

    # 测试输入：每轮先 wait(1)，再 tick!0，最后回到 X。
    # 预期行为：PureDelayType 包住输出前缀；回边由 tick 输出而非 wait 保护。
    # 预期类型：MuType("T", PureDelayType(1, OutputType("tick", TypeVar("T"))))。
    # 检查内容：MuType/PureDelayType/OutputType/TypeVar 四层结构及 ODE/T-X 义务。
    # 论文对应：delay(d).T 与通信守卫 recursive type 的正交组合。
    def test_wait_then_output_then_recursion_builds_timed_mu_type(self) -> None:
        """合法的定时递归循环应保留 delay 和通信前缀。"""

        process = Mu(
            "X",
            Sequence.of(ODE.wait(1), OutputChannel("tick", 0), Var("X")),
        )
        report = check_process(
            process,
            theta={"tick": ChannelType(BasicType.INT)},
        )
        expected = MuType(
            "T",
            PureDelayType(1, OutputType("tick", TypeVar("T"))),
        )
        assert_conversion(
            self,
            report,
            expected,
            obligation_rules=("T-ODE-boundary", "T-X"),
        )


if __name__ == "__main__":
    unittest.main()
