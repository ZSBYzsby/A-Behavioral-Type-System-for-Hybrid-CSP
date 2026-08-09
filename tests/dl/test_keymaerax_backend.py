"""KeYmaera X 后端进程调用、结果映射和失败处理测试。

测试使用真实临时 ``.kyx`` 文件，但 mock 外部进程，因此不要求 CI 安装 Java
或 150MB 的 KeYmaera X jar。项目中的实际集成验证另由 README 所列 smoke
命令执行。

测试内容
--------
1. jar/Java 缺失和翻译失败的保守 unknown 路径。
2. PROVED、CEX、UNFINISHED、FAILED、TIMEOUT 的三值映射。
3. Python 外层超时和子进程安全调用参数。
4. legacy/modern 两代 CLI 的受控自动回退及解析错误识别。
5. 持久产物的逐义务隔离和配置边界。
6. ``check_hcsp`` 到内建后端的完整 safety/boundary 调用链。
7. 公开环境变量到可移植后端配置的完整映射。
8. Java 可执行文件通过标准 ``JAVA_HOME`` 自动发现。

论文对应
--------
论文 Section 4.3 把 dL 公式作为类型规则前提；本文件验证这些前提交给
KeYmaera X 后如何保守地返回 true/false/unknown，不改变规则本身的语义。
"""

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
    check_hcsp,
)


