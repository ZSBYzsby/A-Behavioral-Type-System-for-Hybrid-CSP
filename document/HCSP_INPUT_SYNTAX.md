# HCSP Process and expression input syntax

This page defines the HCSP system, statement, and expression subgrammars in a
complete source's `process` section, and their lowering to the existing Process
and `Expr` ASTs. [GAMMA_THETA_INPUT_SYNTAX.md](GAMMA_THETA_INPUT_SYNTAX.md)
defines the complete `source` grammar, including Gamma, Theta, and Process.

The internal input layer implements these subgrammars without changing Python
AST node semantics. Users place them in complete source rather than calling
fragment parsers. Call `construct_hcsp_type(...)` without a `type` section, or
append `type` and call `check_hcsp_type(...)` to check a supplied Type.
A construction example follows:

```python
from hcsp_typechecker import construct_hcsp_type

source = """
gamma()
theta(ch: channel(value: Real), out: channel(value: Real))
process {{ch?(x); out!(x)}}
"""

type_ast = construct_hcsp_type(source, source_name="example.hcsp")
```

Parsing failures raise `HCSPInputError` with the lexical/syntax phase, source name,
line, column, and source indicator. `parse_annotated_hcsp(...)`,
`parse_annotated_expression(...)`, and direct AST constructors remain internal
interfaces for implementation, testing, and review; they have no package-root
compatibility guarantee. To edit complete Gamma/Theta/Process examples and inspect
their Types, run `python examples/demo_type_construction.py` from the repository root.

## 1. General conventions

- A `process_system` contains one or more nonempty statement blocks.
- One block represents a sequential process; multiple blocks run in parallel.
- Within a block, `;` denotes sequential composition, without a trailing semicolon.
- `{...}` encloses the system and executable statement blocks.
- `(...)` encloses arguments, conditions, annotations, and named ODE configuration.
- `,` separates parallel processes, communication and function arguments, ODE
  equations, and interrupt branches.
- Whitespace and line breaks have no semantics.
- Comments use `//` for a line or non-nested `/* ... */` blocks.

## 2. Process grammar

```ebnf
process_source
    ::= process_system EOF


process_system
    ::= "{"
            statement_block
            { "," statement_block }
        "}"


statement_block
    ::= "{"
            statement
            { ";" statement }
        "}"


statement
    ::= skip_statement
      | assignment_statement
      | assertion_statement
      | input_action
      | output_action
      | process_call
      | if_statement
      | choice_statement
      | recursion_statement
      | ode_statement


skip_statement
    ::= "skip"


assignment_statement
    ::= IDENT ":=" expr


assertion_statement
    ::= "assert" "(" expr ")"


input_action
    ::= IDENT "?"
        "(" identifier_list ")"


output_action
    ::= IDENT "!"
        "(" expression_list ")"



process_call
    ::= "call" IDENT


if_statement
    ::= "if"
        "(" expr ")"
        statement_block
        "else"
        statement_block


choice_statement
    ::= "choose"
        statement_block
        "or"
        statement_block
        { "or" statement_block }


recursion_statement
    ::= "mu" IDENT
        "invariant"
        "(" expr ")"
        statement_block


ode_statement
    ::= "ode" "("

            flow_clause
            ","

            domain_clause
            ","

            [ safety_clause "," ]

            delay_clause

            [ "," interrupt_clause ]

        ")"


flow_clause
    ::= "flow" "("
            [
                ode_equation
                { "," ode_equation }
            ]
        ")"


ode_equation
    ::= "dot" IDENT "=" expr


domain_clause
    ::= "domain"
        "(" expr ")"


safety_clause
    ::= "safety"
        "(" expr ")"


delay_clause
    ::= "delay"
        "(" duration ")"


interrupt_clause
    ::= "interrupt" "("
            event_branch
            { "," event_branch }
        ")"


event_branch
    ::= "on"
        communication_action
        statement_block


communication_action
    ::= input_action
      | output_action


identifier_list
    ::= IDENT
        { "," IDENT }


expression_list
    ::= expr
        { "," expr }


duration
    ::= finite_duration
      | "inf"


finite_duration
    ::= rational_constant_expression


rational_constant_expression
    ::= rational_additive_expression


rational_additive_expression
    ::= rational_multiplicative_expression
        {
            ( "+" | "-" )
            rational_multiplicative_expression
        }


rational_multiplicative_expression
    ::= rational_unary_expression
        {
            ( "*" | "/" )
            rational_unary_expression
        }


rational_unary_expression
    ::= ( "+" | "-" ) rational_unary_expression
      | rational_power_expression


rational_power_expression
    ::= rational_primary_expression
        [
            ( "**" | "^" )
            rational_unary_expression
        ]


rational_primary_expression
    ::= integer_literal
      | real_literal
      | "(" rational_constant_expression ")"
```

