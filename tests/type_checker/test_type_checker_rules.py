r"""验证 TypeChecker 按用户 Type 递归核对项目实际规则。

测试内容
--------
1. Constructor 生成的离散、选择、递归、并行和 ODE Type 经规范语法写回后，
   Checker 均可逐规则接受；
2. 多元内部选择和多元外部中断按分支数量、顺序和通信方向逐项检查；
3. 错误通信分支、错误 delay 与已被证明器否证的公式前提均会失败；
4. 测试直接监视 TypeConstructor.construct，确保 Checker 不再通过“先构造再
   比较”实现；
5. 嵌套 T-If/T-sqcup 保留 Type 语法圆括号确定的分块，并且不允许交换分支。

论文对应
--------
覆盖 Table 2 的 T-End、T-Skip、T-Assign、T-Assert、T-If、T-sqcup、T-In、
T-Out、T-&、T-ODE、T-mu、T-X、T-sigma 与 T-||；具体公式和上下文变化遵循
项目 TypeConstructor 中已经实现并审计的算法化规则。
"""

from __future__ import annotations

import unittest
from unittest.mock import patch
from io import StringIO

from hcsp_typechecker import (
    HCSPTypeCheckingError,
    check_hcsp_type,
    construct_hcsp_type,
)
from hcsp_typechecker.backend.common import Verdict
from hcsp_typechecker.backend.type_checker import TypeCheckingRequest
from hcsp_typechecker.data_structures.runtime_context import Configuration
from hcsp_typechecker.data_structures.type_ast import InternalChoiceType
from hcsp_typechecker.frontend.type_checker_frontend import (
    parse_typechecking_source,
)
from hcsp_typechecker.frontend.type_syntax import format_type_source
from hcsp_typechecker.backend.type_checker import TypeChecker


_DISCRETE_SOURCE = """gamma(x: Int)
theta()
process {{x := 1; assert(x == 1)}}"""

_IF_SOURCE = """gamma(x: Int)
theta(a: channel(v: Int), b: channel(v: Int))
process {{if (x >= 0) {a!(x)} else {b!(x)}}}"""

_CHOICE_SOURCE = """gamma()
theta(a: channel(v: Int), b: channel(v: Int), c: channel(v: Int))
process {{choose {a!(0)} or {b!(0)} or {c!(0)}}}"""

_RECURSION_SOURCE = """gamma(x: Int)
theta(tick: channel(v: Int))
process {{x := 0; mu Loop invariant(x >= 0) {tick!(x); call Loop}}}"""

_PARALLEL_SOURCE = """gamma(x: Int)
theta(ch: channel(v: Int))
process {{ch!(1)}, {ch?(x)}}"""

_NESTED_IF_SOURCE = """gamma(x: Int)
theta(a: channel(v: Int), b: channel(v: Int), c: channel(v: Int))
process {{if (x >= 0) {choose {a!(0)} or {b!(0)}} else {c!(0)}}}"""

_NESTED_CHOICE_SOURCE = """gamma(x: Int)
theta(a: channel(v: Int), b: channel(v: Int), c: channel(v: Int))
process {{choose {if (x >= 0) {a!(0)} else {b!(0)}} or {c!(0)}}}"""

_INFINITE_ODE_SOURCE = """gamma()
theta(ch: channel(v: Int), reset: channel(v: Int))
process {{ode(
    flow(),
    domain(true),
    delay(inf),
    interrupt(on ch!(0) {skip}, on reset?(value) {skip})
)}}"""


