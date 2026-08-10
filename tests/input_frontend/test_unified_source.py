"""Gamma、Theta 与 Process 统一用户输入的解析和 lowering 测试。

测试内容
--------
1. 五种 BasicType、连续演化向量和单槽/多槽 ChannelType 的精确转换。
2. 显式 refinement、缺省恒真 refinement、空环境和并行 Process 的转换。
3. Gamma/Theta 重复声明、非法类型、连续向量和通道元数的结构诊断。
4. ASCII 标识符边界、完整 source 固定次序以及全局源码位置的保留。

论文对应
--------
本文件验证用户文本到类型构造器输入对象的边界：Gamma 项转换为 BasicType 或
ContinuousType，Theta 项转换为带 binders/refinement 的 ChannelType，Process
部分仍转换为 Section 2.1 对应的正式 HCSP AST。本文件不执行 Table 2 推导，
也不在前端重复检查 Process 通信实参与 Theta 签名的元数或 refinement 类型。
"""

from __future__ import annotations

import unittest

from hcsp_typechecker._internal import (
    BasicType,
    BooleanExpr,
    ChannelType,
    CompareExpr,
    ContinuousType,
    HCSPInputError,
    InputChannel,
    Literal,
    OutputChannel,
    Parallel,
    ParsedHCSPSource,
    Skip,
    Variable,
    parse_expression,
    parse_hcsp_source,
)


def _source_with(
    *,
    gamma: str = "",
    theta: str = "",
    process: str = "{{skip}}",
) -> str:
    """建立供负例复用的最小完整 source，不参与被测解析逻辑。"""

    return f"gamma({gamma})\ntheta({theta})\nprocess {process}"


