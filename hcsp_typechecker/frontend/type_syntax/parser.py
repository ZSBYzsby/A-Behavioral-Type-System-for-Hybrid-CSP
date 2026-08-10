"""把 ``type`` 用户语法降低为既有的行为 Type AST。

语法刻意使用命名结构而非运算符优先级。``angelic { ... }`` 保留当前
AST 对 Angelic Type 的规范化：零、一、多个通信分支分别成为
``NoInterruptType``、单个输入/输出节点、``ExternalChoiceType``。
"""

from __future__ import annotations

from fractions import Fraction
from typing import Callable, TypeVar

from ..type_constructor_frontend.errors import HCSPInputError, SourcePosition
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
    """在共享的项目词法 token 流上解析一个完整的 ``type`` 段。"""

    def __init__(self, source: str, source_name: str) -> None:
        """保存源码、扫描 token，并把游标置于首个 token。"""

        self.source = source
        self.source_name = source_name
        self.tokens = tokenize(source, source_name=source_name)
        self.index = 0

    @property
    def current(self) -> Token:
        """返回尚未消费的当前 token。"""

        return self.tokens[self.index]

    def parse(self) -> ConfigurationType:
        """解析 ``type <configuration-type>`` 并要求输入恰好结束。"""

        self._expect("type")
        value = self._parse_configuration_type()
        self._expect("EOF")
        return value

    def _parse_configuration_type(self) -> ConfigurationType:
        """解析单进程类型或多分量 ``parallel`` configuration type。"""

        if self.current.kind != "parallel":
            return self._parse_process_type()
        start = self._expect("parallel")
        self._expect("{")
        components = [self._parse_configuration_type()]
        self._expect(",")
        components.append(self._parse_configuration_type())
        while self._match(",") is not None:
            components.append(self._parse_configuration_type())
        self._expect("}")
        return self._construct(start, lambda: ParallelType(components))

    def _parse_process_type(self) -> ProcessType:
        """解析论文过程类型范畴 ``T`` 的一个具体产生式。"""

        token = self.current
        if self._match("empty") is not None:
            return EmptyType()
        if self._match("bottom") is not None:
            return BottomType()
        if self.current.kind == "internal":
            return self._parse_internal_choice()
        if self.current.kind == "delay":
            return self._parse_finite_delay()
        if self.current.kind == "forever":
            return self._parse_infinite_delay()
        if self.current.kind == "mu":
            return self._parse_mu()
        if self.current.kind == "IDENT":
            self.index += 1
            return self._construct(token, lambda: TypeVariable(token.text))
        raise self._syntax_error(
            "expected a process type",
            expected=(
                "empty",
                "bottom",
                "internal",
                "delay",
                "forever",
                "mu",
                "type variable",
            ),
        )

    def _parse_internal_choice(self) -> ProcessType:
        """解析至少两个过程分支组成的多元内部选择。"""

        start = self._expect("internal")
        self._expect("{")
        branches = [self._parse_process_type()]
        self._expect(",")
        branches.append(self._parse_process_type())
        while self._match(",") is not None:
            branches.append(self._parse_process_type())
        self._expect("}")
        return self._construct(start, lambda: InternalChoiceType(branches))

    def _parse_finite_delay(self) -> ProcessType:
        """解析有限 delay；缺省 interrupt 规范为 ``NoInterruptType``。"""

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
        """解析无穷 delay；它没有用户可写的自然到时后继。"""

        start = self._expect("forever")
        interrupts: AngelicType = NoInterruptType()
        if self._match("interrupt") is not None:
            interrupts = self._parse_angelic_type()
        return self._construct(start, lambda: InfiniteDelayType(interrupts))

    def _parse_mu(self) -> ProcessType:
        """解析 ``mu X. T``，并交给 ``MuType`` 验证通信守卫条件。"""

        start = self._expect("mu")
        variable = self._expect("IDENT")
        self._expect(".")
        body = self._parse_process_type()
        return self._construct(start, lambda: MuType(variable.text, body))

    def _parse_angelic_type(self) -> AngelicType:
        """解析零、一或多个通信分支，并规范为唯一的 ``A`` 节点。"""

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
        """解析一个 ``ch? -> T`` 或 ``ch! -> T`` 的 Angelic 分支。"""

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
        """只接受精确、有限且非负的整数字面量或分数字面量。"""

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
        """若当前 token 属于指定种类则消费它，否则保持游标不动。"""

        if self.current.kind != kind:
            return None
        token = self.current
        self.index += 1
        return token

    def _expect(self, kind: str) -> Token:
        """消费指定 token，失败时产生带源码位置的语法诊断。"""

        token = self._match(kind)
        if token is None:
            raise self._syntax_error(
                f"expected {kind!r}",
                expected=(kind,),
            )
        return token

    def _construct(self, token: Token, build: Callable[[], _T]) -> _T:
        """把 AST 构造期的局部良构错误包装成用户可定位的诊断。"""

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
        """按当前 token 的位置创建语法错误。"""

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
        """按给定 token 的位置创建 AST 良构性错误。"""

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
    """把完整 ``type`` 源码解析为项目的 ``ConfigurationType`` AST。"""

    return TypeParser(source, source_name).parse()
