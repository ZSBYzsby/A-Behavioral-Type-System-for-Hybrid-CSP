r"""Regression tests for subjudgment architecture. Paper reference: Table 2."""

from __future__ import annotations

import ast
import inspect
import unittest
from typing import Any, get_type_hints

import hcsp_typechecker.backend.common.rule_engine as constructor_module
from hcsp_typechecker._internal import (
    Configuration,
    ODE,
    ODEAnnotation,
    Sequence,
    Skip,
    TypeConstructor,
    TypeConstructionRequest,
    Verdict,
)


class ExplicitSubjudgmentArchitectureTests(unittest.TestCase):
    r"""Tests for Explicit Subjudgment Architecture."""


    def test_constructor_uses_construct_entrypoint_without_check_alias(self) -> None:
        r"""Verify constructor uses construct entrypoint without check alias."""

        self.assertTrue(callable(getattr(TypeConstructor, "construct", None)))
        self.assertFalse(hasattr(TypeConstructor, "check"))


    def test_rules_only_expand_conclusions_into_premises(self) -> None:
        r"""Verify rules only expand conclusions into premises."""

        source = inspect.getsource(constructor_module.Table2RuleEngine)
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


    def test_runtime_solver_visits_all_judgment_layers(self) -> None:
        r"""Verify runtime solver visits all judgment layers."""

        proof_observations: list[
            tuple[str, tuple[str, ...], tuple[str, ...]]
        ] = []
        constructor: TypeConstructor


        def observing_backend(obligation: Any) -> bool:
            r"""Check that dL proofs occur at their ordered premise positions."""

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
        original_preparer = constructor._prepare_child_judgment

        def observing_preparer(judgment):
            r"""Record judgment kinds prepared by the explicit work stack."""

            visited.append(type(judgment).__name__)
            return original_preparer(judgment)

        constructor._prepare_child_judgment = observing_preparer  # type: ignore[method-assign]
        report = constructor.construct(
            TypeConstructionRequest(
                gamma={},
                theta={},
                configurations=[
                    Configuration(
                        {},
                        Sequence.of(
                            ODE(
                                (),
                                "t < 1",
                                annotation=ODEAnnotation(delay=1),
                            ),
                            Skip(),
                        ),
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
        self.assertIn("process[skip]", ode_step.detail)
        step_rules = tuple(step.rule for step in report.steps)
        self.assertIn("Proof", step_rules)
        self.assertEqual(
            tuple(item[0] for item in proof_observations),
            ("domain", "boundary"),
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
