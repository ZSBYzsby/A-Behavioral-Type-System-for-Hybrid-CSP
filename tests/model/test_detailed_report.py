"""验证面向用户的详细类型检查报告。

测试内容：本文件覆盖两类功能：

* ``InferenceStep`` 是否按规则进入顺序保存环境快照和候选类型；
* ``CheckReport.format_detailed()`` 是否同时展示总体结论、执行过程、证明义务、
  分组后的一阶逻辑/dL 公式、原始公式、证明器实际输入、遗留义务、诊断和
  汇总，避免命令行用户只能看到一个最终 ``Verdict``。

测试使用 ``ch?x; ch!x``，因为它能清楚观察 T-In 在后继上下文中引入
``x:Int`` 和新鲜接收符号，再由 T-Out 使用该符号完成输出检查。

预期行为：成功报告保存完整先序规则轨迹，详细文本将候选类型和证明结论分区。
论文对应：Section 4.2/4.3 与 Table 2 的推导树及其横线以上的证明前提。
"""

from __future__ import annotations

import unittest

from hcsp_typechecker import (
    BasicType,
    ChannelType,
    Configuration,
    ContinuousType,
    InputChannel,
    ODE,
    ODEAnnotation,
    OutputChannel,
    Sequence,
    Skip,
    Verdict,
    check_hcsp,
)


