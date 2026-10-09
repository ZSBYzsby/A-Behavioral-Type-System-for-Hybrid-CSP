r"""Regression tests for unified source. Paper reference: Section 2.1, Table 2."""

from __future__ import annotations

import unittest

from hcsp_typechecker._internal import (
    BasicType,
    BooleanExpr,
    ChannelType,
    CompareExpr,
    ContinuousType,
    HCSPInputError,
    InputChannel,
    Literal,
    OutputChannel,
    Parallel,
    ParsedHCSPSource,
    Skip,
    Variable,
    parse_expression,
    parse_hcsp_source,
)


def _source_with(
    *,
    gamma: str = "",
    theta: str = "",
    process: str = "{{skip}}",
) -> str:
    r"""Build a minimal complete input around the test statements."""

    return f"gamma({gamma})\ntheta({theta})\nprocess {process}"


class UnifiedSourceConversionTests(unittest.TestCase):
    r"""Tests for Unified Source Conversion."""


    def test_complete_source_lowers_all_environment_forms(self) -> None:
        r"""Verify complete source lowers all environment forms."""

        source = """
            gamma(
                motion: continuous(velocity, position),
                enabled: Bool,
                count: Nat,
                offset: Int,
                ratio: Rational,
                position: Real,
                velocity: Real
            )
            theta(
                sensor: channel(value: Real)
                    where(0 <= value and value <= 100),
                state: channel(index: Nat, accepted: Bool),
                exact: channel(delta: Rational),
                command: channel(mode: Int),
                always: channel(flag: Bool) where(true)
            )
            process {{skip}}
        """

        parsed = parse_hcsp_source(source)

        self.assertIsInstance(parsed, ParsedHCSPSource)
        self.assertEqual(
            parsed.gamma,
            {
                "motion": ContinuousType(("position", "velocity")),
                "enabled": BasicType.BOOL,
                "count": BasicType.NAT,
                "offset": BasicType.INT,
                "ratio": BasicType.RATIONAL,
                "position": BasicType.REAL,
                "velocity": BasicType.REAL,
            },
        )
        self.assertEqual(
            parsed.theta["sensor"],
            ChannelType(
                (BasicType.REAL,),
                refinement=BooleanExpr(
                    "and",
                    (
                        CompareExpr(
                            (Literal(0), Variable("value")),
                            ("<=",),
                        ),
                        CompareExpr(
                            (Variable("value"), Literal(100)),
                            ("<=",),
                        ),
                    ),
                ),
                binders=("value",),
            ),
        )
        self.assertEqual(
            parsed.theta["state"],
            ChannelType(
                (BasicType.NAT, BasicType.BOOL),
                refinement=True,
                binders=("index", "accepted"),
            ),
        )
        self.assertEqual(
            parsed.theta["exact"],
            ChannelType(
                BasicType.RATIONAL,
                refinement=True,
                binders=("delta",),
            ),
        )
        self.assertEqual(
            parsed.theta["command"],
            ChannelType(
                BasicType.INT,
                refinement=True,
                binders=("mode",),
            ),
        )
        self.assertIs(parsed.theta["always"].refinement, True)
        self.assertEqual(parsed.process, Skip())


    def test_empty_environments_are_valid(self) -> None:
        r"""Verify empty environments are valid."""

        parsed = parse_hcsp_source(_source_with())

        self.assertEqual(parsed.gamma, {})
        self.assertEqual(parsed.theta, {})
        self.assertEqual(parsed.process, Skip())


    def test_parallel_process_is_preserved_in_unified_source(self) -> None:
        r"""Verify parallel process is preserved in unified source."""

        source = _source_with(
            gamma="received: Int",
            theta="ch: channel(payload: Int)",
            process="{{ch!(0)}, {ch?(received)}}",
        )

        parsed = parse_hcsp_source(source)

        self.assertEqual(parsed.gamma, {"received": BasicType.INT})
        self.assertEqual(
            parsed.theta,
            {
                "ch": ChannelType(
                    BasicType.INT,
                    refinement=True,
                    binders=("payload",),
                )
            },
        )
        self.assertEqual(
            parsed.process,
            Parallel(
                OutputChannel("ch", 0),
                InputChannel("ch", "received"),
            ),
        )


    def test_parsed_environments_are_read_only_snapshots(self) -> None:
        r"""Verify parsed environments are read only snapshots."""

        original_gamma = {"x": BasicType.REAL}
        original_theta = {
            "ch": ChannelType(BasicType.REAL, binders=("value",))
        }
        parsed = ParsedHCSPSource(original_gamma, original_theta, Skip())

        original_gamma["x"] = BasicType.BOOL
        original_theta.clear()
        self.assertEqual(parsed.gamma["x"], BasicType.REAL)
        self.assertIn("ch", parsed.theta)
        with self.assertRaises(TypeError):
            parsed.gamma["x"] = BasicType.INT  # type: ignore[index]
        with self.assertRaises(AttributeError):
            parsed.theta.clear()  # type: ignore[attr-defined]


    def test_comments_and_separate_name_spaces_are_preserved(self) -> None:
        r"""Verify comments and separate name spaces are preserved."""

        source = """gamma(shared: Real)
/* Gamma and Theta stay in one token stream. */
theta(
    shared: channel(shared: Real) where(shared >= 0)
)
// The process section follows the same source positions.
process {{skip}}"""

        parsed = parse_hcsp_source(source)

        self.assertEqual(parsed.gamma, {"shared": BasicType.REAL})
        self.assertEqual(parsed.theta["shared"].binders, ("shared",))
        self.assertEqual(
            parsed.theta["shared"].refinement,
            parse_expression("shared >= 0"),
        )
        self.assertEqual(parsed.process, Skip())


    def test_refinement_semantics_remain_for_backend_validation(self) -> None:
        r"""Verify refinement semantics remain for backend validation."""

        source = _source_with(
            theta="bad: channel(value: Real) where(value + missing)"
        )

        parsed = parse_hcsp_source(source)

        self.assertEqual(
            parsed.theta["bad"].refinement,
            parse_expression("value + missing"),
        )


