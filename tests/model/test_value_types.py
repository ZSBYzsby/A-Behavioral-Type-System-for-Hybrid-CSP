"""检查 ``model.py`` 的基础值类型边界。

测试内容
--------

* ``BasicType`` 只公开论文实现采用的 Bool/N/Z/Q/R；
* 类型名称和 Python 类型对象的规范化；
* 数值提升仍严格遵循 Nat <: Int <: Rational <: Real。
* ``ContinuousType`` 与普通 ``BasicType.REAL`` 在 Gamma 中保持显式不同，
  只保存允许出现的 ODE 演化向量，不再保存轨迹性质 phi；
* ``ChannelType`` 允许多个独立 ``BasicType`` 槽位，但不形成 tuple 值类型。

论文对应
--------

测试 Definition 4.1 中基础类型 B 在项目数据模型里的落实，并验证 Table 2
表达式类型前提使用的数值兼容关系。

精确枚举检查保证实现不会静默扩大当前项目的值类型模型。
"""

from __future__ import annotations

import unittest

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

    # 测试输入：普通 BasicType.REAL 与独立单元素 ODE 向量声明。
    # 预期行为：两项在 Gamma 中保持不同，且向量声明不能作为表达式标量读取。
    # 检查内容：类别相等性、规范化结果、gamma_value_type 拒绝和可读文本。
    # 论文对应：x:Real 与 underlined(v):R>=0 -> R^n 是两种不同 Gamma 项。
    def test_continuous_declaration_is_not_a_scalar_value(self) -> None:
        """ODE 向量声明不再包装或冒充成员变量的 Real 值类型。"""

        continuous = ContinuousType(("x",))

        self.assertNotEqual(continuous, BasicType.REAL)
        self.assertIs(normalize_gamma_type(BasicType.REAL), BasicType.REAL)
        self.assertIs(normalize_gamma_type(continuous), continuous)
        with self.assertRaises(TypeError):
            gamma_value_type(continuous)
        self.assertEqual(str(continuous), "R>=0 ~> Real on (x)")

    # 测试输入：旧接口尝试向 ContinuousType 传入轨迹性质 phi。
    # 预期行为：构造器拒绝该字段，防止 Gamma 与 ODE safety 再次产生双重来源。
    # 检查内容：旧 phi 关键字稳定产生 TypeError，且对象没有 phi 属性。
    # 论文对应：连续项已退化为 R>=0 -> R^n，恒成立性质只位于 ODE 批注。
    def test_continuous_type_no_longer_accepts_trajectory_property(self) -> None:
        """ContinuousType 不再提供 phi 字段或兼容性旁路。"""

        with self.assertRaises(TypeError):
            ContinuousType(phi="x >= 0")  # type: ignore[call-arg]
        self.assertFalse(hasattr(ContinuousType(("x",)), "phi"))

    # 测试输入：显式连续向量 (p,v,a)。
    # 预期行为：构造器把成员规范成无序集合的稳定表示，逆序声明与其相等；
    #           文本暴露 R^3 值域和成员，方便审计 Gamma 快照。
    # 检查内容：variables、逆序相等性与可读文本。
    # 论文对应：退化后的 underlined(v) 是 R^n 轨迹，方程排列不改变向量。
    def test_continuous_type_stores_explicit_vector_members(self) -> None:
        """多变量连续声明保存规范化后的无序成员集合。"""

        trajectory = ContinuousType(
            variables=("p", "v", "a"),
        )

        self.assertEqual(trajectory.variables, ("a", "p", "v"))
        self.assertEqual(
            trajectory,
            ContinuousType(variables=("a", "v", "p")),
        )
        self.assertIn("R^3", str(trajectory))
        self.assertIn("on (a, p, v)", str(trajectory))

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

    # 测试输入：省略向量成员，并尝试把 ContinuousType 放入通道载荷槽。
    # 预期行为：ODE 声明必须给出非空成员集合；Theta 槽位仍只接受 BasicType。
    # 检查内容：显式向量构造边界及 Gamma/Theta 类型命名空间隔离。
    # 论文对应：连续项描述 ODE vector 而不是一个可通信的标量值类型 B。
    def test_continuous_type_requires_vector_and_rejects_channel_use(self) -> None:
        """连续声明只能作为 Gamma 中带成员集合的 ODE 向量项。"""

        with self.assertRaises(TypeError):
            ContinuousType()  # type: ignore[call-arg]
        with self.assertRaises(TypeError):
            ChannelType(ContinuousType(("x",)))


if __name__ == "__main__":
    unittest.main()