class UnifiedSourceConversionTests(unittest.TestCase):
    """验证三个顶层部分到既有环境模型和 Process AST 的精确转换。"""

    # 测试输入：含五种标量类型、向前引用连续向量以及五个不同签名通道的完整 source。
    # 预期行为：一次解析得到 ParsedHCSPSource，且三个字段均使用项目既有正式对象。
    # 检查内容：精确比较 Gamma、连续成员规范序、Theta 槽序、binders 和 refinement AST。
    # 论文对应：覆盖 Gamma 的 B/连续项以及项目多标量扩展后的 Theta refinement type。
    def test_complete_source_lowers_all_environment_forms(self) -> None:
        """完整环境声明应无损转换，而不建立第二套 Gamma/Theta AST。"""

        source = """
            gamma(
                motion: continuous(velocity, position),
                enabled: Bool,
                count: Nat,
                offset: Int,
                ratio: Rational,
                position: Real,
                velocity: Real
            )
            theta(
                sensor: channel(value: Real)
                    where(0 <= value and value <= 100),
                state: channel(index: Nat, accepted: Bool),
                exact: channel(delta: Rational),
                command: channel(mode: Int),
                always: channel(flag: Bool) where(true)
            )
            process {{skip}}
        """

        parsed = parse_hcsp_source(source)

        self.assertIsInstance(parsed, ParsedHCSPSource)
        self.assertEqual(
            parsed.gamma,
            {
                "motion": ContinuousType(("position", "velocity")),
                "enabled": BasicType.BOOL,
                "count": BasicType.NAT,
                "offset": BasicType.INT,
                "ratio": BasicType.RATIONAL,
                "position": BasicType.REAL,
                "velocity": BasicType.REAL,
            },
        )
        self.assertEqual(
            parsed.theta["sensor"],
            ChannelType(
                (BasicType.REAL,),
                refinement=BooleanExpr(
                    "and",
                    (
                        CompareExpr(
                            (Literal(0), Variable("value")),
                            ("<=",),
                        ),
                        CompareExpr(
                            (Variable("value"), Literal(100)),
                            ("<=",),
                        ),
                    ),
                ),
                binders=("value",),
            ),
        )
        self.assertEqual(
            parsed.theta["state"],
            ChannelType(
                (BasicType.NAT, BasicType.BOOL),
                refinement=True,
                binders=("index", "accepted"),
            ),
        )
        self.assertEqual(
            parsed.theta["exact"],
            ChannelType(
                BasicType.RATIONAL,
                refinement=True,
                binders=("delta",),
            ),
        )
        self.assertEqual(
            parsed.theta["command"],
            ChannelType(
                BasicType.INT,
                refinement=True,
                binders=("mode",),
            ),
        )
        self.assertIs(parsed.theta["always"].refinement, True)
        self.assertEqual(parsed.process, Skip())

    # 测试输入：最小的 ``gamma() theta() process {{skip}}`` 完整输入。
    # 预期行为：两个空环境均合法，process 字段直接保存 Skip 而非包装节点。
    # 检查内容：核对空映射、聚合记录类型和单分量 Process 的精确 AST。
    # 论文对应：空环境不增加类型假设，单分量系统仍对应系统产生式 S ::= P。
    def test_empty_environments_are_valid(self) -> None:
        """没有变量和通道声明时，统一入口仍应能解析独立 HCSP 进程。"""

        parsed = parse_hcsp_source(_source_with())

        self.assertEqual(parsed.gamma, {})
        self.assertEqual(parsed.theta, {})
        self.assertEqual(parsed.process, Skip())

    # 测试输入：一个 Int 状态、一个一槽通道及该通道的互补输入/输出并行分量。
    # 预期行为：环境只转换一次，两个进程块按原顺序 lower 为规范 Parallel。
    # 检查内容：比较 Gamma、Theta 和 Parallel 两侧的完整正式节点。
    # 论文对应：覆盖系统层 S ::= S || S'，并保留互补通信可同步的通道方向。
    def test_parallel_process_is_preserved_in_unified_source(self) -> None:
        """统一包装不应改变既有多块 process_system 的并行 lowering。"""

        source = _source_with(
            gamma="received: Int",
            theta="ch: channel(payload: Int)",
            process="{{ch!(0)}, {ch?(received)}}",
        )

        parsed = parse_hcsp_source(source)

        self.assertEqual(parsed.gamma, {"received": BasicType.INT})
        self.assertEqual(
            parsed.theta,
            {
                "ch": ChannelType(
                    BasicType.INT,
                    refinement=True,
                    binders=("payload",),
                )
            },
        )
        self.assertEqual(
            parsed.process,
            Parallel(
                OutputChannel("ch", 0),
                InputChannel("ch", "received"),
            ),
        )

    # 测试输入：解析后的环境映射，以及手工传给 ParsedHCSPSource 的可变原始字典。
    # 预期行为：聚合记录防御性复制两个环境，且调用方不能再原地修改解析快照。
    # 检查内容：覆盖外部字典后改不泄漏、Mapping 赋值失败和 Theta 清空失败。
    # 论文对应：固定一次 source 对应的 Gamma/Theta，避免检查前改变判断上下文。
    def test_parsed_environments_are_read_only_snapshots(self) -> None:
        """ParsedHCSPSource 应绑定稳定环境，而非仅冻结两个可变字典引用。"""

        original_gamma = {"x": BasicType.REAL}
        original_theta = {
            "ch": ChannelType(BasicType.REAL, binders=("value",))
        }
        parsed = ParsedHCSPSource(original_gamma, original_theta, Skip())

        original_gamma["x"] = BasicType.BOOL
        original_theta.clear()
        self.assertEqual(parsed.gamma["x"], BasicType.REAL)
        self.assertIn("ch", parsed.theta)
        with self.assertRaises(TypeError):
            parsed.gamma["x"] = BasicType.INT  # type: ignore[index]
        with self.assertRaises(AttributeError):
            parsed.theta.clear()  # type: ignore[attr-defined]

    # 测试输入：三段之间含两类注释，且 Gamma 键、Theta 通道和局部 binder 同名。
    # 预期行为：注释不切断统一 token 流，不同命名空间中的 shared 均被保留。
    # 检查内容：核对 Gamma、Theta binder/refinement 和 Process 三个正式结果。
    # 论文对应：Gamma 与 Theta 是独立环境，refinement binder 又具有局部作用域。
    def test_comments_and_separate_name_spaces_are_preserved(self) -> None:
        """跨段注释和合法的跨命名空间同名不应导致源码被错误切分。"""

        source = """gamma(shared: Real)
/* Gamma and Theta stay in one token stream. */
theta(
    shared: channel(shared: Real) where(shared >= 0)
)
// The process section follows the same source positions.
process {{skip}}"""

        parsed = parse_hcsp_source(source)

        self.assertEqual(parsed.gamma, {"shared": BasicType.REAL})
        self.assertEqual(parsed.theta["shared"].binders, ("shared",))
        self.assertEqual(
            parsed.theta["shared"].refinement,
            parse_expression("shared >= 0"),
        )
        self.assertEqual(parsed.process, Skip())

    # 测试输入：refinement 含外部自由名，且整体是数值而不是 Bool 公式。
    # 预期行为：统一前端只保存合法 Expr，不抢先重复完整判断上下文的类型工作。
    # 检查内容：精确比较 ChannelType.refinement 与严格表达式入口生成的 AST。
    # 论文对应：Theta 的公式类型和自由名最终由含 Gamma/参数的类型判断检查。
    def test_refinement_semantics_remain_for_the_type_constructor(self) -> None:
        """语法合法的 refinement 应被无损保存，即使其后仍可能类型错误。"""

        source = _source_with(
            theta="bad: channel(value: Real) where(value + missing)"
        )

        parsed = parse_hcsp_source(source)

        self.assertEqual(
            parsed.theta["bad"].refinement,
            parse_expression("value + missing"),
        )


