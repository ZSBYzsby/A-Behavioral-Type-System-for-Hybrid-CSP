r"""Regression tests for KeYmaera X backend. Paper reference: Section 4.3."""

from __future__ import annotations

from dataclasses import replace
from pathlib import Path
import shutil
import subprocess
import unittest
from unittest.mock import patch

from hcsp_typechecker._internal import (
    BasicType,
    ChannelType,
    Configuration,
    ContinuousType,
    DLFormula,
    KeYmaeraXBackend,
    KeYmaeraXConfig,
    ODE,
    ODEAnnotation,
    OutputChannel,
    ProofObligation,
    Sequence,
    UntranslatedDLFormula,
    Verdict,
    construct_type,
)


class KeYmaeraXBackendTests(unittest.TestCase):
    r"""Tests for Ke Ymaera X Backend."""

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

        if self.runtime.exists():
            shutil.rmtree(self.runtime)

    @classmethod
    def tearDownClass(cls) -> None:
        r"""Remove the empty shared test directory."""

        runtime_root = Path(__file__).parent / "_runtime"
        if runtime_root.exists():
            runtime_root.rmdir()

    def _fixture(
        self,
        directory: str | Path,
        *,
        cli_style: str = "legacy",
    ) -> tuple[KeYmaeraXBackend, ProofObligation]:
        r"""Create placeholder prover executables and a test obligation."""

        root = Path(directory)
        java = root / "java.exe"
        jar = root / "keymaerax.jar"
        java.write_bytes(b"test java placeholder")
        jar.write_bytes(b"test jar placeholder")
        config = KeYmaeraXConfig(
            jar_path=jar,
            java_path=java,
            home_directory=root / "home",
            timeout_seconds=3,
            cli_style=cli_style,  # type: ignore[arg-type]
            keep_artifacts=True,
            artifacts_directory=root / "artifacts",
        )
        formula = DLFormula(
            "(kxv0=kxv0)",
            ("kxv0",),
            (("kxv0", "x"),),
            "test",
        )
        obligation = ProofObligation(
            "T-ODE-test",
            "test dL formula",
            formula,
            kind="dl",
        )
        return KeYmaeraXBackend(config), obligation


    def test_environment_variables_build_portable_configuration(self) -> None:
        r"""Verify environment variables build portable configuration."""

        environment = {
            "KEYMAERAX_JAR": str(self.runtime / "keymaerax.jar"),
            "KEYMAERAX_JAVA": str(self.runtime / "java"),
            "KEYMAERAX_HOME": str(self.runtime / "home"),
            "KEYMAERAX_TIMEOUT": "45",
            "KEYMAERAX_KEEP_ARTIFACTS": "yes",
            "KEYMAERAX_ARTIFACTS": str(self.runtime / "evidence"),
            "KEYMAERAX_CLI_STYLE": "modern",
            "KEYMAERAX_TACTIC": "auto",
            "KEYMAERAX_ARITHMETIC_TOOL": "Z3",
        }
        with patch.dict(
            "hcsp_typechecker.backend.common.keymaerax.os.environ",
            environment,
            clear=True,
        ):
            config = KeYmaeraXConfig.from_environment()

        self.assertEqual(config.jar_path, environment["KEYMAERAX_JAR"])
        self.assertEqual(config.java_path, environment["KEYMAERAX_JAVA"])
        self.assertEqual(config.home_directory, environment["KEYMAERAX_HOME"])
        self.assertEqual(config.timeout_seconds, 45.0)
        self.assertTrue(config.keep_artifacts)
        self.assertEqual(
            config.artifacts_directory,
            environment["KEYMAERAX_ARTIFACTS"],
        )
        self.assertEqual(config.cli_style, "modern")
        self.assertEqual(config.tactic, "auto")
        self.assertEqual(config.arithmetic_tool, "Z3")


    def test_java_home_is_used_when_explicit_java_is_absent(self) -> None:
        r"""Verify java home is used when explicit java is absent."""

        java = self.runtime / "jdk" / "bin" / "java.exe"
        java.parent.mkdir(parents=True)
        java.write_text("test java placeholder", encoding="utf-8")
        backend = KeYmaeraXBackend(KeYmaeraXConfig())

        with patch.dict(
            "hcsp_typechecker.backend.common.keymaerax.os.environ",
            {"JAVA_HOME": str(self.runtime / "jdk")},
            clear=True,
        ), patch(
            "hcsp_typechecker.backend.common.keymaerax.shutil.which",
            return_value=None,
        ):
            resolved = backend._java_executable()

        self.assertEqual(resolved, str(java))


    def test_missing_jar_is_unknown_with_configuration_help(self) -> None:
        r"""Verify missing jar is unknown with configuration help."""

        backend = KeYmaeraXBackend(
            KeYmaeraXConfig(
                jar_path=None,
                java_path=None,
            )
        )
        result = backend.check(
            ProofObligation(
                "test",
                "test",
                DLFormula("true", (), (), "test"),
                kind="dl",
            )
        )

        self.assertEqual(result.verdict, Verdict.UNKNOWN)
        self.assertIn("KEYMAERAX_JAR", result.detail)


    def test_untranslated_formula_never_starts_a_process(self) -> None:
        r"""Verify untranslated formula never starts a process."""

        backend = KeYmaeraXBackend()
        obligation = ProofObligation(
            "test",
            "test",
            UntranslatedDLFormula("safety", "unsupported function"),
            kind="dl",
        )
        with patch("hcsp_typechecker.backend.common.keymaerax.subprocess.run") as run:
            result = backend.check(obligation)

        self.assertEqual(result.verdict, Verdict.UNKNOWN)
        self.assertIn("unsupported function", result.detail)
        run.assert_not_called()


    def test_proved_status_maps_to_true_and_writes_valid_archive(self) -> None:
        r"""Verify proved status maps to true and writes valid archive."""

        backend, obligation = self._fixture(self.runtime)
        observed_archive: list[str] = []

        def successful_run(command: list[str], **options: object):
            r"""Inspect the generated archive before returning mock proof success."""

            input_path = Path(command[command.index("-prove") + 1])
            observed_archive.append(input_path.read_text(encoding="utf-8"))
            self.assertFalse(options["shell"])
            return subprocess.CompletedProcess(
                command,
                0,
                "PROVED T-ODE-test",
                "",
            )

        with patch(
            "hcsp_typechecker.backend.common.keymaerax.subprocess.run",
            side_effect=successful_run,
        ) as run:
            result = backend.check(obligation)

        self.assertEqual(result.verdict, Verdict.TRUE)
        self.assertIn("proved", result.detail)
        self.assertEqual(run.call_count, 1)
        self.assertIn("Problem\n  (kxv0=kxv0)\nEnd.", observed_archive[0])
        self.assertIn('Tactic "HCSP Proof"', observed_archive[0])


    def test_counterexample_status_maps_to_false(self) -> None:
        r"""Verify counterexample status maps to false."""

        backend, obligation = self._fixture(self.runtime)
        completed = subprocess.CompletedProcess(
            ["java"],
            255,
            "UNFINISHED (CEX) T-ODE-test",
            "",
        )
        with patch(
            "hcsp_typechecker.backend.common.keymaerax.subprocess.run",
            return_value=completed,
        ):
            result = backend.check(obligation)

        self.assertEqual(result.verdict, Verdict.FALSE)
        self.assertIn("counterexample", result.detail)


    def test_unfinished_and_failed_statuses_stay_unknown(self) -> None:
        r"""Verify unfinished and failed statuses stay unknown."""

        for status in ("UNFINISHED T-ODE-test", "FAILED T-ODE-test"):
            with self.subTest(status=status):
                backend, obligation = self._fixture(self.runtime)
                completed = subprocess.CompletedProcess(
                    ["java"],
                    255,
                    status,
                    "",
                )
                with patch(
                    "hcsp_typechecker.backend.common.keymaerax.subprocess.run",
                    return_value=completed,
                ):
                    result = backend.check(obligation)
                self.assertEqual(result.verdict, Verdict.UNKNOWN)


    def test_python_timeout_stays_unknown(self) -> None:
        r"""Verify python timeout stays unknown."""

        backend, obligation = self._fixture(self.runtime)
        with patch(
            "hcsp_typechecker.backend.common.keymaerax.subprocess.run",
            side_effect=subprocess.TimeoutExpired(["java"], 3),
        ):
            result = backend.check(obligation)

        self.assertEqual(result.verdict, Verdict.UNKNOWN)
        self.assertIn("3 seconds", result.detail)


    def test_interrupted_process_does_not_trust_captured_status(self) -> None:
        """A timeout invalidates positive and negative statuses from partial output."""

        backend, obligation = self._fixture(self.runtime)
        for status in ("PROVED T-ODE-test", "UNFINISHED (CEX) T-ODE-test"):
            with self.subTest(status=status), patch(
                "hcsp_typechecker.backend.common.keymaerax.subprocess.run",
                side_effect=subprocess.TimeoutExpired(["java"], 3, output=status),
            ):
                result = backend.check(obligation)
                self.assertIs(result.verdict, Verdict.UNKNOWN)
                self.assertIn("3 seconds", result.detail)


    def test_abnormal_exit_conflicting_statuses_and_log_prefixes_are_unknown(self) -> None:
        """Only consistent official statuses can decide a proof obligation."""

        backend, obligation = self._fixture(self.runtime)
        outputs = (
            (1, "PROVED T-ODE-test", "runtime failure", "exited abnormally"),
            (0, "PROVED T-ODE-test\nDISPROVED T-ODE-test", "", "conflicting"),
            (0, "PROVED T-ODE-test\nFAILED T-ODE-test", "", "conflicting"),
            (0, "PROVED T-ODE-test\nUNFINISHED T-ODE-test", "", "conflicting"),
            (0, "PROVED T-ODE-test\nTIMEOUT T-ODE-test", "", "timeout"),
            (0, "PROVEDNESS is incidental log text", "", "no recognized"),
            (0, "DISPROVEDNESS is incidental log text", "", "no recognized"),
            (0, "PROVED T-ODE-test", "HCSP_BACKEND_OS_ERROR: failed", "OS_ERROR"),
        )
        for code, stdout, stderr, reason in outputs:
            with self.subTest(stdout=stdout, code=code), patch(
                "hcsp_typechecker.backend.common.keymaerax.subprocess.run",
                return_value=subprocess.CompletedProcess(["java"], code, stdout, stderr),
            ):
                result = backend.check(obligation)
                self.assertIs(result.verdict, Verdict.UNKNOWN)
                self.assertIn(reason, result.detail)


    def test_auto_cli_retries_modern_style_only_after_usage_error(self) -> None:
        r"""Verify auto cli retries modern style only after usage error."""

        backend, obligation = self._fixture(
            self.runtime,
            cli_style="auto",
        )
        legacy_error = subprocess.CompletedProcess(
            ["java"],
            1,
            "",
            "Unknown option -prove\nUsage: keymaerax",
        )
        modern_success = subprocess.CompletedProcess(
            ["java"],
            0,
            "PROVED T-ODE-test",
            "",
        )
        with patch(
            "hcsp_typechecker.backend.common.keymaerax.subprocess.run",
            side_effect=(legacy_error, modern_success),
        ) as run:
            result = backend.check(obligation)

        self.assertEqual(result.verdict, Verdict.TRUE)
        self.assertEqual(run.call_count, 2)
        first_command = run.call_args_list[0].args[0]
        second_command = run.call_args_list[1].args[0]
        self.assertIn("-prove", first_command)
        self.assertIn("prove", second_command)
        self.assertIn("--tool", second_command)


    def test_failed_to_parse_arguments_also_triggers_cli_retry(self) -> None:
        r"""Verify failed to parse arguments also triggers cli retry."""

        backend, obligation = self._fixture(self.runtime, cli_style="auto")
        legacy_error = subprocess.CompletedProcess(
            ["java"],
            1,
            "",
            "Failed to parse arguments: unknown option -prove\nUsage: keymaerax",
        )
        modern_success = subprocess.CompletedProcess(
            ["java"],
            0,
            "PROVED T-ODE-test",
            "",
        )
        with patch(
            "hcsp_typechecker.backend.common.keymaerax.subprocess.run",
            side_effect=(legacy_error, modern_success),
        ) as run:
            result = backend.check(obligation)

        self.assertEqual(result.verdict, Verdict.TRUE)
        self.assertEqual(run.call_count, 2)


    def test_persistent_artifacts_are_isolated_per_obligation(self) -> None:
        r"""Verify persistent artifacts are isolated per obligation."""

        backend, obligation = self._fixture(self.runtime)
        input_paths: list[Path] = []

        def record_archive(command: list[str], **_options: object):
            r"""Record the archive passed to the legacy CLI and return success."""

            input_paths.append(Path(command[command.index("-prove") + 1]))
            return subprocess.CompletedProcess(command, 0, "PROVED", "")

        with patch(
            "hcsp_typechecker.backend.common.keymaerax.subprocess.run",
            side_effect=record_archive,
        ):
            first = backend.check(obligation)
            second = backend.check(obligation)

        self.assertEqual((first.verdict, second.verdict), (Verdict.TRUE, Verdict.TRUE))
        self.assertEqual(len(input_paths), 2)
        self.assertNotEqual(input_paths[0].parent, input_paths[1].parent)
        self.assertTrue(all(path.is_file() for path in input_paths))


    def test_artifact_io_failure_is_returned_as_unknown(self) -> None:
        r"""Verify artifact io failure is returned as unknown."""

        backend, obligation = self._fixture(self.runtime)
        blocked = self.runtime / "artifacts"
        blocked.write_text("not a directory", encoding="utf-8")

        with patch("hcsp_typechecker.backend.common.keymaerax.subprocess.run") as run:
            result = backend.check(obligation)

        self.assertEqual(result.verdict, Verdict.UNKNOWN)
        self.assertIn("work directory", result.detail)
        run.assert_not_called()


    def test_temporary_cleanup_failure_does_not_discard_proof(self) -> None:
        r"""Verify temporary cleanup failure does not discard proof."""

        persistent, obligation = self._fixture(self.runtime)
        backend = KeYmaeraXBackend(
            replace(persistent.config, keep_artifacts=False)
        )

        class FailingCleanup:
            r"""A writable temporary directory whose cleanup simulates Windows access denial."""

            name = str(self.runtime)

            def cleanup(self) -> None:
                r"""Simulate a cleanup failure caused by an externally retained handle."""

                raise PermissionError("directory is busy")

        completed = subprocess.CompletedProcess(
            ["java"],
            0,
            "PROVED T-ODE-test",
            "",
        )
        with patch(
            "hcsp_typechecker.backend.common.keymaerax.tempfile.TemporaryDirectory",
            return_value=FailingCleanup(),
        ), patch(
            "hcsp_typechecker.backend.common.keymaerax.subprocess.run",
            return_value=completed,
        ):
            result = backend.check(obligation)

        self.assertEqual(result.verdict, Verdict.TRUE)


    def test_timeout_must_be_finite_and_positive(self) -> None:
        r"""Verify timeout must be finite and positive."""

        for timeout in (0, -1, True, False, float("inf"), float("-inf"), float("nan")):
            with self.subTest(timeout=timeout):
                with self.assertRaises(ValueError):
                    KeYmaeraXConfig(timeout_seconds=timeout)


    def test_formal_timeout_status_has_specific_unknown_detail(self) -> None:
        r"""Verify formal timeout status has specific unknown detail."""

        backend, obligation = self._fixture(self.runtime)
        completed = subprocess.CompletedProcess(
            ["java"],
            124,
            "TIMEOUT T-ODE-test",
            "",
        )
        with patch(
            "hcsp_typechecker.backend.common.keymaerax.subprocess.run",
            return_value=completed,
        ):
            result = backend.check(obligation)

        self.assertEqual(result.verdict, Verdict.UNKNOWN)
        self.assertIn("proof-search timeout", result.detail)


    def test_construct_type_uses_configured_keymaerax_backend(self) -> None:
        r"""Verify construct type uses configured KeYmaera X backend."""

        backend, _obligation = self._fixture(self.runtime)
        process = Sequence.of(
            ODE(
                [("x", 1)],
                True,
                annotation=ODEAnnotation(safety="x >= 0", delay=1),
            ),
            OutputChannel("done", 0),
        )
        completed = subprocess.CompletedProcess(
            ["java"],
            0,
            "PROVED HCSP obligation",
            "",
        )

        with patch(
            "hcsp_typechecker.backend.common.keymaerax.subprocess.run",
            return_value=completed,
        ) as run:
            report = construct_type(
                gamma={"x": BasicType.REAL, "ode_x": ContinuousType(("x",))},
                theta={"done": ChannelType(BasicType.INT)},
                path_condition="x >= 0",
                configurations=[Configuration({"x": 0}, process)],
                keymaerax_config=backend.config,
            )

        self.assertEqual(report.verdict, Verdict.TRUE)
        self.assertEqual(run.call_count, 2)
        dl_obligations = [
            obligation
            for obligation in report.obligations
            if obligation.kind == "dl"
        ]
        self.assertEqual(
            [item.rule for item in dl_obligations],
            ["T-ODE-safety", "T-ODE-boundary"],
        )
        self.assertTrue(
            all(item.verdict == Verdict.TRUE for item in dl_obligations)
        )


if __name__ == "__main__":
    unittest.main()
