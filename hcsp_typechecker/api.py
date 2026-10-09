r"""Public facade connecting text parsing, Table 2 proofs, Table 3 graphs, and lock analysis."""

from __future__ import annotations

from collections.abc import Mapping, Sequence
from dataclasses import dataclass, field, replace
from enum import Enum
import sys
from typing import Any, TextIO, TypeAlias

from .frontend.errors import HCSPInputError
from .frontend.type_constructor_frontend.parser import (
    parse_expression,
    parse_hcsp_source,
)
from .frontend.type_checker_frontend import parse_typechecking_source
from .frontend.type_constructor_frontend.source import ParsedHCSPSource
from .frontend.normalized_type_syntax import (
    format_normalized_type_ast as _format_normalized_type_ast,
)
from .frontend.type_transition_graph_syntax import (
    format_type_transition_graph as _format_type_transition_graph,
)
from .frontend.type_lock_analysis_syntax import (
    format_lock_freedom_full as _format_lock_freedom_full,
    format_lock_freedom_result as _format_lock_freedom_result,
)
from .data_structures.process_ast.ast import HCSP, Process
from .data_structures.type_ast.ast import ConfigurationType
from .data_structures.type_ast.render import format_type_source
from .data_structures.normalized_type_ast import TypeNormalizationError
from .backend.type_constructor import (
    TypeConstructionErrorKind,
    TypeConstructionReport,
    classify_construction_error,
    construct_type,
)
from .backend.type_checker import (
    TypeChecker,
    TypeCheckingErrorKind,
    TypeCheckingRequest,
    classify_checking_error,
)
from .backend.type_operational_semantics import (
    TypeTransitionGraphSizeError,
    build_type_transition_graph as _build_type_transition_graph,
)
from .backend.type_lock_analysis import (
    IncompleteTransitionGraphError,
    analyze_lock_freedom as _analyze_lock_freedom,
)
from .backend.common.keymaerax import KeYmaeraXConfig
from .backend.common.model import Verdict
from .data_structures.type_transition_graph import TypeTransitionGraph
from .data_structures.type_lock_analysis import LockFreedomReport
from .data_structures.runtime_context import (
    ChannelType,
    Configuration,
    GammaType,
    ParameterEnvironment,
)


# The public API exposes TypeAST without promising specific node constructors.
TypeAST: TypeAlias = ConfigurationType


class OutputMode(str, Enum):
    r"""Select text verbosity without changing results, proofs, or exception types."""

    NONE = "none"
    RESULT = "result"
    FULL = "full"


class TypeTransitionGraphErrorKind(str, Enum):
    r"""Stable categories for invalid types, normalization failures, and graph limits."""

    INVALID_TYPE = "invalid-type"
    INVALID_LIMIT = "invalid-limit"
    NORMALIZATION = "normalization"
    SIZE_LIMIT = "size-limit"


class TypeLockAnalysisErrorKind(str, Enum):
    r"""Stable categories for invalid graphs and incomplete reachable closures."""

    INVALID_GRAPH = "invalid-graph"
    INCOMPLETE_GRAPH = "incomplete-graph"


@dataclass(frozen=True, slots=True)
class HCSPErrorDetail:
    r"""Structured diagnostic evidence including rule, location, formula, and prover detail."""

    category: str
    verdict: str
    message: str
    rule: str = ""
    location: str = ""
    proof_kind: str = ""
    formula: str = ""
    backend_detail: str = ""


def _normalize_output_mode(value: OutputMode | str) -> OutputMode:
    r"""Normalize the string shorthand to an OutputMode."""

    if isinstance(value, OutputMode):
        return value
    if isinstance(value, str):
        try:
            return OutputMode(value.strip().lower())
        except ValueError as exc:
            raise ValueError(
                "output must be 'none', 'result', or 'full'"
            ) from exc
    raise TypeError("output must be an OutputMode or string")


def _write_output(text: str, stream: TextIO | None) -> None:
    r"""Write one rendered result to the selected text stream."""

    destination = sys.stdout if stream is None else stream
    print(text, file=destination)


def _format_environment(environment: Mapping[str, Any]) -> str:
    r"""Display an environment compactly in declaration order."""

    if not environment:
        return "{}"
    entries = ", ".join(
        f"{name}: {declaration}" for name, declaration in environment.items()
    )
    return "{" + entries + "}"


@dataclass(frozen=True, slots=True)
class _ProgramContext:
    r"""Keep environments and Process ASTs from one parse bound to one API call."""

    source_text: str = field(repr=False)
    source_name: str
    parsed: ParsedHCSPSource = field(repr=False)

    def __post_init__(self) -> None:
        r"""Validate that the context contains a complete parsed program."""

        if not isinstance(self.source_text, str):
            raise TypeError("HCSP source must be a string")
        if not isinstance(self.source_name, str) or not self.source_name:
            raise ValueError("source_name must be a non-empty string")
        if not isinstance(self.parsed, ParsedHCSPSource):
            raise TypeError("internal program context requires ParsedHCSPSource")

    @property
    def process_ast(self) -> HCSP:
        r"""Return the internal Process or Parallel AST for this call."""

        return self.parsed.process

    @property
    def gamma(self) -> Mapping[str, GammaType]:
        r"""Return the call's read-only Gamma."""

        return self.parsed.gamma

    @property
    def theta(self) -> Mapping[str, ChannelType]:
        r"""Return the call's read-only Theta."""

        return self.parsed.theta

    @property
    def parameters(self) -> ParameterEnvironment:
        r"""Return shared parameters and their constraint."""

        return self.parsed.parameters

    @property
    def process_components(self) -> tuple[Process, ...]:
        r"""Return top-level process leaves in source order."""

        return self.parsed.process_components

    def format_full(self) -> str:
        r"""Display source and environment summaries without exporting Process AST objects."""

        return "\n".join(
            (
                '=== HCSP type construction full log ===',
                f"Source : {self.source_name}",
                "",
                '--- Original user input ---',
                self.source_text,
                "",
                '--- Input parsing and internal model construction ---',
                'Status       : success',
                f"Parameters : {_format_environment(self.parameters.declarations)}",
                f"Constraint H : {self.parameters.constraint}",
                f"Gamma      : {_format_environment(self.gamma)}",
                f"Theta      : {_format_environment(self.theta)}",
                f"Process count : {len(self.process_components)}",
                'Process AST : constructed internally; not exposed by the public API',
            )
        )


