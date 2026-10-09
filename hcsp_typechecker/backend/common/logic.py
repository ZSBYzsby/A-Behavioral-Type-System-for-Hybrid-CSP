r"""Translate expression ASTs to Z3 and prove first-order obligations."""

from __future__ import annotations

from dataclasses import dataclass
from decimal import Decimal
from fractions import Fraction
from numbers import Integral, Real
from typing import Any, Mapping, MutableMapping, Sequence

from ...identifiers import is_hcsp_identifier
from ...data_structures.process_ast.expressions import (
    BinaryExpr,
    BooleanExpr,
    CallExpr,
    CompareExpr,
    Expr,
    ExprLike,
    Literal,
    UnaryExpr,
    Variable,
    ensure_expr,
    ensure_variable,
)
from ...data_structures.runtime_context import (
    BasicType,
    ChannelType,
    GammaType,
    gamma_value_type,
    is_subtype,
    normalize_gamma_type,
    normalize_type,
)
from .model import Verdict

try:
    import z3  # type: ignore
except ImportError:  # pragma: no cover - exercised when dependency is absent
    # Allow imports without Z3; proof requests report UNKNOWN with the missing dependency.
    z3 = None


@dataclass(frozen=True, slots=True)
class ExprResult:
    r"""A translated term with its static type and definedness conditions."""

    term: Any
    value_type: BasicType
    definedness: tuple[Any, ...] = ()


class ExpressionError(ValueError):
    r"""An expression is malformed, ill-typed, or unsupported."""

    pass


def z3_available() -> bool:
    r"""Report whether automatic first-order proofs are available."""
    return z3 is not None


def _is_z3(value: Any) -> bool:
    r"""Avoid accessing Z3 types when the dependency is unavailable."""
    return z3 is not None and isinstance(value, z3.AstRef)


def lvalue_name(value: str | Variable) -> str:
    r"""Extract the variable name from a scalar assignment target."""
    try:
        return ensure_variable(value).name
    except (TypeError, ValueError) as exc:
        raise ExpressionError(str(exc)) from exc


