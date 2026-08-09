"""完整用户 source 中共享只读参数段的解析和 lowering 测试。

测试内容
--------
1. 可选 ``parameters(...) where(...)`` 段及五种规范 BasicType 的精确转换；
2. 省略/恒真约束、约束 Expr、只读声明快照和固定顶层顺序；
3. 重复参数、Gamma 冲突、非法类型、非法 IDENT 与尾逗号的诊断；
4. 已声明参数在并行分量间的合法共享，以及未声明状态变量仍受
   Assumption 2.1 分离要求约束。

论文对应
--------
参数环境是项目为共享预赋值增加的只读背景 ``H``，不属于状态 Gamma，也不
改变 Section 2.1 的 Process AST。本文件只验证 concrete syntax 到现有
``ParameterEnvironment``/Process AST 的转换；约束的 Bool 类型、可满足性及
程序对参数的写入由完整类型判断负责。
"""

from __future__ import annotations

import unittest

from hcsp_typechecker._internal import (
    BasicType,
    HCSPInputError,
    Parallel,
    ParsedHCSPSource,
    Skip,
    parse_expression,
    parse_hcsp_source,
)


class ParameterSourceConversionTests(unittest.TestCase):
    """验证可选参数段产生独立、稳定的共享参数环境。"""

    # 测试输入：分别省略 parameters 段，以及显式写出空 parameters() 段。
    # 预期行为：两种形式都得到空声明和恒真约束，旧版三段 source 保持兼容。
    # 检查内容：核对 ParameterEnvironment 的声明映射、约束和 Process AST。
    # 论文对应：没有共享预赋值时背景 H 为 true，不增加任何类型判断前提。
    def test_parameter_section_is_optional_and_empty_form_is_equivalent(self) -> None:
        """新增参数段不能破坏不含参数的既有完整 source。"""

        legacy = parse_hcsp_source(
            "gamma() theta() process {{skip}}"
        )
        explicit = parse_hcsp_source(
            "gamma() parameters() theta() process {{skip}}"
        )

        for parsed in (legacy, explicit):
            with self.subTest(source_form=parsed):
                self.assertEqual(parsed.parameters.declarations, {})
                self.assertIs(parsed.parameters.constraint, True)
                self.assertEqual(parsed.process, Skip())

    # 测试输入：五种规范 BasicType 参数和同时引用它们的联合 where 约束。
    # 预期行为：声明逐项转换为 BasicType，非平凡约束保存为项目 Expr。
    # 检查内容：精确比较声明映射、约束 AST，并确认参数没有混入 Gamma。
    # 论文对应：共享参数具有基础值类型，H 对所有合法预赋值给出联合限制。
    def test_all_parameter_basic_types_and_constraint_are_lowered_exactly(self) -> None:
        """参数声明应复用现有 BasicType 和 Expr，而不建立第二套模型。"""

        parsed = parse_hcsp_source(
            """gamma(state: Real)
parameters(
    enabled: Bool,
    count: Nat,
    offset: Int,
    ratio: Rational,
    limit: Real
) where(enabled and count <= offset and ratio <= limit)
theta()
process {{skip}}"""
        )

        self.assertEqual(
            parsed.parameters.declarations,
            {
                "enabled": BasicType.BOOL,
                "count": BasicType.NAT,
                "offset": BasicType.INT,
                "ratio": BasicType.RATIONAL,
                "limit": BasicType.REAL,
            },
        )
        self.assertEqual(
            parsed.parameters.constraint,
            parse_expression(
                "enabled and count <= offset and ratio <= limit"
            ),
        )
        self.assertEqual(parsed.gamma, {"state": BasicType.REAL})
        self.assertNotIn("limit", parsed.gamma)

    # 测试输入：显式 where(true)，以及解析后公开的 parameters.declarations。
    # 预期行为：恒真公式归一为 Python True，声明映射不能被调用方原地修改。
    # 检查内容：核对唯一恒真表示，并尝试覆盖和清空只读声明快照。
    # 论文对应：固定一次判断所使用的参数预赋值域，避免检查前改变背景 H。
    def test_true_constraint_and_declarations_use_read_only_normal_form(self) -> None:
        """解析后的参数环境应与只读语义一致地暴露稳定快照。"""

        parsed = parse_hcsp_source(
            """gamma()
parameters(limit: Real) where(true)
theta()
process {{skip}}"""
        )

        self.assertIs(parsed.parameters.constraint, True)
        with self.assertRaises(TypeError):
            parsed.parameters.declarations["limit"] = BasicType.INT  # type: ignore[index]
        with self.assertRaises(AttributeError):
            parsed.parameters.declarations.clear()  # type: ignore[attr-defined]

    # 测试输入：约束只使用已声明参数 limit，但结果 limit+1 是数值而不是 Bool。
    # 预期行为：前端保存名称范围合法的 Expr，不提前执行完整表达式类型判断。
    # 检查内容：精确比较 constraint 与独立表达式入口生成的 AST。
    # 论文对应：H 只能引用自身声明；公式的 Bool 类型仍由 typing environment 检查。
    def test_constraint_semantics_are_preserved_for_the_type_checker(self) -> None:
        """语法转换不应丢失随后由 checker 拒绝的约束表达式。"""

        parsed = parse_hcsp_source(
            """gamma()
parameters(limit: Real) where(limit + 1)
theta()
process {{skip}}"""
        )

        self.assertEqual(
            parsed.parameters.constraint,
            parse_expression("limit + 1"),
        )

    # 测试输入：两个并行分量读取同一个已声明 limit，但使用不同输出通道。
    # 预期行为：完整 source 成功形成 Parallel，顶层叶子视图保持源码顺序。
    # 检查内容：核对 Parallel 根、两个 Process 分量及共享参数仍在独立环境中。
    # 论文对应：只读参数不属于任一分量的状态 V，可作为并行判断的共同背景。
    def test_declared_parameter_can_be_read_by_parallel_components(self) -> None:
        """参数上下文应只放宽并行分量对同一只读自由名的读取。"""

        parsed = parse_hcsp_source(
            """gamma()
parameters(limit: Real) where(limit >= 0)
theta(
    left: channel(value: Real),
    right: channel(value: Real)
)
process {
    {assert(limit >= 0); left!(limit)},
    {assert(limit >= 0); right!(limit)}
}"""
        )

        self.assertIsInstance(parsed.process, Parallel)
        self.assertEqual(len(parsed.process_components), 2)
        self.assertEqual(
            parsed.parameters.declarations,
            {"limit": BasicType.REAL},
        )
        self.assertTrue(
            all("limit" in component.get_vars()
                for component in parsed.process_components)
        )

    # 测试输入：两个并行分量共享普通 Gamma 状态 shared；另有合法参数 limit。
    # 预期行为：limit 可共享不应掩盖 shared 的 Assumption 2.1 冲突。
    # 检查内容：确认在 Process 构造期得到 validation 错误并明确指出 shared。
    # 论文对应：并行状态空间仍必须分离；参数例外只适用于已声明只读自由名。
    def test_parameter_exemption_does_not_hide_shared_state_variables(self) -> None:
        """共享参数集合不能被用来放宽真正的并行状态冲突。"""

        source = """gamma(shared: Real)
parameters(limit: Real)
theta(
    left: channel(value: Real),
    right: channel(value: Real)
)
process {
    {left!(shared + limit)},
    {right!(shared + limit)}
}"""

        with self.assertRaises(HCSPInputError) as context:
            parse_hcsp_source(source)

        self.assertEqual(context.exception.phase, "validation")
        self.assertIn("share variables: shared", str(context.exception))


