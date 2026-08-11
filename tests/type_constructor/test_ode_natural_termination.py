r"""验证显式 ODE 后继与两条 Table 2 候选规则的选择。

测试内容
--------
1. 裸末尾 ODE 在 AST 入口同样被 Constructor 拒绝，防止绕过用户前端约束。
2. ``ODE; skip`` 隔离试用 ``T-\unrhd`` 与 ``T-\unrhd'``，由证明结果选择。
3. 两候选公式均保留供审计，但只有选中候选参与最终 verdict。
4. ``ODE; P`` 且 P 非 skip 时只使用带自然后继的规则。

论文对应
--------
显式 ``skip`` 既可以是“无实际后继”的语法占位，也可以是规则 prime 的真实
空后继；工具逐条证明 domain/boundary 前提来区分。非空后继不存在该歧义。
"""

from __future__ import annotations

import unittest
from typing import Any, Mapping

from hcsp_typechecker._internal import (
    Assert,
    BottomType,
    Configuration,
    EmptyType,
    FiniteDelayType,
    NoInterruptType,
    ODE,
    ODEAnnotation,
    Skip,
    TypeConstructionRequest,
    TypeConstructor,
    Verdict,
)


def _backend(
    answers: Mapping[str, Verdict],
    calls: list[str],
):
    """建立按 dL role 返回结论并记录调用顺序的测试后端。"""

    def decide(obligation: Any) -> Verdict:
        """读取公式 role；未显式指定的角色缺省视为已证明。"""

        role = getattr(getattr(obligation, "formula", None), "role", "")
        calls.append(role)
        return answers.get(role, Verdict.TRUE)

    return decide


def _finite_ode(*, continuation: object | None = None) -> ODE:
    """构造具有非平凡 domain/boundary 的有限空 flow ODE。"""

    return ODE(
        (),
        "t < 1",
        annotation=ODEAnnotation(safety=True, delay=1),
        continuation=continuation,
    )


def _construct(process: object, answers: Mapping[str, Verdict], calls: list[str]):
    """在空环境中构造一个 ODE 测试进程的类型。"""

    return TypeConstructor(dl_checker=_backend(answers, calls)).construct(
        TypeConstructionRequest(
            gamma={},
            theta={},
            configurations=[Configuration({}, process)],
        )
    )


