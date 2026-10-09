r"""Regression tests for parsed source integration. Paper reference: Table 2, Definition 4.1."""

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
    r"""Tests for Parsed Source Constructor Integration."""


    def test_parsed_sequential_source_is_accepted_by_constructor(self) -> None:
        r"""Verify parsed sequential source is accepted by constructor."""

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


    def test_non_boolean_refinement_is_rejected_by_constructor(self) -> None:
        r"""Verify non boolean refinement is rejected by constructor."""

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


    def test_unused_invalid_refinement_is_rejected_by_constructor(self) -> None:
        r"""Verify unused invalid refinement is rejected by constructor."""

        sources_and_fragments = (
            (
                """gamma()
theta(bad: channel(value: Real) where(value + 1))
process {{skip}}""",
                "Expected Bool formula",
            ),
            (
                """gamma()
theta(bad: channel(value: Real) where(value >= missing))
process {{skip}}""",
                "Unbound variable 'missing'",
            ),
        )

        for source, fragment in sources_and_fragments:
            with self.subTest(fragment=fragment):
                parsed = parse_hcsp_source(source)
                report = construct_type(
                    gamma=parsed.gamma,
                    theta=parsed.theta,
                    configurations=(parsed.process,),
                )
                self.assertEqual(report.verdict, Verdict.FALSE)
                self.assertIsNone(report.constructed_type)
                self.assertTrue(
                    any(fragment in item.message for item in report.diagnostics)
                )


    def test_unused_well_formed_refinement_can_reference_parameter(self) -> None:
        r"""Verify unused well formed refinement can reference parameter."""

        parsed = parse_hcsp_source(
            """gamma()
parameters(limit: Real) where(limit >= 0)
theta(unused: channel(value: Real) where(value >= limit))
process {{skip}}"""
        )
        report = construct_type(
            gamma=parsed.gamma,
            theta=parsed.theta,
            parameters=parsed.parameters,
            configurations=(parsed.process,),
        )

        self.assertEqual(report.verdict, Verdict.TRUE, report.format_detailed())
        self.assertIsNotNone(report.constructed_type)


    def test_parsed_parameter_constraint_is_used_as_constructor_background(self) -> None:
        r"""Verify parsed parameter constraint is used as constructor background."""

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
        self.assertIn('Parameter constraint', detailed)


    def test_parallel_components_share_gamma_and_parameters(self) -> None:
        r"""Verify parallel components share Gamma and parameters."""

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
            [
                {"left_state", "right_state"},
                {"left_state", "right_state"},
            ],
        )
        self.assertTrue(
            all("limit" not in gamma for gamma in t_sigma_gammas)
        )
        self.assertFalse(
            any(item.verdict is Verdict.FALSE for item in report.diagnostics)
        )


    def test_parsed_parameter_cannot_be_an_assignment_target(self) -> None:
        r"""Verify parsed parameter cannot be an assignment target."""

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


    def test_unsatisfiable_parsed_parameter_constraint_stops_construction(self) -> None:
        r"""Verify unsatisfiable parsed parameter constraint stops construction."""

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
