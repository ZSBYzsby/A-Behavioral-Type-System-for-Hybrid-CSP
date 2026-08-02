"""验证 PPT 所述“先展开规则、后统一判定公式池”的两阶段架构。

测试内容：使用带有限 delay 的无后继 ODE 同时生成 state、自动恒真 safety 和
domain dL 前提，并通过可观察的自定义 dL 后端确认外部证明器不会在类型规则
递归期间提前运行。

预期行为：全部候选类型和全部 Pending Proof 都先生成；随后出现唯一的
``Proof-Pool`` 阶段，后端调用发生在该阶段，最终 ``CheckReport.obligations``
只保存统一判定后的不可变结果。

论文对应：项目采用公共公式池 Pool；Table 2 中的逻辑公式 premise 与子
judgment premise 分阶段处理。
"""

from __future__ import annotations

import unittest
from typing import Any

from hcsp_typechecker import (
    BasicType,
    Configuration,
    ODE,
    ODEAnnotation,
    TypeChecker,
    TypingJudgment,
    Verdict,
)


class DeferredProofPoolTests(unittest.TestCase):
    """保证证明器只在类型推导完成后的统一 Pool 阶段运行。"""

    # 测试输入：x'=0、非平凡不变域 x<=1、safety=true、delay=1 的有限 ODE。
    # 预期行为：自定义 dL 后端被调用时，规则轨迹已经以 Proof-Pool 结尾，
    #           Pool 已包含全部三条义务，而最终 decided obligations 尚未写回。
    # 检查内容：调用时机、Pool 完整性、统一判定后的义务顺序和最终 Verdict。
    # 论文对应：先递归处理子 judgment 并收集公式，最后统一检查 Pool。
    def test_dl_backend_runs_only_after_all_rules_populate_pool(self) -> None:
        """dL 后端不得在 T-ODE 正在构造候选类型时被提前调用。"""

        observations: list[tuple[str, tuple[str, ...], int, int]] = []
        checker: TypeChecker

        def deferred_backend(obligation: Any) -> bool:
            """记录后端调用瞬间的规则轨迹、Pending Pool 和 decided 列表。"""

            observations.append(
                (
                    obligation.rule,
                    tuple(step.rule for step in checker.steps),
                    len(checker.proof_pool),
                    len(checker.obligations),
                )
            )
            return True

        checker = TypeChecker(dl_checker=deferred_backend)
        process = ODE(
            [("x", 0)],
            "x <= 1",
            annotation=ODEAnnotation(safety=True, delay=1),
        )
        report = checker.check(
            TypingJudgment(
                gamma={"x": BasicType.REAL},
                theta={},
                configurations=[Configuration({"x": 0}, process)],
                path_condition="x == 0",
            )
        )

        self.assertEqual(report.verdict, Verdict.TRUE)
        self.assertEqual(report.steps[-1].rule, "Proof-Pool")
        self.assertEqual(len(checker.proof_pool), 3)
        self.assertEqual(
            tuple(item.rule for item in report.obligations),
            ("T-sigma", "T-ODE-safety", "T-ODE-domain"),
        )
        self.assertEqual(
            tuple(item.verdict for item in report.obligations),
            (Verdict.TRUE, Verdict.TRUE, Verdict.TRUE),
        )

        # safety=true 在 Pool 内统一判真，不需要调用外部后端；domain 才进入
        # deferred_backend。调用时 decided 列表还没有整体写回。
        self.assertEqual(
            tuple(item[0] for item in observations),
            ("T-ODE-domain",),
        )
        for _, rules, pending_count, decided_count in observations:
            self.assertEqual(rules[-1], "Proof-Pool")
            self.assertEqual(pending_count, 3)
            self.assertEqual(decided_count, 0)


if __name__ == "__main__":
    unittest.main()
