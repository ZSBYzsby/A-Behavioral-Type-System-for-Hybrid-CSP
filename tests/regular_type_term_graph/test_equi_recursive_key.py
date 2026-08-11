r"""等递归正规树状态键的回归测试。

测试内容
--------
1. ``mu t.T`` 与一次展开 ``T[mu t.T/t]`` 使用同一状态键。
2. 递归变量改名、冗余绑定和选择幂等不会改变正规树。
3. 通信方向、通道名与并行分量重数仍然能够区分状态。
4. 嵌套 De Bruijn 绑定被正确转换成有限循环项图。

论文对应
--------
这些测试不新增 Table 3 规则；它们只实现论文递归类型的等递归解释，使状态图
按同一棵无限正规树而不是有限 ``mu`` 语法的展开深度判重。
"""

from __future__ import annotations

import unittest

from hcsp_typechecker.backend.type_operational_semantics.regular_tree import (
    build_regular_type_term_graph,
    equi_recursive_equivalent,
    equi_recursive_state_key,
    normalized_type_from_state_key,
)
from hcsp_typechecker.data_structures.normalized_type_ast import (
    NormalizedConfigurationType,
    NormalizedMuType,
    normalize_type_ast,
)
from hcsp_typechecker.data_structures.regular_type_term_graph import (
    CanonicalRegularTypeNode,
    EquiRecursiveStateKey,
    RegularTypeNodeKind,
)
from hcsp_typechecker.data_structures.type_ast import (
    EmptyType,
    InfiniteDelayType,
    InputType,
    InternalChoiceType,
    MuType,
    OutputType,
    ParallelType,
    TypeVar,
    make_external_choice,
)


