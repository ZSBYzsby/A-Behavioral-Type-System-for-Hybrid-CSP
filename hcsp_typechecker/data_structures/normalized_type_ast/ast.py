r"""Table 3 状态空间采用的规范化行为 Type AST。

规范化树不是用户 Type 语法的第二种写法，而是操作语义内部的商结构：并行按结合律、
交换律和 ``EmptyType`` 单位元规范化但保留重数；内部选择按结合律、交换律和幂等律
规范化；外部选择按交换律和幂等律规范化；递归引用使用 De Bruijn index 消除绑定名
差异。全部节点不可变且可哈希，可直接作为状态图判重键。
"""

from __future__ import annotations

from abc import ABC
from dataclasses import dataclass
from fractions import Fraction
from typing import Any, Iterable, TypeAlias

from ...identifiers import is_hcsp_identifier


class NormalizedProcessType(ABC):
    """规范化过程类型 ``T`` 的抽象类别。"""

    def __new__(cls, *args: Any, **kwargs: Any) -> "NormalizedProcessType":
        """阻止绕过具体规范产生式直接实例化抽象过程类别。"""

        if cls is NormalizedProcessType:
            raise TypeError("NormalizedProcessType is an abstract category")
        return super().__new__(cls)


class NormalizedAngelicType(ABC):
    """规范化中断/外部选择类型 ``A`` 的抽象类别。"""

    def __new__(cls, *args: Any, **kwargs: Any) -> "NormalizedAngelicType":
        """阻止绕过具体规范产生式直接实例化抽象 angelic 类别。"""

        if cls is NormalizedAngelicType:
            raise TypeError("NormalizedAngelicType is an abstract category")
        return super().__new__(cls)


@dataclass(frozen=True, slots=True)
class NormalizedEmptyType(NormalizedProcessType):
    """正常终止且不再产生信道通信的空过程行为。"""


@dataclass(frozen=True, slots=True)
class NormalizedBottomType(NormalizedProcessType):
    """论文中的异常底行为 ``\bot``，不能与正常空行为合并。"""


@dataclass(frozen=True, slots=True)
class NormalizedBoundTypeVar(NormalizedProcessType):
    """使用 De Bruijn index 表示的受绑定递归类型变量。"""

    index: int

    def __post_init__(self) -> None:
        """拒绝 Boolean 和负数，确保 index 能表示某一外层 ``mu``。"""

        if isinstance(self.index, bool) or not isinstance(self.index, int):
            raise TypeError("Normalized type-variable index must be an integer")
        if self.index < 0:
            raise ValueError("Normalized type-variable index must be non-negative")


@dataclass(frozen=True, slots=True)
class NormalizedNoInterruptType(NormalizedAngelicType):
    """空 angelic choice，即 delay 不含任何通信中断分支。"""


@dataclass(frozen=True, slots=True)
class NormalizedInputType(NormalizedAngelicType):
    """规范化输入中断分支 ``ch?.T``。"""

    channel: str
    continuation: NormalizedProcessType

    def __post_init__(self) -> None:
        """验证通道词法边界和通信后的规范化过程类型。"""

        if not is_hcsp_identifier(self.channel):
            raise ValueError("Normalized input channel must be an HCSP identifier")
        if not isinstance(self.continuation, NormalizedProcessType):
            raise TypeError("Normalized input continuation must be a process type")


@dataclass(frozen=True, slots=True)
class NormalizedOutputType(NormalizedAngelicType):
    """规范化输出中断分支 ``ch!.T``。"""

    channel: str
    continuation: NormalizedProcessType

    def __post_init__(self) -> None:
        """验证通道词法边界和通信后的规范化过程类型。"""

        if not is_hcsp_identifier(self.channel):
            raise ValueError("Normalized output channel must be an HCSP identifier")
        if not isinstance(self.continuation, NormalizedProcessType):
            raise TypeError("Normalized output continuation must be a process type")


NormalizedCommunicationType: TypeAlias = NormalizedInputType | NormalizedOutputType


@dataclass(frozen=True, slots=True)
class NormalizedExternalChoiceType(NormalizedAngelicType):
    """按交换律和幂等律排序去重后的多元外部选择。"""

    branches: tuple[NormalizedCommunicationType, ...]

    def __post_init__(self) -> None:
        """保证多元节点至少两支，并已经处于唯一排序去重形式。"""

        if len(self.branches) < 2:
            raise ValueError("Normalized external choice requires at least two branches")
        if not all(
            isinstance(branch, (NormalizedInputType, NormalizedOutputType))
            for branch in self.branches
        ):
            raise TypeError("Normalized external-choice branches must be communications")
        expected = tuple(
            sorted(set(self.branches), key=normalized_angelic_key)
        )
        if self.branches != expected:
            raise ValueError(
                "Normalized external-choice branches must be sorted and unique"
            )


