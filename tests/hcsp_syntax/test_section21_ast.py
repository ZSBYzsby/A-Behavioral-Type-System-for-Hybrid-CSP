r"""HCSP Section 2.1 抽象语法树逐产生式测试。

本文件只检查语法，不调用类型检查器。

测试内容
--------
1. 节点种类必须恰好等于论文的 ``E / P / S`` 产生式，其中内部
   选择使用与论文二元选择+顺序组合等价的三元规范形；
2. 每个节点的子项必须属于正确语法范畴；
3. E、P、S 的继承关系和跨层拒绝边界；
4. 便捷类方法只能展开成项目规范节点，不能引入新的 AST 种类；
5. ODE/Mu 批注作为字段存在，但不改变 Section 2.1 节点库存。
6. 通道名称必须满足与变量相同的标识符词法规则，非法名称在 AST 边界拒绝。
7. ``ODE.wait(d)`` 只展开为 ODE/Sequence/Skip，并使用自动局部时钟。
8. ``HCSP``、``Process`` 和 ``EventReaction`` 抽象范畴不能被直接实例化。

论文对应
--------
逐项对应 Section 2.1 的事件反应 ``E``、顺序进程 ``P`` 和系统 ``S`` 文法；
``InternalChoice(P, P', Q)`` 是 ``(P \sqcup P');Q`` 的唯一规范 AST；
``ODEAnnotation`` 与 ``RecursionAnnotation`` 对应 Section 4.2/4.3 的批注扩展。
"""

from __future__ import annotations

import math
from fractions import Fraction
import unittest

import hcsp_typechecker as public_api
import hcsp_typechecker.hcsp_process_ast as process_ast
from hcsp_typechecker import (
    Assert,
    Assign,
    Channel,
    EmptyEvent,
    EventChoice,
    EventReaction,
    Expr,
    HCSP,
    If,
    InputChannel,
    InternalChoice,
    Literal,
    Mu,
    ODE,
    ODEAnnotation,
    ODELocalClock,
    OutputChannel,
    Parallel,
    Process,
    RecursionAnnotation,
    Sequence,
    Skip,
    Var,
    Variable,
)


EXPECTED_EVENT_NODES = {"EmptyEvent", "EventChoice"}
EXPECTED_PROCESS_NODES = {
    "Skip",
    "Assign",
    "Assert",
    "InputChannel",
    "OutputChannel",
    "If",
    "ODE",
    "Sequence",
    "InternalChoice",
    "Var",
    "Mu",
}
EXPECTED_SYSTEM_ONLY_NODES = {"Parallel"}


def assert_event_reaction(test: unittest.TestCase, event: EventReaction) -> None:
    """递归检查一个对象是否只使用论文的事件反应产生式 ``E``。"""

    test.assertIsInstance(event, EventReaction)
    test.assertNotIsInstance(event, HCSP)
    if isinstance(event, EmptyEvent):
        return
    test.assertIsInstance(event, EventChoice)
    test.assertIsInstance(event.communication, (InputChannel, OutputChannel))
    assert_process(test, event.continuation)
    assert_event_reaction(test, event.alternative)


