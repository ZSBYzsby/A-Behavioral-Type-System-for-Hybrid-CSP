"""后端 Python 风格与可读性约定的自动化回归测试。

测试内容：检查后端行宽、future annotations、通配符导入、dataclass slots 和
__init__ 返回标注。

论文对应：本文件不改变 Table 2 数学规则，只保证 Constructor、Checker 与共享
证明层持续采用一致、可审计的实现风格。
"""

from __future__ import annotations

import ast
from pathlib import Path
import unittest

import hcsp_typechecker


class BackendStyleTests(unittest.TestCase):
    """锁定后端模块共同遵守的机械代码风格。"""

    # 测试输入：backend 下全部 Python 文件及其抽象语法树。
    # 预期行为：行宽、future import、显式导入、slots 和初始化标注全部统一。
    # 检查内容：集中报告所有不符合 BACKEND_CODE_STYLE.md 的文件和行号。
    # 论文对应：只约束实现形式，不修改任何 HCSP 类型判断或证明前提。
    def test_backend_sources_follow_shared_style(self) -> None:
        """检查全部后端源码的稳定机械风格。"""

        backend = Path(hcsp_typechecker.__file__).parent / "backend"
        violations: list[str] = []
        for path in sorted(backend.rglob("*.py")):
            source = path.read_text(encoding="utf-8")
            relative = path.relative_to(backend)
            tree = ast.parse(source, filename=str(path))

            for line_number, line in enumerate(source.splitlines(), 1):
                if len(line) > 100:
                    violations.append(
                        f"{relative}:{line_number}: line exceeds 100 characters"
                    )

            if path.name != "__init__.py":
                has_future_annotations = any(
                    isinstance(node, ast.ImportFrom)
                    and node.module == "__future__"
                    and any(alias.name == "annotations" for alias in node.names)
                    for node in tree.body
                )
                if not has_future_annotations:
                    violations.append(
                        f"{relative}: missing future annotations import"
                    )

            for node in ast.walk(tree):
                if isinstance(node, ast.ImportFrom) and any(
                    alias.name == "*" for alias in node.names
                ):
                    violations.append(
                        f"{relative}:{node.lineno}: wildcard import"
                    )
                if isinstance(node, ast.FunctionDef) and node.name == "__init__":
                    if not (
                        isinstance(node.returns, ast.Constant)
                        and node.returns.value is None
                    ):
                        violations.append(
                            f"{relative}:{node.lineno}: __init__ needs -> None"
                        )
                if not isinstance(node, ast.ClassDef):
                    continue
                for decorator in node.decorator_list:
                    is_dataclass = (
                        isinstance(decorator, ast.Name)
                        and decorator.id == "dataclass"
                    ) or (
                        isinstance(decorator, ast.Call)
                        and isinstance(decorator.func, ast.Name)
                        and decorator.func.id == "dataclass"
                    )
                    if not is_dataclass:
                        continue
                    slots_enabled = isinstance(decorator, ast.Call) and any(
                        keyword.arg == "slots"
                        and isinstance(keyword.value, ast.Constant)
                        and keyword.value.value is True
                        for keyword in decorator.keywords
                    )
                    if not slots_enabled:
                        violations.append(
                            f"{relative}:{node.lineno}: dataclass needs slots=True"
                        )

        self.assertFalse(
            violations,
            "Backend style violations:\n" + "\n".join(violations),
        )


if __name__ == "__main__":
    unittest.main()
