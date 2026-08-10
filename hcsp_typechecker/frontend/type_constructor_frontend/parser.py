"""把规范 HCSP 用户输入转换为现有项目模型的递归下降解析器。

完整入口按 ``document/GAMMA_THETA_INPUT_SYNTAX.md`` 从同一 token 流中依次构造
Gamma、可选共享参数环境、Theta 和 Process AST；Process/Expr 子语法仍由
``document/HCSP_INPUT_SYNTAX.md`` 定义。语句块统一交给 ``Sequence.of`` lowering，
使内部选择后面的公共后继进入多元 ``InternalChoice.continuation``，
而不会形成项目禁止的外置 ``Sequence(InternalChoice(...), Q)`` 结构。
"""

from __future__ import annotations

from decimal import Decimal, DecimalException
from math import inf
from typing import Callable, TypeVar

from ...data_structures.process_ast.ast import (
    Assert,
    Assign,
    EventChoice,
    HCSP,
    If,
    InputChannel,
    InternalChoice,
    Mu,
    ODE,
    ODEAnnotation,
    OutputChannel,
    Parallel,
    Process,
    RecursionAnnotation,
    Sequence,
    Skip,
    Var,
)
from ...data_structures.process_ast.expressions import (
    BinaryExpr,
    BooleanExpr,
    CallExpr,
    CompareExpr,
    Expr,
    Literal,
    UnaryExpr,
    Variable,
)
from ...data_structures.runtime_context import (
    BasicType,
    ChannelType,
    ContinuousType,
    GammaType,
    ParameterEnvironment,
)
from .errors import HCSPInputError, SourcePosition
from .lexer import Token, tokenize
from .source import ParsedHCSPSource


_T = TypeVar("_T")
_COMPARISON_OPERATORS = frozenset({"==", "!=", "<", "<=", ">", ">=", "<->"})
_BASIC_TYPE_TOKENS = {
    "Bool": BasicType.BOOL,
    "Nat": BasicType.NAT,
    "Int": BasicType.INT,
    "Rational": BasicType.RATIONAL,
    "Real": BasicType.REAL,
}