def assert_process(test: unittest.TestCase, process: Process) -> None:
    """递归检查一个对象是否只使用论文的顺序进程产生式 ``P``。"""

    test.assertIsInstance(process, Process)
    test.assertIsInstance(process, HCSP)
    test.assertNotIsInstance(process, Parallel)

    if isinstance(process, (Skip, Var)):
        return
    if isinstance(process, Assign):
        test.assertIsInstance(process.target, Variable)
        test.assertIsInstance(process.expression, Expr)
        return
    if isinstance(process, Assert):
        test.assertIsInstance(process.condition, Expr)
        return
    if isinstance(process, InputChannel):
        test.assertTrue(process.targets)
        test.assertTrue(
            all(isinstance(target, Variable) for target in process.targets)
        )
        return
    if isinstance(process, OutputChannel):
        test.assertTrue(process.payloads)
        test.assertTrue(
            all(isinstance(payload, Expr) for payload in process.payloads)
        )
        return
    if isinstance(process, If):
        test.assertIsInstance(process.condition, Expr)
        assert_process(test, process.then_branch)
        assert_process(test, process.else_branch)
        return
    if isinstance(process, ODE):
        for variable, derivative in process.eqs:
            test.assertIsInstance(variable, str)
            test.assertIsInstance(derivative, Expr)
        test.assertIsInstance(process.constraint, Expr)
        test.assertIsInstance(process.annotation, ODEAnnotation)
        test.assertIsInstance(process.annotation.safety, Expr)
        test.assertTrue(
            isinstance(process.annotation.delay, (Expr, float))
        )
        test.assertIsInstance(process.local_clock, ODELocalClock)
        test.assertEqual(process.local_clock.initial_value, Literal(0))
        test.assertEqual(process.local_clock.derivative, Literal(1))
        if process.local_clock_deadline is not None:
            test.assertIsInstance(process.local_clock_deadline, Literal)
        assert_event_reaction(test, process.interrupts)
        return
    if isinstance(process, Sequence):
        assert_process(test, process.first)
        assert_process(test, process.second)
        return
    if isinstance(process, InternalChoice):
        assert_process(test, process.left)
        assert_process(test, process.right)
        assert_process(test, process.continuation)
        return
    if isinstance(process, Mu):
        test.assertIsInstance(process.variable, str)
        test.assertIsInstance(process.annotation, RecursionAnnotation)
        test.assertIsInstance(process.annotation.invariant, Expr)
        assert_process(test, process.body)
        return
    test.fail(f"Unsupported Process subclass escaped grammar audit: {type(process)!r}")


def assert_system(test: unittest.TestCase, system: HCSP) -> None:
    """递归检查一个对象是否符合 ``S ::= P | S || S'``。"""

    test.assertIsInstance(system, HCSP)
    if isinstance(system, Process):
        assert_process(test, system)
        return
    test.assertIsInstance(system, Parallel)
    assert_system(test, system.left)
    assert_system(test, system.right)


class Section21NodeInventoryTests(unittest.TestCase):
    """保证项目不会增加或遗漏 Section 2.1 的语法节点。"""

    # 测试输入：分别直接调用 HCSP()、Process() 和 EventReaction()。
    # 预期行为：三个抽象语法范畴都在构造边界抛出 TypeError。
    # 检查内容：防止只有 get_vars 占位实现、却能生成无论文产生式的裸节点。
    # 论文对应：Section 2.1 的 E/P/S 是语法范畴，只有列出的产生式才是节点。
    def test_abstract_process_categories_cannot_be_instantiated(self) -> None:
        """E、P、S 的 Python 分类基类本身不构成合法 AST 节点。"""

        for abstract_class in (HCSP, Process, EventReaction):
            with self.subTest(abstract_class=abstract_class.__name__):
                with self.assertRaises(TypeError):
                    abstract_class()

    # 测试输入：EventReaction 的直接子类集合。
    # 预期行为：集合恰为 EmptyEvent 与 EventChoice，无多余事件节点。
    # 检查内容：比较类名全集，不把文件路径等非语义实现细节当作测试目标。
    # 论文对应：Section 2.1 的 ``E ::= empty | (...) \Box E``。
    def test_event_node_inventory_is_exact(self) -> None:
        """事件节点集合必须恰好是 empty、输入选择和输出选择所需节点。"""

        nodes = EventReaction.__subclasses__()
        actual = {node.__name__ for node in nodes}
        self.assertEqual(actual, EXPECTED_EVENT_NODES)

    # 测试输入：Process 的全部直接子类集合。
    # 预期行为：集合恰为论文列出的十一种 P 构造。
    # 检查内容：锁定进程节点库存，不约束未来等价的内部文件组织调整。
    # 论文对应：Section 2.1 的完整 ``P ::= ...`` 产生式列表。
    def test_process_node_inventory_is_exact(self) -> None:
        """顺序进程节点集合必须恰好对应论文列出的十一种构造。"""

        nodes = Process.__subclasses__()
        actual = {node.__name__ for node in nodes}
        self.assertEqual(actual, EXPECTED_PROCESS_NODES)

    # 测试输入：HCSP 的直接子类中除 Process 外的节点。
    # 预期行为：系统层独有节点只有 Parallel。
    # 检查内容：确认没有把事件或其他构造提升为系统层 S。
    # 论文对应：Section 2.1 的 ``S ::= P | S \parallel S'``。
    def test_system_only_node_inventory_is_exact(self) -> None:
        """除 Process 外，系统层只能额外包含二元 Parallel。"""

        nodes = [node for node in HCSP.__subclasses__() if node is not Process]
        actual = {node.__name__ for node in nodes}
        self.assertEqual(actual, EXPECTED_SYSTEM_ONLY_NODES)

    # 测试输入：公共包导出的全部 EventReaction/HCSP 具体子类。
    # 预期行为：恰好等于当前论文 E/P/S 具体节点集合，没有遗漏或额外节点。
    # 检查内容：按类型层次正向检查完整公开库存。
    # 论文对应：公共构造接口严格对应 Section 2.1 的 E、P、S 产生式。
    def test_public_concrete_ast_inventory_matches_section21(self) -> None:
        """公开 AST 节点集合应由当前论文文法正向、完整地定义。"""

        abstract_nodes = {EventReaction, Process, HCSP}
        actual = {
            name
            for name, value in vars(public_api).items()
            if isinstance(value, type)
            and value not in abstract_nodes
            and (
                issubclass(value, EventReaction)
                or issubclass(value, HCSP)
            )
        }
        expected = (
            EXPECTED_EVENT_NODES
            | EXPECTED_PROCESS_NODES
            | EXPECTED_SYSTEM_ONLY_NODES
        )
        self.assertEqual(actual, expected)


