"""项目表达式 AST 到 Z3 的翻译与一阶逻辑证明基础设施。

公开 HCSP 节点在构造阶段已经把字符串和 Python 常量转换为项目自有
:class:`~hcsp_typechecker.expressions.Expr`。本模块因此只需要访问确定的节点
类型，不再根据外部对象类名或字段进行兼容性猜测。

Z3 项仍可在通道 callable refinement 和证明器内部出现，但它们不是 HCSP AST
的一部分。不支持的数学函数会被建模为未解释函数，以保持证明结论保守。

本模块同时服务于推导的两个不同阶段：``ExpressionTranslator`` 在规则展开阶段
确定性地产生带类型的 Z3 项和有定义性条件；``Z3ProofEngine`` 在所有规则展开
完成后判定收集到的具体 FOL 公式。它不综合路径谓词或赋值后置条件。T-Assign
已经由 ``checker.py`` 把右值项写入后继符号映射，因此传到这里的证明目标中不
存在等待 Z3 搜索的未知 ``phi'``。
"""

from __future__ import annotations

from dataclasses import dataclass
from decimal import Decimal
from fractions import Fraction
from numbers import Integral, Real
from typing import Any, Mapping, MutableMapping, Sequence

from .expressions import (
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
from .model import (
    BasicType,
    ChannelType,
    Verdict,
    is_subtype,
    normalize_type,
)

try:
    import z3  # type: ignore
except ImportError:  # pragma: no cover - exercised when dependency is absent
    # 包仍可导入；需要自动证明时返回 UNKNOWN 并说明依赖缺失。
    z3 = None


@dataclass(frozen=True)
class ExprResult:
    """表达式翻译结果：Z3 项、静态类型及求值有定义所需的条件。

    Z3 的除法和幂运算本身采用全函数语义，不能直接表达论文中“表达式求值
    失败”的情况。因此 ``definedness`` 单独保存诸如除数非零、平方根参数
    非负等侧条件；类型规则再把这些条件放入显式公式 premise 或演化域。
    """

    term: Any
    value_type: BasicType
    definedness: tuple[Any, ...] = ()


class ExpressionError(ValueError):
    """表达式无法解析、类型不匹配或使用了不支持的构造。"""

    pass


def z3_available() -> bool:
    """报告当前环境是否可以执行自动一阶逻辑证明。"""
    return z3 is not None


def _is_z3(value: Any) -> bool:
    """避免在未安装 Z3 时访问其类型对象。"""
    return z3 is not None and isinstance(value, z3.AstRef)


def lvalue_name(value: str | Variable) -> str:
    """提取项目标量左值的变量名。"""
    try:
        return ensure_variable(value).name
    except (TypeError, ValueError) as exc:
        raise ExpressionError(str(exc)) from exc


class ExpressionTranslator:
    """把项目表达式 AST 翻译为带类型的 Z3 项。

    一个 translator 对应一个 ``Gamma`` 和当前符号状态。控制流分支复制
    translator 的符号映射，使赋值和输入产生的状态更新不会跨分支泄漏。
    """

    def __init__(
        self,
        gamma: Mapping[str, BasicType],
        symbols: MutableMapping[str, Any] | None = None,
        *,
        name_prefix: str = "",
    ):
        """建立规范化变量环境，并可复用调用方提供的符号表。"""
        self.gamma = {
            str(name): normalize_type(value, subject="Gamma entry")
            for name, value in gamma.items()
        }
        self.symbols: MutableMapping[str, Any] = {} if symbols is None else symbols
        self.name_prefix = name_prefix
        self._functions: dict[tuple[str, tuple[str, ...], str], Any] = {}

    def clone(
        self,
        symbols: MutableMapping[str, Any] | None = None,
    ) -> "ExpressionTranslator":
        """复制分支局部符号状态，同时共享未解释函数声明。"""
        other = ExpressionTranslator(
            self.gamma,
            dict(self.symbols) if symbols is None else symbols,
            name_prefix=self.name_prefix,
        )
        other._functions = self._functions
        return other

    def symbol(self, name: str, value_type: BasicType | None = None) -> Any:
        """按需创建并缓存基础类型变量对应的 Z3 常量。"""
        if z3 is None:
            raise ExpressionError("z3-solver is not installed")
        name = str(name)
        if name in self.symbols:
            return self.symbols[name]
        actual_type = (
            self.gamma.get(name, BasicType.REAL)
            if value_type is None
            else normalize_type(value_type, subject="Symbol type")
        )
        value = self._fresh_scalar(name, actual_type)
        self.symbols[name] = value
        return value

    def fresh_symbol(self, name: str, value_type: BasicType, suffix: str) -> Any:
        """创建不写入当前符号表的新鲜符号。"""
        normalized = normalize_type(value_type, subject="Fresh symbol type")
        return self._fresh_scalar(f"{name}{suffix}", normalized)

    def _fresh_scalar(self, name: str, value_type: BasicType) -> Any:
        """把基础类型映射到一个 Z3 sort 并创建常量。"""
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
        """翻译项目表达式或证明器内部产生的 Z3 项。

        非 Z3 输入必须能够由 ``ensure_expr`` 转换成项目表达式；任意第三方
        对象会被明确拒绝，而不会按类名猜测其含义。
        """
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
        """翻译并强制要求结果为布尔公式。"""
        result = self.boolean_result(value, local_symbols=local_symbols)
        return result.term

    def boolean_result(
        self,
        value: ExprLike | Any,
        *,
        local_symbols: Mapping[str, Any] | None = None,
    ) -> ExprResult:
        """翻译布尔公式，同时保留其全部求值有定义条件。"""

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
        """把联合通道精化同时实例化到本次通信的全部标量值。"""

        return self.refinement_result(channel_type, value_terms).term

    def refinement_result(
        self,
        channel_type: ChannelType,
        value_terms: Sequence[Any],
    ) -> ExprResult:
        """实例化通道精化，并保留精化表达式的求值有定义条件。"""

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
                    # Int 可以安全提升到 Real；其他 sort 不执行隐式强制转换。
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
        """按项目表达式节点类型递归翻译。"""
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
                self.gamma.get(expression.name, self._type_of_z3(value)),
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

        if isinstance(expression, BinaryExpr):
            left = self._translate_expr(expression.left, local_symbols)
            right = self._translate_expr(expression.right, local_symbols)
            self._require_numeric(left)
            self._require_numeric(right)
            result_type = self._join_numeric(
                left.value_type,
                right.value_type,
            )
            definedness = self._definedness_of((left, right))
            try:
                if expression.op == "+":
                    term = left.term + right.term
                elif expression.op == "-":
                    term = left.term - right.term
                    if result_type == BasicType.NAT:
                        result_type = BasicType.INT
                elif expression.op == "*":
                    term = left.term * right.term
                elif expression.op == "/":
                    # ``/`` 是数学实数除法。若两个操作数都是 Z3 Int，必须先
                    # 提升为 Real，否则 Z3 会构造整数 Euclidean division。
                    numerator = self._as_real(left.term)
                    denominator = self._as_real(right.term)
                    term = numerator / denominator
                    result_type = BasicType.REAL
                    definedness += (right.term != 0,)
                elif expression.op == "%":
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
                    f"Invalid operands for {expression.op!r}: {exc}"
                ) from exc
            return ExprResult(term, result_type, definedness)

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

    def _translate_function(
        self,
        name: str,
        args: Sequence[ExprResult],
    ) -> ExprResult:
        """翻译已知数学函数，其他数值函数保守建模为未解释函数。"""
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
        """按求值顺序合并子表达式的有定义条件。"""

        return tuple(
            condition
            for value in values
            for condition in value.definedness
        )

    @staticmethod
    def _as_real(term: Any) -> Any:
        """把 Z3 Int 项显式提升到 Real，其他实数项保持不变。"""

        return z3.ToReal(term) if z3.is_int(term) else term

    def _sort_for_type(self, value_type: BasicType) -> Any:
        """返回值类型在未解释函数签名中对应的 Z3 sort。"""
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
        """拒绝把数值或字符串表达式误用为逻辑条件。"""
        if value.value_type != BasicType.BOOL:
            raise ExpressionError(f"Expected Bool, got {value.value_type}")

    @staticmethod
    def _require_numeric(value: ExprResult) -> None:
        """拒绝对非数值表达式应用算术或序关系运算。"""
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
        """计算二元算术结果所需的最小公共数值类型。"""
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
        """从 Z3 sort 反向恢复检查器值类型。"""
        if z3.is_bool(value):
            return BasicType.BOOL
        if z3.is_int(value):
            return BasicType.INT
        if z3.is_real(value):
            return BasicType.REAL
        raise ExpressionError(f"Unsupported Z3 sort: {value.sort()}")


