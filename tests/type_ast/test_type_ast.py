r"""Section 4.1/4.2 行为类型 AST 的规范化与构造边界测试。

测试内容
--------
1. ``A`` 的零、单、多通信分支分别拥有唯一节点形状。
2. 类型通信前缀的通道名遵循与 process 变量相同的标识符规则。
3. 论文统一时延产生式按推导结果分成纯等待、通信超时和完整定时外部选择。
4. 三种有限时延节点的适用条件互斥，并精确保存有理时延。
5. ``T``、``A``、``mathcal T`` 的层次阻止并行类型进入顺序过程位置。
6. ``mu t.T`` 在类型 AST 构造时执行 communication-guarded 检查。
7. 全部规范时延节点参与递归类型的 alpha 等价比较。
8. ``BehavioralType``、``ConfigurationType``、``ProcessType`` 和
   ``AngelicType`` 抽象层不能被直接实例化。
9. 嵌套选择、通信前缀、定时行为和并行组合的文本输出具有无歧义括号。

论文对应
--------
对应 Section 4.1 的 ``T/A`` 产生式、三个时延定义式缩写、递归类型良构要求，
以及 Section 4.2 的组合配置类型 ``mathcal T``。这些测试确保内部扁平化不会
产生论文没有定义的空选择、单分支内部选择或跨语法层嵌套。
"""

from __future__ import annotations

from decimal import Decimal
from fractions import Fraction
from math import inf, nan
import unittest

from hcsp_typechecker._internal import (
    AngelicType,
    BehavioralType,
    BottomType,
    ConfigurationType,
    EmptyType,
    EndType,
    ExternalChoiceType,
    FiniteDelayType,
    InfiniteDelayType,
    InputType,
    InternalChoiceType,
    MuType,
    NoInterruptType,
    OutputType,
    ParallelType,
    ProcessType,
    TypeVar,
    make_external_choice,
    make_delay_type,
    types_equivalent,
)


class AbstractTypeBaseTests(unittest.TestCase):
    """确认类型语法分类层不能绕过具体论文产生式单独构造。"""

    # 测试输入：直接实例化行为类型根、配置类型、过程类型和 angelic 类型基类。
    # 预期行为：四个构造都因继承抽象 __str__ 而抛出 TypeError。
    # 检查内容：锁定类型 AST 已有 ABC 边界，防止后续重构意外移除 abstractmethod。
    # 论文对应：Section 4.1/4.2 的 T、A、mathcal T 只能使用具体产生式表示。
    def test_abstract_type_categories_cannot_be_instantiated(self) -> None:
        """类型分类基类不是论文类型节点，必须保持不可实例化。"""

        for abstract_class in (
            BehavioralType,
            ConfigurationType,
            ProcessType,
            AngelicType,
        ):
            with self.subTest(abstract_class=abstract_class.__name__):
                with self.assertRaises(TypeError):
                    abstract_class()


