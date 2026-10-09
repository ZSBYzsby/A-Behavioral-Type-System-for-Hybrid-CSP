r"""Lower user type syntax into existing behavioral ASTs."""

from __future__ import annotations

from fractions import Fraction
from typing import Callable, TypeVar

from ..errors import HCSPInputError, SourcePosition
from ..type_constructor_frontend.lexer import Token, tokenize
from ...data_structures.type_ast.ast import (
    AngelicType,
    BottomType,
    ConfigurationType,
    EmptyType,
    FiniteDelayType,
    InfiniteDelayType,
    InputType,
    InternalChoiceType,
    MuType,
    NoInterruptType,
    OutputType,
    ParallelType,
    ProcessType,
    TypeVar as TypeVariable,
    make_external_choice,
)


_T = TypeVar("_T")


class TypeParser:
    r"""Parse a complete type section using the shared lexical stream."""

    def __init__(self, source: str, source_name: str) -> None:
        r"""Store source and tokens and initialize the cursor."""

        self.source = source
        self.source_name = source_name
        self.tokens = tokenize(source, source_name=source_name)
        self.index = 0

    @property
    def current(self) -> Token:
        r"""Return the current unconsumed token."""

        return self.tokens[self.index]

    def parse(self) -> ConfigurationType:
        r"""Parse type followed by a configuration and EOF."""

        self._expect("type")
        value = self._parse_configuration_type()
        self._expect("EOF")
        return value

    def _parse_configuration_type(self) -> ConfigurationType:
        r"""Parse a process type or multi-component parallel type."""

        values: list[ConfigurationType] = []
        pending: list[tuple[object, ...]] = [("configuration",)]
        while pending:
            task = pending.pop()
            if task[0] == "configuration":
                if self.current.kind != "parallel":
                    values.append(self._parse_process_type())
                    continue
                token = self._expect("parallel")
                self._expect("{")
                pending.append(("parallel-more", token, len(values)))
                pending.append(("configuration",))
                continue

            _, token, start = task
            component_count = len(values) - start
            if component_count == 1:
                self._expect(",")
                pending.append(("parallel-more", token, start))
                pending.append(("configuration",))
                continue
            if self._match(",") is not None:
                pending.append(("parallel-more", token, start))
                pending.append(("configuration",))
                continue
            self._expect("}")
            components = tuple(values[start:])
            del values[start:]
            values.append(
                self._construct(token, lambda: ParallelType(components))
            )

        if len(values) != 1:
            raise RuntimeError("configuration Type parsing produced invalid results")
        return values[0]

    def _parse_process_type(self) -> ProcessType:
        r"""Parse deep continuation Types with an explicit work stack."""

        values: list[ProcessType | AngelicType] = []
        pending: list[tuple[object, ...]] = [("process",)]
        while pending:
            task = pending.pop()
            tag = task[0]
            if tag == "expect":
                self._expect(task[1])
                continue
            if tag == "finish-unary":
                _, kind, start, token, payload = task
                children = values[start:]
                del values[start:]
                if kind == "mu":
                    built = self._construct(
                        token, lambda: MuType(payload, children[0])
                    )
                elif kind == "infinite":
                    built = self._construct(
                        token, lambda: InfiniteDelayType(children[0])
                    )
                elif kind == "communication":
                    channel, direction = payload
                    constructor = InputType if direction == "?" else OutputType
                    built = self._construct(
                        token, lambda: constructor(channel, children[0])
                    )
                else:
                    raise RuntimeError(f"unsupported unary Type task: {kind}")
                values.append(built)
                continue
            if tag == "finish-finite":
                _, start, token, duration, has_interrupt = task
                children = values[start:]
                del values[start:]
                interrupts = children[0] if has_interrupt else NoInterruptType()
                continuation = children[1] if has_interrupt else children[0]
                values.append(
                    self._construct(
                        token,
                        lambda: FiniteDelayType(
                            duration, interrupts, continuation
                        ),
                    )
                )
                continue
            if tag == "internal-more":
                _, start, token = task
                if self._match(",") is not None:
                    pending.append(task)
                    pending.append(("expect", ")"))
                    pending.append(("process",))
                    pending.append(("expect", "("))
                    continue
                self._expect("}")
                branches = tuple(values[start:])
                del values[start:]
                if len(branches) < 2:
                    raise self._validation_error(
                        "internal choice requires at least two branches", token
                    )
                values.append(
                    self._construct(token, lambda: InternalChoiceType(branches))
                )
                continue
            if tag == "angelic-more":
                _, start, token = task
                if self._match(",") is not None:
                    if self.current.kind == "}":
                        raise self._syntax_error(
                            "trailing comma is not allowed in angelic branches",
                            expected=("communication branch",),
                        )
                    pending.append(task)
                    pending.append(("communication",))
                    continue
                self._expect("}")
                branches = tuple(values[start:])
                del values[start:]
                values.append(
                    self._construct(token, lambda: make_external_choice(branches))
                )
                continue
            if tag == "angelic":
                start_token = self._expect("angelic")
                self._expect("{")
                start = len(values)
                if self._match("}") is not None:
                    values.append(NoInterruptType())
                else:
                    pending.append(("angelic-more", start, start_token))
                    pending.append(("communication",))
                continue
            if tag == "communication":
                channel = self._expect("IDENT")
                direction = self.current
                if direction.kind not in {"?", "!"}:
                    raise self._syntax_error(
                        "expected '?' or '!' after an angelic channel name",
                        expected=("?", "!"),
                    )
                self.index += 1
                self._expect("->")
                start = len(values)
                pending.append(
                    (
                        "finish-unary",
                        "communication",
                        start,
                        channel,
                        (channel.text, direction.kind),
                    )
                )
                pending.append(("process",))
                continue

            token = self.current
            if self._match("empty") is not None:
                values.append(EmptyType())
            elif self._match("bottom") is not None:
                values.append(BottomType())
            elif self._match("(") is not None:
                pending.append(("expect", ")"))
                pending.append(("process",))
            elif self._match("internal") is not None:
                self._expect("{")
                start = len(values)
                if self.current.kind != "(":
                    raise self._syntax_error(
                        "each internal-choice branch must be parenthesized",
                        expected=("(",),
                    )
                pending.append(("internal-more", start, token))
                pending.append(("expect", ")"))
                pending.append(("process",))
                pending.append(("expect", "("))
            elif self._match("delay") is not None:
                self._expect("(")
                duration = self._parse_duration()
                self._expect(")")
                start = len(values)
                has_interrupt = self._match("interrupt") is not None
                pending.append(
                    ("finish-finite", start, token, duration, has_interrupt)
                )
                pending.append(("process",))
                pending.append(("expect", "then"))
                if has_interrupt:
                    pending.append(("angelic",))
            elif self._match("forever") is not None:
                start = len(values)
                if self._match("interrupt") is None:
                    values.append(InfiniteDelayType(NoInterruptType()))
                else:
                    pending.append(
                        ("finish-unary", "infinite", start, token, None)
                    )
                    pending.append(("angelic",))
            elif self._match("mu") is not None:
                variable = self._expect("IDENT")
                self._expect(".")
                start = len(values)
                pending.append(
                    ("finish-unary", "mu", start, token, variable.text)
                )
                pending.append(("process",))
            elif self.current.kind == "IDENT":
                self.index += 1
                values.append(
                    self._construct(token, lambda: TypeVariable(token.text))
                )
            else:
                raise self._syntax_error(
                    "expected a process type",
                    expected=(
                        "empty", "bottom", "(", "internal", "delay",
                        "forever", "mu", "type variable",
                    ),
                )
        if len(values) != 1 or not isinstance(values[0], ProcessType):
            raise RuntimeError("Type parser produced an invalid process result")
        return values[0]

    def _parse_internal_choice(self) -> ProcessType:
        r"""Parse at least two explicitly parenthesized internal-choice branches."""

        start = self._expect("internal")
        self._expect("{")
        branches = [self._parse_required_choice_branch()]
        self._expect(",")
        branches.append(self._parse_required_choice_branch())
        while self._match(",") is not None:
            branches.append(self._parse_required_choice_branch())
        self._expect("}")
        return self._construct(start, lambda: InternalChoiceType(branches))

    def _parse_parenthesized_process_type(self) -> ProcessType:
        r"""Parse grouping parentheses without adding an AST node."""

        self._expect("(")
        value = self._parse_process_type()
        self._expect(")")
        return value

    def _parse_required_choice_branch(self) -> ProcessType:
        r"""Require an explicit (T) block for an internal-choice branch."""

        if self.current.kind != "(":
            raise self._syntax_error(
                "each internal-choice branch must be parenthesized",
                expected=("(",),
            )
        return self._parse_parenthesized_process_type()

    def _parse_finite_delay(self) -> ProcessType:
        r"""Parse finite delay, defaulting omitted interrupts to NoInterruptType."""

        start = self._expect("delay")
        self._expect("(")
        duration = self._parse_duration()
        self._expect(")")
        interrupts: AngelicType = NoInterruptType()
        if self._match("interrupt") is not None:
            interrupts = self._parse_angelic_type()
        self._expect("then")
        continuation = self._parse_process_type()
        return self._construct(
            start,
            lambda: FiniteDelayType(duration, interrupts, continuation),
        )

    def _parse_infinite_delay(self) -> ProcessType:
        r"""Parse infinite delay without a writable timeout continuation."""

        start = self._expect("forever")
        interrupts: AngelicType = NoInterruptType()
        if self._match("interrupt") is not None:
            interrupts = self._parse_angelic_type()
        return self._construct(start, lambda: InfiniteDelayType(interrupts))

    def _parse_mu(self) -> ProcessType:
        r"""Parse mu X.T and validate communication guards via MuType."""

        start = self._expect("mu")
        variable = self._expect("IDENT")
        self._expect(".")
        body = self._parse_process_type()
        return self._construct(start, lambda: MuType(variable.text, body))

    def _parse_angelic_type(self) -> AngelicType:
        r"""Canonicalize zero, one, or multiple communication branches."""

        start = self._expect("angelic")
        self._expect("{")
        branches: list[InputType | OutputType] = []
        if self.current.kind != "}":
            branches.append(self._parse_communication_branch())
            while self._match(",") is not None:
                if self.current.kind == "}":
                    raise self._syntax_error(
                        "trailing comma is not allowed in angelic branches",
                        expected=("communication branch",),
                    )
                branches.append(self._parse_communication_branch())
        self._expect("}")
        return self._construct(start, lambda: make_external_choice(branches))

    def _parse_communication_branch(self) -> InputType | OutputType:
        r"""Parse a ch? -> T or ch! -> T angelic branch."""

        channel = self._expect("IDENT")
        direction = self.current
        if direction.kind not in {"?", "!"}:
            raise self._syntax_error(
                "expected '?' or '!' after an angelic channel name",
                expected=("?", "!"),
            )
        self.index += 1
        self._expect("->")
        continuation = self._parse_process_type()
        if direction.kind == "?":
            return self._construct(
                channel,
                lambda: InputType(channel.text, continuation),
            )
        return self._construct(
            channel,
            lambda: OutputType(channel.text, continuation),
        )

    def _parse_duration(self) -> Fraction:
        r"""Require an exact nonnegative integer or fraction duration."""

        numerator = self._expect("INTEGER")
        denominator: Token | None = None
        if self._match("/") is not None:
            denominator = self._expect("INTEGER")
        try:
            top = int(numerator.text)
            if denominator is None:
                return Fraction(top)
            bottom = int(denominator.text)
            if bottom <= 0:
                raise ValueError("denominator must be positive")
            return Fraction(top, bottom)
        except ValueError as exc:
            token = denominator or numerator
            raise self._validation_error(str(exc), token) from exc

    def _match(self, kind: str) -> Token | None:
        r"""Consume a matching token without advancing on failure."""

        if self.current.kind != kind:
            return None
        token = self.current
        self.index += 1
        return token

    def _expect(self, kind: str) -> Token:
        r"""Require a token or produce a located syntax diagnostic."""

        token = self._match(kind)
        if token is None:
            raise self._syntax_error(
                f"expected {kind!r}",
                expected=(kind,),
            )
        return token

    def _construct(self, token: Token, build: Callable[[], _T]) -> _T:
        r"""Wrap constructor well-formedness failures as located diagnostics."""

        try:
            return build()
        except (TypeError, ValueError) as exc:
            raise self._validation_error(str(exc), token) from exc

    def _syntax_error(
        self,
        message: str,
        *,
        expected: tuple[str, ...] = (),
    ) -> HCSPInputError:
        r"""Create a syntax error at the current token."""

        return HCSPInputError(
            message,
            phase="syntax",
            source_name=self.source_name,
            source=self.source,
            position=self.current.position,
            found=None if self.current.kind == "EOF" else self.current.text,
            expected=expected,
        )

    def _validation_error(self, message: str, token: Token) -> HCSPInputError:
        r"""Create a well-formedness error at the selected token."""

        return HCSPInputError(
            message,
            phase="validation",
            source_name=self.source_name,
            source=self.source,
            position=token.position,
            found=token.text,
        )


def parse_type_source(
    source: str,
    *,
    source_name: str = "<type>",
) -> ConfigurationType:
    r"""Parse complete Type source into ConfigurationType."""

    return TypeParser(source, source_name).parse()
