r"""Regression tests for type checker rules. Paper reference: Table 2."""

from __future__ import annotations

import unittest
from unittest.mock import patch
from io import StringIO

from hcsp_typechecker import (
    HCSPTypeCheckingError,
    check_hcsp_type,
    construct_hcsp_type,
)
from hcsp_typechecker.backend.common import Verdict
from hcsp_typechecker.backend.type_checker import TypeCheckingRequest
from hcsp_typechecker.data_structures.runtime_context import Configuration
from hcsp_typechecker.data_structures.type_ast import InternalChoiceType
from hcsp_typechecker.frontend.type_checker_frontend import (
    parse_typechecking_source,
)
from hcsp_typechecker.frontend.type_syntax import format_type_source
from hcsp_typechecker.backend.type_checker import TypeChecker


_DISCRETE_SOURCE = """gamma(x: Int)
theta()
process {{x := 1; assert(x == 1)}}"""

_IF_SOURCE = """gamma(x: Int)
theta(a: channel(v: Int), b: channel(v: Int))
process {{if (x >= 0) {a!(x)} else {b!(x)}}}"""

_CHOICE_SOURCE = """gamma()
theta(a: channel(v: Int), b: channel(v: Int), c: channel(v: Int))
process {{choose {a!(0)} or {b!(0)} or {c!(0)}}}"""

_RECURSION_SOURCE = """gamma(x: Int)
theta(tick: channel(v: Int))
process {{x := 0; mu Loop invariant(x >= 0) {tick!(x); call Loop}}}"""

_PARALLEL_SOURCE = """gamma(x: Int)
theta(ch: channel(v: Int))
process {{ch!(1)}, {ch?(x)}}"""

_PARALLEL_UNUSED_GAMMA_SOURCE = """gamma(unused: Int)
theta()
process {{skip}, {skip}}"""

_NESTED_IF_SOURCE = """gamma(x: Int)
theta(a: channel(v: Int), b: channel(v: Int), c: channel(v: Int))
process {{if (x >= 0) {choose {a!(0)} or {b!(0)}} else {c!(0)}}}"""

_NESTED_CHOICE_SOURCE = """gamma(x: Int)
theta(a: channel(v: Int), b: channel(v: Int), c: channel(v: Int))
process {{choose {if (x >= 0) {a!(0)} else {b!(0)}} or {c!(0)}}}"""

_INFINITE_ODE_SOURCE = """gamma()
theta(ch: channel(v: Int), reset: channel(v: Int))
process {{ode(
    flow(),
    domain(true),
    delay(inf),
    interrupt(on ch!(0) {skip}, on reset?(value) {skip})
); skip}}"""

_NESTED_CROSS_SCOPE_RECURSION_SOURCE = """gamma(flag: Bool)
theta(a: channel(v: Int), b: channel(v: Int), c: channel(v: Int), d: channel(v: Int))
process {{mu X invariant(true) {
    a!(0);
    if (flag) {call X} else {
        d!(0);
        mu Y invariant(true) {
            if (flag) {b!(0); call X} else {c!(0); call Y}
        }
    }
}}}"""

_NESTED_SHADOW_ONLY_RECURSION_SOURCE = """gamma(flag: Bool)
theta(a: channel(v: Int), c: channel(v: Int), d: channel(v: Int))
process {{mu X invariant(true) {
    a!(0);
    if (flag) {call X} else {
        d!(0);
        mu Y invariant(true) {c!(0); call Y}
    }
}}}"""


