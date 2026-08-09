"""Process AST 到 Type AST 的内部类型推导与证明后端。

该层实现 Table 2 规则、检查输入/报告模型、表达式逻辑翻译以及 dL/KeYmaera X
证明。它依赖 ``process`` 与 ``type_system``，但两者均不反向依赖本层。普通
用户通过包根 ``infer_hcsp_type`` 调用，不直接构造这里的判断或证明器对象。
"""

from .checker import TypeChecker, check_hcsp
from .dl import DLFormula, DLTranslationError, UntranslatedDLFormula
from .keymaerax import KeYmaeraXBackend, KeYmaeraXConfig
from .model import (
    BasicType,
    ChannelType,
    CheckReport,
    Configuration,
    ContinuousType,
    DLCheckResult,
    Diagnostic,
    InferenceStep,
    ParameterEnvironment,
    ProofObligation,
    TypingJudgment,
    Verdict,
)

__all__ = [
    "BasicType",
    "ChannelType",
    "CheckReport",
    "Configuration",
    "ContinuousType",
    "DLCheckResult",
    "DLFormula",
    "DLTranslationError",
    "Diagnostic",
    "InferenceStep",
    "KeYmaeraXBackend",
    "KeYmaeraXConfig",
    "ParameterEnvironment",
    "ProofObligation",
    "TypeChecker",
    "TypingJudgment",
    "UntranslatedDLFormula",
    "Verdict",
    "check_hcsp",
]
