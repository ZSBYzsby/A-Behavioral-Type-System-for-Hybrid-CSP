"""公开接口文档与当前代码的一致性回归测试。

测试内容
--------
1. 根包 ``__all__`` 中的稳定名称必须同时出现在 README 和完整功能参考中。
2. 公开文档不得重新出现已实现 TypeChecker 仍“尚未实现”等陈旧说明。
3. README 与 ``document`` 目录中的本地 Markdown 链接必须指向现存文件。

论文对应
--------
本文件不新增论文规则；它保证 TypeConstructor、TypeChecker、Table 3 图接口及其
语法/输出文档始终描述当前实现，而不会因项目结构迭代重新暴露过时接口。
"""

from __future__ import annotations

import re
import unittest
from pathlib import Path

import hcsp_typechecker


PROJECT_ROOT = Path(__file__).resolve().parents[2]
README = PROJECT_ROOT / "README.md"
DOCUMENT_ROOT = PROJECT_ROOT / "document"
FUNCTION_REFERENCE = DOCUMENT_ROOT / "PROJECT_FUNCTION_REFERENCE.md"


class PublicDocumentationTests(unittest.TestCase):
    """锁定用户文档的公开名称、当前状态和本地链接。"""

    # 测试输入：根包 __all__、README 和完整功能参考。
    # 预期行为：每个稳定公开名称均由两份入口文档说明，且旧状态措辞不存在。
    # 检查内容：比较公开白名单并扫描已经确认废弃的历史描述。
    # 论文对应：保证 Constructor/Checker 的 Table 2 功能状态不被旧文档误报。
    def test_public_names_and_feature_status_match_the_code(self) -> None:
        """确认公开白名单均有文档，并拒绝已知陈旧状态说明。"""

        readme_text = README.read_text(encoding="utf-8")
        reference_text = FUNCTION_REFERENCE.read_text(encoding="utf-8")
        for public_name in hcsp_typechecker.__all__:
            self.assertIn(public_name, readme_text)
            self.assertIn(public_name, reference_text)

        combined = "\n".join(
            path.read_text(encoding="utf-8")
            for path in (README, *sorted(DOCUMENT_ROOT.glob("*.md")))
        )
        stale_patterns = (
            r"TypeChecker.{0,30}尚未实现",
            r"未来的\s*\*\*TypeChecker\*\*",
            r"当前公共接口也不接受用户 Type",
            r"tests/` 当前共有 \d+ 个自动化测试",
        )
        for pattern in stale_patterns:
            self.assertIsNone(re.search(pattern, combined, flags=re.DOTALL))

    # 测试输入：README 和 document 下所有 Markdown 链接目标。
    # 预期行为：忽略网页与纯锚点后，每个本地目标都能从所在文档解析到现存文件。
    # 检查内容：提取 Markdown 链接、去除锚点并验证相对路径。
    # 论文对应：保证语法、构造规则和检查规则之间的审计导航持续有效。
    def test_local_markdown_links_resolve(self) -> None:
        """确认公开文档中的所有本地 Markdown 链接没有失效。"""

        missing: list[str] = []
        paths = (README, *sorted(DOCUMENT_ROOT.glob("*.md")))
        for document_path in paths:
            text = document_path.read_text(encoding="utf-8")
            for raw_target in re.findall(r"\[[^\]]+\]\(([^)]+)\)", text):
                target = raw_target.strip().strip("<>")
                if not target or target.startswith(("#", "http://", "https://")):
                    continue
                relative_target = target.split("#", 1)[0]
                # 数学文档中也会出现 ``[formula](formula)`` 形状；当前公开文档的
                # 本地导航目标均为 Markdown 文件，因此只检查这一明确子集。
                if not relative_target.lower().endswith(".md"):
                    continue
                resolved = (document_path.parent / relative_target).resolve()
                if not resolved.exists():
                    missing.append(
                        f"{document_path.relative_to(PROJECT_ROOT)} -> {target}"
                    )

        self.assertFalse(
            missing,
            "Broken local documentation links:\n" + "\n".join(missing),
        )


if __name__ == "__main__":
    unittest.main()
