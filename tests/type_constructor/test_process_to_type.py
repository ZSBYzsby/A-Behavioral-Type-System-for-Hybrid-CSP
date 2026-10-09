r"""Regression tests for process to type. Paper reference: Section 2.1, Section 4.1, Section
4.2/4.3, Table 2.
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
    TypeConstructionReport,
    Configuration,
    ContinuousType,
    ConfigurationType,
    EmptyType,
    EventChoice,
    ExternalChoiceType,
    If,
    InputChannel,
    InputType,
    InfiniteDelayType,
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
    FiniteDelayType,
    RecursionAnnotation,
    ProcessType,
    Sequence,
    Skip,
    TypeConstructor,
    NoInterruptType,
    TypeVar,
    Var,
    Verdict,
    construct_type,
    types_equivalent,
)


def _true_dl(_obligation: object) -> Verdict:
    r"""Approve dL goals with a mock backend to isolate construction."""

    return Verdict.TRUE


def _select_natural_timeout(obligation: object) -> Verdict:
    r"""Reject domain preservation and approve the boundary candidate."""

    formula = getattr(obligation, "formula", None)
    return (
        Verdict.FALSE
        if getattr(formula, "role", "") == "domain"
        else Verdict.TRUE
    )


def _select_communication_only(obligation: object) -> Verdict:
    r"""Approve the domain candidate and reject the timeout candidate."""

    formula = getattr(obligation, "formula", None)
    return (
        Verdict.FALSE
        if getattr(formula, "role", "") == "boundary"
        else Verdict.TRUE
    )


def _unknown_dl(_obligation: object) -> Verdict:
    r"""Return UNKNOWN to exercise complete untrusted candidate construction."""

    return Verdict.UNKNOWN


@dataclass(frozen=True)
class ConversionScenario:
    r"""An executable Process-to-Type scenario with exact expected results."""

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

    def run(self) -> TypeConstructionReport:
        r"""Call internal construction and retain the complete evidence report."""

        return construct_type(
            gamma=self.gamma,
            theta=self.theta,
            configurations=[Configuration(self.state, self.process)],
            path_condition=self.path,
            dl_checker=self.dl_checker,
        )


def build_conversion_scenarios() -> tuple[ConversionScenario, ...]:
    r"""Define exact conversion scenarios for syntax and failure paths."""

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
            'skip becomes termination type 0',
            Skip(),
            Verdict.TRUE,
            EmptyType(),
        ),
        ConversionScenario(
            "P02_ASSIGN",
            'Assignment updates symbolic state without an observable type prefix',
            Assign("x", 1),
            Verdict.TRUE,
            EmptyType(),
            gamma={"x": BasicType.INT},
            state={"x": 0},
        ),
        ConversionScenario(
            "P03_ASSERT",
            'A proved assertion preserves the continuation type',
            Assert("x >= 0"),
            Verdict.TRUE,
            EmptyType(),
            gamma={"x": BasicType.INT},
            state={"x": 0},
            path="x >= 0",
            obligation_rules=("T-Assert",),
        ),
        ConversionScenario(
            "P04_INPUT",
            'Scalar ch?(x) becomes an input prefix',
            InputChannel("in", "x"),
            Verdict.TRUE,
            InfiniteDelayType(InputType("in", EmptyType())),
            theta={"in": integer},
        ),
        ConversionScenario(
            "P05_OUTPUT",
            'Scalar ch!(e) becomes an output prefix',
            OutputChannel("out", 1),
            Verdict.TRUE,
            InfiniteDelayType(OutputType("out", EmptyType())),
            theta={"out": integer},
            obligation_rules=("T-Out",),
        ),
        ConversionScenario(
            "P06_IF",
            'Binary if becomes an internal choice of two continuations',
            If(
                "x >= 0",
                OutputChannel("positive", 0),
                OutputChannel("negative", 0),
            ),
            Verdict.TRUE,
            InternalChoiceType(
                (
                    InfiniteDelayType(OutputType("positive", EmptyType())),
                    InfiniteDelayType(OutputType("negative", EmptyType())),
                )
            ),
            gamma={"x": BasicType.INT},
            theta={"positive": integer, "negative": integer},
            state={"x": 0},
        ),
        ConversionScenario(
            "P07_ODE_EVENT_REACTION",
            'An infinite-delay ODE retains an unreachable bottom continuation explicitly',
            Sequence.of(event_ode, Skip()),
            Verdict.TRUE,
            InfiniteDelayType(ExternalChoiceType(
                (
                    InputType("sense", EmptyType()),
                    OutputType("stop", EmptyType()),
                )
            )),
            gamma={"x": BasicType.REAL, "ode_x": ContinuousType(("x",))},
            theta={"sense": integer, "stop": integer},
            obligation_rules=("T-ODE-domain",),
        ),
        ConversionScenario(
            "P08_SEQUENCE",
            "P; P' embeds the successor type into the prefix continuation",
            Sequence.of(
                InputChannel("in", "x"),
                OutputChannel("out", "x"),
            ),
            Verdict.TRUE,
            InfiniteDelayType(
                InputType(
                    "in",
                    InfiniteDelayType(OutputType("out", EmptyType())),
                )
            ),
            theta={"in": integer, "out": integer},
            obligation_rules=("T-Out",),
        ),
        ConversionScenario(
            "P09_INTERNAL_CHOICE",
            'P_1 |~| ... |~| P_n becomes an n-ary internal choice',
            InternalChoice(
                OutputChannel("left", 0),
                OutputChannel("right", 0),
                OutputChannel("audit", 0),
            ),
            Verdict.TRUE,
            InternalChoiceType(
                (
                    InfiniteDelayType(OutputType("left", EmptyType())),
                    InfiniteDelayType(OutputType("right", EmptyType())),
                    InfiniteDelayType(OutputType("audit", EmptyType())),
                )
            ),
            theta={"left": integer, "right": integer, "audit": integer},
            step_rules=("T-sqcup",),
        ),
        ConversionScenario(
            "P10_MU_AND_VAR",
            'mu X.P and X become a communication-guarded recursive type',
            Mu(
                "X",
                Sequence.of(InputChannel("tick", "u"), Var("X")),
            ),
            Verdict.TRUE,
            MuType(
                "T",
                InfiniteDelayType(InputType("tick", TypeVar("T"))),
            ),
            theta={"tick": integer},
            obligation_rules=("T-mu", "T-X"),
        ),
        ConversionScenario(
            "P11_TERMINATING_ODE_SEQUENCE",
            'An ODE without communication becomes a wait with the sequential continuation',
            Sequence.of(terminating_ode, OutputChannel("done", 0)),
            Verdict.TRUE,
            FiniteDelayType(
                1,
                NoInterruptType(),
                InfiniteDelayType(OutputType("done", EmptyType())),
            ),
            gamma={"x": BasicType.REAL, "ode_x": ContinuousType(("x",))},
            theta={"done": integer},
            dl_checker=_true_dl,
            obligation_rules=("T-ODE-boundary",),
        ),
        ConversionScenario(
            "S01_PARALLEL",
            "S || S' becomes a parallel type with two components",
            Parallel(
                OutputChannel("left", 0),
                InputChannel("right", "u"),
            ),
            Verdict.TRUE,
            ParallelType(
                (
                    InfiniteDelayType(OutputType("left", EmptyType())),
                    InfiniteDelayType(InputType("right", EmptyType())),
                )
            ),
            theta={"left": integer, "right": integer},
        ),
        ConversionScenario(
            "C01_ASSIGN_ASSERT_SEQUENCE",
            'Post-assignment symbolic state proves the following assertion',
            Sequence.of(Assign("x", "x + 1"), Assert("x >= 1")),
            Verdict.TRUE,
            EmptyType(),
            gamma={"x": BasicType.INT},
            state={"x": 0},
            path="x >= 0",
            obligation_rules=("T-Assert",),
        ),
        ConversionScenario(
            "C02_IF_WITH_COMMON_TAIL",
            'Both if branches connect to the outer sequential continuation',
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
                    InfiniteDelayType(
                        OutputType(
                            "positive",
                            InfiniteDelayType(OutputType("done", EmptyType())),
                        )
                    ),
                    InfiniteDelayType(
                        OutputType(
                            "negative",
                            InfiniteDelayType(OutputType("done", EmptyType())),
                        )
                    ),
                )
            ),
            gamma={"x": BasicType.INT},
            theta={"positive": integer, "negative": integer, "done": integer},
            state={"x": 0},
        ),
        ConversionScenario(
            "C03_INPUT_BINDS_FRESH_CONTINUATION",
            'Check unrelated state y, receive fresh x, and use it in the continuation',
            Sequence.of(
                Assert("y >= 0"),
                InputChannel("in", "x"),
                OutputChannel("out", "x"),
            ),
            Verdict.TRUE,
            InfiniteDelayType(
                InputType(
                    "in",
                    InfiniteDelayType(OutputType("out", EmptyType())),
                )
            ),
            gamma={"y": BasicType.INT},
            theta={"in": integer, "out": integer},
            state={"y": 0},
            path="y >= 0",
            obligation_rules=("T-Assert", "T-Out"),
        ),
        ConversionScenario(
            "C04_FINITE_COMMUNICATION_TIMEOUT",
            'Finite d with nonempty A and terminal skip selects a finite-delay candidate',
            Sequence.of(timeout_ode, Skip()),
            Verdict.TRUE,
            FiniteDelayType(2, OutputType("tick", EmptyType()), BottomType()),
            gamma={"x": BasicType.REAL, "ode_x": ContinuousType(("x",))},
            theta={"tick": integer},
            dl_checker=_select_communication_only,
            obligation_rules=("T-ODE-domain",),
        ),
        ConversionScenario(
            "C05_TIMED_EXTERNAL_CHOICE_WITH_FALLBACK",
            'Finite d with nonempty A and a normal continuation produces FiniteDelayType',
            Sequence.of(fallback_ode, OutputChannel("done", 0)),
            Verdict.TRUE,
            FiniteDelayType(
                1,
                OutputType(
                    "alarm",
                    InfiniteDelayType(OutputType("done", EmptyType())),
                ),
                InfiniteDelayType(OutputType("done", EmptyType())),
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
            'Infinite d has no natural timeout; communication interrupts continue with the sequential tail',
            Sequence.of(infinite_fallback_ode, OutputChannel("done", 0)),
            Verdict.TRUE,
            InfiniteDelayType(OutputType(
                "alarm",
                InfiniteDelayType(OutputType("done", EmptyType())),
            )),
            gamma={"x": BasicType.REAL, "ode_x": ContinuousType(("x",))},
            theta={"alarm": integer, "done": integer},
            state={"x": 0},
            obligation_rules=("T-ODE-domain",),
        ),
        ConversionScenario(
            "C09_INTERNAL_CHOICE_WITH_COMMON_TAIL",
            'Every n-ary internal-choice branch retains the same sequential continuation',
            InternalChoice(
                OutputChannel("left", 0),
                OutputChannel("right", 0),
                continuation=OutputChannel("done", 0),
            ),
            Verdict.TRUE,
            InternalChoiceType(
                (
                    InfiniteDelayType(
                        OutputType(
                            "left",
                            InfiniteDelayType(OutputType("done", EmptyType())),
                        )
                    ),
                    InfiniteDelayType(
                        OutputType(
                            "right",
                            InfiniteDelayType(OutputType("done", EmptyType())),
                        )
                    ),
                )
            ),
            theta={"left": integer, "right": integer, "done": integer},
            obligation_rules=("T-Out",),
            step_rules=("T-sqcup",),
        ),
        ConversionScenario(
            "N01_ASSERT_FALSE",
            'An unprovable assertion gives a false construction verdict',
            Assert("x > 0"),
            Verdict.FALSE,
            None,
            gamma={"x": BasicType.INT},
            state={"x": 0},
            obligation_rules=("T-Assert",),
        ),
        ConversionScenario(
            "N02_ASSIGN_TYPE_MISMATCH",
            'An assignment incompatible with Gamma produces no behavioral type',
            Assign("x", True),
            Verdict.FALSE,
            None,
            gamma={"x": BasicType.INT},
            state={"x": 0},
            diagnostic_contains=("expects Int",),
        ),
        ConversionScenario(
            "N03_INPUT_CHANNEL_MISSING",
            'An input channel missing from Theta cannot be translated',
            InputChannel("missing", "x"),
            Verdict.FALSE,
            None,
            diagnostic_contains=("not declared in Theta",),
        ),
        ConversionScenario(
            "N04_OUTPUT_REFINEMENT_FALSE",
            'An output payload violating the channel refinement is rejected',
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
            'A non-Bool if guard is rejected',
            If("x + 1", Skip(), Skip()),
            Verdict.FALSE,
            None,
            gamma={"x": BasicType.INT},
            state={"x": 0},
            diagnostic_contains=("Expected Bool formula",),
        ),
        ConversionScenario(
            "N06_ODE_VARIABLE_NOT_REAL",
            'Non-Real ODE state variables are rejected; the hidden clock needs no Gamma declaration',
            ordinary_ode_variable,
            Verdict.FALSE,
            None,
            gamma={"x": BasicType.INT},
            dl_checker=_true_dl,
            diagnostic_contains=("must have BasicType.REAL",),
        ),
        ConversionScenario(
            "N07_ODE_WITHOUT_DL_BACKEND",
            'An unresolved nontrivial ODE proof still produces a complete, untrusted candidate',
            Sequence.of(unknown_ode, Skip()),
            Verdict.UNKNOWN,
            FiniteDelayType(1, NoInterruptType(), EmptyType()),
            gamma={"x": BasicType.REAL, "ode_x": ContinuousType(("x",))},
            state={"x": 0},
            path="x == 0",
            dl_checker=_unknown_dl,
            diagnostic_contains=(),
            obligation_rules=(
                "T-ODE-safety",
                "T-ODE-boundary",
            ),
        ),
        ConversionScenario(
            "N08_ODE_VARIABLE_MISSING_FROM_GAMMA",
            'ODE variables missing from Gamma are rejected; the automatic clock is exempt',
            ordinary_ode_variable,
            Verdict.FALSE,
            None,
            diagnostic_contains=("not declared in Gamma",),
        ),
        ConversionScenario(
            "N09_ASSERT_CONDITION_NOT_BOOL",
            'A non-Bool assertion fails static typing',
            Assert("x + 1"),
            Verdict.FALSE,
            None,
            gamma={"x": BasicType.INT},
            state={"x": 0},
            diagnostic_contains=("Expected Bool formula",),
        ),
        ConversionScenario(
            "N10_INPUT_TARGET_TYPE_MISMATCH",
            'An input target incompatible with the channel slot produces no input type',
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
            'A nonnumeric ODE derivative produces no delay type',
            Sequence.of(
                ODE(
                    [("x", True)],
                    True,
                    annotation=ODEAnnotation(delay=inf),
                ),
                Skip(),
            ),
            Verdict.FALSE,
            None,
            gamma={"x": BasicType.REAL, "ode_x": ContinuousType(("x",))},
            state={"x": 0},
            diagnostic_contains=("derivative of x must be numeric",),
        ),
        ConversionScenario(
            "N12_RECURSION_INVARIANT_NOT_BOOL",
            'A non-Bool recursion invariant produces no MuType',
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
            'A non-Bool initial path condition prevents T-sigma system derivation',
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
    r"""Tests for Process To Type Scenario."""


def _make_scenario_test(scenario: ConversionScenario):
    r"""Create a test checking the scenario verdict, type, and evidence."""


    def test(self: ProcessToTypeScenarioTests) -> None:
        r"""Verify the scenario verdict, exact Type, and proof evidence."""

        report = scenario.run()
        self.assertEqual(
            report.verdict,
            scenario.expected_verdict,
            f"{scenario.case_id}: {scenario.description}\n{report.summary()}\n"
            f"diagnostics={report.diagnostics}",
        )
        if scenario.expected_type is not None:
            self.assertIsNotNone(report.constructed_type)
            self.assertTrue(
                types_equivalent(report.constructed_type, scenario.expected_type),
                f"{scenario.case_id}: constructed {report.constructed_type}, "
                f"expected {scenario.expected_type}",
            )
        else:
            self.assertIsNone(
                report.constructed_type,
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
    r"""Tests for Process To Type Coverage."""


    def test_every_rule_entry_is_executed(self) -> None:
        r"""Verify every rule entry is executed."""

        rule_names = {
            name
            for name, value in inspect.getmembers(TypeConstructor, inspect.isfunction)
            if name.startswith("rule_t_")
        }
        originals = {name: getattr(TypeConstructor, name) for name in rule_names}
        executed: set[str] = set()

        def wrapper(name: str):
            r"""Record a rule invocation and delegate to its original implementation."""

            original = originals[name]

            def instrumented(self, *args, **kwargs):
                r"""Count a rule invocation without changing its semantics."""

                executed.add(name)
                return original(self, *args, **kwargs)

            return instrumented

        try:
            for name in rule_names:
                setattr(TypeConstructor, name, wrapper(name))
            for scenario in SCENARIOS:
                scenario.run()
        finally:
            for name, original in originals.items():
                setattr(TypeConstructor, name, original)

        self.assertEqual(
            executed,
            rule_names,
            f"Rules not exercised: {sorted(rule_names - executed)}",
        )


class ConstructionFailureSeparationTests(unittest.TestCase):
    r"""Tests for Construction Failure Separation."""


    def test_failure_is_none_and_terminal_ode_uses_bottom(self) -> None:
        r"""Verify failure is none and terminal ODE uses bottom."""

        report = construct_type(
            gamma={},
            theta={},
            configurations=[
                Configuration({}, Skip(), name="valid"),
                Configuration({}, InputChannel("missing", "x"), name="invalid"),
            ],
        )

        self.assertEqual(report.verdict, Verdict.FALSE)
        self.assertIsNone(report.constructed_type)
        self.assertEqual(report.constructed_component_types, (EmptyType(), None))
        terminal_ode_report = construct_type(
            gamma={"x": BasicType.REAL, "ode_x": ContinuousType(("x",))},
            theta={},
            configurations=[
                Configuration(
                    {"x": 0},
                    Sequence.of(
                        ODE(
                            [("x", 0)],
                            True,
                            annotation=ODEAnnotation(delay=1),
                        ),
                        Skip(),
                    ),
                )
            ],
            dl_checker=_select_communication_only,
        )
        self.assertEqual(terminal_ode_report.verdict, Verdict.TRUE)
        self.assertEqual(
            terminal_ode_report.constructed_type,
            FiniteDelayType(1, NoInterruptType(), BottomType()),
        )


class ConstructionLayerAnnotationTests(unittest.TestCase):
    r"""Tests for Construction Layer Annotation."""


    def test_process_and_system_construction_annotations_are_separated(self) -> None:
        r"""Verify process and system construction annotations are separated."""

        process_hints = get_type_hints(TypeConstructor._solve_process_judgment)
        system_hints = get_type_hints(TypeConstructor._solve_system_judgment)
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
    r"""Tests for Typing Environment Boundary."""


    def test_gamma_rejects_container_type_specs(self) -> None:
        r"""Verify Gamma rejects container type specs."""

        global_report = construct_type(
            gamma={"state": (BasicType.INT, BasicType.REAL)},  # type: ignore[dict-item]
            theta={},
            configurations=[Configuration({}, Skip())],
        )
        self.assertEqual(global_report.verdict, Verdict.FALSE)
        self.assertIsNone(global_report.constructed_type)
        self.assertTrue(
            any(
                "Gamma entry must be a BasicType or ContinuousType"
                in item.message
                for item in global_report.diagnostics
            )
        )


    def test_theta_rejects_non_identifier_channel_name(self) -> None:
        r"""Verify Theta rejects non identifier channel name."""

        report = construct_type(
            gamma={},
            theta={" invalid ": ChannelType(BasicType.INT)},
            configurations=[Configuration({}, Skip())],
        )

        self.assertEqual(report.verdict, Verdict.FALSE)
        self.assertIsNone(report.constructed_type)
        self.assertTrue(
            any(
                diagnostic.rule == "environment"
                and "Invalid channel name" in diagnostic.message
                for diagnostic in report.diagnostics
            )
        )


    def test_gamma_names_use_the_same_ascii_ident_rule(self) -> None:
        r"""Verify Gamma names use the same ascii ident rule."""

        global_report = construct_type(
            gamma={"\u03b1\u03b2": BasicType.INT},
            theta={},
            configurations=[Configuration({}, Skip())],
        )
        self.assertEqual(global_report.verdict, Verdict.FALSE)
        self.assertIsNone(global_report.constructed_type)
        self.assertTrue(
            any(
                "Gamma names" in diagnostic.message
                for diagnostic in global_report.diagnostics
            )
        )


if __name__ == "__main__":
    unittest.main()
