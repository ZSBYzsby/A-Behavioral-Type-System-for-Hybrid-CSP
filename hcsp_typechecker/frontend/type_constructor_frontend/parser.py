r"""Recursive-descent input parsing with explicit stacks for deep process structure."""

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
from ..errors import HCSPInputError, SourcePosition
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
    r"""Parse complete input or fragments on one token stream."""

    def __init__(self, source: str, source_name: str) -> None:
        r"""Tokenize source and initialize the parser cursor."""

        self.source = source
        self.source_name = source_name
        self.tokens = tokenize(source, source_name=source_name)
        self.index = 0

    def parse_source(self) -> HCSP:
        r"""Parse a nonempty process-system fragment followed by EOF."""

        process = self._parse_process_system()
        self._expect("EOF")
        return process

    def parse_complete_source(self) -> ParsedHCSPSource:
        r"""Parse complete environments and Process on one token stream."""

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
        r"""Parse a program prefix, leaving a possible type section unconsumed."""

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
        r"""Lower nonempty top-level process blocks into Process or Parallel."""

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
        r"""Parse Gamma and validate Real members of continuous vectors."""

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

        # Validate continuous-vector members after parsing all Gamma entries to permit forward
        # references.
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
        r"""Parse a basic type or nonempty continuous declaration."""

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
        r"""Parse Theta entries directly into ChannelType."""

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
        r"""Parse a nonempty scalar channel signature and optional joint refinement."""

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
            # Canonicalize omitted where as true; other refinements remain strict Expr objects.
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
        r"""Parse one of the five supported basic type names."""

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
        r"""Parse optional shared read-only parameters and their joint constraint."""

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
        r"""Parse a standalone expression followed by EOF."""

        expression = self._parse_expression()
        self._expect("EOF")
        return expression

    @property
    def current(self) -> Token:
        r"""Return the current unconsumed token."""

        return self.tokens[self.index]

    def _parse_statement_block(self) -> Process:
        r"""Parse nonempty blocks and deep control structures using explicit tasks."""

        values: list[Process] = []
        pending: list[tuple[object, ...]] = [("block",)]
        while pending:
            task = pending.pop()
            tag = task[0]
            if tag == "expect":
                self._expect(task[1])
                continue
            if tag == "finish-control":
                _, kind, start, token, payload = task
                children = tuple(values[start:])
                del values[start:]
                if kind == "if":
                    built = self._construct(
                        token, lambda: If(payload, children[0], children[1])
                    )
                elif kind == "mu":
                    variable, invariant = payload
                    built = self._construct(
                        token,
                        lambda: Mu(
                            variable,
                            children[0],
                            annotation=RecursionAnnotation(invariant),
                        ),
                    )
                else:
                    raise RuntimeError(f"unsupported control task: {kind}")
                values.append(built)
                continue
            if tag == "choice-more":
                _, start, token = task
                if self._match("or") is not None:
                    pending.append(task)
                    pending.append(("block",))
                    continue
                branches = tuple(values[start:])
                del values[start:]
                values.append(
                    self._construct(token, lambda: InternalChoice.of(*branches))
                )
                continue
            if tag == "block-more":
                _, start, block_token, statement_tokens = task
                if self._match(";") is not None:
                    if self.current.kind in {";", "}"}:
                        raise self._syntax_error(
                            "semicolon must be followed by another statement",
                            expected=("statement",),
                        )
                    statement_tokens.append(self.current)
                    pending.append(task)
                    pending.append(("statement",))
                    continue
                self._expect("}")
                statements = tuple(values[start:])
                del values[start:]
                if isinstance(statements[-1], ODE):
                    raise self._validation_error(
                        "an ODE must have an explicit sequential successor; append "
                        "'; skip' when it has no actual successor",
                        statement_tokens[-1],
                    )
                values.append(
                    self._construct(
                        block_token, lambda: Sequence.of(*statements)
                    )
                )
                continue
            if tag == "block":
                start_token = self._expect("{")
                if self.current.kind == "}":
                    raise self._syntax_error(
                        "statement block cannot be empty; use skip for no behavior",
                        expected=("statement",),
                    )
                start = len(values)
                statement_tokens = [self.current]
                pending.append(
                    ("block-more", start, start_token, statement_tokens)
                )
                pending.append(("statement",))
                continue

            kind = self.current.kind
            if kind == "if":
                start_token = self._expect("if")
                self._expect("(")
                condition = self._parse_expression()
                self._expect(")")
                start = len(values)
                pending.append(
                    ("finish-control", "if", start, start_token, condition)
                )
                pending.append(("block",))
                pending.append(("expect", "else"))
                pending.append(("block",))
            elif kind == "choose":
                start_token = self._expect("choose")
                start = len(values)
                pending.append(("choice-more", start, start_token))
                pending.append(("block",))
                pending.append(("expect", "or"))
                pending.append(("block",))
            elif kind == "mu":
                start_token = self._expect("mu")
                variable = self._expect("IDENT")
                self._expect("invariant")
                self._expect("(")
                invariant = self._parse_expression()
                self._expect(")")
                start = len(values)
                pending.append(
                    (
                        "finish-control",
                        "mu",
                        start,
                        start_token,
                        (variable.text, invariant),
                    )
                )
                pending.append(("block",))
            else:
                values.append(self._parse_statement())
        if len(values) != 1:
            raise RuntimeError("statement-block parser produced an invalid result")
        return values[0]

    def _parse_statement(self) -> Process:
        r"""Dispatch process statements by their first token."""

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
        r"""Parse identifier-led assignment, input, or output."""

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
        r"""Parse assert(expr)."""

        start = self._expect("assert")
        self._expect("(")
        condition = self._parse_expression()
        self._expect(")")
        return self._construct(start, lambda: Assert(condition))

    def _parse_process_call(self) -> Process:
        r"""Parse an explicit call X recursion invocation."""

        start = self._expect("call")
        variable = self._expect("IDENT")
        return self._construct(start, lambda: Var(variable.text))

    def _parse_if(self) -> Process:
        r"""Parse a conditional with two required statement-block branches."""

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
        r"""Parse at least two internal-choice branches before attaching a shared tail."""

        start = self._expect("choose")
        branches = [self._parse_statement_block()]
        self._expect("or")
        branches.append(self._parse_statement_block())
        while self._match("or") is not None:
            branches.append(self._parse_statement_block())
        return self._construct(start, lambda: InternalChoice.of(*branches))

    def _parse_recursion(self) -> Process:
        r"""Parse mu recursion with a required boundary invariant."""

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
        r"""Parse ordered ODE clauses with optional safety and interrupts."""

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
        r"""Parse zero or more dot equations in source order."""

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
        r"""Parse a single-expression ODE clause of the form name(expr)."""

        self._expect(name)
        self._expect("(")
        expression = self._parse_expression()
        self._expect(")")
        return expression

    def _parse_delay_clause(self) -> tuple[Expr | float, Token]:
        r"""Parse an exact rational or positive-infinity ODE delay."""

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
        r"""Parse a nonempty communication interrupt branch table."""

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
        r"""Parse a communication guard and its statement-block continuation."""

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
        r"""Parse distinct nonempty input targets without a trailing comma."""

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
        r"""Parse nonempty expression arguments with context-specific trailing commas."""

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
        r"""Parse expressions before static value-type checking."""

        return self._parse_or_expression()

    def _parse_or_expression(self) -> Expr:
        r"""Parse or/|| into an n-ary BooleanExpr."""

        operands = [self._parse_and_expression()]
        while self.current.kind in {"or", "||"}:
            self._advance()
            operands.append(self._parse_and_expression())
        return operands[0] if len(operands) == 1 else BooleanExpr("or", operands)

    def _parse_and_expression(self) -> Expr:
        r"""Parse and/&& into an n-ary BooleanExpr."""

        operands = [self._parse_not_expression()]
        while self.current.kind in {"and", "&&"}:
            self._advance()
            operands.append(self._parse_not_expression())
        return operands[0] if len(operands) == 1 else BooleanExpr("and", operands)

    def _parse_not_expression(self) -> Expr:
        r"""Parse logical negation between comparison and conjunction precedence."""

        if self.current.kind in {"not", "!"}:
            self._advance()
            return UnaryExpr("not", self._parse_not_expression())
        return self._parse_comparison_expression()

    def _parse_comparison_expression(self) -> Expr:
        r"""Preserve chained relations in one CompareExpr."""

        operands = [self._parse_additive_expression()]
        operators: list[str] = []
        while self.current.kind in _COMPARISON_OPERATORS:
            operator = self._advance().kind
            operators.append("==" if operator == "<->" else operator)
            operands.append(self._parse_additive_expression())
        return operands[0] if not operators else CompareExpr(operands, operators)

    def _parse_additive_expression(self) -> Expr:
        r"""Parse left-associative addition and subtraction."""

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
        r"""Parse left-associative multiplication, division, and modulo."""

        result = self._parse_unary_expression()
        while self.current.kind in {"*", "/", "%"}:
            operator = self._advance().kind
            result = BinaryExpr(operator, result, self._parse_unary_expression())
        return result

    def _parse_unary_expression(self) -> Expr:
        r"""Parse unary signs with power binding more tightly on their right."""

        if self.current.kind in {"+", "-"}:
            operator = self._advance().kind
            return UnaryExpr(operator, self._parse_unary_expression())
        return self._parse_power_expression()

    def _parse_power_expression(self) -> Expr:
        r"""Parse ** and ^ as right-associative exponentiation."""

        left = self._parse_primary_expression()
        if self.current.kind in {"**", "^"}:
            self._advance()
            return BinaryExpr("**", left, self._parse_unary_expression())
        return left

    def _parse_primary_expression(self) -> Expr:
        r"""Parse literals, variables, named calls, and parenthesized expressions."""

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
        r"""Parse function arguments, permitting empty lists and trailing commas."""

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
        r"""Parse a variable-free rational constant expression."""

        return self._parse_rational_additive()

    def _parse_rational_additive(self) -> Expr:
        r"""Parse left-associative rational addition and subtraction."""

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
        r"""Parse left-associative rational multiplication and division."""

        result = self._parse_rational_unary()
        while self.current.kind in {"*", "/"}:
            operator = self._advance().kind
            result = BinaryExpr(operator, result, self._parse_rational_unary())
        return result

    def _parse_rational_unary(self) -> Expr:
        r"""Parse unary signs in rational constant expressions."""

        if self.current.kind in {"+", "-"}:
            operator = self._advance().kind
            return UnaryExpr(operator, self._parse_rational_unary())
        return self._parse_rational_power()

    def _parse_rational_power(self) -> Expr:
        r"""Parse right-associative rational exponentiation."""

        left = self._parse_rational_primary()
        if self.current.kind in {"**", "^"}:
            self._advance()
            return BinaryExpr("**", left, self._parse_rational_unary())
        return left

    def _parse_rational_primary(self) -> Expr:
        r"""Parse rational literals and parenthesized constant expressions."""

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
        r"""Convert a lexically validated number token into Literal."""

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
        r"""Wrap AST constructor failures as located validation diagnostics."""

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
        r"""Consume and return the current token."""

        token = self.current
        if token.kind != "EOF":
            self.index += 1
        return token

    def _match(self, *kinds: str) -> Token | None:
        r"""Consume a matching token; otherwise leave the cursor unchanged."""

        if self.current.kind not in kinds:
            return None
        return self._advance()

    def _expect(self, kind: str) -> Token:
        r"""Require a token kind or raise a located syntax error."""

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
        r"""Create a syntax diagnostic at the current token."""

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
        r"""Create a lowering/well-formedness diagnostic at a selected token."""

        return HCSPInputError(
            message,
            phase="validation",
            source_name=self.source_name,
            source=self.source,
            position=token.position,
            found=token.text,
        )


def _checked_source(source: object, source_name: str) -> str:
    r"""Convert non-string public inputs into consistent lexical diagnostics."""

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
    r"""Parse a process-system fragment into existing HCSP ASTs."""

    return Parser(_checked_source(source, source_name), source_name).parse_source()


def parse_hcsp_source(
    source: str,
    *,
    source_name: str = "<input>",
) -> ParsedHCSPSource:
    r"""Parse complete environments and Process input into domain models."""

    return Parser(
        _checked_source(source, source_name),
        source_name,
    ).parse_complete_source()


def parse_expression(source: str, *, source_name: str = "<expression>") -> Expr:
    r"""Parse an Expr using the strict frontend grammar."""

    return Parser(
        _checked_source(source, source_name),
        source_name,
    ).parse_expression_source()