def _parse_program(source: str, source_name: str) -> _ProgramContext:
    r"""Parse complete input into a call-local program context."""

    parsed = parse_hcsp_source(source, source_name=source_name)
    return _ProgramContext(
        source_text=source,
        source_name=source_name,
        parsed=parsed,
    )


def _first_report_reason(report: TypeConstructionReport) -> str:
    r"""Select a concise failure reason consistent with the final verdict."""

    # Match the primary reason to the final verdict: a later FALSE outranks earlier UNKNOWN.
    for diagnostic in report.diagnostics:
        if diagnostic.verdict is report.verdict:
            return diagnostic.message
    for obligation in report.obligations:
        if (
            obligation.verdict is report.verdict
            and obligation.verdict is not Verdict.TRUE
        ):
            return obligation.detail or obligation.description
    if report.diagnostics:
        return report.diagnostics[0].message
    for obligation in report.obligations:
        if obligation.verdict is not Verdict.TRUE:
            return obligation.detail or obligation.description
    if report.verdict is Verdict.UNKNOWN:
        return 'Some premises remain unproved'
    return 'TypeConstructor did not produce a trusted Type AST'


_ENVIRONMENT_RULES = frozenset({"environment", "parameters"})


def _report_error_details(
    report: TypeConstructionReport,
    *,
    mismatch: str = "",
    rule_category: str = "derivation",
) -> tuple[HCSPErrorDetail, ...]:
    r"""Convert diagnostics and failed obligations into stable public error details."""

    details: list[HCSPErrorDetail] = []
    for diagnostic in report.diagnostics:
        if diagnostic.verdict is Verdict.TRUE:
            continue
        if diagnostic.rule in _ENVIRONMENT_RULES:
            category = "environment"
        elif mismatch and diagnostic.message == mismatch:
            category = "type-mismatch"
        else:
            category = rule_category
        details.append(
            HCSPErrorDetail(
                category=category,
                verdict=diagnostic.verdict.value,
                message=diagnostic.message,
                rule=diagnostic.rule,
                location=diagnostic.location,
            )
        )
    for obligation in report.obligations:
        if not obligation.active or obligation.verdict is Verdict.TRUE:
            continue
        details.append(
            HCSPErrorDetail(
                category=(
                    "proof-failed"
                    if obligation.verdict is Verdict.FALSE
                    else "proof-unknown"
                ),
                verdict=obligation.verdict.value,
                message=obligation.description,
                rule=obligation.rule,
                location=obligation.location,
                proof_kind=obligation.kind,
                formula=str(
                    obligation.formula
                    if obligation.proof_formula is None
                    else obligation.proof_formula
                ),
                backend_detail=obligation.detail,
            )
        )
    return tuple(details)


def _primary_error_detail(
    details: tuple[HCSPErrorDetail, ...],
    category: str,
    fallback: str,
) -> HCSPErrorDetail:
    r"""Choose primary evidence consistent with the overall failure category."""

    for detail in details:
        if detail.category == category:
            return detail
    if details:
        return details[0]
    return HCSPErrorDetail(category, "false", fallback)


def _error_phase(category: str) -> str:
    r"""Group error categories by processing phase."""

    if category == "environment":
        return "environment"
    if category.startswith("proof-"):
        return "proof"
    if category == "type-mismatch":
        return "type-matching"
    return "rule-derivation"


def _error_category_explanation(category: str) -> str:
    r"""Explain each stable error category in English."""

    return {
        "environment": 'Gamma, Theta, shared parameters, or the path condition are not well-formed',
        "derivation": 'Table 2 rules cannot derive a complete type for the current Process',
        "type-mismatch": 'The supplied Type structure does not match the rule conclusion',
        "rule-application": 'The current Process or runtime context violates a static rule premise',
        "proof-failed": 'A required proof formula was disproved or a counterexample was found',
        "proof-unknown": 'A required proof formula remains unresolved by a trusted prover',
    }.get(category, 'No trusted conclusion was obtained')


def _render_primary_detail(detail: HCSPErrorDetail) -> tuple[str, ...]:
    r"""Render the primary rule, location, and prover evidence for result output."""

    lines = [f"Reason     : {detail.message}"]
    if detail.rule:
        lines.append(f"Related rule : {detail.rule}")
    if detail.location:
        lines.append(f"Judgment location : {detail.location}")
    if detail.proof_kind:
        lines.append(f"Proof kind : {detail.proof_kind.upper()}")
    if detail.backend_detail:
        lines.append(f"Prover detail: {detail.backend_detail}")
    return tuple(lines)


def _detail_reason(detail: HCSPErrorDetail) -> str:
    r"""Include prover evidence in the legacy-compatible reason field."""

    if detail.backend_detail:
        return f"{detail.message}: {detail.backend_detail}"
    return detail.message


