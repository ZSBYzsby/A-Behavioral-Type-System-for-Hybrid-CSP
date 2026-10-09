r"""Regression tests for multi communication."""

from __future__ import annotations

import unittest

from hcsp_typechecker._internal import (
    Assert,
    BasicType,
    ChannelType,
    Configuration,
    EmptyType,
    InputChannel,
    InputType,
    InfiniteDelayType,
    OutputChannel,
    OutputType,
    Parallel,
    ParallelType,
    Sequence,
    Verdict,
    construct_type,
    types_equivalent,
)


class MultiScalarCommunicationTests(unittest.TestCase):
    r"""Tests for Multi Scalar Communication."""


    def test_multi_input_binds_each_scalar_and_assumes_joint_refinement(self) -> None:
        r"""Verify multi input binds each scalar and assumes joint refinement."""

        process = Sequence.of(
            InputChannel("data", ("x", "ready")),
            Assert("x >= 0 and ready"),
        )
        report = construct_type(
            gamma={},
            theta={
                "data": ChannelType(
                    (BasicType.INT, BasicType.BOOL),
                    "eta1 >= 0 and eta2",
                )
            },
            configurations=[Configuration({}, process)],
        )

        self.assertEqual(report.verdict, Verdict.TRUE)
        self.assertTrue(
            types_equivalent(
                report.constructed_type,
                InfiniteDelayType(InputType("data", EmptyType())),
            )
        )
        self.assertIn("T-Assert", {item.rule for item in report.obligations})


    def test_multi_output_proves_callable_joint_refinement(self) -> None:
        r"""Verify multi output proves callable joint refinement."""

        report = construct_type(
            gamma={"x": BasicType.INT, "limit": BasicType.INT},
            theta={
                "pair": ChannelType(
                    (BasicType.INT, BasicType.INT),
                    lambda left, right: left < right,
                    binders=("left", "right"),
                )
            },
            path_condition="x < limit",
            configurations=[
                Configuration(
                    {"x": 1, "limit": 2},
                    OutputChannel("pair", ("x", "limit")),
                )
            ],
        )

        self.assertEqual(report.verdict, Verdict.TRUE)
        self.assertTrue(
            types_equivalent(
                report.constructed_type,
                InfiniteDelayType(OutputType("pair", EmptyType())),
            )
        )
        t_out = [item for item in report.obligations if item.rule == "T-Out"]
        self.assertEqual(len(t_out), 1)
        self.assertEqual(t_out[0].verdict, Verdict.TRUE)


    def test_input_and_output_arity_must_match_channel_signature(self) -> None:
        r"""Verify input and output arity must match channel signature."""

        channel = ChannelType((BasicType.INT, BasicType.BOOL))
        reports = (
            construct_type(
                gamma={},
                theta={"data": channel},
                configurations=[Configuration({}, InputChannel("data", "x"))],
            ),
            construct_type(
                gamma={},
                theta={"data": channel},
                configurations=[
                    Configuration({}, OutputChannel("data", (1, True, 2)))
                ],
            ),
        )

        expected_fragments = ("got 1 targets", "got 3 expressions")
        for report, fragment in zip(reports, expected_fragments):
            with self.subTest(fragment=fragment):
                self.assertEqual(report.verdict, Verdict.FALSE)
                self.assertIsNone(report.constructed_type)
                self.assertTrue(
                    any(fragment in item.message for item in report.diagnostics)
                )


    def test_each_output_slot_is_type_checked_independently(self) -> None:
        r"""Verify each output slot is type checked independently."""

        report = construct_type(
            gamma={},
            theta={
                "mixed": ChannelType((BasicType.INT, BasicType.BOOL))
            },
            configurations=[
                Configuration({}, OutputChannel("mixed", (True, 1)))
            ],
        )

        self.assertEqual(report.verdict, Verdict.FALSE)
        self.assertIsNone(report.constructed_type)
        messages = tuple(item.message for item in report.diagnostics)
        self.assertTrue(any("slot 1 expects Int, got Bool" in text for text in messages))
        self.assertTrue(any("slot 2 expects Bool, got Nat" in text for text in messages))


    def test_existing_input_target_uses_safe_subtype_direction(self) -> None:
        r"""Verify existing input target uses safe subtype direction."""

        unsafe = construct_type(
            gamma={"x": BasicType.INT},
            theta={"ch": ChannelType(BasicType.REAL)},
            configurations=[Configuration({}, InputChannel("ch", "x"))],
        )
        safe = construct_type(
            gamma={"x": BasicType.REAL},
            theta={"ch": ChannelType(BasicType.INT)},
            configurations=[Configuration({}, InputChannel("ch", "x"))],
        )

        self.assertEqual(unsafe.verdict, Verdict.FALSE)
        self.assertIsNone(unsafe.constructed_type)
        self.assertTrue(
            any(
                "has type Int, channel slot carries Real" in item.message
                for item in unsafe.diagnostics
            )
        )
        self.assertEqual(safe.verdict, Verdict.TRUE)
        self.assertTrue(
            types_equivalent(
                safe.constructed_type,
                InfiniteDelayType(InputType("ch", EmptyType())),
            )
        )


    def test_parallel_multi_input_and_output_keep_one_behavior_action(self) -> None:
        r"""Verify parallel multi input and output keep one behavior action."""

        system = Parallel(
            InputChannel("pair", ("x", "y")),
            OutputChannel("pair", (1, 2)),
        )
        report = construct_type(
            gamma={},
            theta={
                "pair": ChannelType((BasicType.INT, BasicType.INT))
            },
            configurations=[Configuration({}, system)],
        )
        expected = ParallelType(
            (
                InfiniteDelayType(InputType("pair", EmptyType())),
                InfiniteDelayType(OutputType("pair", EmptyType())),
            )
        )

        self.assertEqual(report.verdict, Verdict.TRUE)
        self.assertTrue(types_equivalent(report.constructed_type, expected))


if __name__ == "__main__":
    unittest.main()
