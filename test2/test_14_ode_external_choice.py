"""单样例 14：ODE 中两个事件分支到外部选择类型。

测试内容：验证 ``left!``/``right!`` 两个可由环境触发的中断分支。
预期结果：CommunicationTimeoutType 的 choices 是 ExternalChoiceType。
论文对应：事件反应 E 的 Box 选择、T-cap 与有限 T-unrhd。
"""

import unittest

from hcsp_typechecker import (
    BasicType,
    ChannelType,
    CommunicationTimeoutType,
    ContinuousType,
    EndType,
    EventChoice,
    ExternalChoiceType,
    ODE,
    ODEAnnotation,
    OutputChannel,
    OutputType,
    Skip,
)
from test2._support import assert_conversion, check_process


class ODEExternalChoiceExample(unittest.TestCase):
    """检查多个 ODE 中断通信被规范为 angelic external choice。"""

    # 测试输入：x'=0、B=true、delay=2，事件分别为 left!0 和 right!0。
    # 预期行为：两事件显示为 A=(left!.(0)) cap (right!.(0))，有限超时后继为 bottom。
    # 预期类型：CommunicationTimeoutType(
    #     2, ExternalChoiceType((OutputType("left", EndType()), OutputType("right", EndType()))))。
    # 检查内容：ExternalChoiceType 分支次序及外层 CommunicationTimeoutType。
    # 论文对应：A ::= A cap ch!.T 与 delay(d) unrhd A 缩写。
    def test_two_ode_events_form_external_choice_inside_timeout(self) -> None:
        """两个事件分支必须保留为外部选择而非内部选择。"""

        process = ODE(
            [("x", 0)],
            True,
            EventChoice.of(
                (OutputChannel("left", 0), Skip()),
                (OutputChannel("right", 0), Skip()),
            ),
            annotation=ODEAnnotation(delay=2),
        )
        integer = ChannelType(BasicType.INT)
        report = check_process(
            process,
            gamma={"x": BasicType.REAL, "ode_x": ContinuousType(("x",))},
            theta={"left": integer, "right": integer},
        )
        choices = ExternalChoiceType(
            (OutputType("left", EndType()), OutputType("right", EndType()))
        )
        assert_conversion(
            self,
            report,
            CommunicationTimeoutType(2, choices),
            obligation_rules=("T-ODE-domain",),
        )


if __name__ == "__main__":
    unittest.main()
