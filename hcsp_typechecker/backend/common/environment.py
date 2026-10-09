r"""Shared prepared typing environments for Constructor and Checker."""

from __future__ import annotations

from dataclasses import dataclass
from typing import Any

from ...data_structures.runtime_context import BasicType, ChannelType, GammaType


@dataclass(frozen=True, slots=True)
class PreparedTypingEnvironment:
    r"""Normalized Gamma, Theta, and parameters after common well-formedness checks."""

    gamma: dict[str, GammaType]
    theta: dict[str, ChannelType]
    parameters: dict[str, BasicType]
    parameter_symbols: dict[str, Any]
    parameter_condition: Any


__all__ = ["PreparedTypingEnvironment"]