class UnifiedEnvironmentValidationTests(unittest.TestCase):
    r"""Tests for Unified Environment Validation."""


    def test_duplicate_environment_keys_are_rejected(self) -> None:
        r"""Verify duplicate environment keys are rejected."""

        cases = (
            (_source_with(gamma="x: Real, x: Int"), "x"),
            (
                _source_with(
                    gamma="x: Real, motion: continuous(x), motion: Real"
                ),
                "motion",
            ),
            (
                _source_with(
                    theta=(
                        "ch: channel(x: Int), "
                        "ch: channel(y: Real)"
                    )
                ),
                "ch",
            ),
        )
        for source, repeated_name in cases:
            with self.subTest(repeated_name=repeated_name):
                with self.assertRaises(HCSPInputError) as context:
                    parse_hcsp_source(source)
                self.assertEqual(context.exception.phase, "validation")
                self.assertEqual(context.exception.found, repeated_name)


    def test_only_canonical_basic_type_names_are_accepted(self) -> None:
        r"""Verify only canonical basic type names are accepted."""

        invalid_sources = (
            _source_with(gamma="x: bool"),
            _source_with(gamma="x: String"),
            _source_with(theta="ch: channel(x: integer)"),
            _source_with(theta="ch: channel(x: continuous(y))"),
        )
        for source in invalid_sources:
            with self.subTest(source=source.splitlines()[0]):
                with self.assertRaises(HCSPInputError) as context:
                    parse_hcsp_source(source)
                self.assertEqual(context.exception.phase, "syntax")


    def test_continuous_vector_structure_and_real_members_are_checked(self) -> None:
        r"""Verify continuous vector structure and Real members are checked."""

        cases = (
            (_source_with(gamma="motion: continuous()"), "syntax"),
            (
                _source_with(
                    gamma="x: Real, motion: continuous(x, x)"
                ),
                "validation",
            ),
            (
                _source_with(gamma="t: Real, motion: continuous(t)"),
                "validation",
            ),
            (
                _source_with(gamma="motion: continuous(x)"),
                "validation",
            ),
            (
                _source_with(gamma="x: Int, motion: continuous(x)"),
                "validation",
            ),
        )
        for source, phase in cases:
            with self.subTest(gamma_line=source.splitlines()[0]):
                with self.assertRaises(HCSPInputError) as context:
                    parse_hcsp_source(source)
                self.assertEqual(context.exception.phase, phase)


    def test_channel_arity_and_binder_uniqueness_are_checked(self) -> None:
        r"""Verify channel arity and binder uniqueness are checked."""

        cases = (
            (_source_with(theta="ch: channel()"), "syntax"),
            (
                _source_with(theta="ch: channel(x: Int, x: Real)"),
                "validation",
            ),
        )
        for source, phase in cases:
            with self.subTest(theta_line=source.splitlines()[1]):
                with self.assertRaises(HCSPInputError) as context:
                    parse_hcsp_source(source)
                self.assertEqual(context.exception.phase, phase)


    def test_unicode_environment_identifiers_are_lexical_errors(self) -> None:
        r"""Verify unicode environment identifiers are lexical errors."""

        invalid_sources = (
            _source_with(gamma="\u03b1\u03b2: Real"),
            _source_with(theta="\u03b3\u03b4: channel(x: Int)"),
            _source_with(theta="ch: channel(ｘ: Int)"),
        )
        for source in invalid_sources:
            with self.subTest(source=source):
                with self.assertRaises(HCSPInputError) as context:
                    parse_hcsp_source(source)
                self.assertEqual(context.exception.phase, "lexical")


