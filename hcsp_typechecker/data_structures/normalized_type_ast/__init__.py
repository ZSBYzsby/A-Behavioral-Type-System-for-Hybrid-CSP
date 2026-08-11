"""Table 3 操作语义使用的规范化行为 Type AST。

本子包与保存用户/TypeConstructor 原始结构的 ``type_ast`` 分离。公开的
``normalize_type_ast`` 只执行从原 Type AST 到规范化 AST 的单向转换；规范化结果
消除并行排列、内部/外部选择的 AC-idempotent 差异和递归绑定变量改名差异，供状态图
结点直接判等与哈希。
"""

from .ast import (
    NormalizedAngelicType,
    NormalizedBottomType,
    NormalizedBoundTypeVar,
    NormalizedConfigurationType,
    NormalizedEmptyType,
    NormalizedExternalChoiceType,
    NormalizedFiniteDelayType,
    NormalizedInfiniteDelayType,
    NormalizedInputType,
    NormalizedInternalChoiceType,
    NormalizedMuType,
    NormalizedNoInterruptType,
    NormalizedOutputType,
    NormalizedProcessType,
    make_normalized_external_choice,
    make_normalized_internal_choice,
    normalized_angelic_key,
    normalized_process_key,
)
from .conversion import TypeNormalizationError, normalize_type_ast

__all__ = [
    "NormalizedAngelicType",
    "NormalizedBottomType",
    "NormalizedBoundTypeVar",
    "NormalizedConfigurationType",
    "NormalizedEmptyType",
    "NormalizedExternalChoiceType",
    "NormalizedFiniteDelayType",
    "NormalizedInfiniteDelayType",
    "NormalizedInputType",
    "NormalizedInternalChoiceType",
    "NormalizedMuType",
    "NormalizedNoInterruptType",
    "NormalizedOutputType",
    "NormalizedProcessType",
    "TypeNormalizationError",
    "make_normalized_external_choice",
    "make_normalized_internal_choice",
    "normalize_type_ast",
    "normalized_angelic_key",
    "normalized_process_key",
]
