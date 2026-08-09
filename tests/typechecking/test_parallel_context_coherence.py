r"""Table 2 [T-||] 的 Gamma/路径组合一致性测试。

测试内容
--------
本文件专门验证 Assumption 2.1 之外的并行 typing-context 条件：

1. Assumption 2.1 已在 process AST 层保证并行进程不共享程序变量；
2. 每个 Configuration 的局部 Gamma 还必须是全局 Gamma 的同型分区，不能
   新增变量、改变类型或在所有分量的并集中遗漏变量；
3. 使用局部路径时，所有并行叶子必须同时提供，外层 ``true`` 表示 Table 2
   结论路径由局部路径的合取形成，不能再给一条相互冲突的全局路径；
4. 论文中的有状态配置必须写成多个 ``(sigma, P)`` 叶子。单个
   ``Configuration({}, Parallel(...))`` 只作为空状态、空 Gamma、true 路径
   的便捷写法保留。

论文对应
--------
对应 Definition 4.1 中上下文组合 ``Gamma,Gamma'`` 的定义域不交条件，以及
Table 2 [T-||]：两个前提分别使用 ``Gamma,phi`` 和 ``Gamma',phi'``，结论使用
它们的不交并集与合取。Assumption 2.1 负责程序变量集合不交；本文件验证类型
判断输入本身也确实形成同一个可组合的上下文。
"""

from __future__ import annotations

import unittest

from hcsp_typechecker._internal import (
    Assert,
    BasicType,
    Configuration,
    EndType,
    InputChannel,
    OutputChannel,
    Parallel,
    ParallelType,
    Skip,
    Verdict,
    check_hcsp,
    types_equivalent,
)


