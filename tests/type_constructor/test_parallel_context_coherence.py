r"""Table 2 [T-||] 的共享 Gamma、状态所有权与路径组合测试。

测试内容
--------
本文件专门验证统一 Gamma 下的并行 typing-context 条件：

1. Assumption 2.1 已在 process AST 层保证并行进程不共享程序变量；
2. 所有 Configuration 直接使用同一份 Gamma；低层接口还会把 state 定义域
   纳入所有权检查，防止多个配置绕过 Process AST 共享状态；
3. 使用局部路径时，所有并行叶子必须同时提供，外层 ``true`` 表示 Table 2
   结论路径由局部路径的合取形成，不能再给一条相互冲突的全局路径；
4. 论文中的有状态配置必须写成多个 ``(sigma, P)`` 叶子。单个
   ``Configuration({}, Parallel(...))`` 只作为空状态、空 Gamma、true 路径
   的便捷写法保留。

论文对应
--------
项目把 Gamma 解释为整个判断共享的类型声明环境，并以 Assumption 2.1 和
configuration state 所有权保证并行分量不共享可变状态。Theta 和全局参数同样
共享，局部路径仍按 Table 2 [T-||] 的前提分别建立。
"""

from __future__ import annotations

import unittest

from hcsp_typechecker._internal import (
    Assert,
    BasicType,
    Configuration,
    EmptyType,
    InputChannel,
    OutputChannel,
    Parallel,
    ParallelType,
    Skip,
    Verdict,
    construct_type,
    types_equivalent,
)


