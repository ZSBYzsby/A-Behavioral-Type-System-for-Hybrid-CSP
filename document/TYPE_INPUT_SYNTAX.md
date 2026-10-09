# Supplied Type input syntax

This page defines the concrete Type syntax used by TypeChecker. Internal parsing
and formatting are provided by
`hcsp_typechecker.frontend.type_syntax.parse_type_source` and
`hcsp_typechecker.frontend.type_syntax.format_type_source`.
These are implementation interfaces, outside the stable package-root API.
Users pass complete typed source to `check_hcsp_type(...)`.

Parsing and canonical formatting satisfy:

```text
parse_type_source(format_type_source(T)) == T
```

Here `T` is a `ConfigurationType` representable in the user syntax, including
its identifier and numeric-literal restrictions. Internal AST constructors
enforce ASCII identifier shape but do not universally reject reserved words;
for example, `TypeVar("empty")` cannot round-trip through text because `empty`
denotes `EmptyType`. The formatter uses one canonical spelling; the parser also
accepts explicit empty Angelic Types in finite and infinite delays.

Construction and checking reports in `result/full` mode use the same formatter.
The `type ...` text following labels such as `Type source :`,
`Complete candidate Type source :`, and `Supplied Type source :` can be copied
and parsed without loss. Reports display canonical source rather than Python AST
`repr` output. Simple Types stay on one line; `parallel`, `internal`, and
`angelic` blocks use line breaks and four-space indentation at each nesting level.

## 1. Type section in complete input

```ebnf
typed_source
    ::= program_prefix
        type_section
        EOF

type_section
    ::= "type" configuration_type
```

`program_prefix` follows the [Complete HCSP input syntax](GAMMA_THETA_INPUT_SYNTAX.md):
Gamma, optional Parameters, Theta, and Process, in order. This page defines only
the final `type_section`.

## 2. Type grammar

```ebnf
configuration_type
    ::= process_type
      | "parallel" "{"
            configuration_type "," configuration_type
            { "," configuration_type }
        "}"

process_type
    ::= "empty"
      | "bottom"
      | "internal" "{"
            parenthesized_type "," parenthesized_type
            { "," parenthesized_type }
        "}"
      | "delay" "(" finite_duration ")"
            [ "interrupt" angelic_type ]
            "then" process_type
      | "forever" [ "interrupt" angelic_type ]
      | "mu" IDENT "." process_type
      | IDENT
      | parenthesized_type

parenthesized_type
    ::= "(" process_type ")"

angelic_type
    ::= "angelic" "{"
            [ communication_branch { "," communication_branch } ]
        "}"

communication_branch
    ::= IDENT "?" "->" process_type
      | IDENT "!" "->" process_type

finite_duration
    ::= NONNEGATIVE_INTEGER
      | NONNEGATIVE_INTEGER "/" POSITIVE_INTEGER
```

Parentheses are part of the grouping syntax. Every `internal` branch must be
written as `(process_type)`. Other `process_type` positions also accept grouping
parentheses, but canonical formatting emits them only where internal-choice grouping requires them.

## 3. AST mapping and canonical output

| Type AST | Canonical output |
|---|---|
| `EmptyType()` | `empty` |
| `BottomType()` | `bottom` |
| `InternalChoiceType(T1,...,Tn)` | `internal {(T1), ..., (Tn)}` |
| `FiniteDelayType(d, NoInterruptType(), T)` | `delay(d) then T` |
| `FiniteDelayType(d, A, T)` | `delay(d) interrupt A then T` |
| `InfiniteDelayType(NoInterruptType())` | `forever` |
| `InfiniteDelayType(A)` | `forever interrupt A` |
| `MuType(X,T)` | `mu X. T` |
| `TypeVar(X)` | `X` |
| `ParallelType(T1,...,Tn)` | `parallel {T1, ..., Tn}` |

`A` uses `angelic_type`:

`InternalChoiceType` preserves nested internal choices. Parentheses specify the
rule grouping: the current T-If node must have two branches, and an n-ary T-sqcup
node must match the Process branch count. The checker then checks each branch
in order. It does not search alternative groupings or rewrite the supplied
structure using associativity or commutativity.

For example:

```text
internal {(
    internal {(T1), (T2)}
), (T3)}
```

The first child judgment receives `internal {(T1), (T2)}` and the second receives
`T3`. This is a different Type AST from
`internal {(T1), (internal {(T2), (T3)})}`.

| Angelic Type AST | Canonical output |
|---|---|
| `NoInterruptType()` | `angelic {}` |
| `InputType(ch,T)` | `angelic {ch? -> T}` |
| `OutputType(ch,T)` | `angelic {ch! -> T}` |
| `ExternalChoiceType(...)` | `angelic {branch1, ..., branchn}` |

`angelic {}` is the empty interrupt set (A); `empty` is a Process Type (T) with
no observable communication. They are distinct categories. For delay, the parser accepts:

```text
delay(1) then empty
delay(1) interrupt angelic {} then empty
```

Both produce `FiniteDelayType(1, NoInterruptType(), EmptyType())`; canonical
formatting always uses the first form, omitting the empty interrupt.

`bottom` preserves the formal `BottomType` node. A finite
`delay(d) interrupt A then bottom` represents `T-\unrhd`, whose deadline
continuation is unreachable. `delay(d) interrupt A then empty` represents
`T-\unrhd'` with a reachable empty continuation. `InfiniteDelayType` fixes its
unreachable bottom continuation implicitly. Serialization preserves the finite bottom/empty distinction.

## 4. Syntactic category boundaries

`AngelicType` and `ProcessType` are separate Python abstract categories.
`angelic {...}` may occur only after `interrupt`, not as the root of a `type`
section. An input/output Process behavior uses an infinite-delay node, for example:

```text
type forever interrupt angelic {ch? -> empty}
```

This corresponds to:

```python
InfiniteDelayType(InputType("ch", EmptyType()))
```
