r"""Failure classification for TypeConstructor."""

from __future__ import annotations

from enum import Enum

from ..common.model import Verdict
from .model import TypeConstructionReport


class TypeConstructionErrorKind(str, Enum):
    r"""Stable machine-readable construction error categories."""

    ENVIRONMENT = "environment"
    DERIVATION = "derivation"
    PROOF_FAILED = "proof-failed"
    PROOF_UNKNOWN = "proof-unknown"


def classify_construction_error(
    report: TypeConstructionReport,
) -> TypeConstructionErrorKind:
    r"""Choose the primary construction failure phase from the report."""

    if any(
        item.verdict is Verdict.FALSE
        and item.rule in {"environment", "parameters"}
        for item in report.diagnostics
    ):
        return TypeConstructionErrorKind.ENVIRONMENT
    if report.verdict is Verdict.UNKNOWN:
        return TypeConstructionErrorKind.PROOF_UNKNOWN
    if any(
        item.active and item.verdict is Verdict.FALSE
        for item in report.obligations
    ):
        return TypeConstructionErrorKind.PROOF_FAILED
    return TypeConstructionErrorKind.DERIVATION


__all__ = ["TypeConstructionErrorKind", "classify_construction_error"]
