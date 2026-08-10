"""Case-study 脚本对单一稳定公共接口的使用契约测试。

测试内容
--------
1. ``case.py`` 与 ``new_case.py`` 只能从包根导入 ``construct_hcsp_type`` 和公共
   异常，不能重新依赖旧两阶段入口、内部 AST 构造器或低层构造器；
2. 两个脚本生成的完整用户 source 都必须能通过同一个公开入口越过解析阶段。
   为避免在接口契约测试中重复执行昂贵 dL 证明，测试用恒假路径条件让推导在
   T-sigma 处稳定停止，并以 ``HCSPTypeConstructionError``（而非输入错误）证明解析成功。

论文对应
--------
两个脚本分别保存 Section 5 原始 ``phi_a`` 与加强 ``phi_a``。本文件不重新证明
dL 前提，只锁定案例以完整 source 进入统一的 source -> Type AST 工作流，且不再
从公开 API 取得 Process AST、Gamma、Theta 或参数环境的中间对象。
"""

from __future__ import annotations

import ast
from fractions import Fraction
import importlib.util
from pathlib import Path
from types import ModuleType
import unittest

from hcsp_typechecker import HCSPTypeConstructionError, construct_hcsp_type


PROJECT_ROOT = Path(__file__).resolve().parents[2]
CASE_DIRECTORY = PROJECT_ROOT / "case_study"
COMMON_PUBLIC_IMPORTS = {
    "HCSPInputError",
    "HCSPTypeConstructionError",
    "construct_hcsp_type",
}
EXPECTED_PUBLIC_IMPORTS = {
    # 原始案例需要单独识别“已得到完整候选类型，但证明仍为 unknown”，
    # 因而显式捕获更具体的不可信类型异常；改良案例只需把所有类型构造
    # 失败统一视为非零退出码，捕获其公共基类即可。
    "case.py": COMMON_PUBLIC_IMPORTS | {"HCSPUntrustedTypeConstructionError"},
    "new_case.py": COMMON_PUBLIC_IMPORTS,
}


def _load_case_module(filename: str) -> ModuleType:
    """从案例目录加载脚本，而不要求案例目录本身成为产品包。"""

    path = CASE_DIRECTORY / filename
    module_name = "_hcsp_case_test_" + path.stem
    specification = importlib.util.spec_from_file_location(module_name, path)
    if specification is None or specification.loader is None:
        raise RuntimeError(f"Cannot load case-study module {path}")
    module = importlib.util.module_from_spec(specification)
    specification.loader.exec_module(module)
    return module


class CaseStudyPublicInterfaceTests(unittest.TestCase):
    """防止可执行案例重新绕过项目承诺的单一用户入口。"""

    # 测试输入：解析两个 case-study Python 文件的项目导入语句。
    # 预期行为：项目包导入只来自根 hcsp_typechecker，名称恰为单入口与两个异常。
    # 检查内容：拒绝 _internal、子包路径、旧 parse/infer、AST 构造器和 construct_type。
    # 论文对应：这里只约束案例进入论文推导规则的工程边界，不改动案例公式。
    def test_case_scripts_import_only_the_single_stable_facade(self) -> None:
        """两个案例脚本不得重新依赖两阶段接口或任何内部模块。"""

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
                    EXPECTED_PUBLIC_IMPORTS[filename],
                )

    # 测试输入：两个脚本针对 d=3/2 生成的完整 Gamma/Parameters/Theta/Process source，
    #           调用单入口时额外给路径条件 false。
    # 预期行为：两份输入都先成功完成内部解析，再在 T-sigma 处以 false 类型错误停止；
    #           若 source 语法退化，本测试会得到 HCSPInputError 而不是预期异常。
    # 检查内容：核对 delay/显式空 flow ODE 的精确有理文本、false verdict、空部分类型和停止规则。
    # 论文对应：原始与加强案例只在 phi_a 强度上不同，基础混成系统输入保持一致；
    #           false 路径条件仅用于压缩该接口测试，不声称是案例的真实推导前提。
    def test_case_sources_cross_parsing_boundary_through_single_entrypoint(
        self,
    ) -> None:
        """两份完整案例 source 必须由单入口成功解析且进入类型推导。"""

        original = _load_case_module("case.py")
        improved = _load_case_module("new_case.py")
        period = Fraction(3, 2)
        sources = {
            "original": original._build_original_case_source(period),
            "improved": improved.build_source(period),
        }

        for name, source in sources.items():
            with self.subTest(case=name):
                self.assertIn("delay((3/2))", source)
                self.assertIn("ode(flow(), domain(t < (3/2)), delay((3/2)))", source)
                with self.assertRaises(HCSPTypeConstructionError) as captured:
                    construct_hcsp_type(
                        source,
                        source_name=f"case-study-{name}.hcsp",
                        path_condition=False,
                        output="none",
                    )
                error = captured.exception
                self.assertEqual(error.verdict, "false")
                self.assertEqual(error.partial_types, (None, None))
                self.assertIn("T-sigma", error.format_result())


if __name__ == "__main__":
    unittest.main()
