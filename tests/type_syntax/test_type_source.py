"""用户 Type 源码的解析、规范化输出与 Type AST 无损往返测试。

测试内容
--------
覆盖 ``empty``、``bottom``、多元内部/外部选择、有限/无穷时延、递归、
类型变量与并行 configuration type，并锁定空 Angelic Type 的缺省规则。

论文对应
--------
Section 4.1 的过程类型 ``T``、Angelic Type ``A`` 与 Section 4.2 的
configuration type ``mathcal T``。本测试只验证用户 Type 前端，不执行
TypeChecker 的 Table 2 正确性判断。
"""

from __future__ import annotations

import unittest
from fractions import Fraction
from textwrap import dedent

from hcsp_typechecker.frontend.type_constructor_frontend.errors import (
    HCSPInputError,
)
from hcsp_typechecker.frontend.type_syntax import (
    format_type_source,
    parse_type_source,
)
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


class TypeSourceRoundTripTests(unittest.TestCase):
    """验证每种正式 Type AST 节点都具有稳定、可再次解析的规范文本。"""

    # 测试输入：包含所有可由 type_source 根语法表达的 Type AST 节点的嵌套并行类型。
    # 预期行为：格式化结果以 type 开头，重新解析后与原 AST 严格相等。
    # 检查内容：T/A 分层、分支顺序、Fraction 时延和 Mu 绑定名称均不丢失。
    # 论文对应：T、A、mathcal T 的全部正式产生式及 A 的分支数规范化。
    def test_format_then_parse_preserves_complete_type_ast(self) -> None:
        """规范序列化必须对完整嵌套 Type AST 保持无损。"""

        value = ParallelType(
            (
                FiniteDelayType(
                    Fraction(3, 2),
                    ExternalChoiceType(
                        (
                            InputType("reset", EmptyType()),
                            OutputType("alarm", BottomType()),
                        )
                    ),
                    InternalChoiceType(
                        (
                            EmptyType(),
                            InfiniteDelayType(OutputType("done", EmptyType())),
                        )
                    ),
                ),
                MuType(
                    "X",
                    InfiniteDelayType(InputType("tick", TypeVar("X"))),
                ),
            )
        )

        source = format_type_source(value)
        self.assertEqual(parse_type_source(source), value)
        self.assertEqual(
            source,
            dedent(
                """\
                type parallel {
                    delay(3/2) interrupt angelic {
                        reset? -> empty,
                        alarm! -> bottom
                    } then internal {
                        (empty),
                        (
                            forever interrupt angelic {
                                done! -> empty
                            }
                        )
                    },
                    mu X. forever interrupt angelic {
                        tick? -> X
                    }
                }"""
            ),
        )

    # 测试输入：有限/无穷 delay 中显式 angelic {} 与完全省略 interrupt 的两种写法。
    # 预期行为：二者均成为 NoInterruptType；序列化时统一输出省略 interrupt 的短写法。
    # 检查内容：empty T 与空 A 不混淆，且 parser 接受用户的显式空中断说明。
    # 论文对应：A 的空选择和 delay(d) unrhd A triangleright T 的缩写规则。
    def test_empty_angelic_is_accepted_and_canonicalized_when_delayed(self) -> None:
        """显式空 Angelic Type 与缺省中断应有相同的 Type AST。"""

        finite = parse_type_source(
            "type delay(1) interrupt angelic {} then empty"
        )
        infinite = parse_type_source("type forever interrupt angelic {}")

        self.assertEqual(
            finite,
            FiniteDelayType(Fraction(1), NoInterruptType(), EmptyType()),
        )
        self.assertEqual(infinite, InfiniteDelayType(NoInterruptType()))
        self.assertEqual(format_type_source(finite), "type delay(1) then empty")
        self.assertEqual(format_type_source(infinite), "type forever")

    # 测试输入：具有两个通信分支的 angelic 块和两个内部过程分支的 internal 块。
    # 预期行为：前者成为 ExternalChoiceType，后者成为 InternalChoiceType。
    # 检查内容：A 的外部选择不会被误降为 T 的内部选择，分支顺序保持输入顺序。
    # 论文对应：A ::= A sqcap ch?.T | A sqcap ch!.T 与 T ::= T sqcup T'。
    def test_multiple_angelic_and_internal_branches_remain_distinct(self) -> None:
        """多元外部选择与多元内部选择必须降低为不同的 AST 节点。"""

        value = parse_type_source(
            "type delay(0) interrupt angelic {a? -> empty, b! -> empty} "
            "then internal {(empty), (forever)}"
        )

        self.assertEqual(
            value,
            FiniteDelayType(
                Fraction(0),
                ExternalChoiceType(
                    (InputType("a", EmptyType()), OutputType("b", EmptyType()))
                ),
                InternalChoiceType(
                    (EmptyType(), InfiniteDelayType(NoInterruptType()))
                ),
            ),
        )

    # 测试输入：外层二元内部选择的左分支仍是二元内部选择，括号显式保留分块。
    # 预期行为：解析后得到嵌套 InternalChoiceType；序列化后分块完全不变。
    # 检查内容：不再按结合律把三片类型压成同一个三元节点。
    # 论文对应：每一层 T-If/T-sqcup 的子 judgment 与当前层括号分支逐项对应。
    def test_parentheses_preserve_nested_internal_choice_blocks(self) -> None:
        """内部选择的圆括号必须成为可逆的规则分块边界。"""

        source = "type internal {(internal {(empty), (forever)}), (bottom)}"
        value = parse_type_source(source)

        self.assertEqual(
            value,
            InternalChoiceType(
                (
                    InternalChoiceType(
                        (EmptyType(), InfiniteDelayType(NoInterruptType()))
                    ),
                    BottomType(),
                )
            ),
        )
        self.assertEqual(
            format_type_source(value),
            dedent(
                """\
                type internal {
                    (
                        internal {
                            (empty),
                            (forever)
                        }
                    ),
                    (bottom)
                }"""
            ),
        )


