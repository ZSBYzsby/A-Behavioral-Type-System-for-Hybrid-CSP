r"""公式和子 judgment 失败后的严格短路测试。

测试内容
--------
1. T-Assert 的公式为 false 时，不再访问顺序后继；
2. T-ODE 的 dL 公式为 unknown 时，不再构造 ODE 后继类型；
3. T-If 的第一个子 judgment 失败时，不再检查第二个兄弟分支；
4. 顶层 T-|| 在某配置失败后停止后续配置，同时保留此前完成的分量类型。

预期行为
--------
每个 premise 只有判为 true 才允许推导继续。false/unknown 义务、或失败的子
judgment，都会令当前规则返回内部失败标记；最终 ``inferred_type`` 为 None。
报告只包含停止点以前实际产生的 obligations/steps/diagnostics，未访问代码不能
留下规则步骤或次生错误。顶层多配置报告仍用 ``component_types`` 保存已经完成
的前缀分量，停止点及其后的分量均为 None。

论文对应
--------
Table 2 的一条类型规则只有在横线上方的全部 premises 都成立时才能使用。本文件
测试实现层的求解顺序与失败传播，不为论文规则增加新的逻辑前提。
"""

from __future__ import annotations

from math import inf
import unittest

from hcsp_typechecker import (
    Assert,
    BasicType,
    Configuration,
    ContinuousType,
    EndType,
    If,
    InputChannel,
    ODE,
    ODEAnnotation,
    OutputChannel,
    Sequence,
    Skip,
    Verdict,
    check_hcsp,
)


class DerivationShortCircuitTests(unittest.TestCase):
    """验证非真公式和失败子判断都只留下推导前缀。"""

    # 测试输入：assert(false) 后接一个未在 Theta 声明的输出通道。
    # 预期行为：T-Assert 义务为 false 后立即停止；T-Out 永远不会被访问，
    #           因而既没有 T-Out 步骤，也没有 missing 通道诊断。
    # 检查内容：类型、义务规则、步骤规则和诊断均只来自停止点以前。
    # 论文对应：T-Assert 的 ``phi => B`` 不成立时无规则结论。
    def test_false_formula_stops_before_sequential_successor(self) -> None:
        """已否证的断言不能继续检查或包装其顺序后继。"""

        report = check_hcsp(
            gamma={},
            theta={},
            configurations=[
                Configuration(
                    {},
                    Sequence.of(Assert(False), OutputChannel("missing", 0)),
                )
            ],
        )

        self.assertEqual(report.verdict, Verdict.FALSE)
        self.assertIsNone(report.inferred_type)
        self.assertEqual(
            tuple(item.rule for item in report.obligations),
            ("T-sigma", "T-Assert"),
        )
        self.assertFalse(any(item.rule == "T-Out" for item in report.steps))
        self.assertFalse(
            any("missing" in item.message for item in report.diagnostics)
        )

    # 测试输入：无限 delay ODE 的 safety 为 x>=0，dL 后端返回 unknown；后继
    #           是一个未声明通道输入。
    # 预期行为：ODE-safety 记录 unknown 后停止，不再生成 domain 义务、事件
    #           类型或输入通道诊断，最终类型为 None。
    # 检查内容：只保留一条 unknown safety 义务，不访问 T-In。
    # 论文对应：T-ODE 的 safety dL premise 未建立时不能使用规则结论。
    def test_unknown_formula_stops_ode_before_its_successor(self) -> None:
        """证明器未知不是成功，不能保守地拼接 ODE 候选类型。"""

        process = Sequence.of(
            ODE(
                [("x", 1)],
                True,
                annotation=ODEAnnotation(safety="x >= 0", delay=inf),
            ),
            InputChannel("missing", "received"),
        )
        report = check_hcsp(
            gamma={"x": BasicType.REAL, "ode_x": ContinuousType(("x",))},
            theta={},
            configurations=[Configuration({"x": 0}, process)],
            dl_checker=lambda _obligation: None,
        )

        self.assertEqual(report.verdict, Verdict.UNKNOWN)
        self.assertIsNone(report.inferred_type)
        ode_obligations = tuple(
            item for item in report.obligations if item.rule.startswith("T-ODE")
        )
        self.assertEqual(len(ode_obligations), 1)
        self.assertEqual(ode_obligations[0].rule, "T-ODE-safety")
        self.assertEqual(ode_obligations[0].verdict, Verdict.UNKNOWN)
        self.assertFalse(any(item.rule == "T-In" for item in report.steps))
        self.assertFalse(
            any("missing" in item.message for item in report.diagnostics)
        )

    # 测试输入：if true then assert(false) else missing?x。
    # 预期行为：then 子 judgment 失败后，T-If 不再访问 else 兄弟 premise；
    #           最终无 InternalChoiceType，也没有 T-In 相关记录。
    # 检查内容：无正式类型、无 T-In 步骤、无未声明通道诊断。
    # 论文对应：T-If 的两个进程 premise 都必须成立，任一个失败即无结论。
    def test_failed_child_stops_later_sibling_premise(self) -> None:
        """子 judgment 失败必须向父规则传播并截断后续兄弟分支。"""

        report = check_hcsp(
            gamma={},
            theta={},
            configurations=[
                Configuration(
                    {},
                    If(True, Assert(False), InputChannel("missing", "x")),
                )
            ],
        )

        self.assertEqual(report.verdict, Verdict.FALSE)
        self.assertIsNone(report.inferred_type)
        self.assertFalse(any(item.rule == "T-In" for item in report.steps))
        self.assertFalse(
            any("missing" in item.message for item in report.diagnostics)
        )

    # 测试输入：三个无状态配置依次为 skip、assert(false)、missing?x。
    # 预期行为：K1 完成 EndType；K2 在断言处失败；K3 完全未访问。总类型为
    #           None，分量报告为 (EndType(), None, None)。
    # 检查内容：核对部分分量类型，并确认 K3 没有任何步骤或诊断。
    # 论文对应：T-|| 需要所有配置 premise；这里验证顺序求解的部分结果表示。
    def test_parallel_report_keeps_only_completed_prefix(self) -> None:
        """顶层失败既不丢失已完成分量，也不继续运行后续配置。"""

        report = check_hcsp(
            gamma={},
            theta={},
            configurations=[
                Configuration({}, Skip(), name="K1"),
                Configuration({}, Assert(False), name="K2"),
                Configuration({}, InputChannel("missing", "x"), name="K3"),
            ],
        )

        self.assertEqual(report.verdict, Verdict.FALSE)
        self.assertIsNone(report.inferred_type)
        self.assertEqual(report.component_types, (EndType(), None, None))
        self.assertFalse(any(item.location == "K3" for item in report.steps))
        self.assertFalse(
            any("missing" in item.message for item in report.diagnostics)
        )


if __name__ == "__main__":
    unittest.main()
