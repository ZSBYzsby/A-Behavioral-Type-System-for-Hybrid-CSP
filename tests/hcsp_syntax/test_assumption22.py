r"""Regression tests for assumption22. Paper reference: Assumption 2.2, Section 2.1."""

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
    Sequence,
    Skip,
    Var,
)


class Assumption22ConstructionTests(unittest.TestCase):
    r"""Tests for Assumption22 Construction."""


    def test_input_and_output_each_guard_a_recursive_call(self) -> None:
        r"""Verify input and output each guard a recursive call."""

        prefixes = (
            InputChannel("in", "value"),
            OutputChannel("out", 1),
        )
        for prefix in prefixes:
            with self.subTest(prefix=type(prefix).__name__):
                process = Mu("X", Sequence(prefix, Var("X")))
                self.assertIsInstance(process, Mu)


    def test_absent_bound_occurrence_is_vacuously_guarded(self) -> None:
        r"""Verify absent bound occurrence is vacuously guarded."""

        process = Mu("X", InternalChoice(Skip(), Var("Y")))
        self.assertIsInstance(process, Mu)


    def test_direct_unguarded_recursive_call_is_rejected(self) -> None:
        r"""Verify direct unguarded recursive call is rejected."""

        with self.assertRaisesRegex(
            ValueError,
            r"Assumption 2\.2 violated.*'X'.*body",
        ):
            Mu("X", Var("X"))


    def test_silent_prefixes_do_not_guard_recursion(self) -> None:
        r"""Verify silent prefixes do not guard recursion."""

        prefixes = (Skip(), Assign("x", 1), Assert("x >= 0"))
        for prefix in prefixes:
            with self.subTest(prefix=type(prefix).__name__):
                with self.assertRaisesRegex(ValueError, "Assumption 2.2"):
                    Mu("X", Sequence(prefix, Var("X")))


    def test_common_communication_prefix_guards_all_later_paths(self) -> None:
        r"""Verify common communication prefix guards all later paths."""

        body = Sequence.of(
            InputChannel("start", "v"),
            If(
                "v >= 0",
                Var("X"),
                InternalChoice(Var("X"), Var("X")),
            ),
        )
        self.assertIsInstance(Mu("X", body), Mu)


    def test_if_rejects_one_unguarded_recursive_branch(self) -> None:
        r"""Verify if rejects one unguarded recursive branch."""

        body = If(
            True,
            Sequence.of(OutputChannel("out", 1), Var("X")),
            Var("X"),
        )
        with self.assertRaisesRegex(ValueError, r"body\.else"):
            Mu("X", body)


    def test_internal_choice_rejects_one_unguarded_branch(self) -> None:
        r"""Verify internal choice rejects one unguarded branch."""

        body = InternalChoice(
            Sequence.of(InputChannel("in", "v"), Var("X")),
            Var("X"),
        )
        with self.assertRaisesRegex(ValueError, r"body\.branches\[1\]"):
            Mu("X", body)


    def test_all_internal_choice_branches_may_be_guarded(self) -> None:
        r"""Verify all internal choice branches may be guarded."""

        body = InternalChoice(
            Sequence.of(InputChannel("left", "v"), Var("X")),
            Sequence.of(OutputChannel("right", 1), Var("X")),
        )
        self.assertIsInstance(Mu("X", body), Mu)


    def test_choice_common_continuation_inherits_each_guarded_exit(self) -> None:
        r"""Verify choice common continuation inherits each guarded exit."""

        body = InternalChoice(
            InputChannel("left", "v"),
            OutputChannel("right", 1),
            continuation=Var("X"),
        )
        self.assertIsInstance(Mu("X", body), Mu)


    def test_choice_common_continuation_rejects_one_unguarded_exit(self) -> None:
        r"""Verify choice common continuation rejects one unguarded exit."""

        with self.assertRaisesRegex(ValueError, r"body\.continuation"):
            Mu(
                "X",
                InternalChoice(
                    InputChannel("left", "v"),
                    Skip(),
                    continuation=Var("X"),
                ),
            )


    def test_all_communicating_if_exits_guard_a_common_tail(self) -> None:
        r"""Verify all communicating if exits guard a common tail."""

        body = If(
            True,
            InputChannel("left", "v"),
            OutputChannel("right", 1),
            continuation=Var("X"),
        )
        self.assertIsInstance(Mu("X", body), Mu)


    def test_one_silent_if_exit_does_not_guard_a_common_tail(self) -> None:
        r"""Verify one silent if exit does not guard a common tail."""

        with self.assertRaisesRegex(ValueError, r"body\.continuation"):
            Mu(
                "X",
                If(
                    True,
                    InputChannel("left", "v"),
                    Skip(),
                    continuation=Var("X"),
                ),
            )


    def test_ode_event_prefix_guards_its_continuation(self) -> None:
        r"""Verify ODE event prefix guards its continuation."""

        events = EventChoice(
            (InputChannel("stop", "v"), Var("X")),
            (OutputChannel("alarm", 1), Var("X")),
        )
        body = ODE(
            [("x", 1)],
            "x <= 1",
            events,
            annotation=ODEAnnotation(delay=1),
        )
        self.assertIsInstance(Mu("X", body), Mu)


    def test_ode_does_not_guard_its_sequential_fallback(self) -> None:
        r"""Verify ODE does not guard its sequential fallback."""

        events = EventChoice((InputChannel("stop", "v"), Skip()))
        with self.assertRaisesRegex(ValueError, r"body\.continuation"):
            Mu(
                "X",
                ODE(
                    [("x", 1)],
                    "x <= 1",
                    events,
                    annotation=ODEAnnotation(delay=1),
                    continuation=Var("X"),
                ),
            )


    def test_nested_mu_respects_lexical_shadowing(self) -> None:
        r"""Verify nested mu respects lexical shadowing."""

        inner = Mu(
            "X",
            Sequence.of(InputChannel("inner", "v"), Var("X")),
        )
        self.assertIsInstance(Mu("X", inner), Mu)

        different_binder = Mu("Y", Var("X"))
        with self.assertRaisesRegex(ValueError, r"mu\[Y\]\.body"):
            Mu("X", different_binder)


if __name__ == "__main__":
    unittest.main()
