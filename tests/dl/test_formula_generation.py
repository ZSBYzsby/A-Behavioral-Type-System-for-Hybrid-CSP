r"""HCSP ODE 证明义务到正式 dL 公式的翻译测试。

这些测试不模拟连续数值轨迹，而是检查送入 KeYmaera X 前的语义边界：

* safety、domain、boundary 三类公式是否使用新版 Table 2 的正确 box 模态；
* Gamma 是否只登记 ODE 演化向量，安全目标是否唯一来自 ODE 批注；
* 每个 ODE 的隐藏局部时钟是否以 t=0、t'=1 进入正式 dL；
* ODE 前的赋值是否通过入口快照等式保留下来；
* Z3 内部名称是否全部替换成 KeYmaera X 合法名称；
* 无法可靠编码的表达式是否保守成为 ``UntranslatedDLFormula``。

测试内容
--------
1. safety/domain 的不变性模态和 boundary 的严格边界蕴含。
2. 精确有理时延、无限时延和 ODE 入口状态快照。
3. 未解释函数、Bool 状态等不可可靠翻译边界。
4. KeYmaera X archive 的变量、Problem、Tactic 和 End 结构。

论文对应
--------
对应 Section 4.3 与新版 Table 2 中 T-ODE 及两条 T-\unrhd 行为规则
的 dL 前提，并验证这些前提生成 KeYmaera X 可消费输入的适配层。
"""

from __future__ import annotations

from math import inf
import unittest

from hcsp_typechecker._internal import (
    Assign,
    BasicType,
    ChannelType,
    Configuration,
    ContinuousType,
    DLFormula,
    ODE,
    ODEAnnotation,
    OutputChannel,
    Sequence,
    UntranslatedDLFormula,
    Verdict,
    construct_type,
)


def _approve_and_collect(storage: list[object]):
    """建立一个保存证明义务且返回 TRUE 的隔离后端。"""

    def checker(obligation: object) -> Verdict:
        """记录检查器实际发送的对象，避免测试依赖私有方法。"""

        storage.append(obligation)
        return Verdict.TRUE

    return checker


def _select_boundary_and_collect(storage: list[object]):
    """记录两个 ODE 候选，否证 domain 并唯一选中 boundary 规则。"""

    def checker(obligation: object) -> Verdict:
        """按 dL role 返回可区分两条规则的模拟结果。"""

        storage.append(obligation)
        formula = getattr(obligation, "formula", None)
        return (
            Verdict.FALSE
            if getattr(formula, "role", "") == "domain"
            else Verdict.TRUE
        )

    return checker


def _local_clock_name(test: unittest.TestCase, formula: DLFormula) -> str:
    """从审计映射中取得当前 ODE 自动局部时钟的 KeYmaera X 安全名称。"""

    clocks = [
        safe
        for safe, original in formula.symbol_map
        if original.startswith("@hcsp_ode_clock_")
    ]
    test.assertEqual(len(clocks), 1, formula.symbol_map)
    return clocks[0]


