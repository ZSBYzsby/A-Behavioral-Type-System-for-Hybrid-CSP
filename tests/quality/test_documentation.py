"""Python 文档和测试审计注释的质量回归检查。

测试内容
--------
1. 每个 Python 模块、类、函数和嵌套函数都必须具有 docstring。
2. 每个 ``test_*.py`` 文件头必须同时给出“测试内容”和“论文对应”。
3. 每个静态测试函数前必须具有测试输入、预期行为、检查内容和论文对应注释。
4. 动态场景工厂中名为 ``test`` 的内层函数也执行相同检查。
5. 构建目录、虚拟环境和本地临时目录中的第三方 Python 文件不属于审计对象。

论文对应
--------
本文件不实现新的论文规则，而是保证所有验证 Section 2.1、Section 4 和
Table 2/3 的测试持续保留足够审计信息，防止以后新增测试时说明退化。
"""

from __future__ import annotations

import ast
import unittest
from pathlib import Path


# 本文件位于 tests/quality；向上两级到达项目根。
PROJECT_ROOT = Path(__file__).resolve().parents[2]
EXCLUDED_DIRECTORY_NAMES = frozenset(
    {
        ".git",
        ".tmp",
        ".venv",
        "build",
        "dist",
        "venv",
        "__pycache__",
    }
)


class DocumentationCoverageTests(unittest.TestCase):
    """防止项目在后续修改中重新出现无说明的 Python 代码单元。"""

    # 测试输入：项目内全部 Python 源文件和所有 test_*.py 的语法树。
    # 预期行为：docstring、测试文件头目录和四项测试前置注释均无遗漏。
    # 检查内容：集中扫描并一次报告所有文件、行号、定义名和缺失类别。
    # 论文对应：保证每条论文语法/类型/dL 回归测试都有可追踪说明。
    def test_documentation_and_test_audit_comments_are_complete(self) -> None:
        """扫描 AST，集中报告缺失 docstring 或测试审计注释的位置。"""
        missing: list[str] = []

        for path in sorted(PROJECT_ROOT.rglob("*.py")):
            relative = path.relative_to(PROJECT_ROOT)
            directory_parts = relative.parts[:-1]
            if any(
                part in EXCLUDED_DIRECTORY_NAMES or part.endswith(".egg-info")
                for part in directory_parts
            ):
                continue

            # utf-8-sig 同时兼容普通 UTF-8 和可能带 BOM 的外部编辑器文件。
            source = path.read_text(encoding="utf-8-sig")
            tree = ast.parse(source, filename=str(path))
            source_lines = source.splitlines()

            if ast.get_docstring(tree) is None:
                missing.append(f"{relative}: module")

            if path.name.startswith("test_"):
                module_doc = ast.get_docstring(tree) or ""
                for heading in ("测试内容", "论文对应"):
                    if heading not in module_doc:
                        missing.append(
                            f"{relative}: module header missing {heading}"
                        )

            # ast.walk 会同时访问顶层函数、方法和嵌套测试工厂函数。
            for node in ast.walk(tree):
                if not isinstance(
                    node,
                    (ast.ClassDef, ast.FunctionDef, ast.AsyncFunctionDef),
                ):
                    continue
                if ast.get_docstring(node) is None:
                    missing.append(f"{relative}:{node.lineno}: {node.name}")

                is_test_function = isinstance(
                    node,
                    (ast.FunctionDef, ast.AsyncFunctionDef),
                ) and (
                    node.name.startswith("test_") or node.name == "test"
                )
                if not path.name.startswith("test_") or not is_test_function:
                    continue

                preceding = "\n".join(
                    source_lines[max(0, node.lineno - 9):node.lineno - 1]
                )
                for label in (
                    "测试输入：",
                    "预期行为：",
                    "检查内容：",
                    "论文对应：",
                ):
                    if f"# {label}" not in preceding:
                        missing.append(
                            f"{relative}:{node.lineno}: {node.name} "
                            f"missing {label} comment"
                        )

        self.assertFalse(
            missing,
            "Missing audit documentation:\n" + "\n".join(missing),
        )


if __name__ == "__main__":
    unittest.main()
