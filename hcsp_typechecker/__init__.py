"""HCSP 行为类型检查器的稳定用户接口。

普通用户只需两步：先用 :func:`parse_hcsp_program` 把完整文本输入转换成一个
只读 :class:`HCSPProgram`，再用 :func:`infer_hcsp_type` 得到正式 Type AST。
其余子包属于项目内部实现，不承诺跨版本保持导入路径或构造协议稳定。
"""

from .api import (
    HCSPInputError,
    HCSPProgram,
    HCSPTypeError,
    OutputMode,
    TypeAST,
    infer_hcsp_type,
    parse_hcsp_program,
)


__all__ = [
    "HCSPInputError",
    "HCSPProgram",
    "HCSPTypeError",
    "OutputMode",
    "TypeAST",
    "infer_hcsp_type",
    "parse_hcsp_program",
]