class Section21EventGrammarTests(unittest.TestCase):
    """逐项测试 ``E ::= empty | input-choice | output-choice``。"""

    # 测试输入：无参数 EmptyEvent 节点。
    # 预期行为：递归 E 验证器接受它，且它不属于 HCSP 系统。
    # 检查内容：核对事件递归的唯一终止产生式。
    # 论文对应：Section 2.1 的 ``E ::= empty``。
    def test_empty_event_production(self) -> None:
        """``EmptyEvent`` 精确表示事件反应的 empty 产生式。"""

        assert_event_reaction(self, EmptyEvent())

    # 测试输入：输入事件分支后递归连接一个输出事件分支。
    # 预期行为：整棵结构由 EventChoice 递归并以 EmptyEvent 结尾。
    # 检查内容：递归检查通信前缀、P continuation 和 E alternative。
    # 论文对应：Section 2.1 的两种 ``(ch★ -> P) \Box E`` 产生式。
    def test_recursive_input_and_output_choice_productions(self) -> None:
        """输入与输出事件分支递归链接，并最终以 EmptyEvent 收尾。"""

        reaction = EventChoice(
            InputChannel("sense", "x"),
            Assign("x", "x + 1"),
            EventChoice(
                OutputChannel("ack", 0),
                Skip(),
                EmptyEvent(),
            ),
        )
        assert_event_reaction(self, reaction)

    # 测试输入：EventChoice.of 的两个输入/输出分支便捷参数。
    # 预期行为：展开为两层 EventChoice 和一个 EmptyEvent。
    # 检查内容：核对右递归形状并运行独立 E 语法验证器。
    # 论文对应：类方法只展开 Section 2.1 的二元 ``\Box`` 文法。
    def test_event_choice_class_method_builds_only_recursive_e_nodes(self) -> None:
        """EventChoice.of 只生成 EventChoice/EmptyEvent 递归树。"""

        self.assertIsInstance(EventChoice.of(), EmptyEvent)
        reaction = EventChoice.of(
            (InputChannel("left", "x"), Skip()),
            (OutputChannel("right", 1), Assign("y", 0)),
        )
        assert_event_reaction(self, reaction)
        self.assertIsInstance(reaction.alternative, EventChoice)
        self.assertIsInstance(reaction.alternative.alternative, EmptyEvent)

    # 测试输入：把赋值 ``x := 1`` 放在事件分支箭头之前。
    # 预期行为：EventChoice 构造器抛出 TypeError。
    # 检查内容：证明事件守卫只允许 InputChannel/OutputChannel。
    # 论文对应：扩展后的 E 前缀只能是多标量输入或输出通信。
    def test_event_choice_rejects_noncommunication_prefix(self) -> None:
        """事件分支前缀不能是赋值、断言或其他非通信进程。"""

        with self.assertRaises(TypeError):
            EventChoice(Assign("x", 1), Skip())  # type: ignore[arg-type]

    # 测试输入：分别把 EmptyEvent 和 Parallel 放在事件箭头后。
    # 预期行为：两种非 P continuation 都被 TypeError 拒绝。
    # 检查内容：覆盖 E/P 和 S/P 两个跨范畴错误。
    # 论文对应：事件产生式箭头后必须严格为顺序进程 ``P``。
    def test_event_choice_rejects_nonprocess_continuation(self) -> None:
        """事件箭头后的 continuation 必须属于 P，不能是 E 或 S||S'。"""

        with self.assertRaises(TypeError):
            EventChoice(InputChannel("c", "x"), EmptyEvent())  # type: ignore[arg-type]
        with self.assertRaises(TypeError):
            EventChoice(
                InputChannel("c", "x"),
                Parallel(Skip(), Skip()),
            )  # type: ignore[arg-type]

    # 测试输入：把普通 Skip 作为 EventChoice 的 alternative。
    # 预期行为：构造器抛出 TypeError，拒绝以 P 替代递归 E。
    # 检查内容：锁定方框选择右项的事件反应范畴。
    # 论文对应：``(ch★ -> P) \Box E`` 的右项必须继续属于 E。
    def test_event_choice_rejects_process_as_alternative(self) -> None:
        """方框选择右侧必须递归为 E，不能放入普通进程 P。"""

        with self.assertRaises(TypeError):
            EventChoice(InputChannel("c", "x"), Skip(), Skip())  # type: ignore[arg-type]


