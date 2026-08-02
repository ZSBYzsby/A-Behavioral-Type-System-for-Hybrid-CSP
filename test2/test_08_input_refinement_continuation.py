"""单样例 08：输入 refinement 对后继断言和输出的影响。

测试内容：从 ``nonneg?x`` 的 refinement 获得后继 ``assert(x>=0)`` 所需事实。
预期结果：输入后断言成立，并继续输出 copy，类型中不出现 Assert 节点。
论文对应：Table 2 的 T-In、T-Assert、T-Out 组合。
"""

import unittest

from hcsp_typechecker import (
    Assert,
    BasicType,
    ChannelType,
    EndType,
    InputChannel,
    InputType,
    OutputChannel,
    OutputType,
    Sequence,
)
from test2._support import assert_conversion, check_process


class InputRefinementContinuationExample(unittest.TestCase):
    """检查输入 refinement 被加入通信后继的路径事实。"""

    # 测试输入：{eta:Int | eta>=0} 的 nonneg?x；随后 assert(x>=0); copy!x。
    # 预期行为：T-In 替换 eta 为 x 后为断言提供事实，最终类型为 nonneg?.copy!.0。
    # 预期类型：InputType("nonneg", OutputType("copy", EndType()))。
    # 检查内容：输入/输出前缀和 T-Assert、T-Out 两类具体证明义务。
    # 论文对应：T-In 的 refinement 假设进入 continuation judgment。
    def test_input_refinement_proves_the_following_assertion(self) -> None:
        """输入值 refinement 应对同一输入分支的后继可见。"""

        process = Sequence.of(
            InputChannel("nonneg", "x"),
            Assert("x >= 0"),
            OutputChannel("copy", "x"),
        )
        report = check_process(
            process,
            theta={
                "nonneg": ChannelType(BasicType.INT, lambda eta: eta >= 0),
                "copy": ChannelType(BasicType.INT),
            },
        )
        expected = InputType("nonneg", OutputType("copy", EndType()))
        assert_conversion(
            self,
            report,
            expected,
            obligation_rules=("T-Assert", "T-Out"),
        )


if __name__ == "__main__":
    unittest.main()
