r"""Regression tests for public API. Paper reference: Table 3, Table 2."""

from __future__ import annotations

from io import StringIO
import unittest
from unittest.mock import patch

import hcsp_typechecker
from hcsp_typechecker import (
    HCSPErrorDetail,
    HCSPInputError,
    HCSPTypeConstructionError,
    HCSPTypeCheckingError,
    HCSPTypeTransitionGraphError,
    HCSPTypeLockAnalysisError,
    HCSPUntrustedTypeConstructionError,
    OutputMode,
    TypeAST,
    TypeCheckingErrorKind,
    TypeConstructionErrorKind,
    TypeTransitionGraph,
    TypeTransitionGraphErrorKind,
    TypeLockAnalysisErrorKind,
    LockFreedomReport,
    analyze_type_lock_freedom,
    build_type_transition_graph,
    construct_hcsp_type,
    check_hcsp_type,
)
from hcsp_typechecker.frontend.type_syntax import (
    format_type_source,
    parse_type_source,
)


_SKIP_SOURCE = """gamma()
theta()
process {{skip}}"""

_COMMUNICATION_SOURCE = """gamma(x: Int)
parameters(limit: Int) where(limit >= 0)
theta(ch: channel(value: Int))
process {{ch?(x); ch!(x)}}"""

_PARALLEL_SOURCE = """gamma()
theta()
process {{skip}, {skip}}"""


