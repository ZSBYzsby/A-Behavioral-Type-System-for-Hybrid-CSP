"""检查 ``model.py`` 的基础值类型边界。

测试内容
--------

* ``BasicType`` 只公开论文实现采用的 Bool/N/Z/Q/R；
* 类型名称和 Python 类型对象的规范化；
* String、Unit、Any 三种旧扩展在所有公开入口都被拒绝；
* 数值提升仍严格遵循 Nat <: Int <: Rational <: Real。
* ``ChannelType`` 允许多个独立 ``BasicType`` 槽位，但不形成 tuple 值类型。

论文对应
--------

测试 Definition 4.1 中基础类型 B 在项目数据模型里的落实，并验证 Table 2
表达式类型前提使用的数值兼容关系。

这些测试防止后续为了示例方便而重新引入没有进入当前项目值类型模型的类型。
"""

from __future__ import annotations

import unittest

from hcsp_typechecker.model import (
    BasicType,
    ChannelType,
    is_subtype,
    normalize_channel_type,
    normalize_type,
)


class BasicTypeBoundaryTests(unittest.TestCase):
    """验证基础类型集合和公开规范化边界。"""

    # 测试输入：枚举 BasicType 的全部成员。
    # 预期行为：成员集合精确等于 Bool/Nat/Int/Rational/Real。
    # 检查内容：既防止遗漏论文所需类型，也防止加入 String/Unit/Any 扩展。
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
    # 检查内容：删除旧类型后，保留类型的用户友好输入没有受到影响。
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

    # 测试输入：String、Unit、Any 的文本别名和对应 Python 类型对象/值。
    # 预期行为：normalize_type 与 ChannelType 构造均立即抛出 TypeError。
    # 检查内容：旧扩展不能通过 Gamma 或 Theta 的任意公共入口重新进入模型。
    # 论文对应：当前基础类型域不为这些值提供 B，因此不能形成通道精化类型。
    def test_removed_value_types_are_rejected_at_model_boundary(self) -> None:
        """String、Unit、Any 及其旧简写不再是合法基础类型说明。"""

        removed = ("String", "str", "Unit", "Any", str, None, type(None))
        for specification in removed:
            with self.subTest(specification=specification):
                with self.assertRaisesRegex(TypeError, "must be a BasicType"):
                    normalize_type(specification)
                with self.assertRaisesRegex(TypeError, "must be a BasicType"):
                    ChannelType(specification)

    # 测试输入：数值链上正向和反向的若干类型对。
    # 预期行为：低等级可提升到高等级，反向窄化被拒绝，Bool 只兼容自身。
    # 检查内容：移除 Any 顶类型分支后，正常数值子类型逻辑仍保持正确。
    # 论文对应：Table 2 表达式类型前提所使用的基础类型兼容判断。
    def test_numeric_subtyping_remains_directional(self) -> None:
        """数值提升保持单向，且不存在 Any 形式的无条件接收类型。"""

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


if __name__ == "__main__":
    unittest.main()
