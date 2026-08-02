"""单样例 27：非 Bool 的 if guard 必须拒绝。

测试内容：用整数表达式 ``x+1`` 作为 ``if`` 的条件。
预期结果：verdict=false 且无法为 if 构造候选行为类型。
论文对应：Section 2.1 的条件位置 B 及 Table 2 的 T-If 类型前提。
"""

import unittest

from hcsp_typechecker import BasicType, If, Skip, Verdict
from test2._support import assert_conversion, check_process


class InvalidIfGuardRejectedExample(unittest.TestCase):
    """检查条件表达式的 Bool 类型要求。"""

    # 测试输入：x:Int，进程 if (x+1) then skip else skip。
    # 预期行为：表达式可解析但不是 Bool，T-If 在产生分支类型前拒绝。
    # 预期类型：None（guard 类型错误使两个分支 judgment 不展开）。
    # 检查内容：verdict=false、inferred_type=None 和 Expected Bool formula 诊断。
    # 论文对应：B 与普通数值表达式 e 是不同的语义位置。
    def test_integer_expression_cannot_be_used_as_if_guard(self) -> None:
        """非布尔 guard 不应被 Python truthiness 静默接受。"""

        report = check_process(
            If("x + 1", Skip(), Skip()),
            gamma={"x": BasicType.INT},
            state={"x": 0},
        )
        assert_conversion(
            self,
            report,
            None,
            expected_verdict=Verdict.FALSE,
            diagnostic_contains=("Expected Bool formula",),
        )


if __name__ == "__main__":
    unittest.main()
