r"""Regression tests for doctor. Paper reference: Section 4.3, Table 2."""

from pathlib import Path
import shutil
import unittest
from unittest.mock import patch

from hcsp_typechecker.tooling.doctor import collect_environment, format_environment
from hcsp_typechecker.backend.common.keymaerax import KeYmaeraXConfig


class EnvironmentDoctorTests(unittest.TestCase):
    r"""Tests for Environment Doctor."""

    def setUp(self) -> None:
        r"""Create isolated writable test fixtures."""

        self.runtime = (
            Path(__file__).parent
            / "_runtime"
            / self._testMethodName
        )
        self.runtime.mkdir(parents=True, exist_ok=True)

    def tearDown(self) -> None:
        r"""Remove temporary test fixtures."""

        runtime_root = Path(__file__).parent / "_runtime"
        if self.runtime.exists():
            shutil.rmtree(self.runtime)
        if runtime_root.exists() and not any(runtime_root.iterdir()):
            runtime_root.rmdir()


    def test_explicit_full_environment_is_reported_ready(self) -> None:
        r"""Verify explicit full environment is reported ready."""

        java = self.runtime / "java-placeholder"
        jar = self.runtime / "keymaerax.jar"
        java.write_text("placeholder", encoding="utf-8")
        jar.write_text("placeholder", encoding="utf-8")
        config = KeYmaeraXConfig(jar_path=jar, java_path=java)

        with patch(
            "hcsp_typechecker.tooling.doctor._java_version",
            return_value='openjdk version "21"',
        ):
            checks = collect_environment(
                require_keymaerax=True,
                config=config,
            )

        self.assertTrue(all(check.available for check in checks))
        rendered = format_environment(checks)
        self.assertIn("HCSP behavioral type environment", rendered)
        self.assertIn("Core type engine ready : yes", rendered)
        self.assertIn("KeYmaera X ready   : yes", rendered)


if __name__ == "__main__":
    unittest.main()
