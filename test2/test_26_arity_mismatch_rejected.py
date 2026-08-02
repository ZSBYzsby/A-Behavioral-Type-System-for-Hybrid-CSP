"""单样例 26：通信载荷元数与 Theta 不一致时必须拒绝。

测试内容：一槽通道 ``pair`` 被用于二目标输入 ``pair?(x,y)``。
预期结果：verdict=false、无候选类型，并指出期望 1 槽但收到 2 个目标。
论文对应：多标量 T-In 扩展要求目标数量与 ChannelType arity 相同。
"""

import unittest

from hcsp_typechecker import BasicType, ChannelType, InputChannel, Verdict
from test2._support import assert_conversion, check_process


class ArityMismatchRejectedExample(unittest.TestCase):
    """检查多标量通信的元数边界。"""

    # 测试输入：Theta(pair) 只有一个 Int 槽，进程却输入两个变量 x、y。
    # 预期行为：T-In 在建立绑定前拒绝，不能生成 InputType。
    # 预期类型：None（通信元数错误导致结构推导失败）。
    # 检查内容：None 候选类型和包含 expects 1 payload slots 的诊断。
    # 论文对应：扩展 T-In 的 xi 列表必须与 Theta(ch) 的 Bi 列表一一对应。
    def test_input_payload_arity_must_match_theta_signature(self) -> None:
        """输入目标数量与通道签名不一致时应结构失败。"""

        report = check_process(
            InputChannel("pair", ("x", "y")),
            theta={"pair": ChannelType(BasicType.INT)},
        )
        assert_conversion(
            self,
            report,
            None,
            expected_verdict=Verdict.FALSE,
            diagnostic_contains=("expects 1 payload slots", "got 2 targets"),
        )


if __name__ == "__main__":
    unittest.main()
