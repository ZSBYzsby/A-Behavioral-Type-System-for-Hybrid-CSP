r"""Definition 4.1 连续 Gamma 项及 T-ODE 使用边界测试。

测试内容
--------
1. ``ContinuousType`` 声明的变量可以组成 ODE 向量，普通 Real 参数仍可出现在
   导数、路径和 safety 中；
2. 普通 ``BasicType.REAL`` 不能冒充 ODE 左端的连续变量；
3. 离散赋值和通信输入只更新连续变量的当前值，不删除连续类别；
4. 连续变量在 ODE 外按当前 Real 值参与普通表达式和输出；
5. 顶层/局部 Gamma 必须同时保持基础类型与连续类别一致。

预期行为
--------
Gamma 显式区分 ``x:Real`` 与 ``x:ContinuousType``。表达式层把后者读取为 Real，
但 T-ODE 只接受后者作为微分方程左端。非法普通 Real ODE 在建立 dL 义务前
静态失败；合法连续变量经过赋值或输入后仍可继续演化。

论文对应
--------
对应 Definition 4.1 的普通值项 ``x:B`` 与连续轨迹项
``underlined(v):R_{>=0} partial-function R^n``，以及 Table 2 [T-ODE]。
"""

from __future__ import annotations

from math import inf
import unittest

from hcsp_typechecker import (
    Assign,
    BasicType,
    ChannelType,
    Configuration,
    ContinuousType,
    EndType,
    InputChannel,
    ODE,
    ODEAnnotation,
    OutputChannel,
    OutputType,
    Sequence,
    Skip,
    Verdict,
    check_hcsp,
)


def _approve_dl(_obligation: object) -> Verdict:
    """固定证明测试产生的非平凡 dL premise。"""

    return Verdict.TRUE