class TypeSourceDiagnosticsTests(unittest.TestCase):
    """验证 Type 前端拒绝无结构、非规范或不满足 AST 局部条件的输入。"""

    # 测试输入：把 angelic 直接放在 type 根位置。
    # 预期行为：拒绝；A 只能位于有限或无穷 delay 的 interrupt 位置。
    # 检查内容：T 与 A 的输入语法范畴严格分离。
    # 论文对应：T 与 A 是不同产生式，A 仅由 delay 节点引用。
    def test_angelic_type_cannot_be_the_type_root(self) -> None:
        """用户不能把单独的 Angelic Type 误写成完整过程类型。"""

        with self.assertRaises(HCSPInputError) as caught:
            parse_type_source("type angelic {ch? -> empty}")

    # 测试输入：旧版未给 internal 的两个分支加圆括号。
    # 预期行为：在第一个分支位置立即给出要求 ``(`` 的语法错误。
    # 检查内容：用户必须明确标注每一层选择规则的 Type 分块。
    # 论文对应：T-If/T-sqcup 的每个 premise 只消费当前括号内的对应 Type。
    def test_internal_choice_requires_parenthesized_branches(self) -> None:
        """旧版无括号内部选择语法必须被拒绝。"""

        with self.assertRaises(HCSPInputError) as caught:
            parse_type_source("type internal {empty, forever}")
        self.assertIn("must be parenthesized", str(caught.exception))
        self.assertEqual(caught.exception.phase, "syntax")

    # 测试输入：有限 delay 使用 bottom 作为自然到时后继。
    # 预期行为：由 FiniteDelayType 局部构造检查拒绝。
    # 检查内容：bottom 不会被误当作有限时延的正常终止。
    # 论文对应：有限 delay 的自然后继是 T；项目的 BottomType 不代表正常空行为。
    def test_finite_delay_rejects_bottom_continuation(self) -> None:
        """有限时延后继不得写成 BottomType。"""

        with self.assertRaises(HCSPInputError) as caught:
            parse_type_source("type delay(1) then bottom")
        self.assertEqual(caught.exception.phase, "validation")

    # 测试输入：缺少 delay 的 then 分隔符以及带尾逗号的 angelic 分支表。
    # 预期行为：两个输入均在具体语法阶段报错且保持源码行列信息。
    # 检查内容：关键字结构、逗号列表和 -> token 不会退化为表达式或 Process 语法。
    # 论文对应：将数学产生式固定为无优先级歧义的用户输入结构。
    def test_syntax_errors_preserve_source_diagnostics(self) -> None:
        """Type 前端应使用与 HCSP 前端一致的可定位诊断。"""

        for source in (
            "type delay(1) empty",
            "type forever interrupt angelic {ch? -> empty,}",
        ):
            with self.subTest(source=source), self.assertRaises(HCSPInputError) as caught:
                parse_type_source(source, source_name="expected.type")
            self.assertEqual(caught.exception.source_name, "expected.type")
            self.assertEqual(caught.exception.phase, "syntax")
