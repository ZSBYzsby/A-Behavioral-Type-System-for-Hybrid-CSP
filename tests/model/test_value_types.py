"""检查 ``model.py`` 的基础值类型边界。

测试内容
--------

* ``BasicType`` 只公开论文实现采用的 Bool/N/Z/Q/R；
* 类型名称和 Python 类型对象的规范化；
* 数值提升仍严格遵循 Nat <: Int <: Rational <: Real。
* ``ContinuousType`` 与普通 ``BasicType.REAL`` 在 Gamma 中保持显式不同，
  并保存 Definition 4.1 的连续向量成员和轨迹性质 phi；
* ``ChannelType`` 允许多个独立 ``BasicType`` 槽位，但不形成 tuple 值类型。

论文对应
--------

测试 Definition 4.1 中基础类型 B 在项目数据模型里的落实，并验证 Table 2
表达式类型前提使用的数值兼容关系。

精确枚举检查保证实现不会静默扩大当前项目的值类型模型。
"""

from __future__ import annotations

import unittest

from hcsp_typechecker.expressions import Literal, parse_expr
from hcsp_typechecker.model import (
    BasicType,
    ChannelType,
    ContinuousType,
    gamma_value_type,
    is_subtype,
    normalize_channel_type,
    normalize_gamma_type,
    normalize_type,
)


class BasicTypeBoundaryTests(unittest.TestCase):
    """验证基础类型集合和公开规范化边界。"""

    # 测试输入：枚举 BasicType 的全部成员。
    # 预期行为：成员集合精确等于 Bool/Nat/Int/Rational/Real。
    # 检查内容：同时防止遗漏论文所需类型和静默扩大基础类型集合。
    # 论文对应：Definition 4.1 中本项目落实的基础类型 B。
    def test_basic_type_contains_only_supported_paper_value_types(self) -> None:
        """BasicType 的公开成员必须精确等于当前采用的五种基础值类型。"""

        self.assertEqual(
            tuple(BasicType),
            (
                BasicType.BOOL,
                BasicType.NAT,
                BasicType.INT,
                BasicType.RATIONAL,
                BasicType.REAL,
            ),
        )

    # 测试输入：五种类型的名称别名及 Python bool/int/float 类型对象。
    # 预期行为：全部被规范化为相应 BasicType 成员。
    # 检查内容：确认当前五种类型的用户友好输入保持稳定。
    # 论文对应：Gamma/Theta 中基础类型 B 的实现表示。
    def test_supported_type_specifications_are_normalized(self) -> None:
        """受支持的名称和 Python 数值类型对象应保持稳定规范化。"""

        cases = {
            "Bool": BasicType.BOOL,
            "Nat": BasicType.NAT,
            "Int": BasicType.INT,
            "Rational": BasicType.RATIONAL,
            "Real": BasicType.REAL,
            bool: BasicType.BOOL,
            int: BasicType.INT,
            float: BasicType.REAL,
        }
        for source, expected in cases.items():
            with self.subTest(source=source):
                self.assertIs(normalize_type(source), expected)

    # 测试输入：数值链上正向和反向的若干类型对。
    # 预期行为：低等级可提升到高等级，反向窄化被拒绝，Bool 只兼容自身。
    # 检查内容：正常数值子类型逻辑保持严格且方向正确。
    # 论文对应：Table 2 表达式类型前提所使用的基础类型兼容判断。
    def test_numeric_subtyping_remains_directional(self) -> None:
        """数值提升保持单向，Bool 只与自身兼容。"""

        self.assertTrue(is_subtype(BasicType.NAT, BasicType.REAL))
        self.assertTrue(is_subtype(BasicType.INT, BasicType.RATIONAL))
        self.assertFalse(is_subtype(BasicType.REAL, BasicType.INT))
        self.assertFalse(is_subtype(BasicType.BOOL, BasicType.INT))
        self.assertTrue(is_subtype(BasicType.BOOL, BasicType.BOOL))


class ChannelTypeBoundaryTests(unittest.TestCase):
    """验证 Theta 的多标量通道签名仍由独立基础类型组成。"""

    # 测试输入：一槽/多槽类型、默认/显式 binders，以及空槽和非法分量/名称。
    # 预期行为：每槽独立规范化；binders 与元数一一对应，非法签名立即失败。
    # 检查内容：tuple 仅保存通信签名，不能嵌套成为某个槽位的值类型。
    # 论文对应：按协作者确认扩展 Theta(ch) 的多槽签名，每个 Bi 仍是基础类型。
    def test_channel_signature_uses_independent_basic_slots(self) -> None:
        """多标量通道必须保存定元数的基础类型和 refinement binders。"""

        scalar = ChannelType("Int")
        self.assertEqual(scalar.value_types, (BasicType.INT,))
        self.assertEqual(scalar.binders, ("eta",))

        multiple = normalize_channel_type((BasicType.INT, "Real", bool))
        self.assertEqual(
            multiple.value_types,
            (BasicType.INT, BasicType.REAL, BasicType.BOOL),
        )
        self.assertEqual(multiple.binders, ("eta1", "eta2", "eta3"))

        explicit = ChannelType(
            (BasicType.INT, BasicType.REAL),
            "left <= right",
            binders=("left", "right"),
        )
        self.assertEqual(explicit.binders, ("left", "right"))

        invalid_declarations = (
            lambda: ChannelType(()),
            lambda: ChannelType((BasicType.INT, (BasicType.REAL,))),
            lambda: ChannelType((BasicType.INT, BasicType.REAL), binders=("x",)),
            lambda: ChannelType((BasicType.INT, BasicType.REAL), binders=("x", "x")),
            lambda: ChannelType((BasicType.INT,), binders=("not valid",)),
        )
        for declaration in invalid_declarations:
            with self.subTest(declaration=declaration):
                with self.assertRaises((TypeError, ValueError)):
                    declaration()


