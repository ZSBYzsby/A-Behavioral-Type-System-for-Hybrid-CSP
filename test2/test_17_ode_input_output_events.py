"""单样例 17：ODE 的输入/输出事件选择、有限 fallback 和公共 tail。

测试内容：组合输入 reset、输出 alarm、连续演化和结束后的 done 输出。
预期结果：TimedExternalChoiceType，choices 为两分支 ExternalChoiceType。
论文对应：事件 E、T-In/T-Out、T-cap 和有限 T-unrhd-prime 的组合。
"""

import unittest

from hcsp_typechecker import (
    BasicType,
    ChannelType,
    ContinuousType,
    EndType,
    EventChoice,
    ExternalChoiceType,
    InputChannel,
    InputType,
    ODE,
    ODEAnnotation,
    OutputChannel,
    OutputType,
    Sequence,
    Skip,
    TimedExternalChoiceType,
)
from test2._support import assert_conversion, check_process


class ODEInputOutputEventsExample(unittest.TestCase):
    """检查异向、多分支 ODE 中断的复杂类型结构。"""

    # 测试输入：x'=1、x<1、d=1；reset?y/alarm!x 两事件；外层 done!x。
    # 预期行为：两个事件 continuation 都接 done；自然到时也接 done。
    # 预期类型：TimedExternalChoiceType(1, ExternalChoiceType((
    #     InputType("reset", OutputType("done", EndType())),
    #     OutputType("alarm", OutputType("done", EndType())))), OutputType("done", EndType()))。
    # 检查内容：TimedExternalChoiceType、ExternalChoiceType、Input/Output 三层组合。
    # 论文对应：T-cap 组合事件子判断，再由 T-unrhd-prime 加有限 fallback。
    def test_mixed_ode_events_and_tail_build_full_timed_type(self) -> None:
        """输入/输出事件和自然结束应形成完整且分支明确的定时类型。"""

        evolution = ODE(
            [("x", 1)],
            "x < 1",
            EventChoice.of(
                (InputChannel("reset", "y"), Skip()),
                (OutputChannel("alarm", "x"), Skip()),
            ),
            annotation=ODEAnnotation(safety="x <= 1", delay=1),
        )
        real = ChannelType(BasicType.REAL)
        report = check_process(
            Sequence.of(evolution, OutputChannel("done", "x")),
            gamma={"x": ContinuousType()},
            theta={"reset": real, "alarm": real, "done": real},
            state={"x": 0},
            path_condition="x == 0",
        )
        done = OutputType("done", EndType())
        choices = ExternalChoiceType(
            (
                InputType("reset", done),
                OutputType("alarm", done),
            )
        )
        expected = TimedExternalChoiceType(1, choices, done)
        assert_conversion(
            self,
            report,
            expected,
            obligation_rules=("T-ODE-boundary", "T-Out"),
        )


if __name__ == "__main__":
    unittest.main()