class FiniteODETerminationTests(unittest.TestCase):
    """锁定显式 skip 的候选选择和非 skip 后继的确定分派。"""

    # 测试输入：直接 AST API 构造省略 continuation 的 ODE。
    # 预期行为：节点自身把公共后继规范为 Skip，不再生成 Sequence(ODE, Skip)。
    # 检查内容：锁定 Table 2 终端控制节点的唯一 AST 形状。
    # 论文对应：无实际后继仍以 skip 占位，但占位属于 ODE 节点自己的 Q 字段。
    def test_ode_defaults_to_an_owned_skip_continuation(self) -> None:
        """ODE 的缺省公共后继应保存在节点内部。"""

        ode = _finite_ode()
        self.assertIsInstance(ode.continuation, Skip)

    # 测试输入：ODE;skip，domain 真而 boundary 假。
    # 预期行为：两条规则都试用，最终选择纯通信 T-unrhd。
    # 检查内容：两候选义务均保留，只有 domain 候选 active。
    # 论文对应：skip 在此解释为“无实际后继”的占位。
    def test_skip_selects_communication_rule_when_only_domain_holds(self) -> None:
        """domain 成立时应选择纯通信规则。"""

        calls: list[str] = []
        report = _construct(
            _finite_ode(continuation=Skip()),
            {"domain": Verdict.TRUE, "boundary": Verdict.FALSE},
            calls,
        )

        self.assertEqual(report.verdict, Verdict.TRUE)
        self.assertEqual(
            report.constructed_type,
            FiniteDelayType(1, NoInterruptType(), BottomType()),
        )
        self.assertEqual(calls, ["domain", "boundary"])
        active_rules = {
            item.rule for item in report.obligations if item.active
        }
        self.assertIn("T-ODE-domain", active_rules)
        self.assertNotIn("T-ODE-boundary", active_rules)

    # 测试输入：ODE;skip，domain 假而 boundary 真。
    # 预期行为：选择 T-unrhd-prime，并把 skip 作为真实 T-End 子判断。
    # 检查内容：选中义务为 boundary，最终后继仍规范成 EmptyType。
    # 论文对应：prime 规则允许真实后继 Q 本身是空语句。
    def test_skip_selects_timeout_rule_when_only_boundary_holds(self) -> None:
        """boundary 成立时应选择带自然后继的规则。"""

        calls: list[str] = []
        report = _construct(
            _finite_ode(continuation=Skip()),
            {"domain": Verdict.FALSE, "boundary": Verdict.TRUE},
            calls,
        )

        self.assertEqual(report.verdict, Verdict.TRUE)
        self.assertEqual(
            report.constructed_type,
            FiniteDelayType(1, NoInterruptType(), EmptyType()),
        )
        self.assertEqual(calls, ["domain", "boundary"])
        active_rules = {
            item.rule for item in report.obligations if item.active
        }
        self.assertIn("T-ODE-boundary", active_rules)
        self.assertNotIn("T-ODE-domain", active_rules)

    # 测试输入：ODE;skip 的 domain 已证明，而 boundary 由于后端能力返回 unknown。
    # 预期行为：依据两条规则适用条件互斥，采用已证的 T-unrhd 且总体可信。
    # 检查内容：未决 boundary 仍保留为 inactive 审计证据，不污染最终 verdict。
    # 论文对应：候选试用用于选规则；已经建立一个完整推导后无需证明另一规则不成立。
    def test_proved_candidate_dominates_inactive_unknown_candidate(self) -> None:
        """一个候选已证明时，另一个未决候选不得降低可信性。"""

        calls: list[str] = []
        report = _construct(
            _finite_ode(continuation=Skip()),
            {"domain": Verdict.TRUE, "boundary": Verdict.UNKNOWN},
            calls,
        )

        self.assertEqual(report.verdict, Verdict.TRUE)
        self.assertEqual(
            report.constructed_type,
            FiniteDelayType(1, NoInterruptType(), BottomType()),
        )
        self.assertEqual(calls, ["domain", "boundary"])
        boundary = next(
            item for item in report.obligations if item.rule == "T-ODE-boundary"
        )
        self.assertEqual(boundary.verdict, Verdict.UNKNOWN)
        self.assertFalse(boundary.active)

    # 测试输入：ODE;skip 的 domain 与 boundary 都暂时 unknown。
    # 预期行为：继续形成完整临时候选，但总体 verdict 保持 unknown。
    # 检查内容：候选来源与 active 状态可在报告中审计。
    # 论文对应：UNKNOWN 不等于反例，不应像 FALSE 一样截断后续推导。
    def test_unknown_candidates_keep_an_untrusted_type(self) -> None:
        """两条规则未决时保留完整但不可信的等价类型。"""

        calls: list[str] = []
        report = _construct(
            _finite_ode(continuation=Skip()),
            {"domain": Verdict.UNKNOWN, "boundary": Verdict.UNKNOWN},
            calls,
        )

        self.assertEqual(report.verdict, Verdict.UNKNOWN)
        self.assertEqual(
            report.constructed_type,
            FiniteDelayType(1, NoInterruptType(), EmptyType()),
        )
        self.assertEqual(calls, ["domain", "boundary"])
        self.assertEqual(
            {item.candidate for item in report.obligations if item.candidate},
            {"communication-only", "natural-timeout"},
        )

    # 测试输入：有限 ODE 后是非 skip 的 assert(true)。
    # 预期行为：无需候选选择，只使用 T-unrhd-prime 的 boundary 前提。
    # 检查内容：证明器不接收 domain；后继静态检查正常完成。
    # 论文对应：真实非空后继只与 prime 规则结论匹配。
    def test_non_skip_successor_uses_only_timeout_rule(self) -> None:
        """非 skip 后继必须唯一分派到自然超时规则。"""

        calls: list[str] = []
        report = _construct(
            _finite_ode(continuation=Assert(True)),
            {"boundary": Verdict.TRUE},
            calls,
        )

        self.assertEqual(report.verdict, Verdict.TRUE)
        self.assertEqual(calls, ["boundary"])
        self.assertNotIn("T-ODE-Select", {step.rule for step in report.steps})


if __name__ == "__main__":
    unittest.main()
