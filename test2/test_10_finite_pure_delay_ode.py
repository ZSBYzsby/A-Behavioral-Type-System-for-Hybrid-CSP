"""单样例 10：有限、无通信 ODE 到纯 delay 类型的转换。

测试内容：验证 ``x'=1 & x<1`` 在 delay=1 后自然进入 skip。
预期结果：``PureDelayType(1, EndType())``，并生成 safety/boundary dL 义务。
论文对应：Table 2 有自然后继的有限 ODE 规则。
"""

import unittest

from hcsp_typechecker import (
    BasicType,
    EndType,
    ODE,
    ODEAnnotation,
    PureDelayType,
    Sequence,
    Skip,
)
from test2._support import assert_conversion, check_process


class FinitePureDelayODEExample(unittest.TestCase):
    """检查无通信事件分支的有限连续演化。"""

    # 测试输入：x:Real，x'=1，B 为 x<1，safety 为 x<=1，delay=1，后继 skip。
    # 预期行为：空 angelic choice 与有限自然后继规范成 delay(1).0。
    # 预期类型：PureDelayType(1, EndType())。
    # 检查内容：PureDelayType 以及 T-ODE-safety、T-ODE-boundary 义务来源。
    # 论文对应：Table 2 的有限 T-unrhd-prime 和 delay(d).T 缩写。
    def test_finite_ode_without_events_becomes_pure_delay(self) -> None:
        """有限无中断 ODE 应生成带正常后继的纯 delay 类型。"""

        process = Sequence.of(
            ODE(
                [("x", 1)],
                "x < 1",
                annotation=ODEAnnotation(safety="x <= 1", delay=1),
            ),
            Skip(),
        )
        report = check_process(
            process,
            gamma={"x": BasicType.REAL},
            state={"x": 0},
            path_condition="x == 0",
        )
        assert_conversion(
            self,
            report,
            PureDelayType(1, EndType()),
            obligation_rules=("T-ODE-safety", "T-ODE-boundary"),
        )


if __name__ == "__main__":
    unittest.main()
