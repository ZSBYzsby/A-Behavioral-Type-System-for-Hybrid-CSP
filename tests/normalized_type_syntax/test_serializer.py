r"""规范化 Type AST 复用原用户 Type 风格的只读输出测试。

测试内容
--------
1. 规范配置、时延和中断沿用用户 Type 风格，扁平选择与匿名递归显式展示。
2. 原 Type AST 的已确认结构等价差异得到完全相同的规范文本。
3. 嵌套匿名递归分别显示最近和外层 De Bruijn 位置。
4. 输出子包拒绝错误根类别，并且有意不提供任何解析入口。

论文对应
--------
本文件不增加 Table 3 规则，只验证状态图规范类型的面向用户展示不破坏规范状态
判重结果，也不被误解为另一套可输入 Type 语法。
"""

from __future__ import annotations

from fractions import Fraction
import unittest

import hcsp_typechecker.frontend.normalized_type_syntax as normalized_syntax
from hcsp_typechecker.data_structures.normalized_type_ast import normalize_type_ast
from hcsp_typechecker.data_structures.type_ast import (
    BottomType,
    EmptyType,
    ExternalChoiceType,
    FiniteDelayType,
    InfiniteDelayType,
    InputType,
    InternalChoiceType,
    MuType,
    NoInterruptType,
    OutputType,
    ParallelType,
    TypeVar,
)
from hcsp_typechecker.frontend.normalized_type_syntax import (
    format_normalized_type_ast,
)


class NormalizedTypeSerializerTests(unittest.TestCase):
    """锁定规范状态唯一、完整且仅用于输出的文本形式。"""

    # 测试输入：含内部选择、bottom、有限/无穷时延、多元中断和递归变量的完整类型。
    # 预期行为：内部选择无分支圆括号，mu 匿名，引用显示 recursion_position(0)。
    # 检查内容：并行、扁平选择、时延、中断及递归位置覆盖全部复合结构。
    # 论文对应：覆盖状态空间中 T、A、mu 和配置并行层的全部结构种类。
    def test_complete_normalized_tree_reuses_user_type_style(self) -> None:
        """复杂规范类型按稳定的原用户 Type 风格完整输出。"""

        recursive = MuType(
            "loop",
            InfiniteDelayType(InputType("again", TypeVar("loop"))),
        )
        delayed = FiniteDelayType(
            Fraction(3, 2),
            ExternalChoiceType(
                (
                    OutputType("report", EmptyType()),
                    InputType("reset", recursive),
                )
            ),
            InternalChoiceType((BottomType(), EmptyType())),
        )

        rendered = format_normalized_type_ast(
            normalize_type_ast(
                ParallelType((delayed, InfiniteDelayType(NoInterruptType())))
            )
        )

        for fragment in (
            "normalized type parallel {",
            "delay(3/2) interrupt",
            "angelic {",
            "again? ->",
            "report! ->",
            "mu {",
            "again? -> recursion_position(0)",
            "internal {",
            "empty",
            "bottom",
            "forever",
        ):
            with self.subTest(fragment=fragment):
                self.assertIn(fragment, rendered)
        self.assertTrue(
            all(
                not line or (len(line) - len(line.lstrip())) % 4 == 0
                for line in rendered.splitlines()
            )
        )
        for hidden_implementation_spelling in (
            "NormalizedConfigurationType(",
            "NormalizedFiniteDelayType(",
            "NormalizedInfiniteDelayType(",
            "NormalizedNoInterruptType(",
            "NormalizedExternalChoiceType(",
            "NormalizedInputType(",
            "NormalizedOutputType(",
            "Fraction(",
            "index=",
            "(empty)",
            "(bottom)",
            "mu X",
        ):
            with self.subTest(hidden=hidden_implementation_spelling):
                self.assertNotIn(hidden_implementation_spelling, rendered)

    # 测试输入：并行顺序/嵌套不同，内部和外部选择含不同排列及重复分支的两个原类型。
    # 预期行为：两者先规范化后输出逐字相同。
    # 检查内容：展示语法不会重新引入已经由 ACI/ACU 规范化消除的结构差异。
    # 论文对应：状态图以规范商结构判重，相同状态必须只有一种用户可见文本。
    def test_equivalent_original_shapes_have_identical_output(self) -> None:
        """规范等价的原类型共享唯一输出。"""

        first = FiniteDelayType(1, NoInterruptType(), EmptyType())
        second = InfiniteDelayType(
            ExternalChoiceType(
                (InputType("ch", EmptyType()), OutputType("dh", EmptyType()))
            )
        )
        left = ParallelType((second, EmptyType(), first))
        right = ParallelType((first, second))

        self.assertEqual(
            format_normalized_type_ast(normalize_type_ast(left)),
            format_normalized_type_ast(normalize_type_ast(right)),
        )

    # 测试输入：外层 outer 与内层 inner 都经通信受保护，内层体分别引用两层变量。
    # 预期行为：inner 显示 recursion_position(0)，outer 显示 recursion_position(1)。
    # 检查内容：匿名 mu 不丢失 De Bruijn 绑定距离，且不重新伪造变量名称。
    # 论文对应：循环项图重建递归展示树时必须区分最近 binder 与再外一层 binder。
    def test_nested_mu_displays_de_bruijn_recursion_positions(self) -> None:
        """嵌套递归用位置而不是合成变量名表达绑定关系。"""

        nested = MuType(
            "outer",
            InfiniteDelayType(
                InputType(
                    "enter",
                    MuType(
                        "inner",
                        InfiniteDelayType(
                            ExternalChoiceType(
                                (
                                    InputType("again", TypeVar("inner")),
                                    OutputType("leave", TypeVar("outer")),
                                )
                            )
                        ),
                    ),
                )
            ),
        )

        rendered = format_normalized_type_ast(normalize_type_ast(nested))

        self.assertEqual(rendered.count("mu {"), 2)
        self.assertIn("again? -> recursion_position(0)", rendered)
        self.assertIn("leave! -> recursion_position(1)", rendered)
        self.assertNotIn("outer", rendered)
        self.assertNotIn("inner", rendered)

    # 测试输入：原 Type AST 而非规范配置，以及 normalized_type_syntax 导出命名空间。
    # 预期行为：错误根类别抛 TypeError；子包只有 formatter，没有 parse 函数。
    # 检查内容：输出语法保持单向边界，不会成为第二个用户 Type 输入前端。
    # 论文对应：规范化树只服务 Table 3 状态展示，不改变原用户 Type 语法。
    def test_output_syntax_is_deliberately_one_way(self) -> None:
        """规范输出不接受原类型且没有反向 parser。"""

        with self.assertRaises(TypeError):
            format_normalized_type_ast(EmptyType())  # type: ignore[arg-type]
        self.assertEqual(
            normalized_syntax.__all__,
            ["format_normalized_type_ast"],
        )
        self.assertFalse(hasattr(normalized_syntax, "parse_normalized_type_ast"))


if __name__ == "__main__":
    unittest.main()
