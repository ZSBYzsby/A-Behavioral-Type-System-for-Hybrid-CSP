r"""原 Type AST 到 Table 3 规范化 Type AST 的结构回归测试。

测试内容
--------
1. 并行按结合/交换律和 Empty 单位元规范化，但保留重复分量。
2. 内部选择按结合/交换/幂等律展平、排序和去重。
3. 外部选择按交换/幂等律排序去重，并保留不同 continuation。
4. ``mu`` 绑定改为 De Bruijn index，自由类型变量被拒绝。
5. 零时延和 bottom 等有操作语义意义的节点不会被提前化简。

论文对应
--------
规范化是 Table 3 状态空间的实现商结构；它不改变 Section 4.1 原 Type AST，也不
执行任何 Table 3 转移。选择采用本项目确认的多元 AC-idempotent 解释。
"""

from __future__ import annotations

from fractions import Fraction
import unittest

import hcsp_typechecker.data_structures.normalized_type_ast as normalized_api
from hcsp_typechecker.data_structures.normalized_type_ast import (
    NormalizedBoundTypeVar,
    NormalizedConfigurationType,
    NormalizedEmptyType,
    NormalizedExternalChoiceType,
    NormalizedFiniteDelayType,
    NormalizedInfiniteDelayType,
    NormalizedInputType,
    NormalizedInternalChoiceType,
    NormalizedMuType,
    NormalizedOutputType,
    TypeNormalizationError,
    normalize_type_ast,
)
from hcsp_typechecker.data_structures.type_ast import (
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


class NormalizedTypeConversionTests(unittest.TestCase):
    """锁定规范化树作为状态图键所需的全部结构等价。"""

    # 测试输入：顺序不同、嵌套不同且含 Empty 和两个相同分量的并行 Type AST。
    # 预期行为：两个输入得到同一规范根；Empty 被删，但重复非空分量保留。
    # 检查内容：并行结合律、交换律、单位元和非幂等性同时成立。
    # 论文对应：Table 3 中并行分量位置无语义，正常空行为不阻塞其他分量。
    def test_parallel_is_sorted_and_empty_is_only_a_unit(self) -> None:
        """并行配置规范成稳定、有重数的过程多重集合。"""

        first = FiniteDelayType(1, NoInterruptType(), EmptyType())
        second = InfiniteDelayType(NoInterruptType())
        left = ParallelType((second, EmptyType(), first, first))
        right = ParallelType((first, ParallelType((first, second))))

        normalized_left = normalize_type_ast(left)
        normalized_right = normalize_type_ast(right)

        self.assertEqual(normalized_left, normalized_right)
        self.assertEqual(len(normalized_left.components), 3)
        self.assertEqual(
            normalize_type_ast(ParallelType((EmptyType(), EmptyType()))),
            NormalizedConfigurationType((NormalizedEmptyType(),)),
        )

    # 测试输入：不同结合和排列方式且重复出现 A/B 的嵌套内部选择。
    # 预期行为：全部嵌套被展平，重复分支删除，结果按稳定结构顺序保存 A/B。
    # 检查内容：结合律、交换律、幂等律及单分支选择消除。
    # 论文对应：项目采用 Table 3 [P-sqcup] 的多元集合式内部选择解释。
    def test_internal_choice_is_flattened_sorted_and_idempotent(self) -> None:
        """二元编码差异不会进入规范化状态空间。"""

        a = FiniteDelayType(1, NoInterruptType(), EmptyType())
        b = FiniteDelayType(2, NoInterruptType(), EmptyType())
        nested = InternalChoiceType(
            (b, InternalChoiceType((a, b)), a)
        )

        normalized = normalize_type_ast(nested).components[0]

        self.assertIsInstance(normalized, NormalizedInternalChoiceType)
        self.assertEqual(len(normalized.branches), 2)
        duplicate = normalize_type_ast(InternalChoiceType((a, a)))
        self.assertIsInstance(duplicate.components[0], NormalizedFiniteDelayType)

    # 测试输入：外部选择含逆序的两个不同分支及一个完全重复输入分支。
    # 预期行为：完全重复分支被删除并稳定排序，不同 continuation 仍分别保留。
    # 检查内容：外部选择交换律/幂等律只作用于完整通信分支。
    # 论文对应：A 的多元通信选择不依赖书写位置，同事件不同后继仍是不同结果。
    def test_external_choice_is_sorted_and_exactly_deduplicated(self) -> None:
        """规范 angelic choice 以通信分支集合的唯一元组表示。"""

        first = InputType("ch", EmptyType())
        second = OutputType(
            "dh",
            FiniteDelayType(1, NoInterruptType(), EmptyType()),
        )
        value = InfiniteDelayType(ExternalChoiceType((second, first, first)))

        normalized = normalize_type_ast(value).components[0]

        self.assertIsInstance(normalized, NormalizedInfiniteDelayType)
        self.assertIsInstance(normalized.interrupts, NormalizedExternalChoiceType)
        self.assertEqual(len(normalized.interrupts.branches), 2)
        self.assertIsInstance(normalized.interrupts.branches[0], NormalizedInputType)
        self.assertIsInstance(normalized.interrupts.branches[1], NormalizedOutputType)

    # 测试输入：仅递归绑定变量名称不同的两个 mu，以及一个裸自由 TypeVar。
    # 预期行为：两个 mu 规范成相同 De Bruijn 树；自由变量抛规范化错误。
    # 检查内容：alpha 等价成为普通结构相等，规范图状态始终闭合。
    # 论文对应：[P-mu] 的等递归方程不依赖绑定变量的具体拼写。
    def test_recursive_names_become_de_bruijn_indices(self) -> None:
        """递归规范化消除绑定名并拒绝无绑定引用。"""

        left = MuType("t", InfiniteDelayType(InputType("ch", TypeVar("t"))))
        right = MuType("loop", InfiniteDelayType(InputType("ch", TypeVar("loop"))))

        normalized = normalize_type_ast(left)

        self.assertEqual(normalized, normalize_type_ast(right))
        root = normalized.components[0]
        self.assertIsInstance(root, NormalizedMuType)
        self.assertEqual(
            root.body.interrupts.continuation,
            NormalizedBoundTypeVar(0),
        )
        with self.assertRaises(TypeNormalizationError):
            normalize_type_ast(TypeVar("free"))

    # 测试输入：delay(0) 的正常空后继，以及规范化子包的导出命名空间。
    # 预期行为：零时延结点原样保存；不存在反向 denormalize 转换入口。
    # 检查内容：规范化只消除已确认等价，不抢先执行 timeout，也保持单向边界。
    # 论文对应：delay(0) 是 [P-triangleright] 的源状态而非结构重写规则。
    def test_zero_delay_is_retained_and_conversion_is_one_way(self) -> None:
        """操作语义步骤不会被错误塞进 AST 规范化过程。"""

        normalized = normalize_type_ast(
            FiniteDelayType(0, NoInterruptType(), EmptyType())
        )

        delay = normalized.components[0]
        self.assertIsInstance(delay, NormalizedFiniteDelayType)
        self.assertEqual(delay.duration, Fraction(0))
        self.assertFalse(hasattr(normalized_api, "denormalize_type_ast"))


if __name__ == "__main__":
    unittest.main()