def _format_partial_types(report: TypeConstructionReport) -> str:
    r"""Display component types completed before derivation stopped."""

    if not report.constructed_component_types:
        return "(none)"
    return ", ".join(
        f"K{index}="
        + (
            format_type_source(component_type)
            if component_type is not None
            else "(none)"
        )
        for index, component_type in enumerate(
            report.constructed_component_types,
            start=1,
        )
    )


def _format_partial_progress(
    report: TypeConstructionReport,
) -> tuple[str, ...]:
    r"""Summarize partial progress and the stopping point."""

    proved = sum(
        item.verdict is Verdict.TRUE for item in report.obligations
    )
    failed = sum(
        item.verdict is Verdict.FALSE for item in report.obligations
    )
    unknown = sum(
        item.verdict is Verdict.UNKNOWN for item in report.obligations
    )
    lines = [
        f"Partial types : {_format_partial_types(report)}",
        f"Derivation steps : {len(report.steps)} steps executed",
        'Proof obligations : '
        f"true={proved}, false={failed}, unknown={unknown}",
    ]
    if report.steps:
        last_step = max(report.steps, key=lambda item: item.number)
        lines.append(
            'Stop location : '
            f"{last_step.rule} @ {last_step.location or '-'}"
        )
    return tuple(lines)


def _format_type_result(
    report: TypeConstructionReport,
    *,
    failure_kind: TypeConstructionErrorKind | None = None,
    primary_detail: HCSPErrorDetail | None = None,
) -> str:
    r"""Render construction, proof, and trust status from an internal report."""

    constructed_type = report.constructed_type
    proof_counts = {
        verdict: sum(
            obligation.verdict is verdict
            for obligation in report.obligations
        )
        for verdict in Verdict
    }
    proof_summary = (
        f"true={proof_counts[Verdict.TRUE]}, "
        f"false={proof_counts[Verdict.FALSE]}, "
        f"unknown={proof_counts[Verdict.UNKNOWN]}"
    )
    is_trusted = (
        report.verdict is Verdict.TRUE and constructed_type is not None
    )
    is_untrusted = (
        report.verdict is Verdict.UNKNOWN and constructed_type is not None
    )
    construction_status = 'complete' if constructed_type is not None else 'incomplete'
    if is_trusted:
        proof_status = 'all passed'
        trust_status = 'trusted (verified)'
    elif is_untrusted:
        proof_status = 'unverified obligations remain'
        trust_status = 'untrusted (unverified)'
    elif constructed_type is not None:
        proof_status = 'failed obligations remain'
        trust_status = 'untrusted (failed obligations)'
    else:
        proof_status = (
            'failed'
            if report.verdict is Verdict.FALSE
            else 'unresolved premises remain'
        )
        trust_status = 'not applicable (no complete type)'
    lines = [
        '=== HCSP type construction result ===',
        f"Verdict : {report.verdict.value}",
        f"Type construction : {construction_status}",
        'Type AST generation : ' + ('success' if constructed_type is not None else 'failed'),
        f"Proof status : {proof_status}",
        f"Type trust : {trust_status}",
    ]
    if failure_kind is not None:
        lines.extend(
            (
                f"Error kind : {failure_kind.value}",
                f"Error phase : {_error_phase(failure_kind.value)}",
                'Kind explanation : '
                + _error_category_explanation(failure_kind.value),
            )
        )
    if is_untrusted:
        lines.extend(
            (
                'Complete candidate Type source : '
                + format_type_source(constructed_type),
                'Outcome : the candidate is available only as error.untrusted_type; it is not returned as a trusted Type AST',
                f"Proof obligations : {proof_summary}",
            )
        )
    elif constructed_type is not None and report.verdict is Verdict.TRUE:
        lines.append('Type source : ' + format_type_source(constructed_type))
    elif constructed_type is not None:
        lines.extend(
            (
                'Complete candidate Type source : '
                + format_type_source(constructed_type),
                'Outcome : the candidate is not returned as a trusted Type AST',
            )
        )
    else:
        lines.append('Type source : (none)')
        lines.extend(_format_partial_progress(report))
    if primary_detail is not None:
        lines.extend(_render_primary_detail(primary_detail))
    return "\n".join(lines)


def _format_input_error_result(
    error: HCSPInputError,
    *,
    operation: str,
) -> str:
    r"""Render a compact input error with the operation and machine-readable category."""

    return "\n".join(
        (
            f"=== HCSP {operation} input error ===",
            "Verdict : input-error",
            'Result     : failed',
            f"Error kind : input-{error.phase}",
            'Error phase : input',
            f"Reason     : {error.message}",
            f"Location   : {error.source_name}:{error.line}:{error.column}",
            f"{operation} progress : not started (input parsing stopped)",
        )
    )


def _format_input_error_full(
    source: Any,
    source_name: str,
    error: HCSPInputError,
    *,
    operation: str,
) -> str:
    r"""Show the input location and explain that backend processing never started."""

    return "\n".join(
        (
            f"=== HCSP {operation} full error log ===",
            f"Source : {source_name}",
            "Verdict : input-error",
            f"Error kind : input-{error.phase}",
            'Error phase : input',
            "",
            '--- Original user input ---',
            source if isinstance(source, str) else repr(source),
            "",
            '--- Input parsing failed ---',
            error.format_diagnostic(),
            "",
            f"--- {operation} ---",
            'Not started: input did not form valid internal ASTs and environments.',
        )
    )


