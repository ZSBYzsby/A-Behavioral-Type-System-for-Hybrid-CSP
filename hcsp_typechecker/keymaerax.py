"""KeYmaera X 命令行后端。

类型检查器只把 :class:`~hcsp_typechecker.dl.DLFormula` 交给本模块。后端将
公式写入临时 ``.kyx`` archive，以独立进程运行官方 ``keymaerax.jar``，再把
命令行状态映射为项目的三值 :class:`~hcsp_typechecker.model.Verdict`：

* ``PROVED`` -> ``TRUE``；
* ``DISPROVED`` 或带可信反例的 ``UNFINISHED (CEX)`` -> ``FALSE``；
* 超时、解析失败、证明未完成、环境缺失 -> ``UNKNOWN``。

这里判断的是公式有效性/可证明性，不是寻找一个满足赋值。后者不足以验证论文
Table 2 中形如 ``pre -> [ODE]post`` 的全称安全性质。

KeYmaera X 后端只在类型规则全部展开、具体 dL 义务进入证明队列后调用。它既不
选择离散赋值的 ``phi'``，也不把多个 Pool 项联立成谓词综合问题；每次调用都只
独立判定一条已经确定的 ``ProofObligation``。
"""

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
from .model import DLCheckResult, ProofObligation, Verdict


# 功能：解析命令行工具常见的环境变量布尔写法。
# 配置关系：非法或缺失文本采用调用方给出的默认值，避免可选的证明后端
#           因一项展示/产物设置阻止核心类型检查器启动。
def _environment_flag(name: str, *, default: bool = False) -> bool:
    """读取一个环境变量布尔值，并对未知文本采用保守默认值。"""

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
    """Resolve Java from explicit config, ``JAVA_HOME``, or ``PATH``.

    An explicitly configured but invalid ``KEYMAERAX_JAVA`` path is treated as
    a configuration error instead of being silently hidden by another Java
    installation.  ``JAVA_HOME`` is only a fallback when no explicit path was
    supplied; an invalid ``JAVA_HOME`` still allows the conventional ``PATH``
    lookup.
    """

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


