"""单样例 34：语法和类型正确但逻辑上为假的断言。

测试内容：在 state(x)=0 下检查 ``assert(x>0)``。
预期结果：T-Assert 义务为 false，推导停止且不生成 EndType。
论文对应：Table 2 的 T-Assert 前提 ``phi=>B``。
"""

import unittest

from hcsp_typechecker import Assert, BasicType, Verdict
from test2._support import assert_conversion, check_process


class AssertionFailureExample(unittest.TestCase):
    """检查逻辑反例与结构推导失败的区别。"""

    # 测试输入：x:Int、state x=0、path=true，断言条件为 x>0。
    # 预期行为：公式 true=>x>0 被反例否定，且不再访问隐式终端 skip。
    # 预期类型：None（预期 verdict=false）。
    # 检查内容：无正式类型、false verdict 和 T-Assert 义务。
    # 论文对应：只有 phi 能推出 B 时，T-Assert judgment 才成立。
    def test_false_assertion_stops_before_terminal_type(self) -> None:
        """失败断言必须立即终止当前推导。"""

        report = check_process(
            Assert("x > 0"),
            gamma={"x": BasicType.INT},
            state={"x": 0},
        )
        assert_conversion(
            self,
            report,
            None,
            expected_verdict=Verdict.FALSE,
            obligation_rules=("T-Assert",),
        )


if __name__ == "__main__":
    unittest.main()
