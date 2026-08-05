"""把类型规则中的连续演化证明目标表示为 KeYmaera X 可读的 dL 公式。

本模块刻意不定义新的 HCSP 语法，也不修改
:mod:`hcsp_typechecker.hcsp_process_ast` 或
:mod:`hcsp_typechecker.hcsp_type_ast`。
它处于类型检查器和外部证明器之间，只负责两件事：

* 把检查器已经建立的 Z3 符号状态翻译成 differential dynamic logic (dL)；
* 把一条 dL 公式包装成 KeYmaera X 接受的 ``.kyx`` archive。

传入本模块的入口路径、ODE 方程、演化域、安全性质和时延都已经由类型规则
确定。本模块不参与 T-Assign 后置谓词综合，也不从多个 premise 中寻找未知公式；
它只把一条已经具体化、但尚未证明的 ODE 义务转换成可信证明器所需的表示。

论文 Table 2 中与 ODE 有关的三个逻辑前提在这里分别表示为：

``safety``
    ``pre_with_t=0 -> [{x'=f(x), t'=1}]``
    ``(t<=d -> safe)``，其中 ``safe`` 只来自 ODE 节点批注；Gamma 只在规则层
    核对用户 ODE 左侧向量是否已经登记，不向公式追加性质。
``domain``
    ``pre_with_t=0 -> [{x'=f(x), t'=1}]B``。
``boundary``
    ``pre_with_t=0 -> [{x'=f(x), t'=1}]``
    ``((t<d -> B) & (t=d -> !B))``。该公式直接采用新版 Table 2：在 ``d``
    以前演化域成立，在 ``d`` 时演化域恰好失效。仅当有限 ODE 具有自然
    顺序后继时才需要这条边界前提。

KeYmaera X 的程序变量都是实数。项目中的整数或自然数参数在 dL 公式中按实数
过近似处理：若对所有实数都能证明公式，则对整数子域当然也成立；代价只是某些
本来可证的整数性质可能返回 ``unknown``，不会因此误报为 ``true``。
"""

from __future__ import annotations

from dataclasses import dataclass
from typing import Any, Iterable, Sequence

from .logic import z3


class DLTranslationError(ValueError):
    """输入超出当前可靠 dL 翻译子集时抛出的错误。

    调用方应把这个错误转换成 ``UNKNOWN`` 证明义务，而不是把未翻译的表达式
    当作字符串拼接进证明器输入。
    """


@dataclass(frozen=True)
class DLFormula:
    """一条已经完成变量重命名、可交给 KeYmaera X 的 dL 公式。

    ``symbol_map`` 的每一项为 ``(KeYmaera名称, Z3原名称)``，用于审计公式中
    的 ``kxv0`` 等安全名称究竟对应哪个符号状态。KeYmaera X 的标识符语法
    不接受项目 Z3 名称中的双下划线，因此不能直接复用原名称。
    """

    source: str
    variables: tuple[str, ...]
    symbol_map: tuple[tuple[str, str], ...]
    role: str

    def __str__(self) -> str:
        """在报告和日志中直接显示正式 dL 公式。"""

        return self.source

    def to_archive(
        self,
        *,
        entry_name: str = "HCSP dL obligation",
        tactic: str = "auto",
    ) -> str:
        """生成单条证明目标的 KeYmaera X ``.kyx`` archive。

        归档内显式列出 tactic，兼容仍使用旧式 ``-prove`` CLI 的 5.x 版本，
        也兼容新式 ``prove`` 子命令。名称中的换行和引号被替换，防止破坏
        archive 的结构；tactic 是本地受信配置，允许多行 Bellerophon 脚本。
        """

        safe_name = (
            str(entry_name)
            .replace("\\", "/")
            .replace('"', "'")
            .replace("\r", " ")
            .replace("\n", " ")
        )
        variable_block = "\n".join(
            f"  Real {name};" for name in self.variables
        )
        if variable_block:
            variable_section = (
                "ProgramVariables\n"
                f"{variable_block}\n"
                "End.\n\n"
            )
        else:
            variable_section = ""

        tactic_body = str(tactic).strip() or "auto"
        return (
            f'ArchiveEntry "{safe_name}"\n\n'
            f"{variable_section}"
            "Problem\n"
            f"  {self.source}\n"
            "End.\n\n"
            'Tactic "HCSP Proof"\n'
            f"  {tactic_body}\n"
            "End.\n\n"
            "End.\n"
        )


