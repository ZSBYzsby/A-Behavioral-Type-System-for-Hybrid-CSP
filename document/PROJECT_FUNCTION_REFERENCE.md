# HCSP Behavioral Type Constructor and Checker: complete reference

Table 2 of *A Behavioral Type System for Hybrid CSP* supplies the rules.
The implementation makes explicit choices for multiple scalar communication
slots, control-node continuations, shared Gamma, read-only parameters, implicit
ODE clocks, candidate rules, and three-valued proofs. For rule-level mathematical
operations, start with [Implementation semantics](IMPLEMENTATION_SEMANTICS.md),
then use this reference for modules, input, and interfaces. The project uses
Section 2.1 syntax and carries Section 4.2/4.3 safety, delay, and recursion annotations:

- Shared parameters, Gamma, Theta, and HCSP Process appear in one complete source.
- The two HCSP interfaces parse internally: construction produces a Type AST;
  checking verifies a supplied final Type section.
- Continuous Gamma entries register complete ODE vectors; trajectory properties come from ODE safety.
- Internal conclusions are configuration, system, Process, or event judgments.
- Each `rule_t_*` returns `RuleExpansion(premises, conclude)` without recursive rule execution.
- T-Assign deterministically creates a lazy strongest post-state, without synthesizing unknown phi'.
- An explicit-stack evaluator handles child judgments and combines Types bottom-up.
- Concrete state/FOL/dL formulas are simplified and proved in premise order by
  Z3/KeYmaera X. False short-circuits; unknown retains evidence and continues construction.
- Finite `ODE;skip` tries two Table 2 rules in order and selects using immediate premise results.
- Only true returns a trusted Type AST. False or incomplete construction raises
  `HCSPTypeConstructionError`; complete unknown candidates are available through
  `HCSPUntrustedTypeConstructionError.untrusted_type` for review.

**TypeConstructor** constructs Types; **TypeChecker** checks supplied Types.
Both are implemented and share expansion, expression semantics, and provers,
without importing each other. See Public interface inputs and outputs below.

## Obtain source and prepare the environment

Python 3.10–3.13 is supported. Clone the repository, create a virtual environment,
and install `requirements.txt` to run from source, without building a wheel/sdist.
Alternatively, editable installation is documented in the root README.
Run the following commands from the repository root.

Windows PowerShell:

```powershell
py -m venv .venv
.\.venv\Scripts\python -m pip install --upgrade pip
.\.venv\Scripts\python -m pip install -r requirements.txt
.\.venv\Scripts\python -m hcsp_typechecker
```

Linux/macOS:

```bash
python3 -m venv .venv
. .venv/bin/activate
python -m pip install --upgrade pip
python -m pip install -r requirements.txt
python -m hcsp_typechecker
```

The only Python runtime dependency is `z3-solver`. HCSP and expression ASTs are
project-defined; external tool objects or duck-typed objects with `.type` or
similar fields are not accepted.

Source execution has two capability levels:

1. **Core mode** needs Python and Z3: Process ASTs, Type construction, discrete
   checking, and generation of ODE dL obligations.
2. **Full mode** additionally needs Java 17+ and KeYmaera X to prove external dL goals.

KeYmaera X is external, and the repository does not include `keymaerax.jar`.
Obtain its official distribution and configure environment variables without
editing Python source. Java lookup uses `KEYMAERAX_JAVA`, then
`JAVA_HOME/bin/java`, then `PATH`; explicit `KEYMAERAX_JAVA` is optional when Java is discoverable.

Windows PowerShell:

```powershell
$env:KEYMAERAX_JAR = "C:\tools\keymaerax.jar"
$env:KEYMAERAX_JAVA = "C:\Program Files\Java\jdk-21\bin\java.exe"
$env:KEYMAERAX_HOME = "$PWD\.keymaerax-home"
$env:KEYMAERAX_TIMEOUT = "60"
python -m hcsp_typechecker --require-keymaerax
```

Linux/macOS:

```bash
export KEYMAERAX_JAR="$HOME/tools/keymaerax.jar"
export KEYMAERAX_JAVA="$(command -v java)"
export KEYMAERAX_HOME="$PWD/.keymaerax-home"
export KEYMAERAX_TIMEOUT=60
python -m hcsp_typechecker --require-keymaerax
```

To retain generated `.kyx/.kyp` evidence, also set:

