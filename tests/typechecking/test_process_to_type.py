"""HCSP Process/System 到行为类型的场景化转换测试。

正向案例覆盖全部 ``P`` 产生式、事件反应 ``E`` 在 ODE 中的转换以及系统并行
``S || S'``。反向案例覆盖类型规则的关键拒绝条件。每个正向案例都比较行为
类型 AST，而不只比较字符串或总体 true/false。

测试内容
--------
1. ``P01``-``P11``：全部十一种 P 节点及 ODE 事件反应的精确类型。
2. ``S01``：并行系统到 ParallelType 的转换。
3. ``C01``-``C09``：控制流组合、内部选择公共后继、有限时延节点、
   ``ODE.wait`` 和自动局部时钟。
4. ``N01``-``N13``：逻辑证明失败、静态类型失败、通道、refinement、ODE、
   递归不变量、初始路径和缺少 dL 后端的 false/unknown 路径。
5. 动态插桩所有 ``rule_t_*``，要求场景集实际进入每个规则入口。
6. 结构推导失败使用 ``None``，并验证它不会与论文正式类型 ``BottomType`` 混淆。
7. 检查推导入口的类型标注严格区分 process 类型 ``T`` 和 configuration 类型
   ``mathcal T``。
8. Gamma 只允许普通 BasicType 或 ContinuousType，Theta 的字符串键也必须
   满足与 process/type AST 相同的通道标识符规则。

论文对应
--------
正向场景逐项对应 Section 2.1 的 E/P/S 文法和 Section 4.1 的行为类型；
批注/证明义务对应 Section 4.2/4.3 与 Table 2 的类型规则。每个
``ConversionScenario`` 明确保存输入进程、Gamma、Theta、状态、路径条件、
期望 verdict、期望行为类型和应出现的证明证据。
"""

from __future__ import annotations

import inspect
import re
import unittest
from dataclasses import dataclass, field
from math import inf
from typing import Any, Callable, Mapping, get_args, get_type_hints

from hcsp_typechecker._internal import (
    Assert,
    Assign,
    BasicType,
    BottomType,
    ChannelType,
    CheckReport,
    Configuration,
    ContinuousType,
    CommunicationTimeoutType,
    ConfigurationType,
    EndType,
    EventChoice,
    ExternalChoiceType,
    If,
    InputChannel,
    InputType,
    InternalChoice,
    InternalChoiceType,
    Mu,
    MuType,
    ODE,
    ODEAnnotation,
    OutputChannel,
    OutputType,
    Parallel,
    ParallelType,
    PureDelayType,
    RecursionAnnotation,
    ProcessType,
    Sequence,
    Skip,
    TypeChecker,
    TimedExternalChoiceType,
    TypeVar,
    Var,
    Verdict,
    check_hcsp,
    types_equivalent,
)


def _true_dl(_obligation: object) -> Verdict:
    """模拟已成功验证的动态逻辑后端，以隔离行为类型构造。"""

    return Verdict.TRUE


def _select_natural_timeout(obligation: object) -> Verdict:
    """用角色感知的 mock 否证 domain 候选，唯一选中 boundary 规则。"""

    formula = getattr(obligation, "formula", None)
    return (
        Verdict.FALSE
        if getattr(formula, "role", "") == "domain"
        else Verdict.TRUE
    )


@dataclass(frozen=True)
class ConversionScenario:
    """一个进程到行为类型的可执行场景及其精确期望。"""

    case_id: str
    description: str
    process: Any
    expected_verdict: Verdict
    expected_type: ConfigurationType | None
    gamma: Mapping[str, Any] = field(default_factory=dict)
    theta: Mapping[str, Any] = field(default_factory=dict)
    state: Mapping[str, Any] = field(default_factory=dict)
    path: Any = True
    dl_checker: Callable[[object], Any] | None = None
    diagnostic_contains: tuple[str, ...] = ()
    obligation_rules: tuple[str, ...] = ()
    step_rules: tuple[str, ...] = ()

    def run(self) -> CheckReport:
        """调用内部检查器入口并返回保留全部证明证据的检查报告。"""

        return check_hcsp(
            gamma=self.gamma,
            theta=self.theta,
            configurations=[Configuration(self.state, self.process)],
            path_condition=self.path,
            dl_checker=self.dl_checker,
        )