class Section21ProcessGrammarTests(unittest.TestCase):
    """逐项测试 Section 2.1 的所有顺序进程产生式。"""

    # 测试输入：Skip 到 Mu 的十一种代表性 Process 实例。
    # 预期行为：每个实例都由独立递归验证器判为合法 P。
    # 检查内容：覆盖所有原子/复合节点及 ODE、递归批注字段类型。
    # 论文对应：Section 2.1 的完整 P 文法和 Section 4.2/4.3 批注。
    def test_all_atomic_and_compound_process_productions(self) -> None:
        """每种 P 产生式都能构造，并通过独立递归语法验证器。"""

        processes = (
            Skip(),
            Assign("x", "x + 1"),
            Assert("x >= 0"),
            InputChannel("in", "x"),
            OutputChannel("out", "x"),
            If("x >= 0", Assign("x", 1), Assign("x", -1)),
            ODE(
                [("x", 1)],
                "x <= 10",
                EventChoice.of((InputChannel("stop", "u"), Skip())),
                annotation=ODEAnnotation(delay=math.inf),
            ),
            Sequence(Assign("x", 0), Skip()),
            InternalChoice(Assign("x", 1), Assign("x", 2)),
            Var("X"),
            Mu("X", Sequence(InputChannel("tick", "u"), Var("X"))),
        )
        for process in processes:
            with self.subTest(node=type(process).__name__):
                assert_process(self, process)

    # 测试输入：多槽、单槽简写、空参数表、重复输入目标和缺参通信调用。
    # 预期行为：AST 始终保存标量元组；空表、重复目标和缺参均被拒绝。
    # 检查内容：通信列表不生成 TupleExpr，每个分量仍是 Variable/Expr。
    # 论文对应：按协作者确认扩展为 ``ch?(x1,...,xn)``/``ch!(e1,...,en)``，n >= 1。
    def test_communication_requires_explicit_target_and_payload(self) -> None:
        """多标量通信必须具有非空且形状合法的参数序列。"""

        input_process = InputChannel("stop", ("u", "ready"))
        output_process = OutputChannel("stop", (0, "ready"))
        self.assertEqual(
            input_process.targets,
            (Variable("u"), Variable("ready")),
        )
        self.assertEqual(
            output_process.payloads,
            (Literal(0), Variable("ready")),
        )
        self.assertEqual(InputChannel("one", "x").targets, (Variable("x"),))
        self.assertEqual(OutputChannel("one", 1).payloads, (Literal(1),))
        assert_process(self, input_process)
        assert_process(self, output_process)
        with self.assertRaisesRegex(ValueError, "at least one target"):
            InputChannel("stop", ())
        with self.assertRaisesRegex(ValueError, "must be distinct"):
            InputChannel("stop", ("u", "u"))
        with self.assertRaisesRegex(ValueError, "at least one payload"):
            OutputChannel("stop", ())
        with self.assertRaises(TypeError):
            OutputChannel("stop", ((1, 2),))
        with self.assertRaises(TypeError):
            InputChannel("stop")  # type: ignore[call-arg]
        with self.assertRaises(TypeError):
            OutputChannel("stop")  # type: ignore[call-arg]

    # 测试输入：合法 ASCII/Unicode 标识符，以及空白、标点、数字开头等非法名称。
    # 预期行为：合法名称原样保留；三个通道构造入口统一拒绝所有非法名称。
    # 检查内容：锁定通道名与 Variable 相同的 str.isidentifier() 词法边界。
    # 论文对应：Section 2.1 的 ch 是通道标识符，而不是任意非空字符串。
    def test_communication_enforces_identifier_channel_names(self) -> None:
        """通道名必须满足与变量名相同的 Python 标识符规则。"""

        for name in ("channel", "channel_1", "_private", "通道_1"):
            with self.subTest(valid=name):
                self.assertEqual(Channel(name).name, name)
                self.assertEqual(InputChannel(name, "x").channel.name, name)
                self.assertEqual(OutputChannel(name, 0).channel.name, name)

        invalid_names = (
            "",
            " ",
            "\t",
            "\n",
            " channel",
            "channel ",
            "1channel",
            "a-b",
            "a.b",
            "a/b",
            "a\nb",
        )
        for name in invalid_names:
            with self.subTest(name=repr(name)):
                with self.assertRaisesRegex(ValueError, "Invalid channel name"):
                    Channel(name)
                with self.assertRaisesRegex(ValueError, "Invalid channel name"):
                    InputChannel(name, "x")
                with self.assertRaisesRegex(ValueError, "Invalid channel name"):
                    OutputChannel(name, 0)

    # 测试输入：合法二元 If，以及缺失/多余参数、E 分支、Parallel 分支。
    # 预期行为：合法节点保留两个 P；四种非法调用均被拒绝。
    # 检查内容：同时覆盖参数个数和两个分支的语法范畴。
    # 论文对应：``if B then P else P'`` 是严格二元进程产生式。
    def test_if_is_binary_and_requires_two_process_branches(self) -> None:
        """条件语法只能是一个 B、一个 then P 和一个 else P'。"""

        node = If(True, Skip(), Assign("x", 1))
        self.assertIsInstance(node.then_branch, Process)
        self.assertIsInstance(node.else_branch, Process)
        with self.assertRaises(TypeError):
            If(True, Skip())  # type: ignore[call-arg]
        with self.assertRaises(TypeError):
            If(True, Skip(), Skip(), Skip())  # type: ignore[call-arg]
        with self.assertRaises(TypeError):
            If(True, Skip(), EmptyEvent())  # type: ignore[arg-type]
        with self.assertRaises(TypeError):
            If(True, Parallel(Skip(), Skip()), Skip())  # type: ignore[arg-type]

    # 测试输入：空中断 ODE、缺失批注、P 中断、错误批注和非二元方程项。
    # 预期行为：合法项补 EmptyEvent；其余分别抛 ValueError/TypeError。
    # 检查内容：核对 E 范畴、ODEAnnotation 必填字段和方程向量的结构边界。
    # 论文对应：Section 2.1 的 ODE/E 及 Section 4.3 的 safety/delay 批注。
    def test_ode_requires_event_reaction_interrupts(self) -> None:
        """连续演化要求合法 E 和独立 ODEAnnotation。"""

        without_interrupt = ODE(
            [("x", 1)],
            True,
            annotation=ODEAnnotation(delay=1),
        )
        self.assertIsInstance(without_interrupt.interrupts, EmptyEvent)
        self.assertIsInstance(without_interrupt.annotation, ODEAnnotation)
        with self.assertRaises(ValueError):
            ODE([("x", 1)], True)
        with self.assertRaises(TypeError):
            ODE(
                [("x", 1)],
                True,
                Skip(),
                annotation=ODEAnnotation(delay=1),
            )  # type: ignore[arg-type]
        with self.assertRaises(TypeError):
            ODE([("x", 1)], True, annotation=True)  # type: ignore[arg-type]
        with self.assertRaisesRegex(TypeError, r"equation 0"):
            ODE([("x", 1, 2)], True, annotation=ODEAnnotation(delay=1))  # type: ignore[list-item]
        with self.assertRaisesRegex(TypeError, r"equations must be an iterable"):
            ODE(None, True, annotation=ODEAnnotation(delay=1))  # type: ignore[arg-type]

    # 测试输入：合法 Assign; Skip、缺失/多余参数，以及 E/Parallel 混入左右项。
    # 预期行为：合法 Sequence 通过；错误元数和跨层组合均抛 TypeError。
    # 检查内容：检查固定二元形状及左右项都必须属于 Process。
    # 论文对应：Section 2.1 的二元顺序产生式 ``P; P'``。
    def test_sequence_is_binary_p_composition(self) -> None:
        """Sequence 的左右项都必须是 P，不能接受 E 或并行系统。"""

        node = Sequence(Assign("x", 1), Skip())
        assert_process(self, node)
        with self.assertRaises(TypeError):
            Sequence(Skip())  # type: ignore[call-arg]
        with self.assertRaises(TypeError):
            Sequence(Skip(), Skip(), Skip())  # type: ignore[call-arg]
        with self.assertRaises(TypeError):
            Sequence(EmptyEvent(), Skip())  # type: ignore[arg-type]
        with self.assertRaises(TypeError):
            Sequence(Parallel(Skip(), Skip()), Skip())  # type: ignore[arg-type]
        with self.assertRaises(TypeError):
            Sequence(Skip(), EmptyEvent())  # type: ignore[arg-type]

    # 测试输入：显式 ``(Skip \sqcup Assign); Assert``、缺省后继以及
    #           错误元数及 E/Parallel 混入三个 Process 字段的非法情况。
    # 预期行为：显式三元节点保存公共后继；二元调用自动补 Skip。
    # 检查内容：确认三个字段都只能保存 P。
    # 论文对应：``(P \sqcup P');Q`` 与二元选择+顺序组合等价。
    def test_internal_choice_is_ternary_p_composition(self) -> None:
        """InternalChoice 始终保存两个分支和一个公共后继。"""

        node = InternalChoice(Skip(), Assign("x", 1), Assert(True))
        assert_process(self, node)
        self.assertIsInstance(node.continuation, Assert)
        defaulted = InternalChoice(Skip(), Skip())
        self.assertIsInstance(defaulted.continuation, Skip)
        with self.assertRaisesRegex(ValueError, "owns its common continuation"):
            Sequence(defaulted, Assert(True))
        normalized = Sequence.of(defaulted, Assert(True))
        self.assertIsInstance(normalized, InternalChoice)
        self.assertIsInstance(normalized.continuation, Assert)
        with self.assertRaises(TypeError):
            InternalChoice(Skip())  # type: ignore[call-arg]
        with self.assertRaises(TypeError):
            InternalChoice(Skip(), Skip(), Skip(), Skip())  # type: ignore[call-arg]
        with self.assertRaises(TypeError):
            InternalChoice(EmptyEvent(), Skip())  # type: ignore[arg-type]
        with self.assertRaises(TypeError):
            InternalChoice(Skip(), Parallel(Skip(), Skip()))  # type: ignore[arg-type]
        with self.assertRaises(TypeError):
            InternalChoice(Skip(), Skip(), EmptyEvent())  # type: ignore[arg-type]

    # 测试输入：带不变量的合法 Mu，以及非法变量名、E/S body、错误批注。
    # 预期行为：合法递归通过；四类构造错误在 AST 边界被拒绝。
    # 检查内容：核对变量形状、P body 和 RecursionAnnotation 字段类型。
    # 论文对应：Section 2.1 ``mu X.P`` 与 Section 4.3 的 X_phi 批注。
    def test_mu_binds_one_process_variable_and_one_process_body(self) -> None:
        """Mu 只实现带边界批注的 ``mu X_phi.P``。"""

        node = Mu(
            "X",
            Sequence(InputChannel("c", "x"), Var("X")),
            annotation=RecursionAnnotation("y >= 0"),
        )
        assert_process(self, node)
        with self.assertRaises(ValueError):
            Mu("not a name", Skip())
        with self.assertRaises(TypeError):
            Mu("X", EmptyEvent())  # type: ignore[arg-type]
        with self.assertRaises(TypeError):
            Mu("X", Parallel(Skip(), Skip()))  # type: ignore[arg-type]
        with self.assertRaises(TypeError):
            Mu("X", Skip(), annotation=True)  # type: ignore[arg-type]

    # 测试输入：Sequence.of 三项和带 continuation 的 InternalChoice.of。
    # 预期行为：顺序仍右结合；多分支选择的最外层保存公共后继。
    # 检查内容：检查递归字段以及零项、单项和多项边界。
    # 论文对应：多分支辅助构造仍只使用同一 InternalChoice 节点类。
    def test_nary_class_methods_expand_to_canonical_process_trees(self) -> None:
        """多项顺序右结合，多分支选择使用三元规范节点。"""

        self.assertIsInstance(Sequence.of(), Skip)
        only = Assign("only", 0)
        self.assertIs(Sequence.of(only), only)
        self.assertIs(InternalChoice.of(only), only)
        with self.assertRaises(ValueError):
            InternalChoice.of()
        sequential = Sequence.of(Assign("x", 0), Assert(True), Skip())
        choice = InternalChoice.of(
            Assign("x", 0),
            Assign("x", 1),
            Skip(),
            continuation=Assert(True),
        )
        self.assertIsInstance(sequential, Sequence)
        self.assertIsInstance(sequential.second, Sequence)
        self.assertIsInstance(choice, InternalChoice)
        self.assertIsInstance(choice.right, InternalChoice)
        self.assertIsInstance(choice.continuation, Assert)
        assert_process(self, sequential)
        assert_process(self, choice)

    # 测试输入：``ODE.wait("1 / 2")`` 以及包级、模块级 ODE 类。
    # 预期行为：得到 ODE; skip 二元树，ODE 自动时钟截止值为精确 Fraction(1,2)。
    # 检查内容：确认没有 Wait 节点，用户方程为空，隐藏时钟仍固定从 0 以速率 1 演化。
    # 论文对应：Section 2.1 的 ``wait(d) := <dot(t)=1 & t<d>``，t 为局部时钟。
    def test_wait_class_method_expands_to_core_ode_sequence(self) -> None:
        """ODE.wait(d) 应只生成使用自动局部时钟的核心 AST。"""

        self.assertIs(process_ast.ODE, ODE)
        self.assertIs(public_api.ODE, ODE)
        waiting = ODE.wait("1 / 2")

        self.assertIsInstance(waiting, Sequence)
        self.assertIsInstance(waiting.first, ODE)
        self.assertIsInstance(waiting.second, Skip)
        self.assertEqual(waiting.first.eqs, ())
        self.assertEqual(waiting.first.constraint, Literal(True))
        self.assertIsInstance(waiting.first.interrupts, EmptyEvent)
        self.assertEqual(waiting.first.annotation.safety, Literal(True))
        self.assertEqual(waiting.first.annotation.delay, Literal(Fraction(1, 2)))
        self.assertEqual(
            waiting.first.local_clock_deadline,
            Literal(Fraction(1, 2)),
        )
        self.assertEqual(waiting.first.local_clock.initial_value, Literal(0))
        self.assertEqual(waiting.first.local_clock.derivative, Literal(1))
        assert_process(self, waiting)

    # 测试输入：负数、符号量、Bool 和正无穷四类非法 wait 时长。
    # 预期行为：全部在语法糖构造边界抛出 ValueError。
    # 检查内容：有限合法值复用 ODE delay 规范化；额外拒绝 ODE 可接受的 infinity。
    # 论文对应：wait(d) 定义要求 d 属于有限的非负实数，本项目再限制为精确有理数。
    def test_wait_requires_a_finite_non_negative_rational_duration(self) -> None:
        """ODE.wait(d) 不接受负值、符号时长、Bool 或正无穷。"""

        for duration in (-1, "d", True, math.inf):
            with self.subTest(duration=duration):
                with self.assertRaises(ValueError):
                    ODE.wait(duration)

    # 测试输入：在方程右端、演化域和 safety 中直接读取 t，并尝试把 t 写在方程左端。
    # 预期行为：前三处的 t 绑定自动时钟且不进入 get_vars；方程左端 t 被拒绝。
    # 检查内容：核对固定名称/初值/导数、两个 ODE 时钟的新鲜性以及后继作用域边界。
    # 论文对应：Table 2 在 ODE 证明前提中使用每个 ODE 独占的新鲜局部 t。
    def test_ode_binds_the_automatic_local_clock_name_t(self) -> None:
        """ODE 公式可直接读取局部 t，但不能声明 t' 或把 t 泄漏到后继。"""

        first = ODE(
            [("x", "t + 1")],
            "t <= 1",
            annotation=ODEAnnotation(safety="x >= t", delay=1),
        )
        second = ODE([], True, annotation=ODEAnnotation(safety=True, delay=2))

        self.assertEqual(first.get_vars(), {"x"})
        self.assertEqual(first.local_clock.name, "t")
        self.assertEqual(first.local_clock.initial_value, Literal(0))
        self.assertEqual(first.local_clock.derivative, Literal(1))
        self.assertIsNot(first.local_clock, second.local_clock)
        self.assertEqual(
            Sequence(first, Assert("t >= 0")).get_vars(),
            {"x", "t"},
        )
        with self.assertRaisesRegex(ValueError, "reserved.*local clock"):
            ODE(
                [("t", 1)],
                True,
                annotation=ODEAnnotation(delay=1),
            )
        assert_process(self, first)


