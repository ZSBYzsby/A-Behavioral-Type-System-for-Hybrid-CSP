"""单样例 19：条件分支中只有一支回到递归变量。

测试内容：验证 ``mu X.(if flag then in?u;X else stop!0)``。
预期结果：MuType 的 body 是输入递归分支与终止输出分支的 InternalChoiceType。
论文对应：T-mu、T-X、T-If 及 Assumption 2.2 的逐路径通信守卫。
"""

import unittest

from hcsp_typechecker import (
    BasicType,
    ChannelType,
    EndType,
    If,
    InputChannel,
    InputType,
    InternalChoiceType,
    Mu,
    MuType,
    OutputChannel,
    OutputType,
    Sequence,
    TypeVar,
    Var,
)
from test2._support import assert_conversion, check_process


class ConditionalRecursionExample(unittest.TestCase):
    """检查递归回边在 if 单分支中的类型绑定。"""

    # 测试输入：flag:Bool；then 为 in?u;X，else 为 stop!0。
    # 预期行为：递归分支受输入保护，非递归分支正常结束，二者构成内部选择。
    # 预期类型：MuType("T", InternalChoiceType((InputType("in", TypeVar("T")), OutputType("stop", EndType()))))。
    # 检查内容：MuType body 的两个分支、TypeVar 位置和 stop 的 EndType 后继。
    # 论文对应：T-If 两子判断、T-X 回边和 Assumption 2.2 全部回边路径要求。
    def test_if_can_mix_recursive_and_terminating_branches(self) -> None:
        """只有实际含 X 的分支需要产生递归类型变量。"""

        process = Mu(
            "X",
            If(
                "flag",
                Sequence.of(InputChannel("in", "u"), Var("X")),
                OutputChannel("stop", 0),
            ),
        )
        integer = ChannelType(BasicType.INT)
        report = check_process(
            process,
            gamma={"flag": BasicType.BOOL},
            theta={"in": integer, "stop": integer},
            state={"flag": True},
        )
        expected = MuType(
            "T",
            InternalChoiceType(
                (
                    InputType("in", TypeVar("T")),
                    OutputType("stop", EndType()),
                )
            ),
        )
        assert_conversion(self, report, expected, obligation_rules=("T-X",))


if __name__ == "__main__":
    unittest.main()
