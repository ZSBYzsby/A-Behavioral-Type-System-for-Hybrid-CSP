"""单样例 16：ODE 方程、演化域和安全式读取隐式局部时钟 ``t``。

测试内容：验证 ``x'=2*t`` 不要求用户在 Gamma 中声明或初始化 t。
预期结果：成功生成 ``delay(1).(done!.(0))``，所有 dL 义务含实体化的新鲜时钟。
论文对应：Table 2 有限 ODE 前提中的 ``t=0`` 与 ``dot(t)=1``。
"""

import unittest

from hcsp_typechecker import (
    BasicType,
    ChannelType,
    ContinuousType,
    EndType,
    ODE,
    ODEAnnotation,
    OutputChannel,
    OutputType,
    PureDelayType,
    Sequence,
)
from test2._support import assert_conversion, check_process


class ODEImplicitClockExpressionExample(unittest.TestCase):
    """检查保留名 t 在单个 ODE 内的局部读取语义。"""

    # 测试输入：声明 x:Real 和 ODE vector {x}；ODE 为 x'=2*t、x<1。
    # 预期行为：t 被解释为本 ODE 的隐藏时钟，类型显示为 delay(1).(done!.(0))。
    # 预期类型：PureDelayType(1, OutputType("done", EndType()))。
    # 检查内容：不声明 t 仍可转换，并生成 safety/boundary 两类 dL 义务。
    # 论文对应：有限连续规则自动加入 t=0、t'=1，而 t 不进入用户 Gamma。
    def test_ode_can_read_its_implicit_clock_without_gamma_entry(self) -> None:
        """方程右端直接使用 t 时仍应得到有限纯等待类型。"""

        evolution = ODE(
            [("x", "2 * t")],
            "x < 1",
            annotation=ODEAnnotation(safety="x <= 1", delay=1),
        )
        report = check_process(
            Sequence.of(evolution, OutputChannel("done", 0)),
            gamma={"x": BasicType.REAL, "ode_x": ContinuousType(("x",))},
            theta={"done": ChannelType(BasicType.INT)},
            state={"x": 0},
            path_condition="x == 0",
        )
        expected = PureDelayType(1, OutputType("done", EndType()))
        assert_conversion(
            self,
            report,
            expected,
            obligation_rules=("T-ODE-safety", "T-ODE-boundary"),
        )


if __name__ == "__main__":
    unittest.main()
