# Implementation semantics and the paper's rules

This reference describes the current source implementation: data flow through
the frontend, data structures, TypeConstructor, TypeChecker, and proof backends,
and executable forms of Table 2 rules. The paper supplies the rules; this document
records their implementation. Where representations differ, it identifies
extensions, normalization choices, and restrictions explicitly.

Related references provide the complete input EBNF, Type syntax, and Table 3 semantics:

- [Complete HCSP, Gamma, Theta, and parameter input](GAMMA_THETA_INPUT_SYNTAX.md).
- [Supplied Type input and AST round trips](TYPE_INPUT_SYNTAX.md).
- [TypeConstructor rule-by-rule details](TYPE_CONSTRUCTOR.md).
- [TypeChecker's type-directed checking](TYPE_CHECKER.md).
- [Normalized Types, cyclic term graphs, and Table 3](TYPE_OPERATIONAL_SEMANTICS.md).

Internal Python classes are not stable APIs. Users call the four package-root
interfaces documented in the [Public API guide](PUBLIC_API_GUIDE.md).
Internal names below let maintainers locate
the corresponding mathematical steps in source.

---

## 1. Complete request data flow

### 1.1 TypeConstructor

`construct_hcsp_type(source, ...)` executes this chain:

```text
Complete user source
  -> Shared lexer and parser
  -> Gamma / ParameterEnvironment / Theta / Process AST
  -> Top-level Process components + Configuration
  -> PreparedTypingEnvironment
  -> Table2RuleEngine expands ordered premises
  -> Z3 or KeYmaera X decides each formula immediately
  -> TypeConstructor combines child conclusions into a Type AST
  -> Trusted TypeAST or structured exception
```

Parsed Process ASTs remain internal. Construction directly creates formal nodes
from `data_structures/type_ast/ast.py`; it does not generate Type text and reparse
it. Serialization is used only for final presentation.

### 1.2 TypeChecker

`check_hcsp_type(source, ...)` shares lexing, Process ASTs, runtime contexts,
Table 2 expansion, and provers, but traverses the supplied Type:

```text
Complete source with a type section
  -> Process AST + supplied Type AST + environments
  -> Current Process node selects applicable rules
  -> Current supplied Type must match the rule conclusion
  -> Prove formula premises and consume corresponding child Type subtrees
  -> Return the supplied TypeAST after all structure and proofs pass
```

The checker does not call construction or compare against a second complete Type.
It verifies rule conclusions directly.

### 1.3 Type transition graphs

`build_type_transition_graph(type_ast, ...)` does not read HCSP or Gamma/Theta.
It normalizes the formal AST in one direction, compiles an equi-recursive cyclic
term graph, and enumerates the implemented Table 3 one-step relation:

```text
TypeAST -> Normalized Type -> EquiRecursiveStateKey
        -> Table 3 one-step successors -> Complete reachable closure by BFS
        -> TypeTransitionGraph
```

Cyclic term-graph keys determine equality and further derivation. A state's
normalized Type is a deterministically reconstructed readable representative,
so finite syntax trees created by recursion unfolding are not mistaken for distinct states.

### 1.4 Lock and Bottom-error analysis

`analyze_type_lock_freedom(graph, ...)` does not repeat normalization or Table 3.
It builds a CSR outgoing-edge index for interface 3's complete graph, uses BFS
to find `time(infinity,R)` deadlock edges with nonempty `R`, and explicit-stack
DFS to find cycles in the `tau` subgraph. BFS also locates the first reachable
Bottom parallel root. The report separates the paper's `lock_free`, the project's
`error_free`, and their conjunction `behavior_correct`. False properties return
finite witnesses and reachable prefixes; invalid/incomplete graphs raise errors.
Search and path reconstruction are iterative `O(|V|+|E|)` algorithms.

---

## 2. Frontend inputs and representations

### 2.1 Top-level sections

Constructor source is parsed in this fixed order:

```text
gamma(...) [parameters(...) where(...)] theta(...) process {...}
```

Checking additionally requires a final `type ...` section. Omitted parameters
mean empty declarations and a true constraint. One shared token stream preserves
global locations for lexical, bracket, and validation errors without text-based section splitting.

All user identifiers follow the shared ASCII rule:

```text
[A-Za-z_][A-Za-z0-9_]*
```

Text parsers reject reserved words in identifier positions. Internal AST
constructors enforce ASCII identifier shape but do not universally check the
text grammar's reserved words. Unicode identifiers and ambiguous spellings
subject to Python NFKC normalization are rejected at identifier boundaries.
The project parses expressions with its own precedence; public input does not
depend on Python `ast.parse` extensions.

### 2.2 Statement blocks and Sequence normal form

Semicolons denote sequential execution, but the frontend does not mechanically
right-nest every statement as `Sequence(P,Q)`. The Process AST follows these
normal forms for the implemented Table 2 rules:

- `If(B,P1,P2,continuation=Q)` owns common continuation `Q`.
- `InternalChoice(P1,...,Pk,continuation=Q)` owns common continuation `Q`.
- `ODE(...,continuation=Q)` owns its sequential continuation.
- Other adjacent actions use binary `Sequence`.
- `Sequence.of(...)` attaches following statements to those control-node fields.
- Direct `Sequence(control_node,Q)` is rejected to avoid a second equivalent representation.

Thus this source:

```text
if (B) {P1} else {P2}; Q
```

becomes `If(B,P1,P2,continuation=Q)`, not `Sequence(If(B,P1,P2),Q)`.
Internal choice and ODE behave similarly. Each rule can pass the same Q directly
to its child judgments without a generic type-level T-Seq.

Every user ODE requires an explicit following statement, including `; skip`
when no substantive continuation exists. This exposes the distinction between
an unreachable deadline continuation and a reachable empty continuation.
Section 7 explains the two candidate rules.

Deep statement blocks use an explicit frontend task stack. Parsing capacity is
therefore governed by explicit resource budgets rather than Python's default recursion depth.

### 2.3 Process AST construction checks

Process constructors immediately enforce structural checks:

1. E, P, and S categories cannot be mixed; `Parallel` cannot be a sequential continuation.
2. Communication has one or more scalar slots, excluding tuple values; input targets are distinct.
3. `EventChoice` stores a nonempty n-ary branch list; only `EmptyEvent` represents no events.
4. `InternalChoice` has at least two branches and a common continuation, not a binary choice chain.
5. Assumption 2.1 checks free/bound value variables, Process variables, and parallel channels.
6. `ch?(x1,...,xn)` binds only in the corresponding sequential or event-branch continuation.
7. Parallel components cannot share mutable variables, Process variables, input
   channels in the same direction, or output channels in the same direction.
   One input and one output on the same channel allow synchronization.
8. Shared read-only parameters known from complete source are excluded from
   parallel variable-sharing checks; low-level AST construction retains strict checks.
9. Assumption 2.2 requires every path returning to a `mu X.P` binder to cross
   input/output first. Inner same-name `mu` binders shadow outer ones.
10. An automatically inserted empty `Skip` continuation of internal choice is not
    an observable action and does not turn a tail call into a non-tail call.

These checks occur before Table 2 starts. They reject inputs that cannot form
valid Process ASTs, rather than refuting a proof obligation after AST construction.

### 2.4 ODE annotations and hidden clocks

Every ODE carries an `ODEAnnotation`:

- `delay` is required: a statically evaluable nonnegative rational or positive infinity.
- Finite delays use exact `Fraction`, not binary floating-point approximations.
- Omitted `safety` normalizes to `true`.
- Omitted `interrupt` normalizes to `EmptyEvent`.
- `wait(d)` is unsupported; there is no separate wait node.

Every ODE has its own local clock named `t`. User right-hand sides, domain, and
safety may read it; the implementation adds entry `t=0` and derivative `t'=1`.
It cannot be a user left-hand side and is outside Gamma, continuous vectors,
state-variable sets, and the external continuation. Different ODEs use fresh logical clock symbols.

---

## 3. Gamma, Theta, parameters, and Configuration

### 3.1 Gamma

Gamma's scalar types are:

```text
Bool, Nat, Int, Rational, Real
```

The numeric subtype chain is:

```text
Nat <: Int <: Rational <: Real
```

Gamma also accepts independent `ContinuousType((x1,...,xn))` declarations.
These are not tuple-valued state variables or trajectory properties; they
register a permitted ODE left-hand-side set `{x1,...,xn}`. Every member has a
separate `Real` declaration. Hidden clock `t` is excluded from matching, and
safety properties come only from the ODE's own annotation.

Gamma is a declaration environment: initial states may omit scalars, and a
component may see unused declarations. Every parallel configuration receives
the same full Gamma rather than a syntactically restricted subset. Disjointness
applies to mutable state ownership, computed from Process variables and initial-state
keys with shared parameters excluded. Overlapping ownership is rejected.

This differs from the paper's surface form `Gamma = Gamma_1 uplus ... uplus Gamma_n`.
The implementation allows Gamma to be a common declaration superset, while
Process AST and configuration checks enforce mutable-state separation.

### 3.2 Global parameters

`ParameterEnvironment` stores basic-type declarations and constraint H. Parameters:

- May be read by all parallel components.
- May occur in HCSP expressions, Theta refinements, FOL, and dL formulas.
- Have names disjoint from Gamma.
- Cannot be assignment/input targets, ODE left-hand sides, or initial-state keys.
- Undergo type, definedness, and satisfiability checks before formal rules execute.

An unsatisfiable parameter constraint stops the backend. If Z3 returns `unknown`,
an unresolved diagnostic is retained and derivation continues; construction is
ultimately untrusted and checking does not accept.

### 3.3 Theta

Each `ChannelType` has at least one basic scalar slot. Multiple slots communicate
independent scalars in one synchronization, with meaningful slot order. Channels also store:

- Distinct binders paired with the slots.
- One joint refinement, defaulting to `true`.

Local binders shadow same-name external scalars; other free names may come from
Gamma scalars or global parameters. Preparation translates every Theta refinement,
including unused channels. Unbound names, non-Bool formulas, and static expression
errors in unused channels still invalidate the environment.

### 3.4 Initial states and path conditions

`Configuration(state, process, path_condition)` uses a partial state:

- `dom(state)` may be a strict subset of Gamma's scalar keys.
- Unassigned scalars remain symbolic in formulas.
- Unknown keys, vector declaration labels, and parameter keys are rejected.
- T-sigma checks that the parameter constraint implies the path after partial-state
  substitution; it does not require complete enumeration of Gamma.

Internal top-level configurations may each supply local paths or all use a
global default path. Mixing provided/missing local paths is invalid, as is
combining a nontrivial global path with a full set of local paths.

---

## 4. Expressions and proof representations

Expression ASTs are untyped syntax. `ExpressionTranslator` combines Gamma scalars,
parameters, local binders, the current symbolic assignment map, and the ODE clock to produce:

- A Z3 term.
- A `Bool/Nat/Int/Rational/Real` result type.
- Definedness conditions, such as nonzero divisors or nonnegative square-root arguments.

Z3 handles first-order arithmetic, state validity, and refinements. ODE safety,
domain, and boundary become dL formulas for KeYmaera X. Runtime proof results are three-valued:

- `true`: the premise is proved.
- `false`: the rule is refuted and its current branch stops immediately.
- `unknown`: timeout, missing backend, or undecidable goal; retain evidence and continue structure.

The paper generally uses binary valid/provable premises. `unknown` is an added
runtime state for incomplete provers, not a new logical truth value in the paper.

`ProofObligation` records original and submitted formulas, rule, judgment location,
candidate ownership, backend explanation, and whether evidence is active in the
selected derivation. Unselected ODE candidate formulas may remain in full logs
without affecting the selected final verdict.

---

## 5. Shared Table 2 rule execution

Each `rule_t_*` performs these steps:

1. Check the current conclusion judgment's static shape.
2. Generate ordered formula and child-judgment premises.
3. Return `conclude(children)`, defining how child conclusions combine.

The evaluator processes premises with an explicit work stack. Formula premises
invoke provers immediately; child completion precedes `conclude`. Expansion,
proof, and result composition are interleaved rather than collected in a formula
pool. Assignment does not leave an unknown `phi'` for predicate synthesis.

Both engines share `Table2RuleEngine`:

- Construction executes `conclude` to combine child Types into new AST nodes.
- Checking decomposes the supplied Type into the current rule's required child
  subtrees and uses the same premise evaluator.

`false` stops a branch. `unknown` retains structural derivation where possible
instead of creating a no-Type marker. Public outcomes differ: construction can
deliver a complete untrusted candidate through a dedicated exception; checking still fails.

---

## 6. Discrete rule semantics

Here phi is the current symbolic path and T the sequential continuation Type.
`empty` denotes normal `EmptyType`; `bottom` denotes unreachable `BottomType`.

### 6.1 T-End and T-Skip

- Terminal `skip` or the end of a statement list produces `EmptyType`.
- Intermediate `skip;P` processes P without adding a Type node.
- Silent statements may therefore yield reachable empty behavior without invented communication.

### 6.2 T-Assert

`assert(B);P` requires:

1. Translate B as Bool.
2. Prove the current path implies B and its definedness.
3. Continue with P under the original path.

An assertion is a verification point, not an assumption; proving it does not add
B to the continuation path.

### 6.3 T-Assign

`x := e;P` executes:

1. Require a Gamma scalar target, excluding parameters and vector labels.
2. Translate e in the pre-assignment state; `x := x+1` reads the old x.
3. Require `type(e) <: Gamma(x)` and prove e's definedness.
4. Create a lazy post-state: retain phi and map x to e's pre-state term.
5. Subsequent reads of x obtain this substituted value.
6. Record concrete `phi => phi'{e/x}` evidence and process P in that post-state.

Assignment semantics determines `phi'`; it is not an unknown predicate searched
by a prover. There is no pool that synthesizes postconditions from accumulated assignments.

### 6.4 T-If

`If(B,P1,P2,continuation=Q)`:

1. Check the guard is Bool and prove its definedness.
2. Clone contexts with paths `phi and B` and `phi and not B`.
3. Process `P1;Q` and `P2;Q`.
4. Construct a two-branch `InternalChoiceType` in then/else order.

Branch assignments do not leak to siblings. Checking requires exactly two current
Type branches and consumes them in the same order without commutative reordering.

### 6.5 T-In

`ch?(x1,...,xn);P`:

1. Require ch in Theta and the same number of targets as channel slots.
2. Exclude parameters and vector labels as targets.
3. Add undeclared targets to local Gamma with slot types; declared targets require
   `slot_type <: variable_type`, so a Real channel cannot write an Int variable.
4. Create a fresh received symbol per slot, replacing each target's current value.
5. Add type-domain constraints, instantiated joint refinement, and its definedness to the path.
6. Process P and construct `InfiniteDelayType(InputType(ch,T))`.

Input refinement is assumed after reception; it does not prove a sent value's
refinement. Slot types and binders remain in Theta rather than the behavioral Type.

### 6.6 T-Out

`ch!(e1,...,en);P`:

1. Require ch in Theta and matching payload/slot counts.
2. Translate all payload expressions in the current state.
3. Require `type(e_i) <: slot_type_i` for each slot.
4. Prove the path implies payload definedness and joint refinement with `eta_i := e_i`.
5. Process P without changing state.
6. Construct `InfiniteDelayType(OutputType(ch,T))`.

Input assumes the refinement; output proves it.

### 6.7 Internal choice

The implementation extends the binary rule to n-ary form. For
`InternalChoice(P1,...,Pk,continuation=Q)`, process each `P_i;Q`, then construct
`InternalChoiceType((T1,...,Tk))` in source order.

Q's behavior belongs inside every selected branch, not outside the Type choice as
a shared T_Q. Formal Type ASTs preserve rule grouping for exact Process arity
matching. Only later graph normalization quotients choices by associativity,
commutativity, and idempotence.

### 6.8 External event choice

`EventChoice((c1,P1),...,(ck,Pk))` creates a child judgment per communication guard.
Each applies T-In/T-Out and processes its branch plus the ODE's common tail.
The rule extracts the unique communication prefix from each `InfiniteDelayType`
to form an Angelic Type:

- Zero branches: `NoInterruptType`.
- One branch: `InputType` or `OutputType` directly.
- Two or more: `ExternalChoiceType`.

Branches retain source order, and channel prefixes need not be unique. Checking
matches branch count, order, direction, and channel individually.

---

## 7. The two ODE rules

ODE rules require several explicit representation and proof choices, described below.

### 7.1 Static checks before proof

The backend first checks:

- User left-hand sides are distinct Gamma `Real` scalars.
- Their set exactly matches a `ContinuousType` declaration.
- Parameters are not evolved.
- Derivatives are numeric expressions.
- Domain and safety have Bool type.
- Partial-function definedness conditions are retained.
- AST delay is a nonnegative rational or positive infinity.

Failure of these checks prevents formation of a formal delay Type.

### 7.2 dL entry snapshot

Each ODE obligation uses an independent symbolic snapshot. Assignment-produced
symbols enter the pre-state, the clock starts at 0, and `t'=1` is appended.
The source name t shadows any same-name Gamma variable inside the ODE and is
discarded on exit.

### 7.3 Safety obligations shared by candidates

A nontrivial safety goal states that, from the current pre-path and `t=0`, the
user ODE plus `t'=1` preserves the annotation over the relevant `t<=d` interval.
Definedness of derivatives, domain, and safety is included. A normalized true
safety condition can be discharged locally without the external dL backend.

Gamma's `ContinuousType` contributes no safety property; it checks only the left-hand-side set.

### 7.4 Communication-guaranteed candidate T-unrhd

This candidate models communication interrupting evolution before the deadline,
making the deadline continuation unreachable. In addition to safety, it proves
domain preservation `pre => [F]B`. It adds no boundary goal for leaving B at
`t=d`, because its conclusion does not permit natural timeout.

Interrupt branches use post-context `B and safety`; their A combines with Bottom as:

```text
FiniteDelayType(d, A, BottomType())
```

Bottom is formal unreachable behavior, not an error-recovery placeholder.
For `d=infinity`, construction uses `InfiniteDelayType(A)` with the same
unreachable natural continuation.

### 7.5 Natural-timeout candidate T-unrhd-prime

For finite delay with a reachable sequential continuation, a boundary dL obligation states:

```text
t < d  -> B
t = d  -> not B
```

Interrupt branches use `safety`; natural fallback uses `not B and safety`.
The implementation uses these Table 2 postconditions directly, without retaining
entry frame facts unrelated to evolved variables. Required continuation facts
must be reestablished through sufficiently strong safety/domain/other annotations.

All ODE successors still conjoin the prepared shared parameter condition and
intrinsic scalar type-domain constraints, such as Nat nonnegativity. Only the
additional entry-path facts are discarded; see
[Symbolic post-ODE contexts](TYPE_CONSTRUCTOR.md#96-symbolic-post-ode-contexts).

The result is:

```text
FiniteDelayType(d, A, T_fallback)
```

`T_fallback` may be `EmptyType`, a reachable deadline continuation without further
communication; `BottomType` is not interchangeable with it.

### 7.6 Why ODE;skip tries both rules

An explicit skip may either mark the absence of a reachable continuation or be
a real empty continuation. For finite `ODE;skip`, construction tries both rules
in isolated evidence regions:

1. Each candidate has independent obligations, diagnostics, and steps.
2. Prefer proved candidates; choose the first canonical representative if their Types are equivalent.
3. Two proved but inequivalent Types violate the expected rule exclusivity and cause failure.
4. Without a proved candidate, retain a complete `unknown` candidate. Equivalent
   candidates share a representative; otherwise prefer natural timeout and mark it provisional/untrusted.
5. Structurally failed or refuted candidates cannot be selected; evidence remains for full review.
6. An unselected unknown candidate does not weaken a proved candidate, since the
   implementation treats the rule applicability conditions as exclusive.

Finite non-skip continuations use natural timeout only. Infinite delay has no
natural timeout and uses only the communication-guaranteed form.

Checking filters candidates by the supplied delay, A, and Bottom/non-Bottom
continuation, then reuses static checks, dL goals, and isolated `ODE;skip` attempts.
A Bottom continuation is never accepted as a timeout continuation.

---

## 8. Recursion rules

### 8.1 Process AST layer

At the programmatic AST level, omitted `Mu(X,P,invariant=I)` invariants default
to true. Assumption 2.2 enforces communication guarding. The implemented fragment
is guarded tail recursion: mu cannot have an observable following continuation;
an automatically inserted empty Skip is ignored.

### 8.2 T-mu

Constructor:

1. Prove the current path implies I.
2. Allocate a fresh TypeVar for the source Process variable.
3. Replace Gamma scalars with fresh symbols, retaining only parameter constraints,
   basic-type domains, and I rather than concrete assignment history.
4. Process the body from that abstract entry with EmptyType as its normal terminal;
   only explicit Var(X) back edges refer to the binding's fresh TypeVar.
5. If the body references it, check type-level communication guarding and wrap in MuType.
6. If no back edge remains, return the body Type without a redundant MuType.

### 8.3 T-X

`Var(X)` must resolve lexically, occur in tail position, and reestablish its binder's
invariant from the current path. It produces the corresponding fresh TypeVar.
An inner same-name mu shadows the outer binder.

Checking assigns a shared opaque identity to source and supplied Type binders,
rather than merely mapping strings. Alpha matching therefore respects lexical
scope even when inner and outer variables reuse names.

---

## 9. Top-level T-sigma and parallelism

### 9.1 T-sigma

Each configuration leaf checks its partial state and proves that every parameter
valuation satisfying the background constraint makes its initial state satisfy
the path. Only then does it process the child Process/System judgment.
Omitted Gamma scalars remain symbolic in the validity formula; unknown state keys fail.

`Configuration({}, Parallel(...))` is a stateless convenience form for empty
Gamma/state and a true path. Stateful or nontrivial-path parallel input must be
split into configuration leaves so each passes through T-sigma.

### 9.2 T-parallel

For one or more configurations, the implementation:

1. Supplies full Gamma, Theta, and parameters to every component.
2. Computes each component's mutable-state ownership.
3. Rejects undeclared variables unless freshly bound by input.
4. Rejects overlapping mutable-state ownership.
5. Constructs or checks each component Type.
6. Constructs/matches ParallelType in source configuration order.

Table 3 later normalizes parallel composition by associativity and commutativity,
while preserving multiplicity. Formal Type ASTs and checking retain source order
so rule child judgments match supplied components position by position.

---

## 10. Shared and distinct construction/checking behavior

Both share:

- Environment normalization and all-Theta refinement checks.
- Expression typing, definedness, and symbolic states.
- T-sigma, T-parallel, discrete rules, ODE dL goals, and recursion contexts.
- Immediate false short-circuiting and unknown-evidence retention.
- Z3, KeYmaera X, proof obligations, and full report formatting.

They differ in:

| Situation | Constructor | Checker |
|---|---|---|
| Successful child judgment | Combines a new Type node | Consumes a supplied subtree |
| Type grouping | Produced by the current Process rule | Must match supplied parentheses |
| Internal choice | Same arity and source order | Same arity/order; no AC rearrangement search |
| Recursion variables | Fresh internal TypeVars | Alpha correspondence to supplied TypeVars |
| Unknown proofs, complete structure | Untrusted-construction exception with candidate | Checking exception; no provisional acceptance |
| Type origin | Backend-generated | Supplied in the type section |

A trusted constructed Type should round-trip through canonical serialization and
checking under the same Gamma, Theta, parameters, states, paths, and proof settings.
Tests cover discrete statements, branches, recursion, parallelism, and ODEs.
Changing timeouts, prover availability, states, or paths may change the result.

---

## 11. Distinct empty values in formal Types

Three concepts must remain separate:

- `NoInterruptType`: an empty Angelic interrupt set, valid only in A positions.
- `EmptyType`: reachable normal Process behavior with no further communication, produced by skip.
- `BottomType`: unreachable Process behavior, used for T-unrhd/infinite-delay deadline continuations.

Thus:

```text
delay(d, no interrupts, EmptyType)
```

waits until d and reaches normal empty behavior, whereas:

```text
delay(d, A, BottomType)
```

states that the deadline continuation is unreachable. Construction failures use
internal failure markers and structured exceptions, never Bottom placeholders.

Formal ASTs preserve internal-choice grouping and parallel source order for exact
checking. Separate normalized graph ASTs apply the relevant associative,
commutative, and idempotent quotients to choices, and the non-idempotent parallel quotient.

---

## 12. Table 3 graph semantics

Interface 3 first normalizes in one direction:

- Flatten, sort, and deduplicate internal choices.
- Sort and deduplicate external choices.
- Flatten and sort parallel components while preserving duplicates.
- Replace named recursion with positional binding.
- Preserve the distinctions among delays, Bottom, Empty, and communication directions.

Normalized Types become minimal equi-recursive cyclic term graphs. Table 3 acts
on these graphs, not display ASTs. It enumerates nondeterministic choice,
complementary component pairings, communication, and time successors.
Parallel positions are evidence metadata rather than label semantics.

Time uses the chosen maximal critical step: advance to the next deadline among
jointly waiting components, omitting decomposable intermediate waits.
Empty does not block others. Any Bottom parallel root globally error-terminates
the configuration, preventing choice, communication, timeout, or time successors.
All-Empty normal completion is a separate state.

BFS deduplicates states by term-graph key and edges by `(source,label,target)`;
different rule instances remain in `derivations`. Size limits protect resources
without changing semantics by truncation: exceeding `max_states/max_transitions`
raises a structured error and returns no partial graph.

---

## 13. Extensions and restrictions relative to the paper

Points that require particular care during review:

| Item | Current behavior |
|---|---|
| Multiple scalar slots | `ch?(x1,...,xn)` / `ch!(e1,...,en)`; Type stores direction/channel, Theta stores slots |
| Choice nodes | N-ary Process choices rather than repeated binary nesting |
| Sequential control normal form | If/InternalChoice/ODE own continuations; external `Sequence(control,Q)` is forbidden |
| ODE annotations | Safety defaults to true; required delay is a nonnegative rational or positive infinity |
| ODE clock | Local `t=0,t'=1`, outside Gamma and continuous vectors |
| Empty ODE continuation | Explicit `;skip`; isolated communication-guaranteed and timeout candidates |
| ContinuousType | Registers an entire left-hand-side set, without trajectory properties |
| Parallel Gamma | Full Gamma for every component; disjoint mutable ownership checked separately |
| Shared parameters | Read-only environment shared across components and refinement/FOL/dL |
| Assignment postconditions | Deterministic lazy strongest post-state; no synthesis of unknown phi' |
| Assert | Verified without adding the assertion as a continuation assumption |
| Proof results | Runtime true/false/unknown; unknown continues structure without trusted success |
| Checker choice matching | Exact current arity, parentheses, and order; no AC search |
| Recursion | Guarded tail recursion; abstract entry retains parameters, type domains, and invariant |
| Table 3 time | Only the step to the next critical deadline |
| State equality | Equi-recursive cyclic-term quotient; display AST is excluded |
| Deadlock | Reachable infinite-time edge with nonempty ready set, not merely zero outdegree |
| Livelock | Directed cycle in reachable tau subgraph; positive-time cycles do not count |

Some choices implement paper rules directly; others clarify input, proof boundaries,
scalability, or finite state representation. Changes require corresponding reference
updates, rule tests, construction/checking round trips, and public result/full output tests.

---

## 14. Source locations

| Functionality | Authoritative implementation |
|---|---|
| Complete source and Process lowering | `frontend/type_constructor_frontend/parser.py` |
| Type parsing | `frontend/type_syntax/parser.py` |
| Process/ODE/Assumption ASTs | `data_structures/process_ast/ast.py` |
| Formal Type AST | `data_structures/type_ast/ast.py` |
| Gamma/Theta/parameters/Configuration | `data_structures/runtime_context/model.py` |
| Shared preparation | `backend/common/environment.py`, `rule_engine.py` |
| Table 2 and proof scheduling | `backend/common/rule_engine.py` |
| Construction result composition | `backend/type_constructor/constructor.py` |
| Type-directed checking | `backend/type_checker/checker.py` |
| Expressions/Z3 | `backend/common/logic.py` |
| dL formulas | `backend/common/dl.py` |
| KeYmaera X | `backend/common/keymaerax.py` |
| Normalized ASTs | `data_structures/normalized_type_ast/` |
| Equi-recursive term graphs | `backend/type_operational_semantics/regular_tree.py` |
| Table 3 one-step semantics | `backend/type_operational_semantics/table3.py` |
| Reachable-graph BFS | `backend/type_operational_semantics/graph_builder.py` |
| Lock reports and witnesses | `data_structures/type_lock_analysis/` |
| CSR, deadlock BFS, livelock DFS | `backend/type_lock_analysis/` |
| Four public interfaces and structured errors | `api.py` |

This table identifies where behavior is determined. Frontend EBNF is not Table 2
execution, and Type AST `__str__` is not state equality. Review the authoritative
implementation layer rather than inferring semantics from display text.