class Section21SystemGrammarTests(unittest.TestCase):
    """验证 ``S ::= P | S || S'`` 及其跨层边界。"""

    # 测试输入：一个 Assign 顺序进程。
    # 预期行为：系统验证器直接接受该 Process 作为 S。
    # 检查内容：确认 Process 继承 HCSP，且无需额外包装节点。
    # 论文对应：Section 2.1 的系统产生式 ``S ::= P``。
    def test_process_is_a_system(self) -> None:
        """任意 P 都可以直接作为系统 S。"""

        assert_system(self, Assign("x", 1))

    # 测试输入：Assign 与嵌套 Parallel 构成的二层系统。
    # 预期行为：递归系统验证器接受全部左右分量。
    # 检查内容：验证 Parallel 操作数属于 S，因而允许继续嵌套 Parallel。
    # 论文对应：Section 2.1 的递归 ``S ::= S \parallel S'``。
    def test_parallel_is_binary_and_recursively_accepts_systems(self) -> None:
        """Parallel 左右项是 S，因此允许嵌套二元并行。"""

        system = Parallel(
            Assign("x", 1),
            Parallel(OutputChannel("c", 0), Skip()),
        )
        assert_system(self, system)

    # 测试输入：分别把 EmptyEvent 放在 Parallel 左侧和右侧。
    # 预期行为：两种调用均抛 TypeError。
    # 检查内容：确认事件反应 E 不能冒充系统 S。
    # 论文对应：Section 2.1 将 E 与 S 定义为不同语法范畴。
    def test_parallel_rejects_event_reaction(self) -> None:
        """事件反应 E 不是系统 S，不能成为并行分量。"""

        with self.assertRaises(TypeError):
            Parallel(EmptyEvent(), Skip())  # type: ignore[arg-type]
        with self.assertRaises(TypeError):
            Parallel(Skip(), EmptyEvent())  # type: ignore[arg-type]

    # 测试输入：Skip、Assign、Output 三项 Parallel.of 便捷调用。
    # 预期行为：展开为右结合的两层 Parallel。
    # 检查内容：检查树形并递归验证每个叶子都属于系统 S。
    # 论文对应：多项便捷写法只展开二元 ``S \parallel S'``。
    def test_parallel_class_method_builds_only_binary_system_tree(self) -> None:
        """Parallel.of 展开成右结合二元 Parallel。"""

        with self.assertRaises(ValueError):
            Parallel.of(Skip())
        system = Parallel.of(Skip(), Assign("x", 1), OutputChannel("c", 0))
        self.assertIsInstance(system, Parallel)
        self.assertIsInstance(system.right, Parallel)
        assert_system(self, system)

    # 测试输入：Parallel 的一元和三元直接构造调用。
    # 预期行为：两种非二元调用都抛 TypeError。
    # 检查内容：锁定核心 AST 节点恰有 left/right 两个系统字段。
    # 论文对应：Section 2.1 的 Parallel 产生式是严格二元。
    def test_parallel_rejects_missing_or_extra_operands(self) -> None:
        """Parallel 必须精确包含 Section 2.1 规定的两个系统操作数。"""

        with self.assertRaises(TypeError):
            Parallel(Skip())  # type: ignore[call-arg]
        with self.assertRaises(TypeError):
            Parallel(Skip(), Skip(), Skip())  # type: ignore[call-arg]

    # 测试输入：由输入分支构造的 EventReaction。
    # 预期行为：对象属于 E，但既不属于 Process 也不属于 HCSP。
    # 检查内容：直接断言三种基类的继承隔离关系。
    # 论文对应：Section 2.1 分离定义事件反应 E、进程 P 和系统 S。
    def test_event_reaction_is_neither_process_nor_system(self) -> None:
        """E、P、S 的继承关系必须保持分离。"""

        event = EventChoice.of((InputChannel("c", "x"), Skip()))
        self.assertIsInstance(event, EventReaction)
        self.assertNotIsInstance(event, Process)
        self.assertNotIsInstance(event, HCSP)


if __name__ == "__main__":
    unittest.main()
