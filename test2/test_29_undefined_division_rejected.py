"""单样例 29：部分表达式的有定义性证明失败。

测试内容：在允许 ``x=0`` 的路径下检查赋值 ``y:=1/x``。
预期结果：T-Assign 有定义性义务为 false，推导停止且不生成正式类型。
论文对应：T-Assign 的表达式合法/有定义性前提与后置条件前提分离。
"""

import unittest

from hcsp_typechecker import Assign, BasicType, Verdict
from test2._support import assert_conversion, check_process


class UndefinedDivisionRejectedExample(unittest.TestCase):
    """检查可能除零的赋值不会被候选类型掩盖。"""

    # 测试输入：x,y:Real、state x=0、path=true，进程 y:=1/x。
    # 预期行为：除数非零的具体 FOL premise 无法成立，整体 false，并在此停止。
    # 预期类型：None；未访问 T-Assign-post 和隐式终端 skip。
    # 检查内容：无正式类型、false verdict 和 T-Assign 有定义性义务。
    # 论文对应：T-Assign 横线以上的表达式 judgment 必须成立。
    def test_division_by_possible_zero_fails_definedness_obligation(self) -> None:
        """可能除零时应由就地 FOL 证明给出确定失败。"""

        report = check_process(
            Assign("y", "1 / x"),
            gamma={"x": BasicType.REAL, "y": BasicType.REAL},
            state={"x": 0, "y": 0},
            path_condition=True,
        )
        assert_conversion(
            self,
            report,
            None,
            expected_verdict=Verdict.FALSE,
            obligation_rules=("T-Assign",),
        )


if __name__ == "__main__":
    unittest.main()
