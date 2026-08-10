"""验证类型构造器采用显式子 judgment 推导架构。

测试内容：

* 构造器对象只提供 ``construct(request)``，不保留旧 ``check`` 兼容入口；
* 每个 ``rule_t_*`` 方法是否只返回 ``RuleExpansion``；
* 规则函数是否保持只展开一层，不直接求解子规则或调用证明器；
* 一次含 ODE 的真实推导是否依次经过 configuration、system、process 和 event
  四类子 judgment，并在报告中展示 formula/child premises；
* dL 后端是否在相应 formula premise 位置立即运行。

预期行为：规则函数只描述推导树的一层；统一求解器递归处理 child judgment，
公式 premise 由求解器当场判定，规则函数本身仍只描述一层推导树。

论文对应：Table 2 横线下方是 conclusion judgment，横线上方分为逻辑公式
premises 与子 judgments；实现按它们在 ``RuleExpansion`` 中的顺序求解。
"""

from __future__ import annotations

import ast
import inspect
import unittest
from typing import Any, get_type_hints

import hcsp_typechecker.typechecking.constructor as constructor_module
from hcsp_typechecker._internal import (
    Configuration,
    ODE,
    ODEAnnotation,
    TypeConstructor,
    TypeConstructionRequest,
    Verdict,
)


class ExplicitSubjudgmentArchitectureTests(unittest.TestCase):
    """锁定“规则展开”和“premise 求解”之间的架构边界。"""

    # 测试输入：TypeConstructor 的公开实例方法集合。
    # 预期行为：正式入口命名为 construct；旧 check 名称完全不存在。
    # 检查内容：同时防止兼容别名悄悄恢复，给未来 TypeChecker 留出独立语义。
    # 论文对应：当前对象负责从推导请求构造类型，而不是检查用户给定的类型。
    def test_constructor_uses_construct_entrypoint_without_check_alias(self) -> None:
        """TypeConstructor 的动词应准确表达“构造类型”职责。"""

        self.assertTrue(callable(getattr(TypeConstructor, "construct", None)))
        self.assertFalse(hasattr(TypeConstructor, "check"))

    # 测试输入：constructor.py 中当前全部 rule_t_* 方法的 Python AST 和类型标注。
    # 预期行为：所有规则返回 _RuleExpansion，且规则体不调用任何 _solve_*/_infer_*
    #           入口、不直接调用 _decide_proof，也不递归调用其他 rule_t_* 方法。
    # 检查内容：返回类型以及规则函数调用图中的禁止边。
    # 论文对应：规则只由 conclusion 产生 premises，统一引擎负责推导树递归。
    def test_rules_only_expand_conclusions_into_premises(self) -> None:
        """规则函数必须保持为纯粹的一层推导展开入口。"""

        source = inspect.getsource(constructor_module.TypeConstructor)
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
                method = getattr(TypeConstructor, rule.name)
                hints = get_type_hints(method, vars(constructor_module))
                self.assertIs(hints["return"], constructor_module._RuleExpansion)

                forbidden_calls: list[str] = []
                for call in (node for node in ast.walk(rule) if isinstance(node, ast.Call)):
                    called = ast.unparse(call.func)
                    if (
                        called.startswith("self._solve_")
                        or called.startswith("self._infer_")
                        or called.startswith("self.rule_t_")
                        or called == "self._decide_proof"
                    ):
                        forbidden_calls.append(called)
                self.assertEqual(forbidden_calls, [])

    # 测试输入：带显式时钟边界的有限 ODE，其规则同时产生 dL 公式、事件反应和自然后继。
    # 预期行为：统一分派器实际看到四层 judgment；报告中的 T-sigma/T-ODE 说明
    #           分别列出 state formula、system、dL formula、event 和 process premise。
    # 检查内容：运行时 judgment 类别、候选类型、premise 轨迹，以及后端调用
    #           瞬间已经完成的 Proof 步骤和义务记录。
    # 论文对应：T-sigma、连续演化规则的公式 premise 与子 judgment premise。
    def test_runtime_solver_visits_all_judgment_layers(self) -> None:
        """一次 ODE 推导应经过显式 judgment 树并就地判定公式。"""

        proof_observations: list[
            tuple[str, tuple[str, ...], tuple[str, ...]]
        ] = []
        constructor: TypeConstructor

        # 功能：记录后端被调用时的执行轨迹，并唯一证明 boundary 候选。
        def observing_backend(obligation: Any) -> bool:
            """确认每条 dL premise 都在其推导位置立即进入证明后端。"""

            role = getattr(obligation.formula, "role", "")
            proof_observations.append(
                (
                    role,
                    tuple(step.rule for step in constructor.steps),
                    tuple(item.rule for item in constructor.obligations),
                )
            )
            return role == "boundary"

        constructor = TypeConstructor(dl_checker=observing_backend)
        visited: list[str] = []
        original_solver = constructor._solve_child_judgment

        def observing_solver(judgment):
            """记录统一分派器收到的 judgment 类别，再保持原求解语义。"""

            visited.append(type(judgment).__name__)
            return original_solver(judgment)

        constructor._solve_child_judgment = observing_solver  # type: ignore[method-assign]
        report = constructor.construct(
            TypeConstructionRequest(
                gamma={},
                theta={},
                configurations=[
                    Configuration(
                        {},
                        ODE((), "t < 1", annotation=ODEAnnotation(delay=1)),
                    )
                ],
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
        self.assertIn("process[T-End]", ode_step.detail)
        step_rules = tuple(step.rule for step in report.steps)
        self.assertNotIn("T-ODE-Select", step_rules)
        self.assertIn("Proof", step_rules)
        self.assertEqual(
            tuple(item[0] for item in proof_observations),
            ("boundary",),
        )
        for _role, rules_at_call, obligations_at_call in proof_observations:
            with self.subTest(role=_role):
                self.assertEqual(rules_at_call[-1], "Proof")
                self.assertEqual(
                    obligations_at_call,
                    ("T-sigma", "T-ODE-safety"),
                )


if __name__ == "__main__":
    unittest.main()