class EquiRecursiveStateKeyTests(unittest.TestCase):
    """检查有限项图确实编码所需的等递归正规树等价。"""

    # 测试输入：守卫递归类型及其按照 [P-mu] 展开一次后的规范类型。
    # 预期行为：两者的等递归状态键完全相同。
    # 检查内容：递归绑定被转换为循环边，展开深度不进入图节点身份。
    # 论文对应：递归类型按 mu t.T 与 T[mu t.T/t] 的等递归方程解释。
    def test_mu_type_equals_its_one_step_unfolding(self) -> None:
        """一次递归展开不会制造新的语义状态。"""

        loop = MuType(
            "loop",
            InfiniteDelayType(InputType("ch", TypeVar("loop"))),
        )
        folded = normalize_type_ast(loop)
        body = folded.components[0]
        self.assertIsInstance(body, NormalizedMuType)
        unfolded = normalize_type_ast(
            InfiniteDelayType(InputType("ch", loop))
        )
        unfolded_twice = normalize_type_ast(
            InfiniteDelayType(
                InputType("ch", InfiniteDelayType(InputType("ch", loop)))
            )
        )

        self.assertNotEqual(folded, unfolded)
        self.assertTrue(equi_recursive_equivalent(folded, unfolded))
        self.assertEqual(
            equi_recursive_state_key(folded),
            equi_recursive_state_key(unfolded),
        )
        self.assertEqual(
            equi_recursive_state_key(folded),
            equi_recursive_state_key(unfolded_twice),
        )

    # 测试输入：只在递归变量名称上不同的两个闭合递归类型。
    # 预期行为：二者产生相同最小项图和状态键。
    # 检查内容：原 Type AST 的绑定名称不会泄漏到正规树节点标签。
    # 论文对应：alpha-renaming 不改变递归类型含义。
    def test_alpha_renaming_does_not_change_the_key(self) -> None:
        """递归变量名不属于状态的可观察结构。"""

        left = normalize_type_ast(
            MuType("left", InfiniteDelayType(OutputType("tick", TypeVar("left"))))
        )
        right = normalize_type_ast(
            MuType("right", InfiniteDelayType(OutputType("tick", TypeVar("right"))))
        )

        self.assertEqual(
            equi_recursive_state_key(left),
            equi_recursive_state_key(right),
        )

    # 测试输入：外层和内层递归引用同时出现在内层外部选择 continuation 中。
    # 预期行为：两套 alpha-renaming 后的嵌套递归得到同一有限循环图。
    # 检查内容：De Bruijn index 0/1 分别回指内层和外层 binder，而不发生捕获。
    # 论文对应：嵌套 mu 的词法作用域与守卫递归约束。
    def test_nested_binders_resolve_without_capture(self) -> None:
        """嵌套递归的内外回边指向各自的正规项图节点。"""

        def nested(outer: str, inner: str) -> MuType:
            """按给定绑定名构造同时回指内层和外层的闭合递归类型。"""

            return MuType(
                outer,
                InfiniteDelayType(
                    InputType(
                        "enter",
                        MuType(
                            inner,
                            InfiniteDelayType(
                                make_external_choice(
                                    (
                                        InputType("again", TypeVar(inner)),
                                        OutputType("leave", TypeVar(outer)),
                                    )
                                )
                            ),
                        ),
                    )
                ),
            )

        left = normalize_type_ast(nested("outer", "inner"))
        right = normalize_type_ast(nested("x", "y"))

        key = equi_recursive_state_key(left)
        self.assertEqual(key, equi_recursive_state_key(right))
        self.assertGreaterEqual(len(key.nodes), 5)
        self.assertEqual(
            equi_recursive_state_key(normalized_type_from_state_key(key)),
            key,
        )

    # 测试输入：binder 未在递归体中出现的 mu 类型和其递归体本身。
    # 预期行为：无实际回边的冗余 mu 不改变正规树状态键。
    # 检查内容：项图只保存可观察构造，mu 不被作为独立标签节点。
    # 论文对应：等递归解释下无引用的 mu t.T 与 T 相等。
    def test_unused_mu_binder_is_semantically_transparent(self) -> None:
        """没有递归引用的绑定器不会留在最小项图中。"""

        body = InfiniteDelayType(InputType("ready", EmptyType()))
        wrapped = normalize_type_ast(MuType("unused", body))
        plain = normalize_type_ast(body)

        self.assertEqual(
            equi_recursive_state_key(wrapped),
            equi_recursive_state_key(plain),
        )

    # 测试输入：同一循环及其一次展开组成的二元内部选择。
    # 预期行为：分支在正规树等价后按幂等律折叠，结果等价于单独循环。
    # 检查内容：先做双模拟再做选择去重，避免结构规范化遗漏递归等价分支。
    # 论文对应：内部选择满足幂等律，且递归采用等递归解释。
    def test_choice_collapses_branches_equal_only_after_unfolding(self) -> None:
        """递归等价暴露出的重复选择分支会再次规范化。"""

        loop = MuType(
            "loop",
            InfiniteDelayType(InputType("a", TypeVar("loop"))),
        )
        unfolded = InfiniteDelayType(InputType("a", loop))
        choice = normalize_type_ast(InternalChoiceType((loop, unfolded)))
        plain = normalize_type_ast(loop)

        self.assertEqual(
            equi_recursive_state_key(choice),
            equi_recursive_state_key(plain),
        )

    # 测试输入：通信方向或通道名不同的三个递归协议。
    # 预期行为：三者状态键两两不同。
    # 检查内容：只忽略递归折叠差异，不忽略 Table 3 可观察的通信标签。
    # 论文对应：输入、输出及通道名决定可同步动作，必须保留。
    def test_observable_communication_labels_remain_distinct(self) -> None:
        """等递归商不会过度合并不同通信协议。"""

        input_a = normalize_type_ast(
            MuType("t", InfiniteDelayType(InputType("a", TypeVar("t"))))
        )
        input_b = normalize_type_ast(
            MuType("t", InfiniteDelayType(InputType("b", TypeVar("t"))))
        )
        output_a = normalize_type_ast(
            MuType("t", InfiniteDelayType(OutputType("a", TypeVar("t"))))
        )

        keys = {
            equi_recursive_state_key(input_a),
            equi_recursive_state_key(input_b),
            equi_recursive_state_key(output_a),
        }
        self.assertEqual(len(keys), 3)

    # 测试输入：一个循环分量、两个相同循环并行和附加 Empty 单位元的并行。
    # 预期行为：Empty 不改变键，但两个相同并行分量的重数不会丢失。
    # 检查内容：配置根是多重集而不是普通集合。
    # 论文对应：并行满足 Empty 单位元与交换律，但不满足幂等律。
    def test_parallel_roots_preserve_multiplicity_but_remove_empty(self) -> None:
        """配置正规化仅删除空单位元，不合并两个相同行为分量。"""

        loop = MuType(
            "t", InfiniteDelayType(InputType("request", TypeVar("t")))
        )
        single = normalize_type_ast(loop)
        with_empty = normalize_type_ast(ParallelType((loop, EmptyType())))
        doubled = normalize_type_ast(ParallelType((loop, loop)))

        self.assertEqual(
            equi_recursive_state_key(single),
            equi_recursive_state_key(with_empty),
        )
        self.assertNotEqual(
            equi_recursive_state_key(single),
            equi_recursive_state_key(doubled),
        )

    # 测试输入：一个 alpha-renamed 递归协议的规范配置。
    # 预期行为：构造项图中不出现 mu 或变量种类，仅由真实构造和循环边编码。
    # 检查内容：正规项图的数据结构边界与图判重设计保持一致。
    # 论文对应：mu 展开方程被编码为有限循环表示，而不是可观察动作。
    def test_term_graph_contains_no_mu_or_variable_nodes(self) -> None:
        """递归语法节点在有限项图中被消去。"""

        normalized = normalize_type_ast(
            MuType("t", InfiniteDelayType(InputType("ch", TypeVar("t"))))
        )

        graph = build_regular_type_term_graph(normalized)

        self.assertEqual(
            {node.kind for node in graph.nodes},
            {RegularTypeNodeKind.INFINITE_DELAY, RegularTypeNodeKind.INPUT},
        )

    # 测试输入：含嵌套递归、外部选择和并行重数的规范循环项图状态键。
    # 预期行为：为输出重建规范 AST 后，再构图得到完全相同的状态键。
    # 检查内容：项图到展示 AST 的单向重建不会改变等递归正规树或并行重数。
    # 论文对应：展示代表只编码同一个递归方程解，不参与 Table 3 状态身份。
    def test_display_ast_reconstructs_the_same_regular_tree(self) -> None:
        """项图展示代表必须往返保持规范状态键。"""

        loop = MuType(
            "loop",
            InfiniteDelayType(
                make_external_choice(
                    (
                        InputType("again", TypeVar("loop")),
                        OutputType("done", EmptyType()),
                    )
                )
            ),
        )
        original = normalize_type_ast(ParallelType((loop, loop)))
        key = equi_recursive_state_key(original)

        displayed = normalized_type_from_state_key(key)

        self.assertEqual(equi_recursive_state_key(displayed), key)

    # 测试输入：把通信节点错误地直接作为配置根的手工项图。
    # 预期行为：数据结构构造时立即拒绝，不把类别错误拖到 Table 3 后端。
    # 检查内容：项图根必须属于 process type，而不能属于 angelic type。
    # 论文对应：T 与 A 是不同语法类别，有限图表示仍必须保持该产生式边界。
    def test_regular_graph_rejects_angelic_configuration_roots(self) -> None:
        """循环项图自身负责维护过程/angelic 双类别不变量。"""

        with self.assertRaisesRegex(ValueError, "process-type"):
            EquiRecursiveStateKey(
                (0,),
                (
                    CanonicalRegularTypeNode(
                        RegularTypeNodeKind.INPUT,
                        "ch",
                        (1,),
                    ),
                    CanonicalRegularTypeNode(RegularTypeNodeKind.EMPTY),
                ),
            )


if __name__ == "__main__":
    unittest.main()