class UnifiedEnvironmentValidationTests(unittest.TestCase):
    """验证环境声明在写入最终映射前完成全部结构良构检查。"""

    # 测试输入：Gamma 中重复键以及 Theta 中重复通道名的两个完整 source。
    # 预期行为：第二次声明产生 validation 错误，绝不由 Python 字典静默覆盖。
    # 检查内容：逐例核对错误阶段和 found 字段指向第二个重复名称。
    # 论文对应：保证 Gamma/Theta 均为单值有限映射，而不是保留歧义声明的列表。
    def test_duplicate_environment_keys_are_rejected(self) -> None:
        """标量、连续向量和通道声明都必须共享各自环境的唯一键约束。"""

        cases = (
            (_source_with(gamma="x: Real, x: Int"), "x"),
            (
                _source_with(
                    gamma="x: Real, motion: continuous(x), motion: Real"
                ),
                "motion",
            ),
            (
                _source_with(
                    theta=(
                        "ch: channel(x: Int), "
                        "ch: channel(y: Real)"
                    )
                ),
                "ch",
            ),
        )
        for source, repeated_name in cases:
            with self.subTest(repeated_name=repeated_name):
                with self.assertRaises(HCSPInputError) as context:
                    parse_hcsp_source(source)
                self.assertEqual(context.exception.phase, "validation")
                self.assertEqual(context.exception.found, repeated_name)

    # 测试输入：别名/未知 Gamma 类型，以及 channel 槽位中的 continuous 类型。
    # 预期行为：仅五种规范 BasicType 名称可用，其他形式均在 syntax 阶段失败。
    # 检查内容：覆盖小写 Python API 别名、项目不支持的类型和非基础槽位类型。
    # 论文对应：锁定 B ::= Bool | Nat | Int | Rational | Real 的用户输入边界。
    def test_only_canonical_basic_type_names_are_accepted(self) -> None:
        """程序化 API 的别名和非基础值类型不得泄漏进 concrete syntax。"""

        invalid_sources = (
            _source_with(gamma="x: bool"),
            _source_with(gamma="x: String"),
            _source_with(theta="ch: channel(x: integer)"),
            _source_with(theta="ch: channel(x: continuous(y))"),
        )
        for source in invalid_sources:
            with self.subTest(source=source.splitlines()[0]):
                with self.assertRaises(HCSPInputError) as context:
                    parse_hcsp_source(source)
                self.assertEqual(context.exception.phase, "syntax")

    # 测试输入：空 continuous、重复成员、保留时钟 t、缺失标量及非 Real 标量成员。
    # 预期行为：语法空列表或结构不合法向量均失败，向前引用则在读完整个 Gamma 后检查。
    # 检查内容：区分空参数 syntax 错误与其余 validation 错误，并覆盖成员 Real 要求。
    # 论文对应：连续声明只登记非空互异的完整 ODE 用户变量集合，不包含隐式时钟。
    def test_continuous_vector_structure_and_real_members_are_checked(self) -> None:
        """continuous 成员必须互异、非 t，且在同一 Gamma 中另行声明为 Real。"""

        cases = (
            (_source_with(gamma="motion: continuous()"), "syntax"),
            (
                _source_with(
                    gamma="x: Real, motion: continuous(x, x)"
                ),
                "validation",
            ),
            (
                _source_with(gamma="t: Real, motion: continuous(t)"),
                "validation",
            ),
            (
                _source_with(gamma="motion: continuous(x)"),
                "validation",
            ),
            (
                _source_with(gamma="x: Int, motion: continuous(x)"),
                "validation",
            ),
        )
        for source, phase in cases:
            with self.subTest(gamma_line=source.splitlines()[0]):
                with self.assertRaises(HCSPInputError) as context:
                    parse_hcsp_source(source)
                self.assertEqual(context.exception.phase, phase)

    # 测试输入：零槽 channel 以及同一多槽 channel 内重复使用的 binder。
    # 预期行为：unit/零元通信在 syntax 阶段失败，重复 binder 在 validation 阶段失败。
    # 检查内容：验证至少一槽的 arity 下界和 binder 与槽位一一对应后的互异性。
    # 论文对应：Theta 每次通信承载一个或多个独立 BasicType 标量，不含 unit/tuple 值。
    def test_channel_arity_and_binder_uniqueness_are_checked(self) -> None:
        """channel 签名必须非空，并为每个有序槽位给出唯一局部 binder。"""

        cases = (
            (_source_with(theta="ch: channel()"), "syntax"),
            (
                _source_with(theta="ch: channel(x: Int, x: Real)"),
                "validation",
            ),
        )
        for source, phase in cases:
            with self.subTest(theta_line=source.splitlines()[1]):
                with self.assertRaises(HCSPInputError) as context:
                    parse_hcsp_source(source)
                self.assertEqual(context.exception.phase, phase)

    # 测试输入：分别把中文、全角兼容字符放在 Gamma 键、通道名和 binder 位置。
    # 预期行为：三者均由共享词法器在 NFKC 规范化前报告 lexical 错误。
    # 检查内容：确认统一入口沿用严格 ASCII IDENT，而未借用 Python Unicode 标识符。
    # 论文对应：名称表示不改变数学结构，但项目要求所有环境和 Process 使用同一词法边界。
    def test_unicode_environment_identifiers_are_lexical_errors(self) -> None:
        """Gamma、Theta 和槽位 binder 都只能使用规范 ASCII 标识符。"""

        invalid_sources = (
            _source_with(gamma="变量: Real"),
            _source_with(theta="通道: channel(x: Int)"),
            _source_with(theta="ch: channel(ｘ: Int)"),
        )
        for source in invalid_sources:
            with self.subTest(source=source):
                with self.assertRaises(HCSPInputError) as context:
                    parse_hcsp_source(source)
                self.assertEqual(context.exception.phase, "lexical")