class TypeDirectedRuleTests(unittest.TestCase):
    r"""Tests for Type Directed Rule."""


    def test_constructor_roundtrip_covers_discrete_and_multiway_rules(self) -> None:
        r"""Verify constructor roundtrip covers discrete and multiway rules."""

        for source in (_DISCRETE_SOURCE, _IF_SOURCE, _CHOICE_SOURCE):
            with self.subTest(source=source):
                constructed = construct_hcsp_type(source)
                checked = check_hcsp_type(
                    source + "\n" + format_type_source(constructed)
                )
                self.assertEqual(checked, constructed)


    def test_constructor_roundtrip_covers_recursion_and_parallel(self) -> None:
        r"""Verify constructor roundtrip covers recursion and parallel."""

        for source in (
            _RECURSION_SOURCE,
            _PARALLEL_SOURCE,
            _PARALLEL_UNUSED_GAMMA_SOURCE,
        ):
            with self.subTest(source=source):
                constructed = construct_hcsp_type(source)
                checked = check_hcsp_type(
                    source + "\n" + format_type_source(constructed)
                )
                self.assertEqual(checked, constructed)


    def test_nested_same_name_mu_cannot_capture_outer_recursive_edge(self) -> None:
        r"""Verify nested same name mu cannot capture outer recursive edge."""

        constructed = construct_hcsp_type(_NESTED_CROSS_SCOPE_RECURSION_SOURCE)
        supplied = format_type_source(constructed)
        supplied = supplied.replace("mu t2.", "mu t1.")
        supplied = supplied.replace("c! -> t2", "c! -> t1")

        with self.assertRaises(HCSPTypeCheckingError) as caught:
            check_hcsp_type(
                _NESTED_CROSS_SCOPE_RECURSION_SOURCE + "\n" + supplied
            )
        self.assertEqual(caught.exception.verdict, "false")
        self.assertIn(
            "TypeVar bound to process variable 'X'",
            caught.exception.reason,
        )


    def test_nested_same_name_mu_is_allowed_without_cross_scope_edge(self) -> None:
        r"""Verify nested same name mu is allowed without cross scope edge."""

        constructed = construct_hcsp_type(_NESTED_SHADOW_ONLY_RECURSION_SOURCE)
        supplied = format_type_source(constructed)
        supplied = supplied.replace("mu t2.", "mu t1.")
        supplied = supplied.replace("c! -> t2", "c! -> t1")

        checked = check_hcsp_type(
            _NESTED_SHADOW_ONLY_RECURSION_SOURCE + "\n" + supplied
        )
        self.assertEqual(format_type_source(checked), supplied)


    def test_constructor_roundtrip_covers_multiway_external_interrupts(self) -> None:
        r"""Verify constructor roundtrip covers multiway external interrupts."""

        constructed = construct_hcsp_type(_INFINITE_ODE_SOURCE)
        checked = check_hcsp_type(
            _INFINITE_ODE_SOURCE + "\n" + format_type_source(constructed)
        )
        self.assertEqual(checked, constructed)


    def test_constructor_roundtrip_preserves_nested_internal_choice_blocks(self) -> None:
        r"""Verify constructor roundtrip preserves nested internal choice blocks."""

        for source in (_NESTED_IF_SOURCE, _NESTED_CHOICE_SOURCE):
            with self.subTest(source=source):
                constructed = construct_hcsp_type(source)
                checked = check_hcsp_type(
                    source + "\n" + format_type_source(constructed)
                )
                self.assertEqual(checked, constructed)


    def test_nested_choice_blocks_do_not_exchange_type_branches(self) -> None:
        r"""Verify nested choice blocks do not exchange type branches."""

        constructed = construct_hcsp_type(_NESTED_IF_SOURCE)
        supplied = format_type_source(constructed)
        supplied = supplied.replace("a!", "__first__!", 1)
        supplied = supplied.replace("b!", "a!", 1)
        supplied = supplied.replace("__first__!", "b!", 1)
        with self.assertRaises(HCSPTypeCheckingError) as caught:
            check_hcsp_type(_NESTED_IF_SOURCE + "\n" + supplied)
        self.assertEqual(caught.exception.verdict, "false")
        self.assertIn("same channel", caught.exception.reason)
    def test_nested_choice_rejects_different_parenthesized_grouping(self) -> None:
        r"""Verify nested choice rejects different parenthesized grouping."""

        constructed = construct_hcsp_type(_NESTED_IF_SOURCE)
        self.assertIsInstance(constructed, InternalChoiceType)
        outer = constructed
        assert isinstance(outer, InternalChoiceType)
        self.assertIsInstance(outer.branches[0], InternalChoiceType)
        left = outer.branches[0]
        assert isinstance(left, InternalChoiceType)
        regrouped = InternalChoiceType(
            (
                left.branches[0],
                InternalChoiceType((left.branches[1], outer.branches[1])),
            )
        )

        with self.assertRaises(HCSPTypeCheckingError) as caught:
            check_hcsp_type(
                _NESTED_IF_SOURCE + "\n" + format_type_source(regrouped)
            )
        self.assertEqual(caught.exception.verdict, "false")
        self.assertIn("T-sqcup requires InternalChoiceType", caught.exception.reason)


    def test_wrong_branch_inside_multiway_choice_is_rejected(self) -> None:
        r"""Verify wrong branch inside multiway choice is rejected."""

        constructed = construct_hcsp_type(_CHOICE_SOURCE)
        supplied = format_type_source(constructed).replace("a!", "wrong!", 1)
        with self.assertRaises(HCSPTypeCheckingError) as caught:
            check_hcsp_type(_CHOICE_SOURCE + "\n" + supplied)
        self.assertEqual(caught.exception.verdict, "false")
        self.assertIn("same channel", caught.exception.reason)


    def test_finite_ode_rejects_wrong_duration_before_proof(self) -> None:
        r"""Verify finite ODE rejects wrong duration before proof."""

        source = """gamma(x: Real, motion: continuous(x))
theta()
process {{ode(flow(dot x = 0), domain(t < 1), safety(true), delay(1)); skip}}
type delay(2) then empty"""
        parsed = parse_typechecking_source(source)
        request = TypeCheckingRequest(
            parsed.program.gamma,
            parsed.program.theta,
            (Configuration({}, parsed.program.process_components[0], name="K1"),),
            parsed.expected_type,
            parameters=parsed.program.parameters,
        )
        calls: list[object] = []


        def prove(formula: object) -> Verdict:
            r"""Return role-specific mock proofs to isolate checking structure."""

            calls.append(formula)
            return Verdict.TRUE

        report = TypeChecker(dl_checker=prove).check(request)
        self.assertEqual(report.verdict, Verdict.FALSE)
        self.assertIn("annotation delay is 1", report.mismatch)
        self.assertEqual(calls, [])


    def test_finite_ode_checks_interrupt_and_timeout_children(self) -> None:
        r"""Verify finite ODE checks interrupt and timeout children."""

        source = """gamma(x: Real, motion: continuous(x))
theta()
process {{ode(flow(dot x = 0), domain(t < 1), safety(true), delay(1)); skip}}
type delay(1) then empty"""
        parsed = parse_typechecking_source(source)
        request = TypeCheckingRequest(
            parsed.program.gamma,
            parsed.program.theta,
            (Configuration({}, parsed.program.process_components[0], name="K1"),),
            parsed.expected_type,
            parameters=parsed.program.parameters,
        )
        calls: list[object] = []


        def prove(formula: object) -> Verdict:
            r"""Return role-specific mock proofs to isolate checking structure."""

            calls.append(formula)
            role = getattr(getattr(formula, "formula", None), "role", "")
            return Verdict.FALSE if role == "domain" else Verdict.TRUE

        report = TypeChecker(dl_checker=prove).check(request)
        self.assertEqual(report.verdict, Verdict.TRUE)
        self.assertTrue(report.structurally_matched)
        # The supplied Empty tail excludes the communication-only rule before any domain proof
        # runs.
        self.assertEqual(len(calls), 1)
        self.assertEqual(
            {item.rule for item in report.evidence.obligations},
            {
                "T-ODE-safety",
                "T-ODE-boundary",
                "T-sigma",
            },
        )
        self.assertEqual(
            {
                item.rule
                for item in report.evidence.obligations
                if item.active
            },
            {"T-ODE-safety", "T-ODE-boundary", "T-sigma"},
        )


    def test_bottom_continuation_selects_communication_rule(self) -> None:
        r"""Verify bottom continuation selects communication rule."""

        source = """gamma(x: Real, motion: continuous(x))
theta()
process {{ode(flow(dot x = 0), domain(t < 1), safety(true), delay(1)); skip}}
type delay(1) then bottom"""
        parsed = parse_typechecking_source(source)
        request = TypeCheckingRequest(
            parsed.program.gamma,
            parsed.program.theta,
            (Configuration({}, parsed.program.process_components[0], name="K1"),),
            parsed.expected_type,
            parameters=parsed.program.parameters,
        )

        def prove(formula: object) -> Verdict:
            r"""Return role-specific mock proofs to isolate checking structure."""

            role = getattr(getattr(formula, "formula", None), "role", "")
            return Verdict.TRUE

        report = TypeChecker(dl_checker=prove).check(request)

        self.assertEqual(report.verdict, Verdict.TRUE)
        self.assertTrue(report.structurally_matched)
        domain = next(
            item
            for item in report.evidence.obligations
            if item.rule == "T-ODE-domain"
        )
        self.assertEqual(domain.verdict, Verdict.TRUE)
        self.assertTrue(domain.active)
        self.assertNotIn(
            "T-ODE-boundary",
            {item.rule for item in report.evidence.obligations},
        )


    def test_checker_drops_unevolved_fact_across_ode(self) -> None:
        r"""Verify checker drops unevolved fact across ODE."""

        source = """gamma(x: Real, ode_x: continuous(x))
theta(set: channel(first: Real, second: Real) where(first == 0 and second > 0))
process {{
    set?(x, y);
    ode(flow(dot x = 1), domain(t < 1), safety(true), delay(1));
    assert(y > 0)
}}
type forever interrupt angelic {
    set? -> delay(1) then empty
}"""
        parsed = parse_typechecking_source(source)
        request = TypeCheckingRequest(
            parsed.program.gamma,
            parsed.program.theta,
            (Configuration({}, parsed.program.process_components[0], name="K1"),),
            parsed.expected_type,
            parameters=parsed.program.parameters,
        )
        report = TypeChecker(dl_checker=lambda _formula: Verdict.TRUE).check(request)

        self.assertEqual(report.verdict, Verdict.FALSE, report.format_detailed())
        self.assertFalse(report.structurally_matched)


    def test_matching_shape_is_rejected_when_formula_premise_is_false(self) -> None:
        r"""Verify matching shape is rejected when formula premise is false."""

        source = "gamma() theta() process {{assert(false)}}\ntype empty"
        with self.assertRaises(HCSPTypeCheckingError) as caught:
            check_hcsp_type(source)
        self.assertEqual(caught.exception.verdict, "false")
        self.assertIn("counterexample", caught.exception.reason)


    def test_checker_rejects_real_input_into_existing_int_target(self) -> None:
        r"""Verify checker rejects Real input into existing Int target."""

        source = """gamma(x: Int)
theta(ch: channel(v: Real))
process {{ch?(x)}}
type forever interrupt angelic {
    ch? -> empty
}"""

        with self.assertRaises(HCSPTypeCheckingError) as caught:
            check_hcsp_type(source)
        self.assertEqual(caught.exception.verdict, "false")
        self.assertIn(
            "has type Int, channel slot carries Real",
            caught.exception.reason,
        )


    def test_checker_rejects_invalid_refinement_on_unused_channel(self) -> None:
        r"""Verify checker rejects invalid refinement on unused channel."""

        source = """gamma()
theta(bad: channel(value: Real) where(value + 1))
process {{skip}}
type empty"""

        with self.assertRaises(HCSPTypeCheckingError) as caught:
            check_hcsp_type(source)
        self.assertEqual(caught.exception.verdict, "false")
        self.assertIn("Expected Bool formula", caught.exception.reason)


    def test_checker_does_not_call_type_constructor_construct(self) -> None:
        r"""Verify checker does not call type constructor construct."""

        with patch(
            "hcsp_typechecker.backend.type_constructor.constructor."
            "TypeConstructor.construct",
            side_effect=AssertionError("constructor must not run"),
        ) as construct:
            checked = check_hcsp_type(
                "gamma() theta() process {{skip}}\ntype empty"
            )
        self.assertEqual(str(checked), "0")
        construct.assert_not_called()


    def test_checker_result_and_full_outputs_have_distinct_detail(self) -> None:
        r"""Verify checker result and full outputs have distinct detail."""

        source = _DISCRETE_SOURCE + "\ntype empty"
        result_stream = StringIO()
        full_stream = StringIO()
        result_type = check_hcsp_type(
            source,
            output="result",
            stream=result_stream,
        )
        full_type = check_hcsp_type(
            source,
            output="full",
            stream=full_stream,
        )
        self.assertEqual(result_type, full_type)
        self.assertIn('HCSP type checking result', result_stream.getvalue())
        self.assertNotIn('Original user input', result_stream.getvalue())
        self.assertIn('HCSP type checking full log', full_stream.getvalue())
        self.assertIn('Original user input', full_stream.getvalue())
        self.assertIn('Supplied Type checking and proof report', full_stream.getvalue())
        self.assertIn("T-Assign-post", full_stream.getvalue())


if __name__ == "__main__":
    unittest.main()
