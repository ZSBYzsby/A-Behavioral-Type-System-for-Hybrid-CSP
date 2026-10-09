# TypeConstructor: constructing a Type AST from a Process AST

This reference describes the algorithms and mathematical operations performed
by the current code. During review, compare these explicit implementation
behaviors with the relevant paper rules.

For the complete flow through lowering, contexts, construction, checking, and
Table 3, start with [Implementation semantics](IMPLEMENTATION_SEMANTICS.md).
This page adds rule-level construction evidence and examples.

**TypeConstructor** takes annotated HCSP, Gamma, Theta, parameters, and optional
states/paths, and constructs its Type AST. **TypeChecker** is implemented
separately for supplied Types; see [TYPE_CHECKER.md](TYPE_CHECKER.md).

Main implementation locations:

- `hcsp_typechecker/data_structures/process_ast/ast.py`: Process, Event, and System ASTs.
- `hcsp_typechecker/backend/type_constructor/constructor.py`: construction entry point.
- `hcsp_typechecker/backend/common/environment.py`: shared normalized environments.
- `hcsp_typechecker/backend/common/rule_engine.py`: judgments, premises, and Table 2 expansion.
- `hcsp_typechecker/backend/common/logic.py`: Z3 translation and FOL/state decisions.
- `hcsp_typechecker/backend/common/dl.py`: ODE-to-dL translation.
- `hcsp_typechecker/data_structures/type_ast/ast.py`: final Type ASTs and canonical construction.
- `hcsp_typechecker/data_structures/runtime_context/model.py`: contexts and configurations.
- `hcsp_typechecker/backend/type_constructor/model.py`: construction requests/reports.
- `hcsp_typechecker/backend/common/model.py`: shared proof obligations, diagnostics, and evidence.

---

## 1. Construction inputs and outputs

A `TypeConstructionRequest` can be abstracted as:

\[
(\Gamma,\Pi,\Theta,\Phi,K),
\]

Here:

- \(\Gamma\) declares variables.
- \(\Pi=(\Delta,H)\) declares shared read-only parameters and legal prevaluations.
- \(\Theta\) gives channel refinements.
- \(\Phi\) is the current path condition.
- \(K\) contains one or more `Configuration(state, process)` objects.
- Each configuration Process is sequential or a restricted stateless Parallel convenience form.

The internal result is a `TypeConstructionReport`:

- `constructed_type`: a ConfigurationType when all structural derivation completes;
  unknown verdicts make it a complete unverified candidate.
- `constructed_component_types`: component results, with None at failed/unvisited positions.
- `obligations`: state, FOL, and dL goals actually attempted.
- `diagnostics`: structural/static errors and unresolved candidate-selection reasons.
- `steps`: entry environments and results in execution order.
- `verdict`: combined true/false/unknown from active obligations and diagnostics.

None means no complete structure exists. A nonempty Type still requires its
verdict: true is trusted, unknown has unresolved required proofs. Neither is
BottomType, which represents unreachable formal behavior. Construction produces
Bottom in T-unrhd conclusions but never uses it for failed derivations or recovery.