class ContinuousTypeBoundaryTests(unittest.TestCase):
    """验证 Gamma 连续项与普通 Real 值项的模型边界。"""

    # 测试输入：普通 BasicType.REAL 与默认 phi=true 的 ContinuousType()。
    # 预期行为：两项在 Gamma 规范化后保持不同，但表达式当前值类型均为 Real；
    #           连续类型的文本明确展示 Definition 4.1 的全程性质 true。
    # 检查内容：类别相等性、规范化结果、底层值类型、phi AST 和可读文本。
    # 论文对应：Definition 4.1 的 x:B 与 underlined(v):trajectory 两种 Gamma 项。
    def test_continuous_real_is_distinct_but_reads_as_real(self) -> None:
        """连续标记不能退化成普通 Real，同时仍提供实数当前值。"""

        continuous = ContinuousType()

        self.assertNotEqual(continuous, BasicType.REAL)
        self.assertIs(normalize_gamma_type(BasicType.REAL), BasicType.REAL)
        self.assertIs(normalize_gamma_type(continuous), continuous)
        self.assertIs(gamma_value_type(continuous), BasicType.REAL)
        self.assertEqual(continuous.phi, Literal(True))
        self.assertEqual(str(continuous), "R>=0 ~> Real")

    # 测试输入：连续 x 带非平凡轨迹性质 x>=0。
    # 预期行为：构造器立即把字符串规范化成项目 Expr，并把 phi 纳入值相等性；
    #           不同 phi 的连续声明不能在 Gamma 分区检查中被当成同一种类型。
    # 检查内容：phi 的严格 AST、可读显示以及 dataclass 相等性。
    # 论文对应：Definition 4.1 的 underlined(v):R>=0 -> phi。
    def test_continuous_type_stores_trajectory_property(self) -> None:
        """ContinuousType 必须正式保存而非丢弃连续轨迹性质 phi。"""

        nonnegative = ContinuousType(phi="x >= 0")

        self.assertEqual(nonnegative.phi, parse_expr("x >= 0"))
        self.assertIn("x >= 0", str(nonnegative))
        self.assertNotEqual(nonnegative, ContinuousType(phi=True))

    # 测试输入：显式连续向量 (p,v,a) 及联合性质 p<=10 and v<=4。
    # 预期行为：构造器保留有序成员，任一登记键都解析成同一个正式向量；显示
    #           文本同时暴露 phi 和成员，方便审计 Gamma 快照。
    # 检查内容：variables、effective_variables、phi 与可读文本。
    # 论文对应：Definition 4.1 的 underlined(v) 是整体 R^n 轨迹而非逐标量性质。
    def test_continuous_type_stores_explicit_vector_members(self) -> None:
        """多变量连续声明必须显式保留有序向量成员。"""

        trajectory = ContinuousType(
            variables=("p", "v", "a"),
            phi="p <= 10 and v <= 4",
        )

        self.assertEqual(trajectory.variables, ("p", "v", "a"))
        self.assertEqual(
            trajectory.effective_variables("v"),
            ("p", "v", "a"),
        )
        self.assertEqual(
            trajectory.phi,
            parse_expr("p <= 10 and v <= 4"),
        )
        self.assertIn("on (p, v, a)", str(trajectory))

    # 测试输入：空向量、重复成员、非法变量名以及误传单个字符串。
    # 预期行为：ContinuousType 构造时立即拒绝，不能把含糊向量带入 Gamma。
    # 检查内容：四类无效 variables 输入都产生 TypeError/ValueError。
    # 论文对应：连续向量必须由确定、互异的状态变量分量构成。
    def test_continuous_vector_rejects_invalid_members(self) -> None:
        """连续向量成员必须非空、互异并符合变量词法规则。"""

        invalid_declarations = (
            lambda: ContinuousType(variables=()),
            lambda: ContinuousType(variables=("x", "x")),
            lambda: ContinuousType(variables=("not valid",)),
            lambda: ContinuousType(variables="x"),
        )
        for declaration in invalid_declarations:
            with self.subTest(declaration=declaration):
                with self.assertRaises((TypeError, ValueError)):
                    declaration()

    # 测试输入：尝试构造 Bool/Int/Rational 连续轨迹，并把 ContinuousType 放入通道。
    # 预期行为：只有 Real 可成为连续当前值；Theta 槽位仍只接受 BasicType。
    # 检查内容：连续类型构造边界及 Gamma/Theta 类型命名空间隔离。
    # 论文对应：HCSP ODE 在实数状态空间演化，通道项仍使用基础类型 B。
    def test_continuous_type_rejects_non_real_and_channel_use(self) -> None:
        """连续类型只能出现在 Gamma，且只能表示实值连续轨迹。"""

        for value_type in (
            BasicType.BOOL,
            BasicType.NAT,
            BasicType.INT,
            BasicType.RATIONAL,
        ):
            with self.subTest(value_type=value_type):
                with self.assertRaises(TypeError):
                    ContinuousType(value_type)

        with self.assertRaises(TypeError):
            ChannelType(ContinuousType())


if __name__ == "__main__":
    unittest.main()
