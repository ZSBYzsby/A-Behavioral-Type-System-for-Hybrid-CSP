r"""Regression tests for value types. Paper reference: Definition 4.1, Table 2."""

from __future__ import annotations

import unittest

from hcsp_typechecker.data_structures.runtime_context import (
    BasicType,
    ChannelType,
    ContinuousType,
    gamma_value_type,
    is_subtype,
    normalize_channel_type,
    normalize_gamma_type,
    normalize_type,
)


class BasicTypeBoundaryTests(unittest.TestCase):
    r"""Tests for Basic Type Boundary."""


    def test_basic_type_contains_only_supported_paper_value_types(self) -> None:
        r"""Verify basic type contains only supported paper value types."""

        self.assertEqual(
            tuple(BasicType),
            (
                BasicType.BOOL,
                BasicType.NAT,
                BasicType.INT,
                BasicType.RATIONAL,
                BasicType.REAL,
            ),
        )


    def test_supported_type_specifications_are_normalized(self) -> None:
        r"""Verify supported type specifications are normalized."""

        cases = {
            "Bool": BasicType.BOOL,
            "Nat": BasicType.NAT,
            "Int": BasicType.INT,
            "Rational": BasicType.RATIONAL,
            "Real": BasicType.REAL,
            bool: BasicType.BOOL,
            int: BasicType.INT,
            float: BasicType.REAL,
        }
        for source, expected in cases.items():
            with self.subTest(source=source):
                self.assertIs(normalize_type(source), expected)


    def test_numeric_subtyping_remains_directional(self) -> None:
        r"""Verify numeric subtyping remains directional."""

        self.assertTrue(is_subtype(BasicType.NAT, BasicType.REAL))
        self.assertTrue(is_subtype(BasicType.INT, BasicType.RATIONAL))
        self.assertFalse(is_subtype(BasicType.REAL, BasicType.INT))
        self.assertFalse(is_subtype(BasicType.BOOL, BasicType.INT))
        self.assertTrue(is_subtype(BasicType.BOOL, BasicType.BOOL))


class ChannelTypeBoundaryTests(unittest.TestCase):
    r"""Tests for Channel Type Boundary."""


    def test_channel_signature_uses_independent_basic_slots(self) -> None:
        r"""Verify channel signature uses independent basic slots."""

        scalar = ChannelType("Int")
        self.assertEqual(scalar.value_types, (BasicType.INT,))
        self.assertEqual(scalar.binders, ("eta",))

        multiple = normalize_channel_type((BasicType.INT, "Real", bool))
        self.assertEqual(
            multiple.value_types,
            (BasicType.INT, BasicType.REAL, BasicType.BOOL),
        )
        self.assertEqual(multiple.binders, ("eta1", "eta2", "eta3"))

        explicit = ChannelType(
            (BasicType.INT, BasicType.REAL),
            "left <= right",
            binders=("left", "right"),
        )
        self.assertEqual(explicit.binders, ("left", "right"))

        invalid_declarations = (
            lambda: ChannelType(()),
            lambda: ChannelType((BasicType.INT, (BasicType.REAL,))),
            lambda: ChannelType((BasicType.INT, BasicType.REAL), binders=("x",)),
            lambda: ChannelType((BasicType.INT, BasicType.REAL), binders=("x", "x")),
            lambda: ChannelType((BasicType.INT,), binders=("not valid",)),
            lambda: ChannelType((BasicType.INT,), binders=("\u03b1\u03b2",)),
            lambda: ChannelType((BasicType.INT,), binders=("ｘ",)),
        )
        for declaration in invalid_declarations:
            with self.subTest(declaration=declaration):
                with self.assertRaises((TypeError, ValueError)):
                    declaration()


class ContinuousTypeBoundaryTests(unittest.TestCase):
    r"""Tests for Continuous Type Boundary."""


    def test_continuous_declaration_is_not_a_scalar_value(self) -> None:
        r"""Verify continuous declaration is not a scalar value."""

        continuous = ContinuousType(("x",))

        self.assertNotEqual(continuous, BasicType.REAL)
        self.assertIs(normalize_gamma_type(BasicType.REAL), BasicType.REAL)
        self.assertIs(normalize_gamma_type(continuous), continuous)
        with self.assertRaises(TypeError):
            gamma_value_type(continuous)
        self.assertEqual(str(continuous), "R>=0 ~> Real on (x)")


    def test_continuous_type_no_longer_accepts_trajectory_property(self) -> None:
        r"""Verify continuous type no longer accepts trajectory property."""

        with self.assertRaises(TypeError):
            ContinuousType(phi="x >= 0")  # type: ignore[call-arg]
        self.assertFalse(hasattr(ContinuousType(("x",)), "phi"))


    def test_continuous_type_stores_explicit_vector_members(self) -> None:
        r"""Verify continuous type stores explicit vector members."""

        trajectory = ContinuousType(
            variables=("p", "v", "a"),
        )

        self.assertEqual(trajectory.variables, ("a", "p", "v"))
        self.assertEqual(
            trajectory,
            ContinuousType(variables=("a", "v", "p")),
        )
        self.assertIn("R^3", str(trajectory))
        self.assertIn("on (a, p, v)", str(trajectory))


    def test_continuous_vector_rejects_invalid_members(self) -> None:
        r"""Verify continuous vector rejects invalid members."""

        invalid_declarations = (
            lambda: ContinuousType(variables=()),
            lambda: ContinuousType(variables=("x", "x")),
            lambda: ContinuousType(variables=("not valid",)),
            lambda: ContinuousType(variables=("\u03b1\u03b2",)),
            lambda: ContinuousType(variables=("ｘ",)),
            lambda: ContinuousType(variables="x"),
        )
        for declaration in invalid_declarations:
            with self.subTest(declaration=declaration):
                with self.assertRaises((TypeError, ValueError)):
                    declaration()


    def test_continuous_type_requires_vector_and_rejects_channel_use(self) -> None:
        r"""Verify continuous type requires vector and rejects channel use."""

        with self.assertRaises(TypeError):
            ContinuousType()  # type: ignore[call-arg]
        with self.assertRaises(TypeError):
            ChannelType(ContinuousType(("x",)))


if __name__ == "__main__":
    unittest.main()
