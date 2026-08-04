"""单样例 32：输出值违反通道 refinement 的失败路径。

测试内容：向要求非负值的通道发送 ``-1``。
预期结果：T-Out 义务为 false，推导停止且不生成 OutputType。
论文对应：Table 2 的 T-Out refinement 替换公式。
"""

import unittest

from hcsp_typechecker import (
    BasicType,
    ChannelType,
    OutputChannel,
    Verdict,
)
from test2._support import assert_conversion, check_process


class OutputRefinementRejectedExample(unittest.TestCase):
    """检查通信结构成立但 refinement 证明失败的区分。"""

    # 测试输入：Theta(bounded)={eta:Int | eta>=0}，进程发送常量 -1。
    # 预期行为：实例化 refinement 为 -1>=0 后证明失败，且不再访问输出后继。
    # 预期类型：None（预期 verdict=false）。
    # 检查内容：无正式类型、false verdict 和 T-Out 义务。
    # 论文对应：T-Out 的 phi=>psi{e/eta} 不成立时整个 judgment 不成立。
    def test_negative_payload_fails_nonnegative_refinement(self) -> None:
        """违反 refinement 的输出不能因通道和基础类型正确而通过。"""

        report = check_process(
            OutputChannel("bounded", -1),
            theta={
                "bounded": ChannelType(BasicType.INT, lambda eta: eta >= 0)
            },
        )
        assert_conversion(
            self,
            report,
            None,
            expected_verdict=Verdict.FALSE,
            obligation_rules=("T-Out",),
        )


if __name__ == "__main__":
    unittest.main()