@dataclass(frozen=True)
class UntranslatedDLFormula:
    """保留无法可靠翻译的 dL 目标及其原因。

    这种对象仍会进入 :class:`~hcsp_typechecker.model.ProofObligation`，使审计者
    能看到失败发生在哪一类公式；KeYmaera X 后端会保守返回 ``UNKNOWN``。
    """

    role: str
    reason: str

    def __str__(self) -> str:
        """提供紧凑、可读的报告文本。"""

        return f"<untranslated {self.role}: {self.reason}>"


class _Z3ToKeYmaeraX:
    """把检查器使用的 Z3 算术/布尔子集打印为 KeYmaera X 语法。

    这里不调用 Z3 求解。Z3 AST 只是类型检查器当前符号状态的无歧义中间表示。
    每个自由数值常量都会被重命名为 ``kxvN``，从而避开 KeYmaera X 对下划线
    和索引的特殊词法规则。
    """

    def __init__(self) -> None:
        """建立空的、按首次访问顺序分配名称的符号表。"""

        self._names: dict[tuple[str, str], str] = {}

    @property
    def variables(self) -> tuple[str, ...]:
        """返回按首次出现顺序分配的 KeYmaera X 变量名。"""

        return tuple(self._names.values())

    @property
    def symbol_map(self) -> tuple[tuple[str, str], ...]:
        """返回安全名称到原始 Z3 名称的可审计映射。"""

        return tuple(
            (safe, original)
            for (original, _sort), safe in self._names.items()
        )

    def term(self, value: Any) -> str:
        """翻译数值项，并拒绝布尔、字符串、tuple 和未解释函数。"""

        self._require_z3(value)

        if z3.is_int_value(value):
            return str(value.as_long())
        if z3.is_rational_value(value):
            numerator = value.numerator_as_long()
            denominator = value.denominator_as_long()
            if denominator == 1:
                return str(numerator)
            return f"({numerator}/{denominator})"
        if z3.is_algebraic_value(value):
            raise DLTranslationError(
                "algebraic/irrational constants are not in the supported "
                "KeYmaera X arithmetic fragment"
            )

        if self._is_uninterpreted_constant(value):
            sort = value.sort()
            if sort.kind() not in {
                z3.Z3_INT_SORT,
                z3.Z3_REAL_SORT,
            }:
                raise DLTranslationError(
                    f"dL terms require numeric variables, got {sort} for {value}"
                )
            return self._variable_name(value)

        kind = value.decl().kind()
        arguments = list(value.children())

        if kind == z3.Z3_OP_TO_REAL and len(arguments) == 1:
            return self.term(arguments[0])
        if kind == z3.Z3_OP_UMINUS and len(arguments) == 1:
            return f"(-{self.term(arguments[0])})"
        if kind in {
            z3.Z3_OP_ADD,
            z3.Z3_OP_MUL,
            z3.Z3_OP_SUB,
            z3.Z3_OP_DIV,
            z3.Z3_OP_POWER,
        }:
            return self._arithmetic(kind, arguments)

        # ``mod``, ``ite``, strings、数组及未解释函数都没有在这里做猜测式编码。
        raise DLTranslationError(
            "unsupported dL term produced by the expression translator: "
            f"{value} (Z3 kind {kind})"
        )

    def formula(self, value: Any) -> str:
        """翻译布尔公式，包括连接词、蕴含和数值关系。"""

        self._require_z3(value)
        if z3.is_true(value):
            return "true"
        if z3.is_false(value):
            return "false"
        if not z3.is_bool(value):
            raise DLTranslationError(f"expected a Boolean formula, got {value}")

        # KeYmaera X 没有布尔型程序变量；任意 Bool 常量不能安全当作实数编码。
        if self._is_uninterpreted_constant(value):
            raise DLTranslationError(
                f"Boolean state variable {value} is not representable as a "
                "KeYmaera X real program variable"
            )

        kind = value.decl().kind()
        arguments = list(value.children())
        if kind == z3.Z3_OP_NOT and len(arguments) == 1:
            return f"!({self.formula(arguments[0])})"
        if kind in {z3.Z3_OP_AND, z3.Z3_OP_OR}:
            operator = "&" if kind == z3.Z3_OP_AND else "|"
            if not arguments:
                return "true" if kind == z3.Z3_OP_AND else "false"
            return "(" + f" {operator} ".join(
                self.formula(item) for item in arguments
            ) + ")"
        if kind == z3.Z3_OP_IMPLIES and len(arguments) == 2:
            return (
                f"({self.formula(arguments[0])} -> "
                f"{self.formula(arguments[1])})"
            )
        if kind in {
            z3.Z3_OP_EQ,
            z3.Z3_OP_DISTINCT,
            z3.Z3_OP_LE,
            z3.Z3_OP_GE,
            z3.Z3_OP_LT,
            z3.Z3_OP_GT,
        }:
            return self._relation(kind, arguments)

        raise DLTranslationError(
            "unsupported dL formula produced by the expression translator: "
            f"{value} (Z3 kind {kind})"
        )

    def variable(self, value: Any) -> str:
        """翻译 ODE 左端变量，并保证它确实是实值自由常量。"""

        self._require_z3(value)
        if (
            not self._is_uninterpreted_constant(value)
            or value.sort().kind() != z3.Z3_REAL_SORT
        ):
            raise DLTranslationError(
                f"ODE left-hand side must be a real variable, got {value}"
            )
        return self._variable_name(value)

    @staticmethod
    def _require_z3(value: Any) -> None:
        """给缺少 Z3 或错误中间表示提供直接、稳定的错误信息。"""

        if z3 is None:
            raise DLTranslationError("z3-solver is required to construct dL formulas")
        if not isinstance(value, z3.AstRef):
            raise DLTranslationError(
                f"dL translation expected a Z3 term, got {type(value).__name__}"
            )

    @staticmethod
    def _is_uninterpreted_constant(value: Any) -> bool:
        """区分自由常量与有参数的未解释函数应用。"""

        return (
            z3.is_const(value)
            and value.decl().kind() == z3.Z3_OP_UNINTERPRETED
            and value.num_args() == 0
        )

    def _variable_name(self, value: Any) -> str:
        """为一个 Z3 自由常量分配确定性的 KeYmaera X 安全名称。"""

        key = (str(value.decl().name()), str(value.sort()))
        if key not in self._names:
            self._names[key] = f"kxv{len(self._names)}"
        return self._names[key]

    def _arithmetic(self, kind: int, arguments: Sequence[Any]) -> str:
        """打印受支持的数值运算，并保留 Z3 AST 的结合结构。"""

        if not arguments:
            raise DLTranslationError("empty arithmetic application")
        if kind == z3.Z3_OP_ADD:
            operator = "+"
        elif kind == z3.Z3_OP_MUL:
            operator = "*"
        elif kind == z3.Z3_OP_SUB:
            operator = "-"
        elif kind == z3.Z3_OP_DIV:
            operator = "/"
        else:
            operator = "^"

        if kind == z3.Z3_OP_POWER and len(arguments) != 2:
            raise DLTranslationError("power needs exactly two operands")
        return "(" + f" {operator} ".join(
            self.term(item) for item in arguments
        ) + ")"

    def _relation(self, kind: int, arguments: Sequence[Any]) -> str:
        """打印比较关系；多元 ``distinct`` 展开成两两不等式。"""

        if kind == z3.Z3_OP_DISTINCT:
            if len(arguments) < 2:
                return "true"
            pairs = [
                f"({self.term(arguments[left])} != {self.term(arguments[right])})"
                for left in range(len(arguments))
                for right in range(left + 1, len(arguments))
            ]
            return "(" + " & ".join(pairs) + ")"
        if len(arguments) != 2:
            raise DLTranslationError("binary relation has unexpected arity")
        operators = {
            z3.Z3_OP_EQ: "=",
            z3.Z3_OP_LE: "<=",
            z3.Z3_OP_GE: ">=",
            z3.Z3_OP_LT: "<",
            z3.Z3_OP_GT: ">",
        }
        return (
            f"({self.term(arguments[0])} {operators[kind]} "
            f"{self.term(arguments[1])})"
        )


