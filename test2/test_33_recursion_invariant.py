"""单样例 33：带非平凡不变量批注的递归类型推导。

测试内容：验证 ``mu X_counter>=0.(tick!counter; X)`` 的 T-mu/T-X 前提。
预期结果：总体为 true，类型为 ``mu T.(tick!.T)``。
论文对应：Section 4.2/4.3 的 process variable 批注及 Table 2 的 T-mu/T-X。
"""

import unittest

from hcsp_typechecker import (
    BasicType,
    ChannelType,
    Mu,
    MuType,
    OutputChannel,
    OutputType,
    RecursionAnnotation,
    Sequence,
    TypeVar,
    Var,
)
from test2._support import assert_conversion, check_process


class RecursionInvariantExample(unittest.TestCase):
    """检查递归入口和回边共同维护显式边界不变量。"""

    # 测试输入：counter:Nat，invariant 为 counter>=0，每轮 tick!counter 后回到 X。
    # 预期行为：Nat 域事实证明入口和回边不变量，生成通信守卫 MuType。
    # 预期类型：MuType("T", OutputType("tick", TypeVar("T")))。
    # 检查内容：递归 Type AST、T-mu 与 T-X 两个具体 FOL 义务。
    # 论文对应：X_phi 批注在 mu 入口和每个 X 回边上分别产生 premise。
    def test_recursive_annotation_is_checked_at_entry_and_back_edge(self) -> None:
        """可维持的递归不变量应使 T-mu 和 T-X 同时通过。"""

        process = Mu(
            "X",
            Sequence.of(OutputChannel("tick", "counter"), Var("X")),
            annotation=RecursionAnnotation("counter >= 0"),
        )
        report = check_process(
            process,
            gamma={"counter": BasicType.NAT},
            theta={"tick": ChannelType(BasicType.NAT)},
            state={"counter": 0},
        )
        expected = MuType("T", OutputType("tick", TypeVar("T")))
        assert_conversion(
            self,
            report,
            expected,
            obligation_rules=("T-mu", "T-X"),
        )


if __name__ == "__main__":
    unittest.main()
