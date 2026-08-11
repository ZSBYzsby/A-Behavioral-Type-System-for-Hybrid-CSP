r"""新版 Table 2 的 ODE 后继路径条件测试。

测试内容
--------
本文件不重复检查 dL 字符串；``tests/dl/test_formula_generation.py`` 已负责
domain、safety 和 boundary 公式。这里隔离检查三个 ODE 后继子 judgment
是否获得准确的前置条件：

1. 纯通信规则的事件后继使用 ``B and safety``；
2. 带自然超时规则的通信后继只使用 ``safety``；
3. 带自然超时规则的自然后继使用 ``not B and safety``。
4. ODE 后继严格使用 Table 2 的 B/safety 条件，不继承任意入口路径约束。

测试把 dL 后端固定为可信 ``true``，使结果只取决于后继中的 ``T-Assert``，
不会把公式证明器是否安装混入路径条件测试。

论文对应
--------
对应新版论文 Table 2 的两条 ODE 行为规则：第一条规则在 ``B and safety`` 下
检查纯通信事件；第二条规则分别在 ``safety`` 与 ``not B and safety`` 下检查
通信中断和自然超时后继。
"""

from __future__ import annotations

from math import inf
import unittest

from hcsp_typechecker._internal import (
    Assign,
    Assert,
    BasicType,
    ChannelType,
    Configuration,
    ContinuousType,
    EventChoice,
    InputChannel,
    ODE,
    ODEAnnotation,
    OutputChannel,
    ParameterEnvironment,
    Sequence,
    Skip,
    Verdict,
    construct_type,
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

        process = Sequence.of(
            ODE(
                [("x", 1)],
                "x < 1",
                EventChoice((OutputChannel("alarm", 0), Assert("x < 1"))),
                annotation=ODEAnnotation(safety=True, delay=inf),
            ),
            Skip(),
        )
        report = construct_type(
            gamma={"x": BasicType.REAL, "ode_x": ContinuousType(("x",))},
            theta={"alarm": ChannelType(BasicType.INT)},
            configurations=[Configuration({"x": 0}, process)],
            path_condition="x == 0",
            dl_checker=_approve_dl,
        )

        self.assertEqual(report.verdict, Verdict.TRUE)
        self.assertEqual(_assertion_verdict(report), Verdict.TRUE)

    # 测试输入：同一 ODE 显式后接 done!0，使其唯一采用带自然超时的规则；事件后继
    #           仍尝试断言 x<1，而 safety=true 不提供该事实。
    # 预期行为：断言为 false，证明实现没有从另一条规则错误继承 B。
    # 检查内容：边界 dL 由可信后端批准，只观察事件 continuation 的路径条件。
    # 论文对应：超时规则的 ``Gamma.Theta.phi |- E;P::A``，其中不含 B。
    def test_timed_event_does_not_receive_domain_assumption(self) -> None:
        """带超时规则的通信后继不能额外假设演化域 B。"""

        evolution = ODE(
            [("x", 1)],
            "x < 1",
            EventChoice((OutputChannel("alarm", 0), Assert("x < 1"))),
            annotation=ODEAnnotation(safety=True, delay=1),
        )
        report = construct_type(
            gamma={"x": BasicType.REAL, "ode_x": ContinuousType(("x",))},
            theta={
                "alarm": ChannelType(BasicType.INT),
                "done": ChannelType(BasicType.INT),
            },
            configurations=[
                Configuration(
                    {"x": 0},
                    Sequence.of(evolution, OutputChannel("done", 0)),
                )
            ],
            path_condition="x == 0",
            dl_checker=_approve_dl,
        )

        self.assertEqual(report.verdict, Verdict.FALSE)
        self.assertEqual(_assertion_verdict(report), Verdict.FALSE)

    # 测试输入：边界 B 为 x<1 的 ODE 自然结束后断言 x>=1。
    # 预期行为：断言成立，因为自然后继在 ``not B and safety`` 下检查。
    # 检查内容：若实现遗漏自然结束所需的 not-domain 条件，本断言会被判为 false。
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
        report = construct_type(
            gamma={"x": BasicType.REAL, "ode_x": ContinuousType(("x",))},
            theta={},
            configurations=[Configuration({"x": 0}, process)],
            path_condition="x == 0",
            dl_checker=_approve_dl,
        )

        self.assertEqual(report.verdict, Verdict.TRUE)
        self.assertEqual(_assertion_verdict(report), Verdict.TRUE)

    # 测试输入：set?(x,y) 联合 refinement 给出 x=0 and y>0，随后 ODE 只演化 x，
    #           自然后继断言未演化变量 y>0。
    # 预期行为：断言为 false；Table 2 的自然后继前提只有 not B and safety，
    #           不自动继承输入 refinement 中关于 y 的事实。
    # 检查内容：确认实现不再添加论文规则之外的 ODE frame 增强。
    # 论文对应：超时规则后继严格使用 ``Gamma.Theta.not B∧phi``。
    def test_ode_drops_precondition_about_unevolved_variable(self) -> None:
        """ODE 后置路径不继承关于未演化变量的入口事实。"""

        process = Sequence.of(
            InputChannel("set", ("x", "y")),
            ODE(
                [("x", 1)],
                "t < 1",
                annotation=ODEAnnotation(safety=True, delay=1),
            ),
            Assert("y > 0"),
        )
        report = construct_type(
            gamma={"x": BasicType.REAL, "ode_x": ContinuousType(("x",))},
            theta={
                "set": ChannelType(
                    (BasicType.REAL, BasicType.REAL),
                    "eta1 == 0 and eta2 > 0",
                )
            },
            configurations=[Configuration({}, process)],
            dl_checker=_approve_dl,
        )

        self.assertEqual(report.verdict, Verdict.FALSE, report.format_detailed())
        self.assertEqual(_assertion_verdict(report), Verdict.FALSE)

    # 测试输入：与上例相同，但自然后继改为断言演化前 refinement 中的 x=0。
    # 预期行为：断言为 false；x 已连续演化，旧输入值约束不能进入后状态。
    # 检查内容：确认演化变量的旧值约束不会进入严格重建的后继路径。
    # 论文对应：ODE 左侧变量的新状态只能由连续语义及 endpoint 条件约束。
    def test_ode_discards_precondition_about_evolved_variable(self) -> None:
        """演化变量的旧值事实不能被误当作 ODE 后状态事实。"""

        process = Sequence.of(
            InputChannel("set", ("x", "y")),
            ODE(
                [("x", 1)],
                "t < 1",
                annotation=ODEAnnotation(safety=True, delay=1),
            ),
            Assert("x == 0"),
        )
        report = construct_type(
            gamma={"x": BasicType.REAL, "ode_x": ContinuousType(("x",))},
            theta={
                "set": ChannelType(
                    (BasicType.REAL, BasicType.REAL),
                    "eta1 == 0 and eta2 > 0",
                )
            },
            configurations=[Configuration({}, process)],
            dl_checker=_approve_dl,
        )

        self.assertEqual(report.verdict, Verdict.FALSE)
        self.assertEqual(_assertion_verdict(report), Verdict.FALSE)

    # 测试输入：输入得到 y>0 后执行 x:=y，再让 ODE 只演化 x，最后断言 y>0。
    # 预期行为：断言为 false；即使 x 与 y 在入口共享符号项，Table 2 的 ODE
    #           后继条件也不会自动携带输入 refinement。
    # 检查内容：确认符号别名不会绕过严格的后继路径重建。
    # 论文对应：后继只使用规则明确给出的 not B and safety。
    def test_ode_drops_aliased_unevolved_precondition(self) -> None:
        """符号别名不能让入口路径事实越过 ODE。"""

        process = Sequence.of(
            InputChannel("set", "y"),
            Assign("x", "y"),
            ODE(
                [("x", 1)],
                "t < 1",
                annotation=ODEAnnotation(safety=True, delay=1),
            ),
            Assert("y > 0"),
        )
        report = construct_type(
            gamma={
                "x": BasicType.REAL,
                "y": BasicType.REAL,
                "ode_x": ContinuousType(("x",)),
            },
            theta={
                "set": ChannelType(BasicType.REAL, "eta > 0")
            },
            configurations=[Configuration({}, process)],
            dl_checker=_approve_dl,
        )

        self.assertEqual(report.verdict, Verdict.FALSE, report.format_detailed())
        self.assertEqual(_assertion_verdict(report), Verdict.FALSE)

    # 测试输入：ODE 后继只断言 Gamma 的 Nat 固有约束和全局参数约束，入口
    #           path 不额外提供这两个事实。
    # 预期行为：断言成立；它们属于持续有效的判断环境，不是被删除的入口路径。
    # 检查内容：防止严格采用 not B and safety 时误删 Gamma/H 的环境语义。
    # 论文对应：ODE 后继仍处在同一个 Gamma；参数 H 是项目的只读环境扩展。
    def test_ode_keeps_gamma_domains_and_parameter_environment(self) -> None:
        """严格后继路径仍应保留 Gamma 与只读参数环境的固有条件。"""

        process = Sequence.of(
            ODE(
                [("x", 1)],
                "t < 1",
                annotation=ODEAnnotation(safety=True, delay=1),
            ),
            Assert("count >= 0 and limit >= 0"),
        )
        report = construct_type(
            gamma={
                "x": BasicType.REAL,
                "count": BasicType.NAT,
                "ode_x": ContinuousType(("x",)),
            },
            theta={},
            parameters=ParameterEnvironment(
                {"limit": BasicType.REAL},
                "limit >= 0",
            ),
            configurations=[Configuration({"count": 0}, process)],
            dl_checker=_approve_dl,
        )

        self.assertEqual(report.verdict, Verdict.TRUE, report.format_detailed())
        self.assertEqual(_assertion_verdict(report), Verdict.TRUE)


if __name__ == "__main__":
    unittest.main()