def _ode(
    printer: _Z3ToKeYmaeraX,
    equations: Iterable[tuple[Any, Any]],
    *,
    domain: Any | None = None,
) -> str:
    """打印含用户方程及自动局部时钟的 ODE 程序 ``{x'=e, ... & B}``。"""

    rendered = [
        f"{printer.variable(variable)}'={printer.term(derivative)}"
        for variable, derivative in equations
    ]
    if not rendered:
        raise DLTranslationError("an ODE obligation needs at least one equation")
    equations_text = ", ".join(rendered)
    domain_text = (
        ""
        if domain is None
        else f" & {printer.formula(domain)}"
    )
    return "{" + equations_text + domain_text + "}"


def _finish(
    printer: _Z3ToKeYmaeraX,
    source: str,
    role: str,
) -> DLFormula:
    """在所有子式完成翻译后冻结变量表和审计映射。"""

    return DLFormula(source, printer.variables, printer.symbol_map, role)


def safety_formula(
    *,
    precondition: Any,
    equations: Sequence[tuple[Any, Any]],
    domain: Any,
    safety: Any,
    duration: Any | None,
    clock: Any,
    infinite_duration: bool = False,
) -> DLFormula:
    """构造论文 Table 2 的 ODE 安全性 dL 前提。

    ``precondition`` 已包含当前 ODE 自动局部时钟的入口条件 ``t=0``，而
    ``equations`` 已包含 ``t'=1``。调用方传入的 ``safety`` 只来自 ODE 节点，
    并留在 box 的后置目标中接受验证，不能作为 ODE 程序的演化域假设。Gamma
    只登记允许出现的 ODE 演化向量，不再携带另一份连续性质。HCSP 源演化域
    ``B`` 仍由 Table 2 的其他 premise 验证；参数 ``domain`` 保留在签名中就是
    为了明确本安全公式不直接使用它。
    有限时延在后置条件中引用同一个 ``clock``；无限时延仍保留该 ODE 固有的
    局部时钟方程。
    """

    if z3 is not None and z3.is_true(z3.simplify(safety)):
        return DLFormula("true", (), (), "safety")

    printer = _Z3ToKeYmaeraX()
    pre = printer.formula(precondition)
    post = printer.formula(safety)
    if infinite_duration:
        program = _ode(printer, equations)
        source = f"({pre} -> [{program}]{post})"
        return _finish(printer, source, "safety")
    if duration is None:
        raise DLTranslationError(
            "a finite safety obligation needs the annotated delay d"
        )

    delay = printer.term(duration)
    clock_term = printer.term(clock)
    program = _ode(printer, equations)
    source = (
        f"({pre} -> "
        f"[{program}]({clock_term}<={delay} -> {post}))"
    )
    return _finish(printer, source, "safety")


