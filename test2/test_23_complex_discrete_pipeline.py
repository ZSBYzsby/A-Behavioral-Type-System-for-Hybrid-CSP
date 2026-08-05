"""单样例 23：赋值、if、输入、输出和公共 tail 的复杂离散流水线。

测试内容：组合 T-Assign、T-If、T-In、T-Out 与顺序 continuation。
预期结果：两个分支类型均以 audit! 结束，赋值节点本身不进入 Type AST。
论文对应：Table 2 多条离散规则的嵌套子 judgment。
"""

import unittest

from hcsp_typechecker import (
    Assign,
    BasicType,
    ChannelType,
    EndType,
    If,
    InputChannel,
    InputType,
    InternalChoiceType,
    OutputChannel,
    OutputType,
    Sequence,
)
from test2._support import assert_conversion, check_process


class ComplexDiscretePipelineExample(unittest.TestCase):
    """检查多层离散控制流的 continuation 拼接和状态传播。"""

    # 测试输入：x 自增；按 x>=0 分支输出 positive，或 reset?y 后重置 x 并输出 negative；
    #           最后两个分支都输出 audit!x。
    # 预期行为：类型为 positive!.(audit!.(0)) 与 reset?.(negative!.(audit!.(0))) 的内部选择。
    # 预期类型：InternalChoiceType((OutputType("positive", OutputType("audit", EndType())),
    #     InputType("reset", OutputType("negative", OutputType("audit", EndType())))))。
    # 检查内容：赋值不可观察性、输入绑定、分支结构、公共 tail 和多条 T-Out 义务。
    # 论文对应：T-Assign/T-If/T-In/T-Out 的复合推导树。
    def test_complex_discrete_flow_preserves_all_visible_prefixes(self) -> None:
        """复杂离散进程应只把可观察通信保留到行为类型中。"""

        process = Sequence.of(
            Assign("x", "x + 1"),
            If(
                "x >= 0",
                OutputChannel("positive", "x"),
                Sequence.of(
                    InputChannel("reset", "y"),
                    Assign("x", "y"),
                    OutputChannel("negative", "x"),
                ),
            ),
            OutputChannel("audit", "x"),
        )
        integer = ChannelType(BasicType.INT)
        report = check_process(
            process,
            gamma={"x": BasicType.INT},
            theta={
                "positive": integer,
                "reset": integer,
                "negative": integer,
                "audit": integer,
            },
            state={"x": 0},
        )
        audit = OutputType("audit", EndType())
        expected = InternalChoiceType(
            (
                OutputType("positive", audit),
                InputType("reset", OutputType("negative", audit)),
            )
        )
        assert_conversion(
            self,
            report,
            expected,
            obligation_rules=("T-Assign-post", "T-Out"),
        )


if __name__ == "__main__":
    unittest.main()
