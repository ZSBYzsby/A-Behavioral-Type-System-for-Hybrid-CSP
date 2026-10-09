r"""Regression tests for recursive tail skip."""

from __future__ import annotations

import unittest

from hcsp_typechecker import (
    HCSPTypeConstructionError,
    check_hcsp_type,
    construct_hcsp_type,
)
from hcsp_typechecker.frontend.type_syntax import format_type_source


_CHOICE_WITH_IMPLICIT_SKIP = """gamma()
theta(a: channel(value: Int), b: channel(value: Int))
process {{
    mu X invariant(true) {
        choose {a!(0); call X} or {b!(0); call X}
    }
}}"""


class RecursiveTailSkipTests(unittest.TestCase):
    r"""Tests for Recursive Tail Skip."""


    def test_choice_default_skip_preserves_tail_recursion(self) -> None:
        r"""Verify choice default skip preserves tail recursion."""

        constructed = construct_hcsp_type(_CHOICE_WITH_IMPLICIT_SKIP)
        checked = check_hcsp_type(
            _CHOICE_WITH_IMPLICIT_SKIP + "\n" + format_type_source(constructed)
        )

        self.assertEqual(format_type_source(checked), format_type_source(constructed))


    def test_explicit_skip_after_call_is_still_tail_position(self) -> None:
        r"""Verify explicit skip after call is still tail position."""

        source = """gamma()
theta(a: channel(value: Int))
process {{mu X invariant(true) {a!(0); call X; skip}}}"""

        construct_hcsp_type(source)


    def test_non_skip_after_call_remains_non_tail(self) -> None:
        r"""Verify non skip after call remains non tail."""

        source = """gamma()
theta(a: channel(value: Int))
process {{mu X invariant(true) {a!(0); call X; skip; assert(true)}}}"""

        with self.assertRaisesRegex(
            HCSPTypeConstructionError,
            "tail position",
        ):
            construct_hcsp_type(source)


    def test_skip_after_mu_is_not_an_observable_continuation(self) -> None:
        r"""Verify skip after mu is not an observable continuation."""

        source = """gamma()
theta(a: channel(value: Int))
process {{mu X invariant(true) {a!(0); call X}; skip}}"""

        construct_hcsp_type(source)


if __name__ == "__main__":
    unittest.main()