class HCSPTypeConstructionError(RuntimeError):
    r"""Construction failed to produce a trusted Type AST."""

    def __init__(
        self,
        context: _ProgramContext,
        report: TypeConstructionReport,
    ) -> None:
        r"""Store structured failure fields and private evidence for full output."""

        self.source_name = context.source_name
        self.verdict = report.verdict.value
        self.partial_types = report.constructed_component_types
        self.kind = classify_construction_error(report)
        self.phase = _error_phase(self.kind.value)
        self.details = _report_error_details(report)
        self.primary_detail = _primary_error_detail(
            self.details,
            self.kind.value,
            _first_report_reason(report),
        )
        self.reason = _detail_reason(self.primary_detail)
        self.rule = self.primary_detail.rule
        self.location = self.primary_detail.location
        self._context = context
        self._report = report
        super().__init__(self.format_result())

    def format_result(self) -> str:
        r"""Summarize failure, partial types, and derivation progress."""

        return _format_type_result(
            self._report,
            failure_kind=self.kind,
            primary_detail=self.primary_detail,
        )

    def format_full(self) -> str:
        r"""Display the input and construction evidence up to the stopping point."""

        result_lines = self.format_result().splitlines()
        return "\n\n".join(
            (
                self._context.format_full(),
                self._report.format_detailed(),
                '=== Type construction failure summary ===\n'
                + "\n".join(result_lines[1:]),
            )
        )


class HCSPUntrustedTypeConstructionError(HCSPTypeConstructionError):
    r"""Construction produced a complete candidate with unresolved proof obligations."""

    def __init__(
        self,
        context: _ProgramContext,
        report: TypeConstructionReport,
    ) -> None:
        r"""Keep the complete unverified candidate and its audit evidence."""

        if report.verdict is not Verdict.UNKNOWN:
            raise ValueError(
                "HCSPUntrustedTypeConstructionError requires an unknown verdict"
            )
        if report.constructed_type is None:
            raise ValueError(
                "HCSPUntrustedTypeConstructionError requires a complete "
                "constructed type"
            )
        self.untrusted_type: TypeAST = report.constructed_type
        super().__init__(context, report)


class HCSPTypeCheckingError(RuntimeError):
    r"""Table 2 rules or proofs failed to validate the supplied Type."""

    def __init__(
        self,
        source_name: str,
        report: object,
        source_text: str = "",
    ) -> None:
        r"""Store structured checking status and the internal audit report."""

        self.source_name = source_name
        self._source_text = source_text
        self._report = report
        self.verdict = report.verdict.value
        self.expected_type = report.expected_type
        self.kind = classify_checking_error(report)
        self.phase = _error_phase(self.kind.value)
        self.details = _report_error_details(
            report.evidence,
            mismatch=report.mismatch,
            rule_category="rule-application",
        )
        self.primary_detail = _primary_error_detail(
            self.details,
            self.kind.value,
            report.mismatch
            or report.failure_reason
            or _first_report_reason(report.evidence),
        )
        self.reason = _detail_reason(self.primary_detail)
        self.rule = self.primary_detail.rule
        self.location = self.primary_detail.location
        self.type_mismatch_detected = bool(report.mismatch)
        self.type_structure_matched: bool | None = (
            False
            if report.mismatch
            else True
            if report.evidence.constructed_type is not None
            else None
        )
        super().__init__(self.format_result())

    def format_result(self) -> str:
        r"""Display the supplied Type and its primary checking failure."""

        if self.kind is TypeCheckingErrorKind.ENVIRONMENT:
            structure_status = 'not started (invalid environment)'
        elif self.kind is TypeCheckingErrorKind.TYPE_MISMATCH:
            structure_status = 'mismatch'
        else:
            structure_status = 'checked against the rules; final result failed'
        lines = [
            '=== HCSP type checking result ===',
            f"Verdict : {self.verdict}",
            'Check result : failed',
            f"Error kind : {self.kind.value}",
            f"Error phase : {self.phase}",
            'Kind explanation : ' + _error_category_explanation(self.kind.value),
            f"Type structure : {structure_status}",
            'Supplied Type source : ' + format_type_source(self.expected_type),
        ]
        lines.extend(_render_primary_detail(self.primary_detail))
        return "\n".join(lines)

    def format_full(self) -> str:
        r"""Display rule matching and proof obligations for the supplied Type."""

        sections = [
            '=== HCSP type checking full log ===\n'
            f"Source : {self.source_name}",
        ]
        if self._source_text:
            sections.append('--- Original user input ---\n' + self._source_text)
        result_lines = self.format_result().splitlines()
        sections.extend(
            (
                self._report.format_detailed(),
                '=== Type checking failure summary ===\n'
                + "\n".join(result_lines[1:]),
            )
        )
        return "\n\n".join(sections)


