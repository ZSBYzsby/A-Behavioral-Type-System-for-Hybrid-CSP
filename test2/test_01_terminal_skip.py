"""单样例 01：终端 ``skip`` 的 Process -> Type 转换。

测试内容：验证最小终止进程能够生成唯一空行为类型。
预期结果：总体为 true，候选类型精确等于 ``EndType()``。
论文对应：Section 2.1 的 ``skip`` 与 Table 2 的 T-End/T-sigma。
"""

import unittest

from hcsp_typechecker import EndType, Skip
from test2._support import assert_conversion, check_process


class TerminalSkipExample(unittest.TestCase):
    """检查不带顺序后继的终端 skip。"""

    # 测试输入：空 Gamma、空 Theta、空状态中的 Skip()。
    # 预期行为：成功生成唯一正常终止类型 0。
    # 预期类型：EndType()。
    # 检查内容：verdict、EndType AST 以及 configuration 的 T-sigma 义务。
    # 论文对应：Table 2 的 T-End 和 Section 4.1 的 angelic type 0。
    def test_terminal_skip_converts_to_end_type(self) -> None:
        """终端 skip 应精确转换为 EndType。"""

        report = check_process(Skip())
        assert_conversion(self, report, EndType(), obligation_rules=("T-sigma",))


if __name__ == "__main__":
    unittest.main()
