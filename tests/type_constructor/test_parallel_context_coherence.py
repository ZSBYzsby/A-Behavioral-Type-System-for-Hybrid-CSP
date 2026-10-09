r"""Regression tests for parallel context coherence. Paper reference: Table 2, Assumption 2.1."""

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
    r"""Tests for Parallel Context Coherence."""


    def test_every_component_uses_the_same_complete_gamma(self) -> None:
        r"""Verify every component uses the same complete Gamma."""

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


    def test_configuration_states_cannot_share_a_variable(self) -> None:
        r"""Verify configuration states cannot share a variable."""

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


    def test_nontrivial_global_path_cannot_be_overridden_locally(self) -> None:
        r"""Verify nontrivial global path cannot be overridden locally."""

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


    def test_parallel_local_paths_must_be_all_or_none(self) -> None:
        r"""Verify parallel local paths must be all or none."""

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


    def test_stateful_parallel_requires_explicit_configuration_leaves(self) -> None:
        r"""Verify stateful parallel requires explicit configuration leaves."""

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


    def test_explicit_stateful_leaves_form_a_valid_parallel_judgment(self) -> None:
        r"""Verify explicit stateful leaves form a valid parallel judgment."""

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


    def test_stateless_parallel_sugar_remains_available(self) -> None:
        r"""Verify stateless parallel sugar remains available."""

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
