r"""Diagnose core Python/Z3 and optional Java/KeYmaera X capabilities."""

from __future__ import annotations

import argparse
from dataclasses import dataclass
from pathlib import Path
import platform
import subprocess
import sys
from typing import Sequence

from ..backend.common.keymaerax import KeYmaeraXConfig, resolve_java_executable


@dataclass(frozen=True)
class EnvironmentCheck:
    r"""A named environment capability with availability and evidence."""

    name: str
    available: bool
    detail: str
    required: bool = True


def _java_executable(config: KeYmaeraXConfig) -> str | None:
    r"""Reuse the proof backend's Java resolution policy."""

    return resolve_java_executable(config)


def _java_version(executable: str) -> str:
    r"""Read Java's first version line with a timeout."""

    try:
        completed = subprocess.run(
            [executable, "-version"],
            capture_output=True,
            text=True,
            timeout=10,
            check=False,
            shell=False,
        )
    except (OSError, subprocess.TimeoutExpired) as exc:
        return f"version check failed: {exc}"
    output = (completed.stderr or completed.stdout).strip().splitlines()
    return output[0] if output else f"exit code {completed.returncode}"


def collect_environment(
    *,
    require_keymaerax: bool = False,
    config: KeYmaeraXConfig | None = None,
) -> tuple[EnvironmentCheck, ...]:
    r"""Inspect required Python/Z3 and optional Java/KeYmaera X."""

    active_config = config or KeYmaeraXConfig.from_environment()
    python_ok = sys.version_info >= (3, 10)

    try:
        import z3  # Imported lazily so a missing dependency gets a clear row.

        z3_detail = z3.get_version_string()
        z3_ok = True
    except (ImportError, AttributeError) as exc:
        z3_detail = f"unavailable: {exc}"
        z3_ok = False

    jar_path = (
        None
        if active_config.jar_path is None
        else Path(active_config.jar_path).expanduser()
    )
    jar_ok = jar_path is not None and jar_path.is_file()
    java = _java_executable(active_config)
    java_ok = java is not None

    return (
        EnvironmentCheck(
            "Python",
            python_ok,
            f"{platform.python_version()} at {sys.executable}",
        ),
        EnvironmentCheck("z3-solver", z3_ok, z3_detail),
        EnvironmentCheck(
            "Java",
            java_ok,
            "not found; set KEYMAERAX_JAVA/JAVA_HOME or add java to PATH"
            if java is None
            else f"{_java_version(java)} at {java}",
            required=require_keymaerax,
        ),
        EnvironmentCheck(
            "KeYmaera X",
            jar_ok,
            "not found; set KEYMAERAX_JAR"
            if jar_path is None
            else str(jar_path),
            required=require_keymaerax,
        ),
    )


def format_environment(checks: Sequence[EnvironmentCheck]) -> str:
    r"""Display core-engine and external dL prover readiness separately."""

    lines = ["HCSP behavioral type environment"]
    for check in checks:
        status = "OK" if check.available else ("ERROR" if check.required else "OPTIONAL")
        lines.append(f"[{status:8}] {check.name}: {check.detail}")
    core_ready = all(
        check.available
        for check in checks
        if check.name in {"Python", "z3-solver"}
    )
    full_ready = all(check.available for check in checks)
    lines.append("")
    lines.append(f"Core type engine ready : {'yes' if core_ready else 'no'}")
    lines.append(f"KeYmaera X ready   : {'yes' if full_ready else 'no'}")
    if core_ready and not full_ready:
        lines.append(
            "Discrete checks remain available; unproved dL obligations return unknown."
        )
    return "\n".join(lines)


def main(argv: Sequence[str] | None = None) -> int:
    r"""Return nonzero only when a required capability is unavailable."""

    parser = argparse.ArgumentParser(
        description="Inspect HCSP type engines and optional KeYmaera X setup.",
    )
    parser.add_argument(
        "--require-keymaerax",
        action="store_true",
        help="treat Java and the KeYmaera X jar as required",
    )
    arguments = parser.parse_args(argv)
    checks = collect_environment(
        require_keymaerax=arguments.require_keymaerax,
    )
    print(format_environment(checks))
    return 0 if all(check.available or not check.required for check in checks) else 1


if __name__ == "__main__":
    raise SystemExit(main())
