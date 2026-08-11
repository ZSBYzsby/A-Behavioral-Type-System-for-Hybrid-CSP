r"""验证项目根包公开的 Type 构造、检查和 Table 3 状态图接口。

测试内容
--------
1. 根包只暴露 TypeConstructor、TypeChecker 与可自行打印结果的状态图生成接口；
2. 单进程与并行 source 都能由一次调用直接转换为正式 Type AST；
3. ``none``、``result``、``full`` 只改变打印详细程度，不改变推导结果；
4. concrete syntax 解析失败时立即抛 ``HCSPInputError``，类型构造器不会启动；
5. ``false`` 时抛 ``HCSPTypeConstructionError`` 并保留部分推导；``unknown`` 且推导完成时抛
   ``HCSPUntrustedTypeConstructionError``，通过 ``untrusted_type`` 提供完整但不可信的候选；
6. 并行初态数量、初态元素类型和字符串路径条件都由同一个入口规范化。
7. 图接口的 result/full 模式分别输出摘要与完整状态图，formatter 不单独公开。

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
    HCSPErrorDetail,
    HCSPInputError,
    HCSPTypeConstructionError,
    HCSPTypeCheckingError,
    HCSPUntrustedTypeConstructionError,
    OutputMode,
    TypeAST,
    TypeCheckingErrorKind,
    TypeConstructionErrorKind,
    TypeTransitionGraph,
    build_type_transition_graph,
    construct_hcsp_type,
    check_hcsp_type,
)
from hcsp_typechecker.frontend.type_syntax import (
    format_type_source,
    parse_type_source,
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
    # 预期行为：根包只导出三个业务接口及其公共结果/异常类型；不公开 formatter。
    # 检查内容：精确比较 __all__，并确认两阶段函数、HCSPProgram 和 AST 构造器均隐藏。
    # 论文对应：Process AST 只是应用规则所需的内部中间表示，不是类型判断的最终结果。
    def test_root_package_exports_only_supported_business_interfaces(self) -> None:
        """普通调用者应只看到已承诺稳定的业务与展示接口。"""

        expected = {
            "HCSPErrorDetail",
            "HCSPInputError",
            "HCSPTypeConstructionError",
            "HCSPTypeCheckingError",
            "HCSPUntrustedTypeConstructionError",
            "OutputMode",
            "TypeAST",
            "TypeCheckingErrorKind",
            "TypeConstructionErrorKind",
            "TypeTransitionGraph",
            "build_type_transition_graph",
            "construct_hcsp_type",
            "check_hcsp_type",
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
            "format_normalized_type_ast",
            "format_type_transition_graph",
        ):
            with self.subTest(hidden_name=hidden_name):
                self.assertFalse(hasattr(hcsp_typechecker, hidden_name))

    # 测试输入：通过公开 TypeConstructor 得到的 skip Type AST。
    # 预期行为：公开图接口返回 complete 的单状态、零边 TypeTransitionGraph。
    # 检查内容：用户无需接触规范化 AST 或后端即可连接 Type 构造与 Table 3 图生成。
    # 论文对应：Table 2 的 skip 得到正常空类型；Table 3 下该类型没有可执行转移。
    def test_constructed_type_can_feed_the_public_graph_interface(self) -> None:
        """第三个根接口直接消费已有正式 Type AST 并返回图数据结构。"""

        constructed = construct_hcsp_type(_SKIP_SOURCE)

        graph = build_type_transition_graph(constructed)

        self.assertIsInstance(graph, TypeTransitionGraph)
        self.assertTrue(graph.complete)
        self.assertEqual(len(graph.states), 1)
        self.assertEqual(graph.transitions, ())

    # 测试输入：skip Type AST 与状态图接口的 result 输出模式。
    # 预期行为：摘要给出图规模、完整性和 ``normalized type empty`` 初态。
    # 检查内容：规范 Type formatter 只在图接口内部使用，不需要独立公开函数。
    # 论文对应：Table 3 状态节点以规范配置类型为内容；本测试只锁定工程展示协议。
    def test_graph_result_mode_prints_the_initial_normalized_type(self) -> None:
        """图接口的摘要模式在内部调用规范类型 formatter。"""

        output = StringIO()

        graph = build_type_transition_graph(
            construct_hcsp_type(_SKIP_SOURCE),
            output="result",
            stream=output,
        )

        self.assertEqual(len(graph.states), 1)
        rendered = output.getvalue()
        self.assertIn("Table 3 状态迁移图结果", rendered)
        self.assertIn("状态数量 : 1", rendered)
        self.assertIn("转移数量 : 0", rendered)
        self.assertIn("完整闭包 : 是", rendered)
        self.assertIn("normalized type empty", rendered)

    # 测试输入：公开接口由 skip 构造的单状态、零转移完整图。
    # 预期行为：整图输出包含初态、完整性、状态块、规范类型和空 transitions 块。
    # 检查内容：普通用户无需遍历内部元组即可获得稳定、完整的图文本。
    # 论文对应：Table 3 下空类型无后继，但仍构成含一个初态的完整可达图。
    def test_graph_full_mode_prints_the_complete_graph(self) -> None:
        """图接口的完整模式在内部调用整图 formatter。"""

        output = StringIO()

        graph = build_type_transition_graph(
            construct_hcsp_type(_SKIP_SOURCE),
            output="full",
            stream=output,
        )

        rendered = output.getvalue().rstrip("\n")

        self.assertEqual(
            rendered,
            "\n".join(
                (
                    "type transition graph {",
                    "    initial = S0",
                    "    complete = true",
                    "    states {",
                    "        S0 = normalized type empty",
                    "    }",
                    "    transitions {}",
                    "}",
                )
            ),
        )

    # 测试输入：skip 的完整 source 与等价的用户 Type 段 empty。
    # 预期行为：TypeChecker 返回用户给定的正式 Type AST。
    # 检查内容：验证完整输入的 type 段解析、Table 2 检查入口和成功返回协议。
    # 论文对应：T-End 的结论为过程空通信行为 0。
    def test_type_checker_accepts_matching_user_type(self) -> None:
        """用户写出的正确 Type 应被 TypeChecker 验证。"""

        output = StringIO()
        checked = check_hcsp_type(
            _SKIP_SOURCE + "\ntype empty",
            output="result",
            stream=output,
        )
        self.assertEqual(str(checked), "0")
        self.assertIn("Type 源码 : type empty", output.getvalue())
        self.assertNotIn("EmptyType()", output.getvalue())

    # 测试输入：skip 的完整 source 与不匹配的用户 Type bottom。
    # 预期行为：TypeChecker 报告 false，而不是将 bottom 当错误占位符接受。
    # 检查内容：验证用户 Type 与规则结论的结构比对。
    # 论文对应：T-End 只允许 0，不允许 \bot。
    def test_type_checker_rejects_non_matching_user_type(self) -> None:
        """不匹配的用户 Type 必须被拒绝。"""

        with self.assertRaises(HCSPTypeCheckingError) as caught:
            check_hcsp_type(_SKIP_SOURCE + "\ntype bottom")
        self.assertEqual(caught.exception.verdict, "false")
        self.assertIs(
            caught.exception.kind,
            TypeCheckingErrorKind.TYPE_MISMATCH,
        )
        self.assertEqual(caught.exception.phase, "type-matching")
        self.assertEqual(caught.exception.rule, "T-End")
        self.assertTrue(caught.exception.type_mismatch_detected)
        self.assertIs(caught.exception.type_structure_matched, False)
        self.assertTrue(caught.exception.details)
        self.assertIsInstance(caught.exception.details[0], HCSPErrorDetail)
        self.assertIn(
            "给定 Type 源码 : type bottom",
            caught.exception.format_result(),
        )
        self.assertIn(
            "给定 Type 源码 : type bottom",
            caught.exception.format_full(),
        )
        self.assertNotIn("BottomType()", caught.exception.format_full())

    # 测试输入：TypeConstructor 可成功构造的通信 source；随后将其 Type AST 写回用户 Type 语法。
    # 预期行为：把该 type 段附回原输入后，TypeChecker 可再次验证成功。
    # 检查内容：锁定 Process/环境 -> Type AST -> Type 语法 -> TypeChecker 的端到端往返。
    # 论文对应：同一棵 T-sigma、T-In、T-Out、T-End 推导树既可构造也可检查。
    def test_constructed_type_serialization_is_accepted_by_type_checker(self) -> None:
        """构造出的可信 Type 写回用户语法后必须可被检查器验证。"""

        constructed = construct_hcsp_type(_COMMUNICATION_SOURCE)
        checked = check_hcsp_type(
            _COMMUNICATION_SOURCE + "\n" + format_type_source(constructed)
        )
        self.assertEqual(checked, constructed)

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
        self.assertEqual(
            str(constructed),
            r"delay(infinity) \unrhd (ch?.(delay(infinity) \unrhd (ch!.(0))))",
        )

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
        self.assertIn("Type 源码 : type empty", result_text)
        self.assertNotIn("EmptyType()", result_text)
        emitted_source = next(
            line.partition(":")[2].strip()
            for line in result_text.splitlines()
            if line.startswith("Type 源码 :")
        )
        self.assertEqual(parse_type_source(emitted_source), result_type)
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
        self.assertIs(error.kind, TypeConstructionErrorKind.PROOF_FAILED)
        self.assertEqual(error.phase, "proof")
        self.assertEqual(error.rule, "T-Assert")
        self.assertEqual(error.location, "K1")
        self.assertTrue(error.details)
        self.assertEqual(error.details[0].proof_kind, "fol")
        self.assertTrue(error.details[0].formula)
        self.assertIn("counterexample", error.details[0].backend_detail)
        self.assertEqual(error.partial_types, (None,))
        self.assertTrue(error.reason)
        self.assertFalse(hasattr(error, "program"))
        self.assertFalse(hasattr(error, "process_ast"))
        self.assertIn("Verdict : false", error.format_result())
        self.assertIn("Type 源码 : (none)", error.format_result())
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
            "hcsp_typechecker.backend.common.keymaerax."
            "KeYmaeraXBackend.__call__",
            return_value=None,
        ):
            with self.assertRaises(HCSPUntrustedTypeConstructionError) as captured:
                construct_hcsp_type(
                "gamma()\ntheta()\nprocess {{ode(flow(), domain(t < 1), "
                "delay(1)); skip}}",
                    source_name="unknown-ode.hcsp",
                    output="full",
                    stream=output,
                )

        error = captured.exception
        self.assertIsInstance(error, HCSPTypeConstructionError)
        self.assertEqual(error.verdict, "unknown")
        self.assertIs(error.kind, TypeConstructionErrorKind.PROOF_UNKNOWN)
        self.assertEqual(error.phase, "proof")
        self.assertIsInstance(error.untrusted_type, TypeAST)
        self.assertEqual(str(error.untrusted_type), "delay(1).(0)")
        self.assertEqual(error.partial_types, (error.untrusted_type,))
        self.assertFalse(hasattr(error, "program"))
        self.assertIn("Verdict : unknown", str(error))
        self.assertIn("完整候选 Type", error.format_result())
        self.assertIn(
            "完整候选 Type 源码 : type delay(1) then empty",
            error.format_result(),
        )
        self.assertIn("不可信（未验证）", error.format_result())
        self.assertIn("类型构造与证明详细报告", error.format_full())
        self.assertIn("dL", error.format_full())
        self.assertIn("规则推导 : 已完成", error.format_full())
        self.assertIn(
            "构造 Type 源码 : type delay(1) then empty",
            error.format_full(),
        )
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
        self.assertEqual(captured.exception.kind, "input-syntax")
        self.assertIn("路径条件解析失败", error_output.getvalue())
        self.assertIn("path-demo.hcsp:path_condition", error_output.getvalue())

    # 测试输入：TypeChecker 输入末尾只有 type 关键字，缺少具体 Type。
    # 预期行为：result/full 都抛同一 HCSPInputError；full 使用 TypeChecker 自己的
    #           标题并显示原始输入、精确位置和插入符，绝不误称“类型构造”。
    # 检查内容：锁定两套业务各自的输入错误渲染，同时复用同一结构化前端异常。
    # 论文对应：尚未形成右侧 Type 时，Table 2 检查判断不能启动。
    def test_type_checker_input_error_uses_checker_specific_output(self) -> None:
        """Checker 的输入错误不得再复用 Constructor 的错误标题。"""

        source = _SKIP_SOURCE + "\ntype"
        result_output = StringIO()
        full_output = StringIO()
        with self.assertRaises(HCSPInputError):
            check_hcsp_type(
                source,
                source_name="bad-type.hcsp",
                output="result",
                stream=result_output,
            )
        with self.assertRaises(HCSPInputError):
            check_hcsp_type(
                source,
                source_name="bad-type.hcsp",
                output="full",
                stream=full_output,
            )

        self.assertIn("HCSP 类型检查输入错误", result_output.getvalue())
        self.assertIn("错误类别 : input-syntax", result_output.getvalue())
        self.assertNotIn("类型构造", result_output.getvalue())
        self.assertIn("HCSP 类型检查完整错误日志", full_output.getvalue())
        self.assertIn(source, full_output.getvalue())
        self.assertIn("syntax error", full_output.getvalue())
        self.assertIn("^", full_output.getvalue())
        self.assertNotIn("类型构造", full_output.getvalue())

    # 测试输入：Checker 分别遇到非法 Theta、assert(false) 和证明后端 unknown。
    # 预期行为：三个失败都保持 HCSPTypeCheckingError 兼容基类，但 kind 分别为
    #           environment、proof-failed、proof-unknown，并携带规则和证明证据。
    # 检查内容：验证调用者无需解析中文日志即可程序化区分失败种类。
    # 论文对应：良构环境、被否证前提和未决前提是三种不同的判断失败来源。
    def test_type_checker_errors_have_machine_readable_categories(self) -> None:
        """Checker 应结构化区分环境、证明失败和证明未决。"""

        invalid_environment = (
            "gamma() theta(bad: channel(v: Real) where(v + 1)) "
            "process {{skip}} type empty"
        )
        with self.assertRaises(HCSPTypeCheckingError) as environment_error:
            check_hcsp_type(invalid_environment)
        self.assertIs(
            environment_error.exception.kind,
            TypeCheckingErrorKind.ENVIRONMENT,
        )
        self.assertEqual(environment_error.exception.phase, "environment")
        self.assertEqual(environment_error.exception.rule, "environment")
        self.assertFalse(environment_error.exception.type_mismatch_detected)

        with self.assertRaises(HCSPTypeCheckingError) as proof_error:
            check_hcsp_type(
                "gamma() theta() process {{assert(false)}} type empty"
            )
        self.assertIs(
            proof_error.exception.kind,
            TypeCheckingErrorKind.PROOF_FAILED,
        )
        self.assertEqual(proof_error.exception.rule, "T-Assert")
        self.assertIn("counterexample", proof_error.exception.reason)
        self.assertTrue(proof_error.exception.details[0].formula)

        unknown_source = (
            "gamma() theta() process {{ode(flow(), domain(t < 1), "
            "delay(1)); skip}} type delay(1) then empty"
        )
        with patch(
            "hcsp_typechecker.backend.common.keymaerax."
            "KeYmaeraXBackend.__call__",
            return_value=None,
        ):
            with self.assertRaises(HCSPTypeCheckingError) as unknown_error:
                check_hcsp_type(unknown_source)
        self.assertIs(
            unknown_error.exception.kind,
            TypeCheckingErrorKind.PROOF_UNKNOWN,
        )
        self.assertEqual(unknown_error.exception.verdict, "unknown")
        self.assertEqual(unknown_error.exception.phase, "proof")
        self.assertIs(unknown_error.exception.type_structure_matched, True)
        self.assertIn("no decision", unknown_error.exception.reason)

    # 测试输入：Constructor 分别遇到非法未使用通道 refinement 与 Bool 变量的
    #           数值赋值；两者都明确失败，但前者属于环境，后者属于规则推导。
    # 预期行为：异常 kind/phase/rule 精确区分 environment 和 derivation。
    # 检查内容：验证 Constructor 的非证明类错误也有稳定的机器可读类别和明细。
    # 论文对应：判断环境良构性先于 Table 2；T-Assign 的静态类型错误发生在规则内。
    def test_constructor_separates_environment_and_derivation_errors(self) -> None:
        """Constructor 不应把所有非证明错误压成一个通用失败。"""

        invalid_environment = (
            "gamma() theta(bad: channel(v: Real) where(v + 1)) "
            "process {{skip}}"
        )
        with self.assertRaises(HCSPTypeConstructionError) as environment_error:
            construct_hcsp_type(invalid_environment)
        self.assertIs(
            environment_error.exception.kind,
            TypeConstructionErrorKind.ENVIRONMENT,
        )
        self.assertEqual(environment_error.exception.phase, "environment")
        self.assertEqual(environment_error.exception.rule, "environment")

        invalid_assignment = "gamma(x: Bool) theta() process {{x := 1}}"
        with self.assertRaises(HCSPTypeConstructionError) as derivation_error:
            construct_hcsp_type(invalid_assignment)
        self.assertIs(
            derivation_error.exception.kind,
            TypeConstructionErrorKind.DERIVATION,
        )
        self.assertEqual(derivation_error.exception.phase, "rule-derivation")
        self.assertEqual(derivation_error.exception.rule, "T-Assign")
        self.assertTrue(derivation_error.exception.details)

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
