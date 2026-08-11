"""TypeChecker 专属的失败分类规则。

Checker 需要额外区分用户 Type 结构不匹配和普通规则静态错误；这两个类别在
TypeConstructor 中没有对应物，因此不能复用 Constructor 的分类函数。
"""

from __future__ import annotations

from enum import Enum

from ..common.model import Verdict
from .model import TypeCheckingReport


class TypeCheckingErrorKind(str, Enum):
    """TypeChecker 失败的稳定机器可读分类。"""

    ENVIRONMENT = "environment"
    TYPE_MISMATCH = "type-mismatch"
    RULE_APPLICATION = "rule-application"
    PROOF_FAILED = "proof-failed"
    PROOF_UNKNOWN = "proof-unknown"


def classify_checking_error(
    report: TypeCheckingReport,
) -> TypeCheckingErrorKind:
    """根据最终报告判定 Checker 的首要失败阶段。"""

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