class KeYmaeraXBackendTests(unittest.TestCase):
    """覆盖后端的所有三值出口和两代 CLI。"""

    def setUp(self) -> None:
        """在测试目录下建立会自动回收的独立后端运行目录。"""

        self.runtime = (
            Path(__file__).parent
            / "_runtime"
            / self._testMethodName
        )
        self.runtime.mkdir(parents=True, exist_ok=True)

    def tearDown(self) -> None:
        """删除 mock Java、jar 和 archive，避免测试产物进入项目文件树。"""

        if self.runtime.exists():
            shutil.rmtree(self.runtime)

    @classmethod
    def tearDownClass(cls) -> None:
        """全部后端测试完成后删除已经为空的共享运行目录。"""

        runtime_root = Path(__file__).parent / "_runtime"
        if runtime_root.exists():
            runtime_root.rmdir()

    def _fixture(
        self,
        directory: str | Path,
        *,
        cli_style: str = "legacy",
    ) -> tuple[KeYmaeraXBackend, ProofObligation]:
        """在临时目录建立存在但不执行的 Java/jar 文件和简单义务。"""

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

    # 测试输入：跨平台 KEYMAERAX_* 环境变量，包括产物目录、CLI 风格和策略。
    # 预期行为：from_environment 把文本规范化成完整 KeYmaeraXConfig。
    # 检查内容：路径、数值、布尔值及高级后端选项均不依赖开发者本机常量。
    # 论文对应：只改变 dL premise 的外部执行配置，不改变 Table 2 公式本身。
    def test_environment_variables_build_portable_configuration(self) -> None:
        """公开环境变量应覆盖完整的可移植后端配置。"""

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
            "hcsp_typechecker.typechecking.keymaerax.os.environ",
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

    # 测试输入：未设置 KEYMAERAX_JAVA，但 JAVA_HOME/bin 中存在 Java 占位文件。
    # 预期行为：后端自动选中 JAVA_HOME 下的可执行文件，不要求用户修改源码。
    # 检查内容：同时屏蔽 PATH 回退，确保结果确实来自标准 JAVA_HOME 布局。
    # 论文对应：只决定 dL premise 的外部证明器入口，不改变 Table 2 的公式。
    def test_java_home_is_used_when_explicit_java_is_absent(self) -> None:
        """标准 JAVA_HOME 应作为显式路径之后、PATH 之前的可移植回退。"""

        java = self.runtime / "jdk" / "bin" / "java.exe"
        java.parent.mkdir(parents=True)
        java.write_text("test java placeholder", encoding="utf-8")
        backend = KeYmaeraXBackend(KeYmaeraXConfig())

        with patch.dict(
            "hcsp_typechecker.typechecking.keymaerax.os.environ",
            {"JAVA_HOME": str(self.runtime / "jdk")},
            clear=True,
        ), patch(
            "hcsp_typechecker.typechecking.keymaerax.shutil.which",
            return_value=None,
        ):
            resolved = backend._java_executable()

        self.assertEqual(resolved, str(java))

    # 测试输入：jar_path/java_path 均未配置的后端和一条简单 dL 义务。
    # 预期行为：返回 unknown，并给出 KEYMAERAX_JAR 配置提示。
    # 检查内容：确认环境缺失既不抛异常，也不被误判为公式 false。
    # 论文对应：未能验证 dL 前提时类型规则只能采用保守未知结果。
    def test_missing_jar_is_unknown_with_configuration_help(self) -> None:
        """环境缺失不能抛异常或误报 false。"""

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

    # 测试输入：携带 unsupported function 原因的 UntranslatedDLFormula。
    # 预期行为：直接返回 unknown，subprocess.run 从未被调用。
    # 检查内容：防止把翻译错误文本误写成 .kyx 后交给证明器。
    # 论文对应：T-ODE 前提没有可靠 dL 编码时不得猜测证明结果。
    def test_untranslated_formula_never_starts_a_process(self) -> None:
        """翻译失败应直接 unknown，不得把原因文本当作 .kyx 输入。"""

        backend = KeYmaeraXBackend()
        obligation = ProofObligation(
            "test",
            "test",
            UntranslatedDLFormula("safety", "unsupported function"),
            kind="dl",
        )
        with patch("hcsp_typechecker.typechecking.keymaerax.subprocess.run") as run:
            result = backend.check(obligation)

        self.assertEqual(result.verdict, Verdict.UNKNOWN)
        self.assertIn("unsupported function", result.detail)
        run.assert_not_called()

    # 测试输入：mock 子进程返回 PROVED 的合法恒等 dL 义务。
    # 预期行为：映射为 true，只调用一次且使用 shell=False 参数数组。
    # 检查内容：在 mock 内读取真实临时 archive 并核对 Problem/Tactic。
    # 论文对应：KeYmaera X 闭合类型规则的 dL 前提后该前提为真。
    def test_proved_status_maps_to_true_and_writes_valid_archive(self) -> None:
        """PROVED 状态应为 true，调用必须使用参数数组且禁用 shell。"""

        backend, obligation = self._fixture(self.runtime)
        observed_archive: list[str] = []

        def successful_run(command: list[str], **options: object):
            """在 mock 进程返回前读取后端刚写出的 archive。"""

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
            "hcsp_typechecker.typechecking.keymaerax.subprocess.run",
            side_effect=successful_run,
        ) as run:
            result = backend.check(obligation)

        self.assertEqual(result.verdict, Verdict.TRUE)
        self.assertIn("proved", result.detail)
        self.assertEqual(run.call_count, 1)
        self.assertIn("Problem\n  (kxv0=kxv0)\nEnd.", observed_archive[0])
        self.assertIn('Tactic "HCSP Proof"', observed_archive[0])

    # 测试输入：官方输出 ``UNFINISHED (CEX)`` 和非零退出码。
    # 预期行为：后端映射为 false，detail 明确包含 counterexample。
    # 检查内容：区分“存在反例”和普通未完成证明。
    # 论文对应：dL 前提被反例否定时相应 HCSP 类型推导失败。
    def test_counterexample_status_maps_to_false(self) -> None:
        """官方 ``UNFINISHED (CEX)`` 状态提供反例，应映射为公式无效。"""

        backend, obligation = self._fixture(self.runtime)
        completed = subprocess.CompletedProcess(
            ["java"],
            255,
            "UNFINISHED (CEX) T-ODE-test",
            "",
        )
        with patch(
            "hcsp_typechecker.typechecking.keymaerax.subprocess.run",
            return_value=completed,
        ):
            result = backend.check(obligation)

        self.assertEqual(result.verdict, Verdict.FALSE)
        self.assertIn("counterexample", result.detail)

    # 测试输入：UNFINISHED 与 FAILED 两种无反例状态输出。
    # 预期行为：两者均保持 unknown，而不是映射成 false。
    # 检查内容：用子测试覆盖搜索未闭合和工具失败两个出口。
    # 论文对应：不能证明不等于证明公式无效，类型结果必须保持保守。
    def test_unfinished_and_failed_statuses_stay_unknown(self) -> None:
        """未完成证明和工具故障都不等价于公式为假。"""

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
                    "hcsp_typechecker.typechecking.keymaerax.subprocess.run",
                    return_value=completed,
                ):
                    result = backend.check(obligation)
                self.assertEqual(result.verdict, Verdict.UNKNOWN)

    # 测试输入：subprocess.run 抛出 timeout=3 秒的 TimeoutExpired。
    # 预期行为：结果 unknown，detail 保留 ``3 seconds``。
    # 检查内容：验证外层超时被捕获并转换为可审计诊断。
    # 论文对应：证明资源耗尽不构成 dL 公式真假结论。
    def test_python_timeout_stays_unknown(self) -> None:
        """外层进程超时必须终止证明并在报告中保留秒数。"""

        backend, obligation = self._fixture(self.runtime)
        with patch(
            "hcsp_typechecker.typechecking.keymaerax.subprocess.run",
            side_effect=subprocess.TimeoutExpired(["java"], 3),
        ):
            result = backend.check(obligation)

        self.assertEqual(result.verdict, Verdict.UNKNOWN)
        self.assertIn("3 seconds", result.detail)

    # 测试输入：legacy 调用返回 usage 错误，modern 调用随后返回 PROVED。
    # 预期行为：auto 模式恰调用两次并最终返回 true。
    # 检查内容：核对首个 -prove 参数和第二个 prove/--tool 参数。
    # 论文对应：工具版本兼容只影响 dL 前提的执行，不改变证明公式。
    def test_auto_cli_retries_modern_style_only_after_usage_error(self) -> None:
        """auto 模式应兼容 5.1.x 旧参数和当前源码的新子命令。"""

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
            "hcsp_typechecker.typechecking.keymaerax.subprocess.run",
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

    # 测试输入：旧 CLI 输出以 Failed 开头的参数解析错误，modern 随后 PROVED。
    # 预期行为：Failed 英文前缀不被误当成正式 FAILED 证明状态，仍执行第二次。
    # 检查内容：核对最终 true 和恰好两次子进程调用。
    # 论文对应：证明器适配错误不能把本可验证的 dL premise 永久降为 unknown。
    def test_failed_to_parse_arguments_also_triggers_cli_retry(self) -> None:
        """参数解析器的 Failed 行必须优先按 CLI 不兼容处理。"""

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
            "hcsp_typechecker.typechecking.keymaerax.subprocess.run",
            side_effect=(legacy_error, modern_success),
        ) as run:
            result = backend.check(obligation)

        self.assertEqual(result.verdict, Verdict.TRUE)
        self.assertEqual(run.call_count, 2)

    # 测试输入：同一 keep_artifacts 后端连续验证两次相同义务。
    # 预期行为：两次 archive 位于不同的唯一子目录，旧文件不会被覆盖。
    # 检查内容：记录 -prove 输入路径并确认路径不同、文件均保留且父目录存在。
    # 论文对应：每条顺序判定的 dL premise 都应保有可独立审计的证明输入。
    def test_persistent_artifacts_are_isolated_per_obligation(self) -> None:
        """持久证明产物必须支持重复调用和并发调用而不共享固定文件名。"""

        backend, obligation = self._fixture(self.runtime)
        input_paths: list[Path] = []

        def record_archive(command: list[str], **_options: object):
            """记录每次旧式 CLI 所读取的 archive 路径并返回成功状态。"""

            input_paths.append(Path(command[command.index("-prove") + 1]))
            return subprocess.CompletedProcess(command, 0, "PROVED", "")

        with patch(
            "hcsp_typechecker.typechecking.keymaerax.subprocess.run",
            side_effect=record_archive,
        ):
            first = backend.check(obligation)
            second = backend.check(obligation)

        self.assertEqual((first.verdict, second.verdict), (Verdict.TRUE, Verdict.TRUE))
        self.assertEqual(len(input_paths), 2)
        self.assertNotEqual(input_paths[0].parent, input_paths[1].parent)
        self.assertTrue(all(path.is_file() for path in input_paths))

    # 测试输入：artifacts_directory 路径已被一个普通文件占用。
    # 预期行为：后端返回 unknown 和目录错误说明，且不启动 Java 进程。
    # 检查内容：验证文件系统错误不会越过 DLChecker 接口直接抛给 TypeChecker。
    # 论文对应：工具环境故障不构成 dL premise 的真假结论。
    def test_artifact_io_failure_is_returned_as_unknown(self) -> None:
        """持久目录创建失败必须成为保守结果而不是未捕获异常。"""

        backend, obligation = self._fixture(self.runtime)
        blocked = self.runtime / "artifacts"
        blocked.write_text("not a directory", encoding="utf-8")

        with patch("hcsp_typechecker.typechecking.keymaerax.subprocess.run") as run:
            result = backend.check(obligation)

        self.assertEqual(result.verdict, Verdict.UNKNOWN)
        self.assertIn("work directory", result.detail)
        run.assert_not_called()

    # 测试输入：非持久模式已得到 PROVED，但 TemporaryDirectory.cleanup 抛 OSError。
    # 预期行为：清理竞态不覆盖证明结果，最终仍返回 true。
    # 检查内容：用可控临时目录替身隔离验证 finally 清理分支。
    # 论文对应：证明后的实现清理故障不能改变已判定 dL premise 的真值。
    def test_temporary_cleanup_failure_does_not_discard_proof(self) -> None:
        """Windows 临时句柄竞态不得从后端接口泄漏异常。"""

        persistent, obligation = self._fixture(self.runtime)
        backend = KeYmaeraXBackend(
            replace(persistent.config, keep_artifacts=False)
        )

        class FailingCleanup:
            """提供可写工作目录，并在清理时模拟 Windows 拒绝访问。"""

            name = str(self.runtime)

            def cleanup(self) -> None:
                """模拟临时目录被外部句柄短暂占用。"""

                raise PermissionError("directory is busy")

        completed = subprocess.CompletedProcess(
            ["java"],
            0,
            "PROVED T-ODE-test",
            "",
        )
        with patch(
            "hcsp_typechecker.typechecking.keymaerax.tempfile.TemporaryDirectory",
            return_value=FailingCleanup(),
        ), patch(
            "hcsp_typechecker.typechecking.keymaerax.subprocess.run",
            return_value=completed,
        ):
            result = backend.check(obligation)

        self.assertEqual(result.verdict, Verdict.TRUE)

    # 测试输入：0、正负无穷和 NaN 四种无效 timeout_seconds。
    # 预期行为：配置构造时统一抛 ValueError，不把异常值传给 subprocess。
    # 检查内容：逐一覆盖正数性和有限性边界。
    # 论文对应：这是外部证明资源配置的实现安全边界，不改变 dL 公式语义。
    def test_timeout_must_be_finite_and_positive(self) -> None:
        """NaN/无穷不能绕过仅使用 ``<= 0`` 的旧校验。"""

        for timeout in (0, float("inf"), float("-inf"), float("nan")):
            with self.subTest(timeout=timeout):
                with self.assertRaises(ValueError):
                    KeYmaeraXConfig(timeout_seconds=timeout)

    # 测试输入：KeYmaera X 正式状态行 ``TIMEOUT``。
    # 预期行为：结果为 unknown，detail 明确说明 proof-search timeout。
    # 检查内容：区分工具正式超时状态和“没有识别到状态”的笼统错误。
    # 论文对应：未闭合 dL premise 不能被当作反例或成功证明。
    def test_formal_timeout_status_has_specific_unknown_detail(self) -> None:
        """正式 TIMEOUT 状态应映射到可读的保守 unknown。"""

        backend, obligation = self._fixture(self.runtime)
        completed = subprocess.CompletedProcess(
            ["java"],
            124,
            "TIMEOUT T-ODE-test",
            "",
        )
        with patch(
            "hcsp_typechecker.typechecking.keymaerax.subprocess.run",
            return_value=completed,
        ):
            result = backend.check(obligation)

        self.assertEqual(result.verdict, Verdict.UNKNOWN)
        self.assertIn("proof-search timeout", result.detail)

    # 测试输入：带有限 delay/safety 的 ODE#done!0 和显式后端配置。
    # 预期行为：内部检查入口返回 true，并调用后端两次。
    # 检查内容：核对送出的 dL 义务依次是 safety 与 boundary 且均通过。
    # 论文对应：Section 4.3 ODE 规则从进程推导到外部 dL 证明的完整链路。
    def test_check_hcsp_uses_configured_keymaerax_backend(self) -> None:
        """内部检查入口应把 ODE safety/boundary 义务一路交给内建后端。"""

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
            "hcsp_typechecker.typechecking.keymaerax.subprocess.run",
            return_value=completed,
        ) as run:
            report = check_hcsp(
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