```text
KEYMAERAX_KEEP_ARTIFACTS=true
KEYMAERAX_ARTIFACTS=<writable-output-directory>
KEYMAERAX_CLI_STYLE=auto
KEYMAERAX_TACTIC=auto
KEYMAERAX_ARITHMETIC_TOOL=Z3
```

Without KeYmaera X, core mode and tests using controlled prover fixtures still
work. Goals requiring external dL proof explicitly become unknown, rather than
assumed true/false. The doctor exits successfully for a usable core environment;
`python -m hcsp_typechecker --require-keymaerax` additionally requires Java and the jar.

## Section 2.1 syntax

Core ASTs correspond to the paper's productions:

```text
E ::= empty
    | (ch?(x1,...,xn) -> P) [] E
    | (ch!(e1,...,en) -> P) [] E

P ::= skip | x := e | assert(B)
    | ch?(x1,...,xn) | ch!(e1,...,en)
    | if B then P else P'
    | <dot(v)=e & B> |> E
    | P; P' | P |~| P' | X | mu X.P

S ::= P | S || S'
```

Users construct Types through `construct_hcsp_type(...)`. It parses complete input
under [GAMMA_THETA_INPUT_SYNTAX.md](GAMMA_THETA_INPUT_SYNTAX.md), binds shared
parameters, Gamma, Theta, and Process from that source, and starts construction:

```python
from hcsp_typechecker import construct_hcsp_type

source = """
gamma(x: Int)
parameters(limit: Int) where(limit >= 0)
theta(ch: channel(value: Int) where(value <= limit))
process {{ch?(x); ch!(x)}}
"""

type_ast = construct_hcsp_type(
    source,
    source_name="example.hcsp",
    output="result",
)
```

Parsed environments and Process ASTs remain internal. The facade creates required
configurations and interleaves construction with proof. False stops immediately;
unknown retains evidence and continues. Complete all-true construction returns
trusted TypeAST; complete unknown construction raises
`HCSPUntrustedTypeConstructionError`, exposing the candidate only as `untrusted_type`.

Output modes are:

- `none`: default; no printing.
- `result`: final verdict and canonical trusted Type, complete untrusted candidate
  with its trust status, or failure reason and partial progress.
- `full`: original input, environment summary, construction progress, rule steps,
  FOL/dL formulas, backend results, unresolved obligations, and trust status.
  It does not print Process AST objects or reprs.

Presentation does not change returned objects, proofs, or exceptions. `stream=`
redirects to a text stream. See Public interface inputs and outputs for complete
arguments and failure handling. Lexical, syntax, and source-structure errors
raise `HCSPInputError` with source name, line, column, and diagnostic span.

`parse_hcsp_source`, `parse_hcsp`, `parse_expression`, `construct_type`, and direct
AST constructors are internal implementation and review interfaces, outside
package-root compatibility guarantees. Users need not construct
`TypeConstructionRequest`, internal judgments, or `TypeConstructionReport`.

To edit short complete inputs and inspect results, run from the repository root:

```text
python examples/demo_type_construction.py
```

[GAMMA_THETA_INPUT_SYNTAX.md](GAMMA_THETA_INPUT_SYNTAX.md) is the implemented
root grammar binding parameters, Gamma, Theta, and Process.
`HCSP_INPUT_SYNTAX.md` defines its Process/Expr subgrammars.

The following concrete Process/Expr nodes and Python constructors describe
internal representations for maintainers, not the stable user API.

`Sequence` and `Parallel` are binary nodes. `If`, n-ary `InternalChoice`, and
`ODE` own common continuations and end their sequence spines. E occurs only in
ODE interrupts. `Sequence.of(...)`, `InternalChoice.of(...)`, `EventChoice.of(...)`,
and `Parallel.of(...)` construct the corresponding normalized recursive ASTs.

`(if B then P else P');Q`, `(P_1 |~| ... |~| P_n);Q`, and `ODE;Q` store Q in
`If.continuation`, `InternalChoice.continuation`, and `ODE.continuation`.
Internal choice uses `InternalChoice(P_1,...,P_n,continuation=Q)`. Omitting Q in
the programmatic constructor still stores `Skip()`.
Direct `Sequence(If(...),Q)`, `Sequence(InternalChoice(...),Q)`, and
`Sequence(ODE(...),Q)` are invalid; `Sequence.of(...)` absorbs Q into those nodes.

Default Skip is an empty structural placeholder. Tail checking ignores trailing
skips, so a branch-ending X remains tail-recursive. If any other Process remains
after skips are ignored, T-X rejects the back edge.

