r"""Regression tests for case study scripts. Paper reference: Section 5."""

from __future__ import annotations

import ast
from contextlib import redirect_stdout
from fractions import Fraction
import importlib.util
from io import StringIO
import os
from pathlib import Path
from types import ModuleType
import unittest
from unittest.mock import patch

from hcsp_typechecker import (
    HCSPTypeConstructionError,
    HCSPUntrustedTypeConstructionError,
    construct_hcsp_type,
)


PROJECT_ROOT = Path(__file__).resolve().parents[2]
CASE_DIRECTORY = PROJECT_ROOT / "examples"
COMMON_PUBLIC_IMPORTS = {
    "HCSPInputError",
    "HCSPTypeConstructionError",
    "construct_hcsp_type",
}
EXPECTED_PUBLIC_IMPORTS = {
    # The original case expects proof-unknown; the strengthened case fails on an untrusted
    # candidate.
    "case_study_original.py": COMMON_PUBLIC_IMPORTS
    | {
        "HCSPUntrustedTypeConstructionError",
        "TypeConstructionErrorKind",
    },
    "case_study_revised.py": COMMON_PUBLIC_IMPORTS
    | {
        "HCSPTypeTransitionGraphError",
        "HCSPTypeLockAnalysisError",
        "HCSPUntrustedTypeConstructionError",
        "build_type_transition_graph",
        "analyze_type_lock_freedom",
    },
}


def _load_case_module(filename: str) -> ModuleType:
    r"""Load a case script independently of package installation."""

    path = CASE_DIRECTORY / filename
    module_name = "_hcsp_case_test_" + path.stem
    specification = importlib.util.spec_from_file_location(module_name, path)
    if specification is None or specification.loader is None:
        raise RuntimeError(f"Cannot load case-study module {path}")
    module = importlib.util.module_from_spec(specification)
    specification.loader.exec_module(module)
    return module


def _unverified_candidate_error() -> HCSPUntrustedTypeConstructionError:
    r"""Create a genuine public unverified-candidate exception with a controlled prover."""

    with patch(
        "hcsp_typechecker.backend.common.keymaerax.KeYmaeraXBackend.__call__",
        return_value=None,
    ):
        try:
            construct_hcsp_type(
                "gamma() theta() process {{"
                "ode(flow(), domain(t < 1), delay(1)); skip}}"
            )
        except HCSPUntrustedTypeConstructionError as error:
            return error
    raise AssertionError("The fixture must produce a complete unverified candidate")


class CaseStudyPublicInterfaceTests(unittest.TestCase):
    r"""Tests for Case Study Public Interface."""


    def test_case_scripts_import_only_the_single_stable_facade(self) -> None:
        r"""Verify case scripts import only the single stable facade."""

        for filename in ("case_study_original.py", "case_study_revised.py"):
            path = CASE_DIRECTORY / filename
            tree = ast.parse(path.read_text(encoding="utf-8"), filename=str(path))
            project_imports = [
                node
                for node in ast.walk(tree)
                if isinstance(node, ast.ImportFrom)
                and node.module is not None
                and node.module.startswith("hcsp_typechecker")
            ]
            with self.subTest(filename=filename):
                self.assertEqual(len(project_imports), 1)
                self.assertEqual(project_imports[0].module, "hcsp_typechecker")
                self.assertEqual(
                    {alias.name for alias in project_imports[0].names},
                    EXPECTED_PUBLIC_IMPORTS[filename],
                )


    def test_case_sources_cross_parsing_boundary_through_single_entrypoint(
        self,
    ) -> None:
        r"""Verify case sources cross parsing boundary through single entrypoint."""

        original = _load_case_module("case_study_original.py")
        improved = _load_case_module("case_study_revised.py")
        period = Fraction(3, 2)
        sources = {
            "original": original._build_original_case_source(period),
            "improved": improved.build_source(period),
        }

        for name, source in sources.items():
            with self.subTest(case=name):
                self.assertIn("delay((3/2))", source)
                self.assertIn("ode(flow(), domain(t < (3/2)), delay((3/2)))", source)
                with self.assertRaises(HCSPTypeConstructionError) as captured:
                    construct_hcsp_type(
                        source,
                        source_name=f"case-study-{name}.hcsp",
                        path_condition=False,
                        output="none",
                    )
                error = captured.exception
                self.assertEqual(error.verdict, "false")
                self.assertEqual(error.partial_types, (None, None))
                self.assertIn("T-sigma", error.format_result())


    def test_original_case_requires_the_expected_unverified_candidate(self) -> None:
        r"""Distinguish reproduction of the original outcome from unexpected proof success."""

        original = _load_case_module("case_study_original.py")
        candidate_error = _unverified_candidate_error()
        trusted_type = construct_hcsp_type("gamma() theta() process {{skip}}")
        outcomes = (
            ("unverified", {"side_effect": candidate_error}, 0),
            ("unexpected-trusted", {"return_value": trusted_type}, 1),
        )
        for label, result, expected in outcomes:
            with self.subTest(outcome=label), patch.dict(os.environ), patch.object(
                original, "construct_hcsp_type", **result
            ), redirect_stdout(StringIO()):
                self.assertEqual(original.main(["--d", "1"]), expected)


    def test_revised_case_stops_before_analysis_for_unverified_candidates(self) -> None:
        r"""Keep unresolved proofs from proceeding as trusted graph-analysis inputs."""

        revised = _load_case_module("case_study_revised.py")
        candidate_error = _unverified_candidate_error()
        with patch.dict(os.environ), patch.object(
            revised, "construct_hcsp_type", side_effect=candidate_error
        ), patch.object(revised, "build_type_transition_graph") as graph_builder, patch.object(
            revised, "analyze_type_lock_freedom"
        ) as analyzer, redirect_stdout(StringIO()):
            self.assertEqual(revised.main(["--d", "1"]), 1)
        graph_builder.assert_not_called()
        analyzer.assert_not_called()


    def test_revised_case_requires_lock_freedom_after_trusted_construction(self) -> None:
        r"""Use real graphs to check acceptance of synchronization and rejection of deadlock."""

        revised = _load_case_module("case_study_revised.py")
        prefix = "gamma(x: Int) theta(ch: channel(value: Int)) "
        programs = (
            ("synchronizing", prefix + "process {{ch?(x)}, {ch!(1)}}", 0),
            ("deadlocked", prefix + "process {{ch?(x)}}", 1),
        )
        for label, source, expected in programs:
            trusted_type = construct_hcsp_type(source)
            with self.subTest(case=label), patch.dict(os.environ), patch.object(
                revised, "construct_hcsp_type", return_value=trusted_type
            ), redirect_stdout(StringIO()):
                self.assertEqual(revised.main(["--d", "1"]), expected)


if __name__ == "__main__":
    unittest.main()
