"""单样例 31：正式 ``BottomType`` 与推导失败 ``None`` 的边界。

测试内容：验证有限、无事件、无自然顺序后继的 ODE 生成正式 bottom continuation。
预期结果：``PureDelayType(1, BottomType())`` 且 verdict=true。
论文对应：Section 4.1 的 bottom 与 ``delay(d) unrhd 0`` 规范表示。
"""

import unittest

from hcsp_typechecker import BottomType, ContinuousType, ODE, ODEAnnotation, PureDelayType
from test2._support import assert_conversion, check_process


class FormalBottomDelayExample(unittest.TestCase):
    """检查论文正式底行为不会与实现错误占位符混淆。"""

    # 测试输入：x'=0、B=true、delay=1，无通信事件，也没有外层顺序后继。
    # 预期行为：到时后没有正常行为，规范类型为 delay(1).bottom，而不是 None。
    # 预期类型：PureDelayType(1, BottomType())。
    # 检查内容：PureDelayType 的 continuation 精确为 BottomType 且 verdict=true。
    # 论文对应：bottom 是 T 的正式产生式；失败占位必须由 None 单独表示。
    def test_finite_ode_without_any_successor_uses_formal_bottom(self) -> None:
        """合法规则产生的 bottom 必须保留为正式 Type AST 节点。"""

        process = ODE(
            [("x", 0)],
            True,
            annotation=ODEAnnotation(delay=1),
        )
        report = check_process(process, gamma={"x": ContinuousType()}, state={"x": 0})
        assert_conversion(
            self,
            report,
            PureDelayType(1, BottomType()),
            obligation_rules=("T-ODE-domain",),
        )


if __name__ == "__main__":
    unittest.main()