class Z3ProofEngine:
    """用“否定式不可满足”判定一阶逻辑公式是否有效。"""

    def __init__(self, timeout_ms: int = 5_000):
        """设置每个证明义务独立使用的求解超时。"""
        self.timeout_ms = int(timeout_ms)

    def valid(self, formula: Any) -> tuple[Verdict, str]:
        """判定公式全称有效性，并附上反例或未知原因。"""
        if z3 is None:
            return Verdict.UNKNOWN, "z3-solver is not installed"
        if not z3.is_bool(formula):
            return Verdict.FALSE, f"proof obligation is not Boolean: {formula}"
        solver = z3.Solver()
        solver.set(timeout=self.timeout_ms)
        solver.add(z3.Not(z3.simplify(formula)))
        result = solver.check()
        if result == z3.unsat:
            return Verdict.TRUE, "negation is unsatisfiable"
        if result == z3.sat:
            return Verdict.FALSE, f"counterexample: {solver.model()}"
        return Verdict.UNKNOWN, solver.reason_unknown() or "Z3 returned unknown"

    def state_satisfies(
        self,
        formula: Any,
        state: Mapping[str, Any],
        symbols: Mapping[str, Any],
    ) -> tuple[Verdict, str]:
        """检查一个可能不完整的具体状态是否满足路径条件。"""
        if z3 is None:
            return Verdict.UNKNOWN, "z3-solver is not installed"
        substitutions = []
        try:
            for name, concrete in state.items():
                if name not in symbols:
                    continue
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
            return Verdict.TRUE, "state satisfies the path condition"
        if z3.is_false(closed):
            return Verdict.FALSE, "state violates the path condition"
        positive, _ = self.valid(closed)
        if positive == Verdict.TRUE:
            return (
                Verdict.TRUE,
                "path condition is valid for unspecified state variables",
            )
        negative, _ = self.valid(z3.Not(closed))
        if negative == Verdict.TRUE:
            return (
                Verdict.FALSE,
                "path condition is false for all unspecified state variables",
            )
        return (
            Verdict.UNKNOWN,
            f"state is partial; residual condition: {closed}",
        )

    @staticmethod
    def _concrete(value: Any, sort: Any) -> Any:
        """按目标符号 sort 把 Python 状态值转换为 Z3 常量。"""
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
    """构造蕴含；无 Z3 时保留可打印的结构化占位值。"""
    if z3 is None:
        return ("implies", left, right)
    return z3.Implies(left, right)


def conjunction(*items: Any) -> Any:
    """构造任意元合取。"""
    if z3 is None:
        return ("and",) + items
    return z3.And(*items)


def negation(item: Any) -> Any:
    """构造逻辑否定。"""
    if z3 is None:
        return ("not", item)
    return z3.Not(item)


def simplify(item: Any) -> Any:
    """在 Z3 可用时化简公式，否则原样返回。"""
    if z3 is None:
        return item
    return z3.simplify(item)