class UnifiedSourceSyntaxTests(unittest.TestCase):
    r"""Tests for Unified Source Syntax."""


    def test_top_level_order_separators_and_required_sections_are_fixed(self) -> None:
        r"""Verify top level order separators and required sections are fixed."""

        invalid_sources = (
            "theta() process {{skip}}",
            "gamma() process {{skip}}",
            "gamma() theta()",
            "theta() gamma() process {{skip}}",
            "gamma(); theta() process {{skip}}",
            "gamma(x: Real,) theta() process {{skip}}",
            "gamma() theta(ch: channel(x: Int),) process {{skip}}",
            "gamma() theta() process {{skip}} extra",
        )
        for source in invalid_sources:
            with self.subTest(source=source):
                with self.assertRaises(HCSPInputError) as context:
                    parse_hcsp_source(source)
                self.assertEqual(context.exception.phase, "syntax")


    def test_environment_keywords_and_assignment_token_are_not_identifiers(self) -> None:
        r"""Verify environment keywords and assignment token are not identifiers."""

        invalid_sources = (
            _source_with(gamma="channel: Real"),
            _source_with(theta="ch: channel(where: Real)"),
            _source_with(process="{{process := 1}}"),
            "gamma(x := Real) theta() process {{skip}}",
            _source_with(
                theta="ch: channel(x: Real) where(x := 1)"
            ),
        )
        for source in invalid_sources:
            with self.subTest(source=source):
                with self.assertRaises(HCSPInputError) as context:
                    parse_hcsp_source(source)
                self.assertEqual(context.exception.phase, "syntax")


    def test_environment_syntax_error_preserves_global_source_location(self) -> None:
        r"""Verify environment syntax error preserves global source location."""

        source = """gamma(
    x: Real
)
theta(
    ch: channel(
        value Real
    )
)
process {{skip}}"""

        with self.assertRaises(HCSPInputError) as context:
            parse_hcsp_source(source, source_name="model.hcsp")

        error = context.exception
        self.assertEqual(error.phase, "syntax")
        self.assertEqual(error.source_name, "model.hcsp")
        self.assertEqual((error.line, error.column), (6, 15))
        self.assertEqual(error.found, "Real")
        self.assertEqual(error.expected, (":",))
        diagnostic = error.format_diagnostic()
        self.assertIn("model.hcsp:6:15", diagnostic)
        self.assertIn("        value Real", diagnostic)
        self.assertIn("              ^", diagnostic)


    def test_environment_validation_error_points_to_second_declaration(self) -> None:
        r"""Verify environment validation error points to second declaration."""

        source = """gamma(
    x: Real,
    /* duplicate follows */
    x: Int
)
theta()
process {{skip}}"""

        with self.assertRaises(HCSPInputError) as context:
            parse_hcsp_source(source, source_name="duplicate.hcsp")

        error = context.exception
        self.assertEqual(error.phase, "validation")
        self.assertEqual(error.source_name, "duplicate.hcsp")
        self.assertEqual(error.found, "x")
        self.assertEqual((error.line, error.column), (4, 5))


if __name__ == "__main__":
    unittest.main()