T-sqcup derives `P;Q` and `P';Q` independently and combines their Types as internal
choice; no generic type-level T-Seq is needed.

Channel, state, Process, and Type variable names use `[A-Za-z_][A-Za-z0-9_]*`.
User source also excludes reserved words: `chan`, `channel_1`, and `_private` are
valid; `channel` is reserved. Unicode/compatibility names, whitespace, `1channel`,
`a-b`, `a.b`, and names with surrounding whitespace are rejected at AST/environment boundaries.

A finite delay d must be a nonnegative rational. Programmatic input accepts int,
float, Decimal, Fraction, and constant rational arithmetic. Negative values,
symbolic values, Bool, NaN, and infinities are invalid finite delays; ordinary ODE
annotations separately permit positive infinity.

Every ordinary `ODE(...)` creates an independent `ODELocalClock`, initialized to
0 with derivative 1. Users need not declare it in equations, Gamma, or initial state:

```python
ode = ODE(
    [("x", "t + 1")],
    True,
    annotation=ODEAnnotation(safety=True, delay=5),
)

assert ode.local_clock.name == "t"
assert ode.local_clock.initial_value == Literal(0)
assert ode.local_clock.derivative == Literal(1)
```

Within ODE right-hand sides, domain, and safety, t reads the implicit local clock.
For this example, declare x as Real and register
`ode_x: ContinuousType(("x",))`; t needs no declaration or initial value and is
excluded from ODE-vector matching. The example has true domain/safety.
An ODE owns its continuation; a non-skip finite continuation requires an exact
boundary goal. Without the external prover, unresolved goals make any complete
candidate untrusted. Domain/safety can instead be `t < 5 and x < 20` and `x >= t`.
Users cannot provide a t left-hand side, since `t'=1` is automatic. Local t is
excluded from Gamma, `fv`, `bv`, `get_vars()`, and parallel ownership V, and is not
in scope in interrupt or external continuations. Persistent clocks there require
ordinary declared state variables. Each ODE, including parallel ODEs, has a fresh
internal Real clock symbol shared by that ODE's dL formulas.

The hidden clock measures elapsed time without inserting a delay boundary into
the user domain. Delay remains an explicit annotation. Finite natural timeout
requires proof of the exact boundary; to end at d, give an explicit strict domain
boundary, for example `t < 5`.

### Assumption 2.1 construction checks

The project checks `fv(S) ∩ bv(S) = ∅`. Input adds all xi to bound value variables
and binds occurrences in its sequential/event continuation. `mu X.P` binds X in
P. A name remaining free outside its binding scope causes composite AST constructors
to raise `ValueError`.

`ch?(x,y); assert(x >= 0 and y >= 0)` is valid. In contrast,
`assert(x >= 0); ch?(x,y)`, free/bound x in different choice branches, or free/bound
Process X in one system violates the condition.

The implementation lets input in one branch of a composite prefix bind its
common sequential continuation. Thus
`If(B,InputChannel("ch",("x",)),Skip(),continuation=P_using_x)` is structurally
valid without requiring every prefix branch to bind x.

`Parallel(S1,S2)` requires disjoint variable sets `V = fv ⊎ bv`, input-channel sets
iCh, and output-channel sets oCh. A same-channel input/output pair remains valid
for synchronization. Violations raise `ValueError` before TypeConstructor starts.

### Assumption 2.2 construction checks

`Mu("X",body)` requires every bound `Var("X")` to be preceded by input/output
on every path reaching it. Assignment, assertion, skip, and ODE evolution do not
count as communication. An unguarded path raises `ValueError`.

The check traverses sequences, conditionals, choices, and interrupt continuations,
respecting shadowing by an inner same-name Mu. Interrupt communication guards
its branch, but cannot guard the ODE's natural continuation.
Core traversals use explicit stacks for long Processes, deep Type continuations,
construction/checking, and normalized term graphs. End-to-end stress tests
serialize large actual constructed Types for checking and graph generation,
preventing inconsistent artificial depth limits. Graph limits control reachable
state/edge counts separately from AST depth.

## Section 4.2/4.3 annotations

Annotations attach to existing ODE and mu nodes without adding new P nodes:

```text
ODE:  <dot(v)=e & B>_safety |>[delay] E
mu:   mu X_invariant.P
```

The corresponding Python constructors are:

