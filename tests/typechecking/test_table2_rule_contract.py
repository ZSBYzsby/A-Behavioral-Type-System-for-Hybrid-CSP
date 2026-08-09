r"""论文 Table 2 类型规则与顺序公式判定的逐规则契约测试。

测试内容
--------
本文件不重复验证每个公式的数学真值；相应工作分别由 ``tests/logic`` 和
``tests/dl`` 完成。这里锁定“应用某条 Table 2 规则时究竟产生哪些公式
premise”，并同时检查推导轨迹采用了正确的规则入口：

1. 终端 ``skip`` 使用 T-End，中间 ``skip # P`` 使用 T-Skip；
2. 离散规则中，T-Assert、T-Assign、T-Out 产生论文明确写出的 FOL premise，
   其余结构规则在表达式处处有定义时不凭空增加公式；
3. T-⊔ 与 T-⊓ 只递归产生子 judgment，本身不产生逻辑 premise；
4. 无自然后继的 ODE 恰好产生 safety/domain 两条 dL premise；
5. 有限时延且有自然后继的 ODE 恰好产生 safety/boundary 两条 dL premise；
6. T-mu、T-X、T-sigma 和 T-parallel 的公式来源与 Table 2 保持一致。

测试使用总定义表达式，避免把除零、平方根定义域等“表达式类型 judgment 的
有定义性条件”混入 Table 2 显式逻辑 premise 的基线。多标量通信和 ODE 隐藏
局部时钟是项目已经约定的逐槽/消糖表示，不改变本文件检查的规则公式集合。

论文对应
--------
逐项对应论文 Table 2 的 T-End、T-Skip、T-Assert、T-Assign、T-If、T-In、
T-Out、T-⊔、T-⊓、T-ODE、两条定时 ODE 规则、T-mu、T-X、T-sigma 与
T-parallel。若以后修改规则分派或顺序证明流程，本文件应首先暴露公式遗漏、
方向颠倒或多生成义务的问题。
"""

from __future__ import annotations

import unittest
from typing import Any, Mapping, Sequence as TypingSequence

from hcsp_typechecker._internal import (
    Assert,
    Assign,
    BasicType,
    ChannelType,
    Configuration,
    ContinuousType,
    EventChoice,
    If,
    InputChannel,
    InternalChoice,
    Mu,
    ODE,
    ODEAnnotation,
    OutputChannel,
    Sequence,
    Skip,
    TypeChecker,
    TypingJudgment,
    Var,
    Verdict,
    check_hcsp,
)


def _approve_dl(_obligation: object) -> Verdict:
    """隔离外部证明器，只检查规则生成了哪几条 dL premise。"""

    return Verdict.TRUE


def _select_boundary_rule(obligation: object) -> Verdict:
    """否证 domain 候选并证明 boundary，使 ``ODE;skip`` 唯一选中自然超时规则。"""

    formula = getattr(obligation, "formula", None)
    return (
        Verdict.FALSE
        if getattr(formula, "role", "") == "domain"
        else Verdict.TRUE
    )


def _check_one(
    process: object,
    *,
    gamma: Mapping[str, BasicType | ContinuousType] | None = None,
    theta: Mapping[str, ChannelType] | None = None,
    state: Mapping[str, Any] | None = None,
    path: object = True,
    dl_checker: object = _approve_dl,
):
    """用单配置 T-sigma 包装一个进程，返回完整且可审计的检查报告。"""

    return check_hcsp(
        gamma={} if gamma is None else gamma,
        theta={} if theta is None else theta,
        configurations=[Configuration(state, process)],
        path_condition=path,
        dl_checker=dl_checker,  # type: ignore[arg-type]
    )


def _obligation_signature(report: object) -> tuple[tuple[str, str], ...]:
    """按生成顺序提取 ``(规则来源, 公式类别)``，用于精确集合比较。"""

    return tuple(
        (obligation.rule, obligation.kind)
        for obligation in report.obligations  # type: ignore[attr-defined]
    )


