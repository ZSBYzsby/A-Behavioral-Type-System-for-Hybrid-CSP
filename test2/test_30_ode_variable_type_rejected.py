"""单样例 30：ODE 左端状态变量必须在 Gamma 中显式声明为连续变量。

测试内容：把连续变量 x 错误声明为 Int 后转换有限 ODE。
预期结果：两条 ODE 规则都因结构错误不可用，不生成类型并报告连续类型要求。
论文对应：连续演化表达式类型前提与 Table 2 的有限 ODE 规则。
"""

import unittest

from hcsp_typechecker import (
    BasicType,
    ODE,
    ODEAnnotation,
    Sequence,
    Skip,
    Verdict,
)
from test2._support import assert_conversion, check_process


class ODEVariableTypeRejectedExample(unittest.TestCase):
    """检查用户连续变量与自动 Real 局部时钟的类型边界。"""

    # 测试输入：Gamma(x)=Int，ODE 为 x'=1、x<1、delay=1，后接 skip。
    # 预期行为：x 不是 ContinuousType，使两条候选规则都不可形成合法推导。
    # 预期类型：None；错误占位不会伪装成论文正式类型。
    # 检查内容：类型生成失败和 must have ContinuousType 诊断；隐藏 t 无需声明。
    # 论文对应：ODE 方程变量属于连续 Real 状态，局部时钟由规则自动引入。
    def test_integer_ode_state_variable_is_rejected(self) -> None:
        """ODE 的用户演化变量没有连续声明时必须拒绝。"""

        process = Sequence.of(
            ODE(
                [("x", 1)],
                "x < 1",
                annotation=ODEAnnotation(delay=1),
            ),
            Skip(),
        )
        report = check_process(
            process,
            gamma={"x": BasicType.INT},
            state={"x": 0},
        )
        assert_conversion(
            self,
            report,
            None,
            expected_verdict=Verdict.FALSE,
            diagnostic_contains=("must have ContinuousType",),
        )


if __name__ == "__main__":
    unittest.main()