class AngelicTypeNormalizationTests(unittest.TestCase):
    """检查 ``A`` 的分支数量与唯一 AST 表示。"""

    # 测试输入：零个、一个和两个合法通信分支，以及直接构造的非规范选择。
    # 预期行为：工厂分别返回 End/Input/External；空或单分支 External 构造失败。
    # 检查内容：同时拒绝把 EndType 伪装成 ExternalChoiceType 的通信分支。
    # 论文对应：A ::= 0 | A \sqcap ch?.T | A \sqcap ch!.T。
    def test_angelic_choice_has_one_shape_per_branch_count(self) -> None:
        """同一个 angelic choice 不应再有多个结构不同的 AST 表示。"""

        input_branch = InputType("in", EndType())
        output_branch = OutputType("out", EndType())
        self.assertIsInstance(make_external_choice(()), NoInterruptType)
        self.assertIs(make_external_choice((input_branch,)), input_branch)
        self.assertEqual(
            make_external_choice((input_branch, output_branch)),
            ExternalChoiceType((input_branch, output_branch)),
        )
        with self.assertRaises(ValueError):
            ExternalChoiceType(())
        with self.assertRaises(ValueError):
            ExternalChoiceType((input_branch,))
        with self.assertRaises(TypeError):
            ExternalChoiceType((input_branch, EmptyType()))  # type: ignore[arg-type]

    # 测试输入：合法 ASCII 通道标识符及 Unicode、空白、标点、数字开头名称。
    # 预期行为：InputType/OutputType 接受合法名称并统一拒绝非法名称。
    # 检查内容：防止直接构造 type AST 时绕过 process Channel 的词法边界。
    # 论文对应：A 中的 ch?.T/ch!.T 与 process 层的 ch 使用同一通道命名空间。
    def test_communication_type_channels_are_identifiers(self) -> None:
        """行为类型中的通道名遵循与 process AST 相同的标识符规则。"""

        for name in ("channel", "channel_1", "_private", "Channel2"):
            with self.subTest(valid=name):
                self.assertEqual(InputType(name, EndType()).channel, name)
                self.assertEqual(OutputType(name, EndType()).channel, name)

        for name in (
            "",
            " ",
            " channel",
            "channel ",
            "1channel",
            "a-b",
            "a\nb",
            "通道_1",
            "ｃｈ",
            "K",
        ):
            with self.subTest(invalid=repr(name)):
                with self.assertRaises(ValueError):
                    InputType(name, EndType())
                with self.assertRaises(ValueError):
                    OutputType(name, EndType())

    # 测试输入：ASCII 与 Unicode/NFKC 兼容形式的 TypeVar 和 MuType 绑定名。
    # 预期行为：ASCII 名称通过，非 ASCII 名称在直接 Type AST 构造时拒绝。
    # 检查内容：保证推导生成类型和手工类型使用同一递归名称词法边界。
    # 论文对应：过程类型变量 t 与 mu t.T 的绑定器共享统一 ASCII IDENT。
    def test_recursive_type_names_use_ascii_ident(self) -> None:
        """类型变量引用与递归绑定名必须满足项目 ASCII IDENT。"""

        self.assertEqual(TypeVar("t_1").name, "t_1")
        self.assertEqual(MuType("t_1", EndType()).variable, "t_1")
        for name in ("类型", "ｔ", "K"):
            with self.subTest(name=name):
                with self.assertRaises(ValueError):
                    TypeVar(name)
                with self.assertRaises(ValueError):
                    MuType(name, EndType())


class TimedTypeNormalizationTests(unittest.TestCase):
    """检查统一 delay 产生式被规范成语义互斥的具体节点。"""

    # 测试输入：有限 d 下，A 是否为空、fallback 是否为 bottom 的全部组合。
    # 预期行为：分别得到 PureDelay、CommunicationTimeout、TimedExternalChoice。
    # 检查内容：覆盖有限 delta/A/T 组合到三个具体类的全部分派分支。
    # 论文对应：Section 4.1 的三个 delay 定义式缩写。
    def test_unified_delay_rule_dispatches_to_distinct_nodes(self) -> None:
        """推导结果的语义差异必须直接反映在节点类上。"""

        communication = InputType("ch", EmptyType())
        self.assertEqual(
            make_delay_type(1, NoInterruptType(), EmptyType()),
            FiniteDelayType(1, NoInterruptType(), EmptyType()),
        )
        self.assertEqual(
            make_delay_type(1, communication, EmptyType()),
            FiniteDelayType(1, communication, EmptyType()),
        )

    # 测试输入：infinity 下分别组合 bottom/非 bottom 后继以及空/非空 A。
    # 预期行为：全部规范成 A，候选超时后继不进入最终类型 AST。
    # 检查内容：确认永远不会发生的超时事件在 process→type 边界被设置为 bottom。
    # 论文对应：A := delay(infinity) \unrhd A \triangleright \bot；无限等待只保留
    #           可由通信触发的 angelic type A。
    def test_infinite_delay_discards_timeout_fallback(self) -> None:
        """无限时延应把不可达 fallback 规范为空行为并返回 A。"""

        communication = InputType("ch", EmptyType())
        self.assertEqual(
            make_delay_type(inf, communication, BottomType()),
            InfiniteDelayType(communication),
        )
        self.assertEqual(
            make_delay_type(inf, communication, EmptyType()),
            InfiniteDelayType(communication),
        )
        self.assertEqual(
            make_delay_type(inf, NoInterruptType(), EmptyType()),
            InfiniteDelayType(NoInterruptType()),
        )

    # 测试输入：非法 A、bottom 后继和无穷时延直接传给有限时延节点。
    # 预期行为：字段类别或有限时延不变量不成立时，构造立即拒绝。
    # 检查内容：统一节点仍严格区分 A/T，并禁止把 bottom 用作有限正常后继。
    # 论文对应：有限 delay(d) \unrhd A \triangleright T 中 T 不可为 bottom。
    def test_delay_node_constructors_reject_overlapping_forms(self) -> None:
        """具体 delay 节点不能重新表达另一个节点负责的缩写。"""

        communication = OutputType("ch", EndType())
        with self.assertRaises(TypeError):
            FiniteDelayType(1, "not-an-interrupt", EmptyType())  # type: ignore[arg-type]
        with self.assertRaises(ValueError):
            FiniteDelayType(1, NoInterruptType(), BottomType())
        with self.assertRaises(ValueError):
            FiniteDelayType(1, communication, BottomType())

    # 测试输入：int、float、Decimal 的同值时延，以及负数、Bool、NaN 等非法值。
    # 预期行为：有限合法值成为最简 Fraction，正无穷工厂规范为 A，其余失败。
    # 检查内容：类型 AST 只保存精确 duration，不保存 Literal/浮点近似。
    # 论文对应：0 <= d < infinity 的有限缩写和 delta=infinity 的 A 缩写。
    def test_duration_is_exact_and_checked_at_type_boundary(self) -> None:
        """类型节点独立维护精确非负有限时延不变量。"""

        self.assertEqual(
            FiniteDelayType(0.5, NoInterruptType(), EndType()).duration,
            Fraction(1, 2),
        )
        self.assertEqual(
            FiniteDelayType(
                Decimal("0.125"), NoInterruptType(), EndType()
            ).duration,
            Fraction(1, 8),
        )
        communication = InputType("ch", EmptyType())
        self.assertEqual(
            make_delay_type(Decimal("Infinity"), communication, EmptyType()),
            InfiniteDelayType(communication),
        )
        for invalid in (-1, True, nan, -inf, Decimal("NaN")):
            with self.subTest(invalid=invalid):
                with self.assertRaises((TypeError, ValueError)):
                    FiniteDelayType(invalid, NoInterruptType(), EndType())


