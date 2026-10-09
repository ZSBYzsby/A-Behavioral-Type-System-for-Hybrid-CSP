r"""Regression tests for backend boundaries. Paper reference: Table 3, Table 2."""

from __future__ import annotations

from pathlib import Path
import unittest

import hcsp_typechecker
from hcsp_typechecker.backend.common.rule_engine import Table2RuleEngine
from hcsp_typechecker.backend.common.environment import PreparedTypingEnvironment
from hcsp_typechecker.backend.type_checker import TypeChecker
from hcsp_typechecker.backend.type_constructor import TypeConstructor


class BackendBoundaryTests(unittest.TestCase):
    r"""Tests for Backend Boundary."""


    def test_business_backends_share_engine_without_inheriting_each_other(self) -> None:
        r"""Verify business backends share engine without inheriting each other."""

        self.assertTrue(issubclass(TypeConstructor, Table2RuleEngine))
        self.assertTrue(issubclass(TypeChecker, Table2RuleEngine))
        self.assertFalse(issubclass(TypeChecker, TypeConstructor))
        self.assertFalse(issubclass(TypeConstructor, TypeChecker))


    def test_typing_environment_preparation_has_one_common_implementation(self) -> None:
        r"""Verify typing environment preparation has one common implementation."""

        self.assertIn("_prepare_typing_environment", Table2RuleEngine.__dict__)
        self.assertNotIn("_prepare_typing_environment", TypeConstructor.__dict__)
        self.assertNotIn("_prepare_typing_environment", TypeChecker.__dict__)
        self.assertEqual(
            PreparedTypingEnvironment.__module__,
            "hcsp_typechecker.backend.common.environment",
        )


    def test_common_backend_does_not_import_business_backends(self) -> None:
        r"""Verify common backend does not import business backends."""

        common = Path(hcsp_typechecker.__file__).parent / "backend" / "common"
        source = "\n".join(
            path.read_text(encoding="utf-8")
            for path in sorted(common.glob("*.py"))
        )
        self.assertNotIn("backend.type_constructor", source)
        self.assertNotIn("backend.type_checker", source)
        self.assertNotIn("..type_constructor", source)
        self.assertNotIn("..type_checker", source)


    def test_business_backends_do_not_import_each_other(self) -> None:
        r"""Verify business backends do not import each other."""

        backend = Path(hcsp_typechecker.__file__).parent / "backend"
        constructor_source = (
            backend / "type_constructor" / "constructor.py"
        ).read_text(encoding="utf-8")
        checker_source = (
            backend / "type_checker" / "checker.py"
        ).read_text(encoding="utf-8")
        self.assertNotIn("type_checker", constructor_source)
        self.assertNotIn("type_constructor", checker_source)


    def test_operational_semantics_does_not_import_table2_backends(self) -> None:
        r"""Verify operational semantics does not import table2 backends."""

        semantics = (
            Path(hcsp_typechecker.__file__).parent
            / "backend"
            / "type_operational_semantics"
        )
        source = "\n".join(
            path.read_text(encoding="utf-8")
            for path in sorted(semantics.glob("*.py"))
        )
        self.assertNotIn("type_constructor", source)
        self.assertNotIn("type_checker", source)


    def test_data_structures_contain_only_domain_models(self) -> None:
        r"""Verify data structures contain only domain models."""

        data_structures = (
            Path(hcsp_typechecker.__file__).parent / "data_structures"
        )
        self.assertFalse((data_structures / "type_construction").exists())
        self.assertFalse((data_structures / "type_checking").exists())
        source = "\n".join(
            path.read_text(encoding="utf-8")
            for path in sorted(data_structures.rglob("*.py"))
        )
        self.assertNotIn("backend.", source)
        self.assertNotIn("..backend", source)


    def test_legacy_mixed_backend_directory_is_removed(self) -> None:
        r"""Verify legacy mixed backend directory is removed."""

        package = Path(hcsp_typechecker.__file__).parent
        self.assertFalse((package / "typechecking").exists())


if __name__ == "__main__":
    unittest.main()
