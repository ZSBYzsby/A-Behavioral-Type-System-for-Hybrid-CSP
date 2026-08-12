r"""Table 3 状态空间采用的规范化行为 Type AST。

规范化树不是用户 Type 语法的第二种写法，而是操作语义内部的商结构：并行按结合律、
交换律和 ``EmptyType`` 单位元规范化但保留重数；内部选择按结合律、交换律和幂等律
规范化；外部选择按交换律和幂等律规范化；递归引用使用 De Bruijn index 消除绑定名
差异。全部节点不可变且可哈希，并作为有限循环项图的构造输入；Table 3 正式作用于
该项图，使 ``mu t.T`` 与 ``T[mu t.T/t]`` 从状态身份到出边集合都完全一致。
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
        """拒绝 Boolean 和负数，保证 De Bruijn index 具有合法编码形状。"""

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
    """返回规范过程类型的稳定全序键，使用迭代后序遍历。"""

    return _normalized_key(value)


def normalized_angelic_key(value: NormalizedAngelicType) -> tuple[Any, ...]:
    """返回规范 angelic type 的稳定全序键，使用迭代后序遍历。"""

    return _normalized_key(value)


def _normalized_children(
    value: NormalizedProcessType | NormalizedAngelicType,
) -> tuple[NormalizedProcessType | NormalizedAngelicType, ...]:
    """返回稳定键计算所需的直接子节点。"""

    if isinstance(value, (NormalizedInputType, NormalizedOutputType)):
        return (value.continuation,)
    if isinstance(value, (NormalizedExternalChoiceType, NormalizedInternalChoiceType)):
        return value.branches
    if isinstance(value, NormalizedFiniteDelayType):
        return (value.interrupts, value.continuation)
    if isinstance(value, NormalizedInfiniteDelayType):
        return (value.interrupts,)
    if isinstance(value, NormalizedMuType):
        return (value.body,)
    return ()


def _normalized_key(
    root: NormalizedProcessType | NormalizedAngelicType,
) -> tuple[Any, ...]:
    """以显式栈构造深层规范 Type 的不可变结构键。"""

    results: dict[int, tuple[Any, ...]] = {}
    pending = [(root, False)]
    while pending:
        current, exiting = pending.pop()
        key = id(current)
        if key in results:
            continue
        children = _normalized_children(current)
        if not exiting and children:
            pending.append((current, True))
            pending.extend((child, False) for child in reversed(children))
            continue
        child_keys = tuple(results[id(child)] for child in children)
        if isinstance(current, NormalizedEmptyType): value = ("00-empty",)
        elif isinstance(current, NormalizedBottomType): value = ("01-bottom",)
        elif isinstance(current, NormalizedBoundTypeVar): value = ("02-bound", current.index)
        elif isinstance(current, NormalizedInternalChoiceType): value = ("03-internal", child_keys)
        elif isinstance(current, NormalizedFiniteDelayType):
            value = ("04-finite", current.duration.numerator, current.duration.denominator, child_keys[0], child_keys[1])
        elif isinstance(current, NormalizedInfiniteDelayType): value = ("05-infinite", child_keys[0])
        elif isinstance(current, NormalizedMuType): value = ("06-mu", child_keys[0])
        elif isinstance(current, NormalizedNoInterruptType): value = ("00-none",)
        elif isinstance(current, NormalizedInputType): value = ("01-input", current.channel, child_keys[0])
        elif isinstance(current, NormalizedOutputType): value = ("02-output", current.channel, child_keys[0])
        elif isinstance(current, NormalizedExternalChoiceType): value = ("03-external", child_keys)
        else:
            raise TypeError(f"Unsupported normalized type: {type(current).__name__}")
        results[key] = value
    return results[id(root)]


def _target_binder_guarded(
    value: NormalizedProcessType,
    nested_depth: int,
    under_communication: bool,
) -> bool:
    """检查目标外层 mu 的引用在所有路径上均先经过一次通信。"""

    pending: list[tuple[object, int, bool, bool]] = [
        (value, nested_depth, under_communication, False)
    ]
    while pending:
        current, depth, protected, angelic = pending.pop()
        if not angelic:
            if isinstance(current, (NormalizedEmptyType, NormalizedBottomType)):
                continue
            if isinstance(current, NormalizedBoundTypeVar):
                if current.index == depth and not protected:
                    return False
                continue
            if isinstance(current, NormalizedInternalChoiceType):
                pending.extend(
                    (branch, depth, protected, False)
                    for branch in current.branches
                )
                continue
            if isinstance(current, NormalizedFiniteDelayType):
                pending.append((current.continuation, depth, protected, False))
                pending.append((current.interrupts, depth, protected, True))
                continue
            if isinstance(current, NormalizedInfiniteDelayType):
                pending.append((current.interrupts, depth, protected, True))
                continue
            if isinstance(current, NormalizedMuType):
                pending.append((current.body, depth + 1, protected, False))
                continue
            raise TypeError(
                f"Unsupported normalized process type: {type(current).__name__}"
            )

        if isinstance(current, NormalizedNoInterruptType):
            continue
        if isinstance(current, (NormalizedInputType, NormalizedOutputType)):
            pending.append((current.continuation, depth, True, False))
            continue
        if isinstance(current, NormalizedExternalChoiceType):
            pending.extend(
                (branch, depth, protected, True)
                for branch in current.branches
            )
            continue
        raise TypeError(
            f"Unsupported normalized angelic type: {type(current).__name__}"
        )
    return True


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
