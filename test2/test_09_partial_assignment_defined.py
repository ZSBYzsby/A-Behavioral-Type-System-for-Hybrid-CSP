"""单样例 09：含除法赋值的有定义性与后置状态。

测试内容：验证在路径 ``x != 0`` 下 ``y := 1/x`` 可以完成类型推导。
预期结果：总体为 true，候选类型为 EndType，并顺序判定具体有定义性与后置义务。
论文对应：T-Assign 的表达式类型前提及 ``phi=>phi'{e/x}``。
"""

import unittest

from hcsp_typechecker import Assign, BasicType, EndType
from test2._support import assert_conversion, check_process


class PartialAssignmentDefinedExample(unittest.TestCase):
    """检查部分算术表达式在已知定义域内的成功路径。"""

    # 测试输入：x,y:Real，state x=2，path x!=0，进程 y:=1/x。
    # 预期行为：除数非零义务可证，最强后置状态确定，赋值不增加行为前缀。
    # 预期类型：EndType()。
    # 检查内容：EndType、T-Assign 有定义性义务及 T-Assign-post 义务。
    # 论文对应：T-Assign 横线以上的表达式合法性和后置条件前提。
    def test_division_assignment_is_valid_under_nonzero_path(self) -> None:
        """已知分母非零时，含除法的赋值应通过。"""

        report = check_process(
            Assign("y", "1 / x"),
            gamma={"x": BasicType.REAL, "y": BasicType.REAL},
            state={"x": 2, "y": 0},
            path_condition="x != 0",
        )
        assert_conversion(
            self,
            report,
            EndType(),
            obligation_rules=("T-Assign", "T-Assign-post"),
        )


if __name__ == "__main__":
    unittest.main()