Missing Z3 prevents expression translation and yields `unknown` without a complete
candidate. Query failures and unresolved dL proofs also yield `unknown`; when
derivation can continue, the public API exposes the candidate only through
`HCSPUntrustedTypeConstructionError.untrusted_type`. It never returns that
candidate as a trusted result. See [Failure recovery](PUBLIC_API_GUIDE.md#87-handling-failures-in-an-application)
for the required caller handling.

---

## 2. Checks already performed during Process AST construction

TypeConstructor accepts project Process ASTs, not arbitrary Python objects.
Before backend construction, `data_structures/process_ast/ast.py` has performed:

1. Parse expression strings into project Expr nodes.
2. Validate assignment targets, input targets, and channel identifiers.
3. Normalize scalar communication shorthand to one-slot tuples.
4. Check child syntactic categories in If, Sequence, choices, ODE, and Mu.
5. Check Assumption 2.1 at composite construction.
6. Check Assumption 2.2 communication guarding for Mu.
7. Normalize finite annotation delay to exact Fraction and reject negatives,
   symbolic values, NaN, and negative infinity.
8. Create the ODE-local t clock with initial value 0 and derivative 1.

Some inputs therefore fail before Type derivation. For example, `ch!x;ch?x`
freely uses and binds x, so `fv(P) ∩ bv(P) != empty`. This violates Assumption 2.1
and raises ValueError at the internal AST boundary.

---

## 3. Gamma, parameters, Theta, and symbolic state

### 3.1 Gamma

Gamma has two entry categories:

```python
GammaType = BasicType | ContinuousType
```

Ordinary variables use:

```python
BasicType.BOOL
BasicType.NAT
BasicType.INT
BasicType.RATIONAL
BasicType.REAL
```

ODE left-hand-side variables remain ordinary Real values:

```text
"p": BasicType.REAL
"v": BasicType.REAL
"a": BasicType.REAL
```

A separately named continuous entry registers a permitted ODE evolution vector,
with domain shape \(\mathbb R_{\ge0}\rightharpoonup\mathbb R^n\), without trajectory
property \(\phi\). Invariant evolution properties belong in the ODE safety annotation.

For a multi-scalar vector such as \(\{p,v,a\}\), record its complete member set:

```python
trajectory = ContinuousType(
    variables=("p", "v", "a"),
)
{
    "p": BasicType.REAL,
    "v": BasicType.REAL,
    "a": BasicType.REAL,
    "vehicle_ode": trajectory,
}
```

Normalization requires all members to be BasicType.REAL scalars. T-ODE requires
the user left-hand-side set to equal a registered variables set. Order is irrelevant;
strict subsets/supersets fail before dL goals are created.

A ContinuousType label has no current value and cannot occur in expressions,
state, assignments, or input targets. It records:

- Permission for an ODE vector to occur in the Process.
- Its complete variables set.

Real values in left-hand sides, derivative parameters, domains, and safety use
BasicType.REAL. Reals outside ODEs need no continuous declaration.

### 3.2 Shared read-only parameter environment

`ParameterEnvironment(declarations,constraint)` gives a Gamma-independent
\(\Pi=(\Delta,H)\):

The prepared condition includes definedness and intrinsic parameter type domains:

\[
\widehat H=Def(H)\land H\land TypeDomain(\Delta).
\]

- \(\Delta\) declares only BasicType parameters.
- H refers only to names in Delta.
- Preparation checks \(\widehat H\) is satisfiable, preventing vacuous proofs.
- Every parallel configuration uses the same parameter symbols; these are outside
  Gamma and mutable-state overlap/ownership checks.
- Parameters may be read in paths, expressions, refinements, recursion invariants,
  and ODE formulas, but cannot be state keys or assignment/input/ODE targets.

Gamma and Delta names must be disjoint. Users choose parameter values once before
execution; construction covers every valuation satisfying \(\widehat H\) rather
than storing an instance.

### 3.3 Theta

For channel ch, ChannelType stores:

\[
\Theta(ch)=((B_1,\ldots,B_n),(\eta_1,\ldots,\eta_n),R),
\]

Here:

- \(B_i\) is an individual scalar slot's BasicType.
- \(\eta_i\) binds that slot's value in the refinement.
- R is the joint refinement.

Arity and payload types remain in Theta and obligations, outside InputType/OutputType.
The same channel name with different Theta signatures still displays the same
ch? or ch! prefix at the behavioral Type level.

Before any Process rule, preparation visits every Theta entry. Temporary slot
symbols validate that refinements reference only local binders, Gamma scalars,
and shared parameters, and have Bool type. Invalid unused channels also fail.
Preparation checks well-formedness, not universal truth of refinements.

### 3.4 Context for each control-flow path

Each path maintains:

\[
C=(\Gamma,\Delta,H,\Theta,\Phi,\rho,\mathcal R,location,valid),
\]

Here:

- gamma is a branch-local copy of full Gamma; each configuration begins with the
  same declarations, and input adds targets only to its continuation branch.
  parameters/parameter_condition are shared Delta/\(\widehat H\); theta is shared.
- path is the Z3 formula \(\Phi\).
- symbols is \(\rho\), mapping names to current Z3 terms.
- rec_env binds Process variables to Type variables and invariants.
- location identifies the branch in reports.
- static_valid records successful initial environment/path preparation.

Parameters receive shared symbols first. Each configuration's BasicType Gamma
variables then receive fresh prefixed symbols. Their Z3 sorts are:

- `Bool` -> Z3 Bool;
- `Nat`, `Int` -> Z3 Int;
- `Rational`, `Real` -> Z3 Real.

Continuous declarations receive no Z3 symbols. For a configuration's supplied
path \(\Phi_i\), the prepared local path and full initial path are:

\[
\widehat\Phi_i=Def(\Phi_i)\land\Phi_i\land TypeDomain(\Gamma,\rho_i),
\qquad \Phi=\widehat H\land\widehat\Phi_i.
\]

Intrinsic type-domain constraints currently add \(x\ge0\) for Nat values.

---

## 4. Mathematical expression translation

For e in the current context, ExpressionTranslator returns:

\[
\llbracket e\rrbracket_{\rho}=(u,B,D),
\]

Here:

- u is a Z3 term.
- B is the inferred BasicType.
- D lists definedness conditions.

For example:

- `x / y` requires \(y\ne0\).
- `sqrt(x)` requires \(x\ge0\).
- `%` accepts only Nat/Int.
- Reading `x:BasicType.REAL` gives Real; vector declaration labels cannot be read.

Numeric subtyping is:

\[
Nat <: Int <: Rational <: Real.
\]

Static typing and definedness proof are separate. Type errors produce diagnostics;
partial-expression conditions typically become formula premises of the current rule.

---

## 5. Unified derivation evaluator

### 5.1 Four internal judgments

Rules create four explicit judgment categories rather than recursing themselves:

1. `_ConfigurationJudgment(state, system, context)`;
2. `_SystemJudgment(system, context)`;
3. `_ProcessJudgment(nodes, context, terminal)`;
4. `_EventJudgment(reaction, tail, context, terminal)`.

Each rule expands one level and returns:

```text
RuleExpansion(rule, premises, conclude)
```

There are two premise categories:

- FormulaPremise: state, FOL, or dL formulas.
- ChildJudgmentPremise: child judgments evaluated by the explicit work stack.

conclude combines already derived child Types into the parent AST.

### 5.2 Ordered proof, false short-circuiting, and unknown retention

`_solve_rule_expansion` processes premises in stored order:

1. Dispatch formula premises immediately to the appropriate prover.
2. Continue normally after true.
3. Stop the current rule immediately after a false required premise.
4. Record unknown goals and reasons, then continue remaining premises.
5. Evaluate child judgments using the work stack. Failure to form a child Type
   prevents visiting later siblings.
6. Once all required child Types exist, execute conclude. Earlier unknown proofs
   permit structure but make the final result untrusted.

Proof and derivation are interleaved, without a formula pool. Unknown is not
refutation: construction attempts to reach the root with a complete candidate.
False or structural/static failure retains only evidence and partial Types up to
the actual stopping point.

### 5.3 Sequence has no corresponding Type AST node

`_as_nodes` iteratively expands binary Sequence(P,Q) into:

```text
[Sequential nodes of P..., Sequential nodes of Q...]
```

Construction processes the head and passes the remainder as continuation.
There is no SequenceType or postprocessing that first types P and appends Q's
Type to every endpoint. Continuations propagate during derivation.

If, InternalChoice, and ODE own their continuations and cannot be external
Sequence prefixes. `nodes[1:]` holds only temporarily added outer derivation tails.

---

## 6. Top-level configurations and parallel systems

### 6.1 Environment normalization

Construction normalizes Gamma, parameters, and Theta first. Invalid variable
types, parameter constraints, overlapping names, channels, or signatures fail
before Process rules. Unsatisfiable parameter constraints are rejected.

### 6.2 Multiple configurations

Even one configuration passes through rule_t_parallel.

Every child configuration receives full Gamma, a possible superset of its used
declarations. Visible unused declarations do not affect derivation; no local
Gamma partition is constructed or accepted.

Shared declarations do not imply shared mutable state. Assumption 2.1 separates
parallel variable sets; the low-level multiple-Configuration interface combines
process.get_vars() with state keys and rejects ownership overlap. Input may bind
new undeclared targets; other undeclared used names fail.

Every component also receives shared Delta/H, outside mutable ownership.

Either every configuration supplies a local path or none does. With local paths,
the outer path must be default true.

Children follow input order. False or structural/static failure stops later
components; completed prefix results remain in constructed_component_types,
with None at failed/unvisited positions. Formula unknown permits continuing
construction and retaining an untrusted complete component candidate.

When all component structures complete:

- One component returns its Type directly.
- Multiple components produce ParallelType((T1,...,Tn)).

ParallelType flattens nested parallel composition while retaining component order.

### 6.3 T-sigma state checks

For configuration \((\sigma,P)\), first require:

\[
dom(\sigma)\subseteq dom(\Gamma_{value}),
\]

\(\Gamma_{value}\) contains BasicType entries only, excluding vector declarations.
Parameters are outside it, so \(dom(\sigma)\cap dom(\Delta)\) must be empty.

State may cover only a subset of Gamma values. Substitute supplied values into the path:

\[
\widehat H\Rightarrow\widehat\Phi_i[\sigma].
\]

Unassigned Gamma values and parameters remain symbolic. Validity universally
checks all parameter valuations satisfying \(\widehat H\) and unspecified state values,
rather than choosing an instance that satisfies the formula.

Only after state validation does the System/Process child judgment run.

### 6.4 Parallel AST convenience form

`Configuration({},Parallel(...))` requires empty Gamma/state and a true full path.
The evaluator derives the left/right systems and combines their ParallelType.

Stateful parallelism or a nontrivial parameter constraint requires explicit
Configuration leaves, with T-|| establishing each state/path premise. Leaves
still share full Gamma, Theta, and parameters.

---

## 7. Discrete Process node construction

### 7.1 Terminal Skip and implicit termination

For an empty node list or the last explicit Skip:

\[
skip \longmapsto terminal.
\]

The usual top-level terminal is EmptyType, producing normal empty communication behavior 0.

There are no premises or Context changes.

### 7.2 Intermediate Skip; P

Intermediate Skip simply derives the remaining nodes:

\[
type(skip;P,C)=type(P,C).
\]

Gamma, path, and symbolic state stay unchanged; no Type prefix is generated.

### 7.3 `Assert(B); P`

Translate the condition first:

\[
\llbracket B\rrbracket_\rho=(b,Bool,D_B).
\]

Immediately prove:

\[
\Phi\Rightarrow(D_B\land b).
\]

Then derive P under the original Context. Assert verifies rather than assumes,
so the path remains \(\Phi\), not \(\Phi\land B\). The result is P's Type, without AssertType.

### 7.4 `Assign(x,e); P`

The assignment rule performs:

1. Require x to be declared in Gamma and outside shared parameters.
2. Evaluate \(\llbracket e\rrbracket_\rho=(u,B_e,D_e)\) in the pre-state.
3. Check \(B_e <: base(\Gamma(x))\).
4. Prove \(\Phi\Rightarrow D_e\) when definedness is nontrivial.
5. Create the updated symbol map:

\[
\rho'(x)=u,
\qquad
\rho'(y)=\rho(y)\quad(y\ne x).
\]

The path remains pre-assignment Phi, possibly referring to historical x symbols.
Later expression reads obtain u through rho'. No explicit existential strongest
postcondition formula is constructed.

T-Assign-post additionally records this actual formula:

\[
\Phi\Rightarrow\Phi,
\]

_LazyAssignmentPostState.pre_path is the original path. This records that the
symbol map already determines the post-state, without searching an unknown Phi'.

Derive P under \((\Phi,\rho')\); its Type is the result, without AssignType.
Targets must be BasicType variables, excluding ContinuousType labels and
prevalued read-only parameters.

### 7.5 `ch?(x1,...,xn); P`

Obtain the channel slots and refinement from Theta:

\[
((B_1,\ldots,B_n),(\eta_1,\ldots,\eta_n),R).
\]

The input rule performs:

1. Require the channel and matching arity; forbid parameter targets.
2. Existing targets require the safe received-value-to-variable subtype direction:

\[
B_i <: existing_i.
\]

   Thus Int channel values may enter Real variables, but Real values cannot enter Int.
3. Add new targets to continuation Gamma with corresponding slot types.
4. Preserve existing targets' BasicType declarations; vector labels are not updated.
5. Create fresh received symbols \(r_i\) and update:

\[
\rho'(x_i)=r_i;
\]

6. Add the instantiated input refinement as a continuation assumption:

\[
\Phi'=\Phi\land Def(R[r/\eta])\land R[r/\eta]
       \land TypeDomain(r_1)\land\cdots\land TypeDomain(r_n).
\]

Nat reception adds TypeDomain \(r_i\ge0\); other types currently add none.

For different safe subtypes, Gamma retains the wider target declaration while
the fresh symbol uses the actual slot type. Later reads treat the received value
as an admissible subtype, without accepting values outside the declared target range.

Input assumes its refinement rather than generating a FOL obligation to prove it.
After deriving the continuation, construct:

```python
InfiniteDelayType(InputType(channel, continuation_type))
```

InputType is an Angelic A branch; T-In wraps it in infinite delay to form Process
Type T. Payload count, slot types, names, and refinement are not stored in the Type AST.

### 7.6 `ch!(e1,...,en); P`

The output rule performs:

1. Require the channel and matching arity.
2. Translate each \(e_i\) to \((u_i,B_i',D_i)\).
3. Require \(B_i' <: B_i\).
4. Instantiate \(R[u_1/\eta_1,\ldots,u_n/\eta_n]\).
5. Prove:

\[
\Phi\Rightarrow
\left(\bigwedge_i D_i\right)
\land Def(R[u/\eta])
\land R[u/\eta].
\]

Output preserves Gamma, path, and symbols. After continuation success, construct:

```python
InfiniteDelayType(OutputType(channel, continuation_type))
```

### 7.7 `If(B,P1,P2, continuation=Q)`

Require a Bool guard; separately prove partial-guard definedness:

\[
\Phi\Rightarrow Def(B).
\]

Then clone two contexts:

\[
C_{then}.path=\Phi\land B,
\qquad
C_{else}.path=\Phi\land\neg B.
\]

Append the node-owned common Q to each branch:

\[
T_1=type(P_1;Q,C_{then}),
\qquad
T_2=type(P_2;Q,C_{else}).
\]

After both child judgments succeed, construct:

```python
InternalChoiceType((T1, T2))
```

Nested InternalChoiceTypes preserve rule grouping, expressed by parenthesized
branches in canonical Type text. Ordered evaluation stops before else if then
cannot form a Type due to false/static/structural failure. Unknown formulas still
permit a candidate then Type and continued else derivation.

### 7.8 N-ary InternalChoice(P1,...,Pn, continuation=Q)

All branches share Q; derive separately:

\[
T_i=type(P_i;Q;tail,C_i)\qquad(i=1,\ldots,n).
\]

Each C_i independently clones the original context, isolating assignments and
inputs. Successful children combine as InternalChoiceType((T1,...,Tn)).

Omitted Q stores Skip. External Sequence(InternalChoice(...),Q) is invalid, as
for If and ODE. Default Skip completes the fields without observable behavior;
tail checking ignores it after X, so an internal X;skip remains tail-recursive.

---

## 8. EventReaction to Angelic Type

EventReaction occurs only in ODE interrupts.

### 8.1 `EmptyEvent`

EmptyEvent produces NoInterruptType, meaning no communication interrupts,
distinct from EmptyType's normal empty Process behavior.

### 8.2 `EventChoice((communication_1,P_1),...,(communication_n,P_n))`

Each event branch derives the full sequential behavior:

```text
communication; P; ODE outer tail
```

Each guard is input/output, so a successful child Type has an InfiniteDelayType
communication prefix. The rule extracts its InputType/OutputType to build the
angelic Type. The explicit work stack evaluates branches in source order.

make_external_choice combines branches:

- Zero: NoInterruptType.
- One: the InputType/OutputType directly.
- Multiple: ExternalChoiceType((branch1,...,branchn)).

Formal external choices retain source order and different same-channel branches,
without channel-based deduplication, sorting, or commutative rewriting.

---

## 9. Complete ODE construction

Let the Process node contain:

\[
\dot x_1=e_1,\ldots,\dot x_n=e_n,
\quad B,
\quad E,
\quad safety=S,
\quad delay=d.
\]

It also has local clock t with entry \(t=0\) and derivative \(\dot t=1\).

### 9.1 Static checks

Check first:

1. Left-hand sides are distinct.
2. Targets are declared and are not shared parameters.
3. Each target is BasicType.REAL.
4. A nonempty target set exactly matches a ContinuousType declaration.
5. Derivatives are numeric.
6. Domain B is Bool.
7. Safety S is Bool.
8. Retain derivative/domain/safety definedness conditions.

Local t shadows a same-name Gamma entry in derivatives, B, and S. It is appended
only during dL dynamics construction and is excluded from vector matching.

Static failure generates neither dL goals nor delay Types.

### 9.2 dL symbolic entry snapshot

After assignment, symbols[x] may be a compound term, while dL left-hand sides
must be variables. _ode_dl_terms allocates fresh entry variables \(x_i^0\)
and equalities:

\[
x_i^0=\rho(x_i).
\]

Allocate an ODE-specific fresh clock tau and add:

\[
\tau=0,
\qquad
\dot\tau=1.
\]

The dL precondition is then (Phi already includes H):

\[
Pre=\Phi\land\bigwedge_i(x_i^0=\rho(x_i))\land(\tau=0).
\]

The base dynamics are:

\[
F^*=\{\dot x_1^0=e_1,\ldots,\dot x_n^0=e_n,\dot\tau=1\}.
\]

Let the user left-hand-side set be:

\[
V_{ODE}=\{x_1,\ldots,x_n\}.
\]

The engine requires a ContinuousType variables set exactly equal to V_ODE.
No match is a static T-ODE failure. Matching permits the vector but adds no
property to dL. Empty flow requires no declaration. The continuous dL program
uses the domain-free dynamics F* above.

Delay is not automatically inserted into the evolution domain. Natural termination
at a time boundary needs the corresponding explicit clock condition in the domain.

### 9.3 Safety dL obligation

D_F, D_B, and D_S are definedness conditions for derivatives, source domain,
and safety. The node safety is the sole source of evolution invariants.

Without the local true shortcut, finite delay generates:

\[
Pre\Rightarrow[F^*]
(\tau\le d\Rightarrow(D_F\land D_B\land D_S\land S)).
\]

Without the shortcut, infinite delay generates:

\[
Pre\Rightarrow[F^*](D_F\land D_B\land D_S\land S).
\]

Source domain B is not a dL program domain; its definedness enters the safety
postcondition. Gamma checks vectors statically. H enters the antecedent through
the path, while parameters stay outside the evolution vector.

If \(D_F\land D_S\land S\) simplifies syntactically to true, discharge locally
without KeYmaera X. This shortcut excludes D_B; the actual non-shortcut dL
formula includes it as above. Unsupported translation stores
UntranslatedDLFormula, normally yielding unknown.

### 9.4 Communication-guaranteed domain obligation

When the ODE(...,continuation=Skip()) selection chooses the communication-only
rule without natural timeout, generate:

\[
Pre\Rightarrow[F^*](D_F\land D_B\land B^*).
\]

B* is the invariant to prove, not a program domain. A syntactically true domain
is discharged directly.

### 9.5 Natural-timeout boundary obligation

Finite delay with a natural continuation generates:

\[
Pre\Rightarrow[F^*]
\left(
(\tau<d\Rightarrow D_F\land D_B\land B^*)
\land
(\tau=d\Rightarrow D_F\land D_B\land\neg B^*)
\right).
\]

F* is again domain-free. The goal maintains B before d and establishes its failure at d.

### 9.6 Symbolic post-ODE contexts

dL obligations do not compute analytic solutions. On exit, each evolved variable
is replaced by a fresh post-state symbol:

\[
\rho_{post}(x_i)=x_i^{post}.
\]

The selected rule establishes the ODE-specific continuation conditions. First define:

\[
\widehat B=Def(B(post))\land B(post),
\qquad
\widehat S=Def(S(post))\land S(post).
\]

The post-state safety instance is justified by the same dL obligation, not
introduced as an unchecked assumption.

Every successor also retains the prepared parameter condition and scalar
type-domain constraints, evaluated using the post-state symbol map:

\[
E_{post}=Def(H)\land H\land TypeDomain(\Delta)
         \land TypeDomain(\Gamma,\rho_{post}).
\]

Here `TypeDomain` includes nonnegativity for Nat values; H is the shared parameter
constraint. These environment facts are retained even though the entry path is replaced.

The three cases are:

1. Communication-guaranteed interrupt continuation:

\[
\Phi_{event}=E_{post}\land\widehat B\land\widehat S;
\]

2. Natural-timeout rule's interrupt continuation:

\[
\Phi_{event}=E_{post}\land\widehat S;
\]

3. Natural-timeout continuation:

\[
\Phi_{fallback}=E_{post}\land Def(B(post))\land\neg B(post)\land\widehat S.
\]

Derivative definedness is not appended to these paths; it remains in the earlier dL goals.

Post-paths replace the entry Phi rather than conjoin with it. Earlier dL premises
establish the connection between entry and continuous evolution.

If B/S uses the clock, create a fresh post-clock and project it out of the
ODE-specific condition while retaining the environment condition:

\[
E_{post}\land\exists\tau.\ (\tau\ge0\land condition(\tau)).
\]

Local clocks do not enter interrupt or external-continuation Gamma.

### 9.7 ODE Type composition and normalization

With Angelic A from interrupts and Process T from natural continuation, call:

```python
make_delay_type(d, A, T)
```

Finite d has this canonical representation:

| A | T | Type AST |
|---|---|---|
| Any A | BottomType() | FiniteDelayType(d,A,bottom), communication-only T-unrhd |
| NoInterruptType() | Non-bottom T | FiniteDelayType(d,A,T), displayed as delay(d).T |
| Nonempty communication choice | Non-bottom T | FiniteDelayType(d,A,T), full display form |

Write a finite ODE without substantive continuation as ode(...);skip. If selection
uses communication-only, Bottom records the unreachable deadline continuation:

```python
FiniteDelayType(d, A, BottomType())
```

Positive infinity uses InfiniteDelayType(A), with fixed unreachable Bottom
timeout, not an ordinary stored field. Thus:

- With events: InfiniteDelayType(InputType/OutputType/ExternalChoiceType).
- Without events: InfiniteDelayType(NoInterruptType()).

An infinite ODE never naturally enters an outer tail, but an actual interrupt
branch still executes that tail after its own continuation.

### 9.8 Source skip and two distinct Type continuations

User blocks cannot end with bare ode(...). Write this even without substantive continuation:

```text
ode(..., delay(d)); skip
```

Two rules interpret this shape:

- Placeholder skip: try T-unrhd, prove safety/domain, omit the placeholder from
  interrupt continuations, and use Bottom as the deadline continuation.
- Real empty skip: try T-unrhd', prove safety/boundary, and check skip :: EmptyType.

Construction isolates both attempts and selects from proof outcomes. Both retain
candidate-tagged evidence, but only the selected candidate contributes to the
verdict. Unknown permits a provisional untrusted candidate under the common
policy. Finite non-skip Q uses only T-unrhd'. Distinct Bottom/Empty Type
continuations disambiguate identical source skips. Infinite delay has no natural
timeout and uses InfiniteDelayType(A).

---

## 10. Recursive Process construction

### 10.1 `Mu(X,P,invariant=I)`

Mu supports no observable outer sequential tail. Trailing skips are ignored.
Any remaining non-skip Q in Mu(...);Q is unsupported, gives an unknown structural
diagnostic, and prevents the parent Type. This is a missing derivation rule,
not an unresolved generated formula that permits continued Type construction.

At recursion entry, prove:

\[
\Phi\Rightarrow Def(I)\land I.
\]

Allocate a fresh Type variable independent of source names, such as t1, and record:

```text
X -> (TypeVar("t1"), invariant I)
```

The body starts with fresh symbols for every Gamma scalar and this abstract path,
instead of the current concrete state:

\[
\widehat H\land I\land Def(I)\land TypeDomain(\Gamma,\rho_{rec}).
\]

Here \(\rho_{rec}\) is the fresh recursion-entry symbol map. The path models any
iteration entry satisfying the invariant, without prior assignment history.

### 10.2 `Var(X)`

At a back edge, require:

1. X is bound in rec_env.
2. No non-skip tail follows Var(X); explicit/default X;skip remains tail position.
3. Reestablish the invariant from the current path:

\[
\Phi_{body}\Rightarrow Def(I)\land I.
\]

After proof, Var(X) becomes the corresponding TypeVar("t1").

### 10.3 Retaining MuType

After deriving the body Type:

- If t1 occurs, verify every occurrence is guarded by InputType/OutputType,
  then construct MuType("t1",body_type).
- Otherwise return body_type without a redundant Mu wrapper.

Delay, internal choice, and parallel composition are not communication guards;
only input/output prefixes set under_communication to true.

---

## 11. Formal Type AST normalization

Constructors maintain these forms:

1. Normal completion is EmptyType.
2. Bottom is unreachable behavior in finite T-unrhd/infinite delay; failure remains None/failure evidence.
3. Empty/single/multiple external choices use NoInterrupt, Input/Output, or ExternalChoice.
4. Nested InternalChoice preserves grouping and order, without flattening/sorting.
5. Finite delay always uses FiniteDelayType(d,A,T); paper abbreviations affect display only.
6. InfiniteDelayType(A) has fixed unreachable Bottom continuation.
7. ParallelType flattens but does not sort.
8. Mu binders permit alpha renaming.

types_equivalent compares canonical structure ignoring Mu binder names. It does not implement:

- Choice commutativity.
- Parallel commutativity.
- Subtyping.
- Behavioral bisimulation.
- Semantic equivalence of channel refinements.

Exact Fractions give 1, 1.0, and Fraction(1,1) the same normalized delay key.

---

## 12. Three proof-obligation categories

### 12.1 State premise

T-sigma substitutes concrete state into the prepared local path and proves
\(\widehat H\Rightarrow\widehat\Phi_i[\sigma]\). Undeclared names, vector labels, and parameter state
keys fail. Omitted Gamma values remain universally quantified with parameters.

### 12.2 FOL premise

Z3 checks validity through negation:

\[
valid(F)\quad\text{iff}\quad unsat(\neg F).
\]

- unsat: true.
- sat: false, retaining a counterexample model.
- unknown/timeout: unknown.

### 12.3 dL premise

dL goes to configured KeYmaera X or an internally injected dl_checker.
Syntactically true safety/domain can be discharged locally. Missing backends,
unsupported translation, timeout, and incomplete proofs conservatively give unknown.

False prevents Type construction for the rule. Unknown retains a required proof
without preventing candidate structure; only all-true final Types are trusted.

---

## 13. Final verdict and partial results

The final verdict combines:

1. Active proof obligations of the selected derivation.
2. Diagnostics participating in its result.

Priority is:

\[
false > unknown > true.
\]

Verdict aggregation and existence of a complete Type are separate:

- A false necessary premise short-circuits, usually leaving constructed_type=None.
- Unknown formula premises continue; completed structure yields verdict=unknown
  and a nonempty complete untrusted candidate.
- Unsupported rule expansion can also give unknown with constructed_type=None.
- Valid Types may contain Bottom as unreachable behavior, never construction failure.

The public facade does not return unknown candidates normally. Complete candidates
raise HCSPUntrustedTypeConstructionError with error.untrusted_type; incomplete
results raise HCSPTypeConstructionError. Full reports retain actual formulas and verdicts.

### 13.1 Structured errors

HCSPTypeConstructionError provides stable fields:

- kind: TypeConstructionErrorKind, with environment, derivation, proof-failed, or proof-unknown.
- phase: environment, rule-derivation, or proof.
- rule/location: primary failing judgment.
- partial_types: component Types completed before stopping.
- details: participating HCSPErrorDetail records, including FOL/dL kind,
  submitted formula, and backend explanation for proof failures.

A complete candidate with unknown proofs uses HCSPUntrustedTypeConstructionError
with kind=proof-unknown and untrusted_type. Lexical/syntax/validation failures
instead stop the frontend immediately with HCSPInputError and source location/caret.

---

## 14. Small complete examples

### 14.1 `ch?x; ch!x`

With empty initial Gamma and a Real channel ch:

1. T-In creates fresh r, Gamma={x:Real}, and symbols[x]=r.
2. Add the input refinement to the path.
3. T-Out reads r and proves the output refinement.
4. Terminate with EmptyType.
5. Wrap the result:

```python
InfiniteDelayType(
    InputType("ch", InfiniteDelayType(OutputType("ch", EmptyType())))
)
```

Displayed as:

```text
type forever interrupt angelic {
    ch? -> forever interrupt angelic {ch! -> empty}
}
```

### 14.2 `x := x + 1; ch!x`

For symbols[x]=x0, assignment gives:

\[
symbols[x]=x0+1.
\]

T-Out reads x0+1 and proves refinement on the updated value. Assignment adds
no behavioral prefix; the final Type retains only:

```text
type forever interrupt angelic {ch! -> empty}
```

### 14.3 `if B then ch1!0 else ch2!0`

Derive branches under \(\Phi\land B\) and \(\Phi\land\neg B\), producing:

```python
InternalChoiceType((
    InfiniteDelayType(OutputType("ch1", EmptyType())),
    InfiniteDelayType(OutputType("ch2", EmptyType())),
))
```

### 14.4 Finite ODE without interrupts and with natural continuation

For an empty event set, tail Type T, and uniquely selected timeout candidate:

```python
make_delay_type(d, NoInterruptType(), T)
```

The canonical result is:

```python
FiniteDelayType(d, NoInterruptType(), T)
```

---

## 15. Implementation choices requiring particular review

These are concrete choices affecting comparison with the paper:

1. Sequence passes remaining nodes; there is no generic type-level sequencing.
2. Assignment uses the old path and updated symbols, without postpredicate synthesis.
3. Actual T-Assign-post proves \(\Phi\Rightarrow\Phi\).
4. Input requires slot type <: declared target type; output requires payload type <: slot type.
5. Input assumes refinement; output proves it.
6. If/choice siblings are ordered. If, InternalChoice, and ODE own continuations.
   False/structural failure stops siblings; unknown formulas do not.
7. ODE post-state uses fresh variables and B/safety abstraction, not analytic solutions.
8. Three ODE continuations use B∧safety, safety, and ¬B∧safety.
9. Safety/domain/boundary dL uses domain-free dynamics.
10. Bare final ODE is invalid. ODE;skip lowers to the ODE field and isolates
    T-unrhd/T-unrhd'; non-skip successors use only prime.
11. InfiniteDelayType fixes unreachable Bottom outside ordinary mutable fields.
12. Recursive bodies start from a fresh invariant-only abstract state.
13. Formal Type equivalence ignores binder renaming but preserves choice/parallel order.
