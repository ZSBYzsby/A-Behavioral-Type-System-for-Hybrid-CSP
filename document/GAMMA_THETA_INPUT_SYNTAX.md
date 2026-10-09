# Shared parameters, Gamma, Theta, and complete HCSP input syntax

This reference defines how one source binds shared read-only parameters, the
typing environment `Gamma`, the channel environment `Theta`, and an HCSP Process
system, and how they map to the existing data model. The unified internal parser
implements this concrete syntax. Users call the package-root
`construct_hcsp_type(...)`, or append a `type` section and call
`check_hcsp_type(...)`. See [HCSP_INPUT_SYNTAX.md](HCSP_INPUT_SYNTAX.md) for
statement and expression subgrammars.

Parsing reuses existing representations:

- Optional `parameters(...) where(...)` becomes a `ParameterEnvironment`.
- Parsed `Gamma` is a read-only `Mapping[str, GammaType]`, with `BasicType`
  or `ContinuousType` values.
- Parsed `Theta` is a read-only `Mapping[str, ChannelType]`.
- The Process section becomes the existing `Process` or `Parallel` AST.

The public facade returns the final `TypeAST`, without exposing the parsed
Process AST. The internal parser passes the four related objects from the same
source to TypeConstructor, without introducing a second environment or Process
AST. Python mappings and node constructors below illustrate internal lowering;
users need not import these internal classes.

## 1. Design conventions

- Sections appear in order: `gamma`, optional `parameters`, `theta`, `process`.
  Gamma, Theta, and Process are mandatory; `parameters` may be omitted.
- `gamma(...)` and `theta(...)` enclose the environments; empty forms are
  `gamma()` and `theta()`.
- Shared parameters use `parameters(...)`. An omitted constraint and
  `where(true)` both normalize to a true background constraint.
- `process` must contain a nonempty HCSP system; single and parallel components
  both use `process_system`.
- Separate declarations with `,`, without a trailing comma.
- Environment sections do not use braces; `{...}` encloses systems and executable blocks.
- Environment sections do not use semicolons; `;` denotes sequential Process execution.
- Type names have one case-sensitive canonical spelling. Python API aliases are
  not accepted in user text.
- Identifiers follow `[A-Za-z_][A-Za-z0-9_]*`. Keywords and canonical type names
  cannot be declaration names.
- Whitespace and line breaks have no semantics. Comments use `// ...` and
  non-nested `/* ... */`.
- `expr` refers to the implemented strict expression grammar in `HCSP_INPUT_SYNTAX.md`.

## 2. Complete EBNF

```ebnf
program_prefix
    ::= gamma
        [ parameters ]
        theta
        process


constructor_source
    ::= program_prefix
        EOF


gamma
    ::= "gamma" "("
            [
                gamma_entry
                { "," gamma_entry }
            ]
        ")"


gamma_entry
    ::= IDENT ":" gamma_type


gamma_type
    ::= basic_type
      | continuous_type


continuous_type
    ::= "continuous" "("
            identifier_list
        ")"


parameters
    ::= "parameters" "("
            [
                parameter_entry
                { "," parameter_entry }
            ]
        ")"
        [ "where" "(" expr ")" ]


parameter_entry
    ::= IDENT ":" basic_type


theta
    ::= "theta" "("
            [
                theta_entry
                { "," theta_entry }
            ]
        ")"


theta_entry
    ::= IDENT ":" channel_type


channel_type
    ::= "channel" "("
            channel_slot
            { "," channel_slot }
        ")"
        [ "where" "(" expr ")" ]


channel_slot
    ::= IDENT ":" basic_type


basic_type
    ::= "Bool"
      | "Nat"
      | "Int"
      | "Rational"
      | "Real"


identifier_list
    ::= IDENT
        { "," IDENT }


process
    ::= "process" process_system


process_system
    ::= "{"
            statement_block
            { "," statement_block }
        "}"
```

`HCSP_INPUT_SYNTAX.md` defines `statement_block`, statements, ODEs, communication,
and `expr`. TypeConstructor consumes `constructor_source`; TypeChecker appends
a mandatory `type` section to the same `program_prefix`, as defined in
[TYPE_INPUT_SYNTAX.md](TYPE_INPUT_SYNTAX.md). Individual Gamma, parameter, Theta,
and Process parsers are fragment-level implementation interfaces used in tests,
not alternative complete-source formats.

## 3. Lowering Gamma

### 3.1 Scalar declarations

```hcsp
gamma(
    ready: Bool,
    count: Nat,
    offset: Int,
    ratio: Rational,
    position: Real
)
```

Each declaration maps to:

```python
{
    "ready": BasicType.BOOL,
    "count": BasicType.NAT,
    "offset": BasicType.INT,
    "ratio": BasicType.RATIONAL,
    "position": BasicType.REAL,
}
```

User input accepts only `Bool`, `Nat`, `Int`, `Rational`, and `Real`.
`String`, `Unit`, `Any`, tuples, and Python convenience aliases such as
`bool`, `integer`, and `R` are unsupported.

### 3.2 Continuous-evolution vector declarations