class HCSPTypeTransitionGraphError(RuntimeError):
    r"""A complete graph could not be built from the Type AST."""

    def __init__(
        self,
        kind: TypeTransitionGraphErrorKind,
        reason: str,
        type_ast: object,
        *,
        limit_name: str = "",
        limit: int | None = None,
        option_name: str = "",
        option_value: object = None,
    ) -> None:
        r"""Store structured error fields and the input Type text."""

        if not isinstance(kind, TypeTransitionGraphErrorKind):
            raise TypeError("graph error kind must be TypeTransitionGraphErrorKind")
        self.verdict = "error"
        self.kind = kind
        self.phase = {
            TypeTransitionGraphErrorKind.INVALID_TYPE: "input-validation",
            TypeTransitionGraphErrorKind.INVALID_LIMIT: "option-validation",
            TypeTransitionGraphErrorKind.NORMALIZATION: "normalization",
            TypeTransitionGraphErrorKind.SIZE_LIMIT: "graph-construction",
        }[kind]
        self.reason = reason
        self.limit_name = limit_name
        self.limit = limit
        self.option_name = option_name
        self.option_value = option_value
        self.details = (
            HCSPErrorDetail(
                category=kind.value,
                verdict="error",
                message=reason,
                rule=(
                    "critical-deadline-graph"
                    if kind is TypeTransitionGraphErrorKind.SIZE_LIMIT
                    else "type-normalization"
                    if kind is TypeTransitionGraphErrorKind.NORMALIZATION
                    else "public-interface"
                ),
                location=(
                    option_name
                    if kind is TypeTransitionGraphErrorKind.INVALID_LIMIT
                    else "Type AST root"
                ),
            ),
        )
        self.primary_detail = self.details[0]
        self._input_type = (
            format_type_source(type_ast)
            if isinstance(type_ast, ConfigurationType)
            else repr(type_ast)
        )
        super().__init__(self.format_result())

    def format_result(self) -> str:
        r"""Summarize the category, phase, reason, and optional graph limit."""

        explanations = {
            TypeTransitionGraphErrorKind.INVALID_TYPE: (
                'The input is not a supported Type AST configuration root'
            ),
            TypeTransitionGraphErrorKind.INVALID_LIMIT: (
                'State and transition limits must be strictly positive integers or None'
            ),
            TypeTransitionGraphErrorKind.NORMALIZATION: (
                'The Type AST cannot be converted to a closed equi-recursive normalized state'
            ),
            TypeTransitionGraphErrorKind.SIZE_LIMIT: (
                'The complete reachable graph exceeds the requested size limit'
            ),
        }
        lines = [
            '=== HCSP Type transition graph result ===',
            "Verdict : error",
            'Graph construction : failed',
            f"Error kind : {self.kind.value}",
            f"Error phase : {self.phase}",
            f"Kind explanation : {explanations[self.kind]}",
            f"Reason     : {self.reason}",
        ]
        if self.limit_name:
            lines.append(f"Size limit : {self.limit_name}={self.limit}")
        if self.option_name:
            lines.append(
                f"Invalid option : {self.option_name}={self.option_value!r}"
            )
        lines.append('Return value : none (no partial transition graph is returned)')
        return "\n".join(lines)

    def format_full(self) -> str:
        r"""Display the input Type, processing phases, and failure summary."""

        if self.kind is TypeTransitionGraphErrorKind.INVALID_TYPE:
            stages = (
                'Type root validation : failed',
                'Type normalization : not started',
                'Graph traversal : not started',
            )
        elif self.kind is TypeTransitionGraphErrorKind.INVALID_LIMIT:
            stages = (
                'Type root validation : success',
                'Option validation : failed',
                'Type normalization : not started',
                'Graph traversal : not started',
            )
        elif self.kind is TypeTransitionGraphErrorKind.NORMALIZATION:
            stages = (
                'Type root validation : success',
                'Option validation : success',
                'Type normalization : failed',
                'Graph traversal : not started',
            )
        else:
            stages = (
                'Type root validation : success',
                'Option validation : success',
                'Type normalization : success',
                'Graph traversal : failed (size limit reached)',
            )
        result_lines = self.format_result().splitlines()
        return "\n\n".join(
            (
                '=== HCSP Type transition graph full error log ===\n\n'.join(stages),
                '--- Input Type ---\n' + self._input_type,
                '=== Graph construction failure summary ===\n'
                + "\n".join(result_lines[1:]),
            )
        )


def _write_graph_error(
    error: HCSPTypeTransitionGraphError,
    mode: OutputMode,
    stream: TextIO | None,
) -> None:
    r"""Write a graph error once according to the selected output mode."""

    if mode is OutputMode.NONE:
        return
    _write_output(
        error.format_full()
        if mode is OutputMode.FULL
        else error.format_result(),
        stream,
    )


class HCSPTypeLockAnalysisError(RuntimeError):
    r"""Property analysis requires a valid, complete reachable Type graph."""

    def __init__(
        self,
        kind: TypeLockAnalysisErrorKind,
        reason: str,
        graph: object,
    ) -> None:
        r"""Store error classification and graph size information."""

        if not isinstance(kind, TypeLockAnalysisErrorKind):
            raise TypeError("lock-analysis error kind must be TypeLockAnalysisErrorKind")
        self.verdict = "error"
        self.kind = kind
        self.phase = (
            "input-validation"
            if kind is TypeLockAnalysisErrorKind.INVALID_GRAPH
            else "reachability-validation"
        )
        self.reason = reason
        self.state_count = len(graph.states) if isinstance(graph, TypeTransitionGraph) else None
        self.transition_count = (
            len(graph.transitions) if isinstance(graph, TypeTransitionGraph) else None
        )
        self.details = (
            HCSPErrorDetail(
                category=kind.value,
                verdict="error",
                message=reason,
                rule="lock-freedom-graph-analysis",
                location="TypeTransitionGraph root",
            ),
        )
        self.primary_detail = self.details[0]
        super().__init__(self.format_result())

    def format_result(self) -> str:
        r"""Explain the failure without returning partial property conclusions."""

        lines = [
            '=== Type behavioral correctness result ===',
            "Verdict : error",
            'Property analysis : failed',
            f"Error kind : {self.kind.value}",
            f"Error phase : {self.phase}",
            f"Reason     : {self.reason}",
        ]
        if self.state_count is not None:
            lines.extend(
                (
                    f"Graph state count : {self.state_count}",
                    f"Graph transition count : {self.transition_count}",
                )
            )
        lines.append('Return value : none (no partial property result is returned)')
        return "\n".join(lines)

    def format_full(self) -> str:
        r"""Display validation phases and failure evidence without repeating the graph."""

        reachability = (
            'not started'
            if self.kind is TypeLockAnalysisErrorKind.INVALID_GRAPH
            else 'failed'
        )
        return "\n\n".join(
            (
                '=== Type behavioral correctness full error log ===\n'
                f"Graph object validation : {'failed' if self.kind is TypeLockAnalysisErrorKind.INVALID_GRAPH else 'success'}\n"
                f"Reachable closure validation : {reachability}\n"
                'Deadlock search : not started\n'
                'Livelock search : not started\n'
                'Bottom error search : not started',
                '=== Behavioral correctness failure summary ===\n'
                + "\n".join(self.format_result().splitlines()[1:]),
            )
        )


