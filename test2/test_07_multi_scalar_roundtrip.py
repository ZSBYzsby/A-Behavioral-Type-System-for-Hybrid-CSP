"""单样例 07：多标量输入与多标量输出的往返通信。

测试内容：验证 ``pair?(x, ready); echo!(x, ready)`` 的扩展通信实现。
预期结果：行为类型只保存通道前缀，载荷元数和各槽类型仍由 Theta 保存。
论文对应：项目确认的多标量 T-In/T-Out 扩展；每个槽仍是 BasicType。
"""

import unittest

from hcsp_typechecker import (
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


class MultiScalarRoundtripExample(unittest.TestCase):
    """检查两个独立标量槽位的绑定、类型匹配和继续使用。"""

    # 测试输入：pair/echo 都承载 (Int,Bool)，输入目标为 x、ready，随后原样输出。
    # 预期行为：两个输入变量按槽加入 Gamma，输出元数/类型匹配并生成嵌套前缀。
    # 预期类型：InputType("pair", OutputType("echo", EndType()))。
    # 检查内容：InputType/OutputType 结构和 echo 的 T-Out 证明义务。
    # 论文对应：多标量 T-In/T-Out 同时替换全部 xi/etai 与 ei/etai。
    def test_multi_scalar_input_values_can_be_output_together(self) -> None:
        """多标量输入绑定应能作为后继多标量输出的表达式使用。"""

        signature = ChannelType((BasicType.INT, BasicType.BOOL))
        process = Sequence.of(
            InputChannel("pair", ("x", "ready")),
            OutputChannel("echo", ("x", "ready")),
        )
        report = check_process(
            process,
            theta={"pair": signature, "echo": signature},
        )
        expected = InputType("pair", OutputType("echo", EndType()))
        assert_conversion(self, report, expected, obligation_rules=("T-Out",))


if __name__ == "__main__":
    unittest.main()
