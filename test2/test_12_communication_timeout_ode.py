"""单样例 12：有限 ODE 通信中断且没有自然后继。

测试内容：验证 delay=2 的 ODE 只提供 ``tick!`` 通信分支。
预期结果：``CommunicationTimeoutType(2, OutputType('tick', EndType()))``。
论文对应：Table 2 第一条有限 T-unrhd 规则及 communication-timeout 缩写。
"""

import unittest

from hcsp_typechecker import (
    BasicType,
    ChannelType,
    CommunicationTimeoutType,
    EndType,
    EventChoice,
    ODE,
    ODEAnnotation,
    OutputChannel,
    OutputType,
    Skip,
)
from test2._support import assert_conversion, check_process


class CommunicationTimeoutODEExample(unittest.TestCase):
    """检查只有通信中断分支的有限连续行为。"""

    # 测试输入：x'=0、B=true、delay=2，事件为 tick!0 -> skip，无顺序后继。
    # 预期行为：有限时间内可输出 tick；若直到 d 仍未通信则进入 bottom。
    # 预期类型：CommunicationTimeoutType(2, OutputType("tick", EndType()))。
    # 检查内容：CommunicationTimeoutType、输出 choice 和 T-ODE-domain 义务。
    # 论文对应：delay(d) \\unrhd A := delay(d) \\unrhd A \\triangleright bottom。
    def test_finite_event_only_ode_becomes_communication_timeout(self) -> None:
        """没有自然后继的有限事件 ODE 应使用通信超时类型。"""

        process = ODE(
            [("x", 0)],
            True,
            EventChoice.of((OutputChannel("tick", 0), Skip())),
            annotation=ODEAnnotation(delay=2),
        )
        report = check_process(
            process,
            gamma={"x": BasicType.REAL},
            theta={"tick": ChannelType(BasicType.INT)},
        )
        expected = CommunicationTimeoutType(2, OutputType("tick", EndType()))
        assert_conversion(
            self,
            report,
            expected,
            obligation_rules=("T-ODE-domain",),
        )


if __name__ == "__main__":
    unittest.main()
