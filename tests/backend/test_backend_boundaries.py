"""锁定 TypeConstructor、TypeChecker、Table 3 操作语义与共享后端目录边界。

测试内容：

* 两个业务后端是否分别位于 ``backend/type_constructor`` 和
  ``backend/type_checker``；
* 二者是否只共同继承 ``Table2RuleEngine``，而不互相继承；
* ``backend/common`` 是否保持对两个业务包的零依赖；
* ``data_structures`` 是否只保留领域数据且不反向依赖后端；
* Table 3 操作语义是否只依赖 Type/图数据结构而不反向调用两个 Table 2 后端；
* 已废弃的 ``typechecking`` 混合目录是否完全移除。

预期行为：共享规则和证明工具只能位于 common；Constructor 与 Checker 可以
依赖 common，但两个业务包不能互相导入。

论文对应：两个业务功能使用同一套项目 Table 2 规则；目录分层只隔离算法职责，
不复制或改变规则的数学含义。
"""

from __future__ import annotations

from pathlib import Path
import unittest

import hcsp_typechecker
from hcsp_typechecker.backend.common.rule_engine import Table2RuleEngine
from hcsp_typechecker.backend.common.environment import PreparedTypingEnvironment
from hcsp_typechecker.backend.type_checker import TypeChecker
from hcsp_typechecker.backend.type_constructor import TypeConstructor


class BackendBoundaryTests(unittest.TestCase):
    """验证后端物理布局和单向依赖。"""

    # 测试输入：两个业务类和共享规则引擎的 Python 继承关系。
    # 预期行为：两个业务类均继承共享引擎，但彼此不存在继承关系。
    # 检查内容：issubclass 关系和 TypeChecker/TypeConstructor 的职责独立性。
    # 论文对应：两项功能复用同一套 Table 2 规则，但递归目标不同。
    def test_business_backends_share_engine_without_inheriting_each_other(self) -> None:
        """Constructor 与 Checker 应是共享引擎的两个并列业务后端。"""

        self.assertTrue(issubclass(TypeConstructor, Table2RuleEngine))
        self.assertTrue(issubclass(TypeChecker, Table2RuleEngine))
        self.assertFalse(issubclass(TypeChecker, TypeConstructor))
        self.assertFalse(issubclass(TypeConstructor, TypeChecker))

    # 测试输入：共享规则引擎、两个业务类及公共环境准备结果的定义位置。
    # 预期行为：环境准备算法只由 common 引擎定义，Constructor/Checker 不再各存副本。
    # 检查内容：方法归属和结果类模块路径，防止后续修改重新制造两套环境规则。
    # 论文对应：Gamma、Theta 与参数是两种 Table 2 业务共同的判断前提。
    def test_typing_environment_preparation_has_one_common_implementation(self) -> None:
        """环境规范化与良构检查只能存在于共享后端。"""

        self.assertIn("_prepare_typing_environment", Table2RuleEngine.__dict__)
        self.assertNotIn("_prepare_typing_environment", TypeConstructor.__dict__)
        self.assertNotIn("_prepare_typing_environment", TypeChecker.__dict__)
        self.assertEqual(
            PreparedTypingEnvironment.__module__,
            "hcsp_typechecker.backend.common.environment",
        )

    # 测试输入：backend/common 下所有 Python 源文件的导入文本。
    # 预期行为：common 不得反向导入 type_constructor 或 type_checker。
    # 检查内容：共享层源码不存在两个业务包的模块路径。
    # 论文对应：共享规则层不预先选择“构造”或“检查”这一业务方向。
    def test_common_backend_does_not_import_business_backends(self) -> None:
        """共享后端必须位于依赖图底部。"""

        common = Path(hcsp_typechecker.__file__).parent / "backend" / "common"
        source = "\n".join(
            path.read_text(encoding="utf-8")
            for path in sorted(common.glob("*.py"))
        )
        self.assertNotIn("backend.type_constructor", source)
        self.assertNotIn("backend.type_checker", source)
        self.assertNotIn("..type_constructor", source)
        self.assertNotIn("..type_checker", source)

    # 测试输入：两个业务实现文件的导入文本。
    # 预期行为：Constructor 不导入 Checker，Checker 也不导入 Constructor。
    # 检查内容：两个模块只通过 backend/common 共享规则与证明工具。
    # 论文对应：构造类型和验证给定类型是使用同一规则的两个独立算法。
    def test_business_backends_do_not_import_each_other(self) -> None:
        """两个业务后端之间不得形成直接依赖。"""

        backend = Path(hcsp_typechecker.__file__).parent / "backend"
        constructor_source = (
            backend / "type_constructor" / "constructor.py"
        ).read_text(encoding="utf-8")
        checker_source = (
            backend / "type_checker" / "checker.py"
        ).read_text(encoding="utf-8")
        self.assertNotIn("type_checker", constructor_source)
        self.assertNotIn("type_constructor", checker_source)

    # 测试输入：backend/type_operational_semantics 下全部 Python 源码。
    # 预期行为：Table 3 图生成不导入 TypeConstructor 或 TypeChecker。
    # 检查内容：状态图后端只消费已有 Type AST，不重复运行任何 Table 2 业务流程。
    # 论文对应：Table 3 的前提是已经得到类型，与 Table 2 构造/检查算法职责分离。
    def test_operational_semantics_does_not_import_table2_backends(self) -> None:
        """Table 3 后端不能通过 Constructor/Checker 间接决定图转移。"""

        semantics = (
            Path(hcsp_typechecker.__file__).parent
            / "backend"
            / "type_operational_semantics"
        )
        source = "\n".join(
            path.read_text(encoding="utf-8")
            for path in sorted(semantics.glob("*.py"))
        )
        self.assertNotIn("type_constructor", source)
        self.assertNotIn("type_checker", source)

    # 测试输入：data_structures 的目录和全部 Python 导入文本。
    # 预期行为：Process/Type/规范 Type/runtime context/图模型均不依赖 backend。
    # 检查内容：旧业务模型目录不存在，全部领域数据源码不含后端导入路径。
    # 论文对应：数据层同时承载 Table 2 类型和 Table 3 图，但不执行任何规则算法。
    def test_data_structures_contain_only_domain_models(self) -> None:
        """领域数据层不得重新吸收 Constructor/Checker 的业务模型。"""

        data_structures = (
            Path(hcsp_typechecker.__file__).parent / "data_structures"
        )
        self.assertFalse((data_structures / "type_construction").exists())
        self.assertFalse((data_structures / "type_checking").exists())
        source = "\n".join(
            path.read_text(encoding="utf-8")
            for path in sorted(data_structures.rglob("*.py"))
        )
        self.assertNotIn("backend.", source)
        self.assertNotIn("..backend", source)

    # 测试输入：安装包根目录中的旧 typechecking 路径。
    # 预期行为：旧混合目录不存在，内部调用全部使用 backend 新层次。
    # 检查内容：文件系统中不存在 hcsp_typechecker/typechecking。
    # 论文对应：该检查只锁定实现架构，不改变任何推导规则。
    def test_legacy_mixed_backend_directory_is_removed(self) -> None:
        """旧的混合后端目录不能作为隐式兼容入口残留。"""

        package = Path(hcsp_typechecker.__file__).parent
        self.assertFalse((package / "typechecking").exists())


if __name__ == "__main__":
    unittest.main()
