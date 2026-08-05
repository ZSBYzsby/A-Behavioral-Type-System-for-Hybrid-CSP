"""单样例 21：HCSP ``Parallel`` AST 到组合配置类型。

测试内容：验证一个输出分量与一个输入分量的并行系统。
预期结果：显示为 ``(left!.(0)) | (right?.(0))``，分量次序保持不变。
论文对应：Section 2.1 的 S parallel S' 与 Table 2 的 T-parallel。
"""

import unittest

from hcsp_typechecker import (
    BasicType,
    ChannelType,
    EndType,
    InputChannel,
    InputType,
    OutputChannel,
    OutputType,
    Parallel,
    ParallelType,
)
from test2._support import assert_conversion, check_process


class SimpleParallelExample(unittest.TestCase):
    """检查系统层并行不会被误表示为 ProcessType 选择。"""

    # 测试输入：left!0 与 right?u 并行，两个分量没有共享用户变量。
    # 预期行为：分别推导 OutputType/InputType，再由 T-parallel 组合。
    # 预期类型：ParallelType((OutputType("left", EndType()), InputType("right", EndType())))。
    # 检查内容：ParallelType 类别、分量顺序和各自 EndType 后继。
    # 论文对应：mathcal T ::= T | mathcal T 与 Gamma 分区判断。
    def test_parallel_ast_becomes_parallel_configuration_type(self) -> None:
        """并行系统应生成 ParallelType，而不是内部选择。"""

        process = Parallel(
            OutputChannel("left", 0),
            InputChannel("right", "u"),
        )
        integer = ChannelType(BasicType.INT)
        report = check_process(process, theta={"left": integer, "right": integer})
        expected = ParallelType(
            (
                OutputType("left", EndType()),
                InputType("right", EndType()),
            )
        )
        assert_conversion(self, report, expected)


if __name__ == "__main__":
    unittest.main()
