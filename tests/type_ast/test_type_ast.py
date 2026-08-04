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

from hcsp_typechecker import (
    AngelicType,
    BehavioralType,
    BottomType,
    CommunicationTimeoutType,
    ConfigurationType,
    EndType,
    ExternalChoiceType,
    InputType,
    InternalChoiceType,
    MuType,
    OutputType,
    ParallelType,
    ProcessType,
    PureDelayType,
    TimedExternalChoiceType,
    TypeVar,
    make_external_choice,
    make_timed_type,
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
        self.assertIsInstance(make_external_choice(()), EndType)
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
            ExternalChoiceType((input_branch, EndType()))  # type: ignore[arg-type]

    # 测试输入：合法 ASCII/Unicode 通道标识符及空白、标点、数字开头的非法名称。
    # 预期行为：InputType/OutputType 接受合法名称并统一拒绝非法名称。
    # 检查内容：防止直接构造 type AST 时绕过 process Channel 的词法边界。
    # 论文对应：A 中的 ch?.T/ch!.T 与 process 层的 ch 使用同一通道命名空间。
    def test_communication_type_channels_are_identifiers(self) -> None:
        """行为类型中的通道名遵循与 process AST 相同的标识符规则。"""

        for name in ("channel", "channel_1", "_private", "通道_1"):
            with self.subTest(valid=name):
                self.assertEqual(InputType(name, EndType()).channel, name)
                self.assertEqual(OutputType(name, EndType()).channel, name)

        for name in ("", " ", " channel", "channel ", "1channel", "a-b", "a\nb"):
            with self.subTest(invalid=repr(name)):
                with self.assertRaises(ValueError):
                    InputType(name, EndType())
                with self.assertRaises(ValueError):
                    OutputType(name, EndType())


class TimedTypeNormalizationTests(unittest.TestCase):
    """检查统一 delay 产生式被规范成语义互斥的具体节点。"""

    # 测试输入：有限 d 下，A 是否为空、fallback 是否为 bottom 的全部组合。
    # 预期行为：分别得到 PureDelay、CommunicationTimeout、TimedExternalChoice。
    # 检查内容：覆盖有限 delta/A/T 组合到三个具体类的全部分派分支。
    # 论文对应：Section 4.1 的三个 delay 定义式缩写。
    def test_unified_delay_rule_dispatches_to_distinct_nodes(self) -> None:
        """推导结果的语义差异必须直接反映在节点类上。"""

        communication = InputType("ch", EndType())
        self.assertEqual(
            make_timed_type(1, EndType(), EndType()),
            PureDelayType(1, EndType()),
        )
        self.assertEqual(
            make_timed_type(1, EndType(), BottomType()),
            PureDelayType(1, BottomType()),
        )
        self.assertEqual(
            make_timed_type(1, communication, BottomType()),
            CommunicationTimeoutType(1, communication),
        )
        self.assertEqual(
            make_timed_type(1, communication, EndType()),
            TimedExternalChoiceType(1, communication, EndType()),
        )

    # 测试输入：infinity 下分别组合 bottom/非 bottom 后继以及空/非空 A。
    # 预期行为：全部规范成 A，候选超时后继不进入最终类型 AST。
    # 检查内容：确认永远不会发生的超时事件在 process→type 边界被设置为 bottom。
    # 论文对应：A := delay(infinity) \unrhd A \triangleright \bot；无限等待只保留
    #           可由通信触发的 angelic type A。
    def test_infinite_delay_discards_timeout_fallback(self) -> None:
        """无限时延应把不可达 fallback 规范为空行为并返回 A。"""

        communication = InputType("ch", EndType())
        self.assertIs(
            make_timed_type(inf, communication, BottomType()),
            communication,
        )
        self.assertIs(
            make_timed_type(inf, communication, EndType()),
            communication,
        )
        self.assertEqual(
            make_timed_type(inf, EndType(), EndType()),
            EndType(),
        )

    # 测试输入：把空 A、bottom fallback、infinity 放入不对应的具体 delay 节点。
    # 预期行为：每种非规范直接构造都抛出 ValueError。
    # 检查内容：证明三个节点的字段状态空间互斥而不是换名后的通用容器。
    # 论文对应：delay(d).T、delay(d) \unrhd A 与完整式的适用条件不同。
    def test_delay_node_constructors_reject_overlapping_forms(self) -> None:
        """具体 delay 节点不能重新表达另一个节点负责的缩写。"""

        communication = OutputType("ch", EndType())
        with self.assertRaises(ValueError):
            CommunicationTimeoutType(1, EndType())
        with self.assertRaises(ValueError):
            TimedExternalChoiceType(1, EndType(), EndType())
        with self.assertRaises(ValueError):
            TimedExternalChoiceType(1, communication, BottomType())
        with self.assertRaises(ValueError):
            CommunicationTimeoutType(inf, communication)

    # 测试输入：int、float、Decimal 的同值时延，以及负数、Bool、NaN 等非法值。
    # 预期行为：有限合法值成为最简 Fraction，正无穷工厂规范为 A，其余失败。
    # 检查内容：类型 AST 只保存精确 duration，不保存 Literal/浮点近似。
    # 论文对应：0 <= d < infinity 的有限缩写和 delta=infinity 的 A 缩写。
    def test_duration_is_exact_and_checked_at_type_boundary(self) -> None:
        """类型节点独立维护精确非负有限时延不变量。"""

        self.assertEqual(PureDelayType(0.5, EndType()).duration, Fraction(1, 2))
        self.assertEqual(
            PureDelayType(Decimal("0.125"), EndType()).duration,
            Fraction(1, 8),
        )
        communication = InputType("ch", EndType())
        self.assertIs(
            make_timed_type(Decimal("Infinity"), communication, EndType()),
            communication,
        )
        for invalid in (-1, True, nan, -inf, Decimal("NaN")):
            with self.subTest(invalid=invalid):
                with self.assertRaises((TypeError, ValueError)):
                    PureDelayType(invalid, EndType())


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
            MuType("t", PureDelayType(1, TypeVar("t")))
        guarded = MuType("t", InputType("ch", TypeVar("t")))
        self.assertEqual(guarded.body, InputType("ch", TypeVar("t")))

    # 测试输入：仅绑定变量名不同、且包含 TimedExternalChoiceType 的两个递归类型。
    # 预期行为：types_equivalent 返回 true；改变通信方向后返回 false。
    # 检查内容：新时延节点的 duration、A、fallback 全部进入 alpha 结构键。
    # 论文对应：mu t.T 的受绑定变量改名不改变类型结构。
    def test_alpha_equivalence_covers_timed_nodes(self) -> None:
        """拆分 delay 节点后仍应保留递归类型的 alpha 等价。"""

        left = MuType(
            "t",
            TimedExternalChoiceType(
                1,
                InputType("ch", TypeVar("t")),
                EndType(),
            ),
        )
        right = MuType(
            "u",
            TimedExternalChoiceType(
                Fraction(1),
                InputType("ch", TypeVar("u")),
                EndType(),
            ),
        )
        changed = MuType(
            "u",
            TimedExternalChoiceType(
                1,
                OutputType("ch", TypeVar("u")),
                EndType(),
            ),
        )
        self.assertTrue(types_equivalent(left, right))
        self.assertFalse(types_equivalent(left, changed))


if __name__ == "__main__":
    unittest.main()