@dataclass(frozen=True, slots=True)
class NormalizedInternalChoiceType(NormalizedProcessType):
    """按结合律、交换律和幂等律展平排序去重的多元内部选择。"""

    branches: tuple[NormalizedProcessType, ...]

    def __post_init__(self) -> None:
        """拒绝嵌套、单分支、乱序或重复的非规范内部选择。"""

        if len(self.branches) < 2:
            raise ValueError("Normalized internal choice requires at least two branches")
        if not all(
            isinstance(branch, NormalizedProcessType) for branch in self.branches
        ):
            raise TypeError("Normalized internal-choice branches must be process types")
        if any(
            isinstance(branch, NormalizedInternalChoiceType)
            for branch in self.branches
        ):
            raise ValueError("Normalized internal choices must be flattened")
        expected = tuple(
            sorted(set(self.branches), key=normalized_process_key)
        )
        if self.branches != expected:
            raise ValueError(
                "Normalized internal-choice branches must be sorted and unique"
            )


def _normalize_duration(duration: Any) -> Fraction:
    """把规范 delay 时长限制为非负精确有理数。"""

    if isinstance(duration, bool):
        raise TypeError("Normalized duration must not be Boolean")
    if isinstance(duration, Fraction):
        value = duration
    elif isinstance(duration, int):
        value = Fraction(duration)
    else:
        raise TypeError("Normalized duration must be an int or Fraction")
    if value < 0:
        raise ValueError("Normalized duration must be non-negative")
    return value


@dataclass(frozen=True, slots=True, init=False)
class NormalizedFiniteDelayType(NormalizedProcessType):
    r"""规范有限时延 ``delay(d) \unrhd A \triangleright T``。"""

    duration: Fraction
    interrupts: NormalizedAngelicType
    continuation: NormalizedProcessType

    def __init__(
        self,
        duration: int | Fraction,
        interrupts: NormalizedAngelicType,
        continuation: NormalizedProcessType,
    ) -> None:
        """验证并冻结有限有理时长、中断集合和正常后继。"""

        if not isinstance(interrupts, NormalizedAngelicType):
            raise TypeError("Normalized finite delay requires an angelic type")
        if not isinstance(continuation, NormalizedProcessType):
            raise TypeError("Normalized finite delay requires a process continuation")
        if isinstance(continuation, NormalizedBottomType):
            raise ValueError("Normalized finite-delay continuation cannot be bottom")
        object.__setattr__(self, "duration", _normalize_duration(duration))
        object.__setattr__(self, "interrupts", interrupts)
        object.__setattr__(self, "continuation", continuation)


@dataclass(frozen=True, slots=True)
class NormalizedInfiniteDelayType(NormalizedProcessType):
    """规范无穷时延；其不可达自然后继由语义固定为 ``\bot``。"""

    interrupts: NormalizedAngelicType

    def __post_init__(self) -> None:
        """确保无穷时延只携带规范 angelic type。"""

        if not isinstance(self.interrupts, NormalizedAngelicType):
            raise TypeError("Normalized infinite delay requires an angelic type")


@dataclass(frozen=True, slots=True)
class NormalizedMuType(NormalizedProcessType):
    """无绑定名称的规范递归类型；变量引用使用 De Bruijn index。"""

    body: NormalizedProcessType

    def __post_init__(self) -> None:
        """确保递归体属于过程范畴且自身递归引用均受通信保护。"""

        if not isinstance(self.body, NormalizedProcessType):
            raise TypeError("Normalized recursive body must be a process type")
        if not _target_binder_guarded(self.body, 0, False):
            raise ValueError("Normalized recursive variable is not communication-guarded")


def make_normalized_internal_choice(
    branches: Iterable[NormalizedProcessType],
) -> NormalizedProcessType:
    """展平、排序并去重内部选择，单一结果直接返回该分支。"""

    flat: list[NormalizedProcessType] = []
    for branch in branches:
        if not isinstance(branch, NormalizedProcessType):
            raise TypeError("Normalized internal-choice branch must be a process type")
        if isinstance(branch, NormalizedInternalChoiceType):
            flat.extend(branch.branches)
        else:
            flat.append(branch)
    if not flat:
        raise ValueError("Normalized internal choice cannot be empty")
    unique = tuple(sorted(set(flat), key=normalized_process_key))
    if len(unique) == 1:
        return unique[0]
    return NormalizedInternalChoiceType(unique)


def make_normalized_external_choice(
    branches: Iterable[NormalizedCommunicationType],
) -> NormalizedAngelicType:
    """排序并去重外部选择，按零、单、多分支返回唯一规范节点。"""

    items = tuple(branches)
    if not all(
        isinstance(branch, (NormalizedInputType, NormalizedOutputType))
        for branch in items
    ):
        raise TypeError("Normalized external-choice branch must be a communication")
    unique = tuple(sorted(set(items), key=normalized_angelic_key))
    if not unique:
        return NormalizedNoInterruptType()
    if len(unique) == 1:
        return unique[0]
    return NormalizedExternalChoiceType(unique)