class ParallelContextCoherenceTests(unittest.TestCase):
    """验证共享 Gamma 不会放松并行分量的状态所有权约束。"""

    # 测试输入：全局 Gamma 额外声明 unused:Int，两个自动分区的 skip 都不使用它。
    # 预期行为：两个 T-sigma 都直接读取完整 Gamma，仍生成 ParallelType。
    # 检查内容：Gamma 是声明环境而不是状态所有权分区，未使用项可以重复可见。
    # 论文对应：项目统一 Gamma 约定不改变两个 skip 的行为类型。
    def test_every_component_uses_the_same_complete_gamma(self) -> None:
        """每个并行配置直接使用同一份完整 Gamma。"""

        report = construct_type(
            gamma={"unused": BasicType.INT},
            theta={},
            configurations=[
                Configuration({}, Skip()),
                Configuration({}, Skip()),
            ],
        )

        self.assertEqual(report.verdict, Verdict.TRUE)
        self.assertTrue(
            types_equivalent(
                report.constructed_type,
                ParallelType((EmptyType(), EmptyType())),
            )
        )
        sigma_gammas = [
            dict(step.gamma) for step in report.steps if step.rule == "T-sigma"
        ]
        self.assertEqual(
            sigma_gammas,
            [{"unused": "Int"}, {"unused": "Int"}],
        )

    # 测试输入：两个低层 Configuration 的 state 都给 x 赋初值，Process 均为 skip。
    # 预期行为：即使 Process AST 本身没有变量，也拒绝重复拥有同一可变状态 x。
    # 检查内容：共享 Gamma 不会被误当作共享状态许可。
    # 论文对应：并行配置的可变状态空间仍必须互不重叠。
    def test_configuration_states_cannot_share_a_variable(self) -> None:
        """共享 Gamma 下两个配置仍不能同时拥有同一个状态变量。"""

        report = construct_type(
            gamma={"x": BasicType.INT},
            theta={},
            configurations=[
                Configuration({"x": 0}, Skip()),
                Configuration({"x": 1}, Skip()),
            ],
        )

        self.assertEqual(report.verdict, Verdict.FALSE)
        self.assertIsNone(report.constructed_type)
        self.assertTrue(
            any(
                "share state variables: x" in item.message
                for item in report.diagnostics
            )
        )

    # 测试输入：同一判断同时给出全局 false 和局部 true 路径。
    # 预期行为：拒绝含义冲突的双重路径输入，不能让局部 true 覆盖全局 false。
    # 检查内容：在 T-sigma 之前结构失败，最终没有候选类型。
    # 论文对应：[T-||] 结论只有唯一的 phi and phi'，不存在额外覆盖优先级。
    def test_nontrivial_global_path_cannot_be_overridden_locally(self) -> None:
        """显式局部路径只能在外层路径留为默认 true 时使用。"""

        report = construct_type(
            gamma={},
            theta={},
            configurations=[
                Configuration({}, Skip(), path_condition=True)
            ],
            path_condition=False,
        )

        self.assertEqual(report.verdict, Verdict.FALSE)
        self.assertIsNone(report.constructed_type)
        self.assertTrue(
            any(
                "non-trivial global path" in item.message
                for item in report.diagnostics
            )
        )

    # 测试输入：两个并行叶子中只有第一个提供局部路径。
    # 预期行为：拒绝一半使用局部路径、一半继承全局路径的混合解释。
    # 检查内容：T-|| 返回结构失败并说明所有分量必须采用同一种路径输入方式。
    # 论文对应：两个 premise 各自有确定的 phi/phi'，结论再取二者合取。
    def test_parallel_local_paths_must_be_all_or_none(self) -> None:
        """局部路径必须覆盖全部并行配置，不能只覆盖部分分量。"""

        report = construct_type(
            gamma={},
            theta={},
            configurations=[
                Configuration({}, Skip(), path_condition=True),
                Configuration({}, Skip()),
            ],
        )

        self.assertEqual(report.verdict, Verdict.FALSE)
        self.assertIsNone(report.constructed_type)
        self.assertTrue(
            any(
                "either all provide local path" in item.message
                for item in report.diagnostics
            )
        )

    # 测试输入：x/y 分属两个无共享变量的进程，但被包进同一个有状态 Parallel 配置。
    # 预期行为：即使满足 Assumption 2.1，也要求改写成两个显式 Configuration。
    # 检查内容：确认 Assumption 2.1 与 Gamma/state/path 分区是两类独立要求。
    # 论文对应：配置语法 K ::= (sigma,P) | K||K'，有状态叶子中的 P 不是 S||S'。
    def test_stateful_parallel_requires_explicit_configuration_leaves(self) -> None:
        """Assumption 2.1 不会自动把一个全局 state/Gamma 拆成两个配置。"""

        system = Parallel(Assert("x > 0"), Assert("y > 0"))
        report = construct_type(
            gamma={"x": BasicType.INT, "y": BasicType.INT},
            theta={},
            configurations=[Configuration({"x": 1, "y": 1}, system)],
            path_condition="x > 0 and y > 0",
        )

        self.assertEqual(report.verdict, Verdict.FALSE)
        self.assertIsNone(report.constructed_type)
        self.assertTrue(
            any(
                "stateful Parallel system" in item.message
                for item in report.diagnostics
            )
        )

    # 测试输入：把上一个 x/y 系统按论文写成两个状态、路径独立的配置。
    # 预期行为：两个 T-sigma 分别成功，T-|| 生成 ParallelType((0,0))。
    # 检查内容：验证共享 Gamma 不会被误判为共享状态，局部路径仍可合取。
    # 论文对应：Table 2 [T-sigma] 两次应用后由 [T-||] 组合。
    def test_explicit_stateful_leaves_form_a_valid_parallel_judgment(self) -> None:
        """有状态并行的规范输入是多个状态所有权互不相交的 Configuration。"""

        report = construct_type(
            gamma={"x": BasicType.INT, "y": BasicType.INT},
            theta={},
            configurations=[
                Configuration(
                    {"x": 1},
                    Assert("x > 0"),
                    path_condition="x > 0",
                    name="left",
                ),
                Configuration(
                    {"y": 1},
                    Assert("y > 0"),
                    path_condition="y > 0",
                    name="right",
                ),
            ],
            path_condition="true",
        )

        self.assertEqual(report.verdict, Verdict.TRUE)
        self.assertTrue(
            types_equivalent(
                report.constructed_type,
                ParallelType((EmptyType(), EmptyType())),
            )
        )
        self.assertEqual(sum(step.rule == "T-sigma" for step in report.steps), 2)

    # 测试输入：空 Gamma、空 state、true 路径下的常量输出与新鲜输入并行。
    # 预期行为：继续接受单 Configuration 的轻量语法糖并生成两个行为分量。
    # 检查内容：限制只影响需要拆分状态的 Parallel，不破坏无状态协议便捷写法。
    # 论文对应：两个空状态配置的 T-sigma 前提均为真，可安全省略重复输入样板。
    def test_stateless_parallel_sugar_remains_available(self) -> None:
        """无状态并行仍可使用单 Configuration 的安全便捷写法。"""

        report = construct_type(
            gamma={},
            theta={"left": BasicType.INT, "right": BasicType.INT},
            configurations=[
                Configuration(
                    {},
                    Parallel(
                        OutputChannel("left", 0),
                        InputChannel("right", "received"),
                    ),
                )
            ],
        )

        self.assertEqual(report.verdict, Verdict.TRUE)
        self.assertIsInstance(report.constructed_type, ParallelType)


if __name__ == "__main__":
    unittest.main()