@dataclass(frozen=True)
class KeYmaeraXConfig:
    """KeYmaera X 本地进程的可复现配置。

    ``cli_style="auto"`` 先使用 5.1.x 发布版的旧式参数；若输出表明 CLI 参数
    不被识别，再尝试当前源码中的子命令形式。Python 的 ``timeout_seconds``
    是最终保护，即使某个 KeYmaera X 版本不认识内部超时参数也能终止进程。
    """

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
        """尽早拒绝无效配置，避免在证明中途出现含糊错误。"""

        try:
            timeout = float(self.timeout_seconds)
        except (TypeError, ValueError) as exc:
            raise ValueError(
                "KeYmaera X timeout_seconds must be a finite positive number"
            ) from exc
        if not math.isfinite(timeout) or timeout <= 0:
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
        """从环境变量和常见项目路径建立默认配置。

        支持：

        * ``KEYMAERAX_JAR``：官方 jar 的路径；
        * ``KEYMAERAX_JAVA``：Java 可执行文件路径；
        * ``KEYMAERAX_HOME``：KeYmaera X 可写配置根目录；
        * ``KEYMAERAX_TIMEOUT``：秒数。
        * ``KEYMAERAX_KEEP_ARTIFACTS``：是否保留生成的 ``.kyx/.kyp``；
        * ``KEYMAERAX_ARTIFACTS``：保留证明文件时使用的输出目录；
        * ``KEYMAERAX_CLI_STYLE``：``auto``、``legacy`` 或 ``modern``；
        * ``KEYMAERAX_TACTIC``：证明策略名称；
        * ``KEYMAERAX_ARITHMETIC_TOOL``：算术后端名称。

        未找到 jar/Java 时仍返回配置对象，真正调用时给出 ``UNKNOWN`` 及明确
        原因，因此仅含一阶逻辑的项目不会被环境探测打断。
        """

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
    """把一条 dL 证明义务交给独立 KeYmaera X 进程。"""

    def __init__(self, config: KeYmaeraXConfig | None = None):
        """保存显式配置，或从当前环境建立延迟检查的默认配置。"""

        self.config = (
            KeYmaeraXConfig.from_environment()
            if config is None
            else config
        )

    def __call__(self, obligation: ProofObligation) -> DLCheckResult:
        """实现 ``DLChecker`` callable 接口。"""

        return self.check(obligation)

    def check(self, obligation: ProofObligation) -> DLCheckResult:
        """验证一条已经形式化的 dL 义务并返回带证据说明的三值结果。"""

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
                # KeYmaera X/SQLite 在 Windows 上偶尔会短暂保留文件句柄。证明
                # 结果不能因临时目录清理竞态而丢失，所以忽略这种清理错误。
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
                # 自动模式只在明确的参数/usage 错误上尝试另一种 CLI。
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
                # Windows 上 Java/SQLite、杀毒软件或受限执行环境可能短暂保留
                # 临时目录句柄。清理失败不能覆盖已经得到的证明结果或 UNKNOWN
                # 说明；目录之后仍可由操作系统的临时文件维护回收。
                try:
                    cleanup.cleanup()
                except OSError:
                    pass

    def _environment_error(self) -> str | None:
        """检查 jar 和 Java；不启动不完整的外部命令。"""

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
        """Resolve Java using the public cross-platform configuration policy."""

        return resolve_java_executable(self.config)

    def _prepare_home(self) -> str | None:
        """确保显式 KeYmaera X home 中存在其 5.x 所需配置目录。

        未显式配置时沿用 Java 的正常 ``user.home``。显式目录主要用于 CI、
        沙箱和不希望证明器写入用户主目录的部署。
        """

        if self.config.home_directory is None:
            return None
        try:
            home = Path(self.config.home_directory).expanduser()
            (home / ".keymaerax").mkdir(parents=True, exist_ok=True)
        except OSError as exc:
            return f"cannot prepare KeYmaera X home directory: {exc}"
        return None

    def _persistent_directory(self, obligation: ProofObligation) -> Path:
        """为每条需保留的义务建立唯一目录，避免覆盖和并发竞态。"""

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
        """按选定版本构造无 shell 的参数数组，避免路径转义和注入问题。"""

        java = self._java_executable()
        assert java is not None  # 已由 ``_environment_error`` 检查。
        jar = str(Path(self.config.jar_path).expanduser())
        # 官方启动器在证明模式下会把 Java 线程栈提高到 20 MB。这里显式提供
        # 同一设置，并用 ``-launch``/``--launch`` 阻止 jar 再次拉起子 JVM；
        # 如此既不会在深证明中因默认栈过小失败，也不会丢失自定义 user.home。
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
        """运行证明器；超时和操作系统错误由调用方映射为 ``UNKNOWN``。"""

        try:
            return subprocess.run(
                command,
                capture_output=True,
                text=True,
                # Java 默认使用平台控制台编码；采用相同编码可让 Windows 中文
                # 错误信息保持可读，ASCII 状态行在所有支持平台上均不受影响。
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
        """规范化 ``TimeoutExpired`` 在不同 Python 版本中的输出类型。"""

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
        """只根据官方状态行判定，不把普通日志中的单词误当作结论。"""

        combined = "\n".join(
            part for part in (result.stdout, result.stderr) if part
        )
        statuses = [
            line.strip().upper()
            for line in combined.splitlines()
            if line.strip().upper().startswith(
                (
                    "PROVED",
                    "DISPROVED",
                    "UNFINISHED",
                    "FAILED",
                    "TIMEOUT",
                )
            )
        ]
        if any(line.startswith("PROVED") for line in statuses):
            return DLCheckResult(
                Verdict.TRUE,
                f"KeYmaera X proved the dL formula ({style} CLI)",
            )
        if any(
            line.startswith("DISPROVED")
            or line.startswith("UNFINISHED (CEX)")
            for line in statuses
        ):
            return DLCheckResult(
                Verdict.FALSE,
                "KeYmaera X produced a counterexample to validity "
                f"({style} CLI)",
            )
        if "HCSP_BACKEND_TIMEOUT" in combined:
            return DLCheckResult(
                Verdict.UNKNOWN,
                f"KeYmaera X exceeded {self.config.timeout_seconds:g} seconds",
            )
        if any(line.startswith("TIMEOUT") for line in statuses):
            return DLCheckResult(
                Verdict.UNKNOWN,
                "KeYmaera X reported a proof-search timeout",
            )
        if "HCSP_BACKEND_OS_ERROR" in combined:
            return DLCheckResult(Verdict.UNKNOWN, combined.strip())
        if any(line.startswith("UNFINISHED") for line in statuses):
            return DLCheckResult(
                Verdict.UNKNOWN,
                "KeYmaera X proof search was unfinished",
            )
        if any(line.startswith("FAILED") for line in statuses):
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
        """识别旧式/新式参数不兼容，而不是对真正的证明失败重复运行。"""

        combined = f"{result.stdout}\n{result.stderr}".lower()
        # 参数解析器本身常以 ``Failed to parse arguments`` 开头；必须先识别
        # 明确的 option/usage 标记，不能把普通英文 Failed 误当正式证明状态。
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
        # 没有明确 CLI 标记时，任何正式状态（含 FAILED）都属于本次证明结果，
        # 不应以另一套参数重复运行同一个义务。
        return False

    @staticmethod
    def _excerpt(output: str, limit: int = 600) -> str:
        """限制报告中外部进程文本的长度，同时保留首个错误上下文。"""

        compact = " ".join(output.split())
        return compact if len(compact) <= limit else compact[:limit] + "..."
