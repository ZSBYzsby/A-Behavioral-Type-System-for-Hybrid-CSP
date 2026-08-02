"""单样例 35：多标量通道上的联合 refinement。

测试内容：同时发送 low/high，并证明联合性质 ``low <= high``。
预期结果：总体为 true，类型为单个 ``range!.0`` 通信前缀。
论文对应：项目多标量 T-Out 扩展的一次性联合替换。
"""

import unittest

from hcsp_typechecker import (
    BasicType,
    ChannelType,
    EndType,
    OutputChannel,
    OutputType,
)
from test2._support import assert_conversion, check_process


class JointMultiScalarRefinementExample(unittest.TestCase):
    """检查多槽 refinement 能表达槽位之间的关系。"""

    # 测试输入：low=1、high=3；range 承载两个 Int，联合 refinement 为 low<=high。
    # 预期行为：两个实际表达式同时替换两个 binder，路径条件足以证明联合性质。
    # 预期类型：OutputType("range", EndType())。
    # 检查内容：一个 OutputType 前缀、二槽 ChannelType 和单条联合 T-Out 义务。
    # 论文对应：T-Out 扩展为 phi=>psi{e1/eta1,e2/eta2}，而非两个独立谓词。
    def test_two_payloads_satisfy_one_joint_refinement(self) -> None:
        """多标量输出应一次证明跨槽位的联合 refinement。"""

        report = check_process(
            OutputChannel("range", ("low", "high")),
            gamma={"low": BasicType.INT, "high": BasicType.INT},
            theta={
                "range": ChannelType(
                    (BasicType.INT, BasicType.INT),
                    lambda low, high: low <= high,
                    binders=("low_value", "high_value"),
                )
            },
            state={"low": 1, "high": 3},
            path_condition="low <= high",
        )
        assert_conversion(
            self,
            report,
            OutputType("range", EndType()),
            obligation_rules=("T-Out",),
        )


if __name__ == "__main__":
    unittest.main()
