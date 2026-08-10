r"""验证项目根包公开的单入口 HCSP 类型构造接口。

测试内容
--------
1. 根包只暴露 ``construct_hcsp_type``、正式 Type AST 抽象、输出模式和公共异常；
2. 单进程与并行 source 都能由一次调用直接转换为正式 Type AST；
3. ``none``、``result``、``full`` 只改变打印详细程度，不改变推导结果；
4. concrete syntax 解析失败时立即抛 ``HCSPInputError``，类型构造器不会启动；
5. ``false`` 时抛 ``HCSPTypeConstructionError`` 并保留部分推导；``unknown`` 且推导完成时抛
   ``HCSPUntrustedTypeConstructionError``，通过 ``untrusted_type`` 提供完整但不可信的候选；
6. 并行初态数量、初态元素类型和字符串路径条件都由同一个入口规范化。

论文对应
--------
本文件锁定的是论文模型外层的工程封装，而不重复测试 Table 2 的每条规则。
调用者提交同一份包含参数背景 H、Gamma、Theta 与 Process 的完整 source；入口在
内部完成 source -> Process AST -> Type AST 全流程，并且只在完整判断为 ``true``
时把论文意义下的配置类型 ``mathcal T`` 作为普通返回值。``unknown`` 时完整
候选只作为带明确不可信标记的异常数据，不能被误用为已证 Type AST；中间
Process AST 始终不对外暴露。
"""

from __future__ import annotations

from io import StringIO
import unittest
from unittest.mock import patch

import hcsp_typechecker
from hcsp_typechecker import (
    HCSPInputError,
    HCSPTypeConstructionError,
    HCSPUntrustedTypeConstructionError,
    OutputMode,
    TypeAST,
    construct_hcsp_type,
)


_SKIP_SOURCE = """gamma()
theta()
process {{skip}}"""

_COMMUNICATION_SOURCE = """gamma(x: Int)
parameters(limit: Int) where(limit >= 0)
theta(ch: channel(value: Int))
process {{ch?(x); ch!(x)}}"""

_PARALLEL_SOURCE = """gamma()
theta()
process {{skip}, {skip}}"""


