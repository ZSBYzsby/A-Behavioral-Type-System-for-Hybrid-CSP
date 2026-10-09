# Interface 4: lock and Bottom-error analysis of Type graphs

This page explains how the code implements deadlock freedom, livelock freedom,
and lock freedom from Definitions 4.5--4.7 on a complete `TypeTransitionGraph`
returned by interface 3. It also covers the project's Bottom-error freedom and
combined behavioral correctness, including data structures, algorithms,
counterexamples, complexity, and implementation boundaries.

## 1. Interface contract

```python
from hcsp_typechecker import analyze_type_lock_freedom

report = analyze_type_lock_freedom(graph, output="result")
```

The input must be the complete reachable graph returned by
`build_type_transition_graph(type_ast)`. A valid analysis returns a
`LockFreedomReport`; deadlock, livelock, and Bottom errors are ordinary property
results. A non-graph input raises `invalid-graph`; states unreachable from the
initial state cause `incomplete-graph`. The interface can verify stored-state
reachability, but cannot infer whether someone manually deleted a required
Table 3 edge. Completeness therefore relies on the graph coming from interface 3.

## 2. Mathematical criteria

### 2.1 Deadlock

A state `S` is a deadlock witness source exactly when the graph contains
`S -- time(infinity, ready=R) --> S'` with nonempty `R`, implementing Definition 4.5.
An `EmptyType` or `BottomType` state without outgoing edges is not such a deadlock.
Their Table 3 meanings differ: all Empty components mean normal completion;
any Bottom parallel root means error termination of the whole configuration and
prevents the other components from moving. `lock_free` concerns Definitions 4.5/4.6
and does not reclassify Bottom termination as deadlock.
`time(infinity, ready={})` also fails the nonempty-ready criterion.

### 2.2 Livelock

Retain only `SilentTransitionLabel` edges, displayed as `tau`. A directed cycle
in this reachable subgraph admits an infinite silent derivation `T ->^omega`,
as in Definition 4.6. The criterion is existential: a cycle with exit edges still
counts if execution can keep choosing the silent cycle. A cycle containing
positive-time edges is not a purely silent cycle.

### 2.3 Lock freedom

`report.lock_free` equals `report.deadlock_free and report.livelock_free`.
The counterexamples are searched independently and can coexist.

### 2.4 Bottom-error freedom and behavioral correctness

A state `S` is a Bottom-error state exactly when at least one component of its
normalized configuration root tuple is `NormalizedBottomType`. Only Bottom
nodes at parallel roots count. Bottom nested in a delay continuation,
communication continuation, or unselected branch does not cause a premature error.

`report.error_free` means no Bottom-error state is reachable. The combined property is:

```text
report.behavior_correct = report.lock_free and report.error_free
```

This extension preserves the paper's deadlock/livelock definitions. A terminal
Bottom state may have `lock_free=True`, but necessarily has `error_free=False`
and `behavior_correct=False`.

## 3. Reports and counterexamples

`LockFreedomReport` stores state/edge counts, five Boolean results, and optional
`deadlock_witness`, `livelock_witness`, and `bottom_error_witness` fields.
`TransitionPath` stores actual `TypeTransition` objects and validates that their
endpoints connect.

A deadlock witness consists of a shortest BFS `prefix` from the initial state to
the deadlock source and the final `infinite_wait` edge. A livelock witness contains
a `prefix` to the cycle entry and a nonempty, closed `cycle` of `tau` edges.
Each edge retains its label and Table 3 `derivations` for inspection.

A Bottom-error witness contains the shortest BFS `prefix` to the first error
state and `component_indices`, identifying all Bottom roots in that state's
displayed normalized parallel components.

## 4. Algorithms for large graphs

### 4.1 CSR outgoing-edge index

Two linear scans build a compressed sparse row index. The range
`offsets[s]..offsets[s+1]` contains state `s`'s outgoing edges, and `edge_ids`
preserves transition order. Compact integer arrays avoid duplicating Python
adjacency lists or dictionaries for each state.

### 4.2 BFS reachability, deadlock, and Bottom errors

BFS scans reachability, records parent edges for shortest prefixes, finds the
first deadlock edge and Bottom-error state, and checks reachable closure.
If fewer states are visited than stored, the interface rejects the graph and
returns no partial property conclusions.

### 4.3 Silent cycles with explicit-stack DFS

Livelock detection uses three-color DFS with explicit state and next-edge stacks.
A silent edge to an active ancestor identifies a cycle, reconstructed from DFS
parent edges and that back edge. Both BFS prefixes and DFS cycles are
reconstructed iteratively without recursive functions.

### 4.4 Complexity

For `|V|` states and `|E|` edges, time and auxiliary space are `O(|V|+|E|)`;
the Python call stack uses `O(1)` space. Regression tests include a 12,000-state
silent chain with a terminal self-loop, covering CSR, BFS, DFS, and long-prefix
reconstruction. Explicit-graph memory is the practical limit.

## 5. Output and errors

- `none`: no output.
- `result`: graph size, the five properties, and compact counterexamples.
- `full`: also prints reachable prefixes, infinite-wait edges, silent cycles,
  or Bottom-error states, with rule evidence and relevant normalized Types.

Full analysis output does not repeat the entire graph; interface 3's `full` mode
provides that. Invalid graphs raise `HCSPTypeLockAnalysisError`, exposing `kind`,
`phase`, `reason`, `details`, and `format_result()/format_full()`.
A false property result does not raise an exception.

## 6. Module locations

```text
hcsp_typechecker/
    data_structures/type_lock_analysis/   Reports, paths, and counterexamples
    backend/type_lock_analysis/           CSR, BFS, and explicit-stack DFS
    frontend/type_lock_analysis_syntax/   Read-only result/full presentation
    api.py                               Public arguments, errors, and output dispatch
```

Data structures do not depend on search backends, backends do not print, and the
presentation layer does not reevaluate properties. This follows the same
data-structure, backend, and frontend/facade layering as the first three interfaces.
