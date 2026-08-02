"""单样例 02：赋值、最强后置状态与后继断言的组合。

测试内容：验证 ``x := x + 1; assert(x >= 1)`` 的顺序推导。
预期结果：总体为 true，赋值和断言均不增加通信前缀，类型为 ``EndType``。
论文对应：Table 2 的 T-Assign、T-Assert、T-Skip/T-End。
"""

import unittest

from hcsp_typechecker import Assert, Assign, BasicType, EndType, Sequence
from test2._support import assert_conversion, check_process


class AssignmentPoststateExample(unittest.TestCase):
    """检查赋值后符号状态是否传给顺序后继。"""

    # 测试输入：x:Int，state(x)=0，path 为 x>=0，进程先自增再断言 x>=1。
    # 预期行为：断言读取更新后的 x，所有具体公式均可证明，行为类型仍为 0。
    # 预期类型：EndType()。
    # 检查内容：精确 Type AST，以及 T-Assign-post、T-Assert 证明义务均被生成。
    # 论文对应：T-Assign 的 phi=>phi'{e/x} 与 T-Assert 的 phi=>B。
    def test_assignment_updates_the_assertion_state(self) -> None:
        """赋值后的惰性最强后置状态应使后继断言成立。"""

        process = Sequence.of(Assign("x", "x + 1"), Assert("x >= 1"))
        report = check_process(
            process,
            gamma={"x": BasicType.INT},
            state={"x": 0},
            path_condition="x >= 0",
        )
        assert_conversion(
            self,
            report,
            EndType(),
            obligation_rules=("T-Assign-post", "T-Assert"),
        )


if __name__ == "__main__":
    unittest.main()