def _write_lock_analysis_error(
    error: HCSPTypeLockAnalysisError,
    mode: OutputMode,
    stream: TextIO | None,
) -> None:
    r"""Write a lock-analysis error once according to the output mode."""

    if mode is OutputMode.NONE:
        return
    _write_output(
        error.format_full() if mode is OutputMode.FULL else error.format_result(),
        stream,
    )


def _normalize_initial_states(
    value: Mapping[str, Any] | Sequence[Mapping[str, Any]] | None,
    component_count: int,
) -> tuple[Mapping[str, Any], ...]:
    r"""Match partial initial states to top-level process components in source order."""

    if value is None:
        return tuple({} for _ in range(component_count))
    if isinstance(value, Mapping):
        if component_count != 1:
            raise ValueError(
                "parallel HCSP input requires one initial-state mapping per "
                "top-level process component"
            )
        return (dict(value),)
    if isinstance(value, (str, bytes)) or not isinstance(value, Sequence):
        raise TypeError(
            "initial_states must be a mapping, a sequence of mappings, or None"
        )
    states = tuple(value)
    if len(states) != component_count:
        raise ValueError(
            "initial_states count must match the number of top-level process "
            f"components ({component_count})"
        )
    if any(not isinstance(state, Mapping) for state in states):
        raise TypeError("every initial state must be a mapping")
    return tuple(dict(state) for state in states)


def _normalize_path_condition(value: str | bool, source_name: str) -> Any:
    r"""Parse a bool or expression string as the initial path condition."""

    if isinstance(value, str):
        return parse_expression(
            value,
            source_name=f"{source_name}:path_condition",
        )
    if isinstance(value, bool):
        return value
    raise TypeError("path_condition must be a bool or expression string")


def _build_configurations(
    context: _ProgramContext,
    initial_states: Mapping[str, Any]
    | Sequence[Mapping[str, Any]]
    | None,
) -> tuple[Configuration, ...]:
    r"""Create one configuration for each top-level process component."""

    states = _normalize_initial_states(
        initial_states,
        len(context.process_components),
    )
    return tuple(
        Configuration(state, component, name=f"K{index}")
        for index, (state, component) in enumerate(
            zip(states, context.process_components),
            start=1,
        )
    )


def construct_hcsp_type(
    source: str,
    *,
    source_name: str = "<input>",
    initial_states: Mapping[str, Any]
    | Sequence[Mapping[str, Any]]
    | None = None,
    path_condition: str | bool = True,
    output: OutputMode | str = OutputMode.NONE,
    stream: TextIO | None = None,
    z3_timeout_ms: int = 5_000,
    keymaerax_timeout_seconds: float | None = None,
) -> TypeAST:
    r"""Construct and prove a behavioral Type AST from complete HCSP input.

    Args:
        source: Ordered gamma, optional parameters, theta, and process sections.
        source_name: Label used in source diagnostics.
        initial_states: Partial Gamma assignments; for parallel processes, pass
            one mapping per component in source order.
        path_condition: Initial path predicate as a bool or expression string.
        output: Presentation mode: none, result, or full.
        stream: Destination for output; None selects standard output.
        z3_timeout_ms: Timeout in milliseconds for each Z3 query.
        keymaerax_timeout_seconds: External proof timeout override in seconds.

    Returns:
        The constructed Type AST, only after all required proofs are verified.

    Raises:
        HCSPInputError: Invalid source or path-condition syntax.
        HCSPUntrustedTypeConstructionError: A complete candidate exists but
            proofs remain unknown; inspect the exception's untrusted_type.
        HCSPTypeConstructionError: Invalid context or failed derivation/proof.
        TypeError, ValueError: Invalid Python argument shapes or output mode.
    """

    mode = _normalize_output_mode(output)
    try:
        context = _parse_program(source, source_name)
    except HCSPInputError as error:
        if mode is not OutputMode.NONE:
            rendered = (
                _format_input_error_full(
                    source,
                    source_name,
                    error,
                    operation='type construction',
                )
                if mode is OutputMode.FULL
                else _format_input_error_result(
                    error,
                    operation='type construction',
                )
            )
            _write_output(rendered, stream)
        raise

    try:
        normalized_path = _normalize_path_condition(
            path_condition,
            context.source_name,
        )
    except HCSPInputError as error:
        if mode is not OutputMode.NONE:
            rendered = (
                "\n\n".join(
                    (
                        context.format_full(),
                        "\n".join(
                            (
                                '=== Path condition parsing failed ===',
                                "Verdict : input-error",
                                f"Error kind : {error.kind}",
                                'Error phase : input',
                                error.format_diagnostic(),
                                "",
                                'Type construction did not start.',
                            )
                        ),
                    )
                )
                if mode is OutputMode.FULL
                else _format_input_error_result(
                    error,
                    operation='type construction',
                )
            )
            _write_output(rendered, stream)
        raise

    configurations = _build_configurations(context, initial_states)
    keymaerax_config: KeYmaeraXConfig | None = None
    if keymaerax_timeout_seconds is not None:
        keymaerax_config = replace(
            KeYmaeraXConfig.from_environment(),
            timeout_seconds=keymaerax_timeout_seconds,
        )
    report = construct_type(
        gamma=context.gamma,
        theta=context.theta,
        configurations=configurations,
        path_condition=normalized_path,
        parameters=context.parameters,
        keymaerax_config=keymaerax_config,
        z3_timeout_ms=z3_timeout_ms,
    )

    if report.verdict is Verdict.TRUE and report.constructed_type is None:
        raise RuntimeError(
            "internal TypeConstructor invariant violated: a true verdict did not "
            "produce a Type AST"
        )

    if report.verdict is Verdict.UNKNOWN and report.constructed_type is not None:
        failure: HCSPTypeConstructionError | None = (
            HCSPUntrustedTypeConstructionError(
                context,
                report,
            )
        )
    elif report.verdict is not Verdict.TRUE:
        failure = HCSPTypeConstructionError(context, report)
    else:
        failure = None
    if mode is not OutputMode.NONE:
        if failure is not None:
            rendered = (
                failure.format_full()
                if mode is OutputMode.FULL
                else failure.format_result()
            )
        else:
            rendered = (
                "\n\n".join((context.format_full(), report.format_detailed()))
                if mode is OutputMode.FULL
                else _format_type_result(report)
            )
        _write_output(rendered, stream)

    if failure is not None:
        raise failure
    if report.constructed_type is None:
        raise RuntimeError(
            "internal TypeConstructor invariant violated: successful "
            "construction lost its Type AST"
        )
    return report.constructed_type


