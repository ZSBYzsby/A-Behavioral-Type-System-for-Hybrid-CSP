r"""Run independent KeYmaera X proofs and conservatively interpret official verdicts."""

from __future__ import annotations

from dataclasses import dataclass
import locale
import math
import os
from pathlib import Path
import re
import shutil
import subprocess
import tempfile
from typing import Literal
import uuid

from .dl import DLFormula, UntranslatedDLFormula
from .model import (
    DLCheckResult,
    ProofObligation,
    Verdict,
)


def _environment_flag(name: str, *, default: bool = False) -> bool:
    r"""Read a Boolean environment flag, falling back on unknown values."""

    value = os.environ.get(name)
    if value is None:
        return default
    normalized = value.strip().lower()
    if normalized in {"1", "true", "yes", "on"}:
        return True
    if normalized in {"0", "false", "no", "off"}:
        return False
    return default


def resolve_java_executable(config: "KeYmaeraXConfig") -> str | None:
    r"""Resolve Java from explicit configuration, JAVA_HOME, then PATH."""

    if config.java_path is not None:
        candidate = Path(config.java_path).expanduser()
        return str(candidate) if candidate.is_file() else None

    java_home = os.environ.get("JAVA_HOME")
    if java_home:
        bin_directory = Path(java_home).expanduser() / "bin"
        for executable_name in ("java.exe", "java"):
            candidate = bin_directory / executable_name
            if candidate.is_file():
                return str(candidate)

    return shutil.which("java")


@dataclass(frozen=True, slots=True)
class KeYmaeraXConfig:
    r"""Configure prover paths, timeouts, tactics, CLI compatibility, and retained artifacts."""

    jar_path: str | os.PathLike[str] | None = None
    java_path: str | os.PathLike[str] | None = None
    timeout_seconds: float = 60.0
    tactic: str = "auto"
    arithmetic_tool: str = "Z3"
    cli_style: Literal["auto", "legacy", "modern"] = "auto"
    home_directory: str | os.PathLike[str] | None = None
    keep_artifacts: bool = False
    artifacts_directory: str | os.PathLike[str] | None = None

    def __post_init__(self) -> None:
        r"""Reject invalid prover configuration before proof execution."""

        try:
            timeout = float(self.timeout_seconds)
        except (TypeError, ValueError) as exc:
            raise ValueError(
                "KeYmaera X timeout_seconds must be a finite positive number"
            ) from exc
        if (
            isinstance(self.timeout_seconds, bool)
            or not math.isfinite(timeout)
            or timeout <= 0
        ):
            raise ValueError(
                "KeYmaera X timeout_seconds must be a finite positive number"
            )
        object.__setattr__(self, "timeout_seconds", timeout)
        if self.cli_style not in {"auto", "legacy", "modern"}:
            raise ValueError(
                "KeYmaera X cli_style must be auto, legacy, or modern"
            )
        if not str(self.tactic).strip():
            raise ValueError("KeYmaera X tactic must not be empty")

    @classmethod
    def from_environment(cls) -> "KeYmaeraXConfig":
        r"""Read prover configuration from KEYMAERAX_* variables and local jar candidates."""

        jar = os.environ.get("KEYMAERAX_JAR")
        if jar is None:
            candidates = (
                Path.cwd() / "tools" / "keymaerax.jar",
                Path.cwd() / "keymaerax.jar",
            )
            jar = next(
                (str(path) for path in candidates if path.is_file()),
                None,
            )

        timeout_text = os.environ.get("KEYMAERAX_TIMEOUT", "60")
        try:
            timeout = float(timeout_text)
        except ValueError:
            timeout = 60.0
        if not math.isfinite(timeout) or timeout <= 0:
            timeout = 60.0

        cli_style = os.environ.get("KEYMAERAX_CLI_STYLE", "auto").strip().lower()
        if cli_style not in {"auto", "legacy", "modern"}:
            cli_style = "auto"
        return cls(
            jar_path=jar,
            java_path=os.environ.get("KEYMAERAX_JAVA"),
            home_directory=os.environ.get("KEYMAERAX_HOME"),
            timeout_seconds=timeout,
            tactic=os.environ.get("KEYMAERAX_TACTIC", "auto"),
            arithmetic_tool=os.environ.get(
                "KEYMAERAX_ARITHMETIC_TOOL",
                "Z3",
            ),
            cli_style=cli_style,  # type: ignore[arg-type]
            keep_artifacts=_environment_flag("KEYMAERAX_KEEP_ARTIFACTS"),
            artifacts_directory=os.environ.get("KEYMAERAX_ARTIFACTS"),
        )


