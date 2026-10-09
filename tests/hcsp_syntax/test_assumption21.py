r"""Regression tests for assumption21. Paper reference: Assumption 2.1, Section 2.1."""

from __future__ import annotations

import unittest

from hcsp_typechecker._internal import (
    Assert,
    Assign,
    EmptyEvent,
    EventChoice,
    If,
    InputChannel,
    InternalChoice,
    Mu,
    ODE,
    ODEAnnotation,
    OutputChannel,
    Parallel,
    Sequence,
    Skip,
    Var,
)


class Assumption21ConstructionTests(unittest.TestCase):
    r"""Tests for Assumption21 Construction."""
    def test_input_target_binds_sequence_continuation(self) -> None:
        r"""Verify input target binds sequence continuation."""

        process = Sequence(
            InputChannel("sensor", "x"),
            Assert("x >= 0"),
        )
        self.assertIsInstance(process, Sequence)

        branched_prefix = If(
            True,
            InputChannel("sensor", "x"),
            Skip(),
            continuation=Assert("x >= 0"),
        )
        self.assertIsInstance(branched_prefix, If)
        self.assertIsInstance(branched_prefix.continuation, Assert)


    def test_input_cannot_bind_a_previously_free_variable(self) -> None:
        r"""Verify input cannot bind a previously free variable."""

        with self.assertRaisesRegex(
            ValueError,
            r"free and bound variables overlap: x",
        ):
            Sequence(
                Assert("x >= 0"),
                InputChannel("sensor", "x"),
            )


    def test_choice_rejects_free_and_bound_name_overlap(self) -> None:
        r"""Verify choice rejects free and bound name overlap."""

        with self.assertRaisesRegex(ValueError, r"overlap: x"):
            InternalChoice(
                InputChannel("left", "x"),
                Assert("x >= 0"),
            )


    def test_event_input_binds_its_branch_continuation(self) -> None:
        r"""Verify event input binds its branch continuation."""

        reaction = EventChoice(
            (InputChannel("sensor", "x"), Assert("x >= 0")),
        )
        self.assertIsInstance(reaction, EventChoice)


    def test_event_alternative_cannot_reuse_input_target_name(self) -> None:
        r"""Verify event alternative cannot reuse input target name."""

        other_branch = (OutputChannel("report", 1), Assert("x >= 0"))
        with self.assertRaisesRegex(ValueError, r"overlap: x"):
            EventChoice(
                other_branch,
                (InputChannel("sensor", "x"), Skip()),
            )


    def test_mu_binds_occurrences_in_its_body(self) -> None:
        r"""Verify mu binds occurrences in its body."""

        recursive = Mu(
            "X",
            Sequence(OutputChannel("guard", 0), Var("X")),
        )
        self.assertIsInstance(recursive, Mu)


    def test_mu_free_and_bound_process_names_cannot_overlap(self) -> None:
        r"""Verify mu free and bound process names cannot overlap."""

        recursive = Mu(
            "X",
            Sequence(OutputChannel("guard", 0), Var("X")),
        )
        with self.assertRaisesRegex(
            ValueError,
            r"overlap: X \(process variable\)",
        ):
            InternalChoice(Var("X"), recursive)


    def test_parallel_rejects_shared_value_variables(self) -> None:
        r"""Verify parallel rejects shared value variables."""

        with self.assertRaisesRegex(
            ValueError,
            r"parallel components share variables: x",
        ):
            Parallel(Assign("x", 1), Assert("x >= 0"))


    def test_parallel_rejects_shared_process_variables(self) -> None:
        r"""Verify parallel rejects shared process variables."""

        with self.assertRaisesRegex(
            ValueError,
            r"share variables: X \(process variable\)",
        ):
            Parallel(Mu("X", Skip()), Mu("X", Skip()))


    def test_parallel_rejects_shared_input_channels(self) -> None:
        r"""Verify parallel rejects shared input channels."""

        with self.assertRaisesRegex(ValueError, r"share input channels: c"):
            Parallel(
                InputChannel("c", "x"),
                InputChannel("c", "y"),
            )


    def test_parallel_rejects_shared_output_channels(self) -> None:
        r"""Verify parallel rejects shared output channels."""

        with self.assertRaisesRegex(ValueError, r"share output channels: c"):
            Parallel(OutputChannel("c", 1), OutputChannel("c", 2))


    def test_parallel_allows_complementary_channel_directions(self) -> None:
        r"""Verify parallel allows complementary channel directions."""

        system = Parallel(
            InputChannel("c", "x"),
            OutputChannel("c", 1),
        )
        self.assertIsInstance(system, Parallel)


    def test_nested_parallel_checks_aggregated_channels(self) -> None:
        r"""Verify nested parallel checks aggregated channels."""

        nested = Parallel(
            OutputChannel("d", 1),
            OutputChannel("c", 2),
        )
        with self.assertRaisesRegex(ValueError, r"share output channels: c"):
            Parallel(OutputChannel("c", 0), nested)


    def test_parallel_ode_clocks_are_fresh_and_excluded_from_v(self) -> None:
        r"""Verify parallel ODE clocks are fresh and excluded from v."""

        left = ODE([], True, annotation=ODEAnnotation(delay=1))
        right = ODE([], True, annotation=ODEAnnotation(delay=2))
        system = Parallel(left, right)

        self.assertIs(system.left, left)
        self.assertIs(system.right, right)
        self.assertIsNot(left.local_clock, right.local_clock)
        self.assertEqual(left.get_vars(), set())
        self.assertEqual(right.get_vars(), set())


    def test_ode_variable_cannot_be_rebound_by_interrupt_input(self) -> None:
        r"""Verify ODE variable cannot be rebound by interrupt input."""

        interrupts = EventChoice((InputChannel("stop", "x"), Skip()))
        with self.assertRaisesRegex(ValueError, r"overlap: x"):
            ODE(
                [("x", 1)],
                "x <= 10",
                interrupts,
                annotation=ODEAnnotation(delay=1),
            )


if __name__ == "__main__":
    unittest.main()
