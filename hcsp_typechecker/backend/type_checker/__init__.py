"""TypeChecker 的类型定向递归、请求报告与错误分类。

本后端把用户 Type 当作 Table 2 judgment 的给定结论逐层核对，不调用
TypeConstructor。普通用户使用包根 ``check_hcsp_type``。
"""

from .checker import TypeChecker
from .errors import TypeCheckingErrorKind, classify_checking_error
from .model import TypeCheckingReport, TypeCheckingRequest

__all__ = [
    "TypeChecker",
    "TypeCheckingErrorKind",
    "TypeCheckingReport",
    "TypeCheckingRequest",
    "classify_checking_error",
]
