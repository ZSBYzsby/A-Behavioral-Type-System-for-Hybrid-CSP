r"""公式和子 judgment 失败后的严格短路测试。

测试内容
--------
1. T-Assert 的公式为 false 时，不再访问顺序后继；
2. T-ODE 的 dL 公式为 unknown 时，保留未决义务并继续构造完整候选类型；
3. T-If 的第一个子 judgment 失败时，不再检查第二个兄弟分支；
4. 顶层 T-|| 在某配置失败后停止后续配置，同时保留此前完成的分量类型。

预期行为
--------
``false`` 义务或失败的子 judgment 会令当前规则返回内部失败
标记，并保留停止点以前的 obligations/steps/diagnostics。``unknown`` 只表示
证明器尚未建立公式：推导必须继续访问后续 judgment，得到完整但不可信的
``constructed_type``，同时保留 UNKNOWN verdict。顶层多配置的真正失败仍用
``constructed_component_types`` 保存已完成的前缀分量，失败点及其后的分量为 None。

论文对应
--------
Table 2 的一条类型规则只有在横线上方的全部 premises 都成立时才是已证
结论。项目在工具层允许尚未证明的 premise 继续生成候选推导树，但必须把其结果
标记为 UNKNOWN/不可信；已否证的 premise 仍然使规则失败。
"""

from __future__ import annotations

import unittest

from hcsp_typechecker._internal import (
    Assert,
    BasicType,
    ChannelType,
    Configuration,
    ContinuousType,
    EndType,
    If,
    InputChannel,
    InputType,
    InfiniteDelayType,
    NoInterruptType,
    ODE,
    ODEAnnotation,
    OutputChannel,
    FiniteDelayType,
    Sequence,
    Skip,
    Verdict,
    construct_type,
)


class DerivationShortCircuitTests(unittest.TestCase):
    """区分已否证前提的短路与未决前提的继续推导。"""

    # 测试输入：assert(false) 后接一个未在 Theta 声明的输出通道。
    # 预期行为：T-Assert 义务为 false 后立即停止；T-Out 永远不会被访问，
    #           因而既没有 T-Out 步骤，也没有 missing 通道诊断。
    # 检查内容：类型、义务规则、步骤规则和诊断均只来自停止点以前。
    # 论文对应：T-Assert 的 ``phi => B`` 不成立时无规则结论。
    def test_false_formula_stops_before_sequential_successor(self) -> None:
        """已否证的断言不能继续检查或包装其顺序后继。"""

        report = construct_type(
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
        self.assertIsNone(report.constructed_type)
        self.assertEqual(
            tuple(item.rule for item in report.obligations),
            ("T-sigma", "T-Assert"),
        )
        self.assertFalse(any(item.rule == "T-Out" for item in report.steps))
        self.assertFalse(
            any("missing" in item.message for item in report.diagnostics)
        )

    # 测试输入：有限 ODE 的 safety/boundary 由 dL 后端返回 unknown；
    #           自然到时后执行已在 Theta 声明的 ch?received。
    # 预期行为：两条 ODE 义务保留 unknown，但 T-In 仍被访问，并生成
    #           delay(1).(ch?.0) 完整候选类型；总体 verdict 仍为 unknown。
    # 检查内容：候选类型、两条未决 dL 义务以及后继 T-In 步骤同时存在。
    # 论文对应：横线上方公式未证明时，所得只是不可信的候选推导。
    def test_unknown_formula_is_recorded_while_ode_successor_is_constructed(self) -> None:
        """UNKNOWN 只降低候选类型的可信性，不得截断后继推导。"""

        process = Sequence.of(
            ODE(
                [("x", 1)],
                "t < 1",
                annotation=ODEAnnotation(safety="x >= 0", delay=1),
            ),
            InputChannel("ch", "received"),
        )
        report = construct_type(
            gamma={"x": BasicType.REAL, "ode_x": ContinuousType(("x",))},
            theta={"ch": ChannelType(BasicType.INT)},
            configurations=[Configuration({"x": 0}, process)],
            dl_checker=lambda _obligation: None,
        )

        self.assertEqual(report.verdict, Verdict.UNKNOWN)
        self.assertEqual(
            report.constructed_type,
            FiniteDelayType(
                1,
                NoInterruptType(),
                InfiniteDelayType(InputType("ch", EndType())),
            ),
        )
        ode_obligations = tuple(
            item for item in report.obligations if item.rule.startswith("T-ODE")
        )
        self.assertEqual(
            tuple(item.rule for item in ode_obligations),
            ("T-ODE-safety", "T-ODE-boundary"),
        )
        self.assertTrue(
            all(item.verdict is Verdict.UNKNOWN for item in ode_obligations)
        )
        self.assertTrue(any(item.rule == "T-In" for item in report.steps))
        self.assertFalse(report.diagnostics)

    # 测试输入：if true then assert(false) else missing?x。
    # 预期行为：then 子 judgment 失败后，T-If 不再访问 else 兄弟 premise；
    #           最终无 InternalChoiceType，也没有 T-In 相关记录。
    # 检查内容：无正式类型、无 T-In 步骤、无未声明通道诊断。
    # 论文对应：T-If 的两个进程 premise 都必须成立，任一个失败即无结论。
    def test_failed_child_stops_later_sibling_premise(self) -> None:
        """子 judgment 失败必须向父规则传播并截断后续兄弟分支。"""

        report = construct_type(
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
        self.assertIsNone(report.constructed_type)
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

        report = construct_type(
            gamma={},
            theta={},
            configurations=[
                Configuration({}, Skip(), name="K1"),
                Configuration({}, Assert(False), name="K2"),
                Configuration({}, InputChannel("missing", "x"), name="K3"),
            ],
        )

        self.assertEqual(report.verdict, Verdict.FALSE)
        self.assertIsNone(report.constructed_type)
        self.assertEqual(report.constructed_component_types, (EndType(), None, None))
        self.assertFalse(any(item.location == "K3" for item in report.steps))
        self.assertFalse(
            any("missing" in item.message for item in report.diagnostics)
        )


if __name__ == "__main__":
    unittest.main()