class PublicFacadeTests(unittest.TestCase):
    """锁定普通调用者可见的名称、返回值、输出和失败协议。"""

    # 测试输入：直接查看根包导出白名单以及旧两阶段接口和内部实现名称。
    # 预期行为：根包只导出一个业务函数；不存在可公开取得 Process AST 的程序容器。
    # 检查内容：精确比较 __all__，并确认两阶段函数、HCSPProgram 和 AST 构造器均隐藏。
    # 论文对应：Process AST 只是应用规则所需的内部中间表示，不是类型判断的最终结果。
    def test_root_package_exports_only_one_business_entrypoint(self) -> None:
        """普通调用者应只看到 source 到 Type AST 的单一业务入口。"""

        expected = {
            "HCSPInputError",
            "HCSPTypeConstructionError",
            "HCSPUntrustedTypeConstructionError",
            "OutputMode",
            "TypeAST",
            "construct_hcsp_type",
        }

        self.assertEqual(set(hcsp_typechecker.__all__), expected)
        self.assertEqual(len(hcsp_typechecker.__all__), len(expected))
        for name in expected:
            with self.subTest(public_name=name):
                self.assertTrue(hasattr(hcsp_typechecker, name))
        for hidden_name in (
            "HCSPProgram",
            "parse_hcsp_program",
            "infer_hcsp_type",
            "TypeConstructor",
            "BasicType",
            # 下列名称属于重命名前的公开/内部术语，不得作为兼容别名残留。
            "typecheck_hcsp",
            "TypeChecker",
            "CheckReport",
            "TypingJudgment",
            "InferenceStep",
            "HCSPTypeError",
            "HCSPUntrustedTypeError",
        ):
            with self.subTest(hidden_name=hidden_name):
                self.assertFalse(hasattr(hcsp_typechecker, hidden_name))

    # 测试输入：含参数、Gamma、Theta 和 ch?(x); ch!(x) 的完整单进程 source。
    # 预期行为：一次调用直接返回 ch?.(ch!.(0))，调用者不处理任何中间程序对象。
    # 检查内容：返回 TypeAST 抽象类别，并核对输入、输出与终止类型的嵌套结构文本。
    # 论文对应：内部依次使用 T-sigma、T-In、T-Out 与 T-End 形成过程类型。
    def test_single_process_directly_returns_type_ast(self) -> None:
        """完整单进程 source 应由单入口直接转换成正式 Type AST。"""

        constructed = construct_hcsp_type(
            _COMMUNICATION_SOURCE,
            source_name="communication.hcsp",
        )

        self.assertIsInstance(constructed, TypeAST)
        self.assertEqual(str(constructed), "ch?.(ch!.(0))")

    # 测试输入：两个独立 skip 块构成的顶层并行 source，并给出两个有序初态。
    # 预期行为：入口在内部拆分顶层 Process 叶子并返回配置类型 (0) | (0)。
    # 检查内容：直接核对 TypeAST 类别和并行类型文本，不读取内部 process_components。
    # 论文对应：系统层并行判断把两个 T-End 结果组合为配置类型 mathcal T。
    def test_parallel_process_directly_returns_type_ast(self) -> None:
        """并行 source 的内部配置组装不应成为用户必须执行的额外阶段。"""

        constructed = construct_hcsp_type(
            _PARALLEL_SOURCE,
            initial_states=({}, {}),
        )

        self.assertIsInstance(constructed, TypeAST)
        self.assertEqual(str(constructed), "(0) | (0)")

    # 测试输入：同一份 skip source 分别采用 none、result、full 三种输出模式。
    # 预期行为：三次调用返回完全相同的 Type AST；摘要只给最终结果，完整日志还给出
    #           原始 source、阶段状态、实际执行的规则和证明义务，但不打印 Process AST。
    # 检查内容：比较输出层级及返回对象相等性，并防止旧两阶段标题/AST repr 回流。
    # 论文对应：日志是推导过程的可视化，不参与 source 到配置类型的数学变换。
    def test_output_modes_only_change_rendering_detail(self) -> None:
        """静默、结果和完整日志必须共享同一条单入口推导语义。"""

        silent = StringIO()
        result_stream = StringIO()
        full_stream = StringIO()

        silent_type = construct_hcsp_type(
            _SKIP_SOURCE,
            output=OutputMode.NONE,
            stream=silent,
        )
        result_type = construct_hcsp_type(
            _SKIP_SOURCE,
            output=" RESULT ",
            stream=result_stream,
        )
        full_type = construct_hcsp_type(
            _SKIP_SOURCE,
            source_name="skip.hcsp",
            output=OutputMode.FULL,
            stream=full_stream,
        )

        result_text = result_stream.getvalue()
        full_text = full_stream.getvalue()
        self.assertEqual(silent.getvalue(), "")
        self.assertIn("Type AST", result_text)
        self.assertIn("Verdict : true", result_text)
        self.assertNotIn("规则执行过程", result_text)
        self.assertNotIn("原始用户输入", result_text)
        self.assertIn("skip.hcsp", full_text)
        self.assertIn(_SKIP_SOURCE, full_text)
        self.assertIn("类型构造与证明详细报告", full_text)
        self.assertIn("规则执行过程", full_text)
        self.assertIn(
            "Process AST : 已在内部构造，不作为公共对象暴露",
            full_text,
        )
        self.assertNotIn("Skip()", full_text)
        self.assertNotIn("Parallel(", full_text)
        self.assertNotIn("HCSPProgram", full_text)
        self.assertEqual(silent_type, result_type)
        self.assertEqual(result_type, full_type)

    # 测试输入：缺少 process 右花括号的非法 source，并分别请求 result/full 日志。
    # 预期行为：入口定位错误后立即抛 HCSPInputError；内部类型构造函数从未被调用。
    # 检查内容：摘要含来源与行列；完整日志还含原始行、syntax error 和插入符；
    #           mock 的 construct_type 调用次数保持为零，证明流程确实在解析边界停止。
    # 论文对应：尚未形成 Process AST 时不存在可以提交给 Table 2 的判断对象。
    def test_parse_failure_stops_before_type_construction(self) -> None:
        """解析失败必须终止整个单入口调用，而不能继续使用残缺 AST 推导。"""

        broken = "gamma()\ntheta()\nprocess {{skip"
        result_stream = StringIO()
        full_stream = StringIO()

        with patch("hcsp_typechecker.api.construct_type") as constructor:
            with self.assertRaises(HCSPInputError):
                construct_hcsp_type(
                    broken,
                    source_name="broken.hcsp",
                    output="result",
                    stream=result_stream,
                )
            with self.assertRaises(HCSPInputError):
                construct_hcsp_type(
                    broken,
                    source_name="broken.hcsp",
                    output="full",
                    stream=full_stream,
                )
            constructor.assert_not_called()

        self.assertIn("失败", result_stream.getvalue())
        self.assertIn("broken.hcsp:3:15", result_stream.getvalue())
        self.assertNotIn("process {{skip", result_stream.getvalue())
        self.assertIn("process {{skip", full_stream.getvalue())
        self.assertIn("syntax error", full_stream.getvalue())
        self.assertIn("^", full_stream.getvalue())
        self.assertNotIn("规则执行过程", full_stream.getvalue())

    # 测试输入：路径条件为 true、程序断言为 false 的语法正确 source。
    # 预期行为：推导在 T-Assert 的 false 前提处停止并抛 HCSPTypeConstructionError，不返回 Type AST。
    # 检查内容：异常保留 verdict/reason/部分类型和摘要，但没有 program/process_ast 属性；
    #           result 模式写出的内容与异常自身的摘要完全相同。
    # 论文对应：规则前提被否证时，完整类型判断不存在正式右侧类型。
    def test_false_construction_raises_error_with_partial_derivation(self) -> None:
        """已否证前提必须报告停止点，且不得通过异常泄露中间程序容器。"""

        output = StringIO()
        with self.assertRaises(HCSPTypeConstructionError) as captured:
            construct_hcsp_type(
                "gamma()\ntheta()\nprocess {{assert(false)}}",
                source_name="false-assert.hcsp",
                output="result",
                stream=output,
            )

        error = captured.exception
        self.assertEqual(error.verdict, "false")
        self.assertEqual(error.partial_types, (None,))
        self.assertTrue(error.reason)
        self.assertFalse(hasattr(error, "program"))
        self.assertFalse(hasattr(error, "process_ast"))
        self.assertIn("Verdict : false", error.format_result())
        self.assertIn("Type AST : None", error.format_result())
        self.assertIn("部分类型 : K1=(none)", error.format_result())
        self.assertIn("推导步骤 : 已执行", error.format_result())
        self.assertIn("停止位置 :", error.format_result())
        self.assertIn("T-Assert", error.format_result())
        self.assertEqual(output.getvalue().strip(), error.format_result())

    # 测试输入：显式有限 ODE 产生 dL 义务，测试替身让证明后端明确不作出判断。
    # 预期行为：入口推导得到 unknown 时仍完成 ODE 类型，但抛出专用
    #           HCSPUntrustedTypeConstructionError，只在 untrusted_type 中暴露该完整候选。
    # 检查内容：verdict、完整不可信类型、完整 dL 日志和显著的信任警告，
    #           同时仍不显示 Process AST repr。
    # 论文对应：论文前提未被证明时候选不是已证判断；unknown 是工具的可审计扩展。
    def test_unknown_construction_exposes_only_an_explicit_untrusted_type(self) -> None:
        """外部证明无结论时应保留完整推导，但不得伪装成普通成功返回。"""

        output = StringIO()
        with patch(
            "hcsp_typechecker.typechecking.constructor."
            "KeYmaeraXBackend.__call__",
            return_value=None,
        ):
            with self.assertRaises(HCSPUntrustedTypeConstructionError) as captured:
                construct_hcsp_type(
                    "gamma()\ntheta()\nprocess {{ode(flow(), domain(t < 1), delay(1))}}",
                    source_name="unknown-ode.hcsp",
                    output="full",
                    stream=output,
                )

        error = captured.exception
        self.assertIsInstance(error, HCSPTypeConstructionError)
        self.assertEqual(error.verdict, "unknown")
        self.assertIsInstance(error.untrusted_type, TypeAST)
        self.assertEqual(str(error.untrusted_type), "delay(1).(0)")
        self.assertEqual(error.partial_types, (error.untrusted_type,))
        self.assertFalse(hasattr(error, "program"))
        self.assertIn("Verdict : unknown", str(error))
        self.assertIn("完整候选 Type", error.format_result())
        self.assertIn("不可信（未验证）", error.format_result())
        self.assertIn("类型构造与证明详细报告", error.format_full())
        self.assertIn("dL", error.format_full())
        self.assertIn("规则推导 : 已完成", error.format_full())
        self.assertIn("完整候选，未验证", error.format_full())
        self.assertIn(
            "Process AST : 已在内部构造，不作为公共对象暴露",
            error.format_full(),
        )
        self.assertNotIn("ODE(", error.format_full())
        self.assertEqual(output.getvalue().rstrip("\n"), error.format_full())
        self.assertEqual(output.getvalue().count("类型构造与证明详细报告"), 1)

    # 测试输入：两分量并行 source 分别给单 mapping、一个 mapping 的序列和含非
    #           mapping 的序列。
    # 预期行为：同一入口在推导前拒绝歧义数量、错误数量和错误元素类型。
    # 检查内容：三种错误分别稳定抛 ValueError、ValueError 与 TypeError。
    # 论文对应：并行规则要求每个顶层 Process 分量恰有一个对应初始状态 sigma。
    def test_parallel_initial_state_shape_is_validated_by_single_entrypoint(self) -> None:
        """并行初态必须按源码分量顺序一一给出。"""

        with self.assertRaisesRegex(ValueError, "one initial-state mapping"):
            construct_hcsp_type(_PARALLEL_SOURCE, initial_states={})
        with self.assertRaisesRegex(ValueError, r"components \(2\)"):
            construct_hcsp_type(_PARALLEL_SOURCE, initial_states=({},))
        with self.assertRaisesRegex(TypeError, "every initial state"):
            construct_hcsp_type(
                _PARALLEL_SOURCE,
                initial_states=({}, 0),  # type: ignore[arg-type]
            )

    # 测试输入：Gamma 声明 x:Int，初态 x=1，合法路径条件 x >= 0；随后传入 x >=。
    # 预期行为：合法字符串经严格 Expr 前端解析并由 T-sigma 证明；非法字符串在同一
    #           接口内以 HCSPInputError 结束，并把来源标记为 path_condition。
    # 检查内容：成功返回终止类型；失败 full 日志包含精确的派生来源和定位诊断。
    # 论文对应：字符串表示判断左侧 phi，T-sigma 检查 models phi[sigma]。
    def test_path_condition_uses_strict_expression_frontend(self) -> None:
        """主 source 与路径条件应共享一个用户级调用和统一的词法边界。"""

        source = "gamma(x: Int)\ntheta()\nprocess {{skip}}"
        constructed = construct_hcsp_type(
            source,
            source_name="path-demo.hcsp",
            initial_states={"x": 1},
            path_condition="x >= 0",
        )

        self.assertIsInstance(constructed, TypeAST)
        self.assertEqual(str(constructed), "0")
        error_output = StringIO()
        with self.assertRaises(HCSPInputError) as captured:
            construct_hcsp_type(
                source,
                source_name="path-demo.hcsp",
                path_condition="x >=",
                output="full",
                stream=error_output,
            )
        self.assertEqual(
            captured.exception.source_name,
            "path-demo.hcsp:path_condition",
        )
        self.assertIn("路径条件解析失败", error_output.getvalue())
        self.assertIn("path-demo.hcsp:path_condition", error_output.getvalue())

    # 测试输入：给单入口传入不存在的输出级别。
    # 预期行为：在解析和推导前以稳定 ValueError 拒绝，错误列出三种可用模式。
    # 检查内容：异常文本包含 none/result/full，防止悄悄降级成任意一种模式。
    # 论文对应：这是纯展示层约束，不改变任何论文判断。
    def test_invalid_output_mode_is_rejected(self) -> None:
        """单入口只接受文档承诺的三种日志详细度。"""

        with self.assertRaisesRegex(ValueError, "none.*result.*full"):
            construct_hcsp_type(_SKIP_SOURCE, output="verbose")


if __name__ == "__main__":
    unittest.main()
