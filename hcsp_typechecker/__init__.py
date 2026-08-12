"""HCSP 行为 TypeConstructor、TypeChecker、Table 3 图和锁分析稳定接口。

普通用户调用 :func:`construct_hcsp_type` 从完整 HCSP 输入构造类型，或调用
:func:`check_hcsp_type` 检查同一输入末尾给出的用户 Type。Process AST、规则
judgment 和证明请求只在接口内部流转；其余子包不承诺稳定导入路径。
已有 Type AST 可交给 :func:`build_type_transition_graph`，得到以规范化 Type AST
为展示内容、以等递归循环项图为状态身份并覆盖 Table 3 关键-deadline约化关系全部
后继的状态转移图；该接口通过 ``result/full`` 模式输出初始规范类型或完整图，并以
:class:`HCSPTypeTransitionGraphError` 结构化报告输入、规范化和规模错误。
完整图可以继续交给 :func:`analyze_type_lock_freedom`。第四接口按照论文定义寻找
带非空 ready 集的无限时间边和纯静默有向环；性质不成立时正常返回含反例的
``LockFreedomReport``，只有图对象无效或不是完整可达闭包时才抛
``HCSPTypeLockAnalysisError``。

当规则推导已完成但证明义务仍为 ``unknown`` 时，接口抛出
:class:`HCSPUntrustedTypeConstructionError`，并通过其 ``untrusted_type`` 属性保留完整但
未验证的候选类型；候选类型不会伪装成普通成功返回值。

TypeChecker 以给定 Type 为规则结论逐层递归，不通过先运行 TypeConstructor 再
比较完整类型实现。

两套业务异常分别使用 ``TypeConstructionErrorKind`` 与
``TypeCheckingErrorKind`` 分类；共同的 ``HCSPErrorDetail`` 保存规则、判断位置、
证明公式和后端说明，调用者无需解析展示文本即可处理错误。
"""

from .api import (
    HCSPErrorDetail,
    HCSPInputError,
    HCSPTypeConstructionError,
    HCSPTypeCheckingError,
    HCSPTypeTransitionGraphError,
    HCSPTypeLockAnalysisError,
    HCSPUntrustedTypeConstructionError,
    OutputMode,
    TypeAST,
    TypeCheckingErrorKind,
    TypeConstructionErrorKind,
    TypeTransitionGraph,
    TypeTransitionGraphErrorKind,
    TypeLockAnalysisErrorKind,
    LockFreedomReport,
    analyze_type_lock_freedom,
    build_type_transition_graph,
    construct_hcsp_type,
    check_hcsp_type,
)


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
    "TypeTransitionGraph",
    "TypeTransitionGraphErrorKind",
    "TypeLockAnalysisErrorKind",
    "LockFreedomReport",
    "analyze_type_lock_freedom",
    "build_type_transition_graph",
    "construct_hcsp_type",
    "check_hcsp_type",
]
