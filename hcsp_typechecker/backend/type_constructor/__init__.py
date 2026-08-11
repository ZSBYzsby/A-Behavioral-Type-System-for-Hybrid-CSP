"""TypeConstructor 的低层请求、规则执行、报告与错误分类。

普通用户不直接导入本子包；稳定入口是包根 ``construct_hcsp_type``。本子包供
门面编排、规则单元测试和论文审计使用。
"""

from .constructor import TypeConstructor, construct_type
from .errors import TypeConstructionErrorKind, classify_construction_error
from .model import TypeConstructionReport, TypeConstructionRequest

__all__ = [
    "TypeConstructionReport",
    "TypeConstructionErrorKind",
    "TypeConstructionRequest",
    "TypeConstructor",
    "construct_type",
    "classify_construction_error",
]
