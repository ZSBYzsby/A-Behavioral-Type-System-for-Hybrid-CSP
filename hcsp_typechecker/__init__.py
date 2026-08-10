"""HCSP 行为 TypeConstructor 与 TypeChecker 的稳定用户接口。

普通用户调用 :func:`construct_hcsp_type` 从完整 HCSP 输入构造类型，或调用
:func:`check_hcsp_type` 检查同一输入末尾给出的用户 Type。Process AST、规则
judgment 和证明请求只在接口内部流转；其余子包不承诺稳定导入路径。

当规则推导已完成但证明义务仍为 ``unknown`` 时，接口抛出
:class:`HCSPUntrustedTypeConstructionError`，并通过其 ``untrusted_type`` 属性保留完整但
未验证的候选类型；候选类型不会伪装成普通成功返回值。

TypeChecker 以给定 Type 为规则结论逐层递归，不通过先运行 TypeConstructor 再
比较完整类型实现。
"""

from .api import (
    HCSPInputError,
    HCSPTypeConstructionError,
    HCSPTypeCheckingError,
    HCSPUntrustedTypeConstructionError,
    OutputMode,
    TypeAST,
    construct_hcsp_type,
    check_hcsp_type,
)


__all__ = [
    "HCSPInputError",
    "HCSPTypeConstructionError",
    "HCSPTypeCheckingError",
    "HCSPUntrustedTypeConstructionError",
    "OutputMode",
    "TypeAST",
    "construct_hcsp_type",
    "check_hcsp_type",
]
