r"""验证项目根包公开的两阶段 HCSP 用户接口。

测试内容
--------
1. 根包 ``__all__`` 只暴露解析、推导、聚合结果、输出模式和公共异常；
2. 单进程与并行 source 均可依次转换为 ``HCSPProgram`` 和正式 ``TypeAST``；
3. ``HCSPProgram`` 永久绑定 Process AST、Gamma、Theta 和参数，且环境不可修改；
4. ``none``、``result``、``full`` 只改变打印详细程度，不改变返回结果；
5. 解析失败以及推导得到 ``false``/``unknown`` 时保留稳定异常和审计文本；
6. 并行初态数量、初态元素类型和字符串路径条件由第二阶段入口统一规范化。

论文对应
--------
本文件测试的是论文模型外层的工程封装，而不重新测试各条 Table 2 规则。
第一阶段把同一份用户 source 的参数背景 H、Gamma、Theta 与 Process AST 绑定；
第二阶段只在完整判断为 ``true`` 时返回论文意义下的配置类型 ``mathcal T``。
``false`` 与实现扩展的 ``unknown`` 都不能伪装成正式 Type AST。
"""

from __future__ import annotations

from dataclasses import FrozenInstanceError
from io import StringIO
import unittest
from unittest.mock import patch

import hcsp_typechecker
from hcsp_typechecker import (
    HCSPInputError,
    HCSPProgram,
    HCSPTypeError,
    OutputMode,
    TypeAST,
    infer_hcsp_type,
    parse_hcsp_program,
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
    """锁定普通调用者可见的名称、对象、输出和失败协议。"""

    # 测试输入：直接查看根包的导出白名单以及若干旧内部实现名称。
    # 预期行为：根包只导出七个稳定门面名称，不重新暴露 AST 构造器或检查器。
    # 检查内容：精确比较 __all__，并确认 TypeChecker/BasicType 不在根命名空间。
    # 论文对应：这是工程封装边界；论文 AST 与推导细节通过两阶段入口间接使用。
    def test_root_package_exports_only_the_stable_facade(self) -> None:
        """根包导入协议应形成明确白名单，而不是整个实现对象图。"""

        expected = {
            "HCSPInputError",
            "HCSPProgram",
            "HCSPTypeError",
            "OutputMode",
            "TypeAST",
            "infer_hcsp_type",
            "parse_hcsp_program",
        }

        self.assertEqual(set(hcsp_typechecker.__all__), expected)
        self.assertEqual(len(hcsp_typechecker.__all__), len(expected))
        for name in expected:
            with self.subTest(public_name=name):
                self.assertTrue(hasattr(hcsp_typechecker, name))
        self.assertFalse(hasattr(hcsp_typechecker, "TypeChecker"))
        self.assertFalse(hasattr(hcsp_typechecker, "BasicType"))

    # 测试输入：含参数、Gamma、Theta 和 ch?(x);ch!(x) 的完整单进程 source。
    # 预期行为：第一阶段返回聚合程序，第二阶段返回 ch?.(ch!.(0)) 正式类型。
    # 检查内容：对象类别、四部分绑定、单分量视图以及 TypeAST 抽象类别。
    # 论文对应：第二阶段依次使用 T-sigma、T-In、T-Out 与 T-End 形成过程类型。
    def test_single_process_succeeds_through_both_public_stages(self) -> None:
        """普通用户无需接触内部构造器即可完成单进程类型推导。"""

        program = parse_hcsp_program(
            _COMMUNICATION_SOURCE,
            source_name="communication.hcsp",
        )
        inferred = infer_hcsp_type(program)

        self.assertIsInstance(program, HCSPProgram)
        self.assertEqual(program.source_name, "communication.hcsp")
        self.assertEqual(tuple(program.gamma), ("x",))
        self.assertEqual(tuple(program.theta), ("ch",))
        self.assertEqual(tuple(program.parameters.declarations), ("limit",))
        self.assertEqual(len(program.process_components), 1)
        self.assertIsInstance(inferred, TypeAST)
        self.assertEqual(str(inferred), "ch?.(ch!.(0))")

    # 测试输入：两个独立 skip 块构成的顶层并行完整 source。
    # 预期行为：第一阶段保留一个正式 Parallel AST，并提供两个有序 Process 叶子。
    # 检查内容：分量数以及第二阶段返回的并行配置类型 (0) | (0)。
    # 论文对应：系统层的并行判断将两个 T-End 结果组合为配置类型 mathcal T。
    def test_parallel_process_succeeds_through_both_public_stages(self) -> None:
        """并行 source 应由聚合对象自动拆成一一对应的内部配置。"""

        program = parse_hcsp_program(_PARALLEL_SOURCE)
        inferred = infer_hcsp_type(program, initial_states=({}, {}))

        self.assertEqual(len(program.process_components), 2)
        self.assertEqual(type(program.process_ast).__name__, "Parallel")
        self.assertIsInstance(inferred, TypeAST)
        self.assertEqual(str(inferred), "(0) | (0)")

    # 测试输入：解析含 Gamma、Theta 和共享参数的完整通信 source 后尝试原地修改。
    # 预期行为：HCSPProgram 字段冻结，三个环境映射及参数声明都拒绝修改。
    # 检查内容：字段赋值抛 FrozenInstanceError，映射写入/清空抛 TypeError/AttributeError。
    # 论文对应：一次判断所用 H、Gamma、Theta 与 Process 必须保持同源且不可误配。
    def test_program_keeps_all_lowered_models_in_read_only_bindings(self) -> None:
        """第一阶段结果应是稳定快照，而不是四个可被调用者拆改的容器。"""

        program = parse_hcsp_program(_COMMUNICATION_SOURCE)

        with self.assertRaises(FrozenInstanceError):
            program.source_name = "changed.hcsp"  # type: ignore[misc]
        with self.assertRaises(TypeError):
            program.gamma["x"] = object()  # type: ignore[index]
        with self.assertRaises(AttributeError):
            program.theta.clear()  # type: ignore[attr-defined]
        with self.assertRaises(TypeError):
            program.parameters.declarations["limit"] = object()  # type: ignore[index]

        self.assertEqual(program.source_text, _COMMUNICATION_SOURCE)
        self.assertEqual(len(program.process_components), 1)

    # 测试输入：同一份 skip source 分别采用 none、result、full 三种解析输出模式。
    # 预期行为：三次都返回等价 HCSPProgram，仅文本从空、摘要递增到含原文的完整日志。
    # 检查内容：静默流为空；摘要无原始输入区；单进程完整日志含来源和原文，
    #           但不把根 AST 再伪装成一个内容完全相同的 K1 分量重复打印。
    # 论文对应：输出层不参与 source 到 Process AST/Gamma/Theta/H 的数学转换。
    def test_parse_output_modes_only_change_rendering_detail(self) -> None:
        """第一阶段的输出模式不应改变解析得到的程序模型。"""

        silent = StringIO()
        result_stream = StringIO()
        full_stream = StringIO()

        silent_program = parse_hcsp_program(
            _SKIP_SOURCE,
            output=OutputMode.NONE,
            stream=silent,
        )
        result_program = parse_hcsp_program(
            _SKIP_SOURCE,
            output=" RESULT ",
            stream=result_stream,
        )
        full_program = parse_hcsp_program(
            _SKIP_SOURCE,
            source_name="skip.hcsp",
            output=OutputMode.FULL,
            stream=full_stream,
        )

        self.assertEqual(silent.getvalue(), "")
        self.assertIn("=== HCSP 用户输入转换结果 ===", result_stream.getvalue())
        self.assertNotIn("--- 原始用户输入 ---", result_stream.getvalue())
        self.assertIn("=== HCSP 用户输入转换完整日志 ===", full_stream.getvalue())
        self.assertIn("来源 : skip.hcsp", full_stream.getvalue())
        self.assertIn(_SKIP_SOURCE, full_stream.getvalue())
        self.assertNotIn("--- 顶层并行分量 ---", full_stream.getvalue())
        self.assertEqual(full_stream.getvalue().count("Process AST:"), 1)
        self.assertEqual(silent_program.process_ast, result_program.process_ast)
        self.assertEqual(result_program.process_ast, full_program.process_ast)

        parallel_stream = StringIO()
        parse_hcsp_program(
            _PARALLEL_SOURCE,
            output="full",
            stream=parallel_stream,
        )
        self.assertIn("--- 顶层并行分量 ---", parallel_stream.getvalue())
        self.assertIn("K1 AST", parallel_stream.getvalue())
        self.assertIn("K2 AST", parallel_stream.getvalue())

    # 测试输入：同一个已解析 skip 程序分别采用 none、result、full 推导输出模式。
    # 预期行为：三次均返回同一正式 Type AST；摘要只给结论，完整日志给出规则与公式。
    # 检查内容：比较类型相等性和三档文本中的结果标题、规则区及输入环境摘要。
    # 论文对应：日志只是 Table 2 推导树和横线上方前提的可视化，不改变推导结论。
    def test_inference_output_modes_only_change_rendering_detail(self) -> None:
        """第二阶段的静默、结果和完整日志必须共享完全相同的判断过程。"""

        program = parse_hcsp_program(_SKIP_SOURCE)
        silent = StringIO()
        result_stream = StringIO()
        full_stream = StringIO()

        silent_type = infer_hcsp_type(
            program,
            output="none",
            stream=silent,
        )
        result_type = infer_hcsp_type(
            program,
            output=OutputMode.RESULT,
            stream=result_stream,
        )
        full_type = infer_hcsp_type(
            program,
            output="full",
            stream=full_stream,
        )

        self.assertEqual(silent.getvalue(), "")
        self.assertIn("=== HCSP 到 Type AST 转换结果 ===", result_stream.getvalue())
        self.assertIn("Verdict : true", result_stream.getvalue())
        self.assertNotIn("=== 规则执行过程 ===", result_stream.getvalue())
        self.assertIn("=== HCSP 用户输入转换结果 ===", full_stream.getvalue())
        self.assertIn("=== 类型检查详细报告 ===", full_stream.getvalue())
        self.assertIn("=== 规则执行过程 ===", full_stream.getvalue())
        self.assertEqual(silent_type, result_type)
        self.assertEqual(result_type, full_type)

    # 测试输入：缺少 process 右花括号的非法 source，并分别请求 result/full 日志。
    # 预期行为：两种模式都继续抛 HCSPInputError，同时先写出对应详细度的定位信息。
    # 检查内容：摘要含来源与行列；完整日志还含原始行、syntax error 和插入符。
    # 论文对应：该错误发生在 concrete syntax 边界，尚未形成可用于论文规则的 Process。
    def test_parse_failure_prints_requested_diagnostic_before_raising(self) -> None:
        """解析失败既不能被吞掉，也不能因抛异常而丢失用户请求的日志。"""

        broken = "gamma()\ntheta()\nprocess {{skip"
        result_stream = StringIO()
        full_stream = StringIO()

        with self.assertRaises(HCSPInputError):
            parse_hcsp_program(
                broken,
                source_name="broken.hcsp",
                output="result",
                stream=result_stream,
            )
        with self.assertRaises(HCSPInputError):
            parse_hcsp_program(
                broken,
                source_name="broken.hcsp",
                output="full",
                stream=full_stream,
            )

        self.assertIn("状态 : 失败", result_stream.getvalue())
        self.assertIn("broken.hcsp:3:15", result_stream.getvalue())
        self.assertNotIn("process {{skip", result_stream.getvalue())
        self.assertIn("=== HCSP 用户输入转换完整日志 ===", full_stream.getvalue())
        self.assertIn("process {{skip", full_stream.getvalue())
        self.assertIn("syntax error", full_stream.getvalue())
        self.assertIn("^", full_stream.getvalue())

    # 测试输入：路径条件为 true、程序断言为 false 的可解析 source。
    # 预期行为：第二阶段得到 false 后抛 HCSPTypeError，不返回候选或 BottomType。
    # 检查内容：异常关联原程序、verdict/reason/部分类型，并与已打印摘要一致。
    # 论文对应：T-Assert 的前提不能成立时，完整判断不存在正式 Type AST。
    def test_false_inference_raises_public_error_with_partial_report(self) -> None:
        """已否证前提必须通过公共异常返回，而不能伪造成类型生成成功。"""

        program = parse_hcsp_program(
            "gamma()\ntheta()\nprocess {{assert(false)}}"
        )
        output = StringIO()

        with self.assertRaises(HCSPTypeError) as captured:
            infer_hcsp_type(program, output="result", stream=output)

        error = captured.exception
        self.assertIs(error.program, program)
        self.assertEqual(error.verdict, "false")
        self.assertEqual(error.partial_types, (None,))
        self.assertTrue(error.reason)
        self.assertIn("Verdict : false", error.format_result())
        self.assertIn("Type AST : None", error.format_result())
        self.assertEqual(output.getvalue().strip(), error.format_result())

    # 测试输入：wait(1) 产生 dL 义务，测试替身让证明后端明确不作出判断。
    # 预期行为：第二阶段保守返回 unknown 并抛 HCSPTypeError，不泄漏未证候选类型。
    # 检查内容：verdict、空部分类型、简洁错误文本，以及接口打印内容与异常中
    #           保存的同一份完整 dL 审计日志严格相等且只出现一次。
    # 论文对应：unknown 是实现的保守扩展；论文前提未被证明时不能应用 ODE 类型规则。
    def test_unknown_inference_raises_public_error_without_candidate_type(self) -> None:
        """外部证明没有结论时，门面必须阻止未经证明的 Type AST 越界返回。"""

        program = parse_hcsp_program(
            "gamma()\ntheta()\nprocess {{wait(1)}}"
        )

        output = StringIO()
        with patch(
            "hcsp_typechecker.typechecking.checker."
            "KeYmaeraXBackend.__call__",
            return_value=None,
        ):
            with self.assertRaises(HCSPTypeError) as captured:
                infer_hcsp_type(program, output="full", stream=output)

        error = captured.exception
        self.assertEqual(error.verdict, "unknown")
        self.assertEqual(error.partial_types, (None,))
        self.assertIn("Verdict : unknown", str(error))
        self.assertIn("=== 类型检查详细报告 ===", error.format_full())
        self.assertIn("dL", error.format_full())
        self.assertEqual(output.getvalue().rstrip("\n"), error.format_full())
        self.assertEqual(output.getvalue().count("=== 类型检查详细报告 ==="), 1)

    # 测试输入：两分量并行程序分别给单 mapping、一个 mapping 的序列和含非 mapping 的序列。
    # 预期行为：入口在进入类型检查前拒绝歧义数量、错误数量和错误元素类型。
    # 检查内容：三种错误分别稳定抛 ValueError、ValueError 与 TypeError。
    # 论文对应：T-parallel 要求每个顶层 Process 分量恰有一个对应初始状态 sigma。
    def test_parallel_initial_state_count_and_element_types_are_validated(self) -> None:
        """并行初态必须按源码分量顺序一一给出，不允许隐式复制或丢弃。"""

        program = parse_hcsp_program(_PARALLEL_SOURCE)

        with self.assertRaisesRegex(ValueError, "one initial-state mapping"):
            infer_hcsp_type(program, initial_states={})
        with self.assertRaisesRegex(ValueError, r"components \(2\)"):
            infer_hcsp_type(program, initial_states=({},))
        with self.assertRaisesRegex(TypeError, "every initial state"):
            infer_hcsp_type(program, initial_states=({}, 0))  # type: ignore[arg-type]

    # 测试输入：Gamma 声明 x:Int，初态 x=1，字符串路径条件写为 x >= 0。
    # 预期行为：入口用统一 Expr 语法解析字符串，并由 T-sigma 证明代入后的条件成立。
    # 检查内容：返回正式终止类型；非法字符串以 path_condition 来源抛异常并写 full 日志。
    # 论文对应：字符串最终表示判断左侧的 phi，T-sigma 检查 models phi[sigma]。
    def test_string_path_condition_uses_the_strict_expression_frontend(self) -> None:
        """调用者可传字符串路径条件，同时仍获得统一词法和定位诊断。"""

        program = parse_hcsp_program(
            "gamma(x: Int)\ntheta()\nprocess {{skip}}",
            source_name="path-demo.hcsp",
        )

        inferred = infer_hcsp_type(
            program,
            initial_states={"x": 1},
            path_condition="x >= 0",
        )

        self.assertIsInstance(inferred, TypeAST)
        self.assertEqual(str(inferred), "0")
        error_output = StringIO()
        with self.assertRaises(HCSPInputError) as captured:
            infer_hcsp_type(
                program,
                path_condition="x >=",
                output="full",
                stream=error_output,
            )
        self.assertEqual(
            captured.exception.source_name,
            "path-demo.hcsp:path_condition",
        )
        self.assertIn("=== 路径条件解析失败 ===", error_output.getvalue())
        self.assertIn("path-demo.hcsp:path_condition", error_output.getvalue())


if __name__ == "__main__":
    unittest.main()
