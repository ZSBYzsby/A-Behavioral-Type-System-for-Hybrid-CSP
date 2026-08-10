"""HCSP 源码项目的跨平台运行环境诊断。

核心 TypeConstructor/TypeChecker 只需要 Python 和 ``z3-solver``；只有证明生成的 dL 义务时才需要
Java 和 KeYmaera X。本模块分别报告这两层能力，避免把可选证明器缺失误认为
Python 项目本身无法运行。

在仓库根目录运行::

    python -m hcsp_typechecker.tooling.doctor

若部署必须自动证明 ODE 目标，可增加 ``--require-keymaerax``。
"""

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
    """一项具名环境能力、可用状态和用户可读证据。"""

    name: str
    available: bool
    detail: str
    required: bool = True


def _java_executable(config: KeYmaeraXConfig) -> str | None:
    """复用真实证明后端的 Java 定位策略。"""

    return resolve_java_executable(config)


def _java_version(executable: str) -> str:
    """返回 Java 版本输出首行，并用超时防止环境诊断挂起。"""

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
    """检查核心 Python/Z3 与可选 Java/KeYmaera X 能力。"""

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
    """格式化诊断条目，并说明核心类型构造与完整 dL 证明能力的边界。"""

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
    """运行诊断；仅在必需能力缺失时返回非零退出码。"""

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