Finite-duration expressions exclude variables, functions, Boolean operations,
comparisons, modulo, and `inf`. Their value must be nonnegative, divisors nonzero,
and power exponents integers. Only the separate `duration` alternative allows
`inf` for an ordinary ODE's `delay`.

## 3. Expression grammar

Every Process `expr` uses this grammar. Numeric expressions and Boolean formulas
share syntax; subsequent type checking determines their actual types.

```ebnf
expr
    ::= or_expression


or_expression
    ::= and_expression
        { or_operator and_expression }


or_operator
    ::= "or"
      | "||"


and_expression
    ::= not_expression
        { and_operator not_expression }


and_operator
    ::= "and"
      | "&&"


not_expression
    ::= not_operator not_expression
      | comparison_expression


not_operator
    ::= "not"
      | "!"


comparison_expression
    ::= additive_expression
        {
            comparison_operator
            additive_expression
        }


comparison_operator
    ::= "=="
      | "!="
      | "<"
      | "<="
      | ">"
      | ">="
      | "<->"


additive_expression
    ::= multiplicative_expression
        {
            additive_operator
            multiplicative_expression
        }


additive_operator
    ::= "+"
      | "-"


multiplicative_expression
    ::= unary_expression
        {
            multiplicative_operator
            unary_expression
        }


multiplicative_operator
    ::= "*"
      | "/"
      | "%"


unary_expression
    ::= unary_arithmetic_operator unary_expression
      | power_expression


unary_arithmetic_operator
    ::= "+"
      | "-"


power_expression
    ::= primary_expression
        [
            power_operator
            unary_expression
        ]


power_operator
    ::= "**"
      | "^"


primary_expression
    ::= literal
      | IDENT
      | function_call
      | "(" expr ")"


function_call
    ::= IDENT
        "("
            [ argument_list ]
        ")"


argument_list
    ::= expr
        { "," expr }
        [ "," ]


literal
    ::= boolean_literal
      | integer_literal
      | real_literal


boolean_literal
    ::= "true"
      | "false"


integer_literal
    ::= decimal_digits


real_literal
    ::= decimal_digits "." [ decimal_digits ] [ exponent ]
      | "." decimal_digits [ exponent ]
      | decimal_digits exponent


exponent
    ::= ( "e" | "E" )
        [ "+" | "-" ]
        decimal_digits


decimal_digits
    ::= DIGIT
        { DIGIT }
```

`true` and `false` are case-insensitive; canonical output uses lowercase.

To bound memory use during exact rational conversion, a numeric literal may have
at most 4096 significant digits and a decimal exponent of absolute value at most
10000. Exceeding these bounds gives a source-located lexical diagnostic rather
than exposing a host Python numeric exception.

## 4. Identifiers and reserved words

```ebnf
IDENT
    ::= ( ASCII_LETTER | "_" )
        { ASCII_LETTER | DIGIT | "_" }
```

The equivalent regular expression is:

```text
[A-Za-z_][A-Za-z0-9_]*
```

State variables, channels, Process variables, and functions use the same
case-sensitive lexical rule. HCSP and expression keywords cannot be identifiers.

Current reserved words include:

```text
skip assert call if else choose or mu invariant
ode flow dot domain safety delay interrupt on
true false inf not and
None
```

Complete source also reserves these environment-section and type names:

```text
gamma parameters theta process continuous channel where
Bool Nat Int Rational Real
```

Type-section keywords are also reserved across complete and fragment inputs:

```text
type empty bottom internal forever angelic then parallel
```