```python
ode = ODE(
    [("x", 1)],
    "x < 10",
    annotation=ODEAnnotation(
        safety="x <= 10",
        delay=2,
    ),
)

loop = Mu(
    "X",
    Sequence.of(OutputChannel("tick", (0,)), Var("X")),
    annotation=RecursionAnnotation("x >= 0"),
)
```

At the programmatic AST level, omitted safety/invariant means true. Each ODE
requires `ODEAnnotation` with delay. Finite delay is a statically evaluable
nonnegative rational; positive infinity is also valid. Symbolic values, negatives,
Bool, NaN, and negative infinity fail immediately at construction.

`ODEAnnotation` stores safety and delay. Automatic `local_clock` is a separate
read-only ODE field, not another annotation or user constructor argument.

Finite delays normalize to exact Fractions. These are valid:

```python
from decimal import Decimal
from fractions import Fraction

ODEAnnotation(delay=2)
ODEAnnotation(delay=0.5)                 # Normalizes to Fraction(1, 2).
ODEAnnotation(delay=Decimal("0.125"))    # Normalizes to Fraction(1, 8).
ODEAnnotation(delay=Fraction(2, 3))
ODEAnnotation(delay="1 / 4 + 1 / 4")     # Constant arithmetic: Fraction(1, 2).
ODEAnnotation(delay=float("inf"))
```

These raise `ValueError`:

```python
ODEAnnotation()                 # Missing delay.
ODEAnnotation(delay=-1)         # Negative delay.
ODEAnnotation(delay="d")        # Symbolic delay.
ODEAnnotation(delay="sqrt(2)")  # Cannot be statically evaluated as a rational.
ODE([("x", 1)], True)           # Missing ODEAnnotation.
```

## Run the demos and paper cases

After cloning and installing dependencies, run from the repository root:

```text
python -m hcsp_typechecker
python examples/demo_type_construction.py
python examples/demo_type_checking.py
python examples/demo_type_transition_graph.py
```

The checking demo should report `2/2` expected outcomes. Type construction
can report complete but unverified ODE candidates when KeYmaera X is unavailable.
Configure the external prover before running the ODE round trip and paper cases:

```text
python examples/demo_ode_type_round_trip.py
python examples/case_study_original.py --d 1
python examples/case_study_revised.py --d 1
```

The original case intentionally reproduces an unverified candidate. The revised
case should return a trusted Type, build a complete graph, and report all five
behavioral properties as true. Each script documents its expected outcome in
its header; the two case-note files explain the paper inputs and assumptions.

The paper's Section 4.3 recursion example can use complete user syntax:

```python
from hcsp_typechecker import construct_hcsp_type

source = """
gamma()
theta(
    ch: channel(received: Real) where(received >= 1),
    dh: channel(sent: Real) where(sent >= 0)
)
process {{
    mu X invariant(true) {
        ch?(x);
        dh!(sqrt(x));
        call X
    }
}}
"""

type_ast = construct_hcsp_type(source, output="full")
# Reports use canonical Type syntax: type mu t1. forever interrupt angelic {...}
```

## Public interface inputs and outputs

This section distinguishes stable interfaces from internals. For parameter
details, result fields, exception patterns, and end-to-end examples, use the
[Public API guide](PUBLIC_API_GUIDE.md).

The package-root stable export list contains:

- Four operations: `construct_hcsp_type`, `check_hcsp_type`,
  `build_type_transition_graph`, and `analyze_type_lock_freedom`.
- Result types: `TypeAST`, `TypeTransitionGraph`, and `LockFreedomReport`.
- Output enum: `OutputMode`.
- Six exceptions: `HCSPInputError`, `HCSPTypeConstructionError`,
  its subclass `HCSPUntrustedTypeConstructionError`, `HCSPTypeCheckingError`,
  `HCSPTypeTransitionGraphError`, and `HCSPTypeLockAnalysisError`.
- Four category enums: `TypeConstructionErrorKind`, `TypeCheckingErrorKind`,
  `TypeTransitionGraphErrorKind`, and `TypeLockAnalysisErrorKind`, plus `HCSPErrorDetail`.

The constructor signature is:

```text
construct_hcsp_type(
    source,
    *,
    source_name="<input>",
    initial_states=None,
    path_condition=True,
    output=OutputMode.NONE,
    stream=None,
    z3_timeout_ms=5000,
    keymaerax_timeout_seconds=None,
) -> TypeAST
```

The checker entry point is:

