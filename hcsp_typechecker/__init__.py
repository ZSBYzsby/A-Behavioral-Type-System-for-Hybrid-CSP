"""HCSP 行为 TypeConstructor 的稳定单入口用户接口。

普通用户只需调用 :func:`construct_hcsp_type`，把包含参数、Gamma、Theta 和
Process 的完整文本直接构造成正式 Type AST。Process AST 和低层构造对象只在接口内部
流转；其余子包属于项目内部实现，不承诺跨版本保持导入路径或构造协议稳定。

当规则推导已完成但证明义务仍为 ``unknown`` 时，接口抛出
:class:`HCSPUntrustedTypeConstructionError`，并通过其 ``untrusted_type`` 属性保留完整但
未验证的候选类型；候选类型不会伪装成普通成功返回值。

未来接收“用户给定 Type”并判断其是否成立的功能将作为独立 ``TypeChecker``
加入；当前根接口只提供 TypeConstructor，不占用未来检查器的名称。
"""

from .api import (
    HCSPInputError,
    HCSPTypeConstructionError,
    HCSPUntrustedTypeConstructionError,
    OutputMode,
    TypeAST,
    construct_hcsp_type,
)


__all__ = [
    "HCSPInputError",
    "HCSPTypeConstructionError",
    "HCSPUntrustedTypeConstructionError",
    "OutputMode",
    "TypeAST",
    "construct_hcsp_type",
]
