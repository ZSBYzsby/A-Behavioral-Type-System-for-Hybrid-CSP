r"""Failure classification for TypeChecker."""

from __future__ import annotations

from enum import Enum

from ..common.model import Verdict
from .model import TypeCheckingReport


class TypeCheckingErrorKind(str, Enum):
    r"""Stable machine-readable TypeChecker error categories."""

    ENVIRONMENT = "environment"
    TYPE_MISMATCH = "type-mismatch"
    RULE_APPLICATION = "rule-application"
    PROOF_FAILED = "proof-failed"
    PROOF_UNKNOWN = "proof-unknown"


def classify_checking_error(
    report: TypeCheckingReport,
) -> TypeCheckingErrorKind:
    r"""Choose the primary checking failure phase from the final report."""

    if report.mismatch:
        return TypeCheckingErrorKind.TYPE_MISMATCH
    if any(
        item.verdict is Verdict.FALSE
        and item.rule in {"environment", "parameters"}
        for item in report.evidence.diagnostics
    ):
        return TypeCheckingErrorKind.ENVIRONMENT
    if report.verdict is Verdict.UNKNOWN:
        return TypeCheckingErrorKind.PROOF_UNKNOWN
    if any(
        item.active and item.verdict is Verdict.FALSE
        for item in report.evidence.obligations
    ):
        return TypeCheckingErrorKind.PROOF_FAILED
    return TypeCheckingErrorKind.RULE_APPLICATION


__all__ = ["TypeCheckingErrorKind", "classify_checking_error"]
