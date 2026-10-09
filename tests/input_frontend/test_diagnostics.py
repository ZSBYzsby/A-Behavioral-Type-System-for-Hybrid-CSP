r"""Regression tests for diagnostics. Paper reference: Section 2.1/4.3, Table 2."""

from __future__ import annotations

import unittest

from hcsp_typechecker._internal import HCSPInputError, parse_expression, parse_hcsp


class LexicalDiagnosticTests(unittest.TestCase):
    r"""Tests for Lexical Diagnostic."""


    def test_illegal_character_reports_exact_location(self) -> None:
        r"""Verify illegal character reports exact location."""

        source = "{{skip;\n    @}}"
        with self.assertRaises(HCSPInputError) as context:
            parse_hcsp(source, source_name="example.hcsp")
        error = context.exception
        self.assertEqual(error.phase, "lexical")
        self.assertEqual(error.source_name, "example.hcsp")
        self.assertEqual((error.line, error.column), (2, 5))
        self.assertEqual(error.found, "@")
        diagnostic = error.format_diagnostic()
        self.assertIn("example.hcsp:2:5", diagnostic)
        self.assertIn("    @}}", diagnostic)
        self.assertIn("    ^", diagnostic)


    def test_unterminated_comment_points_to_comment_start(self) -> None:
        r"""Verify unterminated comment points to comment start."""

        with self.assertRaises(HCSPInputError) as context:
            parse_hcsp("{{/* never closed")
        error = context.exception
        self.assertEqual(error.phase, "lexical")
        self.assertEqual((error.line, error.column), (1, 3))
        self.assertIn("unterminated block comment", error.message)


    def test_noncanonical_lexemes_and_non_string_input_are_lexical_errors(self) -> None:
        r"""Verify noncanonical lexemes and non string input are lexical errors."""

        for source in ("\u03b1\u03b2", "0x10", "1_000"):
            with self.subTest(source=source):
                with self.assertRaises(HCSPInputError) as context:
                    parse_expression(source)
                self.assertEqual(context.exception.phase, "lexical")
        with self.assertRaises(HCSPInputError) as context:
            parse_hcsp(1)  # type: ignore[arg-type]
        self.assertEqual(context.exception.phase, "lexical")


    def test_extreme_numeric_literals_have_bounded_diagnostics(self) -> None:
        r"""Verify extreme numeric literals have bounded diagnostics."""

        for source in ("9" * 4097, "1e10001"):
            with self.subTest(length=len(source)):
                with self.assertRaises(HCSPInputError) as context:
                    parse_expression(source)
                self.assertEqual(context.exception.phase, "lexical")


class SyntaxDiagnosticTests(unittest.TestCase):
    r"""Tests for Syntax Diagnostic."""


    def test_missing_semicolon_reports_second_statement(self) -> None:
        r"""Verify missing semicolon reports second statement."""

        source = "{{x := 0\n  y := 1}}"
        with self.assertRaises(HCSPInputError) as context:
            parse_hcsp(source)
        error = context.exception
        self.assertEqual(error.phase, "syntax")
        self.assertEqual((error.line, error.column), (2, 3))
        self.assertEqual(error.found, "y")
        self.assertEqual(error.expected, ("}",))


    def test_malformed_source_and_block_boundaries_are_syntax_errors(self) -> None:
        r"""Verify malformed source and block boundaries are syntax errors."""

        malformed = (
            "{}",
            "{{skip},}",
            "{{skip} {skip}}",
            "{{skip;}}",
            "skip",
        )
        for source in malformed:
            with self.subTest(source=source):
                with self.assertRaises(HCSPInputError) as context:
                    parse_hcsp(source)
                self.assertEqual(context.exception.phase, "syntax")


    def test_unclosed_parenthesis_exposes_expected_token(self) -> None:
        r"""Verify unclosed parenthesis exposes expected token."""

        with self.assertRaises(HCSPInputError) as context:
            parse_hcsp("{{assert(x > 0}}")
        error = context.exception
        self.assertEqual(error.phase, "syntax")
        self.assertEqual(error.expected, (")",))


    def test_eof_after_newline_displays_the_actual_empty_line(self) -> None:
        r"""Verify EOF after newline displays the actual empty line."""

        with self.assertRaises(HCSPInputError) as context:
            parse_hcsp("{\n")
        error = context.exception
        self.assertEqual((error.line, error.column), (2, 1))
        self.assertEqual(error.format_diagnostic().splitlines()[-2:], ["", "^"])


class ValidationDiagnosticTests(unittest.TestCase):
    r"""Tests for Validation Diagnostic."""


    def test_duplicate_input_target_is_located_at_second_occurrence(self) -> None:
        r"""Verify duplicate input target is located at second occurrence."""

        with self.assertRaises(HCSPInputError) as context:
            parse_hcsp("{{ch?(x, x)}}")
        error = context.exception
        self.assertEqual(error.phase, "validation")
        self.assertEqual((error.line, error.column), (1, 10))
        self.assertEqual(error.found, "x")
        self.assertIn("duplicate input target", error.message)


    def test_reserved_ode_clock_reports_equation_position(self) -> None:
        r"""Verify reserved ODE clock reports equation position."""

        source = "{{ode(flow(dot t = 1), domain(true), delay(1))}}"
        with self.assertRaises(HCSPInputError) as context:
            parse_hcsp(source)
        error = context.exception
        self.assertEqual(error.phase, "validation")
        self.assertEqual(error.found, "t")
        self.assertIn("implicit local clock", error.message)


    def test_parallel_validation_preserves_assumption_message(self) -> None:
        r"""Verify parallel validation preserves assumption message."""

        with self.assertRaises(HCSPInputError) as context:
            parse_hcsp("{{ch!(0)}, {ch!(1)}}")
        error = context.exception
        self.assertEqual(error.phase, "validation")
        self.assertIn("Assumption 2.1", error.message)
        self.assertIn("output channels", error.message)


if __name__ == "__main__":
    unittest.main()