def normalized_process_key(value: NormalizedProcessType) -> tuple[Any, ...]:
    """返回规范过程类型的稳定全序键，供集合规范化和确定性遍历使用。"""

    if isinstance(value, NormalizedEmptyType):
        return ("00-empty",)
    if isinstance(value, NormalizedBottomType):
        return ("01-bottom",)
    if isinstance(value, NormalizedBoundTypeVar):
        return ("02-bound", value.index)
    if isinstance(value, NormalizedInternalChoiceType):
        return (
            "03-internal",
            tuple(normalized_process_key(branch) for branch in value.branches),
        )
    if isinstance(value, NormalizedFiniteDelayType):
        return (
            "04-finite",
            value.duration.numerator,
            value.duration.denominator,
            normalized_angelic_key(value.interrupts),
            normalized_process_key(value.continuation),
        )
    if isinstance(value, NormalizedInfiniteDelayType):
        return ("05-infinite", normalized_angelic_key(value.interrupts))
    if isinstance(value, NormalizedMuType):
        return ("06-mu", normalized_process_key(value.body))
    raise TypeError(f"Unsupported normalized process type: {type(value).__name__}")


def normalized_angelic_key(value: NormalizedAngelicType) -> tuple[Any, ...]:
    """返回规范 angelic type 的稳定全序键。"""

    if isinstance(value, NormalizedNoInterruptType):
        return ("00-none",)
    if isinstance(value, NormalizedInputType):
        return (
            "01-input",
            value.channel,
            normalized_process_key(value.continuation),
        )
    if isinstance(value, NormalizedOutputType):
        return (
            "02-output",
            value.channel,
            normalized_process_key(value.continuation),
        )
    if isinstance(value, NormalizedExternalChoiceType):
        return (
            "03-external",
            tuple(normalized_angelic_key(branch) for branch in value.branches),
        )
    raise TypeError(f"Unsupported normalized angelic type: {type(value).__name__}")


def _target_binder_guarded(
    value: NormalizedProcessType,
    nested_depth: int,
    under_communication: bool,
) -> bool:
    """检查目标外层 mu 的引用在所有路径上均先经过一次通信。"""

    if isinstance(value, (NormalizedEmptyType, NormalizedBottomType)):
        return True
    if isinstance(value, NormalizedBoundTypeVar):
        return value.index != nested_depth or under_communication
    if isinstance(value, NormalizedInternalChoiceType):
        return all(
            _target_binder_guarded(branch, nested_depth, under_communication)
            for branch in value.branches
        )
    if isinstance(value, NormalizedFiniteDelayType):
        return _target_binder_guarded_angelic(
            value.interrupts,
            nested_depth,
            under_communication,
        ) and _target_binder_guarded(
            value.continuation,
            nested_depth,
            under_communication,
        )
    if isinstance(value, NormalizedInfiniteDelayType):
        return _target_binder_guarded_angelic(
            value.interrupts,
            nested_depth,
            under_communication,
        )
    if isinstance(value, NormalizedMuType):
        return _target_binder_guarded(
            value.body,
            nested_depth + 1,
            under_communication,
        )
    raise TypeError(f"Unsupported normalized process type: {type(value).__name__}")


def _target_binder_guarded_angelic(
    value: NormalizedAngelicType,
    nested_depth: int,
    under_communication: bool,
) -> bool:
    """在 angelic 分支中把通信 continuation 标记为已受保护。"""

    if isinstance(value, NormalizedNoInterruptType):
        return True
    if isinstance(value, (NormalizedInputType, NormalizedOutputType)):
        return _target_binder_guarded(
            value.continuation,
            nested_depth,
            True,
        )
    if isinstance(value, NormalizedExternalChoiceType):
        return all(
            _target_binder_guarded_angelic(
                branch,
                nested_depth,
                under_communication,
            )
            for branch in value.branches
        )
    raise TypeError(f"Unsupported normalized angelic type: {type(value).__name__}")


@dataclass(frozen=True, slots=True, init=False)
class NormalizedConfigurationType:
    """按并行结合/交换律和 Empty 单位元规范化的配置类型根。"""

    components: tuple[NormalizedProcessType, ...]

    def __init__(self, components: Iterable[NormalizedProcessType]) -> None:
        """删除并行 Empty 单位元、排序分量并保留并行重数。"""

        items = tuple(components)
        if not all(isinstance(item, NormalizedProcessType) for item in items):
            raise TypeError("Normalized configuration components must be process types")
        nonempty = tuple(
            item for item in items if not isinstance(item, NormalizedEmptyType)
        )
        if nonempty:
            canonical = tuple(sorted(nonempty, key=normalized_process_key))
        else:
            canonical = (NormalizedEmptyType(),)
        object.__setattr__(self, "components", canonical)

    @property
    def is_empty(self) -> bool:
        """判断该规范配置是否是唯一正常空状态。"""

        return len(self.components) == 1 and isinstance(
            self.components[0], NormalizedEmptyType
        )