def build_conversion_scenarios() -> tuple[ConversionScenario, ...]:
    """构造覆盖全部语法产生式和核心失败路径的稳定场景集。"""

    integer = ChannelType(BasicType.INT)

    event_ode = ODE(
        [("x", 0)],
        True,
        EventChoice.of(
            (InputChannel("sense", "sample"), Skip()),
            (OutputChannel("stop", 0), Skip()),
        ),
        annotation=ODEAnnotation(delay=inf),
    )
    infinite_fallback_ode = ODE(
        [("x", 0)],
        True,
        EventChoice.of((OutputChannel("alarm", 0), Skip())),
        annotation=ODEAnnotation(delay=inf),
    )
    terminating_ode = ODE(
        [("x", 1)],
        "x < 1",
        annotation=ODEAnnotation(delay=1),
    )
    unknown_ode = ODE(
        [("x", 1)],
        "x < 1",
        annotation=ODEAnnotation(safety="x <= 1", delay=1),
    )
    timeout_ode = ODE(
        [("x", 0)],
        True,
        EventChoice.of((OutputChannel("tick", 0), Skip())),
        annotation=ODEAnnotation(delay=2),
    )
    fallback_ode = ODE(
        [("x", 1)],
        "x < 1",
        EventChoice.of((OutputChannel("alarm", 0), Skip())),
        annotation=ODEAnnotation(delay=1),
    )
    # ODE.wait(1) 只展开为空用户方程 ODE; Skip，并使用隐藏时钟建立边界。
    # mock dL 后端隔离语法糖的类型结构与 KeYmaera X 实际求证环境。
    implicit_clock_wait = ODE.wait(1)
    ordinary_ode_variable = Sequence.of(
        ODE(
            [("x", 1)],
            "x < 1",
            annotation=ODEAnnotation(safety=True, delay=1),
        ),
        Skip(),
    )

    return (
        ConversionScenario(
            "P01_SKIP",
            "skip 转换为终止类型 0",
            Skip(),
            Verdict.TRUE,
            EndType(),
        ),
        ConversionScenario(
            "P02_ASSIGN",
            "赋值更新符号状态但不增加可观察类型前缀",
            Assign("x", 1),
            Verdict.TRUE,
            EndType(),
            gamma={"x": BasicType.INT},
            state={"x": 0},
        ),
        ConversionScenario(
            "P03_ASSERT",
            "成功断言保持 continuation 类型",
            Assert("x >= 0"),
            Verdict.TRUE,
            EndType(),
            gamma={"x": BasicType.INT},
            state={"x": 0},
            path="x >= 0",
            obligation_rules=("T-Assert",),
        ),
        ConversionScenario(
            "P04_INPUT",
            "一槽 ch?(x) 转换为输入前缀类型",
            InputChannel("in", "x"),
            Verdict.TRUE,
            InputType("in", EndType()),
            theta={"in": integer},
        ),
        ConversionScenario(
            "P05_OUTPUT",
            "一槽 ch!(e) 转换为输出前缀类型",
            OutputChannel("out", 1),
            Verdict.TRUE,
            OutputType("out", EndType()),
            theta={"out": integer},
            obligation_rules=("T-Out",),
        ),
        ConversionScenario(
            "P06_IF",
            "二元 if 转换为两个 continuation 的内部选择",
            If(
                "x >= 0",
                OutputChannel("positive", 0),
                OutputChannel("negative", 0),
            ),
            Verdict.TRUE,
            InternalChoiceType(
                (
                    OutputType("positive", EndType()),
                    OutputType("negative", EndType()),
                )
            ),
            gamma={"x": BasicType.INT},
            theta={"positive": integer, "negative": integer},
            state={"x": 0},
        ),
        ConversionScenario(
            "P07_ODE_EVENT_REACTION",
            "无限时延 ODE 按论文缩写规范为外部选择 A",
            event_ode,
            Verdict.TRUE,
            ExternalChoiceType(
                (
                    InputType("sense", EndType()),
                    OutputType("stop", EndType()),
                )
            ),
            gamma={"x": BasicType.REAL, "ode_x": ContinuousType(("x",))},
            theta={"sense": integer, "stop": integer},
            obligation_rules=("T-ODE-domain",),
        ),
        ConversionScenario(
            "P08_SEQUENCE",
            "P; P' 把后继类型嵌入前缀 continuation",
            Sequence.of(
                InputChannel("in", "x"),
                OutputChannel("out", "x"),
            ),
            Verdict.TRUE,
            InputType("in", OutputType("out", EndType())),
            theta={"in": integer, "out": integer},
            obligation_rules=("T-Out",),
        ),
        ConversionScenario(
            "P09_INTERNAL_CHOICE",
            "P |~| P' 转换为二元内部选择类型",
            InternalChoice(
                OutputChannel("left", 0),
                OutputChannel("right", 0),
            ),
            Verdict.TRUE,
            InternalChoiceType(
                (
                    OutputType("left", EndType()),
                    OutputType("right", EndType()),
                )
            ),
            theta={"left": integer, "right": integer},
            step_rules=("T-sqcup",),
        ),
        ConversionScenario(
            "P10_MU_AND_VAR",
            "mu X.P 与 X 转换为通信保护的递归类型",
            Mu(
                "X",
                Sequence.of(InputChannel("tick", "u"), Var("X")),
            ),
            Verdict.TRUE,
            MuType("T", InputType("tick", TypeVar("T"))),
            theta={"tick": integer},
            obligation_rules=("T-mu", "T-X"),
        ),
        ConversionScenario(
            "P11_TERMINATING_ODE_SEQUENCE",
            "无通信 ODE 形成以外层顺序后继为 continuation 的纯等待",
            Sequence.of(terminating_ode, OutputChannel("done", 0)),
            Verdict.TRUE,
            PureDelayType(
                1,
                OutputType("done", EndType()),
            ),
            gamma={"x": BasicType.REAL, "ode_x": ContinuousType(("x",))},
            theta={"done": integer},
            dl_checker=_true_dl,
            obligation_rules=("T-ODE-boundary",),
        ),
        ConversionScenario(
            "S01_PARALLEL",
            "S || S' 转换为两个分量的并行行为类型",
            Parallel(
                OutputChannel("left", 0),
                InputChannel("right", "u"),
            ),
            Verdict.TRUE,
            ParallelType(
                (
                    OutputType("left", EndType()),
                    InputType("right", EndType()),
                )
            ),
            theta={"left": integer, "right": integer},
        ),
        ConversionScenario(
            "C01_ASSIGN_ASSERT_SEQUENCE",
            "赋值后的符号状态可证明后继断言",
            Sequence.of(Assign("x", "x + 1"), Assert("x >= 1")),
            Verdict.TRUE,
            EndType(),
            gamma={"x": BasicType.INT},
            state={"x": 0},
            path="x >= 0",
            obligation_rules=("T-Assert",),
        ),
        ConversionScenario(
            "C02_IF_WITH_COMMON_TAIL",
            "if 两个分支都正确连接外层顺序 continuation",
            Sequence.of(
                If(
                    "x >= 0",
                    OutputChannel("positive", 0),
                    OutputChannel("negative", 0),
                ),
                OutputChannel("done", 0),
            ),
            Verdict.TRUE,
            InternalChoiceType(
                (
                    OutputType(
                        "positive",
                        OutputType("done", EndType()),
                    ),
                    OutputType(
                        "negative",
                        OutputType("done", EndType()),
                    ),
                )
            ),
            gamma={"x": BasicType.INT},
            theta={"positive": integer, "negative": integer, "done": integer},
            state={"x": 0},
        ),
        ConversionScenario(
            "C03_INPUT_BINDS_FRESH_CONTINUATION",
            "先检查无关状态 y，再输入新鲜 x 并在后继中使用",
            Sequence.of(
                Assert("y >= 0"),
                InputChannel("in", "x"),
                OutputChannel("out", "x"),
            ),
            Verdict.TRUE,
            InputType("in", OutputType("out", EndType())),
            gamma={"y": BasicType.INT},
            theta={"in": integer, "out": integer},
            state={"y": 0},
            path="y >= 0",
            obligation_rules=("T-Assert", "T-Out"),
        ),
        ConversionScenario(
            "C04_FINITE_COMMUNICATION_TIMEOUT",
            "有限 d、非空 A、无自然后继经域不变量验证形成 CommunicationTimeoutType",
            timeout_ode,
            Verdict.TRUE,
            CommunicationTimeoutType(
                2,
                OutputType("tick", EndType()),
            ),
            gamma={"x": BasicType.REAL, "ode_x": ContinuousType(("x",))},
            theta={"tick": integer},
            dl_checker=_true_dl,
            obligation_rules=("T-ODE-domain",),
        ),
        ConversionScenario(
            "C05_TIMED_EXTERNAL_CHOICE_WITH_FALLBACK",
            "有限 d、非空 A 和正常后继形成 TimedExternalChoiceType",
            Sequence.of(fallback_ode, OutputChannel("done", 0)),
            Verdict.TRUE,
            TimedExternalChoiceType(
                1,
                OutputType(
                    "alarm",
                    OutputType("done", EndType()),
                ),
                OutputType("done", EndType()),
            ),
            gamma={"x": BasicType.REAL, "ode_x": ContinuousType(("x",))},
            theta={"alarm": integer, "done": integer},
            state={"x": 0},
            path="x == 0",
            dl_checker=_true_dl,
            obligation_rules=("T-ODE-boundary",),
        ),
        ConversionScenario(
            "C06_INFINITE_DELAY_DISCARDS_TIMEOUT_FALLBACK",
            "无限 d 把超时后继设为 bottom，但通信中断后仍继续顺序 tail",
            Sequence.of(infinite_fallback_ode, OutputChannel("done", 0)),
            Verdict.TRUE,
            OutputType(
                "alarm",
                OutputType("done", EndType()),
            ),
            gamma={"x": BasicType.REAL, "ode_x": ContinuousType(("x",))},
            theta={"alarm": integer, "done": integer},
            state={"x": 0},
            obligation_rules=("T-ODE-domain",),
        ),
        ConversionScenario(
            "C07_WAIT_SUGAR_WITH_IMPLICIT_CLOCK",
            "ODE.wait(d) 无用户时钟或 Gamma 声明并生成有限纯等待类型",
            implicit_clock_wait,
            Verdict.TRUE,
            PureDelayType(1, EndType()),
            dl_checker=_select_natural_timeout,
            obligation_rules=("T-ODE-boundary",),
        ),
        ConversionScenario(
            "C08_WAIT_SUGAR_WITH_CONTINUATION",
            "ODE.wait(d) 的展开可与外层顺序后继组合",
            Sequence.of(ODE.wait(1), OutputChannel("done", 0)),
            Verdict.TRUE,
            PureDelayType(1, OutputType("done", EndType())),
            theta={"done": integer},
            dl_checker=_true_dl,
            obligation_rules=("T-ODE-boundary",),
        ),
        ConversionScenario(
            "C09_INTERNAL_CHOICE_WITH_COMMON_TAIL",
            "三元 (P |~| P'); Q 节点为两个分支保留同一顺序后继",
            InternalChoice(
                OutputChannel("left", 0),
                OutputChannel("right", 0),
                OutputChannel("done", 0),
            ),
            Verdict.TRUE,
            InternalChoiceType(
                (
                    OutputType("left", OutputType("done", EndType())),
                    OutputType("right", OutputType("done", EndType())),
                )
            ),
            theta={"left": integer, "right": integer, "done": integer},
            obligation_rules=("T-Out",),
            step_rules=("T-sqcup",),
        ),
        ConversionScenario(
            "N01_ASSERT_FALSE",
            "不可证明的断言使检查结果为 false",
            Assert("x > 0"),
            Verdict.FALSE,
            None,
            gamma={"x": BasicType.INT},
            state={"x": 0},
            obligation_rules=("T-Assert",),
        ),
        ConversionScenario(
            "N02_ASSIGN_TYPE_MISMATCH",
            "赋值右值与 Gamma 类型不匹配时不生成行为类型",
            Assign("x", True),
            Verdict.FALSE,
            None,
            gamma={"x": BasicType.INT},
            state={"x": 0},
            diagnostic_contains=("expects Int",),
        ),
        ConversionScenario(
            "N03_INPUT_CHANNEL_MISSING",
            "未在 Theta 声明的输入通道不能转换",
            InputChannel("missing", "x"),
            Verdict.FALSE,
            None,
            diagnostic_contains=("not declared in Theta",),
        ),
        ConversionScenario(
            "N04_OUTPUT_REFINEMENT_FALSE",
            "输出表达式违反通道 refinement 时拒绝",
            OutputChannel("bounded", -1),
            Verdict.FALSE,
            None,
            theta={
                "bounded": ChannelType(
                    BasicType.INT,
                    lambda eta: eta >= 0,
                )
            },
            obligation_rules=("T-Out",),
        ),
        ConversionScenario(
            "N05_IF_GUARD_NOT_BOOL",
            "if 守卫不是 Bool 时拒绝转换",
            If("x + 1", Skip(), Skip()),
            Verdict.FALSE,
            None,
            gamma={"x": BasicType.INT},
            state={"x": 0},
            diagnostic_contains=("Expected Bool formula",),
        ),
        ConversionScenario(
            "N06_ODE_VARIABLE_NOT_REAL",
            "用户 ODE 状态变量不是 Real 时拒绝；隐藏时钟不需要 Gamma 声明",
            ordinary_ode_variable,
            Verdict.FALSE,
            None,
            gamma={"x": BasicType.INT},
            dl_checker=_true_dl,
            diagnostic_contains=("must have BasicType.REAL",),
        ),
        ConversionScenario(
            "N07_ODE_WITHOUT_DL_BACKEND",
            "非平凡 ODE 证明缺少后端时返回 unknown",
            Sequence.of(unknown_ode, Skip()),
            Verdict.UNKNOWN,
            None,
            gamma={"x": BasicType.REAL, "ode_x": ContinuousType(("x",))},
            state={"x": 0},
            path="x == 0",
            diagnostic_contains=("stopped at an unknown premise",),
            obligation_rules=("T-ODE-safety",),
        ),
        ConversionScenario(
            "N08_ODE_VARIABLE_MISSING_FROM_GAMMA",
            "用户 ODE 状态变量缺少 Gamma 声明时拒绝；自动时钟不受此限制",
            ordinary_ode_variable,
            Verdict.FALSE,
            None,
            diagnostic_contains=("not declared in Gamma",),
        ),
        ConversionScenario(
            "N09_ASSERT_CONDITION_NOT_BOOL",
            "assert 条件不是 Bool 时静态类型推导失败",
            Assert("x + 1"),
            Verdict.FALSE,
            None,
            gamma={"x": BasicType.INT},
            state={"x": 0},
            diagnostic_contains=("Expected Bool formula",),
        ),
        ConversionScenario(
            "N10_INPUT_TARGET_TYPE_MISMATCH",
            "已有输入目标与通道槽位类型不兼容时不生成输入类型",
            InputChannel("number", "flag"),
            Verdict.FALSE,
            None,
            gamma={"flag": BasicType.BOOL},
            theta={"number": integer},
            state={"flag": False},
            diagnostic_contains=("channel slot carries Int",),
        ),
        ConversionScenario(
            "N11_ODE_DERIVATIVE_NOT_NUMERIC",
            "ODE 导数不是数值表达式时不生成时延类型",
            ODE(
                [("x", True)],
                True,
                annotation=ODEAnnotation(delay=inf),
            ),
            Verdict.FALSE,
            None,
            gamma={"x": BasicType.REAL, "ode_x": ContinuousType(("x",))},
            state={"x": 0},
            diagnostic_contains=("derivative of x must be numeric",),
        ),
        ConversionScenario(
            "N12_RECURSION_INVARIANT_NOT_BOOL",
            "递归不变量不是 Bool 时不构造 MuType",
            Mu(
                "X",
                Sequence.of(InputChannel("tick", "u"), Var("X")),
                annotation=RecursionAnnotation("counter + 1"),
            ),
            Verdict.FALSE,
            None,
            gamma={"counter": BasicType.INT},
            theta={"tick": integer},
            state={"counter": 0},
            diagnostic_contains=("Expected Bool formula",),
        ),
        ConversionScenario(
            "N13_INITIAL_PATH_NOT_BOOL",
            "初始路径不是 Bool 时不进入 T-sigma 的系统类型推导",
            Skip(),
            Verdict.FALSE,
            None,
            gamma={"x": BasicType.INT},
            state={"x": 0},
            path="x + 1",
            diagnostic_contains=("Expected Bool formula",),
        ),
    )


