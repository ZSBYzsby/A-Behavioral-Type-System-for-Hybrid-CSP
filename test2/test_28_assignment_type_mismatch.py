"""单样例 28：赋值右值与 Gamma 基础类型不兼容。

测试内容：把 Bool 常量赋给声明为 Int 的状态变量 x。
预期结果：verdict=false；结构候选仍为 EndType，但诊断明确类型不匹配。
论文对应：T-Assign 的 ``Gamma |- e:B`` 与左值基础类型一致性前提。
"""

import unittest

from hcsp_typechecker import Assign, BasicType, EndType, Verdict
from test2._support import assert_conversion, check_process


class AssignmentTypeMismatchExample(unittest.TestCase):
    """区分“候选类型可构造”和“所有类型前提已成立”。"""

    # 测试输入：Gamma(x)=Int、state x=0，执行 x:=true。
    # 预期行为：赋值不增加行为前缀所以候选为 EndType，但总体判定必须为 false。
    # 预期类型：EndType()（仅候选类型；预期 verdict=false）。
    # 检查内容：保留候选 Type AST，同时出现 expects Int 的确定错误诊断。
    # 论文对应：T-Assign 的表达式基础类型 premise 不满足。
    def test_boolean_cannot_be_assigned_to_integer_state_variable(self) -> None:
        """类型错误不能因赋值在行为上不可见而被忽略。"""

        report = check_process(
            Assign("x", True),
            gamma={"x": BasicType.INT},
            state={"x": 0},
        )
        assert_conversion(
            self,
            report,
            EndType(),
            expected_verdict=Verdict.FALSE,
            diagnostic_contains=("expects Int",),
        )


if __name__ == "__main__":
    unittest.main()
