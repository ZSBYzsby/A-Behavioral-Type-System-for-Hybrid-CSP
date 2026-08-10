"""统一用户输入结果与现有类型构造器的集成边界测试。

测试内容
--------
1. ``ParsedHCSPSource`` 的只读 Gamma/Theta 可直接交给现有构造入口；
2. 前端保留的 refinement 类型/自由名错误在通道实际使用时由构造器拒绝；
3. 参数约束作为共享背景进入顺序及多配置推导，且不参与局部 Gamma 分区；
4. 赋值、输入和 ODE 左端均不能修改统一 source 声明的只读参数。

论文对应
--------
本文件连接 concrete syntax lowering 与 Table 2 推导入口，但不改变任何推导规则：
解析器产生 Definition 4.1 环境和正式 Process AST，构造器继续负责 T-In/T-Out 的
refinement 公式类型与实例化。共享参数作为独立背景 H 传入各子 judgment，不属于
并行分量的状态 Gamma。
"""

from __future__ import annotations

import unittest

from hcsp_typechecker._internal import (
    Configuration,
    ParallelType,
    Verdict,
    construct_type,
    parse_hcsp_source,
)


class ParsedSourceConstructorIntegrationTests(unittest.TestCase):
    """验证统一前端产物与当前检查模型之间不需要格式适配。"""

    # 测试输入：一槽 Int 通道上的 ch?(x);ch!(x)，Gamma 预先声明同型 x。
    # 预期行为：只读环境和 Process AST 可直接进入检查器并得到 true 正式类型。
    # 检查内容：核对 verdict、候选类型以及不存在环境或结构 false 诊断。
    # 论文对应：依次触发 T-In 和 T-Out，环境对象仍是 Definition 4.1 的 Gamma/Theta。
    def test_parsed_sequential_source_is_accepted_by_constructor(self) -> None:
        """统一解析结果应直接满足 construct_type 的 Mapping/HCSP 输入协议。"""

        parsed = parse_hcsp_source(
            """gamma(x: Int)
theta(ch: channel(value: Int))
process {{ch?(x); ch!(x)}}"""
        )

        report = construct_type(
            gamma=parsed.gamma,
            theta=parsed.theta,
            configurations=(parsed.process,),
        )

        self.assertEqual(report.verdict, Verdict.TRUE)
        self.assertIsNotNone(report.constructed_type)
        self.assertFalse(
            any(item.verdict is Verdict.FALSE for item in report.diagnostics)
        )

    # 测试输入：通道 refinement 是数值表达式 value+1，Process 实际在该通道输出。
    # 预期行为：前端成功保存 Expr；T-Out 使用声明时因非 Bool refinement 返回 false。
    # 检查内容：核对无正式类型，并在诊断中看到 Expected Bool formula。
    # 论文对应：refinement 的公式判断属于通信类型规则，不在 concrete parser 中猜测。
    def test_used_non_boolean_refinement_is_rejected_by_constructor(self) -> None:
        """语法转换成功不能掩盖后续 Theta refinement 的静态类型错误。"""

        parsed = parse_hcsp_source(
            """gamma()
theta(ch: channel(value: Real) where(value + 1))
process {{ch!(0)}}"""
        )

        report = construct_type(
            gamma=parsed.gamma,
            theta=parsed.theta,
            configurations=(parsed.process,),
        )

        self.assertEqual(report.verdict, Verdict.FALSE)
        self.assertIsNone(report.constructed_type)
        self.assertTrue(
            any(
                "Expected Bool formula" in item.message
                for item in report.diagnostics
            )
        )

    # 测试输入：共享 Real 参数 limit 的约束为 limit>=0，程序断言同一公式并输出 limit。
    # 预期行为：parsed.parameters 直接进入 constructor，背景约束证明断言和输出 refinement。
    # 检查内容：核对 true verdict、正式类型以及详细报告中 Parameters/H 的可见性。
    # 论文对应：所有公式前提在共享背景 H 下判定，参数不是 Gamma 中的可变状态。
    def test_parsed_parameter_constraint_is_used_as_constructor_background(self) -> None:
        """统一 source 的参数环境不应要求调用方重新手工构造。"""

        parsed = parse_hcsp_source(
            """gamma()
parameters(limit: Real) where(limit >= 0)
theta(out: channel(value: Real) where(value >= 0))
process {{assert(limit >= 0); out!(limit)}}"""
        )

        report = construct_type(
            gamma=parsed.gamma,
            theta=parsed.theta,
            parameters=parsed.parameters,
            configurations=parsed.process_components,
        )

        self.assertEqual(report.verdict, Verdict.TRUE, report.format_detailed())
        self.assertIsNotNone(report.constructed_type)
        detailed = report.format_detailed()
        self.assertIn("Parameters: limit:Real", detailed)
        self.assertIn("参数约束", detailed)

    # 测试输入：两个并行块分别更新 left_state/right_state，却共同读取参数 limit。
    # 预期行为：process_components 形成两个 Configuration；参数跨分量共享，状态分区互斥。
    # 检查内容：核对 ParallelType、两个 T-sigma 的局部 Gamma 及无 false 诊断。
    # 论文对应：T-parallel 的子判断共享 Theta/H，但 Gamma 是各私有状态域的不交并集。
    def test_parallel_components_share_parameter_but_partition_state_gamma(self) -> None:
        """顶层 Parallel 必须按叶子交给 constructor，参数不应污染 Gamma 分区。"""

        parsed = parse_hcsp_source(
            """gamma(left_state: Real, right_state: Real)
parameters(limit: Real) where(limit >= 0)
theta(
    left: channel(value: Real) where(value == limit),
    right: channel(value: Real) where(value == limit)
)
process {
    {left_state := limit; left!(left_state)},
    {right_state := limit; right!(right_state)}
}"""
        )
        configurations = tuple(
            Configuration({}, component, name=name)
            for name, component in zip(
                ("Left", "Right"),
                parsed.process_components,
            )
        )

        report = construct_type(
            gamma=parsed.gamma,
            theta=parsed.theta,
            parameters=parsed.parameters,
            configurations=configurations,
        )

        self.assertEqual(report.verdict, Verdict.TRUE, report.format_detailed())
        self.assertIsInstance(report.constructed_type, ParallelType)
        self.assertEqual(len(report.constructed_component_types), 2)
        t_sigma_gammas = [
            {name for name, _value_type in step.gamma}
            for step in report.steps
            if step.rule == "T-sigma"
        ]
        self.assertEqual(
            t_sigma_gammas,
            [{"left_state"}, {"right_state"}],
        )
        self.assertTrue(
            all("limit" not in gamma for gamma in t_sigma_gammas)
        )
        self.assertFalse(
            any(item.verdict is Verdict.FALSE for item in report.diagnostics)
        )

    # 测试输入：在文本 source 中把共享参数 limit 写成赋值目标。
    # 预期行为：source 可形成 AST，但对应 Table 2 静态前提立即返回 false。
    # 检查内容：核对不生成正式类型，诊断明确包含 shared read-only parameter；
    #           输入与 ODE 写参数的低层分支由 parameter_environment 单元测试覆盖。
    # 论文对应：参数在执行前预赋值并在整个离散/连续执行期间保持不变。
    def test_parsed_parameter_cannot_be_an_assignment_target(self) -> None:
        """文本前端生成的共享参数不能被 HCSP 赋值改写。"""

        parsed = parse_hcsp_source(
            """gamma()
parameters(limit: Real)
theta()
process {{limit := 1}}"""
        )
        report = construct_type(
            gamma=parsed.gamma,
            theta=parsed.theta,
            parameters=parsed.parameters,
            configurations=parsed.process_components,
        )

        self.assertEqual(report.verdict, Verdict.FALSE)
        self.assertIsNone(report.constructed_type)
        self.assertTrue(
            any(
                "shared read-only parameter" in item.message
                for item in report.diagnostics
            ),
            report.format_detailed(),
        )

    # 测试输入：参数约束 limit>0 and limit<0，自身语法和 Bool 类型均合法。
    # 预期行为：前端保留公式；constructor 在展开任何 Process 规则前拒绝空参数域。
    # 检查内容：核对 false、无正式类型及不可满足参数约束诊断。
    # 论文对应：不能利用矛盾背景 H 的真空蕴含伪造任意行为类型推导。
    def test_unsatisfiable_parsed_parameter_constraint_stops_construction(self) -> None:
        """共享参数的合法预赋值集合必须非空。"""

        parsed = parse_hcsp_source(
            """gamma()
parameters(limit: Real) where(limit > 0 and limit < 0)
theta()
process {{skip}}"""
        )

        report = construct_type(
            gamma=parsed.gamma,
            theta=parsed.theta,
            parameters=parsed.parameters,
            configurations=parsed.process_components,
        )

        self.assertEqual(report.verdict, Verdict.FALSE)
        self.assertIsNone(report.constructed_type)
        self.assertTrue(
            any(
                "must be satisfiable" in item.message
                for item in report.diagnostics
            )
        )


if __name__ == "__main__":
    unittest.main()