```hcsp
gamma(
    p: Real,
    v: Real,
    a: Real,
    vehicle_motion: continuous(p, v, a)
)
```

This becomes:

```python
{
    "p": BasicType.REAL,
    "v": BasicType.REAL,
    "a": BasicType.REAL,
    "vehicle_motion": ContinuousType(("p", "v", "a")),
}
```

`vehicle_motion` names an ODE vector declaration, not a scalar expression variable.
`continuous(p, v, a)` does not implicitly declare its members: each must separately
be declared `Real` in the same Gamma. Member declarations may precede or follow
the vector; the parser checks them after reading all of Gamma.

Vector members are interpreted as a set, so order does not affect matching with
ODE left-hand sides. Different continuous declarations may overlap or register
the same full set under different names. An ODE with user equations must match
one declaration's entire member set exactly; a strict subset or superset does not match.

The implicit ODE-local clock `t` is outside the user vector, is not added to Gamma,
and is excluded from vector comparison. It cannot occur in `continuous(...)`.
A scalar Gamma declaration may still be named `t`, but the hidden local clock
shadows it inside the ODE flow, domain, and safety. An empty-flow ODE needs no
continuous declaration.

### 3.3 Gamma structural checks

- Scalar and continuous declaration names share one namespace and must be unique.
  Duplicate declarations report the second occurrence rather than overwriting a dictionary entry.
- Continuous member lists are nonempty, contain distinct valid IDENTs, and each
  member has a separate same-name `Real` declaration.
- The implicit clock name `t` cannot be a continuous member.
- Continuous declarations do not carry safety properties; those come from the
  corresponding ODE's `safety(...)` annotation.
- `gamma()` is a valid empty Gamma.

## 4. Lowering shared read-only parameters

```hcsp
parameters(
    end: Real,
    vmax: Real,
    amin: Real,
    amax: Real
) where(
    end >= 0 and vmax >= 0 and amin < 0 and amax >= 0
)
```

This section becomes:

```python
ParameterEnvironment(
    {
        "end": BasicType.REAL,
        "vmax": BasicType.REAL,
        "amin": BasicType.REAL,
        "amax": BasicType.REAL,
    },
    parse_annotated_expression(
        "end >= 0 and vmax >= 0 and amin < 0 and amax >= 0"
    ),
)
```

Parameters use only the five `BasicType` values, excluding `continuous(...)`.
Names must be distinct and absent from Gamma. Free names in the constraint must
be declared parameters. TypeConstructor checks its Bool type, definedness, and
satisfiability. Omitting `parameters` means empty declarations with a true constraint.

Shared parameters are outside Gamma state and may be read by multiple parallel
Processes without violating state separation. This exception applies when the
complete-source parser knows the parameter declarations and constructs `Parallel`.
The low-level `parse_annotated_hcsp(...)` and direct `Parallel(...)` retain strict
Assumption 2.1 checks. TypeConstructor always rejects attempts to modify parameters
through assignment, input targets, ODE left-hand sides, or initial states.

## 5. Lowering Theta

### 5.1 Single-slot channels

```hcsp
theta(
    sensor: channel(value: Real) where(0 <= value and value <= 100),
    tick: channel(code: Nat)
)
```

The result is equivalent to:

```python
{
    "sensor": ChannelType(
        (BasicType.REAL,),
        refinement=parse_annotated_expression("0 <= value and value <= 100"),
        binders=("value",),
    ),
    "tick": ChannelType(
        (BasicType.NAT,),
        refinement=True,
        binders=("code",),
    ),
}
```

Omitting `where(...)` gives a `true` refinement. Explicit `where(true)` normalizes
to the same representation, avoiding redundant semantically identical structures.

### 5.2 Multiple-slot channels

```hcsp
theta(
    state: channel(position: Real, velocity: Real)
        where(position >= 0 and velocity >= 0),
    result: channel(index: Nat, accepted: Bool)
)
```

The first declaration becomes:

```python
ChannelType(
    (BasicType.REAL, BasicType.REAL),
    refinement=parse_annotated_expression(
        "position >= 0 and velocity >= 0"
    ),
    binders=("position", "velocity"),
)
```

Slot order must match input targets in `ch?(x1, ..., xn)` and output payloads in
`ch!(e1, ..., en)`. Multiple slots are not a tuple value type; each carries an
individual `BasicType` scalar.

### 5.3 Name scope in refinements

- Slot names are local binders scoped to their channel's `where(...)`.
- Binders are distinct within one channel; different channels may reuse names.
- In a refinement, local binders shadow same-name Gamma scalars or shared parameters.
- Refinements may also refer to Gamma scalars and shared read-only parameters
  supplied by the complete typing judgment.
- A `ContinuousType` declaration name has no scalar value and cannot be an expression variable.
- Every refinement must have type `Bool`. Parsing stores syntactically valid
  `Expr` nodes; construction/checking environment preparation validates binders,
  free names, and types for every Theta entry, including unused channels.
  T-In/T-Out handle expression definedness and proofs after substituting actual
  communication values. Successful parsing establishes concrete syntax; successful
  backend preparation establishes Theta's static semantics.

