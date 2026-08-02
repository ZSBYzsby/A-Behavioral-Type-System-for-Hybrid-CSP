r"""新版 Table 2 的 ODE 后继路径条件测试。

测试内容
--------
本文件不重复检查 dL 字符串；``tests/dl/test_formula_generation.py`` 已负责
domain、safety 和 boundary 公式。这里隔离检查三个 ODE 后继子 judgment
是否获得准确的前置条件：

1. 纯通信规则的事件后继使用 ``B and safety``；
2. 带自然超时规则的通信后继只使用 ``safety``；
3. 带自然超时规则的自然后继使用 ``not B and safety``。

测试把 dL 后端固定为可信 ``true``，使结果只取决于后继中的 ``T-Assert``，
不会把公式证明器是否安装混入路径条件测试。

论文对应
--------
对应新版论文 Table 2 的两条 ODE 行为规则：第一条规则在 ``B and safety`` 下
检查纯通信事件；第二条规则分别在 ``safety`` 与 ``not B and safety`` 下检查
通信中断和自然超时后继。
"""

from __future__ import annotations

import unittest

from hcsp_typechecker import (
    Assert,
    BasicType,
    ChannelType,
    Configuration,
    EventChoice,
    ODE,
    ODEAnnotation,
    OutputChannel,
    Sequence,
    Skip,
    Verdict,
    check_hcsp,
)


def _approve_dl(_formula: object) -> Verdict:
    """让本组测试只观察 FOL 后继条件，不依赖外部 KeYmaera X。"""

    return Verdict.TRUE


def _assertion_verdict(report) -> Verdict:
    """取得场景中唯一 T-Assert 义务的判定结果。"""

    assertions = [
        obligation
        for obligation in report.obligations
        if obligation.rule == "T-Assert"
    ]
    if len(assertions) != 1:
        raise AssertionError(f"expected one T-Assert obligation, got {assertions!r}")
    return assertions[0].verdict


class ODETable2SuccessorContextTests(unittest.TestCase):
    """逐一验证新版 Table 2 的三个 ODE 子 judgment 前置条件。"""

    # 测试输入：无自然顺序后继的 ODE，事件 alarm! 后断言当前状态仍在 x<1。
    # 预期行为：断言成立，因为纯通信规则在 ``B and safety`` 下检查 E。
    # 检查内容：可信 dL 后端隔离连续证明，只核对 T-Assert 得到 true。
    # 论文对应：Table 2 第一条 ODE 行为规则的 ``Gamma.Theta.B∧phi |- E::A``。
    def test_communication_only_event_receives_domain_and_safety(self) -> None:
        """纯通信事件后继可以使用演化域和安全批注。"""

        process = ODE(
            [("x", 1)],
            "x < 1",
            EventChoice(OutputChannel("alarm", 0), Assert("x < 1")),
            annotation=ODEAnnotation(safety=True, delay=1),
        )
        report = check_hcsp(
            gamma={"x": BasicType.REAL},
            theta={"alarm": ChannelType(BasicType.INT)},
            configurations=[Configuration({"x": 0}, process)],
            path_condition="x == 0",
            dl_checker=_approve_dl,
        )

        self.assertEqual(report.verdict, Verdict.TRUE)
        self.assertEqual(_assertion_verdict(report), Verdict.TRUE)

    # 测试输入：同一 ODE 显式后接 Skip，使其采用带自然超时的规则；事件后继
    #           仍尝试断言 x<1，而 safety=true 不提供该事实。
    # 预期行为：断言为 false，证明实现没有从另一条规则错误继承 B。
    # 检查内容：边界 dL 由可信后端批准，只观察事件 continuation 的路径条件。
    # 论文对应：超时规则的 ``Gamma.Theta.phi |- E;P::A``，其中不含 B。
    def test_timed_event_does_not_receive_domain_assumption(self) -> None:
        """带超时规则的通信后继不能额外假设演化域 B。"""

        evolution = ODE(
            [("x", 1)],
            "x < 1",
            EventChoice(OutputChannel("alarm", 0), Assert("x < 1")),
            annotation=ODEAnnotation(safety=True, delay=1),
        )
        report = check_hcsp(
            gamma={"x": BasicType.REAL},
            theta={"alarm": ChannelType(BasicType.INT)},
            configurations=[Configuration({"x": 0}, Sequence(evolution, Skip()))],
            path_condition="x == 0",
            dl_checker=_approve_dl,
        )

        self.assertEqual(report.verdict, Verdict.FALSE)
        self.assertEqual(_assertion_verdict(report), Verdict.FALSE)

    # 测试输入：边界 B 为 x<1 的 ODE 自然结束后断言 x>=1。
    # 预期行为：断言成立，因为自然后继在 ``not B and safety`` 下检查。
    # 检查内容：若实现像旧版一样只传递 safety=true，本断言会被判为 false。
    # 论文对应：超时规则的 ``Gamma.Theta.not B∧phi |- P::T``。
    def test_timeout_continuation_receives_not_domain_and_safety(self) -> None:
        """自然超时后继可以使用演化域已经失效这一事实。"""

        process = Sequence.of(
            ODE(
                [("x", 1)],
                "x < 1",
                annotation=ODEAnnotation(safety=True, delay=1),
            ),
            Assert("x >= 1"),
        )
        report = check_hcsp(
            gamma={"x": BasicType.REAL},
            theta={},
            configurations=[Configuration({"x": 0}, process)],
            path_condition="x == 0",
            dl_checker=_approve_dl,
        )

        self.assertEqual(report.verdict, Verdict.TRUE)
        self.assertEqual(_assertion_verdict(report), Verdict.TRUE)


if __name__ == "__main__":
    unittest.main()