```text
check_hcsp_type(
    source,
    *,
    source_name="<input>",
    initial_states=None,
    path_condition=True,
    output=OutputMode.NONE,
    stream=None,
    z3_timeout_ms=5000,
    keymaerax_timeout_seconds=None,
) -> TypeAST
```

It requires a final `type configuration_type` after the same program sections,
checks it as the conclusion of each rule judgment, and raises
`HCSPTypeCheckingError` on failure.

- Source includes Gamma, optional Parameters, Theta, and Process; parsed
  environments/ASTs remain internal to the call.
- One Process accepts one state mapping; parallel input requires one per component
  in source order. Omission gives empty states.
- Initial states may cover a Gamma-scalar subset, excluding undeclared names,
  shared parameters, and ContinuousType labels. Declared BasicType input targets
  may have initial values that later input replaces.
- `path_condition` defaults to true and also accepts a strict expression string.
  String syntax failures raise source-located `HCSPInputError`.
- Timeouts change waiting limits, not mathematical rules.

Only a true verdict with a complete Type returns TypeAST normally. Static,
structural, or false-proof failure stops construction and raises
`HCSPTypeConstructionError`. Unknown retains evidence and continues; a complete
candidate raises `HCSPUntrustedTypeConstructionError` with `untrusted_type`,
while incomplete results use the parent exception. Candidates remain untrusted
until unresolved obligations are proved. Construction errors expose `verdict`,
`kind`, `phase`, `reason`, `rule`, `location`, `details`, `partial_types`, and
`format_result()/format_full()`. Checking has its own categories plus
`type_mismatch_detected` and three-valued `type_structure_matched`.
Frontend errors raise `HCSPInputError` before business backends start.

Checking returns the supplied TypeAST only with complete structural matching
and all premises true. Mismatch, static-rule failure, or false proof raises
`HCSPTypeCheckingError`. Unknown continues through remaining structure where
possible. If no mismatch or definite failure takes precedence, unresolved proofs
raise `kind="proof-unknown"`; an unverified Type is never accepted.
Constructor exception handling follows:

```python
from hcsp_typechecker import (
    HCSPInputError,
    HCSPTypeConstructionError,
    HCSPUntrustedTypeConstructionError,
    construct_hcsp_type,
)

try:
    type_ast = construct_hcsp_type(
        source,
        source_name="example.hcsp",
        output="result",
    )
except HCSPInputError as error:
    # Result mode already printed diagnostics; inspect error.kind or set an exit code.
    pass
except HCSPUntrustedTypeConstructionError as error:
    # Result mode printed the candidate; its AST remains in error.untrusted_type.
    pass
except HCSPTypeConstructionError as error:
    pass
```

Output strings also have enum forms `OutputMode.NONE/RESULT/FULL`. Return values
are ASTs, not rendered logs; candidates occur only on exceptions. None prints
nothing, result prints outcomes/candidates/failures, and full includes input,
rules, FOL/dL goals, proofs, unresolved obligations, and trust status. Constructor
full reports add environment summaries; checking environments appear in rule
steps. Neither exposes Process reprs. Output defaults to stdout, redirected by stream.

Reported Types use [Canonical user Type syntax](TYPE_INPUT_SYNTAX.md) with a
complete `type` prefix, without a parallel Python repr. Text after `Type source :`
can be copied into input and parsed again by checking.

Users choose shared parameter values before execution, with every legal valuation
satisfying the source where constraint. Parameters are outside component Gamma
state and are readable in parallel Processes, refinements, recursion invariants,
and ODE formulas, but cannot be modified by states, assignment, input, or ODEs. For example:

```hcsp
gamma(
    p: Real,
    v: Real,
    a: Real,
    vehicle_ode: continuous(p, v, a)
)
parameters(
    end: Real,
    vmax: Real,
    amin: Real,
    amax: Real
) where(end >= 0 and vmax >= 0 and amin < 0 and amax >= 0)
theta()
process {{skip}}
```

For parameter constraint H and configuration path phi, T-sigma checks
`H -> phi[sigma]`; later rules use `H and phi`. The result covers every parameter
valuation satisfying H, not just an instance. Construction also checks H is
satisfiable, rejecting vacuous proofs from inconsistent constraints.

p, v, and a are scalar Gamma values; vehicle_ode registers only a complete ODE
vector and cannot be read, assigned, or input-bound. User left-hand sides must
exactly match a continuous set, independent of order. Strict subsets/supersets fail.
Empty-flow ODEs need no declaration. Safety properties occur only in safety;
the implicit t clock is outside Gamma and vector matching.

