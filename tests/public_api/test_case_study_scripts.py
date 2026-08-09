"""Case-study 脚本对稳定公共接口的使用契约测试。

测试内容
--------
1. ``case.py`` 与 ``new_case.py`` 只能从包根导入稳定门面名称，不能重新依赖
   ``_internal``、直接 AST 构造器或低层检查器；
2. 两个脚本生成的完整用户 source 都必须由 ``parse_hcsp_program`` 成功转换为
   具有相同环境形状和两个并行分量的 ``HCSPProgram``。

论文对应
--------
两个脚本分别保存 Section 5 原始 ``phi_a`` 与加强 ``phi_a``；本文件不重新证明
dL 前提，只锁定它们都通过同一公开“source -> Process AST”边界进入类型推导。
"""

from __future__ import annotations

import ast
from fractions import Fraction
import importlib.util
from pathlib import Path
from types import ModuleType
import unittest

from hcsp_typechecker import HCSPProgram, parse_hcsp_program


PROJECT_ROOT = Path(__file__).resolve().parents[2]
CASE_DIRECTORY = PROJECT_ROOT / "case_study"
PUBLIC_IMPORTS = {
    "HCSPInputError",
    "HCSPTypeError",
    "infer_hcsp_type",
    "parse_hcsp_program",
}


def _load_case_module(filename: str) -> ModuleType:
    """从含空格的案例目录加载脚本，而不把它变成产品包。"""

    path = CASE_DIRECTORY / filename
    module_name = "_hcsp_case_test_" + path.stem
    specification = importlib.util.spec_from_file_location(module_name, path)
    if specification is None or specification.loader is None:
        raise RuntimeError(f"Cannot load case-study module {path}")
    module = importlib.util.module_from_spec(specification)
    specification.loader.exec_module(module)
    return module


class CaseStudyPublicInterfaceTests(unittest.TestCase):
    """防止可执行案例绕过项目承诺的两阶段用户接口。"""

    # 测试输入：解析两个 case-study Python 文件的 import 语句。
    # 预期行为：项目包导入只来自根 ``hcsp_typechecker``，且名称恰属于公开白名单。
    # 检查内容：拒绝 `_internal`、子包路径、AST 构造器和低层 check_hcsp 回流。
    # 论文对应：案例公式保持不变；这里只约束其进入论文推导规则的程序接口。
    def test_case_scripts_import_only_the_stable_facade(self) -> None:
        """两个案例脚本不得重新依赖任何非稳定项目内部模块。"""

        for filename in ("case.py", "new_case.py"):
            path = CASE_DIRECTORY / filename
            tree = ast.parse(path.read_text(encoding="utf-8"), filename=str(path))
            project_imports = [
                node
                for node in ast.walk(tree)
                if isinstance(node, ast.ImportFrom)
                and node.module is not None
                and node.module.startswith("hcsp_typechecker")
            ]
            with self.subTest(filename=filename):
                self.assertEqual(len(project_imports), 1)
                self.assertEqual(project_imports[0].module, "hcsp_typechecker")
                self.assertEqual(
                    {alias.name for alias in project_imports[0].names},
                    PUBLIC_IMPORTS,
                )

    # 测试输入：两个脚本针对 d=3/2 生成的完整 Gamma/Parameters/Theta/Process source。
    # 预期行为：公共第一接口均返回两分量 HCSPProgram，并保留相同环境声明顺序。
    # 检查内容：核对参数、Gamma、Theta、分量数及 delay/wait 的精确有理文本。
    # 论文对应：原始与加强案例只应在 phi_a 强度上不同，基础混成系统保持一致。
    def test_case_sources_parse_through_the_public_program_interface(self) -> None:
        """两份案例 source 必须完整通过公开解析门面。"""

        original = _load_case_module("case.py")
        improved = _load_case_module("new_case.py")
        period = Fraction(3, 2)
        sources = {
            "original": original._build_original_case_source(period),
            "improved": improved.build_source(period),
        }

        for name, source in sources.items():
            with self.subTest(case=name):
                program = parse_hcsp_program(source, output="none")
                self.assertIsInstance(program, HCSPProgram)
                self.assertEqual(
                    tuple(program.parameters.declarations),
                    ("end", "vmax", "amin", "amax"),
                )
                self.assertEqual(
                    tuple(program.gamma),
                    ("p", "v", "a", "vehicle_ode", "command"),
                )
                self.assertEqual(tuple(program.theta), ("ch", "dh", "stop"))
                self.assertEqual(len(program.process_components), 2)
                self.assertIn("delay((3/2))", source)
                self.assertIn("wait((3/2))", source)


if __name__ == "__main__":
    unittest.main()
