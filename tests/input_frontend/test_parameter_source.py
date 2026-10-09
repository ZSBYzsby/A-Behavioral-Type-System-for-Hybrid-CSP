r"""Regression tests for parameter source. Paper reference: Assumption 2.1, Section 2.1."""

from __future__ import annotations

import unittest

from hcsp_typechecker._internal import (
    BasicType,
    HCSPInputError,
    Parallel,
    ParsedHCSPSource,
    Skip,
    parse_expression,
    parse_hcsp_source,
)


class ParameterSourceConversionTests(unittest.TestCase):
    r"""Tests for Parameter Source Conversion."""


    def test_parameter_section_is_optional_and_empty_form_is_equivalent(self) -> None:
        r"""Verify parameter section is optional and empty form is equivalent."""

        legacy = parse_hcsp_source(
            "gamma() theta() process {{skip}}"
        )
        explicit = parse_hcsp_source(
            "gamma() parameters() theta() process {{skip}}"
        )

        for parsed in (legacy, explicit):
            with self.subTest(source_form=parsed):
                self.assertEqual(parsed.parameters.declarations, {})
                self.assertIs(parsed.parameters.constraint, True)
                self.assertEqual(parsed.process, Skip())


    def test_all_parameter_basic_types_and_constraint_are_lowered_exactly(self) -> None:
        r"""Verify all parameter basic types and constraint are lowered exactly."""

        parsed = parse_hcsp_source(
            """gamma(state: Real)
parameters(
    enabled: Bool,
    count: Nat,
    offset: Int,
    ratio: Rational,
    limit: Real
) where(enabled and count <= offset and ratio <= limit)
theta()
process {{skip}}"""
        )

        self.assertEqual(
            parsed.parameters.declarations,
            {
                "enabled": BasicType.BOOL,
                "count": BasicType.NAT,
                "offset": BasicType.INT,
                "ratio": BasicType.RATIONAL,
                "limit": BasicType.REAL,
            },
        )
        self.assertEqual(
            parsed.parameters.constraint,
            parse_expression(
                "enabled and count <= offset and ratio <= limit"
            ),
        )
        self.assertEqual(parsed.gamma, {"state": BasicType.REAL})
        self.assertNotIn("limit", parsed.gamma)


    def test_true_constraint_and_declarations_use_read_only_normal_form(self) -> None:
        r"""Verify true constraint and declarations use read only normal form."""

        parsed = parse_hcsp_source(
            """gamma()
parameters(limit: Real) where(true)
theta()
process {{skip}}"""
        )

        self.assertIs(parsed.parameters.constraint, True)
        with self.assertRaises(TypeError):
            parsed.parameters.declarations["limit"] = BasicType.INT  # type: ignore[index]
        with self.assertRaises(AttributeError):
            parsed.parameters.declarations.clear()  # type: ignore[attr-defined]


    def test_constraint_semantics_are_preserved_for_the_type_constructor(self) -> None:
        r"""Verify constraint semantics are preserved for the type constructor."""

        parsed = parse_hcsp_source(
            """gamma()
parameters(limit: Real) where(limit + 1)
theta()
process {{skip}}"""
        )

        self.assertEqual(
            parsed.parameters.constraint,
            parse_expression("limit + 1"),
        )


    def test_declared_parameter_can_be_read_by_parallel_components(self) -> None:
        r"""Verify declared parameter can be read by parallel components."""

        parsed = parse_hcsp_source(
            """gamma()
parameters(limit: Real) where(limit >= 0)
theta(
    left: channel(value: Real),
    right: channel(value: Real)
)
process {
    {assert(limit >= 0); left!(limit)},
    {assert(limit >= 0); right!(limit)}
}"""
        )

        self.assertIsInstance(parsed.process, Parallel)
        self.assertEqual(len(parsed.process_components), 2)
        self.assertEqual(
            parsed.parameters.declarations,
            {"limit": BasicType.REAL},
        )
        self.assertTrue(
            all("limit" in component.get_vars()
                for component in parsed.process_components)
        )


    def test_parameter_exemption_does_not_hide_shared_state_variables(self) -> None:
        r"""Verify parameter exemption does not hide shared state variables."""

        source = """gamma(shared: Real)
parameters(limit: Real)
theta(
    left: channel(value: Real),
    right: channel(value: Real)
)
process {
    {left!(shared + limit)},
    {right!(shared + limit)}
}"""

        with self.assertRaises(HCSPInputError) as context:
            parse_hcsp_source(source)

        self.assertEqual(context.exception.phase, "validation")
        self.assertIn("share variables: shared", str(context.exception))


