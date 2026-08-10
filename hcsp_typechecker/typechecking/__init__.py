"""Process AST 到 Type AST 的内部类型构造与证明后端。

该层实现 Table 2 规则、构造输入/报告模型、表达式逻辑翻译以及 dL/KeYmaera X
证明。它依赖 ``process`` 与 ``type_system``，但两者均不反向依赖本层。普通
用户通过包根的 TypeConstructor 接口间接调用，不直接构造这里的判断或证明器对象。

目录名 ``typechecking`` 是整个项目的类型相关共享实现层，不表示当前已经实现了
接收用户给定 Type 的 ``TypeChecker``。现有构造算法集中在 ``constructor.py``；
未来检查器将以独立模块和请求模型加入，并复用这里的环境与证明基础设施。
"""

from .constructor import TypeConstructor, construct_type
from .dl import DLFormula, DLTranslationError, UntranslatedDLFormula
from .keymaerax import KeYmaeraXBackend, KeYmaeraXConfig
from .model import (
    BasicType,
    ChannelType,
    TypeConstructionReport,
    Configuration,
    ContinuousType,
    DLCheckResult,
    Diagnostic,
    DerivationStep,
    ParameterEnvironment,
    ProofObligation,
    TypeConstructionRequest,
    Verdict,
)

__all__ = [
    "BasicType",
    "ChannelType",
    "TypeConstructionReport",
    "Configuration",
    "ContinuousType",
    "DLCheckResult",
    "DLFormula",
    "DLTranslationError",
    "Diagnostic",
    "DerivationStep",
    "KeYmaeraXBackend",
    "KeYmaeraXConfig",
    "ParameterEnvironment",
    "ProofObligation",
    "TypeConstructor",
    "TypeConstructionRequest",
    "UntranslatedDLFormula",
    "Verdict",
    "construct_type",
]
