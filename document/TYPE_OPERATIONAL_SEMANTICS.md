# Normalized Types and Table 3 transition graphs

Interface 3 converts an existing formal Type AST to normalized states and
enumerates reachable transitions under Section 4.4, Table 3. Its scope includes
normalized data structures, cyclic-term-graph identity, one-step semantics, and
complete graph generation. Interface 4 analyzes lock freedom, Bottom-error freedom,
and behavioral correctness separately; see [Lock and Bottom-error analysis](TYPE_LOCK_ANALYSIS.md).
General termination and other graph properties are outside the current scope.
Graph construction does not reprove a Type's correspondence to an HCSP Process;
obtain a trusted Type from construction or verify it through checking first.

## Stable interface

See the [Public API guide](PUBLIC_API_GUIDE.md#5-transition-graph-interface) for graph fields,
error categories, limits, and traversal examples. This page explains normalization,
equi-recursive identity, and the Table 3 backend.

```python
from hcsp_typechecker import (
    HCSPTypeTransitionGraphError,
    TypeAST,
    TypeTransitionGraph,
    TypeTransitionGraphErrorKind,
    build_type_transition_graph,
)

graph: TypeTransitionGraph = build_type_transition_graph(
    type_ast,
    output="full",
)
```

`result` prints graph size and the initial normalized Type; the `full` example
above prints all states, labels, and rule evidence. Normalized Type output has
no parser and is not user Type input; see
[Read-only normalized Type syntax](NORMALIZED_TYPE_OUTPUT_SYNTAX.md).

See [Read-only graph syntax](TYPE_TRANSITION_GRAPH_OUTPUT_SYNTAX.md) for complete graph text.

The complete signature is:

```text
build_type_transition_graph(
    type_ast: TypeAST,
    *,
    max_states: int | None = None,
    max_transitions: int | None = None,
    output: OutputMode | str = OutputMode.NONE,
    stream: TextIO | None = None,
) -> TypeTransitionGraph
```

Limits must be positive integers or `None`. Invalid Type roots, invalid options,
normalization failures, and exceeded limits become `HCSPTypeTransitionGraphError`
with stable `kind`/`phase` values. Exceeding a limit gives `size-limit` without a
partial graph. Input must be a `TypeAST` configuration root, not Type text,
a Process AST, or a normalized AST. To use supplied Type text, include it in
complete input to `check_hcsp_type(...)` first.

`result` prints the compact error category, phase, and reason; `full` also prints
the input Type and progress through root validation, option validation,
normalization, and graph traversal. `none` prints nothing. Exception fields remain
available: `kind`, `phase`, `reason`, `details`, plus `limit_name/limit` for size
errors or `option_name/option_value` for invalid options. Only expected user-input
and resource-limit failures are wrapped; internal programming defects propagate.

## Data structures and backend boundaries

```text
data_structures/
├── type_ast/                  Original Type AST
├── normalized_type_ast/       Table 3 normalized AST and one-way conversion
├── regular_type_term_graph/   Finite cyclic term graphs and equi-recursive keys
└── type_transition_graph/     States, edges, labels, and derivation evidence

backend/
└── type_operational_semantics/
    ├── regular_tree.py        Term graphs, bisimulation minimization, and stable keys
    ├── table3.py              All one-step transitions on cyclic term graphs
    └── graph_builder.py       BFS closure and merging evidence for identical edges

frontend/
├── normalized_type_syntax/    Read-only normalized Type presentation
└── type_transition_graph_syntax/  Read-only states, edges, labels, and rule evidence
```

Data structures do not import backends. Table 3 algorithms are separate from
construction/checking and do not depend on Gamma, Theta, parameters, or provers.

The data flow is:

```text
Formal Type AST
    -> Normalized Type AST
    -> Finite cyclic RegularTypeTermGraph
    -> Bisimulation-minimized EquiRecursiveStateKey
    -> Table 3 one-step successors
    -> Complete reachable closure by BFS
    -> TypeTransitionGraph
```

`EquiRecursiveStateKey` determines equality and rule execution. Each `TypeState`'s
normalized AST is deterministically reconstructed for display and is not used
to deduplicate states.

## One-way normalization

The project provides only:

```text
normalize_type_ast(TypeAST) -> NormalizedConfigurationType
```

There is no inverse conversion to the original Type AST. Original ASTs serve user
syntax, construction, and checking; normalized ASTs serve graph construction.

A normalized configuration root stores a nonempty, stably sorted tuple of Process
components. One component is sequential; multiple components are parallel.
Normal empty configuration contains exactly one `NormalizedEmptyType`. If any
parallel root is `NormalizedBottomType`, the whole configuration is error-terminated.

## Normalized equivalence

Parallel composition applies:

- Associative flattening.
- Commutative sorting.
- Removal of the `EmptyType` identity.
- Preservation of duplicate components; parallel composition is not idempotent.

Internal choice applies:

- Associative flattening.
- Commutative sorting.
- Idempotent deduplication.
- Replacement by the sole branch when deduplication leaves one.

External choice applies:

- Commutative sorting.
- Idempotent removal of identical communication branches.
- NoInterrupt, Input/Output, or ExternalChoice nodes for zero, one, or multiple branches.

Recursion removes variable names in favor of De Bruijn indices. Free TypeVars are
rejected. Finite zero delays, Bottom nodes, and Empty internal-choice branches
retain their operational significance and are not removed prematurely.

Normalized ASTs are finite syntax trees, so Python structural equality still
distinguishes `mu t.T` from `T[mu t.T/t]`. Table 3 operates on the next representation,
a finite cyclic term graph, ensuring folded/unfolded spellings have the same outgoing behavior.

## Equi-recursive regular-tree state keys

Graph deduplication builds a further representation above normalized ASTs:

1. Resolve each `mu` binder and De Bruijn reference to directed back edges.
2. Build a finite cyclic `RegularTypeTermGraph` without `mu`/TypeVar nodes.
3. Compute the greatest bisimulation partition and minimize its quotient graph.
4. Reapply flattening, commutativity, and idempotence to choices.
5. Remove Empty root identities and sort roots while preserving parallel multiplicity.
6. Freeze a hashable `EquiRecursiveStateKey`.

Thus `mu t.T`, `T[mu t.T/t]`, and any finite unfolding share a state identifier.
Channel names, directions, durations, sequential structure, and parallel multiplicity
remain observable and are not merged by the quotient. The minimal term graph is
both state key and Table 3 execution state. A deterministic De Bruijn `mu` display
AST is reconstructed for output only.

## Graph model

`TypeTransitionGraph` stores:

- `initial_state`: the initial state identifier.
- `states`: consecutively numbered `TypeState` objects, each with a normalized
  display AST reconstructed from its term graph.
- `transitions`: a tuple of `TypeTransition` objects.

Only fully enumerated graphs are returned. Exceeding a state or transition limit
raises immediately, without returning intermediate results that could be mistaken
for complete closure.

There are two label categories:

- `SilentTransitionLabel`: zero-time `mathcal T -> mathcal T'`.
- `TimedTransitionLabel(duration, ready)`: a `d,R` timed transition.

Finite durations use exact `Fraction` values; infinity uses `InfiniteTime.VALUE`.
Ready sets are `frozenset[ReadyAction]`, with channel and input/output direction per action.

One edge can retain multiple `TransitionDerivation` records. When different
component/branch combinations produce the same source, label, and target, graph
structure is merged while distinct Table 3 rule instances remain available for review.

Evidence `component_indices` refers to the source state's displayed normalized
parallel components; `branch_indices` refers to their displayed internal-choice
or Angelic branches. Internal graph numbering differs from reconstructed AST
ordering, so the backend explicitly maps positions before printing. Duplicate
parallel components retain separate positions even when sharing a term-graph node.
Communication evidence pairs the two index tuples position by position.

## Table 3 one-step rules

For each minimal cyclic term graph, the backend enumerates:

1. Check roots first: any Bottom root globally stops the configuration, yielding no edges.
2. Every distinct non-Bottom internal-choice branch.
3. Zero-delay timeouts whose natural continuation is not Bottom. A Bottom
   continuation permits only Angelic communication; otherwise the component
   remains at an error boundary.
4. Every complementary communication-branch pairing between two parallel components.
5. The unique next-critical-deadline time step when joint waiting is permitted.

Rule evidence maps to these operations:

| `Table3Rule` | Operation | Label |
|---|---|---|
| `P-unrhd` | Synchronize same-channel opposite-direction interrupts of two components | `tau` |
| `P-triangleright` | Finite delay reaches 0 with non-Bottom natural continuation | `tau` |
| `P-sqcup` | Select a non-Bottom internal-choice branch | `tau` |
| `P-unrhd-prime` | Advance one waiting component by the critical duration | `time(d,R)` |
| `P-parallel` | Joint waiting, with one time-step premise per component | `time(d,R)` |

Bottom records an error and remains in normalized states. Once it is a parallel
root, no component may choose, communicate, time out, or advance time. Empty
represents normal completion and is removed as a parallel identity, allowing
other components to proceed. If all components complete, the unique Empty root has no edges.

`[P-mu]` is compiled into term-graph back edges. A communication continuation may
return directly to an existing node without building a temporary
`T[mu t.T/t]` AST. Edge evidence records actual choice, communication, timeout,
or time rules, omitting administrative recursion-unfolding steps.

When zero-delay timeout and boundary communication both satisfy their premises,
both edges are retained.

## Critical deadlines

If every nonempty component can wait and no complementary actions exist across
their ready sets, choose the smallest positive finite remaining delay. Advance
all components by that duration: subtract it from finite delays and leave infinite delays unchanged.

If every component has infinite delay, generate an infinite-time edge. Bottom
roots stop globally before time rules are considered. Zero-delay, internal-choice,
or other non-waiting components prevent a joint time edge. Available complementary
communication also prevents time from advancing past that synchronization point.

The paper permits any positive `d` satisfying the premises. This implementation
uses a state-space reduction: retain only the time edge reaching the earliest
finite deadline, since shorter steps introduce no new discrete choice point.
At that deadline, apply timeout, communication, or the next joint time step.
This is the interface's explicit reduced semantics, rather than enumeration of
every arbitrary-duration paper transition.

## Graph traversal

BFS uses minimal `EquiRecursiveStateKey` objects as execution states. After each
step, target term graphs discard unreachable nodes, are minimized, and become
target keys. Visited recursive states form back edges instead of copied syntax
trees. `TypeState` ASTs serve display only. Traversal finishes when the queue is
empty; exceeding a state/edge limit aborts the entire construction with a size error.

For multiple component/branch combinations with identical source, label, and
target, BFS stores one edge with all distinct `TransitionDerivation` records in
`derivations`. This compresses duplicate graph structure without losing
nondeterministic rule instances. States and edges follow stable construction order.
