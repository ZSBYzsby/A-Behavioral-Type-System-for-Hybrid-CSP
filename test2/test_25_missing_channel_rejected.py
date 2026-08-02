"""单样例 25：未在 Theta 声明的通道必须拒绝。

测试内容：尝试转换 ``missing!0``，但 Theta 为空。
预期结果：verdict=false，结构推导失败，``inferred_type is None``。
论文对应：T-Out 需要 ``Theta(ch)`` refinement type 的环境前提。
"""

import unittest

from hcsp_typechecker import OutputChannel, Verdict
from test2._support import assert_conversion, check_process


class MissingChannelRejectedExample(unittest.TestCase):
    """检查类型推导失败不会伪装成 BottomType。"""

    # 测试输入：Theta={}，进程为 OutputChannel("missing", 0)。
    # 预期行为：T-Out 找不到通道声明，返回 false 且不构造正式候选类型。
    # 预期类型：None（结构推导失败，不使用 BottomType 充当占位符）。
    # 检查内容：None 失败标记和包含 not declared in Theta 的定位诊断。
    # 论文对应：Table 2 的输出规则以 Theta 中存在 ch 类型为必要条件。
    def test_output_on_undeclared_channel_has_no_candidate_type(self) -> None:
        """未声明输出通道必须导致结构类型推导失败。"""

        report = check_process(OutputChannel("missing", 0), theta={})
        assert_conversion(
            self,
            report,
            None,
            expected_verdict=Verdict.FALSE,
            diagnostic_contains=("not declared in Theta",),
        )


if __name__ == "__main__":
    unittest.main()
