"""测试内容：三类输入结构各自的转换入口，以及 frontend 的组合入口。

论文对应：带批注 HCSP、Gamma/Theta/参数和行为 Type 分别是类型构造/未来类型检查
共享的输入对象；完整 source 仅在组合前端中把前三者绑定起来。
"""

from __future__ import annotations

import unittest

from hcsp_typechecker.frontend.annotated_hcsp_syntax import parse_annotated_hcsp
from hcsp_typechecker.frontend.type_constructor_frontend import parse_hcsp_source
from hcsp_typechecker.data_structures.process_ast.ast import Skip
from hcsp_typechecker.frontend.type_syntax import (
    format_type_source,
    parse_type_source,
)
from hcsp_typechecker.data_structures.type_ast.ast import EmptyType
from hcsp_typechecker.frontend.typing_context_syntax import parse_typing_context


class TestInputStructureBoundaries(unittest.TestCase):
    """验证各输入结构不依赖完整 TypeConstructor 门面也可独立 lower。"""

    # 测试输入：最小带批注 HCSP process_system。
    # 预期行为：得到正式 Process AST。
    # 检查内容：Process 片段入口属于 annotated_hcsp 包。
    # 论文对应：Section 2.1 的 process 层语法。
    def test_annotated_hcsp_fragment_lowers_to_process_ast(self) -> None:
        """带批注 HCSP 片段转换为既有 Process AST。"""

        self.assertEqual(parse_annotated_hcsp("{{skip}}"), Skip())

    # 测试输入：仅含 Gamma、参数和 Theta 的上下文前缀。
    # 预期行为：得到三个正式环境对象。
    # 检查内容：环境结构不需要伪造 process 段即可完成声明 lowering。
    # 论文对应：类型构造使用的 Gamma、Theta 和共享参数 H。
    def test_typing_context_fragment_lowers_to_environment_objects(self) -> None:
        """Gamma、参数与 Theta 片段转换为只读内部环境。"""

        context = parse_typing_context(
            "gamma(x: Real) "
            "parameters(limit: Real) where(limit >= 0) "
            "theta(ch: channel(value: Real))"
        )
        self.assertEqual(tuple(context.gamma), ("x",))
        self.assertEqual(tuple(context.parameters.declarations), ("limit",))
        self.assertEqual(tuple(context.theta), ("ch",))

    # 测试输入：最小 Type source。
    # 预期行为：Type AST 与规范化文本可逆。
    # 检查内容：Type 语法独立于 Process 和环境结构。
    # 论文对应：行为类型 T 的空通信行为 0。
    def test_type_fragment_round_trips_independently(self) -> None:
        """Type 输入结构转换为 Type AST 后可无损规范化输出。"""

        value = parse_type_source("type empty")
        self.assertEqual(value, EmptyType())
        self.assertEqual(format_type_source(value), "type empty")

    # 测试输入：完整 source。
    # 预期行为：组合前端绑定三类输入结果和 Process AST。
    # 检查内容：完整入口只负责组合，不取代各片段转换入口。
    # 论文对应：一次类型构造所需的完整输入上下文。
    def test_frontend_combines_context_and_process(self) -> None:
        """完整 source 由 frontend 组合成一次内部构造上下文。"""

        parsed = parse_hcsp_source("gamma() theta() process {{skip}}")
        self.assertEqual(parsed.process, Skip())
        self.assertEqual(dict(parsed.gamma), {})
        self.assertEqual(dict(parsed.theta), {})


if __name__ == "__main__":
    unittest.main()
