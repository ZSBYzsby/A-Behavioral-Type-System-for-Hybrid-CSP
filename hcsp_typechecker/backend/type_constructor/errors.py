"""TypeConstructor 专属的失败分类规则。

本模块只判断“构造为何没有交付可信 Type”：环境错误、规则推导错误、已否证
证明或未决证明。展示文本和公共异常由最外层 API 负责，避免后端直接打印。
"""

from __future__ import annotations

from enum import Enum

from ..common.model import Verdict
from .model import TypeConstructionReport


class TypeConstructionErrorKind(str, Enum):
    """TypeConstructor 失败的稳定机器可读分类。"""

    ENVIRONMENT = "environment"
    DERIVATION = "derivation"
    PROOF_FAILED = "proof-failed"
    PROOF_UNKNOWN = "proof-unknown"


def classify_construction_error(
    report: TypeConstructionReport,
) -> TypeConstructionErrorKind:
    """根据最终报告判定 Constructor 的首要失败阶段。"""

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