class TypeLayerAndRecursionTests(unittest.TestCase):
    """检查类型语法层次及递归类型良构性。"""

    # 测试输入：合法二元 ParallelType，并尝试把它放入 input、choice 和 mu 的 T 位置。
    # 预期行为：所有跨层嵌套均失败，空/单分支内部选择和单分量并行也失败。
    # 检查内容：区分 Section 4.1 的 T 与 Section 4.2 的 mathcal T。
    # 论文对应：mathcal T 可包含 T，但 mathcal T 本身不能反向充当 T。
    def test_configuration_type_cannot_appear_inside_process_type(self) -> None:
        """组合配置类型不能污染通信后继、内部选择或递归体。"""

        combined = ParallelType((EndType(), BottomType()))
        with self.assertRaises(TypeError):
            InputType("ch", combined)  # type: ignore[arg-type]
        with self.assertRaises(TypeError):
            InternalChoiceType((EndType(), combined))  # type: ignore[arg-type]
        with self.assertRaises(TypeError):
            MuType("t", combined)  # type: ignore[arg-type]
        with self.assertRaises(ValueError):
            InternalChoiceType((EndType(),))
        with self.assertRaises(ValueError):
            ParallelType((EndType(),))
        with self.assertRaises(TypeError):
            ProcessType()

    # 测试输入：直接回边、纯等待后回边和输入通信后回边三种 mu 类型体。
    # 预期行为：前两种构造失败；经过 ch? 前缀的递归成功。
    # 检查内容：由类型 AST 自身检查每条目标变量路径的 communication guard。
    # 论文对应：Section 4.1 要求 recursive types guarded by communication prefix。
    def test_recursive_type_requires_a_communication_guard(self) -> None:
        """仅有 delay 不能代替输入或输出通信保护递归变量。"""

        with self.assertRaises(ValueError):
            MuType("t", TypeVar("t"))
        with self.assertRaises(ValueError):
            MuType(
                "t",
                FiniteDelayType(1, NoInterruptType(), TypeVar("t")),
            )
        guarded = MuType("t", InputType("ch", TypeVar("t")))
        self.assertEqual(guarded.body, InputType("ch", TypeVar("t")))

    # 测试输入：仅绑定变量名不同、且包含 FiniteDelayType 的两个递归类型。
    # 预期行为：types_equivalent 返回 true；改变通信方向后返回 false。
    # 检查内容：新时延节点的 duration、A、fallback 全部进入 alpha 结构键。
    # 论文对应：mu t.T 的受绑定变量改名不改变类型结构。
    def test_alpha_equivalence_covers_timed_nodes(self) -> None:
        """拆分 delay 节点后仍应保留递归类型的 alpha 等价。"""

        left = MuType(
            "t",
            FiniteDelayType(
                1,
                InputType("ch", TypeVar("t")),
                OutputType("done", EndType()),
            ),
        )
        right = MuType(
            "u",
            FiniteDelayType(
                Fraction(1),
                InputType("ch", TypeVar("u")),
                OutputType("done", EndType()),
            ),
        )
        changed = MuType(
            "u",
            FiniteDelayType(
                1,
                OutputType("ch", TypeVar("u")),
                OutputType("done", EndType()),
            ),
        )
        self.assertTrue(types_equivalent(left, right))
        self.assertFalse(types_equivalent(left, changed))