SCENARIOS = build_conversion_scenarios()


class ProcessToTypeScenarioTests(unittest.TestCase):
    """测试方法由下方场景目录动态生成，失败名直接包含案例 ID。"""


def _make_scenario_test(scenario: ConversionScenario):
    """为单个转换场景创建验证 verdict、类型和证据的测试方法。"""

    # 测试输入：scenario 中的 HCSP、Gamma、Theta、state、path 和 dL 后端。
    # 预期行为：报告 verdict/type 分别等于 scenario 的显式期望字段。
    # 检查内容：还逐项核对期望诊断片段、必须生成的证明义务来源，
    #           以及必须出现的原始/算法化规则轨迹。
    # 论文对应：每个场景的 case_id/description 指向相应 Table 2 规则。
    def test(self: ProcessToTypeScenarioTests) -> None:
        """执行一个进程到行为类型场景并核对全部声明结果。"""

        report = scenario.run()
        self.assertEqual(
            report.verdict,
            scenario.expected_verdict,
            f"{scenario.case_id}: {scenario.description}\n{report.summary()}\n"
            f"diagnostics={report.diagnostics}",
        )
        if scenario.expected_type is not None:
            self.assertIsNotNone(report.inferred_type)
            self.assertTrue(
                types_equivalent(report.inferred_type, scenario.expected_type),
                f"{scenario.case_id}: inferred {report.inferred_type}, "
                f"expected {scenario.expected_type}",
            )
        else:
            self.assertIsNone(
                report.inferred_type,
                f"{scenario.case_id}: structural failure must not fabricate a type",
            )
        diagnostic_text = "\n".join(item.message for item in report.diagnostics)
        for fragment in scenario.diagnostic_contains:
            self.assertIn(fragment, diagnostic_text)
        actual_rules = {item.rule for item in report.obligations}
        for rule in scenario.obligation_rules:
            self.assertIn(rule, actual_rules)
        actual_step_rules = {item.rule for item in report.steps}
        for rule in scenario.step_rules:
            self.assertIn(rule, actual_step_rules)

    return test


