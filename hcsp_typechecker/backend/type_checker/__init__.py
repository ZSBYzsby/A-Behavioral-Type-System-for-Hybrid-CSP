r"""Type-directed checking requests, reports, and failure categories."""

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
