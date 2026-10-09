r"""Expose shared Type rendering through the frontend serializer."""

from __future__ import annotations

from ...data_structures.type_ast.ast import ConfigurationType
from ...data_structures.type_ast.render import (
    format_type_source as _format_type_source,
)


def format_type_source(value: ConfigurationType) -> str:
    r"""Render type-prefixed source that parses back without loss."""

    return _format_type_source(value)