for _scenario in SCENARIOS:
    _test_name = "test_" + re.sub(
        r"[^a-z0-9]+",
        "_",
        _scenario.case_id.lower(),
    ).strip("_")
    setattr(
        ProcessToTypeScenarioTests,
        _test_name,
        _make_scenario_test(_scenario),
    )


class ProcessToTypeCoverageTests(unittest.TestCase):
    """验证场景集确实经过每个公开类型规则入口。"""

    # 测试输入：SCENARIOS 和 TypeChecker 当前全部 rule_t_* 方法。
    # 预期行为：每个已实现类型规则都至少被一个转换场景实际执行。
    # 检查内容：包装规则入口并集中报告没有测试路径的规则名称。
    # 论文对应：防止 Table 2 某条已实现类型规则没有任何自动化测试路径。
    def test_every_rule_entry_is_executed(self) -> None:
        """插桩全部 ``rule_t_*``，运行场景集后断言没有遗漏。"""

        rule_names = {
            name
            for name, value in inspect.getmembers(TypeChecker, inspect.isfunction)
            if name.startswith("rule_t_")
        }
        originals = {name: getattr(TypeChecker, name) for name in rule_names}
        executed: set[str] = set()

        def wrapper(name: str):
            """创建记录规则名并转发原调用的临时包装器。"""

            original = originals[name]

            def instrumented(self, *args, **kwargs):
                """记录一次规则执行，然后保持原规则语义。"""

                executed.add(name)
                return original(self, *args, **kwargs)

            return instrumented

        try:
            for name in rule_names:
                setattr(TypeChecker, name, wrapper(name))
            for scenario in SCENARIOS:
                scenario.run()
        finally:
            for name, original in originals.items():
                setattr(TypeChecker, name, original)

        self.assertEqual(
            executed,
            rule_names,
            f"Rules not exercised: {sorted(rule_names - executed)}",
        )


