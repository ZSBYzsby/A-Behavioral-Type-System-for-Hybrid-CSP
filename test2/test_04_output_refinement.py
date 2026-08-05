"""单样例 04：输出通道 refinement 的成功路径。

测试内容：验证路径条件能推出发送值满足通道的非负 refinement。
预期结果：总体为 true，类型显示为 ``nonneg!.(0)``，并产生 T-Out 公式。
论文对应：Table 2 的 T-Out refinement 替换前提。
"""

import unittest

from hcsp_typechecker import BasicType, ChannelType, EndType, OutputChannel, OutputType
from test2._support import assert_conversion, check_process


class OutputRefinementExample(unittest.TestCase):
    """检查一槽输出 refinement 的公式实例化。"""

    # 测试输入：x:Int、path x>=0、通道类型 {eta:Int | eta>=0} 和 nonneg!x。
    # 预期行为：用 x 替换 eta 后得到可证公式，输出前缀成功生成。
    # 预期类型：OutputType("nonneg", EndType())。
    # 检查内容：精确 OutputType 和 T-Out 义务存在。
    # 论文对应：T-Out 的 phi=>psi{e/eta}。
    def test_output_value_satisfies_channel_refinement(self) -> None:
        """满足 refinement 的输出应被接受。"""

        report = check_process(
            OutputChannel("nonneg", "x"),
            gamma={"x": BasicType.INT},
            theta={
                "nonneg": ChannelType(
                    BasicType.INT,
                    lambda eta: eta >= 0,
                )
            },
            state={"x": 1},
            path_condition="x >= 0",
        )
        assert_conversion(
            self,
            report,
            OutputType("nonneg", EndType()),
            obligation_rules=("T-Out",),
        )


if __name__ == "__main__":
    unittest.main()