class TypeDirectedRuleTests(unittest.TestCase):
    """逐类验证给定 Type 子树确实成为规则递归的目标。"""

    # 测试输入：赋值后断言、二元条件和三元内部选择三组离散源码。
    # 预期行为：Constructor 的规范 Type 写回后全部被 Checker 接受。
    # 检查内容：覆盖静默后继、二分支和多分支的 Type-directed 递归。
    # 论文对应：T-Assign、T-Assert、T-If、T-sqcup、T-Out 与 T-End。
    def test_constructor_roundtrip_covers_discrete_and_multiway_rules(self) -> None:
        """离散规则与多元选择的构造结果必须可被直接检查。"""

        for source in (_DISCRETE_SOURCE, _IF_SOURCE, _CHOICE_SOURCE):
            with self.subTest(source=source):
                constructed = construct_hcsp_type(source)
                checked = check_hcsp_type(
                    source + "\n" + format_type_source(constructed)
                )
                self.assertEqual(checked, constructed)

    # 测试输入：通信保护递归和一个输入/输出同步的并行系统。
    # 预期行为：Checker 接受 alpha 绑定后的 MuType 及有序 ParallelType 分量。
    # 检查内容：递归 TypeVar 不依赖 Constructor 的新鲜名称，并行严格逐分量。
    # 论文对应：T-mu、T-X、T-In、T-Out、T-sigma 与 T-||。
    def test_constructor_roundtrip_covers_recursion_and_parallel(self) -> None:
        """递归 alpha 绑定和并行分量均应按判断结构检查。"""

        for source in (_RECURSION_SOURCE, _PARALLEL_SOURCE):
            with self.subTest(source=source):
                constructed = construct_hcsp_type(source)
                checked = check_hcsp_type(
                    source + "\n" + format_type_source(constructed)
                )
                self.assertEqual(checked, constructed)

    # 测试输入：无穷 ODE，含两个有序通信中断分支且 safety/domain 均为 true。
    # 预期行为：无需外部 dL 后端即可检查 InfiniteDelayType 与多元 AngelicType。
    # 检查内容：事件分支按输出 ch、输入 reset 的顺序和方向逐项递归。
    # 论文对应：T-ODE 的无穷时延规则及多元 T-&。
    def test_constructor_roundtrip_covers_multiway_external_interrupts(self) -> None:
        """多元外部中断应按规范 angelic 分支逐项匹配。"""

        constructed = construct_hcsp_type(_INFINITE_ODE_SOURCE)
        checked = check_hcsp_type(
            _INFINITE_ODE_SOURCE + "\n" + format_type_source(constructed)
        )
        self.assertEqual(checked, constructed)

    # 测试输入：if 分支内含内部选择，以及内部选择分支内含 if 的两个嵌套源码。
    # 预期行为：Constructor 保留两层 InternalChoiceType，Checker 按每层元数接受。
    # 检查内容：规范 Type 文本用括号保存 2+1 的两层规则边界。
    # 论文对应：每层 T-If/T-sqcup 的子判断与当前括号块严格逐项对应。
    def test_constructor_roundtrip_preserves_nested_internal_choice_blocks(self) -> None:
        """嵌套选择的括号分块必须经 Constructor 和 Checker 无损往返。"""

        for source in (_NESTED_IF_SOURCE, _NESTED_CHOICE_SOURCE):
            with self.subTest(source=source):
                constructed = construct_hcsp_type(source)
                checked = check_hcsp_type(
                    source + "\n" + format_type_source(constructed)
                )
                self.assertEqual(checked, constructed)

    # 测试输入：上一个嵌套 if 的正确分块类型，但交换内层 a!/b! 分支。
    # 预期行为：Checker 在保留原括号结构的情况下拒绝给定 Type。
    # 检查内容：逐层匹配不采用内部选择交换律。
    # 论文对应：按用户要求，T-If/T-sqcup 的各子判断与 Type 分支顺序完全一致。
    def test_nested_choice_blocks_do_not_exchange_type_branches(self) -> None:
        """括号分块不得把交换后的类型分支重新排列成可接受顺序。"""

        constructed = construct_hcsp_type(_NESTED_IF_SOURCE)
        supplied = format_type_source(constructed)
        supplied = supplied.replace("a!", "__first__!", 1)
        supplied = supplied.replace("b!", "a!", 1)
        supplied = supplied.replace("__first__!", "b!", 1)
        with self.assertRaises(HCSPTypeCheckingError) as caught:
            check_hcsp_type(_NESTED_IF_SOURCE + "\n" + supplied)
        self.assertEqual(caught.exception.verdict, "false")
        self.assertIn("same channel", caught.exception.reason)

    # 测试输入：保持 a,b,c 叶子顺序不变，但把正确的 ``(a sqcup b),c`` 改为
    #           ``a,(b sqcup c)``。
    # 预期行为：Checker 因当前 T-If/T-sqcup 节点分块不符而拒绝。
    # 检查内容：括号不是可忽略的结合律装饰，而是递归规则的实际边界。
    # 论文对应：每个规则 premise 与用户指定的一个 Type 块一一对应。
    def test_nested_choice_rejects_different_parenthesized_grouping(self) -> None:
        """相同叶子顺序的另一种括号分组也不能通过检查。"""

        constructed = construct_hcsp_type(_NESTED_IF_SOURCE)
        self.assertIsInstance(constructed, InternalChoiceType)
        outer = constructed
        assert isinstance(outer, InternalChoiceType)
        self.assertIsInstance(outer.branches[0], InternalChoiceType)
        left = outer.branches[0]
        assert isinstance(left, InternalChoiceType)
        regrouped = InternalChoiceType(
            (
                left.branches[0],
                InternalChoiceType((left.branches[1], outer.branches[1])),
            )
        )

        with self.assertRaises(HCSPTypeCheckingError) as caught:
            check_hcsp_type(
                _NESTED_IF_SOURCE + "\n" + format_type_source(regrouped)
            )
        self.assertEqual(caught.exception.verdict, "false")
        self.assertIn("T-sqcup requires InternalChoiceType", caught.exception.reason)

    # 测试输入：三元内部选择的正确 Type，但把首个输出通道 a 改成 wrong。
    # 预期行为：Checker 在第一条不匹配的通信规则处立即失败。
    # 检查内容：证明不是只比较选择节点 arity，也会深入每个分支 continuation。
    # 论文对应：多元 T-sqcup 的每个 premise 都是 P_i :: T_i。
    def test_wrong_branch_inside_multiway_choice_is_rejected(self) -> None:
        """选择外形正确但内部通信错误的 Type 不能通过。"""

        constructed = construct_hcsp_type(_CHOICE_SOURCE)
        supplied = format_type_source(constructed).replace("a!", "wrong!", 1)
        with self.assertRaises(HCSPTypeCheckingError) as caught:
            check_hcsp_type(_CHOICE_SOURCE + "\n" + supplied)
        self.assertEqual(caught.exception.verdict, "false")
        self.assertIn("same channel", caught.exception.reason)

    # 测试输入：有限 ODE 的用户 Type 把正确 delay(1) 写成 delay(2)。
    # 预期行为：在调用 dL mock 前由 T-ODE 的类型结论外形检查拒绝。
    # 检查内容：delay 批注是 Type 结论的一部分，不能由证明器修复。
    # 论文对应：有限 T-ODE 结论中的 d 必须等于过程批注 d。
    def test_finite_ode_rejects_wrong_duration_before_proof(self) -> None:
        """有限 ODE 的给定时延必须与过程批注精确一致。"""

        source = """gamma(x: Real, motion: continuous(x))
theta()
process {{ode(flow(dot x = 0), domain(t < 1), safety(true), delay(1))}}
type delay(2) then empty"""
        parsed = parse_typechecking_source(source)
        request = TypeCheckingRequest(
            parsed.program.gamma,
            parsed.program.theta,
            (Configuration({}, parsed.program.process_components[0], name="K1"),),
            parsed.expected_type,
            parameters=parsed.program.parameters,
        )
        calls: list[object] = []

        # 测试输入：若错误 delay 未被结构层截获，后端将收到 dL 公式。
        # 预期行为：本函数在当前测试中一次也不被调用。
        # 检查内容：记录调用而统一返回 true，隔离证明结论本身的影响。
        # 论文对应：规则结论的 d 匹配先于横线上方的 dL premise。
        def prove(formula: object) -> Verdict:
            """记录意外的 dL 调用，并提供不会干扰结构测试的真结论。"""

            calls.append(formula)
            return Verdict.TRUE

        report = TypeChecker(dl_checker=prove).check(request)
        self.assertEqual(report.verdict, Verdict.FALSE)
        self.assertIn("annotation delay is 1", report.mismatch)
        self.assertEqual(calls, [])

    # 测试输入：与上例相同的有限 ODE，但给定 delay(1) 且注入恒真 dL 后端。
    # 预期行为：Checker 证明 safety/boundary 后接受 NoInterrupt 与 Empty 后继。
    # 检查内容：有限 ODE 的 A、T 两个子 judgment 和两条 dL premise 均被访问。
    # 论文对应：项目有限 T-ODE 规则的 safety、boundary、A 与自然后继 T。
    def test_finite_ode_checks_interrupt_and_timeout_children(self) -> None:
        """正确有限 ODE Type 应在完成全部 dL 与子类型检查后通过。"""

        source = """gamma(x: Real, motion: continuous(x))
theta()
process {{ode(flow(dot x = 0), domain(t < 1), safety(true), delay(1))}}
type delay(1) then empty"""
        parsed = parse_typechecking_source(source)
        request = TypeCheckingRequest(
            parsed.program.gamma,
            parsed.program.theta,
            (Configuration({}, parsed.program.process_components[0], name="K1"),),
            parsed.expected_type,
            parameters=parsed.program.parameters,
        )
        calls: list[object] = []

        # 测试输入：有限 ODE 的 safety 与 boundary dL 公式。
        # 预期行为：两项均由后端判真，使 Checker 可以继续检查 A/T 子判断。
        # 检查内容：保存公式调用次数并避免依赖本机 KeYmaera X。
        # 论文对应：有限 T-ODE 横线上方的两项动态逻辑 premise。
        def prove(formula: object) -> Verdict:
            """记录有限 ODE 义务并模拟可信后端证明成功。"""

            calls.append(formula)
            return Verdict.TRUE

        report = TypeChecker(dl_checker=prove).check(request)
        self.assertEqual(report.verdict, Verdict.TRUE)
        self.assertTrue(report.structurally_matched)
        # safety(true) 仍登记为一条已证明义务，但由本地恒真快捷路径完成；
        # 只有非平凡 boundary 需要调用注入的 dL 后端。
        self.assertEqual(len(calls), 1)
        self.assertEqual(
            {item.rule for item in report.evidence.obligations},
            {"T-ODE-safety", "T-ODE-boundary", "T-sigma"},
        )

    # 测试输入：assert(false) 配上结构上看似正确的 empty Type。
    # 预期行为：Type 结构匹配仍不足以通过；FOL premise 的反例使检查失败。
    # 检查内容：Checker 复用证明义务，而不是只做 AST 形状验证。
    # 论文对应：T-Assert 要求证明当前 phi 蕴含 B。
    def test_matching_shape_is_rejected_when_formula_premise_is_false(self) -> None:
        """结构正确但规则公式被否证时必须报告 false。"""

        source = "gamma() theta() process {{assert(false)}}\ntype empty"
        with self.assertRaises(HCSPTypeCheckingError) as caught:
            check_hcsp_type(source)
        self.assertEqual(caught.exception.verdict, "false")
        self.assertIn("counterexample", caught.exception.reason)

    # 测试输入：最小 skip/type empty，并监视旧的完整类型构造入口。
    # 预期行为：检查成功且 TypeConstructor.construct 从未被调用。
    # 检查内容：锁定 Checker 是给定 Type 导向递归，不会退化成构造后比较。
    # 论文对应：Checker 直接验证 T-End 的给定结论 0。
    def test_checker_does_not_call_type_constructor_construct(self) -> None:
        """TypeChecker 不得借用完整 TypeConstructor 结果完成检查。"""

        with patch(
            "hcsp_typechecker.backend.type_constructor.constructor."
            "TypeConstructor.construct",
            side_effect=AssertionError("constructor must not run"),
        ) as construct:
            checked = check_hcsp_type(
                "gamma() theta() process {{skip}}\ntype empty"
            )
        self.assertEqual(str(checked), "0")
        construct.assert_not_called()

    # 测试输入：带 T-Assign-post 与 T-Assert 公式的成功源码，分别使用 result/full。
    # 预期行为：result 只显示结论；full 额外显示原输入、规则轨迹和 FOL 公式。
    # 检查内容：两种输出不改变返回 Type，且 full 使用 TypeChecker 而非 Constructor 标题。
    # 论文对应：展示检查树中横线上方公式 premise 的实际证明记录。
    def test_checker_result_and_full_outputs_have_distinct_detail(self) -> None:
        """TypeChecker 的简洁输出和完整日志应共享结论但具有不同细节。"""

        source = _DISCRETE_SOURCE + "\ntype empty"
        result_stream = StringIO()
        full_stream = StringIO()
        result_type = check_hcsp_type(
            source,
            output="result",
            stream=result_stream,
        )
        full_type = check_hcsp_type(
            source,
            output="full",
            stream=full_stream,
        )
        self.assertEqual(result_type, full_type)
        self.assertIn("HCSP 类型检查结果", result_stream.getvalue())
        self.assertNotIn("原始用户输入", result_stream.getvalue())
        self.assertIn("HCSP 类型检查完整日志", full_stream.getvalue())
        self.assertIn("原始用户输入", full_stream.getvalue())
        self.assertIn("给定 Type 检查与证明详细报告", full_stream.getvalue())
        self.assertIn("T-Assign-post", full_stream.getvalue())


if __name__ == "__main__":
    unittest.main()