class InferenceFailureSeparationTests(unittest.TestCase):
    """验证内部推导失败、公开 None 与论文正式 ``BottomType`` 的边界。"""

    # 测试输入：合法 skip 与非法输入的并行报告，以及有限、无中断、无后继的 ODE。
    # 预期行为：前者按位置报告 (EndType(), None)，后者生成含正式 BottomType 的类型。
    # 检查内容：失败不产生 bottom/ParallelType，同时合法 Table 2 规则仍可产生正式 bottom。
    # 论文对应：Section 4.1 的 \bot 是行为类型，只能来自类型规则，不能表示 T-In 失败。
    def test_failure_is_none_while_formal_bottom_remains_a_type(self) -> None:
        """同时确认失败标记与论文正式 bottom 在两个方向上都不会混淆。"""

        report = check_hcsp(
            gamma={},
            theta={},
            configurations=[
                Configuration({}, Skip(), name="valid"),
                Configuration({}, InputChannel("missing", "x"), name="invalid"),
            ],
        )

        self.assertEqual(report.verdict, Verdict.FALSE)
        self.assertIsNone(report.inferred_type)
        self.assertEqual(report.component_types, (EndType(), None))
        self.assertFalse(
            any(isinstance(item, BottomType) for item in report.component_types)
        )

        formal_bottom_report = check_hcsp(
            gamma={"x": BasicType.REAL, "ode_x": ContinuousType(("x",))},
            theta={},
            configurations=[
                Configuration(
                    {"x": 0},
                    ODE(
                        [("x", 0)],
                        True,
                        annotation=ODEAnnotation(delay=1),
                    ),
                )
            ],
            dl_checker=_true_dl,
        )
        self.assertEqual(formal_bottom_report.verdict, Verdict.TRUE)
        self.assertEqual(
            formal_bottom_report.inferred_type,
            PureDelayType(1, BottomType()),
        )