def _step_rules(report: object) -> tuple[str, ...]:
    """提取推导轨迹规则名；就地 Proof 步骤也保留，调用方可按需忽略。"""

    return tuple(step.rule for step in report.steps)  # type: ignore[attr-defined]


class Table2RuleContractTests(unittest.TestCase):
    """锁定 Table 2 规则分派和公式 premise 的一一对应关系。"""

    # 测试输入：分别检查 ``skip`` 与 ``skip # ch!(0)``。
    # 预期行为：前者只经过 T-End；后者先经过 T-Skip，再推导输出及终端 T-End。
    # 检查内容：规则轨迹和两种场景的完整顺序证明记录签名。
    # 论文对应：Table 2 的 T-End 没有 premise，T-Skip 只有后继 process judgment。
    def test_t_end_and_t_skip_follow_the_exact_source_shape(self) -> None:
        """终端与中间 skip 必须由两条不同的论文规则处理。"""

        terminal = _check_one(Skip())
        self.assertEqual(terminal.verdict, Verdict.TRUE)
        terminal_steps = _step_rules(terminal)
        self.assertIn("T-End", terminal_steps)
        self.assertNotIn("T-Skip", terminal_steps)
        self.assertEqual(
            _obligation_signature(terminal),
            (("T-sigma", "state"),),
        )

        theta = {"done": ChannelType(BasicType.INT)}
        intermediate = _check_one(
            Sequence.of(Skip(), OutputChannel("done", 0)),
            theta=theta,
        )
        self.assertEqual(intermediate.verdict, Verdict.TRUE)
        intermediate_steps = _step_rules(intermediate)
        self.assertIn("T-Skip", intermediate_steps)
        self.assertIn("T-End", intermediate_steps)
        self.assertLess(
            intermediate_steps.index("T-Skip"),
            intermediate_steps.index("T-Out"),
        )
        self.assertEqual(
            _obligation_signature(intermediate),
            (("T-sigma", "state"), ("T-Out", "fol")),
        )

    # 测试输入：assert、赋值、if、输入、输出和内部选择的最小合法进程。
    # 预期行为：仅 T-Assert、T-Assign 的替换 premise 和 T-Out 增加 FOL 义务；
    #           T-If、T-In、T-⊔ 只建立表达式类型/子 judgment premise。
    # 检查内容：每个场景的完整、有序证明记录，而非仅检查某个规则“出现过”。
    # 论文对应：Table 2 各离散规则横线以上的全部 premise。
    def test_discrete_rules_generate_exact_table2_formula_sets(self) -> None:
        """总定义离散表达式不得遗漏或额外产生 Table 2 公式。"""

        integer_channel = ChannelType(BasicType.INT)
        cases: TypingSequence[
            tuple[
                str,
                object,
                Mapping[str, BasicType | ContinuousType],
                Mapping[str, ChannelType],
                Mapping[str, Any],
                object,
                tuple[tuple[str, str], ...],
                str,
            ]
        ] = (
            (
                "T-Assert",
                Assert("x >= 0"),
                {"x": BasicType.INT},
                {},
                {"x": 0},
                "x >= 0",
                (("T-sigma", "state"), ("T-Assert", "fol")),
                "T-Assert",
            ),
            (
                "T-Assign",
                Assign("x", "x + 1"),
                {"x": BasicType.INT},
                {},
                {"x": 0},
                True,
                (("T-sigma", "state"), ("T-Assign-post", "fol")),
                "T-Assign",
            ),
            (
                "T-If",
                If("x >= 0", Skip(), Skip()),
                {"x": BasicType.INT},
                {},
                {"x": 0},
                True,
                (("T-sigma", "state"),),
                "T-If",
            ),
            (
                "T-In",
                InputChannel("data", "x"),
                {},
                {"data": integer_channel},
                {},
                True,
                (("T-sigma", "state"),),
                "T-In",
            ),
            (
                "T-Out",
                OutputChannel("data", 1),
                {},
                {"data": integer_channel},
                {},
                True,
                (("T-sigma", "state"), ("T-Out", "fol")),
                "T-Out",
            ),
            (
                "T-sqcup",
                InternalChoice(Skip(), Skip()),
                {},
                {},
                {},
                True,
                (("T-sigma", "state"),),
                "T-sqcup",
            ),
        )

        for (
            name,
            process,
            gamma,
            theta,
            state,
            path,
            expected,
            expected_step,
        ) in cases:
            with self.subTest(rule=name):
                report = _check_one(
                    process,
                    gamma=gamma,
                    theta=theta,
                    state=state,
                    path=path,
                )
                self.assertEqual(report.verdict, Verdict.TRUE)
                self.assertEqual(_obligation_signature(report), expected)
                self.assertIn(expected_step, _step_rules(report))

        assignment = _check_one(
            Assign("x", "x + 1"),
            gamma={"x": BasicType.INT},
            state={"x": 0},
        )
        post_premise = assignment.obligations[1]
        self.assertIn("Implies", str(post_premise.formula))
        self.assertIn("phi => phi'{e/x}", post_premise.description)

    # 测试输入：带两个输出事件分支、无顺序后继的有限 ODE。
    # 预期行为：T-⊓ 只展开事件子 judgment；其自身不增加公式。两条 T-Out
    #           refinement premise 来自分支，ODE 本身只增加 safety/domain。
    # 检查内容：完整证明记录签名、T-⊓ 轨迹和 dL 公式 role。
    # 论文对应：Table 2 的 T-⊓ 以及只有通信中断后继的第一条定时 ODE 规则。
    def test_external_choice_and_communication_only_ode_formula_set(self) -> None:
        """通信型 ODE 必须恰好生成 domain 与 safety 两类连续义务。"""

        integer_channel = ChannelType(BasicType.INT)
        process = ODE(
            [("x", 0)],
            True,
            EventChoice.of(
                (OutputChannel("left", 0), Skip()),
                (OutputChannel("right", 1), Skip()),
            ),
            annotation=ODEAnnotation(safety=True, delay=1),
        )
        report = _check_one(
            process,
            gamma={"x": BasicType.REAL, "ode_x": ContinuousType(("x",))},
            theta={"left": integer_channel, "right": integer_channel},
            state={"x": 0},
        )

        self.assertEqual(report.verdict, Verdict.TRUE)
        self.assertEqual(
            _obligation_signature(report),
            (
                ("T-sigma", "state"),
                ("T-ODE-safety", "dl"),
                ("T-ODE-domain", "dl"),
                ("T-Out", "fol"),
                ("T-Out", "fol"),
            ),
        )
        self.assertIn("T-&", _step_rules(report))
        ode_roles = tuple(
            obligation.formula.role
            for obligation in report.obligations
            if obligation.kind == "dl"
        )
        self.assertEqual(ode_roles, ("safety", "domain"))

    # 测试输入：有限 delay=1、演化域 x<1 且显式后接 skip 的 ODE。
    # 预期行为：存在自然后继，因此不生成 domain-invariant premise；改为生成
    #           safety 与精确边界 ``(t<d -> B) and (t=d -> not B)`` 两条义务。
    # 检查内容：两条候选的完整顺序证明记录，以及最终有效义务仅含 boundary。
    # 论文对应：Table 2 带 fallback 的第二条定时 ODE 规则。
    def test_finite_ode_with_fallback_has_exact_boundary_formula_set(self) -> None:
        """有限自然终止 ODE 必须选择 boundary，而不能沿用 domain premise。"""

        process = Sequence.of(
            ODE(
                [("x", 1)],
                "x < 1",
                annotation=ODEAnnotation(safety="x <= 1", delay=1),
            ),
            Skip(),
        )
        report = _check_one(
            process,
            gamma={"x": BasicType.REAL, "ode_x": ContinuousType(("x",))},
            state={"x": 0},
            path="x == 0",
            dl_checker=_select_boundary_rule,
        )

        self.assertEqual(report.verdict, Verdict.TRUE)
        self.assertEqual(
            _obligation_signature(report),
            (
                ("T-sigma", "state"),
                ("T-ODE-safety", "dl"),
                ("T-ODE-domain", "dl"),
                ("T-ODE-safety", "dl"),
                ("T-ODE-boundary", "dl"),
            ),
        )
        self.assertEqual(
            tuple(item.active for item in report.obligations),
            (True, False, False, True, True),
        )
        ode_roles = tuple(
            obligation.formula.role
            for obligation in report.obligations
            if obligation.kind == "dl"
        )
        self.assertEqual(
            ode_roles,
            ("safety", "domain", "safety", "boundary"),
        )
        active_ode_roles = tuple(
            obligation.formula.role
            for obligation in report.obligations
            if obligation.kind == "dl" and obligation.active
        )
        self.assertEqual(active_ode_roles, ("safety", "boundary"))
        boundary_source = report.obligations[4].formula.source
        # KeYmaera X 打印器把 ``t < 1`` 规范成等价的 ``1 > t``，而
        # ``t = 1`` 可能打印成 ``1 = t``；两部分必须同时保留。
        self.assertIn("1 >", boundary_source)
        self.assertIn("1 =", boundary_source)
        self.assertIn("-> !(", boundary_source)

    # 测试输入：通信保护递归 mu X.(tick?u # X)，以及两个局部 Gamma 不相交的
    #           顶层配置。递归 invariant 使用默认 true。
    # 预期行为：递归产生 T-mu、T-X 两条蕴含；每个 configuration 各产生一条
    #           T-sigma 状态义务；T-parallel 本身不额外产生逻辑公式。
    # 检查内容：递归和并行两组完整证明记录签名及相应规则轨迹。
    # 论文对应：Table 2 的 T-mu、T-X、T-sigma 和 T-parallel。
    def test_recursion_configuration_and_parallel_formula_sets(self) -> None:
        """递归边界与配置状态是最后四条规则中仅有的逻辑义务。"""

        recursive = Mu(
            "X",
            Sequence.of(InputChannel("tick", "u"), Var("X")),
        )
        recursion_report = _check_one(
            recursive,
            theta={"tick": ChannelType(BasicType.INT)},
        )
        self.assertEqual(recursion_report.verdict, Verdict.TRUE)
        self.assertEqual(
            _obligation_signature(recursion_report),
            (
                ("T-sigma", "state"),
                ("T-mu", "fol"),
                ("T-X", "fol"),
            ),
        )
        recursion_steps = _step_rules(recursion_report)
        self.assertIn("T-mu", recursion_steps)
        self.assertIn("T-X", recursion_steps)

        checker = TypeChecker(dl_checker=_approve_dl)
        parallel_report = checker.check(
            TypingJudgment(
                gamma={"left": BasicType.INT, "right": BasicType.INT},
                theta={},
                configurations=(
                    Configuration(
                        {"left": 0},
                        Skip(),
                        gamma={"left": BasicType.INT},
                        path_condition="left == 0",
                        name="left",
                    ),
                    Configuration(
                        {"right": 1},
                        Skip(),
                        gamma={"right": BasicType.INT},
                        path_condition="right == 1",
                        name="right",
                    ),
                ),
            )
        )
        self.assertEqual(parallel_report.verdict, Verdict.TRUE)
        self.assertEqual(
            _obligation_signature(parallel_report),
            (("T-sigma", "state"), ("T-sigma", "state")),
        )
        self.assertEqual(_step_rules(parallel_report).count("T-||"), 1)


if __name__ == "__main__":
    unittest.main()