class UnifiedSourceSyntaxTests(unittest.TestCase):
    """验证完整 source 的固定顶层形状与共享 token 流诊断。"""

    # 测试输入：缺少顶层段、交换 gamma/theta、加入顶层分号及环境尾逗号的 source。
    # 预期行为：完整入口只接受依次相邻的 gamma、theta、process 三段且不接受尾逗号。
    # 检查内容：逐项确认所有错误归类为 syntax，而非误切文本后的局部异常。
    # 论文对应：这是用户接口的组合文法约束，不增加或删减任何 HCSP Process 产生式。
    def test_top_level_order_separators_and_required_sections_are_fixed(self) -> None:
        """完整 source 必须恰好按 gamma、theta、process 顺序连续书写。"""

        invalid_sources = (
            "theta() process {{skip}}",
            "gamma() process {{skip}}",
            "gamma() theta()",
            "theta() gamma() process {{skip}}",
            "gamma(); theta() process {{skip}}",
            "gamma(x: Real,) theta() process {{skip}}",
            "gamma() theta(ch: channel(x: Int),) process {{skip}}",
            "gamma() theta() process {{skip}} extra",
        )
        for source in invalid_sources:
            with self.subTest(source=source):
                with self.assertRaises(HCSPInputError) as context:
                    parse_hcsp_source(source)
                self.assertEqual(context.exception.phase, "syntax")

    # 测试输入：把完整 source 保留字用作环境名/Process 左值，并把 := 误写进声明。
    # 预期行为：所有形式都在 syntax 阶段拒绝，同时 := 仍保持单一最长 token。
    # 检查内容：覆盖 Gamma 键、Theta binder、Process 标识符和声明冒号边界。
    # 论文对应：这些是 concrete syntax 的词法边界，不改变任何 Process 数学节点。
    def test_environment_keywords_and_assignment_token_are_not_identifiers(self) -> None:
        """新增关键字不能退化成 IDENT，声明冒号也不能吞掉赋值运算符。"""

        invalid_sources = (
            _source_with(gamma="channel: Real"),
            _source_with(theta="ch: channel(where: Real)"),
            _source_with(process="{{process := 1}}"),
            "gamma(x := Real) theta() process {{skip}}",
            _source_with(
                theta="ch: channel(x: Real) where(x := 1)"
            ),
        )
        for source in invalid_sources:
            with self.subTest(source=source):
                with self.assertRaises(HCSPInputError) as context:
                    parse_hcsp_source(source)
                self.assertEqual(context.exception.phase, "syntax")

    # 测试输入：命名源码第六行的 channel 槽位在 binder 与 Real 之间遗漏冒号。
    # 预期行为：错误定位到 Real 的全局行列，且保留 source_name/found/expected 字段。
    # 检查内容：核对一基位置、规范字段和格式化诊断中的源码行及插入符。
    # 论文对应：保证环境错误在构造 Gamma/Theta 和执行 Table 2 之前即可精确审计。
    def test_environment_syntax_error_preserves_global_source_location(self) -> None:
        """统一解析必须共享 token 流，不能因分段解析丢失全局源码位置。"""

        source = """gamma(
    x: Real
)
theta(
    ch: channel(
        value Real
    )
)
process {{skip}}"""

        with self.assertRaises(HCSPInputError) as context:
            parse_hcsp_source(source, source_name="model.hcsp")

        error = context.exception
        self.assertEqual(error.phase, "syntax")
        self.assertEqual(error.source_name, "model.hcsp")
        self.assertEqual((error.line, error.column), (6, 15))
        self.assertEqual(error.found, "Real")
        self.assertEqual(error.expected, (":",))
        diagnostic = error.format_diagnostic()
        self.assertIn("model.hcsp:6:15", diagnostic)
        self.assertIn("        value Real", diagnostic)
        self.assertIn("              ^", diagnostic)

    # 测试输入：Gamma 第四行第二次声明 x，前面穿插注释但不改变 token 归属。
    # 预期行为：validation 错误精确定位第二个 x，而不是第一个声明或段首。
    # 检查内容：核对 phase、source_name、found 以及完整 source 的一基行列。
    # 论文对应：Gamma 是函数式有限映射，重复定义必须在 lowering 前明确拒绝。
    def test_environment_validation_error_points_to_second_declaration(self) -> None:
        """结构验证错误也必须保留统一 source 中真正违规 token 的位置。"""

        source = """gamma(
    x: Real,
    /* duplicate follows */
    x: Int
)
theta()
process {{skip}}"""

        with self.assertRaises(HCSPInputError) as context:
            parse_hcsp_source(source, source_name="duplicate.hcsp")

        error = context.exception
        self.assertEqual(error.phase, "validation")
        self.assertEqual(error.source_name, "duplicate.hcsp")
        self.assertEqual(error.found, "x")
        self.assertEqual((error.line, error.column), (4, 5))


if __name__ == "__main__":
    unittest.main()
