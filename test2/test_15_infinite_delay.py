"""单样例 15：正无穷 delay 的类型规范化。

测试内容：验证无限等待时不可达的超时 fallback 不保留在 Type AST 中。
预期结果：只留下 ``alarm!.done!.0`` 的 angelic 通信行为。
论文对应：``A := delay(infinity) \\unrhd A \\triangleright bottom`` 定义式。
"""

from math import inf
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
)
from test2._support import assert_conversion, check_process


class InfiniteDelayExample(unittest.TestCase):
    """检查无限 ODE 只保留可达通信 continuation。"""

    # 测试输入：x'=0、B=true、delay=infinity、alarm 事件，外层 tail 为 done!0。
    # 预期行为：自然超时永不发生；alarm 中断后仍进入外层 done continuation。
    # 预期类型：OutputType("alarm", OutputType("done", EndType()))。
    # 检查内容：结果是 OutputType 链且不含任何有限 delay 类型节点。
    # 论文对应：无限 delay 的 A 缩写及不可达 timeout continuation 规范化。
    def test_infinite_delay_discards_unreachable_timeout_fallback(self) -> None:
        """无限时延应返回 angelic choice，并保留事件发生后的公共 tail。"""

        evolution = ODE(
            [("x", 0)],
            True,
            EventChoice.of((OutputChannel("alarm", 0), Skip())),
            annotation=ODEAnnotation(delay=inf),
        )
        integer = ChannelType(BasicType.INT)
        report = check_process(
            Sequence.of(evolution, OutputChannel("done", 0)),
            gamma={"x": BasicType.REAL},
            theta={"alarm": integer, "done": integer},
            state={"x": 0},
        )
        expected = OutputType("alarm", OutputType("done", EndType()))
        assert_conversion(
            self,
            report,
            expected,
            obligation_rules=("T-ODE-domain",),
        )


if __name__ == "__main__":
    unittest.main()