class ExpressionTranslator:
    r"""Translate project expression ASTs into typed Z3 terms."""

    def __init__(
        self,
        gamma: Mapping[str, GammaType],
        symbols: MutableMapping[str, Any] | None = None,
        *,
        name_prefix: str = "",
    ) -> None:
        r"""Create a scalar environment, excluding ODE vector declaration labels."""
        invalid_names = {
            repr(name) for name in gamma if not is_hcsp_identifier(name)
        }
        if invalid_names:
            raise ExpressionError(
                "Invalid Gamma names: " + ", ".join(sorted(invalid_names))
            )
        normalized_gamma = {
            name: normalize_gamma_type(value, subject="Gamma entry")
            for name, value in gamma.items()
        }
        self.gamma = {
            name: value
            for name, value in normalized_gamma.items()
            if isinstance(value, BasicType)
        }
        self.symbols: MutableMapping[str, Any] = {} if symbols is None else symbols
        self.name_prefix = name_prefix
        self._functions: dict[tuple[str, tuple[str, ...], str], Any] = {}

    def clone(
        self,
        symbols: MutableMapping[str, Any] | None = None,
    ) -> "ExpressionTranslator":
        r"""Clone branch-local symbols while sharing uninterpreted function declarations."""
        other = ExpressionTranslator(
            self.gamma,
            dict(self.symbols) if symbols is None else symbols,
            name_prefix=self.name_prefix,
        )
        other._functions = self._functions
        return other

    def symbol(self, name: str, value_type: GammaType | None = None) -> Any:
        r"""Cache a Z3 constant using the current Gamma value type."""
        if z3 is None:
            raise ExpressionError("z3-solver is not installed")
        if not is_hcsp_identifier(name):
            raise ExpressionError(
                f"Invalid expression symbol name: {name!r}"
            )
        if name in self.symbols:
            return self.symbols[name]
        actual_type = (
            gamma_value_type(self.gamma.get(name, BasicType.REAL))
            if value_type is None
            else gamma_value_type(value_type, subject="Symbol type")
        )
        value = self._fresh_scalar(name, actual_type)
        self.symbols[name] = value
        return value

    def fresh_symbol(self, name: str, value_type: GammaType, suffix: str) -> Any:
        r"""Create a fresh symbol without inserting it into the symbol table."""
        normalized = gamma_value_type(value_type, subject="Fresh symbol type")
        return self._fresh_scalar(f"{name}{suffix}", normalized)

    def _fresh_scalar(self, name: str, value_type: BasicType) -> Any:
        r"""Map a basic value type to a Z3 constant of the corresponding sort."""
        if z3 is None:
            raise ExpressionError("z3-solver is not installed")
        normalized = normalize_type(value_type, subject="Scalar type")
        full_name = f"{self.name_prefix}{name}"
        if normalized == BasicType.BOOL:
            return z3.Bool(full_name)
        if normalized in {BasicType.NAT, BasicType.INT}:
            return z3.Int(full_name)
        if normalized in {
            BasicType.RATIONAL,
            BasicType.REAL,
        }:
            return z3.Real(full_name)
        raise ExpressionError(f"Cannot create a Z3 scalar for {normalized}")

    def translate(
        self,
        value: ExprLike | Any,
        *,
        local_symbols: Mapping[str, Any] | None = None,
    ) -> ExprResult:
        r"""Translate an expression AST or an internally generated Z3 term."""
        if z3 is None:
            raise ExpressionError("z3-solver is not installed")
        locals_map = {} if local_symbols is None else dict(local_symbols)
        if _is_z3(value):
            return ExprResult(value, self._type_of_z3(value))
        try:
            expression = ensure_expr(value)
        except (TypeError, ValueError) as exc:
            raise ExpressionError(str(exc)) from exc
        return self._translate_expr(expression, locals_map)

    def boolean(
        self,
        value: ExprLike | Any,
        *,
        local_symbols: Mapping[str, Any] | None = None,
    ) -> Any:
        r"""Require translation to produce a Boolean formula."""
        result = self.boolean_result(value, local_symbols=local_symbols)
        return result.term

    def boolean_result(
        self,
        value: ExprLike | Any,
        *,
        local_symbols: Mapping[str, Any] | None = None,
    ) -> ExprResult:
        r"""Translate a Boolean formula with all definedness conditions."""

        result = self.translate(value, local_symbols=local_symbols)
        if result.value_type != BasicType.BOOL:
            raise ExpressionError(
                f"Expected Bool formula, got {result.value_type}: {value!r}"
            )
        return result

    def refinement(
        self,
        channel_type: ChannelType,
        value_terms: Sequence[Any],
    ) -> Any:
        r"""Instantiate joint channel refinement with all communicated scalar values."""

        return self.refinement_result(channel_type, value_terms).term

    def refinement_result(
        self,
        channel_type: ChannelType,
        value_terms: Sequence[Any],
    ) -> ExprResult:
        r"""Instantiate refinement while retaining definedness conditions."""

        terms = tuple(value_terms)
        if len(terms) != channel_type.arity:
            raise ExpressionError(
                "Channel refinement arity does not match communication payload"
            )
        refinement = channel_type.refinement
        if refinement is True:
            return ExprResult(z3.BoolVal(True), BasicType.BOOL)
        if refinement is False:
            return ExprResult(z3.BoolVal(False), BasicType.BOOL)
        if callable(refinement):
            try:
                produced = refinement(*terms)
            except Exception as exc:
                raise ExpressionError(
                    "Channel refinement callable failed for "
                    f"{len(terms)} payload slots: {exc}"
                ) from exc
            return self.boolean_result(produced)
        if _is_z3(refinement):
            substitutions: list[tuple[Any, Any]] = []
            for name, value_type, value_term in zip(
                channel_type.binders,
                channel_type.value_types,
                terms,
            ):
                binder = self.fresh_symbol(name, value_type, "")
                replacement = value_term
                if not binder.sort().eq(replacement.sort()):
                    # Promote Int to Real; do not implicitly coerce other sorts.
                    if z3.is_real(binder) and z3.is_int(replacement):
                        replacement = z3.ToReal(replacement)
                    else:
                        raise ExpressionError(
                            "Z3 refinement binder and payload have incompatible "
                            f"sorts at slot {len(substitutions) + 1}: "
                            f"{binder.sort()} and {replacement.sort()}"
                        )
                substitutions.append((binder, replacement))
            substituted = z3.substitute(refinement, *substitutions)
            if not z3.is_bool(substituted):
                raise ExpressionError("Channel refinement must be Boolean")
            return ExprResult(substituted, BasicType.BOOL)
        return self.boolean_result(
            refinement,
            local_symbols=dict(zip(channel_type.binders, terms)),
        )

    def _translate_expr(
        self,
        expression: Expr,
        local_symbols: Mapping[str, Any],
    ) -> ExprResult:
        r"""Dispatch translation by expression node kind."""
        if isinstance(expression, BinaryExpr):
            return self._translate_binary_expr(expression, local_symbols)
        if isinstance(expression, Literal):
            value = expression.value
            if isinstance(value, bool):
                return ExprResult(z3.BoolVal(value), BasicType.BOOL)
            if isinstance(value, int):
                value_type = BasicType.NAT if value >= 0 else BasicType.INT
                return ExprResult(z3.IntVal(value), value_type)
            if isinstance(value, (float, Decimal, Fraction)):
                return ExprResult(z3.RealVal(str(value)), BasicType.REAL)

        if isinstance(expression, Variable):
            if expression.name in local_symbols:
                value = local_symbols[expression.name]
                return ExprResult(value, self._type_of_z3(value))
            if (
                expression.name not in self.gamma
                and expression.name not in self.symbols
            ):
                raise ExpressionError(f"Unbound variable {expression.name!r}")
            value = self.symbol(expression.name)
            return ExprResult(
                value,
                gamma_value_type(
                    self.gamma.get(
                        expression.name,
                        self._type_of_z3(value),
                    )
                ),
            )

        if isinstance(expression, UnaryExpr):
            item = self._translate_expr(expression.operand, local_symbols)
            if expression.op == "not":
                self._require_bool(item)
                return ExprResult(
                    z3.Not(item.term),
                    BasicType.BOOL,
                    item.definedness,
                )
            self._require_numeric(item)
            if expression.op == "-":
                result_type = (
                    BasicType.INT
                    if item.value_type == BasicType.NAT
                    else item.value_type
                )
                return ExprResult(-item.term, result_type, item.definedness)
            return item

        if isinstance(expression, BooleanExpr):
            values = [
                self._translate_expr(item, local_symbols)
                for item in expression.operands
            ]
            for item in values:
                self._require_bool(item)
            constructor = z3.And if expression.op == "and" else z3.Or
            return ExprResult(
                constructor(*(item.term for item in values)),
                BasicType.BOOL,
                self._definedness_of(values),
            )

        if isinstance(expression, CompareExpr):
            left = self._translate_expr(expression.operands[0], local_symbols)
            comparisons = []
            operands = [left]
            for operator, right_expr in zip(
                expression.operators,
                expression.operands[1:],
            ):
                right = self._translate_expr(right_expr, local_symbols)
                if operator in {"==", "!="}:
                    if not (
                        is_subtype(left.value_type, right.value_type)
                        or is_subtype(right.value_type, left.value_type)
                    ):
                        raise ExpressionError(
                            f"Cannot compare {left.value_type} with "
                            f"{right.value_type}"
                        )
                else:
                    self._require_numeric(left)
                    self._require_numeric(right)
                operations = {
                    "==": lambda: left.term == right.term,
                    "!=": lambda: left.term != right.term,
                    "<": lambda: left.term < right.term,
                    "<=": lambda: left.term <= right.term,
                    ">": lambda: left.term > right.term,
                    ">=": lambda: left.term >= right.term,
                }
                comparisons.append(operations[operator]())
                left = right
                operands.append(right)
            return ExprResult(
                z3.And(*comparisons),
                BasicType.BOOL,
                self._definedness_of(operands),
            )

        if isinstance(expression, CallExpr):
            args = [
                self._translate_expr(item, local_symbols)
                for item in expression.arguments
            ]
            return self._translate_function(expression.name, args)

        raise ExpressionError(
            f"Unsupported project expression node: {type(expression).__name__}"
        )

    def _translate_binary_expr(
        self,
        expression: BinaryExpr,
        local_symbols: Mapping[str, Any],
    ) -> ExprResult:
        r"""Translate deep binary expression trees using an explicit postorder stack."""
        pending: list[tuple[Expr, bool]] = [(expression, False)]
        translated: dict[int, ExprResult] = {}

        while pending:
            current, exiting = pending.pop()
            if not isinstance(current, BinaryExpr):
                translated[id(current)] = self._translate_expr(
                    current,
                    local_symbols,
                )
                continue
            if not exiting:
                pending.append((current, True))
                pending.append((current.right, False))
                pending.append((current.left, False))
                continue

            # Shared immutable AST operands need cached results for every reference; popping
            # loses the second use.
            left = translated[id(current.left)]
            right = translated[id(current.right)]
            translated[id(current)] = self._combine_binary_results(
                current.op,
                left,
                right,
            )

        return translated[id(expression)]

    def _combine_binary_results(
        self,
        operator: str,
        left: ExprResult,
        right: ExprResult,
    ) -> ExprResult:
        r"""Combine operand results with arithmetic typing and definedness rules."""
        self._require_numeric(left)
        self._require_numeric(right)
        result_type = self._join_numeric(left.value_type, right.value_type)
        definedness = self._definedness_of((left, right))
        try:
            if operator == "+":
                term = left.term + right.term
            elif operator == "-":
                term = left.term - right.term
                if result_type == BasicType.NAT:
                    result_type = BasicType.INT
            elif operator == "*":
                term = left.term * right.term
            elif operator == "/":
                # Promote division operands to Real to avoid Z3 integer division.
                numerator = self._as_real(left.term)
                denominator = self._as_real(right.term)
                term = numerator / denominator
                result_type = BasicType.REAL
                definedness += (right.term != 0,)
            elif operator == "%":
                if left.value_type not in {BasicType.NAT, BasicType.INT} or (
                    right.value_type not in {BasicType.NAT, BasicType.INT}
                ):
                    raise ExpressionError(
                        "Modulo operands must both have Nat or Int type"
                    )
                term = left.term % right.term
                result_type = (
                    BasicType.NAT
                    if left.value_type == right.value_type == BasicType.NAT
                    else BasicType.INT
                )
                definedness += (right.term != 0,)
            else:
                term = left.term**right.term
                result_type = BasicType.REAL
        except ExpressionError:
            raise
        except z3.Z3Exception as exc:
            raise ExpressionError(
                f"Invalid operands for {operator!r}: {exc}"
            ) from exc
        return ExprResult(term, result_type, definedness)

    def _translate_function(
        self,
        name: str,
        args: Sequence[ExprResult],
    ) -> ExprResult:
        r"""Translate known math functions; model other numeric functions conservatively."""
        lower = name.lower()
        if lower == "sqrt" and len(args) == 1:
            self._require_numeric(args[0])
            argument = self._as_real(args[0].term)
            try:
                term = z3.Sqrt(argument)
            except z3.Z3Exception as exc:
                raise ExpressionError(f"Invalid sqrt argument: {exc}") from exc
            return ExprResult(
                term,
                BasicType.REAL,
                args[0].definedness + (argument >= 0,),
            )
        if lower == "abs" and len(args) == 1:
            self._require_numeric(args[0])
            return ExprResult(
                z3.Abs(args[0].term),
                args[0].value_type,
                args[0].definedness,
            )
        if lower in {"min", "max"} and len(args) >= 2:
            for item in args:
                self._require_numeric(item)
            result_type = args[0].value_type
            term = args[0].term
            for item in args[1:]:
                result_type = self._join_numeric(
                    result_type,
                    item.value_type,
                )
                condition = (
                    term <= item.term
                    if lower == "min"
                    else term >= item.term
                )
                term = z3.If(condition, term, item.term)
            return ExprResult(
                term,
                result_type,
                self._definedness_of(args),
            )
        for item in args:
            self._require_numeric(item)
        signature = tuple(str(item.value_type) for item in args)
        key = (name, signature, str(BasicType.REAL))
        if key not in self._functions:
            self._functions[key] = z3.Function(
                name,
                *(self._sort_for_type(item.value_type) for item in args),
                z3.RealSort(),
            )
        return ExprResult(
            self._functions[key](*(item.term for item in args)),
            BasicType.REAL,
            self._definedness_of(args),
        )

    @staticmethod
    def _definedness_of(values: Sequence[ExprResult]) -> tuple[Any, ...]:
        r"""Merge child definedness conditions in evaluation order."""

        return tuple(
            condition
            for value in values
            for condition in value.definedness
        )

    @staticmethod
    def _as_real(term: Any) -> Any:
        r"""Promote Z3 Int terms to Real."""

        return z3.ToReal(term) if z3.is_int(term) else term

    def _sort_for_type(self, value_type: BasicType) -> Any:
        r"""Select the Z3 sort for an uninterpreted function signature."""
        normalized = normalize_type(value_type)
        if normalized == BasicType.BOOL:
            return z3.BoolSort()
        if normalized in {BasicType.NAT, BasicType.INT}:
            return z3.IntSort()
        if normalized in {
            BasicType.RATIONAL,
            BasicType.REAL,
        }:
            return z3.RealSort()
        raise ExpressionError(
            f"Unsupported function argument type {normalized}"
        )

    @staticmethod
    def _require_bool(value: ExprResult) -> None:
        r"""Reject non-Boolean logical conditions."""
        if value.value_type != BasicType.BOOL:
            raise ExpressionError(f"Expected Bool, got {value.value_type}")

    @staticmethod
    def _require_numeric(value: ExprResult) -> None:
        r"""Reject nonnumeric arithmetic and ordering operands."""
        if value.value_type not in {
            BasicType.NAT,
            BasicType.INT,
            BasicType.RATIONAL,
            BasicType.REAL,
        }:
            raise ExpressionError(
                f"Expected numeric expression, got {value.value_type}"
            )

    @staticmethod
    def _join_numeric(left: BasicType, right: BasicType) -> BasicType:
        r"""Find the least common numeric type for binary arithmetic."""
        ranks = {
            BasicType.NAT: 0,
            BasicType.INT: 1,
            BasicType.RATIONAL: 2,
            BasicType.REAL: 3,
        }
        if left not in ranks or right not in ranks:
            raise ExpressionError(
                f"Expected numeric types, got {left} and {right}"
            )
        return max((left, right), key=lambda item: ranks[item])

    @staticmethod
    def _type_of_z3(value: Any) -> BasicType:
        r"""Recover the shared value type from a Z3 sort."""
        if z3.is_bool(value):
            return BasicType.BOOL
        if z3.is_int(value):
            return BasicType.INT
        if z3.is_real(value):
            return BasicType.REAL
        raise ExpressionError(f"Unsupported Z3 sort: {value.sort()}")