class DLFormulaGenerationTests(unittest.TestCase):
    """覆盖论文三类 ODE 公式前提及关键组合场景。"""

    # 测试输入：Gamma 登记单元素向量 (x)；ODE 在 x'=t+1、源域和 safety
    #           中直接读取局部 t。
    # 预期行为：生成 safety/domain DLFormula，且不生成自然结束 boundary。
    # 检查内容：核对两处 t 指向同一时钟，ODE safety 只进入 safety 目标，
    #           源 B 只进入 domain 目标，Gamma 不追加第二份性质。
    # 论文对应：Table 2 的纯通信中断 T-ODE-safety/T-ODE-domain 前提。
    def test_safety_and_domain_are_formal_box_modalities(self) -> None:
        """同一 ODE 的 safety/domain 公式都应显式包含自动局部时钟。"""

        captured: list[object] = []
        process = ODE(
            [("x", "t + 1")],
            "t <= 10 and x <= 10",
            annotation=ODEAnnotation(safety="x >= t and t <= 2", delay=inf),
        )
        report = construct_type(
            gamma={"x": BasicType.REAL, "ode_x": ContinuousType(("x",))},
            theta={},
            configurations=[Configuration({"x": 0}, process)],
            path_condition="x == 0",
            dl_checker=_approve_and_collect(captured),
        )

        self.assertEqual(report.verdict, Verdict.TRUE)
        formulas = {
            item.rule: item.formula
            for item in report.obligations
            if item.kind == "dl"
        }
        safety = formulas["T-ODE-safety"]
        domain = formulas["T-ODE-domain"]
        self.assertIsInstance(safety, DLFormula)
        self.assertIsInstance(domain, DLFormula)
        safety_clock = _local_clock_name(self, safety)
        domain_clock = _local_clock_name(self, domain)
        self.assertIn(f"{safety_clock}'=1", safety.source)
        self.assertIn(f"'=({safety_clock} + 1)", safety.source)
        self.assertNotIn(f"{safety_clock}<=2 ->", safety.source)
        self.assertIn(f" >= {safety_clock}", safety.source)
        self.assertTrue(
            f"{safety_clock} = 0" in safety.source
            or f"0 = {safety_clock}" in safety.source
        )
        self.assertIn("[{", safety.source)
        self.assertIn("}](", safety.source)
        safety_program = safety.source.split("}]", 1)[0]
        domain_program = domain.source.split("}]", 1)[0]
        safety_post = safety.source.split("}]", 1)[1]
        self.assertIn(" >= ", safety_post)
        self.assertNotRegex(domain.source, r"0 <= kxv\d+")
        self.assertNotIn("10 >=", safety_program)
        self.assertNotIn("10 >=", domain_program)
        self.assertIn("-> [{", domain.source)
        self.assertIn(f"{domain_clock}'=1", domain.source)
        self.assertIn(f"'=({domain_clock} + 1)", domain.source)
        self.assertIn(f"10 >= {domain_clock}", domain.source)
        self.assertTrue(
            f"{domain_clock} = 0" in domain.source
            or f"0 = {domain_clock}" in domain.source
        )
        self.assertNotIn("K1__", safety.source)
        self.assertNotIn("__dlentry", safety.source)
        self.assertNotIn("T-ODE-boundary", formulas)

    # 测试输入：delay=1 的 ODE 后接 done 输出，因而具有 fallback。
    # 预期行为：boundary 公式在无额外 Gamma 性质的单个 box 中分别检查
    #           t<d -> B 和 t=d -> not B，不加入 diamond 可达性条件。
    # 检查内容：查验严格时钟比较、边界等式、否定域；ODE 程序中没有待验证的
    #           源 B，即 x<1，Gamma 仅负责确认向量 (x) 已登记。
    # 论文对应：新版 Table 2 带自然后继规则的精确边界 dL 前提。
    def test_boundary_uses_strict_before_and_not_domain_at_deadline(self) -> None:
        """带 fallback 的 ODE 应按 Table 2 证明 d 前在 B、d 时离开 B。"""

        captured: list[object] = []
        process = Sequence.of(
            ODE(
                [("x", 1)],
                "x < 1",
                annotation=ODEAnnotation(safety="x <= 1", delay=1),
            ),
            OutputChannel("done", 0),
        )
        report = construct_type(
            gamma={"x": BasicType.REAL, "ode_x": ContinuousType(("x",))},
            theta={"done": ChannelType(BasicType.INT)},
            configurations=[Configuration({"x": 0}, process)],
            path_condition="x == 0",
            dl_checker=_approve_and_collect(captured),
        )

        boundary = next(
            item.formula
            for item in report.obligations
            if item.rule == "T-ODE-boundary"
        )
        self.assertIsInstance(boundary, DLFormula)
        clock = _local_clock_name(self, boundary)
        self.assertIn("[{", boundary.source)
        self.assertNotIn("<{", boundary.source)
        boundary_program = boundary.source.split("}]", 1)[0]
        self.assertNotIn("1 >", boundary_program)
        self.assertIn(f"1 > {clock}", boundary.source)
        self.assertIn(f"1 = {clock}", boundary.source)
        self.assertIn("-> !(", boundary.source)

    # 测试输入：delay="1 / 2"、边界 ``2*x<=1`` 的有限 ODE。
    # 预期行为：dL 中使用 ``(1/2)``，不出现近似小数。
    # 检查内容：同时检查 t<d 和 t=d 两个位置的精确有理数序列化。
    # 论文对应：Remark 4.1 的外部精确持续时间进入新版边界公式。
    def test_exact_rational_delay_is_serialized_for_keymaerax(self) -> None:
        """Fraction 时延应以精确除法进入 dL，而不是浮点近似。"""

        captured: list[object] = []
        process = Sequence.of(
            ODE(
                [("x", 1)],
                "2 * x < 1",
                annotation=ODEAnnotation(
                    safety="2 * x <= 1",
                    delay="1 / 2",
                ),
            ),
            OutputChannel("done", 0),
        )
        report = construct_type(
            gamma={"x": BasicType.REAL, "ode_x": ContinuousType(("x",))},
            theta={"done": ChannelType(BasicType.INT)},
            configurations=[Configuration({"x": 0}, process)],
            path_condition="x == 0",
            dl_checker=_approve_and_collect(captured),
        )

        boundary = next(
            item.formula
            for item in report.obligations
            if item.rule == "T-ODE-boundary"
        )
        self.assertEqual(report.verdict, Verdict.TRUE)
        self.assertIsInstance(boundary, DLFormula)
        clock = _local_clock_name(self, boundary)
        self.assertIn(f"(1/2) > {clock}", boundary.source)
        self.assertIn(f"(1/2) = {clock}", boundary.source)

    # 测试输入：先执行 x:=x+1，再进入安全式 x>=1 的静止 ODE。
    # 预期行为：dL 使用新鲜入口变量并以等式连接赋值后的当前 x。
    # 检查内容：核对 symbol_map、__dlentry 名称、加法和入口等式。
    # 论文对应：离散 T-Assign 的后状态必须成为后续 T-ODE 的前置状态。
    def test_assignment_before_ode_is_materialized_at_entry(self) -> None:
        """ODE 左端必须是新鲜变量，并由等式连接到赋值后的当前值。"""

        captured: list[object] = []
        process = Sequence.of(
            Assign("x", "x + 1"),
            ODE(
                [("x", 0)],
                True,
                annotation=ODEAnnotation(safety="x >= 1", delay=1),
            ),
        )
        report = construct_type(
            gamma={"x": BasicType.REAL, "ode_x": ContinuousType(("x",))},
            theta={},
            configurations=[Configuration({"x": 0}, process)],
            path_condition="x == 0",
            dl_checker=_approve_and_collect(captured),
        )

        safety = next(
            item.formula
            for item in report.obligations
            if item.rule == "T-ODE-safety"
        )
        self.assertIsInstance(safety, DLFormula)
        original_names = {original for _safe, original in safety.symbol_map}
        self.assertIn("K1__x", original_names)
        self.assertTrue(
            any("__dlentry" in name for name in original_names),
            safety.symbol_map,
        )
        self.assertIn(" + 1", safety.source)
        self.assertIn(" = ", safety.source)

    # 测试输入：delay=infinity、x'=0、域/安全式 x>=0。
    # 预期行为：生成全时间 box 不变式，同时保留该 ODE 固有的自动局部时钟。
    # 检查内容：要求存在 box implication、t=0 和 t'=1，但不比较有限 delay。
    # 论文对应：纯通信中断的 T-\unrhd 无限演化安全前提。
    def test_infinite_delay_safety_becomes_an_invariant(self) -> None:
        """d=infinity 不比较时限，但仍保留每个 ODE 固有的局部时钟。"""

        captured: list[object] = []
        process = ODE(
            [("x", 0)],
            "x >= 0",
            annotation=ODEAnnotation(safety="x >= 0", delay=inf),
        )
        report = construct_type(
            gamma={"x": BasicType.REAL, "ode_x": ContinuousType(("x",))},
            theta={},
            configurations=[Configuration({"x": 0}, process)],
            path_condition="x >= 0",
            dl_checker=_approve_and_collect(captured),
        )

        safety = next(
            item.formula
            for item in report.obligations
            if item.rule == "T-ODE-safety"
        )
        self.assertIsInstance(safety, DLFormula)
        clock = _local_clock_name(self, safety)
        self.assertIn("-> [{", safety.source)
        self.assertIn(f"{clock}'=1", safety.source)
        self.assertTrue(
            f"{clock} = 0" in safety.source
            or f"0 = {clock}" in safety.source
        )

    # 测试输入：没有任何用户 ODE 分量或向量声明的空 flow 有限 ODE。
    # 预期行为：dL 可构造；自动局部时钟是 ODE 模态中的唯一微分方程。
    # 检查内容：要求公式含 t=0、t'=1、t<1 -> B 和 t=1 -> not B；其中
    #           演化域 B 显式写为严格边界 t<1。
    # 论文对应：ODE 的局部 t 由规则隐式引入，并在 d 时到达演化边界。
    def test_hidden_clock_supports_ode_without_user_equations(self) -> None:
        """空用户方程仍应通过自动 t'=1 形成正式的 boundary 公式。"""

        captured: list[object] = []
        process = ODE((), "t < 1", annotation=ODEAnnotation(delay=1))
        report = construct_type(
            gamma={},
            theta={},
            configurations=[Configuration({}, process)],
            dl_checker=_select_boundary_and_collect(captured),
        )

        boundary = next(
            item.formula
            for item in report.obligations
            if item.rule == "T-ODE-boundary"
        )
        self.assertEqual(report.verdict, Verdict.TRUE)
        self.assertIsInstance(boundary, DLFormula)
        clock = _local_clock_name(self, boundary)
        self.assertIn(f"[{{{clock}'=1}}]", boundary.source)
        self.assertIn(f"1 > {clock}", boundary.source)
        self.assertIn(f"1 = {clock}", boundary.source)
        self.assertIn("-> !(", boundary.source)
        self.assertTrue(
            f"{clock} = 0" in boundary.source
            or f"0 = {clock}" in boundary.source
        )

    # 测试输入：向量场 x'=1/y、safety=true，入口 y=0，ODE 后接 Skip。
    # 预期行为：safety 不得走“批注 true 自动通过”捷径，公式必须要求 y!=0。
    # 检查内容：核对正式 safety DLFormula 中出现非零侧条件和无域 box 模态。
    # 论文对应：Table 2 默认方程右端 e 能求值；实现需显式验证偏表达式前提。
    def test_partial_ode_derivative_enters_definedness_obligation(self) -> None:
        """ODE 向量场中的除零风险必须进入连续安全证明。"""

        captured: list[object] = []
        process = Sequence.of(
            ODE(
                [("x", "1 / y")],
                "t < 1",
                annotation=ODEAnnotation(safety=True, delay=1),
            ),
            OutputChannel("done", 0),
        )
        report = construct_type(
            gamma={
                "x": BasicType.REAL,
                "y": BasicType.REAL,
                "ode_x": ContinuousType(("x",)),
            },
            theta={"done": ChannelType(BasicType.INT)},
            configurations=[Configuration({"x": 0, "y": 0}, process)],
            path_condition="x == 0 and y == 0",
            dl_checker=_approve_and_collect(captured),
        )

        safety = next(
            item.formula
            for item in report.obligations
            if item.rule == "T-ODE-safety"
        )
        self.assertIsInstance(safety, DLFormula)
        self.assertNotEqual(safety.source, "true")
        self.assertIn("!= 0", safety.source)
        self.assertNotRegex(safety.source, r"\[\{[^}]+ & ")

    # 测试输入：ODE 导数 ``mystery(x)``，项目没有该函数的 dL 定义。
    # 预期行为：safety 义务为 unknown，并保存 UntranslatedDLFormula。
    # 检查内容：错误原因必须指出 unsupported dL term，且不启动猜测翻译。
    # 论文对应：T-ODE 前提无法可靠送入证明器时采用保守三值结果。
    def test_uninterpreted_derivative_is_not_string_spliced(self) -> None:
        """未解释函数不能被猜测成 KeYmaera 定义，义务必须保持 unknown。"""

        process = ODE(
            [("x", "mystery(x)")],
            True,
            annotation=ODEAnnotation(safety="x >= 0", delay=1),
        )
        report = construct_type(
            gamma={"x": BasicType.REAL, "ode_x": ContinuousType(("x",))},
            theta={},
            configurations=[Configuration({"x": 0}, process)],
            path_condition="x == 0",
        )

        safety = next(
            item
            for item in report.obligations
            if item.rule == "T-ODE-safety"
        )
        self.assertEqual(safety.verdict, Verdict.UNKNOWN)
        self.assertIsInstance(safety.formula, UntranslatedDLFormula)
        self.assertIn("unsupported dL term", safety.formula.reason)

    # 测试输入：前置条件包含 Bool 状态 flag 和 Real 状态 x。
    # 预期行为：dL 翻译保持 unknown，不把 flag 声明成 KeYmaera Real。
    # 检查内容：核对 UntranslatedDLFormula 及 Boolean state 原因。
    # 论文对应：dL 状态变量类型必须忠实于 T-ODE 的 Gamma 声明。
    def test_boolean_state_in_precondition_is_rejected_conservatively(self) -> None:
        """KeYmaera 实变量不能冒充 Bool 状态变量，不能产生不可靠编码。"""

        process = ODE(
            [("x", 0)],
            True,
            annotation=ODEAnnotation(safety="x >= 0", delay=1),
        )
        report = construct_type(
            gamma={
                "x": BasicType.REAL,
                "flag": BasicType.BOOL,
                "ode_x": ContinuousType(("x",)),
            },
            theta={},
            configurations=[Configuration({"x": 0, "flag": True}, process)],
            path_condition="flag and x == 0",
        )

        safety = next(
            item
            for item in report.obligations
            if item.rule == "T-ODE-safety"
        )
        self.assertEqual(safety.verdict, Verdict.UNKNOWN)
        self.assertIsInstance(safety.formula, UntranslatedDLFormula)
        self.assertIn("Boolean state variable", safety.formula.reason)

    # 测试输入：单变量恒等 DLFormula、含引号/换行的条目名和 auto tactic。
    # 预期行为：生成名称已清理、区块完整且以外层 End. 结束的 archive。
    # 检查内容：逐段核对 ProgramVariables、Problem、Tactic 和嵌套 End。
    # 论文对应：这是论文 dL 前提送入 KeYmaera X 的工具适配格式。
    def test_archive_declares_every_variable_and_tactic(self) -> None:
        """DLFormula archive 应含变量区、Problem、Tactic 和两个层级的 End。"""

        formula = DLFormula(
            "(kxv0=kxv0)",
            ("kxv0",),
            (("kxv0", "K1__x"),),
            "smoke",
        )
        archive = formula.to_archive(
            entry_name='unsafe "name"\nline',
            tactic="auto",
        )

        self.assertIn('ArchiveEntry "unsafe \'name\' line"', archive)
        self.assertIn("ProgramVariables\n  Real kxv0;\nEnd.", archive)
        self.assertIn("Problem\n  (kxv0=kxv0)\nEnd.", archive)
        self.assertIn('Tactic "HCSP Proof"\n  auto\nEnd.', archive)
        self.assertTrue(archive.endswith("End.\n"))


if __name__ == "__main__":
    unittest.main()