class DetailedReportTests(unittest.TestCase):
    """检查详细报告的结构化数据和最终文本表示。"""

    def _report(self):
        """构造一个无需外部 dL 后端即可完整判真的通信报告。"""

        process = Sequence.of(
            InputChannel("ch", "x"),
            OutputChannel("ch", "x"),
        )
        return check_hcsp(
            gamma={},
            theta={"ch": ChannelType(BasicType.INT)},
            configurations=[Configuration({}, process)],
            path_condition=True,
        )

    # 测试输入：空 Gamma 下的 ch?x; ch!x，Theta(ch) 为一槽 Int refinement type。
    # 预期行为：T-sigma 的 state 和 T-Out 的 FOL 公式分别在各自规则位置
    #           立即出现 Proof 步骤；T-Out 的入口快照已经包含
    #           x:Int 和输入动作建立的新鲜符号。
    # 检查内容：规则先序编号、输入作用域产生的环境变化、逐层候选类型和
    #           公式判定与规则展开的严格顺序。
    # 论文对应：Section 4.2/Table 2 的环境判断、T-sigma、T-In、T-Out、T-End。
    def test_trace_exposes_rule_order_and_input_environment_change(self) -> None:
        """规则轨迹应让用户看见输入值如何进入后继类型检查上下文。"""

        report = self._report()

        self.assertEqual(report.verdict, Verdict.TRUE)
        self.assertEqual(
            tuple(step.rule for step in report.steps),
            (
                "environment",
                "T-||",
                "T-sigma",
                "Proof",
                "T-In",
                "T-Out",
                "Proof",
                "T-End",
            ),
        )
        self.assertEqual(
            tuple(step.number for step in report.steps),
            (1, 2, 3, 4, 5, 6, 7, 8),
        )

        input_step = next(step for step in report.steps if step.rule == "T-In")
        output_step = next(step for step in report.steps if step.rule == "T-Out")
        self.assertEqual(input_step.gamma, ())
        self.assertEqual(output_step.gamma, (("x", "Int"),))
        self.assertTrue(
            any(name == "x" and "__input" in term for name, term in output_step.symbolic_state)
        )
        self.assertIn("ch?.(ch!.(0))", input_step.result)
        self.assertIn("ch!.(0)", output_step.result)
        proof_steps = tuple(step for step in report.steps if step.rule == "Proof")
        self.assertEqual(len(proof_steps), 2)
        self.assertTrue(all("= true" in step.result for step in proof_steps))
        output_obligation = next(
            obligation
            for obligation in report.obligations
            if obligation.rule == "T-Out"
        )
        self.assertIsNotNone(output_obligation.proof_formula)

    # 测试输入：与上一测试相同的成功通信报告。
    # 预期行为：多行文本明确区分总体 Verdict、候选类型、规则执行、逻辑义务和诊断。
    # 检查内容：关键标题、可读 Theta、T-In/T-Out 说明、单独的 FOL/dL
    #           公式清单及统计数量；本案例没有 ODE，因此 dL 清单应明确为空。
    # 论文对应：推导树和横线以上的逻辑前提在实现报告中分区展示。
    def test_detailed_text_separates_inference_from_proof_evidence(self) -> None:
        """详细文本不应把“类型已生成”和“证明义务为真”合并成一个模糊状态。"""

        rendered = self._report().format_detailed()

        expected_fragments = (
            "总体结论 : true",
            "类型生成 : 成功",
            "推导类型 : ch?.(ch!.(0))",
            "=== 规则执行过程 ===",
            "T-In @ K1",
            "T-Out @ K1",
            "Gamma    : x:Int",
            "Theta    : ch:{eta:Int | true}",
            "=== 本次检查的一阶逻辑（FOL）公式 ===",
            "[FOL01] 对应 O01 | 有效 | 已证明 | T-sigma | STATE",
            "[FOL02] 对应 O02 | 有效 | 已证明 | T-Out | FOL",
            "实际检查公式:",
            "=== 本次检查的微分动态逻辑（dL）公式 ===",
            "(无 dL 公式)",
            "=== 顺序公式判定记录 ===",
            "[O02] 有效 | 已证明 | T-Out | FOL",
            "论文前提 : [T-Out]  phi => refinement{e/eta}",
            "规则生成公式（原始）:",
            "证明器实际输入:",
            "判定后端 : Z3 有效性检查",
            "处理状态 : 已解决",
            "=== 未解决或未通过的证明义务 ===",
            "(无；所有已生成证明义务均已证明)",
            "Proof @ T-Out",
            "=== 诊断信息 ===",
            "规则步骤 : 8",
            "证明记录 : 2",
            "有效义务 : 2 (true=2, false=0, unknown=0)",
            "遗留义务 : 0 (未通过=0, 待证明=0)",
        )
        for fragment in expected_fragments:
            with self.subTest(fragment=fragment):
                self.assertIn(fragment, rendered)

    # 测试输入：具有非平凡 safety 和有限自然后继的 ODE，dL 后端固定返回 unknown。
    # 预期行为：两个 ODE 候选都在首条 unknown safety premise 处停止，因此
    #           不伪造唯一类型，只保留两条已经实际判定的候选证据。
    # 检查内容：候选标记、单独的 dL 公式清单、选择诊断和未选候选证据区。
    # 论文对应：Table 2 两条带 fallback ODE premise 必须保留，不能因后端缺失而隐藏。
    def test_unknown_dl_formulas_are_repeated_in_unresolved_section(self) -> None:
        """报告应把尚未判定的 dL 公式集中列出并给出后续操作。"""

        process = Sequence.of(
            ODE(
                [("x", 1)],
                "x < 1",
                annotation=ODEAnnotation(safety="x <= 1", delay=1),
            ),
            Skip(),
        )
        report = check_hcsp(
            gamma={"x": ContinuousType()},
            theta={},
            configurations=[Configuration({"x": 0}, process)],
            path_condition="x == 0",
            dl_checker=lambda _obligation: None,
        )
        rendered = report.format_detailed()

        self.assertEqual(report.verdict, Verdict.UNKNOWN)
        self.assertIsNone(report.inferred_type)
        expected_fragments = (
            "未选候选 : 2",
            "candidate=communication-only",
            "candidate=natural-timeout",
            "[O02] 未选候选 | 待证明 | T-ODE-safety | DL",
            "[O03] 未选候选 | 待证明 | T-ODE-safety | DL",
            "=== 本次检查的微分动态逻辑（dL）公式 ===",
            "[DL01] 对应 O02 | 未选候选 | 待证明 | T-ODE-safety | DL",
            "[DL02] 对应 O03 | 未选候选 | 待证明 | T-ODE-safety | DL",
            "实际检查公式:",
            "[T-unrhd/T-unrhd-prime]",
            "配置的 dL 后端（通常为 KeYmaera X）",
            "=== 未选 ODE 候选的未决证据 ===",
            "stopped at an unknown premise",
            "遗留义务 : 0 (未通过=0, 待证明=0)",
        )
        for fragment in expected_fragments:
            with self.subTest(fragment=fragment):
                self.assertIn(fragment, rendered)


if __name__ == "__main__":
    unittest.main()
