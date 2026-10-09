"""Regression tests for unresolved proofs, backend failures, and trust boundaries."""

from contextlib import redirect_stdout
from io import StringIO
import unittest
from unittest.mock import Mock, patch

import z3

from hcsp_typechecker import (
    HCSPTypeCheckingError,
    HCSPTypeConstructionError,
    HCSPUntrustedTypeConstructionError,
    check_hcsp_type,
    construct_hcsp_type,
)
from hcsp_typechecker.backend.common.logic import Z3ProofEngine
from hcsp_typechecker.backend.common.model import Verdict


SKIP_SOURCE = "gamma() theta() process {{skip}}"
ODE_SOURCE = (
    "gamma() theta() process {{"
    "ode(flow(), domain(t < 1), delay(1)); skip}}"
)


class ProofFailureHandlingTests(unittest.TestCase):
    """Keep unresolved verification distinct from refutation and trusted results."""

    def test_missing_z3_is_unknown_without_a_candidate(self) -> None:
        """Dependency failure stops translation without blaming the user's environment."""

        for function, source, error_type in (
            (construct_hcsp_type, SKIP_SOURCE, HCSPTypeConstructionError),
            (check_hcsp_type, SKIP_SOURCE + " type empty", HCSPTypeCheckingError),
        ):
            with self.subTest(function=function.__name__):
                output = StringIO()
                with patch("hcsp_typechecker.backend.common.logic.z3", None):
                    with redirect_stdout(output), self.assertRaises(error_type) as captured:
                        function(source)
                error = captured.exception
                self.assertEqual(output.getvalue(), "")
                self.assertEqual(error.verdict, "unknown")
                self.assertEqual(error.kind.value, "proof-unknown")
                self.assertEqual(error.primary_detail.category, "proof-unknown")
                self.assertIn("z3-solver is not installed", error.reason)
                self.assertFalse(hasattr(error, "untrusted_type"))

    def test_z3_query_exceptions_remain_unknown(self) -> None:
        """Solver failures provide evidence without claiming a counterexample."""

        engine = Z3ProofEngine()
        formula = z3.BoolVal(True)
        for method in (engine.valid, engine.satisfiable):
            with self.subTest(query=method.__name__), patch(
                "hcsp_typechecker.backend.common.logic.z3.Solver",
                side_effect=z3.Z3Exception("solver unavailable"),
            ):
                verdict, detail = method(formula)
                self.assertIs(verdict, Verdict.UNKNOWN)
                self.assertIn("solver unavailable", detail)
            solver = Mock()
            solver.check.side_effect = z3.Z3Exception("query interrupted")
            with self.subTest(query=method.__name__, phase="check"), patch(
                "hcsp_typechecker.backend.common.logic.z3.Solver", return_value=solver
            ):
                verdict, detail = method(formula)
                self.assertIs(verdict, Verdict.UNKNOWN)
                self.assertIn("query interrupted", detail)

    def test_parameter_query_failure_has_structured_public_diagnostics(self) -> None:
        """An unresolved environment query makes otherwise complete Types untrusted."""

        for function, source, error_type in (
            (construct_hcsp_type, SKIP_SOURCE, HCSPUntrustedTypeConstructionError),
            (check_hcsp_type, SKIP_SOURCE + " type empty", HCSPTypeCheckingError),
        ):
            with self.subTest(function=function.__name__), patch(
                "hcsp_typechecker.backend.common.logic.z3.Solver",
                side_effect=z3.Z3Exception("solver unavailable"),
            ):
                with self.assertRaises(error_type) as captured:
                    function(source)
                error = captured.exception
                self.assertEqual(error.verdict, "unknown")
                self.assertEqual(error.kind.value, "proof-unknown")
                self.assertEqual(error.primary_detail.category, "proof-unknown")
                self.assertIn("Z3 satisfiability query failed", error.reason)

    def test_invalid_z3_timeouts_are_argument_errors(self) -> None:
        """Reject coercions and unsigned overflow while allowing an explicit unlimited query."""

        for function, source in (
            (construct_hcsp_type, SKIP_SOURCE),
            (check_hcsp_type, SKIP_SOURCE + " type empty"),
        ):
            for timeout in (True, False, 0.5, "5000", None):
                with self.subTest(function=function.__name__, timeout=timeout):
                    with self.assertRaisesRegex(TypeError, "z3_timeout_ms"):
                        function(source, z3_timeout_ms=timeout)
            for timeout in (-1, 4_294_967_296):
                with self.subTest(function=function.__name__, timeout=timeout):
                    with self.assertRaisesRegex(ValueError, "z3_timeout_ms"):
                        function(source, z3_timeout_ms=timeout)
            self.assertIsNotNone(function(source, z3_timeout_ms=0))

    def test_later_refutation_overrides_an_unknown_proof(self) -> None:
        """A disproved assertion remains the primary error after an unresolved ODE premise."""

        source = ODE_SOURCE.replace("; skip", "; assert(false)")
        with patch(
            "hcsp_typechecker.backend.common.keymaerax.KeYmaeraXBackend.__call__",
            return_value=Verdict.UNKNOWN,
        ):
            with self.assertRaises(HCSPTypeConstructionError) as captured:
                construct_hcsp_type(source)
        error = captured.exception
        self.assertNotIsInstance(error, HCSPUntrustedTypeConstructionError)
        self.assertEqual(error.verdict, "false")
        self.assertEqual(error.kind.value, "proof-failed")
        self.assertEqual(error.rule, "T-Assert")
        self.assertEqual(error.partial_types, (None,))

    def test_unselected_false_obligation_is_excluded_from_error_summary(self) -> None:
        """Alternative rule failures do not contaminate the selected candidate's summary."""

        def decide(obligation):
            """Refute the communication rule and leave the timeout rule unresolved."""

            return Verdict.FALSE if obligation.formula.role == "domain" else Verdict.UNKNOWN

        with patch(
            "hcsp_typechecker.backend.common.keymaerax.KeYmaeraXBackend.__call__",
            side_effect=decide,
        ):
            with self.assertRaises(HCSPUntrustedTypeConstructionError) as captured:
                construct_hcsp_type(ODE_SOURCE)
        error = captured.exception
        self.assertEqual(error.verdict, "unknown")
        self.assertIn("false=0", error.format_result())
        self.assertNotIn("false=1", error.format_result())
        self.assertIn("Inactive candidate obligations", error.format_result())
        self.assertTrue(all(detail.verdict != "false" for detail in error.details))

    def test_unknown_checking_output_is_unverified_with_matched_structure(self) -> None:
        """Matching Type structure does not turn an unknown proof into a successful check."""

        source = ODE_SOURCE + " type delay(1) then empty"
        with patch(
            "hcsp_typechecker.backend.common.keymaerax.KeYmaeraXBackend.__call__",
            return_value=Verdict.UNKNOWN,
        ):
            with self.assertRaises(HCSPTypeCheckingError) as captured:
                check_hcsp_type(source)
        error = captured.exception
        self.assertTrue(error.type_structure_matched)
        self.assertIn("Check result : unverified", error.format_result())
        self.assertIn("Type structure : matches all rule conclusions", error.format_result())
        self.assertFalse(hasattr(error, "untrusted_type"))


if __name__ == "__main__":
    unittest.main()