class PublicFacadeTests(unittest.TestCase):
    r"""Tests for Public Facade."""


    def test_root_package_exports_only_supported_business_interfaces(self) -> None:
        r"""Verify root package exports only supported business interfaces."""

        expected = {
            "HCSPErrorDetail",
            "HCSPInputError",
            "HCSPTypeConstructionError",
            "HCSPTypeCheckingError",
            "HCSPTypeTransitionGraphError",
            "HCSPTypeLockAnalysisError",
            "HCSPUntrustedTypeConstructionError",
            "OutputMode",
            "TypeAST",
            "TypeCheckingErrorKind",
            "TypeConstructionErrorKind",
            "TypeTransitionGraph",
            "TypeTransitionGraphErrorKind",
            "TypeLockAnalysisErrorKind",
            "LockFreedomReport",
            "analyze_type_lock_freedom",
            "build_type_transition_graph",
            "construct_hcsp_type",
            "check_hcsp_type",
        }

        self.assertEqual(set(hcsp_typechecker.__all__), expected)
        self.assertEqual(len(hcsp_typechecker.__all__), len(expected))
        for name in expected:
            with self.subTest(public_name=name):
                self.assertTrue(hasattr(hcsp_typechecker, name))
        for hidden_name in (
            "HCSPProgram",
            "parse_hcsp_program",
            "infer_hcsp_type",
            "TypeConstructor",
            "BasicType",
            # Retired public/internal names must not survive as compatibility aliases.
            "typecheck_hcsp",
            "TypeChecker",
            "CheckReport",
            "TypingJudgment",
            "InferenceStep",
            "HCSPTypeError",
            "HCSPUntrustedTypeError",
            "format_normalized_type_ast",
            "format_type_transition_graph",
            "TypeTransitionGraphSizeError",
        ):
            with self.subTest(hidden_name=hidden_name):
                self.assertFalse(hasattr(hcsp_typechecker, hidden_name))


    def test_constructed_type_can_feed_the_public_graph_interface(self) -> None:
        r"""Verify constructed type can feed the public graph interface."""

        constructed = construct_hcsp_type(_SKIP_SOURCE)

        graph = build_type_transition_graph(constructed)

        self.assertIsInstance(graph, TypeTransitionGraph)
        self.assertEqual(len(graph.states), 1)
        self.assertEqual(graph.transitions, ())


    def test_graph_result_mode_prints_the_initial_normalized_type(self) -> None:
        r"""Verify graph result mode prints the initial normalized type."""

        output = StringIO()

        graph = build_type_transition_graph(
            construct_hcsp_type(_SKIP_SOURCE),
            output="result",
            stream=output,
        )

        self.assertEqual(len(graph.states), 1)
        rendered = output.getvalue()
        self.assertIn('Table 3 transition graph result', rendered)
        self.assertIn('State count : 1', rendered)
        self.assertIn('Transition count : 0', rendered)
        self.assertNotIn('complete closure', rendered)
        self.assertIn("normalized type empty", rendered)


    def test_graph_full_mode_prints_the_complete_graph(self) -> None:
        r"""Verify graph full mode prints the complete graph."""

        output = StringIO()

        graph = build_type_transition_graph(
            construct_hcsp_type(_SKIP_SOURCE),
            output="full",
            stream=output,
        )

        rendered = output.getvalue().rstrip("\n")

        self.assertEqual(
            rendered,
            "\n".join(
                (
                    "type transition graph {",
                    "    initial = S0",
                    "    states {",
                    "        S0 = normalized type empty",
                    "    }",
                    "    transitions {}",
                    "}",
                )
            ),
        )


    def test_graph_size_limit_raises_a_public_error(self) -> None:
        r"""Verify graph size limit raises a public error."""

        value = parse_type_source(
            "type internal {(delay(1) then empty), (delay(2) then empty)}"
        )

        output = StringIO()
        with self.assertRaises(HCSPTypeTransitionGraphError) as caught:
            build_type_transition_graph(
                value,
                max_states=1,
                output="result",
                stream=output,
            )

        self.assertIs(
            caught.exception.kind,
            TypeTransitionGraphErrorKind.SIZE_LIMIT,
        )
        self.assertEqual(caught.exception.phase, "graph-construction")
        self.assertEqual(caught.exception.limit_name, "max_states")
        self.assertEqual(caught.exception.limit, 1)
        self.assertEqual(caught.exception.verdict, "error")
        self.assertEqual(len(caught.exception.details), 1)
        self.assertIn('Return value : none (no partial transition graph is returned)', output.getvalue())
        self.assertNotIn("type transition graph {", output.getvalue())


    def test_graph_normalization_error_has_a_complete_failure_log(self) -> None:
        r"""Verify graph normalization error has a complete failure log."""

        output = StringIO()
        with self.assertRaises(HCSPTypeTransitionGraphError) as caught:
            build_type_transition_graph(
                parse_type_source("type X"),
                output="full",
                stream=output,
            )

        self.assertIs(
            caught.exception.kind,
            TypeTransitionGraphErrorKind.NORMALIZATION,
        )
        self.assertEqual(caught.exception.phase, "normalization")
        self.assertIsNotNone(caught.exception.__cause__)
        rendered = output.getvalue()
        self.assertIn('Type normalization : failed', rendered)
        self.assertIn('Graph traversal : not started', rendered)
        self.assertIn('--- Input Type ---\ntype X', rendered)
        self.assertEqual(rendered.count('Graph construction failure summary'), 1)


    def test_graph_call_contract_errors_are_structured(self) -> None:
        r"""Verify graph call contract errors are structured."""

        with self.assertRaises(HCSPTypeTransitionGraphError) as invalid_type:
            build_type_transition_graph(object())  # type: ignore[arg-type]
        self.assertIs(
            invalid_type.exception.kind,
            TypeTransitionGraphErrorKind.INVALID_TYPE,
        )
        self.assertEqual(invalid_type.exception.phase, "input-validation")

        with self.assertRaises(HCSPTypeTransitionGraphError) as invalid_limit:
            build_type_transition_graph(
                parse_type_source("type empty"),
                max_states=0,
            )
        self.assertIs(
            invalid_limit.exception.kind,
            TypeTransitionGraphErrorKind.INVALID_LIMIT,
        )
        self.assertEqual(invalid_limit.exception.phase, "option-validation")
        self.assertEqual(invalid_limit.exception.option_name, "max_states")
        self.assertEqual(invalid_limit.exception.option_value, 0)
        self.assertEqual(invalid_limit.exception.primary_detail.location, "max_states")

        with self.assertRaises(HCSPTypeTransitionGraphError) as wrong_kind:
            build_type_transition_graph(
                parse_type_source("type empty"),
                max_transitions=True,
            )
        self.assertEqual(wrong_kind.exception.option_name, "max_transitions")
        self.assertIs(wrong_kind.exception.option_value, True)
        self.assertIn(
            'Invalid option : max_transitions=True',
            wrong_kind.exception.format_result(),
        )


    def test_type_checker_accepts_matching_user_type(self) -> None:
        r"""Verify type checker accepts matching user type."""

        output = StringIO()
        checked = check_hcsp_type(
            _SKIP_SOURCE + "\ntype empty",
            output="result",
            stream=output,
        )
        self.assertEqual(str(checked), "0")
        self.assertIn('Type source : type empty', output.getvalue())
        self.assertNotIn("EmptyType()", output.getvalue())


    def test_type_checker_rejects_non_matching_user_type(self) -> None:
        r"""Verify type checker rejects non matching user type."""

        with self.assertRaises(HCSPTypeCheckingError) as caught:
            check_hcsp_type(_SKIP_SOURCE + "\ntype bottom")
        self.assertEqual(caught.exception.verdict, "false")
        self.assertIs(
            caught.exception.kind,
            TypeCheckingErrorKind.TYPE_MISMATCH,
        )
        self.assertEqual(caught.exception.phase, "type-matching")
        self.assertEqual(caught.exception.rule, "T-End")
        self.assertTrue(caught.exception.type_mismatch_detected)
        self.assertIs(caught.exception.type_structure_matched, False)
        self.assertTrue(caught.exception.details)
        self.assertIsInstance(caught.exception.details[0], HCSPErrorDetail)
        self.assertIn(
            'Supplied Type source : type bottom',
            caught.exception.format_result(),
        )
        self.assertIn(
            'Supplied Type source : type bottom',
            caught.exception.format_full(),
        )
        self.assertNotIn("BottomType()", caught.exception.format_full())


    def test_constructed_type_serialization_is_accepted_by_type_checker(self) -> None:
        r"""Verify constructed type serialization is accepted by type checker."""

        constructed = construct_hcsp_type(_COMMUNICATION_SOURCE)
        checked = check_hcsp_type(
            _COMMUNICATION_SOURCE + "\n" + format_type_source(constructed)
        )
        self.assertEqual(checked, constructed)


    def test_single_process_directly_returns_type_ast(self) -> None:
        r"""Verify single process directly returns type AST."""

        constructed = construct_hcsp_type(
            _COMMUNICATION_SOURCE,
            source_name="communication.hcsp",
        )

        self.assertIsInstance(constructed, TypeAST)
        self.assertEqual(
            str(constructed),
            r"delay(infinity) \unrhd (ch?.(delay(infinity) \unrhd (ch!.(0))))",
        )


    def test_parallel_process_directly_returns_type_ast(self) -> None:
        r"""Verify parallel process directly returns type AST."""

        constructed = construct_hcsp_type(
            _PARALLEL_SOURCE,
            initial_states=({}, {}),
        )

        self.assertIsInstance(constructed, TypeAST)
        self.assertEqual(str(constructed), "(0) | (0)")


    def test_output_modes_only_change_rendering_detail(self) -> None:
        r"""Verify output modes only change rendering detail."""

        silent = StringIO()
        result_stream = StringIO()
        full_stream = StringIO()

        silent_type = construct_hcsp_type(
            _SKIP_SOURCE,
            output=OutputMode.NONE,
            stream=silent,
        )
        result_type = construct_hcsp_type(
            _SKIP_SOURCE,
            output=" RESULT ",
            stream=result_stream,
        )
        full_type = construct_hcsp_type(
            _SKIP_SOURCE,
            source_name="skip.hcsp",
            output=OutputMode.FULL,
            stream=full_stream,
        )

        result_text = result_stream.getvalue()
        full_text = full_stream.getvalue()
        self.assertEqual(silent.getvalue(), "")
        self.assertIn('Type source : type empty', result_text)
        self.assertNotIn("EmptyType()", result_text)
        emitted_source = next(
            line.partition(":")[2].strip()
            for line in result_text.splitlines()
            if line.startswith('Type source :')
        )
        self.assertEqual(parse_type_source(emitted_source), result_type)
        self.assertIn("Verdict : true", result_text)
        self.assertNotIn('Rule execution trace', result_text)
        self.assertNotIn('Original user input', result_text)
        self.assertIn("skip.hcsp", full_text)
        self.assertIn(_SKIP_SOURCE, full_text)
        self.assertIn('Type construction and proof report', full_text)
        self.assertIn('Rule execution trace', full_text)
        self.assertIn(
            'Process AST : constructed internally; not exposed by the public API',
            full_text,
        )
        self.assertNotIn("Skip()", full_text)
        self.assertNotIn("Parallel(", full_text)
        self.assertNotIn("HCSPProgram", full_text)
        self.assertEqual(silent_type, result_type)
        self.assertEqual(result_type, full_type)


    def test_parse_failure_stops_before_type_construction(self) -> None:
        r"""Verify parse failure stops before type construction."""

        broken = "gamma()\ntheta()\nprocess {{skip"
        result_stream = StringIO()
        full_stream = StringIO()

        with patch("hcsp_typechecker.api.construct_type") as constructor:
            with self.assertRaises(HCSPInputError):
                construct_hcsp_type(
                    broken,
                    source_name="broken.hcsp",
                    output="result",
                    stream=result_stream,
                )
            with self.assertRaises(HCSPInputError):
                construct_hcsp_type(
                    broken,
                    source_name="broken.hcsp",
                    output="full",
                    stream=full_stream,
                )
            constructor.assert_not_called()

        self.assertIn('failed', result_stream.getvalue())
        self.assertIn("broken.hcsp:3:15", result_stream.getvalue())
        self.assertNotIn("process {{skip", result_stream.getvalue())
        self.assertIn("process {{skip", full_stream.getvalue())
        self.assertIn("syntax error", full_stream.getvalue())
        self.assertIn("^", full_stream.getvalue())
        self.assertNotIn('Rule execution trace', full_stream.getvalue())


    def test_false_construction_raises_error_with_partial_derivation(self) -> None:
        r"""Verify false construction raises error with partial derivation."""

        output = StringIO()
        with self.assertRaises(HCSPTypeConstructionError) as captured:
            construct_hcsp_type(
                "gamma()\ntheta()\nprocess {{assert(false)}}",
                source_name="false-assert.hcsp",
                output="result",
                stream=output,
            )

        error = captured.exception
        self.assertEqual(error.verdict, "false")
        self.assertIs(error.kind, TypeConstructionErrorKind.PROOF_FAILED)
        self.assertEqual(error.phase, "proof")
        self.assertEqual(error.rule, "T-Assert")
        self.assertEqual(error.location, "K1")
        self.assertTrue(error.details)
        self.assertEqual(error.details[0].proof_kind, "fol")
        self.assertTrue(error.details[0].formula)
        self.assertIn("counterexample", error.details[0].backend_detail)
        self.assertEqual(error.partial_types, (None,))
        self.assertTrue(error.reason)
        self.assertFalse(hasattr(error, "program"))
        self.assertFalse(hasattr(error, "process_ast"))
        self.assertIn("Verdict : false", error.format_result())
        self.assertIn('Type source : (none)', error.format_result())
        self.assertIn('Partial types : K1=(none)', error.format_result())
        self.assertIn('Derivation steps :', error.format_result())
        self.assertIn('Stop location :', error.format_result())
        self.assertIn("T-Assert", error.format_result())
        self.assertEqual(output.getvalue().strip(), error.format_result())


    def test_unknown_construction_exposes_only_an_explicit_untrusted_type(self) -> None:
        r"""Verify unknown construction exposes only an explicit untrusted type."""

        output = StringIO()
        with patch(
            "hcsp_typechecker.backend.common.keymaerax."
            "KeYmaeraXBackend.__call__",
            return_value=None,
        ):
            with self.assertRaises(HCSPUntrustedTypeConstructionError) as captured:
                construct_hcsp_type(
                "gamma()\ntheta()\nprocess {{ode(flow(), domain(t < 1), "
                "delay(1)); skip}}",
                    source_name="unknown-ode.hcsp",
                    output="full",
                    stream=output,
                )

        error = captured.exception
        self.assertIsInstance(error, HCSPTypeConstructionError)
        self.assertEqual(error.verdict, "unknown")
        self.assertIs(error.kind, TypeConstructionErrorKind.PROOF_UNKNOWN)
        self.assertEqual(error.phase, "proof")
        self.assertIsInstance(error.untrusted_type, TypeAST)
        self.assertEqual(str(error.untrusted_type), "delay(1).(0)")
        self.assertEqual(error.partial_types, (error.untrusted_type,))
        self.assertFalse(hasattr(error, "program"))
        self.assertIn("Verdict : unknown", str(error))
        self.assertIn('Complete candidate Type', error.format_result())
        self.assertIn(
            'Complete candidate Type source : type delay(1) then empty',
            error.format_result(),
        )
        self.assertIn('untrusted (unverified)', error.format_result())
        self.assertIn('Type construction and proof report', error.format_full())
        self.assertIn("dL", error.format_full())
        self.assertIn('Rule derivation : complete', error.format_full())
        self.assertIn(
            'Constructed Type source : type delay(1) then empty',
            error.format_full(),
        )
        self.assertIn(
            'Process AST : constructed internally; not exposed by the public API',
            error.format_full(),
        )
        self.assertNotIn("ODE(", error.format_full())
        self.assertEqual(output.getvalue().rstrip("\n"), error.format_full())
        self.assertEqual(output.getvalue().count('Type construction and proof report'), 1)


    def test_parallel_initial_state_shape_is_validated_by_single_entrypoint(self) -> None:
        r"""Verify parallel initial state shape is validated by single entrypoint."""

        with self.assertRaisesRegex(ValueError, "one initial-state mapping"):
            construct_hcsp_type(_PARALLEL_SOURCE, initial_states={})
        with self.assertRaisesRegex(ValueError, r"components \(2\)"):
            construct_hcsp_type(_PARALLEL_SOURCE, initial_states=({},))
        with self.assertRaisesRegex(TypeError, "every initial state"):
            construct_hcsp_type(
                _PARALLEL_SOURCE,
                initial_states=({}, 0),  # type: ignore[arg-type]
            )


    def test_path_condition_uses_strict_expression_frontend(self) -> None:
        r"""Verify path condition uses strict expression frontend."""

        source = "gamma(x: Int)\ntheta()\nprocess {{skip}}"
        constructed = construct_hcsp_type(
            source,
            source_name="path-demo.hcsp",
            initial_states={"x": 1},
            path_condition="x >= 0",
        )

        self.assertIsInstance(constructed, TypeAST)
        self.assertEqual(str(constructed), "0")
        error_output = StringIO()
        with self.assertRaises(HCSPInputError) as captured:
            construct_hcsp_type(
                source,
                source_name="path-demo.hcsp",
                path_condition="x >=",
                output="full",
                stream=error_output,
            )
        self.assertEqual(
            captured.exception.source_name,
            "path-demo.hcsp:path_condition",
        )
        self.assertEqual(captured.exception.kind, "input-syntax")
        self.assertIn('Path condition parsing failed', error_output.getvalue())
        self.assertIn("path-demo.hcsp:path_condition", error_output.getvalue())


    def test_type_checker_input_error_uses_checker_specific_output(self) -> None:
        r"""Verify type checker input error uses checker specific output."""

        source = _SKIP_SOURCE + "\ntype"
        result_output = StringIO()
        full_output = StringIO()
        with self.assertRaises(HCSPInputError):
            check_hcsp_type(
                source,
                source_name="bad-type.hcsp",
                output="result",
                stream=result_output,
            )
        with self.assertRaises(HCSPInputError):
            check_hcsp_type(
                source,
                source_name="bad-type.hcsp",
                output="full",
                stream=full_output,
            )

        self.assertIn('HCSP type checking input error', result_output.getvalue())
        self.assertIn('Error kind : input-syntax', result_output.getvalue())
        self.assertNotIn('type construction', result_output.getvalue())
        self.assertIn('HCSP type checking full error log', full_output.getvalue())
        self.assertIn(source, full_output.getvalue())
        self.assertIn("syntax error", full_output.getvalue())
        self.assertIn("^", full_output.getvalue())
        self.assertNotIn('type construction', full_output.getvalue())


    def test_type_checker_errors_have_machine_readable_categories(self) -> None:
        r"""Verify type checker errors have machine readable categories."""

        invalid_environment = (
            "gamma() theta(bad: channel(v: Real) where(v + 1)) "
            "process {{skip}} type empty"
        )
        with self.assertRaises(HCSPTypeCheckingError) as environment_error:
            check_hcsp_type(invalid_environment)
        self.assertIs(
            environment_error.exception.kind,
            TypeCheckingErrorKind.ENVIRONMENT,
        )
        self.assertEqual(environment_error.exception.phase, "environment")
        self.assertEqual(environment_error.exception.rule, "environment")
        self.assertFalse(environment_error.exception.type_mismatch_detected)

        with self.assertRaises(HCSPTypeCheckingError) as proof_error:
            check_hcsp_type(
                "gamma() theta() process {{assert(false)}} type empty"
            )
        self.assertIs(
            proof_error.exception.kind,
            TypeCheckingErrorKind.PROOF_FAILED,
        )
        self.assertEqual(proof_error.exception.rule, "T-Assert")
        self.assertIn("counterexample", proof_error.exception.reason)
        self.assertTrue(proof_error.exception.details[0].formula)

        unknown_source = (
            "gamma() theta() process {{ode(flow(), domain(t < 1), "
            "delay(1)); skip}} type delay(1) then empty"
        )
        with patch(
            "hcsp_typechecker.backend.common.keymaerax."
            "KeYmaeraXBackend.__call__",
            return_value=None,
        ):
            with self.assertRaises(HCSPTypeCheckingError) as unknown_error:
                check_hcsp_type(unknown_source)
        self.assertIs(
            unknown_error.exception.kind,
            TypeCheckingErrorKind.PROOF_UNKNOWN,
        )
        self.assertEqual(unknown_error.exception.verdict, "unknown")
        self.assertEqual(unknown_error.exception.phase, "proof")
        self.assertIs(unknown_error.exception.type_structure_matched, True)
        self.assertIn("no decision", unknown_error.exception.reason)


    def test_constructor_separates_environment_and_derivation_errors(self) -> None:
        r"""Verify constructor separates environment and derivation errors."""

        invalid_environment = (
            "gamma() theta(bad: channel(v: Real) where(v + 1)) "
            "process {{skip}}"
        )
        with self.assertRaises(HCSPTypeConstructionError) as environment_error:
            construct_hcsp_type(invalid_environment)
        self.assertIs(
            environment_error.exception.kind,
            TypeConstructionErrorKind.ENVIRONMENT,
        )
        self.assertEqual(environment_error.exception.phase, "environment")
        self.assertEqual(environment_error.exception.rule, "environment")

        invalid_assignment = "gamma(x: Bool) theta() process {{x := 1}}"
        with self.assertRaises(HCSPTypeConstructionError) as derivation_error:
            construct_hcsp_type(invalid_assignment)
        self.assertIs(
            derivation_error.exception.kind,
            TypeConstructionErrorKind.DERIVATION,
        )
        self.assertEqual(derivation_error.exception.phase, "rule-derivation")
        self.assertEqual(derivation_error.exception.rule, "T-Assign")
        self.assertTrue(derivation_error.exception.details)


    def test_invalid_output_mode_is_rejected(self) -> None:
        r"""Verify invalid output mode is rejected."""

        with self.assertRaisesRegex(ValueError, "none.*result.*full"):
            construct_hcsp_type(_SKIP_SOURCE, output="verbose")


if __name__ == "__main__":
    unittest.main()