These names cannot be ordinary Process IDENTs. Complete-source parsing for
`construct_hcsp_type(...)` and internal fragment parsing share the reserved-word
table, so names have the same token interpretation across parsing paths.

`None` is reserved but invalid, enabling an explicit unsupported-null diagnostic;
it is not a literal production. Lowercase `none` remains an ordinary case-sensitive identifier.

## 5. Operator precedence and associativity

From highest to lowest:

| Precedence | Form | Associativity |
|---|---|---|
| 1 | Parentheses, function calls | — |
| 2 | `**`, `^` | Right |
| 3 | Unary `+`, unary `-` | Right |
| 4 | `*`, `/`, `%` | Left |
| 5 | `+`, `-` | Left |
| 6 | `==`, `!=`, `<`, `<=`, `>`, `>=`, `<->` | Chained comparison |
| 7 | `not`, `!` | Right |
| 8 | `and`, `&&` | Collected left-to-right into one n-ary node |
| 9 | `or`, `||` | Collected left-to-right into one n-ary node |

For example:

```text
-x ** 2       = -(x ** 2)
(-x) ** 2     = (-x) ** 2
x ** y ** z   = x ** (y ** z)
not x < y     = not (x < y)
a or b and c  = a or (b and c)
```

Chained comparisons are stored in one `CompareExpr`:

```text
0 <= x < limit
```

They represent the conjunction of successive relations:

```text
0 <= x and x < limit
```

## 6. Process input semantics

### 6.1 Top-level parallelism

```text
lower_source({P}) = P

lower_source({P1, ..., Pn})
    = Parallel.of(P1, ..., Pn), n >= 2
```

The outer list is nonempty and ordered, not a mathematical set. It preserves
source order and duplicate components.

### 6.2 Sequential composition

```text
lower_block({P1; ...; Pn})
    = Sequence.of(P1, ..., Pn)
```

For `if`, internal choice, and ODE, subsequent block statements are the control
node's common continuation. The parser places them directly in its `continuation`
field rather than wrapping the control node in `Sequence`. Such nodes therefore
end their sequence spine; their internal Q still executes under Table 2.

### 6.3 Communication

- `ch?(x1, ..., xn)` receives one or more independent scalars.
- `ch!(e1, ..., en)` sends one or more scalar expressions.
- Input targets are distinct.
- Argument lists are nonempty; unit communication is unsupported.
- Multiple arguments do not form a tuple value.

### 6.4 Recursion

- `mu X invariant(phi) { ... }` requires an explicit invariant.
- Use `invariant(true)` when no nontrivial invariant is needed.
- `call X` constructs `Var("X")`.
- AST construction and TypeConstructor further check recursion scope,
  communication guarding, tail position, and Assumptions 2.1/2.2.

### 6.5 ODE

- `flow(...)`, `domain(...)`, and `delay(...)` are required.
- Omitted `safety(...)` defaults to `true`.
- Omitted `interrupt(...)` produces `EmptyEvent()`, meaning no communication interrupts.
- An explicit interrupt contains at least one branch; `interrupt()` is invalid.
- `flow()` is valid and declares no user continuous-variable equations.
- Left-hand sides use `dot x`, for example `dot x = v`, and are distinct within a flow.
- Every ODE adds a hidden local clock `t` initialized to `0` with derivative `1`.
- `t` may occur in right-hand sides, `domain`, and `safety`, but not in user left-hand sides.
- The clock is outside the user evolution vector and is not scoped into interrupt
  branches or the ODE's external continuation.
- Finite delays evaluate to nonnegative rationals; ordinary ODEs also allow `delay(inf)`.
- `wait(d)` is unsupported. A finite wait that naturally ends at `d` uses
  `ode(flow(), domain(t < d), delay(d)); skip`.
- Every ODE requires an explicit following statement, including `; skip` when
  there is no substantive continuation. A bare ODE ending a block is an input error.
- `ODE; Q` lowers to `ODE(..., continuation=Q)`, not `Sequence(ODE(...), Q)`.
- `ODE; skip` tries both `T-\unrhd`, treating skip as an unreachable-continuation
  placeholder, and `T-\unrhd'`, treating it as a real empty continuation.
  Domain/boundary proofs select a candidate. `ODE; P` for non-skip `P` uses only the prime rule.

## 7. Expr AST mapping

