"""单样例 13：有限 ODE 同时具有通信分支和自然到时后继。

测试内容：验证 alarm 中断与 done 公共 tail 组合为完整定时外部选择。
预期结果：``TimedExternalChoiceType(1, alarm!.done!.0, done!.0)``。
论文对应：Table 2 第二条有限 T-unrhd-prime 规则。
"""

import unittest

from hcsp_typechecker import (
    BasicType,
    ChannelType,
    EndType,
    EventChoice,
    ODE,
    ODEAnnotation,
    OutputChannel,
    OutputType,
    Sequence,
    Skip,
    TimedExternalChoiceType,
)
from test2._support import assert_conversion, check_process


class TimedODEFallbackExample(unittest.TestCase):
    """检查通信中断和正常到时两条 continuation 不被混淆。"""

    # 测试输入：x'=1、x<1、delay=1、alarm!0 中断，ODE 后统一执行 done!0。
    # 预期行为：通信分支先 alarm 再 done；自然到时分支直接 done。
    # 预期类型：TimedExternalChoiceType(
    #     1, OutputType("alarm", OutputType("done", EndType())), OutputType("done", EndType()))。
    # 检查内容：TimedExternalChoiceType 的 choices/fallback 和 boundary 义务。
    # 论文对应：完整 delay(d) \\unrhd A \\triangleright T 产生式。
    def test_event_and_natural_exit_form_timed_external_choice(self) -> None:
        """有限 ODE 的通信路径和自然结束路径应分别保留。"""

        evolution = ODE(
            [("x", 1)],
            "x < 1",
            EventChoice.of((OutputChannel("alarm", 0), Skip())),
            annotation=ODEAnnotation(safety="x <= 1", delay=1),
        )
        process = Sequence.of(evolution, OutputChannel("done", 0))
        integer = ChannelType(BasicType.INT)
        report = check_process(
            process,
            gamma={"x": BasicType.REAL},
            theta={"alarm": integer, "done": integer},
            state={"x": 0},
            path_condition="x == 0",
        )
        expected = TimedExternalChoiceType(
            1,
            OutputType("alarm", OutputType("done", EndType())),
            OutputType("done", EndType()),
        )
        assert_conversion(
            self,
            report,
            expected,
            obligation_rules=("T-ODE-safety", "T-ODE-boundary"),
        )


if __name__ == "__main__":
    unittest.main()