class ParameterSourceValidationTests(unittest.TestCase):
    r"""Tests for Parameter Source Validation."""


    def test_duplicate_and_gamma_overlapping_parameters_are_rejected(self) -> None:
        r"""Verify duplicate and Gamma overlapping parameters are rejected."""

        cases = (
            (
                "gamma() parameters(x: Real, x: Int) "
                "theta() process {{skip}}",
                "duplicate parameter declaration",
            ),
            (
                "gamma(x: Real) parameters(x: Real) "
                "theta() process {{skip}}",
                "overlap",
            ),
        )
        for source, expected_message in cases:
            with self.subTest(expected_message=expected_message):
                with self.assertRaises(HCSPInputError) as context:
                    parse_hcsp_source(source)
                self.assertEqual(context.exception.phase, "validation")
                self.assertEqual(context.exception.found, "x")
                self.assertIn(expected_message, str(context.exception))


    def test_parameter_constraint_may_only_reference_declared_parameters(self) -> None:
        r"""Verify parameter constraint may only reference declared parameters."""

        source = """gamma(state: Real)
parameters(limit: Real) where(limit >= state and missing >= 0)
theta()
process {{skip}}"""

        with self.assertRaises(HCSPInputError) as context:
            parse_hcsp_source(source, source_name="parameters.hcsp")

        error = context.exception
        self.assertEqual(error.phase, "validation")
        self.assertEqual(error.source_name, "parameters.hcsp")
        self.assertEqual(error.found, "where")
        self.assertEqual((error.line, error.column), (2, 25))
        self.assertIn("missing, state", str(error))


    def test_parameter_types_identifiers_and_commas_are_strict(self) -> None:
        r"""Verify parameter types identifiers and commas are strict."""

        cases = (
            (
                "gamma() parameters(x: real) theta() process {{skip}}",
                "syntax",
            ),
            (
                "gamma() parameters(x: continuous(y)) "
                "theta() process {{skip}}",
                "syntax",
            ),
            (
                "gamma() parameters(x: Real,) theta() process {{skip}}",
                "syntax",
            ),
            (
                "gamma() parameters(\u03b1\u03b2: Real) theta() process {{skip}}",
                "lexical",
            ),
        )
        for source, expected_phase in cases:
            with self.subTest(expected_phase=expected_phase):
                with self.assertRaises(HCSPInputError) as context:
                    parse_hcsp_source(source)
                self.assertEqual(context.exception.phase, expected_phase)


    def test_parameter_section_has_one_fixed_optional_position(self) -> None:
        r"""Verify parameter section has one fixed optional position."""

        invalid_sources = (
            "parameters() gamma() theta() process {{skip}}",
            "gamma() theta() parameters() process {{skip}}",
            "gamma(); parameters() theta() process {{skip}}",
            "gamma() parameters() parameters() theta() process {{skip}}",
        )
        for source in invalid_sources:
            with self.subTest(source=source):
                with self.assertRaises(HCSPInputError) as context:
                    parse_hcsp_source(source)
                self.assertEqual(context.exception.phase, "syntax")


    def test_parameters_keyword_is_reserved_everywhere(self) -> None:
        r"""Verify parameters keyword is reserved everywhere."""

        invalid_sources = (
            "gamma() parameters(parameters: Real) "
            "theta() process {{skip}}",
            "gamma() theta() process {{parameters := 1}}",
        )
        for source in invalid_sources:
            with self.subTest(source=source):
                with self.assertRaises(HCSPInputError) as context:
                    parse_hcsp_source(source)
                self.assertEqual(context.exception.phase, "syntax")


if __name__ == "__main__":
    unittest.main()