Internal `construct_type` returns `TypeConstructionReport` with verdict,
obligations, diagnostics, and rule evidence. The public facade returns trusted
Types only, raises construction errors on definite failure, and delivers complete
unknown candidates through untrusted exceptions. Formal Bottom is unreachable/error
behavior, not an internal construction-failure placeholder. Finite T-unrhd uses
Bottom for an unreachable deadline continuation; T-unrhd' uses Empty for a real empty continuation.

## Architecture and project-defined ASTs

The implementation separates a stable facade, input structures, two Table 2
backends, Table 3 operational semantics, and lock analysis:

- `hcsp_typechecker.api`: orchestrates complete-source construction, typed-source
  checking, graph construction, and analysis, with uniform errors/output.
  Intermediate Process ASTs remain internal.

- `frontend.annotated_hcsp_syntax`: annotated Process/Expr fragment lowering.
- `frontend.typing_context_syntax`: Gamma/Theta/parameter fragment lowering.
- `frontend.type_syntax`: supplied Type parsing and canonical formatting.
- `frontend.normalized_type_syntax`: read-only normalized AST presentation with
  flattened choices, anonymous `mu`, and `recursion_position`; no parser.
- `frontend.type_transition_graph_syntax`: read-only metadata, states, edges,
  and Table 3 evidence; no parser.
- `frontend.type_constructor_frontend`: complete-source lexer, locations, and
  parameters/Gamma/Theta/Process binding for construction.
- `frontend.type_checker_frontend`: final Type parsing and binding with the parsed program.
- `data_structures.process_ast`: expressions e/B, Section 2.1 E/P/S nodes,
  and Section 4.2/4.3 ODE/Mu annotations.
- `data_structures.type_ast`: Section 4.1 T/A and Section 4.2 configuration Types,
  alpha equivalence, and direct Type AST analysis/transformation.
- `data_structures.normalized_type_ast`: finite De Bruijn ASTs for graph compilation
  and display; finite unfolding differences remain structurally visible.
- `data_structures.regular_type_term_graph`: finite cyclic representations and
  bisimulation-minimized equi-recursive state keys.
- `data_structures.type_transition_graph`: states, labels, transitions, and evidence.
- `data_structures.runtime_context`: Gamma/Theta/parameters/Configuration,
  basic types, continuous vectors, and channel refinements.
- `backend.common`: four conclusion judgments, two premise categories, Table 2
  expansion, environment normalization, shared results/evidence, expression logic,
  dL formulas, and KeYmaera X adaptation.
- `backend.type_constructor`: construction requests/reports and composition of
  child conclusions into Type ASTs.
- `backend.type_checker`: supplied-subtree rule checking and its requests/reports;
  both Table 2 backends depend on common, not each other.
- `backend.type_operational_semantics`: term-graph Table 3, bisimulation minimization,
  and BFS closure, independent of construction/checking.
- `data_structures.type_lock_analysis`: property reports, paths, and witnesses.
- `backend.type_lock_analysis`: CSR indexing and iterative BFS/DFS analysis.
- `frontend.type_lock_analysis_syntax`: read-only property and witness formatting.
- `tooling`: cross-platform environment diagnostics.

All module paths above are relative to `hcsp_typechecker`.

Dependencies flow in one direction: frontends convert text to domain structures;
common provides rule/proof infrastructure over those structures; construction
and checking each depend on common plus data structures, without mutual imports.
The outer api facade composes frontend and backend calls.

The root `hcsp_typechecker.__all__` is the explicit stable export list:

```text
HCSPErrorDetail, HCSPInputError, HCSPTypeConstructionError,
HCSPTypeCheckingError, HCSPTypeTransitionGraphError,
HCSPTypeLockAnalysisError, HCSPUntrustedTypeConstructionError, OutputMode,
TypeAST, TypeCheckingErrorKind, TypeConstructionErrorKind,
TypeTransitionGraphErrorKind, TypeLockAnalysisErrorKind,
TypeTransitionGraph, LockFreedomReport,
construct_hcsp_type, check_hcsp_type,
build_type_transition_graph, analyze_type_lock_freedom
```

Users depend only on these names. Parsing helpers, construct_type, concrete
nodes, judgments, obligations, and backend configuration are obtained from
internal subpackages without compatibility guarantees. Future Type analysis
should first define a facade contract before joining the root export list.