class ParameterSourceValidationTests(unittest.TestCase):
    """验证参数段的有限映射、类型、词法和顶层位置约束。"""

    # 测试输入：参数段内重复 x，以及 Gamma 和参数段分别声明同一个 x。
    # 预期行为：两种歧义都在第二个 x 处产生 validation 错误，字典不静默覆盖。
    # 检查内容：逐例核对 phase、found 和错误消息中的环境关系。
    # 论文对应：状态 Gamma 与只读参数环境必须是定义域不交的有限映射。
    def test_duplicate_and_gamma_overlapping_parameters_are_rejected(self) -> None:
        """同一名称不能重复声明或同时具有可变状态与只读参数身份。"""

        cases = (
            (
                "gamma() parameters(x: Real, x: Int) "
                "theta() process {{skip}}",
                "duplicate parameter declaration",
            ),
            (
                "gamma(x: Real) parameters(x: Real) "
                "theta() process {{skip}}",
                "overlap",
            ),
        )
        for source, expected_message in cases:
            with self.subTest(expected_message=expected_message):
                with self.assertRaises(HCSPInputError) as context:
                    parse_hcsp_source(source)
                self.assertEqual(context.exception.phase, "validation")
                self.assertEqual(context.exception.found, "x")
                self.assertIn(expected_message, str(context.exception))

    # 测试输入：参数约束引用声明列表中不存在的 missing。
    # 预期行为：在 where token 处产生 validation 错误，不把未定型名称交给 checker。
    # 检查内容：核对错误阶段、全局行列及明确列出的未声明名称。
    # 论文对应：参数背景 H 的自由变量定义域必须包含于共享参数声明域。
    def test_parameter_constraint_may_only_reference_declared_parameters(self) -> None:
        """参数约束不能读取 Gamma、通道 binder 或未声明的普通自由名。"""

        source = """gamma(state: Real)
parameters(limit: Real) where(limit >= state and missing >= 0)
theta()
process {{skip}}"""

        with self.assertRaises(HCSPInputError) as context:
            parse_hcsp_source(source, source_name="parameters.hcsp")

        error = context.exception
        self.assertEqual(error.phase, "validation")
        self.assertEqual(error.source_name, "parameters.hcsp")
        self.assertEqual(error.found, "where")
        self.assertEqual((error.line, error.column), (2, 25))
        self.assertIn("missing, state", str(error))

    # 测试输入：小写类型、continuous 类型、参数尾逗号和 Unicode 参数名。
    # 预期行为：前三类为 syntax 错误，Unicode 在共享词法器处为 lexical 错误。
    # 检查内容：确认参数只接受规范 BasicType、无尾逗号的 ASCII IDENT 声明。
    # 论文对应：参数值仍取自 B ::= Bool|Nat|Int|Rational|Real，不是连续向量。
    def test_parameter_types_identifiers_and_commas_are_strict(self) -> None:
        """程序化类型别名和额外 concrete syntax 不得泄漏进参数段。"""

        cases = (
            (
                "gamma() parameters(x: real) theta() process {{skip}}",
                "syntax",
            ),
            (
                "gamma() parameters(x: continuous(y)) "
                "theta() process {{skip}}",
                "syntax",
            ),
            (
                "gamma() parameters(x: Real,) theta() process {{skip}}",
                "syntax",
            ),
            (
                "gamma() parameters(参数: Real) theta() process {{skip}}",
                "lexical",
            ),
        )
        for source, expected_phase in cases:
            with self.subTest(expected_phase=expected_phase):
                with self.assertRaises(HCSPInputError) as context:
                    parse_hcsp_source(source)
                self.assertEqual(context.exception.phase, expected_phase)

    # 测试输入：把 parameters 放在 gamma 前、theta 后，或用分号分隔顶层段。
    # 预期行为：完整入口只接受 gamma 后、theta 前的单个可选参数段。
    # 检查内容：逐例确认错误均来自固定顶层文法，而非被解释为 Process 语句。
    # 论文对应：这是用户输入包装格式，不改变底层 HCSP 的任一产生式。
    def test_parameter_section_has_one_fixed_optional_position(self) -> None:
        """参数段不能移动、重复或用 Process 的分号与环境段连接。"""

        invalid_sources = (
            "parameters() gamma() theta() process {{skip}}",
            "gamma() theta() parameters() process {{skip}}",
            "gamma(); parameters() theta() process {{skip}}",
            "gamma() parameters() parameters() theta() process {{skip}}",
        )
        for source in invalid_sources:
            with self.subTest(source=source):
                with self.assertRaises(HCSPInputError) as context:
                    parse_hcsp_source(source)
                self.assertEqual(context.exception.phase, "syntax")

    # 测试输入：把保留字 parameters 用作参数名及 Process 赋值目标。
    # 预期行为：两处都在 syntax 阶段拒绝，关键字不会退化为普通 IDENT。
    # 检查内容：覆盖新增关键字在环境和 Process 共用词法表中的一致边界。
    # 论文对应：名称拼写不改变数学含义，但 concrete syntax 必须无歧义。
    def test_parameters_keyword_is_reserved_everywhere(self) -> None:
        """新增顶层关键字在所有片段入口中都必须保持保留。"""

        invalid_sources = (
            "gamma() parameters(parameters: Real) "
            "theta() process {{skip}}",
            "gamma() theta() process {{parameters := 1}}",
        )
        for source in invalid_sources:
            with self.subTest(source=source):
                with self.assertRaises(HCSPInputError) as context:
                    parse_hcsp_source(source)
                self.assertEqual(context.exception.phase, "syntax")


if __name__ == "__main__":
    unittest.main()
