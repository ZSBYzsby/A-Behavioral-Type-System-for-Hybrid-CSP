"""单样例 22：PPT 风格多个 configuration 的顶层组合检查。

测试内容：不用 Parallel AST，而直接提交两个带独立局部 Gamma/state 的配置。
预期结果：两个输出类型组成 ParallelType，每个 configuration 各有 T-sigma。
论文对应：Section 4.2 的 configuration judgment 与 Table 2 的 T-parallel。
"""

import unittest

from hcsp_typechecker import (
    BasicType,
    ChannelType,
    Configuration,
    EndType,
    OutputChannel,
    OutputType,
    ParallelType,
    check_hcsp,
)
from test2._support import assert_conversion


class MultipleConfigurationsExample(unittest.TestCase):
    """检查统一入口对多个顶层 configuration 的分量推导。"""

    # 测试输入：K1 state(left)=1 执行 a!left；K2 state(right)=2 执行 b!right。
    # 预期行为：局部 Gamma 独立生效，两个输出分量组合为 ParallelType。
    # 预期类型：ParallelType((OutputType("a", EndType()), OutputType("b", EndType())))。
    # 检查内容：精确组合类型、两个 T-sigma 和两个 T-Out 证明义务。
    # 论文对应：Gamma1/Gamma2 分区的 configuration judgment 及 T-parallel。
    def test_two_explicit_configurations_build_parallel_type(self) -> None:
        """多个 configuration 应按输入次序汇总为组合配置类型。"""

        integer = ChannelType(BasicType.INT)
        report = check_hcsp(
            gamma={"left": BasicType.INT, "right": BasicType.INT},
            theta={"a": integer, "b": integer},
            configurations=(
                Configuration(
                    {"left": 1},
                    OutputChannel("a", "left"),
                    gamma={"left": BasicType.INT},
                    path_condition="left == 1",
                    name="sender-a",
                ),
                Configuration(
                    {"right": 2},
                    OutputChannel("b", "right"),
                    gamma={"right": BasicType.INT},
                    path_condition="right == 2",
                    name="sender-b",
                ),
            ),
        )
        expected = ParallelType(
            (OutputType("a", EndType()), OutputType("b", EndType()))
        )
        assert_conversion(
            self,
            report,
            expected,
            obligation_rules=("T-sigma", "T-Out"),
        )
        self.assertEqual(
            sum(item.rule == "T-sigma" for item in report.obligations),
            2,
        )


if __name__ == "__main__":
    unittest.main()
