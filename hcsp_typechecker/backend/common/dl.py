r"""Translate continuous-evolution proof goals into KeYmaera X dL formulas."""

from __future__ import annotations

from dataclasses import dataclass
from typing import Any, Iterable, Sequence

from .logic import z3


class DLTranslationError(ValueError):
    r"""The input exceeds the soundly supported dL translation fragment."""


@dataclass(frozen=True, slots=True)
class DLFormula:
    r"""A renamed dL formula ready for KeYmaera X."""

    source: str
    variables: tuple[str, ...]
    symbol_map: tuple[tuple[str, str], ...]
    role: str

    def __str__(self) -> str:
        r"""Display the dL formula in reports."""

        return self.source

    def to_archive(
        self,
        *,
        entry_name: str = "HCSP dL obligation",
        tactic: str = "auto",
    ) -> str:
        r"""Create a KeYmaera X .kyx archive for one proof goal."""

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


@dataclass(frozen=True, slots=True)
class UntranslatedDLFormula:
    r"""Preserve an unsupported dL goal with its translation failure reason."""

    role: str
    reason: str

    def __str__(self) -> str:
        r"""Return compact report text."""

        return f"<untranslated {self.role}: {self.reason}>"


class _Z3ToKeYmaeraX:
    r"""Print the supported Z3 arithmetic and Boolean fragment in KeYmaera X syntax."""

    def __init__(self) -> None:
        r"""Allocate symbol names in first-visit order."""

        self._names: dict[tuple[str, str], str] = {}

    @property
    def variables(self) -> tuple[str, ...]:
        r"""Return allocated KeYmaera X names in encounter order."""

        return tuple(self._names.values())

    @property
    def symbol_map(self) -> tuple[tuple[str, str], ...]:
        r"""Map safe prover names back to original Z3 symbols."""

        return tuple(
            (safe, original)
            for (original, _sort), safe in self._names.items()
        )

    def term(self, value: Any) -> str:
        r"""Translate numeric terms; reject unsupported sorts and uninterpreted functions."""

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

        # Reject unsupported constructs rather than guess a dL encoding.
        raise DLTranslationError(
            "unsupported dL term produced by the expression translator: "
            f"{value} (Z3 kind {kind})"
        )

    def formula(self, value: Any) -> str:
        r"""Translate Boolean connectives, implications, and numeric relations."""

        self._require_z3(value)
        if z3.is_true(value):
            return "true"
        if z3.is_false(value):
            return "false"
        if not z3.is_bool(value):
            raise DLTranslationError(f"expected a Boolean formula, got {value}")

        # KeYmaera X has no Boolean program variables; encoding arbitrary Bool constants as
        # reals is unsound.
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
        r"""Require a real-valued free constant on the ODE left-hand side."""

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
        r"""Reject missing Z3 or an invalid intermediate representation."""

        if z3 is None:
            raise DLTranslationError("z3-solver is required to construct dL formulas")
        if not isinstance(value, z3.AstRef):
            raise DLTranslationError(
                f"dL translation expected a Z3 term, got {type(value).__name__}"
            )

    @staticmethod
    def _is_uninterpreted_constant(value: Any) -> bool:
        r"""Distinguish free constants from uninterpreted function applications."""

        return (
            z3.is_const(value)
            and value.decl().kind() == z3.Z3_OP_UNINTERPRETED
            and value.num_args() == 0
        )

    def _variable_name(self, value: Any) -> str:
        r"""Assign deterministic, safe KeYmaera X names to free constants."""

        key = (str(value.decl().name()), str(value.sort()))
        if key not in self._names:
            self._names[key] = f"kxv{len(self._names)}"
        return self._names[key]

    def _arithmetic(self, kind: int, arguments: Sequence[Any]) -> str:
        r"""Preserve arithmetic AST grouping when printing supported operations."""

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
        r"""Print comparisons and expand distinct into pairwise inequalities."""

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
    r"""Print user ODE equations with the automatically generated local clock."""

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
    r"""Freeze symbol names and audit mappings after translation."""

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
    r"""Construct the Table 2 ODE safety premise."""

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
    r"""Construct pre -> [{F}]B for evolution ending only through communication."""

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
    r"""Construct the exact Table 2 evolution-boundary premise."""

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