def check_hcsp_type(
    source: str,
    *,
    source_name: str = "<input>",
    initial_states: Mapping[str, Any]
    | Sequence[Mapping[str, Any]]
    | None = None,
    path_condition: str | bool = True,
    output: OutputMode | str = OutputMode.NONE,
    stream: TextIO | None = None,
    z3_timeout_ms: int = 5_000,
    keymaerax_timeout_seconds: float | None = None,
) -> TypeAST:
    r"""Validate a supplied Type against the HCSP Process in the same input.

    source must include a final type section. The checker follows its branch
    grouping and order as rule conclusions rather than comparing against a
    separately constructed Type. Other arguments have the same meaning as in
    construct_hcsp_type.

    Returns:
        The supplied Type AST after all structural checks and proofs succeed.

    Raises:
        HCSPInputError: Invalid source or path-condition syntax.
        HCSPTypeCheckingError: Invalid context, Type mismatch, or failed or
            unknown proof. Unknown proofs never count as successful checking.
        TypeError, ValueError: Invalid Python argument shapes or output mode.
    """

    mode = _normalize_output_mode(output)
    try:
        parsed = parse_typechecking_source(source, source_name=source_name)
    except HCSPInputError as error:
        if mode is not OutputMode.NONE:
            _write_output(
                (
                    _format_input_error_full(
                        source,
                        source_name,
                        error,
                        operation='type checking',
                    )
                    if mode is OutputMode.FULL
                    else _format_input_error_result(
                        error,
                        operation='type checking',
                    )
                ),
                stream,
            )
        raise
    components = parsed.program.process_components
    try:
        normalized_path = _normalize_path_condition(path_condition, source_name)
    except HCSPInputError as error:
        if mode is not OutputMode.NONE:
            _write_output(
                (
                    _format_input_error_full(
                        source,
                        source_name,
                        error,
                        operation='type checking',
                    )
                    if mode is OutputMode.FULL
                    else _format_input_error_result(
                        error,
                        operation='type checking',
                    )
                ),
                stream,
            )
        raise
    states = _normalize_initial_states(initial_states, len(components))
    configurations = tuple(
        Configuration(state, component, name=f"K{index}")
        for index, (state, component) in enumerate(zip(states, components), 1)
    )
    keymaerax_config = None
    if keymaerax_timeout_seconds is not None:
        keymaerax_config = replace(
            KeYmaeraXConfig.from_environment(),
            timeout_seconds=keymaerax_timeout_seconds,
        )
    report = TypeChecker(
        keymaerax_config=keymaerax_config,
        z3_timeout_ms=z3_timeout_ms,
    ).check(
        TypeCheckingRequest(
            parsed.program.gamma,
            parsed.program.theta,
            configurations,
            parsed.expected_type,
            path_condition=normalized_path,
            parameters=parsed.program.parameters,
        )
    )
    if report.verdict is Verdict.TRUE:
        if mode is not OutputMode.NONE:
            result_text = "\n".join(
                (
                    '=== HCSP type checking result ===',
                    "Verdict : true",
                    'Type structure : matches all rule conclusions',
                    'Proof status : all premises verified',
                    'Type source : '
                    + format_type_source(parsed.expected_type),
                )
            )
            _write_output(
                (
                    "\n\n".join(
                        (
                            '=== HCSP type checking full log ===\n'
                            f"Source : {source_name}\n\n"
                            '--- Original user input ---\n'
                            f"{source}",
                            report.format_detailed(),
                        )
                    )
                    if mode is OutputMode.FULL
                    else result_text
                ),
                stream,
            )
        return parsed.expected_type
    error = HCSPTypeCheckingError(source_name, report, source)
    if mode is not OutputMode.NONE:
        _write_output(
            error.format_full() if mode is OutputMode.FULL else error.format_result(),
            stream,
        )
    raise error