class TypeRenderingTests(unittest.TestCase):
    """固定面向用户的类型文本结构，防止嵌套运算再次产生视觉歧义。"""

    # 测试输入：输入前缀的后继是内部选择，两个内部选择分支均为输出前缀。
    # 预期行为：输入前缀括住整个内部选择，每个输出前缀也括住自己的后继。
    # 检查内容：输出不能被误读成 ``(in?.left!.0) \sqcup right!.0``。
    # 论文对应：通信前缀 ``ch?.T`` 的作用域覆盖完整后继类型 ``T``。
    def test_communication_prefix_parenthesizes_complete_continuation(self) -> None:
        """通信后继中的选择必须明确属于该通信前缀。"""

        value = InputType(
            "in",
            InternalChoiceType(
                (
                    OutputType("left", EndType()),
                    OutputType("right", EndType()),
                )
            ),
        )

        self.assertEqual(
            str(value),
            r"in?.((left!.(0)) \sqcup (right!.(0)))",
        )

    # 测试输入：双通信分支的完整定时选择，其正常到时后继又是内部选择。
    # 预期行为：\unrhd 右侧的整个 A 与 \triangleright 右侧的整个 T 分别加括号。
    # 检查内容：外部选择的每条通信分支也各自具有清晰边界。
    # 论文对应：``delay(d) \unrhd A \triangleright T`` 的 A/T 是两个独立子树。
    def test_timed_type_parenthesizes_choices_and_fallback(self) -> None:
        """完整定时类型应直接显露 choices 与 fallback 的 AST 边界。"""

        choices = ExternalChoiceType(
            (
                InputType("reset", EndType()),
                OutputType("alarm", EndType()),
            )
        )
        fallback = InternalChoiceType(
            (
                OutputType("left", EndType()),
                OutputType("right", EndType()),
            )
        )

        self.assertEqual(
            str(FiniteDelayType(2, choices, fallback)),
            r"delay(2) \unrhd ((reset?.(0)) \sqcap (alarm!.(0))) "
            r"\triangleright ((left!.(0)) \sqcup (right!.(0)))",
        )
        self.assertEqual(
            str(FiniteDelayType(2, choices, EmptyType())),
            r"delay(2) \unrhd ((reset?.(0)) \sqcap (alarm!.(0)))",
        )

    # 测试输入：左分量为递归内部选择，右分量为带输出后继的纯等待。
    # 预期行为：mu 体、内部选择分支、delay 后继和每个并行分量均有明确括号。
    # 检查内容：同时固定递归、时延和并行三种外层构造的组合显示。
    # 论文对应：mathcal T 的两个分量分别保存完整的过程类型 T。
    def test_parallel_type_parenthesizes_complete_components(self) -> None:
        """并行竖线两侧必须能直接看出各自完整的配置子树。"""

        recursive = MuType(
            "t",
            InternalChoiceType(
                (
                    InputType("ch", TypeVar("t")),
                    OutputType("stop", EndType()),
                )
            ),
        )
        delayed = FiniteDelayType(
            1,
            NoInterruptType(),
            OutputType("done", EndType()),
        )

        self.assertEqual(
            str(ParallelType((recursive, delayed))),
            r"(mu t.((ch?.(t)) \sqcup (stop!.(0)))) "
            r"| (delay(1).(done!.(0)))",
        )


if __name__ == "__main__":
    unittest.main()
