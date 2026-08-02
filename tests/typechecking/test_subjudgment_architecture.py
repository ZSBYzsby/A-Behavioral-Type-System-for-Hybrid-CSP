"""验证类型检查器采用显式子 judgment 推导架构。

测试内容：

* 每个 ``rule_t_*`` 方法是否只返回 ``RuleExpansion``；
* 规则函数内部是否不再直接求解子规则或写入公共 Proof Pool；
* 一次含 ODE 的真实推导是否依次经过 configuration、system、process 和 event
  四类子 judgment，并在报告中展示 formula/child premises。

预期行为：规则函数只描述推导树的一层；统一求解器递归处理 child judgment，
公式 premise 统一进入 Pool，候选类型构造完成后证明器才运行。

论文对应：Table 2 横线下方是 conclusion judgment，横线上方分为逻辑公式
premises 与子 judgments；实现使用同一公共 Pool 汇总逻辑前提。
"""

from __future__ import annotations

import ast
import inspect
import unittest
from typing import get_type_hints

import hcsp_typechecker.checker as checker_module
from hcsp_typechecker import Configuration, ODE, TypeChecker, TypingJudgment, Verdict


class ExplicitSubjudgmentArchitectureTests(unittest.TestCase):
    """锁定“规则展开”和“premise 求解”之间的架构边界。"""

    # 测试输入：checker.py 中当前全部 rule_t_* 方法的 Python AST 和类型标注。
    # 预期行为：所有规则返回 _RuleExpansion，且规则体不调用任何 _solve_*/_infer_*
    #           入口、不直接写 proof_pool，也不直接递归调用其他 rule_t_* 方法。
    # 检查内容：返回类型以及规则函数调用图中的禁止边。
    # 论文对应：规则只由 conclusion 产生 premises，统一引擎负责推导树递归。
    def test_rules_only_expand_conclusions_into_premises(self) -> None:
        """规则函数必须保持为纯粹的一层推导展开入口。"""

        source = inspect.getsource(checker_module.TypeChecker)
        tree = ast.parse(source)
        class_node = tree.body[0]
        self.assertIsInstance(class_node, ast.ClassDef)

        rules = [
            node
            for node in class_node.body
            if isinstance(node, ast.FunctionDef) and node.name.startswith("rule_t_")
        ]
        self.assertTrue(rules)

        for rule in rules:
            with self.subTest(rule=rule.name):
                method = getattr(TypeChecker, rule.name)
                hints = get_type_hints(method, vars(checker_module))
                self.assertIs(hints["return"], checker_module._RuleExpansion)

                forbidden_calls: list[str] = []
                for call in (node for node in ast.walk(rule) if isinstance(node, ast.Call)):
                    called = ast.unparse(call.func)
                    if (
                        called.startswith("self._solve_")
                        or called.startswith("self._infer_")
                        or called.startswith("self.rule_t_")
                        or called == "self.proof_pool.append"
                    ):
                        forbidden_calls.append(called)
                self.assertEqual(forbidden_calls, [])

    # 测试输入：ODE.wait(1)，其规则同时产生 dL 公式、事件反应和自然后继。
    # 预期行为：统一分派器实际看到四层 judgment；报告中的 T-sigma/T-ODE 说明
    #           分别列出 state formula、system、dL formula、event 和 process premise。
    # 检查内容：运行时 judgment 类别、候选类型生成、详细 premise 轨迹与 Pool 顺序。
    # 论文对应：T-sigma、连续演化规则的公式 premise 与子 judgment premise。
    def test_runtime_solver_visits_all_judgment_layers(self) -> None:
        """一次 ODE 推导应经过显式 judgment 树并把公式统一放入 Pool。"""

        checker = TypeChecker(dl_checker=lambda _obligation: True)
        visited: list[str] = []
        original_solver = checker._solve_child_judgment

        def observing_solver(judgment):
            """记录统一分派器收到的 judgment 类别，再保持原求解语义。"""

            visited.append(type(judgment).__name__)
            return original_solver(judgment)

        checker._solve_child_judgment = observing_solver  # type: ignore[method-assign]
        report = checker.check(
            TypingJudgment(
                gamma={},
                theta={},
                configurations=[Configuration({}, ODE.wait(1))],
            )
        )

        self.assertEqual(report.verdict, Verdict.TRUE)
        self.assertTrue(
            {
                "_ConfigurationJudgment",
                "_SystemJudgment",
                "_ProcessJudgment",
                "_EventJudgment",
            }.issubset(visited)
        )

        sigma_step = next(step for step in report.steps if step.rule == "T-sigma")
        ode_step = next(step for step in report.steps if step.rule == "T-ODE")
        self.assertIn("formula[state:T-sigma]", sigma_step.detail)
        self.assertIn("system[K1]", sigma_step.detail)
        self.assertIn("formula[dl:T-ODE-safety]", ode_step.detail)
        self.assertIn("formula[dl:T-ODE-boundary]", ode_step.detail)
        self.assertIn("event[E]", ode_step.detail)
        self.assertIn("process[skip]", ode_step.detail)
        self.assertEqual(report.steps[-1].rule, "Proof-Pool")


if __name__ == "__main__":
    unittest.main()
