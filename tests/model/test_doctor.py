"""公开安装环境自检入口的跨平台行为测试。

测试内容
--------
验证核心 Python/Z3 与可选 Java/KeYmaera X 被分层报告，并验证完整部署可以把
外部证明器设为必需能力。

论文对应
--------
环境自检不改变 Section 4.3/Table 2 公式；它只说明 dL premise 当前能否交给
可信后端，缺少可选后端时仍保持论文判断所需的保守 ``unknown``。
"""

from pathlib import Path
import shutil
import unittest
from unittest.mock import patch

from hcsp_typechecker.tooling.doctor import collect_environment, format_environment
from hcsp_typechecker.backend.common.keymaerax import KeYmaeraXConfig


class EnvironmentDoctorTests(unittest.TestCase):
    """检查核心模式和完整 KeYmaera X 模式的环境能力边界。"""

    def setUp(self) -> None:
        """在工作区测试目录下建立可写、可回收的运行目录。"""

        self.runtime = (
            Path(__file__).parent
            / "_runtime"
            / self._testMethodName
        )
        self.runtime.mkdir(parents=True, exist_ok=True)

    def tearDown(self) -> None:
        """删除环境自检生成的占位文件，避免进入发布内容。"""

        runtime_root = Path(__file__).parent / "_runtime"
        if self.runtime.exists():
            shutil.rmtree(self.runtime)
        if runtime_root.exists() and not any(runtime_root.iterdir()):
            runtime_root.rmdir()

    # 测试输入：存在的临时 Java/jar 路径和 require_keymaerax=True。
    # 预期行为：Python、Z3、Java、jar 四项均报告可用，完整模式 ready=yes。
    # 检查内容：结构化检查结果及面向用户的汇总文本。
    # 论文对应：可用证明器允许处理 ODE 规则生成的 dL premise。
    def test_explicit_full_environment_is_reported_ready(self) -> None:
        """存在显式 Java 和 jar 时，自检应确认完整 ODE 后端可用。"""

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