class Parser:
    """在单一 token 序列上解析完整 source 或低层片段。"""

    def __init__(self, source: str, source_name: str) -> None:
        """扫描源文本并初始化语法游标。"""

        self.source = source
        self.source_name = source_name
        self.tokens = tokenize(source, source_name=source_name)
        self.index = 0

    def parse_source(self) -> HCSP:
        """解析低层非空 Process 系统片段，并要求随后为 EOF。"""

        process = self._parse_process_system()
        self._expect("EOF")
        return process

    def parse_complete_source(self) -> ParsedHCSPSource:
        """从同一 token 流解析环境与 Process 的完整输入。"""

        gamma = self._parse_gamma_section()
        parameters = (
            self._parse_parameter_section(forbidden_names=frozenset(gamma))
            if self.current.kind == "parameters"
            else ParameterEnvironment()
        )
        theta = self._parse_theta_section()
        self._expect("process")
        process = self._parse_process_system(
            shared_parameters=frozenset(parameters.declarations),
        )
        self._expect("EOF")
        return ParsedHCSPSource(
            gamma=gamma,
            theta=theta,
            process=process,
            parameters=parameters,
        )

    def parse_complete_source_without_eof(self) -> ParsedHCSPSource:
        """解析完整构造器输入，但把 EOF 留给可选的 ``type`` 分节。"""

        gamma = self._parse_gamma_section()
        parameters = (
            self._parse_parameter_section(forbidden_names=frozenset(gamma))
            if self.current.kind == "parameters"
            else ParameterEnvironment()
        )
        theta = self._parse_theta_section()
        self._expect("process")
        process = self._parse_process_system(
            shared_parameters=frozenset(parameters.declarations),
        )
        return ParsedHCSPSource(
            gamma=gamma,
            theta=theta,
            process=process,
            parameters=parameters,
        )

    def _parse_process_system(
        self,
        *,
        shared_parameters: frozenset[str] = frozenset(),
    ) -> HCSP:
        """解析非空顶层块列表，并 lower 为 Process 或 Parallel。"""

        start = self._expect("{")
        if self.current.kind != "{":
            raise self._syntax_error(
                "source must contain at least one statement block",
                expected=("{",),
            )
        blocks = [self._parse_statement_block()]
        while self._match(",") is not None:
            if self.current.kind == "}":
                raise self._syntax_error(
                    "trailing comma is not allowed in the source block list",
                    expected=("{",),
                )
            blocks.append(self._parse_statement_block())
        self._expect("}")
        if len(blocks) == 1:
            return blocks[0]
        return self._construct(
            start,
            lambda: Parallel.of(
                *blocks,
                shared_parameters=shared_parameters,
            ),
        )

    def _parse_gamma_section(self) -> dict[str, GammaType]:
        """解析 Gamma，在读完后验证所有连续向量的 Real 成员声明。"""

        self._expect("gamma")
        self._expect("(")
        gamma: dict[str, GammaType] = {}
        continuous_entries: list[tuple[Token, tuple[Token, ...]]] = []

        if self.current.kind != ")":
            while True:
                declaration = self._expect("IDENT")
                if declaration.text in gamma:
                    raise self._validation_error(
                        f"duplicate Gamma declaration {declaration.text!r}",
                        declaration,
                    )
                self._expect(":")
                value, members = self._parse_gamma_type()
                gamma[declaration.text] = value
                if members is not None:
                    continuous_entries.append((declaration, members))

                if self._match(",") is None:
                    break
                if self.current.kind == ")":
                    raise self._syntax_error(
                        "trailing comma is not allowed in gamma",
                        expected=("Gamma declaration",),
                    )
        self._expect(")")

        # continuous 成员可以在向量声明之后才定型，因此必须等整个
        # Gamma 读完后再检查，不能错误拒绝合法的向前引用。
        for declaration, members in continuous_entries:
            for member in members:
                member_type = gamma.get(member.text)
                if member_type is None:
                    raise self._validation_error(
                        f"continuous declaration {declaration.text!r} references "
                        f"missing Gamma scalar {member.text!r}",
                        member,
                    )
                if member_type is not BasicType.REAL:
                    raise self._validation_error(
                        f"continuous declaration {declaration.text!r} requires "
                        f"member {member.text!r} to have type Real; got "
                        f"{member_type}",
                        member,
                    )
        return gamma

    def _parse_gamma_type(
        self,
    ) -> tuple[GammaType, tuple[Token, ...] | None]:
        """解析一个基础类型或非空 ``continuous(...)`` 声明。"""

        if self.current.kind in _BASIC_TYPE_TOKENS:
            token = self._advance()
            return _BASIC_TYPE_TOKENS[token.kind], None
        if self.current.kind != "continuous":
            raise self._syntax_error(
                f"expected a Gamma type, found {self.current.display}",
                expected=tuple(_BASIC_TYPE_TOKENS) + ("continuous",),
            )

        start = self._advance()
        self._expect("(")
        if self.current.kind == ")":
            raise self._syntax_error(
                "continuous declaration must contain at least one member",
                expected=("IDENT",),
            )
        members: list[Token] = []
        seen: set[str] = set()
        while True:
            member = self._expect("IDENT")
            if member.text == "t":
                raise self._validation_error(
                    "implicit ODE clock 't' cannot be a continuous vector member",
                    member,
                )
            if member.text in seen:
                raise self._validation_error(
                    f"duplicate continuous vector member {member.text!r}",
                    member,
                )
            seen.add(member.text)
            members.append(member)
            if self._match(",") is None:
                break
            if self.current.kind == ")":
                raise self._syntax_error(
                    "trailing comma is not allowed in continuous member lists",
                    expected=("IDENT",),
                )
        self._expect(")")
        value = self._construct(
            start,
            lambda: ContinuousType(tuple(member.text for member in members)),
        )
        return value, tuple(members)

    def _parse_theta_section(self) -> dict[str, ChannelType]:
        """解析 Theta 并将每项直接 lowering 为现有 ``ChannelType``。"""

        self._expect("theta")
        self._expect("(")
        theta: dict[str, ChannelType] = {}
        if self.current.kind != ")":
            while True:
                declaration = self._expect("IDENT")
                if declaration.text in theta:
                    raise self._validation_error(
                        f"duplicate Theta declaration {declaration.text!r}",
                        declaration,
                    )
                self._expect(":")
                theta[declaration.text] = self._parse_channel_type()

                if self._match(",") is None:
                    break
                if self.current.kind == ")":
                    raise self._syntax_error(
                        "trailing comma is not allowed in theta",
                        expected=("Theta declaration",),
                    )
        self._expect(")")
        return theta

    def _parse_channel_type(self) -> ChannelType:
        """解析非空多标量通道签名与可选联合 refinement。"""

        start = self._expect("channel")
        self._expect("(")
        if self.current.kind == ")":
            raise self._syntax_error(
                "channel declaration must contain at least one payload slot",
                expected=("channel slot",),
            )

        binders: list[str] = []
        value_types: list[BasicType] = []
        seen: set[str] = set()
        while True:
            binder = self._expect("IDENT")
            if binder.text in seen:
                raise self._validation_error(
                    f"duplicate channel refinement binder {binder.text!r}",
                    binder,
                )
            seen.add(binder.text)
            binders.append(binder.text)
            self._expect(":")
            value_types.append(self._parse_basic_type())
            if self._match(",") is None:
                break
            if self.current.kind == ")":
                raise self._syntax_error(
                    "trailing comma is not allowed in channel slot lists",
                    expected=("channel slot",),
                )
        self._expect(")")

        refinement: bool | Expr = True
        if self._match("where") is not None:
            self._expect("(")
            parsed_refinement = self._parse_expression()
            self._expect(")")
            # 省略 where 和显式 where(true) 使用唯一的内部表示；其他公式
            # 始终保留为项目 Expr，而不接受字符串/callable/Z3 便捷值。
            if not (
                isinstance(parsed_refinement, Literal)
                and parsed_refinement.value is True
            ):
                refinement = parsed_refinement

        return self._construct(
            start,
            lambda: ChannelType(
                tuple(value_types),
                refinement=refinement,
                binders=tuple(binders),
            ),
        )

    def _parse_basic_type(self) -> BasicType:
        """解析用户输入层唯一的五种规范基础类型名。"""

        token = self.current
        if token.kind not in _BASIC_TYPE_TOKENS:
            raise self._syntax_error(
                f"expected a basic type, found {token.display}",
                expected=tuple(_BASIC_TYPE_TOKENS),
            )
        self._advance()
        return _BASIC_TYPE_TOKENS[token.kind]

    def _parse_parameter_section(
        self,
        *,
        forbidden_names: frozenset[str],
    ) -> ParameterEnvironment:
        """解析可选共享只读参数声明及其联合约束。"""

        self._expect("parameters")
        self._expect("(")
        declarations: dict[str, BasicType] = {}
        if self.current.kind != ")":
            while True:
                declaration = self._expect("IDENT")
                if declaration.text in declarations:
                    raise self._validation_error(
                        f"duplicate parameter declaration "
                        f"{declaration.text!r}",
                        declaration,
                    )
                if declaration.text in forbidden_names:
                    raise self._validation_error(
                        "Gamma and the shared parameter environment "
                        f"overlap at {declaration.text!r}",
                        declaration,
                    )
                self._expect(":")
                declarations[declaration.text] = self._parse_basic_type()
                if self._match(",") is None:
                    break
                if self.current.kind == ")":
                    raise self._syntax_error(
                        "trailing comma is not allowed in parameters",
                        expected=("parameter declaration",),
                    )
        self._expect(")")

        constraint: bool | Expr = True
        where_token = self._match("where")
        if where_token is not None:
            self._expect("(")
            parsed_constraint = self._parse_expression()
            self._expect(")")
            unknown_names = (
                parsed_constraint.get_vars() - set(declarations)
            )
            if unknown_names:
                raise self._validation_error(
                    "shared parameter constraint references undeclared "
                    "names: " + ", ".join(sorted(unknown_names)),
                    where_token,
                )
            if not (
                isinstance(parsed_constraint, Literal)
                and parsed_constraint.value is True
            ):
                constraint = parsed_constraint

        return ParameterEnvironment(declarations, constraint)

    def parse_expression_source(self) -> Expr:
        """解析一个独立表达式并要求其后立即到达 EOF。"""

        expression = self._parse_expression()
        self._expect("EOF")
        return expression

    @property
    def current(self) -> Token:
        """返回尚未消费的当前 token。"""

        return self.tokens[self.index]

    def _parse_statement_block(self) -> Process:
        """解析非空语句块，并用唯一顺序规范形组合全部语句。"""

        start = self._expect("{")
        if self.current.kind == "}":
            raise self._syntax_error(
                "statement block cannot be empty; use skip for no behavior",
                expected=("statement",),
            )
        statements = [self._parse_statement()]
        while self._match(";") is not None:
            if self.current.kind in {";", "}"}:
                raise self._syntax_error(
                    "semicolon must be followed by another statement",
                    expected=("statement",),
                )
            statements.append(self._parse_statement())
        self._expect("}")
        return self._construct(start, lambda: Sequence.of(*statements))

    def _parse_statement(self) -> Process:
        """按首 token 分派并解析一条完整 Process 语句。"""

        kind = self.current.kind
        if kind == "skip":
            token = self._advance()
            return self._construct(token, Skip)
        if kind == "IDENT":
            return self._parse_identifier_statement()
        if kind == "assert":
            return self._parse_assertion()
        if kind == "call":
            return self._parse_process_call()
        if kind == "if":
            return self._parse_if()
        if kind == "choose":
            return self._parse_choice()
        if kind == "mu":
            return self._parse_recursion()
        if kind == "ode":
            return self._parse_ode()
        raise self._syntax_error(
            f"expected a statement, found {self.current.display}",
            expected=("statement",),
        )

    def _parse_identifier_statement(self) -> Process:
        """解析以普通标识符开始的赋值、输入或输出动作。"""

        name = self._expect("IDENT")
        if self._match(":=") is not None:
            expression = self._parse_expression()
            return self._construct(
                name,
                lambda: Assign(name.text, expression),
            )
        if self._match("?") is not None:
            targets = self._parse_identifier_arguments()
            return self._construct(
                name,
                lambda: InputChannel(name.text, targets),
            )
        if self._match("!") is not None:
            payloads = self._parse_expression_arguments(allow_trailing=False)
            return self._construct(
                name,
                lambda: OutputChannel(name.text, payloads),
            )
        raise self._syntax_error(
            "identifier at statement start must be followed by :=, ? or !",
            expected=(":=", "?", "!"),
        )

    def _parse_assertion(self) -> Process:
        """解析 ``assert(expr)``。"""

        start = self._expect("assert")
        self._expect("(")
        condition = self._parse_expression()
        self._expect(")")
        return self._construct(start, lambda: Assert(condition))

    def _parse_process_call(self) -> Process:
        """解析显式进程变量调用 ``call X``。"""

        start = self._expect("call")
        variable = self._expect("IDENT")
        return self._construct(start, lambda: Var(variable.text))

    def _parse_if(self) -> Process:
        """解析具有两个必填语句块分支的条件语句。"""

        start = self._expect("if")
        self._expect("(")
        condition = self._parse_expression()
        self._expect(")")
        then_branch = self._parse_statement_block()
        self._expect("else")
        else_branch = self._parse_statement_block()
        return self._construct(
            start,
            lambda: If(condition, then_branch, else_branch),
        )

    def _parse_choice(self) -> Process:
        """解析至少两个内部选择分支并建立无公共尾的初始选择节点。"""

        start = self._expect("choose")
        branches = [self._parse_statement_block()]
        self._expect("or")
        branches.append(self._parse_statement_block())
        while self._match("or") is not None:
            branches.append(self._parse_statement_block())
        return self._construct(start, lambda: InternalChoice.of(*branches))

    def _parse_recursion(self) -> Process:
        """解析带必填边界不变量的 ``mu`` 递归。"""

        start = self._expect("mu")
        variable = self._expect("IDENT")
        self._expect("invariant")
        self._expect("(")
        invariant = self._parse_expression()
        self._expect(")")
        body = self._parse_statement_block()
        return self._construct(
            start,
            lambda: Mu(
                variable.text,
                body,
                annotation=RecursionAnnotation(invariant),
            ),
        )

    def _parse_ode(self) -> Process:
        """解析固定顺序、带可选 safety/interrupt 的 ODE 配置。"""

        start = self._expect("ode")
        self._expect("(")
        equations = self._parse_flow_clause()
        self._expect(",")
        domain = self._parse_named_expression("domain")
        self._expect(",")
        safety: Expr = Literal(True)
        if self.current.kind == "safety":
            safety = self._parse_named_expression("safety")
            self._expect(",")
        delay, delay_token = self._parse_delay_clause()
        interrupts = None
        if self._match(",") is not None:
            interrupts = self._parse_interrupt_clause()
        self._expect(")")
        annotation = self._construct(
            delay_token,
            lambda: ODEAnnotation(safety=safety, delay=delay),
        )
        return self._construct(
            start,
            lambda: ODE(
                equations,
                domain,
                interrupts,
                annotation=annotation,
            ),
        )

    def _parse_flow_clause(self) -> tuple[tuple[str, Expr], ...]:
        """解析保持书写顺序的零个或多个 ``dot x = e`` 方程。"""

        self._expect("flow")
        self._expect("(")
        equations: list[tuple[str, Expr]] = []
        names: set[str] = set()
        if self.current.kind != ")":
            while True:
                self._expect("dot")
                variable = self._expect("IDENT")
                if variable.text == "t":
                    raise self._validation_error(
                        "ODE variable 't' is reserved for the implicit local clock",
                        variable,
                    )
                if variable.text in names:
                    raise self._validation_error(
                        f"duplicate ODE equation for {variable.text!r}",
                        variable,
                    )
                names.add(variable.text)
                self._expect("=")
                equations.append((variable.text, self._parse_expression()))
                if self._match(",") is None:
                    break
        self._expect(")")
        return tuple(equations)

    def _parse_named_expression(self, name: str) -> Expr:
        """解析 ``name(expr)`` 形式的单表达式 ODE clause。"""

        self._expect(name)
        self._expect("(")
        expression = self._parse_expression()
        self._expect(")")
        return expression

    def _parse_delay_clause(self) -> tuple[Expr | float, Token]:
        """解析有限有理常量或正无穷 ODE delay。"""

        self._expect("delay")
        self._expect("(")
        duration_token = self.current
        if self._match("inf") is not None:
            duration: Expr | float = inf
        else:
            duration = self._parse_rational_expression()
        self._expect(")")
        return duration, duration_token

    def _parse_interrupt_clause(self):
        """解析非空中断分支表并构造递归 EventReaction。"""

        start = self._expect("interrupt")
        self._expect("(")
        if self.current.kind == ")":
            raise self._syntax_error(
                "interrupt must contain at least one event branch",
                expected=("on",),
            )
        branches = [self._parse_event_branch()]
        while self._match(",") is not None:
            branches.append(self._parse_event_branch())
        self._expect(")")
        return self._construct(start, lambda: EventChoice.of(*branches))

    def _parse_event_branch(
        self,
    ) -> tuple[InputChannel | OutputChannel, Process]:
        """解析一个通信守卫及其专属语句块后继。"""

        self._expect("on")
        channel = self._expect("IDENT")
        if self._match("?") is not None:
            targets = self._parse_identifier_arguments()
            communication = self._construct(
                channel,
                lambda: InputChannel(channel.text, targets),
            )
        elif self._match("!") is not None:
            payloads = self._parse_expression_arguments(allow_trailing=False)
            communication = self._construct(
                channel,
                lambda: OutputChannel(channel.text, payloads),
            )
        else:
            raise self._syntax_error(
                "event branch channel must be followed by ? or !",
                expected=("?", "!"),
            )
        continuation = self._parse_statement_block()
        return communication, continuation

    def _parse_identifier_arguments(self) -> tuple[str, ...]:
        """解析非空、无尾逗号且目标互异的输入变量列表。"""

        self._expect("(")
        first = self._expect("IDENT")
        values = [first.text]
        seen = {first.text}
        while self._match(",") is not None:
            item = self._expect("IDENT")
            if item.text in seen:
                raise self._validation_error(
                    f"duplicate input target {item.text!r}",
                    item,
                )
            seen.add(item.text)
            values.append(item.text)
        self._expect(")")
        return tuple(values)

    def _parse_expression_arguments(
        self,
        *,
        allow_trailing: bool,
    ) -> tuple[Expr, ...]:
        """解析非空表达式参数表，并按上下文决定是否允许尾逗号。"""

        self._expect("(")
        if self.current.kind == ")":
            raise self._syntax_error(
                "communication payload list cannot be empty",
                expected=("expression",),
            )
        values = [self._parse_expression()]
        while self._match(",") is not None:
            if self.current.kind == ")":
                if allow_trailing:
                    break
                raise self._syntax_error(
                    "trailing comma is not allowed in communication arguments",
                    expected=("expression",),
                )
            values.append(self._parse_expression())
        self._expect(")")
        return tuple(values)

    def _parse_expression(self) -> Expr:
        """解析统一、后续再进行值类型检查的表达式。"""

        return self._parse_or_expression()

    def _parse_or_expression(self) -> Expr:
        """解析 ``or``/``||`` 层并构造规范多元 BooleanExpr。"""

        operands = [self._parse_and_expression()]
        while self.current.kind in {"or", "||"}:
            self._advance()
            operands.append(self._parse_and_expression())
        return operands[0] if len(operands) == 1 else BooleanExpr("or", operands)

    def _parse_and_expression(self) -> Expr:
        """解析 ``and``/``&&`` 层并构造规范多元 BooleanExpr。"""

        operands = [self._parse_not_expression()]
        while self.current.kind in {"and", "&&"}:
            self._advance()
            operands.append(self._parse_not_expression())
        return operands[0] if len(operands) == 1 else BooleanExpr("and", operands)

    def _parse_not_expression(self) -> Expr:
        """解析低于比较、高于 and 的逻辑否定。"""

        if self.current.kind in {"not", "!"}:
            self._advance()
            return UnaryExpr("not", self._parse_not_expression())
        return self._parse_comparison_expression()

    def _parse_comparison_expression(self) -> Expr:
        """解析零个或多个关系运算，并保留单个链式 CompareExpr。"""

        operands = [self._parse_additive_expression()]
        operators: list[str] = []
        while self.current.kind in _COMPARISON_OPERATORS:
            operator = self._advance().kind
            operators.append("==" if operator == "<->" else operator)
            operands.append(self._parse_additive_expression())
        return operands[0] if not operators else CompareExpr(operands, operators)

    def _parse_additive_expression(self) -> Expr:
        """按左结合解析加法和减法。"""

        result = self._parse_multiplicative_expression()
        while self.current.kind in {"+", "-"}:
            operator = self._advance().kind
            result = BinaryExpr(
                operator,
                result,
                self._parse_multiplicative_expression(),
            )
        return result

    def _parse_multiplicative_expression(self) -> Expr:
        """按左结合解析乘法、实除法和取模。"""

        result = self._parse_unary_expression()
        while self.current.kind in {"*", "/", "%"}:
            operator = self._advance().kind
            result = BinaryExpr(operator, result, self._parse_unary_expression())
        return result

    def _parse_unary_expression(self) -> Expr:
        """解析算术正负号，并保持乘方高于左侧一元符号。"""

        if self.current.kind in {"+", "-"}:
            operator = self._advance().kind
            return UnaryExpr(operator, self._parse_unary_expression())
        return self._parse_power_expression()

    def _parse_power_expression(self) -> Expr:
        """把 ``**`` 和 ``^`` 都按高优先级右结合乘方解析。"""

        left = self._parse_primary_expression()
        if self.current.kind in {"**", "^"}:
            self._advance()
            return BinaryExpr("**", left, self._parse_unary_expression())
        return left

    def _parse_primary_expression(self) -> Expr:
        """解析字面量、变量、简单函数调用或括号分组。"""

        token = self.current
        if token.kind == "INTEGER":
            self._advance()
            return self._numeric_literal(token)
        if token.kind == "REAL":
            self._advance()
            return self._numeric_literal(token)
        if token.kind in {"true", "false"}:
            self._advance()
            return Literal(token.kind == "true")
        if token.kind == "IDENT":
            self._advance()
            if self.current.kind != "(":
                return Variable(token.text)
            arguments = self._parse_function_arguments()
            return CallExpr(token.text, arguments)
        if self._match("(") is not None:
            expression = self._parse_expression()
            self._expect(")")
            return expression
        raise self._syntax_error(
            f"expected an expression, found {token.display}",
            expected=("literal", "identifier", "("),
        )

    def _parse_function_arguments(self) -> tuple[Expr, ...]:
        """解析允许空表和尾逗号的简单函数位置实参。"""

        self._expect("(")
        if self._match(")") is not None:
            return ()
        arguments = [self._parse_expression()]
        while self._match(",") is not None:
            if self._match(")") is not None:
                return tuple(arguments)
            arguments.append(self._parse_expression())
        self._expect(")")
        return tuple(arguments)

    def _parse_rational_expression(self) -> Expr:
        """解析仅含有理数字面量和允许算术运算的常量表达式。"""

        return self._parse_rational_additive()

    def _parse_rational_additive(self) -> Expr:
        """按左结合解析有理常量加减法。"""

        result = self._parse_rational_multiplicative()
        while self.current.kind in {"+", "-"}:
            operator = self._advance().kind
            result = BinaryExpr(
                operator,
                result,
                self._parse_rational_multiplicative(),
            )
        return result

    def _parse_rational_multiplicative(self) -> Expr:
        """按左结合解析有理常量乘除法。"""

        result = self._parse_rational_unary()
        while self.current.kind in {"*", "/"}:
            operator = self._advance().kind
            result = BinaryExpr(operator, result, self._parse_rational_unary())
        return result

    def _parse_rational_unary(self) -> Expr:
        """解析有理常量表达式的一元正负号。"""

        if self.current.kind in {"+", "-"}:
            operator = self._advance().kind
            return UnaryExpr(operator, self._parse_rational_unary())
        return self._parse_rational_power()

    def _parse_rational_power(self) -> Expr:
        """按右结合解析有理常量乘方。"""

        left = self._parse_rational_primary()
        if self.current.kind in {"**", "^"}:
            self._advance()
            return BinaryExpr("**", left, self._parse_rational_unary())
        return left

    def _parse_rational_primary(self) -> Expr:
        """解析数值字面量或括号包围的有理常量表达式。"""

        token = self.current
        if token.kind == "INTEGER":
            self._advance()
            return self._numeric_literal(token)
        if token.kind == "REAL":
            self._advance()
            return self._numeric_literal(token)
        if self._match("(") is not None:
            expression = self._parse_rational_expression()
            self._expect(")")
            return expression
        raise self._syntax_error(
            "duration must be a constant rational expression",
            expected=("numeric literal", "("),
        )

    def _numeric_literal(self, token: Token) -> Literal:
        """把已通过词法限制的数字 token 安全转换为项目 Literal。"""

        try:
            value = (
                int(token.text)
                if token.kind == "INTEGER"
                else Decimal(token.text)
            )
            return Literal(value)
        except (DecimalException, OverflowError, ValueError) as exc:
            error = self._validation_error(
                f"numeric literal cannot be represented: {token.text!r}",
                token,
            )
            raise error from exc

    def _construct(
        self,
        token: Token,
        factory: Callable[[], _T],
    ) -> _T:
        """运行正式 AST 构造器，并把良构失败包装为定位诊断。"""

        try:
            return factory()
        except HCSPInputError:
            raise
        except (TypeError, ValueError) as exc:
            error = HCSPInputError(
                str(exc),
                phase="validation",
                source_name=self.source_name,
                source=self.source,
                position=token.position,
                found=token.text,
            )
            raise error from exc

    def _advance(self) -> Token:
        """消费并返回当前 token。"""

        token = self.current
        if token.kind != "EOF":
            self.index += 1
        return token

    def _match(self, *kinds: str) -> Token | None:
        """当前 token 属于给定集合时消费它，否则保持游标不变。"""

        if self.current.kind not in kinds:
            return None
        return self._advance()

    def _expect(self, kind: str) -> Token:
        """要求并消费指定 token，否则抛出带期望信息的语法错误。"""

        token = self.current
        if token.kind != kind:
            raise self._syntax_error(
                f"expected {kind!r}, found {token.display}",
                expected=(kind,),
            )
        return self._advance()

    def _syntax_error(
        self,
        message: str,
        *,
        expected: tuple[str, ...] = (),
    ) -> HCSPInputError:
        """在当前 token 处建立语法阶段异常。"""

        token = self.current
        return HCSPInputError(
            message,
            phase="syntax",
            source_name=self.source_name,
            source=self.source,
            position=token.position,
            found=None if token.kind == "EOF" else token.text,
            expected=expected,
        )

    def _validation_error(self, message: str, token: Token) -> HCSPInputError:
        """在指定 token 处建立 lowering/AST 良构异常。"""

        return HCSPInputError(
            message,
            phase="validation",
            source_name=self.source_name,
            source=self.source,
            position=token.position,
            found=token.text,
        )


def _checked_source(source: object, source_name: str) -> str:
    """把公共入口的非字符串参数转换成一致的词法诊断。"""

    if isinstance(source, str):
        return source
    raise HCSPInputError(
        "HCSP source must be a string",
        phase="lexical",
        source_name=source_name,
        source="",
        position=SourcePosition(0, 1, 1),
        found=type(source).__name__,
    )


def parse_hcsp(source: str, *, source_name: str = "<input>") -> HCSP:
    """把一个 Process 系统片段转换为 Process/Parallel AST。"""

    return Parser(_checked_source(source, source_name), source_name).parse_source()


def parse_hcsp_source(
    source: str,
    *,
    source_name: str = "<input>",
) -> ParsedHCSPSource:
    """解析完整环境与 Process 输入并返回现有模型。"""

    return Parser(
        _checked_source(source, source_name),
        source_name,
    ).parse_complete_source()


def parse_expression(source: str, *, source_name: str = "<expression>") -> Expr:
    """用用户输入前端的严格表达式文法构造一个项目 Expr。"""

    return Parser(
        _checked_source(source, source_name),
        source_name,
    ).parse_expression_source()
