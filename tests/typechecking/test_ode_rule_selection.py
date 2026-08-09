r"""验证 ``ODE;skip`` 对两条 Table 2 规则的顺序试用与唯一选择。

测试内容
--------
1. domain 成立、boundary 不成立时，只选择纯通信中断规则；
2. domain 不成立、boundary 成立时，只选择自然超时规则；
3. 两组 premise 都成立但结论类型不等价时，报告规则歧义而不擅自选型；
4. 一条规则已证明、另一条非等价规则仍 unknown 时，不假装已经唯一选型；
5. 每个候选的公式按候选顺序立即证明，未选候选只作为审计证据保留。

论文对应
--------
有限 ``ODE;skip`` 在 AST 形状上可能同时匹配 Table 2 的纯通信中断规则与
自然超时规则。实现必须分别验证两条横线上方的 premise，再根据证明结果选择
唯一可行的结论；不能只按语法形状预先决定规则，也不能把公式推迟到批量阶段。
"""

from __future__ import annotations

import unittest
from typing import Any, Callable

from hcsp_typechecker._internal import (
    BottomType,
    Configuration,
    EndType,
    ODE,
    PureDelayType,
    TypingJudgment,
    TypeChecker,
    Verdict,
)


def _role_backend(
    *,
    domain: Verdict,
    boundary: Verdict,
    calls: list[str],
) -> Callable[[Any], Verdict]:
    """构造只按 dL role 返回结果的可观察测试后端。"""

    # 功能：记录调用 role，并返回该候选 premise 的预设三值结果。
    def decide(obligation: Any) -> Verdict:
        """按公式 role 返回测试指定的 domain 或 boundary 结论。"""

        formula = getattr(obligation, "formula", None)
        role = getattr(formula, "role", "")
        calls.append(role)
        if role == "domain":
            return domain
        if role == "boundary":
            return boundary
        return Verdict.TRUE

    return decide


def _check_wait(
    *,
    domain: Verdict,
    boundary: Verdict,
) -> tuple[object, tuple[str, ...]]:
    """检查 ``wait(1)`` 并同时返回外部后端的实际调用顺序。"""

    calls: list[str] = []
    checker = TypeChecker(
        dl_checker=_role_backend(
            domain=domain,
            boundary=boundary,
            calls=calls,
        )
    )
    report = checker.check(
        TypingJudgment(
            gamma={},
            theta={},
            configurations=[Configuration({}, ODE.wait(1))],
        )
    )
    return report, tuple(calls)


class ODESkipRuleSelectionTests(unittest.TestCase):
    """锁定候选规则证明、选择和审计证据的完整行为。"""

    # 测试输入：wait(1)，测试后端证明 domain、否证 boundary。
    # 预期行为：选择纯通信中断规则，得到 delay(1).bottom；总体 verdict 为 true。
    # 检查内容：两条 dL 公式的调用顺序、候选标签和 active 标记。
    # 论文对应：纯通信规则的 fallback 为 bottom，不采用自然超时后的 skip 类型。
    def test_selects_communication_rule_when_only_domain_is_proved(self) -> None:
        """仅 domain 候选成立时必须生成正式的纯时延到底类型。"""

        report, calls = _check_wait(
            domain=Verdict.TRUE,
            boundary=Verdict.FALSE,
        )

        self.assertEqual(report.verdict, Verdict.TRUE)
        self.assertEqual(report.inferred_type, PureDelayType(1, BottomType()))
        self.assertEqual(calls, ("domain", "boundary"))
        self.assertEqual(
            tuple(item.candidate for item in report.obligations[1:]),
            (
                "communication-only",
                "communication-only",
                "natural-timeout",
                "natural-timeout",
            ),
        )
        self.assertEqual(
            tuple(item.active for item in report.obligations),
            (True, True, True, False, False),
        )

    # 测试输入：wait(1)，测试后端否证 domain、证明 boundary。
    # 预期行为：选择自然超时规则，超时后执行 skip，得到 delay(1).end。
    # 检查内容：未选通信候选的 false 义务不会污染最终 verdict，但仍留在报告中。
    # 论文对应：自然超时规则把 ODE 的顺序后继作为 timed type 的 fallback。
    def test_selects_timeout_rule_when_only_boundary_is_proved(self) -> None:
        """仅 boundary 候选成立时必须把 skip 作为自然超时后继。"""

        report, calls = _check_wait(
            domain=Verdict.FALSE,
            boundary=Verdict.TRUE,
        )

        self.assertEqual(report.verdict, Verdict.TRUE)
        self.assertEqual(report.inferred_type, PureDelayType(1, EndType()))
        self.assertEqual(calls, ("domain", "boundary"))
        self.assertEqual(
            tuple(item.active for item in report.obligations),
            (True, False, False, True, True),
        )
        self.assertEqual(
            tuple(item.verdict for item in report.obligations),
            (
                Verdict.TRUE,
                Verdict.TRUE,
                Verdict.FALSE,
                Verdict.TRUE,
                Verdict.TRUE,
            ),
        )

    # 测试输入：wait(1)，测试后端同时证明 domain 与 boundary。
    # 预期行为：两个候选分别生成 delay(1).bottom 与 delay(1).end，因不等价而
    #           返回 unknown，且 inferred_type 为 None。
    # 检查内容：不会按候选次序任意选第一个；两组公式都作为未选证据保留。
    # 论文对应：一棵推导树必须有确定结论；非等价规则结论不能静默合并。
    def test_reports_ambiguity_when_both_non_equivalent_rules_are_proved(self) -> None:
        """两条规则同时成立但结论不同必须显式报告歧义。"""

        report, calls = _check_wait(
            domain=Verdict.TRUE,
            boundary=Verdict.TRUE,
        )

        self.assertEqual(report.verdict, Verdict.UNKNOWN)
        self.assertIsNone(report.inferred_type)
        self.assertEqual(calls, ("domain", "boundary"))
        self.assertEqual(
            tuple(item.active for item in report.obligations),
            (True, False, False, False, False),
        )
        self.assertTrue(
            any(
                item.rule == "T-ODE-Select"
                and "ambiguous" in item.message
                for item in report.diagnostics
            )
        )

    # 测试输入：wait(1)，domain 已证明而 boundary 仍为 unknown。
    # 预期行为：通信规则虽成立，但自然超时规则尚未排除且结论类型不同，因此
    #           总体为 unknown，不能先返回 delay(1).bottom。
    # 检查内容：inferred_type=None、两组义务均为未选证据及专门的未唯一诊断。
    # 论文对应：选择规则需要排除非等价的另一棵可能推导树。
    def test_proved_plus_non_equivalent_unknown_is_not_unique(self) -> None:
        """一个真候选不能掩盖另一条仍可能成立的非等价候选。"""

        report, calls = _check_wait(
            domain=Verdict.TRUE,
            boundary=Verdict.UNKNOWN,
        )

        self.assertEqual(report.verdict, Verdict.UNKNOWN)
        self.assertIsNone(report.inferred_type)
        self.assertEqual(calls, ("domain", "boundary"))
        self.assertEqual(
            tuple(item.active for item in report.obligations),
            (True, False, False, False, False),
        )
        self.assertTrue(
            any(
                item.rule == "T-ODE-Select"
                and "not unique yet" in item.message
                for item in report.diagnostics
            )
        )


if __name__ == "__main__":
    unittest.main()