class ParallelContextCoherenceTests(unittest.TestCase):
    """验证并行分量局部上下文能精确组成入口处的全局判断。"""

    # 测试输入：全局 Gamma 声明 x:Int，唯一局部 Gamma 把同一个 x 改成 Bool。
    # 预期行为：T-|| 在建立子 judgment 前拒绝改型，结果 false 且无正式类型。
    # 检查内容：诊断明确展示 global/local 类型，而不是等到状态求值时偶然失败。
    # 论文对应：Definition 4.1 的上下文组合只能合并既有、互不相交的类型项。
    def test_local_gamma_cannot_change_a_global_variable_type(self) -> None:
        """局部 Gamma 不是能够重新声明全局变量类型的覆盖层。"""

        report = check_hcsp(
            gamma={"x": BasicType.INT},
            theta={},
            configurations=[
                Configuration(
                    {"x": True},
                    Skip(),
                    gamma={"x": BasicType.BOOL},
                )
            ],
        )

        self.assertEqual(report.verdict, Verdict.FALSE)
        self.assertIsNone(report.inferred_type)
        self.assertTrue(
            any(
                "global Int, local Bool" in item.message
                for item in report.diagnostics
            )
        )

    # 测试输入：全局 Gamma 含 left/right，但两个局部分量合起来只声明 left。
    # 预期行为：即使局部 Gamma 两两不交，也因并集不等于全局 Gamma 而失败。
    # 检查内容：排除“只检查 overlap、不检查 coverage”造成的上下文静默丢失。
    # 论文对应：[T-||] 结论 Gamma,Gamma' 正是两个前提上下文的完整不交并集。
    def test_local_gamma_union_must_cover_the_global_gamma(self) -> None:
        """两两不交只是必要条件，局部 Gamma 还必须完整覆盖全局 Gamma。"""

        report = check_hcsp(
            gamma={"left": BasicType.INT, "right": BasicType.INT},
            theta={},
            configurations=[
                Configuration({}, Skip(), gamma={"left": BasicType.INT}),
                Configuration({}, Skip(), gamma={}),
            ],
        )

        self.assertEqual(report.verdict, Verdict.FALSE)
        self.assertIsNone(report.inferred_type)
        self.assertTrue(
            any(
                "do not cover the global Gamma: right" in item.message
                for item in report.diagnostics
            )
        )

    # 测试输入：全局 Gamma 为空，局部 Gamma 凭空声明 y:Int。
    # 预期行为：T-|| 立即拒绝局部新增项，不能把局部环境伪装成全局判断的前提。
    # 检查内容：结果必须为 false/None，并报告 y 不存在于 global Gamma。
    # 论文对应：结论上下文由前提上下文组成，检查器入口不能同时声称全局为空。
    def test_local_gamma_cannot_invent_a_global_variable(self) -> None:
        """局部 Gamma 中的每个变量都必须来自入口全局 Gamma。"""

        report = check_hcsp(
            gamma={},
            theta={},
            configurations=[
                Configuration(
                    {"y": 1},
                    Skip(),
                    gamma={"y": BasicType.INT},
                )
            ],
        )

        self.assertEqual(report.verdict, Verdict.FALSE)
        self.assertIsNone(report.inferred_type)
        self.assertTrue(
            any(
                "absent from the global Gamma: y" in item.message
                for item in report.diagnostics
            )
        )

    # 测试输入：同一判断同时给出全局 false 和局部 true 路径。
    # 预期行为：拒绝含义冲突的双重路径输入，不能让局部 true 覆盖全局 false。
    # 检查内容：在 T-sigma 之前结构失败，最终没有候选类型。
    # 论文对应：[T-||] 结论只有唯一的 phi and phi'，不存在额外覆盖优先级。
    def test_nontrivial_global_path_cannot_be_overridden_locally(self) -> None:
        """显式局部路径只能在外层路径留为默认 true 时使用。"""

        report = check_hcsp(
            gamma={},
            theta={},
            configurations=[
                Configuration({}, Skip(), path_condition=True)
            ],
            path_condition=False,
        )

        self.assertEqual(report.verdict, Verdict.FALSE)
        self.assertIsNone(report.inferred_type)
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

        report = check_hcsp(
            gamma={},
            theta={},
            configurations=[
                Configuration({}, Skip(), path_condition=True),
                Configuration({}, Skip()),
            ],
        )

        self.assertEqual(report.verdict, Verdict.FALSE)
        self.assertIsNone(report.inferred_type)
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
        report = check_hcsp(
            gamma={"x": BasicType.INT, "y": BasicType.INT},
            theta={},
            configurations=[Configuration({"x": 1, "y": 1}, system)],
            path_condition="x > 0 and y > 0",
        )

        self.assertEqual(report.verdict, Verdict.FALSE)
        self.assertIsNone(report.inferred_type)
        self.assertTrue(
            any(
                "stateful Parallel system" in item.message
                for item in report.diagnostics
            )
        )

    # 测试输入：把上一个 x/y 系统按论文写成两个状态、Gamma、路径均独立的配置。
    # 预期行为：两个 T-sigma 分别成功，T-|| 生成 ParallelType((0,0))。
    # 检查内容：验证新增一致性检查不会拒绝合法的不交分区与局部路径合取。
    # 论文对应：Table 2 [T-sigma] 两次应用后由 [T-||] 组合。
    def test_explicit_stateful_leaves_form_a_valid_parallel_judgment(self) -> None:
        """有状态并行的规范输入是多个上下文互不相交的 Configuration。"""

        report = check_hcsp(
            gamma={"x": BasicType.INT, "y": BasicType.INT},
            theta={},
            configurations=[
                Configuration(
                    {"x": 1},
                    Assert("x > 0"),
                    gamma={"x": BasicType.INT},
                    path_condition="x > 0",
                    name="left",
                ),
                Configuration(
                    {"y": 1},
                    Assert("y > 0"),
                    gamma={"y": BasicType.INT},
                    path_condition="y > 0",
                    name="right",
                ),
            ],
            path_condition="true",
        )

        self.assertEqual(report.verdict, Verdict.TRUE)
        self.assertTrue(
            types_equivalent(
                report.inferred_type,
                ParallelType((EndType(), EndType())),
            )
        )
        self.assertEqual(sum(step.rule == "T-sigma" for step in report.steps), 2)

    # 测试输入：空 Gamma、空 state、true 路径下的常量输出与新鲜输入并行。
    # 预期行为：继续接受单 Configuration 的轻量语法糖并生成两个行为分量。
    # 检查内容：限制只影响需要拆分状态的 Parallel，不破坏无状态协议便捷写法。
    # 论文对应：两个空状态配置的 T-sigma 前提均为真，可安全省略重复输入样板。
    def test_stateless_parallel_sugar_remains_available(self) -> None:
        """无状态并行仍可使用单 Configuration 的安全便捷写法。"""

        report = check_hcsp(
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
        self.assertIsInstance(report.inferred_type, ParallelType)


if __name__ == "__main__":
    unittest.main()