class InferenceLayerAnnotationTests(unittest.TestCase):
    """锁定显式 process/system judgment 求解器的返回类型层次。"""

    # 测试输入：统一推导引擎中 process 与 system judgment 求解器的运行时标注。
    # 预期行为：前者返回 ProcessType|失败，后者返回 ConfigurationType|失败。
    # 检查内容：两层共享同一个非行为类型失败分支，且类型层次不会互相流入。
    # 论文对应：Section 4.1 的 T 与 Section 4.2 的 mathcal T 不得在推导入口混用。
    def test_process_and_system_inference_annotations_are_separated(self) -> None:
        """验证子 judgment 求解结果与 ``P :: T``、``S :: mathcal T`` 一致。"""

        process_hints = get_type_hints(TypeChecker._solve_process_judgment)
        system_hints = get_type_hints(TypeChecker._solve_system_judgment)
        process_members = set(get_args(process_hints["return"]))
        system_members = set(get_args(system_hints["return"]))

        self.assertIn(ProcessType, process_members)
        self.assertNotIn(ConfigurationType, process_members)
        self.assertIn(ConfigurationType, system_members)
        self.assertNotIn(ProcessType, system_members)
        self.assertEqual(
            process_members - {ProcessType},
            system_members - {ConfigurationType},
        )