| Input form | AST node |
|---|---|
| Boolean, integer, real literals | `Literal` |
| `x` | `Variable` |
| `not e`, `!e`, `+e`, `-e` | `UnaryExpr` |
| `+`, `-`, `*`, `/`, `%` | `BinaryExpr` |
| `**`, `^` | `BinaryExpr("**", ...)` |
| `and`, `&&`, `or`, `||` | `BooleanExpr` |
| Single or chained comparison | `CompareExpr` |
| `f(e1, ..., en)` | `CallExpr` |

Parsing does not perform type checking. For example, `1 and 2` produces an
expression tree, but subsequent checking rejects non-Bool operands of `and`.

Parsing permits ordinary function names with any number of positional arguments.
The proof backend gives specific semantics to only some functions; unsupported
forms produce explicit expression-typing or proof diagnostics.

## 8. Unsupported expressions

- Conditional expressions: `a if B else b`.
- Attribute access and methods: `plant.temperature`, `obj.f(x)`.
- Indexing, slicing, and dynamic calls: `array[i]`, `functions[i](x)`.
- Lambdas, generators, and comprehensions.
- Tuple, list, dictionary, and set values.
- String, bytes, complex, `None`, and ellipsis literals.
- Keyword arguments, `*args`, and `**kwargs`.
- Undefined operators such as `//`, `@`, `<<`, `>>`, `&`, and `|`.
- `in`, `not in`, `is`, and `is not`.
- Assignment expressions, the walrus operator, and destructuring targets.

## 9. Process fragment examples

```hcsp
{
    {
        start?(x);
        x := x + 1;

        ode(
            flow(
                dot x = v,
                dot v = -x
            ),
            domain(t <= 1 and x <= limit),
            safety(x <= limit),
            delay(1),
            interrupt(
                on reset?(new_x, new_v) {
                    x := new_x;
                    v := new_v
                },
                on report!(x, v) {
                    skip
                }
            )
        );

        finished!(x)
    },

    {
        start!(initial_value);
        finished?(result)
    }
}
```

## 10. Complete-source interface and internal compatibility boundaries

The complete public construction entry point is:

```python
from hcsp_typechecker import construct_hcsp_type

type_ast = construct_hcsp_type(
    complete_source,
    source_name="example.hcsp",
    output="none",  # Also accepts "result" or "full".
)
```

It parses `constructor_source` from `GAMMA_THETA_INPUT_SYNTAX.md`, creates internal
parameters, Gamma, Theta, and Process ASTs, then constructs and proves the Type.
For an appended `type` section, call `check_hcsp_type(...)` to check the supplied
Type; see [TYPE_CHECKER.md](TYPE_CHECKER.md). Output and exception contracts are
centralized in the [Public API guide](PUBLIC_API_GUIDE.md).

These entry points belong to internal development and review:

```python
from hcsp_typechecker.frontend.annotated_hcsp_syntax import (
    parse_annotated_expression,
    parse_annotated_hcsp,
)
from hcsp_typechecker.frontend.type_constructor_frontend import parse_hcsp_source
```

- `parse_annotated_hcsp(...)` parses a nonempty `process_system` fragment and lowers
  it to a Process/Parallel AST.
- `parse_annotated_expression(...)` builds `Expr` using Section 3's strict grammar.
- `parse_hcsp_source(...)` is the facade's shared program-prefix parser, returning
  internal `ParsedHCSPSource`.
- `parse_expr(...)` is the legacy convenience constructor for Process expressions.

Their signatures and records are outside the public compatibility contract.
They accept ASCII IDENTs and the decimal numbers listed here. `^` and `**` parse
as high-precedence right-associative power, stored as `BinaryExpr("**", ...)`.
Function arguments allow an empty list and trailing comma; communication arguments
and top-level blocks do not allow trailing commas. `&&`, `||`, `!`, `<->`, and
case-insensitive Boolean literals normalize to the corresponding Expr nodes.

Internal `parse_expr(...)` additionally accepts some legacy Python numeric literal
forms. It shares the ASCII IDENT restriction and rewrites `^` tokens to actual
`**` before Python parsing, avoiding XOR precedence, left associativity, and
Python's Unicode/NFKC identifier extensions.