### 5.4 Theta structural checks

- Channel names are unique within Theta; duplicates cannot silently overwrite entries.
- `channel(...)` has at least one slot; zero-argument unit communication is unsupported.
- Slots use `BasicType`, excluding `continuous(...)` and tuple types.
- Syntax pairs each slot with a binder; binders are distinct within a channel.
- An omitted `where(...)` means `true`; an explicit refinement must parse as `Expr`
  under the strict expression grammar.
- User text produces project `Expr` refinements. Python callables and raw Z3
  formulas are programmatic implementation capabilities outside this concrete syntax.
- `theta()` is a valid empty Theta.

## 6. Complete example

```hcsp
gamma(
    p: Real,
    v: Real,
    a: Real,
    mode: Int,
    enabled: Bool,
    vehicle_motion: continuous(p, v)
)

parameters(
    limit: Real
) where(limit >= 0)

theta(
    command: channel(acceleration: Real)
        where(-2 <= acceleration and acceleration <= 2),
    state: channel(position_out: Real, velocity_out: Real),
    switch: channel(next_mode: Int, active: Bool)
        where(0 <= next_mode and next_mode <= 3)
)

process {
    {
        command?(a);
        ode(
            flow(
                dot p = v,
                dot v = a
            ),
            domain(t <= 1),
            safety(p * p + v * v <= 100),
            delay(1)
        );
        state!(p, v)
    }
}
```

This example illustrates parsing and environment lowering. Its safety annotation
is not guaranteed for arbitrary initial states; parsing success alone does not
establish a trusted Type. For verified runnable examples, see the
[Public API guide](PUBLIC_API_GUIDE.md#2-minimal-runnable-examples).

Parsing produces four related objects from this source. Shared parameters become
`ParameterEnvironment({"limit": BasicType.REAL}, limit >= 0)`; the environments are:

```python
gamma = {
    "p": BasicType.REAL,
    "v": BasicType.REAL,
    "a": BasicType.REAL,
    "mode": BasicType.INT,
    "enabled": BasicType.BOOL,
    "vehicle_motion": ContinuousType(("p", "v")),
}

theta = {
    "command": ChannelType(
        (BasicType.REAL,),
        parse_annotated_expression("-2 <= acceleration and acceleration <= 2"),
        ("acceleration",),
    ),
    "state": ChannelType(
        (BasicType.REAL, BasicType.REAL),
        True,
        ("position_out", "velocity_out"),
    ),
    "switch": ChannelType(
        (BasicType.INT, BasicType.BOOL),
        parse_annotated_expression("0 <= next_mode and next_mode <= 3"),
        ("next_mode", "active"),
    ),
}
```

The internal `ParsedHCSPSource.process` field stores the formal Process AST
produced from `process {...}`, not a string or a duplicate set of node definitions.
This record passes internally between `parse_hcsp_source(...)` and TypeConstructor;
it is not a public return value.

## 7. Complete-source and internal fragment interfaces

Users call the package-root construction interface once:

```python
from hcsp_typechecker import construct_hcsp_type

type_ast = construct_hcsp_type(
    source,
    source_name="example.hcsp",
    initial_states=None,
    path_condition=True,
    output="full",
)
```

The interface binds parameters, Gamma, Theta, and the Process AST from the same
source and starts construction internally. Intermediate objects are not returned.
Internal judgments, `TypeConstructionRequest`, and parsing records are not
constructed through the package-root API.

Without a `type` section, TypeConstructor constructs the Type. Appending
`type configuration_type` to the same source enables TypeChecker to check it.
See [TYPE_INPUT_SYNTAX.md](TYPE_INPUT_SYNTAX.md) for syntax and
[TYPE_CHECKER.md](TYPE_CHECKER.md) for the algorithm.

Arguments, output modes, returns, and errors are documented centrally in
[Public API guide](PUBLIC_API_GUIDE.md), and the
[Complete project reference](PROJECT_FUNCTION_REFERENCE.md#public-interface-inputs-and-outputs).
This syntax reference does not duplicate their presentation contracts.

These internal implementation entry points remain available:

```python
from hcsp_typechecker.frontend.annotated_hcsp_syntax import parse_annotated_hcsp
from hcsp_typechecker.frontend.type_constructor_frontend import parse_hcsp_source
from hcsp_typechecker.frontend.typing_context_syntax import parse_typing_context
from hcsp_typechecker.backend.type_constructor import construct_type
```

`parse_hcsp_source(...)` returns internal `ParsedHCSPSource`;
`parse_typing_context(...)` parses only the `gamma [parameters] theta` prefix;
`parse_annotated_hcsp(...)` parses a `process_system` fragment;
`construct_type(...)` accepts an internal `TypeConstructionRequest`.
They support implementation, testing, and rule review and are outside the
package-root API and user compatibility contract.

The parser retains declaration tokens and checks duplicates before dictionary
insertion. After reading Gamma, it checks continuous-member forward references,
duplicates, and Real types. All top-level sections share one token stream, preserving
comments, global line/column positions, and diagnostic spans without first splitting
the source into text sections.