class ContinuousGammaTests(unittest.TestCase):
    """验证连续声明、当前值读取以及 ODE 左端资格。"""

    # 测试输入：x、v 为连续 Real，gain 为普通 Real；ODE 使用三者构造向量场。
    # 预期行为：连续向量通过 T-ODE，普通参数可读取但不被误当成演化变量。
    # 检查内容：总体 true、正式类型存在、T-ODE 步骤显示两类 Gamma 项。
    # 论文对应：[T-ODE] 要求 v 向量连续，而 e 可读取 Gamma 中普通值变量。
    def test_explicit_continuous_vector_accepts_ordinary_real_parameter(self) -> None:
        """ODE 左端连续声明与右端普通 Real 参数可以共存。"""

        process = ODE(
            [("x", "v"), ("v", "-x * gain")],
            "x * x + v * v <= 4",
            annotation=ODEAnnotation(
                safety="x * x + v * v <= 4",
                delay=inf,
            ),
        )
        report = check_hcsp(
            gamma={
                "x": ContinuousType(),
                "v": ContinuousType(),
                "gain": BasicType.REAL,
            },
            theta={},
            configurations=[
                Configuration({"x": 0, "v": 1, "gain": 1}, process)
            ],
            path_condition="x == 0 and v == 1 and gain == 1",
            dl_checker=_approve_dl,
        )

        self.assertEqual(report.verdict, Verdict.TRUE)
        self.assertIsNotNone(report.inferred_type)
        ode_step = next(item for item in report.steps if item.rule == "T-ODE")
        self.assertIn(("x", "R>=0 ~> Real"), ode_step.gamma)
        self.assertIn(("v", "R>=0 ~> Real"), ode_step.gamma)
        self.assertIn(("gain", "Real"), ode_step.gamma)

    # 测试输入：x 只声明为普通 BasicType.REAL，却出现在 ODE 方程左端。
    # 预期行为：T-ODE 静态失败、无正式类型，且 dL 后端不会被调用。
    # 检查内容：ContinuousType 定位诊断和空 ODE 证明义务集合。
    # 论文对应：普通 x:R 与 underlined(x):trajectory 是不同 Gamma 项。
    def test_ordinary_real_cannot_be_an_ode_lvalue(self) -> None:
        """普通 Real 声明不能依靠 ODE 语法被隐式升级成连续变量。"""

        calls: list[object] = []

        def backend(obligation: object) -> Verdict:
            """记录不应发生的 dL 后端调用。"""

            calls.append(obligation)
            return Verdict.TRUE

        report = check_hcsp(
            gamma={"x": BasicType.REAL},
            theta={},
            configurations=[
                Configuration(
                    {"x": 0},
                    ODE(
                        [("x", 1)],
                        True,
                        annotation=ODEAnnotation(delay=inf),
                    ),
                )
            ],
            dl_checker=backend,
        )

        self.assertEqual(report.verdict, Verdict.FALSE)
        self.assertIsNone(report.inferred_type)
        self.assertEqual(calls, [])
        self.assertFalse(
            any(item.rule.startswith("T-ODE-") for item in report.obligations)
        )
        self.assertTrue(
            any("must have ContinuousType" in item.message for item in report.diagnostics)
        )

    # 测试输入：连续 x 先执行离散赋值 x:=0，再进入 x'=1 的 ODE。
    # 预期行为：赋值使用 x 的 Real 当前值类型，后继 Gamma 仍将 x 标记为连续。
    # 检查内容：T-Assign 和 T-ODE 都执行、总体 true、ODE 步骤仍显示连续声明。
    # 论文对应：连续变量在 ODE 外表示当前状态值，但其轨迹类别不能被赋值删除。
    def test_assignment_preserves_continuous_declaration(self) -> None:
        """离散重置连续变量后仍可把它作为 ODE 左端。"""

        process = Sequence.of(
            Assign("x", 0),
            ODE(
                [("x", 1)],
                True,
                annotation=ODEAnnotation(delay=inf),
            ),
        )
        report = check_hcsp(
            gamma={"x": ContinuousType()},
            theta={},
            configurations=[Configuration({"x": 2}, process)],
            dl_checker=_approve_dl,
        )

        self.assertEqual(report.verdict, Verdict.TRUE)
        self.assertIsNotNone(report.inferred_type)
        self.assertTrue(any(item.rule == "T-Assign" for item in report.steps))
        ode_step = next(item for item in report.steps if item.rule == "T-ODE")
        self.assertIn(("x", "R>=0 ~> Real"), ode_step.gamma)

    # 测试输入：连续 x 从 Real 通道接收新值，然后进入 x'=1 的 ODE。
    # 预期行为：T-In 更新当前符号但保留 ContinuousType，随后 T-ODE 成功。
    # 检查内容：输入/ODE 两个规则步骤和 ODE 入口 Gamma 快照。
    # 论文对应：输入更新当前值；连续轨迹声明仍属于外层 Gamma。
    def test_input_preserves_continuous_declaration(self) -> None:
        """通信写入连续变量不能把它降级成普通通道载荷类型。"""

        process = Sequence.of(
            InputChannel("reset", "x"),
            ODE(
                [("x", 1)],
                True,
                annotation=ODEAnnotation(delay=inf),
            ),
        )
        report = check_hcsp(
            gamma={"x": ContinuousType()},
            theta={"reset": ChannelType(BasicType.REAL)},
            configurations=[Configuration({}, process)],
            dl_checker=_approve_dl,
        )

        self.assertEqual(report.verdict, Verdict.TRUE)
        self.assertIsNotNone(report.inferred_type)
        self.assertTrue(any(item.rule == "T-In" for item in report.steps))
        ode_step = next(item for item in report.steps if item.rule == "T-ODE")
        self.assertIn(("x", "R>=0 ~> Real"), ode_step.gamma)

    # 测试输入：连续 x 不进入 ODE，只把当前值发送到 Real 通道。
    # 预期行为：表达式翻译把 x 读取为 Real，生成普通 OutputType。
    # 检查内容：总体 true 和精确输出类型，不要求变量必须在每个进程中演化。
    # 论文对应：连续变量未出现在 ODE 内时表示其当前状态值。
    def test_continuous_variable_reads_as_real_outside_ode(self) -> None:
        """连续变量的当前值可用于普通表达式、断言和通信。"""

        report = check_hcsp(
            gamma={"x": ContinuousType()},
            theta={"sample": ChannelType(BasicType.REAL)},
            configurations=[Configuration({"x": 1}, OutputChannel("sample", "x"))],
            path_condition="x == 1",
        )

        self.assertEqual(report.verdict, Verdict.TRUE)
        self.assertEqual(report.inferred_type, OutputType("sample", EndType()))

    # 测试输入：全局 Gamma 将 x 声明为连续，局部 Gamma 将同名 x 声明为普通 Real。
    # 预期行为：T-parallel 在进入配置推导前拒绝类别变化并返回 None。
    # 检查内容：局部/全局 Gamma 同型检查包含 continuous-vs-ordinary 差异。
    # 论文对应：T-parallel 的 Gamma 分区必须保持原环境项，而不只比较底层 sort。
    def test_local_gamma_cannot_drop_continuous_marker(self) -> None:
        """局部 Gamma 不得把连续 Real 悄悄改写成普通 Real。"""

        report = check_hcsp(
            gamma={"x": ContinuousType()},
            theta={},
            configurations=[
                Configuration(
                    {"x": 0},
                    Skip(),
                    gamma={"x": BasicType.REAL},
                )
            ],
        )

        self.assertEqual(report.verdict, Verdict.FALSE)
        self.assertIsNone(report.inferred_type)
        self.assertTrue(
            any("changes global variable types" in item.message for item in report.diagnostics)
        )


if __name__ == "__main__":
    unittest.main()
