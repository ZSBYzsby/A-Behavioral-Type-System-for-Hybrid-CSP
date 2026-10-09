r"""Regression tests for type demo. Paper reference: Table 2."""

from __future__ import annotations

from contextlib import redirect_stdout
from io import StringIO
import unittest
from unittest.mock import patch

from examples import demo_ode_type_round_trip as round_trip_demo


class TypeDemoRoundTripTests(unittest.TestCase):
    r"""Tests for Type Demo Round Trip."""


    def test_sixth_demo_round_trips_through_constructor_and_checker(self) -> None:
        r"""Verify sixth demo round trips through constructor and checker."""

        output = StringIO()
        with patch(
            "hcsp_typechecker.backend.common.keymaerax."
            "KeYmaeraXBackend.__call__",
            return_value=True,
        ) as backend, redirect_stdout(output):
            exit_code = round_trip_demo.main()

        rendered = output.getvalue()
        self.assertEqual(exit_code, 0)
        self.assertGreater(backend.call_count, 0)
        self.assertIn('Type source : type delay(3/2)', rendered)
        self.assertIn("reset? -> forever interrupt angelic", rendered)
        self.assertIn('Round trip succeeded', rendered)
        self.assertNotIn("FiniteDelayType", rendered)


if __name__ == "__main__":
    unittest.main()