Each rule expands one level, with Process/System result categories kept distinct.
T-Assign represents a lazy strongest post-state through the pre-path and updated
symbol map; the evaluator proves already concrete formulas only.

Finite continuous behavior uses `FiniteDelayType(d,A,T)`. Paper-style display
abbreviates based on A/T: `delay(d).T`, `delay(d) \unrhd A`, or the full form.
An omitted natural continuation stores Bottom; a reachable normal empty one
stores Empty. Infinite delay uses `InfiniteDelayType(A)`, fixing timeout to
unreachable Bottom and retaining sequential behavior only in actual communication
continuations. EmptyType is the unique normal empty communication behavior.
External choices normalize empty/single branches to NoInterrupt or Input/Output.

These expression strings and constructors are internal review examples.
Users put equivalent content in complete source:

```python
from hcsp_typechecker.data_structures.process_ast import (
    Assert,
    Assign,
    BinaryExpr,
    CompareExpr,
    InputChannel,
    Literal,
    OutputChannel,
    Sequence,
    Variable,
    ensure_expr,
)
from hcsp_typechecker.data_structures.runtime_context import BasicType, ChannelType

expr = BinaryExpr("+", Variable("x"), Literal(1))
hp = Sequence.of(
    Assign("x", expr),
    Assert(CompareExpr((Variable("x"), Literal(0)), (">=",))),
)

# Expressions return scalar BasicTypes; Gamma uses ContinuousType to register ODE sets.
scalar_value = ensure_expr("x + 1")
multi_channel = ChannelType(
    (BasicType.INT, BasicType.BOOL),
    "eta1 >= 0 and eta2",
)
multi_input = InputChannel("data", ("x", "ready"))
multi_output = OutputChannel("data", ("x", "ready"))
```

Construction dispatches with isinstance. Objects outside HCSP fail structurally
even if they have fields named type, hps, or expr.

Expressions support scalar literals, variables, arithmetic, comparisons, Boolean
connectives, and simple calls. There is no tuple expression or TupleType;
tuple/list values fail construction. Results have one BasicType. ContinuousType
is a declaration label without expression value. ChannelType stores a nonempty
BasicType slot sequence; communication nodes store matching target/payload
sequences. Their Python tuples are argument lists, not tuple-valued expressions.
Each payload produces one scalar, and refinements may reference all slot binders.
Conditional expressions are unsupported; use Process `If(B,P,P',continuation=Q)`,
whose programmatic omitted continuation defaults to Skip.

Translation retains a Z3 term, BasicType, and definedness. `/` is real division
with explicit promotion of integer operands. Rules prove nonzero divisors and
nonnegative sqrt arguments at the corresponding premise. `%` accepts only Nat/Int.
Division by zero, negative square roots, or Real modulo produce auditable false
obligations/diagnostics rather than adopting Z3's total-function extensions or leaking Z3Exception.

## ODE proof backend

ODEAnnotation supplies safety/delay, and the ODE adds its hidden clock.
Construction creates formal dL obligations and uses the built-in KeYmaera X adapter:

```python
from hcsp_typechecker import construct_hcsp_type

source = """
gamma(x: Real, ode_x: continuous(x))
theta(done: channel(value: Int))
process {{
    ode(
        flow(dot x = 1),
        domain(x < 1),
        safety(x <= 1),
        delay(1)
    );
    done!(0)
}}
"""

type_ast = construct_hcsp_type(
    source,
    initial_states={"x": 0},
    path_condition="x == 0",
    output="full",
)
```

The adapter creates a single-goal kyx archive and launches an independent process,
supporting legacy 5.1.x `-prove` and modern `prove` CLI styles. Goals include:

- Safety: `pre_with_t=0 → [{ODE,t'=1}](t≤d → safety)`.
- Communication-guaranteed domain: `pre_with_t=0 → [{ODE,t'=1}]B`.
- Finite natural-timeout boundary: prove `(t<d → B) ∧ (t=d → ¬B)` under
  domain-free dynamics `{ODE,t'=1}`. Communication-only conclusions have no
  natural timeout and do not generate this goal.

Every source ODE needs an explicit continuation, including `;skip` when there is
no substantive continuation. It lowers into the ODE field, not external Sequence.
ODE;skip isolates communication-guaranteed and natural-timeout candidates and
selects using immediate domain/boundary results. Unselected evidence remains
for review. Non-skip successors use natural timeout only. The two Types differ
in Bottom versus reachable Empty continuations, with different premises and child judgments.

