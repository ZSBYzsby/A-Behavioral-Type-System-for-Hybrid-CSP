"""Table 3 状态空间使用的规范化行为 Type AST 及单向转换。

本子包与保存用户、TypeConstructor 和 TypeChecker 正式结构的 ``type_ast`` 分离。
``normalize_type_ast`` 消除并行排列、选择的代数等价以及递归绑定变量改名差异，
但仍把 ``mu`` 保存为有限 AST 节点。真正忽略 ``mu t.T`` 与有限展开差异的状态身份
由后续 ``regular_type_term_graph`` 循环项图给出；本层结果同时作为该项图的输入和
状态图面向用户的展示类型，不提供反向转换。
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