class TypingEnvironmentBoundaryTests(unittest.TestCase):
    """验证 Gamma/Theta 环境入口遵守基础类型和通道命名边界。"""

    # 测试输入：全局 Gamma 和 Configuration 局部 Gamma 分别使用 tuple/list 类型说明。
    # 预期行为：两种入口都返回 false、无候选类型，并报告 Gamma 项类型要求。
    # 检查内容：确认局部环境失败也产生推导失败，而不是退化为空 Gamma 后继续。
    # 论文对应：Definition 4.1 的 Gamma 把每个状态变量映射到一个基础类型 B。
    def test_global_and_local_gamma_reject_container_type_specs(self) -> None:
        """全局和分量局部 Gamma 都不能使用 tuple/list 类型说明。"""

        global_report = check_hcsp(
            gamma={"state": (BasicType.INT, BasicType.REAL)},  # type: ignore[dict-item]
            theta={},
            configurations=[Configuration({}, Skip())],
        )
        local_report = check_hcsp(
            gamma={},
            theta={},
            configurations=[
                Configuration(
                    {},
                    Skip(),
                    gamma={"state": [BasicType.INT, BasicType.REAL]},  # type: ignore[dict-item]
                )
            ],
        )

        for report in (global_report, local_report):
            with self.subTest(report=report):
                self.assertEqual(report.verdict, Verdict.FALSE)
                self.assertIsNone(report.inferred_type)
                self.assertTrue(
                    any(
                        "Gamma entry must be a BasicType or ContinuousType"
                        in item.message
                        for item in report.diagnostics
                    )
                )

    # 测试输入：Theta 使用带首尾空格的字符串键，配置本身只含 Skip。
    # 预期行为：公开检查入口返回 false，并报告 Invalid typing environment。
    # 检查内容：确认非法通道名即使未出现在 process AST 中也会被统一拒绝。
    # 论文对应：Theta 的定义域与 ch?.T/ch!.T 使用同一组通道标识符。
    def test_theta_rejects_non_identifier_channel_name(self) -> None:
        """Theta 的字符串键必须通过统一的 Channel 标识符检查。"""

        report = check_hcsp(
            gamma={},
            theta={" invalid ": ChannelType(BasicType.INT)},
            configurations=[Configuration({}, Skip())],
        )

        self.assertEqual(report.verdict, Verdict.FALSE)
        self.assertIsNone(report.inferred_type)
        self.assertTrue(
            any(
                diagnostic.rule == "environment"
                and "Invalid channel name" in diagnostic.message
                for diagnostic in report.diagnostics
            )
        )

    # 测试输入：全局/局部 Gamma 分别使用 Unicode 与非字符串声明键。
    # 预期行为：两者在任何规则执行前作为非法环境返回 false。
    # 检查内容：确认环境入口不再把键经 str() 静默改名或接受 Python Unicode 名称。
    # 论文对应：Definition 4.1 的 Gamma 定义域与 Process 状态变量使用同一 IDENT。
    def test_gamma_names_use_the_same_ascii_ident_rule(self) -> None:
        """全局和局部 Gamma 的键必须是原生 ASCII IDENT 字符串。"""

        global_report = check_hcsp(
            gamma={"变量": BasicType.INT},
            theta={},
            configurations=[Configuration({}, Skip())],
        )
        local_report = check_hcsp(
            gamma={},
            theta={},
            configurations=[
                Configuration(
                    {},
                    Skip(),
                    gamma={1: BasicType.INT},  # type: ignore[dict-item]
                )
            ],
        )

        for report in (global_report, local_report):
            with self.subTest(report=report):
                self.assertEqual(report.verdict, Verdict.FALSE)
                self.assertIsNone(report.inferred_type)
                self.assertTrue(
                    any(
                        "Gamma names" in diagnostic.message
                        for diagnostic in report.diagnostics
                    )
                )


if __name__ == "__main__":
    unittest.main()