class KeYmaeraXBackend:
    r"""Submit one dL obligation to an independent KeYmaera X process."""

    def __init__(self, config: KeYmaeraXConfig | None = None) -> None:
        r"""Store explicit configuration or derive defaults from the environment."""

        self.config = (
            KeYmaeraXConfig.from_environment()
            if config is None
            else config
        )

    def __call__(self, obligation: ProofObligation) -> DLCheckResult:
        r"""Implement the DLChecker callable protocol."""

        return self.check(obligation)

    def check(self, obligation: ProofObligation) -> DLCheckResult:
        r"""Return a three-valued proof verdict with backend evidence."""

        formula = obligation.formula
        if isinstance(formula, UntranslatedDLFormula):
            return DLCheckResult(
                Verdict.UNKNOWN,
                f"dL translation is unavailable: {formula.reason}",
            )
        if not isinstance(formula, DLFormula):
            return DLCheckResult(
                Verdict.UNKNOWN,
                "dL obligation is not a DLFormula; refusing string-based proof input",
            )

        environment_error = self._environment_error()
        if environment_error is not None:
            return DLCheckResult(Verdict.UNKNOWN, environment_error)
        home_error = self._prepare_home()
        if home_error is not None:
            return DLCheckResult(Verdict.UNKNOWN, home_error)

        cleanup: tempfile.TemporaryDirectory[str] | None = None
        try:
            if self.config.keep_artifacts:
                work_directory = self._persistent_directory(obligation)
            else:
                # Ignore Windows cleanup races so retained SQLite handles cannot discard proof
                # results.
                cleanup = tempfile.TemporaryDirectory(
                    prefix="hcsp-keymaerax-",
                    ignore_cleanup_errors=True,
                )
                work_directory = Path(cleanup.name)
        except OSError as exc:
            return DLCheckResult(
                Verdict.UNKNOWN,
                f"cannot create KeYmaera X work directory: {exc}",
            )

        try:
            input_path = work_directory / "obligation.kyx"
            output_path = work_directory / "obligation.kyp"
            try:
                input_path.write_text(
                    formula.to_archive(
                        entry_name=f"{obligation.rule}: {formula.role}",
                        tactic=self.config.tactic,
                    ),
                    encoding="utf-8",
                )
            except OSError as exc:
                return DLCheckResult(
                    Verdict.UNKNOWN,
                    f"cannot write KeYmaera X obligation archive: {exc}",
                )
            styles = (
                ("legacy", "modern")
                if self.config.cli_style == "auto"
                else (self.config.cli_style,)
            )
            last_result: DLCheckResult | None = None
            for index, style in enumerate(styles):
                command = self._command(style, input_path, output_path)
                result = self._run(command)
                last_result = self._interpret(result, style)
                # Retry another CLI style only for explicit argument/usage errors.
                if (
                    index + 1 < len(styles)
                    and self._looks_like_cli_mismatch(result)
                ):
                    continue
                return last_result
            return last_result or DLCheckResult(
                Verdict.UNKNOWN,
                "KeYmaera X did not produce a result",
            )
        finally:
            if cleanup is not None:
                # Temporary cleanup failures must not overwrite proof results or UNKNOWN
                # evidence.
                try:
                    cleanup.cleanup()
                except OSError:
                    pass

    def _environment_error(self) -> str | None:
        r"""Validate jar and Java availability before launching the prover."""

        if self.config.jar_path is None:
            return (
                "KeYmaera X is not configured: set KEYMAERAX_JAR or place "
                "keymaerax.jar in ./tools"
            )
        jar = Path(self.config.jar_path).expanduser()
        if not jar.is_file():
            return f"KeYmaera X jar does not exist: {jar}"
        java = self._java_executable()
        if java is None:
            return (
                "Java was not found: install Java 17+, set KEYMAERAX_JAVA or "
                "JAVA_HOME, or add java to PATH"
            )
        return None

    def _java_executable(self) -> str | None:
        r"""Use the shared cross-platform Java resolution policy."""

        return resolve_java_executable(self.config)

    def _prepare_home(self) -> str | None:
        r"""Prepare the configuration directory required by KeYmaera X 5.x."""

        if self.config.home_directory is None:
            return None
        try:
            home = Path(self.config.home_directory).expanduser()
            (home / ".keymaerax").mkdir(parents=True, exist_ok=True)
        except OSError as exc:
            return f"cannot prepare KeYmaera X home directory: {exc}"
        return None

    def _persistent_directory(self, obligation: ProofObligation) -> Path:
        r"""Allocate a unique directory per retained obligation to prevent overwrites."""

        root = (
            Path(self.config.artifacts_directory)
            if self.config.artifacts_directory is not None
            else Path.cwd() / "keymaerax-artifacts"
        )
        root.mkdir(parents=True, exist_ok=True)
        readable_rule = re.sub(
            r"[^A-Za-z0-9_.-]+",
            "-",
            obligation.rule,
        ).strip("-._") or "obligation"
        target = root / f"{readable_rule}-{uuid.uuid4().hex}"
        target.mkdir(exist_ok=False)
        return target

    def _command(
        self,
        style: str,
        input_path: Path,
        output_path: Path,
    ) -> list[str]:
        r"""Build a shell-free argument list for the selected CLI style."""

        java = self._java_executable()
        assert java is not None
        jar = str(Path(self.config.jar_path).expanduser())
        # Match the official launcher's 20 MB stack and prevent a child JVM from losing
        # user.home.
        jvm_options = ["-Xss20M"]
        if self.config.home_directory is not None:
            jvm_options.append(
                "-Duser.home="
                + str(Path(self.config.home_directory).expanduser())
            )
        if style == "legacy":
            return [
                java,
                *jvm_options,
                "-jar",
                jar,
                "-launch",
                "-tool",
                self.config.arithmetic_tool,
                "-prove",
                str(input_path),
                "-out",
                str(output_path),
            ]
        return [
            java,
            *jvm_options,
            "-jar",
            jar,
            "--launch",
            "--tool",
            self.config.arithmetic_tool,
            "prove",
            str(input_path),
            str(output_path),
        ]

    def _run(self, command: list[str]) -> subprocess.CompletedProcess[str]:
        r"""Run the prover; callers map timeout and operating-system failures to UNKNOWN."""

        try:
            return subprocess.run(
                command,
                capture_output=True,
                text=True,
                # Decode Java output using the platform console encoding; verdict lines remain
                # ASCII.
                encoding=locale.getpreferredencoding(False),
                errors="replace",
                timeout=self.config.timeout_seconds,
                check=False,
                shell=False,
            )
        except subprocess.TimeoutExpired as exc:
            stdout = self._output_text(exc.stdout)
            stderr = self._output_text(exc.stderr)
            return subprocess.CompletedProcess(
                command,
                124,
                stdout,
                f"{stderr}\nHCSP_BACKEND_TIMEOUT".strip(),
            )
        except OSError as exc:
            return subprocess.CompletedProcess(
                command,
                127,
                "",
                f"HCSP_BACKEND_OS_ERROR: {exc}",
            )

    @staticmethod
    def _output_text(value: str | bytes | None) -> str:
        r"""Normalize subprocess timeout output across Python versions."""

        if value is None:
            return ""
        if isinstance(value, bytes):
            return value.decode("utf-8", errors="replace")
        return value

    def _interpret(
        self,
        result: subprocess.CompletedProcess[str],
        style: str,
    ) -> DLCheckResult:
        r"""Interpret official status lines without treating incidental log words as verdicts."""

        combined = "\n".join(
            part for part in (result.stdout, result.stderr) if part
        )
        # A process failure invalidates any status captured before it stopped.
        if "HCSP_BACKEND_TIMEOUT" in combined:
            return DLCheckResult(
                Verdict.UNKNOWN,
                f"KeYmaera X exceeded {self.config.timeout_seconds:g} seconds",
            )
        if "HCSP_BACKEND_OS_ERROR" in combined:
            return DLCheckResult(Verdict.UNKNOWN, combined.strip())

        statuses: set[str] = set()
        for line in combined.splitlines():
            normalized = line.strip().upper()
            match = re.match(
                r"^(PROVED|DISPROVED|UNFINISHED|FAILED|TIMEOUT)(?=$|[\s(:])",
                normalized,
            )
            if match is None:
                continue
            status = match.group(1)
            if re.match(r"^UNFINISHED\s+\(CEX\)(?=$|[\s:])", normalized):
                status = "DISPROVED"
            statuses.add(status)

        if "TIMEOUT" in statuses:
            return DLCheckResult(
                Verdict.UNKNOWN,
                "KeYmaera X reported a proof-search timeout",
            )
        if len(statuses) > 1:
            return DLCheckResult(
                Verdict.UNKNOWN,
                "KeYmaera X returned conflicting proof statuses: "
                + ", ".join(sorted(statuses)),
            )
        if "PROVED" in statuses:
            if result.returncode != 0:
                return DLCheckResult(
                    Verdict.UNKNOWN,
                    "KeYmaera X reported PROVED but exited abnormally "
                    f"(exit {result.returncode}, {style} CLI)",
                )
            return DLCheckResult(
                Verdict.TRUE,
                f"KeYmaera X proved the dL formula ({style} CLI)",
            )
        if "DISPROVED" in statuses:
            return DLCheckResult(
                Verdict.FALSE,
                "KeYmaera X produced a counterexample to validity "
                f"({style} CLI)",
            )
        if "UNFINISHED" in statuses:
            return DLCheckResult(
                Verdict.UNKNOWN,
                "KeYmaera X proof search was unfinished",
            )
        if "FAILED" in statuses:
            return DLCheckResult(
                Verdict.UNKNOWN,
                "KeYmaera X failed while processing the obligation",
            )
        excerpt = self._excerpt(combined)
        return DLCheckResult(
            Verdict.UNKNOWN,
            "KeYmaera X returned no recognized proof status "
            f"(exit {result.returncode}, {style} CLI)"
            + (f": {excerpt}" if excerpt else ""),
        )

    @staticmethod
    def _looks_like_cli_mismatch(
        result: subprocess.CompletedProcess[str],
    ) -> bool:
        r"""Retry only for an explicit CLI mismatch, not a proof failure."""

        combined = f"{result.stdout}\n{result.stderr}".lower()
        # Recognize explicit option/usage failures before interpreting formal proof verdicts.
        has_cli_marker = any(
            marker in combined
            for marker in (
                "unknown option",
                "unknown argument",
                "unrecognized option",
                "failed to parse argument",
                "usage:",
                "error: unknown",
            )
        )
        if has_cli_marker:
            return True
        # Without a CLI mismatch marker, FAILED is a proof result and must not trigger a retry.
        return False

    @staticmethod
    def _excerpt(output: str, limit: int = 600) -> str:
        r"""Limit external log text while retaining the first error context."""

        compact = " ".join(output.split())
        return compact if len(compact) <= limit else compact[:limit] + "..."