def build_type_transition_graph(
    type_ast: TypeAST,
    *,
    max_states: int | None = None,
    max_transitions: int | None = None,
    output: OutputMode | str = OutputMode.NONE,
    stream: TextIO | None = None,
) -> TypeTransitionGraph:
    r"""Build the complete Table 3 graph using critical-deadline time reduction.

    States use equi-recursive regular-tree identity. Edges preserve distinct
    rule derivations even when they share source, label, and target.

    Args:
        type_ast: A formal TypeAST returned by construction or checking.
        max_states: Positive state-count limit, or None for no limit.
        max_transitions: Positive transition-count limit, or None for no limit.
        output: Presentation mode: none, result, or full.
        stream: Destination for output; None selects standard output.

    Returns:
        The complete reachable graph; a size limit never returns a partial graph.

    Raises:
        HCSPTypeTransitionGraphError: Invalid type/limit, normalization failure,
            or a graph exceeding the requested limits.
        ValueError: Invalid output mode.
    """

    mode = _normalize_output_mode(output)
    if not isinstance(type_ast, ConfigurationType):
        error = HCSPTypeTransitionGraphError(
            TypeTransitionGraphErrorKind.INVALID_TYPE,
            'type_ast must be a TypeAST/ConfigurationType',
            type_ast,
        )
        _write_graph_error(error, mode, stream)
        raise error

    for limit_name, limit in (
        ("max_states", max_states),
        ("max_transitions", max_transitions),
    ):
        if (
            limit is not None
            and (
                isinstance(limit, bool)
                or not isinstance(limit, int)
                or limit <= 0
            )
        ):
            error = HCSPTypeTransitionGraphError(
                TypeTransitionGraphErrorKind.INVALID_LIMIT,
                f"{limit_name} must be a strictly positive integer or None",
                type_ast,
                option_name=limit_name,
                option_value=limit,
            )
            _write_graph_error(error, mode, stream)
            raise error

    try:
        graph = _build_type_transition_graph(
            type_ast,
            max_states=max_states,
            max_transitions=max_transitions,
        )
    except TypeNormalizationError as cause:
        error = HCSPTypeTransitionGraphError(
            TypeTransitionGraphErrorKind.NORMALIZATION,
            str(cause),
            type_ast,
        )
        _write_graph_error(error, mode, stream)
        raise error from cause
    except TypeTransitionGraphSizeError as cause:
        error = HCSPTypeTransitionGraphError(
            TypeTransitionGraphErrorKind.SIZE_LIMIT,
            'The complete transition graph exceeds the allowed size limit',
            type_ast,
            limit_name=cause.limit_name,
            limit=cause.limit,
        )
        _write_graph_error(error, mode, stream)
        raise error from cause
    if mode is OutputMode.RESULT:
        lines = [
            'Table 3 transition graph result',
            f"Initial state : S{graph.initial_state}",
            f"State count : {len(graph.states)}",
            f"Transition count : {len(graph.transitions)}",
        ]
        initial = graph.states[graph.initial_state].type_ast
        lines.append('Initial normalized Type :')
        lines.extend(
            "    " + line
            for line in _format_normalized_type_ast(initial).splitlines()
        )
        _write_output("\n".join(lines), stream)
    elif mode is OutputMode.FULL:
        _write_output(_format_type_transition_graph(graph), stream)
    return graph


def analyze_type_lock_freedom(
    graph: TypeTransitionGraph,
    *,
    output: OutputMode | str = OutputMode.NONE,
    stream: TextIO | None = None,
) -> LockFreedomReport:
    r"""Analyze lock freedom, reachable Bottom errors, and behavioral correctness.

    graph must be a complete reachable graph from build_type_transition_graph.
    Deadlock requires an infinite-time edge with a nonempty ready set; livelock
    requires a reachable silent cycle. Reachable Bottom termination is checked
    separately. behavior_correct is the conjunction of lock_free and error_free.
    The analysis runs in O(V + E) time.

    output selects none, result, or full; stream defaults to standard output.

    Returns:
        A LockFreedomReport with counterexample witnesses for failed properties.
        A failed property is a normal result, not an exception.

    Raises:
        HCSPTypeLockAnalysisError: Invalid graph or incomplete reachable closure.
        ValueError: Invalid output mode.
    """

    mode = _normalize_output_mode(output)
    if not isinstance(graph, TypeTransitionGraph):
        error = HCSPTypeLockAnalysisError(
            TypeLockAnalysisErrorKind.INVALID_GRAPH,
            'graph must be a TypeTransitionGraph returned by build_type_transition_graph',
            graph,
        )
        _write_lock_analysis_error(error, mode, stream)
        raise error
    try:
        report = _analyze_lock_freedom(graph)
    except IncompleteTransitionGraphError as cause:
        error = HCSPTypeLockAnalysisError(
            TypeLockAnalysisErrorKind.INCOMPLETE_GRAPH,
            str(cause),
            graph,
        )
        _write_lock_analysis_error(error, mode, stream)
        raise error from cause

    if mode is OutputMode.RESULT:
        _write_output(_format_lock_freedom_result(report), stream)
    elif mode is OutputMode.FULL:
        _write_output(_format_lock_freedom_full(report, graph), stream)
    return report


__all__ = [
    "HCSPErrorDetail",
    "HCSPInputError",
    "HCSPTypeConstructionError",
    "HCSPTypeCheckingError",
    "HCSPTypeTransitionGraphError",
    "HCSPTypeLockAnalysisError",
    "HCSPUntrustedTypeConstructionError",
    "OutputMode",
    "TypeAST",
    "TypeCheckingErrorKind",
    "TypeConstructionErrorKind",
    "TypeTransitionGraphErrorKind",
    "TypeLockAnalysisErrorKind",
    "TypeTransitionGraph",
    "LockFreedomReport",
    "analyze_type_lock_freedom",
    "build_type_transition_graph",
    "construct_hcsp_type",
    "check_hcsp_type",
]