Post-contexts are distinct: communication-guaranteed interrupts use `B ∧ safety`;
natural-timeout interrupts use safety; natural continuation uses `¬B ∧ safety`.
Separate internal enum values represent these meanings rather than one ambiguous flag.
Each post-context also retains the prepared shared parameter condition and scalar
type-domain constraints; see
[Symbolic post-ODE contexts](TYPE_CONSTRUCTOR.md#96-symbolic-post-ode-contexts).

Infinite delay avoids finite-boundary comparisons but retains the local clock.
Nontrivial safety/domain modalities still contain entry t=0 and derivative t'=1.

PROVED maps to true; definite counterexamples map to false. Incomplete proof,
timeout, parse failure, missing environment, or unsupported reliable translation
maps to unknown. True safety is discharged locally; finite natural boundaries
still require proof. False stops the rule; unknown preserves obligations while
structural derivation continues.

Reliable translation covers real/integer constants and variables, `+ - * / ^`,
numeric comparisons, and `not/and/or/implies`. Integer parameters are overapproximated
by reals in dL. Boolean states, strings, tuple/list values, modulo, conditional
expressions, and uninterpreted functions conservatively produce unknown.
Internal `dl_checker` and `keymaerax_config` injection belongs to construct_type,
not the public facade. Public calls use environment configuration and expose
`keymaerax_timeout_seconds` only as a per-call override.

## Verdict semantics

FOL/dL premises require validity, not merely a satisfying assignment. Z3 checks
unsatisfiability of negation; KeYmaera X attempts proof. This realizes universal
Table 2 premises such as `phi => B`, `phi => refinement`, and `pre => [ODE]post`:

- Unsatisfiable negation: true.
- KeYmaera X PROVED: true.
- A trustworthy Z3/KeYmaera X counterexample: false.
- Incomplete query/proof, timeout, or unavailable tool: unknown.

Current scope includes Table 2 construction/checking and proofs, complete Table 3
reachable graphs, and deadlock/livelock/Bottom-error analysis on those graphs.
General termination and other graph properties are outside the current scope.

## Table 3 transition graphs

An existing TypeAST can be passed to interface 3:

```python
from hcsp_typechecker import (
    TypeTransitionGraph,
    build_type_transition_graph,
)

graph: TypeTransitionGraph = build_type_transition_graph(
    type_ast,
    max_states=None,
    max_transitions=None,
    output="full",
)
```

Result mode prints graph size and initial normalized Type. Full mode uses internal
formatters for all states, labels, and evidence; these formatters are not root exports.

`HCSPTypeTransitionGraphError` distinguishes invalid Type, invalid limits,
normalization failure, and size limits using kind/phase. It exposes limit_name/limit
or option_name/option_value as appropriate, never a partial graph.
Result gives compact errors, full adds input and stage progress, and none is silent.

Pass a complete graph to `analyze_type_lock_freedom(graph,...)`. CSR and iterative
linear BFS/DFS find nonempty-ready infinite waits, silent cycles, and reachable
Bottom errors. LockFreedomReport contains shortest reachable prefixes and finite
witnesses, with lock_free, error_free, and behavior_correct kept separate.
False properties return normally; invalid/incomplete graphs raise
HCSPTypeLockAnalysisError. See [Lock analysis](TYPE_LOCK_ANALYSIS.md).

The graph interface normalizes original Types into separate ASTs and enumerates
Table 3 under critical-deadline reduction. Data structures hold normalized Types,
graphs, states, labels, and evidence; the backend handles term conversion,
minimization, rules, and BFS. Recursion becomes cyclic term graphs quotiented by
greatest bisimulation, merging finite unfoldings. Table 3 rewrites these graphs;
P-mu is absorbed into back edges, and deterministic normalized ASTs serve display.
There is no inverse conversion to original Types. See
[Operational semantics](TYPE_OPERATIONAL_SEMANTICS.md),
[Normalized output syntax](NORMALIZED_TYPE_OUTPUT_SYNTAX.md), and
[Graph output syntax](TYPE_TRANSITION_GRAPH_OUTPUT_SYNTAX.md).

initial_state identifies the root; states holds consecutive identifiers and
display ASTs; transitions holds source/target, tau/time labels, and derivations.
`graph.outgoing(state_id)` provides stable outgoing edges. EquiRecursiveStateKey
determines identity; display ASTs do not execute rules or deduplicate states.
