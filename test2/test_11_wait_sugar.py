"""单样例 11：``ODE.wait(d)`` 语法糖的类型转换。

测试内容：验证有理数 ``wait(3/2)`` 展开后仍得到规范 PureDelayType。
预期结果：``PureDelayType(Fraction(3,2), EndType())``。
论文对应：Section 2.1 的 wait 展开与 Table 2 的有限 ODE 规则。
"""

from fractions import Fraction
import unittest

from hcsp_typechecker import EndType, ODE, PureDelayType
from test2._support import (
    assert_conversion,
    check_process,
    select_natural_timeout_dl,
)


class WaitSugarExample(unittest.TestCase):
    """检查 wait 类方法、隐藏截止时钟和类型规范化。"""

    # 测试输入：不声明任何用户时钟，直接构造 ODE.wait(Fraction(3,2))。
    # 预期行为：内部 ODE;Skip 使用隐藏局部 t，到时生成 delay(3/2).0。
    # 预期类型：PureDelayType(Fraction(3, 2), EndType())。
    # 检查内容：精确有理 duration、EndType 后继及 T-ODE-boundary 义务。
    # 论文对应：wait(d) 的 ODE 展开和 delay(d).T 类型缩写。
    def test_wait_sugar_becomes_exact_rational_delay(self) -> None:
        """wait 应在不污染 Gamma 的前提下生成精确有理时延。"""

        report = check_process(
            ODE.wait(Fraction(3, 2)),
            dl_checker=select_natural_timeout_dl,
        )
        expected = PureDelayType(Fraction(3, 2), EndType())
        assert_conversion(
            self,
            report,
            expected,
            obligation_rules=("T-ODE-boundary",),
        )


if __name__ == "__main__":
    unittest.main()