class Z3ProofEngine:
    r"""Prove validity by checking unsatisfiability of the negated formula."""

    def __init__(self, timeout_ms: int = 5_000) -> None:
        r"""Set the timeout used independently for each obligation."""
        if isinstance(timeout_ms, bool) or not isinstance(timeout_ms, int):
            raise TypeError("z3_timeout_ms must be an integer, not a Boolean")
        if not 0 <= timeout_ms <= 4_294_967_295:
            raise ValueError(
                "z3_timeout_ms must be between 0 and 4294967295; "
                "0 disables the timeout"
            )
        self.timeout_ms = timeout_ms

    def valid(self, formula: Any) -> tuple[Verdict, str]:
        r"""Decide universal validity with a counterexample or unknown reason."""
        if z3 is None:
            return Verdict.UNKNOWN, "z3-solver is not installed"
        if not z3.is_bool(formula):
            return Verdict.FALSE, f"proof obligation is not Boolean: {formula}"
        try:
            solver = z3.Solver()
            solver.set(timeout=self.timeout_ms)
            solver.add(z3.Not(z3.simplify(formula)))
            result = solver.check()
            if result == z3.unsat:
                return Verdict.TRUE, "negation is unsatisfiable"
            if result == z3.sat:
                return Verdict.FALSE, f"counterexample: {solver.model()}"
            return Verdict.UNKNOWN, solver.reason_unknown() or "Z3 returned unknown"
        except z3.Z3Exception as exc:
            return Verdict.UNKNOWN, f"Z3 validity query failed: {exc}"

    def satisfiable(self, formula: Any) -> tuple[Verdict, str]:
        r"""Check whether the shared parameter constraint has a satisfying valuation."""

        if z3 is None:
            return Verdict.UNKNOWN, "z3-solver is not installed"
        if not z3.is_bool(formula):
            return Verdict.FALSE, f"parameter constraint is not Boolean: {formula}"
        try:
            solver = z3.Solver()
            solver.set(timeout=self.timeout_ms)
            solver.add(z3.simplify(formula))
            result = solver.check()
            if result == z3.sat:
                return Verdict.TRUE, "constraint has at least one admissible assignment"
            if result == z3.unsat:
                return Verdict.FALSE, "constraint is unsatisfiable"
            return Verdict.UNKNOWN, solver.reason_unknown() or "Z3 returned unknown"
        except z3.Z3Exception as exc:
            return Verdict.UNKNOWN, f"Z3 satisfiability query failed: {exc}"

    def state_satisfies(
        self,
        formula: Any,
        state: Mapping[str, Any],
        symbols: Mapping[str, Any],
    ) -> tuple[Verdict, str]:
        r"""Check partial-state substitution using validity of phi[sigma]."""
        if z3 is None:
            return Verdict.UNKNOWN, "z3-solver is not installed"
        undeclared = set(state) - set(symbols)
        if undeclared:
            names = ", ".join(
                repr(name) for name in sorted(undeclared, key=repr)
            )
            return (
                Verdict.FALSE,
                "state contains variables not declared in Gamma: " + names,
            )
        substitutions = []
        try:
            for name, concrete in state.items():
                substitutions.append(
                    (symbols[name], self._concrete(concrete, symbols[name].sort()))
                )
        except (ExpressionError, TypeError, ValueError, z3.Z3Exception) as exc:
            return Verdict.FALSE, f"invalid concrete state value: {exc}"
        closed = (
            z3.simplify(z3.substitute(formula, *substitutions))
            if substitutions
            else formula
        )
        if z3.is_true(closed):
            return Verdict.TRUE, "the substituted path condition is true"
        if z3.is_false(closed):
            return Verdict.FALSE, "the substituted path condition is false"
        verdict, detail = self.valid(closed)
        if verdict == Verdict.TRUE:
            return (
                Verdict.TRUE,
                "the residual path condition is valid for every unspecified "
                f"state variable: {closed}",
            )
        if verdict == Verdict.FALSE:
            return (
                Verdict.FALSE,
                "the residual path condition is not valid: "
                f"{closed}; {detail}",
            )
        return (
            Verdict.UNKNOWN,
            "validity of the residual path condition is unknown: "
            f"{closed}; {detail}",
        )

    @staticmethod
    def _concrete(value: Any, sort: Any) -> Any:
        r"""Convert a Python state value to the target Z3 sort."""
        if sort.kind() == z3.Z3_BOOL_SORT:
            if type(value) is not bool:
                raise ExpressionError(
                    f"Boolean state value must be bool, got {value!r}"
                )
            return z3.BoolVal(value)
        if sort.kind() == z3.Z3_INT_SORT:
            if not isinstance(value, Integral) or isinstance(value, bool):
                raise ExpressionError(
                    f"Integer state value must be an integer, got {value!r}"
                )
            return z3.IntVal(value)
        if sort.kind() == z3.Z3_REAL_SORT:
            if not isinstance(value, (Real, Decimal, Fraction)) or isinstance(
                value,
                bool,
            ):
                raise ExpressionError(
                    f"Real state value must be numeric, got {value!r}"
                )
            return z3.RealVal(str(value))
        raise ExpressionError(f"Unsupported concrete state sort: {sort}")


def implies(left: Any, right: Any) -> Any:
    r"""Build implication, retaining a printable placeholder without Z3."""
    if z3 is None:
        return ("implies", left, right)
    return z3.Implies(left, right)


def conjunction(*items: Any) -> Any:
    r"""Build an n-ary conjunction."""
    if z3 is None:
        return ("and",) + items
    return z3.And(*items)


def negation(item: Any) -> Any:
    r"""Build logical negation."""
    if z3 is None:
        return ("not", item)
    return z3.Not(item)


def simplify(item: Any) -> Any:
    r"""Simplify with Z3 when available; otherwise retain the input."""
    if z3 is None:
        return item
    return z3.simplify(item)