def domain_formula(
    *,
    precondition: Any,
    equations: Sequence[tuple[Any, Any]],
    domain: Any,
    domain_definedness: Any,
) -> DLFormula:
    """构造只允许通信中断时的演化域保持前提 ``pre -> [{F}]B``。

    调用方传入的 pre/equations 已分别包含局部时钟的 ``t=0``/``t'=1``；若
    源演化域 B 使用保留名 ``t``，调用方也已把它翻译成这里的同一个时钟项。
    B 是这条 premise 要证明的不变量，所以只出现在后置条件。若写成
    ``[{F & B}]B``，dL 的演化域语义会预设待检查的性质，无法发现动力学离开
    相应区域的反例。
    """

    if z3 is not None and z3.is_true(z3.simplify(domain)):
        return DLFormula("true", (), (), "domain")
    printer = _Z3ToKeYmaeraX()
    pre = printer.formula(precondition)
    post = printer.formula(z3.simplify(z3.And(domain_definedness, domain)))
    program = _ode(printer, equations)
    return _finish(
        printer,
        f"({pre} -> [{program}]{post})",
        "domain",
    )


def boundary_formula(
    *,
    precondition: Any,
    equations: Sequence[tuple[Any, Any]],
    domain: Any,
    domain_definedness: Any,
    duration: Any,
    clock: Any,
) -> DLFormula:
    """构造新版 Table 2 的准确演化边界前提。

    公式在无演化域假设的动力学 ``{F,t'=1}`` 上证明：当局部时钟还满足
    ``t<d`` 时 ``B`` 成立，而在 ``t=d`` 时 ``B`` 已经失效。这里不能把待验证
    的 ``B`` 放入 dL 程序的演化域，否则第二个蕴含无法观察到真实反例；也不再
    使用旧实现的 box+diamond 近似编码。
    """

    printer = _Z3ToKeYmaeraX()
    pre = printer.formula(precondition)
    in_domain = z3.simplify(z3.And(domain_definedness, domain))
    outside_domain = z3.simplify(
        z3.And(domain_definedness, z3.Not(domain))
    )
    post = printer.formula(
        z3.And(
            z3.Implies(clock < duration, in_domain),
            z3.Implies(clock == duration, outside_domain),
        )
    )
    program = _ode(printer, equations)
    source = f"({pre} -> [{program}]{post})"
    return _finish(printer, source, "boundary")
